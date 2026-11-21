"""Causal entry intent generation using closed bars and fresh public quotes."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .features import DecisionFeatures, DecisionStream
from .market_data import ONE_MINUTE, DatasetError, Minute
from .paper import MarketSnapshot, PaperBatch
from .risk import Side
from .strategies import Baseline

ACTION_WINDOW = timedelta(seconds=5)


@dataclass(frozen=True, slots=True)
class PaperEntryIntent:
    side: Side
    atr: Decimal
    signal_time: datetime
    quote_time: datetime
    observed_at: datetime
    quote_price: Decimal
    displayed_quantity: Decimal
    mark_price: Decimal


@dataclass(frozen=True, slots=True)
class PaperCloseIntent:
    signal_time: datetime


class PaperEntrySignals:
    """Return at most one unsized intent per on-time decision."""

    def __init__(
        self,
        policy: Callable[[DecisionFeatures], str] = Baseline.action,
        *,
        position_policy: Callable[[DecisionFeatures, Minute], str] | None = None,
    ):
        self._policy = policy
        self._position_policy = position_policy
        self._features = DecisionStream()
        self._armed = False
        self._pending: tuple[DecisionFeatures, str] | None = None
        self._last_observed: datetime | None = None

    def mark_unready(self) -> None:
        """Disarm on disconnect or stale data before handling catch-up batches."""
        self._armed = False
        self._pending = None

    def _validate(self, batch: PaperBatch) -> datetime | None:
        snapshot = batch.snapshot
        observed = snapshot.server_time
        if self._last_observed is not None and observed < self._last_observed:
            raise DatasetError("Snapshot paper bergerak ke belakang")
        if not snapshot.fresh_at(observed):
            raise DatasetError(
                "Snapshot paper kedaluwarsa atau bertimestamp masa depan"
            )
        expected = self._features.cursor
        for minute in batch.minutes:
            stamp = minute.contract.open_time
            if (
                stamp.utcoffset() != timedelta(0)
                or stamp.second
                or stamp.microsecond
                or minute.mark.open_time != stamp
                or (expected is not None and stamp != expected)
            ):
                raise DatasetError("Candle paper tidak sinkron atau tidak berurutan")
            expected = stamp + ONE_MINUTE
        boundary = observed.replace(second=0, microsecond=0)
        if expected is not None and (
            expected > boundary or (batch.caught_up and expected != boundary)
        ):
            raise DatasetError("Cursor candle paper tidak sesuai waktu snapshot")
        return expected

    def observe(self, batch: PaperBatch) -> PaperEntryIntent | PaperCloseIntent | None:
        try:
            cursor = self._validate(batch)
        except DatasetError:
            self.mark_unready()
            raise
        first_live_minute = self._armed and batch.caught_up and len(batch.minutes) == 1
        if not batch.caught_up or len(batch.minutes) > 1:
            self.mark_unready()
        for minute in batch.minutes:
            decision = self._features.update(minute)
            if decision is None or not first_live_minute:
                continue
            if self._position_policy is None and not decision.volume_ok:
                continue
            action = (
                self._policy(decision)
                if self._position_policy is None
                else self._position_policy(decision, minute)
            )
            if action not in {"WAIT", "LONG", "SHORT", "HOLD", "CLOSE"}:
                raise DatasetError("Tindakan policy paper tidak dikenal")
            if action == "CLOSE" or (
                decision.volume_ok and action in {"LONG", "SHORT"}
            ):
                self._pending = decision, action
        self._armed = batch.caught_up and cursor is not None
        self._last_observed = batch.snapshot.server_time
        return self._intent(batch.snapshot)

    def _intent(
        self, snapshot: MarketSnapshot
    ) -> PaperEntryIntent | PaperCloseIntent | None:
        if self._pending is None:
            return None
        decision, action = self._pending
        if snapshot.server_time > decision.signal_time + ACTION_WINDOW:
            self._pending = None
            return None
        if min(snapshot.quote_time, snapshot.mark_time) < decision.signal_time:
            return None
        self._pending = None
        if action == "CLOSE":
            return PaperCloseIntent(decision.signal_time)
        side = Side.LONG if action == "LONG" else Side.SHORT
        price, quantity = (
            (snapshot.ask_price, snapshot.ask_quantity)
            if side == Side.LONG
            else (snapshot.bid_price, snapshot.bid_quantity)
        )
        return PaperEntryIntent(
            side,
            decision.atr,
            decision.signal_time,
            snapshot.quote_time,
            snapshot.server_time,
            price,
            quantity,
            snapshot.mark_price,
        )
