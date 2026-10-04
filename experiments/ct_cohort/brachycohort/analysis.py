"""Descriptive tables and paired cluster estimates; never invent population power."""
from collections import Counter, defaultdict
from pathlib import Path
import csv
import json
import numpy as np

from .core import Blocked, atomic_json, load_json, sha256


def results(base):
    rows = []
    for attempt in sorted(Path(base).glob("runs/*/*/attempt.json")):
        record = load_json(attempt)
        if record.get("retry_of"):
            continue  # Recovery is reported separately, never a second primary observation.
        terminal = attempt.parent / "terminal_result.json"
        if not terminal.is_file():
            rows.append({"recipe_hash": record["recipe_hash"], "attempt_id": attempt.parent.name,
                         "row_id": record["row"]["row_id"], "dataset": record["row"]["dataset"],
                         "cluster_id": record["row"]["inference_cluster_id"], "arm": record["recipe"]["arm"],
                         "status": "INCOMPLETE", "workflow_completion": "UNKNOWN", "elapsed_s": None})
            continue
        row = load_json(terminal)
        pointer = Path(base) / "tables/adjudications" / attempt.parent.name / "current.json"
        if pointer.is_file():
            ref = load_json(pointer)
            reviewed = Path(ref["path"]).resolve()
            if pointer.parent.resolve() not in reviewed.parents or sha256(reviewed) != ref["sha256"] or sha256(terminal) != ref["first_attempt_terminal_sha256"]:
                raise Blocked("ADJUDICATION_LINK_CHANGED")
            updated = load_json(reviewed)
            if updated["recipe_hash"] != row["recipe_hash"] or updated["attempt_id"] != row["attempt_id"]:
                raise Blocked("ADJUDICATION_IDENTITY_MISMATCH")
            row = updated
        rows.append(row)
    from .progress import chain, settlement, needs_reconciliation
    for row in rows:
        items = chain(Path(base) / "runs" / row["recipe_hash"], row["recipe_hash"])
        if not items:
            raise Blocked("ANALYSIS_ATTEMPT_CHAIN_MISSING")
        latest, _ = items[-1]
        proof = settlement(latest)
        row["case_progress"] = (proof["state"] if proof else "INCOMPLETE" if needs_reconciliation(latest) else "SETTLED")
        row["recovery_attempts"] = len(items) - 1
        if proof:
            row["eventual_software_completion"] = proof.get("recovered_software_completion", "UNKNOWN")
            row["eventual_artifact_directory"] = proof.get("destination")
        elif not needs_reconciliation(latest):
            completed = load_json(latest / "terminal_result.json")
            row["eventual_software_completion"] = completed.get("software_completion", "UNKNOWN")
            row["eventual_artifact_directory"] = str(latest)
        else:
            row["eventual_software_completion"] = "UNKNOWN"
    return rows


def paired_cluster_summary(rows, seed=1729, n_bootstrap=5000):
    by_cluster = defaultdict(dict)
    for r in rows:
        cluster = r["cluster_id"]
        if r["arm"] in by_cluster[cluster]:
            return {"status": "BLOCKED", "reason": "MULTIPLE_TARGETS_OR_RETRIES_PER_CLUSTER"}
        by_cluster[cluster][r["arm"]] = int(r["workflow_completion"] == "PASS")
    pairs = [r for r in by_cluster.values() if set(r) == {"browser-chat", "manual-ui"}]
    if not pairs:
        return {"status": "NOT_EVALUABLE", "reason": "NO_COMPLETE_ARM_PAIRS", "clusters": len(by_cluster)}
    deltas = np.array([r["browser-chat"] - r["manual-ui"] for r in pairs], dtype=float)
    if len(pairs) < 30:
        interval = None
        reason = "INSUFFICIENT_CLUSTERS_FOR_BOOTSTRAP_INFERENCE"
    else:
        rng = np.random.default_rng(seed)
        means = [float(np.mean(rng.choice(deltas, size=len(deltas), replace=True))) for _ in range(n_bootstrap)]
        interval = np.percentile(means, [2.5, 97.5]).tolist()
        reason = "DESCRIPTIVE_UNWEIGHTED_CLUSTER_BOOTSTRAP_NOT_LOCKED_STRATIFIED_PRIMARY_TEST"
    return {"status": "DESCRIPTIVE", "paired_clusters": len(pairs), "incomplete_pairs": len(by_cluster) - len(pairs),
            "difference": float(deltas.mean()), "discordant_pairs": int(np.count_nonzero(deltas)),
            "ci95": interval, "interval_note": reason, "clinical_inference": False}


