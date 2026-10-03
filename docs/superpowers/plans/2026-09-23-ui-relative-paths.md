# UI Absolute-Path Relativization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all user-visible absolute paths in the browser UI render as `<workspace>/…`, `<runtime>/…`, `<app>/…`, or `<path>/filename` tokens, and make token values round-trip back to be resolved by the backend.

**Architecture:** Add `utils/display_paths.py` providing a reversible path-token mapping and recursive value transformation. Outbound, wire in at only 3 chokepoints (SSE `ChatTask.publish`, Flask `after_request` JSON, final-reply sanitization pipeline); inbound, use `resolve_user_path` to restore a small number of known path fields. No frontend changes.

**Tech Stack:** Python 3.12, Flask 3.1, pytest, vanilla JS (unchanged).

**Spec:** `docs/superpowers/specs/2026-09-23-ui-relative-paths-design.md`

> Note: This repository forbids commit/push; the "commit" steps in the plan are all replaced with "stage and verify", and are ultimately handled by a manual/sync process.

---

### Task 1: Path-token core module + unit tests

**Files:**
- Create: `utils/display_paths.py`
- Test: `tests/test_display_paths.py`

Covers spec §3: `DisplayRoots`, `relativize_text`, `relativize_value`, `resolve_user_path`, longest-prefix-first, `<path>/basename` fallback, round-trip consistency, default roots.

### Task 2: Outbound SSE — `ChatTask.publish`

**Files:**
- Modify: `web/chat_tasks.py` (`ChatTask.publish` / new `_display_roots`)
- Test: `tests/test_display_paths.py` (add Task integration cases)

After `relativize_value` on the data of `step`/`error`/`response` events, `encode_event` rewrites the journal text so that `self.steps` matches replay.

### Task 3: Outbound JSON — `web/server.py` `after_request`

**Files:**
- Modify: `web/server.py` (add `_request_display_roots` and `@app.after_request`)
- Test: `tests/test_display_paths.py`

Recursively relativize responses for `/api/*` with `application/json`; skip `text/event-stream` and binary.

### Task 4: Outbound final-reply sanitization

**Files:**
- Modify: `utils/user_errors.py` (`relativize_internal_paths`/`sanitize_user_response` gain an optional `roots`)
- Modify: pass roots at `agent_runtime/response_tools.py:1583`, `agent_runtime/chat_workflows.py:769,4371,4386`
- Test: `tests/test_user_error_sanitization.py` (or the existing corresponding test)

Relativize first, then fall back, so the final answer displays `<workspace>/…` rather than a basename.

### Task 5: Inbound resolution

**Files:**
- Modify: `web/server.py` (`?path=` and `ct_path`)
- Modify: `web/routes/planning_routes.py` (`ct_path/ctv_path/oar_path/image_path/ct_image_path/label_path`)
- Modify: `web/routes/viewer_routes.py` (`ct_path`)
- Modify: `web/export_service.py` / `web/workspace_store.py` (`source_path`/`created_array_paths`)
- Test: `tests/test_display_paths.py`

Restore tokens before the existing `owns_path` validation.

### Task 6: Verification and sync

- Internal testing: `py_compile` + targeted tests + full test suite
- Sync to public testing (whole-file LF + `diff -w`)
- Public-testing full suite + restart server + verification
