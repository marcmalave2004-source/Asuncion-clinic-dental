"""EMA-crossover + RSI-filter strategy.

Long-only, spot-style logic (no shorting, no leverage) by design: it is the
safest default for a bot that can be pointed at real funds.

Entry (BUY): the fast EMA crosses above the slow EMA (an emerging uptrend)
             while RSI is below the overbought threshold (avoids buying into
             an already-extended move).
Exit (SELL): the fast EMA crosses back below the slow EMA, OR the position's
             stop-loss/take-profit is hit (handled by risk.py against live
             price, not here).

This is a reasonable, well-understood default - not a guarantee of
profitability. Past performance of any indicator combination does not
predict future returns; treat this as a starting point to tune and validate
via the backtester, not as financial advice.
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
    )


def signal_for_row(prev: pd.Series, curr: pd.Series, cfg: StrategyConfig) -> Signal:
    if pd.isna(prev["ema_fast"]) or pd.isna(prev["ema_slow"]) or pd.isna(curr["ema_fast"]) or pd.isna(curr["ema_slow"]):
        return Signal.HOLD

    crossed_up = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]
    crossed_down = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]

    if crossed_up and curr["rsi"] < cfg.rsi_overbought:
        return Signal.BUY
    if crossed_down:
        return Signal.SELL
    return Signal.HOLD


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
