# BrachyBot 架构全局理解

> 通过 codegraph（231 个文件索引）对整个项目做的系统性探索。涵盖子系统划分、端到端请求链路、数据流、设计模式、配置/基准方法与近期演化重点。

**生成日期:** 2026-06-13

---

## 一、Elevator Pitch（一句话定位）

**BrachyBot** 是一个面向临床的、由 LLM 驱动的多智能体近距离放射治疗（brachytherapy）规划平台，把 CT/MR 影像上传、CTV/OAR 分割、针道轨迹优化、粒子（seed）布源、剂量计算（CNN/高斯）、DVH 评估、约束校验与 DICOM 导出整合到一个 Flask Web 应用中，通过统一的 `ToolRegistry` 暴露给具备函数调用能力的 `BrachyAgent`，配合 `PlanReviewer` / `FactChecker` / `SafetyGuardian` 多智能体评审、`QualityGate` 多模态质量门控、文件系统式 `Case/ClinicalKB` 记忆、动态工具创建、SSE 实时任务流以及基于 Playwright 的 525 例 v2 基准测试系统，实现"上传→规划→评估→导出"全流程的临床决策支持。

---

## 二、高层架构图

```
+----------------------------------------------------------------------------+
|                              Web Frontend (SPA)                             |
|  web/app/index.html  +  static/  (Cornerstone-style 2D/3D viewer, chat UI,  |
|  panel-based UI for CT slices, dose overlay, planning config, exports)     |
+-----------------------------------+----------------------------------------+
                                    |  HTTP (fetch + SSE)  /api/*
                                    v
+----------------------------------------------------------------------------+
|                        Flask Backend  (web/server.py)                       |
|  create_app() @ web/server.py:174  |  MAX_CONTENT_LENGTH 500MB             |
|  Per-session BrachyAgent in _sessions{}  |  LRU 50 / 1hr TTL                 |
|  30+ routes: upload / viewer / planning / chat / tasks(stream) / export      |
+----+----------------------------------+----------------+--------------------+
     |                                  |                |
     v                                  v                v
+------------+   chat()/chat_with_stream()  +----------------------+
|   Upload  +------------------------->+    BrachyAgent         |
|  /api/up   |                           |  (AgenticSys.py:847)   |
+------------+                           |  - rule-based detect   |
                                        |  - LLM func-calling   |
                                        |  - tool exec + retry  |
                                        |  - multi-agent init   |
                                        +-----+-----------------+
                                              |
                  +---------------------------+----------------------------+
                  |                           |                            |
                  v                           v                            v
        +-------------------+     +----------------------+     +--------------------+
        |   ToolRegistry    |     |   AgentMemory        |     |  Multi-Agent Subsys|
        |  (AgenticSys.py   |     |  (AgenticSys.py:135) |     |  (agents/*)        |
        |   :52-132)        |     |  +SmartContextManager|     |  Router / Planner  |
        |  + brain/core/    |     |  (memory/smart_context|     |  PlanReviewer      |
        |   tool_registry   |     |   max 8000 tokens)   |     |  FactChecker       |
        |  21 ToolSpec from |     +----------------------+     |  SafetyGuardian    |
        |  toolset.json     |                                   |  Synthesizer       |
        +---------+---------+                                   |  ->QualityGate     |
                  | dispatch                                     +---------+---------+
                  v                                                         |
   +--------------+--------------+----------+----------+----------------+    |
   |              |              |          |        |                |    |
   |   Segmentation |  Planning  | Dose Eng | Eval   | Memory/KB      |    |
   |   CTV_seg/*   |  traj_plan | dose_eng | dose_  | case_memory    |    |
   |   OAR_seg/*   |  seed_plan | gaussian | eval/  | clinical_kb    |    |
   |   totalseg_*  |  planning_  | cnn_dose | quality| clinical_kb/   |    |
   |               |  pipeline   | _engine  | plan_  | knowledge_base |    |
   +---------------+-------------+----------+--------+----------------+    |
                                                                          |
                                              Quality Gate reviews ------>+
                                              (parallel: plan_reviewer,
                                               fact_checker, safety_guardian)
                                              rules -> GateResult
                                              -> human-in-loop on reject

   +----------------------------------------------------------------+
   |                ToolFactory: 40+ tools (BaseTool)                |
   |  image_loader | image_preproc | viewer_command | ui_* | export |
   |  filesystem_browser | shell_exec | code_exec | env_manager      |
   |  web_search/fetch/access | report_generator | safety_validator |
   |  tool_creator (dynamic Python generation)                      |
   +----------------------------------------------------------------+
                                  |
                                  v
   +----------------------------------------------------------------+
   |   plans/ (Zhiyuan v2 algorithm) + dose_pre/ + VoCo/ + scripts  |
   |   trajectories, optimal_plan, optimal_plan_rl (REINFORCE)      |
   +----------------------------------------------------------------+
                                  |
                                  v
   +----------------------------------------------------------------+
   |          Persistent Storage (JSON, single-process)              |
   |  uploads/<CT_*>.nii | case_memory/data/*.json | clinical_kb/   |
   |  memory/data/crystallized_skills.json | skills/data/skills/    |
   |  + DICOM RT / STL / PDF reports on demand                       |
   +----------------------------------------------------------------+

   +----------------------------------------------------------------+
   |      Benchmark & Self-Evolution (benchmarks/ v1,v2)            |
   |  aligned_benchmark.py (Playwright 1920x1080 @ :8080)           |
   |  525 cases / 22 categories | 6-dim scoring | root-cause label  |
   |  generate_final_report.py | auto_monitor.py | 4-agent parallel |
   +----------------------------------------------------------------+
```

