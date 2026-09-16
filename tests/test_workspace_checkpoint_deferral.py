"""Heavy-task checkpoint deferral tests for planning latency."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from web.workspace_store import WorkspaceStore


class _Memory:
    def __init__(self):
        self._lock = threading.RLock()
        self.planning_results = {"dose_metrics": {"v100": 90.0}}
        self._planning_versions = {key: 1 for key in self.planning_results}
        self.patient_data = {"site": "pancreas"}
        self.conversation = [{"role": "user", "content": "plan this case"}]
        self.tool_results = [{"tool": "ctv_segmentation", "success": True}]
        self.context_summary = "summary"
        self.compaction_count = 1
        self.current_phase = SimpleNamespace(value="planning")
        self.conversation_state = {"ctv_segmented": True}
        self.user_lang = "en"
        self._ui_state = {}

    def get_ui_state(self):
        return self._ui_state

    def retrieve(self, key, default=None):
        return self.planning_results.get(key, default)


class _Agent:
    def __init__(self):
        self.config = {"mode": "rule_based"}
        self.memory = _Memory()


def _case(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("defer_user", "hash")
    case = store.create_session(user["id"], "Deferral case")
    return store, user, case, _Agent()


def test_should_not_defer_without_probe(tmp_path):
    store, user, case, _agent = _case(tmp_path)
    store._checkpoint_completed_at[(user["id"], case.id)] = time.monotonic()
    assert store._should_defer_checkpoint(user["id"], case.id) is False


def test_should_not_defer_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS", "0")
    store, user, case, _agent = _case(tmp_path)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[(user["id"], case.id)] = time.monotonic()
    assert store.checkpoint_max_staleness_seconds == 0.0
    assert store._should_defer_checkpoint(user["id"], case.id) is False


def test_should_not_defer_without_completed_checkpoint(tmp_path):
    store, user, case, _agent = _case(tmp_path)
    store.set_heavy_task_probe(lambda _u, _s: True)
    assert store._should_defer_checkpoint(user["id"], case.id) is False


def test_defers_while_busy_and_fresh(tmp_path):
    store, user, case, _agent = _case(tmp_path)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[(user["id"], case.id)] = time.monotonic()
    assert store._should_defer_checkpoint(user["id"], case.id) is True


def test_does_not_defer_when_stale(tmp_path):
    store, user, case, _agent = _case(tmp_path)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[(user["id"], case.id)] = (
        time.monotonic() - store.checkpoint_max_staleness_seconds - 5.0
    )
    assert store._should_defer_checkpoint(user["id"], case.id) is False


def test_probe_failure_does_not_defer(tmp_path):
    store, user, case, _agent = _case(tmp_path)

    def _broken(_u, _s):
        raise RuntimeError("registry unavailable")

    store.set_heavy_task_probe(_broken)
    store._checkpoint_completed_at[(user["id"], case.id)] = time.monotonic()
    assert store._should_defer_checkpoint(user["id"], case.id) is False


def test_successful_checkpoint_records_completion_time(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    assert key not in store._checkpoint_completed_at
    store.snapshot_agent(user["id"], case.id, agent, reason="seed")
    assert key in store._checkpoint_completed_at
