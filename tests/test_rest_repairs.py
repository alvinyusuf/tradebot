import hashlib
import json
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import pyarrow.parquet as pq
import pytest

from tradebot.market_data import ArchiveDataset, DatasetError

START = datetime(2024, 8, 12, 10, 2, tzinfo=UTC)
END = START + timedelta(minutes=2)
STAMP = int(START.timestamp()) * 1000
CANDLE_HEADER = "open_time,open,high,low,close,volume,close_time\n"


def _archive(root, series, body, missing=()):
    filename = "BTCUSDT-fundingRate-2024-08" if series == "fundingRate" else "BTCUSDT-1m-2024-08"
    folder = "BTCUSDT" if series == "fundingRate" else "BTCUSDT/1m"
    path = root / series / f"{filename}.zip"
    path.parent.mkdir()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{filename}.csv", body)
    return {
        "series": series,
        "month": "2024-08",
        "source": f"https://data.binance.vision/data/futures/um/monthly/{series}/{folder}/{filename}.zip",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "missing_open_times_utc_ms": list(missing),
    }


def _evidence(endpoint, query, rows):
    raw = json.dumps(rows)
    return {
        "source": f"https://fapi.binance.com/fapi/v1/{endpoint}?{urlencode(query)}",
        "attempted_at": "2026-11-21T01:00:00+00:00",
        "fetched_at": "2026-11-21T01:00:01+00:00",
        "response_text": raw,
        "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
    }


def _csv_candle(stamp):
    return f"{stamp},100,105,95,101,0,{stamp + 59999}\n"


@pytest.fixture
def fixture(tmp_path):
    manifest = tmp_path / "manifest.json"
    report = tmp_path / "public-api.json"
    second = STAMP + 60000
    manifest.write_text(json.dumps({
        "timezone": "UTC",
        "schema_version": 1,
        "warmup_start": START.isoformat(),
        "end_exclusive": END.isoformat(),
        "funding_interval_discrepancies": [],
        "archives": [
            _archive(tmp_path, "klines", CANDLE_HEADER + _csv_candle(STAMP) + _csv_candle(second)),
            _archive(tmp_path, "markPriceKlines", CANDLE_HEADER + _csv_candle(second), (STAMP,)),
            _archive(
                tmp_path, "fundingRate",
                f"calc_time,funding_interval_hours,last_funding_rate\n{STAMP + 12},8,0.001\n",
            ),
        ],
        "daily_repairs": [],
    }), encoding="utf-8")
    row = [STAMP, "100", "105", "95", "101", "0", STAMP + 59999, "0", 60, "0", "0", "0"]
    candle_evidence = _evidence("markPriceKlines", {
        "symbol": "BTCUSDT", "interval": "1m", "startTime": STAMP,
        "endTime": STAMP + 59999, "limit": 1,
    }, [row]) | {"data": row}
    end_ms = STAMP + 120000
    funding_evidence = _evidence("fundingRate", {
        "symbol": "BTCUSDT", "startTime": STAMP, "endTime": end_ms - 1, "limit": 1000,
    }, [{"symbol": "BTCUSDT", "fundingTime": STAMP + 7, "fundingRate": "0.001", "markPrice": "99"}])
    payload = {
        "schema_version": 2,
        "archive_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "mark_price_repairs": {str(STAMP): candle_evidence},
        "funding_history": {
            "start_utc_ms": STAMP,
            "end_exclusive_utc_ms": end_ms,
            "pages": [funding_evidence],
        },
    }
    return manifest, report, payload


def test_rest_repairs_fill_verified_gap_and_preserve_exact_funding(fixture):
    manifest, report, payload = fixture
    report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetError, match="unrepaired gap"):
        list(ArchiveDataset(manifest).minutes(START, END))
    archive = ArchiveDataset(manifest, public_api_report=report)
    first, second = archive.minutes(START, END)
    assert first.mark.close == Decimal(101)
    assert first.funding_mark_price == Decimal(99)
    assert first.funding_time == START + timedelta(milliseconds=7)
    assert second.funding_rate is None
    assert archive.funding_timing == "rest_settlement"

    parquet = manifest.with_name("dataset.parquet")
    archive.export_parquet(parquet, START, END)
    metadata = pq.read_metadata(parquet).metadata
    assert metadata[b"source_public_api_report_sha256"].decode() == archive.public_api_report_sha256
    assert metadata[b"funding_timing"] == b"rest_settlement"


def test_tampered_rest_evidence_is_rejected(fixture):
    manifest, report, payload = fixture
    payload["mark_price_repairs"][str(STAMP)]["response_text"] += " "
    report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetError, match="checksum mismatch"):
        ArchiveDataset(manifest, public_api_report=report)


def test_blank_rest_mark_preserves_verified_timestamp(fixture):
    manifest, report, payload = fixture
    page = payload["funding_history"]["pages"][0]
    raw = page["response_text"].replace('"99"', '""')
    page["response_text"] = raw
    page["response_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    report.write_text(json.dumps(payload), encoding="utf-8")
    archive = ArchiveDataset(manifest, public_api_report=report)
    first, _ = archive.minutes(START, END)
    assert first.funding_time_verified
    assert first.funding_time == START + timedelta(milliseconds=7)
    assert first.funding_mark_price is None
    assert archive.missing_rest_funding_marks == 1


def test_rest_evidence_for_different_manifest_is_rejected(fixture):
    manifest, report, payload = fixture
    payload["archive_manifest_sha256"] = "0" * 64
    report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetError, match="does not match audit manifest"):
        ArchiveDataset(manifest, public_api_report=report)


def test_verified_funding_rate_must_agree_with_archive(fixture):
    manifest, report, payload = fixture
    page = payload["funding_history"]["pages"][0]
    raw = page["response_text"].replace("0.001", "0.005")
    page["response_text"] = raw
    page["response_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    report.write_text(json.dumps(payload), encoding="utf-8")
    archive = ArchiveDataset(manifest, public_api_report=report)
    with pytest.raises(DatasetError, match="schedules or rates differ"):
        list(archive.minutes(START, END))


def test_contract_archive_cannot_supply_mark_candles(fixture):
    manifest, report, payload = fixture
    data = json.loads(manifest.read_bytes())
    mark_entry = data["archives"][1]
    mark_entry["source"] = data["archives"][0]["source"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    payload["archive_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    report.write_text(json.dumps(payload), encoding="utf-8")
    archive = ArchiveDataset(manifest, public_api_report=report)
    with pytest.raises(DatasetError, match="Unexpected archive source"):
        list(archive.minutes(START, END))
