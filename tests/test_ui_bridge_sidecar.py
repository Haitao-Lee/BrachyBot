"""UI bridge sidecar persistence tests (no full-snapshot rewrites)."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from web.server import _select_case_bridge
from web.workspace_store import WorkspaceArchived, WorkspaceStore


def _store(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("bridge_user", "hash")
    case = store.create_session(user["id"], "Bridge case")
    return store, user, case


def _app_client_store(tmp_path, username):
    from web.server import create_app

    app = create_app({
        "runtime_dir": str(tmp_path / "server-runtime"),
        "secret_key": "test-secret",
        "workspace_maintenance": False,
    })
    client = app.test_client()
    body = client.post(
        "/api/auth/register",
        json={"username": username, "password": "bridge-password-123"},
    ).get_json()
    return client, body, app.extensions["brachybot_workspace_store"]


def test_ui_bridge_roundtrip(tmp_path):
    store, user, case = _store(tmp_path)
    store.save_ui_bridge(
        user["id"],
        case.id,
        {"state": {"viewer": {"axial": 12}}, "events": [{"type": "x"}],
         "training": {}, "updated_at": 123.0},
        reason="ui.state_saved",
    )
    loaded = store.load_ui_bridge(user["id"], case.id)
    assert loaded["state"] == {"viewer": {"axial": 12}}
    assert loaded["events"] == [{"type": "x"}]
    assert loaded["reason"] == "ui.state_saved"
    assert float(loaded["saved_at"]) > 0


def test_ui_bridge_missing_returns_empty(tmp_path):
    store, user, case = _store(tmp_path)
    assert store.load_ui_bridge(user["id"], case.id) == {}


def test_ui_bridge_invalid_json_returns_empty(tmp_path):
    store, user, case = _store(tmp_path)
    root = store.workspace_root(user["id"], case.id, create=True)
    (root / "ui_bridge.json").write_text("{not json", encoding="utf-8")
    assert store.load_ui_bridge(user["id"], case.id) == {}


def test_select_case_bridge_prefers_newer_sidecar():
    snapshot = {"state": {"a": 1}, "updated_at": 100.0}
    sidecar = {"state": {"a": 2}, "saved_at": 200.0}
    assert _select_case_bridge(snapshot, sidecar)["state"] == {"a": 2}


def test_select_case_bridge_falls_back_to_snapshot():
    snapshot = {"state": {"a": 1}, "updated_at": 300.0}
    sidecar = {"state": {"a": 2}, "saved_at": 200.0}
    assert _select_case_bridge(snapshot, sidecar)["state"] == {"a": 1}
    assert _select_case_bridge(snapshot, {})["state"] == {"a": 1}
    assert _select_case_bridge({}, {}) == {}


def test_flush_ui_bridge_uses_sidecar_writer(tmp_path):
    from web.routes import planning_routes

    calls = []

    class _Store:
        def save_ui_bridge(self, user_id, session_id, bridge, *, reason=""):
            calls.append((user_id, session_id, dict(bridge), reason))

        def save_snapshot_patch(self, *args, **kwargs):
            raise AssertionError("bridge flush must not rewrite the full snapshot")

    key = ("user-1", "case-1")
    planning_routes._UI_BRIDGE_CHECKPOINT_PENDING[key] = (
        _Store(), "user-1", "case-1", {"state": {"a": 1}}, "ui.state_saved",
    )
    try:
        planning_routes._flush_ui_bridge_checkpoint(key)
    finally:
        planning_routes._UI_BRIDGE_CHECKPOINT_PENDING.pop(key, None)
        planning_routes._UI_BRIDGE_CHECKPOINT_TIMERS.pop(key, None)
    assert calls == [("user-1", "case-1", {"state": {"a": 1}}, "ui.state_saved")]


def test_ui_state_restores_from_sidecar(tmp_path):
    from web.server import create_app
    from web import server_support as _server_support

    app = create_app({
        "runtime_dir": str(tmp_path / "server-runtime"),
        "secret_key": "test-secret",
        "workspace_maintenance": False,
    })
    client = app.test_client()
    registered = client.post(
        "/api/auth/register",
        json={"username": "bridge_restore", "password": "bridge-password-123"},
    )
    body = registered.get_json()
    token = body["csrf_token"]
    sid = body["active_session_id"]
    saved = client.post(
        "/api/ui/state",
        json={"state": {"viewer": {"axial": 7}}, "session_id": sid},
        headers={"X-CSRF-Token": token},
    )
    assert saved.status_code == 200
    # Flush the debounced writer synchronously so the sidecar exists.
    from web.routes import planning_routes
    planning_routes._flush_ui_bridge_checkpoint((str(body["user"]["id"]), sid))
    # Simulate a fresh process: drop the live bucket.
    bucket = _server_support._ui_bucket(sid)
    bucket.clear()
    restored = client.get("/api/ui/state", query_string={"session_id": sid})
    assert restored.status_code == 200
    assert restored.get_json()["state"] == {"viewer": {"axial": 7}}


def test_sidecar_write_does_not_touch_snapshot_or_revision(tmp_path):
    store, user, case = _store(tmp_path)
    before_revision = store.get_session(user["id"], case.id).revision
    before_bridge = store.load_snapshot(user["id"], case.id).get("ui", {}).get("bridge")
    store.save_ui_bridge(
        user["id"],
        case.id,
        {"state": {"a": 1}, "events": [], "training": {}},
    )
    assert store.get_session(user["id"], case.id).revision == before_revision
    after_bridge = store.load_snapshot(user["id"], case.id).get("ui", {}).get("bridge")
    assert after_bridge == before_bridge
    assert store.load_ui_bridge(user["id"], case.id)["state"] == {"a": 1}


def test_sidecar_sanitizes_non_json_payloads(tmp_path):
    store, user, case = _store(tmp_path)
    store.save_ui_bridge(
        user["id"],
        case.id,
        {"state": {
            "nan": float("nan"),
            "s": {1, 2},
            "p": Path("/tmp/x"),
            "obj": object(),
        }},
    )
    loaded = store.load_ui_bridge(user["id"], case.id)
    assert loaded["state"]["nan"] is None
    assert isinstance(loaded["state"]["s"], list)
    assert loaded["state"]["p"] == "/tmp/x"
    assert loaded["state"]["obj"] == {"$unsupported": "object"}


def test_ui_bridge_archived_case_is_not_resurrected(tmp_path, monkeypatch):
    store, user, case = _store(tmp_path)
    monkeypatch.setattr(
        store,
        "get_session",
        lambda *args, **kwargs: SimpleNamespace(storage_status="archived"),
    )
    with pytest.raises(WorkspaceArchived):
        store.save_ui_bridge(user["id"], case.id, {"state": {"a": 1}})
    assert store.load_ui_bridge(user["id"], case.id) == {}


def test_select_case_bridge_tie_prefers_snapshot():
    snapshot = {"state": {"a": 1}, "updated_at": 200.0}
    sidecar = {"state": {"a": 2}, "saved_at": 200.0}
    assert _select_case_bridge(snapshot, sidecar)["state"] == {"a": 1}


def test_select_case_bridge_non_mapping():
    assert _select_case_bridge(None, ["not-a-bridge"]) == {}
    assert _select_case_bridge("bad", "worse") == {}


def test_load_ui_bridge_corrupt_shapes_return_empty(tmp_path):
    store, user, case = _store(tmp_path)
    root = store.workspace_root(user["id"], case.id, create=True)
    (root / "ui_bridge.json").write_text(
        '{"state": "oops", "events": 1, "training": []}', encoding="utf-8",
    )
    assert store.load_ui_bridge(user["id"], case.id) == {}


def test_flush_swallows_writer_failure():
    from web.routes import planning_routes

    class _Store:
        def save_ui_bridge(self, *args, **kwargs):
            raise ValueError("not JSON serializable")

    key = ("user-2", "case-2")
    planning_routes._UI_BRIDGE_CHECKPOINT_PENDING[key] = (
        _Store(), "user-2", "case-2", {"state": {}}, "ui.state_saved",
    )
    try:
        planning_routes._flush_ui_bridge_checkpoint(key)
    finally:
        planning_routes._UI_BRIDGE_CHECKPOINT_TIMERS.pop(key, None)
    assert key not in planning_routes._UI_BRIDGE_CHECKPOINT_PENDING


def test_legacy_snapshot_only_case_restores(tmp_path):
    from web import server_support as _server_support

    client, body, store = _app_client_store(tmp_path, "legacy_bridge")
    sid = body["active_session_id"]
    user_id = body["user"]["id"]
    store.save_snapshot_patch(
        user_id,
        sid,
        {"ui": {"bridge": {
            "state": {"legacy": 1},
            "events": [],
            "training": {},
            "updated_at": time.time(),
        }}},
    )
    _server_support._ui_bucket(sid).clear()
    restored = client.get("/api/ui/state", query_string={"session_id": sid})
    assert restored.status_code == 200
    assert restored.get_json()["state"] == {"legacy": 1}


def test_workspace_snapshot_prefers_sidecar_bridge(tmp_path):
    client, body, store = _app_client_store(tmp_path, "snapshot_bridge")
    sid = body["active_session_id"]
    user_id = body["user"]["id"]
    store.save_snapshot_patch(
        user_id,
        sid,
        {"ui": {"bridge": {
            "state": {"snap": 1},
            "events": [],
            "training": {},
            "updated_at": time.time() - 100.0,
        }}},
    )
    store.save_ui_bridge(
        user_id,
        sid,
        {"state": {"side": 2}, "events": [], "training": {}, "updated_at": time.time()},
    )
    response = client.get("/api/workspace/snapshot")
    assert response.status_code == 200
    bridge = response.get_json()["workspace"]["ui"]["bridge"]
    assert bridge["state"] == {"side": 2}


def test_sidecar_persists_lone_surrogates(tmp_path):
    store, user, case = _store(tmp_path)
    store.save_ui_bridge(
        user["id"], case.id, {"state": {"label": "\ud800oops"}},
    )
    loaded = store.load_ui_bridge(user["id"], case.id)
    assert loaded["state"]["label"].endswith("oops")


def test_session_select_returns_newest_bridge(tmp_path):
    client, body, store = _app_client_store(tmp_path, "select_bridge")
    sid = body["active_session_id"]
    user_id = body["user"]["id"]
    token = body["csrf_token"]
    store.save_snapshot_patch(
        user_id,
        sid,
        {"ui": {"bridge": {
            "state": {"snap": 1},
            "events": [],
            "training": {},
            "updated_at": time.time() - 100.0,
        }}},
    )
    store.save_ui_bridge(
        user_id,
        sid,
        {"state": {"side": 2}, "events": [], "training": {}, "updated_at": time.time()},
    )
    response = client.post(
        f"/api/sessions/{sid}/select",
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    workspace = response.get_json()["workspace"]
    assert workspace["ui"]["bridge"]["state"] == {"side": 2}
