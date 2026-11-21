"""Journal Demo market intents before sending and reconcile by stable ID."""

from collections.abc import Callable
from decimal import Decimal

from .demo_execution import DemoAPIError, DemoExecution, DemoOrder, DemoRequestUncertain
from .reconciliation import OrderJournal, OrderState
from .risk import OrderPlan, Side

_STATES: dict[str, OrderState] = {
    "NEW": "acknowledged",
    "PARTIALLY_FILLED": "partial",
    "FILLED": "filled",
    "CANCELED": "canceled",
    "REJECTED": "rejected",
    "EXPIRED": "canceled",
    "EXPIRED_IN_MATCH": "canceled",
}


class DemoMarketJournal:
    def __init__(self, execution: DemoExecution, journal: OrderJournal):
        self.execution = execution
        self.journal = journal

    def _record(self, order: DemoOrder) -> DemoOrder:
        state = _STATES[order.status]
        self.journal.record(
            order.client_id, f"demo:{order.client_id}:{order.order_id}:{state}", state
        )
        return order

    def _submit(self, client_id: str, send: Callable[[], DemoOrder]) -> DemoOrder:
        self.journal.plan(client_id, require_no_unresolved=True)
        try:
            order = send()
        except DemoRequestUncertain:
            self.journal.record(client_id, f"demo:{client_id}:unknown", "unknown")
            raise
        except (DemoAPIError, TypeError, ValueError):
            self.journal.record(client_id, f"demo:{client_id}:rejected", "rejected")
            raise
        return self._record(order)

    def enter(self, plan: OrderPlan, *, client_id: str) -> DemoOrder:
        return self._submit(
            client_id, lambda: self.execution.submit_entry(plan, client_id=client_id)
        )

    def close(self, side: Side, quantity: Decimal, *, client_id: str) -> DemoOrder:
        return self._submit(
            client_id,
            lambda: self.execution.close_position(side, quantity, client_id=client_id),
        )

    def reconcile(self, client_id: str) -> DemoOrder:
        if self.journal.state(client_id) is None:
            raise ValueError("Client ID Demo tidak tercatat")
        return self._record(self.execution.query_order(client_id))
