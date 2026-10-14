"""Registered owned quality tools cannot turn missing/stale facts into QA.

Actual scoped runtime, Agent injector, gateway and registered executors are used.
Synthetic measured physical dose exercises QA contracts, not model accuracy.
"""
import copy
import os

import numpy as np
import pytest
import SimpleITK as sitk

from AgenticSys import BrachyAgent
from agent_runtime.core import AgentMemory, ToolRegistry
from agent_runtime.contracts import RunLedger, ToolCallGateway
from agent_runtime.timepoint_tools import owned_tool_arguments
from tool_factory.plan_quality.plan_quality_scorer import PlanQualityScorerTool
from tool_factory.plan_quality.oar_constraint_checker import OARConstraintCheckerTool
from tool_factory.report_generator import ReportGeneratorTool
from tool_factory.output.report_auto_fill import ReportAutoFillTool
from tool_factory.viewer_command.query_metrics import QueryMetricsTool
from web.dose_components import component_bundle, dose_component, total_evaluation_updates
from web.planning_config import current_evaluation_config
from web.planning_runs import current_planning_context
from web.timepoint_chat import ScopedChatRuntime, capture_chat_scope
from web.timepoint_resources import capture_resources
from web.workspace_store import WorkspaceStore
from web.timepoints import TimepointError


