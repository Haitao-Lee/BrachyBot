# Audit of Whitelist / Deterministic Constraints in the BrachyBot Chat Message Path

> Investigation question: When a user sends an instruction to BrachyBot in the chat dialog, how much behavior is determined by hardcoded whitelists / deterministic rules, such that in many cases whether an LLM is present makes little difference?
> Investigation date: 2026-08-11
> Scope: the chat message path (user message → routing → tool execution → reply)

## Core Conclusion

**Yes, the proportion is quite high.** After a user sends a message, the vast majority of behavior is already determined by fixed rules **before** the LLM is invoked. The message path:

```
POST /api/chat
  → chat_tasks 启动 worker（web/chat_tasks.py）
  → agent.chat_with_stream（agent_runtime/chat_workflows.py:1422）
  → turn_policy.classify_local_turn（确定性分类器，turn_policy.py:400）
  → 本地短路 或 LLM 函数调用（llm_runtime._run_llm_function_calling_stream）
  → 工具执行
```

The only places where the LLM truly plays a decisive role are: small talk, open knowledge Q&A, intent interpretation of ambiguous requests, and organizing tool results into prose.

---

## 1. Intent Whitelist (Most Central; Every Message Passes Through It)

| Location | Name | Purpose |
|---|---|---|
| `agent_runtime/turn_policy.py:400-559` | `classify_local_turn()` | The **pre-LLM classifier** that every message must pass through; it uses keywords/regex to sort input into one of about 12 fixed intents and attaches a tool whitelist to each intent |
| `turn_policy.py:36-45` | `LocalTurnPolicy.intent` | Fixed enumeration: `small_talk / image_metadata_query / segmentation / report_generation / surgical_guide_generation / session_content_query / case_dose_query / knowledge_query / clinical_planning / external_project_query / clinical_knowledge / ui_control` |
| `turn_policy.py:57-88` | `_is_interrogative()` | Regex detection of questions (`？吗呢 是不是/有没有 what/how/can…`), deciding whether to route to "answer" or "command" |

## 2. Deterministic Replies That Skip the LLM Entirely (`llm_calls: 0`)

The following intents use purely templated replies with **zero LLM calls**:

- `case_dose_query` (`chat_workflows.py:383-565`): dose / DVH / D90 / V100 are formatted directly from the archived snapshot (`_current_dose_metrics`)
- `image_metadata_query` (`chat_workflows.py:232-368`): CT dimensions / spacing / metadata are answered directly from an in-memory read (`_current_image_metadata`)
- `report_generation` (`chat_workflows.py:568-612`): fixed actions for report / figures / summary (`_session_content_response`)
- `session_content_query` (`chat_workflows.py:568-612`): fixed confirmation text for session content
- OAR count / 3D status questions (`chat_workflows.py:207-230, 1840-1857`): canned replies (`_build_current_oar_count_response`, `_build_3d_status_response`)
- **Rule-based chat fallback** (`chat_workflows.py:2846-3229`): when the LLM is unavailable, purely keyword-based dispatch per `分割→segmentation, 规划→planning, 评估/剂量→evaluation, 帮助→工具列表` (the `_rule_based_chat*` series)

## 3. Planning / Segmentation: The LLM Only "Recites Lines" and the Toolchain Is Fixed

- `response_tools.py:254-558` **`_detect_tool_request()`**: regex `ACTION_PATTERNS` (Chinese-English bilingual) → fixed toolchain, e.g. `plan_full → ctv → oar → planning_pipeline → surgical_guide`
- `AgenticSys.py:979-1059` `_normalize_clinical_tool_calls()`: **rewrites** the tools chosen by the LLM into the fixed order `ctv → oar → planning_pipeline → surgical_guide`
- **Workflow Enforcer** (`chat_workflows.py:1261-2709`): if the LLM has not finished, it forcibly runs the four tools and replaces the reply with a deterministic report
- `response_tools.py:654-1001` `_build_planning_report()`: the 10-section clinical report is generated directly from archived metrics, with a **comment explicitly stating "bypass LLM synthesis"**
- `llm_runtime.py:806-829`: when planning is complete but the LLM did not call a tool, the LLM summary is skipped and `_build_planning_report` is used directly
- `chat_workflows.py:2195-2208`: when the planning tool has run but the reply is < 500 characters, the full planning report is deterministically regenerated

## 4. Tools the LLM Can Call Are Also Subject to Multiple Whitelist Filters

| Location | Name | Purpose |
|---|---|---|
| `llm_runtime.py:1845-1875` + `turn_policy.py:562-569` | `filter_tool_schemas()` | Before every LLM call: CT-related tools are removed when there is no CT; only web tools are kept for external projects; filtering follows the local policy `allow_tools` |
| `turn_policy.py:13-33` | `KNOWLEDGE_TOOLS / UI_TOOLS / CLINICAL_TOOLS` | Each intent category allows only its corresponding tool subset |
| `tool_factory/ui_controller/__init__.py:27-560` | `CONTROL_REGISTRY` | ~90 UI control items, each with only a **fixed command + value range**; the LLM can only choose among them |
| `ui_controller/__init__.py:623-725` | `UIControllerTool._execute()` | Validates each `{target, command, value}`; out-of-range/unknown targets are rejected before browser execution |
| `AgenticSys.py:1813-1834` | `_VALIDATORS` | A hardcoded validation gate per tool (e.g. CTV volume > 0, number of organs detected by OAR, empty code_executor stderr) |
| `agent_runtime/core.py:95-127` | `ToolRegistry.is_available()` / `to_openai_tools()` | Unavailable tools are removed from the LLM tool schema |
| `agent_runtime/core.py:348, 377-378` | `ToolCall` validation | The tool name must be in the registry, and enums must conform to the schema |

