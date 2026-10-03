# NL/UI Parity — WP0 Baseline and Acceptance Matrix

Corresponding main report: `NATURAL_LANGUAGE_UI_PARITY_AUDIT_2026-09-28.md`.
Attachment: `audits/nl-ui-parity-20260928/`.

## 0. Working Tree Recheck (WP0 Step 1)

| Item | Value |
|---|---|
| Branch | `codex/session-task-recovery` |
| HEAD | `a3aa976844526195756a36beebc2828b165e9c33` |
| Consistent with audit baseline | Yes (`a3aa97684`) |
| dirty diff | Only `docs/MONITOR_INTERACTION_AUDIT_2026-09-26.md` (+145 lines, second-pass review) |
| untracked | `docs/NATURAL_LANGUAGE_UI_PARITY_AUDIT_2026-09-28.md`, `docs/audits/` |
| Production source files | Consistent with audit baseline (this recheck changed no `.py/.js/.html/.css/.cjs`) |

Python environment: `/home/lht/.conda/envs/brachytherapy/bin/python` (3.12).
Node environment: `/home/lht/.conda/envs/brachytherapy/bin/node` (v20.17.0).
Tests must be run with `env -u BRACHYBOT_API_KEY`.

## 1. Test Baseline Record

### 1.1 Targeted Python Suite (audit baseline 139 items)

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

**2026-09-28 measured: 139 passed, 3 SWIG warnings, 5.78 s** (consistent with the audit record).

### 1.2 Node VM Regression (audit baseline 2 items)

- `tests/guide-visibility-browser.test.cjs` → passed
- `tests/chat_turn_lifecycle.cjs` → PASS

### 1.3 Full-Suite Baseline (used during this work)

```bash
env -u BRACHYBOT_API_KEY /home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q \
  --ignore=tests/test_release_access.py
```

2026-09-28 measured baseline: **1901 passed, 8 skipped, 2 failed** (62 s); the 2 pre-existing failures are in `tests/test_brain_system.py` (`test_agent_chat_fallback`, `test_brain_agent_connection`), unrelated to this scope; they must not be made green by weakening assertions during the repair.

### 1.4 Real-Browser Tests (environment-blocked, left incomplete)

The following 3 items failed at the load stage because the audit environment lacks the `playwright` module; this is **not a product-logic regression**, and they are not rewritten as passing here:

- `tests/manual-step-viewer-browser.test.cjs`
- `tests/monitor-dashboard-browser.test.cjs`
- `tests/monitor-coaching-browser.test.cjs`

They must be re-run in an environment with `playwright` and a real Viewer/GPU; they are incomplete WP6 items.

## 2. Attachment Probe → Formal Assertion Mapping

The audit probes (`audit_probes.py` / `audit_browser_probes.cjs`) are **baseline observation scripts**, not assertions. This work rewrites their expected behavior as formal tests, submitted by defect ownership:

| Probe observation | Corresponding defect | Expected assertion location |
|---|---|---|
| `aggregate_authorization`: empty-context "update all" allows all 5 writable tools | F01 | `tests/test_aggregate_scope_authorization.py` |
| `dependency_order`: `consumer` before `dose_recompute#2` | F03 | `tests/test_action_plan_step_identity.py` |
| `provider_dependencies`: `depends_on`/`key` discarded | F03 | Same as above |
| `ui_requests`: polite requests/questions rejected as `rejected_unsafe_clause` | F04 | `tests/test_ui_operation_speech_acts.py` |
| `ui_requests`: "把刚才藏起来的导板恢复一下" parses to `null` | F04 | Same as above |
| `ui_requests`: "请不要显示导板" correctly rejected | F04 (retained) | Same as above |
| `ui_requests`: "CTV 和 OAR 分别 30%/70%" → `ctv,30`+`oar,30` | F05 | `tests/test_multi_target_parameter_binding.py` |
| `coverage`: "脊髓受到多少辐射" required is empty | F13 | `tests/test_answer_coverage.py` extended |
| `coverage`: "每根针有多少粒子" only requires `seed_total` | F13 | Same as above |
| `simple_async_failure_is_discarded` | F02 | `tests/ui-control-receipt.test.cjs` |
| `argument_handler_not_awaited` | F02 | Same as above |
| `numeric_without_bounds_clamped_to_zero` | F10 | Same as above |
| `checkbox_string_false_becomes_true` | F10 | Same as above |
| `independent_batch_stops_after_failure` | F12 | `tests/ui-action-dependency.test.cjs` |
| `relative_opacity_is_absolute` | F10 | `tests/ui-control-receipt.test.cjs` |
| `ctrl_wheel_loses_modifier` / `drag_only_pointer_events` | F09 | **Left incomplete** (WP4, needs real Viewer) |
| `virtual_catalog_capacity` (258 objects → 4464 entries > 4096 cap) | F06 | `tests/test_ui_catalog_pagination.py` |

## 3. Capability Classification Rules (WP0 deliverable)

Label the 111 targets in `CONTROL_REGISTRY` and the 264 static-control candidates in `index.html` with the following four categories. **Unjustified omission is forbidden**:

| Category | Meaning | Disposition |
|---|---|---|
| `capability_id` | Wired to a business executor with receipt/postconditions | Migrate to unified schema (WP4) |
| `ui-only` | Pure display/layout/theme, no clinical side effects | Low-risk fast path, still returns a dispatched receipt |
| `security-exception` | Destructive/sensitive (password, delete, export, clear) | Only explicit clause-local authorization; unreachable via generic DOM |
| `pending-e2e` | Code path exists but needs real Viewer/GPU/persistence acceptance | Must not be marked complete |

