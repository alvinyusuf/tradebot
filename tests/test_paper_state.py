import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradebot.execution import ExecutionState
from tradebot.market_data import Candle, Minute
from tradebot.paper import MarketSnapshot, PaperBatch
from tradebot.paper_state import PaperSnapshot, PaperStateStore
from tradebot.paper_worker import PaperWorker
from tradebot.portfolio import Portfolio
from tradebot.risk import DailyRisk, MaintenanceBracket, OrderFilters, OrderPlan, Side

D = Decimal
NOW = datetime(2026, 1, 1, tzinfo=UTC)
FEE = D(".0005")
PLAN = OrderPlan(
    Side.SHORT, D(".01"), D(100), D(104), D(92), 2, D(".5"), D(".05"), D(150)
)


def new_snapshot():
    portfolio = Portfolio(D(100))
    state = DailyRisk(NOW.date(), D(100))
    return PaperSnapshot(portfolio, state, NOW, "model-1", "config-1", NOW)


def load(store):
    return store.load(model_id="model-1", config_id="config-1")


def test_backup_restores_snapshot_without_overwriting_destination(tmp_path):
    state = PaperStateStore(tmp_path / "paper.sqlite")
    snapshot = new_snapshot()
    state.save(snapshot)
    destination = tmp_path / "paper-backup.sqlite"
    state.backup(destination)
    later = NOW + timedelta(minutes=1)
    state.save(replace(snapshot, last_processed=later, next_minute=later))
    restored = load(PaperStateStore(destination))
    assert restored.last_processed == NOW
    assert restored.portfolio.balance == snapshot.portfolio.balance
    with pytest.raises(FileExistsError):
        state.backup(destination)
    assert load(PaperStateStore(destination)).last_processed == NOW


def test_snapshot_restart_preserves_wallet_exactly_and_keeps_both_halts(tmp_path):
    path = tmp_path / "paper.sqlite"
    snapshot = new_snapshot()
    initial_store = PaperStateStore(path)
    portfolio = snapshot.portfolio
    earlier = NOW - timedelta(hours=1)
    portfolio.open(PLAN, earlier, FEE)
    portfolio.close(D(96), earlier + timedelta(minutes=10), FEE, "profit")
    portfolio.open(PLAN, NOW, FEE)
    portfolio.book_funding_at(
        D(99), D(".00001234567890123456789"), NOW + timedelta(seconds=1)
    )
    snapshot.daily_risk.observe(NOW, D(95), flat=False)
    snapshot.daily_risk.halt_system()
    snapshot = replace(snapshot, last_processed=NOW + timedelta(seconds=5))
    initial_store.save(snapshot)

    reopened = PaperStateStore(path)
    restored = load(reopened)
    assert restored.last_processed == snapshot.last_processed
    assert restored.next_minute == NOW
    assert restored.daily_risk == snapshot.daily_risk
    assert (
        restored.daily_risk.entry_halted and restored.daily_risk.halted_on == NOW.date()
    )
    assert restored.portfolio is not portfolio
    assert restored.portfolio.closed_trades == portfolio.closed_trades
    assert restored.portfolio.position == portfolio.position
    assert restored.portfolio.balance == portfolio.balance
    assert restored.portfolio.total_fees == portfolio.total_fees
    assert restored.portfolio.total_funding == portfolio.total_funding
    assert restored.portfolio.realized_pnl == portfolio.realized_pnl
    with pytest.raises(ValueError, match="chronological"):
        restored.portfolio.close(D(90), NOW - timedelta(seconds=1), FEE, "invalid")

    tomorrow = NOW + timedelta(days=1)
    restored.portfolio.close(D(98), tomorrow, FEE, "paper_end")
    restored.daily_risk.observe(tomorrow, restored.portfolio.balance, flat=True)
    assert not restored.daily_risk.day_halted and restored.daily_risk.system_halted
    reopened.save(replace(restored, last_processed=tomorrow, next_minute=tomorrow))
    assert load(PaperStateStore(path)).portfolio.position is None


def test_delayed_funding_matches_position_that_held_before_settlement(tmp_path):
    path = tmp_path / "paper.sqlite"
    store = PaperStateStore(path)
    state = new_snapshot()
    wallet = state.portfolio
    wallet.open(PLAN, NOW - timedelta(minutes=4), FEE)
    first = wallet.close(D(99), NOW, FEE, "stop")
    wallet.open(PLAN, NOW, FEE)
    cash = wallet.book_funding_at(D(99), D(".001"), NOW)
    assert cash == D(".00099")
    assert wallet.position.funding == 0
    assert wallet.closed_trades[0].net_pnl == first.net_pnl + cash
    store.save(state)
    restored = load(PaperStateStore(path))
    assert restored.portfolio.total_funding == cash
    assert restored.portfolio.closed_trades[0].funding == cash
    assert (
        restored.portfolio.book_funding_at(D(99), D(".001"), NOW - timedelta(hours=1))
        == 0
    )


