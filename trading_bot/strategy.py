"""Two selectable long-only, spot-style entry/exit strategies (no shorting,
no leverage) - the safest default for a bot that can be pointed at real
funds. Pick one via strategy.mode in config.yaml.

"ema_rsi" (default) - trend-following:
  Entry (BUY): the fast EMA is above the slow EMA (an uptrend, not
               necessarily one that just started) while RSI is below the
               overbought threshold (avoids buying into an already-extended
               move). Doesn't require a fresh crossover on this exact
               candle - it acts on any candle where the trend is already up,
               so it catches moves that started before the bot last checked.
  Exit (SELL): the fast EMA is below the slow EMA.

"bollinger" - mean-reversion "floor/ceiling" bounce:
  Entry (BUY): price closes at or below the lower Bollinger Band (the
               "floor"), on the expectation it reverts back toward the mean.
  Exit (SELL): price closes at or above the upper Bollinger Band (the
               "ceiling").

"momentum" - pure short-term scalping, no trend/RSI filter at all:
  Entry (BUY): this candle closed higher than the previous one - any tiny
               uptick, no confirmation required.
  Exit (SELL): this candle closed lower than the previous one.
  Meant to be paired with a very tight trailing_stop_pct so it grabs small,
  frequent gains instead of waiting for a confirmed trend. Because it reacts
  to single-candle noise instead of a trend, expect many more trades but a
  much weaker edge per trade - validate with the backtester before trusting
  it with real money, and remember the backtester assumes a perfect fill at
  the candle's close with no spread, which matters a lot more here than for
  the other two modes given how small each trade's target profit is.

Either way, the actual stop-loss/take-profit are ATR-based and handled by
risk.py against live price, not here.

Neither is a guarantee of profitability. Past performance of any indicator
combination does not predict future returns; treat this as a starting point
to tune and validate via the backtester, not as financial advice.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from trading_bot.config import StrategyConfig
from trading_bot.indicators import add_indicators


class Signal(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class StrategyDecision:
    signal: Signal
    price: float
    atr: float
    rsi: float


def prepare(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    return add_indicators(
        df,
        ema_fast=cfg.ema_fast,
        ema_slow=cfg.ema_slow,
        rsi_period=cfg.rsi_period,
        atr_period=cfg.atr_period,
        bb_period=cfg.bb_period,
        bb_std_dev=cfg.bb_std_dev,
    )


def _signal_ema_rsi(prev: pd.Series, curr: pd.Series, cfg: StrategyConfig) -> Signal:
    if pd.isna(prev["ema_fast"]) or pd.isna(prev["ema_slow"]) or pd.isna(curr["ema_fast"]) or pd.isna(curr["ema_slow"]):
        return Signal.HOLD

    if curr["ema_fast"] > curr["ema_slow"] and curr["rsi"] < cfg.rsi_overbought:
        return Signal.BUY
    if curr["ema_fast"] < curr["ema_slow"]:
        return Signal.SELL
    return Signal.HOLD


def _signal_bollinger(prev: pd.Series, curr: pd.Series, cfg: StrategyConfig) -> Signal:
    if pd.isna(curr["bb_upper"]) or pd.isna(curr["bb_lower"]):
        return Signal.HOLD

    if curr["close"] <= curr["bb_lower"]:
        return Signal.BUY
    if curr["close"] >= curr["bb_upper"]:
        return Signal.SELL
    return Signal.HOLD


def _signal_momentum(prev: pd.Series, curr: pd.Series, cfg: StrategyConfig) -> Signal:
    if pd.isna(prev["close"]) or pd.isna(curr["close"]):
        return Signal.HOLD

    if curr["close"] > prev["close"]:
        return Signal.BUY
    if curr["close"] < prev["close"]:
        return Signal.SELL
    return Signal.HOLD


def signal_for_row(prev: pd.Series, curr: pd.Series, cfg: StrategyConfig) -> Signal:
    if cfg.mode == "bollinger":
        return _signal_bollinger(prev, curr, cfg)
    if cfg.mode == "momentum":
        return _signal_momentum(prev, curr, cfg)
    return _signal_ema_rsi(prev, curr, cfg)


def latest_decision(df: pd.DataFrame, cfg: StrategyConfig) -> StrategyDecision:
    """Given an OHLCV dataframe (oldest -> newest), compute indicators and
    return the decision for the most recently closed candle."""
    prepared = prepare(df, cfg)
    if len(prepared) < 2:
        raise ValueError("Need at least 2 candles to evaluate a crossover")

    prev, curr = prepared.iloc[-2], prepared.iloc[-1]
    signal = signal_for_row(prev, curr, cfg)
    return StrategyDecision(
        signal=signal,
        price=float(curr["close"]),
        atr=float(curr["atr"]) if not pd.isna(curr["atr"]) else 0.0,
        rsi=float(curr["rsi"]),
    )
