"""
Deprecated head-and-neck tumor segmentation entrypoint.

TotalSegmentator head/neck outputs are anatomical structures, not a tumor CTV.
This wrapper is kept only for backward-compatible imports and always fails
closed.
"""

from typing import Dict

from tool_factory import BaseTool, ToolResult


class HeadNeckTumorSegmentationTool(BaseTool):
    """Deprecated compatibility wrapper for older imports."""

    @property
    def name(self) -> str:
        return "head_neck_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Deprecated. TotalSegmentator head/neck anatomy is not tumor CTV. "
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
                "head_neck_tumor_segmentation is deprecated because TotalSegmentator "
                "does not produce a head-and-neck tumor CTV mask. Provide label_path "
                "or integrate a verified head-and-neck tumor model."
            ),
            metadata={
                "deprecated": True,
                "site": "head_neck",
                "recommended_tool": "ctv_segmentation",
                "catalog_tool": "ctv_model_catalog",
            },
        )
