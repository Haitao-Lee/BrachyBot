"""Accuracy-first latency contracts; synthetic fixtures, no provider or patient work."""
import json
import threading
from types import SimpleNamespace

import pytest

from agent_runtime.core import AgentMemory, ToolRegistry
from agent_runtime.workspace_readiness import (
    EVIDENCE_MARKER, ensure_workspace_ready, requires_full_workspace,
    saved_case_evidence, refresh_saved_evidence,
)


@pytest.mark.parametrize("tool,params,full", [
    ("query_metrics", {"metric_type": "dose_metrics"}, False),
    ("query_metrics", {"metric_type": "oar_dose_metrics"}, False),
    ("query_metrics", {"metric_type": "plan_score"}, False),
    ("query_metrics", {"metric_type": "seed_count"}, False),
    ("query_metrics", {"metric_type": "needle_count"}, False),
    ("query_metrics", {"metric_type": "spacing_info"}, False),
    ("query_metrics", {"metric_type": "planning_method"}, False),
    ("query_metrics", {"metric_type": "hu_statistics"}, True),
    ("query_metrics", {"metric_type": "ctv_volume"}, True),
    ("query_metrics", {"metric_type": "oar_volumes"}, True),
    ("query_metrics", {"metric_type": "needle_seed_counts"}, True),
    ("query_metrics", {"metric_type": "all_metrics"}, True),
    ("query_metrics", {}, True),
    ("query_metrics", {"metric_type": "invented"}, True),
    ("query_metrics", {"metric_type": ["dose_metrics"]}, True),
    ("ui_content", {"target": "report"}, False),
    ("ui_screenshot", {}, False),
    ("ui_inspector", {}, False),
    ("surgical_guide", {"action": "status"}, False),
    ("surgical_guide", {"action": "analyze"}, True),
    ("surgical_guide", {"action": "generate"}, True),
    ("surgical_guide", {}, True),
    ("clinical_kb", {"action": "search"}, False),
    ("clinical_kb", {"action": "add"}, True),
    ("clinical_kb", {}, True),
    ("case_memory", {"action": "list"}, False),
    ("case_memory", {"action": "save"}, True),
    ("case_memory", {}, True),
    ("ui_controller", {"actions": [{"target": "tree.visibility", "command": "set", "value": True}]}, True),
    ("dose_recompute", {}, True),
    ("planning_pipeline", {}, True),
    ("ctv_segmentation", {}, True),
    ("doc_reader", {}, True),
    ("unknown_tool", {"conversation_access": "read", "workspace_requirement": "metadata"}, True),
])
def test_resource_dependencies_are_operation_sensitive_and_fail_closed(tool, params, full):
    assert requires_full_workspace(tool, params) is full


def test_cold_read_does_not_wait_but_array_operation_cannot_run_without_waiter():
    cold = SimpleNamespace(_workspace_data_ready=False)
    ensure_workspace_ready(cold, "query_metrics", {"metric_type": "dose_metrics"})
    with pytest.raises(RuntimeError, match="not executed"):
        ensure_workspace_ready(cold, "dose_recompute", {})


def test_waiter_checks_warm_tools_and_cannot_claim_ready_without_real_data():
    calls = []
    cold = SimpleNamespace(_workspace_data_ready=False, _workspace_resource_waiter=calls.append)
    with pytest.raises(RuntimeError):
        ensure_workspace_ready(cold, "planning_pipeline", {})
    assert calls == [True]
    cold._workspace_data_ready = True
    ensure_workspace_ready(cold, "query_metrics", {"metric_type": "dose_metrics"})
    assert calls == [True, False]


def test_direct_registry_execution_cannot_bypass_cold_case_guard():
    executed = []
    registry = ToolRegistry()
    registry.workspace_agent = SimpleNamespace(_workspace_data_ready=False)
    registry.register(SimpleNamespace(name="planning_pipeline", execute=lambda **kw: executed.append(kw)))
    with pytest.raises(RuntimeError):
        registry.execute("planning_pipeline")
    assert executed == []


