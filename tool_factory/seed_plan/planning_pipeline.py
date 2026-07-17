"""
Brachytherapy Planning Pipeline
================================
Unified orchestrator that uses the Zhiyuan v2 planning algorithm.

Supports both full pipeline and individual step invocation.
Each step checks prerequisites and attempts auto-recovery.

Steps:
- trajectory_init: Generate candidate needle paths
- trajectory_refine: Filter trajectories by quality
- seed_planning: Optimize seed positions
- dose_calc: Calculate dose distribution
- dose_eval: Compute DVH metrics
- full: Run all steps in sequence
"""

import sys
import os
import json
import copy
import logging
import re
import numpy as np
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
from plans.dose_pre.model_loader import DOSE_MODEL_SCALE_GY

logger = logging.getLogger(__name__)

# Load default parameters from Zhiyuan config
PLANS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "plans")
CONFIG_PATH = os.path.join(PLANS_DIR, "config.json")

# Default planning parameters (from Zhiyuan config.json)
# Dose is in normalized units (matching Zhiyuan convention).
# in_lowest_energy=1.0 is the prescription dose threshold.
# No Gy conversion needed - all metrics use normalized units.
NEW_SLICES_ROUNDED = 64

# The Data tree and the planning backend must use the same default policy.
# Derive labels from TotalSegmentator names rather than fragile numeric lists.
_NON_TRAVERSABLE_NAME_PATTERNS = (
    r"bone|rib|skull|spine|vertebra|sacrum|sternum|pelvis|femur|humerus|scapula|"
    r"clavicula|hip|ilium|ischium|pubis",
    r"cartilage|disc|meniscus",
    r"aorta|vena\s*cava|iliac\s+(?:artery|vein|vena)|femoral\s*(?:artery|vein)|"
    r"carotid|jugular|artery|vein|vessel|brachiocephalic\s+trunk",
    r"nerve|plexus|sciatic|spinal\s*cord|brachial",
)


def _is_default_non_traversable_name(name: str) -> bool:
    normalized = str(name or "").replace("_", " ").lower()
    return any(re.search(pattern, normalized) for pattern in _NON_TRAVERSABLE_NAME_PATTERNS)


def _default_obstacle_label_ids():
    """Return TotalSegmentator labels classified as non-traversable by default."""
    try:
        from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
        return frozenset(
            int(label_id)
            for label_id, name in TOTALSEG_LABEL_MAPPING.items()
            if _is_default_non_traversable_name(name)
        )
    except Exception as exc:
        # Reduced test environments may omit TotalSegmentator dependencies.
        logger.warning("Unable to load TotalSegmentator label mapping: %s", exc)
        # Keep the safety default conservative if a lightweight environment
        # can read a previously generated OAR mask but cannot import the map.
        return frozenset(
            set(range(25, 51))
            | set(range(52, 61))
            | set(range(62, 69))
            | set(range(69, 80))
            | set(range(91, 118))
        )


# Keep the old public symbol for integrations that import it directly, while
# making its contents come from the authoritative TotalSegmentator mapping.
OBSTACLE_ORGAN_LABELS = _default_obstacle_label_ids()


def _resolve_data_tree_obstacle_labels(agent):
    """Resolve the current Data tree non-traversable OAR whitelist.

    The Data tree can add case-specific hard obstacles, while the default
    bone/cartilage/vessel baseline remains mandatory. A client-side category
    change must never silently downgrade those hard obstacles to traversable.
    CTV sub-labels are excluded because CTV labels 2 and 3 are always hard
    obstacles from the CTV mask itself.
    """
    defaults = set(OBSTACLE_ORGAN_LABELS or _default_obstacle_label_ids())
    if agent is None or not getattr(agent, "memory", None):
        return defaults, "default"
    try:
        ui_state = agent.memory.get_ui_state() or {}
    except Exception as exc:
        logger.debug("[OAR filter] UI state unavailable; using defaults: %s", exc)
        return defaults, "default"

    data_tree = ui_state.get("data_tree") if isinstance(ui_state, dict) else None
    organs = data_tree.get("organs") if isinstance(data_tree, dict) else None
    if not isinstance(organs, list):
        return defaults, "default"

    selected = set()
    usable_oar_entries = 0
    for item in organs:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "oar").strip().lower()
        item_id = str(item.get("id") or "").strip().lower()
        if source == "ctv" or item_id.startswith("ctv_"):
            continue
        try:
            label_id = int(item.get("label_id", item.get("labelId")))
        except (TypeError, ValueError):
            continue
        usable_oar_entries += 1
        category = str(item.get("category") or "traversable").strip().lower()
        if category == "non_traversable":
            selected.add(label_id)

    if not usable_oar_entries:
        logger.debug("[OAR filter] Data tree has no usable OAR labels; using defaults")
        return defaults, "default"
    resolved = defaults | selected
    logger.info(
        "[OAR filter] using mandatory baseline plus Data tree additions: %d hard labels "
        "(%d manually selected from %d OAR entries)",
        len(resolved), len(selected), usable_oar_entries,
    )
    return resolved, "data_tree_plus_default"


def _safe_dicom_orient(image, target_orientation='LPI', context=""):
    """Apply DICOMOrient with explicit logging on failure.

    The bare except: pass pattern is dangerous because a failed orientation
    leaves the image in its native frame, while labels stored via
    _store_label_with_metadata may assume LPI. We log the failure so that
    downstream misalignment is debuggable.
    """
    import SimpleITK as sitk
    try:
        return sitk.DICOMOrient(image, target_orientation)
    except Exception as e:
        logger.warning(
            f"DICOMOrient('{target_orientation}') failed{(' ' + context) if context else ''}: {e}. "
            f"Image kept in its native orientation — verify alignment if used with labels."
        )
        return image


def load_config() -> Dict:
    """Load planning configuration from Zhiyuan config.json."""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load config: {e}")
        return {}


CONFIG = load_config()


def _resample_for_planning(ct_image, ctv_mask, oar_mask, new_size=[128, 128, 64]):
    """Resample CT/CTV/OAR to planning grid size.

    The Zhiyuan algorithm operates on a resampled grid, not the original CT.
    This is critical for correct trajectory generation and dose calculation.

    Args:
        ct_image: SimpleITK image of CT
        ctv_mask: numpy array of CTV mask
        oar_mask: numpy array of OAR mask (or None)
        new_size: target size [x, y, z]

    Returns:
        (resampled_ct, resampled_ctv_array, resampled_oar_array)
    """
    import SimpleITK as sitk

    # Calculate new spacing to preserve physical size
    original_size = ct_image.GetSize()
    original_spacing = ct_image.GetSpacing()
    new_spacing = [
        original_size[0] * original_spacing[0] / new_size[0],
        original_size[1] * original_spacing[1] / new_size[1],
        original_size[2] * original_spacing[2] / new_size[2],
    ]

    # Resample CT (linear interpolation)
    resampler = sitk.ResampleImageFilter()
    resampler.SetSize(new_size)
    resampler.SetOutputSpacing(new_spacing)
    resampler.SetOutputDirection(ct_image.GetDirection())
    resampler.SetOutputOrigin(ct_image.GetOrigin())
    resampler.SetInterpolator(sitk.sitkLinear)
    resampled_ct = resampler.Execute(ct_image)

    # Resample CTV (nearest neighbor for labels)
    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
    ctv_sitk = sitk.GetImageFromArray(ctv_mask.astype(np.uint8))
    ctv_sitk.SetSpacing(ct_image.GetSpacing())
    ctv_sitk.SetOrigin(ct_image.GetOrigin())
    ctv_sitk.SetDirection(ct_image.GetDirection())
    resampled_ctv = resampler.Execute(ctv_sitk)

    # Resample OAR (nearest neighbor for labels)
    resampled_oar = None
    if oar_mask is not None:
        oar_sitk = sitk.GetImageFromArray(oar_mask.astype(np.uint8))
        oar_sitk.SetSpacing(ct_image.GetSpacing())
        oar_sitk.SetOrigin(ct_image.GetOrigin())
        oar_sitk.SetDirection(ct_image.GetDirection())
        resampled_oar = resampler.Execute(oar_sitk)

    resampled_ctv_array = sitk.GetArrayFromImage(resampled_ctv)
    resampled_oar_array = sitk.GetArrayFromImage(resampled_oar) if resampled_oar is not None else None

    return resampled_ct, resampled_ctv_array, resampled_oar_array


def _convert_ref_direc_to_voxel(ref_direc_ras, ct_image):
    """Convert the legacy LPS planning direction to voxel space.

    This is critical because the planning algorithm operates in voxel space.
    The reference direction must be in the same coordinate system.

    Args:
        ref_direc_ras: 3-element direction in SimpleITK physical LPS. The
            argument name is retained for backward compatibility.
        ct_image: SimpleITK image with direction/spacing metadata

    Returns:
        3-element direction in voxel space
    """
    from plans.utilizations import ras_direction_to_voxel
    return ras_direction_to_voxel(np.array(ref_direc_ras), ct_image)


# ----------------------------------------------------------------------
# Reference direction resolution
# ----------------------------------------------------------------------
# Sentinel values for ``ref_direc`` resolution:
#   - list/tuple/array of 3 numbers  → use as-is (legacy LPS, normalized)
#   - "auto" or None                  → organ-aware default from _ORGAN_DEFAULT_REFDIREC
#                                        (falls back to global config, then "auto_detect")
#   - "auto_detect"                   → geometric detection from CTV center to skin
#                                        (slowest but most adaptive)
# ----------------------------------------------------------------------

# Organ-specific legacy LPS approach vectors. Their numeric values are part of
# the deployed coordinate contract and are validated with the current viewer
# and planning transforms. Do not reinterpret them as true RAS vectors or flip
# individual axes without a versioned end-to-end migration.
_ORGAN_DEFAULT_REFDIREC = {
    "pancreas":  [0.0, -1.0, 0.0],
    "pancreatic": [0.0, -1.0, 0.0],
    "liver":     [1.0, 0.0, 0.0],
    "prostate":  [0.0, -1.0, 0.0],
    "lung":      [0.0, 1.0, 0.0],
    "kidney":    [0.0, -1.0, 0.0],
    "colon":     [0.0, -1.0, 0.0],
    "head_neck": [0.0, 0.0, 1.0],
    "btcv":      [0.0, 0.0, 1.0],
    "brats21":   [0.0, 0.0, 1.0],
}

# Global default if no organ hint is available. Keep this aligned with the
# persisted planning setting and the manual Web UI default.
_GLOBAL_DEFAULT_REFDIREC = [0.0, 1.0, 0.0]


def _normalize_ref_direc(d):
    """Normalize a 3-vector, returning the global default if degenerate."""
    d = np.asarray(d, dtype=np.float64).reshape(-1)
    if d.size != 3 or not np.all(np.isfinite(d)):
        return np.array(_GLOBAL_DEFAULT_REFDIREC, dtype=np.float64)
    n = np.linalg.norm(d)
    if n < 1e-9:
        return np.array(_GLOBAL_DEFAULT_REFDIREC, dtype=np.float64)
    return d / n


def _get_organ_hint(agent) -> Optional[str]:
    """Look up the active tumor type from agent memory (best-effort)."""
    if not agent:
        return None
    mem = getattr(agent, "memory", None)
    if mem is None:
        return None
    for key in ("tumor_type_used", "tumor_type", "anatomy"):
        v = mem.retrieve(key)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    return None


