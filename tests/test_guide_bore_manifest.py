"""Synthetic final-mesh negative controls for reusable manufactured bores."""

from copy import deepcopy
import hashlib
from types import SimpleNamespace

import numpy as np
import pytest
import SimpleITK as sitk

from web.guide_placement import (
    BoreValidationProfile, CurrentCTGeometry, GuidePlacementError, audit_bore_mesh, build_bore_manifest,
    create_guide_placement, image_geometry_identity, initialize_bore_trajectories,
    mesh_geometry_sha256, verify_manufactured_geometry,
    review_guide_placement,
)
from web.surgical_guide import (
    DEFAULT_GUIDE_PARAMETERS, GUIDE_MINIMUM_WALL_MM, generate_surgical_guide,
    mesh_to_ascii_stl, normalize_guide_parameters,
)


# Paired fixture audit, 2026-10-10, isolated RTX3090 checkout, CPU only.
# The before side was run before Task C files were transferred. The exact same
# 64-cubed spherical CT and source plan below were used. Byte-identical indexed
# meshes are required; final-bore metadata intentionally becomes stricter.
# These single-run times are observations, not a p50/p95 or clinical benchmark.
# Frozen latency reference/dependency hashes and evidence remain untouched.
PRE_TASK_GEOMETRY_AUDIT = {
    (1., False): {
        "before_seconds": .2043776020873338, "legacy_auxiliary_count": 0,
        "after_seconds": .5990929210092872, "audited_auxiliary_count": 0,
        "vertices_sha256": "a82c2740c7f4a0e80ef36efa609033f85fb3732df1e7ca7e5795fb57fe1c9e8e",
        "faces_sha256": "ca58ce7f61b7945df1a014afd242e86c1582710b8dce93b8b25ec9d4f207fe07",
    },
    (1., True): {
        "before_seconds": .1256699471268803, "legacy_auxiliary_count": 21,
        "after_seconds": .6945123279001564, "audited_auxiliary_count": 10,
        "vertices_sha256": "99c40e25a1adbdac9ad684c7bbbaf95488d27c891dc79d17d914ec2bfac60805",
        "faces_sha256": "0df8af7d2ce6b6888482929a9f940a8276e69b6380ecf085ffada54a62a9c7bb",
    },
    (.5, False): {
        "before_seconds": .280580576043576, "legacy_auxiliary_count": 0,
        "after_seconds": 2.127949324902147, "audited_auxiliary_count": 0,
        "vertices_sha256": "e6cfefc66bb79792bedff2041c3f428688a2e093a42e75ddb6543cd67a13e9e7",
        "faces_sha256": "b8e207b9b637811e505cc07bd38862e33d4720d7fdf3fd339f147b6bfbcb5667",
    },
    (.5, True): {
        "before_seconds": .3246057608630508, "legacy_auxiliary_count": 24,
        "after_seconds": 2.660360732814297, "audited_auxiliary_count": 16,
        "vertices_sha256": "d1b26a9dceb290812fac3144421c0ffc24078526df2d7c97936c7affcff76bf3",
        "faces_sha256": "4a663315eb19b80244e6df6da89f4c0f5feea487361aa57c22a80807cfe3c8e5",
    },
}


def annular_mesh(start=0.0, end=3.0, inner=1.3, outer=3.0, count=64):
    angles = np.arange(count) * 2 * np.pi / count
    vertices = []
    for x, radius in ((start, inner), (start, outer), (end, inner), (end, outer)):
        vertices.extend(np.column_stack((np.full(count, x), radius * np.cos(angles), radius * np.sin(angles))))
    faces = []
    for a, b in ((0, 1), (1, 3), (3, 2), (2, 0)):
        for i in range(count):
            j = (i + 1) % count
            faces.extend(((a * count + i, a * count + j, b * count + j),
                          (a * count + i, b * count + j, b * count + i)))
    return np.asarray(vertices, dtype=np.float32), np.asarray(faces, dtype=np.int32)


