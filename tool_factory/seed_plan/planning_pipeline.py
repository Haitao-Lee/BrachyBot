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
            logger.info(f"[_get_agent] agent id={id(agent)}, ctv_array={'exists' if ctv is not None else 'None'}")
        else:
            logger.warning("[_get_agent] _global_agent is None")
        return agent
    except Exception as e:
        logger.error(f"[_get_agent] Error: {e}")
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
    """
    radiation_volume = np.zeros_like(ctv_mask, dtype=np.int32)
    # Only tumor (label 1) is the target
    radiation_volume[ctv_mask == 1] = target_value
    # Artery and vein are obstacles (non-traversable)
    radiation_volume[(ctv_mask == 2) | (ctv_mask == 3)] = obstacle_value
    # OAR from TotalSegmentator (if provided)
    if oar_mask is not None:
        radiation_volume[(oar_mask > 0) & (radiation_volume == 0)] = obstacle_value
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
                    "description": "Run specific step or 'full' for complete pipeline",
                    "enum": ["trajectory_init", "trajectory_refine", "seed_planning", "dose_calc", "dose_eval", "full"],
                    "default": "full",
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
                    "description": "Reference direction [x, y, z] in RAS space",
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

        step = kwargs.get("step", "full")
        agent = _get_agent()

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

        # Get reference direction
        ref_direc = kwargs.get("ref_direc")
        if ref_direc is None:
            ref_direc = agent_config.get("reference_direc", CONFIG.get("reference_direc", [0, 1, 0]))

        # Get mode
        mode = kwargs.get("mode", "rule_based")

        # Route to the requested step
        if step == "full":
            return self._run_full_pipeline(ct_image, ctv_mask, oar_mask, ref_direc, mode, agent_config, agent)
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
        """Load CT image from path or agent memory."""
        import SimpleITK as sitk

        ct_image_path = kwargs.get("ct_image_path")
        if ct_image_path:
            logger.info(f"Loading CT image: {ct_image_path}")
            ct_image = sitk.ReadImage(ct_image_path)
            if agent:
                agent.memory.store("ct_image", ct_image)
                agent.memory.store("ct_path", ct_image_path)
            return ct_image

        if agent:
            ct_image = agent.memory.retrieve("ct_image")
            if ct_image is not None:
                return ct_image

        return None

    def _load_ctv(self, kwargs, agent, ct_image):
        """Load CTV mask from path or agent memory. Returns None if not available."""
        import SimpleITK as sitk

        ctv_mask_path = kwargs.get("ctv_mask_path")
        if ctv_mask_path:
            logger.info(f"Loading CTV mask from path: {ctv_mask_path}")
            ctv_mask = sitk.GetArrayFromImage(sitk.ReadImage(ctv_mask_path))
            if agent:
                agent.memory.store("ctv_array", ctv_mask)
            return ctv_mask

        if agent:
            # Try _get_label_array first (handles DICOMOrient)
            if hasattr(agent, '_get_label_array'):
                ctv_mask = agent._get_label_array("ctv_array")
            else:
                ctv_mask = agent.memory.retrieve("ctv_array")

            if ctv_mask is not None:
                # Ensure it's a numpy array
                if hasattr(ctv_mask, 'GetArrayFromImage'):
                    ctv_mask = sitk.GetArrayFromImage(ctv_mask)
                # Validate it has content
                if hasattr(ctv_mask, 'shape'):
                    logger.info(f"CTV from memory: shape={ctv_mask.shape}, non-zero={int(ctv_mask.sum()) if ctv_mask.dtype in [int, float] else 'N/A'}")
                return ctv_mask
            else:
                logger.warning("CTV mask not found in agent memory")

        return None

    def _load_oar(self, kwargs, agent, ct_image):
        """Load OAR mask from path or agent memory. Returns None if not available."""
        import SimpleITK as sitk

        oar_mask_path = kwargs.get("oar_mask_path")
        if oar_mask_path:
            logger.info(f"Loading OAR mask: {oar_mask_path}")
            oar_mask = sitk.GetArrayFromImage(sitk.ReadImage(oar_mask_path))
            if agent:
                agent.memory.store("oar_array", oar_mask)
            return oar_mask

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
        logger.info(f"Radiation volume: target_voxels={target_count}")
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
        logger.info("Running init_plan...")
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
            init_result = self._step_trajectory_init(ct_image, ctv_mask, oar_mask, [0, 1, 0], {}, agent)
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

        # Run planning
        from plans.brachy_plan_v2 import brachy_plan, brachy_plan_rf
        import SimpleITK as sitk
        logger.info(f"Running seed planning (mode={mode})...")

        # Convert numpy arrays to SimpleITK images (brachy_plan needs SimpleITK for coordinate transforms)
        ctv_sitk = sitk.GetImageFromArray(resampled_ctv.astype(np.uint8))
        ctv_sitk.CopyInformation(resampled_ct)
        oar_sitk = None
        if resampled_oar is not None:
            oar_sitk = sitk.GetImageFromArray(resampled_oar.astype(np.uint8))
            oar_sitk.CopyInformation(resampled_ct)

        try:
            if mode == "rl":
                plan_res, sum_image, dose_image = brachy_plan_rf(
                    resampled_ct, ctv_sitk, oar_sitk, dose_model, args, _MockProgressDialog()
                )
            else:
                plan_res, sum_image, dose_image = brachy_plan(
                    resampled_ct, ctv_sitk, oar_sitk, dose_model, args, _MockProgressDialog()
                )
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
                      "Or run full pipeline: tool('planning_pipeline', step='full')"
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
                      "Or run full pipeline: tool('planning_pipeline', step='full')"
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

        # Compute DVH metrics in normalized units (matching Zhiyuan convention)
        # in_lowest_energy=1.0 is the prescription dose threshold
        target_mask = ctv_mask > 0
        target_doses = dose_distribution[target_mask]

        if len(target_doses) == 0:
            return ToolResult(success=False, error="[dose_eval] No target voxels found in CTV mask.")

        # Compute metrics in normalized units
        prescribed_dose = 1.0  # Normalized prescription dose
        v100 = float(np.sum(target_doses >= prescribed_dose) / len(target_doses))
        v150 = float(np.sum(target_doses >= 1.5 * prescribed_dose) / len(target_doses))
        v200 = float(np.sum(target_doses >= 2.0 * prescribed_dose) / len(target_doses))
        sorted_doses = np.sort(target_doses)
        d90 = float(sorted_doses[int(0.10 * len(target_doses))])
        d95 = float(sorted_doses[int(0.05 * len(target_doses))])
        d50 = float(np.percentile(target_doses, 50))
        max_dose = float(np.max(target_doses))
        mean_dose = float(np.mean(target_doses))

        # OAR metrics in normalized units (use organ names if available)
        oar_metrics = {}
        if oar_mask is not None:
            for label_val in np.unique(oar_mask):
                if label_val > 0:
                    oar_doses = dose_distribution[oar_mask == label_val]
                    if len(oar_doses) > 0:
                        # Get organ name
                        oar_name = None
                        if organ_names:
                            oar_name = organ_names.get(int(label_val)) or organ_names.get(str(int(label_val))) or organ_names.get(label_val)
                        if not oar_name:
                            oar_name = f"OAR_{int(label_val)}"
                        oar_metrics[oar_name] = {
                            "max_dose": float(np.max(oar_doses)),
                            "mean_dose": float(np.mean(oar_doses)),
                            "d2cc": float(np.percentile(oar_doses, 98)) if len(oar_doses) > 10 else 0,
                            "volume_voxels": int(len(oar_doses)),
                        }

        # Plan score (simple heuristic)
        plan_score = min(100, max(0, v100 * 100 - max(0, (1 - v100) * 200)))

        # Compute DVH curve data (cumulative dose-volume histogram)
        # Format: {name: {dose_bins: [...], volume_pcts: [...]}} for drawDVH()
        # Uses 300 bins like dvh_calculation.py
        dvh_data = {}
        if len(target_doses) > 0:
            dose_max_val = float(np.max(target_doses)) * 1.1
            num_bins = 300
            dose_bins = np.linspace(0, dose_max_val, num_bins + 1)
            dose_centers = (dose_bins[:-1] + dose_bins[1:]) / 2.0

            # CTV cumulative DVH
            ctv_pcts = []
            for d in dose_centers:
                pct = float(np.sum(target_doses >= d) / len(target_doses) * 100.0)
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
                    oar_doses_arr = dose_distribution[oar_mask == label_val]
                    if len(oar_doses_arr) > 0:
                        oar_pcts = []
                        for d in dose_centers:
                            pct = float(np.sum(oar_doses_arr >= d) / len(oar_doses_arr) * 100.0)
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
            "v100": v100,
            "v150": v150,
            "v200": v200,
            "d90": d90,
            "d95": d95,
            "d50": d50,
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
                           mode, agent_config, agent):
        """Run the complete planning pipeline."""
        results = {}

        # Step 1: Trajectory initialization
        logger.info("Step 1/5: Trajectory initialization...")
        traj_result = self._step_trajectory_init(ct_image, ctv_mask, oar_mask, ref_direc, agent_config, agent)
        if not traj_result.success:
            return traj_result
        results["trajectories"] = traj_result.metadata.get("trajectories", [])

        # Step 2: Trajectory refinement
        logger.info("Step 2/5: Trajectory refinement...")
        refine_result = self._step_trajectory_refine(ct_image, ctv_mask, oar_mask, agent)
        if not refine_result.success:
            return refine_result
        results["refined_trajectories"] = refine_result.metadata.get("refined_trajectories", [])

        # Step 3: Seed planning
        logger.info("Step 3/5: Seed placement optimization...")
        seed_result = self._step_seed_planning(ct_image, ctv_mask, oar_mask, mode, agent_config, agent)
        if not seed_result.success:
            return seed_result
        results["seed_plan"] = seed_result.metadata.get("seed_plan", [])
        results["total_seeds"] = seed_result.metadata.get("total_seeds", 0)

        # Step 4: Dose calculation
        logger.info("Step 4/5: Dose calculation...")
        dose_result = self._step_dose_calc(ct_image, ctv_mask, oar_mask, agent_config, agent)
        if dose_result.success:
            results["dose_distribution"] = dose_result.data

        # Step 5: Dose evaluation
        logger.info("Step 5/5: Dose evaluation...")
        eval_result = self._step_dose_eval(ctv_mask, oar_mask, agent)
        if eval_result.success:
            results["dose_metrics"] = eval_result.metadata

        # Build summary
        total_seeds = results.get("total_seeds", 0)
        metrics = results.get("dose_metrics", {})
        summary = (
            f"Planning completed: {total_seeds} seeds. "
            f"V100={metrics.get('v100', 0):.1%}, D90={metrics.get('d90', 0):.2f}, "
            f"Score={metrics.get('plan_score', 0):.0f}/100"
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
            },
        )


class _MockProgressDialog:
    """No-op progress dialog for headless mode."""
    def setValue(self, v): pass
    def setLabelText(self, t): pass
