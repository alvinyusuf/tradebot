from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from tradebot.demo_preflight import demo_preflight
from tradebot.paper import PaperFeedError

NOW = datetime(2026, 11, 21, 15, 59, 10, tzinfo=UTC)


def test_preflight_requires_real_market_and_demo_clock():
    def feed(start, *, clock):
        assert start == NOW.replace(second=0) - timedelta(minutes=1)
        assert clock() == NOW
        batch = SimpleNamespace(
            caught_up=True,
            minutes=(object(),),
            snapshot=SimpleNamespace(quote_time=NOW, mark_time=NOW),
        )
        return SimpleNamespace(poll=lambda *, max_minutes: batch)

    report = demo_preflight(
        clock=lambda: NOW,
        read_demo_time=lambda: {"serverTime": int(NOW.timestamp() * 1000)},
        feed_factory=feed,
    )
    assert report["ready"]
    assert report["demo"]["clock_offset_ms"] == 0
    delayed = demo_preflight(
        clock=lambda: NOW,
        read_demo_time=lambda: {"serverTime": int(NOW.timestamp() * 1000) - 1001},
        feed_factory=feed,
    )
    assert delayed["market"]["ready"]
    assert not delayed["demo"]["ready"]
    assert not delayed["ready"]


def test_preflight_checks_demo_even_if_market_is_unavailable():
    def feed(*_args, **_kwargs):
        raise PaperFeedError("fixture connection refused")

    report = demo_preflight(
        clock=lambda: NOW,
        read_demo_time=lambda: {"serverTime": int(NOW.timestamp() * 1000)},
        feed_factory=feed,
    )
    assert report["demo"]["ready"] and not report["ready"]
    assert report["market"]["error"] == "fixture connection refused"
