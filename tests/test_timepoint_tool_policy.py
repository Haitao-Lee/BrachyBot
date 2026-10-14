"""New mixed-effect operations retain semantic authorization and scope boundaries."""
import pytest
from agent_runtime.execution_authorization import TurnExecutionAuthorization, tool_call_is_mutating
from agent_runtime.workspace_readiness import requires_full_workspace
from agent_runtime.artifact_analysis import coerce_analysis_tool_call


@pytest.mark.parametrize("action", ["status", "analyze", "manifest", "validate_placement"])
def test_guide_reads_never_acquire_generation_effect(action):
    params = {"action": action, "source_timepoint_id": "a" * 32}
    assert not tool_call_is_mutating("surgical_guide", params)
    assert coerce_analysis_tool_call("surgical_guide", params, "inspect") == params


def test_manifest_does_not_wait_for_unrelated_case_array_hydration():
    assert not requires_full_workspace("surgical_guide", {"action": "manifest"})
    assert not requires_full_workspace("timepoint_inspector", {"action": "list"})
    assert not requires_full_workspace("seed_segmentation", {"action": "get_reconstruction"})
    assert requires_full_workspace("surgical_guide", {"action": "validate_placement"})


def test_analysis_cannot_turn_a_placement_request_into_generation():
    assert coerce_analysis_tool_call("surgical_guide", {"action": "estimate_placement", "placement": {"matrix": []}}, "inspect") == {"action": "analyze"}


def test_new_seed_operations_are_action_aware_not_all_read_only():
    assert not tool_call_is_mutating("seed_segmentation", {"action": "get_reconstruction"})
    for action in (None, "reconstruct", "detect", "review_reconstruction", "unknown"):
        assert tool_call_is_mutating("seed_segmentation", {"action": action})


def test_whole_guide_name_grant_cannot_transfer_another_timepoints_printed_guide():
    auth = TurnExecutionAuthorization(1)
    auth.grant_tools(["surgical_guide"], source="legacy_generate")
    assert auth.tool_allowed("surgical_guide", {"action": "generate"})
    call = {"action": "estimate_placement", "source_timepoint_id": "a" * 32, "timepoint_id": "b" * 32,
            "guide_version": 1, "placement": {"method": "manual_rigid"}}
    assert not auth.tool_allowed("surgical_guide", call)
    auth.grant_tool_calls([{"tool": "surgical_guide", "params": call}], source="explicit_semantic_call")
    assert auth.tool_allowed("surgical_guide", call)
    for key, value in (("source_timepoint_id", "c" * 32), ("timepoint_id", "c" * 32), ("guide_version", 2)):
        assert not auth.tool_allowed("surgical_guide", {**call, key: value})


def test_normalization_cannot_add_a_hidden_timepoint_to_an_old_scoped_grant():
    auth = TurnExecutionAuthorization(1)
    auth.grant_tool_calls([{"tool": "planning_pipeline", "params": {"step": "full"}}], source="explicit_call")
    assert not auth.tool_allowed("planning_pipeline", {"step": "full", "timepoint_id": "a" * 32})


@pytest.mark.parametrize("action", ["reconstruct", "get_reconstruction", "review_reconstruction"])
def test_scoped_implant_actions_do_not_receive_a_mounted_default_image(action):
    # Exercise the actual agent injector, not only the direct tool dispatcher.
    # A default image argument is incompatible with captured implant inputs.
    from AgenticSys import BrachyAgent
    from tool_factory import ToolResult
    from agent_runtime.core import AgentMemory
    from types import SimpleNamespace
    original = BrachyAgent._execute_tool_with_memory
    received = []
    class Harness:
        _VALIDATORS = {}
        def _current_execution_authorization(self): return None
        def _is_replan_request(self, *args): return False
        def _inject_reference_direction_params(self, *args): return None
        def _force_reexecution_requested(self, **kwargs): return False
    agent = Harness()
    agent.memory, agent.config = AgentMemory("a" * 32), {}
    agent.memory.store("ct_image", "mounted-other-image-must-not-be-injected")
    agent.registry = SimpleNamespace(execute=lambda name, **kwargs: (
        received.append(kwargs) or ToolResult(success=True, metadata={"num_detected": 1})))
    agent.tool_gateway = SimpleNamespace(execute=lambda registry, name, params, run, **kwargs: run())
    # The relevant producer uses the registry without requiring model assets.
    result = original(agent, "seed_segmentation", {"action": action})
    assert result.success
    assert len(received) == 1
    assert "image" not in received[0]
