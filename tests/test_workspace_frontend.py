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
    assert 'id="workspaceLockDismiss"' in index
    assert 'id="workspaceRecoveryDismiss"' in index


def test_chat_ui_state_capture_and_workspace_conflicts_are_non_blocking():
    """Optional UI context cannot block chat, and stale saves have one repair path."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    chat = read("web/app/static/js/brachybot-chat-todo.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    routes = read("web/routes/session_routes.py")

    assert "function _cloneUiStateValue" in ui_api
    assert "function _collectUIState" in ui_api
    assert "_cloneUiStateValue(dataTreeState.expansionState)" in ui_api
    assert "jsonClone(dataTreeState.expansionState)" not in ui_api
    assert "Optional UI state capture failed; sending request without it" in chat
    assert "workspaceSaveInFlight" in workspace
    assert "workspaceSaveQueuedReasons" in workspace
    assert "for (let attempt = 0; attempt < 2; attempt += 1)" in workspace
    assert 'payload["current_revision"] = current_revision' in routes
    assert '"stale_workspace" if is_stale_revision else "workspace_locked"' in routes


def test_ct_data_tree_window_level_controls_share_the_viewer_state():
    """The CT row uses one live dual-handle range backed by Viewer W/L state."""
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    controls = read("web/app/static/css/brachybot-report-controls.css")

    assert "function setViewerWindowLevel" in volume
    assert "function applyDataTreeWindowRange" in volume
    assert "window.applyDataTreeWindowRange = applyDataTreeWindowRange" in volume
    assert 'data-ct-window-level="low"' in volume
    assert 'data-ct-window-level="high"' in volume
    assert 'type="range"' in volume
    assert "normalized.high - normalized.low" in volume
    assert "(normalized.high + normalized.low) / 2" in volume
    assert "renderDelayMs: 16" in volume
    assert "persistOnNoChange: persist" in volume
    assert "_syncWindowLevelControls();" in volume
    assert "viewer.window_level.data_tree" in volume
    assert "clearSliceCache();" in volume
    assert ".ct-window-level-controls" in controls
    assert ".ct-window-range-fill" in controls
    assert "pointer-events: auto" in controls
    assert ".tree-item--ct .item-info { display: none; }" in controls


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
    # Removing another case must not cancel a plan currently running in the
    # selected case. Only the selected-case branch may enter the transition
    # path that calls prepareSessionChange().
    inactive_branch = workspace.split("if (id !== activeSessionId)", 1)[1].split(
        "return runWorkspaceTransition", 1
    )[0]
    assert "prepareSessionChange" not in inactive_branch
    assert "void loadServerSessions().then(() => renderSessionList())" in inactive_branch


def test_deleted_case_browser_state_is_cleared_only_after_server_success():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    delete_block = workspace.split("window.deleteSession =", 1)[1].split(
        "window.renameServerSession", 1
    )[0]
    assert "async function clearDeletedSessionBrowserData" in workspace
    assert "window.SessionCache.invalidateSession(id)" in workspace
    assert "storage.removeItem(key)" in workspace
    assert "delete legacySessions[id]" in workspace
    assert "delete window._sessionChatTaskIds?.[id]" in workspace
    assert delete_block.index("if (!response.ok)") < delete_block.index(
        "await clearDeletedSessionBrowserData(id)"
    )


def test_session_delete_is_permanent_and_recycle_bin_is_not_exposed_in_the_ui():
    index = read("web/app/index.html")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    delete_block = workspace.split("window.deleteSession =", 1)[1].split(
        "window.renameServerSession", 1
    )[0]
    assert 'id="recycleBinCount"' not in index
    assert 'id="recycleBinPanel"' not in index
    assert "/purge`" in delete_block


def test_startup_renders_server_session_directory_before_the_heavy_snapshot():
    """A slow restored case must never keep the left session list empty."""
    auth = read("web/app/static/js/brachybot-auth.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    load_sessions = workspace.split("window.loadSessions =", 1)[1].split(
        "window.saveSessions =", 1
    )[0]

    assert "let authenticationPromise = null;" in auth
    assert "if (authenticationPromise) return authenticationPromise;" in auth
    assert "void acquireLease()" in auth
    assert "renderSessionList();" in load_sessions
    assert load_sessions.index("renderSessionList();") < load_sessions.index(
        "await loadActiveWorkspace()"
    )
    assert "startup.session_list_first_paint" in load_sessions


def test_session_restore_uses_corner_non_blocking_hydration_and_fresh_snapshot():
    """Case switching must show progress without masking the workspace."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    css = read("web/app/static/css/brachybot-auth.css")
    assert "authoritativeWorkspace" in workspace
    assert "'/api/workspace/snapshot'" in workspace
    assert "X-BrachyBot-Session" in workspace
    assert ".workspace-hydration-notice" in css
    assert "position: fixed" in css
    assert "right: 18px" in css
    assert "bottom: 18px" in css
    assert "body.workspace-hydrating::after { display: none; }" in css
    assert "pointer-events: none" in css
    assert "workspaceSnapshotHasClinicalResources" in workspace
    assert "initial case has no clinical resources; hydration skipped" in ui_api


