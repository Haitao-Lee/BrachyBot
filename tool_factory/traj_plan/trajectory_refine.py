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
                "spacing": {
                    "type": "array",
                    "description": "Voxel spacing in the same axis order as radiation_volume, used to convert depth_mm to sampling steps.",
                    "items": {"type": "number"},
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
        spacing = kwargs.get("spacing")
        spacing_arr = None
        if spacing is not None:
            spacing_arr = np.asarray(spacing, dtype=np.float64).flatten()
            if spacing_arr.size != 3 or not np.all(np.isfinite(spacing_arr)) or np.any(spacing_arr <= 0):
                return ToolResult(success=False, error="spacing must contain three positive finite values")

        ref_norm = np.linalg.norm(ref_direc)
        if not np.isfinite(ref_norm) or ref_norm <= 1e-8:
            return ToolResult(success=False, error="ref_direc must be finite and non-zero")
        ref_direc = ref_direc / ref_norm
        max_angle_rad = np.radians(max_angular_deviation)

        scored_trajectories = []

        for i, traj in enumerate(trajectories):
            if len(traj) < 3:
                continue

            origin = np.array(traj[0]).flatten()
            direction = np.array(traj[1]).flatten()
            direction_norm = np.linalg.norm(direction)
            if direction.size != 3 or not np.isfinite(direction_norm) or direction_norm <= 1e-8:
                continue
            direction = direction / direction_norm
            # t[4] = scalar total depth, t[2] = list of target segment lengths
            depth = traj[4] if len(traj) > 4 else (sum(traj[2]) if len(traj) > 2 else 0)

            angle = np.arccos(np.clip(np.dot(direction, ref_direc), -1, 1))
            if angle > max_angle_rad:
                continue

            target_mask = radiation_volume == target_value
            obstacle_mask = radiation_volume == obstacle_value

            if spacing_arr is not None:
                step_mm = float(np.linalg.norm(direction * spacing_arr))
                max_depth_idx = int(np.ceil(float(depth) / max(step_mm, 1e-6)))
            else:
                max_depth_idx = int(depth)
            max_depth_idx = max(1, min(max_depth_idx, max(radiation_volume.shape) - 1))
            trajectory_points = origin + np.outer(np.arange(max_depth_idx), direction)

            # Check bounds for each point
            in_bounds = np.all((trajectory_points >= 0) & (trajectory_points < np.array(radiation_volume.shape)), axis=1)
            valid_points = trajectory_points[in_bounds]

            if len(valid_points) > 0:
                # Index into target_mask using valid points
                indices = valid_points.astype(int)
                if np.any(obstacle_mask[indices[:, 0], indices[:, 1], indices[:, 2]]):
                    continue
                target_coverage = np.sum(target_mask[indices[:, 0], indices[:, 1], indices[:, 2]]) / len(valid_points)
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
