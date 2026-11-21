from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from tradebot.acceptance import (
    GATE_B_SEEDS,
    GateStatus,
    RunMetrics,
    evaluate_gate_b,
    evaluate_paper,
)

GOOD = RunMetrics(D("0.02"), D("0.1"), 100, D("1.10"), 0, 0, 0)
BASELINE = replace(GOOD, net_return=D("0.01"))
START = datetime(2026, 1, 1, tzinfo=UTC)


def runs(**changes):
    return dict.fromkeys(GATE_B_SEEDS, replace(GOOD, **changes))


def test_gate_b_passes_aggregate_thresholds_including_equal_risk_limits():
    base, stress = runs(), runs(net_return=D("0.005"))
    base[11] = replace(GOOD, net_return=D("-0.01"), max_drawdown=D("0.15"))
    assert evaluate_gate_b(base, stress, BASELINE).status == GateStatus.PASS


def test_gate_b_fails_if_median_ties_baseline_and_stress_is_nonpositive():
    result = evaluate_gate_b(runs(), runs(net_return=D(0)), GOOD)
    assert result.status == GateStatus.FAIL
    assert "base:median_return_did_not_beat_baseline" in result.reasons
    assert "stress:nonpositive_median_return" in result.reasons


def test_insufficient_gate_b_samples_and_missing_factor_audit_are_inconclusive():
    few = evaluate_gate_b(runs(closed_trades=99), runs(), BASELINE)
    assert few.status == GateStatus.INCONCLUSIVE
    assert "base:11:insufficient_trades" in few.reasons
    no_loss = evaluate_gate_b(runs(profit_factor=None), runs(), BASELINE)
    assert no_loss.status == GateStatus.INCONCLUSIVE
    assert no_loss.reasons == ("base:undefined_profit_factor",)


def test_gate_b_blocks_known_liquidation_even_if_seed_evidence_is_missing():
    stress = {11: replace(GOOD, liquidations=1)}
    report = evaluate_gate_b(runs(software_violations=None), stress, BASELINE)
    assert report.status == GateStatus.FAIL
    assert "stress:11:liquidations" in report.reasons
    assert "stress:22:missing_run" in report.reasons
    assert "base:11:software_violations_unknown" in report.reasons


@pytest.mark.parametrize("days", [30, 90])
def test_paper_gate_accepts_inclusive_day_limits(days):
    assert (
        evaluate_paper(START, START + timedelta(days=days), GOOD, frozen=True).status
        == GateStatus.PASS
    )


def test_paper_gate_does_not_treat_a_nonempty_status_string_as_frozen():
    with pytest.raises(ValueError, match="boolean"):
        evaluate_paper(START, START + timedelta(days=45), GOOD, frozen="false")


def test_paper_gate_requires_both_minima_without_changing_config():
    report = evaluate_paper(
        START, START + timedelta(days=29), replace(GOOD, closed_trades=99), frozen=False
    )
    assert report.status == GateStatus.INCONCLUSIVE
    assert set(report.reasons) == {
        "paper:insufficient_days",
        "paper:insufficient_trades",
        "paper:model_or_config_changed",
    }


def test_paper_gate_rejects_net_zero_and_a_drawdown_above_threshold():
    report = evaluate_paper(
        START,
        START + timedelta(days=45),
        replace(GOOD, net_return=D(0), max_drawdown=D("0.1001")),
        frozen=True,
    )
    assert report.status == GateStatus.FAIL
    assert set(report.reasons) == {
        "paper:nonpositive_net_return",
        "paper:drawdown_exceeds_limit",
    }


def test_paper_gate_rejects_unverified_audit_and_overlong_observation_as_evidence():
    report = evaluate_paper(
        START,
        START + timedelta(days=91),
        replace(GOOD, software_violations=None),
        frozen=True,
    )
    assert report.status == GateStatus.INCONCLUSIVE
    assert set(report.reasons) == {
        "paper:window_exceeds_ninety_days",
        "paper:software_violations_unknown",
    }
