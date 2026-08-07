"""Regression checks for threshold-derived skin masks.

These checks intentionally avoid importing the full GPU application. They
protect the browser/backend contract that makes a large threshold mask a real
Data Tree object without blocking the UI or being mistaken for a Planning
mesh.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_threshold_apply_is_chunked_and_has_busy_feedback():
    index = read("web/app/index.html")
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    layout = read("web/app/static/js/brachybot-viewer-layout.js")

    assert 'id="viewerThresholdApply"' in index
    assert 'aria-busy="false"' in index
    assert "async function applyThreshold()" in volume
    assert "_countThresholdVoxels" in volume
    assert "await _yieldViewerWork()" in volume
    assert "kind: 'threshold'" in volume
    assert "await _yieldViewerPaint()" in layout
    assert "_sliceRenderGeneration" in layout


def test_threshold_mask_is_a_data_tree_mask_and_not_a_planning_mesh():
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    manual = read("web/app/static/js/brachybot-3d-manual.js")
    layout = read("web/app/static/js/brachybot-viewer-layout.js")

    assert "const id = 'mask_threshold'" in volume
    assert "source: 'viewer_threshold'" in volume
    assert "_reconstructThresholdMask3D" in layout
    assert "const isMaskMesh" in manual
    assert "never leak it into Planning -> 3D meshes" in manual


def test_skin_surface_waits_for_background_ct_hydration():
    routes = read("web/routes/viewer_routes.py")
    layout = read("web/app/static/js/brachybot-viewer-layout.js")

    skin_route = routes.split('def api_viewer_3d_skin', 1)[1].split(
        'def api_planning_seeds_3d', 1
    )[0]
    assert '"pending": True' in skin_route
    assert "), 202" in skin_route
    assert "maxPendingAttempts" in layout
    assert "data.pending" in layout
