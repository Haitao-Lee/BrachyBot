"""Planning, chat, export, and UI bridge routes for the BrachyBot web API."""

import json
import copy
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import SimpleITK as sitk
from flask import Response, current_app, jsonify, request, send_file, session as flask_session, stream_with_context

from web.auth import current_user
from web.chat_tasks import ChatTask, ChatTaskManager
from web.workspace_store import WorkspaceError, WorkspaceQuotaExceeded
from agent_runtime.core import resolve_reference_direction_input

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

_UI_BRIDGE_LOCK = _server_support._UI_BRIDGE_LOCK
_append_ui_event = _server_support._append_ui_event
_build_plan_advice = _server_support._build_plan_advice
_build_system_readiness = _server_support._build_system_readiness
_compute_manual_ai_dose = _server_support._compute_manual_ai_dose
_decode_png_data_url = _server_support._decode_png_data_url
_make_screenshot_url = _server_support._make_screenshot_url
_resolve_output_path = _server_support._resolve_output_path
_safe_screenshot_path = _server_support._safe_screenshot_path
_training_feedback_for_event = _server_support._training_feedback_for_event
_training_screenshot_for_event = _server_support._training_screenshot_for_event
_ui_bucket = _server_support._ui_bucket
_ui_session_id = _server_support._ui_session_id
_valid_screenshot_request = _server_support._valid_screenshot_request
_validate_path = _server_support._validate_path


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
    """Convert an automatic serialized plan to the frontend world snapshot."""
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
                "id": f"seed_{trajectory_index}_{seed_index}",
                "position": [float(v) for v in position[:3]],
                "direction": [float(v) for v in direction[:3]],
                "trajectory_id": trajectory_id,
            })
        points = (needle_geometry or {}).get(str(trajectory_index))
        if isinstance(points, list) and len(points) >= 2:
            needles.append({
                "id": f"needle_{trajectory_index}",
                "points": [[float(v) for v in point[:3]] for point in points[:2]],
                "trajectory_id": trajectory_id,
            })
    return {"seeds": seeds, "needles": needles}


def _current_planning_snapshot(agent):
    """Return the current manual snapshot, or the automatic baseline."""
    memory = agent.memory
    manual_seeds = memory.retrieve("manual_seeds") or []
    manual_needles = memory.retrieve("manual_needles") or []
    if manual_seeds or manual_needles:
        return {"seeds": list(manual_seeds), "needles": list(manual_needles)}
    baseline = memory.retrieve("algorithm_plan_snapshot")
    if isinstance(baseline, dict):
        return {
            "seeds": list(baseline.get("seeds") or []),
            "needles": list(baseline.get("needles") or []),
        }
    return _snapshot_from_seed_plan(
        memory.retrieve("seed_plan_serialized") or [],
        memory.retrieve("verified_needle_geometry") or {},
    )


