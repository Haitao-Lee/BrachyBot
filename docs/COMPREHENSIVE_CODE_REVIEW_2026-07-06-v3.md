# Comprehensive Code Review — 2026-07-06 (v3)

**Review scope:** Commit `418381c` → `0084554`
**Files reviewed:** agent_runtime/ (5 files), web/server.py, web/server_support.py, web/routes/ (2 files), web/app/ (static/ JS+CSS + index.html), AgenticSys.py, config/prompts/system_prompt.md, clinical_kb/, tool_factory/, brachybot.py, tests/, .gitignore, requirements.txt
**Total:** ~40,000 lines across all files
**Status:** 9 CRITICAL, 12 HIGH, 19 IMPORTANT, 20 MINOR issues found

---

## CRITICAL (9)

### C1. Missing `AgentMemory` import in `agent_runtime/llm_runtime.py`
- **File:** `agent_runtime/llm_runtime.py:3` (import), `:49`, `:1014`, `:1315` (usage)
- `from agent_runtime.core import PlanningPhase, ToolResultPipeline` omits `AgentMemory`. Lines 49/1014/1315 call `AgentMemory.is_ct_loaded()` → `NameError` at runtime.

### C2. `DOSE_MODEL_SCALE_GY` not imported in `web/server.py`
- **File:** `web/server.py:507`
- `_build_report_interpretation()` uses bare name `DOSE_MODEL_SCALE_GY`. Defined in `server_support.py:70` but not imported in `server.py` (import block lines 18-26). → `NameError` when `/api/report/auto-fill` called with scope `"interpretation"`.

### C3. Streaming forced-search post-processing inside `else` block
- **File:** `agent_runtime/llm_runtime.py:1241-1253`
- Step recording (`forced_step["status"]="done"`, `yield_event`) and search-result message injection indented inside `else:` block → only executes on FAILURE. Non-stream version (lines 290-298) correctly has these outside if/else. → LLM receives no search results on success in streaming mode.

### C4. Missing path validation in `api_segmentation` and `api_planning_run_step`
- **File:** `web/routes/planning_routes.py:304-309` (`api_segmentation`), `:422-426` (`api_planning_run_step`)
- Both accept `image_path`/`ct_image_path` from user JSON body and pass directly to segmentation/planning tools **without calling `_validate_path()`**. Other routes (header_info, viewer_load, preoperative_plan, intraoperative_plan) all validate their paths.
- **Risk:** Arbitrary file read / traversal via `/etc/passwd`, `/data/restricted/other_patient.dcm`.
- **Fix:** Add `if not _validate_path(image_path): return jsonify({"error": "Invalid path"}), 400`.

### C5. `_rate_limit_store` lock-free under concurrent requests
- **File:** `web/server_support.py:64`, `796-818`
- `_rate_limit_store` (`Dict[str, list]`) is read/written by `_check_rate_limit()` without any lock. With Flask's threaded model, multiple threads simultaneously filter/reassign per-IP timestamp lists. → `ValueError: list.remove(x): x not in list` or lost writes. Counter `_rate_limit_cleanup_counter` (line 793) also bare-global.
- **Fix:** Guard with `threading.Lock()`.

### C6. No `"use strict"` in 10/11 frontend JS files
- **Files:** All `web/app/static/js/brachybot-*.js` except `report-shell.js:14`
- 10 split JS files run in sloppy mode. In an 11-file global-scope architecture, accidental assignment to undeclared variable becomes silent global instead of `ReferenceError`. → Hard-to-find bugs, especially during refactoring.

### C7. Infinite `requestAnimationFrame` render loop in 3D viewer
- **File:** `web/app/static/js/brachybot-3d-manual.js:463-498`
- `animate()` calls `requestAnimationFrame(animate)` unconditionally — never stops. Re-renders scene at 60fps even with zero interaction or mesh changes. → Continuous battery drain on portable devices.
- **Fix:** Only run loop when scene has pending updates; stop on idle.

### C8. Hardcoded welcome message and status strings bypass i18n toggle
- **File:** `web/app/static/js/brachybot-chat-core.js:149,257,1718`, `ui-api.js:407-409,813`
- Welcome message `"Welcome to BrachyBot. Describe your brachytherapy case..."`, Thinking indicator, and CT loading status messages are hardcoded in English. When user toggles EN→中, these stay English. No `data-i18n-zh` attributes.
- **Fix:** Make all user-visible strings i18n-aware.

