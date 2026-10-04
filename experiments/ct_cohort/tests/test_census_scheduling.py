"""Synthetic metadata-only scale/resume regressions. No patient/GPU work."""
from contextlib import contextmanager
import asyncio
import copy

import pytest

from brachycohort.core import Blocked, atomic_json, digest, load_json, sha256
from brachycohort.cohort import (SOFTWARE_ENDPOINT, build_frame, entry_for, execution_recipe,
                               load_frame, pending_cases, primary_endpoint, budget_preview)
from brachycohort.runner import endpoint
from test_protocol_and_collection import frozen_documents


def candidate(i, profile, cluster=None):
    row = {"row_id": f"r{i}", "dataset": "synthetic", "inference_cluster_id": cluster or f"c{i}",
           "ct_path": f"/source/ct-{i}.nii.gz", "label_path": f"/source/mask-{i}.nii.gz",
           "target_values": [2], "target_semantics": "research tumor", "target_hash": f"target{i}",
           "source_hashes": {"ct": f"ct{i}", "label": f"label{i}"},
           "derivative_recipe": {"kind": "supplied_union_no_margin"}}
    return row, profile, digest(profile), None


@pytest.fixture
def frame_cfg(tmp_path):
    cfg = {"experiment_id": "synthetic", "random_seed": 0, "model_recipe": {"test": True}}
    for name in ("manifest", "profiles", "case_approvals", "preflight_policy"):
        path = tmp_path / (name + ".json")
        atomic_json(path, {"synthetic": name})
        cfg[name + "_path"] = str(path)
    cfg.update(product_revision="test", budgets={"overall_s": 60})
    return cfg


def frozen(frame=None, identifiers=None, study="descriptive_stress"):
    protocol = {"row_ids": identifiers or [], "study_kind": study, "sampling_seed": 0,
                "arms": ["browser-chat"], "primary_endpoint": SOFTWARE_ENDPOINT}
    return {"protocol": protocol, "hash": "frozen", "governance": {"permitted_datasets": ["synthetic"]},
            **({"cohort_frame": frame} if frame else {})}


def record_terminal(storage, cfg, frozen, value, mode="browser-chat", **extra):
    row, profile, ph, _ = value
    rh = digest(execution_recipe(row, ph, cfg, mode, frozen))
    root = storage.path("runs/" + rh + "/attempt")
    atomic_json(root / "attempt.json", {"test": True})
    atomic_json(root / "terminal_result.json", {"recipe_hash": rh, "status": "FAILED", **extra})
    return root


def test_census_has_no_800_cap(storage, frame_cfg, approved_profile, monkeypatch):
    values = [candidate(i, approved_profile, f"cluster{i // 2}") for i in range(2400)]
    monkeypatch.setattr("brachycohort.runner.candidates", lambda *_: iter(reversed(values)))
    frame = build_frame(frame_cfg, storage)
    assert frame["allocated_rows"] == 2400 and frame["clusters"] == 1200
    assert frame["selection"]["limit"] is None
    assert frame["status"] == "DRAFT_REVIEW_REQUIRED"
    other = build_frame(frame_cfg, storage)
    assert frame["rows"] == other["rows"]
    assert build_frame(frame_cfg, storage, "one-per-cluster")["allocated_rows"] == 1200
    assert build_frame(frame_cfg, storage, limit=900)["allocated_rows"] == 900


def test_frame_pins_selection_and_inputs(storage, frame_cfg, approved_profile, monkeypatch):
    monkeypatch.setattr("brachycohort.runner.candidates", lambda *_: iter([candidate(1, approved_profile)]))
    frame = build_frame(frame_cfg, storage)
    path = storage.path("protocol/frame.json")
    atomic_json(path, frame)
    protocol = frozen()["protocol"]
    protocol["cohort_frame"] = {"path": str(path), "sha256": sha256(path)}
    assert load_frame(protocol, storage, frame_cfg)["allocated_rows"] == 1
    atomic_json(frame_cfg["profiles_path"], {"changed": True})
    with pytest.raises(Blocked, match="COHORT_FRAME_RECIPE_DRIFT"):
        load_frame(protocol, storage, frame_cfg)
    atomic_json(path, {**frame, "allocated_rows": 7})
    with pytest.raises(Blocked, match="COHORT_FRAME_CHANGED"):
        load_frame(protocol, storage, frame_cfg)


