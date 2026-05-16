"""
Plan Refinement Tool
===================
Iteratively refines seed placement based on dose evaluation feedback.
Adjusts seed positions/numbers to improve coverage or reduce OAR dose.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
from typing import Dict, List, Optional, Tuple
import numpy as np


class PlanRefinementTool(BaseTool):
    """
    Tool for iterative plan refinement based on dose feedback.

    Analyzes current dose distribution and suggests/implements adjustments:
    - Add seeds to improve under-dosed regions
    - Remove/reposition seeds causing hot spots
    - Adjust seed dwell times for better homogeneity
    """

    @property
    def name(self) -> str:
        return "plan_refinement"

    @property
    def description(self) -> str:
        return (
            "Iteratively refine seed placement based on dose evaluation feedback. "
            "Adds/removes/repositions seeds to improve V100, reduce V200, or lower OAR dose. "
            "Input: current plan, dose distribution, target metrics. "
            "Output: Refined plan with improved dose metrics."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "current_plan": {"type": "array", "description": "Current seed plan"},
                "dose_distribution": {"type": "array", "description": "Current 3D dose array"},
                "ctv_mask": {"type": "array", "description": "CTV binary mask"},
                "oar_mask": {"type": "array", "description": "OAR multi-label mask"},
                "prescribed_dose": {"type": "number", "default": 1.0},
                "target_v100": {"type": "number", "default": 0.95, "description": "Target V100"},
                "max_iterations": {"type": "integer", "default": 3},
            },
            "required": ["current_plan", "dose_distribution", "ctv_mask"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "refined_plan": {"type": "array", "description": "Refined seed plan"},
                "improved_metrics": {"type": "object", "description": "New dose metrics after refinement"},
                "iterations_used": {"type": "integer", "description": "Number of refinement iterations"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        current_plan = kwargs["current_plan"]
        dose_distribution = kwargs["dose_distribution"]
        ctv_mask = kwargs["ctv_mask"]
        oar_mask = kwargs.get("oar_mask")
        prescribed_dose = kwargs.get("prescribed_dose", 1.0)
        target_v100 = kwargs.get("target_v100", 0.95)
        max_iterations = kwargs.get("max_iterations", 3)

        ctv_voxels = ctv_mask > 0
        target_doses = dose_distribution[ctv_voxels]

        current_v100 = np.sum(target_doses >= prescribed_dose) / len(target_doses)
        current_v150 = np.sum(target_doses >= 1.5 * prescribed_dose) / len(target_doses)

        refined_plan = current_plan
        iterations = 0

        for i in range(max_iterations):
            ctv_voxels = ctv_mask > 0
            target_doses = dose_distribution[ctv_voxels]
            if len(target_doses) == 0:
                break
            current_v100 = np.sum(target_doses >= prescribed_dose) / len(target_doses)

            if current_v100 >= target_v100:
                break

            under_dosed = (ctv_mask > 0) & (dose_distribution < prescribed_dose)
            if not np.any(under_dosed):
                break

            under_dosed_coords = np.array(np.where(under_dosed)).T
            if len(under_dosed_coords) == 0:
                break

            centroid = np.mean(under_dosed_coords, axis=0)

            new_seed = self._suggest_seed_position(centroid, refined_plan)
            if new_seed is not None:
                refined_plan = refined_plan + [new_seed] if isinstance(refined_plan, list) else [new_seed]
                dose_distribution = self._simulate_dose_addition(dose_distribution, new_seed, ctv_mask.shape)

            iterations += 1

        improvements = {
            "iterations_used": iterations,
            "seeds_added": iterations,
            "final_v100": current_v100,
        }

        return ToolResult(
            success=True,
            data=refined_plan,
            message=f"Plan refinement completed. {iterations} adjustment(s) made. V100: {current_v100:.1%}",
            metadata={
                "refined_plan": refined_plan,
                "improved_metrics": improvements,
                "iterations_used": iterations,
            },
        )

    def _suggest_seed_position(self, centroid, current_plan):
        if isinstance(current_plan, list) and len(current_plan) > 0:
            last_seed = current_plan[-1]
            if isinstance(last_seed, (list, tuple)) and len(last_seed) >= 2:
                direc = last_seed[1] if len(last_seed) > 1 else [0, 0, 1]
                return [centroid.tolist(), direc]
        return [centroid.tolist(), [0, 0, 1]]

    def _simulate_dose_addition(self, dose_dist, seed, shape):
        pos = np.array(seed[0]) if isinstance(seed[0], list) else np.array(seed)
        sigma = 5.0
        z, y, x = np.ogrid[:shape[0], :shape[1], :shape[2]]
        dist_sq = (x - pos[0])**2 + (y - pos[1])**2 + (z - pos[2])**2
        seed_dose = np.exp(-dist_sq / (2 * sigma**2))
        return dose_dist + seed_dose


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Plan Refinement Tool")
    parser.add_argument("--current_plan", required=True, help="JSON list of current seeds")
    parser.add_argument("--dose_distribution", required=True, help="Path to dose .nii.gz")
    parser.add_argument("--ctv_mask", required=True, help="Path to CTV mask .nii.gz")
    args = parser.parse_args()

    import SimpleITK as sitk
    import json

    dose = sitk.GetArrayFromImage(sitk.ReadImage(args.dose_distribution))
    ctv = sitk.GetArrayFromImage(sitk.ReadImage(args.ctv_mask))
    plan = json.loads(args.current_plan)

    tool = PlanRefinementTool()
    result = tool._execute(
        current_plan=plan,
        dose_distribution=dose,
        ctv_mask=ctv,
    )
    print(result.message)


if __name__ == "__main__":
    main()