"""Submission target, tool isolation and shared-dialogue negative controls."""
from dataclasses import FrozenInstanceError, replace
import json
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from AgenticSys import BrachyAgent
from agent_runtime.core import AgentMemory, ToolRegistry
from agent_runtime.contracts import RunLedger, ToolCallGateway
from tool_factory import ToolResult
from tool_factory.viewer_command.query_metrics import QueryMetricsTool
from web.chat_tasks import ChatTaskManager
from web.timepoint_chat import ChatTimepointScope, capture_chat_scope, ScopedChatRuntime
from web.timepoints import TimepointConflict, TimepointError
from web.workspace_store import WorkspaceStore
from utils.tool_security import tool_scope, output_directory, validate_tool_paths, workspace_root


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    store = WorkspaceStore(tmp_path / "runtime")
    owner = store.create_user("chat_scope", "synthetic-test-hash")["id"]
    sid = store.create_session(owner, "Synthetic patient").id
    first = store.create_timepoint(owner, sid, "Scan B", expected_revision=0)["created_timepoint_id"]
    second = store.create_timepoint(owner, sid, "Scan C", expected_revision=1)["created_timepoint_id"]
    for identifier, coverage in ((first, .81), (second, .92)):
        store.save_timepoint_results(owner, sid, identifier, {
            "ct_data": np.zeros((4, 4, 4), np.int16), "ct_spacing": (1., 1., 1.), "ct_origin": (0., 0., 0.),
            "ct_direction": (1., 0., 0., 0., 1., 0., 0., 0., 1.), "dose_metrics": {"v100": coverage},
            "ctv_binary_array": np.ones((4, 4, 4), np.uint8), "oar_array": np.zeros((4, 4, 4), np.uint8),
        }, expected_state_revision=0)
    agent = object.__new__(BrachyAgent)
    agent.config = {"_workspace_owner_id": owner, "_workspace_session_id": sid,
                    "_workspace_root": str(store.workspace_root(owner, sid))}
    agent._workspace_store = store
    agent._workspace_data_ready = True
    agent.memory = AgentMemory(sid)
    agent.memory.store("dose_metrics", {"v100": .11})
    agent.memory.store("ct_path", "root-scan-must-not-be-used")
    agent.registry = ToolRegistry()
    agent.registry.register(QueryMetricsTool())
    agent.run_ledger = RunLedger()
    agent.tool_gateway = ToolCallGateway(agent.run_ledger)
    return store, owner, sid, first, second, agent


def activate(owned, identifier=None, language="en"):
    store, owner, sid, first, _, agent = owned
    scope = capture_chat_scope(store, owner, sid, identifier or first, ui_language=language)
    runtime = ScopedChatRuntime(agent, scope)
    runtime.view._active_turn_context = {"timepoint_scope": scope}
    return runtime


def test_default_is_owned_legacy_and_captured_target_is_immutable(owned):
    store, owner, sid, first, _, _ = owned
    scope = capture_chat_scope(store, owner, sid)
    assert scope.timepoint_id == store.list_timepoints(owner, sid)["default_timepoint_id"]
    selected = capture_chat_scope(store, owner, sid, first, ui_language="zh")
    with pytest.raises(FrozenInstanceError):
        selected.timepoint_id = scope.timepoint_id
    assert selected.public_dict() == {"session_id": sid, "timepoint_id": first, "ui_language": "zh"}
    assert "owner_id" not in selected.public_dict()
    assert scope.legacy_default is True and selected.legacy_default is False


def test_only_automatic_default_title_is_localizable_not_a_custom_name(owned):
    store, owner, sid, _, _, _ = owned
    catalog = store.list_timepoints(owner, sid)
    default = catalog["default_timepoint_id"]
    assert catalog["items"][default]["auto_title"] is True
    renamed = store.update_timepoint(owner, sid, default, {"title": "Clinician's custom title"},
        expected_revision=catalog["catalog_revision"])
    assert renamed["items"][default]["auto_title"] is False
    assert renamed["items"][default]["title"] == "Clinician's custom title"


