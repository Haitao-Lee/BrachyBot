"""
AI-BrachyAgent Web API Server
=============================
REST API server with WebSocket support for real-time updates.
Run: python web/server.py
"""

import os
import sys
import json
import logging
import time
import threading
import secrets
import hashlib
import hmac
import base64
import binascii
import math
import re
from collections import deque
from datetime import datetime
from typing import Dict, Any, Optional, Iterable
from functools import wraps

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from flask import request, jsonify, send_from_directory, Response
from flask_cors import CORS
from plans.dose_pre.model_loader import DOSE_MODEL_SCALE_GY

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(WEB_DIR, "app")
PROJECT_ROOT = os.path.realpath(os.path.join(WEB_DIR, ".."))
UPLOAD_DIR = os.path.realpath(os.path.join(PROJECT_ROOT, "uploads"))
RUNTIME_DIR = os.path.realpath(os.path.expanduser(
    os.environ.get("BRACHYBOT_RUNTIME_DIR", os.path.join(PROJECT_ROOT, ".runtime"))
))
OUTPUT_DIRS = [
    os.path.realpath(os.path.join(PROJECT_ROOT, "output")),
    os.path.realpath(os.path.join(PROJECT_ROOT, "outputs")),
]
SCREENSHOTS_DIR = os.path.realpath(os.path.join(UPLOAD_DIR, "screenshots"))

TRUE_VALUES = {"1", "true", "yes", "on"}
ALLOWED_UPLOAD_EXTENSIONS = {
    ".nii", ".nii.gz", ".mha", ".mhd", ".nrrd", ".dcm", ".dicom",
}
ALLOWED_DICOM_SERIES_EXTENSIONS = {"", ".dcm", ".dicom"}
MAX_UPLOAD_FILES = int(os.environ.get("BRACHYBOT_MAX_UPLOAD_FILES", "3000"))
MAX_SCREENSHOT_BYTES = int(os.environ.get("BRACHYBOT_MAX_SCREENSHOT_BYTES", str(25 * 1024 * 1024)))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _canonical_oar_display_name(name: Any, label_id: Any = None) -> str:
    """Return a clinically meaningful OAR label without inventing anatomy.

    Older snapshots used strings such as ``Organ 10000`` when a mask label
    was not present in the TotalSegmentator mapping.  Those strings are
    implementation placeholders, not anatomical names, and must never be
    emitted in a report or viewer.  Known numeric labels are resolved from
    the authoritative mapping; unknown labels remain explicitly unmapped.
    """
    raw = str(name or "").strip()
    generic = bool(re.fullmatch(r"(?i)(?:organ|organ_|label|structure)[ _-]?\d+", raw))
    if raw and not generic:
        return raw
    try:
        numeric_label = int(label_id if label_id is not None else re.search(r"\d+", raw).group(0))
    except (AttributeError, TypeError, ValueError):
        numeric_label = None
    if numeric_label is not None:
        try:
            from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
            mapped = TOTALSEG_LABEL_MAPPING.get(numeric_label)
            if mapped:
                return str(mapped)
        except (ImportError, AttributeError, TypeError):
            pass
        return f"Unmapped structure (label {numeric_label})"
    return raw or "Unmapped structure"


_UPLOADED_OAR_SOURCES = {
    "uploaded_unknown",
    "manual_label",
    "uploaded",
    "manual_upload",
}


def _oar_display_name_map(agent: Any, oar_array: Any = None) -> Dict[int, str]:
    """Build OAR names without inventing anatomy for uploaded labels.

    Model-produced masks carry an authoritative label map.  An uploaded
    multi-label mask normally carries no ontology, so its labels are exposed
    as stable ``OAR 1``, ``OAR 2`` identifiers and remain traversable until a
    user explicitly renames or reclassifies them in the Data Tree.  This
    provenance gate prevents a numeric label from being mistaken for a
    TotalSegmentator label merely because the integer happens to match.
    """
    memory = getattr(agent, "memory", None)
    retrieve = getattr(memory, "retrieve", None)
    if not callable(retrieve):
        return {}
    source = str(
        retrieve("oar_source", retrieve("oar_mask_provenance", "")) or ""
    ).strip().lower()
    names = retrieve("organ_names", {}) or {}
    if not isinstance(names, dict):
        names = {}
    if oar_array is None:
        try:
            oar_array = agent._get_label_array("oar_array")
        except Exception:
            oar_array = retrieve("oar_array")

    label_ids = set()
    try:
        import numpy as _np
        label_ids = {int(value) for value in _np.unique(oar_array) if int(value) > 0}
    except Exception:
        for value in names:
            try:
                if int(value) > 0:
                    label_ids.add(int(value))
            except (TypeError, ValueError):
                continue

    def _raw_name(label_id: int) -> str:
        return str(names.get(label_id, names.get(str(label_id), "")) or "").strip()

    def _is_generic(value: str) -> bool:
        return bool(re.fullmatch(
            r"(?i)(?:oar|organ|label|structure|unmapped(?: structure)?)"
            r"[ _-]?(?:\d+|\(label\s*\d+\))?", value.strip()
        ))

    result: Dict[int, str] = {}
    for ordinal, label_id in enumerate(sorted(label_ids), start=1):
        raw = _raw_name(label_id)
        # An uploaded OAR label file has no trusted ontology. Even if an old
        # model run left names such as ``stomach`` in the checkpoint, never
        # expose those names as facts for the new opaque mask. The Data Tree
        # can later carry an explicit user rename/reclassification.
        if source in _UPLOADED_OAR_SOURCES:
            result[label_id] = f"OAR {ordinal}"
            continue
        # Explicit names are preserved so a user's rename survives refreshes.
        if raw and not _is_generic(raw):
            result[label_id] = raw
            continue
        if not source:
            result[label_id] = f"OAR {ordinal}"
            continue
        # Numeric fallback is allowed only for the known TotalSegmentator
        # ontology. Other model outputs must provide their own metadata.
        if source in {"totalsegmentator", "model_totalsegmentator"}:
            try:
                from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
                mapped = TOTALSEG_LABEL_MAPPING.get(label_id)
            except Exception:
                mapped = None
            result[label_id] = str(mapped or f"OAR {ordinal}")
        else:
            result[label_id] = f"OAR {ordinal}"
    return result

# API key for authentication. Local loopback development can run without a key;
# non-loopback startup is refused unless BRACHYBOT_API_KEY is set or the
# explicitly unsafe BRACHYBOT_ALLOW_INSECURE_REMOTE=1 override is provided.
# BRACHYBOT_TRUST_NETWORK only broadens LAN CORS/rate-limit policy; it never
# disables a configured API key.
API_KEY = os.environ.get("BRACHYBOT_API_KEY", None)
_TRUST_NETWORK = os.environ.get("BRACHYBOT_TRUST_NETWORK", "").lower() in TRUE_VALUES
_API_KEY_REQUIRED = bool(API_KEY) or os.environ.get("BRACHYBOT_REQUIRE_API_KEY", "").lower() in TRUE_VALUES
if _API_KEY_REQUIRED and not API_KEY:
    raise RuntimeError(
        "BRACHYBOT_REQUIRE_API_KEY is enabled but BRACHYBOT_API_KEY is not set"
    )
if not API_KEY and not _TRUST_NETWORK:
    logger.info("API key auth is disabled for loopback local development")

# Trusted network: no rate limiting. Local dev: generous limit.
RATE_LIMIT_REQUESTS = 9999 if _TRUST_NETWORK else 120
RATE_LIMIT_WINDOW = 60
_rate_limit_store: Dict[str, list] = {}
_rate_limit_lock = threading.Lock()

_MESH_CACHE_LOCK = threading.Lock()
_MESH_CACHE: Dict[tuple, Dict[str, Any]] = {}
_MESH_CACHE_ORDER = deque()
_MESH_CACHE_MAX_ITEMS = int(os.environ.get("BRACHYBOT_MESH_CACHE_MAX_ITEMS", "96"))

_MANUAL_DOSE_MODEL_LOCK = threading.RLock()
_MANUAL_DOSE_MODEL_CACHE: Dict[str, Any] = {}
# Per-seed predictions are immutable CPU arrays. A needle edit usually moves
# only the seeds on one trajectory; reusing unchanged seed maps makes that
# interaction incremental while preserving the exact trained DoseUNet output.
_MANUAL_DOSE_SEED_CACHE: Dict[tuple, Any] = {}
_MANUAL_DOSE_SEED_CACHE_ORDER: list = []
_MANUAL_DOSE_SEED_CACHE_LIMIT = 128
DOSE_MODEL_UNITS = "normalized_model_output"


