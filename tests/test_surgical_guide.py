"""Geometry regressions for the native patient-specific puncture guide."""

from __future__ import annotations

import numpy as np
import pytest
import SimpleITK as sitk

from tool_factory.surgical_guide import SurgicalGuideTool
from web.surgical_guide import (
    BORE_WALL_POLICY,
    GUIDE_MINIMUM_WALL_MM,
    NeedleGuidePath,
    _auxiliary_hole_specs,
    _auxiliary_hole_support,
    _connect_plate_patch_components,
    _cylinder_sdf_in_region,
    _primary_bore_cutter_specs,
    _project_bore_walls,
    _needle_spacing_quality,
    _retain_largest_printable_component,
    _sample_mask_at_world_points,
    _subtract_cylinder_specs_from_mask,
    generate_surgical_guide,
    guide_bore_quality_ready,
    _filter_components,
    _remove_truncated_cap_backed_voxels,
    _resample_mask_to_local_grid,
    _segment_distance_mm,
    guide_state_for_version,
    guide_version_summaries,
    invalidate_surgical_guides,
    mesh_to_ascii_stl,
    normalize_guide_parameters,
    save_guide_version,
    validate_exported_stl,
)


class _Memory:
    def __init__(self, values):
        self.values = dict(values)

    def retrieve(self, key):
        return self.values.get(key)

    def store(self, key, value):
        self.values[key] = value


class _Agent:
    def __init__(self, values):
        self.memory = _Memory(values)


def _synthetic_agent():
    shape = (64, 64, 64)
    zz, yy, xx = np.indices(shape)
    body = (xx - 32) ** 2 + (yy - 32) ** 2 + (zz - 32) ** 2 <= 22 ** 2
    ct = np.where(body, 40, -1000).astype(np.int16)
    image = sitk.GetImageFromArray(ct)
    image.SetSpacing((1.0, 1.0, 1.0))
    return _Agent({
        "ct_image": image,
        "ct_data": ct,
        "algorithm_plan_snapshot": {
            "needles": [{
                "id": "needle_0",
                "trajectory_id": "traj_1",
                "points": [[32.0, 32.0, 32.0], [-10.0, 32.0, 32.0]],
            }],
            "seeds": [{
                "id": "seed_0",
                "trajectory_id": "traj_1",
                "position": [28.0, 32.0, 32.0],
            }],
        },
    })


def test_auxiliary_hole_support_rejects_a_cylinder_that_ends_inside_the_plate():
    """A partial Boolean cut must never be reported as a realized hole."""
    image = sitk.GetImageFromArray(np.zeros((16, 16, 16), dtype=np.int16))
    image.SetSpacing((1.0, 1.0, 1.0))
    # A four-millimetre-thick flat guide slab in physical X.
    solid = np.zeros((16, 16, 16), dtype=bool)
    solid[:, :, 5:9] = True
    lower_xyz = np.array([0, 0, 0], dtype=np.int64)
    start = np.array([0.0, 8.0, 8.0])

    supported, reason = _auxiliary_hole_support(
        solid,
        image,
        lower_xyz,
        (1.0, 1.0, 1.0),
        start,
        np.array([6.0, 8.0, 8.0]),
        radius=1.3,
        plate_thickness_mm=3.0,
    )
    assert supported is False
    assert reason == "not_through_plate"

    supported, reason = _auxiliary_hole_support(
        solid,
        image,
        lower_xyz,
        (1.0, 1.0, 1.0),
        start,
        np.array([14.0, 8.0, 8.0]),
        radius=1.3,
        plate_thickness_mm=3.0,
    )
    assert supported is True
    assert reason == "ready"


def test_sparse_guide_sampling_does_not_copy_the_complete_binary_grid(monkeypatch):
    """Auxiliary-bore QA must pass the original CSG grid to SciPy unchanged."""
    from scipy import ndimage

    image = sitk.GetImageFromArray(np.ones((12, 13, 14), dtype=np.uint8))
    image.SetSpacing((0.5, 0.75, 1.25))
    solid = np.ones((12, 13, 14), dtype=bool)
    captured = {}

    def fake_map_coordinates(source, coordinates, **kwargs):
        captured["same_object"] = source is solid
        captured["order"] = kwargs.get("order")
        captured["coordinates"] = np.asarray(coordinates)
        return np.ones(captured["coordinates"].shape[1], dtype=bool)

    monkeypatch.setattr(ndimage, "map_coordinates", fake_map_coordinates)
    sampled = _sample_mask_at_world_points(
        solid,
        image,
        np.zeros(3, dtype=np.int64),
        image.GetSpacing(),
        np.array([[1.0, 1.5, 2.5], [2.0, 3.0, 5.0]]),
    )

    assert captured["same_object"] is True
    assert captured["order"] == 0
    assert captured["coordinates"].shape == (3, 2)
    assert sampled.tolist() == [True, True]


def test_filter_components_removes_diagonal_spurs_before_meshing():
    mask = np.zeros((12, 12, 12), dtype=bool)
    mask[2:7, 2:7, 2:7] = True
    # These voxels form a tiny component that touches the main solid only by
    # edges/corners.  Keeping it can make the marching-cubes surface non-manifold.
    mask[7, 7, 7] = True
    mask[7, 6, 7] = True
    mask[6, 7, 7] = True

    filtered = _filter_components(mask, minimum_voxels=24)

    assert filtered[2:7, 2:7, 2:7].all()
    assert not filtered[7, 7, 7]
    assert not filtered[7, 6, 7]
    assert not filtered[6, 7, 7]


def test_filter_components_drops_large_post_bore_material_islands():
    """A sizeable CSG island must not turn one guide into two printable parts."""
    mask = np.zeros((24, 24, 24), dtype=bool)
    mask[2:18, 2:18, 2:18] = True
    # This island is deliberately larger than the historical speck threshold.
    # Size-only filtering therefore reproduces the old false failure.
    mask[19:23, 4:10, 4:10] = True

    filtered, qa = _retain_largest_printable_component(mask, minimum_voxels=24)

    assert filtered[2:18, 2:18, 2:18].all()
    assert not filtered[19:23, 4:10, 4:10].any()
    assert qa["input_component_count"] == 2
    assert qa["retained_component_count"] == 1
    assert qa["dropped_component_count"] == 1
    assert qa["dropped_voxel_count"] == 144


def test_dense_primary_channels_are_audited_without_rejecting_fused_sleeves():
    """Close channels are reported for review, not silently removed."""
    direction = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    paths = [
        NeedleGuidePath(
            needle_id="needle_a",
            trajectory_id="traj_a",
            target=np.array([20.0, 20.0, 20.0]),
            external=np.array([-10.0, 20.0, 20.0]),
            entry=np.array([10.0, 20.0, 20.0]),
            inward_direction=direction,
            seed_count=1,
        ),
        NeedleGuidePath(
            needle_id="needle_b",
            trajectory_id="traj_b",
            target=np.array([20.0, 22.0, 20.0]),
            external=np.array([-10.0, 22.0, 20.0]),
            entry=np.array([10.0, 22.0, 20.0]),
            inward_direction=direction,
            seed_count=1,
        ),
    ]

    quality = _needle_spacing_quality(
        paths,
        normalize_guide_parameters({"auxiliary_holes_enabled": False}),
    )

    assert quality["status"] == "warning"
    assert quality["path_count"] == 2
    assert quality["bore_wall_conflict_pair_count"] == 1
    assert quality["requires_operator_review"] is True
    assert {quality["closest_pairs"][0][key] for key in ("needle_a", "needle_b")} == {
        "needle_a",
        "needle_b",
    }


