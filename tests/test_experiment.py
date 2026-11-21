import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tradebot import experiment
from tradebot.config import RunConfig
from tradebot.features import MARKET_VECTOR_SIZE, DecisionFeatures
from tradebot.market_data import Candle, Minute
from tradebot.risk import MaintenanceBracket, OrderFilters
from tradebot.simulation import SimulationConfig


def test_training_excludes_known_gap_while_evaluation_refuses_it():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    warmup = start - timedelta(days=30)
    gap = start + timedelta(minutes=1)
    end = start + timedelta(minutes=4)
    calls = []

    class Archive:
        def unrepaired_minutes(self):
            return (("markPriceKlines", int(gap.timestamp()) * 1000),)

        def minutes(self, start_at, end_at):
            calls.append((start_at, end_at))
            if start_at <= gap < end_at:
                raise ValueError("gap within interval")
            return ()

    experiment._prepared_split(Archive(), start, end, training=True)
    assert calls == [(warmup, gap), (gap + timedelta(minutes=1), end)]
    with pytest.raises(ValueError, match="gap within interval"):
        experiment._prepared_split(Archive(), start, end)


def test_holdout_requires_exact_frozen_manifest(tmp_path):
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")
    config = RunConfig.model_validate(
        {
            "dataset": {
                "manifest": source,
                "metadata": source,
                "metadata_status": "historical",
            },
        }
    )
    artifact = {
        "schema_version": 1,
        "fold": None,
        "provenance": experiment._provenance(config),
        "development_evidence_sha256": ["1", "2", "3"],
    }
    path = tmp_path / "training.json"
    raw = json.dumps(artifact).encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    experiment.check_holdout(config, path, digest)
    with pytest.raises(ValueError, match="Hash"):
        experiment.check_holdout(config, path, None)
    path.write_bytes(raw + b"\n")
    with pytest.raises(ValueError, match="Hash"):
        experiment.check_holdout(config, path, digest)


def test_cpu_ppo_checkpoint_and_reload(monkeypatch, tmp_path):
    torch = pytest.importorskip("torch")
    sb3 = pytest.importorskip("stable_baselines3")
    from tradebot import learning

    start = datetime(2024, 1, 1, tzinfo=UTC)
    train_end = start + timedelta(days=30)
    validation_end = train_end + timedelta(minutes=30)
    test_end = validation_end + timedelta(minutes=30)
    ranges = {
        "train": (start, train_end),
        "validation": (train_end, validation_end),
        "test": (validation_end, test_end),
    }

    def prepared_split(_archive, first, last, *, training=False):
        length = (last - first) // timedelta(minutes=1)
        minutes = []
        for offset in range(length):
            at = first + timedelta(minutes=offset)
            candle = Candle(
                at, Decimal(100), Decimal(101), Decimal(99), Decimal(100), Decimal(1)
            )
            minutes.append(Minute(candle, candle))
        decisions = [
            DecisionFeatures(
                first + timedelta(minutes=offset),
                Decimal(2),
                True,
                (0.0,) * MARKET_VECTOR_SIZE,
            )
            for offset in range(0, length + 1, 15)
        ]
        return minutes, decisions

    metadata = tmp_path / "fixture.json"
    metadata.write_text("{}", encoding="utf-8")
    config = RunConfig.model_validate(
        {
            "mode": "train",
            "strategy_id": "ppo-v0.1",
            "output_dir": tmp_path,
            "dataset": {
                "manifest": metadata,
                "metadata": metadata,
                "metadata_status": "fixture",
            },
        }
    )
    filters = OrderFilters(
        Decimal(".1"), Decimal(".001"), Decimal(".001"), Decimal(100), Decimal(1)
    )
    brackets = (
        MaintenanceBracket(
            Decimal(0), Decimal(100000), Decimal(".004"), Decimal(0), 125
        ),
    )
    monkeypatch.setattr(
        experiment, "research_range", lambda _fold, split: ranges[split]
    )
    monkeypatch.setattr(experiment, "_prepared_split", prepared_split)
    monkeypatch.setattr(
        experiment,
        "load_research_inputs",
        lambda _config: (
            None,
            filters,
            brackets,
            SimulationConfig(purge_minutes=0),
        ),
    )
    monkeypatch.setattr(learning, "PPO_SEEDS", (11,))
    monkeypatch.setattr(learning, "PPO_CHECKPOINT_INTERVAL", 4)
    monkeypatch.setattr(learning, "PPO_MAX_STEPS", 8)
    monkeypatch.setattr(
        learning,
        "build_ppo",
        lambda environment, seed: sb3.PPO(
            "MlpPolicy",
            environment,
            n_steps=4,
            batch_size=4,
            n_epochs=1,
            seed=seed,
            device="cpu",
        ),
    )
    thread_count = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        artifact = experiment.train_experiment(config, 1)
        manifest = json.loads((artifact / "training.json").read_bytes())
        assert set(manifest["checkpoint_scores"]) == {"4", "8"}
        assert manifest["selected_step"] in {4, 8}
        evaluation = config.model_copy(
            update={"mode": "evaluate", "model_id": str(artifact)}
        )
        results = experiment.evaluate_experiment(evaluation, 1)
        assert (Path(results["runs"][11]) / "summary.json").is_file()
        assert Path(results["development_index"]).is_file()
    finally:
        torch.set_num_threads(thread_count)
