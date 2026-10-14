"""Independent physical fixtures for research implant reconstruction contracts."""

from dataclasses import FrozenInstanceError, replace
import json
import math
import time

import numpy as np
import pytest
import SimpleITK as sitk

from utils.implant_reconstruction import (
    ADDITIONAL_SEED_PRESENTATION, ImageGeometry, ImageReference, ObservationReview,
    OrientationProfile, PhysicalPCAOrientationProvider, ReconstructionCancelled,
    ReconstructionDeadlineExceeded, SeedAxisReconstruction, SeedDetection, SeedDimensions,
    axis_angle_deg, canonical_axis, fuse_unoriented_axes, reconstruct_original_grid_mask,
    review_observations,
)


def image_reference(image):
    return ImageReference("session-a", "intra-a", "ct-a", 1, "a" * 64, ImageGeometry.from_image(image))


def blank_image(size=(64, 64, 64), spacing=(0.5, 0.5, 0.5), origin=(0.0, 0.0, 0.0), direction=None):
    image = sitk.GetImageFromArray(np.full(size[::-1], -500, dtype=np.float32))
    image.SetSpacing(spacing)
    image.SetOrigin(origin)
    if direction is not None:
        image.SetDirection(tuple(float(x) for x in np.asarray(direction).flatten()))
    return image


def physical_rods(image, rods):
    """Rasterize prescribed physical capsules independently of the estimator."""
    array = sitk.GetArrayFromImage(image)
    z, y, x = np.indices(array.shape)
    xyz = np.stack((x, y, z), axis=-1)
    direction = np.asarray(image.GetDirection()).reshape(3, 3)
    points = np.asarray(image.GetOrigin()) + (xyz * image.GetSpacing()) @ direction.T
    for center, axis, length, radius in rods:
        unit = np.asarray(axis, dtype=float) / np.linalg.norm(axis)
        delta = points - np.asarray(center)
        projection = delta @ unit
        radial = np.linalg.norm(delta - np.clip(projection, -length / 2, length / 2)[..., None] * unit, axis=-1)
        array[radial <= radius] = 2500.0
    output = sitk.GetImageFromArray(array)
    output.CopyInformation(image)
    return output


def reconstruct(image, centers, *, profile=OrientationProfile(), labels=None, dimensions=None, coverage="unknown"):
    detections = tuple(center if isinstance(center, SeedDetection) else
                       SeedDetection(str(i), tuple(center)) for i, center in enumerate(centers))
    return PhysicalPCAOrientationProvider().estimate_seed_axes(
        image_reference(image), image, detections, labels, profile=profile,
        dimensions=dimensions, coverage_status=coverage)


@pytest.mark.parametrize("axis", [(1, 2, 3), (-1, -2, -3), (0, 0, 1)])
def test_antipodal_projector_fusion_preserves_axis(axis):
    expected = canonical_axis(axis)
    fused = fuse_unoriented_axes((axis, -np.asarray(axis)), (1, 4))
    assert axis_angle_deg(fused, expected) < 1e-5
    assert np.linalg.norm(fused) == pytest.approx(1)


def test_equal_orthogonal_evidence_is_unresolved():
    with pytest.raises(ValueError, match="ambiguous"):
        fuse_unoriented_axes(((1, 0, 0), (0, 1, 0)), (1, 1))


@pytest.mark.parametrize("axis", [(0, 0, 0), (1, float("nan"), 1), (1, 2)])
def test_invalid_axis_rejected(axis):
    with pytest.raises(ValueError):
        canonical_axis(axis)


@pytest.mark.parametrize("count", [1, 2])
def test_sparse_centers_do_not_invent_an_axis(count):
    points = [(10.0, 10.0, 10.0), (16.0, 13.0, 18.0)][:count]
    result = reconstruct(blank_image(), points)
    assert not result.deposition_lines
    assert all(s.axis_lps is None and s.axis_source == "unknown" for s in result.observations)
    assert [s.center_lps_mm for s in result.observations] == points


