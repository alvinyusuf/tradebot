"""Run a bounded PPO smoke experiment on actual history with Demo rules."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import torch

from tradebot.experiment import _checkpoint_metrics, _evaluate, _prepared_split
from tradebot.learning import MarketScaler, TradeEnvironment, build_ppo
from tradebot.market_data import ArchiveDataset
from tradebot.risk import MaintenanceBracket, OrderFilters
from tradebot.simulation import run_backtest

ROOT = Path("data/audit")
OUTPUT = Path("runs/demo-ppo-exploration-20261121")


def main():
    torch.set_num_threads(2)
    metadata = json.loads((ROOT / "demo-metadata-20261121.json").read_bytes())
    if (
        metadata["environment"] != "demo"
        or metadata["notional_coefficient"] is not None
    ):
        raise ValueError("Snapshot Demo tidak cocok dengan eksperimen eksplorasi")
    filters = OrderFilters(
        **{name: Decimal(value) for name, value in metadata["order_filters"].items()}
    )
    brackets = tuple(
        MaintenanceBracket(
            **{
                key: int(value) if key == "max_leverage" else Decimal(value)
                for key, value in bracket.items()
            }
        )
        for bracket in metadata["maintenance_brackets"]
    )
    archive = ArchiveDataset(
        ROOT / "manifest.json", public_api_report=ROOT / "public-api.json"
    )
    train = (datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 3, 1, tzinfo=UTC))
    validation = (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 8, tzinfo=UTC))
    train_minutes, train_decisions = _prepared_split(archive, *train, training=True)
    val_minutes, val_decisions = _prepared_split(archive, *validation)
    scaler = MarketScaler.fit_train(
        train_decisions, train_start=train[0], train_end=train[1]
    )
    training = TradeEnvironment(
        train_minutes,
        train_decisions,
        filters,
        brackets,
        scaler,
        start=train[0],
        end=train[1],
        training=True,
    )
    evaluation = TradeEnvironment(
        val_minutes,
        val_decisions,
        filters,
        brackets,
        scaler,
        start=validation[0],
        end=validation[1],
        training=False,
    )
    model = build_ppo(training, seed=11)
    model.learn(total_timesteps=2048)
    ppo = _evaluate(model, evaluation)
    baseline = run_backtest(
        val_minutes,
        val_decisions,
        filters,
        brackets,
        start=validation[0],
        end=validation[1],
    )
    OUTPUT.mkdir(parents=True, exist_ok=False)
    model.save(OUTPUT / "exploratory-model.zip")
    report = {
        "scope": "exploratory_demo_rules_approximation",
        "seed": 11,
        "steps": model.num_timesteps,
        "train": [value.isoformat() for value in train],
        "validation": [value.isoformat() for value in validation],
        "manifest_sha256": archive.manifest_sha256,
        "public_api_report_sha256": archive.public_api_report_sha256,
        "metadata_fetched_at": metadata["fetched_at"],
        "ppo": _checkpoint_metrics(ppo) | {"rejections": ppo.rejections},
        "baseline": _checkpoint_metrics(baseline) | {"rejections": baseline.rejections},
    }
    payload = json.dumps(report, indent=2) + "\n"
    (OUTPUT / "summary.json").write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
