from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradebot.features import MARKET_VECTOR_SIZE, iter_decisions
from tradebot.market_data import Candle, DatasetError, Minute
from tradebot.strategies import baseline_action

START = datetime(2023, 1, 1, tzinfo=UTC)


@pytest.fixture
def minutes():
    result = []
    for index in range(60 * 52):
        opening = Decimal(1000 + index)
        candle = Candle(
            START + timedelta(minutes=index),
            opening,
            opening + 3,
            opening - 2,
            opening + 1,
            Decimal(1),
        )
        result.append(Minute(candle, candle))
    return result


def test_decisions_do_not_depend_on_future_minutes(minutes):
    decisions = list(iter_decisions(minutes))
    assert decisions[0].signal_time == START + timedelta(hours=50)
    assert len(decisions[0].values) == MARKET_VECTOR_SIZE
    prefix = minutes[: 60 * 50]
    assert list(iter_decisions(prefix)) == decisions[:1]


def test_features_reject_minute_gap(minutes):
    with pytest.raises(DatasetError, match="not continuous"):
        list(iter_decisions(minutes[:100] + minutes[101:]))


def test_baseline_uses_cross_hour_trend_rsi_and_volume():
    long_setup = {
        "previous_close": 100,
        "previous_ema": 100,
        "close": 105,
        "ema": 102,
        "fast_hour": 103,
        "slow_hour": 100,
        "rsi": 70,
        "volume_ok": True,
    }
    assert baseline_action(**long_setup) == "LONG"
    assert baseline_action(**(long_setup | {"rsi": 70.1})) == "WAIT"
    assert baseline_action(**(long_setup | {"volume_ok": False})) == "WAIT"
    assert baseline_action(
        previous_close=100,
        previous_ema=100,
        close=95,
        ema=98,
        fast_hour=97,
        slow_hour=100,
        rsi=30,
        volume_ok=True,
    ) == "SHORT"
