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


def test_hold_when_no_crossover():
    cfg = StrategyConfig()
    prev = _row(ema_fast=10.5, ema_slow=10.0, rsi=50)
    curr = _row(ema_fast=10.6, ema_slow=10.0, rsi=50)
    assert signal_for_row(prev, curr, cfg) == Signal.HOLD


def test_hold_when_indicators_not_ready():
    cfg = StrategyConfig()
    prev = _row(ema_fast=float("nan"), ema_slow=10.0, rsi=50)
    curr = _row(ema_fast=10.1, ema_slow=10.0, rsi=50)
    assert signal_for_row(prev, curr, cfg) == Signal.HOLD