def test_distant_plate_patches_are_joined_on_the_skin_shell():
    """Separate needle groups must export as one flush printable plate."""
    from scipy import ndimage

    plate = np.zeros((20, 48, 112), dtype=bool)
    plate[8:12, 4:44, 4:108] = True
    zz, yy, xx = np.indices(plate.shape)
    first = (zz - 10) ** 2 + (yy - 24) ** 2 + (xx - 20) ** 2 <= 12 ** 2
    second = (zz - 10) ** 2 + (yy - 24) ** 2 + (xx - 92) ** 2 <= 12 ** 2
    patches = plate & (first | second)
    _labels, before = ndimage.label(
        patches, structure=ndimage.generate_binary_structure(3, 1),
    )
    assert before == 2

    connected, qa = _connect_plate_patch_components(
        plate,
        patches,
        np.asarray([[10.0, 24.0, 20.0], [10.0, 24.0, 92.0]]),
        (1.0, 1.0, 1.0),
    )

    _labels, after = ndimage.label(
        connected, structure=ndimage.generate_binary_structure(3, 1),
    )
    assert after == 1
    assert not np.any(connected & ~plate)
    assert qa["initial_component_count"] == 2
    assert qa["final_component_count"] == 1
    assert qa["bridge_count"] == 1
    assert qa["single_piece"] is True


def test_skin_resampling_interpolates_thick_slice_contours_in_physical_space():
    """Intermediate guide slices must not repeat nearest-neighbour CT steps."""
    source = np.zeros((3, 24, 24), dtype=bool)
    yy, xx = np.indices(source.shape[1:])
    for z_index, center_x in enumerate((5.0, 11.0, 17.0)):
        source[z_index] = (xx - center_x) ** 2 + (yy - 12.0) ** 2 <= 4.0 ** 2

    resampled, spacing = _resample_mask_to_local_grid(
        source,
        source_spacing_zyx=(5.0, 1.0, 1.0),
        target_spacing_mm=1.0,
    )

    assert spacing == (1.0, 1.0, 1.0)
    assert resampled.shape[0] == 11
    center_x_by_slice = []
    for section in resampled:
        occupied = np.argwhere(section)
        center_x_by_slice.append(float(occupied[:, 1].mean()))
    # A nearest-neighbour resample would expose only the three source centres.
    # Signed-distance interpolation creates physically intermediate contours
    # across each 5 mm source-slice interval.
    rounded_centers = {round(value, 1) for value in center_x_by_slice}
    assert len(rounded_centers) >= 7
    assert center_x_by_slice == sorted(center_x_by_slice)


def test_skin_resampling_can_reuse_the_physical_signed_distance_field():
    source = np.zeros((5, 9, 9), dtype=bool)
    source[1:4, 2:7, 2:7] = True

    resampled, spacing, signed_distance = _resample_mask_to_local_grid(
        source,
        source_spacing_zyx=(2.0, 1.0, 1.0),
        target_spacing_mm=0.5,
        return_signed_distance=True,
    )

    assert spacing == (0.5, 0.5, 0.5)
    assert signed_distance.shape == resampled.shape
    assert signed_distance.dtype == np.float32
    assert np.array_equal(resampled, signed_distance <= 0.0)


def test_truncated_cap_rejection_preserves_lateral_skin_support():
    body = np.zeros((7, 11, 11), dtype=bool)
    body[:, 3:8, 3:8] = True
    signed_distance = np.ones(body.shape, dtype=np.float32)
    solid = np.zeros(body.shape, dtype=bool)
    # The first point is directly above the lower scan cap. The second lies
    # beside the lateral wall and is closer to real skin than to either cap.
    solid[1, 5, 5] = True
    solid[3, 5, 8] = True

    removed = _remove_truncated_cap_backed_voxels(
        solid,
        body,
        signed_distance,
        (1.0, 1.0, 1.0),
        remove_lower_cap=True,
        remove_upper_cap=True,
    )

    assert removed == 1
    assert not bool(solid[1, 5, 5])
    assert bool(solid[3, 5, 8])


def test_guide_is_watertight_and_stl_round_trips():
    agent = _synthetic_agent()
    guide = generate_surgical_guide(agent, {"geometry_resolution_mm": 1.0})
    assert guide["status"] == "ready"
    assert guide["validation"]["watertight"] is True
    assert guide["validation"]["source_needle_count"] == 1
    assert guide["auxiliary_holes"]["enabled"] is True
    assert guide["auxiliary_holes"]["realized_count"] > 0
    assert guide["needle_paths"][0]["guide_centerline_deviation_mm"] == 0.0
    assert guide["validation"]["geometry_resolution_mm"] == 1.0
    payload = mesh_to_ascii_stl(guide["vertices"], guide["faces"])
    assert validate_exported_stl(payload)["watertight"] is True
    skin = agent.memory.retrieve("skin_surface")
    skin_mask = agent.memory.retrieve("skin_surface_mask")
    assert skin["object_id"] == "skin_surface:guide"
    assert skin["data_tree_node_id"] == "skin_surface"
    assert skin["default_opacity"] == pytest.approx(0.10)
    assert skin["status"] == "ready"
    assert skin_mask.dtype == np.uint8
    assert skin_mask.shape == agent.memory.retrieve("ct_data").shape
    assert int(np.count_nonzero(skin_mask)) == skin["voxel_count"]
    assert guide["skin_surface_object_id"] == skin["object_id"]
    assert guide["skin_surface_data_version"] == skin["data_version"]


def test_auxiliary_holes_are_real_plate_only_alternate_paths():
    """The reference-style auxiliary pattern is part of the exported guide.

    Auxiliary holes are not viewer-only decorations: the generated solid must
    report realized alternate bores, keep them associated with the source
    needle, and mark them as plate-only/non-protruding geometry.
    """
    guide = generate_surgical_guide(_synthetic_agent(), {
        "geometry_resolution_mm": 0.5,
        "auxiliary_holes_enabled": True,
    })
    auxiliary = guide["auxiliary_holes"]
    assert auxiliary["enabled"] is True
    assert auxiliary["requested_count"] == 24
    assert auxiliary["realized_count"] > 0
    assert auxiliary["realized_count"] <= auxiliary["requested_count"]
    assert auxiliary["through_plate_only"] is True
    assert auxiliary["non_protruding"] is True
    assert len(auxiliary["holes"]) == auxiliary["realized_count"]
    assert {hole["needle_id"] for hole in auxiliary["holes"]} == {"needle_0"}
    assert guide["validation"]["auxiliary_holes"]["realized_count"] == auxiliary["realized_count"]
    assert guide["validation"]["watertight"] is True


def test_auxiliary_holes_can_be_disabled_without_changing_primary_contract():
    guide = generate_surgical_guide(_synthetic_agent(), {
        "geometry_resolution_mm": 1.0,
        "auxiliary_holes_enabled": False,
    })
    auxiliary = guide["auxiliary_holes"]
    assert auxiliary["enabled"] is False
    assert auxiliary["requested_count"] == 0
    assert auxiliary["realized_count"] == 0
    assert guide["validation"]["watertight"] is True


def test_cross_needle_auxiliary_holes_keep_a_printable_wall():
    """Auxiliary patterns from nearby needles must never intersect each other."""
    direction = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    paths = [
        NeedleGuidePath(
            needle_id="needle_0",
            trajectory_id="traj_1",
            target=np.array([32.0, 28.0, 32.0]),
            external=np.array([-10.0, 28.0, 32.0]),
            entry=np.array([10.0, 28.0, 32.0]),
            inward_direction=direction,
            seed_count=1,
        ),
        NeedleGuidePath(
            needle_id="needle_1",
            trajectory_id="traj_2",
            target=np.array([32.0, 36.0, 32.0]),
            external=np.array([-10.0, 36.0, 32.0]),
            entry=np.array([10.0, 36.0, 32.0]),
            inward_direction=direction,
            seed_count=1,
        ),
    ]
    params = normalize_guide_parameters({
        "geometry_resolution_mm": 1.0,
        "auxiliary_holes_enabled": True,
    })

    specs = _auxiliary_hole_specs(paths, params)
    skipped = [item for item in specs if item.get("skipped")]
    realized = [item for item in specs if not item.get("skipped")]

    assert any(item.get("skip_reason") == "nearby_auxiliary_hole" for item in skipped)
    assert {item["needle_id"] for item in realized} == {"needle_0", "needle_1"}
    minimum_distance = (
        2.0 * params["auxiliary_hole_radius_mm"] + GUIDE_MINIMUM_WALL_MM
    )
    for index, first in enumerate(realized):
        for second in realized[index + 1:]:
            distance = _segment_distance_mm(
                first["start"], first["end"], second["start"], second["end"]
            )
            assert distance + 1e-6 >= minimum_distance


