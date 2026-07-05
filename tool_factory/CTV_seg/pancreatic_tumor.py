"""
Deprecated pancreatic tumor segmentation entrypoint.

Use pancreatic_tumor_nnunet.NNUNetPancreaticTumorTool through the unified
ctv_segmentation tool. This legacy wrapper is intentionally fail-closed because
older revisions could silently return an empty fallback mask.
"""

from typing import Dict

from tool_factory import BaseTool, ToolResult


class PancreaticTumorSegmentationTool(BaseTool):
    """Deprecated compatibility wrapper for older imports."""

    @property
    def name(self) -> str:
        return "pancreatic_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Deprecated. Use ctv_segmentation with tumor_type='nnunet_pancreatic'. "
            "This legacy wrapper is disabled to avoid empty-mask fallback results."
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
                "pancreatic_tumor_segmentation is deprecated. Use "
                "ctv_segmentation with tumor_type='nnunet_pancreatic' or provide label_path."
            ),
            metadata={
                "deprecated": True,
                "site": "pancreas",
                "recommended_tool": "ctv_segmentation",
                "tumor_type": "nnunet_pancreatic",
            },
        )
