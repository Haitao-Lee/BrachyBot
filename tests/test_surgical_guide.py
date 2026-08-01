"""Geometry regressions for the native patient-specific puncture guide."""

from __future__ import annotations

import numpy as np
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
