"""Heavy-task checkpoint deferral tests for planning latency."""

from __future__ import annotations

import logging
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


def _install_counter(store):
    calls = []

    def _fake_snapshot(*args, **kwargs):
        calls.append(kwargs.get("reason"))
        return {}

    store._snapshot_agent_locked = _fake_snapshot
    return calls


def _cancel_timers(store, key):
    timer = store._checkpoint_timers.pop(key, None)
    if timer is not None:
        timer.cancel()


def test_timer_defers_and_rearms_while_busy(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    calls = _install_counter(store)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[key] = time.monotonic()
    try:
        store._checkpoint_timer(user["id"], case.id, agent, "test.defer", generation=0)
        assert calls == []
        assert key in store._checkpoint_timers
    finally:
        _cancel_timers(store, key)


def test_timer_runs_when_stale_even_if_busy(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    calls = _install_counter(store)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[key] = (
        time.monotonic() - store.checkpoint_max_staleness_seconds - 5.0
    )
    try:
        store._checkpoint_timer(user["id"], case.id, agent, "test.stale", generation=0)
        assert calls == ["test.stale"]
    finally:
        _cancel_timers(store, key)


def test_timer_runs_when_probe_idle(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    calls = _install_counter(store)
    store.set_heavy_task_probe(lambda _u, _s: False)
    store._checkpoint_completed_at[key] = time.monotonic()
    try:
        store._checkpoint_timer(user["id"], case.id, agent, "test.idle", generation=0)
        assert calls == ["test.idle"]
    finally:
        _cancel_timers(store, key)


def test_invalid_staleness_env_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS", "abc")
    store, _user, _case_obj, _agent = _case(tmp_path)
    assert store.checkpoint_max_staleness_seconds == 60.0


def test_non_finite_staleness_env_falls_back(tmp_path, monkeypatch):
    for value in ("nan", "inf", "-inf"):
        monkeypatch.setenv("BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS", value)
        store, _user, _case_obj, _agent = _case(tmp_path / value)
        assert store.checkpoint_max_staleness_seconds == 60.0


def test_negative_staleness_env_clamps_to_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS", "-5")
    store, _user, _case_obj, _agent = _case(tmp_path)
    assert store.checkpoint_max_staleness_seconds == 0.0


def test_superseded_checkpoint_does_not_record_completion(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    store._checkpoint_generations[key] = 5
    result = store._snapshot_agent_locked(
        user["id"], case.id, agent, reason="stale", checkpoint_generation=4,
    )
    assert result == {}
    assert key not in store._checkpoint_completed_at


def test_discard_checkpoint_clears_completion_time(tmp_path):
    store, user, case, _agent = _case(tmp_path)
    key = (user["id"], case.id)
    store._checkpoint_completed_at[key] = time.monotonic()
    store.discard_agent_checkpoint(user["id"], case.id)
    assert key not in store._checkpoint_completed_at


def test_deferral_cancels_orphaned_timer(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    fired = []
    orphan = threading.Timer(0.05, fired.append, args=("orphan",))
    orphan.daemon = True
    store._checkpoint_timers[key] = orphan
    orphan.start()
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[key] = time.monotonic()
    try:
        store._checkpoint_timer(user["id"], case.id, agent, "test.orphan", generation=0)
        time.sleep(0.25)
        assert fired == []
        assert key in store._checkpoint_timers
    finally:
        _cancel_timers(store, key)


def test_flush_checkpoint_is_not_deferred_while_busy(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    calls = _install_counter(store)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[key] = time.monotonic()
    store.flush_agent_checkpoint(user["id"], case.id, agent, "test.flush")
    assert calls == ["test.flush"]


def test_discard_cancels_deferred_timer(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[key] = time.monotonic()
    store._checkpoint_timer(user["id"], case.id, agent, "test.defer", generation=0)
    assert key in store._checkpoint_timers
    store.discard_agent_checkpoint(user["id"], case.id)
    assert key not in store._checkpoint_timers
    assert key not in store._checkpoint_completed_at


def test_deferral_does_not_resurrect_superseded_checkpoint(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    calls = _install_counter(store)
    store._checkpoint_completed_at[key] = time.monotonic()

    def _probe(_u, _s):
        store._checkpoint_generations[key] = store._checkpoint_generations.get(key, 0) + 1
        return True

    store.set_heavy_task_probe(_probe)
    try:
        store._checkpoint_timer(user["id"], case.id, agent, "test.superseded", generation=0)
        assert calls == []
        assert key not in store._checkpoint_timers
    finally:
        _cancel_timers(store, key)


def test_staleness_forced_run_logs_info(tmp_path, caplog):
    store, user, case, _agent = _case(tmp_path)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[(user["id"], case.id)] = time.monotonic() - 999.0
    with caplog.at_level(logging.INFO, logger="web.workspace_store"):
        assert store._should_defer_checkpoint(user["id"], case.id) is False
    assert any("forced by staleness" in record.message for record in caplog.records)


def test_create_app_wires_heavy_task_probe(tmp_path):
    from web.server import create_app

    app = create_app({
        "runtime_dir": str(tmp_path / "server-runtime"),
        "secret_key": "test-secret",
        "workspace_maintenance": False,
    })
    store = app.extensions["brachybot_workspace_store"]
    assert store._heavy_task_probe is not None
    assert store._heavy_task_probe("missing-user", "0" * 32) is False


def test_wired_probe_reflects_running_task(tmp_path):
    from web.server import create_app

    app = create_app({
        "runtime_dir": str(tmp_path / "server-runtime"),
        "secret_key": "test-secret",
        "workspace_maintenance": False,
    })
    store = app.extensions["brachybot_workspace_store"]

    class _Registry:
        def live(self, _user_id, _session_id):
            return object()

    app.extensions["brachybot_chat_tasks"] = _Registry()
    assert store._heavy_task_probe("u", "s") is True
