"""Registered pipeline tool publishes to its named workspace, never the mounted one."""
from types import SimpleNamespace
from uuid import uuid4
import numpy as np
import pytest

from agent_runtime.core import AgentMemory, ToolResultPipeline
from tool_factory import ToolResult
from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
from web.workspace_store import WorkspaceStore


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    store = WorkspaceStore(tmp_path / "runtime")
    owner = store.create_user("scoped_executor", "synthetic-hash")["id"]
    sid = store.create_session(owner, "Synthetic patient").id
    created = store.create_timepoint(owner, sid, "Named scan", expected_revision=0)
    target = created["created_timepoint_id"]
    root = store.workspace_root(owner, sid, create=True)
    store.save_timepoint_results(owner, sid, target, {"ct_data": np.zeros((4,4,4), np.int16),
        "ct_spacing": (1.,1.,1.), "ct_origin": (0.,0.,0.), "ct_direction": (1.,0.,0.,0.,1.,0.,0.,0.,1.),
        "ctv_binary_array": np.ones((4,4,4), np.uint8), "oar_array": np.zeros((4,4,4), np.uint8)},
        expected_state_revision=0)
    memory = AgentMemory(sid)
    memory.store("ct_path", "mounted-scan-must-not-be-read")
    memory.store("dose_metrics", {"v100": .123})
    memory.add_message("user", "shared conversation")
    agent = SimpleNamespace(memory=memory, _workspace_store=store,
        config={"_workspace_owner_id": owner, "_workspace_session_id": sid, "_workspace_root": str(root)})
    return store, owner, sid, target, agent


def test_registered_tool_commits_to_named_workspace_preserving_shared_agent(owned, monkeypatch):
    store, owner, sid, target, agent = owned
    before = dict(agent.memory.planning_results)
    captured = []
    def run(_tool, image, ctv, oar, ref, mode, config, view, **kwargs):
        assert view is not agent
        assert view.config["_workspace_timepoint_id"] == target
        assert image.GetSize() == (4,4,4)
        assert view.memory.retrieve("ct_path") is None
        view.memory.store("dose_metrics", {"v100": .9})
        view.memory.store("total_seeds", 2)
        callback = kwargs.get("preview_emitter")
        if callback:
            callback.start("seed_planning")
        return ToolResult(success=True, metadata={"step_executed": "full", "total_seeds": 2,
            "dose_metrics": {"v100": .9}})
    monkeypatch.setattr(PlanningPipelineTool, "_run_full_pipeline", run)
    def receive_preview(event): captured.append(event)
    receive_preview.supports_timepoint_scope = True
    result = PlanningPipelineTool()._execute(_agent=agent, timepoint_id=target, step="full", preview_callback=receive_preview)
    assert result.success, result.error
    assert result.metadata["published_to_timepoint"] is True
    assert result.metadata["timepoint_title"] == "Named scan"
    assert agent.memory.planning_results == before
    assert agent.memory.conversation[-1]["content"] == "shared conversation"
    saved = store.load_timepoint_snapshot(owner, sid, target, decode_arrays=True)
    assert saved["agent"]["planning_results"]["dose_metrics"]["v100"] == .9
    assert captured and all(event["timepoint_id"] == target for event in captured)
    assert not store.load_snapshot(owner, sid)["agent"]["planning_results"].get("dose_metrics")


def test_wrong_timepoint_or_mixed_input_paths_cannot_fall_back_to_default(owned):
    _, _, _, target, agent = owned
    result = PlanningPipelineTool()._execute(_agent=agent, timepoint_id=uuid4().hex, step="full")
    assert not result.success
    result = PlanningPipelineTool()._execute(_agent=agent, timepoint_id=target, step="full", ct_image_path="mounted-other.nii")
    assert not result.success
    assert "mixed legacy" in result.error
    assert agent.memory.retrieve("dose_metrics")["v100"] == .123


def test_target_change_during_calculation_never_publishes_stale_success(owned, monkeypatch):
    store, owner, sid, target, agent = owned
    other = WorkspaceStore(store.runtime_dir)
    def run(_tool, *args, **kwargs):
        other.save_timepoint_results(owner, sid, target, {"input_changed": True}, expected_clinical_revision=1)
        args[6].memory.store("dose_metrics", {"v100": .99})
        return ToolResult(success=True, metadata={"dose_metrics": {"v100": .99}})
    monkeypatch.setattr(PlanningPipelineTool, "_run_full_pipeline", run)
    result = PlanningPipelineTool()._execute(_agent=agent, timepoint_id=target, step="full")
    assert not result.success
    assert result.metadata["calculation_completed"] is True
    state = store.load_timepoint_snapshot(owner, sid, target)["agent"]["planning_results"]
    assert state["input_changed"] is True
    assert "dose_metrics" not in state


def test_failure_does_not_replace_saved_target_or_shared_conversation(owned, monkeypatch):
    store, owner, sid, target, agent = owned
    monkeypatch.setattr(PlanningPipelineTool, "_run_full_pipeline", lambda *a, **k: ToolResult(success=False, error="synthetic calculation failure"))
    result = PlanningPipelineTool()._execute(_agent=agent, timepoint_id=target, step="full")
    assert not result.success
    assert store.list_timepoints(owner, sid)["items"][target]["clinical_revision"] == 1
    assert agent.memory.retrieve("dose_metrics")["v100"] == .123


def test_legacy_session_only_viewer_callback_cannot_paint_other_timepoint(owned, monkeypatch):
    _, _, _, target, agent = owned
    captured = []
    def run(_tool, *args, **kwargs):
        emitter = kwargs["preview_emitter"]
        emitter.start("trajectory_init")
        return ToolResult(success=True, metadata={"step_executed": "full"})
    monkeypatch.setattr(PlanningPipelineTool, "_run_full_pipeline", run)
    result = PlanningPipelineTool()._execute(_agent=agent, timepoint_id=target, step="full", preview_callback=captured.append)
    assert result.success, result.error
    assert captured == []


def test_agent_store_and_normalizer_do_not_copy_other_timepoint_result_to_root(owned):
    from AgenticSys import BrachyAgent
    _, _, _, target, agent = owned
    call = [{"tool": "planning_pipeline", "params": {"timepoint_id": target, "step": "full"}}]
    assert BrachyAgent._normalize_clinical_tool_calls(agent, call, "only replan that saved scan") == call
    BrachyAgent._store_tool_result(agent, "planning_pipeline", ToolResult(success=True,
        metadata={"timepoint_id": target, "dose_metrics": {"v100": .99}, "total_seeds": 999}))
    assert agent.memory.retrieve("dose_metrics")["v100"] == .123
    assert agent.memory.retrieve("total_seeds") is None


def test_scoped_planning_formatter_does_not_claim_unmounted_viewer_is_displayed():
    result = ToolResult(success=True, metadata={"step_executed": "full", "timepoint_title": "Target scan",
        "total_seeds": 2, "total_source_count": 8, "supplemental_only": True, "target_coverage_met": False,
        "dose_metrics": {"v100": .8, "d90": 90., "plan_score": None}})
    en = ToolResultPipeline.format("planning_pipeline", result, "en")
    zh = ToolResultPipeline.format("planning_pipeline", result, "zh")
    assert "Target scan" in en
    assert "| Sources (implanted + newly planned) | 8 |" in en
    assert "Coverage remains below" in en
    assert "Unavailable" in en and "未提供" in zh
    assert "displayed in 3D" not in en
