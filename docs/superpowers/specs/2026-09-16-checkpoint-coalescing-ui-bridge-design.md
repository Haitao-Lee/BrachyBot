# Busy-Time Checkpoint Coalescing + UI Bridge Sidecar Persistence + Planning Attribution Design

- Date: 2026-09-16
- Status: Pending review
- Involves: `web/workspace_store.py`, `web/routes/planning_routes.py`, `web/server.py`, `plans/performance.py` + tests
- Hard constraints: Do not break existing functionality; default behavior matches the status quo when there are no heavy tasks and no new files; rollback is possible.

## 1. Background and Evidence (measured 2026-09-16)

1. Checkpoint deferral during planning is already in effect (20 → 2 times in the 17:51 window, all completed).
2. Newly discovered waste: **guide-template stage (while the same chat task is still running) 21 checkpoint starts, 0 completions, 20 cancellations**. Cause: the UI continuously POSTs → `after_request` calls `schedule_agent_checkpoint` on every request → each call bumps the generation → the snapshot being prepared is judged stale and discarded; all 30MB rewrites are wasted, and UI requests take 5–18s with "connection interrupted" appearing in the browser (task logs can reconnect, no data loss, but poor experience).
3. Every `POST /api/workspace/state` goes through `_flush_ui_bridge_checkpoint` → `save_snapshot_patch`, **fully rewriting snapshot.json (~30MB) and bumping the revision** (a 7.6s → 409 conflict appears in the logs).
4. Planning absolute wall-clock time is affected 2–3x by machine contention (standalone replay 51s vs in-server 177s); current logs cannot attribute this directly (missing loadavg / CPU time).

## 2. Goals / Non-Goals

Goals:
1. **Do not let new routine scheduling cancel an "in-flight" snapshot**; skipped changes are compensated once via a "coalesced follow-up", ensuring final persistence is not lost and there is no repeated storm.
2. **Change the UI bridge state to a small sidecar file** (atomic write), no longer rewriting 30MB for UI events; the reader stays backward compatible (falls back to snapshot content when an old workspace has no sidecar).
3. `[planning_latency]` gains machine-contention attribution fields (loadavg, process CPU time, average parallelism, active thread count).

Non-goals:
- Do not change the `snapshot.json` schema; do not change revision/lease semantics; do not change the planning algorithm; do not implement incremental snapshots (can be evaluated later).
- Do not change `flush_agent_checkpoint` (task end / control plane must be synchronous).

## 3. Design

### A. Checkpoint Coalescing (`web/workspace_store.py`)

New (`__init__`, all protected by `self._lock`):
- `_checkpoint_inflight: Dict[Tuple[str, str], int]` (value = generation at the start of the in-flight snapshot)
- `_checkpoint_dirty: Dict[Tuple[str, str], Dict[str, Any]]` (value = payload of the most recent coalesced scheduling)

`schedule_agent_checkpoint`:
- Within the existing `with self._lock:`, first check: `_checkpoint_inflight[key]` exists (value = generation at the start of the in-flight snapshot) **and the current generation equals it** → coalesce: `_checkpoint_dirty[key] = {"agent", "reason", "operation"}` (keep the payload of the most recent scheduling), `logger.debug("workspace checkpoint coalesced ...")`, **return directly** (do not bump generation, do not touch the timer).
- Once an external writer bumps the generation (e.g. partial writers such as `save_agent_results_patch`, flush, discard), the in-flight snapshot is now invalid: subsequent scheduling **returns to the original path** (cancel the old timer, bump the generation, schedule a new timer according to the payload), consistent with the pre-change semantics, avoiding swallowing a full checkpoint explicitly queued by the caller.
- When the in-flight snapshot finishes (in `finally`, holding the lock): if a coalesced payload exists and the generation is unchanged → replay that payload (`reason` appends `.coalesced` only once, using the captured agent/operation; exceptions are logged as warning only and do not mask the original exception); if the generation has changed → discard the older payload and log debug (the newer writer is responsible for persistence). Replay and the generation check complete in the same critical section.

`_snapshot_agent_locked` (wrapper; rename the original body to `_snapshot_agent_locked_inner`):
- After the early generation-exit branch at the start, `with self._lock:` record `generation_at_entry` and set `_checkpoint_inflight[key] = generation_at_entry`;
- Wrap the inner call in an outer `try/finally`: in `finally`, within the same critical section, clear inflight, pop the coalesced payload, and if the generation is unchanged replay it (using the captured agent/operation, `reason` appends `.coalesced` only once, scheduling exceptions are logged as warning only); if the generation has changed, discard the older payload and log debug.
- The existing `_CheckpointSuperseded` / discard semantics remain unchanged (flush/discard still bump the generation and can cancel an in-flight snapshot).

`flush_agent_checkpoint` / `discard_agent_checkpoint`:
- Within each `with self._lock:`, `_checkpoint_dirty.pop(key, None)` (flush is an authoritative write and needs no follow-up; discard is a deletion).
- inflight is not cleaned manually; the running task cleans it up in finally.

Semantics:
- During in-flight, all routine triggers (`request.completed`, `memory.store:*`, `operation.checkpoint`, UI patch, etc.) are coalesced into "1 follow-up"; the task-end flush still persists synchronously and no longer triggers extraneous follow-ups.
- The worst-case crash loss window is unchanged (≤ stale cap / task-end flush).

### B. UI Bridge Sidecar (`workspace_store.py` + `planning_routes.py` + `server.py`)

