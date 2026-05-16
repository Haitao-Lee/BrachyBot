"""
Segmentation Skills
==================
Predefined skill templates for various segmentation workflows.
"""

from .skill_base import Skill


class PancreasSegmentationSkill(Skill):
    """Pancreatic tumor and surrounding structure segmentation."""

    def __init__(self):
        super().__init__(
            name="pancreas_segmentation",
            description="Pancreatic tumor (CTV) + surrounding OAR (artery, vein, pancreas) segmentation",
            category="segmentation",
            triggers=["胰腺", "pancreas", "胰", "pancreatic"],
            tool_sequence=[
                "ctv_segmentation",
                "oar_segmentation",
            ],
            parameters={
                "ctv_segmentation": {"tumor_type": "pancreatic"},
                "oar_segmentation": {"organ_type": "pancreatic"},
            },
        )


class ProstateSegmentationSkill(Skill):
    """Prostate cancer segmentation."""

    def __init__(self):
        super().__init__(
            name="prostate_segmentation",
            description="Prostate tumor segmentation for brachytherapy planning",
            category="segmentation",
            triggers=["前列腺", "prostate", "摄护腺"],
            tool_sequence=[
                "ctv_segmentation",
                "oar_segmentation",
            ],
            parameters={
                "ctv_segmentation": {"tumor_type": "prostate"},
                "oar_segmentation": {"organ_type": "general"},
            },
        )


class GenericSegmentationSkill(Skill):
    """Generic segmentation for any tumor type using TotalSegmentator."""

    def __init__(self):
        super().__init__(
            name="generic_segmentation",
            description="Generic tumor and organ segmentation using TotalSegmentator",
            category="segmentation",
            triggers=["分割", "segment", "标注", "annotate"],
            tool_sequence=[
                "ctv_segmentation",
                "oar_segmentation",
            ],
            parameters={
                "ctv_segmentation": {"fast_mode": False},
                "oar_segmentation": {"organ_type": "general"},
            },
        )