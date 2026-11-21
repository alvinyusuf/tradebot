"""Assess a local Gate B or paper evidence document."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .acceptance import (
    GATE_B_SEEDS,
    GateResult,
    GateStatus,
    RunMetrics,
    evaluate_gate_b,
    evaluate_paper,
)

GATE_B_EVIDENCE = (
    "holdout_verified",
    "configuration_frozen",
    "execution_costs_verified",
)


def _object(value, field):
    if not isinstance(value, dict):
        raise TypeError(f"{field} harus berupa objek JSON")
    return value


def _required(document, field):
    if field not in document:
        raise ValueError(f"Input bukti memerlukan {field}")
    return document[field]


def _flag(document, field):
    value = _required(document, field)
    if type(value) is not bool:
        raise ValueError(f"{field} harus berupa boolean JSON")
    return value


def _number(document, field, *, allow_none=False):
    value = _required(document, field)
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise TypeError(f"{field} harus berupa angka desimal")
    try:
        return Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Nilai {field} tidak valid") from exc


def _metrics(payload):
    metrics = _object(payload, "RunMetrics")
    return RunMetrics(
        net_return=_number(metrics, "net_return"),
        max_drawdown=_number(metrics, "max_drawdown"),
        closed_trades=_required(metrics, "closed_trades"),
        profit_factor=_number(metrics, "profit_factor", allow_none=True),
        liquidations=_required(metrics, "liquidations"),
        software_violations=_required(metrics, "software_violations"),
        unexplained_overshoots=_required(metrics, "unexplained_overshoots"),
    )


def _seed_metrics(document, field):
    data = _object(_required(document, field), field)
    expected = {str(seed) for seed in GATE_B_SEEDS}
    if data.keys() - expected:
        raise ValueError(f"{field} memuat seed PPO di luar v0.1")
    return {int(seed): _metrics(value) for seed, value in data.items()}


def _timestamp(document, field):
    value = _required(document, field)
    if not isinstance(value, str):
        raise TypeError(f"{field} harus berupa timestamp ISO 8601 UTC")
    return datetime.fromisoformat(value)


def _evaluate_b(document):
    evidence = _object(_required(document, "evidence"), "evidence")
    unknown = tuple(
        f"evidence:{flag}" for flag in GATE_B_EVIDENCE if not _flag(evidence, flag)
    )
    baseline = _required(document, "baseline")
    result = evaluate_gate_b(
        _seed_metrics(document, "base"),
        _seed_metrics(document, "stress"),
        _metrics(baseline) if baseline is not None else None,
    )
    if not unknown:
        return result
    status = GateStatus.FAIL if result.status == GateStatus.FAIL else GateStatus.INCONCLUSIVE
    return GateResult(status, result.reasons + unknown)


def evaluate_gate_report(document) -> GateResult:
    document = _object(document, "Dokumen bukti")
    version = _required(document, "schema_version")
    if type(version) is not int or version != 1:
        raise ValueError("Versi skema bukti kelulusan tidak didukung")
    gate = _required(document, "gate")
    if gate == "B":
        return _evaluate_b(document)
    if gate == "paper":
        return evaluate_paper(
            _timestamp(document, "start"),
            _timestamp(document, "end"),
            _metrics(_required(document, "metrics")),
            frozen=_flag(document, "frozen"),
        )
    raise ValueError("Gate harus berisi B atau paper")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Kunci JSON berulang: {key}")
        result[key] = value
    return result


def load_gate_report(path: Path | str) -> dict:
    """Read a local evidence file and return the assessment and source digest."""
    raw = Path(path).read_bytes()
    document = json.loads(raw, parse_float=Decimal, object_pairs_hook=_unique_object)
    result = evaluate_gate_report(document)
    return {
        "schema_version": 1,
        "gate": document["gate"],
        "status": result.status.value,
        "reasons": list(result.reasons),
        "input_sha256": hashlib.sha256(raw).hexdigest(),
    }