def test_child_inherits_parent_not_the_newly_selected_target(owned):
    store, owner, sid, first, second, _ = owned
    parent = capture_chat_scope(store, owner, sid, first)
    child = capture_chat_scope(store, owner, sid, parent_scope=parent)
    assert child.timepoint_id == first
    with pytest.raises(TimepointConflict):
        capture_chat_scope(store, owner, sid, second, parent_scope=parent)
    with pytest.raises(TimepointConflict):
        capture_chat_scope(store, owner, sid, parent_scope=replace(parent, session_id="f" * 32))


@pytest.mark.parametrize("bad", ["", "current", "Scan B", "../scan", "F" * 32, 1, True, [], {}])
def test_explicit_invalid_target_does_not_fall_back_to_default(owned, bad):
    store, owner, sid, _, _, _ = owned
    with pytest.raises((TimepointError, TypeError)):
        capture_chat_scope(store, owner, sid, bad)


def test_actual_metrics_injector_reads_selected_scan_not_shared_agent(owned):
    *_, root = owned
    runtime = activate(owned)
    result = runtime.view._execute_tool_with_memory("query_metrics", {"metric_type": "dose_metrics"})
    assert result.success, result.error
    assert result.data["V100"] == .81
    assert result.metadata["timepoint_id"] == runtime.scope.timepoint_id
    assert root.memory.retrieve("dose_metrics")["v100"] == .11
    assert root.memory.tool_results[-1]["timepoint_id"] == runtime.scope.timepoint_id
    runtime.close()