The complete item-by-item classification is in `docs/audits/nl-ui-parity-20260928/capability_registry.csv` (audit snapshot) + the `docs/audits/nl-ui-parity-20260928/capability_classification.csv` newly added by this work (updated as implementation proceeds).

## 4. Business Capability Parity Matrix (main report §5, 25 domains)

Legend: **Supported** = manual and chat share a business executor and receipts match; **Partial** = corresponding code exists but end-to-end proof is missing; **Gap** = confirmed insufficient contract; **To E2E** = must be verified by real operation.

| # | Domain | Status | Defect | Test ID |
|---|---|---|---|---|
| 1 | Login and permissions | To E2E | — | WP6 |
| 2 | Case session | Partial | F07 | `test_ui_bridge_sidecar.py`, `test_ui_state_versioning.py` |
| 3 | File input | Gap | F02/F14 | `ui-control-receipt.test.cjs` (browse only dispatched) |
| 4 | Input mode | Partial | F05 | `test_multi_target_parameter_binding.py` |
| 5 | Parameters | Gap | F10/F14 | `ui-control-receipt.test.cjs` |
| 6 | Auto-segmentation | Supported (dedicated executor) | F01 | `test_aggregate_scope_authorization.py` |
| 7 | Manual mask | Partial | F09 | To E2E |
| 8 | Step-by-step | Partial | F16 | To E2E |
| 9 | Whole planning | Partial | F12 | `ui-action-dependency.test.cjs` |
| 10 | Downstream update | Partial | F01/F03 | `test_aggregate_scope_authorization.py`, `test_action_plan_step_identity.py` |
| 11 | 2D browsing | Gap | F09 | To E2E (WP4) |
| 12 | 2D measurement | Partial | F09 | To E2E |
| 13 | 3D browsing | Partial | F09 | To E2E |
| 14 | Data Tree | Partial | F06/F11 | `test_ui_catalog_pagination.py`, `test_capability_ref_scope.py` |
| 15 | Data Tree resource operations | Gap | F11 | `test_capability_ref_scope.py` |
| 16 | Needle-track editing | Partial | F09/F12 | `ui-action-dependency.test.cjs` |
| 17 | Seed editing | Partial | F09/F12 | Same as above |
| 18 | Manual recomputation | Partial | F14 | To E2E |
| 19 | Analysis/DVH | Partial | F13 | `test_answer_coverage.py`, `test_metric_provenance.py` |
| 20 | Guide | Supported (dedicated path) | F08 | `test_object_resolver_states.py` |
| 21 | Report body | Partial | F14 | `ui-control-receipt.test.cjs` |
| 22 | Report artifacts | Partial | F02/F14 | Same as above |
| 23 | Chat screenshot | Partial | F16 | To E2E |
| 24 | Monitor | Partial | F12/F16 | To E2E |
| 25 | Global UI | Supported (ui-only) | — | `test_ui_operation_speech_acts.py` |

**Do not compute coverage using `111/264`**: the two denominators have different meanings (registered targets vs static-control candidates).

## 5. Incomplete Real End-to-End Acceptance Items for WP6 (explicitly retained)

The following items are **not claimed complete in this implementation**; they must be accepted in a real browser + a case with completed planning + a GPU environment:

1. **Full real-case workflow E2E** (main report §11.5): completed planning → hide/restore guide → separately localize guide/tumor → read OAR dose → manual edit → Monitor alert/screenshot → keep/undo → necessary recomputation → limited-scope downstream update → report export → refresh restore.
2. **Real Viewer/GPU interaction**: the three 2D windows do not mis-link with each other; Ctrl/Shift/plain wheel, left/right buttons, touch/pen, resize, coordinate transform after camera change, undo/redo, cancel drag (F09).
3. **Playwright browser suite**: `manual-step-viewer-browser`, `monitor-dashboard-browser`, `monitor-coaching-browser` (missing `playwright` dependency).
4. **Multiple tabs / network loss / out-of-order POST / 401/409/500 / late stale requests** (F07 acceptance matrix).
5. **Two-tab concurrency, browser recovery, ref invalidation after case switch** (F07/F11).
6. **Real network and token budget measurement for 200/500/1000 seed catalogs** (F06; this work only did synthetic scale).
7. **Acceptance of the actual image composition of report Fig1(a)/(b)** (§9.5; cannot just check that the camera API was called).
8. **Performance p50/p95 measurement** (§7: local hit rate, semantic parsing latency, model calls per turn, catalog bytes/tokens, etc.).
9. **Real authentication E2E for login/role/session ownership** (domain 1).
10. **Clinical efficacy or safety validation** — neither this audit nor the implementation covers it.

## 6. Forbidden "Repair Shortcuts" (implementation constraints)

- Adding another special `if` for each failing Chinese sentence (a sentence whitelist).
- Treating all questions as read-only, or all verbs as authorization.
- Widening `aggregate_command` so that all mutating tools are allowed.
- Assuming that returning a longer tool list solves capability discovery.
- Letting arbitrary model selector/JS/shell execution replace business APIs.
- Reporting a clinical operation as complete when the click/dispatch succeeded.
- Treating source-text search results as the truth about case objects.
- Treating a result with undeclared coverage as "fully answered".
- Using "all tests green" to mask that the browser was not run, the real GPU was not run, or historical assertions were weakened.
