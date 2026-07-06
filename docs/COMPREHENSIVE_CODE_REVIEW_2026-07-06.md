# Comprehensive Code Review — 2026-07-06 (v4 Deep-Dive)

**Review scope:** Commit `418381c` → `0084554` (modularization)
**Files reviewed:** 20 files, ~40,000 lines of Python + 20,000+ lines of frontend JS/CSS/HTML
**Method:** Four independent line-by-line deep-dive agents + human verification
**Status:** 18 CRITICAL, 22 HIGH, 25 IMPORTANT, 30 MINOR issues found

---

## CRITICAL (18)

### C1. Missing `AgentMemory` import — `NameError` at runtime
- **File:** `agent_runtime/llm_runtime.py:3` (import), `:49`, `:1014`, `:1315` (usage)
- `from agent_runtime.core import PlanningPhase, ToolResultPipeline` omits `AgentMemory`. Lines 49/1014/1315 call `AgentMemory.is_ct_loaded()`. → `NameError`.

### C2. `DOSE_MODEL_SCALE_GY` not imported in `web/server.py`
- **File:** `web/server.py:507`
- `_build_report_interpretation()` uses bare name `DOSE_MODEL_SCALE_GY`. Defined in `server_support.py:70` but not imported. → `NameError` on `/api/report/auto-fill`.

### C3. Streaming forced-search post-processing inside `else` block
- **File:** `agent_runtime/llm_runtime.py:1241-1253`
- Step recording and message injection indented inside `else:` — executes only on FAILURE. Non-stream (line 290-298) correctly outside if/else.

### C4. Missing path validation — file traversal in 2 routes
- **File:** `web/routes/planning_routes.py:304-309`, `:422-426`
- `api_segmentation` and `api_planning_run_step` accept `image_path`/`ct_image_path` from JSON body, pass directly to segmentation/planning tools without `_validate_path()`. → Arbitrary file read.

### C5. `_rate_limit_store` lock-free — data corruption under concurrency
- **File:** `web/server_support.py:64`, `796-818`
- `_check_rate_limit()` reads/writes `Dict[str, list]` without lock. Multiple threads simultaneously filter/reassign. `_rate_limit_cleanup_counter` (line 793) also bare global.

### C6. `str.format()` crash with untrusted `enhanced_context`
- **File:** `agent_runtime/llm_runtime.py:171,306,1131,1259`
- `SYSTEM_PROMPT_TEMPLATE.format(enhanced_context=enhanced_context, ...)` — `enhanced_context` is assembled from reflexion warnings, crystallized skill names, user messages. If any contain `{` or `}`, `str.format()` raises `KeyError`/`ValueError`.
- **Fix:** Escape braces before `.format()` or switch to `string.Template`.

### C7. Triple-dispatch tool result storage — data corruption risk
- **File:** `agent_runtime/llm_runtime.py:1749-1750,1883-1889,2042-2043,2095-2097`
- `_store_tool_result` called 3× per successful tool: inline at 1886, then batch at 2097 **twice** (appended to `_tool_results_to_store` at 1750 AND 2043). Doubles `conversation_state["last_tool_calls"]`.

### C8. `result.message` hijacked by unrelated auto-planning block
- **File:** `AgenticSys.py:1453`
- After CTV segmentation succeeds, `result.message` is mutated to say "planning pipeline auto-completed" — semantically incorrect; `result` is the CTV result, not planning.

### C9. `AgentMemory.clear_all_data` calls nonexistent method
- **File:** `agent_runtime/core.py:532`
- `self._init_enhanced_integration()` — this method is on `BrachyAgent`, not `AgentMemory`. Crashes if called on bare `AgentMemory` instance (e.g., in tests).

### C10. Duplicate `ReportGeneratorTool` registration
- **File:** `AgenticSys.py:572-575` and `:691-695`
- Same tool imported from two different paths and registered twice. Second overwrites first silently.