def test_three_oblique_centers_support_a_three_dimensional_prior_without_snapping():
    axis = np.asarray((1, 2, 3), dtype=float) / math.sqrt(14)
    centers = [np.asarray((12, 12, 12)) + t * axis for t in (-6, 0, 6)]
    result = reconstruct(blank_image(), centers)
    assert len(result.deposition_lines) == 1
    for observation, center in zip(result.observations, centers):
        assert observation.center_lps_mm == tuple(center)
        assert observation.axis_source == "estimated_from_deposition_line"
        assert axis_angle_deg(observation.axis_lps, axis) < 1e-5
        assert abs(observation.axis_lps[2]) > 0.5
        assert observation.review_status == "review_needed"
    assert result.deposition_lines[0].actual_needle is False
    assert result.deposition_lines[0].line_style == "dashed"


def test_migrated_center_remains_unassigned_and_unchanged():
    points = [(8, 10, 10), (14, 10, 10), (20, 10, 10), (16, 18, 17)]
    result = reconstruct(blank_image(), points)
    assert all(s.axis_lps is not None for s in result.observations[:3])
    assert result.observations[-1].axis_lps is None
    assert result.observations[-1].center_lps_mm == points[-1]


def test_separate_parallel_groups_are_not_global_mean_clustered():
    points = [(x, y, 12) for y in (10, 15) for x in (7, 13, 19, 25)]
    result = reconstruct(blank_image(), points)
    assert len(result.deposition_lines) == 2
    assert {line.detection_ids for line in result.deposition_lines} == {
        ("0", "1", "2", "3"), ("4", "5", "6", "7")}
    assert all(s.axis_lps is not None for s in result.observations)


def test_subresolution_parallel_groups_do_not_become_one_authoritative_line():
    points = [(x, y, 12) for y in (10, 10.6) for x in (7, 13, 19, 25)]
    result = reconstruct(blank_image(), points)
    assert "mixed_or_parallel_support_rejected" in result.diagnostics
    assert not result.deposition_lines
    assert all(s.axis_lps is None for s in result.observations)


def test_crossing_groups_preserve_competing_association_at_intersection():
    center = np.asarray((16, 16, 16))
    first = np.asarray((1, 0, 1)) / math.sqrt(2)
    second = np.asarray((0, 1, -1)) / math.sqrt(2)
    points = [center] + [center + t * first for t in (-12, -6, 6, 12)] + [
        center + t * second for t in (-12, -6, 6, 12)]
    result = reconstruct(blank_image(), points)
    crossing = result.observations[0]
    assert len(result.deposition_lines) >= 2
    assert len(crossing.candidate_line_ids) >= 2
    assert crossing.axis_lps is None
    assert "competing_deposition_lines" in crossing.diagnostics
    assert all(s.axis_lps is not None for s in result.observations[1:])


def test_local_pca_uses_real_sitk_rotated_anisotropic_geometry():
    theta, phi = math.radians(32), math.radians(27)
    rz = np.asarray(((math.cos(theta), -math.sin(theta), 0),
                     (math.sin(theta), math.cos(theta), 0), (0, 0, 1)))
    ry = np.asarray(((math.cos(phi), 0, math.sin(phi)), (0, 1, 0),
                     (-math.sin(phi), 0, math.cos(phi))))
    image = blank_image(spacing=(0.35, 0.6, 0.8), origin=(-32, 43, 11), direction=rz @ ry)
    center = image.TransformContinuousIndexToPhysicalPoint((30.3, 29.8, 31.2))
    axis = np.asarray((0.4, -0.2, 0.9))
    image = physical_rods(image, [(center, axis, 4.0, 0.65)])
    result = reconstruct(image, [center])
    observation = result.observations[0]
    assert observation.axis_source == "local_pca"
    assert axis_angle_deg(observation.axis_lps, axis) < 8
    assert observation.center_lps_mm == center
    assert observation.local_diagnostics.identifiable
    assert observation.local_diagnostics.resolution_angle_deg is not None


def test_thick_slice_local_axis_stays_unknown_without_independent_prior():
    image = blank_image(size=(64, 64, 8), spacing=(0.5, 0.5, 5))
    center = (16, 16, 15)
    image = physical_rods(image, [(center, (1, 0, 0), 4.0, 0.4)])
    observation = reconstruct(image, [center]).observations[0]
    assert observation.axis_lps is None
    assert "undersampled_original_grid" in observation.diagnostics


