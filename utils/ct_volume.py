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

    if dimension == 3:
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
    return frame, {
        "source_dimension": 4,
        "source_size": list(source_size),
        "frame_count": frame_count,
        "selected_frame": int(frame_index),
        "reduced_to_3d": True,
    }
