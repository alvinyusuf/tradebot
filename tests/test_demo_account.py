import hashlib
import hmac
from urllib.parse import parse_qsl, urlsplit

import pytest

from tradebot.demo_account import inspect_demo_account
from tradebot.demo_execution import DemoExecution, DemoRequestUncertain

ACCOUNT_PAYLOADS = {
    "/fapi/v1/positionSide/dual": {"dualSidePosition": False},
    "/fapi/v1/symbolConfig": [
        {
            "symbol": "BTCUSDT",
            "marginType": "ISOLATED",
            "isAutoAddMargin": False,
            "leverage": 5,
        }
    ],
    "/fapi/v3/positionRisk": [],
    "/fapi/v1/openOrders": [],
    "/fapi/v1/openAlgoOrders": [],
}


def demo_client(changes=None):
    payloads = ACCOUNT_PAYLOADS | (changes or {})
    observed = []

    def read(request):
        url = urlsplit(request.full_url)
        assert url.scheme == "https" and url.netloc == "demo-fapi.binance.com"
        assert request.get_method() == "GET" and request.data is None
        if url.path == "/fapi/v1/time":
            return {"serverTime": 1723456980000}
        assert request.get_header("X-mbx-apikey") == "demo-account-fixture"
        unsigned, signature = url.query.rsplit("&signature=", 1)
        assert (
            signature
            == hmac.new(
                b"demo-secret-fixture", unsigned.encode(), hashlib.sha256
            ).hexdigest()
        )
        params = dict(parse_qsl(unsigned))
        assert params["timestamp"] == "1723456980000"
        if url.path.endswith("positionSide/dual"):
            assert "symbol" not in params
        else:
            assert params["symbol"] == "BTCUSDT"
        observed.append(url.path)
        return payloads[url.path]

    return DemoExecution(
        "demo-account-fixture", "demo-secret-fixture", read=read
    ), observed


def test_readiness_checks_all_demo_routes_and_never_mutates_account():
    execution, observed = demo_client()
    state = inspect_demo_account(execution)
    assert state.ready and state.violations == ()
    assert observed == list(ACCOUNT_PAYLOADS)


def test_account_violations_are_reported_without_account_identifiers():
    execution, _ = demo_client(
        {
            "/fapi/v1/positionSide/dual": {"dualSidePosition": True},
            "/fapi/v1/symbolConfig": [
                {
                    "symbol": "BTCUSDT",
                    "marginType": "CROSSED",
                    "isAutoAddMargin": True,
                    "leverage": 6,
                }
            ],
            "/fapi/v3/positionRisk": [
                {"symbol": "BTCUSDT", "positionSide": "SHORT", "positionAmt": "-0.001"}
            ],
            "/fapi/v1/openOrders": [{"symbol": "BTCUSDT", "orderId": 91234}],
            "/fapi/v1/openAlgoOrders": [{"symbol": "BTCUSDT", "algoId": 88713}],
        }
    )
    state = inspect_demo_account(execution)
    assert not state.ready
    assert state.violations == (
        "hedge_mode",
        "not_isolated",
        "auto_add_margin",
        "leverage_above_limit",
        "position_present",
        "open_orders_present",
        "open_algo_orders_present",
    )
    assert "91234" not in repr(state) and "88713" not in repr(state)


def test_unconfigured_leverage_is_reported_as_account_violation():
    symbol = ACCOUNT_PAYLOADS["/fapi/v1/symbolConfig"][0]
    execution, _ = demo_client({"/fapi/v1/symbolConfig": [symbol | {"leverage": 0}]})
    assert inspect_demo_account(execution).violations == ("leverage_unconfigured",)


@pytest.mark.parametrize(
    "changes",
    [
        {"/fapi/v1/symbolConfig": []},
        {"/fapi/v3/positionRisk": {}},
        {"/fapi/v1/openAlgoOrders": [{"symbol": "ETHUSDT"}]},
        {
            "/fapi/v3/positionRisk": [
                {"symbol": "BTCUSDT", "positionSide": "BOTH", "positionAmt": "NaN"}
            ]
        },
    ],
)
def test_uncertain_account_state_cannot_pass_readiness(changes):
    execution, _ = demo_client(changes)
    with pytest.raises(DemoRequestUncertain):
        inspect_demo_account(execution)
