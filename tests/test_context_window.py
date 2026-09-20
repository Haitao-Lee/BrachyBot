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


def test_compression_meta_reports_used_tokens_and_ratio():
    """A compressed snapshot must still describe the current context size.

    Regression: ``as_dict`` omitted ``used_tokens``/``ratio``, so the indicator
    fell back to 0/<window> immediately after an automatic compression.
    """
    from agent_runtime.context_window import CompressionMeta

    meta = CompressionMeta(
        window=1_000,
        target_tokens=800,
        trigger_ratio=0.85,
        before_tokens=2_000,
        after_tokens=700,
        ratio_before=2.0,
        ratio_after=0.7,
        compressed=True,
    )
    as_dict = meta.as_dict()
    assert as_dict["used_tokens"] == 700
    assert as_dict["ratio"] == 0.7


def test_context_status_is_never_empty_for_a_nonempty_session():
    """The indicator must not read 0/<window> before the first snapshot.

    Regression: ``context_status`` returned only window/target/trigger whenever
    ``_ctx_last_meta`` was unset (before a turn, after a direct-tool turn, or on
    a freshly resolved case agent), which the UI rendered as 0/1048576.
    """
    from agent_runtime.llm_runtime import LLMRuntimeMixin

    obj = LLMRuntimeMixin()
    manager = ContextWindowManager(window=1_048_576)
    obj._context_window_manager = lambda: manager

    class Memory:
        conversation = [{"role": "user", "content": "x" * 400} for _ in range(10)]
        context_summary = ""

        def retrieve(self, *args, **kwargs):
            return None

    obj.memory = Memory()
    obj._begin_context_turn()

    status = obj.context_status()
    assert status["window"] == 1_048_576
    assert status["used_tokens"] > 0
    assert status["ratio"] > 0


def test_context_status_prefers_measured_provider_usage():
    """The last real provider prompt_tokens is the most accurate context size."""
    from agent_runtime.llm_runtime import LLMRuntimeMixin

    obj = LLMRuntimeMixin()
    manager = ContextWindowManager(window=1_048_576)
    obj._context_window_manager = lambda: manager

    class Memory:
        conversation = []
        context_summary = ""

        def retrieve(self, *args, **kwargs):
            return None

    obj.memory = Memory()
    obj._begin_context_turn()
    obj._record_context_usage({"prompt_tokens": 4_321})

    status = obj.context_status()
    assert status["used_tokens"] == 4_321
    assert status["ratio"] > 0


def test_context_indicator_uses_durable_context_not_tool_peak():
    """The ring must not report a transient tool-result peak as the context.

    A turn's later provider calls append tool results, so their prompt_tokens
    can be far larger than the durable conversation. Reporting the peak made
    the next turn look smaller once the transient results were gone.
    """
    from agent_runtime.llm_runtime import LLMRuntimeMixin

    obj = LLMRuntimeMixin()
    manager = ContextWindowManager(window=1_048_576)
    obj._context_window_manager = lambda: manager

    class Memory:
        conversation = []
        context_summary = ""

        def retrieve(self, *args, **kwargs):
            return None

    obj.memory = Memory()
    obj._begin_context_turn()
    obj._record_context_usage({"prompt_tokens": 30_000})  # first call: durable
    obj._record_context_usage({"prompt_tokens": 39_166})  # later call: tool peak
    assert obj.context_status()["used_tokens"] == 30_000


def test_context_indicator_grows_monotonically_across_turns():
    """A growing conversation must never make the ring shrink."""
    from agent_runtime.llm_runtime import LLMRuntimeMixin

    obj = LLMRuntimeMixin()
    manager = ContextWindowManager(window=1_048_576)
    obj._context_window_manager = lambda: manager

    class Memory:
        conversation = []
        context_summary = ""

        def retrieve(self, *args, **kwargs):
            return None

    obj.memory = Memory()

    obj._begin_context_turn()
    obj._record_context_usage({"prompt_tokens": 30_000})
    obj._record_context_usage({"prompt_tokens": 39_166})
    first = obj.context_status()["used_tokens"]

    obj._begin_context_turn()
    obj._record_context_usage({"prompt_tokens": 33_000})
    obj._record_context_usage({"prompt_tokens": 45_000})
    second = obj.context_status()["used_tokens"]

    assert first == 30_000
    assert second == 33_000
    assert second > first


def test_context_status_exposes_scope_and_turn_totals():
    """The status must label both quantities so the UI can distinguish them.

    ``used_tokens`` is the current context (next request's prompt); the turn
    totals are the cumulative usage across every model call in the turn.
    """
    from agent_runtime.llm_runtime import LLMRuntimeMixin

    obj = LLMRuntimeMixin()
    manager = ContextWindowManager(window=1_048_576)
    obj._context_window_manager = lambda: manager

    class Memory:
        conversation = []
        context_summary = ""

        def retrieve(self, *args, **kwargs):
            return None

    obj.memory = Memory()
    obj._begin_context_turn()
    obj._record_context_usage(
        {"prompt_tokens": 1_000, "completion_tokens": 100, "total_tokens": 1_100}
    )
    obj._record_context_usage(
        {"prompt_tokens": 3_000, "completion_tokens": 200, "total_tokens": 3_200}
    )

    status = obj.context_status()
    assert status["scope"] == "current_context"
    assert status["used_tokens"] == 1_000  # durable first call
    assert status["turn_input_tokens"] == 4_000
    assert status["turn_output_tokens"] == 300
    assert status["turn_total_tokens"] == 4_300
    assert status["llm_calls"] == 2
    assert status["measured"] is True
    assert status["estimated"] is False




def test_context_status_drops_stale_usage_after_manual_compression():
    """Manual compression must not keep reporting the pre-compression size."""
    from agent_runtime.core import AgentMemory
    from agent_runtime.llm_runtime import LLMRuntimeMixin

    obj = LLMRuntimeMixin()
    manager = ContextWindowManager(window=1_048_576)
    obj._context_window_manager = lambda: manager
    memory = AgentMemory("ctx-status-compress")
    for i in range(12):
        memory.add_message("user", f"turn {i} " + "y" * 200)
    obj.memory = memory
    obj._ctx_last_prompt_tokens = 999_999

    obj.compress_context_now()

    status = obj.context_status()
    assert 0 < status["used_tokens"] < 999_999
