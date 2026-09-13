"""Development-only persistent login policy tests."""

from __future__ import annotations

from flask import Flask

from web.auth import configure_auth, register_auth_routes
from web.workspace_store import WorkspaceStore


def _app(tmp_path, **auth_config):
    app = Flask(__name__)
    store = WorkspaceStore(tmp_path / "runtime")
    configure_auth(app, store, {"secret_key": "test-secret", **auth_config})
    register_auth_routes(app, store)
    return app


def _register(client, username):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": "correct horse battery staple"},
    )


def test_debug_account_receives_long_lived_cookie_and_existing_cookie_is_upgraded(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()

    response = _register(client, "HaitaoLi")
    assert response.status_code == 201
    assert "Expires=" in response.headers["Set-Cookie"]
    assert app.extensions["brachybot_auth_policy"]["enabled"] is True
    assert app.extensions["brachybot_auth_policy"]["username"] == "HaitaoLi"
    assert app.config["PERMANENT_SESSION_LIFETIME"].days == 3650

    # A browser that still has an older session cookie is upgraded by the
    # authenticated /me request; no forced logout/login cycle is required.
    with client.session_transaction() as browser_session:
        browser_session.permanent = False
        browser_session.modified = True
    upgraded = client.get("/api/auth/me")
    assert upgraded.status_code == 200
    with client.session_transaction() as browser_session:
        assert browser_session.permanent is True
        assert browser_session["bb_debug_account"] is True


def test_debug_policy_is_account_scoped(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()

    response = _register(client, "ordinary_user")
    assert response.status_code == 201
    with client.session_transaction() as browser_session:
        assert browser_session.permanent is False
        assert "bb_debug_account" not in browser_session
    assert "Expires=" not in response.headers["Set-Cookie"]


def test_public_deployment_cannot_enable_debug_account(tmp_path):
    app = _app(tmp_path, deployment_mode="public")
    client = app.test_client()

    response = _register(client, "HaitaoLi")
    assert response.status_code == 201
    policy = app.extensions["brachybot_auth_policy"]
    assert policy["enabled"] is False
    with client.session_transaction() as browser_session:
        assert browser_session.permanent is False
        assert "bb_debug_account" not in browser_session
    assert "Expires=" not in response.headers["Set-Cookie"]
