"""
VoCo Liver Tumor Segmentation
==============================
Liver tumor segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on 3D-IRCADb dataset (3 classes: background, liver, liver_tumor).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoLiverTumorTool(VoCoSegmentationBase):
    """Segment liver tumors from CT using VoCo SwinUNETR (3D-IRCADb, 3 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_LIVER_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "3D-IRCADb", "model_voco_74.27.pt"),
    )
    OUT_CHANNELS = 3
    FEATURE_SIZE = 48
    ROI_SIZE = (96, 96, 96)
    SPACING = (1.5, 1.5, 1.5)
    A_MIN = -175.0
    A_MAX = 250.0
    LABEL_MAP = {
        0: ("background", False),
        1: ("liver", False),
        2: ("liver_tumor", True),
    }
