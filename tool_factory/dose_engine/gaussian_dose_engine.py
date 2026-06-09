"""
Gaussian Dose Engine Tool
========================
Analytical Gaussian model for fast dose calculation.
Uses a simplified Gaussian ellipsoid to approximate radiation dose distribution.
"""


from tool_factory import BaseTool, ToolResult
import numpy as np
import SimpleITK as sitk
from typing import Dict


class GaussianDoseEngineTool(BaseTool):
    """
    Tool for calculating radiation dose distributions using analytical Gaussian model.

    Fast approximation method that models each seed as a Gaussian ellipsoid
    for quick dose distribution calculation.
    """

    @property
    def name(self) -> str:
        return "gaussian_dose_engine"

    @property
    def description(self) -> str:
        return (
            "Calculate radiation dose distribution using analytical Gaussian model. "
            "Fast approximation for quick dose calculation. "
            "Input: CT image shape, seed positions/directions, and sigma parameters. "
            "Output: 3D dose distribution array and per-seed dose contributions."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "dose_image": {
                    "type": "object",
                    "description": "SimpleITK Image of the CT scan for dose calculation",
                },
                "seeds": {
                    "type": "array",
                    "description": "List of seed entries, each [[position], [direction]] where position is [z, y, x] and direction is [dx, dy, dz]",
                },
                "seed_sigma": {
                    "type": "array",
                    "description": "Gaussian sigma for dose spread (length, radius, radius)",
                    "items": {"type": "number"},
                    "default": [4.5, 1.2, 1.2],
                },
                "seed_avr_dose": {
                    "type": "number",
                    "description": "Average dose per seed in Gy (default: 50)",
                    "default": 50,
                },
            },
            "required": ["dose_image", "seeds"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "cumulative_dose": {
                    "type": "array",
                    "description": "3D NumPy array of cumulative dose distribution",
                },
                "per_seed_doses": {
                    "type": "array",
                    "description": "List of 3D arrays, one per seed",
                },
                "max_dose": {
                    "type": "number",
                    "description": "Maximum dose value in the volume",
                },
                "mean_dose": {
                    "type": "number",
                    "description": "Mean dose value in voxels with dose > 0",
                },
                "engine": {
                    "type": "string",
                    "description": "Engine used for calculation",
                },
                "num_seeds": {
                    "type": "integer",
                    "description": "Number of seeds processed",
                },
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        from plans import utilizations

        dose_image = kwargs["dose_image"]
        seeds = kwargs["seeds"]
        seed_sigma = tuple(kwargs.get("seed_sigma", [4.5, 1.2, 1.2]))
        seed_avr_dose = kwargs.get("seed_avr_dose", 50)

        shape = sitk.GetArrayFromImage(dose_image).shape
        per_seed_doses = []
        for seed_entry in seeds:
            pos, direc = seed_entry[0], seed_entry[1]
            dose = utilizations.simple_single_dose_calculation(
                shape, pos, direc, seed_sigma, seed_avr_dose
            )
            per_seed_doses.append(dose)

        cumulative_dose = np.sum(np.asarray(per_seed_doses), axis=0)

        return ToolResult(
            success=True,
            data=cumulative_dose,
            message=f"Gaussian dose calculation completed. {len(per_seed_doses)} seed(s) processed.",
            metadata={
                "cumulative_dose": cumulative_dose,
                "per_seed_doses": per_seed_doses,
                "max_dose": float(np.max(cumulative_dose)),
                "mean_dose": float(np.mean(cumulative_dose[cumulative_dose > 0])) if np.any(cumulative_dose > 0) else 0.0,
                "engine": "gaussian",
                "num_seeds": len(per_seed_doses),
            },
        )


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Gaussian Dose Engine Tool")
    parser.add_argument("--dose_image", required=True, help="Path to CT dose image (.nii.gz)")
    parser.add_argument("--seeds", required=True, help="JSON string: list of [[position], [direction]] entries")
    parser.add_argument("--seed_sigma", nargs=3, type=float, default=[4.5, 1.2, 1.2], help="Gaussian sigma (length, radius, radius)")
    parser.add_argument("--seed_avr_dose", type=float, default=50, help="Average dose per seed in Gy")
    parser.add_argument("--output", help="Output path for cumulative dose (.nii.gz)")
    parser.add_argument("--json_output", help="Output path for metrics JSON")

    args = parser.parse_args()

    dose_image = sitk.ReadImage(args.dose_image)
    seeds = json.loads(args.seeds)

    tool = GaussianDoseEngineTool()
    result = tool._execute(
        dose_image=dose_image,
        seeds=seeds,
        seed_sigma=args.seed_sigma,
        seed_avr_dose=args.seed_avr_dose,
    )

    print(result.message)
    print(f"Max dose: {result.metadata['max_dose']:.2f} Gy")
    print(f"Mean dose: {result.metadata['mean_dose']:.2f} Gy")

    if args.output:
        dose_nii = sitk.GetImageFromArray(result.data)
        dose_nii.CopyInformation(dose_image)
        sitk.WriteImage(dose_nii, args.output)
        print(f"Dose saved to {args.output}")

    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump({
                "engine": result.metadata["engine"],
                "num_seeds": result.metadata["num_seeds"],
                "max_dose": result.metadata["max_dose"],
                "mean_dose": result.metadata["mean_dose"],
            }, f, indent=2)


if __name__ == "__main__":
    main()
