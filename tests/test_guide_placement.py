"""Rigid pose, current-image corridor, and immutable obstacle controls."""

from copy import deepcopy

import numpy as np
import pytest
import SimpleITK as sitk

from test_guide_bore_manifest import tube_guide
from web.guide_placement import (
    BoreValidationProfile, CurrentCTGeometry, GuidePlacementError, RigidTransform,
    create_guide_placement, estimate_landmark_placement, estimate_surface_placement,
    fit_rigid_landmarks, image_geometry_identity, initialize_bore_trajectories,
    placed_guide_geometry, review_guide_placement, validate_bore_corridor,
    validate_continuation_trajectory, validate_fixed_obstacles,
)


PROFILE = BoreValidationProfile("synthetic_only_v1", .5, 2., .1, 30.)


def current_context(oar=False, rotate=False):
    image = sitk.Image([40, 17, 17], sitk.sitkInt16)
    image.SetOrigin((-5, -8, -8))
    image.SetSpacing((1, 1, 1))
    if rotate:
        image.SetDirection((0, -1, 0, 1, 0, 0, 0, 0, 1))
    body = np.zeros((17, 17, 40), dtype=bool)
    body[2:-2, 2:-2, 10:38] = True
    ctv = np.zeros_like(body)
    ctv[6:11, 6:11, 20:24] = True
    obstacles = np.zeros_like(body)
    if oar:
        obstacles[8, 8, 17] = True
    identity = image_geometry_identity(image, image_id="intra_ct", image_revision="1")
    return CurrentCTGeometry(image, identity=identity, body_mask=body, ctv_mask=ctv, oar_mask=obstacles)


def accepted_placement(guide, context, matrix=None):
    placement = create_guide_placement(guide, np.eye(4) if matrix is None else matrix,
                                       manufactured_guide_id="printed_fixture", target_image=context.identity,
                                       evidence={"source": "synthetic_direct_pose"})
    return review_guide_placement(placement, reviewer="synthetic_reviewer", decision="accepted",
                                  profile_id="synthetic_review_v1", evidence_reviewed=True,
                                  manufacturing_confirmed=True)


