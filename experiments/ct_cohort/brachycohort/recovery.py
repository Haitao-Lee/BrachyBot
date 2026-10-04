"""Append-only case recovery; wait/collect existing jobs before a case-level retry."""
import asyncio
import time
import uuid
import subprocess
from pathlib import Path

from .core import Blocked, Journal, atomic_json, digest, load_json, sha256, utc
from .verify import archive_manifest, check, review, verify_archive, unzip_verified


async def wait_case_idle(driver, expected_task_id, seconds):
    """A disconnected browser is NOT proof the server stopped. Require both fences."""
    from .observer import terminal_task
    deadline = time.monotonic() + seconds
    consecutive = 0
    while time.monotonic() < deadline:
        payload = await driver.observer.get("/api/chat/task")
        task = payload.get("task")
        if task and task.get("session_id") != driver.session_id:
            raise Blocked("RECOVERY_TASK_CASE_MISMATCH")
        if task and expected_task_id and task.get("task_id") != expected_task_id:
            raise Blocked("RECOVERY_TASK_CHANGED")
        snapshot = await driver.observer.get("/api/workspace/snapshot")
        operation = snapshot.get("workspace", {}).get("operation", {}).get("state")
        idle = operation in {"ready", "completed", "idle", "failed", "cancelled"}
        # After an isolated server restart a task may be absent, but a busy operation
        # still prohibits replay. Missing/unknown operation state is not idle.
        consecutive = consecutive + 1 if idle and (not task or terminal_task(payload, expected_task_id)) else 0
        if consecutive >= 2:
            driver.journal.event("recovery", "SERVER_IDLE_VERIFIED", task=task, operation=operation)
            return {"task": task, "operation": operation}
        await asyncio.sleep(min(2, max(0, deadline - time.monotonic())))
    raise Blocked("RECOVERY_SERVER_STILL_BUSY", "Original case retained; rerun later, no duplicate planning submitted")


def seal_interrupted(root, attempt):
    """Preserve the original result; a recovery success never becomes first-attempt success."""
    if (root / "terminal_result.json").is_file():
        return
    row, rec = attempt["row"], attempt["recipe"]
    outcome = {"recipe_hash": attempt["recipe_hash"], "attempt_id": root.name, "row_id": row["row_id"],
               "dataset": row["dataset"], "cluster_id": row["inference_cluster_id"], "arm": rec["arm"],
               "status": "INTERRUPTED", "interrupted": True, "workflow_completion": "UNKNOWN",
               "software_completion": "UNKNOWN", "reviewed_completion": "UNKNOWN", "elapsed_s": None,
               "finished_at": utc(), "error_code": "MISSING_TERMINAL_AFTER_INTERRUPTION",
               "clinical_approval": "NOT_ESTABLISHED", "reconciliation": "REQUIRED_BEFORE_NEXT_MUTATION"}
    if attempt.get("retry_of"):
        outcome.update(retry_of=attempt["retry_of"], first_attempt_id=attempt["first_attempt_id"])
    atomic_json(root / "terminal_result.json", outcome)