### C11. `loadDefaultParams` — `const setVal` redeclared in same block scope
- **File:** `web/app/static/js/brachybot-ui-api.js:1089,1103`
- `const setVal = (id, val) => { ... };` declared at lines 1089 and 1103 in the same function, NOT in separate `if` blocks. → `SyntaxError: Identifier 'setVal' has already been declared` at runtime in non-strict mode.

### C12. `{current_date}` template variable never replaced
- **File:** `config/prompts/system_prompt.md:2`, `__init__.py`
- `_load_prompt()` reads file content and returns as-is. No `.replace("{current_date}", ...)` or `str.format()` call. LLM receives literal `{current_date}` string.

### C13. `_isFullPlan` operator precedence bug
- **File:** `web/app/static/js/brachybot-chat-todo.js:580-582`
- `const isFullPlan = /规划|execute|.../i.test(text) && /放射性|粒子|.../i.test(text) || /规划/.test(text) || /planning/i.test(text) || /规划/.test(text);`
- `&&` has higher precedence than `||`. Any text containing "规划" triggers full plan, even if the user is asking a knowledge question.

### C14. `_isAdviceRequest` overly broad regex
- **File:** `web/app/static/js/brachybot-chat-todo.js:697-700`
- `"review"` matches ANY message containing "review" (e.g., "Let me review the document"), routed to `requestPlanningAdvice()` instead of normal chat.

### C15. `api_export/stl` saves `.npy` files, not STL
- **File:** `web/routes/planning_routes.py:1564-1565`
- `np.save(...seed_...pos.npy)` — endpoint name says "stl" but implementation saves NumPy `.npy` files.

### C16. `.step-num` class undefined in CSS — used 7 times in HTML
- **File:** HTML uses `<span class="step-num">0</span>` × 7. No `.step-num` rule exists in any of the 4 CSS files.

### C17. Orphan CSS declaration after prematurely closed block
- **File:** `web/app/static/css/brachybot-chat-status.css:1027-1032`
- `font-feature-settings: "tnum" 1; } color: var(--primary); ... }` — the `}` at end of line 1028 closes `.usage-value`. Properties after it are orphaned, never applied.

### C18. `.metric-card.warn` duplicate `border` — warn border overridden
- **File:** `web/app/static/css/brachybot-panels-viewers.css:499-500`
- `border: 1px solid rgba(245, 158, 11, 0.5); border: 1px solid transparent;` — second declaration makes warn border transparent.

---

## HIGH (22)

### H1. `_record_experience` crashes when `_init_self_evolution` fails
- **File:** `AgenticSys.py:420-432` → `chat_workflows.py:1469`
- `except` block does not set `self.exp_memory = None`. → `AttributeError`.

### H2. Invalid CSS `font-family` syntax
- **File:** `brachybot-theme-layout.css:396`. `'Inter, sans-serif'` — whole value quoted.

### H3. Missing `_cancelled()` check at streaming loop top
- **File:** `llm_runtime.py:1286`. Non-stream checks at line 338; stream doesn't.

### H4. Inconsistent CT-loaded gate: stream vs non-stream
- **File:** `llm_runtime.py:438` vs `:1314-1316`. Non-stream checks BOTH UI state AND memory; stream checks UI state only.

### H5. Bare `except:` catches `KeyboardInterrupt` / `SystemExit`
- **File:** `AgenticSys.py:1670`. `except:` without type.

### H6. Inline path validation bypasses centralized `_validate_path`
- **File:** `web/server.py:261-275`. Uses `startswith()` instead of shared validator.

### H7. No 413 JSON error handler
- **File:** `web/server.py:83`. Flask's default returns HTML.

### H8. `DOSE_SCALE = 120.0` defined 5× across codebase
- **File:** `planning_pipeline.py:1249,1383,1431,1488` (4×) + `server_support.py:70`.
- WET duplication. Scale change requires 5 edits.

### H9. Missing `anthropic` in `requirements.txt`
- Code references `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` but SDK not listed.

### H10. Stale worktrees with divergent code
- `.claude/worktrees/benchmark-optimization/`, `datamind-report/`, `ui-design-fixes/`.
- Full pre-modularization code copies.

