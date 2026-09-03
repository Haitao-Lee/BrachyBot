"""Best-effort transport for ephemeral planning geometry previews.

The objects described by this module are deliberately outside the clinical
planning state.  They are sampled visual observations of an algorithm that is
already running; they are never inputs to dose calculation, never persisted in
the workspace, and never authoritative enough to appear in the Data Tree.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable, Dict, Iterable, Optional


logger = logging.getLogger(__name__)

PREVIEW_SCHEMA_VERSION = 1
MAX_PREVIEW_TRAJECTORIES = 64
MAX_PREVIEW_NEEDLES = 32
MAX_PREVIEW_SEEDS = 256


def safe_preview(callback: Optional[Callable[[Dict[str, Any]], None]], payload: Dict[str, Any]) -> None:
    """Invoke an algorithm observer without letting it affect the algorithm."""
    if not callable(callback):
        return
    try:
        callback(payload)
    except Exception:
        # Preview is an observability side channel.  A closed SSE connection,
        # stale browser, or malformed optional frame must never fail planning.
        logger.debug("Planning preview observer failed", exc_info=True)


def _finite_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 3) if math.isfinite(number) else None


def _point(value: Any) -> Optional[list[float]]:
    try:
        values = list(value)
    except (TypeError, ValueError):
        return None
    if len(values) < 3:
        return None
    point = [_finite_number(values[index]) for index in range(3)]
    return point if all(number is not None for number in point) else None


def _bounded_geometry(geometry: Any) -> Dict[str, list]:
    source = geometry if isinstance(geometry, dict) else {}
    result: Dict[str, list] = {"trajectories": [], "needles": [], "seeds": []}

    for key, limit in (
        ("trajectories", MAX_PREVIEW_TRAJECTORIES),
        ("needles", MAX_PREVIEW_NEEDLES),
    ):
        values = source.get(key)
        if not isinstance(values, Iterable) or isinstance(values, (str, bytes, dict)):
            continue
        for index, item in enumerate(values):
            if index >= limit:
                break
            item = item if isinstance(item, dict) else {"points": item}
            points = item.get("points")
            if not isinstance(points, Iterable) or isinstance(points, (str, bytes, dict)):
                continue
            normalized_points = []
            for value in points:
                normalized = _point(value)
                if normalized is not None:
                    normalized_points.append(normalized)
            if len(normalized_points) < 2:
                continue
            result[key].append({
                "id": str(item.get("id") or f"preview_{key}_{index}"),
                "points": normalized_points,
                "status": str(item.get("status") or "candidate"),
            })

    seeds = source.get("seeds")
    if isinstance(seeds, Iterable) and not isinstance(seeds, (str, bytes, dict)):
        for index, item in enumerate(seeds):
            if index >= MAX_PREVIEW_SEEDS:
                break
            item = item if isinstance(item, dict) else {}
            position = _point(item.get("position"))
            direction = _point(item.get("direction") or (0.0, 0.0, 1.0))
            if position is None or direction is None:
                continue
            result["seeds"].append({
                "id": str(item.get("id") or f"preview_seed_{index}"),
                "trajectory_id": str(item.get("trajectory_id") or ""),
                "position": position,
                "direction": direction,
                "status": str(item.get("status") or "candidate"),
            })
    return result


class PlanningPreviewEmitter:
    """Rate-limited lifecycle emitter for one non-persistent Planning run."""

    def __init__(
        self,
        callback: Optional[Callable[[Dict[str, Any]], None]],
        *,
        session_id: str,
        planning_id: str,
        min_frame_interval: float = 0.20,
    ) -> None:
        self._callback = callback if callable(callback) else None
        self.session_id = str(session_id or "")
        self.planning_id = str(planning_id or "")
        self.run_id = self.planning_id
        self.min_frame_interval = max(0.05, float(min_frame_interval))
        self.sequence = 0
        self.stage = ""
        self._last_frame_at = 0.0
        self._closed = False

    @property
    def enabled(self) -> bool:
        return self._callback is not None and not self._closed

    def _emit(self, action: str, **payload: Any) -> None:
        if not self.enabled:
            return
        self.sequence += 1
        event = {
            "schema_version": PREVIEW_SCHEMA_VERSION,
            "type": "planning_preview",
            "action": str(action),
            "session_id": self.session_id,
            "planning_id": self.planning_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "stage": str(payload.pop("stage", None) or self.stage or "planning"),
            "ephemeral": True,
            "editable": False,
            "persistent": False,
            **payload,
        }
        safe_preview(self._callback, event)

    def start(self, stage: str, *, phase: str = "", detail: str = "") -> None:
        if not self.enabled:
            return
        if self.stage and self.stage != str(stage):
            self.complete(self.stage, status="superseded")
        self.stage = str(stage)
        self._last_frame_at = 0.0
        self._emit("start", stage=self.stage, phase=str(phase), detail=str(detail))

    def frame(
        self,
        geometry: Dict[str, Any],
        *,
        stage: Optional[str] = None,
        phase: str = "",
        detail: str = "",
        progress: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> bool:
        if not self.enabled:
            return False
        now = time.monotonic()
        if not force and now - self._last_frame_at < self.min_frame_interval:
            return False
        self._last_frame_at = now
        self._emit(
            "frame",
            stage=str(stage or self.stage or "planning"),
            phase=str(phase),
            detail=str(detail),
            progress=dict(progress or {}),
            geometry=_bounded_geometry(geometry),
        )
        return True

    def complete(self, stage: Optional[str] = None, *, status: str = "done", detail: str = "") -> None:
        if not self.enabled:
            return
        completed_stage = str(stage or self.stage or "planning")
        self._emit("complete", stage=completed_stage, status=str(status), detail=str(detail))
        if completed_stage == self.stage:
            self.stage = ""

    def cleanup(self, reason: str = "finished") -> None:
        if not self.enabled:
            return
        self._emit("cleanup", stage=self.stage or "planning", reason=str(reason))
        self._closed = True

