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
        _event("step", task.commit_step("pending")),
        _event("step", task.commit_step("done")),
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


def test_cancelling_one_case_does_not_cancel_another_running_case():
    manager = ChatTaskManager()
    first_gate = threading.Event()
    second_gate = threading.Event()

    class _CaseAgent(_Agent):
        def __init__(self, gate):
            super().__init__([])
            self.gate = gate

        def chat_with_stream(self, _message):
            yield _event("start", {})
            self.gate.wait(timeout=2)
            yield _event("response", {"response": "finished"})
            yield _event("done", {})

    first_agent = _CaseAgent(first_gate)
    second_agent = _CaseAgent(second_gate)
    first = manager.start(_App(), "user-a", "case-a", first_agent, "one", {})
    second = manager.start(_App(), "user-a", "case-b", second_agent, "two", {})

    manager.cancel(first)
    first_gate.set()
    second_gate.set()

    deadline = time.time() + 2
    while second.status == "running" and time.time() < deadline:
        time.sleep(0.01)

    assert first.status == "cancelled"
    assert first_agent.cancelled is True
    assert second.status == "completed"
    assert second.response == "finished"
    assert second_agent.cancelled is False


def test_terminal_done_is_withheld_until_case_results_are_committed():
    """The UI must not observe completion before the workspace is durable."""

    manager = ChatTaskManager()
    finalization_started = threading.Event()
    allow_commit = threading.Event()
    observed = []

    def commit_result(_task):
        finalization_started.set()
        assert allow_commit.wait(timeout=2)
        return True

    task = manager.start(
        _App(),
        "user-a",
        "case-a",
        _Agent([
            _event("response", {"response": "finished"}),
            _event("done", {}),
        ]),
        "hello",
        {},
        on_finish=commit_result,
    )

    reader = threading.Thread(
        target=lambda: observed.extend(list(task.iter_events(0))),
        daemon=True,
    )
    reader.start()
    assert finalization_started.wait(timeout=2)
    assert task.status == "running"
    assert task.public_state()["phase"] == "finalizing"
    assert not any(item.startswith("event: done") for item in observed)

    allow_commit.set()
    reader.join(timeout=2)
    assert not reader.is_alive()
    assert task.status == "completed"
    assert task.result_committed is True
    assert observed[-1] == _event("done", {})


def test_failed_case_commit_never_emits_a_false_done_event():
    manager = ChatTaskManager()
    task = manager.start(
        _App(),
        "user-a",
        "case-a",
        _Agent([
            _event("response", {"response": "finished"}),
            _event("done", {}),
        ]),
        "hello",
        {},
        on_finish=lambda _task: False,
    )

    deadline = time.time() + 2
    while task.status == "running" and time.time() < deadline:
        time.sleep(0.01)

    events = list(task.iter_events(0))
    assert task.status == "failed"
    assert task.result_committed is False
    assert not any(item.startswith("event: done") for item in events)
    assert any("Case results could not be saved" in item for item in events)
