# Training Monitor — Comprehensive Understanding, Audit, and Improvement Plan

Date: 2026-09-19
Repository: `<workspace>/BrachyBot` (internal tree)
Branch / HEAD: `codex/session-task-recovery` @ `fdc64cbb0`
Scope: the **live planning training monitor** ("Monitor" / "Finish Monitor", `training.mode`, `/api/training/*`)
Nature of this document: **analysis only**. No code was changed.

> Terminology
> - **Monitor / training monitor** = the live planning-supervision feature described here.
> - **Run** = one started monitor session with a unique `monitor_run_id`.
> - **Event** = one UI/planning interaction recorded through `/api/ui/event`.
> - **Deterministic engine** = the non-LLM feedback/advice/summary code in `web/server_support.py`.
> - The unrelated `benchmarks/auto_monitor.py` (benchmark supervisor) is **out of scope**.

### 0.1 Internal-tree provenance note

This analysis was performed against the internal tree. Its monitor modules are **semantically line-for-line identical** to the sibling public tree (`BrachyBot-release`) for the entire monitor subsystem; the only differences are (a) `index.html` line offsets caused by a release-only authentication-boot block, (b) a handful of `Cache-Control/Connection` streaming headers in `planning_routes.py` after line 7500, and (c) CRLF line terminators. All monitor line references below were re-verified in the internal tree. Internal-only hygiene observations are collected in §3.6 and §10.5.

---

## 0. Executive Summary

The training monitor is a **case-owned, run-scoped, deterministic supervisor** layered on top of the manual/automatic planning workstation. A browser starts a run; every meaningful UI and planning interaction is streamed to the server; the server returns short, rule-based coaching feedback and occasionally suggests a screenshot at a high-value checkpoint; the user can request detailed advice at any time; and stopping the run produces a final workflow report. It is deliberately **LLM-independent** so it keeps working when the LLM API backend is unavailable.

The design is sound and unusually well thought through for a feature of its size (idempotent lifecycle, stale-run normalization, run-id fencing, non-blocking event path, deterministic clinical checks, rate-limited evidence capture). The main problems are **maintainability and correctness debt that has accumulated across five near-identical generations of the same helper family**, plus a handful of real behavioral bugs:

1. **The deterministic engine source is duplicated ~5 times** in `web/server_support.py`; only the last copy executes. The dead copies contain different (sometimes better) translation tables. This is the single largest risk to future changes.
2. **Events from mismatched/abandoned runs are still appended and still refresh the run's liveness**, contradicting the code's own comment, defeating the stale-run timeout, and inflating counts.
3. **`training.events` is unbounded**, unlike the global event list (capped at 500), so long runs grow memory and the persisted `ui_bridge.json` without bound.
4. **Close paths are inconsistent**: an orderly-stop run stores `last_summary`; a stale/shutdown/restore close does not, so `/training/stop` can return `summary_message: null`.
5. **Chinese localization is incomplete** for several advice strings, so zh reports leak English.
6. **The deterministic feedback/screenshot path requires `commit_status:"committed"` supplied by the browser**, silently disabling manual-event feedback for non-browser callers.
7. **Advice is computed over the global event window while counts use the run window**, so they can disagree.
8. **Test coverage is broad but shallow**: dominated by source-substring assertions rather than behavioral tests; `/api/training/advice`, start/stop conflict semantics, shutdown reconciliation, throttles, and multi-session isolation are effectively untested.

None are architectural dead ends. §8 gives a phased plan: (A) correctness hardening, (B) consolidating the engine into one tested module, (C) UX upgrades that turn the monitor from a passive "edge glow + chat snippets" into an actionable coaching HUD, and (D) product capabilities (per-site rubrics, competency scoring, audit timeline export, plan comparison).

---

## 1. What the Monitor Is Trying To Do, and Why It Is Built This Way

### 1.1 Product intent

- `README.md:642-651` (internal) — the monitor is one of the pillars of "UI-aware manual planning": users can ask BrachyBot to monitor a manual or automatic planning process, receive **live feedback after key interactions**, capture **rate-limited review screenshots at key checkpoints**, **request detailed advice at any time**, and **stop to receive a final workflow report**.
- `docs/UI_CONTROL_MANUAL_TRAINING_REPORT_2026-06-30.md:62-73` — the monitor supports both **live and retrospective** use; events are buffered; the backend returns lightweight deterministic feedback for segmentation/planning/needle/seed/dose events; high-value checkpoints yield a `suggested_screenshot`; stop returns a final report summarizing workflow activity and current plan quality.
- `docs/PRODUCT_READINESS_UI_MANUAL_TRAINING_AUDIT_2026-07-02.md:24-25,42-44` — requirements: start/stop/advice endpoints exist; the frontend records events and throttles screenshots; the final report is deterministic; **retrospective advice works without an active session**; stop returns counts, strengths, issues, recommendations rendered in chat.

### 1.2 Why deterministic (not LLM-driven)

`docs/UI_CONTROL_MANUAL_TRAINING_REPORT_2026-06-30.md:73`: the advice engine uses current metrics and event history deterministically and **does not depend on an LLM, so it remains available when LLM APIs fail**. Consequences:

- Feedback must be cheap and synchronous (it runs on the `/api/ui/event` request thread).
- It cannot reason freely; it encodes a fixed set of **clinical checks** (seed spacing, needle collision, DVH metrics, artifact staleness) and a fixed advice template.
- Screenshots are suggested by rules, not requested by a model.

### 1.3 Why case-owned and run-scoped

Monitoring state lives under a per-session bucket (`web/server_support.py:356-385`, keyed by `_ui_session_id`). A run has a `monitor_run_id`; every event carries it, and the server only evaluates feedback/screenshots when it matches the active run (`web/routes/planning_routes.py:4896-4901`). This prevents a delayed callback from an old run leaking into a new run or a different case. The frontend mirrors this ownership (`brachybot-ui-api.js:1770-1776`, `3d-manual.js:2339-2350`).

### 1.4 Why observation is passive/event-driven