async def recover_case(root, cfg, storage, frozen):
    """No new planning here. Settle a finished job or authorize ONLY this interrupted case retry."""
    from .browser import Browser
    from .observer import copy_workspace, workspace, verify_effective_target, decode
    from .runner import collect, endpoint, fingerprint, original_sources_unchanged
    from .progress import save_settlement
    started = time.monotonic()
    attempt = load_json(root / "attempt.json")
    row, profile = attempt["row"], attempt["profile"]
    original_sources_unchanged(row)
    was_interrupted = not (root / "terminal_result.json").is_file() or load_json(root / "terminal_result.json").get("interrupted", False)
    destination = root / "recoveries" / uuid.uuid4().hex
    destination.mkdir(parents=True)
    journal = Journal(destination, storage.check)
    result = {"attempt_id": root.name, "recipe_hash": attempt["recipe_hash"], "row_id": row["row_id"],
              "recovered_at": utc(), "primary_first_attempt_success_changed": False,
              "planning_resubmitted": False, "destination": str(destination), "checks": {}}
    identity_path = root / "session.json"
    if not identity_path.is_file():
        if attempt.get("resumability_version") != 1:
            raise Blocked("LEGACY_INTERRUPTION_IDENTITY_UNRESOLVED", str(root))
        # v1 persists session identity before ANY upload/tool action. A lost create
        # response can leave an empty orphan case, but cannot have submitted planning.
        result.update(no_server_work_submitted=True, state="RETRY_READY" if was_interrupted else "SETTLED")
    else:
        identity = load_json(identity_path)
        if identity.get("recipe_hash") != attempt["recipe_hash"] or not identity.get("session_id"):
            raise Blocked("RECOVERY_RECIPE_MISMATCH")
        from .runtime import validate_live_service
        validate_live_service(storage, cfg, allow_shutdown_pending=True)
        result["session_id"] = identity["session_id"]
        async with Browser(cfg, storage, journal, destination) as driver:
            await driver.attach_case(identity["session_id"])
            expected = load_json(root / "chat_task.json").get("task_id") if (root / "chat_task.json").is_file() else None
            result["server_observation"] = await wait_case_idle(driver, expected, cfg["budgets"]["workflow_s"])
            planning = await driver.observer.get("/api/planning/results")
            planning["experiment_session_id"] = identity["session_id"]
            atomic_json(destination / "planning_results.json", planning)
            complete = bool(planning.get("has_dose") and planning.get("has_dvh") and planning.get("has_guide"))
            checks = result["checks"]
            if complete:
                # Reuse only verified, current products of the supplied target/profile.
                # Collect into a fresh recovery directory; never overwrite original artifacts.
                try:
                    selected = load_json(root / "selected_target.json")["object_ids"]
                    checks["target"] = verify_effective_target(cfg["metadata_runtime"], identity["session_id"], row, selected)
                    wr, snapshot = workspace(cfg["metadata_runtime"], identity["session_id"])
                    state = snapshot["agent"]["planning_results"]
                    row = {**row, "observed_target_fingerprint": fingerprint(decode(state["ctv_binary_array"], wr))}
                    await driver.export_pdf()
                    zipped = await driver.export_session()
                    path, exported = unzip_verified(zipped, destination / "export", cfg.get("per_case_max_export_bytes", 100 * 1024**3))
                    copy_workspace(cfg["metadata_runtime"], identity["session_id"], destination / "observer-backup", storage.check)
                    checks.update(collect(destination, row, profile, planning, (exported, path.parent), state,
                                          selected, cfg, attempt["recipe_hash"], frozen["acceptance_rules"]))
                    original_sources_unchanged(row)
                    checks["source_preservation"] = check("PASS")
                    # This is a recovery-collection budget, not a reconstructed original runtime.
                    within = time.monotonic() - started <= cfg["budgets"]["overall_s"]
                    if cfg.get("execution_deadline_utc"):
                        from datetime import datetime, timezone
                        within = within and datetime.now(timezone.utc) <= datetime.fromisoformat(cfg["execution_deadline_utc"].replace("Z", "+00:00"))
                    checks["within_budget"] = check("PASS" if within else "FAIL",
                        None if within else "RECOVERY_TIME_BUDGET_EXCEEDED",
                        basis="recovery_collection_not_reconstructed_first_attempt_runtime")
                    manifest = archive_manifest(destination)
                    atomic_json(destination / "artifact_manifest.json", manifest)
                    checks["archive"] = verify_archive(destination, manifest)
                    result["collection_finished"] = True
                except Exception as exc:
                    result["collection_error"] = str(exc)
                result.update(recovered_software_completion=endpoint(checks, require_review=False),
                              recovered_reviewed_completion=endpoint(checks))
            # Failed ordinary attempts are recorded and skipped, not retried until lucky.
            # Only interrupted, incomplete cases may be replayed automatically.
            # A collected FAIL/UNKNOWN is still a recorded case, not a license to
            # repeat it until the measurements happen to pass.
            result["state"] = "SETTLED" if result.get("collection_finished") or not was_interrupted else "RETRY_READY"
    storage.check()
    original_sources_unchanged(row)
    result["elapsed_s"] = time.monotonic() - started
    seal_interrupted(root, attempt)
    save_settlement(root, destination, result)
    return result


