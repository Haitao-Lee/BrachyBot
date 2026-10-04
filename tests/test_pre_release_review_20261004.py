"""Negative controls for authenticated case tools and decoded data boundaries."""
from types import SimpleNamespace
import socket

import numpy as np
import pytest
from flask import Flask

from utils.tool_security import checked_path, tool_scope, validate_tool_paths
from utils.image_limits import check_voxel_count, read_image
from utils.public_http import public_get, resolve_public_url


@pytest.mark.parametrize("field", ["file_path", "ct_path", "output_dir", "mask_path", "label_path", "custom_path"])
def test_paths_are_case_bound_including_nested_arguments(tmp_path, field):
    case = tmp_path / "case_a"
    case.mkdir()
    with tool_scope({"_workspace_root": str(case)}):
        validate_tool_paths("reader", {field: str(case / "inputs" / "ct.nii.gz")})
        with pytest.raises(PermissionError):
            validate_tool_paths("reader", {"options": {field: str(tmp_path / "case_b" / "ct.nii.gz")}})


def test_context_scope_is_restored_and_cli_is_not_case_restricted(tmp_path):
    from utils.tool_security import workspace_root
    assert workspace_root() is None
    with tool_scope({"_workspace_root": str(tmp_path)}):
        with pytest.raises(RuntimeError):
            with tool_scope({"_workspace_root": str(tmp_path / "inner")}):
                raise RuntimeError("failed call")
        assert workspace_root() == tmp_path.resolve()
    assert workspace_root() is None
    validate_tool_paths("reader", {"file_path": "/trusted/cli/input"})


def test_path_lists_cannot_bypass_case_containment(tmp_path):
    with tool_scope({"_workspace_root": str(tmp_path / "a")}):
        with pytest.raises(PermissionError):
            validate_tool_paths("reader", {"dicom_files": [str(tmp_path / "b" / "slice.dcm")]})


def test_web_fallback_handlers_cannot_generate_code(tmp_path):
    from agent_runtime.chat_workflows import ChatWorkflowMixin
    agent = SimpleNamespace(config={"_workspace_root": str(tmp_path)})
    assert "disabled" in ChatWorkflowMixin._handle_code_writing(agent, {})
    assert "disabled" in ChatWorkflowMixin._handle_self_evolution(agent)


def test_execution_experience_uses_structured_steps_not_response_words():
    from agent_runtime.chat_workflows import ChatWorkflowMixin
    recorded = []
    agent = SimpleNamespace(
        exp_memory=SimpleNamespace(record=lambda **entry: recorded.append(entry)),
        memory=SimpleNamespace(current_phase=SimpleNamespace(value="idle"), planning_results={}),
    )
    ChatWorkflowMixin._record_experience(agent, "update", "Everything is fine.", [{"type": "tool", "status": "error"}])
    assert recorded[-1]["success"] is False
    ChatWorkflowMixin._record_experience(agent, "inspect", "No failures found", [{"type": "tool", "status": "done"}])
    assert recorded[-1]["success"] is True
    ChatWorkflowMixin._record_experience(agent, "update", "已完成")
    assert recorded[-1]["context"]["execution_evidence"] == "failed_or_unverified"


def test_case_memory_and_symlinks_do_not_expose_another_case(tmp_path):
    from tool_factory.case_memory import CaseMemoryTool, _case_file, _case_files
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    with tool_scope({"_workspace_root": str(a)}):
        tool = CaseMemoryTool()
        assert tool.execute(action="save", case_data={"case_id": "local", "organ": "test"}).success
        with pytest.raises(ValueError):
            _case_file("../../../b/private")
        private = b / "private.json"
        private.write_text('{"case_id":"other"}')
        (_case_file("link")).symlink_to(private)
        assert len(list(_case_files())) == 1
    with tool_scope({"_workspace_root": str(b)}):
        result = tool.execute(action="list")
        assert "local" not in str(result.data)


