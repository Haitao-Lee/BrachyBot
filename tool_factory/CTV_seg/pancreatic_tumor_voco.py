"""
VoCo Pancreatic Tumor Segmentation
===================================
Pancreatic tumor segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on PANORAMA dataset (7 classes).
Label mapping per PANORAMA challenge definition:
  0=background, 1=pancreas, 2=tumor(PDAC), 3=artery, 4=vein, 5=bile_duct, 6=pancreatic_duct
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
    # PANORAMA's published six-class label legend. Keep this independent
    # from custom nnU-Net datasets even when their numeric labels overlap.
    LABEL_MAP = {
        0: ("background", False),
        1: ("pancreatic_tumor", True),
        2: ("vein", False),
        3: ("artery", False),
        4: ("pancreas", False),
        5: ("pancreatic_duct", False),
        6: ("common_bile_duct", False),
    }