def bore_candidate(kind="auxiliary", candidate_id="aux_synthetic"):
    return {"candidate_id": candidate_id, "kind": kind, "center_local_mm": [0, 0, 0],
            "axis_local": [1, 0, 0], "requested_radius_mm": 1.3,
            "construction_endpoints_local_mm": [[-2, 0, 0], [5, 0, 0]],
            "provenance": "synthetic_annular_fixture"}


def tube_guide():
    vertices, faces = annular_mesh()
    manifest = build_bore_manifest(vertices, faces, [bore_candidate()], minimum_wall_mm=GUIDE_MINIMUM_WALL_MM)
    return {"vertices": vertices, "faces": faces, "bore_manifest": manifest}


def test_manifest_is_measured_on_exact_export_without_mutating_mesh():
    guide = tube_guide()
    manifest = verify_manufactured_geometry(guide)
    assert manifest["stl_sha256"] == hashlib.sha256(mesh_to_ascii_stl(guide["vertices"], guide["faces"])).hexdigest()
    assert manifest["mesh_sha256"] == mesh_geometry_sha256(guide["vertices"], guide["faces"])
    bore = manifest["bores"][0]
    assert bore["eligible"] and bore["manufacturing_outcome"] == "realized"
    assert bore["guiding_length_mm"] == pytest.approx(3)
    assert bore["outer_intersection_local_mm"] == pytest.approx([0, 0, 0])
    assert bore["inner_intersection_local_mm"] == pytest.approx([3, 0, 0])
    assert 1.29 < bore["effective_radius_mm"] < 1.3
    assert bore["needle_clearance_mm"] is None
    assert bore["geometry_audit"]["mechanical_validation"] == "not_established"
    assert bore["bore_id"] == tube_guide()["bore_manifest"]["bores"][0]["bore_id"]


def test_skipped_candidate_and_legacy_center_do_not_certify_a_through_hole():
    guide = tube_guide()
    candidate = bore_candidate()
    candidate["skip_reason"] = "outside_plate_patch"
    manifest = build_bore_manifest(guide["vertices"], guide["faces"], [candidate], minimum_wall_mm=.35)
    assert manifest["bores"][0]["manufacturing_outcome"] == "skipped"
    assert not manifest["bores"][0]["eligible"]
    with pytest.raises(GuidePlacementError, match="legacy"):
        verify_manufactured_geometry({"auxiliary_holes": {"holes": [{"center_world_mm": [0, 0, 0]}]}})


def test_subray_membrane_is_detected_by_continuous_triangle_geometry():
    vertices, faces = annular_mesh()
    # A tiny triangle intersects the axis between any discrete axial samples.
    blocker = np.array([[1.234567, -.001, -.001], [1.234567, .001, -.001], [1.234567, 0, .001]])
    faces = np.vstack((faces, np.arange(len(vertices), len(vertices) + 3)))
    vertices = np.vstack((vertices, blocker))
    result = audit_bore_mesh(vertices, faces, bore_candidate(), minimum_wall_mm=.35)
    assert not result["passed"]
    assert result["reason"] == "blocked_axis_in_final_mesh"


def test_absent_disconnected_and_merged_channels_fail_closed():
    vertices, faces = annular_mesh()
    absent = bore_candidate()
    absent["center_local_mm"] = [0, 8, 0]
    assert not audit_bore_mesh(vertices, faces, absent, minimum_wall_mm=.35)["passed"]
    other_vertices, other_faces = annular_mesh(5, 8)
    result = audit_bore_mesh(np.vstack((vertices, other_vertices)),
                            np.vstack((faces, other_faces + len(vertices))),
                            bore_candidate(), minimum_wall_mm=.35)
    assert result["reason"] == "disconnected_guidance"
    # A centerline alone remains open in a larger merged void, but the
    # independent channel has lost its intended enclosing guidance wall.
    vertices, faces = annular_mesh(inner=2)
    result = audit_bore_mesh(vertices, faces, bore_candidate(), minimum_wall_mm=.35)
    assert not result["passed"]
    assert result["reason"] == "missing_or_ambiguous_wall_support"


