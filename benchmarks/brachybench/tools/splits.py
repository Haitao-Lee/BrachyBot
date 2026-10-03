#!/usr/bin/env python3
"""Dataset splits (DESIGN §12.6, N7) -- four sets, five split levels.

The whole point of the four-way split is that **only the sealed set produces
confirmatory conclusions** and that Pilot results can never be used to revise
the sealed items.  Splitting happens at five levels (N7) so that nothing
leaks across the boundary:

    L1 patient | L2 task template | L3 fault mechanism |
    L4 scenario combination | L5 attack source

    python tools/splits.py build --tasks tasks/ --seed 20260929 --out splits/
    python tools/splits.py check --tasks tasks/ --splits splits/assignment.json --seed 20260929

``check`` verifies (a) no leakage across the five levels and (b) that a rebuild
with the recorded seed reproduces the published assignment byte for byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from collections import defaultdict
from typing import Any, Dict, List, Sequence, Tuple

LEVELS = ("patient", "task_template", "fault_mechanism", "scenario_combo", "attack_source")


def _levels_of(task: Dict[str, Any]) -> Dict[str, str]:
    """Five-level key of a task, derived from its fixture/construct/provenance."""
    fix = task.get("fixture") or {}
    prov = task.get("provenance") or {}
    anti = task.get("anti_gaming") or {}
    family = str(fix.get("case_family") or "")
    # the whole slug is the patient identity ("case_0_x", not "case")
    patient = family.split("/", 1)[1] if "/" in family else family
    # L2 "task template": for property-based fixtures the *probed mechanism* is
    # the template (the generator name alone would merge 25 independent
    # configurations into one component and make the split degenerate).
    mech = ((task.get("oracle") or {}).get("config") or {}).get("mechanism")
    template = f"{task.get('construct')}::{mech}" if mech else str(task.get("construct") or "")
    # L3 "fault mechanism": the *property* being probed, not the shared
    # provenance string -- 150 generated fixtures that all cite the same
    # generator would otherwise collapse into a single component and make the
    # split degenerate.
    mech = (task.get("oracle") or {}).get("config") or {}
    derived = str(prov.get("derived_from") or "")
    if "#" in derived:
        fault = derived.split("#")[-1]
    elif mech.get("mechanism"):
        fault = str(mech["mechanism"])
    else:
        # Different IDs are not independent mechanisms. Conservative shared
        # grouping is preferable to manufacturing a healthy-looking split.
        fault = str(task.get("construct") or "unknown_mechanism")
    combo = f"{patient}|{template}|{task.get('cost_class')}"
    # L5 "attack source" is where adversarial content enters (tool return / OCR
    # / file metadata).  A task with no contrast family has NO attack source, so
    # the level must be *inactive* -- keying it on the generator family would
    # merge 25 independent configurations into one component.
    contrast = str(anti.get("contrast_family_id") or "")
    attack = contrast.split("/", 1)[0] if contrast.startswith(("D1", "D2", "security", "injection")) else "none"
    return {
        "patient": patient,
        "task_template": template,
        "fault_mechanism": fault,
        "scenario_combo": combo,
        "attack_source": attack,
    }


def build(tasks: Sequence[Dict[str, Any]], *, seed: int,
          dev=0.10, pilot=0.15, sealed=0.30) -> Dict[str, Any]:
    """Assign each task to exactly one of {dev, pilot, public, sealed}.

    Assignment is by **group of the five-level key**, never per task, so that
    e.g. all tasks from one patient land in one split (N7 L1).
    """
    rng = random.Random(seed)
    task_ids = [str(t.get("id") or "") for t in tasks]
    if any(not i for i in task_ids) or len(set(task_ids)) != len(task_ids):
        raise ValueError("split commitments require unique nonempty task IDs")
    groups = _connected_groups(tasks)
    keys = sorted(groups)
    rng.shuffle(keys)
    n = len(keys)
    n_dev, n_pilot, n_sealed = int(round(n * dev)), int(round(n * pilot)), int(round(n * sealed))
    buckets = {
        "dev": keys[:n_dev],
        "pilot": keys[n_dev:n_dev + n_pilot],
        "sealed": keys[n_dev + n_pilot:n_dev + n_pilot + n_sealed],
    }
    buckets["public"] = keys[n_dev + n_pilot + n_sealed:]
    out = {"seed": seed, "levels": list(LEVELS), "splits": {}, "groups": len(keys),
           "tasks": len(tasks)}
    for name, ks in buckets.items():
        ids = sorted(i for k in ks for i in groups[k])
        out["splits"][name] = {
            "task_index": ids,
            "task_ids": sorted(task_ids[i] for i in ids),
            "n_tasks": len(ids),
            "group_keys": ["|".join(k) for k in ks],
            "sha256": hashlib.sha256(
                json.dumps(sorted((task_ids[i], hashlib.sha256(json.dumps(tasks[i], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()) for i in ids),
                           separators=(",", ":")).encode()).hexdigest(),
        }
    out["sealed_manifest_only"] = True   # DESIGN §19.2: sealed ships as a hash
    out["commitment_version"] = "task_id_and_canonical_content_v2"
    out["secrecy_verified"] = False
    out["note"] = "Split membership does not make previously public tasks unseen or secret."
    out["counts"] = {k: v["n_tasks"] for k, v in out["splits"].items()}
    return out


def _connected_groups(tasks: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, ...], List[int]]:
    """N7: tasks sharing **any** level value are one indivisible group.

    Grouping only on the 5-tuple would still let two tasks that share a patient
    land in different splits (the leak this whole design exists to prevent).
    We therefore take connected components of the graph "linked iff they share
    at least one level value", then key each component by its full level tuple.
    """
    parent = list(range(len(tasks)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    levels = [_levels_of(t) for t in tasks]
    owner: Dict[str, int] = {}
    for i, lv in enumerate(levels):
        for lvl in LEVELS:
            val = lv[lvl]
            if val in ("none", "", None):
                continue          # the level is inactive for this task
            key = f"{lvl}:{val}"
            if key in owner:
                union(owner[key], i)
            else:
                owner[key] = i

    comps: Dict[int, List[int]] = defaultdict(list)
    for i in range(len(tasks)):
        comps[find(i)].append(i)
    out: Dict[Tuple[str, ...], List[int]] = {}
    for members in comps.values():
        key = min(tuple(levels[i][k] for k in LEVELS) for i in members)
        out[key] = sorted(members)
    return out


def check_leakage(tasks: Sequence[Dict[str, Any]], splits: Dict[str, Any]) -> List[str]:
    """No connected component may straddle two splits (N7)."""
    groups = _connected_groups(tasks)
    bad: List[str] = []
    for key, members in groups.items():
        where = set()
        for name, blk in (splits.get("splits") or {}).items():
            idx = set(blk.get("task_index") or [])
            if idx & set(members):
                where.add(name)
        if len(where) > 1:
            bad.append(f"leak at group {'|'.join(key)}: members {members} span {sorted(where)}")
    return bad


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "check"):
        p = sub.add_parser(name)
        p.add_argument("--tasks", required=True)
        p.add_argument("--seed", type=int, default=20260929)
        if name == "build":
            p.add_argument("--out", required=True)
        else:
            p.add_argument("--splits", required=True)
    args = ap.parse_args(argv)

    # recursive: generated fixtures live under tasks/physics/ (N7 still has to
    # see them, since a shared patient/template level must not straddle splits)
    tasks = []
    for dirpath, dirs, files in os.walk(args.tasks):
        dirs.sort()
        for fn in sorted(files):
            if fn.endswith(".json"):
                with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                    tasks.append(json.load(fh))

    if args.cmd == "build":
        doc = build(tasks, seed=args.seed)
        os.makedirs(args.out, exist_ok=True)
        path = os.path.join(args.out, "assignment.json")
        # sealed ships as a commitment only
        sealed = doc["splits"]["sealed"]
        with open(os.path.join(args.out, "sealed.manifest.sha256"), "w", encoding="utf-8") as fh:
            fh.write(sealed["sha256"] + "\n")
        n_sealed = sealed["n_tasks"]
        doc["splits"]["sealed"] = {"task_index": [], "task_ids": [], "group_keys": [],
                                   "n_tasks": n_sealed,
                                   "sha256": sealed["sha256"],
                                   "note": "membership commitment only; secrecy of the underlying tasks is NOT established"}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, sort_keys=True)
        for k, v in doc["splits"].items():
            shown = v.get("n_tasks", len(v["task_index"]))
            print(f"  {k:8s} {shown:4d} tasks  {len(v['group_keys']):3d} groups  "
                  f"sha256={v['sha256'][:12]}")
        print(f"  total {sum(v.get('n_tasks', len(v['task_index'])) for v in doc['splits'].values())} tasks")
        print(f"  connected components: {doc['groups']}")
        print(f"wrote {path}")
        return 0

    with open(args.splits, encoding="utf-8") as fh:
        splits = json.load(fh)
    if splits.get("commitment_version") != "task_id_and_canonical_content_v2":
        print("BLOCKED: legacy index-only commitment does not bind task content. Preserve it as historical evidence; create a separately versioned split.", file=sys.stderr)
        return 2
    leaks = check_leakage(tasks, splits)
    if leaks:
        print("FAIL: cross-split leakage", file=sys.stderr)
        for b in leaks[:20]:
            print("  " + b, file=sys.stderr)
        return 1
    rebuilt = build(tasks, seed=args.seed)
    for name in ("dev", "pilot", "sealed", "public"):
        a = splits["splits"][name]["sha256"]
        b = rebuilt["splits"][name]["sha256"]
        if a != b:
            print(f"FAIL: {name} sha256 drift {a[:12]} != {b[:12]}", file=sys.stderr)
            return 1
    print("OK: no five-level leakage, rebuild reproduces the published assignment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