New store methods:
- `save_ui_bridge(user_id, session_id, bridge, *, reason="ui.bridge") -> None`
  - `get_session` verifies ownership; path `workspace_root(user_id, session_id)/ui_bridge.json`; content `{**bridge, "reason": ..., "saved_at": time.time()}`; atomic write via the existing `_atomic_json`; on failure raises `WorkspaceError` (the caller logs a warning as before).
  - Does not bump revision, iterate arrays, or touch snapshot.json.
- `load_ui_bridge(user_id, session_id) -> Dict[str, Any]`
  - File missing / parse failed / not a Mapping → `{}`; otherwise returns the dict (including `saved_at`).

`_flush_ui_bridge_checkpoint` (`planning_routes.py:1030`):
- `save_snapshot_patch({"ui": {"bridge": bridge}})` → `store.save_ui_bridge(user_id, selected, bridge, reason=reason)`; exception handling stays the same.

Reader (the only read point is `web/server.py:583`):
- On startup/restore: `snapshot_bridge = snapshot.ui.bridge or {}`; `sidecar = store.load_ui_bridge(...)`;
- Pick the one with the newer `saved_at` (missing treated as oldest); use the sidecar when `sidecar.saved_at > snapshot_bridge.updated_at`, otherwise use the snapshot. Old workspaces without a sidecar behave unchanged.

Cleanup: the sidecar lives in the case directory and is handled together with case deletion/recycle bin; no extra logic is needed (verify the path with the existing `_safe_workspace_child` during implementation).

### C. Planning Attribution (`plans/performance.py`)

Within `collect_planning_latency`:
- Record at start: `os.getloadavg()`, `time.process_time()`, `threading.active_count()`;
- Record the same values at end, write into `metadata['latency_profile']['contention']`:
  ```python
  {
    "loadavg_1m_start": float, "loadavg_1m_end": float,
    "process_cpu_seconds": float,    # process_time delta
    "wall_seconds": float,
    "avg_parallelism": float,        # cpu/wall, >1 means multiple cores busy
    "threads_start": int, "threads_end": int,
  }
  ```
- The `[planning_latency]` log appends `wall=... cpu=... parallelism=... load=...`, keeping the existing `total_seconds/nested_timings` unchanged.
- Pure observation; does not change any computation/return.

## 4. Compatibility and Rollback

1. A: Behavior matches the status quo when there is no in-flight snapshot; generation is still advanced by flush/discard; existing tests (including superseded/discard/orphan cases) should keep passing.
2. B: Old workspaces (no sidecar) fall back to the snapshot on read; the write side changes only one call site; `ui.bridge` in the snapshot may stay at the last value before the switch, but reads use the newer one, so semantics are unchanged.
3. C: Only adds fields to logs/metadata; existing `test_planning_latency_profile.py` assertions must keep passing.
4. Rollback: A/B can be rolled back independently (B reverts to one line of `save_snapshot_patch`); C has no side effects.

## 5. Test Plan

A (`tests/test_workspace_checkpoint_deferral.py` or a new file):
- During in-flight, `schedule_agent_checkpoint` does not bump generation, does not replace the timer, and sets dirty;
- After the snapshot completes, dirty triggers one coalesced follow-up (monkeypatch `_snapshot_agent_locked` counting);
- `flush_agent_checkpoint` clears dirty and produces no follow-up;
- Existing superseded/cancelled cases still pass.

B (`tests/test_workspace_store.py` or a new file + route tests):
- `save_ui_bridge`/`load_ui_bridge` round-trip, missing falls back to `{}`, invalid JSON falls back to `{}`, atomic write leaves no temporary residue;
- Restore priority: sidecar newer than snapshot → use sidecar; sidecar older/none → use snapshot (can use `create_app` + restore path or unit-test the selection function directly, if extracted into a small function);
- `_flush_ui_bridge_checkpoint` goes through the sidecar (integration: monkeypatch store to assert the call).

C (`tests/test_planning_latency_profile.py`):
- The `contention` field exists and is numeric; does not affect `nested_timings`/return value/exception semantics.

Regression: `tests/test_workspace_store.py`, `test_workspace_frontend.py`, `test_workspace_checkpoint_deferral.py`, `test_chat_tasks.py`, `test_workspace_auth.py`, `test_public_deployment.py`.

## 6. Acceptance

1. In-server planning: the guide-template/long-task stage `checkpoint started` no longer shows a "continuous start-cancel" storm (`cancelled stale` drops significantly), and checkpoints can complete;
2. UI requests (`/api/workspace/state`) no longer show the 5–9s level (can be compared against Slow request logs);
3. The new `[planning_latency]` attribution fields are readable: an idle window has high `avg_parallelism` and low load; a busy window has high load, explaining the wall-clock time;
4. Result hashes/metrics unchanged; after restart, UI bridge state restores correctly (validate opening an old case, a new case, and deleting a case each once).

## 7. Risks

| Risk | Mitigation |
|---|---|
| dirty follow-up lost (process crash) | Task-end flush + stale cap still cover it; the follow-up only reduces the loss window |
| Sidecar and snapshot bridge data inconsistent | Read takes the newer by `saved_at/updated_at`; old data falls back compatibly |
| Sidecar mistakenly cleaned up | Place it in the case directory, use `_safe_workspace_child`; manage it with the case lifecycle |
| `_snapshot_agent_locked` structural change introduces a regression | Minimize changes with an outer try/finally + run the full existing checkpoint test suite as a regression |
