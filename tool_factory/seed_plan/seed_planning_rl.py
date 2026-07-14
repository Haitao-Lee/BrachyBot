"""
RL-Based Seed Planning Tool
=========================
Optimizes seed placement using Hierarchical REINFORCE reinforcement learning.
"""

import sys
import os


from tool_factory import BaseTool, ToolResult
from .model_support import resolve_dose_model
import numpy as np
from typing import Dict, Optional


class RLSeedPlanningTool(BaseTool):
    """
    Tool for RL-based seed placement optimization using Hierarchical REINFORCE.

    Uses hierarchical reinforcement learning:
    1. High-level: Select best trajectories via REINFORCE policy gradient
    2. Low-level: Optimize seed positions along selected trajectories
    3. CNN surrogate for fast dose prediction during training
    """

    @property
    def name(self) -> str:
        return "seed_planning_rl"

    @property
    def description(self) -> str:
        return (
            "Generate optimized seed placement using Hierarchical REINFORCE reinforcement learning. "
            "High-level policy selects optimal trajectories, low-level policy optimizes seed positions. "
            "Uses CNN surrogate for fast dose prediction during RL training."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "trajectories": {
                    "type": "array",
                    "description": "List of candidate trajectories from trajectory planning",
                },
                "radiation_volume": {
                    "type": "object",
                    "description": "3D NumPy array of radiation volume (1=target, 0=background, obstacle_value=OAR)",
                },
                "dose_image": {
                    "type": "object",
                    "description": "SimpleITK Image of the CT scan for DL inference",
                },
                "dl_params": {
                    "type": "object",
                    "description": "Deep learning parameters for dose CNN model",
                },
                "dose_cal_model": {
                    "type": "object",
                    "description": "Optional injected dose_unet_spacing1mm model; otherwise the configured checkpoint is loaded",
                },
                "rf_params": {
                    "type": "object",
                    "description": "Reinforcement learning parameters {max_episodes, bandwidth}",
                },
                "target_value": {
                    "type": "number",
                    "description": "Value representing target voxels (default: 1)",
                    "default": 1,
                },
                "in_lowest_dose": {
                    "type": "number",
                    "description": "Minimum target dose in Gy (default: 1)",
                    "default": 1,
                },
                "out_highest_dose": {
                    "type": "number",
                    "description": "Maximum healthy tissue dose in Gy (default: 1)",
                    "default": 1,
                },
                "DVH_rate": {
                    "type": "number",
                    "description": "Target DVH coverage rate (default: 0.9)",
                    "default": 0.9,
                },
                "infer_img_size": {
                    "type": "array",
                    "description": "DoseUNet sliding-window patch size [z, y, x] (default: [64, 64, 64])",
                    "items": {"type": "integer"},
                },
                "interval_rate": {
                    "type": "number",
                    "description": "Interval rate for RL sub-positions (default: 2)",
                    "default": 2,
                },
                "seed_info": {
                    "type": "object",
                    "description": "Seed properties {radius, length, num_of_seeds, seed_avr_dose}",
                },
                "image_normalize": {
                    "type": "array",
                    "description": "Image normalization [min, max, scale] (default: [-1000, 3000, 255])",
                },
            },
            "required": ["trajectories", "radiation_volume", "dose_image"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "optimal_plan": {
                    "type": "array",
                    "description": "Optimized plan: list of [trajectory, seeds, per_seed_doses]",
                },
                "dose_distribution": {
                    "type": "object",
                    "description": "3D NumPy array of cumulative dose distribution",
                },
                "total_seeds": {
                    "type": "integer",
                    "description": "Total number of seeds placed",
                },
                "num_trajectories": {
                    "type": "integer",
                    "description": "Number of trajectories used",
                },
                "training_reward": {
                    "type": "number",
                    "description": "Final RL training reward achieved",
                },
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        from plans import core

        trajectories = kwargs["trajectories"]
        radiation_volume = kwargs["radiation_volume"]
        dose_image = kwargs["dose_image"]
        dl_params = kwargs.get("dl_params", {})
        dose_cal_model, model_error = resolve_dose_model(kwargs, dl_params)
        if dose_cal_model is None:
            return ToolResult(success=False, error=model_error or "Dose model is unavailable")
        rf_params = kwargs.get("rf_params", {"max_episodes": 100, "bandwidth": 0.1})
        target_value = kwargs.get("target_value", 1)
        in_lowest_dose = kwargs.get("in_lowest_dose", 1)
        out_highest_dose = kwargs.get("out_highest_dose", 1)
        DVH_rate = kwargs.get("DVH_rate", 0.9)
        infer_img_size = tuple(kwargs.get("infer_img_size", (64, 64, 64)))
        interval_rate = kwargs.get("interval_rate", 2)
        seed_info = kwargs.get("seed_info", {"radius": 0.4, "length": 4.5, "seed_avr_dose": 50})
        image_normalize = kwargs.get("image_normalize", [-1000, 3000, 255])

        norm_min, norm_max, norm_scale = image_normalize[0], image_normalize[1], image_normalize[2]

        optimal_plan = core.optimal_plan_rf(
            init_trajectories=trajectories,
            radiation_volume=radiation_volume,
            dose_image=dose_image,
            dose_cal_model=dose_cal_model,
            dl_params=dl_params,
            rf_params=rf_params,
            interval_rate=interval_rate,
            target_value=target_value,
            infer_img_size=infer_img_size,
            in_lowest_dose=in_lowest_dose,
            out_highest_dose=out_highest_dose,
            DVH_rate=DVH_rate,
            seed_info=seed_info,
            image_normalize_min=norm_min,
            image_normalize_max=norm_max,
            image_normalize_scale=norm_scale,
        )

        total_seeds = 0
        dose_sum = np.zeros_like(radiation_volume).astype(float)

        if optimal_plan and isinstance(optimal_plan, (list, tuple)):
            for entry in optimal_plan:
                if isinstance(entry, (list, tuple)) and len(entry) >= 3:
                    seeds = entry[1]
                    seed_doses = entry[2]
                    if isinstance(seeds, list):
                        total_seeds += len(seeds)
                    if isinstance(seed_doses, list):
                        for sd in seed_doses:
                            if isinstance(sd, np.ndarray):
                                dose_sum += sd

        return ToolResult(
            success=True,
            data=optimal_plan,
            message=f"RL-based seed planning completed. {total_seeds} seeds placed across {len(optimal_plan) if optimal_plan else 0} trajectories.",
            metadata={
                "optimal_plan": optimal_plan,
                "dose_distribution": dose_sum,
                "total_seeds": total_seeds,
                "num_trajectories": len(optimal_plan) if optimal_plan else 0,
            },
        )
