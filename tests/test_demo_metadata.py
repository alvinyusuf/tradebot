import hashlib
import hmac
import json
from urllib.parse import urlsplit

from tradebot.demo_metadata import fetch_demo_metadata


def test_demo_requests_are_signed_gets_and_artifact_excludes_keys():
    symbol = {
        "symbol": "BTCUSDT",
        "contractType": "PERPETUAL",
        "marginAsset": "USDT",
        "status": "TRADING",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
            {
                "filterType": "MARKET_LOT_SIZE",
                "stepSize": "0.001",
                "minQty": "0.001",
                "maxQty": "10",
            },
            {"filterType": "MIN_NOTIONAL", "notional": "50"},
        ],
    }
    paths = []

    def read(request):
        target = urlsplit(request.full_url)
        endpoint = target.path.split("/")[-1]
        assert target.netloc == "demo-fapi.binance.com"
        assert request.get_method() == "GET"
        paths.append(endpoint)
        if endpoint == "exchangeInfo":
            assert not request.headers
            return {"symbols": [symbol]}
        if endpoint == "time":
            assert not request.headers
            return {"serverTime": 1723456980000}
        assert request.get_header("X-mbx-apikey") == "demo-key-fixture"
        params, signature = target.query.rsplit("&signature=", 1)
        assert (
            signature
            == hmac.new(
                b"demo-secret-fixture", params.encode(), hashlib.sha256
            ).hexdigest()
        )
        if endpoint == "leverageBracket":
            return {
                "symbol": "BTCUSDT",
                "brackets": [
                    {
                        "notionalFloor": 0,
                        "notionalCap": 10000,
                        "maintMarginRatio": "0.004",
                        "cum": 0,
                        "initialLeverage": 75,
                    }
                ],
            }
        assert endpoint == "commissionRate"
        return {
            "symbol": "BTCUSDT",
            "makerCommissionRate": "0.0002",
            "takerCommissionRate": "0.0005",
        }

    artifact = fetch_demo_metadata("demo-key-fixture", "demo-secret-fixture", read=read)
    assert paths == [
        "exchangeInfo",
        "time",
        "leverageBracket",
        "time",
        "commissionRate",
    ]
    assert artifact["environment"] == "demo"
    assert artifact["order_filters"]["quantity_step"] == "0.001"
    assert "fixture" not in json.dumps(artifact)
