"""Market data providers.

Trading 212's public API does not expose historical/candle price data (only
account, instruments and orders), so when trading via T212 the strategy's
OHLCV input has to come from somewhere else. Yahoo Finance (via the
`yfinance` package) is a free, no-API-key source that covers most stocks and
ETFs and is the default paired with the Trading 212 broker.

Both providers expose the same two methods so strategy.py / backtester.py /
runner.py never need to know which one is in use.
"""
from __future__ import annotations

from typing import Protocol

import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

# Approx bars/day per Yahoo Finance interval, used to size lookback windows.
_BARS_PER_DAY = {
    "1m": 390, "2m": 195, "5m": 78, "15m": 26, "30m": 13,
    "60m": 7, "1h": 7, "1d": 1,
}
# Yahoo Finance's own retention limits per intraday interval (days).
_MAX_LOOKBACK_DAYS = {
    "1m": 7, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "60m": 730, "1h": 730,
}
_TIMEFRAME_TO_YF_INTERVAL = {"1h": "60m"}


class MarketDataProvider(Protocol):
    def fetch_recent(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame: ...

    def fetch_historical(self, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> pd.DataFrame: ...


class CcxtMarketData:
    """Wraps an ExchangeClient's fetch_ohlcv so it satisfies MarketDataProvider."""

    def __init__(self, exchange):
        self.exchange = exchange

    def fetch_recent(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        rows = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        return pd.DataFrame(rows, columns=OHLCV_COLUMNS)

    def fetch_historical(self, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> pd.DataFrame:
        import time as _time

        all_rows: list[list[float]] = []
        cursor = since_ms
        while cursor < until_ms:
            batch = self.exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000)
            if not batch:
                break
            all_rows.extend(batch)
            last_ts = batch[-1][0]
            if last_ts <= cursor or len(batch) < 2:
                break
            cursor = last_ts + 1
            _time.sleep(self.exchange._exchange.rateLimit / 1000.0)

        df = pd.DataFrame(all_rows, columns=OHLCV_COLUMNS)
        df = df[(df["timestamp"] >= since_ms) & (df["timestamp"] <= until_ms)]
        return df.drop_duplicates(subset="timestamp").reset_index(drop=True)


def _yf_interval(timeframe: str) -> str:
    return _TIMEFRAME_TO_YF_INTERVAL.get(timeframe, timeframe)


def _lookback_days(timeframe: str, limit: int) -> int:
    per_day = _BARS_PER_DAY.get(timeframe, 7)
    needed = max(2, int(limit / per_day) + 2)
    cap = _MAX_LOOKBACK_DAYS.get(timeframe)
    return min(needed, cap) if cap else needed


def _normalize_yf(raw: "pd.DataFrame") -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    out = raw.copy()
    # yfinance can return MultiIndex columns (ticker, field) even for a
    # single symbol depending on version; flatten to the field name.
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)

    out = out.reset_index()
    time_col = "Datetime" if "Datetime" in out.columns else "Date"
    out = out.rename(
        columns={
            time_col: "timestamp", "Open": "open", "High": "high",
            "Low": "low", "Close": "close", "Volume": "volume",
        }
    )
    # .dt.as_unit("ms") pins the resolution explicitly before casting to int -
    # pandas' default datetime64 resolution changed from ns (<=2.x) to us
    # (3.x), so a bare .astype("int64") // 1_000_000 silently produces
    # seconds instead of milliseconds depending on the installed pandas version.
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True).dt.as_unit("ms").astype("int64")
    return out[OHLCV_COLUMNS]


class YFinanceMarketData:
    """Fetches OHLCV for stocks/ETFs from Yahoo Finance.

    Note: Yahoo Finance limits how far back intraday data can be requested
    (e.g. ~60 days for 5m/15m/30m bars). Daily ("1d") bars have effectively
    no such limit and are the more realistic choice for a Trading 212 style
    swing/position strategy anyway - T212 (Invest/ISA) is not built for
    high-frequency intraday trading.
    """

    def __init__(self, symbol_overrides: dict[str, str] | None = None):
        self.symbol_overrides = symbol_overrides or {}  # our display symbol -> Yahoo ticker, when they differ

    def _resolve_symbol(self, symbol: str) -> str:
        return self.symbol_overrides.get(symbol, symbol)

    def fetch_recent(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        import yfinance as yf

        days = _lookback_days(timeframe, limit)
        raw = yf.download(
            self._resolve_symbol(symbol), period=f"{days}d", interval=_yf_interval(timeframe),
            progress=False, auto_adjust=False,
        )
        df = _normalize_yf(raw)
        return df.tail(limit).reset_index(drop=True)

    def fetch_historical(self, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> pd.DataFrame:
        import yfinance as yf

        start = pd.to_datetime(since_ms, unit="ms", utc=True)
        end = pd.to_datetime(until_ms, unit="ms", utc=True)
        raw = yf.download(
            self._resolve_symbol(symbol), start=start, end=end, interval=_yf_interval(timeframe),
            progress=False, auto_adjust=False,
        )
        df = _normalize_yf(raw)
        return df[(df["timestamp"] >= since_ms) & (df["timestamp"] <= until_ms)].reset_index(drop=True)


def build_market_data(settings, exchange_client=None) -> MarketDataProvider:
    """exchange_client is required (and only used) for provider == 'ccxt'."""
    if settings.exchange.provider == "trading212":
        overrides = {
            i.symbol: i.data_symbol
            for i in settings.exchange.effective_instruments()
            if i.data_symbol and i.data_symbol != i.symbol
        }
        return YFinanceMarketData(symbol_overrides=overrides)

    if exchange_client is None:
        raise ValueError("exchange_client is required for the ccxt provider")
    return CcxtMarketData(exchange_client)
