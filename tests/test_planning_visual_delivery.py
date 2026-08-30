"""Regression contracts for chat-driven planning result delivery.

The clinical pipeline may finish on a background worker, but its results must
still travel through the same case-bound UI path: labels first, then planning
objects, dose/DVH/report products, and finally the complete tracked 3D mesh
reconstruction. The data plane may become usable earlier, but loading must
remain active until the actual mesh promises settle.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_chat_segmentation_completion_loads_labels_before_background_meshes():
    chat = read("web/app/static/js/brachybot-chat-todo.js")
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")

    assert "loadLabelVolumes({" in chat
    assert "forceFresh: true" in chat
    assert "reconcileSegmentationViewerState" in chat
    # The chat SSE path delegates mesh work to the session-bound hydration
    # helper; the helper owns the non-blocking progressive reconstruction.
    assert "startSegmentationMeshPrewarm(" in viewer
    assert "normalizedKind" in viewer


def test_full_oar_reconstruction_is_tracked_until_all_meshes_settle():
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    block = manual.split("async function _loadCTVAndObstacleMeshes", 1)[1].split(
        "// Load dose distribution", 1
    )[0]

    # A cold restore must select the complete OAR target set once.  The old
    # implementation first ran the non-traversable subset and then ran a
    # second all-OAR pass after label hydration, which reset the UI from e.g.
    # 3/37 to 3/58 and made the first work look wasted.
    assert block.count("await prewarmSegmentationMeshes('all', {") == 1
    assert "allOAR: Array.isArray(allOarIds)" in block
    assert "oarIds: allOarIds" in block
    assert "labelsReady" in block
    assert "if (oarLabelData)" not in block
    assert "loadingToken" in block
    assert "startSegmentationMeshPrewarm('all', {" not in block
    assert "function startSegmentationMeshPrewarm(kind = 'all', opts = {})" in manual


def test_structural_reconstruction_is_case_scoped_and_waits_for_label_snapshot():
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")

    assert "let _structuralMeshReconstructionInFlight = null" in manual
    assert "return existing.promise" in manual
    assert "_structuralMeshReconstructionInFlight = null" in manual
    assert "function _structuralMeshScopeIsCurrent(scope)" in manual
    assert "await Promise.resolve(options.labelsReady)" in manual
    assert "labelsReady: options.labelsReady" in planning
    assert "labelsReady: labelTask" in ui_api


def test_cold_restore_keeps_one_loading_owner_until_parallel_viewer_work_finishes():
    """Essential readiness must not create a silent gap before 3D completion."""
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")

    assert "Object.defineProperty(refreshOutcome, 'backgroundCompletion'" in planning
    assert "const viewerCompletionPromise = backgroundMeshesPromise.then" in planning
    assert "value: viewerCompletionPromise" in planning
    assert "showLoading: !options.hydrationScope" in planning
    assert "loadSeeds3D({" in planning
    assert "onProgress: options.onHydrationProgress" in planning
    assert "registerBackgroundTask(completion, { kind: 'viewer_3d' })" in ui_api
    assert "Promise.allSettled(backgroundTasks).finally" in ui_api
    assert "if (!backgroundNoticeTransferred)" in ui_api
    assert "registerBackgroundTask: options.registerBackgroundTask" in ui_api
    assert "pendingBackgroundKinds" in ui_api
    assert "const maxConcurrent = Math.max(" in manual
    assert "Array.from({ length: workerCount }, () => runOarWorker())" in manual
    assert "await Promise.all(batch)" not in manual
    assert "reportProgress({ phase: 'oar', current: completed, total: oarIds.length })" in manual


def test_terminal_planning_refresh_delivers_all_downstream_products():
    chat = read("web/app/static/js/brachybot-chat-todo.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")

    schedule = chat.split("function _scheduleCasePlanningRefresh", 1)[1].split(
        "function _sessionChatQueue", 1
    )[0]
    assert "autoGenerateGuide: true" in schedule
    assert "retryPending: true" in schedule
    for required in (
        "await loadLabelVolumes({",
        "updateSeeds(data.seeds)",
        "updateTrajectories(data.trajectories)",
        "loadDoseOverlay()",
        "drawDVH()",
        "loadCTVAndObstacleMeshes({",
        "reportAutoFill({ sessionId: expectedSessionId })",
        "updateClinicalEvaluation()",
    ):
        assert required in planning
    assert "loadAllIsoSurfaces({" in planning
    assert "reconstruct3d: true" in planning


def test_surgical_guide_uses_real_mesh_for_data_tree_bound_2d_projection():
    annotation = read("web/app/static/js/brachybot-manual-annotation.js")
    guide = read("web/app/static/js/brachybot-surgical-guide.js")

    assert "function _drawSurgicalGuideSliceProjection" in annotation
    assert "function hasSurgicalGuideProjection" in annotation
    assert "patient_specific_puncture_guide" in annotation
    assert "_worldToIndex(world.x, world.y, world.z)" in annotation
    assert "_drawSurgicalGuideSliceProjection(ctx, axisIdx, sliceIndex, orientIdx, toDisplay);" in annotation
    assert "window.loadAllSlices?.();" in guide


def test_planning_refresh_preserves_existing_tree_presentation_state():
    planning = read("web/app/static/js/brachybot-dvh-planning.js")

    assert "const wasLoaded = !!dataTreeState.seeds.loaded;" in planning
    assert "if (hasSeeds && !wasLoaded) dataTreeState.seeds.visible = true;" in planning
    assert "const prior = new Map((dataTreeState.planning.seeds || []).map(seed =>" in planning
    assert "const seedPresentation = new Map((dataTreeState.planning.seeds || []).map(seed =>" in planning
    assert "visible: existing?.visible ?? true" in planning


def test_planning_result_contract_exposes_run_identity_and_artifact_state():
    """Every refreshed result must identify the run that owns its products."""
    routes = read("web/routes/planning_routes.py")
    result_block = routes.split("def api_planning_results", 1)[1].split(
        "@app.route(\"/api/planning/runs\"", 1
    )[0]
    for required in (
        '"planning_id": current_planning_id',
        '"planning_label": active_run.get("label")',
        '"planning_status": active_run.get("status")',
        '"artifact_status": artifact_status',
        "pending = dose_workspace_data_pending(agent)",
        "dvh_data = dose_context.get(\"dvh\")",
    ):
        assert required in result_block


def test_2d_segmentation_uses_clinical_source_over_layer_order():
    """CTV must stay visible above an overlapping semi-transparent OAR."""
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")

    assert "function _sourceOverPackedRgba" in viewer
    assert "Segmentation is source-over composited in a stable clinical" in viewer
    assert "OAR is composited above open/manual masks and skin" in viewer
    # The former mutually-exclusive writes made CTV disappear at every voxel
    # also occupied by an OAR, regardless of the selected opacity.
    assert "if (oA === 0 && isDataTreeNodeVisible2D(dataTreeState.oar)" not in viewer
    assert "if (oA === 0 && isDataTreeNodeVisible2D(dataTreeState.ctv)" not in viewer


def test_data_tree_opacity_drag_is_a_single_commit_transaction():
    """Fast slider drags may update pixels live but must not replace their input."""
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    css = read("web/app/static/css/brachybot-report-controls.css")

    for required in (
        "let _dataTreeOpacityDrag = null",
        "function _finishDataTreeOpacityDrag",
        "function _bindDataTreeOpacityControls",
        "control.addEventListener('pointerdown'",
        "if (_isDataTreeOpacityDragActive())",
        "function _commitGroupOpacity(category)",
    ):
        assert required in viewer
    assert "min-width: 54px" in css
    assert "touch-action: none" in css


def test_data_tree_has_independent_2d_and_3d_presentation_controls():
    """Visual nodes retain a master state plus independent MPR/3D controls."""
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    annotation = read("web/app/static/js/brachybot-manual-annotation.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")

    for required in (
        "node.visible2D = node.visible2D !== false",
        "node.visible3D = node.visible3D !== false",
        "function batchSetViewVisibility(view, visible)",
        "function setGroupViewVisibility(category, view, visible)",
        "Show in 2D",
        "Hide in 2D",
        "Show in 3D",
        "Hide in 3D",
        "function applyDataTreeViewVisibility()",
    ):
        assert required in viewer

    assert "meshData.visible3D !== false" in manual
    assert "visible2D: seed.visible2D ?? old.visible2D ?? true" in manual
    assert "visible2D !== false" in annotation
    assert "['visible', 'visible2D', 'visible3D', 'opacity', 'color', 'material', 'locked']" in workspace


def test_guide_skin_uses_the_same_data_tree_control_paths_as_other_visual_nodes():
    """The persisted guide skin must not bypass view or opacity controls."""
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")

    # A scene-wide appearance sync must respect the 3D-specific flag.  This
    # catches the regression where a later sync made a hidden skin reappear.
    assert "item.visible !== false && item.visible3D !== false" in viewer

    # Programmatic visibility and opacity paths must explicitly resolve the
    # stable skin node instead of falling through to a missing top-level key.
    assert "else if (id === 'skin_surface') current = dataTreeState.skin?.visible;" in viewer
    assert "if (id === 'skin_surface') {\n        dataTreeState.skin.opacity = opacity;" in viewer
    assert "_scheduleDataTreeSave('viewer.opacity:skin_surface')" in viewer

    # The 2D renderer already consumes the persisted skin node state; keep an
    # assertion beside the control checks so the contract remains end-to-end.
    assert "const hasSkin2d = !!(skinSurfaceData && isDataTreeNodeVisible2D(dataTreeState.skin));" in viewer


def test_iso_surface_refresh_keeps_data_tree_appearance_and_view_flags():
    """Refreshing dose geometry must not reset a user's visibility choices."""
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")

    assert "const priorLevels = new Map" in manual
    assert "existing.visible2D = existing.visible2D !== false" in manual
    assert "existing.visible3D = existing.visible3D !== false" in manual
    assert "rebuiltLevels[i] = existing" in manual
    assert "Array.from({ length: Math.min(maxConcurrent, relValues.length) }" in manual
    assert "suppressTreeEntry: true" in manual
    assert "deferRender: true" in manual
    assert "let loadedLevels = 0" in manual
    assert "const failedLevels = []" in manual
    assert "loaded: level.loaded === true" in viewer
    assert "return { stale: false, levels: relValues.length, loadedLevels, failedLevels }" in manual