### H11. `_parse_tool_calls` fragile single-quote substitution
- **File:** `chat_workflows.py:73`
- `raw.replace("'", '"')` — corrupts strings containing apostrophes (e.g., "user's input").

### H12. `_clean_response_text` — dead condition and redundant patterns
- **File:** `llm_runtime.py:803-804`
- `('tool_use' in stripped or 'tool_use' in stripped)` — right side identical to left.
- Lines 812, 830, 835: same `\`\`\`tool_call` pattern matched 3× with increasing greediness.

### H13. Duplicate DICOM export endpoints
- **File:** `planning_routes.py:1479` (`/api/export/dicom_rt`) and `:1742` (`/api/export/dicom`)
- Nearly identical logic, different defaults.

### H14. `int16` overflow risk in CT data
- **File:** `viewer_routes.py:280`
- `ct_data.astype(np.int16)` — HU values >32767 silently truncated.

### H15. `list.pop(0)` O(n) cache eviction
- **File:** `viewer_routes.py:964`
- `_MESH_CACHE_ORDER.pop(0)` shifts ~48 elements on average. Use `collections.deque`.

### H16. Import inside loop — 100× import per request
- **File:** `viewer_routes.py:610-616`
- `from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING` inside `for label in unique_labels:`.

### H17. `renderDoseOverlay` vs `renderDoseOverlayOnLayer` — dual implementations
- **File:** `brachybot-3d-manual.js:2046` and `:1997`
- Two versions of same logic differing by canvas parameter style. One may become stale.

### H18. `renderDoseContourOnCanvas` — `contour.level.toFixed(1)` without null check
- **File:** `brachybot-3d-manual.js:2293`
- `contour.level` could be undefined → `TypeError`.

### H19. Dual language globals `_uiLanguage` vs `_i18nLang`
- **File:** `chat-core.js:900,1165`
- `window._uiLanguage` (server-detected) vs `window._i18nLang` (UI toggle). Functions check one or the other inconsistently. → Some UI parts show Chinese while others show English.

### H20. `_MESH_CACHE` key uses `id(mask_data)` — memory address reuse
- **File:** `viewer_routes.py:861`
- Python `id()` returns memory address. If old object GC'd and new object allocated at same address, stale mesh returned.

### H21. `_build_report_interpretation` — 500 error handler doesn't log exception
- **File:** `web/server.py:855-857`
- `@app.errorhandler(500)` returns JSON but never logs `e`. Debugging impossible.

### H22. `API_KEY=None` crash when `BRACHYBOT_REQUIRE_API_KEY=1`
- **File:** `server_support.py:56-59`, `:947-956`
- `_API_KEY_REQUIRED = True` but `API_KEY = None`. `_screenshot_signature()` calls `None.encode()` → `AttributeError`.

---

## IMPORTANT (25)

### I1. `get_status()` checks wrong memory key `ct_data`
- **File:** `chat_workflows.py:1930`. Should be `ct_image`.

### I2. Dead `session_context` parameter
- **File:** `planning_routes.py:57`. Passed but never referenced.

### I3. 55+ production `console.log` calls
- Across 5 JS files. Debug tracing active in production.

### I4. `data_available` never populated in `conversation_state`
- **File:** `core.py:131`. Initialized as `[]`, never written.

### I5. `dose_calc` used instead of `dose_engine` in planning tool set
- **File:** `core.py:1180-1183`. Sub-step names, not tool names.

### I6. `print()` instead of `logger` in production
- **File:** `AgenticSys.py:1737,1740,1743`.

### I7. `_has_completed_planning_in_steps` too narrow
- **File:** `AgenticSys.py:739-746`. Only checks `planning_pipeline`, not individual tools.

### I8. `organ_counts.get(n, 0)` with name key always 0
- **File:** `chat_workflows.py:829-833`. `organ_counts` keyed by label ID, sort key passes name.

### I9. `_chatHistory` array grows unbounded
- **File:** `chat-todo.js:624`. No cap on array over long sessions.

