"""Broker abstraction: fetch account balance and place orders, without the
rest of the bot needing to know whether it's talking to a crypto exchange
via ccxt or to Trading 212's REST API."""
from __future__ import annotations

from typing import Protocol

from trading_bot.config import Settings


class BrokerClient(Protocol):
    def fetch_free_balance(self) -> float: ...

    def create_market_order(self, symbol: str, side: str, amount: float) -> dict: ...


class CcxtBroker:
    def __init__(self, exchange, quote_ccy: str):
        self.exchange = exchange
        self.quote_ccy = quote_ccy

    def fetch_free_balance(self) -> float:
        balance = self.exchange.fetch_balance()
        return float(balance.get("free", {}).get(self.quote_ccy, 0.0))

    def create_market_order(self, symbol: str, side: str, amount: float) -> dict:
        amount_precise = self.exchange.amount_to_precision(symbol, amount)
        return self.exchange.create_market_order(symbol, side, amount_precise)


CASH_FIELD_CANDIDATES = ("availableToTrade", "free", "cash", "available", "availableFunds", "blended")


class Trading212Broker:
    def __init__(self, client, ticker_map: dict[str, str]):
        self.client = client
        self.ticker_map = ticker_map  # our display symbol (e.g. "AAPL") -> T212 instrument code

    def fetch_free_balance(self) -> float:
        summary = self.client.get_account_summary()
        # Confirmed against a real account's response on 2026-08-14:
        # {"id", "currency", "totalValue", "cash": {"availableToTrade",
        # "reservedForOrders", "inPies"}, "investments": {...}}. Checking a
        # short candidate list (with availableToTrade first) instead of a
        # single hardcoded key stays robust to minor response variations.
        cash_obj = summary.get("cash", summary) if isinstance(summary.get("cash"), dict) else summary
        for key in CASH_FIELD_CANDIDATES:
            if key in cash_obj:
                return float(cash_obj[key])
        raise ValueError(
            f"Could not find a free-cash field in the T212 account summary response. "
            f"Top-level keys were: {list(summary.keys())}. Inspect the real response "
            f"(e.g. via `check-broker`) and add the right key name to CASH_FIELD_CANDIDATES "
            f"in trading_bot/broker.py."
        )

    def create_market_order(self, symbol: str, side: str, amount: float) -> dict:
        if symbol not in self.ticker_map:
            raise ValueError(f"No t212_ticker configured for symbol {symbol!r} - check exchange.instruments")
        signed_qty = amount if side == "buy" else -amount
        return self.client.place_market_order(self.ticker_map[symbol], signed_qty)


def build_broker(settings: Settings, exchange_client=None):
    """exchange_client is required (and only used) for provider == 'ccxt' -
    callers already have one for market data, so it's passed in rather than
    constructed twice."""
    if settings.exchange.provider == "trading212":
        from trading_bot.t212_client import Trading212Client

        instruments = settings.exchange.effective_instruments()
        missing = [i.symbol for i in instruments if not i.t212_ticker]
        if missing:
            raise ValueError(f"t212_ticker must be set for every instrument - missing for: {missing}")
        ticker_map = {i.symbol: i.t212_ticker for i in instruments}

        client = Trading212Client(
            api_key=settings.api_key,
            api_secret=settings.api_secret,
            environment=settings.exchange.t212_environment,
        )
        return Trading212Broker(client, ticker_map)

    if exchange_client is None:
        raise ValueError("exchange_client is required for the ccxt provider")
    quote_ccy = settings.exchange.symbol.split("/")[-1]
    return CcxtBroker(exchange_client, quote_ccy)
