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

import copy
import json
import hashlib
import logging
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
# Candidate trajectories are an in-process planning workspace, not durable
# clinical results. Persisting thousands of nested NumPy objects on every
# memory.store checkpoint made a chat turn spend minutes encoding data that can
# be regenerated from the final seed plan and needle geometry. Small fixtures
# and manual plans remain persisted for compatibility.
TRANSIENT_PLANNING_RESULT_KEYS = frozenset({
    "refined_trajectories",
    "radiation_volume",
    "resampled_ct",
    "resampled_ctv",
    "resampled_oar",
})
TRANSIENT_COLLECTION_LIMIT = int(
    os.environ.get("BRACHYBOT_TRANSIENT_COLLECTION_LIMIT", "256")
)
# Small planning arrays (seed coordinates, face indices, and similar records)
# are cheaper to read eagerly than to keep as one mmap per sidecar. Historical
# Planning snapshots can contain thousands of these tiny files; mapping each
# one exhausts the default 1024-descriptor process limit before hydration can
# publish any data. Large medical volumes remain memory-mapped.
EAGER_ARRAY_LOAD_MAX_BYTES = int(
    os.environ.get("BRACHYBOT_EAGER_ARRAY_LOAD_MAX_BYTES", str(1024 ** 2))
)
MIN_OPEN_FILE_LIMIT = int(
    os.environ.get("BRACHYBOT_MIN_OPEN_FILE_LIMIT", "65536")
)

logger = logging.getLogger(__name__)


def _configure_open_file_limit() -> None:
    """Give the bounded mmap cache enough descriptors on POSIX hosts.

    Eager loading removes the thousands of tiny sidecar descriptors. The
    remaining large CT, dose, mesh, and mask mappings are intentionally kept
    lazy, so a server caching several active Sessions still needs more than a
    shell's usual 1024-descriptor soft limit. The hard limit remains untouched.
    """
    try:
        import resource
    except ImportError:  # Windows does not expose POSIX resource limits.
        return
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(int(hard), max(int(soft), MIN_OPEN_FILE_LIMIT))
        if target > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            logger.info(
                "Raised process open-file soft limit from %d to %d for workspace hydration",
                soft,
                target,
            )
    except (OSError, ValueError):
        logger.warning(
            "Could not raise the process open-file limit; large Session hydration may be constrained",
            exc_info=True,
        )


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
            # Nested Planning snapshots can produce path-like names hundreds
            # of characters long. Use a stable digest for the physical file;
            # the complete logical name remains in the snapshot/reuse index.
            # This keeps snapshots portable to Windows without weakening the
            # source-key/version identity used for sidecar reuse.
            logical_digest = hashlib.sha256(name.encode("utf-8", "replace")).hexdigest()[:16]
            source_prefix = _safe_filename(source_key or "array")[:16]
            relative = Path("arrays") / (
                f"{source_prefix}_{logical_digest}_{version_suffix}_{self._counter}.npy"
            )
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
        # A memmap keeps one descriptor alive for the array lifetime. Tiny
        # planning arrays therefore load eagerly, while large medical volumes
        # retain lazy, read-only mmap behavior to bound resident memory.
        mmap_mode = "r" if path.stat().st_size > EAGER_ARRAY_LOAD_MAX_BYTES else None
        return np.load(path, allow_pickle=False, mmap_mode=mmap_mode)
    if "$tuple" in value:
        return tuple(_decode_artifacts(item, root) for item in value["$tuple"])
    if "$image" in value or "$unsupported" in value:
        return None
    return _restore_json({key: _decode_artifacts(item, root) for key, item in value.items()})


def _restore_hydration_metadata(value: Any) -> Any:
    """Restore only JSON/scalar checkpoint metadata during a fast cold start.

    Array and image references deliberately become ``None`` until the
    background hydration pass has decoded the case artifacts. This prevents a
    lightweight agent from exposing a fake, partially decoded clinical result.
    """
    if isinstance(value, list):
        return [_restore_hydration_metadata(item) for item in value]
    if not isinstance(value, dict):
        return _restore_json(value)
    if "$array" in value or "$image" in value:
        return None
    if "$tuple" in value:
        return tuple(_restore_hydration_metadata(item) for item in value["$tuple"])
    if "$unsupported" in value:
        return None
    return {
        str(key): _restore_hydration_metadata(item)
        for key, item in value.items()
    }


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