class TaskManager:
    """Manages background task progress for SSE streaming."""
    def __init__(self, max_tasks: int = 1000, ttl_seconds: int = 3600):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._max_tasks = max_tasks
        self._ttl_seconds = ttl_seconds

    def _prune_locked(self):
        now = time.time()
        expired = [
            tid for tid, task in self._tasks.items()
            if task.get("status") != "running" and now - task.get("updated_at", now) > self._ttl_seconds
        ]
        for tid in expired:
            self._tasks.pop(tid, None)
        if len(self._tasks) > self._max_tasks:
            ordered = sorted(self._tasks.items(), key=lambda item: item[1].get("updated_at", 0))
            for tid, _task in ordered[: len(self._tasks) - self._max_tasks]:
                self._tasks.pop(tid, None)

    def create_task(
        self,
        task_type: str,
        description: str,
        *,
        workspace_owner: Optional[str] = None,
    ) -> str:
        """Create a task, optionally scoped to one authenticated workspace.

        ``workspace_owner`` is deliberately server-generated (``user_id`` and
        selected case id). It is never accepted from a browser request.
        Keeping it with the transient task prevents the SSE status endpoints
        from becoming a cross-account progress feed.
        """
        task_id = secrets.token_hex(8)
        with self._lock:
            self._prune_locked()
            now = time.time()
            self._tasks[task_id] = {
                "id": task_id,
                "type": task_type,
                "description": description,
                "status": "running",
                "progress": 0,
                "message": "Starting...",
                "result": None,
                "error": None,
                "created_at": now,
                "updated_at": now,
                "workspace_owner": workspace_owner,
            }
        return task_id

    def update_progress(self, task_id: str, progress: int, message: str = ""):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["progress"] = progress
                if message:
                    self._tasks[task_id]["message"] = message
                self._tasks[task_id]["updated_at"] = time.time()

    def complete_task(self, task_id: str, result: Any = None):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "completed"
                self._tasks[task_id]["progress"] = 100
                self._tasks[task_id]["result"] = result
                self._tasks[task_id]["updated_at"] = time.time()

    def fail_task(self, task_id: str, error: str):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "failed"
                self._tasks[task_id]["error"] = error
                self._tasks[task_id]["updated_at"] = time.time()

    @staticmethod
    def _public_task(task: Dict[str, Any]) -> Dict[str, Any]:
        public = dict(task)
        public.pop("workspace_owner", None)
        return public

    def get_task(self, task_id: str, *, workspace_owner: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._prune_locked()
            task = self._tasks.get(task_id)
            if not task or (workspace_owner is not None and task.get("workspace_owner") != workspace_owner):
                return None
            return self._public_task(task)

    def get_all_tasks(self, *, workspace_owner: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            self._prune_locked()
            return {
                tid: self._public_task(task)
                for tid, task in self._tasks.items()
                if workspace_owner is None or task.get("workspace_owner") == workspace_owner
            }


task_manager = TaskManager()

_UI_BRIDGE_LOCK = threading.Lock()
_UI_BRIDGE_MAX_EVENTS = int(os.environ.get("BRACHYBOT_UI_BRIDGE_MAX_EVENTS", "500"))
_UI_BRIDGE: Dict[str, Dict[str, Any]] = {}


def _ui_session_id(session_id: Optional[str] = None) -> str:
    sid = str(session_id or "web").strip()
    return sid or "web"


def _ui_bucket(session_id: Optional[str] = None) -> Dict[str, Any]:
    sid = _ui_session_id(session_id)
    with _UI_BRIDGE_LOCK:
        return _UI_BRIDGE.setdefault(sid, {
            "state": {},
            "events": [],
            "training": {
                "active": False,
                "goal": "",
                "started_at": None,
                "stopped_at": None,
                "events": [],
                "feedback": [],
            },
        })


def _drop_ui_bucket(session_id: Optional[str]) -> None:
    """Remove UI/training state when the owning agent session is deleted."""
    sid = _ui_session_id(session_id)
    with _UI_BRIDGE_LOCK:
        _UI_BRIDGE.pop(sid, None)


def _append_ui_event(
    session_id: Optional[str],
    event: Dict[str, Any],
    *,
    include_in_training: bool = True,
) -> Dict[str, Any]:
    bucket = _ui_bucket(session_id)
    item = dict(event or {})
    item.setdefault("type", "ui.event")
    item.setdefault("label", "")
    item.setdefault("detail", {})
    item["ts"] = time.time()
    with _UI_BRIDGE_LOCK:
        events = bucket.setdefault("events", [])
        events.append(item)
        if len(events) > _UI_BRIDGE_MAX_EVENTS:
            del events[: len(events) - _UI_BRIDGE_MAX_EVENTS]
        training = bucket.setdefault("training", {})
        if training.get("active") and include_in_training:
            training.setdefault("events", []).append(item)
    return item


def _extract_metric_value(metrics: Dict[str, Any], *names: str) -> Optional[float]:
    if not isinstance(metrics, dict):
        return None
    for name in names:
        value = metrics.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _metric_as_fraction(
    value: Optional[float],
    *,
    units: Optional[str] = None,
) -> Optional[float]:
    """Normalize a volume metric while honoring an explicit unit contract.

    Current automatic and manual CTV metrics are stored as fractions. Older
    persisted payloads may omit the unit and can still use the legacy value
    heuristic; new writers should always set ``volume_metric_units``.
    """
    if value is None:
        return None
    value = float(value)
    normalized_units = str(units or "").strip().lower()
    if normalized_units in {"fraction", "ratio", "0-1"}:
        return value
    if normalized_units in {"percent", "percentage", "0-100"}:
        return value / 100.0
    return value / 100.0 if value > 1.0 else value


def _volume_metric_as_fraction(metrics: Dict[str, Any], name: str) -> Optional[float]:
    """Read a CTV volume metric using its persisted unit declaration."""
    return _metric_as_fraction(
        _extract_metric_value(metrics, name),
        units=metrics.get("volume_metric_units") if isinstance(metrics, dict) else None,
    )


def _volume_metric_as_percent(value: Any, *, units: Optional[str] = None) -> Optional[float]:
    """Normalize a volume metric to a physically valid 0-100 percentage.

    OAR metrics historically came from both fraction and percent writers.
    Report generation is a compatibility boundary, so it must normalize old
    records and clamp impossible values instead of multiplying blindly.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    normalized_units = str(units or "").strip().lower()
    if normalized_units in {"fraction", "ratio", "0-1"}:
        if not 0.0 <= number <= 1.0:
            return None
        percent = number * 100.0
    elif normalized_units in {"percent", "percentage", "0-100"}:
        if not 0.0 <= number <= 100.0:
            return None
        percent = number
    else:
        # Only the unlabelled legacy boundary may use the fraction heuristic.
        # A value above 100 is not recoverable: repeatedly dividing it would
        # silently turn corrupt clinical data into a plausible percentage.
        if 0.0 <= number <= 1.0:
            percent = number * 100.0
        elif 0.0 <= number <= 100.0:
            percent = number
        else:
            return None
    return float(percent)


def _segment_segment_distance(
    first_start: list,
    first_end: list,
    second_start: list,
    second_end: list,
) -> float:
    """Return the shortest Euclidean distance between two finite 3D segments."""
    u = [first_end[i] - first_start[i] for i in range(3)]
    v = [second_end[i] - second_start[i] for i in range(3)]
    w = [first_start[i] - second_start[i] for i in range(3)]
    a = sum(value * value for value in u)
    b = sum(u[i] * v[i] for i in range(3))
    c = sum(value * value for value in v)
    d = sum(u[i] * w[i] for i in range(3))
    e = sum(v[i] * w[i] for i in range(3))
    denominator = a * c - b * b
    small = 1e-9
    s_num, s_den = denominator, denominator
    t_num, t_den = denominator, denominator
    if denominator < small:
        s_num, s_den = 0.0, 1.0
        t_num, t_den = e, c
    else:
        s_num = b * e - c * d
        t_num = a * e - b * d
        if s_num < 0.0:
            s_num = 0.0
            t_num, t_den = e, c
        elif s_num > s_den:
            s_num = s_den
            t_num, t_den = e + b, c
    if t_num < 0.0:
        t_num = 0.0
        if -d < 0.0:
            s_num = 0.0
        elif -d > a:
            s_num = s_den
        else:
            s_num, s_den = -d, a
    elif t_num > t_den:
        t_num = t_den
        if -d + b < 0.0:
            s_num = 0.0
        elif -d + b > a:
            s_num = s_den
        else:
            s_num, s_den = -d + b, a
    sc = 0.0 if abs(s_num) < small else s_num / max(s_den, small)
    tc = 0.0 if abs(t_num) < small else t_num / max(t_den, small)
    delta = [w[i] + sc * u[i] - tc * v[i] for i in range(3)]
    return math.sqrt(sum(value * value for value in delta))


def _latest_plan_snapshot(agent) -> Dict[str, Any]:
    if agent is None or not hasattr(agent, "memory"):
        return {}
    metrics = agent.memory.retrieve("dose_metrics") or agent.memory.retrieve("metrics") or {}
    if isinstance(metrics, dict) and "metrics" in metrics and isinstance(metrics["metrics"], dict):
        metrics = metrics["metrics"]
    total_seeds = agent.memory.retrieve("total_seeds") or 0
    num_trajectories = agent.memory.retrieve("num_trajectories") or 0

    def _points(value: Any) -> list:
        if isinstance(value, dict):
            value = value.get("position") or value.get("pos") or value.get("point")
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return []
        try:
            return [float(value[0]), float(value[1]), float(value[2])]
        except (TypeError, ValueError):
            return []

    # Prefer the explicit manual/baseline snapshot. It is the same world-mm
    # representation used by the viewer, so monitor QA never compares voxel
    # indices with physical coordinates by accident.
    seeds = list(agent.memory.retrieve("manual_seeds") or [])
    needles = list(agent.memory.retrieve("manual_needles") or [])
    if not seeds and not needles:
        baseline = agent.memory.retrieve("algorithm_plan_snapshot")
        if isinstance(baseline, dict):
            seeds = list(baseline.get("seeds") or [])
            needles = list(baseline.get("needles") or [])
    if not seeds:
        serialized = agent.memory.retrieve("seed_plan_serialized") or []
        for entry in serialized:
            if not isinstance(entry, dict):
                continue
            seeds.extend(entry.get("seeds") or [])

    # Keep stable seed IDs next to the physical coordinates.  The monitor uses
    # these IDs to focus a screenshot on a real pair of seeds; array indexes
    # alone are not safe once manual edits or a serialized plan reorder seeds.
    seed_entries = []
    for index, seed in enumerate(seeds):
        point = _points(seed)
        if point:
            seed_id = str(seed.get("id") or f"seed_{index}") if isinstance(seed, dict) else f"seed_{index}"
            direction = _points(seed.get("direction")) if isinstance(seed, dict) else []
            needle_id = str(
                seed.get("needle_id")
                or seed.get("trajectory_id")
                or ""
            ) if isinstance(seed, dict) else ""
            seed_entries.append({
                "id": seed_id,
                "position": point,
                "direction": direction,
                "needle_id": needle_id,
            })
    seed_ids = [entry["id"] for entry in seed_entries]
    seed_positions = [entry["position"] for entry in seed_entries]

    plan_config = agent.memory.retrieve("plan_config") or {}
    seed_info = plan_config.get("seed_info") if isinstance(plan_config, dict) else {}
    seed_info = seed_info if isinstance(seed_info, dict) else {}
    seed_length_mm = max(float(seed_info.get("length") or 4.5), 0.1)
    seed_radius_mm = max(float(seed_info.get("radius") or 0.4), 0.05)
    seed_clearance_mm = max(float(seed_info.get("minimum_clearance_mm") or 0.5), 0.0)

    needle_directions = {}
    for needle in needles:
        if not isinstance(needle, dict):
            continue
        needle_id = str(needle.get("id") or needle.get("needle_id") or "")
        points = needle.get("points") or []
        if not needle_id or not isinstance(points, (list, tuple)) or len(points) < 2:
            continue
        start, end = _points(points[0]), _points(points[-1])
        if not start or not end:
            continue
        vector = [end[axis] - start[axis] for axis in range(3)]
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude > 1e-9:
            needle_directions[needle_id] = [value / magnitude for value in vector]

    def _unit_direction(entry: Dict[str, Any]) -> list:
        direction = entry.get("direction") or needle_directions.get(entry.get("needle_id")) or []
        if len(direction) >= 3:
            magnitude = math.sqrt(sum(float(direction[axis]) ** 2 for axis in range(3)))
            if magnitude > 1e-9:
                return [float(direction[axis]) / magnitude for axis in range(3)]
        return [0.0, 0.0, 1.0]

    def _segment_endpoints(entry: Dict[str, Any]) -> tuple:
        center = entry["position"]
        direction = _unit_direction(entry)
        half = seed_length_mm / 2.0
        return (
            [center[axis] - direction[axis] * half for axis in range(3)],
            [center[axis] + direction[axis] * half for axis in range(3)],
        )

    def _segment_distance(left_entry: Dict[str, Any], right_entry: Dict[str, Any]) -> float:
        """Shortest distance between the physical center axes of two seeds."""
        p1, q1 = _segment_endpoints(left_entry)
        p2, q2 = _segment_endpoints(right_entry)
        u = [q1[i] - p1[i] for i in range(3)]
        v = [q2[i] - p2[i] for i in range(3)]
        w = [p1[i] - p2[i] for i in range(3)]
        a = sum(value * value for value in u)
        b = sum(u[i] * v[i] for i in range(3))
        c = sum(value * value for value in v)
        d = sum(u[i] * w[i] for i in range(3))
        e = sum(v[i] * w[i] for i in range(3))
        denominator = a * c - b * b
        small = 1e-9
        s_num, s_den = denominator, denominator
        t_num, t_den = denominator, denominator
        if denominator < small:
            s_num, s_den = 0.0, 1.0
            t_num, t_den = e, c
        else:
            s_num = b * e - c * d
            t_num = a * e - b * d
            if s_num < 0.0:
                s_num = 0.0
                t_num, t_den = e, c
            elif s_num > s_den:
                s_num = s_den
                t_num, t_den = e + b, c
        if t_num < 0.0:
            t_num = 0.0
            if -d < 0.0:
                s_num = 0.0
            elif -d > a:
                s_num = s_den
            else:
                s_num, s_den = -d, a
        elif t_num > t_den:
            t_num = t_den
            if -d + b < 0.0:
                s_num = 0.0
            elif -d + b > a:
                s_num = s_den
            else:
                s_num, s_den = -d + b, a
        sc = 0.0 if abs(s_num) < small else s_num / max(s_den, small)
        tc = 0.0 if abs(t_num) < small else t_num / max(t_den, small)
        delta = [w[i] + sc * u[i] - tc * v[i] for i in range(3)]
        return math.sqrt(sum(value * value for value in delta))

    close_pairs = []
    interference_threshold_mm = 2.0 * seed_radius_mm + seed_clearance_mm
    for left in range(len(seed_entries)):
        for right in range(left + 1, len(seed_entries)):
            axis_distance = _segment_distance(seed_entries[left], seed_entries[right])
            center_distance = math.sqrt(sum(
                (seed_positions[left][axis] - seed_positions[right][axis]) ** 2
                for axis in range(3)
            ))
            if axis_distance < interference_threshold_mm:
                close_pairs.append({
                    "first": left,
                    "second": right,
                    "first_id": seed_ids[left],
                    "second_id": seed_ids[right],
                    "first_needle_id": seed_entries[left]["needle_id"],
                    "second_needle_id": seed_entries[right]["needle_id"],
                    "center_distance_mm": round(center_distance, 3),
                    "axis_distance_mm": round(axis_distance, 3),
                    "surface_clearance_mm": round(axis_distance - (2.0 * seed_radius_mm), 3),
                    "risk": "overlap" if axis_distance < (2.0 * seed_radius_mm) else "too_close",
                })
    if seed_positions:
        seed_interference = {
            "status": "attention" if close_pairs else "clear",
            "threshold_mm": interference_threshold_mm,
            "seed_length_mm": seed_length_mm,
            "seed_radius_mm": seed_radius_mm,
            "minimum_clearance_mm": seed_clearance_mm,
            "seed_count": len(seed_positions),
            "close_pairs": close_pairs[:50],
        }
    else:
        seed_interference = {
            "status": "unavailable",
            "threshold_mm": interference_threshold_mm,
            "seed_length_mm": seed_length_mm,
            "seed_radius_mm": seed_radius_mm,
            "minimum_clearance_mm": seed_clearance_mm,
            "seed_count": 0,
            "close_pairs": [],
        }

    needle_entries = []
    for index, needle in enumerate(needles):
        if not isinstance(needle, dict):
            continue
        points = needle.get("points") or []
        if not isinstance(points, (list, tuple)) or len(points) < 2:
            continue
        start, end = _points(points[0]), _points(points[-1])
        if start and end:
            needle_entries.append({
                "id": str(needle.get("id") or needle.get("needle_id") or f"needle_{index}"),
                "start": start,
                "end": end,
            })
    needle_diameter_mm = max(float(plan_config.get("needle_diameter_mm") or 1.2), 0.1)
    needle_clearance_mm = max(float(plan_config.get("needle_clearance_mm") or 1.0), 0.0)
    needle_threshold_mm = needle_diameter_mm + needle_clearance_mm
    needle_close_pairs = []
    for left in range(len(needle_entries)):
        for right in range(left + 1, len(needle_entries)):
            distance = _segment_segment_distance(
                needle_entries[left]["start"],
                needle_entries[left]["end"],
                needle_entries[right]["start"],
                needle_entries[right]["end"],
            )
            if distance < needle_threshold_mm:
                needle_close_pairs.append({
                    "first_id": needle_entries[left]["id"],
                    "second_id": needle_entries[right]["id"],
                    "distance_mm": round(distance, 3),
                    "minimum_distance_mm": round(needle_threshold_mm, 3),
                    "risk": "intersecting" if distance < needle_diameter_mm else "too_close",
                })

    obstacle_hits = []
    if needle_entries:
        try:
            from tool_factory.seed_plan.planning_pipeline import (
                _merge_embedded_hard_obstacles,
                _resolve_data_tree_obstacle_labels,
                _world_segment_hits_obstacle,
            )

            ct_image = agent.memory.retrieve("ct_image")
            if ct_image is None:
                ct_image = agent.memory.retrieve("image")
            ctv_mask = agent.memory.retrieve("ctv_mask")
            if ctv_mask is None:
                ctv_mask = agent.memory.retrieve("ctv_label_data")
            oar_mask = agent.memory.retrieve("oar_mask")
            if oar_mask is None:
                oar_mask = agent.memory.retrieve("oar_label_data")
            if ct_image is not None and ctv_mask is not None:
                merged_oar, embedded_labels = _merge_embedded_hard_obstacles(oar_mask, agent)
                obstacle_labels, _ = _resolve_data_tree_obstacle_labels(agent)
                obstacle_labels.update(embedded_labels)
                for needle in needle_entries:
                    if _world_segment_hits_obstacle(
                        [needle["start"], needle["end"]],
                        ct_image,
                        ctv_mask,
                        merged_oar,
                        obstacle_labels,
                    ):
                        obstacle_hits.append(needle["id"])
        except (ImportError, OSError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("Monitor could not validate needle obstacles: %s", exc)

    artifact_status = agent.memory.retrieve("manual_artifact_status") or {}
    guide = agent.memory.retrieve("surgical_guide") or {}
    return {
        "metrics": metrics if isinstance(metrics, dict) else {},
        "total_seeds": int(total_seeds or 0),
        "num_trajectories": int(num_trajectories or 0),
        "has_dose": agent.memory.retrieve("dose_distribution") is not None
            or agent.memory.retrieve("dose_distribution_gy") is not None,
        "manual_preview": bool(agent.memory.retrieve("manual_planning_preview")),
        "seed_ids": seed_ids,
        "seed_positions": seed_positions,
        "seed_interference": seed_interference,
        "needle_geometry": {
            "needle_count": len(needle_entries),
            "diameter_mm": needle_diameter_mm,
            "minimum_distance_mm": needle_threshold_mm,
            "close_pairs": needle_close_pairs[:50],
            "obstacle_hits": obstacle_hits,
        },
        "artifact_status": artifact_status if isinstance(artifact_status, dict) else {},
        "surgical_guide": {
            "available": bool(guide),
            "status": (
                guide.get("status") if isinstance(guide, dict) else None
            ) or (
                artifact_status.get("surgical_guide")
                if isinstance(artifact_status, dict)
                else None
            ) or "not_generated",
            "planning_version": (
                guide.get("planning_version") if isinstance(guide, dict) else None
            ),
        },
    }


def _source_backed_target_context(agent) -> Dict[str, Any]:
    """Resolve case criteria without falling back to a generic disease site."""
    if agent is None or not hasattr(agent, "memory"):
        return {}
    memory = agent.memory
    tumor_type = str(
        memory.retrieve("tumor_type_used")
        or memory.retrieve("tumor_type")
        or memory.retrieve("cancer_type")
        or memory.retrieve("organ")
        or ""
    ).strip()
    if not tumor_type:
        return {}
    try:
        from tool_factory.dose_eval.comprehensive_dose_evaluation import (
            ComprehensiveDoseEvaluationTool,
        )
        from tool_factory.plan_quality.clinical_standards import get_target_standard

        site = ComprehensiveDoseEvaluationTool._site_from_tumor_type(tumor_type)
        if site == "default":
            return {}
        criteria = get_target_standard(site)
        if not criteria:
            return {}
        return {"tumor_type": tumor_type, "site": site, "criteria": criteria}
    except (ImportError, OSError, ValueError, TypeError) as exc:
        logger.warning("Could not resolve source-backed target criteria: %s", exc)
        return {}


def _build_plan_advice(agent, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Create deterministic planning advice from current metrics and UI events."""
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    events = list((_ui_bucket(session_id).get("events") or [])[-80:])
    advice: list = []
    issues: list = []
    strengths: list = []

    rx_gy = None
    prescribed = _extract_metric_value(metrics, "prescribed_dose", "prescription")
    if prescribed and prescribed < 10:
        rx_gy = prescribed * DOSE_MODEL_SCALE_GY
    elif prescribed:
        rx_gy = prescribed

    v100 = _volume_metric_as_fraction(metrics, "v100")
    d90 = _extract_metric_value(metrics, "d90")
    v150 = _volume_metric_as_fraction(metrics, "v150")
    v200 = _volume_metric_as_fraction(metrics, "v200")
    plan_score = _extract_metric_value(metrics, "plan_score", "score")

    if v100 is not None:
        strengths.append(
            f"CTV V100 is {v100 * 100:.1f}%; compare it with the applicable site-specific guidance or confirmed case protocol target."
        )
        advice.append("Inspect cold CTV regions against the intended prescription coverage, then recompute dose and DVH after edits.")
    else:
        advice.append("Run dose evaluation to make V100/D90 advice available.")

    if d90 is not None:
        rx_text = f"; current dose reference is {rx_gy:.0f} Gy" if rx_gy is not None else ""
        strengths.append(f"CTV D90 is {d90:.1f} Gy{rx_text}.")
        advice.append("Compare D90 with the source-backed prescription convention for this tumor site before labeling coverage adequate or inadequate.")

    if v200 is not None:
        issues.append(f"CTV V200 is {v200 * 100:.1f}%; inspect the corresponding hot-spot location in 2D/3D.")
        advice.append("If the hot spot is clinically undesirable for this site, spread central seeds along the needle track or reduce local seed density.")
    if v150 is not None:
        strengths.append(f"CTV V150 is {v150 * 100:.1f}%; interpret uniformity with the current site-specific criteria.")

    oar_metrics = metrics.get("oar_metrics") if isinstance(metrics, dict) else None
    if isinstance(oar_metrics, dict):
        high_oars = []
        for name, m in oar_metrics.items():
            if not isinstance(m, dict):
                continue
            dmax = _extract_metric_value(m, "dmax", "max_dose", "Dmax") or 0.0
            d2cc = _extract_metric_value(m, "d2cc", "D2cc") or 0.0
            if dmax > 0 or d2cc > 0:
                high_oars.append((str(name), dmax, d2cc))
        if high_oars:
            top = sorted(high_oars, key=lambda x: max(x[1], x[2]), reverse=True)[:5]
            strengths.append("Top OAR doses: " + ", ".join(f"{n} Dmax={dm:.1f} Gy D2cc={d2:.1f} Gy" for n, dm, d2 in top))
            advice.append("Compare OAR doses against applicable site-specific guidance or the confirmed case protocol before classifying safety.")

    if snapshot.get("total_seeds", 0) == 0:
        advice.append("No seeds are present. Add a needle and place seeds through the CTV before dose evaluation.")
    elif v100 is not None:
        advice.append("Review whether the current seed count and spacing are sufficient for the requested coverage after applying source-backed criteria.")

    recent_manual = [e for e in events if str(e.get("type", "")).startswith("manual.")]
    if recent_manual:
        advice.append("Recent manual edits were detected; recompute dose after each seed or needle adjustment to keep DVH current.")

    interference = snapshot.get("seed_interference") or {}
    if interference.get("status") == "attention":
        pairs = list(interference.get("close_pairs") or [])
        overlap_count = sum(1 for pair in pairs if pair.get("risk") == "overlap")
        issues.append(
            f"{len(pairs)} seed pair(s) violate the physical spacing rule "
            f"(seed {float(interference.get('seed_length_mm') or 4.5):.1f} mm x "
            f"{float(interference.get('seed_radius_mm') or 0.4) * 2.0:.1f} mm; "
            f"minimum surface clearance "
            f"{float(interference.get('minimum_clearance_mm') or 0.5):.1f} mm). "
            f"{overlap_count} pair(s) geometrically overlap."
        )
        for pair in pairs[:8]:
            issues.append(
                f"{pair.get('first_id')} ({pair.get('first_needle_id') or 'unassigned'}) and "
                f"{pair.get('second_id')} ({pair.get('second_needle_id') or 'unassigned'}): "
                f"center distance {float(pair.get('center_distance_mm') or 0.0):.2f} mm, "
                f"surface clearance {float(pair.get('surface_clearance_mm') or 0.0):.2f} mm "
                f"[{pair.get('risk') or 'too_close'}]."
            )
        advice.append(
            "Inspect the highlighted seed pairs in the 3D viewer, correct their "
            "axial spacing, and recompute dose before final review."
        )
    elif interference.get("status") == "clear":
        strengths.append(
            f"No seed pair violates the {float(interference.get('minimum_clearance_mm') or 0.5):.1f} mm "
            "minimum physical surface-clearance rule in the current preview."
        )
    elif snapshot.get("total_seeds", 0) > 1:
        advice.append("Seed geometry was not available for the monitor; verify seed spacing directly in the 3D viewer.")

    needle_geometry = snapshot.get("needle_geometry") or {}
    obstacle_hits = list(needle_geometry.get("obstacle_hits") or [])
    if obstacle_hits:
        issues.append(
            "Needles intersecting current Data Tree non-traversable structures: "
            + ", ".join(obstacle_hits[:20])
            + "."
        )
        advice.append(
            "Move or remove every obstacle-intersecting needle before dose review "
            "or Surgical Guide generation."
        )
    needle_pairs = list(needle_geometry.get("close_pairs") or [])
    if needle_pairs:
        for pair in needle_pairs[:8]:
            issues.append(
                f"{pair.get('first_id')} and {pair.get('second_id')} are "
                f"{float(pair.get('distance_mm') or 0.0):.2f} mm apart "
                f"(minimum {float(pair.get('minimum_distance_mm') or 0.0):.2f} mm; "
                f"{pair.get('risk') or 'too_close'})."
            )
        advice.append(
            "Review the highlighted needle pairs for physical collision and "
            "guide-sleeve manufacturability."
        )

    artifact_status = snapshot.get("artifact_status") or {}
    stale_labels = [
        key for key, value in artifact_status.items()
        if str(value or "").lower() in {"stale", "expired", "outdated"}
    ]
    if stale_labels:
        issues.append("Outdated dependent results: " + ", ".join(sorted(stale_labels)) + ".")
        advice.append(
            "Recompute the outdated dose/DVH and regenerate the Surgical Guide "
            "before finalizing the plan."
        )
    guide = snapshot.get("surgical_guide") or {}
    if snapshot.get("num_trajectories", 0) > 0 and not guide.get("available"):
        issues.append("No Surgical Guide has been generated for the current needle plan.")
    elif str(guide.get("status") or "").lower() in {"stale", "expired", "outdated"}:
        issues.append("The Surgical Guide does not match the current planning version.")

    if plan_score is not None:
        strengths.append(f"Plan score is {plan_score:.0f}/100; use it as an advisory ranking signal, not approval.")

    if not strengths and not issues and not advice:
        advice.append("Load CT, segment CTV/OAR, and run planning or manual AI dose recomputation to generate actionable advice.")

    return {
        "success": True,
        "snapshot": snapshot,
        "strengths": strengths,
        "issues": issues,
        "advice": advice,
        "event_count": len(events),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def _monitor_language(value: Any) -> str:
    """Normalize the UI language used by deterministic monitor messages."""
    return "zh" if str(value or "").strip().lower().startswith(("zh", "cn")) else "en"


def _monitor_event_detail(event: Dict[str, Any]) -> Dict[str, Any]:
    detail = event.get("detail") if isinstance(event, dict) else None
    return detail if isinstance(detail, dict) else {}


def _monitor_event_status(event: Dict[str, Any]) -> str:
    detail = _monitor_event_detail(event)
    raw = str(detail.get("status") or "").strip().lower()
    label = str(event.get("label") or "").strip().lower()
    text = f"{raw} {label}"
    if any(token in text for token in ("error", "failed", "failure")):
        return "error"
    if any(token in text for token in ("completed", "complete", "finished", "done")):
        return "done"
    if any(token in text for token in ("started", "running", "pending", "queued")):
        return "running"
    return "event"


def _monitor_step_key(event: Dict[str, Any]) -> str:
    """Resolve a stable stage key from manual-planning event variants."""
    detail = _monitor_event_detail(event)
    raw = str(detail.get("step") or detail.get("kind") or "").strip().lower()
    label = str(event.get("label") or "").strip().lower()
    text = f"{raw} {label}".replace("-", "_").replace(" ", "_")
    aliases = (
        ("ctv_segmentation", "ctv"),
        ("oar_segmentation", "oar"),
        ("trajectory_init", "trajectory_init"),
        ("trajectory_initialization", "trajectory_init"),
        ("trajectory_refine", "trajectory_refine"),
        ("trajectory_refinement", "trajectory_refine"),
        ("seed_planning", "seed_planning"),
        ("seed_position", "seed_planning"),
        ("dose_calc", "dose_calc"),
        ("dose_calculation", "dose_calc"),
        ("dose_eval", "dose_eval"),
        ("dose_evaluation", "dose_eval"),
        ("full_pipeline", "full"),
        ("full", "full"),
    )
    for needle, key in aliases:
        if needle in text:
            return key
    if "ctv" in text:
        return "ctv"
    if "oar" in text:
        return "oar"
    if "trajectory" in text or "needle" in text:
        return "trajectory_refine"
    if "seed" in text:
        return "seed_planning"
    if "dose" in text:
        return "dose_eval"
    return raw or "unknown"


def _monitor_step_label(key: str, language: str = "en") -> str:
    labels = {
        "ctv": ("CTV 分割", "CTV segmentation"),
        "oar": ("OAR 分割", "OAR segmentation"),
        "trajectory_init": ("轨迹初始化", "Trajectory initialization"),
        "trajectory_refine": ("轨迹优化", "Trajectory refinement"),
        "seed_planning": ("粒子布源", "Seed planning"),
        "dose_calc": ("剂量计算", "Dose calculation"),
        "dose_eval": ("剂量评估", "Dose evaluation"),
        "full": ("完整规划流程", "Full planning pipeline"),
    }
    pair = labels.get(key, (key or "步骤", key or "step"))
    return pair[0] if language == "zh" else pair[1]


def _localize_monitor_text(text: Any, language: str = "en") -> str:
    """Translate deterministic monitor prose without translating clinical names."""
    raw = str(text or "")
    if language != "zh" or not raw:
        return raw
    exact = {
        "Run dose evaluation to make V100/D90 advice available.": "请先执行剂量评估，以生成 V100/D90 建议。",
        "Inspect cold CTV regions against the intended prescription coverage, then recompute dose and DVH after edits.": "请检查 CTV 的低剂量区域，并在编辑后重新计算剂量和 DVH。",
        "Compare D90 with the source-backed prescription convention for this tumor site before labeling coverage adequate or inadequate.": "在判断覆盖是否充分前，请将 D90 与该部位有来源依据的处方规范进行比较。",
        "If the hot spot is clinically undesirable for this site, spread central seeds along the needle track or reduce local seed density.": "如果该部位不适合当前热点分布，请沿针道分散中心粒子或降低局部粒子密度。",
        "Compare OAR doses against applicable site-specific guidance or the confirmed case protocol before classifying safety.": "在判断安全性前，请依据适用的部位特异性指南或已确认的病例方案比较 OAR 剂量。",
        "Review whether the current seed count and spacing are sufficient for the requested coverage after applying source-backed criteria.": "依据有来源依据的标准，检查当前粒子数量和间距是否足以达到目标覆盖。",
        "Recent manual edits were detected; recompute dose after each seed or needle adjustment to keep DVH current.": "检测到近期手动编辑；每次调整粒子或针道后请重新计算剂量，以保持 DVH 最新。",
        "No seeds are present. Add a needle and place seeds through the CTV before dose evaluation.": "当前没有粒子。请先添加针道并在 CTV 内布置粒子，再进行剂量评估。",
        "Dose preview updated. Open Analysis to inspect DVH and OAR dose.": "剂量预览已更新。请打开分析面板检查 DVH 和 OAR 剂量。",
        "Seed geometry was not available for the monitor; verify seed spacing directly in the 3D viewer.": "监测器未获得粒子几何信息；请直接在 3D viewer 中核对粒子间距。",
        "Regenerate the Surgical Guide from the current needle geometry before export or clinical review.": "请基于当前针道几何重新生成手术导板，再进行导出或临床审核。",
        "Recompute dose and DVH, then refresh the report before final review.": "请重新计算剂量和 DVH，并刷新报告后再进行最终审核。",
    }
    if raw in exact:
        return exact[raw]
    match = re.fullmatch(r"CTV V100 is ([0-9.]+)%; compare it with the applicable site-specific guidance or confirmed case protocol target\.", raw)
    if match:
        return f"CTV V100 为 {match.group(1)}%；请与适用的部位特异性指南或已确认的病例方案目标比较。"
    match = re.fullmatch(r"CTV D90 is ([0-9.]+) Gy(?:; current dose reference is ([0-9.]+) Gy)?\.", raw)
    if match:
        suffix = f"；当前剂量参考为 {match.group(2)} Gy" if match.group(2) else ""
        return f"CTV D90 为 {match.group(1)} Gy{suffix}。"
    match = re.fullmatch(r"CTV V200 is ([0-9.]+)%; inspect the corresponding hot-spot location in 2D/3D\.", raw)
    if match:
        return f"CTV V200 为 {match.group(1)}%；请在 2D/3D viewer 中检查对应的热点位置。"
    match = re.fullmatch(r"CTV V150 is ([0-9.]+)%; interpret uniformity with the current site-specific criteria\.", raw)
    if match:
        return f"CTV V150 为 {match.group(1)}%；请依据当前部位特异性标准判读均匀性。"
    match = re.fullmatch(r"Dose preview updated: V100=([0-9.]+)%, D90=([0-9.]+) Gy\. Review hot spots and OAR dose before adding seeds\.", raw)
    if match:
        return f"剂量预览已更新：V100={match.group(1)}%，D90={match.group(2)} Gy。添加粒子前请检查热点和 OAR 剂量。"
    match = re.fullmatch(r"Seed edit recorded\. ([0-9]+) close seed pair\(s\) are below ([0-9.]+) mm; inspect them before continuing\.", raw)
    if match:
        return f"已记录粒子编辑：有 {match.group(1)} 对粒子间距小于 {match.group(2)} mm；继续前请检查这些粒子。"
    match = re.fullmatch(r"Seed edit recorded\. Current V100 is ([0-9.]+)%; inspect cold CTV regions after recompute\.", raw)
    if match:
        return f"已记录粒子编辑：当前 V100 为 {match.group(1)}%；重新计算后请检查 CTV 低剂量区域。"
    if raw.startswith("Top OAR doses: "):
        return "OAR 最高剂量结构：" + raw[len("Top OAR doses: "):]
    if raw.startswith("No seed-center pair is closer than "):
        return "当前预览中没有粒子中心间距小于 " + raw[len("No seed-center pair is closer than "):].replace(" in the current preview.", "。")
    if raw.startswith("Needle edit recorded."):
        return "已记录针道编辑。请确认针道经过安全组织，并与不可穿刺 OAR 保持距离。"
    match = re.fullmatch(
        r"Needles intersecting current Data Tree non-traversable structures: (.+)\.",
        raw,
    )
    if match:
        return f"针道 {match.group(1)} 与当前不可穿刺结构相交。"
    match = re.fullmatch(
        r"(.+) and (.+) are ([0-9.]+) mm apart \(minimum ([0-9.]+) mm; (.+)\)\.",
        raw,
    )
    if match:
        return (
            f"针道 {match.group(1)} 与 {match.group(2)} 的最短距离为 {match.group(3)} mm；"
            f"当前配置的最小距离为 {match.group(4)} mm。"
        )
    match = re.fullmatch(
        r"(.+) \((.*)\) and (.+) \((.*)\): center distance ([0-9.]+) mm, "
        r"surface clearance ([0-9.-]+) mm \[(.+)\]\.",
        raw,
    )
    if match:
        return (
            f"粒子 {match.group(1)}（{match.group(2)}）与 {match.group(3)}（{match.group(4)}）"
            f"的中心距离为 {match.group(5)} mm，表面间隙为 {match.group(6)} mm"
            f"（{match.group(7)}）。"
        )
    match = re.fullmatch(r"Outdated dependent results: (.+)\.", raw)
    if match:
        return f"手动几何编辑后，规划产物 {match.group(1)} 已过期。"
    if raw == "No Surgical Guide has been generated for the current needle plan.":
        return "当前针道规划尚未生成手术导板。"
    if raw == "The Surgical Guide does not match the current planning version.":
        return "手术导板与当前针道规划不一致，已标记为过期。"
    if raw.startswith("Move or remove every obstacle-intersecting needle"):
        return "请在剂量审核或生成手术导板前，移动或删除所有与不可穿刺结构相交的针道。"
    if raw.startswith("Review the highlighted needle pairs"):
        return "请检查高亮的针道组合是否发生物理碰撞，并确认导向套筒可制造。"
    if raw.startswith("Recompute the outdated dose/DVH"):
        return "请重新计算已过期的剂量和 DVH，并重新生成手术导板后再完成规划。"
    if raw.startswith("Inspect the highlighted seed pairs"):
        return "请在 3D viewer 中检查高亮粒子组合，修正轴向间距并重新计算剂量。"
    if raw.startswith("Seed edit recorded."):
        return "已记录粒子编辑。请重新计算剂量并核对 DVH，再放置下一枚粒子。"
    match = re.fullmatch(
        r"Plan score is ([0-9.]+)/100; use it as an advisory ranking signal, not approval\."
        , raw,
    )
    if match:
        return f"规划评分为 {match.group(1)}/100；该分数仅用于辅助排序，不代表临床批准。"
    if raw.startswith("Plan score is "):
        return raw.replace("; use it as an advisory ranking signal, not approval.", "；该分数仅用于辅助排序，不代表临床批准。")
    return raw


def _localize_plan_advice(advice: Dict[str, Any], language: str = "en") -> Dict[str, Any]:
    result = dict(advice or {})
    for key in ("strengths", "issues", "advice"):
        values = result.get(key)
        if isinstance(values, list):
            result[key] = [_localize_monitor_text(value, language) for value in values]
    result["language"] = language
    return result


def _monitor_activity_label(key: str, language: str = "en") -> str:
    """Render event counters as user-facing labels, not internal event IDs."""
    labels = {
        "planning.step": ("规划步骤", "Planning steps"),
        "segmentation.step": ("分割步骤", "Segmentation steps"),
        "manual.needle.drag": ("手动针道拖拽", "Manual needle drags"),
        "manual.needle.position_only": ("手动针道位置调整", "Manual needle position updates"),
        "manual.seed.drag": ("手动粒子拖拽", "Manual seed drags"),
        "manual.seed.add": ("手动添加粒子", "Manual seed additions"),
        "manual.seed.delete": ("手动删除粒子", "Manual seed deletions"),
        "manual.dose": ("手动剂量重算", "Manual dose updates"),
        "ui.panel": ("面板操作", "Panel interactions"),
        "ui.click": ("点击操作", "Click interactions"),
        "ui.change": ("控件修改", "Control changes"),
        "ui.slider": ("滑块调整", "Slider changes"),
        "training.start": ("监测启动", "Monitor starts"),
        "training.stop": ("监测结束", "Monitor stops"),
    }
    pair = labels.get(key)
    if pair:
        return pair[0] if language == "zh" else pair[1]
    return key.replace(".", " ").strip().title() or ("其他事件" if language == "zh" else "Other events")


def _format_training_summary(events: list, counts: Dict[str, int], advice: Dict[str, Any], language: str = "en") -> str:
    """Return a readable, localized monitor report instead of a raw paragraph."""
    if language == "zh":
        lines = ["## 规划监测总结", f"本次监测记录了 {len(events)} 个 UI/规划事件。"]
        section_labels = ("活动概览", "当前优势", "需要关注", "建议")
    else:
        lines = ["## Planning monitoring summary", f"Recorded {len(events)} UI/planning events."]
        section_labels = ("Activity", "Strengths", "Issues", "Recommendations")
    if counts:
        lines.extend(["", f"### {section_labels[0]}"])
        for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]:
            lines.append(f"- {_monitor_activity_label(key, language)}: {value}")
    localized = _localize_plan_advice(advice, language)
    for heading, key in zip(section_labels[1:], ("strengths", "issues", "advice")):
        values = localized.get(key) or []
        if values:
            lines.extend(["", f"### {heading}"])
            lines.extend(f"- {value}" for value in values)
    return "\n".join(lines)


def _readiness_item(key: str, label: str, passed: bool, detail: str, action: str = "") -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "passed": bool(passed),
        "detail": detail,
        "action": action,
    }


def _build_system_readiness(agent, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Build a deterministic product-readiness checklist for the current case."""
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    memory = getattr(agent, "memory", None)

    def mem(key: str, default=None):
        if memory is None:
            return default
        try:
            return memory.retrieve(key) if memory.retrieve(key) is not None else default
        except Exception:
            return default

    ct_loaded = mem("ct_image") is not None or bool(mem("ct_path"))
    ctv_ready = mem("ctv_array") is not None
    organ_names = mem("organ_names", {}) or {}
    oar_ready = mem("oar_array") is not None and (bool(mem("oar_is_full")) or len(organ_names) >= 5)
    planning_ready = snapshot.get("total_seeds", 0) > 0 and snapshot.get("num_trajectories", 0) > 0
    dose_ready = bool(snapshot.get("has_dose")) and bool(metrics)
    report_ready = bool(mem("report_form", {}) or metrics)
    kb_root = os.path.join(PROJECT_ROOT, "clinical_kb")
    kb_ready = os.path.exists(os.path.join(kb_root, "sources")) and os.path.exists(
        os.path.join(PROJECT_ROOT, "tool_factory", "clinical_kb", "data", "knowledge_base.json")
    )
    try:
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        screenshots_ready = os.access(SCREENSHOTS_DIR, os.W_OK)
    except Exception:
        screenshots_ready = False
    ui_events = list((_ui_bucket(session_id).get("events") or [])[-20:])

    checks = [
        _readiness_item("ct", "CT loaded", ct_loaded, "CT image/path available." if ct_loaded else "No CT image is loaded.", "Upload or load CT first."),
        _readiness_item("ctv", "CTV segmentation", ctv_ready, "CTV mask is available." if ctv_ready else "CTV mask is missing.", "Run CTV segmentation."),
        _readiness_item(
            "oar",
            "OAR segmentation",
            oar_ready,
            f"OAR map has {len(organ_names)} named structure(s)." if oar_ready else "Full OAR map is missing or incomplete.",
            "Run OAR segmentation before planning/DVH review.",
        ),
        _readiness_item(
            "planning",
            "Needles and seeds",
            planning_ready,
            f"{snapshot.get('num_trajectories', 0)} trajectory(ies), {snapshot.get('total_seeds', 0)} seed(s).",
            "Run planning_pipeline or manual seed placement.",
        ),
        _readiness_item("dose", "Dose and DVH", dose_ready, "Dose distribution and metrics are available." if dose_ready else "Dose/DVH metrics are not current.", "Recompute dose/DVH after planning edits."),
        _readiness_item("report", "Report data", report_ready, "Report can be auto-filled from current data." if report_ready else "Report data is not ready.", "Auto-fill report after dose evaluation."),
        _readiness_item("clinical_kb", "Clinical evidence", kb_ready, "Clinical evidence source index is present." if kb_ready else "Clinical evidence source index is missing.", "Repair the clinical evidence index before making source-backed clinical claims."),
        _readiness_item(
            "screenshots",
            "Screenshot feedback",
            screenshots_ready,
            "Screenshot directory is writable." if screenshots_ready else "Screenshot directory is not writable.",
            "Fix uploads/screenshots permissions before UI screenshot or training feedback.",
        ),
    ]

    execution_tools = {
        "code_executor_enabled": os.environ.get("BRACHYBOT_ENABLE_CODE_EXECUTOR", "").lower() in TRUE_VALUES,
        "shell_executor_enabled": os.environ.get("BRACHYBOT_ENABLE_SHELL_EXECUTOR", "").lower() in TRUE_VALUES,
        "shell_mode": "argv_allowlist_no_shell",
    }
    ready_for_review = all(item["passed"] for item in checks[:6])
    blockers = [item for item in checks if not item["passed"]]

    return {
        "success": True,
        "ready": ready_for_review,
        "items": checks,
        "ready_for_review": ready_for_review,
        "checks": checks,
        "blockers": blockers,
        "snapshot": snapshot,
        "recent_ui_events": ui_events,
        "execution_tools": execution_tools,
        "clinical_governance": {
            "clinical_kb_required": True,
            "constraint_policy": "Use applicable site-specific clinical guidance or confirmed case-protocol limits for target/OAR thresholds.",
            "threshold_policy": "Use applicable site-specific clinical guidance or confirmed case-protocol limits for target/OAR thresholds.",
            "local_templates": "Metric summaries only; no local-template clinical approval.",
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def _training_feedback_for_event(agent, session_id: Optional[str], event: Dict[str, Any]) -> Optional[str]:
    etype = str(event.get("type", ""))
    label = str(event.get("label", ""))
    detail = _monitor_event_detail(event)
    language = _monitor_language(event.get("language") or detail.get("language"))
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    d90 = _extract_metric_value(metrics, "d90")
    target_context = _source_backed_target_context(agent)
    target_criteria = target_context.get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(target_criteria, "v100_min"))

    if etype.startswith("manual.seed"):
        interference = snapshot.get("seed_interference") or {}
        if interference.get("status") == "attention":
            message = (
                f"Seed edit recorded. {len(interference.get('close_pairs') or [])} close seed pair(s) "
                f"are below {float(interference.get('threshold_mm') or 0.8):.1f} mm; inspect them before continuing."
            )
            return _localize_monitor_text(message, language)
        if v100 is not None and v100_min is not None and v100 < v100_min:
            return _localize_monitor_text(
                f"Seed edit recorded. Current V100 is {v100 * 100:.1f}%; inspect cold CTV regions after recompute.",
                language,
            )
        return _localize_monitor_text("Seed edit recorded. Recompute dose and verify DVH before placing the next seed.", language)
    if etype.startswith("manual.needle"):
        message = "Needle edit recorded. Check that the path traverses safe tissue and keeps distance from non-traversable OARs."
        return _localize_monitor_text(message, language)
    if etype in {"planning.step", "segmentation.step"}:
        key = _monitor_step_key(event)
        stage = _monitor_step_label(key, language)
        status = _monitor_event_status(event)
        if language == "zh":
            if status == "running":
                return f"{stage}正在执行；完成后我会检查 Data Tree 和 viewer 输出。"
            if status == "done":
                return f"{stage}已完成；请检查 Data Tree 和 viewer 输出，再继续下一步。"
            if status == "error":
                return f"{stage}执行失败；请查看错误详情并确认输入数据。"
            return f"{stage}事件已记录；请检查 Data Tree 输出。"
        if status == "running":
            return f"{stage} is running; I will verify the Data Tree and viewer output when it finishes."
        if status == "done":
            return f"{stage} completed; verify the Data Tree and viewer output before the next prerequisite step."
        if status == "error":
            return f"{stage} failed; inspect the error details and confirm the input data."
        return f"{stage} event recorded; verify its Data Tree output."
    if etype == "manual.dose":
        if v100 is not None and d90 is not None:
            return _localize_monitor_text(
                f"Dose preview updated: V100={v100 * 100:.1f}%, D90={d90:.1f} Gy. Review hot spots and OAR dose before adding seeds.",
                language,
            )
        return _localize_monitor_text("Dose preview updated. Open Analysis to inspect DVH and OAR dose.", language)
    return None


def _training_screenshot_for_event(agent, session_id: Optional[str], event: Dict[str, Any], feedback: Optional[str]) -> Optional[Dict[str, Any]]:
    """Suggest a screenshot target for high-value training checkpoints."""
    if not feedback:
        return None
    etype = str(event.get("type", ""))
    language = _monitor_language(event.get("language") or _monitor_event_detail(event).get("language"))
    status = _monitor_event_status(event)
    if etype in {"planning.step", "segmentation.step"} and status != "done":
        # A screenshot taken while a stage is merely starting is usually the
        # previous stage's image. Only completed checkpoints are evidence.
        return None
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    v200 = _volume_metric_as_fraction(metrics, "v200")
    target_criteria = _source_backed_target_context(agent).get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(target_criteria, "v100_min"))
    v200_max = _metric_as_fraction(_extract_metric_value(target_criteria, "v200_max"))

    def _focus_seed_ids() -> list[str]:
        ids = []
        for pair in (snapshot.get("seed_interference", {}) or {}).get("close_pairs", [])[:4]:
            for key in ("first_id", "second_id"):
                seed_id = str(pair.get(key) or "").strip()
                if seed_id and seed_id not in ids:
                    ids.append(seed_id)
        return ids

    if etype == "manual.dose":
        source_backed_concern = (
            v100 is not None and v100_min is not None and v100 < v100_min
        ) or (
            v200 is not None and v200_max is not None and v200 > v200_max
        )
        if source_backed_concern:
            result = {
                "target": "dose-overview",
                "question": "Training monitor snapshot: show current CT, masks, dose heatmap, seeds/needles, and DVH after manual dose recomputation.",
            }
            focus_seed_ids = _focus_seed_ids()
            if focus_seed_ids:
                result["focus_seed_ids"] = focus_seed_ids
            return result
        return {
            "target": "dvh",
            "question": "Training monitor snapshot: show the updated DVH after manual dose recomputation.",
        }

    if etype.startswith("segmentation."):
        return {
            "target": "viewer-3d",
            "question": (
                "监测截图：显示 3D viewer 和 Data Tree 中刚加载的 CTV/OAR 结构。"
                if language == "zh"
                else "Training monitor snapshot: show the newly loaded CTV/OAR structures in the 3D viewer and Data Tree."
            ),
        }

    if etype == "planning.step":
        key = _monitor_step_key(event)
        if key in {"trajectory_init", "trajectory_refine", "seed_planning"}:
            question = (
                f"监测截图：显示 {_monitor_step_label(key, 'zh')} 完成后的 3D viewer、针道/粒子和 Data Tree。"
                if language == "zh"
                else f"Training monitor snapshot: show the 3D viewer, needle/seed output, and Data Tree after {_monitor_step_label(key)}."
            )
            return {"target": "viewer-3d", "question": question}
        if key not in {"dose_calc", "dose_eval", "full"}:
            return None
        return {
            "target": "dose-overview",
            "question": (
                "监测截图：显示完成后的剂量分布和 DVH。"
                if language == "zh"
                else "Training monitor snapshot: show the completed plan dose distribution and DVH for review."
            ),
        }

    if etype.startswith("manual.needle"):
        return {
            "target": "viewer-3d",
            "question": (
                "监测截图：显示当前 3D 针道和邻近解剖结构。"
                if language == "zh"
                else "Training monitor snapshot: show the current 3D needle path and nearby anatomy."
            ),
        }

    if etype.startswith("manual.seed"):
        result = {
            "target": "viewer-3d",
            "question": (
                "监测截图：显示被编辑的粒子及其邻近粒子，以便检查间距。"
                if language == "zh"
                else "Training monitor snapshot: show the edited seed and nearby seeds so spacing can be checked."
            ),
        }
        focus_seed_ids = _focus_seed_ids()
        if focus_seed_ids:
            result["focus_seed_ids"] = focus_seed_ids
        return result

    return None


def _safe_float_list(values: Any, length: int = 3, default: Optional[list] = None) -> list:
    if default is None:
        default = [0.0] * length
    if values is None:
        return list(default)
    try:
        arr = list(values)[:length]
        if len(arr) < length:
            arr.extend(default[len(arr):])
        return [float(v) for v in arr]
    except Exception:
        return list(default)


class ManualNeedleSafetyError(ValueError):
    """Raised when a manual needle would cross a hard Data Tree obstacle."""

    code = "manual_needle_intersects_obstacle"

    def __init__(self, rejected_needle_ids: list[str]):
        self.rejected_needle_ids = rejected_needle_ids
        ids = ", ".join(rejected_needle_ids) or "manual needle"
        super().__init__(
            f"Manual needle update rejected: {ids} intersects a non-traversable structure. "
            "The previous safe geometry was retained."
        )


def _validate_manual_needle_safety(agent, needles, ct_image, ctv_mask, oar_mask):
    """Fail closed when a manual world-coordinate needle crosses hard anatomy."""
    import numpy as np

    from tool_factory.seed_plan.planning_pipeline import (
        _resolve_data_tree_obstacle_labels,
        _world_segment_hits_obstacle,
    )

    obstacle_labels, _ = _resolve_data_tree_obstacle_labels(agent)
    rejected = []
    for index, needle in enumerate(needles or []):
        if not isinstance(needle, dict):
            continue
        needle_id = str(needle.get("id") or f"manual_needle_{index + 1}")
        points = needle.get("points")
        if not isinstance(points, list) or len(points) < 2:
            rejected.append(needle_id)
            continue
        try:
            start = np.asarray(points[0], dtype=np.float64).reshape(-1)[:3]
            end = np.asarray(points[-1], dtype=np.float64).reshape(-1)[:3]
            if start.size != 3 or end.size != 3 or not np.all(np.isfinite(start + end)):
                raise ValueError("invalid manual endpoint")
        except Exception:
            rejected.append(needle_id)
            continue
        if _world_segment_hits_obstacle(
            [start, end], ct_image, ctv_mask, oar_mask, obstacle_labels
        ):
            rejected.append(needle_id)
    if rejected:
        raise ManualNeedleSafetyError(rejected)


def _reproject_seeds_onto_needles(
    seeds: list,
    needles: list,
    previous_needles: list,
) -> tuple[list, int]:
    """Move seeds with a dragged needle while preserving their relative depth.

    The browser keeps seed positions in patient-world coordinates. A needle
    edit changes the treatment geometry, so retaining the old seed coordinates
    would make the next dose calculation inconsistent with the visible needle.
    The old and new endpoint pairs define a one-dimensional parameter t; each
    seed is projected onto the old line and reconstructed on the new line at
    the same t. This is intentionally limited to needle edits and never
    changes an explicit seed drag.
    """
    import numpy as np

    def _points_by_trajectory(items):
        result = {}
        for item in items or []:
            if not isinstance(item, dict):
                continue
            points = item.get("points")
            if not isinstance(points, list) or len(points) < 2:
                continue
            try:
                p0 = np.asarray(_safe_float_list(points[0], 3), dtype=np.float64)
                p1 = np.asarray(_safe_float_list(points[-1], 3), dtype=np.float64)
                if not np.all(np.isfinite(p0)) or not np.all(np.isfinite(p1)):
                    continue
                key = str(item.get("trajectory_id") or item.get("id") or "")
                if key:
                    result[key] = (p0, p1)
            except Exception:
                continue
        return result

    old_by_traj = _points_by_trajectory(previous_needles)
    new_by_traj = _points_by_trajectory(needles)
    if not old_by_traj or not new_by_traj:
        return list(seeds or []), 0

    # Only seeds belonging to a needle whose endpoints actually changed are
    # reprojected.  Reprojecting unchanged trajectories introduces tiny
    # floating-point differences, invalidates their dose-cache keys, and
    # turns a single-needle edit into a full-plan inference.
    changed_trajectories = set()
    for trajectory_id in set(old_by_traj).intersection(new_by_traj):
        old_points = old_by_traj[trajectory_id]
        new_points = new_by_traj[trajectory_id]
        if not (
            np.allclose(old_points[0], new_points[0], rtol=0.0, atol=1e-6)
            and np.allclose(old_points[1], new_points[1], rtol=0.0, atol=1e-6)
        ):
            changed_trajectories.add(trajectory_id)

    if not changed_trajectories:
        return [dict(seed) if isinstance(seed, dict) else seed for seed in seeds or []], 0

    updated = []
    changed = 0
    for seed in seeds or []:
        if not isinstance(seed, dict):
            updated.append(seed)
            continue
        trajectory_id = str(seed.get("trajectory_id") or "")
        old_line = old_by_traj.get(trajectory_id)
        new_line = new_by_traj.get(trajectory_id)
        if (
            trajectory_id not in changed_trajectories
            or old_line is None
            or new_line is None
        ):
            updated.append(dict(seed))
            continue
        try:
            position = np.asarray(_safe_float_list(seed.get("position") or seed.get("pos"), 3), dtype=np.float64)
            old_target, old_entry = old_line
            new_target, new_entry = new_line
            old_axis = old_target - old_entry
            new_axis = new_target - new_entry
            old_length_sq = float(np.dot(old_axis, old_axis))
            new_length = float(np.linalg.norm(new_axis))
            if old_length_sq <= 1e-8 or new_length <= 1e-8:
                updated.append(dict(seed))
                continue
            t = float(np.dot(position - old_entry, old_axis) / old_length_sq)
            t = float(np.clip(t, 0.0, 1.0))
            replacement = new_entry + t * new_axis
            replacement_direction = (new_axis / new_length).tolist()
            item = dict(seed)
            item["position"] = replacement.tolist()
            item["direction"] = replacement_direction
            updated.append(item)
            changed += 1
        except Exception:
            updated.append(dict(seed))
    return updated, changed


def _compute_manual_ai_dose(
    agent,
    seeds: list,
    needles: list,
    *,
    previous_needles: Optional[list] = None,
    reproject_seeds: bool = False,
) -> Dict[str, Any]:
    """Recompute manual-plan dose with the trained DoseUNet model only.

    Manual seed and needle coordinates remain in frontend world coordinates.
    For model inference only, seed positions are transformed onto the existing
    planning grid and directions are converted with the same RAS-to-voxel helper
    used by the automatic planning pipeline. The resulting normalized dose is
    resampled back to original CT space for the existing overlays, DVH, and report
    paths. There is intentionally no analytical/Gaussian fallback here.
    """
    import numpy as np
    import time
    import SimpleITK as sitk

    if agent is None or not hasattr(agent, "memory"):
        raise ValueError("Agent not available")

    # A needle drag is a geometry edit, not merely a dose refresh. Reproject
    # the submitted seeds onto the new needle before converting coordinates for
    # DoseUNet inference. The previous geometry is supplied by the browser so
    # this remains correct even when the stored plan came from automatic mode.
    seeds, reprojection_count = _reproject_seeds_onto_needles(
        seeds,
        needles,
        previous_needles or [],
    ) if reproject_seeds else (list(seeds or []), 0)
    ct_image = agent.memory.retrieve("ct_image")
    ct_data = agent.memory.retrieve("ct_data")
    if ct_image is None or ct_data is None:
        raise ValueError("No CT image loaded")

    original_shape = tuple(int(v) for v in np.asarray(ct_data).shape)

    def _mask_array(*keys, shape=original_shape):
        for key in keys:
            arr = agent.memory.retrieve(key)
            if arr is None:
                continue
            try:
                arr_np = np.asarray(arr)
                if arr_np.shape == shape:
                    return arr_np
            except Exception:
                continue
        return None

    ctv_mask = _mask_array("ctv_mask", "ctv_array", "ctv_label_data", "ctv_full_labels")
    if ctv_mask is None or not np.any(ctv_mask > 0):
        raise ValueError("CTV mask is required before manual AI dose recomputation.")
    oar_mask = _mask_array("oar_array", "oar_label_data")
    _validate_manual_needle_safety(agent, needles, ct_image, ctv_mask, oar_mask)

    from plans import utilizations
    from plans.config import setting
    from tool_factory.seed_plan.planning_pipeline import (
        NEW_SLICES_ROUNDED,
        _load_dose_model,
        _resample_for_planning,
    )

    resampled_ct = agent.memory.retrieve("resampled_ct")
    resampled_ctv = agent.memory.retrieve("resampled_ctv")
    resampled_oar = agent.memory.retrieve("resampled_oar")
    if resampled_ct is None or resampled_ctv is None:
        resampled_ct, resampled_ctv, resampled_oar = _resample_for_planning(
            ct_image, ctv_mask, oar_mask, new_size=[128, 128, NEW_SLICES_ROUNDED]
        )
        agent.memory.store("resampled_ct", resampled_ct)
        agent.memory.store("resampled_ctv", resampled_ctv)
        if resampled_oar is not None:
            agent.memory.store("resampled_oar", resampled_oar)

    # Replanning is an interactive operation and can happen repeatedly for
    # one case. Reuse the process-wide, read-only DoseUNet instance instead of
    # reloading a large checkpoint on every needle drag. The model remains the
    # canonical trained checkpoint; this cache only removes redundant weight
    # deserialization and GPU upload.
    from plans.device_manager import get_device
    dose_device = get_device(caller="manual_planning_dose")
    dose_cache_key = str(dose_device)
    with _MANUAL_DOSE_MODEL_LOCK:
        dose_model = _MANUAL_DOSE_MODEL_CACHE.get(dose_cache_key)
        model_error = None
        if dose_model is None:
            dose_model, model_error = _load_dose_model(device=dose_device)
            if dose_model is not None:
                _MANUAL_DOSE_MODEL_CACHE[dose_cache_key] = dose_model
    if dose_model is None:
        raise ValueError(model_error or "dose_unet_spacing1mm dose model is unavailable")

    def _prepare_model_seeds(seed_records):
        """Normalize world-coordinate seeds for the deployed DoseUNet."""
        normalized = []
        model_ready = []
        size_xyz_local = np.asarray(resampled_ct.GetSize(), dtype=np.float64)
        for i, seed in enumerate(seed_records or []):
            pos = _safe_float_list(seed.get("position") if isinstance(seed, dict) else None, 3)
            direction = _safe_float_list(
                (seed.get("direction") if isinstance(seed, dict) else None),
                3,
                [0.0, 0.0, 1.0],
            )
            direction_np = np.asarray(direction, dtype=np.float64)
            dn = float(np.linalg.norm(direction_np))
            if dn <= 1e-8 or not np.all(np.isfinite(direction_np)):
                direction_np = np.array([0.0, 0.0, 1.0], dtype=np.float64)
            else:
                direction_np = direction_np / dn
            seed_id = str(
                seed.get("id")
                if isinstance(seed, dict) and seed.get("id")
                else f"manual_seed_{i + 1}"
            )
            traj_id = str(
                seed.get("trajectory_id")
                if isinstance(seed, dict) and seed.get("trajectory_id")
                else "manual_traj_1"
            )

            try:
                idx_xyz = np.asarray(
                    resampled_ct.TransformPhysicalPointToContinuousIndex(
                        tuple(float(v) for v in pos)
                    ),
                    dtype=np.float64,
                )
            except Exception as exc:
                logger.warning("Skipping seed with invalid physical coordinate transform: %s", exc)
                continue
            if not np.all(np.isfinite(idx_xyz)) or np.any(idx_xyz < 0.0) or np.any(idx_xyz >= size_xyz_local):
                continue

            try:
                voxel_direction = utilizations.ras_direction_to_voxel(
                    direction_np, resampled_ct
                ).astype(np.float32)
            except Exception as exc:
                logger.warning("Falling back to default voxel seed direction: %s", exc)
                voxel_direction = np.array([0.0, 0.0, 1.0], dtype=np.float32)
            vdn = float(np.linalg.norm(voxel_direction))
            if vdn <= 1e-8 or not np.all(np.isfinite(voxel_direction)):
                voxel_direction = np.array([0.0, 0.0, 1.0], dtype=np.float32)
            else:
                voxel_direction = voxel_direction / vdn

            pos_zyx = np.array([idx_xyz[2], idx_xyz[1], idx_xyz[0]], dtype=np.float32)
            seed_weight = float(seed.get("weight", 1.0)) if isinstance(seed, dict) else 1.0
            if not np.isfinite(seed_weight) or seed_weight <= 0.0:
                seed_weight = 1.0
            model_ready.append((pos_zyx, voxel_direction.astype(np.float32), seed_weight))
            normalized.append({
                "id": seed_id,
                "position": pos,
                "direction": direction_np.astype(np.float32).tolist(),
                "trajectory_id": traj_id,
                "weight": seed_weight,
            })
        return normalized, model_ready

    norm_seeds, model_seeds = _prepare_model_seeds(seeds)

    if not model_seeds:
        raise ValueError("No manual seeds fall inside the current CT volume.")

    args = setting()
    dose_image = utilizations.normalize_dose_image(
        resampled_ct,
        args.image_normalize[0],
        args.image_normalize[1],
        args.image_normalize[0],
        args.image_normalize[1],
    )
    dose_signature = (
        dose_cache_key,
        tuple(int(v) for v in dose_image.GetSize()),
        tuple(round(float(v), 5) for v in dose_image.GetSpacing()),
        tuple(round(float(v), 5) for v in dose_image.GetOrigin()),
        tuple(round(float(v), 5) for v in dose_image.GetDirection()),
    )
    def _seed_cache_key(seed):
        return (
            dose_signature,
            tuple(round(float(v), 4) for v in seed["position"]),
            tuple(round(float(v), 5) for v in seed["direction"]),
            round(float(seed["weight"]), 5),
        )

    def _cached_seed_maps(seed_records, model_records, *, deadline=None):
        """Return AI maps, evaluating only cache misses for this seed set."""
        cached_maps = []
        missing_seeds = []
        missing_records = []
        for seed, model_seed in zip(seed_records, model_records):
            cache_key = _seed_cache_key(seed)
            cached = _MANUAL_DOSE_SEED_CACHE.get(cache_key)
            if cached is None:
                cached_maps.append(None)
                missing_seeds.append(model_seed)
                missing_records.append((len(cached_maps) - 1, cache_key))
            else:
                cached_maps.append(cached)
        if missing_seeds:
            computed_maps = utilizations.batch_seed_dose_calculation_dl(
                missing_seeds,
                dose_image,
                dose_model,
                args.radiation_array_params["infer_img_size"],
                args.seed_info,
                args.image_normalize[0],
                args.image_normalize[1],
                args.image_normalize[2],
                deadline=deadline,
            )
            for (index, cache_key), seed_dose in zip(missing_records, computed_maps):
                array = np.asarray(seed_dose, dtype=np.float32).copy()
                _MANUAL_DOSE_SEED_CACHE[cache_key] = array
                _MANUAL_DOSE_SEED_CACHE_ORDER.append(cache_key)
                cached_maps[index] = array
            while len(_MANUAL_DOSE_SEED_CACHE_ORDER) > _MANUAL_DOSE_SEED_CACHE_LIMIT:
                stale_key = _MANUAL_DOSE_SEED_CACHE_ORDER.pop(0)
                _MANUAL_DOSE_SEED_CACHE.pop(stale_key, None)
        return [np.asarray(item, dtype=np.float32) for item in cached_maps if item is not None], len(missing_seeds)

    def _changed_trajectory_ids(old_needles, new_needles):
        """Return only the seed-association keys affected by a needle edit.

        The browser may serialize ``id`` and ``trajectory_id`` differently
        after a workspace restore. Comparing only trajectory_id therefore used
        to classify every needle as changed and silently turned a one-needle
        edit into a full-plan DoseUNet run. Match the stable needle id first,
        then include both old and new association keys when an id was renamed.
        """
        def _index(items):
            by_id = {}
            by_trajectory = {}
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                points = item.get("points")
                if not isinstance(points, list) or len(points) < 2:
                    continue
                endpoints = np.asarray([points[0], points[-1]], dtype=np.float64)
                needle_id = str(item.get("id") or "").strip()
                trajectory_id = str(item.get("trajectory_id") or needle_id).strip()
                record = {"points": endpoints, "trajectory_id": trajectory_id}
                if needle_id:
                    by_id[needle_id] = record
                if trajectory_id:
                    by_trajectory[trajectory_id] = record
            return by_id, by_trajectory

        old_by_id, old_by_trajectory = _index(old_needles)
        new_by_id, new_by_trajectory = _index(new_needles)
        changed = set()
        matched_ids = set(old_by_id).intersection(new_by_id)
        for needle_id in matched_ids:
            old_record = old_by_id[needle_id]
            new_record = new_by_id[needle_id]
            if not np.allclose(old_record["points"], new_record["points"], rtol=0.0, atol=1e-6):
                changed.update((needle_id, old_record["trajectory_id"], new_record["trajectory_id"]))

        # Preserve the legacy trajectory-only contract for callers that do not
        # have stable ids. When stable ids are available, do not compare the
        # raw trajectory-id sets: a workspace restore may rename all of those
        # association labels without changing any physical geometry.
        if not matched_ids:
            changed.update(set(old_by_trajectory).symmetric_difference(new_by_trajectory))
        else:
            matched_old_trajectories = {
                old_by_id[key]["trajectory_id"] for key in matched_ids
            }
            matched_new_trajectories = {
                new_by_id[key]["trajectory_id"] for key in matched_ids
            }
            changed.update(
                (set(old_by_trajectory) - matched_old_trajectories)
                .symmetric_difference(set(new_by_trajectory) - matched_new_trajectories)
            )
        for trajectory_id in set(old_by_trajectory).intersection(new_by_trajectory):
            if not np.allclose(
                old_by_trajectory[trajectory_id]["points"],
                new_by_trajectory[trajectory_id]["points"],
                rtol=0.0,
                atol=1e-6,
            ):
                changed.add(trajectory_id)
        # Do not add the raw trajectory-id difference here. Stable ids are
        # authoritative after workspace restore; re-adding this symmetric
        # difference would classify every restored needle as changed and turn
        # a one-needle edit into a full DoseUNet inference.
        return {str(value) for value in changed if str(value)}

    # A runaway interactive request is worse than a clear retryable error: it
    # blocks the user's case and leaves the progress row looking frozen. The
    # deadline is only applied to needle re-planning; ordinary manual dose
    # recomputation keeps its existing behavior. Every deadline check occurs
    # between model windows, never in the middle of a forward pass.
    interactive_deadline = None
    if reproject_seeds:
        try:
            timeout_s = float(os.environ.get("BRACHYBOT_MANUAL_REPLAN_TIMEOUT_S", "180"))
        except ValueError as exc:
            raise ValueError("BRACHYBOT_MANUAL_REPLAN_TIMEOUT_S must be numeric") from exc
        if timeout_s <= 0:
            raise ValueError("BRACHYBOT_MANUAL_REPLAN_TIMEOUT_S must be positive")
        interactive_deadline = time.monotonic() + timeout_s

    dose_base = np.zeros_like(sitk.GetArrayFromImage(dose_image), dtype=np.float32)
    changed_trajectories = _changed_trajectory_ids(previous_needles, needles) if reproject_seeds else set()
    if reproject_seeds:
        logger.info(
            "[manual_dose] geometry diff: changed_keys=%s previous_needles=%d current_needles=%d",
            sorted(changed_trajectories), len(previous_needles), len(needles),
        )
    previous_seed_records = agent.memory.retrieve("manual_seeds")
    if not isinstance(previous_seed_records, list) or not previous_seed_records:
        baseline_snapshot = agent.memory.retrieve("algorithm_plan_snapshot") or {}
        previous_seed_records = list(baseline_snapshot.get("seeds") or []) if isinstance(baseline_snapshot, dict) else []
    baseline_dose_key = "dose_distribution" if agent.memory.retrieve("manual_ai_dose") else "algorithm_plan_dose_distribution"
    previous_dose = agent.memory.retrieve(baseline_dose_key)
    incremental_applied = False
    if changed_trajectories and previous_dose is not None:
        candidate_base = np.asarray(previous_dose, dtype=np.float32)
        if candidate_base.shape == dose_base.shape:
            old_records = [
                seed for seed in previous_seed_records
                if isinstance(seed, dict) and str(seed.get("trajectory_id") or "") in changed_trajectories
            ]
            new_records = [
                seed for seed in norm_seeds
                if isinstance(seed, dict) and str(seed.get("trajectory_id") or "") in changed_trajectories
            ]
            old_norm, old_model = _prepare_model_seeds(old_records)
            new_norm, new_model = _prepare_model_seeds(new_records)
            # Automatic planning already has the exact trained-model dose
            # maps for its seeds in seed_plan[trajectory][2]. Reuse those maps
            # for the removed contribution instead of running DoseUNet again.
            # This is the main latency fix for the first drag after planning.
            old_maps = []
            old_misses = 0
            if not agent.memory.retrieve("manual_ai_dose"):
                seed_plan = agent.memory.retrieve("seed_plan") or []
                for trajectory_index, entry in enumerate(seed_plan):
                    if not isinstance(entry, (list, tuple)) or len(entry) < 3:
                        continue
                    trajectory_key = f"traj_{trajectory_index + 1}"
                    if trajectory_key not in changed_trajectories:
                        continue
                    for seed_dose in entry[2] or []:
                        seed_array = np.asarray(seed_dose, dtype=np.float32)
                        if seed_array.shape == dose_base.shape:
                            old_maps.append(seed_array)
                old_misses = 0 if old_maps else 1
            if not old_maps and old_model:
                old_maps, old_misses = _cached_seed_maps(
                    old_norm, old_model, deadline=interactive_deadline
                )
            new_maps, new_misses = _cached_seed_maps(
                new_norm, new_model, deadline=interactive_deadline
            ) if new_model else ([], 1)
            if old_maps and new_maps:
                dose_base = candidate_base.copy()
                for seed_dose in old_maps:
                    dose_base -= seed_dose
                for seed_dose in new_maps:
                    dose_base += seed_dose
                logger.info(
                    "[manual_dose] incremental needle replan: trajectories=%d, old_seeds=%d, "
                    "new_seeds=%d, model_misses=%d, full_seed_count=%d",
                    len(changed_trajectories), len(old_norm), len(new_norm),
                    old_misses + new_misses, len(norm_seeds),
                )
                incremental_applied = True
            else:
                dose_base = np.zeros_like(dose_base)

    if not incremental_applied:
        per_seed_doses, model_misses = _cached_seed_maps(
            norm_seeds, model_seeds, deadline=interactive_deadline
        )
        dose = np.zeros_like(dose_base, dtype=np.float32)
        for seed_dose in per_seed_doses:
            dose += seed_dose
        logger.info(
            "[manual_dose] full seed inference: seeds=%d, model_misses=%d",
            len(norm_seeds), model_misses,
        )
    else:
        dose = dose_base
    dose = np.nan_to_num(dose, nan=0.0, posinf=0.0, neginf=0.0)
    dose[dose < 0.0] = 0.0

    norm_needles = []
    for i, needle in enumerate(needles or []):
        points = needle.get("points") if isinstance(needle, dict) else None
        if not isinstance(points, list) or len(points) < 2:
            continue
        norm_needles.append({
            "id": str(needle.get("id") or f"manual_needle_{i + 1}"),
            "points": [_safe_float_list(points[0], 3), _safe_float_list(points[-1], 3)],
            "trajectory_id": str(needle.get("trajectory_id") or f"manual_traj_{i + 1}"),
        })

    grouped: Dict[str, list] = {}
    for seed in norm_seeds:
        grouped.setdefault(seed["trajectory_id"], []).append(seed)
    plan_serialized = []
    for traj_id, seed_list in grouped.items():
        needle = next((n for n in norm_needles if n.get("trajectory_id") == traj_id), None)
        trajectory = {"id": traj_id, "points": needle.get("points") if needle else []}
        plan_serialized.append({
            "trajectory": trajectory,
            "seeds": [{"position": s["position"], "direction": s["direction"]} for s in seed_list],
            "num_seeds": len(seed_list),
        })

    dose_sitk = sitk.GetImageFromArray(dose.astype(np.float32))
    dose_sitk.CopyInformation(resampled_ct)
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(ct_image)
    resampler.SetInterpolator(sitk.sitkLinear)
    dose_original = sitk.GetArrayFromImage(resampler.Execute(dose_sitk)).astype(np.float32)

    organ_names = agent.memory.retrieve("organ_names") or {}
    spacing = np.asarray(ct_image.GetSpacing(), dtype=np.float32)
    voxel_vol_cm3 = float(np.prod(spacing) / 1000.0)
    dose_gy = dose_original * DOSE_MODEL_SCALE_GY

    metrics: Dict[str, Any] = {
        "prescribed_dose": 1.0,
        "volume_metric_units": "fraction",
        "manual_preview": True,
        "dose_engine": "dose_unet_spacing1mm",
        "total_seeds": len(norm_seeds),
        "num_trajectories": len(grouped),
        "reprojected_seeds": int(reprojection_count),
    }
    dvh_data: Dict[str, Any] = {}
    if ctv_mask is not None and np.any(ctv_mask > 0):
        target_doses = dose_gy[ctv_mask > 0]
        if target_doses.size:
            sorted_desc = np.sort(target_doses)[::-1]

            def dose_at_pct(pct):
                idx = int(np.clip(np.ceil((pct / 100.0) * len(sorted_desc)) - 1, 0, len(sorted_desc) - 1))
                return float(sorted_desc[idx])

            def vol_at_dose(thr):
                return float(np.sum(target_doses >= thr) / len(target_doses))

            metrics.update({
                "dmax": float(np.max(target_doses)),
                "dmin": float(np.min(target_doses)),
                "dmean": float(np.mean(target_doses)),
                "d98": dose_at_pct(98),
                "d95": dose_at_pct(95),
                "d90": dose_at_pct(90),
                "d50": dose_at_pct(50),
                "d2": dose_at_pct(2),
                "v100": vol_at_dose(DOSE_MODEL_SCALE_GY),
                "v150": vol_at_dose(DOSE_MODEL_SCALE_GY * 1.5),
                "v200": vol_at_dose(DOSE_MODEL_SCALE_GY * 2.0),
                "v50": vol_at_dose(DOSE_MODEL_SCALE_GY * 0.5),
                "ctv_voxels": int(np.sum(ctv_mask > 0)),
                "ctv_volume_cm3": float(np.sum(ctv_mask > 0) * voxel_vol_cm3),
            })
            dose_max_val = max(600.0, float(np.max(target_doses)) * 1.1, 360.0)
            centers = np.linspace(0.0, dose_max_val, 601, dtype=np.float32)
            dvh_data["CTV"] = {
                "dose_bins": centers.tolist(),
                "volume_pcts": [float(np.sum(target_doses >= d) / len(target_doses) * 100.0) for d in centers],
            }

    oar_metrics: Dict[str, Any] = {}
    if oar_mask is not None:
        labels = [int(v) for v in np.unique(oar_mask) if int(v) > 0]
        centers = None
        for label in labels:
            mask = oar_mask == label
            od = dose_gy[mask]
            if od.size == 0:
                continue
            name = _canonical_oar_display_name(
                organ_names.get(label) or organ_names.get(str(label)),
                label,
            )
            sorted_desc = np.sort(od)[::-1]

            def dose_at_xcc(x_cc):
                nvox = max(1, int(np.ceil(x_cc / max(voxel_vol_cm3, 1e-9))))
                idx = min(nvox - 1, len(sorted_desc) - 1)
                return float(sorted_desc[idx])

            oar_metrics[name] = {
                "label_id": int(label),
                "dmax": float(np.max(od)),
                "max_dose": float(np.max(od)),
                "mean_dose": float(np.mean(od)),
                "d0_1cc": dose_at_xcc(0.1),
                "d1cc": dose_at_xcc(1.0),
                "d2cc": dose_at_xcc(2.0),
                # Volume metrics use the same fraction contract as CTV
                # metrics. Report/UI boundaries convert to percent exactly
                # once, preventing impossible values such as 350.3%.
                "v100": float(np.sum(od >= DOSE_MODEL_SCALE_GY) / len(od)),
                "v150": float(np.sum(od >= DOSE_MODEL_SCALE_GY * 1.5) / len(od)),
                "volume_cm3": float(np.sum(mask) * voxel_vol_cm3),
                "volume_voxels": int(np.sum(mask)),
            }
            if centers is None:
                centers = np.linspace(0.0, max(600.0, float(np.max(dose_gy)) * 1.1, 360.0), 601, dtype=np.float32)
            dvh_data[name] = {
                "dose_bins": centers.tolist(),
                "volume_pcts": [float(np.sum(od >= d) / len(od) * 100.0) for d in centers],
            }
    metrics["oar_metrics"] = oar_metrics
    metrics["dvh_data"] = dvh_data

    target_context = _source_backed_target_context(agent)
    if target_context and metrics.get("ctv_voxels", 0) > 0:
        from tool_factory.dose_eval.comprehensive_dose_evaluation import (
            ComprehensiveDoseEvaluationTool,
        )
        from tool_factory.plan_quality.clinical_standards import get_oar_standard

        evaluator = ComprehensiveDoseEvaluationTool()
        site = target_context["site"]
        constraints = get_oar_standard(site)
        violations = []
        for name, values in oar_metrics.items():
            constraint = evaluator._match_oar_constraint(name, constraints)
            if constraint:
                violations.extend(evaluator._check_oar_violation(
                    name,
                    {"D2cc": values.get("d2cc"), "Dmax": values.get("dmax"), "Dmean": values.get("mean_dose")},
                    constraint,
                ))
        metrics["plan_score"] = evaluator._compute_plan_score(
            {
                "V100": metrics.get("v100", 0.0),
                "V150": metrics.get("v150", 0.0),
                "V200": metrics.get("v200", 0.0),
                "D90": metrics.get("d90", 0.0),
            },
            DOSE_MODEL_SCALE_GY,
            violations,
            target_context["tumor_type"],
        )
        metrics["criteria_status"] = "SOURCE_BACKED"
        metrics["criteria_site"] = site
    else:
        metrics["plan_score"] = None
        metrics["criteria_status"] = "UNVERIFIED"

    agent.memory.store("manual_planning_preview", True)
    agent.memory.store("manual_ai_dose", True)
    agent.memory.store("manual_plan_active", True)
    agent.memory.store("dose_engine", "dose_unet_spacing1mm")
    agent.memory.store("manual_seeds", norm_seeds)
    agent.memory.store("manual_needles", norm_needles)
    agent.memory.store("seed_plan", plan_serialized)
    agent.memory.store("seed_plan_serialized", plan_serialized)
    agent.memory.store("total_seeds", len(norm_seeds))
    agent.memory.store("num_trajectories", len(grouped))
    agent.memory.store("dose_distribution", dose)
    agent.memory.store("dose_distribution_gy", dose_original)
    agent.memory.store("dose_units", DOSE_MODEL_UNITS)
    agent.memory.store("dose_scale_gy", DOSE_MODEL_SCALE_GY)
    agent.memory.store("dose_metrics", metrics)
    agent.memory.store("metrics", metrics)
    agent.memory.store("dvh_data", dvh_data)
    planning_version = int(agent.memory.retrieve("manual_plan_version") or 0)
    artifact_status = {
        "dose": "ready",
        "dvh": "ready",
        "report": "stale",
        "quality_check": "stale",
        "surgical_guide": "stale",
        "reason": "manual dose recomputed",
        "planning_version": planning_version,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    agent.memory.store("manual_artifact_status", artifact_status)

    return {
        "success": True,
        "manual_preview": True,
        "dose_engine": "dose_unet_spacing1mm",
        "total_seeds": len(norm_seeds),
        "num_trajectories": len(grouped),
        # Return authoritative post-reprojection geometry so the browser does
        # not need a full planning refresh just to synchronize one dragged
        # needle and its attached seeds.
        "seeds": norm_seeds,
        "needles": norm_needles,
        "reprojected_seeds": int(reprojection_count),
        "metrics": metrics,
        "dose_range": [float(dose_original.min()), float(dose_original.max())],
        "dose_range_normalized": [float(dose_original.min()), float(dose_original.max())],
        "dose_range_gy": [float(dose_gy.min()), float(dose_gy.max())],
        "dose_units": DOSE_MODEL_UNITS,
        "dose_scale_gy": DOSE_MODEL_SCALE_GY,
        "planning_id": agent.memory.retrieve("manual_planning_id"),
        "planning_version": planning_version,
        "artifact_status": artifact_status,
    }


import colorsys

def _label_color(label_id: int) -> tuple:
    """Generate visually distinct color for organ label using golden-ratio HSV.

    Provides unique colors for 57+ organs without modulo collision.
    """
    golden_ratio = 0.618033988749895
    h = (label_id * golden_ratio) % 1.0
    s = 0.65 + (label_id % 3) * 0.12  # 0.65/0.77/0.89
    v = 0.85 + (label_id % 2) * 0.10   # 0.85/0.95
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


_rate_limit_cleanup_counter = 0


def _check_rate_limit(client_ip: str) -> bool:
    global _rate_limit_cleanup_counter
    now = datetime.now().timestamp()

    with _rate_limit_lock:
        # The limiter is shared by Flask worker threads. Keep cleanup and
        # per-client mutation under one lock so the timestamp lists cannot be
        # overwritten or deleted while another request is updating them.
        _rate_limit_cleanup_counter += 1
        if _rate_limit_cleanup_counter >= 100:
            _rate_limit_cleanup_counter = 0
            expired_ips = [
                ip for ip, timestamps in _rate_limit_store.items()
                if all(now - t >= RATE_LIMIT_WINDOW for t in timestamps)
            ]
            for ip in expired_ips:
                _rate_limit_store.pop(ip, None)

        timestamps = [
            t for t in _rate_limit_store.get(client_ip, [])
            if now - t < RATE_LIMIT_WINDOW
        ]
        if len(timestamps) >= RATE_LIMIT_REQUESTS:
            _rate_limit_store[client_ip] = timestamps
            return False
        timestamps.append(now)
        _rate_limit_store[client_ip] = timestamps
        return True


def _client_ip_for_rate_limit() -> str:
    """Honor proxy headers only when the deployment explicitly trusts them."""
    if os.environ.get("BRACHYBOT_TRUST_PROXY", "").lower() in TRUE_VALUES:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
    return request.remote_addr or "unknown"


def _is_loopback_host(host: str) -> bool:
    host = (host or "").strip().lower()
    return host in {"127.0.0.1", "localhost", "::1"} or host.startswith("127.")


def _env_paths(name: str) -> list:
    raw = os.environ.get(name, "")
    return [p for p in raw.split(os.pathsep) if p.strip()]


def _real_roots(paths: Iterable[str]) -> list:
    roots = []
    for path in paths:
        if not path:
            continue
        roots.append(os.path.realpath(os.path.abspath(os.path.expanduser(path))))
    return roots


def _is_under_root(path: str, roots: Iterable[str]) -> bool:
    resolved = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    for root in _real_roots(roots):
        if resolved == root or resolved.startswith(root + os.sep):
            return True
    return False


def _allowed_read_roots() -> list:
    return _real_roots([
        UPLOAD_DIR,
        RUNTIME_DIR,
        "/tmp",
        "/data",
        *_env_paths("BRACHYBOT_DATA_ROOTS"),
    ])


def _allowed_write_roots() -> list:
    return _real_roots([
        *OUTPUT_DIRS,
        SCREENSHOTS_DIR,
        RUNTIME_DIR,
        "/tmp",
        *_env_paths("BRACHYBOT_OUTPUT_ROOTS"),
    ])


def _validate_path(path: str, purpose: str = "read") -> bool:
    """Validate a file path against purpose-specific allowlists."""
    if not path:
        return False
    if "\x00" in path:
        return False
    if '..' in path.replace('\\', '/').split('/'):
        return False
    try:
        resolved = os.path.realpath(os.path.abspath(path))
    except (OSError, ValueError):
        return False
    roots = _allowed_write_roots() if purpose == "write" else _allowed_read_roots()
    if _is_under_root(resolved, roots):
        return True
    logger.warning(
        "Path validation failed: %s (resolved: %s) not in allowed %s roots: %s",
        path, resolved, purpose, roots,
    )
    return False


def _resolve_output_path(path: str) -> Optional[str]:
    if not path:
        return None
    candidate = path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)
    resolved = os.path.realpath(os.path.abspath(candidate))
    return resolved if _validate_path(resolved, purpose="write") else None


def _upload_ext(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".nii.gz"):
        return ".nii.gz"
    return os.path.splitext(lower)[1]


def _validate_upload_name(filename: str, *, dicom_series: bool = False) -> bool:
    ext = _upload_ext(filename)
    allowed = ALLOWED_DICOM_SERIES_EXTENSIONS if dicom_series else ALLOWED_UPLOAD_EXTENSIONS
    return ext in allowed


def _decode_png_data_url(image_data: str) -> bytes:
    if "," in image_data:
        header, b64 = image_data.split(",", 1)
        if not header.lower().startswith("data:image/png;base64"):
            raise ValueError("Only PNG screenshots are accepted")
    else:
        b64 = image_data
    try:
        img_bytes = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid base64 image data") from exc
    if len(img_bytes) > MAX_SCREENSHOT_BYTES:
        raise ValueError(f"Screenshot exceeds {MAX_SCREENSHOT_BYTES} bytes")
    if not img_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Screenshot payload is not a PNG image")
    return img_bytes


def _valid_api_key_from_request() -> bool:
    """Validate the current request's API key header without short-circuiting routes."""
    if not _API_KEY_REQUIRED:
        return True
    if not API_KEY:
        # Explicit auth was requested but no secret was configured. Fail closed
        # instead of raising AttributeError on API_KEY.encode().
        return False
    request_key = request.headers.get("X-API-Key", "")
    if not request_key:
        return False
    return secrets.compare_digest(request_key, API_KEY)


def _screenshot_signature(filename: str, expires: int) -> str:
    """Create a URL signature for browser image loads that cannot set headers."""
    if not API_KEY:
        raise RuntimeError("BRACHYBOT_API_KEY is required for signed screenshot URLs")
    payload = f"{filename}:{int(expires)}".encode("utf-8")
    return hmac.new(API_KEY.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _make_screenshot_url(filename: str, ttl_seconds: int = 3600) -> str:
    if not _API_KEY_REQUIRED:
        return f"/api/screenshots/{filename}"
    if not API_KEY:
        return f"/api/screenshots/{filename}"
    expires = int(time.time()) + int(ttl_seconds)
    sig = _screenshot_signature(filename, expires)
    return f"/api/screenshots/{filename}?expires={expires}&sig={sig}"


def _valid_screenshot_request(filename: str) -> bool:
    """Allow either normal API-key auth or a short-lived signed screenshot URL."""
    if _valid_api_key_from_request():
        return True
    try:
        expires = int(request.args.get("expires", "0"))
    except ValueError:
        return False
    sig = request.args.get("sig", "")
    if not sig or expires < int(time.time()):
        return False
    return secrets.compare_digest(sig, _screenshot_signature(filename, expires))


def _safe_screenshot_path(filename: str) -> str:
    """Resolve a screenshot filename inside uploads/screenshots only."""
    if os.path.basename(filename) != filename or _upload_ext(filename) != ".png":
        raise ValueError("Invalid screenshot filename")
    screenshots_dir = SCREENSHOTS_DIR
    filepath = os.path.realpath(os.path.join(screenshots_dir, filename))
    if not filepath.startswith(screenshots_dir + os.sep):
        raise ValueError("Invalid screenshot path")
    return filepath


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Local loopback development may run without auth; non-loopback
        # binding is rejected at startup unless a key or trusted-network
        # override is explicitly configured.
        if _API_KEY_REQUIRED and not _valid_api_key_from_request():
            return jsonify({"error": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated


def rate_limit(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _TRUST_NETWORK:
            client_ip = _client_ip_for_rate_limit()
            if not _check_rate_limit(client_ip):
                return jsonify({"error": "Rate limit exceeded"}), 429
        return f(*args, **kwargs)
    return decorated


# The monitor helpers above predate the unified UTF-8 message path.  Keep their
# compatibility entry points, but bind the public runtime names to this clean
# implementation so persisted events from older sessions are rendered without
# mojibake and without exposing internal English status prose in Chinese UI.
def _monitor_step_label_clean(key: str, language: str = "en") -> str:
    labels = {
        "ctv": ("CTV 分割", "CTV segmentation"),
        "oar": ("OAR 分割", "OAR segmentation"),
        "trajectory_init": ("轨迹初始化", "Trajectory initialization"),
        "trajectory_refine": ("轨迹优化", "Trajectory refinement"),
        "seed_planning": ("粒子布源", "Seed planning"),
        "dose_calc": ("剂量计算", "Dose calculation"),
        "dose_eval": ("剂量评估", "Dose evaluation"),
        "full": ("完整规划流程", "Full planning pipeline"),
    }
    pair = labels.get(key, (key or "步骤", key or "step"))
    return pair[0] if language == "zh" else pair[1]


def _localize_monitor_text_clean(text: Any, language: str = "en") -> str:
    raw = str(text or "")
    if language != "zh" or not raw:
        return raw
    exact = {
        "Run dose evaluation to make V100/D90 advice available.": "请先执行剂量评估，以生成 V100/D90 建议。",
        "Inspect cold CTV regions against the intended prescription coverage, then recompute dose and DVH after edits.": "请检查 CTV 的低剂量区域，并在编辑后重新计算剂量和 DVH。",
        "Compare D90 with the source-backed prescription convention for this tumor site before labeling coverage adequate or inadequate.": "在判断覆盖是否充分前，请将 D90 与该部位有来源依据的处方规范进行比较。",
        "If the hot spot is clinically undesirable for this site, spread central seeds along the needle track or reduce local seed density.": "如果该部位不适合当前热点分布，请沿针道分散中心粒子或降低局部粒子密度。",
        "Compare OAR doses against applicable site-specific guidance or the confirmed case protocol before classifying safety.": "在判断安全性前，请依据适用的部位特异性指南或已确认的病例方案比较 OAR 剂量。",
        "Review whether the current seed count and spacing are sufficient for the requested coverage after applying source-backed criteria.": "依据有来源依据的标准，检查当前粒子数量和间距是否足以达到目标覆盖。",
        "Recent manual edits were detected; recompute dose after each seed or needle adjustment to keep DVH current.": "检测到近期手动编辑；每次调整粒子或针道后请重新计算剂量，以保持 DVH 最新。",
        "No seeds are present. Add a needle and place seeds through the CTV before dose evaluation.": "当前没有粒子。请先添加针道并在 CTV 内布置粒子，再进行剂量评估。",
        "Dose preview updated. Open Analysis to inspect DVH and OAR dose.": "剂量预览已更新。请打开分析面板检查 DVH 和 OAR 剂量。",
        "Seed geometry was not available for the monitor; verify seed spacing directly in the 3D viewer.": "监测器未获得粒子几何信息；请直接在 3D viewer 中核对粒子间距。",
    }
    if raw in exact:
        return exact[raw]
    patterns = (
        (r"CTV V100 is ([0-9.]+)%; compare it with the applicable site-specific guidance or confirmed case protocol target\.",
         lambda m: f"CTV V100 为 {m.group(1)}%；请与适用的部位特异性指南或已确认的病例方案目标比较。"),
        (r"CTV D90 is ([0-9.]+) Gy(?:; current dose reference is ([0-9.]+) Gy)?\.",
         lambda m: f"CTV D90 为 {m.group(1)} Gy" + (f"；当前剂量参考为 {m.group(2)} Gy" if m.group(2) else "") + "。"),
        (r"CTV V200 is ([0-9.]+)%; inspect the corresponding hot-spot location in 2D/3D\.",
         lambda m: f"CTV V200 为 {m.group(1)}%；请在 2D/3D viewer 中检查对应的热点位置。"),
        (r"CTV V150 is ([0-9.]+)%; interpret uniformity with the current site-specific criteria\.",
         lambda m: f"CTV V150 为 {m.group(1)}%；请依据当前部位特异性标准判断均匀性。"),
        (r"Dose preview updated: V100=([0-9.]+)%, D90=([0-9.]+) Gy\. Review hot spots and OAR dose before adding seeds\.",
         lambda m: f"剂量预览已更新：V100={m.group(1)}%，D90={m.group(2)} Gy。添加粒子前请检查热点和 OAR 剂量。"),
        (r"Seed edit recorded\. ([0-9]+) close seed pair\(s\) are below ([0-9.]+) mm; inspect them before continuing\.",
         lambda m: f"已记录粒子编辑：有 {m.group(1)} 对粒子间距小于 {m.group(2)} mm；继续前请检查这些粒子。"),
        (r"Seed edit recorded\. Current V100 is ([0-9.]+)%; inspect cold CTV regions after recompute\.",
         lambda m: f"已记录粒子编辑：当前 V100 为 {m.group(1)}%；重新计算后请检查 CTV 低剂量区域。"),
        (r"Plan score is ([0-9.]+)/100; use it as an advisory ranking signal, not approval\.",
         lambda m: f"规划评分为 {m.group(1)}/100；该分数仅用于辅助排序，不代表临床批准。"),
    )
    for pattern, formatter in patterns:
        match = re.fullmatch(pattern, raw)
        if match:
            return formatter(match)
    if raw.startswith("Top OAR doses: "):
        return "OAR 最高剂量结构：" + raw[len("Top OAR doses: "):]
    if raw.startswith("No seed-center pair is closer than "):
        return "当前预览中没有粒子中心间距小于 " + raw[len("No seed-center pair is closer than "):].replace(" in the current preview.", "。")
    if raw.startswith("Needle edit recorded."):
        return "已记录针道编辑。请确认针道经过安全组织，并与不可穿刺 OAR 保持距离。"
    if raw.startswith("Seed edit recorded."):
        return "已记录粒子编辑。请重新计算剂量并核对 DVH，再放置下一枚粒子。"
    if raw.startswith("Plan score is "):
        return raw.replace("; use it as an advisory ranking signal, not approval.", "；该分数仅用于辅助排序，不代表临床批准。")
    return raw


def _monitor_activity_label_clean(key: str, language: str = "en") -> str:
    labels = {
        "planning.step": ("规划步骤", "Planning steps"),
        "segmentation.step": ("分割步骤", "Segmentation steps"),
        "manual.needle.drag": ("手动针道拖拽", "Manual needle drags"),
        "manual.needle.position_only": ("手动针道位置调整", "Manual needle position updates"),
        "manual.seed.drag": ("手动粒子拖拽", "Manual seed drags"),
        "manual.seed.add": ("手动添加粒子", "Manual seed additions"),
        "manual.seed.delete": ("手动删除粒子", "Manual seed deletions"),
        "manual.dose": ("手动剂量重算", "Manual dose updates"),
        "ui.panel": ("面板操作", "Panel interactions"),
        "ui.click": ("点击操作", "Click interactions"),
        "ui.change": ("控件修改", "Control changes"),
        "ui.slider": ("滑块调整", "Slider changes"),
        "training.start": ("监测启动", "Monitor starts"),
        "training.stop": ("监测结束", "Monitor stops"),
    }
    pair = labels.get(key)
    if pair:
        return pair[0] if language == "zh" else pair[1]
    return key.replace(".", " ").strip().title() or ("其他事件" if language == "zh" else "Other events")


def _format_training_summary_clean(events: list, counts: Dict[str, int], advice: Dict[str, Any], language: str = "en") -> str:
    if language == "zh":
        lines = ["## 规划监测总结", f"本次监测记录了 {len(events)} 个 UI/规划事件。"]
        section_labels = ("活动概览", "当前优势", "需要关注", "建议")
    else:
        lines = ["## Planning monitoring summary", f"Recorded {len(events)} UI/planning events."]
        section_labels = ("Activity", "Strengths", "Issues", "Recommendations")
    if counts:
        lines.extend(["", f"### {section_labels[0]}"])
        for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]:
            lines.append(f"- {_monitor_activity_label_clean(key, language)}: {value}")
    localized = _localize_plan_advice(advice, language)
    for heading, key in zip(section_labels[1:], ("strengths", "issues", "advice")):
        values = localized.get(key) or []
        if values:
            lines.extend(["", f"### {heading}"])
            lines.extend(f"- {value}" for value in values)
    return "\n".join(lines)


def _training_feedback_for_event_clean(agent, session_id: Optional[str], event: Dict[str, Any]) -> Optional[str]:
    etype = str(event.get("type", ""))
    detail = _monitor_event_detail(event)
    language = _monitor_language(event.get("language") or detail.get("language"))
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    d90 = _extract_metric_value(metrics, "d90")
    target_criteria = _source_backed_target_context(agent).get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(target_criteria, "v100_min"))
    if etype.startswith("manual.seed"):
        interference = snapshot.get("seed_interference") or {}
        if interference.get("status") == "attention":
            return _localize_monitor_text_clean(
                f"Seed edit recorded. {len(interference.get('close_pairs') or [])} close seed pair(s) are below {float(interference.get('threshold_mm') or 0.8):.1f} mm; inspect them before continuing.",
                language,
            )
        if v100 is not None and v100_min is not None and v100 < v100_min:
            return _localize_monitor_text_clean(
                f"Seed edit recorded. Current V100 is {v100 * 100:.1f}%; inspect cold CTV regions after recompute.",
                language,
            )
        return _localize_monitor_text_clean("Seed edit recorded. Recompute dose and verify DVH before placing the next seed.", language)
    if etype.startswith("manual.needle"):
        return _localize_monitor_text_clean("Needle edit recorded. Check that the path traverses safe tissue and keeps distance from non-traversable OARs.", language)
    if etype in {"planning.step", "segmentation.step"}:
        key = _monitor_step_key(event)
        stage = _monitor_step_label_clean(key, language)
        status = _monitor_event_status(event)
        if language == "zh":
            messages = {
                "running": f"{stage}正在执行；完成后我会检查 Data Tree 和 viewer 输出。",
                "done": f"{stage}已完成；请检查 Data Tree 和 viewer 输出，再继续下一步。",
                "error": f"{stage}执行失败；请查看错误详情并确认输入数据。",
                "event": f"{stage}事件已记录；请检查 Data Tree 输出。",
            }
            return messages[status]
        if status == "running":
            return f"{stage} is running; I will verify the Data Tree and viewer output when it finishes."
        if status == "done":
            return f"{stage} completed; verify the Data Tree and viewer output before the next prerequisite step."
        if status == "error":
            return f"{stage} failed; inspect the error details and confirm the input data."
        return f"{stage} event recorded; verify its Data Tree output."
    if etype == "manual.dose":
        if v100 is not None and d90 is not None:
            return _localize_monitor_text_clean(
                f"Dose preview updated: V100={v100 * 100:.1f}%, D90={d90:.1f} Gy. Review hot spots and OAR dose before adding seeds.",
                language,
            )
        return _localize_monitor_text_clean("Dose preview updated. Open Analysis to inspect DVH and OAR dose.", language)
    return None


def _training_screenshot_for_event_clean(agent, session_id: Optional[str], event: Dict[str, Any], feedback: Optional[str]) -> Optional[Dict[str, Any]]:
    if not feedback:
        return None
    etype = str(event.get("type", ""))
    language = _monitor_language(event.get("language") or _monitor_event_detail(event).get("language"))
    status = _monitor_event_status(event)
    if etype in {"planning.step", "segmentation.step"} and status != "done":
        return None
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    v200 = _volume_metric_as_fraction(metrics, "v200")
    target_criteria = _source_backed_target_context(agent).get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(target_criteria, "v100_min"))
    v200_max = _metric_as_fraction(_extract_metric_value(target_criteria, "v200_max"))
    focus_ids = []
    for pair in (snapshot.get("seed_interference", {}) or {}).get("close_pairs", [])[:4]:
        for key in ("first_id", "second_id"):
            seed_id = str(pair.get(key) or "").strip()
            if seed_id and seed_id not in focus_ids:
                focus_ids.append(seed_id)
    def question(zh: str, en: str) -> str:
        return zh if language == "zh" else en
    if etype == "manual.dose":
        concern = (v100 is not None and v100_min is not None and v100 < v100_min) or (v200 is not None and v200_max is not None and v200 > v200_max)
        result = {
            "target": "dose-overview" if concern else "dvh",
            "question": question(
                "监测截图：显示手动剂量重算后的 CT、掩膜、剂量热图、粒子/针道和 DVH。" if concern else "监测截图：显示手动剂量重算后的 DVH。",
                "Training monitor snapshot: show the CT, masks, dose heatmap, seeds/needles, and DVH after manual dose recomputation." if concern else "Training monitor snapshot: show the updated DVH after manual dose recomputation.",
            ),
        }
        if focus_ids:
            result["focus_seed_ids"] = focus_ids
        return result
    if etype == "segmentation.step":
        return {"target": "viewer-3d", "question": question("监测截图：显示刚加载的 CTV/OAR 结构、3D viewer 和 Data Tree。", "Training monitor snapshot: show the newly loaded CTV/OAR structures in the 3D viewer and Data Tree.")}
    if etype == "planning.step":
        key = _monitor_step_key(event)
        if key in {"trajectory_init", "trajectory_refine", "seed_planning"}:
            stage = _monitor_step_label_clean(key, language)
            return {"target": "viewer-3d", "question": question(f"监测截图：显示{stage}完成后的 3D viewer、针道、粒子和 Data Tree。", f"Training monitor snapshot: show the 3D viewer, needle/seed output, and Data Tree after {_monitor_step_label_clean(key)}.")}
        if key in {"dose_calc", "dose_eval", "full"}:
            return {"target": "dose-overview", "question": question("监测截图：显示完成后的剂量分布和 DVH。", "Training monitor snapshot: show the completed plan dose distribution and DVH for review.")}
        return None
    if etype.startswith("manual.needle"):
        return {"target": "viewer-3d", "question": question("监测截图：显示当前 3D 针道和邻近解剖结构。", "Training monitor snapshot: show the current 3D needle path and nearby anatomy.")}
    if etype.startswith("manual.seed"):
        result = {"target": "viewer-3d", "question": question("监测截图：显示被编辑的粒子及其邻近粒子，以检查间距。", "Training monitor snapshot: show the edited seed and nearby seeds so spacing can be checked.")}
        if focus_ids:
            result["focus_seed_ids"] = focus_ids
        return result
    return None


def _monitor_step_label_utf8(key: str, language: str = "en") -> str:
    labels = {
        "ctv": ("CTV 分割", "CTV segmentation"),
        "oar": ("OAR 分割", "OAR segmentation"),
        "trajectory_init": ("轨迹初始化", "Trajectory initialization"),
        "trajectory_refine": ("轨迹优化", "Trajectory refinement"),
        "seed_planning": ("粒子布源", "Seed planning"),
        "dose_calc": ("剂量计算", "Dose calculation"),
        "dose_eval": ("剂量评估", "Dose evaluation"),
        "full": ("完整规划流程", "Full planning pipeline"),
    }
    pair = labels.get(key, (key or "步骤", key or "step"))
    return pair[0] if language == "zh" else pair[1]


def _localize_monitor_text_utf8(text: Any, language: str = "en") -> str:
    """Translate deterministic monitor prose without leaking internal English."""
    raw = str(text or "")
    if language != "zh" or not raw:
        return raw
    exact = {
        "Run dose evaluation to make V100/D90 advice available.": "请先执行剂量评估，以生成 V100/D90 建议。",
        "Inspect cold CTV regions against the intended prescription coverage, then recompute dose and DVH after edits.": "请检查 CTV 的低剂量区域，编辑后重新计算剂量和 DVH。",
        "Compare D90 with the source-backed prescription convention for this tumor site before labeling coverage adequate or inadequate.": "请将 D90 与该部位有来源依据的处方规范比较后，再判断覆盖是否充分。",
        "If the hot spot is clinically undesirable for this site, spread central seeds along the needle track or reduce local seed density.": "如果该部位不适合当前热点分布，请沿针道分散中心粒子或降低局部粒子密度。",
        "Compare OAR doses against applicable site-specific guidance or the confirmed case protocol before classifying safety.": "判断安全性前，请依据适用的部位特异性指南或已确认的病例方案比较 OAR 剂量。",
        "Review whether the current seed count and spacing are sufficient for the requested coverage after applying source-backed criteria.": "依据有来源的标准，检查当前粒子数量和间距是否足以达到目标覆盖。",
        "Recent manual edits were detected; recompute dose after each seed or needle adjustment to keep DVH current.": "检测到近期手动编辑；每次调整粒子或针道后请重新计算剂量，以保持 DVH 为最新结果。",
        "No seeds are present. Add a needle and place seeds through the CTV before dose evaluation.": "当前没有粒子。请先添加针道并在 CTV 内布置粒子，再进行剂量评估。",
        "Dose preview updated. Open Analysis to inspect DVH and OAR dose.": "剂量预览已更新，请打开分析面板检查 DVH 和 OAR 剂量。",
        "Seed geometry was not available for the monitor; verify seed spacing directly in the 3D viewer.": "监测器未获得粒子几何信息，请直接在 3D 查看器中核对粒子间距。",
    }
    if raw in exact:
        return exact[raw]
    patterns = (
        (r"CTV V100 is ([0-9.]+)%; compare it with the applicable site-specific guidance or confirmed case protocol target\.",
         lambda m: f"CTV V100 为 {m.group(1)}%，请与适用的部位特异性指南或已确认病例方案目标比较。"),
        (r"CTV D90 is ([0-9.]+) Gy(?:; current dose reference is ([0-9.]+) Gy)?\.",
         lambda m: f"CTV D90 为 {m.group(1)} Gy" + (f"，当前剂量参考为 {m.group(2)} Gy" if m.group(2) else "") + "。"),
        (r"CTV V200 is ([0-9.]+)%; inspect the corresponding hot-spot location in 2D/3D\.",
         lambda m: f"CTV V200 为 {m.group(1)}%，请在 2D/3D 查看器中检查对应的热点位置。"),
        (r"CTV V150 is ([0-9.]+)%; interpret uniformity with the current site-specific criteria\.",
         lambda m: f"CTV V150 为 {m.group(1)}%，请依据当前部位特异性标准判断均匀性。"),
        (r"Dose preview updated: V100=([0-9.]+)%, D90=([0-9.]+) Gy\. Review hot spots and OAR dose before adding seeds\.",
         lambda m: f"剂量预览已更新：V100={m.group(1)}%，D90={m.group(2)} Gy。添加粒子前请检查热点和 OAR 剂量。"),
        (r"Seed edit recorded\. ([0-9]+) close seed pair\(s\) are below ([0-9.]+) mm; inspect them before continuing\.",
         lambda m: f"已记录粒子编辑：有 {m.group(1)} 对粒子间距小于 {m.group(2)} mm；继续前请检查这些粒子。"),
        (r"Seed edit recorded\. Current V100 is ([0-9.]+)%; inspect cold CTV regions after recompute\.",
         lambda m: f"已记录粒子编辑：当前 V100 为 {m.group(1)}%；重新计算后请检查 CTV 低剂量区域。"),
        (r"Plan score is ([0-9.]+)/100; use it as an advisory ranking signal, not approval\.",
         lambda m: f"规划评分为 {m.group(1)}/100；该分数仅用于辅助排序，不代表临床批准。"),
    )
    for pattern, formatter in patterns:
        match = re.fullmatch(pattern, raw)
        if match:
            return formatter(match)
    if raw.startswith("Top OAR doses: "):
        return "OAR 最高剂量结构：" + raw[len("Top OAR doses: "):]
    if raw.startswith("No seed-center pair is closer than "):
        return "当前预览中没有粒子中心间距小于 " + raw[len("No seed-center pair is closer than "):].replace(" in the current preview.", "。")
    if raw.startswith("Needle edit recorded."):
        return "已记录针道编辑。请确认针道经过安全组织，并与不可穿刺 OAR 保持距离。"
    if raw.startswith("Seed edit recorded."):
        return "已记录粒子编辑。请重新计算剂量并核对 DVH，再放置下一枚粒子。"
    if raw.startswith("Plan score is "):
        return raw.replace("; use it as an advisory ranking signal, not approval.", "；该分数仅用于辅助排序，不代表临床批准。")
    return raw


def _monitor_activity_label_utf8(key: str, language: str = "en") -> str:
    labels = {
        "planning.step": ("规划步骤", "Planning steps"),
        "segmentation.step": ("分割步骤", "Segmentation steps"),
        "manual.needle.drag": ("手动针道拖拽", "Manual needle drags"),
        "manual.needle.position_only": ("手动针道位置调整", "Manual needle position updates"),
        "manual.seed.drag": ("手动粒子拖拽", "Manual seed drags"),
        "manual.seed.add": ("手动添加粒子", "Manual seed additions"),
        "manual.seed.delete": ("手动删除粒子", "Manual seed deletions"),
        "manual.dose": ("手动剂量重算", "Manual dose updates"),
        "ui.panel": ("面板操作", "Panel interactions"),
        "ui.click": ("点击操作", "Click interactions"),
        "ui.change": ("控件修改", "Control changes"),
        "ui.slider": ("滑块调整", "Slider changes"),
        "training.start": ("监测启动", "Monitor starts"),
        "training.stop": ("监测结束", "Monitor stops"),
    }
    pair = labels.get(key)
    if pair:
        return pair[0] if language == "zh" else pair[1]
    return key.replace(".", " ").strip().title() or ("其他事件" if language == "zh" else "Other events")


def _format_training_summary_utf8(events: list, counts: Dict[str, int], advice: Dict[str, Any], language: str = "en") -> str:
    if language == "zh":
        lines = ["## 规划监测总结", f"本次监测记录了 {len(events)} 个界面/规划事件。"]
        section_labels = ("活动概览", "当前优势", "需要关注", "建议")
    else:
        lines = ["## Planning monitoring summary", f"Recorded {len(events)} UI/planning events."]
        section_labels = ("Activity", "Strengths", "Issues", "Recommendations")
    if counts:
        lines.extend(["", f"### {section_labels[0]}"])
        for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]:
            lines.append(f"- {_monitor_activity_label_utf8(key, language)}: {value}")
    localized = _localize_plan_advice(advice, language)
    for heading, key in zip(section_labels[1:], ("strengths", "issues", "advice")):
        values = localized.get(key) or []
        if values:
            lines.extend(["", f"### {heading}"])
            lines.extend(f"- {value}" for value in values)
    return "\n".join(lines)


def _training_feedback_for_event_utf8(agent, session_id: Optional[str], event: Dict[str, Any]) -> Optional[str]:
    etype = str(event.get("type", ""))
    detail = _monitor_event_detail(event)
    language = _monitor_language(event.get("language") or detail.get("language"))
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    d90 = _extract_metric_value(metrics, "d90")
    target_criteria = _source_backed_target_context(agent).get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(target_criteria, "v100_min"))
    if etype.startswith("manual.seed"):
        interference = snapshot.get("seed_interference") or {}
        if interference.get("status") == "attention":
            return _localize_monitor_text_utf8(
                f"Seed edit recorded. {len(interference.get('close_pairs') or [])} close seed pair(s) are below {float(interference.get('threshold_mm') or 0.8):.1f} mm; inspect them before continuing.",
                language,
            )
        if v100 is not None and v100_min is not None and v100 < v100_min:
            return _localize_monitor_text_utf8(
                f"Seed edit recorded. Current V100 is {v100 * 100:.1f}%; inspect cold CTV regions after recompute.",
                language,
            )
        return _localize_monitor_text_utf8("Seed edit recorded. Recompute dose and verify DVH before placing the next seed.", language)
    if etype.startswith("manual.needle"):
        return _localize_monitor_text_utf8("Needle edit recorded. Check that the path traverses safe tissue and keeps distance from non-traversable OARs.", language)
    if etype in {"planning.step", "segmentation.step"}:
        stage = _monitor_step_label_utf8(_monitor_step_key(event), language)
        status = _monitor_event_status(event)
        if language == "zh":
            messages = {
                "running": f"{stage}正在执行；完成后我会检查数据树和查看器输出。",
                "done": f"{stage}已完成；请检查数据树和查看器输出，再继续下一步。",
                "error": f"{stage}执行失败；请查看错误详情并确认输入数据。",
                "event": f"{stage}事件已记录；请检查数据树输出。",
            }
            return messages[status]
        if status == "running":
            return f"{stage} is running; I will verify the Data Tree and viewer output when it finishes."
        if status == "done":
            return f"{stage} completed; verify the Data Tree and viewer output before the next prerequisite step."
        if status == "error":
            return f"{stage} failed; inspect the error details and confirm the input data."
        return f"{stage} event recorded; verify its Data Tree output."
    if etype == "manual.dose":
        if v100 is not None and d90 is not None:
            return _localize_monitor_text_utf8(
                f"Dose preview updated: V100={v100 * 100:.1f}%, D90={d90:.1f} Gy. Review hot spots and OAR dose before adding seeds.",
                language,
            )
        return _localize_monitor_text_utf8("Dose preview updated. Open Analysis to inspect DVH and OAR dose.", language)
    return None


def _training_screenshot_for_event_utf8(agent, session_id: Optional[str], event: Dict[str, Any], feedback: Optional[str]) -> Optional[Dict[str, Any]]:
    if not feedback:
        return None
    etype = str(event.get("type", ""))
    language = _monitor_language(event.get("language") or _monitor_event_detail(event).get("language"))
    status = _monitor_event_status(event)
    if etype in {"planning.step", "segmentation.step"} and status != "done":
        return None
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    v200 = _volume_metric_as_fraction(metrics, "v200")
    target_criteria = _source_backed_target_context(agent).get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(target_criteria, "v100_min"))
    v200_max = _metric_as_fraction(_extract_metric_value(target_criteria, "v200_max"))
    focus_ids = []
    for pair in (snapshot.get("seed_interference", {}) or {}).get("close_pairs", [])[:4]:
        for key in ("first_id", "second_id"):
            seed_id = str(pair.get(key) or "").strip()
            if seed_id and seed_id not in focus_ids:
                focus_ids.append(seed_id)
    def q(zh: str, en: str) -> str:
        return zh if language == "zh" else en
    if etype == "manual.dose":
        concern = (v100 is not None and v100_min is not None and v100 < v100_min) or (v200 is not None and v200_max is not None and v200 > v200_max)
        result = {
            "target": "dose-overview" if concern else "dvh",
            "question": q(
                "监测截图：显示手动剂量重算后的 CT、掩膜、剂量热图、粒子、针道和 DVH。" if concern else "监测截图：显示手动剂量重算后的 DVH。",
                "Training monitor snapshot: show the CT, masks, dose heatmap, seeds/needles, and DVH after manual dose recomputation." if concern else "Training monitor snapshot: show the updated DVH after manual dose recomputation.",
            ),
        }
        if focus_ids:
            result["focus_seed_ids"] = focus_ids
        return result
    if etype == "segmentation.step":
        return {"target": "viewer-3d", "question": q("监测截图：显示刚加载的 CTV/OAR 结构、3D 查看器和数据树。", "Training monitor snapshot: show the newly loaded CTV/OAR structures in the 3D viewer and Data Tree.")}
    if etype == "planning.step":
        key = _monitor_step_key(event)
        if key in {"trajectory_init", "trajectory_refine", "seed_planning"}:
            stage = _monitor_step_label_utf8(key, language)
            return {"target": "viewer-3d", "question": q(f"监测截图：显示{stage}完成后的 3D 查看器、针道、粒子和数据树。", f"Training monitor snapshot: show the 3D viewer, needle/seed output, and Data Tree after {_monitor_step_label_utf8(key)}.")}
        if key in {"dose_calc", "dose_eval", "full"}:
            return {"target": "dose-overview", "question": q("监测截图：显示规划完成后的剂量分布和 DVH。", "Training monitor snapshot: show the completed plan dose distribution and DVH for review.")}
        return None
    if etype.startswith("manual.needle"):
        return {"target": "viewer-3d", "question": q("监测截图：显示当前 3D 针道和附近解剖结构。", "Training monitor snapshot: show the current 3D needle path and nearby anatomy.")}
    if etype.startswith("manual.seed"):
        result = {"target": "viewer-3d", "question": q("监测截图：显示被编辑的粒子及其邻近粒子，用于检查间距。", "Training monitor snapshot: show the edited seed and nearby seeds so spacing can be checked.")}
        if focus_ids:
            result["focus_seed_ids"] = focus_ids
        return result
    return None


