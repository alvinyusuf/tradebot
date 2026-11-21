"""Durable single-run snapshots for the paper portfolio and daily risk state."""

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .portfolio import ClosedTrade, Portfolio, Position
from .risk import DailyRisk, OrderPlan, Side


@dataclass(frozen=True, slots=True)
class PaperSnapshot:
    portfolio: Portfolio
    daily_risk: DailyRisk
    last_processed: datetime | None
    model_id: str
    config_id: str
    next_minute: datetime | None = None
    expected_funding: datetime | None = None
    unverified_exposure_intervals: int = 0


class _LedgerData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_balance: Decimal
    balance: Decimal
    position: Position | None
    closed_trades: tuple[ClosedTrade, ...]
    total_fees: Decimal
    total_funding: Decimal
    realized_pnl: Decimal


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    model_id: str
    config_id: str
    last_processed: datetime | None
    next_minute: datetime | None = None
    expected_funding: datetime | None = None
    unverified_exposure_intervals: int = Field(default=0, ge=0, strict=True)
    portfolio: _LedgerData
    daily_risk: DailyRisk


def _require_utc(timestamp: datetime | None) -> None:
    if timestamp is not None and timestamp.utcoffset() != timedelta(0):
        raise ValueError("Paper snapshot requires UTC timestamps")


def _validate_plan(plan: OrderPlan) -> None:
    amounts = (
        plan.quantity,
        plan.entry_price,
        plan.stop_price,
        plan.take_profit_price,
        plan.initial_margin,
        plan.loss_at_stop,
        plan.liquidation_price,
    )
    if not all(amount.is_finite() for amount in amounts):
        raise ValueError("Non-finite amounts in paper order plan")
    if not (
        plan.side in (Side.LONG, Side.SHORT)
        and 1 <= plan.leverage <= 5
        and plan.quantity > 0
        and plan.stop_price > 0
        and plan.take_profit_price > 0
        and plan.side * (plan.entry_price - plan.stop_price) > 0
        and plan.side * (plan.take_profit_price - plan.entry_price) > 0
        and plan.loss_at_stop > 0
        and plan.liquidation_price >= 0
        and plan.initial_margin == plan.quantity * plan.entry_price / plan.leverage
    ):
        raise ValueError("Invalid order plan in paper ledger")


def _restore(payload: _Payload) -> PaperSnapshot:
    if not (payload.model_id and payload.config_id):
        raise ValueError("Paper snapshot requires immutable model and config IDs")
    _require_utc(payload.last_processed)
    _require_utc(payload.next_minute)
    _require_utc(payload.expected_funding)
    if payload.next_minute is not None and (
        payload.next_minute.second or payload.next_minute.microsecond
    ):
        raise ValueError("Paper funding cursor must be aligned to an exact minute")
    risk = payload.daily_risk
    if risk.day_halted != (risk.halted_on is not None) or (
        risk.halted_on is not None and risk.halted_on > risk.day
    ):
        raise ValueError("Inconsistent daily halt state")
    ledger = payload.portfolio
    totals = (
        ledger.balance,
        ledger.total_fees,
        ledger.total_funding,
        ledger.realized_pnl,
    )
    if not all(amount.is_finite() for amount in totals) or ledger.total_fees < 0:
        raise ValueError("Invalid totals in paper ledger")
    wallet = Portfolio(ledger.initial_balance)
    last_fill_at = None
    for trade in ledger.closed_trades:
        _validate_plan(trade.plan)
        _require_utc(trade.opened_at)
        _require_utc(trade.closed_at)
        amounts = (
            trade.exit_price,
            trade.entry_fee,
            trade.exit_fee,
            trade.gross_pnl,
            trade.funding,
        )
        if (
            not all(amount.is_finite() for amount in amounts)
            or (last_fill_at is not None and trade.opened_at < last_fill_at)
            or trade.closed_at < trade.opened_at
            or trade.exit_price <= 0
            or trade.entry_fee < 0
            or trade.exit_fee < 0
        ):
            raise ValueError("Invalid closed trade in paper ledger")
        last_fill_at = trade.closed_at
    if ledger.position is not None:
        position = ledger.position
        _validate_plan(position.plan)
        _require_utc(position.opened_at)
        if (
            not position.entry_fee.is_finite()
            or not position.funding.is_finite()
            or (last_fill_at is not None and position.opened_at < last_fill_at)
            or position.entry_fee < 0
        ):
            raise ValueError("Invalid position in paper ledger")
        last_fill_at = position.opened_at
    if last_fill_at is not None and (
        payload.last_processed is None or last_fill_at > payload.last_processed
    ):
        raise ValueError("Paper fill is ahead of the persisted quote cursor")
    wallet.balance = ledger.balance
    wallet.position = ledger.position
    wallet.closed_trades = list(ledger.closed_trades)
    wallet.total_fees = ledger.total_fees
    wallet.total_funding = ledger.total_funding
    wallet.realized_pnl = ledger.realized_pnl
    wallet._last_fill_at = last_fill_at
    return PaperSnapshot(
        wallet,
        risk,
        payload.last_processed,
        payload.model_id,
        payload.config_id,
        payload.next_minute,
        payload.expected_funding,
        payload.unverified_exposure_intervals,
    )


