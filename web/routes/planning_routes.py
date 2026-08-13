"""Planning, chat, export, and UI bridge routes for the BrachyBot web API."""

import json
import copy
import hashlib
import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

import numpy as np
import SimpleITK as sitk
from flask import Response, current_app, jsonify, request, send_file, session as flask_session, stream_with_context

from plans.dose_pre.model_loader import (
    DEFAULT_PRESCRIPTION_GY,
    dose_gy_to_model,
    planning_dose_value_to_gy,
    resolve_dose_scale_gy,
    resolve_prescription_gy,
)
from web.auth import current_user
from web.chat_tasks import ChatTask, ChatTaskManager
from web.workspace_store import WorkspaceError, WorkspaceQuotaExceeded, WorkspaceNotFound
from agent_runtime.core import resolve_reference_direction_input
from web.planning_runs import (
    activate_planning_run,
    active_planning_id,
    fork_planning_run,
    invalidate_planning_dependents,
    list_planning_runs,
    mark_planning_run,
    planning_run_snapshot,
    publish_planning_run,
)

try:
    from web.server_support import (
        DOSE_MODEL_SCALE_GY,
        DOSE_MODEL_UNITS,
        PROJECT_ROOT,
        SCREENSHOTS_DIR,
        TRUE_VALUES,
        rate_limit,
        require_api_key,
        task_manager,
    )
    from web import server_support as _server_support
except ImportError:  # pragma: no cover - supports `python web/server.py`.
    from server_support import (  # type: ignore
        DOSE_MODEL_SCALE_GY,
        DOSE_MODEL_UNITS,
        PROJECT_ROOT,
        SCREENSHOTS_DIR,
        TRUE_VALUES,
        rate_limit,
        require_api_key,
        task_manager,
    )
    import server_support as _server_support  # type: ignore

logger = logging.getLogger(__name__)

# Marching cubes needs an outside background sample when a dose isosurface
# touches the planning-grid boundary.  The padding is used only while
# extracting the display surface; dose values, grid geometry, and all
# planning calculations remain on the original array.
_DOSE_SURFACE_BOUNDARY_PADDING_VOXELS = 1


def _pad_dose_surface_volume(volume, fill_value):
    """Pad a dose grid for a closed display isosurface and return the offset."""
    array = np.asarray(volume)
    pad = int(_DOSE_SURFACE_BOUNDARY_PADDING_VOXELS)
    if array.ndim != 3 or pad <= 0:
        return array, np.zeros(3, dtype=np.float64)
    padded = np.pad(
        array,
        ((pad, pad), (pad, pad), (pad, pad)),
        mode="constant",
        constant_values=fill_value,
    )
    return padded, np.full(3, float(pad), dtype=np.float64)


def _dose_coverage_audit(
    dose_array,
    target_mask,
    threshold_normalized,
    *,
    threshold_gy,
    prescription_gy,
    dose_metrics=None,
    grid="unknown",
):
    """Recompute target coverage on the exact grid used for a dose surface.

    The audit proves that a displayed prescription surface and the persisted
    DVH metric describe the same dose field. A small delta is expected after
    linear resampling to the original CT grid; a material disagreement must be
    visible in logs and response metadata.
    """
    if dose_array is None or target_mask is None:
        return None
    try:
        dose_np = (
            sitk.GetArrayFromImage(dose_array)
            if isinstance(dose_array, sitk.Image)
            else np.asarray(dose_array)
        )
        target_np = (
            sitk.GetArrayFromImage(target_mask)
            if isinstance(target_mask, sitk.Image)
            else np.asarray(target_mask)
        )
    except Exception:
        logger.exception("[dose_coverage_audit] Could not decode dose or target data")
        return None

    if dose_np.ndim != 3 or target_np.ndim != 3 or dose_np.shape != target_np.shape:
        logger.warning(
            "[dose_coverage_audit] Grid mismatch dose=%s target=%s grid=%s",
            getattr(dose_np, "shape", None),
            getattr(target_np, "shape", None),
            grid,
        )
        return None

    target = target_np > 0
    target_voxels = int(np.count_nonzero(target))
    if target_voxels == 0:
        return None
    covered_voxels = int(np.count_nonzero((dose_np >= float(threshold_normalized)) & target))
    coverage_fraction = covered_voxels / target_voxels

    reported_metric = None
    reported_fraction = None
    ratio = float(threshold_gy) / max(float(prescription_gy), 1e-12)
    for expected_ratio, metric_name in ((1.0, "v100"), (1.5, "v150"), (2.0, "v200")):
        if abs(ratio - expected_ratio) <= 0.025:
            reported_metric = metric_name
            break
    metrics = dose_metrics if isinstance(dose_metrics, dict) else {}
    if isinstance(metrics.get("metrics"), dict):
        metrics = metrics["metrics"]
    if reported_metric and isinstance(metrics.get(reported_metric), (int, float)):
        reported_fraction = float(metrics[reported_metric])
        units = str(metrics.get("volume_metric_units") or "").strip().lower()
        if units in {"percent", "percentage", "0-100"} or (not units and reported_fraction > 1.0):
            reported_fraction /= 100.0

    delta_points = None
    consistent = None
    if reported_fraction is not None:
        delta_points = (coverage_fraction - reported_fraction) * 100.0
        # Original-CT dose is linearly resampled from the planning grid. One
        # percentage point is a strict but practical interpolation tolerance.
        consistent = abs(delta_points) <= 1.0

    return {
        "grid": str(grid),
        "threshold_gy": float(threshold_gy),
        "threshold_model": float(threshold_normalized),
        "prescription_gy": float(prescription_gy),
        "target_voxels": target_voxels,
        "covered_target_voxels": covered_voxels,
        "cold_target_voxels": target_voxels - covered_voxels,
        "coverage_fraction": float(coverage_fraction),
        "coverage_percent": float(coverage_fraction * 100.0),
        "reported_metric": reported_metric,
        "reported_coverage_fraction": reported_fraction,
        "reported_coverage_percent": (
            float(reported_fraction * 100.0) if reported_fraction is not None else None
        ),
        "delta_percentage_points": float(delta_points) if delta_points is not None else None,
        "consistent": consistent,
    }


def _saved_dose_scale_gy(agent) -> float:
    """Return the calibration owned by the current plan/session."""
    if agent is None:
        return DOSE_MODEL_SCALE_GY
    memory = getattr(agent, "memory", None)
    try:
        plan_config = memory.retrieve("plan_config") or {}
        dose_metrics = memory.retrieve("dose_metrics") or {}
        stored_scale = memory.retrieve("dose_scale_gy")
    except Exception:
        plan_config = {}
        dose_metrics = {}
        stored_scale = None
    return resolve_dose_scale_gy(
        plan_config,
        dose_metrics,
        dose_scale_gy=stored_scale,
    )


def _dose_data_generation(agent) -> int:
    """Return the newest persisted dose generation for cache validation.

    Workspace memory versions are incremented whenever a value is stored.  A
    slice response must carry that generation so the browser can distinguish
    a newly published dose grid from a same-shaped grid cached during an older
    planning stage.
    """
    memory = getattr(agent, "memory", None)
    versions = getattr(memory, "_planning_versions", {}) if memory is not None else {}
    if not isinstance(versions, dict):
        return 0
    generations = []
    for key in (
        "dose_distribution_gy",
        "dose_distribution",
        "dose_metrics",
        "dvh_data",
    ):
        try:
            generations.append(int(versions.get(key, 0) or 0))
        except (TypeError, ValueError):
            continue
    return max(generations, default=0)


def _submitted_manual_needles(data: Dict[str, Any], current_needles: Any) -> list:
    """Resolve the needle list without confusing an explicit empty list.

    ``needles=[]`` is a valid mutation when the operator deletes the last
    needle.  Only an omitted or ``null`` field means "keep the server list".
    Keeping this rule in one small helper prevents every mutation route from
    accidentally resurrecting deleted planning objects.
    """
    if "needles" not in data or data.get("needles") is None:
        needles = list(current_needles or [])
    else:
        needles = data.get("needles")
        if not isinstance(needles, list):
            raise ValueError("needles must be a list")
    needles, _ = _deduplicate_manual_needle_records(needles)
    return needles


_UI_BRIDGE_LOCK = _server_support._UI_BRIDGE_LOCK
_append_ui_event = _server_support._append_ui_event
_build_plan_advice = _server_support._build_plan_advice
_build_system_readiness = _server_support._build_system_readiness
_compute_manual_ai_dose = _server_support._compute_manual_ai_dose
_seed_interference_report = _server_support._seed_interference_report
_decode_png_data_url = _server_support._decode_png_data_url
_make_screenshot_url = _server_support._make_screenshot_url
_resolve_output_path = _server_support._resolve_output_path
_safe_screenshot_path = _server_support._safe_screenshot_path
_training_feedback_for_event = _server_support._training_feedback_for_event
_training_screenshot_for_event = _server_support._training_screenshot_for_event
_format_training_summary = _server_support._format_training_summary
_localize_plan_advice = _server_support._localize_plan_advice
_monitor_language = _server_support._monitor_language
_ui_bucket = _server_support._ui_bucket
_ui_session_id = _server_support._ui_session_id
_valid_screenshot_request = _server_support._valid_screenshot_request
_validate_path = _server_support._validate_path
_oar_display_name_map = _server_support._oar_display_name_map

# UI events can arrive in bursts while a viewer is being dragged or a
# training monitor is active.  Persisting every event synchronously used to
# serialize a snapshot and scan large case artifacts on the request thread.
# Keep only the latest bridge state per owned case and flush it in a daemon
# timer; the in-memory bridge remains available immediately.
_UI_BRIDGE_CHECKPOINT_LOCK = threading.Lock()
_UI_BRIDGE_CHECKPOINT_PENDING: Dict[tuple, tuple] = {}
_UI_BRIDGE_CHECKPOINT_TIMERS: Dict[tuple, threading.Timer] = {}


def _flush_ui_bridge_checkpoint(key: tuple) -> None:
    with _UI_BRIDGE_CHECKPOINT_LOCK:
        item = _UI_BRIDGE_CHECKPOINT_PENDING.pop(key, None)
        _UI_BRIDGE_CHECKPOINT_TIMERS.pop(key, None)
    if item is None:
        return
    store, user_id, selected, bridge, reason = item
    try:
        store.save_snapshot_patch(
            user_id,
            selected,
            {"ui": {"bridge": bridge}},
            expected_revision=None,
            reason=reason,
        )
    except WorkspaceNotFound:
        # A delayed browser event can arrive after explicit case deletion.
        logger.debug("Ignoring UI bridge checkpoint for deleted case %s", selected)
    except WorkspaceError:
        # This is a background durability retry point, not a user-facing
        # workflow failure; avoid emitting a misleading traceback per event.
        logger.warning("Unable to persist UI bridge state for case %s", selected, exc_info=False)


def _validate_label_geometry(ct_path: str, label_path: str) -> Optional[str]:
    """Reject masks whose physical grid differs from the active CT.

    Resampling an uploaded mask implicitly would change the established
    coordinate chain and can move a CTV/OAR relative to planned needles. The
    user can resample explicitly and upload the corrected label instead.
    """
    try:
        ct = sitk.ReadImage(ct_path)
        label = sitk.ReadImage(label_path)
    except Exception as exc:
        return f"Unable to read CT or mask: {exc}"
    if tuple(ct.GetSize()) != tuple(label.GetSize()):
        return f"Mask size {tuple(label.GetSize())} does not match CT size {tuple(ct.GetSize())}"
    if not np.allclose(ct.GetSpacing(), label.GetSpacing(), rtol=0.0, atol=1e-4):
        return "Mask spacing does not match the CT spacing"
    if not np.allclose(ct.GetOrigin(), label.GetOrigin(), rtol=0.0, atol=1e-4):
        return "Mask origin does not match the CT origin"
    if not np.allclose(ct.GetDirection(), label.GetDirection(), rtol=0.0, atol=1e-4):
        return "Mask direction does not match the CT direction"
    return None


def _snapshot_from_seed_plan(serialized_plan, needle_geometry):
    """Convert an automatic serialized plan to the public Viewer snapshot.

    Automatic plans store per-seed dose maps in zero-based Python lists, but
    their public object IDs are one-based (``traj_1``, ``needle_1``,
    ``seed_1_1``).  Keep that storage/display distinction here.  Returning
    list indices as IDs made a rejected drag or a Planning restore hand the
    browser different identities from ``/planning/results`` and
    ``/planning/seeds_3d`` for the exact same geometry.
    """
    seeds = []
    needles = []
    for trajectory_index, entry in enumerate(serialized_plan or []):
        if not isinstance(entry, dict):
            continue
        trajectory_id = f"traj_{trajectory_index + 1}"
        for seed_index, seed in enumerate(entry.get("seeds") or []):
            if isinstance(seed, dict):
                position = seed.get("position") or seed.get("pos")
                direction = seed.get("direction") or seed.get("dir")
            elif isinstance(seed, (list, tuple)) and len(seed) >= 2:
                position, direction = seed[0], seed[1]
            else:
                continue
            if not isinstance(position, (list, tuple)) or not isinstance(direction, (list, tuple)):
                continue
            if len(position) < 3 or len(direction) < 3:
                continue
            seeds.append({
                "id": f"seed_{trajectory_index + 1}_{seed_index + 1}",
                "position": [float(v) for v in position[:3]],
                "direction": [float(v) for v in direction[:3]],
                "trajectory_id": trajectory_id,
            })
        points = (needle_geometry or {}).get(str(trajectory_index))
        if isinstance(points, list) and len(points) >= 2:
            needles.append({
                "id": f"needle_{trajectory_index + 1}",
                "points": [[float(v) for v in point[:3]] for point in points[:2]],
                "trajectory_id": trajectory_id,
            })
    return {"seeds": seeds, "needles": needles}


def _deduplicate_manual_seed_records(records):
    """Repair a legacy manual snapshot that contains the same seed ID twice.

    A seed ID is the stable identity used by the Data Tree, Viewer and dose
    transactions. Older snapshots could duplicate an entry after a failed
    optimistic edit, making every later geometry update fail validation. Keep
    the last record for a duplicated ID (the most recent edit) and report the
    repaired IDs to the caller for logging.
    """
    result = []
    indexes = {}
    duplicate_ids = []
    for record in records or []:
        if not isinstance(record, dict):
            result.append(record)
            continue
        seed_id = str(record.get("id") or "").strip()
        if seed_id and seed_id in indexes:
            result[indexes[seed_id]] = record
            duplicate_ids.append(seed_id)
            continue
        if seed_id:
            indexes[seed_id] = len(result)
        result.append(record)
    return result, sorted(set(duplicate_ids))


def _deduplicate_manual_needle_records(records):
    """Repair legacy manual needle snapshots by stable needle ID."""
    result = []
    indexes = {}
    duplicate_ids = []
    for record in records or []:
        if not isinstance(record, dict):
            result.append(record)
            continue
        needle_id = str(record.get("id") or "").strip()
        if needle_id and needle_id in indexes:
            result[indexes[needle_id]] = record
            duplicate_ids.append(needle_id)
            continue
        if needle_id:
            indexes[needle_id] = len(result)
        result.append(record)
    return result, sorted(set(duplicate_ids))


def _repair_serialized_manual_seed_plan(memory, seeds):
    """Drop duplicate IDs from the serialized mirror used by the viewer."""
    serialized = memory.retrieve("seed_plan_serialized")
    if not isinstance(serialized, list):
        serialized = memory.retrieve("seed_plan")
    if not isinstance(serialized, list):
        return
    seen = set()
    repaired = []
    for entry in serialized:
        if not isinstance(entry, dict):
            repaired.append(entry)
            continue
        entry_copy = dict(entry)
        clean_seeds = []
        for seed in entry.get("seeds") or []:
            if not isinstance(seed, dict):
                continue
            seed_id = str(seed.get("id") or "").strip()
            if seed_id and seed_id in seen:
                continue
            if seed_id:
                seen.add(seed_id)
            clean_seeds.append(seed)
        entry_copy["seeds"] = clean_seeds
        entry_copy["num_seeds"] = len(clean_seeds)
        repaired.append(entry_copy)
    # This is a repair of the manual serialized mirror. The automatic
    # ``seed_plan`` also carries per-seed dose maps and must remain immutable
    # so a later manual edit can subtract the original contribution exactly.
    memory.store("manual_plan_serialized", repaired)
    memory.store("seed_plan_serialized", repaired)
    memory.store("total_seeds", len(seeds or []))


def _current_planning_snapshot(agent):
    """Return the current manual snapshot, or the automatic baseline."""
    memory = agent.memory
    raw_manual_seeds = memory.retrieve("manual_seeds")
    raw_manual_needles = memory.retrieve("manual_needles")
    manual_seeds = list(raw_manual_seeds) if raw_manual_seeds is not None else []
    manual_needles = list(raw_manual_needles) if raw_manual_needles is not None else []
    manual_seeds, duplicate_ids = _deduplicate_manual_seed_records(manual_seeds)
    if duplicate_ids:
        logger.warning("Repairing duplicate manual seed IDs: %s", duplicate_ids)
        memory.store("manual_seeds", manual_seeds)
        _repair_serialized_manual_seed_plan(memory, manual_seeds)
    manual_needles, duplicate_needle_ids = _deduplicate_manual_needle_records(manual_needles)
    if duplicate_needle_ids:
        logger.warning("Repairing duplicate manual needle IDs: %s", duplicate_needle_ids)
        memory.store("manual_needles", manual_needles)
    if (
        memory.retrieve("manual_plan_active")
        or len(manual_seeds) > 0
        or len(manual_needles) > 0
    ):
        return {"seeds": list(manual_seeds), "needles": list(manual_needles)}
    serialized = memory.retrieve("seed_plan_serialized")
    geometry = memory.retrieve("verified_needle_geometry")
    if isinstance(serialized, list) and serialized:
        public_snapshot = _snapshot_from_seed_plan(
            serialized,
            geometry if isinstance(geometry, dict) else {},
        )
        if public_snapshot["seeds"] or public_snapshot["needles"]:
            return public_snapshot

    # Older snapshots can predate ``seed_plan_serialized``. Preserve their
    # stored records as a compatibility fallback rather than treating an old
    # case as an empty Planning.
    baseline = memory.retrieve("algorithm_plan_snapshot")
    if isinstance(baseline, dict):
        baseline_seeds = baseline.get("seeds")
        baseline_needles = baseline.get("needles")
        return {
            "seeds": list(baseline_seeds) if baseline_seeds is not None else [],
            "needles": list(baseline_needles) if baseline_needles is not None else [],
        }
    return {"seeds": [], "needles": []}


def _manual_seed_geometry_settings(memory) -> Dict[str, float]:
    """Return the physical seed constraints used by planning and interaction."""
    plan_config = memory.retrieve("plan_config") or {}
    seed_info = plan_config.get("seed_info") if isinstance(plan_config, dict) else {}
    if not isinstance(seed_info, dict):
        seed_info = {}

    def positive(name: str, default: float) -> float:
        try:
            value = float(seed_info.get(name, default) or default)
        except (TypeError, ValueError):
            value = default
        return value if np.isfinite(value) and value > 0.0 else default

    length_mm = positive("length", 4.5)
    radius_mm = positive("radius", 0.4)
    step_mm = 0.0
    for key in ("implant_step_mm", "seed_step_mm", "center_spacing_mm"):
        if key not in seed_info:
            continue
        try:
            candidate = float(seed_info[key])
        except (TypeError, ValueError):
            continue
        if np.isfinite(candidate) and candidate > 0.0:
            step_mm = candidate
            break
    return {
        "length_mm": length_mm,
        "radius_mm": radius_mm,
        "implant_step_mm": step_mm,
        "minimum_center_distance_mm": max(length_mm, positive("minimum_center_distance_mm", length_mm)),
    }


def _normalize_manual_seed_records(
    memory,
    raw_seeds: list,
    needles: list,
) -> list:
    """Project submitted seeds onto their owning needle's valid implant span."""
    settings = _manual_seed_geometry_settings(memory)
    needle_by_trajectory = {}
    for needle in needles or []:
        if not isinstance(needle, dict):
            continue
        points = needle.get("points")
        if not isinstance(points, list) or len(points) < 2:
            continue
        trajectory_id = str(needle.get("trajectory_id") or needle.get("id") or "").strip()
        if not trajectory_id:
            continue
        start = np.asarray(points[0], dtype=np.float64).reshape(-1)[:3]
        end = np.asarray(points[-1], dtype=np.float64).reshape(-1)[:3]
        if start.size != 3 or end.size != 3 or not np.all(np.isfinite([*start, *end])):
            continue
        axis = end - start
        length = float(np.linalg.norm(axis))
        if length <= settings["length_mm"] + 1e-6:
            continue
        needle_by_trajectory[trajectory_id] = (start, end, axis, length)

    normalized = []
    seen_ids = set()
    for index, seed in enumerate(raw_seeds or []):
        if not isinstance(seed, dict):
            raise ValueError(f"Invalid seed at index {index}")
        seed_id = str(seed.get("id") or "").strip()
        if not seed_id:
            raise ValueError(f"Seed at index {index} is missing an id")
        if seed_id in seen_ids:
            raise ValueError(f"Duplicate seed id: {seed_id}")
        seen_ids.add(seed_id)
        trajectory_id = str(seed.get("trajectory_id") or "").strip()
        needle_geometry = needle_by_trajectory.get(trajectory_id)
        if needle_geometry is None:
            raise ValueError(f"Seed {seed_id} has no valid owning needle")
        position = np.asarray(seed.get("position") or seed.get("pos"), dtype=np.float64).reshape(-1)[:3]
        if position.size != 3 or not np.all(np.isfinite(position)):
            raise ValueError(f"Seed {seed_id} has an invalid position")

        start, _end, axis, length = needle_geometry
        unit = axis / length
        distance_mm = float(np.dot(position - start, unit))
        half_length = settings["length_mm"] * 0.5
        distance_mm = float(np.clip(distance_mm, half_length, length - half_length))
        implant_step = settings["implant_step_mm"]
        if implant_step > 0.0:
            distance_mm = half_length + round((distance_mm - half_length) / implant_step) * implant_step
            distance_mm = float(np.clip(distance_mm, half_length, length - half_length))
        projected = start + unit * distance_mm
        normalized.append({
            "id": seed_id,
            "position": projected.tolist(),
            "direction": unit.tolist(),
            "trajectory_id": trajectory_id,
            "visible": seed.get("visible", True) is not False,
            "opacity": float(seed.get("opacity", 1.0) or 1.0),
            "color": str(seed.get("color") or "#ffcc00"),
            "axial_position_mm": distance_mm,
        })
    return normalized


