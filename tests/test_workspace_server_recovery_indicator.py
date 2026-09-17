from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_server_restart_recovery_keeps_a_visible_resource_loading_boundary():
    workspace = _source("web/app/static/js/brachybot-workspace.js")
    index = _source("web/app/index.html")

    # A live tab does not receive a DOM reload when only the Python server is
    # restarted. The workspace bridge therefore needs its own control-plane
    # probe and must enter the same case-owned restore path on recovery.
    assert "startWorkspaceServerHealthMonitor" in workspace
    assert "checkWorkspaceServerHealth" in workspace
    assert "workspaceServerAvailable === false" in workspace
    assert "workspaceServerInstanceId" in workspace
    assert "server_instance_id" in workspace
    assert "const restarted = Boolean(" in workspace
    assert "void recoverWorkspaceAfterServerRestart()" in workspace
    assert "await window.loadSessions({" in workspace
    assert "preserveVisibleClinicalState" in workspace
    assert "loadSessionsInFlight" in workspace
    # A transient health-probe timeout during planning/report capture must not
    # be treated as a process restart. Full case hydration is allowed only
    # after the server's process-scoped instance id changes.
    assert "const previousServerInstanceId = workspaceServerInstanceId;" in workspace
    assert "if (restarted) {" in workspace
    assert "if (restarted || recovered || workspaceServerRecoveryPending)" not in workspace
    assert "workspaceServerRecoveryPending = false;" in workspace

    # The indicator must be visible before the slow snapshot request, not
    # only after the server has finished rebuilding the workspace response.
    assert "window.showCaseResourceLoading?.({" in workspace
    assert "runId: `startup-${Date.now()}`" in workspace
    assert "startWorkspaceServerHealthMonitor();" in workspace

    # Force the browser to fetch the updated workspace bridge after a server
    # restart instead of retaining the prior cached script.
    assert 'static/js/brachybot-workspace.js?v=59' in index


def test_restart_recovery_notice_is_not_a_second_loading_spinner():
    """Chat recovery owns its transcript warning; resource loading stays separate."""
    workspace = _source("web/app/static/js/brachybot-workspace.js")
    chat_todo = _source("web/app/static/js/brachybot-chat-todo.js")
    index = _source("web/app/index.html")
    css = _source("web/app/static/css/brachybot-auth.css")

    recovery_markup = index.split('id="workspaceRecoveryNotice"', 1)[1].split('</div>', 1)[0]
    assert 'workspace-recovery-icon' in recovery_markup
    assert 'workspace-hydration-spinner' not in recovery_markup
    assert 'static/css/brachybot-auth.css?v=9' in index

    render = workspace.split('function renderRecoveryNotice', 1)[1].split('function applyChatSnapshotFast', 1)[0]
    assert 'recoveryTranscriptContainsNotice' in render
    assert 'chatStillActive' in render
    assert 'sameNoticeVisible' in render
    assert 'setTimeout' in render
    assert 'showCaseResourceLoading' not in render
    assert 'workspaceHydrationNotice' not in render
    assert 'hideWorkspaceRecoveryNotice' in render

    recovery_helper = chat_todo.split('function _addTaskRecoveryNotice', 1)[1].split('function _scheduleCasePlanningRefresh', 1)[0]
    assert "messageKind: 'task_recovery_notice'" in recovery_helper
    assert 'window.hideWorkspaceRecoveryNotice?.' in recovery_helper
    assert 'workspaceHydrationNotice' not in recovery_helper

    recovery_css = css.split('.workspace-recovery-notice {', 1)[1].split('}', 1)[0]
    assert 'var(--warning)' in recovery_css
    assert '.workspace-recovery-icon' in css
