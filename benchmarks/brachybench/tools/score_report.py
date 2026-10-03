#!/usr/bin/env python3
"""Aggregate per-item subordinate scores into a per-track / per-panel report.

Reads the ``item_score`` blocks produced by ``run_task`` and reports, per track:
counts of Meets / Does not meet / Insufficient / N-A, the mean subordinate score
over scored (non-N/A) items, and the N/A reason histogram.

Never merges tracks into a single number (DESIGN §10.2 ironclad rule 2) and never treats
N/A as 0 or 1 (doc §8).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BB)


def aggregate(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    per_track: Dict[str, Dict[str, Any]] = {}
    bucket: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "meets": 0, "does_not_meet": 0, "insufficient": 0,
                 "na": 0, "scored": 0, "sum_value": 0.0, "na_reasons": Counter()}
    )
    for it in items:
        tr = it.get("track") or "?"
        b = bucket[tr]
        b["n"] += 1
        v = it.get("verdict")
        if v == "Meets":
            b["meets"] += 1
        elif v == "Does not meet":
            b["does_not_meet"] += 1
        else:
            b["insufficient"] += 1
        value = it.get("value")
        if value is None:
            b["na"] += 1
            b["na_reasons"][it.get("n_a_reason") or "unknown"] += 1
        else:
            b["scored"] += 1
            b["sum_value"] += float(value)
    for tr, b in bucket.items():
        per_track[tr] = {
            "n": b["n"], "meets": b["meets"], "does_not_meet": b["does_not_meet"],
            "insufficient": b["insufficient"], "na": b["na"], "scored": b["scored"],
            "mean_value": (round(b["sum_value"] / b["scored"], 4) if b["scored"] else None),
            "pass_rate": (round(b["meets"] / b["n"], 4) if b["n"] else None),
            "na_reasons": dict(b["na_reasons"]),
        }
    return {"estimand": "item_weighted_diagnostic_only_not_SSR_scenario",
            "n_items": sum(b["n"] for b in bucket.values()),
            "per_track": dict(sorted(per_track.items()))}


def format_table(report: Dict[str, Any]) -> str:
    lines = [f"{'track':5s} {'n':>6s} {'Meets':>6s} {'DNM':>6s} {'Insuff':>7s} "
             f"{'N/A':>5s} {'scored':>6s} {'mean':>7s} {'pass':>6s}"]
    for tr, r in report["per_track"].items():
        mv = "-" if r["mean_value"] is None else f"{r['mean_value']:.3f}"
        pr = "-" if r["pass_rate"] is None else f"{r['pass_rate']:.2f}"
        lines.append(f"{tr:5s} {r['n']:>6d} {r['meets']:>6d} {r['does_not_meet']:>6d} "
                     f"{r['insufficient']:>7d} {r['na']:>5d} {r['scored']:>6d} {mv:>7s} {pr:>6s}")
    return "\n".join(lines)


def from_results_dir(root: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    has_records = any(fn.endswith(".record.json") for _, _, files in os.walk(root) for fn in files)
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".json"):
                continue
            if has_records and not fn.endswith(".record.json"):
                continue
            try:
                with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError):
                continue
            it = doc.get("item_score") or (doc.get("evaluation") or {}).get("item_score")
            ev = doc.get("evaluation") or {}
            if not it and ev.get("task_id"):
                it = {"task_id": ev["task_id"], "track": ev.get("track", "?"),
                      "verdict": ev.get("verdict"), "value": None,
                      "n_a_reason": "infra_failed" if ev.get("error") or ev.get("infra_failed") else "unscored_run"}
            if it:
                items.append(it)
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results_dir", help="directory of run_task outputs")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = aggregate(from_results_dir(args.results_dir))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
