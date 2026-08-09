import numpy as np
import pandas as pd

from trading_bot.indicators import atr, ema, rsi


def test_ema_of_constant_series_equals_constant():
    series = pd.Series([10.0] * 30)
    result = ema(series, period=5)
    assert np.isclose(result.iloc[-1], 10.0)


def test_rsi_is_high_for_strictly_increasing_series():
    series = pd.Series(np.arange(1, 50, dtype=float))
    result = rsi(series, period=14)
    assert result.iloc[-1] > 90


def test_rsi_is_low_for_strictly_decreasing_series():
    series = pd.Series(np.arange(50, 1, -1, dtype=float))
    result = rsi(series, period=14)
    assert result.iloc[-1] < 10


def test_atr_is_non_negative():
    df = pd.DataFrame(
        {
            "high": [10, 11, 12, 11, 13, 14],
            "low": [9, 9.5, 10, 9, 11, 12],
            "close": [9.5, 10.5, 11, 10, 12, 13],
        }
    )
    result = atr(df, period=3)
    assert (result.dropna() >= 0).all()
