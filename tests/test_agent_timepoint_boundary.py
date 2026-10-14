"""Actual registry/task adapters: owned defaults, helper admission and CAS reads."""
import copy
import json
import threading
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pytest

from AgenticSys import BrachyAgent
from agent_runtime.core import AgentMemory, ToolRegistry
from agent_runtime.contracts import RunLedger, ToolCallGateway
from agent_runtime.execution_authorization import TurnExecutionAuthorization
from agent_runtime.timepoint_targets import (capture_human_target_evidence,
    confirm_pending_timepoint_call, require_human_target)
from tool_factory import BaseTool, ToolResult
from tool_factory.timepoint_controller import TimepointControllerTool
from tool_factory.timepoint_inspector import TimepointInspectorTool
from tool_factory.viewer_command.query_metrics import QueryMetricsTool
from web.chat_tasks import ChatTaskManager
from web.timepoint_chat import ScopedChatRuntime, capture_chat_scope
from web.timepoint_http import current_binding, ScopedWorkspaceStore
from web.timepoints import TimepointConflict
from web.workspace_store import WorkspaceStore


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    raw = WorkspaceStore(tmp_path / "runtime")
    owner = raw.create_user("agent_scope", "synthetic-hash")["id"]
    sid = raw.create_session(owner, "Synthetic").id
    catalog = raw.migrate_default_timepoint(owner, sid)
    first = catalog["default_timepoint_id"]
    second = raw.create_timepoint(owner, sid, "Scan B", expected_revision=catalog["catalog_revision"])["created_timepoint_id"]
    for target, coverage in ((first, .8), (second, .9)):
        state = raw.load_timepoint_snapshot(owner, sid, target)
        raw.save_timepoint_results(owner, sid, target, {
            "ct_data": np.zeros((3, 3, 3), np.int16), "ct_spacing": [1., 1., 1.],
            "ct_origin": [0., 0., 0.], "ct_direction": [1., 0., 0., 0., 1., 0., 0., 0., 1.],
            "ctv_array": np.ones((3, 3, 3), np.uint8), "oar_array": np.zeros((3, 3, 3), np.uint8),
            "dose_metrics": {"v100": coverage, "d90": 100., "prescription_gy": 100.},
            "metric_units": {"dose": "Gy", "coverage": "fraction"}, "dose_source_basis": "projected_total",
        }, expected_clinical_revision=state["timepoint_clinical_revision"])
    root = object.__new__(BrachyAgent)
    root.memory = AgentMemory(sid)
    root.memory.store("dose_metrics", {"v100": .1})
    root.config = {"_workspace_owner_id": owner, "_workspace_session_id": sid,
                   "_workspace_root": str(raw.workspace_root(owner, sid)),
                   "_workspace_scoped_browser_delivery": True}
    root._workspace_store = raw
    root._workspace_data_ready = True
    root._begin_context_turn = lambda: None
    root.registry = ToolRegistry()
    for tool in (QueryMetricsTool(), TimepointInspectorTool(root), TimepointControllerTool(root)):
        root.registry.register(tool)
    root.run_ledger = RunLedger()
    root.tool_gateway = ToolCallGateway(root.run_ledger)
    root._workspace_hydration_cancel = threading.Event()
    root._workspace_ready_event = threading.Event()
    root._workspace_hydration_in_progress = True
    root._active_turn_context = {"bad_previous_request": True}
    root._turn_local = threading.local()
    raw.acquire_lease(owner, sid, "synthetic-editor")
    return raw, owner, sid, first, second, root


def activate(owned, target=None, message="Read the current metrics"):
    raw, owner, sid, first, _, root = owned
    scope = capture_chat_scope(raw, owner, sid, target or first)
    runtime = ScopedChatRuntime(root, scope)
    runtime.view._active_turn_context = {"timepoint_scope": scope, "request_id": "human-request",
                                        "editor_token": "synthetic-editor"}
    runtime.view._begin_turn(message)
    return runtime


