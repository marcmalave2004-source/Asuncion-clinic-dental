"""Position sizing and account-level risk controls.

These are the guardrails that keep a strategy mistake or a bad market move
from doing more damage than the user explicitly agreed to risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from trading_bot.config import RiskConfig, StrategyConfig


@dataclass
class PositionSizeResult:
    amount: float
    stop_loss: float
    take_profit: float
    risk_amount: float


def compute_stop_and_target(entry_price: float, atr: float, cfg: StrategyConfig) -> tuple[float, float]:
    stop_loss = entry_price - atr * cfg.atr_stop_mult
    take_profit = entry_price + atr * cfg.atr_target_mult
    return max(stop_loss, 0.0), take_profit


def size_position(
    balance_quote: float,
    entry_price: float,
    stop_loss: float,
    risk_cfg: RiskConfig,
) -> PositionSizeResult | None:
    """Sizes a position so that a stop-loss hit loses at most
    risk_per_trade_pct of the account balance. Returns None if the resulting
    order would be below the exchange's minimum notional or risk is invalid.
    """
    if entry_price <= stop_loss:
        return None

    risk_amount = balance_quote * (risk_cfg.risk_per_trade_pct / 100.0)
    per_unit_risk = entry_price - stop_loss
    amount = risk_amount / per_unit_risk

    notional = amount * entry_price
    if notional < risk_cfg.min_order_quote:
        return None
    if notional > balance_quote:
        # Never risk more than the account actually has available.
        amount = balance_quote / entry_price
        notional = amount * entry_price
        if notional < risk_cfg.min_order_quote:
            return None

    return PositionSizeResult(
        amount=amount,
        stop_loss=stop_loss,
        take_profit=0.0,
        risk_amount=risk_amount,
    )


class DailyLossKillSwitch:
    """Halts new trades for the day once realized+unrealized losses exceed
    max_daily_loss_pct of the balance recorded at the start of the day."""

    def __init__(self, risk_cfg: RiskConfig):
        self.risk_cfg = risk_cfg
        self._day: str | None = None
        self._start_equity: float | None = None
        self.triggered = False

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def update(self, current_equity: float) -> bool:
        """Call once per loop with current total equity. Returns True if
        trading should be halted for the rest of the day."""
        today = self._today()
        if self._day != today:
            self._day = today
            self._start_equity = current_equity
            self.triggered = False

        assert self._start_equity is not None
        if self._start_equity <= 0:
            return self.triggered

        drawdown_pct = (self._start_equity - current_equity) / self._start_equity * 100.0
        if drawdown_pct >= self.risk_cfg.max_daily_loss_pct:
            self.triggered = True
        return self.triggered
