# NL/UI 对等性 — WP0 基线与验收矩阵

对应主报告：`NATURAL_LANGUAGE_UI_PARITY_AUDIT_2026-09-28.md`。
附件：`audits/nl-ui-parity-20260928/`。

## 0. 工作树重新核对（WP0 第一步）

| 项 | 值 |
|---|---|
| 分支 | `codex/session-task-recovery` |
| HEAD | `a3aa976844526195756a36beebc2828b165e9c33` |
| 与审计基线一致 | 是（`a3aa97684`） |
| dirty diff | 仅 `docs/MONITOR_INTERACTION_AUDIT_2026-09-26.md`（+145 行，第二轮复审） |
| untracked | `docs/NATURAL_LANGUAGE_UI_PARITY_AUDIT_2026-09-28.md`、`docs/audits/` |
| 生产源文件 | 与审计基线一致（本次核对未改动任何 `.py/.js/.html/.css/.cjs`） |

Python 环境：`/home/lht/.conda/envs/brachytherapy/bin/python`（3.12）。
Node 环境：`/home/lht/.conda/envs/brachytherapy/bin/node`（v20.17.0）。
测试必须 `env -u BRACHYBOT_API_KEY` 运行。

## 1. 测试基线记录

### 1.1 定向 Python 套件（审计基线 139 项）

```bash
env -u BRACHYBOT_API_KEY /home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_ui_control_snapshot_contract.py \
  tests/test_guide_visibility_contract.py \
  tests/test_intent_decision_contract.py \
  tests/test_intent_shortcut_boundary.py \
  tests/test_semantic_execution_authorization.py \
  tests/test_semantic_decision_budget.py \
  tests/test_answer_coverage.py \
  tests/test_agent_workspace_state.py \
  tests/test_downstream_update.py \
  tests/test_case_question_orchestration.py \
  tests/test_ui_bridge_sidecar.py
```

**2026-09-28 实测：139 passed, 3 SWIG warnings, 5.78 s**（与审计记录一致）。

### 1.2 Node VM 回归（审计基线 2 项）

- `tests/guide-visibility-browser.test.cjs` → passed
- `tests/chat_turn_lifecycle.cjs` → PASS

### 1.3 全量套件基线（本次工作期间使用）

```bash
env -u BRACHYBOT_API_KEY /home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q \
  --ignore=tests/test_release_access.py
```

2026-09-28 实测基线：**1901 passed, 8 skipped, 2 failed**（62 s）；2 项既有失败位于 `tests/test_brain_system.py`（`test_agent_chat_fallback`、`test_brain_agent_connection`），与本次范围无关，修复过程中不得用削弱断言的方式使其变绿。

### 1.4 真实浏览器测试（环境阻断，保留未完成）

以下 3 项在审计环境缺 `playwright` 模块而在加载阶段失败，**不是产品逻辑回归**，本次不改写为通过：

- `tests/manual-step-viewer-browser.test.cjs`
- `tests/monitor-dashboard-browser.test.cjs`
- `tests/monitor-coaching-browser.test.cjs`

需在装有 `playwright` 且有真实 Viewer/GPU 的环境补跑，属于 WP6 未完成项。

## 2. 附件探针 → 正式断言映射

审计探针（`audit_probes.py` / `audit_browser_probes.cjs`）是**基线观察脚本**，不是断言。本工作将其期望行为改写为正式测试，按缺陷归属提交：

