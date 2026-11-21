"""Offline PPO development-fold orchestration."""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from uuid import uuid4

from .config import RunConfig
from .research import load_research_inputs, research_range


def _prepared_split(archive, start, end, *, training=False):
    from .features import iter_decisions

    # One materialization per split allows seeded episodes to seek by timestamp.
    # Warmup candles are consumed by the features and excluded from execution.
    warmup = start - timedelta(days=30)
    if not training:
        rows = tuple(archive.minutes(warmup, end))
        return rows, tuple(iter_decisions(rows))

    excluded = {
        datetime.fromtimestamp(stamp / 1000, UTC)
        for _, stamp in archive.unrepaired_minutes()
    }
    segments = []
    left = warmup
    for missing in sorted(stamp for stamp in excluded if warmup <= stamp < end):
        if left < missing:
            segments.append((left, missing))
        left = missing + timedelta(minutes=1)
    if left < end:
        segments.append((left, end))
    minutes = []
    decisions = []
    for left, right in segments:
        continuous = tuple(archive.minutes(left, right))
        minutes.extend(continuous)
        decisions.extend(iter_decisions(continuous))
    return minutes, decisions


def _evaluate(model, environment):
    observation, _ = environment.reset()
    finished = False
    while not finished:
        action, _ = model.predict(observation, deterministic=True)
        observation, _, terminated, truncated, _ = environment.step(action.item())
        finished = terminated or truncated
    return environment.result


def _checkpoint_metrics(result):
    maximum_drawdown = 0.0
    peak = result.starting_equity
    for point in result.equity_curve:
        peak = max(peak, point.equity)
        maximum_drawdown = max(maximum_drawdown, float((peak - point.equity) / peak))
    return {
        "net_return": float(result.ending_equity / result.starting_equity - 1),
        "max_drawdown": maximum_drawdown,
        "closed_trades": len(result.trades),
    }


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provenance(config: RunConfig):
    from .reporting import implementation_sha256

    evidence = {
        "manifest_sha256": _hash(config.dataset.manifest),
        "metadata_sha256": _hash(config.dataset.metadata),
        "public_api_report_sha256": None,
        "implementation_sha256": implementation_sha256(),
    }
    if config.dataset.public_api_report is not None:
        evidence["public_api_report_sha256"] = _hash(config.dataset.public_api_report)
    return evidence


def _check_development_evidence(
    config: RunConfig, indexes: tuple[Path, ...]
) -> list[str]:
    from .learning import PPO_SEEDS

    provenance = _provenance(config)
    evidence = {}
    for path in indexes:
        raw = path.read_bytes()
        run = json.loads(raw)
        if (
            run["schema_version"] != 1
            or run["provenance"] != provenance
            or run["cost_scenario"] != "base"
            or run["fold"] not in (1, 2, 3)
            or run["fold"] in evidence
        ):
            raise ValueError(
                "Bukti pengembangan tidak cocok dengan data, versi, atau fold"
            )
        if set(run["runs"]) != {str(seed) for seed in PPO_SEEDS}:
            raise ValueError("Bukti pengembangan harus memuat kelima seed")
        start, end = research_range(run["fold"], "test")
        for result in run["runs"].values():
            summary_path = Path(result["directory"]) / "summary.json"
            summary_bytes = summary_path.read_bytes()
            summary = json.loads(summary_bytes)
            if (
                hashlib.sha256(summary_bytes).hexdigest() != result["summary_sha256"]
                or datetime.fromisoformat(summary["start"]) != start
                or datetime.fromisoformat(summary["end_exclusive"]) != end
                or summary["implementation_sha256"]
                != provenance["implementation_sha256"]
            ):
                raise ValueError(
                    "Ringkasan fold pengembangan tidak cocok dengan indeks"
                )
        evidence[run["fold"]] = hashlib.sha256(raw).hexdigest()
    if set(evidence) != {1, 2, 3}:
        raise ValueError(
            "Training final membutuhkan bukti evaluasi base dari tiga fold pengembangan"
        )
    return [evidence[fold] for fold in (1, 2, 3)]


