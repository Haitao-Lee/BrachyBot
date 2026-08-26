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
from .totalsegmentator_liver_tumor import TotalSegmentatorLiverTumorTool
from .biomedparse_v2 import (
    BiomedParseV2CTVTool,
    BiomedParseV2GenericSegmentationTool,
    SITE_SPECS as BIOMEDPARSE_SITE_SPECS,
)
from .model_catalog import CTVModelCatalogTool, catalog_with_local_status, filter_catalog

# Removed VoCoProstateTool (was using wrong Amos-MR weights)
# Removed VoCoPancSegTool (was pointing to PANORAMA weights with wrong out_channels)


TOOL_REGISTRY = {
    # CTV models. The pancreatic production path always uses nnU-Net.
    "pancreatic_tumor": NNUNetPancreaticTumorTool,
    # Liver CTV uses the TotalSegmentator liver_vessels task. The adapter
    # exposes only its liver_tumor output and discards the other task labels.
    "liver_tumor": TotalSegmentatorLiverTumorTool,
    "totalsegmentator_liver_tumor": TotalSegmentatorLiverTumorTool,
    # Other non-pancreatic CTV candidates remain on the BiomedParse v2
    # research adapter.
    "kidney_tumor": BiomedParseV2CTVTool,
    "lung_tumor": BiomedParseV2CTVTool,
    "colon_tumor": BiomedParseV2CTVTool,
    # Whole-gland prostate can be a prostate-brachytherapy target in some
    # workflows, but this is not a lesion segmentation model.
    "prostate_tumor": ProstateTumorSegmentationTool,
    # VoCo aliases remain accepted for old calls. Liver follows the current
    # TotalSegmentator route; other sites retain their BiomedParse route.
    "voco_pancreatic": NNUNetPancreaticTumorTool,
    "nnunet_pancreatic": NNUNetPancreaticTumorTool,
    "voco_liver": TotalSegmentatorLiverTumorTool,
    "voco_colon": BiomedParseV2CTVTool,
    "voco_kidney": BiomedParseV2CTVTool,
    "voco_lung": BiomedParseV2CTVTool,
    # Microsoft BiomedParse v2 research adapter. The liver prompt remains
    # available to generic open segmentation, but not to CTV dispatch.
    **{
        key: BiomedParseV2CTVTool
        for key in BIOMEDPARSE_SITE_SPECS
        if key != "biomedparse_liver_tumor"
    },
    # Defensive compatibility alias for old callers that bypass normalization.
    "biomedparse_liver_tumor": TotalSegmentatorLiverTumorTool,
    # Anatomical, embolism, infection, and MRI-only research models remain
    # importable below but are intentionally excluded from automatic CTV
    # routing. Treating their masks as a CT tumor target would be unsafe.
}


# Non-liver legacy site aliases resolve to their BiomedParse prompts. Liver is
# intentionally absent because its CTV route is TotalSegmentator.
BIOMEDPARSE_FALLBACKS = {
    "kidney_tumor": "biomedparse_kidney_lesion",
    "lung_tumor": "biomedparse_lung_lesion",
    "colon_tumor": "biomedparse_colon_primary",
    "voco_kidney": "biomedparse_kidney_lesion",
    "voco_lung": "biomedparse_lung_lesion",
    "voco_colon": "biomedparse_colon_primary",
}


