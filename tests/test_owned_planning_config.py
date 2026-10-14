"""Owned Input configuration survives request, cache and Session boundaries.

HTTP tests use the real Flask factory, authentication, scoped request adapter
and filesystem/SQLite store. Numerical execution is not part of this contract.
"""
import copy
from io import BytesIO
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from web.input_workflow import PLANNING_CONFIG_KEYS
from web.workspace_store import WorkspaceStore


CONFIG_A = {
    "DVH_rate": .81, "max_iter": 7, "in_lowest_dose_gy": 130,
    "out_highest_dose_gy": 110, "reference_direc": [0., 0., 1.],
    "mode": "rule_based",
}
CONFIG_B = {
    "DVH_rate": .93, "max_iter": 9, "in_lowest_dose_gy": 145,
    "out_highest_dose_gy": 105, "reference_direc": [1., 0., 0.],
    "mode": "rule_based",
}


@pytest.fixture
def owned_config_http(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.delenv("BRACHYBOT_API_KEY", raising=False)
    monkeypatch.delenv("BRACHYBOT_REQUIRE_API_KEY", raising=False)
    if os.name == "nt":
        # Windows has no directory fsync. Files and SQLite remain real; this
        # portable suite does not claim POSIX directory durability.
        monkeypatch.setattr(WorkspaceStore, "_fsync_directory", staticmethod(lambda path: None))
        # Windows CRT fsync rejects read-only descriptors used by bundle
        # export/tree flush. Keep the real fsync with a writable descriptor
        # only for this fixture's files; no production IO is replaced.
        original_open = Path.open
        def portable_open(path, mode="r", *args, **kwargs):
            if mode == "rb" and path.resolve().is_relative_to(tmp_path.resolve()):
                mode = "r+b"
            return original_open(path, mode, *args, **kwargs)
        monkeypatch.setattr(Path, "open", portable_open)
    from web.server import create_app
    options = {
        "runtime_dir": str(tmp_path / "runtime"),
        "secret_key": "synthetic-owned-config-secret",
        "workspace_maintenance": False,
        "expose_internal_seams": True,
    }
    app = create_app(options)
    client = app.test_client()
    credentials = {"username": "owned_config_owner", "password": "synthetic-config-password-123"}
    response = client.post("/api/auth/register", json=credentials)
    assert response.status_code == 201, response.get_data(as_text=True)
    auth = response.get_json()
    sid, uid = auth["active_session_id"], auth["user"]["id"]
    store = app.extensions["brachybot_workspace_store"]
    raw = getattr(store, "raw", store)
    response = client.get(f"/api/sessions/{sid}/timepoints")
    assert response.status_code == 200, response.get_data(as_text=True)
    catalog = response.get_json()
    first = catalog["default_timepoint_id"]
    headers = {
        "X-CSRF-Token": auth["csrf_token"],
        "X-BrachyBot-Session": sid,
        "X-BrachyBot-Timepoint": first,
    }
    response = client.post(f"/api/sessions/{sid}/timepoints", headers=headers, json={
        "title": "Independent config B", "expected_revision": catalog["catalog_revision"],
    })
    assert response.status_code == 201, response.get_data(as_text=True)
    second = response.get_json()["created_timepoint_id"]
    case = SimpleNamespace(app=app, client=client, raw=raw, uid=uid, sid=sid,
        first=first, second=second, headers=headers, options=options,
        credentials=credentials, tmp_path=tmp_path)
    yield case
    app.extensions["brachybot_shutdown_flush"]()


def _headers(case, tid, *, sid=None, csrf=None):
    return {**case.headers, "X-BrachyBot-Timepoint": tid,
        "X-BrachyBot-Session": sid or case.sid,
        "X-CSRF-Token": csrf or case.headers["X-CSRF-Token"]}


def _get(case, tid, *, client=None, sid=None, csrf=None):
    response = (client or case.client).get("/api/config", headers=_headers(case, tid, sid=sid, csrf=csrf))
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body["success"] is True
    assert isinstance(body["defaults"], dict) and body["defaults"]
    assert isinstance(body["config"], dict)
    assert set(body["config"]) <= set(PLANNING_CONFIG_KEYS)
    return body


def _post(case, tid, patch):
    response = case.client.post("/api/config", headers=_headers(case, tid), json=patch)
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["success"] is True
    return response.get_json()["config"]


def _snapshot(case, tid, *, store=None, sid=None):
    return (store or case.raw).load_timepoint_snapshot(case.uid, sid or case.sid, tid)


def _assert_config(actual, patch):
    for key, value in patch.items():
        assert actual[key] == value, key
    assert actual["in_lowest_energy"] == patch["in_lowest_dose_gy"]
    assert actual["out_highest_energy"] == patch["out_highest_dose_gy"]
    assert actual["dose_value_unit"] == "gy"


def test_http_post_then_new_get_preserves_a_and_b_independence(owned_config_http):
    case = owned_config_http
    before_b = _snapshot(case, case.second)
    initial_b = _get(case, case.second)
    before_a = _snapshot(case, case.first)
    _assert_config(_post(case, case.first, CONFIG_A), CONFIG_A)
    # Each client call ends its request; GET cannot reuse POST's detached view.
    a = _get(case, case.first)
    _assert_config(a["config"], CONFIG_A)
    saved_a = _snapshot(case, case.first)
    assert saved_a["timepoint_clinical_revision"] > before_a["timepoint_clinical_revision"]
    assert saved_a["agent"]["planning_results"]["timepoint_planning_config"] == a["config"]
    assert _get(case, case.second)["config"] == initial_b["config"]
    assert _snapshot(case, case.second)["timepoint_clinical_revision"] == before_b["timepoint_clinical_revision"]
    _assert_config(_post(case, case.second, CONFIG_B), CONFIG_B)
    _assert_config(_get(case, case.second)["config"], CONFIG_B)
    assert _get(case, case.first)["config"] == a["config"]
    assert _snapshot(case, case.first)["timepoint_clinical_revision"] == saved_a["timepoint_clinical_revision"]
    # Updating one acquisition never rewrites the shipped defaults.
    assert _get(case, case.second)["defaults"] == a["defaults"] == initial_b["defaults"]


def test_http_config_restores_after_agent_cache_eviction_and_store_reopen(owned_config_http):
    case = owned_config_http
    for tid, patch in ((case.first, CONFIG_A), (case.second, CONFIG_B)):
        _post(case, tid, patch)
    expected = {tid: _get(case, tid)["config"] for tid in (case.first, case.second)}
    cache, timestamps, lock = case.app.extensions["brachybot_agent_cache"]
    key = (case.uid, case.sid)
    with lock:
        old_agent = cache[key]
    case.app.extensions["brachybot_shutdown_flush"]()
    with lock:
        cache.pop(key)
        timestamps.pop(key, None)
    for tid in expected:
        assert _get(case, tid)["config"] == expected[tid]
    with lock:
        # GET reads durable metadata without rehydrating a large clinical
        # Agent. Eviction must remain effective; restoration is store-owned.
        assert key not in cache
    reopened = WorkspaceStore(case.raw.runtime_dir)
    for tid in expected:
        assert _snapshot(case, tid, store=reopened)["agent"]["planning_results"]["timepoint_planning_config"] == expected[tid]
    # A second factory has its own empty Agent cache and freshly opened store.
    from web.server import create_app
    cold_app = create_app(dict(case.options))
    cold_client = cold_app.test_client()
    login = cold_client.post("/api/auth/login", json=case.credentials)
    assert login.status_code == 200, login.get_data(as_text=True)
    try:
        for tid in expected:
            assert _get(case, tid, client=cold_client, csrf=login.get_json()["csrf_token"])["config"] == expected[tid]
    finally:
        cold_app.extensions["brachybot_shutdown_flush"]()


def test_session_bundle_import_and_cold_store_keep_each_owned_config(owned_config_http):
    case = owned_config_http
    for tid, patch in ((case.first, CONFIG_A), (case.second, CONFIG_B)):
        _post(case, tid, patch)
    expected = {tid: _get(case, tid)["config"] for tid in (case.first, case.second)}
    from web.timepoint_bundle import export_bundle
    archive = case.tmp_path / "owned-config-session.zip"
    export_bundle(case.raw, case.uid, case.sid, archive)
    imported = case.client.post("/api/workspace/import-bundle", headers=case.headers,
        data={"file": (BytesIO(archive.read_bytes()), archive.name)}, content_type="multipart/form-data")
    assert imported.status_code == 201, imported.get_data(as_text=True)
    body = imported.get_json()
    restored_sid = body["session"]["id"]
    assert restored_sid != case.sid
    assert body["active_session_changed"] is False
    reopened = WorkspaceStore(case.raw.runtime_dir)
    for tid, config in expected.items():
        assert _snapshot(case, tid, store=reopened, sid=restored_sid)["agent"]["planning_results"]["timepoint_planning_config"] == config
        assert _get(case, tid, sid=restored_sid)["config"] == config
        assert _get(case, tid)["config"] == config


def test_same_config_has_no_clinical_delta_or_product_invalidation(owned_config_http):
    case = owned_config_http
    _post(case, case.first, CONFIG_A)
    stored_config = _get(case, case.first)["config"]
    before = _snapshot(case, case.first)
    products = {
        "dose_metrics": {"v100": .91, "d90": 132.},
        "total_seeds": 12, "planning_version": 3, "report_status": "current",
        "manual_artifact_status": {"dose": "current", "dvh": "current"},
    }
    case.raw.save_timepoint_results(case.uid, case.sid, case.first, products,
        expected_clinical_revision=before["timepoint_clinical_revision"])
    before = _snapshot(case, case.first)
    _post(case, case.first, stored_config)
    after = _snapshot(case, case.first)
    assert after["timepoint_clinical_revision"] == before["timepoint_clinical_revision"]
    assert after["agent"]["planning_results"]["timepoint_planning_config"] == stored_config
    for key, value in products.items():
        assert after["agent"]["planning_results"][key] == value
    assert _get(case, case.first)["config"] == stored_config


def test_invalid_config_is_rejected_without_changing_saved_or_live_values(owned_config_http):
    case = owned_config_http
    _post(case, case.first, CONFIG_A)
    before = _snapshot(case, case.first)
    config = _get(case, case.first)["config"]
    rejected = case.client.post("/api/config", headers=case.headers,
        json={"max_iter": 99, "DVH_rate": 1.5})
    assert rejected.status_code == 400, rejected.get_data(as_text=True)
    assert _snapshot(case, case.first)["timepoint_clinical_revision"] == before["timepoint_clinical_revision"]
    assert _snapshot(case, case.first)["agent"]["planning_results"]["timepoint_planning_config"] == config
    assert _get(case, case.first)["config"] == config


def test_plan_reset_keeps_timepoint_config_outside_historical_plan(owned_config_http):
    case = owned_config_http
    _post(case, case.first, CONFIG_A)
    config = _get(case, case.first)["config"]
    response = case.client.post("/api/planning/clear", headers=case.headers, json={})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["success"] is True
    saved = _snapshot(case, case.first)["agent"]["planning_results"]
    assert saved["timepoint_planning_config"] == config
    planning_id = saved["active_planning_id"]
    assert "timepoint_planning_config" not in saved["planning_run:" + planning_id]
    assert _get(case, case.first)["config"] == config


def test_unowned_config_fields_are_not_persisted_or_returned_by_get(owned_config_http):
    case = owned_config_http
    forbidden = {"api_key": "synthetic-must-not-persist", "_workspace_owner_id": "foreign-owner",
        "_workspace_timepoint_id": case.second, "provider": "foreign-provider"}
    _post(case, case.first, {**CONFIG_A, **forbidden})
    current = _get(case, case.first)["config"]
    saved = _snapshot(case, case.first)["agent"]["planning_results"]["timepoint_planning_config"]
    _assert_config(current, CONFIG_A)
    assert saved == current
    assert set(saved).isdisjoint(forbidden)


def test_scoped_pipeline_restores_owned_config_before_numerical_execution(owned_config_http, monkeypatch):
    case = owned_config_http
    _post(case, case.second, CONFIG_B)
    config = _get(case, case.second)["config"]
    before = _snapshot(case, case.second)
    case.raw.save_timepoint_results(case.uid, case.sid, case.second, {
        "ct_data": np.zeros((4, 4, 4), np.int16),
        "ct_spacing": (1., 1., 1.), "ct_origin": (0., 0., 0.),
        "ct_direction": (1., 0., 0., 0., 1., 0., 0., 0., 1.),
        "ctv_binary_array": np.ones((4, 4, 4), np.uint8),
        "oar_array": np.zeros((4, 4, 4), np.uint8),
    }, expected_clinical_revision=before["timepoint_clinical_revision"])
    from agent_runtime.core import AgentMemory
    from tool_factory import ToolResult
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
    from web.timepoint_execution import ScopedPipelineExecutor
    control = SimpleNamespace(memory=AgentMemory(case.sid), _workspace_store=WorkspaceStore(case.raw.runtime_dir),
        config={**copy.deepcopy(CONFIG_A), "_workspace_owner_id": case.uid,
            "_workspace_session_id": case.sid, "_workspace_root": str(case.raw.workspace_root(case.uid, case.sid))})
    captured = []
    def inspect_execution(_tool, **kwargs):
        view = kwargs["_agent"]
        captured.append(view)
        _assert_config(view.config, CONFIG_B)
        assert view.config["_workspace_timepoint_id"] == case.second
        assert view.memory.retrieve("timepoint_planning_config") == config
        return ToolResult(success=False, error="Synthetic boundary inspection; no numerical calculation")
    monkeypatch.setattr(PlanningPipelineTool, "_execute", inspect_execution)
    revision = _snapshot(case, case.second)["timepoint_clinical_revision"]
    result = ScopedPipelineExecutor(control).execute(case.second)
    assert result.success is False and len(captured) == 1
    assert captured[0] is not control
    assert control.config["DVH_rate"] == CONFIG_A["DVH_rate"]
    assert control.memory.retrieve("timepoint_planning_config") is None
    assert _snapshot(case, case.second)["timepoint_clinical_revision"] == revision
