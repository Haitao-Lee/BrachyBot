"""Real installed SimpleITK CPU registration on synthetic physical images."""
import numpy as np
import pytest
import SimpleITK as sitk

from utils.guide_registration_cpu import RegistrationLimits, image_pose, surface_pose, visible_guide_surface
from web.guide_placement import GuidePlacementError, RigidTransform


def phantom(size=40):
    z, y, x = np.indices((size,) * 3)
    array = np.full((size,) * 3, -1000., dtype=np.float32)
    body = ((x - size / 2) ** 2 / (size / 3) ** 2 + (y - size / 2) ** 2 / (size / 3.2) ** 2 + (z - size / 2) ** 2 / (size / 3.4) ** 2) < 1
    array[body] = 30. + x[body] * 2 + y[body]
    array += 700 * np.exp(-((x - 17) ** 2 / 10 + (y - 23) ** 2 / 18 + (z - 18) ** 2 / 6))
    array += 500 * np.exp(-((x - 24) ** 2 / 5 + (y - 17) ** 2 / 9 + (z - 25) ** 2 / 15))
    return sitk.GetImageFromArray(array)


def test_real_image_registration_has_correct_point_push_direction():
    source = phantom()
    translation = np.array([2., -1., 3.])
    target = sitk.Resample(source, source, sitk.TranslationTransform(3, (-translation).tolist()), sitk.sitkLinear, -1000.)
    result = image_pose(source, target, limits=RegistrationLimits(iterations=120))
    pose = RigidTransform.from_matrix(result['matrix'])
    points = np.array([[15., 20., 18.], [22., 14., 25.]])
    assert np.max(np.linalg.norm(pose.points(points) - (points + translation), axis=1)) < 1.5
    assert result['qc']['review_required']
    assert result['qc']['anatomy_to_guide_pose_is_estimate']
    assert not result['qc']['direct_guide_observation']


def test_equal_metadata_with_constant_or_different_content_is_not_alignment():
    blank = sitk.GetImageFromArray(np.zeros((24, 24, 24), np.float32))
    with pytest.raises(GuidePlacementError, match='variation'):
        image_pose(blank, blank, limits=RegistrationLimits())
    first, second = phantom(), phantom()
    second = sitk.Resample(second, second, sitk.TranslationTransform(3, (-2., 1., -3.)), sitk.sitkLinear, -1000.)
    assert first.GetOrigin() == second.GetOrigin()
    result = image_pose(first, second, limits=RegistrationLimits(iterations=120))
    assert not np.allclose(result['matrix'], np.eye(4), atol=.1)


def test_symmetric_surface_fit_remains_unacceptable():
    values = [-2., -1., 0., 1., 2.]
    points = np.array([[a, b, c] for a in values for b in values for c in values if 0 < a * a + b * b + c * c <= 4])
    result = surface_pose(points, points + [3., 4., 5.], limits=RegistrationLimits(), max_residual_mm=.2, ambiguity_margin_mm=.05)
    assert result['qc']['ambiguous']
    assert result['qc']['distinct_pose_count'] > 1


def test_selected_visible_material_reconstructs_physical_oblique_surface():
    array = np.full((32, 32, 32), -1000., np.float32)
    array[10:20, 12:18, 8:24] = 500.
    image = sitk.GetImageFromArray(array); image.SetSpacing((.7, 1.1, 1.4)); image.SetOrigin((11., 22., 33.))
    image.SetDirection((0., -1., 0., 1., 0., 0., 0., 0., 1.))
    points, evidence = visible_guide_surface(image, [2, 2, 2, 30, 30, 30], 200., RegistrationLimits())
    assert len(points) > 8 and evidence['component_count'] == 1
    assert points[:, 0].mean() == pytest.approx(11 - 14.5 * 1.1, abs=.2)
    assert evidence['reconstruction_is_estimate']
    with pytest.raises(GuidePlacementError, match='boundary'):
        visible_guide_surface(image, [8, 12, 10, 24, 18, 20], 200., RegistrationLimits())
