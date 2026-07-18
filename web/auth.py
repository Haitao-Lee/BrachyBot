"""Cookie authentication and request ownership helpers for BrachyBot."""

from __future__ import annotations

import os
import re
import secrets
from functools import wraps
from typing import Any, Callable, Dict, Optional

from flask import Flask, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from web.server_support import rate_limit, require_api_key
from web.workspace_store import WorkspaceError, WorkspaceStore


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
MIN_PASSWORD_LENGTH = 12


def _json_error(message: str, status: int):
    return jsonify({"error": message}), status


def configure_auth(app: Flask, store: WorkspaceStore, config: Optional[Dict[str, Any]] = None) -> None:
    """Configure cookie security and install the API authentication boundary."""
    config = config or {}
    secret = config.get("secret_key") or os.environ.get("BRACHYBOT_SECRET_KEY")
    if not secret:
        # A generated development key still protects credentials in-process,
        # but operators receive a clear signal that login cookies will expire
        # across server restarts until they configure a persistent secret.
        secret = secrets.token_urlsafe(48)
        app.logger.warning("BRACHYBOT_SECRET_KEY is unset; login cookies will reset after server restart")
    app.config.update(
        SECRET_KEY=secret,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=str(os.environ.get("BRACHYBOT_COOKIE_SECURE", "")).lower() in {"1", "true", "yes", "on"},
    )
    app.extensions["brachybot_workspace_store"] = store

    @app.before_request
    def _require_authenticated_api_user():
        if request.method == "OPTIONS" or not request.path.startswith("/api/"):
            return None
        if request.path.startswith("/api/auth/"):
            return None
        user = current_user(store)
        if not user:
            return _json_error("Authentication required", 401)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not csrf_valid():
            return _json_error("Invalid CSRF token", 403)
        return None


def current_user(store: WorkspaceStore) -> Optional[Dict[str, Any]]:
    user_id = session.get("bb_user_id")
    if not user_id:
        return None
    user = store.get_user_by_id(str(user_id))
    if not user or not bool(user.get("is_active")):
        session.clear()
        return None
    return user


def csrf_token() -> str:
    token = session.get("bb_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["bb_csrf_token"] = token
    return str(token)


def csrf_valid() -> bool:
    expected = session.get("bb_csrf_token")
    actual = request.headers.get("X-CSRF-Token", "")
    return bool(expected and actual and secrets.compare_digest(str(expected), str(actual)))


def login_required(store: WorkspaceStore):
    def decorator(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user(store):
                return _json_error("Authentication required", 401)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def register_auth_routes(app: Flask, store: WorkspaceStore) -> None:
    """Register open-account endpoints.  Case data is never accepted here."""

    @app.route("/api/auth/register", methods=["POST"])
    @require_api_key
    @rate_limit
    def auth_register():
        # The deployment API key is intentionally required before account
        # creation. It is a server-access boundary, while the session cookie
        # remains the user identity boundary; removing this guard would expose
        # an open registration endpoint whenever the service is network-bound.
        data = request.get_json(silent=True) or {}
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        if not USERNAME_RE.fullmatch(username):
            return _json_error("Username must be 3-64 characters: letters, digits, dot, dash, or underscore", 400)
        if len(password) < MIN_PASSWORD_LENGTH:
            return _json_error(f"Password must contain at least {MIN_PASSWORD_LENGTH} characters", 400)
        try:
            user = store.create_user(username, generate_password_hash(password))
            case = store.create_session(user["id"], "New case")
        except WorkspaceError as exc:
            return _json_error(str(exc), 409)
        session.clear()
        session["bb_user_id"] = user["id"]
        session["bb_session_id"] = case.id
        token = csrf_token()
        return jsonify({"success": True, "user": public_user(user), "active_session_id": case.id, "csrf_token": token}), 201

    @app.route("/api/auth/login", methods=["POST"])
    @require_api_key
    @rate_limit
    def auth_login():
        data = request.get_json(silent=True) or {}
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        user = store.get_user_by_username(username)
        if not user or not bool(user.get("is_active")) or not check_password_hash(str(user.get("password_hash") or ""), password):
            return _json_error("Invalid username or password", 401)
        sessions = store.list_sessions(user["id"])
        active = str(session.get("bb_session_id") or "")
        if not any(item.id == active for item in sessions):
            active = sessions[0].id if sessions else store.create_session(user["id"], "New case").id
        session.clear()
        session["bb_user_id"] = user["id"]
        session["bb_session_id"] = active
        token = csrf_token()
        return jsonify({"success": True, "user": public_user(user), "active_session_id": active, "csrf_token": token})

    @app.route("/api/auth/logout", methods=["POST"])
    @require_api_key
    @rate_limit
    def auth_logout():
        user = current_user(store)
        if user and not csrf_valid():
            return _json_error("Invalid CSRF token", 403)
        # Login state is intentionally cleared even when the session is already
        # invalid; callers receive a deterministic successful logout.
        session.clear()
        return jsonify({"success": True})

    @app.route("/api/auth/me", methods=["GET"])
    @require_api_key
    @rate_limit
    def auth_me():
        user = current_user(store)
        if not user:
            return _json_error("Authentication required", 401)
        active = str(session.get("bb_session_id") or "")
        try:
            store.get_session(user["id"], active)
        except WorkspaceError:
            entries = store.list_sessions(user["id"])
            active = entries[0].id if entries else store.create_session(user["id"], "New case").id
            session["bb_session_id"] = active
        return jsonify({"success": True, "user": public_user(user), "active_session_id": active, "csrf_token": csrf_token()})

    @app.route("/api/auth/password", methods=["POST"])
    @require_api_key
    @rate_limit
    def auth_change_password():
        user = current_user(store)
        if not user:
            return _json_error("Authentication required", 401)
        if not csrf_valid():
            return _json_error("Invalid CSRF token", 403)
        data = request.get_json(silent=True) or {}
        current_password = str(data.get("current_password") or "")
        new_password = str(data.get("new_password") or "")
        if not check_password_hash(str(user.get("password_hash") or ""), current_password):
            return _json_error("Current password is incorrect", 403)
        if len(new_password) < MIN_PASSWORD_LENGTH:
            return _json_error(f"Password must contain at least {MIN_PASSWORD_LENGTH} characters", 400)
        store.update_password_hash(user["id"], generate_password_hash(new_password))
        return jsonify({"success": True})


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": user["id"], "username": user["username"], "created_at": user["created_at"]}
