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


def test_type_rejection_is_reported_as_loading_not_planning_incomplete():
    message = format_tool_error(
        "dose_evaluation", "Invalid parameter type for dose_array", {}, "zh"
    )
    assert "尚未加载" in message or "仍在加载" in message
    assert "规划没有完成" not in message


def test_dose_evaluation_schema_marks_server_injected_arrays():
    from tool_factory.dose_eval import DoseEvaluationTool

    properties = DoseEvaluationTool().input_schema["properties"]
    for field in ("dose_array", "ctv_mask", "oar_mask"):
        assert properties[field].get("x-server-injected") is True, field


def test_gateway_accepts_the_server_injected_numpy_dose_arrays():
    import numpy as np

    from agent_runtime.contracts import ToolCall, ToolCallGateway
    from tool_factory.dose_eval import DoseEvaluationTool

    tool = DoseEvaluationTool()

    class Registry:
        tool_names = {"dose_evaluation"}

        @staticmethod
        def get(_name):
            return tool

    gateway = ToolCallGateway.__new__(ToolCallGateway)
    call = ToolCall.from_payload("dose_evaluation", {
        "dose_array": np.zeros((2, 2, 2)),
        "ctv_mask": np.zeros((2, 2, 2), dtype=np.uint8),
    })
    assert gateway.validate(Registry(), call) is None


def test_genuine_planning_failure_keeps_the_planning_message():
    message = format_tool_error("dose_engine", "planner solver diverged", {}, "zh")
    assert "规划没有完成" in message


def test_dose_evaluation_failure_never_claims_planning_incomplete():
    message = format_tool_error("dose_evaluation", "planner solver diverged", {}, "zh")
    assert "规划没有完成" not in message
    assert "剂量评估" in message


def test_grid_mismatch_is_reported_as_data_mismatch_not_planning_incomplete():
    message = format_tool_error(
        "dose_evaluation", "ctv_mask shape must match dose_array", {}, "zh"
    )
    assert "规划没有完成" not in message
    assert "网格" in message


def test_grid_mismatch_on_planning_tools_is_also_honest():
    message = format_tool_error(
        "dose_engine",
        "[dose_eval] Dose and CTV grids do not match: dose=(64, 128, 128), CTV=(57, 512, 512).",
        {},
        "zh",
    )
    assert "规划没有完成" not in message
    assert "网格" in message


def test_memory_has_planning_result_uses_persisted_data_not_a_lifecycle_flag():
    from agent_runtime.llm_runtime import _memory_has_planning_result

    class Memory:
        def __init__(self, values):
            self.values = values

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

    # A manual draft still exposes dose/metrics in the workspace.
    assert _memory_has_planning_result(Memory({"dose_metrics": {"d90": 12.0}})) is True
    assert _memory_has_planning_result(Memory({"dose_distribution_gy": object()})) is True
    assert _memory_has_planning_result(Memory({})) is False
    assert _memory_has_planning_result(None) is False