## 5. Reply-Side Whitelists (Fallbacks When LLM Output Is Empty / Unavailable)

- `llm_runtime.py:32-42` `_EVIDENCE_ONLY_TOOLS`: the raw results of evidence-type tools (clinical_kb / web_search / web_fetch / fact_checker, etc.) **must never** become user-facing fallback answers
- `llm_runtime.py:43-64` `_SAFE_TOOL_FALLBACKS`: only segmentation / planning / dose / ui_* tools can serve as empty-reply fallbacks
- `llm_runtime.py:65-72` `_INTERNAL_FALLBACK_MARKERS`: filters debug / transport noise (`"[tool result:"`, `<html`, etc.)
- `agent_runtime/core.py:1668`: `format_steps` reuses the same reply whitelist for non-LLM synthesis
- `response_tools.py:1651-1658` `_INTERNAL_FIELDS` / `_PYTHON_REPR_RE`: intercepts hallucinated internal parameters (`step_callback`, `memory`) and Python repr values from entering tool calls
- `llm_runtime.py:1124-1148`: on an empty reply, uses `_collect_tool_fallback_text()` (whitelisted tools only) or `_tool_fallback_message()`

## 6. Security / Capability Whitelists (Not Part of Chat Routing, but Equally Constraining)

| Location | Name | Purpose |
|---|---|---|
| `tool_factory/shell_executor/__init__.py:29-43` | `BLOCKED_COMMANDS` + `ALLOWED_PATTERNS` | The Shell tool allows only whitelisted executables (python / ls / git / curl …); dangerous patterns are blocked |
| `tool_factory/env_manager/__init__.py:222-235` | `ALLOWED_PACKAGE_PATTERNS` / `BRACHYBOT_ENV_PACKAGE_ALLOWLIST` | pip install package whitelist |
| `web/server_support.py:2797-2814` | `_allowed_read_roots()` / `_allowed_write_roots()` | File read/write root whitelist (uploads / .runtime / /tmp / environment-config root); `_validate_path` is enforced on every image path |
| `agents/fact_checker.py:63-74` | `TRUSTED_DOMAINS` | Trusted domain whitelist (PubMed / NCCN / AAPM / WHO, etc.); the rest are marked "Unverified sources" |
| `agents/fact_checker.py:76-85` | `HALLUCINATION_PATTERNS` | Deterministic hallucination blacklist ("according to a study I conducted", placeholder PMID/URL, etc.) |
| `brain/core/tool_code_writer.py:281-317` | `allowed_imports` | Import whitelist for LLM-generated tool code |
| `tool_factory/tool_creator/__init__.py:40-84` | `allowed_imports` | Same as above, used for the "create tool" capability |
| `tool_factory/CTV_seg/model_catalog.py:515-541` | `filter_catalog()` | CTV models are filtered by `ui_visible / deprecated / site / include_experimental`, determining which models are visible and available to the LLM / operator |
| `agent_runtime/response_tools.py:1399-1407` | `_SUPPORTED_AUTOMATIC_CTV_TYPES` | Whitelist of CTV model routes that automatic planning may emit |

## 7. Fixed-Enumeration Intent Classification (Rather Than Free-Text LLM Judgment)

| Location | Enumeration / Fixed Set | Value |
|---|---|---|
| `turn_policy.py:36-45` | `LocalTurnPolicy.intent` | 12 fixed intents (see Section 1) |
| `agents/router_agent.py:37-122` | `RouterAgent.INTENT_PATTERNS` | `follow_up / clinical_planning / segmentation / dose_evaluation / knowledge_query / web_search / optimization / status_check` (+ fallback `general`) |
| `response_tools.py:1290-1320` | `_classify_query_type()` | `realtime / knowledge / analysis / system` |
| `turn_policy.py:310-378` | `resolve_session_content_target()` | Fixed target enumeration: `report_figures / report / session_screenshots / planning / dose / dvh / metrics / ct / structures / surgical_guide / data_tree / chat_history / artifact / session_summary` |
| `turn_policy.py:203-257` | `resolve_report_request_action()` | `regenerate / view_figures / view` |

## Conclusion

**The LLM's role is deliberately narrowed to an "intent translator + text generator"**: intent classification, toolchain orchestration, report synthesis, parameter validation, and reply fallback are all hardcoded. This ensures the deterministic safety of the clinical workflow (the segmentation → planning → guide order is not disturbed, and no hallucinated dose appears), at the cost of the LLM having almost no decision-making authority over structured clinical tasks.