def test_isotropic_local_ball_has_no_identifiable_axis():
    image = physical_rods(blank_image(), [((16, 16, 16), (1, 0, 0), 0, 1.2)])
    observation = reconstruct(image, [(16, 16, 16)]).observations[0]
    assert observation.axis_lps is None
    assert "local_axis_not_identifiable" in observation.diagnostics


def test_rotated_seed_keeps_strong_local_axis_instead_of_deposition_axis():
    centers = [(x, 16, 16) for x in (5, 11, 17, 23, 29)]
    rods = [(center, (0, 0, 1) if i == 2 else (1, 0, 0), 3.6, 0.5)
            for i, center in enumerate(centers)]
    image = physical_rods(blank_image(), rods)
    result = reconstruct(image, centers)
    rotated = result.observations[2]
    assert axis_angle_deg(rotated.axis_lps, (0, 0, 1)) < 3
    assert rotated.axis_source == "local_pca"
    assert "rotated_seed_or_association_disagreement" in rotated.diagnostics
    assert rotated.local_line_disagreement_deg > 80


def test_two_centers_with_independent_capsule_axes_can_support_a_line():
    centers = [(10, 16, 16), (18, 16, 16)]
    image = physical_rods(blank_image(), [(center, (1, 0, 0), 4, 0.5) for center in centers])
    result = reconstruct(image, centers)
    assert len(result.deposition_lines) == 1
    assert result.deposition_lines[0].independently_supported_axes == 2
    assert "two_point_line_with_independent_local_support" in result.deposition_lines[0].flags


def test_split_component_gets_per_center_local_support_not_cloned_component_axis():
    centers = [(13, 16, 16), (17, 16, 17)]
    image = physical_rods(blank_image(), [(centers[0], (1, 0, 0), 3, 0.5),
                                         (centers[1], (0, 0, 1), 3, 0.5)])
    labels = sitk.Cast(image > 800, sitk.sitkUInt16)
    detections = [SeedDetection(str(i), center, (1,), association_status="associated")
                  for i, center in enumerate(centers)]
    result = reconstruct(image, detections, labels=labels)
    assert axis_angle_deg(result.observations[0].axis_lps, (1, 0, 0)) < 8
    assert axis_angle_deg(result.observations[1].axis_lps, (0, 0, 1)) < 8
    assert all("shared_component_partitioned" in s.diagnostics for s in result.observations)


def test_component_ambiguity_prevents_local_axis_acceptance():
    center = (16, 16, 16)
    image = physical_rods(blank_image(), [(center, (1, 0, 0), 4, 0.5)])
    labels = sitk.Cast(image > 800, sitk.sitkUInt16)
    detection = SeedDetection("ambiguous", center, (1, 2), association_status="ambiguous")
    observation = reconstruct(image, [detection], labels=labels).observations[0]
    assert observation.axis_lps is None
    assert "component_association_ambiguous" in observation.diagnostics


def test_partial_fov_and_outside_centers_cannot_get_a_prior_axis():
    centers = [(-2, 10, 10), (5, 10, 10), (12, 10, 10)]
    result = reconstruct(blank_image(), centers, coverage="partial")
    assert result.observations[0].axis_lps is None
    assert "center_outside_original_grid" in result.observations[0].diagnostics
    assert result.review_status == "review_needed"
    assert not result.deposition_lines


