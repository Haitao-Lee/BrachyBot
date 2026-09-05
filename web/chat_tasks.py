"""Session-scoped background chat tasks and replayable SSE events.

The browser is allowed to leave a case while a model/tool workflow is still
running.  A request-bound Flask generator is therefore the wrong lifecycle:
when its client disconnects, ``GeneratorExit`` must not cancel the clinical
workflow.  This module keeps the worker and its bounded event journal alive
independently of the current browser tab, while still allowing an explicit
Stop action to cancel the owning Agent.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple

# Long or repetitive agent workflows can publish tens of thousands of raw
# events (tool payloads, text chunks) into one task journal. Retaining every
# event grows process memory without bound while the task runs, so journals
# are capped. The cap is far above any real turn's event count; a subscriber
# that resumes from a sequence older than the retained window replays what
# remains instead of the trimmed prefix.
MAX_TASK_JOURNAL_EVENTS = 2000
# Step metadata is persisted separately from the replay journal.  It needs an
# independent bound or a tool-heavy task can still retain every decoded step
# after the corresponding raw events have been trimmed.
MAX_TASK_STEPS = 2000

logger = logging.getLogger(__name__)


def _event_parts(raw: Any) -> Tuple[str, Dict[str, Any]]:
    """Decode one Agent SSE event for task metadata and durable summaries."""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw or "")
    event_name = "message"
    data_text = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            event_name = line[7:].strip()
        elif line.startswith("data: "):
            data_text += line[6:].strip()
    try:
        data = json.loads(data_text) if data_text else {}
    except (TypeError, ValueError):
        data = {"raw": data_text}
    return event_name, data if isinstance(data, dict) else {"value": data}


@dataclass
class ChatTask:
    """One isolated chat turn owned by one account case."""

    task_id: str
    user_id: str
    session_id: str
    agent: Any
    message: str
    request_id: str = ""
    user_message_id: str = ""
    assistant_message_id: str = ""
    # A visual-analysis follow-up is a real execution task, but its result is
    # presented inside the original assistant reply. Keep execution identity
    # and transcript identity separate so retries cannot replay the parent
    # task or attach a child answer to a later user turn.
    parent_request_id: str = ""
    parent_user_message_id: str = ""
    parent_assistant_message_id: str = ""
    internal_followup: bool = False
    response_language: str = ""
    # The global UI locale is a fallback for a new/ambiguous dialogue turn;
    # it is deliberately kept separate from response_language so a Chinese
    # user message in an English UI remains a Chinese chat/trace turn.
    ui_language: str = ""
    created_at: float = field(default_factory=time.time)
    status: str = "running"
    finished_at: Optional[float] = None
    response: str = ""
    streamed_response: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    completion_status: str = ""
    result_committed: bool = False
    # Transcript persistence and the heavy Agent checkpoint have separate
    # lifecycles.  The chat response is durable before the task becomes
    # terminal; the clinical arrays may finish in the background afterwards.
    persistence_status: str = "not_started"
    persistence_error: str = ""

    def __post_init__(self) -> None:
        self.request_id = str(self.request_id or self.task_id)
        self.user_message_id = str(
            self.user_message_id or f"user-{self.request_id}"
        )
        self.assistant_message_id = str(
            self.assistant_message_id or f"assistant-{self.request_id}"
        )
        self.parent_request_id = str(self.parent_request_id or "")
        self.parent_user_message_id = str(self.parent_user_message_id or "")
        self.parent_assistant_message_id = str(self.parent_assistant_message_id or "")
        self._events: Deque[str] = deque()
        # Absolute sequence number of ``_events[0]``. Trimming the front of
        # the journal advances this offset so subscriber sequence numbers
        # stay stable across reconnects.
        self._event_base = 0
        self._terminal_event_seen = False
        self._condition = threading.Condition()
        self._commit_step_id = f"workspace-commit-{self.task_id}"
        self._worker_done = threading.Event()
        self._skip_finalization = False

    def commit_step(self, status: str, result: str = "") -> Dict[str, Any]:
        """Return the stable progress step used while durable results commit."""
        step = {
            "id": self._commit_step_id,
            "type": "tool",
            "tool": "workspace_checkpoint",
            "title": "Saving case results",
            "status": str(status),
            "content": (
                "Persisting clinical results, conversation, and viewer state."
                if status == "pending"
                else "Case results saved."
            ),
        }
        if result:
            step["result"] = str(result)
        return step

    @staticmethod
    def encode_event(event_name: str, data: Dict[str, Any]) -> str:
        return f"event: {event_name}\ndata: {json.dumps(data)}\n\n"

    def _append_event_locked(self, text: str) -> None:
        """Append one event while preserving the bounded absolute sequence."""
        self._events.append(text)
        while len(self._events) > MAX_TASK_JOURNAL_EVENTS:
            self._events.popleft()
            self._event_base += 1

    def publish(self, raw: Any) -> None:
        """Append an event and notify every current/future subscriber."""
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw or "")
        if not text:
            return
        event_name, data = _event_parts(text)
        # Workspace persistence is an internal durability concern, not a
        # workflow step.  Older agents and recovery paths may still emit the
        # legacy ``workspace_checkpoint`` event; suppress it at the task
        # journal boundary so the UI cannot show a false, indefinitely
        # pending operation after the clinical response is already complete.
        if (
            event_name == "step"
            and isinstance(data, dict)
            and str(data.get("tool") or "") == "workspace_checkpoint"
        ):
            logger.debug("Suppressing internal workspace checkpoint step for task %s", self.task_id)
            return
        with self._condition:
            if event_name == "step" and isinstance(data, dict):
                self.steps.append(dict(data))
                if len(self.steps) > MAX_TASK_STEPS:
                    del self.steps[:-MAX_TASK_STEPS]
            elif event_name == "response" and isinstance(data, dict):
                self.response = str(data.get("response") or "")
                self.streamed_response = ""
            elif event_name == "final_text_chunk" and isinstance(data, dict):
                # Keep a durable fallback if the provider disconnects after
                # the text stream but before the aggregate response arrives.
                self.streamed_response += str(data.get("text") or "")
            elif event_name == "error" and isinstance(data, dict):
                self.error = str(data.get("message") or data.get("error") or "")
            elif event_name == "done" and isinstance(data, dict) and data.get("cancelled"):
                self.status = "cancelled"
            if event_name == "done":
                self._terminal_event_seen = True
            self._append_event_locked(text)
            self._condition.notify_all()

    def finish(self, status: str = "completed", error: str = "") -> None:
        with self._condition:
            if self.status == "running":
                self.status = status
                self.finished_at = time.time()
            self.error = error or self.error
            self._condition.notify_all()

    def is_running(self) -> bool:
        """Return whether the worker is still allowed to publish events."""
        with self._condition:
            return self.status == "running"

    def cancel(self) -> bool:
        """Mark the task terminal and publish one replayable cancellation event.

        Agent providers can yield buffered tool or text events after their
        cancellation hook returns.  The task journal is the source of truth
        for every browser, so cancellation must become a terminal protocol
        event before the worker sees those late events.
        """
        with self._condition:
            if self.status != "running":
                return False
            self.status = "cancelled"
            self.completion_status = "cancelled"
            self.finished_at = time.time()
            if not self._terminal_event_seen:
                self._append_event_locked(
                    self.encode_event("done", {"cancelled": True})
                )
                self._terminal_event_seen = True
            self._condition.notify_all()
        return True

    def event_count(self) -> int:
        with self._condition:
            return self._event_base + len(self._events)

    def set_persistence_status(self, status: str, error: str = "") -> None:
        with self._condition:
            self.persistence_status = str(status or "not_started")
            self.persistence_error = str(error or "")
            self._condition.notify_all()

    def wait_for_worker(self, timeout: Optional[float] = None) -> bool:
        """Wait until the task thread has stopped touching its workspace."""
        return self._worker_done.wait(timeout=timeout)

    def iter_events(self, after_seq: int = 0) -> Iterable[str]:
        """Replay from a sequence and then follow live events until terminal."""
        index = max(0, int(after_seq or 0))
        while True:
            heartbeat = False
            with self._condition:
                relative = index - self._event_base
                if relative < 0:
                    # The requested prefix was trimmed by the bounded journal;
                    # replay everything that remains rather than failing the
                    # reconnect.
                    index = self._event_base
                    relative = 0
                while relative >= len(self._events) and self.status == "running":
                    # A long model/tool phase may legitimately produce no
                    # user-visible event for a while. Emit a protocol comment
                    # after a bounded idle interval so reverse proxies and
                    # browsers keep the stream open instead of showing a
                    # misleading "connection interrupted" recovery state.
                    if not self._condition.wait(timeout=10.0):
                        heartbeat = True
                        break
                    relative = max(0, index - self._event_base)
                batch = list(self._events)[relative:] if relative < len(self._events) else []
                index = self._event_base + len(self._events)
                terminal = self.status != "running" and (index - self._event_base) >= len(self._events)
            for event in batch:
                yield event
            if heartbeat and not terminal:
                yield ": brachybot-task-alive\n\n"
            if terminal:
                return

    def public_state(self) -> Dict[str, Any]:
        with self._condition:
            raw_brain_available = getattr(self.agent, "brain_available", None)
            brain_available = (
                raw_brain_available if isinstance(raw_brain_available, bool) else None
            )
            public_message = self.message
            if self.internal_followup:
                public_message = (
                    "正在分析已捕获的图像。"
                    if str(self.response_language).lower().startswith("zh")
                    else "Analyzing captured visual evidence."
                )
            return {
                "task_id": self.task_id,
                "request_id": self.request_id,
                "user_message_id": self.user_message_id,
                "assistant_message_id": self.assistant_message_id,
                "parent_request_id": self.parent_request_id or None,
                "parent_user_message_id": self.parent_user_message_id or None,
                "parent_assistant_message_id": self.parent_assistant_message_id or None,
                "internal_followup": bool(self.internal_followup),
                "response_language": self.response_language or None,
                "ui_language": self.ui_language or None,
                "session_id": self.session_id,
                # Lightweight Session status deliberately reports unknown.
                # Once this task owns a hydrated Agent, expose the real model
                # availability so the header cannot remain falsely Offline.
                "brain_available": brain_available,
                "status": self.status,
                "phase": (
                    "finalizing"
                    if self.status == "running" and self.completion_status
                    else self.status
                ),
                # Never expose the hidden multimodal prompt or its screenshot
                # URLs through task recovery metadata.
                "message": public_message,
                "created_at": self.created_at,
                "finished_at": self.finished_at,
                "event_count": self._event_base + len(self._events),
                "response_available": bool(self.response or self.streamed_response),
                "result_committed": bool(self.result_committed),
                "persistence_status": self.persistence_status,
                "persistence_error": self.persistence_error or None,
                "error": self.error or None,
            }


class ChatTaskManager:
    """Own session-isolated chat workers for the lifetime of one server."""

    def __init__(self, retention_seconds: int = 3600) -> None:
        self.retention_seconds = max(300, int(retention_seconds))
        self._lock = threading.RLock()
        self._tasks: Dict[str, ChatTask] = {}

    @staticmethod
    def _owner_key(user_id: str, session_id: str) -> Tuple[str, str]:
        return str(user_id), str(session_id)

    def active(self, user_id: str, session_id: str) -> Optional[ChatTask]:
        with self._lock:
            self._purge_locked()
            candidates = [
                task for task in self._tasks.values()
                if (task.user_id, task.session_id) == self._owner_key(user_id, session_id)
                and task.status == "running"
            ]
            return max(candidates, key=lambda task: task.created_at, default=None)

    def live(self, user_id: str, session_id: str) -> Optional[ChatTask]:
        """Return the newest worker that has not left the Agent yet.

        ``ChatTask.cancel`` changes the public status immediately so the
        browser can stop its progress indicator.  That status is not proof
        that the worker has released Agent memory or restored an internal
        follow-up snapshot.  Lifecycle decisions that can start another
        turn must use this method to avoid concurrent case mutation.
        """
        with self._lock:
            self._purge_locked()
            candidates = [
                task for task in self._tasks.values()
                if (task.user_id, task.session_id) == self._owner_key(user_id, session_id)
                and not task._worker_done.is_set()
            ]
            return max(candidates, key=lambda task: task.created_at, default=None)

    def latest(self, user_id: str, session_id: str) -> Optional[ChatTask]:
        with self._lock:
            self._purge_locked()
            candidates = [
                task for task in self._tasks.values()
                if (task.user_id, task.session_id) == self._owner_key(user_id, session_id)
            ]
            return max(candidates, key=lambda task: task.created_at, default=None)

    def get(self, task_id: str, user_id: str, session_id: str) -> Optional[ChatTask]:
        with self._lock:
            self._purge_locked()
            task = self._tasks.get(str(task_id))
            if task is None or (task.user_id, task.session_id) != self._owner_key(user_id, session_id):
                return None
            return task

    def start(
        self,
        app: Any,
        user_id: str,
        session_id: str,
        agent: Any,
        message: str,
        ui_state: Optional[Dict[str, Any]],
        on_finish: Optional[Callable[[ChatTask], Optional[bool]]] = None,
        start_gate: Optional[threading.Event] = None,
        agent_supplier: Optional[Callable[[], Any]] = None,
        request_id: str = "",
        user_message_id: str = "",
        assistant_message_id: str = "",
        parent_request_id: str = "",
        parent_user_message_id: str = "",
        parent_assistant_message_id: str = "",
        internal_followup: bool = False,
        response_language: str = "",
        ui_language: str = "",
    ) -> ChatTask:
        """Start one worker, rejecting concurrent turns in the same case.

        ``agent_supplier`` keeps the HTTP/SSE handshake independent from cold
        workspace hydration.  A browser can receive a task immediately while
        the worker reconstructs the case-owned Agent in the background.
        """
        # Captured before the worker closure is created so ordinary turns do
        # not close over an unassigned local when there is no predecessor.
        predecessor: Optional[ChatTask] = None
        with self._lock:
            self._purge_locked()
            request_key = str(request_id or "")
            if request_key:
                duplicate = next((
                    task for task in self._tasks.values()
                    if (task.user_id, task.session_id) == self._owner_key(user_id, session_id)
                    and task.request_id == request_key
                    and bool(task.internal_followup) == bool(internal_followup)
                ), None)
                if duplicate is not None:
                    return duplicate
            # ``active`` only represents the public running state.  A task
            # that was just cancelled can still be executing its generator
            # finalizer and restoring AgentMemory.  Treat that worker as the
            # predecessor too, otherwise a new user turn can enter the same
            # Agent concurrently and inherit the old screenshot prompt.
            live = self.live(user_id, session_id)
            if live is not None:
                # A visual-analysis child may be submitted as soon as the
                # browser receives the parent's terminal SSE event. The
                # parent can still be inside its persistence/finalization
                # block at that point, so its public ``status`` may remain
                # ``running`` for a few more milliseconds. This is a valid
                # sequential continuation only when it is explicitly bound
                # to that exact visible parent turn. The worker below waits
                # on ``predecessor`` before it may touch AgentMemory.
                linked_internal_followup = (
                    bool(internal_followup)
                    and not bool(live.internal_followup)
                    and bool(parent_request_id)
                    and str(parent_request_id) == str(live.request_id)
                    and (
                        not parent_user_message_id
                        or not live.user_message_id
                        or str(parent_user_message_id) == str(live.user_message_id)
                    )
                    and (
                        not parent_assistant_message_id
                        or not live.assistant_message_id
                        or str(parent_assistant_message_id) == str(live.assistant_message_id)
                    )
                )
                # A screenshot analysis is a child of an already visible
                # assistant reply. A new user instruction supersedes it
                # instead of waiting behind it or inheriting its prompt. The
                # new worker still waits for the old worker thread to leave
                # the Agent so two turns cannot mutate one AgentMemory at
                # the same time.
                if linked_internal_followup:
                    predecessor = live
                elif internal_followup:
                    # Do not let an orphaned child prompt attach to an
                    # unrelated live turn. This is an identity boundary, not
                    # a text/keyword rule: the browser must provide stable
                    # request/message identifiers of its parent reply.
                    raise RuntimeError(
                        "Visual analysis follow-up is not linked to the active parent task"
                    )
                elif live.internal_followup:
                    predecessor = live
                    live._skip_finalization = True
                    if live.status == "running":
                        self.cancel(live)
                elif live.status != "running":
                    # The browser may already have received a cancellation
                    # acknowledgement.  The new turn starts only after the
                    # cancelled worker has actually unwound.
                    predecessor = live
                    # A terminal task can still be inside its finalizer until
                    # ``_worker_done`` is set.  Once a newer turn owns the
                    # case, the old worker must not checkpoint or append a
                    # late response after the predecessor barrier opens.
                    live._skip_finalization = True
                else:
                    raise RuntimeError("A chat task is already running for this case")
            task = ChatTask(
                task_id=uuid.uuid4().hex,
                user_id=str(user_id),
                session_id=str(session_id),
                agent=agent,
                message=str(message),
                request_id=str(request_id or ""),
                user_message_id=str(user_message_id or ""),
                assistant_message_id=str(assistant_message_id or ""),
                parent_request_id=str(parent_request_id or ""),
                parent_user_message_id=str(parent_user_message_id or ""),
                parent_assistant_message_id=str(parent_assistant_message_id or ""),
                internal_followup=bool(internal_followup),
                response_language=str(response_language or ""),
                ui_language=str(ui_language or ""),
            )
            self._tasks[task.task_id] = task

        def worker() -> None:
            finalized = False
            terminal_event = ""
            try:
                if predecessor is not None:
                    predecessor.wait_for_worker(timeout=None)
                    if not task.is_running():
                        return
                if start_gate is not None:
                    start_gate.wait()
                if not task.is_running():
                    return
                # The Agent may access Flask-independent services through the
                # application extensions; install an app context, but never a
                # browser session cookie. The task's owner/case is explicit.
                with app.app_context():
                    hydrated_agent_now = False
                    if task.agent is None and agent_supplier is not None:
                        trace_zh = str(
                            task.response_language or task.ui_language or ""
                        ).lower().startswith("zh")
                        task.publish(task.encode_event(
                            "step",
                            {
                                "id": f"workspace-hydration-{task.task_id}",
                                "type": "tool",
                                "tool": "workspace_hydration",
                                "title": "加载病例资源" if trace_zh else "Loading case resources",
                                "status": "pending",
                                "content": (
                                    "开始本次对话前正在恢复病例资源。"
                                    if trace_zh
                                    else "Restoring the case before starting this chat turn."
                                ),
                            },
                        ))
                        task.agent = agent_supplier()
                        hydrated_agent_now = True
                        if task.agent is None:
                            raise RuntimeError("Case resources are not available")
                        if not task.is_running():
                            return
                        task.publish(task.encode_event(
                            "step",
                            {
                                "id": f"workspace-hydration-{task.task_id}",
                                "type": "tool",
                                "tool": "workspace_hydration",
                                "title": "加载病例资源" if trace_zh else "Loading case resources",
                                "status": "done",
                                "content": "病例资源已恢复。" if trace_zh else "Case resources restored.",
                            },
                        ))
                    if task.agent is None:
                        raise RuntimeError("Agent not available")
                    agent = task.agent
                    # A cold task needs a status event as soon as hydration
                    # resolves the Agent.  A pre-hydrated task normally gets
                    # the same value through task_meta, but lightweight
                    # adapters are allowed to omit the workflow ``start``
                    # event; the worker fills that protocol gap below.
                    brain_status_sent = False
                    if hydrated_agent_now:
                        task.publish(task.encode_event(
                            "brain_status",
                            {
                                "available": bool(getattr(agent, "brain_available", False)),
                                "source": "hydrated_agent",
                            },
                        ))
                        brain_status_sent = True
                    agent.memory.set_ui_state(ui_state or {})
                    previous_turn_context = getattr(agent, "_active_turn_context", None)
                    agent._active_turn_context = {
                        "internal_followup": bool(task.internal_followup),
                        "request_id": task.request_id,
                        "parent_request_id": task.parent_request_id,
                        "parent_user_message_id": task.parent_user_message_id,
                        "parent_assistant_message_id": task.parent_assistant_message_id,
                        # Keep the language attached to the task identity as
                        # well as the durable chat row.  A recovered visual
                        # child must not fall back to the next turn's or the
                        # global UI language while it is being rendered.
                        "response_language": task.response_language,
                        "ui_language": task.ui_language,
                    }
                    turn_stream = None
                    provider_start_seen = False
                    try:
                        turn_stream = agent.chat_with_stream(task.message)
                        for event in turn_stream:
                            # Explicit Stop is the only normal cancellation path.
                            # Providers may flush a buffered event after their
                            # cancellation hook returns; never let it mutate the
                            # owning case or leak into a later replay.
                            if not task.is_running():
                                break
                            event_name, _ = _event_parts(event)
                            # A protocol-compliant workflow emits ``start``
                            # and the task_meta handshake already carries the
                            # status.  Some small adapters emit only response
                            # and done; publish the status before their first
                            # event so the replay journal remains self-
                            # describing without adding a duplicate event to
                            # the normal trace.
                            if event_name == "start":
                                provider_start_seen = True
                            elif not brain_status_sent and not provider_start_seen:
                                task.publish(task.encode_event(
                                    "brain_status",
                                    {
                                        "available": bool(getattr(agent, "brain_available", False)),
                                        "source": "prehydrated_agent",
                                    },
                                ))
                                brain_status_sent = True
                            # The Agent's ``done`` event is a protocol boundary,
                            # not proof that case data is durable. Hold it until
                            # arrays, chat, report state, and operation metadata
                            # have committed to the owning workspace.
                            if event_name == "done":
                                terminal_event = (
                                    event.decode("utf-8", errors="replace")
                                    if isinstance(event, bytes) else str(event or "")
                                )
                                continue
                            if not task.is_running():
                                break
                            task.publish(event)
                        # An empty pre-hydrated stream has no provider event
                        # from which to infer the status boundary.  Publish it
                        # before the task's terminal response in that rare
                        # case, while keeping normal ``start`` traces intact.
                        if not brain_status_sent and not provider_start_seen and task.is_running():
                            task.publish(task.encode_event(
                                "brain_status",
                                {
                                    "available": bool(getattr(agent, "brain_available", False)),
                                    "source": "prehydrated_agent",
                                },
                            ))
                            brain_status_sent = True
                    finally:
                        # The workflow wrapper uses generator finalization to
                        # restore its temporary internal memory snapshot. An
                        # early Stop or superseding user turn must close the
                        # stream explicitly; waiting for GC leaves the old
                        # Agent turn holding memory and task ownership.
                        close_stream = getattr(turn_stream, "close", None)
                        if callable(close_stream):
                            try:
                                close_stream()
                            except Exception:
                                logger.debug(
                                    "Unable to close chat stream for task %s",
                                    task.task_id,
                                    exc_info=True,
                                )
                        if previous_turn_context is None:
                            try:
                                delattr(agent, "_active_turn_context")
                            except AttributeError:
                                pass
                        else:
                            agent._active_turn_context = previous_turn_context
                    if task.is_running():
                        task.completion_status = "completed"
                        # The final response is gated by the lightweight chat
                        # transcript transaction.  The expensive Agent
                        # checkpoint is scheduled by on_finish and must not be
                        # exposed as a fake pending tool step or delay `done`.
                        committed = True
                        if on_finish is not None:
                            committed = on_finish(task) is not False
                            finalized = True
                        if not committed:
                            failure = "Case results could not be saved."
                            task.publish(task.encode_event(
                                "step",
                                task.commit_step("error", failure),
                            ))
                            task.publish(task.encode_event("error", {"message": failure}))
                            task.finish("failed", failure)
                            return
                        task.result_committed = True
                        # The Agent normally emits `done`. The task boundary
                        # supplies it when an adapter omits it. The lightweight
                        # transcript is already committed; clinical array
                        # persistence continues independently and reports its
                        # state through task metadata rather than the trace.
                        task.publish(terminal_event or "event: done\ndata: {}\n\n")
                        task.finish("completed")
                    if on_finish is not None and not task._skip_finalization:
                        if not finalized:
                            on_finish(task)
                            finalized = True
            except Exception as exc:  # pragma: no cover - exercised by integration tests
                logger.exception("Chat task %s failed", task.task_id)
                task.completion_status = "failed"
                task.publish(
                    "event: error\ndata: " + json.dumps({"message": str(exc)}) + "\n\n"
                )
                if (
                    on_finish is not None
                    and task.agent is not None
                    and not task._skip_finalization
                ):
                    try:
                        with app.app_context():
                            on_finish(task)
                            finalized = True
                    except Exception:
                        logger.exception("Chat task %s finalization failed", task.task_id)
                task.finish("failed", str(exc))
            finally:
                # A deleted case must not be checkpointed after its workspace
                # has moved to trash. Explicit cancellation owns that terminal
                # state and intentionally skips the normal persistence hook.
                if (
                    on_finish is not None
                    and not finalized
                    and task.agent is not None
                    and not task._skip_finalization
                ):
                    try:
                        with app.app_context():
                            on_finish(task)
                    except Exception:
                        logger.exception("Chat task %s finalization failed", task.task_id)
                task._worker_done.set()

        thread = threading.Thread(target=worker, name=f"brachy-chat-{task.task_id[:8]}", daemon=True)
        thread.start()
        return task

    def cancel(self, task: Optional[ChatTask]) -> bool:
        if task is None:
            return False
        cancelled = task.cancel()
        if not cancelled:
            return False
        try:
            if task.agent is not None:
                task.agent._cancel_active_turn()
        except Exception:
            logger.exception("Unable to cancel chat task %s", task.task_id)
        return True

    def cancel_session(
        self,
        user_id: str,
        session_id: str,
        *,
        wait_timeout: float = 10.0,
    ) -> bool:
        """Cancel one case-owned task and wait for workspace access to cease.

        Session navigation never calls this method. It is reserved for an
        explicit delete/purge operation, where moving files while a worker is
        still reading them would create retries, missing CT errors, and stale
        checkpoints against a non-existent workspace.
        """
        # Deletion must wait for a cancelled-but-still-unwinding worker too;
        # moving the workspace while it is still reading creates intermittent
        # missing-case and partial-hydration failures.
        task = self.active(user_id, session_id) or self.live(user_id, session_id)
        if task is None:
            return True
        task._skip_finalization = True
        self.cancel(task)
        return task.wait_for_worker(timeout=max(0.0, float(wait_timeout)))

    def _purge_locked(self) -> None:
        cutoff = time.time() - self.retention_seconds
        stale = [
            task_id for task_id, task in self._tasks.items()
            if task.status != "running" and (task.finished_at or task.created_at) < cutoff
        ]
        for task_id in stale:
            self._tasks.pop(task_id, None)
