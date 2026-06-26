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
import logging
import numpy as np
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Load default parameters from Zhiyuan config
PLANS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "plans")
CONFIG_PATH = os.path.join(PLANS_DIR, "config.json")

# Default planning parameters (from Zhiyuan config.json)
# Dose is in normalized units (matching Zhiyuan convention).
# in_lowest_energy=1.0 is the prescription dose threshold.
# No Gy conversion needed - all metrics use normalized units.
NEW_SLICES_ROUNDED = 64

# TotalSegmentator v2 organ labels that physically block a needle trajectory.
# Soft parenchymal organs (lung, liver, kidney, spleen, muscle) are deliberately
# excluded so the posterior / trans-abdominal approach can find a path to the CTV
# even when the OAR mask contains the full body atlas (117 organs).
# See memory/oar-obstacle-filter-fix.md for rationale.
OBSTACLE_ORGAN_LABELS = frozenset({
    # Vessels (aorta, vena cava, portal, iliac, pulmonary, brachiocephalic, etc.)
    15, 52, 53, 54, 55, 56, 57, 58, 59, 60, 62, 63, 64, 65, 66, 67, 68,
    # Bowel
    18, 19, 20,
    # Bone — vertebrae (cervical, thoracic, lumbar, sacrum), ribs, sternum, humerus,
    # scapula, clavicula, femur, hip, spinal cord
    25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40,
    41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 79,
    69, 70, 71, 72, 73, 74, 75, 76, 77, 78,
    # Soft but high-risk for transabdominal / posterior approach
    6,    # stomach
    16,   # trachea
    17,   # thyroid
    51,   # heart
})


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
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load config: {e}")
        return {}


CONFIG = load_config()