def test_original_grid_mask_roundtrip_preserves_rotated_geometry_and_component_ids():
    original = blank_image(size=(8, 9, 10), spacing=(0.8, 1.1, 1.4), origin=(-10, 20, 30),
                           direction=((0, 0, 1), (1, 0, 0), (0, 1, 0)))
    native = sitk.Image((12, 12, 12), sitk.sitkUInt16)
    native.SetSpacing((1, 1, 1))
    native.SetOrigin((-9.7, 20.2, 30.1))
    native.SetDirection(original.GetDirection())
    native[3, 4, 5] = 7
    native[5, 5, 7] = 12
    output = reconstruct_original_grid_mask(native, original)
    assert ImageGeometry.from_image(output) == ImageGeometry.from_image(original)
    expected = np.zeros(original.GetSize()[::-1], dtype=np.uint16)
    for z in range(original.GetSize()[2]):
        for y in range(original.GetSize()[1]):
            for x in range(original.GetSize()[0]):
                point = original.TransformIndexToPhysicalPoint((x, y, z))
                continuous = native.TransformPhysicalPointToContinuousIndex(point)
                nearest = tuple(int(math.floor(v + 0.5)) for v in continuous)
                if all(0 <= nearest[i] < native.GetSize()[i] for i in range(3)):
                    expected[z, y, x] = native[nearest]
    np.testing.assert_array_equal(sitk.GetArrayFromImage(output), expected)
    assert set(np.unique(expected)) == {0, 7, 12}


def test_original_grid_mask_returns_an_independent_copy_on_equal_grids():
    image = blank_image(size=(5, 5, 5))
    mask = sitk.Cast(image > 0, sitk.sitkUInt8)
    mask[2, 2, 2] = 1
    output = reconstruct_original_grid_mask(mask, image)
    output[2, 2, 2] = 0
    assert mask[2, 2, 2] == 1


def test_mask_resampling_does_not_invent_foreground_to_preserve_a_subvoxel_detection():
    native = sitk.Image((8, 8, 8), sitk.sitkUInt8)
    native[1, 1, 1] = 1
    original = blank_image(size=(4, 4, 4), spacing=(2, 2, 2))
    output = reconstruct_original_grid_mask(native, original)
    assert not np.any(sitk.GetArrayFromImage(output))


def test_noisy_oblique_lines_use_robust_physical_tls_and_reject_an_outlier():
    rng = np.random.default_rng(371)
    axis = np.asarray((1, 0.3, 0.7))
    axis /= np.linalg.norm(axis)
    origin = np.asarray((16, 16, 16))
    centers = [origin + t * axis + rng.normal(0, 0.04, 3) for t in (-12, -6, 0, 6, 12)]
    centers.append(origin + (0, 7, -7))
    result = reconstruct(blank_image(), centers)
    assert len(result.deposition_lines) == 1
    assert result.deposition_lines[0].rms_perpendicular_mm < 0.15
    assert axis_angle_deg(result.deposition_lines[0].axis_lps, axis) < 1
    assert result.observations[-1].axis_lps is None


def test_left_handed_image_grid_still_uses_physical_lps_axes():
    image = blank_image(origin=(30, 0, 0), direction=((-1, 0, 0), (0, 1, 0), (0, 0, 1)))
    center = image.TransformContinuousIndexToPhysicalPoint((30, 30, 30))
    axis = (-1, 1, 2)
    image = physical_rods(image, [(center, axis, 4, 0.6)])
    observation = reconstruct(image, [center]).observations[0]
    assert axis_angle_deg(observation.axis_lps, axis) < 7


def test_revision_is_typed_immutable_and_json_roundtrips():
    result = reconstruct(blank_image(), [(10, 10, 10), (16, 10, 10), (22, 10, 10)])
    restored = SeedAxisReconstruction.from_dict(json.loads(json.dumps(result.to_dict())))
    assert restored == result
    with pytest.raises(FrozenInstanceError):
        restored.observations[0].center_lps_mm = (0, 0, 0)
    assert isinstance(restored.observations, tuple)
    assert isinstance(restored.observations[0].center_lps_mm, tuple)
    assert restored.observations[0].physical_seed_id is None
    assert restored.observations[0].center_uncertainty_mm == 0.25
    assert result.to_dict()["review_status"] == "review_needed"