_monitor_step_label = _monitor_step_label_utf8
_localize_monitor_text = _localize_monitor_text_utf8
_monitor_activity_label = _monitor_activity_label_utf8
_format_training_summary = _format_training_summary_utf8
_training_feedback_for_event = _training_feedback_for_event_utf8
_training_screenshot_for_event = _training_screenshot_for_event_utf8


# Final monitor localization boundary.  Older compatibility shims above are
# intentionally left in place for imports from archived deployments, but they
# are not allowed to own the public helper names: a previous deployment had
# mojibake literals in that shim and leaked them into the web chat.
def _monitor_step_label_final(key: str, language: str = "en") -> str:
    labels = {
        "ctv": ("CTV 分割", "CTV segmentation"),
        "oar": ("OAR 分割", "OAR segmentation"),
        "trajectory_init": ("轨迹初始化", "Trajectory initialization"),
        "trajectory_refine": ("轨迹优化", "Trajectory refinement"),
        "seed_planning": ("粒子布源", "Seed planning"),
        "dose_calc": ("剂量计算", "Dose calculation"),
        "dose_eval": ("剂量评估", "Dose evaluation"),
        "full": ("完整规划流程", "Full planning pipeline"),
    }
    pair = labels.get(key, (key or "步骤", key or "step"))
    return pair[0] if language == "zh" else pair[1]


