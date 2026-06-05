"""
VoCo Brain Tumor Segmentation (BraTS21)
=========================================
Brain tumor segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on BraTS21 dataset (4 classes: background, necrotic_core, peritumoral_edema, enhancing_tumor).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoBRATS21SegTool(VoCoSegmentationBase):
    """Segment brain tumors from MRI using VoCo SwinUNETR (BraTS21, 4 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_BRATS21_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "BRATS21", "model_90.23.pt"),
    )
    OUT_CHANNELS = 4
    FEATURE_SIZE = 48
    ROI_SIZE = (128, 128, 128)
    SPACING = (1.0, 1.0, 1.0)
    A_MIN = 0.0
    A_MAX = 0.0  # MRI: no intensity clipping
    LABEL_MAP = {
        0: ("background", False),
        1: ("necrotic_core", True),
        2: ("peritumoral_edema", True),
        3: ("enhancing_tumor", True),
    }

    def _get_transforms(self):
        """MRI-specific transforms: no intensity windowing."""
        from monai.transforms import (
            Compose, LoadImaged, EnsureChannelFirstd, Orientationd,
            Spacingd, CropForegroundd, SpatialPadd, NormalizeIntensityd,
        )
        return Compose([
            LoadImaged(keys=["image"]),
            EnsureChannelFirstd(keys=["image"]),
            Orientationd(keys=["image"], axcodes="RAS"),
            Spacingd(keys=["image"], pixdim=self.SPACING, mode="bilinear"),
            NormalizeIntensityd(keys=["image"], nonzero=True, channel_wise=True),
            CropForegroundd(keys=["image"], source_key="image"),
            SpatialPadd(keys=["image"], spatial_size=self.ROI_SIZE, mode="constant"),
        ])
