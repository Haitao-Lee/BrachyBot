# BrachyBot 聊天消息路径中的白名单 / 确定性约束审计

> 调查问题：当用户在对话框中向 BrachyBot 发送指令时，有多少行为是由硬编码的白名单 / 确定性规则决定，以至于在很多时候有没有 LLM 影响不大？
> 调查日期：2026-08-11
> 范围：聊天消息路径（用户消息 → 路由 → 工具执行 → 回复）

## 核心结论

**是的，比例相当高。** 用户发消息后，绝大部分行为在调用 LLM **之前**就已经被固定规则决定。消息路径：

```
POST /api/chat
  → chat_tasks 启动 worker（web/chat_tasks.py）
  → agent.chat_with_stream（agent_runtime/chat_workflows.py:1422）
  → turn_policy.classify_local_turn（确定性分类器，turn_policy.py:400）
  → 本地短路 或 LLM 函数调用（llm_runtime._run_llm_function_calling_stream）
  → 工具执行
```

LLM 真正起决定性作用的地方只剩下：闲聊、开放知识问答、模糊请求的意图解读、以及把工具结果组织成散文。

---

## 一、意图白名单（最核心，每条消息都经过）

| 位置 | 名称 | 作用 |
|---|---|---|
| `agent_runtime/turn_policy.py:400-559` | `classify_local_turn()` | 每条消息必经的 **LLM 前分类器**，用关键词/正则把输入归入约 12 个固定意图之一，并附带每个意图的工具白名单 |
| `turn_policy.py:36-45` | `LocalTurnPolicy.intent` | 固定枚举：`small_talk / image_metadata_query / segmentation / report_generation / surgical_guide_generation / session_content_query / case_dose_query / knowledge_query / clinical_planning / external_project_query / clinical_knowledge / ui_control` |
| `turn_policy.py:57-88` | `_is_interrogative()` | 正则检测问句（`？吗呢 是不是/有没有 what/how/can…`），决定走"回答"还是"命令"路由 |

## 二、完全跳过 LLM 的确定性回复（`llm_calls: 0`）

以下意图走纯模板回复，**零 LLM 调用**：

- `case_dose_query`（`chat_workflows.py:383-565`）：剂量 / DVH / D90 / V100 从存档快照直接格式化输出（`_current_dose_metrics`）
- `image_metadata_query`（`chat_workflows.py:232-368`）：CT 尺寸 / spacing / 元数据直接读内存回答（`_current_image_metadata`）
- `report_generation`（`chat_workflows.py:568-612`）：报告 / 图 / 摘要固定动作（`_session_content_response`）
- `session_content_query`（`chat_workflows.py:568-612`）：会话内容固定确认文案
- OAR 数量 / 3D 状态问题（`chat_workflows.py:207-230, 1840-1857`）：canned 回复（`_build_current_oar_count_response`、`_build_3d_status_response`）
- **规则聊天兜底**（`chat_workflows.py:2846-3229`）：LLM 不可用时按 `分割→segmentation、规划→planning、评估/剂量→evaluation、帮助→工具列表` 纯关键词分发（`_rule_based_chat*` 系列）

## 三、规划 / 分割类：LLM 只"背台词"，工具链被固定

- `response_tools.py:254-558` **`_detect_tool_request()`**：正则 `ACTION_PATTERNS`（中英双语）→ 固定工具链，如 `plan_full → ctv → oar → planning_pipeline → surgical_guide`
- `AgenticSys.py:979-1059` `_normalize_clinical_tool_calls()`：把 LLM 选的工具**重写**成固定的 `ctv → oar → planning_pipeline → surgical_guide` 顺序
- **Workflow Enforcer**（`chat_workflows.py:1261-2709`）：LLM 没执行完就强制补跑四个工具，并把回复替换成确定性报告
- `response_tools.py:654-1001` `_build_planning_report()`：10 节临床报告直接从存档指标生成，**注释明确"绕过 LLM 合成"**
- `llm_runtime.py:806-829`：规划完成但 LLM 未调用工具时，跳过 LLM 摘要直接用 `_build_planning_report`
- `chat_workflows.py:2195-2208`：规划工具已跑但回复 < 500 字符时，确定性重新生成完整规划报告

## 四、LLM 能调用的工具也受多重白名单过滤

| 位置 | 名称 | 作用 |
|---|---|---|
| `llm_runtime.py:1845-1875` + `turn_policy.py:562-569` | `filter_tool_schemas()` | 每次 LLM 调用前：无 CT 时剔除 CT 相关工具；外部项目只留 web 工具；按本地策略 `allow_tools` 过滤 |
| `turn_policy.py:13-33` | `KNOWLEDGE_TOOLS / UI_TOOLS / CLINICAL_TOOLS` | 每个意图类别只允许对应的工具子集 |
| `tool_factory/ui_controller/__init__.py:27-560` | `CONTROL_REGISTRY` | ~90 个 UI 控制项，每个只有**固定命令 + 取值范围**，LLM 只能从中挑选 |
| `ui_controller/__init__.py:623-725` | `UIControllerTool._execute()` | 校验每个 `{target, command, value}`，越界/未知目标在浏览器执行前被拒绝 |
| `AgenticSys.py:1813-1834` | `_VALIDATORS` | 每个工具硬编码验证门（如 CTV 体积 > 0、OAR 检出器官数、code_executor stderr 为空） |
| `agent_runtime/core.py:95-127` | `ToolRegistry.is_available()` / `to_openai_tools()` | 不可用工具从 LLM 工具 schema 中剔除 |
| `agent_runtime/core.py:348, 377-378` | `ToolCall` 校验 | 工具名必须在 registry 内、enum 必须符合 schema |

