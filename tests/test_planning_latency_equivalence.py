"""Compare hot paths with frozen pre-optimization code, including boundaries."""
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import SimpleITK as sitk
from scipy.ndimage import distance_transform_edt
from plans import geometry, utilizations
from plans.dose_pre import inference
from tool_factory.seed_plan import planning_pipeline
from scripts.latency_dependency_guard import verify_dependencies


def reference(module, name):
    frozen = json.loads(Path(__file__).with_name('latency_reference.json').read_text())
    verify_dependencies(Path(__file__).resolve().parents[1], frozen)
    source = frozen['functions'][module.__name__.split('.')[-1]][name]
    namespace = dict(module.__dict__)
    exec(compile(source, '<reference:a7fbbba23>', 'exec'), namespace)
    return namespace[name]


def test_shared_baseline_dependencies_are_frozen():
    frozen = json.loads(Path(__file__).with_name('latency_reference.json').read_text())
    assert '_refine_target_boundary' in frozen['dependency_hashes']['utilizations']
    assert '_local_physical_coordinate_arrays' in frozen['dependency_hashes']['inference']
    assert 'is_point_inside_array' in frozen['dependency_hashes']['geometry']
    assert 'voxel_to_world' in frozen['dependency_hashes']['geometry']
    assert 'infer_truncated_boundary_faces_from_image' in frozen['dependency_hashes']['utilizations']
    verify_dependencies(Path(__file__).resolve().parents[1], frozen)


def test_replay_baseline_fixture_contains_every_replaced_function():
    expected = {
        'utilizations': {'_trace_target_exit', 'trajectory_entry_is_valid', 'get_available_position'},
        'geometry': {'get_trajectory_info'},
        'inference': {'generate_line_map'},
        'planning_pipeline': {'_filter_world_safe_trajectories'},
    }
    frozen = json.loads(Path(__file__).with_name('latency_reference.json').read_text())
    assert set(frozen['functions']) == set(expected)
    for module in [utilizations, geometry, inference, planning_pipeline]:
        for name in expected[module.__name__.split('.')[-1]]:
            assert callable(reference(module, name))


def test_ray_and_seed_search_match_original_on_boundaries_and_cavities():
    old_exit = reference(utilizations, '_trace_target_exit')
    old_entry = reference(utilizations, 'trajectory_entry_is_valid')
    old_positions = reference(utilizations, 'get_available_position')
    old_info = reference(geometry, 'get_trajectory_info')
    rng = np.random.default_rng(915)
    mask = np.zeros((41, 43, 45), dtype=bool)
    mask[3:-3, 3:-3, 3:-3] = True
    mask[20:, 16:22, 15:19] = False
    image = sitk.GetImageFromArray(mask.astype(np.uint8))
    image.SetOrigin((12.3, -45.6, -127.1))
    image.SetSpacing((0.8, 1.3, 2.0))
    image.SetDirection((0., -1., 0., 1., 0., 0., 0., 0., 1.))
    distance_map = distance_transform_edt(mask)
    radiation = mask.astype(np.int8)
    radiation[30:35, 20:25, 20:25] = 2
    points = [np.array([3., 3., 3.]), np.array([38., 40., 42.]), np.zeros(3)]
    points += [rng.uniform(np.zeros(3), mask.shape) for _ in range(500)]
    for i, point in enumerate(points):
        direction = np.eye(3)[i % 3].copy() if i < 3 else rng.normal(size=3)
        for sign in (-1, 1):
            old = old_exit(point, direction, mask, sign)
            new = utilizations._trace_target_exit(point, direction, mask, sign)
            if old is None: assert new is None
            else: np.testing.assert_array_equal(new, old)
        kwargs = dict(step_size=(.5, .3, 1.)[i % 3], truncated_boundary_faces=tuple(rng.integers(0,2,6).astype(bool)))
        assert old_entry(point, direction, mask, **kwargs) == utilizations.trajectory_entry_is_valid(point, direction, mask, **kwargs)
        assert old_info(point, radiation, direction, 1, 0, 2) == geometry.get_trajectory_info(point, radiation, direction, 1, 0, 2)
        for dtype in (np.float32, np.float64):
            p, d = point.astype(dtype), direction.astype(dtype)
            assert old_info(p, radiation, d, 1, 0, 2) == geometry.get_trajectory_info(p, radiation, d, 1, 0, 2)
        trajectory = [point, direction, [4, 6, 8], [2, 3], 23]
        seeds = [[rng.uniform(np.zeros(3), mask.shape), direction] for _ in range(i % 4)]
        args = (trajectory, seeds, {'length': 4.5, 'margin_rate': (.0,.5,1.)[i % 3]}, image, distance_map)
        assert old_positions(*args) == utilizations.get_available_position(*args)


