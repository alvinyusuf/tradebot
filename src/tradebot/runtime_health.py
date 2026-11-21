"""Readiness and freshness watchdog for the public paper components."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from .execution import ExecutionState
from .paper import BinancePaperFeed, MarketSnapshot, PaperBatch, PaperFeedError
from .paper_strategy import PaperCloseIntent, PaperEntryIntent, PaperEntrySignals


class RuntimeHealth:
    """Gate paper intent processing until feed catch-up and ledger reconciliation."""

    def __init__(
        self,
        signals: PaperEntrySignals,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._signals = signals
        self._clock = clock
        self._snapshot: MarketSnapshot | None = None
        self._caught_up = False
        self.state = ExecutionState.RECONCILING
        self.reason = "startup"

    def _set_state(self, state: ExecutionState, reason: str):
        self.state = state
        self.reason = reason
        if state != ExecutionState.READY:
            self._signals.mark_unready()

    def fail(self, reason: str):
        self._snapshot = None
        self._caught_up = False
        self._set_state(ExecutionState.HALTED, reason)

    @staticmethod
    def _fresh(snapshot: MarketSnapshot, local_now: datetime) -> bool:
        if local_now.utcoffset() != timedelta(0):
            return False
        server_now = local_now + timedelta(milliseconds=snapshot.clock_drift_ms)
        return snapshot.fresh_at(server_now)

    def tick(self, local_now: datetime) -> ExecutionState:
        """Run on the scheduler's one-second cadence even between candles."""
        if self._snapshot is not None and not self._fresh(self._snapshot, local_now):
            self.fail("market_stale")
        return self.state

    def confirm_reconciled(self, local_now: datetime, *, ledger_matches: bool):
        """Accept an explicit reconciliation result from the caller's ledger."""
        self.tick(local_now)
        if not ledger_matches:
            self.fail("ledger_mismatch")
            raise RuntimeError("Ledger paper belum cocok")
        if self._snapshot is None or not self._caught_up:
            raise RuntimeError(
                "Rekonsiliasi membutuhkan data segar yang telah menyusul pasar"
            )
        self._set_state(ExecutionState.READY, "reconciled")

    def observe(
        self, batch: PaperBatch, local_now: datetime
    ) -> PaperEntryIntent | PaperCloseIntent | None:
        self.tick(local_now)
        if not self._fresh(batch.snapshot, local_now):
            self.fail("market_stale")
            raise PaperFeedError("Batch paper kedaluwarsa saat diterima")
        received_at = local_now + timedelta(milliseconds=batch.snapshot.clock_drift_ms)
        observed = batch.snapshot.server_time
        if received_at < observed:
            self.fail("clock_changed")
            raise PaperFeedError("Clock bergerak ke belakang setelah poll")
        if received_at > observed:
            same_minute = received_at.replace(
                second=0, microsecond=0
            ) == observed.replace(second=0, microsecond=0)
            batch = PaperBatch(
                batch.minutes,
                replace(batch.snapshot, server_time=received_at),
                batch.caught_up and same_minute,
            )
        catch_up = not batch.caught_up or len(batch.minutes) > 1
        if self.state == ExecutionState.READY and catch_up:
            self._set_state(ExecutionState.RECONCILING, "catch_up")
        if self.state != ExecutionState.READY:
            self._signals.mark_unready()
        try:
            intent = self._signals.observe(batch)
        except (ArithmeticError, ValueError, RuntimeError):
            self.fail("invalid_batch")
            raise
        self._snapshot = batch.snapshot
        self._caught_up = batch.caught_up
        return intent if self.state == ExecutionState.READY else None

    def poll(
        self, feed: BinancePaperFeed
    ) -> PaperEntryIntent | PaperCloseIntent | None:
        try:
            batch = feed.poll()
        except PaperFeedError:
            self.fail("poll_failed")
            raise
        return self.observe(batch, self._clock())
