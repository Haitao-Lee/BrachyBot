"""Focused persistence and ownership tests for durable case workspaces."""

from __future__ import annotations

import threading
from io import BytesIO
from types import SimpleNamespace

import numpy as np

from web.workspace_store import WorkspaceLeaseConflict, WorkspaceNotFound, WorkspaceQuotaExceeded, WorkspaceStore


class _Memory:
    def __init__(self):
        self._lock = threading.RLock()
        self.planning_results = {
            "ct_path": "inputs/study.nii",
            "ct_data": np.arange(12, dtype=np.int16).reshape(3, 2, 2),
            "dose_distribution_gy": np.ones((3, 2, 2), dtype=np.float32),
            "seed_plan_serialized": {"seeds": [[1.0, 2.0, 3.0]]},
        }
        self._planning_versions = {key: 1 for key in self.planning_results}
        self.patient_data = {"site": "pancreas"}
        self.conversation = [{"role": "user", "content": "plan this case"}]
        self.tool_results = [{"tool": "ctv_segmentation", "success": True}]
        self.context_summary = "summary"
        self.compaction_count = 1
        self.current_phase = SimpleNamespace(value="planning")
        self.conversation_state = {"ctv_segmented": True}
        self.user_lang = "en"
        self._ui_state = {"planning": {"reference_direc": [0, 1, 0]}}

    def get_ui_state(self):
        return self._ui_state

    def retrieve(self, key, default=None):
        return self.planning_results.get(key, default)


class _Agent:
    def __init__(self):
        self.config = {"mode": "rule_based"}
        self.memory = _Memory()