def test_line_map_is_bit_exact_for_axis_oblique_and_anisotropic_images():
    old = reference(inference, 'generate_line_map')
    rng = np.random.default_rng(21)
    for i in range(12):
        size = (120, 120, 120) if i < 3 else (31, 42, 25)
        image = sitk.Image(size, sitk.sitkFloat32)
        image.SetOrigin((-123.456, .125, 57.13))
        if i % 2:
            image.SetSpacing((.9, 1.1, 1.7))
            t = .37
            image.SetDirection((np.cos(t), -np.sin(t), 0, np.sin(t), np.cos(t), 0, 0, 0, 1))
        index = np.asarray(size)/2 + rng.uniform(-.5,.5,3)
        position = image.TransformContinuousIndexToPhysicalPoint(tuple(index))
        direction = np.eye(3)[i].copy() if i < 3 else rng.normal(size=3)
        before = old(image, position, direction.copy())
        after = inference.generate_line_map(image, position, direction.copy())
        np.testing.assert_array_equal(sitk.GetArrayFromImage(after), sitk.GetArrayFromImage(before))
        assert after.GetSpacing() == before.GetSpacing()
        assert after.GetDirection() == before.GetDirection()
        assert after.GetOrigin() == before.GetOrigin()


def test_world_filter_computes_faces_once_and_still_validates_every_needle():
    faces = (True, False, True, False, False, False)
    trajectories = [object() for _ in range(5)]
    context = type('Safety', (), {})()
    with (patch.object(planning_pipeline, 'build_needle_safety_context', return_value=context),
          patch.object(planning_pipeline, '_candidate_world_needle_points', return_value=[[1,2,3], [4,5,6]]),
          patch.object(planning_pipeline, '_needle_enters_through_truncated_boundary', side_effect=[True, False, False, False, False]) as boundary,
          patch.object(context, 'segment_hits_obstacle', create=True, side_effect=[False, True, False, False]) as obstacle,
          patch.object(utilizations, 'infer_truncated_boundary_faces_from_image', return_value=faces) as infer):
        result = planning_pipeline._filter_world_safe_trajectories(trajectories, None, object(), None, None, set(), body_mask=object())
    infer.assert_called_once()
    assert boundary.call_count == 5
    assert obstacle.call_count == 4
    assert all(call.kwargs['truncated_boundary_faces'] == faces for call in boundary.call_args_list)
    assert result == [trajectories[1], trajectories[3], trajectories[4]]


def test_world_filter_missing_safety_context_still_rejects():
    with (patch.object(planning_pipeline, 'build_needle_safety_context', return_value=None),
          patch.object(planning_pipeline, '_candidate_world_needle_points', return_value=[[1,2,3],[4,5,6]]),
          patch.object(planning_pipeline, '_needle_enters_through_truncated_boundary', return_value=False)):
        assert planning_pipeline._filter_world_safe_trajectories([object()], None, object(), None, None, set(), body_mask=object(), truncated_boundary_faces=(False,)*6) == []
