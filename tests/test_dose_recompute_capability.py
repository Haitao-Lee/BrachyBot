"""Regression tests for the stateful conversational dose refresh capability."""

import threading
from types import SimpleNamespace
from unittest.mock import patch

from agent_runtime.core import ToolResultPipeline
from agent_runtime.llm_runtime import _collect_tool_fallback_text
from agent_runtime.response_tools import ResponseToolMixin
from agent_runtime.turn_policy import classify_local_turn
from tool_factory import ToolResult
from tool_factory.dose_recompute import CurrentPlanDoseRecomputeTool


def test_recompute_request_keeps_the_stateful_capability_available_to_the_llm():
    """A dose refresh is a registered clinical capability, not a keyword reply."""
    policy = classify_local_turn("请重新计算剂量")

    assert policy.intent == "semantic_action"
    assert policy.direct_execution is False
    assert "dose_recompute" in policy.allow_tools


def test_raw_provider_dose_call_without_runtime_payload_is_upgraded_to_stateful_tool():
    """The low-level model contract must not produce an empty conversational turn."""
    calls = ResponseToolMixin()._normalize_tool_params([
        {"tool": "dose_engine", "params": {}},
    ])

    assert calls == [{"tool": "dose_recompute", "params": {}}]


def test_internal_dose_calc_alias_uses_the_same_stateful_capability():
    calls = ResponseToolMixin()._normalize_tool_params([
        {"tool": "dose_calc", "params": {}},
    ])

    assert calls == [{"tool": "dose_recompute", "params": {}}]


def test_dose_recompute_has_a_user_facing_result_without_full_plan_synthesis():
    result = ToolResult(
        success=True,
        metadata={
            "planning_id": "planning_2",
            "planning_label": "Planning_2",
            "total_seeds": 40,
            "num_trajectories": 8,
            "metrics": {
                "v100": 0.9061,
                "v150": 0.7430,
                "v200": 0.5893,
                "d90": 122.75,
            },
            "artifact_status": {
                "dose": "ready",
                "dvh": "ready",
                "report": "stale",
                "surgical_guide": "stale",
            },
        },
    )

    response = ToolResultPipeline.format("dose_recompute", result, "zh")

    assert "当前 Planning 剂量重算" in response
    assert "Planning_2" in response
    assert "90.6%" in response
    assert "Dose / DVH" in response
    assert "报告" in response and "手术导板" in response
    assert "相关检索或处理步骤已结束" not in response


def test_empty_model_response_fallback_keeps_the_recompute_result():
    successes, failures = _collect_tool_fallback_text(
        [{
            "type": "tool",
            "tool": "dose_recompute",
            "status": "done",
            "result": "## 当前 Planning 剂量重算\nDose / DVH | 已更新",
        }],
        [],
        "zh",
    )

    assert failures == []
    assert successes == ["## 当前 Planning 剂量重算\nDose / DVH | 已更新"]


def test_recompute_executes_against_the_active_planning_snapshot():
    """The high-level tool must resolve state before invoking dose inference."""

    class Memory:
        def __init__(self):
            self.planning_results = {}
            self._planning_versions = {}
            self._lock = threading.RLock()
            self.conversation_state = {"data_available": []}
            self.user_lang = "zh"

        def retrieve(self, key):
            return self.planning_results.get(key)

        def store(self, key, value):
            self.planning_results[key] = value

    memory = Memory()
    agent = SimpleNamespace(memory=memory)
    seeds = [{"id": "seed_1", "position": [1.0, 2.0, 3.0]}]
    needles = [{"id": "needle_1", "start": [0.0, 0.0, 0.0], "end": [1.0, 1.0, 1.0]}]
    calls = {}

    def fake_compute(current_agent, current_seeds, current_needles, **kwargs):
        calls["geometry"] = (current_seeds, current_needles)
        calls["previous"] = kwargs
        current_agent.memory.store("dose_metrics", {"v100": 0.91})
        current_agent.memory.store("dvh_data", {"CTV": [[0.0, 100.0]]})
        current_agent.memory.store(
            "manual_artifact_status",
            {"dose": "ready", "dvh": "ready", "report": "stale", "surgical_guide": "stale"},
        )
        return {
            "metrics": {"v100": 0.91},
            "total_seeds": 1,
            "num_trajectories": 1,
            "artifact_status": current_agent.memory.retrieve("manual_artifact_status"),
        }

    def fake_publish(current_agent, result, *, status):
        calls["published"] = (result.metadata, status)

    with patch("tool_factory.dose_recompute._ensure_ct_runtime"), \
         patch("web.planning_runs.restore_active_planning_aliases"), \
         patch("web.planning_runs.active_planning_id", return_value="planning-p2"), \
         patch(
             "web.planning_runs.list_planning_runs",
             return_value=[{"planning_id": "planning-p2", "label": "Planning_2"}],
         ), \
         patch(
             "web.routes.planning_routes._current_planning_snapshot",
             return_value={"seeds": seeds, "needles": needles},
         ), \
         patch("web.routes.planning_routes._compute_manual_ai_dose", side_effect=fake_compute), \
         patch("web.planning_runs.publish_planning_run", side_effect=fake_publish):
        result = CurrentPlanDoseRecomputeTool().execute(
            _agent=agent,
            reason="manual geometry changed",
        )

    assert result.success is True
    assert calls["geometry"] == (seeds, needles)
    assert calls["previous"] == {
        "previous_needles": None,
        "previous_seeds": None,
        "previous_dose": None,
    }
    assert calls["published"][0]["planning_id"] == "planning-p2"
    assert calls["published"][0]["planning_label"] == "Planning_2"
    assert calls["published"][1] == "completed"
