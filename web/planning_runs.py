"""Session-scoped planning run history.

The clinical runtime historically exposed one mutable ``planning_results``
mapping.  This module adds an additive compatibility layer: the active plan
continues to use those keys, while every completed or in-progress planning
run also gets an immutable, namespaced snapshot under
``planning_run:<planning_id>``.  Large arrays are deliberately kept in the
same memory/persistence pipeline as the existing result keys so the workspace
store can encode them as owned sidecars.

The module has no Flask dependency.  It can therefore be used by the tool
runtime, HTTP routes, and tests without introducing a web/runtime cycle.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

try:  # NumPy is already a runtime dependency, but keep imports test-friendly.
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # type: ignore


PLANNING_RUNS_KEY = "planning_runs"
ACTIVE_PLANNING_ID_KEY = "active_planning_id"
PLANNING_RUN_ID_KEY = "planning_run_id"
PLANNING_RUN_PREFIX = "planning_run:"

# Results that describe the previous geometry must not remain active after a
# manual edit.  The parent run keeps the immutable copy; the child starts with
# geometry only and receives fresh dose/DVH/guide data after recomputation.
STALE_PLANNING_VALUE_KEYS = (
    "dose_distribution",
    "dose_distribution_gy",
    "dose_distribution_physical_gy",
    "dose_metrics",
    "metrics",
    "dvh_data",
    "surgical_guide",
)

# These are plan-owned values.  CT and segmentation inputs remain shared by a
# session and are intentionally not copied into every planning run.
PLANNING_VALUE_KEYS = (
    "trajectories",
    "refined_trajectories",
    "seed_plan",
    "seed_plan_serialized",
    "seed_positions",
    "verified_needle_geometry",
    "dose_distribution",
    "algorithm_plan_dose_distribution",
    "dose_distribution_gy",
    "algorithm_plan_dose_distribution_gy",
    "dose_metrics",
    "algorithm_plan_dose_metrics",
    "algorithm_plan_dvh_data",
    "dvh_data",
    "total_seeds",
    "num_trajectories",
    "plan_config",
    "dose_units",
    "dose_scale_gy",
    "radiation_volume",
    # Resampled CT grids are recreated from the session CT/masks when needed;
    # duplicating them into every historical run would multiply storage and
    # checkpoint time for little restore value.
    "obstacle_label_ids",
    "obstacle_label_source",
    "ref_direc_voxel",
    "algorithm_plan_snapshot",
    "manual_seeds",
    "manual_needles",
    "manual_plan_active",
    "manual_plan_version",
    "manual_geometry_only",
    "manual_planning_id",
    "manual_plan_serialized",
    "manual_planning_preview",
    "manual_ai_dose",
    "manual_artifact_status",
    "dose_distribution_physical_gy",
    "dose_engine",
    "metrics",
    "surgical_guide",
    "surgical_guide_versions",
    "skin_surface",
    "skin_surface_mask",
    "artifact_status",
)


def _now() -> float:
    return time.time()


def _clone(value: Any) -> Any:
    """Clone plan data without sharing mutable arrays with a later run."""
    if np is not None and isinstance(value, np.ndarray):
        return np.array(value, copy=True)
    if isinstance(value, Mapping):
        return {str(key): _clone(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clone(item) for item in value)
    # SimpleITK images and other runtime handles are not plan artifacts.  A
    # defensive deepcopy is useful for ordinary dataclasses and scalars, but
    # a non-copyable object is omitted rather than making a replan fail.
    try:
        return copy.deepcopy(value)
    except Exception:
        return None


def _memory_put(memory: Any, key: str, value: Any) -> None:
    """Update memory once without scheduling one checkpoint per field."""
    with memory._lock:
        memory.planning_results[key] = value
        versions = getattr(memory, "_planning_versions", {})
        versions[key] = int(versions.get(key, 0)) + 1
        available = set(memory.conversation_state.get("data_available", []))
        if value is None:
            available.discard(key)
        else:
            available.add(key)
        memory.conversation_state["data_available"] = sorted(available)


def _memory_delete(memory: Any, key: str) -> None:
    with memory._lock:
        memory.planning_results.pop(key, None)
        versions = getattr(memory, "_planning_versions", {})
        versions[key] = int(versions.get(key, 0)) + 1
        available = set(memory.conversation_state.get("data_available", []))
        available.discard(key)
        memory.conversation_state["data_available"] = sorted(available)


def _notify(memory: Any, reason: str) -> None:
    try:
        memory._notify_persistence(reason)
    except Exception:
        pass


def _raw_runs(memory: Any) -> List[Dict[str, Any]]:
    raw = memory.retrieve(PLANNING_RUNS_KEY) or []
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping) and item.get("planning_id")]


def _write_runs(memory: Any, runs: Iterable[Mapping[str, Any]], *, reason: str) -> None:
    normalized = [dict(item) for item in runs if isinstance(item, Mapping)]
    normalized.sort(key=lambda item: int(item.get("sequence") or 0))
    _memory_put(memory, PLANNING_RUNS_KEY, normalized)
    _notify(memory, reason)


def _has_current_plan(memory: Any) -> bool:
    return any(memory.retrieve(key) is not None for key in PLANNING_VALUE_KEYS if key not in {
        "manual_plan_active", "manual_geometry_only", "artifact_status",
    })


def _capture_current(memory: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key in PLANNING_VALUE_KEYS:
        value = memory.retrieve(key)
        if value is not None:
            cloned = _clone(value)
            if cloned is not None:
                result[key] = cloned
    return result


def _clear_active_plan(memory: Any) -> None:
    """Clear mutable plan aliases before a genuinely new run starts.

    CT and segmentation inputs are deliberately outside ``PLANNING_VALUE_KEYS``
    and therefore survive.  Without this boundary a failed or partial replan
    could inherit the previous run's guide, dose, or seeds and publish a
    deceptively mixed snapshot under the new Planning ID.
    """
    with memory._lock:
        for key in PLANNING_VALUE_KEYS:
            if key in memory.planning_results:
                memory.planning_results.pop(key, None)
                versions = getattr(memory, "_planning_versions", {})
                versions[key] = int(versions.get(key, 0)) + 1
        available = set(memory.conversation_state.get("data_available", []))
        available.difference_update(PLANNING_VALUE_KEYS)
        memory.conversation_state["data_available"] = sorted(available)


def _run_summary(run: Mapping[str, Any]) -> Dict[str, Any]:
    """Return only compact metadata suitable for Data Tree and API lists."""
    return {
        "planning_id": str(run.get("planning_id") or ""),
        "sequence": int(run.get("sequence") or 0),
        "label": str(run.get("label") or f"Planning_{int(run.get('sequence') or 0)}"),
        "status": str(run.get("status") or "unknown"),
        "visible": bool(run.get("visible", False)),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "parent_planning_id": run.get("parent_planning_id"),
        "input_revision": run.get("input_revision") or {},
        "data_version": int(run.get("data_version") or 0),
        "total_seeds": int(run.get("total_seeds") or 0),
        "num_trajectories": int(run.get("num_trajectories") or 0),
        "has_dose": bool(run.get("has_dose")),
        "has_dvh": bool(run.get("has_dvh")),
        "has_guide": bool(run.get("has_guide")),
        "error": run.get("error"),
    }


def ensure_planning_history(memory: Any) -> List[Dict[str, Any]]:
    """Migrate a legacy single-plan memory into ``Planning_0`` lazily."""
    runs = _raw_runs(memory)
    if runs:
        # Older registry records may predate the visibility field. The active
        # alias is authoritative; normalize the presentation hint once so a
        # restart cannot show multiple runs or none of them.
        active = str(
            memory.retrieve(ACTIVE_PLANNING_ID_KEY)
            or memory.retrieve(PLANNING_RUN_ID_KEY)
            or ""
        )
        if active not in {str(item.get("planning_id")) for item in runs}:
            active = str(runs[-1].get("planning_id") or "")
            if active:
                _memory_put(memory, ACTIVE_PLANNING_ID_KEY, active)
                _memory_put(memory, PLANNING_RUN_ID_KEY, active)
        changed = False
        normalized = []
        for item in runs:
            visible = str(item.get("planning_id") or "") == active
            if item.get("visible") is not visible:
                item = {**item, "visible": visible}
                changed = True
            normalized.append(item)
        if changed:
            _write_runs(memory, normalized, reason="planning.history.visibility.migrated")
            runs = normalized
        return runs
    if not _has_current_plan(memory):
        return []
    planning_id = "planning-legacy-0"
    snapshot = _capture_current(memory)
    _memory_put(memory, PLANNING_RUN_PREFIX + planning_id, snapshot)
    run = {
        "planning_id": planning_id,
        "sequence": 0,
        "label": "Planning_0",
        "status": "completed",
        "legacy": True,
        "visible": True,
        "created_at": _now(),
        "updated_at": _now(),
        "data_version": int(memory.retrieve("manual_plan_version") or 1),
        "total_seeds": int(memory.retrieve("total_seeds") or len(memory.retrieve("manual_seeds") or [])),
        "num_trajectories": int(memory.retrieve("num_trajectories") or len(memory.retrieve("trajectories") or [])),
        "has_dose": memory.retrieve("dose_distribution_gy") is not None or memory.retrieve("dose_distribution") is not None,
        "has_dvh": bool(memory.retrieve("dose_metrics") or memory.retrieve("dvh_data")),
        "has_guide": bool(memory.retrieve("surgical_guide")),
    }
    _write_runs(memory, [run], reason="planning.history.migrated")
    _memory_put(memory, ACTIVE_PLANNING_ID_KEY, planning_id)
    _memory_put(memory, PLANNING_RUN_ID_KEY, planning_id)
    _notify(memory, "planning.history.active")
    return [run]


def active_planning_id(memory: Any) -> Optional[str]:
    value = memory.retrieve(ACTIVE_PLANNING_ID_KEY) or memory.retrieve(PLANNING_RUN_ID_KEY)
    if value:
        return str(value)
    runs = ensure_planning_history(memory)
    return str(runs[-1]["planning_id"]) if runs else None


def list_planning_runs(memory: Any) -> List[Dict[str, Any]]:
    return [_run_summary(run) for run in ensure_planning_history(memory)]


def _find_run(memory: Any, planning_id: str) -> Optional[Dict[str, Any]]:
    target = str(planning_id or "")
    return next((run for run in ensure_planning_history(memory) if str(run.get("planning_id")) == target), None)


def begin_planning_run(
    agent: Any,
    *,
    step: str = "full",
    force_new: bool = False,
    input_revision: Optional[Mapping[str, Any]] = None,
) -> str:
    """Reserve a run before planning writes its mutable active aliases."""
    memory = agent.memory
    runs = ensure_planning_history(memory)
    active = active_planning_id(memory)
    active_run = _find_run(memory, active) if active else None
    if (
        not force_new
        and step != "full"
        and active_run
        and str(active_run.get("status")) in {"running", "draft"}
    ):
        return str(active_run["planning_id"])

    _clear_active_plan(memory)
    sequence = max((int(run.get("sequence") or 0) for run in runs), default=-1) + 1
    planning_id = f"planning-{uuid4().hex}"
    now = _now()
    run = {
        "planning_id": planning_id,
        "sequence": sequence,
        "label": f"Planning_{sequence}",
        "status": "running",
        "visible": True,
        "created_at": now,
        "updated_at": now,
        "parent_planning_id": active,
        "input_revision": dict(input_revision or {}),
        "data_version": 1,
    }
    # Visibility is a persisted presentation hint, not the source of truth
    # for activation.  Keep it in the registry so a restart paints the same
    # active Planning group before the large clinical arrays are decoded.
    for existing in runs:
        existing["visible"] = False
    _memory_put(memory, ACTIVE_PLANNING_ID_KEY, planning_id)
    _memory_put(memory, PLANNING_RUN_ID_KEY, planning_id)
    _write_runs(memory, [*runs, run], reason="planning.run.started")
    return planning_id


def fork_planning_run(agent: Any, *, reason: str = "manual_edit") -> str:
    """Create an editable child run without changing the completed parent.

    Manual geometry edits are allowed to continue within a single draft. The
    first edit after a completed automatic/manual plan copies the active
    snapshot, switches the mutable aliases to the child ID, and marks the
    parent hidden. The copy happens before the edit is applied, so the parent
    remains a true restore point rather than a stale label in the tree.
    """
    memory = agent.memory
    runs = ensure_planning_history(memory)
    active = active_planning_id(memory)
    active_run = _find_run(memory, active) if active else None
    if active_run and str(active_run.get("status")) in {"running", "draft"}:
        _memory_put(memory, "manual_planning_id", str(active))
        return str(active)

    parent_snapshot = _capture_current(memory)
    sequence = max((int(item.get("sequence") or 0) for item in runs), default=-1) + 1
    planning_id = f"planning-{uuid4().hex}"
    now = _now()
    # The mutable manual planning ID must point at the child inside the child
    # snapshot as well; otherwise restoring the child would resurrect the
    # parent's ID and the next edit could attach to the wrong run.
    parent_snapshot["manual_planning_id"] = planning_id
    run = {
        "planning_id": planning_id,
        "sequence": sequence,
        "label": f"Planning_{sequence}",
        "status": "draft",
        "visible": True,
        "created_at": now,
        "updated_at": now,
        "parent_planning_id": active,
        "input_revision": {"reason": str(reason or "manual_edit")},
        "data_version": int(memory.retrieve("manual_plan_version") or 0) + 1,
        "source": "manual_edit",
    }
    for item in runs:
        item["visible"] = False
    _memory_put(memory, PLANNING_RUN_PREFIX + planning_id, parent_snapshot)
    _memory_put(memory, ACTIVE_PLANNING_ID_KEY, planning_id)
    _memory_put(memory, PLANNING_RUN_ID_KEY, planning_id)
    _memory_put(memory, "manual_planning_id", planning_id)
    _write_runs(memory, [*runs, run], reason="planning.run.forked")
    _notify(memory, "planning.run.editable")
    return planning_id


def invalidate_planning_dependents(memory: Any, *, reason: str = "planning geometry changed") -> Dict[str, Any]:
    """Remove active derived artifacts after a geometry edit.

    The currently selected run is a mutable draft until dose evaluation is
    completed.  Keeping the old dose grid or guide in its active aliases would
    make the UI report stale values as if they belonged to the edited geometry.
    Historical runs are untouched because their namespaced snapshots remain
    immutable.  ``manual_artifact_status`` is retained as the explicit UI
    contract describing what needs recomputation.
    """
    for key in STALE_PLANNING_VALUE_KEYS:
        _memory_delete(memory, key)
    status = {
        "dose": "stale",
        "dvh": "stale",
        "report": "stale",
        "quality_check": "stale",
        "surgical_guide": "stale",
        "reason": str(reason or "planning geometry changed"),
        "updated_at": _now(),
    }
    _memory_put(memory, "manual_artifact_status", status)
    _memory_put(memory, "surgical_guide_versions", [])
    _notify(memory, "planning.run.dependents.invalidated")
    return status


def _update_run(memory: Any, planning_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
    runs = ensure_planning_history(memory)
    found = None
    updated: List[Dict[str, Any]] = []
    for run in runs:
        if str(run.get("planning_id")) == str(planning_id):
            run = {**run, **changes, "updated_at": _now()}
            found = run
        updated.append(run)
    if found is not None:
        _write_runs(memory, updated, reason=f"planning.run.{changes.get('status', 'updated')}")
    return found


def publish_planning_run(agent: Any, result: Any = None, *, status: str = "completed") -> Optional[str]:
    """Persist the current active aliases as the reserved run's snapshot."""
    memory = agent.memory
    meta = getattr(result, "metadata", {}) or {}
    planning_id = str(meta.get("planning_id") or active_planning_id(memory) or "")
    if not planning_id:
        return None
    snapshot = _capture_current(memory)
    _memory_put(memory, PLANNING_RUN_PREFIX + planning_id, snapshot)
    metrics = memory.retrieve("dose_metrics") or {}
    guide = memory.retrieve("surgical_guide")
    _update_run(
        memory,
        planning_id,
        status=status,
        total_seeds=int(memory.retrieve("total_seeds") or len(memory.retrieve("manual_seeds") or [])),
        num_trajectories=int(memory.retrieve("num_trajectories") or len(memory.retrieve("trajectories") or [])),
        has_dose=memory.retrieve("dose_distribution_gy") is not None or memory.retrieve("dose_distribution") is not None,
        has_dvh=bool(metrics or memory.retrieve("dvh_data")),
        has_guide=isinstance(guide, Mapping),
        data_version=int(memory.retrieve("manual_plan_version") or 1),
        metrics_summary={
            key: metrics.get(key)
            for key in ("v100", "v150", "v200", "d90", "plan_score")
            if isinstance(metrics, Mapping) and metrics.get(key) is not None
        },
    )
    if status == "completed":
        # A successful child becomes the only displayed Planning.  Keeping
        # this transition at publish time means a failed replan can restore
        # the previous immutable run instead of leaving the tree empty.
        runs = ensure_planning_history(memory)
        _write_runs(
            memory,
            [
                {**item, "visible": str(item.get("planning_id")) == planning_id}
                for item in runs
            ],
            reason="planning.run.completed.visibility",
        )
    _memory_put(memory, ACTIVE_PLANNING_ID_KEY, planning_id)
    _memory_put(memory, PLANNING_RUN_ID_KEY, planning_id)
    _notify(memory, "planning.run.published")
    return planning_id


