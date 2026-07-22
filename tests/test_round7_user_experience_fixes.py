"""Regression tests for lease identity, metric units, and restore fast-path."""

from web.server_support import _volume_metric_as_percent
import pytest


def test_oar_volume_percent_normalizes_fraction_percent_and_legacy_double_scale():
    assert _volume_metric_as_percent(0.03503) == pytest.approx(3.503)
    assert _volume_metric_as_percent(3.503, units="percent") == pytest.approx(3.503)
    assert _volume_metric_as_percent(350.3, units="percent") == pytest.approx(3.503)
    assert _volume_metric_as_percent(1.0, units="fraction") == 100.0
    assert _volume_metric_as_percent(1.2, units="percent") == 1.2
    assert _volume_metric_as_percent(float("nan")) is None


def test_automatic_baseline_and_restore_contract_are_explicitly_separate():
    from pathlib import Path

    source = Path("tool_factory/seed_plan/planning_pipeline.py").read_text(encoding="utf-8")
    route = Path("web/routes/planning_routes.py").read_text(encoding="utf-8")
    assert "algorithm_plan_dose_distribution" in source
    assert "algorithm_plan_dose_distribution_gy" in source
    assert "algorithm_plan_dose_metrics" in source
    assert "fast_restore" in route
    assert '"dose_recomputed": False' in route
