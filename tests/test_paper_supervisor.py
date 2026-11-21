from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from tradebot.execution import ExecutionState
from tradebot.paper import MarketSnapshot, PaperBatch, PaperFeedError
from tradebot.paper_audit import PaperAuditLog
from tradebot.paper_state import PaperStateStore
from tradebot.paper_supervisor import PaperSupervisor
from tradebot.paper_worker import PaperWorker
from tradebot.risk import MaintenanceBracket, OrderFilters

START = datetime(2025, 1, 1, tzinfo=UTC)
D = Decimal
FILTERS = OrderFilters(D(".1"), D(".001"), D(".001"), D(1), D(1))
BRACKETS = (MaintenanceBracket(D(0), D(1_000_000), D(".004"), D(0), 125),)
MODEL = "fixture-model"
CONFIG = "fixture-config"


class Fixture:
    def __init__(self, path, *, reconcile=None, on_result=None, on_event=None):
        self.elapsed = 0.0
        self.worker = PaperWorker(FILTERS, BRACKETS)
        self.store = PaperStateStore(path)
        self.futures = []
        self.events = []
        self.results = []
        self.supervisor = PaperSupervisor(
            self.worker,
            self.poll,
            self.store,
            model_id=MODEL,
            config_id=CONFIG,
            reconcile=reconcile or (lambda _worker, _batch: True),
            on_result=on_result or self.record_result,
            on_event=on_event or self.events.append,
            clock=self.clock,
            monotonic_clock=lambda: self.elapsed,
            sleeper=self.advance,
            submit=self.submit,
        )

    @staticmethod
    def poll():
        raise AssertionError("Offline future must not call network")

    def clock(self):
        return START + timedelta(seconds=self.elapsed)

    def advance(self, seconds):
        self.elapsed += seconds

    def submit(self, poll):
        assert poll == self.poll
        future = Future()
        self.futures.append(future)
        return future

    def batch(self):
        now = self.clock()
        return PaperBatch(
            (),
            MarketSnapshot(now, now, now, D(100), D(101), D(1), D(1), D(100), 0),
            True,
        )

    def record_result(self, result):
        snapshot = self.store.load(model_id=MODEL, config_id=CONFIG)
        assert snapshot is not None and snapshot.last_processed == result.observed_at
        assert self.worker.health.state == result.state
        self.results.append(result)


def test_watchdog_runs_with_poll_pending_then_requires_reconciliation(tmp_path):
    fixture = Fixture(tmp_path / "paper.db")
    supervisor = fixture.supervisor
    supervisor.step()
    fixture.futures[0].set_result(fixture.batch())
    supervisor.step()
    assert fixture.worker.health.state == ExecutionState.READY
    assert fixture.results[0].state == ExecutionState.RECONCILING

    fixture.advance(1)
    supervisor.step()
    assert len(fixture.futures) == 2
    fixture.advance(5)
    supervisor.step()
    assert len(fixture.futures) == 2
    assert fixture.worker.health.state == ExecutionState.HALTED
    assert fixture.events == ["reconciled", "market_stale"]
    fixture.futures[1].set_result(fixture.batch())
    supervisor.step()
    assert fixture.results[-1].state == ExecutionState.HALTED
    assert fixture.events[-1] == "reconciled"
    supervisor.close()


def test_rejected_reconciliation_stays_halted(tmp_path):
    fixture = Fixture(tmp_path / "paper.db", reconcile=lambda _worker, _batch: False)
    fixture.supervisor.step()
    fixture.futures[0].set_result(fixture.batch())
    fixture.supervisor.step()
    assert fixture.worker.health.state == ExecutionState.HALTED
    assert fixture.events == ["ledger_mismatch"]
    fixture.supervisor.close()


def test_supervision_checkpoints_and_audits_before_reconciliation(tmp_path):
    path = tmp_path / "paper.db"
    audit = PaperAuditLog(path)
    identity = {"model_id": MODEL, "config_id": CONFIG}

    def observe(result):
        durable = fixture.store.load(**identity)
        assert durable.last_processed == result.observed_at
        audit.observe(result, fixture.worker, **identity)

    fixture = Fixture(
        path,
        on_result=observe,
        on_event=lambda event: audit.event(fixture.clock(), event, **identity),
    )
    fixture.supervisor.step()
    fixture.futures[0].set_result(fixture.batch())
    fixture.supervisor.step()
    fixture.advance(30)
    fixture.supervisor.step()
    daily = audit.daily(START.date(), **identity)
    assert daily["observations"] == 1
    assert daily["last_state"] == ExecutionState.RECONCILING.value
    assert daily["runtime_events"] == {
        "reconciled": 1,
        "market_stale": 1,
        "heartbeat": 1,
    }
    fixture.supervisor.close()


def test_transient_poll_failure_waits_then_resubmits(tmp_path):
    fixture = Fixture(tmp_path / "paper.db")
    fixture.supervisor.step()
    fixture.futures[0].set_exception(PaperFeedError("fixture outage"))
    fixture.supervisor.step()
    fixture.advance(4)
    fixture.supervisor.step()
    assert len(fixture.futures) == 1
    assert fixture.events == ["poll_failed"]
    fixture.advance(1)
    fixture.supervisor.step()
    assert len(fixture.futures) == 2
    fixture.supervisor.close()


def test_rate_limit_stops_without_retry(tmp_path):
    fixture = Fixture(tmp_path / "paper.db")
    fixture.supervisor.step()
    error = PaperFeedError("fixture rate limit")
    error.__cause__ = HTTPError("https://example.invalid", 429, "limited", {}, None)
    fixture.futures[0].set_exception(error)
    with pytest.raises(PaperFeedError):
        fixture.supervisor.step()
    assert fixture.worker.health.state == ExecutionState.HALTED
    with pytest.raises(RuntimeError, match="ditutup"):
        fixture.supervisor.step()
    assert len(fixture.futures) == 1


def test_audit_failure_stops_after_ledger_checkpoint(tmp_path):
    def failed_audit(_result):
        raise OSError("fixture audit failure")

    fixture = Fixture(tmp_path / "paper.db", on_result=failed_audit)
    fixture.supervisor.step()
    fixture.futures[0].set_result(fixture.batch())
    with pytest.raises(OSError, match="audit failure"):
        fixture.supervisor.step()
    assert fixture.worker.health.state == ExecutionState.HALTED
    assert fixture.events == []
    assert fixture.store.load(model_id=MODEL, config_id=CONFIG) is not None


def test_run_stops_and_discards_pending_poll(tmp_path):
    fixture = Fixture(tmp_path / "paper.db")
    fixture.supervisor.run(lambda: fixture.elapsed >= 2)
    assert fixture.elapsed == 2
    assert len(fixture.futures) == 1 and fixture.futures[0].cancelled()
    assert fixture.results == []
