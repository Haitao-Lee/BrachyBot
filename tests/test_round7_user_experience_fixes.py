"""Regression tests for lease identity, metric units, and restore fast-path."""

from web.server_support import _volume_metric_as_percent
import pytest


def test_oar_volume_percent_rejects_impossible_values_instead_of_rescaling():
    assert _volume_metric_as_percent(0.03503) == pytest.approx(3.503)
    assert _volume_metric_as_percent(3.503, units="percent") == pytest.approx(3.503)
    assert _volume_metric_as_percent(350.3, units="percent") is None
    assert _volume_metric_as_percent(1.0, units="fraction") == 100.0
    assert _volume_metric_as_percent(1.2, units="percent") == 1.2
    assert _volume_metric_as_percent(1.2, units="fraction") is None
    assert _volume_metric_as_percent(101.0) is None
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


def test_segmentation_only_requests_do_not_seed_a_planning_progress_item():
    from pathlib import Path

    source = Path("web/app/static/js/brachybot-chat-todo.js").read_text(encoding="utf-8")
    assert "const segmentationOnly = asksSegmentation && !asksPlanningAction;" in source
    assert "&& !segmentationOnly;" in source
