"""Shared helpers for the EXT track (DESIGN §25).

Everything here is protocol-neutral: paths, hashing, the reference SUT used by
the E0 smoke harness, and the eight-state outcome enum.  Per-benchmark
adapters live under ``external/<ext_id>/adapter/adapter.py`` and must not
implement their own scoring (DESIGN §25.5).
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))


def ext_dir(ext_id: str) -> str:
    return os.path.join(HERE, ext_id)


def vendor_dir(ext_id: str) -> str:
    return os.path.join(ext_dir(ext_id), "vendor")


def data_dir(ext_id: str) -> str:
    return os.path.join(ext_dir(ext_id), "data")


def results_dir(ext_id: str) -> str:
    d = os.path.join(ext_dir(ext_id), "results")
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------------------
# hashing
# --------------------------------------------------------------------------
def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dir_digest(root: str, patterns: Optional[Tuple[str, ...]] = None) -> Tuple[str, int, int]:
    """Deterministic digest of a directory tree.

    Returns ``(digest, n_files, total_bytes)``.  Files are visited in sorted
    relative-path order; each contributes ``relpath\\0size\\0sha256``.  Only
    files whose relative path contains one of ``patterns`` (if given) count.
    """
    h = hashlib.sha256()
    n = 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if patterns and not any(p in rel for p in patterns):
                continue
            try:
                size = os.path.getsize(full)
                digest = sha256_file(full)
            except OSError:
                continue
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update(str(size).encode("ascii"))
            h.update(b"\0")
            h.update(digest.encode("ascii"))
            h.update(b"\n")
            n += 1
            total += size
    return h.hexdigest(), n, total


# --------------------------------------------------------------------------
# dataset presence helper (adapters report a precise gap, never crash)
# --------------------------------------------------------------------------
def require_path(path: str, what: str) -> str:
    if not os.path.exists(path):
        raise DatasetUnavailable(f"{what} not present at {path}")
    return path


class DatasetUnavailable(RuntimeError):
    """Raised when a benchmark's data has not been materialised.

    The E0 harness maps this to ``BLOCKED`` (data) rather than a harness bug.
    """


class UpstreamUnavailable(RuntimeError):
    """Raised by ``score()`` when the official evaluator cannot run offline.

    Examples: a paid LLM judge, a missing upstream grader module, or a gated
    resource.  Maps to ``BLOCKED`` / ``LICENSE_REQUIRED`` in E0 -- never to a
    silent pass.
    """


# --------------------------------------------------------------------------
# reference SUT (E0 only; never a benchmark result)
# --------------------------------------------------------------------------
class NullSUT:
    """A SUT stand-in for the E0 skeleton.

    It returns a fixed empty (or explicitly configured) string. It never reads
    gold/reference fields. It exists so the E0 harness
    can exercise the full ``build_input -> run_task -> score`` lifecycle
    without any model, network, or API key.
    """

    def __init__(self, default: str = ""):
        self.default = default
        self.calls: List[Any] = []

    def __call__(self, observation: Any) -> Dict[str, Any]:
        self.calls.append(observation)
        return {"text": self.default, "trace": [], "artifacts": {}}


# --------------------------------------------------------------------------
# small IO
# --------------------------------------------------------------------------
def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_jsonl(path: str, limit: Optional[int] = None) -> List[Any]:
    rows: List[Any] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)


# --------------------------------------------------------------------------
# vendored package loading
# --------------------------------------------------------------------------
def ensure_vendor_package(alias: str, vendor_path: str, shims: Optional[Dict[str, Any]] = None):
    """Register ``vendor_path`` as a package named ``alias`` (no sys.path edit).

    Upstream trees are imported WITHOUT being added to ``sys.path`` so their
    top-level modules (e.g. ``types.py``) cannot shadow the standard library.
    Optional ``shims`` are inserted into ``sys.modules`` only if absent.
    """
    import sys
    import types

    for name, mod in (shims or {}).items():
        sys.modules.setdefault(name, mod)
    mod = sys.modules.get(alias)
    if mod is None:
        mod = types.ModuleType(alias)
        mod.__path__ = [vendor_path]
        sys.modules[alias] = mod
    return mod


def blobfile_shim():
    """A minimal ``blobfile`` stand-in: ``BlobFile`` == builtins.open."""
    import builtins
    import types

    bf = types.ModuleType("blobfile")
    bf.BlobFile = lambda path, mode="rb": builtins.open(path, mode)  # type: ignore[attr-defined]
    return bf


# --------------------------------------------------------------------------
# adapter registry
# --------------------------------------------------------------------------
# Only benchmarks BrachyBot can actually participate in are included.  The
# MedAgentBench / MedCTA / PhysicianBench / HealthAgentBench candidates need
# FHIR / EHR / HL7 / terminal capability (or paid APIs / gated data) that
# BrachyBot does not have, so they are excluded and recorded under
# ``external/excluded/`` (see external/README.md).
_ADAPTERS = {
    "EXT-1": ("EXT-1.adapter.adapter", "AbraAdapter"),
    "EXT-2": ("EXT-2.adapter.adapter", "HealthBenchAdapter"),
    "EXT-3": ("EXT-3.adapter.adapter", "MedSafetyAdapter"),
    "EXT-4": ("EXT-4.adapter.adapter", "MedMemoryAdapter"),
    "EXT-9": ("EXT-9.adapter.adapter", "LongMemEvalAdapter"),
    "EXT-10": ("EXT-10.adapter.adapter", "MedHalluAdapter"),
    "EXT-11": ("EXT-11.adapter.adapter", "MedCalcAdapter"),
    "EXT-12": ("EXT-12.adapter.adapter", "AgentClinicAdapter"),
    "EXT-13": ("EXT-13.adapter.adapter", "AmegaAdapter"),
    "EXT-14": ("EXT-14.adapter.adapter", "MedPhysBenchAdapter"),
    "EXT-15": ("EXT-15.adapter.adapter", "MedicalAgentsBenchAdapter"),
}


def _pkg_dir(ext_id: str) -> str:
    return os.path.join(HERE, ext_id.replace("-", "_"))


def load_adapter(ext_id: str):
    """Import and instantiate the adapter for ``ext_id``.

    Adapter packages live at ``external/EXT-N/adapter/``; ``EXT-N`` is not a
    valid Python package name, so we register it as ``EXT_N`` on the fly.
    """
    import importlib
    import sys

    if ext_id not in _ADAPTERS:
        raise KeyError(f"unknown ext_id {ext_id!r}")
    module_name, class_name = _ADAPTERS[ext_id]
    pkg = ext_id.replace("-", "_")
    pkg_path = os.path.join(HERE, pkg)
    if pkg not in sys.modules:
        import types

        pkg_mod = types.ModuleType(pkg)
        pkg_mod.__path__ = [pkg_path]
        sys.modules[pkg] = pkg_mod
        adapter_pkg = os.path.join(pkg_path, "adapter")
        adapter_mod = types.ModuleType(f"{pkg}.adapter")
        adapter_mod.__path__ = [adapter_pkg]
        sys.modules[f"{pkg}.adapter"] = adapter_mod
        sys.path.insert(0, HERE)
        sys.path.insert(0, adapter_pkg)
    mod = importlib.import_module(module_name)
    return getattr(mod, class_name)()