## 五、回复侧的白名单（LLM 输出为空 / 不可用时的兜底）

- `llm_runtime.py:32-42` `_EVIDENCE_ONLY_TOOLS`：证据类工具（clinical_kb / web_search / web_fetch / fact_checker 等）的原始结果**永远不能**变成面向用户的兜底答案
- `llm_runtime.py:43-64` `_SAFE_TOOL_FALLBACKS`：只有分割 / 规划 / 剂量 / ui_* 工具可做空回复兜底
- `llm_runtime.py:65-72` `_INTERNAL_FALLBACK_MARKERS`：过滤调试 / 传输杂串（`"[tool result:"`、`<html` 等）
- `agent_runtime/core.py:1668`：`format_steps` 复用同一套回应白名单做非 LLM 合成
- `response_tools.py:1651-1658` `_INTERNAL_FIELDS` / `_PYTHON_REPR_RE`：拦截幻觉的内部参数（`step_callback`、`memory`）与 Python repr 值进入工具调用
- `llm_runtime.py:1124-1148`：空回复时用 `_collect_tool_fallback_text()`（仅白名单工具）或 `_tool_fallback_message()`

## 六、安全 / 能力白名单（不属于聊天路由，但同样约束行为）

| 位置 | 名称 | 作用 |
|---|---|---|
| `tool_factory/shell_executor/__init__.py:29-43` | `BLOCKED_COMMANDS` + `ALLOWED_PATTERNS` | Shell 工具只允许白名单可执行文件（python / ls / git / curl …），危险模式被拦截 |
| `tool_factory/env_manager/__init__.py:222-235` | `ALLOWED_PACKAGE_PATTERNS` / `BRACHYBOT_ENV_PACKAGE_ALLOWLIST` | pip 安装包白名单 |
| `web/server_support.py:2797-2814` | `_allowed_read_roots()` / `_allowed_write_roots()` | 文件读写根目录白名单（uploads / .runtime / /tmp / 环境配置根目录），`_validate_path` 在每个图片路径上强制执行 |
| `agents/fact_checker.py:63-74` | `TRUSTED_DOMAINS` | 可信域名白名单（PubMed / NCCN / AAPM / WHO 等），其余标记"Unverified sources" |
| `agents/fact_checker.py:76-85` | `HALLUCINATION_PATTERNS` | 确定性幻觉黑名单（"according to a study I conducted"、占位 PMID/URL 等） |
| `brain/core/tool_code_writer.py:281-317` | `allowed_imports` | LLM 生成工具代码的 import 白名单 |
| `tool_factory/tool_creator/__init__.py:40-84` | `allowed_imports` | 同上，用于"创建工具"能力 |
| `tool_factory/CTV_seg/model_catalog.py:515-541` | `filter_catalog()` | CTV 模型按 `ui_visible / deprecated / site / include_experimental` 过滤，决定 LLM / 操作员可见可用的模型 |
| `agent_runtime/response_tools.py:1399-1407` | `_SUPPORTED_AUTOMATIC_CTV_TYPES` | 自动规划可发出的 CTV 模型路由白名单 |

## 七、固定枚举意图分类（而非自由文本 LLM 判断）

| 位置 | 枚举 / 固定集合 | 值 |
|---|---|---|
| `turn_policy.py:36-45` | `LocalTurnPolicy.intent` | 12 个固定意图（见第一节） |
| `agents/router_agent.py:37-122` | `RouterAgent.INTENT_PATTERNS` | `follow_up / clinical_planning / segmentation / dose_evaluation / knowledge_query / web_search / optimization / status_check`（+ 兜底 `general`） |
| `response_tools.py:1290-1320` | `_classify_query_type()` | `realtime / knowledge / analysis / system` |
| `turn_policy.py:310-378` | `resolve_session_content_target()` | 固定目标枚举：`report_figures / report / session_screenshots / planning / dose / dvh / metrics / ct / structures / surgical_guide / data_tree / chat_history / artifact / session_summary` |
| `turn_policy.py:203-257` | `resolve_report_request_action()` | `regenerate / view_figures / view` |

## 结论

**LLM 的作用被刻意收窄成一个"意图翻译器 + 文案生成器"**：意图分类、工具链编排、报告合成、参数校验、回复兜底全部是硬编码的。这保证了临床流程的确定性安全（分割 → 规划 → 导板顺序不乱、不出现幻觉剂量），代价是 LLM 对结构化临床任务几乎没有决策权。