The monitor never drives the plan; it observes. `reportUIEvent` is called from existing UI code; the browser posts `type/label/detail/language/monitor_run_id/ui_state` (`brachybot-ui-api.js:2061-2085`). The server appends and returns feedback. This avoids an always-on second inference loop and keeps the browser interactive (`planning_routes.py:4902-4909` refuses to cold-hydrate an agent on the telemetry path).

### 1.5 Why idempotent and stale-safe

Monitor close happens on many boundaries (user stop, `pagehide`, session switch, server shutdown, restore), so the lifecycle was explicitly hardened (commits `1cd78cf79`, `a8d97fce4`; `docs/CODE_REVIEW.md`). The rules:

- Start with the same run id while active → idempotent success replay.
- Start with a different run id while active → 409.
- A run idle longer than `BRACHYBOT_MONITOR_STALE_SECONDS` (default 1800 s) is auto-closed (`server_support.py:359-362,439-448,410-436`).
- Stop on an inactive or mismatched run → idempotent success, never an error.
- A persisted `active:true` is **not** a live browser lease; it is normalized to inactive on hydration/restore (`server_support.py:415-422`, `server.py:626-640`, `planning_routes.py:4752-4773`).

### 1.6 Why the UI-first split

The monitor is part of the "UI-aware workstation" contract (`agent_runtime/turn_policy.py:2085-2099`, `tool_factory/ui_controller/__init__.py:413-417`). Even "please stop monitor" is classified as `ui_control`, not a knowledge query, so it reaches the UI controller and actually stops the run (fix `b17ddfe5b`; test `tests/test_runtime_contracts.py:662-674`).

---

## 2. Architecture and Data Flow

### 2.1 Component map

| Layer | Primary files | Responsibility |
|---|---|---|
| HTTP routes | `web/routes/planning_routes.py` (`api_ui_event` 4884, `api_training_start` 4980, `api_training_stop` 5059, `api_training_advice` 5174, `api_readiness` 5212, `api_screenshot` 7919) | Validate, own the run state machine, return feedback/advice/summary |
| Bridge/state + engine | `web/server_support.py` (`_UI_BRIDGE` 356, `_ui_bucket` 370, `_append_ui_event` 494, lifecycle 410-484, deterministic engine 4375-4675) | In-memory bucket, event append, staleness, deterministic checks, localization, summary |
| Persistence | `web/workspace_store.py:3864-3914` (sidecar `ui_bridge.json`), `web/routes/planning_routes.py:1021-1050,2757-2794` (debounced checkpoint), `web/server.py:626-640` (hydration), `:2227-2238` (shutdown) | Durable history across reload/restart |
| Session snapshot | `web/routes/session_routes.py:65-73,391-412`, `server_support.select_case_bridge:388-407` | Legacy snapshot fallback merge |
| Agent routing | `agent_runtime/turn_policy.py:2085-2126`, `agent_runtime/ui_operations.py:72-77`, `tool_factory/ui_controller/__init__.py:413-417` | "start/stop/status/advice" intent & UI command |
| Tools | `tool_factory/ui_screenshot`, `ui_inspector`, `ui_controller`, `ui_content` | Screenshot target catalogue/plan; monitor is metadata mode, not a branch |
| Frontend state | `web/app/static/js/brachybot-ui-api.js:1719-2224`, `brachybot-3d-manual.js:2235-2524` | Client state machine, event posting, feedback batching, screenshot interception, stop report |
| Frontend UI/CSS | `web/app/index.html:80,448,912-913`, `brachybot-chat-status.css:1752-1877` | Monitor button, status chip, edge overlay |
| Tests | `tests/test_training_monitor_audit.py`, `test_screenshot_trace_integration.py`, `test_workspace_frontend.py`, `test_runtime_contracts.py`, `test_manual_seed_transactions.py`, `test_ui_bridge_sidecar.py` | Contract/regression coverage (largely substring-based) |

### 2.2 Lifecycle state machine

```
                 POST /api/training/start
inactive ─────────────────────────────────────► starting
   ▲                                                │ success
   │                                                ▼
   │ stop (user)  ┌──────────────┐               active ◄────────┐
   ├──────────────┤  stopping    │◄────────────────┘              │
   │              └──────────────┘                                │
   │                   │ stop success                            │ events
   │                   ▼                                         │
   └──────────────── inactive ◄── stale timeout (>=1800 s) ──────┘
                          ▲
                          │ hydration / restore / shutdown
                    active (persisted) normalized to inactive
```

Server-side facts (`planning_routes.py`):

- **Start** (`4980-5057`): `run_id = data.monitor_run_id or uuid4().hex` (`4989`). Stale previous → close with `reason="monitor_timeout"` (`5002-5007`). Same run id while active → 200 replay (`5010-5018`). Different run id while active → **409** (`5019-5023`). New record stores `active/run_id/goal/language/started_at/last_activity_at/stopped_at/events/feedback` (`5025-5035`). `training.start` is appended with `include_in_training=False` (`5036-5045`).
- **Event** (`4884-4978`): computes `monitor_run_matches` (`4896-4901`), uses only a **cached** agent (`4907`), reuses the authoritative committed event when `already_recorded` (`4924-4937`) else appends (`4939-4944`), returns feedback/screenshot only when matched (`4950-4957`).
- **Stop** (`5059-5172`): inactive → idempotent `already_stopped` (`5085-5095`); run mismatch → idempotent `run_mismatch` (`5096-5106`); otherwise sets inactive, copies `training.events` (`5116-5121`), counts (`5127-5130`), and — unless `auto_close` — deterministic advice via `_build_plan_advice(..., fast=True)` (`5135`), summary (`5141`) persisted as `training.last_summary` (`5153-5154`).
- **Advice** (`5174-5210`): requires an agent (else **500** `Agent not available`, `5181-5183`); optional grounded local-read answerer for a free-text question (`5195-5209`).
- **Stale close** (`server_support.py:410-436`): `active=False`, `phase="inactive"`, `run_id=None`, `last_run_id`, `stopped_at`, `closed_reason`, `auto_closed=True`, refresh `last_activity_at`.

### 2.3 HTTP API surface