def test_planning_visual_loads_are_retryable_and_case_scoped():
    """A transient limiter response must not abort restored visual products."""
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    layout = read("web/app/static/js/brachybot-viewer-layout.js")
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")

    assert "_seeds3DLoadInFlight" in manual
    assert "_organ3DReconstructionInFlight" in layout
    # Rate-limit/pending handling is centralized in the bounded request
    # helper. Individual mesh loaders consume its response rather than
    # maintaining their own unbounded status whitelist.
    assert "response.status === 429" in manual
    assert "request.data?.error" in manual
    assert "timedOut: true" in manual
    assert "_isoSurfaceLoadInFlight" in manual
    assert "const rebuiltLevels = [];" in manual
    assert "Keep the currently displayed surfaces until each replacement" in manual
    assert "if (_viewer3DRequestScopeIsCurrent(requestScope) && !silent)" in layout
    assert "silent && [202, 404, 409, 429].includes(res.status)" in layout
    assert "window.fetchViewerJsonWithRetry(API + '/viewer/overlay'" in viewer
    assert "request.response?.ok" in viewer
    assert "loadAllIsoSurfaces({" in planning
    assert "reconstruct3d: true" in planning
    assert "'Isosurface reconstruction',\n                180000" in planning
    assert "_withTimeout(loadSeeds3D({" in planning
    assert "showLoading: !options.hydrationScope" in planning
    assert "}), 'Seeds', 120000)" in planning


