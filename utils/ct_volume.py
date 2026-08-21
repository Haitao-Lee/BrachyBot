"""CT volume normalization shared by upload, hydration, and planning paths."""

from __future__ import annotations

from typing import Any, Dict, Tuple

import SimpleITK as sitk


def normalize_ct_image(
    image: sitk.Image,
    *,
    frame_index: int = 0,
) -> Tuple[sitk.Image, Dict[str, Any]]:
    """Return a scalar 3-D CT frame and its source-dimension metadata.

    BrachyBot's viewers and planning algorithms operate on one 3-D CT volume.
    NIfTI files can still contain a fourth dimension, commonly because a scan
    was exported as a time series or because a scalar CT was wrapped in a
    singleton frame dimension.  SimpleITK's DICOMOrient filter does not accept
    a float32 4-D scalar image, so extract one deterministic frame before any
    orientation or label-alignment operation.

    The uploaded file is never modified.  For a true 4-D source, frame zero is
    selected deliberately and the choice is returned in metadata so callers
    can expose it or persist it with the session.  Other dimensions are
    rejected with an actionable error instead of falling through to a less
    informative SimpleITK exception.
    """
    if image is None:
        raise ValueError("CT image is empty")

    # Keep lightweight test doubles and legacy adapters pass-through. Real
    # upload paths always provide a SimpleITK image with GetDimension().
    if not hasattr(image, "GetDimension"):
        return image, {}

    dimension = int(image.GetDimension())
    source_size = tuple(int(value) for value in image.GetSize())

    # SimpleITK can represent a multi-channel volume as a 3-D vector image.
    # It still reports dimension 3, but DICOMOrient cannot process every
    # vector pixel type. CT input is scalar by definition, so keep the first
    # component as the deterministic display/planning frame and record the
    # reduction for diagnostics. This also covers loaders that expose a
    # 4-D-looking vector volume after frame extraction.
    try:
        component_count = int(image.GetNumberOfComponentsPerPixel())
    except (AttributeError, TypeError, ValueError):
        component_count = 1

    def scalar_frame(value: sitk.Image) -> Tuple[sitk.Image, int]:
        try:
            components = int(value.GetNumberOfComponentsPerPixel())
        except (AttributeError, TypeError, ValueError):
            components = 1
        if components <= 1:
            return value, 1
        return sitk.VectorIndexSelectionCast(value, 0), components

    if dimension == 3:
        if component_count > 1:
            frame, reduced_components = scalar_frame(image)
            metadata = {
                "source_dimension": 3,
                "source_size": list(source_size),
                "frame_count": 1,
                "selected_frame": None,
                "reduced_to_3d": True,
                "source_components": reduced_components,
            }
            return frame, metadata
        return image, {
            "source_dimension": 3,
            "source_size": list(source_size),
            "frame_count": 1,
            "selected_frame": None,
            "reduced_to_3d": False,
        }

    if dimension != 4:
        raise ValueError(
            "CT viewer and planning currently support 3-D images or 4-D "
            f"images reduced to one 3-D frame; received {dimension}-D data"
        )

    frame_count = int(source_size[3])
    if frame_count < 1:
        raise ValueError("4-D CT has no frames")
    if not 0 <= int(frame_index) < frame_count:
        raise ValueError(
            f"CT frame index {frame_index} is outside the available range "
            f"0..{frame_count - 1}"
        )

    # A zero in the extracted dimension removes that dimension and preserves
    # the source voxel type, spacing, origin, and direction for the 3-D frame.
    extract_size = [source_size[0], source_size[1], source_size[2], 0]
    extract_index = [0, 0, 0, int(frame_index)]
    frame = sitk.Extract(image, extract_size, extract_index)
    frame, reduced_components = scalar_frame(frame)
    metadata = {
        "source_dimension": 4,
        "source_size": list(source_size),
        "frame_count": frame_count,
        "selected_frame": int(frame_index),
        "reduced_to_3d": True,
    }
    if reduced_components > 1:
        metadata["source_components"] = reduced_components
    return frame, metadata
