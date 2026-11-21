from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradebot.market_data import Candle, DatasetError, Minute
from tradebot.paper import MarketSnapshot, PaperBatch
from tradebot.paper_strategy import PaperEntrySignals
from tradebot.risk import Side

START = datetime(2025, 1, 1, tzinfo=UTC)
SIGNAL = START + timedelta(hours=50)


def minute(index):
    opening = Decimal(1000 + index)
    candle = Candle(
        START + timedelta(minutes=index), opening, opening + 3, opening - 2, opening + 1, Decimal(2)
    )
    return Minute(candle, candle)


def batch(minutes, observed, *, quote_time=None, caught_up=True):
    snapshot = MarketSnapshot(
        observed,
        quote_time or observed,
        observed,
        Decimal(100),
        Decimal(102),
        Decimal(3),
        Decimal(5),
        Decimal(101),
        0,
    )
    return PaperBatch(tuple(minutes), snapshot, caught_up)


def warmed(policy):
    worker = PaperEntrySignals(policy)
    bars = [minute(index) for index in range(2999)]
    assert worker.observe(batch(bars, SIGNAL - timedelta(seconds=59))) is None
    return worker


@pytest.mark.parametrize(("action", "side", "price", "quantity"), [
    ("LONG", Side.LONG, 102, 5),
    ("SHORT", Side.SHORT, 100, 3),
])
def test_uses_observable_post_signal_quote_and_size(action, side, price, quantity):
    worker = warmed(lambda _: action)
    latest = minute(2999)
    received = SIGNAL + timedelta(milliseconds=100)
    old_quote = SIGNAL - timedelta(milliseconds=100)
    assert worker.observe(batch([latest], received, quote_time=old_quote)) is None
    received += timedelta(milliseconds=100)
    intent = worker.observe(batch([], received))
    assert intent is not None
    assert (intent.side, intent.quote_price, intent.displayed_quantity) == (side, price, quantity)
    assert intent.signal_time == SIGNAL
    assert intent.quote_time == intent.observed_at == received
    assert worker.observe(batch([], received)) is None


def test_refuses_historical_catch_up_even_at_latest_signal():
    worker = PaperEntrySignals(lambda _: "LONG")
    bars = [minute(index) for index in range(3000)]
    assert worker.observe(batch(bars, SIGNAL + timedelta(seconds=1))) is None
    assert worker.observe(batch([], SIGNAL + timedelta(seconds=2))) is None


def test_refuses_late_and_interrupted_signals():
    worker = warmed(lambda _: "LONG")
    assert worker.observe(batch([minute(2999)], SIGNAL + timedelta(seconds=6))) is None
    worker = warmed(lambda _: "LONG")
    worker.mark_unready()
    assert worker.observe(batch([minute(2999)], SIGNAL + timedelta(seconds=1))) is None


def test_invalid_batch_does_not_advance_feature_cursor():
    worker = warmed(lambda _: "LONG")
    with pytest.raises(DatasetError, match="tidak berurutan"):
        worker.observe(batch([minute(3000)], SIGNAL + timedelta(seconds=1)))
    assert worker.observe(batch([minute(2999)], SIGNAL + timedelta(seconds=2))) is None