@pytest.fixture
def owned_quality(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    if os.name == "nt":
        # SQLite/file writes remain real; directory fsync is POSIX-only.
        monkeypatch.setattr(WorkspaceStore, "_fsync_directory", staticmethod(lambda path: None))
    store = WorkspaceStore(tmp_path / "runtime")
    uid = store.create_user("owned_quality", "synthetic-test-hash")["id"]
    sid = store.create_session(uid, "Synthetic quality case").id
    tid = store.create_timepoint(uid, sid, "Owned scan", expected_revision=0)["created_timepoint_id"]
    image = sitk.GetImageFromArray(np.zeros((3, 4, 5), np.int16))
    values = {
        "ct_data": sitk.GetArrayFromImage(image), "ct_spacing": (1., 1., 1.),
        "ct_origin": (0., 0., 0.), "ct_direction": tuple(image.GetDirection()),
        "ctv_binary_array": np.ones((3, 4, 5), np.uint8), "oar_array": np.ones((3, 4, 5), np.uint8),
        "organ_names": {1: "bladder"}, "tumor_type_used": "prostate",
        "plan_config": {"in_lowest_dose_gy": 90., "dose_value_unit": "gy", "tumor_type": "prostate"},
        "timepoint_planning_config": {"in_lowest_dose_gy": 120., "dose_value_unit": "gy",
            "tumor_type": "prostate", "oar_constraints": {"bladder": {"max_dose": 80.}}},
    }
    resources = capture_resources(values.get, image)
    fixed = dose_component("implanted", np.full((3, 4, 5), 60.), image,
        units="physical_gy", scale=190.8, resources=resources)
    planned = dose_component("planned", np.full((3, 4, 5), 30.), image,
        units="physical_gy", scale=190.8, resources=resources)
    bundle = component_bundle(fixed, planned, resources)
    updates, _ = total_evaluation_updates(bundle, values.get, image,
        current_evaluation_config(values.get), resources, 190.8)
    assert updates["dose_metrics"]["prescription_gy"] == 120.
    values.update(updates, dose_components=bundle, timepoint_resource_state={"fingerprints": resources})
    store.save_timepoint_results(uid, sid, tid, values, expected_state_revision=0)
    control = object.__new__(BrachyAgent)
    control.config = {"_workspace_owner_id": uid, "_workspace_session_id": sid,
        "_workspace_root": str(store.workspace_root(uid, sid))}
    control._workspace_store = store
    control._workspace_data_ready = True
    control.memory = AgentMemory(sid)
    control.memory.store("dose_metrics", {"v100": .999, "d90": 999., "plan_score": 99.})
    control.registry = ToolRegistry()
    for tool in (QueryMetricsTool(), PlanQualityScorerTool(), OARConstraintCheckerTool(), ReportGeneratorTool(), ReportAutoFillTool()):
        control.registry.register(tool)
    control.run_ledger = RunLedger()
    control.tool_gateway = ToolCallGateway(control.run_ledger)
    runtime = ScopedChatRuntime(control, capture_chat_scope(store, uid, sid, tid))
    runtime.view._active_turn_context = {"timepoint_scope": runtime.scope}
    yield runtime
    runtime.close()


def _execute(runtime, name, params=None):
    return runtime.view._execute_tool_with_memory(name, params or {})


@pytest.mark.parametrize("tool,params", [
    ("query_metrics", {"metric_type": "dose_metrics", "metrics": {"v100": 1., "d90": 999.}}),
    ("query_metrics", {"metric_type": "oar_dose_metrics"}),
    ("plan_quality_scorer", {"v100": 1., "v150": 0., "v200": 0., "d90": 999., "prescribed_dose": 90.}),
    ("oar_constraint_checker", {"oar_metrics": {"bladder": {"max_dose": 0.}}}),
    ("report_generator", {"action": "summary", "plan_data": {"metrics": {"plan_score": 100., "v100": 1.}}}),
    ("report_auto_fill", {"scope": "metrics"}),
])
def test_stale_context_never_revives_raw_or_caller_metrics(owned_quality, tool, params):
    runtime = owned_quality
    memory = runtime.view.memory
    raw = copy.deepcopy(memory.retrieve("dose_metrics"))
    memory.store("manual_artifact_status", {"dvh": "stale", "quality_check": "stale"})
    assert current_planning_context(memory)["metrics"] == {}
    result = _execute(runtime, tool, params)
    assert not result.success
    assert memory.retrieve("dose_metrics") == raw
    assert runtime.control_agent.memory.retrieve("dose_metrics")["d90"] == 999.


def test_scorer_receives_measured_total_and_current_rx_not_caller_override(owned_quality):
    runtime = owned_quality
    args = owned_tool_arguments(runtime.view, "plan_quality_scorer", {
        "prescribed_dose": 90., "organ": "pancreas", "v100": 1., "d90": 999.,
        "oar_constraints": {"bladder": {"max_dose": 999.}}})
    metrics = current_planning_context(runtime.view.memory)["metrics"]
    assert args["prescribed_dose"] == 120. and args["organ"] == "prostate"
    assert args["v100"] == metrics["v100"] == 0. and args["d90"] == 90.
    assert args["oar_constraints"]["bladder"]["max_dose"] == 80.
    result = _execute(runtime, "plan_quality_scorer", {"prescribed_dose": 90., "organ": "pancreas"})
    assert result.success, result.error
    expected = PlanQualityScorerTool().execute(**args)
    assert result.data["overall_score"] == expected.data["overall_score"]
    assert result.data["organ"] == "prostate"
    assert runtime.view.memory.retrieve("plan_config")["in_lowest_dose_gy"] == 90.


@pytest.mark.parametrize("missing", ["v100", "v150", "v200", "d90"])
def test_scorer_never_defaults_absent_measurements_to_zero(owned_quality, missing):
    runtime = owned_quality
    metrics = copy.deepcopy(runtime.view.memory.retrieve("dose_metrics"))
    metrics.pop(missing)
    runtime.view.memory.store("dose_metrics", metrics)
    runtime.view.memory.store("metrics", {})
    result = _execute(runtime, "plan_quality_scorer", {missing: 0., "prescribed_dose": 120.})
    assert not result.success
    with pytest.raises(TimepointError, match=missing):
        owned_tool_arguments(runtime.view, "plan_quality_scorer", {missing: 0., "prescribed_dose": 120.})


def test_oar_missing_constrained_measurement_cannot_pass_as_zero(owned_quality):
    runtime = owned_quality
    metrics = copy.deepcopy(runtime.view.memory.retrieve("dose_metrics"))
    metrics["oar_metrics"] = {"bladder": {"d2cc": 10.}}
    runtime.view.memory.store("dose_metrics", metrics)
    runtime.view.memory.store("metrics", {})
    result = _execute(runtime, "oar_constraint_checker", {
        "tumor_type": "prostate", "custom_constraints": {"bladder": {"max_dose": 999.}}})
    assert not result.success
    with pytest.raises(TimepointError, match="max_dose"):
        owned_tool_arguments(runtime.view, "oar_constraint_checker", {})


def test_oar_checker_uses_saved_current_limits_and_measured_zero_is_valid(owned_quality):
    runtime = owned_quality
    result = _execute(runtime, "oar_constraint_checker", {
        "tumor_type": "unknown", "custom_constraints": {"bladder": {"max_dose": 999.}}})
    assert result.success, result.error
    assert result.data["all_checked_pass"] is False
    assert any(row["limit"] == 80. and row["actual"] == 90. for row in result.data["violations"])
    metrics = copy.deepcopy(runtime.view.memory.retrieve("dose_metrics"))
    metrics["oar_metrics"] = {"bladder": {"max_dose": 0.}}
    runtime.view.memory.store("dose_metrics", metrics)
    runtime.view.memory.store("metrics", {})
    zero = _execute(runtime, "oar_constraint_checker")
    assert zero.success and zero.data["all_checked_pass"] is True


def test_report_inputs_use_current_rx_and_keep_historical_plan_config(owned_quality):
    runtime = owned_quality
    args = owned_tool_arguments(runtime.view, "report_generator", {
        "action": "summary", "plan_data": {"prescription_gy": 999.}})
    data = args["plan_data"]
    assert data["prescription_gy"] == data["prescription_rationale"]["prescription_gy"] == 120.
    assert data["plan_config"]["in_lowest_dose_gy"] == 90.
    assert data["metrics"]["source_set"] == "total"
    assert _execute(runtime, "report_generator", {"action": "summary"}).success
    runtime.view.memory.store("manual_artifact_status", {"quality_check": "stale"})
    empty = owned_tool_arguments(runtime.view, "report_generator", {"action": "full_report"})["plan_data"]
    assert empty["metrics"] == {}
    text = ReportGeneratorTool()._generate_full_report(empty)
    assert "Not observed" in text
    assert "90.00 Gy" not in text and "0/100" not in text


def test_explicit_historical_comparison_retains_saved_rx_and_metrics(owned_quality):
    runtime = owned_quality
    memory = runtime.view.memory
    snapshot = {"plan_config": {"in_lowest_dose_gy": 90.}, "dose_metrics": {"v100": 1., "d90": 90.}}
    memory.store("planning_run:historic", snapshot)
    args = owned_tool_arguments(runtime.view, "plan_comparator", {"planning_ids": ["historic"]})
    assert args["plans"][0]["plan_config"]["in_lowest_dose_gy"] == 90.
    assert args["plans"][0]["dose_metrics"]["v100"] == 1.
    assert memory.retrieve("timepoint_planning_config")["in_lowest_dose_gy"] == 120.


def test_autofill_cannot_fallback_to_stale_raw_metrics_but_patient_scope_remains_available(owned_quality):
    runtime = owned_quality
    runtime.view.memory.store("manual_artifact_status", {"quality_check": "stale"})
    assert runtime.view.memory.retrieve("dose_metrics")["d90"] == 90.
    with pytest.raises(TimepointError, match="Current total-dose quality"):
        owned_tool_arguments(runtime.view, "report_auto_fill", {"scope": "all"})
    patient = owned_tool_arguments(runtime.view, "report_auto_fill", {"scope": "patient"})
    assert patient["_agent"] is runtime.view


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), True])
def test_invalid_measurement_cannot_receive_a_quality_score(owned_quality, bad):
    runtime = owned_quality
    metrics = copy.deepcopy(runtime.view.memory.retrieve("dose_metrics"))
    metrics.update(v150=bad, V150=0.)
    runtime.view.memory.store("dose_metrics", metrics)
    runtime.view.memory.store("metrics", {})
    assert not _execute(runtime, "plan_quality_scorer").success