### I10. `dataTreeState.planning.seeds.forEach` without null guard
- **File:** `viewer-volume.js:2002-2004`. Throws if seeds/needles/doseLevels is null.

### I11. `batchSetOpacity` / `setDataOpacity` referenced from inline onclick but may not be defined
- **File:** `viewer-volume.js:2130`, `:1666`. Slider/context menu may not work.

### I12. Auto-OAR logic triplicated across 3 files
- `AgenticSys.py:1200-1328`, `llm_runtime.py:1929-2038`, `chat_workflows.py:979-1206`. ~130 lines copy-pasted 3×.

### I13. 80% duplication between streaming and non-streaming LLM loops
- `llm_runtime.py:31-696` vs `:948-2237`. ~1300 lines duplicated.

### I14. `_convert_anthropic_to_openai_messages` dead code
- **File:** `AgenticSys.py:1681-1732`. Zero callers.

### I15. Multiple `_global_agent` resolution pattern copy-pasted 8+ times in route files
- Extract into `_resolve_agent()` helper.

### I16. `builtins` monkey-patch pollutes global namespace
- **File:** `server.py:957-959`. `import builtins; builtins.track_operation = ...`

### I17. Hardcoded upload path duplicates `UPLOAD_DIR` constant
- **File:** `server.py:272-273`. Manual `os.path.realpath(...)` instead of shared constant.

### I18. `_captureScreenshot` — `.then()` inside `async` function — lost promise
- **File:** `ui-api.js:2075`. Should use `await`.

### I19. `_interceptScreenshot` — race condition with 500ms setTimeout + no abort
- **File:** `ui-api.js:2331`. Two rapid calls race; no `AbortController`.

### I20. `reconstructOrgan3D` — hardcoded label IDs `[1,2,3,4,5,6]`
- **File:** `viewer-layout.js:680`. Ignores labels >6.

### I21. `_applyDoseTextureToMesh` — sequential HTTP requests per vertex
- **File:** `viewer-layout.js:1008`. `await` inside loop of 12,500+ vertices = minutes of sequential fetches.

### I22. Orphan `RLock` created via `getattr(agent.memory, "_lock", threading.RLock())`
- **File:** `planning_routes.py:1450`. Fallback creates a new lock that no other code knows about — no real synchronization.

### I23. `renderOverlayFromVolume` threshold viewport mismatch
- **File:** `viewer_routes.py:219`. Overlay mask computed on raw HU, rendered on windowed image.

### I24. No tests for `agent_runtime/` or `web/routes/`
- Zero test coverage for all new core modules and all API route handlers.

### I25. `{current_date}` never replaced in system prompt
- (Same as C12 — LLM sees literal `{current_date}`)

---

## MINOR (30)

### M1. Unused imports across `agent_runtime/`
- `response_tools.py`: `base64`, `io`, `traceback`, `datetime`, `unquote`/`urlparse`, `SimpleITK as sitk`, `SYSTEM_PROMPT_TEMPLATE`/`get_prompt_modules`, `PlanningPhase`
- `chat_workflows.py`: `base64`, `io`, `datetime`, `unquote`/`urlparse`, `SYSTEM_PROMPT_TEMPLATE`/`get_prompt_modules`

### M2. F-strings in logger calls (~30 occurrences)
- Always evaluated even when log level is disabled.

### M3. `/api/planning/seeds_3d` route in `viewer_routes.py:1044`
- Route naming inconsistent with file organization.

### M4. 261 inline `style=""` attributes in `index.html`

### M5. `.data-tree-*` styles in `report-controls.css:1-20`
- Belong in `panels-viewers.css`.

### M6. No `{CT,MR,US}_DATA_ROOTS` env var documentation

### M7. `_global_agent` singleton overwritten by multiple instances
- Module-level singleton. Documented but fragile.

### M8. `_clean_response_text` — 27 stacked `re.sub` calls
- `llm_runtime.py:759-885`. Maintenance hazard.

