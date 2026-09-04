"""Viewer and 3D visualization routes for the BrachyBot web API."""

import gzip
import hashlib
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
from web.viewer_cache import (
    load_viewer_cache,
    schedule_viewer_cache_write,
    viewer_cache_key,
)
from utils.ct_volume import normalize_ct_image
from agent_runtime.core import PlanningPhase

try:
    from web.server_support import rate_limit, require_api_key
    from web import server_support as _server_support
except ImportError:  # pragma: no cover - supports `python web/server.py`.
    from server_support import rate_limit, require_api_key  # type: ignore
    import server_support as _server_support  # type: ignore

logger = logging.getLogger(__name__)


def _viewer_json_response(payload, status=200):
    """Return a private JSON response, gzip-compressed when supported.

    Meshes contain large repetitive numeric lists. Compressing the response
    reduces transfer time without changing the JSON contract; browsers
    transparently decode ``Content-Encoding: gzip`` before ``response.json()``.
    Small/error responses stay uncompressed.
    """
    response = jsonify(payload)
    raw = response.get_data()
    if len(raw) >= 1024 and "gzip" in request.headers.get("Accept-Encoding", "").lower():
        response.set_data(gzip.compress(raw, compresslevel=1))
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Vary"] = "Accept-Encoding"
    return (response, status) if status != 200 else response


def _viewer_geometry_signature(agent, shape):
    """Build a stable CT geometry signature for derived mesh cache keys."""
    def values(value, length):
        try:
            return [float(item) for item in list(value)[:length]]
        except (TypeError, ValueError):
            return []

    return {
        "shape_zyx": [int(item) for item in tuple(shape or ())],
        "spacing_xyz": values(agent.memory.retrieve("ct_spacing"), 3),
        "origin_xyz": values(agent.memory.retrieve("ct_origin"), 3),
        "direction": values(agent.memory.retrieve("ct_direction"), 9),
    }

_MESH_CACHE = _server_support._MESH_CACHE
_MESH_CACHE_LOCK = _server_support._MESH_CACHE_LOCK
_MESH_CACHE_MAX_ITEMS = _server_support._MESH_CACHE_MAX_ITEMS
_MESH_CACHE_ORDER = _server_support._MESH_CACHE_ORDER
_label_color = _server_support._label_color
_ctv_label_color = _server_support._ctv_label_color
_validate_path = _server_support._validate_path

_UPLOADED_LABEL_SOURCES = {
    "manual_label",
    "uploaded_unknown",
    "uploaded",
    "manual_upload",
}

# Marching cubes needs a background sample on every side of a volume to close
# a surface that touches the CT acquisition boundary. Without this one-voxel
# guard, a mask that reaches z=0/z=max produces an open, volume-sized cut face;
# in the WebGL viewer that looks like a screen-aligned inner rectangle and can
# also make the surface bounds used for camera fitting incomplete. The padding
# is only for surface extraction. The planning mask and all physical
# coordinates remain unchanged.
_MESH_BOUNDARY_PADDING_VOXELS = 1

# OAR/CTV surfaces are derived display products.  Running two full-volume
# distance transforms for every label is needlessly expensive for a 48 x 512
# x 512 CT (and becomes catastrophic when 50+ structures are requested).
# Crop each binary label to a padded bounding box before extraction.  The
# returned voxel origin is added back before the patient-world transform, so
# this is an exact display-domain optimisation rather than a clinical-data
# change.  The margin covers the largest presentation cleanup operation below.
_MESH_CROP_MARGIN_VOXELS = 8


def _pad_surface_volume(volume, fill_value=0):
    """Pad a 3-D scalar/label volume for a closed marching-cubes surface.

    Return the padded array and the number of padded voxels in array order
    (z, y, x). The caller subtracts ``padding * spacing`` from marching-cubes
    vertices before converting them to patient world coordinates.
    """
    array = np.asarray(volume)
    if array.ndim != 3 or _MESH_BOUNDARY_PADDING_VOXELS <= 0:
        return array, np.zeros(3, dtype=np.float64)
    pad = int(_MESH_BOUNDARY_PADDING_VOXELS)
    padded = np.pad(
        array,
        ((pad, pad), (pad, pad), (pad, pad)),
        mode="constant",
        constant_values=fill_value,
    )
    return padded, np.full(3, float(pad), dtype=np.float64)


def _signed_surface_field(binary_volume):
    """Build a validated signed-distance field for level-zero extraction.

    ``skimage.measure.marching_cubes`` raises a generic data-range exception
    when preprocessing has erased a thin label. Validate that contract here so
    every mask route either receives a real inside/outside boundary or returns
    a precise error instead of failing midway through a batch reconstruction.
    The sign is negative inside and positive outside.
    """
    from scipy.ndimage import distance_transform_edt

    binary = (np.asarray(binary_volume) > 0).astype(np.uint8, copy=False)
    if binary.ndim != 3:
        raise ValueError("Surface mask must be a 3-D binary volume.")
    if not np.any(binary):
        raise ValueError("Surface mask became empty during preprocessing.")
    padded, surface_padding_zyx = _pad_surface_volume(binary)
    dist_out = distance_transform_edt(1 - padded)
    dist_in = distance_transform_edt(padded)
    signed_field = dist_out - dist_in
    field_min = float(np.min(signed_field))
    field_max = float(np.max(signed_field))
    if not field_min < 0.0 < field_max:
        raise ValueError(
            "Surface mask does not contain a valid inside/outside boundary "
            f"(signed range {field_min:.6g} to {field_max:.6g})."
        )
    return signed_field, surface_padding_zyx


def _crop_binary_surface_volume(binary_volume, margin=None):
    """Crop a non-empty binary volume and return ``(crop, origin_zyx)``.

    ``origin_zyx`` is the crop's offset in the original NumPy volume.  A
    generous fixed margin keeps the subsequent sparse-mask morphology away
    from the crop edge.  Empty/invalid inputs are returned unchanged so the
    caller retains the existing precise validation/error path.
    """
    array = np.asarray(binary_volume)
    if array.ndim != 3 or not np.any(array):
        return array, np.zeros(3, dtype=np.int64)
    try:
        # Reduce each axis to a tiny presence vector instead of materialising
        # three coordinate arrays for every occupied voxel. The latter can
        # consume hundreds of MB for a dense 512 x 512 CT label and is
        # especially harmful while several bounded mesh workers run together.
        occupied_by_axis = (
            np.any(array, axis=(1, 2)),
            np.any(array, axis=(0, 2)),
            np.any(array, axis=(0, 1)),
        )
        occupied_indices = [np.flatnonzero(values) for values in occupied_by_axis]
        if any(len(values) == 0 for values in occupied_indices):
            return array, np.zeros(3, dtype=np.int64)
        lower = np.array([int(values[0]) for values in occupied_indices], dtype=np.int64)
        upper = np.array([int(values[-1]) + 1 for values in occupied_indices], dtype=np.int64)
    except (AttributeError, TypeError, ValueError):
        return array, np.zeros(3, dtype=np.int64)
    pad = max(0, int(_MESH_CROP_MARGIN_VOXELS if margin is None else margin))
    shape = np.asarray(array.shape, dtype=np.int64)
    lower = np.maximum(0, lower - pad)
    upper = np.minimum(shape, upper + pad)
    cropped = np.ascontiguousarray(array[
        lower[0]:upper[0], lower[1]:upper[1], lower[2]:upper[2],
    ])
    return cropped, lower


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


def _clamp_viewer_slice_index(value, axis_name, shape, axis_map=None):
    """Normalize a viewer slice request to the currently loaded volume.

    Viewer requests can outlive a CT change: a slider event for the previous
    case may arrive after the new, smaller volume has already been installed.
    Treat that as a stale presentation request and clamp it to the new volume
    instead of letting ``numpy.take`` raise an IndexError.  The returned axis
    is also normalized so malformed axis names cannot select a non-existent
    dimension.
    """
    dimensions = tuple(int(size) for size in (shape or ()) if size is not None)
    mapping = axis_map or {"axial": 0, "sagittal": 2, "coronal": 1}
    try:
        axis = int(mapping.get(str(axis_name), 0))
    except (TypeError, ValueError):
        axis = 0
    if axis < 0 or axis >= len(dimensions):
        axis = 0
    maximum = max(0, dimensions[axis] - 1) if dimensions else 0
    try:
        requested = int(float(value))
    except (TypeError, ValueError, OverflowError):
        requested = 0
    return max(0, min(requested, maximum)), axis


