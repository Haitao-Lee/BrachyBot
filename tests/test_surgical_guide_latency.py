"""Exact geometry differences against the complete pre-optimization module."""
import hashlib
import importlib.util
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
import SimpleITK as sitk

from web import surgical_guide as current
from web.guide_generation_runtime import singleflight


def load_reference():
    from scripts.guide_latency_reference_guard import verify_reference
    verify_reference()
    path = Path(__file__).parent / "data" / "surgical_guide_latency_reference.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "dad562e79d2036fb836c2656f487658bf3344675bd09f8bf08186b839f1f06ff"
    spec = importlib.util.spec_from_file_location("guide_latency_reference", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


reference = load_reference()


@pytest.mark.parametrize("angle", [0., .31, 1.17])
@pytest.mark.parametrize("spacing", [(0.2, .2, .2), (.37, .62, 1.1)])
def test_cylinder_dense_and_sparse_are_exact(angle, spacing):
    rng = np.random.default_rng(916)
    shape = (31, 35, 37)
    image = sitk.GetImageFromArray(np.zeros(shape, dtype=np.int16))
    image.SetOrigin((-15.1, 31.7, -72.4))
    c, s = np.cos(angle), np.sin(angle)
    image.SetDirection((c, -s, 0., s, c, 0., 0., 0., 1.))
    lower = np.array([2, 3, 1])
    origin = current._crop_origin_world(image, lower)
    direction = np.asarray(image.GetDirection()).reshape(3, 3)
    for _ in range(8):
        start = origin + direction @ (rng.uniform(1, 10, 3) * spacing)
        end = origin + direction @ (rng.uniform(15, 25, 3) * spacing)
        radius = float(rng.uniform(.4, 2.5))
        args = (image, lower, shape, spacing, start, end, radius)
        old, box = reference._cylinder_sdf_in_region(*args)
        new, new_box = current._cylinder_sdf_in_region(*args)
        assert box == new_box
        np.testing.assert_array_equal(old, new)
        active = rng.random(shape) < .08
        sparse, sparse_box = current._cylinder_sdf_in_region(*args, active_mask=active)
        assert box == sparse_box
        np.testing.assert_array_equal(old[active[box]], sparse[active[box]])
        np.testing.assert_array_equal(active[box] & (old <= 0), active[box] & (sparse <= 0))


def test_patch_matches_historical_tree_at_boundaries(monkeypatch):
    rng = np.random.default_rng(12)
    plate = rng.random((73, 61, 81)) < .35
    for radius in [0., 1., np.sqrt(2), 6., 17.23, 100.]:
        entries = np.array([[0, 0, 0], [20, 25, 30], [60.3, 39.5, 61.2], [-4, 60, 20]], dtype=np.float32)
        monkeypatch.setenv("BRACHYBOT_GUIDE_FAST_PATH", "0")
        old = current._entry_patch_mask(plate, entries, radius)
        monkeypatch.setenv("BRACHYBOT_GUIDE_FAST_PATH", "1")
        np.testing.assert_array_equal(old, current._entry_patch_mask(plate, entries, radius))


@pytest.mark.parametrize("return_signed_distance", [False, True])
def test_resample_destination_buffer_is_bit_exact(monkeypatch, return_signed_distance):
    rng = np.random.default_rng(772)
    mask = rng.random((15, 17, 19)) > .42
    spacing = (.73, 1.11, .89)
    monkeypatch.setenv("BRACHYBOT_GUIDE_RESAMPLE_WORKERS", "1")
    expected = reference._resample_mask_to_local_grid(
        mask, spacing, .2, return_signed_distance=return_signed_distance
    )
    actual = current._resample_mask_to_local_grid(
        mask, spacing, .2, return_signed_distance=return_signed_distance
    )
    assert expected[1] == actual[1]
    np.testing.assert_array_equal(expected[0], actual[0])
    if return_signed_distance:
        np.testing.assert_array_equal(expected[2], actual[2])


@pytest.mark.parametrize("resolution", [.2, .35, .4, .8])
def test_mesh_is_bit_exact(resolution):
    shape = (33, 35, 37)
    z, y, x = np.indices(shape)
    mask = ((x - 18)**2 + (y - 16)**2 + (z - 17)**2 < 13**2)
    mask &= ((x - 18)**2 + (y - 16)**2 > 3**2)
    image = sitk.GetImageFromArray(mask.astype(np.uint8))
    image.SetOrigin((-25., 37.5, 51.7))
    args = (mask, image, np.array([1, 2, 3]), (resolution,) * 3)
    old = reference._mesh_from_mask(*args)
    new = current._mesh_from_mask(*args)
    for a, b in zip(old, new):
        np.testing.assert_array_equal(a, b)


@pytest.mark.parametrize("seed", range(5))
def test_mesh_random_topology_and_offset_exact(seed):
    rng = np.random.default_rng(seed)
    mask = np.zeros((33, 31, 39), dtype=bool)
    mask[7:17, 11:21, 13:25] = rng.random((10, 10, 12)) > .5
    image = sitk.GetImageFromArray(mask.astype(np.uint8))
    args = (mask, image, np.array([2, 3, 4]), (.2, .2, .2))
    for a, b in zip(reference._mesh_from_mask(*args), current._mesh_from_mask(*args)):
        np.testing.assert_array_equal(a, b)


@pytest.mark.parametrize("seed", range(4))
def test_component_cropping_preserves_ties_and_metadata(seed):
    rng = np.random.default_rng(seed)
    mask = np.zeros((51, 61, 73), dtype=bool)
    mask[13:30, 25:40, 21:36] = rng.random((17, 15, 15)) > .7
    if seed == 0:
        mask[:] = False
    old, a = reference._retain_largest_printable_component(mask, 4)
    new, b = current._retain_largest_printable_component(mask, 4)
    np.testing.assert_array_equal(old, new)
    assert a == b


def test_skin_cache_is_scoped_bounded_and_invalidated():
    from web.guide_generation_runtime import cached_skin
    import web.guide_generation_runtime as runtime
    class Memory:
        pass
    memory, other = Memory(), Memory()
    calls = []
    def compute():
        calls.append(1)
        return np.zeros((2, 2, 2), bool), {"z_min": True}, np.ones((2, 2, 2), bool)
    a = cached_skin(memory, "ctA", compute)
    a[1]["z_min"] = False
    b = cached_skin(memory, "ctA", compute)
    assert a[0] is b[0] and b[1]["z_min"]
    assert len(calls) == 1 and not b[0].flags.writeable
    cached_skin(memory, "ctB", compute)
    cached_skin(other, "ctA", compute)
    assert len(calls) == 3 and len(runtime._skin_cache) <= 2


def test_resampled_cache_is_scoped_bounded_and_read_only(monkeypatch):
    from web.guide_generation_runtime import cached_resampled
    import web.guide_generation_runtime as runtime

    class Memory:
        pass

    monkeypatch.setenv("BRACHYBOT_GUIDE_RESAMPLE_CACHE_MAX_BYTES", "100000")
    monkeypatch.setenv("BRACHYBOT_GUIDE_RESAMPLE_CACHE_RESERVE_BYTES", "0")
    runtime._resample_cache.clear()
    runtime._resample_cache_bytes = 0
    memory, other = Memory(), Memory()
    calls = []

    def compute():
        calls.append(1)
        return (
            np.zeros((3, 4, 5), dtype=bool),
            (.2, .2, .2),
            np.ones((3, 4, 5), dtype=np.float32),
        )

    first = cached_resampled(memory, "grid-a", compute)
    second = cached_resampled(memory, "grid-a", compute)
    assert len(calls) == 1
    assert first[0] is second[0] and first[2] is second[2]
    assert not first[0].flags.writeable and not first[2].flags.writeable
    with pytest.raises(ValueError):
        first[0][0, 0, 0] = True

    cached_resampled(other, "grid-a", compute)
    assert len(calls) == 2 and len(runtime._resample_cache) <= 1
    cached_resampled(memory, "grid-a", compute)
    assert len(calls) == 3  # the other Session evicted the bounded entry


def test_sparse_cylinder_subtraction_matches_historical_mask(monkeypatch):
    rng = np.random.default_rng(221)
    shape = (58, 61, 67)
    image = sitk.GetImageFromArray(np.zeros(shape, dtype=np.int16))
    image.SetOrigin((-17.2, 28.4, -63.1))
    angle = .37
    image.SetDirection((np.cos(angle), -np.sin(angle), 0.,
                        np.sin(angle), np.cos(angle), 0., 0., 0., 1.))
    lower = np.array([2, 3, 1])
    spacing = (.2, .2, .2)
    origin = current._crop_origin_world(image, lower)
    direction = np.asarray(image.GetDirection()).reshape(3, 3)
    specs = []
    for start_index, end_index, radius in [
        ((8, 10, 12), (31, 38, 42), 1.2),
        ((20, 7, 45), (45, 48, 54), .9),
        ((5, 43, 18), (37, 24, 57), 1.7),
    ]:
        start = origin + direction @ (np.asarray(start_index) * spacing)
        end = origin + direction @ (np.asarray(end_index) * spacing)
        specs.append({"start": start, "end": end, "radius_mm": radius})

    baseline = rng.random(shape) < .23
    expected = baseline.copy()
    reference._subtract_cylinder_specs_from_mask(
        expected, image, lower, spacing, specs
    )
    actual = baseline.copy()
    monkeypatch.setenv("BRACHYBOT_GUIDE_FAST_PATH", "1")
    current._subtract_cylinder_specs_from_mask(
        actual, image, lower, spacing, specs
    )
    np.testing.assert_array_equal(expected, actual)


def test_bore_projection_and_cross_bore_guards_are_exact():
    rng = np.random.default_rng(97)
    vertices = rng.uniform(-12, 12, (30000, 3))
    specs = [{"id": str(i), "start": rng.uniform(-5, 0, 3),
              "end": rng.uniform(0, 5, 3), "radius_mm": 1.3} for i in range(8)]
    params = current.normalize_guide_parameters({})
    old, a = reference._project_bore_walls(vertices, [], specs, params)
    new, b = current._project_bore_walls(vertices, [], specs, params)
    np.testing.assert_array_equal(old, new)
    assert a == b


def test_patch_component_bridge_and_unseeded_island_exact():
    plate = np.zeros((28, 45, 61), dtype=bool)
    plate[12:15, 3:41, 5:57] = True
    patch = np.zeros_like(plate)
    patch[12:15, 5:10, 8:14] = True
    patch[12:15, 30:36, 43:49] = True
    patch[12:15, 17:19, 29:32] = True
    entries = np.array([[13, 7, 11], [13, 33, 46]], np.float32)
    old, a = reference._connect_plate_patch_components(plate, patch, entries, (.2,) * 3)
    new, b = current._connect_plate_patch_components(plate, patch, entries, (.2,) * 3)
    np.testing.assert_array_equal(old, new)
    assert a == b


@pytest.mark.parametrize("opening", [False, True])
def test_repair_halo_preserves_array_boundaries(opening):
    from scipy import ndimage
    rng = np.random.default_rng(8)
    operation = ndimage.binary_opening if opening else ndimage.binary_closing
    structure = np.ones((3, 3, 3), bool) if opening else ndimage.generate_binary_structure(3, 1)
    for mode in ("empty", "full", "interior", "boundary"):
        mask = np.zeros((41, 33, 35), bool)
        if mode == "full":
            mask[:] = True
        elif mode == "interior":
            mask[10:25, 13:28, 5:20] = rng.random((15, 15, 15)) > .3
        elif mode == "boundary":
            mask[:15, :15, -15:] = rng.random((15, 15, 15)) > .3
        np.testing.assert_array_equal(operation(mask, structure=structure, iterations=1),
                                      current._repair_morphology(mask, opening=opening))


def test_packed_edge_qa_is_exact():
    rng = np.random.default_rng(10)
    vertices = rng.normal(size=(300, 3))
    for count in [4, 100, 50000]:
        faces = rng.integers(0, len(vertices), (count, 3))
        assert reference.mesh_validation(vertices, faces) == current.mesh_validation(vertices, faces)
    for faces in [np.array([[-1, 0, 1]] * 4), np.array([[0, 1, 301]] * 4)]:
        assert reference.mesh_validation(vertices, faces) == current.mesh_validation(vertices, faces)


@pytest.mark.parametrize("iterations", [0, 1, 3, 20])
@pytest.mark.parametrize("lam,mu", [(.5, None), (.23, -.37)])
def test_smoothing_in_place_preserves_all_rounding(iterations, lam, mu):
    rng = np.random.default_rng(13)
    vertices = rng.normal(size=(503, 3)) * np.array([1e-5, 1., 1e5])
    faces = rng.integers(0, 500, (900, 3))
    args = (vertices, faces, iterations, lam, mu)
    np.testing.assert_array_equal(reference._smooth_mesh_vertices(*args), current._smooth_mesh_vertices(*args))


def test_singleflight_shares_only_overlapping_identical_memory_requests():
    memory = object()
    entered, release, joined = Event(), Event(), Event()
    calls = []
    def compute():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return {"mesh": [1, 2]}
    # Observe that the waiter entered Future.result before releasing the owner.
    import web.guide_generation_runtime as runtime
    original = runtime.Future.result
    def wait_result(self, *a, **kw):
        joined.set()
        return original(self, *a, **kw)
    from unittest.mock import patch
    with patch.object(runtime.Future, "result", wait_result), ThreadPoolExecutor(2) as pool:
        owner = pool.submit(singleflight, memory, "same", compute)
        assert entered.wait(5)
        waiter = pool.submit(singleflight, memory, "same", compute)
        assert joined.wait(5)
        release.set()
        a, b = owner.result(), waiter.result()
    assert len(calls) == 1
    assert a == b and a is not b and a["mesh"] is not b["mesh"]
    singleflight(memory, "same", compute)
    assert len(calls) == 2  # Explicit subsequent regeneration is not cached.
    assert singleflight(object(), "same", lambda: 7) == 7
    with pytest.raises(ValueError):
        singleflight(memory, "error", lambda: (_ for _ in ()).throw(ValueError("failed")))
    assert singleflight(memory, "error", lambda: 9) == 9


def test_singleflight_waiter_stop_does_not_cancel_owner():
    from utils.cancellation import cancellation_scope, OperationCancelled
    entered, release, cancel = Event(), Event(), Event()
    memory = object()
    def compute():
        entered.set()
        assert release.wait(5)
        return 3
    def waiter():
        with cancellation_scope(cancel.is_set):
            return singleflight(memory, "key", compute)
    with ThreadPoolExecutor(2) as pool:
        owner = pool.submit(singleflight, memory, "key", compute)
        assert entered.wait(5)
        waiting = pool.submit(waiter)
        cancel.set()
        try:
            with pytest.raises(OperationCancelled):
                waiting.result(timeout=2)
            assert not owner.done()
        finally:
            release.set()
        assert owner.result() == 3


def test_singleflight_different_key_and_memory_never_wait():
    entered, release = Event(), Event()
    memory = object()
    def compute():
        entered.set()
        assert release.wait(5)
        return 1
    with ThreadPoolExecutor(2) as pool:
        owner = pool.submit(singleflight, memory, "A", compute)
        assert entered.wait(5)
        try:
            assert pool.submit(singleflight, memory, "B", lambda: 2).result(timeout=2) == 2
            assert pool.submit(singleflight, object(), "A", lambda: 3).result(timeout=2) == 3
        finally:
            release.set()
        assert owner.result() == 1
