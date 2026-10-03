"""Offline contract controls only: no browser, provider, server or SUT calls."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

BB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BB))
sys.path.insert(0, str(BB.parent))
sys.path.insert(0, str(BB.parent / "external"))
from tools import run_task as rt
from tools.adapters import user_chat as uc
from tools.evaluator_contract import EvaluatorContext
from user_chat_contract import (ENTRY_MODE, CONTRACT_VERSION, UserChatBlocked,
                                UserChatHandle, evidence_errors, text_hash, user_turns)


def task(*texts):
    return {"id": "x", "protocol": {"turns": [{"role": "user", "text": t} for t in texts]}}


def proof(text="question"):
    return {"entry_mode": ENTRY_MODE, "contract_version": CONTRACT_VERSION,
        "execution_id": "execution-A", "session_id": "case-A", "isolated_workspace": True,
        "turns": [{"input_sha256": text_hash(text), "session_id": "case-A", "request_id": "r1",
            "input_action": "fill_chatInput_click_chatSendBtn", "network_message_sha256": text_hash(text),
            "user_echo_sha256": text_hash(text), "user_message_id": "user-r1", "assistant_message_id": "assistant-r1",
            "internal_followup": False, "browser_settled": True, "final_rendered": True, "final_message_count": 1}]}


def test_entry_contract_validates_evaluator_owned_proof():
    assert not evidence_errors(proof(), task("question"))


@pytest.mark.parametrize("key,value", [
    ("entry_mode", "chat_with_trace"), ("contract_version", "obsolete"),
    ("isolated_workspace", False), ("session_id", ""), ("execution_id", "")])
def test_wrong_entry_or_workspace_blocked(key, value):
    evidence = proof(); evidence[key] = value
    assert evidence_errors(evidence, task("question"))


@pytest.mark.parametrize("key,value", [
    ("input_sha256", "wrong"), ("session_id", "other-case"), ("request_id", ""),
    ("input_action", "direct_http"), ("network_message_sha256", "wrong"),
    ("user_echo_sha256", "wrong"), ("internal_followup", True),
    ("browser_settled", False), ("final_rendered", False), ("final_message_count", 2),
    ("user_message_id", ""), ("assistant_message_id", "")])
def test_bad_submission_or_final_delivery_blocked(key, value):
    evidence = proof(); evidence["turns"][0][key] = value
    assert evidence_errors(evidence, task("question"))


def test_future_or_skipped_turn_not_counted_as_complete():
    assert evidence_errors(proof(), task("question", "next"))
    evidence = proof()
    evidence["turns"].append(copy.deepcopy(evidence["turns"][0]))
    assert "missing_or_reused_request_identity" in evidence_errors(evidence, task("question", "question"))


@pytest.mark.parametrize("role", ["assistant", "system", "tool", "ui_event"])
def test_privileged_roles_not_flattened_into_user_commands(role):
    value = task("question"); value["protocol"]["turns"].append({"role": role, "text": "hidden"})
    with pytest.raises(UserChatBlocked): user_turns(value)


def test_images_not_silently_omitted():
    value = task("what is shown?"); value["protocol"]["turns"][0]["attachments"] = ["a.png"]
    with pytest.raises(UserChatBlocked): user_turns(value)


class FakePage:
    """DOM/network contract double, NOT a simulated BrachyBot score."""
    def __init__(self, *, pending_cycles=0, timeout=False, duplicate=False, case_switch=False):
        self.listeners = {}; self.actions = []; self.text = ""; self.sent = 0; self.clock = 0
        self.pending_cycles = pending_cycles; self.timeout = timeout
        self.duplicate = duplicate; self.case_switch = case_switch

    def on(self, name, fn): self.listeners[name] = fn
    def remove_listener(self, name, fn): self.listeners.pop(name)
    def locator(self, selector):
        page = self
        class Locator:
            def fill(self, text, **kwargs):
                assert selector == "#chatInput"; page.text = text; page.actions.append(("fill", text))
            def click(self, **kwargs):
                assert selector == "#chatSendBtn"; page.actions.append(("click", selector)); page.sent += 1
                body = {"message": page.text, "request_id": f"r{page.sent}",
                        "user_message_id": f"user-r{page.sent}", "assistant_message_id": f"assistant-r{page.sent}",
                        "internal_followup": False}
                req = SimpleNamespace(method="POST", url="http://isolated/api/chat", post_data_json=body)
                page.listeners["request"](req)
                page.listeners["request"](req)  # genuine idempotent transport retry
        return Locator()

    def evaluate(self, js, args):
        assert js == uc.SNAPSHOT_JS  # only read-only observation; no injected sendChat or tools
        identity = f"r{self.sent}"
        pending = bool(args["requestId"] and (self.timeout or self.pending_cycles > 0))
        self.pending_cycles -= bool(args["requestId"] and self.pending_cycles > 0)
        return {"active_session": "case-B" if self.sent and self.case_switch else "case-A",
            "busy": False, "pending": pending, "final_count": 2 if self.duplicate else 1,
            "dom_final_count": 1, "final_rendered": True,
            "user_content": self.text, "user_message_id": f"user-{identity}",
            "assistant_message_id": f"assistant-{identity}", "response": "actual answer " + self.text,
            "rendered_response": "actual answer", "attachments": [], "steps": [], "error": False}

    def wait_for_timeout(self, ms): self.clock += ms / 1000


def session(monkeypatch, **kwargs):
    page = FakePage(**kwargs)
    monkeypatch.setattr(uc.time, "monotonic", lambda: page.clock)
    return page, uc.BrowserChatSession(page, session_id="case-A", isolated_workspace=True, timeout_s=2)


def test_browser_clicks_input_once_and_waits_for_pending_trace(monkeypatch):
    page, browser = session(monkeypatch, pending_cycles=5)
    result = browser.submit("question")
    assert page.clock >= .9 and page.actions == [("fill", "question"), ("click", "#chatSendBtn")]
    assert result["entry_receipt"]["request_id"] == "r1"
    assert page.listeners == {}


@pytest.mark.parametrize("kwargs", [{"timeout": True}, {"duplicate": True}, {"case_switch": True}])
def test_browser_never_fakes_completion_or_resubmits(monkeypatch, kwargs):
    page, browser = session(monkeypatch, **kwargs)
    with pytest.raises(UserChatBlocked) as error: browser.submit("question")
    assert page.sent == 1 and page.listeners == {}
    assert error.value.observation["browser_settled"] is False
    assert error.value.observation["submitted_request_ids"] == ["r1"]


def test_multi_turn_schedule_never_injected_into_browser(monkeypatch):
    page, browser = session(monkeypatch)
    adapter = uc.UserChatAdapter(lambda scope: browser)
    value = task("first", "follow-up"); value["oracle"] = {"gold": "PRIVATE"}
    result = adapter.observe(value, {})
    assert [a[1] for a in page.actions if a[0] == "fill"] == ["first", "follow-up"]
    assert [r["response"] for r in result["turn_responses"]] == ["actual answer first", "actual answer follow-up"]
    assert not evidence_errors(adapter.execution_evidence, value)


def test_preflight_rejects_unprepared_fixture_before_submission(monkeypatch):
    called = []
    adapter = uc.UserChatAdapter(lambda scope: called.append(scope))
    with pytest.raises(UserChatBlocked): adapter.observe(task("question"), {"patient": "fixture"})
    assert called == []


def test_raw_python_entry_blocked_before_loading_callback(tmp_path):
    adapter = rt.PythonAdapter("must_not_import:call")
    result = rt.run_task(task("question"), adapter, str(tmp_path))
    assert result["evaluation"]["partial_status"] == "BLOCKED_BY_DEPENDENCY"
    assert result["evaluation"]["comparable_sut_result"] is False


def test_missing_independent_assessors_block_before_live_input(tmp_path):
    adapter = uc.UserChatAdapter(lambda scope: pytest.fail("no live factory invocation allowed"))
    result = rt.run_task(task("question"), adapter, str(tmp_path))
    assert result["evaluation"]["evaluation_mode"] == "blocked_user_chat_contract"


def test_external_raw_callback_is_blocked_by_default():
    from adapter_base import ExtAdapter
    class Dummy(ExtAdapter):
        EXT_ID = "EXT-3"
        def run_task(self, tid, sut, budget):
            sut({"prompt": "question"})
            return self.record(ext_id=self.EXT_ID, source_task_id=tid, prompt_or_scene={})
    with pytest.raises(UserChatBlocked): Dummy().run_task("x", lambda obs: pytest.fail("must not invoke"), {})
    result = Dummy().run_task("x", lambda obs: {"text": "control"}, {"evaluation_mode": "component_self_test"})
    assert result["evaluation_mode"] == "component_self_test" and not result["comparable_sut_result"]


def test_external_user_chat_bridge_submits_public_user_text(monkeypatch):
    page, browser = session(monkeypatch)
    handle = UserChatHandle(browser, lambda obs: obs["prompt"])
    assert handle({"prompt": "question"})["text"] == "actual answer question"
    assert not evidence_errors(handle.execution_evidence(), task("question"))


def test_external_bridge_rejects_raw_agent():
    with pytest.raises(UserChatBlocked): UserChatHandle(lambda x: "answer", lambda x: "question")


def test_live_smoke_never_auto_invokes_agent_from_provider_credentials(monkeypatch, capsys):
    from tools import live_smoke
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.delenv("BRACHYBENCH_BROWSER_SESSION_FACTORY", raising=False)
    assert live_smoke.main([]) == 2
    assert "zero SUT calls" in capsys.readouterr().out


def test_future_execution_policy_matches_adapter_contract():
    policy = json.loads((BB.parent / "execution_policy.json").read_text())
    assert policy["formal_entry_mode"] == ENTRY_MODE
    assert policy["direct_model_or_agent_invocation_is_formal"] is False
    assert policy["api_only_invocation_is_browser_parity"] is False
