"""Persistent order lifecycle used to exercise recovery locally."""

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

OrderState = Literal[
    "pending", "unknown", "acknowledged", "partial", "filled", "canceled", "rejected"
]
_TRANSITIONS = {
    "pending": {"unknown", "acknowledged", "partial", "filled", "canceled", "rejected"},
    "unknown": {"acknowledged", "partial", "filled", "canceled", "rejected"},
    "acknowledged": {"unknown", "partial", "filled", "canceled", "rejected"},
    "partial": {"unknown", "filled", "canceled"},
    "filled": set(),
    "canceled": set(),
    "rejected": set(),
}


@dataclass(frozen=True)
class OrderRecord:
    client_id: str
    state: OrderState


class OrderJournal:
    def __init__(self, path: Path):
        self.path = path
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orders (
                    client_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS order_events (
                    event_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL REFERENCES orders(client_id),
                    state TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA foreign_keys=ON")
            yield db

    def plan(self, client_id: str, *, require_no_unresolved: bool = False) -> None:
        """Record intent before sending and reject any reused client ID."""
        if not client_id:
            raise ValueError("Client ID wajib diisi")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                require_no_unresolved
                and db.execute(
                    "SELECT 1 FROM orders WHERE state IN ('pending', 'unknown', 'acknowledged', 'partial') LIMIT 1"
                ).fetchone()
            ):
                raise ValueError("Order yang belum pasti perlu direkonsiliasi")
            try:
                db.execute("INSERT INTO orders VALUES (?, 'pending')", (client_id,))
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Client ID sudah tercatat: {client_id}") from exc
            db.execute(
                "INSERT INTO order_events VALUES (?, ?, 'pending', ?)",
                (f"plan:{client_id}", client_id, datetime.now(UTC).isoformat()),
            )

    def record(self, client_id: str, event_id: str, state: OrderState) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous_event = db.execute(
                "SELECT client_id, state FROM order_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if previous_event == (client_id, state):
                return
            if previous_event is not None:
                raise ValueError(f"Isi event berbeda untuk ID yang sama: {event_id}")
            record = db.execute(
                "SELECT state FROM orders WHERE client_id = ?", (client_id,)
            ).fetchone()
            if record is None:
                raise ValueError(f"Order belum tercatat: {client_id}")
            current = record[0]
            if current != state and state not in _TRANSITIONS[current]:
                raise ValueError(f"Transisi order tidak valid: {current} -> {state}")
            db.execute(
                "INSERT INTO order_events VALUES (?, ?, ?, ?)",
                (event_id, client_id, state, datetime.now(UTC).isoformat()),
            )
            db.execute(
                "UPDATE orders SET state = ? WHERE client_id = ?", (state, client_id)
            )

    def unresolved(self) -> tuple[OrderRecord, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT client_id, state FROM orders "
                "WHERE state IN ('pending', 'unknown', 'acknowledged', 'partial') ORDER BY client_id"
            )
            return tuple(OrderRecord(*row) for row in rows)

    def state(self, client_id: str) -> OrderState | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT state FROM orders WHERE client_id = ?", (client_id,)
            ).fetchone()
            return None if row is None else row[0]

    def backup(self, target: Path) -> None:
        if target.resolve() == self.path.resolve():
            raise ValueError("Target backup harus berbeda dari database aktif")
        with self._connect() as db, closing(sqlite3.connect(target)) as copy:
            db.backup(copy)
