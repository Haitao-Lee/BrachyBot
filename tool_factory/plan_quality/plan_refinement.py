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

    This tool proposes seed-placement changes from the current dose map. It
    does not simulate dose. Any changed plan must be re-evaluated by the
    trained myDoseNet dose path.
    """

    @property
    def name(self) -> str:
        return "plan_refinement"

    @property
    def description(self) -> str:
        return (
            "Iteratively refine seed placement based on dose evaluation feedback. "
            "Suggests seed additions in under-dosed CTV regions. "
            "It does not use an analytical/Gaussian dose approximation; run "
            "dose_engine or planning_pipeline afterward to recompute dose with myDoseNet. "
            "Input: current plan, dose distribution, target metrics. "
            "Output: candidate refined plan plus current metrics."
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
                "candidate_seeds": {"type": "array", "description": "Seed candidates proposed for the next myDoseNet recalculation"},
                "metrics_before": {"type": "object", "description": "Metrics measured on the input dose distribution"},
                "requires_dose_recalculation": {"type": "boolean", "description": "Always true when candidates are proposed"},
                "improved_metrics": {"type": "object", "description": "Backward-compatible metrics object; final metrics are null until myDoseNet is rerun"},
                "iterations_used": {"type": "integer", "description": "Number of refinement iterations"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        current_plan = kwargs["current_plan"]
        dose_distribution = np.asarray(kwargs["dose_distribution"], dtype=np.float32)
        ctv_mask = np.asarray(kwargs["ctv_mask"])
        oar_mask = kwargs.get("oar_mask")
        prescribed_dose = kwargs.get("prescribed_dose", 1.0)
        target_v100 = kwargs.get("target_v100", 0.95)
        max_iterations = kwargs.get("max_iterations", 3)

        if dose_distribution.shape != ctv_mask.shape:
            return ToolResult(
                success=False,
                error=(
                    "dose_distribution and ctv_mask shape mismatch: "
                    f"{dose_distribution.shape} vs {ctv_mask.shape}"
                ),
            )

        ctv_voxels = ctv_mask > 0
        if not np.any(ctv_voxels):
            return ToolResult(success=False, error="CTV mask is empty")

        target_doses = dose_distribution[ctv_voxels]
        if target_doses.size == 0:
            return ToolResult(success=False, error="No dose samples inside CTV")

        current_v100 = np.sum(target_doses >= prescribed_dose) / len(target_doses)
        current_v150 = np.sum(target_doses >= 1.5 * prescribed_dose) / len(target_doses)
        current_v200 = np.sum(target_doses >= 2.0 * prescribed_dose) / len(target_doses)
        current_d90 = float(np.percentile(target_doses, 10)) if target_doses.size else 0.0

        refined_plan = list(current_plan) if isinstance(current_plan, list) else []
        candidate_centers = []
        if current_v100 < target_v100:
            under_dosed = ctv_voxels & (dose_distribution < prescribed_dose)
            candidate_centers = self._candidate_centers_from_underdosed(
                under_dosed,
                dose_distribution,
                refined_plan,
                max(1, int(max_iterations)),
            )

        candidate_seeds = []
        for center in candidate_centers:
            seed = self._suggest_seed_position(center, refined_plan)
            if seed is not None:
                refined_plan.append(seed)
                candidate_seeds.append(seed)

        iterations = len(candidate_seeds)

        improvements = {
            "iterations_used": iterations,
            "seeds_added": iterations,
            "current_v100": float(current_v100),
            "current_v150": float(current_v150),
            "current_v200": float(current_v200),
            "current_d90": current_d90,
            "final_v100": None,
            "requires_dose_recalculation": iterations > 0,
            "dose_engine_required": "myDoseNet",
        }

        metrics_before = {
            "v100": float(current_v100),
            "v150": float(current_v150),
            "v200": float(current_v200),
            "d90": current_d90,
            "prescribed_dose": float(prescribed_dose),
            "target_v100": float(target_v100),
        }

        if iterations:
            message = (
                f"Plan refinement proposed {iterations} seed candidate(s). "
                f"Input V100: {current_v100:.1%}. Recompute dose with myDoseNet "
                "before accepting the refined plan."
            )
        else:
            message = (
                f"Plan refinement did not propose changes. Input V100: {current_v100:.1%}."
            )

        return ToolResult(
            success=True,
            data=refined_plan,
            message=message,
            metadata={
                "refined_plan": refined_plan,
                "candidate_seeds": candidate_seeds,
                "metrics_before": metrics_before,
                "improved_metrics": improvements,
                "requires_dose_recalculation": iterations > 0,
                "dose_engine": "myDoseNet",
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

    def _candidate_centers_from_underdosed(self, under_dosed, dose_distribution, current_plan, max_candidates):
        coords = np.argwhere(under_dosed)
        if coords.size == 0:
            return []

        doses = dose_distribution[under_dosed]
        order = np.argsort(doses)
        existing = self._extract_seed_positions(current_plan)
        selected = []
        min_dim = max(1, min(dose_distribution.shape))
        min_sep = max(4.0, float(min_dim) * 0.04)

        # Prefer the coldest voxels, but keep candidates spatially separated so
        # the follow-up myDoseNet calculation has meaningful alternatives.
        for idx in order:
            candidate = coords[int(idx)].astype(np.float32)
            if self._is_far_enough(candidate, existing + selected, min_sep):
                selected.append(candidate)
                if len(selected) >= max_candidates:
                    break

        if not selected:
            selected.append(np.mean(coords, axis=0).astype(np.float32))
        return selected[:max_candidates]

    @staticmethod
    def _extract_seed_positions(plan):
        positions = []
        if not isinstance(plan, list):
            return positions
        for item in plan:
            pos = None
            if isinstance(item, dict):
                pos = item.get("position") or item.get("pos")
            elif isinstance(item, (list, tuple)) and item:
                pos = item[0]
            try:
                arr = np.asarray(pos, dtype=np.float32).reshape(-1)
                if arr.size >= 3 and np.all(np.isfinite(arr[:3])):
                    positions.append(arr[:3])
            except Exception:
                continue
        return positions

    @staticmethod
    def _is_far_enough(candidate, points, min_sep):
        if not points:
            return True
        for point in points:
            try:
                if float(np.linalg.norm(candidate - np.asarray(point, dtype=np.float32)[:3])) < min_sep:
                    return False
            except Exception:
                continue
        return True


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