def test_narrow_missing_wall_between_support_rays_is_not_certified():
    # A watertight C-shaped tube has a very narrow slit at angle zero. All
    # sixteen material-membership rays miss it; continuous cylinder/triangle
    # crossings must still reject the lost enclosing guidance.
    count = 65
    angles = np.linspace(.005, 2 * np.pi - .005, count)
    vertices = []
    for x, radius in ((0, 1.3), (0, 3), (3, 1.3), (3, 3)):
        vertices.extend(np.column_stack((np.full(count, x), radius * np.cos(angles), radius * np.sin(angles))))
    faces = []
    for a, b in ((0, 1), (1, 3), (3, 2), (2, 0)):
        for i in range(count - 1):
            faces.extend(((a * count + i, a * count + i + 1, b * count + i + 1),
                          (a * count + i, b * count + i + 1, b * count + i)))
    for i in (0, count - 1):
        faces.extend(((i, count + i, 3 * count + i), (i, 3 * count + i, 2 * count + i)))
    vertices, faces = np.asarray(vertices), np.asarray(faces)
    from web.surgical_guide import mesh_validation
    assert mesh_validation(vertices, faces)["watertight"]
    result = audit_bore_mesh(vertices, faces, bore_candidate(), minimum_wall_mm=.35)
    assert not result["passed"]
    assert result["reason"] == "missing_continuous_cylindrical_support"


def test_hash_and_manifest_changes_are_rejected():
    guide = tube_guide()
    changed = deepcopy(guide)
    changed["vertices"][0, 0] += .1
    with pytest.raises(GuidePlacementError, match="mesh changed"):
        verify_manufactured_geometry(changed)
    changed = deepcopy(guide)
    changed["bore_manifest"]["bores"][0]["guiding_length_mm"] += 1
    with pytest.raises(GuidePlacementError, match="manifest changed"):
        verify_manufactured_geometry(changed)
    with pytest.raises(GuidePlacementError, match="STL bytes differ"):
        verify_manufactured_geometry(guide, stl_payload=b"other artifact")


class _Memory:
    def __init__(self, values):
        self.values = values

    def retrieve(self, key):
        return self.values.get(key)

    def store(self, key, value):
        self.values[key] = value


def synthetic_agent():
    z, y, x = np.indices((64, 64, 64))
    ct = np.where((x - 32) ** 2 + (y - 32) ** 2 + (z - 32) ** 2 <= 22 ** 2, 40, -1000).astype(np.int16)
    return SimpleNamespace(memory=_Memory({
        "ct_image": sitk.GetImageFromArray(ct), "ct_data": ct,
        "algorithm_plan_snapshot": {
            "needles": [{"id": "needle_0", "trajectory_id": "traj_1",
                         "points": [[32., 32., 32.], [-10., 32., 32.]]}],
            "seeds": [{"id": "seed_0", "trajectory_id": "traj_1", "position": [28., 32., 32.]}],
        },
    }))


@pytest.mark.parametrize("resolution,enabled", PRE_TASK_GEOMETRY_AUDIT)
def test_default_mesh_matches_paired_pre_task_fixture_audit(resolution, enabled):
    guide = generate_surgical_guide(synthetic_agent(), {
        "geometry_resolution_mm": resolution, "auxiliary_holes_enabled": enabled,
        "auxiliary_density_profile": "standard_v1",
    })
    before = PRE_TASK_GEOMETRY_AUDIT[(resolution, enabled)]
    assert hashlib.sha256(guide["vertices"].tobytes()).hexdigest() == before["vertices_sha256"]
    assert hashlib.sha256(guide["faces"].tobytes()).hexdigest() == before["faces_sha256"]
    assert guide["validation"]["watertight"]
    assert guide["parameters"]["truncation_margin_mm"] == 5


