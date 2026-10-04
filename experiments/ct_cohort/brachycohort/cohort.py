"""Explicit census frames and resumable first-attempt scheduling, not power claims."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .core import Blocked, atomic_json, digest, load_json, sha256, utc


SOFTWARE_ENDPOINT = "software_workflow_completion_within_budget"
REVIEWED_ENDPOINT = "first_attempt_verified_software_workflow_completion_within_budget"


def primary_endpoint(protocol):
    name = protocol.get("primary_endpoint", REVIEWED_ENDPOINT)
    if name not in {SOFTWARE_ENDPOINT, REVIEWED_ENDPOINT}:
        raise Blocked("UNKNOWN_PRIMARY_ENDPOINT")
    if name == SOFTWARE_ENDPOINT and protocol.get("study_kind") == "paired_workflow":
        raise Blocked("PAIRED_REVIEW_ENDPOINT_REQUIRED")
    return name


def frame_inputs(cfg):
    """Pin metadata recipes without reading the cohort's full medical payloads."""
    result = {}
    for name in ("manifest", "profiles", "case_approvals", "preflight_policy"):
        path = cfg.get(name + "_path")
        if not path or not Path(path).is_file():
            raise Blocked("FRAME_INPUT_UNRESOLVED", name)
        result[name + "_sha256"] = sha256(path)
    result["model_recipe_hash"] = digest(cfg.get("model_recipe"))
    return result


def entry_for(row, profile, profile_hash):
    return {"row_id": row["row_id"], "dataset": row["dataset"],
            "cluster_id": row["inference_cluster_id"], "site": profile["applicability"]["site"],
            "ct_path": row["ct_path"], "label_path": row["label_path"],
            "target_values": row["target_values"], "target_semantics": row["target_semantics"],
            "target_hash": row["target_hash"], "source_hashes": row["source_hashes"],
            "profile_hash": profile_hash, "resolved_row_hash": digest(row),
            "patient_linkage_resolved": row.get("patient_linkage_resolved", False)}


def build_frame(cfg, storage, target_policy="all-targets", limit=None, datasets=None):
    """DRAFT selection from reviewed eligible rows; never grants execution approval."""
    from .runner import candidates
    if target_policy not in {"all-targets", "one-per-cluster"}:
        raise Blocked("UNKNOWN_TARGET_SELECTION_POLICY")
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise Blocked("INVALID_FRAME_LIMIT")
    seed = cfg.get("random_seed")
    if type(seed) is not int:
        raise Blocked("INVALID_SCHEDULE_SEED")
    inputs = frame_inputs(cfg)
    seen, reasons, rows = set(), Counter(), []
    for row, profile, ph, error in candidates(cfg, storage):
        if row["row_id"] in seen:
            raise Blocked("DUPLICATE_RESOLVED_ROW")
        seen.add(row["row_id"])
        if datasets and row["dataset"] not in datasets:
            reasons["DATASET_NOT_SELECTED"] += 1
        elif error:
            reasons[error] += 1
        elif not row.get("inference_cluster_id"):
            reasons["CLUSTER_UNRESOLVED"] += 1
        else:
            rows.append(entry_for(row, profile, ph))
    # Stable seeded order avoids an arbitrary dataset/path prefix. This is an
    # ordering recipe, not a promise about the planner's internal RNG.
    rows.sort(key=lambda r: (digest([seed, r["row_id"]]), r["row_id"]))
    if target_policy == "one-per-cluster":
        clusters, selected = set(), []
        for row in rows:
            if row["cluster_id"] in clusters:
                reasons["ADDITIONAL_TARGET_IN_CLUSTER"] += 1
            else:
                clusters.add(row["cluster_id"])
                selected.append(row)
        rows = selected
    if limit is not None:
        reasons["OUTSIDE_EXPLICIT_SUBSET"] += max(0, len(rows) - limit)
        rows = rows[:limit]
    if inputs != frame_inputs(cfg):
        raise Blocked("FRAME_INPUT_CHANGED_DURING_SELECTION")
    return {"schema_version": 1, "status": "DRAFT_REVIEW_REQUIRED", "created_at": utc(),
            "experiment_id": cfg["experiment_id"], "inputs": inputs,
            "selection": {"target_policy": target_policy, "limit": limit,
                          "datasets": sorted(datasets or []), "seed": seed},
            "inference_unit": "target_run" if target_policy == "all-targets" else "cluster_selected_target",
            "screened_resolved_rows": len(seen), "excluded_reasons": dict(reasons),
            "allocated_rows": len(rows), "clusters": len({r["cluster_id"] for r in rows}),
            "dataset_counts": dict(Counter(r["dataset"] for r in rows)), "rows": rows,
            "clinical_approval": "NOT_ESTABLISHED", "power_or_precision_established": False}