---

## 三、端到端请求生命周期

> 以"上传 CT、请求胰腺癌 CTV/OAR 分割、生成规划、评估 DVH、导出 DICOM RT"为典型例子。

### 1. 上传 CT 体积
- **入口**：`POST /api/upload`（`web/server.py:260` `api_upload()`）。
- **限制**：`MAX_CONTENT_LENGTH = 500MB`（`web/server.py:187`），支持 `.nii / .nii.gz / .mhd / .dcm`、DICOM 目录。
- **落盘**：`uploads/CTyuanaju_20260613_122330.nii`。
- **解析**：`tool_factory/image_processing/image_loader.py:18` 的 `ImageLoaderTool` 用 SimpleITK 读取并抽取 spacing/origin/direction/size。
- **回传 UI**：JSON 返回 `{file_id, file_path, metadata, viewer_ready=true}`。

### 2. 进入 CT 查看器（2D + 3D）
- 前端调用 `GET /api/viewer/image`、`POST /api/viewer/slice`、`GET /api/viewer/volume`（`web/server.py:299/319/397/483`）。
- 3D 网格：`POST /api/viewer/3d`、`/api/viewer/3d_mask`、`/api/viewer/3d_skin`（`web/server.py:886/973/1103`）。
- HU 调节：`POST /api/viewer/hu`（`web/server.py:833`），预设 lung/bone/soft_tissue/brain/default。
- LLM 主动控制 viewer：通过 `ViewerCommandTool` 发出结构化 `{target, command, value}` → `POST /api/viewer/control`（`web/server.py:2322`）。

### 3. 用户发送聊天消息
- **入口**：`POST /api/chat`（`web/server.py:2112`）。
- 后端按 `session_id` 调 `get_agent(session_id)`（LRU/TTL 守卫，`web/server.py:193-251`），拿到 `BrachyAgent(AgenticSys)` 实例。
- 调用主入口 `BrachyAgent.chat(message)`（`AgenticSys.py:3600`）或流式 `chat_with_stream`（SSE 通过 `/api/tasks/stream`、`web/server.py:2181`）。
- Abort 支持：`POST /api/chat/abort`（`web/server.py:1991`）。

### 4. Agent 主循环（混合：规则 + LLM 函数调用）
- **规则路径**（`AgenticSys.py:1599 _detect_tool_request`）：模式匹配识别 `segment` / `plan` / `dose evaluation` → `_execute_direct_tools` 直接调工具，跳过 LLM。
- **LLM 路径**（`_run_llm_function_calling` `AgenticSys.py:2098` / 流式 `2760`）：
  1. 构造系统提示（`config/prompts/system_prompt.md`） + 多智能体提示（`config/prompts/multi_agent/*.md`，由 `LLMCapableAgent._load_system_prompt` `base_agent.py:145` 注入）。
  2. 加载 `SmartContextManager` 摘要（`memory/smart_context.py:499`），把 `AgentMemory` 的 patient_data / planning_results 压缩到 ≤8000 token。
  3. 通过 `Brain Router`（`brain/core/router.py:170`）按 `task_type` 选 provider（OpenAI / Anthropic / OpenRouter），常用 `claude-sonnet-4-20250514`。
  4. 将 `ToolRegistry.to_openai_tools()` 转成 function-calling 描述。
  5. LLM 返回 `tool_calls`；Agent 解析为 `(tool_name, args)`。
  6. 派发到 `_execute_tool_with_memory`（`AgenticSys.py:1248`） → `_validate_and_execute`（`AgenticSys.py:1402`，含重试） → `ToolRegistry.execute(name, **kwargs)`。
  7. 工具结果走 `ToolResultPipeline.format`（`AgenticSys.py:446`）按 segmentation/analysis/ui/planning 分类格式化为 markdown/JSON。
  8. 反馈给 LLM 让其继续决策或最终合成 `_synthesize_with_llm`。

### 5. 分割流程（CTV + OAR）
- 工具调用 `pancreatic_ctv`（`tool_factory/CTV_seg/`）、`totalsegmentator_oar`（104 个结构）或器官特化工具。
- 结果 mask 写入 `AgentMemory.planning_results["ctv_mask"/"oar_masks"]`，同时通过 `/api/viewer/overlay`（`web/server.py:634`）实时回显到前端。

### 6. 规划流水线（5 步顺序）
入口工具 `planning_pipeline`（`tool_factory/seed_plan/planning_pipeline.py`），由 `BrachyAgent` 一步调用或拆成 `/api/planning/run_step`（`web/server.py:1435`）分步执行：

1. **trajectory_init**：`plans/core.py:init_plan` → `plans.utilizations.get_cone/get_close_points` 构建圆锥方向网格，按 `min_depth` 修剪。
2. **trajectory_refine**：碰撞/障碍物过滤。
3. **seed_planning**：`plans/core.py:optimal_plan`（3 阶段：轨迹选择+布源至 DVH_rate、replan、sequentially remove/add）或 `optimal_plan_rf`（Hierarchical REINFORCE）。
4. **dose_calc**：`cnn_dose_engine`（`tool_factory/dose_engine/cnn_dose_engine.py:16`，myDoseNet 深度学习代理）或 `gaussian_dose_engine`（`gaussian_dose_engine.py:15` 解析高斯近似）。
5. **dose_eval**：`comprehensive_dose_evaluation` 输出 V100/V150/V200、D90/D100/D2cc、DVH、0–100 `plan_score`。

中间状态 `resampled_ct/ctv/oar, trajectories, seed_plan, dose_distribution, total_seeds, ct_spacing, organ_names` 持久化到 `AgentMemory` 以便步骤恢复。

