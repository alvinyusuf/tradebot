"""Close-position conditional orders for one-way BTCUSDT on Binance Demo."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .demo_execution import DemoExecution, DemoRequestUncertain, _validate_client_id
from .demo_metadata import SYMBOL
from .risk import Side

ProtectionKind = Literal["STOP_MARKET", "TAKE_PROFIT_MARKET"]
_KINDS = {"STOP_MARKET", "TAKE_PROFIT_MARKET"}
_STATUSES = {
    "NEW",
    "TRIGGERING",
    "TRIGGERED",
    "FINISHED",
    "CANCELED",
    "EXPIRED",
    "REJECTED",
}


@dataclass(frozen=True, slots=True)
class DemoAlgoOrder:
    client_id: str
    algo_id: int
    status: str
    kind: str
    side: str
    trigger_price: Decimal
    actual_order_id: int | None


def _parse_protection(response: dict, client_id: str) -> DemoAlgoOrder:
    try:
        if (
            response["symbol"] != SYMBOL
            or response["clientAlgoId"] != client_id
            or response["algoType"] != "CONDITIONAL"
            or response["positionSide"] != "BOTH"
            or response["workingType"] != "MARK_PRICE"
            or response["closePosition"] is not True
        ):
            raise ValueError("Proteksi berbeda dari model posisi Demo")
        algo_id = response["algoId"]
        status, kind, side = (
            response["algoStatus"],
            response["orderType"],
            response["side"],
        )
        trigger_price = Decimal(response["triggerPrice"])
        raw_order_id = response.get("actualOrderId", "")
        actual_order_id = None if raw_order_id == "" else int(raw_order_id)
        if not (
            type(algo_id) is int
            and algo_id > 0
            and status in _STATUSES
            and kind in _KINDS
            and side in {"BUY", "SELL"}
            and trigger_price.is_finite()
            and trigger_price > 0
            and (actual_order_id is None or actual_order_id > 0)
        ):
            raise ValueError("Nilai respons proteksi tidak konsisten")
    except (ArithmeticError, KeyError, TypeError, ValueError):
        raise DemoRequestUncertain(
            "Respons proteksi Demo tidak dapat direkonsiliasi"
        ) from None
    return DemoAlgoOrder(
        client_id, algo_id, status, kind, side, trigger_price, actual_order_id
    )


class DemoProtection:
    """Send and reconcile standalone close-position protection on Demo."""

    def __init__(self, execution: DemoExecution):
        self._execution = execution

    def place(
        self,
        *,
        position_side: Side,
        kind: ProtectionKind,
        trigger_price: Decimal,
        client_id: str,
    ) -> DemoAlgoOrder:
        if not self._execution._execution_enabled:
            raise ValueError("Eksekusi proteksi Demo belum diaktifkan untuk sesi ini")
        _validate_client_id(client_id)
        if position_side is not Side.LONG and position_side is not Side.SHORT:
            raise ValueError("Sisi posisi Demo tidak valid")
        if kind not in _KINDS or not trigger_price.is_finite() or trigger_price <= 0:
            raise ValueError("Jenis atau harga pemicu proteksi Demo tidak valid")
        side = "SELL" if position_side is Side.LONG else "BUY"
        response = self._execution._signed(
            "algoOrder",
            "POST",
            {
                "algoType": "CONDITIONAL",
                "side": side,
                "positionSide": "BOTH",
                "type": kind,
                "triggerPrice": format(trigger_price, "f"),
                "workingType": "MARK_PRICE",
                "closePosition": "true",
                "clientAlgoId": client_id,
            },
        )
        order = _parse_protection(response, client_id)
        if (order.kind, order.side, order.trigger_price) != (kind, side, trigger_price):
            raise DemoRequestUncertain("Proteksi Demo berbeda dari permintaan")
        return order

    def query(self, client_id: str) -> DemoAlgoOrder:
        _validate_client_id(client_id)
        response = self._execution._signed(
            "algoOrder", "GET", {"clientAlgoId": client_id}, include_symbol=False
        )
        return _parse_protection(response, client_id)

    def cancel(self, client_id: str, *, algo_id: int) -> None:
        if not self._execution._execution_enabled:
            raise ValueError("Eksekusi proteksi Demo belum diaktifkan untuk sesi ini")
        if type(algo_id) is not int or algo_id <= 0:
            raise ValueError("ID proteksi Demo tidak valid")
        current = self.query(client_id)
        if current.algo_id != algo_id:
            raise DemoRequestUncertain("ID proteksi Demo berubah sebelum pembatalan")
        if current.status == "CANCELED":
            return
        if current.status != "NEW":
            raise DemoRequestUncertain("Proteksi Demo tidak aktif untuk dibatalkan")
        response = self._execution._signed(
            "algoOrder", "DELETE", {"clientAlgoId": client_id}, include_symbol=False
        )
        if (
            response.get("clientAlgoId") != client_id
            or type(response.get("algoId")) is not int
            or response["algoId"] != algo_id
            or response.get("code") not in (200, "200")
        ):
            raise DemoRequestUncertain("Pembatalan proteksi Demo belum terkonfirmasi")