def test_main_execution_gates_before_injecting_any_memory_array():
    from AgenticSys import BrachyAgent
    agent = object.__new__(BrachyAgent)
    agent.config = {}
    agent._workspace_data_ready = False
    def forbidden_read(*args):
        pytest.fail("memory injection preceded the cold workspace barrier")
    agent.memory = SimpleNamespace(retrieve=forbidden_read)
    with pytest.raises(RuntimeError):
        agent._execute_tool_with_memory("dose_recompute", {})


def memory_agent():
    agent = SimpleNamespace(memory=AgentMemory("synthetic-case"), _workspace_data_ready=False, _turn_timings={})
    agent.memory.planning_results.update({
        "active_planning_id": "p1", "planning_run_id": "p1",
        "dose_metrics": {"v100": 0.9031, "d90": 120.63, "dmax": float("nan"),
            "oar_metrics": {f"oar_{i}": {"dmax": i + 1, "d2cc": i} for i in range(12)}},
        "total_seeds": 181, "num_trajectories": 24,
        "artifact_status": {"report": {"stale": True, "status": "stale", "reason": "private"}, "dose": "stale"},
        "ct_data": SimpleNamespace(secret="arrays must not be serialized"),
    })
    agent.memory.patient_data = {"patient_id": "do-not-send", "patient_name": "private"}
    return agent


def packet(agent):
    return json.loads(saved_case_evidence(agent).split("\n", 1)[1])


def test_prefetched_facts_are_bounded_saved_scoped_and_honest():
    agent = memory_agent()
    text = saved_case_evidence(agent)
    data = packet(agent)
    assert len(text) < 6000
    assert data["planning_id"] == "p1" and not data["full_resources_ready"]
    assert data["dose_metrics"]["d90"] == 120.63
    assert "dmax" not in data["dose_metrics"]
    assert data["artifact_status"]["report"]["stale"] is True
    assert data["oar_dose"]["available_rows"] == 12
    assert data["oar_dose"]["truncated"] is True
    assert len(data["oar_dose"]["included_rows"]) == 8
    assert not any(term in text for term in ("patient_name", "do-not-send", "secret", "private", "report_contents"))
    assert data["freshness"] == "saved_snapshot_not_independent_validation"


def test_prefetch_does_not_resurrect_an_old_or_different_plan():
    agent = memory_agent()
    agent.memory.planning_results["dose_metrics"] = {}
    agent.memory.planning_results["planning_run:p1"] = {"dose_metrics": {"d90": 999}}
    assert packet(agent)["dose_metrics"] == {}
    agent.memory.planning_results["planning_run_id"] = "p2"
    agent.memory.planning_results["planning_run:p1"]["artifact_status"] = {"report": "current"}
    data = packet(agent)
    assert data["dose_metrics"]["d90"] == 999
    assert data["artifact_status"]["report"] == "current"


def test_packet_refreshes_in_place_after_write_without_fake_receipts():
    agent = memory_agent()
    messages = [{"role": "user", "content": saved_case_evidence(agent)}, {"role": "user", "content": "my real request"}]
    agent.memory.planning_results["dose_metrics"] = {"d90": 121.8}
    refresh_saved_evidence(messages, agent)
    assert len(messages) == 2 and messages[-1]["content"] == "my real request"
    assert "121.8" in messages[0]["content"] and "120.63" not in messages[0]["content"]
    assert "receipt" not in messages[0]["content"]


@pytest.mark.parametrize("stream", [False, True])
def test_simple_saved_read_can_use_one_model_round_without_mandatory_query(stream):
    from test_decision_chain_execution import Harness, run
    from agent_runtime.semantic_kernel import semantic_runtime_policy
    from agent_runtime.turn_policy import LocalTurnPolicy
    class PrefetchHarness(Harness):
        def _pack_context_for_provider(self, messages, message):
            from agent_runtime.llm_runtime import LLMRuntimeMixin
            return LLMRuntimeMixin._pack_context_for_provider(self, messages, message)
    harness = PrefetchHarness([], {})
    harness._active_turn_policy = semantic_runtime_policy(LocalTurnPolicy("knowledge_query", "low", False, False, False))
    harness.memory.planning_results.update(memory_agent().memory.planning_results)
    _, response = run(harness, stream)
    assert len(harness.provider_messages) == 1
    assert harness.executed == [] and response
    assert EVIDENCE_MARKER in str(harness.provider_messages[0])
    assert "120.63" in str(harness.provider_messages[0])


