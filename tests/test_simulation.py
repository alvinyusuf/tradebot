"""Offline regressions for exchange risk and simulator time boundaries."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradebot.features import DecisionFeatures
from tradebot.market_data import Candle, Minute
from tradebot.risk import MaintenanceBracket, OrderFilters
from tradebot.simulation import HistoricalSimulator, SimulationConfig, run_backtest

D = Decimal
FILTERS = OrderFilters(D("0.1"), D("0.001"), D("0.001"), D("1000"), D("1"))
BRACKETS = (MaintenanceBracket(D(0), D("1000000"), D("0.004"), D(0), 5),)
START = datetime(2024, 1, 1, tzinfo=UTC)
CONFIG = SimulationConfig(purge_minutes=0)


def minute(timestamp, *, contract=("100", "100.5", "99.5", "100"),
           mark=("100", "100.5", "99.5", "100"), funding=None):
    return Minute(
        Candle(timestamp, *map(D, contract), D(100)),
        Candle(timestamp, *map(D, mark), D(0)),
        funding,
        timestamp if funding is not None else None,
    )


def signal(timestamp, action="LONG"):
    return DecisionFeatures(timestamp, D("1.0"), True, (), action)


def test_next_open_and_conservative_stop_on_dual_touch_are_deterministic():
    begin = START.replace(minute=14)
    decision_at = begin + timedelta(minutes=1)
    finish = begin + timedelta(minutes=2)
    candles = [
        minute(begin, contract=("98", "100", "97", "99")),
        minute(
            decision_at,
            contract=("100", "104", "97", "102"),
            mark=("100", "104", "97", "102"),
        ),
    ]
    kwargs = {"end": finish, "start": begin, "config": CONFIG}
    result = run_backtest(candles, [signal(decision_at)], FILTERS, BRACKETS, **kwargs)
    assert result == run_backtest(candles, [signal(decision_at)], FILTERS, BRACKETS, **kwargs)
    (trade,) = result.trades
    assert trade.opened_at == decision_at
    assert trade.plan.entry_price == D("100.02")
    assert trade.reason == "stop_loss"
    assert trade.exit_price == trade.plan.stop_price * D("0.9998")
    assert result.ending_equity == result.starting_equity + trade.net_pnl


def test_entry_stop_at_open_precedes_later_liquidation_touch():
    simulator = HistoricalSimulator(FILTERS, BRACKETS, config=CONFIG)
    event = minute(START, mark=("98", "98", "0.01", "97"))
    point = simulator.step(event, signal(START), "LONG")
    result = simulator.finish()
    (trade,) = result.trades
    assert point.exposed
    assert trade.reason == "stop_loss"
    assert trade.closed_at == START
    assert result.liquidations == 0


def test_opening_gap_liquidation_halts_day_and_blocks_next_signal():
    simulator = HistoricalSimulator(FILTERS, BRACKETS, config=CONFIG)
    simulator.step(minute(START), signal(START), "LONG")
    next_minute = START + timedelta(minutes=1)
    simulator.step(
        minute(next_minute, contract=("0.01", "0.02", "0.01", "0.01"),
               mark=("0.01", "0.02", "0.01", "0.01"))
    )
    for offset in range(2, 15):
        simulator.step(minute(START + timedelta(minutes=offset)))
    signal_time = START + timedelta(minutes=15)
    simulator.step(minute(signal_time), signal(signal_time), "LONG")
    result = simulator.finish()
    assert result.liquidations == 1
    assert result.daily_overshoots == 1
    assert result.rejections == {"daily_halt": 1}
    assert len(result.trades) == 1


def test_funding_boundary_charges_carried_position_and_baseline_wait_is_hold():
    candles = [
        minute(START + timedelta(minutes=offset), funding=D("0.001") if offset == 15 else None)
        for offset in range(16)
    ]
    result = run_backtest(
        candles,
        [signal(START), signal(START + timedelta(minutes=15), "WAIT")],
        FILTERS,
        BRACKETS,
        end=START + timedelta(minutes=16),
        config=CONFIG,
    )
    (trade,) = result.trades
    assert trade.funding == -trade.plan.quantity * D(100) * D("0.001")
    assert trade.reason == "end_of_run"
    assert result.invalid_intents == 0
    assert result.equity_curve[-1].equity == result.ending_equity


@pytest.mark.parametrize(("price", "charge_mark"), [(D(101), D(101)), (None, D(100))])
def test_exact_after_open_funding_uses_recorded_or_opening_mark(price, charge_mark):
    simulator = HistoricalSimulator(FILTERS, BRACKETS, config=CONFIG)
    initial = minute(START)
    event = Minute(
        initial.contract,
        initial.mark,
        D("0.001"),
        START + timedelta(milliseconds=7),
        price,
        True,
    )
    simulator.step(event, signal(START), "LONG")
    (trade,) = simulator.finish().trades
    assert trade.funding == -trade.plan.quantity * charge_mark * D("0.001")


def test_missing_minute_or_misaligned_decision_invalidates_interval():
    with pytest.raises(ValueError, match="Gap"):
        run_backtest(
            [minute(START), minute(START + timedelta(minutes=2))],
            [],
            FILTERS,
            BRACKETS,
            end=START + timedelta(minutes=3),
            config=CONFIG,
        )
    simulator = HistoricalSimulator(FILTERS, BRACKETS, config=CONFIG)
    with pytest.raises(ValueError, match="Sinyal"):
        simulator.step(minute(START), signal(START + timedelta(minutes=15)), "LONG")
    assert simulator.last_minute is None


def test_midnight_boundary_depends_on_next_open_and_new_entry_purge_applies():
    begin = START.replace(hour=23, minute=45)
    simulator = HistoricalSimulator(FILTERS, BRACKETS, config=CONFIG)
    first = simulator.step(minute(begin), signal(begin), "LONG", allow_entry=False)
    assert not first.exposed
    for offset in range(1, 15):
        simulator.step(minute(begin + timedelta(minutes=offset)))
    assert simulator.daily_risk.day == begin.date()
    next_open = begin + timedelta(minutes=15)
    simulator.step(minute(next_open), signal(next_open), "LONG")
    assert simulator.daily_risk.day == next_open.date()
    assert simulator.finish().rejections == {"purge": 1}
