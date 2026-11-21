from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradebot.execution import ExecutionState
from tradebot.market_data import Candle, Minute
from tradebot.paper import MarketSnapshot, PaperBatch, PaperFeedError
from tradebot.paper_strategy import PaperEntrySignals
from tradebot.runtime_health import RuntimeHealth

START = datetime(2025, 1, 1, tzinfo=UTC)


def snapshot(stamp, *, drift=0):
    return MarketSnapshot(
        stamp, stamp, stamp, Decimal(100), Decimal(101), Decimal(1), Decimal(1), Decimal(100), drift
    )


def minute(index):
    price = Decimal(9000 + index)
    row = Candle(
        START + timedelta(minutes=index), price, price + 3, price - 2, price + 1, Decimal(2)
    )
    return Minute(row, row)


def test_watchdog_requires_fresh_reconciled_feed_and_halts_on_stale():
    health = RuntimeHealth(PaperEntrySignals())
    assert health.state == ExecutionState.RECONCILING
    with pytest.raises(RuntimeError, match="data segar"):
        health.confirm_reconciled(START, ledger_matches=True)
    health.observe(PaperBatch((), snapshot(START), True), START)
    assert health.state == ExecutionState.RECONCILING
    health.confirm_reconciled(START, ledger_matches=True)
    assert health.tick(START + timedelta(seconds=5)) == ExecutionState.READY
    assert health.tick(START + timedelta(seconds=5, milliseconds=1)) == ExecutionState.HALTED
    assert health.reason == "market_stale"


def test_failed_poll_and_ledger_mismatch_disarm_and_require_explicit_reconciliation():
    class FailingFeed:
        def poll(self):
            raise PaperFeedError("fixture connection lost")

    health = RuntimeHealth(PaperEntrySignals())
    initial = PaperBatch((), snapshot(START), True)
    health.observe(initial, START)
    health.confirm_reconciled(START, ledger_matches=True)
    with pytest.raises(PaperFeedError, match="connection lost"):
        health.poll(FailingFeed())
    assert health.state == ExecutionState.HALTED
    assert health.reason == "poll_failed"
    health.observe(initial, START)
    assert health.state == ExecutionState.HALTED
    with pytest.raises(RuntimeError, match="Ledger"):
        health.confirm_reconciled(START, ledger_matches=False)
    health.observe(initial, START)
    health.confirm_reconciled(START, ledger_matches=True)
    assert health.state == ExecutionState.READY


def test_excessive_clock_drift_blocks_receipt():
    health = RuntimeHealth(PaperEntrySignals())
    with pytest.raises(PaperFeedError, match="kedaluwarsa"):
        health.observe(PaperBatch((), snapshot(START, drift=1001), True), START)
    assert health.state == ExecutionState.HALTED


def test_causal_intent_available_only_after_reconciliation():
    policy_calls = []

    def policy(features):
        policy_calls.append(features.signal_time)
        return "LONG"

    health = RuntimeHealth(PaperEntrySignals(policy))
    signal = START + timedelta(hours=50)
    previous = signal - timedelta(seconds=1)
    warmup = PaperBatch(tuple(minute(index) for index in range(2999)), snapshot(previous), True)
    assert health.observe(warmup, previous) is None
    assert policy_calls == []
    health.confirm_reconciled(previous, ledger_matches=True)

    received = signal + timedelta(seconds=1)
    entry = health.observe(PaperBatch((minute(2999),), snapshot(received), True), received)
    assert entry is not None
    assert entry.signal_time == signal
    assert policy_calls == [signal]


def test_catch_up_requires_reconcile_before_readiness():
    health = RuntimeHealth(PaperEntrySignals())
    health.observe(PaperBatch((), snapshot(START), True), START)
    health.confirm_reconciled(START, ledger_matches=True)
    health.observe(PaperBatch((), snapshot(START), False), START)
    assert health.state == ExecutionState.RECONCILING
    with pytest.raises(RuntimeError, match="menyusul pasar"):
        health.confirm_reconciled(START, ledger_matches=True)


def test_actual_worker_receipt_is_used_to_detect_delayed_poll():
    class DelayedFeed:
        def poll(self):
            return PaperBatch((), snapshot(START), True)

    health = RuntimeHealth(PaperEntrySignals(), clock=lambda: START + timedelta(seconds=6))
    with pytest.raises(PaperFeedError, match="kedaluwarsa"):
        health.poll(DelayedFeed())
    assert health.state == ExecutionState.HALTED
