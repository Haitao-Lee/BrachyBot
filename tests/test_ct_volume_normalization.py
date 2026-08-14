"""Regression tests for CT dimensionality normalization."""

import numpy as np
import pytest

sitk = pytest.importorskip("SimpleITK")

from utils.ct_volume import normalize_ct_image


def test_float32_four_dimensional_ct_is_reduced_before_orientation():
    source = sitk.GetImageFromArray(
        np.arange(2 * 3 * 4 * 2, dtype=np.float32).reshape(2, 3, 4, 2),
        isVector=False,
    )
    source.SetSpacing((0.7, 0.8, 5.0, 1.0))

    frame, metadata = normalize_ct_image(source)

    assert source.GetDimension() == 4
    assert frame.GetDimension() == 3
    assert frame.GetSize() == source.GetSize()[:3]
    assert frame.GetPixelIDTypeAsString() == "32-bit float"
    assert metadata == {
        "source_dimension": 4,
        "source_size": list(source.GetSize()),
        "frame_count": source.GetSize()[3],
        "selected_frame": 0,
        "reduced_to_3d": True,
    }

    # This is the operation that failed for the uploaded prostate file.
    oriented = sitk.DICOMOrient(frame, "LPI")
    assert oriented.GetDimension() == 3


def test_three_dimensional_ct_is_preserved_without_copying():
    source = sitk.GetImageFromArray(np.zeros((3, 4, 5), dtype=np.int16))

    frame, metadata = normalize_ct_image(source)

    assert frame is source
    assert metadata["source_dimension"] == 3
    assert metadata["reduced_to_3d"] is False
    assert metadata["selected_frame"] is None


def test_unsupported_dimensions_fail_with_actionable_error():
    source = sitk.GetImageFromArray(
        np.zeros((2, 2, 2, 2, 2), dtype=np.float32),
        isVector=False,
    )

    with pytest.raises(ValueError, match="support 3-D images or 4-D"):
        normalize_ct_image(source)
