# UI Control, Manual Planning, and Training Monitor Implementation Report

Date: 2026-06-30

## Goal

This change extends BrachyBot from an LLM-only planning assistant into a UI-aware planning workstation. The implementation targets three product requirements:

1. BrachyBot can observe the current Web UI state and control UI actions through structured tool calls.
2. The Web UI remains usable as a complete manual planning application when LLM APIs are unavailable.
3. BrachyBot can run a live training/monitoring session during manual or automatic planning, then produce a final advice report.

## Product Workflow

### UI-aware BrachyBot control

- The frontend now collects a structured UI snapshot through `collectUIState()`.
- The snapshot includes active panel, viewer settings, overlays, data tree visibility, manual planning status, and training monitor status.
- The snapshot also includes a bounded, redacted inventory of clickable/input controls. Sensitive fields such as API keys, tokens, secrets, and passwords are reported as `[redacted]`.
- The browser sends snapshots to the backend via `POST /api/ui/state`.
- User interactions are recorded through `POST /api/ui/event`, including button clicks, sliders, input changes, panel switches, planning steps, segmentation steps, manual needle/seed edits, and dose recomputation.
- `ui_controller` now exposes structured actions for:
  - `ui.state`
  - `ui.control`
  - `plan.run`
  - `plan.run_manual_step`
  - `training.mode`
  - `manual.needle.create`
  - `manual.seed.add`
  - `manual.dose.recompute`
  - `manual.plan.finish`
  - `3d.dose_surface`

### Manual planning without LLM dependency

Manual planning can now be completed from the Input and Viewer panels:

1. Load CT.
2. Run CTV segmentation.
3. Run OAR segmentation.
4. Initialize and refine trajectories.
5. Run seed planning.
6. Calculate dose.
7. Evaluate dose and DVH.
8. Auto-fill or export the report.

The `plan.run` UI controller action now calls the real frontend `runPlanning()` path instead of injecting a chat prompt. This is important because a failed or expired LLM key should not prevent the UI from running the clinical pipeline through existing backend APIs.

### Manual needle and seed editing

The 3D viewer now supports manual fine planning:

- Add an editable needle near the current target.
- Drag the needle entry/tip handles in 3D.
- Add seeds along the selected/current manual needle.
- Drag existing seed meshes.
- Recompute the fast manual dose/DVH preview after seed or needle edits.
- Keep Data Tree, 2D seed/needle projections, 3D meshes, dose overlay, DVH, and metrics synchronized.

Needle endpoint handles are separate `needle_handle` objects, while clinical needle meshes remain thinner than seed meshes so seeds stay visible.

## Training Monitor

The training monitor supports both live and retrospective use:

- Live mode starts with `POST /api/training/start` or `ui_controller` target `training.mode` command `start`.
- While active, UI events are appended to the backend event buffer.
- The backend returns lightweight deterministic feedback for important events, such as segmentation, planning steps, needle edits, seed edits, and dose recomputation.
- For high-value checkpoints, such as dose recomputation or completed planning, the backend can return a `suggested_screenshot` target. The frontend rate-limits these suggestions and captures a dose overview, DVH, or 3D view into the chat.
- The user can request detailed advice at any time with `POST /api/training/advice`.
- Stopping the monitor with `POST /api/training/stop` returns a final report summarizing observed workflow activity and current plan quality.

The backend advice engine currently uses current metrics and event history deterministically. It does not depend on an LLM, so it remains available when LLM APIs fail.

## Backend Changes

Implemented in `web/server.py`:

- UI state bridge:
  - `GET /api/ui/state`
  - `POST /api/ui/state`
  - `POST /api/ui/event`
- Training monitor:
  - `POST /api/training/start`
  - `POST /api/training/stop`
  - `GET /api/training/advice`
  - `POST /api/training/advice`
- Manual planning preview:
  - `POST /api/manual_planning/update`
- Plan advice helpers:
  - `_latest_plan_snapshot`
  - `_build_plan_advice`
  - `_training_feedback_for_event`
  - `_compute_manual_preview`

`_compute_manual_preview` creates an interaction-speed dose preview from manual world-coordinate seeds. It updates the same frontend-facing memory fields used by the existing dose overlay and DVH paths.

## Frontend Changes

Implemented in `web/app/index.html`:

- Manual Fine Planning controls in the Input panel:
  - Monitor
  - Finish Monitor
  - Add Needle
  - Add Seed
  - Recompute Dose
  - Detailed Advice
  - Manual seed strength, sigma, and cutoff inputs
- UI bridge:
  - `syncUIBridgeState`
  - `reportUIEvent`
  - `instrumentUIControls`
- Chat shortcuts:
  - Start monitor/training mode.
  - Stop monitor.
  - Request current plan advice.
- Manual 3D editing:
  - Needle/seed creation.
  - Needle endpoint drag handles.
  - Seed drag recomputation.
  - Scene/Data Tree/2D overlay synchronization.
- UI controller execution:
  - Manual actions now call actual frontend functions instead of indirect chat prompts.
  - Dose surface mode can be controlled through `ui_controller`.

## Agent Tooling Changes

Implemented in `tool_factory/ui_controller/__init__.py`:

- New controls were added to `CONTROL_REGISTRY`.
- Validation now accepts manual planning, training, UI state sync, and dose surface controls.
- Human-readable execution descriptions were added for trace readability.

Implemented in `tool_factory/ui_inspector/__init__.py`:

- The workflow list now includes Manual Planning and Training Monitor flows.

Implemented in `config/prompts/planning_agent.md`:

- The tool reference now lists the manual workflow, manual editing, training monitor, and dose surface controls.

## Coordinate Safety

The existing CT, mask, dose, seed, and 2D/3D coordinate chain was intentionally preserved.

This implementation does not change the established viewer coordinate transforms. Manual preview uses seed/needle world coordinates and SimpleITK `TransformPhysicalPointToIndex` on the backend to map world coordinates into CT voxel indices. This keeps manual editing compatible with the current viewer world-coordinate convention while avoiding ad hoc axis flips.

## Clinical Boundary

The manual dose preview is designed for responsive interaction and training feedback. It is not a replacement for the formal planning pipeline dose engine. The formal report and clinical approval workflow should continue to rely on the established planning pipeline outputs and independent clinical review.

## Verification Checklist

- UI controller can switch panels and trigger real manual workflow functions.
- UI controller has a generic `ui.control` fallback for new buttons, inputs, selects, and checkboxes.
- Manual workflow buttons no longer depend on a working LLM key.
- Training mode starts, records events, emits live feedback, and produces final advice.
- Training mode can request rate-limited automatic screenshots for visual review checkpoints.
- Manual needles and seeds appear in 3D, Data Tree, and 2D overlays.
- Manual seed/needle edits recompute a fast dose/DVH preview.
- Existing coordinate conversion functions were not changed.
- Existing automatic planning, report generation, screenshots, and dose surface mode remain compatible.
`ui.control` is a safe fallback for newly added UI controls that do not yet have a dedicated target. It accepts an element id or CSS selector and supports `click`, `set`, `toggle`, `focus`, and `blur`. It does not execute arbitrary JavaScript.