def locked_paired_analysis(rows, protocol, frame):
    """Prespecified design weights, cluster pairs, and no complete-case shortcut."""
    spec = protocol.get("analysis")
    if protocol.get("study_kind") != "paired_workflow" or not isinstance(spec, dict) or spec.get("method") != "stratified_paired_cluster_bootstrap_v1":
        return {"status": "NOT_REGISTERED", "formal_inference": False}
    weights = spec.get("stratum_weights", {})
    alpha = spec.get("alpha", .025)
    margin = spec.get("noninferiority_margin")
    samples = spec.get("bootstrap_replicates", 10000)
    if not weights or any(type(w) not in (int, float) or not np.isfinite(w) or w <= 0 for w in weights.values()) or not np.isclose(sum(weights.values()), 1):
        raise Blocked("INVALID_PREREGISTERED_STRATUM_WEIGHTS")
    if not isinstance(margin, (int, float)) or not 0 < margin < 1 or not 0 < alpha < .5 or type(samples) is not int or samples < 1000:
        raise Blocked("INVALID_PREREGISTERED_ANALYSIS")
    if set(frame) != set(protocol["row_ids"]):
        return {"status": "BLOCKED", "reason": "LOCKED_CASE_FRAME_UNRESOLVED"}
    started = {}
    for r in rows:
        key = (r["row_id"], r["arm"])
        if key in started:
            return {"status": "BLOCKED", "reason": "DUPLICATE_FIRST_ATTEMPT"}
        if r["row_id"] not in frame:
            return {"status": "BLOCKED", "reason": "UNREGISTERED_ROW_IN_ANALYSIS"}
        started[key] = r
    groups = defaultdict(list)
    clusters = []
    unfinished = []
    for identifier, f in frame.items():
        cluster = f["cluster_id"]
        clusters.append(cluster)
        stratum = f["stratum"]
        if stratum not in weights:
            return {"status": "BLOCKED", "reason": "UNREGISTERED_STRATUM"}
        pair = [started.get((identifier, arm)) for arm in ("browser-chat", "manual-ui")]
        if any(r is None or r["status"] == "INCOMPLETE" for r in pair):
            unfinished.append(identifier)
            continue
        groups[stratum].append(int(pair[0]["workflow_completion"] == "PASS") - int(pair[1]["workflow_completion"] == "PASS"))
    if len(set(clusters)) != len(clusters):
        return {"status": "BLOCKED", "reason": "UNRESOLVED_REPEATED_CLUSTERS"}
    if unfinished:
        return {"status": "NOT_FINAL", "allocated_pairs": len(frame), "unfinished_pairs": unfinished,
                "note": "Do not silently drop allocated cases. Resolve stopped/undispatched allocations in a signed protocol amendment."}
    minimum = max(30, spec.get("minimum_clusters_per_stratum", 50))
    if set(groups) != set(weights) or any(len(groups[s]) < minimum for s in weights):
        return {"status": "EXPLORATORY_ONLY", "reason": "SPARSE_OR_EMPTY_FROZEN_STRATUM",
                "stratum_counts": {s: len(groups[s]) for s in weights}}
    rng = np.random.default_rng(protocol["sampling_seed"])
    estimate = sum(weights[s] * np.mean(groups[s]) for s in weights)
    boot = np.zeros(samples)
    for s in weights:
        a = np.array(groups[s], dtype=float)
        # Bound memory: no all-strata/all-replicate resampling matrix.
        for i in range(samples):
            boot[i] += weights[s] * rng.choice(a, len(a), replace=True).mean()
    bootstrap_interval = np.quantile(boot, [alpha, 1 - alpha]).tolist()
    # A bootstrap of all tied successes yields a zero-width interval and
    # spuriously certifies noninferiority at the boundary. Protect every case,
    # not only observed degenerate samples, with a bounded-pair concentration
    # interval. D lies in [-1, 1]; each cluster has weight w_s / n_s.
    radius = np.sqrt(2 * np.log(1 / alpha) * sum(weights[s] ** 2 / len(groups[s]) for s in weights))
    conservative = [max(-1., float(estimate - radius)), min(1., float(estimate + radius))]
    interval = [min(bootstrap_interval[0], conservative[0]), max(bootstrap_interval[1], conservative[1])]
    return {"status": "LOCKED_DESIGN_ESTIMATE", "method": spec["method"], "pairs": len(frame),
            "difference": float(estimate), "interval": interval, "bootstrap_interval": bootstrap_interval,
            "finite_sample_guard_interval": conservative, "interval_coverage": 1 - 2 * alpha,
            "noninferiority_margin": margin, "lower_bound_above_negative_margin": bool(interval[0] > -margin),
            "stratum_counts": {s: len(groups[s]) for s in weights}, "weights": weights,
            "clinical_equivalence_claim": False, "interval_method_requires_investigator_validation": True,
            "note": "Prespecify the Hoeffding-envelope decision interval and recalculate power for it; the bootstrap interval alone is descriptive. Independent resolved clusters are required. First-attempt UNKNOWN/FAIL count as unsuccessful; no post-hoc superiority test."}