def test_background_hydration_preserves_active_dialogue_and_ui(tmp_path):
    from test_workspace_store import _Agent
    from web.workspace_store import WorkspaceStore
    store = WorkspaceStore(tmp_path / "workspaces")
    user = store.create_user("synthetic", "test-password")
    case = store.create_session(user["id"], "test case")
    agent = _Agent()
    store.snapshot_agent(user["id"], case.id, agent)
    restored = _Agent()
    store.hydrate_agent(user["id"], case.id, restored, include_planning_results=False, load_ct=False)
    restored._workspace_hydration_in_progress = True
    restored.memory.conversation.append({"role": "user", "content": "new live turn"})
    restored.memory.tool_results.append({"tool": "query_metrics", "success": True})
    restored.memory.user_lang = "zh"
    restored.memory._ui_state = {"controls": {"new": "live"}}
    restored.memory.context_summary = "new summary"
    restored.config = {"mode": "live-config"}
    ledger_updates = []
    restored.run_ledger = SimpleNamespace(restore_state=ledger_updates.append)
    store.hydrate_agent(user["id"], case.id, restored, include_planning_results=True, load_ct=False)
    assert restored.memory.conversation[-1]["content"] == "new live turn"
    assert restored.memory.tool_results[-1]["tool"] == "query_metrics"
    assert restored.memory.user_lang == "zh"
    assert restored.memory._ui_state == {"controls": {"new": "live"}}
    assert restored.memory.context_summary == "new summary"
    assert restored.config == {"mode": "live-config"}
    assert ledger_updates == []
    assert restored.memory.retrieve("dose_distribution_gy") is not None


@pytest.mark.parametrize("language", ["en", "zh"])
def test_task_waiter_is_scoped_and_reports_only_real_waits(language):
    from flask import Flask
    from web.chat_tasks import ChatTaskManager
    agent = SimpleNamespace(memory=SimpleNamespace(set_ui_state=lambda state: None), brain_available=False)
    waits = []
    def factory(current, progress):
        assert current is agent
        def waiter(required):
            assert progress({"phase": "check", "quiet": True})
            waits.append(required)
            if required:
                progress({"phase": "ct"})
                progress({"phase": "ready"})
        return waiter
    def chat(message):
        agent._workspace_resource_waiter(False)
        agent._workspace_resource_waiter(True)
        yield 'event: response\ndata: {"response":"saved facts"}\n\n'
        yield 'event: done\ndata: {}\n\n'
    agent.chat_with_stream = chat
    task = ChatTaskManager().start(Flask(__name__), "owner", "case", agent, "test", {},
        resource_waiter_factory=factory, response_language=language)
    assert task.wait_for_worker(timeout=5)
    assert waits == [False, True] and task.status == "completed"
    assert not hasattr(agent, "_workspace_resource_waiter")
    events = list(task.iter_events())
    assert len([e for e in events if '"tool": "workspace_hydration"' in e]) == 2
    from web.chat_tasks import _event_parts
    titles = [_event_parts(e)[1].get("title") for e in events]
    assert ('准备操作所需资源' if language == "zh" else 'Preparing resources for the operation') in titles


def test_missing_resources_are_not_attempted_receipts_and_do_not_block_metadata_sibling():
    from agent_runtime.workspace_readiness import prepare_resource_calls
    agent = SimpleNamespace(_workspace_data_ready=False)
    calls = [{"id": "write", "tool": "planning_pipeline", "params": {}},
             {"id": "read", "tool": "query_metrics", "params": {"metric_type": "dose_metrics"}}]
    results = prepare_resource_calls(agent, calls)
    assert results[0]["_resource_blocked"] and results[0]["_argument_error"]
    assert results[1] is calls[1] and not calls[0].get("_argument_error")
    from agent_runtime.execution_authorization import TurnExecutionAuthorization
    auth = TurnExecutionAuthorization(1)
    auth.grant_tool_calls(results, source="test")
    assert not auth.granted_tools