def test_3d_loading_has_reference_counted_ownership_and_soft_watchdog():
    layout = read("web/app/static/js/brachybot-viewer-layout.js")
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    planning = read("web/app/static/js/brachybot-dvh-planning.js")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")

    for required in (
        "const _viewer3DLoadingState =",
        "function beginViewer3DLoading",
        "function endViewer3DLoading",
        "function resetViewer3DLoading",
        "tokens.size > 0",
    ):
        assert required in layout
    assert "window.resetViewer3DLoading" in ui_api
    assert "window.beginViewer3DLoading('Rendering seeds and needles...')" in manual
    assert "window.beginViewer3DLoading('Rendering dose surfaces...')" in manual
    assert "still running after ${ms/1000}s; waiting for completion" in planning
    assert "Promise.race([" not in planning


def test_derived_viewer_resources_have_restart_safe_persistent_cache_contract():
    """Restart recovery must reuse only case-scoped, validated derived data."""
    cache = read("web/viewer_cache.py")
    viewer_routes = read("web/routes/viewer_routes.py")
    planning_routes = read("web/routes/planning_routes.py")

    assert "artifacts" in cache
    assert "viewer-cache" in cache
    assert "json.gz" in cache
    assert "os.replace(temporary, path)" in cache
    assert "cache_key" in cache
    assert "load_viewer_cache" in viewer_routes
    assert "schedule_viewer_cache_write" in viewer_routes
    assert "viewer_cache_key(\"segmentation_mesh\"" in viewer_routes
    assert "viewer_cache_key(\n                \"skin_mesh\"" in viewer_routes
    assert "skin-mesh" in viewer_routes
    assert "load_viewer_cache" in planning_routes
    assert "schedule_viewer_cache_write" in planning_routes
    assert "viewer_cache_key(\n                \"dose_isosurface\"" in planning_routes
    assert "dose_digest" in planning_routes


