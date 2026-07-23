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
    agent_calls = []

    def get_agent(session_id=None):
        agent_calls.append(session_id)
        agents.setdefault(session_id or "active", object())
        return agents[session_id or "active"]

    def drop_agent(session_id):
        agents.pop(session_id, None)

    register_session_routes(app, store, get_agent, drop_agent)
    app.extensions["test_agent_calls"] = agent_calls

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


def test_authenticated_editor_can_explicitly_take_over_a_locked_case(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    created = _register(client, "takeover_user")
    csrf = created["csrf_token"]
    first_token = "a" * 20
    second_token = "b" * 20
    headers = {"X-CSRF-Token": csrf}

    first = client.post(
        "/api/workspace/lease",
        json={"editor_token": first_token},
        headers={**headers, "X-BrachyBot-Editor": first_token},
    )
    assert first.status_code == 200

    blocked = client.post(
        "/api/workspace/lease",
        json={"editor_token": second_token},
        headers={**headers, "X-BrachyBot-Editor": second_token},
    )
    assert blocked.status_code == 409

    takeover = client.post(
        "/api/workspace/lease",
        json={"editor_token": second_token, "takeover": True},
        headers={**headers, "X-BrachyBot-Editor": second_token},
    )
    assert takeover.status_code == 200
    assert takeover.get_json()["taken_over"] is True


def test_lease_request_can_bind_an_owned_session_explicitly(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    created = _register(client, "lease_case_user")
    csrf = created["csrf_token"]
    created_case = client.post(
        "/api/sessions",
        json={"title": "Second case", "editor_token": "c" * 20},
        headers={"X-CSRF-Token": csrf, "X-BrachyBot-Editor": "c" * 20},
    )
    assert created_case.status_code == 201
    second_id = created_case.get_json()["active_session_id"]
    lease = client.post(
        "/api/workspace/lease",
        json={"session_id": second_id, "editor_token": "c" * 20},
        headers={"X-CSRF-Token": csrf, "X-BrachyBot-Editor": "c" * 20},
    )
    assert lease.status_code == 200
    assert lease.get_json()["editable"] is True


def test_request_scoped_case_header_does_not_change_selected_case(tmp_path):
    """Delayed work must target its owner without navigating the browser."""
    app = _app(tmp_path)
    client = app.test_client()
    auth = _register(client, "request_scope_user")
    first_id = auth["active_session_id"]
    csrf = auth["csrf_token"]
    created = client.post(
        "/api/sessions",
        json={"title": "Selected second case"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    second_id = created.get_json()["active_session_id"]

    saved = client.post(
        "/api/workspace/state",
        json={
            "session_id": first_id,
            "ui": {"marker": "first-case-only"},
        },
        headers={"X-CSRF-Token": csrf, "X-BrachyBot-Session": first_id},
    )
    assert saved.status_code == 200
    assert saved.get_json()["workspace"]["session_id"] == first_id

    first_snapshot = client.get(
        "/api/workspace/snapshot",
        headers={"X-BrachyBot-Session": first_id},
    ).get_json()["workspace"]
    selected_snapshot = client.get("/api/workspace/snapshot").get_json()["workspace"]
    assert first_snapshot["ui"]["marker"] == "first-case-only"
    assert selected_snapshot["session_id"] == second_id
    assert client.get("/api/sessions").get_json()["active_session_id"] == second_id


def test_request_scoped_case_header_rejects_cross_user_access(tmp_path):
    app = _app(tmp_path)
    owner = app.test_client()
    other = app.test_client()
    owner_auth = _register(owner, "header_owner")
    _register(other, "header_other")

    response = other.get(
        "/api/workspace/snapshot",
        headers={"X-BrachyBot-Session": owner_auth["active_session_id"]},
    )
    assert response.status_code == 404


def test_explicit_lease_does_not_change_selected_case(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    auth = _register(client, "lease_navigation_user")
    first_id = auth["active_session_id"]
    csrf = auth["csrf_token"]
    created = client.post(
        "/api/sessions",
        json={"title": "Keep selected"},
        headers={"X-CSRF-Token": csrf},
    )
    second_id = created.get_json()["active_session_id"]

    lease = client.post(
        "/api/workspace/lease",
        json={"session_id": first_id, "editor_token": "lease-navigation-token"},
        headers={
            "X-CSRF-Token": csrf,
            "X-BrachyBot-Editor": "lease-navigation-token",
            "X-BrachyBot-Session": first_id,
        },
    )
    assert lease.status_code == 200
    assert client.get("/api/sessions").get_json()["active_session_id"] == second_id


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


def test_workspace_upload_honors_owned_request_session_header(tmp_path):
    from web.server import create_app

    app = create_app({
        "runtime_dir": str(tmp_path / "server-runtime"),
        "secret_key": "test-secret",
        "workspace_maintenance": False,
    })
    client = app.test_client()
    auth = _register(client, "scoped_upload_user")
    first_id = auth["active_session_id"]
    second = client.post(
        "/api/sessions",
        json={"title": "Selected second case"},
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    second_id = second.get_json()["active_session_id"]

    response = client.post(
        "/api/upload",
        data={"file": (BytesIO(b"request-scoped-input"), "first-study.nii")},
        content_type="multipart/form-data",
        headers={
            "X-CSRF-Token": auth["csrf_token"],
            "X-BrachyBot-Session": first_id,
        },
    )
    assert response.status_code == 200
    assert response.get_json()["session_id"] == first_id
    assert client.get("/api/sessions").get_json()["active_session_id"] == second_id


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


def test_case_selection_returns_snapshot_without_blocking_on_agent_hydration(tmp_path):
    """Control-plane selection must not synchronously rebuild a case agent."""
    app = _app(tmp_path)
    client = app.test_client()
    auth = _register(client, "fast_switch_user")
    store = app.extensions["brachybot_workspace_store"]
    other = store.create_session(auth["user"]["id"], "Restorable case")

    response = client.post(
        f"/api/sessions/{other.id}/select",
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["workspace"]["session"]["id"] == other.id
    assert app.extensions["test_agent_calls"] == []


def test_new_case_creation_transfers_the_current_browser_lease(tmp_path):
    """Creating an empty case should not require a second lease round trip."""
    app = _app(tmp_path)
    client = app.test_client()
    auth = _register(client, "fast_create_user")
    editor_token = "create-browser-editor-token"
    csrf = auth["csrf_token"]

    acquired = client.post(
        "/api/workspace/lease",
        json={"editor_token": editor_token},
        headers={"X-CSRF-Token": csrf, "X-BrachyBot-Editor": editor_token},
    )
    assert acquired.status_code == 200
    assert acquired.get_json()["editable"] is True

    created = client.post(
        "/api/sessions",
        json={"title": "Fast empty case"},
        headers={"X-CSRF-Token": csrf, "X-BrachyBot-Editor": editor_token},
    )
    assert created.status_code == 201
    payload = created.get_json()
    assert payload["lease"]["editable"] is True
    assert payload["active_session_id"] == payload["session"]["id"]
    assert app.extensions["test_agent_calls"] == []


def test_transient_task_feed_filters_by_workspace_owner():
    tasks = TaskManager()
    first = tasks.create_task("planning", "First case", workspace_owner="user-a:case-a")
    second = tasks.create_task("planning", "Second case", workspace_owner="user-b:case-b")
    assert tasks.get_task(first, workspace_owner="user-a:case-a")["id"] == first
    assert tasks.get_task(second, workspace_owner="user-a:case-a") is None
    assert set(tasks.get_all_tasks(workspace_owner="user-a:case-a")) == {first}
