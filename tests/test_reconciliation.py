import pytest

from tradebot.reconciliation import OrderJournal, OrderRecord


def test_unknown_intent_survives_restart_duplicate_events_and_backup(tmp_path):
    database = tmp_path / "journal.db"
    journal = OrderJournal(database)
    journal.plan("entry-1")
    journal.record("entry-1", "timeout-1", "unknown")
    recovered = OrderJournal(database)
    assert recovered.unresolved() == (OrderRecord("entry-1", "unknown"),)
    with pytest.raises(ValueError, match="sudah tercatat"):
        recovered.plan("entry-1")

    recovered.record("entry-1", "partial-1", "partial")
    recovered.record("entry-1", "partial-1", "partial")
    with pytest.raises(ValueError, match="Isi event berbeda"):
        recovered.record("entry-1", "partial-1", "filled")
    recovered.record("entry-1", "fill-1", "filled")
    recovered.record("entry-1", "partial-1", "partial")
    assert recovered.unresolved() == ()

    backup = tmp_path / "backup.db"
    recovered.plan("exit-1")
    recovered.backup(backup)
    recovered.record("exit-1", "exit-filled", "filled")
    assert OrderJournal(backup).unresolved() == (OrderRecord("exit-1", "pending"),)
