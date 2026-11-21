"""Deterministic, offline execution against synchronized one-minute candles."""

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from .features import DecisionFeatures
from .market_data import Minute
from .portfolio import ClosedTrade, Portfolio
from .risk import (
    DailyRisk,
    MaintenanceBracket,
    OrderFilters,
    Side,
    liquidation_price,
    size_entry,
)
from .strategies import Baseline

MINUTE = timedelta(minutes=1)
MAX_HOLD = timedelta(hours=4)


class Action(StrEnum):
    WAIT = "WAIT"
    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"
    CLOSE = "CLOSE"


@dataclass(frozen=True)
class SimulationConfig:
    initial_equity: Decimal = Decimal(100)
    fee_rate: Decimal = Decimal("0.0005")
    slippage: Decimal = Decimal("0.0002")
    purge_minutes: int = 240
    funding_reserve_per_settlement: Decimal = Decimal("0.001")
    max_funding_settlements: int = 4

    def __post_init__(self):
        if not self.initial_equity.is_finite() or self.initial_equity <= 0:
            raise ValueError("Modal awal harus positif")
        for value in (
            self.fee_rate,
            self.slippage,
            self.funding_reserve_per_settlement,
        ):
            if not value.is_finite() or not 0 <= value < 1:
                raise ValueError(
                    "Fee, slippage dan cadangan funding harus berada pada [0,1)"
                )
        if self.purge_minutes < 0 or self.max_funding_settlements < 0:
            raise ValueError("Purge dan jumlah settlement cadangan tidak boleh negatif")


@dataclass(frozen=True)
class EquityPoint:
    timestamp: datetime
    equity: Decimal
    exposed: bool


@dataclass(frozen=True)
class BacktestResult:
    starting_equity: Decimal
    ending_equity: Decimal
    equity_curve: tuple[EquityPoint, ...]
    trades: tuple[ClosedTrade, ...]
    rejections: dict[str, int]
    daily_overshoots: int
    liquidations: int
    invalid_intents: int


def _minute_boundary(timestamp: datetime) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise ValueError("Simulasi membutuhkan timestamp UTC")
    if timestamp.second or timestamp.microsecond:
        raise ValueError("Timestamp candle harus sejajar dengan menit")


