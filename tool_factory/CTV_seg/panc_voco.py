"""
VoCo Pancreas Cancer Segmentation (MSD Task07)
================================================
Pancreas cancer segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on MSD Panc dataset (3 classes: background, pancreas, cancer).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoPancSegTool(VoCoSegmentationBase):
    """Segment pancreas cancer from CT using VoCo SwinUNETR (MSD Panc, 3 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_PANC_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "PANORAMA", "model_voco.pt"),
    )
    OUT_CHANNELS = 3
    FEATURE_SIZE = 48
    ROI_SIZE = (96, 96, 96)
    SPACING = (1.5, 1.5, 1.5)
    A_MIN = -175.0
    A_MAX = 250.0
    LABEL_MAP = {
        0: ("background", False),
        1: ("pancreas", False),
        2: ("cancer", True),
    }
