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
    # Matches Zhiyuan/BrachyPlan.py convention: 1=tumor, 2=artery, 3=vein, 4=pancreas
    LABEL_MAP = {
        0: ("background", False),
        1: ("tumor", True),
        2: ("artery", False),
        3: ("vein", False),
        4: ("pancreas", False),
        5: ("unknown_5", False),
        6: ("unknown_6", False),
    }
