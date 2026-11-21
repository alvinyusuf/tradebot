"""Wire validated data, contract metadata and the historical simulator."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import tee

from .config import RunConfig


def development_range(fold: int, split: str) -> tuple[datetime, datetime]:
    boundaries = [
        datetime(year, month, 1, tzinfo=UTC)
        for year, month in [
            (2023, 1),
            (2024, 1),
            (2024, 4),
            (2024, 7),
            (2024, 10),
            (2025, 1),
        ]
    ]
    train_end = fold
    ranges = {
        "train": (0, train_end),
        "validation": (train_end, train_end + 1),
        "test": (train_end + 1, train_end + 2),
    }
    start, end = ranges[split]
    return boundaries[start], boundaries[end]


def research_range(fold: int | None, split: str) -> tuple[datetime, datetime]:
    if fold is not None:
        return development_range(fold, split)
    boundaries = [
        datetime(year, month, 1, tzinfo=UTC)
        for year, month in [(2023, 1), (2025, 7), (2026, 1), (2026, 11)]
    ]
    index = {"train": 0, "validation": 1, "test": 2}[split]
    return boundaries[index], boundaries[index + 1]


def load_research_inputs(config: RunConfig):
    from .market_data import ArchiveDataset
    from .risk import MaintenanceBracket, OrderFilters
    from .simulation import SimulationConfig

    if config.dataset.metadata_status == "fixture":
        raise ValueError("Metadata fixture hanya untuk pengujian sintetis")
    if config.dataset.public_api_report is None:
        archive = ArchiveDataset(config.dataset.manifest)
    else:
        archive = ArchiveDataset(
            config.dataset.manifest, public_api_report=config.dataset.public_api_report
        )
    metadata = json.loads(config.dataset.metadata.read_bytes(), parse_float=Decimal)
    if metadata.get("environment") == "demo":
        raise ValueError("Metadata demo hanya untuk verifikasi integrasi demo")
    if (
        metadata["status"] != config.dataset.metadata_status
        or metadata["symbol"] != config.symbol
    ):
        raise ValueError("Metadata tidak cocok dengan konfigurasi")
    if not metadata.get("source") or not metadata.get("fetched_at"):
        raise ValueError("Metadata memerlukan sumber dan waktu pengambilan")
    filters = OrderFilters(
        **{key: Decimal(value) for key, value in metadata["order_filters"].items()}
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
    simulator_config = SimulationConfig(
        initial_equity=config.risk.initial_equity,
        fee_rate=config.execution.fee_rate,
        slippage=config.execution.slippage,
    )
    return archive, filters, brackets, simulator_config


def run_baseline(config: RunConfig, fold: int | None, split: str):
    from .features import iter_decisions
    from .simulation import run_backtest

    if config.strategy_id != "ema-rsi-volume-v0.1":
        raise ValueError("Command backtest memerlukan strategi baseline")
    start, end = research_range(fold, split)
    archive, filters, brackets, simulator_config = load_research_inputs(config)
    warmup = start - timedelta(days=30)
    feature_minutes, simulation_minutes = tee(archive.minutes(warmup, end))
    decisions = iter_decisions(feature_minutes)
    result = run_backtest(
        simulation_minutes,
        decisions,
        filters,
        brackets,
        start=start,
        end=end,
        config=simulator_config,
    )
    return result, start, end