def _mark_manual_dependents_stale(memory, *, reason: str, planning_version: int) -> Dict[str, Any]:
    status = {
        "dose": "stale",
        "dvh": "stale",
        "report": "stale",
        "quality_check": "stale",
        "surgical_guide": "stale",
        "reason": str(reason),
        "planning_version": int(planning_version),
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    memory.store("manual_artifact_status", status)
    return status


_FULL_WORKSPACE_CHAT_TERMS = (
    "ct", "ctv", "oar", "mask", "segmentation", "segment", "分割", "掩膜",
    "planning", "plan", "规划", "剂量", "dose", "dvh", "needle", "seed",
    "trajectory", "穿刺", "粒子", "针道", "导板", "surgical guide", "手术导板",
    "replan", "重新规划", "重建", "reconstruct", "viewer", "查看器",
)


def _chat_requires_full_workspace(message: str, image_path: str = "") -> bool:
    """Return whether a chat turn needs decoded CT/label/planning arrays.

    Metadata-only status and knowledge questions must be able to answer while
    a large case is warming in the background.  Clinical actions remain bound
    to the fully hydrated Agent so a fast response can never overwrite a case
    with incomplete arrays.
    """
    if image_path:
        return True
    text = str(message or "").strip().lower()
    for term in _FULL_WORKSPACE_CHAT_TERMS:
        if term.isascii():
            if re.search(r"\b" + re.escape(term) + r"\b", text):
                return True
        elif term in text:
            return True
    return False


def register_planning_routes(
    app,
    get_agent,
    *,
    get_cached_agent=None,
    get_agent_for_owner=None,
):

    # Chat workers are case-scoped and outlive an individual browser stream.
    # Switching the selected case therefore only changes presentation; it
    # cannot cancel a task that belongs to another case.
    chat_tasks = app.extensions.get("brachybot_chat_tasks")
    if chat_tasks is None:
        chat_tasks = ChatTaskManager()
        app.extensions["brachybot_chat_tasks"] = chat_tasks

    def request_case_context():
        """Resolve and authorize the case explicitly bound to this request."""
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        session_id = str(
            request.headers.get("X-BrachyBot-Session")
            or flask_session.get("bb_session_id")
            or ""
        ).strip()
        if not store or not user or not session_id:
            raise WorkspaceError("Authentication required")
        entry = store.get_session(user["id"], session_id)
        return store, user, entry.id

    def workspace_data_pending(agent):
        """Return a fast retry response while cold-case arrays are decoding."""
        if agent is None:
            return jsonify({
                "success": False,
                "pending": True,
                "code": "workspace_agent_initializing",
                "message": "Case resources are being initialized.",
                "retry_after_ms": 250,
            }), 202
        if agent is not None and getattr(agent, "_workspace_hydration_error", ""):
            return jsonify({
                "success": False,
                "pending": False,
                "code": "workspace_hydration_failed",
                "phase": getattr(agent, "_workspace_hydration_phase", "failed"),
                "error": agent._workspace_hydration_error,
            }), 409
        if agent is not None and not getattr(agent, "_workspace_data_ready", True):
            return jsonify({
                "success": False,
                "pending": True,
                "code": "workspace_hydration_pending",
                "message": "Case resources are still loading.",
                "phase": getattr(agent, "_workspace_hydration_phase", "artifacts"),
                "retry_after_ms": 250,
            }), 202
        return None

    def dose_workspace_data_pending(agent):
        """Gate dose reads only when the dose grid itself is unavailable.

        Workspace hydration decodes large CT/mesh artifacts in the background.
        A persisted dose grid is independently sufficient for a slice overlay,
        so holding these requests behind the global hydration flag leaves the
        last painted slice on screen until an unrelated task finishes.
        """
        pending = workspace_data_pending(agent)
        if pending is None or agent is None:
            return pending
        memory = getattr(agent, "memory", None)
        if memory is None or not active_planning_id(memory):
            return pending
        if memory.retrieve("dose_distribution_gy") is not None:
            return None
        if memory.retrieve("dose_distribution_physical_gy") is not None:
            return None
        if (
            memory.retrieve("dose_distribution") is not None
            and memory.retrieve("resampled_ct") is not None
            and memory.retrieve("ct_image") is not None
        ):
            return None
        return pending

    def monitor_control_agent(session_id):
        """Resolve monitor state without synchronously hydrating a case."""
        if callable(get_cached_agent):
            cached = get_cached_agent(session_id)
            if cached is not None:
                return cached
        if not callable(get_agent):
            return None
        try:
            # The server callback installs a metadata shell and continues
            # decoding CT/planning arrays in its background hydration worker.
            return get_agent(session_id, _lightweight=True)
        except TypeError:
            # Small test/app factories may still expose the old callback
            # signature. Do not fall back to a potentially blocking cold load.
            return None

    def workspace_output_dir(category: str) -> str:
        """Return an owned artifact directory; client paths are never trusted."""
        store, user, session_id = request_case_context()
        # Direct exporters write into tool-owned directories, unlike browser
        # artifacts which pass through ``write_artifact``. Refuse a new export
        # when the account is already at its quota.
        store.ensure_capacity(user["id"], 0)
        root = store.workspace_root(user["id"], session_id, create=True) / "artifacts" / category
        root.mkdir(parents=True, exist_ok=True)
        return str(root)

    def validate_workspace_output(category: str) -> None:
        """Verify a direct exporter did not exceed the selected user's quota.

        Scientific exporters often require a filesystem directory instead of a
        stream. They remain constrained to the selected workspace and are
        checked before the result is exposed as a downloadable artifact.
        """
        _ = category
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        if not store or not user:
            raise WorkspaceError("Authentication required")
        store.ensure_capacity(user["id"], 0)

    def artifact_download_url(relative_path: str) -> str:
        """Return the authenticated download route for an active-case artifact."""
        _, _, session_id = request_case_context()
        safe_path = "/".join(part for part in str(relative_path).replace("\\", "/").split("/") if part and part not in {".", ".."})
        return f"/api/sessions/{session_id}/artifacts/{safe_path}"

    def checkpoint_operation(agent: Any, state: str, message: str, *, checkpoint: Optional[Dict[str, Any]] = None) -> None:
        """Record a recoverable long-operation state without blocking planning."""
        try:
            store, user, session_id = request_case_context()
        except WorkspaceError:
            return
        if agent is None:
            return
        operation = {
            "state": state,
            "message": message,
            "updated_at": time.time(),
            "checkpoint": checkpoint or {},
        }
        if state == "running":
            operation["started_at"] = time.time()
        try:
            # Operation checkpoints are progress metadata, not a reason to
            # serialize the full Agent on the planning thread. The store
            # debounces these writes and performs array work in its daemon
            # checkpoint worker, preserving the latest operation payload.
            store.schedule_agent_checkpoint(
                user["id"],
                session_id,
                agent,
                "operation.checkpoint",
                operation=operation,
            )
        except WorkspaceError:
            logger.warning("Unable to checkpoint workspace operation", exc_info=True)

    def fallback_task_response(task: ChatTask) -> str:
        """Build a real answer when a structured dose turn has no final prose.

        This narrow recovery reads the current task agent's metrics only. It
        is not a replacement model and cannot invent a plan for general chat.
        """
        message = str(getattr(task, "message", "") or "")
        if not re.search(r"dose distribution|dose map|dose cloud|剂量分布|剂量云图|剂量结果", message, re.I):
            return ""
        try:
            metrics = task.agent.memory.retrieve("dose_metrics") or {}
        except Exception:
            metrics = {}
        if not isinstance(metrics, dict):
            metrics = {}
        try:
            language = str(getattr(task.agent.memory, "user_lang", "en") or "en").lower()
        except Exception:
            language = "en"
        language = "zh" if language.startswith("zh") or re.search(r"[\u3400-\u9fff]", message) else "en"

        def percent(value):
            try:
                number = float(value)
                return f"{(number * 100 if number <= 1.000001 else number):.1f}%"
            except (TypeError, ValueError):
                return None

        def dose(value):
            try:
                return f"{float(value):.2f} Gy"
            except (TypeError, ValueError):
                return None

        rows = []
        for key in ("v100", "v150", "v200"):
            value = percent(metrics.get(key))
            if value is not None:
                rows.append(f"- {key.upper()}: {value}")
        for key in ("d90", "dmean", "d2", "d2_max", "max_dose"):
            value = dose(metrics.get(key))
            if value is not None:
                rows.append(f"- {key.upper()}: {value}")
                if key in {"d2", "d2_max", "max_dose"}:
                    break
        if not rows:
            return (
                "当前病例还没有可用的剂量分布数据。请先完成剂量计算。"
                if language == "zh"
                else "No dose distribution is available for this case yet. Run dose calculation first."
            )
        if language == "zh":
            return "当前剂量分布结果如下：\n\n" + "\n".join(rows) + "\n\n可在 Analysis 面板查看完整 DVH 和 OAR 剂量。"
        return "Current dose distribution results:\n\n" + "\n".join(rows) + "\n\nOpen Analysis to inspect the full DVH and OAR dose."

    def finalize_chat_task(task: ChatTask) -> bool:
        """Persist the detached task's result without relying on a browser.

        The browser normally persists its visible transcript.  That writer is
        absent while the user is viewing another case, so the background task
        must also write the user turn, trace, and final answer to the owning
        workspace.  Adjacent duplicate suppression keeps this compatible with
        a browser that remained connected for the whole turn.
        """
        store = current_app.extensions.get("brachybot_workspace_store")
        if store is None:
            return False
        final_status = str(task.completion_status or task.status or "failed")
        state = "ready" if final_status == "completed" else "interrupted"
        operation = {
            "state": state,
            "message": (
                "Chat response completed" if state == "ready"
                else (task.error or "Chat response was interrupted")
            ),
            "updated_at": time.time(),
            # The transcript is committed before the task emits `done`; the
            # large Agent arrays are persisted by the background checkpoint
            # below. Keep this marker explicit for restart diagnostics.
            "persist_state": "pending",
            "checkpoint": {
                "kind": "chat",
                "task_id": task.task_id,
                "status": final_status,
                "event_count": task.event_count(),
            },
        }
        try:
            snapshot = store.load_snapshot(task.user_id, task.session_id)
            chat = snapshot.get("chat") if isinstance(snapshot.get("chat"), dict) else {}
            messages = list(chat.get("messages") or [])

            def append_message(
                message_type: str,
                content: str,
                steps: Any = None,
                timestamp_ms: Optional[int] = None,
                message_id: str = "",
                request_id: str = "",
                attachments: Any = None,
                turn_sequence: Optional[int] = None,
                reply_to_message_id: str = "",
            ) -> None:
                content = str(content or "")
                if not content and message_type != "thinking":
                    if not attachments:
                        return
                message_kind = (
                    "execution_trace"
                    if message_type == "thinking"
                    else "assistant_final"
                    if message_type == "bot-response"
                    else "user_message"
                    if message_type == "user"
                    else message_type
                )
                sequence = (
                    int(turn_sequence)
                    if turn_sequence is not None
                    else 1
                    if message_kind == "execution_trace"
                    else 0
                    if message_kind == "user_message"
                    else 2
                )
                candidate = {
                    "type": message_type,
                    "content": content,
                    "steps": steps,
                    # Preserve the task start time for the user turn.  A
                    # detached browser can finalize this transcript long
                    # after the request was entered; using the finish time
                    # for every row makes restored histories appear to have
                    # been sent all at once.
                    "timestamp": int(
                        timestamp_ms
                        if timestamp_ms is not None
                        else (task.finished_at or time.time()) * 1000
                    ),
                    "id": str(message_id or uuid4().hex),
                    "request_id": str(request_id or task.request_id),
                    "message_kind": message_kind,
                    "turn_sequence": sequence,
                }
                response_language = str(getattr(task, "response_language", "") or "")[:8]
                if response_language:
                    # The language belongs to the turn, not to the current
                    # global UI language.  Persist it on every durable row so
                    # a refreshed Trace renders in the language used for the
                    # original request.
                    candidate["response_language"] = response_language
                    candidate["trace_language"] = response_language
                if reply_to_message_id:
                    candidate["reply_to_message_id"] = str(reply_to_message_id)
                if attachments:
                    candidate["attachments"] = list(attachments)

                existing = None
                for record in messages:
                    if not isinstance(record, dict):
                        continue
                    if message_id and str(record.get("id") or "") == str(message_id):
                        existing = record
                        break
                    if (
                        request_id
                        and str(record.get("request_id") or "") == str(request_id)
                        and record.get("type") == message_type
                    ):
                        existing = record
                        break
                if existing is not None:
                    if content:
                        existing["content"] = content
                    if steps:
                        merged = {}
                        order = []
                        for index, step in enumerate(
                            list(existing.get("steps") or []) + list(steps or [])
                        ):
                            if not isinstance(step, dict):
                                continue
                            key = str(
                                step.get("id")
                                or (
                                    f"{step.get('type', '')}:"
                                    f"{step.get('tool', '')}:"
                                    f"{step.get('parent_tool', '')}:"
                                    f"{step.get('title', '')}:{index}"
                                )
                            )
                            if key not in merged:
                                order.append(key)
                            merged[key] = step
                        existing["steps"] = [merged[key] for key in order]
                    if attachments:
                        known = {
                            str(item.get("id") or item.get("url") or "")
                            for item in (existing.get("attachments") or [])
                            if isinstance(item, dict)
                        }
                        combined = list(existing.get("attachments") or [])
                        for item in attachments:
                            if not isinstance(item, dict):
                                continue
                            key = str(item.get("id") or item.get("url") or "")
                            if key and key not in known:
                                combined.append(item)
                                known.add(key)
                        existing["attachments"] = combined
                    previous_timestamp = int(existing.get("timestamp") or 0)
                    candidate_timestamp = int(candidate.get("timestamp") or 0)
                    if previous_timestamp and candidate_timestamp:
                        existing["timestamp"] = min(previous_timestamp, candidate_timestamp)
                    elif candidate_timestamp:
                        existing["timestamp"] = candidate_timestamp
                    existing["request_id"] = candidate["request_id"]
                    existing["message_kind"] = candidate["message_kind"]
                    existing["turn_sequence"] = candidate["turn_sequence"]
                    if candidate.get("response_language"):
                        existing["response_language"] = candidate["response_language"]
                        existing["trace_language"] = candidate["trace_language"]
                    if candidate.get("reply_to_message_id"):
                        existing["reply_to_message_id"] = candidate["reply_to_message_id"]
                    return

                previous = messages[-1] if messages else None
                if (
                    previous
                    and previous.get("type") == candidate["type"]
                    and str(previous.get("content") or "") == content
                    and not request_id
                ):
                    return
                messages.append(candidate)

            # Do not expose an internal uploaded-image path in the durable
            # transcript; the browser's visible user bubble contains the
            # original request without that server detail.
            display_message = task.message.split("\n\n[Uploaded image path:", 1)[0]
            task_created_ms = int(task.created_at * 1000)

            def existing_same_turn_state() -> tuple[bool, bool, bool]:
                """Avoid replaying a turn already committed by the browser.

                The live SSE client and the detached task finalizer can finish
                in either order. A complete JSON hash is intentionally not
                sufficient because the two writers attach different timestamps
                and terminal step details. Match the authenticated task's
                creation time and user text, then require an assistant answer
                before treating the turn as already durable. Legitimate repeat
                questions remain separate when they were sent at another time.
                """
                for index, record in enumerate(messages):
                    if (
                        isinstance(record, dict)
                        and str(record.get("request_id") or "") == task.request_id
                    ):
                        matching = [
                            row
                            for row in messages
                            if isinstance(row, dict)
                            and str(row.get("request_id") or "") == task.request_id
                        ]
                        return (
                            any(
                                row.get("type") == "bot-response"
                                and str(row.get("content") or "").strip()
                                for row in matching
                            ),
                            any(row.get("type") == "user" for row in matching),
                            any(
                                row.get("type") == "thinking" and row.get("steps")
                                for row in matching
                            ),
                        )
                    if not isinstance(record, dict) or record.get("type") != "user":
                        continue
                    if str(record.get("content") or "") != display_message:
                        continue
                    try:
                        record_ms = int(float(record.get("timestamp") or 0))
                    except (TypeError, ValueError):
                        record_ms = 0
                    if record_ms and abs(record_ms - task_created_ms) > 120000:
                        continue
                    has_trace = False
                    for following in messages[index + 1:]:
                        if not isinstance(following, dict):
                            continue
                        if following.get("type") == "user":
                            break
                        if following.get("type") == "thinking" and following.get("steps"):
                            has_trace = True
                        if following.get("type") == "bot-response" and str(following.get("content") or "").strip():
                            return True, True, has_trace
                    # A live browser may have persisted the user and trace,
                    # but not the final answer yet. The detached finalizer
                    # must append the answer while reusing those existing
                    # rows; otherwise a reconnect creates a second Trace.
                    return False, True, has_trace
                return False, False, False

            turn_already_committed, turn_has_user, turn_has_trace = existing_same_turn_state()
            if not turn_has_user and not task.internal_followup:
                # Keep the task creation timestamp explicit in the durable
                # transcript. This is the source of truth when a browser
                # reconnects after the live SSE stream has disappeared.
                append_message(
                    "user",
                    display_message,
                    timestamp_ms=int(task.created_at * 1000),
                    message_id=task.user_message_id,
                    request_id=task.request_id,
                )
            # ``workspace_checkpoint`` is an internal save operation, never a
            # user-facing workflow step.  Filter legacy journals as well as
            # live events so an older interrupted turn cannot resurrect a
            # fake pending step on the next session restore.
            persisted_steps = []
            for raw_step in list(task.steps):
                if str(raw_step.get("tool") or "") == "workspace_checkpoint":
                    continue
                step = dict(raw_step)
                presentation_tool = str(step.get("tool") or "")
                if presentation_tool in {"ui_screenshot", "ui_content"}:
                    metadata = (
                        dict(step.get("metadata") or {})
                        if isinstance(step.get("metadata"), dict)
                        else {}
                    )
                    if presentation_tool == "ui_content":
                        command = (
                            dict(metadata.get("content_command") or {})
                            if isinstance(metadata.get("content_command"), dict)
                            else {}
                        )
                        # Persist only the user-safe command summary. Raw
                        # model instructions, paths, and browser internals
                        # are not durable chat content.
                        step["params"] = {
                            "target": str(command.get("target") or metadata.get("content_target") or ""),
                            "presentation": str(command.get("presentation") or "auto"),
                            "mode": str(command.get("mode") or "chat"),
                        }
                        step["content"] = ""
                        step["result"] = ""
                        step["metadata"] = {
                            "content_command": {
                                key: command.get(key)
                                for key in ("command", "target", "presentation", "mode", "planning_id", "object_ids")
                                if command.get(key) not in (None, "", [])
                            },
                            "trace_summary_i18n": metadata.get("trace_summary_i18n", {}),
                            "internal_only": True,
                            "user_visible": False,
                        }
                    else:
                        plan = (
                            dict(metadata.get("screenshot_plan") or {})
                            if isinstance(metadata.get("screenshot_plan"), dict)
                            else {}
                        )
                        # A recovered task can predate the SSE sanitizer, so
                        # repeat the boundary check before persisting its
                        # Trace. Preserve only stable scene identifiers and
                        # rendering controls, never model prompts or paths.
                        safe_plan = {
                            key: plan.get(key)
                            for key in (
                                "version",
                                "mode",
                                "target",
                                "views",
                                "layout",
                                "object_ids",
                                "data_tree_node_ids",
                                "highlight_object_ids",
                                "hide_unrelated",
                                "focus",
                                "slice_indices",
                                "overlays",
                            )
                            if plan.get(key) not in (None, "", [], {})
                        }
                        views = list(safe_plan.get("views") or [])
                        step["params"] = {
                            "mode": str(safe_plan.get("mode") or "chat"),
                            "views": views[:8],
                            "layout": str(safe_plan.get("layout") or "auto"),
                        }
                        step["content"] = ""
                        step["result"] = ""
                        step["metadata"] = {
                            "screenshot_plan": safe_plan,
                            "trace_summary_i18n": metadata.get(
                                "trace_summary_i18n", {}
                            ),
                            "internal_only": True,
                            "user_visible": False,
                        }
                persisted_steps.append(step)
            if persisted_steps and (not turn_already_committed or task.internal_followup):
                append_message(
                    "thinking",
                    "",
                    persisted_steps,
                    timestamp_ms=int((task.finished_at or time.time()) * 1000),
                    message_id=f"trace-{task.request_id}",
                    request_id=task.request_id,
                    turn_sequence=1,
                    reply_to_message_id=task.assistant_message_id,
                )
            # A user-cancelled turn must never resurrect buffered draft text
            # when the case is reopened. Preserve the request and trace for
            # audit, then record one explicit terminal status instead.
            if turn_already_committed and not task.internal_followup:
                # The browser already persisted the complete visible turn.
                # Do not append a second trace just because the detached
                # finalizer is also doing its durability fallback.
                pass
            elif final_status == "cancelled":
                append_message(
                    "system",
                    "Stopped.",
                    message_id=f"status-{task.request_id}",
                    request_id=task.request_id,
                )
            else:
                final_response = task.response or task.streamed_response
                screenshot_steps = [
                    step for step in persisted_steps
                    if str(step.get("tool") or "") == "ui_screenshot"
                ]
                non_screenshot_tools = [
                    step for step in persisted_steps
                    if step.get("type") == "tool"
                    and str(step.get("tool") or "") not in {
                        "ui_screenshot",
                        "fact_checker",
                        "completeness_checker",
                    }
                ]
                screenshot_capture_phase = bool(screenshot_steps) and not non_screenshot_tools
                if not final_response or re.match(
                    r"^Tools executed\. Check the execution trace above for results\.?$",
                    str(final_response).strip(),
                    re.I,
                ):
                    final_response = fallback_task_response(task) or final_response
                if screenshot_capture_phase and not task.internal_followup:
                    final_response = ""
                if final_response:
                    append_message(
                        "bot-response",
                        final_response,
                        message_id=task.assistant_message_id,
                        request_id=task.request_id,
                    )
                elif task.error:
                    append_message(
                        "error",
                        "AI error: " + task.error,
                        message_id=f"error-{task.request_id}",
                        request_id=task.request_id,
                    )

            store.save_snapshot_patch(
                task.user_id,
                task.session_id,
                {
                    "chat": {
                        "messages": messages,
                        # Keep a case-level trace as a compact, direct source
                        # for restore diagnostics. The thinking message above
                        # remains the presentation format used by the chat UI.
                        "execution_trace": persisted_steps,
                        # Only running tasks occupy ``task_id``. Keep the last
                        # id separately for audit without making a completed
                        # turn look resumable after a browser restart.
                        "task_id": None,
                        "last_task_id": task.task_id,
                        "task_status": final_status,
                    },
                    "operation": operation,
                },
                expected_revision=None,
                reason="chat.task.finalized",
            )

            # Agent checkpoints can encode CT/label/dose arrays and prune
            # superseded sidecars. They are intentionally detached from the
            # chat response: the small transcript transaction above is enough
            # for immediate replay, while this worker makes the clinical data
            # durable without blocking SSE `done`, input, or case switching.
            task.set_persistence_status("pending")
            app_instance = current_app._get_current_object()

            def persist_agent_checkpoint() -> None:
                started = time.perf_counter()
                ready_operation = {
                    **operation,
                    "persist_state": "ready",
                    "persisted_at": time.time(),
                    "checkpoint": {
                        **(operation.get("checkpoint") or {}),
                        "persist_state": "ready",
                    },
                }
                try:
                    with app_instance.app_context():
                        store.flush_agent_checkpoint(
                            task.user_id,
                            task.session_id,
                            task.agent,
                            "chat.task.finalized.background",
                            operation=ready_operation,
                        )
                    task.set_persistence_status("ready")
                    logger.info(
                        "Background workspace checkpoint completed task=%s session=%s duration_ms=%.1f",
                        task.task_id,
                        task.session_id,
                        (time.perf_counter() - started) * 1000.0,
                    )
                except WorkspaceNotFound:
                    # A deleted case must never be recreated by a late save.
                    task.set_persistence_status("discarded", "Case workspace was deleted")
                    logger.info(
                        "Background workspace checkpoint discarded task=%s session=%s duration_ms=%.1f",
                        task.task_id,
                        task.session_id,
                        (time.perf_counter() - started) * 1000.0,
                    )
                except Exception as exc:  # pragma: no cover - integration path
                    task.set_persistence_status("error", str(exc))
                    logger.exception(
                        "Background workspace checkpoint failed task=%s session=%s duration_ms=%.1f",
                        task.task_id,
                        task.session_id,
                        (time.perf_counter() - started) * 1000.0,
                    )
                    try:
                        with app_instance.app_context():
                            failed_operation = {
                                **operation,
                                "persist_state": "error",
                                "persist_error": str(exc),
                                "updated_at": time.time(),
                                "checkpoint": {
                                    **(operation.get("checkpoint") or {}),
                                    "persist_state": "error",
                                    "persist_error": str(exc),
                                },
                            }
                            store.save_snapshot_patch(
                                task.user_id,
                                task.session_id,
                                {"operation": failed_operation},
                                expected_revision=None,
                                reason="chat.task.checkpoint_failed",
                            )
                    except WorkspaceError:
                        logger.debug(
                            "Unable to persist background checkpoint failure for task %s",
                            task.task_id,
                            exc_info=True,
                        )

            checkpoint_thread = threading.Thread(
                target=persist_agent_checkpoint,
                name=f"brachy-checkpoint-{task.task_id[:8]}",
                daemon=True,
            )
            checkpoint_thread.start()
            return True
        except WorkspaceError:
            logger.warning("Unable to persist detached chat task %s", task.task_id, exc_info=True)
            return False

    def owned_case_path(path: str) -> bool:
        try:
            store, user, session_id = request_case_context()
        except WorkspaceError:
            return False
        return bool(store.owns_path(user["id"], session_id, path))

    def request_ui_session_id(data: Optional[Dict[str, Any]] = None) -> str:
        """Resolve UI bridge state from the signed selected-case cookie.

        UI bridge events used to trust a client-side ``session_id``.  That is
        unsafe once multiple accounts share one server: even a rejected agent
        lookup could otherwise expose an in-memory bridge bucket.  Existing
        payloads retain their field for compatibility but it is deliberately
        ignored here.
        """
        _ = data
        try:
            _, _, session_id = request_case_context()
        except WorkspaceError:
            return _ui_session_id("web")
        return _ui_session_id(session_id)

    def task_workspace_owner() -> Optional[str]:
        """Return the server-derived owner key for transient progress tasks."""
        try:
            _, user, session_id = request_case_context()
        except WorkspaceError:
            return None
        return f"{user['id']}:{session_id}"

    def checkpoint_ui_bridge(session_id: str, reason: str) -> None:
        """Persist UI-controller events that do not live in AgentMemory.

        Training feedback and UI execution events are stored in the bridge so
        tools can respond immediately. They are also clinical case state and
        therefore need a JSON checkpoint before the process can be restarted
        or the case can be reopened in a different browser.
        """
        try:
            store, user, selected = request_case_context()
        except WorkspaceError:
            return
        if session_id != _ui_session_id(selected):
            return
        # ``_ui_bucket`` initializes its map while holding the same lock, so
        # obtain the bucket before taking a second snapshot lock.
        bucket = _ui_bucket(session_id)
        with _UI_BRIDGE_LOCK:
            bridge = {
                "state": dict(bucket.get("state") or {}),
                "events": list(bucket.get("events") or []),
                "training": dict(bucket.get("training") or {}),
                "updated_at": bucket.get("updated_at"),
            }
        key = (str(user["id"]), str(selected))
        with _UI_BRIDGE_CHECKPOINT_LOCK:
            _UI_BRIDGE_CHECKPOINT_PENDING[key] = (
                store,
                user["id"],
                selected,
                bridge,
                reason,
            )
            if key not in _UI_BRIDGE_CHECKPOINT_TIMERS:
                timer = threading.Timer(0.25, _flush_ui_bridge_checkpoint, args=(key,))
                timer.daemon = True
                _UI_BRIDGE_CHECKPOINT_TIMERS[key] = timer
                timer.start()

    @app.route("/api/planning/clear", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_planning_clear():
        """Explicitly clear planning data while retaining the loaded CT."""
        agent = get_agent()
        if agent is None:
            return jsonify({"success": True, "message": "No agent to clear"})

        try:
            # Clear planning results but KEEP CT/label data
            # CT data (ct_data, ct_spacing, ct_path, ct_sitk) must persist
            # so the viewer can still display the CT after page refresh
            planning_keys = [
                # Planning results
                "dose_metrics", "total_seeds", "num_trajectories",
                "seed_plan", "dose_distribution", "dose_distribution_gy",
                "trajectories", "refined_trajectories",
                "dvh_data", "plan_config", "plan_score", "metrics",
                "seed_positions", "radiation_volume",
                "seed_plan_serialized", "manual_planning_preview",
                "manual_seeds", "manual_needles",
                # Segmentation results (will be re-generated by agent)
                "ctv_array", "ctv_mask", "ctv_label_stats", "ctv_label_map",
                "ctv_full_labels", "oar_array", "organ_names", "organ_counts",
            ]
            # Planning refreshes and long-running tools can overlap in Flask's
            # threaded server. Mutate the memory map under its canonical lock.
            with agent.memory._lock:
                for key in planning_keys:
                    agent.memory.planning_results.pop(key, None)

            # Clear conversation history
            agent.memory.clear_conversation()

            logger.info("[planning_clear] Cleared planning data, kept CT data")
            return jsonify({"success": True, "message": "Planning data cleared"})
        except Exception as e:
            logger.error(f"Clear planning failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/results", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_planning_results():
        """Get latest planning results including metrics, seeds, trajectories, dose, DVH.

        Returns:
            success, metrics, seeds, trajectories, dvh, has_dose,
            dose_shape, dose_range, has_trajectories, num_trajectories.
        """
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending

        try:
            import numpy as np

            # Get data from memory
            dose_metrics = agent.memory.retrieve("dose_metrics") or {}
            total_seeds = agent.memory.retrieve("total_seeds") or 0
            num_trajectories = agent.memory.retrieve("num_trajectories") or 0
            seed_plan = agent.memory.retrieve("seed_plan")
            seed_plan_serialized = agent.memory.retrieve("seed_plan_serialized") or []
            dose_distribution = agent.memory.retrieve("dose_distribution")
            dose_distribution_gy = agent.memory.retrieve("dose_distribution_gy")
            trajectories = agent.memory.retrieve("trajectories") or agent.memory.retrieve("refined_trajectories")

            # Build seeds list with trajectory linkage for the data tree.
            # Each trajectory is a tuple/list of the form:
            #   (entry_pt, exit_pt, target_pt, target_idx, depth, extra...)
            # and seed_plan[i] is [trajectory_descriptor, [seed_list_per_seed_pos]]
            # We pair seeds with their parent trajectory so the data tree can
            # show "Trajectory N → Seed 1, Seed 2, …".
            resampled_ct = agent.memory.retrieve("resampled_ct")
            seeds = []
            trajectories_data = []

            plan_source = seed_plan if seed_plan else seed_plan_serialized
            if plan_source:
                for i, entry in enumerate(plan_source):
                    if isinstance(entry, dict):
                        traj_descriptor = entry.get("trajectory")
                        seed_list = entry.get("seeds") or []
                    elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                        traj_descriptor = entry[0]
                        seed_list = entry[1] if len(entry) > 1 else []
                    else:
                        continue
                    # Convert trajectory descriptor to world coordinates
                    entry_pt_world = None
                    target_pt_world = None
                    try:
                        if resampled_ct is not None and traj_descriptor is not None:
                            from plans.utilizations import position_transform
                            # entry[0] can be many shapes; canonicalize
                            if isinstance(traj_descriptor, (list, tuple)) and len(traj_descriptor) >= 2:
                                entry_pt = np.array(traj_descriptor[0], dtype=np.float64).flatten()[:3]
                                target_pt = np.array(traj_descriptor[2], dtype=np.float64).flatten()[:3] if len(traj_descriptor) > 2 else None
                                entry_pt_world = position_transform(resampled_ct, entry_pt)[0].tolist()
                                if target_pt is not None:
                                    target_pt_world = position_transform(resampled_ct, target_pt)[0].tolist()
                    except Exception:
                        pass

                    trajectory_id = f"traj_{i + 1}"
                    trajectories_data.append({
                        "id": trajectory_id,
                        "index": i,
                        "entry": entry_pt_world,
                        "target": target_pt_world,
                        "seed_count": len(seed_list) if isinstance(seed_list, (list, tuple)) else 0,
                    })

                    for j, seed in enumerate(seed_list or []):
                        if isinstance(seed, dict):
                            seed_pos = seed.get("position") or seed.get("pos")
                        elif isinstance(seed, (list, tuple)) and len(seed) >= 2:
                            seed_pos = seed[0]
                        else:
                            continue
                        if seed_pos is None:
                            continue
                        # Seeds from optimal_plan() are ALREADY in world coordinates.
                        # Do NOT apply position_transform again (double-transform bug).
                        pos_world = np.array(seed_pos, dtype=np.float64).flatten()[:3].tolist()
                        seeds.append({
                            "id": f"seed_{i + 1}_{j + 1}",
                            "pos": pos_world,
                            "dose": float(dose_metrics.get("d90", 0)),
                            "trajectory_id": trajectory_id,
                        })

            # Manual edits are the authoritative current plan.  Falling back
            # to seed_plan after a seed/needle delete made the deleted objects
            # reappear in the Data Tree and viewers on the next refresh.
            manual_plan_active = bool(agent.memory.retrieve("manual_plan_active"))
            current_plan = _current_planning_snapshot(agent)
            current_needles = current_plan.get("needles") or []
            if manual_plan_active:
                seeds = []
                for index, row in enumerate(current_plan.get("seeds") or []):
                    if not isinstance(row, dict):
                        continue
                    position = row.get("position")
                    if position is None:
                        position = row.get("pos")
                    try:
                        position_values = (
                            np.asarray(position, dtype=np.float64).reshape(-1)[:3]
                        )
                    except (TypeError, ValueError):
                        continue
                    if position_values.size != 3 or not np.all(np.isfinite(position_values)):
                        continue
                    seeds.append({
                        **row,
                        "id": str(row.get("id") or f"seed_{index + 1}"),
                        "pos": position_values.tolist(),
                        "trajectory_id": str(
                            row.get("trajectory_id")
                            or row.get("needle_id")
                            or ""
                        ),
                    })
                trajectories_data = []
                for index, row in enumerate(current_needles):
                    if not isinstance(row, dict):
                        continue
                    points = row.get("points") or []
                    trajectory_id = str(
                        row.get("trajectory_id")
                        or row.get("id")
                        or f"traj_{index + 1}"
                    )
                    trajectories_data.append({
                        "id": trajectory_id,
                        "index": index,
                        "entry": points[0] if len(points) >= 1 else None,
                        "target": points[-1] if len(points) >= 2 else None,
                        "seed_count": sum(
                            1 for seed in seeds
                            if str(seed.get("trajectory_id") or "") == trajectory_id
                        ),
                    })
                total_seeds = len(seeds)
                num_trajectories = len(current_needles)

            # Build DVH data
            dvh_data = dose_metrics.get("dvh_data", {})

            # Dose shape/range
            dose_shape = None
            dose_min = None
            dose_max = None
            dose_for_stats = dose_distribution_gy if dose_distribution_gy is not None else dose_distribution
            if dose_for_stats is not None:
                try:
                    dnp = np.asarray(dose_for_stats)
                    if dnp.ndim == 3:
                        dose_shape = list(dnp.shape)
                    dose_min = float(np.min(dnp))
                    dose_max = float(np.max(dnp))
                except Exception:
                    pass

            # Include tumor_type in metrics so the client can
            # display the actual segmentation model name in the report.
            tumor_type = agent.memory.retrieve("tumor_type_used", "")
            if tumor_type and isinstance(dose_metrics, dict):
                dose_metrics["tumor_type"] = tumor_type

            current_planning_id = active_planning_id(agent.memory)
            active_run = next(
                (
                    item for item in list_planning_runs(agent.memory)
                    if str(item.get("planning_id") or "") == str(current_planning_id or "")
                ),
                {},
            )
            artifact_status = agent.memory.retrieve("manual_artifact_status") or {}
            return jsonify({
                "success": True,
                "planning_id": current_planning_id,
                "planning_label": active_run.get("label"),
                "planning_status": active_run.get("status"),
                "planning_data_version": active_run.get("data_version"),
                "artifact_status": artifact_status if isinstance(artifact_status, dict) else {},
                "metrics": dose_metrics,
                "seeds": seeds,
                "needles": current_needles,
                "trajectories": trajectories_data,
                "total_seeds": total_seeds,
                "num_trajectories": num_trajectories,
                "has_trajectories": bool(trajectories) or len(trajectories_data) > 0,
                "dvh": dvh_data,
                "has_dose": dose_for_stats is not None,
                "dose_shape": dose_shape,
                "dose_min": dose_min,
                "dose_max": dose_max,
                "dose_units": DOSE_MODEL_UNITS,
                "dose_scale_gy": _saved_dose_scale_gy(agent),
            })
        except Exception as e:
            logger.error(f"Get planning results failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/runs", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_planning_runs():
        """List the session's saved planning runs without loading meshes."""
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"success": False, "error": "Agent not available"}), 500
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending
        try:
            runs = list_planning_runs(agent.memory)
            return jsonify({
                "success": True,
                "active_planning_id": active_planning_id(agent.memory),
                "runs": runs,
            })
        except Exception as exc:
            logger.exception("Unable to list planning runs")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/planning/runs/<planning_id>/activate", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_activate_planning_run(planning_id: str):
        """Make one saved Planning the active alias for this Session.

        Activation is intentionally separate from a visibility-only browser
        toggle: all downstream APIs (Dose, DVH, Report and Surgical Guide)
        must read the same active planning ID after this transaction.
        """
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"success": False, "error": "Agent not available"}), 500
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending
        try:
            summary = activate_planning_run(agent, planning_id)
            return jsonify({
                "success": True,
                "active_planning_id": str(planning_id),
                "planning": summary,
                # Clinical arrays stay behind the existing planning/mesh
                # endpoints.  Returning the raw snapshot here would attempt
                # to JSON-encode Numpy/SimpleITK objects and make activation
                # fail for exactly the large cases this endpoint is for.
                "requires_refresh": True,
            })
        except KeyError as exc:
            return jsonify({"success": False, "error": str(exc)}), 404
        except Exception as exc:
            logger.exception("Unable to activate planning run %s", planning_id)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/manual_planning/restore_algorithm_plan", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_manual_planning_restore_algorithm_plan():
        """Activate the original completed algorithm Planning without recompute.

        Manual edits live in child Planning runs. Restoring a Seed therefore
        means activating the immutable algorithm parent, including its dose,
        DVH, report-owned guide, and guide skin snapshot, rather than moving
        one point and launching another expensive calculation.
        """
        data = request.get_json(silent=True) or {}
        session_id = request_ui_session_id(data)
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"success": False, "error": "Agent not available"}), 500
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending
        try:
            runs = list_planning_runs(agent.memory)
            active_id = str(active_planning_id(agent.memory) or "")
            by_id = {str(item.get("planning_id") or ""): item for item in runs}
            candidates = []
            cursor = active_id
            visited = set()
            while cursor and cursor not in visited:
                visited.add(cursor)
                current_run = by_id.get(cursor)
                if current_run:
                    candidates.append(current_run)
                    cursor = str(current_run.get("parent_planning_id") or "")
                else:
                    break
            seen_candidate_ids = {
                str(item.get("planning_id") or "") for item in candidates
            }
            candidates.extend(
                item for item in reversed(runs)
                if str(item.get("planning_id") or "") not in seen_candidate_ids
            )

            snapshots = {}

            def _snapshot_for(item):
                planning_id = str(item.get("planning_id") or "")
                if planning_id not in snapshots:
                    snapshots[planning_id] = planning_run_snapshot(agent.memory, planning_id)
                return snapshots[planning_id]

            def _is_algorithm_restore_point(item):
                snapshot = _snapshot_for(item)
                if str(item.get("source") or "") == "manual_edit":
                    return False
                if str(item.get("status") or "") not in {"completed", ""}:
                    return False
                # Modern runs contain ``algorithm_plan_snapshot``. A legacy
                # completed run may only have seed-plan aliases, but it is
                # still a valid immutable restore point and must not force a
                # slow recomputation merely because of its age.
                return bool(snapshot) and any(
                    snapshot.get(key) is not None
                    for key in (
                        "algorithm_plan_snapshot",
                        "seed_plan",
                        "seed_plan_serialized",
                        "manual_seeds",
                        "dose_distribution",
                        "dose_distribution_gy",
                    )
                )

            target = next((item for item in candidates if _is_algorithm_restore_point(item)), None)
            if target is None:
                return jsonify({
                    "success": False,
                    "error": "No completed algorithm Planning is available for restore.",
                    "code": "algorithm_baseline_missing",
                }), 409

            target_id = str(target.get("planning_id") or "")
            summary = activate_planning_run(agent, target_id)
            snapshot = _snapshot_for(target)
            # Activate first, then emit the same public snapshot contract used
            # by the Viewer.  This keeps restore/conflict callbacks on the
            # one-based IDs the Data Tree is already rendering.
            restored_snapshot = _current_planning_snapshot(agent)
            return jsonify({
                "success": True,
                "session_id": session_id,
                "active_planning_id": target_id,
                "planning_id": target_id,
                "planning": summary,
                "seeds": list(restored_snapshot.get("seeds") or []),
                "needles": list(restored_snapshot.get("needles") or []),
                "artifact_status": snapshot.get("manual_artifact_status") or snapshot.get("artifact_status") or {},
                "restored_algorithm_plan": True,
                "requires_refresh": True,
            })
        except KeyError as exc:
            return jsonify({"success": False, "error": str(exc)}), 404
        except Exception as exc:
            logger.exception("Unable to restore the algorithm planning run")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/planning/show_step", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_planning_show_step():
        """Show specific planning step results and return data for UI update."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        step = data.get("step", "all")

        try:
            import numpy as np

            # Get all planning data
            dose_metrics = agent.memory.retrieve("dose_metrics") or {}
            total_seeds = agent.memory.retrieve("total_seeds") or 0
            seed_plan = agent.memory.retrieve("seed_plan")
            trajectories = agent.memory.retrieve("trajectories") or agent.memory.retrieve("refined_trajectories")
            dose_distribution = agent.memory.retrieve("dose_distribution")

            result = {
                "success": True,
                "step": step,
                "planning_id": active_planning_id(agent.memory),
            }

            if step in ("trajectories", "trajectory_init", "trajectory_refine", "all"):
                result["trajectories"] = trajectories or []
                result["num_trajectories"] = len(trajectories) if trajectories else 0

            if step in ("seeds", "seed_planning", "all"):
                result["seed_plan"] = seed_plan or []
                result["total_seeds"] = total_seeds

            if step in ("dose", "dose_calc", "dose_distribution", "all"):
                result["has_dose"] = dose_distribution is not None
                if dose_distribution is not None:
                    result["dose_range"] = [float(np.min(dose_distribution)), float(np.max(dose_distribution))]
                    result["dose_units"] = DOSE_MODEL_UNITS
                    result["dose_scale_gy"] = DOSE_MODEL_SCALE_GY

            if step in ("dvh", "dose_eval", "metrics", "all"):
                result["metrics"] = dose_metrics
                result["dvh"] = dose_metrics.get("dvh_data", {})

            return jsonify(result)
        except Exception as e:
            logger.error(f"Show step results failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/segmentation", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_segmentation():
        """MANUAL segmentation (2026-06-15) — runs CTV or OAR
        segmentation directly without going through the LLM agent.
        Used by the Step-by-Step manual planning buttons in the Input
        panel. The user wanted a "manual UI" that doesn't require
        chatting with the LLM at all.

        Request: { kind: 'ctv' | 'oar', image_path: '...', tumor_type?: 'nnunet_pancreatic' | ..., label_path?: '...' }
        Returns: { success, kind, label_counts, total_labels, ... }
        """
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        # Do not mutate a lightweight shell while its case-owned arrays are
        # being restored.  A background hydration finishing after this write
        # would otherwise overwrite the newly imported mask and remove its
        # Data Tree nodes.  The browser retries this 202 response.
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending

        data = request.get_json() or {}
        kind = data.get("kind", "ctv")
        image_path = data.get("image_path", "")
        tumor_type = data.get("tumor_type")
        label_path = data.get("label_path")
        if not image_path:
            return jsonify({"error": "image_path is required"}), 400
        if not _validate_path(image_path, purpose="read") or not owned_case_path(image_path):
            return jsonify({"error": "Invalid image_path"}), 400
        if label_path and (not _validate_path(label_path, purpose="read") or not owned_case_path(label_path)):
            return jsonify({"error": "Invalid label_path"}), 400
        if label_path:
            geometry_error = _validate_label_geometry(image_path, label_path)
            if geometry_error:
                return jsonify({
                    "success": False,
                    "kind": kind,
                    "error": geometry_error,
                    "hint": "Resample the mask onto the exact CT grid before uploading it.",
                }), 422

        checkpoint_operation(
            agent,
            "running",
            f"Manual {kind.upper()} segmentation is running",
            checkpoint={"kind": "segmentation", "segmentation_kind": kind, "tumor_type": tumor_type},
        )
        try:
            # Dispatch to the appropriate tool.
            if kind == "ctv":
                from tool_factory.CTV_seg import CTVSegmentationTool
                tool = CTVSegmentationTool()
                kwargs = {"image_path": image_path}
                if tumor_type:
                    kwargs["tumor_type"] = tumor_type
                if label_path:
                    kwargs["label_path"] = label_path
                result = tool.execute(**kwargs)
            elif kind == "oar":
                from tool_factory.OAR_seg import OARSegmentationTool
                tool = OARSegmentationTool()
                kwargs = {"image_path": image_path}
                if label_path:
                    kwargs["label_path"] = label_path
                result = tool.execute(**kwargs)
            else:
                return jsonify({"error": f"Unknown segmentation kind: {kind}"}), 400

            if not result.success:
                checkpoint_operation(
                    agent,
                    "interrupted",
                    f"Manual {kind.upper()} segmentation did not complete",
                    checkpoint={
                        "kind": "segmentation",
                        "segmentation_kind": kind,
                        "error": str(result.error or result.message or "unknown error"),
                    },
                )
                return jsonify({
                    "success": False,
                    "kind": kind,
                    "tumor_type": tumor_type,
                    "clarification_required": bool((getattr(result, "metadata", {}) or {}).get("clarification_required")),
                    "clarification_question": (getattr(result, "metadata", {}) or {}).get("clarification_question"),
                    "error": result.error or result.message or "Segmentation failed",
                }), 422

            # Store under the standard memory keys the rest of the
            # system reads from (ctv_label_data, oar_label_data, etc.).
            if kind == "ctv" and hasattr(agent, "memory"):
                meta = getattr(result, "metadata", {}) or {}
                mask = None
                for key in ("ctv_array", "mask_array", "ctv_mask", "mask"):
                    if meta.get(key) is not None:
                        mask = meta[key]
                        break
                if mask is not None:
                    try:
                        agent.memory.store("ctv_label_data", mask)
                        agent.memory.store("ctv_array", meta.get("ctv_array", mask))
                        agent.memory.store("ctv_mask", meta.get("ctv_mask", mask))
                        agent.memory.store("ctv_segmented", True)
                        if meta.get("tumor_type_used"):
                            agent.memory.store("tumor_type_used", meta["tumor_type_used"])
                        # Always overwrite provenance, including ``None``.
                        # A new uploaded CTV must not inherit full labels or
                        # tumor metadata from the previous case/mask.
                        agent.memory.store("ctv_source", meta.get("ctv_source"))
                        agent.memory.store("label_grid_orientation", meta.get("label_grid_orientation") or "LPI")
                        agent.memory.store("ctv_full_labels", meta.get("full_label_array"))
                        agent.memory.store("ctv_embedded_oar_array", meta.get("oar_array"))
                        if label_path:
                            # Keep both historical and canonical memory keys
                            # so auto-tool parameter preparation and manual
                            # UI uploads resolve the same case-owned mask.
                            agent.memory.store("ctv_path", label_path)
                            agent.memory.store("ctv_mask_path", label_path)
                        if meta.get("label_map"):
                            agent.memory.store("ctv_label_map", meta["label_map"])
                        if meta.get("label_stats"):
                            agent.memory.store("ctv_label_stats", meta["label_stats"])
                        if meta.get("ctv_volume_mm3") is not None:
                            agent.memory.store("ctv_volume_mm3", meta["ctv_volume_mm3"])
                        if meta.get("ctv_voxel_count") is not None:
                            agent.memory.store("ctv_voxels", meta["ctv_voxel_count"])
                    except Exception as e:
                        logger.warning(f"store ctv_label_data failed: {e}")
            elif kind == "oar" and hasattr(agent, "memory"):
                # OAR tool returns metadata["oar_array"], metadata["organ_names"], etc.
                meta = getattr(result, "metadata", {}) or {}
                oar_array = meta.get("oar_array")
                if oar_array is not None:
                    try:
                        agent.memory.store("oar_array", oar_array)
                        agent.memory.store("oar_label_data", oar_array)
                        agent.memory.store("oar_segmented", True)
                        if label_path:
                            agent.memory.store("oar_path", label_path)
                            agent.memory.store("oar_mask_path", label_path)
                        # Replace names/counts even when the uploaded mask has
                        # no anatomical ontology. The OAR tool deliberately
                        # emits numbered names for that case.
                        agent.memory.store("organ_names", meta.get("organ_names") or {})
                        agent.memory.store("organ_counts", meta.get("organ_counts") or {})
                        agent.memory.store(
                            "oar_source",
                            meta.get("oar_source") or ("uploaded_unknown" if label_path else "unknown_model"),
                        )
                        agent.memory.store(
                            "oar_mask_provenance",
                            meta.get("oar_mask_provenance") or ("uploaded_unknown" if label_path else "model"),
                        )
                        # A user-provided multi-label mask is a complete OAR
                        # volume even when its labels have no anatomical
                        # ontology.  Keeping this flag explicit prevents the
                        # next chat turn or workspace restore from treating
                        # the import as an incomplete result and silently
                        # replacing it with a model/CTV fallback.
                        agent.memory.store("oar_is_full", True)
                        agent.memory.store("label_grid_orientation", meta.get("label_grid_orientation") or "LPI")
                    except Exception as e:
                        logger.warning(f"store oar data failed: {e}")

            meta = getattr(result, "metadata", {}) or {}
            label_counts = meta.get("organ_counts", {}) or meta.get("label_counts", {}) or meta.get("labels_found", {}) or {}
            organ_names = {
                str(key): str(value)
                for key, value in (meta.get("organ_names") or {}).items()
            } if kind == "oar" else {}
            organ_counts = {
                str(key): int(value)
                for key, value in (meta.get("organ_counts") or {}).items()
                if isinstance(value, (int, float))
            } if kind == "oar" else {}
            # Return the same normalized object consumed by /viewer/organs.
            # This makes the upload response a complete control-plane update;
            # the browser does not have to wait for a binary volume request or
            # a later 3D reconstruction just to create Data Tree nodes.
            if kind == "oar":
                # Model tools historically keyed ``organ_counts`` by the
                # anatomical name while ``organ_names`` is keyed by numeric
                # label.  Uploaded masks use numeric keys for both.  Build
                # this response from the label map and resolve either count
                # convention so both paths expose the same contract.
                label_ids = list(organ_names) or [
                    key for key in organ_counts
                    if str(key).lstrip("-").isdigit()
                ]
                organs = {}
                for index, raw_label_id in enumerate(label_ids):
                    label_id = str(raw_label_id)
                    name = organ_names.get(label_id, f"OAR {index + 1}")
                    count = organ_counts.get(label_id)
                    if count is None:
                        count = organ_counts.get(raw_label_id)
                    if count is None:
                        count = organ_counts.get(name, 0)
                    organs[label_id] = {
                        "name": name,
                        "voxel_count": int(count or 0),
                    }
            else:
                organs = {}
            checkpoint_operation(
                agent,
                "ready",
                f"Manual {kind.upper()} segmentation completed",
                checkpoint={"kind": "segmentation", "segmentation_kind": kind, "completed": True},
            )
            if kind == "ctv" and str(tumor_type or "").startswith("biomedparse_"):
                from tool_factory.CTV_seg.biomedparse_v2 import record_pipeline_validation
                record_pipeline_validation(
                    str(tumor_type),
                    result_save_path_passed=True,
                )
            return jsonify({
                "success": True,
                "kind": kind,
                "tumor_type": tumor_type,
                "label_counts": label_counts,
                "total_labels": len(label_counts),
                # The browser can populate the Data Tree immediately from the
                # authoritative import result while the binary label volume is
                # fetched and cached in the background.
                "organs": organs,
                "organ_names": organ_names,
                "organ_counts": organ_counts,
                "oar_source": str(meta.get("oar_source") or "") if kind == "oar" else "",
                "oar_mask_provenance": str(meta.get("oar_mask_provenance") or "") if kind == "oar" else "",
            })
        except Exception as e:
            logger.error(f"Manual segmentation ({kind}) failed: {e}")
            checkpoint_operation(
                agent,
                "interrupted",
                f"Manual {kind.upper()} segmentation failed",
                checkpoint={"kind": "segmentation", "segmentation_kind": kind, "error": str(e)},
            )
            return jsonify({"error": str(e)}), 500

    @app.route("/api/ctv/models", methods=["GET"])
    @require_api_key
    def api_ctv_models():
        """Return CTV model resources with local availability and source links."""
        try:
            from tool_factory.CTV_seg.model_catalog import filter_catalog

            site = request.args.get("site") or None
            include_experimental = request.args.get("include_experimental", "1").lower() not in ("0", "false", "no")
            # Keep the complete research catalog available to the agent/tool,
            # while the human selector receives only explicitly UI-visible
            # entries.  This prevents the unvalidated pancreatic VoCo alias
            # from looking like a second production model.
            models = filter_catalog(
                site=site,
                include_experimental=include_experimental,
                for_ui=True,
            )
            return jsonify({"success": True, "models": models, "count": len(models)})
        except Exception as e:
            logger.error(f"CTV model catalog failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/ctv/models/validation", methods=["POST"])
    @require_api_key
    def api_ctv_model_validation():
        """Record a browser-observed Data Tree/viewer integration success."""
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"success": False, "error": "Agent not available"}), 500
        payload = request.get_json(silent=True) or {}
        tumor_type = str(payload.get("tumor_type") or "").strip()
        current_type = str(agent.memory.retrieve("tumor_type_used", "") or "").strip()
        if not tumor_type.startswith("biomedparse_") or tumor_type != current_type:
            return jsonify({"success": False, "error": "Tumor type does not match the active case"}), 409
        if not bool(agent.memory.retrieve("ctv_segmented", False)):
            return jsonify({"success": False, "error": "No active CTV result"}), 409
        from tool_factory.CTV_seg.biomedparse_v2 import record_pipeline_validation
        record_pipeline_validation(
            tumor_type,
            data_tree_viewer_passed=bool(payload.get("data_tree_viewer_passed")),
        )
        return jsonify({"success": True, "tumor_type": tumor_type})

    @app.route("/api/planning/run_step", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_planning_run_step():
        """Run a specific planning step."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        ct_image_path = data.get("ct_image_path")
        step = data.get("step", "full")

        if not ct_image_path:
            return jsonify({"error": "ct_image_path is required"}), 400
        if not _validate_path(ct_image_path, purpose="read") or not owned_case_path(ct_image_path):
            return jsonify({"error": "Invalid ct_image_path"}), 400

        try:
            # Use planning pipeline tool
            from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
            tool = PlanningPipelineTool()

            # Get config from agent; fall back to plans/config.json defaults
            # for any planning params not set on the agent (e.g. reference_direc,
            # radiation_array_params). This keeps endpoint behavior consistent
            # with the canonical config and avoids stale [0,1,0] direction.
            config = getattr(agent, 'config', {})
            try:
                import json as _json, os as _os
                _cfg_path = _os.path.join(PROJECT_ROOT, 'plans', 'config.json')
                with open(_cfg_path, encoding="utf-8") as _f:
                    _default_cfg = _json.load(_f)
            except Exception:
                _default_cfg = {}

            def _cfg(key, default=None):
                """Get config value: agent.config > plans/config.json > default."""
                if key in config:
                    return config[key]
                if key in _default_cfg:
                    return _default_cfg[key]
                return default

            # Merge radiation_array_params from default if not on agent
            _rad_params_default = _default_cfg.get("radiation_array_params", {})

            ui_state = agent.memory.get_ui_state() or {}
            planning_state = ui_state.get("planning") if isinstance(ui_state, dict) else {}
            planning_state = planning_state if isinstance(planning_state, dict) else {}
            live_ref = resolve_reference_direction_input(
                planning_state,
                {**config, **_default_cfg},
                default="auto",
            )

            checkpoint_operation(
                agent,
                "running",
                f"Planning step '{step}' is in progress",
                checkpoint={"kind": "planning", "step": step, "mode": _cfg("mode", "rule_based")},
            )
            result = tool._execute(
                ct_image_path=ct_image_path,
                step=step,
                mode=_cfg("mode", "rule_based"),
                seed_info=_cfg("seed_info"),
                planning_params={
                    "dose_value_unit": _cfg("dose_value_unit", "gy"),
                    "in_lowest_energy": _cfg("in_lowest_energy"),
                    "out_highest_energy": _cfg("out_highest_energy"),
                    "DVH_rate": _cfg("DVH_rate"),
                },
                ref_direc=live_ref,
                _agent=agent,
            )

            if result.success:
                # Store results in memory
                agent._store_tool_result("planning_pipeline", result)
                # Sanitize metadata for JSON serialization (strip non-scalar fields
                # like trajectory lists / numpy arrays — callers can read them via
                # /api/planning/show_step).
                import numpy as _np
                _meta = {}
                for _k, _v in (result.metadata or {}).items():
                    if isinstance(_v, (_np.ndarray, list, tuple)):
                        continue  # skip heavy / non-serializable
                    _meta[_k] = _v
                # Return a small, durable UI projection as part of every
                # manual-step response.  The large arrays stay in the
                # workspace sidecars, but the client can immediately rebuild
                # its Data Tree without guessing whether the tool wrote OAR or
                # planning data.
                try:
                    _organ_names = agent.memory.retrieve("organ_names") or {}
                    _organ_counts = agent.memory.retrieve("organ_counts") or {}
                    _planning = {
                        "trajectories": agent.memory.retrieve("trajectories") or [],
                        "seeds": agent.memory.retrieve("seeds") or agent.memory.retrieve("seed_plan") or [],
                        "needles": agent.memory.retrieve("needles") or [],
                        "has_dose": agent.memory.retrieve("dose_distribution") is not None
                        or agent.memory.retrieve("dose_distribution_gy") is not None,
                    }
                    _meta.update({
                        "oar_loaded": bool(agent.memory.retrieve("oar_array") is not None),
                        "organ_names": _organ_names if isinstance(_organ_names, dict) else {},
                        "organ_counts": _organ_counts if isinstance(_organ_counts, dict) else {},
                        "oar_source": agent.memory.retrieve("oar_source"),
                        "planning_projection": {
                            "trajectory_count": len(_planning["trajectories"]) if isinstance(_planning["trajectories"], list) else 0,
                            "seed_count": len(_planning["seeds"]) if isinstance(_planning["seeds"], list) else 0,
                            "needle_count": len(_planning["needles"]) if isinstance(_planning["needles"], list) else 0,
                            "has_dose": bool(_planning["has_dose"]),
                        },
                    })
                except Exception as _projection_error:
                    logger.debug("Manual planning UI projection unavailable: %s", _projection_error)
                checkpoint_operation(
                    agent,
                    "ready",
                    f"Planning step '{step}' completed",
                    checkpoint={"kind": "planning", "step": step},
                )
                return jsonify({
                    "success": True,
                    "step": step,
                    "message": result.message,
                    "metadata": _meta,
                })
            else:
                checkpoint_operation(
                    agent,
                    "interrupted",
                    f"Planning step '{step}' did not complete",
                    checkpoint={"kind": "planning", "step": step, "error": str(result.error or "unknown error")},
                )
                return jsonify({"success": False, "error": result.error}), 400

        except Exception as e:
            checkpoint_operation(
                agent,
                "interrupted",
                f"Planning step '{step}' failed",
                checkpoint={"kind": "planning", "step": step, "error": str(e)},
            )
            logger.error(f"Run planning step failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/config", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_planning_config():
        """Get planning configuration including iso-dose parameters."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        try:
            config = getattr(agent, 'config', {})
            # Read iso_dose_params from config file if not in agent config
            iso_params = config.get("iso_dose_params")
            if not iso_params:
                import json as _json
                config_path = os.path.join(PROJECT_ROOT, "plans", "config.json")
                if os.path.exists(config_path):
                    with open(config_path, "r", encoding="utf-8") as f:
                        file_config = _json.load(f)
                    iso_params = file_config.get("iso_dose_params", {})

            # Read display_3d settings from default_params.json
            # This has the relative isosurface multipliers and display settings.
            display_3d = {}
            import json as _json
            dp_path = os.path.join(PROJECT_ROOT, "config", "default_params.json")
            if os.path.exists(dp_path):
                with open(dp_path, "r", encoding="utf-8") as f:
                    dp_config = _json.load(f)
                display_3d = dp_config.get("display_3d", {})
            # Include the prescription dose so the frontend can compute
            # absolute Gy from relative multipliers.
            #
            # DoseUNet output calibration is independent from prescription:
            # current model output 1.0 is 190.8 Gy, while the default
            # prescription remains 120 Gy.
            dose_metrics = agent.memory.retrieve("dose_metrics") or {}
            plan_config = agent.memory.retrieve("plan_config") or config
            saved_scale = _saved_dose_scale_gy(agent)
            prescription_gy = resolve_prescription_gy(
                plan_config,
                dose_metrics,
                dose_scale_gy=saved_scale,
            )
            display_3d["_prescriptionGy"] = prescription_gy
            display_3d["_doseScaleGy"] = saved_scale

            return jsonify({
                "success": True,
                "iso_dose_params": iso_params or {
                    "iso_dose_values": [1.0, 1.5, 2.0, 4.0],
                    "iso_colors": [[0,1,0],[0,1,1],[1,1,0],[1,0.5,0],[1,0,0],[1,0,1],[0.5,0,0.5],[0,0.5,1]],
                    "iso_opacities": [0.3, 0.2, 0.1, 0.05],
                },
                "display_3d": display_3d,
                "dose_value_unit": "gy",
                "in_lowest_energy": prescription_gy,
            })
        except Exception as e:
            logger.error(f"Get config failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/dose_isosurface", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_planning_dose_isosurface():
        """Generate dose isosurface mesh for 3D visualization.

        Threshold is received in Gy for user-facing labels. Stored dose arrays
        remain normalized model output, so levels are converted before meshing.
        """
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        pending = dose_workspace_data_pending(agent)
        if pending is not None:
            return pending

        data = request.get_json() or {}
        threshold = data.get("threshold", 1.0)

        try:
            import numpy as np
            from skimage import measure

            # Prefer the resampled original-CT dose field. The legacy key name
            # includes "_gy", but values remain normalized model output.
            dose_array = agent.memory.retrieve("dose_distribution_gy")
            dose_in_original_ct_space = dose_array is not None
            if dose_array is None:
                dose_array = agent.memory.retrieve("dose_distribution")
            if dose_array is None:
                return jsonify({"error": "No dose distribution available"}), 400

            # CRITICAL: coordinate transform depends on which dose array we have.
            # - dose_distribution_gy: resampled to ORIGINAL CT space by _step_dose_calc
            #   → use ct_image spacing/origin/direction
            # - dose_distribution (fallback): still in PLANNING GRID space
            #   → use resampled_ct spacing/origin/direction
            # Using the wrong spacing causes isosurfaces to be offset by hundreds of mm.
            if dose_in_original_ct_space:
                ct_image = agent.memory.retrieve("ct_image")
                if ct_image is not None:
                    spacing = ct_image.GetSpacing()
                    origin = ct_image.GetOrigin()
                    direction = ct_image.GetDirection()
                    logger.info(f"[dose_isosurface] Using ct_image (original CT space) spacing={spacing}, origin={origin}")
                else:
                    spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
                    origin = agent.memory.retrieve("ct_origin") or (0.0, 0.0, 0.0)
                    direction = agent.memory.retrieve("ct_direction") or (1, 0, 0, 0, 1, 0, 0, 0, 1)
                    logger.info(f"[dose_isosurface] Using fallback spacing={spacing}")
            else:
                # dose_distribution is in planning grid space — use resampled_ct
                resampled_ct = agent.memory.retrieve("resampled_ct")
                if resampled_ct is not None:
                    spacing = resampled_ct.GetSpacing()
                    origin = resampled_ct.GetOrigin()
                    direction = resampled_ct.GetDirection()
                    logger.info(f"[dose_isosurface] Using resampled_ct (planning grid) spacing={spacing}")
                else:
                    spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
                    origin = agent.memory.retrieve("ct_origin") or (0.0, 0.0, 0.0)
                    direction = agent.memory.retrieve("ct_direction") or (1, 0, 0, 0, 1, 0, 0, 0, 1)
                    logger.info(f"[dose_isosurface] Using fallback spacing={spacing}")

            target_mask = (
                agent.memory.retrieve("ctv_array")
                if dose_in_original_ct_space
                else agent.memory.retrieve("resampled_ctv")
            )

            dose_np = np.array(dose_array)
            if dose_np.ndim != 3:
                return jsonify({"error": "Invalid dose array dimensions"}), 400

            data_min = float(dose_np.min())
            data_max = float(dose_np.max())
            logger.info(f"[dose_isosurface] threshold={threshold}, dose_range=[{data_min:.4f}, {data_max:.4f}], "
                        f"dose_shape={dose_np.shape}, spacing={spacing}, origin={origin}")

            level = float(threshold)
            dose_metrics = agent.memory.retrieve("dose_metrics") or {}
            plan_config = agent.memory.retrieve("plan_config") or {}
            dose_scale_gy = resolve_dose_scale_gy(
                plan_config,
                dose_metrics,
                dose_scale_gy=agent.memory.retrieve("dose_scale_gy"),
            )
            # The frontend sends a physical-Gy threshold. Convert it with the
            # calibration persisted by this plan (190.8 for new plans, 120
            # for historical sessions without calibration metadata).
            level_normalized = dose_gy_to_model(level, dose_scale_gy)
            logger.info(f"[dose_isosurface] {level} Gy -> {level_normalized:.4f} normalized (data range: {data_min:.4f}-{data_max:.4f})")
            prescription_gy = resolve_prescription_gy(
                plan_config,
                dose_metrics,
                default_gy=DEFAULT_PRESCRIPTION_GY,
                dose_scale_gy=dose_scale_gy,
            )
            coverage_audit = _dose_coverage_audit(
                dose_np,
                target_mask,
                level_normalized,
                threshold_gy=level,
                prescription_gy=prescription_gy,
                dose_metrics=dose_metrics,
                grid="original_ct" if dose_in_original_ct_space else "planning",
            )
            if coverage_audit and coverage_audit.get("reported_coverage_percent") is not None:
                log_method = logger.info if coverage_audit.get("consistent") is not False else logger.warning
                log_method(
                    "[dose_isosurface] %s displayed coverage=%.4f%% reported=%.4f%% delta=%+.4f pp consistent=%s",
                    coverage_audit["reported_metric"].upper(),
                    coverage_audit["coverage_percent"],
                    coverage_audit["reported_coverage_percent"],
                    coverage_audit["delta_percentage_points"],
                    coverage_audit["consistent"],
                )
            level = level_normalized
            if level <= data_min or level > data_max:
                return jsonify({"success": True, "vertices": [], "faces": [], "vertex_count": 0,
                                "face_count": 0, "threshold": threshold, "dose_range": [data_min, data_max],
                                "dose_units": DOSE_MODEL_UNITS, "dose_scale_gy": dose_scale_gy,
                                "planning_id": active_planning_id(agent.memory),
                                "dose_generation": _dose_data_generation(agent),
                                "coverage_audit": coverage_audit})

            # Use resampled_ct spacing (z,y,x -> x,y,z for marching cubes).
            # Pad only the extraction field so an isosurface that touches the
            # planning grid gets a closed outside cap instead of a hard
            # rectangular cut face in the 3D viewer.
            spacing_zyx = tuple(float(s) for s in spacing[::-1])
            dose_for_surface, surface_padding_zyx = _pad_dose_surface_volume(
                dose_np,
                fill_value=data_min,
            )
            vertices, faces, _, _ = measure.marching_cubes(
                dose_for_surface,
                level=level,
                spacing=spacing_zyx,
                allow_degenerate=False,
            )
            vertices -= surface_padding_zyx * np.asarray(spacing_zyx, dtype=np.float64)

            # Transform from planning grid voxel coords to world coords
            origin_xyz = np.array(origin[:3], dtype=np.float64)
            direction_matrix = np.array(direction[:9], dtype=np.float64).reshape(3, 3)
            # vertices are in (z,y,x) from marching_cubes with spacing_zyx, convert to (x,y,z)
            vertices_xyz = vertices[:, ::-1]
            vertices_world = (direction_matrix @ vertices_xyz.T).T + origin_xyz

            # Decimate
            if len(faces) > 80000:
                stride = max(1, len(faces) // 80000)
                faces = faces[::stride]

            return jsonify({
                "success": True,
                "vertices": vertices_world.tolist(),
                "faces": faces.tolist(),
                "vertex_count": len(vertices_world),
                "face_count": len(faces),
                "threshold": threshold,
                "dose_range": [data_min, data_max],
                "dose_units": DOSE_MODEL_UNITS,
                "dose_scale_gy": dose_scale_gy,
                "planning_id": active_planning_id(agent.memory),
                "dose_generation": _dose_data_generation(agent),
                "coverage_audit": coverage_audit,
                "surface_boundary_padding_voxels": int(_DOSE_SURFACE_BOUNDARY_PADDING_VOXELS),
            })
        except Exception as e:
            logger.error(f"Dose isosurface failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/dose_overlay", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_planning_dose_overlay():
        """Get dose distribution resampled to original CT space for 2D overlay.

        Returns metadata about the dose overlay. The actual slice data is fetched
        via the dose_overlay_slice endpoint.
        """
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        pending = dose_workspace_data_pending(agent)
        if pending is not None:
            return pending

        try:
            import numpy as np
            import SimpleITK as sitk

            # Try dose_distribution_gy first (already resampled to original CT space).
            # Values are normalized model output, not physical Gy.
            dose_np = agent.memory.retrieve("dose_distribution_gy")
            if dose_np is not None:
                dose_np = np.array(dose_np, dtype=np.float32)
                logger.info(f"[dose_overlay] Using dose_distribution_gy, shape={dose_np.shape}")
            else:
                # Fall back to dose_distribution (planning grid) and resample
                dose_array = agent.memory.retrieve("dose_distribution")
                if dose_array is None:
                    return jsonify({"success": False, "error": "No dose distribution available"})
                dose_np = np.array(dose_array, dtype=np.float32)
                logger.info(f"[dose_overlay] Using dose_distribution (planning grid), shape={dose_np.shape}")

                # Get resampled CT (planning grid) and original CT
                resampled_ct = agent.memory.retrieve("resampled_ct")
                ct_image = agent.memory.retrieve("ct_image")

                if resampled_ct is not None and ct_image is not None:
                    # Resample dose from planning grid to original CT space
                    dose_sitk = sitk.GetImageFromArray(dose_np)
                    dose_sitk.SetSpacing(resampled_ct.GetSpacing())
                    dose_sitk.SetOrigin(resampled_ct.GetOrigin())
                    dose_sitk.SetDirection(resampled_ct.GetDirection())

                    resampler = sitk.ResampleImageFilter()
                    resampler.SetReferenceImage(ct_image)
                    resampler.SetInterpolator(sitk.sitkLinear)
                    dose_original = resampler.Execute(dose_sitk)
                    dose_np = sitk.GetArrayFromImage(dose_original)
                    logger.info(f"[dose_overlay] Resampled to original CT space, shape={dose_np.shape}")

            # Get CT metadata
            ct_image = agent.memory.retrieve("ct_image")
            if ct_image is not None:
                ct_size = [int(s) for s in ct_image.GetSize()]
                ct_spacing = [float(s) for s in ct_image.GetSpacing()]
                ct_origin = [float(o) for o in ct_image.GetOrigin()]
            else:
                ct_size = list(dose_np.shape[::-1])
                ct_spacing = [0.68, 0.68, 5.0]
                ct_origin = [0.0, 0.0, 0.0]

            # Compute peak voxel (single maximum dose point across entire volume)
            peak_flat_idx = int(np.argmax(dose_np))
            peak_z, peak_y, peak_x = np.unravel_index(peak_flat_idx, dose_np.shape)

            return jsonify({
                "success": True,
                "dose_shape": list(dose_np.shape),
                "dose_min": float(dose_np.min()),
                "dose_max": float(dose_np.max()),
                "ct_spacing": ct_spacing,
                "ct_origin": ct_origin,
                "ct_size": ct_size,
                "dose_units": DOSE_MODEL_UNITS,
                "dose_scale_gy": _saved_dose_scale_gy(agent),
                "planning_id": active_planning_id(agent.memory),
                "dose_generation": _dose_data_generation(agent),
                "peak_voxel": {
                    "x": int(peak_x),
                    "y": int(peak_y),
                    "z": int(peak_z),
                },
            })
        except Exception as e:
            logger.error(f"Dose overlay data failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/dose_overlay_slice", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_planning_dose_overlay_slice():
        """Get a single dose overlay slice for a given axis and index.

        Returns the 2D dose slice in the same space as the CT slice.
        """
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        pending = dose_workspace_data_pending(agent)
        if pending is not None:
            return pending

        data = request.get_json() or {}
        axis = data.get("axis", "axial")
        slice_index = data.get("slice_index", 0)

        try:
            import numpy as np
            import SimpleITK as sitk

            # Try dose_distribution_gy first (already resampled). Values are
            # normalized model output, not physical Gy.
            dose_np = agent.memory.retrieve("dose_distribution_gy")
            if dose_np is not None:
                dose_np = np.array(dose_np, dtype=np.float32)
            else:
                # Fall back to dose_distribution and resample
                dose_array = agent.memory.retrieve("dose_distribution")
                if dose_array is None:
                    return jsonify({"success": False, "error": "No dose distribution available"})
                dose_np = np.array(dose_array, dtype=np.float32)

                # Resample to original CT space
                resampled_ct = agent.memory.retrieve("resampled_ct")
                ct_image = agent.memory.retrieve("ct_image")

                if resampled_ct is not None and ct_image is not None:
                    dose_sitk = sitk.GetImageFromArray(dose_np)
                    dose_sitk.SetSpacing(resampled_ct.GetSpacing())
                    dose_sitk.SetOrigin(resampled_ct.GetOrigin())
                    dose_sitk.SetDirection(resampled_ct.GetDirection())
                    resampler = sitk.ResampleImageFilter()
                    resampler.SetReferenceImage(ct_image)
                    resampler.SetInterpolator(sitk.sitkLinear)
                    resampler.SetInput(dose_sitk)
                    dose_original = resampler.Execute()
                    dose_np = sitk.GetArrayFromImage(dose_original)

            # Extract 2D slice (dose_np is in z,y,x order).
            # The 2D CT renderer (brachybot-viewer-volume.js) draws the
            # sagittal canvas as row=Z (vertical) / col=Y (horizontal) and the
            # coronal canvas as row=Z / col=X. Return the dose slice in that
            # same row/column orientation so the dose heatmap overlays the CT:
            #   axial   -> dose_np[z]          (Y, X) rows=Y cols=X
            #   sagittal-> dose_np[:, :, x]    (Z, Y) rows=Z cols=Y
            #   coronal -> dose_np[:, y, :]    (Z, X) rows=Z cols=X
            # The previous implementation applied a numpy .T transpose, which
            # put Z on the horizontal axis and made the dose peak appear
            # rotated 90° away from the seed positions on sagittal/coronal.
            if axis in {"axial", "z"}:
                z = max(0, min(int(slice_index), dose_np.shape[0] - 1))
                slice_2d = dose_np[z].tolist()
            elif axis in {"coronal", "y"}:
                y = max(0, min(int(slice_index), dose_np.shape[1] - 1))
                slice_2d = dose_np[:, y, :].tolist()
            else:  # sagittal
                x = max(0, min(int(slice_index), dose_np.shape[2] - 1))
                slice_2d = dose_np[:, :, x].tolist()

            return jsonify({
                "success": True,
                "slice": slice_2d,
                "dose_min": float(dose_np.min()),
                "dose_max": float(dose_np.max()),
                "dose_units": DOSE_MODEL_UNITS,
                "dose_scale_gy": _saved_dose_scale_gy(agent),
                "planning_id": active_planning_id(agent.memory),
                "dose_generation": _dose_data_generation(agent),
            })
        except Exception as e:
            logger.error(f"Dose overlay slice failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/dose_contour_slice", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_planning_dose_contour_slice():
        """Get dose contour lines for a given slice.

        Returns contour line coordinates for overlaying on 2D viewers.
        Uses iso_dose_values from config as contour levels.
        """
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        pending = dose_workspace_data_pending(agent)
        if pending is not None:
            return pending

        data = request.get_json() or {}
        axis = data.get("axis", "axial")
        slice_index = data.get("slice_index", 0)

        try:
            import numpy as np
            from skimage import measure as ski_measure

            # Get dose distribution
            dose_np = agent.memory.retrieve("dose_distribution_gy")
            if dose_np is not None:
                dose_np = np.array(dose_np, dtype=np.float32)
            else:
                dose_dist = agent.memory.retrieve("dose_distribution")
                if dose_dist is None:
                    return jsonify({"error": "No dose distribution available"}), 400
                dose_np = np.array(dose_dist, dtype=np.float32)

            # Get iso-dose values from config
            config = getattr(agent, 'config', {})
            iso_params = config.get("iso_dose_params", {})
            # iso_dose_values are stored as RELATIVE multipliers of
            # the prescription dose (1.0×Rx, 1.5×Rx, ...). The dose
            # distribution here is normalized model output. Contours use
            # relative levels directly; only labels are converted to Gy.
            #
            # Without this conversion (2026-06-16 user bug), the
            # contour endpoint called find_contours(slice_2d, level=1.0)
            # which interpreted 1.0 as **1 Gy** rather than "1×Rx ≈
            # 120 Gy". Result: every contour line landed at the dose
            # distribution's edge (around 1 Gy), which doesn't match
            # the visible dose map at all.
            iso_values_rel = iso_params.get("iso_dose_values", [1.0, 1.5, 2.0, 4.0])
            # Colors now match the colorbar (petRainbow2 colormap) and 3D isosurfaces.
            # 1.0×Rx = green, 1.5×Rx = yellow-green, 2.0×Rx = yellow, 4.0×Rx = orange.
            iso_colors_raw = iso_params.get("iso_colors", [[0,1,0], [0.53,1,0], [1,1,0], [1,0.53,0], [1,0,0]])
            iso_opacities = iso_params.get("iso_opacities", [0.7, 0.6, 0.5, 0.4])  # Increased opacity for better visibility
            # Read the physical prescription independently from the saved
            # DoseUNet calibration, then build Rx-relative isodose levels.
            dose_metrics = {}
            try:
                dose_metrics = agent.memory.retrieve("dose_metrics") or {}
            except Exception:
                pass
            plan_config = agent.memory.retrieve("plan_config") or config
            dose_scale_gy = resolve_dose_scale_gy(
                plan_config,
                dose_metrics,
                dose_scale_gy=agent.memory.retrieve("dose_scale_gy"),
            )
            prescription_gy = resolve_prescription_gy(
                plan_config,
                dose_metrics,
                dose_scale_gy=dose_scale_gy,
            )
            try:
                rf = agent.memory.retrieve("report_form") or {}
                if rf.get("planning", {}).get("prescriptionGy"):
                    prescription_gy = float(rf["planning"]["prescriptionGy"])
            except Exception:
                pass
            # The stored dose array remains raw model output. Isodose
            # multipliers are relative to the physical prescription, so first
            # calculate Gy labels and then convert each level to model units.
            iso_values_gy = [float(v) * prescription_gy for v in iso_values_rel]  # Gy for labels
            iso_values_contour = [
                dose_gy_to_model(value, dose_scale_gy)
                for value in iso_values_gy
            ]

            # Extract 2D slice from 3D dose array, in the same row/column
            # orientation as the dose-overlay slice endpoint and the 2D CT
            # canvas (row=Z vertical, col=Y/X horizontal). No transpose.
            if axis == 'axial' or axis == 'z':
                z = max(0, min(int(slice_index), dose_np.shape[0] - 1))
                slice_2d = dose_np[z]
            elif axis == 'coronal' or axis == 'y':
                y = max(0, min(int(slice_index), dose_np.shape[1] - 1))
                slice_2d = dose_np[:, y, :]
            else:  # sagittal
                x = max(0, min(int(slice_index), dose_np.shape[2] - 1))
                slice_2d = dose_np[:, :, x]

            d_min = float(dose_np.min())
            d_max = float(dose_np.max())

            # Filter iso_values to those within the dose range of this slice.
            # Use normalized levels (matching normalized dose array).
            s_min = float(slice_2d.min())
            s_max = float(slice_2d.max())
            range_tolerance = max(1e-6, abs(s_max - s_min) * 1e-6)
            valid_levels = [
                (index, c, g, r)
                for index, (c, g, r) in enumerate(zip(iso_values_contour, iso_values_gy, iso_values_rel))
                if (s_min - range_tolerance) <= c <= (s_max + range_tolerance)
            ]

            if not valid_levels:
                return jsonify({
                    "success": True,
                    "contours": [],
                    "dose_range": [d_min, d_max],
                    "slice_range": [s_min, s_max],
                    "dose_units": DOSE_MODEL_UNITS,
                    "dose_scale_gy": dose_scale_gy,
                    "planning_id": active_planning_id(agent.memory),
                    "dose_generation": _dose_data_generation(agent),
                    "slice_shape": [int(slice_2d.shape[0]), int(slice_2d.shape[1])],
                })

            # Generate contour lines using marching squares
            contours_data = []
            for level_index, level_contour, level_gy, level_rel in valid_levels:
                try:
                    contours = ski_measure.find_contours(slice_2d, level=level_contour)
                    # Convert to list of [row, col] coordinate arrays
                    contour_lines = []
                    for contour in contours:
                        if len(contour) > 2:  # Need at least 3 points for a line
                            contour_lines.append(contour.tolist())

                    if contour_lines:
                        # Get color for this level
                        color = iso_colors_raw[level_index % len(iso_colors_raw)]
                        opacity = iso_opacities[min(level_index, len(iso_opacities) - 1)] if iso_opacities else 0.3
                        contours_data.append({
                            # Return BOTH: level_gy for the 2D label so
                            # the user sees actual dose (e.g. "120")
                            # instead of the relative multiplier ("1.0"),
                            # and level_rel for color/opacity lookup.
                            "level": float(level_gy),
                            "level_rel": float(level_rel),
                            "lines": contour_lines,
                            "color": color,
                            "opacity": opacity,
                        })
                except Exception as e:
                    logger.warning(f"Contour generation failed for level {level_gy}: {e}")

            return jsonify({
                "success": True,
                "contours": contours_data,
                "dose_range": [d_min, d_max],
                "slice_range": [s_min, s_max],
                "slice_shape": [int(slice_2d.shape[0]), int(slice_2d.shape[1])],
                "dose_units": DOSE_MODEL_UNITS,
                "dose_scale_gy": dose_scale_gy,
                "planning_id": active_planning_id(agent.memory),
                "dose_generation": _dose_data_generation(agent),
            })
        except Exception as e:
            logger.error(f"Dose contour slice failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/config", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_config_get():
        """Get default hyperparameters from config file."""
        try:
            import json
            config_path = os.path.join(PROJECT_ROOT, "config", "default_params.json")
            with open(config_path, 'r', encoding="utf-8") as f:
                defaults = json.load(f)
            return jsonify({
                "success": True,
                "defaults": defaults,
                # Planning defaults are physical Gy. This separate scale
                # describes the raw DoseUNet output calibration.
                "dose_scale_gy": DOSE_MODEL_SCALE_GY,
                "default_prescription_gy": DEFAULT_PRESCRIPTION_GY,
            })
        except Exception as e:
            logger.error(f"Get config failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/device/status", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_device_status():
        """Get current GPU/CPU device allocation. The agent uses
        plans/device_manager.DeviceManager to pick the best free GPU
        at the start of each tool call; this endpoint surfaces the
        live state so the frontend can show a "GPU 0 (12GB free)"
        badge in the status bar. Tools (ctv_segmentation,
        oar_segmentation, dose engine) record which device they're
        using so the user can see the distribution."""
        try:
            from plans.device_manager import DeviceManager
            return jsonify({"success": True, **DeviceManager.instance().status()})
        except Exception as e:
            logger.error(f"Get device status failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/config", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_config():
        """Update agent configuration (hyperparameters)."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}

        try:
            # Store all parameter groups
            param_keys = [
                "seed_info", "radiation_array_params", "reference_direc",
                "ref_direc_auto", "reference_direc_mode",
                "tumor_type",
                "dose_value_unit",
                "in_lowest_energy", "out_highest_energy",
                "in_lowest_dose_gy", "out_highest_dose_gy", "DVH_rate",
                "max_iter", "rf_params", "distance_filter",
                "direc_resolution", "dl_params", "iter_rate", "replan_rate",
                "mode",
            ]
            for key in param_keys:
                if key in data:
                    agent.config[key] = data[key]
            # API updates use the current physical-Gy contract. Legacy
            # multiplier migration happens while restoring old saved plans,
            # not while accepting a new configuration request.
            value_unit = data.get("dose_value_unit") or "gy"
            if "in_lowest_energy" in data and "in_lowest_dose_gy" not in data:
                in_lowest_gy = planning_dose_value_to_gy(
                    data["in_lowest_energy"],
                    value_unit=value_unit,
                )
                agent.config["in_lowest_energy"] = in_lowest_gy
                agent.config["in_lowest_dose_gy"] = in_lowest_gy
            if "out_highest_energy" in data and "out_highest_dose_gy" not in data:
                out_highest_gy = planning_dose_value_to_gy(
                    data["out_highest_energy"],
                    value_unit=value_unit,
                )
                agent.config["out_highest_energy"] = out_highest_gy
                agent.config["out_highest_dose_gy"] = out_highest_gy
            if "in_lowest_dose_gy" in data:
                agent.config["in_lowest_energy"] = float(data["in_lowest_dose_gy"])
            if "out_highest_dose_gy" in data:
                agent.config["out_highest_energy"] = float(data["out_highest_dose_gy"])
            agent.config["dose_value_unit"] = "gy"
            agent.config["dose_scale_gy"] = DOSE_MODEL_SCALE_GY

            return jsonify({"success": True, "config": agent.config})
        except Exception as e:
            logger.error(f"Config update failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/ui/state", methods=["GET", "POST"])
    @require_api_key
    @rate_limit
    def api_ui_state():
        """Store or read frontend UI state used by agent UI control."""
        data = request.get_json(silent=True) or {}
        session_id = request_ui_session_id(data)
        # UI bridge reads and writes are control-plane operations.  A cold case
        # must not be hydrated just because the browser is restoring a slider,
        # layout, or monitor state; doing that made a reset/session switch wait
        # on CT and planning arrays.  A cached agent is still updated when one
        # already exists, while durable state remains the source of truth.
        agent = get_cached_agent(session_id) if callable(get_cached_agent) else None
        bucket = _ui_bucket(session_id)

        def _restore_durable_bridge_if_needed() -> Dict[str, Any]:
            """Return the newest bridge without letting a reset lose it.

            Bridge writes are deliberately debounced.  A user can therefore
            POST a UI state and immediately reset or switch cases before the
            250 ms writer runs.  Prefer the live bucket, then the pending
            writer payload, then the durable snapshot.  This preserves the
            fast asynchronous write path without making a small control-plane
            state disappear at an agent-cache boundary.
            """
            with _UI_BRIDGE_LOCK:
                live = {
                    "state": dict(bucket.get("state") or {}),
                    "events": list(bucket.get("events") or []),
                    "training": dict(bucket.get("training") or {}),
                    "updated_at": bucket.get("updated_at"),
                }
            if live["state"] or live["events"] or live["training"].get("active"):
                return live

            key = None
            try:
                store, user, selected = request_case_context()
                key = (str(user["id"]), str(selected))
            except WorkspaceError:
                store = user = selected = None

            if key is not None:
                with _UI_BRIDGE_CHECKPOINT_LOCK:
                    pending = _UI_BRIDGE_CHECKPOINT_PENDING.get(key)
                if pending is not None:
                    bridge = pending[3]
                    if isinstance(bridge, dict):
                        return {
                            "state": dict(bridge.get("state") or {}),
                            "events": list(bridge.get("events") or []),
                            "training": _server_support._close_stale_training_snapshot(
                                bridge.get("training") or {},
                                reason="server_restart_or_pending_restore",
                            ),
                            "updated_at": bridge.get("updated_at"),
                        }

            if store is not None and user is not None and selected:
                try:
                    snapshot = store.load_snapshot(user["id"], selected)
                    bridge = ((snapshot.get("ui") or {}).get("bridge") or {})
                    if isinstance(bridge, dict):
                        return {
                            "state": dict(bridge.get("state") or {}),
                            "events": list(bridge.get("events") or []),
                            "training": _server_support._close_stale_training_snapshot(
                                bridge.get("training") or {},
                                reason="server_restart_or_durable_restore",
                            ),
                            "updated_at": bridge.get("updated_at"),
                        }
                except WorkspaceError:
                    pass
            return live

        durable_bridge = _restore_durable_bridge_if_needed()
        if durable_bridge["state"] or durable_bridge["events"] or durable_bridge["training"].get("active"):
            with _UI_BRIDGE_LOCK:
                # Only fill an empty live bucket.  A newer browser event must
                # never be overwritten by an older disk snapshot.
                if not bucket.get("state") and not bucket.get("events") and not bucket.get("training", {}).get("active"):
                    bucket.update(durable_bridge)

        if request.method == "POST":
            state_payload = data.get("state") or data.get("ui_state") or {}
            with _UI_BRIDGE_LOCK:
                bucket["state"] = state_payload if isinstance(state_payload, dict) else {}
                bucket["updated_at"] = time.time()
            if agent is not None and hasattr(agent, "memory"):
                try:
                    agent.memory.set_ui_state(bucket["state"])
                except Exception as e:
                    logger.debug(f"ui_state memory update failed: {e}")
            checkpoint_ui_bridge(session_id, "ui.state_saved")
            return jsonify({
                "success": True,
                "session_id": session_id,
                "state_keys": list((bucket.get("state") or {}).keys()),
                "training": bucket.get("training", {}),
            })

        with _UI_BRIDGE_LOCK:
            state_copy = dict(bucket.get("state") or {})
            events_copy = list(bucket.get("events") or [])[-100:]
            training_copy = dict(bucket.get("training") or {})
        return jsonify({
            "success": True,
            "session_id": session_id,
            "state": state_copy,
            "events": events_copy,
            "training": training_copy,
        })

    @app.route("/api/ui/capabilities", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_ui_capabilities():
        """Return the UI-control contract exposed to BrachyBot and tests."""
        try:
            from tool_factory.ui_controller import CONTROL_REGISTRY
            from tool_factory.ui_screenshot import SCREENSHOT_TARGETS
            from tool_factory.ui_content import SESSION_CONTENT_TARGETS
            from tool_factory.CTV_seg.model_catalog import catalog_with_local_status
        except Exception as e:
            logger.error(f"Failed to load UI capabilities: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

        controls = {
            key: {
                "commands": value.get("commands", []),
                "values": value.get("values"),
                "value_type": value.get("value_type"),
                "range": value.get("range"),
                "destructive": bool(value.get("destructive")),
                "description": value.get("description", ""),
            }
            for key, value in CONTROL_REGISTRY.items()
        }
        execution_tools = {
            "code_executor_enabled": os.environ.get("BRACHYBOT_ENABLE_CODE_EXECUTOR", "").lower() in TRUE_VALUES,
            "shell_executor_enabled": os.environ.get("BRACHYBOT_ENABLE_SHELL_EXECUTOR", "").lower() in TRUE_VALUES,
            "shell_mode": "argv_allowlist_no_shell",
        }
        return jsonify({
            "success": True,
            "version": 1,
            "control_count": len(controls),
            "controls": controls,
            "screenshot_targets": SCREENSHOT_TARGETS,
            "session_content_targets": SESSION_CONTENT_TARGETS,
            "ctv_models": catalog_with_local_status(),
            "manual_workflow_steps": [
                "ctv_segmentation",
                "oar_segmentation",
                "trajectory_init",
                "trajectory_refine",
                "seed_planning",
                "dose_calc",
                "dose_eval",
                "surgical_guide",
            ],
            "manual_3d_planning": {
                "needles": ["create", "drag_endpoints", "restore_algorithm_position", "toggle_visibility", "set_opacity"],
                "seeds": ["add", "drag", "toggle_visibility", "set_opacity"],
                "dose_recompute": "dose_unet_spacing1mm",
                "surgical_guide": ["generate", "set_parameters", "load_version", "export_stl", "validate_stl"],
            },
            "training_monitor": {
                "live_monitoring": True,
                "retrospective_advice": True,
                "final_report_on_stop": True,
                "screenshot_targets": ["dose-overview", "dvh", "viewer-3d"],
            },
            "execution_tools": execution_tools,
        })

    @app.route("/api/ui/event", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_ui_event():
        """Record a frontend UI event and optionally return live monitor feedback."""
        data = request.get_json() or {}
        session_id = request_ui_session_id(data)
        state_payload = data.get("ui_state") or data.get("state")
        bucket = _ui_bucket(session_id)
        training_state = bucket.get("training") or {}
        request_run_id = str(data.get("monitor_run_id") or "").strip()
        active_run_id = str(training_state.get("run_id") or "").strip()
        # Every active Monitor event has a run id. Requiring an exact match
        # prevents a delayed callback from an older run being evaluated or
        # appended to the active run after a stop/start or session transition.
        monitor_run_matches = bool(
            training_state.get("active")
            and request_run_id
            and active_run_id
            and request_run_id == active_run_id
        )
        # Ordinary UI telemetry must stay lightweight. Hydrating a cold agent
        # for every click/slider move was enough to make Monitor itself feel
        # like it blocked the planning interface. Only an active monitor may
        # inspect the in-memory planning snapshot, and it never forces a cold
        # session hydration on this request path.
        agent = get_cached_agent(session_id) if monitor_run_matches and callable(get_cached_agent) else None
        language = _monitor_language(
            data.get("language")
            or (state_payload.get("language") if isinstance(state_payload, dict) else None)
            or training_state.get("language")
            or (bucket.get("state") or {}).get("language")
        )
        if isinstance(state_payload, dict):
            with _UI_BRIDGE_LOCK:
                bucket["state"] = state_payload
                bucket["updated_at"] = time.time()
            if agent is not None and hasattr(agent, "memory"):
                try:
                    agent.memory.set_ui_state(state_payload)
                except Exception as exc:
                    logger.warning("Failed to persist UI state to agent memory: %s", exc)

        event = _append_ui_event(session_id, {
            "type": data.get("type", "ui.event"),
            "label": data.get("label", ""),
            "detail": data.get("detail", {}),
            "language": language,
        })
        # The deterministic monitor checks are intentionally allowed to run
        # without a cached Agent.  A cold session must not make Monitor look
        # dead, and these helpers already degrade to event-focused guidance
        # when a clinical snapshot is unavailable.  Do not call get_agent here:
        # this request path must remain non-blocking during CT hydration.
        feedback = (
            _training_feedback_for_event(agent, session_id, event)
            if monitor_run_matches else None
        )
        suggested_screenshot = (
            _training_screenshot_for_event(agent, session_id, event, feedback)
            if monitor_run_matches else None
        )
        if feedback:
            with _UI_BRIDGE_LOCK:
                training = bucket.setdefault("training", {})
                if training.get("active"):
                    training.setdefault("feedback", []).append({"ts": time.time(), "message": feedback})
                    training["feedback"] = training["feedback"][-100:]
        checkpoint_ui_bridge(session_id, "ui.event_saved")
        return jsonify({
            "success": True,
            "event": event,
            "training": bucket.get("training", {}),
            "feedback": feedback if bucket.get("training", {}).get("active") else None,
            "feedback_raw": feedback if bucket.get("training", {}).get("active") else None,
            "feedback_localized": feedback if bucket.get("training", {}).get("active") else None,
            "suggested_screenshot": suggested_screenshot if bucket.get("training", {}).get("active") else None,
            "language": language,
            "monitor_run_id": active_run_id or None,
        })

    @app.route("/api/training/start", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_training_start():
        """Start live planning monitoring/training mode."""
        data = request.get_json() or {}
        session_id = request_ui_session_id(data)
        goal = str(data.get("goal") or "Monitor my planning workflow").strip()
        bucket = _ui_bucket(session_id)
        run_id = str(data.get("monitor_run_id") or uuid4().hex).strip()
        language = _monitor_language(
            data.get("language")
            or (data.get("ui_state") or {}).get("language")
            or (bucket.get("state") or {}).get("language")
        )
        with _UI_BRIDGE_LOCK:
            previous = bucket.get("training") or {}
            # A persisted ``active`` flag is not proof that a live browser is
            # still attached.  Browser refreshes, server restarts and evicted
            # agent instances can leave an abandoned run in the durable
            # bridge. Close that run before accepting a new one so a new
            # monitor can start without a false 409 conflict.
            if _server_support._training_is_stale(previous):
                previous = _server_support._close_stale_training_snapshot(
                    previous,
                    reason="monitor_timeout",
                )
                bucket["training"] = previous
            if previous.get("active"):
                previous_run_id = str(previous.get("run_id") or "").strip()
                if previous_run_id == run_id:
                    return jsonify({
                        "success": True,
                        "session_id": session_id,
                        "monitor_run_id": run_id,
                        "training": previous,
                        "message": "实时规划监测已启动。" if language == "zh" else "Live planning monitoring started.",
                        "language": language,
                    })
                return jsonify({
                    "success": False,
                    "error": "该病例已有正在运行的监测任务。" if language == "zh" else "A monitor run is already active for this case.",
                    "monitor_run_id": previous_run_id or None,
                }), 409
            now = time.time()
            bucket["training"] = {
                "active": True,
                "run_id": run_id,
                "goal": goal,
                "language": language,
                "started_at": now,
                "last_activity_at": now,
                "stopped_at": None,
                "events": [],
                "feedback": [],
            }
        _append_ui_event(
            session_id,
            {
                "type": "training.start",
                "label": "监测已启动" if language == "zh" else "Monitor started",
                "detail": {"goal": goal, "language": language, "run_id": run_id},
                "language": language,
            },
            include_in_training=False,
        )
        checkpoint_ui_bridge(session_id, "training.started")
        return jsonify({
            "success": True,
            "session_id": session_id,
            "monitor_run_id": run_id,
            "training": bucket["training"],
            "message": (
                "实时规划监测已启动。" if language == "zh"
                else "Live planning monitoring started."
            ),
            "language": language,
        })

    @app.route("/api/training/stop", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_training_stop():
        """Stop live monitoring and return a final deterministic training report."""
        stop_started = time.perf_counter()
        data = request.get_json() or {}
        session_id = request_ui_session_id(data)
        logger.info("[monitor_stop] request received session=%s", session_id)
        auto_close = bool(data.get("auto_close") or data.get("silent"))
        bucket = _ui_bucket(session_id)
        with _UI_BRIDGE_LOCK:
            training = bucket.setdefault("training", {})
            request_run_id = str(data.get("monitor_run_id") or "").strip()
            active_run_id = str(training.get("run_id") or "").strip()
            active = bool(training.get("active"))
            language = _monitor_language(
                data.get("language")
                or (data.get("ui_state") or {}).get("language")
                or training.get("language")
                or (bucket.get("state") or {}).get("language")
            )
            # Monitor is a Session-owned resource. A browser restored after a
            # server restart may still know an old run id, but that run is no
            # longer active. Stop must be idempotent so pagehide/session-switch
            # cleanup never becomes a user-visible error.
            if not active:
                return jsonify({
                    "success": True,
                    "already_stopped": True,
                    "no_active_run": True,
                    "session_id": session_id,
                    "monitor_run_id": active_run_id or request_run_id or None,
                    "summary_message": training.get("last_summary"),
                    "training": training,
                    "language": language,
                })
            if request_run_id and active_run_id and request_run_id != active_run_id:
                return jsonify({
                    "success": True,
                    "already_stopped": True,
                    "run_mismatch": True,
                    "no_active_run": True,
                    "session_id": session_id,
                    "monitor_run_id": active_run_id,
                    "training": training,
                    "language": language,
                })
            training["active"] = False
            training["stopped_at"] = time.time()
            training["last_activity_at"] = training["stopped_at"]
            training["closed_reason"] = str(data.get("reason") or "user").strip()
            training["auto_closed"] = auto_close
            # ``events`` is initialized for every training run. Do not use a
            # truthiness fallback here: an empty training run must stay empty
            # instead of re-counting unrelated global UI events (including
            # training.start or events from before monitoring began).
            training_events = training.get("events")
            events = list(
                training_events
                if isinstance(training_events, list)
                else (bucket.get("events") or [])
            )
            feedback = list(training.get("feedback") or [])
        # Do not synchronously hydrate CT/planning arrays while a browser is
        # leaving a case. Auto-close only records the event boundary; manual
        # Finish Monitoring may still build the deterministic advice report.
        agent = None if auto_close else monitor_control_agent(session_id)
        counts: Dict[str, int] = {}
        for event in events:
            etype = str(event.get("type", "ui.event"))
            counts[etype] = counts.get(etype, 0) + 1
        # Finish Monitoring must return promptly.  Seed/needle spacing and
        # artifact-state checks are deterministic and cheap; CT/OAR needle
        # intersection validation is intentionally deferred to the full
        # advice/quality-check path so a large volume cannot block the UI.
        advice = {} if auto_close else _build_plan_advice(agent, session_id, fast=True)
        logger.info(
            "[monitor_stop] advice built session=%s elapsed_ms=%.1f",
            session_id, (time.perf_counter() - stop_started) * 1000.0,
        )
        localized_advice = _localize_plan_advice(advice, language)
        summary = _format_training_summary(events, counts, advice, language)
        summary_message = {
            "message_id": f"assistant-monitor-{active_run_id or 'latest'}-summary",
            "request_id": f"monitor-{active_run_id or 'latest'}",
            "message_kind": "monitor_summary",
            "content": summary,
            "language": language,
            "completed_at": time.time(),
        }
        # The browser may leave this case while the final quality check is
        # running. Store a compact, case-owned summary with the monitor state
        # so hydration can restore it instead of losing the close-out message.
        with _UI_BRIDGE_LOCK:
            training["last_summary"] = summary_message
        checkpoint_ui_bridge(session_id, "training.stopped")
        logger.info(
            "[monitor_stop] response ready session=%s elapsed_ms=%.1f",
            session_id, (time.perf_counter() - stop_started) * 1000.0,
        )
        return jsonify({
            "success": True,
            "session_id": session_id,
            "monitor_run_id": active_run_id or None,
            "summary": summary,
            "event_counts": counts,
            "feedback": feedback,
            "advice": advice,
            "localized_advice": localized_advice,
            "summary_message": summary_message,
            "training": training,
            "language": language,
        })

    @app.route("/api/training/advice", methods=["GET", "POST"])
    @require_api_key
    @rate_limit
    def api_training_advice():
        """Return detailed advice for the current auto/manual plan."""
        data = request.get_json(silent=True) or {}
        session_id = request_ui_session_id(data)
        agent = monitor_control_agent(session_id)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        language = _monitor_language(
            data.get("language")
            or (data.get("ui_state") or {}).get("language")
            or ((_ui_bucket(session_id).get("state") or {}).get("language"))
        )
        advice = _build_plan_advice(agent, session_id)
        return jsonify({**advice, "localized_advice": _localize_plan_advice(advice, language), "language": language})

    @app.route("/api/readiness", methods=["GET", "POST"])
    @require_api_key
    @rate_limit
    def api_readiness():
        """Return a product-readiness checklist for the current case."""
        data = request.get_json(silent=True) or {}
        session_id = request_ui_session_id(data)
        agent = monitor_control_agent(session_id)
        return jsonify(_build_system_readiness(agent, session_id))

    @app.route("/api/manual_planning/update", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_manual_planning_update():
        """Update manual world-coordinate seeds/needles and recompute DoseUNet dose."""
        data = request.get_json() or {}
        session_id = request_ui_session_id(data)
        agent = get_agent(session_id)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        seeds = data.get("seeds") or []
        needles = data.get("needles") or []
        reason = data.get("reason") or "manual_update"
        previous_needles = data.get("previous_needles") or []
        previous_seeds = data.get("previous_seeds") if "previous_seeds" in data else None
        reproject_seeds = bool(data.get("reproject_seeds")) or reason in {"needle_drag", "manual_replan"}
        # ``update_seeds`` normally owns this validation, but callers can use
        # the Dose endpoint directly (older browsers, retries, or API users).
        # Never let such a path launch expensive dose inference for a geometry
        # that the manual-edit contract would have rejected. The check occurs
        # before forking a Planning child or invalidating any current result.
        interference = _seed_interference_report(agent, seeds, needles)
        if interference.get("status") == "attention":
            current = _current_planning_snapshot(agent)
            return jsonify({
                "success": False,
                "code": "manual_seed_interference",
                "error": "Dose update rejected: overlapping or unsafe seed spacing.",
                "session_id": session_id,
                "planning_id": active_planning_id(agent.memory),
                "planning_version": agent.memory.retrieve("manual_plan_version") or 0,
                "seeds": list(current.get("seeds") or []),
                "needles": list(current.get("needles") or []),
                "interference": interference,
                "artifact_status": agent.memory.retrieve("manual_artifact_status") or {},
            }), 422
        previous_planning_id = active_planning_id(agent.memory)
        previous_dose = None
        if previous_seeds is not None and not reproject_seeds:
            # Capture the baseline before invalidate_planning_dependents clears
            # active dose aliases. The child Planning must subtract from this
            # exact field, never from a dose belonging to a later edit.
            previous_dose_key = (
                "dose_distribution"
                if agent.memory.retrieve("manual_ai_dose")
                else "algorithm_plan_dose_distribution"
            )
            previous_dose = agent.memory.retrieve(previous_dose_key)
        planning_id = None
        created_new_planning = False
        try:
            # A completed Planning is immutable. The first dose/replan edit
            # creates a child draft; repeated edits while that draft is open
            # reuse the same planning_id instead of producing one run per
            # drag/click.
            planning_id = fork_planning_run(agent, reason=str(reason))
            created_new_planning = str(planning_id) != str(previous_planning_id or "")
            invalidate_planning_dependents(agent.memory, reason=str(reason))
            checkpoint_operation(
                agent,
                "running",
                "Manual dose update is in progress",
                checkpoint={
                    "kind": "manual_planning",
                    "reason": str(reason),
                    "seed_count": len(seeds),
                    "needle_count": len(needles),
                },
            )
            result = _compute_manual_ai_dose(
                agent,
                seeds,
                needles,
                previous_needles=previous_needles,
                previous_seeds=previous_seeds,
                previous_dose=previous_dose,
                reproject_seeds=reproject_seeds,
            )
            event = _append_ui_event(session_id, {
                "type": "manual.dose",
                "label": reason,
                "detail": {
                    "seeds": result.get("total_seeds", 0),
                    "trajectories": result.get("num_trajectories", 0),
                    "manual_preview": True,
                    "dose_engine": "dose_unet_spacing1mm",
                },
            })
            result["event"] = event
            result["advice"] = _build_plan_advice(agent, session_id)
            result["planning_id"] = planning_id
            publish_planning_run(agent, result, status="completed")
            checkpoint_operation(
                agent,
                "ready",
                "Manual dose update completed",
                checkpoint={"kind": "manual_planning", "reason": str(reason)},
            )
            return jsonify(result)
        except Exception as e:
            if created_new_planning:
                try:
                    mark_planning_run(agent, planning_id, "failed", error=str(e))
                except Exception:
                    logger.warning("Unable to roll back failed manual planning run %s", planning_id, exc_info=True)
            checkpoint_operation(
                agent,
                "interrupted",
                "Manual dose update did not complete",
                checkpoint={"kind": "manual_planning", "reason": str(reason), "error": str(e)},
            )
            logger.error(f"Manual planning update failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            error_code = getattr(e, "code", None)
            response = {"success": False, "error": str(e)}
            if error_code:
                response["code"] = error_code
                response["rejected_needle_ids"] = getattr(e, "rejected_needle_ids", [])
            return jsonify(response), 422 if error_code == "manual_needle_intersects_obstacle" else 500

    @app.route("/api/manual_planning/update_geometry", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_manual_planning_update_geometry():
        """Persist moved needle geometry without recomputing dose.

        A drag is not implicit consent to launch the expensive dose engine.
        This endpoint updates only world-coordinate needle geometry and the
        matching manual snapshot, while reusing the Data Tree obstacle gate.
        """
        data = request.get_json(silent=True) or {}
        session_id = request_ui_session_id(data)
        agent = get_agent(session_id)
        if agent is None:
            return jsonify({"success": False, "error": "Agent not available"}), 500

        planning_id = None
        created_new_planning = False

        raw_needles = data.get("needles")
        if raw_needles is None:
            raw_needles = []
        if not isinstance(raw_needles, list):
            return jsonify({"success": False, "error": "needles must be a list"}), 400

        normalized_needles = []
        try:
            for index, needle in enumerate(raw_needles):
                if not isinstance(needle, dict):
                    raise ValueError(f"Invalid needle at index {index}")
                points = needle.get("points")
                if not isinstance(points, list) or len(points) < 2:
                    raise ValueError(f"Needle {needle.get('id') or index} needs two endpoints")
                endpoints = []
                for point in (points[0], points[-1]):
                    values = np.asarray(point, dtype=np.float64).reshape(-1)[:3]
                    if values.size != 3 or not np.all(np.isfinite(values)):
                        raise ValueError(f"Invalid endpoint for needle {needle.get('id') or index}")
                    endpoints.append(values.tolist())
                normalized_needles.append({
                    "id": str(needle.get("id") or f"needle_{index}"),
                    "points": endpoints,
                    "trajectory_id": needle.get("trajectory_id"),
                })

            normalized_needles, repaired_needle_ids = _deduplicate_manual_needle_records(
                normalized_needles
            )
            if repaired_needle_ids:
                logger.warning("Repairing duplicate submitted needle IDs: %s", repaired_needle_ids)

            memory = agent.memory
            current = _current_planning_snapshot(agent)
            current_version = int(memory.retrieve("manual_plan_version") or 0)
            expected_version = data.get("expected_version")
            if expected_version is not None:
                try:
                    expected_version = int(expected_version)
                except (TypeError, ValueError):
                    return jsonify({"success": False, "error": "expected_version must be an integer"}), 400
                if expected_version != current_version:
                    return jsonify({
                        "success": False,
                        "error": "The planning data changed before this needle edit was committed.",
                        "code": "stale_manual_plan",
                        "planning_version": current_version,
                        "seeds": list(current.get("seeds") or []),
                        "needles": list(current.get("needles") or []),
                    }), 409
            ct_image = memory.retrieve("ct_image")
            if ct_image is None:
                raise ValueError("No CT image loaded")
            # A flattened/1D mask must never be handed to needle-safety
            # validation: _world_segment_hits_obstacle compares the mask shape
            # against the CT grid and fail-closes (rejects every needle) when
            # they differ. Pick only masks that match the CT grid, matching the
            # _mask_array contract used by the dose recompute path.
            expected_shape = tuple(int(value) for value in reversed(ct_image.GetSize()))
            ctv_mask = None
            for key in ("ctv_mask", "ctv_array", "ctv_full_labels"):
                candidate = memory.retrieve(key)
                if candidate is None:
                    continue
                arr = np.asarray(candidate)
                if tuple(arr.shape) == expected_shape:
                    ctv_mask = arr
                    break
            oar_mask = None
            for key in ("oar_array", "oar_label_data"):
                candidate = memory.retrieve(key)
                if candidate is None:
                    continue
                arr = np.asarray(candidate)
                if tuple(arr.shape) == expected_shape:
                    oar_mask = arr
                    break
            if normalized_needles:
                _server_support._validate_manual_needle_safety(
                    agent, normalized_needles, ct_image, ctv_mask, oar_mask
                )

            current_seeds = list(current.get("seeds") or [])
            raw_seeds = data.get("seeds")
            if raw_seeds is not None:
                if not isinstance(raw_seeds, list):
                    raise ValueError("seeds must be a list")
                raw_seeds, repaired_seed_ids = _deduplicate_manual_seed_records(raw_seeds)
                if repaired_seed_ids:
                    logger.warning("Repairing duplicate submitted seed IDs: %s", repaired_seed_ids)
                current_seeds = _normalize_manual_seed_records(
                    memory, raw_seeds, normalized_needles
                )
            if current_seeds and not normalized_needles:
                raise ValueError("A seed requires an owning needle")
            # Only fork after all validation/projection has succeeded. A
            # rejected drag must not leave an empty draft Planning selected.
            previous_planning_id = active_planning_id(memory)
            planning_id = fork_planning_run(agent, reason=str(data.get("reason") or "needle_position_only"))
            created_new_planning = str(planning_id) != str(previous_planning_id or "")
            invalidate_planning_dependents(
                memory,
                reason=str(data.get("reason") or "needle_position_only"),
            )
            planning_id = str(memory.retrieve("manual_planning_id") or planning_id or uuid4().hex)
            next_version = current_version + 1
            # Keep seeds and geometry coherent for later explicit replanning,
            # restore, reload, and session switching.
            memory.store("manual_planning_id", planning_id)
            memory.store("manual_seeds", current_seeds)
            memory.store("manual_needles", normalized_needles)
            memory.store("manual_plan_active", True)
            memory.store("manual_plan_version", next_version)
            memory.store("manual_geometry_only", True)
            reason = str(data.get("reason") or "needle_position_only")
            grouped_seeds: Dict[str, list] = {}
            for seed in current_seeds:
                grouped_seeds.setdefault(str(seed["trajectory_id"]), []).append(seed)
            serialized_plan = []
            for needle_item in normalized_needles:
                trajectory_id = str(needle_item.get("trajectory_id") or needle_item.get("id") or "")
                seed_items = grouped_seeds.get(trajectory_id, [])
                serialized_plan.append({
                    "trajectory_id": trajectory_id,
                    "needle_id": str(needle_item.get("id") or trajectory_id),
                    "trajectory": {
                        "id": trajectory_id,
                        "points": needle_item.get("points") or [],
                    },
                    "seeds": [
                        {
                            "id": seed["id"],
                            "position": seed["position"],
                            "direction": seed["direction"],
                            "trajectory_id": trajectory_id,
                        }
                        for seed in seed_items
                    ],
                    "num_seeds": len(seed_items),
                })
            # Do not replace the automatic seed_plan dose-map tuples during a
            # geometry-only edit. The manual mirror is sufficient for the
            # current draft and preserves the original plan's restore data.
            memory.store("manual_plan_serialized", serialized_plan)
            memory.store("seed_plan_serialized", serialized_plan)
            memory.store("total_seeds", len(current_seeds))
            artifact_status = _mark_manual_dependents_stale(
                memory,
                reason=reason,
                planning_version=next_version,
            )
            try:
                from web.surgical_guide import invalidate_surgical_guides
                invalidate_surgical_guides(agent, f"manual needle geometry updated: {reason}")
            except ImportError:
                pass
            publish_planning_run(agent, None, status="draft")
            event = _append_ui_event(session_id, {
                "type": "manual.needle.position_only",
                "label": reason,
                "detail": {
                    "needle_count": len(normalized_needles),
                    "planning_id": planning_id,
                    "planning_version": next_version,
                    "seed_count": len(current_seeds),
                    "artifacts_stale": True,
                    "dose_recomputed": False,
                },
            })
            checkpoint_operation(
                agent,
                "ready",
                "Needle geometry updated without dose recomputation",
                checkpoint={
                    "kind": "manual_planning",
                    "reason": reason,
                    "needle_count": len(normalized_needles),
                    "dose_recomputed": False,
                },
            )
            return jsonify({
                "success": True,
                "session_id": session_id,
                "case_id": session_id,
                "planning_id": planning_id,
                "planning_version": next_version,
                "needles": normalized_needles,
                "seeds": current_seeds,
                "artifact_status": artifact_status,
                "dose_recomputed": False,
                "event": event,
            })
        except _server_support.ManualNeedleSafetyError as exc:
            if created_new_planning:
                try:
                    mark_planning_run(agent, planning_id, "failed", error=str(exc))
                except Exception:
                    logger.warning("Unable to roll back rejected manual planning run %s", planning_id, exc_info=True)
            logger.warning("Position-only needle update rejected: %s", exc)
            return jsonify({
                "success": False,
                "error": str(exc),
                "code": exc.code,
                "rejected_needle_ids": exc.rejected_needle_ids,
            }), 422
        except Exception as exc:
            if created_new_planning:
                try:
                    mark_planning_run(agent, planning_id, "failed", error=str(exc))
                except Exception:
                    logger.warning("Unable to roll back failed manual planning run %s", planning_id, exc_info=True)
            logger.exception("Position-only needle update failed")
            return jsonify({"success": False, "error": str(exc)}), 422

    @app.route("/api/manual_planning/update_seeds", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_manual_planning_update_seeds():
        """Commit seed geometry without using dose recomputation as persistence.

        The full submitted seed list is the mutation boundary. Every seed is
        projected onto its owning needle, clamped so the physical cylinder
        remains inside the implant span, and saved under a monotonic planning
        version. A stale browser callback therefore cannot overwrite a newer
        edit, including the valid empty-list state after deleting the last seed.
        """
        data = request.get_json(silent=True) or {}
        session_id = request_ui_session_id(data)
        agent = get_agent(session_id)
        if agent is None:
            return jsonify({"success": False, "error": "Agent not available"}), 500
        raw_seeds = data.get("seeds")
        if not isinstance(raw_seeds, list):
            return jsonify({"success": False, "error": "seeds must be a list"}), 400

        memory = agent.memory
        current = _current_planning_snapshot(agent)
        try:
            needles = _submitted_manual_needles(data, current.get("needles"))
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        if not needles and raw_seeds:
            return jsonify({"success": False, "error": "A seed requires an owning needle"}), 400

        current_version = int(memory.retrieve("manual_plan_version") or 0)
        expected_version = data.get("expected_version")
        if expected_version is not None:
            try:
                expected_version = int(expected_version)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "expected_version must be an integer"}), 400
            if expected_version != current_version:
                return jsonify({
                    "success": False,
                    "error": "The planning data changed before this seed edit was committed.",
                    "code": "stale_manual_plan",
                    "planning_version": current_version,
                    "seeds": list(current.get("seeds") or []),
                    "needles": list(current.get("needles") or []),
                }), 409

        reason = str(data.get("reason") or "seed_geometry")
        previous_planning_id = active_planning_id(memory)
        planning_id = None
        created_new_planning = False
        try:
            raw_seeds, repaired_seed_ids = _deduplicate_manual_seed_records(raw_seeds)
            if repaired_seed_ids:
                logger.warning("Repairing duplicate submitted seed IDs: %s", repaired_seed_ids)
            normalized_seeds = _normalize_manual_seed_records(memory, raw_seeds, needles)
            interference = _seed_interference_report(agent, normalized_seeds, needles)
            if interference.get("status") == "attention":
                # Reject before fork/invalidate/store. The previous Planning,
                # its dose, and its guide therefore remain usable and the
                # browser can restore the pre-drag snapshot verbatim.
                return jsonify({
                    "success": False,
                    "code": "manual_seed_interference",
                    "error": "Seed geometry rejected: overlapping or unsafe seed spacing.",
                    "session_id": session_id,
                    "planning_id": active_planning_id(memory),
                    "planning_version": current_version,
                    "seeds": list(current.get("seeds") or []),
                    "needles": list(current.get("needles") or []),
                    "interference": interference,
                    "artifact_status": memory.retrieve("manual_artifact_status") or {},
                }), 422
            planning_id = fork_planning_run(agent, reason=reason)
            created_new_planning = str(planning_id) != str(previous_planning_id or "")
            invalidate_planning_dependents(memory, reason=reason)
            planning_id = str(memory.retrieve("manual_planning_id") or planning_id or uuid4().hex)
            next_version = current_version + 1
            memory.store("manual_planning_id", planning_id)
            memory.store("manual_plan_active", True)
            memory.store("manual_plan_version", next_version)
            memory.store("manual_seeds", normalized_seeds)
            memory.store("manual_needles", needles)
            grouped_seeds: Dict[str, list] = {}
            for seed in normalized_seeds:
                grouped_seeds.setdefault(str(seed["trajectory_id"]), []).append(seed)
            serialized_plan = []
            for needle in needles:
                trajectory_id = str(needle.get("trajectory_id") or needle.get("id") or "")
                seed_items = grouped_seeds.get(trajectory_id, [])
                serialized_plan.append({
                    "trajectory_id": trajectory_id,
                    "needle_id": str(needle.get("id") or trajectory_id),
                    "trajectory": {
                        "id": trajectory_id,
                        "points": needle.get("points") or [],
                    },
                    "seeds": [
                        {
                            "id": seed["id"],
                            "position": seed["position"],
                            "direction": seed["direction"],
                            "trajectory_id": trajectory_id,
                        }
                        for seed in seed_items
                    ],
                    "num_seeds": len(seed_items),
                })
            # Keep the automatic seed_plan immutable: its third tuple element
            # contains per-seed DoseUNet maps used to subtract one moved seed
            # during incremental recomputation. Manual geometry has its own
            # namespaced mirrors and must never erase those maps.
            memory.store("manual_plan_serialized", serialized_plan)
            memory.store("seed_plan_serialized", serialized_plan)
            memory.store("total_seeds", len(normalized_seeds))
            memory.store("manual_geometry_only", True)
            artifact_status = _mark_manual_dependents_stale(
                memory,
                reason=reason,
                planning_version=next_version,
            )
            try:
                from web.surgical_guide import invalidate_surgical_guides
                invalidate_surgical_guides(agent, f"seed geometry updated: {reason}")
            except ImportError:
                pass
            publish_planning_run(agent, None, status="draft")
            event = _append_ui_event(session_id, {
                "type": f"manual.seed.{reason}",
                "label": reason,
                "detail": {
                    "seed_count": len(normalized_seeds),
                    "planning_id": planning_id,
                    "planning_version": next_version,
                    "artifacts_stale": True,
                },
            })
            return jsonify({
                "success": True,
                "session_id": session_id,
                "case_id": session_id,
                "planning_id": planning_id,
                "planning_version": next_version,
                "seeds": normalized_seeds,
                "needles": needles,
                "seed_geometry": _manual_seed_geometry_settings(memory),
                "artifact_status": artifact_status,
                "event": event,
            })
        except Exception as exc:
            if created_new_planning and planning_id:
                try:
                    mark_planning_run(agent, planning_id, "failed", error=str(exc))
                except Exception:
                    logger.warning("Unable to roll back failed seed planning run %s", planning_id, exc_info=True)
            logger.warning("Manual seed geometry update rejected: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 422

    @app.route("/api/manual_planning/restore_needle", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_manual_planning_restore_needle():
        """Restore one needle and its seeds from the latest algorithm plan."""
        data = request.get_json() or {}
        session_id = request_ui_session_id(data)
        agent = get_agent(session_id)
        if agent is None:
            return jsonify({"success": False, "error": "Agent not available"}), 500

        needle_id = str(data.get("needle_id") or data.get("needleId") or "").strip()
        if not needle_id:
            return jsonify({"success": False, "error": "needle_id is required"}), 400

        baseline = agent.memory.retrieve("algorithm_plan_snapshot") or {}
        baseline_seeds = list(baseline.get("seeds") or []) if isinstance(baseline, dict) else []
        baseline_needles = list(baseline.get("needles") or []) if isinstance(baseline, dict) else []
        if not baseline_needles:
            return jsonify({
                "success": False,
                "error": "No algorithm baseline is available. Run automatic planning first.",
                "code": "algorithm_baseline_missing",
            }), 409

        current = _current_planning_snapshot(agent)
        current_needles = list(current.get("needles") or [])
        current_seeds = list(current.get("seeds") or [])
        target = next((n for n in current_needles if str(n.get("id")) == needle_id), None)
        if target is None:
            target = next((n for n in baseline_needles if str(n.get("id")) == needle_id), None)
        if target is None:
            return jsonify({"success": False, "error": f"Unknown needle: {needle_id}"}), 404

        target_trajectory = str(target.get("trajectory_id") or "")
        baseline_needle = next((n for n in baseline_needles if str(n.get("id")) == needle_id), None)
        if baseline_needle is None and target_trajectory:
            baseline_needle = next(
                (n for n in baseline_needles if str(n.get("trajectory_id")) == target_trajectory),
                None,
            )
        if baseline_needle is None:
            return jsonify({"success": False, "error": f"No baseline geometry for {needle_id}"}), 409

        baseline_trajectory = str(baseline_needle.get("trajectory_id") or target_trajectory)
        restored_seeds = [
            dict(seed) for seed in baseline_seeds
            if str(seed.get("trajectory_id") or "") == baseline_trajectory
        ]
        if not restored_seeds:
            return jsonify({"success": False, "error": f"No baseline seeds for {needle_id}"}), 409

        kept_seeds = [
            seed for seed in current_seeds
            if str(seed.get("trajectory_id") or "") != target_trajectory
        ]
        kept_needles = [
            needle for needle in current_needles
            if str(needle.get("id")) != needle_id
        ]
        new_seeds = kept_seeds + restored_seeds
        new_needles = kept_needles + [dict(baseline_needle)]

        def _component_signature(items):
            return sorted(
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for item in (items or [])
                if isinstance(item, dict)
            )

        # Reusing the baseline dose is safe only for the common accidental
        # single-needle edit case. If another needle/seed was also changed,
        # the baseline dose no longer describes the current geometry and the
        # normal AI recomputation below remains the correct fallback.
        baseline_other_needles = [
            n for n in baseline_needles if str(n.get("id")) != needle_id
        ]
        current_other_needles = [
            n for n in current_needles if str(n.get("id")) != needle_id
        ]
        baseline_other_seeds = [
            s for s in baseline_seeds if str(s.get("trajectory_id") or "") != baseline_trajectory
        ]
        current_other_seeds = [
            s for s in current_seeds if str(s.get("trajectory_id") or "") != target_trajectory
        ]
        unchanged_other_geometry = (
            _component_signature(baseline_other_needles) == _component_signature(current_other_needles)
            and _component_signature(baseline_other_seeds) == _component_signature(current_other_seeds)
        )
        baseline_dose = agent.memory.retrieve("algorithm_plan_dose_distribution")
        baseline_dose_gy = agent.memory.retrieve("algorithm_plan_dose_distribution_gy")
        baseline_metrics = agent.memory.retrieve("algorithm_plan_dose_metrics")
        fast_restore = (
            unchanged_other_geometry
            and isinstance(baseline_metrics, dict)
            and baseline_dose is not None
            and baseline_dose_gy is not None
        )
        previous_planning_id = active_planning_id(agent.memory)
        planning_id = None
        created_new_planning = False
        try:
            planning_id = fork_planning_run(agent, reason="restore_algorithm_needle")
            created_new_planning = str(planning_id) != str(previous_planning_id or "")
            invalidate_planning_dependents(agent.memory, reason="restore_algorithm_needle")
            checkpoint_operation(
                agent,
                "running",
                f"Restoring {needle_id} to the algorithm baseline",
                checkpoint={"kind": "manual_planning", "reason": "restore_algorithm_needle", "needle_id": needle_id},
            )
            if fast_restore:
                # The algorithm plan already passed dose calculation and
                # safety validation. Restore its immutable arrays/metrics;
                # never run the expensive dose network for this operation.
                dose_grid = np.array(baseline_dose, copy=True)
                dose_grid_gy = np.array(baseline_dose_gy, copy=True)
                restored_metrics = copy.deepcopy(baseline_metrics)
                agent.memory.store("manual_seeds", new_seeds)
                agent.memory.store("manual_needles", new_needles)
                agent.memory.store("manual_geometry_only", False)
                agent.memory.store("manual_planning_preview", False)
                agent.memory.store("manual_ai_dose", False)
                agent.memory.store("dose_distribution", dose_grid)
                agent.memory.store("dose_distribution_gy", dose_grid_gy)
                agent.memory.store("dose_metrics", restored_metrics)
                agent.memory.store("metrics", restored_metrics)
                agent.memory.store("dvh_data", copy.deepcopy(restored_metrics.get("dvh_data") or {}))
                result = {
                    "success": True,
                    "fast_restore": True,
                    "dose_recomputed": False,
                    "dose_restored": True,
                    "manual_preview": False,
                    "total_seeds": len(new_seeds),
                    "num_trajectories": len(new_needles),
                    "metrics": restored_metrics,
                    "dose_range": [float(dose_grid_gy.min()), float(dose_grid_gy.max())],
                }
            else:
                result = _compute_manual_ai_dose(
                    agent,
                    new_seeds,
                    new_needles,
                    previous_needles=current_needles,
                    reproject_seeds=False,
                )
            try:
                from web.surgical_guide import invalidate_surgical_guides
                invalidate_surgical_guides(agent, f"manual needle restored: {needle_id}")
            except ImportError:
                pass
            checkpoint_operation(
                agent,
                "ready",
                f"Restored {needle_id} to the algorithm baseline",
                checkpoint={"kind": "manual_planning", "reason": "restore_algorithm_needle", "needle_id": needle_id},
            )
            result["restored_needle_id"] = needle_id
            result["needles"] = new_needles
            result["seeds"] = new_seeds
            result["planning_id"] = planning_id
            publish_planning_run(agent, result, status="completed")
            result["event"] = _append_ui_event(session_id, {
                "type": "manual.needle.restore",
                "label": f"Restored {needle_id} to algorithm baseline",
                "detail": {"needle_id": needle_id},
            })
            return jsonify(result)
        except Exception as exc:
            if created_new_planning and planning_id:
                try:
                    mark_planning_run(agent, planning_id, "failed", error=str(exc))
                except Exception:
                    logger.warning("Unable to roll back failed needle restore run %s", planning_id, exc_info=True)
            checkpoint_operation(
                agent,
                "interrupted",
                f"Needle baseline restore failed for {needle_id}",
                checkpoint={"kind": "manual_planning", "reason": "restore_algorithm_needle", "needle_id": needle_id, "error": str(exc)},
            )
            logger.exception("Needle baseline restore failed")
            error_code = getattr(exc, "code", None)
            response = {"success": False, "error": str(exc)}
            if error_code:
                response["code"] = error_code
                response["rejected_needle_ids"] = getattr(exc, "rejected_needle_ids", [])
            return jsonify(response), 422 if error_code == "manual_needle_intersects_obstacle" else 500

    @app.route("/api/status", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_status():
        """Get system status."""
        # Session restoration only needs durable paths, artifact keys, and
        # recovery metadata. Hydrating the full Agent here reads CT/plan data
        # and can take minutes, so keep this explicit lightweight branch free
        # of get_agent(); the normal status contract remains unchanged.
        if request.args.get("lightweight", "").lower() in TRUE_VALUES:
            try:
                store, user, session_id = request_case_context()
                snapshot = store.load_snapshot(user["id"], session_id)
                agent_state = snapshot.get("agent") or {}
                results = agent_state.get("planning_results") or {}
                ui_state = agent_state.get("ui_state") or {}
                controls = ((snapshot.get("ui") or {}).get("state") or {}).get("controls") or {}

                def first_path(*keys):
                    for source in (results, ui_state, controls):
                        for key in keys:
                            value = source.get(key) if isinstance(source, dict) else None
                            if isinstance(value, str) and value.strip():
                                return value.strip()
                            if isinstance(value, dict) and isinstance(value.get("value"), str) and value["value"].strip():
                                return value["value"].strip()
                    return None

                operation = snapshot.get("operation") or {}
                return jsonify({
                    "session_id": session_id,
                    "ct_path": first_path("ct_path", "ctPath", "ct_image_path", "ctImagePath"),
                    "ctv_path": first_path("ctv_path", "ctvPath", "ctv_mask_path", "ctvMaskPath"),
                    "oar_path": first_path("oar_path", "oarPath", "oar_mask_path", "oarMaskPath"),
                    "stored_keys": sorted(str(key) for key in results.keys()),
                    "brain_available": None,
                    "runtime": agent_state.get("runtime_state") or {},
                    "workspace": {
                        "revision": snapshot.get("session", {}).get("revision"),
                        "recovery_status": snapshot.get("session", {}).get("recovery_status") or operation.get("state", "ready"),
                        "checkpoint_state": operation.get("state", "idle"),
                    },
                    "lightweight": True,
                })
            except WorkspaceError as exc:
                return jsonify({"error": str(exc)}), 404
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        status = agent.get_status()
        # The browser must restore case-owned input paths from the hydrated
        # agent, rather than from a stale UI snapshot. Keeping these explicit
        # makes Input, Data Tree, viewers, and downstream planning agree after
        # a browser refresh or session transition.
        status["ct_path"] = agent.memory.retrieve("ct_path")
        status["ctv_path"] = agent.memory.retrieve("ctv_path")
        status["oar_path"] = agent.memory.retrieve("oar_path")
        status["brain_available"] = agent.brain_available
        if hasattr(agent, "run_ledger"):
            # Expose only compact, JSON-safe lifecycle evidence. The frontend
            # can recover an interrupted turn without accessing model memory,
            # raw images, or provider-private request payloads.
            status["runtime"] = agent.run_ledger.export_state()
        status["execution_tools"] = {
            "code_executor_enabled": os.environ.get("BRACHYBOT_ENABLE_CODE_EXECUTOR", "").lower() in TRUE_VALUES,
            "shell_executor_enabled": os.environ.get("BRACHYBOT_ENABLE_SHELL_EXECUTOR", "").lower() in TRUE_VALUES,
            "shell_mode": "argv_allowlist_no_shell",
        }
        # Surface GPU/CPU device allocation. See plans/device_manager.py
        # for the auto-pick heuristic (best free memory, with concurrent
        # lease penalty so we spread load across GPUs).
        try:
            from plans.device_manager import DeviceManager
            status["devices"] = DeviceManager.instance().status()
        except Exception as _e:
            status["devices"] = {"cuda_available": False, "error": str(_e)}
        try:
            store, user, session_id = request_case_context()
        except WorkspaceError:
            store = user = session_id = None
        if user and store and session_id:
            try:
                entry = store.get_session(user["id"], session_id)
                status["workspace"] = {
                    "revision": entry.revision,
                    "recovery_status": entry.recovery_status,
                    "checkpoint_state": (store.load_snapshot(user["id"], entry.id).get("operation") or {}).get("state", "idle"),
                }
            except WorkspaceError:
                status["workspace"] = {"recovery_status": "unavailable"}
        return jsonify(status)

    @app.route("/api/plan/preoperative", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_preoperative_plan():
        """Run pre-operative planning."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        ct_path = data.get("ct_path")
        ctv_path = data.get("ctv_path")
        oar_path = data.get("oar_path")
        mode = data.get("mode", "rule_based")

        if not ct_path:
            return jsonify({"error": "ct_path is required"}), 400

        if not _validate_path(ct_path) or not owned_case_path(ct_path):
            return jsonify({"error": "Invalid ct_path"}), 400
        if ctv_path and (not _validate_path(ctv_path) or not owned_case_path(ctv_path)):
            return jsonify({"error": "Invalid ctv_path"}), 400
        if oar_path and (not _validate_path(oar_path) or not owned_case_path(oar_path)):
            return jsonify({"error": "Invalid oar_path"}), 400
        try:
            safe_output_dir = workspace_output_dir("preoperative")
        except WorkspaceQuotaExceeded as exc:
            return jsonify({"error": str(exc)}), 413
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 403
        if mode not in ("rule_based", "rl", "auto"):
            return jsonify({"error": "Invalid mode. Use 'rule_based', 'rl', or 'auto'"}), 400

        checkpoint_operation(
            agent,
            "running",
            "Pre-operative planning is running",
            checkpoint={"kind": "preoperative_plan", "mode": mode},
        )
        try:
            # Get hyperparameters from agent config
            config = getattr(agent, 'config', {})
            # UI input takes priority over agent.config for ALL params.
            ui_state = agent.memory.get_ui_state() if hasattr(agent, 'memory') and hasattr(agent.memory, 'get_ui_state') else {}
            planning_state = ui_state.get("planning") if isinstance(ui_state.get("planning"), dict) else {}
            reference_direc = resolve_reference_direction_input(
                planning_state,
                config,
                default="auto",
            )
            plan_mode = ui_state.get("plan_mode") or mode or "rule_based"
            seed_info = planning_state.get("seed_info") or config.get('seed_info')
            radiation_array_params = planning_state.get("radiation_params") or config.get('radiation_array_params')
            in_lowest_energy = planning_state.get("in_lowest_energy") if planning_state.get("in_lowest_energy") is not None else config.get('in_lowest_energy')
            out_highest_energy = planning_state.get("out_highest_energy") if planning_state.get("out_highest_energy") is not None else config.get('out_highest_energy')
            dose_value_unit = planning_state.get("dose_value_unit") or config.get("dose_value_unit")
            DVH_rate = planning_state.get("dvh_rate") if planning_state.get("dvh_rate") is not None else config.get('DVH_rate')
            max_iter = planning_state.get("max_iter") if planning_state.get("max_iter") is not None else config.get('max_iter')
            rf_params = config.get('rf_params')

            result = agent.run_preoperative_plan(
                ct_path=ct_path,
                ctv_path=ctv_path,
                oar_path=oar_path,
                mode=plan_mode,
                seed_info=seed_info,
                radiation_array_params=radiation_array_params,
                reference_direc=reference_direc,
                in_lowest_energy=in_lowest_energy,
                out_highest_energy=out_highest_energy,
                dose_value_unit=dose_value_unit,
                DVH_rate=DVH_rate,
                max_iter=max_iter,
                rf_params=rf_params,
                output_dir=safe_output_dir,
            )
            validate_workspace_output("preoperative")
            checkpoint_operation(
                agent,
                "ready",
                "Pre-operative planning completed",
                checkpoint={"kind": "preoperative_plan", "mode": plan_mode, "completed": True},
            )
            return jsonify(result)
        except WorkspaceQuotaExceeded as exc:
            checkpoint_operation(
                agent,
                "interrupted",
                "Pre-operative planning exceeded the account storage quota",
                checkpoint={"kind": "preoperative_plan", "error": str(exc)},
            )
            return jsonify({"error": str(exc)}), 413
        except Exception as e:
            logger.error(f"Preoperative planning failed: {e}")
            checkpoint_operation(
                agent,
                "interrupted",
                "Pre-operative planning failed",
                checkpoint={"kind": "preoperative_plan", "mode": mode, "error": str(e)},
            )
            return jsonify({"error": str(e)}), 500

    @app.route("/api/plan/intraoperative", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_intraoperative_plan():
        """Run intra-operative replanning."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        ct_path = data.get("ct_path")
        original_plan = data.get("original_plan")
        threshold = data.get("deviation_threshold_mm", data.get("threshold", 2.0))

        if not ct_path:
            return jsonify({"error": "ct_path is required"}), 400
        if not original_plan:
            return jsonify({"error": "original_plan with planned physical seed positions is required"}), 400

        if not _validate_path(ct_path) or not owned_case_path(ct_path):
            return jsonify({"error": "Invalid ct_path"}), 400
        try:
            safe_output_dir = workspace_output_dir("intraoperative")
        except WorkspaceQuotaExceeded as exc:
            return jsonify({"error": str(exc)}), 413
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 403
        try:
            threshold = float(threshold)
            if threshold <= 0:
                return jsonify({"error": "threshold must be positive"}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid threshold value"}), 400

        checkpoint_operation(
            agent,
            "running",
            "Intra-operative replanning is running",
            checkpoint={"kind": "intraoperative_replan", "deviation_threshold_mm": threshold},
        )
        try:
            result = agent.run_intraoperative_replan(
                intra_op_ct_path=ct_path,
                original_plan=original_plan,
                deviation_threshold_mm=threshold,
                output_dir=safe_output_dir,
            )
            validate_workspace_output("intraoperative")
            checkpoint_operation(
                agent,
                "ready",
                "Intra-operative replanning completed",
                checkpoint={"kind": "intraoperative_replan", "completed": True},
            )
            return jsonify(result)
        except WorkspaceQuotaExceeded as exc:
            checkpoint_operation(
                agent,
                "interrupted",
                "Intra-operative replanning exceeded the account storage quota",
                checkpoint={"kind": "intraoperative_replan", "error": str(exc)},
            )
            return jsonify({"error": str(exc)}), 413
        except Exception as e:
            logger.error(f"Intraoperative replanning failed: {e}")
            checkpoint_operation(
                agent,
                "interrupted",
                "Intra-operative replanning failed",
                checkpoint={"kind": "intraoperative_replan", "error": str(e)},
            )
            return jsonify({"error": str(e)}), 500

    @app.route("/api/chat/abort", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_chat_abort():
        """Clean up incomplete conversation after user aborts streaming."""
        try:
            _, user, session_id = request_case_context()
            task = chat_tasks.active(user["id"], session_id)
            if task is not None:
                # The abort endpoint performs its own small, explicit
                # interruption checkpoint below. Do not let the cancelled
                # worker later run the normal completion hook against the
                # same agent after a new chat turn has already started.
                task._skip_finalization = True
                chat_tasks.cancel(task)
            agent = (get_cached_agent(session_id) if callable(get_cached_agent) else None)
            if agent is None and task is not None:
                agent = task.agent
            if agent is None:
                # Stop must be responsive even while the case is hydrating.
                try:
                    store, _, _ = request_case_context()
                    if task is not None:
                        store.save_snapshot_patch(
                            user["id"], session_id,
                            {"operation": {
                                "state": "interrupted",
                                "message": "Chat was cancelled by the user.",
                                "updated_at": time.time(),
                                "checkpoint": {"kind": "chat", "cancelled": True},
                            }},
                            reason="chat.task.cancelled_during_hydration",
                        )
                except WorkspaceError:
                    pass
                return jsonify({"success": True, "cancel_requested": bool(task)})
            agent._cancel_active_turn()
            # Remove the last incomplete conversation turn
            # AgentMemory owns the lock that protects conversation state.
            # A newly-created fallback lock would not synchronize anything.
            with agent.memory._lock:
                conv = agent.memory.conversation
                if len(conv) >= 2:
                    # Remove last assistant message if incomplete
                    if conv[-1].get("role") == "assistant":
                        conv.pop()
                    # Remove last user message (the one that triggered the aborted response)
                    if conv and conv[-1].get("role") == "user":
                        conv.pop()
            checkpoint_operation(
                agent,
                "interrupted",
                "Chat was cancelled by the user",
                checkpoint={"kind": "chat", "cancelled": True},
            )
            return jsonify({"success": True, "cancel_requested": True})
        except Exception as e:
            logger.error(f"Chat abort cleanup failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/clear_all", methods=["POST"])
    @require_api_key
    def api_clear_all():
        """Clear all loaded data (CT, CTV, OAR, planning results) for a fresh start."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        try:
            agent.memory.clear_all_data()
            agent.memory.clear_conversation()
            checkpoint_operation(
                agent,
                "ready",
                "Case data was cleared by the user",
                checkpoint={"kind": "clear", "completed": True},
            )
            return jsonify({"success": True, "message": "All data cleared"})
        except Exception as e:
            logger.error(f"Clear all data failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/export/dicom_rt", methods=["POST"])
    @app.route("/api/export/dicom", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_export_dicom_rt():
        """Export linked RTSTRUCT, RTPLAN, and RTDOSE objects.

        ``/api/export/dicom`` is retained as a backward-compatible alias. Both
        routes intentionally use this single implementation so their geometry,
        safety policy, and response schema cannot drift apart.
        """
        data = request.get_json() or {}
        # Case selection is a server-side, signed-cookie concern. Keep accepting
        # the old payload shape, but never let a client-selected ID choose data.
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        try:
            safe_output_dir = workspace_output_dir("dicom_rt")
        except WorkspaceQuotaExceeded as exc:
            return jsonify({"error": str(exc)}), 413
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 403

        try:
            os.makedirs(safe_output_dir, exist_ok=True)
            seed_plan = (
                agent.memory.retrieve("seed_plan")
                or agent.memory.retrieve("seed_plan_serialized")
                or agent.memory.retrieve("manual_seeds")
            )
            dose_distribution = agent.memory.retrieve("dose_distribution")
            reference_image = agent.memory.retrieve("resampled_ct")
            if reference_image is None:
                reference_image = agent.memory.retrieve("ct_image")
            if reference_image is None:
                return jsonify({"error": "No planning image is available. Load CT data first."}), 400
            if not seed_plan:
                return jsonify({"error": "No plan available. Run planning first."}), 400

            reference_shape = tuple(reversed(reference_image.GetSize()))
            resampled_ctv = agent.memory.retrieve("resampled_ctv")
            resampled_oar = agent.memory.retrieve("resampled_oar")
            if resampled_ctv is None:
                candidate = agent._get_label_array("ctv_array")
                if candidate is not None and tuple(np.asarray(candidate).shape) == reference_shape:
                    resampled_ctv = candidate
            if resampled_oar is None:
                candidate = agent._get_label_array("oar_array")
                if candidate is not None and tuple(np.asarray(candidate).shape) == reference_shape:
                    resampled_oar = candidate

            structures = {}
            if resampled_ctv is not None:
                ctv_array = np.asarray(resampled_ctv)
                if tuple(ctv_array.shape) == reference_shape and np.any(ctv_array > 0):
                    structures["CTV"] = ctv_array > 0

            organ_names = _oar_display_name_map(agent, resampled_oar)
            used_names = set(structures)
            if resampled_oar is not None:
                oar_array = np.asarray(resampled_oar)
                if tuple(oar_array.shape) != reference_shape:
                    return jsonify({
                        "error": (
                            f"OAR grid {tuple(oar_array.shape)} does not match the DICOM export "
                            f"grid {reference_shape}. Re-run dose calculation on the current case."
                        )
                    }), 400
                for label in np.unique(oar_array):
                    label_id = int(label)
                    if label_id <= 0:
                        continue
                    name = organ_names.get(label_id) or organ_names.get(str(label_id))
                    base_name = str(name or f"OAR {label_id}")
                    unique_name = base_name if base_name not in used_names else f"{base_name}_{label_id}"
                    used_names.add(unique_name)
                    structures[unique_name] = oar_array == label

            dose_metrics = agent.memory.retrieve("dose_metrics") or {}
            dose_scale_gy = float(
                agent.memory.retrieve("dose_scale_gy") or DOSE_MODEL_SCALE_GY
            )
            plan_config = agent.memory.retrieve("plan_config") or {}
            prescription_gy = resolve_prescription_gy(
                plan_config,
                dose_metrics,
                dose_scale_gy=dose_scale_gy,
            )
            seed_info = plan_config.get("seed_info") or getattr(agent, "config", {}).get("seed_info", {})
            from tool_factory.output.dicom_rt_exporter import DicomRTExporterTool

            tool = DicomRTExporterTool()
            result = tool.execute(
                ct_image=reference_image,
                structures=structures,
                seed_plan=seed_plan,
                dose_array=dose_distribution,
                output_dir=safe_output_dir,
                dicom_tags=agent.memory.retrieve("ct_dicom_tags") or {},
                dose_scale_gy=dose_scale_gy,
                dose_units=agent.memory.retrieve("dose_units") or DOSE_MODEL_UNITS,
                prescription_gy=prescription_gy,
                isotope=data.get("isotope") or "I-125",
                seed_length_mm=float(seed_info.get("length", 4.5) or 4.5),
            )

            if result.success:
                validate_workspace_output("dicom_rt")
                return jsonify({
                    "success": True,
                    "files": result.data,
                    "output_dir": safe_output_dir,
                    "message": result.message,
                    "clinical_status": result.metadata.get("clinical_status"),
                    "manifest": result.metadata.get("manifest"),
                })
            return jsonify({"success": False, "error": result.error}), 400
        except WorkspaceQuotaExceeded as exc:
            return jsonify({"error": str(exc)}), 413
        except Exception as e:
            logger.error(f"DICOM-RT export failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/export/stl", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_export_stl():
        """Export seed positions as STL files."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        try:
            safe_output_dir = workspace_output_dir("stl")
        except WorkspaceQuotaExceeded as exc:
            return jsonify({"error": str(exc)}), 413
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 403

        try:
            import os
            import numpy as np
            os.makedirs(safe_output_dir, exist_ok=True)

            seed_plan = agent.memory.retrieve("seed_plan")
            if seed_plan is None:
                return jsonify({"error": "No plan available. Run planning first."}), 400

            seed_info = getattr(agent, 'config', {}).get("seed_info", {"length": 4.5, "radius": 0.4})
            seed_length = float(seed_info.get("length", 4.5) or 4.5)
            seed_radius = float(seed_info.get("radius", 0.4) or 0.4)

            def _seed_cylinder_stl(pos, direction, facets=16):
                """Return ASCII STL for one seed cylinder in world coordinates."""
                pos = np.asarray(pos, dtype=float).reshape(3)
                direction = np.asarray(direction, dtype=float).reshape(3)
                norm = float(np.linalg.norm(direction))
                if norm < 1e-8:
                    direction = np.array([0.0, 0.0, 1.0])
                else:
                    direction = direction / norm
                helper = np.array([1.0, 0.0, 0.0])
                if abs(float(np.dot(helper, direction))) > 0.9:
                    helper = np.array([0.0, 1.0, 0.0])
                u = np.cross(direction, helper)
                u = u / max(float(np.linalg.norm(u)), 1e-8)
                v = np.cross(direction, u)
                half = direction * (seed_length / 2.0)
                p0 = pos - half
                p1 = pos + half

                ring0 = []
                ring1 = []
                for k in range(facets):
                    angle = 2.0 * np.pi * k / facets
                    offset = seed_radius * (np.cos(angle) * u + np.sin(angle) * v)
                    ring0.append(p0 + offset)
                    ring1.append(p1 + offset)

                triangles = []
                for k in range(facets):
                    nk = (k + 1) % facets
                    triangles.append((ring0[k], ring1[k], ring1[nk]))
                    triangles.append((ring0[k], ring1[nk], ring0[nk]))
                    triangles.append((p0, ring0[nk], ring0[k]))
                    triangles.append((p1, ring1[k], ring1[nk]))

                lines = ["solid seed"]
                for a, b, c in triangles:
                    normal = np.cross(b - a, c - a)
                    normal = normal / max(float(np.linalg.norm(normal)), 1e-8)
                    lines.append(f"  facet normal {normal[0]:.8g} {normal[1]:.8g} {normal[2]:.8g}")
                    lines.append("    outer loop")
                    for p in (a, b, c):
                        lines.append(f"      vertex {p[0]:.8g} {p[1]:.8g} {p[2]:.8g}")
                    lines.append("    endloop")
                    lines.append("  endfacet")
                lines.append("endsolid seed")
                return "\n".join(lines) + "\n"

            # Export seeds as individual ASCII STL files. The endpoint name and
            # file extensions intentionally match the payload; raw NPY exports
            # belong in a separate debug/export route if ever needed.
            count = 0
            files = []
            for i, entry in enumerate(seed_plan):
                if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                    continue
                seeds = entry[1]
                for j, seed in enumerate(seeds):
                    if not isinstance(seed, (list, tuple)) or len(seed) < 2:
                        continue
                    pos = np.array(seed[0])
                    direc = np.array(seed[1])
                    filename = f"seed_{i}_{j}.stl"
                    payload = _seed_cylinder_stl(pos, direc).encode("utf-8")
                    store, user, session_id = request_case_context()
                    # Use the streaming writer so every generated STL obeys
                    # the same replacement-aware quota policy as uploads.
                    import io
                    store.write_artifact(
                        user["id"], session_id, "stl", filename,
                        io.BytesIO(payload), expected_bytes=len(payload),
                    )
                    files.append(filename)
                    count += 1

            return jsonify({
                "success": True,
                "count": count,
                "files": files,
                "download_urls": [artifact_download_url(f"stl/{name}") for name in files],
                "output_dir": safe_output_dir,
            })
        except WorkspaceQuotaExceeded as exc:
            return jsonify({"error": str(exc)}), 413
        except Exception as e:
            logger.error(f"STL export failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/chat", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_chat():
        """Natural language chat interface with execution trace."""
        data = request.get_json() or {}
        message = data.get("message", "")
        ui_state = data.get("ui_state", {})
        stream = data.get("stream", True)  # Default to streaming
        image_path = data.get("image_path", None)  # Optional image path
        clear_context = data.get("clear_context", False)  # Optional: clear conversation history
        request_id = re.sub(
            r"[^A-Za-z0-9_.:-]",
            "",
            str(data.get("request_id") or ""),
        )[:128] or uuid4().hex
        user_message_id = re.sub(
            r"[^A-Za-z0-9_.:-]",
            "",
            str(data.get("user_message_id") or ""),
        )[:160] or f"user-{request_id}"
        assistant_message_id = re.sub(
            r"[^A-Za-z0-9_.:-]",
            "",
            str(data.get("assistant_message_id") or ""),
        )[:160] or f"assistant-{request_id}"
        internal_followup = bool(data.get("internal_followup", False))
        response_language = str(data.get("response_language") or "")[:8]
        if not message and not image_path:
            return jsonify({"error": "message or image is required"}), 400

        # ``session_id`` remains tolerated in older browser payloads, but the
        # authenticated user's selected workspace is always authoritative.
        # Streaming requests must not wait for a cold Agent: the browser has a
        # short connection timeout, while workspace hydration may read large
        # CT/NPY sidecars. Resolve the case first and use a lazy worker agent.
        agent = None
        owner = None
        session_id = None
        if stream:
            try:
                store, owner, session_id = request_case_context()
            except WorkspaceError:
                return jsonify({"error": "Authentication required"}), 401
            if callable(get_cached_agent):
                agent = get_cached_agent(session_id)
                # A lightweight cache hit is only a control-plane shell.  It
                # must not enter the worker before the case-owned hydration
                # thread restores arrays, planning results, and CT metadata.
                # Otherwise a fast chat turn can observe an empty workspace
                # and overwrite the durable response with an incomplete one.
                if agent is not None and not getattr(agent, "_workspace_data_ready", True):
                    agent = None
        else:
            agent = get_agent()
            if agent is None:
                return jsonify({"error": "Agent not available"}), 500

        # Clear-context with no new turn is an explicit synchronous operation;
        # a queued turn below applies the clear inside its worker before chat.
        if clear_context and not message and not image_path:
            if agent is None:
                agent = get_agent()
            if agent is None:
                return jsonify({"error": "Agent not available"}), 500
            agent.memory.clear_conversation()
            logger.info("Conversation context cleared")
            return jsonify({"success": True, "message": "Conversation context cleared"})
        if clear_context and agent is not None:
            agent.memory.clear_conversation()
            logger.info("Conversation context cleared")

        if image_path and (not _validate_path(image_path, purpose="read") or not owned_case_path(image_path)):
            return jsonify({"error": "image_path must belong to the active case workspace"}), 403

        # If image provided but no message, use default prompt
        if image_path and not message:
            message = "Please analyze this image"

        # Include image path in message if provided
        full_message = message
        if image_path:
            full_message = f"{message}\n\n[Uploaded image path: {image_path}]"

        if stream:
            def agent_supplier():
                resolved = (
                    get_agent_for_owner(owner, session_id, _lightweight=True)
                    if callable(get_agent_for_owner)
                    else get_agent(session_id, _lightweight=True)
                )
                # A chat task already exposes a visible hydration step. Wait
                # on the case-owned readiness event here rather than blocking
                # the HTTP/SSE handshake in get_agent while large arrays load.
                ready_event = getattr(resolved, "_workspace_ready_event", None) if resolved is not None else None
                if resolved is not None and not getattr(resolved, "_workspace_data_ready", True):
                    # Low-risk knowledge/status turns can use the JSON
                    # metadata shell immediately.  Only clinical actions wait
                    # for arrays, and the wait is bounded so a damaged CT or
                    # stalled decoder cannot leave a chat spinner forever.
                    if not _chat_requires_full_workspace(message, image_path):
                        logger.info(
                            "Using metadata-only case shell for lightweight chat session=%s",
                            session_id,
                        )
                    else:
                        if ready_event is not None:
                            ready_event.wait(timeout=120)
                        if not getattr(resolved, "_workspace_data_ready", False):
                            logger.warning(
                                "Full case hydration did not finish within 120s session=%s",
                                session_id,
                            )
                            return None
                if resolved is not None and clear_context:
                    resolved.memory.clear_conversation()
                return resolved

            start_gate = threading.Event()
            try:
                task = chat_tasks.start(
                    current_app._get_current_object(),
                    owner["id"],
                    session_id,
                    agent,
                    full_message,
                    ui_state,
                    on_finish=finalize_chat_task,
                    start_gate=start_gate,
                    agent_supplier=agent_supplier if agent is None else None,
                    request_id=request_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    internal_followup=internal_followup,
                    response_language=response_language,
                )
            except RuntimeError as exc:
                return jsonify({
                    "error": str(exc),
                    "code": "chat_task_running",
                }), 409

            try:
                checkpoint = {
                    "kind": "chat",
                    "task_id": task.task_id,
                    "request_id": task.request_id,
                    "user_message": message[:500],
                }
                if agent is not None:
                    checkpoint_operation(agent, "running", "Chat response is in progress", checkpoint=checkpoint)
                else:
                    store.save_snapshot_patch(
                        owner["id"], session_id,
                        {"operation": {
                            "state": "running",
                            "message": "Case resources are loading; chat is queued.",
                            "updated_at": time.time(),
                            "started_at": time.time(),
                            "checkpoint": checkpoint,
                        }},
                        reason="chat.task.queued_during_hydration",
                    )
                # Persist the task identity separately from the agent
                # checkpoint.  This small merge makes the running task
                # discoverable after a case switch or browser refresh even
                # when the full agent snapshot is still being written.
                try:
                    # A detached task can outlive its browser stream. Persist
                    # the user turn before releasing the worker gate so a
                    # refresh restores the request, Thinking state, and task
                    # identity together rather than showing an orphaned
                    # progress animation with no initiating command.
                    snapshot = store.load_snapshot(owner["id"], session_id)
                    chat = snapshot.get("chat") if isinstance(snapshot.get("chat"), dict) else {}
                    messages = list(chat.get("messages") or [])
                    display_message = full_message.split("\n\n[Uploaded image path:", 1)[0]
                    previous = messages[-1] if messages else None
                    if not internal_followup and not (
                        previous
                        and previous.get("type") == "user"
                        and (
                            str(previous.get("id") or "") == task.user_message_id
                            or str(previous.get("content") or "") == display_message
                        )
                    ):
                        messages.append({
                            "type": "user",
                            "content": display_message,
                            "timestamp": int(time.time() * 1000),
                            "id": task.user_message_id,
                            "request_id": task.request_id,
                            "message_kind": "user_message",
                            "turn_sequence": 0,
                            "response_language": str(getattr(task, "response_language", "") or "")[:8],
                            "trace_language": str(getattr(task, "response_language", "") or "")[:8],
                        })
                    store.save_snapshot_patch(
                        owner["id"],
                        session_id,
                        {
                            "chat": {
                                "messages": messages,
                                "task_id": task.task_id,
                                "task_status": "running",
                            }
                        },
                        expected_revision=None,
                        reason="chat.task.started",
                    )
                except WorkspaceNotFound:
                    # Frontend may retry a persistence for a recently deleted case.
                    # Silently drop the write — the session no longer exists.
                    pass
                except WorkspaceError:
                    logger.warning("Unable to persist chat task identity %s", task.task_id, exc_info=True)
                finally:
                    # Release the worker only after the running checkpoint has
                    # been written, preventing a fast Q&A turn from overwriting
                    # its final ready checkpoint with a late running state.
                    start_gate.set()

            except Exception:
                # checkpoint_operation may fail if the workspace was deleted
                # between task creation and persistence. Release the gate
                # anyway so the SSE stream can still start.
                start_gate.set()

            def generate_task(task_to_stream: ChatTask, after_seq: int = 0):
                # The task metadata is deliberately sent before the Agent's
                # own start event so the browser can detach/reconnect without
                # ever guessing which case owns the stream.
                yield (
                    "event: task_meta\ndata: "
                    + json.dumps(task_to_stream.public_state())
                    + "\n\n"
                ).encode("utf-8")
                try:
                    for event in task_to_stream.iter_events(after_seq):
                        yield event.encode("utf-8")
                except GeneratorExit:
                    # Disconnecting a browser is not a user cancellation. The
                    # background worker and its event journal continue, and a
                    # later case selection can subscribe again.
                    logger.info("Chat SSE detached for task %s; task continues", task_to_stream.task_id)
                    raise

            resp = Response(
                stream_with_context(generate_task(task)),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                    'Connection': 'keep-alive',
                }
            )
            resp.direct_passthrough = True
            return resp
        else:
            try:
                checkpoint_operation(
                    agent,
                    "running",
                    "Chat response is in progress",
                    checkpoint={"kind": "chat", "user_message": message[:500]},
                )
                agent.memory.set_ui_state(ui_state)
                result = agent.chat_with_trace(full_message)

                # Sanitize result to make it JSON-serializable (remove numpy arrays, etc.)
                def _sanitize_for_json(obj):
                    """Recursively sanitize objects to make them JSON-serializable."""
                    import numpy as np
                    if isinstance(obj, dict):
                        return {k: _sanitize_for_json(v) for k, v in obj.items()}
                    elif isinstance(obj, (list, tuple)):
                        return [_sanitize_for_json(item) for item in obj]
                    elif isinstance(obj, np.ndarray):
                        return f"<ndarray shape={obj.shape} dtype={obj.dtype}>"
                    elif isinstance(obj, (np.integer, np.int64)):
                        return int(obj)
                    elif isinstance(obj, (np.floating, np.float64)):
                        return float(obj)
                    elif isinstance(obj, np.bool_):
                        return bool(obj)
                    elif hasattr(obj, '__dict__'):
                        return f"<{type(obj).__name__} object>"
                    else:
                        return obj

                sanitized_result = _sanitize_for_json(result)

                checkpoint_operation(agent, "ready", "Chat response completed", checkpoint={"kind": "chat"})
                return jsonify({
                    "response": sanitized_result["response"],
                    "steps": sanitized_result["steps"],
                    "llm_meta": sanitized_result.get("llm_meta", {}),
                    "context": {
                        "summary": agent.memory.context_summary or None,
                        "compaction_count": agent.memory.compaction_count,
                        "message_count": len(agent.memory.conversation),
                        "ui_state": agent.memory.get_ui_state(),
                    },
                    "session_id": agent.memory.session_id,
                    "brain_available": agent.brain_available,
                })
            except Exception as e:
                checkpoint_operation(agent, "interrupted", "Chat response failed", checkpoint={"kind": "chat"})
                logger.error(f"Chat failed: {e}")
                return jsonify({"error": str(e)}), 500

    @app.route("/api/chat/task", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_chat_task():
        """Return the selected case's live task and durable recovery hints.

        The in-process task is authoritative while the server is running, but
        the browser may reconnect after a case switch or a dropped SSE stream.
        Returning the compact persisted task marker as well prevents a stale
        control-plane snapshot from being mistaken for a new chat request.
        """
        try:
            store, user, session_id = request_case_context()
        except WorkspaceError:
            return jsonify({"error": "Authentication required"}), 401
        task = chat_tasks.active(user["id"], session_id) or chat_tasks.latest(user["id"], session_id)
        persisted = {
            "task_id": None,
            "last_task_id": None,
            "status": "idle",
            "operation_state": "ready",
        }
        try:
            snapshot = store.load_snapshot(user["id"], session_id)
            chat = snapshot.get("chat") if isinstance(snapshot.get("chat"), dict) else {}
            operation = snapshot.get("operation") if isinstance(snapshot.get("operation"), dict) else {}
            persisted.update({
                "task_id": chat.get("task_id"),
                "last_task_id": chat.get("last_task_id"),
                "status": chat.get("task_status") or "idle",
                "operation_state": operation.get("state") or "ready",
                "updated_at": chat.get("updated_at") or snapshot.get("saved_at"),
            })
        except WorkspaceError:
            # The case was deleted between the ownership check and the read.
            # Keep the endpoint useful for the currently selected case without
            # exposing a filesystem exception to the browser.
            pass
        return jsonify({
            "task": task.public_state() if task is not None else None,
            "persisted": persisted,
        })

    @app.route("/api/chat/tasks/<task_id>/stream", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_chat_task_stream(task_id: str):
        """Replay/follow one selected-case task after a case switch."""
        try:
            _, user, session_id = request_case_context()
        except WorkspaceError:
            return jsonify({"error": "Authentication required"}), 401
        task = chat_tasks.get(task_id, user["id"], session_id)
        if task is None:
            return jsonify({"error": "Chat task not found for the selected case"}), 404
        try:
            after_seq = max(0, int(request.args.get("after_seq", "0")))
        except ValueError:
            after_seq = 0

        def generate():
            yield (
                "event: task_meta\ndata: "
                + json.dumps(task.public_state())
                + "\n\n"
            ).encode("utf-8")
            try:
                for event in task.iter_events(after_seq):
                    yield event.encode("utf-8")
            except GeneratorExit:
                logger.info("Chat task %s replay stream detached; task continues", task.task_id)
                raise

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.route("/api/tasks/stream")
    @require_api_key
    @rate_limit
    def api_tasks_stream():
        """SSE endpoint for real-time task progress updates."""
        task_id = request.args.get("task_id")

        def generate():
            deadline = time.time() + 300
            last_payload = None
            try:
                while time.time() < deadline:
                    if task_id:
                        task = task_manager.get_task(task_id, workspace_owner=task_workspace_owner())
                        payload = {"task": task}
                        if task:
                            data = json.dumps(task)
                            if data != last_payload:
                                last_payload = data
                                yield f"event: task\ndata: {data}\n\n".encode("utf-8")
                            if task.get("status") != "running":
                                break
                        else:
                            yield f"event: task\ndata: {json.dumps(payload)}\n\n".encode("utf-8")
                            break
                    else:
                        tasks = task_manager.get_all_tasks(workspace_owner=task_workspace_owner())
                        data = json.dumps(tasks)
                        if data != last_payload:
                            last_payload = data
                            yield f"event: tasks\ndata: {data}\n\n".encode("utf-8")
                        if not any(task.get("status") == "running" for task in tasks.values()):
                            break
                    yield b"event: heartbeat\ndata: {}\n\n"
                    time.sleep(5)
            except GeneratorExit:
                logger.debug("Task SSE client disconnected")
                raise

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    @app.route("/api/tasks/<task_id>", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_task_status(task_id):
        """Get task status."""
        task = task_manager.get_task(task_id, workspace_owner=task_workspace_owner())
        if task is None:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(task)

    @app.route("/api/tasks", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_tasks_list():
        """List all tasks."""
        return jsonify(task_manager.get_all_tasks(workspace_owner=task_workspace_owner()))

    @app.route("/api/export/report", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_export_report():
        """Generate planning report."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        output_format = data.get("format", "json")
        if output_format not in ("json", "html", "pdf"):
            return jsonify({"error": "Invalid format. Use 'json', 'html', or 'pdf'"}), 400
        try:
            safe_output_path = os.path.join(workspace_output_dir("reports"), f"report.{output_format}")
        except WorkspaceQuotaExceeded as exc:
            return jsonify({"error": str(exc)}), 413
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 403

        try:
            if output_format == "pdf":
                return jsonify({
                    "error": "Server-side PDF report export is not available. Use the browser Report panel PDF export.",
                }), 501

            metrics = agent.memory.retrieve("dose_metrics") or agent.memory.retrieve("metrics") or {}
            from tool_factory.report_context import (
                build_report_context,
                format_prescription_rationale_markdown,
                format_tumor_assessment_markdown,
            )

            def _report_lookup(key, default=None):
                if key == "plan_config":
                    return agent.memory.retrieve(key) or getattr(agent, "config", {}) or default
                return agent.memory.retrieve(key, default)

            report_context = build_report_context(_report_lookup)
            lang = data.get("language", agent.memory.user_lang if hasattr(agent.memory, "user_lang") else "zh")
            tumor_md = format_tumor_assessment_markdown(report_context, lang)
            dose_md = format_prescription_rationale_markdown(report_context, lang)

            payload = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "patient_id": (getattr(agent.memory, "patient_data", None) or {}).get("id", "UNKNOWN"),
                "plan_name": "BrachyPlan",
                "ct_path": agent.memory.retrieve("ct_path"),
                "tumor_type": agent.memory.retrieve("tumor_type_used", ""),
                "tumor_imaging_assessment": report_context.get("tumor_imaging", {}),
                "prescription_rationale": report_context.get("prescription_rationale", {}),
                "dose_metrics": metrics,
                "total_seeds": agent.memory.retrieve("total_seeds", 0),
                "total_trajectories": agent.memory.retrieve("num_trajectories", 0),
                "narrative_markdown": "\n\n".join([tumor_md, dose_md]),
            }

            rendered: bytes
            if output_format == "json":
                rendered = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
            elif output_format == "html":
                import html
                body = html.escape(payload["narrative_markdown"]).replace("\n", "<br>\n")
                rendered = (
                    "<!doctype html><html><head><meta charset='utf-8'>"
                    "<title>BrachyPlan Report</title></head><body>"
                    "<h1>BrachyPlan Report</h1>"
                    f"<pre>{html.escape(json.dumps(payload, indent=2, ensure_ascii=False, default=str))}</pre>"
                    f"<hr><div>{body}</div>"
                    "</body></html>"
                ).encode("utf-8")

            store, user, session_id = request_case_context()
            import io
            safe_output_path = str(store.write_artifact(
                user["id"], session_id, "reports", f"report.{output_format}",
                io.BytesIO(rendered), expected_bytes=len(rendered),
            ))

            return jsonify({
                "success": True,
                "path": safe_output_path,
                "report_path": safe_output_path,
                "download_url": artifact_download_url(f"reports/report.{output_format}"),
                "message": f"Report generated: {safe_output_path}",
            })

        except WorkspaceQuotaExceeded as exc:
            return jsonify({"error": str(exc)}), 413
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/control", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_control():
        """LLM-callable viewer control endpoint. Adjust window/level, navigate slices, toggle overlays."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        action = data.get("action", "")
        ct_data = agent.memory.retrieve("ct_data")

        if ct_data is None and action not in ("get_state",):
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            if action == "set_window":
                w = data.get("window", agent.memory.retrieve("ct_window_width") or 400)
                l = data.get("level", agent.memory.retrieve("ct_window_center") or 40)
                agent.memory.store("ct_window_width", w)
                agent.memory.store("ct_window_center", l)
                return jsonify({"success": True, "message": f"Window set to W:{w} L:{l}", "window": w, "level": l})

            elif action == "set_preset":
                presets = {
                    "soft": {"w": 400, "l": 40},
                    "bone": {"w": 2000, "l": 400},
                    "lung": {"w": 1500, "l": -600},
                    "brain": {"w": 80, "l": 40},
                }
                preset = data.get("preset", "soft")
                if preset not in presets:
                    return jsonify({"error": f"Unknown preset: {preset}. Available: {list(presets.keys())}"}), 400
                p = presets[preset]
                agent.memory.store("ct_window_width", p["w"])
                agent.memory.store("ct_window_center", p["l"])
                return jsonify({"success": True, "message": f"Preset '{preset}' applied (W:{p['w']} L:{p['l']})", "window": p["w"], "level": p["l"]})

            elif action == "navigate_slice":
                axis = data.get("axis", "axial")
                slice_index = data.get("slice_index", 0)
                shape = ct_data.shape
                axis_map = agent.memory.retrieve("ct_axis_map") or {'axial': 2, 'sagittal': 0, 'coronal': 1}
                axis_idx = axis_map.get(axis, 2)
                max_slice = shape[axis_idx] - 1
                slice_index = max(0, min(slice_index, max_slice))
                agent.memory.store(f"viewer_slice_{axis}", slice_index)
                return jsonify({"success": True, "message": f"Moved to {axis} slice {slice_index}/{max_slice}", "axis": axis, "slice_index": slice_index, "max_slice": max_slice})

            elif action == "set_threshold":
                threshold = data.get("threshold")
                if threshold is not None:
                    try:
                        threshold = float(threshold)
                    except (TypeError, ValueError):
                        return jsonify({"error": "threshold must be numeric or null"}), 400
                agent.memory.store("viewer_threshold", threshold)
                return jsonify({"success": True, "message": f"Threshold {'cleared' if threshold is None else f'set to {threshold} HU'}", "threshold": threshold})

            elif action == "toggle_overlay":
                overlay = data.get("overlay", "ctv")
                current = agent.memory.retrieve("viewer_overlay")
                new_overlay = None if current == overlay else overlay
                agent.memory.store("viewer_overlay", new_overlay)
                return jsonify({"success": True, "message": f"Overlay {overlay} {'activated' if new_overlay else 'deactivated'}", "overlay": new_overlay})

            elif action == "get_state":
                return jsonify({
                    "success": True,
                    "ct_loaded": ct_data is not None,
                    "ct_shape": list(ct_data.shape) if ct_data is not None else None,
                    "window": agent.memory.retrieve("ct_window_width") or 400,
                    "level": agent.memory.retrieve("ct_window_center") or 40,
                    "threshold": agent.memory.retrieve("viewer_threshold"),
                    "overlay": agent.memory.retrieve("viewer_overlay"),
                    "slices": {
                        "axial": agent.memory.retrieve("viewer_slice_axial") or 0,
                        "sagittal": agent.memory.retrieve("viewer_slice_sagittal") or 0,
                        "coronal": agent.memory.retrieve("viewer_slice_coronal") or 0,
                    },
                })

            else:
                return jsonify({"error": f"Unknown action: {action}. Available: set_window, set_preset, navigate_slice, set_threshold, toggle_overlay, get_state"}), 400

        except Exception as e:
            logger.error(f"Viewer control failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/screenshot", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_screenshot():
        """Save one screenshot attachment under its owning chat request."""
        data = request.get_json() or {}
        image_data = data.get("image", "")  # base64 data URL
        description = data.get("description", "screenshot")
        title = str(data.get("title") or "")[:240]
        target = data.get("target", "unknown")
        mode = str(data.get("mode") or "chat").lower()
        if mode not in {"chat", "monitor", "report"}:
            return jsonify({"error": "Invalid screenshot mode"}), 400
        request_id = re.sub(
            r"[^A-Za-z0-9_.:-]", "", str(data.get("request_id") or "")
        )[:128]
        message_id = re.sub(
            r"[^A-Za-z0-9_.:-]", "", str(data.get("message_id") or "")
        )[:160]
        attachment_id = re.sub(
            r"[^A-Za-z0-9_.:-]", "", str(data.get("attachment_id") or "")
        )[:160] or f"screenshot-{uuid4().hex}"
        planning_id = str(data.get("planning_id") or "")[:160]
        case_id = str(data.get("case_id") or "")[:160]
        data_version = str(data.get("data_version") or "")[:160]
        question = str(data.get("question") or "")[:2000]
        layout = str(data.get("layout") or "auto")[:32]
        response_language = str(
            data.get("response_language") or data.get("responseLanguage") or ""
        )[:8]
        view_metadata = data.get("view_metadata")
        if not isinstance(view_metadata, dict):
            view_metadata = {}

        if not image_data:
            return jsonify({"error": "No image data provided"}), 400

        try:
            img_bytes = _decode_png_data_url(image_data)

            # Report figures need a recoverable identity even if an older or
            # partially written workspace snapshot loses the figure array.
            # Keep the axis in the filename so the artifact-catalog fallback
            # can rebuild Figure 1/2 membership without relying on file order.
            report_axis = ""
            if mode == "report":
                report_axis = re.sub(
                    r"[^A-Za-z0-9_-]",
                    "",
                    str(view_metadata.get("axis") or view_metadata.get("capture_role") or ""),
                )[:80]
            descriptor = f"_{report_axis}" if report_axis else ""
            if mode == "report" and report_axis:
                # Report capture roles are idempotent within one Planning run.
                # Re-capturing Figure 1(a), including after a Session restore,
                # must update its durable artifact rather than create another
                # UUID-named file that later restores as a duplicate subfigure.
                report_identity = f"{planning_id or '__unassigned__'}:{report_axis}"
                report_digest = hashlib.sha256(
                    report_identity.encode("utf-8")
                ).hexdigest()[:12]
                filename = f"report_screenshot{descriptor}_{report_digest}.png"
            else:
                filename = f"{mode}_screenshot{descriptor}_{uuid4().hex[:12]}.png"
            try:
                store, user, session_id = request_case_context()
            except WorkspaceError:
                return jsonify({"error": "Authentication required"}), 401
            filepath = store.write_screenshot(user["id"], session_id, filename, img_bytes)
            url = f"/api/sessions/{session_id}/screenshots/{filename}"
            logger.info(f"Screenshot saved: {filepath} ({len(img_bytes)} bytes)")

            attachment = {
                "id": attachment_id,
                "type": "screenshot",
                "url": url,
                "target": target,
                "mode": mode,
                "description": description,
                "title": title,
                "question": question,
                "layout": layout,
                "session_id": session_id,
                "case_id": case_id or session_id,
                "planning_id": planning_id or None,
                "message_id": message_id or None,
                "request_id": request_id or None,
                "data_version": data_version or None,
                "created_at": time.time(),
                "view_metadata": view_metadata,
            }

            # Persist the attachment independently from the long-running chat
            # task.  Capturing and finalizing are separate asynchronous
            # writers: the image must first enter the Session-owned registry,
            # then be copied onto the owning message when that row exists (or
            # created below).  This prevents a stale browser checkpoint from
            # leaving a PNG on disk with no recoverable chat reference.
            chat_patch = {"attachments": [attachment]}
            if request_id or message_id:
                snapshot = store.load_snapshot(user["id"], session_id)
                chat = snapshot.get("chat") if isinstance(snapshot.get("chat"), dict) else {}
                messages = list(chat.get("messages") or [])
                owner_message = None
                for record in messages:
                    if not isinstance(record, dict):
                        continue
                    if message_id and str(record.get("id") or "") == message_id:
                        owner_message = record
                        break
                    if (
                        request_id
                        and str(record.get("request_id") or "") == request_id
                        and record.get("type") in {"bot-response", "bot"}
                    ):
                        owner_message = record
                        break
                if owner_message is None:
                    owner_message = {
                        "type": "bot-response",
                        "content": "",
                        "steps": None,
                        "timestamp": int(time.time() * 1000),
                        "id": message_id or f"assistant-{request_id}",
                        "request_id": request_id,
                        "message_kind": "assistant_final",
                        "turn_sequence": 2,
                        "response_language": response_language,
                        "trace_language": response_language,
                        "attachments": [],
                    }
                    messages.append(owner_message)
                existing_attachments = list(owner_message.get("attachments") or [])
                if not any(
                    isinstance(item, dict)
                    and str(item.get("id") or "") == attachment_id
                    for item in existing_attachments
                ):
                    existing_attachments.append(attachment)
                owner_message["attachments"] = existing_attachments[-16:]
                chat_patch["messages"] = messages
            store.save_snapshot_patch(
                user["id"],
                session_id,
                {"chat": chat_patch},
                expected_revision=None,
                reason="chat.screenshot.attached",
            )

            return jsonify({
                "success": True,
                "url": url,
                "screenshot_url": url,
                "path": url,
                "data": {"url": url},
                "filename": filename,
                "description": description,
                "target": target,
                "attachment": attachment,
            })
        except Exception as e:
            logger.error(f"Screenshot save failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/sessions/<session_id>/screenshots/<filename>")
    @rate_limit
    def api_serve_screenshot(session_id, filename):
        """Serve an authenticated screenshot from its owning case workspace."""
        if not filename.lower().endswith(".png") or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid screenshot filename"}), 400
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        try:
            filepath = store.session_artifact_path(user["id"], session_id, "screenshots", filename)
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 403
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404
        response = send_file(filepath, mimetype="image/png")
        response.headers["Cache-Control"] = "private, max-age=300"
        return response

    @app.route("/api/screenshots/<filename>")
    @rate_limit
    def api_serve_legacy_screenshot(filename):
        """Serve screenshots written by the pre-session attachment path.

        Older persisted chat attachments intentionally keep their original
        URL. Keep that URL readable during migration; new screenshots always
        use the session-scoped endpoint above. Signed URLs remain valid when
        API-key authentication is enabled.
        """
        if not filename.lower().endswith(".png") or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid screenshot filename"}), 400
        if not _valid_screenshot_request(filename):
            return jsonify({"error": "Invalid or missing API key"}), 401
        try:
            filepath = _safe_screenshot_path(filename)
        except (ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404
        response = send_file(filepath, mimetype="image/png")
        response.headers["Cache-Control"] = "private, max-age=300"
        return response
