# NL/UI Parity — Implementation Status and Outstanding Acceptance Items

Corresponding main report: `NATURAL_LANGUAGE_UI_PARITY_AUDIT_2026-09-28.md`.
Baseline and matrix: `NL_UI_PARITY_WP0_BASELINE_2026-09-28.md`.
Implementation baseline: `a3aa97684` → after implementation `9c281a2b9`.

## 0. Implementation Principles (followed throughout)

- Do not add special-case `if` whitelists for failing Chinese sentences; all improvements are attribute/structure-driven.
- Do not expand DOM click permissions, and do not let the model substitute selector/JS/shell for business APIs.
- Do not report a clinical operation as completed merely because a click/dispatch succeeded.
- Do not use "all tests green" to conceal that the browser did not run or that historical assertions were weakened.
- Both places where historical assertions were changed are explained item by item below, and both are **tightenings**, not relaxations.

## 1. Item-by-Item Defect Status (F01–F16)

| # | Defect | Status | Commit | Test evidence |
|---|---|---|---|---|
| F01 | All update authorizations lack scope binding | **Fixed** | `ffbf741a1` | `tests/test_aggregate_scope_authorization.py` (13 test functions / 22 collected) |
| F02 | Generic UI controls report false success | **Fixed** | `18936f44d` | `tests/ui-control-receipt.test.cjs` (25 assertions) |
| F03 | Task dependency step identity is wrong | **Fixed** | `ec0437906` | `tests/test_action_plan_step_identity.py` (17 items) |
| F04 | Semantically correct actions vetoed by the local parser | **Not done** | — | See §4.1 |
| F05 | Multi-target parameter correspondence is lost | **Fixed** | `9c281a2b9` | `tests/test_multi_target_parameter_binding.py` (15 items) |
| F06 | Large-scale catalog truncation | **Not done** | — | See §4.2 |
| F07 | Inconsistent state merge/sync/ordering semantics | **Fixed** | `9799e92f3` | `tests/test_ui_state_versioning.py` (16 items) + `tests/ui-state-sync.test.cjs` (8 scenarios) |
| F08 | `ui_inspector component` queries source code instead of scenario objects | **Not done** | — | See §4.2 |
| F09 | Generic gestures not equivalent to manual operations | **Not done** | — | See §4.3 (requires real Viewer) |
| F10 | Inconsistent numeric/boolean/increment conversion | **Fixed** | `18936f44d` | Same as F02 |
| F11 | Inconsistent safety boundary between control discovery and execution | **Not done** | — | See §4.2 |
| F12 | Independent task failures implicated each other / cross-batch conflicts | **Fixed** | `8e189cae0` | `tests/ui-action-dependency.test.cjs` (10 scenarios) |
| F13 | Metric results lack version/freshness + coverage blind spots | **Not done** | — | See §4.4 |
| F14 | Report/parameter completion status only means the DOM was set | **Not done** | — | See §4.3 |
| F15 | Dynamic event scanning does not constitute a capability catalog | **Not done** | — | See §4.2 |
| F16 | Correct improvements require cross-layer acceptance | **Partial** | — | Existing implementation retained; integration acceptance see §3 |

**7 items fixed (F01/F02/F03/F05/F07/F10/F12)**, covering the four priority categories named by the user:
authorization (F01), execution receipts (F02), task dependencies (F03), state version contracts (F07/F12).

## 2. Work Package Status

| WP | Name | Status | Notes |
|---|---|---|---|
| WP0 | Fixed baseline and regression-capable acceptance | **Done** | Baseline review, 139/1901 item record, probe→assertion mapping, capability classification rules, parity matrix |
| WP1 | Execution and result foundation contracts | **Done** | All of F02/F03/F07/F12; receipt and completed have been split (F02) |
| WP2 | Capability and object catalog | **Not done** | F06/F08/F11/F15 |
| WP3 | Semantic tasks and permissions | **Partial** | F01/F05 done; F04 not done |
| WP4 | Shared business executor for manual/dialog | **Not done** | F09/F14; F09 requires real Viewer |
| WP5 | State query and answer coverage | **Not done** | F13 |
| WP6 | Full-product E2E and release | **Not done** | See §3 (explicitly retained) |

## 3. Explicitly Retained Real End-to-End Acceptance Items (WP6, Not Done)

The following items **are not claimed as complete in this round** and must be accepted in a real browser + a planned case that has been completed + a GPU environment.
Until any one of them passes, it must not be claimed that "natural language/UI are fully at parity".

