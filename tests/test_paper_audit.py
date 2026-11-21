from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradebot.execution import ExecutionState
from tradebot.paper_audit import PaperAuditLog
from tradebot.paper_worker import PaperWorker, PaperWorkerResult
from tradebot.risk import OrderFilters


def test_paper_audit_persists_and_summarizes_observations_by_utc_day(tmp_path):
    path = tmp_path / "paper.db"
    journal = PaperAuditLog(path)
    identity = {"model_id": "fixture-model", "config_id": "fixture-config"}
    midnight = datetime(2025, 1, 2, tzinfo=UTC)
    unit = Decimal(1)
    worker = PaperWorker(OrderFilters(unit, unit, unit, unit, unit), ())
    state = ExecutionState.RECONCILING

    def record(at, equity):
        worker.last_processed = at
        result = PaperWorkerResult(state, at, Decimal(equity))
        journal.observe(result, worker, **identity)
        return result

    record(midnight - timedelta(microseconds=1), 100)
    record(midnight, 101)
    worker.portfolio.total_fees = Decimal(".1")
    last = record(midnight + timedelta(minutes=1), 100)
    journal.observe(last, worker, **identity)
    journal.event(midnight, "reconciling", **identity)
    journal.event(midnight + timedelta(days=1), "heartbeat", **identity)
    daily = PaperAuditLog(path).daily(midnight.date(), **identity)
    assert daily["observations"] == 2
    assert daily["ending_equity"] == "100"
    assert Decimal(daily["observed_max_drawdown"]) == Decimal(1) / 101
    assert daily["delta_cumulative_fees"] == "0.1"
    assert daily["runtime_events"] == {"reconciling": 1}
    with pytest.raises(ValueError, match="berbeda"):
        journal.observe(
            PaperWorkerResult(state, last.observed_at, Decimal(99)), worker, **identity
        )
