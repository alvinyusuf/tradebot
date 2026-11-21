"""Causal Gymnasium environment and fixed v0.1 PPO configuration."""

from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from math import log
from typing import ClassVar

import gymnasium as gym
import numpy as np

from .features import MARKET_VECTOR_SIZE, DecisionFeatures
from .market_data import ONE_MINUTE, Minute
from .portfolio import Portfolio
from .risk import DAY_LIMIT, DailyRisk, MaintenanceBracket, OrderFilters
from .simulation import Action, HistoricalSimulator, SimulationConfig

DECISION_INTERVAL = timedelta(minutes=15)
TRAIN_EPISODE = timedelta(days=30)
ACTIONS = (Action.WAIT, Action.LONG, Action.SHORT, Action.HOLD, Action.CLOSE)
OBSERVATION_SIZE = MARKET_VECTOR_SIZE + 5
PPO_SEEDS = (11, 22, 33, 44, 55)
PPO_MAX_STEPS = 1_000_000
PPO_CHECKPOINT_INTERVAL = 50_000
DEFAULT_SIMULATION = SimulationConfig()


def _check_boundary(timestamp: datetime):
    if (
        timestamp.utcoffset() != timedelta(0)
        or timestamp.second
        or timestamp.microsecond
        or timestamp.minute % 15
    ):
        raise ValueError("Learning intervals require UTC quarter-hour boundaries")


@dataclass(frozen=True, slots=True)
class MarketScaler:
    """Frozen, serializable per-coordinate statistics learned over one train split."""

    train_start: datetime
    train_end: datetime
    mean: tuple[float, ...]
    scale: tuple[float, ...]

    def __post_init__(self):
        _check_boundary(self.train_start)
        _check_boundary(self.train_end)
        if self.train_start >= self.train_end:
            raise ValueError("Invalid scaler training interval")
        if (
            len(self.mean) != MARKET_VECTOR_SIZE
            or len(self.scale) != MARKET_VECTOR_SIZE
            or not np.isfinite(self.mean).all()
            or not np.isfinite(self.scale).all()
            or min(self.scale) <= 0
        ):
            raise ValueError("Invalid scaler statistics")

    @classmethod
    def fit_train(
        cls,
        decisions: Iterable[DecisionFeatures],
        *,
        train_start: datetime,
        train_end: datetime,
    ):
        observations = [
            row.values
            for row in decisions
            if train_start <= row.signal_time < train_end
        ]
        samples = np.asarray(observations, dtype=np.float64)
        if (
            samples.ndim != 2
            or samples.shape[1] != MARKET_VECTOR_SIZE
            or not np.isfinite(samples).all()
        ):
            raise ValueError(
                "Training split has no compatible finite market observations"
            )
        scale = samples.std(axis=0)
        scale[scale == 0] = 1
        return cls(train_start, train_end, tuple(samples.mean(axis=0)), tuple(scale))

    def transform(self, values: tuple[float, ...]) -> np.ndarray:
        if len(values) != MARKET_VECTOR_SIZE:
            raise ValueError("Incompatible market feature vector")
        return (np.asarray(values, dtype=np.float64) - self.mean) / self.scale


def policy_observation(
    scaler: MarketScaler,
    decision: DecisionFeatures,
    portfolio: Portfolio,
    state: DailyRisk | None,
    mark: Decimal | None,
) -> np.ndarray:
    market = scaler.transform(decision.values)
    position = portfolio.position
    if position is not None and mark is None:
        raise ValueError("An open position requires a completed mark")
    equity = portfolio.equity(mark) if mark is not None else portfolio.balance
    if state is not None and decision.signal_time.date() > state.day:
        state = replace(state)
        state.observe(decision.signal_time, equity, flat=position is None)
    basis = min(state.day_start_equity, equity) if state else equity
    remaining_ratio = 1.0
    if state:
        maximum = DAY_LIMIT * state.day_start_equity
        remaining_ratio = (
            float(state.remaining_budget(equity) / maximum) if maximum > 0 else 0.0
        )
    position_values = (0, 0, 0, 0, remaining_ratio)
    if position is not None and basis > 0:
        position_values = (
            position.plan.side,
            position.unrealized(mark) / basis,
            (decision.signal_time - position.opened_at) / timedelta(hours=4),
            position.plan.initial_margin / basis,
            remaining_ratio,
        )
    observation = np.concatenate(
        (market, np.asarray(position_values, dtype=np.float64))
    ).astype(np.float32)
    if not np.isfinite(observation).all():
        raise ValueError("Policy observation must be finite")
    return observation


