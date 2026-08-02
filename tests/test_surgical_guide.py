"""Geometry regressions for the native patient-specific puncture guide."""

from __future__ import annotations

import numpy as np
import pytest
import SimpleITK as sitk

from tool_factory.surgical_guide import SurgicalGuideTool
from web.surgical_guide import (
    generate_surgical_guide,
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


def test_guide_is_watertight_and_stl_round_trips():
    guide = generate_surgical_guide(_synthetic_agent(), {"geometry_resolution_mm": 1.0})
    assert guide["status"] == "ready"
    assert guide["validation"]["watertight"] is True
    assert guide["validation"]["source_needle_count"] == 1
    assert guide["needle_paths"][0]["guide_centerline_deviation_mm"] == 0.0
    assert guide["validation"]["geometry_resolution_mm"] == 1.0
    payload = mesh_to_ascii_stl(guide["vertices"], guide["faces"])
    assert validate_exported_stl(payload)["watertight"] is True


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
    # CT z in [0, z_count-1]. The guide must be shaved off the boundary slices:
    # no vertex may sit exactly on z=0 or z=z_count-1 (the flat truncation
    # planes), otherwise the plate would contact the scan boundary as if skin.
    min_z = float(vertices[:, 2].min())
    max_z = float(vertices[:, 2].max())
    assert min_z > 0.4, f"guide still touches z=0 truncation plane (min z {min_z:.2f})"
    assert max_z < float(z_count - 1) - 0.4, (
        f"guide still touches z={z_count - 1} truncation plane (max z {max_z:.2f})"
    )




