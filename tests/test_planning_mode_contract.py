from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


def test_planning_mode_normalization_rejects_silent_fallthrough():
    from tool_factory.seed_plan.planning_pipeline import normalize_planning_mode

    assert normalize_planning_mode("rl") == "rl"
    assert normalize_planning_mode("normal") == "rule_based"
    assert normalize_planning_mode("rule-based") == "rule_based"

    try:
        normalize_planning_mode("unrelated")
    except ValueError as exc:
        assert "rule_based" in str(exc)
        assert "rl" in str(exc)
    else:  # pragma: no cover - the assertion documents the safety boundary
        raise AssertionError("invalid planning mode was silently accepted")


def test_rule_based_fallback_requires_a_strict_coverage_improvement():
    from tool_factory.seed_plan.planning_pipeline import (
        rule_based_fallback_is_strictly_better,
    )

    assert rule_based_fallback_is_strictly_better(0.394, 0.394) is False
    assert rule_based_fallback_is_strictly_better(0.394, 0.393) is False
    assert rule_based_fallback_is_strictly_better(0.394, 0.39401) is True
    assert rule_based_fallback_is_strictly_better(0.394, float("nan")) is False


def test_full_pipeline_persists_mode_and_parameter_fingerprint_per_run():
    from tool_factory import ToolResult
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool

    class Memory:
        def __init__(self):
            self.values = {}

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def store(self, key, value):
            self.values[key] = value

    class Agent:
        def __init__(self):
            self.memory = Memory()
            self.config = {}

    args = SimpleNamespace(
        seed_info={"radius": 0.4, "length": 4.5, "seed_avr_dose": 50},
        in_lowest_energy=120.0,
        out_highest_energy=120.0,
        DVH_rate=0.9,
        iter_rate=2,
        max_iter=4,
        replan_rate=0.6,
        distance_filtter={"lower_bound": 0.8, "upper_bound": 10.0},
        radiation_array_params={"target_value": 2, "obstacle_value": 3},
        rf_params={"fallback_to_rule_based": True},
        image_normalize=[-1000, 3000, 255],
        dl_params={"device": "cpu"},
    )
    agent = Agent()
    tool = PlanningPipelineTool()
    run_ids = iter(("planning-rl", "planning-rule"))
    reservations = []

    def begin(_agent, *, input_revision, force_new, **_kwargs):
        reservations.append({"input_revision": input_revision, "force_new": force_new})
        return next(run_ids)

    def publish(_agent, result, *, status):
        assert status == "completed"
        return result.metadata["planning_id"]

    with (
        patch("plans.config.setting", return_value=args),
        patch.object(tool, "_load_ct", return_value=object()),
        patch.object(tool, "_load_ctv", return_value=np.zeros((2, 2, 2), dtype=np.uint8)),
        patch.object(tool, "_load_oar", return_value=np.zeros((2, 2, 2), dtype=np.uint8)),
        patch(
            "tool_factory.seed_plan.planning_pipeline._merge_embedded_hard_obstacles",
            return_value=(object(), set()),
        ),
        patch(
            "tool_factory.seed_plan.planning_pipeline._resolve_ref_direc",
            return_value=[0.0, -1.0, 0.0],
        ),
        patch("web.planning_runs.begin_planning_run", side_effect=begin),
        patch("web.planning_runs.publish_planning_run", side_effect=publish),
        patch.object(
            tool,
            "_run_full_pipeline",
            side_effect=lambda *_args, **_kwargs: ToolResult(
                success=True,
                metadata={"total_seeds": 0},
            ),
        ),
    ):
        first = tool._execute(step="full", mode="rl", _agent=agent)
        second = tool._execute(step="full", mode="rule_based", _agent=agent)

    assert first.success is True
    assert second.success is True
    assert [entry["input_revision"]["mode"] for entry in reservations] == ["rl", "rule_based"]
    assert all(entry["force_new"] is True for entry in reservations)
    assert reservations[0]["input_revision"]["planning_fingerprint"] != reservations[1]["input_revision"]["planning_fingerprint"]
    assert first.metadata["requested_mode"] == "rl"
    assert second.metadata["requested_mode"] == "rule_based"
