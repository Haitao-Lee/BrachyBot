"""
VoCo Kidney Tumor Segmentation
===============================
Kidney tumor segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on KiPA dataset (5 classes: background, renal_vein, kidney, renal_artery, tumor).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoKidneyTumorTool(VoCoSegmentationBase):
    """Segment kidney tumors from CT using VoCo SwinUNETR (KiPA, 5 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_KIDNEY_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "Kipa", "model_voco.pt"),
    )
    OUT_CHANNELS = 5
    FEATURE_SIZE = 48
    ROI_SIZE = (128, 128, 128)
    SPACING = (1.0, 1.0, 1.0)
    A_MIN = -175.0
    A_MAX = 250.0
    LABEL_MAP = {
        0: ("background", False),
        1: ("renal_vein", False),
        2: ("kidney", False),
        3: ("renal_artery", False),
        4: ("tumor", True),
    }
