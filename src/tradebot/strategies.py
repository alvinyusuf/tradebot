"""Frozen v0.1 comparison strategy."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .features import DecisionFeatures


def baseline_action(
    *,
    previous_close: float,
    previous_ema: float,
    close: float,
    ema: float,
    fast_hour: float,
    slow_hour: float,
    rsi: float,
    volume_ok: bool,
) -> str:
    if not volume_ok:
        return "WAIT"
    if fast_hour > slow_hour and previous_close <= previous_ema and close > ema and 50 <= rsi <= 70:
        return "LONG"
    if fast_hour < slow_hour and previous_close >= previous_ema and close < ema and 30 <= rsi <= 50:
        return "SHORT"
    return "WAIT"


class Baseline:
    @staticmethod
    def action(features: "DecisionFeatures") -> str:
        return features.baseline_action
