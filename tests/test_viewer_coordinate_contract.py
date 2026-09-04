"""Regression checks for the browser MPR coordinate contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _clamp_index(value, count, rounder=round):
    size = max(0, int(count or 0))
    maximum = max(0, size - 1)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(maximum, rounder(numeric)))


def test_axial_display_and_volume_z_are_exact_inverses_for_any_depth():
    for depth in (1, 2, 3, 11, 48, 97):
        for volume_z in range(depth):
            display_z = depth - 1 - _clamp_index(volume_z, depth)
            round_trip = depth - 1 - _clamp_index(display_z, depth)
            assert round_trip == volume_z


def test_frontend_uses_one_mapping_for_pointer_navigation_and_annotations():
    volume = read("web/app/static/js/brachybot-viewer-volume.js")
    manual = read("web/app/static/js/brachybot-manual-annotation.js")
    index = read("web/app/index.html")

    assert "function _viewerAxialDisplayToVolumeZ" in volume
    assert "function _viewerVolumeZToAxialDisplay" in volume
    assert "function _viewerMprImageToVoxel" in volume
    assert "displayZ: _viewerVolumeZToAxialDisplay(z, zCount)" in volume
    assert manual.count("_viewerMprImageToVoxel(axis, imgX, imgY") >= 2
    assert "updates.axial = voxel.displayZ" in manual
    assert "mapVoxel(axis, coords.x, coords.y" in manual
    assert "volZ = state.slices.axial" not in manual
    assert "updates.axial = volZ" not in manual
    assert "brachybot-viewer-volume.js?v=51" in index
    assert "brachybot-manual-annotation.js?v=22" in index


def test_server_fallback_and_threshold_use_the_same_axial_only_flip():
    routes = read("web/routes/viewer_routes.py")

    assert "slice_data = ct_windowed[:, :, slice_index]" in routes
    assert "slice_data = ct_windowed[:, slice_index, :]" in routes
    assert "mask_slice = mask_data[:, :, slice_index]" in routes
    assert "mask_slice = mask_data[:, slice_index, :]" in routes
    assert "mask.shape[0] - 1 - slice_index" in routes
    assert "mask_data[z_arr" not in routes
    assert "ct_windowed[z_arr" not in routes
