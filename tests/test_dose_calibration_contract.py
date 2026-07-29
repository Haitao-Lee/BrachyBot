import json
from pathlib import Path

import pytest

from plans.dose_pre.model_loader import (
    DEFAULT_PRESCRIPTION_GY,
    DOSE_MODEL_SCALE_GY,
    LEGACY_DOSE_MODEL_SCALE_GY,
    dose_gy_to_model,
    dose_model_to_gy,
    planning_dose_value_to_gy,
    planning_dose_value_to_model,
    resolve_dose_scale_gy,
    resolve_prescription_gy,
)


ROOT = Path(__file__).resolve().parents[1]


def test_default_configs_store_physical_gy_thresholds():
    default_params = json.loads(
        (ROOT / "config" / "default_params.json").read_text(encoding="utf-8")
    )
    plan_config = json.loads(
        (ROOT / "plans" / "config.json").read_text(encoding="utf-8")
    )

    for config in (default_params["planning"], plan_config):
        assert config["dose_value_unit"] == "gy"
        assert config["dose_scale_gy"] == pytest.approx(190.8)
        assert config["in_lowest_energy"] == pytest.approx(120.0)
        assert config["out_highest_energy"] == pytest.approx(120.0)
        assert config["in_lowest_dose_gy"] == pytest.approx(120.0)
        assert config["out_highest_dose_gy"] == pytest.approx(120.0)


def test_new_model_calibration_is_independent_from_prescription():
    assert DEFAULT_PRESCRIPTION_GY == pytest.approx(120.0)
    assert DOSE_MODEL_SCALE_GY == pytest.approx(190.8)
    assert dose_model_to_gy(1.0) == pytest.approx(190.8)
    assert dose_gy_to_model(120.0) == pytest.approx(120.0 / 190.8)
    assert planning_dose_value_to_model(120.0, value_unit="gy") == pytest.approx(
        120.0 / 190.8
    )


def test_current_physical_gy_and_legacy_multiplier_plans_resolve_safely():
    current = {
        "dose_value_unit": "gy",
        "in_lowest_energy": 120.0,
        "out_highest_energy": 120.0,
        "dose_scale_gy": 190.8,
    }
    legacy = {
        "in_lowest_energy": 1.0,
        "out_highest_energy": 1.0,
    }

    assert resolve_prescription_gy(current) == pytest.approx(120.0)
    assert planning_dose_value_to_gy(120.0, value_unit="gy") == pytest.approx(120.0)
    assert resolve_dose_scale_gy(current) == pytest.approx(190.8)

    assert resolve_prescription_gy(legacy) == pytest.approx(120.0)
    assert planning_dose_value_to_gy(1.0) == pytest.approx(120.0)
    assert resolve_dose_scale_gy(legacy) == pytest.approx(
        LEGACY_DOSE_MODEL_SCALE_GY
    )


def test_isodose_levels_are_rx_multiples_in_physical_gy():
    multipliers = [1.0, 1.5, 2.0, 4.0]
    levels_gy = [DEFAULT_PRESCRIPTION_GY * value for value in multipliers]
    levels_model = [dose_gy_to_model(value) for value in levels_gy]

    assert levels_gy == pytest.approx([120.0, 180.0, 240.0, 480.0])
    assert levels_model == pytest.approx(
        [120.0 / 190.8, 180.0 / 190.8, 240.0 / 190.8, 480.0 / 190.8]
    )
