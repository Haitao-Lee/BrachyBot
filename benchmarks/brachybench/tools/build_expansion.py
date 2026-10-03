#!/usr/bin/env python3
"""Build the K/L/H/F thin-rail expansion from ``tools/specs/*_tasks.py``.

One generator guarantees schema consistency across all four tracks and keeps
shared files (``_negatives.json``, ``capabilities/coverage.json``) single-writer.
The auto quality machine (``tests/test_coverage_scenarios.py``) then proves every
emitted scenario is discriminating: the safe replay must give ``Meets`` and the
unsafe/negative observation must give ``Does not meet``.

Spec entry contract (each element of the spec module's ``TASKS``)::

    {
      "task":    { ...task.schema.json doc... },   # fixture.initial_state_hash
                                                     filled later by build_fixtures
      "obs_pos": { ... },   # written to tests/replay/<id>.json  (-> Meets)
      "obs_neg": { ... },   # written to tests/replay/_negatives.json[id] (-> Does not meet)
      "coverage": { capability_id: { "F": ["oracle:x","task:id"], ... } },
    }

Modes::

    python tools/build_expansion.py --spec tools/specs/K_tasks.py --prove --dry-run
        # load ONE spec, prove pos/neg for every task via the oracle dispatch,
        # write nothing.  Per-track authoring runs this to self-verify.

    python tools/build_expansion.py
        # emit every spec -> tasks/ + tests/replay/ + merge _negatives.json and
        # coverage.json (single process, no races).

Observation contract per oracle is in ``tools/run_task.py`` (generic checks read
``obs["oracle_inputs"][check]`` with ``check(**kwargs)``; bespoke checks read
``terminal_state``/``ui_state``/``claims``/``trace``/``evidence_ctx``/``audit``/
``dose``).  Author against the real ``oracles/*.py`` ``check()`` signatures.
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import sys
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BB)

from oracles import Verdict, registered as _registered  # noqa: E402
from tools import run_task as rt  # noqa: E402
from validate import parse_yaml_lite  # noqa: E402

_REGISTERED_ORACLES = set(_registered())


def _valid_capability_ids() -> set:
    reg = parse_yaml_lite(
        open(os.path.join(BB, "capabilities", "registry.yaml"), encoding="utf-8").read()
    )
    return {c["id"] for dom in (reg.get("domains") or []) for c in (dom.get("capabilities") or [])}


_VALID_CAPS = _valid_capability_ids()

def _canon(o: Any) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


SPECS_DIR = os.path.join(HERE, "specs")
TASKS_DIR = os.path.join(BB, "tasks")
REPLAY_DIR = os.path.join(BB, "tests", "replay")
NEG_PATH = os.path.join(REPLAY_DIR, "_negatives.json")
COVERAGE_PATH = os.path.join(BB, "capabilities", "coverage.json")

#: fields that belong to the task doc (task.schema.json) vs spec-only keys.
SPEC_ONLY = {"task", "obs_pos", "obs_neg", "coverage"}

#: Authors occasionally pass a *dimension* letter where a track id is expected.
#: Normalise onto the nearest real track (E=robustness/recovery, D2=system
#: security, I=communication/internationalisation) so the schema enum holds.
_TRACK_ALIASES = {"R": "E", "S": "D2", "P": "I"}


def _load_module(path: str):
    name = "brachy_spec_" + os.path.basename(path).replace(".py", "")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _iter_entries(path: str) -> List[Dict[str, Any]]:
    mod = _load_module(path)
    return list(getattr(mod, "TASKS", []))


def prove_entry(entry: Dict[str, Any]) -> Tuple[bool, str]:
    """Score one entry's positive and negative through the oracle dispatch."""
    task = entry["task"]
    setup = (task.get("fixture") or {}).get("setup_script") or ""
    initial = rt.load_initial_state(task) if setup.endswith(".py") else {}
    ok = True
    detail = []
    for label, obs, want in (("pos", entry["obs_pos"], Verdict.MEETS.value),
                             ("neg", entry["obs_neg"], Verdict.DOES_NOT_MEET.value)):
        try:
            out = rt.evaluate(task, obs, initial)
        except Exception as exc:  # noqa: BLE001 -- report and count as a failure
            return False, f"{label}: dispatch error {type(exc).__name__}: {exc}"
        got = out.get("verdict")
        detail.append(f"{label}->{got}")
        if got != want:
            ok = False
    return ok, " ".join(detail)


def _specificity_defects(entries: List[Dict[str, Any]]) -> List[str]:
    """Entries whose identical observation is reused across different constructs.

    A task must exercise *its own* construct.  Identical ``(obs_pos, obs_neg)``
    under one check across different constructs is a defect unless the members
    are a legitimate expression/outcome family (one shared ``paraphrase_group``
    or ``contrast_family_id``), a decision-surface ``tool_call_boundary`` set, or
    a degenerate-input restraint set.
    """
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for e in entries:
        t = e["task"]
        key = ((t.get("oracle") or {}).get("check"),
               _canon(e["obs_pos"]), _canon(e["obs_neg"]))
        groups.setdefault(key, []).append(e)
    bad: List[str] = []
    for key, mem in groups.items():
        if len(mem) < 2:
            continue
        check = key[0]
        if check == "tool_call_boundary":
            continue
        restraint = all(
            (m["task"].get("oracle") or {}).get("check") == "forbidden_reachable"
            and "no_costly_tool_call" in ((m["task"].get("oracle") or {}).get("forbidden_predicates") or [])
            for m in mem)
        if restraint:
            continue
        cons = {m["task"].get("construct") for m in mem}
        pgs = {(m["task"].get("anti_gaming") or {}).get("paraphrase_group") for m in mem}
        fams = {(m["task"].get("unit") or {}).get("contrast_family_id") for m in mem}
        if len(cons) == 1 and len(pgs) == 1 and None not in pgs:
            continue
        if len(fams) == 1 and None not in fams:
            continue
        bad.extend(m["task"]["id"] for m in mem)
    return sorted(set(bad))


