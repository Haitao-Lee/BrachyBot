"""
VoCo-based TotalSegmentator Tool
================================
Uses VoCo fine-tuned SwinUNETR for multi-organ segmentation (104 structures).
"""

import os

from tool_factory import BaseTool, ToolResult
import numpy as np
import torch
import SimpleITK as sitk
from typing import Dict, Optional, List
from functools import partial


class VoCoTotalSegmentatorTool(BaseTool):
    """
    VoCo-based total organ segmentation tool using SwinUNETR.

    Supports 104 anatomical structures using VoCo pre-trained and fine-tuned weights.
    Uses sliding window inference for efficient 3D volume processing.
    """

    DEFAULT_CONFIG = {
        "model_path": os.environ.get("VOCO_MODEL_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "VoCo", "Totalsegmentator", "model_voco.pt")),
        "model_large_path": os.environ.get("VOCO_MODEL_LARGE_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "VoCo", "Totalsegmentator", "model_voco_large_85.27.pt")),
        "out_channels": 104,
        "feature_size": 48,
        "feature_size_large": 96,
        "roi_size": (96, 96, 96),
        "spacing": (1.5, 1.5, 1.5),
        "a_min": -175.0,
        "a_max": 250.0,
    }

    ORGAN_NAMES = {
        1: "spleen",
        2: "right_kidney",
        3: "left_kidney",
        4: "gallbladder",
        5: "liver",
        6: "stomach",
        7: "pancreas",
        8: "right_adrenal",
        9: "left_adrenal",
        10: "right_lung",
        11: "left_lung",
        12: "heart",
        13: "aorta",
        14: "pulmonary_artery",
        15: "inferior_vena_cava",
        16: "portal_splenic_vein",
        17: "iliac_artery_left",
        18: "iliac_artery_right",
        19: "iliac_vena_left",
        20: "iliac_vena_right",
    }

    def __init__(self):
        self._model = None
        self._device = None
        self._current_config = None

    @property
    def name(self) -> str:
        return "voco_total_segmentation"

    @property
    def description(self) -> str:
        return (
            "Segment 104 anatomical structures using VoCo pre-trained SwinUNETR. "
            "Includes organs: spleen, kidneys, liver, stomach, pancreas, lungs, heart, vessels, etc. "
            "Input: CT image (SimpleITK) or path. "
            "Output: Multi-label segmentation mask with per-organ metrics."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {
                    "type": "object",
                    "description": "SimpleITK Image of CT scan",
                },
                "image_path": {
                    "type": "string",
                    "description": "Path to CT image file (.nii.gz, .nii)",
                },
                "organ_labels": {
                    "type": "array",
                    "description": "List of specific organ labels to extract (default: all)",
                    "items": {"type": "integer"},
                },
                "model_type": {
                    "type": "string",
                    "description": "Model size: 'base' or 'large'",
                    "enum": ["base", "large"],
                    "default": "base",
                },
                "feature_size": {
                    "type": "integer",
                    "description": "Model feature size (default: 48 for base, 96 for large)",
                },
                "roi_size": {
                    "type": "array",
                    "description": "Sliding window ROI size [x, y, z]",
                    "items": {"type": "integer"},
                    "default": [96, 96, 96],
                },
                "sw_batch_size": {
                    "type": "integer",
                    "description": "Sliding window batch size",
                    "default": 4,
                },
                "infer_overlap": {
                    "type": "number",
                    "description": "Sliding window overlap ratio",
                    "default": 0.75,
                },
            },
            "required": [],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "oar_mask": {
                    "type": "object",
                    "description": "SimpleITK multi-label OAR mask",
                },
                "oar_array": {
                    "type": "array",
                    "description": "NumPy array of OAR labels",
                },
                "organ_counts": {
                    "type": "object",
                    "description": "Voxel counts per organ label",
                },
                "organ_volumes": {
                    "type": "object",
                    "description": "Volume in mm³ per organ label",
                },
                "num_organs": {
                    "type": "integer",
                    "description": "Number of organs segmented",
                },
            },
        }

    def _load_model(self, config: Dict, model_type: str = "base") -> torch.nn.Module:
        """Load and initialize the SwinUNETR model."""
        from monai.networks.nets import SwinUNETR

        if model_type == "large":
            model_path = config["model_large_path"]
            feature_size = config.get("feature_size_large", 96)
        else:
            model_path = config["model_path"]
            feature_size = config.get("feature_size", 48)

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        model = SwinUNETR(
            img_size=config["roi_size"],
            in_channels=1,
            out_channels=config["out_channels"],
            feature_size=feature_size,
            use_v2=True,
        )

        checkpoint = torch.load(model_path, map_location=self._device, weights_only=False)
        if "state_dict" in checkpoint:
            state_dict = checkpoint["state_dict"]
        else:
            state_dict = checkpoint

        model.load_state_dict(state_dict, strict=True)
        model.to(self._device)
        model.eval()

        return model

    def _get_transforms(self, config: Dict):
        """Get preprocessing transforms."""
        from monai.transforms import Compose, LoadImaged, EnsureChannelFirstd, Orientationd
        from monai.transforms import Spacingd, ScaleIntensityRanged, CropForegroundd, SpatialPadd

        roi_size = config["roi_size"]

        test_transforms = Compose([
            LoadImaged(keys=["image"]),
            EnsureChannelFirstd(keys=["image"]),
            Orientationd(keys=["image"], axcodes="RAS"),
            Spacingd(
                keys=["image"],
                pixdim=config["spacing"],
                mode=("bilinear"),
            ),
            ScaleIntensityRanged(
                keys=["image"],
                a_min=config["a_min"],
                a_max=config["a_max"],
                b_min=0.0,
                b_max=1.0,
                clip=True,
            ),
            CropForegroundd(keys=["image"], source_key="image"),
            SpatialPadd(keys=["image"], spatial_size=roi_size, mode='constant'),
        ])

        return test_transforms

    def _inference(self, image: sitk.Image, config: Dict, model_type: str = "base") -> np.ndarray:
        """Run inference on the image."""
        from monai.inferers import sliding_window_inference
        from monai.data import Dataset, DataLoader

        if self._model is None or self._current_config != (model_type, id(config)):
            self._model = self._load_model(config, model_type)
            self._current_config = (model_type, id(config))

        self._model.eval()

        transforms = self._get_transforms(config)
        original_spacing = image.GetSpacing()
        original_origin = image.GetOrigin()
        original_direction = image.GetDirection()

        test_data_dicts = [{"image": image}]
        test_ds = Dataset(data=test_data_dicts, transform=transforms)
        test_loader = DataLoader(test_ds, batch_size=1, shuffle=False, num_workers=0)

        roi_size = list(config["roi_size"])
        sw_batch_size = config.get("sw_batch_size", 4)
        infer_overlap = config.get("infer_overlap", 0.75)

        model_inferer = partial(
            sliding_window_inference,
            roi_size=roi_size,
            sw_batch_size=sw_batch_size,
            predictor=self._model,
            overlap=infer_overlap,
        )

        with torch.no_grad():
            for batch_data in test_loader:
                data = batch_data["image"].to(self._device)

                with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=torch.cuda.is_available()):
                    logits = model_inferer(data)

                output = logits.argmax(1, keepdim=True)

                output_image = sitk.GetImageFromArray(
                    output.squeeze(0).squeeze(0).cpu().numpy()
                )

                output_image.SetSpacing(original_spacing)
                output_image.SetOrigin(original_origin)
                output_image.SetDirection(original_direction)

                return sitk.GetArrayFromImage(output_image)
        return np.zeros(image.GetSize()[::-1], dtype=np.int64)

    def _execute(self, **kwargs) -> ToolResult:

        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        organ_labels = kwargs.get("organ_labels")
        model_type = kwargs.get("model_type", "base")
        feature_size = kwargs.get("feature_size")
        target_value = kwargs.get("target_value", 1)

        if image is None and image_path is not None:
            image = sitk.ReadImage(image_path)
        elif image is None:
            return ToolResult(success=False, error="Either 'image' or 'image_path' must be provided")

        config = self.DEFAULT_CONFIG.copy()
        if feature_size is not None:
            config["feature_size"] = feature_size

        try:
            oar_array = self._inference(image, config, model_type)
        except FileNotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Inference failed: {str(e)}")

        spacing = image.GetSpacing()
        voxel_size = spacing[0] * spacing[1] * spacing[2]

        organ_counts = {}
        organ_volumes = {}
        unique_labels = np.unique(oar_array)

        for label in unique_labels:
            if label > 0:
                count = int(np.sum(oar_array == label))
                organ_counts[int(label)] = count
                organ_volumes[int(label)] = float(count * voxel_size)

        if organ_labels is not None:
            filtered_array = np.zeros_like(oar_array)
            for label in organ_labels:
                if label in organ_counts:
                    filtered_array[oar_array == label] = label
            oar_array = filtered_array

        oar_mask = sitk.GetImageFromArray(oar_array.astype(np.uint8))
        oar_mask.CopyInformation(image)

        num_organs = len([l for l in organ_counts.keys() if organ_counts[l] > 0])

        return ToolResult(
            success=True,
            data=oar_array,
            message=f"VoCo TotalSegmentator completed. {num_organs} organs segmented.",
            metadata={
                "oar_mask": oar_mask,
                "oar_array": oar_array,
                "organ_counts": organ_counts,
                "organ_volumes": organ_volumes,
                "num_organs": num_organs,
            },
        )


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="VoCo TotalSegmentator Tool")
    parser.add_argument("--image", required=True, help="Path to input CT image")
    parser.add_argument("--model_type", choices=["base", "large"], default="base",
                        help="Model size: base (48) or large (96)")
    parser.add_argument("--output", help="Output path for OAR mask (.nii.gz)")
    parser.add_argument("--json_output", help="Output path for metrics JSON")

    args = parser.parse_args()

    tool = VoCoTotalSegmentatorTool()
    result = tool._execute(
        image_path=args.image,
        model_type=args.model_type,
    )

    print(result.message)
    print(f"Number of organs: {result.metadata['num_organs']}")

    if args.output:
        sitk.WriteImage(result.metadata["oar_mask"], args.output)
        print(f"OAR mask saved to {args.output}")

    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump({
                "num_organs": result.metadata["num_organs"],
                "organ_counts": result.metadata["organ_counts"],
                "organ_volumes": result.metadata["organ_volumes"],
            }, f, indent=2)


if __name__ == "__main__":
    main()
