import base64
from unittest.mock import MagicMock

import pytest

from trading_bot.t212_client import Trading212Client, Trading212Error


def _client(api_secret=None):
    return Trading212Client(api_key="test-key", api_secret=api_secret, environment="demo")


def test_base_url_selected_by_environment():
    assert _client().base_url == "https://demo.trading212.com/api/v0"
    live = Trading212Client(api_key="k", environment="live")
    assert live.base_url == "https://live.trading212.com/api/v0"


def test_invalid_environment_rejected():
    with pytest.raises(ValueError):
        Trading212Client(api_key="k", environment="staging")


def test_auth_header_without_secret_sends_raw_key():
    client = _client(api_secret=None)
    assert client._auth_header() == {"Authorization": "test-key"}


def test_auth_header_with_secret_sends_basic_auth():
    client = _client(api_secret="test-secret")
    header = client._auth_header()
    expected_token = base64.b64encode(b"test-key:test-secret").decode()
    assert header == {"Authorization": f"Basic {expected_token}"}


def test_get_account_cash_hits_expected_endpoint(monkeypatch):
    client = _client()
    mock_response = MagicMock(status_code=200, ok=True, content=b'{"free": 1234.5}')
    mock_response.json.return_value = {"free": 1234.5}
    mock_request = MagicMock(return_value=mock_response)
    monkeypatch.setattr(client._session, "request", mock_request)

    result = client.get_account_cash()

    assert result == {"free": 1234.5}
    called_method, called_url = mock_request.call_args[0]
    assert called_method == "GET"
    assert called_url == "https://demo.trading212.com/api/v0/equity/account/cash"


def test_place_market_order_sends_signed_quantity(monkeypatch):
    client = _client()
    mock_response = MagicMock(status_code=200, ok=True, content=b"{}")
    mock_response.json.return_value = {}
    mock_request = MagicMock(return_value=mock_response)
    monkeypatch.setattr(client._session, "request", mock_request)

    client.place_market_order("AAPL_US_EQ", -5.0)

    _, kwargs = mock_request.call_args
    assert kwargs["json"] == {"ticker": "AAPL_US_EQ", "quantity": -5.0}


def test_401_raises_trading212_error_with_helpful_message(monkeypatch):
    client = _client()
    mock_response = MagicMock(status_code=401, ok=False, content=b"")
    monkeypatch.setattr(client._session, "request", MagicMock(return_value=mock_response))

    with pytest.raises(Trading212Error, match="401 Unauthorized"):
        client.get_account_cash()


def test_retryable_status_is_retried_then_succeeds(monkeypatch):
    client = _client()
    failing = MagicMock(status_code=503, ok=False, content=b"")
    success = MagicMock(status_code=200, ok=True, content=b"{}")
    success.json.return_value = {}
    mock_request = MagicMock(side_effect=[failing, success])
    monkeypatch.setattr(client._session, "request", mock_request)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    result = client.get_account_cash()

    assert result == {}
    assert mock_request.call_count == 2
