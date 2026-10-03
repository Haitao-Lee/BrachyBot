#!/usr/bin/env python3
"""E0 smoke suite: run every authored task that has a recorded observation.

Component-contract regression only; never a formal SUT performance gate.
Confirmed failed criteria remain FAILED, missing evidence is BLOCKED, and
missing replay is SKIPPED-live. A successful regression assertion about an
expected evidence gap does not make the underlying task completed or safe.
CLI returns 1 for contract/criterion failure, 2 for blocked/skipped readiness.

    python tools/run_suite.py --tasks-dir tasks --replay-dir tests/replay --out results
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

from oracles import Verdict  # noqa: E402
from tools import run_task as rt  # noqa: E402
from tools import score_report as sr  # noqa: E402
from tools import panel_report as pr  # noqa: E402
from tools.component_replay import prepare, load_profile, assert_component_outcome


class ComponentReplayAdapter(rt.ReplayAdapter):
    """Explicit versioned synthetic controls; inheritance retains replay mode."""
    def __init__(self, directory):
        super().__init__(directory)
        self.profile = load_profile()

    def observe(self, task, initial_state):
        raw = super().observe(task, initial_state)
        observation, _ = prepare(task, raw, 'positive', self.directory, profile=self.profile)
        return observation


def _authored_tasks(tasks_dir: str) -> List[Dict[str, Any]]:
    out = []
    for dirpath, _, files in sorted(os.walk(tasks_dir)):
        for fn in sorted(files):
            if fn.endswith(".json"):
                with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                    out.append(json.load(fh))
    return out


def run_suite(tasks_dir: str, replay_dir: str, out: str) -> Dict[str, Any]:
    adapter = ComponentReplayAdapter(replay_dir)
    rows = []
    for task in _authored_tasks(tasks_dir):
        tid = task["id"]
        replay = os.path.join(replay_dir, f"{tid}.json")
        if not os.path.isfile(replay):
            rows.append({"task_id": tid, "track": task.get("track"),
                         "verdict": "SKIPPED-live", "ok": False, "score": None,
                         "status": "SKIPPED-live", "contract_ok": None,
                         "coverage": 0, "n_a_reason": "replay_missing"})
            continue
        outcome = rt.run_task(task, adapter, out)
        verdict = outcome["evaluation"]["verdict"]
        item = outcome["evaluation"].get("item_score") or {}
        scenario = (task.get("unit") or {}).get("scenario_id") or tid
        contract_ok, contract_error = True, None
        try:
            assert_component_outcome(outcome['evaluation'], adapter.profile['entries'].get(tid), 'positive')
        except (AssertionError, KeyError) as exc:
            contract_ok, contract_error = False, str(exc)
        merged = outcome['evaluation'].get('merged') or {}
        status = ('COMPLETED' if verdict == Verdict.MEETS.value else
                  'FAILED' if verdict == Verdict.DOES_NOT_MEET.value else 'BLOCKED-evidence')
        rows.append({"task_id": tid, "track": task.get("track"), "scenario": scenario,
                     "weight": (task.get("scoring") or {}).get("weight", 1.0),
                     "verdict": verdict, "ok": verdict == Verdict.MEETS.value,
                     "score": item.get("value"), "coverage": item.get("coverage"),
                     "n_a_reason": item.get("n_a_reason"), "status": status,
                     "contract_ok": contract_ok, "contract_error": contract_error,
                     "evidence_gaps": merged.get('evidence_gaps', []),
                     "violations": merged.get('violations', []),
                     "evaluation_mode": "component_self_test", "comparable_sut_result": False})
    n_ok = sum(1 for r in rows if r["ok"])
    failed = [r for r in rows if r['status'] == 'FAILED']
    scored = [{"track": r["track"], "scenario": r["scenario"], "verdict": r["verdict"],
               "value": r["score"], "coverage": r["coverage"],
               "n_a_reason": r["n_a_reason"]} for r in rows]
    summary = {
        "evaluation_mode": "component_self_test",
        "comparable_sut_result": False,
        "formal_result_count": 0,
        "contract_profile": "v2",
        "n_contract_failures": sum(r.get('contract_ok') is False for r in rows),
        "n_blocked": sum(r['status'] == 'BLOCKED-evidence' for r in rows),
        "ready_for_formal_evaluation": False,
        "n_skipped": sum(r["verdict"] == "SKIPPED-live" for r in rows),
        "note": "Expected-positive replay checks evaluator plumbing, not real SUT performance or n_runs robustness",
        "n_tasks": len(rows),
        "n_ok": n_ok,
        "n_failed": len(failed),
        "score_summary": sr.aggregate(scored),
        "panel_report": pr.report(scored, n_boot=1000),
        "rows": rows,
    }
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "e0_prv_suite.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    with open(os.path.join(out, "pilot_report.md"), "w", encoding="utf-8") as fh:
        fh.write(pr.render_markdown(summary["panel_report"]))
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks-dir", default=os.path.join(BB, "tasks"))
    ap.add_argument("--replay-dir", default=os.path.join(BB, "tests", "replay"))
    ap.add_argument("--out", default="results")
    args = ap.parse_args(argv)

    summary = run_suite(args.tasks_dir, args.replay_dir, args.out)
    for r in summary["rows"]:
        mark = r['status']
        print(f"  [{mark:4s}] {r['task_id']:16s} track={r['track'] or '?':3s} {r['verdict']}")
    print(f"E0 PRV smoke: {summary['n_ok']}/{summary['n_tasks']} ok, "
          f"{summary['n_failed']} failed, {summary['n_blocked']} blocked, "
          f"{summary['n_contract_failures']} contract failures")
    if summary.get("score_summary", {}).get("n_items"):
        print(sr.format_table(summary["score_summary"]))
        print(f"report: {os.path.join(args.out, 'pilot_report.md')}")
    if summary['n_failed'] or summary['n_contract_failures']:
        return 1
    return 2 if summary['n_blocked'] or summary['n_skipped'] else 0


if __name__ == "__main__":
    raise SystemExit(main())
