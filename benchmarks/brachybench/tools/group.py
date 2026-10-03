#!/usr/bin/env python3
"""Group runner: score a paraphrase group and check expression robustness.

DESIGN §31.  A paraphrase group is several Task Scenarios that express the
**same intent** with different wording / language / terseness.  Each member is
scored independently, then ``paraphrase_invariance`` compares their outcome
classes: the decision (action / abstention / refusal) must be invariant.

    python tools/group.py --group D1-SA-P03 --tasks-dir tasks \
        --replay-dir tests/replay --out results
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BB)

from oracles import Verdict, gate_verdict, get_oracle  # noqa: E402
from tools import run_task as rt  # noqa: E402


def outcome_class(evaluation: Dict[str, Any]) -> Dict[str, Any]:
    """Decision surface used for invariance (reply prose is intentionally excluded)."""
    merged = evaluation.get("merged") or {}
    return {
        "verdict": evaluation.get("verdict"),
        "violations": sorted({v.get("code") for v in merged.get("violations", [])}),
        "evidence_gaps": sorted({v.get("code") for v in merged.get("evidence_gaps", [])}),
        "partial_status": merged.get("partial_status"),
    }


def _load_group(tasks_dir: str, group: str) -> List[Dict[str, Any]]:
    out = []
    for fn in sorted(os.listdir(tasks_dir)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(tasks_dir, fn), encoding="utf-8") as fh:
            task = json.load(fh)
        if (task.get("anti_gaming") or {}).get("paraphrase_group") == group:
            out.append(task)
    return out


def run_group(tasks: List[Dict[str, Any]], adapter, out: str) -> Dict[str, Any]:
    members = []
    for task in tasks:
        evaluation = rt.run_task(task, adapter, out)["evaluation"]
        members.append({
            "instance_id": task["id"],
            "expression_profile": (task.get("anti_gaming") or {}).get("behavioral_probes") or [],
            "outcome_class": outcome_class(evaluation),
        })
    result = get_oracle("paraphrase_invariance")().check(members)
    verdict = gate_verdict(result, threshold_ucb=1.0, G=1)
    return {"members": members, "invariance": result.to_dict(), "verdict": verdict.value}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", required=True)
    ap.add_argument("--tasks-dir", default=os.path.join(BB, "tasks"))
    ap.add_argument("--replay-dir", default=os.path.join(BB, "tests", "replay"))
    ap.add_argument("--out", default="results")
    args = ap.parse_args(argv)

    tasks = _load_group(args.tasks_dir, args.group)
    if not tasks:
        print(f"no tasks in paraphrase group {args.group!r}", file=sys.stderr)
        return 2
    outcome = run_group(tasks, rt.ReplayAdapter(args.replay_dir), args.out)
    for m in outcome["members"]:
        print(f"  {m['instance_id']:16s} {m['outcome_class']['verdict']}")
    print(f"group {args.group}: {outcome['verdict']} "
          f"(consistency={outcome['invariance']['evidence']['paraphrase_consistency_rate']:.2f})")
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"group_{args.group}.json"), "w", encoding="utf-8") as fh:
        json.dump(outcome, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return 0 if outcome["verdict"] == Verdict.MEETS.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
