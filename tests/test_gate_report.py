import hashlib
import json

import pytest

from tradebot.acceptance import GATE_B_SEEDS, GateStatus
from tradebot.gate_report import evaluate_gate_report, load_gate_report


def metrics(net_return="0.12"):
    return {
        "net_return": net_return,
        "max_drawdown": "0.06",
        "closed_trades": 110,
        "profit_factor": "1.2",
        "liquidations": 0,
        "software_violations": 0,
        "unexplained_overshoots": 0,
    }


def gate_b():
    return {
        "schema_version": 1,
        "gate": "B",
        "base": {str(seed): metrics() for seed in GATE_B_SEEDS},
        "stress": {str(seed): metrics("0.07") for seed in GATE_B_SEEDS},
        "baseline": metrics("0.08"),
        "evidence": {
            "holdout_verified": True,
            "configuration_frozen": True,
            "execution_costs_verified": True,
        },
    }


def test_gate_b_report_binds_hash_and_uses_five_seed_assessment(tmp_path):
    path = tmp_path / "gate-b.json"
    raw = json.dumps(gate_b()).encode()
    path.write_bytes(raw)
    result = load_gate_report(path)
    assert result == {
        "schema_version": 1,
        "gate": "B",
        "status": "pass",
        "reasons": [],
        "input_sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_unverified_holdout_is_inconclusive_and_hard_failure_takes_precedence():
    document = gate_b()
    document["evidence"]["holdout_verified"] = False
    result = evaluate_gate_report(document)
    assert result.status == GateStatus.INCONCLUSIVE
    assert "evidence:holdout_verified" in result.reasons
    document["stress"]["11"]["liquidations"] = 1
    result = evaluate_gate_report(document)
    assert result.status == GateStatus.FAIL
    assert "stress:11:liquidations" in result.reasons


def test_gate_b_requires_explicit_evidence_and_audit_counts():
    document = gate_b()
    del document["evidence"]["configuration_frozen"]
    with pytest.raises(ValueError, match="configuration_frozen"):
        evaluate_gate_report(document)
    document["evidence"]["configuration_frozen"] = True
    del document["base"]["11"]["software_violations"]
    with pytest.raises(ValueError, match="software_violations"):
        evaluate_gate_report(document)


def test_paper_requires_frozen_configuration_and_duration():
    document = {
        "schema_version": 1,
        "gate": "paper",
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-01-31T00:00:00Z",
        "frozen": False,
        "metrics": metrics(),
    }
    assert evaluate_gate_report(document).status == GateStatus.INCONCLUSIVE
    document["frozen"] = True
    assert evaluate_gate_report(document).status == GateStatus.PASS
    document["end"] = "2026-01-30T23:59:00Z"
    assert evaluate_gate_report(document).status == GateStatus.INCONCLUSIVE


def test_malformed_evidence_is_rejected_without_pass(tmp_path):
    path = tmp_path / "gate-b.json"
    path.write_text('{"schema_version": 1, "gate": "B", "gate": "paper"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Kunci JSON berulang"):
        load_gate_report(path)
    document = gate_b()
    document["base"]["11"]["closed_trades"] = True
    with pytest.raises(ValueError, match="Event counts"):
        evaluate_gate_report(document)
