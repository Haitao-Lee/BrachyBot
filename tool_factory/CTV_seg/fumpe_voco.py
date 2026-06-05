"""
VoCo Pulmonary Embolism Segmentation
======================================
Pulmonary embolism segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on FUMPE dataset (2 classes: background, pulmonary_embolism).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoFUMPESegTool(VoCoSegmentationBase):
    """Segment pulmonary embolism from CT using VoCo SwinUNETR (FUMPE, 2 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_FUMPE_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "FUMPE", "model_voco_55.32.pt"),
    )
    OUT_CHANNELS = 2
    FEATURE_SIZE = 48
    ROI_SIZE = (192, 192, 192)
    SPACING = (1.25, 1.25, 1.25)
    A_MIN = -1000.0
    A_MAX = 500.0
    LABEL_MAP = {
        0: ("background", False),
        1: ("pulmonary_embolism", True),
    }