def test_session_restore_fits_all_viewers_with_authoritative_session_guard():
    """The final restore pass must reset MPR geometry without cross-case races."""
    layout = read("web/app/static/js/brachybot-viewer-layout.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    assert "async function fitAllViewersAfterWorkspaceRestore" in layout
    assert "_activeApiSessionId" in layout
    assert "await loadAllSlices()" in layout
    assert "reconcile2DViewerLayers" in layout
    assert "ensureCameraFitsVisibleScene" in layout
    assert "fitAllViewersAfterWorkspaceRestore" in ui_api
    assert "reason: 'workspace-hydration-fit'" in ui_api


def test_report_restore_does_not_erase_newer_generated_text():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    report = read("web/app/static/js/brachybot-report-export.js")
    assert "function _preservePopulatedReport" in workspace
    assert "_reportNarrativeLength(current) > 0" in workspace
    assert "const keepCurrentReport = _preservePopulatedReport" in workspace
    assert "f.updatedAt = Date.now();" in report
    assert "window.cancelScheduledWorkspaceSave" in report
    assert "async function persistWorkspace(reason, options = {})" in workspace
    assert "options.allowDuringRestore" in workspace
    assert "sessionId: ownerSessionId" in report
    assert "workspaceSavePayload(ownerSessionId, reason)" in workspace
    assert "reportState(ownerSessionId)" in workspace
    assert "const previousCaseFlush = typeof flushActiveReportState === 'function'" in workspace
    assert "flushActiveReportState({ sessionId: previousSessionId })" in workspace
    assert "ownerSessionId !== String(activeSessionId || '')" in workspace
    assert "function reportFormFromSnapshot" in workspace
    assert "const reportSection = snapshot.report" in workspace


def test_report_restore_is_session_bound_and_uses_agent_planning_identity():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    assert "function workspacePlanningIdentity" in workspace
    assert "results.active_planning_id || results.planning_run_id" in workspace
    assert "planningIdentity.activeId" in workspace
    assert "function sessionBoundReportMap" in workspace
    assert "window.__reportWorkspaceSessionId = sessionId" in workspace
    assert "window.__reportWorkspaceByPlanning = reportMap" in workspace
    assert "declaredReportPlanningId === targetPlanningId" in workspace
    assert "report.session-planning-ownership.repaired" in workspace
    assert "window.__reportWorkspaceByPlanning = {}" in ui_api
    assert "window.__reportWorkspaceSessionId = null" in ui_api


def test_missing_report_figure_metadata_is_rebuilt_from_durable_artifacts():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    assert "async function restoreReportFiguresFromArtifacts" in workspace
    assert "hydrateDataTreeArtifactCatalog" in workspace
    assert "report_screenshot_" in workspace
    assert "report.figures.restored-from-catalog" in workspace
    assert "_serverUrl" in workspace


def test_report_quality_columns_are_persisted_and_auto_fill_is_awaited():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    report = read("web/app/static/js/brachybot-report-export.js")
    shell = read("web/app/static/js/brachybot-report-shell.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")
    assert "qualityAssessment" in workspace
    assert "function syncReportQualityAssessment" in report
    assert "_storedMetricAssessment" in report
    assert "inputFingerprint" in report
    assert "refreshCriteria: options.refreshCriteria === true" in shell
    assert "function reportNeedsSourceBackedQualityRefresh(form)" in report
    assert "window.reportNeedsSourceBackedQualityRefresh" in report
    assert "window.Report.autoFill.fromAll({" in planning
    assert "captureFigures: false" in planning
    assert "window.syncReportQualityAssessment(f, { force: true })" not in shell
    assert "await Report.autoFill.fromAll()" in planning


def test_report_source_restore_is_bound_to_the_selected_session():
    """Late report metadata from another case must not overwrite this case."""
    shell = read("web/app/static/js/brachybot-report-shell.js")
    assert "function _activeReportSessionId" in shell
    assert "function _reportSessionIsCurrent" in shell
    assert "'X-BrachyBot-Session': _activeReportSessionId(sessionId)" in shell
    assert "const expectedSessionId = _activeReportSessionId(opts.sessionId)" in shell
    assert "if (!isCurrent()) return { stale: true, applied: 0 };" in shell


def test_report_recapture_is_durably_scheduled_after_viewer_hydration():
    planning = read("web/app/static/js/brachybot-dvh-planning.js")
    store = read("web/workspace_store.py")
    assert "_scheduleReportAutoSave" in planning
    assert "def _merge_report_patch" in store
    assert "elif key == \"report\":" in store


def test_startup_and_session_switch_share_the_same_corner_resource_notice():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    assert "window.showCaseResourceLoading" in workspace
    assert "window.showCaseResourceLoading?.({ sessionId: id })" in workspace
    assert "window.showCaseResourceLoading?.({ sessionId, runId: generation })" in workspace
    assert "window.showCaseResourceLoading?.(hydrationScope)" in ui_api


def test_task_stream_has_keepalive_and_workspace_restore_has_stale_notice_fallback():
    chat_tasks = read("web/chat_tasks.py")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    assert "brachybot-task-alive" in chat_tasks
    assert "hydrationHideTimer" in workspace
    assert "background restore skipped: empty or stale case" in workspace
    assert "window.__workspaceHydrationRunId = (window.__workspaceHydrationRunId || 0) + 1" in workspace
    assert "scope?.immediate === true" in workspace
    assert "notice.hidden = true" in workspace


def test_surgical_guide_empty_tool_call_uses_generate_default():
    """The chat tool may omit action when requesting the default guide."""
    tool = read("tool_factory/surgical_guide/__init__.py")
    assert '"default": "generate"' in tool
    assert '"required": []' in tool
    assert 'or "generate"' in tool


def test_planning_completion_refresh_is_not_tied_to_one_trace_shape():
    """Every real planning event must converge on one case-owned UI refresh."""
    chat = read("web/app/static/js/brachybot-chat-todo.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")
    assert "const PLANNING_EVENT_TOOLS = new Set" in chat
    assert "parentTool" in chat
    assert "turnSawPlanningWork" in chat
    assert "if (_planningToolsInSteps.length > 0 || turnSawPlanningWork)" in chat
    assert "retryPending: true" in chat
    assert "autoGenerateGuide: true" in chat
    assert "await guideRestorePromise" in planning
    assert "reconcileDataTreeVisualNodes" in planning


def test_geometry_only_planning_runs_are_restored_after_restart():
    """A draft without dose keys still enters the cold-restore planning path."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    assert "storedKeys.has('planning_runs')" in ui_api
    assert "String(key).startsWith('planning_run:')" in ui_api
    assert "key.startsWith('planning_run:')" in workspace


def test_planning_activation_clears_the_previous_dvh_instance():
    """Switching runs cannot leave the previous Plotly chart on screen."""
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    clear_block = manual.split("function clearPlanningVisualization()", 1)[1].split(
        "// Delete a seed", 1
    )[0]
    assert "Plotly.purge(dvhElement)" in clear_block


def test_final_chat_commit_separates_transcript_from_heavy_checkpoint():
    """The response is released after the small transcript write, not NPY I/O."""
    routes = read("web/routes/planning_routes.py")
    block = routes.split("def finalize_chat_task", 1)[1].split("def owned_case_path", 1)[0]
    assert "store.flush_agent_checkpoint" in block
    assert "checkpoint_thread.start()" in block
    assert '"persist_state": "pending"' in block
    assert '"chat.task.finalized.background"' in block
    assert 'task.commit_step("done")' not in block


def test_viewer_render_posts_do_not_schedule_workspace_checkpoints():
    """Slice/overlay refreshes are reads even though their transport is POST."""
    server = read("web/server.py")
    assert "viewer_read_posts" in server
    for path in (
        "/api/viewer/slice",
        "/api/viewer/overlay",
        "/api/viewer/3d",
        "/api/viewer/3d_mask",
        "/api/viewer/3d_skin",
    ):
        assert path in server


def test_new_case_creation_avoids_empty_workspace_hydration_and_redundant_round_trips():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    auth = read("web/app/static/js/brachybot-auth.js")
    sessions = read("web/routes/session_routes.py")
    new_case = workspace.split("window.newChat =", 1)[1].split("window.switchSession =", 1)[0]
    assert "await loadServerSessions()" not in new_case
    assert "previousCaseFlush = typeof flushActiveReportState === 'function'" in new_case
    assert "flushActiveReportState({ sessionId: previousSessionId })" in new_case
    assert "void previousCaseFlush.catch" in new_case
    assert "window.awaitActiveSessionReady" in workspace
    assert "The optimistic shell" in workspace
    assert "void persistWorkspace('session.switching')" not in new_case
    assert "paintSessionShell(optimisticId, { blank: true, clearWorkspace: false })" in new_case
    assert "await yieldWorkspaceShellPaint()" in new_case
    assert "function paintSessionShell(sessionId, { clearWorkspace = true, blank = false } = {})" in workspace
    assert "if (blank)" in workspace
    assert "clearClientWorkspace({ clearReport: true, deferDisposal: true })" in workspace
    assert "scheduleBackgroundWorkspaceRestore" not in new_case
    assert "applyLeaseResult" in new_case
    assert "function applyLeaseResult" in auth
    assert '"lease": lease' in sessions
    assert "sessions[createdSession.id] = sessionStateFromPayload(createdSession)" in new_case
    assert new_case.index("sessions[createdSession.id]") < new_case.index("renderSessionList()")
    assert "window.setWorkspaceHydrationState?.(false)" in new_case
    shell = workspace.split("function paintSessionShell", 1)[1].split(
        "async function loadServerSessions", 1
    )[0]
    assert "sessionDisplay.textContent = sessionId" in shell


def test_workspace_transitions_publish_measurable_first_paint_and_restore_stages():
    """Session latency must be observable instead of hidden behind one loader."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    index = read("web/app/index.html")

    assert "window.__workspacePerformance" in workspace
    assert "brachybot:workspace-performance" in workspace
    assert "create.shell_first_paint" in workspace
    assert "switch.shell_first_paint" in workspace
    assert "switch.presentation_ready" in workspace
    assert "startup.chat_first_paint" in workspace
    assert "restore.ct_first_paint" in ui_api
    assert "restore.labels_data_tree" in ui_api
    assert "restore.planning_dvh" in ui_api
    assert "restore.report_and_presentation" in ui_api
    assert "restore.fully_interactive" in ui_api
    # Versioned URLs are intentional cache invalidation points. Keep this
    # assertion aligned with the workspace/report artifact restore contract.
    assert "brachybot-workspace.js?v=37" in index
    assert "brachybot-ui-api.js?v=49" in index
    assert "brachybot-viewer-volume.js?v=43" in index
    assert "brachybot-manual-annotation.js?v=18" in index


def test_case_owned_api_requests_never_use_presentation_placeholders():
    """Uploads and data requests must carry only durable server case IDs."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")

    session_helper = ui_api.split("function _activeApiSessionId()", 1)[1].split(
        "function _shouldLogTrainingFeedback", 1
    )[0]
    assert "'web'" not in session_helper
    assert "/^[a-f0-9]{32}$/.test(normalized)" in session_helper

    fetch_wrapper = ui_api.split("function brachybotFetch", 1)[1].split(
        "// Abort controller for stopping streaming responses", 1
    )[0]
    assert "controlPlaneRequest" in fetch_wrapper
    assert "requestSessionId && !controlPlaneRequest" in fetch_wrapper

    upload = ui_api.split("async function handleFileSelect", 1)[1].split(
        "/** Import a user-provided label", 1
    )[0]
    assert "await window.awaitActiveSessionReady()" in upload
    assert "await window.reconcileActiveSession(ownerSessionId)" in upload
    assert "headers: { 'X-BrachyBot-Session': ownerSessionId }" in upload

    assert "window.reconcileActiveSession" in workspace


def test_transition_recovery_uses_the_server_authoritative_case():
    """A stale browser case must not cascade 404s after transition failure."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    recovery = workspace.split("async function recoverWorkspaceAfterTransitionFailure", 1)[1].split(
        "window.loadSessions", 1
    )[0]
    assert "const recoverySessionId" in recovery
    assert "sessionId: recoverySessionId" in recovery
    assert "loadActiveWorkspace({ commit: false" not in recovery


def test_workspace_fetch_preserves_external_transition_abort_semantics():
    """A superseded switch is cancellation, not a misleading timeout error."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    fetch_block = workspace.split("async function workspaceFetch", 1)[1].split(
        "function setWorkspaceHydrationState", 1
    )[0]
    assert "const externalSignal = init?.signal || null" in fetch_block
    assert "if (externalSignal?.aborted) throw error" in fetch_block
    assert "Workspace request timed out" in fetch_block


def test_clinical_restore_can_only_close_its_own_hydration_notice():
    """A stale restore must not mutate the loading state of a newer case."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    restore = ui_api.split(
        "async function restoreActiveSessionWorkspace(options = {})", 1
    )[1].split("window.restoreActiveSessionWorkspace =", 1)[0]
    assert "const hydrationScope = { sessionId: sessionAtStart, runId: hydrationRunId }" in restore
    assert "window.setWorkspaceHydrationState?.(false, '', hydrationScope)" in restore
    assert "window.setWorkspaceHydrationState?.(false);" not in restore