def test_saved_dose_read_does_not_decode_arrays_or_remove_their_references(owned, monkeypatch):
    import web.workspace_store as persistence
    store, owner, sid, first, _, _ = owned
    encoded = store.load_timepoint_snapshot(owner, sid, first)["agent"]["planning_results"]["ct_data"]
    monkeypatch.setattr(persistence, "_decode_artifacts", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Heavy array decode on saved-metric read")))
    runtime = activate(owned)
    result = runtime.view._execute_tool_with_memory("query_metrics", {"metric_type": "dose_metrics"})
    assert result.success and result.data["V100"] == .81
    assert runtime.view._workspace_data_ready is False
    assert store.load_timepoint_snapshot(owner, sid, first)["agent"]["planning_results"]["ct_data"] == encoded
    runtime.close()


def test_metadata_only_commit_preserves_undecoded_arrays(owned):
    store, owner, sid, first, _, _ = owned
    runtime = activate(owned)
    encoded = store.load_timepoint_snapshot(owner, sid, first)["agent"]["planning_results"]["ct_data"]
    runtime.before_tool()
    runtime.view.memory.store("metadata_change", {"saved": True})
    assert runtime.commit_tool(ToolResult(True)).success
    saved = store.load_timepoint_snapshot(owner, sid, first)["agent"]["planning_results"]
    assert saved["ct_data"] == encoded and saved["metadata_change"] == {"saved": True}
    runtime.close()


def test_explicit_sibling_call_overrides_only_that_call(owned):
    store, owner, sid, first, second, root = owned
    runtime = activate(owned)
    view = runtime.view
    one = view._execute_tool_with_memory("query_metrics", {"metric_type": "dose_metrics", "timepoint_id": second})
    two = view._execute_tool_with_memory("query_metrics", {"metric_type": "dose_metrics"})
    assert one.success and two.success
    assert one.data["V100"] == .92 and two.data["V100"] == .81
    assert one.metadata["timepoint_id"] == second and two.metadata["timepoint_id"] == first
    assert root.memory.retrieve("dose_metrics")["v100"] == .11
    runtime.close()


def test_explicit_sibling_rebinds_legacy_http_locks_and_restores_parent_context(owned):
    from web.timepoint_http import HttpTimepointBinding, bound_request, current_binding, bucket_key
    from web.timepoint_chat import run_scoped_tool
    _, owner, sid, first, second, _ = owned
    runtime = activate(owned)
    def execute(view, name, params, **kwargs):
        assert current_binding().timepoint_id == second
        assert bucket_key(sid) == (owner,sid,second)
        assert view.memory.retrieve('dose_metrics')['v100'] == .92
        return ToolResult(True)
    with bound_request(HttpTimepointBinding(owner,sid,first)):
        result = run_scoped_tool(runtime.view,'query_metrics',{'metric_type':'dose_metrics','timepoint_id':second},execute)
        assert result.success and current_binding().timepoint_id == first
    runtime.close()


def test_planning_child_thread_keeps_submitted_timepoint_lock_identity(owned):
    from pathlib import Path
    from web.timepoint_http import HttpTimepointBinding, bound_request, current_binding, bucket_key, scoped_callable
    _, owner, sid, first, second, _ = owned
    values = []
    gate = threading.Event()
    def compute():
        assert gate.wait(5)
        values.append((current_binding().timepoint_id, bucket_key(sid)))
    with bound_request(HttpTimepointBinding(owner, sid, first)):
        captured = scoped_callable(compute)
    with bound_request(HttpTimepointBinding(owner, sid, second)):
        worker = threading.Thread(target=captured)
        worker.start()
        gate.set()
        worker.join(5)
        assert not worker.is_alive()
        assert current_binding().timepoint_id == second
    assert values == [(first, (owner, sid, first))]
    root = Path(__file__).resolve().parents[1]
    assert 'target=scoped_callable(_run)' in (root/'agent_runtime/chat_workflows.py').read_text()
    assert 'target=scoped_callable(_run_tool)' in (root/'agent_runtime/llm_runtime.py').read_text()


@pytest.mark.parametrize("tool", ["ctv_segmentation", "oar_segmentation", "planning_pipeline", "report_generator", "surgical_guide"])
def test_unqualified_mutation_publishes_only_captured_workspace(owned, monkeypatch, tool):
    store, owner, sid, first, second, root = owned
    runtime = activate(owned)
    def compute(view, name, params, **callbacks):
        assert view.config["_workspace_timepoint_id"] == first
        assert view.memory.retrieve("ct_path") is None
        view.memory.store("synthetic_artifact", {"operation": name})
        return ToolResult(True)
    monkeypatch.setattr(BrachyAgent, "_execute_tool_with_memory_unscoped", compute)
    result = runtime.view._execute_tool_with_memory(tool, {})
    assert result.success and result.metadata["published_to_timepoint"]
    assert store.load_timepoint_snapshot(owner, sid, first)["agent"]["planning_results"]["synthetic_artifact"]["operation"] == tool
    assert "synthetic_artifact" not in store.load_timepoint_snapshot(owner, sid, second)["agent"]["planning_results"]
    assert root.memory.retrieve("synthetic_artifact") is None
    runtime.close()


def test_failure_rolls_back_unpublished_work_before_next_tool(owned, monkeypatch):
    runtime = activate(owned)
    def fail(view, *args, **kwargs):
        view.memory.store("dose_metrics", {"v100": .999})
        return ToolResult(False, error="Synthetic failure")
    monkeypatch.setattr(BrachyAgent, "_execute_tool_with_memory_unscoped", fail)
    result = runtime.view._execute_tool_with_memory("planning_pipeline", {})
    assert not result.success
    assert runtime.view.memory.retrieve("dose_metrics")["v100"] == .81
    runtime.close()


def test_provider_id_cannot_silently_widen_humans_default_mutation_target(owned, monkeypatch):
    store, owner, sid, first, second, _ = owned
    runtime = activate(owned, language="zh")
    def must_not_run(*args, **kwargs):
        raise AssertionError("Mutation on an unconfirmed noncurrent target")
    monkeypatch.setattr(BrachyAgent, "_execute_tool_with_memory_unscoped", must_not_run)
    result = runtime.view._execute_tool_with_memory("planning_pipeline", {"timepoint_id": second})
    assert not result.success and result.metadata["code"] == "timepoint_target_confirmation_required"
    assert store.list_timepoints(owner, sid)["items"][first]["clinical_revision"] == 1
    assert store.list_timepoints(owner, sid)["items"][second]["clinical_revision"] == 1
    runtime.close()


def test_language_update_is_shared_not_a_new_clinical_revision(owned):
    store, owner, sid, first, _, root = owned
    runtime = activate(owned)
    runtime.before_tool()
    runtime.view.memory.store("session_language", {"code": "zh"})
    result = runtime.commit_tool(ToolResult(True))
    assert result.success and not result.metadata["published_to_timepoint"]
    assert store.list_timepoints(owner, sid)["items"][first]["clinical_revision"] == 1
    runtime.close()
    assert root.memory.retrieve("session_language") == {"code": "zh"}


def test_required_array_hydration_retains_current_turn_language(owned):
    runtime = activate(owned)
    runtime.view.memory.store("session_language", {"code": "zh"})
    runtime.before_tool("planning_pipeline", {})
    assert runtime.view._workspace_data_ready is True
    assert runtime.view.memory.retrieve("session_language") == {"code": "zh"}
    assert not runtime.view.memory.retrieve("ct_data").flags.writeable
    runtime.close()


def test_changed_input_rejects_old_computation_without_default_fallback(owned, monkeypatch):
    store, owner, sid, first, _, root = owned
    runtime = activate(owned, language="zh")
    other = WorkspaceStore(store.runtime_dir)
    def compute(view, *args, **kwargs):
        other.save_timepoint_results(owner, sid, first, {"changed_ct": True}, expected_clinical_revision=1)
        view.memory.store("synthetic_artifact", "stale")
        return ToolResult(True)
    monkeypatch.setattr(BrachyAgent, "_execute_tool_with_memory_unscoped", compute)
    result = runtime.view._execute_tool_with_memory("planning_pipeline", {})
    assert not result.success and result.metadata["code"] == "timepoint_conflict"
    assert "已变更" in result.error
    assert "synthetic_artifact" not in store.load_timepoint_snapshot(owner, sid, first)["agent"]["planning_results"]
    assert root.memory.retrieve("synthetic_artifact") is None
    runtime.close()


@pytest.mark.parametrize("tool", ["ui_controller", "ui_screenshot", "unknown_future_tool"])
def test_unadapted_tool_reports_not_executed_on_other_workspace(owned, tool):
    runtime = activate(owned, language="zh")
    result = runtime.view._execute_tool_with_memory(tool, {})
    assert not result.success and result.metadata["code"] == "timepoint_tool_not_ready"
    assert "未在其他时间点执行" in result.error
    runtime.close()


def test_same_output_name_is_scoped_and_input_paths_remain_case_owned(owned):
    _, _, _, first, second, root = owned
    a, b = activate(owned, first), activate(owned, second)
    with tool_scope(a.view.config):
        path_a = output_directory("reports", "unused-fallback") / "same-name.md"
        with pytest.raises(PermissionError):
            validate_tool_paths("report_generator", {"output_path": str(path_a.parent.parent.parent.parent / "outside.md")}, config=a.view.config)
    with tool_scope(b.view.config):
        path_b = output_directory("reports", "unused-fallback") / "same-name.md"
    assert path_a != path_b and first in str(path_a) and second in str(path_b)
    with pytest.raises(PermissionError):
        with tool_scope({"_workspace_root": root.config["_workspace_root"], "_workspace_output_root": "/not-in-this-case"}):
            pass
    assert workspace_root() is None
    a.close(); b.close()


def test_retries_do_not_rebind_one_request_id_to_a_new_target(owned):
    store, owner, sid, first, second, root = owned
    manager, gate = ChatTaskManager(), threading.Event()
    a = capture_chat_scope(store, owner, sid, first)
    b = capture_chat_scope(store, owner, sid, second)
    task = manager.start(SimpleNamespace(app_context=lambda: __import__('contextlib').nullcontext()),
        owner, sid, root, "Synthetic request", {}, request_id="stable", timepoint_scope=a, start_gate=gate)
    assert manager.start(None, owner, sid, root, "Synthetic request", {}, request_id="stable", timepoint_scope=a) is task
    with pytest.raises(RuntimeError, match="different target"):
        manager.start(None, owner, sid, root, "Synthetic request", {}, request_id="stable", timepoint_scope=b)
    manager.cancel(task); gate.set()
    assert task.wait_for_worker(timeout=3)


def test_task_runs_selected_view_and_finalizer_retains_captured_view_until_flush(owned, monkeypatch):
    store, owner, sid, first, _, root = owned
    def stream(view, message):
        assert view is not root and view.memory.retrieve("dose_metrics")["v100"] == .81
        view.memory.add_message("user", message)
        yield 'event: response\ndata: {"response":"Synthetic scoped answer"}\n\n'
        yield 'event: done\ndata: {}\n\n'
    monkeypatch.setattr(BrachyAgent, "chat_with_stream", stream)
    finalized = []
    task = ChatTaskManager().start(SimpleNamespace(app_context=lambda: __import__('contextlib').nullcontext()),
        owner, sid, root, "Synthetic question", {}, request_id="named-turn",
        timepoint_scope=capture_chat_scope(store, owner, sid, first), on_finish=lambda task: finalized.append(task.agent))
    assert task.wait_for_worker(timeout=3)
    assert task.status == "completed" and len(finalized) == 1
    assert finalized[0] is not root
    assert finalized[0].config["_workspace_timepoint_id"] == first
    assert task.agent is root and root.memory.conversation[-1]["content"] == "Synthetic question"
    assert root.memory.retrieve("dose_metrics")["v100"] == .11
    assert task.public_state()["timepoint_id"] == first
    assert all(json.loads(event.split("data: ")[1])["timepoint_id"] == first for event in task.iter_events())


@pytest.mark.parametrize('streaming', [True, False])
def test_real_authenticated_chat_route_reads_named_target_and_scopes_old_metrics_api(tmp_path, monkeypatch, streaming):
    import time
    from test_case_archive_active_use import _build_app
    monkeypatch.delenv("BRACHYBOT_API_KEY", raising=False)
    monkeypatch.delenv("BRACHYBOT_REQUIRE_API_KEY", raising=False)
    app = _build_app(tmp_path, monkeypatch)
    client = app.test_client()
    auth = client.post("/api/auth/register", json={"username": "scope_route", "password": "synthetic-password-123"}).get_json()
    owner, sid = auth["user"]["id"], auth["active_session_id"]
    store = app.extensions["brachybot_workspace_store"]
    target = store.create_timepoint(owner, sid, "Target scan", expected_revision=0)["created_timepoint_id"]
    store.save_timepoint_results(owner, sid, target, {"dose_metrics": {"v100": .87}}, expected_state_revision=0)
    root = object.__new__(BrachyAgent)
    root.memory = AgentMemory(sid)
    root.memory.store("dose_metrics", {"v100": .12})
    root.config = {"_workspace_owner_id": owner, "_workspace_session_id": sid, "_workspace_root": str(store.workspace_root(owner, sid))}
    root._workspace_store, root._workspace_data_ready, root._brain_available = store, True, False
    root.registry = ToolRegistry(); root.registry.register(QueryMetricsTool())
    root.run_ledger = RunLedger(); root.tool_gateway = ToolCallGateway(root.run_ledger)
    def stream(view, message):
        result = view._execute_tool_with_memory("query_metrics", {"metric_type": "dose_metrics"})
        assert result.success and result.data["V100"] == .87
        yield 'event: response\ndata: {"response":"Read the selected scan: 87%"}\n\n'
        yield 'event: done\ndata: {}\n\n'
    monkeypatch.setattr(BrachyAgent, "chat_with_stream", stream)
    sessions, timestamps, lock = app.extensions["brachybot_agent_cache"]
    with lock:
        sessions[(owner, sid)] = root; timestamps[(owner, sid)] = time.time()
    headers = {"X-CSRF-Token": auth["csrf_token"], "X-BrachyBot-Session": sid, "X-BrachyBot-Timepoint": target}
    response = client.post("/api/chat", headers=headers, json={"message": "What is the current dose?", "stream": streaming, "timepoint_id": target})
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Read the selected scan: 87%' in body and target in body
    assert root.memory.retrieve("dose_metrics")["v100"] == .12
    assert store.list_timepoints(owner, sid)["capabilities"]["execution_scope"] is True
    metrics = client.get("/api/planning/results", headers=headers)
    assert metrics.status_code == 200, metrics.get_json()
    assert metrics.headers['X-BrachyBot-Timepoint'] == target
    assert metrics.get_json()['metrics']['v100'] == .87
    assert root.memory.retrieve("dose_metrics")["v100"] == .12
