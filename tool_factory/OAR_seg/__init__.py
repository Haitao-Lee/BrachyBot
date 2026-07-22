"""
OAR Segmentation Tools
=====================
Organs At Risk (OAR) segmentation tools for various anatomical sites.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tool_factory import BaseTool, ToolResult

from .totalsegmentator_oar import TotalSegmentatorOARTool
from .pancreatic_oar import PancreaticOARTool


TOOL_REGISTRY = {
    "totalsegmentator_oar": TotalSegmentatorOARTool,
    "pancreatic_oar": PancreaticOARTool,
}

# The legacy VoCo OAR wrappers are intentionally not public tools. Their MONAI
# preprocessing crops and reorients the volume without an inverse transform,
# so attaching the original CT geometry can produce a plausible but misplaced
# mask. TotalSegmentator covers the same structures with a validated spatial
# round trip; keep the legacy modules only as research references until their
# checkpoints and inverse transforms are independently validated.


def get_tool(tool_name: str):
    """Get an OAR segmentation tool by name."""
    tool_class = TOOL_REGISTRY.get(tool_name)
    if tool_class is None:
        raise ValueError(f"Unknown tool: {tool_name}. Available: {list(TOOL_REGISTRY.keys())}")
    return tool_class()


def list_tools():
    """List all available OAR segmentation tools."""
    return list(TOOL_REGISTRY.keys())


class OARSegmentationTool(BaseTool):
    """
    Unified OAR segmentation tool that delegates to appropriate models.

    Automatically selects TotalSegmentator for general organs or
    nnU-Net for pancreatic structures based on the anatomical site.
    """

    @property
    def name(self) -> str:
        return "oar_segmentation"

    @property
    def description(self) -> str:
        return (
            "Segment Organs At Risk (OAR) from CT images. "
            "Automatically selects appropriate model based on anatomical site. "
            "Supports 40+ organs and vessels via TotalSegmentator, plus pancreas via nnU-Net. "
            "Input: CT image (SimpleITK) or path. "
            "Output: Multi-label OAR mask with per-organ metrics."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "image": {
                    "type": "object",
                    "description": "Server-injected SimpleITK Image of CT scan",
                    "x-server-injected": True,
                },
                "image_path": {"type": "string", "description": "Path to CT file (.nii.gz, .mhd)"},
                "label_path": {"type": "string", "description": "Path to existing OAR label file (optional)"},
                "organ_type": {
                    "type": "string",
                    "description": "'pancreatic' for pancreas/artery/vein, 'aorta' for vessels, 'general' for other organs",
                    "enum": ["pancreatic", "aorta", "general"],
                },
                "task": {"type": "string", "description": "TotalSegmentator task (default: 'body')"},
            },
            "required": [],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "oar_mask": {"type": "object", "description": "SimpleITK multi-label OAR mask"},
                "oar_array": {"type": "array", "description": "NumPy array of OAR labels"},
                "organ_counts": {"type": "object", "description": "Voxel counts per organ label"},
            },
        }

    def _execute(self, **kwargs):
        import SimpleITK as sitk

        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        label_path = kwargs.get("label_path")
        organ_type = kwargs.get("organ_type", "general")
        label_img = None

        if label_path and os.path.exists(label_path):
            label_img = sitk.ReadImage(label_path)
            oar_array = sitk.GetArrayFromImage(label_img)
        else:
            if image is None and image_path is not None:
                image = sitk.ReadImage(image_path)
            elif image is None:
                return ToolResult(success=False, error="Either 'image' or 'image_path' must be provided")

            if organ_type == "pancreatic":
                tool = PancreaticOARTool()
            else:
                tool = TotalSegmentatorOARTool()

            result = tool._execute(image=image)
            if result.success:
                oar_array = result.metadata.get("oar_array", result.data)
            else:
                return result

        import numpy as np
        organ_counts = {}
        organ_names = {}
        if oar_array is not None:
            unique_labels = np.unique(oar_array)
            for label in unique_labels:
                if label > 0:
                    organ_counts[int(label)] = int(np.sum(oar_array == label))

            # Try to get organ names from TotalSegmentator label mapping
            try:
                from .totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
                for label_id in organ_counts:
                    organ_names[label_id] = TOTALSEG_LABEL_MAPPING.get(
                        label_id, f"Unmapped structure (label {label_id})"
                    )
            except ImportError:
                for label_id in organ_counts:
                    organ_names[label_id] = f"Unmapped structure (label {label_id})"

        return ToolResult(
            success=True,
            data=oar_array,
            message=f"OAR segmentation completed. {len(organ_counts)} organs segmented.",
            metadata={
                "oar_mask": image if image is not None else (label_img if label_img is not None else label_path),
                "oar_array": oar_array,
                "organ_counts": organ_counts,
                "organ_names": organ_names,
            },
        )


__all__ = [
    "BaseTool",
    "ToolResult",
    "TotalSegmentatorOARTool",
    "PancreaticOARTool",
    "VoCoTotalSegmentatorTool",
    "VoCoAortaVesselTool",
    "OARSegmentationTool",
    "get_tool",
    "list_tools",
]
