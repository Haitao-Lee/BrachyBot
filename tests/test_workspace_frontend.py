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


def test_new_case_creation_avoids_empty_workspace_hydration_and_redundant_round_trips():
    workspace = read("web/app/static/js/brachybot-workspace.js")
    auth = read("web/app/static/js/brachybot-auth.js")
    sessions = read("web/routes/session_routes.py")
    new_case = workspace.split("window.newChat =", 1)[1].split("window.switchSession =", 1)[0]
    assert "await loadServerSessions()" not in new_case
    assert "void persistWorkspace('session.switching')" in new_case
    assert "paintSessionShell(optimisticId)" in new_case
    assert "clearClientWorkspace({ clearReport: true, deferDisposal: true })" in workspace
    assert "scheduleBackgroundWorkspaceRestore" not in new_case
    assert "applyLeaseResult" in new_case
    assert "function applyLeaseResult" in auth
    assert '"lease": lease' in sessions
    assert "sessions[createdSession.id] = sessionStateFromPayload(createdSession)" in new_case
    assert new_case.index("sessions[createdSession.id]") < new_case.index("renderSessionList()")
    assert "window.setWorkspaceHydrationState?.(false)" in new_case


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
    started = routes.split('reason="chat.task.started"', 1)[0]
    assert 'display_message = full_message.split("\\n\\n[Uploaded image path:"' in started
    assert '"messages": messages' in started
    assert '"task_status": "running"' in started


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
    assert "void persistWorkspace('session.switching')" in switch_block
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
    assert "paintSessionShell(id);" in switch_block
    assert switch_block.index("paintSessionShell(id);") < switch_block.index(
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
    assert "channel_radius_mm: numericControl" in guide
    assert "sleeve_outer_radius_mm: numericControl" in guide
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
    assert "headers: _viewerDataHeaders(expectedSessionId)" in viewer
    assert "void hydrateOarDataTreeFromServer(scope.dataGeneration, scope.sessionId);" in viewer
    assert "Invalid OAR metadata header" in viewer


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


def test_chat_callbacks_are_persisted_to_the_turn_owner_case():
    """A response arriving after navigation must not be saved into the visible case."""
    chat = read("web/app/static/js/brachybot-chat-core.js")
    todo = read("web/app/static/js/brachybot-chat-todo.js")

    assert "sessionId = activeSessionId" in chat
    assert "const ownerSessionId = String(sessionId || activeSessionId || '')" in chat
    assert "ownerSessionId === String(activeSessionId || '')" in chat
    assert "saveSessionMessage(safeType, c, null, Date.now(), ownerSessionId)" in chat
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


def test_dose_colorbar_and_slice_cache_force_immediate_2d_repaint():
    """A scale/session change must invalidate pixels, not only slice indices."""
    manual_annotation = read("web/app/static/js/brachybot-manual-annotation.js")
    manual_3d = read("web/app/static/js/brachybot-3d-manual.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")

    assert "function invalidateDoseOverlayRenderCache()" in manual_annotation
    assert "_doseOverlayRenderEpoch" in manual_annotation
    assert "doseCanvas._doseRenderEpoch !== _doseOverlayRenderEpoch" in manual_annotation
    assert "renderEpoch === _doseOverlayRenderEpoch" in manual_annotation
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
    assert 'data-availability="available"' in selector
    assert 'data-availability="unavailable"' in selector
    assert "refreshTumorTypeAvailability" in ui_api
    assert "Green tumor types can be segmented automatically." in ui_api


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
    assert "requestAnimationFrame(() => requestAnimationFrame(render))" in layout
    assert "_clearViewerResizeOverrides(panel)" in layout
    assert "window.resizeViewer3D" in layout
    assert "window.syncViewerGeometry({ resetPositions: true, settleMs: 100 })" in ui_api
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
    assert "def _llm_unavailable_message()" in workflow
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
