#!/usr/bin/env python3
"""SHA-256 manifest builder / verifier (DESIGN §19.2 freeze & checksum).

Writes ``MANIFEST.sha256`` in the classic ``sha256sum`` format so it can be
verified with ``sha256sum -c`` as well as with this script.

    # build (writes MANIFEST.sha256 in --root)
    python hash_manifest.py build --root benchmarks/brachybench \
        --exclude MANIFEST.sha256 --exclude results --exclude __pycache__

    # verify (exit 1 on mismatch -- CI gate)
    python hash_manifest.py check --root benchmarks/brachybench

Sealed sets ship **only** their manifest (commitment scheme, §13.5).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from typing import Iterable, List, Tuple

MANIFEST_NAME = "MANIFEST.sha256"


def _iter_files(root: str, exclude: Iterable[str]) -> List[str]:
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in exclude and not any(os.path.join(rel_dir, d).startswith(e) for e in exclude)
        )
        for fn in sorted(filenames):
            rel = os.path.normpath(os.path.join(rel_dir, fn))
            if rel in (".", MANIFEST_NAME):
                continue
            if any(rel == e or rel.startswith(e + os.sep) for e in exclude):
                continue
            out.append(rel)
    return out


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(root: str, exclude: Iterable[str]) -> Tuple[int, str]:
    rels = _iter_files(root, exclude)
    lines = [f"{_sha256(os.path.join(root, r))}  {r}" for r in rels]
    text = "\n".join(lines) + ("\n" if lines else "")
    out = os.path.join(root, MANIFEST_NAME)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    return len(rels), out


def check(root: str) -> List[str]:
    path = os.path.join(root, MANIFEST_NAME)
    if not os.path.isfile(path):
        return [f"missing {path}"]
    bad: List[str] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            try:
                digest, rel = line.split("  ", 1)
            except ValueError:
                bad.append(f"{path}:{lineno}: malformed line")
                continue
            full = os.path.join(root, rel)
            if not os.path.isfile(full):
                bad.append(f"missing file: {rel}")
                continue
            if _sha256(full) != digest:
                bad.append(f"checksum mismatch: {rel}")
    return bad


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "check"):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True)
        if name == "build":
            p.add_argument("--exclude", action="append", default=[])
    args = ap.parse_args(argv)

    if args.cmd == "build":
        n, out = build(args.root, set(args.exclude) | {MANIFEST_NAME, "__pycache__"})
        print(f"wrote {out} ({n} files)")
        return 0

    bad = check(args.root)
    if bad:
        print("FAIL: " + args.root, file=sys.stderr)
        for b in bad:
            print("  " + b, file=sys.stderr)
        return 1
    print("OK: " + args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
