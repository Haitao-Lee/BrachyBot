#!/usr/bin/env python3
"""Recompute ``initial_state_hash`` for every task (BA-15).

Seed tasks previously carried placeholder hashes, so the frozen initial state
was unverifiable.  This tool runs each task's ``fixture.setup_script`` and
rewrites ``initial_state_hash`` from the real canonical CWS.  The test suite
re-runs it in check mode, so a fixture change cannot silently drift.

    python tools/build_fixtures.py            # rewrite hashes
    python tools/build_fixtures.py --check    # fail on drift (CI gate)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from typing import Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BB)
from fixtures import hash_cws  # noqa: E402


def _load(path: str):
    spec = importlib.util.spec_from_file_location(
        "brachy_fixture_" + os.path.basename(path).replace(".py", ""), path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def compute(task_path: str) -> Tuple[str, Dict]:
    with open(task_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    rel = doc["fixture"]["setup_script"]
    setup = os.path.join(BB, rel)
    if not os.path.isfile(setup):
        raise FileNotFoundError(f"{task_path}: setup_script not found: {rel}")
    state = _load(setup).build()
    return hash_cws(state), doc


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root", default=BB)
    args = ap.parse_args(argv)

    tdir = os.path.join(args.root, "tasks")
    drift: List[str] = []
    n = 0
    for fn in sorted(os.listdir(tdir)):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(tdir, fn)
        n += 1
        digest, doc = compute(p)
        want = doc["fixture"]["initial_state_hash"]
        if want == digest:
            continue
        drift.append(f"{fn}: {want} -> {digest}")
        if not args.check:
            doc["fixture"]["initial_state_hash"] = digest
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
    if args.check and drift:
        print("FAIL initial_state_hash drift:", file=sys.stderr)
        for d in drift:
            print("  " + d, file=sys.stderr)
        return 1
    if args.check:
        print(f"OK: {n} tasks, hashes match fixtures")
    else:
        print(f"rewrote {len(drift)} of {n} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