def _viewer_mpr_z_resample_indices(source_depth, spacing, axis_name):
    """Return the nearest-neighbor Z map shared by all PNG MPR fallbacks.

    The browser volume renderer uses ``round(Z * spacing_z / spacing_in_plane)``
    output rows and maps each output row back with ``floor(row / ratio)``.
    Keeping that calculation here prevents the CT, label, and dose fallback
    endpoints from drifting apart for anisotropic studies.
    """
    if axis_name not in {"sagittal", "coronal"}:
        return None
    try:
        depth = int(source_depth)
    except (TypeError, ValueError):
        return None
    if depth < 1:
        return None
    try:
        values = list(spacing or ())
        spacing_x = float(values[0]) or 0.68
        spacing_y = float(values[1]) or 0.68
        spacing_z = float(values[2]) or 5.0
    except (TypeError, ValueError, IndexError):
        spacing_x, spacing_y, spacing_z = 0.68, 0.68, 5.0
    denominator = spacing_y if axis_name == "sagittal" else spacing_x
    try:
        ratio = max(spacing_z / denominator, 0.01)
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = 1.0
    if abs(ratio - 1.0) <= 1e-12:
        return None
    target_depth = max(1, int(np.floor(depth * ratio + 0.5)))
    return np.minimum(
        (np.arange(target_depth) / ratio).astype(np.intp),
        depth - 1,
    )


def _requires_label_faithful_mesh(agent, source: str, label_id: int) -> bool:
    """Return whether a mesh must preserve the exact planning-mask boundary.

    CTV meshes are compared directly with dose isosurfaces and DVH coverage,
    while non-traversable structures are part of the planning safety contract.
    Presentation-oriented dilation, closing, hole filling, and mesh smoothing
    move those visible boundaries away from the masks used by the calculations.
    Render these labels from their unchanged voxel masks so the 3D viewer does
    not contradict dose coverage or trajectory validation.
    """
    if str(source or "").strip().lower() == "ctv":
        return True

    try:
        from tool_factory.seed_plan.planning_pipeline import _resolve_data_tree_obstacle_labels

        hard_labels, _ = _resolve_data_tree_obstacle_labels(agent)
        if int(label_id) in {int(value) for value in hard_labels}:
            return True
    except Exception:
        logger.exception("[viewer_3d] Could not resolve the current hard-obstacle policy")

    return False


def _is_open_generic_mask_entry(entry):
    """Return whether a generic mask still belongs in the standalone group.

    A BiomedParse/open mask becomes an effective CTV or OAR through the real
    structure transaction. Once that happens it must be served by the CTV/OAR
    label endpoints only; returning it here would make the Viewer rebuild a
    second, stale standalone mesh and could overwrite its visibility state.
    """
    if not isinstance(entry, dict):
        return False
    classification = str(
        entry.get("classification") or entry.get("moved_to") or ""
    ).strip().lower()
    return classification not in {"ctv", "oar"}


def _generic_mask_entries(agent):
    """Return JSON-safe metadata for session-owned open segmentation masks."""
    raw = agent.memory.retrieve("generic_segmentation_masks") or []
    entries = []
    if not isinstance(raw, list):
        return entries
    for item in raw:
        if not _is_open_generic_mask_entry(item) or not item.get("mask_id"):
            continue
        entry = dict(item)
        # The binary payload is served separately so the catalogue stays fast
        # and never leaks a multi-megabyte array into the JSON response.
        entry.pop("mask_array", None)
        entries.append(entry)
    return entries


