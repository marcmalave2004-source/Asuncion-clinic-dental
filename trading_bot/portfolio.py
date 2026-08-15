"""Tracks the bot's own view of open positions, one per symbol.

Deliberately independent from exchange-reported positions: the bot only
ever manages positions it opened itself, and checks stop-loss / take-profit
against live price on every loop iteration.
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
    """Persists open positions (keyed by symbol) to disk so a bot restart
    doesn't lose track of what it actually holds on the exchange."""

    def __init__(self, path: str = "state/positions.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> dict[str, Position]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text()) or {}
        return {symbol: Position(**fields) for symbol, fields in data.items()}

    def save_all(self, positions: dict[str, Position]) -> None:
        self.path.write_text(json.dumps({symbol: asdict(p) for symbol, p in positions.items()}))
