"""
Dose Engine Tool
================
Dose calculation engine module.

The only supported engine is the CNN surrogate (``myDoseNet``) — a deep
learning model that predicts 3D dose distributions from seed positions,
directions, and the surrounding CT context.  The earlier analytical
Gaussian engine was removed: its dose-fall-off approximation is not
clinically valid and produced unrealistic plan evaluations.
"""

from tool_factory import BaseTool, ToolResult
import numpy as np
from typing import Dict, List

from tool_factory.dose_engine.cnn_dose_engine import CNNDoseEngineTool


class DoseEngineTool(BaseTool):
    """
    CNN-based dose calculation tool (myDoseNet surrogate).

    The dose-engine dispatcher is a thin wrapper that forwards every call
    to :class:`CNNDoseEngineTool`.  The ``engine`` parameter is retained
    for backward compatibility with previously-saved skill / preference
    payloads; only ``"cnn"`` is accepted, anything else raises an error.
    """

    @property
    def name(self) -> str:
        return "dose_engine"

    @property
    def description(self) -> str:
        return (
            "Calculate radiation dose distribution using the CNN (myDoseNet) "
            "deep-learning surrogate. "
            "Input: CT image, seed positions/directions, and CNN inference parameters. "
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
                "dl_params": {
                    "type": "object",
                    "description": "Deep learning parameters for CNN engine. If 'dose_model' is not provided, will load from dose_model_path.",
                },
                "infer_img_size": {
                    "type": "array",
                    "description": "CNN inference patch size (default: [32, 32, 32])",
                    "items": {"type": "integer"},
                    "default": [32, 32, 32],
                },
                "normalize_min": {
                    "type": "number",
                    "description": "Image normalization minimum (default: -1000)",
                    "default": -1000,
                },
                "normalize_max": {
                    "type": "number",
                    "description": "Image normalization maximum (default: 3000)",
                    "default": 3000,
                },
                "normalize_scale": {
                    "type": "number",
                    "description": "Image normalization scale (default: 255)",
                    "default": 255,
                },
                "seed_info": {
                    "type": "object",
                    "description": "Seed parameters dict with 'length' key (default: {'length': 4.5})",
                    "default": {"length": 4.5},
                },
                "engine": {
                    "type": "string",
                    "description": "Dose calculation engine. Only 'cnn' (myDoseNet) is supported; the legacy 'gaussian' engine has been removed.",
                    "enum": ["cnn"],
                    "default": "cnn",
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
        engine = kwargs.get("engine", "cnn")
        if engine != "cnn":
            return ToolResult(
                success=False,
                error=(
                    f"Unknown engine: {engine!r}. The only supported engine is 'cnn' "
                    f"(myDoseNet); the legacy 'gaussian' analytical engine has been removed."
                ),
            )

        # Forward everything else (including unused legacy seed_sigma / seed_avr_dose
        # which may still be present in older skill payloads) to the CNN engine.
        cnn_tool = CNNDoseEngineTool()
        return cnn_tool._execute(**kwargs)


def main():
    import argparse
    import json
    import SimpleITK as sitk

    parser = argparse.ArgumentParser(description="Dose Engine Tool (CNN / myDoseNet)")
    parser.add_argument("--dose_image", required=True, help="Path to CT dose image (.nii.gz)")
    parser.add_argument("--seeds", required=True, help="JSON string: list of [[position], [direction]] entries")
    parser.add_argument("--infer_img_size", nargs=3, type=int, default=[32, 32, 32], help="CNN inference patch size")
    parser.add_argument("--normalize_min", type=float, default=-1000, help="Image normalization min")
    parser.add_argument("--normalize_max", type=float, default=3000, help="Image normalization max")
    parser.add_argument("--normalize_scale", type=float, default=255, help="Image normalization scale")
    parser.add_argument("--output", help="Output path for cumulative dose (.nii.gz)")
    parser.add_argument("--json_output", help="Output path for metrics JSON")

    args = parser.parse_args()

    dose_image = sitk.ReadImage(args.dose_image)
    seeds = json.loads(args.seeds)

    tool = DoseEngineTool()
    result = tool._execute(
        dose_image=dose_image,
        seeds=seeds,
        infer_img_size=args.infer_img_size,
        normalize_min=args.normalize_min,
        normalize_max=args.normalize_max,
        normalize_scale=args.normalize_scale,
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
