# BrachyBot UI Control, Manual Planning, and Training Monitor Product Readiness Audit

Date: 2026-07-02
Source reviewed: latest `origin/main` from `https://github.com/Haitao-Lee/BrachyBot.git`, commit `2ac18679e69c2c79fc67e386e3bfaa33a29d6935`.

## Scope

This audit checks whether BrachyBot now supports three product goals:

1. BrachyBot can understand current Web UI state and control every user-facing control through chat.
2. The Web UI can still complete a full manual planning workflow when the LLM API is unavailable.
3. BrachyBot can monitor or train a user during manual or automatic planning, give live and retrospective advice, and finish with a summary report.

The review also checked dose-calculation integrity, agent routing behavior, security-sensitive execution tools, and product-readiness gaps from the perspective of a clinical researcher/operator.

## Executive Summary

| Area | Status | Notes |
|---|---:|---|
| UI state awareness | Implemented | Frontend sends state snapshots and event logs to `/api/ui/state` and `/api/ui/event`; agent memory stores `ui_state`; chat requests include `collectUIState()`. |
| UI control by chat | Implemented | `ui_controller` has 73 structured controls; static check confirmed all registry targets are handled in `web/app/index.html`. Generic `ui.control` supports safe DOM id/selector operations. |
| Screenshot-aware answers | Implemented | `ui_screenshot` targets exactly match frontend screenshot target map, including `dose-overview` and `dvh`. |
| Manual planning without LLM | Implemented with clinical boundary | Input panel exposes direct segmentation, planning, dose, report, export controls. Manual 3D needle/seed editing recomputes dose through myDoseNet only. |
| Training/monitoring mode | Implemented | Start/stop/advice endpoints exist; frontend records events, throttles feedback screenshots, and returns a final deterministic advice report. |
| Retrospective advice after planning | Implemented | `/api/training/advice` builds advice from current metrics and UI events without requiring an active monitor session. |
| Simplified Gaussian manual dose | Removed from active product path | Manual recompute uses myDoseNet. `plan_refinement` no longer simulates dose and now marks recalculation as required. Legacy Gaussian fitting files/backups were removed. |
| Knowledge question accidentally triggering planning | Hardened | Router now short-circuits educational questions as `knowledge_query` when no execution intent is present; workflow enforcer is gated by `_planning_requested()`. |
| Developer code/shell capability | Safe-by-default | `code_executor` and `shell_executor` are disabled unless explicitly enabled in a trusted environment. Capability state is exposed in `/api/status` and `/api/ui/capabilities`. |

## Requirement Coverage Table

| Requirement | Implementation Evidence | Verification |
|---|---|---|
| BrachyBot knows UI state | `web/app/index.html::collectUIState()`, `/api/ui/state`, `AgentMemory.set_ui_state()` | Static inspection confirmed active panel, viewer, overlays, data tree, manual state, training state, controls, CT metadata are collected. |
| BrachyBot can control UI controls | `tool_factory/ui_controller/__init__.py`, `_executeUIAction()` | Static registry check: 73 controls, missing frontend handlers: `[]`. |
| Control any ordinary DOM control if no structured target exists | `ui.control` registry target, `executeGenericUIControl()` | Supports click, set, toggle, focus, blur by id/selector/JSON payload. |
| Capture and analyze UI screenshots | `tool_factory/ui_screenshot`, `_SCREENSHOT_TARGET_MAP`, `_interceptScreenshot()` | Tool targets and frontend map are identical; `dose-overview` and `dvh` are supported. |
| Manual workflow without LLM | Input panel manual buttons, `runSegmentationStep()`, `runPlanningStep()`, `runPlanning()` | Static inspection confirms direct API calls exist. Clinical correctness still requires end-to-end run on the remote GPU workstation. |
| Manual 3D needle creation/editing | `addManualNeedle()`, `_makeNeedleHandle()`, `onManualNeedleHandleEdited()` | Needle endpoint handles are created; edits update data tree and overlays. |
| Manual seed placement/editing | `addManualSeed()`, `_makeSeedMesh()`, `onManualSeedEdited()` | Seeds are attached to trajectories and trigger dose recomputation. |
| Recalculate dose after manual edits | `/api/manual_planning/update`, `_compute_manual_ai_dose()` | Uses myDoseNet via `batch_seed_dose_calculation_dl`; no Gaussian fallback. |
| Live training monitor | `/api/training/start`, `reportUIEvent()`, `_training_feedback_for_event()` | Events produce deterministic feedback; screenshots are suggested at high-value checkpoints. |
| Retrospective plan advice | `/api/training/advice`, `_build_plan_advice()` | Advice works from current metrics and recent UI events, even outside active monitoring. |
| Stop monitor and produce final report | `/api/training/stop`, `stopTrainingMode()` | Stop returns event counts, feedback, issues, strengths, recommendations, and renders in chat. |
| Automatic and manual planning use same result surfaces | `refreshPlanningUI()`, dose overlay/DVH/report paths | Manual preview stores dose, metrics, DVH, seeds, needles into the same memory keys used by the UI. |
| Avoid breaking coordinate chain | Current changes did not alter 2D/3D coordinate conversion, slice transforms, seed world-to-planning-grid transforms, or viewer drawing math. | Only dose-model boundary, router, status/capabilities, docs, and stale files were changed. |

