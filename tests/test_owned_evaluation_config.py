"""Actual total-dose QA and reports on owned Rx; no model substitutions.

Synthetic physical fields exercise addition, DVH and scoring on an existing
bundle. They do not establish CNN inference accuracy or clinical readiness.
"""
import copy
from types import SimpleNamespace

import numpy as np
import pytest
import SimpleITK as sitk

from agent_runtime.core import AgentMemory
from tool_factory.report_context import build_report_context, build_prescription_rationale
from tool_factory.report_facts import resolve_report_facts
from web.dose_components import component_bundle, dose_component, evaluate_total, total_evaluation_updates
from web.planning_config import current_evaluation_config, evaluation_inputs_current
from web.routes.dose_component_routes import dose_view_packet
from web.timepoint_resources import capture_resources, fingerprint


@pytest.fixture
def existing_bundle():
    image = sitk.GetImageFromArray(np.zeros((3, 4, 5), np.int16))
    image.SetSpacing((1., 1.5, 2.))
    memory = AgentMemory("a" * 32)
    plan = {"in_lowest_dose_gy": 90., "in_lowest_energy": 90.,
        "dose_value_unit": "gy", "tumor_type": "prostate", "DVH_rate": .9,
        "dose_scale_gy": 190.8, "seed_info": {"length": 4.5, "radius": .4, "activity_mbq": 10.},
        "dl_params": {"dose_model_path": "saved-model.pth"},
        "oar_constraints": {"bladder": {"max_dose": 100.}}}
    for key, value in {
        "ct_image": image, "ctv_binary_array": np.ones((3, 4, 5), np.uint8),
        "oar_array": np.ones((3, 4, 5), np.uint8), "organ_names": {1: "bladder"},
        "plan_config": copy.deepcopy(plan), "total_seeds": 2,
        "timepoint_planning_config": {"in_lowest_dose_gy": 90., "dose_value_unit": "gy", "tumor_type": "prostate"},
    }.items():
        memory.store(key, value)
    resources = capture_resources(memory.retrieve, image)
    fixed = dose_component("implanted", np.full((3, 4, 5), 60., np.float32), image,
        units="physical_gy", scale=190.8, resources=resources,
        sources=[{"id": "observed", "position": [0., 0., 0.], "direction": [0., 0., 1.]}])
    planned = dose_component("planned", np.full((3, 4, 5), 30., np.float32), image,
        units="physical_gy", scale=190.8, resources=resources,
        sources=[{"id": "future", "position": [1., 0., 0.], "direction": [0., 0., 1.]}])
    bundle = component_bundle(fixed, planned, resources)
    memory.store("dose_components", bundle)
    memory.store("timepoint_resource_state", {"fingerprints": resources})
    original = fingerprint(bundle)
    updates, reused = total_evaluation_updates(bundle, memory.retrieve, image,
        current_evaluation_config(memory.retrieve), resources, 190.8)
    assert not reused and updates["dose_metrics"]["v100"] == 1.
    for key, value in updates.items():
        memory.store(key, value)
    return SimpleNamespace(image=image, memory=memory, plan=plan, bundle=bundle,
        resources=resources, bundle_fingerprint=original)


def _current_rx(case, rx=120.):
    case.memory.store("timepoint_planning_config", {
        "in_lowest_dose_gy": rx, "in_lowest_energy": rx, "dose_value_unit": "gy",
        "tumor_type": "prostate", "seed_info": {"length": 99., "radius": 9., "activity_mbq": 999.},
        "dose_scale_gy": 999., "dl_params": {"dose_model_path": "must-not-replace-confirmed.pth"},
    })
    return current_evaluation_config(case.memory.retrieve)


def test_actual_total_qa_and_reports_use_new_rx_without_changing_plan_or_dose(existing_bundle):
    case = existing_bundle
    old_score = case.memory.retrieve("dose_metrics")["plan_score"]
    config = _current_rx(case)
    resources = capture_resources(case.memory.retrieve, case.image)
    for name in ("implanted_dose", "planned_dose", "total_dose"):
        assert resources[name] == case.resources[name]
    assert resources["metrics"] != case.resources["metrics"]
    assert resources["report"] != case.resources["report"]
    updates, reused = total_evaluation_updates(case.bundle, case.memory.retrieve, case.image,
        config, resources, 190.8)
    assert not reused
    metrics = updates["dose_metrics"]
    assert metrics["source_set"] == "total"
    assert metrics["prescription_gy"] == 120. and metrics["v100"] == 0.
    assert metrics["d90"] == 90. and metrics["plan_score"] < old_score
    assert updates["current_dose_evaluation_config"] == config
    assert updates["current_dose_evaluation_config"] is not config
    for key, value in updates.items():
        case.memory.store(key, value)
    case.memory.store("timepoint_resource_state", {"fingerprints": resources})
    facts = resolve_report_facts(case.memory)
    rationale = build_report_context(case.memory)["prescription_rationale"]
    assert facts["prescription_gy"] == rationale["prescription_gy"] == 120.
    assert facts["prescription_source"].startswith("timepoint_planning_config.")
    assert "timepoint_planning_config" in rationale["prescription_source"]
    assert facts["dose"]["plan_score"] == metrics["plan_score"]
    assert facts["seed_activity_mbq"] == 10. and facts["total_activity_mbq"] == 20.
    assert config["dose_scale_gy"] == 190.8
    assert config["seed_info"] == case.plan["seed_info"]
    assert config["dl_params"] == case.plan["dl_params"]
    assert case.memory.retrieve("plan_config") == case.plan
    assert fingerprint(case.bundle) == case.bundle_fingerprint
    assert evaluation_inputs_current(case.memory.retrieve)
    second, reused = total_evaluation_updates(case.bundle, case.memory.retrieve, case.image,
        config, resources, 190.8)
    assert reused and second["dose_metrics"] == metrics


