"""
CTV Segmentation Tools
===================
Clinical Target Volume (CTV) segmentation tools for various tumor types.
Includes both nnU-Net based tools and VoCo pre-trained models.
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tool_factory import BaseTool, ToolResult

from .pancreatic_tumor import PancreaticTumorSegmentationTool
from .liver_tumor import LiverTumorSegmentationTool
from .kidney_tumor import KidneyTumorSegmentationTool
from .prostate_tumor import ProstateTumorSegmentationTool
from .lung_tumor import LungTumorSegmentationTool
from .head_neck_tumor import HeadNeckTumorSegmentationTool

from .pancreatic_tumor_voco import VoCoPancreaticTumorTool
from .liver_tumor_voco import VoCoLiverTumorTool
from .colon_tumor_voco import VoCoColonTumorTool
from .kidney_tumor_voco import VoCoKidneyTumorTool
from .lung_tumor_voco import VoCoLungTumorTool
from .btcv_tumor_voco import VoCoBTCVTumorTool
from .segthor_tumor_voco import VoCoSegThorTumorTool
from .fumpe_voco import VoCoFUMPESegTool
from .covid_voco import VoCoCOVIDSegTool
from .aorta_voco import VoCoAortaSegTool
from .brats21_voco import VoCoBRATS21SegTool
from .pancreatic_tumor_nnunet import NNUNetPancreaticTumorTool

# Removed VoCoProstateTool (was using wrong Amos-MR weights)
# Removed VoCoPancSegTool (was pointing to PANORAMA weights with wrong out_channels)


TOOL_REGISTRY = {
    # nnU-Net based tools
    "pancreatic_tumor": PancreaticTumorSegmentationTool,
    "liver_tumor": LiverTumorSegmentationTool,
    "kidney_tumor": KidneyTumorSegmentationTool,
    "prostate_tumor": ProstateTumorSegmentationTool,
    "lung_tumor": LungTumorSegmentationTool,
    "head_neck_tumor": HeadNeckTumorSegmentationTool,
    # VoCo pre-trained tools (tumor-focused)
    "voco_pancreatic": VoCoPancreaticTumorTool,
    "nnunet_pancreatic": NNUNetPancreaticTumorTool,
    "voco_liver": VoCoLiverTumorTool,
    "voco_colon": VoCoColonTumorTool,
    "voco_kidney": VoCoKidneyTumorTool,
    "voco_lung": VoCoLungTumorTool,
    # VoCo pre-trained tools (organ/structure segmentation)
    "voco_btcv": VoCoBTCVTumorTool,
    "voco_segthor": VoCoSegThorTumorTool,
    "voco_fumpe": VoCoFUMPESegTool,
    "voco_covid": VoCoCOVIDSegTool,
    "voco_aorta": VoCoAortaSegTool,
    "voco_brats21": VoCoBRATS21SegTool,
}


def get_tool(tool_name: str):
    """Get a CTV segmentation tool by name."""
    tool_class = TOOL_REGISTRY.get(tool_name)
    if tool_class is None:
        raise ValueError(f"Unknown tool: {tool_name}. Available: {list(TOOL_REGISTRY.keys())}")
    return tool_class()


def list_tools():
    """List all available CTV segmentation tools."""
    return list(TOOL_REGISTRY.keys())


class CTVSegmentationTool(BaseTool):
    """
    Unified CTV segmentation tool that delegates to tumor-specific tools.

    Automatically selects the appropriate segmentation model based on
    tumor type or falls back to generic segmentation.
    """

    def __init__(self):
        self._tumor_types = list(TOOL_REGISTRY.keys())

    @property
    def name(self) -> str:
        return "ctv_segmentation"

    @property
    def description(self) -> str:
        return (
            "Segment Clinical Target Volume (CTV/tumor) from CT images. "
            "Supports: pancreatic, liver, kidney, prostate, lung, colon, head_neck, btcv, segthor, "
            "fumpe, covid, aorta, brats21, panc. "
            "Uses nnU-Net or VoCo pre-trained models. "
            "Input: CT image (SimpleITK) or path, optional tumor_type. "
            "Output: CTV binary mask and volume metrics."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "image": {"type": "object", "description": "SimpleITK Image of CT scan"},
                "image_path": {"type": "string", "description": "Path to CT file (.nii.gz, .mhd)"},
                "label_path": {"type": "string", "description": "Path to existing CTV label file (optional)"},
                "tumor_type": {
                    "type": "string",
                    "description": f"Tumor type for specialized model. Options: {self._tumor_types}. Auto-detect if not specified.",
                    "enum": self._tumor_types,
                },
                "target_value": {"type": "number", "default": 1, "description": "Label value for tumor voxels"},
                "fast_mode": {"type": "boolean", "default": False, "description": "Disable TTA, reduce threads"},
            },
            "required": [],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "ctv_mask": {"type": "object", "description": "SimpleITK binary mask of CTV"},
                "ctv_array": {"type": "array", "description": "NumPy array of CTV mask"},
                "ctv_volume_mm3": {"type": "number", "description": "CTV volume in mm3"},
                "ctv_voxel_count": {"type": "integer", "description": "Number of CTV voxels"},
                "tumor_type_used": {"type": "string", "description": "Tumor segmentation model used"},
            },
        }

    def _execute(self, **kwargs):
        import SimpleITK as sitk
        import numpy as np

        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        label_path = kwargs.get("label_path")
        tumor_type = kwargs.get("tumor_type")
        target_value = kwargs.get("target_value", 1)
        fast_mode = kwargs.get("fast_mode", False)

        result = None
        if label_path and os.path.exists(label_path):
            label_img = sitk.ReadImage(label_path)
            ctv_array = sitk.GetArrayFromImage(label_img)
            ctv_mask = label_img
        else:
            if image is None and image_path is not None:
                image = sitk.ReadImage(image_path)
            elif image is None:
                return ToolResult(success=False, error="Either 'image' or 'image_path' must be provided")

            if tumor_type and tumor_type in TOOL_REGISTRY:
                tool = TOOL_REGISTRY[tumor_type]()
            else:
                # Default to nnUNet pancreatic tumor tool
                tool = NNUNetPancreaticTumorTool()

            result = tool._execute(image=image, target_value=target_value, fast_mode=fast_mode, return_all_labels=True)
            if result.success:
                ctv_array = result.metadata.get("mask_array", result.data)
                ctv_mask = result.metadata.get("mask", image)
            else:
                return result

        voxel_count = int(np.sum(ctv_array > 0))
        spacing = ctv_mask.GetSpacing() if hasattr(ctv_mask, 'GetSpacing') else (1, 1, 1)
        voxel_size = spacing[0] * spacing[1] * spacing[2]
        volume_mm3 = voxel_count * voxel_size

        # Update label map with tumor type name (e.g., "pancreatic tumor" instead of just "tumor")
        label_map = result.metadata.get("label_map", {}) if result is not None else {}
        tumor_type_name = (tumor_type or "tumor").replace("_", " ").replace("nnunet ", "").replace("voco ", "")
        if 1 in label_map:
            if tumor_type_name == "tumor":
                # Default tool is nnUNet pancreatic — use "pancreatic tumor"
                label_map[1] = "pancreatic tumor"
            else:
                label_map[1] = f"{tumor_type_name} tumor"
        import logging
        logging.getLogger(__name__).info(f"CTV label_map updated: {label_map}, tumor_type={tumor_type}, tumor_type_name={tumor_type_name}")

        res_meta = result.metadata if result is not None else {}
        meta = {
            "ctv_mask": ctv_mask,
            "ctv_array": ctv_array,
            "ctv_volume_mm3": float(volume_mm3),
            # Full multi-label array for data tree display (if available from nnUNet)
            "full_label_array": res_meta.get("full_label_array"),
            "ctv_voxel_count": voxel_count,
            "tumor_type_used": tumor_type or "auto",
            "label_counts": res_meta.get("label_counts", {}),
            "label_map": label_map,
            "label_stats": res_meta.get("label_stats", {}),
        }
        # Pass through OAR data if present (e.g. artery/vein from nnUNet pancreatic)
        if "oar_array" in res_meta:
            meta["oar_array"] = res_meta["oar_array"]
        if "oar_mask" in res_meta:
            meta["oar_mask"] = res_meta["oar_mask"]
        if "organ_names" in res_meta:
            meta["organ_names"] = res_meta["organ_names"]

        return ToolResult(
            success=True,
            data=ctv_array,
            message=f"CTV segmentation completed. Volume: {volume_mm3:.1f} mm3",
            metadata=meta,
        )


__all__ = [
    "BaseTool",
    "ToolResult",
    "PancreaticTumorSegmentationTool",
    "LiverTumorSegmentationTool",
    "KidneyTumorSegmentationTool",
    "ProstateTumorSegmentationTool",
    "LungTumorSegmentationTool",
    "HeadNeckTumorSegmentationTool",
    "VoCoPancreaticTumorTool",
    "VoCoLiverTumorTool",
    "VoCoColonTumorTool",
    "VoCoKidneyTumorTool",
    "VoCoLungTumorTool",
    "VoCoBTCVTumorTool",
    "VoCoSegThorTumorTool",
    "VoCoFUMPESegTool",
    "VoCoCOVIDSegTool",
    "VoCoAortaSegTool",
    "VoCoBRATS21SegTool",
    "NNUNetPancreaticTumorTool",
    "CTVSegmentationTool",
    "get_tool",
    "list_tools",
]
