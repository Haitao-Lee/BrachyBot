"""
VoCo Prostate Segmentation Tool
=============================
Prostate segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned onAMOS-MRI dataset (MRI).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
import torch
import SimpleITK as sitk
from typing import Dict
from functools import partial


class VoCoProstateTool(BaseTool):
    """
    VoCo-based prostate segmentation tool.

    Uses SwinUNETR fine-tuned onAMOS-MRI dataset (DSC: 79.24%, MRI).
    """

    MODEL_PATH = os.environ.get("VOCO_MODEL_PATH", "/home/lht/snap/brachyplan/BrachyBot/VoCo/Amos-MR/model_voco_79.24.pt")))), "VoCo", os.path.basename(__file__).replace("_voco.py", "").replace("_tumor", "").replace("_vessel", "").upper() + "/model_voco.pt"))
    OUT_CHANNELS = 2
    FEATURE_SIZE = 48
    ROI_SIZE = (96, 96, 96)
    SPACING = (1.0, 1.0, 1.0)
    A_MIN = 0.0
    A_MAX = 3000.0

    def __init__(self):
        self._model = None
        self._device = None

    @property
    def name(self) -> str:
        return "voco_prostate"

    @property
    def description(self) -> str:
        return (
            "Segment prostate from MR images using VoCo pre-trained SwinUNETR. "
            "Fine-tuned onAMOS-MRI dataset (DSC: 79.24%). "
            "Input: MR image (SimpleITK) or path. "
            "Output: Prostate segmentation mask and volume metrics."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {"type": "object", "description": "SimpleITK Image of MR scan"},
                "image_path": {"type": "string", "description": "Path to MR image file"},
                "sw_batch_size": {"type": "integer", "default": 4},
                "infer_overlap": {"type": "number", "default": 0.75},
            },
            "required": [],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "prostate_mask": {"type": "object"},
                "prostate_array": {"type": "array"},
                "prostate_volume_mm3": {"type": "number"},
                "prostate_voxel_count": {"type": "integer"},
            },
        }

    def _load_model(self):
        from monai.networks.nets import SwinUNETR

        if not os.path.exists(self.MODEL_PATH):
            raise FileNotFoundError(f"Model not found: {self.MODEL_PATH}")

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        model = SwinUNETR(
            img_size=self.ROI_SIZE,
            in_channels=1,
            out_channels=self.OUT_CHANNELS,
            feature_size=self.FEATURE_SIZE,
            use_v2=True,
        )

        checkpoint = torch.load(self.MODEL_PATH, map_location=self._device, weights_only=False)
        state_dict = checkpoint.get("state_dict", checkpoint)
        model.load_state_dict(state_dict, strict=True)
        model.to(self._device)
        model.eval()
        return model

    def _get_transforms(self):
        from monai.transforms import Compose, LoadImaged, EnsureChannelFirstd, Orientationd
        from monai.transforms import Spacingd, ScaleIntensityRanged, CropForegroundd, SpatialPadd

        return Compose([
            LoadImaged(keys=["image"]),
            EnsureChannelFirstd(keys=["image"]),
            Orientationd(keys=["image"], axcodes="RAS"),
            Spacingd(keys=["image"], pixdim=self.SPACING, mode="bilinear"),
            ScaleIntensityRanged(keys=["image"], a_min=self.A_MIN, a_max=self.A_MAX, b_min=0.0, b_max=1.0, clip=True),
            CropForegroundd(keys=["image"], source_key="image"),
            SpatialPadd(keys=["image"], spatial_size=self.ROI_SIZE, mode='constant'),
        ])

    def _inference(self, image: sitk.Image) -> np.ndarray:
        from monai.inferers import sliding_window_inference
        from monai.data import Dataset, DataLoader

        if self._model is None:
            self._model = self._load_model()

        self._model.eval()
        transforms = self._get_transforms()

        original_spacing = image.GetSpacing()
        original_origin = image.GetOrigin()
        original_direction = image.GetDirection()

        import tempfile
        tmp_path = os.path.join(tempfile.gettempdir(), f"voco_input_{os.getpid()}.nii.gz")
        sitk.WriteImage(image, tmp_path)

        test_ds = Dataset(data=[{"image": tmp_path}], transform=transforms)
        test_loader = DataLoader(test_ds, batch_size=1, shuffle=False, num_workers=0)

        model_inferer = partial(
            sliding_window_inference,
            roi_size=list(self.ROI_SIZE),
            sw_batch_size=4,
            predictor=self._model,
            overlap=0.75,
        )

        with torch.no_grad():
            for batch_data in test_loader:
                data = batch_data["image"].to(self._device)
                with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=torch.cuda.is_available()):
                    logits = model_inferer(data)
                output = logits.argmax(1, keepdim=True)

                output_image = sitk.GetImageFromArray(output.squeeze(0).squeeze(0).cpu().numpy())
                output_image.SetSpacing(original_spacing)
                output_image.SetOrigin(original_origin)
                output_image.SetDirection(original_direction)
                return sitk.GetArrayFromImage(output_image)
        return np.zeros(image.GetSize()[::-1], dtype=np.int64)

    def _execute(self, **kwargs) -> ToolResult:

        image = kwargs.get("image")
        image_path = kwargs.get("image_path")

        if image is None and image_path is not None:
            image = sitk.ReadImage(image_path)
        elif image is None:
            return ToolResult(success=False, error="Either 'image' or 'image_path' must be provided")

        try:
            prostate_array = self._inference(image)
        except FileNotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Inference failed: {str(e)}")

        prostate_array = (prostate_array == 1).astype(np.uint8)

        voxel_count = int(np.sum(prostate_array > 0))
        spacing = image.GetSpacing()
        volume_mm3 = voxel_count * spacing[0] * spacing[1] * spacing[2]

        prostate_mask = sitk.GetImageFromArray(prostate_array)
        prostate_mask.CopyInformation(image)

        return ToolResult(
            success=True,
            data=prostate_array,
            message=f"Prostate segmentation completed. Volume: {volume_mm3:.1f} mm³",
            metadata={
                "prostate_mask": prostate_mask,
                "prostate_array": prostate_array,
                "prostate_volume_mm3": float(volume_mm3),
                "prostate_voxel_count": voxel_count,
            },
        )


def main():
    import argparse
    parser = argparse.ArgumentParser(description="VoCo Prostate Segmentation")
    parser.add_argument("--image", required=True, help="Input MR image path")
    parser.add_argument("--output", help="Output prostate mask path")
    args = parser.parse_args()

    tool = VoCoProstateTool()
    result = tool._execute(image_path=args.image)
    print(result.message)

    if result.success and args.output:
        sitk.WriteImage(result.metadata["prostate_mask"], args.output)
        print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
