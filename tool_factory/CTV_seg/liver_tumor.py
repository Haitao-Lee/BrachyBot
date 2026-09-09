"""Backward-compatible liver tumor CTV entrypoint.

The production implementation is the supplied two-stage nnUNet v2 cascade.
This module keeps the historical import and tool name working for restored
code while routing every liver tumor request to the dedicated local model.
"""

from .nnunet_cascade_tumor import NNUNetLiverTumorTool


class LiverTumorSegmentationTool(NNUNetLiverTumorTool):
    """Historical class name delegating to the dedicated liver cascade."""

    @property
    def name(self) -> str:
        return "liver_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Compatibility wrapper for the dedicated five-fold nnUNet v2 "
            "liver tumor cascade."
        )