def test_nearby_needles_generate_a_watertight_guide_with_auxiliary_holes():
    """Conflicting optional holes are skipped before voxel CSG and meshing."""
    agent = _synthetic_agent()
    agent.memory.store("algorithm_plan_snapshot", {
        "needles": [
            {
                "id": "needle_0",
                "trajectory_id": "traj_1",
                "points": [[32.0, 28.0, 32.0], [-10.0, 28.0, 32.0]],
            },
            {
                "id": "needle_1",
                "trajectory_id": "traj_2",
                "points": [[32.0, 36.0, 32.0], [-10.0, 36.0, 32.0]],
            },
        ],
        "seeds": [
            {
                "id": "seed_0",
                "trajectory_id": "traj_1",
                "position": [28.0, 28.0, 32.0],
            },
            {
                "id": "seed_1",
                "trajectory_id": "traj_2",
                "position": [28.0, 36.0, 32.0],
            },
        ],
    })

    guide = generate_surgical_guide(agent, {
        "geometry_resolution_mm": 1.0,
        "auxiliary_holes_enabled": True,
    })

    assert guide["validation"]["watertight"] is True
    assert guide["validation"]["open_edges"] == 0
    assert guide["validation"]["nonmanifold_edges"] == 0
    assert any(
        item["reason"] == "nearby_auxiliary_hole"
        for item in guide["auxiliary_holes"]["skipped"]
    )
    assert guide["auxiliary_holes"]["minimum_wall_mm"] == GUIDE_MINIMUM_WALL_MM


def test_distant_needle_groups_generate_one_watertight_guide():
    """The complete CSG pipeline must join non-overlapping local patches."""
    shape = (128, 128, 128)
    zz, yy, xx = np.indices(shape)
    body = (xx - 64) ** 2 + (yy - 64) ** 2 + (zz - 64) ** 2 <= 50 ** 2
    ct = np.where(body, 40, -1000).astype(np.int16)
    image = sitk.GetImageFromArray(ct)
    image.SetSpacing((1.0, 1.0, 1.0))
    agent = _Agent({
        "ct_image": image,
        "ct_data": ct,
        "algorithm_plan_snapshot": {
            "needles": [
                {
                    "id": "needle_left_group",
                    "trajectory_id": "traj_left_group",
                    "points": [[64.0, 35.0, 64.0], [-20.0, 35.0, 64.0]],
                },
                {
                    "id": "needle_right_group",
                    "trajectory_id": "traj_right_group",
                    "points": [[64.0, 93.0, 64.0], [-20.0, 93.0, 64.0]],
                },
            ],
            "seeds": [
                {
                    "id": "seed_left_group",
                    "trajectory_id": "traj_left_group",
                    "position": [50.0, 35.0, 64.0],
                },
                {
                    "id": "seed_right_group",
                    "trajectory_id": "traj_right_group",
                    "position": [50.0, 93.0, 64.0],
                },
            ],
        },
    })

    guide = generate_surgical_guide(agent, {
        "geometry_resolution_mm": 1.0,
        "auxiliary_holes_enabled": False,
    })

    connectivity = guide["validation"]["plate_connectivity"]
    assert connectivity["initial_component_count"] == 2
    assert connectivity["bridge_count"] == 1
    assert connectivity["final_component_count"] == 1
    assert connectivity["single_piece"] is True
    assert guide["validation"]["watertight"] is True
    assert validate_exported_stl(
        mesh_to_ascii_stl(guide["vertices"], guide["faces"])
    )["watertight"] is True


def test_auxiliary_hole_parameters_enforce_primary_wall_and_ring_spacing():
    defaults = normalize_guide_parameters()
    assert defaults["auxiliary_holes_enabled"] is True
    assert defaults["auxiliary_hole_first_offset_mm"] == 6.0
    assert defaults["auxiliary_hole_radius_mm"] == pytest.approx(
        defaults["channel_radius_mm"] + 0.4
    )

    legacy = normalize_guide_parameters({"sleeve_outer_radius_mm": 3.6})
    assert legacy["auxiliary_holes_enabled"] is False

    with pytest.raises(ValueError, match="wall"):
        normalize_guide_parameters({"auxiliary_hole_first_offset_mm": 2.0})
    with pytest.raises(ValueError, match="dense|wall"):
        normalize_guide_parameters({
            "auxiliary_holes_per_ring": 24,
            "auxiliary_hole_first_offset_mm": 2.2,
            "auxiliary_hole_radius_mm": 1.0,
        })


def test_auxiliary_bore_diameter_matches_primary_exported_bore():
    """A legacy auxiliary radius cannot produce a smaller physical hole."""
    params = normalize_guide_parameters({
        "channel_radius_mm": 0.9,
        "auxiliary_hole_radius_mm": 0.45,
    })
    assert params["auxiliary_hole_radius_mm"] == pytest.approx(1.3)
    assert params["auxiliary_hole_radius_mm"] == pytest.approx(
        params["channel_radius_mm"] + 0.4
    )


def test_guide_rejects_missing_plan_geometry():
    agent = _synthetic_agent()
    agent.memory.store("algorithm_plan_snapshot", {"needles": [], "seeds": []})
    try:
        generate_surgical_guide(agent)
    except ValueError as exc:
        assert "needle" in str(exc).lower()
    else:
        raise AssertionError("guide generation must reject an empty plan")


def test_guide_preserves_physical_coordinates_for_anisotropic_oriented_ct():
    """Guide dimensions must not inherit thick-slice CT index spacing."""
    agent = _synthetic_agent()
    image = agent.memory.retrieve("ct_image")
    image.SetSpacing((0.8, 0.8, 5.0))
    image.SetOrigin((12.0, -18.0, 40.0))
    image.SetDirection((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, -1.0))
    point = lambda index: list(image.TransformIndexToPhysicalPoint(index))
    agent.memory.store("algorithm_plan_snapshot", {
        "needles": [{
            "id": "needle_0",
            "trajectory_id": "traj_1",
            "points": [point((32, 32, 32)), point((0, 32, 32))],
        }],
        "seeds": [{
            "id": "seed_0",
            "trajectory_id": "traj_1",
            "position": point((28, 32, 32)),
        }],
    })

    guide = generate_surgical_guide(agent, {
        "geometry_resolution_mm": 1.0,
        "channel_radius_mm": 1.2,
        "sleeve_outer_radius_mm": 3.2,
    })
    assert guide["validation"]["watertight"] is True
    assert guide["parameters"]["geometry_resolution_mm"] == 1.0
    entry = np.asarray(guide["needle_paths"][0]["entry_world_mm"])
    expected_skin_x = image.TransformIndexToPhysicalPoint((10, 32, 32))[0]
    assert abs(entry[0] - expected_skin_x) <= 1.5
    assert np.all(np.isfinite(np.asarray(guide["vertices"])))


def test_guide_versions_preserve_parameters_and_stale_as_a_group():
    agent = _synthetic_agent()
    first = save_guide_version(agent, generate_surgical_guide(agent, {"channel_radius_mm": 1.0}))
    second = save_guide_version(agent, generate_surgical_guide(agent, {"channel_radius_mm": 1.4}))
    versions = guide_version_summaries(agent)
    assert [item["version"] for item in versions] == [second["version"], first["version"]]
    assert guide_state_for_version(agent, first["version"])["parameters"]["channel_radius_mm"] == 1.0
    assert invalidate_surgical_guides(agent, "needle geometry changed") is True
    assert all(item["status"] == "stale" for item in guide_version_summaries(agent))