## Changes Made In This Audit

### 1. Plan refinement no longer fakes dose

File: `tool_factory/plan_quality/plan_refinement.py`

Before:

- `PlanRefinementTool` added candidate seeds and updated `dose_distribution` with `_simulate_dose_addition()`.
- `_simulate_dose_addition()` used a Gaussian falloff, causing non-myDoseNet dose estimates to appear as if they were improved metrics.

After:

- The tool proposes seed candidates from cold CTV voxels only.
- It returns `metrics_before`, `candidate_seeds`, and `requires_dose_recalculation`.
- It sets `dose_engine: myDoseNet`.
- It no longer simulates or claims improved post-refinement dose metrics.

### 2. Legacy Gaussian dose code removed or disabled

Files:

- Deleted `plans/fitting_model.py`
- Deleted `plans/core.py.bak`
- Deleted `plans/geometry.py.bak`
- Deleted `plans/utilizations.py.bak`
- Updated `plans/geometry.py`
- Updated `plans/utilizations.py`
- Updated `.gitignore`

What changed:

- Removed the unused oriented Gaussian volume generator from `plans/geometry.py`.
- Removed tracked `.bak` files that contained old Gaussian code and polluted global searches.
- Disabled `deep_learning_optimization()` with a clear `NotImplementedError` because it depended on the removed analytical dose-fitting path.
- Added `*.bak` to `.gitignore`.

Remaining boundary:

- Some compatibility stubs still mention that the legacy analytical model was removed. They are intentionally fail-closed and do not calculate dose.

### 3. Knowledge queries no longer look like planning execution

File: `agents/router_agent.py`

Before:

- Fallback routing could classify educational questions containing "planning", "seed", or "implant" as `clinical_planning`.
- The workflow enforcer was already protected by `_planning_requested()`, but the trace could still look wrong.

After:

- Router short-circuits knowledge-only questions such as "introduce", "why", "benefit", "compare", "介绍", "为什么", "好处", "对比" when no execution verb exists.
- These requests now route as `knowledge_query`.

Validation:

- `why use brachytherapy planning instead of chemo` routes to `knowledge_query`.
- `请你向我介绍放射性粒子植入规划的好处，为啥不用其他治疗` routes to `knowledge_query`.
- `请执行放射性粒子植入规划` still routes to `clinical_planning`.

### 4. UI capability endpoint added

File: `web/server.py`

New endpoint:

```http
GET /api/ui/capabilities
```

It returns:

- Structured UI control registry
- Screenshot targets
- Manual workflow steps
- Manual 3D planning capabilities
- Training monitor capabilities
- Code/shell executor enablement state

`/api/status` now also reports:

- `code_executor_enabled`
- `shell_executor_enabled`
- `shell_mode: argv_allowlist_no_shell`

### 5. README updated

File: `README.md`

Added:

- `GET /api/ui/capabilities` documentation.
- Clear statement that `plan_refinement` only proposes candidates and requires myDoseNet recalculation before accepting any dose metrics.

## Product-Level Assessment

### What is now product-ready enough for integrated testing

| Capability | Readiness |
|---|---|
| Agent-controlled UI tab/viewer/overlay/data-tree/report actions | Ready for browser integration testing |
| Unified screenshot target contract | Ready |
| Manual segmentation/planning/dose/report button workflow | Ready for GPU workstation end-to-end testing |
| Manual 3D needle and seed editing | Ready for visual QA and usability testing |
| Live monitor and retrospective advice | Ready for workflow simulation |
| Dose model boundary | Much safer: no active manual Gaussian dose path |
| Knowledge-vs-execution routing | Improved and testable |