def grant(runtime, name, params):
    runtime.view._current_execution_authorization().grant_tool_calls(
        [{"tool": name, "params": params}], source="synthetic_primary_selection")


def test_migrated_default_detaches_registry_memory_and_lifecycle(owned):
    raw, owner, sid, first, _, root = owned
    runtime = activate(owned)
    view = runtime.view
    assert view is not root and view.registry is not root.registry
    assert view.registry.get("timepoint_inspector")._agent is view
    assert isinstance(view._workspace_store, ScopedWorkspaceStore)
    assert view._workspace_store.raw is raw
    assert view._workspace_hydration_cancel is not root._workspace_hydration_cancel
    assert view._workspace_ready_event is not root._workspace_ready_event
    assert view._turn_local is not root._turn_local
    assert not view._workspace_hydration_in_progress
    assert "bad_previous_request" not in view._active_turn_context
    result = view.registry.execute("query_metrics", metric_type="dose_metrics")
    assert result.success and result.data["V100"] == .8
    assert result.metadata["scope"]["timepoint_id"] == first
    assert root.memory.retrieve("dose_metrics") == {"v100": .1}
    runtime.close()


def test_direct_registry_explicit_other_target_cannot_bypass_binding(owned):
    runtime = activate(owned)
    with pytest.raises(TimepointConflict):
        runtime.view.registry.execute("query_metrics", metric_type="dose_metrics", timepoint_id=owned[4])
    runtime.close()


def test_human_named_other_target_mutation_changes_only_other_target(owned, monkeypatch):
    raw, owner, sid, first, second, root = owned
    runtime = activate(owned, message="Update the clinical planning in Scan B")
    params = {"step": "seed_planning", "timepoint_id": second}
    grant(runtime, "planning_pipeline", params)
    def compute(view, name, args, **callbacks):
        assert current_binding().timepoint_id == second
        assert view.memory.retrieve("dose_metrics")["v100"] == .9
        view.memory.store("synthetic_change", True)
        return ToolResult(True)
    monkeypatch.setattr(BrachyAgent, "_execute_tool_with_memory_unscoped", compute)
    result = runtime.view._execute_tool_with_memory("planning_pipeline", params)
    assert result.success, result.error
    assert raw.load_timepoint_snapshot(owner, sid, second)["agent"]["planning_results"]["synthetic_change"] is True
    assert "synthetic_change" not in raw.load_timepoint_snapshot(owner, sid, first)["agent"]["planning_results"]
    assert root.memory.retrieve("synthetic_change") is None
    runtime.close()


def test_model_id_creates_exact_confirmation_without_mutation(owned):
    runtime = activate(owned, message="Update the current clinical planning")
    params = {"step": "seed_planning", "timepoint_id": owned[4]}
    grant(runtime, "planning_pipeline", params)
    result = runtime.view._execute_tool_with_memory("planning_pipeline", params)
    assert not result.success and result.metadata["code"] == "timepoint_target_confirmation_required"
    pending = result.metadata["target_confirmation"]
    assert pending["timepoint_id"] == owned[4] and not pending["confirmed"]
    raw, owner, sid, _, _, root = owned
    receipt = confirm_pending_timepoint_call(root, pending["receipt_id"], owner_id=owner,
        session_id=sid, request_id="next-human-request")
    assert receipt.permits(runtime.scope, "planning_pipeline", params, raw, "next-human-request")
    assert not receipt.permits(runtime.scope, "planning_pipeline", {**params, "step": "full"}, raw, "next-human-request")
    assert confirm_pending_timepoint_call(root, pending['receipt_id'], owner_id=owner, session_id=sid,
        request_id='next-human-request') is receipt  # A dropped handshake rejoins the same task.
    with pytest.raises(TimepointConflict):
        confirm_pending_timepoint_call(root, pending['receipt_id'], owner_id=owner, session_id=sid, request_id='different-request')
    runtime.close()