### C9. Duplicate `escHtml()` function definition
- **File:** `brachybot-chat-core.js:1` AND `brachybot-report-editor.js:1`
- Second definition silently overwrites first. Identical today but creates XSS risk if only one copy is updated in the future.

---

## HIGH (12)

### H1. `_record_experience` crashes when `_init_self_evolution` fails
- **File:** `AgenticSys.py:420-432` → `agent_runtime/chat_workflows.py:1469`
- `_init_self_evolution()` except block does not set `self.exp_memory = None`. → `AttributeError` when `_record_experience` tries `if not self.exp_memory:`.

### H2. Invalid CSS `font-family` syntax
- **File:** `web/app/static/css/brachybot-theme-layout.css:396`
- `font-family: 'Inter, sans-serif';` — quotes wrap entire value including comma and fallback. → Fallback `sans-serif` never used.

### H3. Missing `_cancelled()` check at streaming loop top
- **File:** `agent_runtime/llm_runtime.py:1286`
- Non-stream loop checks `_cancelled()` at every iteration top (line 338). Stream version starts while loop at 1286 without this check — cancel only checked inside tool execution loop (line 1541). → User cancel between LLM calls is ignored.

### H4. Inconsistent CT-loaded gate: stream vs non-stream
- **File:** `agent_runtime/llm_runtime.py:438` (non-stream) vs `:1314-1316` (stream)
- Non-stream: `_no_files_loaded` checks both UI state AND `self.memory.retrieve("ct_image")`. Stream: `ct_loaded` only checks `AgentMemory.is_ct_loaded(ui_state)` (UI state only). → If CT in memory but UI says not loaded, stream blocks CT tools.

### H5. Double `_store_tool_result` in streaming path
- **File:** `agent_runtime/llm_runtime.py:1883-1886` + `:2095-2097`
- Streaming LLM loop stores tool result inline at 1886, then appends to `_tool_results_to_store` at 2042-2043 and stores again at 2095-2097. → Doubled entries in `conversation_state["last_tool_calls"]`.

### H6. Bare `except:` catches `KeyboardInterrupt` / `SystemExit`
- **File:** `AgenticSys.py:1670`
- `except:` without exception type catches `KeyboardInterrupt` (Ctrl+C) and `SystemExit`. → Process un-killable during dict sanitization.

### H7. Inline path validation bypasses centralized `_validate_path`
- **File:** `web/server.py:261-275` (`api_viewer_image`)
- Uses `startswith(upload_dir + os.sep)` instead of shared `_validate_path()`. → `BRACHYBOT_DATA_ROOTS` env var expansion silently ignored for this endpoint.

### H8. No 413 (Request Entity Too Large) JSON error handler
- **File:** `web/server.py:83`
- `MAX_CONTENT_LENGTH = 500MB` set but Flask's default 413 handler returns HTML. → Client sending >500MB gets HTML error instead of JSON.

### H9. `DOSE_SCALE = 120.0` defined 4 times in `planning_pipeline.py`
- **File:** `tool_factory/seed_plan/planning_pipeline.py:1249,1383,1431,1488`
- Same magic number defined inside 4 different method scopes. Plus `DOSE_MODEL_SCALE_GY = 120.0` in `web/server_support.py:70`. → If scale ever changes, 5 locations must be updated.

### H10. Missing `anthropic` and other dependencies in `requirements.txt`
- **File:** `requirements.txt`
- Missing: `anthropic` (code uses `ANTHROPIC_*` env vars), `flask-socketio/flask-sse`, `playwright`, `nibabel`, `pytest-asyncio`.

### H11. Stale worktrees with divergent code copies
- **File:** `.claude/worktrees/benchmark-optimization/`, `datamind-report/`, `ui-design-fixes/`
- Each contains full copies of brain/, tool_factory/, AgenticSys.py from before modularization. → Risk of stale imports/divergent fixes.

### H12. No tests for `agent_runtime/` or `web/routes/`
- New core modules and all API route handlers have zero test coverage.

---

## IMPORTANT (19)

### I1. `get_status()` checks wrong memory key `ct_data`
- **File:** `agent_runtime/chat_workflows.py:1930`
- `self.memory.retrieve("ct_data") is None` — actual key used everywhere is `ct_image`. → `get_status()` always returns `"ct_loaded": False`.

### I2. Dead `session_context` parameter in planning routes
- **File:** `web/routes/planning_routes.py:57`
- Parameter passed but never referenced in function body. → Confusing API.