def publish_active_planning_state(agent: Any) -> Optional[str]:
    """Refresh the active immutable snapshot without changing run lifecycle.

    Planning-owned artifacts such as a guide skin surface may become available
    independently of dose calculation. Publishing them must not promote a
    manual draft to ``completed`` or regress a completed plan to ``draft``.
    """
    planning_id = active_planning_id(agent.memory)
    if not planning_id:
        return None
    status = next(
        (
            str(item.get("status") or "completed")
            for item in list_planning_runs(agent.memory)
            if str(item.get("planning_id") or "") == str(planning_id)
        ),
        "completed",
    )
    if status not in {"running", "draft", "completed"}:
        status = "completed"
    return publish_planning_run(agent, None, status=status)


def mark_planning_run(agent: Any, planning_id: str, status: str, error: Optional[str] = None) -> bool:
    memory = agent.memory
    changes: Dict[str, Any] = {"status": str(status)}
    if error:
        changes["error"] = str(error)
    updated = _update_run(memory, planning_id, **changes)
    if updated is None:
        return False
    if str(status) in {"failed", "cancelled"}:
        # Do not strand the session on a failed new run.  The previous run is
        # still a complete restore point and should remain what the user sees.
        parent_id = str(updated.get("parent_planning_id") or "")
        if parent_id and isinstance(memory.retrieve(PLANNING_RUN_PREFIX + parent_id), Mapping):
            try:
                activate_planning_run(agent, parent_id)
            except Exception:
                # Reporting the failure is still useful even if the parent
                # cannot be restored (for example after a damaged snapshot).
                pass
        else:
            _update_run(memory, planning_id, visible=False)
    return True


