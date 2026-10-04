"""Sequential GPU/account scheduling, first-attempt outcomes and safe resume."""
from __future__ import annotations
import asyncio
import json
import os
import time
import uuid
from collections import Counter
from pathlib import Path

from .browser import Browser
from .core import Blocked, Journal, atomic_json, digest, load_json, sha256, source_digest, sanitize, utc
from .gates import approved_row, approvals, gates
from .observer import copy_workspace, workspace, verify_effective_target, decode
from .preflight import records
from .profiles import applicable, prompt
from .runtime import validate_runtime, validate_live_service, validate_account_quota
from .verify import (archive_manifest, check, dose_field, geometry, metrics_from_field, mesh, pdf,
                     review, unzip_verified, verify_archive)
from .cohort import SOFTWARE_ENDPOINT, primary_endpoint, pending_cases, budget_preview


def candidates(cfg, storage):
    catalog = load_json(cfg["profiles_path"])
    profiles = catalog["profiles"]
    ids = [p["id"] for p in profiles]
    if len(ids) != len(set(ids)):
        raise Blocked("DUPLICATE_PROFILE_ID")
    by_id = {p["id"]: p for p in profiles}
    approvals_by_id = approvals(cfg.get("case_approvals_path"))
    for path in sorted(storage.path("resolved").glob("*.json")):
        row = load_json(path)
        try:
            if row.get("preflight_status") != "PASS":
                raise Blocked("PREFLIGHT_NOT_PASS")
            row = approved_row(row, approvals_by_id.get(row["row_id"]))
            profile = by_id.get(row["planning_profile_id"])
            if not profile:
                raise Blocked("PROFILE_UNRESOLVED")
            ph = applicable(row, profile)
            model = cfg.get("model_recipe") or {}
            if model.get("dose_engine") != profile["engine"] or model.get("source") != profile["source"]:
                raise Blocked("PROFILE_DEPLOYED_ENGINE_OR_SOURCE_MISMATCH")
            if not any(a.get("sha256") == profile["engine"]["weights_sha256"] for a in cfg.get("model_assets", [])):
                raise Blocked("PROFILE_WEIGHTS_NOT_PINNED")
            yield row, profile, ph, None
        except Blocked as exc:
            yield row, None, None, exc.code


def recipe(row, profile_hash, cfg, arm):
    return {"schema_version": 1, "row_id": row["row_id"], "source_hashes": row["source_hashes"],
            "target_hash": row["target_hash"], "profile_hash": profile_hash, "arm": arm,
            "product_revision": cfg["product_revision"], "schedule_seed": cfg["random_seed"],
            "prompt_version": "fixed-supplied-target-v1", "experiment_id": cfg["experiment_id"],
            "model_recipe": cfg.get("model_recipe"), "derivative_recipe": row["derivative_recipe"],
            "budgets": cfg["budgets"]}


def original_sources_unchanged(row):
    if source_digest(row["ct_path"]) != row["source_hashes"]["ct"] or source_digest(row["label_path"]) != row["source_hashes"]["label"]:
        raise Blocked("SOURCE_CHANGED_AFTER_PREFLIGHT")
    if sha256(row["derived_label_path"]) != row["derived_label_sha256"]:
        raise Blocked("TARGET_DERIVATIVE_CHANGED")
    if sha256(row["derived_ct_path"]) != row["derived_ct_sha256"]:
        raise Blocked("CT_DERIVATIVE_CHANGED")
    if "pet" in row["source_hashes"] and source_digest(row["pet_series_path"]) != row["source_hashes"]["pet"]:
        raise Blocked("PET_SOURCE_CHANGED_AFTER_PREFLIGHT")


def fingerprint(array):
    import hashlib
    import numpy as np
    a = np.ascontiguousarray(array)
    h = hashlib.sha256()
    h.update(str(a.dtype).encode())
    h.update(json.dumps(list(a.shape), separators=(",", ":")).encode())
    h.update(a.tobytes(order="C"))
    return h.hexdigest()


