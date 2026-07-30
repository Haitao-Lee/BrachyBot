"""Regression contracts for chat-driven planning result delivery.

The clinical pipeline may finish on a background worker, but its results must
still travel through the same case-bound UI path: labels first, then planning
objects, dose/DVH/report products, and finally non-blocking full OAR meshes.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_chat_segmentation_completion_loads_labels_before_background_meshes():
    chat = read("web/app/static/js/brachybot-chat-todo.js")

    assert "loadLabelVolumes({" in chat
    assert "forceFresh: true" in chat
    assert "reconcileSegmentationViewerState" in chat
    assert "startSegmentationMeshPrewarm(" in chat
    assert "data.tool === 'oar_segmentation' ? { allOAR: true } : {}" in chat


def test_full_oar_reconstruction_is_non_blocking_after_the_essential_meshes():
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    block = manual.split("async function loadCTVAndObstacleMeshes()", 1)[1].split(
        "// Load dose distribution", 1
    )[0]

    assert "await prewarmSegmentationMeshes('all', { showStatus: false, batchSize: 3 });" in block
    assert "startSegmentationMeshPrewarm('all', {" in block
    assert "allOAR: true" in block
    assert "function startSegmentationMeshPrewarm(kind = 'all', opts = {})" in manual


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
        "loadCTVAndObstacleMeshes()",
        "reportAutoFill({ sessionId: expectedSessionId })",
        "updateClinicalEvaluation()",
    ):
        assert required in planning
    assert "loadAllIsoSurfaces({ reconstruct3d: true })" in planning


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
    assert "visible2D: savedSeedAppearance" in manual
    assert "visible2D !== false" in annotation
    assert "['visible', 'visible2D', 'visible3D', 'opacity', 'color', 'material', 'locked']" in workspace


def test_iso_surface_refresh_keeps_data_tree_appearance_and_view_flags():
    """Refreshing dose geometry must not reset a user's visibility choices."""
    manual = read("web/app/static/js/brachybot-3d-manual.js")

    assert "const priorLevels = new Map" in manual
    assert "existing.visible2D = existing.visible2D !== false" in manual
    assert "existing.visible3D = existing.visible3D !== false" in manual
    assert "dataTreeState.planning.doseLevels.push(existing)" in manual
