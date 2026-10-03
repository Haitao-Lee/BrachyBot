# Frontend UI Absolute Path Relativization Design

Date: 2026-09-23
Scope: Implement in the internal-test tree `BrachyBot`; after verification, sync to the public-test `BrachyBot-release` and restart the public-test server
Status: Approved, pending implementation

## 1. Background

The public-test UI (browser) directly displays server absolute paths. The most typical case is the tool arguments in the chat execution trace (thinking chain):

```
粒子植入规划
planning_pipeline
step: "full", ct_image_path: "/home/lht/snap/brachyplan/BrachyBot/.runtime/workspaces/024f977e.../inputs/CTzhouqun_20260912_130651.nii", mode: "rl", seed_info: {...}, planning_params: {...}, ref_direc: [0,1,0]
```

Similar leakage also appears in:

- The `result` / `content` / `data` of tool results and the human-readable `message` (e.g. `filesystem_browser`'s "listed N items, path: …", `report_generator`'s "Exported to …").
- The system/bot bubble text in the chat (e.g. "…DICOM-RT exported to: /home/…", "Report generated: /home/…").
- Error/notification messages (e.g. `Path does not exist: /home/…`).
- The visible values of the input boxes (`#ctPath` / `#ctvPath` / `#oarPath`), populated by `/api/upload`, `/api/agent/status`, and the workspace snapshot.

The existing pipeline has no path masking at all for tool arguments/results: `ToolResultPipeline.trace_params` (`agent_runtime/core.py`) returns `params` as-is for non-`ui_*` tools, which are directly rendered via the SSE `step` event → `ChatTask.publish` → browser `step.params`. The final assistant reply has a separate `redact_internal_paths` (`utils/user_errors.py`), but it only applies to the "final reply text" and truncates paths to the basename, which is inconsistent with this goal.

## 2. Goals and Non-Goals

### Goals
- **All** absolute paths visible to the user in the browser are presented in relative/token form.
- Display form: workspace-root-relative with a `<workspace>/` prefix, e.g. `<workspace>/inputs/CTzhouqun_20260912_130651.nii`.
- Absolute paths that are not "case workspace / `.runtime` / repository root" are displayed uniformly as `<path>/<basename>`.
- The token form can be **reversibly round-tripped**: after the input box displays the relative form, submitting that value to the backend parses and restores it normally, with no functional impact.
- Traces remain in relative form after reconnection replay and persistence.

### Non-Goals
- Do not modify any planning/dose/guide-template/segmentation algorithm itself.
- Do not change the conversation/tool context sent to the LLM (the model still receives the real absolute paths so it can continue calling tools).
- Do not refactor unrelated modules; do not touch error handling beyond the existing `redact_internal_paths`.

## 3. Path Token Scheme

Add `utils/display_paths.py`, defining an ordered mapping with **longest-prefix first**:

| Prefix | Token |
|---|---|
| Case workspace root `workspace_root` (`<runtime>/workspaces/<user>/<session>`) | `<workspace>` |
| `.runtime` directory | `<runtime>` |
| Repository root | `<app>` |
| Any other absolute path | `<path>/<basename>` |

Core API:

- `relativize_text(text, roots) -> str`: replaces all matching absolute paths within a string with token form; unknown absolute paths use `<path>/<basename>`. Supports paths appearing inside longer text (error messages).
- `relativize_value(value, roots) -> Any`: recursively applies `relativize_text` to `str`/`dict`/`list`/`tuple`; other types are returned as-is.
- `resolve_user_path(value, roots) -> str`: reverse restoration. `<workspace>/rel` → `workspace_root/rel`; `<runtime>/…`, `<app>/…` likewise. A lone `<workspace>` → the workspace root. `<path>/name` is restored by unique basename match within the workspace, runtime, and repository; if there is no match it is returned as-is (leaving a clear error to the existing ownership validation). Strings without tokens are returned as-is.

`roots` is a lightweight structure (dataclass or named tuple) with fields `workspace_root` / `runtime_dir` / `app_root`, any of which may be `None` (a missing token does not participate in replacement/parsing). The workspace root is resolved from `task.agent.config["_workspace_root"]` or the request context; the runtime root is the ancestor named `.runtime` found by walking up from the workspace root; the repository root is the parent directory of the runtime root.

## 4. Outbound (Server → Browser)

There are only 3 choke points, avoiding per-site changes:

