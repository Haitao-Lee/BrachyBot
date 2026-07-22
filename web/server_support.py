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


def _latest_plan_snapshot(agent) -> Dict[str, Any]:
    if agent is None or not hasattr(agent, "memory"):
        return {}
    metrics = agent.memory.retrieve("dose_metrics") or agent.memory.retrieve("metrics") or {}
    if isinstance(metrics, dict) and "metrics" in metrics and isinstance(metrics["metrics"], dict):
        metrics = metrics["metrics"]
    total_seeds = agent.memory.retrieve("total_seeds") or 0
    num_trajectories = agent.memory.retrieve("num_trajectories") or 0
    return {
        "metrics": metrics if isinstance(metrics, dict) else {},
        "total_seeds": int(total_seeds or 0),
        "num_trajectories": int(num_trajectories or 0),
        "has_dose": agent.memory.retrieve("dose_distribution") is not None
            or agent.memory.retrieve("dose_distribution_gy") is not None,
        "manual_preview": bool(agent.memory.retrieve("manual_planning_preview")),
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
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    d90 = _extract_metric_value(metrics, "d90")
    target_context = _source_backed_target_context(agent)
    target_criteria = target_context.get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(target_criteria, "v100_min"))

    if etype.startswith("manual.seed"):
        if v100 is not None and v100_min is not None and v100 < v100_min:
            return f"Seed edit recorded. Current V100 is {v100 * 100:.1f}%; inspect cold CTV regions after recompute."
        return "Seed edit recorded. Recompute dose and verify DVH before placing the next seed."
    if etype.startswith("manual.needle"):
        return "Needle edit recorded. Check that the path traverses safe tissue and keeps distance from non-traversable OARs."
    if etype in {"planning.step", "segmentation.step"}:
        return f"{label or etype} recorded. Continue with the next prerequisite step and verify outputs in the data tree."
    if etype == "manual.dose":
        if v100 is not None and d90 is not None:
            return f"Dose preview updated: V100={v100 * 100:.1f}%, D90={d90:.1f} Gy. Review hot spots and OAR dose before adding seeds."
        return "Dose preview updated. Open Analysis to inspect DVH and OAR dose."
    return None