def consumed_recipe(state, row, profile, selected):
    """Verify consumed config/provenance, not only the UI inputs or requested text."""
    provenance = state.get("planning_provenance") or state.get("planning_request_provenance")
    if provenance is None:
        runs = state.get("planning_runs") or []
        if isinstance(runs, dict):
            runs = list(runs.values())
        active = str(state.get("manual_planning_id") or state.get("planning_id") or "")
        matching = [r for r in runs if str(r.get("planning_id") or "") == active]
        if len(matching) == 1:
            revision = matching[0].get("input_revision") or {}
            provenance = matching[0].get("provenance") or matching[0].get("planning_provenance") or {
                "parameters": revision.get("planning_parameters"), "input_paths": revision,
                "mode": revision.get("mode"), "planning_fingerprint": revision.get("planning_fingerprint")}
    if not isinstance(provenance, dict):
        return check("UNKNOWN", "CONSUMED_RECIPE_PROVENANCE_MISSING")
    source = provenance.get("input_paths", {}).get("ctv_effective") or provenance.get("input_provenance", {}).get("ctv_effective") or provenance.get("ctv_effective")
    if not source:
        source = provenance.get("inputs", {}).get("ctv_effective")
    if not isinstance(source, dict) or set(source.get("object_ids", [])) != set(selected):
        return check("FAIL", "CONSUMED_TARGET_SOURCE_MISMATCH")
    expected_consumed_hash = row.get("observed_target_fingerprint")
    if not expected_consumed_hash:
        return check("UNKNOWN", "CONSUMED_TARGET_OBSERVATION_MISSING")
    if source.get("mask", {}).get("sha256") != expected_consumed_hash:
        return check("FAIL", "CONSUMED_TARGET_FINGERPRINT_MISMATCH")
    params = provenance.get("parameters", {})
    settings = profile["settings"]
    for names, expected in ((["in_lowest_dose_gy", "in_lowest_energy"], settings["prescription_gy"]),
                            (["out_highest_dose_gy", "out_highest_energy"], settings["upper_dose_gy"]),
                            (["DVH_rate"], settings["coverage_fraction"]), (["max_iter"], settings["max_iterations"])):
        actual = next((params[n] for n in names if n in params), None)
        if actual is None:
            return check("UNKNOWN", "CONSUMED_SETTING_MISSING", field=names[0])
        if actual != expected:
            return check("FAIL", "CONSUMED_SETTING_MISMATCH", field=names[0], observed=actual, expected=expected)
    if provenance.get("mode") != settings["mode"]:
        return check("FAIL", "CONSUMED_MODE_MISMATCH", observed=provenance.get("mode"))
    actual = state.get("plan_config") or {}
    if not actual.get("effective_mode"):
        return check("UNKNOWN", "EFFECTIVE_MODE_NOT_OBSERVED")
    if actual["effective_mode"] != settings["mode"]:
        return check("FAIL", "UNREGISTERED_PLANNER_FALLBACK", observed=actual["effective_mode"])
    return check("PASS", provenance=sanitize(provenance), evidence_level="internal_consistency")


def normalize_needles(rows):
    return [{**r, "entry": r.get("entry") or r.get("entry_point"),
             "tip": r.get("tip") or r.get("tip_point") or r.get("target")} for r in rows]