def test_clinical_prerequisite_inspection_happens_after_the_ready_barrier():
    from agent_runtime.workspace_readiness import prepare_resource_calls
    agent = SimpleNamespace(_workspace_data_ready=False)
    def complete(required):
        assert required is True
        agent._workspace_data_ready = True
    agent._workspace_resource_waiter = complete
    calls = [{"id": "planning", "tool": "planning_pipeline", "params": {"step": "full"}}]
    assert prepare_resource_calls(agent, calls) == calls
    assert agent._workspace_data_ready is True


@pytest.mark.parametrize("mode", ["read_cold", "read_failed", "full_cold", "full_failed", "after_explicit_import", "changed_input"])
def test_real_chat_route_uses_tool_dependencies_not_domain_words(tmp_path, monkeypatch, mode):
    from test_case_archive_active_use import _build_app
    from web.routes import planning_routes
    from web.chat_tasks import ChatTaskError
    monkeypatch.delenv("BRACHYBOT_API_KEY", raising=False)
    monkeypatch.delenv("BRACHYBOT_REQUIRE_API_KEY", raising=False)
    app = _build_app(tmp_path, monkeypatch)
    client = app.test_client()
    auth = client.post("/api/auth/register", json={"username": "synthetic_latency", "password": "synthetic-pass-123"}).get_json()
    case_id = auth["active_session_id"]
    memory = AgentMemory(case_id)
    memory.store("ct_path", "/synthetic/current-ct.nii.gz")
    agent = SimpleNamespace(memory=memory, brain_available=False, config={},
        _workspace_data_ready=mode == "after_explicit_import",
        _workspace_hydration_superseded=mode == "after_explicit_import",
        _workspace_hydration_in_progress=True,
        _workspace_hydration_error="synthetic decode failure" if mode in {"read_failed", "full_failed"} else "")
    ready_calls, executed = [], []
    def await_ready(current, report, **kwargs):
        assert current is agent
        ready_calls.append(mode)
        if mode == "full_failed":
            raise ChatTaskError("synthetic decode failure", code="workspace_hydration_failed")
        assert report("ct")
        current._workspace_data_ready = True
        current._workspace_hydration_in_progress = False
    monkeypatch.setattr(planning_routes, "await_chat_case_resources", await_ready)
    def chat(message):
        if mode == "changed_input":
            memory.store("ct_path", "/synthetic/replaced-ct.nii.gz")
        full = mode in {"full_cold", "full_failed", "after_explicit_import", "changed_input"}
        ensure_workspace_ready(agent, "dose_recompute" if full else "query_metrics", {} if full else {"metric_type": "dose_metrics"})
        executed.append(mode)
        yield 'event: response\ndata: {"response":"synthetic saved result"}\n\n'
        yield 'event: done\ndata: {}\n\n'
    agent.chat_with_stream = chat
    sessions, timestamps, lock = app.extensions["brachybot_agent_cache"]
    with lock:
        sessions[(auth["user"]["id"], case_id)] = agent
        timestamps[(auth["user"]["id"], case_id)] = 1e12
    response = client.post("/api/chat", json={"message": "报告里的剂量、导板和CTV状态如何", "stream": True},
        headers={"X-CSRF-Token": auth["csrf_token"], "X-BrachyBot-Session": case_id})
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    if mode in {"full_failed", "changed_input"}:
        assert executed == []
        assert ("workspace_hydration_failed" if mode == "full_failed" else "workspace_hydration_cancelled") in body
    else:
        assert executed == [mode] and "synthetic saved result" in body
    assert bool(ready_calls) == (mode in {"full_cold", "full_failed"})
    assert not hasattr(agent, "_workspace_resource_waiter")