def _quarter(timestamp: datetime) -> datetime:
    return timestamp.replace(
        minute=(timestamp.minute // 15) * 15, second=0, microsecond=0
    )


class HistoricalSimulator:
    """Advance one causal minute at a time for a policy or a fixed backtest."""

    def __init__(
        self,
        filters: OrderFilters,
        brackets: Sequence[MaintenanceBracket],
        *,
        config: SimulationConfig = SimulationConfig(),
    ):
        self.filters = filters
        self.brackets = tuple(brackets)
        self.config = config
        self.portfolio = Portfolio(config.initial_equity)
        self.daily_risk: DailyRisk | None = None
        self.last_minute: Minute | None = None
        self.last_exit: datetime | None = None
        self.equity_curve: list[EquityPoint] = []
        self.rejections: Counter[str] = Counter()
        self.daily_overshoots = 0
        self.liquidations = 0
        self.invalid_intents = 0
        self.finished = False

    def _close(self, price: Decimal, timestamp: datetime, reason: str) -> None:
        position = self.portfolio.position
        if position is None:
            raise RuntimeError("Tidak ada posisi untuk ditutup")
        execution_price = price * (1 - position.plan.side * self.config.slippage)
        self.portfolio.close(execution_price, timestamp, self.config.fee_rate, reason)
        self.last_exit = timestamp
        if reason == "liquidation":
            self.liquidations += 1

    def _risk_observe(
        self,
        timestamp: datetime,
        mark_price: Decimal,
        exit_price: Decimal,
    ) -> None:
        state = self.daily_risk
        assert state is not None
        position = self.portfolio.position
        equity = self.portfolio.equity(mark_price)
        was_halted = state.day_halted
        state.observe(timestamp, equity, flat=position is None)
        if not state.day_halted:
            return
        if position is not None:
            self._close(exit_price, timestamp, "daily_halt")
            equity = self.portfolio.balance
        if not was_halted and equity < state.day_start_equity * Decimal("0.95"):
            self.daily_overshoots += 1

    def _protect(self, minute: Minute, *, at_open: bool) -> None:
        position = self.portfolio.position
        if position is None:
            return
        plan = position.plan
        timestamp = minute.contract.open_time
        if not at_open:
            timestamp += MINUTE - timedelta(microseconds=1)
        if plan.side == Side.LONG:
            adverse = minute.mark.open if at_open else minute.mark.low
            favorable = minute.mark.open if at_open else minute.mark.high
            worse = min
        else:
            adverse = minute.mark.open if at_open else minute.mark.high
            favorable = minute.mark.open if at_open else minute.mark.low
            worse = max
        # Existing positions get the exact opening boundary first. Within the
        # candle the available OHLC cannot establish the order of touches.
        isolated = (
            plan.initial_margin - position.entry_fee + min(Decimal(0), position.funding)
        )
        liquidation = liquidation_price(
            plan.side, plan.quantity, plan.entry_price, isolated, self.brackets
        )
        if liquidation is None:
            raise ValueError("Bracket tidak mencakup harga likuidasi posisi aktif")
        if plan.side * (adverse - liquidation) <= 0:
            self._close(
                worse(liquidation, minute.contract.open),
                timestamp,
                "liquidation",
            )
            return
        if plan.side * (adverse - plan.stop_price) <= 0:
            self._close(
                worse(plan.stop_price, minute.contract.open), timestamp, "stop_loss"
            )
            return
        exit_price = minute.contract.open
        if not at_open:
            exit_price = (
                minute.contract.low if plan.side == Side.LONG else minute.contract.high
            )
        self._risk_observe(timestamp, adverse, exit_price)
        if self.portfolio.position is None:
            return
        if plan.side * (favorable - plan.take_profit_price) >= 0:
            # Market execution is estimated from the same-minute contract
            # price, conservatively bounded by the trigger for intrabar fills.
            exit_price = (
                minute.contract.open
                if at_open
                else worse(plan.take_profit_price, minute.contract.close)
            )
            self._close(exit_price, timestamp, "take_profit")

    def _decide(
        self,
        minute: Minute,
        decision: DecisionFeatures,
        action: Action,
        allow_entry: bool,
    ) -> None:
        timestamp = minute.contract.open_time
        state = self.daily_risk
        assert state is not None
        if self.portfolio.position is not None:
            if action == Action.CLOSE:
                self._close(minute.contract.open, timestamp, "policy_close")
            return
        if action not in (Action.LONG, Action.SHORT):
            return
        if not allow_entry:
            self.rejections["purge"] += 1
            return
        if state.entry_halted:
            self.rejections["daily_halt"] += 1
            return
        if self.last_exit is not None and _quarter(self.last_exit) == _quarter(
            timestamp
        ):
            self.rejections["same_candle_as_exit"] += 1
            return
        if not decision.volume_ok:
            self.rejections["volume"] += 1
            return
        side = Side.LONG if action == Action.LONG else Side.SHORT
        entry = minute.contract.open * (1 + side * self.config.slippage)
        result = size_entry(
            side=side,
            entry_price=entry,
            atr=decision.atr,
            day_start_equity=state.day_start_equity,
            equity=self.portfolio.equity(minute.mark.open),
            available_balance=self.portfolio.available_balance,
            filters=self.filters,
            brackets=self.brackets,
            fee_rate=self.config.fee_rate,
            exit_slippage=self.config.slippage,
            funding_reserve=(
                self.config.funding_reserve_per_settlement
                * self.config.max_funding_settlements
            ),
        )
        if result.plan is None:
            self.rejections[str(result.reason)] += 1
            return
        self.portfolio.open(result.plan, timestamp, self.config.fee_rate)

    def step(
        self,
        minute: Minute,
        decision: DecisionFeatures | None = None,
        action: Action | str | None = None,
        *,
        allow_entry: bool = True,
    ) -> EquityPoint:
        if self.finished:
            raise RuntimeError("Simulasi sudah ditutup")
        timestamp = minute.contract.open_time
        _minute_boundary(timestamp)
        if minute.mark.open_time != timestamp or (
            self.last_minute is not None
            and timestamp != self.last_minute.contract.open_time + MINUTE
        ):
            raise ValueError(
                f"Gap atau candle 1m tidak sinkron pada {timestamp.isoformat()}"
            )
        if decision is not None and (
            decision.signal_time != timestamp or timestamp.minute % 15
        ):
            raise ValueError(
                "Sinyal harus tersedia tepat pada pembukaan menit keputusan"
            )
        if action is not None and decision is None:
            raise ValueError("Intent membutuhkan candle sinyal yang selesai")
        funding_mark = minute.funding_mark_price
        verified_funding = funding_mark is not None or minute.funding_time_verified
        if verified_funding and (
            minute.funding_rate is None
            or minute.funding_time is None
            or not timestamp <= minute.funding_time < timestamp + MINUTE
        ):
            raise ValueError("Settlement funding REST tidak berada pada menit aktif")
        funding_after_open = verified_funding and minute.funding_time > timestamp
        funding_mark = funding_mark or minute.mark.open
        resolved_action = Action(action) if action is not None else Action.WAIT
        if decision is not None:
            # Policy sees the portfolio at the preceding close. An exit on
            # this minute's open does not retroactively change intent validity.
            if self.portfolio.position is not None:
                if resolved_action not in (Action.HOLD, Action.CLOSE):
                    self.invalid_intents += 1
                    resolved_action = Action.HOLD
            elif resolved_action in (Action.HOLD, Action.CLOSE):
                self.invalid_intents += 1
                resolved_action = Action.WAIT

        if self.daily_risk is None:
            self.daily_risk = DailyRisk(timestamp.date(), self.config.initial_equity)
        elif timestamp.date() != self.daily_risk.day:
            # A carried position contributes its opening mark to the UTC day
            # baseline. Funding at that boundary is applied immediately after.
            self.daily_risk.observe(
                timestamp,
                self.portfolio.equity(minute.mark.open),
                flat=self.portfolio.position is None,
            )
        exposed = self.portfolio.position is not None
        if exposed and minute.funding_rate is not None and not funding_after_open:
            self.portfolio.settle_funding(funding_mark, minute.funding_rate)
        self._protect(minute, at_open=True)
        self._risk_observe(timestamp, minute.mark.open, minute.contract.open)
        position = self.portfolio.position
        if position is not None and timestamp >= position.opened_at + MAX_HOLD:
            self._close(minute.contract.open, timestamp, "timeout")
        if decision is not None:
            self._decide(minute, decision, resolved_action, allow_entry)
        position = self.portfolio.position
        exposed = exposed or position is not None
        if position is not None and position.opened_at == timestamp:
            # Opening mark is known when a new position is created. Resolve
            # already-crossed protection before ambiguous intrabar touches.
            self._protect(minute, at_open=True)
        if funding_after_open and self.portfolio.position is not None:
            self.portfolio.settle_funding(funding_mark, minute.funding_rate)
            self._risk_observe(minute.funding_time, funding_mark, minute.contract.open)
        self._protect(minute, at_open=False)
        close_time = timestamp + MINUTE
        # The preceding candle's close belongs to its old UTC day. A new
        # baseline must use the next opening mark instead.
        self._risk_observe(
            close_time - timedelta(microseconds=1),
            minute.mark.close,
            minute.contract.close,
        )
        self.last_minute = minute
        point = EquityPoint(
            close_time, self.portfolio.equity(minute.mark.close), exposed
        )
        self.equity_curve.append(point)
        return point

    def finish(self) -> BacktestResult:
        if self.last_minute is None:
            raise ValueError("Simulasi memerlukan sedikitnya satu candle")
        if not self.finished and self.portfolio.position is not None:
            point = self.equity_curve[-1]
            self._close(self.last_minute.contract.close, point.timestamp, "end_of_run")
            self._risk_observe(
                point.timestamp - timedelta(microseconds=1),
                self.last_minute.mark.close,
                self.last_minute.contract.close,
            )
            self.equity_curve[-1] = EquityPoint(
                point.timestamp, self.portfolio.balance, True
            )
        self.finished = True
        return BacktestResult(
            self.config.initial_equity,
            self.portfolio.balance,
            tuple(self.equity_curve),
            tuple(self.portfolio.closed_trades),
            dict(self.rejections),
            self.daily_overshoots,
            self.liquidations,
            self.invalid_intents,
        )


def run_backtest(
    minutes: Iterable[Minute],
    decisions: Iterable[DecisionFeatures],
    filters: OrderFilters,
    brackets: Sequence[MaintenanceBracket],
    *,
    end: datetime,
    start: datetime | None = None,
    policy: Callable[[DecisionFeatures], str] | None = None,
    config: SimulationConfig = SimulationConfig(),
) -> BacktestResult:
    """Run one contiguous interval ending at the specified exclusive boundary."""
    _minute_boundary(end)
    if start is not None:
        _minute_boundary(start)
        if start >= end:
            raise ValueError("Awal interval harus mendahului akhir")
    simulator = HistoricalSimulator(filters, brackets, config=config)
    decision_stream = iter(decisions)
    decision = next(decision_stream, None)
    entry_end = end - timedelta(minutes=config.purge_minutes)
    for minute in minutes:
        timestamp = minute.contract.open_time
        if timestamp >= end:
            break
        if start is not None and timestamp < start:
            continue
        if simulator.last_minute is None:
            if start is not None and timestamp != start:
                raise ValueError("Dataset tidak mencakup awal interval")
            while decision is not None and decision.signal_time < timestamp:
                decision = next(decision_stream, None)
        if decision is not None and decision.signal_time < timestamp:
            raise ValueError("Sinyal tidak selaras dengan candle 1m")
        if decision is not None and decision.signal_time == timestamp:
            action = (
                policy(decision) if policy is not None else Baseline.action(decision)
            )
            if policy is None and simulator.portfolio.position is not None:
                action = Action.HOLD
            simulator.step(minute, decision, action, allow_entry=timestamp < entry_end)
            decision = next(decision_stream, None)
        else:
            simulator.step(minute)
    if (
        simulator.last_minute is None
        or simulator.last_minute.contract.open_time + MINUTE != end
    ):
        raise ValueError("Dataset tidak mencakup akhir interval")
    return simulator.finish()