def test_workspace_snapshot_round_trip_preserves_arrays_and_ui(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("planner", "hash")
    case = store.create_session(user["id"], "Pancreas case")
    agent = _Agent()

    saved = store.snapshot_agent(user["id"], case.id, agent, reason="test")
    assert saved["agent"]["planning_results"]["ct_data"]["$array"].endswith(".npy")
    store.save_snapshot_patch(user["id"], case.id, {
        "ui": {"state": {"viewer": {"slices": {"axial": 12}}, "data_tree": {"organs": [{"name": "aorta"}]}}},
        "report": {"form": {"version": 3, "case": {"tumorType": "pancreas"}}},
        "chat": {"messages": [{"type": "bot", "content": "ready"}]},
    })

    restored = _Agent()
    store.hydrate_agent(user["id"], case.id, restored)
    assert np.array_equal(restored.memory.retrieve("ct_data"), agent.memory.retrieve("ct_data"))
    assert restored.memory.retrieve("seed_plan_serialized")["seeds"] == [[1.0, 2.0, 3.0]]
    snapshot = store.load_snapshot(user["id"], case.id)
    assert snapshot["ui"]["state"]["viewer"]["slices"]["axial"] == 12
    assert snapshot["chat"]["messages"][0]["content"] == "ready"


def test_workspace_ownership_trash_and_lease_boundaries(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    first = store.create_user("first_user", "hash")
    second = store.create_user("second_user", "hash")
    case = store.create_session(first["id"], "Private case")

    try:
        store.get_session(second["id"], case.id)
        assert False, "cross-account access must fail"
    except WorkspaceNotFound:
        pass

    store.acquire_lease(first["id"], case.id, "a" * 20)
    try:
        store.assert_editable(first["id"], case.id, "b" * 20)
        assert False, "another editor token must be rejected"
    except WorkspaceLeaseConflict:
        pass
    store.assert_editable(first["id"], case.id, "a" * 20)
    takeover = store.acquire_lease(first["id"], case.id, "b" * 20, force=True)
    assert takeover["editable"] is True
    assert takeover["taken_over"] is True
    try:
        store.assert_editable(first["id"], case.id, "a" * 20)
        assert False, "the previous editor must lose write ownership after takeover"
    except WorkspaceLeaseConflict:
        pass

    store.move_to_trash(first["id"], case.id)
    assert store.get_session(first["id"], case.id, include_trashed=True).status == "trashed"
    restored = store.restore_from_trash(first["id"], case.id)
    assert restored.status == "active"


def test_running_operation_is_marked_interrupted_after_restart(tmp_path):
    runtime = tmp_path / "runtime"
    store = WorkspaceStore(runtime)
    user = store.create_user("restart_user", "hash")
    case = store.create_session(user["id"], "Interrupted case")
    agent = _Agent()
    store.mark_operation(user["id"], case.id, agent, {
        "state": "running",
        "message": "Dose calculation is in progress",
        "checkpoint": {"step": "dose_calc"},
    })

    restarted = WorkspaceStore(runtime)
    snapshot = restarted.load_snapshot(user["id"], case.id)
    assert snapshot["operation"]["state"] == "interrupted"
    assert snapshot["operation"]["checkpoint"]["step"] == "dose_calc"


def test_checkpoint_reuses_unchanged_arrays_and_prunes_replaced_versions(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("array_owner", "hash")
    case = store.create_session(user["id"], "Array case")
    agent = _Agent()

    store.snapshot_agent(user["id"], case.id, agent, reason="initial")
    arrays_dir = store.workspace_root(user["id"], case.id) / "arrays"
    initial = sorted(path.name for path in arrays_dir.glob("*.npy"))
    assert len(initial) == 2

    # UI/chat checkpoints must not duplicate unchanged clinical volumes.
    store.snapshot_agent(user["id"], case.id, agent, reason="unchanged")
    assert sorted(path.name for path in arrays_dir.glob("*.npy")) == initial

    # Planning code replaces arrays through AgentMemory.store, advancing the
    # version and allowing the old sidecar to be reclaimed after commit.
    agent.memory.planning_results["dose_distribution_gy"] = np.full((3, 2, 2), 2.0, dtype=np.float32)
    agent.memory._planning_versions["dose_distribution_gy"] += 1
    store.snapshot_agent(user["id"], case.id, agent, reason="dose_updated")
    assert len(list(arrays_dir.glob("*.npy"))) == 2
    restored = _Agent()
    store.hydrate_agent(user["id"], case.id, restored)
    assert float(restored.memory.retrieve("dose_distribution_gy").max()) == 2.0


def test_generated_artifacts_apply_replacement_aware_account_quota(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("quota_owner", "hash")
    case = store.create_session(user["id"], "Quota case")
    quota = store.user_storage_bytes(user["id"]) + 24
    with store._connection() as connection:
        connection.execute("UPDATE users SET storage_quota_bytes = ? WHERE id = ?", (quota, user["id"]))

    store.write_artifact(user["id"], case.id, "reports", "small.txt", BytesIO(b"small"))
    try:
        store.write_artifact(user["id"], case.id, "reports", "large.txt", BytesIO(b"x" * 128))
        assert False, "the second generated artifact should exceed the account quota"
    except WorkspaceQuotaExceeded:
        pass
    assert not (store.workspace_root(user["id"], case.id) / "artifacts" / "reports" / "large.txt").exists()


def test_case_audit_and_review_comments_are_owned_and_persistent(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    owner = store.create_user("review_owner", "hash")
    other = store.create_user("review_other", "hash")
    case = store.create_session(owner["id"], "Review case")

    comment = store.add_review_comment(
        owner["id"], case.id, "review_owner", "Verify the independent dose calculation.",
        {"panel": "dvh", "structure": "CTV"},
    )
    assert comment["status"] == "open"
    assert comment["anchor"]["structure"] == "CTV"
    updated = store.update_review_comment(owner["id"], case.id, comment["id"], status="resolved")
    assert updated["status"] == "resolved"

    events = store.list_audit_events(owner["id"], case.id)
    assert any(event["action"] == "review.comment_added" for event in events)
    assert any(event["action"] == "review.comment_updated" for event in events)
    try:
        store.list_review_comments(other["id"], case.id)
        assert False, "another account must not read review comments"
    except WorkspaceNotFound:
        pass
