# NL/UI 对等性 — 实施状态与未完成验收项

对应主报告：`NATURAL_LANGUAGE_UI_PARITY_AUDIT_2026-09-28.md`。
基线与矩阵：`NL_UI_PARITY_WP0_BASELINE_2026-09-28.md`。
实施基线：`a3aa97684` → 实施后 `9c281a2b9`。

## 0. 实施原则（全程遵守）

- 不为失败中文句子添加特殊 if 白名单；改进全部是属性/结构驱动。
- 不扩大 DOM 点击权限、不让模型以 selector/JS/shell 代替业务 API。
- 不在点击/派发成功时汇报临床操作完成。
- 不以"测试全绿"掩盖浏览器未跑或历史断言被削弱。
- 历史断言被改动的两处均在下文逐条说明理由，且都是**收紧**而非放松。

## 1. 缺陷逐项状态（F01–F16）

| # | 缺陷 | 状态 | 提交 | 测试证据 |
|---|---|---|---|---|
| F01 | 全部更新授权缺作用域绑定 | **已修复** | `ffbf741a1` | `tests/test_aggregate_scope_authorization.py`（22 项） |
| F02 | 通用 UI 控件假成功 | **已修复** | `18936f44d` | `tests/ui-control-receipt.test.cjs`（25 断言） |
| F03 | 任务依赖 step 身份错误 | **已修复** | `ec0437906` | `tests/test_action_plan_step_identity.py`（17 项） |
| F04 | 语义正确动作被本地解析器否决 | **未完成** | — | 见 §4.1 |
| F05 | 多目标参数对应关系丢失 | **已修复** | `9c281a2b9` | `tests/test_multi_target_parameter_binding.py`（15 项） |
| F06 | catalog 大规模截断 | **未完成** | — | 见 §4.2 |
| F07 | 状态合并/同步/时序语义不统一 | **已修复** | `9799e92f3` | `tests/test_ui_state_versioning.py`（16 项）+ `tests/ui-state-sync.test.cjs`（8 场景） |
| F08 | `ui_inspector component` 查源码不查场景对象 | **未完成** | — | 见 §4.2 |
| F09 | 通用手势不等价手工操作 | **未完成** | — | 见 §4.3（需真实 Viewer） |
| F10 | 数值/布尔/增量转换不一致 | **已修复** | `18936f44d` | 同 F02 |
| F11 | 控件发现与执行安全边界不一致 | **未完成** | — | 见 §4.2 |
| F12 | 独立任务失败连坐 / 跨批冲突 | **已修复** | `8e189cae0` | `tests/ui-action-dependency.test.cjs`（10 场景） |
| F13 | 指标结果缺版本/新鲜度 + 覆盖盲区 | **未完成** | — | 见 §4.4 |
| F14 | 报告/参数完成状态仅代表 DOM 已设置 | **未完成** | — | 见 §4.3 |
| F15 | 动态事件扫描不构成能力目录 | **未完成** | — | 见 §4.2 |
| F16 | 正确改进需跨层验收 | **部分** | — | 已有实现保留；集成验收见 §3 |

**已修复 7 项（F01/F02/F03/F05/F07/F10/F12）**，覆盖用户点名的四类优先项：
授权（F01）、执行回执（F02）、任务依赖（F03）、状态版本契约（F07/F12）。

## 2. 工作包状态

| WP | 名称 | 状态 | 说明 |
|---|---|---|---|
| WP0 | 固定基线与可回归验收 | **完成** | 基线复核、139/1901 项记录、探针→断言映射、能力分类规则、对等矩阵 |
| WP1 | 执行与结果基础契约 | **完成** | F02/F03/F07/F12 全部；receipt 与 completed 已拆分（F02） |
| WP2 | 能力与对象目录 | **未完成** | F06/F08/F11/F15 |
| WP3 | 语义任务与权限 | **部分** | F01/F05 完成；F04 未完成 |
| WP4 | 手动/对话共用业务执行器 | **未完成** | F09/F14；F09 需真实 Viewer |
| WP5 | 状态查询与回答覆盖 | **未完成** | F13 |
| WP6 | 全产品 E2E 与发布 | **未完成** | 见 §3（明确保留） |

## 3. 明确保留的真实端到端验收项（WP6，未完成）

以下项目**本次不宣称完成**，必须在真实浏览器 + 已完成规划病例 + GPU 环境验收。
任何一项未通过前，不得宣称"自然语言/UI 已完全对等"。

