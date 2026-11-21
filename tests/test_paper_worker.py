from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradebot.execution import ExecutionState
from tradebot.market_data import Candle, DatasetError, Minute
from tradebot.paper import MarketSnapshot, PaperBatch, PaperFeedError
from tradebot.paper_state import PaperStateStore
from tradebot.paper_worker import PaperWorker
from tradebot.risk import MaintenanceBracket, OrderFilters

START = datetime(2025, 1, 1, tzinfo=UTC)
SIGNAL = START + timedelta(hours=50)
D = Decimal
FILTERS = OrderFilters(D("0.1"), D("0.001"), D("0.001"), D(1), D(1))
BRACKETS = (MaintenanceBracket(D(0), D(1_000_000), D("0.004"), D(0), 125),)
TYPICAL_BID = D(10_000)
TYPICAL_ASK = D(10_001)
TYPICAL_DEPTH = D(1)


def minute(index, *, settlement=None):
    time = START + timedelta(minutes=index)
    price = D(10_000) + D(index) / 1000
    row = Candle(time, price, price + 1, price - 1, price, D(2))
    return (
        Minute(row, row, D("0.001"), settlement, price)
        if settlement
        else Minute(row, row)
    )


def snapshot(
    time,
    *,
    bid=TYPICAL_BID,
    ask=TYPICAL_ASK,
    mark=TYPICAL_BID,
    depth=TYPICAL_DEPTH,
    funding=None,
):
    return MarketSnapshot(time, time, time, bid, ask, depth, depth, mark, 0, funding)


def warmed_worker(*, funding=None, position_policy=None):
    worker = PaperWorker(
        FILTERS, BRACKETS, policy=lambda _: "LONG", position_policy=position_policy
    )
    warm_at = SIGNAL - timedelta(seconds=1)
    warm = tuple(minute(index) for index in range(2999))
    first = worker.process(
        PaperBatch(warm, snapshot(warm_at, funding=funding), True), warm_at
    )
    assert first.opened is None
    worker.health.confirm_reconciled(warm_at, ledger_matches=True)
    return worker


def test_simulates_causal_quote_entry_and_mark_stop():
    worker = warmed_worker()
    at = SIGNAL + timedelta(seconds=1)
    result = worker.process(PaperBatch((minute(2999),), snapshot(at), True), at)
    assert result.state == ExecutionState.READY
    assert result.opened is not None and result.opened.entry_price == D(10_001)
    assert worker.portfolio.position.opened_at == at

    at += timedelta(seconds=1)
    stop = result.opened.stop_price
    stopped = worker.process(
        PaperBatch((), snapshot(at, bid=stop - 1, ask=stop, mark=stop), True), at
    )
    assert stopped.closed is not None
    assert stopped.closed.reason == "stop_loss"
    assert stopped.closed.exit_price == stop - 1
    assert worker.portfolio.position is None