async def recover_pending(cfg, storage, frozen, available):
    """Called under account/GPU leases. Even another arm's busy case must settle first."""
    from .cohort import execution_recipe, row_ids, entry_for
    from .progress import chain, needs_reconciliation, settlement
    recovered = []
    registered = set(row_ids(frozen["protocol"], frozen.get("cohort_frame")))
    frame = {r["row_id"]: r for r in frozen.get("cohort_frame", {}).get("rows", [])}
    for directory in sorted(storage.path("runs").glob("*")):
        if not directory.is_dir():
            raise Blocked("RECIPE_ATTEMPT_DIRECTORY_UNRESOLVED")
        items = chain(directory, directory.name)
        if not items:
            continue
        root, record = items[-1]
        if not needs_reconciliation(root) or settlement(root):
            continue
        identifier = record.get("row", {}).get("row_id")
        if identifier not in registered or identifier not in available or available[identifier][3]:
            raise Blocked("RECOVERY_CASE_NOT_REGISTERED_OR_APPROVED", str(root))
        row, profile, ph, _ = available[identifier]
        arm = record.get("recipe", {}).get("arm")
        if arm not in frozen["protocol"]["arms"] or record.get("recipe") != execution_recipe(row, ph, cfg, arm, frozen) or \
                record.get("recipe_hash") != directory.name or digest(record["recipe"]) != directory.name:
            raise Blocked("RECOVERY_RECIPE_CHANGED", str(root))
        if frame and frame[identifier] != entry_for(row, profile, ph):
            raise Blocked("FROZEN_RESOLVED_ROW_CHANGED", identifier)
        if record["row"] != row or record["profile"] != profile:
            raise Blocked("RECOVERY_CASE_OR_PROFILE_CHANGED", identifier)
        bounded_cfg = {**cfg, "execution_deadline_utc": frozen["budget"].get("deadline_utc")}
        try:
            result = await asyncio.wait_for(recover_case(root, bounded_cfg, storage, frozen),
                                            timeout=cfg["budgets"]["overall_s"])
        except asyncio.TimeoutError:
            raise Blocked("RECOVERY_TIME_BUDGET_EXHAUSTED", "Case retained; no duplicate submission") from None
        recovered.append(result)
    return recovered


def finalize_review(root, cfg, storage):
    from .gates import gates
    from .runner import endpoint
    frozen = gates(cfg, storage, enforce_deadline=False)
    attempt = load_json(root / "attempt.json")
    if attempt["recipe"]["protocol_hash"] != frozen["hash"]:
        raise Blocked("REVIEW_FROZEN_PROTOCOL_DRIFT")
    outcome = load_json(root / "terminal_result.json")
    artifacts = load_json(root / "artifact_manifest.json")
    if verify_archive(root, artifacts)["status"] != "PASS":
        raise Blocked("REVIEW_ARCHIVE_CHANGED")
    directory = cfg.get("review_directory")
    rules = frozen["acceptance_rules"]
    evidence = review(Path(directory) / (attempt["recipe_hash"] + ".json") if directory else None,
                      attempt["recipe_hash"], artifacts, rules["guide_checks"] + rules["report_checks"],
                      digest(rules), root.name)
    checks = {**outcome["checks"], "qualified_artifact_review": evidence}
    if evidence["status"] == "PASS" and evidence["receipt"]["checks"].get("current_quality_evaluation") == "PASS":
        checks["quality_evaluation"] = check("PASS", evidence_level="qualified_external_artifact_review")
    from .cohort import SOFTWARE_ENDPOINT
    software = endpoint(checks, require_review=False)
    reviewed = endpoint(checks)
    adjudicated = {**outcome, "checks": checks, "software_completion": software, "reviewed_completion": reviewed,
                   "workflow_completion": software if outcome.get("primary_endpoint") == SOFTWARE_ENDPOINT else reviewed,
                   "adjudicated_at": utc(), "measurement_origin": "same_first_attempt_artifacts_no_rerun"}
    # Original first-attempt result is never overwritten. Analysis prefers this
    # explicitly linked adjudication, not any later recovered planning artifacts.
    directory = storage.path("tables/adjudications/" + root.name)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (digest(adjudicated) + ".json")
    atomic_json(path, adjudicated)
    atomic_json(directory / "current.json", {"path": str(path), "sha256": sha256(path),
                "first_attempt_terminal_sha256": sha256(root / "terminal_result.json")})
    return adjudicated


