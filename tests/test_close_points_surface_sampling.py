import numpy as np
import SimpleITK as sitk

from plans import utilizations


def test_get_cone_promotes_legacy_two_sector_sampling_to_full_3d():
    directions = np.asarray(
        utilizations.get_cone(np.array([0.0, 1.0, 0.0]), 30, 3, 2),
        dtype=np.float64,
    )

    # Three radial rings and six azimuths produce 1 + 3*6 directions.
    assert directions.shape == (19, 3)
    assert np.any(directions[1:, 2] > 0.1)
    assert np.any(directions[1:, 2] < -0.1)
    assert np.any(directions[1:, 0] > 0.1)
    assert np.any(directions[1:, 0] < -0.1)
    np.testing.assert_allclose(np.linalg.norm(directions, axis=1), 1.0)


def _synthetic_target():
    shape = (31, 61, 71)
    zz, yy, xx = np.indices(shape)
    center = np.array([15.0, 30.0, 35.0])
    radii = np.array([11.0, 22.0, 26.0])
    mask = (
        ((zz - center[0]) / radii[0]) ** 2
        + ((yy - center[1]) / radii[1]) ** 2
        + ((xx - center[2]) / radii[2]) ** 2
        <= 1.0
    ).astype(np.uint8)
    image = sitk.GetImageFromArray(np.zeros(shape, dtype=np.int16))
    # SimpleITK spacing is x, y, z; the NumPy array is z, y, x.
    image.SetSpacing((0.7, 1.1, 2.0))
    return image, mask


def test_close_points_cover_surface_and_protect_backside(monkeypatch):
    image, target = _synthetic_target()

    def legacy_path_must_not_run(*args, **kwargs):
        raise AssertionError("legacy O(N^2) backlit sampler was called")

    monkeypatch.setattr(
        utilizations.geometry, "get_backlit_points", legacy_path_must_not_run
    )

    reference = np.array([0.60, 0.30, 1.00])
    close, length = utilizations.get_close_points(
        image,
        target,
        reference,
        1,
        1.5707963267948966,
        max_surface_points=256,
        surface_spacing_mm=2.5,
    )

    assert close.shape == (256, 3)
    assert np.isfinite(length) and length > 0.0
    assert np.all(target[tuple(close.astype(np.int64).T)] == 1)

    target_coords = np.argwhere(target == 1)
    target_world = utilizations.position_transform(
        image, target_coords.astype(np.float64)
    )
    close_world = utilizations.position_transform(
        image, close.astype(np.float64)
    )
    physical_reference = utilizations.direction_transform(image, reference).reshape(-1)
    physical_reference /= np.linalg.norm(physical_reference)
    center = target_world.mean(axis=0)
    target_projection = (target_world - center) @ physical_reference
    close_projection = (close_world - center) @ physical_reference

    # The far/back sector is deliberately protected, rather than being lost
    # to the direction/order-dependent representative selection.
    back_cut = np.quantile(target_projection, 0.30)
    assert np.count_nonzero(close_projection <= back_cut + 1e-9) >= 40

    nearest_mm = np.min(
        np.sum(
            (target_world[:, None, :] - close_world[None, :, :]) ** 2,
            axis=2,
        ),
        axis=1,
    ) ** 0.5
    assert np.percentile(nearest_mm, 95) < 12.0

    # Sampling is deterministic, which is important for reproducible plans
    # and for restoring a planning session.
    close_again, length_again = utilizations.get_close_points(
        image,
        target,
        reference,
        1,
        0.5,
        max_surface_points=256,
        surface_spacing_mm=2.5,
    )
    np.testing.assert_array_equal(close, close_again)
    np.testing.assert_allclose(length, length_again)


def test_close_points_use_physical_projection_length():
    image, target = _synthetic_target()
    reference = np.array([0.0, 0.0, 1.0])
    close, length = utilizations.get_close_points(
        image,
        target,
        reference,
        1,
        0.5,
        max_surface_points=64,
    )
    del close
    target_world = utilizations.position_transform(
        image, np.argwhere(target == 1).astype(np.float64)
    )
    physical_reference = utilizations.direction_transform(image, reference).reshape(-1)
    physical_reference /= np.linalg.norm(physical_reference)
    expected = np.ptp(target_world @ physical_reference)
    np.testing.assert_allclose(length, expected)


def test_close_points_empty_target_is_safe():
    image, target = _synthetic_target()
    target.fill(0)
    close, length = utilizations.get_close_points(
        image, target, np.array([0.0, 0.0, 1.0]), 1, 0.5
    )
    assert close.shape == (0, 3)
    assert length == 0.0


def test_shared_close_points_cover_surface_for_all_candidate_directions():
    image, target = _synthetic_target()
    directions = np.asarray([
        [0.60, 0.30, 1.00],
        [0.60, -0.30, 1.00],
        [-0.60, 0.30, 1.00],
        [-0.60, -0.30, 1.00],
    ], dtype=np.float64)

    close, lengths, stats = utilizations.get_shared_close_points_for_directions(
        image,
        target,
        directions,
        1,
        max_surface_points=128,
        surface_spacing_mm=2.5,
    )

    assert close.shape == (128, 3)
    assert len(lengths) == len(directions)
    assert all(np.isfinite(length) and length > 0.0 for length in lengths)
    assert stats["direction_count"] == len(directions)
    assert stats["selected_points"] == len(close)
    assert stats["protected_points"] >= len(directions)
    assert np.all(target[tuple(close.astype(np.int64).T)] == 1)

    target_coords = np.argwhere(target == 1)
    target_world = utilizations.position_transform(
        image, target_coords.astype(np.float64)
    )
    close_world = utilizations.position_transform(
        image, close.astype(np.float64)
    )
    nearest_mm = np.min(
        np.sum(
            (target_world[:, None, :] - close_world[None, :, :]) ** 2,
            axis=2,
        ),
        axis=1,
    ) ** 0.5
    # The shared set must cover the whole boundary, not only the reference
    # direction's back face.
    assert np.percentile(nearest_mm, 95) < 14.0

    close_again, lengths_again, stats_again = utilizations.get_shared_close_points_for_directions(
        image,
        target,
        directions,
        1,
        max_surface_points=128,
        surface_spacing_mm=2.5,
    )
    np.testing.assert_array_equal(close, close_again)
    np.testing.assert_allclose(lengths, lengths_again)
    assert stats == stats_again