| Method(s) | Path | Handler | Notes |
|---|---|---|---|
| GET/POST | `/api/ui/state` | `api_ui_state` (`4701`) | Restores durable bridge, closes stale training on restore |
| GET | `/api/ui/capabilities` | `api_ui_capabilities` (`4818`) | Advertises `training_monitor` capabilities & screenshot targets (`4848-4879`) |
| POST | `/api/ui/event` | `api_ui_event` (`4884`) | Core telemetry + live feedback/screenshot |
| POST | `/api/training/start` | `api_training_start` (`4980`) | 200 replay / 409 conflict |
| POST | `/api/training/stop` | `api_training_stop` (`5059`) | Idempotent; final summary |
| GET/POST | `/api/training/advice` | `api_training_advice` (`5174`) | 500 if no agent |
| GET/POST | `/api/readiness` | `api_readiness` (`5212`) | Product-readiness checklist |
| POST | `/api/screenshot` | `api_screenshot` (`7919`) | monitor capture sink; `mode ∈ {chat,monitor,report}` (`7929-7931`) |
| GET | `/api/workspace/snapshot` | `session_routes.workspace_snapshot` (`391`) | Restores monitor state |

All routes are wrapped by `@require_api_key` and `@rate_limit` (`server_support.py:3665-3703`), returning 401/429 as applicable.

### 2.4 Storage layers

| Layer | Location | Lifetime | Notes |
|---|---|---|---|
| In-memory bucket | `_UI_BRIDGE[session_id]` (`server_support.py:356-385`) | Process | `state`, `events` (cap 500), `training` |
| Durable sidecar | `<workspace>/ui_bridge.json` (`workspace_store.py:3864-3914`) | Disk | Debounced 250 ms (`planning_routes.py:1021-1050`) |
| Snapshot fallback | `snapshot["ui"]["bridge"]` (`session_routes.py:65-73`) | Disk | Legacy read-only merge by `select_case_bridge` |

The global `events` list is trimmed to `BRACHYBOT_UI_BRIDGE_MAX_EVENTS` (default 500, `server_support.py:509-510`), but `training["events"]` is **not** (`513`). Both lists reference the same dict objects, so a long run keeps the training list growing and re-serializes it on every checkpoint.

### 2.5 Event taxonomy

- Lifecycle: `training.start` (only).
- Clinical/committed (appended by mutation endpoints; `commit_status:"committed"` injected by the browser bridge): `manual.needle.add|drag|delete|position_only|restore`, `manual.seed.add|drag|delete`, `manual.dose`.
- Workflow: `planning.step`, `segmentation.step` (`status: running|done|error`), `planning.error`, `segmentation.error`.
- UI telemetry: `ui.click|change|slider|panel|control`, `parameter.set`, `viewer.*`, `dicom_rt.import`, `system.readiness`, `training.advice`, `planning.run.algorithm.restore`.

Append semantics (`server_support.py:494-515`): defaults `type="ui.event"`, `label=""`, `detail={}`, adds `ts`; appends to global `events`; if `training.active and include_in_training`, also appends to `training.events` and refreshes `last_activity_at`.

### 2.6 Deterministic engine (the real value)

`_latest_plan_snapshot` (`server_support.py:963-1157`) plus `_build_plan_advice` (`1192-1389`) produce:

- **Seed finite-cylinder interference** (`_seed_interference_report:734-878`): default seed length 4.5 mm, radius 0.4 mm, clearance 0.5 mm; flags overlap/too-close with surface clearance, using the owning needle direction (falls back to seed direction then world Z).
- **Needle segment–segment proximity/intersection** (`1047-1063`): threshold = needle diameter + clearance.
- **Needle ↔ non-traversable Data Tree/obstacle intersection** (`1065-1097`): skipped in `fast=True`.
- **Dose/DVH metrics** (V100/V150/V200, D90, plan score, OAR Dmax/D2cc) (`1222-1276`).
- **Artifact staleness & Surgical Guide state** (`1345-1373`).
- **`/api/readiness`** checks CT, CTV, OAR, planning, dose, report, clinical_kb, screenshots (`1639-1725`).

Per-event coaching/checkpoints are produced by the **effective** implementations bound at `server_support.py:4670-4675`:

- `_training_feedback_for_event_clean` (`4524-4612`): seed spacing/cold coverage, needle obstacle/collision, planning/segmentation stage status, dose V100/D90.
- `_training_screenshot_for_event_clean` (`4615-4667`): `segmentation.step`/trajectory steps → `viewer-3d`; `dose_calc|dose_eval|full` → `dose-overview`; `manual.dose` → `dose-overview` if under/over target else `dvh`; `manual.seed.*` → `viewer-3d` with `focus_seed_ids`.
- `_format_training_summary_clean` (`4499-4521`) and `_localize_monitor_text_clean` (`4390-4471`).

### 2.7 Screenshot pipeline

- Suggestion requires non-empty feedback (`4616-4617`) and a completed stage (`4621`).
- Frontend (`brachybot-ui-api.js:2115-2224`): 45 s throttle for ordinary chatter, always fires for stage/dose checkpoints (`2127`); `lastScreenshotAt` set **before** capture (`2129`); 500 ms delay (`2224`); callbacks re-check run ownership (`2135-2137`).
- Capture (`_interceptScreenshot`) waits for visual readiness, snapshots viewer/camera/mesh state, applies focus, captures, uploads to `/api/screenshot`, restores in `finally` (`ui-api.js:11637-11951`; camera/mesh restore `3d-manual.js:5020-5205`).
- Targets validated against `tool_factory/ui_screenshot/__init__.py:20-38`; `dose-overview` expands to three planes + DVH.
- `tool_factory/ui_screenshot` is a pure planner; monitor mode is **metadata**, not a branch (`ui_screenshot/__init__.py:1-8,337-447`).

### 2.8 Agent intent routing

- `turn_policy.py:2085-2126`: `ui` vocabulary includes `monitor`, `training mode`, `start/stop monitoring`, `监测/停止监测/开始监测/结束监测`; when no higher-priority intent matches, returns `LocalTurnPolicy("ui_control", ..., UI_TOOLS)` (`2126`).
- `ui_operations.py:72-77`: `_UI_CONTEXT_RE` includes `monitor/监测`.
- `tool_factory/ui_controller/__init__.py:413-417`: registry target `training.mode` with `start|stop|status|advice` (described at `:1568-1572`).
- `brachybot-ui-api.js:7944-7961`: `start`→`startTrainingMode`, `stop`→`stopTrainingMode`, `advice`→`requestPlanningAdvice`, else status chat.

