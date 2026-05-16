"""
Volume Dose Metrics Tool (Vx)
===========================
Computes Vx metrics: percentage of volume receiving at least x% of prescribed dose.
Supports custom x values and multiple structures.
"""

import sys
import os
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
from typing import Dict, List


class VxMetricsTool(BaseTool):
    """
    Tool for computing Vx dose metrics.

    Vx = percentage of structure volume receiving at least x% of prescribed dose.
    Example: V100 = percentage of volume receiving >= 100% of prescribed dose.
    """

    @property
    def name(self) -> str:
        return "vx_metrics"

    @property
    def description(self) -> str:
        return (
            "Compute Vx metrics: percentage of volume receiving at least x% of prescribed dose. "
            "Supports custom x values (e.g., V100, V150, V90). "
            "Works with multiple structures via mask dictionary."
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
                    "description": "List of x values for Vx calculation, as percentages (default: [100, 150, 200, 90])",
                    "items": {"type": "number"},
                },
            },
            "required": ["dose_array", "masks"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "vx_results": {
                    "type": "object",
                    "description": "Dict mapping structure -> Vx metric name -> value",
                },
                "prescribed_dose": {"type": "number"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        dose_array = kwargs["dose_array"]
        masks = kwargs["masks"]
        prescribed_dose = kwargs.get("prescribed_dose", 1.0)
        vx_values = kwargs.get("vx_values", [100, 150, 200, 90])

        results = {}
        for struct_name, mask in masks.items():
            struct_mask = mask > 0
            struct_doses = dose_array[struct_mask]
            total_voxels = len(struct_doses)

            if total_voxels == 0:
                results[struct_name] = {"error": "No voxels in mask"}
                continue

            struct_results = {}
            for vx in vx_values:
                threshold = (vx / 100.0) * prescribed_dose
                vx_pct = float(np.sum(struct_doses >= threshold) / total_voxels)
                struct_results[f"V{vx}"] = vx_pct

            results[struct_name] = struct_results

        message = f"Computed Vx metrics for {len(masks)} structure(s): " + \
                  ", ".join([f"{s}: " + ", ".join([f"V{k}={v:.1%}" for k, v in r.items() if "error" not in k]) for s, r in results.items()])

        return ToolResult(
            success=True,
            data=results,
            message=message,
            metadata={
                "vx_results": results,
                "prescribed_dose": prescribed_dose,
                "vx_values": vx_values,
            },
        )


def main():
    parser = argparse.ArgumentParser(description="Compute Vx dose metrics")
    parser.add_argument("--dose_array", required=True, help="Path to dose numpy array .npy file")
    parser.add_argument("--masks", required=True, help="JSON dict: structure_name -> mask numpy .npy path")
    parser.add_argument("--prescribed_dose", type=float, default=1.0, help="Prescribed dose in Gy")
    parser.add_argument("--vx_values", nargs="+", type=float, default=[100, 150, 200, 90], help="Vx values (percentages)")
    parser.add_argument("--output", help="Output JSON file path")

    args = parser.parse_args()

    dose_array = np.load(args.dose_array)

    with open(args.masks) as f:
        mask_paths = json.load(f)
    masks = {name: np.load(path) for name, path in mask_paths.items()}

    tool = VxMetricsTool()
    result = tool.execute(
        dose_array=dose_array,
        masks=masks,
        prescribed_dose=args.prescribed_dose,
        vx_values=args.vx_values,
    )

    print(result.message)
    print(json.dumps(result.metadata["vx_results"], indent=2))

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result.metadata, f, indent=2, default=str)


if __name__ == "__main__":
    main()
