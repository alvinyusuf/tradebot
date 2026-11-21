"""Local public-feed paper worker with conservative quote-driven execution."""

import sqlite3
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from .execution import ExecutionState
from .features import DecisionFeatures
from .market_data import ONE_MINUTE, DatasetError, Minute
from .paper import (
    MAX_MARKET_AGE,
    BinancePaperFeed,
    MarketSnapshot,
    PaperBatch,
    PaperFeedError,
)
from .paper_state import PaperSnapshot, PaperStateStore
from .paper_strategy import PaperCloseIntent, PaperEntryIntent, PaperEntrySignals
from .portfolio import ClosedTrade, Portfolio, Position
from .risk import (
    DailyRisk,
    MaintenanceBracket,
    OrderFilters,
    OrderPlan,
    Side,
    liquidation_price,
    size_entry,
)
from .runtime_health import RuntimeHealth
from .simulation import MAX_HOLD, SimulationConfig
from .strategies import Baseline

DEFAULT_PAPER_COSTS = SimulationConfig()


class PositionPolicy(Protocol):
    def __call__(
        self,
        decision: DecisionFeatures,
        *,
        portfolio: Portfolio,
        daily_risk: DailyRisk | None,
        mark: Decimal,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class PaperWorkerResult:
    state: ExecutionState
    observed_at: datetime
    equity: Decimal
    opened: OrderPlan | None = None
    closed: ClosedTrade | None = None


class PaperWorker:
    """Process public observations and simulate portfolio changes inside one worker.

    A caller supplies the scheduler, explicit reconciliation, and checkpoint
    publishing. An open position crossing an unverified gap requires review.
    """

    def __init__(
        self,
        filters: OrderFilters,
        brackets: Sequence[MaintenanceBracket],
        *,
        config: SimulationConfig = DEFAULT_PAPER_COSTS,
        policy: Callable[[DecisionFeatures], str] = Baseline.action,
        position_policy: PositionPolicy | None = None,
        portfolio: Portfolio | None = None,
        daily_risk: DailyRisk | None = None,
        last_processed: datetime | None = None,
        next_minute: datetime | None = None,
        expected_funding: datetime | None = None,
        unverified_exposure_intervals: int = 0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.filters = filters
        self.brackets = tuple(brackets)
        self.config = config
        self.portfolio = (
            portfolio if portfolio is not None else Portfolio(config.initial_equity)
        )
        self.daily_risk = daily_risk
        self.last_processed = last_processed
        self.next_minute = next_minute
        self.clock = clock
        self._position_policy = position_policy
        signals = PaperEntrySignals(
            policy,
            position_policy=self._decide if position_policy is not None else None,
        )
        self.health = RuntimeHealth(signals, clock=clock)
        self.rejections: Counter[str] = Counter()
        self._expected_funding = expected_funding
        self.unverified_exposure_intervals = unverified_exposure_intervals
        self._restart_pending = (
            self.portfolio.position is not None and last_processed is not None
        )

    @classmethod
    def restore(
        cls,
        filters: OrderFilters,
        brackets: Sequence[MaintenanceBracket],
        store: PaperStateStore,
        *,
        model_id: str,
        config_id: str,
        **worker_options,
    ) -> "PaperWorker":
        snapshot = store.load(model_id=model_id, config_id=config_id)
        if snapshot is None:
            return cls(filters, brackets, **worker_options)
        return cls(
            filters,
            brackets,
            portfolio=snapshot.portfolio,
            daily_risk=snapshot.daily_risk,
            last_processed=snapshot.last_processed,
            next_minute=snapshot.next_minute,
            expected_funding=snapshot.expected_funding,
            unverified_exposure_intervals=snapshot.unverified_exposure_intervals,
            **worker_options,
        )

    def checkpoint(self, store: PaperStateStore, *, model_id: str, config_id: str):
        if self.daily_risk is None:
            raise RuntimeError(
                "Worker belum memiliki baseline risiko harian untuk checkpoint"
            )
        try:
            store.save(
                PaperSnapshot(
                    self.portfolio,
                    self.daily_risk,
                    self.last_processed,
                    model_id,
                    config_id,
                    self.next_minute,
                    self._expected_funding,
                    self.unverified_exposure_intervals,
                )
            )
        except (OSError, RuntimeError, ValueError, sqlite3.Error):
            self.health.fail("checkpoint_failed")
            raise

    def tick(self, local_now: datetime) -> ExecutionState:
        was_ready = self.health.state == ExecutionState.READY
        state = self.health.tick(local_now)
        if (
            was_ready
            and state != ExecutionState.READY
            and self.portfolio.position is not None
        ):
            self.unverified_exposure_intervals += 1
        return state

    def poll(self, feed: BinancePaperFeed) -> PaperWorkerResult:
        try:
            batch = feed.poll()
        except PaperFeedError:
            if (
                self.health.state == ExecutionState.READY
                and self.portfolio.position is not None
            ):
                self.unverified_exposure_intervals += 1
            self.health.fail("poll_failed")
            raise
        return self.process(batch, self.clock())

    def process(self, batch: PaperBatch, local_now: datetime) -> PaperWorkerResult:
        snapshot = batch.snapshot
        now = local_now + timedelta(milliseconds=snapshot.clock_drift_ms)
        if self.last_processed is not None and now < self.last_processed:
            self.health.fail("clock_changed")
            raise PaperFeedError("Snapshot mendahului perubahan portofolio terakhir")
        was_ready = self.health.state == ExecutionState.READY
        try:
            intent = self.health.observe(batch, local_now)
        finally:
            if (
                was_ready
                and self.health.state != ExecutionState.READY
                and self.portfolio.position is not None
            ):
                self.unverified_exposure_intervals += 1
        if self._restart_pending:
            assert self.last_processed is not None
            if now - self.last_processed > MAX_MARKET_AGE:
                self.unverified_exposure_intervals += 1
            self._restart_pending = False
        try:
            self._record_closed_minutes(batch.minutes)
            self._prepare_day(now, snapshot.mark_price)
            closed = self._watch_position(
                snapshot,
                now,
                policy_close=isinstance(intent, PaperCloseIntent),
            )
            opened = None
            if isinstance(intent, PaperEntryIntent) and closed is None:
                opened = self._enter(intent)
            self._observe_funding_schedule(snapshot)
        except (ArithmeticError, ValueError):
            self.health.fail("ledger_update_failed")
            raise
        self.last_processed = now
        return PaperWorkerResult(
            self.health.state,
            now,
            self.portfolio.equity(snapshot.mark_price),
            opened,
            closed,
        )

    def _observe_funding_schedule(self, snapshot: MarketSnapshot):
        next_funding = snapshot.next_funding_time
        previous = self._expected_funding
        if next_funding is None:
            return
        if (
            previous is None
            or snapshot.mark_time < previous
            or (self.next_minute is not None and self.next_minute > previous)
        ):
            self._expected_funding = next_funding

    def _decide(self, decision: DecisionFeatures, minute: Minute) -> str:
        assert self._position_policy is not None
        self._record_closed_minutes((minute,))
        try:
            return self._position_policy(
                decision,
                portfolio=self.portfolio,
                daily_risk=self.daily_risk,
                mark=minute.mark.close,
            )
        except (ArithmeticError, RuntimeError, ValueError) as exc:
            raise DatasetError("Inferensi policy paper gagal") from exc

    def _record_closed_minutes(self, minutes: tuple[Minute, ...]):
        for minute in minutes:
            stamp = minute.contract.open_time
            if self.next_minute is not None and stamp < self.next_minute:
                continue
            if self.next_minute is not None and stamp != self.next_minute:
                raise DatasetError("Gap pada cursor ledger paper")
            expected = self._expected_funding
            if (
                expected is not None
                and stamp <= expected < stamp + ONE_MINUTE
                and minute.funding_rate is None
            ):
                raise DatasetError("Settlement funding yang tercatat belum tersedia")
            if self.daily_risk is not None and stamp.date() > self.daily_risk.day:
                self._record_midnight(stamp, minute.mark.open)
            if minute.funding_rate is not None:
                if (
                    minute.funding_time is None
                    or minute.funding_mark_price is None
                    or not stamp <= minute.funding_time < stamp + ONE_MINUTE
                ):
                    raise DatasetError(
                        "Ledger paper membutuhkan settlement funding REST dan mark terkait"
                    )
                self.portfolio.book_funding_at(
                    minute.funding_mark_price, minute.funding_rate, minute.funding_time
                )
            self.next_minute = stamp + ONE_MINUTE

    def _prepare_day(self, now: datetime, mark: Decimal):
        if self.daily_risk is None:
            self.daily_risk = DailyRisk(now.date(), self.portfolio.equity(mark))

    def _record_midnight(self, stamp: datetime, mark: Decimal):
        day = self.daily_risk
        if day is None:
            return
        if stamp.hour or stamp.minute or stamp.date() != day.day + timedelta(days=1):
            raise DatasetError(
                "Batas pergantian hari UTC pada ledger paper belum diverifikasi"
            )
        balance = self.portfolio.balance
        position = self.portfolio.position
        if position is None and self.portfolio.closed_trades:
            previous = self.portfolio.closed_trades[-1]
            if previous.closed_at >= stamp:
                # A stop could already close the position between the UTC
                # boundary and the delayed, complete midnight candle.
                balance -= previous.gross_pnl - previous.exit_fee
                position = Position(
                    previous.plan,
                    previous.opened_at,
                    previous.entry_fee,
                    previous.funding,
                )
        if position is not None and position.opened_at >= stamp:
            raise DatasetError("Posisi dibuka sebelum baseline UTC dapat diverifikasi")
        boundary_equity = balance + (
            position.unrealized(mark) if position is not None else Decimal(0)
        )
        day.observe(
            stamp,
            boundary_equity,
            flat=position is None,
            reconciled=self.health.state == ExecutionState.READY,
        )

    def _watch_position(
        self, snapshot: MarketSnapshot, now: datetime, *, policy_close: bool = False
    ) -> ClosedTrade | None:
        if not snapshot.fresh_at(now):
            raise DatasetError(
                "Posisi paper membutuhkan quote dan mark price yang segar"
            )
        mark = snapshot.mark_price
        day = self.daily_risk
        assert day is not None
        position = self.portfolio.position
        if day.day == now.date():
            day.observe(
                now,
                self.portfolio.equity(mark),
                flat=position is None,
                reconciled=self.health.state == ExecutionState.READY,
            )
        if position is None:
            return None
        plan = position.plan
        liquidation = liquidation_price(
            plan.side,
            plan.quantity,
            plan.entry_price,
            plan.initial_margin
            - position.entry_fee
            + min(Decimal(0), position.funding),
            self.brackets,
        )
        if liquidation is None:
            self.health.fail("missing_maintenance_bracket")
            raise DatasetError("Bracket tidak mencakup posisi paper")
        reason = None
        if plan.side * (mark - liquidation) <= 0:
            reason = "liquidation"
        elif plan.side * (mark - plan.stop_price) <= 0:
            reason = "stop_loss"
        elif day.day_halted:
            reason = "daily_halt"
        elif now >= position.opened_at + MAX_HOLD:
            reason = "timeout"
        elif plan.side * (mark - plan.take_profit_price) >= 0:
            reason = "take_profit"
        elif policy_close:
            reason = "policy_close"
        if reason is None:
            return None
        if reason != "policy_close" and snapshot.quote_time < snapshot.mark_time:
            self.rejections["post_trigger_quote_unavailable"] += 1
            return None
        price, quantity = (
            (snapshot.bid_price, snapshot.bid_quantity)
            if plan.side == Side.LONG
            else (snapshot.ask_price, snapshot.ask_quantity)
        )
        if plan.quantity > quantity:
            self.rejections["exit_depth_unavailable"] += 1
            self.health.fail("exit_depth_unavailable")
            return None
        trade = self.portfolio.close(price, now, self.config.fee_rate, reason)
        if day.day == now.date():
            day.observe(
                now,
                self.portfolio.equity(mark),
                flat=True,
                reconciled=self.health.state == ExecutionState.READY,
            )
        return trade

    def _enter(self, intent: PaperEntryIntent) -> OrderPlan | None:
        day = self.daily_risk
        assert day is not None
        if (
            self.health.state != ExecutionState.READY
            or self.portfolio.position is not None
            or day.entry_halted
        ):
            self.rejections["state_or_risk_halted"] += 1
            return None
        now = intent.observed_at
        if day.day != now.date():
            self.rejections["utc_boundary_pending"] += 1
            return None
        if (
            self._expected_funding is not None
            and self._expected_funding <= now
            and (self.next_minute is None or self.next_minute <= self._expected_funding)
        ):
            self.rejections["funding_pending"] += 1
            return None
        if self.portfolio.closed_trades:
            last_close = self.portfolio.closed_trades[-1].closed_at
            if now < last_close.replace(
                minute=last_close.minute // 15 * 15, second=0, microsecond=0
            ) + timedelta(minutes=15):
                self.rejections["same_decision_bucket_as_exit"] += 1
                return None
        sizing = size_entry(
            side=intent.side,
            entry_price=intent.quote_price,
            atr=intent.atr,
            day_start_equity=day.day_start_equity,
            equity=self.portfolio.equity(intent.mark_price),
            available_balance=self.portfolio.available_balance,
            filters=self.filters,
            brackets=self.brackets,
            fee_rate=self.config.fee_rate,
            exit_slippage=self.config.slippage,
            funding_reserve=self.config.funding_reserve_per_settlement
            * self.config.max_funding_settlements,
        )
        if sizing.plan is None:
            self.rejections[str(sizing.reason)] += 1
            return None
        if sizing.plan.quantity > intent.displayed_quantity:
            self.rejections["entry_depth_unavailable"] += 1
            return None
        self.portfolio.open(sizing.plan, now, self.config.fee_rate)
        return sizing.plan
