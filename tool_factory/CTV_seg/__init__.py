"""
CTV Segmentation Tools
===================
Clinical Target Volume (CTV) segmentation tools for various tumor types.
Includes both nnU-Net based tools and VoCo pre-trained models.
"""

import sys
import os
import re
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
from .biomedparse_v2 import BiomedParseV2CTVTool, SITE_SPECS as BIOMEDPARSE_SITE_SPECS
from .model_catalog import CTVModelCatalogTool, catalog_with_local_status, filter_catalog

# Removed VoCoProstateTool (was using wrong Amos-MR weights)
# Removed VoCoPancSegTool (was pointing to PANORAMA weights with wrong out_channels)


TOOL_REGISTRY = {
    # CTV models. The pancreatic production path always uses nnU-Net.
    "pancreatic_tumor": NNUNetPancreaticTumorTool,
    # Non-pancreatic CTV segmentation uses Microsoft BiomedParse v2 (the
    # installed research adapter). The legacy VoCo SwinUNETR checkpoints were
    # deprecated because their liver/kidney/lung/colon lesion segmentation was
    # clinically unreliable; all former VoCo aliases now resolve to BiomedParse.
    "liver_tumor": BiomedParseV2CTVTool,
    "kidney_tumor": BiomedParseV2CTVTool,
    "lung_tumor": BiomedParseV2CTVTool,
    "colon_tumor": BiomedParseV2CTVTool,
    # Whole-gland prostate can be a prostate-brachytherapy target in some
    # workflows, but this is not a lesion segmentation model.
    "prostate_tumor": ProstateTumorSegmentationTool,
    # VoCo pre-trained aliases are retained for call compatibility but now
    # resolve to BiomedParse; the pancreatic one still goes to nnU-Net.
    "voco_pancreatic": NNUNetPancreaticTumorTool,
    "nnunet_pancreatic": NNUNetPancreaticTumorTool,
    "voco_liver": BiomedParseV2CTVTool,
    "voco_colon": BiomedParseV2CTVTool,
    "voco_kidney": BiomedParseV2CTVTool,
    "voco_lung": BiomedParseV2CTVTool,
    # Microsoft BiomedParse v2 research adapter (all supported tumor prompts).
    **{key: BiomedParseV2CTVTool for key in BIOMEDPARSE_SITE_SPECS},
    # Anatomical, embolism, infection, and MRI-only research models remain
    # importable below but are intentionally excluded from automatic CTV
    # routing. Treating their masks as a CT tumor target would be unsafe.
}


