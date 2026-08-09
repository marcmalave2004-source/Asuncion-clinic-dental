"""Order execution: the only place in the codebase that is allowed to place
a real order on the exchange, and it will refuse to unless every safety gate
agrees.
"""
from __future__ import annotations

from pathlib import Path

from trading_bot.config import Settings
from trading_bot.exchange import ExchangeClient
from trading_bot.logger import get_logger
from trading_bot.storage import TradeRecord, TradeStore

log = get_logger(__name__)


class LiveTradingNotAuthorized(RuntimeError):
    pass


class StopFileTriggered(RuntimeError):
    pass


def check_stop_file(settings: Settings) -> None:
    """A simple, foolproof kill switch: if a file named STOP exists in the
    working directory, the bot halts immediately. Faster and more reliable
    under stress than reaching for the right env var or process id."""
    if Path(settings.runtime.stop_file).exists():
        raise StopFileTriggered(
            f"Stop file '{settings.runtime.stop_file}' found - halting before placing any order."
        )


class OrderExecutor:
    def __init__(self, settings: Settings, exchange: ExchangeClient, store: TradeStore):
        self.settings = settings
        self.exchange = exchange
        self.store = store

    def _assert_live_authorized(self):
        if not self.settings.live_trading_authorized:
            raise LiveTradingNotAuthorized(
                "Live trading requires both LIVE_TRADING=true and "
                "LIVE_TRADING_CONFIRM=I_ACCEPT_THE_RISK in the environment, "
                "and runtime.dry_run: false in config.yaml."
            )

    def place_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price_hint: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        note: str = "",
    ) -> dict:
        check_stop_file(self.settings)
        dry_run = self.settings.effective_dry_run

        if dry_run:
            log.info(
                "[DRY RUN] %s %s amount=%.8f price~=%.2f sl=%s tp=%s note=%s",
                side.upper(), symbol, amount, price_hint, stop_loss, take_profit, note,
            )
            self.store.record_trade(
                TradeRecord(
                    symbol=symbol, side=side, amount=amount, price=price_hint,
                    stop_loss=stop_loss, take_profit=take_profit, dry_run=True, note=note,
                )
            )
            return {"dry_run": True, "symbol": symbol, "side": side, "amount": amount, "price": price_hint}

        self._assert_live_authorized()
        log.warning(
            "LIVE ORDER %s %s amount=%.8f price~=%.2f sl=%s tp=%s note=%s",
            side.upper(), symbol, amount, price_hint, stop_loss, take_profit, note,
        )
        amount_precise = self.exchange.amount_to_precision(symbol, amount)
        order = self.exchange.create_market_order(symbol, side, amount_precise)
        filled_price = float(order.get("average") or order.get("price") or price_hint)
        self.store.record_trade(
            TradeRecord(
                symbol=symbol, side=side, amount=amount_precise, price=filled_price,
                stop_loss=stop_loss, take_profit=take_profit, dry_run=False, note=note,
            )
        )
        return order
