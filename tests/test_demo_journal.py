from decimal import Decimal
from types import SimpleNamespace

import pytest

from tradebot.demo_execution import DemoOrder, DemoRequestUncertain
from tradebot.demo_journal import DemoMarketJournal
from tradebot.reconciliation import OrderJournal
from tradebot.risk import Side


def test_demo_order_is_checkpointed_and_unknown_blocks_submit_until_lookup(tmp_path):
    path = tmp_path / "demo.db"
    journal = OrderJournal(path)
    sent = []

    def close(_side, _quantity, *, client_id):
        assert OrderJournal(path).state(client_id) == "pending"
        sent.append(client_id)
        raise DemoRequestUncertain("fixture timeout")

    def query(client_id):
        return DemoOrder(client_id, 1, "FILLED", "SELL", Decimal(1), Decimal(1))

    execution = SimpleNamespace(close_position=close, query_order=query)
    adapter = DemoMarketJournal(execution, journal)
    with pytest.raises(DemoRequestUncertain):
        adapter.close(Side.LONG, Decimal(1), client_id="close-1")
    restarted = DemoMarketJournal(execution, OrderJournal(path))
    assert restarted.journal.state("close-1") == "unknown"
    with pytest.raises(ValueError, match="direkonsiliasi"):
        restarted.close(Side.LONG, Decimal(1), client_id="close-2")
    assert sent == ["close-1"]
    for _ in range(2):
        assert restarted.reconcile("close-1").status == "FILLED"
    assert not restarted.journal.unresolved()