### M9. Auto-generated API key never used
- `server_support.py:56-59`. Generated but `_API_KEY_REQUIRED` stays `False`.

### M10. `find "%s"` — `_parse_tool_calls` may parse JSON wrongly for `'`
- `chat_workflows.py:73`. Same as H11.

### M11. No retry on LLM API failure
- `llm_runtime.py:351-355`. Transient error ends session.

### M12. `AgentMemory.clear_conversation()` has dead code for `exp_memory`
- `core.py:496-498`. Property on `BrachyAgent`, not `AgentMemory`.

### M13. `agent_runtime/__init__.py` doesn't export mixin classes

### M14. `_todoI18n` referenced in `chat-core.js:1814` before definition in `chat-todo.js`
- Works due to script load order but fragile.

### M15. `_TODO_LABELS` and `GENERIC_TEMPLATES` dead code in `chat-todo.js`
- Lines 29-37, 567-574. Defined but never used.

### M16. `escHtml` without `use strict` — 10/11 JS files in sloppy mode

### M17. Infinite `requestAnimationFrame` render loop
- `3d-manual.js:463-498`. Never stops.

### M18. Hardcoded welcome message bypasses i18n toggle
- `chat-core.js:149,257`. "Welcome to BrachyBot..." stays English.

### M19. Three parallel i18n systems coexist
- `data-i18n-*`, `_TODO_I18N`, `REPORT_STRINGS`. Adding a label requires 3 changes.

### M20. No pytest configuration — `pytest-asyncio` not listed

### M21. `websocket_clients` dead variable
- `server.py:89-95`. Defined, never used.

### M22. `first_url` dead variable
- `llm_runtime.py:269,1224`. Assigned, never read.

### M23. `normalize_dose_image` called with output range = window range
- `server_support.py:600-606`. Clamp, not normalize. Misleading name.

### M24. `main` branch only has worktree copies of tests
- `.claude/worktrees/` each has own `test_brain_system.py` — may diverge.

### M25. SHA256 of API key used instead of `hmac.compare_digest`
- `server_support.py:947-949`. Leaks key hash format.

### M26. `_safe()` helper defined inside `api_upload` — redefined per request
- `server.py:187-190`.

### M27. `duplicate key 'toolMeasure'` in viewer-layout.js tooltips
- `viewer-layout.js:38-39`. Second overwrites first.

### M28. `resampleRatio = 0` division risk in `_displayYToVolumeZ`
- Guarded by `Math.max(spacingZ / spacingY, 0.01)` — safe currently.

### M29. `sources.badgeHtml` — double-quote injection in onclick
- `report-shell.js:171`. XSS vector via `reportForm` field key.

### M30. `consistencyCheck.compare` — duplicate key `name` in obj literal
- `chat-todo.js:1107-1109`. Duplicate key `name` (2nd overwrites 1st).

---

## Route Count Verification

| Source | Count |
|--------|-------|
| `web/server.py` | 6 |
| `web/routes/planning_routes.py` | 38 |
| `web/routes/viewer_routes.py` | 12 |
| **Total** | **56** ✅ (matches monolith) |

## Static Resource Verification

| Check | Result |
|-------|--------|
| CSS `<link>` refs in index.html | 5 (all exist) |
| JS `<script>` refs in index.html | 21 (all exist) |
| brachybot-*.js refs | 11 (all exist) |
| brachybot-*.css refs | 4 (all exist) |
| **Missing refs** | **0** ✅ |

## Verification Status

| Check | Result |
|-------|--------|
| py_compile (all .py files) | 206/206 ✅ |
| node --check (frontend JS) | All pass ✅ |
| `from web.server_support import *` residual | 0 ✅ |
| Route registration smoke | 56/56 ✅ |
| Static resource refs | 26 refs, 0 missing ✅ |
| Unittest discover | 13 tests, 9 pass, 4 skip (missing SimpleITK) ✅ |

---

*Report generated 2026-07-06. 18 CRITICAL, 22 HIGH, 25 IMPORTANT, 30 MINOR — 95 total issues.*