def test_generation_final_manifest_matches_holes_and_frozen_mesh():
    guide = generate_surgical_guide(synthetic_agent(), {"geometry_resolution_mm": .5})
    manifest = verify_manufactured_geometry(guide)
    auxiliary = [b for b in manifest["bores"] if b["kind"] == "auxiliary"]
    assert guide["auxiliary_holes"]["realized_count"] == sum(b["eligible"] for b in auxiliary)
    assert {h["bore_id"] for h in guide["auxiliary_holes"]["holes"]} == {b["bore_id"] for b in auxiliary if b["eligible"]}
    assert all(b["centerline_local_mm"] and b["axis_local"] for b in manifest["bores"] if b["eligible"])
    assert manifest["candidate_count"] == 49
    assert guide["parameters"]["truncation_margin_mm"] == 5
    assert manifest["source_provenance"]["source_plan_signature"] == guide["source_plan_signature"]
    changed = deepcopy(guide)
    changed["parameters"]["truncation_margin_mm"] = 0
    with pytest.raises(GuidePlacementError, match="design parameters changed"):
        verify_manufactured_geometry(changed)


def test_opt_in_density_retains_wall_and_default_geometry():
    default = normalize_guide_parameters({"auxiliary_density_profile": "standard_v1"})
    dense = normalize_guide_parameters({"auxiliary_density_profile": "continuation_dense_v1"})
    assert default["auxiliary_hole_ring_count"] == 2
    assert normalize_guide_parameters()["auxiliary_hole_ring_count"] == 4
    assert dense["auxiliary_hole_ring_count"] == 4
    for field in ("truncation_margin_mm", "channel_radius_mm", "plate_thickness_mm", "sleeve_outer_radius_mm"):
        assert dense[field] == DEFAULT_GUIDE_PARAMETERS[field]
    with pytest.raises(ValueError, match="Unknown"):
        normalize_guide_parameters({"auxiliary_density_profile": "unchecked_profile"})
    guides = [generate_surgical_guide(synthetic_agent(), {"geometry_resolution_mm": .5, "auxiliary_density_profile": profile})
              for profile in ("standard_v1", "continuation_dense_v1")]
    standard_bores = [b for b in guides[0]["bore_manifest"]["bores"] if b["eligible"] and b["kind"] == "auxiliary"]
    dense_bores = [b for b in guides[1]["bore_manifest"]["bores"] if b["eligible"] and b["kind"] == "auxiliary"]
    assert len(dense_bores) > len(standard_bores)
    assert guides[1]["auxiliary_holes"]["minimum_wall_mm"] == .35
    assert guides[1]["bore_manifest"]["mesh_sha256"] != guides[0]["bore_manifest"]["mesh_sha256"]
    # Reuse never changes an already-generated guide when a denser design is
    # generated separately; exact bytes still verify against the old manifest.
    verify_manufactured_geometry(guides[0])
    # The denser profile must add reachable current-target paths, not merely
    # requested cutters. This is synthetic geometric access, not clinical
    # benefit or a mechanical/guidance benchmark.
    agent = synthetic_agent()
    image = agent.memory.retrieve("ct_image")
    z, y, x = np.indices((64, 64, 64))
    ctv = (x - 32) ** 2 + (y - 32) ** 2 + (z - 32) ** 2 <= 18 ** 2
    context = CurrentCTGeometry(image, identity=image_geometry_identity(image, image_id="intra", image_revision="1"),
                                body_mask=agent.memory.retrieve("ct_data") > -300,
                                ctv_mask=ctv, oar_mask=np.zeros_like(ctv))
    profile = BoreValidationProfile("synthetic_density_access_v1", .5, 1., 0., 80.)
    useful_counts = []
    for guide in guides:
        placement = create_guide_placement(guide, np.eye(4), manufactured_guide_id="synthetic_print",
                                            target_image=context.identity, evidence={"source": "synthetic_direct_pose"})
        placement = review_guide_placement(placement, reviewer="synthetic", decision="accepted",
                                            profile_id="synthetic", evidence_reviewed=True, manufacturing_confirmed=True)
        result = initialize_bore_trajectories(guide, placement, context, profile=profile,
                                             fixed_seeds=[], in_situ_needles=[])
        useful_counts.append(len(result["candidates"]))
    assert useful_counts[1] > useful_counts[0]