def emit(entries: List[Dict[str, Any]], *, dry_run: bool) -> int:
    negatives: Dict[str, Any] = {}
    coverage: Dict[str, Any] = {}
    new_ids: List[str] = []
    failures: List[str] = []

    for entry in entries:
        task = entry["task"]
        tid = task["id"]
        new_ids.append(tid)
        if task.get("track") in _TRACK_ALIASES:
            task["track"] = _TRACK_ALIASES[task["track"]]
        task.setdefault("fixture", {}).setdefault("initial_state_hash", "sha256:pending")

        ok, msg = prove_entry(entry)
        if not ok:
            failures.append(f"{tid}: {msg}")
            continue

        if dry_run:
            continue

        with open(os.path.join(TASKS_DIR, f"{tid}.json"), "w", encoding="utf-8") as fh:
            json.dump(task, fh, ensure_ascii=False, indent=2)
        with open(os.path.join(REPLAY_DIR, f"{tid}.json"), "w", encoding="utf-8") as fh:
            json.dump(entry["obs_pos"], fh, ensure_ascii=False, indent=2)
        negatives[tid] = entry["obs_neg"]
        for cap, dims in (entry.get("coverage") or {}).items():
            if cap not in _VALID_CAPS:
                # an author used a non-registry capability key; drop it rather
                # than poison the evidence index (the task itself still exists).
                continue
            bucket = coverage.setdefault(cap, {})
            for dim, ev in (dims or {}).items():
                have = bucket.setdefault(dim, [])
                for ref in ev or []:
                    # drop oracle refs that do not name a registered checker
                    # (e.g. the bespoke ``pred`` pseudo-check); the task ref
                    # remains the honest evidence for that cell.
                    if ref.startswith("oracle:") and ref.split(":", 1)[1] not in _REGISTERED_ORACLES:
                        continue
                    if ref not in have:
                        have.append(ref)

    if failures:
        print(f"FAIL: {len(failures)}/{len(entries)} entry(ies) not discriminating")
        for f in failures[:40]:
            print("  " + f)
        return 1

    if dry_run:
        spec_defects = _specificity_defects(entries)
        if spec_defects:
            print(f"SPECIFICITY FAIL: {len(spec_defects)} entry(ies) reuse an "
                  f"identical observation across different constructs: {spec_defects[:12]}")
            return 1
        print(f"OK (dry-run): {len(new_ids)} entries all discriminate "
              f"(pos->Meets, neg->Does not meet) + specificity clean")
        return 0

    if negatives:
        existing = {}
        if os.path.isfile(NEG_PATH):
            with open(NEG_PATH, encoding="utf-8") as fh:
                existing = json.load(fh) or {}
        existing.update(negatives)
        with open(NEG_PATH, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, ensure_ascii=False, indent=2, sort_keys=True)

    if coverage:
        doc = {}
        if os.path.isfile(COVERAGE_PATH):
            with open(COVERAGE_PATH, encoding="utf-8") as fh:
                doc = json.load(fh) or {}
        cov = doc.setdefault("coverage", {})
        for cap, dims in coverage.items():
            bucket = cov.setdefault(cap, {})
            for dim, ev in dims.items():
                have = bucket.setdefault(dim, [])
                for ref in ev:
                    if ref not in have:
                        have.append(ref)
        doc.setdefault("_note", "generated evidence index; tools/coverage.py enforces it")
        with open(COVERAGE_PATH, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"OK: emitted {len(new_ids)} tasks -> tasks/ + tests/replay/ + merged "
          f"{len(negatives)} negatives + {len(coverage)} coverage caps")
    return 0


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", action="append",
                    help="spec module(s) to build; default = tools/specs/*_tasks.py")
    ap.add_argument("--prove", action="store_true", help="score pos/neg and report")
    ap.add_argument("--dry-run", action="store_true", help="write nothing")
    args = ap.parse_args(argv)

    paths = args.spec or sorted(glob.glob(os.path.join(SPECS_DIR, "*_tasks.py")))
    if not paths:
        print("no spec modules found", file=sys.stderr)
        return 1

    entries: List[Dict[str, Any]] = []
    for p in paths:
        for e in _iter_entries(p):
            entries.append(e)

    # global id uniqueness across every spec
    seen = set()
    dup = [e["task"]["id"] for e in entries if e["task"]["id"] in seen or seen.add(e["task"]["id"])]
    if dup:
        print(f"FAIL: duplicate task ids {dup}", file=sys.stderr)
        return 1

    if args.prove or args.dry_run:
        return emit(entries, dry_run=True)
    return emit(entries, dry_run=False)


if __name__ == "__main__":
    raise SystemExit(main())