def _localize_monitor_text_final(text: Any, language: str = "en") -> str:
    raw = str(text or "")
    if language != "zh" or not raw:
        return raw
    exact = {
        "Run dose evaluation to make V100/D90 advice available.": "请先执行剂量评估，以生成 V100/D90 建议。",
        "Inspect cold CTV regions against the intended prescription coverage, then recompute dose and DVH after edits.": "请检查 CTV 的低剂量区域；编辑后重新计算剂量和 DVH。",
        "Compare D90 with the source-backed prescription convention for this tumor site before labeling coverage adequate or inadequate.": "在判断覆盖是否充分前，请将 D90 与该部位有来源依据的处方规范进行比较。",
        "If the hot spot is clinically undesirable for this site, spread central seeds along the needle track or reduce local seed density.": "如果该部位不适合当前热点分布，请沿针道分散中心粒子或降低局部粒子密度。",
        "Compare OAR doses against applicable site-specific guidance or the confirmed case protocol before classifying safety.": "判断安全性前，请依据适用的部位特异性指南或已确认的病例方案比较 OAR 剂量。",
        "Review whether the current seed count and spacing are sufficient for the requested coverage after applying source-backed criteria.": "依据有来源的标准，检查当前粒子数量和间距是否足以达到目标覆盖。",
        "Recent manual edits were detected; recompute dose after each seed or needle adjustment to keep DVH current.": "检测到近期手动编辑；每次调整粒子或针道后请重新计算剂量，以保持 DVH 为最新结果。",
        "No seeds are present. Add a needle and place seeds through the CTV before dose evaluation.": "当前没有粒子。请先添加针道并在 CTV 内布置粒子，再进行剂量评估。",
        "Dose preview updated. Open Analysis to inspect DVH and OAR dose.": "剂量预览已更新，请打开分析面板检查 DVH 和 OAR 剂量。",
        "Seed geometry was not available for the monitor; verify seed spacing directly in the 3D viewer.": "监测器未获得粒子几何信息，请直接在 3D 查看器中核对粒子间距。",
    }
    if raw in exact:
        return exact[raw]
    patterns = (
        (r"CTV V100 is ([0-9.]+)%; compare it with the applicable site-specific guidance or confirmed case protocol target\.",
         lambda m: f"CTV V100 为 {m.group(1)}%，请与适用的部位特异性指南或已确认的病例方案目标比较。"),
        (r"CTV D90 is ([0-9.]+) Gy(?:; current dose reference is ([0-9.]+) Gy)?\.",
         lambda m: f"CTV D90 为 {m.group(1)} Gy" + (f"，当前剂量参考为 {m.group(2)} Gy" if m.group(2) else "") + "。"),
        (r"CTV V200 is ([0-9.]+)%; inspect the corresponding hot-spot location in 2D/3D\.",
         lambda m: f"CTV V200 为 {m.group(1)}%，请在 2D/3D 查看器中检查对应的热点位置。"),
        (r"CTV V150 is ([0-9.]+)%; interpret uniformity with the current site-specific criteria\.",
         lambda m: f"CTV V150 为 {m.group(1)}%，请依据当前部位特异性标准判断均匀性。"),
        (r"Dose preview updated: V100=([0-9.]+)%, D90=([0-9.]+) Gy\. Review hot spots and OAR dose before adding seeds\.",
         lambda m: f"剂量预览已更新：V100={m.group(1)}%，D90={m.group(2)} Gy。添加粒子前请检查热点和 OAR 剂量。"),
        (r"Seed edit recorded\. ([0-9]+) close seed pair\(s\) are below ([0-9.]+) mm; inspect them before continuing\.",
         lambda m: f"已记录粒子编辑：有 {m.group(1)} 对粒子间距小于 {m.group(2)} mm；继续前请检查这些粒子。"),
        (r"Seed edit recorded\. Current V100 is ([0-9.]+)%; inspect cold CTV regions after recompute\.",
         lambda m: f"已记录粒子编辑：当前 V100 为 {m.group(1)}%；重新计算后请检查 CTV 低剂量区域。"),
        (r"Plan score is ([0-9.]+)/100; use it as an advisory ranking signal, not approval\.",
         lambda m: f"规划评分为 {m.group(1)}/100；该分数仅用于辅助排序，不代表临床批准。"),
    )
    for pattern, formatter in patterns:
        match = re.fullmatch(pattern, raw)
        if match:
            return formatter(match)
    if raw.startswith("Top OAR doses: "):
        return "OAR 最高剂量结构：" + raw[len("Top OAR doses: "):]
    if raw.startswith("No seed-center pair is closer than "):
        return "当前预览中没有粒子中心间距小于 " + raw[len("No seed-center pair is closer than "):].replace(" in the current preview.", "。")
    if raw.startswith("Needle edit recorded."):
        return "已记录针道编辑。请确认针道经过安全组织，并与不可穿刺 OAR 保持距离。"
    if raw.startswith("Seed edit recorded."):
        return "已记录粒子编辑。请重新计算剂量并核对 DVH，再放置下一枚粒子。"
    return raw