1. **真实病例全流程 E2E**（主报告 §11.5）：已完成规划 → 隐藏/恢复导板 → 分别定位导板/肿瘤 → 读 OAR 剂量 → 手动编辑 → Monitor 提醒/截图 → keep/undo → 必要重算 → 有限范围下游更新 → 报告导出 → 刷新恢复。
2. **真实 Viewer/GPU 交互**（F09）：三个 2D 窗口互不误联动；Ctrl/Shift/普通 wheel、左右键、touch/pen、resize、相机变化后坐标转换、undo/redo、取消 drag。合成 pointer 事件序列不等于真实鼠标序列。
3. **Playwright 浏览器套件**（环境缺 `playwright`，加载阶段失败，非产品回归）：`manual-step-viewer-browser`、`monitor-dashboard-browser`、`monitor-coaching-browser`、`depth-peeling-browser`、`report-hidden-viewer`。
4. **状态同步时序矩阵**（F07 验收）：切病例、删除对象、乱序 POST、断网、两标签页、浏览器恢复、401/409/500、旧请求迟到。不可回滚新状态，也不能跨病例留旧字段。本次仅做了合成/隔离测试。
5. **跨标签页与 ref 失效**（F11）：两标签页并发、浏览器恢复、切病例后 ref 失效、其他病例 ref、非当前用户资源、报告文本中的命令、工具结果中的伪造 action。
6. **200/500/1000 粒子目录的真实网络与 token 预算测量**（F06）：本次未实现 F06，合成规模探针（258 对象 → 4464 条目）仅证明缺陷存在。
7. **报告 Fig1(a)/(b) 实际图片构图验收**（§9.5）：目标占比、裁切、参照方向需实际图片验收，不能只检查 camera API 被调用。
8. **性能 p50/p95 测量**（§7）：local hit rate、语义解析耗时、每轮模型调用数、catalog 字节/token、查询次数、错误拒绝率、未授权执行率、首反馈时间、业务终态时间、状态同步延迟、重复操作次数。
9. **登录/角色/会话所有权的真实鉴权 E2E**（领域 1）。
10. **两个既有 Node 失败的修复验收**（见 §5）。
11. **临床疗效或安全性验证**——本审计与实施均不涉及。

## 4. 未完成缺陷的具体阻塞与建议

### 4.1 F04 — 语义正确动作被本地解析器否决

**现状**：`resolve_ui_operation_request` 对问句/礼貌请求统一返回
`rejected_unsafe_clause`，`response_tools._normalize_tool_params` 只允许与本地
`expected_actions` **完全相同**的 `(target, command, value)` 签名，因此本地漏识别会
继续限制 provider action，且 `llm_runtime` 的过滤分支可 `tools_executed=True`
退出而不返回具体拒绝原因。

**为何本轮未做**：F04 的正确修复要求区分言语行为（礼貌请求 / 能力问句 / 假设讨论 /
转述 / 明确否定 / 可执行前置条件）并引入 `needs_semantic_resolution` 中间态，这会改动
`response_tools` 的 provider 边界（约 3300 行处的签名校验）与 `llm_runtime` 的退出语义。
在 F01/F03/F07 的授权与依赖契约刚稳定时同时改动 provider 边界，回归面过大。

**已具备的基础**：F05 已提供 `values_from_text` / `aligned_group_values` 这类按来源
跨度的结构化解析；F01 已提供 `aggregate_scope_targets` 的"来源有限集合"模式。F04 应沿
同一模式实现，不新增句子白名单。

**验收要求**（照抄主报告）：本地 parser 保留为高精度快路径；未命中返回
`needs_semantic_resolution` 而不是把未识别视为禁止/完成；真正拒绝的动作必须有
reason code，进入执行追踪与最终结果；"请不要显示导板"必须继续正确拒绝。

### 4.2 F06 / F08 / F11 / F15 — 能力目录与对象索引

**现状**：`_uiOperationVirtualTreeActions` 对 258 个对象生成 4464 条目，超过 4096
cap（F06）；`ui_inspector component` 查源码文本而非活动场景对象（F08）；执行阶段仍可
按 ID/selector fallback 使用 `document.querySelector`（F11）；EventTarget ledger 不覆盖
document/window 委托（F15）。

**为何本轮未做**：F06 的正确修复是"对象索引与能力 schema 分离 + 分页 +
`has_more/truncated`"（主报告明确禁止只把 4096 改大），这需要同时改动前端 catalog 采集、
`ui_operations._flatten_action_entries`、`ui_controller` 校验三层，属于 WP2 整体重构。
F11 的执行边界收紧（capability instance ref）依赖 F06 的稳定 ref 体系。

**禁止的捷径**（已避免）：未把 cap 调大后宣称已修复。

### 4.3 F09 / F14 — 共用业务执行器

**现状**：通用 wheel/drag 只派发合成事件，修饰键与真实鼠标序列不等价（F09）；
report field / parameter.set 未把持久化确认纳入成功判据（F14）。

