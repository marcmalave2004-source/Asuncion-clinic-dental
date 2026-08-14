"""The live/paper trading loop: poll for new candles, evaluate the
strategy, manage the open position, and enforce the daily loss kill switch."""
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

    store = TradeStore()
    position_store = PositionStore()
    executor = OrderExecutor(settings, broker, store)
    kill_switch = DailyLossKillSwitch(settings.risk)

    symbol = settings.exchange.symbol
    dry_run = settings.effective_dry_run

    log.info(
        "Starting trading loop for %s via provider=%s (dry_run=%s)",
        symbol, settings.exchange.provider, dry_run,
    )
    if not dry_run:
        log.warning("LIVE TRADING IS ACTIVE - real orders with real funds will be placed.")

    position = position_store.load()
    iterations = 0

    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        try:
            check_stop_file(settings)

            df = market_data.fetch_recent(symbol, settings.exchange.timeframe)
            if len(df) < 2:
                time.sleep(settings.runtime.poll_interval_seconds)
                continue

            prepared = prepare(df, settings.strategy)
            current_price = float(prepared.iloc[-1]["close"])
            balance = _get_balance(broker, dry_run)
            equity = balance if position is None else balance + position.amount * current_price

            store.record_equity(equity)
            if kill_switch.update(equity):
                log.warning(
                    "Daily loss kill switch triggered (>= %.2f%% drawdown). Holding, no new entries today.",
                    settings.risk.max_daily_loss_pct,
                )
            else:
                near_close = is_near_session_close(settings.session)

                if position is not None:
                    reason = position.exit_reason(current_price)
                    if reason is None:
                        prev_row, curr_row = prepared.iloc[-2], prepared.iloc[-1]
                        if signal_for_row(prev_row, curr_row, settings.strategy) == Signal.SELL:
                            reason = "signal"
                    if reason is None and near_close:
                        reason = "session_close"

                    if reason is not None:
                        executor.place_order(
                            symbol, "sell", position.amount, current_price, note=f"exit:{reason}"
                        )
                        position = None
                        position_store.save(None)

                elif not kill_switch.triggered and not near_close:
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