def test_guide_version_reads_history_after_active_alias_is_replaced():
    agent = _synthetic_agent()
    first = save_guide_version(
        agent,
        generate_surgical_guide(agent, {"channel_radius_mm": 1.0}),
    )

    # A new Planning clears the active alias while retaining immutable guide
    # history.  The next guide must continue at v2 instead of reverting to v1.
    agent.memory.store("surgical_guide", None)
    agent.memory.store("manual_planning_id", "planning-new")
    second = save_guide_version(
        agent,
        generate_surgical_guide(agent, {"channel_radius_mm": 1.4}),
    )

    assert first["version"] == 1
    assert second["version"] == 2
    assert [item["version"] for item in guide_version_summaries(agent)] == [2, 1]


def test_guide_preserves_every_user_adjustable_manufacturing_dimension():
    parameters = normalize_guide_parameters({
        "skin_threshold_hu": -250.0,
        "skin_clearance_mm": 1.4,
        "plate_thickness_mm": 4.2,
        "patch_margin_mm": 32.0,
        "channel_radius_mm": 1.25,
        "sleeve_outer_radius_mm": 3.6,
        "sleeve_outward_mm": 11.0,
        "sleeve_inward_mm": 6.5,
        "geometry_resolution_mm": 0.8,
    })
    agent = _synthetic_agent()
    state = save_guide_version(agent, generate_surgical_guide(agent, parameters))
    assert state["parameters"] == parameters
    assert state["validation"]["watertight"] is True


def test_guide_sleeve_and_channel_stay_outside_the_body():
    """The channel must guide the needle from outside; the sleeve must not
    penetrate into the skin. Previously sleeve_end = entry + inward *
    sleeve_inward_mm pushed the channel wall into the patient, which would
    prevent the guide from sitting flush against the skin surface."""
    from scipy.spatial import cKDTree

    def gen(inward_mm):
        agent = _synthetic_agent()
        guide = generate_surgical_guide(agent, {
            "geometry_resolution_mm": 1.0,
            "skin_clearance_mm": 0.0,
            "plate_thickness_mm": 3.0,
            "channel_radius_mm": 1.0,
            "sleeve_outer_radius_mm": 3.0,
            "sleeve_outward_mm": 8.0,
            "sleeve_inward_mm": inward_mm,
        })
        return np.asarray(guide["vertices"]), guide

    # The channel/sleeve geometry must be independent of sleeve_inward_mm: the
    # tube is clamped flush with the skin entry, so asking for a longer inward
    # extent must not change the mesh. Before the fix this parameter pushed the
    # channel wall into the body and produced different geometry per value.
    v1, g1 = gen(1.0)
    v30, g30 = gen(30.0)
    assert len(v1) == len(v30) > 0
    tree = cKDTree(v30)
    dist, _ = tree.query(v1)
    assert float(dist.max()) < 1e-6
    # The guide must reach out of the body (outward sleeve) and stay watertight.
    assert g1["validation"]["watertight"] is True
    entry = np.asarray(g1["needle_paths"][0]["entry_world_mm"])
    inward = np.asarray(g1["needle_paths"][0]["direction_world"])
    t = (v1 - entry) @ inward
    assert float(t.max()) >= 5.0, "outward sleeve should protrude out of the body"


def test_agent_tool_uses_the_same_versioned_guide_contract_as_the_web_route():
    agent = _synthetic_agent()
    result = SurgicalGuideTool(agent).execute(action="generate", parameters={"channel_radius_mm": 1.3})
    assert result.success is True
    assert result.metadata["guide"]["version"] == 1
    assert guide_version_summaries(agent)[0]["version"] == 1


def test_surgical_guide_defaults_to_generate_when_action_is_omitted():
    """An empty LLM tool call follows the documented safe default action."""
    agent = _synthetic_agent()
    result = SurgicalGuideTool(agent).execute(parameters={"channel_radius_mm": 1.3})
    assert result.success is True
    assert result.metadata["guide"]["version"] == 1


def test_surgical_guide_has_manual_and_chat_entry_points():
    schema = SurgicalGuideTool().input_schema
    assert schema["properties"]["action"]["enum"] == ["generate", "status"]
    index = open("web/app/index.html", encoding="utf-8").read()
    script = open("web/app/static/js/brachybot-surgical-guide.js", encoding="utf-8").read()
    prompt = open("config/prompts/system_prompt.md", encoding="utf-8").read()
    assert "generateSurgicalGuideButton" in index
    assert "function generateSurgicalGuide" in script
    assert "ensureSurgicalGuideForCurrentPlan" in script
    assert "autoGenerateGuide: true" in open(
        "web/app/static/js/brachybot-chat-todo.js", encoding="utf-8"
    ).read()
    assert "surgical_guide" in prompt


def test_guide_artifact_is_bound_to_the_current_planning_version():
    agent = _synthetic_agent()
    agent.memory.store("manual_planning_id", "plan-test")
    agent.memory.store("manual_plan_version", 7)
    guide = generate_surgical_guide(agent, {"geometry_resolution_mm": 1.0})
    assert guide["object_id"] == "patient_specific_puncture_guide"
    assert guide["data_tree_node_id"] == guide["object_id"]
    assert guide["planning_id"] == "plan-test"
    assert guide["planning_version"] == 7
    assert guide["data_version"] == guide["version"]


def test_surgical_guide_is_rendered_as_an_independent_planning_artifact():
    tree_script = open(
        "web/app/static/js/brachybot-viewer-volume.js", encoding="utf-8"
    ).read()
    assert "independentPlanningMeshes" in tree_script


def test_manual_needle_addition_does_not_hide_algorithm_guide():
    """Adding a manual needle must not invalidate an algorithm-derived guide.

    guide_matches_current_plan compares the guide's source_plan_signature
    against _algorithm_planning_snapshot. A manual needle/seed addition changes
    the display snapshot (_current_planning_snapshot) but must leave the
    algorithm baseline signature unchanged so the existing guide stays visible
    and its regenerate path stays enabled.
    """
    from web.surgical_guide import (
        _algorithm_planning_snapshot,
        _current_planning_snapshot,
        planning_signature,
    )

    agent = _synthetic_agent()
    baseline_sig = planning_signature(_algorithm_planning_snapshot(agent))
    display_sig = planning_signature(_current_planning_snapshot(agent))
    assert baseline_sig == display_sig

    agent.memory.store("manual_needles", [{
        "id": "needle_manual_1",
        "trajectory_id": "manual_traj_1",
        "points": [[20.0, 20.0, 20.0], [20.0, 20.0, 5.0]],
    }])
    agent.memory.store("manual_seeds", [{
        "id": "seed_manual_1",
        "trajectory_id": "manual_traj_1",
        "position": [20.0, 20.0, 12.0],
    }])

    # The display snapshot includes the manual addition, so its signature
    # diverges from the algorithm baseline.
    assert planning_signature(_current_planning_snapshot(agent)) != baseline_sig
    # The algorithm baseline used for guide matching is unchanged.
    assert planning_signature(_algorithm_planning_snapshot(agent)) == baseline_sig

    guide = generate_surgical_guide(agent, {"geometry_resolution_mm": 1.0})
    assert guide["source_plan_signature"] == baseline_sig


