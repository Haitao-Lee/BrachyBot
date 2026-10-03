# Planning Checkpoint Deferral Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** During heavy recomputation (planning/guide/segmentation), defer full workspace checkpoints within a bounded staleness ceiling, reclaiming planning wall-clock time consumed by persistence, while guaranteeing final results are completely unchanged from the existing persistence semantics.

**Architecture:** Inject a read-only "case busy" probe into `WorkspaceStore` (reusing the existing `_case_has_running_chat_task`). Before actually writing to disk, the scheduling timer checks: if busy and less than 60s since the last successful write, it re-arms a 3s timer; otherwise it writes as usual and refreshes the timestamp. `flush_agent_checkpoint` and all patch paths bypass this decision, and the checkpoint is still written synchronously when the task ends.

**Tech Stack:** Python 3.12, Flask, threading.Timer, pytest, `~/.conda/envs/brachytherapy/bin/python`.

**Spec:** `docs/superpowers/specs/2026-09-16-planning-checkpoint-deferral-design.md`

**Run convention:** All pytest commands run from the repo root `<workspace>/BrachyBot`, using the interpreter `~/.conda/envs/brachytherapy/bin/python`. By convention, new test files add `tests/` to the import path (see `tests/conftest.py`; no action needed on your part).

**Constraints:** Do not change `plans/*`, `tool_factory/seed_plan/*`, the snapshot schema, or revision/lease semantics; behavior matches the status quo when no probe is injected; one-command rollback via `BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS=0`.

---

## File Structure

| File | Responsibility |
|---|---|
| `web/workspace_store.py` (modify) | Probe injection, staleness ceiling, completion timestamp, deferral decision, timer integration |
| `web/server.py` (modify, around `:320`) | Wire `_case_has_running_chat_task` as the store's probe |
| `tests/test_workspace_checkpoint_deferral.py` (new) | Decision function/timer/wiring/rollback tests |

---

### Task 1: WorkspaceStore deferral decision component

**Files:**
- Modify: `web/workspace_store.py` (constructor around `:1647`; in `_snapshot_agent_locked` around `:2661`, before `return result`)
- Test: `tests/test_workspace_checkpoint_deferral.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workspace_checkpoint_deferral.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py -q
```

Expected: `FAILED` (`AttributeError: 'WorkspaceStore' object has no attribute 'set_heavy_task_probe'`, etc.).

- [ ] **Step 3: Implement the store components**

In the `web/workspace_store.py` module constants section (near constants such as `TRANSIENT_COLLECTION_LIMIT`), add:

```python
def _checkpoint_max_staleness_seconds() -> float:
    """Bound how long a busy case may defer its scheduled full checkpoint.

    ``0`` disables deferral entirely and restores the pre-deferral timing.
    Invalid values fall back to the default instead of disabling durability.
    """
    default = 60.0
    raw = os.environ.get("BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS")
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS=%r; using %.0f",
            raw,
            default,
        )
        return default
    return max(0.0, value)


DEFER_RETRY_SECONDS = 3.0
```

In `WorkspaceStore.__init__` (near the `self._checkpoint_generations` initialization), add:

```python
        # A busy case may defer its debounced full checkpoint for a bounded
        # window so planning does not compete with 30MB snapshot rewrites.
        # Without an injected probe the timer runs exactly as before.
        self._heavy_task_probe: Optional[Callable[[str, str], bool]] = None
        self._checkpoint_completed_at: Dict[Tuple[str, str], float] = {}
        self.checkpoint_max_staleness_seconds = _checkpoint_max_staleness_seconds()
```

Before `schedule_agent_checkpoint` in `WorkspaceStore`, add two methods:

