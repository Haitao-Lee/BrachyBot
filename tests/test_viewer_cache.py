import gzip
import json

from web.viewer_cache import load_viewer_cache, save_viewer_cache, viewer_cache_key


def test_viewer_cache_key_is_stable_and_changes_with_derived_inputs():
    components = {
        "planning_id": "planning-1",
        "shape": [12, 16, 20],
        "threshold_gy": 120.0,
    }
    first = viewer_cache_key("dose_isosurface", components)
    second = viewer_cache_key("dose_isosurface", dict(reversed(list(components.items()))))
    changed = viewer_cache_key("dose_isosurface", {**components, "threshold_gy": 180.0})

    assert first == second
    assert first != changed
    assert len(first) == 40


def test_viewer_cache_round_trip_is_atomic_and_case_scoped(tmp_path):
    root = tmp_path / "case"
    key = viewer_cache_key("segmentation_mesh", {"mask_digest": "abc"})
    payload = {
        "success": True,
        "vertex_count": 3,
        "face_count": 1,
        "vertices": [[0.0, 0.0, 0.0]],
        "faces": [[0, 0, 0]],
    }

    path = save_viewer_cache(root, "segmentation-mesh", key, payload)

    assert path is not None
    assert path == root / "artifacts" / "viewer-cache" / "v1" / "segmentation-mesh" / f"{key}.json.gz"
    assert load_viewer_cache(root, "segmentation-mesh", key) == payload
    assert not list(path.parent.glob("*.tmp"))


def test_corrupt_or_wrong_key_cache_is_treated_as_a_miss(tmp_path):
    root = tmp_path / "case"
    key = viewer_cache_key("dose_isosurface", {"threshold": 120})
    path = save_viewer_cache(root, "dose-isosurface", key, {"success": True})
    assert path is not None

    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump({"schema": 1, "cache_key": "wrong", "payload": {"success": True}}, handle)
    assert load_viewer_cache(root, "dose-isosurface", key) is None

    path.write_bytes(b"not a gzip payload")
    assert load_viewer_cache(root, "dose-isosurface", key) is None
