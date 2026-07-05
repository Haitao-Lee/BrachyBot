"""
Deprecated kidney tumor segmentation entrypoint.

TotalSegmentator kidney outputs are anatomical kidney masks, not kidney tumor
CTV. This wrapper is kept only for backward-compatible imports and always
fails closed.
"""

from typing import Dict

from tool_factory import BaseTool, ToolResult


class KidneyTumorSegmentationTool(BaseTool):
    """Deprecated compatibility wrapper for older imports."""

    @property
    def name(self) -> str:
        return "kidney_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Deprecated. TotalSegmentator kidney masks are not kidney tumor CTV. "
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
                "kidney_tumor_segmentation is deprecated because TotalSegmentator "
                "does not produce a kidney tumor CTV mask. Provide label_path or "
                "train/integrate a verified kidney tumor model from ctv_model_catalog."
            ),
            metadata={
                "deprecated": True,
                "site": "kidney",
                "recommended_tool": "ctv_segmentation",
                "catalog_tool": "ctv_model_catalog",
            },
        )