| 探针观察项 | 对应缺陷 | 期望断言落点 |
|---|---|---|
| `aggregate_authorization`: 空上下文"全部更新"放行全部 5 个可写工具 | F01 | `tests/test_aggregate_scope_authorization.py` |
| `dependency_order`: `consumer` 先于 `dose_recompute#2` | F03 | `tests/test_action_plan_step_identity.py` |
| `provider_dependencies`: `depends_on`/`key` 被丢弃 | F03 | 同上 |
| `ui_requests`: 礼貌请求/问句被 `rejected_unsafe_clause` | F04 | `tests/test_ui_operation_speech_acts.py` |
| `ui_requests`: "把刚才藏起来的导板恢复一下" 解析为 `null` | F04 | 同上 |
| `ui_requests`: "请不要显示导板" 正确拒绝 | F04（保留） | 同上 |
| `ui_requests`: "CTV 和 OAR 分别 30%/70%" → `ctv,30`+`oar,30` | F05 | `tests/test_multi_target_parameter_binding.py` |
| `coverage`: "脊髓受到多少辐射" required 为空 | F13 | `tests/test_answer_coverage.py` 扩充 |
| `coverage`: "每根针有多少粒子" 只要求 `seed_total` | F13 | 同上 |
| `simple_async_failure_is_discarded` | F02 | `tests/ui-control-receipt.test.cjs` |
| `argument_handler_not_awaited` | F02 | 同上 |
| `numeric_without_bounds_clamped_to_zero` | F10 | 同上 |
| `checkbox_string_false_becomes_true` | F10 | 同上 |
| `independent_batch_stops_after_failure` | F12 | `tests/ui-action-dependency.test.cjs` |
| `relative_opacity_is_absolute` | F10 | `tests/ui-control-receipt.test.cjs` |
| `ctrl_wheel_loses_modifier` / `drag_only_pointer_events` | F09 | **保留未完成**（WP4，需真实 Viewer） |
| `virtual_catalog_capacity`（258 对象 → 4464 条 > 4096 cap） | F06 | `tests/test_ui_catalog_pagination.py` |

## 3. 能力分类规则（WP0 交付）

对 `CONTROL_REGISTRY` 的 111 个 target 与 `index.html` 的 264 个静态控件候选，按下列四类标注。**禁止无理由遗漏**：

| 分类 | 含义 | 处置 |
|---|---|---|
| `capability_id` | 已接业务执行器，具备 receipt/后置条件 | 迁移到统一 schema（WP4） |
| `ui-only` | 纯显示/布局/主题，无临床副作用 | 低风险快路径，仍返回 dispatched 回执 |
| `security-exception` | 破坏性/敏感（密码、删除、导出、清空） | 仅显式 clause-local 授权；generic DOM 不可达 |
| `pending-e2e` | 代码路径存在但需真实 Viewer/GPU/持久化验收 | 不得标为已完成 |

完整逐条分类见 `docs/audits/nl-ui-parity-20260928/capability_registry.csv`（审计快照）+ 本工作新增的 `docs/audits/nl-ui-parity-20260928/capability_classification.csv`（随实施更新）。

## 4. 业务能力对等矩阵（主报告 §5，25 个领域）

标记：**支持** = 手动与对话共用业务执行器且回执一致；**部分** = 有对应代码但缺端到端证明；**缺口** = 已确认契约不足；**待 E2E** = 必须真实操作验证。