class TradeEnvironment(gym.Env):
    """Choose at quarter-hour boundaries and execute the shared minute simulator."""

    metadata: ClassVar = {"render_modes": []}

    def __init__(
        self,
        minutes: Sequence[Minute],
        decisions: Iterable[DecisionFeatures],
        filters: OrderFilters,
        brackets: Sequence[MaintenanceBracket],
        scaler: MarketScaler,
        *,
        start: datetime,
        end: datetime,
        training: bool,
        config: SimulationConfig = DEFAULT_SIMULATION,
    ):
        super().__init__()
        _check_boundary(start)
        _check_boundary(end)
        if start >= end:
            raise ValueError("Learning partition is empty")
        if training and (start, end) != (scaler.train_start, scaler.train_end):
            raise ValueError("Training partition must match the scaler fit interval")
        if not training and start < scaler.train_end:
            raise ValueError(
                "Evaluation partition must start after the scaler fit interval"
            )

        self.minutes = minutes
        self.decisions = {}
        for decision in decisions:
            if not start <= decision.signal_time <= end:
                continue
            _check_boundary(decision.signal_time)
            if decision.signal_time in self.decisions:
                raise ValueError("Duplicate decision timestamp")
            self.decisions[decision.signal_time] = decision
        self.filters = filters
        self.brackets = tuple(brackets)
        self.scaler = scaler
        self.config = config
        self.entry_deadline = end - timedelta(minutes=config.purge_minutes)
        self._windows = self._find_windows(start, end, training)
        self.action_space = gym.spaces.Discrete(len(ACTIONS))
        self.observation_space = gym.spaces.Box(
            low=-np.inf, high=np.inf, shape=(OBSERVATION_SIZE,), dtype=np.float32
        )
        self.simulator = None
        self.result = None

    def _find_windows(self, start, end, training):
        def open_time(row):
            return row.contract.open_time

        first = bisect_left(self.minutes, start, key=open_time)
        last = bisect_left(self.minutes, end, lo=first, key=open_time)
        continuous = []
        block_start = None
        previous = None
        for index in range(first, last):
            minute = self.minutes[index]
            timestamp = open_time(minute)
            if minute.mark.open_time != timestamp or (
                previous is not None and timestamp <= previous
            ):
                raise ValueError("Unsorted or unsynchronized candle series")
            if previous is not None and timestamp != previous + ONE_MINUTE:
                continuous.append((block_start, previous + ONE_MINUTE))
                block_start = None
            if block_start is None:
                block_start = timestamp
            previous = timestamp
        if previous is not None:
            continuous.append((block_start, previous + ONE_MINUTE))

        windows = []
        for block_start, block_end in continuous:
            if training:
                day = block_start.replace(hour=0, minute=0)
                if day < block_start:
                    day += timedelta(days=1)
                while day + TRAIN_EPISODE <= block_end:
                    boundary = day + TRAIN_EPISODE
                    if self._has_decisions(day, boundary):
                        windows.append(
                            (bisect_left(self.minutes, day, key=open_time), boundary)
                        )
                    day += timedelta(days=1)
            elif (block_start, block_end) == (start, end) and self._has_decisions(
                start, end
            ):
                windows.append((first, end))
        if not windows:
            raise ValueError(
                "No complete episode with continuous minutes and warmed features"
            )
        return tuple(windows)

    def _has_decisions(self, start, end):
        steps = (end - start) // DECISION_INTERVAL
        return all(
            start + offset * DECISION_INTERVAL in self.decisions
            for offset in range(steps + 1)
        )

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._index, self._episode_end = self._windows[
            self.np_random.integers(len(self._windows))
        ]
        self._boundary = self.minutes[self._index].contract.open_time
        self._equity = self.config.initial_equity
        self.simulator = HistoricalSimulator(
            self.filters, self.brackets, config=self.config
        )
        self.result = None
        return self._observation(), self._info()

    def _observation(self):
        simulator = self.simulator
        mark = simulator.last_minute.mark.close if simulator.last_minute else None
        return policy_observation(
            self.scaler,
            self.decisions[self._boundary],
            simulator.portfolio,
            simulator.daily_risk,
            mark,
        )

    def _info(self):
        return {
            "equity": float(self._equity),
            "invalid_intents": self.simulator.invalid_intents,
            "liquidations": self.simulator.liquidations,
        }

    def step(self, action):
        if self.simulator is None or self.result is not None:
            raise RuntimeError("Reset environment before stepping")
        if not self.action_space.contains(action):
            raise ValueError("Action outside environment space")
        before = self._equity
        decision = self.decisions[self._boundary]
        next_boundary = self._boundary + DECISION_INTERVAL
        for minute_offset in range(15):
            minute = self.minutes[self._index]
            self._index += 1
            if minute_offset == 0:
                point = self.simulator.step(
                    minute,
                    decision,
                    ACTIONS[int(action)],
                    allow_entry=self._boundary < self.entry_deadline,
                )
            else:
                point = self.simulator.step(minute)
            self._equity = point.equity
            if self._equity <= 0:
                break

        failed = self._equity <= 0
        reached_limit = next_boundary == self._episode_end
        if failed or reached_limit:
            self.result = self.simulator.finish()
            self._equity = self.result.ending_equity
        if not failed:
            self._boundary = next_boundary
        terminated = failed or self._equity <= 0
        truncated = reached_limit and not terminated
        reward = -1.0 if terminated else log(float(self._equity / before))
        return self._observation(), reward, terminated, truncated, self._info()


def build_ppo(environment: TradeEnvironment, seed: int):
    """Construct the frozen config on CPU. Calling this does not train the model."""
    from stable_baselines3 import PPO

    if seed not in PPO_SEEDS:
        raise ValueError("Seed is not part of the fixed v0.1 PPO experiment")
    return PPO(
        "MlpPolicy",
        environment,
        learning_rate=0.0003,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.0,
        policy_kwargs={"net_arch": [64, 64]},
        device="cpu",
        seed=seed,
    )
