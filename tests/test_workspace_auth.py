"""Cookie authentication and case-session authorization tests."""

from __future__ import annotations

from flask import Flask, jsonify
from io import BytesIO

from web.auth import configure_auth, register_auth_routes
from web.routes.session_routes import register_session_routes
from web.server_support import TaskManager
from web.workspace_store import WorkspaceStore


def _app(tmp_path):
    app = Flask(__name__)
    store = WorkspaceStore(tmp_path / "runtime")
    configure_auth(app, store, {"secret_key": "test-secret"})
    register_auth_routes(app, store)
    agents = {}

    def get_agent(session_id=None):
        agents.setdefault(session_id or "active", object())
        return agents[session_id or "active"]

    def drop_agent(session_id):
        agents.pop(session_id, None)

    register_session_routes(app, store, get_agent, drop_agent)

    @app.route("/api/probe", methods=["GET", "POST"])
    def probe():
        return jsonify({"success": True})

    return app


def _register(client, username):
    response = client.post("/api/auth/register", json={"username": username, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.get_json()


def test_auth_csrf_and_cross_user_session_denial(tmp_path):
    app = _app(tmp_path)
    first = app.test_client()
    second = app.test_client()

    created = _register(first, "first_user")
    token = created["csrf_token"]
    session_id = created["active_session_id"]
    assert first.get("/api/probe").status_code == 200
    assert first.post("/api/probe").status_code == 403
    assert first.post("/api/probe", headers={"X-CSRF-Token": token}).status_code == 200

    other = _register(second, "second_user")
    other_token = other["csrf_token"]
    assert second.post(
        f"/api/sessions/{session_id}/select", headers={"X-CSRF-Token": other_token}
    ).status_code == 404
    assert second.get("/api/workspace/snapshot").status_code == 200


def test_session_trash_restore_and_cookie_logout(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    created = _register(client, "planner_user")
    token = created["csrf_token"]
    session_id = created["active_session_id"]

    deleted = client.delete(f"/api/sessions/{session_id}", headers={"X-CSRF-Token": token})
    assert deleted.status_code == 200
    trash = client.get("/api/sessions/trash").get_json()["sessions"]
    assert any(item["id"] == session_id for item in trash)
    restored = client.post(f"/api/sessions/{session_id}/restore", headers={"X-CSRF-Token": token})
    assert restored.status_code == 200

    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": token}).status_code == 200
    assert client.get("/api/sessions").status_code == 401


def test_session_rename_persists_for_the_authenticated_case(tmp_path):
    """A case rename must survive a fresh server-side session listing."""
    app = _app(tmp_path)
    client = app.test_client()
    created = _register(client, "rename_user")
    session_id = created["active_session_id"]

    response = client.patch(
        f"/api/sessions/{session_id}",
        json={"title": "Pancreas follow-up"},
        headers={"X-CSRF-Token": created["csrf_token"]},
    )
    assert response.status_code == 200
    assert response.get_json()["session"]["title"] == "Pancreas follow-up"

    sessions = client.get("/api/sessions").get_json()["sessions"]
    restored = next(item for item in sessions if item["id"] == session_id)
    assert restored["title"] == "Pancreas follow-up"


def test_password_change_requires_csrf_and_updates_login(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    created = _register(client, "password_user")
    old_password = "correct horse battery staple"
    new_password = "new correct horse battery staple"
    assert client.post("/api/auth/password", json={
        "current_password": old_password,
        "new_password": new_password,
    }).status_code == 403
    assert client.post("/api/auth/password", json={
        "current_password": old_password,
        "new_password": new_password,
    }, headers={"X-CSRF-Token": created["csrf_token"]}).status_code == 200
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": created["csrf_token"]}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "password_user", "password": new_password}).status_code == 200


def test_case_artifact_download_is_account_owned(tmp_path):
    app = _app(tmp_path)
    first = app.test_client()
    second = app.test_client()
    first_auth = _register(first, "artifact_owner")
    _register(second, "artifact_other")
    store = app.extensions["brachybot_workspace_store"]
    artifact = store.session_artifact_path(
        first_auth["user"]["id"], first_auth["active_session_id"], "artifacts", "reports/example.txt"
    )
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("private report", encoding="utf-8")

    own = first.get(f"/api/sessions/{first_auth['active_session_id']}/artifacts/reports/example.txt")
    assert own.status_code == 200
    assert own.data == b"private report"
    denied = second.get(f"/api/sessions/{first_auth['active_session_id']}/artifacts/reports/example.txt")
    assert denied.status_code == 404


def test_browser_generated_artifact_is_stored_in_active_workspace(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    auth = _register(client, "browser_report_user")
    saved = client.post(
        "/api/workspace/artifacts",
        data={"category": "reports", "file": (BytesIO(b"<html>case</html>"), "case.html")},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert saved.status_code == 201
    payload = saved.get_json()
    assert "/artifacts/reports/case.html" in payload["path"].replace("\\", "/")
    downloaded = client.get(payload["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.data == b"<html>case</html>"


def test_workspace_upload_endpoint_returns_owned_path(tmp_path):
    # This integration check uses the public server factory so an upload cannot
    # accidentally fall back to the shared legacy uploads directory.
    from web.server import create_app

    app = create_app({
        "runtime_dir": str(tmp_path / "server-runtime"),
        "secret_key": "test-secret",
        "workspace_maintenance": False,
    })
    client = app.test_client()
    created = _register(client, "upload_user")
    response = client.post(
        "/api/upload",
        data={"file": (BytesIO(b"not-a-real-nifti"), "study.nii")},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": created["csrf_token"]},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert "/inputs/" in payload["path"].replace("\\", "/")
    assert payload["session_id"] == created["active_session_id"]


def test_nonselected_case_mutations_respect_the_case_edit_lease(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    auth = _register(client, "lease_target_user")
    token = auth["csrf_token"]
    store = app.extensions["brachybot_workspace_store"]
    locked = store.create_session(auth["user"]["id"], "Edited elsewhere")
    store.acquire_lease(auth["user"]["id"], locked.id, "other-browser-token-1234")

    response = client.patch(
        f"/api/sessions/{locked.id}",
        json={"title": "Should not rename"},
        headers={"X-CSRF-Token": token, "X-BrachyBot-Editor": "this-browser-token-5678"},
    )
    assert response.status_code == 409
    assert store.get_session(auth["user"]["id"], locked.id).title == "Edited elsewhere"


def test_locked_case_does_not_block_switching_to_an_independent_case(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    auth = _register(client, "lease_switch_user")
    token = auth["csrf_token"]
    active = auth["active_session_id"]
    store = app.extensions["brachybot_workspace_store"]
    other = store.create_session(auth["user"]["id"], "Independent case")
    store.acquire_lease(auth["user"]["id"], active, "other-browser-token-1234")

    switched = client.post(
        f"/api/sessions/{other.id}/select",
        headers={"X-CSRF-Token": token, "X-BrachyBot-Editor": "this-browser-token-5678"},
    )
    assert switched.status_code == 200
    assert switched.get_json()["active_session_id"] == other.id


def test_transient_task_feed_filters_by_workspace_owner():
    tasks = TaskManager()
    first = tasks.create_task("planning", "First case", workspace_owner="user-a:case-a")
    second = tasks.create_task("planning", "Second case", workspace_owner="user-b:case-b")
    assert tasks.get_task(first, workspace_owner="user-a:case-a")["id"] == first
    assert tasks.get_task(second, workspace_owner="user-a:case-a") is None
    assert set(tasks.get_all_tasks(workspace_owner="user-a:case-a")) == {first}
