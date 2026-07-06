"""
Dose Percentile Metrics Tool (Dx)
===============================
Computes Dx metrics: minimum dose covering x% of structure volume.
Supports custom x values (e.g., D90, D95, D99, D50).
"""

import sys
import os
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
from typing import Dict, List


class DxMetricsTool(BaseTool):
    """
    Tool for computing Dx dose percentile metrics.

    Dx = minimum dose (in Gy) that covers x% of the structure volume.
    Example: D90 = minimum dose covering 90% of target volume.

    The dose array is sorted in descending order, and Dx is the lowest
    dose among the hottest x% of the structure volume.
    """

    @property
    def name(self) -> str:
        return "dx_metrics"

    @property
    def description(self) -> str:
        return (
            "Compute Dx metrics: minimum dose covering x% of structure volume. "
            "Supports custom x values (e.g., D90, D95, D99, D50). "
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
                "dx_values": {
                    "type": "array",
                    "description": "List of x values for Dx calculation, as volume percentages (default: [90, 95, 99, 50])",
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
                "dx_results": {
                    "type": "object",
                    "description": "Dict mapping structure -> Dx metric name -> dose value in Gy",
                },
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        dose_array = kwargs["dose_array"]
        masks = kwargs["masks"]
        dx_values = kwargs.get("dx_values", [90, 95, 99, 50])

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

            for dx in dx_values:
                if dx < 0 or dx > 100:
                    struct_results[f"D{dx}"] = {"error": "Invalid Dx value (must be 0-100)"}
                    continue

                idx = int(np.ceil(dx / 100.0 * total_voxels)) - 1
                idx = max(0, min(idx, total_voxels - 1))
                dx_value = float(sorted_doses[idx])
                struct_results[f"D{dx}"] = dx_value

            results[struct_name] = struct_results

        message = f"Computed Dx metrics for {len(masks)} structure(s): " + \
                  ", ".join([f"{s}: " + ", ".join([f"D{k}={v:.2f}Gy" for k, v in r.items() if "error" not in k]) for s, r in results.items()])

        return ToolResult(
            success=True,
            data=results,
            message=message,
            metadata={
                "dx_results": results,
                "dx_values": dx_values,
            },
        )


def main():
    parser = argparse.ArgumentParser(description="Compute Dx dose percentile metrics")
    parser.add_argument("--dose_array", required=True, help="Path to dose numpy array .npy file")
    parser.add_argument("--masks", required=True, help="JSON dict: structure_name -> mask numpy .npy path")
    parser.add_argument("--dx_values", nargs="+", type=float, default=[90, 95, 99, 50], help="Dx values (volume percentages)")
    parser.add_argument("--output", help="Output JSON file path")

    args = parser.parse_args()

    dose_array = np.load(args.dose_array)

    with open(args.masks) as f:
        mask_paths = json.load(f)
    masks = {name: np.load(path) for name, path in mask_paths.items()}

    tool = DxMetricsTool()
    result = tool.execute(
        dose_array=dose_array,
        masks=masks,
        dx_values=args.dx_values,
    )

    print(result.message)
    print(json.dumps(result.metadata["dx_results"], indent=2))

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result.metadata, f, indent=2, default=str)


if __name__ == "__main__":
    main()
