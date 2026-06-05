"""
VoCo Colon Cancer Segmentation
===============================
Colon cancer segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on MSD Task10 Colon dataset (2 classes: background, colon_cancer).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoColonTumorTool(VoCoSegmentationBase):
    """Segment colon cancer from CT using VoCo SwinUNETR (MSD Colon, 2 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_COLON_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "colon", "model_voco_42.57.pt"),
    )
    OUT_CHANNELS = 2
    FEATURE_SIZE = 48
    ROI_SIZE = (96, 96, 96)
    SPACING = (1.5, 1.5, 1.5)
    A_MIN = -175.0
    A_MAX = 250.0
    LABEL_MAP = {
        0: ("background", False),
        1: ("colon_cancer", True),
    }