### 2.9 Frontend state machine and UX

- State: `trainingMonitorState` (`ui-api.js:1719-1734`).
- Phases: `inactive | starting | active | stopping | error` (`setTrainingMonitorPhase:1941-1949`).
- Presentation (`setMonitorPresentation:1866-1939`): body classes `monitor-active|starting|stopping`, `body.dataset.monitorPhase`, non-interactive `#monitorEdgeOverlay` (280 ms fade-out), status chip `#monitorStatus`, start/stop button `disabled`/`aria-pressed`, chat-header icon `aria-busy`.
- Feedback UX: `_queueMonitorFeedback:1811-1847` — immediate for `manual.dose` and completed/failed stages; aggregate seed/needle with 2500 ms flush; dedupe by message.
- Stop report: `stopTrainingMode:2404-2524` — flushes pending feedback **before** `stopping`, calls `/training/stop` with an 8 s AbortController, tolerates already-closed 404/409, renders `data.summary` (or `_formatAdviceReport(localized_advice)`) as one `monitor_summary` message with accumulated screenshot attachments.
- Cleanup: `releaseTrainingMonitorForSession:2235-2270` + `pagehide` keepalive (`2274-2283`); `restoreTrainingMonitorSnapshot:1951-1977` never resurrects an active presentation, it auto-closes a stale run.

---

## 3. Proven Issues, Impact, and Fixes

Severity: **S1** = correctness/clinical-safety-adjacent, **S2** = behavioral bug, **S3** = maintainability/consistency, **S4** = polish.