# Legacy VoCo site aliases now resolve to the corresponding BiomedParse prompt.
# These are the only non-pancreatic CTV sites supported for automatic routing.
BIOMEDPARSE_FALLBACKS = {
    "liver_tumor": "biomedparse_liver_tumor",
    "kidney_tumor": "biomedparse_kidney_lesion",
    "lung_tumor": "biomedparse_lung_lesion",
    "colon_tumor": "biomedparse_colon_primary",
    "voco_liver": "biomedparse_liver_tumor",
    "voco_kidney": "biomedparse_kidney_lesion",
    "voco_lung": "biomedparse_lung_lesion",
    "voco_colon": "biomedparse_colon_primary",
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


# The LLM-facing tumor_type options. The canonical non-pancreatic sites are the
# biomedparse_* prompts plus the friendly *_tumor aliases; the legacy voco_*
# aliases are kept in TOOL_REGISTRY only for backward call compatibility and are
# deliberately hidden from the agent so it cannot pick a deprecated VoCo name.
# Pancreatic production routing stays on nnU-Net.
_PREFERRED_TUMOR_TYPES = (
    ["pancreatic_tumor", "nnunet_pancreatic"]
    + list(BIOMEDPARSE_SITE_SPECS)
    + ["liver_tumor", "kidney_tumor", "lung_tumor", "colon_tumor", "prostate_tumor"]
)


class CTVSegmentationTool(BaseTool):
    """
    Unified CTV segmentation tool that delegates to tumor-specific tools.

    Automatically selects the appropriate segmentation model based on
    tumor type or falls back to generic segmentation.
    """

    def __init__(self):
        self._tumor_types = list(_PREFERRED_TUMOR_TYPES)

    @property
    def name(self) -> str:
        return "ctv_segmentation"

    @property
    def description(self) -> str:
        return (
            "Segment Clinical Target Volume (CTV/tumor) from CT images. "
            "Supports verified local pancreatic nnU-Net and optional external/experimental models "
            "listed by ctv_model_catalog. "
            "Input: CT image (SimpleITK) or path, required tumor_type for automatic "
            "segmentation, or label_path for an existing/manual CTV mask. "
            "Output: CTV binary mask and volume metrics."
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
                "label_path": {"type": "string", "description": "Path to existing CTV label file (optional)"},
                "tumor_type": {
                    "type": "string",
                    "description": f"Tumor type for specialized model. Options: {self._tumor_types}. Required unless label_path is provided.",
                    "enum": self._tumor_types,
                },
                # Backward-compatible alias for older model prompts. The
                # executor normalizes it immediately to tumor_type; new
                # callers should use tumor_type so the contract stays clear.
                "tumor_site": {
                    "type": "string",
                    "description": "Deprecated alias for tumor_type; accepts a site such as pancreas or liver.",
                },
                "target_value": {"type": "number", "default": 1, "description": "Label value for tumor voxels"},
                "fast_mode": {"type": "boolean", "default": False, "description": "Disable TTA, reduce threads"},
                "allow_empty": {"type": "boolean", "default": False, "description": "Only for tests; never allow empty clinical CTV by default"},
                "force_reexecution": {"type": "boolean", "default": False, "description": "Explicitly replace an existing in-memory CTV result"},
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
                "ctv_source": {"type": "string", "description": "CTV provenance: model or manual_label"},
            },
        }

    def _execute(self, **kwargs):
        import SimpleITK as sitk
        import numpy as np

        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        label_path = kwargs.get("label_path")
        tumor_type = (kwargs.get("tumor_type") or kwargs.get("tumor_site") or kwargs.get("site") or "").strip()
        site_aliases = {
            "pancreas": "nnunet_pancreatic",
            "pancreatic": "nnunet_pancreatic",
            "\u80f0\u817a": "nnunet_pancreatic",
            "liver": "biomedparse_liver_tumor",
            "\u809d\u810f": "biomedparse_liver_tumor",
            "kidney": "biomedparse_kidney_lesion",
            "\u80be": "biomedparse_kidney_lesion",
            "lung": "biomedparse_lung_lesion",
            "\u80ba": "biomedparse_lung_lesion",
            "colon": "biomedparse_colon_primary",
            "\u7ed3\u80a0": "biomedparse_colon_primary",
            "head_neck": "biomedparse_head_neck_cancer",
            "head and neck": "biomedparse_head_neck_cancer",
            "\u5934\u9888": "biomedparse_head_neck_cancer",
            "prostate": "prostate_tumor",
            "\u524d\u5217\u817a": "prostate_tumor",
        }
        tumor_type = site_aliases.get(tumor_type.lower(), tumor_type)
        target_value = kwargs.get("target_value", 1)
        fast_mode = kwargs.get("fast_mode", False)
        allow_empty = bool(kwargs.get("allow_empty", False))

        result = None
        from_label_path = False
        if label_path and os.path.exists(label_path):
            # Match both orientation and physical grid. Same-shaped NIfTI
            # arrays are not sufficient: origin/spacing/direction differences
            # can still mirror or translate a mask in the 2D viewer.
            if image is None and image_path is not None:
                image = sitk.ReadImage(image_path)
            from tool_factory.segmentation_alignment import align_label_to_reference
            if image is None:
                # Direct mask-only callers have no physical reference.  The
                # production route supplies the CT and uses physical-grid
                # resampling, while this fallback preserves tool compatibility.
                label_img = sitk.DICOMOrient(sitk.ReadImage(str(label_path)), "LPI")
            else:
                label_img = align_label_to_reference(label_path, image, "LPI")
            ctv_array = sitk.GetArrayFromImage(label_img)
            ctv_mask = label_img
            from_label_path = True
        else:
            if image is None and image_path is not None:
                image = sitk.ReadImage(image_path)
            elif image is None:
                return ToolResult(success=False, error="Either 'image' or 'image_path' must be provided")

            if not tumor_type:
                return ToolResult(
                    success=False,
                    error=(
                        "CTV tumor site is required before automatic segmentation. "
                        "Ask the user to specify the tumor site, or provide label_path "
                        "for an existing/manual CTV mask."
                    ),
                    metadata={
                        "clarification_required": True,
                        "clarification_question": (
                            "Which tumor site should BrachyBot segment as CTV? "
                            "Examples: pancreas, liver, kidney, lung, colon, prostate."
                        ),
                        "model_catalog": filter_catalog(),
                    },
                )
            if tumor_type:
                if tumor_type not in TOOL_REGISTRY:
                    return ToolResult(
                        success=False,
                        error=(
                            f"Unsupported CTV tumor_type '{tumor_type}'. Use label_path for a "
                            "manual CTV or run ctv_model_catalog to inspect verified models, "
                            "external checkpoints, and training datasets."
                        ),
                        metadata={
                            "tumor_type_used": tumor_type,
                            "model_catalog": filter_catalog(),
                        },
                    )
                tool = TOOL_REGISTRY[tumor_type]()

            tool_kwargs = {"image": image, "target_value": target_value, "fast_mode": fast_mode}
            if isinstance(tool, NNUNetPancreaticTumorTool):
                tool_kwargs["return_all_labels"] = True
            if isinstance(tool, BiomedParseV2CTVTool):
                # The research adapter selects its text prompt from the explicit
                # tumor_type. Normalize a legacy VoCo alias (voco_liver etc.) to
                # the corresponding biomedparse_* key so the adapter always
                # receives a supported prompt.
                bp_type = BIOMEDPARSE_FALLBACKS.get(tumor_type) or tumor_type
                tool_kwargs["tumor_type"] = bp_type
                tumor_type_used = bp_type
            else:
                tumor_type_used = tumor_type
            result = tool._execute(**tool_kwargs)
            if result.success:
                result_meta = result.metadata or {}
                result_meta.setdefault("tumor_type_used", tumor_type_used)
                from tool_factory.segmentation_alignment import (
                    align_label_array_to_reference,
                    align_label_image_to_reference,
                )

                # Normalize model output on the same LPI physical grid used by
                # the viewer.  The predictor may have run on the raw image
                # orientation, even when the returned array has the same shape.
                reference_lpi = sitk.DICOMOrient(image, "LPI")

                def _align_output(value, fallback_dtype=np.uint8):
                    if value is None:
                        return None
                    if isinstance(value, sitk.Image):
                        aligned = align_label_image_to_reference(value, image, "LPI")
                        return sitk.GetArrayFromImage(aligned)
                    aligned = align_label_array_to_reference(
                        value, image, "LPI", dtype=fallback_dtype,
                    )
                    return sitk.GetArrayFromImage(aligned)

                ctv_mask_value = result_meta.get("ctv_mask")
                if ctv_mask_value is None:
                    ctv_mask_value = result_meta.get("mask")
                if isinstance(ctv_mask_value, sitk.Image):
                    ctv_mask = align_label_image_to_reference(ctv_mask_value, image, "LPI")
                    ctv_array = sitk.GetArrayFromImage(ctv_mask)
                else:
                    ctv_array = _align_output(
                        result_meta.get("ctv_array", result_meta.get("mask_array", result.data))
                    )
                    ctv_mask = sitk.GetImageFromArray(ctv_array.astype(np.uint8))
                    ctv_mask.CopyInformation(reference_lpi)
                if result_meta.get("full_label_array") is not None:
                    result_meta["full_label_array"] = _align_output(
                        result_meta["full_label_array"], fallback_dtype=np.uint16
                    )
                if result_meta.get("oar_array") is not None:
                    result_meta["oar_array"] = _align_output(
                        result_meta["oar_array"], fallback_dtype=np.uint16
                    )
                result_meta["ctv_array"] = ctv_array
                result_meta["ctv_mask"] = ctv_mask
            else:
                # Preserve the adapter's diagnostic metadata on failure.  In
                # particular, the BiomedParse adapter reports the missing
                # runtime/checkpoint and marks the result research-only.  A
                # generic wrapper must not replace that evidence with a
                # vague empty-mask error, otherwise callers cannot explain
                # why a non-pancreatic model was unavailable.
                failure_meta = dict(result.metadata or {})
                failure_meta.setdefault("tumor_type_used", tumor_type)
                failure_meta.setdefault("model_catalog", filter_catalog())
                return ToolResult(
                    success=False,
                    data=result.data,
                    error=result.error,
                    message=result.message,
                    metadata=failure_meta,
                )

        # Keep the model's metadata available for both successful output and
        # empty-mask diagnostics.  Some research adapters intentionally
        # return a structured failure rather than raising an exception.
        res_meta = (result.metadata or {}) if result is not None else {}
        voxel_count = int(np.sum(ctv_array > 0))
        if voxel_count <= 0 and not allow_empty:
            failure_meta = dict(res_meta)
            failure_meta.setdefault(
                "tumor_type_used",
                tumor_type or ("manual_label" if from_label_path else "unknown"),
            )
            failure_meta.setdefault("model_catalog", filter_catalog())
            return ToolResult(
                success=False,
                error=(
                    "CTV segmentation produced an empty mask. This usually means the requested "
                    "tumor model is not installed, is an experimental checkpoint not wired for "
                    "inference, or the selected site is unsupported. Use label_path for a manual "
                    "CTV or run ctv_model_catalog to see verified models and datasets."
                ),
                metadata=failure_meta,
            )
        spacing = ctv_mask.GetSpacing() if hasattr(ctv_mask, 'GetSpacing') else (1, 1, 1)
        voxel_size = spacing[0] * spacing[1] * spacing[2]
        volume_mm3 = voxel_count * voxel_size

        # Keep CTV display names source-aware.
        label_map = dict(res_meta.get("label_map", {}))
        positive_labels = [int(v) for v in np.unique(ctv_array) if int(v) > 0]
        if not label_map:
            label_map = {
                label: ("CTV" if idx == 0 else f"CTV label {label}")
                for idx, label in enumerate(positive_labels)
            }

        tumor_type_name = (
            tumor_type.replace("_", " ").replace("nnunet ", "").replace("voco ", "")
            if tumor_type else ""
        )
        # Avoid labels such as ``prostate tumor tumor`` while keeping the
        # selected tumor site explicit for uploaded/manual CTV masks.
        tumor_type_name = re.sub(r"\s+tumor$", "", tumor_type_name, flags=re.IGNORECASE).strip()
        if tumor_type_name and 1 in label_map:
            label_map[1] = f"{tumor_type_name} tumor"
        import logging
        logging.getLogger(__name__).info(f"CTV label_map updated: {label_map}, tumor_type={tumor_type}, tumor_type_name={tumor_type_name}")

        meta = {
            "ctv_mask": ctv_mask,
            "ctv_array": ctv_array,
            "ctv_volume_mm3": float(volume_mm3),
            # Full multi-label array for data tree display (if available from nnUNet)
            "full_label_array": res_meta.get("full_label_array"),
            "ctv_voxel_count": voxel_count,
            "tumor_type_used": tumor_type or ("manual_label" if from_label_path else "auto"),
            "ctv_source": (
                "manual_label"
                if from_label_path
                else res_meta.get("ctv_source", "model")
            ),
            "label_grid_orientation": "LPI",
            "manual_label_orientation": "LPI" if from_label_path else None,
            "label_counts": res_meta.get("label_counts", {}),
            "label_map": label_map,
            "label_stats": res_meta.get("label_stats", {}),
            "model_catalog": filter_catalog(),
        }
        for provenance_key in (
            "research_only",
            "clinical_validation_status",
            "model_name",
            "repository",
            "model_url",
            "checkpoint",
            "text_prompt",
            "object_existence_confidence",
            "requested_tumor_type",
            "fallback_from_unavailable_model",
        ):
            if provenance_key in res_meta:
                meta[provenance_key] = res_meta[provenance_key]
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
    "CTVModelCatalogTool",
    "get_tool",
    "list_tools",
]
