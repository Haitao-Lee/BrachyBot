# Checkpoint Coalescing + UI Bridge Sidecar + Planning Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ① An in-flight snapshot is no longer cancelled by routine scheduling (during busy periods it coalesces into a single follow-up); ② UI bridge state moves to a small sidecar file, so a 30MB snapshot is no longer rewritten for UI events; ③ planning latency logs gain loadavg/CPU-time attribution.

**Architecture:** A. `WorkspaceStore` gains `_checkpoint_inflight/_checkpoint_dirty`; `schedule_agent_checkpoint` only sets dirty while a snapshot is in flight, and one coalesced follow-up is added when the snapshot finishes; B. add `save_ui_bridge/load_ui_bridge` sidecar + pick the newer by timestamp on recovery; C. `plans/performance.py` records and outputs contention context.

**Tech Stack:** Python 3.12, Flask, pytest, `~/.conda/envs/brachytherapy/bin/python`.

**Spec:** `docs/superpowers/specs/2026-09-16-checkpoint-coalescing-ui-bridge-design.md`

**Run Convention:** pytest is executed at the repository root `<workspace>/BrachyBot`; the dirty worktree contains a lot of unrelated WIP, so the implementer should only change this task's files, not revert any existing changes, and not run any git write commands (the controller cherry-picks commits selectively).

**Rollback:** A/B can be rolled back independently (B reverts to the one-line `save_snapshot_patch`); C is logging only.

---

## File Structure

| File | Responsibility |
|---|---|
| `web/workspace_store.py` (modify) | inflight/dirty, coalesced follow-up, sidecar read/write |
| `web/routes/planning_routes.py` (modify) | `_flush_ui_bridge_checkpoint` switched to the sidecar |
| `web/server.py` (modify) | choose the snapshot bridge/sidecar bridge by timestamp on recovery (new module-level helper) |
| `plans/performance.py` (modify) | contention attribution fields |
| `tests/test_workspace_checkpoint_deferral.py` (append) | tests for A |
| `tests/test_ui_bridge_sidecar.py` (new) | tests for B |
| `tests/test_planning_latency_profile.py` (append) | tests for C |

---

### Task 1: Checkpoint Coalescing (do not cancel in-flight snapshots)

**Files:** Modify `web/workspace_store.py` (`__init__`, `schedule_agent_checkpoint`, `_snapshot_agent_locked` split + wrapper, `flush_agent_checkpoint`, `discard_agent_checkpoint`); Append tests `tests/test_workspace_checkpoint_deferral.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_workspace_checkpoint_deferral.py`:

```python
def test_schedule_during_inflight_coalesces(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    store._checkpoint_inflight[key] = True
    generation_before = store._checkpoint_generations.get(key, 0)
    store.schedule_agent_checkpoint(user["id"], case.id, agent, "test.inflight")
    assert store._checkpoint_generations.get(key, 0) == generation_before
    assert key not in store._checkpoint_timers
    assert store._checkpoint_dirty.get(key) is True


def test_inflight_completion_schedules_coalesced_followup(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)

    def _inner(*args, **kwargs):
        store.schedule_agent_checkpoint(user["id"], case.id, agent, "test.during")
        return {}

    store._snapshot_agent_locked_inner = _inner
    try:
        store._snapshot_agent_locked(user["id"], case.id, agent, reason="test.run")
        assert key not in store._checkpoint_inflight
        assert key not in store._checkpoint_dirty
        assert key in store._checkpoint_timers
        timer = store._checkpoint_timers[key]
        assert timer.args[3] == "test.run.coalesced"
    finally:
        _cancel_timers(store, key)
        store._snapshot_agent_locked_inner = None


def test_flush_clears_dirty(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    store._checkpoint_dirty[key] = True
    store._snapshot_agent_locked_inner = lambda *a, **k: {}
    try:
        store.flush_agent_checkpoint(user["id"], case.id, agent, "test.flush")
        assert key not in store._checkpoint_dirty
    finally:
        store._snapshot_agent_locked_inner = None
        _cancel_timers(store, key)
```