def _get_agent():
    """Get the global agent instance."""
    try:
        import AgenticSys
        agent = getattr(AgenticSys, '_global_agent', None)
        if agent:
            ctv = agent.memory.retrieve("ctv_array")
            print(f"[GET_AGENT] agent id={id(agent)}, ctv_array={'exists' if ctv is not None else 'None'}, planning_results keys={list(agent.memory.planning_results.keys()) if hasattr(agent.memory, 'planning_results') else 'N/A'}")
        else:
            print("[GET_AGENT] _global_agent is None — trying module-level fallback")
            # Fallback: check if AgenticSys module has the agent
            agent = getattr(AgenticSys, '_global_agent', None)
            if agent:
                print(f"[GET_AGENT] Fallback found agent id={id(agent)}")
        return agent
    except Exception as e:
        print(f"[GET_AGENT] Error: {e}")
        return None


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
    """Convert RAS reference direction to voxel space.

    This is critical because the planning algorithm operates in voxel space.
    The reference direction must be in the same coordinate system.

    Args:
        ref_direc_ras: 3-element direction in RAS space
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
#   - list/tuple/array of 3 numbers  → use as-is (RAS, will be normalized)
#   - "auto" or None                  → organ-aware default from _ORGAN_DEFAULT_REFDIREC
#                                        (falls back to global config, then "auto_detect")
#   - "auto_detect"                   → geometric detection from CTV center to skin
#                                        (slowest but most adaptive)
# ----------------------------------------------------------------------

# Organ-specific default approach direction in RAS (pointing INTO the body
# toward the tumor). These were chosen to avoid the most common OAR
# obstructions seen in clinical brachytherapy cases:
#   - pancreas  : posterior [-Y]      avoids stomach/duodenum in front
#   - prostate  : posterior [-Y]      standard perineal template
#   - liver     : lateral  [+X]       avoids central vessels
#   - lung      : anterior [+Y]       avoids scapula/posterior ribs
#   - kidney    : posterior [-Y]      standard posterior oblique
#   - colon     : posterior [-Y]
#   - head_neck : superior [+Z]       most tumors reachable from above
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

# Global default if no organ hint is available. Changed from anterior [0,1,0]
# to posterior [-1,0,0] as a safer fallback — anterior approach is blocked
# by OARs (stomach/duodenum) for most abdominal tumors.
_GLOBAL_DEFAULT_REFDIREC = [0.0, -1.0, 0.0]


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
    min_world = np.minimum(origin, extent_world)
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
    if isinstance(ref_direc_input, str) and ref_direc_input.lower() == "auto_detect":
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


def _load_dose_model():
    """Load the dose prediction model.

    Returns:
        (model, error_message) - model is None if loading failed
    """
    import torch

    model_path = os.path.join(PLANS_DIR, "dose_pre", "dose_model.pth")
    if not os.path.exists(model_path):
        model_path = os.path.join(os.path.dirname(PLANS_DIR), "dose_pre", "dose_model.pth")
    if not os.path.exists(model_path):
        return None, f"Dose model not found. Expected at: {model_path}"

    try:
        from plans.dose_pre.myDoseNet import myDoseNet
        model = myDoseNet(
            spatial_dims=3,
            in_channels=3,
            out_channels=1,
            features=(16, 32, 64, 128, 256, 32)
        )
        model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
        model.eval()
        return model, None
    except Exception as e:
        return None, f"Failed to load dose model: {e}"


def _build_radiation_volume(ctv_mask, oar_mask, target_value=1, obstacle_value=2):
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
    # OAR from TotalSegmentator (if provided): apply whitelist filter
    if oar_mask is not None:
        total_oar_voxels = int((oar_mask > 0).sum())
        obstacle_mask = np.isin(oar_mask, list(OBSTACLE_ORGAN_LABELS))
        filtered_voxels = int(obstacle_mask.sum())
        radiation_volume[obstacle_mask & (radiation_volume == 0)] = obstacle_value
        logger.info(
            f"[OAR filter] blocking voxels: {filtered_voxels} / {total_oar_voxels} "
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
        # Accept injected agent from _execute_tool_with_memory,
        # fall back to global agent lookup.
        agent = kwargs.pop("_agent", None) or _get_agent()

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

        # Get agent config
        agent_config = getattr(agent, 'config', {}) if agent else {}

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
                print(f"[LOAD_CTV] _get_label_array returned: {'exists' if ctv_mask is not None else 'None'}, type={type(ctv_mask).__name__ if ctv_mask is not None else 'N/A'}")
            else:
                ctv_mask = agent.memory.retrieve("ctv_array")
                print(f"[LOAD_CTV] memory.retrieve returned: {'exists' if ctv_mask is not None else 'None'}")

            if ctv_mask is not None:
                # Ensure it's a numpy array
                if hasattr(ctv_mask, 'GetArrayFromImage'):
                    ctv_mask = sitk.GetArrayFromImage(ctv_mask)
                # Validate it has content
                if hasattr(ctv_mask, 'shape'):
                    print(f"[LOAD_CTV] CTV from memory: shape={ctv_mask.shape}, non-zero={int(ctv_mask.sum()) if ctv_mask.dtype in [int, float] else 'N/A'}")
                return ctv_mask
            else:
                print("[LOAD_CTV] CTV mask NOT found in agent memory")
                # Debug: check what's in planning_results
                if hasattr(agent, 'memory') and hasattr(agent.memory, 'planning_results'):
                    print(f"[LOAD_CTV] planning_results keys: {list(agent.memory.planning_results.keys())}")

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

        # Build radiation volume
        radiation_volume = _build_radiation_volume(
            resampled_ctv, resampled_oar,
            target_value=args.radiation_array_params['target_value'],
            obstacle_value=args.radiation_array_params['obstacle_value']
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

        # Store results
        if agent:
            agent.memory.store("trajectories", trajectories)
            agent.memory.store("resampled_ct", resampled_ct)
            agent.memory.store("resampled_ctv", resampled_ctv)
            agent.memory.store("resampled_oar", resampled_oar)
            agent.memory.store("radiation_volume", radiation_volume)
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
            # Pass sentinel "auto" so the init step picks an organ-aware default
            init_result = self._step_trajectory_init(ct_image, ctv_mask, oar_mask, "auto", {}, agent)
            if not init_result.success:
                return ToolResult(success=False, error=f"[trajectory_refine] Cannot generate trajectories: {init_result.error}")
            trajectories = init_result.metadata.get("trajectories", [])

        if not trajectories:
            return ToolResult(success=False, error="[trajectory_refine] No trajectories generated. Check CTV mask.")

        # Get radiation volume
        radiation_volume = None
        if agent:
            radiation_volume = agent.memory.retrieve("radiation_volume")

        if radiation_volume is None:
            # Build it
            from plans.config import setting
            args = setting()
            resampled_ctv = agent.memory.retrieve("resampled_ctv") if agent else None
            resampled_oar = agent.memory.retrieve("resampled_oar") if agent else None
            if resampled_ctv is not None:
                radiation_volume = _build_radiation_volume(
                    resampled_ctv, resampled_oar,
                    target_value=args.radiation_array_params['target_value'],
                    obstacle_value=args.radiation_array_params['obstacle_value']
                )

        # Filter trajectories by depth
        from plans.config import setting
        args = setting()
        min_depth = args.radiation_array_params.get('min_depth_rate', 5)

        refined = [t for t in trajectories if t[4] >= min_depth]
        if not refined:
            # Fall back to all trajectories
            refined = trajectories
            logger.warning(f"No trajectories with depth >= {min_depth}, using all {len(trajectories)}")

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
            init_result = self._step_trajectory_init(ct_image, ctv_mask, oar_mask, [0, 1, 0], agent_config, agent)
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
            radiation_volume = _build_radiation_volume(
                resampled_ctv, resampled_oar,
                target_value=args_tmp.radiation_array_params['target_value'],
                obstacle_value=args_tmp.radiation_array_params['obstacle_value']
            )
            if agent:
                agent.memory.store("resampled_ct", resampled_ct)
                agent.memory.store("resampled_ctv", resampled_ctv)
                agent.memory.store("resampled_oar", resampled_oar)
                agent.memory.store("radiation_volume", radiation_volume)

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

        # Use the pipeline's radiation volume (already built with whitelist filter)
        # and the trajectories from trajectory_init/refine
        trajectories = agent.memory.retrieve("refined_trajectories") or agent.memory.retrieve("trajectories") if agent else None
        if not trajectories:
            logger.warning("[seed_planning] No trajectories found in memory, running trajectory_init...")
            init_result = self._step_trajectory_init(ct_image, ctv_mask, oar_mask, ref_direc, agent_config, agent)
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

        # Extract results
        total_seeds = 0
        num_trajectories = len(plan_res) if plan_res else 0
        seed_plan = []

        if plan_res:
            for entry in plan_res:
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    trajectory = entry[0]
                    seeds = entry[1]
                    seed_radiations = entry[2] if len(entry) >= 3 else []
                    total_seeds += len(seeds)
                    seed_plan.append({
                        "trajectory": trajectory,
                        "seeds": [(s[0].tolist(), s[1].tolist()) for s in seeds] if seeds else [],
                        "num_seeds": len(seeds),
                    })

        # Store results
        if agent:
            agent.memory.store("seed_plan", plan_res)
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

        # Verify shapes match
        logger.info(f"[dose_eval] dose_distribution shape: {dose_distribution.shape}, ctv_mask shape: {ctv_mask.shape}")
        if oar_mask is not None:
            logger.info(f"[dose_eval] oar_mask shape: {oar_mask.shape}, unique labels: {np.unique(oar_mask).tolist()}")

        # Compute DVH metrics (reference: Zhiyuan BrachyPlan.calculate_dvh)
        # Dose values are normalized; multiply by DOSE_SCALE (120) to get Gy
        DOSE_SCALE = 120.0
        target_mask = ctv_mask > 0
        target_doses = dose_distribution[target_mask]

        if len(target_doses) == 0:
            return ToolResult(success=False, error="[dose_eval] No target voxels found in CTV mask.")

        # All dose metrics in Gy
        target_doses_gy = target_doses * DOSE_SCALE
        sorted_doses = np.sort(target_doses_gy)[::-1]  # Descending order
        n = len(sorted_doses)

        def dose_at_volume(vol_pct):
            idx = min(int(n * vol_pct / 100.0), n - 1)
            return float(sorted_doses[idx])

        def volume_at_dose(dose_threshold):
            return float(np.sum(target_doses_gy >= dose_threshold) / n * 100.0)

        prescribed_dose = 1.0  # Normalized prescription dose
        prescription_gy = prescribed_dose * DOSE_SCALE  # 120 Gy

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
        DOSE_SCALE = 120.0
        oar_metrics = {}
        if oar_mask is not None:
            # Calculate voxel volume in cm³ from spacing
            spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
            voxel_vol_cm3 = float(spacing[0] * spacing[1] * spacing[2]) / 1000.0  # mm³ → cm³

            for label_val in np.unique(oar_mask):
                if label_val > 0:
                    oar_doses = dose_distribution[oar_mask == label_val] * DOSE_SCALE
                    if len(oar_doses) > 0:
                        # Get organ name
                        oar_name = None
                        if organ_names:
                            oar_name = organ_names.get(int(label_val)) or organ_names.get(str(int(label_val))) or organ_names.get(label_val)
                        if not oar_name:
                            oar_name = f"OAR_{int(label_val)}"

                        sorted_doses_desc = np.sort(oar_doses)[::-1]
                        sorted_doses_asc = np.sort(oar_doses)
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
                            idx = min(int(n * pct / 100.0), n - 1)
                            return float(sorted_doses_asc[idx])

                        # Vx Gy: volume (%) receiving at least x Gy
                        def volume_pct_at_dose(dose_gy):
                            return float(np.sum(oar_doses >= dose_gy) / n * 100.0)

                        oar_metrics[oar_name] = {
                            "max_dose": float(np.max(oar_doses)),
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

        # Plan score (simple heuristic)
        plan_score = min(100, max(0, v100 * 100 - max(0, (1 - v100) * 200)))

        # Compute DVH curve data (cumulative dose-volume histogram)
        # Reference: Zhiyuan BrachyPlan.calculate_dvh
        # DVH range: max(prescription*3, 250, dose_max*1.1) — ensures meaningful display
        DOSE_SCALE = 120.0  # Gy normalization factor for dose model
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
                        oar_name = None
                        if organ_names:
                            oar_name = organ_names.get(int(label_val)) or organ_names.get(str(int(label_val))) or organ_names.get(label_val)
                        if not oar_name:
                            oar_name = f"OAR_{int(label_val)}"
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
            "plan_score": plan_score,
            "oar_metrics": oar_metrics,
            "dvh_data": dvh_data,
            "ctv_voxels": int(len(target_doses)),
            "total_seeds": agent.memory.retrieve("total_seeds") if agent else 0,
        }

        if agent:
            agent.memory.store("dose_metrics", metrics)

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
