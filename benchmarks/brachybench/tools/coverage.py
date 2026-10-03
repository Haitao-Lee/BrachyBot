#!/usr/bin/env python3
"""Capability coverage gate (DESIGN §32).

Cross-references the machine-readable capability census
(``capabilities/registry.yaml``) with the evidence actually present
(``capabilities/coverage.json`` + real tasks/oracles/tests) and reports the
coverage matrix.  ``--strict`` makes "capability not tested" a build failure,
which is how comprehensiveness is *maintained* rather than promised.

    python tools/coverage.py                      # report + gap list
    python tools/coverage.py --strict --min 0.80  # CI gate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BB)
sys.path.insert(0, HERE)

from oracles import registered  # noqa: E402
from validate import parse_yaml_lite  # noqa: E402

REGISTRY = os.path.join(BB, "capabilities", "registry.yaml")
COVERAGE = os.path.join(BB, "capabilities", "coverage.json")


def load_registry() -> Dict[str, Any]:
    with open(REGISTRY, encoding="utf-8") as fh:
        return parse_yaml_lite(fh.read())


def capabilities(reg: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for dom in reg.get("domains") or []:
        for cap in dom.get("capabilities") or []:
            out.append({**cap, "domain": dom.get("id")})
    return out


def _task_ids() -> set:
    ids = set()
    tdir = os.path.join(BB, "tasks")
    for dirpath, _, files in os.walk(tdir):
        for fn in files:
            if fn.endswith(".json"):
                ids.add(fn[:-5])
    return ids


def check_evidence(evidence: List[str], task_ids: set, oracle_ids: set) -> List[str]:
    bad = []
    for ref in evidence:
        kind, _, name = ref.partition(":")
        if kind == "task" and name not in task_ids:
            bad.append(f"unresolved task ref {ref!r}")
        elif kind == "oracle" and name not in oracle_ids:
            bad.append(f"unresolved oracle ref {ref!r}")
        elif kind == "test" and not os.path.isfile(os.path.join(BB, name)):
            bad.append(f"unresolved test ref {ref!r}")
        elif kind not in ("task", "oracle", "test"):
            bad.append(f"unknown evidence kind in {ref!r}")
    return bad


def compute() -> Dict[str, Any]:
    reg = load_registry()
    with open(COVERAGE, encoding="utf-8") as fh:
        cov = (json.load(fh) or {}).get("coverage") or {}
    caps = capabilities(reg)
    cap_ids = {c["id"] for c in caps}
    task_ids = _task_ids()
    oracle_ids = set(registered())

    # integrity of the evidence file
    bad_caps = [k for k in cov if k not in cap_ids]
    bad_refs: List[str] = []
    for cid, dims in cov.items():
        for dim, ev in (dims or {}).items():
            bad_refs.extend(check_evidence(ev or [], task_ids, oracle_ids))

    rows = []
    for cap in caps:
        required = list(cap.get("required_dims") or [])
        have = cov.get(cap["id"]) or {}
        covered = [d for d in required if have.get(d)]
        missing = [d for d in required if not have.get(d)]
        rows.append({
            "id": cap["id"], "domain": cap.get("domain"), "mutates": cap.get("mutates"),
            "required": required, "missing": missing,
            "covered": len(covered), "n": len(required),
        })

    total_cells = sum(r["n"] for r in rows)
    covered_cells = sum(r["covered"] for r in rows)
    gap_caps = [r for r in rows if r["missing"]]
    return {
        "n_capabilities": len(rows),
        "total_cells": total_cells,
        "covered_cells": covered_cells,
        "coverage": (covered_cells / total_cells) if total_cells else 0.0,
        "n_capabilities_with_gaps": len(gap_caps),
        "rows": rows,
        "bad_capability_refs": bad_caps,
        "bad_evidence_refs": bad_refs,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--min", type=float, default=0.80,
                    help="minimum cell coverage for --strict")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    report = compute()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"capabilities: {report['n_capabilities']}  "
              f"cells: {report['covered_cells']}/{report['total_cells']} "
              f"= {report['coverage']:.1%}  "
              f"capabilities with gaps: {report['n_capabilities_with_gaps']}")
        if report["bad_capability_refs"]:
            print("ERROR unknown capability ids in coverage.json:", report["bad_capability_refs"])
        if report["bad_evidence_refs"]:
            print("ERROR unresolved evidence refs:", report["bad_evidence_refs"])
        print("--- gaps (capability: missing dims) ---")
        for r in report["rows"]:
            if r["missing"]:
                print(f"  [{r['domain']:12s}] {r['id']:34s} missing {r['missing']}")

    if report["bad_capability_refs"] or report["bad_evidence_refs"]:
        return 2
    if args.strict and report["coverage"] < args.min:
        print(f"STRICT FAIL: coverage {report['coverage']:.1%} < {args.min:.0%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
