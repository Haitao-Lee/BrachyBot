from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_traversability_move_is_metadata_only_and_replan_is_conditional():
    viewer = _read("web/app/static/js/brachybot-viewer-volume.js")

    # The effective structure catalogue is refreshed for the Data Tree, but a
    # traversability policy change must not dispose/reload label geometry.
    assert "const reloadStructureGeometry = structureMutation" in viewer
    assert "reloadStructureGeometry: false" in viewer
    assert "Never dispose or" in viewer

    # Replan is meaningful only when this case already has a plan. A fresh
    # segmentation case must complete the move without showing that dialog.
    assert "function _planningMutationState()" in viewer
    assert "if (!planningBeforeMutation.inProgress && planningBeforeMutation.hasPlan)" in viewer
    assert "This case has no completed plan, so no replan is needed" in viewer

    # A move-only decision keeps the current clinical presentation visible,
    # while an actual traversability replan can skip redundant label loading.
    assert "preservePlanningPresentation: shouldReplan !== true" in viewer
    assert "replanAfterStructureChange(expectedSessionId, { skipLabelLoad: true });" in viewer

