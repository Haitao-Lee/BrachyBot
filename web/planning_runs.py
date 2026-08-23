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
        "label": str(run.get("label") or f"Planning_{int(run.get('sequence') or 0) + 1}"),
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
        "has_metrics": bool(run.get("has_metrics")),
        "has_guide": bool(run.get("has_guide")),
        "has_skin": bool(run.get("has_skin")),
        "artifact_status": dict(run.get("artifact_status") or {})
        if isinstance(run.get("artifact_status"), Mapping) else {},
        "metrics_summary": dict(run.get("metrics_summary") or {})
        if isinstance(run.get("metrics_summary"), Mapping) else {},
        "error": run.get("error"),
    }


def ensure_planning_history(memory: Any) -> List[Dict[str, Any]]:
    """Load Planning history and migrate old zero-based display labels.

    ``sequence`` remains an internal zero-based ordering value for backward
    compatibility.  User-facing labels are one-based (Planning_1, Planning_2,
    ...), which matches the terminology used in the Data Tree and reports.
    """
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
            # Releases before the one-based label contract wrote the sequence
            # directly into labels (Planning_0, Planning_1, ...). Migrate only
            # those exact legacy labels; preserve an explicit custom label.
            sequence = int(item.get("sequence") or 0)
            legacy_label = f"Planning_{sequence}"
            if not item.get("label") or str(item.get("label")) == legacy_label:
                migrated_label = f"Planning_{sequence + 1}"
                if item.get("label") != migrated_label:
                    item = {**item, "label": migrated_label}
                    changed = True
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
        "label": "Planning_1",
        "status": "completed",
        "legacy": True,
        "visible": True,
        "created_at": _now(),
        "updated_at": _now(),
        "data_version": int(memory.retrieve("manual_plan_version") or 1),
        "total_seeds": int(memory.retrieve("total_seeds") or len(memory.retrieve("manual_seeds") or [])),
        "num_trajectories": int(memory.retrieve("num_trajectories") or len(memory.retrieve("trajectories") or [])),
        "has_dose": memory.retrieve("dose_distribution_gy") is not None or memory.retrieve("dose_distribution") is not None,
        "has_dvh": memory.retrieve("dvh_data") is not None or memory.retrieve("algorithm_plan_dvh_data") is not None,
        "has_metrics": isinstance(memory.retrieve("dose_metrics") or memory.retrieve("metrics"), Mapping),
        "has_guide": bool(memory.retrieve("surgical_guide")),
        "has_skin": memory.retrieve("skin_surface") is not None or memory.retrieve("skin_surface_mask") is not None,
        "artifact_status": (
            dict(memory.retrieve("artifact_status") or memory.retrieve("manual_artifact_status") or {})
            if isinstance(
                memory.retrieve("artifact_status") or memory.retrieve("manual_artifact_status") or {},
                Mapping,
            )
            else {}
        ),
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
        "label": f"Planning_{sequence + 1}",
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
        "label": f"Planning_{sequence + 1}",
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
        has_dvh=memory.retrieve("dvh_data") is not None or memory.retrieve("algorithm_plan_dvh_data") is not None,
        has_metrics=isinstance(metrics, Mapping) and bool(metrics),
        has_guide=isinstance(guide, Mapping),
        has_skin=memory.retrieve("skin_surface") is not None or memory.retrieve("skin_surface_mask") is not None,
        artifact_status=(
            dict(memory.retrieve("artifact_status") or memory.retrieve("manual_artifact_status") or {})
            if isinstance(
                memory.retrieve("artifact_status") or memory.retrieve("manual_artifact_status") or {},
                Mapping,
            )
            else {}
        ),
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


def restore_active_planning_aliases(memory: Any) -> List[str]:
    """Repair missing legacy aliases from the active immutable run snapshot.

    Session hydration restores both the namespaced Planning run and the legacy
    top-level values consumed by existing Viewer/DVH/Guide routes. Older or
    interrupted checkpoints may contain the run but omit one or more aliases.
    Filling only absent values from the same active run is safe: it never
    replaces a newer live edit and does not change which Planning is active.
    """
    planning_id = active_planning_id(memory)
    if not planning_id:
        return []
    snapshot = memory.retrieve(PLANNING_RUN_PREFIX + str(planning_id))
    if not isinstance(snapshot, Mapping):
        return []

    restored: List[str] = []
    with memory._lock:
        versions = getattr(memory, "_planning_versions", {})
        run_version = int(versions.get(PLANNING_RUN_PREFIX + str(planning_id), 0))
        available = set(memory.conversation_state.get("data_available", []))
        for key in PLANNING_VALUE_KEYS:
            if memory.planning_results.get(key) is not None:
                continue
            value = snapshot.get(key)
            if value is None:
                continue
            cloned = _clone(value)
            if cloned is None:
                continue
            memory.planning_results[key] = cloned
            versions[key] = max(int(versions.get(key, 0)), run_version)
            available.add(key)
            restored.append(key)
        memory.conversation_state["data_available"] = sorted(available)
    return restored