1. **SSE full events**: `ChatTask.publish()` in `web/chat_tasks.py`.
   - Apply `relativize_value` to the parsed `data` for `step` / `error` / `response` events, then re-serialize with `encode_event` before writing to the journal.
   - Currently the raw `raw` text is written directly; change it to write the relativized text so that `self.steps` and `_events` (replay) are consistent.
   - Covers: tool arguments/results/content/data, `planning_pipeline` sub-steps, `error`, and the streaming final reply text.
   - Compute `roots` from `task.agent.config` (consistent with the existing `_workspace_root` usage in `agent_runtime/llm_runtime.py`).

2. **All non-streaming JSON responses**: add `@app.after_request` in `web/server.py`.
   - Only process `/api/*` responses whose `Content-Type` is `application/json`; skip `text/event-stream` and binary responses. Handle success and error responses uniformly.
   - Recursively relativize the response JSON. Covers `/api/upload`, `/api/agent/status`, workspace snapshots, export responses, notification fields, etc., i.e. the data sources for the input boxes and JS bubbles.
   - Resolve `roots` from the request context (`g.brachybot_workspace` or `session_id` + current user → `workspace_root`); when missing, provide at least `<runtime>` / `<app>`.

3. **Final reply sanitization pipeline**: change `sanitize_user_response` / `redact_internal_paths` in `utils/user_errors.py` to **relativize first, then fall back**.
   - When roots are passed in, call `relativize_text` first so the final answer displays `<workspace>/...`; `redact_internal_paths` degrades to a fallback (normally there is no `/home/` left to match).
   - Call sites: `agent_runtime/response_tools.py`, `agent_runtime/chat_workflows.py`.

## 5. Inbound (Browser → Server)

At the path fields listed above, use `resolve_user_path` to restore the absolute path, then go through the existing `owns_path` / ownership validation. Field set (exhaustively enumerated):

- JSON body: `ct_path`, `ctv_path`, `oar_path`, `image_path`, `ct_image_path`, `label_path`, `source_path`, `path`, `created_array_paths` (list).
- Query: `request.args.get("path")` in `server.py`.
- Files involved: `web/server.py`, `web/routes/planning_routes.py`, `web/routes/viewer_routes.py`, `web/export_service.py`, `web/workspace_store.py`.

`<path>/<basename>` cannot guarantee unique restoration and is mainly used for "display-only" strings; the actual values of functional fields all fall within the workspace/runtime/repository, where the `<workspace>/…` form can be restored precisely.

## 6. Frontend

Do not change any JS. Traces/bubbles/input boxes directly render the token strings returned by the server; the server is responsible for parsing on round-trip. The existing frontend `sanitizeChatErrorContent` (which detects `/home/`) no longer triggers (there is no `/home/` left), with no loss of information.

## 7. Persistence and LLM Context

- After `ChatTask.publish` relativizes, the content written to the journal and `task.steps` is in relative form, so reconnection replay and the persisted execution trace (`execution_trace` in `workspace_store`) are automatically in relative form.
- This trace is used only for browser display and is not fed back to the LLM; the tool context the model needs (`agent.memory` messages/tool results) does not pass through `publish` and keeps the real absolute paths.

## 8. Tests

- Add `tests/test_display_paths.py`:
  - Token mapping and longest-prefix-first (workspace before runtime before repo).
  - Nested dict/list values, occurrences embedded in strings.
  - `relativize` ↔ `resolve` round-trip consistency.
  - Unknown absolute path → `<path>/<basename>`; `<path>/name` restored by unique match / returned as-is when there is no match.
  - Behavior with default roots.
- Add/extend an integration-style contract test: construct a `step` event with an absolute path, verify it is in token form after `ChatTask.publish`, and that `resolve_user_path` can restore it.
- Update existing tests that assert "output paths are absolute".

## 9. Risks and Mitigations

- `after_request` only takes effect for JSON; SSE/binary must be explicitly skipped; SSE is covered by `publish`.
- Absolute paths in old browser localStorage / old snapshots only become relative after one refresh; the server also relativizes when reading old snapshots outbound.
- `<path>/<basename>` cannot be precisely round-tripped; it serves only as a display fallback, and functional fields do not depend on it.
- Performance: response bodies are small, and recursive traversal overhead is negligible.

## 10. Rollout Order

1. Implement `utils/display_paths.py` + the three outbound points + inbound parsing + tests in the internal-test `BrachyBot`.
2. Internal-test `py_compile` + full test suite passes.
3. Sync to the public-test `BrachyBot-release` (whole-file LF overwrite + `diff -w` verification).
4. Run the public-test full suite, restart the public-test server, and verify (single instance / `/api/status` 401 / prewarm).