@pytest.mark.parametrize("tool", ["code_executor", "create_tool", "write_tool", "self_evolve", "env_manager"])
def test_developer_tools_cannot_run_in_web_scope(tmp_path, tool):
    with tool_scope({"_workspace_root": str(tmp_path)}), pytest.raises(PermissionError):
        validate_tool_paths(tool, {})


def test_unknown_declared_mutation_is_not_self_authorized():
    from agent_runtime.request_parse import mutating_execution_authorized
    assert not mutating_execution_authorized("What is in this case?", "case_memory", params={"action": "save"})
    assert not mutating_execution_authorized("Read the uploaded report", "dicom_rt_exporter")
    assert mutating_execution_authorized("Read the uploaded report", "doc_reader")


def test_registration_and_debug_account_are_closed_by_default(tmp_path, monkeypatch):
    from web.auth import configure_auth, register_auth_routes
    from web.workspace_store import WorkspaceStore
    monkeypatch.delenv("BRACHYBOT_ALLOW_SELF_REGISTRATION", raising=False)
    monkeypatch.delenv("BRACHYBOT_DEBUG_ACCOUNT_ENABLED", raising=False)
    app = Flask(__name__)
    store = WorkspaceStore(tmp_path / "runtime")
    configure_auth(app, store, {"secret_key": "test-secret"})
    register_auth_routes(app, store)
    response = app.test_client().post("/api/auth/register", json={"username": "new_user", "password": "correct horse battery staple"})
    assert response.status_code == 403
    assert app.extensions["brachybot_auth_policy"]["enabled"] is False


def test_request_identity_does_not_mix_header_body_query_or_cookie():
    from web.request_identity import explicit_case_id
    from web.workspace_store import WorkspaceError
    app = Flask(__name__)
    with app.test_request_context("/?session_id=a", method="POST", json={"session_id": "b"}):
        with pytest.raises(WorkspaceError):
            explicit_case_id()
    with app.test_request_context("/", headers={"X-BrachyBot-Session": "a", "Cookie": "brachybot_session=b"}, json={"session_id": "a"}):
        assert explicit_case_id() == "a"


@pytest.mark.parametrize("endpoint", ["/api/tasks", "/api/tasks/missing", "/api/tasks/stream"])
def test_task_routes_do_not_fall_back_to_all_owners(endpoint, monkeypatch):
    from web.routes.planning_routes import register_planning_routes, task_manager
    import web.server_support as support
    monkeypatch.setattr(support, "API_KEY", None)
    monkeypatch.setattr(support, "_API_KEY_REQUIRED", False)
    monkeypatch.setattr(support, "_TRUST_NETWORK", True)

    def forbidden(*args, **kwargs):
        pytest.fail("Task store must not be read without an authenticated case owner")

    monkeypatch.setattr(task_manager, "get_task", forbidden)
    monkeypatch.setattr(task_manager, "get_all_tasks", forbidden)
    app = Flask(__name__)
    app.secret_key = "test-secret"
    register_planning_routes(app, lambda: None)
    response = app.test_client().get(endpoint)
    assert response.status_code == 403
    assert response.get_json()["error"] == "Case unavailable"


def test_snapshot_cache_evicts_by_count_and_byte_budget():
    from web.workspace_store import _SnapshotCache
    cache = _SnapshotCache()
    for i in range(12):
        cache[("u", str(i))] = (i, 1024, {"i": i})
    assert len(cache) <= 8
    assert ("u", "0") not in cache
    cache[("u", "large")] = (1, 100 * 1024 * 1024, {})
    assert ("u", "large") not in cache