### 7. 多智能体质量门控（关键安全环节）
- `QualityGate.review(output_type, content, context, force_review)`（`quality/quality_gate.py:19`）按 `MANDATORY_REVIEWS = {treatment_plan, dose_evaluation, clinical_recommendation, web_search_medical}` 触发。
- `asyncio.gather` 并行跑 `PlanReviewer`（`agents/plan_reviewer.py`）、`FactChecker`（`agents/fact_checker.py`：claim/source 验证/反幻觉）、`SafetyGuardian`（`agents/safety_guardian.py`：5 项 OAR/剂量校验）。
- 聚合规则：任一 reject → 拒批+人工；加权分 <5 → 拒；>50% conditional 或 <7 → conditional；否则 pass。
- 通信协议：`AgentMessage/AgentResponse/AgentRole`（`communication/protocol.py:1-138`）+ `MessageBus` 异步 pub/sub（`communication/message_bus.py:17`），`Orchestrator`（`agents/orchestrator.py:16`）协调。

### 8. 结果回流 UI
- 规划结果通过 `/api/planning/results`（`web/server.py:1332`）、`/api/planning/seeds_3d`（`web/server.py:1172`）送到前端。
- 剂量可视化：`/api/planning/dose_isosurface`（`web/server.py:1525`）、`/api/planning/dose_overlay_slice`（`web/server.py:1673`）、`/api/planning/dose_contour_slice`（`web/server.py:1739`）。
- 聊天响应走 `ToolResultPipeline._format_planning`（`AgenticSys.py:460+`）渲染为 markdown，前端渲染为气泡。
- 实时进度：SSE `GET /api/tasks/stream`（`web/server.py:2181`）+ `yield_event`/`emit` 事件（`AgenticSys.py:3712/2769`）。

### 9. 持久化与导出
- 长期案例：`case_memory` 工具把最终 plan 落盘 `tool_factory/case_memory/data/<case_id>.json`。
- 导出：`POST /api/export/dicom_rt`（`web/server.py:2026`）、`/api/export/stl`（`web/server.py:2067`）、`/api/export/dicom`（`web/server.py:2215`）、`/api/export/report`（`web/server.py:2270`），从 `AgentMemory.retrieve('ct_image'/'seed_positions'/'dose_distribution'/'metrics')` 读取。
- 技能进化：`SkillRegistry.evolve_from_interactions`（`AgenticSys.py:4599`）+ `SkillCrystallizer`（`memory/skill_crystallizer.py`）把高频成功链路沉淀到 `crystallized_skills.json`。

---

## 四、子系统、职责与关键入口

### A. Web / HTTP 层（`web/`）
- 入口：`web/server.py:174 create_app()`，Flask + flask_cors，单页应用 `GET /` → `web/app/index.html`。
- 会话管理：`_sessions{}` 字典 + LRU(50) + 1h TTL（`web/server.py:193-251`），`get_agent()` 懒构造。
- 30+ REST 端点分四组：影像/查看器、规划、任务流（SSE）、导出、聊天。
- 实时：SSE（`/api/tasks/stream`），无 WebSocket；遗留 `websocket_clients`（`web/server.py:198`）未使用。
- 静态：`web/app/static/`，`Cache-Control: no-cache`。

### B. 智能体核心（`AgenticSys.py` + `agents/` + `brain/`）
- `BrachyAgent`（`AgenticSys.py:847`）：单智能体主入口，混合规则/LLM 调度。
- `agents/`：6 类专门智能体（router、plan_reviewer、fact_checker、safety_guardian、orchestrator、synthesizer，派生自 `BaseAgent` + `LLMCapableAgent`，`base_agent.py:160`）。
- `brain/`：provider 抽象（`providers/openai_llm.py:15`、`anthropic_llm.py:18`、`openrouter_llm.py`、`minimax_llm.py`）、router（`core/router.py:170`）、tool_registry、tree_search_planner、execution、knowledge、memory、prompts。
- `communication/`：消息总线（`message_bus.py:17`）+ 协议（`protocol.py:1`）。

### C. 工具工厂（`tool_factory/`）
- 公共基类：`tool_factory/__init__.py:63 BaseTool` + `ToolResult`。
- 类别子包：CTV_seg、OAR_seg、traj_plan、seed_plan、dose_engine、dose_eval、image_processing、viewer_command、ui_inspector/controller/screenshot/annotate、filesystem_browser、shell_executor、code_executor、env_manager、web_access/fetch/search、report_generator、safety_validator、performance_tracker、plan_comparator、plan_quality、tool_creator、case_memory、clinical_kb、output、doc_reader、seed_seg。
- 注册中心：`brain/core/tool_registry.py:11 ToolSpec`（含 `toolset.json`，21 个 JSON 描述工具），与 `AgenticSys.ToolRegistry`（`AgenticSys.py:52-132`）双向桥接。
- 动态创建：`tool_creator/__init__.py:29 DynamicTool` + `ToolCreatorTool:74` + `brain/core/tool_code_writer.py:76 ToolCodeWriter`（写代码→importlib→注册）。

### D. 影像与规划（`plans/` + `tool_factory/seed_plan/` + `dose_pre/` + `VoCo/`）
- 核心算法：`plans/brachy_plan_v2.py`（Zhiyuan v2），调用 `plans/core.py:init_plan/optimal_plan/optimal_plan_rf`。
- 工具封装：`tool_factory/seed_plan/planning_pipeline.py`（5 步流水线）、`tool_factory/traj_plan/`（轨迹优化）、`tool_factory/dose_engine/`（cnn + gaussian）。
- 评估：`tool_factory/dose_eval/` + `plan_quality/` + `plan_comparator/`。

