"""

VoCo SegThor Tumor Segmentation Tool
====================================
Thoracic tumor segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on SegThor dataset.
Supports lung and esophageal tumor segmentation.
"""


import os
from tool_factory import BaseTool, ToolResult
import numpy as np
import torch
import SimpleITK as sitk
from typing import Dict
from functools import partial


class VoCoSegThorTumorTool(BaseTool):
    """
    VoCo-based thoracic tumor segmentation tool.

    Uses SwinUNETR fine-tuned on SegThor dataset (DSC: 90.17%).
    Suitable for lung and esophageal tumors.
    """

    MODEL_PATH = os.environ.get("VOCO_MODEL_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "SegThor", "model_90.17.pt"))
    OUT_CHANNELS = 5
    FEATURE_SIZE = 48
    ROI_SIZE = (96, 96, 96)
    SPACING = (1.5, 1.5, 1.5)
    A_MIN = -175.0
    A_MAX = 250.0

    def __init__(self):
        self._model = None
        self._device = None

    @property
    def name(self) -> str:
        return "voco_segthor_tumor"

    @property
    def description(self) -> str:
        return (
            "Segment thoracic tumors from CT images using VoCo pre-trained SwinUNETR. "
            "Fine-tuned on SegThor dataset (DSC: 90.17%). "
            "Supports lung and esophageal tumor segmentation. "
            "Input: CT image (SimpleITK) or path. "
            "Output: Tumor segmentation mask and volume metrics."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {"type": "object", "description": "SimpleITK Image of CT scan"},
                "image_path": {"type": "string", "description": "Path to CT image file"},
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
                "tumor_mask": {"type": "object"},
                "tumor_array": {"type": "array"},
                "tumor_volume_mm3": {"type": "number"},
                "tumor_voxel_count": {"type": "integer"},
            },
        }

    def _load_model(self):
        from monai.networks.nets import SwinUNETR

        if not os.path.exists(self.MODEL_PATH):
            raise FileNotFoundError(f"Model not found: {self.MODEL_PATH}")

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        model = SwinUNETR(
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
        from monai.transforms import Spacingd, ScaleIntensityRanged, CropForegroundd, SpatialPadd, Invertd

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
        from monai.transforms import Spacingd, Orientationd

        if self._model is None:
            self._model = self._load_model()

        self._model.eval()
        transforms = self._get_transforms()

        # Save original image metadata for inverse resampling
        original_size = image.GetSize()  # (X, Y, Z)
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
                pred_array = output.squeeze(0).squeeze(0).cpu().numpy()

                # Create prediction image in transformed space
                pred_image = sitk.GetImageFromArray(pred_array)
                # Set spacing to the resampled spacing (1.5, 1.5, 1.5)
                pred_image.SetSpacing(self.SPACING)
                # Set origin and direction to match the transformed image
                # The transforms change orientation to RAS, so we need to account for that
                pred_image.SetOrigin(image.GetOrigin())
                pred_image.SetDirection(image.GetDirection())

                # Resample prediction back to original image space using nearest neighbor
                resampler = sitk.ResampleImageFilter()
                resampler.SetReferenceImage(image)
                resampler.SetInterpolator(sitk.sitkNearestNeighbor)
                resampler.SetDefaultPixelValue(0)
                resampled_pred = resampler.Execute(pred_image)

                return sitk.GetArrayFromImage(resampled_pred)
        return np.zeros(image.GetSize()[::-1], dtype=np.int64)

    def _execute(self, **kwargs) -> ToolResult:
        image = kwargs.get("image")
        image_path = kwargs.get("image_path")

        if image is None and image_path is not None:
            image = sitk.ReadImage(image_path)
        elif image is None:
            return ToolResult(success=False, error="Either 'image' or 'image_path' must be provided")

        try:
            tumor_array = self._inference(image)
        except FileNotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Inference failed: {str(e)}")

        tumor_array = (tumor_array == 1).astype(np.uint8)

        voxel_count = int(np.sum(tumor_array > 0))
        spacing = image.GetSpacing()
        volume_mm3 = voxel_count * spacing[0] * spacing[1] * spacing[2]

        tumor_mask = sitk.GetImageFromArray(tumor_array)
        tumor_mask.CopyInformation(image)

        return ToolResult(
            success=True,
            data=tumor_array,
            message=f"SegThor tumor segmentation completed. Volume: {volume_mm3:.1f} mm³",
            metadata={
                "tumor_mask": tumor_mask,
                "tumor_array": tumor_array,
                "tumor_volume_mm3": float(volume_mm3),
                "tumor_voxel_count": voxel_count,
            },
        )


def main():
    import argparse
    parser = argparse.ArgumentParser(description="VoCo SegThor Tumor Segmentation")
    parser.add_argument("--image", required=True, help="Input CT image path")
    parser.add_argument("--output", help="Output tumor mask path")
    args = parser.parse_args()

    tool = VoCoSegThorTumorTool()
    result = tool._execute(image_path=args.image)
    print(result.message)

    if result.success and args.output:
        sitk.WriteImage(result.metadata["tumor_mask"], args.output)
        print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
