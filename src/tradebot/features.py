"""Streaming features computed at completed UTC candle boundaries."""

import math
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .market_data import ONE_MINUTE, Candle, DatasetError, Minute
from .strategies import baseline_action

OBSERVATION_CANDLES = 32
MARKET_FEATURE_NAMES = (
    "log_return",
    "close_ema_atr",
    "rsi",
    "atr_close",
    "volume_ratio",
)
MARKET_VECTOR_SIZE = OBSERVATION_CANDLES * len(MARKET_FEATURE_NAMES) + 1


@dataclass(frozen=True, slots=True)
class DecisionFeatures:
    signal_time: datetime
    atr: Decimal
    volume_ok: bool
    values: tuple[float, ...]
    baseline_action: str = "WAIT"


class _Average:
    def __init__(self, period: int, alpha: float):
        self.period = period
        self.alpha = alpha
        self.value = None
        self.seed = []

    def update(self, sample: float) -> float | None:
        if self.value is None:
            self.seed.append(sample)
            if len(self.seed) == self.period:
                self.value = math.fsum(self.seed) / self.period
                self.seed.clear()
        else:
            self.value += self.alpha * (sample - self.value)
        return self.value


class _Bars:
    def __init__(self, size: int):
        self.size = size
        self.rows = []

    def update(self, candle: Candle, available: datetime) -> Candle | None:
        if not self.rows and candle.open_time.minute % self.size:
            return None
        self.rows.append(candle)
        if available.minute % self.size:
            return None
        rows, self.rows = self.rows, []
        if len(rows) != self.size:
            raise DatasetError(f"Incomplete {self.size}m candle at {available.isoformat()}")
        return Candle(
            rows[0].open_time,
            rows[0].open,
            max(row.high for row in rows),
            min(row.low for row in rows),
            rows[-1].close,
            sum((row.volume for row in rows), Decimal(0)),
        )


class _Study:
    def __init__(self, *, hourly: bool):
        self.ema = _Average(20, 2 / 21)
        self.slow = _Average(50, 2 / 51) if hourly else None
        self.atr = _Average(14, 1 / 14)
        self.gain = _Average(14, 1 / 14)
        self.loss = _Average(14, 1 / 14)
        self.previous_close = None

    def update(self, bar: Candle) -> tuple:
        close, low, high = map(float, (bar.close, bar.low, bar.high))
        previous_close, self.previous_close = self.previous_close, close
        previous_ema = self.ema.value
        ema = self.ema.update(close)
        slow = self.slow.update(close) if self.slow is not None else None
        true_range = high - low
        if previous_close is not None:
            true_range = max(true_range, abs(high - previous_close), abs(low - previous_close))
        atr = self.atr.update(true_range)
        rsi = None
        if previous_close is not None:
            change = close - previous_close
            gain = self.gain.update(max(change, 0))
            loss = self.loss.update(max(-change, 0))
            if gain is not None and loss is not None:
                rsi = 50.0 if gain + loss == 0 else 100 * gain / (gain + loss)
        return previous_close, previous_ema, ema, slow, atr, rsi


class DecisionStream:
    """Incrementally update exactly the same closed-bar features used in research."""

    def __init__(self):
        self._quarter, self._hour = _Bars(15), _Bars(60)
        self._quarter_study, self._hour_study = _Study(hourly=False), _Study(hourly=True)
        self._prior_volumes = deque(maxlen=20)
        self._history = deque(maxlen=OBSERVATION_CANDLES)
        self._hour_context = None
        self.cursor: datetime | None = None

    def update(self, minute: Minute) -> DecisionFeatures | None:
        bar = minute.contract
        if (
            bar.open_time.utcoffset() != timedelta(0)
            or bar.open_time.second
            or bar.open_time.microsecond
            or (self.cursor is not None and bar.open_time != self.cursor)
            or minute.mark.open_time != bar.open_time
        ):
            raise DatasetError(f"Feature input is not continuous UTC at {bar.open_time.isoformat()}")
        available = bar.open_time.astimezone(UTC) + ONE_MINUTE
        self.cursor = available
        completed_hour = self._hour.update(bar, available)
        if completed_hour is not None:
            _, _, fast, slow, hour_atr, _ = self._hour_study.update(completed_hour)
            self._hour_context = (
                (fast, slow, (fast - slow) / hour_atr)
                if fast is not None and slow is not None and hour_atr
                else None
            )
        completed_quarter = self._quarter.update(bar, available)
        if completed_quarter is None:
            return None
        previous_close, previous_ema, ema, _, atr, rsi = self._quarter_study.update(completed_quarter)
        volume = completed_quarter.volume
        average_volume = None
        if len(self._prior_volumes) == 20:
            average_volume = sum(self._prior_volumes, Decimal(0)) / 20
        self._prior_volumes.append(volume)
        if not atr or not average_volume or previous_close is None or ema is None or rsi is None:
            self._history.clear()
            return None
        close = float(completed_quarter.close)
        self._history.append((
            math.log(close / previous_close),
            (close - ema) / atr,
            rsi / 100,
            atr / close,
            float(volume / average_volume),
        ))
        if len(self._history) < OBSERVATION_CANDLES or self._hour_context is None or previous_ema is None:
            return None
        fast, slow, hour_value = self._hour_context
        volume_ok = volume >= average_volume
        action = baseline_action(
            previous_close=previous_close,
            previous_ema=previous_ema,
            close=close,
            ema=ema,
            fast_hour=fast,
            slow_hour=slow,
            rsi=rsi,
            volume_ok=volume_ok,
        )
        values = tuple(value for row in self._history for value in row) + (hour_value,)
        return DecisionFeatures(available, Decimal(str(atr)), volume_ok, values, action)


def iter_decisions(minutes: Iterable[Minute]) -> Iterator[DecisionFeatures]:
    """Yield decision vectors only when 32 complete observations are available."""
    stream = DecisionStream()
    for minute in minutes:
        decision = stream.update(minute)
        if decision is not None:
            yield decision