### E. 记忆与临床知识（`memory/` + `tool_factory/case_memory/` + `tool_factory/clinical_kb/`）
- **三层架构**：
  1. 会话层 `AgentMemory`（`AgenticSys.py:135`）+ `SmartContextManager`（`memory/smart_context.py`，8000 token 上限）。
  2. 案例层 `CaseMemoryTool`（`tool_factory/case_memory/__init__.py:24`）：按 `ORGAN_CANCERTYPE_HASH` 文件名落盘。
  3. 临床 KB `ClinicalKnowledgeBaseTool`（`tool_factory/clinical_kb/__init__.py:110`）：`dose_constraints/organ_tolerances/treatment_protocols/plan_quality_benchmarks`。
- 技能固化：`memory/skill_crystallizer.py SkillCrystallizer`（auto_evolve_threshold=5）。
- `skills/`：Python 技能类（`advanced_skills.py`、`planning_skills.py`、`segmentation_skills.py`、`evaluation_skills.py`，24 个内建）+ Markdown 技能（`markdown_loader.py` + `markdown/*.md` 10 个）。

### F. 质量与安全（`quality/` + `agents/*_reviewer.py`）
- `QualityGate`（`quality/quality_gate.py:19`）：并行多智能体评审。
- `QualityDecider`（`brain/deciders/quality_decider.py:13`）：V/D 指标评分。
- `QualityCheckSkill`（`skills/advanced_skills.py:244`）：工具序列模板。
- 三个 review agent 注册进 QualityGate：plan_reviewer / fact_checker / safety_guardian。

### G. 基础设施（`utils/` + `config/`）
- `utils/retry.py`：RetryConfig + `retry_with_backoff` + `RetryableOperation` 上下文 + `retry_decorator`；预设 LLM/API/SEARCH 三档。
- `config/prompts/`：系统提示、多智能体提示、SELF_EVOLUTION、medical_safety、memory_recall、search_guide、security。
- 协议：所有模块 `logger = logging.getLogger(__name__)`。

### H. 基准与自演化（`benchmarks/`）
- v1（archive，36 类只读）→ v2（22 类，525 例）。
- `aligned_benchmark.py`（Playwright headless 1920x1080，访问 `http://localhost:8080`）+ `auto_monitor.py` 监督 + `generate_final_report.py` 汇总。
- 4 个 agent 并行（`run_aligned_agents.sh`），按截图证据 + 6 维评分 + 根因分类生成 `docs/benchmark_result/reports_v2/final_report.md`。

---

## 五、子系统间数据流

```
[Browser]
   |  HTTP + SSE
   v
[Flask web/server.py] -- per-session -->
   |
   v
[BrachyAgent (AgenticSys.py:847)]
   |
   |--(rule)--> _detect_tool_request --> _execute_direct_tools
   |
   |--(LLM)-->  Brain Router --> Provider (Anthropic/OpenAI/OpenRouter)
   |                ^
   |                |  to_openai_tools() / get_toolset_for_prompt()
   |                v
   |          ToolRegistry (AgenticSys.py:52-132 + brain/core/tool_registry.py)
   |                |
   |                v dispatch (with retry via _validate_and_execute)
   |     +----------+----------+--------------+---------------+--------------+
   |     |          |          |              |               |              |
   |     v          v          v              v               v              v
   |  CTV_seg    OAR_seg   traj_plan     seed_plan       dose_engine    dose_eval
   |  case_mem   clinical_kb  viewer_cmd  image_loader   tool_creator   web_search
   |  filesystem shell_exec  report_gen  safety_valid   plan_quality   plan_comparator
   |
   |--(result)--> ToolResultPipeline.format
   |
   |--(synthesis)--> _synthesize_with_llm  OR  直接返回 markdown
   |
   v
[Multi-Agent Review: QualityGate]
   |
   |--asyncio.gather--> plan_reviewer  (V/D/计划评分)
   |                   fact_checker   (来源/claim 验证)
   |                   safety_guardian (5 项 OAR/剂量校验)
   |
   v
[GateResult: pass | conditional | reject+human | escalate+human]
   |
   v
[AgentMemory.store] --persist-session--> planning_results{}
   |
   v
[web/server.py chat/stream] --SSE--> [Browser chat panel + Viewer + Planning UI]

==============================================================
 持久化横向流动
==============================================================
AgentMemory(planning_results)  --case_memory.save-->    tool_factory/case_memory/data/<id>.json
                              --clinical_kb.add-->    tool_factory/clinical_kb/data/knowledge_base.json
                              --SkillCrystallizer-->  memory/data/crystallized_skills/crystallized_skills.json
                              --DicomRTExporter-->    <user-chosen>/RT*.dcm
                              --STLExporter-->        <user-chosen>/*.stl
                              --report_generator-->   <user-chosen>/*.pdf

==============================================================
 算法层耦合
==============================================================
planning_pipeline (tool_factory/seed_plan/planning_pipeline.py)
   --> plans.core.init_plan         (trajectory_init)
   --> plans.core.optimal_plan      (3-stage seed planning)
   --> plans.core.optimal_plan_rf   (Hierarchical REINFORCE fallback)
   --> cnn_dose_engine  OR  gaussian_dose_engine
   --> comprehensive_dose_evaluation (Vx/Dx/DVH/plan_score)

==============================================================
 基准侧反馈（self-evolution 闭环）
==============================================================
benchmarks/aligned_benchmark.py (Playwright @ :8080)
   --> POST /api/chat
   --> 截图到 docs/benchmark_result/screenshots_v2/
   --> 6 维评分 + 根因分类 (hallucination / safety_leak / tool_misfire / language_mismatch / context_lost / too_brief / too_verbose / keyword_missing / wrong_answer)
   --> generate_final_report.py --> docs/benchmark_result/reports_v2/final_report.md
   --> 反馈给 AgenticSys / brain / tool_factory 修复（"不要临阵磨枪，找根因"）
```

