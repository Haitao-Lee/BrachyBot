"""Durable, account-owned BrachyBot case workspaces.

The web server keeps active :class:`BrachyAgent` instances in memory for
latency, but that cache is deliberately not the source of truth.  This module
owns the durable representation used to rebuild an agent after a process
restart and to keep clinical data isolated by account and case session.

Only explicit JSON values and NumPy arrays are persisted.  Python objects,
GPU handles, and SimpleITK pipeline objects are reconstructed on load instead
of being pickled, which keeps the workspace portable and avoids deserialising
untrusted code.
"""

from __future__ import annotations

import json
import math
import os
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

import numpy as np


WORKSPACE_SCHEMA_VERSION = 1
DEFAULT_USER_QUOTA_BYTES = int(
    os.environ.get("BRACHYBOT_USER_STORAGE_QUOTA_BYTES", str(20 * 1024 ** 3))
)
TRASH_RETENTION_SECONDS = int(
    os.environ.get("BRACHYBOT_TRASH_RETENTION_DAYS", "7")
) * 24 * 60 * 60


class WorkspaceError(RuntimeError):
    """Base error for durable workspace operations."""


class WorkspaceNotFound(WorkspaceError):
    """Raised when an account cannot access the requested case session."""


class WorkspaceLeaseConflict(WorkspaceError):
    """Raised when another browser currently owns the editing lease."""


class WorkspaceQuotaExceeded(WorkspaceError):
    """Raised before a workspace exceeds its account storage limit."""


@dataclass(frozen=True)
class WorkspaceSession:
    id: str
    user_id: str
    title: str
    status: str
    created_at: float
    updated_at: float
    revision: int
    recovery_status: str
    deleted_at: Optional[float] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "WorkspaceSession":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            status=row["status"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            revision=int(row["revision"]),
            recovery_status=row["recovery_status"],
            deleted_at=(float(row["deleted_at"]) if row["deleted_at"] is not None else None),
        )

    def public_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "recovery_status": self.recovery_status,
            "deleted_at": self.deleted_at,
        }


def _now() -> float:
    return time.time()


