import numpy as np
import pytest
from brachycohort.preflight import preflight


@pytest.mark.parametrize("values", [[1], [2], [28], [1, 2]])
def test_source_target_mapping_never_organ_guess(storage, make_pair, values):
    labels = np.zeros((5, 6, 7))
    for i, v in enumerate([1, 2, 3, 17, 28]):
        labels[i, 2, 3] = v
    row = make_pair(labels, values)
    result = preflight(row, storage, {})
    assert result["preflight_status"] == "PASS"
    assert result["target_voxels"] == len(values)
    assert result["derivative_recipe"]["target_values"] == values
    assert result["clinical_eligibility"] == "NOT_ESTABLISHED"


def test_empty_is_not_success(storage, make_pair):
    row = make_pair(np.zeros((3, 3, 3)))
    result = preflight(row, storage, {})
    assert result["reasons"] == ["EMPTY_SELECTED_TARGET"]
    row["metadata_positive"] = True
    assert preflight(row, storage, {})["reasons"] == ["METADATA_PAYLOAD_CONFLICT"]


@pytest.mark.parametrize("modality", ["MRI", "PT", "unknown", None])
def test_nonct_blocked(storage, make_pair, modality):
    row = make_pair(np.ones((3, 3, 3)), [1])
    row["image_modality"] = modality
    assert preflight(row, storage, {})["reasons"] == ["NON_CT_OR_NON_TUMOR"]


@pytest.mark.parametrize("value", [0.5, 1.01, float("nan"), float("inf"), -1])
def test_invalid_labels_never_thresholded(storage, make_pair, value):
    a = np.ones((3, 3, 3))
    a[1, 1, 1] = value
    row = make_pair(a, [1])
    assert preflight(row, storage, {})["preflight_status"] == "BLOCKED"


def test_scaling_noise_requires_declared_alphabet(storage, make_pair):
    a = np.zeros((3, 3, 3))
    a[1, 1, 1] = 1.0000002
    row = make_pair(a, [1])
    assert preflight(row, storage, {"allow_near_integer_repair": True})["reasons"] == ["ENCODING_REPAIR_ALPHABET_UNRESOLVED"]
    result = preflight(row, storage, {"allow_near_integer_repair": True, "label_alphabets": {"synthetic": [0, 1]}})
    assert result["preflight_status"] == "PASS"
    assert result["encoding_repair_max_error"] > 0


def test_unknown_units_not_assumed(storage, make_pair):
    a = np.ones((3, 3, 3))
    row = make_pair(a, [1], units="unknown")
    assert preflight(row, storage, {})["reasons"] == ["SPATIAL_UNITS_UNRESOLVED"]
    override = {"unit": "mm", "evidence": "synthetic test metadata, not a dataset approval"}
    result = preflight(row, storage, {"unit_overrides": {"synthetic": {"ct": override, "label": override}}})
    assert result["preflight_status"] == "PASS"


def test_grid_mismatch(storage, make_pair):
    row = make_pair(np.ones((3, 3, 3)), [1], mask_affine=np.eye(4))
    assert preflight(row, storage, {})["reasons"] == ["GRID_MISMATCH"]


def test_allocation_bounded_before_payload(storage, make_pair):
    row = make_pair(np.ones((3, 3, 3)), [1])
    assert preflight(row, storage, {"max_preflight_memory_bytes": 1})["reasons"] == ["PREFLIGHT_MEMORY_BUDGET"]


@pytest.mark.parametrize("values", [[], [0], [-1], [True], ["1"]])
def test_invalid_mapping_blocked(storage, make_pair, values):
    row = make_pair(np.ones((3, 3, 3)), [1])
    row["target_values"] = values
    assert preflight(row, storage, {})["reasons"] == ["TARGET_POLICY_UNRESOLVED"]