def collect(root, row, profile, result, export, state, selected, cfg, recipe_hash, acceptance):
    checks = {}
    checks["plan_geometry"] = geometry(result.get("seeds"), ["pos"])
    checks["needle_geometry"] = geometry(normalize_needles(result.get("needles") or []), ["entry", "tip"])
    checks["consumed_recipe"] = consumed_recipe(state, row, profile, selected)
    manifest, exported_root = export
    if manifest.get("session_id") != result.get("experiment_session_id") or not manifest.get("planning_id"):
        checks["freshness"] = check("FAIL", "EXPORT_IDENTITY_MISMATCH")
    elif manifest.get("planning_id") != result.get("planning_id") or manifest.get("data_version") != result.get("planning_data_version"):
        checks["freshness"] = check("FAIL", "EXPORT_PLANNING_VERSION_MISMATCH")
    elif any(v in {"stale", "pending", "failed", "invalid"} for v in result.get("artifact_status", {}).values() if isinstance(v, str)):
        checks["freshness"] = check("FAIL", "STALE_DEPENDENT_ARTIFACT")
    else:
        checks["freshness"] = check("PASS", evidence_level="internal_consistency")
    exported = manifest.get("files", [])
    types = Counter(e.get("data_type") for e in exported)
    checks["export_completeness"] = check("FAIL" if manifest.get("failures") or manifest.get("skipped") else "PASS",
                                          failures=manifest.get("failures", []), skipped=manifest.get("skipped", []), types=dict(types))
    doses = [e for e in exported if e.get("data_type") == "dose"]
    guides = [e for e in exported if e.get("data_type") == "surgical_guide"]
    if len(doses) == 1:
        path = Path(exported_root) / doses[0]["relative_path"]
        checks["dose_field"] = dose_field(path, row["derived_ct_path"])
        checks["proxy_metrics"] = metrics_from_field(path, row["derived_label_path"], profile["settings"]["prescription_gy"])
    else:
        checks["dose_field"] = check("FAIL", "CURRENT_DOSE_EXPORT_NOT_UNIQUE")
    checks["guide_mesh"] = mesh(Path(exported_root) / guides[0]["relative_path"]) if len(guides) == 1 else check("FAIL", "CURRENT_GUIDE_EXPORT_NOT_UNIQUE")
    checks["pdf"] = pdf(Path(root) / "report.pdf", cfg.get("minimum_pdf_pages", 1)) if (Path(root) / "report.pdf").exists() else check("FAIL", "PDF_MISSING")
    checks["dvh_saved"] = check("PASS" if result.get("dvh") else "FAIL", None if result.get("dvh") else "DVH_MISSING")
    checks["quality_evaluation"] = check("PASS" if types.get("quality_check") else "UNKNOWN",
                                        None if types.get("quality_check") else "QUALITY_EVALUATION_EXPORT_MISSING")
    atomic_json(Path(root) / "engine_execution.json", sanitize(state.get("plan_config") or {}))
    metrics = result.get("metrics") or {}
    oar = metrics.get("oar_metrics") or metrics.get("organ_metrics") or state.get("oar_dose_metrics") or {}
    atomic_json(Path(root) / "target_metrics.json", {"raw": metrics, "proxy_recalculation": checks.get("proxy_metrics"),
                "CI_definition": "product_custom_v100_fraction_squared", "HI_definition": "product_custom_(Dmax-Rx)/Rx",
                "D2_definition": "dose_to_2_percent_target_not_2cc", "physical_dose_validation": "NOT_ESTABLISHED"})
    atomic_json(Path(root) / "oar_metrics.json", {"raw": sanitize(oar), "missing_if_empty": True,
                "constraints": profile["oar_policy"].get("constraints", []), "clinical_acceptance": "UNKNOWN"})
    atomic_json(Path(root) / "plan_geometry.json", {"seeds": result.get("seeds"), "needles": result.get("needles"),
                "trajectories": result.get("trajectories"), "coordinates": "LPS_mm"})
    artifacts = archive_manifest(root)
    review_path = cfg.get("review_directory")
    if review_path:
        review_path = Path(review_path) / (recipe_hash + ".json")
    required = acceptance["guide_checks"] + acceptance["report_checks"]
    checks["qualified_artifact_review"] = review(review_path, recipe_hash, artifacts, required,
                                               digest(acceptance), Path(root).name)
    checks["clinical_quality"] = check("UNKNOWN", "RESEARCH_SOFTWARE_ENDPOINT_NOT_CLINICAL_APPROVAL")
    checks["independent_physics"] = check("UNKNOWN", "REFERENCE_SUBSTUDY_NOT_RUN")
    return checks


def endpoint(checks, require_review=True):
    required = ("target", "plan_geometry", "needle_geometry", "consumed_recipe", "freshness", "export_completeness",
                "dose_field", "guide_mesh", "pdf", "dvh_saved", "quality_evaluation", "within_budget", "source_preservation", "archive")
    if require_review:
        required += ("qualified_artifact_review",)
    statuses = [checks.get(k, check("UNKNOWN", "CHECK_NOT_RUN"))["status"] for k in required]
    return "FAIL" if "FAIL" in statuses else "UNKNOWN" if "UNKNOWN" in statuses else "PASS"