def test_label_mesh_extraction_crops_only_the_derived_display_domain():
    """OAR/CTV mesh acceleration must preserve source geometry and world position."""
    viewer_routes = read("web/routes/viewer_routes.py")

    # The crop is a display-only optimisation.  Both mesh endpoints must add
    # the crop origin back before the existing patient-world transformation,
    # and the cache key must include the crop/version contract.
    assert "_MESH_CROP_MARGIN_VOXELS = 8" in viewer_routes
    assert "def _crop_binary_surface_volume(binary_volume, margin=None)" in viewer_routes
    assert "np.any(array, axis=(1, 2))" in viewer_routes
    assert "np.any(array, axis=(0, 2))" in viewer_routes
    assert "np.any(array, axis=(0, 1))" in viewer_routes
    assert "source_mask_digest = hashlib.blake2b(" in viewer_routes
    assert '"processing_version": "label-mesh-v3-cropped"' in viewer_routes
    assert viewer_routes.count("vertices += crop_origin_zyx * np.asarray(spacing_zyx") >= 2
    assert "mask_volume = max(1, int(np.prod(source_mask_shape)))" in viewer_routes
    assert "coordinates = np.nonzero(array)" not in viewer_routes


def test_iso_surface_exceptions_are_visible_in_the_completion_ledger():
    """An unexpected per-level exception must not be silently dropped."""
    manual = read("web/app/static/js/brachybot-3d-manual.js")

    assert "Every requested level must settle into the ledger" in manual
    assert "const alreadyRecorded = failedLevels.some" in manual
    assert "rebuiltLevels[i] = levelEntry" in manual
    assert "levelEntry.status = preserved ? 'stale' : 'error'" in manual


def test_viewer_requests_share_a_bounded_retry_and_abort_contract():
    """All expensive browser resource paths must settle instead of spinning forever."""
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    layout = read("web/app/static/js/brachybot-viewer-layout.js")
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    guide = read("web/app/static/js/brachybot-surgical-guide.js")

    assert "const _VIEWER_RESOURCE_MAX_WAIT_MS = 300000" in manual
    assert "new AbortController()" in manual
    assert "externalSignal?.aborted" in manual
    assert "Retry-After" in manual
    assert "_viewer3DJsonRequest" in layout
    assert "window.fetchViewerJsonWithRetry" in volume
    assert "window.fetchViewerJsonWithRetry" in guide
    assert "for (let attempt = 0; attempt <= 60; attempt += 1)" not in manual


def test_3d_progress_overlay_never_blocks_interaction_or_cancels_hydration():
    """The legacy in-canvas marker is hidden while mesh loading stays active."""
    html = read("web/app/index.html")
    css = read("web/app/static/css/brachybot-report-controls.css")
    layout = read("web/app/static/js/brachybot-viewer-layout.js")
    manual = read("web/app/static/js/brachybot-3d-manual.js")

    assert 'id="loading3D" role="status" aria-live="polite" aria-atomic="true"' in html
    assert 'id="loading3D" role="status" aria-live="polite" aria-atomic="true" hidden' in html
    assert 'data-interaction-mode="passthrough"' in html

    hidden_rule = css.split("#loading3D", 1)[1]
    assert "display: none !important" in hidden_rule
    assert "visibility: hidden !important" in hidden_rule
    assert "pointer-events: none !important" in hidden_rule
    assert 'id="workspaceHydrationNotice"' in read("web/app/index.html")

    base_rule = css.split(".loading-overlay {", 1)[1].split("}", 1)[0]
    active_rule = css.split(".loading-overlay.active {", 1)[1].split("}", 1)[0]
    assert "pointer-events: none !important" in base_rule
    assert "pointer-events: none !important" in active_rule
    assert "pointer-events: all" not in active_rule
    assert "pointer-events: auto" not in active_rule
    # The progress UI is a compact heads-up chip, not a full-card scrim.
    assert "top: 2.25rem" in base_rule
    assert "left: 50%" in base_rule
    assert "inset: 0" not in base_rule

    render_loading = layout.split("function _renderViewer3DLoading()", 1)[1].split(
        "function beginViewer3DLoading", 1
    )[0]
    assert "loading.style.pointerEvents = 'none'" in render_loading
    assert "loading.dataset.interactionMode = 'passthrough'" in render_loading
    assert "canvas.setAttribute('aria-busy', active ? 'true' : 'false')" in render_loading
    assert "tokens.size > 0" in render_loading

    camera_interaction = manual.split("const markCameraInteraction", 1)[1].split(
        "scene3D.renderer.domElement.addEventListener('pointerdown'", 1
    )[0]
    # A pointer gesture transfers camera ownership away from auto-fit only.
    # It must not invalidate, clear or abort the background resource run.
    assert "_cameraUserInteracted = true" in camera_interaction
    assert "_cameraHydrationActive = false" in camera_interaction
    assert "invalidateSegmentationMeshPrewarm" not in camera_interaction
    assert "invalidateViewer3DRequests" not in camera_interaction
    assert "_segmentationMeshPrewarm.tasks.clear" not in camera_interaction

    prewarm = manual.split("async function prewarmSegmentationMeshes", 1)[1].split(
        "function startSegmentationMeshPrewarm", 1
    )[0]
    assert "await Promise.all(promises)" in prewarm
    assert "finally" in prewarm
