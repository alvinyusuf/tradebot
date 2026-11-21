import hashlib
import hmac
from decimal import Decimal
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from tradebot.demo_execution import DemoAPIError, DemoExecution, DemoRequestUncertain
from tradebot.risk import OrderPlan, Side


def test_demo_signs_test_order_and_queries_matching_id():
    requests = []

    def read(request):
        requests.append(request)
        url = urlsplit(request.full_url)
        assert url.scheme == "https" and url.hostname == "demo-fapi.binance.com"
        if url.path == "/fapi/v1/time":
            assert not request.headers
            return {"serverTime": 123456789}
        assert request.get_header("X-mbx-apikey") == "mock-demo"
        signed = request.data.decode() if request.data is not None else url.query
        message, signature = signed.rsplit("&signature=", 1)
        assert (
            signature
            == hmac.new(b"mock-secret", message.encode(), hashlib.sha256).hexdigest()
        )
        params = parse_qs(message)
        assert params["timestamp"] == ["123456789"]
        assert params["symbol"] == ["BTCUSDT"]
        if request.get_method() == "POST":
            assert url.path == "/fapi/v1/order/test"
            assert params["quantity"] == ["0.001"]
            assert params["type"] == ["MARKET"]
            assert params["newClientOrderId"] == ["fixture:1"]
            return {}
        assert url.path == "/fapi/v1/order" and request.get_method() == "GET"
        assert params["origClientOrderId"] == ["fixture:1"]
        return {
            "symbol": "BTCUSDT",
            "clientOrderId": "fixture:1",
            "orderId": 42,
            "side": "BUY",
            "status": "PARTIALLY_FILLED",
            "origQty": "0.001",
            "executedQty": "0.0005",
        }

    demo = DemoExecution("mock-demo", "mock-secret", read=read)
    demo.test_market_order(side="BUY", quantity=Decimal("1e-3"), client_id="fixture:1")
    lookup = demo.query_order("fixture:1")
    assert lookup.executed_quantity == Decimal("0.0005")
    assert len(requests) == 4


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (400, -1021, DemoAPIError),
        (503, -1007, DemoRequestUncertain),
        (408, -1007, DemoRequestUncertain),
        (429, -1003, DemoAPIError),
    ],
)
def test_signed_failures_are_not_retried(status, code, expected):
    methods = []

    def read(request):
        methods.append(request.get_method())
        if len(methods) == 1:
            return {"serverTime": 100}
        body = BytesIO(f'{{"code": {code}, "msg": "sensitive fixture text"}}'.encode())
        raise HTTPError(request.full_url, status, "request failure", {}, body)

    demo = DemoExecution("mock-demo", "mock-secret", read=read)
    with pytest.raises(expected) as caught:
        demo.test_market_order(side="SELL", quantity=Decimal(1), client_id="fixture")
    assert "sensitive fixture text" not in str(caught.value)
    assert methods == ["GET", "POST"]


def test_invalid_time_never_sends_signed_request():
    def read(request):
        assert request.full_url.endswith("/time")
        return {"serverTime": False}

    demo = DemoExecution("mock-demo", "mock-secret", read=read)
    with pytest.raises(DemoRequestUncertain, match="Timestamp"):
        demo.query_order("fixture")


def test_demo_test_order_accepts_zero_valued_response():
    def read(request):
        if request.full_url.endswith("/time"):
            return {"serverTime": 100}
        return {
            "orderId": 0,
            **dict.fromkeys(
                (
                    "symbol",
                    "clientOrderId",
                    "side",
                    "type",
                    "origQty",
                    "executedQty",
                    "status",
                ),
                "",
            ),
        }

    demo = DemoExecution("fixture", "fixture", read=read)
    demo.test_market_order(side="BUY", quantity=Decimal(".001"), client_id="fixture")


def test_market_submission_requires_opt_in_and_reduce_only_exit():
    sent = []

    def read(request):
        url = urlsplit(request.full_url)
        assert url.hostname == "demo-fapi.binance.com"
        if url.path.endswith("/time"):
            return {"serverTime": 100}
        assert request.get_method() == "POST" and url.path == "/fapi/v1/order"
        params = {k: values[0] for k, values in parse_qs(request.data.decode()).items()}
        sent.append(params)
        return {
            "symbol": "BTCUSDT",
            "clientOrderId": params["newClientOrderId"],
            "orderId": len(sent),
            "side": params["side"],
            "status": "FILLED",
            "origQty": params["quantity"],
            "executedQty": params["quantity"],
            "reduceOnly": params["reduceOnly"] == "true",
            "positionSide": "BOTH",
        }

    d = Decimal
    plan = OrderPlan(
        Side.LONG, d(".001"), d(100), d(98), d(104), 2, d(".05"), d(".003"), d(51)
    )
    with pytest.raises(ValueError, match="belum diaktifkan"):
        DemoExecution("fixture", "fixture", read=read).submit_entry(
            plan, client_id="entry"
        )
    assert not sent
    demo = DemoExecution("fixture", "fixture", read=read, enable_execution=True)
    assert demo.submit_entry(plan, client_id="entry").executed_quantity == plan.quantity
    assert (
        demo.close_position(Side.LONG, plan.quantity, client_id="close").status
        == "FILLED"
    )
    assert [(row["side"], row["reduceOnly"]) for row in sent] == [
        ("BUY", "false"),
        ("SELL", "true"),
    ]