### Candidate Modification Entry Points (For Subsequent Discussion Only; This Audit Changed No Code)

1. `_detect_tool_request`'s `ACTION_PATTERNS` (`response_tools.py:327-353`) — if the LLM is to participate in toolchain selection
2. The forced chain of `_normalize_clinical_tool_calls` (`AgenticSys.py:979-1059`) — if orchestration latitude for the LLM is to be preserved
3. The purely templated report of `_build_planning_report` (`response_tools.py:654-1001`) — if the LLM is to participate in report interpretation
4. The intent enumeration of `classify_local_turn` (`turn_policy.py:400-559`) — if the LLM's scope for intent judgment is to be expanded

---

## 2026-08-11 Implementation Results: Semantic Decisions + Structured Execution Authorization

The issues raised by this audit have been implemented under the principle of "preserving the clinical safety boundary while restoring the LLM's authority to judge complete user semantics". The changes did not remove any existing tools, Viewer controls, reports, screenshots, Monitor, or planning capabilities, nor did they relax tool parameter validation, path restrictions, or clinical result verification.

### New Decision Boundaries

1. `classify_local_turn()` no longer tries to cover every expression with keywords. Only standard commands with clear semantics, no negation, no scope restrictions, and no corrective relation enter the fast path with zero additional LLM.
2. Messages containing negation, exclusion, conditions, corrections, diagnostics, mixed targets, or open-ended operation requirements uniformly enter the existing main LLM function-calling path, where the LLM interprets intent using the current Session state and the complete tool schema.
3. Each conversation turn creates an independent `TurnExecutionAuthorization`. Only tools authorized by this turn's fast path or explicitly selected by the LLM may perform operations that change case state.
4. A backend workflow may only supplement the necessary prerequisite steps for an already-authorized high-level task. For example, an authorized full plan may supplement CTV, OAR, and `planning_pipeline`, but a task must not be started merely because the text contains "规划".
5. Surgical Guide, Report, and Planning are mutually independent write operations. Completion of planning no longer unconditionally triggers the guide; the guide must be explicitly requested by the user in this turn or explicitly selected by the LLM in this turn.
6. The existing parameter schema, tool availability, Session/Planning ownership checks, path safety, result verification, and internal log filtering remain in place. They constrain "how to execute safely" and no longer replace the LLM in deciding "whether the user requested execution".

### Fast Path vs. Flexible Path

- Fast-path examples: `请执行放射性粒子植入规划`, `请执行 CTV 分割`, `请重新生成报告`, `请重新生成手术导板`. These standard commands retain the original low-latency and deterministic workflow.
- Semantic-path examples: `我上传了肝脏肿瘤 CT，请不要执行规划`, `只分割 CTV，不要规划，也不要生成导板`, `我不是要看报告截图，而是要重新填充报告文字`, `把当前能呈现的结果整理给我`.
- Read-only questions remain read-only, including dose, DVH, CT metadata, current Session content, status queries, and concept explanations.

### Key Code

- `agent_runtime/execution_authorization.py`: per-turn structured execution authorization and workflow authorization.
- `agent_runtime/turn_policy.py`: fast-path boundaries, complex-expression recognition, and full tool-capability exposure.
- `agent_runtime/chat_workflows.py`: per-turn authorization lifecycle, direct path, and workflow chain-completion entry points.
- `agent_runtime/llm_runtime.py`: converts tools explicitly selected by the LLM into this turn's execution authorization and filters unauthorized backend-inserted calls.
- `AgenticSys.py`: the planning workflow consumes only structured authorization and no longer reads raw text to decide whether to plan.
- `agent_runtime/response_tools.py`: keyword rewriting for reports/screenshots is limited to the standard fast path and no longer overrides semantic choices already made by the LLM.
- `config/prompts/system_prompt.md`, `config/prompts/planning_agent.md`: define "mentioning is not authorizing", negation priority, read/write separation, and honest-failure strategy.

### Regression Verification

- Added dedicated semantic-authorization tests covering negated planning, mixed scope, conceptual questions, report corrections, unknown open commands, planning prerequisites, and independent guide authorization.
- Full regression in the remote Conda runtime environment: `643 passed, 4 skipped`.
- Standard planning commands still take the local fast path, adding no extra LLM routing latency.
- Negated planning messages do not receive local planning authorization; even if the LLM or backend fails, the old keyword chain-completion cannot start segmentation and planning.

### Current Runtime Environment Limitations

The deployed service has been started on `203.0.113.10:8080`, with HTTP and authentication boundaries working normally. In the real-provider smoke test, the external LLM credentials inherited by the current server returned HTTP 401; this is a runtime credential failure, not a semantic-routing or tool-authorization failure. The test message `我上传了一名肝脏肿瘤患者CT，请不要执行规划` finished in about 1.27 seconds, with 0 clinical tool calls; the user reply used a friendly Chinese explanation, and the raw 401/API key information did not enter the chat stream. After updating valid credentials, a semantic-answer and end-to-end latency verification under a successful provider response still needs to be completed.
