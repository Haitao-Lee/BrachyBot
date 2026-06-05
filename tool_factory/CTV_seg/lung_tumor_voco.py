"""
VoCo Lung Cancer Segmentation
==============================
Lung cancer segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on MSD Task06 Lung dataset (2 classes: background, lung_cancer).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoLungTumorTool(VoCoSegmentationBase):
    """Segment lung cancer from CT using VoCo SwinUNETR (MSD Lung, 2 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_LUNG_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "Lung", "model_voco_75.74.pt"),
    )
    OUT_CHANNELS = 2
    FEATURE_SIZE = 48
    ROI_SIZE = (128, 128, 128)
    SPACING = (1.25, 1.25, 1.25)
    A_MIN = -1000.0
    A_MAX = 500.0
    LABEL_MAP = {
        0: ("background", False),
        1: ("lung_cancer", True),
    }