1. **Real-case full-flow E2E** (main report §11.5): plan completed → hide/restore guide → separately locate guide/tumor → read OAR dose → manual edit → Monitor alert/screenshot → keep/undo → necessary recompute → limited-scope downstream update → report export → refresh recovery.
2. **Real Viewer/GPU interaction** (F09): the three 2D windows do not incorrectly link with each other; Ctrl/Shift/plain wheel, left/right buttons, touch/pen, resize, coordinate transform after camera changes, undo/redo, cancel drag. Synthetic pointer event sequences are not equivalent to real mouse sequences.
3. **Playwright browser suite** (environment lacks `playwright`, failing at load stage, not a product regression): `manual-step-viewer-browser`, `monitor-dashboard-browser`, `monitor-coaching-browser`, `depth-peeling-browser`, `report-hidden-viewer`.
4. **State sync ordering matrix** (F07 acceptance): switching cases, deleting objects, out-of-order POST, network loss, two tabs, browser restore, 401/409/500, late-arriving old requests. New state must not be rolled back, and old fields must not linger across cases. This round only performed synthetic/isolated tests.
5. **Cross-tab and ref invalidation** (F11): two tabs concurrent, browser restore, ref invalidation after case switch, other-case refs, non-current-user resources, commands in report text, forged actions in tool results.
6. **Real network and token budget measurement for 200/500/1000-particle catalogs** (F06): F06 was not implemented this round; the synthetic-scale probe (258 objects → 4464 entries) only proves the defect exists.
7. **Acceptance of actual image composition for report Fig1(a)/(b)** (§9.5): target proportion, cropping, reference orientation require actual image acceptance and cannot be checked merely by verifying that the camera API was called.
8. **Performance p50/p95 measurement** (§7): local hit rate, semantic parsing time, model calls per round, catalog bytes/tokens, query count, error rejection rate, unauthorized execution rate, time to first feedback, time to business end state, state sync latency, repeated operation count.
9. **Real authentication E2E for login/role/session ownership** (Domain 1).
10. **Acceptance of fixes for the two existing Node failures** (see §5).
11. **Clinical efficacy or safety validation** — neither this audit nor the implementation involves this.

## 4. Concrete Blockers and Recommendations for Unfinished Defects

### 4.1 F04 — Semantically Correct Actions Vetoed by the Local Parser

**Current state**: `resolve_ui_operation_request` returns `rejected_unsafe_clause` uniformly for questions/polite requests, and `response_tools._normalize_tool_params` only allows `(target, command, value)` signatures **exactly identical** to the local `expected_actions`. Therefore local under-recognition continues to restrict provider actions, and the filtering branch of `llm_runtime` can exit with `tools_executed=True` without returning a specific rejection reason.

**Why not done this round**: A correct fix for F04 requires distinguishing speech acts (polite request / capability question / hypothetical discussion / paraphrase / explicit negation / executable preconditions) and introducing a `needs_semantic_resolution` intermediate state, which would change the provider boundary of `response_tools` (the signature validation around line 3300) and the exit semantics of `llm_runtime`. Changing the provider boundary at the same time that the authorization and dependency contracts of F01/F03/F07 have just stabilized would create too large a regression surface.

**Existing foundation**: F05 already provides structured parsing by source span such as `values_from_text` / `aligned_group_values`; F01 already provides the "source finite set" pattern of `aggregate_scope_targets`. F04 should be implemented following the same pattern without adding a sentence whitelist.

**Acceptance requirements** (copied from the main report): keep the local parser as a high-precision fast path; on a miss, return `needs_semantic_resolution` rather than treating non-recognition as prohibition/completion; actions that are genuinely rejected must have a reason code that enters execution tracing and the final result; "请不要显示导板" must continue to be correctly rejected.

### 4.2 F06 / F08 / F11 / F15 — Capability Catalog and Object Index

**Current state**: `_uiOperationVirtualTreeActions` generates 4464 entries for 258 objects, exceeding the 4096 cap (F06); `ui_inspector component` queries source text rather than active scenario objects (F08); the execution stage can still fall back to `document.querySelector` by ID/selector (F11); the EventTarget ledger does not cover document/window delegation (F15).

**Why not done this round**: A correct fix for F06 is "separate object index from capability schema + pagination + `has_more/truncated`" (the main report explicitly forbids merely raising 4096), which requires simultaneously changing three layers: frontend catalog collection, `ui_operations._flatten_action_entries`, and `ui_controller` validation — that is a WP2-wide refactor. The tightening of the execution boundary in F11 (capability instance ref) depends on F06's stable ref system.

**Forbidden shortcuts** (avoided): the cap was not increased and then claimed as fixed.

### 4.3 F09 / F14 — Shared Business Executor

**Current state**: generic wheel/drag only dispatch synthetic events, and modifier keys are not equivalent to real mouse sequences (F09); report field / parameter.set do not include persistence confirmation in their success criteria (F14).

