"""Real browser conversation adapter, no direct model/agent/API submission.

An evaluator-owned factory supplies an isolated, logged-in Playwright Page;
fixture preparation and independent artifact collection are separate hooks.
No Playwright/browser installation, service startup or paid call occurs on import.
The current default driver is text-only. Unsupported attachment/control/event
protocols fail closed instead of silently testing an easier different task.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from user_chat_contract import (CONTRACT_VERSION, ENTRY_MODE, UserChatBlocked,
                                evidence_errors, text_hash, user_turns)
from tools.adapters.brachybot import _step_trace


# Read-only observation of the actual browser: never alter application flags,
# forge final responses or invoke sendChat/agent/tools from evaluate().
SNAPSHOT_JS = """({sid, requestId}) => {
  const active = typeof activeSessionId === 'undefined' ? '' : String(activeSessionId || '');
  const session = typeof sessions === 'undefined' ? null : sessions[sid];
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  const finals = messages.filter(m => m.request_id === requestId && m.message_kind === 'assistant_final');
  const traces = messages.filter(m => m.request_id === requestId && m.message_kind === 'execution_trace');
  const rows = Array.from(document.querySelectorAll('#chatMessages .chat-row.bot'))
    .filter(r => r.dataset.requestId === requestId && r.dataset.messageKind === 'assistant_final');
  const steps = traces.flatMap(t => t.steps || []);
  const users = messages.filter(m => m.request_id === requestId && m.type === 'user');
  const row = rows[0];
  const rendered = row?.querySelector('.chat-msg.bot-response, .chat-msg.bot');
  const visible = Boolean(row && row.getClientRects().length &&
    ((rendered?.textContent || '').trim() || row.querySelector('.chat-image-gallery img')));
  const busy = Boolean(window._chatTurnActive || window._chatStreaming || window._hiddenChatFlushRunning
    || window._chatSessionReadinessSubmission || window._pendingHiddenChats?.length
    || window._pendingVisualFinalResponses?.size || window._sessionChatStopPromises?.[sid]
    || window._sessionChatTaskStatuses?.[sid] === 'running'
    || document.getElementById('chatSendBtn')?.classList.contains('streaming'));
  const pending = steps.some(s => s.status === 'pending' || s.status === 'running');
  return {active_session: active, busy, pending, final_count: finals.length,
    dom_final_count: rows.length, final_rendered: visible, response: finals[0]?.content || '',
    user_content: users[0]?.content || '', user_message_id: users[0]?.id || '',
    assistant_message_id: finals[0]?.id || '',
    rendered_response: rendered?.innerText || '', attachments: finals[0]?.attachments || [],
    steps, error: steps.some(s => s.status === 'error' || s.status === 'cancelled')};
}"""


class BrowserChatSession:
    entry_mode = ENTRY_MODE

    def __init__(self, page, *, session_id, isolated_workspace=False, timeout_s=120,
                 execution_id=None):
        if isolated_workspace is not True or not session_id:
            raise UserChatBlocked("an evaluator-verified isolated browser workspace is required")
        if not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= 7200:
            raise ValueError("timeout_s must be positive and bounded")
        self.page = page
        self.session_id = str(session_id)
        self.isolated_workspace = True
        self.execution_id = execution_id or uuid.uuid4().hex
        self.timeout_s = timeout_s

    def _snapshot(self, request_id=""):
        return self.page.evaluate(SNAPSHOT_JS, {"sid": self.session_id, "requestId": request_id})

    def submit(self, text):
        text = text.strip()
        if not text:
            raise UserChatBlocked("empty user message")
        before = self._snapshot()
        if before["active_session"] != self.session_id or before["busy"] or before["pending"]:
            raise UserChatBlocked("wrong case or unfinished prior browser turn; do not click Stop instead of Send")
        started = time.monotonic()
        deadline = started + self.timeout_s
        requests = {}
        children = []
        snapshot = before

        def capture(request):
            if request.method != "POST" or urlsplit(request.url).path != "/api/chat":
                return
            try:
                body = request.post_data_json
            except Exception:
                return
            if not isinstance(body, dict):
                return
            if body.get("internal_followup"):
                children.append({"request_id": body.get("request_id"),
                                 "parent_request_id": body.get("parent_request_id")})
            elif body.get("message") == text and body.get("request_id"):
                # Idempotent network retries have the same request_id: one
                # user submission, not multiple independent turns.
                requests[body["request_id"]] = {k: body.get(k) for k in
                    ("request_id", "message", "user_message_id", "assistant_message_id", "internal_followup")}

        self.page.on("request", capture)
        try:
            self.page.locator("#chatInput").fill(text, timeout=self.timeout_s * 1000)
            self.page.locator("#chatSendBtn").click(timeout=max(1, deadline-time.monotonic()) * 1000)
            stable_since = None
            while time.monotonic() < deadline:
                if len(requests) > 1:
                    raise UserChatBlocked("one input dispatched multiple ordinary requests")
                request_id = next(iter(requests), "")
                snapshot = self._snapshot(request_id)
                if snapshot["active_session"] != self.session_id:
                    raise UserChatBlocked("active case changed during the benchmark turn")
                settled = (request_id and not snapshot["busy"] and not snapshot["pending"]
                           and snapshot["final_count"] == 1 and snapshot["dom_final_count"] == 1
                           and snapshot["final_rendered"]
                           and snapshot["user_content"] == text
                           and snapshot["user_message_id"] == requests[request_id]["user_message_id"]
                           and snapshot["assistant_message_id"] == requests[request_id]["assistant_message_id"])
                if settled:
                    stable_since = stable_since or time.monotonic()
                    # Let queued visual children/UI action microtasks surface;
                    # then check again, rather than treating stream EOF as final.
                    if time.monotonic() - stable_since >= .5:
                        break
                else:
                    stable_since = None
                self.page.wait_for_timeout(100)
            else:
                raise UserChatBlocked("browser final delivery timeout; no fake completion or automatic resubmission")
            sent = requests[request_id]
            receipt = {"request_id": request_id, "session_id": self.session_id,
                "input_action": "fill_chatInput_click_chatSendBtn", "input_sha256": text_hash(text),
                "network_message_sha256": text_hash(sent["message"]),
                "user_echo_sha256": text_hash(snapshot["user_content"]),
                "user_message_id": sent["user_message_id"], "assistant_message_id": sent["assistant_message_id"],
                "internal_followup": bool(sent["internal_followup"]), "browser_settled": True,
                "final_rendered": True, "final_message_count": snapshot["final_count"],
                "visual_children": [c for c in children if c["parent_request_id"] == request_id],
                "wall_clock_s": time.monotonic() - started}
            return {"response": snapshot["response"], "rendered_response": snapshot["rendered_response"],
                    "steps": snapshot["steps"], "trace": _step_trace(snapshot["steps"]),
                    "attachments": snapshot["attachments"], "entry_receipt": receipt,
                    "partial_status": "FAILED_TOOL" if snapshot["error"] else "COMPLETED"}
        except UserChatBlocked as exc:
            # Keep observed partial work. An unfinished later task must not
            # erase the first target's already delivered screenshot/answer.
            exc.observation = {"response": snapshot.get("response", ""),
                "rendered_response": snapshot.get("rendered_response", ""),
                "trace": _step_trace(snapshot.get("steps", [])), "attachments": snapshot.get("attachments", []),
                "partial_status": "BLOCKED_BY_DEPENDENCY", "browser_settled": False,
                "submitted_request_ids": list(requests), "wall_clock_s": time.monotonic()-started}
            raise
        finally:
            self.page.remove_listener("request", capture)


class UserChatAdapter:
    """Factory/fixture/collector are harness-owned, not SUT-selected hooks."""
    name = "browser-user-chat"
    entry_mode = ENTRY_MODE

    def __init__(self, session_factory, *, fixture_driver=None, collector=None, evaluator_context=None):
        self.session_factory = session_factory
        self.fixture_driver = fixture_driver
        self.collector = collector
        self.evaluator_context = evaluator_context
        self.execution_evidence = None

    def observe(self, task, initial_state):
        self.execution_evidence = None
        turns = user_turns(task)  # reject unsupported protocols before any submission
        if (task.get("protocol") or {}).get("events"):
            raise UserChatBlocked("environment events require an explicit UI fixture/event driver")
        if initial_state and self.fixture_driver is None:
            raise UserChatBlocked("isolated fixture driver missing; never run against an unrelated patient case")
        scope = self.fixture_driver(task, initial_state) if self.fixture_driver else None
        session = self.session_factory(scope)
        if not isinstance(session, BrowserChatSession):
            raise UserChatBlocked("factory must supply BrowserChatSession, not a raw model/agent callback")
        delivered = []
        try:
            # Validate the whole schedule first. Never leak future user turns
            # or expected assistant/tool messages to the browser/model.
            budget = (task.get("protocol") or {}).get("budget") or {}
            if budget.get("turns", 0) > 0 and len(turns) > budget["turns"]:
                raise UserChatBlocked("dialogue exceeds the declared user-turn budget")
            start = time.monotonic()
            for turn in turns:
                limit = budget.get("wall_clock_s", 0)
                if limit > 0:
                    remaining = limit - (time.monotonic() - start)
                    if remaining <= 0:
                        raise UserChatBlocked("dialogue wall-clock budget exhausted")
                    session.timeout_s = min(session.timeout_s, remaining)
                delivered.append(session.submit(turn["text"]))
            output = {"response": delivered[-1]["response"],
                "trace": [entry for r in delivered for entry in r["trace"]],
                "turn_responses": [{"user": t["text"], **r} for t, r in zip(turns, delivered)],
                "attachments": [a for r in delivered for a in r["attachments"]],
                "partial_status": delivered[-1]["partial_status"], "wall_clock_s": time.monotonic()-start}
            output["tool_calls"] = len(output["trace"])
            output["tool_budget_verified"] = False  # a complete independent execution audit is still needed
            if budget.get("tool_calls", 0) > 0 and output["tool_calls"] > budget["tool_calls"]:
                raise UserChatBlocked("observed tool calls exceeded the task budget")
            self.execution_evidence = {"contract_version": CONTRACT_VERSION, "entry_mode": ENTRY_MODE,
                "execution_id": session.execution_id, "session_id": session.session_id,
                "isolated_workspace": session.isolated_workspace,
                "turns": [r["entry_receipt"] for r in delivered]}
            errors = evidence_errors(self.execution_evidence, task)
            if errors:
                raise UserChatBlocked(", ".join(errors))
            if self.collector is not None:
                collected = self.collector(session, context={"task": task, "initial_state": initial_state,
                    "execution_id": session.execution_id, "delivered": output})
                # Preserve the actual delivered response; a collector cannot
                # replace it with a reference answer or a self-reported claim.
                output = {**collected, **output}
            return output
        except UserChatBlocked as exc:
            partial = exc.observation or {}
            exc.observation = {**partial, "turn_responses": delivered,
                "trace": [t for r in delivered for t in r["trace"]] + partial.get("trace", []),
                "attachments": [a for r in delivered for a in r["attachments"]] + partial.get("attachments", []),
                "partial_status": "BLOCKED_BY_DEPENDENCY"}
            raise
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()


def load_factory(spec):
    module, separator, function = str(spec).partition(":")
    if not separator or not function:
        raise UserChatBlocked("a trusted browser session factory module:function is required")
    return getattr(importlib.import_module(module), function)


def from_environment():
    factory = os.environ.get("BRACHYBENCH_BROWSER_SESSION_FACTORY", "")
    if not factory:
        raise UserChatBlocked("BRACHYBENCH_BROWSER_SESSION_FACTORY is not configured")
    adapter = UserChatAdapter(load_factory(factory))
    fixture = os.environ.get("BRACHYBENCH_BROWSER_FIXTURE_DRIVER")
    if fixture:
        adapter.fixture_driver = load_factory(fixture)
    return adapter
