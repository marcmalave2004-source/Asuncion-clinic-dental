import numpy as np
import pandas as pd

from trading_bot.indicators import atr, bollinger_bands, ema, rsi


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


def test_bollinger_bands_flat_series_has_zero_width():
    series = pd.Series([50.0] * 25)
    middle, upper, lower = bollinger_bands(series, period=20, num_std=2.0)
    assert np.isclose(middle.iloc[-1], 50.0)
    assert np.isclose(upper.iloc[-1], 50.0)
    assert np.isclose(lower.iloc[-1], 50.0)


def test_bollinger_bands_upper_above_lower_for_volatile_series():
    rng = np.random.default_rng(0)
    series = pd.Series(100 + rng.normal(0, 5, size=40))
    middle, upper, lower = bollinger_bands(series, period=20, num_std=2.0)
    valid = middle.notna()
    assert (upper[valid] > middle[valid]).all()
    assert (lower[valid] < middle[valid]).all()


def test_bollinger_bands_wider_with_larger_num_std():
    rng = np.random.default_rng(1)
    series = pd.Series(100 + rng.normal(0, 5, size=40))
    _, upper_narrow, lower_narrow = bollinger_bands(series, period=20, num_std=1.0)
    _, upper_wide, lower_wide = bollinger_bands(series, period=20, num_std=3.0)
    width_narrow = (upper_narrow - lower_narrow).iloc[-1]
    width_wide = (upper_wide - lower_wide).iloc[-1]
    assert width_wide > width_narrow
