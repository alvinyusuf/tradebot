"""Isolated-margin order sizing and daily risk controls for v0.1."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import IntEnum

D = Decimal
ZERO = D(0)
ENTRY_RISK = D("0.005")
DAY_LIMIT = D("0.05")
MARGIN_LIMIT = D("0.25")
DEFAULT_FEE = D("0.0005")
DEFAULT_SLIPPAGE = D("0.0002")


class Side(IntEnum):
    LONG = 1
    SHORT = -1


@dataclass(frozen=True, slots=True)
class OrderFilters:
    price_tick: Decimal
    quantity_step: Decimal
    min_quantity: Decimal
    max_quantity: Decimal
    min_notional: Decimal

    def __post_init__(self):
        values = (
            self.price_tick,
            self.quantity_step,
            self.min_quantity,
            self.max_quantity,
            self.min_notional,
        )
        if not all(value.is_finite() and value > 0 for value in values):
            raise ValueError("Order filters must be finite and positive")
        if self.min_quantity > self.max_quantity:
            raise ValueError("Minimum quantity exceeds maximum")


@dataclass(frozen=True, slots=True)
class MaintenanceBracket:
    notional_floor: Decimal
    notional_cap: Decimal
    maintenance_rate: Decimal
    cumulative_deduction: Decimal
    max_leverage: int

    def __post_init__(self):
        values = (
            self.notional_floor,
            self.notional_cap,
            self.maintenance_rate,
            self.cumulative_deduction,
        )
        if not all(value.is_finite() and value >= 0 for value in values):
            raise ValueError("Bracket inputs must be finite and nonnegative")
        if not (
            self.notional_floor < self.notional_cap
            and self.maintenance_rate < 1
            and type(self.max_leverage) is int
            and self.max_leverage > 0
        ):
            raise ValueError("Invalid maintenance bracket")


@dataclass(frozen=True, slots=True)
class OrderPlan:
    side: Side
    quantity: Decimal
    entry_price: Decimal
    stop_price: Decimal
    take_profit_price: Decimal
    leverage: int
    initial_margin: Decimal
    loss_at_stop: Decimal
    liquidation_price: Decimal


@dataclass(frozen=True, slots=True)
class SizingResult:
    plan: OrderPlan | None
    reason: str | None


def remaining_daily_budget(day_start_equity, equity, allocated_risk=ZERO):
    budget = min(
        DAY_LIMIT * day_start_equity, equity - (1 - DAY_LIMIT) * day_start_equity
    )
    return max(ZERO, budget - allocated_risk)


@dataclass(slots=True)
class DailyRisk:
    day: date
    day_start_equity: Decimal
    day_halted: bool = False
    system_halted: bool = False
    halted_on: date | None = None

    def __post_init__(self):
        if not self.day_start_equity.is_finite():
            raise ValueError("Invalid day start equity")
        if self.day_halted and self.halted_on is None:
            self.halted_on = self.day

    @property
    def entry_halted(self):
        return self.day_halted or self.system_halted

    def remaining_budget(self, equity, allocated_risk=ZERO):
        if self.entry_halted:
            return ZERO
        return remaining_daily_budget(self.day_start_equity, equity, allocated_risk)

    def observe(
        self, timestamp: datetime, equity: Decimal, *, flat: bool, reconciled=True
    ):
        if timestamp.utcoffset() != timedelta(0) or timestamp.date() < self.day:
            raise ValueError("Daily risk requires a nondecreasing UTC day")
        if not equity.is_finite():
            raise ValueError("Invalid marked equity")
        if timestamp.date() > self.day:
            self.day = timestamp.date()
            self.day_start_equity = equity
        if (
            self.halted_on is not None
            and self.day > self.halted_on
            and flat
            and reconciled
        ):
            self.day_halted = False
            self.halted_on = None
        if remaining_daily_budget(self.day_start_equity, equity) == 0:
            self.day_halted = True
            self.halted_on = self.day
        return self.entry_halted

    def halt_system(self):
        self.system_halted = True

    def recover_system(self, *, flat, reconciled):
        if not (flat and reconciled):
            raise ValueError("System recovery requires flat and reconciled state")
        self.system_halted = False


def _round_to_step(value, step, rounding):
    return (value / step).to_integral_value(rounding=rounding) * step


def _valid_brackets(brackets):
    floor = rate = deduction = ZERO
    for bracket in brackets:
        if (
            bracket.notional_floor != floor
            or bracket.maintenance_rate < rate
            or bracket.cumulative_deduction
            != deduction + floor * (bracket.maintenance_rate - rate)
        ):
            return False
        floor = bracket.notional_cap
        rate = bracket.maintenance_rate
        deduction = bracket.cumulative_deduction
    return bool(brackets)


def liquidation_price(side, quantity, entry_price, isolated_margin, brackets):
    """Solve the linear isolated-equity/maintenance boundary in its mark tier."""
    for bracket in brackets:
        numerator = (
            side * quantity * entry_price
            - isolated_margin
            - bracket.cumulative_deduction
        )
        denominator = quantity * (side - bracket.maintenance_rate)
        price = numerator / denominator
        if side == Side.LONG and price <= 0 and bracket.notional_floor == 0:
            return ZERO
        notional = price * quantity
        if bracket.notional_floor <= notional < bracket.notional_cap:
            return price
    return None


def size_entry(
    *,
    side: Side,
    entry_price: Decimal,
    atr: Decimal,
    day_start_equity: Decimal,
    equity: Decimal,
    available_balance: Decimal,
    filters: OrderFilters,
    brackets: tuple[MaintenanceBracket, ...],
    fee_rate=DEFAULT_FEE,
    exit_slippage=DEFAULT_SLIPPAGE,
    funding_reserve=ZERO,
    allocated_risk=ZERO,
):
    """Find the largest compliant step quantity and its smallest valid leverage.

    Funding reserve is the sum of conservative debit rates for all potential
    settlements during the candidate holding period.
    """
    if side not in (Side.LONG, Side.SHORT):
        raise ValueError("Invalid side")
    inputs = (
        entry_price,
        atr,
        day_start_equity,
        equity,
        available_balance,
        fee_rate,
        exit_slippage,
        funding_reserve,
        allocated_risk,
    )
    if not all(value.is_finite() for value in inputs):
        raise ValueError("Sizing inputs must be finite")
    if not (
        entry_price > 0
        and atr > 0
        and 0 <= fee_rate < 1
        and 0 <= exit_slippage < 1
        and funding_reserve >= 0
        and allocated_risk >= 0
    ):
        raise ValueError("Invalid sizing inputs")
    if not _valid_brackets(brackets):
        return SizingResult(None, "maintenance_brackets_unavailable")

    basis = min(day_start_equity, equity)
    budget = min(
        ENTRY_RISK * basis,
        remaining_daily_budget(day_start_equity, equity, allocated_risk),
    )
    if budget <= 0 or available_balance <= 0:
        return SizingResult(None, "no_risk_budget")
    stop_round = ROUND_FLOOR if side == Side.LONG else ROUND_CEILING
    take_round = ROUND_CEILING if side == Side.LONG else ROUND_FLOOR
    stop = _round_to_step(
        entry_price - side * D("1.5") * atr, filters.price_tick, stop_round
    )
    take = _round_to_step(entry_price + side * 3 * atr, filters.price_tick, take_round)
    if stop <= 0 or take <= 0:
        return SizingResult(None, "invalid_protection_price")
    stop_fill = stop * (1 - side * exit_slippage)
    stop_distance = abs(entry_price - stop)
    stop_loss = (
        abs(entry_price - stop_fill)
        + fee_rate * (entry_price + stop_fill)
        + funding_reserve * max(entry_price, stop, take)
    )
    step = filters.quantity_step
    entry_notional_per_step = entry_price * step
    min_units = int(
        max(
            D(1),
            filters.min_quantity / step,
            filters.min_notional / entry_notional_per_step,
        ).to_integral_value(rounding=ROUND_CEILING)
    )
    max_units = int(min(filters.max_quantity, budget / stop_loss) // step)
    if max_units < min_units:
        return SizingResult(None, "minimum_order")

    best = None
    for leverage in range(1, 6):
        margin_per_unit = entry_notional_per_step / leverage
        fee_per_unit = entry_notional_per_step * fee_rate
        total_reserve_per_unit = (
            entry_notional_per_step
            * (fee_rate + funding_reserve * max(entry_price, stop, take) / entry_price)
            + stop_fill * step * fee_rate
        )
        capacity = int(
            min(
                D(max_units),
                MARGIN_LIMIT * basis / margin_per_unit,
                available_balance / (margin_per_unit + total_reserve_per_unit),
            )
        )
        for bracket in brackets:
            if leverage > bracket.max_leverage:
                continue
            bracket_low = int(
                (bracket.notional_floor / entry_notional_per_step).to_integral_value(
                    rounding=ROUND_CEILING
                )
            )
            bracket_high = (
                int(
                    (bracket.notional_cap / entry_notional_per_step).to_integral_value(
                        rounding=ROUND_CEILING
                    )
                )
                - 1
            )
            low = max(min_units, bracket_low)
            high = min(capacity, bracket_high)
            while low <= high:
                units = (low + high) // 2
                quantity = units * step
                margin = quantity * entry_price / leverage
                isolated = (
                    margin
                    - fee_per_unit * units
                    - funding_reserve * max(entry_price, stop, take) * quantity
                )
                liquidation = liquidation_price(
                    side, quantity, entry_price, isolated, brackets
                )
                if (
                    liquidation is None
                    or side * (entry_price - liquidation) < 2 * stop_distance
                ):
                    high = units - 1
                    continue
                loss = quantity * stop_loss
                if (
                    loss > budget
                    or margin > MARGIN_LIMIT * basis
                    or margin + units * total_reserve_per_unit > available_balance
                ):
                    high = units - 1
                    continue
                if best is None or quantity > best.quantity:
                    best = OrderPlan(
                        side,
                        quantity,
                        entry_price,
                        stop,
                        take,
                        leverage,
                        margin,
                        loss,
                        liquidation,
                    )
                low = units + 1
    return SizingResult(
        best, None if best is not None else "margin_or_liquidation_buffer"
    )
