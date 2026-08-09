"""The live/paper trading loop: poll for new candles, evaluate the
strategy, manage the open position, and enforce the daily loss kill switch."""
from __future__ import annotations

import time

import pandas as pd

from trading_bot.config import Settings
from trading_bot.exchange import ExchangeClient
from trading_bot.executor import OrderExecutor, StopFileTriggered, check_stop_file
from trading_bot.logger import get_logger
from trading_bot.portfolio import Position, PositionStore
from trading_bot.risk import DailyLossKillSwitch, compute_stop_and_target, size_position
from trading_bot.storage import TradeStore
from trading_bot.strategy import Signal, prepare, signal_for_row

log = get_logger(__name__)

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def _fetch_recent_df(exchange: ExchangeClient, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    rows = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    return pd.DataFrame(rows, columns=OHLCV_COLUMNS)


def _get_quote_balance(exchange: ExchangeClient, quote_ccy: str, dry_run: bool, fallback: float = 1000.0) -> float:
    if dry_run:
        # In dry-run there's no real account to size against; use a fixed
        # paper balance so backtona-style sizing math stays exercised.
        return fallback
    balance = exchange.fetch_balance()
    return float(balance.get("free", {}).get(quote_ccy, 0.0))


def run_loop(settings: Settings, max_iterations: int | None = None) -> None:
    exchange = ExchangeClient(settings)
    store = TradeStore()
    position_store = PositionStore()
    executor = OrderExecutor(settings, exchange, store)
    kill_switch = DailyLossKillSwitch(settings.risk)

    symbol = settings.exchange.symbol
    quote_ccy = symbol.split("/")[-1]
    dry_run = settings.effective_dry_run

    log.info(
        "Starting %s trading loop for %s on %s (dry_run=%s)",
        settings.exchange.market_type, symbol, settings.exchange.id, dry_run,
    )
    if not dry_run:
        log.warning("LIVE TRADING IS ACTIVE - real orders with real funds will be placed.")

    position = position_store.load()
    iterations = 0

    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        try:
            check_stop_file(settings)

            df = _fetch_recent_df(exchange, symbol, settings.exchange.timeframe)
            if len(df) < 2:
                time.sleep(settings.runtime.poll_interval_seconds)
                continue

            prepared = prepare(df, settings.strategy)
            current_price = float(prepared.iloc[-1]["close"])
            balance = _get_quote_balance(exchange, quote_ccy, dry_run)
            equity = balance if position is None else balance + position.amount * current_price

            store.record_equity(equity)
            if kill_switch.update(equity):
                log.warning(
                    "Daily loss kill switch triggered (>= %.2f%% drawdown). Holding, no new entries today.",
                    settings.risk.max_daily_loss_pct,
                )
            else:
                if position is not None:
                    reason = position.exit_reason(current_price)
                    if reason is None:
                        prev_row, curr_row = prepared.iloc[-2], prepared.iloc[-1]
                        if signal_for_row(prev_row, curr_row, settings.strategy) == Signal.SELL:
                            reason = "signal"

                    if reason is not None:
                        executor.place_order(
                            symbol, "sell", position.amount, current_price, note=f"exit:{reason}"
                        )
                        position = None
                        position_store.save(None)

                elif not kill_switch.triggered:
                    prev_row, curr_row = prepared.iloc[-2], prepared.iloc[-1]
                    sig = signal_for_row(prev_row, curr_row, settings.strategy)
                    if sig == Signal.BUY:
                        atr_value = float(curr_row["atr"]) if pd.notna(curr_row["atr"]) else 0.0
                        if atr_value > 0:
                            stop_loss, take_profit = compute_stop_and_target(
                                current_price, atr_value, settings.strategy
                            )
                            sized = size_position(balance, current_price, stop_loss, settings.risk)
                            if sized is not None:
                                executor.place_order(
                                    symbol, "buy", sized.amount, current_price,
                                    stop_loss=stop_loss, take_profit=take_profit, note="entry:signal",
                                )
                                position = Position(
                                    symbol=symbol, amount=sized.amount, entry_price=current_price,
                                    stop_loss=stop_loss, take_profit=take_profit,
                                )
                                position_store.save(position)

        except StopFileTriggered as exc:
            log.warning(str(exc))
            break
        except Exception:
            log.exception("Unhandled error in trading loop iteration; will retry next cycle")

        if max_iterations is None or iterations < max_iterations:
            time.sleep(settings.runtime.poll_interval_seconds)