def _auto_detect_ref_direc(ct_image, ctv_mask) -> np.ndarray:
    """Pick the cardinal-axis approach direction with the shortest
    skin-to-CTV path.

    Algorithm:
      1. Get the CTV center-of-mass in world (mm) coordinates.
      2. For each of the 6 cardinal axes (±X, ±Y, ±Z in voxel space),
         walk from the CTV center outward to the body boundary (skin).
         The "skin" is approximated as the first non-air voxel when
         stepping away from the image center — but because CTs always
         include some background, we use a simple HU-based air threshold
         (< -500 HU) to mark the body.
      3. Pick the axis with the shortest skin-to-CTV distance; the
         approach direction is the unit vector from the CTV center
         toward the skin on that axis (i.e. pointing OUT of the body
         for needle insertion planning).

    Falls back to the global default if CTV/center cannot be computed.
    """
    import SimpleITK as sitk

    if ctv_mask is None or not np.any(ctv_mask > 0):
        return np.array(_GLOBAL_DEFAULT_REFDIREC, dtype=np.float64)

    # Prefer the validated body-shell calculation used by the reference
    # BrachyPlan workflow.  The legacy cardinal-ray implementation below is
    # retained only as a bounded fallback for lightweight environments that
    # lack the morphology dependencies.
    try:
        from plans.utilizations import compute_body_shell_and_ref_direction

        ct_array = sitk.GetArrayFromImage(ct_image)
        direction_matrix = np.asarray(ct_image.GetDirection(), dtype=np.float64).reshape(3, 3)
        spacing_zyx = np.asarray(ct_image.GetSpacing(), dtype=np.float64)[::-1]
        _, _, surface_kji, centroid_kji = compute_body_shell_and_ref_direction(
            ct_array,
            np.asarray(ctv_mask),
            spacing_zyx,
            target_value=1,
            direction_matrix=direction_matrix,
        )
        if surface_kji is not None and centroid_kji is not None:
            origin = np.asarray(ct_image.GetOrigin(), dtype=np.float64)
            spacing_xyz = np.asarray(ct_image.GetSpacing(), dtype=np.float64)
            surface_ijk = np.asarray(surface_kji, dtype=np.float64)[::-1]
            centroid_ijk = np.asarray(centroid_kji, dtype=np.float64)[::-1]
            surface_world = origin + direction_matrix.dot(surface_ijk * spacing_xyz)
            centroid_world = origin + direction_matrix.dot(centroid_ijk * spacing_xyz)
            direction = centroid_world - surface_world
            if np.linalg.norm(direction) > 1e-8:
                resolved = _normalize_ref_direc(direction)
                logger.info(
                    "[ref_direction] body-shell entry=%s ctv_center=%s vector=%s",
                    np.round(surface_world, 3).tolist(),
                    np.round(centroid_world, 3).tolist(),
                    np.round(resolved, 5).tolist(),
                )
                return resolved
    except Exception as exc:
        logger.warning("[ref_direction] body-shell detection unavailable; using ray fallback: %s", exc)

    try:
        # CTV center of mass in voxel indices (k, j, i)
        coords = np.argwhere(ctv_mask > 0)
        ctv_center_voxel = coords.mean(axis=0)  # shape (3,) in (k, j, i)
    except Exception as e:
        logger.warning(f"auto_detect_ref_direc: failed to compute CTV center: {e}")
        return np.array(_GLOBAL_DEFAULT_REFDIREC, dtype=np.float64)

    # Convert CTV center to physical (mm) coordinates
    spacing = np.array(ct_image.GetSpacing())            # (sx, sy, sz)  → (x, y, z) in mm
    origin = np.array(ct_image.GetOrigin())              # (ox, oy, oz)  in mm
    direction = np.array(ct_image.GetDirection()).reshape(3, 3)
    # ctv_center_voxel is (k, j, i); physical index is (i, j, k) in mm
    center_ijk = np.array([ctv_center_voxel[2],
                            ctv_center_voxel[1],
                            ctv_center_voxel[0]], dtype=np.float64)
    ctv_center_world = origin + direction @ (spacing * center_ijk)

    # Get CT array for HU-based body segmentation
    ct_array = sitk.GetArrayFromImage(ct_image)  # shape (k, j, i)
    body_mask = ct_array > -500  # soft tissue + bone

    # Image extent in world coords
    size = np.array(ct_image.GetSize())  # (nx, ny, nz) in (x, y, z)
    extent_world = origin + direction @ (spacing * (size - 1))
    max_world = np.maximum(origin, extent_world)

    # For each of 6 cardinal directions in WORLD space, find skin distance
    # from CTV center along that direction.
    best_axis = None
    best_dist = np.inf

    for axis_idx in range(3):
        for sign in (+1.0, -1.0):
            step = np.zeros(3, dtype=np.float64)
            step[axis_idx] = sign
            # Ray march from ctv_center outward along `step`
            # Sample at 1 mm intervals
            max_steps = int(np.linalg.norm(max_world - ctv_center_world) + 1)
            dist = 0.0
            found_skin = False
            for s in range(1, max_steps + 1):
                p = ctv_center_world + step * float(s)
                # Convert p back to voxel index
                rel = (p - origin)
                try:
                    inv_dir = np.linalg.inv(direction)
                    ijk_float = inv_dir @ (rel / spacing)
                except np.linalg.LinAlgError:
                    break
                i_idx = int(round(ijk_float[0]))
                j_idx = int(round(ijk_float[1]))
                k_idx = int(round(ijk_float[2]))
                if not (0 <= i_idx < size[0] and 0 <= j_idx < size[1] and 0 <= k_idx < size[2]):
                    break  # off the image
                if body_mask[k_idx, j_idx, i_idx]:
                    continue  # still inside body
                # Hit air (skin) — record distance
                dist = float(s)
                found_skin = True
                break
            if found_skin and dist > 0 and dist < best_dist:
                best_dist = dist
                # Approach direction: from skin toward CTV (inward), i.e. -sign
                best_axis = -sign * step

    if best_axis is None or best_dist == np.inf:
        return np.array(_GLOBAL_DEFAULT_REFDIREC, dtype=np.float64)

    return _normalize_ref_direc(best_axis)


def _resolve_ref_direc(ref_direc_input, ct_image, ctv_mask, agent) -> np.ndarray:
    """Resolve the user-supplied ref_direc into a concrete RAS unit vector.

    Resolution order:
      1. If ``ref_direc_input`` is a list/array → return it (normalized).
      2. If ``ref_direc_input`` is the string ``"auto_detect"`` →
         run geometric detection.
      3. Otherwise (None, "auto", or anything else) → look up the
         organ-specific default from agent memory; if that fails, run
         auto_detect as a last resort; if that also fails, fall back
         to the global default.

    Returns:
        3-element unit vector in RAS world space.
    """
    # Case 1: explicit numeric direction
    if ref_direc_input is not None and not isinstance(ref_direc_input, str):
        try:
            return _normalize_ref_direc(ref_direc_input)
        except Exception as e:
            logger.warning(f"_resolve_ref_direc: bad numeric input {ref_direc_input!r}: {e}")

    # Case 2: explicit auto_detect request
    if isinstance(ref_direc_input, str) and ref_direc_input.strip().lower() in {"auto", "auto_detect"}:
        logger.info("_resolve_ref_direc: running geometric auto-detection")
        return _auto_detect_ref_direc(ct_image, ctv_mask)

    # Case 3: organ-aware default
    organ = _get_organ_hint(agent)
    if organ and organ in _ORGAN_DEFAULT_REFDIREC:
        d = _ORGAN_DEFAULT_REFDIREC[organ]
        logger.info(f"_resolve_ref_direc: using organ default for {organ!r}: {d}")
        return _normalize_ref_direc(d)

    # Try geometric detection as a sensible fallback for unknown organs
    if ctv_mask is not None and np.any(ctv_mask > 0):
        logger.info(f"_resolve_ref_direc: no organ hint, running auto_detect")
        return _auto_detect_ref_direc(ct_image, ctv_mask)

    # Last resort
    logger.info(f"_resolve_ref_direc: using global default {_GLOBAL_DEFAULT_REFDIREC}")
    return _normalize_ref_direc(_GLOBAL_DEFAULT_REFDIREC)


def _load_dose_model(device=None):
    """Load the dose prediction model.

    The production planning path must use the same centralized device
    selection as the standalone dose engine. Keeping this argument injectable
    preserves deterministic CPU tests while the normal pipeline selects the
    best available GPU and only falls back to CPU when CUDA is unavailable.

    Returns:
        (model, error_message) - model is None if loading failed
    """
    from plans.dose_pre.model_loader import load_dose_model
    if device is None:
        from plans.device_manager import get_device
        device = get_device(caller="planning_pipeline_dose")
    logger.info("[dose_model] loading dose_unet_spacing1mm on %s", device)
    model, error, _ = load_dose_model(device=device)
    return model, error


def _build_radiation_volume(
    ctv_mask,
    oar_mask,
    target_value=1,
    obstacle_value=2,
    obstacle_labels=None,
    obstacle_source="default",
):
    """Build radiation volume from CTV and OAR masks.

    CTV mask from nnUNet pancreatic segmentation:
        1 = tumor (target)
        2 = artery (obstacle)
        3 = vein (obstacle)
        4 = pancreas (background, not target)
    Only label 1 (tumor) is the target for planning.

    OAR mask (from TotalSegmentator) is filtered through OBSTACLE_ORGAN_LABELS
    so soft organs (lung, liver, kidney, spleen, muscle) do NOT block the path —
    they are physically traversable for a trans-abdominal / posterior needle.
    Only vessels, bowel, bone and a few critical soft structures become obstacles.
    """
    radiation_volume = np.zeros_like(ctv_mask, dtype=np.int32)
    # Only tumor (label 1) is the target
    radiation_volume[ctv_mask == 1] = target_value
    # Artery and vein are obstacles (non-traversable) — handled directly from CTV mask
    radiation_volume[(ctv_mask == 2) | (ctv_mask == 3)] = obstacle_value
    # OAR from TotalSegmentator (if provided): apply the current whitelist.
    if oar_mask is not None:
        selected_labels = set(
            OBSTACLE_ORGAN_LABELS if obstacle_labels is None else obstacle_labels
        )
        total_oar_voxels = int((oar_mask > 0).sum())
        obstacle_mask = np.isin(oar_mask, list(selected_labels))
        filtered_voxels = int(obstacle_mask.sum())
        radiation_volume[obstacle_mask & (radiation_volume == 0)] = obstacle_value
        logger.info(
            f"[OAR filter:{obstacle_source}] blocking voxels: {filtered_voxels} / {total_oar_voxels} "
            f"total OAR ({total_oar_voxels - filtered_voxels} non-blocking skipped)"
        )
        # Warn if OAR mask has labels beyond TotalSegmentator v2's 117
        # — whitelist may not cover them, so they would not be treated as obstacles.
        try:
            max_label = int(oar_mask.max())
        except Exception:
            max_label = 0
        if max_label > 117:
            logger.warning(
                f"[OAR filter] OAR mask contains labels up to {max_label} (TotalSegmentator v2 max = 117). "
                f"Labels outside the whitelist will be treated as non-obstacles."
            )
    return radiation_volume


def _trajectory_path_hits_obstacle(trajectory, radiation_volume, obstacle_value, extra_forward_voxels=3.0):
    """Return True when the sampled needle path intersects an obstacle voxel.

    The legacy depth routine only used an obstacle found on the reverse scan
    to reject a candidate.  Its forward scan stopped at an obstacle but still
    returned the trajectory, which allowed a displayed or inserted needle to
    cross the far side of a non-traversable structure.  This check samples the
    complete usable segment in planning-grid coordinates in both directions.
    The planning coordinate convention is unchanged: points are array-order
    ``[z, y, x]`` and the direction is the trajectory's existing voxel vector.
    """
    if radiation_volume is None or not isinstance(trajectory, (list, tuple)) or len(trajectory) < 2:
        return True
    try:
        point = np.asarray(trajectory[0], dtype=np.float64).reshape(-1)[:3]
        direction = np.asarray(trajectory[1], dtype=np.float64).reshape(-1)[:3]
        if point.size != 3 or direction.size != 3 or not np.all(np.isfinite(point + direction)):
            return True
        major = float(np.max(np.abs(direction)))
        if major <= 1e-12:
            return True
        direction = direction / major
        # The reverse side must be clear to the image boundary.  The forward
        # side covers the recorded target/background path plus a small tip
        # margin, without changing the existing coordinate transform.
        backward_limit = float(max(radiation_volume.shape)) * 2.0 + 2.0
        forward_lengths = []
        for idx in (2, 3):
            values = trajectory[idx] if len(trajectory) > idx else []
            if isinstance(values, (list, tuple, np.ndarray)):
                forward_lengths.extend(float(v) for v in values if np.isfinite(v))
        forward_limit = max(float(sum(forward_lengths)) + float(extra_forward_voxels), float(extra_forward_voxels))
        samples = np.arange(-backward_limit, forward_limit + 0.125, 0.25, dtype=np.float64)
        coords = point[None, :] + samples[:, None] * direction[None, :]
        inside = np.all((coords >= 0.0) & (coords < np.asarray(radiation_volume.shape, dtype=np.float64)), axis=1)
        if not np.any(inside):
            return True
        indices = np.floor(coords[inside]).astype(np.int64)
        values = radiation_volume[indices[:, 0], indices[:, 1], indices[:, 2]]
        return bool(np.any(values == obstacle_value))
    except Exception:
        # A malformed trajectory must never bypass the safety gate.
        logger.exception("[obstacle_check] Failed to validate trajectory")
        return True


