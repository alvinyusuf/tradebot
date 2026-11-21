from datetime import UTC, datetime

import pytest

from tradebot.config import RunConfig, read_config
from tradebot.research import development_range


def test_mode_and_unknown_fields_are_rejected(tmp_path):
    payload = {
        "dataset": {
            "manifest": "manifest.json",
            "metadata": "rules.json",
            "metadata_status": "historical",
        }
    }
    config = RunConfig.model_validate(payload)
    path = tmp_path / "config.json"
    path.write_text(config.model_dump_json(), encoding="utf-8")
    assert read_config(path, expected_mode="backtest") == config
    with pytest.raises(ValueError, match="Mode config"):
        read_config(path, expected_mode="live")
    with pytest.raises(ValueError, match="Extra inputs"):
        RunConfig.model_validate({**payload, "api_key": "fixture"})
    with pytest.raises(ValueError):
        RunConfig.model_validate({**payload, "risk": {"max_leverage": 6}})


def test_development_ranges_use_exclusive_quarter_boundary():
    assert development_range(1, "train") == (
        datetime(2023, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 1, tzinfo=UTC),
    )
    assert development_range(2, "test") == (
        datetime(2024, 7, 1, tzinfo=UTC),
        datetime(2024, 10, 1, tzinfo=UTC),
    )
    assert development_range(3, "test") == (
        datetime(2024, 10, 1, tzinfo=UTC),
        datetime(2025, 1, 1, tzinfo=UTC),
    )
