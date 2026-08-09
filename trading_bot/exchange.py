"""Thin wrapper around ccxt so the rest of the bot never touches ccxt directly.

Centralizing this makes it easy to enforce testnet/sandbox mode, retries, and
consistent error handling in one place.
"""
from __future__ import annotations

import time
from typing import Any

import ccxt

from trading_bot.config import Settings
from trading_bot.logger import get_logger

log = get_logger(__name__)

RETRYABLE_ERRORS = (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout)


class ExchangeClient:
    """Wraps a ccxt exchange instance with retries and sandbox support."""

    def __init__(self, settings: Settings):
        self.settings = settings
        exchange_class = getattr(ccxt, settings.exchange.id)
        self._exchange: ccxt.Exchange = exchange_class(
            {
                "apiKey": settings.api_key,
                "secret": settings.api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": settings.exchange.market_type},
            }
        )
        if settings.exchange.use_testnet:
            try:
                self._exchange.set_sandbox_mode(True)
                log.info("Exchange sandbox/testnet mode enabled for %s", settings.exchange.id)
            except ccxt.NotSupported:
                log.warning(
                    "%s does not support ccxt sandbox mode; use_testnet has no effect",
                    settings.exchange.id,
                )

    def _with_retries(self, fn, *args, retries: int = 3, base_delay: float = 1.0, **kwargs) -> Any:
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                return fn(*args, **kwargs)
            except RETRYABLE_ERRORS as exc:
                last_exc = exc
                delay = base_delay * (2 ** (attempt - 1))
                log.warning(
                    "%s failed (attempt %d/%d): %s - retrying in %.1fs",
                    fn.__name__, attempt, retries, exc, delay,
                )
                time.sleep(delay)
        raise last_exc  # type: ignore[misc]

    def fetch_ohlcv(self, symbol: str, timeframe: str, since: int | None = None, limit: int = 500):
        return self._with_retries(self._exchange.fetch_ohlcv, symbol, timeframe, since, limit)

    def fetch_ticker(self, symbol: str):
        return self._with_retries(self._exchange.fetch_ticker, symbol)

    def fetch_balance(self):
        return self._with_retries(self._exchange.fetch_balance)

    def load_markets(self):
        return self._with_retries(self._exchange.load_markets)

    def create_market_order(self, symbol: str, side: str, amount: float):
        """Places a REAL order on the exchange. Callers must gate this behind
        the dry_run / live-trading authorization checks in executor.py -
        this method itself performs no safety checks."""
        return self._with_retries(
            self._exchange.create_order, symbol, "market", side, amount, retries=1
        )

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        return float(self._exchange.amount_to_precision(symbol, amount))

    def price_to_precision(self, symbol: str, price: float) -> float:
        return float(self._exchange.price_to_precision(symbol, price))