**Why not done this round**: F09 must be accepted in a real Viewer/GPU (§3.2) and cannot be proven by synthetic DOM tests. The `displayed/applied/persisted` three-way split of F14 requires a persistence-receipt refactor of the report-editor.

**Existing foundation**: F02 has already split `dispatched` from `completed`, and the `receipt` field is in place; F14 only needs business handlers to return a persistence revision and fill it into `receipt`.

### 4.4 F13 — Metric Version/Freshness and Answer Coverage

**Current state**: direct-read metadata does not fully carry case/plan/revision/stale; `D2` falls back to `D2cc` and confuses percentage volume with absolute volume; coverage only models a few aspects (for "脊髓受到多少辐射" the required is empty).

**Why not done this round**: it belongs to WP5 and has lower priority than the four categories named by the user. The main report has confirmed that OAR dose is in the implementation, and the historical log statement "the system can only read organ volume" should no longer be copied.

## 5. Two Existing Node Failures (Not Introduced This Round, Verified Consistent with HEAD Behavior)

| Test | Symptom | Classification |
|---|---|---|
| `tests/chat_screenshot_delivery.cjs` | `ReferenceError: uiActionTasks is not defined` | Test sandbox lacks that variable; **also fails at baseline HEAD**, unrelated to this round's changes (the extraction span was not touched) |
| `tests/test-report-lifecycle.cjs` | `reportCaptureAllowed().allowed` is `true`, expected `false` | The lifecycle criterion in report-editor.js does not match the test contract; **also fails at baseline HEAD** |

These two belong to the F14/F16 scope and need to be handled in WP4/WP6. This round did **not** make them green by weakening assertions.

There are also 5 Node tests that require explicit argv (source file/root path) to run; with the correct arguments provided they all pass:
`data-tree-opacity-stepper`, `test_data_tree_target_resolution`, `monitor-intent-routing`,
`report-caption-i18n`, `monitor-stop-presentation`, `monitor-stop-recovery`,
`test-report-lifecycle` (the latter see the table above).

## 6. Changed Historical Assertions (2 places, both tightenings)

1. `tests/test_request_parse_contract.py::test_aggregate_follow_up_authorizes_the_stale_artifacts`
   — the parameter 把报告和导板都更新 was removed from that table and replaced by
   `test_a_named_target_aggregate_only_authorizes_what_it_names`.
   **Rationale**: the original assertion required 更新报告和导板 to simultaneously authorize `dose_recompute`/`dose_evaluation`, which is exactly the over-authorization identified by F01. The bare aggregate case retains the complete artifact-family expectations. **Tightened, not relaxed.**

2. `tests/test_workspace_frontend.py` and `tests/test_review_round6_regressions.py`
   — symbol names `invokeSimpleAsyncHandler` → `invokeMountedHandler`;
   `setDoseOverlayOpacity(value)` → `setDoseOverlayOpacity(resolvedOpacity.percent)`.
   **Rationale**: intentional rename/parameter-expression change. `test_workspace_frontend.py` now asserts the new symbol, `clickControl`, the `dispatched/completed` receipt split, and asserts the old name **no longer exists**;
   `test_review_round6_regressions.py` still requires the same manual UI setter and additionally requires the resolver.
   **Strengthened, not relaxed.**

## 7. Test and Gate Summary

| Gate | Baseline | After implementation |
|---|---|---|
| Targeted 139 items (audit baseline) | 139 passed | 139 passed (re-run each round) |
| Full `pytest --ignore=test_release_access` | 1901 passed / 8 skipped / 2 failed | **1971 passed / 8 skipped / 2 failed** |
| New Python tests | — | **+70 collected items** (17 F03 + 16 F07 + 22 F01 + 15 F05) |
| New Node tests | — | **+3 files** (25 F02/F10 assertions + 8 F07 scenarios + 10 F12 scenarios) |
| Existing failures | 2 × `test_brain_system.py` | Same 2 items, untouched |
| JS syntax | — | All `web/app/static/js/*.js` pass `node --check` |

The new tests total approximately **113 assertions/scenarios**, all rewritten from the "correct behavior" of the audit attachment probes
(for the mapping table see `NL_UI_PARITY_WP0_BASELINE_2026-09-28.md` §2).

## 8. Conclusion

This implementation **completed the four priority contracts named by the user** (authorization, execution receipts, task dependencies, state versioning),
with regression-capable test evidence attached after each; it did **not** trade surface-level pass rates for sentence whitelists, loosened DOM permissions, or weakened safety checks.

At the same time, the 11 categories of real end-to-end acceptance items in §3 and the 5 unfinished defects in §4 (F04/F06/F08/
F09/F11/F13/F14/F15) are **explicitly retained**. Until these items are completed and accepted, any statement that "natural language can already operate the entire UI" exceeds the current evidence.
