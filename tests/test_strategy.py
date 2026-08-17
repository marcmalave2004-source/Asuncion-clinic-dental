import pandas as pd

from trading_bot.config import StrategyConfig
from trading_bot.strategy import Signal, signal_for_row


def _row(ema_fast, ema_slow, rsi):
    return pd.Series({"ema_fast": ema_fast, "ema_slow": ema_slow, "rsi": rsi})


def test_buy_signal_on_bullish_crossover_below_overbought():
    cfg = StrategyConfig(rsi_overbought=70)
    prev = _row(ema_fast=9.9, ema_slow=10.0, rsi=55)
    curr = _row(ema_fast=10.1, ema_slow=10.0, rsi=55)
    assert signal_for_row(prev, curr, cfg) == Signal.BUY


def test_no_buy_signal_when_crossover_happens_overbought():
    cfg = StrategyConfig(rsi_overbought=70)
    prev = _row(ema_fast=9.9, ema_slow=10.0, rsi=85)
    curr = _row(ema_fast=10.1, ema_slow=10.0, rsi=85)
    assert signal_for_row(prev, curr, cfg) == Signal.HOLD


def test_sell_signal_on_bearish_crossover():
    cfg = StrategyConfig()
    prev = _row(ema_fast=10.1, ema_slow=10.0, rsi=40)
    curr = _row(ema_fast=9.9, ema_slow=10.0, rsi=40)
    assert signal_for_row(prev, curr, cfg) == Signal.SELL


def test_buy_signal_on_an_uptrend_already_in_progress():
    # No fresh crossover this candle (fast was already above slow last
    # candle too) - the bot should still buy into an ongoing uptrend
    # instead of only reacting to the exact crossing candle.
    cfg = StrategyConfig(rsi_overbought=70)
    prev = _row(ema_fast=10.5, ema_slow=10.0, rsi=50)
    curr = _row(ema_fast=10.6, ema_slow=10.0, rsi=50)
    assert signal_for_row(prev, curr, cfg) == Signal.BUY


def test_sell_signal_on_a_downtrend_already_in_progress():
    cfg = StrategyConfig()
    prev = _row(ema_fast=9.4, ema_slow=10.0, rsi=40)
    curr = _row(ema_fast=9.3, ema_slow=10.0, rsi=40)
    assert signal_for_row(prev, curr, cfg) == Signal.SELL


def test_hold_when_trend_flat_and_rsi_overbought():
    cfg = StrategyConfig(rsi_overbought=70)
    prev = _row(ema_fast=10.6, ema_slow=10.0, rsi=85)
    curr = _row(ema_fast=10.6, ema_slow=10.0, rsi=85)
    assert signal_for_row(prev, curr, cfg) == Signal.HOLD


def test_hold_when_indicators_not_ready():
    cfg = StrategyConfig()
    prev = _row(ema_fast=float("nan"), ema_slow=10.0, rsi=50)
    curr = _row(ema_fast=10.1, ema_slow=10.0, rsi=50)
    assert signal_for_row(prev, curr, cfg) == Signal.HOLD


def _bb_row(close, bb_lower, bb_upper):
    return pd.Series({"close": close, "bb_lower": bb_lower, "bb_upper": bb_upper})


def test_bollinger_buy_when_price_at_or_below_lower_band():
    cfg = StrategyConfig(mode="bollinger")
    prev = curr = _bb_row(close=95.0, bb_lower=96.0, bb_upper=104.0)
    assert signal_for_row(prev, curr, cfg) == Signal.BUY


def test_bollinger_sell_when_price_at_or_above_upper_band():
    cfg = StrategyConfig(mode="bollinger")
    prev = curr = _bb_row(close=105.0, bb_lower=96.0, bb_upper=104.0)
    assert signal_for_row(prev, curr, cfg) == Signal.SELL


def test_bollinger_hold_when_price_between_bands():
    cfg = StrategyConfig(mode="bollinger")
    prev = curr = _bb_row(close=100.0, bb_lower=96.0, bb_upper=104.0)
    assert signal_for_row(prev, curr, cfg) == Signal.HOLD


def test_bollinger_hold_when_bands_not_ready():
    cfg = StrategyConfig(mode="bollinger")
    prev = curr = _bb_row(close=95.0, bb_lower=float("nan"), bb_upper=float("nan"))
    assert signal_for_row(prev, curr, cfg) == Signal.HOLD
