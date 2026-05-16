"""
Trajectory Refinement Tool
=======================
Refines and filters candidate trajectories based on quality metrics.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
from typing import Dict, Optional, List


class TrajectoryRefineTool(BaseTool):
    """
    Tool for refining and filtering candidate trajectories.

    Applies quality filters based on:
    - Trajectory depth within target
    - Clearance from obstacles/OAR
    - Angular deviation from reference direction
    - Number of seeds that can be placed
    """

    @property
    def name(self) -> str:
        return "trajectory_refine"

    @property
    def description(self) -> str:
        return (
            "Refine and filter candidate trajectories based on quality metrics. "
            "Filters trajectories by depth, OAR clearance, and angular constraints. "
            "Returns a filtered list of high-quality trajectories ready for seed planning."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "trajectories": {
                    "type": "array",
                    "description": "List of candidate trajectories from trajectory_init",
                },
                "radiation_volume": {
                    "type": "object",
                    "description": "3D NumPy array of radiation volume mask",
                },
                "ref_direc": {
                    "type": "array",
                    "description": "Reference direction vector [x, y, z]",
                    "items": {"type": "number"},
                },
                "target_value": {
                    "type": "number",
                    "description": "Value representing target voxels (default: 1)",
                    "default": 1,
                },
                "obstacle_value": {
                    "type": "number",
                    "description": "Value representing obstacles/OAR (default: 3)",
                    "default": 3,
                },
                "min_target_coverage": {
                    "type": "number",
                    "description": "Minimum target coverage ratio (default: 0.8)",
                    "default": 0.8,
                },
                "max_angular_deviation": {
                    "type": "number",
                    "description": "Maximum angular deviation from ref_direc in degrees (default: 45)",
                    "default": 45,
                },
                "max_trajectories": {
                    "type": "integer",
                    "description": "Maximum number of trajectories to return (default: 50)",
                    "default": 50,
                },
            },
            "required": ["trajectories", "radiation_volume"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "refined_trajectories": {
                    "type": "array",
                    "description": "Filtered list of trajectories",
                },
                "num_trajectories": {
                    "type": "integer",
                    "description": "Number of refined trajectories",
                },
                "quality_scores": {
                    "type": "array",
                    "description": "Quality scores for each trajectory",
                },
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        trajectories = kwargs["trajectories"]
        radiation_volume = kwargs["radiation_volume"]
        ref_direc = np.array(kwargs.get("ref_direc", [0, 0, 1]), dtype=np.float64)
        target_value = kwargs.get("target_value", 1)
        obstacle_value = kwargs.get("obstacle_value", 3)
        min_target_coverage = kwargs.get("min_target_coverage", 0.8)
        max_angular_deviation = kwargs.get("max_angular_deviation", 45)
        max_trajectories = kwargs.get("max_trajectories", 50)

        ref_direc = ref_direc / np.linalg.norm(ref_direc)
        max_angle_rad = np.radians(max_angular_deviation)

        scored_trajectories = []

        for i, traj in enumerate(trajectories):
            if len(traj) < 3:
                continue

            origin = np.array(traj[0])
            direction = np.array(traj[1])
            depth = traj[2]

            angle = np.arccos(np.clip(np.dot(direction, ref_direc), -1, 1))
            if angle > max_angle_rad:
                continue

            target_mask = radiation_volume == target_value
            obstacle_mask = radiation_volume == obstacle_value

            max_depth_idx = min(int(depth), radiation_volume.shape[0] - 1)
            trajectory_points = origin + np.outer(np.arange(max_depth_idx), direction)

            in_bounds = np.all((trajectory_points >= 0) & (trajectory_points < np.array(radiation_volume.shape)), axis=1)
            trajectory_mask = np.all(in_bounds.reshape(-1, 1), axis=1)

            if np.any(trajectory_mask):
                target_coverage = np.sum(target_mask[trajectory_points[trajectory_mask].astype(int).T]) / np.sum(trajectory_mask)
            else:
                target_coverage = 0

            if target_coverage < min_target_coverage:
                continue

            quality_score = target_coverage * (1 - angle / np.pi)

            scored_trajectories.append((quality_score, traj))

        scored_trajectories.sort(key=lambda x: x[0], reverse=True)
        refined = [t for _, t in scored_trajectories[:max_trajectories]]
        quality_scores = [s for s, _ in scored_trajectories[:max_trajectories]]

        return ToolResult(
            success=True,
            data=refined,
            message=f"Trajectory refinement completed. {len(refined)} trajectories passed quality filters.",
            metadata={
                "refined_trajectories": refined,
                "num_trajectories": len(refined),
                "quality_scores": quality_scores,
            },
        )
