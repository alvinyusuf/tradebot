"""Read public filters and signed account metadata from Binance Futures demo."""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEMO_API = "https://demo-fapi.binance.com/fapi/v1"
SYMBOL = "BTCUSDT"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        return None


def _read(request):
    try:
        with build_opener(_NoRedirect()).open(request, timeout=8) as response:
            return json.load(response, parse_float=Decimal)
    except HTTPError as exc:
        raise OSError(f"Binance demo mengembalikan HTTP {exc.code}") from None
    except URLError:
        raise OSError("Koneksi ke Binance demo gagal") from None


def _decimal(value) -> str:
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError("Angka metadata demo tidak terbatas")
    return str(number)


def fetch_demo_metadata(api_key: str, secret: str, *, read=_read) -> dict:
    """Collect allowlisted read-only demo evidence without retaining credentials."""
    if not api_key or not secret:
        raise ValueError("Kredensial demo diperlukan untuk metadata akun demo")
    public = read(Request(f"{DEMO_API}/exchangeInfo"))
    symbols = [item for item in public["symbols"] if item["symbol"] == SYMBOL]
    if len(symbols) != 1:
        raise ValueError("BTCUSDT tidak ditemukan secara unik di demo")
    symbol = symbols[0]
    if (symbol["contractType"], symbol["marginAsset"], symbol["status"]) != (
        "PERPETUAL",
        "USDT",
        "TRADING",
    ):
        raise ValueError("Kontrak demo bukan BTCUSDT perpetual USDT aktif")
    filters = {entry["filterType"]: entry for entry in symbol["filters"]}
    quantity = filters["MARKET_LOT_SIZE"]

    def signed(endpoint):
        server = read(Request(f"{DEMO_API}/time"))
        stamp = server["serverTime"]
        if type(stamp) is not int or stamp <= 0:
            raise ValueError("Timestamp server demo tidak valid")
        query = urlencode({"symbol": SYMBOL, "recvWindow": 5000, "timestamp": stamp})
        signature = hmac.new(
            secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        request = Request(
            f"{DEMO_API}/{endpoint}?{query}&signature={signature}",
            headers={"X-MBX-APIKEY": api_key},
        )
        return read(request)

    brackets = signed("leverageBracket")
    if isinstance(brackets, list):
        matches = [item for item in brackets if item["symbol"] == SYMBOL]
        if len(matches) != 1:
            raise ValueError("Bracket BTCUSDT demo tidak ditemukan secara unik")
        brackets = matches[0]
    commission = signed("commissionRate")
    if brackets["symbol"] != SYMBOL or commission["symbol"] != SYMBOL:
        raise ValueError("Metadata akun demo memakai symbol berbeda")
    if not brackets["brackets"]:
        raise ValueError("Bracket akun demo kosong")

    return {
        "schema_version": 1,
        "environment": "demo",
        "symbol": SYMBOL,
        "fetched_at": datetime.now(UTC).isoformat(),
        "source": DEMO_API,
        "order_filters": {
            "price_tick": _decimal(filters["PRICE_FILTER"]["tickSize"]),
            "quantity_step": _decimal(quantity["stepSize"]),
            "min_quantity": _decimal(quantity["minQty"]),
            "max_quantity": _decimal(quantity["maxQty"]),
            "min_notional": _decimal(filters["MIN_NOTIONAL"]["notional"]),
        },
        "notional_coefficient": _decimal(brackets["notionalCoef"])
        if "notionalCoef" in brackets
        else None,
        "maintenance_brackets": [
            {
                "notional_floor": _decimal(item["notionalFloor"]),
                "notional_cap": _decimal(item["notionalCap"]),
                "maintenance_rate": _decimal(item["maintMarginRatio"]),
                "cumulative_deduction": _decimal(item["cum"]),
                "max_leverage": item["initialLeverage"],
            }
            for item in brackets["brackets"]
        ],
        "commission": {
            "maker": _decimal(commission["makerCommissionRate"]),
            "taker": _decimal(commission["takerCommissionRate"]),
        },
    }
