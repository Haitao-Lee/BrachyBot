"""Exercise both real provider loops with simulated tools, without case writes."""
from types import SimpleNamespace
import pytest

from AgenticSys import BrachyAgent
from agent_runtime.core import AgentMemory, ToolRegistry
from agent_runtime.execution_authorization import TurnExecutionAuthorization
from agent_runtime.turn_policy import classify_local_turn
from tool_factory import ToolResult


class Harness(BrachyAgent):
    def __init__(self, batches, results):
        self.memory = AgentMemory("decision-contract-test")
        self.memory.smart_context = None
        self.memory.user_lang = "en"
        self.memory.store("ct_path", "/test/ct.nii.gz")
        self.enhanced = None
        self.config = {}
        self.run_ledger = None
        self._turn_execution_authorization = TurnExecutionAuthorization(0)
        self._active_turn_policy = classify_local_turn("Please check the current workspace and explain each result")
        self._active_turn_policy = SimpleNamespace(**{**self._active_turn_policy.__dict__, "allow_tools": None})
        self._active_turn_context = {}
        self._turn_timings = {}
        self._active_turn_token = 0
        self._cancel_requested = False
        self.registry = ToolRegistry()
        for name in {call["name"] for batch in batches for call in batch}:
            self.registry.register(SimpleNamespace(name=name, description=name, category="test", input_schema={"type": "object", "properties": {}}))
        self.batches = list(batches)
        self.results = results
        self.executed = []
        self.provider_messages = []
        self.brain_router = SimpleNamespace(chat_messages=self.reply, chat_messages_stream=self.stream_reply)

    def reply(self, **kwargs):
        self.provider_messages.append([dict(m) for m in kwargs["messages"]])
        calls = self.batches.pop(0) if self.batches else []
        return SimpleNamespace(content="" if calls else "Result: 120.2 Gy\n\n- Available evidence", tool_calls=calls,
                               usage={}, latency_ms=0, finish_reason="stop")

    def stream_reply(self, **kwargs):
        result = self.reply(**kwargs)
        if result.content:
            yield result.content
        yield {"type": "final", "tool_calls": result.tool_calls, "usage": {}}

    def _execute_tool_with_memory(self, name, params, **kwargs):
        self.executed.append(name)
        return self.results.get(name, ToolResult(True, message="verified test result"))

    def _normalize_tool_params(self, calls):
        return calls

    def _normalize_clinical_tool_calls(self, calls, message):
        return calls

    def _begin_context_turn(self):
        pass

    def _pack_context_for_provider(self, messages, message):
        return messages

    def _enforce_context_budget(self, messages, *args, **kwargs):
        return messages

    def _record_context_usage(self, usage):
        pass

    def _detect_realtime_query(self, message):
        return None

    def _detect_external_project_query(self, message):
        return None

    def _has_completed_planning(self):
        return False

    def _planning_requested(self, *args):
        return False

    def _has_completed_planning_in_steps(self, steps):
        return False


def run(harness, stream):
    steps = []
    message = "Please check the current workspace and explain each result"
    harness.memory.add_message("user", message)
    if stream:
        events = list(harness._run_llm_function_calling_stream(message, steps, [0], lambda kind, data: {"type": kind, "data": data}))
        result = [e for e in events if isinstance(e, dict) and e.get("type") == "_result"][-1]["response"]
    else:
        result, _metadata = harness._run_llm_function_calling(message, steps, [0])
    return steps, result


@pytest.mark.parametrize("stream", [False, True])
def test_real_loops_preserve_failure_and_run_independent_query(stream):
    harness = Harness([[
        {"key": "dose", "name": "dose_recompute", "input": {}},
        {"key": "report", "name": "report_generator", "input": {}, "depends_on": ["dose"]},
        {"key": "independent", "name": "query_metrics", "input": {}},
    ]], {"dose_recompute": ToolResult(False, error="test dose failure")})
    steps, response = run(harness, stream)
    assert harness.executed == ["dose_recompute", "query_metrics"]
    assert any(s.get("dependency_blocked") for s in steps)
    # The user-error contract may localize/sanitize the raw error, but neither
    # path may lose the operation's failure or its blocked consumer.
    evidence = str(harness.provider_messages[-1])
    assert "dose_recompute" in evidence and "failed" in evidence
    assert "report" in evidence and "Not executed" in evidence
    assert "120.2" in response
    assert "\n\n- " in response
    assert len(harness.provider_messages) == 2


@pytest.mark.parametrize("stream", [False, True])
def test_real_loops_read_again_after_state_change(stream):
    harness = Harness([[
        {"key": "before", "name": "query_metrics", "input": {}},
        {"key": "edit", "name": "ui_controller", "input": {}},
        {"key": "after", "name": "query_metrics", "input": {}, "depends_on": ["edit"]},
    ]], {})
    run(harness, stream)
    assert harness.executed == ["query_metrics", "ui_controller", "query_metrics"]
    assert len(harness.provider_messages) == 2


def test_injected_clinical_prerequisites_keep_dependency_identity():
    class Memory:
        def retrieve(self, key, default=None):
            return default

    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()
    agent._has_completed_planning = lambda *args: False
    agent._current_ct_path = lambda *args: "/test/ct.nii.gz"
    calls = agent._normalize_clinical_tool_calls([
        {"key": "requested-plan", "id": "p", "tool": "planning_pipeline", "params": {"step": "full"}},
        {"key": "requested-guide", "id": "g", "tool": "surgical_guide", "params": {"action": "generate"}},
    ], "请执行胰腺癌粒子植入规划并生成导板")
    from agent_runtime.step_execution import StepExecutionState
    state = StepExecutionState()
    batch = state.prepare(calls)
    state.record(batch[0], success=False)
    assert [call["tool"] for call in batch] == ["ctv_segmentation", "oar_segmentation", "planning_pipeline", "surgical_guide"]
    assert all(state.blocked_reason(call) for call in batch[1:])
    assert batch[2]["key"] == "requested-plan"
    assert batch[3]["key"] == "requested-guide"
