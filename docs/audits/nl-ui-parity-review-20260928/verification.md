# NL/UI parity 修复后复审验证记录

日期：2026-09-28。
远端：`rtx3090_external:/home/lht/snap/brachyplan/BrachyBot`。
HEAD：`a0aaa2cb4467a7762b37620f53749bf700b360c7`。
主报告：`docs/NATURAL_LANGUAGE_UI_PARITY_AUDIT_2026-09-28.md` §0A。

## 源码范围与保护

以远端git archive HEAD加当前已跟踪差异建立新的本地镜像，不使用历史本地工作副本替代最新代码。核验期间未编辑任何生产源码或测试源码。已有9个已跟踪修改均保留：

- tests/monitor-dashboard-browser.test.cjs
- tests/test_monitor_dashboard.py
- web/app/index.html
- web/app/static/css/brachybot-monitor-dashboard.css
- web/app/static/js/brachybot-monitor-dashboard.js
- web/app/static/js/brachybot-monitor-interaction.js
- web/monitor_changes.py
- web/routes/planning_routes.py
- web/server_support.py

既有未跟踪的 `docs/MONITOR_INTERACTION_AUDIT_REMEDIATION_2026-09-28.md` 未覆盖。无commit、reset、服务重启、临床运行或public-release修改。上传前对主报告旧哈希校验，避免覆盖并发修改。

## Python相关回归

远端仓库根目录，使用 `/home/lht/.conda/envs/brachytherapy/bin/python`：

```bash
PYTHONDONTWRITEBYTECODE=1 /home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q -p no:cacheprovider \
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
  tests/test_ui_bridge_sidecar.py \
  tests/test_action_plan_step_identity.py \
  tests/test_ui_state_versioning.py \
  tests/test_aggregate_scope_authorization.py \
  tests/test_multi_target_parameter_binding.py
```

结果：209 passed，3个SWIG deprecation warnings，4.95s。未宣称全仓库通过。

## Node与浏览器

本机新源码镜像根目录，Node v24.14.0：

```powershell
node tests/ui-control-receipt.test.cjs
node tests/ui-state-sync.test.cjs
node tests/ui-action-dependency.test.cjs

$env:NODE_PATH='C:\Users\hunte\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
$env:CHROME_PATH='C:\Program Files\Google\Chrome\Application\chrome.exe'
node tests/manual-step-viewer-browser.test.cjs
node tests/monitor-dashboard-browser.test.cjs
node tests/monitor-coaching-browser.test.cjs
node tests/depth-peeling-browser.test.cjs
node tests/report-hidden-viewer.test.cjs
```

三项契约和五项浏览器脚本均exit0。sync脚本打印offline为预设网络失败模拟，不是脚本失败。浏览器测试是隔离fixture，没有登录在线病例；包含真实WebGL像素读回和状态恢复检查，但不证明全产品端到端对等。

复核已有失败：

```powershell
node tests/chat_screenshot_delivery.cjs
node tests/test-report-lifecycle.cjs web/app/static/js/brachybot-report-editor.js
```

- 第一项：ReferenceError: uiActionTasks is not defined（VM fixture）。
- 第二项：第15行assert，actual true / expected false。
- 未修改源代码、mock或断言以掩盖失败；本次未进一步归因到真实病例行为。

## 新增隔离反例

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /home/lht/.conda/envs/brachytherapy/bin/python docs/audits/nl-ui-parity-review-20260928/review_probes.py
node docs/audits/nl-ui-parity-review-20260928/review_browser_probes.cjs
```

Python运行时首次使用同内容脚本的/tmp副本；模块均从最新仓库导入。Flask使用test_client，缓存、store、timer均为隔离替身，不连接生产服务、不写真实病例。两份JSON保存本次实际观察；其exit0表示采集成功，R01–R07仍是待修缺陷。

后续应将反例转换为正确行为的正式回归断言，尤其要补完整工具→浏览器→保存→依赖→回答的集成，不仅测试新增helper。
