"""Signed, non-matching order checks and order lookup for Binance Futures Demo."""

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .demo_metadata import DEMO_API, SYMBOL, _NoRedirect
from .risk import OrderPlan, Side

_ORDER_ID = re.compile(r"[.A-Za-z0-9_:/-]{1,36}")
_STATES = frozenset(
    {
        "NEW",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELED",
        "REJECTED",
        "EXPIRED",
        "EXPIRED_IN_MATCH",
    }
)


class DemoRequestUncertain(RuntimeError):
    """No definitive result was received. The caller must stop and reconcile."""


class DemoAPIError(RuntimeError):
    def __init__(self, status: int | None, code: int):
        self.status = status
        self.code = code
        super().__init__(
            f"Binance Demo menolak permintaan (HTTP {status}, kode {code})"
        )


@dataclass(frozen=True, slots=True)
class DemoOrder:
    client_id: str
    order_id: int
    status: str
    side: str
    quantity: Decimal
    executed_quantity: Decimal


def _read(request: Request) -> object:
    with build_opener(_NoRedirect()).open(request, timeout=5) as response:
        return json.load(response)


def _error_code(payload: object) -> int | None:
    if isinstance(payload, dict):
        code = payload.get("code")
        if type(code) is int and code < 0:
            return code
    return None


def _payload(
    request: Request, read: Callable[[Request], object], *, expect_list: bool = False
) -> dict | list:
    try:
        response = read(request)
    except HTTPError as exc:
        try:
            with exc:
                code = _error_code(json.load(exc))
        except (OSError, ValueError):
            code = None
        if (
            400 <= exc.code < 500
            and exc.code != 408
            and code is not None
            and code not in {-1000, -1006, -1007}
        ):
            raise DemoAPIError(exc.code, code) from None
        raise DemoRequestUncertain(
            f"Respons Binance Demo belum pasti (HTTP {exc.code})"
        ) from None
    except (OSError, ValueError):
        raise DemoRequestUncertain(
            "Respons Binance Demo tidak tersedia atau tidak valid"
        ) from None
    code = _error_code(response)
    if code in {-1000, -1006, -1007}:
        raise DemoRequestUncertain(
            f"Binance Demo belum mengonfirmasi permintaan (kode {code})"
        )
    if code is not None:
        raise DemoAPIError(None, code)
    if not isinstance(response, list if expect_list else dict):
        raise DemoRequestUncertain("Skema respons Binance Demo tidak valid")
    return response


def _validate_client_id(client_id: str) -> None:
    if not _ORDER_ID.fullmatch(client_id):
        raise ValueError("Client order ID Binance Demo tidak valid")