def test_image_dimension_limit_and_real_small_volume(tmp_path, monkeypatch):
    import SimpleITK as sitk
    monkeypatch.setenv("BRACHYBOT_MAX_IMAGE_VOXELS", "100")
    check_voxel_count((2, 3, 4))
    with pytest.raises(ValueError):
        check_voxel_count((10, 11, 1))
    with pytest.raises(ValueError):
        check_voxel_count((2, 3, 4), series_length=5)
    for bad in [(0, 3), (-1, 3), ()]:
        with pytest.raises(ValueError):
            check_voxel_count(bad)
    path = tmp_path / "volume.nii.gz"
    sitk.WriteImage(sitk.GetImageFromArray(np.zeros((2, 3, 4), dtype=np.uint8)), str(path))
    assert read_image(path).GetSize() == (4, 3, 2)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "::ffff:127.0.0.1"])
def test_public_http_rejects_private_dns_answers(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))])
    with pytest.raises(ValueError):
        resolve_public_url("https://untrusted.example/path")


def test_public_transport_uses_checked_ip_and_original_tls_hostname(monkeypatch):
    import utils.public_http as http
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    class Pool:
        def __init__(self, host, port, **kw):
            calls.append((host, port, kw))
        def urlopen(self, method, target, **kw):
            calls.append((method, target, kw))
            return SimpleNamespace(status=200, headers={}, close=lambda: None)
        def close(self):
            calls.append("closed")
    monkeypatch.setattr(http.urllib3, "HTTPSConnectionPool", Pool)
    response = public_get("https://public.example/a?q=1")
    assert calls[0][0] == "93.184.216.34"
    assert calls[0][2]["assert_hostname"] == "public.example"
    assert calls[0][2]["server_hostname"] == "public.example"
    assert calls[1][2]["headers"]["Host"] == "public.example"
    assert calls[1][2]["redirect"] is False
    response.close()
    assert calls[-1] == "closed"


def test_web_access_fetch_uses_the_same_guard(monkeypatch):
    from tool_factory.web_access import UnifiedWebAccess
    from tool_factory.web_fetch import WebFetchTool
    from tool_factory import ToolResult
    monkeypatch.setattr(WebFetchTool, "_execute", lambda self, **kw: ToolResult(success=False, error="private URL"))
    result = UnifiedWebAccess().fetch_url("http://127.0.0.1/admin")
    assert result == {"success": False, "error": "private URL"}


def test_device_selection_does_not_accumulate_leases(monkeypatch):
    from plans.device_manager import DeviceManager
    import threading
    manager = DeviceManager.__new__(DeviceManager)
    manager._cuda_available = True
    manager._device_count = 1
    manager._preferred = {}
    manager._active_per_device = {}
    manager._lease_lock = threading.Lock()
    manager._leases = []
    monkeypatch.setattr(manager, "_auto_pick", lambda **kw: "cuda:0")
    monkeypatch.setattr(manager, "_read_info", lambda i: None)
    for i in range(5):
        manager.acquire(caller="test", _reserve=False)
    assert manager._active_per_device == {}


def test_invalid_distance_window_is_not_reported_as_an_empty_good_plan():
    from plans.geometry import distance_filter
    with pytest.raises(ValueError):
        distance_filter(2, 1, 1, 0.1)


def test_coverage_includes_threshold_and_rejects_invalid_grids():
    from tool_factory.seed_plan.planning_pipeline import _plan_target_coverage
    target = np.ones((2, 2, 2))
    assert _plan_target_coverage([(None, None, [np.ones_like(target)])], target, 1, 1) == 1.0
    for dose in [np.ones((1, 1, 1)), np.full_like(target, np.nan)]:
        with pytest.raises(ValueError):
            _plan_target_coverage([(None, None, [dose])], target, 1, 1)


def test_loaded_oar_grid_cannot_disappear_from_dose_evaluation():
    from plans.dose_pre.evaluation_inputs import resolve_dose_evaluation_inputs
    values = {"ctv_array": np.ones((2, 2, 2)), "dose_distribution_gy": np.ones((2, 2, 2)), "oar_array": np.ones((3, 3, 3))}
    result = resolve_dose_evaluation_inputs(values.get)
    assert "OAR" in result["resolution_error"]
    assert not result["params"]


