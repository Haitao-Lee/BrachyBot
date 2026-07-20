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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

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
    created_at: float = field(default_factory=time.time)
    status: str = "running"
    finished_at: Optional[float] = None
    response: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def __post_init__(self) -> None:
        self._events: List[str] = []
        self._condition = threading.Condition()

    def publish(self, raw: Any) -> None:
        """Append an event and notify every current/future subscriber."""
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw or "")
        if not text:
            return
        event_name, data = _event_parts(text)
        if event_name == "step" and isinstance(data, dict):
            self.steps.append(dict(data))
        elif event_name == "response" and isinstance(data, dict):
            self.response = str(data.get("response") or "")
        elif event_name == "error" and isinstance(data, dict):
            self.error = str(data.get("message") or data.get("error") or "")
        elif event_name == "done" and isinstance(data, dict) and data.get("cancelled"):
            self.status = "cancelled"
        with self._condition:
            self._events.append(text)
            self._condition.notify_all()

    def finish(self, status: str = "completed", error: str = "") -> None:
        with self._condition:
            if self.status == "running":
                self.status = status
            self.error = error or self.error
            self.finished_at = time.time()
            self._condition.notify_all()

    def event_count(self) -> int:
        with self._condition:
            return len(self._events)

    def iter_events(self, after_seq: int = 0) -> Iterable[str]:
        """Replay from a sequence and then follow live events until terminal."""
        index = max(0, int(after_seq or 0))
        while True:
            with self._condition:
                while index >= len(self._events) and self.status == "running":
                    self._condition.wait(timeout=1.0)
                batch = self._events[index:]
                index = len(self._events)
                terminal = self.status != "running" and index >= len(self._events)
            for event in batch:
                yield event
            if terminal:
                return

    def public_state(self) -> Dict[str, Any]:
        with self._condition:
            return {
                "task_id": self.task_id,
                "session_id": self.session_id,
                "status": self.status,
                "message": self.message,
                "created_at": self.created_at,
                "finished_at": self.finished_at,
                "event_count": len(self._events),
                "response_available": bool(self.response),
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
        on_finish: Optional[Callable[[ChatTask], None]] = None,
        start_gate: Optional[threading.Event] = None,
    ) -> ChatTask:
        """Start one worker, rejecting concurrent turns in the same case."""
        with self._lock:
            self._purge_locked()
            if self.active(user_id, session_id) is not None:
                raise RuntimeError("A chat task is already running for this case")
            task = ChatTask(
                task_id=uuid.uuid4().hex,
                user_id=str(user_id),
                session_id=str(session_id),
                agent=agent,
                message=str(message),
            )
            self._tasks[task.task_id] = task

        def worker() -> None:
            finalized = False
            try:
                if start_gate is not None:
                    start_gate.wait()
                # The Agent may access Flask-independent services through the
                # application extensions; install an app context, but never a
                # browser session cookie. The task's owner/case is explicit.
                with app.app_context():
                    agent.memory.set_ui_state(ui_state or {})
                    for event in agent.chat_with_stream(task.message):
                        task.publish(event)
                    if task.status == "running":
                        task.finish("completed")
                    if on_finish is not None:
                        on_finish(task)
                        finalized = True
            except Exception as exc:  # pragma: no cover - exercised by integration tests
                logger.exception("Chat task %s failed", task.task_id)
                task.publish(
                    "event: error\ndata: " + json.dumps({"message": str(exc)}) + "\n\n"
                )
                task.finish("failed", str(exc))
                if on_finish is not None:
                    try:
                        with app.app_context():
                            on_finish(task)
                            finalized = True
                    except Exception:
                        logger.exception("Chat task %s finalization failed", task.task_id)
            finally:
                if on_finish is not None and not finalized:
                    try:
                        with app.app_context():
                            on_finish(task)
                    except Exception:
                        logger.exception("Chat task %s finalization failed", task.task_id)

        thread = threading.Thread(target=worker, name=f"brachy-chat-{task.task_id[:8]}", daemon=True)
        thread.start()
        return task

    def cancel(self, task: Optional[ChatTask]) -> bool:
        if task is None:
            return False
        try:
            task.agent._cancel_active_turn()
        except Exception:
            logger.exception("Unable to cancel chat task %s", task.task_id)
        task.finish("cancelled")
        return True

    def _purge_locked(self) -> None:
        cutoff = time.time() - self.retention_seconds
        stale = [
            task_id for task_id, task in self._tasks.items()
            if task.status != "running" and (task.finished_at or task.created_at) < cutoff
        ]
        for task_id in stale:
            self._tasks.pop(task_id, None)