def test_guide_channel_is_clean_flat_cylinder_with_open_through_hole():
    """The channel must be a TRUE flat-ended cylinder that protrudes OUTWARD.

    Regression for three related defects seen in earlier guides:
    1. The sleeve used a capsule (rounded end caps) instead of a flat cylinder,
       so the rounded cap poked the sleeve wall into the skin and sealed the
       bore on the body side (a blind hole).
    2. The sleeve inner end was anchored at the first interior voxel, deeper
       than the skin surface, compounding the inward protrusion.
    3. The local-region sleeve/bore evaluation had to be fast enough to keep
       guide generation practical on real CTs.
    """
    import time

    agent = _synthetic_agent()
    started = time.time()
    guide = generate_surgical_guide(agent, {
        "geometry_resolution_mm": 1.0,
        "skin_clearance_mm": 0.0,
        "plate_thickness_mm": 3.0,
        "channel_radius_mm": 1.0,
        "sleeve_outer_radius_mm": 3.0,
        "sleeve_outward_mm": 8.0,
    })
    elapsed = time.time() - started
    assert guide["validation"]["watertight"] is True
    # The per-needle local-region evaluation keeps a single-needle guide fast.
    assert elapsed < 30.0, f"guide generation too slow: {elapsed:.1f}s"

    entry = np.asarray(guide["needle_paths"][0]["entry_world_mm"])
    inward = np.asarray(guide["needle_paths"][0]["direction_world"])
    vertices = np.asarray(guide["vertices"], dtype=np.float64)
    rel = vertices - entry
    t = rel @ inward
    radial = np.linalg.norm(rel - np.outer(t, inward), axis=1)

    # (1) No sleeve/channel material may sit deep inside the body along the
    # needle axis (t > 0 toward the target, beyond the flush skin face).
    axis_near = radial < 1.5
    assert float(t[axis_near].max()) <= 0.75, "channel/sleeve penetrates the body"

    # (2) The outer end is a FLAT face (a true cylinder), not a rounded cap:
    # wall vertices near the sleeve tip share nearly the same axial position.
    tip_wall = (radial > 1.5) & (radial < 3.4) & (t < -10.0)
    assert tip_wall.any(), "sleeve outer end-face has no wall vertices"
    tip_range = float(t[tip_wall].max()) - float(t[tip_wall].min())
    # One marching-cubes voxel of staircase is expected at 1 mm resolution (plus
    # the 0.4 mm bore margin around the channel opening); a capsule would show
    # ~sleeve_radius of rounding (>= 3 mm).
    assert tip_range < 2.0, f"outer end-face is rounded, not flat (t range {tip_range:.2f})"

    # (3) The bore mouth is open on the outer face (channel is a through-hole).
    # The nominal channel opening is defined by the sleeve inner wall at
    # channel_radius; the bore is cleared with a margin so the opening is fully
    # open. r < channel_radius must contain no solid material.
    mouth_core = (radial < 0.8) & (t < -10.0)
    assert int(mouth_core.sum()) == 0, "bore core must be fully open on the outer face"
    # The channel rim (sleeve inner wall) must be present just outside the bore.
    rim = (radial > 1.0) & (radial < 2.0) & (t < -10.0)
    assert int(rim.sum()) >= 3, "channel rim must be present on the outer face"


def test_exported_primary_and_auxiliary_bore_walls_keep_exact_circular_radius():
    """Manufacturing STL wall vertices must not inherit smoothing error.

    The guide remains a Marching-Cubes mesh for reliable watertight topology,
    but the cylindrical needle interfaces are projected back to their analytic
    radii before export.  This regression protects the actual STL geometry,
    rather than only the Viewer preview.
    """
    guide = generate_surgical_guide(_synthetic_agent(), {
        "geometry_resolution_mm": 1.0,
        "auxiliary_holes_enabled": True,
    })
    quality = guide["validation"]["bore_quality"]
    assert quality["wall_policy"] == BORE_WALL_POLICY
    assert guide_bore_quality_ready(guide) is True
    assert quality["projected_vertex_count"] > 0
    assert quality["primary"]
    assert all(item["projected_vertex_count"] > 0 for item in quality["primary"])
    assert all(item["max_radius_error_after_mm"] < 1e-5 for item in quality["primary"])
    assert quality["auxiliary"]
    assert all(item["projected_vertex_count"] > 0 for item in quality["auxiliary"])
    assert all(item["max_radius_error_after_mm"] < 1e-5 for item in quality["auxiliary"])
    payload = mesh_to_ascii_stl(guide["vertices"], guide["faces"])
    exported = validate_exported_stl(payload)
    assert exported["watertight"] is True


def test_legacy_guide_without_bore_quality_must_be_regenerated_before_export():
    assert guide_bore_quality_ready({"status": "ready", "validation": {}}) is False


def test_guide_oblique_needle_does_not_penetrate_skin_after_trim():
    """An angled needle must not leave sleeve material inside the skin.

    The sleeve is a cylinder along the needle axis; for oblique needles its
    wall crosses the skin surface. The guide is trimmed with the smoothed
    skin's distance field (solid &= outside_distance >= skin_clearance), so no
    guide voxel may remain inside the body regardless of entry angle."""
    agent = _synthetic_agent()
    agent.memory.store("algorithm_plan_snapshot", {
        "needles": [{
            "id": "needle_0", "trajectory_id": "traj_1",
            # Oblique approach: target toward +y, external toward -x.
            "points": [[32.0, 40.0, 32.0], [-10.0, 24.0, 32.0]],
        }],
        "seeds": [{
            "id": "seed_0", "trajectory_id": "traj_1", "position": [28.0, 34.0, 32.0],
        }],
    })
    guide = generate_surgical_guide(agent, {
        "geometry_resolution_mm": 0.5,
        "skin_clearance_mm": 1.0,
        "plate_thickness_mm": 3.0,
        "channel_radius_mm": 0.9,
        "sleeve_outer_radius_mm": 3.0,
        "sleeve_outward_mm": 8.0,
    })
    assert guide["validation"]["watertight"] is True
    entry = np.asarray(guide["needle_paths"][0]["entry_world_mm"])
    inward = np.asarray(guide["needle_paths"][0]["direction_world"])
    vertices = np.asarray(guide["vertices"], dtype=np.float64)
    rel = vertices - entry
    t = rel @ inward
    radial = np.linalg.norm(rel - np.outer(t, inward), axis=1)
    center = np.array([32.0, 32.0, 32.0])
    body_in = np.linalg.norm(vertices - center, axis=1) < 22.0
    wall = (radial > 0.5) & (radial < 3.4) & (t > -1.0)
    # No sleeve-wall vertex may sit inside the body sphere.
    assert int((wall & body_in).sum()) == 0, "sleeve material penetrates the skin"


def test_guide_version_is_reused_when_plan_and_parameters_are_identical():
    """Duplicate generation calls must not bump the version number.

    After a server restart, the LLM tool call and the frontend auto-generate
    can both fire for the same plan; without dedup this produced v1, v2, v3
    all with the same geometry. Identical plan signature + parameters must
    reuse the latest version."""
    agent = _synthetic_agent()
    first = save_guide_version(agent, generate_surgical_guide(agent, {"geometry_resolution_mm": 1.0}))
    assert first["version"] == 1
    second = save_guide_version(agent, generate_surgical_guide(agent, {"geometry_resolution_mm": 1.0}))
    assert second["version"] == 1, "identical regen must not bump version"
    changed = save_guide_version(agent, generate_surgical_guide(agent, {
        "geometry_resolution_mm": 1.0, "plate_thickness_mm": 4.0,
    }))
    assert changed["version"] == 2, "parameter change should bump version"
    versions = guide_version_summaries(agent)
    assert [item["version"] for item in versions] == [2, 1]


def test_guide_mesh_status_stays_ready_in_the_data_tree():
    """A generated guide must not render as 'not_generated' in the Data Tree.

    The guide mesh carries status 'ready' without a `loaded` flag; the tree
    metadata resolver previously downgraded it to 'not_generated'."""
    tree_script = open(
        "web/app/static/js/brachybot-viewer-volume.js", encoding="utf-8"
    ).read()
    assert "explicitStatus === 'ready'" in tree_script, (
        "ensureDataTreeNodeMetadata must treat explicit 'ready' as authoritative"
    )
    assert "not_generated" in tree_script