### 候选改造切入点（仅供后续讨论，本审计未改动任何代码）

1. `_detect_tool_request` 的 `ACTION_PATTERNS`（`response_tools.py:327-353`）— 若希望 LLM 参与工具链选择
2. `_normalize_clinical_tool_calls` 的强制链（`AgenticSys.py:979-1059`）— 若希望保留 LLM 编排空间
3. `_build_planning_report` 的纯模板报告（`response_tools.py:654-1001`）— 若希望 LLM 参与报告解读
4. `classify_local_turn` 的意图枚举（`turn_policy.py:400-559`）— 若希望扩大 LLM 的意图判断范围

---

## 2026-08-11 实施结果：语义决策 + 结构化执行授权

本审计提出的问题已按“保留临床安全边界，同时恢复 LLM 对完整用户语义的判断权”的原则实施。改造没有删除原有工具、Viewer 控制、报告、截图、Monitor 或规划能力，也没有放宽工具参数校验、路径限制和临床结果验证。

### 新的决策边界

1. `classify_local_turn()` 不再尝试用关键词覆盖所有表达。只有语义明确、无否定、无范围限制、无纠正关系的标准命令进入零额外 LLM 的快速路径。
2. 包含否定、排除、条件、纠正、诊断、混合目标或开放式操作要求的消息统一进入既有主 LLM 的函数调用路径，由 LLM 结合当前 Session 状态和完整工具 schema 理解意图。
3. 每一轮对话创建独立的 `TurnExecutionAuthorization`。只有本轮快速路径授权或 LLM 明确选择的工具才能执行会改变病例状态的操作。
4. 后端工作流只能为已经授权的高层任务补齐必要前置步骤。例如，已授权的完整规划可以补齐 CTV、OAR 和 `planning_pipeline`，但不能因为文本出现“规划”就启动任务。
5. Surgical Guide、Report 和 Planning 是彼此独立的写操作。规划完成不再无条件触发导板；导板必须由用户本轮明确要求或由 LLM 在本轮明确选择。
6. 原有的参数 schema、工具可用性、Session/Planning 归属校验、路径安全、结果验证和内部日志过滤继续保留。它们约束“如何安全执行”，不再替代 LLM 决定“用户是否要求执行”。

### 快速路径与灵活路径

- 快速路径示例：`请执行放射性粒子植入规划`、`请执行 CTV 分割`、`请重新生成报告`、`请重新生成手术导板`。这些标准命令保持原有低延迟和确定性工作流。
- 语义路径示例：`我上传了肝脏肿瘤 CT，请不要执行规划`、`只分割 CTV，不要规划，也不要生成导板`、`我不是要看报告截图，而是要重新填充报告文字`、`把当前能呈现的结果整理给我`。
- 只读问题继续保持只读，包括剂量、DVH、CT 元数据、当前 Session 内容、状态查询和概念解释。

### 关键代码

- `agent_runtime/execution_authorization.py`：每轮结构化执行授权和工作流授权。
- `agent_runtime/turn_policy.py`：快速路径边界、复杂表达识别和完整工具能力暴露。
- `agent_runtime/chat_workflows.py`：每轮授权生命周期、直接路径和工作流补链入口。
- `agent_runtime/llm_runtime.py`：将 LLM 明确选择的工具转换为本轮执行授权，并过滤未授权的后端插入调用。
- `AgenticSys.py`：规划工作流只消费结构化授权，不再读取原始文本判断是否规划。
- `agent_runtime/response_tools.py`：报告/截图的关键词重写仅限标准快速路径，不再覆盖 LLM 已完成的语义选择。
- `config/prompts/system_prompt.md`、`config/prompts/planning_agent.md`：定义“提及不等于授权”、否定优先、读写分离和诚实失败策略。

### 回归验证

- 新增语义授权专项测试，覆盖否定规划、混合范围、概念性提问、报告纠正、未知开放命令、规划前置步骤和导板独立授权。
- 远端 Conda 运行环境全量回归：`643 passed, 4 skipped`。
- 标准规划命令仍走本地快速路径，不增加额外 LLM 路由延迟。
- 否定规划消息不会获得本地规划授权；即使 LLM 或后端发生异常，也不能由旧的关键词补链启动分割和规划。

### 当前运行环境限制

部署服务已在 `192.168.1.113:8080` 启动，HTTP 和认证边界正常。真实供应商烟雾测试中，当前服务器继承的外部 LLM 凭据返回 HTTP 401；这是运行凭据失效，不是语义路由或工具授权失败。测试消息 `我上传了一名肝脏肿瘤患者CT，请不要执行规划` 在约 1.27 秒内结束，临床工具调用为 0，用户回复使用中文友好说明，原始 401/API key 信息未进入聊天流。更新有效凭据后仍需补做一次供应商成功响应下的语义回答和端到端时延验证。