@pytest.mark.parametrize(
    ("entry", "exit_price"), [("LONG", TYPICAL_BID), ("SHORT", TYPICAL_ASK)]
)
def test_position_policy_uses_closed_mark_and_causal_policy_exit(entry, exit_price):
    calls = []

    def policy(decision, *, portfolio, daily_risk, mark):
        calls.append((decision, mark, daily_risk is not None))
        return entry if portfolio.position is None else "CLOSE"

    worker = warmed_worker(position_policy=policy)
    first = SIGNAL + timedelta(seconds=1)
    entered = worker.process(PaperBatch((minute(2999),), snapshot(first), True), first)
    assert entered.opened is not None
    assert calls[0][1:] == (minute(2999).mark.close, True)

    for offset in range(4, 900, 4):
        at = first + timedelta(seconds=offset)
        minutes = (minute(2999 + offset // 60),) if offset % 60 == 0 else ()
        worker.process(PaperBatch(minutes, snapshot(at), True), at)
    at = first + timedelta(minutes=15)
    last = minute(3014)
    last = replace(last, contract=replace(last.contract, volume=D(0)))
    late_quote = replace(snapshot(at), quote_time=at - timedelta(seconds=2))
    worker.process(PaperBatch((last,), late_quote, True), at)
    assert worker.portfolio.position is not None
    assert calls[-1][0].volume_ok is False
    assert calls[-1][1] == last.mark.close

    at += timedelta(seconds=1)
    result = worker.process(PaperBatch((), snapshot(at), True), at)
    assert result.closed is not None
    assert result.closed.reason == "policy_close"
    assert result.closed.exit_price == exit_price
    assert len(calls) == 2


@pytest.mark.parametrize("action", ["WAIT", "HOLD", "CLOSE"])
def test_flat_position_policy_inactive_actions_never_enter(action):
    worker = warmed_worker(position_policy=lambda _decision, **_account: action)
    at = SIGNAL + timedelta(seconds=1)
    result = worker.process(PaperBatch((minute(2999),), snapshot(at), True), at)
    assert result.opened is None and result.closed is None
    assert worker.portfolio.position is None


def test_catch_up_and_unready_do_not_fill():
    worker = warmed_worker()
    worker.health.fail("disconnected")
    at = SIGNAL + timedelta(seconds=1)
    result = worker.process(PaperBatch((minute(2999),), snapshot(at), True), at)
    assert result.state == ExecutionState.HALTED
    assert result.opened is None
    assert worker.portfolio.position is None


def test_policy_failure_halts_worker_before_fill():
    def failing_policy(_decision, **_account):
        raise RuntimeError("fixture inference failure")

    worker = warmed_worker(position_policy=failing_policy)
    at = SIGNAL + timedelta(seconds=1)
    with pytest.raises(DatasetError, match="Inferensi"):
        worker.process(PaperBatch((minute(2999),), snapshot(at), True), at)
    assert worker.health.state == ExecutionState.HALTED
    assert worker.portfolio.position is None


def test_refuses_entry_while_known_funding_boundary_is_unverified():
    worker = warmed_worker(funding=SIGNAL)
    at = SIGNAL + timedelta(seconds=1)
    result = worker.process(PaperBatch((minute(2999),), snapshot(at), True), at)
    assert result.opened is None
    assert worker.rejections["funding_pending"] == 1


def test_restored_funding_schedule_refuses_to_skip_missing_settlement(tmp_path):
    worker = warmed_worker(funding=SIGNAL)
    cursor = SIGNAL + timedelta(seconds=1)
    worker.process(PaperBatch((minute(2999),), snapshot(cursor), True), cursor)
    store = PaperStateStore(tmp_path / "paper.db")
    worker.checkpoint(store, model_id="frozen", config_id="v0.1")
    restored = PaperWorker.restore(
        FILTERS, BRACKETS, store, model_id="frozen", config_id="v0.1"
    )
    at = cursor + timedelta(minutes=1)
    with pytest.raises(DatasetError, match="Settlement funding"):
        restored.process(PaperBatch((minute(3000),), snapshot(at), True), at)
    assert restored.next_minute == SIGNAL
    assert restored.health.state == ExecutionState.HALTED


def test_books_late_settlement_on_already_closed_trade_once():
    worker = warmed_worker()
    opened_at = SIGNAL + timedelta(seconds=1)
    start = worker.process(
        PaperBatch((minute(2999),), snapshot(opened_at), True), opened_at
    )
    assert start.opened is not None
    settled_at = SIGNAL + timedelta(seconds=2)
    closed_at = SIGNAL + timedelta(seconds=3)
    stop = start.opened.stop_price
    stop_snapshot = snapshot(closed_at, bid=stop - 1, ask=stop, mark=stop)
    stopped = worker.process(PaperBatch((), stop_snapshot, True), closed_at)
    assert stopped.closed is not None and stopped.closed.funding == 0

    next_bar_at = SIGNAL + timedelta(minutes=1, seconds=1)
    worker.process(
        PaperBatch((minute(3000, settlement=settled_at),), snapshot(next_bar_at), True),
        next_bar_at,
    )
    assert worker.portfolio.closed_trades[-1].funding < 0
    assert worker.portfolio.total_funding == worker.portfolio.closed_trades[-1].funding
    assert worker.next_minute == SIGNAL + timedelta(minutes=1)
    worker.process(
        PaperBatch((), snapshot(next_bar_at, funding=next_bar_at), True), next_bar_at
    )
    assert worker.portfolio.total_funding == worker.portfolio.closed_trades[-1].funding


def test_entry_refuses_quantity_larger_than_displayed_depth():
    worker = warmed_worker()
    at = SIGNAL + timedelta(seconds=1)
    result = worker.process(
        PaperBatch((minute(2999),), snapshot(at, depth=D("0.00001")), True), at
    )
    assert result.opened is None
    assert worker.rejections["entry_depth_unavailable"] == 1


def test_stale_mark_cannot_close_position():
    worker = warmed_worker()
    entered_at = SIGNAL + timedelta(seconds=1)
    first = worker.process(
        PaperBatch((minute(2999),), snapshot(entered_at), True), entered_at
    )
    assert first.opened is not None
    trigger = snapshot(entered_at, mark=first.opened.stop_price)
    late = entered_at + timedelta(seconds=6)
    with pytest.raises(PaperFeedError, match="kedaluwarsa"):
        worker.process(PaperBatch((), trigger, True), late)
    assert worker.portfolio.position is not None
    assert not worker.portfolio.closed_trades


def test_restart_restores_exact_ledger_then_waits_for_reconciliation(tmp_path):
    worker = warmed_worker()
    at = SIGNAL + timedelta(seconds=1)
    worker.process(PaperBatch((minute(2999),), snapshot(at), True), at)
    assert worker.portfolio.position is not None
    state_path = tmp_path / "paper.db"
    store = PaperStateStore(state_path)
    worker.checkpoint(store, model_id="frozen", config_id="v0.1")

    restarted_store = PaperStateStore(state_path)
    restarted = PaperWorker.restore(
        FILTERS, BRACKETS, restarted_store, model_id="frozen", config_id="v0.1"
    )
    assert restarted.portfolio.position == worker.portfolio.position
    assert restarted.portfolio.balance == worker.portfolio.balance
    assert restarted.portfolio.total_fees == worker.portfolio.total_fees
    assert restarted.daily_risk == worker.daily_risk
    assert restarted.next_minute == worker.next_minute
    assert restarted.last_processed == worker.last_processed
    assert restarted.health.state == ExecutionState.RECONCILING
    later = at + timedelta(seconds=1)
    report = restarted.process(PaperBatch((), snapshot(later), True), later)
    assert report.opened is None
    assert restarted.health.state == ExecutionState.RECONCILING
    restarted.health.confirm_reconciled(later, ledger_matches=True)
    assert restarted.health.state == ExecutionState.READY
    restarted.checkpoint(restarted_store, model_id="frozen", config_id="v0.1")


def test_midnight_baseline_after_earlier_tick_exit_uses_prior_open_position():
    worker = warmed_worker()
    entered_at = SIGNAL + timedelta(seconds=1)
    first = worker.process(
        PaperBatch((minute(2999),), snapshot(entered_at), True), entered_at
    )
    assert first.opened is not None
    prior = worker.portfolio.position
    prior_balance = worker.portfolio.balance
    midnight = START + timedelta(days=3)
    # A recovered feed began at the midnight boundary with an already
    # persisted position, before its complete midnight bar was available.
    resumed = PaperWorker(
        FILTERS,
        BRACKETS,
        portfolio=worker.portfolio,
        daily_risk=worker.daily_risk,
        next_minute=midnight,
    )
    stop = first.opened.stop_price
    now = midnight + timedelta(seconds=1)
    closed = resumed.process(
        PaperBatch((), snapshot(now, bid=stop - 1, ask=stop, mark=stop), True),
        now,
    )
    assert closed.closed is not None
    assert resumed.daily_risk.day == entered_at.date()
    now += timedelta(minutes=1)
    midnight_bar = minute(3 * 24 * 60)
    resumed.process(PaperBatch((midnight_bar,), snapshot(now), True), now)
    assert resumed.daily_risk.day == midnight.date()
    assert resumed.daily_risk.day_start_equity == prior_balance + prior.unrealized(
        midnight_bar.mark.open
    )