def _chat_record_key(record: Any) -> str:
    """Return a stable identity for one durable chat record.

    Chat writes can arrive from the live browser and the detached task
    finalizer in either order. New records carry a stable message/step ID and
    must merge under that identity as text, Trace steps, and screenshot
    attachments arrive. Legacy records without an ID use a complete-content
    hash so two legitimate repeated questions remain distinct.
    """
    if isinstance(record, Mapping):
        stable_id = str(record.get("id") or "").strip()
        if stable_id:
            return f"id:{stable_id}"
    try:
        payload = json.dumps(_safe_json(record), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        payload = str(record)
    return "hash:" + hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()


def _merge_record_list(existing: Any, incoming: Any) -> List[Any]:
    """Merge ID-addressed nested records such as Trace steps or attachments."""
    merged: List[Any] = []
    positions: Dict[str, int] = {}
    for record in list(existing or []) + list(incoming or []):
        key = _chat_record_key(record)
        if key not in positions:
            positions[key] = len(merged)
            merged.append(copy.deepcopy(record))
            continue
        position = positions[key]
        current = merged[position]
        if isinstance(current, Mapping) and isinstance(record, Mapping):
            merged[position] = _merge_chat_record(current, record)
    return merged


def _merge_chat_record(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge later fields into one stable chat/Trace/attachment record."""
    result = copy.deepcopy(dict(existing or {}))
    incoming_safe = _safe_json(incoming)

    for key, value in incoming_safe.items():
        if key in {"steps", "attachments"} and isinstance(value, list):
            result[key] = _merge_record_list(result.get(key), value)
            continue
        if key == "meta" and isinstance(value, Mapping):
            current_meta = result.get("meta") if isinstance(result.get("meta"), Mapping) else {}
            result["meta"] = {**copy.deepcopy(dict(current_meta)), **copy.deepcopy(dict(value))}
            continue
        if key == "timestamp":
            candidates = []
            for candidate in (result.get("timestamp"), value):
                try:
                    parsed = float(candidate)
                except (TypeError, ValueError):
                    continue
                if parsed > 0:
                    candidates.append(parsed)
            if candidates:
                earliest = min(candidates)
                result[key] = int(earliest) if earliest.is_integer() else earliest
            continue
        # Screenshot capture first creates an empty assistant shell; the
        # detached finalizer later supplies final text. Never let an empty
        # stale patch erase already durable content or metadata.
        if value not in (None, "", [], {}):
            result[key] = copy.deepcopy(value)
        elif key not in result:
            result[key] = copy.deepcopy(value)
    return result


def _merge_chat_records(existing: Any, incoming: Any) -> List[Any]:
    """Merge durable chat records while preserving stable display order.

    A browser turn writes its final answer and its execution trace from two
    different completion callbacks. The trace can therefore arrive after the
    answer even though it belongs between the user request and that answer.
    Sort by request group and message role, rather than raw write timestamp,
    so a refresh renders every Trace beside the correct response.
    """
    merged: List[Any] = []
    positions: Dict[str, int] = {}
    for record in list(existing or []) + list(incoming or []):
        key = _chat_record_key(record)
        if key not in positions:
            positions[key] = len(merged)
            merged.append(copy.deepcopy(record))
            continue
        position = positions[key]
        current = merged[position]
        if isinstance(current, Mapping) and isinstance(record, Mapping):
            merged[position] = _merge_chat_record(current, record)

    def role_rank(item: Any) -> int:
        if not isinstance(item, Mapping):
            return 3
        try:
            explicit_sequence = float(item.get("turn_sequence", item.get("turnSequence")))
        except (TypeError, ValueError):
            explicit_sequence = float("nan")
        if math.isfinite(explicit_sequence):
            return int(explicit_sequence)
        kind = str(item.get("message_kind") or item.get("messageKind") or "").lower()
        record_type = str(item.get("type") or "").lower()
        if record_type == "user" or kind == "user_message":
            return 0
        if record_type == "thinking" or kind == "execution_trace":
            return 1
        if record_type in {"bot", "bot-response"} or kind == "assistant_final":
            return 2
        return 3

    groups: Dict[str, Dict[str, Any]] = {}
    for index, item in enumerate(merged):
        if not isinstance(item, Mapping):
            request_id = f"orphan-{index}"
        else:
            request_id = str(item.get("request_id") or item.get("requestId") or item.get("id") or f"orphan-{index}")
        group = groups.setdefault(
            request_id,
            {"first_index": index, "first_timestamp": float("inf"), "records": []},
        )
        try:
            timestamp = float(item.get("timestamp", item.get("created_at", 0)) or 0) if isinstance(item, Mapping) else 0
        except (TypeError, ValueError):
            timestamp = 0
        if timestamp > 0:
            group["first_timestamp"] = min(group["first_timestamp"], timestamp)
        group["records"].append((index, item))

    def group_sort_key(group: Dict[str, Any]) -> Tuple[float, int]:
        timestamp = group["first_timestamp"]
        return (timestamp if math.isfinite(timestamp) else float("inf"), group["first_index"])

    ordered: List[Any] = []
    for group in sorted(groups.values(), key=group_sort_key):
        records = sorted(
            group["records"],
            key=lambda pair: (role_rank(pair[1]), pair[0]),
        )
        ordered.extend(item for _, item in records)
    return ordered


def _merge_chat_patch(current: Mapping[str, Any], incoming: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge chat content without allowing a stale client to erase history."""
    result = dict(current or {})
    for key in ("messages", "execution_trace"):
        if key in incoming and isinstance(incoming[key], list):
            result[key] = _merge_chat_records(result.get(key), incoming[key])
    if "attachments" in incoming and isinstance(incoming["attachments"], list):
        # Attachments are a flat Session-owned registry, not chat turns. Do
        # not group or rank them like messages: the stable attachment ID is
        # the only identity that should decide whether two captures are the
        # same file.
        result["attachments"] = _merge_record_list(
            result.get("attachments"), incoming["attachments"]
        )
    # Task control fields are state, not append-only content.  The latest
    # finalizer/browser update is authoritative for these small fields.
    for key, value in incoming.items():
        if key not in {"messages", "execution_trace", "attachments"}:
            result[key] = _safe_json(value)
    return result


def _reconcile_chat_attachment_registry(chat: Any) -> Dict[str, Any]:
    """Attach durable image records to their owning chat message on read.

    Screenshot capture and chat finalization are independent asynchronous
    writers.  A capture can therefore be indexed in ``chat.attachments``
    before the assistant shell exists, or a later browser checkpoint can
    contain the message without its attachment metadata.  The registry is a
    small durable index, while the message's ``attachments`` list remains the
    canonical render contract.  Reconcile both here so refresh and Session
    switching are deterministic even when the writes arrived out of order.
    """
    if not isinstance(chat, Mapping):
        return {}
    result = copy.deepcopy(dict(chat))
    messages = result.get("messages")
    registry = result.get("attachments")
    if not isinstance(messages, list) or not isinstance(registry, list):
        return result

    def matches(message: Mapping[str, Any], attachment: Mapping[str, Any]) -> bool:
        message_id = str(attachment.get("message_id") or attachment.get("messageId") or "").strip()
        request_id = str(attachment.get("request_id") or attachment.get("requestId") or "").strip()
        if message_id:
            # A capture with an explicit message ID is authoritative. Never
            # fall through to request-level matching when it belongs to a
            # different row; that would copy a user image onto the assistant
            # reply when both rows share one request ID.
            return str(message.get("id") or "") == message_id
        return bool(request_id) and str(message.get("request_id") or message.get("requestId") or "") == request_id \
            and str(message.get("type") or "") in {"bot", "bot-response"}

    for message in messages:
        if not isinstance(message, Mapping):
            continue
        if str(message.get("type") or "") not in {"bot", "bot-response", "user"}:
            continue
        related = [item for item in registry if isinstance(item, Mapping) and matches(message, item)]
        if not related:
            continue
        current = message.get("attachments") if isinstance(message.get("attachments"), list) else []
        message["attachments"] = _merge_record_list(current, related)
    return result


def _report_narrative_length(form: Any) -> int:
    if not isinstance(form, Mapping):
        return 0
    return sum(
        len(str(form.get(key) or '').strip())
        for key in ('interpretation', 'safety', 'qaNotes')
    )


def _report_content_score(form: Any) -> int:
    if not isinstance(form, Mapping):
        return 0
    score = _report_narrative_length(form)
    for parent, key in (
        ('case', 'patientId'), ('case', 'tumorType'), ('case', 'plannerName'),
        ('study', 'diagnosis'), ('study', 'clinicalHistory'), ('study', 'priorTreatment'),
        ('segmentation', 'ctvModelName'), ('segmentation', 'oarModelName'),
    ):
        value = (form.get(parent) or {}).get(key) if isinstance(form.get(parent), Mapping) else None
        if isinstance(value, str):
            score += len(value.strip())
    for key in ('references', 'figures', 'oarDose'):
        if isinstance(form.get(key), list):
            score += len(form[key]) * 32
    for group, weight in (('metrics', 8), ('planning', 4)):
        values = form.get(group) if isinstance(form.get(group), Mapping) else {}
        score += sum(weight for value in values.values() if value not in (None, ''))
    quality = form.get('qualityAssessment')
    if isinstance(quality, Mapping):
        metrics = quality.get('metrics')
        if isinstance(metrics, Mapping):
            score += len(metrics) * 4
    return score


_REPORT_QUALITY_KEYS = ('v100', 'd90', 'd95', 'v150', 'v200', 'ci', 'hi', 'gi', 'score')


def _quality_row_has_display(row: Any) -> bool:
    if not isinstance(row, Mapping):
        return False
    return bool(str(row.get('reference') or '').strip()
                or str(row.get('statusText') or '').strip())


def _quality_row_specificity(row: Any) -> int:
    """Rank source-backed report rows above hydration placeholders.

    A delayed browser snapshot can legitimately contain ``Not assessed`` and
    ``See cited case criteria`` while prescription sources are still loading.
    Those strings are displayable, but they must never replace a previously
    persisted numeric criterion and its pass/review decision.
    """
    if not isinstance(row, Mapping):
        return -1
    reference = str(row.get('reference') or '').strip()
    status = str(row.get('statusText') or '').strip()
    generic_references = {
        '', '—', '-', 'See cited case criteria', '见病例引用标准',
        'Not defined by current source', '当前来源未定义',
    }
    generic_statuses = {'', 'Not assessed', '未评估'}
    score = 0
    if reference not in generic_references:
        score += 4
    elif reference:
        score += 1
    if status not in generic_statuses:
        score += 4
    elif status:
        score += 1
    if str(row.get('statusClass') or '').strip():
        score += 2
    return score


def _quality_assessment_specificity(quality: Any) -> int:
    """Return the combined information rank for one assessment snapshot."""
    if not isinstance(quality, Mapping) or not isinstance(quality.get('metrics'), Mapping):
        return -1
    return sum(_quality_row_specificity(row) for row in quality['metrics'].values())


def _quality_row_matches_value(row: Any, metrics: Mapping[str, Any]) -> bool:
    if not isinstance(row, Mapping):
        return False
    key = row.get('_metric_key')
    if key not in metrics:
        return True
    target = metrics.get(key)
    actual = row.get('value')
    if target in (None, ''):
        return actual in (None, '')
    try:
        return math.isclose(float(actual), float(target), rel_tol=0.0, abs_tol=1e-9)
    except (TypeError, ValueError):
        return False


def _merge_report_quality_assessment(
    old_form: Mapping[str, Any],
    new_form: Mapping[str, Any],
    base_form: Mapping[str, Any],
) -> Dict[str, Any]:
    """Keep durable Reference/Status rows when a delayed form is incomplete.

    Browser report saves are full-form snapshots, but hydration and report
    auto-fill can arrive in different orders.  A newer snapshot may therefore
    contain the numeric metrics while its derived quality rows are still
    empty.  Merge row-by-row only when the saved row belongs to the metrics in
    the form being retained; never resurrect a row for a different planning
    result.
    """
    result = dict(base_form or {})
    base_quality = result.get('qualityAssessment')
    old_quality = old_form.get('qualityAssessment') if isinstance(old_form, Mapping) else None
    new_quality = new_form.get('qualityAssessment') if isinstance(new_form, Mapping) else None
    candidates = [quality for quality in (base_quality, new_quality, old_quality)
                  if isinstance(quality, Mapping)]
    if not candidates:
        return result

    metrics = result.get('metrics') if isinstance(result.get('metrics'), Mapping) else {}
    quality = dict(base_quality) if isinstance(base_quality, Mapping) else {}
    rows = dict(quality.get('metrics')) if isinstance(quality.get('metrics'), Mapping) else {}
    for key in _REPORT_QUALITY_KEYS:
        selected = dict(rows.get(key)) if isinstance(rows.get(key), Mapping) else {}
        selected['_metric_key'] = key
        if not _quality_row_matches_value(selected, metrics):
            selected = {}
        selected_specificity = _quality_row_specificity(selected)
        for candidate in candidates:
            candidate_row = candidate.get('metrics', {}).get(key) if isinstance(candidate.get('metrics'), Mapping) else None
            if not _quality_row_has_display(candidate_row):
                continue
            candidate_with_key = dict(candidate_row)
            candidate_with_key['_metric_key'] = key
            if not _quality_row_matches_value(candidate_with_key, metrics):
                continue
            candidate_specificity = _quality_row_specificity(candidate_row)
            if candidate_specificity > selected_specificity:
                # Prefer the most informative row, even when it is older. This
                # prevents a partial-hydration placeholder from erasing a saved
                # source-backed criterion for the same metric value.
                selected = dict(candidate_row)
                selected_specificity = candidate_specificity
                continue
            # Equal or less-specific candidates may only fill absent fields.
            for field in ('reference', 'statusText', 'statusClass'):
                current = selected.get(field)
                if current in (None, '') and candidate_row.get(field) not in (None, ''):
                    selected[field] = candidate_row.get(field)
            if selected.get('value') in (None, '') and 'value' in candidate_row:
                selected['value'] = candidate_row.get('value')
            # Continue through every matching snapshot. The first candidate is
            # often the newer generic base row; stopping there prevents an
            # older, source-backed row from ever being considered.
        selected.pop('_metric_key', None)
        if selected:
            rows[key] = selected
        else:
            rows.pop(key, None)

    if not rows:
        return result
    quality['metrics'] = rows
    # Keep metadata, especially inputFingerprint, from the assessment whose
    # rows supplied the most information. Without that provenance the browser
    # would immediately treat restored specific rows as stale and replace them
    # with hydration placeholders during its next synchronization pass.
    base_rows = base_quality.get('metrics') if isinstance(base_quality, Mapping) else None
    base_has_display = (
        isinstance(base_rows, Mapping)
        and any(_quality_row_has_display(row) for row in base_rows.values())
    )
    best_candidate = max(candidates, key=_quality_assessment_specificity)
    best_specificity = _quality_assessment_specificity(best_candidate)
    base_specificity = _quality_assessment_specificity(base_quality)
    if not base_has_display or best_specificity > base_specificity:
        quality = {**quality, **dict(best_candidate)}
        quality['metrics'] = rows
    result['qualityAssessment'] = quality
    return result


def _report_timestamp(form: Any) -> float:
    if not isinstance(form, Mapping):
        return 0.0
    try:
        value = float(form.get('updatedAt') or form.get('updated_at') or 0)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


_REPORT_FORM_KEYS = frozenset({
    "version", "language", "templateKey", "sessionId", "updatedAt", "updated_at",
    "hospital", "patient", "study", "case", "imaging", "segmentation",
    "planning", "metrics", "qualityAssessment", "oarDose", "interpretation", "safety", "qaNotes",
    "references", "figures", "signature", "editedFields",
})


def _report_form_from_section(section: Any) -> Tuple[Dict[str, Any], bool]:
    """Return a report form from either the current or legacy snapshot shape."""
    if not isinstance(section, Mapping):
        return {}, False
    nested = section.get("form")
    if isinstance(nested, Mapping):
        return dict(nested), True
    direct = {key: value for key, value in section.items() if key in _REPORT_FORM_KEYS}
    return direct, bool(direct)


def _merge_report_patch(current: Mapping[str, Any], incoming: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge report metadata without allowing an older blank form to erase text.

    Browser report saves are full-form snapshots.  A delayed shell restore can
    therefore contain an empty/default form even though a newer planning
    refresh has already generated narrative text.  ``updatedAt`` is emitted by
    the browser on every durable report save; the content comparison keeps
    older snapshots created before that field was introduced compatible.
    """
    current_section = dict(current or {})
    incoming_section = dict(incoming or {})
    old_form, old_has_form = _report_form_from_section(current_section)
    new_form, new_has_form = _report_form_from_section(incoming_section)
    result = {**current_section, **incoming_section}

    # Reports are now partitioned by immutable Planning ID.  A browser can
    # legitimately send a delayed checkpoint containing only the currently
    # displayed run, so a shallow ``{**current, **incoming}`` merge would erase
    # the other runs' narratives, references, audit trail, and figure metadata.
    # Merge each run independently and keep the old entries that are absent from
    # this patch.  The recursive call is safe because a per-run section does not
    # normally contain another ``by_planning_id`` map; it also preserves the
    # timestamp/content protection below for each run.
    current_by_planning = current_section.get("by_planning_id")
    incoming_by_planning = incoming_section.get("by_planning_id")
    if isinstance(current_by_planning, Mapping) or isinstance(incoming_by_planning, Mapping):
        merged_by_planning: Dict[str, Any] = {}
        for planning_id in set(
            (current_by_planning.keys() if isinstance(current_by_planning, Mapping) else ())
        ) | set(
            (incoming_by_planning.keys() if isinstance(incoming_by_planning, Mapping) else ())
        ):
            old_section = (
                current_by_planning.get(planning_id)
                if isinstance(current_by_planning, Mapping) else None
            )
            new_section = (
                incoming_by_planning.get(planning_id)
                if isinstance(incoming_by_planning, Mapping) else None
            )
            if isinstance(old_section, Mapping) and isinstance(new_section, Mapping):
                merged_by_planning[str(planning_id)] = _merge_report_patch(old_section, new_section)
            elif isinstance(new_section, Mapping):
                merged_by_planning[str(planning_id)] = dict(new_section)
            elif isinstance(old_section, Mapping):
                merged_by_planning[str(planning_id)] = dict(old_section)
        result["by_planning_id"] = merged_by_planning
    if not new_has_form:
        return result
    old_time = _report_timestamp(old_form)
    new_time = _report_timestamp(new_form)
    old_score = _report_content_score(old_form)
    new_score = _report_content_score(new_form)
    keep_old = (
        old_time > new_time and old_score >= new_score
    ) or (
        new_time <= old_time and old_score > new_score
        and _report_narrative_length(old_form) > 0
        and _report_narrative_length(new_form) == 0
    )
    # Store the canonical wrapper after a merge. Remove legacy direct-form
    # fields so a later reader cannot choose two conflicting representations.
    for key in _REPORT_FORM_KEYS:
        result.pop(key, None)
    result.pop("form", None)
    merged_form = dict(old_form if keep_old else new_form)
    merged_form = _merge_report_quality_assessment(old_form, new_form, merged_form)
    result["form"] = merged_form
    return result


def _snapshot_planning_identity(snapshot: Mapping[str, Any]) -> Tuple[set[str], Optional[str]]:
    """Return Planning IDs owned by a workspace and its authoritative active ID.

    Report state is submitted by the browser, while Planning state is owned by
    the agent snapshot.  Keeping this boundary explicit prevents a delayed
    browser save from attaching another Session's report to the current case.
    """
    agent = snapshot.get("agent") if isinstance(snapshot, Mapping) else None
    results = agent.get("planning_results") if isinstance(agent, Mapping) else None
    if not isinstance(results, Mapping):
        return set(), None

    planning_ids: set[str] = set()
    runs = results.get("planning_runs")
    if isinstance(runs, list):
        for run in runs:
            if not isinstance(run, Mapping):
                continue
            planning_id = str(run.get("planning_id") or run.get("id") or "").strip()
            if planning_id:
                planning_ids.add(planning_id)
    for key in results:
        value = str(key)
        if value.startswith("planning_run:") and len(value) > len("planning_run:"):
            planning_ids.add(value[len("planning_run:"):])

    active = str(
        results.get("active_planning_id")
        or results.get("planning_run_id")
        or ""
    ).strip() or None
    if active:
        planning_ids.add(active)
    return planning_ids, active


def _report_form_session_id(section: Any) -> str:
    form, has_form = _report_form_from_section(section)
    if not has_form:
        return ""
    return str(form.get("sessionId") or form.get("session_id") or "").strip()


def _sanitize_report_for_snapshot(
    report: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    session_id: str,
) -> Dict[str, Any]:
    """Bind persisted report sections to Planning IDs owned by this Session."""
    result = dict(report or {})
    planning_ids, active_id = _snapshot_planning_identity(snapshot)
    requested_active = str(result.get("active_planning_id") or "").strip() or None
    if not active_id and requested_active and (
        not planning_ids or requested_active in planning_ids
    ):
        active_id = requested_active

    incoming_map = result.get("by_planning_id")
    filtered: Dict[str, Any] = {}
    if isinstance(incoming_map, Mapping):
        for raw_id, section in incoming_map.items():
            planning_id = str(raw_id or "").strip()
            if not planning_id or not isinstance(section, Mapping):
                continue
            if planning_ids and planning_id not in planning_ids:
                continue
            owner = _report_form_session_id(section)
            if owner and owner != str(session_id):
                continue
            filtered[planning_id] = dict(section)

    # Legacy snapshots kept the active report only at the top level. Promote
    # that section into the active run when it belongs to this Session.
    legacy_section = {
        key: value for key, value in result.items()
        if key not in {"active_planning_id", "by_planning_id"}
    }
    legacy_owner = _report_form_session_id(legacy_section)
    if active_id and active_id not in filtered and (
        not legacy_owner or legacy_owner == str(session_id)
    ):
        _, legacy_has_form = _report_form_from_section(legacy_section)
        if legacy_has_form:
            filtered[active_id] = legacy_section

    if active_id and active_id in filtered:
        sanitized = dict(filtered[active_id])
    elif not legacy_owner or legacy_owner == str(session_id):
        sanitized = legacy_section
    else:
        sanitized = {}
    sanitized["active_planning_id"] = active_id
    sanitized["by_planning_id"] = filtered
    return sanitized


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
        _configure_open_file_limit()
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
        self._checkpoint_generations: Dict[Tuple[str, str], int] = {}
        # Heavy snapshot preparation is serialized per case. Multiple UI
        # events may request a checkpoint at once, but they must not each scan
        # and fsync the same CT-sized artifact set concurrently.
        self._checkpoint_work_locks: Dict[Tuple[str, str], threading.Lock] = {}
        self._case_locks: Dict[Tuple[str, str], threading.RLock] = {}
        # Array references are process-local acceleration metadata. The durable
        # snapshot remains authoritative; after restart the encoder rebuilds a
        # nested name-to-path index so unchanged sidecars can be reused safely.
        self._array_refs: Dict[Tuple[str, str, str, str], Tuple[int, str]] = {}
        # Snapshot JSON is the control plane for session switching. Keep a
        # bounded process-local copy keyed by file identity so hot case opens
        # do not repeatedly parse the same large JSON document. The filesystem
        # remains authoritative and every write/delete invalidates this cache.
        self._snapshot_cache: Dict[
            Tuple[str, str], Tuple[int, int, Dict[str, Any]]
        ] = {}
        # Account quota checks used to recursively walk every case directory
        # for every uploaded megabyte.  Keep a process-local total instead:
        # writes invalidate it once, while a single upload uses one stable
        # baseline for its complete stream.  The filesystem remains the
        # authority after a restart or an external filesystem change.
        self._storage_usage_cache: Dict[str, int] = {}
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
            "chat": {"messages": [], "execution_trace": [], "attachments": []},
            "operation": {"state": "idle", "checkpoint": None},
        }

    def load_snapshot(self, user_id: str, session_id: str) -> Dict[str, Any]:
        record = self.get_session(user_id, session_id)
        path = self._snapshot_path(user_id, session_id)
        if not path.exists():
            snapshot = self._empty_snapshot(session_id)
        else:
            try:
                stat = path.stat()
                cache_key = (str(user_id), str(session_id))
                identity = (int(stat.st_mtime_ns), int(stat.st_size))
                with self._lock:
                    cached = self._snapshot_cache.get(cache_key)
                if cached is not None and cached[:2] == identity:
                    snapshot = copy.deepcopy(cached[2])
                else:
                    with open(path, "r", encoding="utf-8") as handle:
                        snapshot = json.load(handle)
                    with self._lock:
                        self._snapshot_cache[cache_key] = (
                            identity[0], identity[1], copy.deepcopy(snapshot),
                        )
            except (OSError, json.JSONDecodeError) as exc:
                raise WorkspaceError("Case workspace snapshot is unreadable") from exc
        if snapshot.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
            raise WorkspaceError("Case workspace schema is unsupported")
        if isinstance(snapshot.get("chat"), Mapping):
            # A screenshot may have been persisted just before the assistant
            # row or after a stale browser checkpoint.  Reconcile the durable
            # attachment index at read time as well, so a restart never loses
            # images merely because the original writes were out of order.
            snapshot["chat"] = _reconcile_chat_attachment_registry(snapshot["chat"])
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

    def replace_snapshot_section(
        self,
        user_id: str,
        session_id: str,
        section: str,
        value: Mapping[str, Any],
        *,
        reason: str = "workspace.section_replaced",
    ) -> Dict[str, Any]:
        """Atomically replace one top-level presentation section.

        ``save_snapshot_patch`` intentionally merges report/UI/chat state to
        protect a newer browser checkpoint. Delete operations need the opposite
        semantic: old report or chat artifacts must not survive as hidden keys.
        """
        if section not in {"ui", "report", "chat", "operation"}:
            raise WorkspaceError("Unsupported workspace section")
        with self._case_guard(user_id, session_id):
            root = self.workspace_root(user_id, session_id, create=True)
            snapshot = self.load_snapshot(user_id, session_id)
            snapshot[section] = _safe_json(dict(value or {}))
            snapshot["saved_at"] = _now()
            self._write_snapshot(user_id, root / "snapshot.json", snapshot)
            with self._connection() as connection:
                connection.execute(
                    "UPDATE case_sessions SET updated_at = ?, revision = revision + 1 "
                    "WHERE id = ? AND user_id = ?",
                    (_now(), session_id, user_id),
                )
            self._audit(user_id, session_id, reason, {"section": section})
            return self.load_snapshot(user_id, session_id)

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
                safe_patch = _safe_json(patch[key])
                if key == "chat":
                    # Chat is append-only.  A browser that was backgrounded
                    # before the latest turn completed can submit an older
                    # full array; shallow replacement would erase the newer
                    # Execution Trace and assistant response on restart.
                    snapshot[key] = _merge_chat_patch(current, safe_patch)
                elif key == "report":
                    merged_report = _merge_report_patch(current, safe_patch)
                    snapshot[key] = _sanitize_report_for_snapshot(
                        merged_report,
                        snapshot,
                        session_id,
                    )
                else:
                    snapshot[key] = {**current, **safe_patch}
        if isinstance(snapshot.get("chat"), Mapping):
            # Keep the message-level attachment contract materialized in the
            # snapshot itself.  This makes old clients and direct snapshot
            # readers see the same complete transcript as the new browser.
            snapshot["chat"] = _reconcile_chat_attachment_registry(snapshot["chat"])
        snapshot["saved_at"] = _now()
        self._write_snapshot(user_id, root / "snapshot.json", snapshot)
        with self._connection() as connection:
            connection.execute(
                "UPDATE case_sessions SET updated_at = ?, revision = revision + 1 WHERE id = ? AND user_id = ?",
                (_now(), session_id, user_id),
            )
        self._audit(user_id, session_id, reason, {"keys": sorted(patch.keys())})
        return self.load_snapshot(user_id, session_id)

    def _checkpoint_work_lock(self, user_id: str, session_id: str) -> threading.Lock:
        key = (str(user_id), str(session_id))
        with self._lock:
            lock = self._checkpoint_work_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._checkpoint_work_locks[key] = lock
            return lock

    def snapshot_agent(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        *,
        reason: str = "agent.checkpoint",
        operation: Optional[Mapping[str, Any]] = None,
        checkpoint_generation: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Serialize heavy checkpoint preparation one case at a time."""
        with self._checkpoint_work_lock(user_id, session_id):
            return self._snapshot_agent_locked(
                user_id,
                session_id,
                agent,
                reason=reason,
                operation=operation,
                checkpoint_generation=checkpoint_generation,
            )

    def _snapshot_agent_locked(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        *,
        reason: str = "agent.checkpoint",
        operation: Optional[Mapping[str, Any]] = None,
        checkpoint_generation: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Persist one coherent agent checkpoint for an account-owned case."""
        if checkpoint_generation is not None:
            with self._lock:
                current_generation = self._checkpoint_generations.get((user_id, session_id), 0)
            if int(checkpoint_generation) != int(current_generation):
                # A newer memory mutation is already scheduled. Do not take a
                # snapshot lock or walk the agent just to discard stale work.
                logger.debug(
                    "workspace checkpoint skipped stale session=%s reason=%s generation=%s current_generation=%s",
                    session_id, reason, checkpoint_generation, current_generation,
                )
                return {}
        started = time.perf_counter()
        logger.info(
            "workspace checkpoint started session=%s reason=%s",
            session_id, reason,
        )
        try:
            prepare_started = time.perf_counter()
            payload = self._prepare_agent_snapshot(user_id, session_id, agent)
            prepare_ms = (time.perf_counter() - prepare_started) * 1000.0
            if checkpoint_generation is not None:
                with self._lock:
                    current_generation = self._checkpoint_generations.get((user_id, session_id), 0)
                if int(checkpoint_generation) != int(current_generation):
                    self._discard_snapshot_payload(payload)
                    logger.info(
                        "workspace checkpoint discarded stale session=%s reason=%s generation=%s current_generation=%s duration_ms=%.1f",
                        session_id,
                        reason,
                        checkpoint_generation,
                        current_generation,
                        (time.perf_counter() - started) * 1000.0,
                    )
                    return {}
            logger.info(
                "workspace checkpoint prepared session=%s reason=%s duration_ms=%.1f arrays_created=%d arrays_reused=%d result_keys=%d",
                session_id,
                reason,
                prepare_ms,
                len(payload.get("created_array_paths") or []),
                int(payload.get("reused_array_count") or 0),
                len(payload.get("encoded_results") or {}),
            )
            commit_started = time.perf_counter()
            with self._case_guard(user_id, session_id):
                result = self._commit_agent_snapshot(
                    user_id, session_id, payload, reason=reason, operation=operation,
                )
            logger.info(
                "workspace checkpoint completed session=%s reason=%s duration_ms=%.1f commit_ms=%.1f discarded=%s",
                session_id,
                reason,
                (time.perf_counter() - started) * 1000.0,
                (time.perf_counter() - commit_started) * 1000.0,
                not bool(result),
            )
            return result
        except Exception:
            logger.warning(
                "workspace checkpoint failed session=%s reason=%s duration_ms=%.1f",
                session_id,
                reason,
                (time.perf_counter() - started) * 1000.0,
                exc_info=True,
            )
            raise

    def _discard_snapshot_payload(self, payload: Mapping[str, Any]) -> None:
        """Remove sidecars produced by a checkpoint invalidated before commit."""
        root = payload.get("root")
        created_array_paths = list(payload.get("created_array_paths") or [])
        if not isinstance(root, Path):
            return
        for relative in created_array_paths:
            try:
                _safe_workspace_child(root, str(relative)).unlink(missing_ok=True)
            except (OSError, WorkspaceError):
                continue
        with self._lock:
            for cache_key, value in list(self._array_refs.items()):
                if cache_key[:2] == (str(payload.get("user_id") or ""), str(payload.get("session_id") or "")):
                    if value[1] in created_array_paths:
                        self._array_refs.pop(cache_key, None)

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
                # Persist versions so a post-restart checkpoint can reuse
                # unchanged NPY sidecars instead of rewriting CT-sized arrays.
                "planning_versions": _safe_json(planning_versions),
                "ui_state": _safe_json(memory.get_ui_state()),
                "runtime_state": _safe_json(
                    agent.run_ledger.export_state()
                    if hasattr(agent, "run_ledger") else {}
                ),
            }
        root = self.workspace_root(user_id, session_id, create=True)
        durable_snapshot = self.load_snapshot(user_id, session_id)
        durable_state = durable_snapshot.get("agent") if isinstance(durable_snapshot.get("agent"), Mapping) else {}
        durable_results = durable_state.get("planning_results") if isinstance(durable_state.get("planning_results"), Mapping) else {}
        durable_versions = durable_state.get("planning_versions") if isinstance(durable_state.get("planning_versions"), Mapping) else {}
        preserve_durable_results = bool(
            getattr(agent, "_workspace_hydration_in_progress", False)
            or getattr(agent, "_workspace_data_ready", True) is False
        )
        if preserve_durable_results:
            # A cold-start metadata pass intentionally replaces array values
            # with None until the detached hydration worker decodes their NPY
            # sidecars. UI/report checkpoints can still run during that window.
            # Treat unchanged durable versions as authoritative so a lightweight
            # checkpoint cannot replace dose, masks, Planning runs, guides, or
            # skin arrays with the metadata-only placeholders and then prune the
            # only sidecar files that can restore them.
            for key, version in durable_versions.items():
                planning_versions.setdefault(str(key), int(version or 0))
            agent_state["planning_versions"] = _safe_json(planning_versions)
        created_array_paths: List[str] = []
        reused_array_count = 0

        # Reuse nested arrays after a process restart.  A top-level lookup is
        # insufficient for OAR/CTV payloads because their arrays are commonly
        # stored below a structure-name mapping.  Rebuilding this name-to-path
        # index keeps restart checkpoints from rewriting hundreds of megabytes
        # of unchanged masks.
        durable_array_refs: Dict[Tuple[str, str], str] = {}

        def collect_array_refs(value: Any, name: str, source_key: str) -> None:
            if isinstance(value, Mapping):
                if "$array" in value:
                    durable_array_refs[(source_key, name)] = str(value["$array"])
                    return
                for key, item in value.items():
                    collect_array_refs(item, f"{name}_{key}", source_key)
            elif isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    collect_array_refs(item, f"{name}_{index}", source_key)

        for source_key, value in durable_results.items():
            collect_array_refs(value, _safe_filename(source_key), str(source_key))

        def reuse_array(source_key: str, name: str) -> Optional[str]:
            nonlocal reused_array_count
            cache_key = (user_id, session_id, source_key, name)
            cached = self._array_refs.get(cache_key)
            version = int(planning_versions.get(source_key, 0))
            if not cached or cached[0] != version:
                previous_version = durable_versions.get(source_key)
                # A fresh process has no in-memory _array_refs.  Reuse a
                # directly persisted array, including nested OAR/CTV arrays,
                # when its memory version still matches the durable snapshot;
                # changed arrays have a new version and are written atomically.
                candidate = durable_array_refs.get((source_key, name))
                if (candidate and previous_version is not None
                        and int(previous_version) == version):
                    try:
                        if _safe_workspace_child(root, candidate).is_file():
                            self._array_refs[cache_key] = (version, candidate)
                            reused_array_count += 1
                            return candidate
                    except (TypeError, ValueError, WorkspaceError):
                        pass
                return None
            relative = cached[1]
            try:
                if _safe_workspace_child(root, relative).is_file():
                    reused_array_count += 1
                    return relative
            except WorkspaceError:
                pass
            return None

        def record_array(source_key: str, name: str, relative: str) -> None:
            cache_key = (user_id, session_id, source_key, name)
            self._array_refs[cache_key] = (int(planning_versions.get(source_key, 0)), relative)
            created_array_paths.append(relative)

        user = self.get_user_by_id(user_id)
        quota = int(user["storage_quota_bytes"]) if user else DEFAULT_USER_QUOTA_BYTES
        # If no planning result/version changed, every array can be reused and
        # a full account-wide recursive size scan adds latency without adding
        # safety. A changed/new result still performs the exact quota check.
        arrays_may_change = (
            planning_versions != durable_versions
            or set(str(key) for key in planning_results)
            != set(str(key) for key in durable_results)
        )
        if arrays_may_change:
            capacity_started = time.perf_counter()
            capacity_remaining = quota - self.user_storage_bytes(user_id)
            logger.info(
                "workspace checkpoint capacity scanned session=%s duration_ms=%.1f remaining_bytes=%d",
                session_id,
                (time.perf_counter() - capacity_started) * 1000.0,
                capacity_remaining,
            )
        else:
            capacity_remaining = quota
            logger.info(
                "workspace checkpoint capacity scan skipped session=%s reason=unchanged_arrays",
                session_id,
            )

        def ensure_snapshot_capacity(path: Path, new_size: int) -> None:
            nonlocal capacity_remaining
            try:
                previous_size = path.stat().st_size if path.exists() else 0
            except OSError:
                previous_size = 0
            delta = max(0, int(new_size) - int(previous_size))
            if delta > capacity_remaining:
                raise WorkspaceQuotaExceeded("Account storage quota would be exceeded")
            capacity_remaining -= delta

        encode_started = time.perf_counter()
        encoder = _ArtifactEncoder(
            root,
            ensure_capacity=ensure_snapshot_capacity,
            reuse_array=reuse_array,
            record_array=record_array,
            array_version=lambda source_key: int(planning_versions.get(source_key, 0)),
        )
        encoded_results: Dict[str, Any] = {}
        ct_path_value = str(
            planning_results.get("ct_path")
            or planning_results.get("ct_image_path")
            or ""
        ).strip()
        ct_can_be_reloaded = False
        if ct_path_value:
            try:
                ct_candidate = Path(ct_path_value).expanduser()
                if not ct_candidate.is_absolute():
                    ct_candidate = _safe_workspace_child(root, ct_path_value)
                ct_can_be_reloaded = ct_candidate.is_file()
            except (OSError, WorkspaceError, ValueError):
                ct_can_be_reloaded = False
        skipped_transient_results: List[str] = []

        def should_skip_result(key: str, value: Any) -> bool:
            if key in TRANSIENT_PLANNING_RESULT_KEYS:
                return True
            if key == "trajectories":
                try:
                    if len(value) > TRANSIENT_COLLECTION_LIMIT:
                        return True
                except (TypeError, ValueError):
                    pass
            if key in {"ct_image", "ct_sitk", "ct_image_raw"}:
                return True
            if key == "ct_data" and ct_can_be_reloaded:
                return True
            return False

        def durable_version_matches(key: str) -> bool:
            if key not in durable_versions or key not in planning_versions:
                return False
            try:
                return int(durable_versions[key]) == int(planning_versions[key])
            except (TypeError, ValueError):
                return False

        for key, value in planning_results.items():
            key = str(key)
            if should_skip_result(key, value):
                skipped_transient_results.append(key)
                continue
            if (
                preserve_durable_results
                and key in durable_results
                and durable_version_matches(key)
            ):
                # Reuse the entire encoded value, not only its top-level array.
                # Planning run snapshots contain deeply nested dose and skin
                # arrays whose metadata-only representation is a tree of None
                # placeholders during cold-start hydration.
                encoded_results[key] = durable_results[key]
                continue
            encoded = encoder.encode(value, _safe_filename(key), str(key))
            if isinstance(encoded, dict) and "$image" in encoded:
                continue
            encoded_results[key] = encoded

        if preserve_durable_results:
            for raw_key, durable_value in durable_results.items():
                key = str(raw_key)
                if key in encoded_results or should_skip_result(key, durable_value):
                    continue
                if durable_version_matches(key):
                    # Top-level arrays disappear completely from a metadata
                    # hydration pass. Preserve those missing unchanged keys as
                    # well as nested arrays handled above.
                    encoded_results[key] = durable_value
        logger.info(
            "workspace checkpoint artifacts encoded session=%s duration_ms=%.1f arrays_created=%d arrays_reused=%d transient_skipped=%s preserve_durable=%s",
            session_id,
            (time.perf_counter() - encode_started) * 1000.0,
            len(created_array_paths),
            reused_array_count,
            ",".join(skipped_transient_results) or "none",
            preserve_durable_results,
        )
        return {
            "agent_state": agent_state,
            "encoded_results": encoded_results,
            "created_array_paths": created_array_paths,
            "reused_array_count": reused_array_count,
            "root": root,
            "user_id": user_id,
            "session_id": session_id,
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
        commit_started = time.perf_counter()
        try:
            snapshot = self.load_snapshot(user_id, session_id)
        except WorkspaceNotFound:
            # The case session has been deleted or moved to trash since
            # the checkpoint was scheduled.  Discard the sidecar arrays
            # and return an empty snapshot — there is nothing to save.
            for relative in created_array_paths:
                try:
                    _safe_workspace_child(root, relative).unlink(missing_ok=True)
                except (OSError, WorkspaceError):
                    continue
            for cache_key, value in list(self._array_refs.items()):
                if cache_key[:2] == (user_id, session_id) and value[1] in created_array_paths:
                    self._array_refs.pop(cache_key, None)
            return {}
        try:
            snapshot["agent"] = {**agent_state, "planning_results": encoded_results}
            if operation is not None:
                snapshot["operation"] = _safe_json(operation)
            snapshot["saved_at"] = _now()
            write_started = time.perf_counter()
            self._write_snapshot(user_id, root / "snapshot.json", snapshot)
            logger.info(
                "workspace checkpoint snapshot written session=%s duration_ms=%.1f",
                session_id,
                (time.perf_counter() - write_started) * 1000.0,
            )
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

        prune_started = time.perf_counter()
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
        logger.info(
            "workspace checkpoint artifacts committed session=%s duration_ms=%.1f prune_ms=%.1f",
            session_id,
            (time.perf_counter() - commit_started) * 1000.0,
            (time.perf_counter() - prune_started) * 1000.0,
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

    def hydrate_agent(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        *,
        include_planning_results: bool = True,
        load_ct: bool = True,
        mark_interrupted: bool = True,
        cancel_event: Any = None,
        phase_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Hydrate one case while its checkpoint sidecars are read-consistent.

        Checkpoints publish a new JSON snapshot and then prune array sidecars
        that are no longer referenced by that snapshot.  Hydration must hold
        the same per-case work lock from snapshot read through array decode;
        otherwise it can read an older snapshot and lose its sidecar between
        those two operations.
        """
        with self._checkpoint_work_lock(user_id, session_id):
            return self._hydrate_agent_locked(
                user_id,
                session_id,
                agent,
                include_planning_results=include_planning_results,
                load_ct=load_ct,
                mark_interrupted=mark_interrupted,
                cancel_event=cancel_event,
                phase_callback=phase_callback,
            )

    def _hydrate_agent_locked(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        *,
        include_planning_results: bool = True,
        load_ct: bool = True,
        mark_interrupted: bool = True,
        cancel_event: Any = None,
        phase_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Load a checkpoint into a fresh agent without evaluating any code.

        A lightweight pass restores only JSON metadata and UI/chat state. Large
        NPY sidecars and the CT volume can then be restored by a detached
        worker, keeping case selection and the first browser paint responsive.
        """
        started = time.perf_counter()
        logger.info(
            "workspace hydration started session=%s planning_results=%s ct=%s",
            session_id, include_planning_results, load_ct,
        )
        snapshot_started = time.perf_counter()
        snapshot = self.load_snapshot(user_id, session_id)
        logger.info(
            "workspace hydration snapshot loaded session=%s duration_ms=%.1f",
            session_id,
            (time.perf_counter() - snapshot_started) * 1000.0,
        )
        root = self.workspace_root(user_id, session_id)
        state = snapshot.get("agent") or {}
        memory = agent.memory
        decode_started = time.perf_counter()
        if phase_callback is not None:
            phase_callback("artifacts" if include_planning_results else "metadata")
        if cancel_event is not None and cancel_event.is_set():
            logger.info("workspace hydration cancelled before decode session=%s", session_id)
            return snapshot
        decoded_results: Dict[str, Any] = {}
        persisted_results = state.get("planning_results") or {}
        persisted_ct_path = str(
            _restore_hydration_metadata(persisted_results.get("ct_path")) or ""
        ).strip()
        has_durable_ct_path = False
        if persisted_ct_path:
            try:
                persisted_ct_file = Path(persisted_ct_path).expanduser()
                if not persisted_ct_file.is_absolute():
                    persisted_ct_file = _safe_workspace_child(root, persisted_ct_path)
                # Absolute paths from snapshots are accepted only when they
                # still belong to this case workspace.
                persisted_ct_file.resolve().relative_to(root.resolve())
                has_durable_ct_path = persisted_ct_file.is_file()
            except (OSError, WorkspaceError, ValueError):
                has_durable_ct_path = False
        for key, value in persisted_results.items():
            if include_planning_results and key == "ct_data" and has_durable_ct_path:
                # Backward compatibility for old snapshots that duplicated CT
                # as an NPY sidecar. Reading the owned CT input is faster and
                # guarantees one physical geometry source.
                continue
            decoded = (
                _decode_artifacts(value, root)
                if include_planning_results
                else _restore_hydration_metadata(value)
            )
            if decoded is not None:
                decoded_results[str(key)] = decoded
        patient_data = _restore_json(state.get("patient_data") or {})
        conversation = _restore_json(state.get("conversation") or [])
        tool_results = _restore_json(state.get("tool_results") or [])
        context_summary = str(state.get("context_summary") or "")
        compaction_count = int(state.get("compaction_count") or 0)
        conversation_state = _restore_json(state.get("conversation_state") or {})
        user_lang = str(state.get("user_lang") or "en")
        ui_state = _restore_json(state.get("ui_state") or {})
        planning_versions = (
            {
                str(key): int(value or 0)
                for key, value in state["planning_versions"].items()
            }
            if isinstance(state.get("planning_versions"), Mapping)
            else {str(key): 1 for key in decoded_results}
        )
        if cancel_event is not None and cancel_event.is_set():
            logger.info("workspace hydration cancelled before atomic publish session=%s", session_id)
            return snapshot
        # NPY decoding can take seconds for a large case. Never hold the Agent
        # memory lock during that I/O. Publish one coherent version only after
        # every artifact has decoded and preserve a CT loaded by the earlier
        # CT-first hydration phase.
        runtime_ct_keys = {
            "ct_image", "ct_sitk", "ct_image_raw", "ct_data", "ct_shape",
            "ct_spacing", "ct_origin", "ct_direction", "ct_axis_map",
            "ct_window_center", "ct_window_width", "ct_source_kind",
            "ct_source_meta", "ct_dicom_tags",
        }
        with memory._lock:
            # An explicit CT import can cancel this worker after the first
            # check above but before the lock becomes available.  Check again
            # inside the publish critical section so old session artifacts can
            # never clear or overwrite a newly imported case.
            if cancel_event is not None and cancel_event.is_set():
                logger.info("workspace hydration cancelled during atomic publish session=%s", session_id)
                return snapshot
            live_ct = {
                key: memory.planning_results[key]
                for key in runtime_ct_keys
                if key in memory.planning_results
                and memory.planning_results[key] is not None
            }
            memory.planning_results.clear()
            memory.planning_results.update(decoded_results)
            if include_planning_results:
                for key, value in live_ct.items():
                    memory.planning_results.setdefault(key, value)
            if hasattr(memory, "_planning_versions"):
                memory._planning_versions = planning_versions
            memory.patient_data = patient_data
            memory.conversation = conversation
            memory.tool_results = tool_results
            memory.context_summary = context_summary
            memory.compaction_count = compaction_count
            if not conversation_state:
                conversation_state = _restore_json(memory.conversation_state)
            memory.conversation_state = conversation_state
            memory.user_lang = user_lang
            memory._ui_state = ui_state
            memory.conversation_state["data_available"] = sorted(
                memory.planning_results.keys()
            )
        restored_aliases: List[str] = []
        if include_planning_results:
            # Historical Planning snapshots are immutable and authoritative.
            # Recreate any missing compatibility aliases before HTTP routes
            # expose the hydrated agent, so seeds, needles, dose, DVH, guide,
            # and skin all become available in the same ready transition.
            try:
                from web.planning_runs import restore_active_planning_aliases

                restored_aliases = restore_active_planning_aliases(memory)
            except Exception:
                logger.exception(
                    "workspace hydration could not restore active Planning aliases session=%s",
                    session_id,
                )
        logger.info(
            "workspace hydration arrays decoded session=%s duration_ms=%.1f result_keys=%d restored_aliases=%s",
            session_id,
            (time.perf_counter() - decode_started) * 1000.0,
            len(memory.planning_results),
            ",".join(restored_aliases) or "none",
        )
        if isinstance(state.get("config"), Mapping):
            agent.config.update(_restore_json(state["config"]))
        if hasattr(agent, "run_ledger") and isinstance(state.get("runtime_state"), Mapping):
            agent.run_ledger.restore_state(_restore_json(state["runtime_state"]))
        ct_started = time.perf_counter()
        if load_ct:
            if phase_callback is not None:
                phase_callback("ct")
            if cancel_event is not None and cancel_event.is_set():
                logger.info("workspace hydration cancelled before CT restore session=%s", session_id)
                return snapshot
            self._hydrate_ct_image(root, memory, cancel_event=cancel_event)
        logger.info(
            "workspace hydration CT phase finished session=%s duration_ms=%.1f ct_loaded=%s",
            session_id,
            (time.perf_counter() - ct_started) * 1000.0,
            memory.retrieve("ct_data") is not None,
        )
        operation = snapshot.get("operation") or {}
        if mark_interrupted and operation.get("state") == "running":
            snapshot = self.mark_session_interrupted(user_id, session_id, "Server restarted before the task completed")
        logger.info(
            "workspace hydration completed session=%s duration_ms=%.1f",
            session_id,
            (time.perf_counter() - started) * 1000.0,
        )
        return snapshot

    @staticmethod
    def _hydrate_ct_image(root: Path, memory: Any, *, cancel_event: Any = None) -> None:
        if memory.retrieve("ct_data") is not None:
            return
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
            # Restore the same physical grid used by the viewer and all
            # current segmentation outputs.  Keeping a raw-direction CT here
            # beside LPI masks recreates the mirror/translation bug after a
            # server restart.
            raw_image = sitk.ReadImage(str(path))
            image = sitk.DICOMOrient(raw_image, "LPI")
            import numpy as np
            array = sitk.GetArrayFromImage(image)
            if cancel_event is not None and cancel_event.is_set():
                return
            with memory._lock:
                if cancel_event is not None and cancel_event.is_set():
                    return
                memory.planning_results["ct_path"] = str(path)
                memory.planning_results["ct_image"] = image
                memory.planning_results["ct_sitk"] = image
                memory.planning_results["ct_image_raw"] = raw_image
                memory.planning_results["ct_data"] = array
                memory.planning_results["ct_shape"] = list(array.shape)
                memory.planning_results["ct_spacing"] = tuple(float(v) for v in image.GetSpacing())
                memory.planning_results["ct_origin"] = tuple(float(v) for v in image.GetOrigin())
                memory.planning_results["ct_direction"] = tuple(float(v) for v in image.GetDirection())
                memory.planning_results["ct_axis_map"] = {"axial": 0, "sagittal": 2, "coronal": 1}
        except Exception:
            # A damaged CT must not prevent the rest of the session metadata
            # from being inspected or deleted.
            return

    def schedule_agent_checkpoint(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        reason: str,
        operation: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Debounce high-frequency memory changes without dropping durability."""
        key = (user_id, session_id)
        with self._lock:
            existing = self._checkpoint_timers.pop(key, None)
            if existing:
                existing.cancel()
            generation = self._checkpoint_generations.get(key, 0) + 1
            self._checkpoint_generations[key] = generation
            timer = threading.Timer(
                0.75,
                self._checkpoint_timer,
                args=(user_id, session_id, agent, reason, operation, generation),
            )
            timer.daemon = True
            self._checkpoint_timers[key] = timer
            timer.start()

    def _checkpoint_timer(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        reason: str,
        operation: Optional[Mapping[str, Any]] = None,
        generation: Optional[int] = None,
    ) -> None:
        key = (user_id, session_id)
        # Never queue a second full snapshot behind an active one. The old
        # implementation blocked on the per-case lock, then encoded and
        # discarded each stale generation in turn. A non-blocking retry lets
        # the newest generation win without serially replaying obsolete work.
        with self._lock:
            current_generation = self._checkpoint_generations.get(key, 0)
            if generation is not None and int(generation) != int(current_generation):
                self._checkpoint_timers.pop(key, None)
                return
            self._checkpoint_timers.pop(key, None)
        work_lock = self._checkpoint_work_lock(user_id, session_id)
        if not work_lock.acquire(blocking=False):
            with self._lock:
                latest_generation = self._checkpoint_generations.get(key, 0)
                if generation is None or int(generation) == int(latest_generation):
                    retry = threading.Timer(
                        0.25,
                        self._checkpoint_timer,
                        args=(user_id, session_id, agent, reason, operation, latest_generation),
                    )
                    retry.daemon = True
                    self._checkpoint_timers[key] = retry
                    retry.start()
            return
        try:
            self._snapshot_agent_locked(
                user_id, session_id, agent, reason=reason,
                operation=operation, checkpoint_generation=generation,
            )
        except WorkspaceNotFound:
            pass
        except Exception:
            logger.warning(
                "Agent checkpoint failed for session %s (reason: %s)",
                session_id, reason, exc_info=True,
            )
        finally:
            work_lock.release()

    def flush_agent_checkpoint(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        reason: str,
        operation: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        key = (user_id, session_id)
        with self._lock:
            timer = self._checkpoint_timers.pop(key, None)
            if timer:
                timer.cancel()
            generation = self._checkpoint_generations.get(key, 0) + 1
            self._checkpoint_generations[key] = generation
        return self.snapshot_agent(
            user_id,
            session_id,
            agent,
            reason=reason,
            operation=operation,
            checkpoint_generation=generation,
        )

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
            self._checkpoint_generations[key] = self._checkpoint_generations.get(key, 0) + 1

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
        with self._lock:
            self._snapshot_cache.pop((str(user_id), str(session_id)), None)
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
        with self._lock:
            self._snapshot_cache.pop((str(user_id), str(session_id)), None)
        self._audit(user_id, session_id, "session.restored", {})
        return self.get_session(user_id, session_id)

    def permanently_delete(self, user_id: str, session_id: str) -> None:
        record = self.get_session(user_id, session_id, include_trashed=True)
        for root in (self.workspace_root(user_id, session_id), self.workspace_root(user_id, session_id, trashed=True)):
            if root.exists():
                shutil.rmtree(root)
        with self._connection() as connection:
            connection.execute("DELETE FROM case_sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
        with self._lock:
            self._snapshot_cache.pop((str(user_id), str(session_id)), None)
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
        user_key = str(user_id)
        with self._lock:
            cached = self._storage_usage_cache.get(user_key)
        if cached is not None:
            return cached
        total = 0
        for base in (self.workspaces_dir / user_key, self.trash_dir / user_key):
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if path.is_file():
                    try:
                        total += path.stat().st_size
                    except OSError:
                        continue
        with self._lock:
            self._storage_usage_cache[user_key] = total
        return total

    def _invalidate_storage_usage(self, user_id: str) -> None:
        """Mark one account's quota total stale after a filesystem mutation."""
        with self._lock:
            self._storage_usage_cache.pop(str(user_id), None)

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
        self._invalidate_storage_usage(user_id)
        try:
            stat = path.stat()
            session_id = str(snapshot.get("session_id") or path.parent.name)
            with self._lock:
                self._snapshot_cache[(str(user_id), session_id)] = (
                    int(stat.st_mtime_ns), int(stat.st_size),
                    copy.deepcopy(dict(snapshot)),
                )
        except (OSError, TypeError, ValueError):
            # The durable atomic write already succeeded. A cache update is
            # optional acceleration and must never turn it into a failed save.
            pass

    def write_upload(self, user_id: str, session_id: str, relative: str, stream: Any, expected_bytes: int = 0) -> Path:
        self.get_session(user_id, session_id)
        root = self.workspace_root(user_id, session_id, create=True)
        path = _safe_workspace_child(root / "inputs", relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Take one capacity snapshot before streaming.  Calling
        # ``user_storage_bytes`` from the loop below previously performed an
        # account-wide rglob for every 1 MiB chunk, making a small CT upload
        # appear frozen when old sessions contained large NPY artifacts.
        user = self.get_user_by_id(user_id)
        if not user:
            raise WorkspaceNotFound("Account is unavailable")
        try:
            previous_size = path.stat().st_size if path.exists() else 0
        except OSError:
            previous_size = 0
        quota_remaining = int(user["storage_quota_bytes"]) - self.user_storage_bytes(user_id) + int(previous_size)
        expected = max(0, int(expected_bytes or 0))
        if expected and expected > quota_remaining:
            raise WorkspaceQuotaExceeded("Account storage quota would be exceeded")
        temp = self.staging_dir / f"input-{secrets.token_hex(16)}.part"
        written = 0
        try:
            with open(temp, "wb") as handle:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > quota_remaining:
                        raise WorkspaceQuotaExceeded("Account storage quota would be exceeded")
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            self._invalidate_storage_usage(user_id)
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
        self._invalidate_storage_usage(user_id)
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
        user = self.get_user_by_id(user_id)
        if not user:
            raise WorkspaceNotFound("Account is unavailable")
        try:
            previous_size = path.stat().st_size if path.exists() else 0
        except OSError:
            previous_size = 0
        quota_remaining = int(user["storage_quota_bytes"]) - self.user_storage_bytes(user_id) + int(previous_size)
        expected = max(0, int(expected_bytes or 0))
        if expected and expected > quota_remaining:
            raise WorkspaceQuotaExceeded("Account storage quota would be exceeded")
        temp = self.staging_dir / f"artifact-{secrets.token_hex(16)}.part"
        written = 0
        try:
            with open(temp, "wb") as handle:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > quota_remaining:
                        raise WorkspaceQuotaExceeded("Account storage quota would be exceeded")
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            self._invalidate_storage_usage(user_id)
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
