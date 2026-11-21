"""Audit official Binance monthly archives without calculating trading results."""

import calendar
import csv
import hashlib
import io
import json
import math
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

BASE = "https://data.binance.vision/data/futures/um"
ROOT = Path("data/audit")
SERIES = {
    "klines": "BTCUSDT/1m/BTCUSDT-1m",
    "markPriceKlines": "BTCUSDT/1m/BTCUSDT-1m",
    "fundingRate": "BTCUSDT/BTCUSDT-fundingRate",
}
CANDLE_HEADER = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]
FUNDING_HEADER = ["calc_time", "funding_interval_hours", "last_funding_rate"]


def download(url):
    with urlopen(url, timeout=25) as response:
        return response.read()


def audit(task):
    series, year, month, day = task
    label = f"{year:04d}-{month:02d}"
    period = "monthly"
    if day is not None:
        label += f"-{day:02d}"
        period = "daily"
    url = f"{BASE}/{period}/{series}/{SERIES[series]}-{label}.zip"
    path = ROOT / series / url.rsplit("/", 1)[-1]
    result = {"series": series, "month": label, "source": url}
    try:
        expected_hash = download(url + ".CHECKSUM").decode("ascii").split()[0]
        payload = path.read_bytes() if path.exists() else b""
        if hashlib.sha256(payload).hexdigest() != expected_hash:
            payload = download(url)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != expected_hash:
            raise ValueError("Checksum SHA-256 berbeda dari checksum resmi")
        result["sha256"] = digest
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != payload:
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(payload)
            temporary.replace(path)
        start = int(datetime(year, month, day or 1, tzinfo=UTC).timestamp()) * 1000
        minutes = (1 if day is not None else calendar.monthrange(year, month)[1]) * 1440
        end = start + minutes * 60000
        funding = series == "fundingRate"
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if len(archive.namelist()) != 1:
                raise ValueError("Jumlah entri ZIP berbeda dari skema")
            with archive.open(archive.namelist()[0]) as raw:
                rows = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
                header = next(rows)
                if header != (FUNDING_HEADER if funding else CANDLE_HEADER):
                    raise ValueError(f"Header tidak sesuai: {header}")
                previous = None
                seen = set()
                funding_times = []
                for row in rows:
                    stamp = int(row[0])
                    if len(row) != len(header) or not start <= stamp < end:
                        raise ValueError(f"Baris di luar rentang atau skema: {stamp}")
                    if previous is not None and stamp < previous:
                        raise ValueError(f"Timestamp tidak terurut: {stamp}")
                    previous = stamp
                    if funding:
                        hours = int(row[1])
                        if hours <= 0 or not math.isfinite(float(row[2])):
                            raise ValueError(f"Funding tidak valid: {stamp}")
                        funding_times.append([stamp, hours])
                    else:
                        if (stamp - start) % 60000 or int(row[6]) != stamp + 59999:
                            raise ValueError(f"Boundary candle tidak valid: {stamp}")
                        opening, high, low, close, volume = map(float, row[1:6])
                        if not (
                            all(map(math.isfinite, (opening, high, low, close, volume)))
                            and 0
                            < low
                            <= min(opening, close)
                            <= max(opening, close)
                            <= high
                            and volume >= 0
                        ):
                            raise ValueError(f"OHLCV tidak valid: {stamp}")
                    if stamp in seen:
                        raise ValueError(f"Timestamp duplikat: {stamp}")
                    seen.add(stamp)
        result["rows"] = len(seen)
        if funding:
            result["funding_times"] = funding_times
            if not funding_times:
                raise ValueError("Arsip funding kosong")
        else:
            result["expected_minutes"] = minutes
            result["missing_open_times_utc_ms"] = sorted(
                set(range(start, end, 60000)) - seen
            )
            result["coverage"] = len(seen) / minutes
    except (OSError, ValueError, IndexError, StopIteration, zipfile.BadZipFile) as exc:
        result["error"] = str(exc)
    return result


def audit_daily_repairs(results):
    gaps_by_day = {}
    for entry in results:
        for stamp in entry.get("missing_open_times_utc_ms", []):
            date = datetime.fromtimestamp(stamp / 1000, UTC)
            task = (entry["series"], date.year, date.month, date.day)
            gaps_by_day.setdefault(task, []).append(stamp)
    repairs = []
    for task, gaps in gaps_by_day.items():
        entry = audit(task)
        entry["recovered_open_times_utc_ms"] = []
        if "error" not in entry:
            unavailable = set(entry["missing_open_times_utc_ms"])
            entry["recovered_open_times_utc_ms"] = [
                stamp for stamp in gaps if stamp not in unavailable
            ]
        repairs.append(entry)
    return repairs


def main():
    tasks = [
        (series, year, month, None)
        for year in range(2022, 2027)
        for month in range(1, 13)
        if (2022, 12) <= (year, month) <= (2026, 10)
        for series in SERIES
    ]
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(audit, tasks))
    repairs = audit_daily_repairs(results)
    funding_gaps = []
    previous = None
    for entry in results:
        for stamp, hours in entry.pop("funding_times", []):
            boundary = round(stamp / 60000) * 60000
            if previous is not None and boundary - previous[0] != hours * 3600000:
                funding_gaps.append(
                    {
                        "previous_utc_ms": previous[1],
                        "next_utc_ms": stamp,
                        "interval_hours": hours,
                    }
                )
            previous = (boundary, stamp)
    manifest = {
        "schema_version": 1,
        "audited_at": datetime.now(UTC).isoformat(),
        "timezone": "UTC",
        "warmup_start": "2022-12-02T00:00:00Z",
        "experiment_start": "2023-01-01T00:00:00Z",
        "end_exclusive": "2026-11-01T00:00:00Z",
        "funding_interval_discrepancies": funding_gaps,
        "contract_metadata": "unverified",
        "archives": results,
        "daily_repairs": repairs,
    }
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    errors = [result for result in results if "error" in result]
    missing = sum(
        len(result.get("missing_open_times_utc_ms", [])) for result in results
    )
    recovered = sum(len(entry["recovered_open_times_utc_ms"]) for entry in repairs)
    print(
        f"{len(results) - len(errors)}/{len(results)} arsip bulanan tervalidasi, "
        f"{missing - recovered} candle masih hilang ({recovered} dipulihkan), "
        f"{len(funding_gaps)} selisih interval funding. Manifest: {ROOT / 'manifest.json'}"
    )
    return bool(errors or missing != recovered or funding_gaps)


if __name__ == "__main__":
    raise SystemExit(main())