def load_frame(protocol, storage, cfg=None):
    spec = protocol.get("cohort_frame")
    if not spec:
        return None
    if not isinstance(spec, dict) or not spec.get("path") or not spec.get("sha256"):
        raise Blocked("COHORT_FRAME_NOT_PINNED")
    path = Path(spec["path"]).resolve()
    if storage.base.resolve() not in path.parents or not path.is_file():
        raise Blocked("COHORT_FRAME_OUTSIDE_EXPERIMENT")
    if sha256(path) != spec["sha256"]:
        raise Blocked("COHORT_FRAME_CHANGED")
    frame = load_json(path)
    rows = frame.get("rows")
    if frame.get("schema_version") != 1 or not isinstance(rows, list) or not rows:
        raise Blocked("COHORT_FRAME_EMPTY_OR_INVALID")
    ids = [r.get("row_id") for r in rows]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise Blocked("COHORT_FRAME_DUPLICATE_OR_INVALID_ROWS")
    if frame.get("allocated_rows") != len(rows):
        raise Blocked("COHORT_FRAME_COUNT_MISMATCH")
    if frame.get("selection", {}).get("seed") != protocol["sampling_seed"]:
        raise Blocked("COHORT_FRAME_SEED_MISMATCH")
    if cfg and (frame.get("experiment_id") != cfg["experiment_id"] or frame.get("inputs") != frame_inputs(cfg)):
        raise Blocked("COHORT_FRAME_RECIPE_DRIFT")
    explicit = protocol.get("row_ids")
    if explicit and explicit != ids:
        raise Blocked("ROW_IDS_AND_COHORT_FRAME_DISAGREE")
    policy = frame.get("selection", {}).get("target_policy")
    if policy not in {"all-targets", "one-per-cluster"}:
        raise Blocked("UNKNOWN_TARGET_SELECTION_POLICY")
    if protocol["study_kind"] == "paired_workflow" and policy != "one-per-cluster":
        raise Blocked("PAIRED_CLUSTER_SELECTION_REQUIRED")
    return frame


def row_ids(protocol, frame=None):
    return [r["row_id"] for r in frame["rows"]] if frame else protocol.get("row_ids", [])


def execution_recipe(row, ph, cfg, mode, frozen):
    from .runner import recipe
    return {**recipe(row, ph, cfg, mode), "protocol_hash": frozen["hash"]}


def attempt_state(storage, recipe_hash):
    from .progress import state
    return state(storage, recipe_hash)


def pending_cases(cfg, storage, frozen, available, arm, max_cases=None):
    """A batch limit counts NEW cases, not already dispatched prefix rows."""
    frame = frozen.get("cohort_frame")
    entries = {r["row_id"]: r for r in frame["rows"]} if frame else {}
    selected, clusters, skipped = [], set(), 0
    permit_multiple = bool(frame and frame["selection"]["target_policy"] == "all-targets"
                           and frozen["protocol"]["study_kind"] != "paired_workflow")
    for identifier in row_ids(frozen["protocol"], frame):
        if identifier not in available or available[identifier][3]:
            raise Blocked("FROZEN_CASE_FRAME_NOT_EXECUTABLE", identifier)
        row, profile, ph, _ = available[identifier]
        if frame and entries[identifier] != entry_for(row, profile, ph):
            raise Blocked("FROZEN_RESOLVED_ROW_CHANGED", identifier)
        if row["dataset"] not in frozen["governance"]["permitted_datasets"]:
            raise Blocked("DATASET_USE_NOT_APPROVED", identifier)
        cluster = row.get("inference_cluster_id")
        if not cluster or not permit_multiple and cluster in clusters:
            raise Blocked("MULTIPLE_PRIMARY_TARGETS_PER_CLUSTER", identifier)
        clusters.add(cluster)
        order = [arm] if arm != "paired" else ["browser-chat", "manual-ui"]
        if arm == "paired" and int(digest([identifier, frozen["protocol"]["sampling_seed"]]), 16) % 2:
            order.reverse()
        pending = [mode for mode in order if attempt_state(storage, digest(execution_recipe(row, ph, cfg, mode, frozen))) == "PENDING"]
        if not pending:
            skipped += 1
        elif max_cases is None or len(selected) < max_cases:
            selected.append((row, profile, ph, pending))
    return selected, skipped


def budget_preview(cfg, storage, cases, measurements=None):
    """A transparent resource projection, never an automatic budget approval."""
    attempts = sum(len(modes) for _, _, _, modes in cases)
    result = {"pending_cases": len(cases), "pending_attempts": attempts,
              "timeout_ceiling_days": attempts * cfg["budgets"]["overall_s"] / 86400,
              "reserve_bytes_per_case": cfg.get("per_case_reserve_bytes"),
              "measured_projection": None, "feasibility_approved": False}
    if measurements:
        times = measurements.get("elapsed_s", [])
        sizes = measurements.get("retained_bytes", [])
        if not times or not sizes or any(type(v) not in (int, float) or not 0 <= v < float("inf") for v in times + sizes):
            raise Blocked("INVALID_PILOT_BUDGET_MEASUREMENTS")
        import numpy as np
        result["measured_projection"] = {"observations": {"runtime": len(times), "storage": len(sizes)},
            "serial_days_at_runtime_p50": attempts * float(np.median(times)) / 86400,
            "serial_days_at_runtime_p95": attempts * float(np.percentile(times, 95)) / 86400,
            "additional_bytes_at_output_p50": attempts * float(np.median(sizes)),
            "additional_bytes_at_output_p95": attempts * float(np.percentile(sizes, 95)),
            "note": "Includes no claim about unmeasured downtime, provider cost, or independent reference compute."}
    return result
