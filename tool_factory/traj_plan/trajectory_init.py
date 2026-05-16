"""
Trajectory Initialization Tool
===========================
Generates candidate needle insertion trajectories using direction sampling.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
from typing import Dict, Optional, List


class TrajectoryInitTool(BaseTool):
    """
    Tool for generating candidate needle/catheter insertion trajectories.

    Uses conical direction sampling around a reference direction to generate
    candidate trajectories through the target volume. Each trajectory consists
    of an origin point, direction vector, and depth information.
    """

    @property
    def name(self) -> str:
        return "trajectory_init"

    @property
    def description(self) -> str:
        return (
            "Generate candidate needle insertion trajectories for brachytherapy planning. "
            "Uses direction sampling around a reference direction to find optimal paths through the target. "
            "Each trajectory contains origin point, direction vector, and penetration depth. "
            "This is the prerequisite step before seed placement optimization."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "dose_image": {
                    "type": "object",
                    "description": "SimpleITK Image of the CT scan",
                },
                "radiation_volume": {
                    "type": "object",
                    "description": "3D NumPy array of radiation volume mask (1=target, 0=background, obstacle_value=OAR)",
                },
                "ref_direc": {
                    "type": "array",
                    "description": "Reference direction vector [x, y, z] (default: auto-compute via PCA)",
                    "items": {"type": "number"},
                },
                "direc_resolution": {
                    "type": "array",
                    "description": "Direction sampling resolution [cone_half_angle, angular_step, n_rings] (default: [30, 3, 2])",
                    "items": {"type": "number"},
                },
                "extract_angle": {
                    "type": "number",
                    "description": "Cone half-angle for candidate extraction in degrees (default: 30)",
                    "default": 30,
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
                    "description": "Value representing obstacles/OAR (default: 3)",
                    "default": 3,
                },
                "maximum_candidate_trajectories": {
                    "type": "integer",
                    "description": "Maximum number of candidate trajectories (default: 500)",
                    "default": 500,
                },
                "min_depth": {
                    "type": "number",
                    "description": "Minimum trajectory depth in mm (default: 2)",
                    "default": 2,
                },
            },
            "required": ["dose_image", "radiation_volume"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "trajectories": {
                    "type": "array",
                    "description": "List of trajectories, each [origin, direction, depth, background_depths]",
                },
                "num_trajectories": {
                    "type": "integer",
                    "description": "Total number of candidate trajectories generated",
                },
                "reference_direction": {
                    "type": "array",
                    "description": "Reference direction vector used for sampling",
                },
                "max_depth_mm": {
                    "type": "number",
                    "description": "Maximum trajectory depth in mm",
                },
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        import core
        import utilizations

        dose_image = kwargs["dose_image"]
        radiation_volume = kwargs["radiation_volume"]
        ref_direc = kwargs.get("ref_direc")
        direc_resolution = kwargs.get("direc_resolution", [30, 3, 2])
        extract_angle = kwargs.get("extract_angle", 30)
        target_value = kwargs.get("target_value", 1)
        background_value = kwargs.get("background_value", 0)
        obstacle_value = kwargs.get("obstacle_value", 3)
        maximum_candidate_trajectories = kwargs.get("maximum_candidate_trajectories", 500)
        min_depth = kwargs.get("min_depth", 2)

        if ref_direc is None:
            ref_direc = utilizations.get_reference_direction(radiation_volume, target_value)

        ref_direc = np.array(ref_direc, dtype=np.float64)
        ref_direc = ref_direc / np.linalg.norm(ref_direc)

        trajectories = core.init_plan(
            dose_image=dose_image,
            radiation_volume=radiation_volume,
            ref_direc=ref_direc,
            direc_resolution=direc_resolution,
            extract_angle=extract_angle,
            target_value=target_value,
            background_value=background_value,
            obstacle_value=obstacle_value,
            maximum_candidate_trajectories=maximum_candidate_trajectories,
            min_depth=min_depth,
        )

        max_depth = 0
        for t in trajectories:
            if len(t) > 2 and t[2] > max_depth:
                max_depth = t[2]

        traj_info = []
        for t in trajectories:
            traj_info.append({
                "origin": t[0].tolist() if hasattr(t[0], "tolist") else list(t[0]),
                "direction": t[1].tolist() if hasattr(t[1], "tolist") else list(t[1]),
                "depth": float(t[2]) if len(t) > 2 else 0,
            })

        return ToolResult(
            success=True,
            data=trajectories,
            message=f"Trajectory initialization completed. Generated {len(trajectories)} candidate trajectories.",
            metadata={
                "trajectories": trajectories,
                "trajectories_info": traj_info,
                "num_trajectories": len(trajectories),
                "reference_direction": ref_direc.tolist(),
                "max_depth_mm": float(max_depth),
            },
        )
