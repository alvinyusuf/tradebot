"""Public USDⓈ-M market data for a paper worker using its own execution model."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import urlopen

from .market_data import EPOCH, Candle, Minute

PUBLIC_BASE = "https://fapi.binance.com/fapi/v1"
SYMBOL = "BTCUSDT"
MINUTE_MS = 60_000
MILLISECOND = timedelta(milliseconds=1)
MAX_MARKET_AGE = timedelta(seconds=5)
MAX_CLOCK_DRIFT_MS = 1000
PUBLIC_PATHS = {"time", "ticker/bookTicker", "premiumIndex", "klines", "markPriceKlines", "fundingRate"}
Query = dict[str, str | int]
Transport = Callable[[str, Query], object]


class PaperFeedError(RuntimeError):
    """A failed poll leaves the last accepted cursor unchanged."""


def public_get(path: str, params: Query) -> object:
    if path not in PUBLIC_PATHS:
        raise ValueError(f"Endpoint publik tidak didukung: {path}")
    query = f"?{urlencode(params)}" if params else ""
    with urlopen(f"{PUBLIC_BASE}/{path}{query}", timeout=5) as response:
        return json.load(response)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ms(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp harus menyertakan timezone")
    return (value - EPOCH) // MILLISECOND


def _datetime(value: int) -> datetime:
    return EPOCH + value * MILLISECOND


def _timestamp(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Timestamp API harus berupa milidetik nonnegatif")
    return value


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    server_time: datetime
    quote_time: datetime
    mark_time: datetime
    bid_price: Decimal
    ask_price: Decimal
    bid_quantity: Decimal
    ask_quantity: Decimal
    mark_price: Decimal
    clock_drift_ms: int
    next_funding_time: datetime | None = None

    def fresh_at(self, server_now: datetime) -> bool:
        if server_now.utcoffset() != timedelta(0) or abs(self.clock_drift_ms) > MAX_CLOCK_DRIFT_MS:
            return False
        return all(
            stamp.utcoffset() == timedelta(0) and timedelta(0) <= server_now - stamp <= MAX_MARKET_AGE
            for stamp in (self.quote_time, self.mark_time)
        )


@dataclass(frozen=True, slots=True)
class PaperBatch:
    minutes: tuple[Minute, ...]
    snapshot: MarketSnapshot
    caught_up: bool


def _decode_candles(payload: object, start: int, end: int, *, mark: bool) -> tuple[Candle, ...]:
    if not isinstance(payload, list) or len(payload) != (end - start) // MINUTE_MS:
        raise ValueError("Jumlah candle tidak mencakup seluruh rentang yang diminta")
    candles = []
    for stamp, row in zip(range(start, end, MINUTE_MS), payload, strict=True):
        if not isinstance(row, list) or len(row) != 12:
            raise ValueError("Skema candle REST tidak valid")
        if _timestamp(row[0]) != stamp or _timestamp(row[6]) != stamp + MINUTE_MS - 1:
            raise ValueError(f"Gap, duplikat, atau candle belum selesai pada {_datetime(stamp).isoformat()}")
        opening, high, low, close = map(Decimal, row[1:5])
        volume = Decimal(0) if mark else Decimal(row[5])
        if not (
            all(value.is_finite() for value in (opening, high, low, close, volume))
            and 0 < low <= min(opening, close) <= max(opening, close) <= high
            and volume >= 0
        ):
            raise ValueError(f"OHLCV REST tidak valid pada {_datetime(stamp).isoformat()}")
        candles.append(Candle(_datetime(stamp), opening, high, low, close, volume))
    return tuple(candles)


def _decode_funding(payload: object, start: int, end: int) -> dict[int, tuple[Decimal, datetime, Decimal]]:
    if not isinstance(payload, list):
        raise TypeError("Skema funding REST tidak valid")
    funding = {}
    for event in payload:
        stamp = _timestamp(event["fundingTime"])
        minute = stamp // MINUTE_MS * MINUTE_MS
        if event["symbol"] != SYMBOL or not start <= stamp < end or minute in funding:
            raise ValueError("Funding berada di luar interval atau settlement menit berulang")
        rate, mark = Decimal(event["fundingRate"]), Decimal(event["markPrice"])
        if not rate.is_finite() or not mark.is_finite() or mark <= 0:
            raise ValueError("Rate atau mark price settlement tidak valid")
        funding[minute] = rate, _datetime(stamp), mark
    return funding


class BinancePaperFeed:
    """Poll closed minute bars in order with public-only readiness checks.

    The caller owns durable cursor persistence, polling cadence, reconnect
    supervision, and any treatment of catch-up bars in a paper PnL ledger.
    """

    def __init__(
        self,
        start: datetime,
        *,
        transport: Transport = public_get,
        clock: Callable[[], datetime] = _utc_now,
    ):
        cursor = _ms(start)
        if cursor < 0 or cursor % MINUTE_MS or start.microsecond:
            raise ValueError("Cursor harus sejajar ke pembukaan menit UTC")
        self._cursor = cursor
        self._transport = transport
        self._clock = clock
        self._expected_funding: int | None = None
        self.ready = False

    @property
    def cursor(self) -> datetime:
        return _datetime(self._cursor)

    def _server_clock(self) -> tuple[int, int]:
        before = _ms(self._clock())
        server = _timestamp(self._transport("time", {})["serverTime"])
        after = _ms(self._clock())
        drift = server - (before + after) // 2
        uncertainty = (after - before + 1) // 2
        if after < before or abs(drift) + uncertainty > MAX_CLOCK_DRIFT_MS:
            raise ValueError("Drift/jeda clock melewati batas satu detik")
        return server, drift

    def _snapshot(self, drift: int) -> tuple[MarketSnapshot, int]:
        mark = self._transport("premiumIndex", {"symbol": SYMBOL})
        quote = self._transport("ticker/bookTicker", {"symbol": SYMBOL})
        quote_time, mark_time = _timestamp(quote["time"]), _timestamp(mark["time"])
        server = _ms(self._clock()) + drift
        if quote["symbol"] != SYMBOL or mark["symbol"] != SYMBOL:
            raise ValueError("Symbol market snapshot salah")
        bid, ask = Decimal(quote["bidPrice"]), Decimal(quote["askPrice"])
        bid_size, ask_size = Decimal(quote["bidQty"]), Decimal(quote["askQty"])
        price = Decimal(mark["markPrice"])
        if not all(value.is_finite() and value > 0 for value in (bid, ask, bid_size, ask_size, price)):
            raise ValueError("Quote, mark price, atau depth top-of-book tidak valid")
        if bid > ask:
            raise ValueError("Bid melewati ask")
        next_funding = _timestamp(mark["nextFundingTime"])
        if next_funding <= mark_time:
            raise ValueError("Waktu funding berikutnya belum diperbarui")
        snapshot = MarketSnapshot(
            _datetime(server), _datetime(quote_time), _datetime(mark_time),
            bid, ask, bid_size, ask_size, price, drift, _datetime(next_funding),
        )
        if not snapshot.fresh_at(snapshot.server_time):
            raise ValueError("Quote atau mark price kedaluwarsa atau bertimestamp masa depan")
        return snapshot, next_funding

    def poll(self, max_minutes: int = 499) -> PaperBatch:
        if not 1 <= max_minutes <= 499:
            raise ValueError("Ukuran batch paper harus di antara 1 dan 499 menit")
        self.ready = False
        try:
            server, drift = self._server_clock()
            closed_through = server // MINUTE_MS * MINUTE_MS
            if self._cursor > closed_through:
                raise ValueError("Cursor lebih baru dari candle terakhir yang selesai")
            end = min(closed_through, self._cursor + max_minutes * MINUTE_MS)
            minutes = self._read_minutes(self._cursor, end)
            snapshot, next_funding = self._snapshot(drift)
            if (
                self._expected_funding is not None
                and self._cursor <= self._expected_funding < end
                and not any(
                    minute.funding_time is not None
                    and _ms(minute.funding_time) // MINUTE_MS == self._expected_funding // MINUTE_MS
                    for minute in minutes
                )
            ):
                raise ValueError("Settlement funding yang diharapkan belum tersedia")
        except (ArithmeticError, KeyError, OSError, TypeError, ValueError) as exc:
            raise PaperFeedError(str(exc)) from exc
        if (
            self._expected_funding is None
            or self._expected_funding < end
            or _ms(snapshot.mark_time) < self._expected_funding
        ):
            self._expected_funding = next_funding
        self._cursor = end
        self.ready = end == _ms(snapshot.server_time) // MINUTE_MS * MINUTE_MS
        return PaperBatch(minutes, snapshot, self.ready)

    def _read_minutes(self, start: int, end: int) -> tuple[Minute, ...]:
        if start == end:
            return ()
        interval = {"symbol": SYMBOL, "startTime": start, "endTime": end - 1}
        query = {**interval, "interval": "1m", "limit": (end - start) // MINUTE_MS}
        contract = _decode_candles(self._transport("klines", query), start, end, mark=False)
        mark = _decode_candles(self._transport("markPriceKlines", query), start, end, mark=True)
        funding = _decode_funding(
            self._transport("fundingRate", {**interval, "limit": 1000}), start, end
        )
        return tuple(
            Minute(contract_bar, mark_bar, *funding.get(_ms(contract_bar.open_time), (None, None, None)))
            for contract_bar, mark_bar in zip(contract, mark, strict=True)
        )
