"""Immutable recipes, bounded IO, NAS fencing and crash-safe local records."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import socket
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class Blocked(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_digest(path):
    """Content AND relative-name identity for regular DICOM directories."""
    path = Path(path)
    if path.is_file():
        return sha256(path)
    if not path.is_dir() or path.is_symlink():
        raise Blocked("SOURCE_NOT_AVAILABLE", str(path))
    files = sorted(p for p in path.rglob("*") if p.is_file())
    if not files or any(p.is_symlink() for p in path.rglob("*")):
        raise Blocked("EMPTY_OR_LINKED_SOURCE_DIRECTORY")
    return digest([{ "path": p.relative_to(path).as_posix(), "sha256": sha256(p)} for p in files])


def child(root, relative):
    root = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise Blocked("UNSAFE_PATH", str(relative))
    target = (root / rel).resolve()
    if target == root or root not in target.parents:
        raise Blocked("UNSAFE_PATH", str(relative))
    return target


def load_json(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def atomic_json(path, value):
    """Same-directory atomic commit. No SQLite/WAL database on the NAS."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def mounts(path="/proc/self/mountinfo"):
    rows = []
    for line in Path(path).read_text().splitlines():
        left, right = line.split(" - ", 1)
        fields, trailing = left.split(), right.split()
        unescape = lambda x: re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), x)
        rows.append({"mount_id": fields[0], "target": unescape(fields[4]),
                     "fstype": trailing[0], "source": unescape(trailing[1])})
    return rows


class Storage:
    """Fail closed on a detached/replaced mount or insufficient capacity."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = Path(cfg["result_root"]).resolve()
        self.source = Path(cfg["source_root"]).resolve()
        self.repo = Path(cfg["source_repository"]).resolve()
        self.mount = Path(cfg["nas_mount"]).resolve()
        if not cfg.get("experiment_id") or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", cfg["experiment_id"]):
            raise Blocked("INVALID_EXPERIMENT_ID")
        if self.root == self.source or self.source in self.root.parents or self.root in self.source.parents:
            raise Blocked("RESULT_SOURCE_OVERLAP")
        if self.root == self.repo or self.repo in self.root.parents or self.root in self.repo.parents:
            raise Blocked("RESULT_REPOSITORY_OVERLAP")
        if self.mount not in self.root.parents:
            raise Blocked("RESULT_NOT_ON_NAS")
        self.identity = self._mount_identity()
        self.base = child(self.root, cfg["experiment_id"])
        self._usage_checked_at = 0
        self._usage_bytes = 0

    def _mount_identity(self):
        candidates = [m for m in mounts() if Path(m["target"]).resolve() == self.mount]
        if len(candidates) != 1:
            raise Blocked("NAS_NOT_MOUNTED", str(self.mount))
        m = candidates[0]
        if m["fstype"] not in self.cfg.get("nas_filesystems", ["cifs", "nfs", "nfs4"]):
            raise Blocked("UNEXPECTED_NAS_FILESYSTEM")
        if self.cfg.get("nas_source") and m["source"] != self.cfg["nas_source"]:
            raise Blocked("NAS_SOURCE_CHANGED")
        return m

    def check(self, reserve=0):
        if self._mount_identity() != self.identity:
            raise Blocked("NAS_MOUNT_CHANGED")
        if self.mount not in self.root.resolve().parents:
            raise Blocked("NAS_PATH_CHANGED")
        free = shutil.disk_usage(self.mount).free
        needed = int(self.cfg.get("min_nas_free_bytes", 100 * 1024**3)) + int(reserve)
        if free < needed:
            raise Blocked("NAS_SPACE_LOW", f"free={free}; required={needed}")
        local = Path(self.cfg["metadata_runtime"]).resolve()
        if self.mount == local or self.mount in local.parents:
            raise Blocked("SQLITE_RUNTIME_ON_NETWORK_FILESYSTEM")
        containing = [m for m in mounts() if Path(m["target"]) == local or Path(m["target"]) in local.parents]
        actual = max(containing, key=lambda m: len(Path(m["target"]).parts)) if containing else {"fstype": "unknown"}
        if actual["fstype"] in {"cifs", "nfs", "nfs4", "smb3", "fuse.sshfs"}:
            raise Blocked("SQLITE_RUNTIME_ON_NETWORK_FILESYSTEM")
        probe = local
        while not probe.exists():
            probe = probe.parent
        if shutil.disk_usage(probe).free < int(self.cfg.get("min_local_free_bytes", 10 * 1024**3)):
            raise Blocked("LOCAL_SPACE_LOW")
        if self.base.exists() and self.cfg.get("max_experiment_bytes") is not None:
            # CIFS tree walks on every 2-second status poll would dominate latency.
            # Capacity is always checked; retained-byte accounting is bounded/cached.
            if reserve or time.monotonic() - self._usage_checked_at > 30:
                self._usage_bytes = sum(p.stat().st_size for p in self.base.rglob("*") if p.is_file())
                self._usage_checked_at = time.monotonic()
            used = self._usage_bytes
            if used + reserve > int(self.cfg["max_experiment_bytes"]):
                raise Blocked("EXPERIMENT_STORAGE_BUDGET_EXCEEDED")
        return {"nas_free_bytes": free, "mount": self.identity}

    def initialize(self):
        self.check()
        for part in ("protocol", "resolved", "derived", "runs", "tables", "locks", "tmp", "deployment", "backend", "archive"):
            child(self.base, part).mkdir(parents=True, exist_ok=True)
        return self.base

    def path(self, relative):
        self.check()
        return child(self.base, relative)

    @contextmanager
    def lease(self, name, global_scope=False):
        """Recover only proven-dead local runners; tasks require separate reconciliation."""
        if global_scope:
            self.check()
            lock_root = child(self.root, ".cohort-locks")
            lock_root.mkdir(parents=True, exist_ok=True)
            path = child(lock_root, digest(name))
        else:
            path = self.path("locks/" + digest(name))
        from .leases import recoverable_lease
        with recoverable_lease(path, name, self.check):
            yield path


class Journal:
    def __init__(self, root, guard=lambda: None):
        self.root = Path(root)
        self.guard = guard
        self.events = self.root / "events"
        self.events.mkdir(parents=True, exist_ok=True)
        self.start = time.monotonic()

    def event(self, stage, status, **payload):
        self.guard()
        record = {"utc": utc(), "elapsed_s": time.monotonic() - self.start,
                  "stage": stage, "status": status, **payload}
        # One immutable object per event avoids interleaved JSONL writes on CIFS.
        atomic_json(self.events / f"{time.time_ns()}-{uuid.uuid4().hex}.json", record)
        return record


def finite(value, positive=False):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and (not positive or value > 0)


def sanitize(value):
    """Redact secrets, not clinical results. Results remain restricted data."""
    denied = re.compile(r"password|secret|authorization|cookie|api.?key|access.?token|refresh.?token", re.I)
    if isinstance(value, dict):
        return {k: "[REDACTED]" if denied.search(str(k)) else sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value
