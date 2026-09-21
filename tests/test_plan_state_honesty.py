"""The system must not invent a planning state it cannot verify.

An already-planned case (particles visible in the Data Tree and 3D Viewer) was
reported as "planning not completed" / "still computing" because readiness was
judged from transient in-memory arrays and a lifecycle string instead of the
persisted planning record.  These tests pin the honest behaviour.
"""

from AgenticSys import BrachyAgent
from utils.user_errors import format_tool_error


class _Memory:
    def __init__(self, values):
        self.values = values
        self.conversation_state = {}

    def retrieve(self, key, default=None):
        return self.values.get(key, default)


class _Agent:
    def __init__(self, values):
        self.memory = _Memory(values)

    @staticmethod
    def _truthy_payload(value):
        if value is None:
            return False
        if isinstance(value, (dict, list, tuple, set, str, bytes)):
            return len(value) > 0
        return True


def test_manual_plan_is_recognised_as_completed():
    agent = _Agent({
        "dose_metrics": {"d90": 12.0, "v100": 0.9},
        "manual_seeds": [{"id": "seed_1"}],
        "manual_plan_serialized": [{"id": "seed_1"}],
        "dose_distribution": {"shape": [57, 512, 512]},
    })
    assert BrachyAgent._has_completed_planning(agent) is True


def test_geometry_only_manual_plan_is_not_completed():
    agent = _Agent({"manual_seeds": [{"id": "seed_1"}]})
    assert BrachyAgent._has_completed_planning(agent) is False


def test_missing_input_is_reported_as_loading_not_planning_incomplete():
    message = format_tool_error("dose_evaluation", "ctv_mask is required", {}, "zh")
    assert "尚未加载" in message or "仍在加载" in message
    assert "规划没有完成" not in message


def test_genuine_planning_failure_keeps_the_planning_message():
    message = format_tool_error("dose_evaluation", "planner solver diverged", {}, "zh")
    assert "规划没有完成" in message