def write_table(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def long_tables(storage, rows):
    """Stream millions of seed/organ/resource rows rather than collect in RAM."""
    from contextlib import ExitStack
    keys = ["attempt_id", "row_id", "dataset", "arm", "cluster_id"]
    schemas = [("target_metrics", ["metric", "value", "basis"]),
               ("oar_metrics", ["organ", "metric", "value", "basis"]),
               ("seeds", ["object_id", "trajectory_id", "x_lps_mm", "y_lps_mm", "z_lps_mm"]),
               ("needles", ["object_id", "length_mm", "entry_lps_mm", "tip_lps_mm"]),
               ("stage_times", ["stage", "status", "duration_s"]),
               ("resources", ["utc", "runner_rss_bytes", "host_ram_available_bytes", "gpus"])]
    class Sink:
        def __init__(self, writer):
            self.append = writer.writerow
    with ExitStack() as stack:
        sinks = []
        for name, fields in schemas:
            path = storage.path("tables/" + name + ".csv")
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(path.open("w", newline="", encoding="utf-8"))
            writer = csv.DictWriter(handle, fieldnames=keys + fields, extrasaction="ignore")
            writer.writeheader()
            sinks.append(Sink(writer))
        _long_rows(storage, rows, *sinks)


def _long_rows(storage, rows, metrics, organs, seeds, needles, stages, resources):
    for outcome in rows:
        root = storage.path("runs/" + outcome["recipe_hash"] + "/" + outcome["attempt_id"])
        key = {k: outcome.get(k) for k in ("attempt_id", "row_id", "dataset", "arm", "cluster_id")}
        for name, target in (("target_metrics.json", metrics), ("oar_metrics.json", organs)):
            if not (root / name).is_file():
                continue
            raw = load_json(root / name).get("raw", {})
            if name.startswith("target"):
                for metric, value in raw.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        target.append({**key, "metric": metric, "value": value, "basis": "saved_product_proxy"})
            else:
                items = raw.items() if isinstance(raw, dict) else [(v.get("organ") or v.get("name"), v) for v in raw] if isinstance(raw, list) else []
                for organ, values in items:
                    if isinstance(values, dict):
                        for metric, value in values.items():
                            if isinstance(value, (int, float)) and not isinstance(value, bool):
                                target.append({**key, "organ": organ, "metric": metric, "value": value, "basis": "saved_product_proxy"})
        if (root / "plan_geometry.json").is_file():
            from .runner import normalize_needles
            data = load_json(root / "plan_geometry.json")
            for seed in data.get("seeds") or []:
                position = seed.get("pos") or [None] * 3
                seeds.append({**key, "object_id": seed.get("id"), "trajectory_id": seed.get("trajectory_id"),
                              **dict(zip(("x_lps_mm", "y_lps_mm", "z_lps_mm"), position))})
            for needle in normalize_needles(data.get("needles") or []):
                a, b = needle.get("entry"), needle.get("tip")
                length = float(np.linalg.norm(np.array(a) - b)) if a and b and len(a) == len(b) == 3 else None
                needles.append({**key, "object_id": needle.get("id"), "length_mm": length,
                                "entry_lps_mm": json.dumps(a), "tip_lps_mm": json.dumps(b)})
        for event_path in sorted((root / "events").glob("*.json")):
            event = load_json(event_path)
            if "duration_s" in event:
                stages.append({**key, "stage": event["stage"], "status": event["status"], "duration_s": event["duration_s"]})
            if event["stage"] == "resources" and event.get("sample"):
                sample = event["sample"]
                resources.append({**key, "utc": sample["utc"], "runner_rss_bytes": sample["runner_rss_bytes"],
                                  "host_ram_available_bytes": sample["host_ram_available_bytes"], "gpus": json.dumps(sample.get("gpus"))})


def analyze(storage, cfg=None):
    rows = results(storage.base)
    strata = defaultdict(list)
    for r in rows:
        strata[(r["dataset"], r["arm"])].append(r)
    table = []
    for (dataset, arm), values in sorted(strata.items()):
        table.append({"dataset": dataset, "arm": arm, "attempts": len(values),
                      "primary_endpoint_pass": sum(r["workflow_completion"] == "PASS" for r in values),
                      "verified_success": sum(r.get("reviewed_completion", r["workflow_completion"] if r.get("status") == "VERIFIED_SUCCESS" else "UNKNOWN") == "PASS" for r in values),
                      "software_success": sum(r.get("software_completion") == "PASS" for r in values),
                      "qualified_review_success": sum(r.get("reviewed_completion") == "PASS" for r in values),
                      "unknown": sum(r["workflow_completion"] == "UNKNOWN" for r in values),
                      "failed": sum(r["workflow_completion"] == "FAIL" for r in values),
                      "unfinished_attempts": sum(r["status"] == "INCOMPLETE" for r in values),
                      "median_elapsed_s_terminal_attempts": float(np.median([r["elapsed_s"] for r in values if r["elapsed_s"] is not None])) if any(r["elapsed_s"] is not None for r in values) else None})
    resolved = [load_json(p) for p in storage.path("resolved").glob("*.json")]
    report = {"status": "DESCRIPTIVE_NOT_CONFIRMATORY", "screened_records": len(resolved),
              "preflight": dict(Counter(r["preflight_status"] for r in resolved)),
              "screen_reasons": dict(Counter(x for r in resolved for x in r.get("reasons", []))),
              "attempts": len(rows), "strata": table, "paired": paired_cluster_summary(rows),
              "unfinished_attempts": sum(r["status"] == "INCOMPLETE" for r in rows),
              "denominator": "all_started_first_attempts_including_missing_terminal_records",
              "unallocated_frozen_rows_excluded_from_attempt_rate_not_final_primary_cohort_result": True,
              "no_patient_level_claim_without_reviewed_linkage": True, "physical_dose_validation": "SEPARATE_REFERENCE_SUBSTUDY"}
    frozen_path = storage.path("protocol/frozen-gates.json")
    if cfg and frozen_path.is_file():
        frozen = load_json(frozen_path)
        protocol = frozen["protocol"]
        from .cohort import row_ids
        cohort_frame = frozen.get("cohort_frame")
        registered = set(row_ids(protocol, cohort_frame))
        spec = protocol.get("analysis") if isinstance(protocol.get("analysis"), dict) else {}
        field = spec.get("stratum_field", "dataset")
        if field not in {"dataset", "approved_site"}:
            raise Blocked("UNSUPPORTED_ANALYSIS_STRATUM")
        if cohort_frame:
            # Analysis uses allocation-time records, not later case approvals.
            frame = {r["row_id"]: {"cluster_id": r["cluster_id"],
                                  "stratum": r["site"] if field == "approved_site" else r["dataset"]}
                     for r in cohort_frame["rows"]}
            report["allocation"] = allocation_summary(storage, rows, protocol, cohort_frame)
            if cohort_frame["selection"]["target_policy"] == "all-targets":
                report["paired"] = {"status": "NOT_REGISTERED", "reason": "TARGET_RUN_CENSUS_NOT_A_PAIRED_CLUSTER_TRIAL"}
        else:
            from .runner import candidates
            frame = {r["row_id"]: {"cluster_id": r["inference_cluster_id"],
                                  "stratum": p["applicability"]["site"] if field == "approved_site" else r["dataset"]}
                     for r, p, ph, error in candidates(cfg, storage) if not error and r["row_id"] in registered}
        # The paired routine still supports legacy row_ids-only protocols.
        report["locked_primary"] = locked_paired_analysis(rows, {**protocol, "row_ids": list(registered)}, frame)
    report["evidence_counts"] = {"software_completion_pass": sum(r.get("software_completion") == "PASS" for r in rows),
        "qualified_review_completion_pass": sum(r.get("reviewed_completion") == "PASS" for r in rows),
        "independent_physics_bound_to_attempts": sum(r.get("checks", {}).get("independent_physics", {}).get("status") == "PASS" for r in rows),
        "standalone_reference_imports_not_automatically_bound_to_attempts": sum(1 for _ in storage.path("tables").glob("reference-*.json")),
        "independent_physics_not_a_cnn_execution_prerequisite": True}
    report["resumption"] = {"recovery_attempts": sum(r.get("recovery_attempts", 0) for r in rows),
        "eventual_software_completion_pass": sum(r.get("eventual_software_completion") == "PASS" for r in rows),
        "case_progress": dict(Counter(r.get("case_progress", "UNKNOWN") for r in rows)),
        "eventual_results_do_not_replace_first_attempt_endpoints": True}
    atomic_json(storage.path("tables/analysis.json"), report)
    long_tables(storage, rows)
    with storage.path("tables/attempts.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["recipe_hash", "attempt_id", "row_id", "dataset", "site", "target_semantics", "cluster_id", "arm", "status", "primary_endpoint", "workflow_completion", "software_completion", "reviewed_completion", "dose_engine", "elapsed_s", "error_code", "case_progress", "recovery_attempts", "eventual_software_completion", "eventual_artifact_directory"]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    # Every additional trial/collection is accessible without duplicating primary units.
    recovery_rows = []
    for path in sorted(storage.path("runs").glob("*/*/attempt.json")):
        record = load_json(path)
        if record.get("retry_of"):
            outcome_path = path.parent / "terminal_result.json"
            outcome = load_json(outcome_path) if outcome_path.is_file() else {"status": "INCOMPLETE"}
            recovery_rows.append({"attempt_id": path.parent.name, "row_id": record["row"]["row_id"],
                                  "kind": "case_retry", "retry_of": record["retry_of"],
                                  "destination": str(path.parent), **outcome})
        for evidence in sorted(path.parent.glob("recoveries/*/recovery.json")):
            recovery_rows.append({"kind": "existing_case_reconciliation", **load_json(evidence)})
    write_table(storage.path("tables/recovery_attempts.csv"), recovery_rows,
                ["kind", "attempt_id", "row_id", "retry_of", "state", "status", "workflow_completion",
                 "recovered_software_completion", "recovered_reviewed_completion", "elapsed_s", "destination"])
    return report


def allocation_summary(storage, outcomes, protocol, frame):
    """Every allocated target/arm remains visible, even before its first attempt."""
    started = {}
    for result in outcomes:
        key = (result["row_id"], result["arm"])
        if key in started:
            raise Blocked("DUPLICATE_FIRST_ATTEMPT")
        started[key] = result
    allowed = {(r["row_id"], arm) for r in frame["rows"] for arm in protocol["arms"]}
    if not set(started) <= allowed:
        raise Blocked("UNREGISTERED_ROW_OR_ARM_IN_ANALYSIS")
    counts, groups = Counter(), {}
    fields = ["row_id", "dataset", "site", "cluster_id", "arm", "ct_path", "label_path", "target_values",
              "target_semantics", "status", "workflow_completion", "software_completion", "reviewed_completion"]
    path = storage.path("tables/cohort_status.csv")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in frame["rows"]:
            for arm in protocol["arms"]:
                result = started.get((row["row_id"], arm))
                state = "NOT_STARTED" if result is None else "INCOMPLETE" if result["status"] == "INCOMPLETE" else result["workflow_completion"]
                counts[state] += 1
                groups.setdefault((row["dataset"], arm), Counter())[state] += 1
                writer.writerow({**row, "target_values": json.dumps(row["target_values"]), "arm": arm,
                    "status": state, "workflow_completion": result["workflow_completion"] if result else "NOT_STARTED",
                    "software_completion": result.get("software_completion", "UNKNOWN") if result else "NOT_STARTED",
                    "reviewed_completion": result.get("reviewed_completion", "UNKNOWN") if result else "NOT_STARTED"})
    return {"inference_unit": frame["inference_unit"], "allocated_targets": len(frame["rows"]),
            "allocated_clusters": frame["clusters"], "allocated_attempts": len(allowed), "counts": dict(counts),
            "final": not counts["NOT_STARTED"] and not counts["INCOMPLETE"],
            "primary_success_over_all_allocated": counts["PASS"] / len(allowed),
            "unfinished_allocations_are_not_claimed_as_failures_or_dropped": True,
            "strata": [{"dataset": d, "arm": a, "counts": dict(c), "allocated": sum(c.values())}
                       for (d, a), c in sorted(groups.items())],
            "clinical_approval": "NOT_ESTABLISHED", "physical_dose_truth": "NOT_ESTABLISHED"}