def test_session_switch_detaches_browser_stream_without_server_abort():
    """Switching cases detaches this tab while the server task keeps running."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    chat_todo = read("web/app/static/js/brachybot-chat-todo.js")
    assert "detachActiveChatTurn" in workspace
    transition_block = workspace.split("async function prepareSessionChange", 1)[1].split(
        "async function runWorkspaceTransition", 1
    )[0]
    assert "fetch(API + '/chat/abort'" not in transition_block
    assert "cancelActiveChatTurn" in chat_todo
    assert "window._chatTurnCancelUi" in chat_todo


def test_case_switch_clears_only_case_scoped_progress_presentation():
    """Old timers must not leak into a new case or cancel the server task."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    chat_todo = read("web/app/static/js/brachybot-chat-todo.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    manual = read("web/app/static/js/brachybot-3d-manual.js")

    assert "clearCaseScopedProgressPresentation" in chat_todo
    assert "trace.sessionId !== activeSessionId" in chat_todo
    assert "if (activeSessionId !== turnSessionId) return;" in chat_todo
    assert "clearCaseScopedProgressPresentation" in ui_api
    assert "clearManualDoseProgressPresentation" in ui_api
    assert "skipClientClear: true" in workspace
    assert "jobSessionId !== String(_activeApiSessionId() || '')" in manual


def test_background_hydration_cannot_overwrite_authoritative_case_data_with_a_ui_snapshot():
    """A saved display snapshot must never replace the selected case's labels."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    routes = read("web/routes/planning_routes.py")

    assert "CASE_DATA_CONTROL_IDS" in workspace
    assert "applyDataTreePresentation" in workspace
    assert "options.preserveClinicalData && CASE_DATA_CONTROL_IDS.has(id)" in workspace
    assert "if (options.preserveClinicalData) applyDataTreePresentation" in workspace
    assert "preserveClinicalData: true, skipChat: true" in ui_api
    assert 'status["ct_path"]' in routes
    assert 'status["ctv_path"]' in routes
    assert 'status["oar_path"]' in routes


def test_cold_start_uses_the_same_clinical_restore_contract_as_session_switch():
    """A compact startup snapshot must never masquerade as decoded CT data."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    startup = workspace.split("window.loadSessions =", 1)[1].split(
        "window.saveSessions =", 1
    )[0]
    assert "authoritativeChat: true" in startup
    assert "preserveClinicalData: true" in startup
    assert "persist: false" in startup
    assert "preserveClinicalData: false" not in startup


def test_clinical_restore_requires_decoded_ct_and_rebinds_viewer_interactions():
    """Blank canvases cannot be reported as a fully restored workspace."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    restore = ui_api.split("async function _restoreActiveSessionWorkspace", 1)[1].split(
        "async function restoreActiveSessionWorkspace", 1
    )[0]
    assert "decodedVoxelCount === expectedVoxelCount" in restore
    assert "state.ctLoaded = false" in restore
    assert "CT restore incomplete for session" in restore
    assert restore.count("setupViewerInteractions();") >= 2
    assert "segmentationMeshTask" in restore
    assert "loadCTVAndObstacleMeshes()" in restore
    assert "planningResult.value?.success !== true" in restore
    assert "continuing with planning restore" in restore


def test_planning_restore_waits_for_seed_needle_and_dose_data():
    """A background restore is not successful until essential plan products exist."""
    planning = read("web/app/static/js/brachybot-dvh-planning.js")
    routes = read("web/routes/planning_routes.py")
    assert "let refreshOutcome = { success: false" in planning
    assert "let doseOverlayPromise = Promise.resolve(null)" in planning
    assert "let seedGeometryPromise = Promise.resolve(null)" in planning
    assert "validateEssentialPlanningRestore" in planning
    assert "essentialReady: true" in planning
    assert "Planning seed/needle restore incomplete" in planning
    assert '"has_guide":' in routes


def test_startup_clear_cannot_race_the_scheduled_clinical_restore():
    """init() must not erase planning arrays after loadSessions schedules hydration."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    assert "startupClinicalRestoreScheduled" in ui_api
    assert "if (!startupClinicalRestoreScheduled)" in ui_api
    assert "backgroundRestoreRetryCounts" in workspace
    assert "restore.retry_scheduled" in workspace


def test_2d_hydration_reconciles_ct_dose_contours_and_planning_projections():
    """Restored overlays must share the final CT geometry without requiring Fit."""
    annotation = read("web/app/static/js/brachybot-manual-annotation.js")
    layout = read("web/app/static/js/brachybot-viewer-layout.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")

    assert "function reconcile2DViewerLayers" in annotation
    assert "window.reconcile2DViewerLayers = reconcile2DViewerLayers" in annotation
    assert "renderDoseForCurrentSlice(axis, sliceIndex);" in annotation
    assert "triggerDoseContourRender(axis, sliceIndex);" in annotation
    assert "renderSeedsOverlay(axis, sliceIndex);" in annotation
    assert "reason: 'viewer-geometry-sync'" in layout
    assert "reason: 'workspace-hydration-complete'" in ui_api
    assert "fitAllViewersAfterWorkspaceRestore" in ui_api
    assert "reason: 'workspace-hydration-fit'" in ui_api
    assert "window.fitAllViewersAfterWorkspaceRestore = fitAllViewersAfterWorkspaceRestore" in layout
    assert "reason," in layout
    assert '[id^="contourCanvas"]' in ui_api
    assert "canvas.style.removeProperty(property);" in ui_api


def test_case_clear_invalidates_late_planning_and_dose_render_responses():
    """Old case refreshes may finish, but they must not paint the new case."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    layout = read("web/app/static/js/brachybot-viewer-layout.js")

    assert "invalidatePlanningRefresh" in ui_api
    assert "window.invalidatePlanningRefresh" in planning
    assert "const isCurrentCase = () =>" in planning
    assert "if (!isCurrentCase() || !ov || ov.stale) return;" in planning
    assert "_doseOverlayLoadGeneration" in manual
    assert "requestSessionId !== _doseOverlaySessionId()" in manual
    assert "invalidateViewer3DRequests" in ui_api
    assert "function _viewer3DRequestScopeIsCurrent" in layout
    assert "scene3D.meshes[id] !== mesh" in layout
    assert "_viewer3DRequestHeaders(requestScope" in layout
    assert "Object.keys(_doseContourCache).forEach" in manual


def test_delayed_header_metadata_cannot_overwrite_a_new_case():
    """DICOM metadata is case-owned just like volume and label arrays."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")

    assert "async function pullHeaderInfo(ctPath, options = {})" in ui_api
    assert "'X-BrachyBot-Session': expectedSessionId" in ui_api
    assert "const ownsResponse = () =>" in ui_api
    assert "String(state.ctPath || '') === expectedPath" in ui_api
    assert "await pullHeaderInfo(state.ctPath, { sessionId: expectedSessionId })" in planning
    assert "const headerResp = await fetch(API + '/header/info'" not in planning


def test_running_chat_persists_the_user_turn_before_a_browser_refresh():
    """Refresh must restore the prompt that owns a replayed task trace."""
    routes = read("web/routes/planning_routes.py")
    stream = routes.split("        if stream:\n            def agent_supplier", 1)[1].split(
        "            def generate_task", 1
    )[0]
    started = stream.split("def persist_chat_task_start", 1)[1]
    assert 'display_message = full_message.split("\\n\\n[Uploaded image path:"' in started
    assert '"messages": messages' in started
    assert '"task_status": "running"' in started
    assert '"operation": operation' in started
    assert 'reason="chat.task.started"' in started
    assert "target=persist_chat_task_start" in stream
    assert "start_gate.set()" in started
    # The request must be able to emit task_meta before slow snapshot I/O
    # completes; the stream path must not call the request-context helper.
    assert "checkpoint_operation(" not in stream


def test_chat_connection_placeholder_does_not_claim_a_router_execution():
    """A local/direct turn must not leave a false Multi-Agent Router row."""
    chat_todo = read("web/app/static/js/brachybot-chat-todo.js")
    index = read("web/app/index.html")
    assert "title: zh ? '\\u8bf7\\u6c42\\u5206\\u6790' : 'Request analysis'" in chat_todo
    assert "Determining execution path..." in chat_todo
    assert "title: zh ? '\\u591a\\u667a\\u80fd\\u4f53\\u8def\\u7531' : 'Multi-Agent Router'" not in chat_todo
    assert 'static/js/brachybot-chat-todo.js?v=21' in index


def test_task_replay_is_deduplicated_and_bound_to_the_original_case():
    """Two restore phases must not make one task stop its own replay."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    chat_todo = read("web/app/static/js/brachybot-chat-todo.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")

    assert "const resumeSessionId = sessionId;" in workspace
    assert "String(activeSessionId || '') !== resumeSessionId" in workspace
    assert "_sessionChatResumePromises" in chat_todo
    assert "if (activeSessionId !== sessionId) return false;" in chat_todo
    assert "Two snapshot applications can race" in chat_todo
    assert "skipChat: options.background === true" in ui_api


def test_case_transitions_do_not_block_on_control_plane_cleanup():
    """Saving/releasing/reacquiring a lease must not delay the visible case."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    switch_block = workspace.split("window.switchSession =", 1)[1].split(
        "window.deleteSession =", 1
    )[0]
    delete_block = workspace.split("window.deleteSession =", 1)[1]
    assert "const previousCaseFlush = typeof flushActiveReportState === 'function'" in switch_block
    assert "void previousCaseFlush.catch" in switch_block
    assert "await Promise.resolve(flushActiveReportState())" not in switch_block
    assert "await persistWorkspace('session.switching')" not in switch_block
    assert "void window.brachybotAuth.releaseLease(previousSessionId)" in switch_block
    assert "await window.brachybotAuth.releaseLease(" not in switch_block
    assert "void window.brachybotAuth.acquireLease(activeSessionId)" in switch_block
    assert "void loadServerSessions().then(() => renderSessionList())" in delete_block
    assert "deferDisposal: true" in delete_block