def test_acceptance_requires_explicit_review_coverage_and_dimensions():
    centers = [(10, 10, 10), (16, 10, 10), (22, 10, 10)]
    result = reconstruct(blank_image(), centers, dimensions=SeedDimensions("source-reviewed", 4.5, 0.8))
    assert not result.dose_input_ready
    accepted = review_observations(result, [ObservationReview(str(i), "accepted", "phantom review")
                                          for i in range(3)], reviewer_id="reader-1",
                                   coverage_status="complete", set_review_evidence="full phantom acquisition")
    assert accepted.review_status == "accepted"
    assert accepted.dose_input_ready
    assert accepted.revision == 2 and accepted.parent_revision_id == result.revision_id
    assert accepted.observation_set_id == result.observation_set_id
    assert result.revision == 1 and result.review_status == "review_needed"
    assert all(s.presentation.color == "#22D3EE" for s in accepted.observations)
    assert all(s.presentation.glyph == "capsule" and s.presentation.geometry_locked for s in accepted.observations)
    assert result.observations[0].presentation.color == "#C084FC"
    assert ADDITIONAL_SEED_PRESENTATION.color == "#FBBF24"


def test_center_correction_creates_new_revision_and_invalidates_group_evidence():
    result = reconstruct(blank_image(), [(10, 10, 10), (16, 10, 10), (22, 10, 10)])
    corrected = review_observations(result, [ObservationReview("1", "review_needed", "new center review",
                                                              corrected_center_lps_mm=(16, 13, 11))],
                                    reviewer_id="reader-2")
    assert corrected.observations[1].center_lps_mm == (16, 13, 11)
    assert result.observations[1].center_lps_mm == (16, 10, 10)
    assert not corrected.deposition_lines
    assert all(s.axis_lps is None and not s.candidate_line_ids for s in corrected.observations)
    assert corrected.observations[1].center_uncertainty_mm is None
    assert corrected.observations[1].component_association_status == "unassociated"


def test_serialized_acceptance_cannot_override_missing_evidence():
    result = reconstruct(blank_image(), [(10, 10, 10)])
    encoded = json.loads(json.dumps(result.to_dict()))
    encoded["review_status"] = "accepted"
    with pytest.raises(ValueError, match="immutable evidence"):
        SeedAxisReconstruction.from_dict(encoded)


def test_accepted_outside_fov_manual_geometry_does_not_pass_the_dose_gate():
    result = reconstruct(blank_image(), [(10, 10, 10)], dimensions=SeedDimensions("source", 4.5, 0.8))
    reviewed = review_observations(result, [ObservationReview("0", "accepted", "external landmark evidence",
                                                             corrected_center_lps_mm=(-10, 10, 10),
                                                             corrected_axis_lps=(1, 0, 0))],
                                   reviewer_id="reader", coverage_status="complete", set_review_evidence="review")
    assert reviewed.review_status == "accepted"
    assert not reviewed.dose_input_ready


def test_accepted_unknown_axis_is_position_review_not_dose_readiness():
    result = reconstruct(blank_image(), [(10, 10, 10)], dimensions=SeedDimensions("source", 4.5, 0.8))
    reviewed = review_observations(result, [ObservationReview("0", "accepted", "center confirmed")],
                                   reviewer_id="reader", coverage_status="complete", set_review_evidence="FOV review")
    assert reviewed.review_status == "accepted"
    assert not reviewed.dose_input_ready
    assert reviewed.observations[0].presentation.glyph == "point_halo"


def test_rejection_keeps_record_and_hides_it_by_role_without_mutating_detection():
    result = reconstruct(blank_image(), [(10, 10, 10)])
    reviewed = review_observations(result, [ObservationReview("0", "rejected", "bone fragment")],
                                   reviewer_id="reader")
    assert len(reviewed.observations) == 1
    assert not reviewed.observations[0].presentation.visible
    assert result.observations[0].presentation.visible


def test_rejecting_one_of_three_centers_invalidates_a_sparse_line_prior():
    result = reconstruct(blank_image(), [(10, 10, 10), (16, 10, 10), (22, 10, 10)])
    reviewed = review_observations(result, [ObservationReview("1", "rejected", "confirmed bone fragment")],
                                   reviewer_id="reader")
    assert not reviewed.deposition_lines
    assert all(s.axis_lps is None for s in reviewed.observations)
    assert reviewed.observations[1].review_status == "rejected"


