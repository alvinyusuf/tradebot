"""Evaluate v0.1 promotion thresholds from explicitly supplied run evidence."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from statistics import median

GATE_B_SEEDS = frozenset({11, 22, 33, 44, 55})
MIN_TRADES = 100


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class GateResult:
    status: GateStatus
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunMetrics:
    """Returns and drawdown are fractions; None denotes missing audit evidence."""

    net_return: Decimal
    max_drawdown: Decimal
    closed_trades: int
    profit_factor: Decimal | None
    liquidations: int
    software_violations: int | None
    unexplained_overshoots: int | None

    def __post_init__(self):
        if not self.net_return.is_finite():
            raise ValueError("Net return must be finite")
        if (
            self.max_drawdown is None
            or self.closed_trades is None
            or self.liquidations is None
        ):
            raise ValueError("Missing required risk and sample metrics")
        ratios = (self.max_drawdown, self.profit_factor)
        if any(
            value is not None and (not value.is_finite() or value < 0)
            for value in ratios
        ):
            raise ValueError(
                "Drawdown and profit factor must be finite and nonnegative"
            )
        counts = (
            self.closed_trades,
            self.liquidations,
            self.software_violations,
            self.unexplained_overshoots,
        )
        if any(
            value is not None and (type(value) is not int or value < 0)
            for value in counts
        ):
            raise ValueError("Event counts must be nonnegative integers")


def _audit(metrics: RunMetrics, scope: str, *, count_liquidation: bool):
    failures = []
    unknown = []
    if count_liquidation and metrics.liquidations:
        failures.append(f"{scope}:liquidations")
    for field in ("software_violations", "unexplained_overshoots"):
        value = getattr(metrics, field)
        if value is None:
            unknown.append(f"{scope}:{field}_unknown")
        elif value > 0:
            failures.append(f"{scope}:{field}")
    return failures, unknown


def evaluate_gate_b(
    base: Mapping[int, RunMetrics],
    stress: Mapping[int, RunMetrics],
    baseline: RunMetrics | None,
) -> GateResult:
    """Assess the frozen five-seed comparison against the final-test baseline."""
    failures = []
    unknown = []
    sample_gaps = []
    for label, runs in (("base", base), ("stress", stress)):
        if runs.keys() - GATE_B_SEEDS:
            raise ValueError(f"Unexpected {label} PPO seed")
        for seed in sorted(GATE_B_SEEDS):
            scope = f"{label}:{seed}"
            metrics = runs.get(seed)
            if metrics is None:
                sample_gaps.append(f"{scope}:missing_run")
                continue
            hard, unchecked = _audit(metrics, scope, count_liquidation=True)
            failures.extend(hard)
            unknown.extend(unchecked)
            if label == "base" and metrics.closed_trades < MIN_TRADES:
                sample_gaps.append(f"{scope}:insufficient_trades")
    if baseline is None:
        sample_gaps.append("baseline:missing_run")
    else:
        hard, unchecked = _audit(baseline, "baseline", count_liquidation=False)
        failures.extend(hard)
        unknown.extend(unchecked)
        if baseline.closed_trades < MIN_TRADES:
            sample_gaps.append("baseline:insufficient_trades")
    if sample_gaps:
        status = GateStatus.FAIL if failures else GateStatus.INCONCLUSIVE
        return GateResult(status, tuple(failures + sample_gaps + unknown))

    base_returns = [row.net_return for row in base.values()]
    mid_return = median(base_returns)
    if mid_return <= 0:
        failures.append("base:nonpositive_median_return")
    if sum(value > 0 for value in base_returns) < 4:
        failures.append("base:fewer_than_four_profitable_seeds")
    if mid_return <= baseline.net_return:
        failures.append("base:median_return_did_not_beat_baseline")
    drawdowns = [row.max_drawdown for row in base.values()]
    if median(drawdowns) > Decimal("0.10"):
        failures.append("base:median_drawdown_exceeds_limit")
    if max(drawdowns) > Decimal("0.15"):
        failures.append("base:seed_drawdown_exceeds_limit")
    factors = [row.profit_factor for row in base.values()]
    if any(value is None for value in factors):
        unknown.append("base:undefined_profit_factor")
    elif median(factors) < Decimal("1.10"):
        failures.append("base:median_profit_factor_below_limit")
    if median(row.net_return for row in stress.values()) <= 0:
        failures.append("stress:nonpositive_median_return")
    if failures:
        return GateResult(GateStatus.FAIL, tuple(failures + unknown))
    if unknown:
        return GateResult(GateStatus.INCONCLUSIVE, tuple(unknown))
    return GateResult(GateStatus.PASS)


def evaluate_paper(
    start: datetime, end: datetime, metrics: RunMetrics, *, frozen: bool
) -> GateResult:
    """Assess the paper part of Gate C. Demo evidence is evaluated separately."""
    if type(frozen) is not bool:
        raise ValueError("Frozen model and config evidence must be a boolean")
    if (
        start.utcoffset() != timedelta(0)
        or end.utcoffset() != timedelta(0)
        or end <= start
    ):
        raise ValueError("Paper window requires ordered UTC timestamps")
    failures, unknown = _audit(metrics, "paper", count_liquidation=True)
    if not frozen:
        unknown.append("paper:model_or_config_changed")
    duration = end - start
    if duration > timedelta(days=90):
        unknown.append("paper:window_exceeds_ninety_days")
    if duration < timedelta(days=30):
        unknown.append("paper:insufficient_days")
    if metrics.closed_trades < MIN_TRADES:
        unknown.append("paper:insufficient_trades")
    if failures:
        return GateResult(GateStatus.FAIL, tuple(failures + unknown))
    if unknown:
        return GateResult(GateStatus.INCONCLUSIVE, tuple(unknown))
    if metrics.net_return <= 0:
        failures.append("paper:nonpositive_net_return")
    if metrics.max_drawdown > Decimal("0.10"):
        failures.append("paper:drawdown_exceeds_limit")
    if failures:
        return GateResult(GateStatus.FAIL, tuple(failures))
    return GateResult(GateStatus.PASS)