def test_census_gates_accept_frame_without_inline_800_row_list(storage, frame_cfg, frozen_documents, approved_profile, monkeypatch):
    from brachycohort.gates import gates
    cfg, documents, save = frozen_documents
    cfg.update(frame_cfg)
    cfg["budgets"] = {k: 60 for k in ("upload_s", "workflow_s", "guide_s", "report_s", "export_s", "overall_s")}
    monkeypatch.setattr("brachycohort.runner.candidates", lambda *_: iter([candidate(i, approved_profile) for i in range(901)]))
    frame = build_frame(cfg, storage)
    path = storage.path("protocol/frame.json")
    atomic_json(path, frame)
    documents["protocol"].update(study_kind="descriptive_stress", row_ids=[], sampling_seed=0,
        arms=["browser-chat"], primary_endpoint=SOFTWARE_ENDPOINT,
        cohort_frame={"path": str(path), "sha256": sha256(path)})
    save()
    before = gates(cfg, storage, execute=True)
    assert before["cohort_frame"]["allocated_rows"] == 901
    snapshot = storage.path("protocol/frozen-gates.json")
    stamp = snapshot.stat().st_mtime_ns
    assert gates(cfg, storage, execute=True)["hash"] == before["hash"]
    assert snapshot.stat().st_mtime_ns == stamp  # no repeated large NAS writes


def test_build_frame_never_silently_collapses_duplicate_rows(storage, frame_cfg, approved_profile, monkeypatch):
    value = candidate(1, approved_profile)
    monkeypatch.setattr("brachycohort.runner.candidates", lambda *_: iter([value, value]))
    with pytest.raises(Blocked, match="DUPLICATE_RESOLVED_ROW"):
        build_frame(frame_cfg, storage)


def test_pending_limit_advances_past_old_batch(storage, frame_cfg, approved_profile):
    values = [candidate(i, approved_profile) for i in range(4)]
    doc = frozen(identifiers=[v[0]["row_id"] for v in values])
    available = {v[0]["row_id"]: v for v in values}
    for value in values[:2]:
        record_terminal(storage, frame_cfg, doc, value)
    cases, skipped = pending_cases(frame_cfg, storage, doc, available, "browser-chat", 1)
    assert cases[0][0]["row_id"] == "r2" and skipped == 2
    record_terminal(storage, frame_cfg, doc, values[2])
    cases, _ = pending_cases(frame_cfg, storage, doc, available, "browser-chat", 1)
    assert cases[0][0]["row_id"] == "r3"


def test_incomplete_or_busy_attempt_blocks_blind_resume(storage, frame_cfg, approved_profile):
    value = candidate(1, approved_profile)
    doc = frozen(identifiers=["r1"])
    root = record_terminal(storage, frame_cfg, doc, value, cancellation_state="CANCEL_PENDING")
    with pytest.raises(Blocked, match="AUTHORITATIVE_RECONCILIATION_REQUIRED"):
        pending_cases(frame_cfg, storage, doc, {"r1": value}, "browser-chat")
    (root / "terminal_result.json").unlink()
    with pytest.raises(Blocked, match="AUTHORITATIVE_RECONCILIATION_REQUIRED"):
        pending_cases(frame_cfg, storage, doc, {"r1": value}, "browser-chat")


def test_partial_pair_only_dispatches_missing_arm(storage, frame_cfg, approved_profile):
    value = candidate(1, approved_profile)
    doc = frozen(identifiers=["r1"], study="paired_workflow")
    record_terminal(storage, frame_cfg, doc, value)
    cases, _ = pending_cases(frame_cfg, storage, doc, {"r1": value}, "paired", 1)
    assert cases[0][3] == ["manual-ui"]


def test_multiple_target_census_but_not_legacy_primary(storage, frame_cfg, approved_profile):
    values = [candidate(i, approved_profile, "same") for i in range(2)]
    available = {v[0]["row_id"]: v for v in values}
    frame = {"selection": {"target_policy": "all-targets"},
             "rows": [entry_for(*v[:3]) for v in values]}
    assert len(pending_cases(frame_cfg, storage, frozen(frame), available, "browser-chat")[0]) == 2
    with pytest.raises(Blocked, match="MULTIPLE_PRIMARY_TARGETS_PER_CLUSTER"):
        pending_cases(frame_cfg, storage, frozen(identifiers=list(available)), available, "browser-chat")


def test_frozen_row_hash_not_just_id(storage, frame_cfg, approved_profile):
    value = candidate(1, approved_profile)
    frame = {"selection": {"target_policy": "all-targets"}, "rows": [entry_for(*value[:3])]}
    changed = copy.deepcopy(value)
    changed[0]["target_values"] = [1]
    with pytest.raises(Blocked, match="FROZEN_RESOLVED_ROW_CHANGED"):
        pending_cases(frame_cfg, storage, frozen(frame), {"r1": changed}, "browser-chat")


