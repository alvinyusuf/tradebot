"""Fault-injection harness for persistent order and protection recovery."""

import json
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from .reconciliation import OrderJournal, OrderState
from .risk import Side

ZERO = Decimal(0)
OPEN = {"pending", "unknown", "acknowledged", "partial"}


class ExecutionState(StrEnum):
    RECONCILING = "RECONCILING"
    READY = "READY"
    HALTED = "HALTED"


@dataclass(frozen=True, slots=True)
class EntryIntent:
    client_id: str
    side: Side
    quantity: Decimal
    stop: Decimal
    target: Decimal

    def __post_init__(self):
        if not self.client_id or len(self.client_id) > 24:
            raise ValueError("ID simulasi wajib dan maksimum 24 karakter")
        if self.side not in (Side.LONG, Side.SHORT):
            raise ValueError("Arah posisi tidak valid")
        if not all(value.is_finite() and value > 0 for value in (self.quantity, self.stop, self.target)):
            raise ValueError("Kuantitas dan harga proteksi harus positif")
        if self.side * (self.target - self.stop) <= 0:
            raise ValueError("Arah SL/TP berlawanan dengan posisi")


@dataclass(frozen=True, slots=True)
class OrderObservation:
    state: OrderState
    cumulative_fill: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class Protection:
    quantity: Decimal
    stop: Decimal
    target: Decimal


class FaultInjectingExchange:
    """Deterministic paper fixture. Position and fills are entirely in memory."""

    def __init__(self):
        self.orders: dict[str, OrderObservation] = {}
        self.position = ZERO
        self.protection: Protection | None = None
        self.next_entry_fill: Decimal | None = None
        self.calls: Counter[str] = Counter()
        self.faults: Counter[str] = Counter()
        self._intent: EntryIntent | None = None

    def _fault(self, key: str):
        if self.faults[key]:
            self.faults[key] -= 1
            raise TimeoutError(key)

    def submit_entry(self, intent: EntryIntent) -> OrderObservation:
        self.calls["entry"] += 1
        self._fault("entry_before")
        if self.position or self._intent or intent.client_id in self.orders:
            raise ValueError("Entry simulasi duplikat atau posisi belum flat")
        self._intent = intent
        quantity = self.next_entry_fill
        self.next_entry_fill = None
        self.orders[intent.client_id] = OrderObservation("acknowledged")
        self.advance_fill(intent.quantity if quantity is None else quantity)
        self._fault("entry_after")
        return self.orders[intent.client_id]

    def advance_fill(self, total: Decimal):
        intent = self._intent
        if intent is None:
            raise ValueError("Tidak ada entry aktif")
        prior = self.orders[intent.client_id]
        if prior.state not in OPEN or not prior.cumulative_fill <= total <= intent.quantity:
            raise ValueError("Fill simulasi di luar batas order aktif")
        self.position += intent.side * (total - prior.cumulative_fill)
        state: OrderState = "acknowledged"
        if total:
            state = "filled" if total == intent.quantity else "partial"
        self.orders[intent.client_id] = OrderObservation(state, total)

    def query(self, client_id: str) -> OrderObservation | None:
        self.calls["query"] += 1
        self._fault("query")
        return self.orders.get(client_id)

    def cancel(self, client_id: str) -> OrderObservation:
        self.calls["cancel"] += 1
        self._fault("cancel")
        prior = self.orders[client_id]
        if prior.state in OPEN:
            self.orders[client_id] = OrderObservation("canceled", prior.cumulative_fill)
            if not self.position:
                self._intent = None
        return self.orders[client_id]

    def set_protection(self, protection: Protection | None):
        self.calls["protection"] += 1
        self._fault("protection_before")
        if protection is not None and protection.quantity != abs(self.position):
            raise ValueError("Jumlah proteksi harus sama dengan posisi terbuka")
        self.protection = protection
        self._fault("protection_after")

    def snapshot(self) -> tuple[Decimal, Protection | None]:
        self.calls["snapshot"] += 1
        self._fault("snapshot")
        return self.position, self.protection

    def close_reduce_only(self, client_id: str, quantity: Decimal) -> OrderObservation:
        self.calls["close"] += 1
        self._fault("close_before")
        if client_id in self.orders or quantity != abs(self.position) or not quantity:
            raise ValueError("Close simulasi harus mengurangi posisi yang diketahui")
        self.position = ZERO
        self._intent = None
        self.orders[client_id] = OrderObservation("filled", quantity)
        self._fault("close_after")
        return self.orders[client_id]


