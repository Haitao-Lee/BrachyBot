"""
Comprehensive Dose Evaluation Tool
================================
Computes all dose metrics in one call: Vx, Dx, absolute dose metrics, and DVH curves.
Provides complete dose plan quality assessment.
"""

import sys
import os
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
from typing import Dict, List
from tool_factory.plan_quality.clinical_standards import get_oar_standard, get_target_standard


class ComprehensiveDoseEvaluationTool(BaseTool):
    """
    Tool for comprehensive dose evaluation.

    Combines all dose metrics computation:
    - Vx metrics (V100, V90, V150, V200)
    - Dx metrics (D90, D95, D99, D50)
    - Absolute dose metrics (D2cc, D1cc, D0.5cc, Dmean, Dmax, Dmin)
    - DVH curves
    - Plan quality score
    """

    @property
    def name(self) -> str:
        return "comprehensive_dose_evaluation"

    @property
    def description(self) -> str:
        return (
            "Comprehensive dose evaluation: computes Vx, Dx, absolute dose metrics, DVH curves, and plan score. "
            "Provides complete dose plan quality assessment in a single call."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "dose_array": {
                    "type": "object",
                    "description": "3D NumPy array of dose distribution in Gy",
                },
                "masks": {
                    "type": "object",
                    "description": "Dict mapping structure name to binary mask array",
                },
                "prescribed_dose": {
                    "type": "number",
                    "description": "Prescribed dose in Gy (default: 1.0)",
                    "default": 1.0,
                },
                "vx_values": {
                    "type": "array",
                    "description": "Vx values for calculation (default: [100, 150, 200, 90])",
                },
                "dx_values": {
                    "type": "array",
                    "description": "Dx values for calculation (default: [90, 95, 99, 50])",
                },
                "cc_values": {
                    "type": "array",
                    "description": "CC values for absolute metrics (default: [2, 1, 0.5])",
                },
                "spacing": {
                    "type": "array",
                    "description": "Voxel spacing [x, y, z] in mm (default: [1, 1, 1])",
                },
                "num_dvh_bins": {
                    "type": "integer",
                    "description": "DVH histogram bins (default: 300)",
                    "default": 300,
                },
                "structure_type": {
                    "type": "object",
                    "description": "Dict mapping structure name to 'target' or 'oar' for scoring",
                },
            },
            "required": ["dose_array", "masks"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "metrics": {"type": "object", "description": "All computed metrics by structure"},
                "plan_score": {"type": "number", "description": "Overall plan quality score (0-100)"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        dose_array = kwargs["dose_array"]
        masks = kwargs["masks"]
        prescribed_dose = kwargs.get("prescribed_dose", 1.0)
        vx_values = kwargs.get("vx_values", [100, 150, 200, 90])
        dx_values = kwargs.get("dx_values", [90, 95, 99, 50])
        cc_values = kwargs.get("cc_values", [2, 1, 0.5])
        spacing = kwargs.get("spacing", [1.0, 1.0, 1.0])
        num_bins = kwargs.get("num_dvh_bins", 300)
        structure_type = kwargs.get("structure_type", {})
        tumor_type = kwargs.get("tumor_type", "")
        site = self._site_from_tumor_type(tumor_type)
        oar_standards = get_oar_standard(site)

        voxel_volume_mm3 = float(spacing[0] * spacing[1] * spacing[2])
        voxel_volume_cc = voxel_volume_mm3 / 1000.0

        metrics = {}
        target_metrics = None
        oar_violations = []

        for struct_name, mask in masks.items():
            struct_mask = mask > 0
            struct_doses = dose_array[struct_mask]
            total_voxels = len(struct_doses)

            if total_voxels == 0:
                metrics[struct_name] = {"error": "No voxels in mask"}
                continue

            sorted_doses = np.sort(struct_doses)[::-1]
            struct_metrics = {}

            for vx in vx_values:
                threshold = (vx / 100.0) * prescribed_dose
                vx_pct = float(np.sum(struct_doses >= threshold) / total_voxels)
                struct_metrics[f"V{vx}"] = vx_pct

            for dx in dx_values:
                if 0 <= dx <= 100:
                    idx = int(np.ceil(dx / 100.0 * total_voxels)) - 1
                    idx = max(0, min(idx, total_voxels - 1))
                    struct_metrics[f"D{dx}"] = float(sorted_doses[idx])

            for cc in cc_values:
                voxels_needed = max(1, int(cc / voxel_volume_cc))
                voxels_needed = min(voxels_needed, total_voxels)
                struct_metrics[f"D{cc}cc"] = float(sorted_doses[voxels_needed - 1])

            struct_metrics["Dmean"] = float(np.mean(struct_doses))
            struct_metrics["Dmax"] = float(np.max(struct_doses))
            struct_metrics["Dmin"] = float(np.min(struct_doses))
            struct_metrics["Dmedian"] = float(np.median(struct_doses))

            hist, bin_edges = np.histogram(struct_doses, bins=num_bins)
            dose_centers = ((bin_edges[:-1] + bin_edges[1:]) / 2).tolist()
            cumulative_pcts = []
            for dose_threshold in dose_centers:
                cumulative_pcts.append(float(np.sum(struct_doses >= dose_threshold) / total_voxels * 100.0))

            struct_metrics["dvh"] = {
                "dose_bins": dose_centers,
                "volume_pcts": cumulative_pcts,
            }

            struct_metrics["total_voxels"] = total_voxels
            struct_metrics["volume_cc"] = total_voxels * voxel_volume_cc

            metrics[struct_name] = struct_metrics

            is_target = structure_type.get(struct_name, "").lower() == "target"
            if is_target:
                target_metrics = struct_metrics
            else:
                constraint = self._match_oar_constraint(struct_name, oar_standards)
                if constraint:
                    oar_violations.extend(self._check_oar_violation(struct_name, struct_metrics, constraint))

        plan_score = self._compute_plan_score(target_metrics, prescribed_dose, oar_violations, tumor_type)

        message = f"Comprehensive evaluation complete for {len(masks)} structure(s). "
        if target_metrics:
            message += f"Target: V100={target_metrics.get('V100', 0):.1%}, D90={target_metrics.get('D90', 0):.2f}Gy. "
        message += f"Plan score: {plan_score:.1f}/100."

        return ToolResult(
            success=True,
            data={"metrics": metrics, "plan_score": plan_score},
            message=message,
            metadata={
                "metrics": metrics,
                "plan_score": plan_score,
                "prescribed_dose": prescribed_dose,
                "voxel_volume_cc": voxel_volume_cc,
                "score_standard_site": site,
                "score_standard_source": "tool_factory.plan_quality.clinical_standards",
            },
        )

    _SITE_ALIASES = {
        "nnunet_pancreatic": "pancreas",
        "pancreatic": "pancreas",
        "pancreas": "pancreas",
        "voco_liver": "liver",
        "liver": "liver",
        "voco_lung": "lung",
        "lung": "lung",
        "voco_kidney": "kidney",
        "kidney": "kidney",
        "renal": "kidney",
        "prostate": "prostate",
        "prostate_tumor": "prostate",
        "head_neck": "head_neck",
        "head and neck": "head_neck",
        "voco_brats21": "head_neck",
        "cervical": "cervical",
        "cervix": "cervical",
        "colon": "colon",
    }

    @classmethod
    def _site_from_tumor_type(cls, tumor_type: str) -> str:
        text = (tumor_type or "").lower().replace("-", "_").strip()
        for pattern, site in cls._SITE_ALIASES.items():
            if pattern in text or text in pattern:
                return site
        return "default"

    @staticmethod
    def _match_oar_constraint(struct_name: str, standards: Dict) -> Dict:
        name = (struct_name or "").lower()
        for key, constraint in standards.items():
            key_l = str(key).lower()
            if key_l == name or key_l in name or name in key_l:
                return constraint if isinstance(constraint, dict) else {}
        return {}

    @staticmethod
    def _check_oar_violation(struct_name: str, struct_metrics: Dict, constraint: Dict) -> List[Dict]:
        metric_map = {
            "d2cc": "D2cc",
            "max_dose": "Dmax",
            "dmax": "Dmax",
            "dmean_max": "Dmean",
            "mean_dose": "Dmean",
        }
        violations = []
        for limit_key, limit in constraint.items():
            metric_key = metric_map.get(str(limit_key).lower())
            if not metric_key or metric_key not in struct_metrics:
                continue
            actual = float(struct_metrics[metric_key])
            if actual > float(limit):
                violations.append({
                    "structure": struct_name,
                    "metric": metric_key,
                    "actual": actual,
                    "constraint": float(limit),
                    "source": "clinical_standards_mirror",
                })
        return violations

    def _compute_plan_score(self, target_metrics, prescribed_dose, oar_violations, tumor_type=""):
        if target_metrics is None:
            return 0.0

        score = 0.0
        v100 = target_metrics.get("V100", 0)
        v150 = target_metrics.get("V150", 0)
        v200 = target_metrics.get("V200", 0)
        d90 = target_metrics.get("D90", 0)

        target_std = get_target_standard(self._site_from_tumor_type(tumor_type))
        v100_min = target_std.get("v100_min", 0.90)
        v150_max = target_std.get("v150_max", 0.50)
        v200_max = target_std.get("v200_max", 0.35)
        d90_min_pct = target_std.get("d90_min_pct", 1.0)

        # V100 scoring (40 pts max) from the clinical standards mirror.
        if v100 >= v100_min:
            score += 40
        elif v100 >= v100_min - 0.05:
            score += 30
        elif v100 >= v100_min - 0.15:
            score += 20
        else:
            score += 10

        # V150 homogeneity (20 pts max)
        if v150 <= v150_max:
            score += 20
        elif v150 <= v150_max + 0.10:
            score += 15
        else:
            score += 5

        # V200 hot spots (10 pts max) from the clinical standards mirror.
        if v200 <= v200_max:
            score += 10
        elif v200 <= v200_max + 0.10:
            score += 5

        # D90 scoring (20 pts max) based on fraction of prescription.
        d90_pct = d90 / prescribed_dose if prescribed_dose > 0 else 0
        if d90_pct >= d90_min_pct:
            score += 20
        elif d90_pct >= d90_min_pct - 0.10:
            score += 15
        elif d90_pct >= d90_min_pct - 0.20:
            score += 10

        score -= len(oar_violations) * 10
        return max(0.0, min(100.0, score))


def main():
    parser = argparse.ArgumentParser(description="Comprehensive dose evaluation")
    parser.add_argument("--dose_array", required=True, help="Path to dose numpy array .npy file")
    parser.add_argument("--masks", required=True, help="JSON dict: structure_name -> mask numpy .npy path")
    parser.add_argument("--prescribed_dose", type=float, default=1.0, help="Prescribed dose in Gy")
    parser.add_argument("--vx_values", nargs="+", type=float, default=[100, 150, 200, 90])
    parser.add_argument("--dx_values", nargs="+", type=float, default=[90, 95, 99, 50])
    parser.add_argument("--cc_values", nargs="+", type=float, default=[2, 1, 0.5])
    parser.add_argument("--spacing", nargs="+", type=float, default=[1, 1, 1])
    parser.add_argument("--structure_type", help="JSON dict: structure_name -> 'target' or 'oar'")
    parser.add_argument("--output", help="Output JSON file path")

    args = parser.parse_args()

    dose_array = np.load(args.dose_array)

    with open(args.masks) as f:
        mask_paths = json.load(f)
    masks = {name: np.load(path) for name, path in mask_paths.items()}

    structure_type = {}
    if args.structure_type:
        with open(args.structure_type) as f:
            structure_type = json.load(f)

    tool = ComprehensiveDoseEvaluationTool()
    result = tool.execute(
        dose_array=dose_array,
        masks=masks,
        prescribed_dose=args.prescribed_dose,
        vx_values=args.vx_values,
        dx_values=args.dx_values,
        cc_values=args.cc_values,
        spacing=args.spacing,
        structure_type=structure_type,
    )

    print(result.message)
    print(f"\nPlan Score: {result.metadata['plan_score']:.1f}/100")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result.metadata, f, indent=2, default=str)
        print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
