"""The live/paper trading loop: poll for new candles on every configured
instrument, manage open positions, and enforce the daily loss kill switch
and the max_open_positions cap."""
from __future__ import annotations

import time

import pandas as pd

from trading_bot.broker import build_broker
from trading_bot.config import Settings
from trading_bot.executor import OrderExecutor, StopFileTriggered, check_stop_file
from trading_bot.logger import get_logger
from trading_bot.market_data import build_market_data
from trading_bot.portfolio import Position, PositionStore
from trading_bot.risk import DailyLossKillSwitch, compute_stop_and_target, size_position
from trading_bot.session import is_near_session_close
from trading_bot.storage import TradeStore
from trading_bot.strategy import Signal, prepare, signal_for_row

log = get_logger(__name__)


def _get_balance(broker, dry_run: bool, fallback: float = 1000.0) -> float:
    if dry_run:
        # In dry-run there's no real account to size against; use a fixed
        # paper balance so the position-sizing math stays exercised.
        return fallback
    return broker.fetch_free_balance()


def run_loop(settings: Settings, max_iterations: int | None = None) -> None:
    exchange_client = None
    if settings.exchange.provider == "ccxt":
        from trading_bot.exchange import ExchangeClient

        exchange_client = ExchangeClient(settings)

    market_data = build_market_data(settings, exchange_client)
    broker = build_broker(settings, exchange_client)

    store = TradeStore(db_path=f"{settings.runtime.state_dir}/trades.db")
    position_store = PositionStore(path=f"{settings.runtime.state_dir}/positions.json")
    executor = OrderExecutor(settings, broker, store)
    kill_switch = DailyLossKillSwitch(settings.risk, state_path=f"{settings.runtime.state_dir}/kill_switch.json")

    instruments = settings.exchange.effective_instruments()
    dry_run = settings.effective_dry_run

    log.info(
        "Starting trading loop for %s via provider=%s (dry_run=%s)",
        [i.symbol for i in instruments], settings.exchange.provider, dry_run,
    )
    if not dry_run:
        log.warning("LIVE TRADING IS ACTIVE - real orders with real funds will be placed.")

    positions = position_store.load_all()
    iterations = 0

    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        try:
            check_stop_file(settings)
            near_close = is_near_session_close(settings.session)
            balance = _get_balance(broker, dry_run)

            # Fetch + prepare every instrument once per cycle up front, so
            # the equity calc below and the entry/exit decisions after it
            # see a consistent snapshot instead of prices drifting mid-loop.
            prepared_by_symbol: dict[str, pd.DataFrame] = {}
            prices: dict[str, float] = {}
            for instrument in instruments:
                df = market_data.fetch_recent(instrument.symbol, settings.exchange.timeframe)
                if len(df) < 2:
                    continue
                prepared_by_symbol[instrument.symbol] = prepare(df, settings.strategy)
                prices[instrument.symbol] = float(prepared_by_symbol[instrument.symbol].iloc[-1]["close"])

            equity = balance + sum(
                pos.amount * prices[sym] for sym, pos in positions.items() if sym in prices
            )
            store.record_equity(equity)
            kill_triggered = kill_switch.update(equity)
            if kill_triggered:
                log.warning(
                    "Daily loss kill switch triggered (>= %.2f%% drawdown). No new entries today "
                    "- existing positions are still managed normally.",
                    settings.risk.max_daily_loss_pct,
                )

            # Exits are evaluated unconditionally - the kill switch and
            # session close only ever block opening *new* positions, never
            # managing ones that already exist.
            positions_changed = False
            for symbol in list(positions.keys()):
                if symbol not in prepared_by_symbol:
                    continue
                prepared = prepared_by_symbol[symbol]
                current_price = prices[symbol]
                position = positions[symbol]
                position.update_peak(current_price)
                positions_changed = True

                reason = position.exit_reason(current_price, trailing_stop_pct=settings.risk.trailing_stop_pct)
                if reason is None:
                    prev_row, curr_row = prepared.iloc[-2], prepared.iloc[-1]
                    if signal_for_row(prev_row, curr_row, settings.strategy) == Signal.SELL:
                        reason = "signal"
                if reason is None and near_close:
                    reason = "session_close"

                if reason is not None:
                    executor.place_order(symbol, "sell", position.amount, current_price, note=f"exit:{reason}")
                    del positions[symbol]

            if positions_changed:
                position_store.save_all(positions)

            # New entries: gated by the kill switch, session close, and
            # max_open_positions. balance_remaining is decremented locally
            # as orders are placed so several signals firing in the same
            # cycle can't all size against the same starting balance.
            if not kill_triggered and not near_close:
                balance_remaining = balance
                for instrument in instruments:
                    symbol = instrument.symbol
                    if symbol in positions or len(positions) >= settings.risk.max_open_positions:
                        continue
                    if symbol not in prepared_by_symbol:
                        continue

                    prepared = prepared_by_symbol[symbol]
                    prev_row, curr_row = prepared.iloc[-2], prepared.iloc[-1]
                    if signal_for_row(prev_row, curr_row, settings.strategy) != Signal.BUY:
                        continue

                    current_price = prices[symbol]
                    atr_value = float(curr_row["atr"]) if pd.notna(curr_row["atr"]) else 0.0
                    if atr_value <= 0:
                        continue
                    stop_loss, take_profit = compute_stop_and_target(current_price, atr_value, settings.strategy)
                    sized = size_position(balance_remaining, current_price, stop_loss, settings.risk)
                    if sized is None:
                        continue

                    executor.place_order(
                        symbol, "buy", sized.amount, current_price,
                        stop_loss=stop_loss, take_profit=take_profit, note="entry:signal",
                    )
                    positions[symbol] = Position(
                        symbol=symbol, amount=sized.amount, entry_price=current_price,
                        stop_loss=stop_loss, take_profit=take_profit,
                    )
                    position_store.save_all(positions)
                    balance_remaining -= sized.amount * current_price

        except StopFileTriggered as exc:
            log.warning(str(exc))
            break
        except Exception:
            log.exception("Unhandled error in trading loop iteration; will retry next cycle")

        if max_iterations is None or iterations < max_iterations:
            time.sleep(settings.runtime.poll_interval_seconds)
