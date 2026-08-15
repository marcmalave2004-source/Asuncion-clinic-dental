"""Position sizing and account-level risk controls.

These are the guardrails that keep a strategy mistake or a bad market move
from doing more damage than the user explicitly agreed to risk.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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
    max_daily_loss_pct of the balance recorded at the start of the day.

    Pass state_path to persist this to disk and reload it on construction -
    needed when the bot runs as a short-lived process invoked repeatedly
    (e.g. one GitHub Actions run per poll) rather than one long-lived loop,
    since a fresh Python process would otherwise have no memory of the
    day's starting equity and the kill switch would never trigger.
    """

    def __init__(self, risk_cfg: RiskConfig, state_path: str | None = None):
        self.risk_cfg = risk_cfg
        self.state_path = Path(state_path) if state_path else None
        self._day: str | None = None
        self._start_equity: float | None = None
        self.triggered = False
        self._load()

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load(self) -> None:
        if not self.state_path or not self.state_path.exists():
            return
        data = json.loads(self.state_path.read_text())
        self._day = data.get("day")
        self._start_equity = data.get("start_equity")
        self.triggered = data.get("triggered", False)

    def _save(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({
            "day": self._day, "start_equity": self._start_equity, "triggered": self.triggered,
        }))

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
            self._save()
            return self.triggered

        drawdown_pct = (self._start_equity - current_equity) / self._start_equity * 100.0
        if drawdown_pct >= self.risk_cfg.max_daily_loss_pct:
            self.triggered = True
        self._save()
        return self.triggered
