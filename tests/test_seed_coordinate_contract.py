import numpy as np
import pytest


def test_seed_plan_world_conversion_uses_image_geometry_for_positions_and_directions():
    sitk = pytest.importorskip("SimpleITK")
    from plans.core import seed_plan_to_world_coordinates

    image = sitk.Image([8, 9, 10], sitk.sitkFloat32)
    image.SetSpacing((2.0, 3.0, 4.0))
    image.SetOrigin((10.0, 20.0, 30.0))
    image.SetDirection((0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0))

    position_zyx = np.array([2.0, 3.0, 4.0])
    direction_zyx = np.array([1.0, 2.0, 3.0])
    dose_map = np.zeros((10, 9, 8), dtype=np.float32)
    plan = [[
        (np.array([2.0, 3.0, 4.0]), np.array([0.0, 1.0, 0.0]), [1], [], 1),
        [(position_zyx, direction_zyx)],
        [dose_map],
    ]]

    converted = seed_plan_to_world_coordinates(plan, image)
    position, direction = converted[0][1][0]

    expected_position = np.asarray(
        image.TransformContinuousIndexToPhysicalPoint((4.0, 3.0, 2.0)),
        dtype=np.float64,
    )
    expected_vector = np.asarray((-6.0, 6.0, 4.0), dtype=np.float64)
    expected_vector /= np.linalg.norm(expected_vector)

    np.testing.assert_allclose(position, expected_position)
    np.testing.assert_allclose(direction, expected_vector)
    np.testing.assert_allclose(converted[0][0][0], plan[0][0][0])
    assert converted[0][2][0] is dose_map


def test_seed_plan_world_conversion_supports_serialized_dict_records():
    sitk = pytest.importorskip("SimpleITK")
    from plans.core import seed_plan_to_world_coordinates

    image = sitk.Image([4, 4, 4], sitk.sitkFloat32)
    image.SetSpacing((1.5, 2.0, 2.5))
    image.SetOrigin((-10.0, 8.0, 20.0))

    serialized = [{
        "trajectory": ([1.0, 1.0, 1.0], [0.0, 0.0, 1.0]),
        "seeds": [{
            "position": [2.0, 1.0, 3.0],
            "direction": [1.0, 0.0, 0.0],
        }],
    }]

    converted = seed_plan_to_world_coordinates(serialized, image)
    seed = converted[0]["seeds"][0]
    np.testing.assert_allclose(seed["position"], [-5.5, 10.0, 25.0])
    np.testing.assert_allclose(seed["direction"], [0.0, 0.0, 1.0])


def test_optimal_plan_early_return_keeps_world_coordinate_contract(monkeypatch):
    sitk = pytest.importorskip("SimpleITK")
    torch = pytest.importorskip("torch")
    from plans import core

    image = sitk.Image([8, 8, 8], sitk.sitkFloat32)
    image.SetSpacing((2.0, 3.0, 4.0))
    image.SetOrigin((10.0, 20.0, 30.0))
    radiation_volume = np.ones((8, 8, 8), dtype=np.int32)
    dose_map = np.zeros_like(radiation_volume, dtype=np.float32)
    trajectory = (np.array([2.0, 3.0, 4.0]), np.array([1.0, 0.0, 0.0]))
    seed = (np.array([2.0, 3.0, 4.0]), np.array([0.0, 1.0, 0.0]))
    calls = iter([(trajectory, 0), (None, None)])

    monkeypatch.setattr(
        core.utilizations,
        "select_optimal_trajectory",
        lambda *args, **kwargs: next(calls),
    )
    monkeypatch.setattr(
        core.utilizations,
        "put_seeds",
        lambda *args, **kwargs: ([seed], 0.5, [dose_map]),
    )

    result = core.optimal_plan(
        [trajectory],
        radiation_volume,
        image,
        torch.nn.Linear(1, 1),
        {},
        0.8,
        10.0,
        0.8,
        1,
        0,
        3,
        (8, 8, 8),
        100.0,
        100.0,
        0.9,
        {"length": 4.5},
        2,
        -1000.0,
        3000.0,
        255.0,
        progressDialog=core._MockProgressDialog(),
    )

    assert len(result) == 1
    position, direction = result[0][1][0]
    np.testing.assert_allclose(position, [18.0, 29.0, 38.0])
    np.testing.assert_allclose(direction, [0.0, 1.0, 0.0])
