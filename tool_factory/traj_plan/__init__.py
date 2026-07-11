"""
Trajectory Planning Tools
=======================
Tools for generating and refining needle insertion trajectories.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tool_factory import BaseTool, ToolResult

from .trajectory_init import TrajectoryInitTool
from .trajectory_refine import TrajectoryRefineTool


TOOL_REGISTRY = {
    "trajectory_init": TrajectoryInitTool,
    "trajectory_refine": TrajectoryRefineTool,
}


def get_tool(tool_name: str):
    """Get a trajectory planning tool by name."""
    tool_class = TOOL_REGISTRY.get(tool_name)
    if tool_class is None:
        raise ValueError(f"Unknown tool: {tool_name}. Available: {list(TOOL_REGISTRY.keys())}")
    return tool_class()


def list_tools():
    """List all available trajectory planning tools."""
    return list(TOOL_REGISTRY.keys())


class TrajectoryPlanningTool(BaseTool):
    """
    Unified trajectory planning tool combining initialization and refinement.

    Generates candidate needle insertion trajectories through the target volume,
    then refines them based on anatomical constraints and OAR proximity.
    """

    @property
    def name(self) -> str:
        return "trajectory_planning"

    @property
    def description(self) -> str:
        return (
            "Generate and refine needle insertion trajectories for brachytherapy. "
            "First initializes candidate trajectories via directional sampling, "
            "then refines them based on OAR avoidance and optimal path finding. "
            "Input: CT image, radiation volume mask, reference direction. "
            "Output: List of optimized trajectories with origin, direction, and depth."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "dose_image": {"type": "object", "description": "SimpleITK Image of CT scan"},
                "radiation_volume": {"type": "array", "description": "3D NumPy array (1=target, 0=background, 3=OAR)"},
                "ref_direc": {"type": "array", "description": "Reference direction [x,y,z] (auto-compute if None)"},
                "direc_resolution": {"type": "array", "description": "[cone_angle, angular_step, n_rings]"},
                "extract_angle": {"type": "number", "description": "Candidate extraction half-angle in radians"},
                "maximum_candidate_trajectories": {"type": "integer", "default": 500},
                "min_depth": {"type": "number", "description": "Minimum valid target depth in mm", "default": 2},
                "target_value": {"type": "number", "default": 1},
                "background_value": {"type": "number", "default": 0},
                "obstacle_value": {"type": "number", "default": 3},
            },
            "required": ["dose_image", "radiation_volume"],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "trajectories": {"type": "array", "description": "List of trajectory dicts"},
                "num_trajectories": {"type": "integer", "description": "Number of generated trajectories"},
            },
        }

    def _execute(self, **kwargs):
        dose_image = kwargs["dose_image"]
        radiation_volume = kwargs["radiation_volume"]
        ref_direc = kwargs.get("ref_direc")
        target_value = kwargs.get("target_value", 1)
        background_value = kwargs.get("background_value", 0)
        obstacle_value = kwargs.get("obstacle_value", 3)

        init_tool = TrajectoryInitTool()
        init_kwargs = {
            "dose_image": dose_image,
            "radiation_volume": radiation_volume,
            "ref_direc": ref_direc,
            "target_value": target_value,
            "background_value": background_value,
            "obstacle_value": obstacle_value,
        }
        for key in (
            "direc_resolution",
            "extract_angle",
            "maximum_candidate_trajectories",
            "min_depth",
        ):
            if key in kwargs and kwargs[key] is not None:
                init_kwargs[key] = kwargs[key]
        result = init_tool._execute(**init_kwargs)

        if not result.success:
            return result

        trajectories = result.data
        refine_tool = TrajectoryRefineTool()
        refine_result = refine_tool._execute(
            dose_image=dose_image,
            trajectories=trajectories,
            radiation_volume=radiation_volume,
            target_value=target_value,
        )

        final_trajectories = refine_result.data if refine_result.success else trajectories

        return ToolResult(
            success=True,
            data=final_trajectories,
            message=f"Trajectory planning completed. {len(final_trajectories)} trajectories generated.",
            metadata={
                "trajectories": final_trajectories,
                "num_trajectories": len(final_trajectories),
            },
        )


__all__ = [
    "BaseTool",
    "ToolResult",
    "TrajectoryInitTool",
    "TrajectoryRefineTool",
    "TrajectoryPlanningTool",
    "get_tool",
    "list_tools",
]
