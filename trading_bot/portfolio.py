"""Tracks the bot's own view of open positions.

Deliberately independent from exchange-reported positions: the bot only
ever manages the single position it opened itself, and checks stop-loss /
take-profit against live price on every loop iteration.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Position:
    symbol: str
    amount: float
    entry_price: float
    stop_loss: float
    take_profit: float

    def unrealized_pnl(self, current_price: float) -> float:
        return (current_price - self.entry_price) * self.amount

    def exit_reason(self, current_price: float) -> str | None:
        if current_price <= self.stop_loss:
            return "stop_loss"
        if current_price >= self.take_profit:
            return "take_profit"
        return None


class PositionStore:
    """Persists the open position (if any) to disk so a bot restart doesn't
    lose track of a real position it holds on the exchange."""

    def __init__(self, path: str = "state/position.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Position | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text())
        if data is None:
            return None
        return Position(**data)

    def save(self, position: Position | None) -> None:
        self.path.write_text(json.dumps(asdict(position) if position else None))
