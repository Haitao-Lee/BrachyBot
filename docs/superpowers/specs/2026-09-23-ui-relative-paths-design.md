# 前端 UI 绝对路径相对化设计

日期：2026-09-23
范围：内测树 `BrachyBot` 实现，验证后同步公测 `BrachyBot-release` 并重启公测 server
状态：已批准，待实现

## 1. 背景

公测 UI（浏览器）会直接展示服务器绝对路径。最典型的是聊天执行轨迹（思考链）里的工具入参：

```
粒子植入规划
planning_pipeline
step: "full", ct_image_path: "/home/lht/snap/brachyplan/BrachyBot/.runtime/workspaces/024f977e.../inputs/CTzhouqun_20260912_130651.nii", mode: "rl", seed_info: {...}, planning_params: {...}, ref_direc: [0,1,0]
```

同类泄漏还出现在：

- 工具结果的 `result` / `content` / `data` 与人类可读 `message`（如 `filesystem_browser` 的"已列出 N 个项目，路径: …"、`report_generator` 的"Exported to …"）。
- 聊天里的 system/bot 气泡文案（如"…DICOM-RT exported to: /home/…""Report generated: /home/…"）。
- 错误/通知消息（如 `Path does not exist: /home/…`）。
- 输入框的可见值（`#ctPath` / `#ctvPath` / `#oarPath`），由 `/api/upload`、`/api/agent/status`、工作区快照填充。

现有链路无任何对工具入参/结果的路径遮蔽：`ToolResultPipeline.trace_params`（`agent_runtime/core.py`）对非 `ui_*` 工具原样返回 `params`，经 SSE `step` 事件 → `ChatTask.publish` → 浏览器 `step.params` 直接渲染。最终的助手回复另有 `redact_internal_paths`（`utils/user_errors.py`），但它只对"最终回复文本"生效，且把路径裁成 basename，与本次目标不一致。

## 2. 目标与非目标

### 目标
- 浏览器中用户可见的**所有**绝对路径改为相对/令牌形式呈现。
- 显示形式：工作区根相对 + `<workspace>/` 前缀，例如 `<workspace>/inputs/CTzhouqun_20260912_130651.nii`。
- 非"病例工作区 / `.runtime` / 仓库根"的绝对路径统一显示为 `<path>/<basename>`。
- 令牌形式可**可逆回传**：输入框显示相对形式后，把该值提交给后端能正常解析还原，功能不受影响。
- 轨迹在重连回放与持久化后仍为相对形式。

### 非目标
- 不修改任何规划/剂量/导板/分割算法本身。
- 不改变送给 LLM 的对话/工具上下文（模型仍拿到真实绝对路径以便继续调用工具）。
- 不重构无关模块；不清理既有 `redact_internal_paths` 之外的错误处理。

## 3. 路径令牌方案

新增 `utils/display_paths.py`，定义按**最长前缀优先**的有序映射：

| 前缀 | 令牌 |
|---|---|
| 病例工作区根 `workspace_root`（`<runtime>/workspaces/<user>/<session>`） | `<workspace>` |
| `.runtime` 目录 | `<runtime>` |
| 仓库根 | `<app>` |
| 其余绝对路径 | `<path>/<basename>` |

核心 API：

- `relativize_text(text, roots) -> str`：把一个字符串内所有匹配的绝对路径替换为令牌形式；未知绝对路径走 `<path>/<basename>`。支持路径出现在更长文本中（错误消息）。
- `relativize_value(value, roots) -> Any`：对 `str`/`dict`/`list`/`tuple` 递归应用 `relativize_text`；其它类型原样返回。
- `resolve_user_path(value, roots) -> str`：反向还原。`<workspace>/rel` → `workspace_root/rel`；`<runtime>/…`、`<app>/…` 同理。`<workspace>` 单独出现 → 工作区根。`<path>/name` 在工作区、运行时、仓库内按 basename 唯一匹配还原；无匹配则原样返回（交由既有所有权校验报清晰错误）。不含令牌的字符串原样返回。

`roots` 是一个轻量结构（dataclass 或命名元组），字段为 `workspace_root` / `runtime_dir` / `app_root`，三者可为 `None`（缺失的令牌不参与替换/解析）。工作区根由 `task.agent.config["_workspace_root"]` 或请求上下文解析；运行时根为工作区根向上查找名为 `.runtime` 的祖先；仓库根为运行时根的父目录。

## 4. 出站（服务器 → 浏览器）

只有 3 个咽喉点，避免逐处改动：

