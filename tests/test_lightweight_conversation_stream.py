"""Streaming contract for the low-risk conversational (small-talk) path.

A greeting must paint token-by-token: the previous blocking provider call made
the browser wait for the complete generation before the first character
appeared, which read as a ~25 s "request analysis" stall even though the local
intent classifier itself is instant.
"""
from __future__ import annotations

import types
from pathlib import Path
from types import SimpleNamespace

from agent_runtime.chat_workflows import ChatWorkflowMixin

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


class _StubRouter:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.calls = []

    def chat_messages_stream(self, messages=None, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})
        for chunk in self._chunks:
            yield chunk


def _build_agent(chunks, *, language="zh"):
    agent = SimpleNamespace(
        _active_trace_language=language,
        _active_turn_context={},
        _active_turn_language_info=None,
        brain_router=_StubRouter(chunks),
        memory=SimpleNamespace(conversation=[]),
        _turn_timings={},
        _turn_started_at=0.0,
        _clean_response_text=lambda text: text,
        _small_talk_fallback_response=lambda message, lang: "本地问候回复",
        _current_llm_unavailable_message=lambda: "AI 语言服务不可用",
    )
    agent._run_lightweight_conversation_stream = types.MethodType(
        ChatWorkflowMixin._run_lightweight_conversation_stream, agent
    )
    return agent


def _run(agent, message="你好"):
    def yield_event(event_type, data):
        # The real SSE transport serializes each event when it is yielded;
        # copy here so a later in-place step update cannot rewrite history.
        return ("sse", event_type, dict(data))

    events = list(
        agent._run_lightweight_conversation_stream(message, [], [0], yield_event)
    )
    text_chunks = [data["text"] for kind, name, data in events if kind == "sse" and name == "text_chunk"]
    steps = [data for kind, name, data in events if kind == "sse" and name == "step"]
    result = next((event for event in events if isinstance(event, dict) and event.get("type") == "_result"), None)
    return text_chunks, steps, result


def _final_chunk(text, usage=None):
    return {
        "type": "final",
        "content": text,
        "finish_reason": "stop",
        "tool_calls": None,
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def test_lightweight_conversation_streams_text_before_the_final_result():
    agent = _build_agent(["您", "好！很高兴", "为您服务。", _final_chunk("")])
    text_chunks, steps, result = _run(agent)

    assert text_chunks == ["您", "好！很高兴", "为您服务。"]
    assert steps[0]["title"] == "LLM 调用 1"
    assert steps[0]["status"] == "pending"
    assert steps[-1]["status"] == "done"
    assert steps[-1]["content"] == "已生成回复"
    assert result is not None
    assert result["response"] == "您好！很高兴为您服务。"
    meta = result["llm_meta"]
    assert meta["llm_calls"] == 1
    assert meta["route"] == "lightweight_conversation"
    assert meta["usage"]["total_tokens"] == 15
    # The router must be called through the streaming provider contract with
    # no tool schemas, so a greeting never waits for the full generation.
    call = agent.brain_router.calls[0]
    assert call["tools"] is None


def test_lightweight_conversation_publishes_non_streaming_provider_content():
    agent = _build_agent([_final_chunk("整段回复")])
    text_chunks, _steps, result = _run(agent)

    assert text_chunks == ["整段回复"]
    assert result["response"] == "整段回复"


def test_lightweight_conversation_error_uses_the_local_fallback():
    agent = _build_agent([{"type": "error", "content": "Error: upstream 500"}])
    text_chunks, steps, result = _run(agent)

    assert text_chunks == []
    assert steps[-1]["title"] == "本地回复"
    assert result["response"] == "本地问候回复"
    assert result["llm_meta"]["route"] == "local_small_talk_fallback"


def test_request_placeholder_reports_connection_and_preparation_phases():
    chat_todo = _read("web/app/static/js/brachybot-chat-todo.js")
    # The optimistic row no longer claims that analysis is running while the
    # browser is only waiting for the task handshake and case-context prep.
    assert "'Connecting & preparing'" in chat_todo
    assert "Connecting to the server..." in chat_todo
    assert "Connected; preparing the case context..." in chat_todo
    assert "'Request analysis'" not in chat_todo