@pytest.mark.parametrize("coverage", ["unknown", "partial", "complete"])
def test_zero_detections_always_start_in_review_state(coverage):
    result = reconstruct(blank_image(), [], coverage=coverage)
    assert result.review_status == "review_needed"
    assert "zero_detections_requires_coverage_review" in result.diagnostics
    assert not result.dose_input_ready


def test_empty_full_coverage_can_only_be_accepted_by_explicit_set_review():
    result = reconstruct(blank_image(), [])
    reviewed = review_observations(result, [], reviewer_id="reader", coverage_status="complete",
                                   set_review_evidence="phantom full coverage confirms zero seeds")
    assert reviewed.review_status == "accepted"


def test_resource_limits_are_visible_and_do_not_generate_default_axes():
    image = blank_image()
    profile = replace(OrientationProfile(), max_roi_voxels=10)
    result = reconstruct(image, [(16, 16, 16)], profile=profile)
    assert result.observations[0].axis_lps is None
    assert "local_roi_resource_limit" in result.observations[0].diagnostics
    with pytest.raises(ValueError, match="count"):
        reconstruct(image, [(16, 16, 16)] * 2, profile=replace(profile, max_detections=1))


def test_dense_shared_component_neighborhood_has_a_bounded_failure_state():
    center = (16, 16, 16)
    image = physical_rods(blank_image(), [(center, (1, 0, 0), 4, 0.5)])
    result = reconstruct(image, [center, (16, 16.2, 16), (16, 16.4, 16)],
                         profile=replace(OrientationProfile(), max_local_competitors=1))
    assert all(s.axis_lps is None for s in result.observations)
    assert all("local_competitor_resource_limit" in s.diagnostics for s in result.observations)


def test_axis_review_invalidates_independent_two_point_line_support():
    centers = [(10, 16, 16), (18, 16, 16)]
    image = physical_rods(blank_image(), [(center, (1, 0, 0), 4, 0.5) for center in centers])
    result = reconstruct(image, centers)
    reviewed = review_observations(result, [ObservationReview("0", "review_needed", "rotated capsule observed",
                                                             corrected_axis_lps=(0, 0, 1))], reviewer_id="reader")
    assert not reviewed.deposition_lines
    assert reviewed.observations[0].axis_source == "reviewed_axis"
    assert reviewed.observations[1].axis_lps is None


def test_line_hypothesis_budget_disallows_unsupported_prior_selection():
    points = [(x, y, 12) for y in (8, 16) for x in (7, 13, 19, 25)]
    result = reconstruct(blank_image(), points, profile=replace(OrientationProfile(), max_hypotheses=1))
    assert "line_hypothesis_budget_reached" in result.diagnostics
    assert all(s.axis_lps is None for s in result.observations)


def test_cancel_and_deadline_fail_before_reconstruction():
    image = blank_image()
    provider = PhysicalPCAOrientationProvider()
    with pytest.raises(ReconstructionCancelled):
        provider.estimate_seed_axes(image_reference(image), image, [], cancelled=lambda: True)
    with pytest.raises(ReconstructionDeadlineExceeded):
        provider.estimate_seed_axes(image_reference(image), image, [], deadline=time.monotonic() - 1)


def test_geometry_mismatch_and_invalid_profiles_fail_closed():
    image = blank_image()
    reference = image_reference(image)
    shifted = sitk.Image(image)
    shifted.SetOrigin((1, 0, 0))
    with pytest.raises(ValueError, match="reference"):
        PhysicalPCAOrientationProvider().estimate_seed_axes(reference, shifted, [])
    with pytest.raises(ValueError):
        OrientationProfile(line_inlier_mm=float("nan"))
    with pytest.raises(ValueError):
        ImageGeometry((5, 5, 5), (1, 1, 1), (0, 0, 0), (1, 0, 0, 0, 2, 0, 0, 0, 1))


def test_unknown_review_identity_and_missing_evidence_fail_closed():
    result = reconstruct(blank_image(), [(10, 10, 10)])
    with pytest.raises(ValueError, match="existing"):
        review_observations(result, [ObservationReview("not-here", "accepted", "review")], reviewer_id="reader")
    with pytest.raises(ValueError):
        ObservationReview("0", "accepted", "")
