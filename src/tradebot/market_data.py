"""Validated, time-aligned minute data from audited Binance archives."""

import csv
import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ONE_MINUTE = timedelta(minutes=1)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
SERIES = ("klines", "markPriceKlines", "fundingRate")


class DatasetError(ValueError):
    """The requested interval cannot produce a valid continuous run."""


@dataclass(frozen=True, slots=True)
class Candle:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class Minute:
    contract: Candle
    mark: Candle
    funding_rate: Decimal | None = None
    funding_time: datetime | None = None
    funding_mark_price: Decimal | None = None
    funding_time_verified: bool = False


def _utc_minute(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DatasetError("Timestamp must be timezone-aware")
    value = value.astimezone(UTC)
    if value.second or value.microsecond:
        raise DatasetError("Expected an exact UTC minute boundary")
    return value


def _month_start(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0)


def _next_month(value: datetime) -> datetime:
    return _month_start(value + timedelta(days=32))


def _timestamp(ms: int) -> datetime:
    return EPOCH + timedelta(milliseconds=ms)


def _candle(row: dict[str, str]) -> Candle:
    ms = int(row["open_time"])
    opening, high, low, close, volume = (
        Decimal(row[field]) for field in ("open", "high", "low", "close", "volume")
    )
    if (
        ms % 60000
        or int(row["close_time"]) != ms + 59999
        or not all(value.is_finite() for value in (opening, high, low, close, volume))
        or not (
            0 < low <= min(opening, close) <= max(opening, close) <= high
            and volume >= 0
        )
    ):
        raise DatasetError(f"Invalid candle at {_timestamp(ms).isoformat()}")
    return Candle(_timestamp(ms), opening, high, low, close, volume)


def _rest_rows(
    evidence: dict, endpoint: str, query: dict[str, list[str]], available: datetime
):
    source = urlparse(evidence["source"])
    if (
        (source.scheme, source.netloc, source.path)
        != (
            "https",
            "fapi.binance.com",
            f"/fapi/v1/{endpoint}",
        )
        or source.params
        or source.fragment
        or parse_qs(source.query, keep_blank_values=True, strict_parsing=True) != query
    ):
        raise ValueError("Unexpected source or query")
    attempted = datetime.fromisoformat(evidence["attempted_at"])
    fetched = datetime.fromisoformat(evidence["fetched_at"])
    if (
        attempted.utcoffset() != timedelta(0)
        or fetched.utcoffset() != timedelta(0)
        or not available <= attempted <= fetched
    ):
        raise ValueError("Invalid collection timestamps")
    raw = evidence["response_text"].encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != evidence["response_sha256"]:
        raise ValueError("REST response checksum mismatch")
    return json.loads(raw)


def _rest_candle(stamp: int, evidence: dict) -> Candle:
    try:
        rows = _rest_rows(
            evidence,
            "markPriceKlines",
            {
                "symbol": ["BTCUSDT"],
                "interval": ["1m"],
                "startTime": [str(stamp)],
                "endTime": [str(stamp + 59999)],
                "limit": ["1"],
            },
            _timestamp(stamp) + ONE_MINUTE,
        )
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("Expected one REST candle")
        row = rows[0]
        if not isinstance(row, list) or len(row) != 12 or row != evidence["data"]:
            raise ValueError("Invalid or inconsistent REST candle schema")
        if type(row[0]) is not int or type(row[6]) is not int or row[0] != stamp:
            raise ValueError("Unexpected candle timestamp")
        if not all(isinstance(value, str) for value in row[1:5]):
            raise ValueError("Expected REST price strings")
        return _candle(
            {
                "open_time": stamp,
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "close_time": row[6],
                "volume": "0",
            }
        )
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise DatasetError(
            f"Invalid REST repair at {_timestamp(stamp).isoformat()}: {exc}"
        ) from exc


def _verified_funding(history: dict, start: datetime, end: datetime):
    """Return exact REST rows, indexed by matching archive settlement minute."""
    try:
        start_ms = (start - EPOCH) // timedelta(milliseconds=1)
        end_ms = (end - EPOCH) // timedelta(milliseconds=1)
        if (history["start_utc_ms"], history["end_exclusive_utc_ms"]) != (
            start_ms,
            end_ms,
        ):
            raise ValueError("Funding evidence range differs from the audit manifest")
        pages = history["pages"]
        if not pages or any("error" in page for page in pages):
            return None
        cursor = start_ms
        funding = {}
        for index, evidence in enumerate(pages):
            rows = _rest_rows(
                evidence,
                "fundingRate",
                {
                    "symbol": ["BTCUSDT"],
                    "startTime": [str(cursor)],
                    "endTime": [str(end_ms - 1)],
                    "limit": ["1000"],
                },
                end,
            )
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError("Unexpected funding page length")
            for row in rows:
                stamp = row["fundingTime"]
                if (
                    row["symbol"] != "BTCUSDT"
                    or row.get("rateType", "Regular") != "Regular"
                    or type(stamp) is not int
                    or not cursor <= stamp < end_ms
                ):
                    raise ValueError("Unexpected or unordered REST funding timestamp")
                rate = Decimal(row["fundingRate"])
                raw_price = row["markPrice"]
                price = None if raw_price == "" else Decimal(raw_price)
                boundary = _timestamp(stamp // 60000 * 60000)
                if (
                    boundary in funding
                    or not rate.is_finite()
                    or (price is not None and (not price.is_finite() or price <= 0))
                ):
                    raise ValueError("Invalid or duplicate REST funding row")
                funding[boundary] = rate, _timestamp(stamp), price
                cursor = stamp + 1
            last = index == len(pages) - 1
            if (len(rows) == 1000 and last and cursor < end_ms) or (
                len(rows) < 1000 and not last
            ):
                raise ValueError("Funding pagination is incomplete or inconsistent")
        return funding
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise DatasetError(f"Invalid REST funding evidence: {exc}") from exc


class ArchiveDataset:
    """Bind local archives to the exact audit manifest used for a run."""

    def __init__(
        self,
        manifest_path: Path | str,
        *,
        public_api_report: Path | str | None = None,
    ):
        path = Path(manifest_path)
        self.root = path.parent
        raw = path.read_bytes()
        self.manifest_sha256 = hashlib.sha256(raw).hexdigest()
        manifest = json.loads(raw)
        if manifest["schema_version"] != 1 or manifest["timezone"] != "UTC":
            raise DatasetError("Unsupported archive manifest schema or timezone")
        self.start = _utc_minute(datetime.fromisoformat(manifest["warmup_start"]))
        self.end = _utc_minute(datetime.fromisoformat(manifest["end_exclusive"]))
        self.funding_discrepancies = manifest["funding_interval_discrepancies"]
        self.archives = {}
        self.repairs = {}
        self.rest_repairs: dict[str, dict[int, Candle]] = {}
        self.public_api_report_sha256 = None
        self.rest_funding = None
        for entry in manifest["archives"]:
            key = entry["series"], entry["month"]
            if key in self.archives:
                raise DatasetError(f"Duplicate archive in manifest: {key}")
            self.archives[key] = entry
        for entry in manifest["daily_repairs"]:
            key = entry["series"], entry["month"][:7]
            if entry.get("recovered_open_times_utc_ms"):
                self.repairs.setdefault(key, []).append(entry)
        if public_api_report is not None:
            self._load_rest_repairs(Path(public_api_report))

    def _load_rest_repairs(self, path: Path) -> None:
        raw = path.read_bytes()
        report = json.loads(raw)
        if (
            report.get("schema_version") != 2
            or report.get("archive_manifest_sha256") != self.manifest_sha256
        ):
            raise DatasetError("REST report does not match audit manifest")
        for key, evidence in report["mark_price_repairs"].items():
            stamp = int(key)
            month = _timestamp(stamp).strftime("%Y-%m")
            month_key = ("markPriceKlines", month)
            entry = self.archives.get(month_key)
            if (
                key != str(stamp)
                or entry is None
                or stamp not in entry.get("missing_open_times_utc_ms", [])
                or any(
                    stamp in repair["recovered_open_times_utc_ms"]
                    for repair in self.repairs.get(month_key, ())
                )
            ):
                raise DatasetError(f"Unexpected REST repair timestamp: {key}")
            if "error" not in evidence:
                self.rest_repairs.setdefault(month, {})[stamp] = _rest_candle(
                    stamp, evidence
                )
        if "funding_history" in report:
            self.rest_funding = _verified_funding(
                report["funding_history"], self.start, self.end
            )
        self.public_api_report_sha256 = hashlib.sha256(raw).hexdigest()

    @property
    def funding_timing(self):
        if self.rest_funding is not None:
            return "rest_settlement"
        return "archive_calc_time_approximation"

    @property
    def missing_rest_funding_marks(self) -> int | None:
        if self.rest_funding is None:
            return None
        return sum(price is None for _, _, price in self.rest_funding.values())

    def unrepaired_minutes(self) -> tuple[tuple[str, int], ...]:
        missing = set()
        for key, archive in self.archives.items():
            series, month = key
            repaired = {
                stamp
                for evidence in self.repairs.get(key, ())
                if "error" not in evidence and evidence.get("sha256")
                for stamp in evidence["recovered_open_times_utc_ms"]
            }
            if series == "markPriceKlines":
                repaired.update(self.rest_repairs.get(month, ()))
            missing.update(
                (series, stamp)
                for stamp in archive.get("missing_open_times_utc_ms", [])
                if stamp not in repaired
            )
        return tuple(sorted(missing))

    def _entries(self, month: datetime, start: datetime, end: datetime) -> dict:
        label = month.strftime("%Y-%m")
        entries = {}
        for series in SERIES:
            key = series, label
            entry = self.archives.get(key)
            if entry is None or entry.get("error") or not entry.get("sha256"):
                raise DatasetError(f"Missing or invalid archive: {series}/{label}")
            recovered = set()
            for repair in self.repairs.get(key, ()):
                if repair.get("error") or not repair.get("sha256"):
                    raise DatasetError(f"Unverified repair: {repair['source']}")
                recovered.update(repair["recovered_open_times_utc_ms"])
            if series == "markPriceKlines":
                recovered.update(self.rest_repairs.get(label, ()))
            for stamp in entry.get("missing_open_times_utc_ms", []):
                if stamp not in recovered and start <= _timestamp(stamp) < end:
                    raise DatasetError(
                        f"{series} has an unrepaired gap at {_timestamp(stamp).isoformat()}"
                    )
            entries[series] = entry
        return entries

    def _rows(self, entry: dict) -> Iterator[dict[str, str]]:
        series = entry["series"]
        label = entry["month"]
        if series not in SERIES or not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", label):
            raise DatasetError(f"Unexpected archive series or label: {series}/{label}")
        period = "monthly" if len(label) == 7 else "daily"
        folder = "BTCUSDT" if series == "fundingRate" else "BTCUSDT/1m"
        stamp = "fundingRate" if series == "fundingRate" else "1m"
        filename = f"BTCUSDT-{stamp}-{label}.zip"
        expected_path = f"/data/futures/um/{period}/{series}/{folder}/{filename}"
        source = urlparse(entry["source"])
        if (
            (source.scheme, source.netloc, source.path)
            != ("https", "data.binance.vision", expected_path)
            or source.params
            or source.query
            or source.fragment
        ):
            raise DatasetError(f"Unexpected archive source: {entry['source']}")
        payload = (self.root / series / filename).read_bytes()
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise DatasetError(f"Archive checksum mismatch: {filename}")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.namelist()
            if members != [filename.removesuffix(".zip") + ".csv"]:
                raise DatasetError(f"Unexpected archive member: {filename}")
            with archive.open(members[0]) as stream:
                yield from csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8"))

    def _candles(self, entry: dict, start: datetime, end: datetime) -> Iterator[Candle]:
        repairs = (
            self.rest_repairs.get(entry["month"], {}).copy()
            if entry["series"] == "markPriceKlines"
            else {}
        )
        for repair in self.repairs.get((entry["series"], entry["month"]), ()):
            expected = set(repair["recovered_open_times_utc_ms"])
            for row in self._rows(repair):
                stamp = int(row["open_time"])
                if stamp in expected:
                    if stamp in repairs:
                        raise DatasetError(
                            f"Duplicate repair at {_timestamp(stamp).isoformat()}"
                        )
                    repairs[stamp] = _candle(row)
        repair_rows = iter(
            sorted(repairs.values(), key=lambda candle: candle.open_time)
        )
        next_repair = next(repair_rows, None)
        for row in self._rows(entry):
            stamp = _timestamp(int(row["open_time"]))
            while next_repair is not None and next_repair.open_time <= stamp:
                if next_repair.open_time == stamp:
                    raise DatasetError(
                        f"Repair overlaps an existing candle at {stamp.isoformat()}"
                    )
                if start <= next_repair.open_time < end:
                    yield next_repair
                next_repair = next(repair_rows, None)
            if start <= stamp < end:
                yield _candle(row)
        while next_repair is not None:
            if start <= next_repair.open_time < end:
                yield next_repair
            next_repair = next(repair_rows, None)

    def _funding(self, entry: dict) -> dict[datetime, tuple[Decimal, datetime]]:
        funding = {}
        for row in self._rows(entry):
            raw_ms = int(row["calc_time"])
            boundary = _timestamp((raw_ms + 30000) // 60000 * 60000)
            rate = Decimal(row["last_funding_rate"])
            if boundary in funding or not rate.is_finite():
                raise DatasetError(
                    f"Invalid or duplicate funding at {boundary.isoformat()}"
                )
            funding[boundary] = rate, _timestamp(raw_ms)
        return funding

    def minutes(
        self,
        start: datetime,
        end: datetime,
        *,
        allow_funding_approximation: bool = False,
    ) -> Iterator[Minute]:
        start, end = _utc_minute(start), _utc_minute(end)
        if not self.start <= start < end <= self.end:
            raise DatasetError("Requested interval is outside the audited dataset")
        for gap in self.funding_discrepancies:
            if (
                start < _timestamp(gap["next_utc_ms"])
                and _timestamp(gap["previous_utc_ms"]) < end
            ):
                raise DatasetError(
                    "Requested interval overlaps a funding schedule discrepancy"
                )
        intervals = []
        month = _month_start(start)
        while month < end:
            next_month = _next_month(month)
            left, right = max(start, month), min(end, next_month)
            intervals.append((left, right, self._entries(month, left, right)))
            month = next_month
        if self.rest_funding is None and not allow_funding_approximation:
            raise DatasetError(
                "Archive calc_time has not been verified against exact REST settlement times"
            )
        verified = self.rest_funding
        archive_funding = {}
        for left, right, entries in intervals:
            archive_funding.update(
                (time, pair)
                for time, pair in self._funding(entries["fundingRate"]).items()
                if left <= time < right
            )
        if verified is not None and {
            time: record[0] for time, record in archive_funding.items()
        } != {
            time: record[0] for time, record in verified.items() if start <= time < end
        }:
            raise DatasetError(
                "REST and archive funding minute schedules or rates differ"
            )
        for left, right, entries in intervals:
            contracts = self._candles(entries["klines"], left, right)
            marks = self._candles(entries["markPriceKlines"], left, right)
            expected = left
            for contract, mark in zip(contracts, marks, strict=True):
                if contract.open_time != expected or mark.open_time != expected:
                    raise DatasetError(
                        f"Unaligned or missing candle at {expected.isoformat()}"
                    )
                if verified is None:
                    rate, raw_time = archive_funding.get(expected, (None, None))
                    price = None
                else:
                    rate, raw_time, price = verified.get(expected, (None, None, None))
                yield Minute(
                    contract,
                    mark,
                    rate,
                    raw_time,
                    price,
                    verified is not None and rate is not None,
                )
                expected += ONE_MINUTE
            if expected != right:
                raise DatasetError(f"Missing candle at {expected.isoformat()}")

    def export_parquet(
        self,
        destination: Path | str,
        start: datetime,
        end: datetime,
        *,
        allow_funding_approximation: bool = False,
    ) -> str:
        """Publish a validated interval once, with provenance embedded in the schema."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        start, end = _utc_minute(start), _utc_minute(end)
        destination = Path(destination)
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        timestamp = pa.timestamp("ms", tz="UTC")
        number = pa.decimal128(38, 18)
        fields = [
            (f"{source}_{name}", number)
            for source in ("contract", "mark")
            for name in ("open", "high", "low", "close", "volume")
        ]
        metadata = {
            b"tradebot_schema_version": b"1",
            b"source_manifest_sha256": self.manifest_sha256.encode("ascii"),
            b"start_inclusive": start.isoformat().encode("ascii"),
            b"end_exclusive": end.isoformat().encode("ascii"),
            b"funding_timing": self.funding_timing.encode("ascii"),
            b"funding_missing_mark_model": b"historical_simulator_uses_mark_minute_open",
        }
        if self.public_api_report_sha256 is not None:
            metadata[b"source_public_api_report_sha256"] = (
                self.public_api_report_sha256.encode("ascii")
            )
        schema = pa.schema(
            [
                ("open_time", timestamp),
                ("available_at", timestamp),
                *fields,
                ("funding_rate", number),
                ("funding_settlement_time", timestamp),
                ("funding_mark_price", number),
                ("funding_archive_calc_time", timestamp),
            ],
            metadata=metadata,
        )

        def record(minute: Minute) -> dict:
            values = {
                "open_time": minute.contract.open_time,
                "available_at": minute.contract.open_time + ONE_MINUTE,
                "funding_rate": minute.funding_rate,
                "funding_archive_calc_time": (
                    minute.funding_time if not minute.funding_time_verified else None
                ),
                "funding_settlement_time": (
                    minute.funding_time if minute.funding_time_verified else None
                ),
                "funding_mark_price": minute.funding_mark_price,
            }
            for source, candle in (
                ("contract", minute.contract),
                ("mark", minute.mark),
            ):
                values.update(
                    {
                        f"{source}_{name}": getattr(candle, name)
                        for name in ("open", "high", "low", "close", "volume")
                    }
                )
            return values

        minutes = self.minutes(
            start, end, allow_funding_approximation=allow_funding_approximation
        )
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, suffix=".tmp", delete=False
        ) as temp:
            temporary = Path(temp.name)
        try:
            with pq.ParquetWriter(temporary, schema) as writer:
                for batch in _batches(map(record, minutes), 4096):
                    writer.write_table(pa.Table.from_pylist(batch, schema=schema))
            with temporary.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            os.link(temporary, destination)
        finally:
            temporary.unlink()
        return digest


def _batches(rows: Iterable[dict], size: int) -> Iterator[list[dict]]:
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
