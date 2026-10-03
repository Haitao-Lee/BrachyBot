"""BrachyBot component adapter (not a formal user-chat benchmark entry).

Since 2026-10-04 formal evaluations use adapters.user_chat. This direct
chat_with_trace adapter remains only for deterministic component regression.

Drives the in-repo agent through its public ``chat_with_trace`` entry point and
translates the returned execution trace into the benchmark's observation dict.

The agent is **injected** (``agent_factory``) so that:

* a real run passes the project's real ``BrachyAgent``;
* CI passes a scripted agent double and exercises the translation and the
  whole scoring pipeline deterministically, without provider credentials.

Contract of ``agent_factory(task, initial_state) -> agent``: the returned
object must expose ``chat_with_trace(message) -> {"response", "steps",
"llm_meta"}`` (the BrachyBot turn API), and optionally ``observation_state()``
returning the terminal CWS.  Anything the agent does *not* expose stays empty
-- a missing field must surface as an evidence gap, never as a silent pass.
"""

from __future__ import annotations

import importlib
import os
import time
from typing import Any, Callable, Dict, Optional, Sequence

_FACTORY: Optional[Callable] = None


def set_agent_factory(factory: Optional[Callable]) -> None:
    """Register the process-wide agent factory (used by tests and real runs)."""
    global _FACTORY
    _FACTORY = factory


def _resolve_factory(agent_factory: Optional[Callable]) -> Callable:
    if agent_factory is not None:
        return agent_factory
    if _FACTORY is not None:
        return _FACTORY
    spec = os.environ.get("BRACHYBOT_AGENT_FACTORY")
    if spec:
        module_name, _, func_name = spec.partition(":")
        return getattr(importlib.import_module(module_name), func_name)
    raise RuntimeError(
        "no agent factory: pass agent_factory=..., call set_agent_factory(...), "
        "or set BRACHYBOT_AGENT_FACTORY=<module>:<func>. A live run must inject "
        "the real BrachyAgent; replay runs do not use this adapter."
    )


def _step_trace(steps: Sequence[Dict[str, Any]]) -> list:
    """Translate BrachyBot execution-trace steps into tool observations."""
    out = []
    for step in steps or []:
        tool = step.get("tool")
        if not tool:
            continue
        meta = step.get("metadata") or {}
        ret = meta.get("ret") if isinstance(meta, dict) else None
        if ret is None:
            ret = meta.get("result", step.get("result")) if isinstance(meta, dict) else None
        if ret is None and isinstance(meta, dict) and "dose_metrics" in meta:
            ret = {"dose_metrics": meta["dose_metrics"]}
        entry = {"tool": tool, "ret": ret if ret is not None else {}}
        params = meta.get("params", step.get("params")) if isinstance(meta, dict) else step.get("params")
        if params is not None:
            entry["params"] = params
        src = meta.get("source_artifact_id") if isinstance(meta, dict) else None
        if src:
            entry["source_artifact_id"] = src
        out.append(entry)
    return out


def trace_to_observation(
    trace_result: Dict[str, Any],
    *,
    terminal_state: Optional[Dict[str, Any]] = None,
    reply: Optional[Dict[str, Any]] = None,
    intent_class: Optional[str] = None,
    model_id: Optional[str] = None,
    llm_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pure translation: BrachyBot turn output -> observation dict."""
    meta = dict(llm_meta or trace_result.get("llm_meta") or {})
    response = str(trace_result.get("response") or "")
    obs: Dict[str, Any] = {
        "response": response,
        "trace": _step_trace(trace_result.get("steps") or []),
        "terminal_state": terminal_state if terminal_state is not None else {},
        "intent_class": intent_class,
        "model_id": model_id or meta.get("model") or meta.get("route") or "unspecified",
        "partial_status": meta.get("partial_status") or "PARTIAL",
    }
    if reply is not None:
        obs["reply"] = reply
    return obs


def _default_state_reader(agent: Any) -> Dict[str, Any]:
    reader = getattr(agent, "observation_state", None)
    if callable(reader):
        return dict(reader() or {})
    return {}


def observe(
    task: Dict[str, Any],
    initial_state: Dict[str, Any],
    *,
    agent_factory: Optional[Callable] = None,
    state_reader: Optional[Callable[[Any], Dict[str, Any]]] = None,
    reply_reader: Optional[Callable[[Any, str], Dict[str, Any]]] = None,
    intent_class: Optional[str] = None,
    event_driver: Optional[Callable] = None,
    completion_reader: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Run every user turn of ``task`` and return one observation."""
    factory = _resolve_factory(agent_factory)
    read_state = state_reader or _default_state_reader
    agent = factory(task, initial_state)
    start = time.monotonic()

    turns = (task.get("protocol") or {}).get("turns") or []
    all_steps: list = []
    response = ""
    meta: Dict[str, Any] = {}
    delivered = []
    budget = (task.get("protocol") or {}).get("budget") or {}
    user_count = 0
    for turn in turns:
        if turn.get("role") != "user":
            if event_driver is None:
                raise RuntimeError("protocol contains context/UI events but no evaluator event driver")
            event_driver(agent, turn)
            continue
        user_count += 1
        if (budget.get("turns", 0) > 0 and user_count > budget["turns"]
                or budget.get("wall_clock_s", 0) > 0 and time.monotonic() - start > budget["wall_clock_s"]):
            meta["partial_status"] = "PARTIAL"
            break
        result = agent.chat_with_trace(turn.get("text", ""))
        all_steps.extend(result.get("steps") or [])
        response = result.get("response", response)
        meta = result.get("llm_meta") or meta
        delivered.append({"user": turn.get("text", ""), "response": response})
        if budget.get("tool_calls", 0) > 0 and len(_step_trace(all_steps)) > budget["tool_calls"]:
            meta["partial_status"] = "PARTIAL"
            break

    terminal = read_state(agent)
    reply = reply_reader(agent, response) if reply_reader else None
    observation = trace_to_observation(
        {"response": response, "steps": all_steps, "llm_meta": meta},
        terminal_state=terminal,
        reply=reply,
        intent_class=intent_class,
        llm_meta=meta,
    )
    observation.update(turn_responses=delivered, turns=len(delivered),
                       wall_clock_s=time.monotonic() - start, tool_calls=len(observation["trace"]))
    if completion_reader is not None:
        observation.update(completion_reader(agent))
    return observation


def observe_task(task: Dict[str, Any], initial_state: Dict[str, Any]) -> Dict[str, Any]:
    """Adapter entry point for ``run_task.py --adapter python:<this>:observe_task``.

    Requires ``BRACHYBOT_AGENT_FACTORY=<module>:<func>`` (a live run) or a
    factory registered via :func:`set_agent_factory`.
    """
    def hook(name):
        spec = os.environ.get(name)
        if not spec:
            return None
        module, _, function = spec.partition(":")
        return getattr(importlib.import_module(module), function)
    return observe(task, initial_state,
                   event_driver=hook("BRACHYBENCH_EVENT_DRIVER"),
                   completion_reader=hook("BRACHYBENCH_COMPLETION_READER"))
