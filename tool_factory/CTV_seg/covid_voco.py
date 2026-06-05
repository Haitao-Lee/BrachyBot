"""
VoCo COVID Lung Lesion Segmentation
=====================================
COVID-19 lung lesion segmentation using VoCo pre-trained SwinUNETR.
Fine-tuned on COVID dataset (2 classes: background, lesion).
"""

import os
from .voco_base import VoCoSegmentationBase


class VoCoCOVIDSegTool(VoCoSegmentationBase):
    """Segment COVID-19 lung lesions from CT using VoCo SwinUNETR (COVID, 2 classes)."""

    MODEL_PATH = os.environ.get(
        "VOCO_COVID_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "COVID", "model_68.78.pt"),
    )
    OUT_CHANNELS = 2
    FEATURE_SIZE = 48
    ROI_SIZE = (192, 192, 192)
    SPACING = (1.25, 1.25, 1.25)
    A_MIN = -1000.0
    A_MAX = 500.0
    LABEL_MAP = {
        0: ("background", False),
        1: ("covid_lesion", True),
    }