def test_session_switch_paints_the_selected_shell_before_snapshot_request():
    """A slow snapshot must not delay sidebar/title/chat selection feedback."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    switch_block = workspace.split("window.switchSession =", 1)[1].split(
        "window.deleteSession =", 1
    )[0]
    assert "function paintSessionShell" in workspace
    assert "paintSessionShell(id, { clearWorkspace: false });" in switch_block
    assert "await yieldWorkspaceShellPaint()" in switch_block
    assert switch_block.index("paintSessionShell(id, { clearWorkspace: false });") < switch_block.index(
        "await workspaceFetch(`/api/sessions/${encodeURIComponent(id)}/select`"
    )
    assert "paintSessionShell(previousSessionId)" in switch_block


def test_case_clear_detaches_webgl_before_deferred_disposal():
    """Old meshes leave the scene synchronously while disposal yields a frame."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    assert "function deferSceneResourceDisposal(resources)" in ui_api
    assert "resetAllState({ deferDisposal: options.deferDisposal === true })" in ui_api
    assert "if (deferredResources) deferredResources.push(mesh)" in ui_api
    assert "requestAnimationFrame(schedule)" in ui_api


def test_workspace_hydration_has_visible_nonblocking_progress_state():
    index = read("web/app/index.html")
    auth_css = read("web/app/static/css/brachybot-auth.css")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    assert 'id="workspaceHydrationNotice"' in index
    assert "workspace-hydration-spinner" in auth_css
    assert "setWorkspaceHydrationState" in workspace
    assert "_restoreActiveSessionWorkspace" in ui_api
    assert "workspaceHydrationNotice" in index


def test_uploaded_oar_mask_is_a_numbered_traversable_data_tree_source():
    """Uploaded opaque labels must not be reinterpreted as named anatomy."""
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    routes = read("web/routes/viewer_routes.py")
    manual = read("web/app/static/js/brachybot-manual-annotation.js")
    for source in ("uploaded_unknown", "uploaded", "manual_upload"):
        assert source in viewer
        assert source in routes
    assert "const uploadedUnknownSource = new Set" in viewer
    assert "`OAR ${i + 1}`" in viewer
    assert "'X-BrachyBot-Session': ownerSessionId" in manual or "sessionHeaders['X-BrachyBot-Session']" in manual
    assert "const hydrationPending = res.status === 202" in manual
    assert "const rateLimited = res.status === 429" in manual
    assert "!hydrationPending && !rateLimited" in manual
    assert "const ownerSessionId" in manual
    assert "const isCurrentOwner = () => ownerSessionId" in manual
    assert "sessionId: ownerSessionId" in manual
    assert "hydrateOarDataTreeFromPayload(data, ownerSessionId)" in manual
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    assert "hydrateOarDataTreeFromPayload(payload, ownerSessionId)" in ui_api
    assert "loadLabelVolumes({\n                forceFresh: true" in ui_api
    assert "window.hydrateOarDataTreeFromPayload = function hydrateOarDataTreeFromPayload(payload, expectedSessionId" in viewer
    assert "dataTreeState.oar.loaded = true" in viewer
    assert "if (typeof renderDataTree === 'function') renderDataTree();" in viewer


def test_label_volume_cache_rejects_legacy_uint8_oar_entries():
    """Old caches must not wrap OAR IDs or omit stable structure IDs."""
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    # v5 keeps independent CTV/OAR color namespaces in addition to the
    # uint16 OAR wire format introduced by v4.
    assert "formatVersion: 5" in viewer
    assert "Number(hdr.formatVersion || 0) >= 5" in viewer
    assert "oarBytesPerVoxel === 2" in viewer
    assert "ctvObjectMap" in viewer
    assert "organMeta" in viewer


