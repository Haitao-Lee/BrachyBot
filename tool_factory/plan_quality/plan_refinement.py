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
from typing import Dict
import copy
from collections.abc import Mapping
import numpy as np


class PlanRefinementTool(BaseTool):
    """
    Tool for iterative plan refinement based on dose feedback.

    This tool proposes seed-placement changes from the current dose map. It
    does not simulate dose. Any changed plan must be re-evaluated by the
    trained dose_unet_spacing1mm dose path.
    """

    def __init__(self, agent=None):
        # ToolRegistry.bind_workspace replaces this binding on the detached
        # executor. Provider kwargs cannot downgrade its proposal policy.
        self._agent = agent

    @property
    def name(self) -> str:
        return "plan_refinement"

    @property
    def description(self) -> str:
        return (
            "Iteratively refine seed placement based on dose evaluation feedback. "
            "Owned timepoint calls read current total dose in Gy and return unvalidated "
            "advisory under-dose ZYX voxel locations, with the current plan unmodified. "
            "No feasible seed or channel is accepted. Guide-first path admission, fixed-implant "
            "capsule collision checks and dose evaluation require separately authorized canonical planning. "
            "Legacy preoperative calls may suggest unvalidated seeds using an existing explicit axis. "
            "It does not compute a plan, dose or segmentation. "
            "Input: current plan, dose distribution, target metrics. "
            "Output: advisory locations or legacy candidates, validation limits and current metrics."
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
                "prescribed_dose": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "Prescription in the same units as dose_distribution",
                },
                "target_v100": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Source-backed or explicitly configured target V100 fraction",
                },
                "max_iterations": {"type": "integer", "minimum": 1, "maximum": 128, "default": 3},
            },
            "required": [
                "current_plan",
                "dose_distribution",
                "ctv_mask",
                "prescribed_dose",
                "target_v100",
            ],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "refined_plan": {"type": "array", "description": "Refined seed plan"},
                "candidate_seeds": {"type": "array", "description": "Seed candidates proposed for the next dose_unet_spacing1mm recalculation"},
                "advisory_locations": {"type": "array", "description": "Under-dose array ZYX voxels; not physical seed positions or admitted channels"},
                "channel_proposals": {"type": "array", "description": "Always empty: this tool does not admit feasible channels"},
                "proposal_kind": {"type": "string"},
                "feasibility_validated": {"type": "boolean"},
                "metrics_before": {"type": "object", "description": "Metrics measured on the input dose distribution"},
                "requires_dose_recalculation": {"type": "boolean", "description": "Always true when candidates are proposed"},
                "improved_metrics": {"type": "object", "description": "Backward-compatible metrics object; final metrics are null until dose_unet_spacing1mm is rerun"},
                "iterations_used": {"type": "integer", "description": "Number of refinement iterations"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        candidate_only = self._candidate_only(kwargs)
        current_plan = kwargs["current_plan"]
        dose_distribution = np.asarray(kwargs["dose_distribution"], dtype=np.float32)
        ctv_mask = np.asarray(kwargs["ctv_mask"])
        oar_mask = kwargs.get("oar_mask")
        prescribed_dose = kwargs.get("prescribed_dose")
        target_v100 = kwargs.get("target_v100")
        max_iterations = kwargs.get("max_iterations", 3)

        try:
            prescribed_dose = float(prescribed_dose)
        except (TypeError, ValueError, OverflowError):
            prescribed_dose = np.nan
        if not np.isfinite(prescribed_dose) or prescribed_dose <= 0:
            return ToolResult(
                success=False,
                error="prescribed_dose must be explicitly provided and greater than zero",
            )
        try:
            target_v100 = float(target_v100)
        except (TypeError, ValueError, OverflowError):
            target_v100 = np.nan
        if not np.isfinite(target_v100) or not 0.0 <= target_v100 <= 1.0:
            return ToolResult(
                success=False,
                error=(
                    "target_v100 must be an explicit source-backed or configured "
                    "fraction between 0 and 1"
                ),
            )
        if type(max_iterations) is not int or not 1 <= max_iterations <= 128:
            return ToolResult(success=False, error="max_iterations must be an integer between 1 and 128")
        if not isinstance(current_plan, list):
            return ToolResult(success=False, error="current_plan must be a list")
        if (dose_distribution.ndim != 3 or not dose_distribution.size
                or not np.isfinite(dose_distribution).all() or np.any(dose_distribution < 0)):
            return ToolResult(success=False, error="dose_distribution must be finite nonnegative nonempty 3D dose")

        if dose_distribution.shape != ctv_mask.shape:
            return ToolResult(
                success=False,
                error=(
                    "dose_distribution and ctv_mask shape mismatch: "
                    f"{dose_distribution.shape} vs {ctv_mask.shape}"
                ),
            )
        if not np.isfinite(ctv_mask).all() or np.any(ctv_mask < 0):
            return ToolResult(success=False, error="ctv_mask must contain finite nonnegative labels")
        oar_clearance = None
        if oar_mask is not None:
            oar_mask = np.asarray(oar_mask)
            if oar_mask.shape != dose_distribution.shape:
                return ToolResult(
                    success=False,
                    error=(
                        "dose_distribution and oar_mask shape mismatch: "
                        f"{dose_distribution.shape} vs {oar_mask.shape}"
                    ),
                )
            if not np.isfinite(oar_mask).all() or np.any(oar_mask < 0):
                return ToolResult(success=False, error="oar_mask must contain finite nonnegative labels")
            if not candidate_only and np.any(oar_mask > 0):
                from scipy.ndimage import distance_transform_edt

                oar_clearance = distance_transform_edt(oar_mask == 0)

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

        refined_plan = copy.deepcopy(current_plan)
        candidate_centers = []
        if current_v100 < target_v100:
            under_dosed = ctv_voxels & (dose_distribution < prescribed_dose)
            # Clearance ranking cannot authorize a seed in an OAR voxel.
            if oar_mask is not None:
                under_dosed &= oar_mask == 0
            candidate_centers = self._candidate_centers_from_underdosed(
                under_dosed,
                dose_distribution,
                [] if candidate_only else refined_plan,
                max_iterations,
                oar_clearance=oar_clearance,
            )

        candidate_seeds = []
        if not candidate_only:
            for center in candidate_centers:
                seed = self._suggest_seed_position(center, refined_plan)
                if seed is not None:
                    refined_plan.append(seed)
                    candidate_seeds.append(seed)

        # These coordinates belong only to the input dose array. Its shape
        # does not prove a physical frame, and existing seeds may be LPS-mm.
        # Do not invent a transform, an axis, a bore or a safety acceptance.
        advisory_locations = [{"index_zyx": center.tolist(),
            "dose": float(dose_distribution[tuple(center.astype(int))]),
            "coordinate_frame": "dose_array_zyx", "is_seed": False,
            "validation_status": "unvalidated_advisory"} for center in candidate_centers]

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
            "dose_engine_required": "dose_unet_spacing1mm" if iterations else None,
        }

        metrics_before = {
            "v100": float(current_v100),
            "v150": float(current_v150),
            "v200": float(current_v200),
            "d90": current_d90,
            "prescribed_dose": float(prescribed_dose),
            "target_v100": float(target_v100),
            "dose_units": kwargs.get("_dose_units", "same_as_input"),
        }

        if candidate_only or (candidate_centers and not candidate_seeds):
            message = (
                f"Plan refinement identified {len(advisory_locations)} advisory under-dose voxel location(s). "
                f"Input V100: {current_v100:.1%}. No feasible seed or channel proposal was accepted or added; "
                "the current plan is unmodified. "
                + ("Input is current total dose in Gy. " if kwargs.get("_dose_units") == "physical_gy" else "") +
                "Locations are dose-array ZYX indices, not physical implant positions. "
                "Fixed-implant capsules, needle paths, OAR clearance and guide-first admission "
                "have not been validated; separately authorized canonical planning is required "
                "to obtain feasible channel proposals."
            )
        elif iterations:
            message = (
                f"Plan refinement proposed {iterations} seed candidate(s). "
                f"Input V100: {current_v100:.1%}. Recompute dose with dose_unet_spacing1mm "
                "before accepting the refined plan. These legacy voxel candidates are unvalidated: "
                "needle paths, physical capsule separation and OAR clearance also require validation."
            )
        else:
            message = (
                f"Plan refinement did not propose changes. Input V100: {current_v100:.1%}."
            )

        return ToolResult(
            success=True,
            data=refined_plan,
            message=message,
            display=message,
            metadata={
                "refined_plan": refined_plan,
                "candidate_seeds": candidate_seeds,
                "advisory_locations": advisory_locations,
                "channel_proposals": [],
                "proposal_kind": "unvalidated_legacy_seed_candidates" if iterations else "unvalidated_advisory_locations",
                "candidate_only": candidate_only,
                "feasibility_validated": False,
                "clinical_use_approved": False,
                "plan_changed": False,
                "refined_plan_is_accepted": False,
                "unvalidated_checks": ["physical_grid", "fixed_implant_capsules", "needle_path",
                                       "oar_clearance", "guide_first_admission", "post_change_dose"],
                "advisory_count": len(advisory_locations),
                "advisory_spacing_units": "voxels",
                "dose_units": kwargs.get("_dose_units", "same_as_input"),
                "dose_basis": "current_total" if kwargs.get("_dose_units") == "physical_gy" else "input",
                "outside_guide_attempted": False,
                "metrics_before": metrics_before,
                "improved_metrics": improvements,
                "requires_dose_recalculation": iterations > 0,
                "dose_engine": "dose_unet_spacing1mm",
                "oar_aware_ranking": oar_clearance is not None,
                "oar_overlap_excluded": oar_mask is not None,
                "iterations_used": iterations,
            },
        )

    def _candidate_only(self, kwargs):
        if kwargs.get("_candidate_only"):
            return True
        agent = self._agent if self._agent is not None else kwargs.get("_agent")
        if agent is None:
            return False
        if getattr(agent, "_workspace_scoped_chat_runtime", None) is not None:
            return True
        # Defense for older server callers retaining an Agent binding outside
        # the owned adapter. A continuation/observed implant must never enter
        # the preoperative voxel-seed proposal path.
        retrieve = getattr(getattr(agent, "memory", None), "retrieve", lambda *_: None)
        scope = retrieve("timepoint_context")
        captured = getattr(agent, "_workspace_timepoint_context", None)
        stage = captured.target.stage if captured is not None else scope.get("stage") if isinstance(scope, Mapping) else None
        return (stage == "intraoperative" or retrieve("continuation_baseline_record") is not None
                or retrieve("implanted_seed_reconstruction") is not None)

    def _suggest_seed_position(self, centroid, current_plan):
        if isinstance(current_plan, list) and len(current_plan) > 0:
            last_seed = current_plan[-1]
            if isinstance(last_seed, (list, tuple)) and len(last_seed) >= 2:
                direc = np.asarray(last_seed[1], dtype=float).reshape(-1)
                if direc.shape == (3,) and np.isfinite(direc).all() and np.linalg.norm(direc) > 0:
                    return [centroid.tolist(), direc.tolist()]
        return None

    def _candidate_centers_from_underdosed(
        self,
        under_dosed,
        dose_distribution,
        current_plan,
        max_candidates,
        oar_clearance=None,
    ):
        coords = np.argwhere(under_dosed)
        if coords.size == 0:
            return []

        doses = dose_distribution[under_dosed]
        if oar_clearance is not None:
            clearances = np.asarray(oar_clearance)[under_dosed]
            dose_span = float(np.ptp(doses))
            clearance_span = float(np.ptp(clearances))
            normalized_dose = (doses - np.min(doses)) / (dose_span if dose_span > 0 else 1.0)
            normalized_clearance = (
                (clearances - np.min(clearances)) / (clearance_span if clearance_span > 0 else 1.0)
            )
            # Coverage remains the primary objective. Clearance only breaks or
            # gently reorders similarly cold candidates before DoseUNet reruns.
            priority = normalized_dose - 0.1 * normalized_clearance
            order = np.argsort(priority)
        else:
            order = np.argsort(doses)
        existing = self._extract_seed_positions(current_plan)
        selected = []
        min_dim = max(1, min(dose_distribution.shape))
        min_sep = max(4.0, float(min_dim) * 0.04)

        # Prefer the coldest voxels, but keep candidates spatially separated so
        # the follow-up DoseUNet calculation has meaningful alternatives.
        for idx in order:
            candidate = coords[int(idx)].astype(np.float32)
            if self._is_far_enough(candidate, existing + selected, min_sep):
                selected.append(candidate)
                if len(selected) >= max_candidates:
                    break

        return selected[:max_candidates]

    @staticmethod
    def _extract_seed_positions(plan):
        positions = []
        if not isinstance(plan, list):
            return positions
        for item in plan:
            pos = None
            if isinstance(item, dict):
                pos = item.get("position")
                if pos is None:
                    pos = item.get("pos")
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