### I3. 55+ production `console.log` calls in JS files
- **Files:** `dvh-planning.js` (~30), `3d-manual.js` (~25), `chat-core.js` (2), `chat-todo.js` (many), `viewer-layout.js` (several)
- Debug tracing active in production. Slight performance overhead.

### I4. `data_available` never populated in `conversation_state`
- **File:** `agent_runtime/core.py:131`
- Initialized as `[]` but nothing ever writes to it. Dead state.

### I5. `dose_calc` used instead of `dose_engine` in planning tool set
- **File:** `agent_runtime/core.py:1180-1183`
- `planning_tools` set uses `dose_calc` and `trajectory_init`/`trajectory_refine` (sub-step names, not tool names). → If `dose_engine` or `trajectory_planning` is the only planning tool called, `is_planning` check fails.

### I6. `print()` instead of `logger` in production code
- **File:** `AgenticSys.py:1737,1740,1743`
- Debug `print(f"[STORE] ...")` statements.

### I7. `_has_completed_planning_in_steps` only checks `planning_pipeline`
- **File:** `AgenticSys.py:739-746`
- LLM loops check broader set (`seed_planning`, `trajectory_planning`, `dose_engine`, `dose_evaluation`). → Safety-net report regeneration may produce duplicate report.

### I8. `organ_counts.get(n, 0)` with name key is always 0
- **File:** `agent_runtime/chat_workflows.py:829-833`
- `organ_counts` keyed by label ID (int), but sort key passes organ name (str). → Sort is always no-op.

### I9. `let`/`const` cross-script dependency (brittle load order)
- **Files:** `brachybot-chat-core.js:1864,1967` ↔ `brachybot-chat-todo.js:2-4,26`
- `_TODO_I18N` (const) and `_activeTodoLang` (let) declared in chat-core.js but accessed in chat-todo.js. Since `let`/`const` at top level don't create `window` properties, any script order change causes `ReferenceError`.

### I10. Double wrapping of `sendChat`
- **Files:** `report-shell.js:1005-1021` then `report-export.js:870-881`
- Both wrap `window.sendChat`. If either fails to call its saved original, entire chat pipeline breaks.

### I11. `_fetchHeader` misses `response.ok` check
- **File:** `brachybot-report-shell.js:289-295`
- `const j = await r.json()` without `r.ok` check. → Non-JSON error body causes cryptic parse error.

### I12. Meshes not disposed on panel switch
- **File:** 3D viewer — `switchPanel()` does not dispose Three.js geometries/materials. → Memory accumulates across planning runs.

### I13. `!important` overuse (~55 declarations)
- **Files:** `brachybot-panels-viewers.css`, `brachybot-report-controls.css`
- Heavy `!important` usage makes cascade hard to reason about.

### I14. Header vs report lang-button styling inconsistency
- **Files:** `brachybot-theme-layout.css:405-413` (CSS class) vs `brachybot-report-shell.js:138-143` (inline JS)
- Two different styling strategies for language toggle buttons.

### I15. `autoCaptureReportFigures` called from 3 entry points
- **File:** `brachybot-report-editor.js:397-1054` (657-line function)
- Called from `Report.autoFill.fromAll()`, `exportReportPDF()`, and `refreshPlanningUI()`. Risk of double-capture.

### I16. Report preview built as single giant `innerHTML` template
- **File:** `brachybot-report-export.js:391-607`
- 216-line template string with 50+ `escHtml()` calls. Any syntax error produces blank report with no console error.

### I17. Three parallel i18n systems coexist
- `data-i18n-*` attributes (chat-core.js), `_TODO_I18N` (chat-todo.js), `REPORT_STRINGS` (report-editor.js)
- Adding a new label requires touching three different dictionaries.

### I18. No pytest configuration
- No `pytest.ini`, `pyproject.toml`, `setup.cfg`, or `.coveragerc`. `pytest-asyncio` not listed. Async tests won't run.

### I19. SSE generator lacks resource timeout
- **File:** `web/routes/planning_routes.py:1611-1634`
- Generator has no hard timeout if `GeneratorExit` not raised. Could run indefinitely on production WSGI servers.

---

## MINOR (20)

### M1. Multiple unused imports in `agent_runtime/`
- `response_tools.py`: `base64`, `io`, `traceback`, `datetime`, `unquote`/`urlparse`, `SimpleITK as sitk`, `SYSTEM_PROMPT_TEMPLATE`/`get_prompt_modules`, `PlanningPhase`
- `chat_workflows.py`: `base64`, `io`, `datetime`, `unquote`/`urlparse`, `SYSTEM_PROMPT_TEMPLATE`/`get_prompt_modules`
- `llm_runtime.py`: Duplicate `import datetime` at lines 170 and 305

