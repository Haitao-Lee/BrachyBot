"""
Brachytherapy Planning Pipeline
================================
Unified orchestrator that chains individual planning tools into a complete workflow.

Supports both full pipeline execution and individual step invocation.
Each step can be called independently via its own tool, or chained via this pipeline.

Individual tools:
- trajectory_init: Generate candidate needle paths
- trajectory_refine: Filter trajectories by quality
- seed_planning: Optimize seed positions
- dose_engine: Calculate dose distribution
- dose_evaluation: Compute DVH metrics
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

# Load default parameters
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config")
DEFAULT_PARAMS_PATH = os.path.join(CONFIG_DIR, "default_params.json")


def load_default_params() -> Dict:
    """Load default parameters from config file."""
    try:
        with open(DEFAULT_PARAMS_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load default params: {e}")
        return {}


DEFAULTS = load_default_params()


def _get_agent():
    """Get the global agent instance."""
    try:
        import AgenticSys
        agent = getattr(AgenticSys, '_global_agent', None)
        if agent is None:
            try:
                from web.server import get_agent
                agent = get_agent()
            except Exception:
                pass
        return agent
    except Exception:
        return None


def _build_radiation_volume(ctv_mask, oar_mask, target_value, obstacle_value):
    """Build radiation volume from CTV and OAR masks."""
    radiation_volume = np.zeros_like(ctv_mask, dtype=np.int32)
    radiation_volume[ctv_mask > 0] = target_value
    if oar_mask is not None:
        radiation_volume[oar_mask > 0] = obstacle_value
    return radiation_volume


class PlanningPipelineTool(BaseTool):
    """
    Unified brachytherapy planning pipeline orchestrator.

    Chains: trajectory_init → trajectory_refine → seed_planning → dose_engine → dose_evaluation

    Can run:
    - 'full': Execute all steps in sequence
    - Individual steps: 'trajectory_init', 'trajectory_refine', 'seed_planning', 'dose_calc', 'dose_eval'

    Each step reads from agent memory (ct_image, ctv_array, oar_array, etc.)
    and writes results back to agent memory for the next step.
    """

    @property
    def name(self) -> str:
        return "planning_pipeline"

    @property
    def description(self) -> str:
        return (
            "Execute brachytherapy planning pipeline. "
            "Chains: trajectory_init → trajectory_refine → seed_planning → dose_engine → dose_evaluation. "
            "Can run full pipeline or individual steps. "
            "Input: CT image path, CTV mask, OAR mask, hyperparameters. "
            "Output: Seed positions, dose distribution, DVH metrics, plan quality score."
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
                    "description": "Planning parameters override {in_lowest_energy, out_highest_energy, DVH_rate, direc_resolution}",
                },
                "ref_direc": {
                    "type": "array",
                    "description": "Reference direction [x, y, z] for trajectory sampling",
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
                "trajectories": {"type": "array"},
                "seed_plan": {"type": "array"},
                "dose_distribution": {"type": "array"},
                "dose_metrics": {"type": "object"},
                "summary": {"type": "string"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        import SimpleITK as sitk

        ct_image_path = kwargs.get("ct_image_path")
        ctv_mask_path = kwargs.get("ctv_mask_path")
        oar_mask_path = kwargs.get("oar_mask_path")
        step = kwargs.get("step", "full")
        ref_direc = kwargs.get("ref_direc")

        agent = _get_agent()

        # Merge: defaults < agent.config (UI hyperparams) < kwargs (explicit params)
        agent_config = getattr(agent, 'config', {}) if agent else {}

        # Read mode from agent.config (UI) or kwargs
        mode = kwargs.get("mode") or agent_config.get("mode", "rule_based")

        seed_info = {**DEFAULTS.get("seed_info", {}), **agent_config.get("seed_info", {}), **(kwargs.get("seed_info") or {})}
        dl_params = {**DEFAULTS.get("dl_params", {}), **agent_config.get("dl_params", {}), **(kwargs.get("dl_params") or {})}
        rf_params = {**DEFAULTS.get("rf_params", {}), **agent_config.get("rf_params", {}), **(kwargs.get("rf_params") or {})}
        radiation_params = {**DEFAULTS.get("radiation_array_params", {}), **agent_config.get("radiation_array_params", {})}
        distance_filter = {**DEFAULTS.get("distance_filter", {}), **agent_config.get("distance_filter", {})}

        # Build planning_params from all sources
        planning_params = {
            **DEFAULTS.get("planning", {}),
            "in_lowest_energy": agent_config.get("in_lowest_energy", DEFAULTS.get("planning", {}).get("in_lowest_energy", 1)),
            "out_highest_energy": agent_config.get("out_highest_energy", DEFAULTS.get("planning", {}).get("out_highest_energy", 1)),
            "DVH_rate": agent_config.get("DVH_rate", DEFAULTS.get("planning", {}).get("DVH_rate", 0.9)),
            "iter_rate": agent_config.get("iter_rate", DEFAULTS.get("planning", {}).get("iter_rate", 2)),
            "max_iter": agent_config.get("max_iter", DEFAULTS.get("planning", {}).get("max_iter", 4)),
            "replan_rate": agent_config.get("replan_rate", DEFAULTS.get("planning", {}).get("replan_rate", 0.6)),
            "direc_resolution": agent_config.get("direc_resolution", DEFAULTS.get("planning", {}).get("direc_resolution", [30, 3, 2])),
            "image_normalize": DEFAULTS.get("planning", {}).get("image_normalize", [-1000, 3000, 255]),
        }
        planning_params.update(kwargs.get("planning_params") or {})

        # Override ref_direc from agent config
        if "reference_direc" in agent_config and ref_direc is None:
            ref_direc = agent_config["reference_direc"]

        # Load CT image
        ct_image = None
        if ct_image_path:
            logger.info(f"Loading CT image: {ct_image_path}")
            ct_image = sitk.ReadImage(ct_image_path)
            if agent:
                agent.memory.store("ct_image", ct_image)
                agent.memory.store("ct_path", ct_image_path)
        elif agent:
            ct_image = agent.memory.retrieve("ct_image")
        if ct_image is None:
            return ToolResult(success=False, error="No CT image available. Provide ct_image_path or load CT first.")

        # Load CTV mask (use _get_label_array for proper orientation)
        ctv_mask = None
        if ctv_mask_path:
            logger.info(f"Loading CTV mask: {ctv_mask_path}")
            ctv_mask = sitk.GetArrayFromImage(sitk.ReadImage(ctv_mask_path))
            if agent:
                agent.memory.store("ctv_array", ctv_mask)
        elif agent:
            # Use _get_label_array which handles DICOMOrient properly
            if hasattr(agent, '_get_label_array'):
                ctv_mask = agent._get_label_array("ctv_array")
            else:
                ctv_mask = agent.memory.retrieve("ctv_array")
        if ctv_mask is None:
            return ToolResult(success=False, error="No CTV mask available. Provide ctv_mask_path or segment CTV first.")
        # Ensure numpy array
        if hasattr(ctv_mask, 'GetArrayFromImage'):
            ctv_mask = sitk.GetArrayFromImage(ctv_mask)

        # Load OAR mask (use _get_label_array for proper orientation)
        oar_mask = None
        if oar_mask_path:
            logger.info(f"Loading OAR mask: {oar_mask_path}")
            oar_mask = sitk.GetArrayFromImage(sitk.ReadImage(oar_mask_path))
            if agent:
                agent.memory.store("oar_array", oar_mask)
        elif agent:
            if hasattr(agent, '_get_label_array'):
                oar_mask = agent._get_label_array("oar_array")
            else:
                oar_mask = agent.memory.retrieve("oar_array")
        # Ensure numpy array
        if oar_mask is not None and hasattr(oar_mask, 'GetArrayFromImage'):
            oar_mask = sitk.GetArrayFromImage(oar_mask)

        # Build radiation volume
        target_value = radiation_params.get("target_value", 2)
        obstacle_value = radiation_params.get("obstacle_value", 3)
        radiation_volume = _build_radiation_volume(ctv_mask, oar_mask, target_value, obstacle_value)
        if agent:
            agent.memory.store("radiation_volume", radiation_volume)

        # Execute requested step
        if step == "trajectory_init":
            return self._step_trajectory_init(ct_image, radiation_volume, ref_direc, radiation_params, planning_params)
        elif step == "trajectory_refine":
            return self._step_trajectory_refine(radiation_volume, ref_direc, radiation_params)
        elif step == "seed_planning":
            return self._step_seed_planning(ct_image, radiation_volume, seed_info, planning_params, dl_params, rf_params, mode)
        elif step == "dose_calc":
            return self._step_dose_calc(ct_image, seed_info, planning_params)
        elif step == "dose_eval":
            return self._step_dose_eval(ctv_mask, oar_mask, planning_params)
        elif step == "full":
            return self._run_full_pipeline(
                ct_image, radiation_volume, ctv_mask, oar_mask,
                ref_direc, seed_info, radiation_params, planning_params,
                dl_params, rf_params, mode, agent
            )
        else:
            return ToolResult(success=False, error=f"Unknown step: {step}")

    def _step_trajectory_init(self, ct_image, radiation_volume, ref_direc, radiation_params, planning_params):
        """Step 1: Generate candidate trajectories."""
        from tool_factory.traj_plan import TrajectoryInitTool

        tool = TrajectoryInitTool()
        result = tool._execute(
            dose_image=ct_image,
            radiation_volume=radiation_volume,
            ref_direc=ref_direc,
            direc_resolution=planning_params.get("direc_resolution", [30, 3, 2]),
            target_value=radiation_params.get("target_value", 2),
            background_value=radiation_params.get("background_value", 0),
            obstacle_value=radiation_params.get("obstacle_value", 3),
            maximum_candidate_trajectories=radiation_params.get("maximum_candidate_trajectories", 500),
        )

        if result.success:
            agent = _get_agent()
            if agent:
                agent.memory.store("trajectories", result.metadata.get("trajectories", []))
            result.metadata["step_executed"] = "trajectory_init"
            result.message = f"Step 1/5: Trajectory initialization completed. {result.metadata.get('num_trajectories', 0)} candidates generated."
        return result

    def _step_trajectory_refine(self, radiation_volume, ref_direc, radiation_params):
        """Step 2: Refine trajectories."""
        from tool_factory.traj_plan import TrajectoryRefineTool

        agent = _get_agent()
        trajectories = agent.memory.retrieve("trajectories") if agent else None
        if not trajectories:
            return ToolResult(success=False, error="No trajectories available. Run trajectory_init first.")

        tool = TrajectoryRefineTool()
        result = tool._execute(
            trajectories=trajectories,
            radiation_volume=radiation_volume,
            ref_direc=ref_direc,
            target_value=radiation_params.get("target_value", 2),
            obstacle_value=radiation_params.get("obstacle_value", 3),
        )

        if result.success:
            if agent:
                agent.memory.store("refined_trajectories", result.metadata.get("refined_trajectories", []))
            result.metadata["step_executed"] = "trajectory_refine"
            result.message = f"Step 2/5: Trajectory refinement completed. {result.metadata.get('num_trajectories', 0)} trajectories passed filters."
        return result

    def _step_seed_planning(self, ct_image, radiation_volume, seed_info, planning_params, dl_params, rf_params, mode):
        """Step 3: Optimize seed placement."""
        from tool_factory.seed_plan import SeedPlanningTool

        agent = _get_agent()
        trajectories = None
        if agent:
            trajectories = agent.memory.retrieve("refined_trajectories") or agent.memory.retrieve("trajectories")
        if not trajectories:
            return ToolResult(success=False, error="No trajectories available. Run trajectory_init and refine first.")

        tool = SeedPlanningTool()
        result = tool._execute(
            trajectories=trajectories,
            radiation_volume=radiation_volume,
            dose_image=ct_image,
            mode=mode,
            dl_params=dl_params,
            rf_params=rf_params,
            seed_info=seed_info,
            target_value=planning_params.get("target_value", 2),
            background_value=planning_params.get("background_value", 0),
            obstacle_value=planning_params.get("obstacle_value", 3),
            in_lowest_dose=planning_params.get("in_lowest_energy", 1),
            out_highest_dose=planning_params.get("out_highest_energy", 1),
            DVH_rate=planning_params.get("DVH_rate", 0.9),
            iter_rate=planning_params.get("iter_rate", 2),
            image_normalize=planning_params.get("image_normalize", [-1000, 3000, 255]),
        )

        if result.success:
            if agent:
                agent.memory.store("seed_plan", result.metadata.get("optimal_plan", []))
                agent.memory.store("dose_distribution", result.metadata.get("dose_distribution"))
                agent.memory.store("total_seeds", result.metadata.get("total_seeds", 0))
            result.metadata["step_executed"] = "seed_planning"
            result.message = f"Step 3/5: Seed planning completed. {result.metadata.get('total_seeds', 0)} seeds across {result.metadata.get('num_trajectories', 0)} trajectories."
        return result

    def _step_dose_calc(self, ct_image, seed_info, planning_params):
        """Step 4: Calculate dose distribution."""
        from tool_factory.dose_engine import DoseEngineTool

        agent = _get_agent()
        seed_plan = agent.memory.retrieve("seed_plan") if agent else None
        if not seed_plan:
            return ToolResult(success=False, error="No seed plan available. Run seed_planning first.")

        # Extract seeds from plan
        seeds = []
        for entry in seed_plan:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                seeds.append(entry[1])

        tool = DoseEngineTool()
        result = tool._execute(
            dose_image=ct_image,
            seeds=seeds,
            engine="gaussian",
            seed_sigma=[seed_info.get("length", 4.5), seed_info.get("radius", 0.4) * 3, seed_info.get("radius", 0.4) * 3],
            seed_avr_dose=seed_info.get("seed_avr_dose", 50),
            normalize_min=planning_params.get("image_normalize", [-1000, 3000, 255])[0],
            normalize_max=planning_params.get("image_normalize", [-1000, 3000, 255])[1],
            normalize_scale=planning_params.get("image_normalize", [-1000, 3000, 255])[2],
        )

        if result.success:
            if agent:
                agent.memory.store("dose_distribution", result.data)
            result.metadata["step_executed"] = "dose_calc"
            result.message = f"Step 4/5: Dose calculation completed. Max={result.metadata.get('max_dose', 0):.2f}Gy, Mean={result.metadata.get('mean_dose', 0):.2f}Gy."
        return result

    def _step_dose_eval(self, ctv_mask, oar_mask, planning_params):
        """Step 5: Evaluate dose metrics."""
        from tool_factory.dose_eval import DoseEvaluationTool

        agent = _get_agent()
        dose_array = agent.memory.retrieve("dose_distribution") if agent else None
        if dose_array is None:
            return ToolResult(success=False, error="No dose distribution available. Run dose_calc first.")

        tool = DoseEvaluationTool()
        result = tool._execute(
            dose_array=dose_array,
            ctv_mask=ctv_mask,
            oar_mask=oar_mask,
            prescribed_dose=planning_params.get("in_lowest_energy", 1),
        )

        if result.success:
            if agent:
                agent.memory.store("dose_metrics", result.metadata)
            result.metadata["step_executed"] = "dose_eval"
            v100 = result.metadata.get("v100", 0)
            d90 = result.metadata.get("d90", 0)
            score = result.metadata.get("plan_score", 0)
            result.message = f"Step 5/5: Dose evaluation completed. V100={v100:.1%}, D90={d90:.2f}Gy, Score={score:.0f}/100."
        return result

    def _run_full_pipeline(self, ct_image, radiation_volume, ctv_mask, oar_mask,
                           ref_direc, seed_info, radiation_params, planning_params,
                           dl_params, rf_params, mode, agent):
        """Run the complete planning pipeline."""
        results = {}

        # Step 1: Trajectory initialization
        logger.info("Step 1/5: Trajectory initialization...")
        traj_result = self._step_trajectory_init(ct_image, radiation_volume, ref_direc, radiation_params, planning_params)
        if not traj_result.success:
            return traj_result
        results["trajectories"] = traj_result.metadata.get("trajectories", [])

        # Step 2: Trajectory refinement
        logger.info("Step 2/5: Trajectory refinement...")
        refine_result = self._step_trajectory_refine(radiation_volume, ref_direc, radiation_params)
        if not refine_result.success:
            return refine_result
        results["refined_trajectories"] = refine_result.metadata.get("refined_trajectories", [])

        # Step 3: Seed planning
        logger.info("Step 3/5: Seed placement optimization...")
        seed_result = self._step_seed_planning(ct_image, radiation_volume, seed_info, planning_params, dl_params, rf_params, mode)
        if not seed_result.success:
            return seed_result
        results["seed_plan"] = seed_result.metadata.get("optimal_plan", [])
        results["total_seeds"] = seed_result.metadata.get("total_seeds", 0)

        # Step 4: Dose calculation
        logger.info("Step 4/5: Dose calculation...")
        dose_result = self._step_dose_calc(ct_image, seed_info, planning_params)
        if dose_result.success:
            results["dose_distribution"] = dose_result.data

        # Step 5: Dose evaluation
        logger.info("Step 5/5: Dose evaluation...")
        eval_result = self._step_dose_eval(ctv_mask, oar_mask, planning_params)
        if eval_result.success:
            results["dose_metrics"] = eval_result.metadata

        # Build summary
        total_seeds = results.get("total_seeds", 0)
        metrics = results.get("dose_metrics", {})
        summary = (
            f"Planning completed: {total_seeds} seeds. "
            f"V100={metrics.get('v100', 0):.1%}, D90={metrics.get('d90', 0):.2f}Gy, "
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