def test_duplicate_catalog_titles_do_not_select_first_match(owned):
    raw, owner, sid, first, second, _ = owned
    catalog = raw.list_timepoints(owner, sid)
    raw.update_timepoint(owner, sid, first, {"title": "Scan B"}, expected_revision=catalog["catalog_revision"])
    scope = capture_chat_scope(raw, owner, sid, first)
    evidence = capture_human_target_evidence(raw, scope, "Run planning in Scan B")
    assert evidence.targets == ()


def test_compare_uses_saved_readset_without_array_decode_or_writes(owned, monkeypatch):
    raw, owner, sid, first, second, root = owned
    before = copy.deepcopy(raw.list_timepoints(owner, sid))
    import web.workspace_store as persistence
    monkeypatch.setattr(persistence, "_decode_artifacts", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Comparison decoded arrays")))
    result = TimepointInspectorTool(root).execute(action="compare", timepoint_ids=[first, second])
    assert result.success, result.error
    assert result.data["comparisons"][0]["aggregate_difference_comparable"]
    assert not result.data["dose_sum_performed"]
    assert result.metadata["read_only"] and len(result.metadata["readset"]) == 2
    assert raw.list_timepoints(owner, sid) == before
    assert root.memory.retrieve("dose_metrics") == {"v100": .1}


def test_comparison_missing_units_never_infers_fraction_or_percent(owned):
    raw, owner, sid, first, second, root = owned
    state = raw.load_timepoint_snapshot(owner, sid, second)
    raw.save_timepoint_results(owner, sid, second, {"metric_units": {}},
        expected_clinical_revision=state["timepoint_clinical_revision"])
    result = TimepointInspectorTool(root).execute(action="compare", timepoint_ids=[first, second])
    comparison = result.data["comparisons"][0]
    assert "metric_units_missing_or_different" in comparison["comparability_limits"]
    assert all(row["difference"] is None for row in comparison["saved_metric_rows"])


def test_compare_reads_canonical_components_without_arrays_and_refuses_stale_quality(owned):
    raw,owner,sid,first,second,root=owned
    for tid in (first,second):
        state=raw.load_timepoint_snapshot(owner,sid,tid)
        record={'source_set':'total','dose_units':'physical_gy','source_count':12,
            'dose_basis':'projected_total_source_dose_not_elapsed_delivered_dose',
            'dependency_fingerprint':'total-current','dose_sha256':'a'*64,
            'dose_distribution_physical_gy':np.ones((3,3,3),np.float32)}
        metrics={**state['agent']['planning_results']['dose_metrics'],'source_set':'total',
                 'dose_value_unit':'gy','volume_metric_units':'fraction'}
        raw.save_timepoint_results(owner,sid,tid,{'dose_components':{'total':record},'dose_metrics':metrics,
            'metric_units':{},'timepoint_resource_state':{'fingerprints':{'total_dose':'total-current'}}},
            expected_clinical_revision=state['timepoint_clinical_revision'])
    result=TimepointInspectorTool(root).execute(action='compare',timepoint_ids=[first,second])
    assert result.success and result.data['comparisons'][0]['aggregate_difference_comparable']
    assert result.data['timepoints'][0]['dose_components']['total']['source_count']==12
    assert 'dose_distribution_physical_gy' not in str(result.data)
    state=raw.load_timepoint_snapshot(owner,sid,second)
    raw.save_timepoint_results(owner,sid,second,{'artifact_status':{'dose':'stale'}},
        expected_clinical_revision=state['timepoint_clinical_revision'])
    comparison=TimepointInspectorTool(root).execute(action='compare',timepoint_ids=[first,second]).data['comparisons'][0]
    assert 'saved_quality_invalidated_recompute_required' in comparison['comparability_limits']
    assert all(row['difference'] is None for row in comparison['saved_metric_rows'])


class PureArithmetic(BaseTool):
    name = "math_helper"
    description = "Synthetic trusted arithmetic helper"
    timepoint_access = "pure"
    input_schema = {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}
    def _execute(self, **kwargs):
        return ToolResult(True, data=kwargs["a"] + kwargs["b"])


def test_real_registered_pure_helper_is_admitted_without_hydration(owned, monkeypatch):
    owned[-1].registry.register(PureArithmetic())
    runtime = activate(owned)
    import web.workspace_store as persistence
    monkeypatch.setattr(persistence, "_decode_artifacts", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Math loaded CT")))
    result = runtime.view.registry.execute("math_helper", a=4., b=7.)
    assert result.success and result.data == 11.
    assert result.metadata["scope"]["timepoint_id"] == owned[3]
    runtime.close()


def test_compiled_inventory_accounts_for_every_actual_registered_tool(owned):
    root = owned[-1]
    root._load_tools()
    from agent_runtime.timepoint_capabilities import compiled_capability_catalog
    catalog = compiled_capability_catalog(root.registry, browser_ready=True)
    assert {row["name"] for row in catalog["tools"]} == set(root.registry.tool_names)
    assert catalog["registered_count"] >= 30
    assert catalog["missing_scope_adapters"] == []


@pytest.mark.parametrize("name,steps", [("trajectory_planning", ["trajectory_init", "trajectory_refine"]),
    ("seed_planning", ["seed_planning"]), ("seed_planning_rl", ["seed_planning"]),
    ("seed_planning_rule_based", ["seed_planning"])])
def test_direct_planning_delegates_only_authorized_canonical_steps(owned, monkeypatch, name, steps):
    runtime = activate(owned, message="Run the requested planning step")
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
    calls = []
    def execute(tool, **kwargs):
        calls.append(kwargs)
        assert kwargs["_agent"] is runtime.view
        assert current_binding().timepoint_id == owned[3]
        return ToolResult(True)
    monkeypatch.setattr(PlanningPipelineTool, "execute", execute)
    grant(runtime, name, {})
    result = runtime.view._execute_tool_with_memory(name, {})
    assert result.success, result.error
    assert [call["step"] for call in calls] == steps
    assert not result.metadata["full_pipeline_executed"]
    assert not runtime.view._current_execution_authorization().tool_allowed("planning_pipeline", {"step": "full"})
    runtime.close()


def test_task_supplier_control_and_finalizer_bind_origin_and_journal(owned, monkeypatch):
    raw, owner, sid, first, _, root = owned
    observed = []
    def supplier():
        assert current_binding() is None
        return root
    def stream(view, message):
        assert view is not root and current_binding().timepoint_id == first
        assert view._active_turn_context["editor_token"] == "synthetic-editor"
        yield 'event: response\ndata: {"response":"Synthetic answer"}\n\n'
        yield 'event: done\ndata: {}\n\n'
    def finalize(task):
        assert current_binding().timepoint_id == first
        runtime = task.agent._workspace_scoped_chat_runtime
        assert not runtime.closed
        observed.append(task.agent)
        return True
    monkeypatch.setattr(BrachyAgent, "chat_with_stream", stream)
    app = SimpleNamespace(app_context=lambda: nullcontext(), extensions={"brachybot_workspace_store": raw})
    task = ChatTaskManager().start(app, owner, sid, None, "Read facts", {}, agent_supplier=supplier,
        on_finish=finalize, timepoint_scope=capture_chat_scope(raw, owner, sid, first),
        editor_token="synthetic-editor", request_id="captured-task")
    assert task.wait_for_worker(timeout=10)
    assert task.status == "completed" and len(observed) == 1
    assert task.agent is root
    operation = raw.latest_timepoint_operation(owner, sid, first)
    assert operation["state"] == "ready" and operation["operation_id"] == task.task_id
    assert operation["request_id"] == "captured-task"
