import copy
import pytest
from brachycohort.core import Blocked
from brachycohort.profiles import validate_profile, applicable, prompt


@pytest.mark.parametrize("field", ["status", "clinical_reviewer", "physics_reviewer", "approved_at", "evidence", "source", "engine", "target_policy"])
def test_missing_approval_never_executable(approved_profile, field):
    approved_profile[field] = None
    with pytest.raises(Blocked):
        validate_profile(approved_profile)


@pytest.mark.parametrize("field,value", [("prescription_gy", 0), ("prescription_gy", float("nan")),
    ("upper_dose_gy", 1), ("coverage_fraction", 90), ("coverage_fraction", 0),
    ("max_iterations", True), ("max_iterations", -1), ("mode", "guess")])
def test_units_and_settings(approved_profile, field, value):
    approved_profile["settings"][field] = value
    with pytest.raises(Blocked):
        validate_profile(approved_profile)


def test_approved_case_and_profile_binding(approved_profile):
    row = {"dataset": "synthetic", "target_semantics": "research tumor", "clinical_eligibility": "NOT_ESTABLISHED", "planning_profile_id": "test-only"}
    with pytest.raises(Blocked, match="CASE_APPROVAL_UNRESOLVED"):
        applicable(row, approved_profile)
    row["clinical_eligibility"] = "APPROVED_RESEARCH"
    assert applicable(row, approved_profile)
    message = prompt(row, approved_profile)
    assert "42 Gy" in message and "80%" in message and "120" not in message
    assert "do not run replacement tumor segmentation" in message
    row["dataset"] = "other"
    with pytest.raises(Blocked, match="PROFILE_CASE_MISMATCH"):
        applicable(row, approved_profile)