def _generic_mask_entry(agent, mask_id):
    wanted = str(mask_id or "").strip()
    if not wanted:
        return None
    raw = agent.memory.retrieve("generic_segmentation_masks") or []
    if not isinstance(raw, list):
        return None
    for item in raw:
        if _is_open_generic_mask_entry(item) and str(item.get("mask_id") or "") == wanted:
            return item
    return None


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
            "source_meta": agent.memory.retrieve("ct_source_meta") or {},
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
            # A Session switch/reconnect can reach the Viewer before the
            # metadata Agent has been installed.  This is a normal control
            # plane race, not a corrupt CT.  Return the same retryable
            # contract used by slice, mask, and 3D endpoints so the client
            # keeps the loading state instead of showing a false HTTP 500.
            return jsonify({
                "success": False,
                "pending": True,
                "code": "workspace_agent_initializing",
                "message": "The case agent is still initializing.",
                "retry_after_ms": 250,
            }), 202

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
            # Keep this route defensive even when a custom loader is injected:
            # DICOMOrient only receives a supported scalar 3-D CT frame. Do
            # not expose SimpleITK's low-level exception as an HTTP 500: the
            # browser can show a useful input error and keep the case usable.
            try:
                ct_sitk, volume_meta = normalize_ct_image(ct_sitk)
            except (TypeError, ValueError, RuntimeError) as exc:
                logger.warning("CT normalization rejected %s: %s", ct_path, exc)
                return jsonify({
                    "success": False,
                    "code": "unsupported_ct_geometry",
                    "error": str(exc),
                }), 422
            src_meta = {**(src_meta or {}), **volume_meta}
            logger.info(f"CT source kind: {kind}; meta: {src_meta}")

            if not hasattr(ct_sitk, "GetDimension") or int(ct_sitk.GetDimension()) != 3:
                return jsonify({
                    "success": False,
                    "code": "unsupported_ct_geometry",
                    "error": "CT input must resolve to one scalar 3-D volume.",
                }), 422

            # Reorient to LPI (Left-Posterior-Inferior) standard anatomical orientation
            try:
                ct_oriented = sitk.DICOMOrient(ct_sitk, 'LPI')
            except RuntimeError as exc:
                logger.warning("CT orientation failed after normalization %s: %s", ct_path, exc)
                return jsonify({
                    "success": False,
                    "code": "ct_orientation_failed",
                    "error": "The CT volume could not be oriented for viewing. Please use a scalar 3-D CT volume.",
                }), 422
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
                # Standalone BiomedParse/open-segmentation results belong to
                # the loaded CT. Never let a different patient inherit them.
                "generic_segmentation_masks", "generic_segmentation_latest",
                "generic_segmentation_completed",
                "oar_array", "oar_mask", "oar_is_full", "oar_source",
                "label_grid_orientation",
                "organ_names", "organ_counts", "dose_metrics", "dose_distribution",
                "dose_distribution_gy", "seed_plan", "seed_plan_serialized",
                "seed_positions", "trajectories", "refined_trajectories",
                "verified_needle_geometry", "dvh_data",
                # The Structure Set is derived from the new CT. Clear its
                # source snapshots, overrides and deletion ledger together.
                "ctv_embedded_oar_array", "structure_registry_initialized",
                "structure_base_ctv_array", "structure_base_ctv_full_labels",
                "structure_base_ctv_label_map", "structure_base_ctv_source",
                "structure_base_oar_array", "structure_base_organ_names",
                "structure_base_oar_source", "structure_overrides",
                "structure_deleted_ids", "structure_catalog",
                # Skin/guide/planning artifacts are patient-specific too.
                "skin_surface", "skin_surface_mask", "surgical_guide",
                "surgical_guide_versions", "artifact_status",
                "manual_artifact_status", "planning_runs",
                "active_planning_id", "planning_run_id", "manual_planning_id",
                "plan_config", "dose_units", "dose_scale_gy",
                "dose_distribution_physical_gy", "algorithm_plan_dose_distribution",
                "algorithm_plan_dose_distribution_gy", "algorithm_plan_dose_metrics",
                "algorithm_plan_dvh_data", "metrics", "manual_ai_dose",
                "manual_plan_active", "manual_plan_version", "manual_geometry_only",
                "manual_plan_serialized", "manual_planning_preview",
                "ct_source_meta", "ct_dicom_tags",
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
                "source_meta": {
                    key: value
                    for key, value in (src_meta or {}).items()
                    if key != "first_slice_tags"
                },
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
            return jsonify({
                "success": False,
                "pending": True,
                "code": "workspace_agent_initializing",
                "message": "The case agent is still initializing.",
                "retry_after_ms": 250,
            }), 202
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
            requested_slice_index = slice_index
            slice_index, axis = _clamp_viewer_slice_index(
                slice_index, axis_name, np.asarray(ct_data).shape, axis_map
            )
            if str(requested_slice_index) != str(slice_index):
                logger.debug(
                    "[viewer] clamped stale slice request axis=%s requested=%r actual=%d shape=%s",
                    axis_name, requested_slice_index, slice_index, tuple(ct_data.shape),
                )
            # Apply window/level
            lower = window_center - window_width / 2
            upper = window_center + window_width / 2
            ct_windowed = np.clip(ct_data, lower, upper)
            ct_windowed = ((ct_windowed - lower) / (upper - lower) * 255).astype(np.uint8)

            # Get a slice from the canonical LPI array (Z, Y, X).  The viewer
            # keeps the historical axial display-index direction, while the
            # vertical coordinate of sagittal/coronal reformats follows array
            # Z directly.  This is intentionally the same contract as the
            # browser volume renderer and its linked crosshair interaction.
            slice_data = np.take(ct_windowed, slice_index, axis=axis)

            # Axial is a single plane, so map its display index to the reversed
            # canonical Z index.  Sagittal/coronal already have Z as their
            # first image dimension; do not reverse it or the fallback path
            # would disagree with the client-side volume path.
            if axis_name == 'axial':
                src_idx = ct_data.shape[0] - 1 - slice_index
                slice_data = np.take(ct_windowed, src_idx, axis=axis)
            elif axis_name == 'sagittal':
                # (Z, Y): image height=Z, width=Y.
                slice_data = ct_windowed[:, :, slice_index]
            elif axis_name == 'coronal':
                # (Z, X): image height=Z, width=X.
                slice_data = ct_windowed[:, slice_index, :]

            # Match the browser MPR geometry when this request is served by
            # the PNG fallback (for example while the volume blob is still
            # hydrating).  Keeping the resampled height and nearest-neighbor
            # Z lookup identical is necessary for mouse coordinates and
            # crosshairs to remain valid across the two rendering paths.
            z_resample_indices = _viewer_mpr_z_resample_indices(
                slice_data.shape[0],
                agent.memory.retrieve("ct_spacing") or (0.6836, 0.6836, 5.0),
                axis_name,
            )
            if z_resample_indices is not None:
                slice_data = slice_data[z_resample_indices, :]

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
                    mask_slice = mask[:, :, slice_index]
                elif axis_name == 'coronal':
                    mask_slice = mask[:, slice_index, :]
                if z_resample_indices is not None:
                    mask_slice = mask_slice[z_resample_indices, :]
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
                "slice_index": int(slice_index),
                "requested_slice_index": requested_slice_index,
                "total_slices": int(ct_data.shape[axis]),
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
            # Structure reclassification intentionally exposes the effective
            # source as ``classified``.  The original model provenance is
            # still authoritative for deciding whether ctv_full_labels may be
            # split into embedded anatomy nodes.
            base_ctv_source = str(
                agent.memory.retrieve("structure_base_ctv_source", "") or ""
            ).strip().lower()
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
            # opaque user data and remains a foreground CTV mask. Historical
            # BiomedParse/TotalSegmentator CTV outputs and current SAT3D
            # outputs are model-produced, so restored payloads from those
            # sources follow the model path rather than uploaded-label logic.
            # Keep the former source token for old sessions created before the
            # provenance field was simplified.
            model_sources = {
                "model",
                "biomedparse_v2",
                "biomedparse_v2_research_candidate",
                "totalsegmentator",
                "totalsegmentator_liver_tumor",
                "sat3d",
            }
            # Keep model-produced multi-label CTV payloads intact across
            # restore. The pancreatic nnUNet route uses a specific provenance
            # token, so treating only the legacy `model` token as multi-label
            # silently dropped pancreas/artery/vein when OAR was loaded later.
            is_model_ctv = (
                ctv_source in model_sources
                or ctv_source.startswith("nnunet_")
                or ctv_source.startswith("biomedparse_")
                or ctv_source.startswith("totalsegmentator_")
                or ctv_source.startswith("sat3d")
                or base_ctv_source in model_sources
                or base_ctv_source.startswith("nnunet_")
                or base_ctv_source.startswith("biomedparse_")
                or base_ctv_source.startswith("totalsegmentator_")
                or base_ctv_source.startswith("sat3d")
            )
            ctv_full = ctv_full_memory if is_model_ctv else None
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
                if is_model_ctv:
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
                        # Restored NPY sidecars are often read-only memmaps.
                        # The embedded-label merge is a real in-memory
                        # mutation, so always detach a private writable buffer
                        # instead of relying on astype(copy=False).
                        oar_array = np.array(
                            oar_array,
                            dtype=np.uint16,
                            copy=True,
                            order="C",
                        )
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

            # CTV and OAR volumes may both use label 1. Keep independent LUTs
            # so an OAR refresh cannot overwrite the primary target's red.
            ctv_color_lut = {}
            oar_color_lut = {}
            if ctv_array is not None:
                # Add all CTV labels with distinct colors
                for lid in np.unique(ctv_array):
                    if lid > 0:
                        ctv_color_lut[int(lid)] = list(_ctv_label_color(int(lid)))
            if oar_array is not None:
                for lid in np.unique(oar_array):
                    if lid > 0:
                        oar_color_lut[int(lid)] = list(_label_color(int(lid)))

            # Retain the legacy header for older clients. Current clients use
            # the typed LUTs below and therefore tolerate overlapping IDs.
            color_lut = {**ctv_color_lut, **oar_color_lut}

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
            response.headers['X-CTV-Color-LUT'] = _json.dumps(ctv_color_lut)
            response.headers['X-OAR-Color-LUT'] = _json.dumps(oar_color_lut)
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
            if is_model_ctv and ctv_full_memory is not None:
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
                            "color": oar_color_lut.get(lid_int, [200, 200, 200]),
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

    @app.route("/api/viewer/generic_masks", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_viewer_generic_masks():
        """List open BiomedParse masks for the active session."""
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({
                "success": False,
                "pending": True,
                "code": "workspace_agent_initializing",
                "message": "The case agent is still initializing.",
                "retry_after_ms": 250,
            }), 202
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending
        from web.uploaded_mask_service import public_uploaded_mask_collections

        return jsonify({
            "success": True,
            "masks": _generic_mask_entries(agent),
            "uploads": public_uploaded_mask_collections(agent.memory),
        })

    @app.route("/api/viewer/generic_mask_volume", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_viewer_generic_mask_volume():
        """Return one persisted open mask as a session-scoped binary volume."""
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({
                "success": False,
                "pending": True,
                "code": "workspace_agent_initializing",
                "message": "The case agent is still initializing.",
                "retry_after_ms": 250,
            }), 202
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending
        entry = _generic_mask_entry(agent, request.args.get("mask_id"))
        if entry is None:
            return jsonify({"success": False, "error": "Generic mask is not available"}), 404
        raw_mask = entry.get("mask_array")
        if raw_mask is None:
            hydration_active = bool(
                getattr(agent, "_workspace_hydration_in_progress", False)
                or getattr(agent, "_workspace_hydration_phase", "")
                not in {"", "ready", "failed"}
            )
            return jsonify({
                "success": False,
                "pending": hydration_active,
                "code": (
                    "generic_mask_hydration_pending"
                    if hydration_active else "generic_mask_unavailable"
                ),
                "message": (
                    "Mask data is still loading."
                    if hydration_active else "Generic segmentation mask data is unavailable."
                ),
                "retry_after_ms": 250 if hydration_active else 0,
            }), 202 if hydration_active else 409
        try:
            volume = np.ascontiguousarray(np.asarray(raw_mask, dtype=np.uint8) > 0)
            ct_data = agent.memory.retrieve("ct_data")
            if volume.ndim != 3 or (ct_data is not None and volume.shape != np.asarray(ct_data).shape):
                return jsonify({"success": False, "error": "Generic mask does not match the current CT geometry"}), 409
            raw = volume.astype(np.uint8, copy=False).tobytes(order="C")
            response = Response(raw, mimetype="application/octet-stream")
            if "gzip" in request.headers.get("Accept-Encoding", ""):
                response.set_data(gzip.compress(raw, compresslevel=4))
                response.headers["Content-Encoding"] = "gzip"
            shape = volume.shape
            response.headers["X-Shape-Z"] = str(shape[0])
            response.headers["X-Shape-Y"] = str(shape[1])
            response.headers["X-Shape-X"] = str(shape[2])
            response.headers["X-Mask-ID"] = str(entry.get("mask_id"))
            response.headers["X-Object-ID"] = str(entry.get("object_id") or "")
            response.headers["X-Data-Tree-Node-ID"] = str(entry.get("data_tree_node_id") or entry.get("mask_id"))
            response.headers["X-Data-Version"] = str(entry.get("data_version") or 1)
            response.headers["X-Session-ID"] = str(entry.get("session_id") or getattr(agent.memory, "session_id", ""))
            response.headers["X-Spacing"] = json.dumps(entry.get("spacing") or agent.memory.retrieve("ct_spacing") or [1, 1, 1])
            response.headers["X-Origin"] = json.dumps(entry.get("origin") or agent.memory.retrieve("ct_origin") or [0, 0, 0])
            response.headers["X-Direction"] = json.dumps(entry.get("direction") or agent.memory.retrieve("ct_direction") or [1, 0, 0, 0, 1, 0, 0, 0, 1])
            response.headers["X-Target"] = str(entry.get("target") or entry.get("label") or "")
            stored_voxel_count = entry.get("voxel_count")
            try:
                voxel_count = (
                    int(stored_voxel_count)
                    if stored_voxel_count is not None
                    else int(np.count_nonzero(volume))
                )
            except (TypeError, ValueError):
                voxel_count = int(np.count_nonzero(volume))
            response.headers["X-Voxel-Count"] = str(voxel_count)
            response.headers["Cache-Control"] = "private, no-store"
            return response
        except Exception as exc:
            logger.warning("Generic mask volume unavailable: %s", exc)
            return jsonify({
                "success": False,
                "code": "generic_mask_unavailable",
                "error": "Generic segmentation mask data is unavailable.",
            }), 409

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
            slice_index, axis = _clamp_viewer_slice_index(
                slice_index, axis_name, np.asarray(ct_data).shape, axis_map
            )

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

            # Extract slice from the canonical (Z, Y, X) mask using the same
            # display contract as /api/viewer/slice and the browser renderer.
            if axis_name == 'axial':
                src_idx = mask_data.shape[0] - 1 - slice_index
                mask_slice = np.take(mask_data, src_idx, axis=axis)
            elif axis_name == 'sagittal':
                mask_slice = mask_data[:, :, slice_index]
            elif axis_name == 'coronal':
                mask_slice = mask_data[:, slice_index, :]

            # For sagittal/coronal: resample Z-axis to match isotropic display
            # Client expects: sagittal -> width=Y, height=Z_resampled
            #                coronal -> width=X, height=Z_resampled
            # After np.take: sagittal=(Z, Y), coronal=(Z, X)
            # Image.fromarray(H, W) -> image width=W, height=H
            # So (Z_resampled, Y) -> width=Y, height=Z_resampled ✓
            z_resample_indices = _viewer_mpr_z_resample_indices(
                mask_slice.shape[0],
                agent.memory.retrieve("ct_spacing") or (0.6836, 0.6836, 5.0),
                axis_name,
            )
            if z_resample_indices is not None:
                mask_slice = mask_slice[z_resample_indices, :]
                # No transpose needed - (Z_resampled, Y/X) gives correct width/height

            # Create colored overlay with per-organ visibility/opacity
            overlay = np.zeros((*mask_slice.shape, 4), dtype=np.uint8)

            if overlay_type == "ctv":
                alpha = int(ctv_opacity * 255)
                unique_ctv_labels = np.unique(mask_slice[mask_slice > 0])
                # Always use per-label colors (consistent with data tree display)
                for label in unique_ctv_labels:
                    label_int = int(label)
                    color = _ctv_label_color(label_int)
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
                    # Use the shared Slicer-style palette for the Data Tree,
                    # 2D overlay and reconstructed 3D surface.
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
        # This route only reads the already hydrated CT volume. Constructing a
        # full LLM agent here made a simple threshold/3D action wait behind
        # unrelated planning state and could leave the browser without a
        # responsive transition. Use the lightweight agent path just like the
        # label-mesh routes.
        agent = get_agent(_lightweight=True)
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
            slice_index, mask_axis = _clamp_viewer_slice_index(
                slice_index, axis, np.asarray(mask).shape, axis_map
            )
            if axis == "axial":
                # The threshold endpoint returns the same displayed axial
                # plane as the main viewer, not the raw array plane at the
                # same slider number.
                mask_slice = np.take(mask, mask.shape[0] - 1 - slice_index, axis=mask_axis)
            else:
                mask_slice = np.take(mask, slice_index, axis=mask_axis)

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
        """Vectorized Laplacian smoothing for a presentation mesh.

        The previous implementation built Python ``set`` adjacency objects
        and iterated over every vertex for every smoothing pass. With dozens
        of OAR surfaces this made a normal Viewer restore spend minutes in
        Python while the browser correctly waited for the mesh promises.
        Aggregate triangle-edge neighbor coordinates with NumPy instead of
        allocating Python adjacency sets. Repeated incidences preserve the
        local triangle weighting used by the presentation smoother; this
        changes only presentation smoothing, never the authoritative mask or
        dose data.
        """
        import numpy as np
        verts = np.asarray(vertices, dtype=np.float64).copy()
        triangles = np.asarray(faces, dtype=np.int64)
        if (verts.ndim != 2 or verts.shape[1] != 3
                or triangles.ndim != 2 or triangles.shape[1] != 3
                or len(verts) == 0 or len(triangles) == 0):
            return verts

        # Every triangle contributes both orientations of its three edges.
        # Duplicate incidences are intentional: they cancel in the degree /
        # sum ratio and avoid a costly Python/set de-duplication pass.
        edges = np.concatenate((
            triangles[:, [0, 1]], triangles[:, [1, 0]],
            triangles[:, [1, 2]], triangles[:, [2, 1]],
            triangles[:, [2, 0]], triangles[:, [0, 2]],
        ), axis=0)
        valid_edges = (
            (edges[:, 0] >= 0) & (edges[:, 0] < len(verts))
            & (edges[:, 1] >= 0) & (edges[:, 1] < len(verts))
        )
        edges = edges[valid_edges]
        if len(edges) == 0:
            return verts
        sources = edges[:, 0]
        targets = edges[:, 1]
        degree = np.bincount(sources, minlength=len(verts)).astype(np.float64)
        valid_vertices = degree > 0
        for _ in range(max(0, int(iterations))):
            neighbor_sum = np.zeros_like(verts)
            np.add.at(neighbor_sum, sources, verts[targets])
            centroid = np.zeros_like(verts)
            centroid[valid_vertices] = (
                neighbor_sum[valid_vertices]
                / degree[valid_vertices, None]
            )
            verts[valid_vertices] += factor * (
                centroid[valid_vertices] - verts[valid_vertices]
            )
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
            original_mask = mask.copy()
            source_mask_shape = tuple(int(value) for value in mask.shape)
            mask, crop_origin_zyx = _crop_binary_surface_volume(mask)

            # CTV geometry must remain identical to the mask used by DVH and
            # dose evaluation. Ordinary anatomy can retain presentation
            # cleanup, but never enlarge a target that users compare against
            # the prescription isosurface.
            label_faithful = str(source or "").strip().lower() == "ctv"
            if not label_faithful:
                # Keep the historical full-volume density decision while
                # applying morphology only to the cropped display domain.
                density = mask.sum() / max(1, int(np.prod(source_mask_shape)))
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

            # A 3-D closing can erase a one-slice structure on anisotropic CT.
            # Presentation cleanup must never turn an existing label into a
            # failed reconstruction; fall back to its exact source geometry.
            preprocessing_fallback = False
            if not np.any(mask):
                logger.warning(
                    "3D presentation cleanup erased %s label=%s; using source mask",
                    source,
                    label_id,
                )
                mask = original_mask
                mask, crop_origin_zyx = _crop_binary_surface_volume(mask)
                preprocessing_fallback = True

            try:
                smooth_field, surface_padding_zyx = _signed_surface_field(mask)
            except ValueError as exc:
                return jsonify({
                    "success": False,
                    "code": "invalid_surface_geometry",
                    "error": str(exc),
                }), 422

            spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
            spacing_xyz = tuple(float(s) for s in spacing[:3])
            spacing_zyx = spacing_xyz[::-1]

            vertices, faces, normals, values = measure.marching_cubes(
                smooth_field, level=0.0, spacing=spacing_zyx, allow_degenerate=False
            )
            vertices -= surface_padding_zyx * np.asarray(spacing_zyx, dtype=np.float64)
            # ``vertices`` are currently relative to the cropped volume. Put
            # them back in the original CT array coordinate system before the
            # existing spacing/direction/origin conversion.
            vertices += crop_origin_zyx * np.asarray(spacing_zyx, dtype=np.float64)

            if not label_faithful:
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
                "geometry_mode": "label_faithful" if label_faithful else "presentation_smoothed",
                "preprocessing_fallback": preprocessing_fallback,
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
            return jsonify({
                "success": False,
                "pending": True,
                "code": "workspace_agent_initializing",
                "message": "The case agent is still initializing.",
                "retry_after_ms": 250,
            }), 202
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending

        # Derived meshes are restart-safe only when their disk cache is scoped
        # to the authenticated case. Resolve this once for the request; cache
        # failures remain non-fatal because the in-memory/clinical data path is
        # authoritative.
        cache_root = None
        case_session_id = ""
        try:
            store, user, case_session_id = request_case_context()
            cache_root = store.workspace_root(user["id"], case_session_id, create=False)
        except Exception as exc:
            logger.debug("Segmentation mesh persistent cache unavailable: %s", exc)

        data = request.get_json() or {}
        label_id = data.get("label_id")
        source = data.get("source", "oar")  # "oar" or "ctv"
        mask_id = str(data.get("mask_id") or "").strip()

        if source == "generic" and not mask_id:
            return jsonify({"error": "mask_id required for generic masks"}), 400
        if source != "generic" and label_id is None:
            return jsonify({"error": "label_id required"}), 400

        try:
            import hashlib
            import numpy as np
            from skimage import measure
            from scipy.ndimage import binary_closing, binary_fill_holes, binary_dilation, gaussian_filter

            if source == "generic":
                generic_entry = _generic_mask_entry(agent, mask_id)
                if generic_entry is None:
                    return jsonify({"success": False, "code": "generic_mask_not_found", "error": "Generic mask is not available"}), 404
                if generic_entry.get("mask_array") is None:
                    hydration_active = bool(
                        getattr(agent, "_workspace_hydration_in_progress", False)
                        or getattr(agent, "_workspace_hydration_phase", "")
                        not in {"", "ready", "failed"}
                    )
                    return jsonify({
                        "success": False,
                        "pending": hydration_active,
                        "code": "generic_mask_hydration_pending" if hydration_active else "generic_mask_unavailable",
                        "error": "Generic segmentation mask is still loading." if hydration_active else "Generic segmentation mask data is unavailable.",
                        "retry_after_ms": 250 if hydration_active else 0,
                    }), 202 if hydration_active else 409
                mask_data = np.asarray(generic_entry["mask_array"], dtype=np.uint8)
                label_faithful = True
            elif source == "ctv":
                mask_data = agent._get_label_array("ctv_array")
                label_faithful = _requires_label_faithful_mesh(agent, source, int(label_id))
            else:
                mask_data = agent._get_label_array("oar_array")
                label_faithful = _requires_label_faithful_mesh(agent, source, int(label_id))

            if mask_data is None:
                hydration_active = bool(
                    getattr(agent, "_workspace_hydration_in_progress", False)
                    or getattr(agent, "_workspace_hydration_phase", "")
                    not in {"", "ready", "failed"}
                )
                return jsonify({
                    "success": False,
                    "pending": hydration_active,
                    "code": (
                        "workspace_hydration_pending"
                        if hydration_active else "mask_data_unavailable"
                    ),
                    "error": (
                        f"{source.upper()} mask data is still loading."
                        if hydration_active
                        else f"No {source} mask data is available for this case."
                    ),
                    "retry_after_ms": 250 if hydration_active else 0,
                }), 202 if hydration_active else 409

            if getattr(mask_data, "ndim", None) != 3:
                return jsonify({
                    "success": False,
                    "code": "invalid_mask_geometry",
                    "error": "Mask data must be a 3-D volume on the current CT grid.",
                }), 409
            ct_data = agent.memory.retrieve("ct_data")
            if ct_data is not None and tuple(mask_data.shape) != tuple(np.asarray(ct_data).shape):
                return jsonify({
                    "success": False,
                    "code": "mask_geometry_mismatch",
                    "error": "Mask data does not match the current CT geometry.",
                }), 409

            # Extract binary mask for this label
            if source != "generic":
                label_id = int(label_id)
            try:
                mask_shape_key = tuple(int(x) for x in getattr(mask_data, "shape", ()))
            except Exception:
                mask_shape_key = ()
            smoothing_key = data.get("smoothing", 1)
            binary_mask = (
                (mask_data > 0).astype(np.uint8)
                if source == "generic"
                else (mask_data == label_id).astype(np.uint8)
            )

            total_voxels = int(binary_mask.sum())
            if total_voxels == 0:
                missing = mask_id if source == "generic" else f"label {label_id}"
                if bool(data.get("allow_missing")):
                    # Background prewarming can observe a persisted label map
                    # one request before the matching volume is available.
                    # Treat that one optional mesh as a skipped item; an
                    # explicit user reconstruction still receives the 400
                    # below and remains diagnosable.
                    return jsonify({
                        "success": False,
                        "skipped": True,
                        "code": "mask_label_not_present",
                        "message": f"{missing} is not present in the current mask.",
                    })
                return jsonify({"error": f"{missing} not found in mask"}), 400
            source_mask_shape = tuple(int(value) for value in binary_mask.shape)
            source_mask_digest = hashlib.blake2b(
                np.ascontiguousarray(binary_mask).tobytes(), digest_size=16,
            ).hexdigest()
            # Distance transforms are the dominant cost of one mesh. Limit
            # them to the structure's padded bounding box, then restore the
            # original array offset before converting to patient coordinates.
            binary_mask, crop_origin_zyx = _crop_binary_surface_volume(binary_mask)
            original_binary_mask = binary_mask.copy()
            binary_mask = np.ascontiguousarray(binary_mask, dtype=np.uint8)
            # Hash the complete source mask, not only the crop. The crop
            # origin is included below as well, so a same-shaped label at a
            # different patient position can never reuse the wrong geometry.
            mask_digest = source_mask_digest
            geometry = _viewer_geometry_signature(agent, mask_shape_key)
            cache_components = {
                "source": source,
                "label_id": mask_id if source == "generic" else label_id,
                "smoothing": str(smoothing_key),
                "label_faithful": bool(label_faithful),
                "mask_shape": list(mask_shape_key),
                "mask_voxels": total_voxels,
                "mask_digest": mask_digest,
                "crop_origin_zyx": [int(value) for value in crop_origin_zyx],
                "geometry": geometry,
                "boundary_padding": int(_MESH_BOUNDARY_PADDING_VOXELS),
                "crop_margin_voxels": int(_MESH_CROP_MARGIN_VOXELS),
                "processing_version": "label-mesh-v3-cropped",
            }
            persistent_cache_key = viewer_cache_key("segmentation_mesh", cache_components)
            # Include the case identity in the process-local cache as well.
            # The previous key could reuse a same-shaped/same-label mesh from
            # another session with different CT origin or direction.
            cache_key = (
                "v2", case_session_id, persistent_cache_key,
            )
            with _MESH_CACHE_LOCK:
                cached = _MESH_CACHE.get(cache_key)
            if cached is not None:
                cached_payload = dict(cached)
                cached_payload["cached"] = True
                return _viewer_json_response(cached_payload)

            if cache_root is not None:
                cached = load_viewer_cache(
                    cache_root, "segmentation-mesh", persistent_cache_key,
                )
                if cached is not None and cached.get("success") is True and cached.get("vertex_count"):
                    with _MESH_CACHE_LOCK:
                        _MESH_CACHE[cache_key] = dict(cached)
                        _MESH_CACHE_ORDER.append(cache_key)
                        while len(_MESH_CACHE_ORDER) > _MESH_CACHE_MAX_ITEMS:
                            old_key = _MESH_CACHE_ORDER.popleft()
                            _MESH_CACHE.pop(old_key, None)
                    cached["cached"] = True
                    logger.info(
                        "[3d_mask] persistent cache hit source=%s label=%s vertices=%s",
                        source,
                        mask_id if source == "generic" else label_id,
                        cached.get("vertex_count"),
                    )
                    return _viewer_json_response(cached)

            if not label_faithful:
                # Adaptive preprocessing is useful for presentation meshes of
                # ordinary anatomy, but it deliberately does not apply to a
                # hard obstacle; changing that surface would contradict the
                # physical mask used by candidate trajectory filtering.
                # Keep the historical full-volume density decision while
                # applying morphology only to the cropped display domain.
                mask_volume = max(1, int(np.prod(source_mask_shape)))
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

            preprocessing_fallback = False
            if not np.any(binary_mask):
                logger.warning(
                    "3D mask cleanup erased source=%s id=%s voxels=%s; using source mask",
                    source,
                    mask_id if source == "generic" else label_id,
                    total_voxels,
                )
                binary_mask = original_binary_mask
                preprocessing_fallback = True

            # Pad and validate centrally. The signed field is negative inside
            # and positive outside; level zero is therefore a real boundary.
            try:
                smooth_field, surface_padding_zyx = _signed_surface_field(binary_mask)
            except ValueError as exc:
                if bool(data.get("allow_missing")):
                    return jsonify({
                        "success": False,
                        "skipped": True,
                        "code": "invalid_surface_geometry",
                        "message": str(exc),
                    })
                return jsonify({
                    "success": False,
                    "code": "invalid_surface_geometry",
                    "error": str(exc),
                }), 422

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
            vertices -= surface_padding_zyx * np.asarray(spacing_zyx, dtype=np.float64)
            # ``vertices`` are relative to the cropped volume. Restore the
            # original CT array offset before the patient-world transform.
            vertices += crop_origin_zyx * np.asarray(spacing_zyx, dtype=np.float64)

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
                "mask_id": mask_id if source == "generic" else None,
                "source": source,
                "geometry_mode": "label_faithful" if label_faithful else "presentation_smoothed",
                "preprocessing_fallback": preprocessing_fallback,
                "surface_boundary_padding_voxels": int(_MESH_BOUNDARY_PADDING_VOXELS),
                "cached": False,
            }
            with _MESH_CACHE_LOCK:
                _MESH_CACHE[cache_key] = payload
                _MESH_CACHE_ORDER.append(cache_key)
                while len(_MESH_CACHE_ORDER) > _MESH_CACHE_MAX_ITEMS:
                    old_key = _MESH_CACHE_ORDER.popleft()
                    _MESH_CACHE.pop(old_key, None)

            # Persist only after the complete mesh payload has been built and
            # inserted into the process-local cache. The write is atomic and
            # asynchronous; a restart during this write can lose a derived
            # cache file, but never a clinical array or a successful response.
            schedule_viewer_cache_write(
                cache_root,
                "segmentation-mesh",
                persistent_cache_key,
                payload,
            )

            return _viewer_json_response(payload)
        except Exception as e:
            logger.error(f"3D mask reconstruction failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/skin_surface_volume", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_viewer_skin_surface_volume():
        """Return the persisted guide skin segmentation in CT voxel order."""
        agent = get_agent(_lightweight=True)
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending
        mask = agent.memory.retrieve("skin_surface_mask")
        metadata = agent.memory.retrieve("skin_surface") or {}
        if mask is None or not isinstance(metadata, dict):
            return jsonify({
                "success": False,
                "available": False,
                "error": "Guide skin surface is not available",
            }), 404
        try:
            import numpy as np

            volume = np.ascontiguousarray(np.asarray(mask, dtype=np.uint8))
            ct_data = agent.memory.retrieve("ct_data")
            if volume.ndim != 3 or (ct_data is not None and volume.shape != np.asarray(ct_data).shape):
                return jsonify({
                    "success": False,
                    "available": False,
                    "error": "Guide skin surface does not match the current CT geometry",
                }), 409
            raw = volume.tobytes(order="C")
            response = Response(raw, mimetype="application/octet-stream")
            if "gzip" in request.headers.get("Accept-Encoding", ""):
                response.set_data(gzip.compress(raw, compresslevel=4))
                response.headers["Content-Encoding"] = "gzip"
            response.headers["X-Shape-Z"] = str(volume.shape[0])
            response.headers["X-Shape-Y"] = str(volume.shape[1])
            response.headers["X-Shape-X"] = str(volume.shape[2])
            response.headers["X-Object-ID"] = str(metadata.get("object_id") or "skin_surface:guide")
            response.headers["X-Data-Tree-Node-ID"] = str(metadata.get("data_tree_node_id") or "skin_surface")
            response.headers["X-Data-Version"] = str(int(metadata.get("data_version") or 1))
            response.headers["X-Planning-ID"] = str(metadata.get("planning_id") or "")
            response.headers["X-Threshold-HU"] = str(float(metadata.get("threshold_hu") or -300.0))
            response.headers["X-Voxel-Count"] = str(
                int(metadata.get("voxel_count") or np.count_nonzero(volume))
            )
            response.headers["Cache-Control"] = "private, no-store"
            return response
        except Exception as exc:
            logger.error("Guide skin volume failed: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/viewer/3d_skin", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_3d_skin():
        """Generate CT skin mesh using isosurface (marching cubes at skin threshold)."""
        # This route only reads the already hydrated CT volume. Constructing a
        # full LLM agent here made a simple threshold/3D action wait behind
        # unrelated planning state and could leave the browser without a
        # responsive transition. Use the lightweight agent path just like the
        # label-mesh routes.
        agent = get_agent(_lightweight=True)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        # The skin surface is also a derived Viewer artifact. Keep its cache
        # separate from clinical arrays and scope it to the authenticated
        # case, so restarting the server does not repeat a full CT marching
        # cubes pass or accidentally reuse another patient's surface.
        cache_root = None
        case_session_id = ""
        try:
            store, user, case_session_id = request_case_context()
            cache_root = store.workspace_root(user["id"], case_session_id, create=False)
        except Exception as exc:
            logger.debug("Skin mesh persistent cache unavailable: %s", exc)

        data = request.get_json() or {}
        source = str(data.get("source") or "threshold").strip().lower()
        threshold = data.get("threshold", -300)  # Default: skin surface at -300 HU
        persisted_skin = agent.memory.retrieve("skin_surface_mask") if source == "guide" else None
        skin_metadata = agent.memory.retrieve("skin_surface") or {}
        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            # Lightweight agent construction intentionally returns before the
            # CT sidecar is decoded. The browser must be able to start the
            # request without turning this normal hydration window into a
            # permanent mask failure.
            hydration_phase = str(getattr(agent, "_workspace_hydration_phase", "") or "")
            if getattr(agent, "_workspace_hydration_in_progress", False) or hydration_phase not in {"", "ready", "error"}:
                return jsonify({
                    "success": False,
                    "pending": True,
                    "retry_after_ms": 300,
                    "error": "CT volume is still loading",
                }), 202
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

            if source == "guide":
                if persisted_skin is None or not isinstance(skin_metadata, dict):
                    return jsonify({"success": False, "error": "Guide skin surface is not available"}), 404
                surface_data = np.asarray(persisted_skin, dtype=np.uint8)
                if surface_data.shape != np.asarray(ct_data).shape:
                    return jsonify({
                        "success": False,
                        "error": "Guide skin surface does not match the current CT geometry",
                    }), 409
            else:
                surface_data = np.asarray(ct_data)

            # Preserve the exact guide envelope at full CT resolution. Manual
            # threshold previews retain the existing bounded subsampling path.
            if source != "guide" and surface_data.shape[0] > 64:
                step = max(1, surface_data.shape[0] // 64)
                ct_sub = surface_data[::step, ::step, ::step]
                sub_spacing = (spacing_zyx[0] * step, spacing_zyx[1] * step, spacing_zyx[2] * step)
            else:
                ct_sub = surface_data
                sub_spacing = spacing_zyx

            surface_array = np.ascontiguousarray(surface_data)
            surface_digest = hashlib.blake2b(
                surface_array.tobytes(), digest_size=16,
            ).hexdigest()
            skin_cache_key = viewer_cache_key(
                "skin_mesh",
                {
                    "source": source,
                    "threshold": float(threshold) if source != "guide" else 0.5,
                    "surface_shape": [int(item) for item in surface_data.shape],
                    "surface_dtype": str(surface_array.dtype),
                    "surface_digest": surface_digest,
                    "subsample_step": int(step) if source != "guide" and surface_data.shape[0] > 64 else 1,
                    "subsurface_shape": [int(item) for item in ct_sub.shape],
                    "subsurface_spacing_zyx": [float(item) for item in sub_spacing],
                    "spacing_xyz": [float(item) for item in spacing_xyz],
                    "origin_xyz": [float(item) for item in origin[:3]],
                    "direction": [float(item) for item in direction[:9]],
                    "guide_planning_id": skin_metadata.get("planning_id") if source == "guide" else None,
                    "guide_data_version": skin_metadata.get("data_version") if source == "guide" else None,
                    "boundary_padding": int(_MESH_BOUNDARY_PADDING_VOXELS),
                    "processing_version": "skin-surface-v2",
                },
            )
            skin_process_cache_key = ("skin-v2", case_session_id, skin_cache_key)
            with _MESH_CACHE_LOCK:
                process_cached = _MESH_CACHE.get(skin_process_cache_key)
            if process_cached is not None:
                cached_payload = dict(process_cached)
                cached_payload["cached"] = True
                return _viewer_json_response(cached_payload)
            if cache_root is not None:
                disk_cached = load_viewer_cache(cache_root, "skin-mesh", skin_cache_key)
                if disk_cached is not None and disk_cached.get("success") is True:
                    with _MESH_CACHE_LOCK:
                        _MESH_CACHE[skin_process_cache_key] = dict(disk_cached)
                        _MESH_CACHE_ORDER.append(skin_process_cache_key)
                        while len(_MESH_CACHE_ORDER) > _MESH_CACHE_MAX_ITEMS:
                            old_key = _MESH_CACHE_ORDER.popleft()
                            _MESH_CACHE.pop(old_key, None)
                    disk_cached["cached"] = True
                    logger.info(
                        "[3d_skin] persistent cache hit source=%s vertices=%s",
                        source,
                        disk_cached.get("vertex_count", 0),
                    )
                    return _viewer_json_response(disk_cached)

            data_min, data_max = float(ct_sub.min()), float(ct_sub.max())
            level = 0.5 if source == "guide" else float(threshold)
            if level <= data_min or level >= data_max:
                if source == "guide":
                    return jsonify({"success": False, "error": "Guide skin surface is empty"}), 409
                level = (data_min + data_max) / 2.0

            # Treat the outside of the acquired CT as air for the skin
            # surface. Padding prevents marching cubes from leaving an open
            # cap at the first/last slice, which otherwise appears as an
            # artificial rectangular clipping boundary in 3D.
            outside_value = 0.0 if source == "guide" else min(data_min, level - 1.0)
            ct_for_surface, surface_padding_zyx = _pad_surface_volume(
                ct_sub, fill_value=outside_value
            )
            vertices, faces, _, _ = measure.marching_cubes(
                ct_for_surface,
                level=level,
                spacing=sub_spacing,
                allow_degenerate=False,
            )
            vertices -= surface_padding_zyx * np.asarray(sub_spacing, dtype=np.float64)

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

            payload = {
                "success": True,
                "vertices": vertices.tolist(),
                "faces": faces.tolist(),
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "threshold": threshold,
                "source": "skin_surface" if source == "guide" else "threshold",
                "organ_id": "skin_surface" if source == "guide" else None,
                "object_id": (
                    skin_metadata.get("object_id", "skin_surface:guide")
                    if source == "guide" else None
                ),
                "data_tree_node_id": (
                    skin_metadata.get("data_tree_node_id", "skin_surface")
                    if source == "guide" else None
                ),
                "planning_id": skin_metadata.get("planning_id") if source == "guide" else None,
                "data_version": skin_metadata.get("data_version") if source == "guide" else None,
                "surface_boundary_padding_voxels": int(_MESH_BOUNDARY_PADDING_VOXELS),
                "cached": False,
            }
            with _MESH_CACHE_LOCK:
                _MESH_CACHE[skin_process_cache_key] = payload
                _MESH_CACHE_ORDER.append(skin_process_cache_key)
                while len(_MESH_CACHE_ORDER) > _MESH_CACHE_MAX_ITEMS:
                    old_key = _MESH_CACHE_ORDER.popleft()
                    _MESH_CACHE.pop(old_key, None)
            schedule_viewer_cache_write(
                cache_root,
                "skin-mesh",
                skin_cache_key,
                payload,
            )
            return _viewer_json_response(payload)
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

        # Do not run display-time safety filtering against the metadata-only
        # hydration shell. A cold restore may contain the durable seed plan
        # while CTV/OAR arrays are still decoding; that is a pending state,
        # not evidence that every needle is unsafe.
        pending = workspace_data_pending(agent)
        if pending is not None:
            return pending

        try:
            import numpy as np

            seed_plan = agent.memory.retrieve("seed_plan")
            seed_plan_serialized = agent.memory.retrieve("seed_plan_serialized") or []
            manual_plan_serialized = agent.memory.retrieve("manual_plan_serialized") or []
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
            manual_seeds = agent.memory.retrieve("manual_seeds") or []
            has_manual_geometry = bool(
                agent.memory.retrieve("manual_plan_active")
                or manual_needles
                or manual_seeds
            )
            if seed_plan is None and not seed_plan_serialized and not manual_plan_serialized:
                return jsonify({
                    "success": True,
                    "seeds": [],
                    "needles": [],
                    "seed_geometry": seed_geometry,
                    "message": "No seed plan available",
                })

            ct_image = agent.memory.retrieve("ct_image")

            # Revalidate the exact world-coordinate line when the current
            # inputs are the same ones that produced the persisted plan. If
            # the inputs changed, preserve the immutable geometry as a
            # clearly stale, review-only artifact instead of silently making
            # the Planning appear empty. Manual edits remain fail-closed
            # against the current original-grid masks.
            safety_ctv = None
            safety_oar = None
            obstacle_labels = set()
            world_validator = None
            safety_state = "deferred"
            safety_warning = None
            stored_safety_context = agent.memory.retrieve("needle_safety_context")
            try:
                from tool_factory.seed_plan.planning_pipeline import (
                    build_needle_safety_provenance,
                    _merge_embedded_hard_obstacles,
                    _resolve_data_tree_obstacle_labels,
                    _world_segment_hits_obstacle,
                    needle_safety_provenance_matches,
                )

                # Safety revalidation is meaningful only on the original CT
                # grid. During a cold restore the registry and verified
                # needle geometry are available before the large label arrays;
                # resampled/partial masks must not be treated as evidence that
                # a persisted, already-validated plan is unsafe.
                ct_data = agent.memory.retrieve("ct_data")
                ct_shape = tuple(np.asarray(ct_data).shape) if ct_data is not None else ()

                def _original_grid_mask(value):
                    if value is None or len(ct_shape) != 3:
                        return None
                    candidate = np.asarray(value)
                    if candidate.ndim != 3 or tuple(candidate.shape) != ct_shape:
                        return None
                    return candidate

                # Planning validates the normalized binary CTV and merges
                # model-emitted hard anatomy into the OAR mask.  Reusing the
                # full multi-label CTV here made a restart validate against a
                # different representation than the one that produced the
                # persisted geometry.
                candidate_ctv = agent._get_label_array("ctv_array")
                if candidate_ctv is None:
                    candidate_ctv = agent._get_label_array("ctv_label_data")
                if candidate_ctv is None:
                    candidate_ctv = agent._get_label_array("ctv_full_labels")
                candidate_oar = agent._get_label_array("oar_array")
                safety_ctv = _original_grid_mask(candidate_ctv)
                safety_oar = _original_grid_mask(candidate_oar)
                if safety_ctv is not None and safety_oar is not None:
                    safety_oar, embedded_labels = _merge_embedded_hard_obstacles(safety_oar, agent)
                    obstacle_labels, obstacle_source = _resolve_data_tree_obstacle_labels(agent)
                    obstacle_labels.update(embedded_labels)
                    world_validator = _world_segment_hits_obstacle
                    current_safety_context = build_needle_safety_provenance(
                        ct_image,
                        safety_ctv,
                        safety_oar,
                        obstacle_labels,
                        obstacle_source=obstacle_source,
                        agent=agent,
                    )
                    if isinstance(stored_safety_context, dict):
                        if current_safety_context is None:
                            safety_state = "deferred"
                        elif needle_safety_provenance_matches(
                            stored_safety_context,
                            current_safety_context,
                        ):
                            safety_state = "verified"
                        else:
                            # The active Planning was accepted against a
                            # different segmentation or obstacle policy.
                            # Keep the immutable geometry visible for review,
                            # but never present it as current-safe.
                            safety_state = "stale"
                            safety_warning = (
                                "Needle geometry was validated against an earlier "
                                "CT/CTV/OAR/obstacle state. It is shown for review "
                                "only; re-plan before clinical use."
                            )
                            logger.warning(
                                "[seeds_3d] Persisted needle geometry is stale relative to current planning inputs"
                            )
                else:
                    logger.info(
                        "[seeds_3d] Deferring display-time safety recheck until original-grid CTV/OAR masks are hydrated"
                    )
            except Exception:
                # A restore-time absence is an intermediate state. The plan
                # already carries validated geometry; wait for the original
                # masks instead of deleting its Data Tree representation.
                logger.warning("[seeds_3d] Display-time safety recheck deferred", exc_info=True)

            if not isinstance(stored_safety_context, dict) and verified_needle_geometry:
                # Older workspaces persisted the geometry but not the input
                # provenance. It was already accepted by the planning
                # pipeline, so keep it visible after restart while making the
                # missing provenance explicit. Manual edits still use the
                # current validator below and therefore remain fail-closed.
                safety_state = "legacy_verified"
                safety_warning = (
                    "Needle geometry comes from a legacy plan without persisted "
                    "input provenance. It is shown for review only; re-plan "
                    "before clinical use."
                )

            def _current_needle_is_safe(points):
                # Manual geometry must always be checked against the current
                # original-grid masks. Missing masks are not evidence of
                # safety for an edit.
                if world_validator is None:
                    return False
                return not world_validator(
                    points, ct_image, safety_ctv, safety_oar, obstacle_labels
                )

            def _automatic_needle_is_safe(points):
                # A persisted automatic geometry is already validated. A
                # changed-input or legacy state is review-only, so preserve
                # the geometry for the Viewer while exposing the stale state
                # to the UI and keeping clinical edit paths fail-closed.
                if safety_state in {"deferred", "stale", "legacy_verified"}:
                    return True
                return _current_needle_is_safe(points)

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

            # A manual edit intentionally leaves the automatic ``seed_plan``
            # immutable so the dose route can subtract its original per-seed
            # maps.  The renderer must nevertheless use the active manual
            # mirror. Previously this preferred ``seed_plan`` unconditionally,
            # so a successful seed drag was redrawn as the old algorithm plan
            # after any Viewer reload.
            if has_manual_geometry:
                # The automatic seed_plan remains immutable for incremental
                # dose replacement.  It is never the active geometry after a
                # manual edit; use the durable manual mirror for every Viewer
                # rebuild, including a session hydration.
                plan_source = manual_plan_serialized or seed_plan_serialized
            else:
                plan_source = (
                    seed_plan
                    if seed_plan is not None
                    else seed_plan_serialized
                )
            for i, entry in enumerate(plan_source):
                explicit_needle_points = None
                trajectory_id = f"traj_{i + 1}"
                needle_id = f"needle_{i + 1}"
                if isinstance(entry, dict):
                    seed_list = entry.get("seeds") or []
                    if has_manual_geometry:
                        trajectory_id = entry.get("trajectory_id", entry.get("id", trajectory_id))
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
                        # Manual records carry their own durable IDs. The
                        # automatic storage plan is zero-based internally, but
                        # every public Viewer/API identity is one-based.
                        "id": (
                            str(seed.get("id") or f"seed_{i + 1}_{j + 1}")
                            if has_manual_geometry and isinstance(seed, dict)
                            else f"seed_{i + 1}_{j + 1}"
                        ),
                        "position": pos_world.tolist(),
                        "voxel_index": _world_to_ct_voxel_index(pos_world),
                        "direction": direc_world.tolist(),
                        "trajectory_id": (
                            seed.get("trajectory_id", trajectory_id)
                            if has_manual_geometry and isinstance(seed, dict)
                            else trajectory_id
                        ),
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
                    if len(explicit_points) != 2 or not _current_needle_is_safe(explicit_points):
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
                    if not _automatic_needle_is_safe(points):
                        logger.error(
                            "[seeds_3d] Withholding needle_%s because current Data Tree obstacles reject its geometry",
                            i,
                        )
                        continue
                    needles.append({
                        "id": f"needle_{i + 1}",
                        "points": [point.tolist() for point in points],
                        "trajectory_id": trajectory_id,
                    })
                except Exception:
                    logger.warning(
                        "[seeds_3d] Withholding automatic needle_%s because no validated geometry is available; re-run planning.",
                        i,
                    )

            logger.info(f"[seeds_3d] returning {len(seeds)} seeds, {len(needles)} needles")
            artifact_status = {}
            for status_source in (
                agent.memory.retrieve("structure_artifact_status"),
                agent.memory.retrieve("manual_artifact_status"),
            ):
                if isinstance(status_source, dict):
                    artifact_status.update(status_source)
            if safety_state in {"stale", "legacy_verified"}:
                artifact_status["planning"] = "stale"
                if safety_warning:
                    artifact_status["reason"] = safety_warning
            return jsonify({
                "success": True,
                "seeds": seeds,
                "needles": needles,
                "seed_geometry": seed_geometry,
                "total_seeds": len(seeds),
                "total_needles": len(needles),
                "planning_id": (
                    agent.memory.retrieve("manual_planning_id")
                    or agent.memory.retrieve("active_planning_id")
                    or agent.memory.retrieve("planning_run_id")
                ),
                "planning_version": int(agent.memory.retrieve("manual_plan_version") or 0),
                "artifact_status": artifact_status,
                "safety_check": safety_state,
                "safety_warning": safety_warning,
                "plan_needs_replan": safety_state in {"stale", "legacy_verified"},
            })
        except Exception as e:
            logger.error(f"Seed 3D data failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500
