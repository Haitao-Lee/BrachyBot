"""Deterministic downstream-repair plan for an aggregate "update everything".

The Session records which artifacts are stale in ``artifact_status``.  An
explicit "全部更新 / 所有后续都更新" turn is executed from that record, in
dependency order, instead of asking the model to re-derive the plan (and then
silently not executing it).
"""

from agent_runtime.response_tools import ResponseToolMixin
from agent_runtime.turn_policy import classify_local_turn


class _Memory:
    def __init__(self, values):
        self.values = values
        self.conversation = []

    def retrieve(self, key, default=None):
        return self.values.get(key, default)

    def get_ui_state(self):
        return {}


def _agent(values):
    agent = ResponseToolMixin()
    agent.memory = _Memory(values)
    return agent


STALE_ALL = {
    "dose_metrics": {"D90": 1.0},
    "artifact_status": {
        "quality_check": "stale",
        "report": "stale",
        "surgical_guide": "stale",
    },
}


def test_aggregate_update_is_a_direct_downstream_plan():
    for message in (
        "那请你全部更新",
        "全部更新，所有后续都更新",
        "update everything",
    ):
        policy = classify_local_turn(message, False, None, None)
        assert policy.intent == "downstream_update", message
        assert policy.direct_execution


def test_questions_and_negations_are_not_downstream_updates():
    for message in ("报告生成好了吗？", "不要全部更新", "如果要全部更新应该使用哪些工具"):
        assert classify_local_turn(message, False, None, None).intent != "downstream_update"


def test_plan_runs_stale_artifacts_in_dependency_order():
    calls = _agent(STALE_ALL)._detect_tool_request("全部更新，所有后续都更新")
    assert [call["tool"] for call in calls] == [
        "dose_evaluation",
        "ui_controller",
        "surgical_guide",
        "ui_controller",
    ]
    assert calls[1]["params"]["actions"][0]["target"] == "report.autofill"
    assert calls[3]["params"]["actions"][0]["target"] == "viewer.refresh_planning"


def test_plan_honours_an_explicit_exclusion():
    calls = _agent(STALE_ALL)._detect_tool_request("全部更新，不含导板")
    assert [call["tool"] for call in calls] == [
        "dose_evaluation",
        "ui_controller",
        "ui_controller",
    ]


def test_plan_only_touches_stale_artifacts():
    values = {
        "dose_metrics": {"D90": 1.0},
        "artifact_status": {
            "quality_check": "ready",
            "report": "ready",
            "surgical_guide": "stale",
        },
    }
    calls = _agent(values)._detect_tool_request("全部更新")
    assert [call["tool"] for call in calls] == ["surgical_guide", "ui_controller"]


def test_plan_abstains_without_a_planning_or_without_stale_work():
    assert _agent({})._detect_tool_request("全部更新") is None
    clean = {
        "dose_metrics": {"D90": 1.0},
        "artifact_status": {
            "quality_check": "ready",
            "report": "ready",
            "surgical_guide": "ready",
        },
    }
    assert _agent(clean)._detect_tool_request("全部更新") is None
