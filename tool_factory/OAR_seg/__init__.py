"""
OAR Segmentation Tools
=====================
Organs At Risk (OAR) segmentation tools for various anatomical sites.
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tool_factory import BaseTool, ToolResult

from .totalsegmentator_oar import (
    TotalSegmentatorOARTool,
    TOTALSEG_LABEL_MAPPING,
    normalize_totalseg_organ_filter,
)
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
            "Use organ_filter for a focused anatomy request; only those named structures are "
            "returned and persisted. Omit organ_filter only when a full OAR set is requested. "
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
                "organ_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional requested anatomy subset, e.g. ['liver'] or "
                        "['kidney_left', 'kidney_right']. When supplied, no other OAR "
                        "labels are returned or persisted."
                    ),
                },
                "force_reexecution": {"type": "boolean", "default": False, "description": "Explicitly replace an existing in-memory OAR result"},
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
        raw_organ_filter = kwargs.get("organ_filter")
        label_img = None
        from_label_path = bool(label_path and os.path.exists(label_path))
        generated_metadata = {}

        try:
            organ_filter = normalize_totalseg_organ_filter(raw_organ_filter)
        except ValueError as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                message=f"OAR segmentation rejected: {exc}",
                metadata={
                    "oar_is_full": False,
                    "oar_scope": "focused",
                    "requested_organs": raw_organ_filter,
                },
            )

        if from_label_path and organ_filter is not None:
            # Uploaded labels have no reliable anatomical label ontology, so
            # filtering their integer IDs by a text anatomy name would either
            # leak unrelated masks or silently discard a reviewed contour.
            # The server execution boundary avoids injecting a saved upload
            # for focused model requests; reject an explicit low-level mix
            # rather than broadening it to the whole uploaded structure set.
            return ToolResult(
                success=False,
                error=(
                    "A named organ_filter cannot be applied safely to an uploaded OAR mask. "
                    "Run model segmentation for the requested anatomy or classify the uploaded label first."
                ),
                metadata={
                    "oar_is_full": False,
                    "oar_scope": "focused",
                    "requested_organs": list(organ_filter),
                },
            )

        if from_label_path:
            # Match both orientation and physical grid. Shape-only checks are
            # unsafe because a same-shaped mask may still be translated or
            # mirrored relative to the CT.
            if image is None and image_path is not None:
                image = sitk.ReadImage(image_path)
            from tool_factory.segmentation_alignment import align_label_to_reference
            if image is None:
                # Direct mask-only callers have no physical reference.  Keep
                # this low-level compatibility path deterministic; API routes
                # always pass the CT and therefore use physical resampling.
                label_img = sitk.DICOMOrient(sitk.ReadImage(str(label_path)), "LPI")
            else:
                label_img = align_label_to_reference(label_path, image, "LPI")
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

            if isinstance(tool, TotalSegmentatorOARTool):
                result = tool._execute(image=image, organ_filter=organ_filter)
            else:
                result = tool._execute(image=image)
            if result.success:
                generated_metadata = result.metadata or {}
                from tool_factory.segmentation_alignment import (
                    align_label_array_to_reference,
                    align_label_image_to_reference,
                )

                raw_mask = generated_metadata.get("oar_mask")
                if isinstance(raw_mask, sitk.Image):
                    aligned_mask = align_label_image_to_reference(raw_mask, image, "LPI")
                    oar_array = sitk.GetArrayFromImage(aligned_mask)
                else:
                    raw_array = generated_metadata.get("oar_array", result.data)
                    aligned_mask = align_label_array_to_reference(
                        raw_array, image, "LPI", dtype=np.uint16,
                    )
                    oar_array = sitk.GetArrayFromImage(aligned_mask)
                # Keep a focused request focused even if a delegated backend
                # ignored the filter (for example a site-specific OAR model).
                # This is the persistence boundary: only selected labels may
                # reach the Data Tree, viewer, workspace snapshot, or later
                # chat context.
                if organ_filter is not None:
                    supplied_names = generated_metadata.get("organ_names") or {}
                    allowed_names = set(organ_filter)
                    allowed_labels = []
                    for label_id in np.unique(oar_array):
                        if int(label_id) <= 0:
                            continue
                        name = supplied_names.get(
                            int(label_id),
                            supplied_names.get(str(int(label_id)), ""),
                        )
                        if not name:
                            name = TOTALSEG_LABEL_MAPPING.get(int(label_id), "")
                        if str(name).strip().lower() in allowed_names:
                            allowed_labels.append(int(label_id))
                    if not allowed_labels:
                        return ToolResult(
                            success=False,
                            error=(
                                "Requested OAR structure(s) were not present in the model output: "
                                + ", ".join(organ_filter)
                            ),
                            metadata={
                                "oar_is_full": False,
                                "oar_scope": "focused",
                                "requested_organs": list(organ_filter),
                            },
                        )
                    oar_array = np.where(np.isin(oar_array, allowed_labels), oar_array, 0)
                    aligned_mask = sitk.GetImageFromArray(oar_array.astype(np.uint16, copy=False))
                    aligned_mask.CopyInformation(image)

                generated_metadata["oar_mask"] = aligned_mask
                generated_metadata["oar_array"] = oar_array
            else:
                return result

        organ_counts = {}
        organ_names = {}
        if oar_array is not None:
            unique_labels = np.unique(oar_array)
            for label in unique_labels:
                if label > 0:
                    organ_counts[int(label)] = int(np.sum(oar_array == label))

            if from_label_path:
                # Uploaded labels have no reliable ontology. Keep them as
                # numbered OARs and let the user rename/reclassify them.
                organ_names = {
                    label_id: f"OAR {ordinal}"
                    for ordinal, label_id in enumerate(sorted(organ_counts), start=1)
                }
            else:
                supplied_names = generated_metadata.get("organ_names") or {}
                organ_names = {
                    label_id: str(supplied_names.get(label_id, supplied_names.get(str(label_id), "")) or "")
                    for label_id in organ_counts
                }
                if organ_type == "pancreatic":
                    from .pancreatic_oar import PANCREATIC_NNUNET_LABELS
                    for label_id in organ_counts:
                        if not organ_names[label_id]:
                            entry = PANCREATIC_NNUNET_LABELS.get(label_id)
                            if entry and entry[1]:
                                organ_names[label_id] = entry[0]
                if not all(organ_names.values()):
                    try:
                        from .totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
                    except ImportError:
                        TOTALSEG_LABEL_MAPPING = {}
                    for ordinal, label_id in enumerate(sorted(organ_counts), start=1):
                        organ_names[label_id] = organ_names[label_id] or str(
                            TOTALSEG_LABEL_MAPPING.get(label_id, f"OAR {ordinal}")
                        )

        is_full_oar = bool(
            generated_metadata.get("oar_is_full", organ_filter is None)
            if not from_label_path
            else organ_filter is None
        )
        return ToolResult(
            success=True,
            data=oar_array,
            message=(
                f"OAR segmentation completed. {len(organ_counts)} organs segmented."
                if is_full_oar
                else (
                    "Focused OAR segmentation completed. Retained requested structures: "
                    + ", ".join(organ_filter or [])
                    + "."
                )
            ),
            metadata={
                # For an uploaded mask, ``image`` is the CT reference used for
                # physical alignment, not the OAR mask itself. Returning the
                # CT here made downstream mesh reconstruction and snapshot
                # hydration receive the wrong SimpleITK image even though the
                # derived NumPy labels looked correct. Keep the aligned label
                # image as the canonical mask object.
                "oar_mask": (
                    label_img
                    if from_label_path and label_img is not None
                    else generated_metadata.get("oar_mask", label_path)
                ),
                "oar_array": oar_array,
                "organ_counts": organ_counts,
                "organ_names": organ_names,
                "manual_label_orientation": "LPI" if label_img is not None else None,
                "label_grid_orientation": "LPI",
                "oar_source": "uploaded_unknown" if from_label_path else (
                    generated_metadata.get("oar_source") or (
                        "nnunet_pancreatic" if organ_type == "pancreatic" else "totalsegmentator"
                    )
                ),
                "oar_mask_provenance": "uploaded_unknown" if from_label_path else "model",
                "oar_is_full": is_full_oar,
                "oar_scope": "full" if is_full_oar else "focused",
                "requested_organs": list(organ_filter or []),
            },
        )


__all__ = [
    "BaseTool",
    "ToolResult",
    "TotalSegmentatorOARTool",
    "PancreaticOARTool",
    "OARSegmentationTool",
    "get_tool",
    "list_tools",
]
