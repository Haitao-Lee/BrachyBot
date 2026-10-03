"""Read-only readiness inventory. Counts and component tests are not agent validity.

No tasks, answers, frozen splits or historical results are rewritten. Exit 2
means a confirmatory experiment is blocked, not that the SUT failed a task.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib


def inspect(tasks_dir, assignment=None):
    files = sorted(pathlib.Path(tasks_dir).rglob("*.json"))
    tasks = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    counts = collections.Counter(str(t.get("track", "?")) for t in tasks)
    ids = [str(t.get("id", "")) for t in tasks]
    gaps = []
    if len(set(ids)) != len(ids) or any(not i for i in ids):
        gaps.append("missing_or_duplicate_task_ids")
    for tr in ("G", "J", "M"):
        if not counts[tr]:
            gaps.append(f"missing_real_task_track:{tr}")
    # A source-owned independence identifier is needed, not a task ID or
    # paraphrase label manufactured for each generated item.
    grouped = sum(bool((t.get("unit") or {}).get("scenario_id")) for t in tasks)
    if grouped != len(tasks):
        gaps.append("incomplete_source_scenario_identity")
    if assignment:
        if assignment.get("commitment_version") != "task_id_and_canonical_content_v2":
            gaps.append("legacy_index_only_split_commitment")
        sealed_ids = set((assignment.get("splits", {}).get("sealed") or {}).get("task_ids") or [])
        if sealed_ids:
            sealed_tracks = collections.Counter(t.get("track") for t in tasks if t.get("id") in sealed_ids)
            for tr in ("B", "D1", "L"):
                if not sealed_tracks[tr]:
                    gaps.append(f"primary_track_absent_from_sealed:{tr}")
        else:
            gaps.append("sealed_membership_not_available_to_private_evaluator")
        if assignment.get("secrecy_verified") is not True:
            gaps.append("sealed_secrecy_not_verified")
    else:
        gaps.append("private_confirmatory_split_not_supplied")
    return {"n_tasks": len(tasks), "tracks": dict(sorted(counts.items())),
            "with_source_scenario_id": grouped,
            "task_content_sha256": hashlib.sha256(json.dumps(tasks, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
            "readiness": "BLOCKED" if gaps else "REQUIRES_INDEPENDENT_EXPERT_AND_RUNTIME_VALIDATION",
            "gaps": gaps, "confirmatory_ready": False,
            "note": "Inventory cannot certify clinical gold, observer independence, unseen exposure or real browser/GPU execution."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--assignment")
    args = parser.parse_args(argv)
    assignment = json.loads(pathlib.Path(args.assignment).read_text(encoding="utf-8")) if args.assignment else None
    print(json.dumps(inspect(args.tasks, assignment), ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