def register_planning_routes(app, get_agent):

    # Chat workers are case-scoped and outlive an individual browser stream.
    # Switching the selected case therefore only changes presentation; it
    # cannot cancel a task that belongs to another case.
    chat_tasks = app.extensions.get("brachybot_chat_tasks")
    if chat_tasks is None:
        chat_tasks = ChatTaskManager()
        app.extensions["brachybot_chat_tasks"] = chat_tasks

    def workspace_output_dir(category: str) -> str:
        """Return an owned artifact directory; client paths are never trusted."""
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        session_id = str(flask_session.get("bb_session_id") or "")
        if not user or not session_id:
            raise WorkspaceError("Authentication required")
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
        session_id = str(flask_session.get("bb_session_id") or "")
        safe_path = "/".join(part for part in str(relative_path).replace("\\", "/").split("/") if part and part not in {".", ".."})
        return f"/api/sessions/{session_id}/artifacts/{safe_path}"

    def checkpoint_operation(agent: Any, state: str, message: str, *, checkpoint: Optional[Dict[str, Any]] = None) -> None:
        """Record a recoverable long-operation state without blocking planning."""
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        session_id = str(flask_session.get("bb_session_id") or "")
        if not store or not user or not session_id or agent is None:
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
            store.mark_operation(user["id"], session_id, agent, operation)
        except WorkspaceError:
            logger.warning("Unable to checkpoint workspace operation", exc_info=True)

    def finalize_chat_task(task: ChatTask) -> None:
        """Persist the detached task's result without relying on a browser.

        The browser normally persists its visible transcript.  That writer is
        absent while the user is viewing another case, so the background task
        must also write the user turn, trace, and final answer to the owning
        workspace.  Adjacent duplicate suppression keeps this compatible with
        a browser that remained connected for the whole turn.
        """
        store = current_app.extensions.get("brachybot_workspace_store")
        if store is None:
            return
        state = "ready" if task.status == "completed" else "interrupted"
        operation = {
            "state": state,
            "message": (
                "Chat response completed" if state == "ready"
                else (task.error or "Chat response was interrupted")
            ),
            "updated_at": time.time(),
            "checkpoint": {
                "kind": "chat",
                "task_id": task.task_id,
                "status": task.status,
                "event_count": task.event_count(),
            },
        }
        try:
            # Store the Agent checkpoint first so clinical arrays/results and
            # the transcript are never advertised as complete independently.
            store.mark_operation(task.user_id, task.session_id, task.agent, operation)
            snapshot = store.load_snapshot(task.user_id, task.session_id)
            chat = snapshot.get("chat") if isinstance(snapshot.get("chat"), dict) else {}
            messages = list(chat.get("messages") or [])

            def append_message(message_type: str, content: str, steps: Any = None) -> None:
                content = str(content or "")
                if not content and message_type != "thinking":
                    return
                candidate = {
                    "type": message_type,
                    "content": content,
                    "steps": steps,
                    "timestamp": int(task.finished_at or time.time()) * 1000,
                }
                previous = messages[-1] if messages else None
                if previous and previous.get("type") == candidate["type"] and str(previous.get("content") or "") == content:
                    return
                messages.append(candidate)

            # Do not expose an internal uploaded-image path in the durable
            # transcript; the browser's visible user bubble contains the
            # original request without that server detail.
            display_message = task.message.split("\n\n[Uploaded image path:", 1)[0]
            append_message("user", display_message)
            if task.steps:
                append_message("thinking", "", task.steps)
            if task.response:
                append_message("bot-response", task.response)
            elif task.error:
                append_message("error", "AI error: " + task.error)

            store.save_snapshot_patch(
                task.user_id,
                task.session_id,
                {
                    "chat": {
                        "messages": messages,
                        "task_id": task.task_id,
                        "task_status": task.status,
                    },
                    "operation": operation,
                },
                expected_revision=None,
                reason="chat.task.finalized",
            )
        except WorkspaceError:
            logger.warning("Unable to persist detached chat task %s", task.task_id, exc_info=True)

    def owned_case_path(path: str) -> bool:
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        session_id = str(flask_session.get("bb_session_id") or "")
        return bool(user and session_id and store.owns_path(user["id"], session_id, path))

    def request_ui_session_id(data: Optional[Dict[str, Any]] = None) -> str:
        """Resolve UI bridge state from the signed selected-case cookie.

        UI bridge events used to trust a client-side ``session_id``.  That is
        unsafe once multiple accounts share one server: even a rejected agent
        lookup could otherwise expose an in-memory bridge bucket.  Existing
        payloads retain their field for compatibility but it is deliberately
        ignored here.
        """
        _ = data
        selected = str(flask_session.get("bb_session_id") or "")
        return _ui_session_id(selected or "web")

    def task_workspace_owner() -> Optional[str]:
        """Return the server-derived owner key for transient progress tasks."""
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        session_id = str(flask_session.get("bb_session_id") or "")
        if not user or not session_id:
            return None
        return f"{user['id']}:{session_id}"

    def checkpoint_ui_bridge(session_id: str, reason: str) -> None:
        """Persist UI-controller events that do not live in AgentMemory.

        Training feedback and UI execution events are stored in the bridge so
        tools can respond immediately. They are also clinical case state and
        therefore need a JSON checkpoint before the process can be restarted
        or the case can be reopened in a different browser.
        """
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        selected = str(flask_session.get("bb_session_id") or "")
        if not store or not user or not selected or session_id != _ui_session_id(selected):
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
        try:
            store.save_snapshot_patch(
                user["id"],
                selected,
                {"ui": {"bridge": bridge}},
                expected_revision=None,
                reason=reason,
            )
        except WorkspaceError:
            logger.warning("Unable to persist UI bridge state", exc_info=True)

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

            return jsonify({
                "success": True,
                "metrics": dose_metrics,
                "seeds": seeds,
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
                "dose_scale_gy": DOSE_MODEL_SCALE_GY,
            })
        except Exception as e:
            logger.error(f"Get planning results failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

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

            result = {"success": True, "step": step}

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
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

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
                        if meta.get("ctv_source"):
                            agent.memory.store("ctv_source", meta["ctv_source"])
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
                        if meta.get("oar_array") is not None:
                            # Preserve model-emitted hard structures such as
                            # artery/vein independently from a later OAR run.
                            agent.memory.store("ctv_embedded_oar_array", meta["oar_array"])
                        if meta.get("full_label_array") is not None:
                            agent.memory.store("ctv_full_labels", meta["full_label_array"])
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
                        if meta.get("organ_names"):
                            agent.memory.store("organ_names", meta["organ_names"])
                        if meta.get("organ_counts"):
                            agent.memory.store("organ_counts", meta["organ_counts"])
                    except Exception as e:
                        logger.warning(f"store oar data failed: {e}")

            meta = getattr(result, "metadata", {}) or {}
            label_counts = meta.get("organ_counts", {}) or meta.get("label_counts", {}) or meta.get("labels_found", {}) or {}
            checkpoint_operation(
                agent,
                "ready",
                f"Manual {kind.upper()} segmentation completed",
                checkpoint={"kind": "segmentation", "segmentation_kind": kind, "completed": True},
            )
            return jsonify({
                "success": True,
                "kind": kind,
                "tumor_type": tumor_type,
                "label_counts": label_counts,
                "total_labels": len(label_counts),
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
            models = filter_catalog(site=site, include_experimental=include_experimental)
            return jsonify({"success": True, "models": models, "count": len(models)})
        except Exception as e:
            logger.error(f"CTV model catalog failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

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
            # DOSE_MODEL_SCALE_GY: the dose_unet_spacing1mm model is rendered
            # trained with labels where output 1.0 = 120 Gy.  All internal
            # dose values are normalized; multiply by this constant to get Gy.
            # This constant is shared with planning_pipeline.py and
            # AgenticSys.py — keep them in sync if the model changes.
            _ile = config.get("in_lowest_energy", 1.0)
            display_3d["_prescriptionGy"] = float(_ile) * DOSE_MODEL_SCALE_GY
            display_3d["_doseScaleGy"] = DOSE_MODEL_SCALE_GY

            return jsonify({
                "success": True,
                "iso_dose_params": iso_params or {
                    "iso_dose_values": [1.0, 1.5, 2.0, 4.0],
                    "iso_colors": [[0,1,0],[0,1,1],[1,1,0],[1,0.5,0],[1,0,0],[1,0,1],[0.5,0,0.5],[0,0.5,1]],
                    "iso_opacities": [0.3, 0.2, 0.1, 0.05],
                },
                "display_3d": display_3d,
                "in_lowest_energy": config.get("in_lowest_energy", 1.0),
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

            dose_np = np.array(dose_array)
            if dose_np.ndim != 3:
                return jsonify({"error": "Invalid dose array dimensions"}), 400

            data_min = float(dose_np.min())
            data_max = float(dose_np.max())
            logger.info(f"[dose_isosurface] threshold={threshold}, dose_range=[{data_min:.4f}, {data_max:.4f}], "
                        f"dose_shape={dose_np.shape}, spacing={spacing}, origin={origin}")

            level = float(threshold)
            # The frontend sends threshold in Gy (e.g. 50, 100, 145).
            # The dose array is in NORMALIZED units (0-94 range), and
            # dose_eval multiplies by DOSE_MODEL_SCALE_GY to get Gy. So we
            # must divide by 120 to match the dose array's range.
            level_normalized = level / DOSE_MODEL_SCALE_GY
            logger.info(f"[dose_isosurface] {level} Gy -> {level_normalized:.4f} normalized (data range: {data_min:.4f}-{data_max:.4f})")
            level = level_normalized
            if level <= data_min or level > data_max:
                return jsonify({"success": True, "vertices": [], "faces": [], "vertex_count": 0,
                                "face_count": 0, "threshold": threshold, "dose_range": [data_min, data_max],
                                "dose_units": DOSE_MODEL_UNITS, "dose_scale_gy": DOSE_MODEL_SCALE_GY})

            # Use resampled_ct spacing (z,y,x -> x,y,z for marching cubes)
            spacing_zyx = tuple(float(s) for s in spacing[::-1])

            vertices, faces, _, _ = measure.marching_cubes(dose_np, level=level, spacing=spacing_zyx, allow_degenerate=False)

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
                "dose_scale_gy": DOSE_MODEL_SCALE_GY,
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
                "dose_scale_gy": DOSE_MODEL_SCALE_GY,
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

            # Extract 2D slice (dose_np is in z,y,x order)
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
                "dose_scale_gy": DOSE_MODEL_SCALE_GY,
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
            # Read prescription in Gy: prefer memory dose_metrics
            # (already in normalized units * DOSE_MODEL_SCALE_GY) then fall
            # back to reportForm, then default 120 Gy.
            # DOSE_MODEL_SCALE_GY: normalized DoseUNet output is rendered as 120 Gy.
            prescription_gy = DOSE_MODEL_SCALE_GY  # I-125 pancreatic default
            try:
                dm = agent.memory.retrieve("dose_metrics") or {}
                pnorm = dm.get("prescribed_dose")
                if isinstance(pnorm, (int, float)) and pnorm > 0:
                    prescription_gy = float(pnorm) * DOSE_MODEL_SCALE_GY
            except Exception:
                pass
            try:
                rf = agent.memory.retrieve("report_form") or {}
                if rf.get("planning", {}).get("prescriptionGy"):
                    prescription_gy = float(rf["planning"]["prescriptionGy"])
            except Exception:
                pass
            # The dose array is in NORMALIZED units (model output, where 1.0 ≈ prescription dose).
            # iso_values_rel are relative multipliers (e.g. 1.0, 1.5, 2.0 × Rx).
            # Since the dose array is already in the same normalized space, use iso_values_rel directly.
            # DOSE_MODEL_SCALE_GY converts normalized values to Gy for display labels only.
            iso_values_gy = [float(v) * prescription_gy for v in iso_values_rel]  # Gy for labels
            iso_values_contour = [float(v) for v in iso_values_rel]  # normalized for find_contours

            # Extract 2D slice from 3D dose array
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
            valid_levels = [(c, g, r) for c, g, r in zip(iso_values_contour, iso_values_gy, iso_values_rel)
                            if s_min < c < s_max]

            if not valid_levels:
                return jsonify({
                    "success": True,
                    "contours": [],
                    "dose_range": [d_min, d_max],
                    "slice_range": [s_min, s_max],
                    "dose_units": DOSE_MODEL_UNITS,
                    "dose_scale_gy": DOSE_MODEL_SCALE_GY,
                })

            # Generate contour lines using marching squares
            contours_data = []
            for i, (level_contour, level_gy, level_rel) in enumerate(valid_levels):
                try:
                    contours = ski_measure.find_contours(slice_2d, level=level_contour)
                    # Convert to list of [row, col] coordinate arrays
                    contour_lines = []
                    for contour in contours:
                        if len(contour) > 2:  # Need at least 3 points for a line
                            contour_lines.append(contour.tolist())

                    if contour_lines:
                        # Get color for this level
                        color = iso_colors_raw[i % len(iso_colors_raw)]
                        opacity = iso_opacities[min(i, len(iso_opacities) - 1)] if iso_opacities else 0.3
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
                "dose_scale_gy": DOSE_MODEL_SCALE_GY,
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
                # The JSON defaults stay normalized for backward-compatible
                # planning code; the UI uses this scale to show physical Gy.
                "dose_scale_gy": DOSE_MODEL_SCALE_GY,
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
                "in_lowest_energy", "out_highest_energy", "DVH_rate",
                "max_iter", "rf_params", "distance_filter",
                "direc_resolution", "dl_params", "iter_rate", "replan_rate",
                "mode",
            ]
            for key in param_keys:
                if key in data:
                    agent.config[key] = data[key]

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
        agent = get_agent(session_id)
        bucket = _ui_bucket(session_id)

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
            "ctv_models": catalog_with_local_status(),
            "manual_workflow_steps": [
                "ctv_segmentation",
                "oar_segmentation",
                "trajectory_init",
                "trajectory_refine",
                "seed_planning",
                "dose_calc",
                "dose_eval",
            ],
            "manual_3d_planning": {
                "needles": ["create", "drag_endpoints", "restore_algorithm_position", "toggle_visibility", "set_opacity"],
                "seeds": ["add", "drag", "toggle_visibility", "set_opacity"],
                "dose_recompute": "dose_unet_spacing1mm",
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
        agent = get_agent(session_id)
        state_payload = data.get("ui_state") or data.get("state")
        bucket = _ui_bucket(session_id)
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
        })
        feedback = _training_feedback_for_event(agent, session_id, event)
        suggested_screenshot = _training_screenshot_for_event(agent, session_id, event, feedback)
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
            "suggested_screenshot": suggested_screenshot if bucket.get("training", {}).get("active") else None,
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
        with _UI_BRIDGE_LOCK:
            bucket["training"] = {
                "active": True,
                "goal": goal,
                "started_at": time.time(),
                "stopped_at": None,
                "events": [],
                "feedback": [],
            }
        _append_ui_event(
            session_id,
            {"type": "training.start", "label": "Training started", "detail": {"goal": goal}},
            include_in_training=False,
        )
        checkpoint_ui_bridge(session_id, "training.started")
        return jsonify({
            "success": True,
            "session_id": session_id,
            "training": bucket["training"],
            "message": "Live planning monitoring started.",
        })

    @app.route("/api/training/stop", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_training_stop():
        """Stop live monitoring and return a final deterministic training report."""
        data = request.get_json() or {}
        session_id = request_ui_session_id(data)
        agent = get_agent(session_id)
        bucket = _ui_bucket(session_id)
        with _UI_BRIDGE_LOCK:
            training = bucket.setdefault("training", {})
            training["active"] = False
            training["stopped_at"] = time.time()
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
        counts: Dict[str, int] = {}
        for event in events:
            etype = str(event.get("type", "ui.event"))
            counts[etype] = counts.get(etype, 0) + 1
        advice = _build_plan_advice(agent, session_id)
        report_lines = [
            "Planning monitoring stopped.",
            f"Recorded {len(events)} UI/planning events.",
        ]
        if counts:
            top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
            report_lines.append("Main activity: " + ", ".join(f"{k}={v}" for k, v in top))
        if advice.get("strengths"):
            report_lines.append("Strengths: " + " ".join(advice["strengths"][:3]))
        if advice.get("issues"):
            report_lines.append("Issues: " + " ".join(advice["issues"][:5]))
        if advice.get("advice"):
            report_lines.append("Recommendations: " + " ".join(advice["advice"][:6]))
        checkpoint_ui_bridge(session_id, "training.stopped")
        return jsonify({
            "success": True,
            "session_id": session_id,
            "summary": "\n".join(report_lines),
            "event_counts": counts,
            "feedback": feedback,
            "advice": advice,
            "training": training,
        })

    @app.route("/api/training/advice", methods=["GET", "POST"])
    @require_api_key
    @rate_limit
    def api_training_advice():
        """Return detailed advice for the current auto/manual plan."""
        data = request.get_json(silent=True) or {}
        session_id = request_ui_session_id(data)
        agent = get_agent(session_id)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        return jsonify(_build_plan_advice(agent, session_id))

    @app.route("/api/readiness", methods=["GET", "POST"])
    @require_api_key
    @rate_limit
    def api_readiness():
        """Return a product-readiness checklist for the current case."""
        data = request.get_json(silent=True) or {}
        session_id = request_ui_session_id(data)
        agent = get_agent(session_id)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
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
        reproject_seeds = bool(data.get("reproject_seeds")) or reason in {"needle_drag", "manual_replan"}
        try:
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
            checkpoint_operation(
                agent,
                "ready",
                "Manual dose update completed",
                checkpoint={"kind": "manual_planning", "reason": str(reason)},
            )
            return jsonify(result)
        except Exception as e:
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

        raw_needles = data.get("needles") or []
        if not isinstance(raw_needles, list) or not raw_needles:
            return jsonify({"success": False, "error": "needles must be a non-empty list"}), 400

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

            memory = agent.memory
            ct_image = memory.retrieve("ct_image")
            if ct_image is None:
                raise ValueError("No CT image loaded")
            ctv_mask = None
            for key in ("ctv_mask", "ctv_array", "ctv_full_labels"):
                candidate = memory.retrieve(key)
                if candidate is not None:
                    ctv_mask = candidate
                    break
            oar_mask = None
            for key in ("oar_array", "oar_label_data"):
                candidate = memory.retrieve(key)
                if candidate is not None:
                    oar_mask = candidate
                    break
            _server_support._validate_manual_needle_safety(
                agent, normalized_needles, ct_image, ctv_mask, oar_mask
            )

            current = _current_planning_snapshot(agent)
            current_seeds = list(current.get("seeds") or [])
            # Keep seeds and geometry coherent for later explicit replanning,
            # restore, reload, and session switching.
            memory.store("manual_seeds", current_seeds)
            memory.store("manual_needles", normalized_needles)
            memory.store("manual_geometry_only", True)
            reason = str(data.get("reason") or "needle_position_only")
            event = _append_ui_event(session_id, {
                "type": "manual.needle.position_only",
                "label": reason,
                "detail": {
                    "needle_count": len(normalized_needles),
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
                "needles": normalized_needles,
                "seeds": current_seeds,
                "dose_recomputed": False,
                "event": event,
            })
        except _server_support.ManualNeedleSafetyError as exc:
            logger.warning("Position-only needle update rejected: %s", exc)
            return jsonify({
                "success": False,
                "error": str(exc),
                "code": exc.code,
                "rejected_needle_ids": exc.rejected_needle_ids,
            }), 422
        except Exception as exc:
            logger.exception("Position-only needle update failed")
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
        try:
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
            checkpoint_operation(
                agent,
                "ready",
                f"Restored {needle_id} to the algorithm baseline",
                checkpoint={"kind": "manual_planning", "reason": "restore_algorithm_needle", "needle_id": needle_id},
            )
            result["restored_needle_id"] = needle_id
            result["needles"] = new_needles
            result["seeds"] = new_seeds
            result["event"] = _append_ui_event(session_id, {
                "type": "manual.needle.restore",
                "label": f"Restored {needle_id} to algorithm baseline",
                "detail": {"needle_id": needle_id},
            })
            return jsonify(result)
        except Exception as exc:
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
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        status = agent.get_status()
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
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        if user:
            try:
                entry = store.get_session(user["id"], str(flask_session.get("bb_session_id") or ""))
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
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        try:
            store = current_app.extensions.get("brachybot_workspace_store")
            user = current_user(store) if store is not None else None
            session_id = str(flask_session.get("bb_session_id") or "")
            if user and session_id:
                chat_tasks.cancel(chat_tasks.active(user["id"], session_id))
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

            organ_names = agent.memory.retrieve("organ_names") or {}
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
                    if not name:
                        try:
                            from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
                            name = TOTALSEG_LABEL_MAPPING.get(label_id)
                        except Exception:
                            name = None
                    base_name = str(name or f"Organ_{label_id}")
                    unique_name = base_name if base_name not in used_names else f"{base_name}_{label_id}"
                    used_names.add(unique_name)
                    structures[unique_name] = oar_array == label

            dose_metrics = agent.memory.retrieve("dose_metrics") or {}
            dose_scale_gy = float(
                agent.memory.retrieve("dose_scale_gy") or DOSE_MODEL_SCALE_GY
            )
            prescription_gy = dose_metrics.get("prescription_gy")
            if not prescription_gy:
                prescription_norm = dose_metrics.get("prescribed_dose")
                if isinstance(prescription_norm, (int, float)) and prescription_norm > 0:
                    prescription_gy = float(prescription_norm) * dose_scale_gy

            plan_config = agent.memory.retrieve("plan_config") or {}
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
                    store = current_app.extensions.get("brachybot_workspace_store")
                    user = current_user(store) if store is not None else None
                    session_id = str(flask_session.get("bb_session_id") or "")
                    if not store or not user or not session_id:
                        raise WorkspaceError("Authentication required")
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
        # ``session_id`` remains tolerated in older browser payloads, but the
        # authenticated user's selected workspace is always authoritative.
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        # Handle clear_context for backward compatibility
        if clear_context:
            agent.memory.clear_conversation()
            logger.info("Conversation context cleared")

        if clear_context and not message and not image_path:
            return jsonify({"success": True, "message": "Conversation context cleared"})

        if not message and not image_path:
            return jsonify({"error": "message or image is required"}), 400

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
            store = current_app.extensions.get("brachybot_workspace_store")
            user = current_user(store) if store is not None else None
            session_id = str(flask_session.get("bb_session_id") or "")
            if not user or not session_id:
                return jsonify({"error": "Authentication required"}), 401
            start_gate = threading.Event()
            try:
                task = chat_tasks.start(
                    current_app._get_current_object(),
                    user["id"],
                    session_id,
                    agent,
                    full_message,
                    ui_state,
                    on_finish=finalize_chat_task,
                    start_gate=start_gate,
                )
            except RuntimeError as exc:
                return jsonify({
                    "error": str(exc),
                    "code": "chat_task_running",
                }), 409

            try:
                checkpoint_operation(
                    agent,
                    "running",
                    "Chat response is in progress",
                    checkpoint={
                        "kind": "chat",
                        "task_id": task.task_id,
                        "user_message": message[:500],
                    },
                )
                # Persist the task identity separately from the agent
                # checkpoint.  This small merge makes the running task
                # discoverable after a case switch or browser refresh even
                # when the full agent snapshot is still being written.
                try:
                    store.save_snapshot_patch(
                        user["id"],
                        session_id,
                        {"chat": {"task_id": task.task_id, "task_status": "running"}},
                        expected_revision=None,
                        reason="chat.task.started",
                    )
                except WorkspaceError:
                    logger.warning("Unable to persist chat task identity %s", task.task_id, exc_info=True)
            finally:
                # Release the worker only after the running checkpoint has
                # been written, preventing a fast Q&A turn from overwriting
                # its final ready checkpoint with a late running state.
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
        """Return the latest in-process task for the selected case."""
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        session_id = str(flask_session.get("bb_session_id") or "")
        if not user or not session_id:
            return jsonify({"error": "Authentication required"}), 401
        task = chat_tasks.active(user["id"], session_id) or chat_tasks.latest(user["id"], session_id)
        return jsonify({"task": task.public_state() if task is not None else None})

    @app.route("/api/chat/tasks/<task_id>/stream", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_chat_task_stream(task_id: str):
        """Replay/follow one selected-case task after a case switch."""
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        session_id = str(flask_session.get("bb_session_id") or "")
        if not user or not session_id:
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

            store = current_app.extensions.get("brachybot_workspace_store")
            user = current_user(store) if store is not None else None
            session_id = str(flask_session.get("bb_session_id") or "")
            if not store or not user or not session_id:
                raise WorkspaceError("Authentication required")
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
        """Receive a screenshot from the frontend and save it."""
        data = request.get_json() or {}
        image_data = data.get("image", "")  # base64 data URL
        description = data.get("description", "screenshot")
        target = data.get("target", "unknown")

        if not image_data:
            return jsonify({"error": "No image data provided"}), 400

        try:
            import uuid
            img_bytes = _decode_png_data_url(image_data)

            filename = f"screenshot_{uuid.uuid4().hex[:12]}.png"
            store = current_app.extensions.get("brachybot_workspace_store")
            user = current_user(store) if store is not None else None
            session_id = str(flask_session.get("bb_session_id") or "")
            if not user or not session_id:
                return jsonify({"error": "Authentication required"}), 401
            filepath = store.write_screenshot(user["id"], session_id, filename, img_bytes)
            url = f"/api/sessions/{session_id}/screenshots/{filename}"
            logger.info(f"Screenshot saved: {filepath} ({len(img_bytes)} bytes)")

            return jsonify({
                "success": True,
                "url": url,
                "screenshot_url": url,
                "path": url,
                "data": {"url": url},
                "filename": filename,
                "description": description,
                "target": target,
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