def normalize_tumor_type(value) -> str:
    """Return the canonical CTV route for a user, catalog, or legacy alias.

    ``ctv_segmentation`` is called from the UI, direct planning shortcut,
    restored Sessions, and the LLM.  Those callers historically used a mix of
    display labels, deprecated ``voco_*`` names, and BiomedParse catalog ids.
    Keeping the normalization here makes the tool contract authoritative and
    prevents a valid BiomedParse request from being rejected before inference.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = re.sub(r"[\s\-/]+", "_", raw.casefold()).strip("_")
    aliases = {
        # Pancreatic production segmentation remains on the validated nnU-Net.
        "pancreatic_tumor": "nnunet_pancreatic",
        "pancreatic": "nnunet_pancreatic",
        "pancreas": "nnunet_pancreatic",
        "voco_pancreatic": "nnunet_pancreatic",
        "nnunet_pancreatic": "nnunet_pancreatic",
        "\u80f0\u817a": "nnunet_pancreatic",
        "\u80f0\u817a\u80bf\u7624": "nnunet_pancreatic",
        "\u80f0\u817a\u764c": "nnunet_pancreatic",
        # TotalSegmentator liver-vessels task. These aliases all mean the
        # dedicated liver tumor CTV route, not generic BiomedParse.
        "liver": "totalsegmentator_liver_tumor",
        "liver_tumor": "totalsegmentator_liver_tumor",
        "liver_cancer": "totalsegmentator_liver_tumor",
        "hepatocellular": "totalsegmentator_liver_tumor",
        "hcc": "totalsegmentator_liver_tumor",
        "voco_liver": "totalsegmentator_liver_tumor",
        "totalsegmentator_liver_tumor": "totalsegmentator_liver_tumor",
        "total_segmentator_liver_tumor": "totalsegmentator_liver_tumor",
        # Historical CTV ids are redirected so old sessions cannot silently
        # switch back to BiomedParse after restart.
        "biomedparse_liver_tumor": "totalsegmentator_liver_tumor",
        "biomedparse_v2_liver_tumor": "totalsegmentator_liver_tumor",
        "\u809d": "totalsegmentator_liver_tumor",
        "\u809d\u810f": "totalsegmentator_liver_tumor",
        "\u809d\u810f\u80bf\u7624": "totalsegmentator_liver_tumor",
        "\u809d\u764c": "totalsegmentator_liver_tumor",
        "kidney": "biomedparse_kidney_lesion",
        "kidney_tumor": "biomedparse_kidney_lesion",
        "kidney_lesion": "biomedparse_kidney_lesion",
        "renal_tumor": "biomedparse_kidney_lesion",
        "voco_kidney": "biomedparse_kidney_lesion",
        "biomedparse_kidney_lesion": "biomedparse_kidney_lesion",
        "biomedparse_v2_kidney_lesion": "biomedparse_kidney_lesion",
        "\u80be": "biomedparse_kidney_lesion",
        "\u80be\u810f": "biomedparse_kidney_lesion",
        "\u80be\u810f\u80bf\u7624": "biomedparse_kidney_lesion",
        "lung": "biomedparse_lung_lesion",
        "lung_tumor": "biomedparse_lung_lesion",
        "lung_lesion": "biomedparse_lung_lesion",
        "voco_lung": "biomedparse_lung_lesion",
        "biomedparse_lung_lesion": "biomedparse_lung_lesion",
        "biomedparse_v2_lung_lesion": "biomedparse_lung_lesion",
        "\u80ba": "biomedparse_lung_lesion",
        "\u80ba\u80bf\u7624": "biomedparse_lung_lesion",
        "\u80ba\u764c": "biomedparse_lung_lesion",
        "colon": "biomedparse_colon_primary",
        "colon_tumor": "biomedparse_colon_primary",
        "colon_primary": "biomedparse_colon_primary",
        "voco_colon": "biomedparse_colon_primary",
        "biomedparse_colon_primary": "biomedparse_colon_primary",
        "biomedparse_v2_colon_primary": "biomedparse_colon_primary",
        "\u7ed3\u80a0": "biomedparse_colon_primary",
        "\u7ed3\u80a0\u80bf\u7624": "biomedparse_colon_primary",
        "\u7ed3\u80a0\u764c": "biomedparse_colon_primary",
        "head_neck": "biomedparse_head_neck_cancer",
        "head_and_neck": "biomedparse_head_neck_cancer",
        "head_neck_tumor": "biomedparse_head_neck_cancer",
        "head_neck_cancer": "biomedparse_head_neck_cancer",
        "biomedparse_head_neck_cancer": "biomedparse_head_neck_cancer",
        "biomedparse_v2_head_neck_cancer": "biomedparse_head_neck_cancer",
        "\u5934\u9888": "biomedparse_head_neck_cancer",
        "\u5934\u9888\u80bf\u7624": "biomedparse_head_neck_cancer",
        "prostate": "prostate_tumor",
        "prostate_tumor": "prostate_tumor",
        "whole_prostate": "prostate_tumor",
        "\u524d\u5217\u817a": "prostate_tumor",
        "\u524d\u5217\u817a\u764c": "prostate_tumor",
    }
    return aliases.get(normalized, raw)


def resolve_ctv_tumor_type(params) -> str:
    """Resolve the canonical CTV model from all supported call aliases.

    The CTV tool is called by the UI, direct workflow shortcuts, the model
    catalog follow-up, and restored Session actions. Older callers used
    ``model`` or ``organ`` while the public contract uses ``tumor_type``.
    Keeping this fallback at the tool boundary prevents a valid site from
    being lost between those entry points.
    """
    if not isinstance(params, dict):
        return ""
    fallback = ""
    for key in (
        "tumor_type",
        "model",
        "tumor_site",
        "site",
        "organ",
        "organ_type",
    ):
        value = params.get(key)
        if value is not None and str(value).strip():
            candidate = normalize_tumor_type(value)
            if not candidate:
                continue
            # Older catalog callers sometimes send a stale model id together
            # with a valid organ/site. Prefer the first registered route so a
            # bad optional alias cannot hide a usable clinical input.
            if candidate in TOOL_REGISTRY:
                return candidate
            if not fallback:
                fallback = candidate
    return fallback


def get_tool(tool_name: str):
    """Get a CTV segmentation tool, normalizing legacy aliases first.

    CTV calls can originate from a restored Session, the browser selector, a
    planning shortcut, or the LLM.  Resolving aliases at this boundary keeps
    those entry points on the same executor instead of making old identifiers
    fail before the real tool is reached.
    """
    requested_name = str(tool_name or "").strip()
    canonical_name = normalize_tumor_type(requested_name)
    tool_class = TOOL_REGISTRY.get(canonical_name)
    if tool_class is None:
        raise ValueError(
            f"Unknown tool: {requested_name}. Available: {list(TOOL_REGISTRY.keys())}"
        )
    return tool_class()


def list_tools():
    """List all available CTV segmentation tools."""
    return list(TOOL_REGISTRY.keys())


# The LLM-facing tumor_type options. Liver is advertised as the dedicated
# TotalSegmentator route; other supported non-pancreatic sites remain the
# BiomedParse candidate prompts. Legacy aliases stay server-side only.
# Pancreatic production routing stays on nnU-Net.
_PREFERRED_TUMOR_TYPES = (
    ["pancreatic_tumor", "nnunet_pancreatic"]
    + [
        key for key in BIOMEDPARSE_SITE_SPECS
        if key != "biomedparse_liver_tumor"
    ]
    + [
        "totalsegmentator_liver_tumor",
        "kidney_tumor",
        "lung_tumor",
        "colon_tumor",
        "prostate_tumor",
    ]
)


# Plausibility bounds for manually imported CTV contours. Brachytherapy
# targets treated with direct seed implantation stay far below one litre;
# the absolute cap is deliberately generous, and the relative cap catches
# masks that cover most of the scanned body even on very large FOV scans.
_MANUAL_CTV_MAX_VOLUME_MM3 = 1_000_000.0  # 1000 cm3
_MANUAL_CTV_MAX_BODY_FRACTION = 0.20


def _implausible_manual_ctv_error(volume_mm3: float, voxel_count: int, ct_image) -> "str | None":
    """Return a rejection message when an imported CTV cannot be a real target.

    The imported file is aligned to the CT grid before this check, so a
    misaligned-but-correct contour is not penalized here; only physically
    implausible target volumes are rejected.
    """
    if volume_mm3 <= _MANUAL_CTV_MAX_VOLUME_MM3:
        return None
    measured_cm3 = volume_mm3 / 1000.0
    body_cm3 = None
    if ct_image is not None:
        try:
            import SimpleITK as sitk

            reference = sitk.DICOMOrient(ct_image, "LPI")
            ct_array = sitk.GetArrayFromImage(reference)
            if ct_array.ndim == 3 and np.issubdtype(ct_array.dtype, np.number):
                spacing = reference.GetSpacing()
                body_voxels = int(np.count_nonzero(ct_array > -300))
                body_cm3 = body_voxels * spacing[0] * spacing[1] * spacing[2] / 1000.0
        except Exception:
            body_cm3 = None
    detail = f"measured CTV volume {measured_cm3:.0f} cm3 ({voxel_count} voxels)"
    if body_cm3:
        fraction = volume_mm3 / (body_cm3 * 1000.0)
        detail += f", {fraction * 100:.0f}% of the scanned body ({body_cm3:.0f} cm3)"
        if fraction <= _MANUAL_CTV_MAX_BODY_FRACTION and volume_mm3 <= (
            _MANUAL_CTV_MAX_VOLUME_MM3 * 4
        ):
            # A very large FOV scan can push an otherwise plausible large
            # target over the absolute cap while staying small relative to
            # the body; trust the relative bound in that window.
            return None
        if fraction > _MANUAL_CTV_MAX_BODY_FRACTION:
            limit = f"limit {_MANUAL_CTV_MAX_BODY_FRACTION * 100:.0f}% of body volume"
        else:
            limit = f"limit {_MANUAL_CTV_MAX_VOLUME_MM3 / 1000.0:.0f} cm3"
    else:
        limit = f"limit {_MANUAL_CTV_MAX_VOLUME_MM3 / 1000.0:.0f} cm3"
    return (
        f"The uploaded CTV mask is not a plausible brachytherapy target "
        f"({detail}; {limit}). It likely contains a whole-organ or body "
        f"contour rather than a tumour. Export or resample the actual tumour "
        f"contour and upload it again."
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
            "Supports verified local pancreatic nnU-Net, the TotalSegmentator "
            "liver_vessels/liver_tumor route, and optional models listed by "
            "ctv_model_catalog. "
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
                    "description": (
                        "Tumor type for specialized model. Canonical options: "
                        f"{self._tumor_types}. Friendly anatomy names, legacy "
                        "VoCo aliases, and historical BiomedParse liver ids are "
                        "normalized by the server. Liver CTV always uses "
                        "TotalSegmentator and exposes only liver_tumor. Required "
                        "unless label_path is provided."
                    ),
                },
                # Backward-compatible alias for older model prompts. The
                # executor normalizes it immediately to tumor_type; new
                # callers should use tumor_type so the contract stays clear.
                "tumor_site": {
                    "type": "string",
                    "description": "Deprecated alias for tumor_type; accepts a site such as pancreas or liver.",
                },
                "model": {
                    "type": "string",
                    "description": "Compatibility alias for a catalog model id, such as totalsegmentator_liver_tumor.",
                },
                "site": {
                    "type": "string",
                    "description": "Compatibility alias for the tumor site.",
                },
                "organ": {
                    "type": "string",
                    "description": "Compatibility alias for the target organ, such as liver.",
                },
                "organ_type": {
                    "type": "string",
                    "description": "Compatibility alias for the target organ.",
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
        tumor_type = resolve_ctv_tumor_type(kwargs)
        target_value = kwargs.get("target_value", 1)
        fast_mode = kwargs.get("fast_mode", False)
        allow_empty = bool(kwargs.get("allow_empty", False))

        result = None
        from_label_path = False
        manual_label_selection = {}
        uploaded_label_array = None
        uploaded_label_path = None
        uploaded_label_geometry = None
        plausibility_warning = None
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
            source_label_array = sitk.GetArrayFromImage(label_img)
            uploaded_label_array = np.ascontiguousarray(source_label_array)
            uploaded_label_path = str(label_path)
            uploaded_label_geometry = {
                "shape": [int(value) for value in uploaded_label_array.shape],
                "spacing": [float(value) for value in label_img.GetSpacing()],
                "origin": [float(value) for value in label_img.GetOrigin()],
                "direction": [float(value) for value in label_img.GetDirection()],
            }
            from tool_factory.segmentation_alignment import select_label_as_binary
            try:
                ctv_array, manual_label_selection = select_label_as_binary(
                    source_label_array,
                    target_value,
                )
            except ValueError as exc:
                return ToolResult(
                    success=False,
                    error=str(exc),
                    metadata={
                        "ctv_source": "manual_label",
                        "code": "invalid_ctv_target_label",
                    },
                )
            # The planning pipeline's semantic contract is binary CTV: value
            # 1 is target, while 2/3 are reserved for embedded obstacles.
            # Preserve the selected source id in metadata, never in the active
            # mask handed to trajectory and dose code.
            ctv_mask = sitk.GetImageFromArray(ctv_array)
            ctv_mask.CopyInformation(label_img)
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
                # runtime/checkpoint and marks the result as BiomedParse-backed.  A
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

            # Build an honest, diagnostic reason instead of a generic "model is
            # missing" guess. When the underlying model actually ran, it reports
            # which labels it found, so we can tell the user exactly what
            # happened and what to check — and distinguish a real model
            # availability problem from a data problem.
            if from_label_path:
                diagnostic = (
                    "The provided CTV label is empty (no foreground voxels). "
                    "Please check the label file: it may be background-only, "
                    "misaligned with the CT grid, or out of the image range."
                )
            else:
                label_counts = res_meta.get("label_counts") or {}
                found = {
                    name: int(count)
                    for name, count in label_counts.items()
                    if count and int(count) > 0
                }
                if found:
                    found_desc = ", ".join(
                        f"{name} ({count} vox)" for name, count in found.items()
                    )
                    diagnostic = (
                        f"The segmentation model completed inference but did NOT detect any "
                        f"tumor region in this CT (labels it did find: {found_desc}). "
                        f"This is usually a data problem rather than a missing model: the CT "
                        f"may not cover the full tumor extent (too few slices / large slice "
                        f"thickness), the tumor may be outside the scanned field, or too "
                        f"subtle for this model. Verify the CT actually covers the tumor "
                        f"(check slice count and spacing), or provide label_path for a "
                        f"manual/clinical CTV."
                    )
                else:
                    diagnostic = (
                        "CTV segmentation produced an empty mask. The model did not "
                        "detect the requested tumor_type in this CT. This can mean the "
                        "model is not installed, is an experimental checkpoint not wired "
                        "for inference, the selected site is unsupported, or the CT does "
                        "not cover the tumor. Use label_path for a manual CTV or run "
                        "ctv_model_catalog to inspect verified models and datasets."
                    )
            return ToolResult(
                success=False,
                error=diagnostic,
                metadata=failure_meta,
            )
        spacing = ctv_mask.GetSpacing() if hasattr(ctv_mask, 'GetSpacing') else (1, 1, 1)
        voxel_size = spacing[0] * spacing[1] * spacing[2]
        volume_mm3 = voxel_count * voxel_size

        # An imported manual mask is untrusted clinical input. A contour that
        # fills most of the body is not a brachytherapy target: accepting it
        # silently made trajectory planning run for ~20 minutes on a
        # body-sized "target" and then rejected every needle as intersecting
        # the mask's embedded vessel labels. The raw upload is staged before
        # the operator chooses a clinical label; explicit Move to CTV applies
        # the same check to the selected candidate before planning can consume it.
        if from_label_path:
            plausibility_warning = _implausible_manual_ctv_error(
                volume_mm3, voxel_count, image
            )
            if plausibility_warning:
                # A multi-label upload is staged before the operator chooses
                # the clinical target. Rejecting the selected default here
                # would discard valid candidate labels and recreate the old
                # whole-file-import failure. Promotion performs the same
                # plausibility check on the explicitly selected child.
                logger.warning("Manual CTV upload requires label selection: %s", plausibility_warning)

        # Keep CTV display names source-aware.
        label_map = dict(res_meta.get("label_map", {}))
        if from_label_path:
            # Source label ids are provenance only.  The active manual CTV is
            # always a single binary Data Tree object on label 1.
            label_map = {1: "CTV"}
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
        if from_label_path:
            meta.update({
                "ctv_target_value": manual_label_selection.get("selected_target_value"),
                "ctv_requested_target_value": manual_label_selection.get("requested_target_value"),
                "ctv_source_labels": manual_label_selection.get("source_labels", []),
                "ctv_source_label_counts": manual_label_selection.get("source_label_counts", {}),
                "ctv_normalized_binary": True,
                "ctv_normalization_version": 1,
                "uploaded_label_array": uploaded_label_array,
                "uploaded_label_path": uploaded_label_path,
                "uploaded_label_geometry": uploaded_label_geometry,
                "ctv_staged_only": True,
                "ctv_plausibility_warning": plausibility_warning,
                "label_counts": {1: int(voxel_count)},
                # A manual replacement must not inherit model-derived label
                # statistics from the previous CTV in this Session.
                "label_stats": {},
            })
        for provenance_key in (
            "model_name",
            "repository",
            "model_url",
            "checkpoint",
            "text_prompt",
            "total_segmentator_task",
            "total_segmentator_label",
            "segmentation_task",
            "segmentation_label",
            "source_labels_exposed",
            "target_semantics",
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
