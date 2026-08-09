import numpy as np
import pandas as pd

from trading_bot.backtester import run_backtest
from trading_bot.config import RiskConfig, StrategyConfig


def _synthetic_ohlcv(n=300, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # Trend + noise so EMA crossovers actually occur a few times.
    trend = np.concatenate(
        [
            np.linspace(100, 130, n // 3),
            np.linspace(130, 90, n // 3),
            np.linspace(90, 120, n - 2 * (n // 3)),
        ]
    )
    noise = rng.normal(0, 1.0, size=len(trend))
    close = trend + noise
    high = close + np.abs(rng.normal(0.5, 0.3, size=len(close)))
    low = close - np.abs(rng.normal(0.5, 0.3, size=len(close)))
    open_ = close + rng.normal(0, 0.2, size=len(close))
    timestamp = np.arange(len(close)) * 3_600_000  # hourly candles in ms
    volume = np.abs(rng.normal(100, 10, size=len(close)))

    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def test_backtest_runs_and_produces_consistent_equity_curve():
    df = _synthetic_ohlcv()
    strategy_cfg = StrategyConfig()
    risk_cfg = RiskConfig(risk_per_trade_pct=1.0, min_order_quote=1.0)

    result = run_backtest(df, strategy_cfg, risk_cfg, initial_balance=1000.0)

    assert result.initial_equity == 1000.0
    assert len(result.equity_curve) == len(df) - 1
    assert result.final_equity > 0
    assert result.max_drawdown_pct >= 0
    # win_rate/profit_factor must not blow up when there are zero trades
    assert 0 <= result.win_rate_pct <= 100


def test_backtest_never_risks_more_than_available_cash():
    df = _synthetic_ohlcv(seed=7)
    strategy_cfg = StrategyConfig()
    risk_cfg = RiskConfig(risk_per_trade_pct=50.0, min_order_quote=1.0)  # aggressive sizing

    result = run_backtest(df, strategy_cfg, risk_cfg, initial_balance=500.0)

    # Equity should never go negative even with aggressive position sizing,
    # since size_position() caps notional at the available cash balance.
    assert min(result.equity_curve) >= 0
