"""Historical backtesting: validate a strategy+risk configuration against
past data before ever pointing it at a live or real-money account.

Fetching the historical OHLCV data itself lives in market_data.py (it's
provider-specific: ccxt for crypto exchanges, Yahoo Finance for Trading
212's stocks/ETFs) - this module only simulates the strategy against
whatever DataFrame it's handed."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from trading_bot.config import RiskConfig, StrategyConfig
from trading_bot.risk import compute_stop_and_target
from trading_bot.strategy import Signal, prepare, signal_for_row


@dataclass
class BacktestTrade:
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    amount: float
    pnl: float
    exit_reason: str


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    final_equity: float = 0.0
    initial_equity: float = 0.0

    @property
    def total_return_pct(self) -> float:
        if self.initial_equity == 0:
            return 0.0
        return (self.final_equity - self.initial_equity) / self.initial_equity * 100.0

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate_pct(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades) * 100.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = -sum(t.pnl for t in self.trades if t.pnl < 0)
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0]
        max_dd = 0.0
        for equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                dd = (peak - equity) / peak * 100.0
                max_dd = max(max_dd, dd)
        return max_dd

    def summary(self) -> str:
        return (
            f"Trades: {self.num_trades} | Win rate: {self.win_rate_pct:.1f}% | "
            f"Return: {self.total_return_pct:+.2f}% | Max DD: {self.max_drawdown_pct:.2f}% | "
            f"Profit factor: {self.profit_factor:.2f} | "
            f"Equity: {self.initial_equity:.2f} -> {self.final_equity:.2f}"
        )


def run_backtest(
    df: pd.DataFrame,
    strategy_cfg: StrategyConfig,
    risk_cfg: RiskConfig,
    initial_balance: float = 1000.0,
) -> BacktestResult:
    from trading_bot.risk import size_position  # local import avoids a cycle at module load time

    data = prepare(df, strategy_cfg)
    result = BacktestResult(initial_equity=initial_balance)

    cash = initial_balance
    position = None  # dict: amount, entry_price, stop_loss, take_profit, entry_time
    fee_rate = risk_cfg.taker_fee_pct / 100.0

    for i in range(1, len(data)):
        prev_row, curr_row = data.iloc[i - 1], data.iloc[i]
        equity = cash if position is None else cash + position["amount"] * curr_row["close"]
        result.equity_curve.append(equity)

        if position is not None:
            exit_price = None
            reason = None
            if curr_row["low"] <= position["stop_loss"]:
                exit_price, reason = position["stop_loss"], "stop_loss"
            elif curr_row["high"] >= position["take_profit"]:
                exit_price, reason = position["take_profit"], "take_profit"
            else:
                sig = signal_for_row(prev_row, curr_row, strategy_cfg)
                if sig == Signal.SELL:
                    exit_price, reason = curr_row["close"], "signal"

            if exit_price is not None:
                proceeds = position["amount"] * exit_price * (1 - fee_rate)
                cost_basis = position["amount"] * position["entry_price"]
                pnl = proceeds - cost_basis
                cash += proceeds
                result.trades.append(
                    BacktestTrade(
                        entry_time=int(position["entry_time"]),
                        exit_time=int(curr_row["timestamp"]),
                        entry_price=position["entry_price"],
                        exit_price=exit_price,
                        amount=position["amount"],
                        pnl=pnl,
                        exit_reason=reason,
                    )
                )
                position = None
                continue

        if position is None:
            sig = signal_for_row(prev_row, curr_row, strategy_cfg)
            if sig == Signal.BUY:
                entry_price = float(curr_row["close"])
                atr_value = float(curr_row["atr"]) if not pd.isna(curr_row["atr"]) else 0.0
                if atr_value <= 0:
                    continue
                stop_loss, take_profit = compute_stop_and_target(entry_price, atr_value, strategy_cfg)
                sized = size_position(cash, entry_price, stop_loss, risk_cfg)
                if sized is None:
                    continue
                cost = sized.amount * entry_price * (1 + fee_rate)
                if cost > cash:
                    continue
                cash -= cost
                position = {
                    "amount": sized.amount,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "entry_time": curr_row["timestamp"],
                }

    final_equity = cash if position is None else cash + position["amount"] * data.iloc[-1]["close"]
    result.final_equity = final_equity
    return result