def _filter_safe_trajectories(trajectories, radiation_volume, obstacle_value):
    """Keep only trajectories whose complete usable path is obstacle-free."""
    safe = []
    rejected = 0
    for trajectory in trajectories or []:
        if _trajectory_path_hits_obstacle(trajectory, radiation_volume, obstacle_value):
            rejected += 1
        else:
            safe.append(trajectory)
    if rejected:
        logger.warning("[obstacle_check] rejected %d/%d trajectories that intersect non-traversable voxels", rejected, len(trajectories or []))
    return safe


def _needle_extension_mm():
    """Return the configured physical insertion length for automatic needles."""
    try:
        from plans.config import setting
        length = float(setting().module_constants.get("DIRECTION_EXTENSION", 150.0))
    except Exception:
        length = 150.0
    if not np.isfinite(length) or length <= 0.0:
        logger.warning("[needle_safety] Invalid needle extension %r; using 150 mm", length)
        return 150.0
    return length


def _trajectory_forward_steps(trajectory, tip_margin_voxels=3.0):
    """Return a conservative forward extent in the trajectory grid convention."""
    lengths = []
    for index in (2, 3):
        values = trajectory[index] if len(trajectory) > index else []
        if not isinstance(values, (list, tuple, np.ndarray)):
            continue
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if np.isfinite(number) and number > 0.0:
                lengths.append(number)
    return max(float(sum(lengths)) + float(tip_margin_voxels), float(tip_margin_voxels))


def _candidate_world_needle_points(trajectory, planning_image, extension_mm=None):
    """Build the full physical needle segment represented by a trajectory.

    The segment keeps the established 150 mm outside-to-deep-target strategy.
    It deliberately uses the same array-order [z, y, x] to world transform as
    seed generation, so safety validation does not introduce another coordinate
    chain.
    """
    if planning_image is None or not isinstance(trajectory, (list, tuple)) or len(trajectory) < 2:
        return None
    try:
        from plans import utilizations

        point = np.asarray(trajectory[0], dtype=np.float64).reshape(-1)[:3]
        direction = np.asarray(trajectory[1], dtype=np.float64).reshape(-1)[:3]
        if point.size != 3 or direction.size != 3 or not np.all(np.isfinite(point + direction)):
            return None
        major = float(np.max(np.abs(direction)))
        if major <= 1e-12:
            return None
        voxel_direction = direction / major
        world_direction = np.asarray(
            utilizations.direction_transform(planning_image, direction), dtype=np.float64
        ).reshape(-1)[:3]
        world_norm = float(np.linalg.norm(world_direction))
        if world_norm <= 1e-12:
            return None
        world_direction /= world_norm
        anchor_world = np.asarray(
            utilizations.position_transform(planning_image, point)[0], dtype=np.float64
        )
        deep_voxel = point + _trajectory_forward_steps(trajectory) * voxel_direction
        deep_world = np.asarray(
            utilizations.position_transform(planning_image, deep_voxel)[0], dtype=np.float64
        )
        extension = _needle_extension_mm() if extension_mm is None else float(extension_mm)
        return [deep_world, anchor_world - extension * world_direction]
    except Exception:
        logger.exception("[needle_safety] Unable to build candidate world needle segment")
        return None


def _seed_plan_entry_needle_points(entry, extension_mm=None):
    """Return the exact world-coordinate needle geometry displayed for a plan entry."""
    try:
        if isinstance(entry, dict):
            seeds = entry.get("seeds") or []
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            seeds = entry[1] or []
        else:
            return None

        positions = []
        direction = None
        for seed in seeds:
            if isinstance(seed, dict):
                position = seed.get("position") or seed.get("pos")
                seed_direction = seed.get("direction") or seed.get("dir")
            elif isinstance(seed, (list, tuple)) and len(seed) >= 2:
                position, seed_direction = seed[0], seed[1]
            else:
                continue
            point = np.asarray(position, dtype=np.float64).reshape(-1)[:3]
            vector = np.asarray(seed_direction, dtype=np.float64).reshape(-1)[:3]
            if point.size != 3 or vector.size != 3 or not np.all(np.isfinite(point + vector)):
                continue
            positions.append(point)
            direction = vector

        if not positions or direction is None:
            return None
        direction_norm = float(np.linalg.norm(direction))
        if direction_norm <= 1e-12:
            return None
        direction /= direction_norm
        extension = _needle_extension_mm() if extension_mm is None else float(extension_mm)
        if len(positions) == 1:
            return [positions[0], positions[0] - extension * direction]

        positions = np.asarray(positions, dtype=np.float64)
        origin = positions[0]
        projections = np.dot(positions - origin, direction)
        shallow = origin + float(np.min(projections)) * direction
        deep = origin + float(np.max(projections)) * direction
        return [deep, shallow - extension * direction]
    except Exception:
        logger.exception("[needle_safety] Unable to build final world needle segment")
        return None


def _world_segment_hits_obstacle(
    points,
    ct_image,
    ctv_mask,
    oar_mask,
    obstacle_labels,
    sample_spacing_mm=0.75,
):
    """Check the complete physical needle segment against original-grid hard masks.

    Planning candidates are built on a resampled grid, whereas the rendered
    needle uses patient-world coordinates and a 150 mm external extension.
    This validator samples that exact world segment and maps each point back
    through SimpleITK's canonical physical-to-index transform. No RAS/LPS flip
    or hand-written voxel transform is introduced here.
    """
    if ct_image is None or points is None or len(points) != 2:
        return True
    try:
        start = np.asarray(points[0], dtype=np.float64).reshape(-1)[:3]
        end = np.asarray(points[1], dtype=np.float64).reshape(-1)[:3]
        if start.size != 3 or end.size != 3 or not np.all(np.isfinite(start + end)):
            return True
        reference_shape = tuple(int(value) for value in reversed(ct_image.GetSize()))
        ctv = None if ctv_mask is None else np.asarray(ctv_mask)
        oar = None if oar_mask is None else np.asarray(oar_mask)
        if ctv is None and oar is None:
            logger.error("[needle_safety] No original-grid masks available for final needle validation")
            return True
        if ctv is not None and tuple(ctv.shape) != reference_shape:
            logger.error("[needle_safety] CTV shape %s does not match CT shape %s", ctv.shape, reference_shape)
            return True
        if oar is not None and tuple(oar.shape) != reference_shape:
            logger.error("[needle_safety] OAR shape %s does not match CT shape %s", oar.shape, reference_shape)
            return True

        distance = float(np.linalg.norm(end - start))
        # Use at most half of the smallest original voxel spacing. A fixed
        # 0.75 mm step could skip a thin oblique intersection in sub-mm CT.
        # The 0.25 mm floor caps work for unusually high-resolution scans.
        min_spacing = float(np.min(np.abs(np.asarray(ct_image.GetSpacing(), dtype=np.float64))))
        effective_step = min(
            max(float(sample_spacing_mm), 0.25),
            max(min_spacing * 0.5, 0.25),
        )
        count = max(2, int(np.ceil(distance / effective_step)) + 1)
        label_ids = set(int(label) for label in (obstacle_labels or ()))
        size_xyz = np.asarray(ct_image.GetSize(), dtype=np.float64)
        for fraction in np.linspace(0.0, 1.0, count, dtype=np.float64):
            world = start + fraction * (end - start)
            index_xyz = np.asarray(
                ct_image.TransformPhysicalPointToContinuousIndex(tuple(float(value) for value in world)),
                dtype=np.float64,
            )
            # The external portion is allowed to be outside the CT field of view.
            if np.any(index_xyz < 0.0) or np.any(index_xyz > (size_xyz - 1.0)):
                continue
            x, y, z = np.rint(index_xyz).astype(np.int64)
            if ctv is not None and int(ctv[z, y, x]) in (2, 3):
                return True
            if oar is not None and int(oar[z, y, x]) in label_ids:
                return True
        return False
    except Exception:
        logger.exception("[needle_safety] Original-grid obstacle validation failed")
        return True


def _filter_world_safe_trajectories(
    trajectories,
    planning_image,
    ct_image,
    ctv_mask,
    oar_mask,
    obstacle_labels,
):
    """Reject candidates whose full 150 mm physical needle intersects hard masks."""
    safe = []
    rejected = 0
    extension = _needle_extension_mm()
    for trajectory in trajectories or []:
        points = _candidate_world_needle_points(trajectory, planning_image, extension)
        if _world_segment_hits_obstacle(points, ct_image, ctv_mask, oar_mask, obstacle_labels):
            rejected += 1
        else:
            safe.append(trajectory)
    if rejected:
        logger.warning(
            "[needle_safety] rejected %d/%d candidates after full %.1f mm physical needle validation",
            rejected, len(trajectories or []), extension,
        )
    return safe


def _validated_needle_geometry(plan_res, ct_image, ctv_mask, oar_mask, obstacle_labels):
    """Return display geometry only when every final automatic needle is safe."""
    geometry = {}
    unsafe_indices = []
    extension = _needle_extension_mm()
    for index, entry in enumerate(plan_res or []):
        points = _seed_plan_entry_needle_points(entry, extension)
        if _world_segment_hits_obstacle(points, ct_image, ctv_mask, oar_mask, obstacle_labels):
            unsafe_indices.append(index)
            continue
        geometry[str(index)] = [point.tolist() for point in points]
    return geometry, unsafe_indices


