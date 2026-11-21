"""Collect timestamped evidence from the public Binance Futures API."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path("data/audit")
BASE = "https://fapi.binance.com/fapi/v1"
SYMBOL = "BTCUSDT"
FUNDING_PAGE = 1000


def missing_mark_minutes(manifest):
    missing = {
        stamp
        for archive in manifest["archives"]
        if archive["series"] == "markPriceKlines"
        for stamp in archive.get("missing_open_times_utc_ms", [])
    }
    recovered = {
        stamp
        for archive in manifest["daily_repairs"]
        if archive["series"] == "markPriceKlines"
        for stamp in archive["recovered_open_times_utc_ms"]
    }
    return sorted(missing - recovered)


def check_symbol(payload):
    matches = [item for item in payload["symbols"] if item["symbol"] == SYMBOL]
    if len(matches) != 1:
        raise ValueError("BTCUSDT tidak ditemukan secara unik")
    symbol = matches[0]
    if (symbol["contractType"], symbol["marginAsset"], symbol["status"]) != (
        "PERPETUAL", "USDT", "TRADING"
    ):
        raise ValueError("BTCUSDT bukan kontrak perpetual USDT berstatus TRADING")
    filters = {item["filterType"]: item for item in symbol["filters"]}
    for kind, field in (
        ("PRICE_FILTER", "tickSize"),
        ("LOT_SIZE", "stepSize"),
        ("MARKET_LOT_SIZE", "stepSize"),
        ("MIN_NOTIONAL", "notional"),
    ):
        value = Decimal(filters[kind][field])
        if not value.is_finite() or value <= 0:
            raise ValueError(f"Nilai filter {kind}/{field} tidak valid")
    return symbol


def check_candle(rows, stamp):
    if not isinstance(rows, list) or len(rows) != 1 or len(rows[0]) != 12:
        raise ValueError("Respons tidak memuat tepat satu candle dengan skema REST")
    row = rows[0]
    if row[0] != stamp or row[6] != stamp + 59999:
        raise ValueError("Boundary candle berbeda dari timestamp yang diminta")
    opening, high, low, close = map(Decimal, row[1:5])
    if not (
        all(value.is_finite() for value in (opening, high, low, close))
        and 0 < low <= min(opening, close) <= max(opening, close) <= high
    ):
        raise ValueError("OHLC candle tidak valid")
    return row


def collect(url, validator, *, preserve_response=False):
    evidence = {"source": url, "attempted_at": datetime.now(UTC).isoformat()}
    try:
        with urlopen(url, timeout=12) as response:
            raw = response.read()
        evidence["fetched_at"] = datetime.now(UTC).isoformat()
        evidence["response_sha256"] = hashlib.sha256(raw).hexdigest()
        evidence["data"] = validator(json.loads(raw))
        if preserve_response:
            evidence["response_text"] = raw.decode("utf-8")
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        evidence["error"] = str(exc)
    return evidence


def check_funding_page(rows, start, end):
    if not isinstance(rows, list) or len(rows) > FUNDING_PAGE:
        raise ValueError("Skema halaman funding tidak valid")
    previous = start - 1
    for row in rows:
        stamp = row["fundingTime"]
        if row["symbol"] != SYMBOL or type(stamp) is not int or not previous < stamp < end:
            raise ValueError("Funding tidak urut atau berada di luar interval")
        previous = stamp
    return rows


def funding_history(manifest):
    def milliseconds(field):
        return int(datetime.fromisoformat(manifest[field]).timestamp()) * 1000

    start = milliseconds("warmup_start")
    end = milliseconds("end_exclusive")
    cursor = start
    pages = []
    while cursor < end:
        query = urlencode({
            "symbol": SYMBOL, "startTime": cursor, "endTime": end - 1, "limit": FUNDING_PAGE,
        })
        evidence = collect(
            f"{BASE}/fundingRate?{query}",
            lambda rows, cursor=cursor: check_funding_page(rows, cursor, end),
            preserve_response=True,
        )
        rows = evidence.pop("data", [])
        pages.append(evidence)
        if "error" in evidence or len(rows) < FUNDING_PAGE:
            break
        cursor = rows[-1]["fundingTime"] + 1
    return {"start_utc_ms": start, "end_exclusive_utc_ms": end, "pages": pages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-funding", action="store_true")
    args = parser.parse_args()
    manifest_file = ROOT / "manifest.json"
    raw_manifest = manifest_file.read_bytes()
    manifest = json.loads(raw_manifest)
    snapshot = collect(f"{BASE}/exchangeInfo", check_symbol)
    candles = {}
    for stamp in missing_mark_minutes(manifest):
        query = urlencode({
            "symbol": SYMBOL,
            "interval": "1m",
            "startTime": stamp,
            "endTime": stamp + 59999,
            "limit": 1,
        })
        candles[str(stamp)] = collect(
            f"{BASE}/markPriceKlines?{query}",
            lambda rows, stamp=stamp: check_candle(rows, stamp),
            preserve_response=True,
        )
    report = {
        "schema_version": 2,
        "archive_manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "exchange_info": snapshot,
        "mark_price_repairs": candles,
    }
    if args.verify_funding:
        report["funding_history"] = funding_history(manifest)
    output = ROOT / "public-api.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"Snapshot filter: {'error' if 'error' in snapshot else 'valid'}")
    recovered = sum("data" in entry for entry in candles.values())
    funding_error = any(
        "error" in page for page in report.get("funding_history", {}).get("pages", ())
    )
    print(f"Candle REST valid: {recovered}/{len(candles)}. Bukti: {output}")
    return "error" in snapshot or recovered != len(candles) or funding_error


if __name__ == "__main__":
    raise SystemExit(main())