### S1-1. Deterministic engine exists in ~5 near-identical generations; only the last executes
- **Evidence:** `web/server_support.py` defines the family at `~1454-1889` (original), `3711-3928` (`_clean` #1), `3931-4156` (`_utf8`), `4163-4368` (`_final`), and `4375-4675` (`_clean` #2). Public names are rebound at `4151-4156`, `4363-4368`, and finally `4670-4675`; the last wins for `_monitor_step_label`, `_localize_monitor_text`, `_monitor_activity_label`, `_format_training_summary`, `_training_feedback_for_event`, `_training_screenshot_for_event`. Three comments (`3707-3710`, `4159-4162`, `4371-4374`) each claim to be the real compatibility boundary.
- **Impact:** Changes to a non-winning copy silently do nothing. The copies diverge semantically (the original has a V200 advice translation the live copy lacks; older feedback variants lack the `commit_status` gate) — the root cause of several localization bugs.
- **Fix:** Extract one module (e.g. `web/monitor_engine.py`) with exactly one implementation; delete the dead copies; keep thin import aliases if tests need old names; re-point `tests/test_training_monitor_audit.py`; add a guard test asserting each public helper's `__module__`.

### S1-2. Mismatched/abandoned-run events are still appended and refresh liveness
- **Evidence:** `api_ui_event` computes `monitor_run_matches` and comments a delayed callback must not be "evaluated or appended" (`planning_routes.py:4893-4901`), but the append at `4939-4944` is unconditional; `_append_ui_event` appends to `training.events` and refreshes `last_activity_at` whenever `training.active` (`server_support.py:512-514`). Mutation endpoints likewise append into any active run without a run-id check (e.g. `5395-5419`, `5701-5718`, `5879-5893`, `6117-6135`).
- **Impact:** (a) A delayed old-run event inflates the new run's counts; (b) unrelated telemetry keeps an abandoned run "fresh", so `_training_is_stale` (evaluated only at start, `5002`) never fires and the next legitimate start gets a false **409**.
- **Fix:** Gate the training append on run match (pass `run_id` into `_append_ui_event` / use a run-scoped append). Tag backend mutation events with the active run id; never append a run-tagged event into a different run. Recompute staleness opportunistically (e.g. in `/api/ui/state` and `/training/advice`).

### S1-3. `training.events` is unbounded
- **Evidence:** `server_support.py:509-513` — global list capped at 500; training list appended with no cap.
- **Impact:** Long runs accumulate every `ui.click`/`ui.slider`; the list is copied into `/training/stop` responses and re-serialized every 250 ms, growing memory and `ui_bridge.json`.
- **Fix:** Cap `training.events` (own constant, e.g. 1000) and drop oldest; or keep only high-value/committed events in the training list and leave raw chatter in the bounded global list.

### S1-4. Inconsistent close paths lose the summary and the advice
- **Evidence:** `_close_stale_training_snapshot` (`server_support.py:410-436`) never sets `last_summary`; `/training/stop` returns `training.get("last_summary")` for an inactive run (`planning_routes.py:5092`). Auto-close (`5135`) sets `advice={}`.
- **Impact:** A run closed by timeout/shutdown/hydration/restore yields `summary_message: null`; closure behavior is not uniform.
- **Fix:** Centralize close into one `close_training_run(reason, build_summary)` used by every path; always persist a summary envelope (and a cheap fast advice snapshot).

### S1-5. Chinese localization incomplete (English leaks)
- **Evidence:** Live `_localize_monitor_text_clean` (`server_support.py:4390-4471`) has no mapping for strings emitted by `_build_plan_advice`: Surgical Guide "persisted/being restored" (`1359-1361`), "status temporarily unavailable" (`1363-1365`), "generation failed" (`1369-1371`), "Load CT, segment CTV/OAR…" (`1379`), the leading seed-interference aggregate "N seed pair(s) violate…" (`1291-1298`), and the V200 hot-spot advice (present in the original block `~1478`, absent in the live copy).
- **Impact:** zh summaries/issues mix English and Chinese.
- **Fix:** After consolidating the engine (S1-1), use one localization table and add a completeness test asserting every produced advice string has a zh mapping or is allow-listed as language-neutral.

### S1-6. Manual feedback is silently disabled for non-browser callers
- **Evidence:** Live `_training_feedback_for_event_clean` returns `None` for any `manual.*` event whose `detail.commit_status != "committed"` (`server_support.py:4527-4531`). Only the browser bridge injects it (`brachybot-3d-manual.js:440-461`, `:452`); backend mutation endpoints append without it.
- **Impact:** Direct `/api/ui/event` callers (or stale JS) receive no manual feedback/screenshots — silently. The monitor's safety depends on a client-supplied trust field.
- **Fix:** Make commit status server-owned: set it at the authoritative mutation endpoint; accept the browser's `committed_event` only for events the server already recorded.

### S2-1. Advice uses the global event window; counts use the run window
- **Evidence:** `_build_plan_advice` reads `_ui_bucket(session_id).get("events")[-80:]` (`server_support.py:1223`) and can emit "Recent manual edits were detected…" (`1283-1285`); `/training/stop` counts only `training.events` (`planning_routes.py:5116-5121`).
- **Impact:** Advice can reference pre-monitor events while the report counts only monitored ones.
- **Fix:** Pass the run-scoped event list (or a `scope` parameter) into `_build_plan_advice`.

### S2-2. Whitespace-only `monitor_run_id` disables the run
- **Evidence:** `run_id = str(data.get("monitor_run_id") or uuid4().hex).strip()` (`4989`). Whitespace is truthy, survives `or`, then `.strip()` yields `""`; `monitor_run_matches` requires a truthy `active_run_id` (`4900`).
- **Fix:** `run_id = str(data.get("monitor_run_id") or "").strip() or uuid4().hex`.

### S2-3. `run_mismatch` response contradicts itself and leaks the active run id
- **Evidence:** `planning_routes.py:5096-5106` returns `run_mismatch:true, no_active_run:true` while `training.active` stays true, and echoes `monitor_run_id: active_run_id` to a stale client.
- **Fix:** Return `no_active_run:false` (or omit), do not echo the active id to a mismatched caller, and include an explicit match flag.

### S2-4. `training.stop` event/label is dead; activity labels drift
- **Evidence:** Only `training.start` is emitted (`5036-5045`); `_monitor_activity_label_clean` defines `training.stop` (`4491`) but nothing emits it. `manual.needle.restore` is emitted by the client (`3d-manual.js:10321`) but absent from the activity map (`4475-4492`).
- **Fix:** Emit `training.stop` (`include_in_training=False`) on close; add missing labels.

### S2-5. `feedback_raw` / `feedback_localized` are misnomers
- **Evidence:** `/api/ui/event` sets all three to the same already-localized string (`planning_routes.py:4972-4974`).
- **Fix:** Return a genuine raw/localized pair or remove the redundant fields (update tests asserting them).

### S2-6. Shutdown close is never persisted; cache eviction drops history
- **Evidence:** `_close_live_training_snapshots` mutates only in-memory buckets (`server_support.py:463-484`); `web/server.py:2227-2238` does not flush the sidecar, so after orderly shutdown `ui_bridge.json` still says `active:true` until next hydration. `_drop_ui_bucket` (`487-491`) is called on LRU eviction/cache drop (`server.py:570`, `944`) without flushing or closing.
- **Impact:** Up to a 250 ms window of events can be lost; the persisted record can contradict reality.
- **Fix:** On shutdown and eviction, close the run and flush the sidecar (best-effort) before dropping.

### S2-7. Readiness contract is self-contradictory
- **Evidence:** `_build_system_readiness` sets `ready_for_review = all(checks[:6])` while `blockers` includes all 8 checks (`server_support.py:1705-1706`).
- **Fix:** Derive `ready` from `not blockers` or document and rename the fields.

### S2-8. `ui_inspector` reports hard-coded viewer state as "current"
- **Evidence:** `tool_factory/ui_inspector/__init__.py:754-758` initializes viewer defaults and never merges live `ui_state["viewer"]/overlays` (published by `brachybot-ui-api.js:1459-1470,1587-1606`), while other fields are merged (`787-807`).
- **Impact:** `query=state` always claims `layout="vertical"`, `window_preset="soft_tissue"`, overlays all `False`.
- **Fix:** Merge live viewer/overlay state like the other sections; add a test.

### S2-9. `training.mode` / `manual.*` have no Chinese execution descriptions
- **Evidence:** `_describe_action_i18n` (`ui_controller/__init__.py:~1457-1460`) has no `training.mode` branch; English has a friendly branch (`~1568-1572`).
- **Fix:** Add the missing i18n branches.

### S3-1. Duplicated/legacy screenshot mechanisms
- **Evidence:** `ui_controller`'s `screenshot` target dispatches to `_captureScreenshot` (`brachybot-ui-api.js:8254-8295`), which downloads a file directly and bypasses the `ui_screenshot` plan → gallery → attachment pipeline. `_interceptScreenshotLegacy` (`9358-9362`) has no callers.
- **Fix:** Route controller screenshots through the unified pipeline or document the difference; remove the uncalled legacy function.

### S3-2. Dead validation branch and dead fields
- **Evidence:** `if errors:` at `ui_controller/__init__.py:1212-1213` is unreachable (errors returned at `1179-1189`). `training["phase"]` is written (`server_support.py:429`) but never initialized server-side nor read. `_ui_session_id` defaults to `"web"`, so loopback callers without a case share one bucket (`server_support.py:365-385`, `planning_routes.py:2728`).
- **Fix:** Remove or wire the dead branch/field; document or isolate the shared loopback bucket.

### S3-3. `performance_tracker` is orphaned
- **Evidence:** Not registered in `AgenticSys.py` (UI tools registered at `:724-745`); aggregation is unguarded (`performance_tracker/__init__.py:163-164,252-253`) while `_get_trends` guards (`198-203`). Legacy string scores crash it; it reports "improving" for 10–19 sessions because `previous_avg=0`.
- **Fix:** Delete, or harden and register it as the basis for competency scoring (§8.3).

### S3-4. Monitor plan `version: 2` is meaningless
- **Evidence:** `brachybot-ui-api.js:2165` sends version 2; `_normalizeStructuredScreenshotPlan:11145` coerces to ≥5.
- **Fix:** Send the real schema version (5).

### S4-1. Screenshot throttle is set before capture and suppresses failures for 45 s
- **Evidence:** `brachybot-ui-api.js:2129` sets `lastScreenshotAt` before `_interceptScreenshot`; failures are swallowed (`2221-2223`).
- **Fix:** Set the timestamp only on success; surface a small notice on repeated failure.

### S4-2. `_waitScreenshotFrames` has no timeout; backgrounded tab can stall
- **Evidence:** `brachybot-ui-api.js:8350-8360` has no timeout; the 3D render loop skips while `document.hidden` (`3d-manual.js:3059,3130`); only the 2D slice wait has an 8 s timeout (`11281`).
- **Fix:** Add a bounded timeout; skip/defer monitor captures while hidden.

### S4-3. `manual.dose` over-focuses seed pairs even for the DVH target
- **Evidence:** `server_support.py:4631-4635,4647-4648` attaches `focus_seed_ids` to every `manual.dose` concern including `v200 > v200_max`; the browser turns any focus ids into `close-up` + `hide_unrelated` (`ui-api.js:2175-2178`).
- **Fix:** Attach seed focus only for spacing-related concerns.

### S4-4. `planning.error` never produces feedback or a checkpoint
- **Evidence:** The browser emits `planning.error`/`segmentation.error`, but `_training_feedback_for_event_clean` handles only `planning.step`/`segmentation.step`; the `status=="error"` branch (`4602-4603`) is effectively unreachable.
- **Fix:** Handle `*.error` explicitly with a failure message and optional diagnostic screenshot.

### 3.6 Internal-tree-specific hygiene observations (monitor-relevant)
- **CRLF terminators** throughout `web/server_support.py` and other monitor modules while the public tree is LF. This makes cross-tree diffs appear huge and complicates patch portability (the internal/public monitor code is semantically identical). Normalize line endings via `.gitattributes` or a one-time pass.
- **Stale codex backups** in the repo root (5 `AgenticSys.py.bak_*`/`.orig` files) and stray server artifacts (`server_codex_monitor_restart_20260730.log`, `server_codex_monitor_restart.pid`, `server_codex_restart*.log`) increase the chance of editing/searching the wrong copy — the same failure mode as the duplicated monitor engine. Remove or gitignore them.
- The working tree has 52 modified files (other workstreams). Any change to the monitor engine (S1-1) should be isolated to its own commit to avoid entanglement.

---

## 4. Suspicious / Unverified Issues

- **Cross-field clock comparison in `select_case_bridge`** (`server_support.py:399-407`): sidecar `saved_at` (flush wall-clock) is compared to snapshot `updated_at` (event time); because the flush stamp is later, the sidecar almost always wins even if it encodes an older event. *Verify with a test.*
- **Malformed `ui_state` can 500**: `/training/start` (`4992`) and `/training/stop` (`5077`) call `(data.get("ui_state") or {}).get("language")` without `isinstance`, unlike `/api/ui/event` (`4910`).
- **Unvalidated client run id** (`4989`): any string is accepted; no format/length bound; two tabs with the same id share a run.
- **Monitor scans despite the "cheap" claim**: `_training_feedback_for_event_clean`/`_training_screenshot_for_event_clean` call `_latest_plan_snapshot(agent)` with `validate_obstacles=True` by default (`4533`, `4623`) on every matched event, while stop deliberately uses `fast=True` (`5131-5135`). This can put CT/OAR segment scans on the event request thread.
- **Global event cap vs advertised "complete" catalogue**: `ui_inspector` caps the operation catalogue at 4096 while describing it as "complete" (`ui_inspector/__init__.py:47-53,791-807`).
- **Attachment caption duplication** was a real bug previously; current code avoids it via `attachments: []` (`ui-api.js:2213-2218`). Guard against regression.

---

## 5. Key Behavioral Scenarios

1. **Manual seed edit** — seed drag commits geometry and appends `manual.seed.drag` → browser re-posts via `/api/ui/event` with `already_recorded:true`, `committed_event`, `commit_status:"committed"` → server runs seed-interference check and returns feedback + `viewer-3d` screenshot with `focus_seed_ids` → browser batches feedback (2500 ms) and captures a focused 3D checkpoint.
2. **Dose recompute** — `manual.dose` is immediate; screenshot target `dose-overview` if V100 below / V200 above target, else `dvh`; always bypasses the 45 s throttle.
3. **"请停止monitor" in chat** — `turn_policy` → `ui_control` → `ui_controller training.mode stop` → `stopTrainingMode` → `/training/stop` → final `monitor_summary`.
4. **Page refresh while active** — `pagehide` sends a keepalive `auto_close` stop; on reload `restoreTrainingMonitorSnapshot` never restores a live presentation and issues a stale-safe close; hydration normalizes `active:true` to inactive.
5. **Server restart while active** — startup hydration (`server.py:626-640`) closes the run; `/api/ui/state` durable restore also closes it; a later `/training/stop` is idempotent.
6. **LLM down** — manual planning and the monitor still work deterministically; `/training/advice` without a live agent returns 500, surfaced as an error.

---

## 6. Why the Design Is Right (keep these properties)

- **Determinism** — feedback survives LLM outages and is auditable. Augment, don't replace.
- **Run-id fencing** — essential for correctness across reload/switch; extend it to every append path (S1-2).
- **Case ownership** — prevents cross-patient leakage; never trust a client-supplied `web`.
- **Non-blocking telemetry** — refusing to cold-hydrate an agent on `/api/ui/event` keeps the workstation responsive.
- **Idempotent close** — pagehide/session-switch/shutdown must never surface an error.
- **Explicit clinical boundary** — monitor output is interactive feedback, not clinical authorization.

---

## 7. Test Coverage Assessment

### 7.1 Covered

- `tests/test_training_monitor_audit.py` (12 tests): deterministic engine behavior, zh localization, summary filtering (`:208-331`); metric-unit declaration/legacy fallback (`:8-18`); lifecycle-event exclusion (`:21-37`); stale detection and non-mutating close (`:40-60`); many **source-substring** assertions across backend/frontend/CSS (`:63-205`).
- `tests/test_screenshot_trace_integration.py:66,1336` — monitor mode normalization and capture-path separation.
- `tests/test_workspace_frontend.py:545,1825,2106,2126` — edge overlay, `monitorPhase`, patch-only paths, ui-controller fallback, CSS fallbacks.
- `tests/test_runtime_contracts.py:662-674` — "stop monitor" is a UI control.
- `tests/test_manual_seed_transactions.py:796-808` — committed-only monitor events.
- `tests/test_ui_bridge_sidecar.py` — `training` key survives sidecar round-trips.

### 7.2 Gaps (high value)

1. **`/api/training/advice`** — no behavioral test, despite the documented retrospective-advice requirement.
2. **Start conflict semantics** — 409, same-run replay, mismatch only substring-asserted.
3. **Stop final report** — no assembly test for counts/strengths/issues/recommendations or language.
4. **Shutdown/restart reconciliation** — only source-asserted.
5. **Stale timeout boundaries** and `BRACHYBOT_MONITOR_STALE_SECONDS` override.
6. **`/api/ui/event` feedback path** — append/feedback/screenshot aggregation not executed.
7. **Start-intent routing** — only stop phrases tested.
8. **`ui_controller training.mode`** registry/commands untested.
9. **Monitor-mode screenshot execution** — no test that monitor captures are internal-only or that unknown modes fail.
10. **Frontend transient behavior** — throttles, batch timer, gallery lifecycle, restore, pagehide, release — substring-only.
11. **Multi-session/multi-tab isolation** — untested (acknowledged in `docs/PRODUCT_READINESS…:165`).
12. **Localization breadth** — only zh; no completeness test (how S1-5 slipped through).
13. **Feedback event breadth** — segmentation completion, `manual.dose`, needle delete/drag/restore, `planning.error`.
14. **No end-to-end/GPU validation** of thresholds (`docs/PRODUCT_READINESS…:163`).

### 7.3 Documentation gaps

- `docs/BRACHYBOT_FULL_SPEC.md` has **zero** mentions of the training monitor; `docs/ARCHITECTURE.md` mentions "monitor" only for the benchmark `auto_monitor.py`. The vision lives in `README.md` and dated audit reports, not in the canonical spec/architecture docs.

---

## 8. Improvement Roadmap Toward the Vision

Ordered by dependency. Phase A makes it trustworthy; Phase B maintainable; Phase C coach-like; Phase D a product.

### Phase A — Correctness and robustness

1. Run-scope every event append; kill the false-409 class (S1-2).
2. Cap `training.events` (S1-3).
3. Unify close into one function; always persist a summary (S1-4, S2-6).
4. Normalize/validate `run_id`; add `ui_state` isinstance guards (S2-2, suspected).
5. Complete zh localization + a completeness test (S1-5).
6. Server-own `commit_status` (S1-6).
7. Unify the advice/count event window (S2-1).
8. Fix readiness semantics and `ui_inspector` live state (S2-7, S2-8).
9. Persist on shutdown/eviction (S2-6).
10. Handle `*.error` events; fix screenshot throttle-on-failure and hidden-tab timeout (S4-1, S4-2, S4-4).

### Phase B — Consolidate the deterministic engine

11. Create `web/monitor_engine.py` with a single implementation; delete the five dead generations; keep re-exports (S1-1).
12. Model the lifecycle as an explicit `MonitorRun` state machine with typed transitions; unit-test each.
13. Make deterministic checks incremental (cache `_latest_plan_snapshot` per `(planning_id, planning_version)`).
14. Schema-version events and the monitor record; document fields; back-compat for `ui_bridge.json`.
15. Add behavioral route tests (advice, start conflicts, stop summary, shutdown/restart, staleness boundaries, throttles, multi-tab isolation).
16. Add a monitor architecture doc referenced from `ARCHITECTURE.md` and `BRACHYBOT_FULL_SPEC.md`.

### Phase C — UX: from passive glow to actionable coaching

17. **Monitor HUD panel** (augmenting the edge overlay): workflow checklist with completed/current/pending prerequisites, live event timeline, current plan metrics (V100/D90/V200/OAR Dmax), and pending feedback. The edge overlay is a nice "you are being watched" cue but communicates no content.
18. **Structured feedback cards** with severity (info/warn/blocking), a one-line "why", and deep-link actions ("Show me" → panel/slice/camera/seed focus). Today feedback is plain markdown in chat.
19. **Timeline + export** in the HUD (JSON/Markdown), implementing the recommended "Planning audit timeline export" (`PRODUCT_READINESS…:174`).
20. **Coaching modes**: `silent` (evidence only), `mentor` (default), `strict` (all checkpoints); store in `training.start` and honor in throttles/selection.
21. **Session continuity**: allow a reload within the same process to *resume* when the browser re-attaches with the same run id and a fresh keepalive, with a short grace window (e.g. 60 s) before auto-close.
22. **Accessibility & i18n**: colorblind-safe severity, full keyboard operation, screen-reader announcements per checkpoint, complete bilingual coverage.
23. **Capture reliability UX**: "capturing evidence…" indicator, one retry on failure, never leave a stale throttle.

### Phase D — Product capabilities toward the training vision

24. **Per-site training rubrics** (prostate/pancreas/liver/head-neck) replacing global thresholds; extends `_source_backed_target_context` (`PRODUCT_READINESS…:177`).
25. **Competency scoring and trends**: score each run against the rubric; store per-user trends. Revive/harden `performance_tracker` (S3-3) or add a dedicated training-report store.
26. **Teach/quiz mode**: ask a question at a checkpoint and grade against the deterministic rubric, linking the answer to `clinical_kb`.
27. **Plan comparison**: auto vs manual vs revised with DVH overlays and metric deltas (`PRODUCT_READINESS…:179`).
28. **Cold-spot finder integration**: highlight CTV subregions below Rx and propose seed targets (`PRODUCT_READINESS…:178`).
29. **Case snapshot bundle**: one-click export/import of CT path, masks, seeds, needles, dose, DVH, report, chat rationale, and monitor timeline (`PRODUCT_READINESS…:175`).
30. **Multi-role presets** (clinical/research/training/developer) selecting monitor verbosity and tools (`PRODUCT_READINESS…:181`).
31. **Multi-observer/attending review**: read-only subscription to a trainee's run with comments, under the same run-id fencing.
32. **Evidence grading**: attach guideline citations from `clinical_kb` to each issue so feedback is defensible.

### Cross-cutting: observability and evaluation

33. **Monitor run metrics**: feedback latency p50/p95, event-path latency, screenshot success rate, staleness-trigger rate, 409 rate, override-after-warning rate; log per run and expose per case.
34. **Threshold validation harness**: replay recorded runs against alternative thresholds to tune per-site rubric sensitivity/specificity before clinical rollout.
35. **Golden-run fixtures**: capture realistic runs (events + plan snapshots) and assert deterministic feedback/summary, so refactors cannot silently change clinical messaging.

---

## 9. Prioritized Backlog

| # | Item | Type | Risk | Effort |
|---|---|---|---|---|
| 1 | Run-scope every event append (S1-2) | Correctness | Low | M |
| 2 | Cap `training.events` (S1-3) | Correctness | Low | S |
| 3 | Unify close + always persist summary (S1-4, S2-6) | Correctness | Low | M |
| 4 | Consolidate deterministic engine (S1-1) | Maintainability | Med | L |
| 5 | Translation completeness test + fill gaps (S1-5) | Correctness | Low | M |
| 6 | Server-own `commit_status` (S1-6) | Correctness | Med | M |
| 7 | Behavioral route tests (advice/start/stop/shutdown) | Quality | Low | L |
| 8 | Unify advice/count window (S2-1) | Correctness | Low | S |
| 9 | Fix readiness + `ui_inspector` live state (S2-7/8) | Correctness | Low | S |
| 10 | Monitor HUD + structured feedback cards (C17-18) | UX | Med | L |
| 11 | Timeline + audit export (C19) | Product | Low | M |
| 12 | Coaching modes + resume-on-reload (C20-21) | UX | Med | M |
| 13 | Per-site rubrics + competency trends (D24-25) | Product | High | L |
| 14 | Plan comparison + cold-spot + case bundle (D27-29) | Product | High | L |
| 15 | Metrics + threshold validation harness (34-35) | Quality | Med | L |

*(S=hours, M=days, L=1–2 weeks, indicative.)*

---

## 10. Appendix — Quick Reference

### 10.1 Constants and tunables

| Name | Default | Location |
|---|---|---|
| `_UI_BRIDGE_MAX_EVENTS` (`BRACHYBOT_UI_BRIDGE_MAX_EVENTS`) | 500 | `server_support.py:357` |
| `_MONITOR_STALE_SECONDS` (`BRACHYBOT_MONITOR_STALE_SECONDS`, min 60) | 1800 s | `server_support.py:359-362` |
| Feedback throttle (non-high-value) | 15000 ms | `brachybot-ui-api.js:2039` |
| Feedback aggregate flush | 2500 ms | `brachybot-ui-api.js:1845` |
| Screenshot throttle (ordinary) | 45000 ms | `brachybot-ui-api.js:2127` |
| Screenshot scheduling delay | 500 ms | `brachybot-ui-api.js:2224` |
| Stop request timeout | 8000 ms | `brachybot-3d-manual.js:2427` |
| Edge fade-out | 280 ms | `brachybot-ui-api.js:1899` |
| UI bridge checkpoint debounce | 250 ms | `planning_routes.py:1021-1050` |
| Screenshot PNG decode limit | 25 MB | `server_support.py:3545-3560` |

### 10.2 Event type → feedback / screenshot mapping (effective engine)

| Event | Feedback | Screenshot target |
|---|---|---|
| `manual.seed.*` (committed) | spacing violation / cold coverage / recompute reminder | `viewer-3d` (+`focus_seed_ids`) |
| `manual.needle.*` (committed) | obstacle hit / collision / safe-path reminder | `viewer-3d` |
| `manual.dose` (committed) | V100/D90 summary | `dose-overview` (concern) else `dvh` |
| `segmentation.step` done | stage completed | `viewer-3d` |
| `planning.step` trajectory_* / seed_planning done | stage completed | `viewer-3d` |
| `planning.step` dose_calc/dose_eval/full done | stage completed | `dose-overview` |
| `planning.error`/`segmentation.error` | **none today** | **none today** |
| `training.start` | excluded from training counts | — |

### 10.3 Client/server ownership checks

- Client owns run: `trainingMonitorState.sessionId/runId` (`ui-api.js:1770-1776`, `3d-manual.js:2341-2350,2449-2451`).
- Server owns run: `bucket["training"].run_id` (`server_support.py:376-385`, `planning_routes.py:4892-4901`).
- Reconciliation: hydration/restore normalizes `active:true` to inactive (`server.py:626-640`, `planning_routes.py:4752-4773`, `ui-api.js:1951-1977`).

### 10.4 Primary source documents (present in the internal tree)

- `README.md:642-651` — user contract.
- `docs/UI_CONTROL_MANUAL_TRAINING_REPORT_2026-06-30.md` — original implementation.
- `docs/PRODUCT_READINESS_UI_MANUAL_TRAINING_AUDIT_2026-07-02.md` — readiness audit and next-step recommendations.
- `docs/CODE_REVIEW.md` — monitor fix rounds (search for "monitor"/"training").
- Commits: `8818a73b6`, `c7522e994`, `dfa68caac`, `a9f75fa1e`, `4043cec5c`, `4260b18c8`, `1cd78cf79`, `a4ff1869d`, `b17ddfe5b`, `c71124673`, `a8d97fce4`, `bc092ae1c`.

### 10.5 Internal line-reference accuracy

All monitor line numbers above were verified in `<workspace>/BrachyBot`. The monitor modules (`server_support.py`, `planning_routes.py`, `brachybot-ui-api.js`, `brachybot-3d-manual.js`, `turn_policy.py`, `ui_screenshot`, `ui_inspector`, `ui_controller`, `ui_content`, `test_training_monitor_audit.py`) are line-for-line equivalent to the public tree within the monitor region. Only these references are internal-specific and were adjusted: `index.html` (`80`, `448`, `912-913`; the public tree adds an auth-boot block) and `README.md:642-651`.

---

*End of analysis. No code was modified by this document's author.*
