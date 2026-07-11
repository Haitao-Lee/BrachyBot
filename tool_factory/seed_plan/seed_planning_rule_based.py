"""
Rule-Based Seed Planning Tool
===========================
Optimizes seed placement using iterative greedy algorithm with DL refinement.
"""

import sys
import os


from tool_factory import BaseTool, ToolResult
from .model_support import resolve_dose_model
import numpy as np
from typing import Dict, Optional


class RuleBasedSeedPlanningTool(BaseTool):
    """
    Tool for rule-based seed placement optimization.

    Uses iterative greedy placement with DL-based dose calculation:
    1. Place seeds at optimal positions along trajectories
    2. Calculate dose using CNN surrogate model
    3. Refine positions based on DVH metrics
    4. Repeat until convergence or max iterations
    """

    @property
    def name(self) -> str:
        return "seed_planning_rule_based"

    @property
    def description(self) -> str:
        return (
            "Generate optimized seed placement using iterative greedy algorithm with DL dose refinement. "
            "Places seeds along trajectories to maximize target coverage while minimizing OAR dose. "
            "Supports DVH-based refinement and distance filtering between seeds."
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
                    "description": "Deep learning parameters for dose calculation",
                },
                "dose_cal_model": {
                    "type": "object",
                    "description": "Optional injected myDoseNet model; otherwise the configured checkpoint is loaded",
                },
                "target_value": {
                    "type": "number",
                    "description": "Value representing target voxels (default: 1)",
                    "default": 1,
                },
                "background_value": {
                    "type": "number",
                    "description": "Value representing background (default: 0)",
                    "default": 0,
                },
                "obstacle_value": {
                    "type": "number",
                    "description": "Value representing OAR (default: 3)",
                    "default": 3,
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
                    "description": "CNN inference patch size [h, w, d] (default: [32, 32, 32])",
                    "items": {"type": "integer"},
                },
                "lower_bound": {
                    "type": "number",
                    "description": "Minimum seed distance filter (default: 0.8)",
                    "default": 0.8,
                },
                "upper_bound": {
                    "type": "number",
                    "description": "Maximum seed distance filter (default: 10)",
                    "default": 10,
                },
                "distance_rate": {
                    "type": "number",
                    "description": "Distance filter rate (default: 0.8)",
                    "default": 0.8,
                },
                "iter_rate": {
                    "type": "integer",
                    "description": "Number of refinement iterations (default: 2)",
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
        target_value = kwargs.get("target_value", 1)
        background_value = kwargs.get("background_value", 0)
        obstacle_value = kwargs.get("obstacle_value", 3)
        in_lowest_dose = kwargs.get("in_lowest_dose", 1)
        out_highest_dose = kwargs.get("out_highest_dose", 1)
        DVH_rate = kwargs.get("DVH_rate", 0.9)
        infer_img_size = tuple(kwargs.get("infer_img_size", (32, 32, 32)))
        lower_bound = kwargs.get("lower_bound", 0.8)
        upper_bound = kwargs.get("upper_bound", 10)
        distance_rate = kwargs.get("distance_rate", 0.8)
        iter_rate = kwargs.get("iter_rate", 2)
        seed_info = kwargs.get("seed_info", {"radius": 0.4, "length": 4.5, "seed_avr_dose": 50})
        image_normalize = kwargs.get("image_normalize", [-1000, 3000, 255])

        norm_min, norm_max, norm_scale = image_normalize[0], image_normalize[1], image_normalize[2]

        optimal_plan = core.optimal_plan(
            init_trajectories=trajectories,
            radiation_volume=radiation_volume,
            dose_image=dose_image,
            dose_cal_model=dose_cal_model,
            dl_params=dl_params,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            distance_rate=distance_rate,
            target_value=target_value,
            background_value=background_value,
            obstacle_value=obstacle_value,
            infer_img_size=infer_img_size,
            in_lowest_dose=in_lowest_dose,
            out_highest_dose=out_highest_dose,
            DVH_rate=DVH_rate,
            seed_info=seed_info,
            iter_rate=iter_rate,
            image_normalize_min=norm_min,
            image_normalize_max=norm_max,
            image_normalize_scale=norm_scale,
        )

        total_seeds = 0
        dose_sum = np.zeros_like(radiation_volume).astype(float)

        if optimal_plan:
            for traj, seeds, seed_doses in optimal_plan:
                total_seeds += len(seeds)
                for sd in seed_doses:
                    dose_sum += sd

        return ToolResult(
            success=True,
            data=optimal_plan,
            message=f"Rule-based seed planning completed. {total_seeds} seeds placed across {len(optimal_plan) if optimal_plan else 0} trajectories.",
            metadata={
                "optimal_plan": optimal_plan,
                "dose_distribution": dose_sum,
                "total_seeds": total_seeds,
                "num_trajectories": len(optimal_plan) if optimal_plan else 0,
            },
        )
