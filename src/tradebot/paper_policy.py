"""Load a frozen local PPO policy for paper inference."""

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .features import DecisionFeatures
from .learning import (
    ACTIONS,
    OBSERVATION_SIZE,
    PPO_CHECKPOINT_INTERVAL,
    PPO_MAX_STEPS,
    PPO_SEEDS,
    MarketScaler,
    policy_observation,
)
from .portfolio import Portfolio
from .research import research_range
from .risk import DailyRisk


@dataclass(frozen=True, slots=True)
class FrozenPaperPolicy:
    model: object
    scaler: MarketScaler
    model_id: str

    @classmethod
    def load(cls, directory: Path, *, seed: int, training_sha256: str):
        from stable_baselines3 import PPO

        if seed not in PPO_SEEDS:
            raise ValueError("Seed PPO paper di luar konfigurasi v0.1")
        raw = (directory / "training.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != training_sha256:
            raise ValueError("Checksum manifest training final berbeda")
        artifact = json.loads(raw)
        if (
            artifact["schema_version"] != 1
            or artifact["fold"] is not None
            or len(artifact.get("development_evidence_sha256", ())) != 3
        ):
            raise ValueError("Paper memerlukan artifact PPO final")
        step = artifact["selected_step"]
        if (
            type(step) is not int
            or not 0 < step <= PPO_MAX_STEPS
            or step % PPO_CHECKPOINT_INTERVAL
        ):
            raise ValueError("Step checkpoint PPO tidak valid")
        data = artifact["scaler"]
        scaler = MarketScaler(
            datetime.fromisoformat(data["train_start"]),
            datetime.fromisoformat(data["train_end"]),
            tuple(data["mean"]),
            tuple(data["scale"]),
        )
        if (scaler.train_start, scaler.train_end) != research_range(None, "train"):
            raise ValueError("Scaler tidak cocok dengan periode training final")
        model_data = (directory / f"seed-{seed}-step-{step}.zip").read_bytes()
        model_hash = hashlib.sha256(model_data).hexdigest()
        if model_hash != artifact["models"][str(seed)]:
            raise ValueError("Checksum checkpoint PPO berbeda")
        model = PPO.load(io.BytesIO(model_data), device="cpu")
        if model.observation_space.shape != (OBSERVATION_SIZE,) or getattr(
            model.action_space, "n", None
        ) != len(ACTIONS):
            raise ValueError("Ruang observasi atau aksi checkpoint tidak cocok")
        return cls(model, scaler, f"{training_sha256}:{seed}:{model_hash}")

    def __call__(
        self,
        decision: DecisionFeatures,
        *,
        portfolio: Portfolio,
        daily_risk: DailyRisk | None,
        mark: Decimal,
    ) -> str:
        observation = policy_observation(
            self.scaler, decision, portfolio, daily_risk, mark
        )
        action, _ = self.model.predict(observation, deterministic=True)
        index = action.item()
        if not isinstance(index, int) or not 0 <= index < len(ACTIONS):
            raise ValueError("Aksi PPO paper tidak valid")
        return ACTIONS[index].value
