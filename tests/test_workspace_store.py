"""Focused persistence and ownership tests for durable case workspaces."""

from __future__ import annotations

import logging
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
            "ctv_array": np.array(
                [[[0, 1], [0, 0]], [[0, 1], [1, 0]], [[0, 0], [0, 0]]],
                dtype=np.uint8,
            ),
            "oar_array": np.array(
                [[[0, 0], [2, 0]], [[0, 0], [0, 3]], [[0, 0], [0, 0]]],
                dtype=np.uint16,
            ),
            "oar_label_map": {
                "2": {"name": "stomach", "category": "traversable"},
                "3": {"name": "vertebrae_L1", "category": "non_traversable"},
            },
            "dose_distribution_gy": np.ones((3, 2, 2), dtype=np.float32),
            "dose_metrics": {"v100": 91.2, "d90": 123.4},
            "dvh_data": {
                "CTV": {"dose": [0.0, 120.0, 240.0], "volume": [100.0, 91.2, 40.0]},
                "stomach": {"dose": [0.0, 120.0], "volume": [100.0, 3.5]},
            },
            "trajectories": [
                {"id": "needle_0", "entry": [1.0, 2.0, 30.0], "target": [1.0, 2.0, 3.0]},
            ],
            "seed_plan_serialized": {
                "seeds": [[1.0, 2.0, 3.0]],
                "needles": [{"id": "needle_0", "seed_indices": [0]}],
            },
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
    assert np.array_equal(restored.memory.retrieve("ctv_array"), agent.memory.retrieve("ctv_array"))
    assert np.array_equal(restored.memory.retrieve("oar_array"), agent.memory.retrieve("oar_array"))
    assert restored.memory.retrieve("seed_plan_serialized")["seeds"] == [[1.0, 2.0, 3.0]]
    restored_label_map = restored.memory.retrieve("oar_label_map")
    vertebra_label = restored_label_map.get(3, restored_label_map.get("3"))
    assert vertebra_label["name"] == "vertebrae_L1"
    assert restored.memory.retrieve("dose_metrics")["v100"] == 91.2
    assert restored.memory.retrieve("dvh_data")["CTV"]["volume"][1] == 91.2
    assert restored.memory.retrieve("trajectories")[0]["id"] == "needle_0"
    snapshot = store.load_snapshot(user["id"], case.id)
    assert snapshot["ui"]["state"]["viewer"]["slices"]["axial"] == 12
    assert snapshot["ui"]["state"]["data_tree"]["organs"][0]["name"] == "aorta"
    assert snapshot["report"]["form"]["case"]["tumorType"] == "pancreas"
    assert snapshot["chat"]["messages"][0]["content"] == "ready"


def test_chat_snapshot_patches_are_append_only(tmp_path):
    """A stale browser patch must not erase a detached task transcript."""
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("chat_owner", "hash")
    case = store.create_session(user["id"], "Chat case")
    first = {"type": "user", "content": "first", "timestamp": 1000}
    second = {"type": "bot-response", "content": "answer", "timestamp": 2000}

    store.save_snapshot_patch(user["id"], case.id, {"chat": {"messages": [first]}})
    # This resembles a backgrounded browser sending its old full array after
    # the detached worker has already appended the answer.
    store.save_snapshot_patch(user["id"], case.id, {"chat": {"messages": [second]}})

    messages = store.load_snapshot(user["id"], case.id)["chat"]["messages"]
    assert [message["content"] for message in messages] == ["first", "answer"]


def test_chat_snapshot_updates_merge_by_stable_message_identity(tmp_path):
    """Screenshot, Trace, and final text updates must remain one reply."""
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("stable_chat_owner", "hash")
    case = store.create_session(user["id"], "Screenshot case")
    initial = {
        "id": "assistant-request-1",
        "request_id": "request-1",
        "type": "bot-response",
        "content": "",
        "timestamp": 2000,
        "attachments": [{
            "id": "shot-1",
            "url": "/api/sessions/case/screenshots/one.png",
        }],
    }
    completed = {
        "id": "assistant-request-1",
        "request_id": "request-1",
        "type": "bot-response",
        "content": "剂量截图分析完成。",
        "timestamp": 3000,
        "attachments": [{
            "id": "shot-1",
            "url": "/api/sessions/case/screenshots/one.png",
        }],
    }
    trace_initial = {
        "id": "trace-request-1",
        "request_id": "request-1",
        "type": "thinking",
        "content": "",
        "timestamp": 2000,
        "steps": [{"id": "screenshot-plan", "status": "pending"}],
    }
    trace_completed = {
        "id": "trace-request-1",
        "request_id": "request-1",
        "type": "thinking",
        "content": "",
        "timestamp": 3000,
        "steps": [{"id": "screenshot-plan", "status": "done"}],
    }

    store.save_snapshot_patch(
        user["id"],
        case.id,
        {"chat": {"messages": [initial, trace_initial]}},
    )
    store.save_snapshot_patch(
        user["id"],
        case.id,
        {"chat": {"messages": [completed, trace_completed]}},
    )

    messages = store.load_snapshot(user["id"], case.id)["chat"]["messages"]
    assert len(messages) == 2
    assistant = next(message for message in messages if message["type"] == "bot-response")
    trace = next(message for message in messages if message["type"] == "thinking")
    assert assistant["content"] == "剂量截图分析完成。"
    assert [item["id"] for item in assistant["attachments"]] == ["shot-1"]
    assert trace["steps"] == [{"id": "screenshot-plan", "status": "done"}]
    assert assistant["timestamp"] == 2000
    assert trace["timestamp"] == 2000


