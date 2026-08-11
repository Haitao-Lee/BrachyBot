"""Focused persistence and ownership tests for durable case workspaces."""

from __future__ import annotations

import logging
import threading
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from web.workspace_store import (
    EAGER_ARRAY_LOAD_MAX_BYTES,
    WorkspaceLeaseConflict,
    WorkspaceNotFound,
    WorkspaceQuotaExceeded,
    WorkspaceStore,
    _decode_artifacts,
)


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


def test_hydration_eager_loads_tiny_arrays_but_keeps_large_volumes_mapped(
    tmp_path, monkeypatch,
):
    """Thousands of tiny planning arrays must not consume one FD each."""
    root = tmp_path / "case"
    arrays = root / "arrays"
    arrays.mkdir(parents=True)
    tiny_path = arrays / "tiny.npy"
    large_path = arrays / "large.npy"
    np.save(tiny_path, np.arange(9, dtype=np.float32))
    large_count = EAGER_ARRAY_LOAD_MAX_BYTES // np.dtype(np.float32).itemsize + 1024
    np.save(large_path, np.arange(large_count, dtype=np.float32))

    real_load = np.load
    modes = {}

    def tracked_load(path, *args, **kwargs):
        modes[Path(path).name] = kwargs.get("mmap_mode")
        return real_load(path, *args, **kwargs)

    monkeypatch.setattr("web.workspace_store.np.load", tracked_load)
    decoded = _decode_artifacts({
        "tiny": {"$array": "arrays/tiny.npy"},
        "large": {"$array": "arrays/large.npy"},
    }, root)

    assert modes == {"tiny.npy": None, "large.npy": "r"}
    assert isinstance(decoded["tiny"], np.ndarray)
    assert not isinstance(decoded["tiny"], np.memmap)
    assert isinstance(decoded["large"], np.memmap)


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


def test_hydration_holds_checkpoint_lock_while_reading_array_sidecars(tmp_path):
    """Checkpoint pruning cannot delete an array between snapshot and decode."""
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("hydration_lock_owner", "hash")
    case = store.create_session(user["id"], "Hydration lock case")
    store.snapshot_agent(user["id"], case.id, _Agent(), reason="test.lock.seed")

    case_lock = store._checkpoint_work_lock(user["id"], case.id)
    assert case_lock.acquire(timeout=1)
    finished = threading.Event()
    errors = []
    restored = _Agent()

    def hydrate():
        try:
            store.hydrate_agent(user["id"], case.id, restored)
        except Exception as exc:  # pragma: no cover - assertion reports it
            errors.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=hydrate)
    worker.start()
    assert not finished.wait(0.05)
    case_lock.release()
    assert finished.wait(3)
    worker.join(timeout=1)
    assert not errors
    assert np.array_equal(
        restored.memory.retrieve("ct_data"),
        np.arange(12, dtype=np.int16).reshape(3, 2, 2),
    )


def test_metadata_hydration_checkpoint_preserves_planning_sidecars(tmp_path):
    """A lightweight startup checkpoint must not prune durable plan arrays."""
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("partial_hydration_owner", "hash")
    case = store.create_session(user["id"], "Partial hydration case")
    agent = _Agent()
    planning_id = "planning-partial"
    skin_mask = np.full((3, 2, 2), 1, dtype=np.uint8)
    guide_vertices = np.arange(18, dtype=np.float32).reshape(6, 3)
    run_snapshot = {
        "seed_plan_serialized": agent.memory.retrieve("seed_plan_serialized"),
        "trajectories": agent.memory.retrieve("trajectories"),
        "dose_distribution_gy": agent.memory.retrieve("dose_distribution_gy"),
        "dose_metrics": agent.memory.retrieve("dose_metrics"),
        "dvh_data": agent.memory.retrieve("dvh_data"),
        "surgical_guide": {"version": 1, "mesh": {"vertices": guide_vertices}},
        "skin_surface_mask": skin_mask,
    }
    agent.memory.planning_results.update({
        "planning_runs": [{"planning_id": planning_id, "status": "completed", "visible": True}],
        "active_planning_id": planning_id,
        "planning_run_id": planning_id,
        f"planning_run:{planning_id}": run_snapshot,
        "surgical_guide": run_snapshot["surgical_guide"],
        "skin_surface_mask": skin_mask,
    })
    agent.memory._planning_versions.update({
        key: 1 for key in agent.memory.planning_results
    })
    store.snapshot_agent(user["id"], case.id, agent, reason="partial.seed")

    partial = _Agent()
    store.hydrate_agent(
        user["id"],
        case.id,
        partial,
        include_planning_results=False,
        load_ct=False,
    )
    partial._workspace_hydration_in_progress = True
    partial._workspace_data_ready = False
    store.snapshot_agent(user["id"], case.id, partial, reason="partial.ui.checkpoint")

    raw = store.load_snapshot(user["id"], case.id)["agent"]["planning_results"]
    assert "$array" in raw["dose_distribution_gy"]
    assert "$array" in raw["skin_surface_mask"]
    assert "$array" in raw[f"planning_run:{planning_id}"]["dose_distribution_gy"]
    assert "$array" in raw[f"planning_run:{planning_id}"]["surgical_guide"]["mesh"]["vertices"]

    restored = _Agent()
    store.hydrate_agent(user["id"], case.id, restored)
    assert np.array_equal(restored.memory.retrieve("skin_surface_mask"), skin_mask)
    assert np.array_equal(
        restored.memory.retrieve("surgical_guide")["mesh"]["vertices"],
        guide_vertices,
    )
    assert restored.memory.retrieve("seed_plan_serialized")["seeds"] == [[1.0, 2.0, 3.0]]
    assert restored.memory.retrieve("dose_metrics")["d90"] == 123.4


