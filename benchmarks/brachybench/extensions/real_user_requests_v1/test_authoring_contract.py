"""Structure/lineage/fail-closed self-tests, NOT benchmark/SUT success tests."""
from copy import deepcopy
import json
from pathlib import Path
from .catalog import PACK
from .quality_gate import validate
from .build import outputs
import pytest

def test_catalog_structural_contract():
    result = validate(PACK)
    assert result["structural_ok"], result["errors"]
    assert (result["families"], result["scenarios"], result["negative_control_specs"]) == (84, 210, 630)
    assert result["formal_ready"] is False and result["formal_results"] == 0

@pytest.mark.parametrize("family", PACK["families"], ids=lambda f:f["id"])
def test_every_family_has_real_contextual_difference(family):
    cases = family["cases"]
    # Not an expert semantic test: simple anti-padding and explicit expectation check.
    assert len({json.dumps(x["steps"],sort_keys=True,ensure_ascii=False) for x in cases}) == len(cases)
    assert len({json.dumps(x["acceptance"],sort_keys=True,ensure_ascii=False) for x in cases}) == len(cases)
    assert all(x["split_group"] == family["id"] for x in cases)

@pytest.mark.parametrize("case", [c for f in PACK["families"] for c in f["cases"]], ids=lambda c:c["id"])
def test_each_case_has_private_verifiable_contract_and_fault_controls(case):
    assert case["initial_state"]["synthetic"] is True
    assert len(case["acceptance"]) >= 2 and len(case["negative_controls"]) == 3
    assert len(case["independent_evidence"]) >= 3
    assert case["formal_eligible"] is False
    assert case["review"]["semantic_review"] == "pending_independent_review"

@pytest.mark.parametrize("fault", ["empty_turn", "missing_outcome", "negative_padding", "missing_observer", "fake_formal", "fake_review", "duplicate_id", "duplicate_protocol", "wrong_lineage", "nan_state", "count_drift"])
def test_incomplete_or_misleading_additions_rejected(fault):
    pack = deepcopy(PACK)
    case = pack["families"][0]["cases"][0]
    if fault == "empty_turn": case["steps"][-1]["text"] = ""
    elif fault == "missing_outcome": case["acceptance"] = [{"kind":"effects","statement":"No changes."}]
    elif fault == "negative_padding": case["negative_controls"] = ["bad", "bad", "bad"]
    elif fault == "missing_observer": case["independent_evidence"] = []
    elif fault == "fake_formal": case["formal_eligible"] = True
    elif fault == "fake_review": case["review"]["semantic_review"] = "human_reviewed"
    elif fault == "duplicate_id": pack["families"][0]["cases"][1]["id"] = case["id"]
    elif fault == "duplicate_protocol": pack["families"][0]["cases"][1]["steps"] = deepcopy(case["steps"])
    elif fault == "wrong_lineage": case["split_group"] = "independent-made-up-group"
    elif fault == "nan_state": case["initial_state"]["bad_value"] = float("nan")
    elif fault == "count_drift": pack["scenario_count"] += 1
    result = validate(pack)
    assert result["structural_ok"] is False
    assert result["formal_ready"] is False

def test_compilation_is_deterministic_and_never_a_score():
    assert outputs() == outputs()
    compiled = json.loads(outputs()["candidate_pack.json"])
    quality = json.loads(outputs()["authoring_quality.json"])
    assert compiled["formal_results"] == 0
    assert quality["semantic_validity"] == "NOT_ESTABLISHED"
    assert quality["live_runs"] == 0
