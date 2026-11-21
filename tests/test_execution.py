from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradebot.execution import (
    EntryIntent,
    ExecutionState,
    FaultInjectingExchange,
    PaperRecovery,
    Protection,
)
from tradebot.reconciliation import OrderJournal
from tradebot.risk import Side

NOW = datetime(2025, 1, 1, tzinfo=UTC)
INTENT = EntryIntent("example", Side.LONG, Decimal(1), Decimal(900), Decimal(1100))


def fresh(recovery):
    recovery.observe_market(now=NOW, quote_time=NOW, mark_time=NOW, clock_drift=timedelta(0))
    recovery.reconcile()


@pytest.fixture
def harness(tmp_path):
    journal = OrderJournal(tmp_path / "paper.sqlite")
    exchange = FaultInjectingExchange()
    recovery = PaperRecovery(journal, exchange)
    fresh(recovery)
    return journal, exchange, recovery


def test_unknown_entry_reconciled_after_restart_by_id(harness):
    journal, exchange, recovery = harness
    exchange.faults["entry_after"] = 1
    recovery.submit_entry(INTENT)
    assert recovery.state == ExecutionState.HALTED
    assert journal.unresolved()[0].state == "unknown"
    assert exchange.position == INTENT.quantity
    assert exchange.calls["entry"] == 1

    restart = PaperRecovery(OrderJournal(journal.path), exchange)
    fresh(restart)
    assert restart.state == ExecutionState.READY
    assert exchange.protection == Protection(INTENT.quantity, INTENT.stop, INTENT.target)
    with pytest.raises(RuntimeError):
        restart.submit_entry(INTENT)
    assert exchange.calls["entry"] == 1


def test_partial_fill_updates_exact_protection(harness):
    _, exchange, recovery = harness
    exchange.next_entry_fill = Decimal("0.25")
    recovery.submit_entry(INTENT)
    assert exchange.protection == Protection(Decimal("0.25"), INTENT.stop, INTENT.target)

    exchange.advance_fill(Decimal("0.75"))
    recovery.reconcile()
    assert exchange.protection == Protection(Decimal("0.75"), INTENT.stop, INTENT.target)
    assert exchange.calls["close"] == 0


def test_protection_timeout_after_ack_does_not_close(harness):
    _, exchange, recovery = harness
    exchange.faults["protection_after"] = 1
    recovery.submit_entry(INTENT)
    assert recovery.state == ExecutionState.READY
    assert exchange.protection == Protection(INTENT.quantity, INTENT.stop, INTENT.target)
    assert exchange.calls["close"] == 0


def test_failed_protection_cancels_remainder_and_reconciles_lost_close_ack(harness):
    journal, exchange, recovery = harness
    exchange.next_entry_fill = Decimal("0.25")
    exchange.faults["protection_before"] = 1
    exchange.faults["close_after"] = 1
    recovery.submit_entry(INTENT)
    assert exchange.calls["cancel"] == 1
    assert exchange.orders["example"].state == "canceled"
    assert exchange.orders["example-close"].cumulative_fill == Decimal("0.25")
    assert recovery.state == ExecutionState.HALTED
    assert journal.unresolved()[0].state == "unknown"

    restart = PaperRecovery(OrderJournal(journal.path), exchange)
    fresh(restart)
    assert restart.state == ExecutionState.HALTED
    assert not journal.unresolved()
    assert exchange.position == 0 and exchange.protection is None
    assert exchange.calls["close"] == 1
    restart.recover()
    assert restart.state == ExecutionState.READY


def test_entry_timeout_before_exchange_processing_stays_halted(harness):
    journal, exchange, recovery = harness
    exchange.faults["entry_before"] = 1
    recovery.submit_entry(INTENT)
    recovery.reconcile()
    recovery.reconcile()
    assert recovery.state == ExecutionState.HALTED
    assert journal.unresolved()[0].state == "unknown"
    assert exchange.calls["entry"] == 1


def test_cancel_timeout_before_emergency_close_is_recoverable(harness):
    journal, exchange, recovery = harness
    exchange.next_entry_fill = Decimal("0.25")
    exchange.faults["protection_before"] = 1
    exchange.faults["cancel"] = 1
    recovery.submit_entry(INTENT)
    assert exchange.calls["close"] == 0
    assert journal.state(INTENT.client_id) == "partial"

    recovery.reconcile()
    assert recovery.state == ExecutionState.HALTED
    assert journal.state(INTENT.client_id) == "canceled"
    assert exchange.position == 0
    assert exchange.calls["close"] == 1


def test_stale_data_persists_across_restart_without_disabling_protection(harness):
    journal, exchange, recovery = harness
    recovery.submit_entry(INTENT)
    recovery.observe_market(
        now=NOW + timedelta(seconds=6),
        quote_time=NOW,
        mark_time=NOW,
        clock_drift=timedelta(0),
    )
    assert recovery.state == ExecutionState.HALTED
    assert exchange.protection == Protection(INTENT.quantity, INTENT.stop, INTENT.target)

    restart = PaperRecovery(OrderJournal(journal.path), exchange)
    fresh(restart)
    assert restart.state == ExecutionState.HALTED
    restart.recover()
    assert restart.state == ExecutionState.READY
    assert exchange.protection == Protection(INTENT.quantity, INTENT.stop, INTENT.target)
