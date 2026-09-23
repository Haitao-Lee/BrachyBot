"""Regression contracts for report capture and truthful response progress."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_report_markdown_uses_one_safe_renderer_for_preview_pdf_and_html_export():
    export = _read("web/app/static/js/brachybot-report-export.js")
    styles = _read("web/app/static/css/brachybot-panels-viewers.css")
    routes = _read("web/routes/planning_routes.py")

    assert "function _renderReportMarkdownWithMarked" in export
    assert "renderer.heading = (text, level)" in export
    assert "headerIds: false" in export
    assert "return _renderMarkdownLegacy(md);" in export
    legacy_start = export.index("function _renderMarkdownLegacy")
    legacy_end = export.index("// ----- 17. Render the multi-page A4 preview")
    assert "###" not in export[legacy_start:legacy_end]
    assert "md-report-h1" in export and "md-report-h6" in export
    assert "md-report-ul" in styles and "md-report-table" in styles
    assert "def _render_report_markdown_html" in routes
    assert "body = _render_report_markdown_html(payload[\"narrative_markdown\"])" in routes
    assert "html.escape(payload[\"narrative_markdown\"]).replace" not in routes

def test_figure_one_detail_view_keeps_the_complete_ctv_in_frame():
    source = _read("web/app/static/js/brachybot-report-editor.js")

    assert "function _frameReportCamera" in source
    assert "halfHeight / Math.tan(halfFovY)" in source
    assert "halfWidth / Math.tan(halfFovX)" in source
    assert "halfDepth + planarDistance" in source
    # Keep a small framing safety border while bringing both report views
    # materially closer to the treatment geometry.
    assert "margin: mode === 'detail' ? 1.10 : 1.08" in source
    assert "targetAspect: REPORT_FIGURE_ASPECT" in source
    assert "function _computeGlobalPlanBox" in source
    assert "const overviewBox = _computeGlobalPlanBox({ includeNeedles: true });" in source
    assert "id === 'skin_surface'" in source
    assert "guide_skin_surface" in source
    assert "function _captureReportCanvasFocus" in source
    assert "const cropContainsFocus = sx <= boxLeft + 0.5" in source
    assert "Focused crop would exclude projected plan content" in source
    assert "return _computeFocusedPlanBox({ includeOars: true, includeNeedles });" in source
    assert "const detailBox = new THREE.Box3();" in source
    assert "renderReport3DFrame = function (focusBox, cameraMargin, readFrame)" in source
    assert "padding: 0.16" in source
    assert "requireFocusCrop: true" in source
    assert "REPORT_FIGURE_LONG_EDGE = 2400" in source
    assert "_captureReportCanvasFit(reportCanvas, maxOutputEdge)" in source


def test_figure_two_dose_surface_capture_embeds_the_3d_dose_colorbar():
    source = _read("web/app/static/js/brachybot-report-editor.js")

    assert "function _drawReport3DDoseColorbar" in source
    assert "getDoseColorbarConfig('threeD')" in source
    assert "_doseColorFromScope('threeD', value)" in source
    assert "_drawReport3DDoseColorbar(" in source
    assert "Report-only annotations" in source


def test_report_figures_are_native_subfigures_and_peak_dose_capture_is_ready():
    editor = _read("web/app/static/js/brachybot-report-editor.js")
    export = _read("web/app/static/js/brachybot-report-export.js")
    viewer = _read("web/app/static/js/brachybot-3d-manual.js")

    for axis in (
        "report_fig1_global",
        "report_fig1_closeup",
        "report_fig2_axial",
        "report_fig2_sagittal",
        "report_fig2_coronal",
        "report_fig2_dose_surface",
        "report_fig2_dvh",
    ):
        assert axis in editor
    assert "figureGroup: 'figure1'" in editor
    assert "figureGroup: 'figure2'" in editor
    assert "seed_plan_composite" not in editor
    assert "dose_dvh_composite" not in editor
    assert "_waitForReportDoseSlice" in editor
    assert "doseCanvas.dataset.renderedSlice = String(sliceIndex)" in viewer
    assert "canvas.dataset.renderedSlice = String(sliceIndex)" in viewer

    # The colorbar canvas is a UI decoration, not a medical image layer.
    assert "parent.querySelectorAll('canvas')" not in export
    assert "`doseOverlayCanvas${cap}`" in export
    assert "`contourCanvas${cap}`" in export
    assert "`seedsOverlayCanvas${cap}`" in export
    assert "`doseColorbar${cap}`" in export


def test_late_viewer_hydration_delegates_to_canonical_report_capture():
    source = _read("web/app/static/js/brachybot-dvh-planning.js")
    start = source.index("4f-2. Re-capture report figures only through the canonical report")
    block = source[start:source.index("// 5. Data tree badges", start)]

    # Capture is deliberately deferred until the final dose/DVH readiness
    # boundary, after the legacy fallback block.
    capture_start = source.index('// 11. Auto-capture report figures')
    capture = source[capture_start:source.index('// 12. Auto-fill report form', capture_start)]
    assert "sessionId: expectedSessionId,\n                    planningId: expectedPlanningId," in capture
    assert 'if (reportCaptureReady' in capture
    assert "options.allowLegacyReportFigureRecovery === true" in block
    assert block.index("options.allowLegacyReportFigureRecovery === true") < block.index("const _replaceOrCreate =")
    assert "Object.assign(window.reportForm.figures[idx], entry)" not in block


def test_figure_one_capture_contract_survives_report_artifact_round_trip():
    editor = _read("web/app/static/js/brachybot-report-editor.js")
    workspace = _read("web/app/static/js/brachybot-workspace.js")
    viewer = _read("web/app/static/js/brachybot-viewer-volume.js")
    api = _read("web/app/static/js/brachybot-ui-api.js")
    export_service = _read("web/export_service.py")

    assert "REPORT_FIGURE_ONE_CAPTURE_CONTRACT = 'figure1-global-overview-v10-framed-hires'" in editor
    assert "REPORT_FIGURE_ONE_CLOSEUP_CAPTURE_CONTRACT = 'figure1-target-closeup-v10-framed-hires'" in editor
    assert "report_fig1_global: REPORT_FIGURE_ONE_CAPTURE_CONTRACT" in editor
    assert "report_fig1_closeup: REPORT_FIGURE_ONE_CLOSEUP_CAPTURE_CONTRACT" in editor
    assert "const _isFigureOneOar = (id, mesh)" in editor
    assert "mesh.visible = !_isStandaloneGenericReportMask(id, mesh)" in editor
    assert "OAR and guide-skin meshes are hidden" in editor
    assert "function _computeGlobalPlanBox" in editor
    assert "captureProfile: 'global_overview'" in editor
    assert "captureProfile: 'target_closeup'" in editor
    legacy = _read("web/app/static/js/brachybot-dvh-planning.js")
    assert "const isOar = key === 'oar'" in legacy
    assert "mesh.visible = !isOar && (isCtv || isSeed || isNeedle);" in legacy
    assert "capture_contract: String(figure.captureContract || '')" in workspace
    assert "capture_profile: String(figure.captureProfile || '')" in workspace
    assert "capture_contract: String(figure.captureContract || '')" in api
    assert "capture_profile: String(figure.captureProfile || '')" in api
    assert "viewMetadata: item.metadata?.view_metadata || item.metadata || {}" in viewer
    assert '"capture_contract": figure.get("captureContract")' in export_service
    assert "captureContract: 'figure1-global-overview-v10-framed-hires'" in workspace
    assert "captureContract: 'figure1-target-closeup-v10-framed-hires'" in workspace
    assert "captureProfile: 'global_overview'" in workspace
    assert "captureProfile: 'target_closeup'" in workspace


def test_figure_one_b_uses_report_only_thin_needles_and_restores_live_geometry():
    """The close-up must reveal individual seeds without changing the live plan."""
    editor = _read("web/app/static/js/brachybot-report-editor.js")
    manual = _read("web/app/static/js/brachybot-3d-manual.js")
    layout = _read("web/app/static/js/brachybot-viewer-layout.js")

    assert "const _savedNeedleGeometries = {};" in editor
    assert "const REPORT_FIGURE_ONE_NEEDLE_RADIUS = 0.12;" in editor
    assert "const _applyFigureOneNeedleStyle = (id, mesh) =>" in editor
    assert "mesh.geometry = replacement.geometry;" in editor
    assert "currentGeometry.dispose?.();" in editor
    assert "if (_isFigureOneNeedle(id, mesh)) {\n                    _applyFigureOneNeedleStyle(id, mesh);" in editor
    assert "displayPoints: points.map(point => [point.x, point.y, point.z])" in manual
    assert "displayPoints: points.map(point => [point.x, point.y, point.z])" in layout

    # The report close-up changes presentation geometry only; the seed geometry
    # remains the configured physical size and is rendered above the shaft.
    assert "_setFigureOneOpacity(mesh, 1.0)" in editor
    assert "_setFigureOneOpacity(mesh, 0.8)" in editor


def test_report_preview_groups_figures_by_stable_metadata_not_array_position():
    source = _read("web/app/static/js/brachybot-report-export.js")

    assert "function _reportFiguresForGroup" in source
    assert "function _reportFigureIsInvalidForExport" in source
    assert "figure?.figureGroup" in source
    assert "left?.sortOrder" in source
    assert "right?.sortOrder" in source
    assert "const figure1Rows = _reportFiguresForGroup(f, 'figure1')" in source
    assert "const figure2Rows = _reportFiguresForGroup(f, 'figure2')" in source
    assert "renderFigurePages" in source
    assert "f.figures[0]" not in source
    assert "f.figures[1]" not in source


def test_native_report_images_use_one_bounded_portrait_a4_page_each():
    source = _read("web/app/static/js/brachybot-report-export.js")
    shell = _read("web/app/static/js/brachybot-report-shell.js")
    editor = _read("web/app/static/js/brachybot-report-editor.js")
    screen_css = _read("web/app/static/css/brachybot-panels-viewers.css")

    assert "const figure1PageCount = figure1Rows.length;" in source
    assert "const figure2PageCount = figure2Rows.length;" in source
    assert "const supplementalPageCount = supplementalRows.length;" in source
    assert "const reportOarRowsPerPage = 24;" in source
    assert "const oarPageCount = Math.max(1" in source
    assert "for (let offset = 0; offset < rows.length; offset += 1)" in source
    assert "const pageRows = rows.slice(offset, offset + 1);" in source
    assert "max-width: 100%" in source
    assert "const REPORT_PAGE_ORIENTATION = 'portrait';" in source
    assert "function _reportFigurePageOrientation()" in source
    assert 'class="report-page report-figure-page"' in source
    assert "report-page report-figure-page report-page--" not in source
    assert "data-page-orientation=" in source
    assert "size: A4 portrait" in source
    assert "size: A4 landscape" not in source
    assert "width: 100% !important; max-width: 100% !important" in source
    assert "object-fit: contain" in source
    assert "min-width: 0" in source
    assert "height: 297mm; min-height: 297mm; max-height: 297mm" in source
    assert "width: 297mm" not in source
    assert "max-height: 176mm" in source
    assert "max-height: 132mm" not in source
    assert "overflow: hidden" in source
    assert 'class="hp-subfigure-media"' in source
    assert "async function _waitForReportPrintAssets" in source
    assert "await _waitForReportPrintAssets(printWindow);" in source
    assert "documentRef.fonts?.ready" in source
    assert "image.decode()" in source
    assert "REPORT_FIGURE_LONG_EDGE = 2400" in editor
    assert ".report-page {" in screen_css
    assert "width: 210mm;" in screen_css
    assert "height: 297mm;" in screen_css
    assert ".report-figure-page .hp-subfigure img" in screen_css
    assert ".report-figure-page .hp-subfigure-media" in screen_css
    assert "flex: 0 0 176mm" in screen_css
    assert "width: 297mm" not in screen_css
    assert "max-height: 132mm" not in screen_css
    assert "Math.max(...pages.map(page => page.offsetWidth || 0))" in shell
    assert "wrap.style.transformOrigin = 'top center';" in shell


def test_report_figure_identity_survives_server_artifact_fallback():
    routes = _read("web/routes/planning_routes.py")
    workspace = _read("web/app/static/js/brachybot-workspace.js")
    planning = _read("web/app/static/js/brachybot-dvh-planning.js")

    assert 'str(view_metadata.get("axis") or view_metadata.get("capture_role") or "")' in routes
    assert "report_identity = f\"{planning_id or '__unassigned__'}:{report_axis}\"" in routes
    assert "hashlib.sha256" in routes
    assert "function normalizeReportFigures" in workspace
    assert "REPORT_FIGURE_DEFINITIONS" in workspace
    assert "const legacyAxis = Object.entries(REPORT_FIGURE_DEFINITIONS).find" in workspace
    assert "duplicate legacy Figure 1(a) entries collapse correctly" in workspace
    assert "_artifactFallback" in workspace
    assert "const recoveredFigureMetadata = (axis, viewMetadata = {}) =>" in workspace
    assert "report_fig2_dose_surface" in workspace
    assert "identityMatch" in workspace
    assert "...figureMetadata" in workspace
    assert "if (figure._artifactFallback || !figure.title || isGenericReportFigureTitle(figure.title))" in workspace
    assert "if (figure._artifactFallback || !figure.caption) figure.caption = definition.caption;" in workspace
    assert "const requiredReportAxes = new Set" in planning
    assert "hasCompleteReportFigureSet" in planning


def test_report_restore_and_export_deduplicate_by_stable_subfigure_role():
    workspace = _read("web/app/static/js/brachybot-workspace.js")
    export = _read("web/app/static/js/brachybot-report-export.js")
    api = _read("web/app/static/js/brachybot-ui-api.js")

    assert "reportFigureIdentity" in workspace
    assert "[...currentFigures, ...recoveredFigures]" in workspace
    assert "function _reportFigureStableIdentity" in export
    assert "const seen = new Set();" in export
    assert "${figureNumber}(${escHtml(headingSubfigure)})" in export
    assert "function _reportFigureStableKey" in api
    assert "const existingIndex = figures.findIndex" in api


def test_report_attachment_registry_prefers_new_content_version_for_same_role():
    from web.workspace_store import _merge_attachment_list

    old = {
        "id": "report-figure-planning-1-report_fig1_closeup",
        "url": "/api/sessions/session/screenshots/report_screenshot_report_fig1_closeup_old.png?v=old",
        "planning_id": "planning-1",
        "view_metadata": {
            "figure_group": "figure1",
            "figure_number": 1,
            "subfigure": "b",
            "capture_role": "planning_closeup",
        },
    }
    fresh = {
        **old,
        "url": "/api/sessions/session/screenshots/report_screenshot_report_fig1_closeup_new.png?v=fresh",
        "sha256": "fresh",
    }

    merged = _merge_attachment_list([old], [fresh])
    assert len(merged) == 1
    assert merged[0]["url"].endswith("?v=fresh")
    assert merged[0]["sha256"] == "fresh"


def test_figure_two_rejects_black_webgl_capture_and_retries():
    source = _read("web/app/static/js/brachybot-report-editor.js")

    assert "async function captureDoseSurface3D(label)" in source
    assert "if (!hasLitPixel) return null;" in source
    assert "const url = renderReport3DFrame?.(" in source
    assert "doseSurfaceDataUrl = await captureDoseSurface3D('primary');" in source
    assert "doseSurfaceDataUrl = await captureDoseSurface3D('retry');" in source
    assert "_isDoseTexturableMesh(id, mesh)" in source


def test_response_trace_exposes_synthesis_and_final_delivery_phases():
    source = _read("agent_runtime/chat_workflows.py")

    assert '"Response Synthesis"' in source
    assert '"Final Response"' in source
    assert 'yield yield_event("step", _synthesis_step)' in source
    assert 'yield yield_event("response", normalized_payload)' in source
    assert 'final_step["status"] = "done"' in source


def test_single_needle_replan_uses_changed_trajectory_incremental_dose_path():
    source = _read("web/server_support.py")
    assert "changed_trajectories = set()" in source
    # Association aliases are now supported (needle_id, trajectory_id, and
    # numeric restored IDs), so the incremental path intersects the changed
    # key set instead of comparing one raw trajectory_id string.
    assert "_manual_geometry_keys(" in source
    assert "intersection(changed_trajectories)" in source
    assert "incremental needle replan" in source
    assert 'baseline_dose_key = "dose_distribution" if agent.memory.retrieve("manual_ai_dose") else "algorithm_plan_dose_distribution"' in source


def test_manual_needle_refresh_does_not_rebuild_the_whole_planning_scene():
    source = _read("web/app/static/js/brachybot-3d-manual.js")
    refresh_body = source.split("async function _refreshManualDoseViews", 1)[1].split("function _manualUiPosition", 1)[0]
    assert "loadDoseOverlay" in refresh_body
    assert "loadAllSlices" in refresh_body
    assert "refreshPlanningUI" not in refresh_body
    assert "data?.needles" in refresh_body


def test_manual_needle_replan_rebuilds_authoritative_seed_meshes():
    """A reprojected seed must not remain at its pre-drag WebGL position."""
    source = _read("web/app/static/js/brachybot-3d-manual.js")
    refresh_body = source.split("async function _refreshManualDoseViews", 1)[1].split("function _manualUiPosition", 1)[0]

    assert "const authoritativeSeedIds = new Set" in refresh_body
    assert "mesh?.userData?.type !== 'seed'" in refresh_body
    assert "_upsertSceneMesh(seed.id, _makeSeedMesh(seed));" in refresh_body
    assert "_syncSeedsOverlayFromDataTree();" in refresh_body


def test_manual_needle_replan_refreshes_downstream_artifacts_in_order():
    manual = _read("web/app/static/js/brachybot-3d-manual.js")
    guide = _read("web/app/static/js/brachybot-surgical-guide.js")

    # The dose response is not the end of a needle replan.  The browser must
    # wait for the new Viewer frame, then update the guide, and only then let
    # the canonical report capture publish figures for the new Planning.
    assert "async function _refreshManualReplanArtifacts" in manual
    orchestration = manual.split("async function _refreshManualReplanArtifacts", 1)[1].split(
        "async function _runManualDoseJob", 1
    )[0]
    assert "backgroundDoseViewerRefresh" in orchestration
    assert "ensureSurgicalGuideForCurrentPlan" in orchestration
    assert "forceRegenerate: true" in orchestration
    assert "captureFigures: true" in orchestration
    assert orchestration.index("backgroundDoseViewerRefresh") < orchestration.index(
        "ensureSurgicalGuideForCurrentPlan"
    )
    assert orchestration.index("ensureSurgicalGuideForCurrentPlan") < orchestration.index(
        "Report.autoFill.fromAll"
    )
    assert "report: reportUpdated ? 'ready' : 'stale'" in orchestration
    assert "requestSequence" in manual

    # A prior guide is remembered and removed before the new dose request;
    # cases without a guide are not auto-populated with one.
    assert "prepareSurgicalGuideForManualReplan" in manual
    assert "regenerateForManualPlan" in manual
    assert "manualPlanGuideRefreshRequested" in guide
    assert "forceRegenerate" in guide
    assert "planningId: options.planningId || null" in guide


def test_manual_replan_has_stable_id_change_detection_and_deadline_guard():
    source = _read("web/server_support.py")
    assert "stable needle id first" in source
    assert "BRACHYBOT_MANUAL_REPLAN_TIMEOUT_S" in source
    assert "seed_plan[trajectory][2]" in source
    assert "deadline=interactive_deadline" in source
    # The trajectory-only fallback is valid only when no stable ids matched;
    # an unconditional second occurrence would reintroduce full-plan reruns
    # after a workspace restore.
    assert source.count("changed.update(set(old_by_trajectory).symmetric_difference(new_by_trajectory))") == 1

def test_figure_two_never_pairs_a_normal_surface_with_a_dose_colorbar():
    editor = _read("web/app/static/js/brachybot-report-editor.js")
    layout = _read("web/app/static/js/brachybot-viewer-layout.js")
    workspace = _read("web/app/static/js/brachybot-workspace.js")

    assert "figure2-dose-surface-v6-framed-hires" in editor
    assert "function _reportDoseSurfaceEvidence()" in editor
    assert "doseTextureMapped === true" in editor
    assert "No CTV/OAR mesh with validated dose vertex colors was rendered" in editor
    assert "displayMode: 'dose_surface'" in editor
    assert "renderSignature: 'dose_texture_vertex_colors'" in editor
    assert "if (state.doseTexture.applying)" in layout
    assert "function _doseTextureRuntimeReady()" in layout
    assert "_restoreDoseTextureMaterials();" in layout
    assert "Dose surface mapping became stale before render" in layout
    assert "state.doseTexture.renderSignature = DOSE_TEXTURE_RUNTIME_SIGNATURE" in layout
    assert "return { success: true, enabled: !!state.doseTexture.enabled, mappedMeshIds }" in layout
    assert "return { success: false, enabled: false, error: e?.message || String(e) }" in layout
    assert "figure2-dose-surface-v6-framed-hires" in workspace


def test_late_dose_readiness_can_repair_missing_report_figures():
    """A planning run that outlives the chat retry window must still capture.

    Dose and DVH can be published many minutes after the run starts. The
    chat-turn terminal refresh used to stop retrying after ~2 minutes and the
    dose-refresh boundary explicitly forbade report capture, so a slow run
    silently shipped a report with no figures.
    """
    manual = _read("web/app/static/js/brachybot-3d-manual.js")
    chat = _read("web/app/static/js/brachybot-chat-todo.js")

    dose_block = manual.split("async function _refreshDoseAfterPlanningEvent", 1)[1].split(
        "})().finally", 1
    )[0]
    assert "captureReportFigures: true" in dose_block
    assert "captureReportFigures: false" not in dose_block
    # The chat-turn refresh keeps retrying long enough for the real pipeline.
    assert "attempt < 400" in chat
    assert "Math.min(2500, 250 + (attempt + 1) * 25)" in chat


def test_figure_one_is_always_normal_surface_and_export_never_recaptures():
    """Fig 1 is normal anatomy; export must print the on-screen report.

    Two regressions:
      * Figure 1 only disabled dose-surface mode when the persisted flag read
        true, so a stale runtime mapping could leak a dose wash into Fig 1(b).
      * Export re-ran the full capture before printing, which mutated the
        report and, because the print window was opened after an await, let
        the browser block the dialog.
    """
    editor = _read("web/app/static/js/brachybot-report-editor.js")
    export = _read("web/app/static/js/brachybot-report-export.js")

    figure1 = editor.split("FIGURE 1: 3D SEED IMPLANT PLAN", 1)[1].split(
        "FIGURE 2", 1
    )[0]
    assert "setDoseTextureMode(false, { silent: true })" in figure1
    assert "if (state.doseTexture?.enabled) {" not in figure1
    assert "if (normalMode?.stale) return { stale: true };" in editor

    pdf = export.split("async function exportReportPDF()", 1)[1].split(
        "function exportReportHTML()", 1
    )[0]
    assert "autoCaptureReportFigures" not in pdf
    open_index = pdf.index("window.open('', '_blank')")
    first_await = pdf.index("await ")
    assert open_index < first_await, (
        "the print window must open inside the click gesture, before any await"
    )


def test_report_auto_fill_tool_reuses_the_canonical_capture_pipeline():
    """A report generated through the server report_auto_fill tool must also
    regenerate its standard figures.

    report_auto_fill only produces a field patch. The canonical client report
    action owns visual preparation and figure capture, so the turn handler must
    run it too. Otherwise a turn that used report_auto_fill (the LLM's choice
    when the request mixed a guide regeneration with a report) filled the
    narrative but never re-captured the figures, while a ui_controller
    report.autofill turn did.
    """
    chat = _read("web/app/static/js/brachybot-chat-todo.js")
    api = _read("web/app/static/js/brachybot-ui-api.js")

    marker = "data.tool === 'report_auto_fill'"
    assert marker in chat
    branch = chat[chat.index(marker):]
    branch = branch[:branch.index("data.tool === 'ui_screenshot'")]
    assert "autoFillScope === 'all'" in branch
    assert "'report.autofill'" in branch
    assert "_executeUIActionsWithProgress" in branch
    # One heavy capture per case even when both report paths fire in one turn.
    assert "_reportAutoFillInFlight" in api
