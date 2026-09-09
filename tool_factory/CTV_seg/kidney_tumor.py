"""Backward-compatible kidney tumor CTV entrypoint.

The production implementation is the supplied two-stage nnUNet v2 cascade.
This historical module remains import-compatible for restored code.
"""

from .nnunet_cascade_tumor import NNUNetKidneyTumorTool


class KidneyTumorSegmentationTool(NNUNetKidneyTumorTool):
    """Historical class name delegating to the dedicated kidney cascade."""

    @property
    def name(self) -> str:
        return "kidney_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Compatibility wrapper for the dedicated five-fold nnUNet v2 "
            "kidney tumor cascade."
        )
