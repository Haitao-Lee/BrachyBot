"""
VoCo Segmentation Base Class
============================
Unified base for all VoCo pre-trained SwinUNETR segmentation tools.
Each subclass defines task-specific config (model path, labels, preprocessing).
"""

import os
import tempfile
from functools import partial
from typing import Dict, List, Optional

import numpy as np
import SimpleITK as sitk
import torch

from tool_factory import BaseTool, ToolResult


class VoCoSegmentationBase(BaseTool):
    """
    Base class for VoCo-based segmentation tools.

    Subclasses must define:
        MODEL_PATH: path to .pt weight file
        OUT_CHANNELS: number of output classes
        LABEL_MAP: dict mapping label_id -> (name, is_target)
            is_target=True means this label is extracted as the output mask.
            For binary tasks (1 target), use LABEL_MAP = {1: ("tumor", True)}
            For multi-organ tasks, set is_target on each organ of interest.
        A_MIN, A_MAX: intensity windowing range
        ROI_SIZE: tuple (x, y, z) for sliding window
        SPACING: tuple (x, y, z) for resampling
        FEATURE_SIZE: 48 (Base), 96 (Large), 192 (Huge)
    """

    # --- Subclass must override these ---
    MODEL_PATH: str = ""
    OUT_CHANNELS: int = 2
    FEATURE_SIZE: int = 48
    ROI_SIZE: tuple = (96, 96, 96)
    SPACING: tuple = (1.5, 1.5, 1.5)
    A_MIN: float = -175.0
    A_MAX: float = 250.0
    # label_id -> (name, is_target)
    LABEL_MAP: Dict = {}

    def __init__(self):
        self._model = None
        self._device = None

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def description(self) -> str:
        return self.__doc__ or "VoCo segmentation tool"

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {"type": "object", "description": "SimpleITK Image of CT/MRI scan"},
                "image_path": {"type": "string", "description": "Path to image file (.nii.gz, .mhd)"},
                "target_labels": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Override which label IDs to extract (default: use LABEL_MAP targets)",
                },
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
                "mask": {"type": "object", "description": "SimpleITK binary/multi-label mask"},
                "mask_array": {"type": "array", "description": "NumPy array of mask"},
                "volume_mm3": {"type": "number", "description": "Total volume in mm3"},
                "voxel_count": {"type": "integer", "description": "Number of mask voxels"},
                "labels_found": {"type": "object", "description": "Per-label voxel counts"},
            },
        }

    # ---- Model Loading ----

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

        # Handle common key prefixes
        for prefix in ["module.", "backbone."]:
            if any(k.startswith(prefix) for k in state_dict.keys()):
                state_dict = {k.replace(prefix, ""): v for k, v in state_dict.items()}

        model.load_state_dict(state_dict, strict=True)
        model.to(self._device)
        model.eval()
        return model

    # ---- Transforms ----

    def _get_transforms(self):
        from monai.transforms import (
            Compose, LoadImaged, EnsureChannelFirstd, Orientationd,
            Spacingd, ScaleIntensityRanged, CropForegroundd, SpatialPadd,
        )
        return Compose([
            LoadImaged(keys=["image"]),
            EnsureChannelFirstd(keys=["image"]),
            Orientationd(keys=["image"], axcodes="RAS"),
            Spacingd(keys=["image"], pixdim=self.SPACING, mode="bilinear"),
            ScaleIntensityRanged(
                keys=["image"],
                a_min=self.A_MIN, a_max=self.A_MAX,
                b_min=0.0, b_max=1.0, clip=True,
            ),
            CropForegroundd(keys=["image"], source_key="image"),
            SpatialPadd(keys=["image"], spatial_size=self.ROI_SIZE, mode="constant"),
        ])

    # ---- Inference ----

    def _inference(self, image: sitk.Image) -> np.ndarray:
        """Run sliding window inference and resample prediction back to original space."""
        from monai.inferers import sliding_window_inference
        from monai.data import Dataset, DataLoader

        if self._model is None:
            self._model = self._load_model()

        self._model.eval()
        transforms = self._get_transforms()

        # Write to temp file for MONAI loader
        tmp_path = os.path.join(tempfile.gettempdir(), f"voco_input_{os.getpid()}.nii.gz")
        sitk.WriteImage(image, tmp_path)

        try:
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
                    with torch.autocast(
                        device_type="cuda", dtype=torch.float16,
                        enabled=torch.cuda.is_available()
                    ):
                        logits = model_inferer(data)
                    output = logits.argmax(1, keepdim=True)
                    pred_array = output.squeeze(0).squeeze(0).cpu().numpy()

                    # Get the transformed image from the batch to extract its spatial metadata
                    # The transforms (Orientationd + Spacingd + CropForegroundd + SpatialPadd)
                    # change the image geometry. We need to create a matching SimpleITK image.
                    transformed_img_tensor = batch_data["image"]
                    # Use SimpleITK to read the transformed data back with correct geometry
                    # We reconstruct the transformed space from the tensor
                    pred_image = sitk.GetImageFromArray(pred_array)
                    pred_image.SetSpacing(self.SPACING)
                    pred_image.SetOrigin((0.0, 0.0, 0.0))
                    pred_image.SetDirection((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))

                    # Resample back to original image space
                    resampler = sitk.ResampleImageFilter()
                    resampler.SetReferenceImage(image)
                    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
                    resampler.SetDefaultPixelValue(0)
                    resampled = resampler.Execute(pred_image)

                    result = sitk.GetArrayFromImage(resampled)

                    # If resampling produced all zeros, the coordinate transform failed.
                    # Fallback: directly resize the prediction array to match original.
                    if result.sum() == 0 and pred_array.sum() > 0:
                        from scipy.ndimage import zoom
                        original_shape = image.GetSize()[::-1]  # (Z, Y, X)
                        zoom_factors = (
                            original_shape[0] / pred_array.shape[0],
                            original_shape[1] / pred_array.shape[1],
                            original_shape[2] / pred_array.shape[2],
                        )
                        result = zoom(pred_array, zoom_factors, order=0)  # nearest neighbor

                    return result
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        return np.zeros(image.GetSize()[::-1], dtype=np.int64)

    # ---- Label Extraction ----

    def _extract_labels(self, pred_array: np.ndarray, target_labels: Optional[List[int]] = None):
        """
        Extract target labels from prediction.

        Returns:
            mask_array: binary mask (union of target labels)
            label_counts: dict of label_name -> voxel_count
        """
        if target_labels is not None:
            # User-specified label IDs
            mask_array = np.isin(pred_array, target_labels).astype(np.uint8)
            label_counts = {}
            for lid in target_labels:
                count = int(np.sum(pred_array == lid))
                name = self.LABEL_MAP.get(lid, (f"label_{lid}", True))[0]
                label_counts[name] = count
        else:
            # Use LABEL_MAP to determine targets
            targets = [lid for lid, (name, is_target) in self.LABEL_MAP.items() if is_target]
            if not targets:
                # No targets defined, return all non-background
                mask_array = (pred_array > 0).astype(np.uint8)
                label_counts = {}
                for lid in np.unique(pred_array):
                    if lid > 0:
                        name = self.LABEL_MAP.get(lid, (f"label_{lid}", True))[0]
                        label_counts[name] = int(np.sum(pred_array == lid))
            else:
                mask_array = np.isin(pred_array, targets).astype(np.uint8)
                label_counts = {}
                for lid in targets:
                    name, _ = self.LABEL_MAP[lid]
                    label_counts[name] = int(np.sum(pred_array == lid))

        return mask_array, label_counts

    # ---- Execute ----

    def _execute(self, **kwargs) -> ToolResult:
        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        target_labels = kwargs.get("target_labels")

        if image is None and image_path is not None:
            image = sitk.ReadImage(image_path)
        elif image is None:
            return ToolResult(success=False, error="Either 'image' or 'image_path' must be provided")

        try:
            pred_array = self._inference(image)
        except FileNotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Inference failed: {str(e)}")

        mask_array, label_counts = self._extract_labels(pred_array, target_labels)

        voxel_count = int(np.sum(mask_array > 0))
        spacing = image.GetSpacing()
        volume_mm3 = voxel_count * spacing[0] * spacing[1] * spacing[2]

        mask_image = sitk.GetImageFromArray(mask_array)
        mask_image.CopyInformation(image)

        # Build display label list
        target_names = [name for lid, (name, is_target) in self.LABEL_MAP.items() if is_target]
        label_str = ", ".join(f"{n}({label_counts.get(n, 0)} vox)" for n in target_names) or "mask"

        return ToolResult(
            success=True,
            data=mask_array,
            message=f"Segmentation completed: {label_str}. Volume: {volume_mm3:.1f} mm3",
            metadata={
                "mask": mask_image,
                "mask_array": mask_array,
                "volume_mm3": float(volume_mm3),
                "voxel_count": voxel_count,
                "labels_found": label_counts,
            },
        )
