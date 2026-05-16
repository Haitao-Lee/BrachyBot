"""
Absolute Dose Volume Metrics Tool (D2cc, D1cc, etc.)
==================================================
Computes absolute dose metrics based on volume in cc.
D_xcc = minimum dose covering x cubic centimeters of structure.
Also includes Dmean, Dmax, Dmin for complete dose statistics.
"""

import sys
import os
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
from typing import Dict, List


class AbsoluteDoseMetricsTool(BaseTool):
    """
    Tool for computing absolute dose metrics based on volume.

    D_xcc = minimum dose covering x cubic centimeters of structure.
    Example: D2cc = minimum dose covering the hottest 2cc of the structure.

    Also computes:
    - Dmean: Mean dose to the structure
    - Dmax: Maximum dose in the structure
    - Dmin: Minimum dose in the structure (of voxels > 0)
    - Dmedian: Median dose
    """

    @property
    def name(self) -> str:
        return "absolute_dose_metrics"

    @property
    def description(self) -> str:
        return (
            "Compute absolute dose metrics based on volume in cc. "
            "D_xcc = minimum dose covering x cubic centimeters. "
            "Also computes Dmean, Dmax, Dmin, Dmedian. "
            "Voxel size is required for cc conversion."
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
                "spacing": {
                    "type": "array",
                    "description": "Voxel spacing [x, y, z] in mm (default: [1, 1, 1])",
                },
                "cc_values": {
                    "type": "array",
                    "description": "List of cc values for D_xcc calculation (default: [2, 1, 0.5])",
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
                "dose_stats": {
                    "type": "object",
                    "description": "Dict mapping structure -> metric name -> value",
                },
                "voxel_volume_mm3": {"type": "number"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        dose_array = kwargs["dose_array"]
        masks = kwargs["masks"]
        spacing = kwargs.get("spacing", [1.0, 1.0, 1.0])
        cc_values = kwargs.get("cc_values", [2, 1, 0.5])

        voxel_volume_mm3 = float(spacing[0] * spacing[1] * spacing[2])
        voxel_volume_cc = voxel_volume_mm3 / 1000.0

        results = {}
        for struct_name, mask in masks.items():
            struct_mask = mask > 0
            struct_doses = dose_array[struct_mask]
            total_voxels = len(struct_doses)

            if total_voxels == 0:
                results[struct_name] = {"error": "No voxels in mask"}
                continue

            sorted_doses = np.sort(struct_doses)[::-1]
            struct_results = {}

            struct_results["Dmean"] = float(np.mean(struct_doses))
            struct_results["Dmax"] = float(np.max(struct_doses))
            positive_doses = struct_doses[struct_doses > 0]
            struct_results["Dmin"] = float(np.min(positive_doses)) if len(positive_doses) > 0 else 0.0
            struct_results["Dmedian"] = float(np.median(struct_doses))

            for cc in cc_values:
                voxels_needed = int(cc / voxel_volume_cc)
                voxels_needed = max(1, min(voxels_needed, total_voxels))
                dose_value = float(sorted_doses[voxels_needed - 1]) if voxels_needed > 0 else 0.0
                struct_results[f"D{cc}cc"] = dose_value

            results[struct_name] = struct_results

        message = f"Computed absolute dose metrics for {len(masks)} structure(s): " + \
                  ", ".join([f"{s}: Dmean={r.get('Dmean', 'N/A'):.2f}Gy, Dmax={r.get('Dmax', 'N/A'):.2f}Gy" for s, r in results.items() if "error" not in r])

        return ToolResult(
            success=True,
            data=results,
            message=message,
            metadata={
                "dose_stats": results,
                "voxel_volume_mm3": voxel_volume_mm3,
                "voxel_volume_cc": voxel_volume_cc,
                "cc_values": cc_values,
            },
        )


def main():
    parser = argparse.ArgumentParser(description="Compute absolute dose metrics (D2cc, D1cc, etc.)")
    parser.add_argument("--dose_array", required=True, help="Path to dose numpy array .npy file")
    parser.add_argument("--masks", required=True, help="JSON dict: structure_name -> mask numpy .npy path")
    parser.add_argument("--spacing", nargs="+", type=float, default=[1, 1, 1], help="Voxel spacing [x, y, z] in mm")
    parser.add_argument("--cc_values", nargs="+", type=float, default=[2, 1, 0.5], help="CC values for D_xcc")
    parser.add_argument("--output", help="Output JSON file path")

    args = parser.parse_args()

    dose_array = np.load(args.dose_array)

    with open(args.masks) as f:
        mask_paths = json.load(f)
    masks = {name: np.load(path) for name, path in mask_paths.items()}

    tool = AbsoluteDoseMetricsTool()
    result = tool.execute(
        dose_array=dose_array,
        masks=masks,
        spacing=args.spacing,
        cc_values=args.cc_values,
    )

    print(result.message)
    print(json.dumps(result.metadata["dose_stats"], indent=2))

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result.metadata, f, indent=2, default=str)


if __name__ == "__main__":
    main()