### What still requires real environment validation

These are not code holes, but they cannot be fully certified from static review alone:

1. GPU workstation myDoseNet inference latency after repeated manual seed drags.
2. Browser rendering performance when all OARs, dose textures, seeds, needles, and DVH are visible.
3. Clinical validity of training feedback thresholds for different tumor sites.
4. Full report PDF/HTML visual layout after multiple user-edited manual plans.
5. Multi-user/session isolation under concurrent browser tabs.

## Recommended Next Product Improvements

These are feasible follow-up features that would make BrachyBot stronger as a clinical research workstation:

| Feature | Value | Feasibility |
|---|---|---|
| UI capability self-test button | Lets users verify all controls, screenshots, and APIs before a case | High |
| Planning audit timeline export | Exports every manual/agent action as a reproducible JSON timeline | High |
| Case snapshot bundle | One-click export/import of CT path, masks, seeds, needles, dose, DVH, report, and chat rationale | High |
| Dose recompute debounce for drag events | Prevents excessive myDoseNet calls while dragging seeds/needles | High |
| Training rubric profiles | Different feedback criteria for prostate, pancreas, liver, head/neck | Medium |
| Interactive cold-spot finder | Highlights CTV subregions below Rx dose and proposes manual seed targets | Medium |
| Multi-plan comparison | Compare auto plan vs manual plan vs revised plan with DVH overlays and metric deltas | Medium |
| True sandboxed code execution | Keep code-creation ability while isolating file system and resources in a container/subprocess | Medium |
| Role-based mode switch | Clinical, research, training, developer UI presets | Medium |

## Validation Performed

Commands run locally on the GitHub clone:

```powershell
git fetch origin main
python -m py_compile web/server.py agents/router_agent.py tool_factory/plan_quality/plan_refinement.py plans/geometry.py plans/utilizations.py AgenticSys.py
node -e "extract and compile all inline scripts from web/app/index.html"
```

Additional checks:

- UI controller registry count: 73.
- Missing frontend handlers for registry controls: none.
- Screenshot tool targets match frontend screenshot targets exactly.
- `PlanRefinementTool` sample run returns candidate seeds and `requires_dose_recalculation=True`.
- Route smoke test confirms educational brachytherapy questions route to `knowledge_query`, while explicit execution requests route to `clinical_planning`.

## Files Changed

| File | Purpose |
|---|---|
| `.gitignore` | Ignore ordinary `.bak` files going forward. |
| `agents/router_agent.py` | Prevent knowledge questions from being classified as clinical execution. |
| `plans/geometry.py` | Remove unused oriented Gaussian generator. |
| `plans/utilizations.py` | Remove stale fitting-model reference and disable legacy analytical optimizer. |
| `tool_factory/plan_quality/plan_refinement.py` | Convert refinement from fake dose simulation to candidate proposal requiring myDoseNet recalculation. |
| `web/server.py` | Add `/api/ui/capabilities`; expose execution tool status in `/api/status`. |
| `README.md` | Document capability endpoint and plan-refinement dose boundary. |
| `plans/core.py.bak`, `plans/geometry.py.bak`, `plans/utilizations.py.bak`, `plans/fitting_model.py` | Removed stale backup/legacy analytical dose code. |

## Final Requirement Checklist

| Requirement | Result |
|---|---|
| Do not break existing coordinate display chain | Satisfied: no coordinate drawing/conversion code changed. |
| BrachyBot knows UI state | Satisfied. |
| BrachyBot can control UI controls from chat | Satisfied by structured registry plus generic fallback. |
| Web UI works without LLM for manual planning | Satisfied in code; needs GPU workstation E2E run for runtime certification. |
| Training monitor works during manual/auto planning | Satisfied. |
| Training advice works after planning completion | Satisfied. |
| Manual needle/seed creation and editing exist | Satisfied. |
| Recompute dose/DVH after manual seeds | Satisfied via myDoseNet only. |
| Remove simplified Gaussian dose model from active path | Satisfied. |
| Do not leave hidden stale backup code | Improved: tracked `.bak` files removed. |
| Update README | Satisfied. |
| Add detailed docs report | Satisfied: this file. |
