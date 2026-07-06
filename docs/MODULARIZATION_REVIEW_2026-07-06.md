# BrachyBot Modularization Review - 2026-07-06

## Scope

This update reduces oversized source files while preserving public entry points
and runtime behavior. `plans/utilizations.py` was intentionally not split because
it contains coordinate, dose, and trajectory logic with high regression risk.

## Current Module Map

### Agent Runtime

- `AgenticSys.py` remains the public facade for `from AgenticSys import BrachyAgent`.
- `agent_runtime/core.py` contains `PlanningPhase`, `ToolRegistry`, `AgentMemory`,
  and `ToolResultPipeline`.
- `agent_runtime/response_tools.py` contains response formatting, tool-result
  synthesis, query classification, and source attribution helpers.
- `agent_runtime/llm_runtime.py` contains LLM function-calling and streaming
  execution loops.
- `agent_runtime/chat_workflows.py` contains chat entry points, rule-based
  fallback, preoperative planning, intraoperative replanning, and status helpers.

### Web API

- `web/server.py` remains the server entry point and app factory.
- `web/server_support.py` contains shared constants, security helpers, path
  validation, rate limiting, screenshot signing, task tracking, UI bridge state,
  manual AI dose computation, readiness, and training feedback helpers.
- `web/__init__.py` marks the web layer as an explicit package for static
  analyzers, pytest discovery, and older packaging tools.
- `web/routes/viewer_routes.py` contains CT loading, 2D viewer, 3D mesh, dose
  overlay, and viewer organ routes.
- `web/routes/planning_routes.py` contains planning, segmentation, configuration,
  UI bridge, training, chat, exports, task streaming, screenshot, and viewer
  control routes.
- Route modules import public support names directly and bind required private
  helpers through the `server_support` module object. `server_support.__all__`
  intentionally exposes only the public support surface.

### Frontend

- `web/app/index.html` is now the DOM shell plus ordered script/link tags.
- `web/app/static/css/brachybot-theme-layout.css` holds theme variables, base layout, and shell styling.
- `web/app/static/css/brachybot-chat-status.css` holds chat, markdown, execution trace, and live status styling.
- `web/app/static/css/brachybot-panels-viewers.css` holds panels, viewer cards, data tree, and visualization chrome.
- `web/app/static/css/brachybot-report-controls.css` holds report/export and remaining control styles.
- `web/app/static/js/brachybot-chat-core.js` holds chat rendering and markdown.
- `web/app/static/js/brachybot-chat-todo.js` holds live todo/progress widgets.
- `web/app/static/js/brachybot-ui-api.js` holds API, upload, UI bridge, and screenshot helpers.
- `web/app/static/js/brachybot-viewer-volume.js` holds volume loading and 2D rendering.
- `web/app/static/js/brachybot-viewer-layout.js` holds viewer layout and data-tree controls.
- `web/app/static/js/brachybot-3d-manual.js` holds 3D meshes, dose surfaces, manual planning, and training monitor behavior.
- `web/app/static/js/brachybot-manual-annotation.js` holds manual workflow and annotation tools.
- `web/app/static/js/brachybot-dvh-planning.js` holds DVH, metrics, OAR table, and clinical evaluation widgets.
- `web/app/static/js/brachybot-report-shell.js`, `brachybot-report-editor.js`, and
  `brachybot-report-export.js` hold report UI, form editing, figure capture, and export.

### Clinical Knowledge Base

- `clinical_kb/guidelines_brachytherapy.md` is now a stable index.
- Split topic files live under `clinical_kb/guidelines/`.
- Verified raw sources remain under `clinical_kb/sources/**/raw/*.md`.
- `tool_factory/clinical_kb/__init__.py` searches both the index and split topic files.

## Compatibility Rules

- Keep `AgenticSys.py` as the public import path.
- Keep the `BrachyAgent` mixin order and required runtime methods intact. The
  facade validates this contract during initialization so future refactors fail
  fast if a required mixin method is missing.
- Keep `web/server.py` as the public server startup path.
- Keep frontend scripts as non-module scripts until a separate migration plan
  replaces global function dependencies.
- Keep `plans/utilizations.py` intact unless coordinate/dose golden tests are
  expanded enough to support a safe split.
- Update `config/prompts/system_prompt.md` whenever the maintenance module map
  changes so LLM-assisted code editing targets the correct files.

## Verification Plan

Required checks after modularization:

1. Python compile check for all changed Python files.
2. Node syntax check for every new `brachybot-*.js` file.
3. Flask app creation smoke test to ensure route registration succeeds.
4. Route inventory comparison to confirm original API endpoints remain registered.
5. Clinical KB query smoke test for `guidelines` and `source_search`.
6. Git diff review for accidental edits to `plans/utilizations.py`.