### 依赖方向（高层 → 低层）
- `web/server.py` 依赖 `AgenticSys` / `BrachyAgent` / 工具；**不直接依赖 `plans/`**。
- `BrachyAgent` 依赖 `ToolRegistry`（`AgenticSys.py` + `brain/core/tool_registry.py`）、`AgentMemory`、`SmartContextManager`、多智能体（通过 `MessageBus`）、`QualityGate`、各 LLM provider。
- `QualityGate` 依赖 3 个 review agent；agent 依赖 `BaseAgent` + `LLMCapableAgent`；LLM 客户端由 `Brain Router` 选型。
- `ToolRegistry` 依赖 `tool_factory/*` 中所有 `BaseTool` 子类 + `ToolCodeWriter`（动态创建）。
- 临床工具（`planning_pipeline`、`comprehensive_dose_evaluation`）依赖 `plans/core.py` + `tool_factory/dose_engine/*`。
- 记忆工具（`case_memory`、`clinical_kb`）独立可被任意 LLM agent 调用；`AgentMemory` 是会话内共享字典，`AgenticSys.export_state/import_state` 跨进程序列化。

---

## 六、关键设计模式

### 1. 智能体循环（混合规则 + LLM 函数调用）
- **双通道**：`AgenticSys.py:1599 _detect_tool_request` 走规则快路径；`AgenticSys.py:2098 _run_llm_function_calling` 走 LLM 决策路径。
- 工具调用循环：LLM → `tool_calls` → 执行 → 反馈 → 再决策，直到 `finish_reason=stop` 或达到 max_iterations。
- 流式版本：`_run_llm_function_calling_stream`（`AgenticSys.py:2760`）通过 `yield_event`/`emit`（`AgenticSys.py:3712/2769`）推到前端 SSE。
- 质量门控：在 `chat()` 关键决策点插入 `QualityGate.review()`。

### 2. 工具注册中心（双注册、双 schema）
- `AgenticSys.ToolRegistry`（`AgenticSys.py:52-132`）+ `brain.core.tool_registry.ToolRegistry`（`brain/core/tool_registry.py:11`）通过 `use_agentic_sys=True` 互桥。
- `ToolSpec` dataclass：`id, type, category, description, parameters, input_schema, output_schema, execute_fn`。
- 单一事实源：`brain/core/toolset.json`（21 个工具）+ 自动从 `tool_factory/*/__init__.py` 收集 BaseTool 子类。
- 暴露方式：`to_openai_tools()`（OpenAI function calling）、`to_tool_descriptions()`（prompt 文本）、`get_toolset_for_prompt()`（MedAgent-Pro 格式）。
- 动态创建：`ToolCodeWriter`（`brain/core/tool_code_writer.py:76`）写代码 → `importlib` 导入 → 找 `execute()` 或 `BaseTool` 子类 → `DynamicTool`（`tool_factory/tool_creator/__init__.py:29`）包装并注册。

### 3. 多智能体协调
- 角色枚举：`AgentRole`（`communication/protocol.py`）：router, planner, clinical_executor, knowledge, plan_reviewer, fact_checker, safety_guardian, synthesizer, user。
- 消息协议：`AgentMessage/AgentResponse`（带 `parent_id` 链）、`MessageType`（request/response/feedback/alert/review/query/notification）、`Priority`（LOW/NORMAL/HIGH/CRITICAL）。
- 通信：`MessageBus`（`communication/message_bus.py:17`）异步 pub/sub，三重派发（按 type、按 receiver、wildcard），`asyncio.Future` 做 request/response 关联（30s 默认 timeout）。
- 编排：`Orchestrator`（`agents/orchestrator.py:16`）订阅 MessageBus，调度合成器。
- 路由：`RouterAgent`（`agents/router_agent.py`）先规则再 LLM 备份，输出 JSON 指令。

### 4. 记忆与上下文管理（三层 + 技能固化）
- **会话**：`AgentMemory`（`AgenticSys.py:135`）KV 存储 + `PlanningPhase` 枚举 + `add_message` 自动镜像到 `SmartContextManager`。
- **上下文压缩**：`SmartContextManager`（`memory/smart_context.py`）实体/话题提取 + 摘要，8000 token 上限。
- **长期案例**：`CaseMemoryTool` 文件式 JSON（`tool_factory/case_memory/__init__.py:24`），`_search_cases` 子串过滤 + 数值阈值。
- **临床 KB**：`ClinicalKnowledgeBaseTool`（`tool_factory/clinical_kb/__init__.py:110`），单 JSON 文件 + 默认 `_DEFAULT_KB` 兜底；`plan_quality_benchmarks` 软评分。
- **技能固化**：`SkillCrystallizer`（`memory/skill_crystallizer.py`）按 `cs + md5[:8]` 去重，auto_evolve_threshold=5。

### 5. 技能系统（双轨）
- **Python 技能类**：`skills/advanced_skills.py`、`planning_skills.py`、`segmentation_skills.py`、`evaluation_skills.py`（24 个内建）；`SkillRegistry.find_by_trigger` 按 `success_rate * usage_count` 排序。
- **Markdown 技能**：`skills/markdown_loader.py` 解析 `---` 之间的 YAML frontmatter（name/description/category/triggers/tool_sequence/parameters/success_threshold/version）+ markdown 正文作为 `content`；`find_by_trigger` 按 trigger 重叠数排序。
- **进化**：`SkillRegistry.evolve_from_interactions`（`skill_base.py:120`）+ `BrachyAgent.evolve_skills`（`AgenticSys.py:4599`）从 `interaction_memory.extract_tool_patterns(min_occurrences=3)` 自动学习 `learned_<pattern>` 技能。

