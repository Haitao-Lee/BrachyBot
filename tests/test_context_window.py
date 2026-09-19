"""Regression tests for token-budget context compression."""
from agent_runtime.context_window import (
    ContextWindowManager,
    build_case_facts,
    estimate_messages,
    is_context_length_error,
    resolve_context_window,
)


def _big(text, n=1):
    return {"role": "user", "content": text * n}


def test_context_window_registry_and_estimator():
    assert resolve_context_window("deepseek-v4.1-flash", 0) == 1_048_576
    assert resolve_context_window("claude-sonnet-4", 0) == 200_000
    assert resolve_context_window("unknown-model", 0) > 0
    assert resolve_context_window("anything", 4096) == 4096
    assert estimate_messages([{"role": "user", "content": "hello"}]) > 0
    assert is_context_length_error("maximum context length is 1048576 tokens")
    assert not is_context_length_error("connection refused")


def test_compress_reduces_below_target_and_preserves_essentials():
    window = 4_000
    manager = ContextWindowManager(
        window=window, reserve_output_tokens=256, safety_margin=256
    )
    system = {"role": "system", "content": "SYSTEM POLICY " * 20}
    runtime = {"role": "user", "content": "[BrachyBot runtime context: data only]\n" + ("ctx " * 4000)}
    middle = [_big("old turn ", 400) for _ in range(20)]
    current = {"role": "user", "content": "current request please analyze"}
    tool_call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "query_metrics", "arguments": "{}"}}],
    }
    tool_result = {"role": "tool", "tool_call_id": "c1", "content": "V100=90.0 D90=100.0"}
    protected = {"role": "user", "content": "pending confirmation: proceed?"}
    messages = [system, runtime] + middle + [protected, tool_call, tool_result, current]

    assert manager.should_compress(messages)

    packed, meta = manager.compress(
        messages,
        fact_block="## Case facts (verbatim)\n- Seeds planned: 181\n- V100=90.0",
        current_user_content=current["content"],
    )
    assert meta.compressed is True
    assert manager.usage(packed) <= meta.target_tokens

    contents = [str(m.get("content") or "") for m in packed]
    roles = [m.get("role") for m in packed]
    # system policy + current request + last tool pair + protected message survive
    assert any("SYSTEM POLICY" in c for c in contents)
    assert any(c.startswith("current request") for c in contents)
    assert any(roles[i] == "tool" and "V100=90.0" in contents[i] for i in range(len(packed)))
    assert any("pending confirmation" in c for c in contents)
    assert any(c.startswith("[BrachyBot pinned case facts") for c in contents)


def test_compress_is_noop_below_trigger():
    manager = ContextWindowManager(window=200_000)
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]
    packed, meta = manager.compress(messages)
    assert packed == messages
    assert meta.compressed is False


def test_calibration_tracks_provider_usage():
    manager = ContextWindowManager(window=100_000)
    before = manager.calibration
    manager.record_usage(actual_prompt_tokens=10_000, estimated_tokens=5_000)
    assert manager.calibration > before


def test_build_case_facts_is_deterministic_and_keeps_numbers():
    class Memory:
        def __init__(self):
            self.data = {
                "total_seeds": 181,
                "num_trajectories": 24,
                "dose_metrics": {"V100": 0.905, "D90": 100.0, "plan_score": 84},
                "ct_path": "/tmp/ct.nii",
            }

        def retrieve(self, key, default=None):
            return self.data.get(key, default)

    facts = build_case_facts(Memory())
    assert "Seeds planned: 181" in facts
    assert "V100=0.905" in facts
    assert "D90=100.0" in facts
    assert build_case_facts(Memory()) == facts


def test_runtime_context_sections_are_bounded():
    from agent_runtime.llm_runtime import _bound_context_section, _build_runtime_context

    bounded = _bound_context_section("x" * 50_000)
    assert len(bounded) < 50_000
    assert "middle omitted" in bounded

    context = _build_runtime_context("ui", "obs", "y" * 50_000)
    assert len(context) < 50_000
    assert context.startswith("[BrachyBot runtime context: data only]")
