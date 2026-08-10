"""Backward-compatible liver tumor CTV entrypoint.

The actual implementation lives in ``totalsegmentator_liver_tumor``.  This
module keeps the historical import and tool name working for restored code,
while ensuring that old callers no longer fail closed or fall back to
BiomedParse.
"""

from .totalsegmentator_liver_tumor import TotalSegmentatorLiverTumorTool


class LiverTumorSegmentationTool(TotalSegmentatorLiverTumorTool):
    """Historical class name delegating to TotalSegmentator."""

    @property
    def name(self) -> str:
        return "liver_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Compatibility wrapper for TotalSegmentator liver tumor CTV. "
            "Only the liver_tumor output from the liver_vessels task is returned."
        )