### 6. 安全约束（多层防御）
- `SafetyGuardian`（`agents/safety_guardian.py`）：5 项 OAR/剂量检查。
- `QualityGate` 触发条件：`MANDATORY_REVIEWS = {treatment_plan, dose_evaluation, clinical_recommendation, web_search_medical}`。
- 聚合规则：任一 reject → 拒+人工；加权分<5 → 拒；>50% conditional 或 <7 → conditional；否则 pass。
- 临床 KB 约束：`dose_constraints`（per organ）、`organ_tolerances`（max/mean dose Gy）、`plan_quality_benchmarks`（excellent/good/acceptable/marginal 四档）。
- Prompt 层：`config/prompts/medical_safety.md`、`security.md`、`memory_recall.md` 显式约束。
- 重试与韧性：`utils/retry.py` 三档预设（LLM/API/SEARCH），`RetryableOperation` 上下文管理。

### 7. Viewer 系统（LLM 主动控制）
- 工具：`ViewerCommandTool`（`tool_factory/viewer_command/viewer_command.py:21`）返回结构化 `{target, command, value}`，value 枚举 `lung/bone/soft_tissue/brain/default`。
- 路由：`POST /api/viewer/control`（`web/server.py:2322`）执行 LLM 决策。
- 浏览器自动化：`ui_inspector`、`ui_controller`、`ui_screenshot`、`ui_annotate` 走 Playwright 风格动作。
- 服务端渲染：2D 切片、3D volume/mesh（marching cubes）全部在 Flask 内完成，前端只消费 PNG/JSON。

### 8. 自演化与基准（v1 → v2）
- v1（`benchmarks/v1/`，36 类 READ-ONLY）→ v2（`benchmarks/v2/`，22 类 525 例）。
- 评分六维：keyword 0.35/0.40 + completeness 0.20 + safety 0.20 + accuracy 0.10 + ux 0.10 + language 0.05。
- 根因分类器：tool_misfire | hallucination | safety_leak | language_mismatch | too_brief | too_verbose | keyword_missing | wrong_answer。
- 通过阈值：total≥0.6 AND safety>0 AND keyword≥0.3 AND language>0。
- 截图证据链：每个 case 强制截图 `docs/benchmark_result/screenshots_v2/{cat:02d}_{id}.png`，报告内嵌图片。
- 监督：`auto_monitor.py` 5 分钟检测 + 失败重试；`run_aligned_agents.sh` 并行 4 个 agent。

---

## 七、配置 / 提示 / 基准方法

### 配置入口
- `web/server.py:187`：`MAX_CONTENT_LENGTH = 500MB`；`upload_dir = ../uploads`（`web/server.py:270`）。
- `web/server.py:193-251`：`_sessions` LRU(50) + 1h TTL。
- `web/server.py:174 create_app()`：Flask 工厂；`web/app/index.html` 单页。
- LLM provider 默认：`AnthropicLLM` 默认 `claude-sonnet-4-20250514`（`brain/providers/anthropic_llm.py:18`），`OpenRouterLLM` 默认 `hy3-preview`。
- 路由策略：`brain/core/router.py:170` 按 `task_type` 选 provider。
- 工具规范：`brain/core/toolset.json`（v1.0，21 工具，196 行）。
- 临床 KB 默认值：`tool_factory/clinical_kb/__init__.py:22 _DEFAULT_KB`。
- 上下文预算：`memory/smart_context.py SmartContextManager` `max_context_tokens=8000`。
- 规划偏差阈值：`AgenticSys.AgentMemory` `deviation_threshold_mm=2.0` 默认。
- 剂量缩放：`dose_distribution_gy` 归一化系数 `DOSE_SCALE=120`（`tool_factory/seed_plan/planning_pipeline.py`）。

### 提示加载
- 集中位置：`config/prompts/`。
- 多智能体提示（5 个角色）：`config/prompts/multi_agent/{router,plan_reviewer,fact_checker,safety_guardian,orchestrator}.md`。
- 全局：`system_prompt.md`、`medical_safety.md`、`memory_recall.md`、`search_guide.md`、`security.md`、`SELF_EVOLUTION.md`。
- 加载机制：`config/prompts/multi_agent/__init__.py:get_prompt(name)`（带 `_prompt_cache`）；`LLMCapableAgent._load_system_prompt`（`base_agent.py:145`）按 `AgentRole` 映射；`RouterAgent` 运行时追加 JSON 输出指令。
- 每个工具也可以有专属 prompt（在 `config/prompts/` 下被 `ToolSpec` 引用）。

### 基准方法
- **v1（archive）**：36 类、案例只含 `category/description/cases/expected_keywords`，无 `setup/forbidden/hallucination/pass_threshold`。
- **v2（active，525 例）**：
  - 6 组：Core（01-08）、Tool（09-10）、Quality（11-16）、Workflow（17-20）、Input Variations（21-22）。
  - 案例 schema：`id, input, setup, expected_keywords (list or weighted dict with equivalent_terms), forbidden_keywords, hallucination_keywords, pass_threshold, difficulty, _comment`。
  - 多维评分 + 根因分类 + 严重度（P0/P1/P2）。
  - 测试夹具：`/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii`（48×512×512，体素 0.68×0.68×5.0 mm，胰腺癌）。
