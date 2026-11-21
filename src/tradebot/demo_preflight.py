"""Verify public production data and official Demo connectivity separately."""

import json
from datetime import UTC, datetime, timedelta
from urllib.request import urlopen

from .demo_metadata import DEMO_API
from .paper import BinancePaperFeed, PaperFeedError


def _now() -> datetime:
    return datetime.now(UTC)


def _demo_time() -> dict:
    with urlopen(f"{DEMO_API}/time", timeout=5) as response:
        return json.load(response)


def demo_preflight(
    *, clock=_now, read_demo_time=_demo_time, feed_factory=BinancePaperFeed
) -> dict:
    start = clock().replace(second=0, microsecond=0) - timedelta(minutes=1)
    result = {"checked_at_utc": clock().isoformat(), "market": {}, "demo": {}}
    try:
        batch = feed_factory(start, clock=clock).poll(max_minutes=3)
        result["market"] = {
            "ready": batch.caught_up and bool(batch.minutes),
            "closed_minutes": len(batch.minutes),
            "last_quote_utc": batch.snapshot.quote_time.isoformat(),
            "last_mark_utc": batch.snapshot.mark_time.isoformat(),
        }
    except (OSError, ValueError, PaperFeedError) as exc:
        result["market"] = {"ready": False, "error": str(exc)}
    try:
        before = clock()
        server_ms = read_demo_time()["serverTime"]
        after = clock()
        if type(server_ms) is not int or server_ms <= 0:
            raise ValueError("Timestamp server demo tidak valid")
        server = datetime.fromtimestamp(server_ms / 1000, UTC)
        drift = server - (before + (after - before) / 2)
        uncertainty = (after - before) / 2
        result["demo"] = {
            "ready": after >= before
            and abs(drift) + uncertainty <= timedelta(seconds=1),
            "server_time_utc": server.isoformat(),
            "clock_offset_ms": drift / timedelta(milliseconds=1),
            "uncertainty_ms": uncertainty / timedelta(milliseconds=1),
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        result["demo"] = {"ready": False, "error": str(exc)}
    result["ready"] = result["market"]["ready"] and result["demo"]["ready"]
    return result
