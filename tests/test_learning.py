import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from tradebot.features import MARKET_VECTOR_SIZE, DecisionFeatures
from tradebot.learning import OBSERVATION_SIZE, MarketScaler, TradeEnvironment
from tradebot.market_data import Candle, Minute
from tradebot.risk import MaintenanceBracket, OrderFilters
from tradebot.simulation import SimulationConfig

D = Decimal
START = datetime(2024, 1, 1, tzinfo=UTC)
END = START + timedelta(minutes=15)
TRAIN = START - timedelta(minutes=30)
FILTERS = OrderFilters(D(".1"), D(".001"), D(".001"), D(100), D(1))
BRACKETS = (MaintenanceBracket(D(0), D(100000), D(".004"), D(0), 125),)


def decision(timestamp, value=0.0):
    return DecisionFeatures(timestamp, D(2), True, (value,) * MARKET_VECTOR_SIZE)


def minutes(start, total):
    rows = []
    for offset in range(total):
        at = start + timedelta(minutes=offset)
        candle = Candle(at, D(100), D(100), D(100), D(100), D(1))
        rows.append(Minute(candle, candle))
    return rows


def fitted_scaler():
    return MarketScaler.fit_train(
        [
            decision(TRAIN, 1.0),
            decision(TRAIN + timedelta(minutes=15), 3.0),
            decision(START, 100.0),
            decision(END, 200.0),
        ],
        train_start=TRAIN,
        train_end=START,
    )


def evaluation(rows):
    return TradeEnvironment(
        rows,
        [decision(START), decision(END)],
        FILTERS,
        BRACKETS,
        fitted_scaler(),
        start=START,
        end=END,
        training=False,
        config=SimulationConfig(purge_minutes=0),
    )


def test_market_scaler_has_an_exclusive_train_end():
    scaler = fitted_scaler()
    assert set(scaler.mean) == {2.0}
    assert set(scaler.scale) == {1.0}


def test_truncation_liquidates_with_costs_and_booked_reward():
    env = evaluation(minutes(START, 15))
    initial, _ = env.reset(seed=11)
    assert initial.shape == (OBSERVATION_SIZE,)
    assert initial.dtype == np.float32
    assert initial[-5:].tolist() == [0, 0, 0, 0, 1]
    obs, reward, terminated, truncated, info = env.step(1)
    assert truncated and not terminated
    assert obs[-5] == 0
    assert len(env.result.trades) == 1
    trade = env.result.trades[0]
    assert trade.reason == "end_of_run" and trade.entry_fee > 0 and trade.exit_fee > 0
    assert math.isclose(reward, math.log(info["equity"] / 100))
    assert reward < 0
    with pytest.raises(RuntimeError, match="Reset"):
        env.step(0)


def test_evaluation_does_not_restart_after_data_gap():
    with pytest.raises(ValueError, match="continuous"):
        evaluation(minutes(START, 15)[:7] + minutes(START, 15)[8:])


def test_nonpositive_equity_is_termination_at_first_failed_minute():
    rows = minutes(START, 15)
    collapse = Candle(
        rows[1].contract.open_time, D(".01"), D(".01"), D(".01"), D(".01"), D(1)
    )
    rows[1] = Minute(collapse, collapse)
    env = TradeEnvironment(
        rows,
        [replace(decision(START), atr=D(".01")), decision(END)],
        FILTERS,
        BRACKETS,
        fitted_scaler(),
        start=START,
        end=END,
        training=False,
        config=SimulationConfig(
            purge_minutes=0, fee_rate=D(0), slippage=D(0), max_funding_settlements=0
        ),
    )
    env.reset(seed=11)
    _, reward, terminated, truncated, _ = env.step(1)
    assert terminated and not truncated and reward == -1
    assert env.result.liquidations == 1
    assert len(env.result.equity_curve) == 2


def test_midnight_observation_renews_daily_budget_without_using_opening_mark():
    midnight = START + timedelta(days=1)
    start = midnight - timedelta(minutes=15)
    end = midnight + timedelta(minutes=15)
    rows = minutes(start, 30)
    stop_gap = replace(rows[1].contract, open=D(92), high=D(92), low=D(92), close=D(92))
    rows[1] = Minute(stop_gap, stop_gap)
    env = TradeEnvironment(
        rows,
        [replace(decision(start), atr=D(".01")), decision(midnight), decision(end)],
        FILTERS,
        BRACKETS,
        fitted_scaler(),
        start=start,
        end=end,
        training=False,
        config=SimulationConfig(
            purge_minutes=0, fee_rate=D(0), slippage=D(0), max_funding_settlements=0
        ),
    )
    env.reset(seed=11)
    observation, _, terminated, truncated, _ = env.step(1)
    assert not terminated and not truncated
    assert env.simulator.daily_risk.day_halted
    assert env.simulator.daily_risk.day == start.date()
    assert env.simulator.last_minute.contract.open_time < midnight
    assert observation[-1] == 1
    env.step(0)
    assert env.simulator.daily_risk.day == midnight.date()
    assert not env.simulator.daily_risk.day_halted


def test_training_reset_random_windows_are_reproducible_and_inside_train():
    end = START + timedelta(days=31)
    decisions = [
        decision(START + timedelta(minutes=15 * offset))
        for offset in range(31 * 96 + 1)
    ]
    scaler = MarketScaler.fit_train(decisions, train_start=START, train_end=end)
    env = TradeEnvironment(
        minutes(START, 31 * 1440),
        decisions,
        FILTERS,
        BRACKETS,
        scaler,
        start=START,
        end=end,
        training=True,
    )
    assert len(env._windows) == 2
    env.reset(seed=11)
    boundary = env._boundary
    env.reset(seed=11)
    assert env._boundary == boundary
    assert env._episode_end - boundary == timedelta(days=30)