def render_pdf(root, storage):
    if not (root / "report.pdf").is_file():
        raise Blocked("PDF_MISSING")
    storage.check(reserve=1024**3)
    destination = storage.path("tables/pdf-review/" + root.name + "/" + sha256(root / "report.pdf"))
    destination.mkdir(parents=True, exist_ok=True)
    output = subprocess.run(["pdftoppm", "-r", "120", "-png", str(root / "report.pdf"), str(destination / "page")],
                            capture_output=True, text=True, timeout=600)
    if output.returncode or not list(destination.glob("page-*.png")):
        raise Blocked("PDF_RENDER_FAILED", output.stderr[-1000:])
    result = {"pdf_sha256": sha256(root / "report.pdf"), "pages": archive_manifest(destination),
              "output": str(destination), "visual_acceptance": "REQUIRES_QUALIFIED_REVIEW"}
    atomic_json(destination / "render.json", result)
    return result


async def resume_collection(root, cfg, storage):
    from .browser import Browser
    from .gates import gates
    from .runtime import validate_live_service
    from .observer import copy_workspace, workspace, terminal_task
    gates(cfg, storage)
    validate_live_service(storage, cfg, allow_shutdown_pending=True)
    attempt = load_json(root / "attempt.json")
    identity = load_json(root / "session.json")
    if identity["recipe_hash"] != attempt["recipe_hash"]:
        raise Blocked("RECOVERY_RECIPE_MISMATCH")
    destination = storage.path("tables/recovery/" + root.name + "/" + uuid.uuid4().hex)
    destination.mkdir(parents=True)
    journal = Journal(destination, storage.check)
    with storage.lease("gpu-planning", global_scope=True):
        async with Browser(cfg, storage, journal, destination) as driver:
            await driver.attach_case(identity["session_id"])
            payload = await driver.observer.get("/api/chat/task")
            task = payload.get("task")
            expected = load_json(root / "chat_task.json")["task_id"] if (root / "chat_task.json").exists() else None
            if task and (expected and task.get("task_id") != expected or not terminal_task(payload, expected)):
                raise Blocked("RECOVERY_TASK_NOT_TERMINAL_OR_CHANGED")
            _, snapshot = workspace(cfg["metadata_runtime"], identity["session_id"])
            if snapshot.get("operation", {}).get("state") not in {"ready", "completed", "idle", "failed", "cancelled"}:
                raise Blocked("RECOVERY_CASE_BUSY")
            result = await driver.observer.get("/api/planning/results")
            atomic_json(destination / "planning_results.json", result)
            await driver.screenshot("recovery-existing-case")
            errors = []
            for name, method in (("pdf", driver.export_pdf), ("session_export", driver.export_session)):
                try:
                    output = await method()
                    if name == "session_export":
                        unzip_verified(output, destination / "export", cfg["per_case_max_export_bytes"])
                except Exception as exc:
                    errors.append({"stage": name, "error": str(exc)})
            copy_workspace(cfg["metadata_runtime"], identity["session_id"], destination / "observer-backup", storage.check)
    summary = {"session_id": identity["session_id"], "recipe_hash": identity["recipe_hash"],
               "planning_resubmitted": False, "primary_first_attempt_success_changed": False,
               "errors": errors, "destination": str(destination), "recovered_at": utc()}
    atomic_json(destination / "artifact_manifest.json", archive_manifest(destination))
    atomic_json(destination / "recovery.json", summary)
    return summary
