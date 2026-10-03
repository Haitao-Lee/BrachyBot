# NL/UI Parity Post-Fix Re-Review Verification Record

Date: 2026-09-28.
Remote: `rtx3090_external:/home/lht/snap/brachyplan/BrachyBot`.
HEAD: `a0aaa2cb4467a7762b37620f53749bf700b360c7`.
Main report: `docs/NATURAL_LANGUAGE_UI_PARITY_AUDIT_2026-09-28.md` §0A.

## Source Scope and Protection

A new local mirror was created from the remote `git archive HEAD` plus the currently tracked diff; no historical local working copy was used in place of the latest code. No production or test source was edited during verification. All nine existing tracked changes were retained:

- tests/monitor-dashboard-browser.test.cjs
- tests/test_monitor_dashboard.py
- web/app/index.html
- web/app/static/css/brachybot-monitor-dashboard.css
- web/app/static/js/brachybot-monitor-dashboard.js
- web/app/static/js/brachybot-monitor-interaction.js
- web/monitor_changes.py
- web/routes/planning_routes.py
- web/server_support.py

The pre-existing untracked `docs/MONITOR_INTERACTION_AUDIT_REMEDIATION_2026-09-28.md` was not overwritten. There were no commits, resets, service restarts, clinical runs, or public-release modifications. Before upload, the main report's old hash was verified to avoid overwriting concurrent modifications.

## Python-Related Regression

Remote repository root, using `/home/lht/.conda/envs/brachytherapy/bin/python`:

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

Result: 209 passed, 3 SWIG deprecation warnings, 4.95s. No claim is made that the entire repository passes.

## Node and Browser

Local new-source mirror root, Node v24.14.0:

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

All three contract scripts and the five browser scripts exited 0. The `offline` message printed by the sync script is a preset network-failure simulation, not a script failure. The browser tests are isolated fixtures and do not log in to live cases; they include real WebGL pixel readback and state-recovery checks, but do not prove full-product end-to-end parity.

Re-checking existing failures:

```powershell
node tests/chat_screenshot_delivery.cjs
node tests/test-report-lifecycle.cjs web/app/static/js/brachybot-report-editor.js
```

- First item: `ReferenceError: uiActionTasks is not defined` (VM fixture).
- Second item: assert at line 15, actual true / expected false.
- No source code, mocks, or assertions were modified to conceal the failures; this session did not further attribute them to real-case behavior.

## Added Isolated Counterexamples

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /home/lht/.conda/envs/brachytherapy/bin/python docs/audits/nl-ui-parity-review-20260928/review_probes.py
node docs/audits/nl-ui-parity-review-20260928/review_browser_probes.cjs
```

The Python runtime first used a `/tmp` copy of the script with identical content; all modules were imported from the latest repository. Flask used `test_client`, and the cache, store, and timer were all isolated stand-ins; it did not connect to production services or write to real cases. The two JSON files record the actual observations from this session; their exit 0 means collection succeeded, and R01–R07 remain unfixed defects.

Going forward, the counterexamples should be converted into formal regression assertions of correct behavior, and in particular the full tool→browser→save→dependency→answer integration should be completed, not merely the newly added helpers tested.
