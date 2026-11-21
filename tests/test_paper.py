from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradebot.paper import BinancePaperFeed, PaperFeedError, public_get

START = datetime(2025, 1, 1, tzinfo=UTC)
START_MS = int(START.timestamp()) * 1000
MINUTE_MS = 60_000


class FixtureTransport:
    def __init__(self):
        self.now = START + timedelta(minutes=4, seconds=3)
        self.clock_skew = 0
        self.quote_age = 10
        self.mark_gap = False
        self.next_funding = START_MS + 5 * MINUTE_MS
        self.events = []
        self.requests = []

    def clock(self):
        return self.now

    def __call__(self, path, params):
        self.requests.append((path, params))
        now_ms = int(self.now.timestamp() * 1000)
        if path == "time":
            return {"serverTime": now_ms + self.clock_skew}
        if path == "ticker/bookTicker":
            return {
                "symbol": "BTCUSDT",
                "bidPrice": "100",
                "askPrice": "101",
                "bidQty": "1",
                "askQty": "2",
                "time": now_ms - self.quote_age,
            }
        if path == "premiumIndex":
            return {
                "symbol": "BTCUSDT",
                "markPrice": "100.5",
                "time": now_ms - 10,
                "nextFundingTime": self.next_funding,
            }
        start, end = params["startTime"], params["endTime"]
        if path == "fundingRate":
            return [event for event in self.events if start <= event["fundingTime"] <= end]
        rows = [
            [stamp, "100", "110", "90", "101", "20", stamp + MINUTE_MS - 1, "0", 10, "0", "0", "0"]
            for stamp in range(start, end + 1, MINUTE_MS)
        ]
        return rows[1:] if path == "markPriceKlines" and self.mark_gap else rows


def test_catch_up_validates_sequences_and_never_consumes_open_candle():
    transport = FixtureTransport()
    feed = BinancePaperFeed(START, transport=transport, clock=transport.clock)
    first = feed.poll(max_minutes=2)
    assert not first.caught_up
    assert [minute.contract.open_time for minute in first.minutes] == [
        START, START + timedelta(minutes=1),
    ]
    assert all(minute.mark.open_time == minute.contract.open_time for minute in first.minutes)
    second = feed.poll()
    assert second.caught_up and feed.ready
    assert feed.cursor == START + timedelta(minutes=4)
    assert [minute.contract.open_time for minute in second.minutes] == [
        START + timedelta(minutes=2), START + timedelta(minutes=3),
    ]
    assert second.snapshot.bid_quantity == Decimal(1)
    assert feed.poll().minutes == ()
    assert all(path not in {"order", "account"} for path, _ in transport.requests)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("quote_age", 5001, "kedaluwarsa"),
        ("clock_skew", 1001, "Drift"),
        ("mark_gap", True, "Jumlah candle"),
    ],
)
def test_refuses_stale_clock_or_gap_without_consuming_cursor(field, value, error):
    transport = FixtureTransport()
    setattr(transport, field, value)
    feed = BinancePaperFeed(START, transport=transport, clock=transport.clock)
    with pytest.raises(PaperFeedError, match=error):
        feed.poll()
    assert feed.cursor == START
    assert not feed.ready


def test_waits_for_observed_funding_settlement_and_preserves_exact_time():
    transport = FixtureTransport()
    feed = BinancePaperFeed(START + timedelta(minutes=4), transport=transport, clock=transport.clock)
    assert feed.poll().caught_up
    settlement = transport.next_funding
    transport.now = START + timedelta(minutes=6, seconds=3)
    transport.next_funding += 8 * 60 * MINUTE_MS
    with pytest.raises(PaperFeedError, match="Settlement"):
        feed.poll()
    assert feed.cursor == START + timedelta(minutes=4)

    transport.events.append({
        "symbol": "BTCUSDT",
        "fundingTime": settlement + 7,
        "fundingRate": "-0.001",
        "markPrice": "100.5",
    })
    batch = feed.poll()
    assert batch.caught_up
    assert batch.minutes[0].funding_rate is None
    funded = batch.minutes[1]
    assert funded.funding_time == START + timedelta(minutes=5, milliseconds=7)
    assert funded.funding_rate == Decimal("-0.001")
    assert funded.funding_mark_price == Decimal("100.5")


def test_default_transport_refuses_nonmarket_endpoints():
    with pytest.raises(ValueError, match="Endpoint publik"):
        public_get("order", {})