def _monitor_activity_label_final(key: str, language: str = "en") -> str:
    labels = {
        "planning.step": ("规划步骤", "Planning steps"),
        "segmentation.step": ("分割步骤", "Segmentation steps"),
        "manual.needle.drag": ("手动针道拖拽", "Manual needle drags"),
        "manual.needle.position_only": ("手动针道位置调整", "Manual needle position updates"),
        "manual.seed.drag": ("手动粒子拖拽", "Manual seed drags"),
        "manual.seed.add": ("手动添加粒子", "Manual seed additions"),
        "manual.seed.delete": ("手动删除粒子", "Manual seed deletions"),
        "manual.dose": ("手动剂量重算", "Manual dose updates"),
        "ui.panel": ("面板操作", "Panel interactions"),
        "ui.click": ("点击操作", "Click interactions"),
        "ui.change": ("控件修改", "Control changes"),
        "ui.slider": ("滑块调整", "Slider changes"),
        "training.start": ("监测启动", "Monitor starts"),
        "training.stop": ("监测结束", "Monitor stops"),
    }
    pair = labels.get(key, (key.replace(".", " ").strip().title() or "其他事件", key.replace(".", " ").strip().title() or "Other events"))
    return pair[0] if language == "zh" else pair[1]


def _format_training_summary_final(events: list, counts: Dict[str, int], advice: Dict[str, Any], language: str = "en") -> str:
    if language == "zh":
        lines = ["## 规划监测总结", f"本次监测记录了 {len(events)} 个界面或规划事件。"]
        section_labels = ("活动概览", "当前优势", "需要关注", "建议")
    else:
        lines = ["## Planning monitoring summary", f"Recorded {len(events)} UI/planning events."]
        section_labels = ("Activity", "Strengths", "Issues", "Recommendations")
    if counts:
        lines.extend(["", f"### {section_labels[0]}"])
        for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]:
            lines.append(f"- {_monitor_activity_label_final(key, language)}: {value}")
    localized = _localize_plan_advice(advice, language)
    for heading, key in zip(section_labels[1:], ("strengths", "issues", "advice")):
        values = localized.get(key) or []
        if values:
            lines.extend(["", f"### {heading}"])
            lines.extend(f"- {value}" for value in values)
    return "\n".join(lines)