class PlanningPipelineTool(BaseTool):
    """
    Unified brachytherapy planning pipeline orchestrator.

    Uses the Zhiyuan v2 planning algorithm:
    1. Resample CT/CTV/OAR to [128, 128, 64] planning grid
    2. Convert reference direction from RAS to voxel space
    3. Run brachy_plan_v2 (init_plan -> optimal_plan)
    4. Transform seeds back to world coordinates
    5. Calculate dose distribution

    Supports both full pipeline and individual step invocation.
    Each step checks prerequisites and attempts auto-recovery.
    """

    @property
    def name(self) -> str:
        return "planning_pipeline"

    @property
    def description(self) -> str:
        return (
            "Execute brachytherapy planning pipeline using Zhiyuan v2 algorithm. "
            "Supports full pipeline or individual steps: "
            "trajectory_init, trajectory_refine, seed_planning, dose_calc, dose_eval. "
            "Each step auto-checks prerequisites and attempts recovery."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "ct_image_path": {
                    "type": "string",
                    "description": "Path to CT image file (.nii.gz). If not provided, uses CT from agent memory.",
                },
                "ctv_mask_path": {
                    "type": "string",
                    "description": "Path to CTV mask file (.nii.gz). If not provided, uses CTV from agent memory.",
                },
                "oar_mask_path": {
                    "type": "string",
                    "description": "Path to OAR mask file (.nii.gz, optional).",
                },
                "step": {
                    "type": "string",
                    "description": "Which planning step to run. Default 'trajectory_init'. For full pipeline in one call, use 'full' (runs all 5 steps; intermediate state not inspectable). For stepwise inspection, call each step in order: trajectory_init → trajectory_refine → seed_planning → dose_calc → dose_eval.",
                    "enum": ["trajectory_init", "trajectory_refine", "seed_planning", "dose_calc", "dose_eval", "full"],
                    "default": "trajectory_init",
                },
                "mode": {
                    "type": "string",
                    "description": "Planning mode: 'rule_based' or 'rl'",
                    "enum": ["rule_based", "rl"],
                    "default": "rule_based",
                },
                "seed_info": {
                    "type": "object",
                    "description": "Seed parameters override {radius, length, seed_avr_dose}",
                },
                "planning_params": {
                    "type": "object",
                    "description": "Planning parameters override {in_lowest_energy, out_highest_energy, DVH_rate}",
                },
                "ref_direc": {
                    "type": "array",
                    "description": (
                        "Reference direction [x, y, z] in RAS world space. "
                        "Special string values are also accepted: "
                        "'auto' (default) picks an organ-aware default (e.g. posterior "
                        "[-Y] for pancreas/prostate, anterior [+Y] for lung); "
                        "'auto_detect' runs geometric detection to find the shortest "
                        "skin-to-CTV approach axis. "
                        "If omitted, falls back to agent config → 'auto'."
                    ),
                    "items": {"type": "number"},
                },
            },
            "required": [],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "step_executed": {"type": "string"},
                "seed_plan": {"type": "array"},
                "dose_distribution": {"type": "object"},
                "dose_metrics": {"type": "object"},
                "total_seeds": {"type": "integer"},
                "summary": {"type": "string"},
            },
        }

    # ============================================================
    # Main entry point
    # ============================================================

    def _execute(self, **kwargs) -> ToolResult:
        import SimpleITK as sitk

        step = kwargs.get("step", "trajectory_init")
        # The caller must inject its session-local agent. A module-level global
        # previously let concurrent web sessions read and overwrite each
        # other's planning memory.
        agent = kwargs.pop("_agent", None)
        if agent is None:
            return ToolResult(
                success=False,
                error=(
                    "planning_pipeline requires a session-local agent context. "
                    "Invoke it through BrachyAgent or /api/planning/run_step."
                ),
            )

        # step_callback: optional, called for each sub-step with
        #   (substep_name, status) where status is 'pending' or 'done'.
        # The agent uses this to emit SSE step events for the todo list
        # so the user sees each sub-step tick through with the
        # breathing animation on the active item, instead of one big
        # 'planning_pipeline' pending → done transition that hides all
        # 5 sub-steps. Internal to this file, NOT exposed in the
        # input_schema (popped before validation).
        step_callback = kwargs.pop("step_callback", None)

        # Load CT image (required for all steps)
        ct_image = self._load_ct(kwargs, agent)
        if ct_image is None:
            return ToolResult(
                success=False,
                error="No CT image available. Provide ct_image_path or load CT first. "
                      "Use: tool('ctv_segmentation', image_path='/path/to/ct.nii.gz')"
            )

        # Load CTV mask (required for most steps)
        ctv_mask = self._load_ctv(kwargs, agent, ct_image)
        logger.info(f"CTV mask loaded: {ctv_mask is not None}, shape={ctv_mask.shape if ctv_mask is not None else 'None'}")

        # Load OAR mask (optional)
        oar_mask = self._load_oar(kwargs, agent, ct_image)
        logger.info(f"OAR mask loaded: {oar_mask is not None}")

        # CRITICAL: Validate required inputs for full pipeline
        # If LLM provides fake paths that don't exist, _load_ctv/_load_oar will return None.
        # AUTO-RECOVERY: If CTV/OAR masks are missing, automatically run segmentation!
        if step == "full":
            if ctv_mask is None:
                return ToolResult(
                    success=False,
                    error="CTV mask is required but not found. You MUST call ctv_segmentation FIRST, then oar_segmentation, before planning_pipeline."
                )

            if oar_mask is None:
                logger.warning("[AUTO-RECOVERY] OAR mask not found — auto-running oar_segmentation")
                ct_path = kwargs.get("ct_image_path") or (agent.memory.retrieve("ct_path") if agent else None)
                if ct_path and os.path.exists(ct_path):
                    try:
                        oar_tool = agent.registry.get("oar_segmentation") if agent else None
                        if oar_tool:
                            # Pass LPI CT object (not file path) to prevent Z-flip
                            oar_result = oar_tool.execute(image=ct_image, image_path=ct_path) if ct_image else oar_tool.execute(image_path=ct_path)
                            if oar_result and oar_result.success:
                                logger.info("[AUTO-RECOVERY] ✓ OAR segmentation completed")
                                # Reload OAR mask from memory
                                oar_mask = self._load_oar(kwargs, agent, ct_image)
                                if oar_mask is None:
                                    return ToolResult(success=False, error="OAR segmentation completed but mask still not found in memory")
                            else:
                                return ToolResult(
                                    success=False,
                                    error=f"Auto-recovery failed: OAR segmentation error: {oar_result.error if oar_result else 'no result'}"
                                )
                        else:
                            return ToolResult(success=False, error="oar_segmentation tool not found")
                    except Exception as e:
                        return ToolResult(success=False, error=f"Auto-recovery failed: {e}")
                else:
                    return ToolResult(
                        success=False,
                        error=f"OAR mask is required but CT path not found. Please upload a CT image first."
                    )

        # Build an invocation-local configuration. Planning overrides belong to
        # this tool call and must never mutate the session-wide agent config.
        agent_config = copy.deepcopy(getattr(agent, 'config', {}) or {}) if agent else {}
        seed_info = kwargs.get("seed_info")
        if seed_info is not None:
            if not isinstance(seed_info, dict):
                return ToolResult(success=False, error="seed_info must be an object")
            agent_config.setdefault("seed_info", {}).update(seed_info)
        planning_params = kwargs.get("planning_params")
        if planning_params is not None:
            if not isinstance(planning_params, dict):
                return ToolResult(success=False, error="planning_params must be an object")
            allowed_planning_params = {
                "in_lowest_energy", "out_highest_energy", "DVH_rate",
                "reference_direc", "iter_rate", "distance_filtter",
            }
            unknown = sorted(set(planning_params) - allowed_planning_params)
            if unknown:
                return ToolResult(
                    success=False,
                    error=f"Unsupported planning_params: {', '.join(unknown)}",
                )
            agent_config.update(copy.deepcopy(planning_params))

        # Get reference direction — accepts explicit array, "auto", or "auto_detect"
        ref_direc_input = kwargs.get("ref_direc")
        if ref_direc_input is None:
            # Try agent config first, then config file (preserves legacy behavior)
            ref_direc_input = agent_config.get("reference_direc")
            if ref_direc_input is None:
                ref_direc_input = CONFIG.get("reference_direc", "auto")
        # Resolve via the unified helper (handles organ defaults + auto_detect)
        ref_direc = _resolve_ref_direc(ref_direc_input, ct_image, ctv_mask, agent)

        # Get mode
        mode = kwargs.get("mode", "rule_based")

        # Route to the requested step
        if step == "full":
            return self._run_full_pipeline(ct_image, ctv_mask, oar_mask, ref_direc, mode, agent_config, agent, step_callback=step_callback)
        elif step == "trajectory_init":
            return self._step_trajectory_init(ct_image, ctv_mask, oar_mask, ref_direc, agent_config, agent)
        elif step == "trajectory_refine":
            return self._step_trajectory_refine(ct_image, ctv_mask, oar_mask, agent)
        elif step == "seed_planning":
            return self._step_seed_planning(ct_image, ctv_mask, oar_mask, mode, agent_config, agent)
        elif step == "dose_calc":
            return self._step_dose_calc(ct_image, ctv_mask, oar_mask, agent_config, agent)
        elif step == "dose_eval":
            return self._step_dose_eval(ctv_mask, oar_mask, agent)
        else:
            return ToolResult(success=False, error=f"Unknown step: '{step}'. Valid steps: trajectory_init, trajectory_refine, seed_planning, dose_calc, dose_eval, full")

    # ============================================================
    # Data loading helpers
    # ============================================================

    def _load_ct(self, kwargs, agent):
        """Load CT image from path or agent memory.
        Always applies DICOMOrient('LPI') so CT and labels share the same orientation.

        Maintains BOTH 'ct_image' (LPI-oriented) and 'ct_image_raw' (original frame)
        in agent.memory so that _store_label_with_metadata can correctly copy
        spatial metadata from the raw frame, matching the contract in AgenticSys.
        """
        import SimpleITK as sitk

        ct_image_path = kwargs.get("ct_image_path")
        if ct_image_path:
            try:
                logger.info(f"Loading CT image: {ct_image_path}")
                ct_raw = sitk.ReadImage(ct_image_path)
                ct_image = _safe_dicom_orient(ct_raw, 'LPI', context="for CT")
                if agent:
                    # Store both raw (for label metadata) and oriented (for downstream use)
                    agent.memory.store("ct_image_raw", ct_raw)
                    agent.memory.store("ct_image", ct_image)
                    agent.memory.store("ct_path", ct_image_path)
                return ct_image
            except Exception as e:
                logger.warning(f"Failed to load CT from path '{ct_image_path}': {e}. Falling back to memory.")

        if agent:
            ct_image = agent.memory.retrieve("ct_image")
            if ct_image is not None:
                # Ensure stored CT is also LPI-oriented
                ct_image = _safe_dicom_orient(ct_image, 'LPI', context="for stored CT")
                # Maintain ct_image_raw invariant — _store_label_with_metadata needs it.
                # If absent (CT was loaded outside this tool), use the LPI-oriented
                # image as its own raw frame reference (consistent orientation).
                if agent.memory.retrieve("ct_image_raw") is None:
                    agent.memory.store("ct_image_raw", ct_image)
                return ct_image

        return None

    def _load_ctv(self, kwargs, agent, ct_image):
        """Load CTV mask from path or agent memory. Returns None if not available."""
        import SimpleITK as sitk

        ctv_mask_path = kwargs.get("ctv_mask_path")
        if ctv_mask_path:
            try:
                logger.info(f"Loading CTV mask from path: {ctv_mask_path}")
                ctv_img = sitk.ReadImage(ctv_mask_path)
                # Orient to LPI to match CT orientation
                ctv_img = _safe_dicom_orient(ctv_img, 'LPI', context="for CTV mask")
                ctv_mask = sitk.GetArrayFromImage(ctv_img)
                if agent:
                    agent.memory.store("ctv_array", ctv_mask)
                return ctv_mask
            except Exception as e:
                logger.warning(f"Failed to load CTV mask from path '{ctv_mask_path}': {e}. Falling back to memory.")

        if agent:
            # Try _get_label_array first (handles DICOMOrient)
            if hasattr(agent, '_get_label_array'):
                ctv_mask = agent._get_label_array("ctv_array")
                logger.debug(
                    "[LOAD_CTV] _get_label_array returned: %s, type=%s",
                    "exists" if ctv_mask is not None else "None",
                    type(ctv_mask).__name__ if ctv_mask is not None else "N/A",
                )
            else:
                ctv_mask = agent.memory.retrieve("ctv_array")
                logger.debug(
                    "[LOAD_CTV] memory.retrieve returned: %s",
                    "exists" if ctv_mask is not None else "None",
                )

            if ctv_mask is not None:
                # Ensure it's a numpy array
                if hasattr(ctv_mask, 'GetArrayFromImage'):
                    ctv_mask = sitk.GetArrayFromImage(ctv_mask)
                # Validate it has content
                if hasattr(ctv_mask, 'shape'):
                    logger.debug(
                        "[LOAD_CTV] CTV from memory: shape=%s, non-zero=%s",
                        ctv_mask.shape,
                        int(np.count_nonzero(ctv_mask)),
                    )
                return ctv_mask
            else:
                logger.debug("[LOAD_CTV] CTV mask not found in agent memory")
                # Debug: check what's in planning_results
                if hasattr(agent, 'memory') and hasattr(agent.memory, 'planning_results'):
                    logger.debug(
                        "[LOAD_CTV] planning_results keys: %s",
                        list(agent.memory.planning_results.keys()),
                    )

        return None

    def _load_oar(self, kwargs, agent, ct_image):
        """Load OAR mask from path or agent memory. Returns None if not available."""
        import SimpleITK as sitk

        oar_mask_path = kwargs.get("oar_mask_path")
        if oar_mask_path:
            try:
                logger.info(f"Loading OAR mask: {oar_mask_path}")
                oar_img = sitk.ReadImage(oar_mask_path)
                oar_img = _safe_dicom_orient(oar_img, 'LPI', context="for OAR mask")
                oar_mask = sitk.GetArrayFromImage(oar_img)
                if agent:
                    agent.memory.store("oar_array", oar_mask)
                return oar_mask
            except Exception as e:
                logger.warning(f"Failed to load OAR mask from path '{oar_mask_path}': {e}. Falling back to memory.")

        if agent:
            if hasattr(agent, '_get_label_array'):
                oar_mask = agent._get_label_array("oar_array")
            else:
                oar_mask = agent.memory.retrieve("oar_array")
            if oar_mask is not None:
                if hasattr(oar_mask, 'GetArrayFromImage'):
                    oar_mask = sitk.GetArrayFromImage(oar_mask)
                return oar_mask

        return None

    def _check_ctv(self, ctv_mask, agent):
        """Check if CTV mask is available. Try to auto-segment if not."""
        if ctv_mask is not None:
            return ctv_mask, None

        # Try to trigger CTV segmentation
        if agent:
            ct_path = agent.memory.retrieve("ct_path")
            if ct_path:
                return None, (
                    "No CTV mask available. Please segment CTV first:\n"
                    f"  tool('ctv_segmentation', image_path='{ct_path}')\n"
                    "Or provide ctv_mask_path directly."
                )

        return None, (
            "No CTV mask available. Please:\n"
            "1. Load CT image first\n"
            "2. Segment CTV: tool('ctv_segmentation', image_path='...')\n"
            "3. Or provide ctv_mask_path directly."
        )

    # ============================================================
    # Individual step implementations
    # ============================================================

    def _step_trajectory_init(self, ct_image, ctv_mask, oar_mask, ref_direc, agent_config, agent):
        """Step 1: Generate candidate trajectories.

        Prerequisites:
        - CT image (required)
        - CTV mask (required)
        - OAR mask (optional)

        Auto-recovery:
        - If CTV missing, returns error with instructions
        """
        # Check CTV
        ctv_mask, err = self._check_ctv(ctv_mask, agent)
        if err:
            logger.error(f"[trajectory_init] CTV check failed: {err}")
            return ToolResult(success=False, error=f"[trajectory_init] {err}")

        logger.info(f"[trajectory_init] CTV shape={ctv_mask.shape}, non-zero={int(np.sum(ctv_mask > 0))}")

        # Get config
        from plans.config import setting
        args = setting()

        # Resample to planning grid
        logger.info("Resampling to planning grid [128, 128, 64]...")
        try:
            resampled_ct, resampled_ctv, resampled_oar = _resample_for_planning(
                ct_image, ctv_mask, oar_mask, new_size=[128, 128, NEW_SLICES_ROUNDED]
            )
            logger.info(f"Resampled CT: {resampled_ct.GetSize()}, CTV non-zero={int(np.sum(resampled_ctv > 0))}")
        except Exception as e:
            logger.error(f"Resampling failed: {e}")
            return ToolResult(success=False, error=f"[trajectory_init] Resampling failed: {e}")

        # Resolve the current Data tree category state before planning.
        obstacle_labels, obstacle_source = _resolve_data_tree_obstacle_labels(agent)

        # Build radiation volume
        radiation_volume = _build_radiation_volume(
            resampled_ctv, resampled_oar,
            target_value=args.radiation_array_params['target_value'],
            obstacle_value=args.radiation_array_params['obstacle_value'],
            obstacle_labels=obstacle_labels,
            obstacle_source=obstacle_source,
        )
        target_count = int(np.sum(radiation_volume == args.radiation_array_params['target_value']))
        obstacle_count = int(np.sum(radiation_volume == args.radiation_array_params['obstacle_value']))
        logger.info(f"Radiation volume: target={target_count}, obstacle={obstacle_count}, shape={radiation_volume.shape}")
        if target_count == 0:
            return ToolResult(success=False, error="[trajectory_init] No target voxels in radiation volume. Check CTV mask.")

        # Convert reference direction
        logger.info("Converting reference direction to voxel space...")
        try:
            ras_direc = np.array(ref_direc).reshape(-1)
            voxel_direc = _convert_ref_direc_to_voxel(ras_direc, resampled_ct)
            logger.info(f"Direction: RAS {ras_direc} -> Voxel {voxel_direc}")
        except Exception as e:
            logger.warning(f"Direction conversion failed: {e}, using default")
            voxel_direc = np.array([0, 0, 1])

        # Run init_plan
        from plans.core import init_plan
        logger.info(f"Running init_plan with: ref_direc={voxel_direc}, direc_resolution={args.direc_resolution}, backlit_angle={args.radiation_array_params['backlit_angle']}, target_value={args.radiation_array_params['target_value']}, obstacle_value={args.radiation_array_params['obstacle_value']}, min_depth={args.radiation_array_params.get('min_depth', 1)}, max_traj={args.radiation_array_params['maximum_candidate_trajectories']}")
        try:
            trajectories = init_plan(
                resampled_ct,
                radiation_volume,
                voxel_direc,
                args.direc_resolution,
                args.radiation_array_params['backlit_angle'],
                args.radiation_array_params['target_value'],
                args.radiation_array_params['background_value'],
                args.radiation_array_params['obstacle_value'],
                args.radiation_array_params['maximum_candidate_trajectories'],
                min_depth=args.radiation_array_params.get('min_depth', 1),
            )
            logger.info(f"init_plan returned {len(trajectories)} trajectories")
        except Exception as e:
            logger.error(f"init_plan failed: {e}")
            import traceback
            traceback.print_exc()
            return ToolResult(success=False, error=f"[trajectory_init] init_plan failed: {e}")

        # Check if trajectories were generated
        if not trajectories:
            logger.error("init_plan returned 0 trajectories")
            return ToolResult(
                success=False,
                error="[trajectory_init] No valid trajectories generated. Possible causes: "
                      "CTV too small, reference direction misaligned, or CTV mask empty. "
                f"Target voxels: {target_count}, Direction: {voxel_direc.tolist()}"
            )

        trajectories = _filter_safe_trajectories(
            trajectories,
            radiation_volume,
            args.radiation_array_params['obstacle_value'],
        )
        trajectories = _filter_world_safe_trajectories(
            trajectories,
            resampled_ct,
            ct_image,
            ctv_mask,
            oar_mask,
            obstacle_labels,
        )
        if not trajectories:
            return ToolResult(
                success=False,
                error="[trajectory_init] No trajectories remain after non-traversable obstacle validation.",
            )

        # Store results
        if agent:
            agent.memory.store("trajectories", trajectories)
            agent.memory.store("resampled_ct", resampled_ct)
            agent.memory.store("resampled_ctv", resampled_ctv)
            agent.memory.store("resampled_oar", resampled_oar)
            agent.memory.store("radiation_volume", radiation_volume)
            agent.memory.store("obstacle_label_ids", sorted(obstacle_labels))
            agent.memory.store("obstacle_label_source", obstacle_source)
            agent.memory.store("ref_direc_voxel", voxel_direc)
            logger.info(f"[trajectory_init] Stored resampled_ct: size={resampled_ct.GetSize()}, spacing={resampled_ct.GetSpacing()}")

        max_depth = max([t[4] for t in trajectories], default=0) if trajectories else 0

        return ToolResult(
            success=True,
            data=trajectories,
            message=f"Step 1/5: Trajectory initialization completed. {len(trajectories)} candidates generated. Max depth: {max_depth:.1f} voxels.",
            metadata={
                "step_executed": "trajectory_init",
                "trajectories": trajectories,
                "num_trajectories": len(trajectories),
                "max_depth": float(max_depth),
                "reference_direction_voxel": voxel_direc.tolist(),
            },
        )

    def _step_trajectory_refine(self, ct_image, ctv_mask, oar_mask, agent):
        """Step 2: Refine trajectories (filter by quality).

        Prerequisites:
        - trajectories (from step 1)

        Auto-recovery:
        - If trajectories missing, runs step 1 first
        """
        # Check trajectories
        trajectories = None
        if agent:
            trajectories = agent.memory.retrieve("trajectories")

        if not trajectories:
            logger.info("No trajectories found, running trajectory_init first...")
            ref_input = (getattr(agent, "config", {}) or {}).get(
                "reference_direc", CONFIG.get("reference_direc", "auto")
            )
            ref_direc = _resolve_ref_direc(ref_input, ct_image, ctv_mask, agent)
            init_result = self._step_trajectory_init(
                ct_image, ctv_mask, oar_mask, ref_direc,
                copy.deepcopy(getattr(agent, "config", {}) or {}), agent,
            )
            if not init_result.success:
                return ToolResult(success=False, error=f"[trajectory_refine] Cannot generate trajectories: {init_result.error}")
            trajectories = init_result.metadata.get("trajectories", [])

        if not trajectories:
            return ToolResult(success=False, error="[trajectory_refine] No trajectories generated. Check CTV mask.")

        # Rebuild from the current Data tree state. Users may move an OAR
        # between parent categories after trajectory initialization.
        radiation_volume = None
        resampled_ct = agent.memory.retrieve("resampled_ct") if agent else None
        resampled_ctv = agent.memory.retrieve("resampled_ctv") if agent else None
        resampled_oar = agent.memory.retrieve("resampled_oar") if agent else None
        obstacle_labels = set(OBSTACLE_ORGAN_LABELS)
        if resampled_ctv is not None:
            from plans.config import setting
            args = setting()
            obstacle_labels, obstacle_source = _resolve_data_tree_obstacle_labels(agent)
            radiation_volume = _build_radiation_volume(
                resampled_ctv, resampled_oar,
                target_value=args.radiation_array_params['target_value'],
                obstacle_value=args.radiation_array_params['obstacle_value'],
                obstacle_labels=obstacle_labels,
                obstacle_source=obstacle_source,
            )
            if agent:
                agent.memory.store("radiation_volume", radiation_volume)
                agent.memory.store("obstacle_label_ids", sorted(obstacle_labels))
                agent.memory.store("obstacle_label_source", obstacle_source)

        # Filter trajectories by depth
        from plans.config import setting
        args = setting()
        min_depth = args.radiation_array_params.get('min_depth_rate', 5)

        depth_candidates = [t for t in trajectories if t[4] >= min_depth]
        if not depth_candidates:
            logger.warning(f"No trajectories with depth >= {min_depth}; checking all {len(trajectories)} candidates")
            depth_candidates = list(trajectories)

        if radiation_volume is not None:
            refined = _filter_safe_trajectories(
                depth_candidates,
                radiation_volume,
                args.radiation_array_params['obstacle_value'],
            )
            if resampled_ct is None:
                return ToolResult(
                    success=False,
                    error="[trajectory_refine] Planning geometry is unavailable for full needle safety validation. Re-run trajectory initialization.",
                )
            refined = _filter_world_safe_trajectories(
                refined,
                resampled_ct,
                ct_image,
                ctv_mask,
                oar_mask,
                obstacle_labels,
            )
        else:
            refined = depth_candidates
        if not refined:
            return ToolResult(
                success=False,
                error="[trajectory_refine] No trajectories remain after non-traversable obstacle validation.",
            )

        # Sort by depth (best first)
        refined.sort(key=lambda t: t[4], reverse=True)

        if agent:
            agent.memory.store("refined_trajectories", refined)

        return ToolResult(
            success=True,
            data=refined,
            message=f"Step 2/5: Trajectory refinement completed. {len(refined)}/{len(trajectories)} passed filter (min_depth={min_depth}).",
            metadata={
                "step_executed": "trajectory_refine",
                "refined_trajectories": refined,
                "num_trajectories": len(refined),
                "num_filtered_out": len(trajectories) - len(refined),
            },
        )

    def _step_seed_planning(self, ct_image, ctv_mask, oar_mask, mode, agent_config, agent):
        """Step 3: Optimize seed placement.

        Prerequisites:
        - CT image (required)
        - CTV mask (required)
        - trajectories (from step 1 or 2)

        Auto-recovery:
        - If trajectories missing, runs steps 1-2 first
        - If CTV missing, returns error with instructions
        """
        # Check CTV
        ctv_mask, err = self._check_ctv(ctv_mask, agent)
        if err:
            return ToolResult(success=False, error=f"[seed_planning] {err}")

        # Check trajectories
        trajectories = None
        if agent:
            trajectories = agent.memory.retrieve("refined_trajectories") or agent.memory.retrieve("trajectories")

        if not trajectories:
            logger.info("No trajectories found, running trajectory_init + refine first...")
            # Use the configured or organ-aware direction resolution.
            ref_direc_input = agent_config.get("reference_direc") if agent_config else None
            if ref_direc_input is None:
                ref_direc_input = CONFIG.get("reference_direc", "auto")
            auto_ref_direc = _resolve_ref_direc(ref_direc_input, ct_image, ctv_mask, agent)
            init_result = self._step_trajectory_init(ct_image, ctv_mask, oar_mask, auto_ref_direc, agent_config, agent)
            if not init_result.success:
                return ToolResult(success=False, error=f"[seed_planning] Cannot generate trajectories: {init_result.error}")
            refine_result = self._step_trajectory_refine(ct_image, ctv_mask, oar_mask, agent)
            if not refine_result.success:
                return ToolResult(success=False, error=f"[seed_planning] Cannot refine trajectories: {refine_result.error}")
            trajectories = refine_result.metadata.get("refined_trajectories", [])

        if not trajectories:
            return ToolResult(success=False, error="[seed_planning] No trajectories available. Check CTV mask.")

        # Get resampled data
        resampled_ct = agent.memory.retrieve("resampled_ct") if agent else None
        resampled_ctv = agent.memory.retrieve("resampled_ctv") if agent else None
        resampled_oar = agent.memory.retrieve("resampled_oar") if agent else None
        radiation_volume = agent.memory.retrieve("radiation_volume") if agent else None

        if resampled_ct is None or resampled_ctv is None:
            logger.info("Resampled data missing, re-running resampling...")
            resampled_ct, resampled_ctv, resampled_oar = _resample_for_planning(
                ct_image, ctv_mask, oar_mask, new_size=[128, 128, NEW_SLICES_ROUNDED]
            )
            from plans.config import setting
            args_tmp = setting()
            obstacle_labels, obstacle_source = _resolve_data_tree_obstacle_labels(agent)
            radiation_volume = _build_radiation_volume(
                resampled_ctv, resampled_oar,
                target_value=args_tmp.radiation_array_params['target_value'],
                obstacle_value=args_tmp.radiation_array_params['obstacle_value'],
                obstacle_labels=obstacle_labels,
                obstacle_source=obstacle_source,
            )
            if agent:
                agent.memory.store("resampled_ct", resampled_ct)
                agent.memory.store("resampled_ctv", resampled_ctv)
                agent.memory.store("resampled_oar", resampled_oar)
                agent.memory.store("radiation_volume", radiation_volume)

        # Always refresh the volume immediately before seed optimization so a
        # Data tree category change is honored without restarting the session.
        if resampled_ctv is not None:
            from plans.config import setting
            args_current = setting()
            obstacle_labels, obstacle_source = _resolve_data_tree_obstacle_labels(agent)
            radiation_volume = _build_radiation_volume(
                resampled_ctv, resampled_oar,
                target_value=args_current.radiation_array_params['target_value'],
                obstacle_value=args_current.radiation_array_params['obstacle_value'],
                obstacle_labels=obstacle_labels,
                obstacle_source=obstacle_source,
            )
            if agent:
                agent.memory.store("radiation_volume", radiation_volume)
                agent.memory.store("obstacle_label_ids", sorted(obstacle_labels))
                agent.memory.store("obstacle_label_source", obstacle_source)

        obstacle_labels = set(locals().get("obstacle_labels", OBSTACLE_ORGAN_LABELS))
        if radiation_volume is not None:
            obstacle_args = args_current if 'args_current' in locals() else setting()
            trajectories = _filter_safe_trajectories(
                trajectories,
                radiation_volume,
                obstacle_args.radiation_array_params['obstacle_value'],
            )
            trajectories = _filter_world_safe_trajectories(
                trajectories,
                resampled_ct,
                ct_image,
                ctv_mask,
                oar_mask,
                obstacle_labels,
            )
            if not trajectories:
                return ToolResult(
                    success=False,
                    error="[seed_planning] No trajectories remain after non-traversable obstacle validation.",
                )

        # Load dose model
        dose_model, model_err = _load_dose_model()
        if dose_model is None:
            return ToolResult(success=False, error=f"[seed_planning] {model_err}")

        # Get config
        from plans.config import setting
        args = setting()

        # Override with agent config
        if "seed_info" in agent_config:
            args.seed_info.update(agent_config["seed_info"])
        if "in_lowest_energy" in agent_config:
            args.in_lowest_energy = agent_config["in_lowest_energy"]
        if "out_highest_energy" in agent_config:
            args.out_highest_energy = agent_config["out_highest_energy"]
        if "DVH_rate" in agent_config:
            args.DVH_rate = agent_config["DVH_rate"]

        # Run planning using core.init_plan + core.optimal_plan directly.
        # We CANNOT use brachy_plan because it rebuilds the radiation volume
        # with get_planning_volume_array which treats ALL OAR as obstacles
        # (185K voxels), while our pipeline uses a whitelist (60K voxels).
        # This causes brachy_plan to find 0 trajectories.
        import SimpleITK as sitk
        from plans import core, utilizations
        logger.info(f"Running seed planning (mode={mode})...")

        # Keep the trajectory list already validated against the current
        # Data-tree obstacle whitelist. Re-reading the unfiltered memory
        # entry here would silently reintroduce paths through bones/vessels.
        if not trajectories:
            logger.warning("[seed_planning] No trajectories found in memory, running trajectory_init...")
            ref_input = agent_config.get("reference_direc", CONFIG.get("reference_direc", "auto"))
            ref_direc = _resolve_ref_direc(ref_input, ct_image, ctv_mask, agent)
            init_result = self._step_trajectory_init(
                ct_image, ctv_mask, oar_mask, ref_direc, agent_config, agent
            )
            if init_result.success:
                trajectories = init_result.metadata.get("trajectories", [])

        if not trajectories:
            return ToolResult(success=False, error="[seed_planning] No trajectories available.")

        logger.info(f"[seed_planning] Using {len(trajectories)} trajectories from pipeline")

        # Build dose_image for coordinate transforms
        dose_image = utilizations.normalize_dose_image(
            resampled_ct, args.image_normalize[0], args.image_normalize[1],
            args.image_normalize[0], args.image_normalize[1]
        )

        try:
            if mode == "rl":
                # RL uses the same filtered trajectories and radiation volume
                # as rule-based planning, so changing mode cannot bypass the
                # resolved reference direction or obstacle policy.
                plan_res = core.optimal_plan_rf(
                    trajectories,
                    radiation_volume,
                    dose_image,
                    dose_model,
                    args.dl_params,
                    args.rf_params,
                    getattr(args, 'distance_filter', getattr(args, 'distance_filtter', {})).get('interval_rate', 2),
                    args.radiation_array_params['target_value'],
                    args.radiation_array_params['infer_img_size'],
                    args.in_lowest_energy,
                    args.out_highest_energy,
                    args.DVH_rate,
                    args.seed_info,
                    args.image_normalize[0],
                    args.image_normalize[1],
                    args.image_normalize[2],
                    _MockProgressDialog()
                )
            else:
                plan_res = core.optimal_plan(
                    trajectories,
                    radiation_volume,
                    dose_image,
                    dose_model,
                    args.dl_params,
                    args.distance_filtter['lower_bound'],
                    args.distance_filtter['upper_bound'],
                    args.distance_filtter['distance_rate'],
                    args.radiation_array_params['target_value'],
                    args.radiation_array_params['background_value'],
                    args.radiation_array_params['obstacle_value'],
                    args.radiation_array_params['infer_img_size'],
                    args.in_lowest_energy,
                    args.out_highest_energy,
                    args.DVH_rate,
                    args.seed_info,
                    args.iter_rate,
                    args.image_normalize[0],
                    args.image_normalize[1],
                    args.image_normalize[2],
                    _MockProgressDialog()
                )
            # Compute dose distribution
            sum_image = np.zeros_like(radiation_volume, dtype=np.float32)
            for entry in plan_res:
                if isinstance(entry, (list, tuple)) and len(entry) >= 3:
                    for seed_dose in entry[2]:
                        sum_image += seed_dose
        except Exception as e:
            logger.error(f"Planning failed: {e}")
            import traceback
            traceback.print_exc()
            return ToolResult(success=False, error=f"[seed_planning] Planning algorithm failed: {e}")

        verified_needle_geometry, unsafe_needle_indices = _validated_needle_geometry(
            plan_res,
            ct_image,
            ctv_mask,
            oar_mask,
            obstacle_labels,
        )
        if unsafe_needle_indices:
            # This is a defense-in-depth assertion. Candidate validation above
            # should prevent it, but a plan must never be accepted or rendered
            # when its actual seed-derived 150 mm needle is unsafe.
            logger.error(
                "[needle_safety] Final seed plan failed physical obstacle validation for needles: %s",
                unsafe_needle_indices,
            )
            return ToolResult(
                success=False,
                error=(
                    "[seed_planning] Safety validation rejected the final needle geometry "
                    f"for trajectory indices {unsafe_needle_indices}. No unsafe plan was published."
                ),
            )

        # Extract results
        total_seeds = 0
        num_trajectories = len(plan_res) if plan_res else 0
        seed_plan = []

        if plan_res:
            for entry in plan_res:
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    trajectory = entry[0]
                    seeds = entry[1]
                    total_seeds += len(seeds)
                    seed_plan.append({
                        "trajectory": trajectory,
                        "seeds": [(s[0].tolist(), s[1].tolist()) for s in seeds] if seeds else [],
                        "num_seeds": len(seeds),
                    })

        # Store results
        if agent:
            agent.memory.store("seed_plan", plan_res)
            agent.memory.store("seed_plan_serialized", seed_plan)
            # The viewer consumes these already validated world-coordinate
            # endpoints instead of reconstructing an unchecked 150 mm line.
            agent.memory.store("verified_needle_geometry", verified_needle_geometry)
            agent.memory.store("dose_distribution", sum_image)
            agent.memory.store("total_seeds", total_seeds)
            agent.memory.store("num_trajectories", num_trajectories)
            # Store actual config used — so reviewer agents can read real thresholds
            agent.memory.store("plan_config", {
                "in_lowest_energy": float(args.in_lowest_energy),
                "out_highest_energy": float(args.out_highest_energy),
                "DVH_rate": float(args.DVH_rate),
                "seed_info": {
                    "radius": float(args.seed_info.get("radius", 0.4)),
                    "length": float(args.seed_info.get("length", 3.7)),
                    "margin_rate": float(args.seed_info.get("margin_rate", 1.5)),
                },
            })
            logger.info(f"[seed_planning] Stored in agent id={id(agent)}: seed_plan={len(plan_res)} entries, total_seeds={total_seeds}")

        summary = (
            f"Step 3/5: Seed planning completed. "
            f"{total_seeds} seeds across {num_trajectories} trajectories. Mode: {mode}."
        )

        return ToolResult(
            success=True,
            data=plan_res,
            message=summary,
            metadata={
                "step_executed": "seed_planning",
                "seed_plan": seed_plan,
                "dose_distribution": sum_image,
                "total_seeds": total_seeds,
                "num_trajectories": num_trajectories,
                "mode": mode,
            },
        )

    def _step_dose_calc(self, ct_image, ctv_mask, oar_mask, agent_config, agent):
        """Step 4: Calculate dose distribution.

        Prerequisites:
        - seed_plan (from step 3)

        Auto-recovery:
        - If seed_plan missing, runs steps 1-3 first
        """
        import SimpleITK as sitk

        # Check seed plan
        seed_plan = None
        if agent:
            seed_plan = agent.memory.retrieve("seed_plan")

        if not seed_plan:
            return ToolResult(
                success=False,
                error="[dose_calc] No seed plan available. Please run seed_planning first:\n"
                      "  tool('planning_pipeline', step='seed_planning')\n"
                      "Run steps in order: trajectory_init → trajectory_refine → seed_planning → dose_calc → dose_eval"
            )

        # Get dose distribution (already computed during seed_planning)
        dose_distribution = None
        if agent:
            dose_distribution = agent.memory.retrieve("dose_distribution")

        if dose_distribution is None:
            return ToolResult(
                success=False,
                error="[dose_calc] No dose distribution available. The seed_planning step should have computed it. "
                      "Try re-running: tool('planning_pipeline', step='seed_planning')"
            )

        # Get resampled CT for resampling dose back to original space
        resampled_ct = agent.memory.retrieve("resampled_ct") if agent else None

        # Dose is in normalized units (no Gy conversion)
        DOSE_SCALE = DOSE_MODEL_SCALE_GY
        dose_array = dose_distribution.copy()

        if resampled_ct is not None and ct_image is not None:
            try:
                # Create SimpleITK image from dose array
                dose_sitk = sitk.GetImageFromArray(dose_distribution.astype(np.float32))
                dose_sitk.CopyInformation(resampled_ct)

                # Resample to original CT size
                resampler = sitk.ResampleImageFilter()
                resampler.SetReferenceImage(ct_image)
                resampler.SetInterpolator(sitk.sitkLinear)
                original_dose = resampler.Execute(dose_sitk)
                dose_array = sitk.GetArrayFromImage(original_dose)
            except Exception as e:
                logger.warning(f"Failed to resample dose to original space: {e}")

        # Store in normalized units
        if agent:
            agent.memory.store("dose_distribution_gy", dose_array)
            agent.memory.store("dose_units", "normalized_model_output")
            agent.memory.store("dose_scale_gy", DOSE_SCALE)

        max_dose = float(np.max(dose_array))
        mean_dose = float(np.mean(dose_array[dose_array > 0])) if np.any(dose_array > 0) else 0

        return ToolResult(
            success=True,
            data=dose_array,
            message=f"Step 4/5: Dose calculation completed. Max={max_dose:.2f}, Mean={mean_dose:.2f} (normalized).",
            metadata={
                "step_executed": "dose_calc",
                "dose_distribution": dose_array,
                "max_dose": max_dose,
                "mean_dose": mean_dose,
            },
        )

    def _step_dose_eval(self, ctv_mask, oar_mask, agent):
        """Step 5: Evaluate dose metrics (DVH).

        Prerequisites:
        - dose_distribution (from step 3 or 4) — in planning grid space
        - CTV mask (required) — must be in planning grid space

        Auto-recovery:
        - If dose missing, returns error
        - If CTV missing, returns error
        """
        # Use resampled masks (planning grid space) for DVH computation
        # The dose_distribution is in planning grid space, so masks must match
        resampled_ctv = agent.memory.retrieve("resampled_ctv") if agent else None
        resampled_oar = agent.memory.retrieve("resampled_oar") if agent else None

        if resampled_ctv is not None:
            ctv_mask = resampled_ctv
            logger.info("[dose_eval] Using resampled CTV mask from planning grid")
        else:
            ctv_mask, err = self._check_ctv(ctv_mask, agent)
            if err:
                return ToolResult(success=False, error=f"[dose_eval] {err}")

        if resampled_oar is not None:
            oar_mask = resampled_oar
            logger.info("[dose_eval] Using resampled OAR mask from planning grid")

        # Check dose distribution
        dose_distribution = None
        if agent:
            dose_distribution = agent.memory.retrieve("dose_distribution")

        if dose_distribution is None:
            return ToolResult(
                success=False,
                error="[dose_eval] No dose distribution available. Please run seed_planning or dose_calc first:\n"
                      "  tool('planning_pipeline', step='seed_planning')\n"
                      "Run steps in order: trajectory_init → trajectory_refine → seed_planning → dose_calc → dose_eval"
            )

        # Get organ names for DVH labels
        organ_names = None
        if agent:
            organ_names = agent.memory.retrieve("organ_names")
            logger.info(f"[dose_eval] organ_names: {organ_names}")

        resolved_organ_names = dict(organ_names or {})

        def _lookup_oar_name(label_val):
            """Resolve numeric OAR labels to stable clinical names."""
            try:
                label_int = int(label_val)
            except (TypeError, ValueError):
                label_int = label_val

            for key in (label_int, str(label_int), label_val, str(label_val)):
                name = resolved_organ_names.get(key)
                if name and not str(name).lower().startswith(("oar_", "organ_", "label_")):
                    return str(name)

            nnunet_oar_names = {201: "artery", 202: "vein", 203: "pancreas"}
            if label_int in nnunet_oar_names:
                name = nnunet_oar_names[label_int]
                resolved_organ_names[label_int] = name
                return name

            try:
                from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
                name = TOTALSEG_LABEL_MAPPING.get(label_int)
                if name:
                    resolved_organ_names[label_int] = name
                    return name
            except Exception:
                pass

            if isinstance(label_int, int):
                return f"Organ {label_int}"
            return str(label_val)

        # Validate every grid before boolean indexing.  This ordering matters:
        # NumPy otherwise raises an opaque IndexError before the actionable
        # planning-grid error below can be returned to the agent and UI.
        dose_distribution = np.asarray(dose_distribution, dtype=np.float32)
        ctv_mask = np.asarray(ctv_mask)
        logger.info(
            "[dose_eval] dose_distribution shape: %s, ctv_mask shape: %s",
            dose_distribution.shape,
            ctv_mask.shape,
        )
        if dose_distribution.shape != ctv_mask.shape:
            return ToolResult(
                success=False,
                error=(
                    "[dose_eval] Dose and CTV grids do not match: "
                    f"dose={dose_distribution.shape}, CTV={ctv_mask.shape}. "
                    "Run dose_calc on the current planning grid before evaluation."
                ),
            )
        if oar_mask is not None:
            oar_mask = np.asarray(oar_mask)
            logger.info(
                "[dose_eval] oar_mask shape: %s, unique labels: %s",
                oar_mask.shape,
                np.unique(oar_mask).tolist(),
            )
            if oar_mask.shape != dose_distribution.shape:
                return ToolResult(
                    success=False,
                    error=(
                        "[dose_eval] Dose and OAR grids do not match: "
                        f"dose={dose_distribution.shape}, OAR={oar_mask.shape}."
                    ),
                )

        # Compute DVH metrics (reference: Zhiyuan BrachyPlan.calculate_dvh)
        #
        # DOSE_SCALE (120.0): dose_unet_spacing1mm output is rendered using
        # trained with ground-truth labels where model output 1.0 = 120 Gy.
        # All internal dose values live in "normalized" space:
        #   - CNN raw output: 0 ~ 255 (uint8 image_normalize_scale)
        #   - After normalization: 0 ~ 1.0 (prescription = 1.0)
        #   - To convert to Gy: dose_normalized × 120.0
        # This constant also appears in the web planning routes and agent runtime.
        # Keep the display scale in sync if the dose model calibration changes.
        DOSE_SCALE = DOSE_MODEL_SCALE_GY
        target_mask = ctv_mask > 0
        target_doses = dose_distribution[target_mask]

        if len(target_doses) == 0:
            return ToolResult(success=False, error="[dose_eval] No target voxels found in CTV mask.")

        # All dose metrics in Gy
        target_doses_gy = target_doses * DOSE_SCALE
        sorted_doses = np.sort(target_doses_gy)[::-1]  # Descending order
        n = len(sorted_doses)

        def dose_at_volume(vol_pct):
            idx = int(np.ceil(n * vol_pct / 100.0)) - 1
            idx = max(0, min(idx, n - 1))
            return float(sorted_doses[idx])

        def volume_at_dose(dose_threshold):
            return float(np.sum(target_doses_gy >= dose_threshold) / n * 100.0)

        prescribed_dose = 1.0
        candidate = 1.0
        if agent:
            plan_config = agent.memory.retrieve("plan_config") or {}
            candidate = plan_config.get(
                "in_lowest_energy",
                getattr(agent, "config", {}).get("in_lowest_energy", 1.0),
            )
        try:
            candidate = float(candidate)
            if candidate > 0:
                prescribed_dose = candidate
        except (TypeError, ValueError):
            logger.warning(
                "Invalid in_lowest_energy=%r; using normalized prescription 1.0",
                candidate,
            )
        prescription_gy = prescribed_dose * DOSE_SCALE

        # D metrics in Gy (reference: dose_at_volume)
        max_dose = float(np.max(target_doses_gy))
        mean_dose = float(np.mean(target_doses_gy))
        min_dose = float(np.min(target_doses_gy))
        d98 = dose_at_volume(98)
        d95 = dose_at_volume(95)
        d90 = dose_at_volume(90)
        d50 = dose_at_volume(50)
        d2 = dose_at_volume(2)

        # V metrics (percentage, reference: volume_at_dose)
        v100 = volume_at_dose(prescription_gy) / 100.0  # As ratio
        v150 = volume_at_dose(prescription_gy * 1.5) / 100.0
        v200 = volume_at_dose(prescription_gy * 2.0) / 100.0
        v50 = volume_at_dose(prescription_gy * 0.5) / 100.0

        # Conformity Index, Homogeneity Index, Coverage (reference)
        ci = (v100 ** 2) if v100 > 0 else 0.0
        hi_n = (d2 - d98) / prescription_gy if prescription_gy > 0 else 0.0
        hi = (max_dose - prescription_gy) / prescription_gy if prescription_gy > 0 else 0.0
        cov = v100
        gi = (v50 / v100) if v100 > 0 else 0.0

        # OAR metrics in Gy (use organ names if available)
        # Include Dxcc, Dx%, Vx metrics like Zhiyuan
        DOSE_SCALE = DOSE_MODEL_SCALE_GY
        oar_metrics = {}
        if oar_mask is not None:
            # dose_distribution and oar_mask are both on the planning grid.
            # Dxcc must therefore use that grid's spacing, never the original
            # CT spacing (which can have a much larger slice thickness).
            resampled_ct = agent.memory.retrieve("resampled_ct") if agent else None
            if resampled_ct is None:
                return ToolResult(
                    success=False,
                    error="[dose_eval] Planning-grid metadata is missing; run dose_calc before dose_eval.",
                )
            spacing = resampled_ct.GetSpacing()
            voxel_vol_cm3 = float(spacing[0] * spacing[1] * spacing[2]) / 1000.0  # mm³ → cm³

            for label_val in np.unique(oar_mask):
                if label_val > 0:
                    oar_doses = dose_distribution[oar_mask == label_val] * DOSE_SCALE
                    if len(oar_doses) > 0:
                        oar_name = _lookup_oar_name(label_val)

                        sorted_doses_desc = np.sort(oar_doses)[::-1]
                        organ_vol_cm3 = len(oar_doses) * voxel_vol_cm3
                        n = len(oar_doses)

                        # Dxcc: minimum dose to hottest x cm³
                        def dose_at_xcc(x_cc):
                            if organ_vol_cm3 < x_cc:
                                return float(np.min(oar_doses))
                            n_voxels = int(x_cc / voxel_vol_cm3)
                            n_voxels = max(1, min(n_voxels, n - 1))
                            return float(sorted_doses_desc[n_voxels - 1])

                        # Dx%: dose received by x% of organ volume
                        def dose_at_pct(pct):
                            idx = int(np.ceil(n * pct / 100.0)) - 1
                            idx = max(0, min(idx, n - 1))
                            return float(sorted_doses_desc[idx])

                        # Vx Gy: volume (%) receiving at least x Gy
                        def volume_pct_at_dose(dose_gy):
                            return float(np.sum(oar_doses >= dose_gy) / n * 100.0)

                        oar_metrics[oar_name] = {
                            "label_id": int(label_val),
                            "max_dose": float(np.max(oar_doses)),
                            "dmax": float(np.max(oar_doses)),
                            "mean_dose": float(np.mean(oar_doses)),
                            "d0_1cc": dose_at_xcc(0.1),
                            "d1cc": dose_at_xcc(1.0),
                            "d2cc": dose_at_xcc(2.0),
                            "d90": dose_at_pct(90),
                            "d95": dose_at_pct(95),
                            "v100": volume_pct_at_dose(prescription_gy),
                            "v150": volume_pct_at_dose(prescription_gy * 1.5),
                            "volume_cm3": round(organ_vol_cm3, 2),
                            "volume_voxels": int(n),
                        }

        # Plan score is an advisory, data-derived summary. The former score
        # used only V100, so plans with different hotspot, homogeneity, or OAR
        # behavior could display the same score. Keep this transparent and
        # deterministic; it is not a substitute for clinical approval.
        coverage_score = min(100.0, max(0.0, v100 * 100.0))
        hotspot_score = 100.0
        hotspot_score -= max(0.0, (v150 - 0.50) * 100.0) * 0.60
        hotspot_score -= max(0.0, (v200 - 0.30) * 100.0) * 0.40
        hotspot_score = min(100.0, max(0.0, hotspot_score))
        homogeneity_score = max(0.0, 100.0 - abs(d90 - prescription_gy) / max(prescription_gy, 1e-6) * 100.0)
        if oar_metrics:
            oar_peak = max(float(item.get("max_dose", 0.0)) for item in oar_metrics.values())
            oar_score = max(0.0, 100.0 - max(0.0, oar_peak / max(prescription_gy, 1e-6) - 0.5) * 50.0)
        else:
            oar_peak = None
            oar_score = 100.0
        plan_score = round(min(100.0, max(0.0,
            coverage_score * 0.45 + hotspot_score * 0.25
            + homogeneity_score * 0.20 + oar_score * 0.10)), 2)

        # Compute DVH curve data (cumulative dose-volume histogram)
        # Reference: Zhiyuan BrachyPlan.calculate_dvh
        # DVH range: max(prescription*3, 250, dose_max*1.1) — ensures meaningful display
        DOSE_SCALE = DOSE_MODEL_SCALE_GY
        prescription_gy = prescribed_dose * DOSE_SCALE  # e.g. 1.0 * 120 = 120 Gy
        dvh_data = {}
        if len(target_doses) > 0:
            dose_max_full = float(np.max(target_doses)) * DOSE_SCALE * 1.1
            # Reference: dose_max_for_bins = max(prescription*3, 250, dose_max_full)
            dose_max_val = max(prescription_gy * 3.0, 250.0, dose_max_full)
            # 600 bins (~1 Gy per bin for a 600 Gy range) gives noticeably
            # smoother DVH curves than the previous 300-bin version
            # (~2 Gy per bin). The data is sent to the frontend as JSON
            # so the ~2x size increase is negligible.
            num_bins = 600
            dose_bins = np.linspace(0, dose_max_val, num_bins + 1)
            dose_centers = (dose_bins[:-1] + dose_bins[1:]) / 2.0

            # CTV cumulative DVH
            ctv_pcts = []
            target_doses_gy = target_doses * DOSE_SCALE
            for d in dose_centers:
                pct = min(100.0, max(0.0, float(np.sum(target_doses_gy >= d) / len(target_doses_gy) * 100.0)))
                ctv_pcts.append(pct)
            dvh_data["CTV"] = {
                "dose_bins": dose_centers.tolist(),
                "volume_pcts": ctv_pcts,
            }

            # OAR cumulative DVH (ALL organs, not just top 3)
            if oar_mask is not None:
                oar_labels = sorted(
                    [l for l in np.unique(oar_mask) if l > 0],
                    key=lambda l: int(np.sum(oar_mask == l)),
                    reverse=True
                )
                for label_val in oar_labels:
                    oar_doses_arr = dose_distribution[oar_mask == label_val] * DOSE_SCALE
                    if len(oar_doses_arr) > 0:
                        oar_pcts = []
                        for d in dose_centers:
                            pct = min(100.0, max(0.0, float(np.sum(oar_doses_arr >= d) / len(oar_doses_arr) * 100.0)))
                            oar_pcts.append(pct)
                        # Try both int and string keys for organ_names
                        oar_name = _lookup_oar_name(label_val)
                        dvh_data[oar_name] = {
                            "dose_bins": dose_centers.tolist(),
                            "volume_pcts": oar_pcts,
                        }

        metrics = {
            # D metrics in Gy (reference: Zhiyuan calculate_dvh)
            "dmax": max_dose,
            "dmin": min_dose,
            "dmean": mean_dose,
            "d98": d98,
            "d95": d95,
            "d90": d90,
            "d50": d50,
            "d2": d2,
            # V metrics as ratios
            "v100": v100,
            "v150": v150,
            "v200": v200,
            "v50": v50,
            # Indices (reference)
            "ci": ci,           # Conformity Index
            "hi": hi,           # Homogeneity Index
            "hi_n": hi_n,       # Normalized HI
            "cov": cov,         # Coverage
            "gi": gi,           # Gradient Index
            # Legacy keys for backward compatibility
            "max_dose": max_dose,
            "mean_dose": mean_dose,
            "prescribed_dose": prescribed_dose,
            "prescription_gy": prescription_gy,
            "dose_scale_gy": DOSE_SCALE,
            "plan_score": plan_score,
            "plan_score_breakdown": {
                "coverage": round(coverage_score, 2),
                "hotspot_control": round(hotspot_score, 2),
                "homogeneity": round(homogeneity_score, 2),
                "oar_sparing": round(oar_score, 2),
                "oar_peak_dose_gy": oar_peak,
            },
            "oar_metrics": oar_metrics,
            "dvh_data": dvh_data,
            "ctv_voxels": int(len(target_doses)),
            "ctv_volume_mm3": (
                float(agent.memory.retrieve("ctv_volume_mm3"))
                if agent and agent.memory.retrieve("ctv_volume_mm3") is not None
                else None
            ),
            "total_seeds": agent.memory.retrieve("total_seeds") if agent else 0,
        }

        if agent:
            agent.memory.store("dose_metrics", metrics)
            if resolved_organ_names:
                agent.memory.store("organ_names", resolved_organ_names)

        return ToolResult(
            success=True,
            data=metrics,
            message=(
                f"Step 5/5: Dose evaluation completed. "
                f"V100={v100:.1%}, D90={d90:.2f}, Score={plan_score:.0f}/100."
            ),
            metadata={
                "step_executed": "dose_eval",
                **metrics,
            },
        )

    # ============================================================
    # Full pipeline
    # ============================================================

    def _run_full_pipeline(self, ct_image, ctv_mask, oar_mask, ref_direc,
                           mode, agent_config, agent, step_callback=None):
        """Run the complete planning pipeline.

        step_callback (optional): callable(substep_name, status) called at
        the start ('pending') and end ('done' or 'error') of each of the
        5 sub-steps. The agent translates this to SSE step events so the
        todo list ticks through ctv→oar→trajectory→seeds→dose instead
        of showing a single 'planning_pipeline' black box.
        """
        import time
        results = {}
        # Per-substep wall-clock timings (seconds). The frontend uses this
        # to render per-step timers in the planning pipeline progress box
        # (otherwise the 4 planning substeps show no time and no running
        # indicator because the agent only streams a single 'done' event
        # for the whole planning_pipeline tool call).
        substep_timings = {}

        def _notify(substep_name, status, content=None):
            """Forward a sub-step transition to the agent. Errors are
            swallowed (callback is best-effort telemetry, must never
            break the tool).

            For 'done' events, includes elapsed_ms in the content so
            the frontend can display the REAL execution time instead of
            measuring wall-clock time between SSE events (which can be
            wrong when multiple events arrive in the same batch).
            """
            if step_callback is None:
                return
            try:
                step_callback(substep_name, status, content)
            except Exception as _e:
                logger.debug(f"step_callback for {substep_name} failed: {_e}")

        # Step 1: Trajectory initialization
        logger.info("Step 1/5: Trajectory initialization...")
        _notify("trajectory_init", "pending", "Generating candidate trajectories")
        t0 = time.time()
        traj_result = self._step_trajectory_init(ct_image, ctv_mask, oar_mask, ref_direc, agent_config, agent)
        substep_timings["trajectory_init"] = round(time.time() - t0, 2)
        _notify("trajectory_init", "done" if traj_result.success else "error",
                f"{len(traj_result.metadata.get('trajectories', []))} trajectories | elapsed_ms={int(substep_timings['trajectory_init']*1000)}")
        if not traj_result.success:
            return traj_result
        results["trajectories"] = traj_result.metadata.get("trajectories", [])

        # Step 2: Trajectory refinement
        logger.info("Step 2/5: Trajectory refinement...")
        _notify("trajectory_refine", "pending", "Refining candidate trajectories")
        t0 = time.time()
        refine_result = self._step_trajectory_refine(ct_image, ctv_mask, oar_mask, agent)
        substep_timings["trajectory_refine"] = round(time.time() - t0, 2)
        _notify("trajectory_refine", "done" if refine_result.success else "error",
                f"elapsed_ms={int(substep_timings['trajectory_refine']*1000)}")
        if not refine_result.success:
            return refine_result
        results["refined_trajectories"] = refine_result.metadata.get("refined_trajectories", [])

        # Step 3: Seed planning
        logger.info("Step 3/5: Seed placement optimization...")
        _notify("seed_planning", "pending", "Optimizing seed placement")
        t0 = time.time()
        seed_result = self._step_seed_planning(ct_image, ctv_mask, oar_mask, mode, agent_config, agent)
        substep_timings["seed_planning"] = round(time.time() - t0, 2)
        _notify("seed_planning", "done" if seed_result.success else "error",
                f"{seed_result.metadata.get('total_seeds', 0)} seeds | elapsed_ms={int(substep_timings['seed_planning']*1000)}")
        if not seed_result.success:
            return seed_result
        results["seed_plan"] = seed_result.metadata.get("seed_plan", [])
        results["total_seeds"] = seed_result.metadata.get("total_seeds", 0)

        # Step 4: Dose calculation
        logger.info("Step 4/5: Dose calculation...")
        _notify("dose_calc", "pending", "Computing dose distribution")
        t0 = time.time()
        dose_result = self._step_dose_calc(ct_image, ctv_mask, oar_mask, agent_config, agent)
        substep_timings["dose_calc"] = round(time.time() - t0, 2)
        _notify("dose_calc", "done" if dose_result.success else "error",
                f"elapsed_ms={int(substep_timings['dose_calc']*1000)}")
        if dose_result.success:
            results["dose_distribution"] = dose_result.data

        # Step 5: Dose evaluation
        logger.info("Step 5/5: Dose evaluation...")
        _notify("dose_eval", "pending", "Evaluating dose metrics")
        t0 = time.time()
        eval_result = self._step_dose_eval(ctv_mask, oar_mask, agent)
        substep_timings["dose_eval"] = round(time.time() - t0, 2)
        _notify("dose_eval", "done" if eval_result.success else "error",
                f"elapsed_ms={int(substep_timings['dose_eval']*1000)}")
        if eval_result.success:
            results["dose_metrics"] = eval_result.metadata

        # Build summary
        # BUG FIX 2026-06-17 (None format): metrics.get(k, 0) returns None
        # when the key exists but its value is None (e.g. plan_score is
        # computed later and stored as None at the time summary is built).
        # The format spec :.1% / :.2f / :.0f then raises
        # "unsupported format string passed to NoneType.__format__".
        # Use `or 0` so a None value falls back to 0.
        total_seeds = results.get("total_seeds", 0) or 0
        num_trajectories = len(results.get("seed_plan", []) or [])
        metrics = results.get("dose_metrics", {}) or {}
        v100_val = metrics.get("v100") or 0
        d90_val = metrics.get("d90") or 0
        score_val = metrics.get("plan_score") or 0
        summary = (
            f"Planning completed: {total_seeds} seeds. "
            f"V100={v100_val:.1%}, D90={d90_val:.2f}, "
            f"Score={score_val:.0f}/100"
        )

        return ToolResult(
            success=True,
            data=results,
            message=summary,
            metadata={
                "step_executed": "full",
                "seed_plan": results.get("seed_plan", []),
                "dose_distribution": results.get("dose_distribution"),
                "dose_metrics": results.get("dose_metrics", {}),
                "total_seeds": total_seeds,
                "num_trajectories": num_trajectories,
                "summary": summary,
                # Per-substep wall-clock timings in seconds. Used by the
                # frontend pipeline progress box to show per-step timers
                # and "running..." indicators for each planning substep.
                "substep_timings": substep_timings,
            },
        )


class _MockProgressDialog:
    """No-op progress dialog for headless mode."""
    def setValue(self, v): pass
    def setLabelText(self, t): pass
