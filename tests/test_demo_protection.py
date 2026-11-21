import hashlib
import hmac
from decimal import Decimal
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from tradebot.demo_execution import DemoExecution, DemoRequestUncertain
from tradebot.demo_protection import DemoProtection
from tradebot.risk import Side


def _protection_response(*, kind="STOP_MARKET", side="SELL", **fields):
    return {
        "symbol": "BTCUSDT",
        "clientAlgoId": "protection-1",
        "algoId": 17,
        "algoType": "CONDITIONAL",
        "algoStatus": "NEW",
        "orderType": kind,
        "side": side,
        "positionSide": "BOTH",
        "workingType": "MARK_PRICE",
        "closePosition": True,
        "triggerPrice": "60000.10",
    } | fields


class _Fixture:
    def __init__(self, *responses, enable_execution=True):
        self.responses = iter(responses)
        self.calls = []
        self.adapter = DemoProtection(
            DemoExecution(
                "demo-fixture",
                "demo-secret",
                read=self.read,
                enable_execution=enable_execution,
            )
        )

    def read(self, request):
        url = urlsplit(request.full_url)
        assert url.hostname == "demo-fapi.binance.com"
        if url.path == "/fapi/v1/time":
            assert not request.has_header("X-mbx-apikey")
            return {"serverTime": 1770736694138}
        assert url.path == "/fapi/v1/algoOrder"
        assert request.get_header("X-mbx-apikey") == "demo-fixture"
        signed_query = request.data.decode() if request.data else url.query
        query, _, signature = signed_query.rpartition("&signature=")
        assert (
            signature
            == hmac.new(b"demo-secret", query.encode(), hashlib.sha256).hexdigest()
        )
        args = {key: value[0] for key, value in parse_qs(query).items()}
        self.calls.append((request.method, args))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.parametrize(
    ("position_side", "kind", "exchange_side"),
    [
        (Side.LONG, "STOP_MARKET", "SELL"),
        (Side.SHORT, "TAKE_PROFIT_MARKET", "BUY"),
    ],
)
def test_place_uses_demo_close_all_and_never_quantity(
    position_side, kind, exchange_side
):
    fixture = _Fixture(_protection_response(kind=kind, side=exchange_side))
    order = fixture.adapter.place(
        position_side=position_side,
        kind=kind,
        trigger_price=Decimal("60000.10"),
        client_id="protection-1",
    )
    assert order.status == "NEW"
    assert order.trigger_price == Decimal("60000.10")
    assert fixture.calls == [
        (
            "POST",
            {
                "symbol": "BTCUSDT",
                "algoType": "CONDITIONAL",
                "side": exchange_side,
                "positionSide": "BOTH",
                "type": kind,
                "triggerPrice": "60000.10",
                "workingType": "MARK_PRICE",
                "closePosition": "true",
                "clientAlgoId": "protection-1",
                "recvWindow": "5000",
                "timestamp": "1770736694138",
            },
        )
    ]


def test_query_returns_triggered_matching_order_identifier():
    fixture = _Fixture(_protection_response(algoStatus="TRIGGERED", actualOrderId="45"))
    order = fixture.adapter.query("protection-1")
    assert order.actual_order_id == 45
    assert fixture.calls == [
        (
            "GET",
            {
                "clientAlgoId": "protection-1",
                "recvWindow": "5000",
                "timestamp": "1770736694138",
            },
        )
    ]


def test_cancel_checks_order_identity_then_requires_matching_ack():
    fixture = _Fixture(
        _protection_response(),
        {"algoId": 17, "clientAlgoId": "protection-1", "code": "200"},
        _protection_response(algoStatus="CANCELED"),
    )
    fixture.adapter.cancel("protection-1", algo_id=17)
    fixture.adapter.cancel("protection-1", algo_id=17)
    assert [method for method, _ in fixture.calls] == ["GET", "DELETE", "GET"]
    assert all("symbol" not in fields for _, fields in fixture.calls)


def test_cancel_does_not_send_for_different_identifier():
    fixture = _Fixture(_protection_response(algoId=19))
    with pytest.raises(DemoRequestUncertain, match="berubah"):
        fixture.adapter.cancel("protection-1", algo_id=17)
    assert [method for method, _ in fixture.calls] == ["GET"]


def test_place_transport_timeout_does_not_retry():
    fixture = _Fixture(URLError("fixture timeout"))
    with pytest.raises(DemoRequestUncertain):
        fixture.adapter.place(
            position_side=Side.LONG,
            kind="STOP_MARKET",
            trigger_price=Decimal("60000.10"),
            client_id="protection-1",
        )
    assert [method for method, _ in fixture.calls] == ["POST"]


def test_wrong_response_is_uncertain():
    fixture = _Fixture(_protection_response(closePosition=False))
    with pytest.raises(DemoRequestUncertain, match="direkonsiliasi"):
        fixture.adapter.query("protection-1")


def test_query_is_available_without_enabling_protection_mutations():
    fixture = _Fixture(_protection_response(), enable_execution=False)
    assert fixture.adapter.query("protection-1").algo_id == 17
    with pytest.raises(ValueError, match="belum diaktifkan"):
        fixture.adapter.place(
            position_side=Side.LONG,
            kind="STOP_MARKET",
            trigger_price=Decimal("60000.10"),
            client_id="protection-1",
        )
    with pytest.raises(ValueError, match="belum diaktifkan"):
        fixture.adapter.cancel("protection-1", algo_id=17)
    assert [method for method, _ in fixture.calls] == ["GET"]
