#!/usr/bin/env python3
"""Task-corpus quality audit (DESIGN §36).

Flags the corpus defects that the size-expansion waves could introduce:

* **empty prompt / placeholder intent** -- a task must say something real;
* **unresolved grounding** -- ``provenance.derived_from`` must name a real file;
* **pos == neg** -- the safe and unsafe observations must differ;
* **generic observation** -- two tasks with the same ``oracle.check`` and an
  *identical* ``(obs_pos, obs_neg)`` but different ``construct`` do not test
  their own construct.  Legitimate exceptions:

  - the check is ``tool_call_boundary`` (the observation is a decision surface:
    the same decision with different wording is the point);
  - a ``forbidden_reachable`` restraint task (``no_costly_tool_call``): the
    correct outcome for every degenerate input is the same "nothing ran";
  - every member shares one ``anti_gaming.paraphrase_group`` (a G-EQ expression
    group) or one ``unit.contrast_family_id`` (a declared shared-outcome family).

Usage::

    python tools/quality_audit.py            # human report + exit 1 if defects
    python tools/quality_audit.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, ".."))

_EXEMPT_CHECKS = {"tool_call_boundary"}


def _canon(o: Any) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _is_restraint(task: Dict[str, Any]) -> bool:
    oracle = task.get("oracle") or {}
    return (oracle.get("check") == "forbidden_reachable"
            and "no_costly_tool_call" in (oracle.get("forbidden_predicates") or []))


def load() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    tasks: Dict[str, Dict[str, Any]] = {}
    for f in sorted(glob.glob(os.path.join(BB, "tasks", "**", "*.json"), recursive=True)):
        if "/physics/" in f.replace(os.sep, "/"):
            continue
        with open(f, encoding="utf-8") as fh:
            doc = json.load(fh)
        tasks[doc["id"]] = doc
    with open(os.path.join(BB, "tests", "replay", "_negatives.json"), encoding="utf-8") as fh:
        negs = json.load(fh)
    return tasks, negs


def audit() -> Dict[str, Any]:
    tasks, negs = load()
    empty_text: List[str] = []
    weak_intent: List[str] = []
    bad_ground: List[str] = []
    pos_eq_neg: List[str] = []
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}

    for tid, t in tasks.items():
        turns = (t.get("protocol") or {}).get("turns") or []
        text = " | ".join((x.get("text") or "") for x in turns).strip()
        construct = (t.get("construct") or "").lower()
        # an intentionally blank/whitespace input probe is not a defect
        empty_by_design = (any(k in construct for k in ("empty", "whitespace", "blank"))
                           or "EMPTY" in tid or "WHITESPACE" in tid)
        if not text and not empty_by_design:
            empty_text.append(tid)
        ci = (t.get("clinical_intent") or "").strip()
        if len(ci) < 4:
            weak_intent.append(tid)
        df = (t.get("provenance") or {}).get("derived_from") or ""
        # every resolved file ref must exist (full path or basename somewhere)
        repo = os.path.dirname(os.path.dirname(BB))  # .../BrachyBot
        for m in re.finditer(r"([A-Za-z0-9_./]+\.py):\d+", df):
            p = m.group(1)
            cands = [os.path.join(repo, p), os.path.join(BB, p)]
            if not any(os.path.exists(c) for c in cands) and not _basename_exists(p):
                bad_ground.append(f"{tid}:{p}")
                break
        pos_p = os.path.join(BB, "tests", "replay", f"{tid}.json")
        if os.path.exists(pos_p):
            with open(pos_p, encoding="utf-8") as fh:
                pos = json.load(fh)
            neg = negs.get(tid)
            if neg is not None and _canon(pos) == _canon(neg):
                pos_eq_neg.append(tid)
            if neg is not None:
                key = ((t.get("oracle") or {}).get("check") or "", _canon(pos), _canon(neg))
                groups.setdefault(key, []).append(t)

    generic: List[str] = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        check = key[0]
        if check in _EXEMPT_CHECKS:
            continue
        if all(_is_restraint(m) for m in members):
            continue
        constructs = {m.get("construct") for m in members}
        pgs = {((m.get("anti_gaming") or {}).get("paraphrase_group")) for m in members}
        fams = {((m.get("unit") or {}).get("contrast_family_id")) for m in members}
        if len(constructs) == 1 and len(pgs) == 1 and None not in pgs:
            continue
        if len(fams) == 1 and None not in fams:
            continue
        generic.extend(m["id"] for m in members)

    return {
        "n_tasks": len(tasks),
        "empty_text": sorted(empty_text),
        "weak_intent": sorted(weak_intent),
        "unresolved_grounding": sorted(bad_ground),
        "pos_eq_neg": sorted(pos_eq_neg),
        "generic_observation": sorted(set(generic)),
    }


_BASENAMES: set = None


def _basename_exists(p: str) -> bool:
    global _BASENAMES
    if _BASENAMES is None:
        _BASENAMES = set()
        root = os.path.dirname(os.path.dirname(BB))  # .../BrachyBot
        for dirpath, dirs, files in os.walk(root):
            if ".git" in dirpath.split(os.sep) or "__pycache__" in dirpath.split(os.sep):
                continue
            _BASENAMES.update(files)
    return os.path.basename(p) in _BASENAMES


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = audit()
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0
    print(f"tasks audited: {rep['n_tasks']}")
    for k in ("empty_text", "weak_intent", "unresolved_grounding",
              "pos_eq_neg", "generic_observation"):
        v = rep[k]
        print(f"  {k:24s} {len(v)}")
        for x in v[:5]:
            print(f"      {x}")
    total = sum(len(rep[k]) for k in ("empty_text", "weak_intent",
                                       "unresolved_grounding", "pos_eq_neg",
                                       "generic_observation"))
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
