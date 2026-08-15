import pandas as pd

import trading_bot.runner as runner_module
from trading_bot.config import ExchangeConfig, InstrumentConfig, RiskConfig, RuntimeConfig, Settings
from trading_bot.portfolio import Position
from trading_bot.strategy import Signal


def _df(close: float, rows: int = 3) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": list(range(rows)),
        "open": [close] * rows, "high": [close] * rows, "low": [close] * rows,
        "close": [close] * rows, "volume": [1] * rows,
    })


class FakeMarketData:
    """Always returns a flat series at a fixed price per symbol - real
    signal computation is monkeypatched out in these tests, so only the
    last close price and having >=2 rows matters."""

    def __init__(self, prices: dict[str, float]):
        self.prices = prices

    def fetch_recent(self, symbol, timeframe, limit=200):
        return _df(self.prices[symbol])


class FakeBroker:
    def __init__(self, balance: float = 1000.0):
        self.balance = balance
        self.orders: list[tuple[str, str, float]] = []

    def fetch_free_balance(self) -> float:
        return self.balance

    def create_market_order(self, symbol, side, amount):
        self.orders.append((symbol, side, amount))
        return {"average": None, "price": None}


def _fake_prepare(df, cfg):
    out = df.copy()
    out["atr"] = 2.0
    out["ema_fast"] = 1.0
    out["ema_slow"] = 1.0
    out["rsi"] = 50.0
    return out


def _settings(tmp_path, instruments, max_open_positions=1, risk_per_trade_pct=10.0, balance_fallback=None):
    risk = RiskConfig(
        risk_per_trade_pct=risk_per_trade_pct, max_daily_loss_pct=50.0,
        max_open_positions=max_open_positions, min_order_quote=1.0, taker_fee_pct=0.0,
    )
    settings = Settings(
        exchange=ExchangeConfig(provider="trading212", instruments=instruments),
        risk=risk,
        runtime=RuntimeConfig(state_dir=str(tmp_path), dry_run=False, poll_interval_seconds=0),
    )
    settings.live_trading_requested = True
    settings.live_trading_confirmed = True
    return settings


def _patch_common(monkeypatch, market_data, broker, signal=Signal.HOLD):
    monkeypatch.setattr(runner_module, "build_market_data", lambda settings, exchange_client=None: market_data)
    monkeypatch.setattr(runner_module, "build_broker", lambda settings, exchange_client=None: broker)
    monkeypatch.setattr(runner_module, "prepare", _fake_prepare)
    monkeypatch.setattr(runner_module, "signal_for_row", lambda prev, curr, cfg: signal)


def test_max_open_positions_caps_entries_across_symbols(tmp_path, monkeypatch):
    instruments = [InstrumentConfig(symbol="AAPL", t212_ticker="AAPL_US_EQ"),
                   InstrumentConfig(symbol="VOO", t212_ticker="VOO_US_EQ")]
    settings = _settings(tmp_path, instruments, max_open_positions=1)
    market_data = FakeMarketData({"AAPL": 10.0, "VOO": 10.0})
    broker = FakeBroker(balance=1000.0)
    _patch_common(monkeypatch, market_data, broker, signal=Signal.BUY)

    runner_module.run_loop(settings, max_iterations=1)

    assert len(broker.orders) == 1  # only one entry allowed despite two BUY signals


def test_balance_remaining_decreases_between_entries_in_same_cycle(tmp_path, monkeypatch):
    instruments = [InstrumentConfig(symbol="AAPL", t212_ticker="AAPL_US_EQ"),
                   InstrumentConfig(symbol="VOO", t212_ticker="VOO_US_EQ")]
    settings = _settings(tmp_path, instruments, max_open_positions=2)
    market_data = FakeMarketData({"AAPL": 10.0, "VOO": 10.0})
    broker = FakeBroker(balance=1000.0)
    _patch_common(monkeypatch, market_data, broker, signal=Signal.BUY)

    runner_module.run_loop(settings, max_iterations=1)

    assert len(broker.orders) == 2
    first_amount, second_amount = broker.orders[0][2], broker.orders[1][2]
    assert second_amount < first_amount  # sized against a smaller remaining balance


def test_kill_switch_blocks_new_entries_but_still_manages_exits(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone

    instruments = [InstrumentConfig(symbol="AAPL", t212_ticker="AAPL_US_EQ"),
                   InstrumentConfig(symbol="VOO", t212_ticker="VOO_US_EQ")]
    settings = _settings(tmp_path, instruments, max_open_positions=2)

    # Seed a much higher start-of-day equity so this cycle's drop trips the
    # kill switch (a fresh kill switch always uses its *first* reading as
    # the baseline, so it can never trigger on the very first call ever).
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (tmp_path / "kill_switch.json").write_text(json.dumps({
        "day": today, "start_equity": 1000.0, "triggered": False,
    }))

    # AAPL has an existing position whose stop-loss the current price has
    # breached; VOO has no position and a BUY signal fires for it too.
    from trading_bot.portfolio import PositionStore
    position_store = PositionStore(path=str(tmp_path / "positions.json"))
    position_store.save_all({
        "AAPL": Position(symbol="AAPL", amount=5.0, entry_price=10.0, stop_loss=9.0, take_profit=20.0),
    })

    market_data = FakeMarketData({"AAPL": 5.0, "VOO": 10.0})  # AAPL price below its stop_loss of 9.0
    # Equity (~26) crashes far below the seeded start-of-day equity (1000)
    # because of the AAPL mark-to-market loss, so the kill switch trips.
    broker = FakeBroker(balance=1.0)
    _patch_common(monkeypatch, market_data, broker, signal=Signal.BUY)

    runner_module.run_loop(settings, max_iterations=1)

    sells = [o for o in broker.orders if o[1] == "sell"]
    buys = [o for o in broker.orders if o[1] == "buy"]
    assert sells == [("AAPL", "sell", 5.0)]  # existing losing position still gets closed
    assert buys == []  # but no new VOO entry while the kill switch is tripped

    remaining = position_store.load_all()
    assert "AAPL" not in remaining
