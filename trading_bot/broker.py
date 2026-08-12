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


class Trading212Broker:
    def __init__(self, client, ticker: str):
        self.client = client
        self.ticker = ticker

    def fetch_free_balance(self) -> float:
        cash = self.client.get_account_cash()
        # Best-effort key lookup - confirm the exact response shape against
        # the official docs (see t212_client.py header) before relying on
        # this for live sizing decisions.
        return float(cash.get("free") or cash.get("cash") or 0.0)

    def create_market_order(self, symbol: str, side: str, amount: float) -> dict:
        signed_qty = amount if side == "buy" else -amount
        return self.client.place_market_order(self.ticker, signed_qty)


def build_broker(settings: Settings, exchange_client=None):
    """exchange_client is required (and only used) for provider == 'ccxt' -
    callers already have one for market data, so it's passed in rather than
    constructed twice."""
    if settings.exchange.provider == "trading212":
        from trading_bot.t212_client import Trading212Client

        if not settings.exchange.t212_ticker:
            raise ValueError("exchange.t212_ticker must be set in config.yaml for the trading212 provider")
        client = Trading212Client(
            api_key=settings.api_key,
            api_secret=settings.api_secret,
            environment=settings.exchange.t212_environment,
        )
        return Trading212Broker(client, settings.exchange.t212_ticker)

    if exchange_client is None:
        raise ValueError("exchange_client is required for the ccxt provider")
    quote_ccy = settings.exchange.symbol.split("/")[-1]
    return CcxtBroker(exchange_client, quote_ccy)