async def attempt(cfg, storage, row, profile, profile_hash, arm, frozen):
    rec = recipe(row, profile_hash, cfg, arm)
    rec["protocol_hash"] = frozen["hash"]
    cfg = {**cfg, "execution_deadline_utc": frozen.get("budget", {}).get("deadline_utc")}
    rh = digest(rec)
    recipe_root = storage.path("runs/" + rh)
    from .progress import chain, settlement, state
    prior = chain(recipe_root, rh)
    if state(storage, rh) != "PENDING":
        raise Blocked("RECIPE_ALREADY_ATTEMPTED", "Completed cases are never replayed")
    if prior and settlement(prior[-1][0])["state"] != "RETRY_READY":
        raise Blocked("AUTHORITATIVE_RECONCILIATION_REQUIRED")
    root = recipe_root / uuid.uuid4().hex
    # Publish a populated attempt atomically; a kill cannot leave an empty active attempt.
    staging = storage.path("tmp/attempt-" + root.name)
    staging.mkdir(parents=True)
    record = {"recipe_hash": rh, "recipe": rec, "row": row, "profile": profile,
              "status": "STARTED", "started_at": utc(), "resumability_version": 1}
    if prior:
        record.update(retry_of=prior[-1][0].name, first_attempt_id=prior[0][0].name)
    atomic_json(staging / "attempt.json", record)
    recipe_root.mkdir(parents=True, exist_ok=True)
    staging.rename(root)
    journal = Journal(root, storage.check)
    atomic_json(root / "planning_recipe.json", rec)
    started = time.monotonic()
    from .resources import sample
    stop_resources = asyncio.Event()
    resource_task = asyncio.create_task(sample(journal, stop_resources))
    checks = {}
    driver = None
    outcome = {"recipe_hash": rh, "attempt_id": root.name, "row_id": row["row_id"], "dataset": row["dataset"],
               "cluster_id": row["inference_cluster_id"], "arm": arm, "status": "FAILED", "clinical_approval": "NOT_ESTABLISHED"}
    outcome.update(primary_endpoint=primary_endpoint(frozen.get("protocol", {})),
                   target_semantics=row.get("target_semantics"), site=profile["applicability"]["site"],
                   profile_hash=profile_hash, dose_engine=profile["engine"]["name"],
                   patient_linkage_resolved=row.get("patient_linkage_resolved", False))
    if prior:
        outcome.update(retry_of=record["retry_of"], first_attempt_id=record["first_attempt_id"],
                       measurement_origin="interruption_recovery_not_first_attempt")
    try:
        original_sources_unchanged(row)
        storage.check(reserve=cfg.get("per_case_reserve_bytes", 10 * 1024**3))
        async with Browser(cfg, storage, journal, root) as driver:
            sid = await driver.create_case()
            outcome["session_id"] = sid
            # Persist identity before any upload: a crash can be reconciled without re-submission.
            atomic_json(root / "session.json", {"session_id": sid, "recipe_hash": rh, "created_at": utc()})
            selected, checks["target"] = await driver.upload_and_promote(row)
            wr, ws = workspace(cfg["metadata_runtime"], sid)
            observed_binary = decode(ws["agent"]["planning_results"]["ctv_binary_array"], wr)
            row = {**row, "observed_target_fingerprint": fingerprint(observed_binary)}
            atomic_json(root / "selected_target.json", {"object_ids": selected, "evidence": checks["target"]})
            await driver.apply_profile(profile)
            async def workflow():
                if arm == "browser-chat":
                    await driver.chat(prompt(row, profile))
                    atomic_json(root / "chat_task.json", {"task_id": driver.task_id, "session_id": sid})
                    await driver.wait_chat()
                elif arm == "manual-ui":
                    await driver.manual_ui()
                else:
                    raise Blocked("UNKNOWN_RUN_ARM")
                result = await driver.observer.get("/api/planning/results")
                result["experiment_session_id"] = sid
                atomic_json(root / "planning_results.json", sanitize(result))
                # Preserve completed branches even if PDF or guide export fails.
                errors = []
                try:
                    await driver.export_pdf()
                except Exception as exc:
                    errors.append({"stage": "pdf", "error": str(exc)})
                exported = None
                try:
                    zip_path = await driver.export_session()
                    manifest_path, manifest = unzip_verified(zip_path, root / "export", cfg.get("per_case_max_export_bytes", 100 * 1024**3))
                    exported = (manifest, manifest_path.parent)
                except Exception as exc:
                    errors.append({"stage": "session_export", "error": str(exc)})
                # Read checkpoint state and copy reference sidecars. No product mutation.
                source_root, snapshot = workspace(cfg["metadata_runtime"], sid)
                state = snapshot.get("agent", {}).get("planning_results", {})
                verify_effective_target(cfg["metadata_runtime"], sid, row, selected)
                copy_workspace(cfg["metadata_runtime"], sid, root / "observer-backup", storage.check)
                if exported:
                    checks.update(collect(root, row, profile, result, exported, state, selected, cfg, rh, frozen["acceptance_rules"]))
                else:
                    checks["export_completeness"] = check("FAIL", "SESSION_EXPORT_FAILED")
                outcome["partial_errors"] = errors
                outcome["software_artifacts_present"] = bool(result.get("has_dose") and result.get("has_dvh") and result.get("has_guide"))
                outcome["planning_id"] = result.get("planning_id")
                outcome["planning_data_version"] = result.get("planning_data_version")
            remaining = cfg["budgets"]["overall_s"] - (time.monotonic() - started)
            if cfg.get("execution_deadline_utc"):
                from datetime import datetime, timezone
                remaining = min(remaining, (datetime.fromisoformat(cfg["execution_deadline_utc"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds())
            try:
                if remaining <= 0:
                    raise Blocked("OVERALL_TIME_BUDGET_EXHAUSTED")
                await asyncio.wait_for(workflow(), timeout=remaining)
            except Exception:
                try:
                    await driver.screenshot("failure-state")
                except Exception:
                    pass
                outcome["cancellation_state"] = await driver.cancel_and_reconcile()
                raise
    except asyncio.CancelledError:
        # Ctrl+C stops this runner, not an assumed server/GPU task. Reattach next run.
        outcome.update(interrupted=True, error_code="RUNNER_INTERRUPTED",
                       reconciliation="REQUIRED_BEFORE_NEXT_MUTATION")
        journal.event("attempt", "INTERRUPTED", session_id=outcome.get("session_id"))
        raise
    except Exception as exc:
        outcome["error_code"] = exc.code if isinstance(exc, Blocked) else "ATTEMPT_TIMEOUT" if isinstance(exc, asyncio.TimeoutError) else "EXECUTION_ERROR"
        outcome["error"] = str(exc)
        journal.event("attempt", "ERROR", code=outcome["error_code"], detail=str(exc))
        # Driver context has already closed; do NOT click/resubmit on a new context.
        if outcome.get("session_id"):
            outcome["reconciliation"] = "REQUIRED_BEFORE_NEXT_MUTATION"
    finally:
        stop_resources.set()
        try:
            await resource_task
        except Exception as exc:
            outcome["resource_observation_error"] = str(exc)
        storage.check()
        try:
            original_sources_unchanged(row)
            checks["source_preservation"] = check("PASS")
        except Blocked as exc:
            checks["source_preservation"] = check("FAIL", exc.code)
        except OSError as exc:
            checks["source_preservation"] = check("UNKNOWN", "SOURCE_RECHECK_UNAVAILABLE", detail=str(exc))
        artifacts = archive_manifest(root)
        checks["archive"] = verify_archive(root, artifacts)
        atomic_json(root / "artifact_manifest.json", artifacts)
        outcome["checks"] = checks
        elapsed = time.monotonic() - started
        deadline_ok = True
        if cfg.get("execution_deadline_utc"):
            from datetime import datetime, timezone
            deadline_ok = datetime.now(timezone.utc) <= datetime.fromisoformat(cfg["execution_deadline_utc"].replace("Z", "+00:00"))
        within = elapsed <= cfg["budgets"]["overall_s"] and deadline_ok
        checks["within_budget"] = check("PASS" if within else "FAIL", "TIME_BUDGET_EXCEEDED" if not within else None)
        outcome["software_completion"] = endpoint(checks, require_review=False)
        outcome["reviewed_completion"] = endpoint(checks)
        software_primary = outcome["primary_endpoint"] == SOFTWARE_ENDPOINT
        outcome["workflow_completion"] = outcome["software_completion"] if software_primary else outcome["reviewed_completion"]
        outcome["status"] = "INTERRUPTED" if outcome.get("interrupted") else ("SOFTWARE_SUCCESS" if software_primary else "VERIFIED_SUCCESS") if outcome["workflow_completion"] == "PASS" else "PARTIAL_OR_UNEVALUABLE" if outcome.get("software_artifacts_present") else "FAILED"
        if outcome.get("interrupted"):
            outcome.update(workflow_completion="UNKNOWN", software_completion="UNKNOWN", reviewed_completion="UNKNOWN")
        outcome["elapsed_s"] = elapsed
        outcome["finished_at"] = utc()
        atomic_json(root / "terminal_result.json", outcome)
        journal.event("attempt", outcome["status"], workflow_completion=outcome["workflow_completion"])
    return outcome


async def run(cfg, storage, max_cases, arm="browser-chat"):
    if max_cases is not None and (type(max_cases) is not int or max_cases <= 0):
        raise Blocked("EXPLICIT_POSITIVE_CASE_LIMIT_REQUIRED")
    frozen = gates(cfg, storage, execute=True)
    storage.initialize()
    arms = frozen["protocol"]["arms"]
    if arm != "paired" and arm not in arms:
        raise Blocked("ARM_NOT_REGISTERED")
    if arm == "paired" and frozen["protocol"]["study_kind"] != "paired_workflow":
        raise Blocked("PAIRED_STUDY_NOT_FROZEN")
    # One cross-arm/account/GPU lease. Distinct experiments also need a common GPU lease.
    lease_name = "account:" + cfg.get("username_env", "COHORT_USERNAME")
    with storage.lease(lease_name, global_scope=True), storage.lease("gpu-planning", global_scope=True):
        available = {}
        for r, p, h, error in candidates(cfg, storage):
            if r["row_id"] in available:
                raise Blocked("DUPLICATE_RESOLVED_ROW")
            available[r["row_id"]] = (r, p, h, error)
        # Reconcile interrupted cases before considering ANY new GPU mutation.
        # Rerunning the same command is enough; no manual lock/result deletion.
        from .recovery import recover_pending
        recovered = await recover_pending(cfg, storage, frozen, available)
        cases, skipped = pending_cases(cfg, storage, frozen, available, arm, max_cases)
        actual = list(storage.path("runs").glob("*/*/attempt.json"))
        pending_attempts = sum(len(modes) for _, _, _, modes in cases)
        if len(actual) + pending_attempts > frozen["budget"]["max_attempts"]:
            raise Blocked("ATTEMPT_BUDGET_EXCEEDED", "Reduce this batch; no pending allocation is silently dropped")
        if not cases:
            return {"cases_dispatched": 0, "new_attempts": 0, "already_terminal_cases": skipped,
                    "reconciled_cases": len(recovered), "outcomes": []}
        validate_live_service(storage, cfg)
        validate_account_quota(cfg, frozen["budget"]["approved_account_quota_bytes"])
        batch_id = uuid.uuid4().hex
        batch_root = storage.path("tables/batches/" + batch_id)
        batch_root.mkdir(parents=True)
        atomic_json(batch_root / "allocation.json", {"protocol_hash": frozen["hash"], "created_at": utc(),
                    "rows": [{"row_id": r["row_id"], "arms": modes} for r, _, _, modes in cases],
                    "budget_projection": budget_preview(cfg, storage, cases)})
        count, outcomes = 0, []
        for row, profile, ph, order in cases:
            for mode in order:
                storage.check()
                # Frozen frame/recipes are already in memory. Do not reparse a
                # many-thousand-row frame or hash all model weights per case.
                # Small signed gate documents and deadline remain fenced.
                for name in ("governance", "protocol", "acceptance_rules", "budget"):
                    if load_json(cfg[name + "_path"]) != frozen[name]:
                        raise Blocked("FROZEN_PROTOCOL_DRIFT", name)
                from datetime import datetime, timezone
                if datetime.fromisoformat(frozen["budget"]["deadline_utc"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                    raise Blocked("RESOURCE_DEADLINE_EXPIRED")
                outcome = await attempt(cfg, storage, row, profile, ph, mode, frozen)
                atomic_json(batch_root / (outcome["attempt_id"] + ".json"), outcome)
                outcomes.append(outcome)
                if outcome.get("reconciliation") and outcome.get("cancellation_state") != "TASK_TERMINAL":
                    raise Blocked("AUTHORITATIVE_RECONCILIATION_REQUIRED", outcome["session_id"])
            count += 1
        summary = {"cases_dispatched": count, "new_attempts": len(outcomes), "already_terminal_cases": skipped,
                   "reconciled_cases": len(recovered),
                   "statuses": dict(Counter(r["status"] for r in outcomes)), "batch_directory": str(batch_root),
                   "outcomes": outcomes if len(outcomes) <= 25 else [], "outcomes_truncated_in_console": len(outcomes) > 25}
        atomic_json(batch_root / "summary.json", summary)
        return summary