def test_tokens_cannot_traverse_and_special_filenames_are_rejected(tmp_path):
    from utils.display_paths import DisplayRoots, resolve_user_path
    from web.workspace_store import _safe_filename, WorkspaceError
    roots = DisplayRoots(workspace_root=str(tmp_path))
    token = roots.resolve_map()[0][0]
    with pytest.raises(ValueError):
        resolve_user_path(token + "/../../outside", roots)
    for name in [".", ".."]:
        with pytest.raises(WorkspaceError):
            _safe_filename(name)


def test_rag_retention_is_bounded_without_changing_returned_results(monkeypatch):
    from brain.knowledge.rag import SimpleRAG
    rag = SimpleRAG()
    monkeypatch.setattr(rag, "_build_documents", lambda: [{"title": "dose", "body": "dose", "urls": [], "tokens": ["dose"]}])
    for i in range(270):
        assert rag.retrieve(f"dose {i}")
    assert len(rag._cache) == 256


def test_current_torch_cve_is_a_release_gate_not_a_claim_of_safety(tmp_path, monkeypatch):
    from scripts.pre_release_security_check import checks
    monkeypatch.setattr("importlib.metadata.version", lambda name: "2.6.0+cu124")
    result = checks(tmp_path)
    assert any(item["id"] == "torch_checkpoint_cve" and item["severity"] == "block" for item in result)


def test_dose_eval_measures_target_label_not_pancreatic_vessel_labels():
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
    values = {"resampled_ctv": np.array([[[1, 1, 2, 3]]]), "dose_distribution": np.array([[[1., 1., 0., 0.]]]), "dose_scale_gy": 120., "total_seeds": 2}
    memory = SimpleNamespace(retrieve=lambda key, *a: values.get(key), store=lambda key, value: values.update({key: value}))
    result = PlanningPipelineTool()._step_dose_eval(None, None, SimpleNamespace(memory=memory))
    assert result.success
    assert result.data["ctv_voxels"] == 2
    assert result.data["v100"] == pytest.approx(1.)
    values["dose_distribution"][0, 0, 0] = np.nan
    previous = values["dose_metrics"]
    assert not PlanningPipelineTool()._step_dose_eval(None, None, SimpleNamespace(memory=memory)).success
    assert values["dose_metrics"] is previous


def test_guide_facts_do_not_turn_nominal_axis_alignment_into_mesh_qa():
    from agent_runtime.artifact_analysis import build_guide_characteristics_facts
    facts = build_guide_characteristics_facts({"validation": {
        "max_centerline_deviation_mm": 0.0,
        "centerline_deviation_method": "nominal_axis_by_construction_not_mesh_measurement",
        "mesh_centerline_deviation_mm": None,
    }})
    assert facts["validation"]["max_centerline_deviation_mm"] == 0.0
    assert facts["validation"]["mesh_centerline_measured"] is False
    assert "not_mesh_measurement" in facts["validation"]["centerline_deviation_method"]


def test_rtdose_dimension_guard_precedes_pixel_decode():
    from tool_factory.input.dicom_rt_importer import _read_rtdose
    class Oversized:
        Rows, Columns, NumberOfFrames = 100000, 100000, 100000
        @property
        def pixel_array(self):
            pytest.fail("pixel decoding must not run")
    with pytest.raises(ValueError):
        _read_rtdose(Oversized())


def test_detached_image_header_cannot_read_a_cross_case_sidecar(tmp_path):
    from utils.image_limits import _check_detached_image
    case = tmp_path / "case"
    case.mkdir()
    header = case / "ct.mhd"
    header.write_text("ObjectType = Image\nElementDataFile = ../other/private.raw\n")
    with pytest.raises(PermissionError):
        _check_detached_image(header)
    header.write_text("ObjectType = Image\nElementDataFile = data.raw\n")
    _check_detached_image(header)