```python
    def set_heavy_task_probe(
        self, probe: Optional[Callable[[str, str], bool]],
    ) -> None:
        """Install the per-case heavy-task query used to defer checkpoints.

        The probe is query-only and must stay cheap: it is called for every
        scheduled checkpoint of an active case.
        """
        self._heavy_task_probe = probe

    def _should_defer_checkpoint(self, user_id: str, session_id: str) -> bool:
        """Return whether a scheduled checkpoint should wait for a busy case.

        Deferral is opt-in: without an injected probe, a positive staleness
        window, or one already completed checkpoint, the timer runs now.
        """
        if self.checkpoint_max_staleness_seconds <= 0:
            return False
        probe = self._heavy_task_probe
        if probe is None:
            return False
        key = (str(user_id), str(session_id))
        with self._lock:
            completed_at = self._checkpoint_completed_at.get(key)
        if completed_at is None:
            return False
        try:
            busy = bool(probe(key[0], key[1]))
        except Exception:
            logger.debug(
                "Heavy task probe failed; checkpoint will run now", exc_info=True,
            )
            return False
        if not busy:
            return False
        return (time.monotonic() - completed_at) < self.checkpoint_max_staleness_seconds
```

Record the timestamp before the successful return in `_snapshot_agent_locked` (existing code:

```python
            logger.info(
                "workspace checkpoint completed session=%s reason=%s duration_ms=%.1f commit_ms=%.1f discarded=%s",
                session_id, reason, (time.perf_counter() - started) * 1000.0,
                (time.perf_counter() - commit_started) * 1000.0, not bool(result),
            )
            return result
```

Change to insert before `return result`):

```python
            if result:
                with self._lock:
                    self._checkpoint_completed_at[
                        (str(user_id), str(session_id))
                    ] = time.monotonic()
            return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py -q
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_store.py -q
```

Expected: all new tests PASS; `test_workspace_store.py` all green (behavior unchanged).

- [ ] **Step 5: Commit**

```bash
git add web/workspace_store.py tests/test_workspace_checkpoint_deferral.py
git commit -m "perf(workspace): add heavy-task checkpoint deferral decision"
```

---

### Task 2: Timer deferral and re-arming

**Files:**
- Modify: `web/workspace_store.py` (`_checkpoint_timer`, around `:3631-3678`)
- Test: `tests/test_workspace_checkpoint_deferral.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_workspace_checkpoint_deferral.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py -q
```

Expected: the 3 new cases FAIL (`calls == ["test.defer"]` in `test_timer_defers_and_rearms_while_busy`); the rest PASS.

- [ ] **Step 3: Implement the timer integration**

Insert after the first `with self._lock:` block in `_checkpoint_timer` and before `work_lock = self._checkpoint_work_lock(...)`:

```python
        if self._should_defer_checkpoint(user_id, session_id):
            with self._lock:
                latest_generation = self._checkpoint_generations.get(key, 0)
                retry = threading.Timer(
                    DEFER_RETRY_SECONDS,
                    self._checkpoint_timer,
                    args=(user_id, session_id, agent, reason, operation, latest_generation),
                )
                retry.daemon = True
                self._checkpoint_timers[key] = retry
                retry.start()
            logger.debug(
                "workspace checkpoint deferred session=%s reason=%s",
                session_id, reason,
            )
            return
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py tests/test_workspace_store.py tests/test_workspace_frontend.py -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add web/workspace_store.py tests/test_workspace_checkpoint_deferral.py
git commit -m "perf(workspace): defer scheduled checkpoints while a heavy case task runs"
```

---

### Task 3: server wiring

**Files:**
- Modify: `web/server.py` (in `create_app`, after `workspace_store = WorkspaceStore(...)`, around `:320`)
- Test: `tests/test_workspace_checkpoint_deferral.py` (append)

- [ ] **Step 1: Write the failing test**

