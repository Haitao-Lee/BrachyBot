"""Frontend contract for the case edit-lease conflict on the chat path.

The lease middleware rejects a mutating request while another browser owns the
case. The chat UI must explain that state and surface the takeover action
instead of the generic "request could not be completed" message, and a
finished turn must not leave its explicit-stop flag behind for the next turn.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_TODO = "web/app/static/js/brachybot-chat-todo.js"


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_chat_lease_conflict_surfaces_takeover_instead_of_generic_failure():
    chat_todo = _read(CHAT_TODO)
    assert "function _chatWorkspaceLockedMessage(" in chat_todo
    assert "resp.status === 409 && serverCode === 'workspace_locked'" in chat_todo
    assert "window.brachybotAuth?.acquireLease?.(turnSessionId)" in chat_todo
    assert "该病例正在另一个浏览器中编辑" in chat_todo
    # The generic failure text must stay for real transport/provider errors.
    assert "本次请求暂时无法完成" in chat_todo


def test_terminal_turn_clears_the_explicit_stop_flag():
    chat_todo = _read(CHAT_TODO)
    # The terminal cleanup block is the only place that clears the parent
    # request identity; the stop path uses the session-scoped abort key.
    anchor = "window._activeChatParentRequestId = null;"
    assert anchor in chat_todo
    tail = chat_todo.split(anchor, 1)[1][:600]
    assert "delete window._explicitChatStopSessions[turnSessionId];" in tail