def train_experiment(
    config: RunConfig,
    fold: int | None,
    *,
    development_indexes: tuple[Path, ...] = (),
) -> Path:
    from importlib.metadata import version

    from stable_baselines3.common.callbacks import BaseCallback

    from .learning import (
        PPO_CHECKPOINT_INTERVAL,
        PPO_MAX_STEPS,
        PPO_SEEDS,
        MarketScaler,
        TradeEnvironment,
        build_ppo,
    )

    if config.strategy_id != "ppo-v0.1" or config.execution.cost_scenario != "base":
        raise ValueError("Training membutuhkan strategi PPO dan biaya base v0.1")
    development_hashes = (
        _check_development_evidence(config, development_indexes) if fold is None else []
    )
    archive, filters, brackets, simulator_config = load_research_inputs(config)
    train_start, train_end = research_range(fold, "train")
    validation_start, validation_end = research_range(fold, "validation")
    train_minutes, train_decisions = _prepared_split(
        archive, train_start, train_end, training=True
    )
    validation_minutes, validation_decisions = _prepared_split(
        archive, validation_start, validation_end
    )
    scaler = MarketScaler.fit_train(
        train_decisions, train_start=train_start, train_end=train_end
    )
    training = TradeEnvironment(
        train_minutes,
        train_decisions,
        filters,
        brackets,
        scaler,
        start=train_start,
        end=train_end,
        training=True,
        config=simulator_config,
    )
    validation = TradeEnvironment(
        validation_minutes,
        validation_decisions,
        filters,
        brackets,
        scaler,
        start=validation_start,
        end=validation_end,
        training=False,
        config=simulator_config,
    )
    label = f"fold-{fold}" if fold is not None else "final"
    output = config.output_dir / f"ppo-{label}-{uuid4().hex}"
    output.mkdir(parents=True)
    scores = {}

    class ValidateCheckpoint(BaseCallback):
        def __init__(self, seed):
            super().__init__()
            self.seed = seed

        def _on_step(self):
            if self.num_timesteps % PPO_CHECKPOINT_INTERVAL == 0:
                score = _checkpoint_metrics(_evaluate(self.model, validation))
                scores.setdefault(self.num_timesteps, {})[self.seed] = score
                self.model.save(
                    output / f"seed-{self.seed}-step-{self.num_timesteps}.zip"
                )
            return self.num_timesteps < PPO_MAX_STEPS

    for seed in PPO_SEEDS:
        model = build_ppo(training, seed)
        model.learn(total_timesteps=PPO_MAX_STEPS, callback=ValidateCheckpoint(seed))

    selected = max(
        sorted(scores),
        key=lambda step: (
            median(score["net_return"] for score in scores[step].values()),
            -median(score["max_drawdown"] for score in scores[step].values()),
        ),
    )
    artifact = {
        "schema_version": 1,
        "fold": fold,
        "development_evidence_sha256": development_hashes,
        "provenance": _provenance(config),
        "scaler": asdict(scaler),
        "training_minutes_excluded": (
            (train_end - train_start + timedelta(days=30)) // timedelta(minutes=1)
            - len(train_minutes)
        ),
        "validation": [validation_start, validation_end],
        "selected_step": selected,
        "models": {
            seed: _hash(output / f"seed-{seed}-step-{selected}.zip")
            for seed in PPO_SEEDS
        },
        "checkpoint_scores": scores,
        "config": config.model_dump(mode="json"),
        "versions": {
            name: version(name)
            for name in ("gymnasium", "numpy", "stable-baselines3", "torch")
        },
    }
    (output / "training.json").write_text(
        json.dumps(artifact, default=str, indent=2) + "\n", encoding="utf-8"
    )
    return output


def check_holdout(config: RunConfig, path: Path, expected_sha256: str | None) -> None:
    raw = path.read_bytes()
    if expected_sha256 != hashlib.sha256(raw).hexdigest():
        raise ValueError("Hash artifact training final berbeda dari konfigurasi beku")
    artifact = json.loads(raw)
    if (
        artifact["schema_version"] != 1
        or artifact["fold"] is not None
        or artifact["provenance"] != _provenance(config)
        or len(artifact.get("development_evidence_sha256", ())) != 3
    ):
        raise ValueError(
            "Holdout memerlukan artifact final dengan bukti pengembangan yang cocok"
        )


def evaluate_experiment(
    config: RunConfig, fold: int | None, *, frozen_training_sha256: str | None = None
) -> dict:
    from stable_baselines3 import PPO

    from .learning import PPO_SEEDS, MarketScaler, TradeEnvironment
    from .reporting import write_run

    if config.strategy_id != "ppo-v0.1" or not config.model_id:
        raise ValueError("Evaluasi membutuhkan artifact model PPO")
    directory = Path(config.model_id)
    artifact_bytes = (directory / "training.json").read_bytes()
    training_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    artifact = json.loads(artifact_bytes)
    if artifact["schema_version"] != 1 or artifact["fold"] != fold:
        raise ValueError("Artifact model tidak cocok dengan fold atau versi")
    if artifact["provenance"] != _provenance(config):
        raise ValueError("Manifest dataset atau metadata berbeda dari training")
    if fold is None:
        check_holdout(config, directory / "training.json", frozen_training_sha256)
    train_start, train_end = research_range(fold, "train")
    scaler_data = artifact["scaler"]
    scaler = MarketScaler(
        datetime.fromisoformat(scaler_data["train_start"]),
        datetime.fromisoformat(scaler_data["train_end"]),
        tuple(scaler_data["mean"]),
        tuple(scaler_data["scale"]),
    )
    if (scaler.train_start, scaler.train_end) != (train_start, train_end):
        raise ValueError("Scaler bukan hasil dari split training fold ini")
    step = artifact["selected_step"]
    models = {}
    for seed in PPO_SEEDS:
        path = directory / f"seed-{seed}-step-{step}.zip"
        if _hash(path) != artifact["models"][str(seed)]:
            raise ValueError(f"Checksum model seed {seed} tidak cocok")
        models[seed] = path
    archive, filters, brackets, simulator_config = load_research_inputs(config)
    start, end = research_range(fold, "test")
    minutes, decisions = _prepared_split(archive, start, end)
    environment = TradeEnvironment(
        minutes,
        decisions,
        filters,
        brackets,
        scaler,
        start=start,
        end=end,
        training=False,
        config=simulator_config,
    )
    runs = {}
    for seed, path in models.items():
        model = PPO.load(path, device="cpu")
        result = _evaluate(model, environment)
        output = write_run(
            config,
            result,
            start,
            end,
            model_evidence={
                "seed": seed,
                "training_sha256": training_sha256,
                "model_sha256": artifact["models"][str(seed)],
            },
        )
        runs[seed] = str(output)
    label = f"development-fold-{fold}" if fold is not None else "holdout"
    index = config.output_dir / f"{label}-{uuid4().hex}.json"
    evidence = {
        seed: {"directory": path, "summary_sha256": _hash(Path(path) / "summary.json")}
        for seed, path in runs.items()
    }
    index.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fold": fold,
                "cost_scenario": config.execution.cost_scenario,
                "provenance": artifact["provenance"],
                "training_sha256": training_sha256,
                "runs": evidence,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "runs": runs,
        "development_index": str(index) if fold is not None else None,
        "holdout_index": str(index) if fold is None else None,
    }
