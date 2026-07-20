import threading
import time

import pytest

from web.chat_tasks import ChatTaskManager


class _App:
    def app_context(self):
        class _Context:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        return _Context()


class _Memory:
    def __init__(self):
        self.ui_state = None

    def set_ui_state(self, value):
        self.ui_state = value


class _Agent:
    def __init__(self, events, delay=0):
        self.memory = _Memory()
        self.events = events
        self.delay = delay
        self.cancelled = False

    def chat_with_stream(self, _message):
        for event in self.events:
            if self.delay:
                time.sleep(self.delay)
            yield event

    def _cancel_active_turn(self):
        self.cancelled = True


def _event(name, payload):
    import json

    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


def test_chat_task_replays_events_and_is_case_scoped():
    manager = ChatTaskManager(retention_seconds=300)
    finished = []
    task = manager.start(
        _App(),
        "user-a",
        "case-a",
        _Agent([
            _event("start", {"language": {"code": "en"}}),
            _event("step", {"id": 1, "type": "user", "status": "done"}),
            _event("response", {"response": "finished"}),
            _event("done", {}),
        ]),
        "hello",
        {"slice": 3},
        on_finish=finished.append,
    )

    deadline = time.time() + 2
    while task.status == "running" and time.time() < deadline:
        time.sleep(0.01)

    assert task.status == "completed"
    assert task.response == "finished"
    assert task.steps[0]["id"] == 1
    assert finished == [task]
    assert task.agent.memory.ui_state == {"slice": 3}
    assert list(task.iter_events(0)) == [
        _event("start", {"language": {"code": "en"}}),
        _event("step", {"id": 1, "type": "user", "status": "done"}),
        _event("response", {"response": "finished"}),
        _event("done", {}),
    ]
    assert manager.get(task.task_id, "user-a", "case-a") is task
    assert manager.get(task.task_id, "user-a", "case-b") is None


def test_only_explicit_cancel_stops_a_running_case_task():
    manager = ChatTaskManager()
    gate = threading.Event()

    class _BlockingAgent(_Agent):
        def chat_with_stream(self, _message):
            yield _event("start", {})
            gate.wait(timeout=2)
            yield _event("done", {"cancelled": self.cancelled})

    task = manager.start(_App(), "user-a", "case-a", _BlockingAgent([]), "hello", {})
    # Replace the stream source only before the worker gets to the gate is
    # intentionally avoided; this test uses a fresh task with the blocking
    # implementation to verify the manager's explicit cancellation contract.
    manager.cancel(task)
    gate.set()
    assert task.status == "cancelled"
    assert task.agent.cancelled is True


def test_same_case_rejects_concurrent_turn_but_other_case_is_allowed():
    manager = ChatTaskManager()
    gate = threading.Event()

    class _SlowAgent(_Agent):
        def chat_with_stream(self, _message):
            yield _event("start", {})
            gate.wait(timeout=2)
            yield _event("done", {})

    first = manager.start(_App(), "user-a", "case-a", _SlowAgent([]), "one", {})
    with pytest.raises(RuntimeError):
        manager.start(_App(), "user-a", "case-a", _SlowAgent([]), "two", {})
    second = manager.start(_App(), "user-a", "case-b", _SlowAgent([]), "two", {})
    manager.cancel(first)
    manager.cancel(second)
    gate.set()
