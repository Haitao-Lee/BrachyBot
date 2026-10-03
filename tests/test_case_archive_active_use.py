"""Regression tests: an actively used case must never be swept to cold storage.

``last_accessed_at`` historically advanced only on an explicit case selection,
so a case left open in a browser drifted past the archive window and the hourly
idle sweep moved it to cold storage mid-session. The next chat turn then could
not hydrate the archived case and reported a misleading "case resources failed
to load" error after a 120 s retry. These tests lock the guard in place.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from web.routes.planning_routes import _case_record_is_archived
from web.server import (
    _case_access_persist_due,
    _case_agent_recently_active,
)


def test_cached_recently_used_agent_marks_case_active():
    now = 10_000.0
    cached = object()
    # Touched 5 minutes ago, one-hour active window -> still in use.
    assert _case_agent_recently_active(cached, now - 300, now, 3600) is True
    # Idle past the window -> eligible for archival.
    assert _case_agent_recently_active(cached, now - 3601, now, 3600) is False
    # No cached agent -> eligible.
    assert _case_agent_recently_active(None, now, now, 3600) is False
    # No in-memory timestamp -> eligible.
    assert _case_agent_recently_active(cached, None, now, 3600) is False


def test_access_persistence_is_throttled():
    now = 10_000.0
    assert _case_access_persist_due(None, now, 300) is True
    assert _case_access_persist_due(now - 299, now, 300) is False
    assert _case_access_persist_due(now - 300, now, 300) is True


def test_case_record_is_archived_detection():
    assert _case_record_is_archived(SimpleNamespace(storage_status="archived")) is True
    assert _case_record_is_archived(SimpleNamespace(storage_status="active")) is False
    assert _case_record_is_archived(SimpleNamespace()) is False


def _build_app(tmp_path, monkeypatch):
    from web.server import create_app

    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    app = create_app({
        "runtime_dir": str(tmp_path / "server-runtime"),
        "secret_key": "test-secret",
        "workspace_maintenance": False,
        "expose_internal_seams": True,
    })
    return app


def _make_stale_case(app, title):
    store = app.extensions["brachybot_workspace_store"]
    user = store.create_user(f"archive_{title}", "hash")
    case = store.create_session(user["id"], title)
    old = time.time() - 8 * 24 * 60 * 60
    with store._connection() as connection:
        connection.execute(
            "UPDATE case_sessions SET last_accessed_at = ? WHERE id = ?",
            (old, case.id),
        )
    return store, user, case, old


def test_active_use_refreshes_access_and_avoids_archival(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    store, user, case, old = _make_stale_case(app, "active")
    sessions, timestamps, lock = app.extensions["brachybot_agent_cache"]
    with lock:
        sessions[(user["id"], case.id)] = object()
        timestamps[(user["id"], case.id)] = time.time()

    app.extensions["brachybot_archive_scan"]()

    record = store.get_session(user["id"], case.id)
    assert record.storage_status == "active"
    assert record.last_accessed_at > old


def test_idle_case_without_cached_agent_is_archived(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    store, user, case, _old = _make_stale_case(app, "idle")
    sessions, timestamps, lock = app.extensions["brachybot_agent_cache"]
    with lock:
        sessions.clear()
        timestamps.clear()

    app.extensions["brachybot_archive_scan"]()

    record = store.get_session(user["id"], case.id)
    assert record.storage_status == "archived"


def test_chat_on_archived_case_fails_fast_with_activation_hint(tmp_path, monkeypatch):
    monkeypatch.delenv("BRACHYBOT_API_KEY", raising=False)
    monkeypatch.delenv("BRACHYBOT_REQUIRE_API_KEY", raising=False)
    app = _build_app(tmp_path, monkeypatch)
    client = app.test_client()
    registered = client.post(
        "/api/auth/register",
        json={"username": "archive_chat", "password": "archive-password-123"},
    ).get_json()
    token = registered["csrf_token"]
    session_id = registered["active_session_id"]
    store = app.extensions["brachybot_workspace_store"]
    store.archive_session(registered["user"]["id"], session_id)

    started = time.perf_counter()
    response = client.post(
        "/api/chat",
        json={"message": "are you still online?", "stream": True},
        headers={"X-CSRF-Token": token, "X-BrachyBot-Session": session_id},
    )
    elapsed = time.perf_counter() - started
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "session_archived" in body
    # The durable archived state must not be waited out as if the case were
    # still cold-starting (the resolve timeout is 120 s).
    assert elapsed < 30.0
