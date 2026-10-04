import copy
import json
from datetime import datetime, timedelta, timezone
import pytest

from brachycohort.core import Blocked, atomic_json, digest, sha256
from brachycohort.gates import gates, approved_row
from brachycohort.runner import consumed_recipe, fingerprint, original_sources_unchanged
from brachycohort.analysis import analyze, paired_cluster_summary, results
from brachycohort.verify import mesh


@pytest.fixture
def frozen_documents(storage, tmp_path):
    documents = {
        "governance": {"status": "APPROVED", "institutional_determination": "synthetic", "data_steward": "test",
            "nas_server_acl_verified": True, "permitted_datasets": ["synthetic"], "model_data_flow_approved": True},
        "protocol": {"status": "FROZEN", "study_kind": "paired_workflow", "investigator": "test", "frozen_at": "test",
            "sampling_seed": 0, "row_ids": ["r1"], "arms": ["browser-chat", "manual-ui"], "analysis": "test", "sample_size_basis": "test"},
        "acceptance_rules": {"status": "FROZEN", "reviewer": "test", "frozen_at": "test", "guide_checks": ["topology"],
            "report_checks": ["readability"], "criteria": {k: {"method": "test", "pass_rule": "test", "owner": "test", "evidence_requirement": "test"} for k in ("topology", "readability")}},
        "budget": {"status": "APPROVED", "owner": "test", "max_attempts": 2, "max_retained_bytes": 100000,
            "approved_account_quota_bytes": 100000, "deadline_utc": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}}
    cfg = {"max_experiment_bytes": 100000, "model_recipe": {"name": "test"},
           "budgets": {k: 60 for k in ("upload_s", "workflow_s", "guide_s", "report_s", "export_s", "overall_s")}}
    def save():
        for name, value in documents.items():
            path = tmp_path / (name + ".json")
            atomic_json(path, value)
            cfg[name + "_path"] = str(path)
        return cfg
    save()
    return cfg, documents, save


def test_frozen_drift_and_seed_zero(storage, frozen_documents):
    cfg, docs, save = frozen_documents
    assert gates(cfg, storage, execute=True)["hash"]
    docs["protocol"]["investigator"] = "other"
    save()
    with pytest.raises(Blocked, match="FROZEN_PROTOCOL_DRIFT"):
        gates(cfg, storage, execute=True)


def test_post_run_review_does_not_reopen_expired_execution(storage, frozen_documents):
    cfg, docs, save = frozen_documents
    docs["budget"]["deadline_utc"] = "2000-01-01T00:00:00Z"
    save()
    with pytest.raises(Blocked, match="RESOURCE_DEADLINE_EXPIRED"):
        gates(cfg, storage)
    assert gates(cfg, storage, enforce_deadline=False)["hash"]


@pytest.mark.parametrize("document,key,value", [
    ("governance", "nas_server_acl_verified", "false"), ("governance", "model_data_flow_approved", "false"),
    ("protocol", "status", "DRAFT"), ("protocol", "row_ids", []), ("protocol", "row_ids", ["r", "r"]),
    ("protocol", "sampling_seed", True), ("acceptance_rules", "criteria", {}),
    ("budget", "max_attempts", -1), ("budget", "max_retained_bytes", True),
    ("budget", "deadline_utc", "2000-01-01T00:00:00Z")])
def test_closed_or_incomplete_protocol(storage, frozen_documents, document, key, value):
    cfg, docs, save = frozen_documents
    docs[document][key] = value
    save()
    with pytest.raises(Blocked):
        gates(cfg, storage)


def test_approval_target_hash_is_not_optional():
    row = {"row_id": "r", "target_hash": "a", "source_hashes": {"ct": "b"}, "ct_content_hash": "c"}
    receipt = {"status": "APPROVED_RESEARCH", "reviewer": "test", "reviewed_at": "test", "target_hash": "wrong", "source_hashes": {"ct": "b"}, "profile_id": "p"}
    with pytest.raises(Blocked, match="CASE_APPROVAL_SOURCE_MISMATCH"):
        approved_row(row, receipt)


def provenance(profile):
    return {"planning_provenance": {"input_paths": {"ctv_effective": {"object_ids": ["mask:1"], "mask": {"sha256": "f"}}},
            "parameters": {"in_lowest_dose_gy": 42, "out_highest_dose_gy": 84, "DVH_rate": .8, "max_iter": 2}, "mode": "rl"},
            "plan_config": {"effective_mode": "rl"}}


def test_consumed_not_just_requested(approved_profile):
    state = provenance(approved_profile)
    row = {"observed_target_fingerprint": "f"}
    assert consumed_recipe(state, row, approved_profile, ["mask:1"])["status"] == "PASS"
    state["planning_provenance"]["parameters"]["in_lowest_dose_gy"] = 120
    assert consumed_recipe(state, row, approved_profile, ["mask:1"])["status"] == "FAIL"


@pytest.mark.parametrize("change", ["wrong_target", "missing_parameters", "missing_effective", "fallback"])
def test_incomplete_or_wrong_provenance_never_passes(approved_profile, change):
    state = provenance(approved_profile)
    if change == "wrong_target":
        state["planning_provenance"]["input_paths"]["ctv_effective"]["object_ids"] = ["other"]
    elif change == "missing_parameters":
        state["planning_provenance"]["parameters"] = {}
    elif change == "missing_effective":
        state["plan_config"] = {}
    else:
        state["plan_config"]["effective_mode"] = "rule_based_fallback"
    assert consumed_recipe(state, {"observed_target_fingerprint": "f"}, approved_profile, ["mask:1"])["status"] != "PASS"


def test_normal_stl_triangle_vertices_are_not_false_failure(tmp_path):
    import trimesh
    path = tmp_path / "cube.stl"
    trimesh.creation.box().export(path)
    assert mesh(path)["status"] == "PASS"
    m = trimesh.creation.box()
    m.update_faces(list(range(len(m.faces) - 1)))
    m.export(path)
    assert mesh(path)["status"] == "FAIL"


def test_missing_terminal_retained_in_denominator(storage):
    path = storage.path("runs/rh/a/attempt.json")
    atomic_json(path, {"recipe_hash": "rh", "recipe": {"arm": "browser-chat"},
                      "row": {"row_id": "r", "dataset": "synthetic", "inference_cluster_id": "c"}})
    values = results(storage.base)
    assert len(values) == 1 and values[0]["status"] == "INCOMPLETE"
    report = analyze(storage)
    assert report["attempts"] == report["unfinished_attempts"] == 1
    assert report["strata"][0]["verified_success"] == 0
    for name in ("seeds", "needles", "oar_metrics", "target_metrics", "resources", "stage_times"):
        assert storage.path("tables/" + name + ".csv").is_file()


def test_retry_not_silently_added_to_primary():
    row = {"cluster_id": "c", "arm": "browser-chat", "workflow_completion": "PASS"}
    assert paired_cluster_summary([row, row])["status"] == "BLOCKED"