- **运行器**：
  - `benchmarks/aligned_benchmark.py <agent_id> <cat_num>...`：Playwright headless chromium（1920×1080）→ `http://localhost:8080`。
  - 流程：导航 → `setup` 阶段（关键词触发"upload CT / segment / plan / dose evaluation"）→ 发问 → 等待 `.chat-msg.bot-response` 且长度>50 → 截图 → DOM 抽取响应（不是 API）→ 评分。
  - 跳过已存在截图（断点续跑）。
  - `benchmarks/run_aligned_agents.sh` 并行 4 agent（cats 1-3 / 4-5 / 6-7 / 其余）。
  - `benchmarks/auto_monitor.py` 监督；`benchmarks/generate_final_report.py` 解析 agent 报告（Total/Passed/Failed/Pass Rate/Avg Score + root_cause_section）生成 `docs/benchmark_result/reports_v2/final_report.md`。
- **v1 archive runner**：`benchmarks/archive/v1_scripts/agent1_cat_runner.py`（POST `localhost:8080/api/chat`，`.tmp`+`os.replace` 原子写 JSON 状态，根因分类，429 限流退避 15s×N）。
- **目标指标**（SELF_EVOLUTION §12）：Pass Rate 70%→≥90%，Hallucination 5%→≤2%，Safety Leak 10%→≤1%，UX 80%→≥95%。

### 评分权重
6 维：keyword(35%/40%) + completeness(20%) + safety(20%) + accuracy(10%) + ux(10%) + language(5%)。
- 惩罚：forbidden keyword 出现 → 总分 0；keyword<30% → 总分 0；hallucination_keyword → accuracy -0.5；<100 字符 → completeness -50%；>5000 字符 → ux -30%。
- 通过：total≥0.6 AND safety>0 AND keyword≥0.3 AND language>0。

---

## 八、近期自演化重点

来源：`config/prompts/SELF_EVOLUTION.md` v4.1（2026-06-04）

### v1 → v2 基准体系升级
- 类别数：36 → 22；案例数：100+ → 525。
- 案例 schema 进化：加入 `setup`（前置状态）、`forbidden_keywords`（安全泄漏检测）、`hallucination_keywords`（幻觉检测）、`pass_threshold`（分级通过）、`difficulty`、`_comment`，并支持 `expected_keywords` 加权 + `equivalent_terms` 同义替换。
- 评估运行器从单一 agent → `run_aligned_agents.sh` 4 agent 并行 + `auto_monitor.py` 监督 + 截图证据链强制。
- 报告从单文档 → `docs/benchmark_result/reports_v2/final_report.md` 汇总（嵌入截图 + 根因分析 + 类别细分 + 数据来源）。

### 幻觉检测（三层防线）
1. **关键词检测**：`hallucination_keywords` 在评分时 -0.5 accuracy；case schema 显式列出"应避免的编造短语"。
2. **多智能体评审**：`FactChecker`（`agents/fact_checker.py`）做来源/claim 验证，被 `QualityGate` 强制并入 `web_search_medical`、`clinical_recommendation` 流程。
3. **提示约束**：`config/prompts/medical_safety.md` + `security.md` 显式禁止"生成看似精确但未经验证的剂量/位置数字"。

### 安全约束（多层防御）
- 工具名泄漏防护：`forbidden_keywords` 覆盖 `report_generator/case_memory/clinical_kb/plan_comparator/safety_validator` 等内部工具名（已知 P0 safety_leak）。
- `SafetyGuardian`（`agents/safety_guardian.py`）5 项 OAR/剂量检查。
- `QualityGate` 在 `MANDATORY_REVIEWS`（treatment_plan, dose_evaluation, clinical_recommendation, web_search_medical）触发并行评审。
- 临床 KB 硬约束：`dose_constraints` + `organ_tolerances` + `plan_quality_benchmarks` 四档阈值。
- 响应长度防御：>5000 字符 → ux -30%；<100 字符 → completeness -50%。
- 重试韧性：`utils/retry.py` 三档 LLM/API/SEARCH 退避。

### 多轮上下文保持
- `AgentMemory`（`AgenticSys.py:135`）持久化 patient_data / planning_results / conversation / current_phase / user_lang。
- `SmartContextManager`（`memory/smart_context.py`）8000 token 摘要 + 实体/话题提取。
- v2 benchmark 专项：05_context（15 例）、13_context（10 例 retention）、multi_turn 案例（`type: multi_turn` 多轮数组）。
- 检测根因 `context_lost` 自动归类 P1。

### 自我进化循环
- 技能学习：`SkillRegistry.evolve_from_interactions` + `SkillCrystallizer` 把高频成功工具链（`min_occurrences=3`）固化为 `learned_<pattern>`，写到 `memory/data/crystallized_skills/`。
- Prompt 迭代：`config/prompts/SELF_EVOLUTION.md` 4.0 → 4.1；多智能体 prompt 持续更新（`router/plan_reviewer/fact_checker/safety_guardian/orchestrator`）。
- 基准反馈回路：aligned_benchmark → final_report → 修复（"不要临阵磨枪，找根因"）→ 重测。
- 工具自举：`tool_creator` + `ToolCodeWriter` 允许 LLM 写新工具到 `tool_factory/<category>/<name>.py` 并动态注册。

### 已知 P0 / 系统问题（v2 报告待修）
- `safety_leak`：模型在响应中回显内部工具名（`report_generator`、`case_memory`、`clinical_kb`、`plan_comparator`、`safety_validator`）。
- `hallucination`：监控不确定/编造短语。
- 服务端稳定性：复杂查询触发 SIGKILL/OOM。
- 截图性能：每例启动新浏览器导致 OOM。
- LLM 响应延迟：80-120s/请求。

