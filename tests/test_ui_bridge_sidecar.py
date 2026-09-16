"""UI bridge sidecar persistence tests (no full-snapshot rewrites)."""

from __future__ import annotations

from web.server import _select_case_bridge
from web.workspace_store import WorkspaceStore


def _store(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("bridge_user", "hash")
    case = store.create_session(user["id"], "Bridge case")
    return store, user, case


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
