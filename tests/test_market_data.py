import pandas as pd

from trading_bot.market_data import (
    OHLCV_COLUMNS,
    YFinanceMarketData,
    _lookback_days,
    _normalize_yf,
    _yf_interval,
)


def test_yf_interval_maps_1h_to_60m():
    assert _yf_interval("1h") == "60m"


def test_yf_interval_passes_through_unknown_timeframes():
    assert _yf_interval("1d") == "1d"
    assert _yf_interval("1wk") == "1wk"


def test_lookback_days_scales_with_limit_and_bar_density():
    assert _lookback_days("1d", limit=100) > _lookback_days("1d", limit=10)
    # Intraday bars are denser, so fewer calendar days are needed for the same limit.
    assert _lookback_days("5m", limit=200) < _lookback_days("1d", limit=200)


def test_lookback_days_respects_yahoo_retention_cap():
    # 1m data is only retained ~7 days by Yahoo Finance regardless of how
    # many bars are requested.
    assert _lookback_days("1m", limit=100_000) == 7


def test_normalize_yf_empty_dataframe_returns_expected_columns():
    result = _normalize_yf(pd.DataFrame())
    assert list(result.columns) == OHLCV_COLUMNS
    assert result.empty


def test_normalize_yf_maps_columns_and_converts_timestamp():
    raw = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Volume": [1000, 1100],
        },
        index=pd.DatetimeIndex(["2024-01-01", "2024-01-02"], name="Date", tz="UTC"),
    )
    result = _normalize_yf(raw)
    assert list(result.columns) == OHLCV_COLUMNS
    assert result.loc[0, "open"] == 100.0
    assert result.loc[0, "timestamp"] == int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)


def test_normalize_yf_flattens_multiindex_columns():
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["AAPL"]])
    raw = pd.DataFrame(
        [[100.0, 102.0, 99.0, 101.0, 1000]],
        columns=columns,
        index=pd.DatetimeIndex(["2024-01-01"], name="Date", tz="UTC"),
    )
    result = _normalize_yf(raw)
    assert list(result.columns) == OHLCV_COLUMNS
    assert result.loc[0, "close"] == 101.0


def test_symbol_override_is_used_instead_of_passed_symbol(monkeypatch):
    captured = {}

    def fake_download(ticker, **kwargs):
        captured["ticker"] = ticker
        return pd.DataFrame()

    monkeypatch.setattr("yfinance.download", fake_download)
    provider = YFinanceMarketData(symbol_overrides={"AAPL": "MSFT"})
    provider.fetch_recent("AAPL", "1d", limit=10)
    assert captured["ticker"] == "MSFT"


def test_symbol_without_an_override_passes_through_unchanged(monkeypatch):
    captured = {}

    def fake_download(ticker, **kwargs):
        captured["ticker"] = ticker
        return pd.DataFrame()

    monkeypatch.setattr("yfinance.download", fake_download)
    provider = YFinanceMarketData(symbol_overrides={"AAPL": "MSFT"})
    provider.fetch_recent("VOO", "1d", limit=10)
    assert captured["ticker"] == "VOO"
