import threading
import time
from unittest.mock import patch

import pytest

from web.chat_tasks import ChatTask, ChatTaskManager
from web.server import _case_has_running_chat_task


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


def test_agent_cache_protects_cases_with_detached_running_tasks():
    """LRU maintenance must not hydrate a second agent during a case task."""

    class _TaskManager:
        def active(self, user_id, session_id):
            return object() if (user_id, session_id) == ("user-a", "case-a") else None

    manager = _TaskManager()
    assert _case_has_running_chat_task(manager, "user-a", "case-a") is True
    assert _case_has_running_chat_task(manager, "user-a", "case-b") is False
    assert _case_has_running_chat_task(None, "user-a", "case-a") is False


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


def test_lazy_agent_supplier_keeps_task_handshake_non_blocking():
    """Cold case hydration belongs to the worker, not the HTTP handshake."""
    manager = ChatTaskManager()
    gate = threading.Event()
    supplied = threading.Event()
    agent = _Agent([
        _event("response", {"response": "hydrated"}),
        _event("done", {}),
    ])

    def supplier():
        supplied.set()
        return agent

    task = manager.start(
        _App(), "user-a", "case-a", None, "hello", {},
        start_gate=gate, agent_supplier=supplier,
    )
    assert task.status == "running"
    assert supplied.is_set() is False
    gate.set()
    deadline = time.time() + 2
    while task.status == "running" and time.time() < deadline:
        time.sleep(0.01)
    assert supplied.is_set() is True
    assert task.status == "completed"
    assert task.response == "hydrated"
    assert any(step.get("tool") == "workspace_hydration" for step in task.steps)


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


def test_cancel_discards_late_provider_events_and_replays_terminal_status_once():
    """Buffered model output must not revive a manually stopped case."""

    manager = ChatTaskManager()
    gate = threading.Event()
    started = threading.Event()
    finalized = []

    class _BufferedAgent(_Agent):
        def chat_with_stream(self, _message):
            yield _event("start", {})
            started.set()
            gate.wait(timeout=2)
            yield _event("response", {"response": "late provider output"})
            yield _event("done", {})

    task = manager.start(
        _App(),
        "user-a",
        "case-a",
        _BufferedAgent([]),
        "hello",
        {},
        on_finish=finalized.append,
    )
    assert started.wait(timeout=2)
    assert manager.cancel(task) is True
    gate.set()

    deadline = time.time() + 2
    while not finalized and time.time() < deadline:
        time.sleep(0.01)

    events = list(task.iter_events(0))
    assert task.status == "cancelled"
    assert task.response == ""
    assert finalized == [task]
    assert not any("late provider output" in event for event in events)
    assert sum(event.startswith("event: done") for event in events) == 1
    assert '"cancelled": true' in events[-1]


def test_explicit_abort_can_skip_late_completion_finalization():
    """Route-owned abort cleanup must not race a later turn's persistence."""

    manager = ChatTaskManager()
    gate = threading.Event()
    started = threading.Event()
    finalized = []

    class _BufferedAgent(_Agent):
        def chat_with_stream(self, _message):
            yield _event("start", {})
            started.set()
            gate.wait(timeout=2)
            yield _event("done", {})

    task = manager.start(
        _App(),
        "user-a",
        "case-a",
        _BufferedAgent([]),
        "hello",
        {},
        on_finish=finalized.append,
    )
    assert started.wait(timeout=2)
    task._skip_finalization = True
    assert manager.cancel(task) is True
    gate.set()
    assert task.wait_for_worker(timeout=2)
    assert task.status == "cancelled"
    assert finalized == []


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


def test_deleting_case_waits_for_worker_and_skips_deleted_workspace_checkpoint():
    """Delete cancellation must quiesce the worker before files can move."""
    manager = ChatTaskManager()
    gate = threading.Event()
    started = threading.Event()
    finalized = []

    class _DeletingAgent(_Agent):
        def chat_with_stream(self, _message):
            started.set()
            yield _event("start", {})
            gate.wait(timeout=2)
            yield _event("response", {"response": "must be discarded"})

        def _cancel_active_turn(self):
            super()._cancel_active_turn()
            gate.set()

    task = manager.start(
        _App(),
        "user-a",
        "case-a",
        _DeletingAgent([]),
        "plan",
        {},
        on_finish=finalized.append,
    )
    assert started.wait(timeout=2)

    assert manager.cancel_session("user-a", "case-a", wait_timeout=2) is True
    assert task.status == "cancelled"
    assert task.wait_for_worker(timeout=0) is True
    assert finalized == []
    assert task.response == ""


def test_terminal_done_is_withheld_until_case_results_are_committed():
    """The UI must not observe completion before the turn commit callback returns."""

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


def test_idle_task_stream_emits_sse_keepalive_comment():
    """Long model phases must not be mistaken for a broken live connection."""
    task = ChatTask("task-id", "user-a", "case-a", _Agent([]), "hello")
    with patch.object(task._condition, "wait", return_value=False):
        event = next(task.iter_events(0))
    assert event == ": brachybot-task-alive\n\n"


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