### M2. F-strings in logger calls (~30 occurrences across `agent_runtime/`)
- Always evaluated even when log level is disabled. Should use lazy `%s` formatting.

### M3. `/api/planning/seeds_3d` route in `viewer_routes.py:1044`
- Route naming inconsistent with file organization.

### M4. 261 inline `style=""` attributes in `index.html`
- Element-level styling not extracted to CSS files.

### M5. `.data-tree-*` styles in `report-controls.css:1-20`
- Belong in `brachybot-panels-viewers.css`.

### M6. No `{CT,MR,US}_DATA_ROOTS` env var documentation
- `_validate_path` supports these but they're not documented.

### M7. `_global_agent` singleton overwritten by multiple `BrachyAgent` instances
- Module-level singleton. Route modules handle with `getattr() or get_agent()` fallback. Documented pattern but fragile.

### M8. `_clean_response_text` — 27 stacked `re.sub` calls
- **File:** `llm_runtime.py:759-885`. O(n*m) cleanup. Maintenance hazard.

### M9. Auto-generated API key never used
- `server_support.py:56-59`. Key generated when env var unset but `_API_KEY_REQUIRED` stays `False`.

### M10. No `<noscript>` fallback in `index.html`
- Page renders blank if JS disabled.

### M11. No retry on LLM API failure
- `llm_runtime.py:351-355`. Transient network error ends session.

### M12. `AgentMemory.clear_conversation()` has dead code for `exp_memory`
- `core.py:496-498`. `exp_memory` is on `BrachyAgent`, not `AgentMemory`.

### M13. `agent_runtime/__init__.py` doesn't export mixin classes
- Only exports from `core.py`, not `ResponseToolMixin`, `LLMRuntimeMixin`, `ChatWorkflowMixin`.

### M14. `DOSE_SCALE` stored in agent memory but never invalidated
- `planning_pipeline.py:1271`. If dose model changes, stale scale persists.

### M15. `_MESH_CACHE` key uses `id(mask_data)` (memory address)
- `viewer_routes.py:861`. Risk of stale cache if old mask GC'd and new mask shares same address.

### M16. Semicolons inconsistent across all JS files
- Mixed usage with no ASI hazards found, but harms readability.

### M17. Three functions >400 lines each
- `sendChat` (chat-todo.js:748, ~604 lines), `autoCaptureReportFigures` (report-editor.js:397, ~657 lines), `refreshPlanningUI` (dvh-planning.js:774, ~438 lines).

### M18. `test_*.py` in `.gitignore` is overly broad
- `.gitignore:82`. Prevents tracking any root-level tests.

### M19. `cross_reference_index.md` path may be relative from wrong directory
- `clinical_kb/guidelines/10_cross_reference_index.md:5`. Reference to `sources/01_gynecologic/...` without `clinical_kb/` prefix.

### M20. Worktree duplicate tests
- `.claude/worktrees/*/tests/test_brain_system.py` — if divergent, could mask regressions.

---

## Route Count Verification

| Source | Count |
|--------|-------|
| Old monolithic `web/server.py` (418381c) | 56 |
| `web/server.py` (0084554) | 6 |
| `web/routes/planning_routes.py` | 38 |
| `web/routes/viewer_routes.py` | 12 |
| **Total new** | **56** ✅ |

## Static Resource Verification

| Check | Result |
|-------|--------|
| CSS `<link>` refs in index.html | 5 (all exist) |
| JS `<script>` refs in index.html | 21 (all exist) |
| brachybot-*.js refs in index.html | 11 (all exist) |
| brachybot-*.css refs in index.html | 4 (all exist) |
| Vendor JS libs | 10 (all exist) |
| **Missing refs** | **0** ✅ |

## Verification Status

| Check | Result |
|-------|--------|
| py_compile (all .py files) | 206/206 ✅ |
| node --check (frontend JS) | All pass ✅ |
| `from web.server_support import *` residual | 0 ✅ |
| Flask route registration smoke | 56/56 ✅ |
| Static resource reference check | 26 refs, 0 missing ✅ |
| Unittest discover + run | 13 tests, 9 pass, 4 skip (missing SimpleITK) ✅ |

---

*Report generated 2026-07-06. Full details including code snippets available on request.*
