"""
VoCo BTCV Multi-Organ Segmentation
====================================
Multi-organ abdominal segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on BTCV dataset (14 classes: spleen, kidneys, gallbladder, esophagus, liver, stomach, aorta, IVC, veins, pancreas, adrenal glands).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoBTCVTumorTool(VoCoSegmentationBase):
    """Segment 13 abdominal organs from CT using VoCo SwinUNETR (BTCV, 14 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_BTCV_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "BTCV", "model_voco_86.64.pt"),
    )
    OUT_CHANNELS = 14
    FEATURE_SIZE = 48
    ROI_SIZE = (96, 96, 96)
    SPACING = (1.5, 1.5, 1.5)
    A_MIN = -175.0
    A_MAX = 250.0
    LABEL_MAP = {
        0: ("background", False),
        1: ("spleen", True),
        2: ("right_kidney", True),
        3: ("left_kidney", True),
        4: ("gallbladder", True),
        5: ("esophagus", True),
        6: ("liver", True),
        7: ("stomach", True),
        8: ("aorta", True),
        9: ("inferior_vena_cava", True),
        10: ("portal_splenic_vein", True),
        11: ("pancreas", True),
        12: ("right_adrenal", True),
        13: ("left_adrenal", True),
    }
