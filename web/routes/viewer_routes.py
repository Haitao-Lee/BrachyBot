"""Viewer and 3D visualization routes for the BrachyBot web API."""

import json
import logging
import os
import time
import threading
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import SimpleITK as sitk
from flask import Response, current_app, jsonify, request, send_from_directory, session as flask_session

from web.auth import current_user

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


def register_viewer_routes(app, get_agent, load_ct_image, extract_dicom_tags):
    def owned_case_path(path: str) -> bool:
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        session_id = str(flask_session.get("bb_session_id") or "")
        return bool(user and session_id and store.owns_path(user["id"], session_id, path))

    @app.route("/api/viewer/load", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_load():
        """Load CT image and return slice metadata (no pixel data)."""
        agent = get_agent()
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

        # Per-patient memory isolation: if a DIFFERENT CT is being
        # loaded, wipe all planning / segmentation / dose state from
        # the previous patient. The agent otherwise happily reuses
        # stale CTV/OAR/planning data from a previous case, which
        # causes wrong masks, wrong seeds, and confusing reports.
        # The user's expectation: same CT path → reuse memory
        # (continuing work on the same patient); different CT path
        # → fresh start.
        prev_ct_path = agent.memory.retrieve("ct_path")
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
            agent.memory.store("ct_source_kind", kind)

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
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

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
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

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

            response = Response(raw_bytes, mimetype='application/octet-stream')
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
        """Return full CTV/OAR label volumes as binary uint8 for client-side rendering."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import numpy as np
            import json as _json

            # Use full multi-label array for CTV (includes tumor, artery, vein, pancreas, etc.)
            # Falls back to binary ctv_array if full labels not available
            ctv_full = agent._get_label_array("ctv_full_labels")
            if ctv_full is None:
                ctv_full = agent._get_label_array("ctv_array")
            oar_array = agent._get_label_array("oar_array")

            # Reorganize labels for data tree:
            # - CTV node: only tumor (label 1)
            # - OAR non-traversable: artery (label 2), vein (label 3) from nnUNet
            # - OAR traversable: pancreas (label 4) from nnUNet
            ctv_array = None
            if ctv_full is not None:
                # CTV = only tumor
                ctv_array = (ctv_full == 1).astype(np.uint8) if np.any(ctv_full == 1) else None

                # Merge nnUNet vessel/organ labels into OAR array
                nnunet_oar_labels = {
                    2: 201,   # artery -> OAR label 201
                    3: 202,   # vein -> OAR label 202
                    4: 203,   # pancreas -> OAR label 203
                }
                has_nnunet_oar = False
                for src_label, dst_label in nnunet_oar_labels.items():
                    if np.any(ctv_full == src_label):
                        has_nnunet_oar = True
                        break

                if has_nnunet_oar:
                    if oar_array is None:
                        oar_array = np.zeros_like(ctv_full, dtype=np.uint8)
                    elif oar_array.shape != ctv_full.shape:
                        # Shape mismatch - likely orientation issue
                        # Skip merging to avoid IndexError
                        logger.warning(f"[label_volume] OAR shape {oar_array.shape} != CTV shape {ctv_full.shape}, skipping nnUNet label merge")
                        has_nnunet_oar = False  # Disable the merge below

                    if has_nnunet_oar:
                        for src_label, dst_label in nnunet_oar_labels.items():
                            mask = ctv_full == src_label
                            if np.any(mask):
                                oar_array[mask] = dst_label

            shape = ct_data.shape  # (Z, Y, X)

            # Ensure label arrays have same shape as CT
            if ctv_array is not None and ctv_array.shape != shape:
                logger.warning(f"CTV shape mismatch: {ctv_array.shape} vs CT {shape}, resampling...")
                import SimpleITK as sitk
                ctv_sitk = sitk.GetImageFromArray(ctv_array.astype(np.uint8))
                ct_ref = agent.memory.retrieve("ct_image")
                if ct_ref is not None:
                    resampler = sitk.ResampleImageFilter()
                    resampler.SetReferenceImage(ct_ref)
                    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
                    resampler.SetDefaultPixelValue(0)
                    ctv_array = sitk.GetArrayFromImage(resampler.Execute(ctv_sitk))

            if oar_array is not None and oar_array.shape != shape:
                logger.warning(f"OAR shape mismatch: {oar_array.shape} vs CT {shape}, resampling...")
                import SimpleITK as sitk
                oar_sitk = sitk.GetImageFromArray(oar_array.astype(np.uint8))
                ct_ref = agent.memory.retrieve("ct_image")
                if ct_ref is not None:
                    resampler = sitk.ResampleImageFilter()
                    resampler.SetReferenceImage(ct_ref)
                    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
                    resampler.SetDefaultPixelValue(0)
                    oar_array = sitk.GetArrayFromImage(resampler.Execute(oar_sitk))

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
                oar_u8 = oar_array.astype(np.uint8)
                payload.extend(oar_u8.tobytes())

            response = Response(bytes(payload), mimetype='application/octet-stream')
            response.headers['X-Shape-Z'] = str(shape[0])
            response.headers['X-Shape-Y'] = str(shape[1])
            response.headers['X-Shape-X'] = str(shape[2])
            response.headers['X-Color-LUT'] = _json.dumps(color_lut)
            response.headers['X-Has-CTV'] = 'true' if ctv_array is not None else 'false'
            response.headers['X-Has-OAR'] = 'true' if oar_array is not None else 'false'
            response.headers['X-CTV-Size'] = str(ctv_offset)
            response.headers['X-OAR-Size'] = str(len(payload) - ctv_offset) if oar_array is not None else '0'

            # Send CTV label names from model (not hardcoded in frontend)
            ctv_label_map = agent.memory.retrieve("ctv_label_map", {})
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

            # Also return organ metadata for data tree
            organ_names = agent.memory.retrieve("organ_names", {})
            organ_counts = agent.memory.retrieve("organ_counts", {})
            # Add nnUNet-derived OAR label names
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
                            "name": organ_names.get(lid_int, f"Organ_{lid_int}"),
                            "color": color_lut.get(lid_int, [200, 200, 200]),
                            "voxels": int(organ_counts.get(lid_int, np.sum(oar_array == lid))),
                        }
            response.headers['X-Organ-Meta'] = _json.dumps(organ_meta)

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
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

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
            if overlay_type == "ctv":
                mask_data = agent._get_label_array("ctv_array")
            else:
                mask_data = agent._get_label_array("oar_array")

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
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        organ_names = agent.memory.retrieve("organ_names", {})
        organ_counts = agent.memory.retrieve("organ_counts", {})

        # If organ_names is empty but oar_array exists, generate from array
        if not organ_names:
            oar_array = agent._get_label_array("oar_array")
            if oar_array is not None:
                import numpy as np
                try:
                    from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
                except ImportError:
                    TOTALSEG_LABEL_MAPPING = {}
                organ_counts_generated = {}
                organ_names_generated = {}
                unique_labels = np.unique(oar_array)
                for label in unique_labels:
                    if label > 0:
                        label_int = int(label)
                        organ_counts_generated[label_int] = int(np.sum(oar_array == label))
                        organ_names_generated[label_int] = TOTALSEG_LABEL_MAPPING.get(
                            label_int, f"organ_{label_int}"
                        )
                organ_names = organ_names_generated
                organ_counts = organ_counts_generated
                # Store for future use
                agent.memory.store("organ_names", organ_names)
                agent.memory.store("organ_counts", organ_counts)

        organs = {}
        for label_id, name in organ_names.items():
            label_int = int(label_id) if isinstance(label_id, str) else label_id
            organs[str(label_int)] = {
                "name": name,
                "voxel_count": organ_counts.get(label_int, organ_counts.get(str(label_int), 0))
            }

        return jsonify({"success": True, "organs": organs})

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
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

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
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

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
            cache_key = (source, label_id, str(smoothing_key), mask_shape_key, total_voxels, mask_digest)
            with _MESH_CACHE_LOCK:
                cached = _MESH_CACHE.get(cache_key)
            if cached is not None:
                cached_payload = dict(cached)
                cached_payload["cached"] = True
                return jsonify(cached_payload)

            # Adaptive preprocessing based on mask density
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

            # Smooth mesh vertices
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
                "length": _positive_geometry_value("length", 3.7),
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
                if isinstance(entry, dict):
                    seed_list = entry.get("seeds") or []
                    trajectory_id = entry.get("trajectory_id", entry.get("id", i))
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
                        "id": f"seed_{i}_{j}",
                        "position": pos_world.tolist(),
                        "voxel_index": _world_to_ct_voxel_index(pos_world),
                        "direction": direc_world.tolist(),
                        "trajectory_id": trajectory_id,
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
                        "id": f"needle_{i}",
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
            })
        except Exception as e:
            logger.error(f"Seed 3D data failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500
