"""Exercise actual auth boundaries with a temporary database, never patient data."""
import pytest
from flask import Flask, jsonify
from werkzeug.security import generate_password_hash

from web.public_server import validate_environment, configure_public_app
from web.auth import configure_auth, register_auth_routes
from web.workspace_store import WorkspaceStore


def environment(tmp_path):
    return {"BRACHYBOT_PUBLIC_ORIGIN": "https://brachy.example.com",
            "BRACHYBOT_API_KEY": "a" * 48, "BRACHYBOT_SECRET_KEY": "b" * 48,
            "BRACHYBOT_RUNTIME_DIR": str(tmp_path / "public-runtime")}


@pytest.mark.parametrize("key,value", [
    ("BRACHYBOT_PUBLIC_ORIGIN", "http://brachy.example.com"),
    ("BRACHYBOT_PUBLIC_ORIGIN", "https://brachy.example.com/path"),
    ("BRACHYBOT_API_KEY", "CHANGE_ME"),
    ("BRACHYBOT_ENABLE_SHELL_EXECUTOR", "1"),
    ("BRACHYBOT_TRUST_PROXY", "1"),
    ("BRACHYBOT_ALLOW_SELF_REGISTRATION", "true"),
    ("BRACHYBOT_RUNTIME_DIR", "/"),
    ("BRACHYBOT_PUBLIC_THREADS", "0"),
])
def test_invalid_environment_fails_before_opening_workspace(tmp_path, key, value):
    env = environment(tmp_path)
    env[key] = value
    with pytest.raises(ValueError):
        validate_environment(env)
    assert not (tmp_path / "public-runtime").exists()


def test_valid_environment_is_read_only(tmp_path):
    assert validate_environment(environment(tmp_path)) == ("brachy.example.com", 18082, 16)
    assert not (tmp_path / "public-runtime").exists()


def test_public_registration_login_csrf_and_host_boundary(tmp_path, monkeypatch):
    from web import server_support
    monkeypatch.setattr(server_support, "_API_KEY_REQUIRED", True)
    monkeypatch.setattr(server_support, "API_KEY", "internal-deployment-key")
    monkeypatch.setenv("BRACHYBOT_ALLOW_SELF_REGISTRATION", "0")
    monkeypatch.setenv("BRACHYBOT_COOKIE_SECURE", "1")
    app = Flask(__name__)
    store = WorkspaceStore(tmp_path / "runtime")
    configure_auth(app, store, {"secret_key": "test-secret"})
    register_auth_routes(app, store)
    configure_public_app(app, "brachy.example.com")
    user = store.create_user("invited", generate_password_hash("correct horse battery staple"))

    @app.route("/api/probe", methods=["GET", "POST"])
    def probe():
        return jsonify(ok=True)

    client = app.test_client()
    origin = "https://brachy.example.com"
    headers = {"X-API-Key": "internal-deployment-key"}
    response = client.post("/api/auth/register", base_url=origin, headers=headers,
                           json={"username": "uninvited", "password": "a long enough password"})
    assert response.status_code == 403
    assert response.json["code"] == "registration_closed"
    assert store.get_user_by_username("uninvited") is None
    assert client.get("/api/probe", base_url=origin).status_code == 401
    assert client.get("/api/probe", base_url="https://evil.example.com").status_code == 400
    assert client.get("/api/probe", base_url="http://brachy.example.com").status_code == 400
    credentials = {"username": user["username"], "password": "correct horse battery staple"}
    assert client.post("/api/auth/login", base_url=origin, json=credentials).status_code == 401
    login = client.post("/api/auth/login", base_url=origin, headers=headers, json=credentials)
    assert login.status_code == 200
    assert "Secure" in login.headers["Set-Cookie"]
    assert "HttpOnly" in login.headers["Set-Cookie"]
    assert client.post("/api/probe", base_url=origin).status_code == 403
    response = client.post("/api/probe", base_url=origin,
                           headers={"X-CSRF-Token": login.json["csrf_token"]})
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
