"""All mutation commands are explicit; no automatic all-case execution."""
from __future__ import annotations
import argparse
import asyncio
import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path

from .core import Blocked, Storage, atomic_json, digest, load_json, sha256, utc


def main():
    parser = argparse.ArgumentParser(prog="brachy-cohort")
    parser.add_argument("--config", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory")
    pre = sub.add_parser("preflight")
    pre_size = pre.add_mutually_exclusive_group(required=True)
    pre_size.add_argument("--limit", type=int)
    pre_size.add_argument("--all-records", action="store_true")
    pre.add_argument("--dataset")
    pre.add_argument("--row-id", action="append")
    pre.add_argument("--allow-offline-data-access", action="store_true")
    sub.add_parser("validate-profiles")
    dry = sub.add_parser("dry-run")
    dry.add_argument("--include-cases", action="store_true", help="Print every case/prompt; default is a bounded preview")
    sub.add_parser("doctor")
    frame = sub.add_parser("build-frame")
    frame.add_argument("--target-policy", choices=["all-targets", "one-per-cluster"], default="all-targets")
    frame.add_argument("--limit", type=int)
    frame.add_argument("--dataset", action="append")
    frame.add_argument("--output", default="protocol/cohort-frame.json", help="New NAS-relative file; never overwrites a frame")
    schedule = sub.add_parser("schedule")
    schedule.add_argument("--arm", choices=["browser-chat", "manual-ui", "paired"], default="browser-chat")
    schedule.add_argument("--max-cases", type=int)
    schedule.add_argument("--measurements", help="Pilot elapsed_s and retained_bytes arrays, not invented constants")
    sub.add_parser("provision")
    sub.add_parser("serve")
    quota = sub.add_parser("set-account-quota")
    quota.add_argument("--execute", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--execute", action="store_true")
    run_size = run.add_mutually_exclusive_group(required=True)
    run_size.add_argument("--max-cases", type=int)
    run_size.add_argument("--all-pending", action="store_true", help="Entire frozen pending frame, still subject to approved resource budget")
    run.add_argument("--arm", choices=["browser-chat", "manual-ui", "paired"], default="browser-chat")
    sub.add_parser("reconcile")
    sub.add_parser("analyze")
    verify = sub.add_parser("verify")
    verify.add_argument("--attempt", required=True)
    finalize = sub.add_parser("finalize-review")
    finalize.add_argument("--attempt", required=True)
    recover = sub.add_parser("resume-collection")
    recover.add_argument("--attempt", required=True)
    recover.add_argument("--execute", action="store_true")
    render = sub.add_parser("render-pdf")
    render.add_argument("--attempt", required=True)
    dicom = sub.add_parser("convert-dicom")
    dicom.add_argument("--row-id", required=True)
    dicom.add_argument("--allow-offline-data-access", action="store_true")
    reference = sub.add_parser("verify-reference")
    reference.add_argument("--dose", required=True)
    reference.add_argument("--reference-dose", required=True)
    reference.add_argument("--target", required=True)
    reference.add_argument("--profile-id", required=True)
    reference.add_argument("--reference-recipe", required=True)
    args = parser.parse_args()
    try:
        cfg = load_json(args.config)
        storage = Storage(cfg)
        storage.check()
        if args.command == "inventory":
            from .preflight import records
            datasets, semantics, paths, seen = Counter(), Counter(), set(), set()
            for row in records(cfg["manifest_path"]):
                if row["row_id"] in seen:
                    raise Blocked("DUPLICATE_MANIFEST_ROW")
                seen.add(row["row_id"])
                datasets[row["dataset"]] += 1
                semantics[row.get("target_semantics", "UNKNOWN")] += 1
                if row.get("ct_path"):
                    paths.add(row["ct_path"])
            result = {"manifest_sha256": sha256(cfg["manifest_path"]), "rows": len(seen),
                      "datasets": dict(datasets), "target_semantics": dict(semantics), "unique_ct_paths": len(paths),
                      "row_count_is_not_eligible_tumor_case_count": True,
                      "approved_profiles_assumed": False}
        elif args.command == "preflight":
            if not args.allow_offline_data_access or args.limit is not None and args.limit <= 0:
                raise Blocked("OFFLINE_ACCESS_AND_POSITIVE_LIMIT_REQUIRED")
            from .preflight import records, preflight
            from .gates import approvals
            storage.initialize()
            policy = load_json(cfg["preflight_policy_path"])
            conversion_reviews = approvals(cfg.get("conversion_approvals_path"))
            states = Counter()
            with storage.lease("preflight"):
                count, seen = 0, set()
                for row in records(cfg["manifest_path"]):
                    if row["row_id"] in seen:
                        raise Blocked("DUPLICATE_MANIFEST_ROW")
                    seen.add(row["row_id"])
                    if args.dataset and row["dataset"] != args.dataset:
                        continue
                    if args.row_id and row["row_id"] not in args.row_id:
                        continue
                    if args.limit is not None and count >= args.limit:
                        break
                    path = storage.path("resolved/" + digest(row["row_id"]) + ".json")
                    if path.exists():
                        result = load_json(path)
                        if result["row_id"] != row["row_id"]:
                            raise Blocked("RESOLVED_ROW_COLLISION")
                        if result.get("preflight_policy_hash") != digest(policy):
                            raise Blocked("PREFLIGHT_POLICY_DRIFT", "Use a new experiment ID; never overwrite a frozen resolved record")
                        if result["preflight_status"] == "PASS":
                            from .runner import original_sources_unchanged
                            original_sources_unchanged(result)
                    else:
                        result = preflight(row, storage, policy, conversion_reviews.get(row["row_id"]))
                        atomic_json(path, result)
                    states[result["preflight_status"]] += 1
                    count += 1
                result = {"inspected_records": count, "statuses": dict(states), "planning_started": False,
                          "scope": "all_matching_records" if args.all_records else "explicit_bounded_subset"}
        elif args.command == "build-frame":
            from .cohort import build_frame
            storage.initialize()
            path = storage.path(args.output)
            with storage.lease("frame-build"):
                if path.exists():
                    raise Blocked("COHORT_FRAME_ALREADY_EXISTS", "Use a new filename; frozen selections are immutable")
                frame = build_frame(cfg, storage, args.target_policy, args.limit, args.dataset)
                atomic_json(path, frame)
            result = {k: v for k, v in frame.items() if k != "rows"}
            result.update(cohort_frame={"path": str(path), "sha256": sha256(path)},
                          next_action="Review the frame and pin its path/hash in a separately frozen protocol; no planning started")
        elif args.command == "schedule":
            from .cohort import pending_cases, budget_preview
            from .runner import candidates
            from .gates import gates
            frozen = gates(cfg, storage, enforce_deadline=False)
            if args.max_cases is not None and args.max_cases <= 0:
                raise Blocked("EXPLICIT_POSITIVE_CASE_LIMIT_REQUIRED")
            if args.arm == "paired" and frozen["protocol"]["study_kind"] != "paired_workflow" or args.arm != "paired" and args.arm not in frozen["protocol"]["arms"]:
                raise Blocked("ARM_NOT_REGISTERED")
            available = {r["row_id"]: (r, p, ph, error) for r, p, ph, error in candidates(cfg, storage)}
            cases, skipped = pending_cases(cfg, storage, frozen, available, args.arm, args.max_cases)
            result = budget_preview(cfg, storage, cases, load_json(args.measurements) if args.measurements else None)
            result.update(already_terminal_cases=skipped, product_mutations=0,
                          approved_max_attempts=frozen["budget"]["max_attempts"],
                          started_attempts=sum(1 for _ in storage.path("runs").glob("*/*/attempt.json")))
        elif args.command == "validate-profiles":
            from .profiles import validate_profile
            result = []
            for p in load_json(cfg["profiles_path"])["profiles"]:
                try:
                    result.append({"id": p["id"], "status": "VALID", "sha256": validate_profile(p)})
                except Blocked as exc:
                    result.append({"id": p.get("id"), "status": "BLOCKED", "reason": exc.code})
        elif args.command == "dry-run":
            from .runner import candidates
            from .profiles import prompt
            from .gates import gates
            try:
                gate_status = {"status": "OPEN", "hash": gates(cfg, storage)["hash"]}
            except Blocked as exc:
                gate_status = {"status": "CLOSED", "reason": exc.code}
            preview, reasons, count, eligible = [], Counter(), 0, 0
            for r, p, ph, reason in candidates(cfg, storage):
                count += 1
                eligible += reason is None
                if reason:
                    reasons[reason] += 1
                if args.include_cases or len(preview) < 25:
                    preview.append({"row_id": r["row_id"], "eligible": reason is None, "block_reason": reason,
                                    "profile_hash": ph, "request": prompt(r, p) if p else None})
            result = {"gates": gate_status, "resolved_rows": count, "eligible_rows": eligible,
                      "block_reasons": dict(reasons), "cases": preview, "cases_preview_truncated": count > len(preview),
                      "product_mutations": 0}
        elif args.command == "doctor":
            from .runtime import validate_runtime
            result = {"storage": storage.check(), "dependencies": {n: bool(importlib.util.find_spec(n)) for n in
                      ("numpy", "nibabel", "SimpleITK", "playwright", "pydicom", "pypdf", "trimesh", "psutil")}}
            try:
                result["deployment"] = validate_runtime(storage, cfg)
            except (Blocked, FileNotFoundError) as exc:
                result["deployment"] = {"status": "NOT_READY", "reason": str(exc)}
        elif args.command == "provision":
            from .runtime import provision
            result = provision(storage, cfg)
        elif args.command == "serve":
            from .runtime import serve
            serve(storage, cfg)
            result = {"service": "EXITED"}
        elif args.command == "set-account-quota":
            if not args.execute:
                raise Blocked("EXECUTION_FLAG_REQUIRED")
            from .runtime import set_account_quota
            result = set_account_quota(storage, cfg)
        elif args.command == "run":
            if not args.execute:
                raise Blocked("EXECUTION_FLAG_REQUIRED", "Use dry-run for a non-mutating preview")
            from .runner import run
            result = asyncio.run(run(cfg, storage, None if args.all_pending else args.max_cases, args.arm))
        elif args.command == "reconcile":
            # File/task receipts only; does not select/upload/submit/retry cases.
            from .observer import workspace
            result = []
            for path in sorted(storage.path("runs").glob("*/*/attempt.json")):
                sidfile = path.parent / "session.json"
                if not sidfile.exists():
                    result.append({"attempt": str(path.parent), "status": "CASE_CREATION_NOT_OBSERVED", "safe_to_replay": False})
                    continue
                sid = load_json(sidfile)["session_id"]
                try:
                    _, snap = workspace(cfg["metadata_runtime"], sid)
                    result.append({"attempt": str(path.parent), "session_id": sid,
                                   "operation": snap.get("operation"), "chat": snap.get("chat"),
                                   "terminal_result_exists": (path.parent / "terminal_result.json").is_file(),
                                   "safe_to_replay": False, "next_action": "LIVE_TASK_OBSERVATION_AND_REVIEW_REQUIRED"})
                except (Blocked, OSError) as exc:
                    result.append({"attempt": str(path.parent), "status": "UNRESOLVED", "error": str(exc), "safe_to_replay": False})
            atomic_json(storage.path("tables/reconciliation.json"), result)
        elif args.command == "analyze":
            from .analysis import analyze
            result = analyze(storage, cfg)
        elif args.command == "verify":
            from .verify import verify_archive
            path = Path(args.attempt).resolve()
            if storage.base not in path.parents:
                raise Blocked("ATTEMPT_OUTSIDE_EXPERIMENT")
            result = verify_archive(path, load_json(path / "artifact_manifest.json"))
        elif args.command in {"finalize-review", "resume-collection", "render-pdf"}:
            from .recovery import finalize_review, resume_collection, render_pdf
            path = Path(args.attempt).resolve()
            if storage.base not in path.parents or not (path / "attempt.json").is_file():
                raise Blocked("ATTEMPT_OUTSIDE_EXPERIMENT")
            if args.command == "finalize-review":
                result = finalize_review(path, cfg, storage)
            elif args.command == "render-pdf":
                result = render_pdf(path, storage)
            else:
                if not args.execute:
                    raise Blocked("EXECUTION_FLAG_REQUIRED", "Recovery selects the existing case and exports; it never repeats planning")
                result = asyncio.run(resume_collection(path, cfg, storage))
        elif args.command == "convert-dicom":
            if not args.allow_offline_data_access:
                raise Blocked("OFFLINE_DATA_ACCESS_ACKNOWLEDGEMENT_REQUIRED")
            from .preflight import records
            from .dicom import convert
            storage.initialize()
            rows = [r for r in records(cfg["manifest_path"]) if r["row_id"] == args.row_id]
            if len(rows) != 1:
                raise Blocked("DICOM_ROW_NOT_UNIQUE")
            result = convert(rows[0], storage)
        elif args.command == "verify-reference":
            from .verify import physics_reference
            from .profiles import validate_profile
            profiles = [p for p in load_json(cfg["profiles_path"])["profiles"] if p["id"] == args.profile_id]
            if len(profiles) != 1:
                raise Blocked("PROFILE_NOT_UNIQUE")
            validate_profile(profiles[0])
            result = physics_reference(args.dose, args.reference_dose, args.target, profiles[0], load_json(args.reference_recipe))
            atomic_json(storage.path("tables/reference-" + digest(result) + ".json"), result)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    except KeyboardInterrupt:
        print(json.dumps({"status": "INTERRUPTED", "next_action": "Rerun the same run command with the same config to resume; do not delete locks or results"}), file=sys.stderr)
        raise SystemExit(130)
    except Blocked as exc:
        print(json.dumps({"status": "BLOCKED", "code": exc.code, "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "error_type": type(exc).__name__,
                          "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(3)