@pytest.mark.parametrize("tool,params", [
    ("query_metrics", {"metric_type": "dose_metrics"}),
    ("plan_quality_scorer", {}),
])
def test_changed_input_rx_without_status_alias_cannot_reuse_raw_metrics(owned_quality, tool, params):
    runtime = owned_quality
    runtime.view._workspace_resource_waiter(True)
    config = copy.deepcopy(runtime.view.memory.retrieve("timepoint_planning_config"))
    config["in_lowest_dose_gy"] = 150.
    runtime.view.memory.store("timepoint_planning_config", config)
    assert current_planning_context(runtime.view.memory)["metrics"] == {}
    assert not _execute(runtime, tool, params).success


def test_query_metrics_cannot_revive_an_explicitly_absent_canonical_alias(owned_quality):
    runtime = owned_quality
    metrics = copy.deepcopy(runtime.view.memory.retrieve("dose_metrics"))
    metrics.update(v150=None, V150=0.)
    runtime.view.memory.store("dose_metrics", metrics)
    runtime.view.memory.store("metrics", {})
    assert not _execute(runtime, "query_metrics", {"metric_type": "dose_metrics"}).success


@pytest.mark.parametrize("tool,params", [
    ("query_metrics", {"metric_type": "dose_metrics"}),
    ("plan_quality_scorer", {}),
    ("oar_constraint_checker", {}),
    ("report_generator", {"action": "summary"}),
])
def test_nonexistent_quality_is_not_replaced_with_zero_or_control_agent_facts(owned_quality, tool, params):
    runtime = owned_quality
    runtime.view._workspace_resource_waiter(True)
    for key in ("dose_metrics", "metrics", "algorithm_plan_dose_metrics"):
        runtime.view.memory.store(key, {})
    assert current_planning_context(runtime.view.memory)["metrics"] == {}
    assert not _execute(runtime, tool, params).success


def test_dicom_export_adapter_rejects_stale_source_dose_without_exporting(owned_quality):
    runtime = owned_quality
    runtime.view._workspace_resource_waiter(True)
    bundle = copy.deepcopy(runtime.view.memory.retrieve("dose_components"))
    bundle["planned"]["status"] = "stale"
    runtime.view.memory.store("dose_components", bundle)
    with pytest.raises(TimepointError, match="stale"):
        owned_tool_arguments(runtime.view, "dicom_rt_exporter", {})


@pytest.mark.parametrize("source_set", ["implanted", "planned"])
def test_component_metrics_cannot_be_presented_as_current_total_quality(owned_quality, source_set):
    runtime = owned_quality
    runtime.view._workspace_resource_waiter(True)
    metrics = copy.deepcopy(runtime.view.memory.retrieve("dose_metrics"))
    metrics["source_set"] = source_set
    runtime.view.memory.store("dose_metrics", metrics)
    runtime.view.memory.store("metrics", {})
    with pytest.raises(TimepointError):
        owned_tool_arguments(runtime.view, "plan_quality_scorer", {})
    with pytest.raises(TimepointError):
        owned_tool_arguments(runtime.view, "query_metrics", {"metric_type": "dose_metrics"})
    report = owned_tool_arguments(runtime.view, "report_generator", {"action": "full_report"})
    assert report["plan_data"]["metrics"] == {}
