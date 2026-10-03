# Deferring Workspace Checkpoints During Planning (Checkpoint Deferral) Design

- Date: 2026-09-16
- Status: Pending review
- Involves: `web/workspace_store.py`, `web/server.py`, new `tests/test_workspace_checkpoint_deferral.py`
- Hard constraints: **do not break any existing working functionality**; default behavior matches the status quo; one-switch rollback.

## 1. Background and Evidence

Planning (`seed_planning`) measured 160.1s in-server (16:37:41.811 → 16:40:21.893), of which:

- `rule_based_optimizer` 143.9s + `coverage_repair` 13.6s (real computation);
- Within the same window, **20 full workspace checkpoints** were completed (17 with `reason=request.completed`, 3 from planning's own `memory.store:*`), with logged completion time totaling **78.2s**, including `artifacts encoded` 17.1s and `snapshot written` 16.3s;
- Each checkpoint traverses 442 arrays and rewrites a ~30MB snapshot, taking 3–6s each.

In an independent replay, the same code took only **70.8s** for `seed_planning` (same day, same machine, same load), proving the gap comes from in-process persistence contention rather than algorithm degradation.

Current trigger sources:

- `after_request` fallback hook: any non-read-only POST/PUT/PATCH/DELETE schedules a full checkpoint (`web/server.py:991-1023`, reason=`request.completed`);
- `memory` persistence callbacks: `memory.store/<tool/message/ui_state>`, etc. (`web/server.py:587` → `agent_runtime/core.py:276-307`).

Existing safety nets (this design relies on them and does not change them):

- UI state has a bridge writer with 250ms debounce (`save_snapshot_patch`);
- Chat history uses patch persistence via `/api/sessions/*/messages`;
- Task completion **synchronously** flushes a full checkpoint via `flush_agent_checkpoint("chat.task.finalized.background")` (`web/routes/planning_routes.py:2625-2650`);
- A ready-made signal for "the case has recomputation running": `_case_has_running_chat_task()` (`web/server.py:181`), already used for cache maintenance;
- Precedent for skipping while busy: the hook defers during hydration (`web/server.py:1010`);
- The scheduler has built-in 0.75s debounce, generation eviction, and non-blocking retry (`web/workspace_store.py:3590-3678`).

## 2. Goals and Non-Goals

Goals:

1. Stop doing consecutive full checkpoints while recomputation is running, reclaiming wall-clock time consumed by persistence (expected 20 → 2~3 within the 160s window, saving about 50–60s);
2. All trigger sources (`request.completed`, `memory.store:*`, `operation.checkpoint`) benefit uniformly;
3. Guarantee the final result and existing persistence semantics are unchanged (flush on completion; idle behavior unchanged).

Non-goals (revisit in phase two):

- Incremental snapshots / writing only changed keys;
- Idle-period "don't persist if nothing changed" dirty check (could eliminate the idle ~6/min spin, but requires aggregating conversation/tool_results/ui_state revision and is higher risk);
- Changing the planning algorithm, parameters, snapshot schema, or revision/lease semantics.

## 3. Design

### 3.1 Components

`WorkspaceStore` additions:

1. `heavy_task_probe: Optional[Callable[[str, str], bool]]`
   - Injected by server; signature `(user_id, session_id) -> bool`; `None` when not injected.
2. `checkpoint_max_staleness_seconds: float`
   - Default 60, read from env var `BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS`; invalid values fall back to the default and log a `warning`; `<=0` means deferral is disabled (fully restoring the status quo).
3. `_checkpoint_completed_at: Dict[Tuple[str, str], float]`
   - The `time.monotonic()` of each (user, session)'s most recent **successfully completed full checkpoint**; updated after `_snapshot_agent_locked` commits successfully (non-discard); `flush_agent_checkpoint` goes through the same path and also updates it; reads and writes are all under `self._lock`.
4. `_should_defer_checkpoint(user_id, session_id) -> bool` (independently testable)
   - `probe is None` → `False` (keep the status quo);
   - `staleness <= 0` → `False`;
   - no `_checkpoint_completed_at` record → `False` (ensures a first persist when "never persisted", before deferral begins);
   - `probe(user, session)` is true and `now - completed_at < staleness` → `True`; otherwise `False`;
   - probe raises → log at `debug` and return `False` (fail-open, does not affect persistence).

### 3.2 Scheduler Integration

Insert in `_checkpoint_timer` (`web/workspace_store.py:3631`) after the generation check and before attempting to acquire `work_lock`:

```text
if self._should_defer_checkpoint(user_id, session_id):
    logger.debug("workspace checkpoint deferred session=%s reason=%s", ...)
    # Reschedule a short timer with the "latest generation" to avoid reviving stale work
    with self._lock:
        latest_generation = self._checkpoint_generations.get(key, 0)
        self._checkpoint_timers[key] = threading.Timer(DEFER_RETRY_SECONDS,
            self._checkpoint_timer,
            args=(user_id, session_id, agent, reason, operation, latest_generation))
        ...start...
    return
```

- `DEFER_RETRY_SECONDS = 3.0` constant, no new env var;
- Strictly follow the "latest generation" rule (consistent with the existing retry branch); stale generations are still discarded;
- After exceeding the staleness cap (even if the task is still running), persist once as usual and refresh `_checkpoint_completed_at`, so the worst-case loss window is ≤ staleness.

### 3.3 Server Wiring

After the store is created in `web/server.py` (`:320`), look up the extension lazily to avoid registration-order issues:

```python
workspace_store.set_heavy_task_probe(
    lambda user_id, session_id: _case_has_running_chat_task(
        app.extensions.get("brachybot_chat_tasks"), user_id, session_id
    )
)
```

(`brachybot_chat_tasks` is registered in `register_planning_routes`, so it must be looked up at call time.)

### 3.4 Logging and Metrics

- Deferral: `logger.debug` each time; if the current persist was force-triggered by the "staleness cap" (probe still busy), log one `logger.info` with `staleness_s` and `reason`, for end-to-end acceptance;
- The existing `checkpoint started/completed` log format is unchanged; acceptance compares counts.

## 4. Compatibility and "Do Not Break Functionality" Guarantees

1. **Probe not injected (tests, CLI, standalone tools)**: `_should_defer_checkpoint` is always `False`, so behavior matches the current per-path flow;
2. **`flush_agent_checkpoint` / `save_snapshot_patch` / `save_agent_results_patch` / `discard_agent_checkpoint` do not pass through `_checkpoint_timer`** and are entirely unaffected; the task-completion `chat.task.finalized.background` synchronous persist is unchanged;
3. **Idle, case switching, lease, deletion, revision/409, and hydration semantics** are all unchanged; the cache eviction/expiry paths already have "do not evict while a task is running" protection, and deferral only affects their scheduling timing, not the final persist;
4. **Zero impact on planning results**: does not touch `plans/*` or `tool_factory/seed_plan/*`; result hashes/metrics should match the status quo;
5. **Rollback switch**: `BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS=0` restores the status quo with no code rollback;
6. **Item-by-item review of control-plane scheduling paths**: `agent.cache_evicted`/`cache_expired` only occur for cases with "no running task" (already protected by `_agent_has_running_task`), so a false probe does not defer; if `agent.cache_dropped` (case switch) and `structures.traversability_changed.full_checkpoint` coincide with recomputation, the worst case defers ≤60s, the task still holds the agent and flushes on completion; `workspace.hydration.reconciled` occurs in the ready phase, normally with no task running;
7. Decoupled from existing uncommitted WIP: this change is committed separately and carries no other WIP.

## 5. Test Plan

New `tests/test_workspace_checkpoint_deferral.py`:

1. probe not injected → the timer executes immediately (matches the status quo);
2. probe busy + an existing persist record and not over the cap → does not execute, reschedules the timer;
3. probe busy but staleness exceeds the cap → executes once;
4. probe busy + no persist record → executes once first;
5. probe raises → executes (fail-open);
6. `flush_agent_checkpoint` still completes synchronously while busy (unaffected by deferral);
7. `MAX_STALENESS=0` → no deferral;
8. after success, `_checkpoint_completed_at` is refreshed (the next schedule executes immediately or defers based on the new time).

Implementation notes: to avoid thread-timing jitter, tests call `_checkpoint_timer` directly (synchronously) and assert the snapshot revision/`_checkpoint_completed_at`, monkeypatching `_snapshot_agent_locked` to count when necessary.

Regression set (must all be green):

- `tests/test_workspace_store.py` (checkpoint core)
- `tests/test_workspace_frontend.py` (`flush_agent_checkpoint` contract, etc.)
- `tests/test_chat_tasks.py`, `tests/test_chat_case_resources_wait.py`
- `tests/test_workspace_lease_ux.py`, `tests/test_workspace_server_recovery_indicator.py`
- Server wiring unit test: after injection, `_should_defer_checkpoint` can hit `_case_has_running_chat_task`

## 6. End-to-End Acceptance (In-Server)

Rerun planning for the same case and same parameters, collecting:

1. Step 3 wall clock (the log time difference from `Step 3/5` → `Step 4/5`);
2. The `checkpoint started` count within the window and the number of `request.completed` events;
3. Result hashes (`trajectory_*`, `dose_*`, `seed_plan_serialized`, `verified_needle_geometry`) and `v100/v150/v200/d90` matching before the change;
4. Correct UI behavior: planning progress, chat, case switching, and restart recovery all show correct data (nothing missing).

Pass criteria: checkpoint count drops significantly (target ≤3 per 160s), Step 3 wall clock decreases; all hashes/metrics unchanged; regression tests all green.

## 7. Risks and Rollback

| Risk | Mitigation |
|---|---|
| Losing up to 60s of intermediate state on crash | The cap can be lowered; the final flush guarantees results are not lost; `MAX_STALENESS=0` disables it |
| probe misjudgment (task has ended but still reports busy) | probe is the existing authoritative signal; probe exceptions are treated as "do not defer" |
| Deleting/switching the case during deferral | Deletion goes through `discard_agent_checkpoint`; switching is handled by the task holding the agent and flushing on finalize |
| Timer pileup/reproduction generation | Reuse the existing "latest generation + 0.75s debounce + single work_lock" rules |

## 8. Deliverables

1. Code changes (two files) + a new test file;
2. Acceptance report: Step 3 wall clock before/after, checkpoint counts, and result hash comparison;
3. An independent commit separate from the user's existing WIP (signed Haitao-Lee).
