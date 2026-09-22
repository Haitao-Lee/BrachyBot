"""A tool turn that runs out of rounds must still answer the user.

Regression: a knowledge question whose every provider round was a tool call
(web_search/web_fetch) exhausted ``max_iterations`` with no answer text. The
empty-response fallback then emitted the metadata-only evidence summary
("已完成资料检索…" / "已读取来源页面，但当前尚未生成综合回答。") which lists
sources but never answers the question. The runtime must give the model one
final, tool-free synthesis round before that last-resort summary.
"""

from types import SimpleNamespace


def _runtime(router):
    from agent_runtime.llm_runtime import LLMRuntimeMixin

    runtime = object.__new__(LLMRuntimeMixin)
    runtime.brain_router = router
    runtime._record_context_usage = lambda usage: None
    return runtime


class _RecordingRouter:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def chat_messages(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


_WEB_STEP = {
    "type": "tool",
    "tool": "web_search",
    "status": "done",
    "result": "## 搜索结果\n- Steve Jobs and Pancreatic Cancer\n来源: https://example.org/a",
}


def test_tool_turn_without_model_text_synthesizes_instead_of_listing_sources():
    router = _RecordingRouter(
        SimpleNamespace(
            content=(
                "乔布斯患的是胰腺神经内分泌肿瘤，2004 年接受了胰十二指肠切除术"
                "（Whipple 手术），2009 年因肝转移接受了肝移植。"
            ),
            usage={"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            latency_ms=1200.0,
            finish_reason="stop",
        )
    )
    runtime = _runtime(router)

    text, meta = runtime._resolve_tool_turn_response(
        [_WEB_STEP],
        [{"role": "user", "content": "乔布斯是胰腺癌患者吗，采用了哪种治疗"}],
        "zh",
        "乔布斯是胰腺癌患者吗，采用了哪种治疗",
        capture_pending=False,
    )

    assert "Whipple" in text
    assert "已完成资料检索" not in text
    assert "尚未生成综合回答" not in text
    assert meta.get("llm_calls") == 1
    assert meta.get("usage", {}).get("total_tokens") == 140
    # The synthesis round must run with tools disabled.
    assert router.calls and router.calls[-1]["tools"] == []


def test_synthesis_rejects_placeholder_and_tool_call_output():
    for bad in (
        "Tools executed. Check the execution trace above for results.",
        '```tool_call\n{"tool": "web_search", "params": {}}\n```',
    ):
        router = _RecordingRouter(
            SimpleNamespace(content=bad, usage={}, latency_ms=0.0)
        )
        runtime = _runtime(router)

        text, meta = runtime._resolve_tool_turn_response(
            [_WEB_STEP],
            [{"role": "user", "content": "乔布斯是胰腺癌患者吗"}],
            "zh",
            "乔布斯是胰腺癌患者吗",
            capture_pending=False,
        )

        # Still a non-empty honest fallback, but no synthesis was accepted.
        assert text
        assert meta.get("llm_calls", 0) == 0
        assert "尚未生成综合回答" in text or "已完成资料检索" in text


def test_synthesis_provider_error_falls_back_to_honest_summary():
    router = _RecordingRouter(error=RuntimeError("provider down"))
    runtime = _runtime(router)

    text, meta = runtime._resolve_tool_turn_response(
        [_WEB_STEP],
        [{"role": "user", "content": "乔布斯是胰腺癌患者吗"}],
        "zh",
        "乔布斯是胰腺癌患者吗",
        capture_pending=False,
    )

    assert text
    assert meta.get("llm_calls", 0) == 0
    assert "已完成资料检索" in text


def test_no_synthesis_without_successful_evidence():
    router = _RecordingRouter(
        SimpleNamespace(content="should not be used", usage={}, latency_ms=0.0)
    )
    runtime = _runtime(router)
    failed_step = {
        "type": "tool",
        "tool": "web_fetch",
        "status": "error",
        "result": "HTTP 404",
    }

    text, meta = runtime._resolve_tool_turn_response(
        [failed_step],
        [{"role": "user", "content": "乔布斯是胰腺癌患者吗"}],
        "zh",
        "乔布斯是胰腺癌患者吗",
        capture_pending=False,
    )

    assert router.calls == []
    assert meta.get("llm_calls", 0) == 0
    assert text


def test_capture_pending_ack_is_never_replaced_by_synthesis():
    router = _RecordingRouter(
        SimpleNamespace(content="synthesized answer", usage={}, latency_ms=0.0)
    )
    runtime = _runtime(router)
    steps = [
        {
            "type": "tool",
            "tool": "ui_screenshot",
            "status": "done",
            "result": "已创建截图计划，正在捕获目标视图。",
            "metadata": {"internal_only": True, "user_visible": False},
        }
    ]

    text, meta = runtime._resolve_tool_turn_response(
        steps,
        [{"role": "user", "content": "截图告知"}],
        "zh",
        "截图告知",
        capture_pending=True,
    )

    assert text
    assert router.calls == []
    assert meta.get("llm_calls", 0) == 0
