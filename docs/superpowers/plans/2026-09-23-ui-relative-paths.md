# 前端 UI 绝对路径相对化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让浏览器 UI 中所有用户可见的绝对路径以 `<workspace>/…`、`<runtime>/…`、`<app>/…`、`<path>/文件名` 令牌形式呈现，且令牌值可回传被后端解析。

**Architecture:** 新增 `utils/display_paths.py` 提供可逆的路径令牌映射与递归值转换。出站只在 3 个咽喉点接入（SSE `ChatTask.publish`、Flask `after_request` JSON、最终回复清洗管道）；入站在少量已知路径字段用 `resolve_user_path` 还原。前端不改。

**Tech Stack:** Python 3.12, Flask 3.1, pytest, 原生 JS（不改）。

**Spec:** `docs/superpowers/specs/2026-09-23-ui-relative-paths-design.md`

> 注：本仓库禁止 commit/push；计划中的"提交"步骤一律以"暂存校验"替代，最终由人工/同步流程处理。

---

### Task 1: 路径令牌核心模块 + 单元测试

**Files:**
- Create: `utils/display_paths.py`
- Test: `tests/test_display_paths.py`

覆盖 spec §3：`DisplayRoots`、`relativize_text`、`relativize_value`、`resolve_user_path`、最长前缀优先、`<path>/basename` 兜底、往返一致、缺省 roots。

### Task 2: 出站 SSE —— `ChatTask.publish`

**Files:**
- Modify: `web/chat_tasks.py`（`ChatTask.publish` / 新增 `_display_roots`）
- Test: `tests/test_display_paths.py`（新增 Task 集成用例）

对 `step`/`error`/`response` 事件的数据 `relativize_value` 后 `encode_event` 重写 journal 文本，使 `self.steps` 与回放一致。

### Task 3: 出站 JSON —— `web/server.py` `after_request`

**Files:**
- Modify: `web/server.py`（新增 `_request_display_roots` 与 `@app.after_request`）
- Test: `tests/test_display_paths.py`

对 `/api/*` 且 `application/json` 的响应递归相对化；`text/event-stream` 与二进制跳过。

### Task 4: 出站最终回复清洗

**Files:**
- Modify: `utils/user_errors.py`（`relativize_internal_paths`/`sanitize_user_response` 增加可选 `roots`）
- Modify: `agent_runtime/response_tools.py:1583`、`agent_runtime/chat_workflows.py:769,4371,4386` 传入 roots
- Test: `tests/test_user_error_sanitization.py`（或既有对应测试）

先相对化再兜底，最终回答显示 `<workspace>/…` 而非 basename。

### Task 5: 入站解析

**Files:**
- Modify: `web/server.py`（`?path=` 与 `ct_path`）
- Modify: `web/routes/planning_routes.py`（`ct_path/ctv_path/oar_path/image_path/ct_image_path/label_path`）
- Modify: `web/routes/viewer_routes.py`（`ct_path`）
- Modify: `web/export_service.py` / `web/workspace_store.py`（`source_path`/`created_array_paths`）
- Test: `tests/test_display_paths.py`

在既有 `owns_path` 校验前还原令牌。

### Task 6: 验证与同步

- 内测 `py_compile` + 定向测试 + 全量测试
- 同步公测（整文件 LF + `diff -w`）
- 公测全量测试 + 重启 server + 核验
