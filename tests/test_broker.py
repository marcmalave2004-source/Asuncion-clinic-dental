from unittest.mock import MagicMock

import pytest

from trading_bot.broker import CcxtBroker, Trading212Broker, build_broker
from trading_bot.config import ExchangeConfig, Settings


def test_ccxt_broker_fetch_free_balance_reads_quote_currency():
    exchange = MagicMock()
    exchange.fetch_balance.return_value = {"free": {"USDT": 500.0, "BTC": 0.01}}
    broker = CcxtBroker(exchange, quote_ccy="USDT")
    assert broker.fetch_free_balance() == 500.0


def test_ccxt_broker_create_market_order_rounds_precision_first():
    exchange = MagicMock()
    exchange.amount_to_precision.return_value = 0.123
    exchange.create_market_order.return_value = {"id": "1"}
    broker = CcxtBroker(exchange, quote_ccy="USDT")

    broker.create_market_order("BTC/USDT", "buy", 0.123456)

    exchange.amount_to_precision.assert_called_once_with("BTC/USDT", 0.123456)
    exchange.create_market_order.assert_called_once_with("BTC/USDT", "buy", 0.123)


def test_trading212_broker_sells_use_negative_quantity():
    client = MagicMock()
    broker = Trading212Broker(client, ticker="AAPL_US_EQ")

    broker.create_market_order("AAPL", "sell", 3.0)

    client.place_market_order.assert_called_once_with("AAPL_US_EQ", -3.0)


def test_trading212_broker_buys_use_positive_quantity():
    client = MagicMock()
    broker = Trading212Broker(client, ticker="AAPL_US_EQ")

    broker.create_market_order("AAPL", "buy", 3.0)

    client.place_market_order.assert_called_once_with("AAPL_US_EQ", 3.0)


def test_trading212_broker_reads_free_cash_top_level():
    client = MagicMock()
    client.get_account_summary.return_value = {"free": 999.0}
    broker = Trading212Broker(client, ticker="AAPL_US_EQ")
    assert broker.fetch_free_balance() == 999.0


def test_trading212_broker_reads_free_cash_nested_under_cash_object():
    client = MagicMock()
    client.get_account_summary.return_value = {"cash": {"free": 500.0}, "invested": {"value": 1000.0}}
    broker = Trading212Broker(client, ticker="AAPL_US_EQ")
    assert broker.fetch_free_balance() == 500.0


def test_trading212_broker_raises_clear_error_when_no_known_field_found():
    client = MagicMock()
    client.get_account_summary.return_value = {"someUnexpectedField": 1}
    broker = Trading212Broker(client, ticker="AAPL_US_EQ")
    with pytest.raises(ValueError, match="Could not find a free-cash field"):
        broker.fetch_free_balance()


def test_build_broker_selects_trading212_and_requires_ticker():
    settings = Settings(exchange=ExchangeConfig(provider="trading212", t212_ticker=None))
    with pytest.raises(ValueError, match="t212_ticker"):
        build_broker(settings)


def test_build_broker_selects_ccxt_and_requires_exchange_client():
    settings = Settings(exchange=ExchangeConfig(provider="ccxt"))
    with pytest.raises(ValueError, match="exchange_client"):
        build_broker(settings, exchange_client=None)


def test_build_broker_ccxt_path_returns_ccxt_broker():
    settings = Settings(exchange=ExchangeConfig(provider="ccxt", symbol="BTC/USDT"))
    fake_exchange = MagicMock()
    broker = build_broker(settings, exchange_client=fake_exchange)
    assert isinstance(broker, CcxtBroker)
    assert broker.quote_ccy == "USDT"
