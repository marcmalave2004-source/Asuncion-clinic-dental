"""SQLite trade log - an audit trail independent of exchange history, so
every decision the bot ever made (dry-run or live) can be reviewed later."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    amount REAL NOT NULL,
    price REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    dry_run INTEGER NOT NULL,
    pnl REAL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    equity REAL NOT NULL
);
"""


@dataclass
class TradeRecord:
    symbol: str
    side: str
    amount: float
    price: float
    dry_run: bool
    stop_loss: float | None = None
    take_profit: float | None = None
    pnl: float | None = None
    note: str = ""


class TradeStore:
    def __init__(self, db_path: str = "state/trades.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record_trade(self, trade: TradeRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO trades
                   (timestamp, symbol, side, amount, price, stop_loss, take_profit, dry_run, pnl, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    trade.symbol,
                    trade.side,
                    trade.amount,
                    trade.price,
                    trade.stop_loss,
                    trade.take_profit,
                    int(trade.dry_run),
                    trade.pnl,
                    trade.note,
                ),
            )

    def record_equity(self, equity: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO equity_snapshots (timestamp, equity) VALUES (?, ?)",
                (datetime.now(timezone.utc).isoformat(), equity),
            )

    def recent_trades(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
            )
            return cur.fetchall()