def test_known_rigid_pose_and_point_direction_distinction():
    matrix = np.eye(4)
    matrix[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
    matrix[:3, 3] = [10, 20, -3]
    transform = RigidTransform.from_matrix(matrix)
    assert transform.points([1, 0, 0]) == pytest.approx([10, 21, -3])
    assert transform.directions([1, 0, 0]) == pytest.approx([0, 1, 0])
    source = [[0, 0, 0], [5, 0, 0], [0, 4, 0], [0, 0, 3]]
    fit = fit_rigid_landmarks(source, transform.points(source), max_residual_mm=.01)
    assert np.allclose(fit["matrix"], matrix)
    assert fit["qc"]["landmark_rank"] == 3


@pytest.mark.parametrize("kind", ["scale", "reflection", "shear", "homogeneous", "nan"])
def test_improper_guide_transforms_are_rejected(kind):
    matrix = np.eye(4)
    if kind == "scale": matrix[0, 0] = 1.1
    elif kind == "reflection": matrix[0, 0] = -1
    elif kind == "shear": matrix[0, 1] = .1
    elif kind == "homogeneous": matrix[3, 0] = .1
    else: matrix[0, 0] = np.nan
    with pytest.raises(GuidePlacementError):
        RigidTransform.from_matrix(matrix)
    if kind in {"scale", "reflection", "shear", "nan"}:
        with pytest.raises(GuidePlacementError):
            RigidTransform(matrix[:3, :3], matrix[:3, 3])


def test_landmarks_reject_degeneracy_reflection_scale_and_residual():
    with pytest.raises(GuidePlacementError, match="degenerate"):
        fit_rigid_landmarks([[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 0, 0], [1, 0, 0], [2, 0, 0]], max_residual_mm=1)
    source = np.array([[0, 0, 0], [5, 0, 0], [0, 4, 0], [0, 0, 3.]])
    with pytest.raises(GuidePlacementError, match="reflection"):
        fit_rigid_landmarks(source, source * [-1, 1, 1], max_residual_mm=100)
    with pytest.raises(GuidePlacementError, match="scale"):
        fit_rigid_landmarks(source, source * 1.1, max_residual_mm=100)
    perturbed = source.copy()
    perturbed[-1] += [1, 1, 0]
    with pytest.raises(GuidePlacementError, match="residual"):
        fit_rigid_landmarks(source, perturbed, max_residual_mm=.01)


def test_landmark_pose_needs_review_and_preserves_manufactured_mesh():
    guide, context = tube_guide(), current_context()
    source = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    placement = estimate_landmark_placement(guide, source, source, max_residual_mm=.01,
                                            manufactured_guide_id="printed_fixture", target_image=context.identity)
    assert placement["review_state"] == "pending"
    assert placement["qc"]["reflection_observability"] == "coplanar_limited"
    with pytest.raises(GuidePlacementError, match="accepted"):
        placed_guide_geometry(guide, placement, target_image=context.identity)
    vertices = guide["vertices"].copy()
    accepted = accepted_placement(guide, context)
    first = placed_guide_geometry(guide, accepted, target_image=context.identity)
    second = placed_guide_geometry(guide, accepted, target_image=context.identity)
    assert np.array_equal(first["vertices_lps_mm"], second["vertices_lps_mm"])
    assert np.array_equal(vertices, guide["vertices"])
    assert first["original_mesh_sha256"] == guide["bore_manifest"]["mesh_sha256"]
    changed = deepcopy(accepted)
    changed["matrix"][0][3] = .1
    with pytest.raises(GuidePlacementError, match="accepted"):
        placed_guide_geometry(guide, changed, target_image=context.identity)
    with pytest.raises(GuidePlacementError, match="different image"):
        placed_guide_geometry(guide, accepted, target_image={**context.identity, "image_revision": "2"})


def test_symmetric_surface_and_missing_review_evidence_fail_closed():
    guide, context = tube_guide(), current_context()
    source = np.array([[x, y, z] for x in (-1., 1.) for y in (-1., 1.) for z in (-1., 1.)])
    alternate = np.eye(4)
    alternate[:3, :3] = np.diag([-1, -1, 1])
    candidate = estimate_surface_placement(guide, source, source, initial_matrices=[np.eye(4), alternate],
                                            max_residual_mm=.01, ambiguity_margin_mm=.01,
                                            manufactured_guide_id="printed_fixture", target_image=context.identity)
    assert candidate["qc"]["ambiguous"]
    with pytest.raises(GuidePlacementError, match="Ambiguous"):
        review_guide_placement(candidate, reviewer="r", decision="accepted", profile_id="p",
                              evidence_reviewed=True, manufacturing_confirmed=True)
    manual = create_guide_placement(guide, np.eye(4), manufactured_guide_id="printed_fixture",
                                    target_image=context.identity, evidence={"source": "manual"})
    with pytest.raises(GuidePlacementError, match="reviewed"):
        review_guide_placement(manual, reviewer="r", decision="accepted", profile_id="p",
                              evidence_reviewed=False, manufacturing_confirmed=True)


def test_current_ctv_initializer_and_shared_refinement_gate():
    guide, context = tube_guide(), current_context()
    placement = accepted_placement(guide, context)
    result = initialize_bore_trajectories(guide, placement, context, profile=PROFILE, fixed_seeds=[], in_situ_needles=[])
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["skin_entry_lps_mm"] == pytest.approx([4.5, 0, 0])
    assert candidate["tip_lps_mm"][0] == pytest.approx(18.5 - .0001)
    assert candidate["target_image"] == context.identity
    bore = placed_guide_geometry(guide, placement, target_image=context.identity)["bores"][0]
    assert validate_continuation_trajectory(candidate, bore, context, profile=PROFILE,
                                            fixed_seeds=[], in_situ_needles=[])["valid"]
    moved = deepcopy(candidate)
    moved["tip_lps_mm"][1] += 1
    check = validate_continuation_trajectory(moved, bore, context, profile=PROFILE, fixed_seeds=[], in_situ_needles=[])
    assert not check["valid"]
    assert "lateral_translation_not_validated" in check["reasons"]
    translated_outer = np.array(candidate["outer_lps_mm"]) + [0, .2, 0]
    translated_tip = np.array(candidate["tip_lps_mm"]) + [0, .2, 0]
    assert not validate_bore_corridor(bore, translated_outer, translated_tip, PROFILE)["valid"]
    changed_axis = deepcopy(candidate)
    changed_axis["axis_lps"] = [0, 1, 0]
    check = validate_continuation_trajectory(changed_axis, bore, context, profile=PROFILE,
                                              fixed_seeds=[], in_situ_needles=[])
    assert "candidate_axis_differs_from_manufactured_bore" in check["reasons"]


def test_changed_anatomy_obstacles_and_occupied_bore_reject_candidates():
    guide, context = tube_guide(), current_context(oar=True)
    placement = accepted_placement(guide, context)
    result = initialize_bore_trajectories(guide, placement, context, profile=PROFILE, fixed_seeds=[], in_situ_needles=[])
    assert not result["candidates"]
    assert "current_oar_corridor_blocked" in result["rejected"][0]["reasons"]
    context = current_context()
    seed = {"id": "implanted", "center_lps_mm": [12, 1, 0], "axis_lps": [0, 1, 0], "length_mm": 4., "radius_mm": .4}
    result = initialize_bore_trajectories(guide, placement, context, profile=PROFILE, fixed_seeds=[seed], in_situ_needles=[])
    assert "intersects_fixed_seed" in result["rejected"][0]["reasons"]
    needle = {"id": "observed", "points_lps_mm": [[9, -2, 0], [10, 0, 0], [11, 2, 0]], "radius_mm": .5}
    result = initialize_bore_trajectories(guide, placement, context, profile=PROFILE, fixed_seeds=[], in_situ_needles=[needle])
    assert "intersects_in_situ_needle" in result["rejected"][0]["reasons"]
    bore_id = guide["bore_manifest"]["bores"][0]["bore_id"]
    result = initialize_bore_trajectories(guide, placement, context, profile=PROFILE, fixed_seeds=[],
                                         in_situ_needles=[], channel_states={bore_id: "consumed_without_reuse_review"})
    assert not result["candidates"]
    assert "channel_consumed_without_reuse_review" in result["rejected"][0]["reasons"]


def test_unknown_seed_axis_is_conservative_and_missing_obstacles_are_not_empty():
    unknown = {"id": "unknown_axis", "center_lps_mm": [2, 2, 0], "length_mm": 4., "radius_mm": .4}
    check = validate_fixed_obstacles([0, 0, 0], [4, 0, 0], profile=PROFILE, fixed_seeds=[unknown], in_situ_needles=[])
    assert not check["valid"]
    with pytest.raises(GuidePlacementError, match="explicitly supplied"):
        validate_fixed_obstacles([0, 0, 0], [4, 0, 0], profile=PROFILE, fixed_seeds=None, in_situ_needles=[])


def test_ct_geometry_identity_and_rotated_anisotropic_ray_cells():
    image = sitk.Image([10, 11, 12], sitk.sitkInt16)
    image.SetSpacing((.5, 1, 2))
    image.SetDirection((0, -1, 0, 1, 0, 0, 0, 0, 1))
    image.SetOrigin((3, 4, 5))
    masks = np.zeros((12, 11, 10), dtype=bool)
    masks[2:10, 2:9, 2:8] = True
    identity = image_geometry_identity(image, image_id="rotated", image_revision="1")
    context = CurrentCTGeometry(image, identity=identity, body_mask=masks, ctv_mask=masks, oar_mask=np.zeros_like(masks))
    start = np.array(image.TransformContinuousIndexToPhysicalPoint((-1., 5., 6.)))
    cells = context.ray_cells(start, [0, 1, 0])
    assert [index for _, _, index in cells] == [(6, 5, i) for i in range(10)]
    assert all(b - a == pytest.approx(.5) for a, b, _ in cells)
    image.SetOrigin((3.1, 4, 5))
    with pytest.raises(GuidePlacementError, match="grid differs"):
        CurrentCTGeometry(image, identity=identity, body_mask=masks, ctv_mask=masks, oar_mask=np.zeros_like(masks))


def test_missing_skin_target_and_short_or_tight_bore_fail_closed():
    guide, context = tube_guide(), current_context()
    placement = accepted_placement(guide, context)
    bore = placed_guide_geometry(guide, placement, target_image=context.identity)["bores"][0]
    assert not validate_bore_corridor(bore, [0, 0, 0], [10, 0, 0],
                                      BoreValidationProfile("too_short", .5, 4., .1, 30.))["valid"]
    assert not validate_bore_corridor(bore, [0, 0, 0], [10, 0, 0],
                                      BoreValidationProfile("too_tight", 1.3, 2., .1, 30.))["valid"]
    body = context.body.copy()
    body[:, :, :10] = True
    context = CurrentCTGeometry(context.image, identity=context.identity, body_mask=body,
                                ctv_mask=context.ctv, oar_mask=context.oar)
    result = initialize_bore_trajectories(guide, placement, context, profile=PROFILE, fixed_seeds=[], in_situ_needles=[])
    assert "skin_entry_unobserved_or_truncated" in result["rejected"][0]["reasons"]


def test_anatomy_profile_and_fixed_observation_revision_fences():
    guide, context = tube_guide(), current_context()
    placement = accepted_placement(guide, context)
    result = initialize_bore_trajectories(guide, placement, context, profile=PROFILE, fixed_seeds=[], in_situ_needles=[])
    candidate = result["candidates"][0]
    bore = placed_guide_geometry(guide, placement, target_image=context.identity)["bores"][0]
    changed_ctv = np.zeros_like(context.ctv)
    changed_ctv[3:5, 3:5, 20:24] = True
    changed = CurrentCTGeometry(context.image, identity=context.identity, body_mask=context.body,
                                ctv_mask=changed_ctv, oar_mask=context.oar)
    check = validate_continuation_trajectory(candidate, bore, changed, profile=PROFILE, fixed_seeds=[], in_situ_needles=[])
    assert "stale_current_anatomy" in check["reasons"]
    assert "tip_not_in_current_ctv" in check["reasons"]
    result = initialize_bore_trajectories(guide, placement, changed, profile=PROFILE, fixed_seeds=[], in_situ_needles=[])
    assert result["rejected"][0]["reasons"] == ["no_reachable_current_ctv"]
    profile = BoreValidationProfile(PROFILE.profile_id, .6, 2., .1, 30.)
    check = validate_continuation_trajectory(candidate, bore, context, profile=profile, fixed_seeds=[], in_situ_needles=[])
    assert "stale_validation_profile_parameters" in check["reasons"]
    seed = {"id": "away", "center_lps_mm": [1, 6, 0], "length_mm": 4., "radius_mm": .4}
    check = validate_continuation_trajectory(candidate, bore, context, profile=PROFILE, fixed_seeds=[seed], in_situ_needles=[])
    assert "stale_fixed_observations" in check["reasons"]
    with pytest.raises(ValueError, match="read-only"):
        context.ctv[0, 0, 0] = True
