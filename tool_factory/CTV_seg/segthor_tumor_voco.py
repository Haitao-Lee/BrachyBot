"""
VoCo SegThor Thoracic Organ Segmentation
==========================================
Thoracic organ segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on SegThor dataset (5 classes: background, esophagus, heart, trachea, aorta).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoSegThorTumorTool(VoCoSegmentationBase):
    """Segment thoracic organs (esophagus, heart, trachea, aorta) from CT using VoCo SwinUNETR (SegThor, 5 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_SEGTHOR_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "SegThor", "model_90.17.pt"),
    )
    OUT_CHANNELS = 5
    FEATURE_SIZE = 48
    ROI_SIZE = (96, 96, 96)
    SPACING = (1.5, 1.5, 1.5)
    A_MIN = -1000.0
    A_MAX = 500.0
    LABEL_MAP = {
        0: ("background", False),
        1: ("esophagus", True),
        2: ("heart", True),
        3: ("trachea", True),
        4: ("aorta", True),
    }
