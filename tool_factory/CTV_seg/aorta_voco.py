"""
VoCo Aorta Segmentation
========================
Aorta vessel segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on AVT/Aorta dataset (2 classes: background, aorta).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoAortaSegTool(VoCoSegmentationBase):
    """Segment aorta from CT using VoCo SwinUNETR (AVT, 2 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_AORTA_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "Aorta", "model_69.64.pt"),
    )
    OUT_CHANNELS = 2
    FEATURE_SIZE = 48
    ROI_SIZE = (96, 96, 96)
    SPACING = (1.5, 1.5, 1.5)
    A_MIN = -175.0
    A_MAX = 250.0
    LABEL_MAP = {
        0: ("background", False),
        1: ("aorta", True),
    }