def _truncated_cylinder_agent(z_count=24, yx=32, radius=12):
    """A CT whose body is a cylinder touching the z scan boundaries (finite FOV).

    The cylinder spans the full z range, so the first and last slices are FLAT
    truncation planes, not real skin — exactly the finite-field-of-view case.
    """
    ct = np.full((z_count, yx, yx), -1000, dtype=np.int16)
    center = yx / 2
    for z in range(z_count):
        for y in range(yx):
            for x in range(yx):
                if (x - center) ** 2 + (y - center) ** 2 <= radius ** 2:
                    ct[z, y, x] = 40
    image = sitk.GetImageFromArray(ct)
    image.SetSpacing((1.0, 1.0, 1.0))
    return _Agent({
        "ct_image": image,
        "ct_data": ct,
        "algorithm_plan_snapshot": {
            "needles": [{
                "id": "needle_0",
                "trajectory_id": "traj_1",
                "points": [[16.0, 16.0, 12.0], [16.0, 16.0, -20.0]],  # enters from +z top
            }],
            "seeds": [{
                "id": "seed_0",
                "trajectory_id": "traj_1",
                "position": [16.0, 16.0, 10.0],
            }],
        },
    })


def test_truncated_fov_body_is_detected_as_flat_cap():
    from web.surgical_guide import (
        _body_mask,
        _smooth_body_mask,
        _truncated_boundary_slices,
    )

    agent = _truncated_cylinder_agent()
    image = agent.memory.retrieve("ct_image")
    ct = agent.memory.retrieve("ct_data")
    body = _body_mask(ct, -300)
    body = _smooth_body_mask(body, (1.0, 1.0, 1.0), 2.0)
    trunc_z_min, trunc_z_max = _truncated_boundary_slices(body)
    assert trunc_z_min is True, "body touches z-min slice: inferior scan boundary is truncated"
    assert trunc_z_max is True, "body touches z-max slice: superior scan boundary is truncated"


def test_truncated_boundary_detection_and_local_guard_cover_all_array_faces():
    """A local guide crop must not use any finite-FOV face as printable skin."""
    from web.surgical_guide import (
        _local_boundary_safety_mask,
        _truncated_boundary_faces,
    )

    body = np.zeros((24, 24, 24), dtype=bool)
    body[:, 4:20, 4:20] = True
    faces = _truncated_boundary_faces(body)
    assert faces["z_min"] is True and faces["z_max"] is True
    assert faces["y_min"] is False and faces["y_max"] is False
    assert faces["x_min"] is False and faces["x_max"] is False

    safe, metadata = _local_boundary_safety_mask(
        local_shape_zyx=(24, 16, 16),
        lower_zyx=(0, 4, 4),
        upper_zyx=(23, 19, 19),
        source_shape_zyx=body.shape,
        boundary_faces=faces,
        target_spacing_zyx=(0.5, 0.5, 0.5),
        margin_mm=5.0,
    )
    assert not safe[:10].any()
    assert not safe[-10:].any()
    assert safe[10:-10].any()
    assert metadata["excluded_faces"] == {"z_min": 10, "z_max": 10}


def test_guide_entry_on_truncation_plane_is_rejected_and_lateral_skin_used():
    from web.surgical_guide import (
        SurgicalGuideError,
        _body_mask,
        _sample_skin_entry,
        _smooth_body_mask,
        _truncated_boundary_slices,
    )

    agent = _truncated_cylinder_agent()
    image = agent.memory.retrieve("ct_image")
    ct = agent.memory.retrieve("ct_data")
    body = _body_mask(ct, -300)
    body = _smooth_body_mask(body, (1.0, 1.0, 1.0), 2.0)
    trunc_z_min, trunc_z_max = _truncated_boundary_slices(body)

    # Needle entering from above (through the +z truncation plane) must NOT pick
    # the flat cap as its entry.
    target = np.asarray([16.0, 16.0, 12.0])
    external_top = np.asarray([16.0, 16.0, -20.0])
    with pytest.raises(SurgicalGuideError):
        _sample_skin_entry(
            image, body, target, external_top,
            truncated_z_min=trunc_z_min, truncated_z_max=trunc_z_max,
        )

    # A lateral needle enters through real cylindrical skin.
    external_lateral = np.asarray([-20.0, 16.0, 12.0])
    entry, _ = _sample_skin_entry(
        image, body, target, external_lateral,
        truncated_z_min=trunc_z_min, truncated_z_max=trunc_z_max,
    )
    assert abs(entry[2] - 12.0) < 3.0, "lateral entry should sit mid-scan (real skin)"


def test_lateral_ct_boundary_entry_is_not_treated_as_skin():
    from web.surgical_guide import (
        SurgicalGuideError,
        _body_mask,
        _largest_component,
        _sample_skin_entry,
        _smooth_body_mask,
        _truncated_boundary_faces,
    )

    # A body that fills the x-min acquisition face has a lateral cap just as
    # unsafe as a superior/inferior z cap. The guide must refuse that entry
    # instead of closing the plate against the finite CT field of view.
    ct = np.full((16, 16, 16), -1000, dtype=np.int16)
    ct[2:14, 2:14, 0:8] = 40
    image = sitk.GetImageFromArray(ct)
    image.SetSpacing((1.0, 1.0, 1.0))
    raw_body = _largest_component(ct > -300)
    faces = _truncated_boundary_faces(raw_body)
    body = _smooth_body_mask(raw_body, (1.0, 1.0, 1.0), 0.5)
    assert faces["x_min"] is True

    with pytest.raises(SurgicalGuideError):
        _sample_skin_entry(
            image,
            body,
            np.asarray([7.0, 8.0, 8.0]),
            np.asarray([-20.0, 8.0, 8.0]),
            truncated_boundary_faces=faces,
        )


def test_guide_with_only_truncated_entries_refuses_to_generate():
    """A guide whose only entry would be on a truncation plane must fail."""
    from web.surgical_guide import SurgicalGuideError, generate_surgical_guide

    agent = _truncated_cylinder_agent()
    # Force the needle to enter from the +z top only (no lateral alternative).
    agent.memory.store("algorithm_plan_snapshot", {
        "needles": [{
            "id": "needle_0", "trajectory_id": "traj_1",
            "points": [[16.0, 16.0, 12.0], [16.0, 16.0, -20.0]],
        }],
        "seeds": [{
            "id": "seed_0", "trajectory_id": "traj_1", "position": [16.0, 16.0, 10.0],
        }],
    })
    with pytest.raises(SurgicalGuideError) as exc_info:
        generate_surgical_guide(agent, {"geometry_resolution_mm": 1.0})
    assert "truncation" in str(exc_info.value).lower() or "scan" in str(exc_info.value).lower()


def test_nearby_needle_sleeve_does_not_plug_neighbouring_channel():
    """Two closely spaced needles must keep each channel a clean through-hole.

    Without the bore margin, the wall of one sleeve intruded into the
    neighbouring channel opening (radial distance 0.7-1.0 mm from the neighbour
    axis). The bore subtraction is now enlarged by GUIDE_BORE_MARGIN_MM so a
    neighbouring wall can never enter the channel."""
    shape = (64, 64, 64)
    zz, yy, xx = np.indices(shape)
    body = (xx - 32) ** 2 / 900 + (yy - 32) ** 2 / 900 + (zz - 32) ** 2 / 900 <= 1.0
    ct = np.where(body, 40, -1000).astype(np.int16)
    image = sitk.GetImageFromArray(ct)
    image.SetSpacing((1.0, 1.0, 1.0))
    agent = _Agent({
        "ct_image": image,
        "ct_data": ct,
        "algorithm_plan_snapshot": {
            "needles": [
                {"id": "needle_0", "trajectory_id": "traj_1",
                 "points": [[32.0, 32.0, 32.0], [-10.0, 32.0, 32.0]]},
                {"id": "needle_1", "trajectory_id": "traj_2",
                 "points": [[35.0, 32.0, 32.0], [-10.0, 35.0, 32.0]]},
            ],
            "seeds": [
                {"id": "seed_0", "trajectory_id": "traj_1", "position": [28.0, 32.0, 32.0]},
                {"id": "seed_1", "trajectory_id": "traj_2", "position": [28.0, 35.0, 32.0]},
            ],
        },
    })
    guide = generate_surgical_guide(agent, {"geometry_resolution_mm": 0.5})
    assert guide["validation"]["watertight"] is True
    vertices = np.asarray(guide["vertices"], dtype=np.float64)
    entries = [np.asarray(p["entry_world_mm"]) for p in guide["needle_paths"]]
    directions = [np.asarray(p["direction_world"]) for p in guide["needle_paths"]]

    # For each needle, check that no OTHER needle's sleeve wall (radial 1.0-3.2
    # mm from that other needle's axis) intrudes into THIS channel (radial < 1.0
    # mm from this axis) along the sleeve region.
    for i in range(2):
        e_i = entries[i]
        d_i = directions[i]
        for j in range(2):
            if i == j:
                continue
            e_j = entries[j]
            d_j = directions[j]
            rel_i = vertices - e_i
            t_i = rel_i @ d_i
            r_i = np.linalg.norm(rel_i - np.outer(t_i, d_i), axis=1)
            rel_j = vertices - e_j
            r_j = np.linalg.norm(rel_j - np.outer(rel_j @ d_j, d_j), axis=1)
            # This channel (near needle i axis, in the sleeve region) must not
            # contain material from the neighbouring sleeve wall.
            in_channel = (r_i < 1.0) & (t_i < -6.0)
            from_neighbour_wall = (r_j > 1.0) & (r_j < 3.2)
            intrusion = int((in_channel & from_neighbour_wall).sum())
            assert intrusion == 0, (
                f"needle {j} sleeve wall intrudes into needle {i} channel ({intrusion} vertices)"
            )