def _planning_value_present(value: Any) -> bool:
    """Return whether a restored artifact contains usable payload data."""
    if value is None:
        return False
    if np is not None and isinstance(value, np.ndarray):
        return value.size > 0
    if isinstance(value, (Mapping, list, tuple, set)):
        return bool(value)
    return True


def _planning_snapshot_flags(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Derive Data Tree artifact flags from one immutable run snapshot.

    The registry is intentionally compact and older checkpoints sometimes
    contain stale ``has_*`` flags.  The namespaced snapshot is the source of
    truth after a restart, so derive the flags from the actual persisted
    values instead of trusting the old summary alone.
    """
    geometry = any(
        _planning_value_present(snapshot.get(key))
        for key in (
            "trajectories",
            "refined_trajectories",
            "seed_plan",
            "seed_plan_serialized",
            "seed_positions",
            "verified_needle_geometry",
            "manual_seeds",
            "manual_needles",
        )
    )
    has_dose = any(
        _planning_value_present(snapshot.get(key))
        for key in (
            "dose_distribution",
            "dose_distribution_gy",
            "dose_distribution_physical_gy",
            "algorithm_plan_dose_distribution",
            "algorithm_plan_dose_distribution_gy",
            "manual_ai_dose",
        )
    )
    has_metrics = any(
        _planning_value_present(snapshot.get(key))
        for key in ("dose_metrics", "algorithm_plan_dose_metrics", "metrics")
    )
    has_dvh = any(
        _planning_value_present(snapshot.get(key))
        for key in ("dvh_data", "algorithm_plan_dvh_data", "dose_metrics")
    )
    has_guide = any(
        _planning_value_present(snapshot.get(key))
        for key in ("surgical_guide", "surgical_guide_versions")
    )
    has_skin = any(
        _planning_value_present(snapshot.get(key))
        for key in ("skin_surface", "skin_surface_mask")
    )

    total_seeds = snapshot.get("total_seeds")
    try:
        total_seeds = int(total_seeds or 0)
    except (TypeError, ValueError):
        total_seeds = 0
    if total_seeds <= 0:
        serialized = snapshot.get("seed_plan_serialized")
        if isinstance(serialized, Mapping):
            serialized = serialized.get("seeds") or serialized.get("seed_plan")
        if isinstance(serialized, list):
            total_seeds = len(serialized)
        elif isinstance(snapshot.get("manual_seeds"), list):
            total_seeds = len(snapshot.get("manual_seeds") or [])

    num_trajectories = snapshot.get("num_trajectories")
    try:
        num_trajectories = int(num_trajectories or 0)
    except (TypeError, ValueError):
        num_trajectories = 0
    if num_trajectories <= 0:
        for key in ("refined_trajectories", "trajectories", "manual_needles"):
            value = snapshot.get(key)
            if isinstance(value, (list, tuple)):
                num_trajectories = len(value)
                if num_trajectories:
                    break

    metrics = next(
        (
            snapshot.get(key)
            for key in ("dose_metrics", "algorithm_plan_dose_metrics", "metrics")
            if isinstance(snapshot.get(key), Mapping)
        ),
        {},
    )
    metrics_summary = {
        key: metrics.get(key)
        for key in ("v100", "v150", "v200", "d90", "plan_score")
        if metrics.get(key) is not None
    }
    artifact_status = next(
        (
            dict(snapshot.get(key))
            for key in ("artifact_status", "manual_artifact_status")
            if isinstance(snapshot.get(key), Mapping)
        ),
        {},
    )
    return {
        "geometry": geometry,
        "has_dose": has_dose,
        "has_dvh": has_dvh,
        "has_metrics": has_metrics,
        "has_guide": has_guide,
        "has_skin": has_skin,
        "total_seeds": total_seeds,
        "num_trajectories": num_trajectories,
        "metrics_summary": metrics_summary,
        "artifact_status": artifact_status,
    }


def _planning_snapshot_score(snapshot: Mapping[str, Any]) -> int:
    """Rank snapshots so a stale empty active shell cannot hide a real plan."""
    flags = _planning_snapshot_flags(snapshot)
    return sum(
        weight
        for key, weight in (
            ("geometry", 2),
            ("has_dose", 3),
            ("has_dvh", 2),
            ("has_metrics", 1),
            ("has_guide", 2),
            ("has_skin", 1),
        )
        if flags[key]
    )


def _activate_planning_snapshot(memory: Any, planning_id: str) -> List[str]:
    """Activate a decoded snapshot without requiring an Agent wrapper."""
    snapshot = memory.retrieve(PLANNING_RUN_PREFIX + str(planning_id))
    if not isinstance(snapshot, Mapping):
        return []
    restored: List[str] = []
    with memory._lock:
        versions = getattr(memory, "_planning_versions", {})
        run_version = int(versions.get(PLANNING_RUN_PREFIX + str(planning_id), 0))
        for key in PLANNING_VALUE_KEYS:
            if key in snapshot:
                value = _clone(snapshot[key])
                if value is not None:
                    memory.planning_results[key] = value
                    restored.append(key)
                else:
                    memory.planning_results.pop(key, None)
            else:
                memory.planning_results.pop(key, None)
            versions[key] = max(int(versions.get(key, 0)), run_version)
        memory.planning_results[ACTIVE_PLANNING_ID_KEY] = str(planning_id)
        versions[ACTIVE_PLANNING_ID_KEY] = max(
            int(versions.get(ACTIVE_PLANNING_ID_KEY, 0)), run_version
        )
        memory.planning_results[PLANNING_RUN_ID_KEY] = str(planning_id)
        versions[PLANNING_RUN_ID_KEY] = max(
            int(versions.get(PLANNING_RUN_ID_KEY, 0)), run_version
        )
        memory.conversation_state["data_available"] = sorted(memory.planning_results.keys())
    return restored


def reconcile_planning_history(
    memory: Any,
    *,
    recover_running: bool = False,
) -> Dict[str, Any]:
    """Reconcile the registry and active aliases after a full hydration.

    A lightweight checkpoint can preserve ``planning_runs`` while a previous
    active alias points at a newly-created, incomplete run.  In that state the
    UI correctly renders the history rows but every downstream endpoint sees
    an empty plan.  This repair is deliberately limited to the hydration
    boundary: live planning never auto-switches the user's active run.
    """
    runs = ensure_planning_history(memory)
    if not runs:
        return {"active_planning_id": None, "restored_aliases": [], "changed": False}

    snapshots = {
        str(run.get("planning_id")): memory.retrieve(
            PLANNING_RUN_PREFIX + str(run.get("planning_id"))
        )
        for run in runs
    }
    changed = False
    enriched: List[Dict[str, Any]] = []
    scores: Dict[str, int] = {}
    for run in runs:
        planning_id = str(run.get("planning_id") or "")
        snapshot = snapshots.get(planning_id)
        if not isinstance(snapshot, Mapping):
            if recover_running and str(run.get("status")) == "running":
                run = {
                    **run,
                    "status": "interrupted",
                    "error": run.get("error") or "Server restarted before this Planning completed",
                }
                changed = True
            enriched.append(run)
            scores[planning_id] = 0
            continue
        flags = _planning_snapshot_flags(snapshot)
        scores[planning_id] = _planning_snapshot_score(snapshot)
        updates: Dict[str, Any] = {}
        for key in ("total_seeds", "num_trajectories"):
            if flags[key] and int(run.get(key) or 0) != int(flags[key]):
                updates[key] = int(flags[key])
        for key in ("has_dose", "has_dvh", "has_metrics", "has_guide", "has_skin"):
            if flags[key] and not bool(run.get(key)):
                updates[key] = True
        if flags["artifact_status"] and run.get("artifact_status") != flags["artifact_status"]:
            updates["artifact_status"] = flags["artifact_status"]
        if flags["metrics_summary"] and run.get("metrics_summary") != flags["metrics_summary"]:
            updates["metrics_summary"] = flags["metrics_summary"]
        if recover_running and str(run.get("status")) == "running":
            updates["status"] = "interrupted"
            updates.setdefault(
                "error",
                "Server restarted before this Planning completed",
            )
        if updates:
            run = {**run, **updates}
            changed = True
        enriched.append(run)

    if changed:
        _write_runs(memory, enriched, reason="planning.history.reconciled")
        runs = enriched

    active = active_planning_id(memory)
    active_run = next((run for run in runs if str(run.get("planning_id")) == str(active)), None)
    stable = [
        run for run in runs
        if str(run.get("status")) in {"completed", "interrupted"}
        and str(run.get("planning_id")) in snapshots
        and isinstance(snapshots.get(str(run.get("planning_id"))), Mapping)
    ]
    best = max(
        stable or [run for run in runs if str(run.get("planning_id")) in snapshots],
        key=lambda run: (
            scores.get(str(run.get("planning_id")), 0),
            int(run.get("sequence") or 0),
        ),
        default=None,
    )
    target = str(active or "")
    if active_run is None or not isinstance(snapshots.get(target), Mapping):
        if best is not None:
            target = str(best.get("planning_id") or "")
    elif str(active_run.get("status")) in {"interrupted", "running"} and best is not None:
        if scores.get(str(best.get("planning_id")), 0) > scores.get(target, 0):
            target = str(best.get("planning_id") or "")

    restored_aliases: List[str]
    active_target_changed = bool(target and target != str(active or ""))
    if active_target_changed:
        restored_aliases = _activate_planning_snapshot(memory, target)
        active = target
        runs = ensure_planning_history(memory)
        _write_runs(
            memory,
            [
                {**run, "visible": str(run.get("planning_id")) == target}
                for run in runs
            ],
            reason="planning.history.active.reconciled",
        )
        _memory_put(memory, ACTIVE_PLANNING_ID_KEY, target)
        _memory_put(memory, PLANNING_RUN_ID_KEY, target)
    else:
        restored_aliases = restore_active_planning_aliases(memory)

    return {
        "active_planning_id": active or None,
        "restored_aliases": restored_aliases,
        "changed": changed or active_target_changed,
    }


def planning_run_snapshot(memory: Any, planning_id: Optional[str] = None) -> Dict[str, Any]:
    target = str(planning_id or active_planning_id(memory) or "")
    if not target:
        return {}
    value = memory.retrieve(PLANNING_RUN_PREFIX + target)
    return dict(value) if isinstance(value, Mapping) else {}


def current_planning_context(memory: Any) -> Dict[str, Any]:
    """Return a compact, version-correct view of the active Planning run.

    Clinical read tools must not depend on whichever legacy alias happens to
    be populated after hydration.  When the active alias and active run agree,
    the live alias wins so unsnapshotted edits remain visible.  When they do
    not agree, the immutable active-run snapshot wins so data from another
    Planning can never leak into the assessment.

    The returned object intentionally excludes dose arrays and detailed mesh
    geometry.  It is safe to inject into metric/review tools and small enough
    to pass through the tool gateway without duplicating case artifacts.
    """
    # This is a read boundary.  Do not call ``active_planning_id`` here because
    # its legacy migration path can mutate memory while a read-only tool is
    # being executed.
    planning_id = str(
        memory.retrieve(ACTIVE_PLANNING_ID_KEY)
        or memory.retrieve(PLANNING_RUN_ID_KEY)
        or ""
    )
    alias_id = str(memory.retrieve(PLANNING_RUN_ID_KEY) or "")
    snapshot = planning_run_snapshot(memory, planning_id) if planning_id else {}
    prefer_live = not planning_id or alias_id == planning_id

    def read(*keys: str, default: Any = None) -> Any:
        if prefer_live:
            for key in keys:
                value = memory.retrieve(key)
                if value is not None:
                    return value
        for key in keys:
            value = snapshot.get(key)
            if value is not None:
                return value
        return default

    metrics = read(
        "dose_metrics", "algorithm_plan_dose_metrics", "metrics", default={}
    )
    plan_config = read("plan_config", default={})
    total_seeds = read("total_seeds", default=0)
    num_trajectories = read("num_trajectories", default=0)
    try:
        total_seeds = int(total_seeds or 0)
    except (TypeError, ValueError):
        total_seeds = 0
    try:
        num_trajectories = int(num_trajectories or 0)
    except (TypeError, ValueError):
        num_trajectories = 0

    if total_seeds <= 0:
        serialized = read("seed_plan_serialized", default={})
        seeds = serialized.get("seeds") if isinstance(serialized, Mapping) else None
        if isinstance(seeds, (list, tuple)):
            total_seeds = len(seeds)
        else:
            manual_seeds = read("manual_seeds", default=[])
            if isinstance(manual_seeds, (list, tuple)):
                total_seeds = len(manual_seeds)
    if num_trajectories <= 0:
        for key in ("manual_needles", "refined_trajectories", "trajectories"):
            value = read(key, default=[])
            if isinstance(value, (list, tuple)) and value:
                num_trajectories = len(value)
                break

    tumor_type = (
        read("tumor_type", default="")
        or memory.retrieve("tumor_type_used")
        or memory.retrieve("tumor_type")
        or ""
    )
    return {
        "planning_id": planning_id or alias_id or None,
        "metrics": dict(metrics) if isinstance(metrics, Mapping) else {},
        "plan_config": dict(plan_config) if isinstance(plan_config, Mapping) else {},
        "tumor_type": str(tumor_type or ""),
        "total_seeds": total_seeds,
        "num_trajectories": num_trajectories,
        "geometry_available": bool(total_seeds and num_trajectories),
        "source": "active_planning_run" if planning_id else "legacy_active_aliases",
    }
