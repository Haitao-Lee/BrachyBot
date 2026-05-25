"""
Dose Engine Tool
================
Dose calculation engine module.
Provides access to CNN and Gaussian dose calculation tools.
"""

from tool_factory import BaseTool, ToolResult
import numpy as np
from typing import Dict, List

from tool_factory.dose_engine.cnn_dose_engine import CNNDoseEngineTool
from tool_factory.dose_engine.gaussian_dose_engine import GaussianDoseEngineTool


class DoseEngineTool(BaseTool):
    """
    Unified dose calculation tool supporting both CNN and Gaussian engines.

    Supports two modes:
    1. CNN surrogate (myDoseNet) - deep learning based dose prediction
    2. Gaussian analytical model - fast analytical approximation

    The LLM Agent can choose the appropriate engine based on the context
    (fast planning vs. high-accuracy validation).
    """

    @property
    def name(self) -> str:
        return "dose_engine"

    @property
    def description(self) -> str:
        return (
            "Calculate radiation dose distribution for given seed positions and directions. "
            "Supports two engines: 'cnn' (fast, uses pre-trained myDoseNet) and 'gaussian' (analytical Gaussian model). "
            "Input: CT image, seed positions/directions, and planning parameters. "
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
                    "description": "Gaussian sigma for dose spread (length, radius, radius) - used by gaussian engine",
                    "items": {"type": "number"},
                    "default": [4.5, 1.2, 1.2],
                },
                "seed_avr_dose": {
                    "type": "number",
                    "description": "Average dose per seed in Gy (default: 50)",
                    "default": 50,
                },
                "engine": {
                    "type": "string",
                    "description": "Dose calculation engine: 'gaussian' or 'cnn' (default: 'gaussian')",
                    "enum": ["gaussian", "cnn"],
                    "default": "gaussian",
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
        engine = kwargs.get("engine", "gaussian")

        if engine == "gaussian":
            tool = GaussianDoseEngineTool()
            return tool._execute(**kwargs)
        elif engine == "cnn":
            tool = CNNDoseEngineTool()
            return tool._execute(**kwargs)
        else:
            return ToolResult(
                success=False,
                error=f"Unknown engine: {engine}. Use 'gaussian' or 'cnn'.",
            )


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Dose Engine Tool - Calculate radiation dose distributions")
    parser.add_argument("--dose_image", required=True, help="Path to CT dose image (.nii.gz)")
    parser.add_argument("--seeds", required=True, help="JSON string: list of [[position], [direction]] entries")
    parser.add_argument("--engine", choices=["gaussian", "cnn"], default="gaussian", help="Dose engine to use")
    parser.add_argument("--seed_sigma", nargs=3, type=float, default=[4.5, 1.2, 1.2], help="Gaussian sigma (length, radius, radius)")
    parser.add_argument("--seed_avr_dose", type=float, default=50, help="Average dose per seed in Gy")
    parser.add_argument("--infer_img_size", nargs=3, type=int, default=[32, 32, 32], help="CNN inference patch size")
    parser.add_argument("--normalize_min", type=float, default=-1000, help="Image normalization min")
    parser.add_argument("--normalize_max", type=float, default=3000, help="Image normalization max")
    parser.add_argument("--normalize_scale", type=float, default=255, help="Image normalization scale")
    parser.add_argument("--output", help="Output path for cumulative dose (.nii.gz)")
    parser.add_argument("--json_output", help="Output path for metrics JSON")

    args = parser.parse_args()

    import SimpleITK as sitk
    dose_image = sitk.ReadImage(args.dose_image)
    seeds = json.loads(args.seeds)

    tool = DoseEngineTool()
    result = tool._execute(
        dose_image=dose_image,
        seeds=seeds,
        engine=args.engine,
        seed_sigma=args.seed_sigma,
        seed_avr_dose=args.seed_avr_dose,
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
