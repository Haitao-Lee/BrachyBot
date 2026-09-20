"""Regression tests for token-budget context compression."""
from agent_runtime.context_window import (
    IMAGE_TOKEN_ESTIMATE,
    ContextWindowManager,
    build_case_facts,
    estimate_breakdown,
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


def test_image_payload_is_not_counted_as_base64_text_tokens():
    """A multimodal screenshot must be billed as an image, not its base64 size.

    Regression: a ~2 MB clinical screenshot encoded as a data URL was counted
    at ``len(url) // 4`` (~500k "tokens"), which made a 1M-token model read as
    roughly 50% full from a single image.
    """
    payload = "A" * 2_000_000
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "analyze this screenshot"},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{payload}",
                    "detail": "high",
                },
            },
        ],
    }
    estimated = estimate_messages([message])
    assert estimated < IMAGE_TOKEN_ESTIMATE + 500
    parts = estimate_breakdown([message])
    assert parts["images"] == IMAGE_TOKEN_ESTIMATE
    assert parts["total"] == estimated


def test_low_detail_image_uses_smaller_budget():
    message = {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA", "detail": "low"}},
        ],
    }
    parts = estimate_breakdown([message])
    assert 0 < parts["images"] < IMAGE_TOKEN_ESTIMATE


def test_compact_emits_durable_checkpoint_signal():
    """AgentMemory.compact must notify persistence so hydration cannot undo it."""
    from agent_runtime.core import AgentMemory

    memory = AgentMemory("compact-persist")
    events = []
    memory.set_persistence_callback(events.append)
    for i in range(10):
        memory.add_message("user", f"turn {i} " + "x" * 80)
    events.clear()

    memory.compact(keep_last=2)

    assert len(memory.conversation) == 2
    assert memory.compaction_count == 1
    assert "conversation.compacted" in events


def test_compress_is_cumulative_and_avoids_duplicate_marker_blocks():
    """A second compression folds into one fresh block, not stacked copies."""
    from agent_runtime.context_window import _content_text, _FACTS_MARKER, _HISTORY_MARKER

    manager = ContextWindowManager(window=8192, reserve_output_tokens=512, safety_margin=512)

    def build(tag):
        msgs = [{"role": "system", "content": "sys"}]
        msgs += [
            {"role": "user", "content": f"old {tag} {i} " + "y" * 300}
            for i in range(30)
        ]
        msgs.append({"role": "user", "content": f"current {tag}"})
        return msgs

    p1, _ = manager.compress(
        build("A"), fact_block="facts-A", aggressive=True,
        current_user_content="current A",
    )
    p2, _ = manager.compress(
        p1, fact_block="facts-B", aggressive=True,
        current_user_content="current A",
    )
    texts = [_content_text(m.get("content")) for m in p2]
    assert sum(t.startswith(_HISTORY_MARKER) for t in texts) == 1
    assert sum(t.startswith(_FACTS_MARKER) for t in texts) == 1
    history = next(t for t in texts if t.startswith(_HISTORY_MARKER))
    assert "old A" in history  # cumulative content retained
    facts = next(t for t in texts if t.startswith(_FACTS_MARKER))
    assert "facts-B" in facts and "facts-A" not in facts


def test_compact_bounds_context_summary():
    from agent_runtime.core import _CONTEXT_SUMMARY_MAX_CHARS, AgentMemory

    memory = AgentMemory("summary-bound")
    for _ in range(30):
        for i in range(5):
            memory.add_message("user", f"m{i} " + "z" * 2_000)
        memory.compact(keep_last=1)
    assert len(memory.context_summary) <= _CONTEXT_SUMMARY_MAX_CHARS + 64


def test_calibration_uses_post_compression_estimate():
    """Provider-usage calibration must compare against what was actually sent."""
    from agent_runtime.llm_runtime import LLMRuntimeMixin

    obj = LLMRuntimeMixin()
    manager = ContextWindowManager(window=8192, reserve_output_tokens=512, safety_margin=512)
    obj._context_window_manager = lambda: manager

    class _Memory:
        conversation = []

        def retrieve(self, *args, **kwargs):
            return None

    obj.memory = _Memory()
    obj._begin_context_turn()

    messages = [{"role": "system", "content": "policy"}]
    messages += [{"role": "user", "content": "big turn " + "x" * 1_000} for _ in range(40)]
    messages.append({"role": "user", "content": "current request"})

    before = manager.usage(messages)
    packed = obj._enforce_context_budget(messages, current_user_content="current request")

    assert obj._ctx_last_meta["compressed"] is True
    assert obj._ctx_last_estimate == obj._ctx_last_meta["after_tokens"]
    assert obj._ctx_last_estimate < before


def test_context_pack_budget_tracks_model_window():
    """The packer must not cap history at a fixed 12k under a large window."""
    from agent_runtime.llm_runtime import LLMRuntimeMixin

    obj = LLMRuntimeMixin()
    assert obj._context_pack_budget() > 12_000