def test_guide_is_shaved_off_truncated_ct_boundaries():
    """A guide on a truncated-CT cylinder must not wrap onto the scan-boundary
    flat planes: after generation the mesh must not contain solid at the CT
    first/last slice, even though the entry is valid lateral skin."""
    z_count, yx, radius = 40, 48, 15
    ct = np.full((z_count, yx, yx), -1000, dtype=np.int16)
    for z in range(z_count):
        for y in range(yx):
            for x in range(yx):
                if (x - yx / 2) ** 2 + (y - yx / 2) ** 2 <= radius ** 2:
                    ct[z, y, x] = 40
    image = sitk.GetImageFromArray(ct)
    image.SetSpacing((1.0, 1.0, 1.0))
    image.SetOrigin((0.0, 0.0, 0.0))
    agent = _Agent({
        "ct_image": image,
        "ct_data": ct,
        "algorithm_plan_snapshot": {
            "needles": [{
                "id": "needle_0", "trajectory_id": "traj_1",
                "points": [[24.0, 24.0, 20.0], [-20.0, 24.0, 20.0]],
            }],
            "seeds": [{
                "id": "seed_0", "trajectory_id": "traj_1", "position": [20.0, 24.0, 20.0],
            }],
        },
    })
    guide = generate_surgical_guide(agent, {"geometry_resolution_mm": 0.5})
    assert guide["validation"]["watertight"] is True
    fov = guide["validation"].get("finite_fov") or {}
    assert fov.get("truncated_superior") is True
    assert fov.get("truncated_inferior") is True
    vertices = np.asarray(guide["vertices"], dtype=np.float64)
    # CT z in [0, z_count-1]. The guide must be shaved off the boundary slices
    # by the truncation safety margin (default 5 mm), not just a single voxel:
    # no vertex may sit on or near the flat scan-boundary planes, otherwise the
    # plate would contact the cut as if it were real skin.
    min_z = float(vertices[:, 2].min())
    max_z = float(vertices[:, 2].max())
    assert min_z >= 3.0, f"guide still contacts z=0 truncation plane (min z {min_z:.2f})"
    assert max_z <= float(z_count - 1) - 3.0, (
        f"guide still contacts z={z_count - 1} truncation plane (max z {max_z:.2f})"
    )


