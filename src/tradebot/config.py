"""Validate versioned, non-secret runtime configuration."""

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class RiskConfig(ConfigModel):
    initial_equity: Decimal = Field(default=Decimal(100), ge=100, le=100)
    risk_fraction: Decimal = Field(
        default=Decimal("0.005"), ge=Decimal("0.005"), le=Decimal("0.005")
    )
    daily_loss_fraction: Decimal = Field(
        default=Decimal("0.05"), ge=Decimal("0.05"), le=Decimal("0.05")
    )
    max_margin_fraction: Decimal = Field(
        default=Decimal("0.25"), ge=Decimal("0.25"), le=Decimal("0.25")
    )
    max_leverage: Literal[5] = 5


class ExecutionConfig(ConfigModel):
    cost_scenario: Literal["base", "stress"] = "base"

    @property
    def fee_rate(self) -> Decimal:
        return Decimal("0.0005")

    @property
    def slippage(self) -> Decimal:
        return Decimal("0.0002" if self.cost_scenario == "base" else "0.0005")


class DatasetConfig(ConfigModel):
    manifest: Path
    metadata: Path
    metadata_status: Literal["historical", "current_rules_approximation", "fixture"]
    public_api_report: Path | None = None


class RunConfig(ConfigModel):
    schema_version: Literal[1] = 1
    mode: Literal["backtest", "train", "evaluate", "paper", "demo", "live"] = "backtest"
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    timeframe: Literal["15m"] = "15m"
    context_timeframe: Literal["1h"] = "1h"
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    dataset: DatasetConfig
    strategy_id: Literal["ema-rsi-volume-v0.1", "ppo-v0.1"] = "ema-rsi-volume-v0.1"
    model_id: str | None = None
    output_dir: Path = Path("runs")

    @model_validator(mode="after")
    def check_research_config(self):
        if (
            self.mode in {"paper", "demo", "live"}
            and self.dataset.metadata_status == "fixture"
        ):
            raise ValueError("Metadata fixture hanya berlaku untuk pengujian lokal")
        if (
            self.strategy_id == "ppo-v0.1"
            and self.mode != "train"
            and not self.model_id
        ):
            raise ValueError("Evaluasi PPO memerlukan model_id")
        return self


def read_config(path: Path, *, expected_mode: str) -> RunConfig:
    config = RunConfig.model_validate_json(path.read_bytes())
    if config.mode != expected_mode:
        raise ValueError(f"Mode config harus {expected_mode}")
    return config
