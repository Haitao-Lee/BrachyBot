"""Regression checks for the authenticated browser workspace bridge."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_authenticated_boot_uses_server_session_loader():
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    assert "window.loadSessions" in ui_api
    assert "window.__serverWorkspaceReady = true" in workspace
    assert "window.loadServerSessions" in workspace


def test_legacy_chat_bindings_delegate_to_durable_workspace():
    chat = read("web/app/static/js/brachybot-chat-core.js")
    assert "window.__serverWorkspaceReady" in chat
    assert "window.scheduleWorkspaceSave('chat.changed')" in chat
    assert "window.newChat !== newChat" in chat
    assert "window.switchSession !== switchSession" in chat
    assert "window.deleteSession !== deleteSession" in chat


def test_workspace_delete_uses_custom_confirmation_and_cancels_active_stream():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    chat_todo = read("web/app/static/js/brachybot-chat-todo.js")
    assert "confirmWorkspaceAction" in workspace
    assert "window.confirm" not in workspace
    assert "window.cancelActiveChatTurn" in chat_todo


def test_chat_snapshot_is_redrawn_after_restore():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    assert "Array.isArray(chat.messages)" in workspace
    assert "loadSessionChat(activeSessionId)" in workspace
    assert "sessions[activeSessionId].pending = false" in workspace
