"""Single-position ledger for simulated USDⓈ-M fills and funding."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

from .risk import ZERO, OrderPlan, Side


@dataclass(frozen=True, slots=True)
class Position:
    plan: OrderPlan
    opened_at: datetime
    entry_fee: Decimal
    funding: Decimal = ZERO

    def unrealized(self, mark_price):
        return (
            self.plan.side * self.plan.quantity * (mark_price - self.plan.entry_price)
        )


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    plan: OrderPlan
    opened_at: datetime
    closed_at: datetime
    exit_price: Decimal
    reason: str
    gross_pnl: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    funding: Decimal

    @property
    def net_pnl(self):
        return self.gross_pnl - self.entry_fee - self.exit_fee + self.funding


class Portfolio:
    def __init__(self, initial_balance: Decimal):
        if not initial_balance.is_finite() or initial_balance <= 0:
            raise ValueError("Initial balance must be finite and positive")
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.position: Position | None = None
        self.closed_trades: list[ClosedTrade] = []
        self.total_fees = ZERO
        self.total_funding = ZERO
        self.realized_pnl = ZERO
        self._last_fill_at: datetime | None = None

    @property
    def available_balance(self):
        if self.position is None:
            return self.balance
        return self.balance - self.position.plan.initial_margin

    def equity(self, mark_price: Decimal):
        self._validate_price(mark_price)
        if self.position is None:
            return self.balance
        return self.balance + self.position.unrealized(mark_price)

    @staticmethod
    def _validate_price(price):
        if not price.is_finite() or price <= 0:
            raise ValueError("Prices must be finite and positive")

    def _validate_fill(self, price, timestamp, fee_rate):
        self._validate_price(price)
        if timestamp.utcoffset() != timedelta(0):
            raise ValueError("Fills require UTC timestamps")
        if self._last_fill_at is not None and timestamp < self._last_fill_at:
            raise ValueError("Fills must be chronological")
        if not fee_rate.is_finite() or not 0 <= fee_rate < 1:
            raise ValueError("Invalid fill fee rate")

    def open(self, plan: OrderPlan, time: datetime, fee_rate: Decimal):
        self._validate_fill(plan.entry_price, time, fee_rate)
        if self.position is not None:
            raise ValueError("Portfolio already has a position")
        if not (
            plan.side in (Side.LONG, Side.SHORT)
            and type(plan.leverage) is int
            and 1 <= plan.leverage <= 5
            and plan.quantity.is_finite()
            and plan.quantity > 0
            and plan.initial_margin == plan.quantity * plan.entry_price / plan.leverage
        ):
            raise ValueError("Invalid plan")
        entry_fee = plan.quantity * plan.entry_price * fee_rate
        if plan.initial_margin + entry_fee > self.available_balance:
            raise ValueError("Insufficient available balance")
        self.position = Position(plan, time, entry_fee)
        self.balance -= entry_fee
        self.total_fees += entry_fee
        self._last_fill_at = time
        return self.position

    def settle_funding(self, mark_price: Decimal, rate: Decimal):
        self._validate_price(mark_price)
        if not rate.is_finite():
            raise ValueError("Invalid funding rate")
        if self.position is None:
            return ZERO
        plan = self.position.plan
        cash = -plan.side * plan.quantity * mark_price * rate
        self.balance += cash
        self.total_funding += cash
        self.position = replace(self.position, funding=self.position.funding + cash)
        return cash

    def book_funding_at(self, mark_price: Decimal, rate: Decimal, timestamp: datetime):
        """Book a settlement exactly once per coordinator cursor.

        Settlement precedes fills at the same timestamp, including closing fills.
        """
        self._validate_price(mark_price)
        if timestamp.utcoffset() != timedelta(0) or not rate.is_finite():
            raise ValueError("Funding requires a UTC timestamp and a finite rate")
        if self.position is not None and self.position.opened_at < timestamp:
            return self.settle_funding(mark_price, rate)
        for index in range(len(self.closed_trades) - 1, -1, -1):
            trade = self.closed_trades[index]
            if trade.closed_at < timestamp:
                break
            if trade.opened_at < timestamp:
                cash = -trade.plan.side * trade.plan.quantity * mark_price * rate
                self.closed_trades[index] = replace(trade, funding=trade.funding + cash)
                self.balance += cash
                self.total_funding += cash
                return cash
        return ZERO

    def close(self, price: Decimal, time: datetime, fee_rate: Decimal, reason: str):
        self._validate_fill(price, time, fee_rate)
        position = self.position
        if position is None:
            raise ValueError("Portfolio has no position")
        gross = position.unrealized(price)
        exit_fee = position.plan.quantity * price * fee_rate
        trade = ClosedTrade(
            position.plan,
            position.opened_at,
            time,
            price,
            reason,
            gross,
            position.entry_fee,
            exit_fee,
            position.funding,
        )
        self.balance += gross - exit_fee
        self.realized_pnl += gross
        self.total_fees += exit_fee
        self.closed_trades.append(trade)
        self.position = None
        self._last_fill_at = time
        return trade
