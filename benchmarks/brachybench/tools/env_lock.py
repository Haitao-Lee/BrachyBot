#!/usr/bin/env python3
"""Environment lock (DESIGN §11.5) -- ``environment.json`` capture and verify.

A reproducibility claim needs more than a version list: model weight hashes
and the **deterministic-kernel flags** decide whether ``PRR_artifact = 1.0`` is
even a meaningful requirement (R2/R11).  ``plans/dose_pre/inference.py`` ships
with ``cudnn.benchmark = True`` and ``allow_tf32 = True`` -- both must be off
during evaluation.

    python tools/env_lock.py write --out environment.json
    python tools/env_lock.py check --file environment.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from typing import Any, Dict, List

DETERMINISM_KEYS = (
    "torch.backends.cudnn.benchmark",
    "torch.backends.cudnn.allow_tf32",
    "torch.backends.cuda.matmul.allow_tf32",
)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(weight_paths: List[str] = ()) -> Dict[str, Any]:
    env: Dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }
    for mod in ("numpy", "scipy", "skimage", "SimpleITK", "torch", "pydicom"):
        try:
            m = __import__(mod)
            env[mod] = getattr(m, "__version__", "unknown")
        except Exception:  # noqa: BLE001
            env[mod] = None
    # deterministic-kernel flags
    flags: Dict[str, Any] = {}
    try:
        import torch
        for k in DETERMINISM_KEYS:
            obj = torch
            for part in k.split(".")[1:]:
                obj = getattr(obj, part, None)
                if obj is None:
                    break
            flags[k] = obj if not callable(obj) else None
        flags["torch.use_deterministic_algorithms"] = bool(
            torch.are_deterministic_algorithms_enabled())
    except Exception:  # noqa: BLE001
        for k in DETERMINISM_KEYS:
            flags[k] = None
    env["determinism"] = flags
    env["deterministic_kernels"] = all(
        flags.get(k) is False for k in DETERMINISM_KEYS
    ) and flags.get("torch.use_deterministic_algorithms") is True
    env["weight_sha256"] = {
        os.path.basename(p): _sha256_file(p) for p in weight_paths if os.path.isfile(p)
    }
    return env


def check(doc: Dict[str, Any], weight_paths: List[str] = ()) -> List[str]:
    """Return a list of drift problems (empty == locked)."""
    bad: List[str] = []
    now = collect()
    for k in ("python", "numpy", "scipy", "skimage", "SimpleITK", "torch"):
        if k in doc and doc[k] != now.get(k):
            bad.append(f"{k}: locked {doc[k]!r} != current {now.get(k)!r}")
    for k in DETERMINISM_KEYS:
        if k in (doc.get("determinism") or {}) and doc["determinism"].get(k) != now["determinism"].get(k):
            bad.append(f"determinism {k}: locked {doc['determinism'].get(k)} != current {now['determinism'].get(k)}")
    for name, digest in (doc.get("weight_sha256") or {}).items():
        paths = [p for p in weight_paths if os.path.basename(p) == name]
        if not paths:
            bad.append(f"weight {name}: not supplied for verification")
            continue
        if _sha256_file(paths[0]) != digest:
            bad.append(f"weight {name}: checksum mismatch")
    return bad


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("--out", required=True)
    w.add_argument("--weight", action="append", default=[])
    c = sub.add_parser("check")
    c.add_argument("--file", required=True)
    c.add_argument("--weight", action="append", default=[])
    args = ap.parse_args(argv)

    if args.cmd == "write":
        doc = collect(args.weight)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, sort_keys=True)
        ok = doc.get("deterministic_kernels")
        print(f"wrote {args.out}")
        print(f"  deterministic_kernels = {ok}")
        if not ok:
            print("  WARN: R2/R11 PRR_artifact=1.0 is not required while "
                  "cudnn.benchmark/allow_tf32 are on (§11.5)", file=sys.stderr)
        return 0

    with open(args.file, encoding="utf-8") as fh:
        doc = json.load(fh)
    bad = check(doc, args.weight)
    if bad:
        print("FAIL: environment drift", file=sys.stderr)
        for b in bad:
            print("  " + b, file=sys.stderr)
        return 1
    print("OK: environment matches the lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
