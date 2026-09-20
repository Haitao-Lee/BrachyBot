from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_backend_tags_the_final_response_delivery_phase():
    source = _read("agent_runtime/chat_workflows.py")

    assert 'phase="final_response"' in source
    assert '"Final Response"' in source


def test_frontend_keeps_final_response_pending_through_browser_work():
    source = _read("web/app/static/js/brachybot-chat-todo.js")

    assert "function _isFinalResponseTraceStep(step)" in source
    assert "_isFinalResponseTraceStep(displayStep)" in source
    assert "status: 'pending'," in source[source.index("const todoStep = _isFinalResponseTraceStep"):
                                             source.index("// MARK FOR RETRY")]
    assert "if (visualFinalResponsePending && finalResponseStep)" in source
    assert "_registerPendingVisualFinalResponse({" in source
    assert "_settlePendingVisualFinalResponse(" in source

    # The client must finish its screenshot/UI-action work before the final
    # response bubble and trace status are finalized.
    assert source.index("await Promise.allSettled(screenshotTasks)") < source.index("const finalText = finalResponseReceived")
    assert source.index("await _awaitChatUIActions(uiActionTasks") < source.index("const finalText = finalResponseReceived")

    # The old eager path marked every deferred final row done as soon as the
    # server stream ended, before the visible response was committed.
    assert "deferredFinalSteps.forEach(step => {\n            step.status = turnFailed ? 'error' : 'done';" not in source
    assert "finalReplyCommitted = Boolean(String(renderedFinalText || '').trim()" in source
    assert "if (!visualFinalResponsePending && unresolved.length)" in source


def test_visual_child_only_settles_parent_after_terminal_delivery():
    source = _read("web/app/static/js/brachybot-chat-todo.js")
    child_finally = source[source.index("if (isInternalFollowup) {", source.index("} finally {", source.index("async function sendChat"))):
                           source.index("const isCurrentTurn = window._chatTurnCancelUi")]

    assert "if (turnDetached || reconnectNeeded)" in child_finally
    assert "_settlePendingVisualFinalResponse(" in child_finally
    assert "turnFailed || !finalReplyCommitted ? 'error' : 'done'" in child_finally


def test_final_response_status_waits_for_send_cleanup():
    source = _read("web/app/static/js/brachybot-chat-todo.js")
    send_start = source.index("async function sendChat")
    cleanup_boundary = source.index("const isCurrentTurn = window._chatTurnCancelUi", send_start)
    finalizer_start = source.rfind("    } finally {", send_start, cleanup_boundary)
    finalizer_end = source.index("window._chatStreaming = false;", finalizer_start)
    assert finalizer_start >= 0
    assert source.index("_finishFinalResponseTraceSteps(", finalizer_start) < finalizer_end
    assert "const unresolvedFinalSteps =" not in source[send_start:finalizer_start]
    assert source.index("setStreamingState(false);", finalizer_end) > finalizer_end

def test_visual_child_waits_for_response_paint_before_settling():
    source = _read("web/app/static/js/brachybot-chat-todo.js")
    send_start = source.index("async function sendChat")
    finalizer_start = source.index("} finally {", send_start)
    child_finally = source[source.index("if (isInternalFollowup) {", finalizer_start):
                           source.index("const isCurrentTurn = window._chatTurnCancelUi", finalizer_start)]
    assert child_finally.index("await _waitForFinalReplyPaint()") < child_finally.index(
        "_settlePendingVisualFinalResponse("
    )


def test_final_reply_paint_wait_cannot_block_when_frames_are_throttled():
    source = _read("web/app/static/js/brachybot-chat-todo.js")
    start = source.index("function _waitForFinalReplyPaint()")
    end = source.index("function _sessionChatQueue", start)
    helper = source[start:end]

    assert "let settled = false;" in helper
    assert "document.visibilityState === 'hidden'" in helper
    assert "document.addEventListener('visibilitychange', visibilityHandler)" in helper
    assert "fallbackTimer = setTimeout(finish, 750);" in helper
    assert "if (settled) return;" in helper
