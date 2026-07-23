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


def test_agent_tool_uses_the_same_versioned_guide_contract_as_the_web_route():
    agent = _synthetic_agent()
    result = SurgicalGuideTool(agent).execute(action="generate", parameters={"channel_radius_mm": 1.3})
    assert result.success is True
    assert result.metadata["guide"]["version"] == 1
    assert guide_version_summaries(agent)[0]["version"] == 1
