"""Contracts for live LLM health reporting.

A configured provider is not necessarily a working one: stale credentials,
a wrong endpoint, or an upstream outage all produce a local fallback answer.
The Brain indicator (and /api/status) must report that failure instead of
staying green because a provider object exists.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _fake_chunk(text: str):
    delta = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason="stop")
    return SimpleNamespace(choices=[choice], usage=None)


class _FakeClient:
    def __init__(self, fail: bool):
        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)
        self._fail = fail

    def _create(self, **_kwargs):
        if self._fail:
            raise RuntimeError("401 Invalid API key")
        return iter([_fake_chunk("hi")])


def test_provider_health_tracks_stream_failure_and_recovery(monkeypatch):
    from brain.providers.generic_openai_compat import GenericOpenAICompatLLM

    llm = GenericOpenAICompatLLM(
        api_key="unit-test-key",
        model="unit-test-model",
        base_url="https://unit.test/v1",
        max_retries=0,
    )
    assert llm.llm_health is None

    monkeypatch.setattr(llm, "_get_client", lambda: _FakeClient(fail=True))
    failing = list(llm.chat_messages_stream([{"role": "user", "content": "hi"}]))
    assert failing[-1]["type"] == "error"
    assert llm.llm_health is False

    monkeypatch.setattr(llm, "_get_client", lambda: _FakeClient(fail=False))
    recovered = list(llm.chat_messages_stream([{"role": "user", "content": "hi"}]))
    assert recovered[-1]["type"] == "final"
    assert llm.llm_health is True


def test_router_health_follows_default_provider():
    from brain.core.router import LLMRouter

    class _Provider:
        llm_health = False

    router = object.__new__(LLMRouter)
    router.providers = {"generic": _Provider()}
    router.default_provider = "generic"
    assert router.llm_health is False

    router.providers = {}
    assert router.llm_health is None


def test_server_and_frontend_surfaces_carry_machine_readable_health():
    agent = read("AgenticSys.py")
    base = read("brain/core/base.py")
    runtime = read("agent_runtime/llm_runtime.py")
    workflows = read("agent_runtime/chat_workflows.py")
    routes = read("web/routes/planning_routes.py")
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    chat = read("web/app/static/js/brachybot-chat-todo.js")

    # Provider-level liveness plus a status string that distinguishes
    # "configured but failing" from "no provider at all".
    assert "def llm_health" in base
    assert "def _record_llm_error" in base
    assert "def llm_health" in read("brain/core/router.py")
    assert "def brain_state" in agent
    assert 'return "offline"' in agent
    # The stale AUTH_TOKEN fallback must announce itself at startup.
    assert "ANTHROPIC_AUTH_TOKEN fallback" in agent

    # Every status payload that reports brain availability also reports the
    # live state, so the UI never has to guess.
    assert routes.count("brain_state") >= 3
    assert '"code"] = "llm_unavailable"' in runtime or "'code'] = 'llm_unavailable'" in runtime
    assert 'thinking_step["code"] = "llm_unavailable"' in workflows

    # Frontend: string states are accepted and the SSE stream flips the chip.
    assert "normalized === 'online'" in ui_api
    assert "status.brain_state ?? status.brain_available" in ui_api
    assert "window.updateBrainStatusIndicator(false, 'llm-unavailable')" in chat
    assert "window.updateBrainStatusIndicator(true, 'llm-response')" in chat