def _safe_json(value: Any) -> Any:
    """Return a JSON-compatible value without silently serialising objects.

    The recursive array encoder intercepts ndarrays before this helper is
    reached.  Unknown values are deliberately represented as a small tagged
    value rather than by ``repr`` so a restored workspace can never mistake a
    debug string for a valid clinical result.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.generic):
        return _safe_json(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(item) for item in value]
    return {"$unsupported": type(value).__name__}


def _restore_json(value: Any) -> Any:
    """Restore numeric label-map keys that JSON necessarily converted to text."""
    if isinstance(value, list):
        return [_restore_json(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "$tuple" in value:
        return tuple(_restore_json(item) for item in value["$tuple"])
    if "$unsupported" in value:
        return None
    restored: Dict[Any, Any] = {}
    for key, item in value.items():
        restored_key: Any = key
        if isinstance(key, str) and key.lstrip("-").isdigit():
            try:
                restored_key = int(key)
            except ValueError:
                pass
        restored[restored_key] = _restore_json(item)
    return restored


class _ArtifactEncoder:
    """Stores arrays as sidecar files while recursively encoding metadata."""

    def __init__(
        self,
        root: Path,
        ensure_capacity: Optional[Callable[[Path, int], None]] = None,
        reuse_array: Optional[Callable[[str, str], Optional[str]]] = None,
        record_array: Optional[Callable[[str, str, str], None]] = None,
        array_version: Optional[Callable[[str], int]] = None,
    ):
        self.root = root
        self.arrays_dir = root / "arrays"
        self.arrays_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0
        self._ensure_capacity = ensure_capacity
        self._reuse_array = reuse_array
        self._record_array = record_array
        self._array_version = array_version

    def encode(self, value: Any, name: str, source_key: Optional[str] = None) -> Any:
        if isinstance(value, np.ndarray):
            self._counter += 1
            if source_key and self._reuse_array is not None:
                existing = self._reuse_array(source_key, name)
                if existing:
                    return {"$array": existing}
            # Include the AgentMemory version in the filename. A changed array
            # must never overwrite the sidecar still referenced by the current
            # snapshot before the new snapshot has been atomically committed.
            version_suffix = str(self._array_version(source_key)) if source_key and self._array_version else "value"
            relative = Path("arrays") / f"{name}_{version_suffix}_{self._counter}.npy"
            path = self.root / relative
            if self._ensure_capacity is not None:
                # ``.npy`` headers are small for the numeric volumes used by
                # BrachyBot; keep a conservative allowance before writing.
                self._ensure_capacity(path, int(value.nbytes) + 64 * 1024)
            _atomic_npy(path, value)
            encoded_relative = str(relative).replace("\\", "/")
            if source_key and self._record_array is not None:
                self._record_array(source_key, name, encoded_relative)
            return {"$array": encoded_relative}
        if isinstance(value, np.generic):
            return _safe_json(value)
        if isinstance(value, tuple):
            return {"$tuple": [self.encode(item, f"{name}_{index}", source_key) for index, item in enumerate(value)]}
        if isinstance(value, list):
            return [self.encode(item, f"{name}_{index}", source_key) for index, item in enumerate(value)]
        if isinstance(value, Mapping):
            return {str(key): self.encode(item, f"{name}_{key}", source_key) for key, item in value.items()}
        # SimpleITK images are rebuilt from the session CT.  Other opaque
        # objects are intentionally excluded rather than pickled.
        module = type(value).__module__ if value is not None else ""
        if module.startswith("SimpleITK"):
            return {"$image": "rebuild_from_ct"}
        return _safe_json(value)


def _decode_artifacts(value: Any, root: Path) -> Any:
    if isinstance(value, list):
        return [_decode_artifacts(item, root) for item in value]
    if not isinstance(value, dict):
        return value
    if "$array" in value:
        path = _safe_workspace_child(root, value["$array"])
        return np.load(path, allow_pickle=False)
    if "$tuple" in value:
        return tuple(_decode_artifacts(item, root) for item in value["$tuple"])
    if "$image" in value or "$unsupported" in value:
        return None
    return _restore_json({key: _decode_artifacts(item, root) for key, item in value.items()})


def _array_references(value: Any) -> set[str]:
    """Collect sidecar paths referenced by an encoded workspace payload."""
    if isinstance(value, list):
        return set().union(*(_array_references(item) for item in value)) if value else set()
    if not isinstance(value, Mapping):
        return set()
    if "$array" in value:
        return {str(value["$array"])}
    references: set[str] = set()
    for item in value.values():
        references.update(_array_references(item))
    return references


def _safe_workspace_child(root: Path, relative: str) -> Path:
    target = (root / str(relative)).resolve()
    if target != root.resolve() and root.resolve() not in target.parents:
        raise WorkspaceError("Workspace artifact path escapes its session root")
    return target


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_bytes(path, json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))


def _atomic_npy(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with open(temp, "wb") as handle:
            np.save(handle, array, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


class WorkspaceStore:
    """SQLite metadata plus filesystem artifacts for account-owned sessions."""

    def __init__(self, runtime_dir: Optional[os.PathLike[str] | str] = None):
        configured = runtime_dir or os.environ.get("BRACHYBOT_RUNTIME_DIR")
        if configured:
            self.runtime_dir = Path(configured).expanduser().resolve()
        else:
            self.runtime_dir = (Path(__file__).resolve().parents[1] / ".runtime").resolve()
        self.database_path = self.runtime_dir / "brachybot.sqlite3"
        self.workspaces_dir = self.runtime_dir / "workspaces"
        self.trash_dir = self.runtime_dir / "trash"
        self.staging_dir = self.runtime_dir / ".staging"
        self._lock = threading.RLock()
        self._checkpoint_timers: Dict[Tuple[str, str], threading.Timer] = {}
        self._case_locks: Dict[Tuple[str, str], threading.RLock] = {}
        # Array references are process-local acceleration metadata. The durable
        # snapshot remains authoritative; after restart the first checkpoint
        # safely writes fresh sidecars and prunes superseded files.
        self._array_refs: Dict[Tuple[str, str, str, str], Tuple[int, str]] = {}
        self._ensure_layout()
        self._initialize_database()
        self.purge_expired_trash()
        self.mark_running_sessions_interrupted()

    def _ensure_layout(self) -> None:
        for directory in (self.runtime_dir, self.workspaces_dir, self.trash_dir, self.staging_dir):
            directory.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(directory, 0o700)
            except OSError:
                pass

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _case_guard(self, user_id: str, session_id: str) -> Iterator[None]:
        """Serialize snapshot writers for one case without blocking others."""
        key = (user_id, session_id)
        with self._lock:
            guard = self._case_locks.setdefault(key, threading.RLock())
        with guard:
            yield

    def _initialize_database(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    storage_quota_bytes INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS case_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    deleted_at REAL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    recovery_status TEXT NOT NULL DEFAULT 'ready'
                );
                CREATE INDEX IF NOT EXISTS idx_case_sessions_user_status
                    ON case_sessions(user_id, status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS workspace_leases (
                    session_id TEXT PRIMARY KEY REFERENCES case_sessions(id) ON DELETE CASCADE,
                    owner_token TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    session_id TEXT,
                    action TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    session_id TEXT NOT NULL REFERENCES case_sessions(id) ON DELETE CASCADE,
                    author TEXT NOT NULL,
                    body TEXT NOT NULL,
                    anchor_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_comments_session
                    ON review_comments(user_id, session_id, created_at ASC);
                """
            )
        for path in (self.database_path, self.database_path.with_name(self.database_path.name + "-wal"), self.database_path.with_name(self.database_path.name + "-shm")):
            if path.exists():
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass

    def create_user(self, username: str, password_hash: str) -> Dict[str, Any]:
        normalized = str(username or "").strip()
        if not normalized:
            raise WorkspaceError("Username is required")
        user_id = uuid.uuid4().hex
        now = _now()
        try:
            with self._connection() as connection:
                connection.execute(
                    "INSERT INTO users(id, username, password_hash, storage_quota_bytes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, normalized, password_hash, DEFAULT_USER_QUOTA_BYTES, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise WorkspaceError("Username is already registered") from exc
        self._audit(user_id, None, "user.registered", {})
        return self.get_user_by_id(user_id)

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (str(username or "").strip(),)).fetchone()
        return dict(row) if row else None

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        with self._connection() as connection:
            result = connection.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ? AND is_active = 1",
                (password_hash, _now(), user_id),
            )
        if result.rowcount != 1:
            raise WorkspaceNotFound("Account is unavailable")
        self._audit(user_id, None, "user.password_changed", {})

    def create_session(self, user_id: str, title: str = "New case") -> WorkspaceSession:
        session_id = uuid.uuid4().hex
        now = _now()
        clean_title = str(title or "New case").strip()[:160] or "New case"
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO case_sessions(id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, user_id, clean_title, now, now),
            )
        try:
            root = self.workspace_root(user_id, session_id, create=True)
            self._write_snapshot(user_id, root / "snapshot.json", self._empty_snapshot(session_id))
        except Exception:
            # Do not leave a selectable database session without a durable
            # root if quota, permission, or filesystem initialization fails.
            root = self.workspace_root(user_id, session_id)
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)
            with self._connection() as connection:
                connection.execute("DELETE FROM case_sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
            raise
        self._audit(user_id, session_id, "session.created", {"title": clean_title})
        return self.get_session(user_id, session_id)

    def list_sessions(self, user_id: str, *, include_trashed: bool = False) -> List[WorkspaceSession]:
        where = "user_id = ?" if include_trashed else "user_id = ? AND status = 'active'"
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM case_sessions WHERE {where} ORDER BY updated_at DESC, created_at DESC",
                (user_id,),
            ).fetchall()
        return [WorkspaceSession.from_row(row) for row in rows]

    def get_session(self, user_id: str, session_id: str, *, include_trashed: bool = False) -> WorkspaceSession:
        condition = "" if include_trashed else "AND status = 'active'"
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT * FROM case_sessions WHERE id = ? AND user_id = ? {condition}",
                (session_id, user_id),
            ).fetchone()
        if not row:
            raise WorkspaceNotFound("Case session was not found")
        return WorkspaceSession.from_row(row)

    def rename_session(self, user_id: str, session_id: str, title: str) -> WorkspaceSession:
        clean_title = str(title or "").strip()[:160]
        if not clean_title:
            raise WorkspaceError("Session title is required")
        self.get_session(user_id, session_id)
        with self._connection() as connection:
            connection.execute(
                "UPDATE case_sessions SET title = ?, updated_at = ?, revision = revision + 1 WHERE id = ? AND user_id = ?",
                (clean_title, _now(), session_id, user_id),
            )
        self._audit(user_id, session_id, "session.renamed", {"title": clean_title})
        return self.get_session(user_id, session_id)

    def workspace_root(self, user_id: str, session_id: str, *, create: bool = False, trashed: bool = False) -> Path:
        base = self.trash_dir if trashed else self.workspaces_dir
        root = (base / user_id / session_id).resolve()
        if base.resolve() not in root.parents:
            raise WorkspaceError("Invalid workspace path")
        if create:
            root.mkdir(parents=True, exist_ok=True)
            for child in ("inputs", "artifacts", "arrays", "screenshots"):
                child_path = root / child
                child_path.mkdir(exist_ok=True)
                try:
                    os.chmod(child_path, 0o700)
                except OSError:
                    pass
            try:
                os.chmod(root, 0o700)
            except OSError:
                pass
        return root

    def _snapshot_path(self, user_id: str, session_id: str, *, trashed: bool = False) -> Path:
        return self.workspace_root(user_id, session_id, trashed=trashed) / "snapshot.json"

    @staticmethod
    def _empty_snapshot(session_id: str) -> Dict[str, Any]:
        return {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "session_id": session_id,
            "saved_at": _now(),
            "agent": {
                "config": {}, "planning_results": {}, "patient_data": {},
                "conversation": [], "tool_results": [], "context_summary": "",
                "compaction_count": 0, "current_phase": "idle",
                "conversation_state": {}, "user_lang": "en",
            },
            "ui": {},
            "report": {},
            "chat": {"messages": [], "execution_trace": []},
            "operation": {"state": "idle", "checkpoint": None},
        }

    def load_snapshot(self, user_id: str, session_id: str) -> Dict[str, Any]:
        record = self.get_session(user_id, session_id)
        path = self._snapshot_path(user_id, session_id)
        if not path.exists():
            snapshot = self._empty_snapshot(session_id)
        else:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    snapshot = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                raise WorkspaceError("Case workspace snapshot is unreadable") from exc
        if snapshot.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
            raise WorkspaceError("Case workspace schema is unsupported")
        snapshot["session"] = record.public_dict()
        snapshot["workspace"] = {
            "inputs_root": str(self.workspace_root(user_id, session_id) / "inputs"),
            "revision": record.revision,
        }
        return snapshot

    def save_snapshot_patch(
        self,
        user_id: str,
        session_id: str,
        patch: Mapping[str, Any],
        *,
        expected_revision: Optional[int] = None,
        reason: str = "workspace.updated",
    ) -> Dict[str, Any]:
        """Atomically merge a UI/report/chat patch for one case workspace."""
        with self._case_guard(user_id, session_id):
            return self._save_snapshot_patch_unlocked(
                user_id, session_id, patch,
                expected_revision=expected_revision, reason=reason,
            )

    def _save_snapshot_patch_unlocked(
        self,
        user_id: str,
        session_id: str,
        patch: Mapping[str, Any],
        *,
        expected_revision: Optional[int] = None,
        reason: str = "workspace.updated",
    ) -> Dict[str, Any]:
        """Merge a structured UI/report/chat patch and atomically advance revision."""
        record = self.get_session(user_id, session_id)
        if expected_revision is not None and int(expected_revision) != record.revision:
            raise WorkspaceLeaseConflict("This case was updated in another browser; reload it before editing")
        root = self.workspace_root(user_id, session_id, create=True)
        snapshot = self.load_snapshot(user_id, session_id)
        for key in ("ui", "report", "chat", "operation"):
            if key in patch and isinstance(patch[key], Mapping):
                current = snapshot.get(key) if isinstance(snapshot.get(key), Mapping) else {}
                snapshot[key] = {**current, **_safe_json(patch[key])}
        snapshot["saved_at"] = _now()
        self._write_snapshot(user_id, root / "snapshot.json", snapshot)
        with self._connection() as connection:
            connection.execute(
                "UPDATE case_sessions SET updated_at = ?, revision = revision + 1 WHERE id = ? AND user_id = ?",
                (_now(), session_id, user_id),
            )
        self._audit(user_id, session_id, reason, {"keys": sorted(patch.keys())})
        return self.load_snapshot(user_id, session_id)

    def snapshot_agent(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        *,
        reason: str = "agent.checkpoint",
        operation: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist one coherent agent checkpoint for an account-owned case."""
        payload = self._prepare_agent_snapshot(user_id, session_id, agent)
        with self._case_guard(user_id, session_id):
            return self._commit_agent_snapshot(
                user_id, session_id, payload, reason=reason, operation=operation,
            )

    def _prepare_agent_snapshot(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
    ) -> Dict[str, Any]:
        """Read agent memory and encode large arrays to disk WITHOUT
        acquiring the per-case _case_guard.  The heavy npy I/O must not
        block concurrent save_snapshot_patch calls from a chat turn."""
        self.get_session(user_id, session_id)
        memory = agent.memory
        with memory._lock:
            planning_results = dict(memory.planning_results)
            planning_versions = dict(getattr(memory, "_planning_versions", {}) or {})
            agent_config = dict(getattr(agent, "config", {}) or {})
            agent_config.pop("_workspace_state_dir", None)
            agent_state = {
                "config": _safe_json(agent_config),
                "patient_data": _safe_json(memory.patient_data),
                "conversation": _safe_json(memory.conversation),
                "tool_results": _safe_json(memory.tool_results),
                "context_summary": str(memory.context_summary or ""),
                "compaction_count": int(memory.compaction_count or 0),
                "current_phase": getattr(memory.current_phase, "value", str(memory.current_phase)),
                "conversation_state": _safe_json(memory.conversation_state),
                "user_lang": str(memory.user_lang or "en"),
                "ui_state": _safe_json(memory.get_ui_state()),
                "runtime_state": _safe_json(
                    agent.run_ledger.export_state()
                    if hasattr(agent, "run_ledger") else {}
                ),
            }
        root = self.workspace_root(user_id, session_id, create=True)
        created_array_paths: List[str] = []

        def reuse_array(source_key: str, name: str) -> Optional[str]:
            cache_key = (user_id, session_id, source_key, name)
            cached = self._array_refs.get(cache_key)
            version = int(planning_versions.get(source_key, 0))
            if not cached or cached[0] != version:
                return None
            relative = cached[1]
            try:
                if _safe_workspace_child(root, relative).is_file():
                    return relative
            except WorkspaceError:
                pass
            return None

        def record_array(source_key: str, name: str, relative: str) -> None:
            cache_key = (user_id, session_id, source_key, name)
            self._array_refs[cache_key] = (int(planning_versions.get(source_key, 0)), relative)
            created_array_paths.append(relative)

        encoder = _ArtifactEncoder(
            root,
            ensure_capacity=lambda path, size: self._ensure_replacement_capacity(user_id, path, size),
            reuse_array=reuse_array,
            record_array=record_array,
            array_version=lambda source_key: int(planning_versions.get(source_key, 0)),
        )
        encoded_results: Dict[str, Any] = {}
        for key, value in planning_results.items():
            if key in {"ct_image", "ct_sitk", "ct_image_raw"}:
                continue
            encoded = encoder.encode(value, _safe_filename(key), str(key))
            if isinstance(encoded, dict) and "$image" in encoded:
                continue
            encoded_results[str(key)] = encoded
        return {
            "agent_state": agent_state,
            "encoded_results": encoded_results,
            "created_array_paths": created_array_paths,
            "root": root,
        }

    def _commit_agent_snapshot(
        self,
        user_id: str,
        session_id: str,
        payload: Dict[str, Any],
        *,
        reason: str = "agent.checkpoint",
        operation: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Merge the prepared agent state into the durable JSON snapshot
        and update SQLite — must be called inside _case_guard."""
        agent_state = payload["agent_state"]
        encoded_results = payload["encoded_results"]
        created_array_paths = payload["created_array_paths"]
        root = payload["root"]
        try:
            snapshot = self.load_snapshot(user_id, session_id)
            snapshot["agent"] = {**agent_state, "planning_results": encoded_results}
            if operation is not None:
                snapshot["operation"] = _safe_json(operation)
            snapshot["saved_at"] = _now()
            self._write_snapshot(user_id, root / "snapshot.json", snapshot)
        except Exception:
            for relative in created_array_paths:
                try:
                    _safe_workspace_child(root, relative).unlink(missing_ok=True)
                except (OSError, WorkspaceError):
                    continue
            for cache_key, value in list(self._array_refs.items()):
                if cache_key[:2] == (user_id, session_id) and value[1] in created_array_paths:
                    self._array_refs.pop(cache_key, None)
            raise

        referenced_arrays = _array_references(encoded_results)
        arrays_dir = root / "arrays"
        for path in arrays_dir.glob("*.npy"):
            relative = path.relative_to(root).as_posix()
            if relative not in referenced_arrays:
                path.unlink(missing_ok=True)
        for cache_key, value in list(self._array_refs.items()):
            if cache_key[:2] == (user_id, session_id) and value[1] not in referenced_arrays:
                self._array_refs.pop(cache_key, None)
        recovery_status = str((snapshot.get("operation") or {}).get("state") or "ready")
        if recovery_status == "running":
            recovery_status = "running"
        elif recovery_status not in {"ready", "interrupted"}:
            recovery_status = "ready"
        with self._connection() as connection:
            connection.execute(
                "UPDATE case_sessions SET updated_at = ?, revision = revision + 1, recovery_status = ? WHERE id = ? AND user_id = ?",
                (_now(), recovery_status, session_id, user_id),
            )
        self._audit(user_id, session_id, reason, {"result_keys": sorted(encoded_results.keys())})
        return self.load_snapshot(user_id, session_id)

    def _snapshot_agent_unlocked(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        *,
        reason: str = "agent.checkpoint",
        operation: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist a safe agent checkpoint and retain the latest UI/chat state."""
        payload = self._prepare_agent_snapshot(user_id, session_id, agent)
        return self._commit_agent_snapshot(
            user_id, session_id, payload, reason=reason, operation=operation,
        )

    def hydrate_agent(self, user_id: str, session_id: str, agent: Any) -> Dict[str, Any]:
        """Load a checkpoint into a fresh agent without evaluating any code."""
        snapshot = self.load_snapshot(user_id, session_id)
        root = self.workspace_root(user_id, session_id)
        state = snapshot.get("agent") or {}
        memory = agent.memory
        with memory._lock:
            memory.planning_results.clear()
            for key, value in (state.get("planning_results") or {}).items():
                decoded = _decode_artifacts(value, root)
                if decoded is not None:
                    memory.planning_results[key] = decoded
            if hasattr(memory, "_planning_versions"):
                memory._planning_versions = {
                    str(key): 1 for key in memory.planning_results
                }
            memory.patient_data = _restore_json(state.get("patient_data") or {})
            memory.conversation = _restore_json(state.get("conversation") or [])
            memory.tool_results = _restore_json(state.get("tool_results") or [])
            memory.context_summary = str(state.get("context_summary") or "")
            memory.compaction_count = int(state.get("compaction_count") or 0)
            memory.conversation_state = _restore_json(state.get("conversation_state") or memory.conversation_state)
            memory.user_lang = str(state.get("user_lang") or "en")
            memory._ui_state = _restore_json(state.get("ui_state") or {})
            available = sorted(memory.planning_results.keys())
            memory.conversation_state["data_available"] = available
        if isinstance(state.get("config"), Mapping):
            agent.config.update(_restore_json(state["config"]))
        if hasattr(agent, "run_ledger") and isinstance(state.get("runtime_state"), Mapping):
            agent.run_ledger.restore_state(_restore_json(state["runtime_state"]))
        self._hydrate_ct_image(root, memory)
        operation = snapshot.get("operation") or {}
        if operation.get("state") == "running":
            snapshot = self.mark_session_interrupted(user_id, session_id, "Server restarted before the task completed")
        return snapshot

    @staticmethod
    def _hydrate_ct_image(root: Path, memory: Any) -> None:
        ct_path = memory.retrieve("ct_path")
        if not ct_path:
            return
        try:
            path = _safe_workspace_child(root, str(ct_path)) if not os.path.isabs(str(ct_path)) else Path(str(ct_path)).resolve()
            # A snapshot may never turn into an arbitrary server file read.
            # Persisted CT inputs are always located below this case workspace.
            path.relative_to(root.resolve())
            if not path.exists():
                return
            import SimpleITK as sitk
            image = sitk.ReadImage(str(path))
            memory.planning_results["ct_path"] = str(path)
            memory.planning_results["ct_image"] = image
            memory.planning_results["ct_sitk"] = image
        except Exception:
            # A damaged CT must not prevent the rest of the session metadata
            # from being inspected or deleted.
            return

    def schedule_agent_checkpoint(self, user_id: str, session_id: str, agent: Any, reason: str) -> None:
        """Debounce high-frequency memory changes without dropping durability."""
        key = (user_id, session_id)
        with self._lock:
            existing = self._checkpoint_timers.pop(key, None)
            if existing:
                existing.cancel()
            timer = threading.Timer(0.75, self._checkpoint_timer, args=(user_id, session_id, agent, reason))
            timer.daemon = True
            self._checkpoint_timers[key] = timer
            timer.start()

    def _checkpoint_timer(self, user_id: str, session_id: str, agent: Any, reason: str) -> None:
        key = (user_id, session_id)
        try:
            self.snapshot_agent(user_id, session_id, agent, reason=reason)
        except Exception:
            # Persistence errors are reported by the request boundary.  A
            # timer must never kill a clinical planning worker.
            pass
        finally:
            with self._lock:
                self._checkpoint_timers.pop(key, None)

    def flush_agent_checkpoint(self, user_id: str, session_id: str, agent: Any, reason: str) -> Dict[str, Any]:
        key = (user_id, session_id)
        with self._lock:
            timer = self._checkpoint_timers.pop(key, None)
            if timer:
                timer.cancel()
        return self.snapshot_agent(user_id, session_id, agent, reason=reason)

    def discard_agent_checkpoint(self, user_id: str, session_id: str) -> None:
        """Cancel a pending checkpoint when a case is explicitly deleted.

        Deletion moves/removes the workspace immediately. A timer left behind
        by a dropped in-memory agent could otherwise recreate the active
        workspace after the delete response has already been committed.
        """
        key = (user_id, session_id)
        with self._lock:
            timer = self._checkpoint_timers.pop(key, None)
            if timer:
                timer.cancel()

    def mark_operation(self, user_id: str, session_id: str, agent: Any, operation: Mapping[str, Any]) -> Dict[str, Any]:
        return self.snapshot_agent(user_id, session_id, agent, reason="operation.checkpoint", operation=operation)

    def mark_session_interrupted(self, user_id: str, session_id: str, detail: str) -> Dict[str, Any]:
        snapshot = self.load_snapshot(user_id, session_id)
        snapshot["operation"] = {
            **(snapshot.get("operation") or {}),
            "state": "interrupted",
            "interrupted_at": _now(),
            "message": detail,
        }
        snapshot["saved_at"] = _now()
        self._write_snapshot(user_id, self._snapshot_path(user_id, session_id), snapshot)
        with self._connection() as connection:
            connection.execute(
                "UPDATE case_sessions SET recovery_status = 'interrupted', updated_at = ?, revision = revision + 1 WHERE id = ? AND user_id = ?",
                (_now(), session_id, user_id),
            )
        self._audit(user_id, session_id, "operation.interrupted", {"detail": detail})
        return self.load_snapshot(user_id, session_id)

    def mark_running_sessions_interrupted(self) -> None:
        with self._connection() as connection:
            rows = connection.execute("SELECT id, user_id FROM case_sessions WHERE status = 'active' AND recovery_status = 'running'").fetchall()
        for row in rows:
            try:
                self.mark_session_interrupted(row["user_id"], row["id"], "Server restarted before the task completed")
            except WorkspaceError:
                continue

    def acquire_lease(
        self,
        user_id: str,
        session_id: str,
        owner_token: str,
        ttl_seconds: int = 75,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Acquire a case edit lease, optionally transferring it explicitly.

        ``force`` is only exposed through the authenticated takeover action.
        Normal heartbeat/acquire calls must continue rejecting a live owner so
        two browsers cannot silently overwrite a clinical workspace.
        """
        self.get_session(user_id, session_id)
        token = str(owner_token or "").strip()
        if len(token) < 16:
            raise WorkspaceError("Invalid editor token")
        now = _now()
        expiry = now + max(15, min(int(ttl_seconds), 300))
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM workspace_leases WHERE session_id = ?", (session_id,)).fetchone()
            replaced_owner = bool(row and float(row["expires_at"]) > now and row["owner_token"] != token)
            if replaced_owner and not force:
                connection.execute("ROLLBACK")
                raise WorkspaceLeaseConflict("This case is being edited in another browser")
            connection.execute(
                "INSERT INTO workspace_leases(session_id, owner_token, expires_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET owner_token = excluded.owner_token, expires_at = excluded.expires_at, updated_at = excluded.updated_at",
                (session_id, token, expiry, now),
            )
            connection.execute("COMMIT")
        if replaced_owner and force:
            # Never record editor tokens in the audit trail.
            self._audit(user_id, session_id, "workspace.lease_taken_over", {})
        return {"editable": True, "expires_at": expiry, "taken_over": replaced_owner and force}

    def release_lease(self, user_id: str, session_id: str, owner_token: str) -> None:
        self.get_session(user_id, session_id)
        with self._connection() as connection:
            connection.execute("DELETE FROM workspace_leases WHERE session_id = ? AND owner_token = ?", (session_id, owner_token))

    def assert_editable(self, user_id: str, session_id: str, owner_token: str) -> None:
        """Reject a write only when another live browser owns this case.

        Older API clients can still operate when no lease exists.  The modern
        browser always acquires a lease; once it does, a second browser cannot
        silently overwrite a live manual-planning edit.
        """
        self.get_session(user_id, session_id)
        now = _now()
        with self._connection() as connection:
            row = connection.execute("SELECT owner_token, expires_at FROM workspace_leases WHERE session_id = ?", (session_id,)).fetchone()
            if not row:
                return
            if float(row["expires_at"]) <= now:
                connection.execute("DELETE FROM workspace_leases WHERE session_id = ?", (session_id,))
                return
            if not owner_token or row["owner_token"] != owner_token:
                raise WorkspaceLeaseConflict("This case is being edited in another browser")

    def move_to_trash(self, user_id: str, session_id: str) -> WorkspaceSession:
        record = self.get_session(user_id, session_id)
        active = self.workspace_root(user_id, session_id)
        trash = self.workspace_root(user_id, session_id, trashed=True)
        trash.parent.mkdir(parents=True, exist_ok=True)
        if active.exists():
            if trash.exists():
                shutil.rmtree(trash)
            shutil.move(str(active), str(trash))
        now = _now()
        with self._connection() as connection:
            connection.execute(
                "UPDATE case_sessions SET status = 'trashed', deleted_at = ?, updated_at = ?, revision = revision + 1 WHERE id = ? AND user_id = ?",
                (now, now, session_id, user_id),
            )
            connection.execute("DELETE FROM workspace_leases WHERE session_id = ?", (session_id,))
        self._audit(user_id, session_id, "session.trashed", {"title": record.title})
        return self.get_session(user_id, session_id, include_trashed=True)

    def restore_from_trash(self, user_id: str, session_id: str) -> WorkspaceSession:
        record = self.get_session(user_id, session_id, include_trashed=True)
        if record.status != "trashed":
            raise WorkspaceError("Only trashed sessions can be restored")
        trashed = self.workspace_root(user_id, session_id, trashed=True)
        active = self.workspace_root(user_id, session_id)
        active.parent.mkdir(parents=True, exist_ok=True)
        if trashed.exists():
            if active.exists():
                raise WorkspaceError("Active workspace already exists")
            shutil.move(str(trashed), str(active))
        with self._connection() as connection:
            connection.execute(
                "UPDATE case_sessions SET status = 'active', deleted_at = NULL, updated_at = ?, revision = revision + 1 WHERE id = ? AND user_id = ?",
                (_now(), session_id, user_id),
            )
        self._audit(user_id, session_id, "session.restored", {})
        return self.get_session(user_id, session_id)

    def permanently_delete(self, user_id: str, session_id: str) -> None:
        record = self.get_session(user_id, session_id, include_trashed=True)
        for root in (self.workspace_root(user_id, session_id), self.workspace_root(user_id, session_id, trashed=True)):
            if root.exists():
                shutil.rmtree(root)
        with self._connection() as connection:
            connection.execute("DELETE FROM case_sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
        self._audit(user_id, session_id, "session.purged", {"previous_status": record.status})

    def purge_expired_trash(self) -> int:
        cutoff = _now() - TRASH_RETENTION_SECONDS
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, user_id FROM case_sessions WHERE status = 'trashed' AND deleted_at IS NOT NULL AND deleted_at < ?",
                (cutoff,),
            ).fetchall()
        for row in rows:
            self.permanently_delete(row["user_id"], row["id"])
        return len(rows)

    def user_storage_bytes(self, user_id: str) -> int:
        total = 0
        for base in (self.workspaces_dir / user_id, self.trash_dir / user_id):
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if path.is_file():
                    try:
                        total += path.stat().st_size
                    except OSError:
                        continue
        return total

    def ensure_capacity(self, user_id: str, additional_bytes: int) -> None:
        user = self.get_user_by_id(user_id)
        if not user:
            raise WorkspaceNotFound("Account is unavailable")
        if self.user_storage_bytes(user_id) + max(0, int(additional_bytes)) > int(user["storage_quota_bytes"]):
            raise WorkspaceQuotaExceeded("Account storage quota would be exceeded")

    def _ensure_replacement_capacity(self, user_id: str, path: Path, new_size: int) -> None:
        """Check only the net increase when atomically replacing an artifact."""
        try:
            previous_size = path.stat().st_size if path.exists() else 0
        except OSError:
            previous_size = 0
        self.ensure_capacity(user_id, max(0, int(new_size) - int(previous_size)))

    def _write_snapshot(self, user_id: str, path: Path, snapshot: Mapping[str, Any]) -> None:
        payload = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        self._ensure_replacement_capacity(user_id, path, len(payload))
        _atomic_bytes(path, payload)

    def write_upload(self, user_id: str, session_id: str, relative: str, stream: Any, expected_bytes: int = 0) -> Path:
        self.get_session(user_id, session_id)
        root = self.workspace_root(user_id, session_id, create=True)
        path = _safe_workspace_child(root / "inputs", relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        if expected_bytes:
            self._ensure_replacement_capacity(user_id, path, int(expected_bytes))
        temp = self.staging_dir / f"input-{secrets.token_hex(16)}.part"
        written = 0
        try:
            with open(temp, "wb") as handle:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    self._ensure_replacement_capacity(user_id, path, written)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            if temp.exists():
                temp.unlink(missing_ok=True)
        return path

    def write_screenshot(self, user_id: str, session_id: str, filename: str, png: bytes) -> Path:
        self.get_session(user_id, session_id)
        root = self.workspace_root(user_id, session_id, create=True)
        path = _safe_workspace_child(root / "screenshots", filename)
        self._ensure_replacement_capacity(user_id, path, len(png))
        _atomic_bytes(path, png)
        return path

    def write_artifact(self, user_id: str, session_id: str, category: str, filename: str, stream: Any, expected_bytes: int = 0) -> Path:
        """Write a generated case artifact under the owned workspace.

        This is deliberately separate from input uploads so report/export
        payloads cannot be mistaken for source images during hydration.
        """
        self.get_session(user_id, session_id)
        safe_category = _safe_filename(category)
        safe_name = _safe_filename(filename)
        root = self.workspace_root(user_id, session_id, create=True)
        path = _safe_workspace_child(root / "artifacts" / safe_category, safe_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if expected_bytes:
            self._ensure_replacement_capacity(user_id, path, int(expected_bytes))
        temp = self.staging_dir / f"artifact-{secrets.token_hex(16)}.part"
        written = 0
        try:
            with open(temp, "wb") as handle:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    self._ensure_replacement_capacity(user_id, path, written)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            if temp.exists():
                temp.unlink(missing_ok=True)
        return path

    def owns_path(self, user_id: str, session_id: str, path: str | Path, *, category: Optional[str] = None) -> bool:
        """Return whether a resolved artifact belongs to the selected case."""
        try:
            root = self.workspace_root(user_id, session_id)
            candidate = Path(path).resolve()
            base = (root / category).resolve() if category else root.resolve()
            candidate.relative_to(base)
            return True
        except (OSError, ValueError):
            return False

    def session_artifact_path(self, user_id: str, session_id: str, category: str, filename: str) -> Path:
        self.get_session(user_id, session_id)
        root = self.workspace_root(user_id, session_id, create=True)
        return _safe_workspace_child(root / category, filename)

    def _audit(self, user_id: Optional[str], session_id: Optional[str], action: str, detail: Mapping[str, Any]) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO audit_events(user_id, session_id, action, detail_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, session_id, action, json.dumps(_safe_json(detail), ensure_ascii=False), _now()),
            )

    def list_audit_events(self, user_id: str, session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        """Return case-scoped audit events without exposing another case's log."""
        self.get_session(user_id, session_id)
        bounded = max(1, min(int(limit or 200), 1000))
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, action, detail_json, created_at FROM audit_events "
                "WHERE user_id = ? AND session_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, session_id, bounded),
            ).fetchall()
        events = []
        for row in reversed(rows):
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except (TypeError, ValueError):
                detail = {}
            events.append({
                "id": int(row["id"]),
                "action": str(row["action"]),
                "detail": detail if isinstance(detail, dict) else {},
                "created_at": float(row["created_at"]),
            })
        return events

    def list_review_comments(self, user_id: str, session_id: str) -> List[Dict[str, Any]]:
        """List review comments for the authenticated owner's case."""
        self.get_session(user_id, session_id)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, author, body, anchor_json, status, created_at, updated_at "
                "FROM review_comments WHERE user_id = ? AND session_id = ? ORDER BY id ASC",
                (user_id, session_id),
            ).fetchall()
        result = []
        for row in rows:
            try:
                anchor = json.loads(row["anchor_json"] or "{}")
            except (TypeError, ValueError):
                anchor = {}
            result.append({
                "id": int(row["id"]),
                "author": str(row["author"]),
                "body": str(row["body"]),
                "anchor": anchor if isinstance(anchor, dict) else {},
                "status": str(row["status"]),
                "created_at": float(row["created_at"]),
                "updated_at": float(row["updated_at"]),
            })
        return result

    def add_review_comment(
        self,
        user_id: str,
        session_id: str,
        author: str,
        body: str,
        anchor: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add an auditable, case-scoped comment for review hand-off."""
        self.get_session(user_id, session_id)
        clean_body = str(body or "").strip()
        if not clean_body or len(clean_body) > 4000:
            raise WorkspaceError("Comment must contain 1-4000 characters")
        clean_author = str(author or "").strip()[:160] or "BrachyBot user"
        safe_anchor = _safe_json(anchor or {})
        if not isinstance(safe_anchor, dict):
            safe_anchor = {}
        now = _now()
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO review_comments(user_id, session_id, author, body, anchor_json, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'open', ?, ?)",
                (user_id, session_id, clean_author, clean_body, json.dumps(safe_anchor, ensure_ascii=False), now, now),
            )
            comment_id = int(cursor.lastrowid)
        self._audit(user_id, session_id, "review.comment_added", {"comment_id": comment_id})
        return next(item for item in self.list_review_comments(user_id, session_id) if item["id"] == comment_id)

    def update_review_comment(self, user_id: str, session_id: str, comment_id: int, *, body: Optional[str] = None, status: Optional[str] = None) -> Dict[str, Any]:
        """Update only owner-visible comment fields and record the transition."""
        self.get_session(user_id, session_id)
        clean_status = str(status or "").strip().lower() if status is not None else None
        if clean_status is not None and clean_status not in {"open", "resolved"}:
            raise WorkspaceError("Comment status must be open or resolved")
        clean_body = str(body or "").strip() if body is not None else None
        if clean_body is not None and not (1 <= len(clean_body) <= 4000):
            raise WorkspaceError("Comment must contain 1-4000 characters")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id FROM review_comments WHERE id = ? AND user_id = ? AND session_id = ?",
                (int(comment_id), user_id, session_id),
            ).fetchone()
            if not row:
                raise WorkspaceNotFound("Review comment was not found")
            fields, values = [], []
            if clean_body is not None:
                fields.append("body = ?"); values.append(clean_body)
            if clean_status is not None:
                fields.append("status = ?"); values.append(clean_status)
            if fields:
                fields.append("updated_at = ?"); values.append(_now())
                values.extend([int(comment_id), user_id, session_id])
                connection.execute(
                    f"UPDATE review_comments SET {', '.join(fields)} WHERE id = ? AND user_id = ? AND session_id = ?",
                    values,
                )
        self._audit(user_id, session_id, "review.comment_updated", {"comment_id": int(comment_id), "status": clean_status})
        return next(item for item in self.list_review_comments(user_id, session_id) if item["id"] == int(comment_id))


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value))[:96] or "value"
