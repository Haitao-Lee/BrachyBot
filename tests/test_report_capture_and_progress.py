"""Regression contracts for report capture and truthful response progress."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_figure_one_detail_view_keeps_the_complete_ctv_in_frame():
    source = _read("web/app/static/js/brachybot-report-editor.js")

    assert "function _frameReportCamera" in source
    assert "halfHeight / Math.tan(halfFovY)" in source
    assert "halfWidth / Math.tan(halfFovX)" in source
    assert "halfDepth + planarDistance" in source
    assert "margin: mode === 'detail' ? 1.10 : 1.30" in source
    assert "targetAspect: REPORT_FIGURE_ASPECT" in source
    assert "id === 'skin_surface'" in source
    assert "guide_skin_surface" in source
    assert "includeOars: true, includeNeedles: true" in source
    assert "REPORT_FIGURE_LONG_EDGE = 1800" in source
    assert "_captureReportCanvasCrop(c, targetAspect, maxOutputEdge)" in source


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

    assert "await autoCaptureReportFigures({ sessionId: expectedSessionId });" in block
    assert "options.allowLegacyReportFigureRecovery === true" in block
    assert block.index("options.allowLegacyReportFigureRecovery === true") < block.index("const _replaceOrCreate =")
    assert "Object.assign(window.reportForm.figures[idx], entry)" not in block


def test_figure_one_capture_contract_survives_report_artifact_round_trip():
    editor = _read("web/app/static/js/brachybot-report-editor.js")
    workspace = _read("web/app/static/js/brachybot-workspace.js")
    viewer = _read("web/app/static/js/brachybot-viewer-volume.js")
    api = _read("web/app/static/js/brachybot-ui-api.js")
    export_service = _read("web/export_service.py")

    assert "REPORT_FIGURE_ONE_CAPTURE_CONTRACT = 'figure1-global-overview-target-detail-v2'" in editor
    assert editor.count("captureContract: REPORT_FIGURE_ONE_CAPTURE_CONTRACT") == 2
    assert "capture_contract: String(figure.captureContract || '')" in workspace
    assert "capture_contract: String(figure.captureContract || '')" in api
    assert "viewMetadata: item.metadata?.view_metadata || item.metadata || {}" in viewer
    assert '"capture_contract": figure.get("captureContract")' in export_service


def test_report_preview_groups_figures_by_stable_metadata_not_array_position():
    source = _read("web/app/static/js/brachybot-report-export.js")

    assert "function _reportFiguresForGroup" in source
    assert "figure?.figureGroup" in source
    assert "left?.sortOrder" in source
    assert "right?.sortOrder" in source
    assert "const figure1Rows = _reportFiguresForGroup(f, 'figure1')" in source
    assert "const figure2Rows = _reportFiguresForGroup(f, 'figure2')" in source
    assert "renderFigurePages" in source
    assert "f.figures[0]" not in source
    assert "f.figures[1]" not in source


def test_native_report_images_use_one_bounded_evidence_page_each():
    source = _read("web/app/static/js/brachybot-report-export.js")
    shell = _read("web/app/static/js/brachybot-report-shell.js")
    screen_css = _read("web/app/static/css/brachybot-panels-viewers.css")

    assert "const figure1PageCount = figure1Rows.length;" in source
    assert "const figure2PageCount = figure2Rows.length;" in source
    assert "const supplementalPageCount = supplementalRows.length;" in source
    assert "for (let offset = 0; offset < rows.length; offset += 1)" in source
    assert "const pageRows = rows.slice(offset, offset + 1);" in source
    assert "max-width: 100%" in source
    assert "function _reportFigurePageOrientation" in source
    assert "data-page-orientation=\"${orientation}\"" in source
    assert "size: A4 portrait" in source
    assert "size: A4 landscape" in source
    assert "width: auto" in source
    assert "min-width: 0" in source
    assert "max-height: 176mm" in source
    assert "max-height: 132mm" in source
    assert "overflow: hidden" in source
    assert ".report-figure-page .hp-subfigure img" in screen_css
    assert ".report-page--landscape" in screen_css
    assert "width: 297mm" in screen_css
    assert "max-height: 176mm" in screen_css
    assert "max-height: 132mm" in screen_css
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
    assert "[...existingFigures, ...recoveredFigures]" in workspace
    assert "function _reportFigureStableIdentity" in export
    assert "const seen = new Set();" in export
    assert "${figureNumber}(${escHtml(headingSubfigure)})" in export
    assert "function _reportFigureStableKey" in api
    assert "seenFigureKeys.has(stableKey)" in api


def test_figure_two_rejects_black_webgl_capture_and_retries():
    source = _read("web/app/static/js/brachybot-report-editor.js")

    assert "async function captureDoseSurface3D(label)" in source
    assert "3D dose-surface capture is black" in source
    assert "doseSurfaceDataUrl = await captureDoseSurface3D('primary');" in source
    assert "doseSurfaceDataUrl = await captureDoseSurface3D('retry');" in source
    assert "_isDoseTexturableMesh(id, mesh)" in source


def test_response_trace_exposes_synthesis_and_final_delivery_phases():
    source = _read("agent_runtime/chat_workflows.py")

    assert '"Response Synthesis"' in source
    assert '"Final Response"' in source
    assert 'yield yield_event("step", _synthesis_step)' in source
    assert 'yield yield_event("response", payload)' in source
    assert 'final_step["status"] = "done"' in source


def test_single_needle_replan_uses_changed_trajectory_incremental_dose_path():
    source = _read("web/server_support.py")
    assert "changed_trajectories = set()" in source
    assert "trajectory_id not in changed_trajectories" in source
    assert "incremental needle replan" in source
    assert 'baseline_dose_key = "dose_distribution" if agent.memory.retrieve("manual_ai_dose") else "algorithm_plan_dose_distribution"' in source


def test_manual_needle_refresh_does_not_rebuild_the_whole_planning_scene():
    source = _read("web/app/static/js/brachybot-3d-manual.js")
    refresh_body = source.split("async function _refreshManualDoseViews", 1)[1].split("function _manualUiPosition", 1)[0]
    assert "loadDoseOverlay" in refresh_body
    assert "loadAllSlices" in refresh_body
    assert "refreshPlanningUI" not in refresh_body
    assert "data?.needles" in refresh_body


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
