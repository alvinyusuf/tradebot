import hashlib
import json
from decimal import Decimal

import numpy as np
import pytest

from tradebot.features import MARKET_VECTOR_SIZE, DecisionFeatures
from tradebot.portfolio import Portfolio
from tradebot.research import research_range


def test_frozen_policy_checks_hashes_and_infers_deterministically(
    tmp_path, monkeypatch
):
    gym = pytest.importorskip("gymnasium")
    sb3 = pytest.importorskip("stable_baselines3")
    from tradebot.paper_policy import FrozenPaperPolicy

    start, end = research_range(None, "train")
    model = tmp_path / "seed-11-step-50000.zip"
    model.write_bytes(b"fixture")
    artifact = {
        "schema_version": 1,
        "fold": None,
        "development_evidence_sha256": ["a", "b", "c"],
        "selected_step": 50000,
        "scaler": {
            "train_start": start.isoformat(),
            "train_end": end.isoformat(),
            "mean": [1] * MARKET_VECTOR_SIZE,
            "scale": [2] * MARKET_VECTOR_SIZE,
        },
        "models": {"11": hashlib.sha256(model.read_bytes()).hexdigest()},
    }
    raw = json.dumps(artifact).encode()
    (tmp_path / "training.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    class Model:
        observation_space = gym.spaces.Box(
            -np.inf, np.inf, shape=(MARKET_VECTOR_SIZE + 5,), dtype=np.float32
        )
        action_space = gym.spaces.Discrete(5)

        def predict(self, observation, *, deterministic):
            assert deterministic
            assert observation.dtype == np.float32
            assert np.all(observation[:MARKET_VECTOR_SIZE] == 1)
            assert observation[-5:].tolist() == [0, 0, 0, 0, 1]
            return np.array(4), None

    def fake_load(stream, *, device):
        assert device == "cpu" and stream.read() == b"fixture"
        return Model()

    monkeypatch.setattr(sb3.PPO, "load", fake_load)
    policy = FrozenPaperPolicy.load(tmp_path, seed=11, training_sha256=digest)
    decision = DecisionFeatures(end, Decimal(1), False, (3.0,) * MARKET_VECTOR_SIZE)
    assert (
        policy(
            decision,
            portfolio=Portfolio(Decimal(100)),
            daily_risk=None,
            mark=Decimal(100),
        )
        == "CLOSE"
    )
    model.write_bytes(b"altered")
    with pytest.raises(ValueError, match="Checksum checkpoint"):
        FrozenPaperPolicy.load(tmp_path, seed=11, training_sha256=digest)
    with pytest.raises(ValueError, match="Checksum manifest"):
        FrozenPaperPolicy.load(tmp_path, seed=11, training_sha256="different")