def test_guide_contact_surface_has_no_flat_platform_on_truncated_cap():
    """The plate on a truncated cylinder must not form a flat horizontal
    platform spanning the scan-boundary cap.

    Previously the guide plate was built from the CLOSED body mask, so the
    shell wrapped the flat superior/inferior caps and the guide's contact
    surface adhered to the CT truncation plane instead of real lateral skin.
    After the fix the plate is built only from voxels whose nearest body voxel
    is lateral skin (not a truncated boundary slice), and the plate is shaved
    back by ``truncation_margin_mm``. As a result the guide has no large
    horizontal platform faces on the cap: its top/bottom edges are narrow rims
    hugging the cylinder wall, and the whole mesh stays clear of the boundary.
    """
    z_count, yx, radius = 40, 48, 15
    ct = np.full((z_count, yx, yx), -1000, dtype=np.int16)
    for z in range(z_count):
        for y in range(yx):
            for x in range(yx):
                if (x - yx / 2) ** 2 + (y - yx / 2) ** 2 <= radius ** 2:
                    ct[z, y, x] = 40
    image = sitk.GetImageFromArray(ct)
    image.SetSpacing((1.0, 1.0, 1.0))
    image.SetOrigin((0.0, 0.0, 0.0))
    agent = _Agent({
        "ct_image": image,
        "ct_data": ct,
        "algorithm_plan_snapshot": {
            "needles": [{
                "id": "needle_0", "trajectory_id": "traj_1",
                "points": [[24.0, 24.0, 20.0], [-20.0, 24.0, 20.0]],
            }],
            "seeds": [{
                "id": "seed_0", "trajectory_id": "traj_1", "position": [20.0, 24.0, 20.0],
            }],
        },
    })
    guide = generate_surgical_guide(agent, {"geometry_resolution_mm": 0.5})
    vertices = np.asarray(guide["vertices"], dtype=np.float64)
    faces = np.asarray(guide["faces"], dtype=np.int64)
    tri = vertices[faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norms = np.linalg.norm(normals, axis=1)
    norms[norms < 1e-9] = 1.0
    normals = normals / norms[:, None]
    face_z = tri.mean(axis=1)[:, 2]
    # Horizontal platform faces (normal ~ along z) far from the cylinder wall
    # would mean the plate wraps the flat cap. The body radius is 15; the plate
    # hugs the lateral wall at radius ~16-19. Faces with a tiny radial extent
    # inside the cap interior are the forbidden flat platform.
    cx = cy = yx / 2.0
    center = tri.mean(axis=1)[:, :2]
    radial = np.sqrt((center[:, 0] - cx) ** 2 + (center[:, 1] - cy) ** 2)
    horizontal = np.abs(normals[:, 2]) > 0.9
    # The plate is shaved back by 5 mm from the boundaries, so the natural
    # top/bottom rims sit at z in [5, 34]. Faces inside that band that are
    # horizontal AND close to the body axis (radial < radius) would be a flat
    # cap platform rather than the lateral ring's end rim.
    in_band = (face_z > 6.0) & (face_z < 33.0)
    cap_platform = horizontal & in_band & (radial < float(radius) - 1.0)
    assert int(cap_platform.sum()) == 0, (
        f"{int(cap_platform.sum())} flat platform faces on the truncated cap"
    )


def test_converging_needle_bores_stay_open_after_unified_drilling():
    """Closely spaced converging needles must each keep a clean through-hole.

    The guide is built as ``(plate ∪ all sleeves) \\ all bores``: every sleeve
    cylinder is unioned first, then every bore is subtracted from the fully
    unioned solid. This guarantees a neighbouring sleeve wall can never plug a
    channel regardless of spacing or crossing angle. Previously the bores were
    drilled before the sleeves were fully merged, so an oblique sleeve wall
    could intrude into an adjacent channel opening."""
    from scipy.spatial import cKDTree

    shape = (90, 90, 90)
    zz, yy, xx = np.indices(shape)
    body = (xx - 45) ** 2 / 900 + (yy - 45) ** 2 / 900 + (zz - 45) ** 2 / 900 <= 1.0
    ct = np.where(body, 40, -1000).astype(np.int16)
    image = sitk.GetImageFromArray(ct)
    image.SetSpacing((1.0, 1.0, 1.0))
    entries = [(12.0, y, 45.0) for y in (40.0, 43.0, 47.0, 50.0)]
    targets = [(45.0, 44.0, 45.0), (45.0, 45.0, 45.0), (45.0, 45.0, 45.0), (45.0, 46.0, 45.0)]
    agent = _Agent({
        "ct_image": image,
        "ct_data": ct,
        "algorithm_plan_snapshot": {
            "needles": [
                {"id": f"needle_{i}", "trajectory_id": f"traj_{i + 1}",
                 "points": [list(t), list(e)]}
                for i, (e, t) in enumerate(zip(entries, targets))
            ],
            "seeds": [
                {"id": f"seed_{i}", "trajectory_id": f"traj_{i + 1}",
                 "position": [28.0, t[1], t[2]]}
                for i, t in enumerate(targets)
            ],
        },
    })
    guide = generate_surgical_guide(agent, {"geometry_resolution_mm": 0.5})
    assert guide["validation"]["watertight"] is True
    vertices = np.asarray(guide["vertices"], dtype=np.float64)
    tree = cKDTree(vertices)
    for path in guide["needle_paths"]:
        entry = np.asarray(path["entry_world_mm"])
        inward = np.asarray(path["direction_world"])
        # Sample the channel axis in the open OUTWARD sleeve region. The first
        # few millimetres behind the entry sit inside the plate (where the bore
        # meets the plate's skin side); the test samples the free sleeve beyond
        # that junction. The bore is drilled at channel_radius + margin
        # (1.3 mm), so points on the axis must stay clear of solid material.
        samples = entry[None, :] + inward[None, :] * np.linspace(-5.0, -11.0, 20)[:, None]
        dist, _ = tree.query(samples)
        # The channel core must be clear. At 0.5 mm resolution the bore wall
        # isosurface can lie ~0.3 mm inside the nominal 1.3 mm bore radius, so
        # a 0.3 mm threshold checks the through-hole is genuinely open without
        # mistaking the discretised wall for a blocked channel.
        blocked = int((dist < 0.3).sum())
        assert blocked == 0, (
            f"{path['needle_id']} channel is blocked by a neighbouring sleeve wall"
        )


def test_primary_bore_cutter_drills_through_foreign_sleeve_beyond_own_tip():
    """A foreign sleeve wall must be cut even beyond the first sleeve's tip.

    This is the geometry seen when two angled needle sleeves approach each
    other: the foreign sleeve can enter a primary channel after that channel's
    own printed sleeve nominally ends. A sleeve-length-only cutter leaves a
    crescent of foreign wall in the otherwise circular channel.
    """
    image = sitk.GetImageFromArray(np.zeros((48, 48, 48), dtype=np.int16))
    image.SetSpacing((1.0, 1.0, 1.0))
    params = normalize_guide_parameters({
        "geometry_resolution_mm": 0.5,
        "skin_clearance_mm": 0.0,
        "plate_thickness_mm": 3.0,
        "channel_radius_mm": 0.9,
        "sleeve_outer_radius_mm": 3.0,
        "sleeve_outward_mm": 8.0,
        "auxiliary_holes_enabled": False,
    })
    primary = NeedleGuidePath(
        needle_id="needle_primary",
        trajectory_id="traj_primary",
        target=np.array([0.0, 20.0, 20.0]),
        external=np.array([20.0, 20.0, 20.0]),
        entry=np.array([5.0, 20.0, 20.0]),
        inward_direction=np.array([-1.0, 0.0, 0.0]),
        seed_count=1,
    )
    crossing = NeedleGuidePath(
        needle_id="needle_crossing",
        trajectory_id="traj_crossing",
        target=np.array([23.0, 8.0, 20.0]),
        external=np.array([23.0, 32.0, 20.0]),
        entry=np.array([23.0, 16.0, 20.0]),
        inward_direction=np.array([0.0, -1.0, 0.0]),
        seed_count=1,
    )
    cutters = _primary_bore_cutter_specs([primary, crossing], params)
    primary_cutter = next(item for item in cutters if item["needle_id"] == primary.needle_id)

    # The primary sleeve itself ends at x=16 mm. The foreign sleeve crosses
    # its channel at x=23 mm, so the final cutter must extend past that wall.
    assert primary_cutter["nominal_length_mm"] == pytest.approx(11.0)
    assert float(np.asarray(primary_cutter["end"])[0]) > 25.0
    assert [item["needle_id"] for item in primary_cutter["crossing_sleeves"]] == [
        crossing.needle_id
    ]

    solid = np.zeros((48, 48, 48), dtype=bool)
    lower_xyz = np.zeros(3, dtype=np.int64)
    crossing_start = np.asarray(crossing.entry, dtype=np.float64)
    crossing_end = crossing_start - crossing.inward_direction * 11.0
    crossing_sdf, box = _cylinder_sdf_in_region(
        image,
        lower_xyz,
        solid.shape,
        (1.0, 1.0, 1.0),
        crossing_start,
        crossing_end,
        3.0,
    )
    solid[box] |= crossing_sdf <= 0.0

    # This point lies on the primary channel axis but in the *wall* (not the
    # central bore) of the crossing sleeve. It reproduces the blocked crescent
    # in the report image before the extended primary cutter is applied.
    probe_zyx = (20, 20, 25)
    assert bool(solid[probe_zyx]) is True
    _subtract_cylinder_specs_from_mask(
        solid,
        image,
        lower_xyz,
        (1.0, 1.0, 1.0),
        cutters,
    )
    assert bool(solid[probe_zyx]) is False

    # The post-Marching-Cubes circular-wall projection must use the same
    # extended cutters. Otherwise it can snap a crossing sleeve-wall vertex
    # back into the newly drilled primary channel after the Boolean CSG pass.
    foreign_wall_vertex = np.array([[24.5, 20.0, 20.0]], dtype=np.float32)
    projected, quality = _project_bore_walls(
        foreign_wall_vertex,
        [primary, crossing],
        [],
        params,
        primary_bore_specs=cutters,
    )
    assert np.allclose(projected, foreign_wall_vertex)
    assert sum(
        item["cross_bore_protected_vertex_count"]
        for item in quality["primary"]
    ) >= 1


def test_bore_wall_projection_never_recloses_a_crossing_primary_channel():
    """Analytic bore rounding must preserve an already drilled crossing void.

    Boolean CSG correctly drills every primary bore last. This unit-level
    regression isolates the later circular-wall projection: a vertex close to
    one sleeve wall would otherwise be snapped into another channel at an
    exact trajectory crossing.
    """
    paths = [
        NeedleGuidePath(
            needle_id="needle_x",
            trajectory_id="traj_1",
            target=np.array([12.0, 0.0, 0.0]),
            external=np.array([-12.0, 0.0, 0.0]),
            entry=np.array([0.0, 0.0, 0.0]),
            inward_direction=np.array([-1.0, 0.0, 0.0]),
            seed_count=1,
        ),
        NeedleGuidePath(
            needle_id="needle_z",
            trajectory_id="traj_2",
            target=np.array([5.0, 0.0, -12.0]),
            external=np.array([5.0, 0.0, 12.0]),
            entry=np.array([5.0, 0.0, 0.0]),
            inward_direction=np.array([0.0, 0.0, -1.0]),
            seed_count=1,
        ),
    ]
    params = normalize_guide_parameters({
        "geometry_resolution_mm": 0.5,
        "skin_clearance_mm": 0.0,
        "plate_thickness_mm": 3.0,
        "sleeve_outward_mm": 8.0,
        "auxiliary_holes_enabled": False,
    })
    # This point lies just outside the x-directed sleeve wall. Rounding that
    # wall to its bore radius would move it into the z-directed primary bore
    # unless the cross-bore guard rejects the projection.
    vertices = np.array([[5.0, 1.50, 0.0]], dtype=np.float32)
    projected, qa = _project_bore_walls(vertices, paths, [], params)

    assert np.allclose(projected, vertices)
    assert sum(item["cross_bore_protected_vertex_count"] for item in qa["primary"]) >= 1




