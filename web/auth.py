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


def _persistent_development_secret(store: WorkspaceStore) -> str:
    """Return a private, restart-stable key for installations without one.

    Production deployments should still provide ``BRACHYBOT_SECRET_KEY``.
    For a local/LAN research installation, rotating an in-memory key on every
    server restart invalidates the authenticated browser before it can restore
    the user's durable cases. Store one random key beside the account database
    instead. ``O_EXCL`` keeps concurrent starters from replacing each other's
    key and mode 0600 prevents other local users from reading it.
    """
    path = store.runtime_dir / "auth_secret_key"
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return existing
    except FileNotFoundError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_urlsafe(48)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return existing
        raise RuntimeError(f"Persistent authentication key is invalid: {path}")
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(generated)
        handle.flush()
        os.fsync(handle.fileno())
    return generated


def _json_error(message: str, status: int):
    return jsonify({"error": message}), status


def configure_auth(app: Flask, store: WorkspaceStore, config: Optional[Dict[str, Any]] = None) -> None:
    """Configure cookie security and install the API authentication boundary."""
    config = config or {}
    secret = config.get("secret_key") or os.environ.get("BRACHYBOT_SECRET_KEY")
    if not secret:
        secret = _persistent_development_secret(store)
        app.logger.warning(
            "BRACHYBOT_SECRET_KEY is unset; using the private restart-stable key in %s",
            store.runtime_dir,
        )
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
    # A password change bumps the account's auth epoch. Sessions issued
    # before the rotation carry the previous epoch and are refused here, so
    # a cookie stolen before the rotation cannot outlive it.
    issued_epoch = int(session.get("bb_auth_epoch") or 0)
    if issued_epoch != int(user.get("auth_epoch") or 0):
        session.clear()
        return None
    return user


def _bind_session_identity(session_obj, user: Dict[str, Any]) -> None:
    """Record the authenticated identity and its current auth epoch."""
    session_obj["bb_user_id"] = user["id"]
    session_obj["bb_auth_epoch"] = int(user.get("auth_epoch") or 0)


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
        _bind_session_identity(session, user)
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
        _bind_session_identity(session, user)
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
        new_epoch = store.update_password_hash(user["id"], generate_password_hash(new_password))
        # Re-bind this browser to the new epoch so the session that performed
        # the rotation stays signed in; every other session for the account
        # now fails the epoch check in current_user and is revoked lazily.
        session["bb_auth_epoch"] = int(new_epoch)
        return jsonify({"success": True})


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": user["id"], "username": user["username"], "created_at": user["created_at"]}
