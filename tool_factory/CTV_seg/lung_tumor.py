"""
Deprecated lung tumor segmentation entrypoint.

TotalSegmentator lung/vessel outputs are anatomical structures, not lung tumor
CTV. This wrapper is kept only for backward-compatible imports and always
fails closed.
"""

from typing import Dict

from tool_factory import BaseTool, ToolResult


class LungTumorSegmentationTool(BaseTool):
    """Deprecated compatibility wrapper for older imports."""

    @property
    def name(self) -> str:
        return "lung_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Deprecated. TotalSegmentator lung/vessel masks are not lung tumor CTV. "
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
                "lung_tumor_segmentation is deprecated because TotalSegmentator "
                "does not produce a lung tumor CTV mask. Provide label_path or "
                "train/integrate a verified lung tumor model from ctv_model_catalog."
            ),
            metadata={
                "deprecated": True,
                "site": "lung",
                "recommended_tool": "ctv_segmentation",
                "catalog_tool": "ctv_model_catalog",
            },
        )