def _encode(snapshot: PaperSnapshot) -> str:
    wallet = snapshot.portfolio
    payload = _Payload(
        schema_version=1,
        model_id=snapshot.model_id,
        config_id=snapshot.config_id,
        last_processed=snapshot.last_processed,
        next_minute=snapshot.next_minute,
        expected_funding=snapshot.expected_funding,
        unverified_exposure_intervals=snapshot.unverified_exposure_intervals,
        daily_risk=snapshot.daily_risk,
        portfolio=_LedgerData(
            initial_balance=wallet.initial_balance,
            balance=wallet.balance,
            position=wallet.position,
            closed_trades=tuple(wallet.closed_trades),
            total_fees=wallet.total_fees,
            total_funding=wallet.total_funding,
            realized_pnl=wallet.realized_pnl,
        ),
    )
    raw = payload.model_dump_json()
    _restore(_Payload.model_validate_json(raw))
    return raw


class PaperStateStore:
    """Commit one current state in SQLite with optimistic writer conflict checks."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._revision = None
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS paper_snapshot (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    revision INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )
            """)

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            yield db

    @staticmethod
    def _row(db):
        return db.execute(
            "SELECT revision, payload FROM paper_snapshot WHERE singleton = 1"
        ).fetchone()

    def load(self, *, model_id: str, config_id: str) -> PaperSnapshot | None:
        with self._connect() as db:
            row = self._row(db)
        if row is None:
            self._revision = None
            return None
        revision, raw = row
        restored = _restore(_Payload.model_validate_json(raw))
        if (restored.model_id, restored.config_id) != (model_id, config_id):
            raise ValueError("Paper checkpoint belongs to a different model or config")
        self._revision = revision
        return restored

    def backup(self, destination: Path) -> None:
        """Publish a consistent SQLite backup to a path that does not exist."""
        if destination.exists():
            raise FileExistsError(destination)
        with NamedTemporaryFile(
            dir=destination.parent, suffix=".db", delete=False
        ) as temporary:
            staging = Path(temporary.name)
        try:
            with self._connect() as source, closing(sqlite3.connect(staging)) as target:
                source.backup(target)
                if target.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise ValueError("Pemeriksaan integritas backup paper gagal")
            destination.hardlink_to(staging)
        finally:
            staging.unlink(missing_ok=True)

    def save(self, snapshot: PaperSnapshot) -> None:
        raw = _encode(snapshot)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db)
            if row is None:
                if self._revision is not None:
                    raise ValueError("Paper checkpoint disappeared after load")
                revision = 1
                db.execute(
                    "INSERT INTO paper_snapshot VALUES (1, ?, ?)", (revision, raw)
                )
            else:
                previous_revision, previous_raw = row
                if previous_revision != self._revision:
                    raise ValueError(
                        "Paper checkpoint changed since the worker loaded it"
                    )
                previous = _Payload.model_validate_json(previous_raw)
                if (snapshot.model_id, snapshot.config_id) != (
                    previous.model_id,
                    previous.config_id,
                ):
                    raise ValueError(
                        "Paper checkpoint belongs to a different model or config"
                    )
                for current_cursor, previous_cursor in (
                    (snapshot.last_processed, previous.last_processed),
                    (snapshot.next_minute, previous.next_minute),
                ):
                    if previous_cursor is not None and (
                        current_cursor is None or current_cursor < previous_cursor
                    ):
                        raise ValueError("Paper checkpoint cursor cannot move backward")
                if (
                    snapshot.unverified_exposure_intervals
                    < previous.unverified_exposure_intervals
                ):
                    raise ValueError(
                        "Paper checkpoint cannot clear unverified exposure evidence"
                    )
                revision = previous_revision + 1
                db.execute(
                    "UPDATE paper_snapshot SET revision = ?, payload = ? WHERE singleton = 1",
                    (revision, raw),
                )
        self._revision = revision
