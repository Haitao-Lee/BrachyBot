"""Viewer and 3D visualization routes for the BrachyBot web API."""

import gzip
import json
import logging
import os
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import SimpleITK as sitk
from flask import Response, current_app, jsonify, request, send_from_directory, session as flask_session

from web.auth import current_user
from web.structure_service import build_effective_structures
from agent_runtime.core import PlanningPhase

try:
    from web.server_support import rate_limit, require_api_key
    from web import server_support as _server_support
except ImportError:  # pragma: no cover - supports `python web/server.py`.
    from server_support import rate_limit, require_api_key  # type: ignore
    import server_support as _server_support  # type: ignore

logger = logging.getLogger(__name__)

_MESH_CACHE = _server_support._MESH_CACHE
_MESH_CACHE_LOCK = _server_support._MESH_CACHE_LOCK
_MESH_CACHE_MAX_ITEMS = _server_support._MESH_CACHE_MAX_ITEMS
_MESH_CACHE_ORDER = _server_support._MESH_CACHE_ORDER
_label_color = _server_support._label_color
_validate_path = _server_support._validate_path

_UPLOADED_LABEL_SOURCES = {
    "manual_label",
    "uploaded_unknown",
    "uploaded",
    "manual_upload",
}


def _viewer_label_array(agent, array_key, path_key, source, reference_image, target_shape):
    """Return one label volume on the current CT grid for every viewer path.

    The label-volume endpoint and the per-slice fallback used to read different
    representations: the former aligned uploaded masks from their NIfTI
    geometry while the latter read the raw in-memory NumPy array.  That made a
    mask disappear or appear mirrored whenever the uploaded image used a
    different direction/spacing.  Keep one physical-grid resolver for both
    paths and only use the legacy shape fit when no physical source is left.
    """
    source_name = str(source or "").strip().lower()
    path = agent.memory.retrieve(path_key)
    if not path:
        path = agent.memory.retrieve(
            "ctv_mask_path" if array_key == "ctv_array" else "oar_mask_path"
        )
    if source_name in _UPLOADED_LABEL_SOURCES and path and reference_image is not None:
        try:
            from tool_factory.segmentation_alignment import align_label_to_reference

            aligned = align_label_to_reference(str(path), reference_image, "LPI")
            return sitk.GetArrayFromImage(aligned)
        except Exception as exc:
            logger.warning("[viewer] uploaded %s alignment failed: %s", array_key, exc)

    value = agent._get_label_array(array_key)
    if value is None:
        return None
    array = np.asarray(value)
    if tuple(array.shape) != tuple(target_shape):
        array = _resample_legacy_label_array(array, reference_image, target_shape)
    return array


def _resample_legacy_label_array(array, reference, target_shape):
    """Fit a legacy array onto the CT grid without ``CopyInformation``.

    Older snapshots stored only a NumPy label array, not its physical image
    metadata.  SimpleITK raises when ``CopyInformation`` is applied to
    different-sized images; that was the source of the intermittent
    ``label_volume`` 500.  The fallback preserves the CT orientation and
    physical extent as far as the legacy metadata permits, then uses nearest
    neighbour interpolation and a final shape guard.
    """
    source = sitk.GetImageFromArray(np.asarray(array, dtype=np.uint16))
    if reference is not None:
        source_size = source.GetSize()
        reference_size = reference.GetSize()
        reference_spacing = reference.GetSpacing()
        source_spacing = tuple(
            float(reference_spacing[index])
            * max(int(reference_size[index]) - 1, 1)
            / max(int(source_size[index]) - 1, 1)
            for index in range(3)
        )
        source.SetSpacing(source_spacing)
        source.SetOrigin(reference.GetOrigin())
        source.SetDirection(reference.GetDirection())
        resampled = sitk.Resample(
            source,
            reference,
            sitk.Transform(),
            sitk.sitkNearestNeighbor,
            0,
            sitk.sitkUInt16,
        )
        result = sitk.GetArrayFromImage(resampled).astype(np.uint16, copy=False)
    else:
        result = np.zeros(target_shape, dtype=np.uint16)
        common = tuple(min(int(result.shape[index]), int(array.shape[index])) for index in range(3))
        source_slices = tuple(slice(0, length) for length in common)
        result[source_slices] = np.asarray(array, dtype=np.uint16)[source_slices]
    if tuple(result.shape) == tuple(target_shape):
        return result
    guarded = np.zeros(target_shape, dtype=np.uint16)
    common = tuple(min(int(guarded.shape[index]), int(result.shape[index])) for index in range(3))
    slices = tuple(slice(0, length) for length in common)
    guarded[slices] = result[slices]
    return guarded


def _requires_label_faithful_mesh(agent, source: str, label_id: int) -> bool:
    """Return whether a mesh must preserve the exact planning-mask boundary.

    Non-traversable structures are part of the planning safety contract.  The
    presentation-oriented dilation, closing, and hole filling used for small
    soft-tissue meshes can move their visible boundary away from the mask
    checked by the trajectory safety gate.  For those labels, render the raw
    mask boundary instead so a needle that is safe in the planner is not made
    to look as though it traverses a reconstructed obstacle.
    """
    try:
        from tool_factory.seed_plan.planning_pipeline import _resolve_data_tree_obstacle_labels

        hard_labels, _ = _resolve_data_tree_obstacle_labels(agent)
        if int(label_id) in {int(value) for value in hard_labels}:
            return True
    except Exception:
        logger.exception("[viewer_3d] Could not resolve the current hard-obstacle policy")

    # The pancreatic CTV model carries artery and vein in its own label
    # namespace.  They are always hard obstacles in planning_pipeline even
    # though their numeric IDs are unrelated to TotalSegmentator labels.
    return str(source or "").strip().lower() == "ctv" and int(label_id) in {2, 3}


