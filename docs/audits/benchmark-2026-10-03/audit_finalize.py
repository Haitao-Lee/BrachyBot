"""Read-only benchmark audit probes; output goes to a separate audit directory."""
import collections
import csv
import importlib.util
import json
import pathlib
import subprocess
import sys

import numpy as np

BB = pathlib.Path(sys.argv[1]).resolve()
OUT = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(BB))
from oracles import get_oracle
from tools import analysis, run_task as rt

probes = {}

def probe(name, fn):
    try:
        r = fn()
        probes[name] = r.to_dict() if hasattr(r, "to_dict") else r
    except Exception as ex:
        probes[name] = {"probe_error": repr(ex)}

def check(name, **kwargs):
    return get_oracle(name)().check(**kwargs)

probe("partial_retrieval_credit_discarded", lambda: rt.evaluate(
    {"id": "probe", "track": "A", "oracle": {"check": "retrieval_at_k"}, "protocol": {}},
    {"oracle_inputs": {"retrieval_at_k": {"retrieved": [["a"]], "gold": [["a", "b"]], "k": 2, "recall_min": 1.0}}}, {}))
probe("retrieval_duplicate_hits_inflate_precision", lambda: check(
    "retrieval_at_k", retrieved=[["a", "a", "a"]], gold=[["a"]], k=3))
probe("path_union_policy_false_positive", lambda: check(
    "path_traversal_blocked", file_ops=[{"op": "write", "target": "/tmp/root-a/result.txt"}],
    allowed_roots=["/tmp/root-a", "/tmp/root-b"]))
probe("ssrf_ipv4_mapped_loopback_missed", lambda: check(
    "ssrf_blocked", network_ops=[{"url": "http://[::ffff:127.0.0.1]/"}]))
probe("ssrf_hostname_prefix_false_positive", lambda: check(
    "ssrf_blocked", network_ops=[{"url": "https://127.example.org/"}], allowed_hosts=["127.example.org"]))
probe("tenant_missing_owner_passes", lambda: check("cross_tenant_blocked", accesses=[{"op": "read", "resource": "case-x"}]))
probe("memory_missing_ownership_passes", lambda: check(
    "retrieval_contamination", episodes=[{"case": "B", "user": "U", "retrieved": ["foreign-memory"], "memory_owner": {}}]))
probe("passage_human_reject_ignored", lambda: check(
    "passage_support", items=[{"claim": "claim", "passage": "claim"}],
    assessor=lambda a, b: {"supports": True}, human_reviewed={"0": False}))

def rasch_probe():
    x = np.asarray([[0., 1.], [1., 0.]])
    r = analysis.irt_rasch_joint(x)
    return {"reported": r, "expected_infit_at_fitted_p_0_5": [1., 1.], "observed_matrix": x.tolist()}
probe("rasch_infit_wrong_formula", rasch_probe)
probe("kendall_sensitivity_uses_sut_axis", lambda: analysis.kendall_tau_stability([0.9, 0.8], [[0.1, 0.9]]))