def test_software_endpoint_does_not_claim_physics_or_review():
    required = ("target", "plan_geometry", "needle_geometry", "consumed_recipe", "freshness", "export_completeness",
                "dose_field", "guide_mesh", "pdf", "dvh_saved", "quality_evaluation", "within_budget", "source_preservation", "archive")
    checks = {k: {"status": "PASS"} for k in required}
    checks.update(qualified_artifact_review={"status": "UNKNOWN"}, independent_physics={"status": "UNKNOWN"})
    assert endpoint(checks, require_review=False) == "PASS"
    assert endpoint(checks) == "UNKNOWN"
    checks["dose_field"] = {"status": "FAIL"}
    assert endpoint(checks, require_review=False) == "FAIL"
    with pytest.raises(Blocked, match="PAIRED_REVIEW_ENDPOINT_REQUIRED"):
        primary_endpoint({"study_kind": "paired_workflow", "primary_endpoint": SOFTWARE_ENDPOINT})


def test_allocation_analysis_keeps_undispatched_targets(storage):
    from brachycohort.analysis import allocation_summary
    frame = {"rows": [{"row_id": f"r{i}", "dataset": "synthetic", "site": "test", "cluster_id": "c",
                       "ct_path": "/ct", "label_path": "/label", "target_values": [2]} for i in range(3)],
             "clusters": 1, "inference_unit": "target_run"}
    outcomes = [{"row_id": "r0", "arm": "browser-chat", "status": "SOFTWARE_SUCCESS", "workflow_completion": "PASS",
                 "software_completion": "PASS", "reviewed_completion": "UNKNOWN"}]
    storage.path("tables").mkdir()
    result = allocation_summary(storage, outcomes, {"arms": ["browser-chat"]}, frame)
    assert result["counts"] == {"PASS": 1, "NOT_STARTED": 2}
    assert result["allocated_clusters"] == 1 and result["allocated_targets"] == 3
    assert result["final"] is False
    assert "NOT_STARTED" in storage.path("tables/cohort_status.csv").read_text()


def test_projection_requires_real_positive_measurements(storage, frame_cfg, approved_profile):
    row, p, ph, _ = candidate(1, approved_profile)
    cases = [(row, p, ph, ["browser-chat"])]
    assert budget_preview(frame_cfg, storage, cases)["measured_projection"] is None
    result = budget_preview(frame_cfg, storage, cases, {"elapsed_s": [30, 60], "retained_bytes": [100, 200]})
    assert result["pending_attempts"] == 1 and result["feasibility_approved"] is False
    with pytest.raises(Blocked, match="INVALID_PILOT_BUDGET_MEASUREMENTS"):
        budget_preview(frame_cfg, storage, cases, {"elapsed_s": [float("nan")], "retained_bytes": [1]})


def test_run_counts_actual_pending_arms_not_requested_ceiling(storage, frozen_documents, approved_profile, monkeypatch):
    import brachycohort.runner as runner
    cfg, docs, save = frozen_documents
    cfg.update(experiment_id="test", product_revision="test", random_seed=0)
    docs["protocol"].update(study_kind="descriptive_stress", arms=["browser-chat"], row_ids=["r1", "r2"])
    docs["budget"]["max_attempts"] = 2
    save()
    @contextmanager
    def lease(*args, **kwargs):
        yield
    storage.lease = lease
    storage.initialize = lambda: None
    values = [candidate(i, approved_profile) for i in (1, 2)]
    monkeypatch.setattr(runner, "candidates", lambda *_: iter(values))
    monkeypatch.setattr(runner, "validate_live_service", lambda *_: None)
    monkeypatch.setattr(runner, "validate_account_quota", lambda *_: None)
    called = []
    async def fake_attempt(cfg, storage, row, profile, ph, mode, frozen):
        value = next(v for v in values if v[0]["row_id"] == row["row_id"])
        record_terminal(storage, cfg, frozen, value, mode)
        called.append(row["row_id"])
        return {"attempt_id": row["row_id"], "status": "FAILED"}
    monkeypatch.setattr(runner, "attempt", fake_attempt)
    assert asyncio.run(runner.run(cfg, storage, 1))["new_attempts"] == 1
    assert asyncio.run(runner.run(cfg, storage, 100))["new_attempts"] == 1
    assert called == ["r1", "r2"]
    assert asyncio.run(runner.run(cfg, storage, None))["new_attempts"] == 0