1. **SSE 全量事件**：`web/chat_tasks.py` 的 `ChatTask.publish()`。
   - 解析出的 `data` 对 `step` / `error` / `response` 事件应用 `relativize_value`，再 `encode_event` 重新序列化后写入 journal。
   - 现状是直接写入原始 `raw` 文本；改为写入相对化后的文本，使 `self.steps` 与 `_events`（回放）一致。
   - 覆盖：工具入参/结果/内容/data、`planning_pipeline` 子步骤、`error`、流式最终回复文本。
   - `roots` 从 `task.agent.config` 计算（与 `agent_runtime/llm_runtime.py` 现有 `_workspace_root` 用法一致）。

2. **所有非流式 JSON 响应**：`web/server.py` 新增 `@app.after_request`。
   - 仅处理 `/api/*` 且 `Content-Type` 为 `application/json` 的响应；跳过 `text/event-stream` 与二进制响应。成功与错误响应统一处理。
   - 递归相对化响应 JSON。覆盖 `/api/upload`、`/api/agent/status`、工作区快照、导出响应、通知字段等，即输入框与 JS 气泡的数据来源。
   - `roots` 由请求上下文解析（`g.brachybot_workspace` 或 `session_id` + 当前用户 → `workspace_root`）；缺失时至少提供 `<runtime>` / `<app>`。

3. **最终回复清洗管道**：`utils/user_errors.py` 的 `sanitize_user_response` / `redact_internal_paths` 改为**先相对化再兜底**。
   - 传入 roots 时先 `relativize_text`，使最终回答显示 `<workspace>/...`；`redact_internal_paths` 退化为兜底（正常情况下已无 `/home/` 可匹配）。
   - 调用点：`agent_runtime/response_tools.py`、`agent_runtime/chat_workflows.py`。

## 5. 入站（浏览器 → 服务器）

在上述路径字段处用 `resolve_user_path` 还原为绝对路径，再走既有 `owns_path` / 所有权校验。字段集合（已穷举）：

- JSON body：`ct_path`、`ctv_path`、`oar_path`、`image_path`、`ct_image_path`、`label_path`、`source_path`、`path`、`created_array_paths`（列表）。
- Query：`server.py` 的 `request.args.get("path")`。
- 涉及文件：`web/server.py`、`web/routes/planning_routes.py`、`web/routes/viewer_routes.py`、`web/export_service.py`、`web/workspace_store.py`。

`<path>/<basename>` 无法保证唯一还原，主要用于"纯展示"字符串；功能型字段的实际值都落在工作区/运行时/仓库内，`<workspace>/…` 形式可精确还原。

## 6. 前端

不改任何 JS。轨迹/气泡/输入框直接渲染服务器返回的令牌字符串；回传时服务器负责解析。前端既有的 `sanitizeChatErrorContent`（检测 `/home/`）不再触发（已无 `/home/`），信息无损。

## 7. 持久化与 LLM 上下文

- `ChatTask.publish` 相对化后，写入 journal 与 `task.steps` 的内容即相对形式，重连回放与持久化的执行轨迹（`workspace_store` 的 `execution_trace`）自动为相对形式。
- 该轨迹仅用于浏览器展示，不回灌给 LLM；模型需要的工具上下文（`agent.memory` 的消息/工具结果）不经 `publish`，保持真实绝对路径。

## 8. 测试

- 新增 `tests/test_display_paths.py`：
  - 令牌映射与最长前缀优先（workspace 优先于 runtime 优先于 repo）。
  - 嵌套 dict/list 值、字符串内嵌出现。
  - `relativize` ↔ `resolve` 往返一致。
  - 未知绝对路径 → `<path>/<basename>`；`<path>/name` 唯一匹配还原 / 无匹配原样返回。
  - 缺省 roots 的行为。
- 新增/扩展一个集成式契约测试：构造带绝对路径的 `step` 事件经 `ChatTask.publish` 后为令牌形式，且 `resolve_user_path` 可还原。
- 更新既有断言"输出路径为绝对"的测试。

## 9. 风险与缓解

- `after_request` 仅对 JSON 生效，需显式跳过 SSE/二进制；SSE 由 `publish` 覆盖。
- 旧浏览器 localStorage / 旧快照里的绝对路径需刷新一次后才变相对；服务器读取旧快照出去时也会相对化。
- `<path>/<basename>` 不可精确回传；仅作展示兜底，功能字段不依赖它。
- 性能：响应体小，递归遍历开销可忽略。

## 10. 落地顺序

1. 内测 `BrachyBot` 实现 `utils/display_paths.py` + 三处出站 + 入站解析 + 测试。
2. 内测 `py_compile` + 全量测试通过。
3. 同步公测 `BrachyBot-release`（整文件 LF 覆盖 + `diff -w` 校验）。
4. 跑公测全量测试，重启公测 server 并核验（单实例 / `/api/status` 401 / prewarm）。
