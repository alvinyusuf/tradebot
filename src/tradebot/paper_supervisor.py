"""Local paper scheduling with one in-flight market request."""

import math
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from time import monotonic, sleep
from urllib.error import HTTPError

from .execution import ExecutionState
from .paper import PaperBatch, PaperFeedError
from .paper_state import PaperStateStore
from .paper_worker import PaperWorker, PaperWorkerResult


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PaperSupervisor:
    """Keep worker and checkpoint mutations on the supervisor thread.

    Only polling runs in the executor. An injected poll must have a finite
    timeout. Shutdown discards any in-flight batch without processing it.
    """

    def __init__(
        self,
        worker: PaperWorker,
        poll: Callable[[], PaperBatch],
        store: PaperStateStore,
        *,
        model_id: str,
        config_id: str,
        reconcile: Callable[[PaperWorker, PaperBatch], bool],
        on_result: Callable[[PaperWorkerResult], None] | None = None,
        on_event: Callable[[str], None] | None = None,
        clock: Callable[[], datetime] = _utc_now,
        monotonic_clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
        poll_interval: float = 1.0,
        watchdog_interval: float = 1.0,
        retry_interval: float = 5.0,
        heartbeat_interval: float = 30.0,
        submit: Callable[[Callable[[], PaperBatch]], Future[PaperBatch]] | None = None,
    ):
        for interval in (
            poll_interval,
            watchdog_interval,
            retry_interval,
            heartbeat_interval,
        ):
            if not math.isfinite(interval) or interval <= 0:
                raise ValueError("Interval supervisor harus positif dan terbatas")
        if not model_id or not config_id:
            raise ValueError("Supervisor membutuhkan identitas model dan konfigurasi")
        self.worker = worker
        self._poll = poll
        self._store = store
        self._model_id = model_id
        self._config_id = config_id
        self._reconcile = reconcile
        self._on_result = on_result
        self._on_event = on_event
        self._clock = clock
        self._monotonic = monotonic_clock
        self._sleep = sleeper
        self._poll_interval = poll_interval
        self._watchdog_interval = watchdog_interval
        self._retry_interval = retry_interval
        self._heartbeat_interval = heartbeat_interval
        self._executor = ThreadPoolExecutor(max_workers=1) if submit is None else None
        self._submit = self._executor.submit if self._executor is not None else submit
        self._future: Future[PaperBatch] | None = None
        self._next_poll = self._next_watchdog = self._monotonic()
        self._next_heartbeat = self._next_poll + heartbeat_interval
        self._closed = False

    def _checkpoint(self) -> None:
        if self.worker.daily_risk is not None:
            self.worker.checkpoint(
                self._store, model_id=self._model_id, config_id=self._config_id
            )

    def _emit(self, event: str) -> None:
        if self._on_event is not None:
            self._on_event(event)

    def _accept(self, batch: PaperBatch) -> PaperWorkerResult:
        result = self.worker.process(batch, self._clock())
        self._checkpoint()
        if self._on_result is not None:
            self._on_result(result)

        event = None
        if batch.caught_up and self.worker.health.state != ExecutionState.READY:
            if self._reconcile(self.worker, batch) is True:
                try:
                    self.worker.health.confirm_reconciled(
                        self._clock(), ledger_matches=True
                    )
                except RuntimeError:
                    event = "reconcile_waiting"
                else:
                    event = "reconciled"
            else:
                self.worker.health.fail("ledger_mismatch")
                event = "ledger_mismatch"

        # A result describes the state when its batch was processed. A later
        # reconciliation changes readiness only for subsequent observations.
        if event is not None:
            self._emit(event)
        return result

    def _finish_poll(self, now: float) -> PaperWorkerResult | None:
        future, self._future = self._future, None
        assert future is not None
        try:
            batch = future.result()
        except PaperFeedError as exc:
            if (
                self.worker.health.state == ExecutionState.READY
                and self.worker.portfolio.position is not None
            ):
                self.worker.unverified_exposure_intervals += 1
            self.worker.health.fail("poll_failed")
            self._checkpoint()
            self._emit("poll_failed")
            # A rate limit or access denial requires the caller to inspect the
            # response and its retry policy before issuing another request.
            cause = exc.__cause__
            if isinstance(cause, HTTPError) and 400 <= cause.code < 500:
                raise
            self._next_poll = now + self._retry_interval
            return None
        return self._accept(batch)

    def step(self) -> PaperWorkerResult | None:
        """Run due work without waiting for a network poll."""
        if self._closed:
            raise RuntimeError("Supervisor paper sudah ditutup")
        try:
            now = self._monotonic()
            if now >= self._next_watchdog:
                previous = self.worker.health.state
                current = self.worker.tick(self._clock())
                self._next_watchdog = now + self._watchdog_interval
                if current == ExecutionState.HALTED and previous != current:
                    self._checkpoint()
                    self._emit(self.worker.health.reason)
            if now >= self._next_heartbeat:
                self._emit("heartbeat")
                self._next_heartbeat = now + self._heartbeat_interval

            result = None
            if self._future is not None and self._future.done():
                result = self._finish_poll(now)
            if self._future is None and now >= self._next_poll:
                assert self._submit is not None
                self._future = self._submit(self._poll)
                self._next_poll = now + self._poll_interval
            return result
        except Exception:
            self.worker.health.fail("supervisor_failed")
            self.close()
            raise

    def run(self, should_stop: Callable[[], bool]) -> None:
        """Run until the caller requests shutdown or a fatal error occurs."""
        try:
            while not should_stop():
                self.step()
                wake = min(self._next_watchdog, self._next_heartbeat)
                if self._future is None:
                    wake = min(wake, self._next_poll)
                self._sleep(max(0.0, wake - self._monotonic()))
        finally:
            self.close()

    def close(self) -> None:
        """Discard pending work. Every accepted batch was already checkpointed."""
        if self._closed:
            return
        self._closed = True
        if self._future is not None:
            self._future.cancel()
            self._future = None
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
