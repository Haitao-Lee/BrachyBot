"""Read discovery never widens owner, computation or mutation scope."""
from types import SimpleNamespace

import pytest

from tool_factory.timepoint_inspector import TimepointInspectorTool
from web.workspace_store import WorkspaceStore


@pytest.fixture
def inspector(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("inspector_owner", "synthetic-hash")
    sid = store.create_session(user["id"], "Synthetic").id
    agent = SimpleNamespace(config={"_workspace_owner_id": user["id"], "_workspace_session_id": sid},
                            _workspace_store=store)
    return store, user["id"], sid, TimepointInspectorTool(agent)


def test_catalog_exposes_all_owned_timepoints_without_loading_arrays(inspector):
    store, user, sid, tool = inspector
    a = store.create_timepoint(user, sid, "Second scan", expected_revision=0)["created_timepoint_id"]
    result = tool.execute(action="list")
    assert result.success
    assert len(result.data["timepoints"]) == 2
    assert result.metadata["read_only"] is True
    assert a in result.data["items"]


def test_inspect_reads_saved_metrics_with_truthful_freshness(inspector):
    store, user, sid, tool = inspector
    identifier = store.create_timepoint(user, sid, "During surgery", expected_revision=0)["created_timepoint_id"]
    store.save_timepoint_results(user, sid, identifier, {
        "ct_path": "inputs/synthetic.nii.gz", "dose_metrics": {"v100": 90.1},
        "organ_names": {"3": "spinal_cord"},
    }, expected_state_revision=0)
    before = store.list_timepoints(user, sid)["catalog_revision"]
    result = tool.execute(action="inspect", timepoint_ids=[identifier])
    assert result.success
    fact = result.data[0]
    assert fact["saved_metrics"]["dose_metrics"]["v100"] == 90.1
    assert fact["dose_freshness"] == "not_independently_checked"
    assert fact["image_name"] == "synthetic.nii.gz"
    assert store.list_timepoints(user, sid)["catalog_revision"] == before


@pytest.mark.parametrize("action", ["delete", "plan", "register", "recompute", None])
def test_no_mutation_actions_are_available(inspector, action):
    *_, tool = inspector
    result = tool.execute(action=action)
    assert not result.success


def test_caller_cannot_select_another_owner_or_session(inspector):
    *_, tool = inspector
    assert not tool.execute(action="list", session_id="other").success
    assert not tool.execute(action="list", owner_id="other").success
    assert not tool.execute(action="inspect", timepoint_ids=["f" * 32]).success


def test_cli_tool_is_unavailable_without_authenticated_store():
    tool = TimepointInspectorTool(SimpleNamespace(config={}))
    assert not tool.is_available()
    assert not tool.execute(action="list").success


def test_inspector_distinguishes_current_input_from_historical_quality(inspector):
    store, user, sid, tool = inspector
    identifier = store.create_timepoint(user,sid,'Changed prescription',expected_revision=0)['created_timepoint_id']
    store.save_timepoint_results(user,sid,identifier,{
        'plan_config':{'in_lowest_dose_gy':90.,'dose_value_unit':'gy'},
        'timepoint_planning_config':{'in_lowest_dose_gy':120.,'dose_value_unit':'gy'},
        'dose_metrics':{'v100':1.,'prescription_gy':90.},
    },expected_state_revision=0)
    result = tool.execute(action='inspect',timepoint_ids=[identifier])
    assert result.success, result.error
    fact = result.data[0]
    assert fact['current_input_config']['in_lowest_dose_gy'] == 120.
    assert fact['current_evaluation_config']['prescription_gy'] == 120.
    assert fact['historical_plan_config']['in_lowest_dose_gy'] == 90.
    assert fact['dose_freshness'] == 'invalidated'