def _training_feedback_for_event_final(agent, session_id: Optional[str], event: Dict[str, Any]) -> Optional[str]:
    etype = str(event.get("type", ""))
    detail = _monitor_event_detail(event)
    language = _monitor_language(event.get("language") or detail.get("language"))
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    d90 = _extract_metric_value(metrics, "d90")
    target = _source_backed_target_context(agent).get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(target, "v100_min"))
    if etype.startswith("manual.seed"):
        interference = snapshot.get("seed_interference") or {}
        if interference.get("status") == "attention":
            message = f"Seed edit recorded. {len(interference.get('close_pairs') or [])} close seed pair(s) are below {float(interference.get('threshold_mm') or 0.8):.1f} mm; inspect them before continuing."
            return _localize_monitor_text_final(message, language)
        if v100 is not None and v100_min is not None and v100 < v100_min:
            return _localize_monitor_text_final(f"Seed edit recorded. Current V100 is {v100 * 100:.1f}%; inspect cold CTV regions after recompute.", language)
        return _localize_monitor_text_final("Seed edit recorded. Recompute dose and verify DVH before placing the next seed.", language)
    if etype.startswith("manual.needle"):
        return _localize_monitor_text_final("Needle edit recorded. Check that the path traverses safe tissue and keeps distance from non-traversable OARs.", language)
    if etype in {"planning.step", "segmentation.step"}:
        stage = _monitor_step_label_final(_monitor_step_key(event), language)
        status = _monitor_event_status(event)
        messages = {
            "running": f"{stage} 正在执行；完成后我会核对 Data Tree 和 viewer 输出。" if language == "zh" else f"{stage} is running; I will verify the Data Tree and viewer output when it finishes.",
            "done": f"{stage} 已完成；请先核对 Data Tree 和 viewer 输出，再继续下一步。" if language == "zh" else f"{stage} completed; verify the Data Tree and viewer output before the next prerequisite step.",
            "error": f"{stage} 执行失败；请检查错误详情并确认输入数据。" if language == "zh" else f"{stage} failed; inspect the error details and confirm the input data.",
            "event": f"已记录 {stage} 事件；请核对 Data Tree 输出。" if language == "zh" else f"{stage} event recorded; verify its Data Tree output.",
        }
        return messages.get(status, messages["event"])
    if etype == "manual.dose":
        if v100 is not None and d90 is not None:
            return _localize_monitor_text_final(f"Dose preview updated: V100={v100 * 100:.1f}%, D90={d90:.1f} Gy. Review hot spots and OAR dose before adding seeds.", language)
        return _localize_monitor_text_final("Dose preview updated. Open Analysis to inspect DVH and OAR dose.", language)
    return None


