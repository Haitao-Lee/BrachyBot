"""Regression checks for the authenticated browser workspace bridge."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_authenticated_boot_uses_server_session_loader():
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    index = read("web/app/index.html")
    assert "window.loadSessions" in ui_api
    assert "window.__serverWorkspaceReady = true" in workspace
    assert "window.loadServerSessions" in workspace
    # The workspace bridge must load before report-export starts init(), or a
    # first page load can transiently select the legacy localStorage session.
    assert index.index("brachybot-workspace.js") < index.index("brachybot-report-export.js")


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


def test_session_switch_waits_for_server_chat_abort_acknowledgement():
    """A cancelled turn must finish targeting its old case before switching."""
    chat_todo = read("web/app/static/js/brachybot-chat-todo.js")
    stop_block = chat_todo.split("if (window._chatTurnActive)", 1)[1].split("const text =", 1)[0]

    assert "await fetch(API + '/chat/abort'" in stop_block
    assert "Chat abort was not acknowledged" in stop_block


def test_chat_snapshot_is_redrawn_after_restore():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    assert "Array.isArray(chat.messages)" in workspace
    assert "loadSessionChat(activeSessionId)" in workspace
    assert "sessions[activeSessionId].pending = false" in workspace


def test_llm_case_rename_uses_the_durable_session_api():
    """A chat-driven rename must survive refresh just like a manual rename."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")

    assert "window.renameServerSession(activeSessionId, title)" in ui_api
    assert "Durable case renaming is unavailable" in ui_api
    assert "api/sessions/${encodeURIComponent(id)}" in workspace


def test_session_ui_actions_wait_for_durable_case_transitions():
    """The UI-controller trace must not complete before a case transition."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")

    assert "if (target === 'session.new') return window.newChat();" in ui_api
    assert "if (target === 'session.switch') return window.switchSession(value);" in ui_api
    assert "return window.deleteSession(value, { skipConfirm: true });" in ui_api
    assert "return { success: true, session_id: activeSessionId };" in workspace
    assert "return { success: true, active_session_id: activeSessionId };" in workspace


def test_server_workspace_serializes_case_transitions():
    """Concurrent sidebar clicks must not restore a stale case snapshot."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    layout = read("web/app/static/css/brachybot-theme-layout.css")

    assert "let workspaceTransition = null;" in workspace
    assert "async function runWorkspaceTransition(operation)" in workspace
    assert "await recoverWorkspaceAfterTransitionFailure();" in workspace
    assert "async function recoverWorkspaceAfterTransitionFailure()" in workspace
    assert "clearScheduledWorkspaceSave();" in workspace
    assert workspace.count("return runWorkspaceTransition(async () => {") >= 3
    assert "workspaceTransition = null;" in workspace
    assert "body.workspace-transitioning #sessionList" in layout


def test_delayed_scene_restore_is_scoped_to_its_case_generation():
    """A late mesh/DVH callback from an old case must not repaint the new one."""
    workspace = read("web/app/static/js/brachybot-workspace.js")

    assert "let workspaceRestoreGeneration = 0;" in workspace
    assert "const workspaceRestoreTimers = new Set();" in workspace
    assert "function invalidateDeferredWorkspaceRestore()" in workspace
    assert "function scheduleDeferredWorkspaceRestore(generation, callback, delay)" in workspace
    assert "if (generation !== workspaceRestoreGeneration) return;" in workspace
    assert "const restoreGeneration = invalidateDeferredWorkspaceRestore();" in workspace
    assert "restoreSceneView(uiState.viewer?.scene, uiState.viewer?.dvh, restoreGeneration);" in workspace


def test_ui_controller_waits_for_async_viewer_and_manual_planning_actions():
    """UI action progress must represent completion, not merely task launch."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    manual = read("web/app/static/js/brachybot-manual-annotation.js")

    assert "return navigateToDosePeakSlices();" in ui_api
    assert "return Promise.all(organs.map(o => reconstructOrgan3D(o.id, true)));" in ui_api
    assert "return resetSession();" in ui_api
    assert "return startTrainingMode(value || 'Monitor planning workflow')" in ui_api
    assert "return clearCurrentChatHistory({ skipConfirm: true });" in ui_api
    assert "return { success: true, step: 'full' };" in manual
    assert "return { success: true, kind, labels: n };" in manual
    assert "Planning reset failed:" in manual


def test_legacy_session_clear_action_is_honest_about_its_scope():
    """The LLM catalog must never claim cache cleanup deletes clinical cases."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    registry = read("tool_factory/ui_controller/__init__.py")

    assert "browser_cache.clear" in ui_api
    assert "Persistent server cases will be retained" in ui_api
    assert '"browser_cache.clear"' in registry
    assert "durable server cases are retained" in registry