def activate_planning_run(agent: Any, planning_id: str) -> Dict[str, Any]:
    """Load one persisted run into the legacy active aliases."""
    memory = agent.memory
    run = _find_run(memory, planning_id)
    if run is None:
        raise KeyError(f"Planning run not found: {planning_id}")
    snapshot = memory.retrieve(PLANNING_RUN_PREFIX + str(planning_id))
    if not isinstance(snapshot, Mapping):
        raise KeyError(f"Planning run data not found: {planning_id}")
    updated_runs = []
    for item in ensure_planning_history(memory):
        updated_runs.append({**item, "visible": str(item.get("planning_id")) == str(planning_id)})
    with memory._lock:
        for key in PLANNING_VALUE_KEYS:
            if key in snapshot:
                memory.planning_results[key] = _clone(snapshot[key])
            else:
                memory.planning_results.pop(key, None)
            memory._planning_versions[key] = int(memory._planning_versions.get(key, 0)) + 1
        memory.planning_results[ACTIVE_PLANNING_ID_KEY] = str(planning_id)
        memory._planning_versions[ACTIVE_PLANNING_ID_KEY] = int(
            memory._planning_versions.get(ACTIVE_PLANNING_ID_KEY, 0)
        ) + 1
        memory.planning_results[PLANNING_RUN_ID_KEY] = str(planning_id)
        memory._planning_versions[PLANNING_RUN_ID_KEY] = int(
            memory._planning_versions.get(PLANNING_RUN_ID_KEY, 0)
        ) + 1
        memory.conversation_state["planning_completed"] = str(run.get("status")) == "completed"
        memory.conversation_state["data_available"] = sorted(memory.planning_results.keys())
    _write_runs(memory, updated_runs, reason="planning.run.visibility")
    _notify(memory, "planning.run.activated")
    return _run_summary(run)


def planning_run_snapshot(memory: Any, planning_id: Optional[str] = None) -> Dict[str, Any]:
    target = str(planning_id or active_planning_id(memory) or "")
    if not target:
        return {}
    value = memory.retrieve(PLANNING_RUN_PREFIX + target)
    return dict(value) if isinstance(value, Mapping) else {}
