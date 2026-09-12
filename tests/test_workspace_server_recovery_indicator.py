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
    assert "await window.loadSessions()" in workspace
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
    assert 'static/js/brachybot-workspace.js?v=54' in index
