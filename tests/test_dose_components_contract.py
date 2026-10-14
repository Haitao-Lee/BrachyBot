"""Source-set, units, scientific reuse and complete-target negative controls."""
import numpy as np
import pytest
import SimpleITK as sitk
from web.dose_components import dose_component, total_component, evaluate_total
from web.timepoint_resources import dependency_fingerprints, fingerprint, observation_content
from web.routes.planning_routes import _dose_display_context
from agent_runtime.core import AgentMemory
from types import SimpleNamespace


def inputs():
    image = sitk.GetImageFromArray(np.zeros((5, 6, 7), np.int16))
    leaves = {key: fingerprint(key) for key in ("image", "observation", "source", "model", "planned_sources", "ctv", "oar", "constraints", "guide", "needles", "guide_profile")}
    return image, dependency_fingerprints(leaves)


def test_components_sum_once_and_use_total_for_evaluation():
    image, resources = inputs()
    old = dose_component("implanted", np.full((5, 6, 7), .5), image,
        units="normalized_model", scale=120., resources=resources)
    new = dose_component("planned", np.full((5, 6, 7), 30.), image,
        units="physical_gy", scale=120., resources=resources)
    total = total_component(old, new, resources)
    assert np.all(total["dose_distribution_physical_gy"] == 90)
    result = evaluate_total({"total": total}, np.ones((5, 6, 7), np.uint8), np.zeros((5, 6, 7), np.uint8),
        image, {"prescription_gy": 120.})
    assert result["source_set"] == "total" and result["metrics"]["CTV"]["D90"] == 90.


def test_total_rejects_different_grid_and_changed_component():
    image, resources = inputs()
    old = dose_component("implanted", np.ones((5, 6, 7)), image, units="physical_gy", scale=190.8, resources=resources)
    new = dose_component("planned", np.ones((5, 6, 7)), image, units="physical_gy", scale=190.8, resources=resources)
    new["dose_distribution_physical_gy"][0, 0, 0] = 100
    with pytest.raises(ValueError, match="content changed"):
        total_component(old, new, resources)


def test_review_notes_do_not_trigger_numeric_recomputation_but_exclusion_does():
    first = {"image_ref": {"image_sha256": "a" * 64}, "revision_id": "old", "coverage_status": "partial",
        "observations": [{"observation_id": "one", "center_lps_mm": [1, 2, 3], "axis_lps": [0, 1, 0], "dimensions": {}, "review_status": "review_needed"}]}
    second = {**first, "revision_id": "reviewed", "coverage_status": "complete", "observations": [{**first["observations"][0], "review_status": "accepted", "review_evidence": "Human checked"}]}
    assert fingerprint(observation_content(first)) == fingerprint(observation_content(second))
    second["observations"][0]["review_status"] = "rejected"
    assert fingerprint(observation_content(first)) != fingerprint(observation_content(second))


def test_physical_gy_is_converted_once_at_legacy_viewer_boundary():
    memory = AgentMemory("a" * 32)
    memory.store("dose_distribution_gy", np.full((5, 6, 7), 190.8, np.float32))
    memory.store("dose_unit_metadata", {"dose_distribution_gy": "physical_gy"})
    memory.store("dose_scale_gy", 190.8)
    context = _dose_display_context(SimpleNamespace(memory=memory))
    assert np.allclose(context["array"], 1)