def test_session_restore_uses_lightweight_status_and_background_assets():
    """The control plane must not hydrate the full Agent or await report blobs."""
    cache = read("web/app/static/js/brachybot-session-cache.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    routes = read("web/routes/planning_routes.py")

    cache_api = cache.split("var api = {", 1)[1]
    cache_get = cache_api.split("put: async", 1)[0]
    assert "beginRunningSizeInitialization(db)" in cache_get
    assert "await ensureRunningSize(db)" not in cache_get


def test_session_restore_hydrates_ct_before_label_or_planning_layers():
    """Clinical overlays must not race the Agent's CT geometry hydration."""
    cache = read("web/app/static/js/brachybot-session-cache.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    routes = read("web/routes/planning_routes.py")
    ct_wait = ui_api.index("await ctTask;")
    labels_start = ui_api.index("const labelTask", ct_wait)
    planning_start = ui_api.index("const planningTask", ct_wait)
    assert labels_start > ct_wait
    assert planning_start > ct_wait
    assert "Agent. The shell remains responsive, but CT must hydrate first." in ui_api
    assert "_pendingSizeDelta" in cache
    assert "function hydrateReportFigureAssets" in workspace
    assert "Promise.all(pending.map" in workspace
    assert "status?lightweight=1" in ui_api
    assert "_statusFromWorkspaceSnapshot" in ui_api
    assert "get_agent();" in routes  # normal status remains available
    assert "lightweight" in routes
    lightweight_block = routes.split('if request.args.get("lightweight"', 1)[1].split("agent = get_agent()", 1)[0]
    assert "get_agent()" not in lightweight_block


def test_deleted_case_cancels_pending_agent_checkpoint():
    store = read("web/workspace_store.py")
    server = read("web/server.py")
    assert "def discard_agent_checkpoint" in store
    assert "workspace_store.discard_agent_checkpoint" in server


def test_chat_snapshot_is_redrawn_after_restore():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    assert "Array.isArray(chat.messages)" in workspace
    assert "loadSessionChat(activeSessionId)" in workspace
    assert "sessions[sessionId].pending = false" in workspace


def test_chat_snapshot_paints_before_heavy_clinical_restore():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    chat = read("web/app/static/js/brachybot-chat-core.js")
    assert "function applyChatSnapshotFast" in workspace
    assert "applyChatSnapshotFast(workspace)" in workspace
    assert "input.dataset.historySession" in chat
    assert "window._lastUserMessage" in chat


def test_case_clear_removes_untracked_surfaces_and_clinical_evaluation():
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    manual_3d = read("web/app/static/js/brachybot-3d-manual.js")
    assert "scene3D.skinMesh = null" in ui_api
    assert "clinicalEvaluationContent" in ui_api
    assert "Detailed evaluation will appear here after planning completes." in ui_api
    assert "invalidateViewerDataLoads" in ui_api
    assert "viewerDataLoadGeneration" in viewer
    assert "scope.dataGeneration !== viewerDataLoadGeneration" in viewer
    assert "invalidateSegmentationMeshPrewarm" in ui_api
    assert "generation !== _segmentationMeshPrewarm.generation" in manual_3d


def test_puncture_guide_controls_preserve_all_dimensions_and_selected_channels():
    """Guide input uses clinical diameters and survives case restoration."""
    index = read("web/app/index.html")
    guide = read("web/app/static/js/brachybot-surgical-guide.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")

    for control in (
        "guideSkinThreshold",
        "guideSkinClearance",
        "guidePlateThickness",
        "guidePatchMargin",
        "guideChannelDiameter",
        "guideSleeveOuterDiameter",
        "guideSleeveOutward",
        "guideSleeveInward",
        "guideGeometryResolution",
        "guideNeedleSelection",
    ):
        assert f'id="{control}"' in index
    assert 'onclick="resetSurgicalGuideControls()"' in index
    assert "channel_radius_mm: channelRadius" in guide
    assert "GUIDE_CONTROLS.sleeve_outer_diameter_mm" in guide
    assert "control.addEventListener('input', saveParameters)" in guide
    assert "needleSelection.addEventListener('change', saveParameters)" in guide
    assert "SELECT' && el.multiple" in workspace
    assert "Array.isArray(saved.values)" in workspace


def test_case_clear_removes_ctv_and_oar_input_paths_and_file_selections():
    """A new case must not display or retain masks from the previous case."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    assert "state.ctvPath = null" in ui_api
    assert "state.oarPath = null" in ui_api
    assert "['ctvPath', 'oarPath'].forEach" in ui_api
    assert "['fileCT', 'fileCTV', 'fileOAR'].forEach" in ui_api


def test_oar_tree_hydrates_when_binary_labels_arrive_without_metadata_header():
    """2D OAR pixels and Data Tree names must restore together per case."""
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    assert "async function hydrateOarDataTreeFromServer" in viewer
    assert "fetch(API + '/viewer/organs', {" in viewer
    assert "headers: _viewerDataHeaders(sessionId)" in viewer
    assert "void hydrateOarDataTreeFromServer(scope.dataGeneration, scope.sessionId);" in viewer
    assert "Invalid OAR metadata header" in viewer
    assert "const generation = Number.isFinite(generationValue)" in viewer
    assert "const sessionId = String(expectedSessionId || _viewerDataSessionId() || '')" in viewer


def test_mask_upload_progress_is_scoped_to_the_selected_input_row():
    """CTV/OAR uploads must not reuse the CT progress overlay DOM node."""
    index = read("web/app/index.html")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    assert 'id="uploadProgressOverlay_ctv"' in index
    assert 'id="uploadProgressOverlay_oar"' in index
    assert "function _uploadProgressElements(targetId)" in ui_api
    assert "_uploadProgressElements(targetId)" in ui_api
    assert "_uploadProgressElements('ctPath')" in ui_api
    assert "hydrateOarDataTreeFromServer(undefined, ownerSessionId)" in ui_api


def test_oar_tree_accepts_server_organs_and_ignores_empty_race_updates():
    """A successful OAR import must survive metadata/cache hydration races."""
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    assert "data.organs && typeof data.organs === 'object'" in viewer
    assert "if (!entries.length) return false;" in viewer
    assert "data.oar_mask_provenance" in viewer
    # The server object uses voxel_count; the upload fallback uses counts.
    assert "info.voxel_count ?? info.voxels ?? info.count" in viewer


def test_oar_snapshot_restore_preserves_live_rows_and_resets_case_provenance():
    """Empty compact snapshots must not erase OAR rows from the active case."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    assert "const hasPlanningRows" in workspace
    assert "Loaded flags are only control-plane hints" in workspace
    assert "dataTreeState.oarSource = '';" in ui_api
    assert "label: o.label" in viewer
    assert "const renamed = !sourceChanged && existing?.label" in viewer


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
    assert "recoverWorkspaceAfterTransitionFailure(transitionGeneration)" in workspace
    assert "async function recoverWorkspaceAfterTransitionFailure(generation)" in workspace
    assert "clearScheduledWorkspaceSave();" in workspace
    assert workspace.count("return runWorkspaceTransition(async () => {") >= 3
    assert "workspaceTransition = null;" in workspace
    assert "body.workspace-transitioning #sessionList" in layout


def test_workspace_network_failures_cannot_leave_case_controls_stuck():
    """Session requests need deadlines and bounded recovery after a restart."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    auth = read("web/app/static/js/brachybot-auth.js")

    assert "async function workspaceFetch" in workspace
    assert "WORKSPACE_REQUEST_TIMEOUT_MS = 15000" in workspace
    assert "WORKSPACE_RECOVERY_TIMEOUT_MS = 5000" in workspace
    assert "new Promise(resolve => setTimeout(resolve, WORKSPACE_RECOVERY_TIMEOUT_MS))" in workspace
    assert "if (!isCurrentTransition(generation)) return;" in workspace
    assert "async function authFetch" in auth
    assert "AUTH_REQUEST_TIMEOUT_MS = 12000" in auth


def test_workspace_notices_are_explicitly_dismissible_without_changing_state():
    """Recovery and lease notices hide only their presentation layer."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    auth = read("web/app/static/js/brachybot-auth.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    assert "function dismissWorkspaceRecoveryNotice()" in workspace
    assert "sessionStorage.setItem(recoveryNoticeDismissKey, '1')" in workspace
    assert "function dismissWorkspaceLockNotice()" in auth
    assert "workspaceLockDismissedKey = workspaceLockKey()" in auth
    assert "typeof activeSessionId !== 'undefined'" in auth
    assert "banner.id = 'assetVersionNotice'" in ui_api
    assert "Dismiss outdated-page notice" in ui_api
    assert 'id="workspaceLockTakeover"' in read("web/app/index.html")
    assert "takeover: true" in auth
    assert "function takeoverLease(sessionId = currentLeaseSessionId())" in auth


def test_lease_release_does_not_depend_on_fetch_wrapper_side_effects():
    """Case changes must release only this browser's lease after cache refreshes."""
    auth = read("web/app/static/js/brachybot-auth.js")
    block = auth.split(
        "async function releaseLease(sessionId = currentLeaseSessionId())", 1
    )[1].split("async function authenticated()", 1)[0]
    assert "credentials: 'same-origin'" in block
    assert "'X-CSRF-Token': state.csrfToken" in block
    assert "'X-BrachyBot-Editor': editorToken" in block
    assert "await authFetch('/api/workspace/lease'" in block
    assert "LEASE_RELEASE_TIMEOUT_MS = 4000" in auth
    assert "session_id: ownerSessionId" in block
    assert "aria-busy" in auth


def test_lease_identity_survives_reload_and_is_bound_to_selected_case():
    auth = read("web/app/static/js/brachybot-auth.js")
    assert "localStorage.getItem(editorKey) || sessionStorage.getItem(editorKey)" in auth
    assert "localStorage.setItem(editorKey, editorToken)" in auth
    assert "function currentLeaseSessionId()" in auth


def test_data_plane_requests_and_lease_transitions_are_case_bound():
    """Fast switches must not let delayed API or lease work follow global selection."""
    auth = read("web/app/static/js/brachybot-auth.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    switch_block = workspace.split("window.switchSession =", 1)[1].split(
        "window.deleteSession =", 1
    )[0]

    assert "headers.set('X-BrachyBot-Session', requestCaseId)" in auth
    assert "const controlPlaneRequest" in auth
    assert "async function releaseLease(sessionId = currentLeaseSessionId())" in auth
    assert "async function acquireLease(sessionId = currentLeaseSessionId())" in auth
    assert "releaseLease(previousSessionId)" in switch_block
    assert "acquireLease(activeSessionId)" in switch_block


def test_oar_restore_keeps_late_metadata_and_ctv_labels_out_of_oar_rows():
    """Late OAR metadata gets saved presentation while CTV labels stay separate."""
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    planning = read("tool_factory/seed_plan/planning_pipeline.py")

    assert "window.__pendingOarPresentation" in volume
    assert "savedTree.ctvLabels || savedTree.ctv_labels" in workspace
    assert "ctv_labels: Object.entries(dataTreeState.ctvLabels || {})" in ui_api
    assert 'data_tree.get("ctv_labels", data_tree.get("ctvLabels", []))' in planning


def test_chat_callbacks_are_persisted_to_the_turn_owner_case():
    """A response arriving after navigation must not be saved into the visible case."""
    chat = read("web/app/static/js/brachybot-chat-core.js")
    todo = read("web/app/static/js/brachybot-chat-todo.js")

    assert "sessionId = activeSessionId" in chat
    assert "const ownerSessionId = String(sessionId || activeSessionId || '')" in chat
    assert "ownerSessionId === String(activeSessionId || '')" in chat
    assert (
        "saveSessionMessage(safeType, c, null, Date.now(), ownerSessionId, safeMeta)"
        in chat
    )
    assert "headers: { 'X-BrachyBot-Session': turnSessionId }" in todo
    assert "addChat('bot-response', finalText, true, Date.now(), false, turnSessionId)" in todo


def test_oar_report_paths_normalize_volume_percentage_once():
    shell = read("web/app/static/js/brachybot-report-shell.js")
    export = read("web/app/static/js/brachybot-report-export.js")
    dvh = read("web/app/static/js/brachybot-dvh-planning.js")
    assert "function _oarVolumePercent(value, units)" in shell
    assert "_oarVolumePercent(x.v100, state.metrics.volume_metric_units)" in shell
    assert "function _oarVolumePercent(value, units)" in export
    assert "_oarVolumePercent(x.v100, state.metrics.volume_metric_units)" in export
    assert "function _dvhOarVolumePercent(value, units)" in dvh


def test_chat_network_failures_finish_the_turn_and_unlock_case_navigation():
    """A half-open chat connection must not leave Thinking or transitions alive."""
    chat = read("web/app/static/js/brachybot-chat-todo.js")
    assert "CHAT_CONNECT_TIMEOUT_MS = 30000" in chat
    assert "CHAT_IDLE_TIMEOUT_MS = 90000" in chat
    assert "CHAT_ABORT_TIMEOUT_MS = 4000" in chat
    assert "function readChatChunk(reader" in chat
    assert "await readChatChunk(reader, CHAT_IDLE_TIMEOUT_MS" in chat
    assert "turnAbortController.abort()" in chat
    assert "workspaceTransitionGeneration += 1" in read("web/app/static/js/brachybot-workspace.js")
    assert "signal: abortController ? abortController.signal : undefined" in chat


def test_chat_creates_and_reconciles_router_trace_before_sse_arrives():
    """A submitted request must show its own pending router immediately."""
    chat = read("web/app/static/js/brachybot-chat-todo.js")

    assert "client-router-${turnRequestId}" in chat
    assert "reconcileOptimisticTraceStep" in chat
    assert "Do not wait for the network/SSE handshake" in chat
    assert "createLiveThinkingChain(" in chat
    assert "status: 'pending'" in chat


def test_explicit_stop_is_a_per_session_barrier_before_the_next_chat_turn():
    """A stopped stream must never abort or clear the next turn in its case."""
    chat = read("web/app/static/js/brachybot-chat-todo.js")
    assert "window._sessionChatStopPromises" in chat
    assert "const pendingStop = pendingStopSessionId" in chat
    assert "await stopPromise;" in chat
    assert "stopTurnAbortController.__brachybotExplicitStop = true;" in chat
    assert "window._activeChatTurnGeneration" in chat
    assert "Number(window._activeChatTurnGeneration || 0) === stopTurnGeneration" in chat


def test_dose_colorbar_and_slice_cache_force_immediate_2d_repaint():
    """A scale/session change must invalidate pixels, not only slice indices."""
    manual_annotation = read("web/app/static/js/brachybot-manual-annotation.js")
    manual_3d = read("web/app/static/js/brachybot-3d-manual.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")

    assert "function invalidateDoseOverlayRenderCache()" in manual_annotation
    assert "_doseOverlayRenderEpoch" in manual_annotation
    assert "doseCanvas._doseRenderEpoch !== _doseOverlayRenderEpoch" in manual_annotation
    assert "renderEpoch === _doseOverlayRenderEpoch" in manual_annotation
    assert "_doseOverlayVolumeOwner === ownerOverlay" in manual_3d
    assert "_doseOverlayVolumeAbortController?.abort()" in manual_3d
    assert "invalidateDoseOverlayRenderCache();" in manual_3d
    assert '[id^="doseOverlayCanvas"]' in ui_api


def test_dose_surface_preserves_data_tree_display_state_and_capture_hides_handles():
    """Display modes may swap materials but must not overwrite user choices."""
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    layout = read("web/app/static/js/brachybot-viewer-layout.js")
    report = read("web/app/static/js/brachybot-report-editor.js")

    assert "function getDataTreeAppearanceForMesh" in volume
    assert "function syncSceneAppearanceFromDataTree" in volume
    assert "window.syncSceneAppearanceFromDataTree" in volume
    assert "getDataTreeAppearanceForMesh(id, mesh)" in layout
    assert "_doseTextureOpacityForMesh" not in layout
    assert "window.__reportCaptureActive" in layout
    assert "window.__reportCaptureActive = true" in report
    assert "window.__reportCaptureActive = false" in report


def test_tumor_type_selector_hides_model_implementation_from_the_user():
    index = read("web/app/index.html")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")

    selector = index.split('id="ctvModelSelect"', 1)[1].split("</select>", 1)[0]
    assert "nnU-Net" not in selector
    assert "VoCo" not in selector
    assert 'data-capability-state="loading"' in selector
    assert "Whole-prostate target" in selector
    assert "refreshTumorTypeAvailability" in ui_api
    assert "capability_state" in ui_api
    # The first probe can run before the authenticated SPA starts. It must be
    # retried after login/key setup instead of leaving callable BiomedParse
    # options permanently red after an initial 401.
    assert "brachybot:auth-ready" in ui_api
    assert "brachybot:api-key-changed" in ui_api
    assert "credentials: 'same-origin'" in ui_api
    auth = read("web/app/static/js/brachybot-auth.js")
    assert "window.dispatchEvent(new Event('brachybot:auth-ready'))" in auth
    # The selector exposes only the user-facing operational distinction:
    # callable routes are green and unavailable routes are red. Validation
    # maturity remains in the explanatory help text, not a third option color.
    assert "callable ? 'tumor-type-available' : 'tumor-type-unavailable'" in ui_api
    assert "optionCallable ? '#4ade80' : '#fb7185'" in ui_api
    assert "Integrated; further validation required" in ui_api


def test_dynamic_clinical_evaluation_uses_global_language_switch():
    """Metric review text must be rerendered, not left in a stale language."""
    dvh = read("web/app/static/js/brachybot-dvh-planning.js")
    assert "window._t(zh, en)" in dvh
    assert "function updateClinicalEvaluation()" in dvh
    assert "Planning Review Items" in dvh
    assert "规划复核项目" in dvh
    assert "window.addEventListener('i18nchange'" in dvh


def test_report_language_is_single_locale_and_references_have_real_metadata():
    """A Chinese export must not append English headings or fake source labels."""
    export = read("web/app/static/js/brachybot-report-export.js")
    shell = read("web/app/static/js/brachybot-report-shell.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")
    context = read("tool_factory/report_context.py")

    assert "const secondaryTitle = () => '';" in export
    assert "source_records" in shell
    assert "Clinical criterion source (" not in shell
    assert "publisher: 'Verified clinical source'" not in shell
    assert "PANCREAS_GUIDELINE_2024" in planning
    assert "https://pubmed.ncbi.nlm.nih.gov/39206973/" in planning
    assert "https://doi.org/10.4103/jcrt.JCRT_96_18" in planning
    assert "https://doi.org/10.3748/wjg.v24.i46.5280" in planning
    assert "PANCREAS_GUIDELINE_2024: {" in planning
    assert "PANCREAS_CONSENSUS_2018: {" in planning
    assert "PANCREAS_TEMPLATE_2018: {" in planning
    assert "Unmapped structure (label ${labelId})" in planning
    assert "未映射结构（标签 ${labelId}）" in planning
    assert "Clinical knowledge-base reference" in context


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


def test_volume_labels_slices_and_planning_results_pin_the_origin_case():
    """Every delayed clinical payload must remain bound to its originating case."""
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")
    report_export = read("web/app/static/js/brachybot-report-export.js")

    assert "function _captureViewerDataScope" in volume
    assert "function _viewerDataScopeIsCurrent" in volume
    assert "headers: _viewerDataHeaders(scope.sessionId)" in volume
    assert "headers: _viewerDataHeaders(scope.sessionId, { 'Content-Type': 'application/json' })" in volume
    assert "if (!sliceIsCurrent()) return;" in volume
    assert "Number(state?.slices?.[axis]) !== Number(sliceIndex)" in volume
    assert "'X-BrachyBot-Session': expectedSessionId" in planning
    assert "loadLabelVolumes({ sessionId: expectedSessionId })" in planning
    assert "'X-BrachyBot-Session': ownerSessionId" in report_export


def test_completed_segmentation_retries_publication_and_rebuilds_2d_3d_per_session():
    """A completed segmentation must not be stranded by a short hydration race."""
    chat = read("web/app/static/js/brachybot-chat-todo.js")
    manual = read("web/app/static/js/brachybot-manual-annotation.js")
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    manual_3d = read("web/app/static/js/brachybot-3d-manual.js")

    assert "window.hydrateCompletedSegmentationArtifacts" in volume
    assert "forceFresh: true" in volume
    assert "startSegmentationMeshPrewarm(normalizedKind" in volume
    assert "allOAR: normalizedKind === 'oar'" in volume
    assert "hydrateCompletedSegmentationArtifacts({" in chat
    assert "hydrateCompletedSegmentationArtifacts({" in manual
    assert "await prewarmSegmentationMeshes(kind" not in manual
    assert "res.status === 202" in manual_3d
    assert "pending_timeout" in manual_3d
    assert "window.SessionCache && !force" in manual_3d


def test_data_tree_keeps_group_expansion_and_shift_batch_selection():
    """Tree redraws must preserve collapsed groups and batch context selection."""
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")

    assert "expansionState: {}" in volume
    assert 'data-group="image"' in volume
    assert 'data-group="segmentation"' in volume
    assert "function _restoreTreeGroupExpansionState" in volume
    assert "_restoreTreeGroupExpansionState(body);" in volume
    assert "_treeExpansionState()[key] = expanded;" in volume
    assert "const savedExpansion = savedTree.expansionState || savedTree.expansion_state;" in workspace
    assert "dataTreeState.expansionState = jsonClone(savedExpansion);" in workspace
    assert "function getSelectedDataTreeIds" in volume
    assert "const selected = getSelectedDataTreeIds();" in volume
    assert "window.setAllTreeGroupsExpansion" in read("web/app/static/js/brachybot-ui-api.js")
    assert "window.setTreeGroupExpansion(value, command === 'expand')" in read("web/app/static/js/brachybot-ui-api.js")
    assert "if (value.startsWith('seed_')) return 'planning_seeds';" in volume
    assert "if (value.startsWith('needle_')) return 'planning_needles';" in volume
    assert "CSS.escape" not in volume
    # A right-click on a member of an existing selection must not clear the
    # selection before Move/Delete/Export consumes it.
    assert "if (!selectedItems.has(id))" in volume
    assert "selectedItems.clear();\n        selectedItems.add(id);" in volume
    assert "window.resetDataTreeSelectionState = resetDataTreeSelectionState;" in volume
    # Explicit batch snapshots must stay explicit: an empty selection must
    # not fall back to the first live item after an async tree refresh.
    assert "const ids = [...new Set((objectIds == null" in volume
    assert "Array.from(objectIds)" in volume
    # Generic masks use the durable ``mask:<id>`` identity while retaining
    # compatibility with old DOM ids such as ``mask_<id>``.  Batch actions
    # must resolve both forms through the same helper instead of filtering
    # one spelling inline.
    assert "function _maskStateEntry(nodeId)" in volume
    assert "value.startsWith('mask:')" in volume
    assert "value.startsWith('mask_')" in volume
    assert "const rawId = _maskSceneMeshId(id);" in volume


def test_generic_masks_hydrate_without_a_shared_label_volume():
    """Open masks must start loading before CTV/OAR early-return branches."""
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    start = volume.index("async function loadLabelVolumes(options = {})")
    generic_start = volume.index("void hydrateGenericMasksFromServer(scope);", start)
    first_fetch = volume.index("fetch(API + '/viewer/label_volume'", start)
    assert generic_start < first_fetch
    assert "genericMaskCatalogGeneration" in volume


def test_generic_segmentation_masks_keep_a_real_tree_and_structure_contract():
    """Open masks must be durable Data Tree objects before promotion."""
    chat = read("web/app/static/js/brachybot-chat-todo.js")
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    routes = read("web/routes/data_routes.py")
    structures = read("web/structure_service.py")

    assert "biomedparse_segmentation" in chat
    assert "hydrateGenericMasksFromServer" in chat
    assert "fetch(API + '/viewer/generic_masks'" in volume
    assert "_isOpenGenericMask" in volume
    assert "reclassify_generic_segmentation_masks" in routes
    assert "def reclassify_generic_segmentation_masks" in structures
    assert "_batch_memory_update(memory, updates, removals=_DOWNSTREAM_KEYS)" in structures
    # The effective Structure Set, not a browser-only label, is the source for
    # later planning/DVH/export after a user moves the mask to CTV or OAR.
    assert "structure_catalog" in structures


def test_replanning_history_and_midrun_dose_publication_have_stable_contracts():
    """Replanning and in-progress dose refresh must be version-bound."""
    planning_runs = read("web/planning_runs.py")
    planning_ui = read("web/app/static/js/brachybot-dvh-planning.js")
    chat = read("web/app/static/js/brachybot-chat-todo.js")
    runtime = read("agent_runtime/llm_runtime.py")
    pipeline = read("tool_factory/seed_plan/planning_pipeline.py")
    routes = read("web/routes/planning_routes.py")
    manual = read("web/app/static/js/brachybot-3d-manual.js")

    assert "def begin_planning_run" in planning_runs
    assert "def activate_planning_run" in planning_runs
    assert "Planning_{sequence}" in planning_runs
    assert "preserveReport: true" in planning_ui
    assert "restoreReportForPlanning(target" in planning_ui
    assert "dose_ready=true" in pipeline
    assert "dose_ready" in runtime
    assert "doseReadyText" in chat
    assert "dose[_\\s-]?ready" in chat
    assert "dose_generation" in routes
    assert "doseGeneration" in manual


def test_ctv_model_provenance_keeps_embedded_anatomy_after_oar_load():
    routes = read("web/routes/viewer_routes.py")
    structures = read("web/structure_service.py")
    assert 'ctv_source.startswith("nnunet_")' in routes
    assert "is_model_ctv" in routes
    assert "def _is_model_ctv_source" in structures
    assert "_is_model_ctv_source(ctv_source)" in structures


def test_task_resume_distinguishes_reconnect_from_a_server_lost_task():
    """A server restart must not leave a false 'restoring' promise in chat."""
    chat = read("web/app/static/js/brachybot-chat-todo.js")

    assert "function _addTaskRecoveryNotice" in chat
    assert "_addTaskRecoveryNotice(turnSessionId, effectiveTaskId, 'reconnecting')" in chat
    assert "_addTaskRecoveryNotice(sessionId, staleTaskId, 'unavailable')" in chat
    assert "The server is no longer running this task" in chat


def test_continue_is_a_case_task_command_and_replay_failures_are_terminal():
    """Continue must never fall through to the clinical/knowledge router."""
    chat = read("web/app/static/js/brachybot-chat-todo.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    routes = read("web/routes/planning_routes.py")

    assert "function _isContinuationRequest(value)" in chat
    assert "resumeSessionChatTask({ userInitiated: true })" in chat
    assert "rawResumeState === 'failed' || rawResumeState === 'cancelled'" in chat
    assert "const replayResult = await sendChat(null" in chat
    assert "reason: 'replay_http_error'" in chat
    assert "return false;\n        }\n\n        const ctype" in chat
    assert '"last_task_id": None' in routes
    assert '"persisted": persisted' in routes
    assert "void window.resumeSessionChatTask();" in workspace


def test_background_snapshot_restore_cannot_clear_live_task_identity():
    """Clinical hydration must skip chat/task presentation and then reconcile."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")

    assert "if (!options.skipChat)" in workspace
    assert "Preserve the local hint until" in workspace
    assert "preserveClinicalData: true" in ui_api
    assert "skipChat: true" in ui_api


def test_ui_controller_waits_for_async_viewer_and_manual_planning_actions():
    """UI action progress must represent completion, not merely task launch."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    manual = read("web/app/static/js/brachybot-manual-annotation.js")
    volume = read("web/app/static/js/brachybot-viewer-volume.js")

    assert "return navigateToDosePeakSlices();" in ui_api
    assert "await hydrateOrgans();" in ui_api
    assert "Promise.allSettled(" in ui_api
    assert "async function groupReconstruct3D(category)" in volume
    assert "payload.organs, payload.oar_source || ''" in volume
    assert "return resetSession();" in ui_api
    assert "return startTrainingMode(value || 'Monitor planning workflow')" in ui_api
    assert "return clearCurrentChatHistory({ skipConfirm: true });" in ui_api
    assert "return { success: true, step: 'full' };" in manual
    assert "return { success: true, kind, labels: n };" in manual
    assert "Planning reset failed:" in manual


def test_viewer_layout_restore_resynchronizes_all_viewer_geometry():
    """Fullscreen/layout restoration must remeasure both 2D and 3D viewers."""
    layout = read("web/app/static/js/brachybot-viewer-layout.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    manual_3d = read("web/app/static/js/brachybot-3d-manual.js")

    assert "function syncViewerGeometry" in layout
    assert "requestAnimationFrame(() => render(acceptNewerGeneration))" in layout
    assert "Measure once immediately" in layout
    assert "schedule(true)" in layout
    assert "_clearViewerResizeOverrides(panel)" in layout
    assert "window.resizeViewer3D" in layout
    assert "function captureViewerViewport(axis)" in layout
    assert "panFractionX" in layout
    assert "_restoreViewerViewport(viewportSnapshot)" in layout
    assert "window.syncViewerGeometry({ resetPositions: true, settleMs: 160, viewportSnapshot })" in ui_api
    assert "panel.classList.add('viewer-fullscreen-active')" in ui_api
    assert "panel.classList.remove('viewer-fullscreen-active')" in ui_api
    assert "data-fullscreen-hidden=\"1\"" in ui_api
    assert "containerW < 1 || containerH < 1" in volume
    assert "scene3D.resize = resizeViewer3D" in manual_3d


def test_legacy_session_clear_action_is_honest_about_its_scope():
    """The LLM catalog must never claim cache cleanup deletes clinical cases."""
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    registry = read("tool_factory/ui_controller/__init__.py")

    assert "browser_cache.clear" in ui_api
    assert "Persistent server cases will be retained" in ui_api
    assert '"browser_cache.clear"' in registry
    assert "durable server cases are retained" in registry


def test_manual_ctv_model_is_explicit_and_uploaded_ct_enables_steps():
    index = read("web/app/index.html")
    manual = read("web/app/static/js/brachybot-manual-annotation.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    routes = read("web/routes/planning_routes.py")

    assert 'id="ctvModelSelect"' in index
    assert "tumor_type: document.getElementById('ctvModelSelect')?.value" in manual
    assert "ctPathInput.dispatchEvent(new Event('input'" in ui_api
    assert '"tumor_type"' in routes


def test_small_talk_never_uses_a_canned_answer_when_llm_is_unavailable():
    workflow = read("agent_runtime/chat_workflows.py")
    assert "def _llm_unavailable_message(lang:" in workflow
    assert "no canned answer was generated" in workflow
    assert "Local Fast Path" not in workflow
    assert "Answered locally; no model call" not in workflow


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


def test_active_progress_animation_remains_continuous_with_a_low_motion_fallback():
    todo = read("web/app/static/js/brachybot-chat-todo.js")
    status_css = read("web/app/static/css/brachybot-chat-status.css")
    report_css = read("web/app/static/css/brachybot-report-controls.css")
    responsive_css = read("web/app/static/css/brachybot-responsive.css")

    assert "todo-active-breathe 1.8s ease-in-out infinite" in status_css
    assert "item.node.classList.remove('pending', 'active', 'predicted')" in todo
    assert "item.node.classList.add(item.status)" in todo
    assert "animation-iteration-count: infinite !important" in report_css
    assert "animation-name: pill-breathe-soft !important" in report_css
    assert "animation-name: todo-active-breathe-soft !important" in responsive_css
    assert "animation-name: pipeline-dot-breathe-soft !important" in responsive_css


def test_background_case_restore_shows_a_corner_indicator_and_restores_case_products():
    """Case switching must paint fast while every durable product hydrates case-locally."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    index = read("web/app/index.html")

    assert 'id="workspaceHydrationNotice"' in index
    hydration_css = read("web/app/static/css/brachybot-auth.css")
    assert ".workspace-hydration-notice" in hydration_css
    assert "position: fixed" in hydration_css
    assert "right: 18px" in hydration_css
    assert "bottom: 18px" in hydration_css
    assert "Restoring case resources..." in workspace
    assert "X-BrachyBot-Session" in workspace
    assert "applyChatSnapshotFast(workspace)" in workspace
    assert "loadLabelVolumes({" in ui_api
    assert "sessionId: sessionAtStart" in ui_api
    assert "skipLabelLoad: true" in ui_api
    assert "await ctTask;" in ui_api
    assert "preserveClinicalData: true" in ui_api
    assert "hydrateReportFigureAssets" in workspace
    assert "restoreSceneView(uiState.viewer?.scene, uiState.viewer?.dvh" in workspace


def test_label_completion_repaints_every_2d_viewer_while_preserving_controls():
    """A restored or newly imported mask must paint without moving a slice."""
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    block = viewer.split("function reconcileSegmentationViewerState", 1)[1].split(
        "window.reconcileSegmentationViewerState", 1
    )[0]

    assert "_viewerDataScopeIsCurrent" in block
    assert "['axial', 'sagittal', 'coronal'].forEach" in block
    assert "renderSliceFromVolume(axis, state.slices[axis])" in block
    assert "requestViewerVisualRefresh(reason)" in block


def test_planning_parent_visibility_clears_independent_dose_projection_layers():
    """Hiding Planning must remove dose canvases as well as 3D children."""
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")

    assert "function _setPlanningDoseProjectionVisibility(visible, options = {})" in viewer
    assert "dataTreeState.planning.visible = !!visible" in viewer
    assert "doseOverlayCanvas" in viewer
    assert "_setPlanningDoseProjectionVisibility(_planningViewVisible('2d'))" in viewer


def test_compact_restart_planning_shell_cannot_hide_restored_dose_layers():
    """A placeholder restart snapshot must not override hydrated Planning visuals."""
    workspace = read("web/app/static/js/brachybot-workspace.js")
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")

    assert "function hasPlanningClinicalRows(planning)" in workspace
    assert "function isCompactPlanningShell(savedTree)" in workspace
    assert "savedTree.planning.visibilityConfigured === true" in workspace
    assert "dataTreeState.planning.visible = true" in workspace
    assert "visibilityConfigured: false" in viewer
    assert "function _planningViewVisible(view)" in viewer
    assert "&& (!_isPlanningDescendantNode(node) || _planningViewVisible('2d'))" in viewer
    assert "&& (!_isPlanningDescendantNode(node) || _planningViewVisible('3d'))" in viewer
    assert "const planningMasterVisible = _planningMasterVisible();" in viewer


def test_finalized_detached_chat_keeps_start_timestamp_and_trace_for_restore():
    """A browser reconnect must recover the original turn time and tool history."""
    routes = read("web/routes/planning_routes.py")
    assert "timestamp_ms=int(task.created_at * 1000)" in routes
    assert '"execution_trace": trace_for_snapshot' in routes
    assert '"chat": {\n                        "messages": messages' in routes


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


def test_monitor_edge_is_a_top_level_non_interactive_layer_and_tumor_colors_are_binary():
    index = read("web/app/index.html")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    status_css = read("web/app/static/css/brachybot-chat-status.css")
    panel_css = read("web/app/static/css/brachybot-panels-viewers.css")

    assert 'id="monitorEdgeOverlay"' in index
    # Monitor exits with an opacity transition, then restores `hidden`; this
    # avoids the old visible snap at Finish Monitoring.
    assert "edge.hidden = false" in ui_api
    assert "edge.classList.add('is-visible')" in ui_api
    assert "edge.classList.remove('is-visible')" in ui_api
    assert "document.body.dataset.monitorPhase === 'inactive'" in ui_api
    assert ".monitor-edge-overlay" in status_css
    assert "pointer-events: none" in status_css
    assert "optionCallable ? '#4ade80' : '#fb7185'" in ui_api
    assert 'option[data-callable="true"]' in panel_css
    assert 'option[data-callable="false"]' in panel_css


def test_monitor_and_guide_controls_have_explicit_runtime_fallbacks():
    """The visual affordances must survive stale/native browser rendering."""
    index = read("web/app/index.html")
    status_css = read("web/app/static/css/brachybot-chat-status.css")
    theme_css = read("web/app/static/css/brachybot-theme-layout.css")
    guide = read("web/app/static/js/brachybot-surgical-guide.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")

    assert "inset: 6px" in status_css
    assert "rgba(79, 124, 255, 0.30)" in status_css
    assert "color-scheme: dark" in theme_css
    assert ".guide-parameter-grid select.is-empty" in theme_css
    assert "No planned needles available" in guide
    assert "capability === 'loading' && selected?.value === 'nnunet_pancreatic'" in ui_api
    assert "_syncTumorTypeSelectorAppearance();" in ui_api


def test_report_restore_preserves_quality_cells_and_keeps_section_order():
    report = read("web/app/static/js/brachybot-report-export.js")
    block = report.split("function _updateReportPreview()", 1)[1].split(
        "function _hpMetricRow", 1
    )[0]
    assert "const reportTotalPages = 4 + oarPageCount" in block
    assert "const figure1Rows = _reportFiguresForGroup(f, 'figure1');" in block
    assert "const figure2Rows = _reportFiguresForGroup(f, 'figure2');" in block
    assert "p1 + figure1Pages + p2 + figure2Pages + supplementalPages + p3Pages + p4 + p5" in block
    assert block.index("secondaryTitle('Target & Prescription')") < block.index("secondaryTitle('Plan Quality Assessment')")
    assert block.index("secondaryTitle('Plan Quality Assessment')") < block.index("secondaryTitle('OAR Dose')")
    assert block.index("secondaryTitle('OAR Dose')") < block.index("secondaryTitle('Clinical Interpretation')")
    for key in ("aD95.reference", "aCI.reference", "aHI.reference", "aGI.reference", "aScore.reference"):
        assert key in block
    assert "options.preserveStored !== false" in report

    workspace = read("web/app/static/js/brachybot-workspace.js")
    assert "_mergePersistedQualityAssessment" in workspace
    assert "syncReportQualityAssessment(targetReport, { preserveStored: true })" in workspace
    assert "syncReportQualityAssessment(window.reportForm, { preserveStored: true })" in workspace


def test_surgical_guide_restore_waits_for_hydration_and_publishes_tool_results():
    routes = read("web/routes/surgical_guide_routes.py")
    guide = read("web/app/static/js/brachybot-surgical-guide.js")
    tool = read("tool_factory/surgical_guide/__init__.py")
    assert "workspace_hydration_pending" in routes
    assert "pending = workspace_data_pending(agent)" in routes
    assert "retryPending: true" in guide
    assert "maxPendingRetries = 240" in guide
    assert "publish_active_planning_state(agent)" in tool
    assert "requires_regeneration: true" in guide
    assert "source_plan_signature" in guide
    assert "Older persisted guides may not have bore_quality metadata" in guide


def test_restore_time_3d_camera_guard_reframes_stale_hydration_targets_without_touching_user_pan():
    viewer = read("web/app/static/js/brachybot-3d-manual.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")
    assert "function ensureCameraFitsVisibleScene({ forceCenter = false, reason = '' } = {})" in viewer
    assert "project(camera)" in viewer
    assert "const offCenter = Math.abs(projectedCenterX) > 0.14" in viewer
    assert "const hydrationCentering = forceCenter || scene3D._workspaceRestoreActive === true;" in viewer
    assert "const cameraOwnsView = scene3D._cameraUserInteracted === true;" in viewer
    assert "const hardClip = !validProjection || outside;" in viewer
    assert "const deliberateCloseup = cameraOwnsView" not in viewer
    assert "const shouldReframe = hydrationCentering" in viewer
    assert "if (cameraOwnsView && !hydrationCentering) return false;" in viewer
    assert "const cameraZoom = Math.max(0.1, Math.min(Number(camera.zoom) || 1, 100));" in viewer
    assert "const requiredDistance = radius * cameraZoom / Math.sin(limitingHalfFov) * 1.18;" in viewer
    assert "window.scheduleCameraFitForSceneMutation?.('mesh-hydration-batch');" in viewer
    assert "scene3D._cameraFitTimer = setTimeout" in viewer
    assert "forceCenter: true" in workspace
    assert "reason: 'workspace-restore-settled'" in workspace
    assert "window.ensureCameraFitsVisibleScene = ensureCameraFitsVisibleScene;" in viewer
    assert "const actualAspect = cssWidth / cssHeight;" in viewer
    assert "aspect: undefined" in workspace
    assert "viewer.3d.camera-fit-after-restore" in viewer
    assert "window.ensureCameraFitsVisibleScene?.({" in workspace
    assert "if (!initial && scene3D._cameraUserInteracted === true) return;" in workspace
    assert "applyScene({ initial: true });" in workspace
    assert "reason: 'planning-mesh-hydration-complete'" in planning
    assert "reason: 'planning-mesh-load-complete'" in planning


def test_prescription_isosurface_exposes_display_grid_v100_audit_in_data_tree():
    viewer = read("web/app/static/js/brachybot-3d-manual.js")
    data_tree = read("web/app/static/js/brachybot-viewer-volume.js")

    assert "function applyDoseCoverageAudit(level, audit)" in viewer
    assert "coverageAudit: data.coverage_audit || null" in viewer
    assert "coveragePct" in viewer
    assert "V100 ${coveragePct.toFixed(1)}%" in viewer
    assert "level.coverageAudit?.coverage_percent" in data_tree
    assert "level.coverageAudit?.reported_metric === 'v100'" in data_tree
