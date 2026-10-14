"""Real store/runtime integration; synthetic volumes, no mocked clinical output."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest

from agent_runtime.core import AgentMemory
from web.timepoint_chat import ScopedChatRuntime, capture_chat_scope
from web.timepoint_http import (HttpTimepointBinding, ScopedHttpRuntime,
    ScopedWorkspaceStore, bound_request, bucket_key, scoped_callable)
from web.timepoints import TimepointConflict, default_timepoint_id
from web.workspace_store import WorkspaceStore


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    raw = WorkspaceStore(tmp_path / "runtime")
    owner = raw.create_user("runtime_owner", "synthetic-hash")["id"]
    sid = raw.create_session(owner, "Synthetic patient").id
    raw.save_agent_results_delta(owner, sid, {"ct_data": np.zeros((4, 5, 6), np.int16),
        "ct_spacing": (1., 2., 3.), "ct_origin": (0., 0., 0.),
        "ct_direction": (1., 0., 0., 0., 1., 0., 0., 0., 1.),
        "dose_metrics": {"v100": .81}}, expected_revision=0)
    raw.save_snapshot_patch(owner, sid, {"ui": {"state": {"color": "#22D3EE", "opacity": .37}},
        "report": {"form": {"title": "Original report"}},
        "chat": {"messages": [{"id": "original", "type": "user", "content": "Shared history"}]}})
    control = SimpleNamespace(memory=AgentMemory(sid), config={"_workspace_owner_id": owner,
        "_workspace_session_id": sid, "_workspace_root": str(raw.workspace_root(owner, sid))},
        _workspace_store=raw, _workspace_data_ready=True)
    catalog = raw.migrate_default_timepoint(owner, sid)
    tid = catalog["default_timepoint_id"]
    return raw, owner, sid, tid, control


def test_real_default_migration_is_idempotent_preserves_all_state_and_shared_chat(migrated):
    raw, owner, sid, tid, _ = migrated
    before = raw.load_timepoint_snapshot(owner, sid, tid, decode_arrays=True)
    assert before["timepoint"]["legacy_default"] is False
    assert before["ui"]["state"] == {"color": "#22D3EE", "opacity": .37}
    assert before["agent"]["planning_results"]["ct_data"].shape == (4, 5, 6)
    assert before["chat"]["messages"][0]["content"] == "Shared history"
    catalog = raw.list_timepoints(owner, sid)
    assert catalog["capabilities"]["execution_scope"] is True
    assert raw.migrate_default_timepoint(owner, sid) == raw.list_timepoints(owner, sid, include_trashed=True)
    assert raw.list_timepoints(owner, sid)["catalog_revision"] == catalog["catalog_revision"]
    raw.save_snapshot_patch(owner, sid, {"chat": {"messages": [{"id": "new", "type": "user", "content": "Another turn"}]}})
    assert raw.load_timepoint_snapshot(owner, sid, tid)["timepoint_clinical_revision"] == before["timepoint_clinical_revision"]


def test_chat_and_display_saves_do_not_invalidate_default_clinical_job(migrated):
    raw, owner, sid, tid, _ = migrated
    context = raw.capture_timepoint_context(owner, sid, tid)
    target = ScopedWorkspaceStore(raw, HttpTimepointBinding(owner, sid, tid))
    target.save_snapshot_patch(owner, sid, {"ui": {"state": {"opacity": .2}}})
    target.save_snapshot_patch(owner, sid, {"chat": {"messages": [{"id": "note", "type": "user", "content": "Note"}]}})
    raw.save_timepoint_results(owner, sid, tid, {"dose_metrics": {"v100": .82}},
        expected_clinical_revision=context.target.clinical_revision, execution_context=context)
    assert target.load_snapshot(owner, sid)["ui"]["state"]["color"] == "#22D3EE"
    assert target.load_snapshot(owner, sid)["agent"]["planning_results"]["dose_metrics"]["v100"] == .82


def test_old_store_contract_writes_only_captured_target_not_later_navigation(migrated):
    raw, owner, sid, tid, _ = migrated
    current = raw.list_timepoints(owner, sid)
    other = raw.create_timepoint(owner, sid, "Later scan", expected_revision=current["catalog_revision"])["created_timepoint_id"]
    old_store = ScopedWorkspaceStore(raw, HttpTimepointBinding(owner, sid, tid))
    with bound_request(HttpTimepointBinding(owner, sid, other)):
        old_store.save_agent_results_patch(owner, sid, {"dose_metrics": {"v100": .86}})
        old_store.save_ui_bridge(owner, sid, {"training": {"active": True, "run_id": "origin-run"}})
    assert raw.load_timepoint_snapshot(owner, sid, tid)["agent"]["planning_results"]["dose_metrics"]["v100"] == .86
    assert not raw.load_timepoint_snapshot(owner, sid, other)["agent"]["planning_results"]
    assert not (raw.load_timepoint_snapshot(owner, sid, other).get("ui") or {}).get("bridge")
    stranger = raw.create_session(owner, "Different patient")
    with pytest.raises(TimepointConflict):
        old_store.load_snapshot(owner, stranger.id)


def test_runtime_hydrates_default_and_publishes_delta_without_root_pollution(migrated):
    raw, owner, sid, tid, control = migrated
    runtime = ScopedHttpRuntime(control, HttpTimepointBinding(owner, sid, tid))
    assert runtime.view.memory.retrieve("ct_data").shape == (4, 5, 6)
    runtime.view.memory.store("dose_metrics", {"v100": .95})
    runtime.checkpoint()
    assert raw.load_timepoint_snapshot(owner, sid, tid)["agent"]["planning_results"]["dose_metrics"]["v100"] == .95
    assert raw.load_snapshot(owner, sid)["agent"]["planning_results"]["dose_metrics"]["v100"] == .81
    runtime.close()


def test_cold_runtime_never_inherits_another_views_ct_ready_or_failure_flags(migrated,monkeypatch):
    import threading
    import web.workspace_store as persistence
    raw,owner,sid,tid,control=migrated
    entered,release=threading.Event(),threading.Event()
    decode=persistence._decode_artifacts
    def gated_decode(*args,**kwargs):
        entered.set()
        assert release.wait(10),'Test did not release the real decoder'
        return decode(*args,**kwargs)
    monkeypatch.setattr(persistence,'_decode_artifacts',gated_decode)
    control._workspace_ct_ready=True
    control._workspace_hydration_error='Failure belonging to a previous view'
    runtime=ScopedHttpRuntime(control,HttpTimepointBinding(owner,sid,tid),lightweight=True)
    try:
        assert entered.wait(5)
        assert runtime.view._workspace_ct_ready is False
        assert not runtime.view._workspace_hydration_error
        assert runtime.view.memory.retrieve('ct_data') is None
    finally:release.set()
    runtime.hydrate(True)
    assert runtime.view._workspace_ct_ready is True
    assert runtime.view.memory.retrieve('ct_data').shape==(4,5,6)
    runtime.close(commit=False)


def test_default_delete_removes_its_graph_and_leaves_a_new_empty_workspace(migrated):
    raw, owner, sid, tid, _ = migrated
    catalog = raw.list_timepoints(owner, sid)
    deleted = raw.delete_timepoint(owner, sid, tid, expected_revision=catalog["catalog_revision"])
    assert deleted["items"][tid]["status"] == "trashed"
    blank = deleted["default_timepoint_id"]
    assert blank != tid and not raw.load_timepoint_snapshot(owner, sid, blank)["agent"]["planning_results"]
    assert raw.load_timepoint_snapshot(owner, sid, blank)["chat"]["messages"]
    with pytest.raises(Exception):
        raw.load_timepoint_snapshot(owner, sid, tid)


def test_monitor_bucket_and_worker_identity_are_owned_by_scan(migrated):
    raw, owner, sid, tid, _ = migrated
    other = "f" * 32
    with bound_request(HttpTimepointBinding(owner, sid, tid)):
        expected = bucket_key(sid)
        worker = scoped_callable(lambda: bucket_key(sid))
    with bound_request(HttpTimepointBinding(owner, sid, other)):
        assert bucket_key(sid) != expected
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(worker).result() == expected


def test_shared_accounting_persists_without_changing_any_timepoint_clinical_revision(migrated):
    raw, owner, sid, tid, _ = migrated
    before = raw.capture_timepoint_context(owner, sid, tid)
    raw.save_shared_agent_control(owner, sid, {"context_summary": "Shared across scans", "compaction_count": 1,
        "context_accounting": {"active_tokens": 1200}, "conversation": [{"role": "user", "content": "Shared input"}]})
    restarted = WorkspaceStore(raw.runtime_dir)
    state = restarted.load_timepoint_snapshot(owner, sid, tid)
    assert state["agent"]["context_summary"] == "Shared across scans"
    assert state["agent"]["context_accounting"]["active_tokens"] == 1200
    before.assert_current(owner, sid, restarted._timepoint_catalog(owner, sid),
        legacy_revision=restarted.get_session(owner, sid).revision)


def test_old_viewer_close_cannot_reset_new_chat_accounting_or_confirmation(migrated):
    raw, owner, sid, tid, control = migrated
    runtime = ScopedHttpRuntime(control, HttpTimepointBinding(owner, sid, tid))
    control.memory.context_accounting = {"active_tokens": 9900}
    control.memory.context_summary = "Updated by the new chat"
    control._pending_execution_confirmation = "new-human-receipt"
    runtime.close(commit=False)
    assert control.memory.context_accounting["active_tokens"] == 9900
    assert control.memory.context_summary == "Updated by the new chat"
    assert control._pending_execution_confirmation == "new-human-receipt"


def test_operation_checkpoint_is_small_independent_and_recovery_is_pid_fenced(migrated):
    import uuid
    raw, owner, sid, tid, _ = migrated
    context = raw.capture_timepoint_context(owner, sid, tid)
    operation_id = uuid.uuid4().hex
    raw.save_timepoint_operation(owner, sid, tid, operation_id, {"state": "running", "checkpoint": {"kind": "dose"}})
    assert raw.load_timepoint_snapshot(owner, sid, tid)["operation"]["operation_id"] == operation_id
    context.assert_current(owner, sid, raw._timepoint_catalog(owner, sid), legacy_revision=raw.get_session(owner, sid).revision)
    with pytest.raises(TimepointConflict):
        raw.save_timepoint_operation(owner, sid, tid, uuid.uuid4().hex, {"state": "running"})
    with raw._connection() as connection:
        connection.execute("UPDATE timepoint_operations SET process_start='obsolete-worker' WHERE operation_id=?", (operation_id,))
    restarted = WorkspaceStore(raw.runtime_dir)
    assert restarted.load_timepoint_snapshot(owner, sid, tid)["operation"]["state"] == "interrupted"
    assert restarted.load_timepoint_snapshot(owner, sid, tid, decode_arrays=True)["agent"]["planning_results"]["ct_data"].shape == (4, 5, 6)