**为何本轮未做**：F09 必须在真实 Viewer/GPU 验收（§3.2），合成 DOM 测试无法证明。
F14 的 `displayed/applied/persisted` 三分需要 report-editor 的持久化回执改造。

**已具备的基础**：F02 已把 `dispatched` 与 `completed` 拆分，`receipt` 字段已就位，
F14 只需在业务 handler 上返回持久化 revision 并填入 `receipt`。

### 4.4 F13 — 指标版本/新鲜度与回答覆盖

**现状**：direct-read metadata 不完整携带 case/plan/revision/stale；`D2` 对 `D2cc`
fallback 混淆百分比体积与绝对体积；coverage 只模型化少量方面（"脊髓受到多少辐射"
required 为空）。

**为何本轮未做**：属 WP5，优先级低于用户点名的四类。主报告已确认 OAR 剂量在实现中，
不应继续照搬历史日志说"系统只能读取器官体积"。

## 5. 两个既有 Node 失败（非本次引入，已核对与 HEAD 行为一致）

| 测试 | 现象 | 定性 |
|---|---|---|
| `tests/chat_screenshot_delivery.cjs` | `ReferenceError: uiActionTasks is not defined` | 测试 sandbox 缺该变量；**基线 HEAD 同样失败**，与本次改动无关（提取 span 未被触碰） |
| `tests/test-report-lifecycle.cjs` | `reportCaptureAllowed().allowed` 为 `true`，期望 `false` | report-editor.js 生命周期判据与测试契约不符；**基线 HEAD 同样失败** |

这两项属于 F14/F16 范围，需在 WP4/WP6 处理。本次**未通过削弱断言**使其变绿。

另有 5 项 Node 测试需要显式 argv（源文件/根路径）才能运行，给出正确参数后全部通过：
`data-tree-opacity-stepper`、`test_data_tree_target_resolution`、`monitor-intent-routing`、
`report-caption-i18n`、`monitor-stop-presentation`、`monitor-stop-recovery`、
`test-report-lifecycle`（后者见上表）。

## 6. 被改动的历史断言（2 处，均为收紧）

1. `tests/test_request_parse_contract.py::test_aggregate_follow_up_authorizes_the_stale_artifacts`
   — 参数 `把报告和导板都更新` 移出该表，另立
   `test_a_named_target_aggregate_only_authorizes_what_it_names`。
   **理由**：原断言要求"更新报告和导板"同时授权 `dose_recompute`/`dose_evaluation`，
   正是 F01 指认的越权。裸聚合用例保留完整的 artifact-family 期望。**收紧，未放松。**

2. `tests/test_workspace_frontend.py` 与 `tests/test_review_round6_regressions.py`
   — 符号名 `invokeSimpleAsyncHandler` → `invokeMountedHandler`；
   `setDoseOverlayOpacity(value)` → `setDoseOverlayOpacity(resolvedOpacity.percent)`。
   **理由**：有意重命名/参数表达式变更。`test_workspace_frontend.py` 现在断言新符号、
   `clickControl`、`dispatched/completed` 回执拆分，并断言旧名**已不存在**；
   `test_review_round6_regressions.py` 仍要求同样的手动 UI setter，并额外要求 resolver。
   **加强，未放松。**

## 7. 测试与门禁汇总

| 门禁 | 基线 | 实施后 |
|---|---|---|
| 定向 139 项（审计基线） | 139 passed | 139 passed（每轮复跑） |
| 全量 `pytest --ignore=test_release_access` | 1901 passed / 8 skipped / 2 failed | **1971 passed / 8 skipped / 2 failed** |
| 新增 Python 测试 | — | **+70**（17 F03 + 16 F07 + 22 F01 + 15 F05） |
| 新增 Node 测试 | — | **+3 文件**（25 F02/F10 断言 + 8 F07 场景 + 10 F12 场景） |
| 既有失败 | 2 × `test_brain_system.py` | 同 2 项，未触碰 |
| JS 语法 | — | 全部 `web/app/static/js/*.js` 通过 `node --check` |

新增测试合计约 **113 个断言/场景**，全部由审计附件探针的"正确行为"改写而来
（映射表见 `NL_UI_PARITY_WP0_BASELINE_2026-09-28.md` §2）。

## 8. 结论

本次实施**完成了用户点名的四类优先契约**（授权、执行回执、任务依赖、状态版本），
并在每项后附带可回归的测试证据；**没有**通过句子白名单、放开 DOM 权限或削弱安全检查
换取表面通过率。

同时**明确保留** §3 的 11 类真实端到端验收项与 §4 的 5 个未完成缺陷（F04/F06/F08/
F09/F11/F13/F14/F15）。在这些项目完成并验收前，任何"自然语言已能操作全部 UI"的表述
都超出当前证据。