def _training_screenshot_for_event_final(agent, session_id: Optional[str], event: Dict[str, Any], feedback: Optional[str]) -> Optional[Dict[str, Any]]:
    if not feedback:
        return None
    etype = str(event.get("type", ""))
    detail = _monitor_event_detail(event)
    language = _monitor_language(event.get("language") or detail.get("language"))
    status = _monitor_event_status(event)
    if etype in {"planning.step", "segmentation.step"} and status != "done":
        return None
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    v200 = _volume_metric_as_fraction(metrics, "v200")
    criteria = _source_backed_target_context(agent).get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(criteria, "v100_min"))
    v200_max = _metric_as_fraction(_extract_metric_value(criteria, "v200_max"))
    focus_ids = []
    for pair in (snapshot.get("seed_interference", {}) or {}).get("close_pairs", [])[:4]:
        for key in ("first_id", "second_id"):
            seed_id = str(pair.get(key) or "").strip()
            if seed_id and seed_id not in focus_ids:
                focus_ids.append(seed_id)
    def question(zh: str, en: str) -> str:
        return zh if language == "zh" else en
    if etype == "manual.dose":
        concern = (v100 is not None and v100_min is not None and v100 < v100_min) or (v200 is not None and v200_max is not None and v200 > v200_max)
        result = {
            "target": "dose-overview" if concern else "dvh",
            "question": question(
                "监测截图：显示手动剂量重算后的 CT、掩膜、剂量热图、粒子、针道和 DVH。" if concern else "监测截图：显示手动剂量重算后的 DVH。",
                "Training monitor snapshot: show the CT, masks, dose heatmap, seeds/needles, and DVH after manual dose recomputation." if concern else "Training monitor snapshot: show the updated DVH after manual dose recomputation.",
            ),
        }
        if focus_ids:
            result["focus_seed_ids"] = focus_ids
        return result
    if etype == "segmentation.step":
        return {"target": "viewer-3d", "question": question("监测截图：显示刚加载的 CTV/OAR 结构、3D 查看器和 Data Tree。", "Training monitor snapshot: show the newly loaded CTV/OAR structures in the 3D viewer and Data Tree.")}
    if etype == "planning.step":
        key = _monitor_step_key(event)
        if key in {"trajectory_init", "trajectory_refine", "seed_planning"}:
            stage = _monitor_step_label_final(key, language)
            return {"target": "viewer-3d", "question": question(f"监测截图：显示 {stage} 完成后的 3D 查看器、针道、粒子和 Data Tree。", f"Training monitor snapshot: show the 3D viewer, needle/seed output, and Data Tree after {_monitor_step_label_final(key)}.")}
        if key in {"dose_calc", "dose_eval", "full"}:
            return {"target": "dose-overview", "question": question("监测截图：显示规划完成后的剂量分布和 DVH。", "Training monitor snapshot: show the completed plan dose distribution and DVH for review.")}
        return None
    if etype.startswith("manual.needle"):
        return {"target": "viewer-3d", "question": question("监测截图：显示当前 3D 针道和附近的解剖结构。", "Training monitor snapshot: show the current 3D needle path and nearby anatomy.")}
    if etype.startswith("manual.seed"):
        result = {"target": "viewer-3d", "question": question("监测截图：显示被编辑的粒子及其邻近粒子，用于检查间距。", "Training monitor snapshot: show the edited seed and nearby seeds so spacing can be checked.")}
        if focus_ids:
            result["focus_seed_ids"] = focus_ids
        return result
    return None


_monitor_step_label = _monitor_step_label_final
_localize_monitor_text = _localize_monitor_text_final
_monitor_activity_label = _monitor_activity_label_final
_format_training_summary = _format_training_summary_final
_training_feedback_for_event = _training_feedback_for_event_final
_training_screenshot_for_event = _training_screenshot_for_event_final


# The historical compatibility block above contains mojibake literals from an
# old source-encoding conversion.  Keep it import-compatible, but make the
# public monitor helpers resolve to this ASCII-source implementation so the
# runtime always emits real UTF-8 text for Chinese users.
def _monitor_step_label_clean(key: str, language: str = "en") -> str:
    labels = {
        "ctv": ("CTV \u5206\u5272", "CTV segmentation"),
        "oar": ("OAR \u5206\u5272", "OAR segmentation"),
        "trajectory_init": ("\u8f68\u8ff9\u521d\u59cb\u5316", "Trajectory initialization"),
        "trajectory_refine": ("\u8f68\u8ff9\u4f18\u5316", "Trajectory refinement"),
        "seed_planning": ("\u7c92\u5b50\u5e03\u6e90", "Seed planning"),
        "dose_calc": ("\u5242\u91cf\u8ba1\u7b97", "Dose calculation"),
        "dose_eval": ("\u5242\u91cf\u8bc4\u4f30", "Dose evaluation"),
        "full": ("\u5b8c\u6574\u89c4\u5212\u6d41\u7a0b", "Full planning pipeline"),
    }
    pair = labels.get(key, (key or "\u6b65\u9aa4", key or "step"))
    return pair[0] if language == "zh" else pair[1]


