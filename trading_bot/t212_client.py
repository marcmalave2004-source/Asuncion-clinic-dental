"""REST client for the Trading 212 public API (Invest / Stocks ISA accounts
only - not available for CFD or SIPP accounts).

Verified against the official docs (docs.trading212.com/api), general
information section, as pasted in by the user on 2026-08-12:

- Auth: HTTP Basic Auth, API Key as username / API Secret as password
  (scheme "authWithSecretKey"). There's also a documented legacy scheme
  ("legacyApiKeyHeader") that sends the raw key in the Authorization header
  with no secret - this client uses Basic Auth whenever a secret is
  configured and falls back to the legacy raw-key header otherwise.
- Base URLs: https://demo.trading212.com/api/v0 (paper) and
  https://live.trading212.com/api/v0 (live).
- Orders execute only in the account's primary currency; multi-currency
  accounts are not supported by the API.
- Rate limits are per-account and vary per endpoint (see method docstrings);
  responses include x-ratelimit-* headers.

One thing that's still a best-effort guess: the exact JSON field names in
the /equity/account/summary response - the docs describe it narratively
("available funds, invested capital, total account value") without a
literal example payload. `Trading212Broker.fetch_free_balance` (broker.py)
therefore checks a few plausible key names and raises a clear error listing
the actual keys it saw if none match, rather than silently returning 0.
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
MAX_RATE_LIMIT_WAIT_SECONDS = 60.0


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

    def _retry_delay(self, resp: requests.Response, attempt: int) -> float:
        if resp.status_code == 429:
            reset_at = resp.headers.get("x-ratelimit-reset")
            if reset_at:
                try:
                    wait = float(reset_at) - time.time()
                    return max(0.5, min(wait, MAX_RATE_LIMIT_WAIT_SECONDS))
                except ValueError:
                    pass
        return 1.0 * (2 ** (attempt - 1))

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
                    "401 Unauthorized from Trading 212 API - double-check your "
                    "TRADING212_API_KEY/TRADING212_API_SECRET in .env and that the key "
                    "has the right permissions and environment (demo vs live)."
                )
            if resp.status_code in RETRYABLE_STATUS and attempt < retries:
                delay = self._retry_delay(resp, attempt)
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
        return self.get_account_summary()

    def get_account_summary(self) -> dict:
        """GET /equity/account/summary - rate limit: 1 req / 5s."""
        return self._request("GET", "/equity/account/summary")

    def get_positions(self) -> list:
        """GET /equity/positions - rate limit: 1 req / 1s."""
        return self._request("GET", "/equity/positions")

    def get_pending_orders(self) -> dict:
        """GET /equity/orders - rate limit: 1 req / 5s."""
        return self._request("GET", "/equity/orders")

    def place_market_order(self, ticker: str, quantity: float, extended_hours: bool = False) -> dict:
        """POST /equity/orders/market - rate limit: 50 req / 1m.
        quantity > 0 buys, quantity < 0 sells (T212 API convention)."""
        body = {"ticker": ticker, "quantity": quantity, "extendedHours": extended_hours}
        return self._request("POST", "/equity/orders/market", json=body)

    def cancel_order(self, order_id: str | int) -> None:
        """DELETE /equity/orders/{id} - rate limit: 50 req / 1m."""
        self._request("DELETE", f"/equity/orders/{order_id}")