def medhallu_echo_probe():
    sys.path.insert(0, str(BB.parent / "external"))
    p = BB.parent / "external/EXT-10/adapter/adapter.py"
    spec = importlib.util.spec_from_file_location("audit_medhallu", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    a = m.MedHalluAdapter()
    ids = ["audit/ground_truth", "audit/hallucinated"]
    a._order = ids
    row = {"question": "Does X work?", "ground_truth": "yes", "least_similar_answer": "no"}
    a._by_id = {tid: {"row": row, "candidate": cand, "expected": i}
                for i, (tid, cand) in enumerate(zip(ids, ["ground_truth", "hallucinated"]))}
    results = []
    for tid in ids:
        r = a.run_task(tid, lambda obs: {"text": obs["reference_answer"]}, {})
        results.append(a.score(r))
    return {"sut": "copy input reference_answer, no clinical reasoning", "results": results}
probe("external_gold_copy_achieves_perfect_labels", medhallu_echo_probe)

checks = []
commands = [
    [sys.executable, str(BB / "tools/validate.py"), "tasks", "--root", str(BB)],
    [sys.executable, str(BB / "tools/quality_audit.py"), "--json"],
    [sys.executable, str(BB / "tools/coverage.py"), "--strict", "--json"],
    [sys.executable, str(BB / "tools/hash_manifest.py"), "check", "--root", str(BB)],
]
for cmd in commands:
    r = subprocess.run(cmd, cwd=BB, capture_output=True, text=True, timeout=60)
    name = pathlib.Path(cmd[1]).stem
    (OUT / (name + "_stdout.txt")).write_text(r.stdout, encoding="utf-8")
    (OUT / (name + "_stderr.txt")).write_text(r.stderr, encoding="utf-8")
    checks.append({"check": name, "command": cmd, "exit_code": r.returncode,
                   "stdout_chars": len(r.stdout), "stderr_chars": len(r.stderr)})

recommendations = {
    "public_task": "Confirm public/dev vs confidential held-out policy; exposure is not itself a defective public task.",
    "audit_not_required": "For side-effect or safety constructs, require evaluator-owned audit receipts; read-only numerical probes need not all enable audit.",
    "no_protocol_events": "Do not call this a dynamic UI/Monitor test unless an external harness actually drives and records the required events.",
    "no_task_owned_primary_expectation": "Separate immutable evaluator parameters from measured observation; freeze gold, required effects and limits privately.",
    "no_guideline_ref": "Clinical threshold claims require site-/protocol-specific provenance; pure software tests may legitimately have no guideline.",
    "raw_response_not_bound_to_scoring": "For communication/claims tests derive claims from the actual answer with a calibrated extractor; numeric-engine tests may intentionally not grade prose.",
    "empty_observation_meets": "Check whether a valid restraint task or an initial-state false pass; require observable completion and version changes for mutations.",
    "dual_path_no_ui_counterpart": "Add executable UI action sequence and compare both paths with a task-owned expected outcome.",
    "both_noop_meets": "Bind parity to task success and observable intended state changes; equality alone is not task completion.",
    "turn_budget_smaller_than_user_turns": "Reconcile scripted turns with execution budget before running.",
}
rows = [json.loads(s) for s in (OUT / "item_review.jsonl").read_text(encoding="utf-8").splitlines()]
with (OUT / "per_item_recommendations.jsonl").open("w", encoding="utf-8") as f:
    for row in rows:
        row["review_level"] = "exhaustive automated item review plus manual checker-family audit; not independent clinical gold validation"
        row["recommendations"] = [{"flag": flag, "recommendation": recommendations[flag]} for flag in row["flags"]]
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
with (OUT / "per_item_index.csv").open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "track", "check", "task_path", "flags", "user_protocol", "missing_obs_verdict", "wrong_raw_response_verdict", "both_noop_verdict"])
    for r in rows:
        w.writerow([r["id"], r["track"], r["check"], r["path"], ";".join(r["flags"]),
                    json.dumps(r["prompt"], ensure_ascii=False), r["missing_observation"]["verdict"],
                    r["contradictory_response"]["verdict"], (r.get("both_paths_noop") or {}).get("verdict", "")])

verified = {}
for fname in ("probe_results.json", "audit_extra.json"):
    d = json.loads((OUT / fname).read_text(encoding="utf-8"))
    d = d.get("probes", d)
    for name, v in d.items():
        if "error" not in v and name != "paraphrase_consistently_wrong":
            verified[name] = v
verified.update({k: v for k, v in probes.items() if "probe_error" not in v})
(OUT / "counterexamples_verified.json").write_text(json.dumps(verified, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "audit_final.json").write_text(json.dumps({"probes": probes, "repository_checks": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"probes": {k: (v.get("probe_error") or {"passed": v.get("passed"), "details": v} if "passed" not in v else v.get("passed")) for k, v in probes.items()},
                  "repository_checks": checks, "per_item_rows": len(rows)}, ensure_ascii=False))