Append:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py::test_create_app_wires_heavy_task_probe -q
```

Expected: FAIL (`assert None is not None`).

- [ ] **Step 3: Implement the wiring**

Insert after `workspace_store = WorkspaceStore(config.get("runtime_dir"))` in `web/server.py` (`_case_has_running_chat_task` is a module-level function; `brachybot_chat_tasks` is registered by `register_planning_routes`, so it must be looked up at call time):

```python
    workspace_store.set_heavy_task_probe(
        lambda user_id, session_id: _case_has_running_chat_task(
            app.extensions.get("brachybot_chat_tasks"), user_id, session_id
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py -q
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_chat_tasks.py tests/test_workspace_server_recovery_indicator.py tests/test_workspace_lease_ux.py -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add web/server.py tests/test_workspace_checkpoint_deferral.py
git commit -m "perf(server): wire chat-task probe into checkpoint deferral"
```

---

### Task 4: Regression and end-to-end acceptance

**Files:**
- No code changes (beyond the three tasks above)

- [ ] **Step 1: Run the full regression set**

```bash
env -u BRACHYBOT_API_KEY ~/.conda/envs/brachytherapy/bin/python -m pytest \
  tests/test_workspace_store.py tests/test_workspace_frontend.py \
  tests/test_chat_tasks.py tests/test_chat_case_resources_wait.py \
  tests/test_workspace_lease_ux.py tests/test_workspace_server_recovery_indicator.py \
  tests/test_workspace_auth.py tests/test_public_deployment.py -q
```

Expected: all PASS (`test_workspace_auth.py` must run in an environment without `BRACHYBOT_API_KEY`; otherwise there is a known environmental 401).

- [ ] **Step 2: Restart the server and reproduce one planning run**

```bash
ps -eo pid,cmd | grep '[w]eb/server.py'   # note the old pid, then restart using your usual method
grep -n 'Step 3/5\|Step 4/5' .runtime/logs/server.log | tail -4
```

In the UI, rerun planning with **the same case and the same parameters**; record the timestamps of `Step 3/5` and `Step 4/5`.

- [ ] **Step 3: Count checkpoints within the window and compare**

```bash
~/.conda/envs/brachytherapy/bin/python - <<'PY'
import re
from pathlib import Path
lines = Path('.runtime/logs/server.log').read_text().splitlines()
start = end = None
for i, line in enumerate(lines):
    if 'Step 3/5' in line:
        start = i
    if start is not None and 'Step 4/5' in line:
        end = i
        break
window = lines[start:end] if start is not None else []
started = [l for l in window if 'checkpoint started' in l]
print('steps:', lines[start][:30] if start is not None else 'n/a', '->', lines[end][:30] if end else 'n/a')
print('checkpoints in window:', len(started))
print('request.completed:', sum('request.completed' in l for l in started))
PY
```

Expected (against the 2026-09-16 16:40 baseline: Step 3 = 160.1s, 20 checkpoints / 17 `request.completed`): ≤3 checkpoints in the window, and a marked drop in Step 3 wall-clock time.

- [ ] **Step 4: Verify results and UI behavior are unchanged**

Compare against the planning result before the change (same case): `total_seeds`, `num_trajectories`, `v100/v150/v200/d90` must be identical; in the UI confirm: planning progress works normally, chat works normally, reopening data after switching cases is complete, and the case can be recovered after restarting the server (no missing masks/dose/seed data).

- [ ] **Step 5: Verify the rollback switch (optional)**

Restart the server with `BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS=0`, rerun planning once, and the number of checkpoints should return to a level close to the baseline, proving the one-command rollback works.

---

## Self-Review

- **Spec coverage**: 3.1 components → Task 1; 3.2 scheduling integration → Task 2; 3.3 server wiring → Task 3; 3.4 logging → the `logger.debug` in Task 2's code + existing logs unchanged; §5 test plan → Tasks 1/2/3; §6 acceptance → Task 4; §7 rollback → Task 4 Step 5; §4 compatibility → Task 1's probe None/env=0 cases + the regression set + flush unaffected (flush does not go through `_checkpoint_timer`, and Task 2 did not change that path).
- **Placeholder scan**: no TBD/TODO; every code step provides complete code and commands.
- **Type consistency**: the signatures and names of `set_heavy_task_probe`, `_should_defer_checkpoint`, `_checkpoint_completed_at`, `checkpoint_max_staleness_seconds`, and `DEFER_RETRY_SECONDS` are consistent across the three tasks; the `_checkpoint_timer` parameter order `(user_id, session_id, agent, reason, operation, generation)` matches the existing implementation.
