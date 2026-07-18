"""Regression tests for OAR-to-CT physical-grid alignment."""

from pathlib import Path
import sys

import numpy as np
import pytest

sitk = pytest.importorskip("SimpleITK")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tool_factory.OAR_seg.totalsegmentator_oar import _align_segmentation_to_reference


def test_totalsegmentator_labels_are_resampled_by_physical_coordinates(tmp_path):
    reference = sitk.Image([6, 5, 4], sitk.sitkInt16)
    reference.SetSpacing((2.0, 3.0, 4.0))
    reference.SetOrigin((10.0, 20.0, 30.0))

    # Place label 26 at physical point (14, 23, 34), which is index
    # (2, 1, 1) in the CT. The exported segmentation uses a shifted origin,
    # so its corresponding label voxel is (3, 2, 2). A raw array transpose
    # would miss this correspondence; affine-aware resampling must recover it.
    exported = sitk.Image([6, 5, 4], sitk.sitkUInt16)
    exported.SetSpacing(reference.GetSpacing())
    exported.SetOrigin((8.0, 17.0, 26.0))
    exported.SetDirection(reference.GetDirection())
    exported_array = np.zeros((4, 5, 6), dtype=np.uint16)
    exported_array[2, 2, 3] = 26
    exported = sitk.GetImageFromArray(exported_array)
    exported.SetSpacing(reference.GetSpacing())
    exported.SetOrigin((8.0, 17.0, 26.0))
    exported.SetDirection(reference.GetDirection())
    path = tmp_path / "totalseg_output.nii.gz"
    sitk.WriteImage(exported, str(path))

    aligned = _align_segmentation_to_reference(str(path), reference)

    assert aligned.shape == (4, 5, 6)
    assert int(aligned[1, 1, 2]) == 26
    assert int(np.sum(aligned == 26)) == 1

