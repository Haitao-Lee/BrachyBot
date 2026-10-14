"""Real tool dispatch, durable guide discovery, and owned candidate publication."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from agent_runtime.core import AgentMemory, ToolResultPipeline
from test_guide_bore_manifest import synthetic_agent, tube_guide
from tool_factory.surgical_guide import SurgicalGuideTool
from web.guide_placement import verify_manufactured_geometry
from web.guide_service import guide_manifest_page, guide_manifest_summary
from web.planning_runs import begin_planning_run
from web.workspace_store import WorkspaceStore


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("guide_service_owner", "synthetic_hash")
    sid = store.create_session(user["id"], "Synthetic guide workspace").id
    agent = SimpleNamespace(memory=AgentMemory(sid), config={
        "_workspace_owner_id": user["id"], "_workspace_session_id": sid,
    }, _workspace_store=store)
    return store, user["id"], sid, agent


def create_timepoint(store, owner, sid, title, **kwargs):
    catalog = store.list_timepoints(owner, sid)
    return store.create_timepoint(owner, sid, title,
                                   expected_revision=catalog["catalog_revision"], **kwargs)["created_timepoint_id"]


def saved_guide():
    guide = tube_guide()
    guide.update({"version": 1, "status": "ready", "parameters": {},
                  "selected_needle_ids": [], "planning_id": "source_plan"})
    for key in ("geometry_id", "mesh_sha256", "stl_sha256"):
        guide[key] = guide["bore_manifest"][key]
    return guide


@pytest.fixture
def scoped(owned):
    store, owner, sid, agent = owned
    source = create_timepoint(store, owner, sid, "Preoperative guide")
    guide = saved_guide()
    store.save_timepoint_results(owner, sid, source,
                                  {"surgical_guide": guide, "surgical_guide_versions": [guide]}, expected_state_revision=0)
    target = create_timepoint(store, owner, sid, "Current intraoperative CT",
                              stage="intraoperative", preoperative_timepoint_id=source)
    store.save_timepoint_results(owner, sid, target, {
        "ct_data": np.arange(512, dtype=np.int16).reshape(8, 8, 8),
        "ct_spacing": (.5, 1., 2.), "ct_origin": (11., 22., 33.),
        "ct_direction": (0., -1., 0., 1., 0., 0., 0., 0., 1.),
    }, expected_state_revision=0)
    return store, owner, sid, agent, source, target


def estimate(tool, source, target, **patch):
    request = {"method": "manual_rigid", "manufactured_guide_id": "declared_synthetic_print",
               "expected_state_revision": 1, "matrix": np.eye(4).tolist(),
               "evidence_source": "synthetic_direct_marker_observation"}
    request.update(patch)
    return tool.execute(action="estimate_placement", source_timepoint_id=source, timepoint_id=target,
                         guide_version=1, placement=request)


def test_schema_exposes_real_design_discovery_and_candidate_actions():
    tool = SurgicalGuideTool()
    schema = tool.input_schema["properties"]
    assert schema["parameters"]["properties"]["auxiliary_density_profile"]["enum"] == ["standard_v1", "continuation_dense_v1"]
    assert {"manifest", "estimate_placement", "validate_placement"} <= set(schema["action"]["enum"])
    assert schema["placement"]["properties"]["max_residual_mm"].get("default") is None
    assert "manufactured_guide_metadata" in tool.output_schema["properties"]


def test_actual_generation_dense_manifest_survives_planning_and_cold_restore(owned):
    store, owner, sid, agent = owned
    planning = begin_planning_run(agent, step="full", force_new=True)
    for key, value in synthetic_agent().memory.values.items():
        agent.memory.store(key, value)
    result = SurgicalGuideTool(agent).execute(action="generate", parameters={
        "geometry_resolution_mm": .5, "auxiliary_density_profile": "continuation_dense_v1",
    })
    assert result.success, result.error
    guide = agent.memory.retrieve("surgical_guide")
    manifest = verify_manufactured_geometry(guide)
    assert guide["parameters"]["auxiliary_hole_ring_count"] == 4
    assert guide["parameters"]["truncation_margin_mm"] == 5
    assert manifest["minimum_wall_policy_mm"] == .35
    assert result.metadata["manufactured_guide_metadata"]["eligible_bore_count"] == manifest["realized_count"]
    assert result.metadata["manufactured_guide_metadata"]["manufacturing_confirmation"] == "not_recorded"
    assert agent.memory.retrieve("planning_run:" + planning)["surgical_guide"]["bore_manifest"] == manifest
    store.snapshot_agent(owner, sid, agent, reason="synthetic_guide_tool_contract")
    restored = SimpleNamespace(memory=AgentMemory(sid), config=deepcopy(agent.config), _workspace_store=store)
    store.hydrate_agent(owner, sid, restored)
    restored_guide = restored.memory.retrieve("surgical_guide")
    assert verify_manufactured_geometry(restored_guide) == manifest
    assert np.array_equal(restored_guide["vertices"], guide["vertices"])
    page = SurgicalGuideTool(restored).execute(action="manifest", guide_version=1, bore_limit=4)
    assert page.success, page.error
    assert page.data["total"] == manifest["candidate_count"]
    assert len(page.data["bores"]) == 4 and page.data["next_offset"] == 4
    assert "eligible_bore_count" in ToolResultPipeline.format("surgical_guide", page)
    assert "vertices" not in page.data and "faces" not in page.data


def test_status_analyze_manifest_are_read_only_and_expose_limits():
    agent = SimpleNamespace(memory=AgentMemory())
    guide = saved_guide()
    agent.memory.store("surgical_guide", guide)
    before = deepcopy(agent.memory._planning_versions)
    tool = SurgicalGuideTool(agent)
    for action in ("status", "analyze", "manifest"):
        result = tool.execute(action=action)
        assert result.success, result.error
        summary = result.metadata["manufactured_guide_metadata"]
        assert summary["manifest_available"]
        assert summary["mesh_identity_checked"] is False
        assert summary["physical_placement"] == "not_established"
    assert agent.memory._planning_versions == before
    assert guide["bore_manifest"]["manufacturing_confirmation"] == "not_recorded"


def test_legacy_manifest_is_unknown_and_does_not_invent_bores():
    agent = SimpleNamespace(memory=AgentMemory())
    agent.memory.store("surgical_guide", {"version": 1, "status": "ready",
                                           "auxiliary_holes": {"holes": [{"center_world_mm": [0, 0, 0]}]}})
    result = SurgicalGuideTool(agent).execute(action="manifest")
    assert result.success
    assert result.data["bores"] == []
    assert not result.data["summary"]["manifest_available"]
    assert not result.data["summary"]["legacy_center_only_eligible"]
    damaged = saved_guide()
    damaged["bore_manifest"]["bores"][0]["eligible"] = False
    assert guide_manifest_summary(damaged)["reason"] == "invalid_manifest_identity"


@pytest.mark.parametrize("offset,limit", [(-1, 20), (0, 0), (0, 33), (True, 10)])
def test_manifest_pagination_is_bounded(offset, limit):
    with pytest.raises(ValueError):
        guide_manifest_page(saved_guide(), offset=offset, limit=limit)


def test_scoped_manifest_reads_saved_source_without_mutation(scoped):
    store, owner, sid, agent, source, _ = scoped
    before = store.list_timepoints(owner, sid)
    result = SurgicalGuideTool(agent).execute(action="manifest", source_timepoint_id=source, guide_version=1)
    assert result.success, result.error
    assert result.data["scope"]["source_timepoint_id"] == source
    assert result.data["summary"]["manifest_available"]
    assert store.list_timepoints(owner, sid) == before


def test_actual_tool_publishes_pending_pose_only_to_named_target(scoped):
    store, owner, sid, agent, source, target = scoped
    source_before = store.load_timepoint_snapshot(owner, sid, source, decode_arrays=True)
    memory_before = deepcopy(agent.memory.planning_results)
    tool = SurgicalGuideTool(agent)
    result = estimate(tool, source, target)
    assert result.success, result.error
    candidate = result.data["placement"]
    assert candidate["review_state"] == "pending" and candidate["review"] is None
    assert result.data["saved_state_revision"] == 2
    assert result.data["clinical_use_approved"] is False
    saved = store.load_timepoint_snapshot(owner, sid, target)
    assert saved["agent"]["planning_results"]["guide_placement_candidates"][candidate["placement_id"]] == candidate
    assert candidate["target_image"]["image_id"] == "ct_data:" + target
    assert agent.memory.planning_results == memory_before
    source_after = store.load_timepoint_snapshot(owner, sid, source, decode_arrays=True)
    before_guide = source_before["agent"]["planning_results"]["surgical_guide"]
    after_guide = source_after["agent"]["planning_results"]["surgical_guide"]
    assert verify_manufactured_geometry(before_guide) == verify_manufactured_geometry(after_guide)
    assert np.array_equal(before_guide["vertices"], after_guide["vertices"])
    catalog_before = store.list_timepoints(owner, sid)
    validated = tool.execute(action="validate_placement", source_timepoint_id=source, timepoint_id=target,
                              guide_version=1, placement_id=candidate["placement_id"])
    assert validated.success, validated.error
    assert validated.data["proper_rigid"] and validated.data["target_image_checked"]
    assert validated.data["review_state"] == "pending" and not validated.data["clinical_use_approved"]
    assert store.list_timepoints(owner, sid) == catalog_before


def test_landmark_candidate_is_fitted_and_persisted(scoped):
    store, owner, sid, agent, source, target = scoped
    points = np.array([[0., 0., 0.], [3., 0., 0.], [0., 3., 0.], [0., 0., 3.]])
    result = estimate(SurgicalGuideTool(agent), source, target, method="landmarks", matrix=None,
                       source_landmarks=points.tolist(), target_landmarks=(points + [1, 2, 3]).tolist(),
                       max_residual_mm=.01)
    assert result.success, result.error
    assert np.allclose(np.array(result.data["placement"]["matrix"])[:3, 3], [1, 2, 3])
    assert result.data["placement"]["qc"]["landmark_count"] == 4


def test_stale_candidate_write_and_nonrigid_matrix_do_not_publish(scoped):
    store, owner, sid, agent, source, target = scoped
    tool = SurgicalGuideTool(agent)
    before = store.list_timepoints(owner, sid)
    assert not estimate(tool, source, target, expected_state_revision=0).success
    scaled = np.eye(4)
    scaled[0, 0] = 1.1
    assert not estimate(tool, source, target, matrix=scaled.tolist()).success
    assert not estimate(tool, source, target, evidence_source="").success
    assert store.list_timepoints(owner, sid) == before
    assert "guide_placement_candidates" not in store.load_timepoint_snapshot(owner, sid, target)["agent"]["planning_results"]


def test_current_ct_change_invalidates_stored_pose(scoped):
    store, owner, sid, agent, source, target = scoped
    tool = SurgicalGuideTool(agent)
    result = estimate(tool, source, target)
    assert result.success, result.error
    store.save_timepoint_results(owner, sid, target, {"ct_origin": [12., 22., 33.]}, expected_state_revision=2)
    check = tool.execute(action="validate_placement", source_timepoint_id=source, timepoint_id=target,
                           guide_version=1, placement_id=result.data["placement"]["placement_id"])
    assert not check.success
    assert "target CT changed" in check.error


def test_missing_current_ct_and_multi_image_selection_fail_closed(scoped):
    store, owner, sid, agent, source, target = scoped
    store.save_timepoint_results(owner, sid, target, {}, removals=("ct_origin",), expected_state_revision=1)
    tool = SurgicalGuideTool(agent)
    missing = estimate(tool, source, target, expected_state_revision=2)
    assert not missing.success and "current target ct" in missing.error.lower()
    store.save_timepoint_results(owner, sid, target, {"ct_origin": [11., 22., 33.],
                                                      "images": [{"image_id": "one"}, {"image_id": "two"}]},
                                  expected_state_revision=2)
    ambiguous = estimate(tool, source, target, expected_state_revision=3)
    assert not ambiguous.success and "planning reference image" in ambiguous.error
    assert "guide_placement_candidates" not in store.load_timepoint_snapshot(owner, sid, target)["agent"]["planning_results"]


def test_pose_operation_does_not_decode_unrelated_dose_arrays(scoped, monkeypatch):
    store, owner, sid, agent, source, target = scoped
    import web.workspace_store as workspace

    store.save_timepoint_results(owner, sid, target, {"unrelated_dose": {"$unsupported": "must_remain_encoded"}},
                                  expected_state_revision=1)
    original = workspace._decode_artifacts
    def guarded(value, root, *args, **kwargs):
        if isinstance(value, dict) and ("unrelated_dose" in value or value.get("$unsupported") == "must_remain_encoded"):
            raise AssertionError("A pose operation must not decode unrelated timepoint clinical arrays")
        return original(value, root, *args, **kwargs)
    monkeypatch.setattr(workspace, "_decode_artifacts", guarded)
    result = estimate(SurgicalGuideTool(agent), source, target, expected_state_revision=2)
    assert result.success, result.error


def test_source_changed_in_another_process_before_pose_commit_is_rejected(scoped, monkeypatch):
    from web.guide_service import GuidePlacementService
    store, owner, sid, agent, source, target = scoped
    other = WorkspaceStore(store.runtime_dir)
    original = GuidePlacementService._target_image
    def race(service, snapshot):
        result = original(service, snapshot)
        other.save_timepoint_results(owner, sid, source, {"source_geometry_revision": 2}, expected_clinical_revision=1)
        return result
    monkeypatch.setattr(GuidePlacementService, "_target_image", race)
    result = estimate(SurgicalGuideTool(agent), source, target)
    assert not result.success
    assert "inputs changed" in result.error
    assert not store.load_timepoint_snapshot(owner, sid, target)["agent"]["planning_results"].get("guide_placement_candidates")


def test_cross_owner_source_and_cross_timepoint_candidate_are_rejected(scoped):
    store, owner, sid, agent, source, target = scoped
    tool = SurgicalGuideTool(agent)
    foreign_sid = store.create_session(owner, "Other Session").id
    foreign = create_timepoint(store, owner, foreign_sid, "Foreign source")
    assert not tool.execute(action="manifest", source_timepoint_id=foreign, guide_version=1).success
    wrong_source = create_timepoint(store, owner, sid, "Unlinked source")
    assert not estimate(tool, wrong_source, target).success
    other_owner = store.create_user("other_guide_owner", "synthetic_hash")["id"]
    foreign_agent = SimpleNamespace(memory=AgentMemory(), config={
        "_workspace_owner_id": other_owner, "_workspace_session_id": sid,
    }, _workspace_store=store)
    assert not SurgicalGuideTool(foreign_agent).execute(action="manifest", source_timepoint_id=source, guide_version=1).success
    assert not tool.execute(action="manifest", source_timepoint_id=source, guide_version=1, owner_id=other_owner).success


def test_multitimepoint_generation_scope_and_analysis_effect_ceiling(scoped, monkeypatch):
    store, owner, sid, agent, source, target = scoped
    import web.surgical_guide as core

    def forbidden_generation(*args, **kwargs):
        raise AssertionError("Generation must not run for these requests")
    monkeypatch.setattr(core, "generate_surgical_guide", forbidden_generation)
    tool = SurgicalGuideTool(agent)
    assert not tool.execute(action="generate").success
    assert not tool.execute(action="generate", timepoint_id=target).success
    assert not tool.execute(action="analyze", placement={"method": "manual_rigid"}).success
    assert not tool.execute(action="manifest", parameters={"auxiliary_density_profile": "continuation_dense_v1"}).success
    assert not tool.execute(action="estimate_placement", source_timepoint_id=source, timepoint_id=target,
                             guide_version=1, placement={"method": "manual_rigid", "expected_state_revision": 1,
                                                         "manufactured_guide_id": "x", "review_state": "accepted"}).success
