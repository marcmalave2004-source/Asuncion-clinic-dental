"""REST client for the Trading 212 public API (Invest / Stocks ISA accounts
only - not available for CFD or SIPP accounts).

*** AUTHENTICATION IS UNVERIFIED - READ THIS BEFORE GOING LIVE ***
docs.trading212.com was unreachable from the environment this client was
written in, so the exact auth header format below was inferred from
third-party SDKs/reverse-engineering writeups that disagreed with each
other (single API key vs. an API key+secret pair with HTTP Basic Auth).
This client defaults to HTTP Basic Auth (api_key as username, api_secret as
password if one is configured) and falls back to sending the raw key in the
Authorization header when no secret is set.

Before trusting this with real money:
  1. Generate an API key in the Trading 212 app (Settings -> API) and note
     whether it gives you one key or a key+secret pair.
  2. Call `Trading212Client.verify_connection()` (wraps a read-only account
     endpoint) and confirm it returns your real account data.
  3. If it 401s, check docs.trading212.com/api yourself and adjust
     `_auth_header()` below to match - it's the only place auth happens.

Endpoint paths (account cash, market orders) are similarly best-effort from
secondary sources and should be cross-checked against the official docs.
"""
from __future__ import annotations

import base64
import time

import requests

from trading_bot.logger import get_logger

log = get_logger(__name__)

BASE_URLS = {
    "demo": "https://demo.trading212.com/api/v0",
    "live": "https://live.trading212.com/api/v0",
}

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class Trading212Error(RuntimeError):
    pass


class Trading212Client:
    def __init__(self, api_key: str, api_secret: str | None = None, environment: str = "demo"):
        if environment not in BASE_URLS:
            raise ValueError(f"environment must be one of {list(BASE_URLS)}, got {environment!r}")
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = BASE_URLS[environment]
        self.environment = environment
        self._session = requests.Session()

    def _auth_header(self) -> dict:
        if self.api_secret:
            token = base64.b64encode(f"{self.api_key}:{self.api_secret}".encode()).decode()
            return {"Authorization": f"Basic {token}"}
        return {"Authorization": self.api_key}

    def _request(self, method: str, path: str, retries: int = 3, **kwargs):
        url = f"{self.base_url}{path}"
        headers = {**self._auth_header(), "Content-Type": "application/json"}
        last_exc: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                resp = self._session.request(method, url, headers=headers, timeout=15, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                delay = 1.0 * (2 ** (attempt - 1))
                log.warning("T212 %s %s failed (attempt %d/%d): %s - retrying in %.1fs",
                            method, path, attempt, retries, exc, delay)
                time.sleep(delay)
                continue

            if resp.status_code == 401:
                raise Trading212Error(
                    "401 Unauthorized from Trading 212 API - the auth header format in "
                    "t212_client.py is unverified against the official docs; check "
                    "docs.trading212.com/api and adjust _auth_header() if needed."
                )
            if resp.status_code in RETRYABLE_STATUS and attempt < retries:
                delay = 1.0 * (2 ** (attempt - 1))
                log.warning("T212 %s %s returned %d - retrying in %.1fs",
                            method, path, resp.status_code, delay)
                time.sleep(delay)
                continue

            if not resp.ok:
                raise Trading212Error(f"T212 {method} {path} failed: {resp.status_code} {resp.text}")
            return resp.json() if resp.content else {}

        raise Trading212Error(f"T212 {method} {path} failed after {retries} attempts") from last_exc

    def verify_connection(self) -> dict:
        """Read-only sanity check - safe to call even against a live key."""
        return self.get_account_cash()

    def get_account_cash(self) -> dict:
        return self._request("GET", "/equity/account/cash")

    def get_portfolio(self) -> list:
        return self._request("GET", "/equity/portfolio")

    def place_market_order(self, ticker: str, quantity: float) -> dict:
        """quantity > 0 buys, quantity < 0 sells (T212 API convention)."""
        return self._request("POST", "/equity/orders/market", json={"ticker": ticker, "quantity": quantity})

    def cancel_order(self, order_id: str | int) -> None:
        self._request("DELETE", f"/equity/orders/{order_id}")