class DemoExecution:
    """Demo-only request validation and read-only order reconciliation."""

    def __init__(
        self,
        api_key: str,
        secret: str,
        *,
        read: Callable[[Request], object] = _read,
        enable_execution: bool = False,
    ):
        if not api_key or not secret:
            raise ValueError("Kredensial terpisah Binance Demo diperlukan")
        self._api_key = api_key
        self._secret = secret.encode()
        self._read = read
        self._execution_enabled = enable_execution is True

    def _signed(
        self,
        endpoint: str,
        method: str,
        params: dict,
        *,
        include_symbol: bool = True,
        expect_list: bool = False,
        version: int = 1,
    ) -> dict | list:
        if version not in (1, 3):
            raise ValueError("Versi endpoint Binance Demo tidak didukung")
        server_time = _payload(Request(f"{DEMO_API}/time"), self._read).get(
            "serverTime"
        )
        if type(server_time) is not int or server_time <= 0:
            raise DemoRequestUncertain("Timestamp server Binance Demo tidak valid")
        symbol = {"symbol": SYMBOL} if include_symbol else {}
        query = urlencode(
            {**symbol, **params, "recvWindow": 5000, "timestamp": server_time}
        )
        signature = hmac.new(self._secret, query.encode(), hashlib.sha256).hexdigest()
        signed = f"{query}&signature={signature}"
        url = f"{DEMO_API.rsplit('/', 1)[0]}/v{version}/{endpoint}"
        headers = {"X-MBX-APIKEY": self._api_key}
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = Request(url, data=signed.encode(), headers=headers, method=method)
        else:
            request = Request(f"{url}?{signed}", headers=headers, method=method)
        return _payload(request, self._read, expect_list=expect_list)

    def test_market_order(
        self, *, side: str, quantity: Decimal, client_id: str
    ) -> None:
        _validate_client_id(client_id)
        if side not in {"BUY", "SELL"} or not quantity.is_finite() or quantity <= 0:
            raise ValueError("Sisi atau kuantitas test order tidak valid")
        response = self._signed(
            "order/test",
            "POST",
            {
                "side": side,
                "type": "MARKET",
                "quantity": format(quantity, "f"),
                "newClientOrderId": client_id,
            },
        )
        # Demo can return a zero-valued order envelope after validation.
        empty_demo_order = response.get("orderId") == 0 and all(
            response.get(field) == ""
            for field in (
                "symbol",
                "clientOrderId",
                "side",
                "type",
                "origQty",
                "executedQty",
                "status",
            )
        )
        if (
            response
            and not empty_demo_order
            and (response.get("symbol"), response.get("clientOrderId"))
            != (
                SYMBOL,
                client_id,
            )
        ):
            raise DemoRequestUncertain(
                "Respons test order tidak cocok dengan permintaan"
            )

    def query_order(self, client_id: str) -> DemoOrder:
        _validate_client_id(client_id)
        response = self._signed("order", "GET", {"origClientOrderId": client_id})
        return self._parse_order(response, client_id)

    def submit_entry(self, plan: OrderPlan, *, client_id: str) -> DemoOrder:
        """Submit a Demo entry from a risk-approved plan."""
        if not isinstance(plan.side, Side) or not 1 <= plan.leverage <= 5:
            raise ValueError("Rencana entry Demo tidak valid")
        side = "BUY" if plan.side == Side.LONG else "SELL"
        return self._submit_market(side, plan.quantity, client_id, reduce_only=False)

    def close_position(
        self, side: Side, quantity: Decimal, *, client_id: str
    ) -> DemoOrder:
        """Submit a reduce-only Demo exit for a reconciled position quantity."""
        if not isinstance(side, Side):
            raise TypeError("Sisi posisi Demo tidak valid")
        closing_side = "SELL" if side == Side.LONG else "BUY"
        return self._submit_market(closing_side, quantity, client_id, reduce_only=True)

    def _submit_market(
        self, side: str, quantity: Decimal, client_id: str, *, reduce_only: bool
    ) -> DemoOrder:
        if not self._execution_enabled:
            raise ValueError("Eksekusi market Demo belum diaktifkan untuk sesi ini")
        _validate_client_id(client_id)
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("Kuantitas market order Demo tidak valid")
        response = self._signed(
            "order",
            "POST",
            {
                "side": side,
                "type": "MARKET",
                "positionSide": "BOTH",
                "quantity": format(quantity, "f"),
                "reduceOnly": "true" if reduce_only else "false",
                "newClientOrderId": client_id,
                "newOrderRespType": "RESULT",
            },
        )
        order = self._parse_order(response, client_id)
        if (
            order.side != side
            or order.quantity != quantity
            or response.get("reduceOnly") is not reduce_only
            or response.get("positionSide") != "BOTH"
        ):
            raise DemoRequestUncertain(
                "Respons market order Demo berbeda dari permintaan"
            )
        return order

    @staticmethod
    def _parse_order(response: dict, client_id: str) -> DemoOrder:
        try:
            if (response["symbol"], response["clientOrderId"]) != (SYMBOL, client_id):
                raise ValueError("Identitas order berbeda")
            order_id = response["orderId"]
            status, side = response["status"], response["side"]
            quantity, executed = (
                Decimal(response["origQty"]),
                Decimal(response["executedQty"]),
            )
            if not (
                type(order_id) is int
                and order_id > 0
                and status in _STATES
                and side in {"BUY", "SELL"}
                and quantity.is_finite()
                and executed.is_finite()
                and 0 <= executed <= quantity
                and quantity > 0
            ):
                raise ValueError("Nilai order tidak konsisten")
        except (ArithmeticError, KeyError, TypeError, ValueError):
            raise DemoRequestUncertain(
                "Respons query order tidak dapat direkonsiliasi"
            ) from None
        return DemoOrder(client_id, order_id, status, side, quantity, executed)