def test_full_hydration_repairs_missing_active_planning_aliases(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("planning_alias_owner", "hash")
    case = store.create_session(user["id"], "Planning alias case")
    agent = _Agent()
    planning_id = "planning-history-only"
    dose = np.full((3, 2, 2), 4.0, dtype=np.float32)
    skin = np.ones((3, 2, 2), dtype=np.uint8)
    run_snapshot = {
        "seed_plan_serialized": {"seeds": [[4.0, 5.0, 6.0]], "needles": [{"id": "needle-9"}]},
        "dose_distribution_gy": dose,
        "dose_metrics": {"v100": 90.61, "d90": 122.75},
        "surgical_guide": {"version": 3},
        "skin_surface_mask": skin,
    }
    agent.memory.planning_results = {
        "planning_runs": [{"planning_id": planning_id, "status": "completed", "visible": True}],
        "active_planning_id": planning_id,
        "planning_run_id": planning_id,
        f"planning_run:{planning_id}": run_snapshot,
    }
    agent.memory._planning_versions = {key: 1 for key in agent.memory.planning_results}
    store.snapshot_agent(user["id"], case.id, agent, reason="history.only")

    restored = _Agent()
    store.hydrate_agent(user["id"], case.id, restored)
    assert np.array_equal(restored.memory.retrieve("dose_distribution_gy"), dose)
    assert np.array_equal(restored.memory.retrieve("skin_surface_mask"), skin)
    assert restored.memory.retrieve("surgical_guide")["version"] == 3
    assert restored.memory.retrieve("seed_plan_serialized")["needles"][0]["id"] == "needle-9"


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


def test_report_snapshot_does_not_let_older_blank_form_erase_narrative(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("report_owner", "hash")
    case = store.create_session(user["id"], "Report case")
    rich = {
        "version": 3,
        "updatedAt": 200,
        "interpretation": "Generated dose interpretation",
        "safety": "Review OAR dose",
        "figures": [{"axis": "dvh", "_cacheKey": "figure-1"}],
    }
    blank = {"version": 3, "updatedAt": 100, "interpretation": "", "safety": "", "figures": []}
    store.save_snapshot_patch(user["id"], case.id, {"report": {"form": rich}})
    store.save_snapshot_patch(user["id"], case.id, {"report": {"form": blank}})
    form = store.load_snapshot(user["id"], case.id)["report"]["form"]
    assert form["interpretation"] == rich["interpretation"]
    assert form["figures"] == rich["figures"]

    reset = {"version": 3, "updatedAt": 300, "interpretation": "", "safety": "", "figures": []}
    store.save_snapshot_patch(user["id"], case.id, {"report": {"form": reset}})
    assert store.load_snapshot(user["id"], case.id)["report"]["form"]["interpretation"] == ""


def test_legacy_direct_report_form_is_canonicalized_without_losing_text(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("legacy_report_owner", "hash")
    case = store.create_session(user["id"], "Legacy report case")
    rich = {
        "version": 3,
        "updatedAt": 200,
        "interpretation": "Persisted legacy narrative",
        "figures": [{"axis": "axial", "_cacheKey": "legacy-figure"}],
    }
    store.save_snapshot_patch(user["id"], case.id, {"report": rich})
    store.save_snapshot_patch(user["id"], case.id, {
        "report": {"form": {"version": 3, "updatedAt": 100, "interpretation": ""}},
    })
    report = store.load_snapshot(user["id"], case.id)["report"]
    assert report["form"]["interpretation"] == "Persisted legacy narrative"
    assert report["form"]["figures"] == rich["figures"]
    assert "interpretation" not in report


def test_report_quality_assessment_survives_snapshot_merge(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("quality_owner", "hash")
    case = store.create_session(user["id"], "Quality report case")
    form = {
        "version": 3,
        "updatedAt": 200,
        "metrics": {"v100": 90.6, "d90": 122.75},
        "qualityAssessment": {
            "version": 1,
            "language": "en",
            "generatedAt": 200,
            "metrics": {
                "v100": {"value": 90.6, "reference": "See cited case criteria", "statusText": "Not assessed"},
                "d90": {"value": 122.75, "reference": "See cited case criteria", "statusText": "Not assessed"},
            },
        },
    }
    store.save_snapshot_patch(user["id"], case.id, {"report": {"form": form}})
    restored = store.load_snapshot(user["id"], case.id)["report"]["form"]
    assert restored["qualityAssessment"]["metrics"]["v100"]["reference"] == "See cited case criteria"
    assert restored["qualityAssessment"]["metrics"]["d90"]["statusText"] == "Not assessed"


def test_report_patch_is_bound_to_the_sessions_authoritative_planning(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("report_planning_owner", "hash")
    case = store.create_session(user["id"], "Planning report ownership case")
    agent = _Agent()
    planning_id = "planning-current"
    agent.memory.planning_results.update({
        "planning_runs": [{"planning_id": planning_id, "status": "completed", "visible": True}],
        "active_planning_id": planning_id,
        "planning_run_id": planning_id,
        f"planning_run:{planning_id}": {"dose_metrics": {"v100": 90.61}},
    })
    agent.memory._planning_versions.update({key: 1 for key in agent.memory.planning_results})
    store.snapshot_agent(user["id"], case.id, agent, reason="report.plan.seed")

    current_form = {
        "version": 3,
        "sessionId": case.id,
        "updatedAt": 200,
        "figures": [{"axis": "axial", "_serverUrl": "/current.png"}],
        "metrics": {"v100": 90.61},
        "qualityAssessment": {
            "metrics": {
                "v100": {
                    "value": 90.61,
                    "reference": "Pancreatic criterion: V100 >= 90%",
                    "statusText": "Meets cited criterion",
                },
            },
        },
    }
    foreign_form = {
        "version": 3,
        "sessionId": "another-session",
        "updatedAt": 300,
        "interpretation": "Foreign case report",
    }
    store.save_snapshot_patch(user["id"], case.id, {
        "report": {
            "form": foreign_form,
            "active_planning_id": "planning-foreign",
            "by_planning_id": {
                planning_id: {"form": current_form},
                "planning-foreign": {"form": foreign_form},
            },
        },
    })

    report = store.load_snapshot(user["id"], case.id)["report"]
    assert report["active_planning_id"] == planning_id
    assert set(report["by_planning_id"]) == {planning_id}
    assert report["form"]["sessionId"] == case.id
    assert report["form"]["figures"][0]["axis"] == "axial"
    quality = report["form"]["qualityAssessment"]["metrics"]["v100"]
    assert quality["reference"] == "Pancreatic criterion: V100 >= 90%"
    assert quality["statusText"] == "Meets cited criterion"


def test_newer_incomplete_report_snapshot_cannot_erase_quality_columns(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("quality_merge_owner", "hash")
    case = store.create_session(user["id"], "Quality merge case")
    complete = {
        "version": 3,
        "updatedAt": 200,
        "metrics": {"v100": 91.23, "d90": 122.55},
        "qualityAssessment": {
            "version": 2,
            "language": "en",
            "generatedAt": 200,
            "inputFingerprint": "stable-plan-inputs",
            "metrics": {
                "v100": {"value": 91.23, "reference": "See cited case criteria", "statusText": "Not assessed"},
                "d90": {"value": 122.55, "reference": "See cited case criteria", "statusText": "Not assessed"},
            },
        },
    }
    store.save_snapshot_patch(user["id"], case.id, {"report": {"form": complete}})
    # This represents a later shell/hydration write that has the metrics but
    # has not rebuilt the derived columns yet.
    incomplete = {
        "version": 3,
        "updatedAt": 300,
        "metrics": {"v100": 91.23, "d90": 122.55},
        "qualityAssessment": {
            "version": 2,
            "language": "en",
            "generatedAt": 300,
            "metrics": {
                "v100": {"value": 91.23},
                "d90": {"value": 122.55},
            },
        },
    }
    store.save_snapshot_patch(user["id"], case.id, {"report": {"form": incomplete}})
    restored = store.load_snapshot(user["id"], case.id)["report"]["form"]
    assert restored["qualityAssessment"]["metrics"]["v100"]["reference"] == "See cited case criteria"
    assert restored["qualityAssessment"]["metrics"]["v100"]["statusText"] == "Not assessed"
    assert restored["qualityAssessment"]["metrics"]["d90"]["reference"] == "See cited case criteria"


def test_generic_hydration_rows_cannot_replace_specific_quality_assessment(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("specific_quality_owner", "hash")
    case = store.create_session(user["id"], "Specific quality case")
    specific = {
        "version": 3,
        "updatedAt": 200,
        "metrics": {"v100": 91.23, "d90": 122.55},
        "qualityAssessment": {
            "version": 2,
            "language": "en",
            "inputFingerprint": "source-backed-plan",
            "metrics": {
                "v100": {
                    "value": 91.23,
                    "reference": "Pancreatic site criterion: V100 >= 90%",
                    "statusText": "Meets cited criterion",
                    "statusClass": "ok",
                },
                "d90": {
                    "value": 122.55,
                    "reference": "Prescription reference: 120 Gy",
                    "statusText": "Review with current protocol",
                    "statusClass": "warn",
                },
            },
        },
    }
    store.save_snapshot_patch(user["id"], case.id, {"report": {"form": specific}})

    delayed_hydration = {
        "version": 3,
        "updatedAt": 300,
        "metrics": {"v100": 91.23, "d90": 122.55},
        "qualityAssessment": {
            "version": 2,
            "language": "en",
            "metrics": {
                "v100": {
                    "value": 91.23,
                    "reference": "See cited case criteria",
                    "statusText": "Not assessed",
                },
                "d90": {
                    "value": 122.55,
                    "reference": "See cited case criteria",
                    "statusText": "Not assessed",
                },
            },
        },
    }
    store.save_snapshot_patch(user["id"], case.id, {"report": {"form": delayed_hydration}})

    rows = store.load_snapshot(user["id"], case.id)["report"]["form"]["qualityAssessment"]["metrics"]
    assert rows["v100"]["reference"] == "Pancreatic site criterion: V100 >= 90%"
    assert rows["v100"]["statusText"] == "Meets cited criterion"
    assert rows["d90"]["reference"] == "Prescription reference: 120 Gy"
    assert rows["d90"]["statusText"] == "Review with current protocol"
    assessment = store.load_snapshot(user["id"], case.id)["report"]["form"]["qualityAssessment"]
    assert assessment["inputFingerprint"] == "source-backed-plan"


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


def test_chat_attachment_registry_reconciles_out_of_order_screenshot_writes(tmp_path):
    """A screenshot captured before the assistant row survives later stale writes."""
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("attachment_registry_owner", "hash")
    case = store.create_session(user["id"], "Attachment registry case")
    attachment = {
        "id": "shot-before-message",
        "type": "screenshot",
        "url": f"/api/sessions/{case.id}/screenshots/chat.png",
        "session_id": case.id,
        "message_id": "assistant-request-2",
        "request_id": "request-2",
    }

    # The browser can upload the image while the assistant shell is still
    # being created.  The registry is the durable hand-off between writers.
    store.save_snapshot_patch(
        user["id"], case.id, {"chat": {"attachments": [attachment]}},
    )
    store.save_snapshot_patch(
        user["id"], case.id,
        {"chat": {"messages": [{
            "id": "assistant-request-2",
            "request_id": "request-2",
            "type": "bot-response",
            "content": "截图已生成",
            "timestamp": 2000,
        }]}},
    )
    # A stale browser checkpoint with the same row but no attachment must not
    # erase the image that was already committed by the capture request.
    store.save_snapshot_patch(
        user["id"], case.id,
        {"chat": {"messages": [{
            "id": "assistant-request-2",
            "request_id": "request-2",
            "type": "bot-response",
            "content": "截图已生成",
            "timestamp": 3000,
            "attachments": [],
        }]}},
    )

    snapshot = store.load_snapshot(user["id"], case.id)
    messages = snapshot["chat"]["messages"]
    assistant = next(message for message in messages if message["type"] == "bot-response")
    assert [item["id"] for item in assistant["attachments"]] == ["shot-before-message"]
    assert [item["id"] for item in snapshot["chat"]["attachments"]] == ["shot-before-message"]


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
