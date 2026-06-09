"""
Seed Planning Unified Tool
========================
Unified interface for seed placement optimization supporting multiple modes.
"""

import sys
import os


from tool_factory import BaseTool, ToolResult
import numpy as np
from typing import Dict, Optional


class SeedPlanningTool(BaseTool):
    """
    Unified tool for seed placement optimization.

    Supports multiple planning modes:
    - 'rule_based': Iterative greedy with DL refinement
    - 'rl': Hierarchical REINFORCE reinforcement learning

    Takes trajectories, CT image, and radiation volume as input,
    returns optimized seed positions and dose distribution.
    """

    @property
    def name(self) -> str:
        return "seed_planning"

    @property
    def description(self) -> str:
        return (
            "Generate optimized seed placement for brachytherapy. "
            "Supports 'rule_based' (iterative greedy + DL) and 'rl' (REINFORCE) modes. "
            "Input: trajectories, CT image, radiation volume. "
            "Output: seed positions, dose distribution, DVH metrics."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "trajectories": {
                    "type": "array",
                    "description": "List of candidate trajectories",
                },
                "radiation_volume": {
                    "type": "object",
                    "description": "3D NumPy array (1=target, 0=background, obstacle_value=OAR)",
                },
                "dose_image": {
                    "type": "object",
                    "description": "SimpleITK Image of CT scan",
                },
                "mode": {
                    "type": "string",
                    "description": "Planning mode: 'rule_based' or 'rl' (default: 'rule_based')",
                    "enum": ["rule_based", "rl"],
                    "default": "rule_based",
                },
                "dl_params": {
                    "type": "object",
                    "description": "Deep learning parameters for dose calculation",
                },
                "rf_params": {
                    "type": "object",
                    "description": "RL parameters {max_episodes, bandwidth} (for 'rl' mode)",
                },
                "seed_info": {
                    "type": "object",
                    "description": "Seed properties {radius, length, num_of_seeds, seed_avr_dose}",
                },
                "target_value": {
                    "type": "number",
                    "description": "Target label value (default: 1)",
                    "default": 1,
                },
                "background_value": {
                    "type": "number",
                    "description": "Background label value (default: 0)",
                    "default": 0,
                },
                "obstacle_value": {
                    "type": "number",
                    "description": "OAR label value (default: 3)",
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
                    "description": "CNN patch size [h, w, d] (default: [32, 32, 32])",
                },
                "image_normalize": {
                    "type": "array",
                    "description": "Image norm [min, max, scale] (default: [-1000, 3000, 255])",
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
                    "description": "Optimized plan: [trajectory, seeds, per_seed_doses]",
                },
                "dose_distribution": {
                    "type": "object",
                    "description": "3D NumPy array of cumulative dose",
                },
                "total_seeds": {
                    "type": "integer",
                    "description": "Total number of seeds",
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
        dose_cal_model = kwargs.get("dose_cal_model")
        mode = kwargs.get("mode", "rule_based")
        dl_params = kwargs.get("dl_params", {})
        seed_info = kwargs.get("seed_info", {"radius": 0.4, "length": 4.5, "seed_avr_dose": 50})
        target_value = kwargs.get("target_value", 1)
        background_value = kwargs.get("background_value", 0)
        obstacle_value = kwargs.get("obstacle_value", 3)
        in_lowest_dose = kwargs.get("in_lowest_dose", 1)
        out_highest_dose = kwargs.get("out_highest_dose", 1)
        DVH_rate = kwargs.get("DVH_rate", 0.9)
        infer_img_size = tuple(kwargs.get("infer_img_size", (32, 32, 32)))
        image_normalize = kwargs.get("image_normalize", [-1000, 3000, 255])

        norm_min, norm_max, norm_scale = image_normalize[0], image_normalize[1], image_normalize[2]

        if mode == "rl":
            rf_params = kwargs.get("rf_params", {"max_episodes": 100, "bandwidth": 0.1})
            interval_rate = kwargs.get("interval_rate", 2)
            optimal_plan = core.optimal_plan_rf(
                init_trajectories=trajectories,
                radiation_volume=radiation_volume,
                dose_image=dose_image,
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
        else:
            lower_bound = kwargs.get("lower_bound", 0.8)
            upper_bound = kwargs.get("upper_bound", 10)
            distance_rate = kwargs.get("distance_rate", 0.8)
            iter_rate = kwargs.get("iter_rate", 2)

            optimal_plan, _ = core.optimal_plan(
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
        num_trajectories = 0

        if optimal_plan:
            if isinstance(optimal_plan, list):
                num_trajectories = len(optimal_plan)
                for entry in optimal_plan:
                    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                        seeds = entry[1]
                        if isinstance(seeds, list):
                            total_seeds += len(seeds)
                        if len(entry) >= 3:
                            seed_doses = entry[2]
                            if isinstance(seed_doses, list):
                                for sd in seed_doses:
                                    if isinstance(sd, np.ndarray):
                                        dose_sum += sd

        return ToolResult(
            success=True,
            data=optimal_plan,
            message=f"Seed planning ({mode}) completed. {total_seeds} seeds across {num_trajectories} trajectories.",
            metadata={
                "optimal_plan": optimal_plan,
                "dose_distribution": dose_sum,
                "total_seeds": total_seeds,
                "num_trajectories": num_trajectories,
                "mode": mode,
            },
        )
