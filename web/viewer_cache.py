"""Case-scoped persistent caches for derived Viewer geometry.

The clinical arrays and planning snapshots remain the source of truth.  This
module only stores deterministic, derived meshes so a server restart does not
force every OAR and dose surface to be rebuilt from scratch.  Cache files are
written atomically and are ignored when missing or corrupt; a cache failure
must therefore degrade to reconstruction, never to a lost clinical result.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


logger = logging.getLogger(__name__)

_CACHE_SCHEMA = 1
_CACHE_ROOT = "viewer-cache"
_NAMESPACE_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


_CACHE_MAX_FILES = _positive_int_env("BRACHYBOT_VIEWER_CACHE_MAX_FILES", 128)
_CACHE_MAX_BYTES = _positive_int_env(
    "BRACHYBOT_VIEWER_CACHE_MAX_BYTES", 1024 * 1024 * 1024
)
_CACHE_LOCK = threading.RLock()
_WRITE_EXECUTOR = ThreadPoolExecutor(
    max_workers=_positive_int_env("BRACHYBOT_VIEWER_CACHE_WRITE_WORKERS", 2),
    thread_name_prefix="viewer-cache",
)
_PENDING_WRITES: Dict[tuple[str, str, str], Future] = {}


def viewer_cache_key(namespace: str, components: Mapping[str, Any]) -> str:
    """Return a stable content-addressed key for one derived resource."""

    canonical = json.dumps(
        {
            "schema": _CACHE_SCHEMA,
            "namespace": str(namespace),
            "components": components,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.blake2b(canonical, digest_size=20).hexdigest()


def _safe_namespace(namespace: str) -> str:
    clean = _NAMESPACE_RE.sub("_", str(namespace or "").strip())
    clean = clean.strip("._")
    return clean[:80] or "default"


def _cache_directory(root: Path, namespace: str, *, create: bool) -> Path:
    case_root = Path(root).resolve()
    directory = (case_root / "artifacts" / _CACHE_ROOT / f"v{_CACHE_SCHEMA}" / _safe_namespace(namespace)).resolve()
    # The root is supplied only after request authentication. Keep the path
    # boundary explicit so a malformed namespace can never escape the case.
    directory.relative_to(case_root)
    if create:
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
    return directory


def _cache_path(root: Path, namespace: str, key: str, *, create: bool) -> Path:
    if not re.fullmatch(r"[0-9a-f]{40}", str(key or "")):
        raise ValueError("Invalid Viewer cache key")
    directory = _cache_directory(root, namespace, create=create)
    path = (directory / f"{key}.json.gz").resolve()
    path.relative_to(directory.resolve())
    return path


def load_viewer_cache(root: Optional[Path], namespace: str, key: str) -> Optional[Dict[str, Any]]:
    """Load a validated derived payload, or ``None`` on a cache miss."""

    if root is None:
        return None
    try:
        path = _cache_path(Path(root), namespace, key, create=False)
        if not path.is_file():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            envelope = json.load(handle)
        if not isinstance(envelope, dict):
            return None
        if envelope.get("schema") != _CACHE_SCHEMA or envelope.get("cache_key") != key:
            return None
        payload = envelope.get("payload")
        return dict(payload) if isinstance(payload, dict) else None
    except (OSError, EOFError, ValueError, TypeError, json.JSONDecodeError) as exc:
        # A partial file can only be a derived-cache failure. Do not let it
        # block the authoritative workspace or turn a cache miss into a 500.
        logger.warning("Viewer cache read ignored namespace=%s key=%s: %s", namespace, key, exc)
        return None


def _prune_locked(directory: Path) -> None:
    try:
        files = [path for path in directory.glob("*.json.gz") if path.is_file()]
    except OSError:
        return
    entries = []
    for path in files:
        try:
            stat = path.stat()
            entries.append((int(stat.st_mtime_ns), int(stat.st_size), path))
        except OSError:
            continue
    entries.sort(key=lambda item: item[0], reverse=True)
    total = 0
    for index, (_, size, path) in enumerate(entries):
        keep = index < _CACHE_MAX_FILES and total + size <= _CACHE_MAX_BYTES
        if keep:
            total += size
            continue
        try:
            path.unlink()
        except OSError:
            pass


def save_viewer_cache(root: Path, namespace: str, key: str, payload: Mapping[str, Any]) -> Optional[Path]:
    """Atomically write a derived payload and prune only derived cache files."""

    try:
        path = _cache_path(Path(root), namespace, key, create=True)
        encoded = json.dumps(
            {
                "schema": _CACHE_SCHEMA,
                "cache_key": key,
                "payload": dict(payload),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("Viewer cache write skipped namespace=%s key=%s: %s", namespace, key, exc)
        return None

    temporary: Optional[Path] = None
    with _CACHE_LOCK:
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{key}.",
                suffix=".tmp",
                dir=str(path.parent),
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                with gzip.GzipFile(fileobj=handle, mode="wb", compresslevel=1, mtime=0) as compressed:
                    compressed.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, path)
            temporary = None
            _prune_locked(path.parent)
            return path
        except OSError as exc:
            logger.warning("Viewer cache atomic write failed namespace=%s key=%s: %s", namespace, key, exc)
            return None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


def schedule_viewer_cache_write(
    root: Optional[Path], namespace: str, key: str, payload: Mapping[str, Any]
) -> None:
    """Persist a cache entry without delaying the HTTP mesh response.

    The payload is already present in the request's memory and is purely
    derived. If the process exits before this background write runs, the next
    request safely recomputes it from the durable case arrays.
    """

    if root is None:
        return
    identity = (str(Path(root).resolve()), str(namespace), str(key))
    with _CACHE_LOCK:
        if identity in _PENDING_WRITES:
            return
        future = _WRITE_EXECUTOR.submit(save_viewer_cache, Path(root), namespace, key, dict(payload))
        _PENDING_WRITES[identity] = future

        def _finished(done: Future) -> None:
            with _CACHE_LOCK:
                if _PENDING_WRITES.get(identity) is done:
                    _PENDING_WRITES.pop(identity, None)
            try:
                done.result()
            except Exception as exc:  # pragma: no cover - defensive executor boundary
                logger.warning("Viewer cache background write failed namespace=%s key=%s: %s", namespace, key, exc)

        future.add_done_callback(_finished)
