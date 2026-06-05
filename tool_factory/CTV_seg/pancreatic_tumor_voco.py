"""
VoCo Pancreatic Tumor Segmentation
===================================
Pancreatic tumor segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on PANORAMA dataset (7 classes: pancreas, duct, bile_duct, tumor, arteries, veins).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoPancreaticTumorTool(VoCoSegmentationBase):
    """Segment pancreatic tumors from CT using VoCo SwinUNETR (PANORAMA, 7 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_PANORAMA_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "PANORAMA", "model_voco.pt"),
    )
    OUT_CHANNELS = 7
    FEATURE_SIZE = 48
    ROI_SIZE = (96, 96, 96)
    SPACING = (1.5, 1.5, 1.5)
    A_MIN = -175.0
    A_MAX = 250.0
    LABEL_MAP = {
        0: ("background", False),
        1: ("pancreas", False),
        2: ("pancreatic_duct", False),
        3: ("bile_duct", False),
        4: ("tumor", True),
        5: ("arteries", False),
        6: ("veins", False),
    }