| # | 领域 | 状态 | 缺陷 | 测试 ID |
|---|---|---|---|---|
| 1 | 登录与权限 | 待 E2E | — | WP6 |
| 2 | 病例会话 | 部分 | F07 | `test_ui_bridge_sidecar.py`、`test_ui_state_versioning.py` |
| 3 | 文件输入 | 缺口 | F02/F14 | `ui-control-receipt.test.cjs`（browse 仅 dispatched） |
| 4 | 输入模式 | 部分 | F05 | `test_multi_target_parameter_binding.py` |
| 5 | 参数 | 缺口 | F10/F14 | `ui-control-receipt.test.cjs` |
| 6 | 自动分割 | 支持（专用执行器） | F01 | `test_aggregate_scope_authorization.py` |
| 7 | 手工 mask | 部分 | F09 | 待 E2E |
| 8 | Step-by-step | 部分 | F16 | 待 E2E |
| 9 | 整体规划 | 部分 | F12 | `ui-action-dependency.test.cjs` |
| 10 | 下游更新 | 部分 | F01/F03 | `test_aggregate_scope_authorization.py`、`test_action_plan_step_identity.py` |
| 11 | 2D 浏览 | 缺口 | F09 | 待 E2E（WP4） |
| 12 | 2D 测量 | 部分 | F09 | 待 E2E |
| 13 | 3D 浏览 | 部分 | F09 | 待 E2E |
| 14 | Data Tree | 部分 | F06/F11 | `test_ui_catalog_pagination.py`、`test_capability_ref_scope.py` |
| 15 | Data Tree 资源操作 | 缺口 | F11 | `test_capability_ref_scope.py` |
| 16 | 针道编辑 | 部分 | F09/F12 | `ui-action-dependency.test.cjs` |
| 17 | 粒子编辑 | 部分 | F09/F12 | 同上 |
| 18 | 手工重算 | 部分 | F14 | 待 E2E |
| 19 | Analysis/DVH | 部分 | F13 | `test_answer_coverage.py`、`test_metric_provenance.py` |
| 20 | 导板 | 支持（专用路径） | F08 | `test_object_resolver_states.py` |
| 21 | 报告正文 | 部分 | F14 | `ui-control-receipt.test.cjs` |
| 22 | 报告产物 | 部分 | F02/F14 | 同上 |
| 23 | 聊天截图 | 部分 | F16 | 待 E2E |
| 24 | Monitor | 部分 | F12/F16 | 待 E2E |
| 25 | 全局 UI | 支持（ui-only） | — | `test_ui_operation_speech_acts.py` |

**不要用 `111/264` 计算覆盖率**：两者分母含义不同（注册 target vs 静态控件候选）。

## 5. WP6 未完成的真实端到端验收项（明确保留）

以下项目**在本次实施中不宣称完成**，必须在真实浏览器 + 已完成规划病例 + GPU 环境验收：

1. **真实病例全流程 E2E**（主报告 §11.5）：已完成规划 → 隐藏/恢复导板 → 分别定位导板/肿瘤 → 读 OAR 剂量 → 手动编辑 → Monitor 提醒/截图 → keep/undo → 必要重算 → 有限范围下游更新 → 报告导出 → 刷新恢复。
2. **真实 Viewer/GPU 交互**：三个 2D 窗口互不误联动；Ctrl/Shift/普通 wheel、左右键、touch/pen、resize、相机变化后坐标转换、undo/redo、取消 drag（F09）。
3. **Playwright 浏览器套件**：`manual-step-viewer-browser`、`monitor-dashboard-browser`、`monitor-coaching-browser`（缺 playwright 依赖）。
4. **多标签页 / 断网 / 乱序 POST / 401/409/500 / 旧请求迟到**（F07 验收矩阵）。
5. **两标签页并发、浏览器恢复、切病例后 ref 失效**（F07/F11）。
6. **200/500/1000 粒子目录的真实网络与 token 预算测量**（F06；本次只做合成规模）。
7. **报告 Fig1(a)/(b) 实际图片构图验收**（§9.5，不能只检查 camera API 被调用）。
8. **性能 p50/p95 测量**（§7：local hit rate、语义解析耗时、每轮模型调用数、catalog 字节/token 等）。
9. **登录/角色/会话所有权的真实鉴权 E2E**（领域 1）。
10. **临床疗效或安全性验证**——本审计与实施均不涉及。

## 6. 禁止的"修复捷径"（实施约束）

- 为每句失败中文再加一条特殊 if（句子白名单）。
- 将所有问句都视为只读，或将所有动词都视为授权。
- 扩大 `aggregate_command` 使所有 mutating tools 放行。
- 认为返回一份更长工具列表就解决能力发现。
- 让模型任意 selector/JS/shell 执行替代业务 API。
- 在点击/派发成功时汇报临床操作完成。
- 把源码文字搜索结果当作病例对象真相。
- 把未声明覆盖范围的结果视为"已答完"。
- 以"测试全绿"掩盖浏览器未跑、真实 GPU 未跑或历史断言被削弱。
