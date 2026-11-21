"""Persistent paper observations and UTC daily summaries."""

import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from .paper_worker import PaperWorker, PaperWorkerResult


class PaperAuditLog:
    def __init__(self, path: Path):
        self.path = path
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS paper_observations (
                    model_id TEXT NOT NULL,
                    config_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    equity TEXT NOT NULL,
                    realized_pnl TEXT NOT NULL,
                    cumulative_fees TEXT NOT NULL,
                    cumulative_funding TEXT NOT NULL,
                    closed_trades INTEGER NOT NULL,
                    unverified_exposure_intervals INTEGER NOT NULL,
                    position_side TEXT,
                    PRIMARY KEY (model_id, config_id, observed_at)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS paper_runtime_events (
                    id INTEGER PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    config_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    event TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS paper_runtime_events_day
                ON paper_runtime_events (model_id, config_id, observed_at)
            """)

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            yield db

    def observe(
        self,
        result: PaperWorkerResult,
        worker: PaperWorker,
        *,
        model_id: str,
        config_id: str,
    ) -> None:
        if result.observed_at.utcoffset() != timedelta(0):
            raise ValueError("Observasi paper memerlukan waktu UTC")
        if (
            result.observed_at != worker.last_processed
            or result.state != worker.health.state
        ):
            raise ValueError("Observasi tidak cocok dengan worker terakhir")
        wallet = worker.portfolio
        row = (
            model_id,
            config_id,
            result.observed_at.isoformat(timespec="microseconds"),
            result.state.value,
            worker.health.reason,
            str(result.equity),
            str(wallet.realized_pnl),
            str(wallet.total_fees),
            str(wallet.total_funding),
            len(wallet.closed_trades),
            worker.unverified_exposure_intervals,
            wallet.position.plan.side.name if wallet.position is not None else None,
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM paper_observations WHERE model_id=? AND config_id=? "
                "ORDER BY observed_at DESC LIMIT 1",
                row[:2],
            ).fetchone()
            if previous is not None and row[2] <= previous["observed_at"]:
                if tuple(previous) == row:
                    return
                raise ValueError(
                    "Observasi paper mundur atau berbeda pada timestamp yang sama"
                )
            db.execute(
                "INSERT INTO paper_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )

    def daily(self, day: date, *, model_id: str, config_id: str) -> dict:
        start = datetime.combine(day, time.min, UTC)
        end = start + timedelta(days=1)
        key = (model_id, config_id, start.isoformat(timespec="microseconds"))
        with self._connect() as db:
            observations = db.execute(
                "SELECT * FROM paper_observations WHERE model_id=? AND config_id=? "
                "AND observed_at>=? AND observed_at<? ORDER BY observed_at",
                (*key, end.isoformat(timespec="microseconds")),
            ).fetchall()
            prior = db.execute(
                "SELECT * FROM paper_observations WHERE model_id=? AND config_id=? "
                "AND observed_at<? ORDER BY observed_at DESC LIMIT 1",
                key,
            ).fetchone()
            events = dict(
                db.execute(
                    "SELECT event, COUNT(*) FROM paper_runtime_events WHERE model_id=? AND config_id=? "
                    "AND observed_at>=? AND observed_at<? GROUP BY event",
                    (*key, end.isoformat(timespec="microseconds")),
                ).fetchall()
            )
        result = {
            "utc_day": day.isoformat(),
            "observations": len(observations),
            "model_id": model_id,
            "config_id": config_id,
            "runtime_events": events,
        }
        if not observations:
            return result
        first, last = observations[0], observations[-1]
        peak = Decimal(first["equity"])
        drawdown = Decimal(0)
        for row in observations:
            equity = Decimal(row["equity"])
            peak = max(peak, equity)
            if peak > 0:
                drawdown = max(drawdown, (peak - equity) / peak)
        result.update(
            {
                "first_observed_at": first["observed_at"],
                "last_observed_at": last["observed_at"],
                "last_state": last["state"],
                "last_reason": last["reason"],
                "position_side": last["position_side"],
                "ending_equity": last["equity"],
                "observed_max_drawdown": str(drawdown),
                "unverified_exposure_intervals": last["unverified_exposure_intervals"],
            }
        )
        if prior is not None:
            for field in ("realized_pnl", "cumulative_fees", "cumulative_funding"):
                result[f"delta_{field}"] = str(
                    Decimal(last[field]) - Decimal(prior[field])
                )
            result["delta_closed_trades"] = (
                last["closed_trades"] - prior["closed_trades"]
            )
            result["delta_base_observed_at"] = prior["observed_at"]
        return result

    def event(
        self, observed_at: datetime, event: str, *, model_id: str, config_id: str
    ) -> None:
        if observed_at.utcoffset() != timedelta(0) or not event:
            raise ValueError("Event paper memerlukan label dan waktu UTC")
        with self._connect() as db:
            db.execute(
                "INSERT INTO paper_runtime_events (model_id, config_id, observed_at, event) VALUES (?, ?, ?, ?)",
                (
                    model_id,
                    config_id,
                    observed_at.isoformat(timespec="microseconds"),
                    event,
                ),
            )