def test_checkpoint_rejects_other_model_backwards_cursors_and_a_stale_writer(tmp_path):
    path = tmp_path / "paper.sqlite"
    writer = PaperStateStore(path)
    later_writer = PaperStateStore(path)
    state = new_snapshot()
    writer.save(state)
    with pytest.raises(ValueError, match="different model"):
        later_writer.load(model_id="model-2", config_id="config-1")
    old = load(later_writer)
    with pytest.raises(ValueError, match="backward"):
        writer.save(replace(state, next_minute=NOW - timedelta(minutes=1)))
    writer.save(replace(state, next_minute=NOW + timedelta(minutes=1)))
    with pytest.raises(ValueError, match="changed"):
        later_writer.save(old)
    assert load(later_writer).next_minute == NOW + timedelta(minutes=1)


def test_unknown_snapshot_schema_fails_closed(tmp_path):
    path = tmp_path / "paper.sqlite"
    writer = PaperStateStore(path)
    writer.save(new_snapshot())
    with closing(sqlite3.connect(path)) as db, db:
        raw = db.execute("SELECT payload FROM paper_snapshot").fetchone()[0]
        payload = json.loads(raw)
        assert payload["schema_version"] == 1
        assert type(payload["portfolio"]["balance"]) is str
        payload["schema_version"] = 2
        db.execute("UPDATE paper_snapshot SET payload = ?", (json.dumps(payload),))
    with pytest.raises(ValueError, match="schema_version"):
        load(PaperStateStore(path))


def test_worker_preserves_pending_funding_and_unverified_exposure_across_restart(
    tmp_path,
):
    filters = OrderFilters(D(".1"), D(".001"), D(".001"), D(1), D(1))
    brackets = (MaintenanceBracket(D(0), D(100000), D(".004"), D(0), 125),)
    store = PaperStateStore(tmp_path / "paper.sqlite")
    wallet = Portfolio(D(100))
    wallet.open(PLAN, NOW - timedelta(minutes=2), FEE)
    worker = PaperWorker(
        filters,
        brackets,
        portfolio=wallet,
        daily_risk=DailyRisk(NOW.date(), D(100)),
        next_minute=NOW,
    )
    funding_time = NOW + timedelta(seconds=30)
    observed = NOW + timedelta(seconds=1)

    def quote(time, next_funding):
        return MarketSnapshot(
            time, time, time, D(98), D(100), D(1), D(1), D(99), 0, next_funding
        )

    worker.process(PaperBatch((), quote(observed, funding_time), True), observed)
    worker.health.confirm_reconciled(observed, ledger_matches=True)
    assert worker.tick(observed + timedelta(seconds=6)) == ExecutionState.HALTED
    worker.checkpoint(store, model_id="model-1", config_id="config-1")
    persisted = load(store)
    assert persisted.expected_funding == funding_time
    assert persisted.unverified_exposure_intervals == 1
    assert persisted.next_minute == NOW

    resumed_store = PaperStateStore(store.path)
    resumed = PaperWorker.restore(
        filters, brackets, resumed_store, model_id="model-1", config_id="config-1"
    )
    assert resumed.health.state == ExecutionState.RECONCILING
    assert resumed.unverified_exposure_intervals >= 1
    after_close = NOW + timedelta(minutes=1, seconds=1)
    candle = Candle(NOW, D(99), D(99), D(99), D(99), D(1))
    minute = Minute(candle, candle, D(".001"), funding_time, D(99))
    later_funding = funding_time + timedelta(hours=8)
    resumed.process(
        PaperBatch((minute,), quote(after_close, later_funding), True), after_close
    )
    resumed.checkpoint(resumed_store, model_id="model-1", config_id="config-1")
    persisted = load(resumed_store)
    assert persisted.portfolio.total_funding == D(".00099")
    assert persisted.portfolio.position.funding == D(".00099")
    assert persisted.expected_funding == later_funding
    assert persisted.next_minute == NOW + timedelta(minutes=1)
    assert persisted.unverified_exposure_intervals >= 1