def test_explicit_historical_reports_keep_saved_evaluation_basis(existing_bundle):
    case = existing_bundle
    config = _current_rx(case)
    # The saved QA was produced at 90 Gy even though current Input now says 120.
    facts = resolve_report_facts(case.memory, evaluation_basis="historical")
    rationale = build_prescription_rationale(case.memory, evaluation_basis="historical")
    assert facts["prescription_gy"] == rationale["prescription_gy"] == 90.
    assert facts["dose"]["prescription_gy"] == 90.
    assert facts["evaluation_basis"] == rationale["evaluation_basis"] == "historical"
    historical = evaluate_total(case.bundle, case.memory.retrieve("ctv_binary_array"),
        case.memory.retrieve("oar_array"), case.image, case.plan, organ_names={1: "bladder"})
    current = evaluate_total(case.bundle, case.memory.retrieve("ctv_binary_array"),
        case.memory.retrieve("oar_array"), case.image, config, organ_names={1: "bladder"})
    assert historical["metrics"]["CTV"]["V100"] == 1.
    assert current["metrics"]["CTV"]["V100"] == 0.
    assert case.memory.retrieve("plan_config") == case.plan


def test_saved_reevaluation_basis_survives_future_input_change(existing_bundle):
    case = existing_bundle
    config = _current_rx(case)
    resources = capture_resources(case.memory.retrieve, case.image)
    updates, _ = total_evaluation_updates(case.bundle, case.memory.retrieve, case.image,
        config, resources, 190.8)
    # Historical report memory contains the reevaluated plan's saved QA/basis.
    for key, value in updates.items():
        case.memory.store(key, value)
    _current_rx(case, 150.)
    facts = resolve_report_facts(case.memory, evaluation_basis="historical")
    rationale = build_report_context(case.memory, evaluation_basis="historical")["prescription_rationale"]
    assert facts["prescription_gy"] == rationale["prescription_gy"] == 120.
    assert facts["dose"]["prescription_gy"] == 120.
    assert facts["prescription_source"].startswith("current_dose_evaluation_config.")
    current = resolve_report_facts(case.memory)
    assert current["prescription_gy"] == 150. and current["dose"] == {}
    assert case.memory.retrieve("plan_config")["in_lowest_dose_gy"] == 90.
    assert not evaluation_inputs_current(case.memory.retrieve)


def test_component_dvh_uses_current_rx_without_exposing_a_component_plan_score(existing_bundle):
    case = existing_bundle
    _current_rx(case)
    agent = SimpleNamespace(memory=case.memory, _workspace_timepoint_context=SimpleNamespace(
        session_id="a" * 32, target=SimpleNamespace(timepoint_id="b" * 32, stage="intraoperative")))
    for source_set, d90 in (("implanted", 60.), ("planned", 30.)):
        packet, dose = dose_view_packet(agent, source_set)
        assert packet["available"] and not packet["stale"]
        assert packet["metrics"]["v100"] == 0. and packet["metrics"]["d90"] == d90
        assert packet["metrics"]["component_only"] is True
        assert "plan_score" not in packet["metrics"]
        assert np.all(dose == d90)
    assert fingerprint(case.bundle) == case.bundle_fingerprint


def test_current_oar_limits_reassess_existing_total_without_changing_source_dose(existing_bundle):
    case = existing_bundle
    owned = copy.deepcopy(case.memory.retrieve("timepoint_planning_config"))
    owned["oar_constraints"] = {"bladder": {"max_dose": 80.}}
    case.memory.store("timepoint_planning_config", owned)
    result = evaluate_total(case.bundle, case.memory.retrieve("ctv_binary_array"),
        case.memory.retrieve("oar_array"), case.image,
        current_evaluation_config(case.memory.retrieve), organ_names={1: "bladder"})
    violation = next(row for row in result["oar_violations"] if row["structure"] == "bladder")
    assert violation["actual"] == 90. and violation["constraint"] == 80.
    assert case.memory.retrieve("plan_config")["oar_constraints"]["bladder"]["max_dose"] == 100.
    assert fingerprint(case.bundle) == case.bundle_fingerprint


def test_legacy_owned_rx_reports_its_actual_input_origin(existing_bundle):
    case = existing_bundle
    case.memory.store("timepoint_planning_config", {"in_lowest_energy": 1., "dose_value_unit": "rx"})
    facts = resolve_report_facts(case.memory)
    rationale = build_prescription_rationale(case.memory)
    assert facts["prescription_gy"] == rationale["prescription_gy"] == 120.
    assert facts["prescription_source"] == "timepoint_planning_config.in_lowest_energy"
    assert facts["dose"] == {}
    assert case.memory.retrieve("plan_config") == case.plan


@pytest.mark.parametrize("report", [resolve_report_facts, build_prescription_rationale, build_report_context])
def test_unknown_report_basis_fails_closed(existing_bundle, report):
    with pytest.raises(ValueError, match="current or historical"):
        report(existing_bundle.memory, evaluation_basis="unrecognized")
