"""Regression tests for legacy label-volume shape handling."""

from pathlib import Path
import sys

import numpy as np
import pytest

sitk = pytest.importorskip("SimpleITK")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web.routes.viewer_routes import _resample_legacy_label_array
from tool_factory.segmentation_alignment import align_label_array_to_reference


def test_legacy_label_array_resamples_to_reference_without_copy_information():
    reference = sitk.Image([6, 5, 4], sitk.sitkInt16)
    reference.SetSpacing((2.0, 3.0, 4.0))
    reference.SetOrigin((10.0, 20.0, 30.0))
    reference.SetDirection((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))

    legacy = np.zeros((2, 3, 4), dtype=np.uint8)
    legacy[1, 1, 2] = 7

    aligned = _resample_legacy_label_array(legacy, reference, (4, 5, 6))

    assert aligned.shape == (4, 5, 6)
    assert int(aligned.max()) == 7
    assert int(np.count_nonzero(aligned)) > 0


def test_legacy_label_array_has_safe_shape_fallback_without_reference():
    legacy = np.ones((2, 3, 4), dtype=np.uint8)

    aligned = _resample_legacy_label_array(legacy, None, (3, 4, 5))

    assert aligned.shape == (3, 4, 5)
    assert np.all(aligned[:2, :3, :4] == 1)
    assert np.all(aligned[2:, :, :] == 0)


def test_model_array_alignment_accepts_a_different_shape():
    reference = sitk.Image([6, 5, 4], sitk.sitkInt16)
    reference.SetSpacing((2.0, 3.0, 4.0))
    reference.SetOrigin((10.0, 20.0, 30.0))

    model_array = np.zeros((2, 3, 4), dtype=np.uint16)
    model_array[1, 1, 2] = 9

    aligned = align_label_array_to_reference(model_array, reference, dtype=np.uint16)

    assert aligned.GetSize() == reference.GetSize()
    assert int(sitk.GetArrayFromImage(aligned).max()) == 9