class PaperRecovery:
    """Exercise reconciliation and protection for one local execution worker."""

    def __init__(self, journal: OrderJournal, exchange: FaultInjectingExchange):
        self.journal = journal
        self.exchange = exchange
        self.state = ExecutionState.RECONCILING
        self.data_fresh = False
        with closing(sqlite3.connect(journal.path)) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS paper_recovery (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    intent TEXT,
                    halt TEXT
                )
            """)
            db.execute("INSERT OR IGNORE INTO paper_recovery VALUES (1, NULL, NULL)")

    def _read(self) -> tuple[EntryIntent | None, str | None]:
        with closing(sqlite3.connect(self.journal.path)) as db:
            payload, halt = db.execute("SELECT intent, halt FROM paper_recovery WHERE id = 1").fetchone()
        if payload is None:
            return None, halt
        client_id, side, quantity, stop, target = json.loads(payload)
        return EntryIntent(client_id, Side(side), Decimal(quantity), Decimal(stop), Decimal(target)), halt

    def _write(self, intent: EntryIntent | None, halt: str | None):
        payload = None
        if intent is not None:
            payload = json.dumps([
                intent.client_id, int(intent.side), str(intent.quantity), str(intent.stop), str(intent.target)
            ])
        with closing(sqlite3.connect(self.journal.path)) as db, db:
            db.execute("UPDATE paper_recovery SET intent = ?, halt = ? WHERE id = 1", (payload, halt))

    def _record(self, client_id: str, state: OrderState):
        self.journal.record(client_id, str(uuid4()), state)

    def observe_market(
        self, *, now: datetime, quote_time: datetime, mark_time: datetime, clock_drift: timedelta
    ):
        self.data_fresh = (
            abs(clock_drift) <= timedelta(seconds=1)
            and all(timedelta(0) <= now - stamp <= timedelta(seconds=5) for stamp in (quote_time, mark_time))
        )
        if not self.data_fresh:
            intent, halt = self._read()
            if halt is None:
                self._write(intent, "data_stale")
            self.state = ExecutionState.HALTED

    def submit_entry(self, intent: EntryIntent):
        current, halt = self._read()
        if (
            self.state != ExecutionState.READY or not self.data_fresh or halt
            or current is not None or self.journal.unresolved()
        ):
            raise RuntimeError("Entry diblokir sampai data dan state siap")
        self.journal.plan(intent.client_id)
        self._write(intent, None)
        try:
            observed = self.exchange.submit_entry(intent)
        except TimeoutError:
            self._record(intent.client_id, "unknown")
            self.state = ExecutionState.HALTED
            return
        self._record(intent.client_id, observed.state)
        self.reconcile()

    def _repair_protection(self, desired: Protection) -> bool:
        try:
            self.exchange.set_protection(desired)
        except TimeoutError:
            # Confirmation may have been lost after a successful update.
            pass
        _, actual = self.exchange.snapshot()
        return actual == desired

    def _emergency(self, intent: EntryIntent, observed: OrderObservation):
        self._write(intent, "protection_failed")
        if observed.state in OPEN:
            observed = self.exchange.cancel(intent.client_id)
            self._record(intent.client_id, observed.state)
        position, _ = self.exchange.snapshot()
        if intent.side * position <= 0 or abs(position) != observed.cumulative_fill:
            raise RuntimeError("Kuantitas posisi tidak dapat dipastikan untuk close")
        close_id = f"{intent.client_id}-close"
        self.journal.plan(close_id)
        try:
            closed = self.exchange.close_reduce_only(close_id, abs(position))
        except TimeoutError:
            self._record(close_id, "unknown")
            return
        self._record(close_id, closed.state)
        flat, _ = self.exchange.snapshot()
        if flat == ZERO:
            self.exchange.set_protection(None)
            self._write(None, "protection_failed")

    def reconcile(self) -> bool:
        self.state = ExecutionState.RECONCILING
        intent, halt = self._read()
        try:
            position, protection = self.exchange.snapshot()
            unresolved = self.journal.unresolved()
            allowed_ids = set()
            if intent is not None:
                allowed_ids = {intent.client_id, f"{intent.client_id}-close"}
            for record in unresolved:
                if record.client_id not in allowed_ids:
                    raise RuntimeError("Order jurnal tanpa intent yang dapat dipastikan")
                observed = self.exchange.query(record.client_id)
                if observed is None:
                    raise RuntimeError("Status order belum diketahui")
                self._record(record.client_id, observed.state)
            if intent is None:
                if position or protection is not None:
                    raise RuntimeError("Posisi atau proteksi tidak cocok dengan jurnal")
            elif halt == "protection_failed":
                self._resume_failed_protection(intent, position)
            else:
                self._reconcile_entry(intent, position, protection, halt)
        except (TimeoutError, RuntimeError, ValueError):
            self.state = ExecutionState.HALTED
            return False
        _, current_halt = self._read()
        self.state = (
            ExecutionState.READY if self.data_fresh and not current_halt else ExecutionState.HALTED
        )
        return True

    def _resume_failed_protection(self, intent: EntryIntent, position: Decimal):
        if not position and not self.journal.unresolved():
            self.exchange.set_protection(None)
            self._write(None, "protection_failed")
        elif position and self.journal.state(f"{intent.client_id}-close") is None:
            observed = self.exchange.query(intent.client_id)
            if observed is None:
                raise RuntimeError("Status entry belum diketahui")
            self._emergency(intent, observed)

    def _reconcile_entry(
        self,
        intent: EntryIntent,
        position: Decimal,
        protection: Protection | None,
        halt: str | None,
    ):
        observed = self.exchange.query(intent.client_id)
        if observed is None or intent.side * position != observed.cumulative_fill:
            raise RuntimeError("Fill dan posisi tidak cocok")
        if not position:
            if protection is not None:
                raise RuntimeError("Proteksi aktif pada akun flat")
            if observed.state in {"canceled", "rejected"}:
                self._write(None, halt)
            return
        desired = Protection(abs(position), intent.stop, intent.target)
        if protection != desired and not self._repair_protection(desired):
            self._emergency(intent, observed)

    def recover(self):
        """Acknowledge a persistent halt after reconciling fresh exchange state."""
        intent, halt = self._read()
        if not halt:
            self.reconcile()
            return
        if halt == "data_stale":
            if not self.data_fresh or not self.reconcile():
                raise RuntimeError("Recovery membutuhkan data segar dan rekonsiliasi")
            intent, halt = self._read()
            if halt != "data_stale":
                raise RuntimeError("Sistem mendeteksi kegagalan proteksi saat recovery")
            self._write(intent, None)
            self.reconcile()
            return
        position, protection = self.exchange.snapshot()
        if intent or position or protection is not None or self.journal.unresolved():
            raise RuntimeError("Recovery membutuhkan posisi flat, proteksi bersih, dan jurnal tuntas")
        self._write(None, None)
        self.reconcile()
