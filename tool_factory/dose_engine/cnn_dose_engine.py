"""
CNN Dose Engine Tool
===================
Deep learning based dose calculation using myDoseNet.
Supports batch inference for multiple seeds simultaneously.
"""


from tool_factory import BaseTool, ToolResult
import os
import numpy as np
import torch
import SimpleITK as sitk
from typing import Dict, List


class CNNDoseEngineTool(BaseTool):
    """
    Tool for calculating radiation dose distributions using deep learning (myDoseNet).

    Uses a CNN surrogate model to predict dose distributions.
    Supports batch inference for efficient multi-seed calculation.
    """

    @property
    def name(self) -> str:
        return "cnn_dose_engine"

    @property
    def description(self) -> str:
        return (
            "Calculate radiation dose distribution using CNN (myDoseNet). "
            "Input: CT image, seed positions/directions, and model parameters. "
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
                    "description": "Deep learning parameters including 'dose_model', 'device', etc.",
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
        import utilizations_promax as utilizations

        dose_image = kwargs["dose_image"]
        seeds = kwargs["seeds"]
        dl_params = kwargs.get("dl_params", {})
        infer_img_size = tuple(kwargs.get("infer_img_size", [32, 32, 32]))
        norm_min = kwargs.get("normalize_min", -1000)
        norm_max = kwargs.get("normalize_max", 3000)
        norm_scale = kwargs.get("normalize_scale", 255)
        seed_info = kwargs.get("seed_info", {"length": 4.5})

        if "dose_model" not in dl_params or dl_params["dose_model"] is None:
            import dose_pre.myDoseNet as myDoseNet

            model = myDoseNet.myDoseNet(
                spatial_dims=dl_params.get("dose_spatial_dims", 3),
                in_channels=dl_params.get("dose_in_channel", 3),
                out_channels=dl_params.get("dose_out_channel", 1),
                features=dl_params.get("dose_cal_features", (16, 32, 64, 128, 256, 32)),
            )
            # Smart device selection: prefer the most-free GPU; fall
            # back to CPU if no CUDA. The centralized manager caches
            # the per-tool choice so the same GPU is reused across
            # forward passes (model weights stay warm). See
            # plans/device_manager.py for the auto-pick heuristic
            # (best free memory, with concurrent-lease penalty so
            # we spread load across multiple GPUs).
            from plans.device_manager import get_device as _get_device
            device = _get_device(caller="cnn_dose_engine")
            if dl_params.get("multi_GPU", False):
                model = torch.nn.DataParallel(model)
            model_path = dl_params.get("dose_model_path", "./dose_pre/dose_model.pth")
            # Resolve relative path against project root
            if not os.path.isabs(model_path):
                _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
                model_path = os.path.join(_project_root, model_path)
            model.load_state_dict(torch.load(model_path, map_location=device))
            model.to(device)
            model.eval()
            dl_params["dose_model"] = model
            dl_params["device"] = device

        dose_model = dl_params["dose_model"]

        seed_tuples = [(seed_entry[0], seed_entry[1]) for seed_entry in seeds]
        per_seed_doses = utilizations.batch_seed_dose_calculation_dl(
            seed_tuples, dose_image, dose_model, infer_img_size,
            seed_info, norm_min, norm_max, norm_scale
        )

        cumulative_dose = np.sum(np.asarray(per_seed_doses), axis=0)

        return ToolResult(
            success=True,
            data=cumulative_dose,
            message=f"CNN dose calculation completed. {len(per_seed_doses)} seed(s) processed.",
            metadata={
                "cumulative_dose": cumulative_dose,
                "per_seed_doses": per_seed_doses,
                "max_dose": float(np.max(cumulative_dose)),
                "mean_dose": float(np.mean(cumulative_dose[cumulative_dose > 0])) if np.any(cumulative_dose > 0) else 0.0,
                "engine": "cnn",
                "num_seeds": len(per_seed_doses),
            },
        )


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="CNN Dose Engine Tool")
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

    tool = CNNDoseEngineTool()
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