def register_viewer_routes(app, get_agent, load_ct_image, extract_dicom_tags):
    def request_case_context():
        """Resolve the case that originated this viewer request.

        The browser's selected-case cookie is only a navigation fallback.
        Delayed loads and render callbacks send ``X-BrachyBot-Session`` so
        switching tabs or cases cannot redirect them into another workspace.
        """
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        session_id = str(
            request.headers.get("X-BrachyBot-Session")
            or flask_session.get("bb_session_id")
            or ""
        ).strip()
        if store is None or user is None or not session_id:
            raise ValueError("Authenticated case session is required")
        entry = store.get_session(user["id"], session_id)
        return store, user, entry.id

    def owned_case_path(path: str) -> bool:
        try:
            store, user, session_id = request_case_context()
        except Exception:
            return False
        return bool(store.owns_path(user["id"], session_id, path))

    def workspace_data_pending(agent, *, require: str = "all"):
        """Return a non-blocking restore response while arrays are decoding."""
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
        ready = (
            getattr(agent, "_workspace_ct_ready", False)
            if require == "ct"
            else getattr(agent, "_workspace_data_ready", True)
        )
        if agent is not None and not ready:
            return jsonify({
                "success": False,
                "pending": True,
                "code": "workspace_hydration_pending",
                "message": "Case resources are still loading.",
                "phase": getattr(agent, "_workspace_hydration_phase", "artifacts"),
                "retry_after_ms": 250,
            }), 202
        return None

    def loaded_ct_response(agent):
        """Describe the hydrated CT without mutating case-owned memory."""
        import numpy as np

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return None
        shape = tuple(int(v) for v in ct_data.shape)
        spacing = tuple(agent.memory.retrieve("ct_spacing") or (1.0, 1.0, 1.0))
        origin = tuple(agent.memory.retrieve("ct_origin") or (0.0, 0.0, 0.0))
        direction = tuple(
            agent.memory.retrieve("ct_direction")
            or (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        )
        axis_map = agent.memory.retrieve("ct_axis_map") or {
            "axial": 0, "sagittal": 2, "coronal": 1,
        }
        return {
            "success": True,
            "restored": True,
            "slices": {
                name: {
                    "slice_index": int(shape[axis] // 2),
                    "total_slices": int(shape[axis]),
                    "shape": list(shape),
                }
                for name, axis in axis_map.items()
            },
            "spacing": [float(v) for v in spacing],
            "origin": [float(v) for v in origin],
            "direction": [float(v) for v in direction],
            "shape": list(shape),
            "hu_range": [float(np.min(ct_data)), float(np.max(ct_data))],
            "dicom": agent.memory.retrieve("ct_dicom_tags") or {},
            "source_kind": agent.memory.retrieve("ct_source_kind") or "nifti",
        }

    @app.route("/api/viewer/load", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_load():
        """Load CT image and return slice metadata (no pixel data)."""
        # Install a lightweight agent immediately; large case artifacts are
        # decoded by the server's background hydration worker.
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        ct_path = data.get("ct_path")
        window_center = data.get("window_center", 40)
        window_width = data.get("window_width", 400)

        if not ct_path:
            return jsonify({"error": "ct_path is required"}), 400
        if not _validate_path(ct_path, purpose="read") or not owned_case_path(ct_path):
            return jsonify({"error": "Invalid ct_path"}), 400

        prev_ct_path = agent.memory.retrieve("ct_path")
        try:
            same_ct = bool(
                prev_ct_path
                and Path(str(prev_ct_path)).resolve() == Path(str(ct_path)).resolve()
            )
        except (OSError, ValueError):
            same_ct = str(prev_ct_path or "") == str(ct_path)
        if same_ct:
            pending = workspace_data_pending(agent, require="ct")
            if pending is not None:
                return pending
            restored = loaded_ct_response(agent)
            if restored is not None:
                # This is a display restore, not a new-patient import. Reusing
                # the hydrated CT here is what keeps OAR, planning, DVH and
                # report artifacts intact after a refresh or case switch.
                return jsonify(restored)

        # Per-patient memory isolation: if a DIFFERENT CT is being
        # loaded, wipe all planning / segmentation / dose state from
        # the previous patient. The agent otherwise happily reuses
        # stale CTV/OAR/planning data from a previous case, which
        # causes wrong masks, wrong seeds, and confusing reports.
        # The user's expectation: same CT path → reuse memory
        # (continuing work on the same patient); different CT path
        # → fresh start.
        if prev_ct_path and prev_ct_path != ct_path:
            logger.info(f"[patient-isolation] CT changed ({prev_ct_path} → {ct_path}), clearing previous patient's state")
            try:
                agent.memory.clear_all_data()
            except Exception as e:
                logger.warning(f"[patient-isolation] clear_all_data failed: {e}")

        try:
            import numpy as np
            import SimpleITK as sitk

            logger.info(f"Loading CT from: {ct_path}")
            agent._workspace_hydration_superseded = True
            hydration_cancel = getattr(agent, "_workspace_hydration_cancel", None)
            if hydration_cancel is not None:
                hydration_cancel.set()
            ct_sitk, kind, src_meta = load_ct_image(ct_path)
            logger.info(f"CT source kind: {kind}; meta: {src_meta}")

            # Reorient to LPI (Left-Posterior-Inferior) standard anatomical orientation
            ct_oriented = sitk.DICOMOrient(ct_sitk, 'LPI')
            logger.info(f"Reoriented to LPI")

            ct_data = sitk.GetArrayFromImage(ct_oriented)  # Shape: (Z, Y, X) in LPI orientation
            spacing = ct_oriented.GetSpacing()  # (X, Y, Z)
            origin = ct_oriented.GetOrigin()  # (X, Y, Z)
            direction = ct_oriented.GetDirection()  # 9-element tuple
            shape = ct_data.shape
            logger.info(f"CT shape after orientation (ZYX): {shape}, spacing (XYZ): {spacing}")

            # Store in agent memory
            agent.memory.store("ct_image", ct_oriented)
            agent.memory.store("ct_image_raw", ct_sitk)  # Pre-orientation, for label alignment
            agent.memory.store("ct_data", ct_data)
            agent.memory.store("ct_spacing", spacing)
            agent.memory.store("ct_origin", origin)
            agent.memory.store("ct_direction", direction)
            agent.memory.store("ct_shape", list(shape))
            agent.memory.store("ct_window_center", window_center)
            agent.memory.store("ct_window_width", window_width)
            # Threshold is an optional display filter and is scoped to the
            # loaded CT. Never carry a previous patient's threshold overlay
            # into a newly loaded study.
            agent.memory.store("viewer_threshold", None)
            agent.memory.store("ct_path", ct_path)  # Store path for 3D reconstruction

            # A new CT invalidates every prior segmentation, plan, and dose
            # result.  Without this clearing, the deduplication guards in
            # _execute_tool_with_memory can skip a fresh CTV/OAR run because
            # the old patient's arrays are still in memory after a session
            # switch or page refresh.
            for _key in (
                "ctv_array", "ctv_mask", "ctv_full_labels", "ctv_label_map",
                "ctv_path", "ctv_source", "ctv_volume_mm3", "ctv_voxel_count",
                "oar_array", "oar_mask", "oar_is_full", "oar_source",
                "label_grid_orientation",
                "organ_names", "organ_counts", "dose_metrics", "dose_distribution",
                "dose_distribution_gy", "seed_plan", "seed_plan_serialized",
                "seed_positions", "trajectories", "refined_trajectories",
                "verified_needle_geometry", "dvh_data",
            ):
                agent.memory.store(_key, None)
            agent.memory.conversation_state["planning_completed"] = False
            agent.memory.conversation_state["ctv_segmentation_done"] = False
            agent.memory.conversation_state["oar_segmentation_done"] = False
            agent.memory.current_phase = PlanningPhase.IDLE
            agent.memory.store("ct_source_kind", kind)
            # Label arrays produced after this load are normalized to the
            # viewer's LPI CT grid. Persist this invariant with the case.
            agent.memory.store("label_grid_orientation", "LPI")

            # Update UI state so LLM knows CT is loaded
            agent.memory.set_ui_state({"ct_path": ct_path})

            if src_meta:
                # Don't store the heavy first_slice_tags blob — only summary
                summary = {k: v for k, v in src_meta.items() if k != "first_slice_tags"}
                agent.memory.store("ct_source_meta", summary)

            # Extract DICOM tags (best-effort, no-op for NIfTI). For series
            # reads the assembled volume's metadata is empty — fall back to
            # the tags we read off the first slice in the helper.
            dicom_tags = extract_dicom_tags(ct_sitk)
            if not dicom_tags and src_meta.get("first_slice_tags"):
                dicom_tags = dict(src_meta["first_slice_tags"])
            if dicom_tags:
                agent.memory.store("ct_dicom_tags", dicom_tags)

            # After LPI orientation:
            # - Array axis 0 = Z = Superior->Inferior (head to foot)
            # - Array axis 1 = Y = Anterior->Posterior (front to back)
            # - Array axis 2 = X = Left->Right (patient left on right side of image)
            axis_map = {
                'axial': 0,    # Z axis (short axis, 48 slices)
                'sagittal': 2, # X axis (left-right)
                'coronal': 1,  # Y axis (anterior-posterior)
            }
            agent.memory.store("ct_axis_map", axis_map)
            agent._workspace_ct_ready = True
            agent._workspace_data_ready = True
            agent._workspace_hydration_in_progress = False
            agent._workspace_hydration_phase = "ready"
            agent._workspace_hydration_error = ""
            ready_event = getattr(agent, "_workspace_ready_event", None)
            if ready_event is not None:
                ready_event.set()

            slices = {}
            for name, axis in axis_map.items():
                mid = int(shape[axis] // 2)
                slices[name] = {
                    'slice_index': mid,
                    'total_slices': int(shape[axis]),
                    'shape': [int(shape[0]), int(shape[1]), int(shape[2])],
                }

            response = {
                "success": True,
                "slices": slices,
                "spacing": [float(spacing[0]), float(spacing[1]), float(spacing[2])],
                "origin": [float(origin[0]), float(origin[1]), float(origin[2])],
                "direction": [float(d) for d in direction],
                "shape": [int(shape[0]), int(shape[1]), int(shape[2])],
                "hu_range": [float(ct_data.min()), float(ct_data.max())],
                "dicom": dicom_tags,
                "source_kind": kind,
            }
            if kind == "dicom_series":
                response["series_count"] = src_meta.get("series_count", 0)
                response["file_count"] = src_meta.get("file_count", 0)
            return jsonify(response)
        except Exception as e:
            import traceback
            logger.error(f"Viewer load failed: {e}")
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/slice", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_slice():
        """Get a specific slice from loaded CT as PNG image."""
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        pending = workspace_data_pending(agent, require="ct")
        if pending is not None:
            return pending

        data = request.get_json() or {}
        axis_name = data.get("axis", "axial")
        slice_index = data.get("slice_index", 0)
        window_center = data.get("window_center", agent.memory.retrieve("ct_window_center") or 40)
        window_width = data.get("window_width", agent.memory.retrieve("ct_window_width") or 400)
        threshold = data.get("threshold", None)

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import numpy as np
            from io import BytesIO
            from PIL import Image

            axis_map = agent.memory.retrieve("ct_axis_map") or {
                'axial': 0, 'sagittal': 2, 'coronal': 1,
            }
            axis = axis_map.get(axis_name, 0)
            # Apply window/level
            lower = window_center - window_width / 2
            upper = window_center + window_width / 2
            ct_windowed = np.clip(ct_data, lower, upper)
            ct_windowed = ((ct_windowed - lower) / (upper - lower) * 255).astype(np.uint8)

            # Get slice - with LPI orientation, ct_data is (Z, Y, X)
            # axial: axis 0 -> (Y, X) = (512, 512), no transpose needed
            # sagittal: axis 2 -> (Z, Y) = (48, 512), transpose for Z vertical
            # coronal: axis 1 -> (Z, X) = (48, 512), transpose for Z vertical
            slice_data = np.take(ct_windowed, slice_index, axis=axis)

            # Apply Z-flip to match raw DICOM ordering in sagittal/coronal views.
            # DICOMOrient('LPI') reverses array Z so LPI Z=0 = head. We invert again at
            # render time so the user sees raw DICOM convention (slider 0 = feet).
            # Axial: single slice, flip via (Z-1)-sliceIndex in the take above.
            if axis_name == 'axial':
                src_idx = ct_data.shape[0] - 1 - slice_index
                slice_data = np.take(ct_windowed, src_idx, axis=axis)
            elif axis_name == 'sagittal':
                # (Z, Y) -> (Y, Z) with Z flipped so top of canvas = raw Z=0 (feet)
                z_arr = np.arange(ct_data.shape[0])[::-1]
                slice_data = ct_windowed[z_arr, :, slice_index].T
            elif axis_name == 'coronal':
                z_arr = np.arange(ct_data.shape[0])[::-1]
                slice_data = ct_windowed[z_arr, slice_index, :].T

            # Apply threshold overlay if requested
            if threshold is not None:
                # Thresholds are specified in physical HU. The displayed CT is
                # windowed to uint8 only for rendering, so computing this mask
                # on raw HU is intentional and anatomically correct.
                mask = ct_data > threshold
                if axis_name == 'axial':
                    src_idx = mask.shape[0] - 1 - slice_index
                    mask_slice = np.take(mask, src_idx, axis=axis)
                elif axis_name == 'sagittal':
                    z_arr = np.arange(mask.shape[0])[::-1]
                    mask_slice = mask[z_arr, :, slice_index].T
                elif axis_name == 'coronal':
                    z_arr = np.arange(mask.shape[0])[::-1]
                    mask_slice = mask[z_arr, slice_index, :].T
                # Create RGB overlay
                slice_rgb = np.stack([slice_data] * 3, axis=-1)
                slice_rgb[mask_slice, 0] = np.minimum(255, slice_rgb[mask_slice, 0].astype(int) + 120)
                slice_rgb[mask_slice, 1] = np.maximum(0, slice_rgb[mask_slice, 1].astype(int) - 80)
                slice_rgb[mask_slice, 2] = np.maximum(0, slice_rgb[mask_slice, 2].astype(int) - 80)
                img = Image.fromarray(slice_rgb)
            else:
                img = Image.fromarray(slice_data)

            # Downsample if too large for display
            max_dim = 512
            if img.width > max_dim or img.height > max_dim:
                ratio = max(img.width / max_dim, img.height / max_dim)
                new_size = (int(img.width / ratio), int(img.height / ratio))
                img = img.resize(new_size, Image.LANCZOS)

            # Convert to base64 PNG
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            import base64
            img_str = base64.b64encode(buffered.getvalue()).decode()

            return jsonify({
                "success": True,
                "data": f"data:image/png;base64,{img_str}",
                "shape": list(slice_data.shape),
            })
        except Exception as e:
            import traceback
            logger.error(f"Viewer slice failed: {e}")
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/volume", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_viewer_volume():
        """Return entire CT volume as binary blob for client-side rendering."""
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        pending = workspace_data_pending(agent, require="ct")
        if pending is not None:
            return pending

        ct_data = agent.memory.retrieve("ct_data")
        spacing = agent.memory.retrieve("ct_spacing")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import numpy as np

            # Convert to int16 for compact HU transfer. Clip first so unusual
            # scanner/private values cannot wrap around during dtype casting.
            ct_int16 = np.clip(ct_data, np.iinfo(np.int16).min, np.iinfo(np.int16).max).astype(np.int16)
            raw_bytes = ct_int16.tobytes()

            accept_encoding = request.headers.get("Accept-Encoding", "")
            content = raw_bytes
            if "gzip" in accept_encoding:
                content = gzip.compress(raw_bytes, compresslevel=4)
                content_encoding = "gzip"
            else:
                content_encoding = None

            response = Response(content, mimetype='application/octet-stream')
            if content_encoding:
                response.headers['Content-Encoding'] = content_encoding
            response.headers['X-Shape-Z'] = str(ct_data.shape[0])
            response.headers['X-Shape-Y'] = str(ct_data.shape[1])
            response.headers['X-Shape-X'] = str(ct_data.shape[2])
            response.headers['X-Spacing-X'] = str(float(spacing[0]))
            response.headers['X-Spacing-Y'] = str(float(spacing[1]))
            response.headers['X-Spacing-Z'] = str(float(spacing[2]))
            response.headers['X-Dtype'] = 'int16'
            return response
        except Exception as e:
            logger.error(f"Volume export failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/label_volume", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_viewer_label_volume():
        """Return CTV uint8 and OAR uint16 label volumes for client rendering."""
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import numpy as np
            import json as _json
            from tool_factory.segmentation_alignment import align_label_to_reference

            # Use full multi-label array for CTV (includes tumor, artery, vein, pancreas, etc.)
            # Falls back to binary ctv_array if full labels not available
            ctv_source = str(agent.memory.retrieve("ctv_source", "") or "").strip().lower()
            oar_source = str(agent.memory.retrieve("oar_source", "") or "").strip().lower()
            ct_ref = agent.memory.retrieve("ct_image")

            uploaded_sources = {
                "manual_label",
                "uploaded_unknown",
                "uploaded",
                "manual_upload",
            }

            def _uploaded_label_array(source, array_key, path_key):
                """Reload uploaded labels on the current LPI CT grid.

                Older snapshots may contain a same-shaped raw-grid array. If
                the case still has the original uploaded path, use its physical
                metadata instead of trusting the legacy array orientation.
                """
                path = agent.memory.retrieve(path_key)
                # Older checkpoints used the explicit ``*_mask_path`` key.
                # Prefer the canonical key, but keep the fallback so a mask
                # uploaded before the workspace schema migration is still
                # aligned from its physical metadata rather than a stale raw
                # NumPy array.
                if not path:
                    path = agent.memory.retrieve(
                        "ctv_mask_path" if array_key == "ctv_array" else "oar_mask_path"
                    )
                if source in uploaded_sources and path and ct_ref is not None:
                    try:
                        return sitk.GetArrayFromImage(
                            align_label_to_reference(str(path), ct_ref, "LPI")
                        )
                    except Exception as exc:
                        logger.warning("[label_volume] uploaded %s alignment failed: %s", array_key, exc)
                return agent._get_label_array(array_key)

            ctv_full_memory = agent._get_label_array("ctv_full_labels")
            # Only model-produced multi-label CTV output may be split into
            # embedded artery/vein/pancreas OAR labels. Uploaded CTV data is
            # opaque user data and remains a foreground CTV mask.
            ctv_full = ctv_full_memory if ctv_source == "model" else None
            if ctv_full is None:
                ctv_full = _uploaded_label_array(ctv_source, "ctv_array", "ctv_path")
            oar_array = _uploaded_label_array(oar_source, "oar_array", "oar_path")

            # Reorganize labels for data tree:
            # - CTV node: only tumor (label 1)
            # - OAR non-traversable: artery (label 2), vein (label 3) from nnUNet
            # - OAR traversable: pancreas (label 4) from nnUNet
            ctv_array = None
            if ctv_full is not None:
                # Model output reserves label 1 for the tumor and may contain
                # embedded anatomy labels.  An uploaded CTV is opaque user
                # data, so every non-zero voxel is CTV even when its source
                # label is 255 or another application-specific value.
                if ctv_source == "model":
                    ctv_array = (
                        (ctv_full == 1).astype(np.uint8)
                        if np.any(ctv_full == 1)
                        else None
                    )
                else:
                    ctv_array = (ctv_full > 0).astype(np.uint8)

                # Merge embedded nnUNet vessel/organ labels only when no
                # user-supplied OAR mask exists.  An uploaded unknown mask is
                # an opaque, complete label volume: adding anatomy-derived
                # labels would manufacture structures the user did not
                # provide and would make the Data Tree disagree with the
                # imported image.
                nnunet_oar_labels = {
                    2: 201,   # artery -> OAR label 201
                    3: 202,   # vein -> OAR label 202
                    4: 203,   # pancreas -> OAR label 203
                }
                has_nnunet_oar = False
                if oar_source not in uploaded_sources:
                    for src_label, dst_label in nnunet_oar_labels.items():
                        if np.any(ctv_full == src_label):
                            has_nnunet_oar = True
                            break

                if has_nnunet_oar:
                    if oar_array is None:
                        # Embedded anatomy is remapped to IDs 201-203. Keep
                        # the working volume wide enough before assignment;
                        # uint8 wrapped those IDs before transport.
                        oar_array = np.zeros_like(ctv_full, dtype=np.uint16)
                    elif oar_array.shape != ctv_full.shape:
                        # Shape mismatch - likely orientation issue
                        # Skip merging to avoid IndexError
                        logger.warning(f"[label_volume] OAR shape {oar_array.shape} != CTV shape {ctv_full.shape}, skipping nnUNet label merge")
                        has_nnunet_oar = False  # Disable the merge below

                    if has_nnunet_oar:
                        if oar_array.dtype.itemsize < 2:
                            oar_array = oar_array.astype(np.uint16, copy=False)
                        for src_label, dst_label in nnunet_oar_labels.items():
                            mask = ctv_full == src_label
                            if np.any(mask):
                                oar_array[mask] = dst_label

            shape = ct_data.shape  # (Z, Y, X)

            # Ensure label arrays have same shape as CT
            if ctv_array is not None and ctv_array.shape != shape:
                logger.warning(f"CTV shape mismatch: {ctv_array.shape} vs CT {shape}, resampling...")
                ctv_array = _resample_legacy_label_array(ctv_array, ct_ref, shape)

            if oar_array is not None and oar_array.shape != shape:
                logger.warning(f"OAR shape mismatch: {oar_array.shape} vs CT {shape}, resampling...")
                oar_array = _resample_legacy_label_array(oar_array, ct_ref, shape)

            effective = None
            ctv_object_map = {}
            oar_object_map = {}
            if agent.memory.retrieve("structure_registry_initialized"):
                effective = build_effective_structures(agent.memory)
                ctv_array = effective.ctv_array
                oar_array = effective.oar_array
                for item in effective.structures:
                    target_label = int(item["target_label"])
                    if item["classification"] == "ctv":
                        ctv_object_map[target_label] = str(item["object_id"])
                    else:
                        oar_object_map[target_label] = str(item["object_id"])

            # Build color LUT for all labels
            color_lut = {}
            if ctv_array is not None:
                # Add all CTV labels with distinct colors
                for lid in np.unique(ctv_array):
                    if lid > 0:
                        color_lut[int(lid)] = list(_label_color(int(lid)))
            if oar_array is not None:
                for lid in np.unique(oar_array):
                    if lid > 0:
                        color_lut[int(lid)] = list(_label_color(int(lid)))

            # Build binary payload: ctv bytes + oar bytes
            payload = bytearray()
            ctv_offset = 0

            if ctv_array is not None:
                ctv_u8 = ctv_array.astype(np.uint8)
                unique_labels = list(np.unique(ctv_u8))
                logger.info(f"CTV array unique labels: {unique_labels}, shape: {ctv_u8.shape}")
                payload.extend(ctv_u8.tobytes())
                ctv_offset = len(payload)

            if oar_array is not None:
                # OAR labels include nnUNet-derived IDs 201-203 and the
                # explicit embedded-obstacle label 10000.  uint8 silently
                # wrapped those values, making the Data Tree and 2D overlay
                # disagree.  Keep the wire format little-endian uint16.
                oar_u16 = np.asarray(oar_array, dtype="<u2")
                payload.extend(oar_u16.tobytes())

            response = Response(bytes(payload), mimetype='application/octet-stream')
            accept_encoding = request.headers.get("Accept-Encoding", "")
            if "gzip" in accept_encoding:
                response.set_data(gzip.compress(bytes(payload), compresslevel=4))
                response.headers['Content-Encoding'] = 'gzip'
            response.headers['X-Shape-Z'] = str(shape[0])
            response.headers['X-Shape-Y'] = str(shape[1])
            response.headers['X-Shape-X'] = str(shape[2])
            response.headers['X-Color-LUT'] = _json.dumps(color_lut)
            response.headers['X-Has-CTV'] = 'true' if ctv_array is not None else 'false'
            response.headers['X-Has-OAR'] = 'true' if oar_array is not None else 'false'
            response.headers['X-CTV-Size'] = str(ctv_offset)
            response.headers['X-OAR-Size'] = str(len(payload) - ctv_offset) if oar_array is not None else '0'
            response.headers['X-CTV-Bytes-Per-Voxel'] = '1'
            response.headers['X-OAR-Bytes-Per-Voxel'] = '2'

            # Send CTV label names from model (not hardcoded in frontend)
            ctv_label_map = (
                effective.ctv_label_map
                if effective is not None
                else agent.memory.retrieve("ctv_label_map", {})
            )
            logger.info(f"CTV label map from memory: {ctv_label_map}")
            if ctv_label_map:
                response.headers['X-CTV-Label-Map'] = _json.dumps({str(k): v for k, v in ctv_label_map.items()})
            else:
                tumor_type_used = str(agent.memory.retrieve("tumor_type_used", "") or "").strip()
                if tumor_type_used and tumor_type_used not in {"manual_label", "label_path", "unknown"}:
                    ctv_name = tumor_type_used.replace("_", " ").replace("nnunet ", "").replace("voco ", "")
                    response.headers['X-CTV-Label-Map'] = _json.dumps({"1": f"{ctv_name} tumor"})
                else:
                    response.headers['X-CTV-Label-Map'] = _json.dumps({"1": "CTV"})
            response.headers['X-CTV-Object-Map'] = _json.dumps({
                str(key): value for key, value in ctv_object_map.items()
            })

            # Also return organ metadata for data tree
            organ_names = (
                dict(effective.organ_names)
                if effective is not None
                else _server_support._oar_display_name_map(agent, oar_array)
            )
            organ_counts = (
                dict(effective.organ_counts)
                if effective is not None
                else agent.memory.retrieve("organ_counts", {}) or {}
            )
            # Precompute voxel counts in a single array pass (O(n)) rather
            # than np.sum(oar_array == lid) per label (O(n·k)).  With 57
            # TotalSegmentator labels and 8M voxels, the old per-label
            # scan piled up ~450 MB of temporary boolean allocations.
            _computed_counts = {}
            if oar_array is not None and not organ_counts:
                try:
                    flat = np.ravel(oar_array)
                    counts = np.bincount(flat)
                    for lid, cnt in enumerate(counts):
                        if cnt > 0:
                            _computed_counts[lid] = int(cnt)
                except Exception:
                    pass
            # Add nnUNet-derived OAR label names
            if ctv_source == "model" and ctv_full_memory is not None:
                nnunet_oar_names = {201: "artery", 202: "vein", 203: "pancreas"}
                for lid, name in nnunet_oar_names.items():
                    if lid not in organ_names:
                        organ_names[lid] = name
            organ_meta = {}
            if oar_array is not None:
                for lid in np.unique(oar_array):
                    lid_int = int(lid)
                    if lid_int > 0:
                        organ_meta[lid_int] = {
                            "name": organ_names.get(lid_int, f"OAR {lid_int}"),
                            "color": color_lut.get(lid_int, [200, 200, 200]),
                            "object_id": oar_object_map.get(lid_int, f"structure:oar:{lid_int}"),
                            "voxels": int(
                                organ_counts.get(lid_int)
                                or _computed_counts.get(lid_int, 0)
                            ),
                        }
            response.headers['X-Organ-Meta'] = _json.dumps(organ_meta)
            response.headers['X-OAR-Source'] = str(
                agent.memory.retrieve("oar_source", "") or ""
            )
            response.headers['X-CTV-Source'] = ctv_source
            response.headers['X-Structure-Version'] = str(
                int(agent.memory.retrieve("planning_version", 0) or 0)
            )

            return response
        except Exception as e:
            logger.error(f"Label volume export failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/overlay", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_overlay():
        """Get segmentation overlay for a specific slice."""
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending

        data = request.get_json() or {}
        axis_name = data.get("axis", "axial")
        slice_index = data.get("slice_index", 0)
        overlay_type = data.get("overlay_type", "oar")  # "ctv" or "oar"
        # Per-organ visibility and opacity from client
        visible_organs = data.get("visible_organs", None)  # list of label_ids to show
        organ_opacities = data.get("organ_opacities", None)  # {label_id: opacity 0-1}
        ctv_opacity = data.get("ctv_opacity", 0.7)
        oar_opacity = data.get("oar_opacity", 0.5)

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import base64
            import numpy as np
            from io import BytesIO
            from PIL import Image

            axis_map = agent.memory.retrieve("ct_axis_map") or {
                'axial': 0, 'sagittal': 2, 'coronal': 1,
            }
            axis = axis_map.get(axis_name, 0)

            # Get the segmentation mask
            ct_ref = agent.memory.retrieve("ct_image")
            ct_shape = np.asarray(ct_data).shape
            ctv_source = str(agent.memory.retrieve("ctv_source", "") or "").strip().lower()
            oar_source = str(agent.memory.retrieve("oar_source", "") or "").strip().lower()
            if overlay_type == "ctv":
                mask_data = _viewer_label_array(
                    agent, "ctv_array", "ctv_path", ctv_source, ct_ref, ct_shape,
                )
            else:
                mask_data = _viewer_label_array(
                    agent, "oar_array", "oar_path", oar_source, ct_ref, ct_shape,
                )

            if mask_data is None:
                img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
                buffered = BytesIO()
                img.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                return jsonify({"success": True, "data": f"data:image/png;base64,{img_str}", "has_mask": False})

            # Extract slice from mask: np.take with axis gives correct orientation
            # mask_data is (Z, Y, X), axis_map: axial=0(Z), sagittal=2(X), coronal=1(Y)
            # Z-flip applied so display matches raw DICOM ordering (slider 0 = feet).
            if axis_name == 'axial':
                src_idx = mask_data.shape[0] - 1 - slice_index
                mask_slice = np.take(mask_data, src_idx, axis=axis)
            elif axis_name == 'sagittal':
                z_arr = np.arange(mask_data.shape[0])[::-1]
                mask_slice = mask_data[z_arr, :, slice_index]
            elif axis_name == 'coronal':
                z_arr = np.arange(mask_data.shape[0])[::-1]
                mask_slice = mask_data[z_arr, slice_index, :]

            # For sagittal/coronal: resample Z-axis to match isotropic display
            # Client expects: sagittal -> width=Y, height=Z_resampled
            #                coronal -> width=X, height=Z_resampled
            # After np.take: sagittal=(Z, Y), coronal=(Z, X)
            # Image.fromarray(H, W) -> image width=W, height=H
            # So (Z_resampled, Y) -> width=Y, height=Z_resampled ✓
            if axis_name in ('sagittal', 'coronal'):
                spacing = agent.memory.retrieve("ct_spacing") or (0.6836, 0.6836, 5.0)
                spacing_x, spacing_y, spacing_z = float(spacing[0]), float(spacing[1]), float(spacing[2])
                if axis_name == 'sagittal':
                    resample_ratio = spacing_z / spacing_y
                else:  # coronal
                    resample_ratio = spacing_z / spacing_x
                if resample_ratio != 1.0:
                    new_z = int(mask_slice.shape[0] * resample_ratio)
                    indices = np.minimum((np.arange(new_z) / resample_ratio).astype(int), mask_slice.shape[0] - 1)
                    mask_slice = mask_slice[indices, :]
                # No transpose needed - (Z_resampled, Y/X) gives correct width/height

            # Create colored overlay with per-organ visibility/opacity
            overlay = np.zeros((*mask_slice.shape, 4), dtype=np.uint8)

            if overlay_type == "ctv":
                alpha = int(ctv_opacity * 255)
                unique_ctv_labels = np.unique(mask_slice[mask_slice > 0])
                # Always use per-label colors (consistent with data tree display)
                for label in unique_ctv_labels:
                    label_int = int(label)
                    color = _label_color(label_int)
                    overlay[mask_slice == label] = [*color, alpha]
            else:
                # OAR: per-organ colors with visibility/opacity filtering
                unique_labels = np.unique(mask_slice[mask_slice > 0])
                for label in unique_labels:
                    label_int = int(label)
                    # Check visibility - use label_int (actual mask value) for filtering
                    if visible_organs is not None and label_int not in visible_organs:
                        continue
                    # Get opacity for this organ
                    if organ_opacities and str(label_int) in organ_opacities:
                        alpha = int(organ_opacities[str(label_int)] * 255)
                    else:
                        alpha = int(oar_opacity * 255)
                    # Use golden-ratio HSV for visually distinct per-organ colors
                    color = _label_color(label_int)
                    overlay[mask_slice == label] = [*color, alpha]

            img = Image.fromarray(overlay, 'RGBA')

            buffered = BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()

            return jsonify({
                "success": True,
                "data": f"data:image/png;base64,{img_str}",
                "has_mask": True,
                "overlay_type": overlay_type,
            })
        except Exception as e:
            logger.error(f"Overlay generation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/organs", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_viewer_organs():
        """Return organ data (names and voxel counts) from OAR segmentation."""
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        if agent.memory.retrieve("structure_registry_initialized"):
            effective = build_effective_structures(agent.memory)
            organs = {}
            object_map = {}
            for item in effective.structures:
                if item["classification"] != "oar":
                    continue
                label = int(item["target_label"])
                object_id = str(item["object_id"])
                object_map[str(label)] = object_id
                organs[str(label)] = {
                    "name": str(item["name"]),
                    "voxel_count": int(item["voxel_count"]),
                    "object_id": object_id,
                }
            return jsonify({
                "success": True,
                "organs": organs,
                "organ_names": {
                    str(key): str(value)
                    for key, value in effective.organ_names.items()
                },
                "organ_counts": {
                    str(key): int(value)
                    for key, value in effective.organ_counts.items()
                },
                "object_map": object_map,
                "total_labels": len(organs),
                "oar_source": "classified",
                "oar_mask_provenance": str(
                    agent.memory.retrieve("oar_mask_provenance", "") or ""
                ),
                "structure_version": int(
                    agent.memory.retrieve("planning_version", 0) or 0
                ),
            })

        # Organ metadata is deliberately restored in the lightweight pass.
        # It is enough to paint the Data Tree immediately and must not be
        # blocked by a large NPY/CT decode.  A brand-new case has neither
        # metadata nor an OAR artifact and should return an empty success,
        # rather than making the browser poll forever for a resource that
        # does not exist.  Only an existing OAR artifact without metadata
        # remains pending until the full hydration pass reconstructs it.
        stored_names = agent.memory.retrieve("organ_names", {}) or {}
        stored_counts = agent.memory.retrieve("organ_counts", {}) or {}
        stored_oar_path = agent.memory.retrieve("oar_path")
        stored_oar_source = agent.memory.retrieve("oar_source", "")
        stored_oar_segmented = bool(agent.memory.retrieve("oar_segmented", False))
        has_oar_metadata = bool(stored_names or stored_counts)
        has_oar_artifact = bool(
            stored_oar_path or stored_oar_source or stored_oar_segmented
        )
        if not getattr(agent, "_workspace_data_ready", True) and not has_oar_metadata:
            if has_oar_artifact:
                pending = workspace_data_pending(agent)
                if pending is not None:
                    return pending
            else:
                return jsonify({
                    "success": True,
                    "organs": {},
                    "organ_names": {},
                    "organ_counts": {},
                    "total_labels": 0,
                    "oar_source": "",
                    "oar_mask_provenance": "",
                })

        # Metadata is the authoritative control-plane during lightweight
        # hydration.  The binary OAR array may still be decoding in the
        # background; asking the ontology helper for that missing array used
        # to replace valid persisted names/counts with an empty map.  Only
        # consult the array when metadata is genuinely absent, and use it to
        # fill missing labels rather than overwrite the saved ontology.
        def _label_map(value):
            if not isinstance(value, dict):
                return {}
            normalized = {}
            for raw_key, raw_value in value.items():
                try:
                    key = int(raw_key)
                except (TypeError, ValueError):
                    continue
                if key <= 0:
                    continue
                normalized[key] = raw_value
            return normalized

        organ_names = _label_map(stored_names)
        organ_counts = _label_map(stored_counts)
        uploaded_sources = {
            "uploaded_unknown",
            "manual_label",
            "uploaded",
            "manual_upload",
        }
        if str(stored_oar_source or "").strip().lower() in uploaded_sources:
            # The uploaded file is an opaque label map, not a TotalSegmentator
            # ontology. Rebuild stable numbered names from its label IDs even
            # when a stale checkpoint contains names from a previous model.
            upload_ids = sorted(set(organ_names) | set(organ_counts))
            organ_names = {
                int(label_id): f"OAR {ordinal}"
                for ordinal, label_id in enumerate(upload_ids, start=1)
            }
        oar_array = None
        if not organ_names and not organ_counts:
            oar_array = agent._get_label_array("oar_array")
            # Older durable cases may retain only the uploaded mask path. In
            # that case derive the small control-plane map from the path once,
            # aligned to the current CT grid, instead of waiting for a manual
            # 3D reconstruction to make the Data Tree visible.
            if oar_array is None and stored_oar_path:
                try:
                    import os
                    import SimpleITK as sitk
                    if os.path.exists(str(stored_oar_path)):
                        ct_path = agent.memory.retrieve("ct_path")
                        if ct_path and os.path.exists(str(ct_path)):
                            from tool_factory.segmentation_alignment import align_label_to_reference
                            aligned = align_label_to_reference(str(stored_oar_path), sitk.ReadImage(str(ct_path)), "LPI")
                            oar_array = sitk.GetArrayFromImage(aligned)
                            stored_oar_source = stored_oar_source or "uploaded_unknown"
                            agent.memory.store("oar_source", stored_oar_source)
                            agent.memory.store("oar_mask_provenance", "uploaded_unknown")
                except Exception as exc:
                    logger.warning("Unable to derive OAR metadata from stored path: %s", exc)
            organ_names = _label_map(
                _server_support._oar_display_name_map(agent, oar_array)
            )
            organ_counts = _label_map(agent.memory.retrieve("organ_counts", {}))

        if oar_array is not None:
            import numpy as np
            unique_labels = np.unique(oar_array)
            next_ordinal = len(organ_names) + 1
            for label in unique_labels:
                label_int = int(label)
                if label_int <= 0:
                    continue
                organ_counts.setdefault(label_int, int(np.sum(oar_array == label)))
                organ_names.setdefault(label_int, f"OAR {next_ordinal}")
                next_ordinal += 1
            # Cache only the completed metadata.  This is a small control
            # plane write and avoids repeating label scans on every refresh.
            if organ_names:
                agent.memory.store("organ_names", organ_names)
            if organ_counts:
                agent.memory.store("organ_counts", organ_counts)

        organs = {}
        for label_id, name in organ_names.items():
            label_int = int(label_id) if isinstance(label_id, str) else label_id
            organs[str(label_int)] = {
                "name": name,
                "voxel_count": organ_counts.get(label_int, organ_counts.get(str(label_int), 0))
            }

        # Return the normalized maps as first-class fields as well as the
        # legacy ``organs`` object.  A large label-volume response can arrive
        # before optional headers are available; the browser can therefore
        # rebuild the same numbered Data Tree nodes from these small maps.
        normalized_names = {str(k): str(v) for k, v in (organ_names or {}).items()}
        normalized_counts = {
            str(k): int(v or 0) for k, v in (organ_counts or {}).items()
        }

        return jsonify({
            "success": True,
            "organs": organs,
            "organ_names": normalized_names,
            "organ_counts": normalized_counts,
            "total_labels": len(organs),
            # The client uses provenance to decide whether an incoming mask
            # may inherit previous Data Tree ontology/category state.
            "oar_source": str(agent.memory.retrieve("oar_source", "") or ""),
            "oar_mask_provenance": str(
                agent.memory.retrieve("oar_mask_provenance", "") or ""
            ),
        })

    @app.route("/api/viewer/threshold", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_threshold():
        """Apply threshold segmentation and return mask."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        lower = data.get("lower", -1000)
        upper = data.get("upper", 1000)
        axis = data.get("axis", "axial")
        slice_index = data.get("slice_index", 0)

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import numpy as np

            mask = (ct_data >= lower) & (ct_data <= upper)
            axis_map = agent.memory.retrieve("ct_axis_map") or {
                'axial': 0, 'sagittal': 2, 'coronal': 1,
            }
            mask_slice = np.take(mask, slice_index, axis=axis_map.get(axis, 0))

            # Count voxels
            total_voxels = int(mask.sum())
            spacing = agent.memory.retrieve("ct_spacing") or (1, 1, 1)
            volume_mm3 = total_voxels * float(np.prod(spacing))

            return jsonify({
                "success": True,
                "mask": mask_slice.tolist(),
                "total_voxels": total_voxels,
                "volume_mm3": volume_mm3,
            })
        except Exception as e:
            logger.error(f"Viewer threshold failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/hu", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_hu():
        """Get HU value at a specific voxel."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        x = data.get("x", 0)
        y = data.get("y", 0)
        z = data.get("z", 0)

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import numpy as np
            shape = ct_data.shape
            # ct_data shape is (Z, Y, X)
            if 0 <= x < shape[2] and 0 <= y < shape[1] and 0 <= z < shape[0]:
                hu = float(ct_data[z, y, x])
                return jsonify({"success": True, "hu": hu, "coords": [x, y, z]})
            else:
                return jsonify({"error": "Coordinates out of bounds"}), 400
        except Exception as e:
            logger.error(f"Viewer HU failed: {e}")
            return jsonify({"error": str(e)}), 500

    def _laplacian_smooth(vertices, faces, iterations=3, factor=0.3):
        """Lightweight Laplacian mesh smoothing using numpy.
        Moves each vertex toward the centroid of its neighbors."""
        import numpy as np
        from collections import defaultdict

        # Build vertex adjacency from faces
        adj = defaultdict(set)
        for f in faces:
            adj[f[0]].add(f[1]); adj[f[0]].add(f[2])
            adj[f[1]].add(f[0]); adj[f[1]].add(f[2])
            adj[f[2]].add(f[0]); adj[f[2]].add(f[1])

        verts = vertices.copy().astype(np.float64)
        for _ in range(iterations):
            new_verts = verts.copy()
            for vi, neighbors in adj.items():
                if not neighbors:
                    continue
                centroid = verts[list(neighbors)].mean(axis=0)
                new_verts[vi] += factor * (centroid - verts[vi])
            verts = new_verts
        return verts

    @app.route("/api/viewer/3d", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_3d():
        """Generate 3D mesh from CTV or OAR mask."""
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending

        data = request.get_json() or {}
        source = data.get("source", "ctv")  # "ctv" or "oar"
        label_id = data.get("label_id")  # specific organ label for OAR

        try:
            import numpy as np
            from skimage import measure
            from scipy.ndimage import binary_closing, binary_fill_holes, binary_dilation

            # Get mask data
            if source == "ctv":
                mask_data = agent._get_label_array("ctv_array")
            else:
                mask_data = agent._get_label_array("oar_array")

            if mask_data is None:
                return jsonify({"error": f"No {source} mask data available"}), 400

            # Extract specific label if provided
            if label_id is not None:
                mask = (mask_data == int(label_id)).astype(np.uint8)
            else:
                mask = (mask_data > 0).astype(np.uint8)

            if mask.sum() == 0:
                return jsonify({"error": "Empty mask"}), 400

            # Adaptive preprocessing based on mask density
            density = mask.sum() / (mask.shape[0] * mask.shape[1] * mask.shape[2])
            if density < 0.001:
                struct = np.ones((3, 3, 3), dtype=np.uint8)
                mask = binary_dilation(mask, structure=struct, iterations=2)
                mask = binary_closing(mask, structure=struct, iterations=3)
                mask = binary_fill_holes(mask).astype(np.uint8)
            elif density < 0.01:
                struct = np.ones((3, 3, 3), dtype=np.uint8)
                mask = binary_dilation(mask, structure=struct, iterations=1)
                mask = binary_closing(mask, structure=struct, iterations=2)
                mask = binary_fill_holes(mask).astype(np.uint8)
            else:
                mask = binary_closing(mask, iterations=2).astype(np.uint8)
                mask = binary_fill_holes(mask).astype(np.uint8)

            # Use distance transform for smooth surface
            from scipy.ndimage import distance_transform_edt
            dist_out = distance_transform_edt(1 - mask)
            dist_in = distance_transform_edt(mask)
            smooth_field = dist_out - dist_in

            spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
            spacing_xyz = tuple(float(s) for s in spacing[:3])
            spacing_zyx = spacing_xyz[::-1]

            vertices, faces, normals, values = measure.marching_cubes(
                smooth_field, level=0.0, spacing=spacing_zyx, allow_degenerate=False
            )

            # Smooth mesh
            vertices = _laplacian_smooth(vertices, faces, iterations=5, factor=0.4)

            # Remove degenerate faces
            v0 = vertices[faces[:, 0]]
            v1 = vertices[faces[:, 1]]
            v2 = vertices[faces[:, 2]]
            face_areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
            faces = faces[face_areas > 1e-10]

            return jsonify({
                "success": True,
                "vertices": vertices.tolist(),
                "faces": faces.tolist(),
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "source": source,
                "label_id": label_id,
            })
        except Exception as e:
            logger.error(f"Viewer 3D failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/3d_mask", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_3d_mask():
        """Generate 3D mesh from a specific organ mask label."""
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending

        data = request.get_json() or {}
        label_id = data.get("label_id")
        source = data.get("source", "oar")  # "oar" or "ctv"

        if label_id is None:
            return jsonify({"error": "label_id required"}), 400

        try:
            import hashlib
            import numpy as np
            from skimage import measure
            from scipy.ndimage import binary_closing, binary_fill_holes, binary_dilation, gaussian_filter

            if source == "ctv":
                mask_data = agent._get_label_array("ctv_array")
            else:
                mask_data = agent._get_label_array("oar_array")

            if mask_data is None:
                return jsonify({"error": f"No {source} mask data available"}), 400

            # Extract binary mask for this label
            label_id = int(label_id)
            label_faithful = _requires_label_faithful_mesh(agent, source, label_id)
            try:
                mask_shape_key = tuple(int(x) for x in getattr(mask_data, "shape", ()))
            except Exception:
                mask_shape_key = ()
            smoothing_key = data.get("smoothing", 1)
            binary_mask = (mask_data == label_id).astype(np.uint8)

            total_voxels = int(binary_mask.sum())
            if total_voxels == 0:
                return jsonify({"error": f"Label {label_id} not found in mask"}), 400
            mask_digest = hashlib.blake2b(binary_mask.tobytes(), digest_size=8).hexdigest()
            cache_key = (
                source, label_id, str(smoothing_key), label_faithful,
                mask_shape_key, total_voxels, mask_digest,
            )
            with _MESH_CACHE_LOCK:
                cached = _MESH_CACHE.get(cache_key)
            if cached is not None:
                cached_payload = dict(cached)
                cached_payload["cached"] = True
                return jsonify(cached_payload)

            if not label_faithful:
                # Adaptive preprocessing is useful for presentation meshes of
                # ordinary anatomy, but it deliberately does not apply to a
                # hard obstacle; changing that surface would contradict the
                # physical mask used by candidate trajectory filtering.
                mask_volume = binary_mask.shape[0] * binary_mask.shape[1] * binary_mask.shape[2]
                density = total_voxels / mask_volume

                # More aggressive morphological ops for sparse/fragmented masks
                if density < 0.001:
                    # Very sparse mask (e.g., small vessel): heavy closing + dilation
                    struct = np.ones((3, 3, 3), dtype=np.uint8)
                    binary_mask = binary_dilation(binary_mask, structure=struct, iterations=2)
                    binary_mask = binary_closing(binary_mask, structure=struct, iterations=3)
                    binary_mask = binary_fill_holes(binary_mask).astype(np.uint8)
                    binary_mask = binary_dilation(binary_mask, structure=struct, iterations=1)
                elif density < 0.01:
                    # Sparse mask (e.g., bile duct, small organ): moderate closing
                    struct = np.ones((3, 3, 3), dtype=np.uint8)
                    binary_mask = binary_dilation(binary_mask, structure=struct, iterations=1)
                    binary_mask = binary_closing(binary_mask, structure=struct, iterations=2)
                    binary_mask = binary_fill_holes(binary_mask).astype(np.uint8)
                else:
                    # Normal density mask: standard cleanup
                    binary_mask = binary_closing(binary_mask, iterations=2).astype(np.uint8)
                    binary_mask = binary_fill_holes(binary_mask).astype(np.uint8)

            # Gaussian smoothing on distance transform for smoother surface
            # This creates a continuous scalar field from the binary mask
            from scipy.ndimage import distance_transform_edt
            dist_out = distance_transform_edt(1 - binary_mask)
            dist_in = distance_transform_edt(binary_mask)
            smooth_field = dist_out - dist_in  # Positive inside, negative outside

            # Get spacing, origin, direction from CT data
            spacing = agent.memory.retrieve("ct_spacing") or (1.0, 1.0, 1.0)
            origin = agent.memory.retrieve("ct_origin") or (0.0, 0.0, 0.0)
            direction = agent.memory.retrieve("ct_direction") or (1, 0, 0, 0, 1, 0, 0, 0, 1)
            # SimpleITK spacing is (X, Y, Z), numpy array is (Z, Y, X)
            # marching_cubes expects spacing in array axis order (sz, sy, sx)
            if isinstance(spacing, (list, tuple)) and len(spacing) >= 3:
                spacing_zyx = tuple(float(s) for s in spacing[:3])[::-1]
            else:
                spacing_zyx = (1.0, 1.0, 1.0)

            # Generate mesh from the smooth distance field (level=0 is the surface)
            vertices, faces, normals, values = measure.marching_cubes(
                smooth_field, level=0.0, spacing=spacing_zyx, allow_degenerate=False
            )

            # Mesh smoothing also moves a boundary.  Preserve the voxel-faithful
            # hard-obstacle surface so it remains consistent with trajectory
            # validation; keep the polished appearance for ordinary anatomy.
            if not label_faithful:
                vertices = _laplacian_smooth(vertices, faces, iterations=5, factor=0.4)

            # Remove degenerate faces (faces with zero area or duplicate vertices)
            v0 = vertices[faces[:, 0]]
            v1 = vertices[faces[:, 1]]
            v2 = vertices[faces[:, 2]]
            face_areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
            valid_faces = face_areas > 1e-10
            faces = faces[valid_faces]

            # Transform vertices from array coordinates to world coordinates
            origin_xyz = np.array(origin[:3], dtype=np.float64)
            direction_matrix = np.array(direction[:9], dtype=np.float64).reshape(3, 3)
            # vertices are in (z, y, x) order with spacing already applied
            # Convert to (x, y, z) order for world coordinate transform
            vertices_xyz = vertices[:, ::-1]  # Reverse to (x, y, z)
            # Apply direction and origin: world = origin + direction @ point
            vertices_world = (direction_matrix @ vertices_xyz.T).T + origin_xyz
            vertices = vertices_world

            # Decimation: use Open3D if available, otherwise skip (no stride-based fallback)
            if len(faces) > 50000:
                target = min(50000, len(faces))
                try:
                    import open3d as o3d
                    mesh_o3d = o3d.geometry.TriangleMesh()
                    mesh_o3d.vertices = o3d.utility.Vector3dVector(vertices)
                    mesh_o3d.triangles = o3d.utility.Vector3iVector(faces)
                    mesh_o3d = mesh_o3d.simplify_quadric_decimation(target_number_of_triangles=target)
                    vertices = np.asarray(mesh_o3d.vertices)
                    faces = np.asarray(mesh_o3d.triangles)
                except (ImportError, Exception):
                    # No decimation - keep full mesh (stride-based creates holes)
                    pass

            payload = {
                "success": True,
                "vertices": vertices.tolist(),
                "faces": faces.tolist(),
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "label_id": label_id,
                "source": source,
                "geometry_mode": "label_faithful" if label_faithful else "presentation_smoothed",
                "cached": False,
            }
            with _MESH_CACHE_LOCK:
                _MESH_CACHE[cache_key] = payload
                _MESH_CACHE_ORDER.append(cache_key)
                while len(_MESH_CACHE_ORDER) > _MESH_CACHE_MAX_ITEMS:
                    old_key = _MESH_CACHE_ORDER.popleft()
                    _MESH_CACHE.pop(old_key, None)

            return jsonify(payload)
        except Exception as e:
            logger.error(f"3D mask reconstruction failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/3d_skin", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_3d_skin():
        """Generate CT skin mesh using isosurface (marching cubes at skin threshold)."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        threshold = data.get("threshold", -300)  # Default: skin surface at -300 HU

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT loaded"}), 400

        try:
            import numpy as np
            from skimage import measure

            spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
            origin = agent.memory.retrieve("ct_origin") or (0.0, 0.0, 0.0)
            direction = agent.memory.retrieve("ct_direction") or (1, 0, 0, 0, 1, 0, 0, 0, 1)
            # SimpleITK spacing is (X, Y, Z), numpy array is (Z, Y, X)
            # marching_cubes expects spacing in array axis order (sz, sy, sx)
            spacing_xyz = tuple(float(s) for s in spacing[:3])
            spacing_zyx = spacing_xyz[::-1]

            # Subsample for faster mesh generation if volume is large
            if ct_data.shape[0] > 64:
                step = max(1, ct_data.shape[0] // 64)
                ct_sub = ct_data[::step, ::step, ::step]
                sub_spacing = (spacing_zyx[0] * step, spacing_zyx[1] * step, spacing_zyx[2] * step)
            else:
                ct_sub = ct_data
                sub_spacing = spacing_zyx

            data_min, data_max = float(ct_sub.min()), float(ct_sub.max())
            level = float(threshold)
            if level <= data_min or level >= data_max:
                level = (data_min + data_max) / 2.0

            vertices, faces, _, _ = measure.marching_cubes(ct_sub, level=level, spacing=sub_spacing, allow_degenerate=False)

            # Smooth jagged marching-cubes surface
            vertices = _laplacian_smooth(vertices, faces, iterations=2, factor=0.2)

            # Transform vertices from array coordinates to world coordinates
            origin_xyz = np.array(origin[:3], dtype=np.float64)
            direction_matrix = np.array(direction[:9], dtype=np.float64).reshape(3, 3)
            vertices_xyz = vertices[:, ::-1]  # Reverse to (x, y, z)
            vertices_world = (direction_matrix @ vertices_xyz.T).T + origin_xyz
            vertices = vertices_world

            # Decimate if too many faces
            if len(faces) > 100000:
                stride = max(1, len(faces) // 100000)
                faces = faces[::stride]

            return jsonify({
                "success": True,
                "vertices": vertices.tolist(),
                "faces": faces.tolist(),
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "threshold": threshold,
            })
        except Exception as e:
            logger.error(f"CT skin reconstruction failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/seeds_3d", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_planning_seeds_3d():
        """Get seed positions and directions for 3D visualization.

        ``core.optimal_plan()`` converts every seed position and direction to
        patient world coordinates before returning.  This route must preserve
        those coordinates exactly; only the optional 2D voxel index is derived
        from the displayed CT image.
        """
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        try:
            import numpy as np

            seed_plan = agent.memory.retrieve("seed_plan")
            seed_plan_serialized = agent.memory.retrieve("seed_plan_serialized") or []
            plan_config = agent.memory.retrieve("plan_config") or getattr(agent, "config", {}) or {}
            seed_info = plan_config.get("seed_info") if isinstance(plan_config, dict) else {}
            if not isinstance(seed_info, dict):
                seed_info = {}
            def _positive_geometry_value(name, default):
                try:
                    value = float(seed_info.get(name, default) or default)
                    return value if np.isfinite(value) and value > 0 else default
                except (TypeError, ValueError):
                    return default
            seed_geometry = {
                # Keep the fallback aligned with config/default_params.json.
                "length": _positive_geometry_value("length", 4.5),
                "radius": _positive_geometry_value("radius", 0.4),
            }
            verified_needle_geometry = agent.memory.retrieve("verified_needle_geometry") or {}
            manual_needles = agent.memory.retrieve("manual_needles") or []
            has_manual_geometry = bool(manual_needles)
            if seed_plan is None and not seed_plan_serialized:
                return jsonify({
                    "success": True,
                    "seeds": [],
                    "needles": [],
                    "seed_geometry": seed_geometry,
                    "message": "No seed plan available",
                })

            ct_image = agent.memory.retrieve("ct_image")

            # Revalidate the exact world-coordinate line before exposing it to
            # the renderer. This is intentionally independent of the cached
            # ``verified_needle_geometry`` snapshot: a Data Tree category can
            # change after planning, and a stale snapshot must never make an
            # unsafe needle visible. The planning pipeline uses the same
            # physical-coordinate validator, so this is a display-time
            # defense in depth rather than a second coordinate convention.
            safety_ctv = None
            safety_oar = None
            obstacle_labels = set()
            world_validator = None
            try:
                from tool_factory.seed_plan.planning_pipeline import (
                    _merge_embedded_hard_obstacles,
                    _resolve_data_tree_obstacle_labels,
                    _world_segment_hits_obstacle,
                )

                safety_ctv = agent._get_label_array("ctv_full_labels")
                if safety_ctv is None:
                    safety_ctv = agent._get_label_array("ctv_array")
                safety_oar = agent._get_label_array("oar_array")
                safety_oar, embedded_labels = _merge_embedded_hard_obstacles(safety_oar, agent)
                obstacle_labels, _ = _resolve_data_tree_obstacle_labels(agent)
                obstacle_labels.update(embedded_labels)
                world_validator = _world_segment_hits_obstacle
            except Exception:
                # A missing optional safety artifact must fail closed below;
                # never silently fall back to rendering an unchecked line.
                logger.exception("[seeds_3d] Unable to prepare current obstacle validator")

            def _needle_is_safe(points):
                if world_validator is None:
                    return False
                return not world_validator(
                    points, ct_image, safety_ctv, safety_oar, obstacle_labels
                )

            def _world_to_ct_voxel_index(world_pos):
                """Return CT voxel index in numpy order [z, y, x]."""
                if ct_image is None:
                    return None
                try:
                    idx_xyz = ct_image.TransformPhysicalPointToIndex(tuple(float(v) for v in world_pos[:3]))
                    return [int(idx_xyz[2]), int(idx_xyz[1]), int(idx_xyz[0])]
                except Exception as e:
                    logger.debug(f"[seeds_3d] world_to_ct_voxel_index failed: {e}")
                    return None

            seeds = []
            needles = []

            plan_source = seed_plan if seed_plan is not None else seed_plan_serialized
            for i, entry in enumerate(plan_source):
                explicit_needle_points = None
                trajectory_id = i
                needle_id = f"needle_{i}"
                if isinstance(entry, dict):
                    seed_list = entry.get("seeds") or []
                    trajectory_id = entry.get("trajectory_id", entry.get("id", i))
                    needle_id = str(entry.get("needle_id") or needle_id)
                    trajectory = entry.get("trajectory")
                    if isinstance(trajectory, dict):
                        candidate_points = trajectory.get("points")
                        if isinstance(candidate_points, list) and len(candidate_points) >= 2:
                            try:
                                points = [np.asarray(p, dtype=np.float64).flatten()[:3] for p in candidate_points[:2]]
                                if all(p.size == 3 and np.all(np.isfinite(p)) for p in points):
                                    explicit_needle_points = [p.tolist() for p in points]
                            except Exception:
                                explicit_needle_points = None
                elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    seed_list = entry[1] if len(entry) > 1 else []
                else:
                    continue

                needle_seeds = []
                for j, seed in enumerate(seed_list):
                    if isinstance(seed, dict):
                        seed_pos = seed.get("position") or seed.get("pos")
                        seed_dir = seed.get("direction") or seed.get("dir")
                    elif isinstance(seed, (list, tuple)) and len(seed) >= 2:
                        seed_pos = seed[0]
                        seed_dir = seed[1]
                    else:
                        continue
                    if seed_pos is None:
                        continue

                    # CRITICAL: optimal_plan() in plans/core.py ALREADY converts
                    # seeds from voxel to world coordinates using position_transform().
                    # The seed[0] and seed[1] are therefore ALREADY in world coords.
                    # Do NOT apply _voxel_to_world again — that would double-transform
                    # and place seeds far from the correct position.
                    pos_world = np.array(seed_pos, dtype=np.float64).flatten()[:3]
                    direc_world = np.array(seed_dir if seed_dir is not None else [0.0, 0.0, 1.0], dtype=np.float64).flatten()[:3]

                    if i == 0 and j == 0:
                        logger.info(f"[seeds_3d] first seed (already world): pos={pos_world.tolist()}, dir={direc_world.tolist()}")

                    seed_data = {
                        "id": str(seed.get("id") or f"seed_{i}_{j}") if isinstance(seed, dict) else f"seed_{i}_{j}",
                        "position": pos_world.tolist(),
                        "voxel_index": _world_to_ct_voxel_index(pos_world),
                        "direction": direc_world.tolist(),
                        "trajectory_id": seed.get("trajectory_id", trajectory_id) if isinstance(seed, dict) else trajectory_id,
                        "seed_index": j,
                    }
                    seeds.append(seed_data)
                    needle_seeds.append(pos_world)

                # A manual update stores explicit world-coordinate endpoint
                # pairs. Preserve them as the authoritative geometry; falling
                # back to seed-derived geometry is only for legacy automatic
                # plans that do not carry explicit needle points.
                # Explicit trajectory points are only authoritative for the
                # manually edited plan, whose endpoint update path performs
                # its own obstacle validation. Automatic plans must always
                # use the pipeline's verified original-grid geometry; an
                # unverified serialized trajectory must never bypass that
                # safety gate.
                if explicit_needle_points is not None and has_manual_geometry:
                    explicit_points = [
                        np.asarray(point, dtype=np.float64).reshape(-1)[:3]
                        for point in explicit_needle_points
                    ]
                    if len(explicit_points) != 2 or not _needle_is_safe(explicit_points):
                        logger.error(
                            "[seeds_3d] Withholding manual needle_%s because current Data Tree obstacles reject its geometry",
                            i,
                        )
                        continue
                    needles.append({
                        "id": needle_id,
                        "points": explicit_needle_points,
                        "trajectory_id": trajectory_id,
                    })
                    continue

                # Automatic needles must come from the planning pipeline's
                # original-grid safety validation. Reconstructing a new 150 mm
                # line here would reintroduce a geometry that was never checked
                # against the Data Tree hard-obstacle policy.
                validated_points = None
                if isinstance(verified_needle_geometry, dict):
                    validated_points = verified_needle_geometry.get(str(i))
                    if validated_points is None:
                        validated_points = verified_needle_geometry.get(i)
                try:
                    points = [np.asarray(point, dtype=np.float64).reshape(-1)[:3] for point in validated_points]
                    if len(points) != 2 or not all(point.size == 3 and np.all(np.isfinite(point)) for point in points):
                        raise ValueError("invalid validated needle points")
                    if not _needle_is_safe(points):
                        logger.error(
                            "[seeds_3d] Withholding needle_%s because current Data Tree obstacles reject its geometry",
                            i,
                        )
                        continue
                    needles.append({
                        "id": f"needle_{i}",
                        "points": [point.tolist() for point in points],
                        "trajectory_id": trajectory_id,
                    })
                except Exception:
                    logger.warning(
                        "[seeds_3d] Withholding automatic needle_%s because no validated geometry is available; re-run planning.",
                        i,
                    )

            logger.info(f"[seeds_3d] returning {len(seeds)} seeds, {len(needles)} needles")
            return jsonify({
                "success": True,
                "seeds": seeds,
                "needles": needles,
                "seed_geometry": seed_geometry,
                "total_seeds": len(seeds),
                "total_needles": len(needles),
                "planning_id": agent.memory.retrieve("manual_planning_id"),
                "planning_version": int(agent.memory.retrieve("manual_plan_version") or 0),
                "artifact_status": agent.memory.retrieve("manual_artifact_status") or {},
            })
        except Exception as e:
            logger.error(f"Seed 3D data failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500