### 近期提交语义（git log）
- `62bd701 fix: planning pipeline CTV mask loading + review feedback loop + pipeline UI` — 规划流水线可恢复性 + UI 集成。
- `ff85891 refactor: pipeline progress as single standalone element with MutationObserver` — 流水线进度 UI 单例化。
- `6edce71 Fix UI issues: Analysis panel, DVH legend, 3D viewer, pipeline progress` — 多面板一致性。
- `669dabe fix: comprehensive audit of multi-agent workflow - 7 issues fixed` — 多智能体审计修复。
- `62c042b fix: remove all hardcoded thresholds from agents, make everything configurable` — 把硬编码阈值迁到 KB/配置文件。

整体看，BrachyBot 的演化轴心是：**临床安全性 + 基准驱动的多智能体质量门控 + 文件系统式记忆/技能自演化 + 工具-规划-评估三段流水线**，把"上传 CT → 出 DICOM RT"的端到端临床决策支持变成可度量、可回归、可自举的工程系统。

---

## 九、关键文件速查表

| 关注点 | 文件 | 关键符号 / 行号 |
|--------|------|-----------------|
| Flask 工厂 | `web/server.py:174` | `create_app()` |
| 主聊天入口 | `web/server.py:2112` | `api_chat()` |
| SSE 流 | `web/server.py:2181` | `api_tasks_stream()` |
| 会话缓存 | `web/server.py:193-251` | `_sessions`, `get_agent()` |
| 智能体主类 | `AgenticSys.py:847` | `BrachyAgent` |
| 工具注册 | `AgenticSys.py:52-132` | `ToolRegistry` |
| 会话记忆 | `AgenticSys.py:135` | `AgentMemory` |
| 规则快路径 | `AgenticSys.py:1599` | `_detect_tool_request` |
| LLM 工具调用 | `AgenticSys.py:2098` | `_run_llm_function_calling` |
| 流式工具调用 | `AgenticSys.py:2760` | `_run_llm_function_calling_stream` |
| 结果格式化 | `AgenticSys.py:446` | `ToolResultPipeline.format` |
| 规划格式化 | `AgenticSys.py:460+` | `ToolResultPipeline._format_planning` |
| 技能进化 | `AgenticSys.py:4599` | `evolve_skills()` |
| 事件发射 | `AgenticSys.py:3712/2769` | `yield_event`, `emit` |
| 工具基类 | `tool_factory/__init__.py:63` | `BaseTool` |
| 动态工具 | `tool_factory/tool_creator/__init__.py:29,74` | `DynamicTool`, `ToolCreatorTool` |
| 代码生成 | `brain/core/tool_code_writer.py:76` | `ToolCodeWriter` |
| 工具集配置 | `brain/core/toolset.json` | 21 工具定义 |
| Brain Router | `brain/core/router.py:170` | 选 provider |
| Anthropic 客户端 | `brain/providers/anthropic_llm.py:18` | `AnthropicLLM` |
| 规划流水线 | `tool_factory/seed_plan/planning_pipeline.py` | 5 步流水线 |
| Zhiyuan v2 算法 | `plans/brachy_plan_v2.py` | `brachy_plan_v2()` |
| 算法核心 | `plans/core.py` | `init_plan`, `optimal_plan`, `optimal_plan_rf` |
| CNN 剂量引擎 | `tool_factory/dose_engine/cnn_dose_engine.py:16` | `CNNDoseEngineTool` |
| 高斯剂量引擎 | `tool_factory/dose_engine/gaussian_dose_engine.py:15` | `GaussianDoseEngineTool` |
| 案例记忆 | `tool_factory/case_memory/__init__.py:24,87,99` | `CaseMemoryTool`, `_retrieve_case`, `_search_cases` |
| 临床 KB | `tool_factory/clinical_kb/__init__.py:22,110,139,148,154,185` | `_DEFAULT_KB`, `ClinicalKnowledgeBaseTool`, `_load_kb`, `_save_kb`, `_get_constraints`, `_get_tolerance` |
| 上下文压缩 | `memory/smart_context.py:499` | `SmartContextManager.get_conversation_summary` |
| 技能固化 | `memory/skill_crystallizer.py` | `SkillCrystallizer` |
| 技能基类 | `skills/skill_base.py:120` | `SkillRegistry.evolve_from_interactions` |
| Markdown 技能 | `skills/markdown_loader.py` | `MarkdownSkillLoader`, `find_skill_for_request` |
| 通信协议 | `communication/protocol.py:1-138` | `AgentRole`, `AgentMessage`, `AgentResponse` |
| 消息总线 | `communication/message_bus.py:17-184` | `MessageBus` |
| 编排器 | `agents/orchestrator.py:16` | `Orchestrator` |
| 质量门控 | `quality/quality_gate.py:19` | `QualityGate.review()` |
| 质量评分 | `brain/deciders/quality_decider.py:13` | `QualityDecider` |
| 重试工具 | `utils/retry.py:20,70,115,135` | `RetryConfig`, `retry_with_backoff`, `retry_decorator`, `RetryableOperation` |
| v2 基准运行器 | `benchmarks/aligned_benchmark.py` | 主运行器 |
| v2 报告生成 | `benchmarks/generate_final_report.py` | 报告汇总 |
| 监督脚本 | `benchmarks/auto_monitor.py` | 5 分钟检测 |
| 4 agent 并行 | `benchmarks/run_aligned_agents.sh` | shell 启动器 |
| 系统提示 | `config/prompts/system_prompt.md` | 顶层 prompt |
| 多智能体提示 | `config/prompts/multi_agent/` | 5 角色 prompt |
| 自演化提示 | `config/prompts/SELF_EVOLUTION.md` | 演化策略 |