def test_manual_case_rename_waits_for_durable_confirmation():
    """A rejected lease write must not leave a fictional title in the sidebar."""
    chat = read("web/app/static/js/brachybot-chat-core.js")
    block = chat.split("const saveRename = async () =>", 1)[1].split("input.addEventListener", 1)[0]

    assert block.index("try {") < block.index("session.title = newTitle;")
    assert "session.title = currentTitle;" in block


def test_chat_restore_preserves_non_adjacent_repeated_messages():
    """Historical retry cleanup must not erase legitimate later repeats."""
    chat = read("web/app/static/js/brachybot-chat-core.js")
    block = chat.split("function loadSessionChat", 1)[1].split("function saveSessionMessage", 1)[0]

    assert "sameAdjacentMessage" in block
    assert "canonicalType" in block
    assert "const seen = new Set();" not in block


def test_active_progress_animation_stops_only_for_terminal_or_reduced_motion_states():
    todo = read("web/app/static/js/brachybot-chat-todo.js")
    status_css = read("web/app/static/css/brachybot-chat-status.css")
    report_css = read("web/app/static/css/brachybot-report-controls.css")
    responsive_css = read("web/app/static/css/brachybot-responsive.css")

    assert "todo-active-breathe 1.8s ease-in-out infinite" in status_css
    assert "item.node.classList.remove('pending', 'active', 'predicted')" in todo
    assert "item.node.classList.add(item.status)" in todo
    assert "animation-duration: 2.4s !important" not in report_css
    assert "animation: none !important" in report_css
    assert "animation: none !important" in responsive_css


def test_report_modal_has_keyboard_safe_close_path():
    report_shell = read("web/app/static/js/brachybot-report-shell.js")
    report_css = read("web/app/static/css/brachybot-report-controls.css")
    assert "role=\"dialog\"" in report_shell
    assert "event.key === 'Escape'" in report_shell
    assert "const focusable" in report_shell
    assert ".rp-modal-overlay" in report_css


def test_report_actions_use_the_app_confirmation_modal_not_browser_confirm():
    report_shell = read("web/app/static/js/brachybot-report-shell.js")
    report_export = read("web/app/static/js/brachybot-report-export.js")
    assert "window._confirmAction" in report_shell
    assert "window._confirmAction" in report_export
    assert "confirm(" not in report_shell
    assert "confirm(" not in report_export


def test_legacy_browser_actions_do_not_fall_back_to_native_confirm():
    chat_core = read("web/app/static/js/brachybot-chat-core.js")
    assert "window.confirm" not in chat_core
    assert "async function clearLocalChatData" in chat_core
    assert "window._confirmAction" in chat_core


def test_viewer_and_upload_failures_use_non_blocking_application_notices():
    """Failure feedback must not freeze a WebGL gesture behind browser alerts."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    viewer = read("web/app/static/js/brachybot-viewer-layout.js")
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    theme = read("web/app/static/css/brachybot-theme-layout.css")

    assert "function showBrachyBotNotice" in ui_api
    assert "window.showBrachyBotNotice" in ui_api
    assert "alert(" not in ui_api
    assert "alert(" not in viewer
    assert "alert(" not in manual
    assert ".app-notice-stack" in theme


def test_deployment_api_key_has_a_session_scoped_login_path():
    """A protected deployment must not leave the account screen at a 401 dead end."""
    index = read("web/app/index.html")
    auth = read("web/app/static/js/brachybot-auth.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")

    assert 'id="authDeploymentKey"' in index
    assert "setDeploymentAccessKey" in auth
    assert "revealDeploymentKeyHelp" in auth
    assert "sessionStorage.setItem('BRACHYBOT_API_KEY'" in ui_api
    assert "localStorage.setItem('BRACHYBOT_API_KEY'" not in ui_api
