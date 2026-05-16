"""
DVH Curve Calculation Tool
=========================
Computes cumulative and differential DVH curves for structures.
Returns dose bins and volume percentages for plotting.
"""

import sys
import os
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
from typing import Dict, List, Tuple


class DVHCalculationTool(BaseTool):
    """
    Tool for computing Dose-Volume Histogram (DVH) curves.

    Computes both cumulative and differential DVH:
    - Cumulative DVH: Shows volume percentage receiving at least a given dose
    - Differential DVH: Shows volume percentage receiving exactly a dose range

    Returns arrays suitable for plotting.
    """

    @property
    def name(self) -> str:
        return "dvh_calculation"

    @property
    def description(self) -> str:
        return (
            "Compute cumulative and differential DVH curves for structures. "
            "Returns dose bins and volume percentages for plotting. "
            "Supports custom binning and dose range settings."
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
                "num_bins": {
                    "type": "integer",
                    "description": "Number of histogram bins (default: 300)",
                    "default": 300,
                },
                "dose_max": {
                    "type": "number",
                    "description": "Maximum dose for binning in Gy (default: auto)",
                },
                "dose_min": {
                    "type": "number",
                    "description": "Minimum dose for binning in Gy (default: 0)",
                    "default": 0,
                },
            },
            "required": ["dose_array", "masks"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "dvh_data": {
                    "type": "object",
                    "description": "Dict mapping structure -> {cumulative: {dose_bins, vol_pcts}, differential: {dose_bins, vol_pcts}}",
                },
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        dose_array = kwargs["dose_array"]
        masks = kwargs["masks"]
        num_bins = kwargs.get("num_bins", 300)
        dose_max_input = kwargs.get("dose_max")
        dose_min = kwargs.get("dose_min", 0)

        dose_max = dose_max_input
        if dose_max is None:
            dose_max = float(np.max(dose_array)) * 1.1

        dose_bins = np.linspace(dose_min, dose_max, num_bins + 1)
        dose_centers = (dose_bins[:-1] + dose_bins[1:]) / 2.0
        bin_width = dose_bins[1] - dose_bins[0]

        results = {}
        for struct_name, mask in masks.items():
            struct_mask = mask > 0
            struct_doses = dose_array[struct_mask]
            total_voxels = len(struct_doses)

            if total_voxels == 0:
                results[struct_name] = {"error": "No voxels in mask"}
                continue

            cumulative_pcts = []
            for dose_threshold in dose_centers:
                pct = float(np.sum(struct_doses >= dose_threshold) / total_voxels * 100.0)
                cumulative_pcts.append(pct)

            hist, _ = np.histogram(struct_doses, bins=dose_bins)
            differential_pcts = (hist / total_voxels * 100.0).tolist()

            results[struct_name] = {
                "cumulative": {
                    "dose_bins": dose_centers.tolist(),
                    "volume_pcts": cumulative_pcts,
                },
                "differential": {
                    "dose_bins": dose_centers.tolist(),
                    "volume_pcts": differential_pcts,
                },
                "bin_width": bin_width,
                "total_voxels": total_voxels,
            }

        message = f"Computed DVH curves for {len(masks)} structure(s): " + \
                  ", ".join([f"{s}: {r.get('total_voxels', 'N/A')} voxels" for s, r in results.items() if "error" not in r])

        return ToolResult(
            success=True,
            data=results,
            message=message,
            metadata={
                "dvh_data": results,
                "dose_bins": dose_centers.tolist(),
                "num_bins": num_bins,
                "dose_range": [dose_min, dose_max],
            },
        )


def main():
    parser = argparse.ArgumentParser(description="Compute DVH curves for structures")
    parser.add_argument("--dose_array", required=True, help="Path to dose numpy array .npy file")
    parser.add_argument("--masks", required=True, help="JSON dict: structure_name -> mask numpy .npy path")
    parser.add_argument("--num_bins", type=int, default=300, help="Number of histogram bins")
    parser.add_argument("--dose_max", type=float, help="Maximum dose for binning in Gy (default: auto)")
    parser.add_argument("--dose_min", type=float, default=0, help="Minimum dose for binning in Gy")
    parser.add_argument("--output", help="Output JSON file path")
    parser.add_argument("--plot_data", help="Output simplified JSON for plotting (cumulative DVH only)")

    args = parser.parse_args()

    dose_array = np.load(args.dose_array)

    with open(args.masks) as f:
        mask_paths = json.load(f)
    masks = {name: np.load(path) for name, path in mask_paths.items()}

    tool = DVHCalculationTool()
    result = tool.execute(
        dose_array=dose_array,
        masks=masks,
        num_bins=args.num_bins,
        dose_max=args.dose_max,
        dose_min=args.dose_min,
    )

    print(result.message)

    if args.plot_data:
        plot_output = {}
        for struct_name, dvh_data in result.data.items():
            if "error" in dvh_data:
                continue
            plot_output[struct_name] = {
                "dose_bins": dvh_data["cumulative"]["dose_bins"],
                "volume_pcts": dvh_data["cumulative"]["volume_pcts"],
            }
        with open(args.plot_data, "w") as f:
            json.dump(plot_output, f)
        print(f"Plot data saved to {args.plot_data}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result.metadata, f, indent=2, default=str)
        print(f"Full results saved to {args.output}")


if __name__ == "__main__":
    main()
