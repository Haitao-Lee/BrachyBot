"""Physical-grid alignment helpers shared by uploaded segmentation tools.

NumPy arrays do not carry origin, spacing, direction, or axis semantics.  A
mask that merely has the same array shape as a CT can still be mirrored or
translated in the viewer.  Keep the alignment in SimpleITK until the final
``GetArrayFromImage`` conversion so every downstream consumer receives the
same LPI, CT-referenced (Z, Y, X) grid.
"""

from __future__ import annotations

import numpy as np
import SimpleITK as sitk


def normalize_positive_label_value(value, *, name: str = "target_value") -> int:
    """Return a positive, discrete label id from an API or UI value.

    Medical label maps are categorical.  Silently truncating ``2.7`` to
    label 2 (or accepting a boolean as label 1) can select the wrong contour,
    so callers share this strict conversion at the mask-ingestion boundary.
    """

    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a positive integer label value.")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer label value.") from exc
    if not np.isfinite(numeric) or not numeric.is_integer() or numeric <= 0:
        raise ValueError(f"{name} must be a positive integer label value.")
    return int(numeric)


def select_label_as_binary(
    label_array: np.ndarray,
    target_value=1,
) -> tuple[np.ndarray, dict]:
    """Select one categorical label and normalize it to the CTV 0/1 contract.

    A manual CTV file may be a multi-label export containing a body/organ
    contour alongside the actual tumour.  Downstream planning deliberately
    reserves CTV value 1 for target and values 2/3 for embedded obstacles, so
    forwarding the source labels unchanged is unsafe.  This helper records
    the source label id for provenance while returning only a binary target.

    If a mask has exactly one positive source label, that sole label is used
    even when a conventional default of 1 was requested (common examples are
    binary masks encoded as 255).  A missing label in a genuinely multi-label
    file is rejected rather than merging foreground classes.
    """

    values = np.asarray(label_array)
    if values.ndim != 3:
        raise ValueError(
            f"CTV label array must be three-dimensional; received shape {values.shape}."
        )
    if not np.issubdtype(values.dtype, np.number):
        raise ValueError("CTV label array must contain numeric discrete labels.")
    if np.issubdtype(values.dtype, np.floating):
        if not np.all(np.isfinite(values)) or not np.all(values == np.rint(values)):
            raise ValueError("CTV label array contains non-finite or non-integer labels.")

    requested = normalize_positive_label_value(target_value)
    source_values, source_counts = np.unique(values, return_counts=True)
    integer_values = [int(item) for item in source_values]
    positive_labels = [item for item in integer_values if item > 0]
    selected = requested
    if requested not in positive_labels:
        if len(positive_labels) == 1:
            selected = positive_labels[0]
        elif positive_labels:
            available = ", ".join(str(item) for item in positive_labels)
            raise ValueError(
                f"Requested CTV target label {requested} is absent; "
                f"available positive labels are {available}."
            )

    binary = np.equal(values, selected).astype(np.uint8, copy=False)
    positive_counts = {
        int(label): int(count)
        for label, count in zip(integer_values, source_counts.tolist())
        if int(label) > 0
    }
    return binary, {
        "requested_target_value": requested,
        "selected_target_value": int(selected),
        "source_labels": positive_labels,
        "source_label_counts": positive_counts,
        "selected_voxel_count": int(np.count_nonzero(binary)),
    }


def align_label_image_to_reference(
    label_image: sitk.Image,
    reference_image: sitk.Image,
    orientation: str = "LPI",
) -> sitk.Image:
    """Orient and resample an in-memory label onto a CT physical grid.

    This helper is intentionally image-based rather than array-based.  Model
    predictors often return a NumPy array whose axis order is correct only for
    the raw input image; copying that array onto an already oriented CT would
    silently mirror or translate the contour.
    """

    reference = sitk.DICOMOrient(reference_image, orientation)
    label = sitk.DICOMOrient(label_image, orientation)
    return sitk.Resample(
        label,
        reference,
        sitk.Transform(),
        sitk.sitkNearestNeighbor,
        0,
        label.GetPixelID(),
    )


def align_label_to_reference(
    label_path: str,
    reference_image: sitk.Image,
    orientation: str = "LPI",
) -> sitk.Image:
    """Read and resample a label image onto the reference CT physical grid."""

    return align_label_image_to_reference(
        sitk.ReadImage(label_path), reference_image, orientation
    )


def align_label_array_to_reference(
    label_array: np.ndarray,
    reference_image: sitk.Image,
    orientation: str = "LPI",
    dtype=None,
) -> sitk.Image:
    """Convert a model NumPy mask and align it to a physical CT grid.

    Predictor outputs do not carry image metadata.  Equal-sized outputs can
    inherit the raw input grid directly; for a different shape, infer the
    source spacing from the reference physical extent rather than calling
    ``CopyInformation`` (which rejects different image sizes).
    """
    values = np.asarray(label_array)
    if dtype is not None:
        values = values.astype(dtype, copy=False)
    label = sitk.GetImageFromArray(values)
    reference_size = reference_image.GetSize()
    source_size = label.GetSize()
    if source_size == reference_size:
        label.CopyInformation(reference_image)
    else:
        reference_spacing = reference_image.GetSpacing()
        source_spacing = tuple(
            float(reference_spacing[index])
            * max(int(reference_size[index]) - 1, 1)
            / max(int(source_size[index]) - 1, 1)
            for index in range(3)
        )
        label.SetSpacing(source_spacing)
        label.SetOrigin(reference_image.GetOrigin())
        label.SetDirection(reference_image.GetDirection())
    return align_label_image_to_reference(label, reference_image, orientation)