def _localize_monitor_text_clean(value: Any, language: str = "en") -> str:
    raw = str(value or "")
    if language != "zh" or not raw:
        return raw
    exact = {
        "Run dose evaluation to make V100/D90 advice available.":
            "\u8bf7\u5148\u6267\u884c\u5242\u91cf\u8bc4\u4f30\uff0c\u4ee5\u4fbf\u751f\u6210 V100/D90 \u5efa\u8bae\u3002",
        "Inspect cold CTV regions against the intended prescription coverage, then recompute dose and DVH after edits.":
            "\u8bf7\u68c0\u67e5 CTV \u7684\u4f4e\u5242\u91cf\u533a\u57df\uff0c\u7f16\u8f91\u540e\u91cd\u65b0\u8ba1\u7b97\u5242\u91cf\u548c DVH\u3002",
        "Compare D90 with the source-backed prescription convention for this tumor site before labeling coverage adequate or inadequate.":
            "\u5224\u65ad\u8986\u76d6\u662f\u5426\u5145\u5206\u524d\uff0c\u8bf7\u5c06 D90 \u4e0e\u8be5\u90e8\u4f4d\u6709\u6765\u6e90\u4f9d\u636e\u7684\u5904\u65b9\u89c4\u8303\u8fdb\u884c\u6bd4\u8f83\u3002",
        "Compare OAR doses against applicable site-specific guidance or the confirmed case protocol before classifying safety.":
            "\u5224\u65ad\u5b89\u5168\u6027\u524d\uff0c\u8bf7\u4f9d\u636e\u9002\u7528\u7684\u90e8\u4f4d\u7279\u5f02\u6027\u6307\u5357\u6216\u5df2\u786e\u8ba4\u7684\u75c5\u4f8b\u65b9\u6848\u6bd4\u8f83 OAR \u5242\u91cf\u3002",
        "Review whether the current seed count and spacing are sufficient for the requested coverage after applying source-backed criteria.":
            "\u6839\u636e\u6709\u6765\u6e90\u7684\u6807\u51c6\uff0c\u68c0\u67e5\u5f53\u524d\u7c92\u5b50\u6570\u91cf\u548c\u95f4\u8ddd\u662f\u5426\u8db3\u4ee5\u8fbe\u5230\u76ee\u6807\u8986\u76d6\u3002",
        "Recent manual edits were detected; recompute dose after each seed or needle adjustment to keep DVH current.":
            "\u68c0\u6d4b\u5230\u8fd1\u671f\u624b\u52a8\u7f16\u8f91\uff1b\u6bcf\u6b21\u8c03\u6574\u7c92\u5b50\u6216\u9488\u9053\u540e\u8bf7\u91cd\u65b0\u8ba1\u7b97\u5242\u91cf\uff0c\u4ee5\u4fdd\u6301 DVH \u4e3a\u6700\u65b0\u7ed3\u679c\u3002",
        "No seeds are present. Add a needle and place seeds through the CTV before dose evaluation.":
            "\u5f53\u524d\u6ca1\u6709\u7c92\u5b50\u3002\u8bf7\u5148\u6dfb\u52a0\u9488\u9053\u5e76\u5728 CTV \u5185\u5e03\u7f6e\u7c92\u5b50\uff0c\u518d\u8fdb\u884c\u5242\u91cf\u8bc4\u4f30\u3002",
        "Dose preview updated. Open Analysis to inspect DVH and OAR dose.":
            "\u5242\u91cf\u9884\u89c8\u5df2\u66f4\u65b0\u3002\u8bf7\u6253\u5f00\u5206\u6790\u9762\u677f\u67e5\u770b DVH \u548c OAR \u5242\u91cf\u3002",
        "Seed geometry was not available for the monitor; verify seed spacing directly in the 3D viewer.":
            "\u76d1\u6d4b\u5668\u672a\u83b7\u53d6\u7c92\u5b50\u51e0\u4f55\u4fe1\u606f\uff0c\u8bf7\u76f4\u63a5\u5728 3D \u67e5\u770b\u5668\u4e2d\u6838\u5bf9\u7c92\u5b50\u95f4\u8ddd\u3002",
        "Inspect the highlighted seed pairs in the 3D viewer, correct their axial spacing, and recompute dose before final review.":
            "\u8bf7\u5728 3D viewer \u4e2d\u68c0\u67e5\u9ad8\u4eae\u7c92\u5b50\u7ec4\u5408\uff0c\u4fee\u6b63\u8f74\u5411\u95f4\u8ddd\u5e76\u91cd\u65b0\u8ba1\u7b97\u5242\u91cf\u3002",
        "Move or remove every obstacle-intersecting needle before dose review or Surgical Guide generation.":
            "\u8bf7\u5728\u5242\u91cf\u5ba1\u6838\u6216\u751f\u6210\u624b\u672f\u5bfc\u677f\u524d\uff0c\u79fb\u52a8\u6216\u5220\u9664\u6240\u6709\u4e0e\u4e0d\u53ef\u7a7f\u523a\u7ed3\u6784\u76f8\u4ea4\u7684\u9488\u9053\u3002",
        "Review the highlighted needle pairs for physical collision and guide-sleeve manufacturability.":
            "\u8bf7\u68c0\u67e5\u9ad8\u4eae\u9488\u9053\u7ec4\u5408\u662f\u5426\u53d1\u751f\u7269\u7406\u78b0\u649e\uff0c\u5e76\u786e\u8ba4\u5bfc\u5411\u5957\u7b52\u53ef\u5236\u9020\u3002",
        "Recompute the outdated dose/DVH and regenerate the Surgical Guide before finalizing the plan.":
            "\u8bf7\u91cd\u65b0\u8ba1\u7b97\u5df2\u8fc7\u671f\u7684\u5242\u91cf\u548c DVH\uff0c\u5e76\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f\u540e\u518d\u5b8c\u6210\u89c4\u5212\u3002",
        "No Surgical Guide has been generated for the current needle plan.":
            "\u5f53\u524d\u9488\u9053\u89c4\u5212\u5c1a\u672a\u751f\u6210\u624b\u672f\u5bfc\u677f\u3002",
        "The Surgical Guide does not match the current planning version.":
            "\u624b\u672f\u5bfc\u677f\u4e0e\u5f53\u524d\u9488\u9053\u89c4\u5212\u4e0d\u4e00\u81f4\uff0c\u5df2\u6807\u8bb0\u4e3a\u8fc7\u671f\u3002",
    }
    if raw in exact:
        return exact[raw]
    patterns = (
        (r"CTV V100 is ([0-9.]+)%; compare it with the applicable site-specific guidance or confirmed case protocol target\.",
         lambda match: f"CTV V100 \u4e3a {match.group(1)}%\uff0c\u8bf7\u4e0e\u9002\u7528\u7684\u90e8\u4f4d\u7279\u5f02\u6027\u6307\u5357\u6216\u5df2\u786e\u8ba4\u7684\u75c5\u4f8b\u65b9\u6848\u76ee\u6807\u6bd4\u8f83\u3002"),
        (r"CTV D90 is ([0-9.]+) Gy(?:; current dose reference is ([0-9.]+) Gy)?\.",
         lambda match: f"CTV D90 \u4e3a {match.group(1)} Gy" + (f"\uff0c\u5f53\u524d\u5242\u91cf\u53c2\u8003\u4e3a {match.group(2)} Gy" if match.group(2) else "") + "\u3002"),
        (r"CTV V200 is ([0-9.]+)%; inspect the corresponding hot-spot location in 2D/3D\.",
         lambda match: f"CTV V200 \u4e3a {match.group(1)}%\uff0c\u8bf7\u5728 2D/3D \u67e5\u770b\u5668\u4e2d\u68c0\u67e5\u5bf9\u5e94\u7684\u70ed\u70b9\u4f4d\u7f6e\u3002"),
        (r"CTV V150 is ([0-9.]+)%; interpret uniformity with the current site-specific criteria\.",
         lambda match: f"CTV V150 \u4e3a {match.group(1)}%\uff0c\u8bf7\u6309\u5f53\u524d\u90e8\u4f4d\u7279\u5f02\u6027\u6807\u51c6\u5224\u65ad\u5747\u5300\u6027\u3002"),
        (r"Plan score is ([0-9.]+)/100; use it as an advisory ranking signal, not approval\.",
         lambda match: f"\u89c4\u5212\u8bc4\u5206\u4e3a {match.group(1)}/100\uff0c\u8be5\u5206\u6570\u4ec5\u7528\u4e8e\u8f85\u52a9\u6392\u5e8f\uff0c\u4e0d\u4ee3\u8868\u4e34\u5e8a\u6279\u51c6\u3002"),
        (r"(.+) \((.*)\) and (.+) \((.*)\): center distance ([0-9.]+) mm, surface clearance ([0-9.-]+) mm \[(.+)\]\.",
         lambda match: (
             f"\u7c92\u5b50 {match.group(1)}\uff08{match.group(2)}\uff09\u4e0e "
             f"{match.group(3)}\uff08{match.group(4)}\uff09\u7684\u4e2d\u5fc3\u8ddd\u79bb\u4e3a "
             f"{match.group(5)} mm\uff0c\u8868\u9762\u95f4\u9699\u4e3a {match.group(6)} mm"
             f"\uff08{match.group(7)}\uff09\u3002"
         )),
        (r"(.+) and (.+) are ([0-9.]+) mm apart \(minimum ([0-9.]+) mm; (.+)\)\.",
         lambda match: (
             f"\u9488\u9053 {match.group(1)} \u4e0e {match.group(2)} \u7684\u6700\u77ed\u8ddd\u79bb\u4e3a "
             f"{match.group(3)} mm\uff1b\u5f53\u524d\u914d\u7f6e\u7684\u6700\u5c0f\u8ddd\u79bb\u4e3a "
             f"{match.group(4)} mm\u3002"
         )),
    )
    for pattern, formatter in patterns:
        match = re.fullmatch(pattern, raw)
        if match:
            return formatter(match)
    if raw.startswith("Top OAR doses: "):
        return "OAR \u6700\u9ad8\u5242\u91cf\u7ed3\u6784\uff1a" + raw[len("Top OAR doses: "):]
    if raw.startswith("Needles intersecting current Data Tree non-traversable structures: "):
        names = raw[len("Needles intersecting current Data Tree non-traversable structures: "):].rstrip(".")
        return f"\u9488\u9053 {names} \u4e0e\u5f53\u524d Data Tree \u4e2d\u7684\u4e0d\u53ef\u7a7f\u523a\u7ed3\u6784\u76f8\u4ea4\u3002"
    if raw.startswith("Outdated dependent results: "):
        names = raw[len("Outdated dependent results: "):].rstrip(".")
        return f"\u624b\u52a8\u51e0\u4f55\u7f16\u8f91\u540e\uff0c\u89c4\u5212\u4ea7\u7269 {names} \u5df2\u8fc7\u671f\u3002"
    if raw.startswith("Needle edit recorded."):
        return "\u5df2\u8bb0\u5f55\u9488\u9053\u7f16\u8f91\u3002\u8bf7\u786e\u8ba4\u9488\u9053\u7ecf\u8fc7\u5b89\u5168\u7ec4\u7ec7\uff0c\u5e76\u4e0e\u4e0d\u53ef\u7a7f\u523a OAR \u4fdd\u6301\u8ddd\u79bb\u3002"
    if raw.startswith("Seed edit recorded."):
        return "\u5df2\u8bb0\u5f55\u7c92\u5b50\u7f16\u8f91\u3002\u8bf7\u91cd\u65b0\u8ba1\u7b97\u5242\u91cf\u5e76\u6838\u5bf9 DVH\uff0c\u518d\u653e\u7f6e\u4e0b\u4e00\u679a\u7c92\u5b50\u3002"
    return raw


def _monitor_activity_label_clean(key: str, language: str = "en") -> str:
    labels = {
        "planning.step": ("\u89c4\u5212\u6b65\u9aa4", "Planning steps"),
        "segmentation.step": ("\u5206\u5272\u6b65\u9aa4", "Segmentation steps"),
        "manual.needle.drag": ("\u624b\u52a8\u9488\u9053\u62d6\u62fd", "Manual needle drags"),
        "manual.needle.position_only": ("\u624b\u52a8\u9488\u9053\u4f4d\u7f6e\u8c03\u6574", "Manual needle position updates"),
        "manual.seed.drag": ("\u624b\u52a8\u7c92\u5b50\u62d6\u62fd", "Manual seed drags"),
        "manual.seed.add": ("\u624b\u52a8\u6dfb\u52a0\u7c92\u5b50", "Manual seed additions"),
        "manual.seed.delete": ("\u624b\u52a8\u5220\u9664\u7c92\u5b50", "Manual seed deletions"),
        "manual.dose": ("\u624b\u52a8\u5242\u91cf\u91cd\u7b97", "Manual dose updates"),
        "ui.panel": ("\u9762\u677f\u64cd\u4f5c", "Panel interactions"),
        "ui.click": ("\u70b9\u51fb\u64cd\u4f5c", "Click interactions"),
        "ui.change": ("\u63a7\u4ef6\u4fee\u6539", "Control changes"),
        "ui.slider": ("\u6ed1\u5757\u8c03\u6574", "Slider changes"),
        "training.start": ("\u76d1\u6d4b\u542f\u52a8", "Monitor starts"),
        "training.stop": ("\u76d1\u6d4b\u7ed3\u675f", "Monitor stops"),
    }
    pair = labels.get(key)
    if pair:
        return pair[0] if language == "zh" else pair[1]
    return (key.replace(".", " ").strip().title() or "\u5176\u4ed6\u4e8b\u4ef6") if language == "zh" else (key.replace(".", " ").strip().title() or "Other events")


def _format_training_summary_clean(events: list, counts: Dict[str, int], advice: Dict[str, Any], language: str = "en") -> str:
    if language == "zh":
        lines = ["## \u89c4\u5212\u76d1\u6d4b\u603b\u7ed3", f"\u672c\u6b21\u76d1\u6d4b\u8bb0\u5f55\u4e86 {len(events)} \u4e2a\u754c\u9762\u6216\u89c4\u5212\u4e8b\u4ef6\u3002"]
        headings = ("\u6d3b\u52a8\u6982\u89c8", "\u5f53\u524d\u4f18\u52bf", "\u9700\u8981\u5173\u6ce8", "\u5efa\u8bae")
    else:
        lines = ["## Planning monitoring summary", f"Recorded {len(events)} UI/planning events."]
        headings = ("Activity", "Strengths", "Issues", "Recommendations")
    if counts:
        lines.extend(["", f"### {headings[0]}"])
        for key, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]:
            lines.append(f"- {_monitor_activity_label_clean(key, language)}: {count}")
    advice = advice or {}
    for heading, key in zip(headings[1:], ("strengths", "issues", "advice")):
        values = advice.get(key) or []
        if values:
            lines.extend(["", f"### {heading}"])
            lines.extend(f"- {_localize_monitor_text_clean(value, language)}" for value in values)
    return "\n".join(lines)


def _training_feedback_for_event_clean(agent, session_id: Optional[str], event: Dict[str, Any]) -> Optional[str]:
    event_type = str(event.get("type", ""))
    detail = _monitor_event_detail(event)
    language = _monitor_language(event.get("language") or detail.get("language"))
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    d90 = _extract_metric_value(metrics, "d90")
    target = _source_backed_target_context(agent).get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(target, "v100_min"))
    if event_type.startswith("manual.seed"):
        interference = snapshot.get("seed_interference") or {}
        if interference.get("status") == "attention":
            pairs = list(interference.get("close_pairs") or [])
            worst = min(
                pairs,
                key=lambda pair: float(pair.get("surface_clearance_mm") or 0.0),
            )
            if language == "zh":
                return (
                    f"已记录粒子编辑。检测到 {len(pairs)} 组粒子违反物理间距要求；"
                    f"最严重的是 {worst.get('first_id')} 与 {worst.get('second_id')}，"
                    f"表面间隙为 {float(worst.get('surface_clearance_mm') or 0.0):.2f} mm。"
                    "已准备对应的 3D 特写，请先调整间距再继续。"
                )
            return (
                f"Seed edit recorded. {len(pairs)} pair(s) violate the physical spacing rule; "
                f"the worst pair is {worst.get('first_id')} and {worst.get('second_id')} "
                f"with {float(worst.get('surface_clearance_mm') or 0.0):.2f} mm surface clearance. "
                "A focused 3D checkpoint is ready; correct the spacing before continuing."
            )
        if v100 is not None and v100_min is not None and v100 < v100_min:
            return _localize_monitor_text_clean(
                f"Seed edit recorded. Current V100 is {v100 * 100:.1f}%; inspect cold CTV regions after recompute.",
                language,
            )
        return _localize_monitor_text_clean("Seed edit recorded. Recompute dose and verify DVH before placing the next seed.", language)
    if event_type.startswith("manual.needle"):
        needle_geometry = snapshot.get("needle_geometry") or {}
        obstacle_hits = list(needle_geometry.get("obstacle_hits") or [])
        if obstacle_hits:
            names = ", ".join(obstacle_hits[:12])
            if language == "zh":
                return f"针道编辑已记录。针道 {names} 与当前 Data Tree 中的不可穿刺结构相交，请先修正路径。"
            return (
                f"Needle edit recorded. {names} intersect the current Data Tree "
                "non-traversable structures; correct these paths before continuing."
            )
        close_pairs = list(needle_geometry.get("close_pairs") or [])
        if close_pairs:
            worst = min(close_pairs, key=lambda pair: float(pair.get("distance_mm") or 0.0))
            if language == "zh":
                return (
                    f"针道编辑已记录。{worst.get('first_id')} 与 {worst.get('second_id')} "
                    f"的最短距离为 {float(worst.get('distance_mm') or 0.0):.2f} mm，"
                    f"低于要求的 {float(worst.get('minimum_distance_mm') or 0.0):.2f} mm。"
                )
            return (
                f"Needle edit recorded. {worst.get('first_id')} and {worst.get('second_id')} "
                f"are {float(worst.get('distance_mm') or 0.0):.2f} mm apart, below the "
                f"{float(worst.get('minimum_distance_mm') or 0.0):.2f} mm minimum."
            )
        return _localize_monitor_text_clean(
            "Needle edit recorded. Check that the path traverses safe tissue and keeps distance from non-traversable OARs.",
            language,
        )
    if event_type in {"planning.step", "segmentation.step"}:
        stage = _monitor_step_label_clean(_monitor_step_key(event), language)
        status = _monitor_event_status(event)
        if status == "running":
            return f"{stage} \u6b63\u5728\u6267\u884c\uff1b\u5b8c\u6210\u540e\u6211\u4f1a\u6838\u5bf9 Data Tree \u548c viewer \u8f93\u51fa\u3002" if language == "zh" else f"{stage} is running; I will verify the Data Tree and viewer output when it finishes."
        if status == "done":
            return f"{stage} \u5df2\u5b8c\u6210\uff1b\u8bf7\u5148\u6838\u5bf9 Data Tree \u548c viewer \u8f93\u51fa\uff0c\u518d\u7ee7\u7eed\u4e0b\u4e00\u6b65\u3002" if language == "zh" else f"{stage} completed; verify the Data Tree and viewer output before the next prerequisite step."
        if status == "error":
            return f"{stage} \u6267\u884c\u5931\u8d25\uff1b\u8bf7\u68c0\u67e5\u9519\u8bef\u8be6\u60c5\u5e76\u786e\u8ba4\u8f93\u5165\u6570\u636e\u3002" if language == "zh" else f"{stage} failed; inspect the error details and confirm the input data."
        return f"\u5df2\u8bb0\u5f55 {stage} \u4e8b\u4ef6\uff1b\u8bf7\u6838\u5bf9 Data Tree \u8f93\u51fa\u3002" if language == "zh" else f"{stage} event recorded; verify its Data Tree output."
    if event_type == "manual.dose":
        if v100 is not None and d90 is not None:
            return _localize_monitor_text_clean(
                f"Dose preview updated: V100={v100 * 100:.1f}%, D90={d90:.1f} Gy. Review hot spots and OAR dose before adding seeds.",
                language,
            )
        return _localize_monitor_text_clean("Dose preview updated. Open Analysis to inspect DVH and OAR dose.", language)
    return None


def _training_screenshot_for_event_clean(agent, session_id: Optional[str], event: Dict[str, Any], feedback: Optional[str]) -> Optional[Dict[str, Any]]:
    if not feedback:
        return None
    event_type = str(event.get("type", ""))
    detail = _monitor_event_detail(event)
    language = _monitor_language(event.get("language") or detail.get("language"))
    if event_type in {"planning.step", "segmentation.step"} and _monitor_event_status(event) != "done":
        return None
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    v200 = _volume_metric_as_fraction(metrics, "v200")
    criteria = _source_backed_target_context(agent).get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(criteria, "v100_min"))
    v200_max = _metric_as_fraction(_extract_metric_value(criteria, "v200_max"))
    focus_ids = []
    for pair in (snapshot.get("seed_interference", {}) or {}).get("close_pairs", [])[:4]:
        for key in ("first_id", "second_id"):
            seed_id = str(pair.get(key) or "").strip()
            if seed_id and seed_id not in focus_ids:
                focus_ids.append(seed_id)
    def question(zh: str, en: str) -> str:
        return zh if language == "zh" else en
    if event_type == "manual.dose":
        concern = (v100 is not None and v100_min is not None and v100 < v100_min) or (v200 is not None and v200_max is not None and v200 > v200_max)
        result = {
            "target": "dose-overview" if concern else "dvh",
            "question": question(
                "\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u624b\u52a8\u5242\u91cf\u91cd\u7b97\u540e\u7684 CT\u3001\u63a9\u819c\u3001\u5242\u91cf\u70ed\u56fe\u3001\u7c92\u5b50\u3001\u9488\u9053\u548c DVH\u3002" if concern else "\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u624b\u52a8\u5242\u91cf\u91cd\u7b97\u540e\u7684 DVH\u3002",
                "Training monitor snapshot: show the CT, masks, dose heatmap, seeds/needles, and DVH after manual dose recomputation." if concern else "Training monitor snapshot: show the updated DVH after manual dose recomputation.",
            ),
        }
        if focus_ids:
            result["focus_seed_ids"] = focus_ids
        return result
    if event_type == "segmentation.step":
        return {"target": "viewer-3d", "question": question("\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u65b0\u52a0\u8f7d\u7684 CTV/OAR \u7ed3\u6784\u3001 3D \u67e5\u770b\u5668\u548c Data Tree\u3002", "Training monitor snapshot: show the newly loaded CTV/OAR structures in the 3D viewer and Data Tree.")}
    if event_type == "planning.step":
        key = _monitor_step_key(event)
        if key in {"trajectory_init", "trajectory_refine", "seed_planning"}:
            stage = _monitor_step_label_clean(key, language)
            return {"target": "viewer-3d", "question": question(f"\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a {stage} \u5b8c\u6210\u540e\u7684 3D \u67e5\u770b\u5668\u3001\u9488\u9053\u3001\u7c92\u5b50\u548c Data Tree\u3002", f"Training monitor snapshot: show the 3D viewer, needle/seed output, and Data Tree after {_monitor_step_label_clean(key)}.")}
        if key in {"dose_calc", "dose_eval", "full"}:
            return {"target": "dose-overview", "question": question("\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u89c4\u5212\u5b8c\u6210\u540e\u7684\u5242\u91cf\u5206\u5e03\u548c DVH\u3002", "Training monitor snapshot: show the completed plan dose distribution and DVH for review.")}
        return None
    if event_type.startswith("manual.needle"):
        return {"target": "viewer-3d", "question": question("\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u5f53\u524d 3D \u9488\u9053\u548c\u9644\u8fd1\u7684\u89e3\u5256\u7ed3\u6784\u3002", "Training monitor snapshot: show the current 3D needle path and nearby anatomy.")}
    if event_type.startswith("manual.seed"):
        result = {"target": "viewer-3d", "question": question("\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u88ab\u7f16\u8f91\u7684\u7c92\u5b50\u53ca\u5176\u90bb\u8fd1\u7c92\u5b50\uff0c\u7528\u4e8e\u68c0\u67e5\u95f4\u8ddd\u3002", "Training monitor snapshot: show the edited seed and nearby seeds so spacing can be checked.")}
        if focus_ids:
            result["focus_seed_ids"] = focus_ids
        return result
    return None


_monitor_step_label = _monitor_step_label_clean
_localize_monitor_text = _localize_monitor_text_clean
_monitor_activity_label = _monitor_activity_label_clean
_format_training_summary = _format_training_summary_clean
_training_feedback_for_event = _training_feedback_for_event_clean
_training_screenshot_for_event = _training_screenshot_for_event_clean


# Public support surface. Route modules import private helpers explicitly via
# the module object, so wildcard imports never expose leading-underscore names.
__all__ = [
    "ALLOWED_DICOM_SERIES_EXTENSIONS",
    "ALLOWED_UPLOAD_EXTENSIONS",
    "API_KEY",
    "APP_DIR",
    "DOSE_MODEL_SCALE_GY",
    "DOSE_MODEL_UNITS",
    "MAX_SCREENSHOT_BYTES",
    "MAX_UPLOAD_FILES",
    "OUTPUT_DIRS",
    "PROJECT_ROOT",
    "RATE_LIMIT_REQUESTS",
    "RATE_LIMIT_WINDOW",
    "RUNTIME_DIR",
    "SCREENSHOTS_DIR",
    "TRUE_VALUES",
    "TaskManager",
    "UPLOAD_DIR",
    "WEB_DIR",
    "logger",
    "rate_limit",
    "require_api_key",
    "task_manager",
]
