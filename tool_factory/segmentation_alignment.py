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