(`timer.args` is the constructor-argument tuple of `threading.Timer`: `(user_id, session_id, agent, reason, operation, generation)`.)

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py -q
```
Expected: the 3 new cases FAIL (`_checkpoint_inflight` does not exist / `_snapshot_agent_locked_inner` does not exist / dirty not cleared).

- [ ] **Step 3: Implement**

In `__init__` (immediately after the `_checkpoint_completed_at` initialization), add:

```python
        # Coalesce checkpoint scheduling while a full snapshot is in flight:
        # a new schedule must not cancel the running write, and the skipped
        # mutation is replayed once as a follow-up after it completes.
        self._checkpoint_inflight: Dict[Tuple[str, str], bool] = {}
        self._checkpoint_dirty: Dict[Tuple[str, str], bool] = {}
```

At the start of the `with self._lock:` block in `schedule_agent_checkpoint` (before `existing = ...`), insert:

```python
            if self._checkpoint_inflight.get(key):
                self._checkpoint_dirty[key] = True
                logger.debug(
                    "workspace checkpoint coalesced session=%s reason=%s",
                    session_id, reason,
                )
                return
```

Rename the existing `_snapshot_agent_locked` entirely to `_snapshot_agent_locked_inner` (content unchanged), and add a wrapper:

```python
    def _snapshot_agent_locked(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        *,
        reason: str = "agent.checkpoint",
        operation: Optional[Mapping[str, Any]] = None,
        checkpoint_generation: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run one full snapshot and replay coalesced schedules afterwards."""
        if checkpoint_generation is not None:
            with self._lock:
                current_generation = self._checkpoint_generations.get(
                    (user_id, session_id), 0
                )
            if int(checkpoint_generation) != int(current_generation):
                logger.debug(
                    "workspace checkpoint skipped stale session=%s reason=%s generation=%s current_generation=%s",
                    session_id, reason, checkpoint_generation, current_generation,
                )
                return {}
        key = (str(user_id), str(session_id))
        with self._lock:
            self._checkpoint_inflight[key] = True
        try:
            return self._snapshot_agent_locked_inner(
                user_id,
                session_id,
                agent,
                reason=reason,
                operation=operation,
                checkpoint_generation=checkpoint_generation,
            )
        finally:
            with self._lock:
                self._checkpoint_inflight.pop(key, None)
                dirty = self._checkpoint_dirty.pop(key, None)
            if dirty:
                logger.info(
                    "workspace checkpoint coalesced follow-up session=%s reason=%s",
                    session_id, reason,
                )
                self.schedule_agent_checkpoint(
                    user_id, session_id, agent, f"{reason}.coalesced",
                )
```

Inside the `with self._lock:` of `flush_agent_checkpoint`, before `generation = ...`, add:

```python
            self._checkpoint_dirty.pop(key, None)
```

Also add inside the `with self._lock:` of `discard_agent_checkpoint`:

```python
            self._checkpoint_dirty.pop(key, None)
```

- [ ] **Step 4: Run tests**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py tests/test_workspace_store.py tests/test_workspace_frontend.py -q
```
Expected: all green (including the existing superseded/discard/orphan cases).

- [ ] **Step 5 (do NOT do): Commit — controller handles it.**

---

### Task 2: UI Bridge Sidecar Persistence

**Files:** Modify `web/workspace_store.py` (add two methods), `web/routes/planning_routes.py` (`_flush_ui_bridge_checkpoint`), `web/server.py` (add helper + call at recovery); Create `tests/test_ui_bridge_sidecar.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui_bridge_sidecar.py`:

```python
"""UI bridge sidecar persistence tests (no full-snapshot rewrites)."""

from __future__ import annotations

from web.server import _select_case_bridge
from web.workspace_store import WorkspaceStore


def _store(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("bridge_user", "hash")
    case = store.create_session(user["id"], "Bridge case")
    return store, user, case


def test_ui_bridge_roundtrip(tmp_path):
    store, user, case = _store(tmp_path)
    store.save_ui_bridge(
        user["id"],
        case.id,
        {"state": {"viewer": {"axial": 12}}, "events": [{"type": "x"}],
         "training": {}, "updated_at": 123.0},
        reason="ui.state_saved",
    )
    loaded = store.load_ui_bridge(user["id"], case.id)
    assert loaded["state"] == {"viewer": {"axial": 12}}
    assert loaded["events"] == [{"type": "x"}]
    assert loaded["reason"] == "ui.state_saved"
    assert float(loaded["saved_at"]) > 0


def test_ui_bridge_missing_returns_empty(tmp_path):
    store, user, case = _store(tmp_path)
    assert store.load_ui_bridge(user["id"], case.id) == {}


def test_ui_bridge_invalid_json_returns_empty(tmp_path):
    store, user, case = _store(tmp_path)
    root = store.workspace_root(user["id"], case.id, create=True)
    (root / "ui_bridge.json").write_text("{not json", encoding="utf-8")
    assert store.load_ui_bridge(user["id"], case.id) == {}


def test_select_case_bridge_prefers_newer_sidecar():
    snapshot = {"state": {"a": 1}, "updated_at": 100.0}
    sidecar = {"state": {"a": 2}, "saved_at": 200.0}
    assert _select_case_bridge(snapshot, sidecar)["state"] == {"a": 2}


def test_select_case_bridge_falls_back_to_snapshot():
    snapshot = {"state": {"a": 1}, "updated_at": 300.0}
    sidecar = {"state": {"a": 2}, "saved_at": 200.0}
    assert _select_case_bridge(snapshot, sidecar)["state"] == {"a": 1}
    assert _select_case_bridge(snapshot, {})["state"] == {"a": 1}
    assert _select_case_bridge({}, {}) == {}


def test_flush_ui_bridge_uses_sidecar_writer(tmp_path):
    from web.routes import planning_routes

    calls = []

    class _Store:
        def save_ui_bridge(self, user_id, session_id, bridge, *, reason=""):
            calls.append((user_id, session_id, dict(bridge), reason))

        def save_snapshot_patch(self, *args, **kwargs):
            raise AssertionError("bridge flush must not rewrite the full snapshot")

    key = ("user-1", "case-1")
    planning_routes._UI_BRIDGE_CHECKPOINT_PENDING[key] = (
        _Store(), "user-1", "case-1", {"state": {"a": 1}}, "ui.state_saved",
    )
    try:
        planning_routes._flush_ui_bridge_checkpoint(key)
    finally:
        planning_routes._UI_BRIDGE_CHECKPOINT_PENDING.pop(key, None)
        planning_routes._UI_BRIDGE_CHECKPOINT_TIMERS.pop(key, None)
    assert calls == [("user-1", "case-1", {"state": {"a": 1}}, "ui.state_saved")]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_ui_bridge_sidecar.py -q
```
Expected: FAIL (`ImportError: _select_case_bridge` / `AttributeError: save_ui_bridge`).

- [ ] **Step 3: Implement**

`web/workspace_store.py`, add before `set_heavy_task_probe`:

```python
    def save_ui_bridge(
        self,
        user_id: str,
        session_id: str,
        bridge: Mapping[str, Any],
        *,
        reason: str = "ui.bridge",
    ) -> None:
        """Persist UI bridge telemetry without rewriting the case snapshot.

        High-frequency UI events (sliders, monitor status) belong to a small
        sidecar so a 30MB snapshot rewrite is not paid per event. The snapshot
        keeps its last bridge copy as a read-only fallback for older cases.
        """
        self.get_session(user_id, session_id)
        payload = dict(bridge) if isinstance(bridge, Mapping) else {}
        payload["reason"] = str(reason)
        payload["saved_at"] = time.time()
        root = self.workspace_root(user_id, session_id, create=True)
        _atomic_json(_safe_workspace_child(root, "ui_bridge.json"), payload)

    def load_ui_bridge(self, user_id: str, session_id: str) -> Dict[str, Any]:
        """Return persisted sidecar bridge state, or {} when absent/invalid."""
        try:
            self.get_session(user_id, session_id)
            root = self.workspace_root(user_id, session_id)
            path = _safe_workspace_child(root, "ui_bridge.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (WorkspaceError, OSError, ValueError, TypeError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}
```

inside `_flush_ui_bridge_checkpoint` in `web/routes/planning_routes.py`:

```python
    store, user_id, selected, bridge, reason = item
    try:
        store.save_ui_bridge(user_id, selected, bridge, reason=reason)
    except WorkspaceNotFound:
        ...
```

(Replaces the original `store.save_snapshot_patch(...)` call; the exception-handling branch stays as is.)

`web/server.py`: add a module-level helper (near `_case_has_running_chat_task`):

```python
def _select_case_bridge(snapshot_bridge: Any, sidecar_bridge: Any) -> dict:
    """Prefer the newest persisted UI bridge between snapshot and sidecar."""
    snapshot = snapshot_bridge if isinstance(snapshot_bridge, Mapping) else {}
    sidecar = sidecar_bridge if isinstance(sidecar_bridge, Mapping) else {}

    def _stamp(payload: Mapping[str, Any], field: str) -> float:
        try:
            return float(payload.get(field) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    if _stamp(sidecar, "saved_at") > _stamp(snapshot, "updated_at"):
        return dict(sidecar)
    return dict(snapshot)
```

At `web/server.py:583`, replace with:

```python
            bridge = _select_case_bridge(
                (hydrated_snapshot.get("ui") or {}).get("bridge") or {},
                workspace_store.load_ui_bridge(user["id"], resolved_session_id),
            )
```

(The following `if isinstance(bridge, dict):` block stays unchanged. `Mapping` is already imported in server.py; add the import if not.)

- [ ] **Step 4: Run tests**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_ui_bridge_sidecar.py tests/test_workspace_store.py tests/test_workspace_frontend.py tests/test_workspace_server_recovery_indicator.py -q
```
Expected: all green.

- [ ] **Step 5 (do NOT do): Commit — controller handles it.**

---

### Task 3: Planning Contention Attribution

**Files:** Modify `plans/performance.py`；Append tests `tests/test_planning_latency_profile.py`。

- [ ] **Step 1: Write the failing test**

Append to `tests/test_planning_latency_profile.py`:

```python
def test_profile_records_contention_context():
    result = SimpleNamespace(success=True, metadata={})

    @collect_planning_latency
    def request():
        return result

    assert request() is result
    contention = result.metadata['latency_profile']['contention']
    for field in (
        'loadavg_1m_start', 'loadavg_1m_end', 'process_cpu_seconds',
        'wall_seconds', 'avg_parallelism', 'threads_start', 'threads_end',
    ):
        assert isinstance(contention[field], (int, float)), field
    assert contention['wall_seconds'] >= 0.0
    assert contention['avg_parallelism'] >= 0.0
    assert contention['threads_end'] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_planning_latency_profile.py -q
```
Expected: the new case FAILs (`KeyError: 'contention'`); the rest pass.

- [ ] **Step 3: Implement**

`plans/performance.py`:

- Add `import os` and `import threading` to the top imports;
- Add a helper:

```python
def _loadavg_1m() -> float:
    try:
        return float(os.getloadavg()[0])
    except (OSError, AttributeError, ValueError):
        return 0.0
```

- Change `collect_planning_latency` to:

```python
def collect_planning_latency(function):
    @wraps(function)
    def run(*args, **kwargs):
        profile = {}
        token = _profile.set(profile)
        started = time.perf_counter()
        cpu_started = time.process_time()
        threads_started = threading.active_count()
        load_started = _loadavg_1m()
        try:
            result = function(*args, **kwargs)
            metadata = getattr(result, 'metadata', None)
            if isinstance(metadata, dict):
                wall = time.perf_counter() - started
                cpu = time.process_time() - cpu_started
                metadata['latency_profile'] = {
                    'total_seconds': wall,
                    'nested_timings': profile,
                    'contention': {
                        'loadavg_1m_start': load_started,
                        'loadavg_1m_end': _loadavg_1m(),
                        'process_cpu_seconds': cpu,
                        'wall_seconds': wall,
                        'avg_parallelism': (cpu / wall) if wall > 0 else 0.0,
                        'threads_start': threads_started,
                        'threads_end': threading.active_count(),
                    },
                }
            return result
        finally:
            wall = time.perf_counter() - started
            cpu = time.process_time() - cpu_started
            parallelism = (cpu / wall) if wall > 0 else 0.0
            logger.info(
                '[planning_latency] total_seconds=%.3f cpu_seconds=%.3f '
                'parallelism=%.2f load1=%.2f nested_timings=%s',
                wall, cpu, parallelism, _loadavg_1m(), profile,
            )
            _profile.reset(token)
    return run
```

- [ ] **Step 4: Run tests**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_planning_latency_profile.py tests/test_planning_latency_equivalence.py -q
```
Expected: all green (existing concurrency-isolation/exception-recovery cases unaffected).

- [ ] **Step 5 (do NOT do): Commit — controller handles it.**

---

### Task 4: Regression + End-to-End Acceptance

- [ ] **Step 1: Regression set**

```bash
env -u BRACHYBOT_API_KEY ~/.conda/envs/brachytherapy/bin/python -m pytest \
  tests/test_workspace_checkpoint_deferral.py tests/test_ui_bridge_sidecar.py \
  tests/test_planning_latency_profile.py tests/test_planning_latency_equivalence.py \
  tests/test_workspace_store.py tests/test_workspace_frontend.py \
  tests/test_chat_tasks.py tests/test_chat_case_resources_wait.py \
  tests/test_workspace_lease_ux.py tests/test_workspace_server_recovery_indicator.py \
  tests/test_workspace_auth.py tests/test_public_deployment.py -q
```

- [ ] **Step 2: Server acceptance (run by the user)**

Restart the server (to load the new code) → rerun one planning + guide session, and check:

1. During long tasks, no consecutive `checkpoint cancelled stale` appears; `checkpoint started` can reach `completed`;
2. `Slow request` no longer shows a 5–9s `POST /api/workspace/state` (sidecar effective);
3. The new `[planning_latency]` fields explain wall-clock time: a quiet window has low `load1`; a busy window has high `load1` and high `parallelism`;
4. Result metrics are unchanged; after opening an old case/a new case/deleting a case, the UI bridge state recovers normally.

---

## Self-Review

- **Spec coverage:** §3A → Task 1; §3B → Task 2; §3C → Task 3; §5 tests → each task; §6 acceptance → Task 4; §4 compatibility/rollback → tests (behavior unchanged when nothing is in flight, old workspace falls back to snapshot, C only adds fields) + commit notes.
- **Placeholder scan:** no TBD/TODO; every code step contains complete code and commands.
- **Type consistency:** `_checkpoint_inflight`/`_checkpoint_dirty` (Dict keys are `(str, str)`), `save_ui_bridge/load_ui_bridge`, `_select_case_bridge`, and the `contention` field naming are consistent between tasks and tests; the `_snapshot_agent_locked` wrapper keeps the original signature, and `_snapshot_agent_locked_inner` is only renamed.
- **Existing test compatibility:** the wrapper keeps the stale-generation early-exit semantics (relied on by the test `test_superseded_checkpoint_does_not_record_completion`); the `_checkpoint_timer`/defer logic is untouched.
