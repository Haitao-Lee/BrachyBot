"""
Deprecated liver tumor segmentation entrypoint.

TotalSegmentator liver/vessel outputs are anatomical structures, not liver
tumor CTV. This wrapper is kept only for backward-compatible imports and
always fails closed.
"""

from typing import Dict

from tool_factory import BaseTool, ToolResult


class LiverTumorSegmentationTool(BaseTool):
    """Deprecated compatibility wrapper for older imports."""

    @property
    def name(self) -> str:
        return "liver_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Deprecated. TotalSegmentator liver/vessel masks are not liver tumor CTV. "
            "Use ctv_model_catalog to inspect verified models or provide label_path."
        )

    @property
    def input_schema(self) -> Dict:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def output_schema(self) -> Dict:
        return {"type": "object", "properties": {}}

    def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(
            success=False,
            error=(
                "liver_tumor_segmentation is deprecated because TotalSegmentator "
                "does not produce a liver tumor CTV mask. Provide label_path or "
                "train/integrate a verified liver tumor model from ctv_model_catalog."
            ),
            metadata={
                "deprecated": True,
                "site": "liver",
                "recommended_tool": "ctv_segmentation",
                "catalog_tool": "ctv_model_catalog",
            },
        )