def test_two_case_workspaces_round_trip_without_cross_case_contamination(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("multi_case_planner", "hash")
    first_case = store.create_session(user["id"], "Case A")
    second_case = store.create_session(user["id"], "Case B")

    first = _Agent()
    first.memory.planning_results["ct_path"] = "inputs/case_a.nii"
    first.memory.planning_results["ct_data"] = np.full((3, 2, 2), 11, dtype=np.int16)
    first.memory.planning_results["ctv_array"] = np.full((3, 2, 2), 1, dtype=np.uint8)
    first.memory.planning_results["oar_array"] = np.full((3, 2, 2), 2, dtype=np.uint16)
    first.memory.planning_results["dose_distribution_gy"] = np.full((3, 2, 2), 120, dtype=np.float32)
    first.memory.planning_results["dose_metrics"] = {"v100": 91.0, "d90": 123.0}
    first.memory.planning_results["seed_plan_serialized"] = {"seeds": [[1, 2, 3]]}
    first.memory.patient_data = {"site": "pancreas", "case": "A"}

    second = _Agent()
    second.memory.planning_results["ct_path"] = "inputs/case_b.nii"
    second.memory.planning_results["ct_data"] = np.full((4, 2, 2), 22, dtype=np.int16)
    second.memory.planning_results["ctv_array"] = np.full((4, 2, 2), 4, dtype=np.uint8)
    second.memory.planning_results["oar_array"] = np.full((4, 2, 2), 5, dtype=np.uint16)
    second.memory.planning_results["dose_distribution_gy"] = np.full((4, 2, 2), 240, dtype=np.float32)
    second.memory.planning_results["dose_metrics"] = {"v100": 82.0, "d90": 105.0}
    second.memory.planning_results["seed_plan_serialized"] = {"seeds": [[9, 8, 7], [6, 5, 4]]}
    second.memory.patient_data = {"site": "liver", "case": "B"}

    store.snapshot_agent(user["id"], first_case.id, first, reason="case_a.plan")
    store.save_snapshot_patch(user["id"], first_case.id, {
        "ui": {"state": {
            "viewer": {"slices": {"axial": 7}, "settings": {"layout": "3d-top"}},
            "data_tree": {"organs": [{"id": "a-stomach", "name": "stomach", "visible": True}]},
            "controls": {"ctPath": {"value": "case-a-display"}},
        }},
        "report": {"form": {"version": 3, "case": {"caseId": "A"}}},
        "chat": {
            "messages": [{"type": "user", "content": "plan case A"}],
            "task_id": "task-a",
            "task_status": "running",
        },
        "operation": {"state": "running", "checkpoint": {"step": "dose_calc"}},
    })
    store.snapshot_agent(user["id"], second_case.id, second, reason="case_b.plan")
    store.save_snapshot_patch(user["id"], second_case.id, {
        "ui": {"state": {
            "viewer": {"slices": {"axial": 13}, "settings": {"layout": "grid"}},
            "data_tree": {"organs": [{"id": "b-liver", "name": "liver", "visible": False}]},
            "controls": {"ctPath": {"value": "case-b-display"}},
        }},
        "report": {"form": {"version": 3, "case": {"caseId": "B"}}},
        "chat": {
            "messages": [{"type": "user", "content": "plan case B"}],
            "task_id": "task-b",
            "task_status": "done",
        },
        "operation": {"state": "ready", "checkpoint": {"step": "report"}},
    })

    restored_a = _Agent()
    restored_b = _Agent()
    store.hydrate_agent(user["id"], first_case.id, restored_a)
    store.hydrate_agent(user["id"], second_case.id, restored_b)
    snapshot_a = store.load_snapshot(user["id"], first_case.id)
    snapshot_b = store.load_snapshot(user["id"], second_case.id)

    assert restored_a.memory.patient_data["case"] == "A"
    assert restored_b.memory.patient_data["case"] == "B"
    assert restored_a.memory.retrieve("ct_data").shape == (3, 2, 2)
    assert restored_b.memory.retrieve("ct_data").shape == (4, 2, 2)
    assert float(restored_a.memory.retrieve("dose_distribution_gy").max()) == 120.0
    assert float(restored_b.memory.retrieve("dose_distribution_gy").max()) == 240.0
    assert len(restored_a.memory.retrieve("seed_plan_serialized")["seeds"]) == 1
    assert len(restored_b.memory.retrieve("seed_plan_serialized")["seeds"]) == 2
    assert snapshot_a["ui"]["state"]["viewer"]["slices"]["axial"] == 7
    assert snapshot_b["ui"]["state"]["viewer"]["slices"]["axial"] == 13
    assert snapshot_a["ui"]["state"]["data_tree"]["organs"][0]["name"] == "stomach"
    assert snapshot_b["ui"]["state"]["data_tree"]["organs"][0]["name"] == "liver"
    assert snapshot_a["report"]["form"]["case"]["caseId"] == "A"
    assert snapshot_b["report"]["form"]["case"]["caseId"] == "B"
    assert snapshot_a["chat"]["task_id"] == "task-a"
    assert snapshot_b["chat"]["task_id"] == "task-b"
    assert snapshot_a["operation"]["checkpoint"]["step"] == "dose_calc"
    assert snapshot_b["operation"]["checkpoint"]["step"] == "report"


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
    assert len(initial) == 4

    # UI/chat checkpoints must not duplicate unchanged clinical volumes.
    store.snapshot_agent(user["id"], case.id, agent, reason="unchanged")
    assert sorted(path.name for path in arrays_dir.glob("*.npy")) == initial

    # Planning code replaces arrays through AgentMemory.store, advancing the
    # version and allowing the old sidecar to be reclaimed after commit.
    agent.memory.planning_results["dose_distribution_gy"] = np.full((3, 2, 2), 2.0, dtype=np.float32)
    agent.memory._planning_versions["dose_distribution_gy"] += 1
    store.snapshot_agent(user["id"], case.id, agent, reason="dose_updated")
    assert len(list(arrays_dir.glob("*.npy"))) == 4
    restored = _Agent()
    store.hydrate_agent(user["id"], case.id, restored)
    assert float(restored.memory.retrieve("dose_distribution_gy").max()) == 2.0


def test_checkpoint_reuses_nested_arrays_after_restart_and_logs_stages(tmp_path, caplog):
    """Restart checkpoints must not rewrite unchanged per-organ mask arrays."""
    runtime = tmp_path / "runtime"
    store = WorkspaceStore(runtime)
    user = store.create_user("nested_owner", "hash")
    case = store.create_session(user["id"], "Nested masks")

    def make_agent():
        agent = _Agent()
        agent.memory.planning_results["oar_array"] = {
            "stomach": np.ones((3, 2, 2), dtype=np.uint8),
            "vertebrae_L1": np.full((3, 2, 2), 2, dtype=np.uint8),
        }
        agent.memory._planning_versions["oar_array"] = 1
        return agent

    first = make_agent()
    with caplog.at_level(logging.INFO, logger="web.workspace_store"):
        store.snapshot_agent(user["id"], case.id, first, reason="nested.initial")
    arrays_dir = store.workspace_root(user["id"], case.id) / "arrays"
    initial = sorted(path.name for path in arrays_dir.glob("*.npy"))

    restarted = WorkspaceStore(runtime)
    with caplog.at_level(logging.INFO, logger="web.workspace_store"):
        restarted.snapshot_agent(user["id"], case.id, make_agent(), reason="nested.restart")
    assert sorted(path.name for path in arrays_dir.glob("*.npy")) == initial
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "workspace checkpoint started" in messages
    assert "workspace checkpoint capacity scanned" in messages
    assert "workspace checkpoint artifacts encoded" in messages
    assert "workspace checkpoint prepared" in messages
    assert "workspace checkpoint snapshot written" in messages
    assert "workspace checkpoint artifacts committed" in messages
    assert "workspace checkpoint completed" in messages
    assert "arrays_reused=5" in messages


def test_upload_stream_checks_account_capacity_once_not_per_chunk(tmp_path, monkeypatch):
    """Large CT uploads must not recursively scan old case artifacts per MiB."""
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("upload_owner", "hash")
    case = store.create_session(user["id"], "Upload case")
    calls = 0
    original = store.user_storage_bytes

    def counted(user_id):
        nonlocal calls
        calls += 1
        return original(user_id)

    monkeypatch.setattr(store, "user_storage_bytes", counted)
    payload = b"x" * (3 * 1024 * 1024 + 17)
    path = store.write_upload(user["id"], case.id, "ct.nii", BytesIO(payload), expected_bytes=len(payload))

    assert path.read_bytes() == payload
    assert calls == 1


def test_checkpoint_drops_large_candidate_trajectory_workspace(tmp_path):
    """Thousands of optimizer candidates are regenerated, not session state."""
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("candidate_owner", "hash")
    case = store.create_session(user["id"], "Candidate case")
    agent = _Agent()
    agent.memory.planning_results["trajectories"] = [
        {"point": np.zeros(3, dtype=np.float32), "direction": np.ones(3, dtype=np.float32)}
        for _ in range(300)
    ]
    agent.memory._planning_versions["trajectories"] = 1

    snapshot = store.snapshot_agent(user["id"], case.id, agent, reason="candidate.workspace")
    assert "trajectories" not in snapshot["agent"]["planning_results"]
    assert "seed_plan_serialized" in snapshot["agent"]["planning_results"]


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
