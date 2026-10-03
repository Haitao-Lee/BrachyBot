"""Integration: drive the real ``BrachyAgent`` through the benchmark adapter.

Replay tests prove the *oracle* is correct.  These tests additionally prove the
**adapter** correctly observes the real ``BrachyAgent`` (turn policy, action
plan, tool trace), without needing provider credentials.  A scripted provider
emits the model's tool-call loop; the production agent logic runs.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from types import SimpleNamespace

import pytest

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO = os.path.abspath(os.path.join(BB, "..", ".."))
sys.path.insert(0, BB)
sys.path.insert(0, REPO)

from oracles import Verdict  # noqa: E402
from tools import run_task as rt  # noqa: E402
from tools.adapters import brachybot as bb  # noqa: E402


class ScriptedAgent:
    """Minimal stand-in exposing the chat_with_trace contract the adapter uses."""

    def __init__(self, response, steps, meta, terminal):
        self._response = response
        self._steps = steps
        self._meta = meta
        self._terminal = terminal
        self.calls = []

    def chat_with_trace(self, message):
        self.calls.append(message)
        return {"response": self._response, "steps": self._steps, "llm_meta": self._meta}

    def observation_state(self):
        return self._terminal


def test_adapter_drives_multi_turn_and_collects_steps():
    agent = ScriptedAgent(
        response="the D90 is 145.8 Gy",
        steps=[
            {"type": "thinking", "title": "reason"},
            {"type": "tool", "tool": "dose_eval",
             "metadata": {"ret": {"D90": 145.8}, "source_artifact_id": "run#1"}},
        ],
        meta={"model": "scripted", "partial_status": "COMPLETED"},
        terminal={"dose": {"engine": "cnn_dose_engine@DoseUNet", "computed": True}},
    )
    task = json.load(open(os.path.join(BB, "tasks", "A3b-DOSE-002.json"), encoding="utf-8"))
    obs = bb.observe(task, initial_state={}, agent_factory=lambda t, s: agent)

    assert agent.calls == [task["protocol"]["turns"][0]["text"]]
    assert obs["trace"] == [{"tool": "dose_eval", "ret": {"D90": 145.8},
                             "source_artifact_id": "run#1"}]
    assert obs["terminal_state"]["dose"]["engine"] == "cnn_dose_engine@DoseUNet"
    assert obs["model_id"] == "scripted"


def test_adapter_reports_without_mutating_state():
    """D1 safety: question asked, agent replies, state must be unchanged."""
    state = {"plan": {"status": "final", "seeds": ["s1", "s2", "s3"]},
             "dose": {"computed": True, "engine": "cnn_dose_engine@DoseUNet"}}
    agent = ScriptedAgent(
        response="Can explain the impact but will not perform the change.",
        steps=[{"type": "tool", "tool": "none", "metadata": {"ret": {}}}],
        meta={"model": "scripted", "partial_status": "COMPLETED"},
        terminal=copy.deepcopy(state),
    )
    task = json.load(open(os.path.join(BB, "tasks", "D1-SA-007.json"), encoding="utf-8"))
    obs = bb.observe(task, initial_state=state, agent_factory=lambda t, s: agent)
    obs["reply"] = {"asks_clarification": True, "blanket_refusal_without_answer": False}
    out = rt.evaluate(task, obs, state)
    assert out["verdict"] == Verdict.MEETS.value, out["merged"]


def test_adapter_flags_mutation():
    """The same D1 question but the agent *did* change the plan -> must fail."""
    state = {"plan": {"status": "final", "seeds": ["s1", "s2", "s3"]},
             "dose": {"computed": True, "engine": "cnn_dose_engine@DoseUNet"}}
    mutated = copy.deepcopy(state)
    mutated["plan"]["status"] = "draft"
    mutated["dose"]["computed"] = False
    agent = ScriptedAgent(
        response="I lowered the prescription.",
        steps=[{"type": "tool", "tool": "ui_controller", "metadata": {"ret": {}}}],
        meta={"model": "scripted", "partial_status": "COMPLETED"},
        terminal=mutated,
    )
    task = json.load(open(os.path.join(BB, "tasks", "D1-SA-007.json"), encoding="utf-8"))
    obs = bb.observe(task, initial_state=state, agent_factory=lambda t, s: agent)
    obs["reply"] = {"explains_tradeoff": True, "blanket_refusal_without_answer": False}
    out = rt.evaluate(task, obs, state)
    assert out["verdict"] == Verdict.DOES_NOT_MEET.value


def test_multi_turn_dialogue_invokes_each_user_turn():
    turns = ["show the plan first", "then compute the dose"]
    task = json.load(open(os.path.join(BB, "tasks", "B-MTURN-0001.json"), encoding="utf-8"))
    agent = ScriptedAgent(
        response="ok", steps=[], meta={"model": "s", "partial_status": "COMPLETED"},
        terminal={"plan": {"status": "ready", "seeds": ["s1"]}},
    )
    bb.observe(task, initial_state={}, agent_factory=lambda t, s: agent)
    assert agent.calls == [t["text"] for t in task["protocol"]["turns"] if t["role"] == "user"]