def _training_screenshot_for_event(agent, session_id: Optional[str], event: Dict[str, Any], feedback: Optional[str]) -> Optional[Dict[str, str]]:
    """Suggest a screenshot target for high-value training checkpoints."""
    if not feedback:
        return None
    etype = str(event.get("type", ""))
    label = str(event.get("label", ""))
    snapshot = _latest_plan_snapshot(agent)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = _volume_metric_as_fraction(metrics, "v100")
    v200 = _volume_metric_as_fraction(metrics, "v200")
    target_criteria = _source_backed_target_context(agent).get("criteria", {})
    v100_min = _metric_as_fraction(_extract_metric_value(target_criteria, "v100_min"))
    v200_max = _metric_as_fraction(_extract_metric_value(target_criteria, "v200_max"))

    if etype == "manual.dose":
        source_backed_concern = (
            v100 is not None and v100_min is not None and v100 < v100_min
        ) or (
            v200 is not None and v200_max is not None and v200 > v200_max
        )
        if source_backed_concern:
            return {
                "target": "dose-overview",
                "question": "Training monitor snapshot: show current CT, masks, dose heatmap, seeds/needles, and DVH after manual dose recomputation.",
            }
        return {
            "target": "dvh",
            "question": "Training monitor snapshot: show the updated DVH after manual dose recomputation.",
        }

    if etype == "planning.step" and ("completed" in label.lower() or "full pipeline completed" in label.lower()):
        return {
            "target": "dose-overview",
            "question": "Training monitor snapshot: show the completed plan dose distribution and DVH for review.",
        }

    if etype.startswith("manual.needle"):
        return {
            "target": "viewer-3d",
            "question": "Training monitor snapshot: show the current 3D needle path and nearby anatomy.",
        }

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

    updated = []
    changed = 0
    for seed in seeds or []:
        if not isinstance(seed, dict):
            updated.append(seed)
            continue
        trajectory_id = str(seed.get("trajectory_id") or "")
        old_line = old_by_traj.get(trajectory_id)
        new_line = new_by_traj.get(trajectory_id)
        if old_line is None or new_line is None:
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

    norm_seeds = []
    model_seeds = []
    size_xyz = np.asarray(resampled_ct.GetSize(), dtype=np.float64)
    for i, seed in enumerate(seeds or []):
        pos = _safe_float_list(seed.get("position") if isinstance(seed, dict) else None, 3)
        direction = _safe_float_list((seed.get("direction") if isinstance(seed, dict) else None), 3, [0.0, 0.0, 1.0])
        direction_np = np.asarray(direction, dtype=np.float64)
        dn = float(np.linalg.norm(direction_np))
        if dn <= 1e-8 or not np.all(np.isfinite(direction_np)):
            direction_np = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        else:
            direction_np = direction_np / dn
        seed_id = str(seed.get("id") if isinstance(seed, dict) and seed.get("id") else f"manual_seed_{i + 1}")
        traj_id = str(seed.get("trajectory_id") if isinstance(seed, dict) and seed.get("trajectory_id") else "manual_traj_1")

        try:
            idx_xyz = np.asarray(
                resampled_ct.TransformPhysicalPointToContinuousIndex(tuple(float(v) for v in pos)),
                dtype=np.float64,
            )
        except Exception as exc:
            logger.warning("Skipping seed with invalid physical coordinate transform: %s", exc)
            continue
        if not np.all(np.isfinite(idx_xyz)) or np.any(idx_xyz < 0.0) or np.any(idx_xyz >= size_xyz):
            continue

        try:
            voxel_direction = utilizations.ras_direction_to_voxel(direction_np, resampled_ct).astype(np.float32)
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
        model_seeds.append((pos_zyx, voxel_direction.astype(np.float32), seed_weight))
        norm_seeds.append({
            "id": seed_id,
            "position": pos,
            "direction": direction_np.astype(np.float32).tolist(),
            "trajectory_id": traj_id,
            "weight": seed_weight,
        })

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
    cached_maps = []
    missing_seeds = []
    missing_indices = []
    for index, (seed, model_seed) in enumerate(zip(norm_seeds, model_seeds)):
        position_key = tuple(round(float(v), 4) for v in seed["position"])
        direction_key = tuple(round(float(v), 5) for v in seed["direction"])
        cache_key = (dose_signature, position_key, direction_key, round(float(seed["weight"]), 5))
        cached = _MANUAL_DOSE_SEED_CACHE.get(cache_key)
        if cached is None:
            cached_maps.append(None)
            missing_seeds.append(model_seed)
            missing_indices.append(index)
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
        )
        for index, cache_key, seed_dose in zip(
            missing_indices,
            [
                (
                    dose_signature,
                    tuple(round(float(v), 4) for v in norm_seeds[i]["position"]),
                    tuple(round(float(v), 5) for v in norm_seeds[i]["direction"]),
                    round(float(norm_seeds[i]["weight"]), 5),
                )
                for i in missing_indices
            ],
            computed_maps,
        ):
            array = np.asarray(seed_dose, dtype=np.float32).copy()
            _MANUAL_DOSE_SEED_CACHE[cache_key] = array
            _MANUAL_DOSE_SEED_CACHE_ORDER.append(cache_key)
            cached_maps[index] = array
        while len(_MANUAL_DOSE_SEED_CACHE_ORDER) > _MANUAL_DOSE_SEED_CACHE_LIMIT:
            stale_key = _MANUAL_DOSE_SEED_CACHE_ORDER.pop(0)
            _MANUAL_DOSE_SEED_CACHE.pop(stale_key, None)
    per_seed_doses = [np.asarray(item, dtype=np.float32) for item in cached_maps if item is not None]
    dose = np.zeros_like(sitk.GetArrayFromImage(dose_image), dtype=np.float32)
    for seed_dose in per_seed_doses:
        dose += np.asarray(seed_dose, dtype=np.float32)
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

    return {
        "success": True,
        "manual_preview": True,
        "dose_engine": "dose_unet_spacing1mm",
        "total_seeds": len(norm_seeds),
        "num_trajectories": len(grouped),
        "reprojected_seeds": int(reprojection_count),
        "metrics": metrics,
        "dose_range": [float(dose_original.min()), float(dose_original.max())],
        "dose_range_normalized": [float(dose_original.min()), float(dose_original.max())],
        "dose_range_gy": [float(dose_gy.min()), float(dose_gy.max())],
        "dose_units": DOSE_MODEL_UNITS,
        "dose_scale_gy": DOSE_MODEL_SCALE_GY,
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
