# BrachyBot Natural Language–Frontend Interaction Full-Chain Parity Audit and Implementation Handoff

Date: 2026-09-28  
Audit target: the current LAN working tree of `/home/lht/snap/brachyplan/BrachyBot`  
Initial-review baseline: `a3aa976844526195756a36beebc2828b165e9c33`

Post-fix re-review: 2026-09-28, HEAD `a0aaa2cb4467a7762b37620f53749bf700b360c7`, including the current 9 tracked Monitor workspace modifications.

Deliverable nature: code audit, isolated probes, implementation design, and acceptance plan; **this pass does not modify business code, does not restart services, and does not execute clinical planning or modify patient data.**

## 0A. Post-Fix Re-Review — Current Implementation Status Is Governed by This Section

**There are valid fixes, but "7 items fixed, WP1 complete" cannot be equated with the seven underlying contracts being closed. Most original samples now pass; newly added probes still reproduce authorization loosening, false completion, wrong dependencies, wrong parameter binding, and state regression.**

This pass verifies against `NL_UI_PARITY_IMPLEMENTATION_STATUS_2026-09-28.md`, the fix commits, and the latest working tree. Sections §0–§11 below retain the initial-review evidence and design rationale; **the original reproductions and old line numbers do not represent the current state**; this section supersedes the old conclusions. Existing fixes and tests should be retained and cannot be torn down because residual gaps were found. This pass only updates the report and audit attachments; it does not modify business code, restart 8080, run planning, modify patient data, or touch public-release.

### 0A.1 Item-by-Item Reconciliation Table

| ID | Current judgment | Verified improvements / still to complete |
|---|---|---|
| F01 | **Partially fixed, P0 authorization gap remains** | Bare "update all" no longer lets through CTV/OAR/new planning; mixed condition/reference/question can still let through CTV. With no source, it still defaults to dose, report, and guide. See R01. |
| F02 | **Partially fixed, P0 false completion remains** | Synchronous/asynchronous failures and simple literal-parameter handlers are now handled correctly; JobRef and explicit completed:false are still upgraded to complete, and outer progress is not connected to the terminal state. See R02. |
| F03 | **Partially fixed, P0 dependency gap remains** | Original step key, duplicate-tool, and provider-dependency tests pass; graph merging can bind a forward reference to the wrong producer, and validate has not become a mandatory pre-execution gate. See R03. |
| F04 | **Not closed** | Local parsing and expected action signatures still restrict semantic actions; polite requests/referential questions cannot be solved by adding to an allowlist. |
| F05 | **Partially fixed** | Numeric binding such as 30%/70% respectively passes; textual value ordering and duplicate values are still wrong. See R04. |
| F06 | **Directory contract not fixed** | The catalog 4096 truncation remains; object indexing, capability schema, and discoverable pagination are incomplete; the initial-review 258-node scale evidence is retained and does not claim this pass read a real case. |
| F07 | **Partially fixed, end-to-end state inconsistent** | AgentMemory replace/patch/tombstone, same-browser sequencing, and HTTP failure checks pass; cold-session out-of-order, bucket deletion markers, planning versions, and persistence still have gaps. See R05. |
| F08 | **Query semantics not fixed** | component still queries source-code components, not the current guide/mesh resource resolver; the state branch already has live content, so one should not say the entire tool has no state. |
| F09 | **Gesture parity not complete** | Generic wheel/drag and real MPR are still different paths; viewport/coordinates/modifier keys are not uniformly fed into business commands. |
| F10 | **Original three cases fixed, boundary not closed** | Empty min/max, string false, and relative opacity on a normal current value pass; a missing overlay object causes null→0 to mask a valid fallback. See R06. |
| F11 | **Permission and disambiguation not closed** | Execution still has ID/selector fallback; collection-time filtering is not equivalent to execution-time uniqueness, freshness, and permission validation. No sensitive-control attack testing was performed. |
| F12 | **Partially fixed** | Independent-failure isolation within a batch, pre-blocking on failure within a batch, and per-session batch serialization pass; cross-batch dependencies, unknown preconditions, and cancellation still have gaps. See R07. |
| F13 | **Evidence contract not closed** | Active planning and OAR data capabilities already exist; D2/D2cc fallback, version/freshness, and required outputs still cannot be reconciled. It is not "only able to query organ volumes." |
| F14 | **Persistence receipt not closed** | The DOM applied state of parameter/report fields still differs from workspace persisted; a global saved postcondition is missing. |
| F15 | **Explicit capability catalog not complete** | Element listener scanning is a patch; it cannot cover all delegated events and business semantics; no heap profile was done this pass. |
| F16 | **Browser verification expanded, real-case E2E still to be verified** | All 5 Chrome/Playwright scripts passed this pass; fixture/WebGL success does not mean natural language → real business → save → reload has passed across the whole product. |

"Partially fixed" takes the complete contract of the original defect as its scope and does not mean the corresponding commits are invalid. The parts of `ffbf741a1 / ec0437906 / 18936f44d / 9799e92f3 / 9c281a2b9 / 8e189cae0` that already work correctly should be retained.

### 0A.2 Newly Added Reproductions, Root Causes, and Reasonable Fix Boundaries

S = latest source verification; P = isolated production-function/Flask test-client probe. P is not an online patient-case operation and does not infer that a user actually encountered every boundary.

#### R01｜P0｜aggregate bypasses conditional/reference/question attributes (F01, S/P)

Location: `aggregate_scope_targets` at `agent_runtime/request_parse.py:1299`, and the final aggregate authorization branch at `:1416`.

Calling `mutating_execution_authorized(message, 'ctv_segmentation')` with no historical context:

| Request | Actual result | Correct boundary |
|---|---|---|
| 全部更新 | false | The original bare-aggregate mis-authorization has been fixed |
| 全部更新；如果以后需要，重新分割CTV。 | **true** | A conditional future segmentation must not authorize |
| 全部更新；他说“重新分割CTV”。 | **true** | A quotation must not authorize |
| 全部更新，CTV分割了吗？ | **true** | A status question must not authorize |

The ordinary authorization loop filters conditional/quoted/attributed/interrogative/ambiguous, but the aggregate scope excludes only excluded/negated, collects targets from other clauses, and authorizes again, bypassing the ordinary loop. This evidence proves the underlying defense has a hole; **it does not prove that a real upper-layer request necessarily starts segmentation**.

Additional S-level gap: with no source it falls back to dose/report/surgical_guide; count reference is sliced by target category, does not verify that a sufficient number of real pending items exists, and does not bind the case/plan revision of a structured offer. The default product family cannot be called a sourced scope.

Fix direction: scope may only come from affirmatively executable subtasks, valid pending items, or the current explicitly stale product set; source, exclusions, and risk validation are completed within the same authorization contract. With no explicit source, first do read-only parsing/clarification; do not borrow targets from conditions or quotations; this is not a blanket disabling of aggregate.

#### R02｜P0｜JobRef/dispatch success is still treated as business completion (F02, S/P)

Location: handlerCompleted at `brachybot-ui-api.js:2869`, `_executeUIActionsWithProgress` at `:7302`; `tool_factory/ui_controller/__init__.py:1195`.

- The handler returns `{success:true,completed:false,status:'running',job_id:'job-1'}`, yet the outer result is **completed:true** while the inner receipt is still false.
- The progress executor receives `{success:true,completed:false,dispatched:true}` and still emits **pending→done**.
- The backend `executed=len(validated)` is assigned before browser execution; "executed" does not constitute business evidence.

Root cause: `success===true || receipt!=null || job_id!=null` is used as the completion test; the outer layer mainly checks success/stale and does not understand the real terminal state. Adding a receipt field does not mean the receipt chain is connected.

Fix direction: unify accepted/dispatched/running/waiting_user/completed/failed/cancelled; JobRef only proves receipt, and completion depends on the business terminal state and the necessary persisted revision. Progress, dependencies, and the final answer consume the same ledger, and false completion is not masked by changing wording or fixed wait seconds.

#### R03｜P0｜Forward-dependency mapping error on merge, validation not wired into the execution gate (F03, S/P)

Location: merge at `agent_runtime/action_plan.py:200`, validate at `:274`; the ordering entry point at `agent_runtime/llm_runtime.py:1086`.

There is an existing old producer A; the new graph lists consumer C first (depending on new A), then lists new producer A. The merge renames new A to dose_recompute#2 but leaves C→old A; the order becomes **old A→C→new A**, and validate is still empty. A single pass that builds key_map while processing edges cannot correctly remap forward references.

S-level verification: ActionPlan's validate/is_valid has not yet become a mandatory check at the LLM ordering/execution entry; ordered_steps retaining exceptional-graph steps for enumeration does not equal permitting execution of an exceptional graph. A newly added validation unit test cannot replace a production call.

Fix direction: first assign unique IDs to the entire subgraph, then rewrite all dependency edges (including placeholders); reject unclear duplicate names. Validate at generation, merge, recovery, and before execution; consumers wait for the exact producer's success receipt and matching version. Separate the enumeration-tolerance API from the execution API.

#### R04｜P1｜Textual values bound by pattern order, duplicate values lost (F05, S/P)

Location: values_from_text at `agent_runtime/ui_operations.py:111`.

- “CTV和OAR分别设为不透明和半透明” actually produces ctv,50 and oar,100, but should be 100 and 50.
- “CTV和OAR分别设为半透明和半透明” extracts only [50], returning ambiguous with no action.

Cause: each pattern does only one re.search, losing the original text position and repeated occurrences; the numeric-branch fix by text order is effective.

Fix direction: uniformly extract numbers/text/colors as typed values carrying a source span, retain repeated occurrences, then bind by subtask and the "respectively" relation. Add a retention set covering Chinese/English reverse order, duplicate values, mixed types, local negation, and multiple leaves in the same group, rather than word-by-word patches.

#### R05｜P1｜No sequence protection for cold sessions, bucket and in-memory deletion semantics diverge (F07, S/P)

Location: set_ui_state at `agent_runtime/core.py:616`; the `/api/ui/state` POST and checkpoint_ui_bridge in `planning_routes.py`; `brachybot-ui-api.js:2157`.

Isolated Flask route, in-memory store, and empty timer reproduce:

1. Cold Agent: the same browser first writes seq9, then writes seq4; both return 200/accepted, and the final value becomes the old one. Sequence validation depends on a cached Agent, and the bucket is not independently checked.
2. Hot Agent: patch+tombstones delete the deleted field and return 200; AgentMemory has deleted it, but the bucket and state_keys still retain deleted:'old', so the read/persisted fact differs from the Agent.
3. The same browser updating from (seq1, plan_revision2) to (seq2, plan_revision1) is accepted, and the old planning state overwrites the new one. plan_revision is merely a recorded field and has not become an effective fence.

Additional S-level gap: the checkpoint saves only state/events/training/updated_at, not the browser sequence fence; the frontend reads state.planningRevision, but its write is not found in the current static JS, and the effective manual-planning version comes from manualPlanningState.planningVersion. The presence of this field in the request does not justify claiming production version validation is effective. No real dual-tab/process-restart injection was performed.

Fix direction: the owner/case control-plane atomic receiver does not depend on Agent loading; the same accepted canonical state is used by the bucket, Agent, and checkpoint; persist/restore the sequence, and clarify planning revision authority, cross-tab conflicts, and frontend ack ownership. Do not start an expensive case hydration just for UI validation.

#### R06｜P1｜null in relative opacity treated as a valid 0 (F10, S/P)

Location: _overlayOpacityFraction at `brachybot-ui-api.js:7915`.

When state={doseOpacity:0.6} and the doseOverlay object is missing, increase10 actually resolves to base0, percent10, but a valid fallback should be used to get 70. Number(null)===0 masks the fallback. This is a definite misreading of a valid fallback, not an instance of guessing a default when the value is unknown.

Fix direction: for null/undefined/blank, first test missing and then convert to a number; a relative operation must not be performed when there is no valid current value. For differing current values within a group, explicitly decide whether to set them uniformly or increase per object, rather than silently letting the first item stand for the whole group.

#### R07｜P1｜Serial batches are not equivalent to a cross-batch dependency and cancellation system (F12, S/P)

Location: _executeUIActionsWithProgress and _queueUIActionBatch at `brachybot-ui-api.js:7302`.

- The first-batch producer fails; the second-batch consumer that explicitly depends on the producer still executes, because failedSteps exists only within this call.
- An unknown precondition executes as long as it is not in failedSteps; there is no requirement that it has already succeeded.
- An isolated call passing an already-aborted signal still executes; this function only checks the session. This evidence does not mean every upper-layer cancellation entry point will let it through, but it proves the executor itself has no cancellation gate.
- The pending receipt from R02 also prematurely releases dependencies.

Fix direction: the owner/request/step ledger retains results across batches; unknown/incomplete preconditions wait or fail validation and are not defaulted to success. Check cancellation and ownership before enqueueing, dequeueing, and business writes; use an effect lock for the Viewer/workspace. Retain the implemented serial queue but do not call it a complete DAG and recoverable transaction.

### 0A.3 Actual Tests and Evidence Boundaries of This Pass

| Level | Result of this pass | Must not be over-interpreted |
|---|---|---|
| 15 related Python files | **209 passed**, 3 SWIG warnings | 139 original + 70 new, not the whole repository |
| 3 newly added Node contract scripts | **all passed** | ui-control-receipt, ui-state-sync, ui-action-dependency; do not cover the counterexamples above |
| 5 Playwright/Chrome scripts | **5/5 passed** | manual-step-viewer, monitor-dashboard, monitor-coaching, depth-peeling, report-hidden-viewer; real browser/WebGL + isolated fixtures, not patient-case E2E |
| Newly added counterexample probes | **reproduce R01–R07 gaps** | An observation script exiting 0 only means collection succeeded, not that the defect acceptance passed |
| Two pre-existing Node failures | **still reproduce** | chat_screenshot_delivery's sandbox lacks uiActionTasks; test-report-lifecycle expects captureAllowed=false but gets true. The assertions were not changed, so this alone cannot establish a real screenshot failure |
| Whole-repository pytest, real cases, online LLM | **not run this pass** | The 1971 passed/8 skipped/2 failed in the implementation record is a historical run, not re-certification this time |

Environment conclusion update: the old "Playwright is missing, so the five browser scripts could not execute" was the environment conclusion at that time; this pass used bundled Node dependencies and the local Chrome to execute and pass all five. The five should no longer be marked as not run, nor should this be used to declare whole-product E2E complete.

### 0A.4 Subsequent Implementation Order and Work-Package Status

1. Fix R01 authorization first, then R02/R03 terminal state and dependency identity; do not first expand the executable natural-language range.
2. In parallel, improve the R05 control-plane receiver and the R07 cross-batch ledger, keeping cold sessions lightweight; do not add per-subtask LLM calls or judge success by a fixed long wait.
3. Fix R04/R06 and expand the value-type retention set, then do the F04 semantic fallback. The model understands complex language; the deterministic layer validates sourced permissions, parameters, and versions, rather than permanently vetoing on local recognition misses.
4. Continue F06/F08/F11/F15 resource-capability indexing and F13/F14 evidence persistence; retain the existing OAR, active planning, screenshot transaction, and Monitor authoritative executor.
5. **WP1 should be marked "partially complete, pending closure"**; WP0's test foundation is valid; WP2/3/4/5 still have reconciliation-table gaps; WP6's five fixture browser tests have now passed, while real-case end-to-end, performance, and restart recovery remain to be verified.

Closing conditions: the original regressions stay passing; R01–R07 are changed to correct-behavior assertions and pass; the production call chain actually uses the new contract; actions requiring save/render have real postconditions; independent failure, dependency waiting, cancellation, and disconnect/cold-load/reload have evidence. New helpers, fields, or "fixed" documents cannot replace integration acceptance.

### 0A.5 Attachments for This Pass

`docs/audits/nl-ui-parity-review-20260928/`:

- review_probes.py / review_results.json: parsing, authorization, graph merging, parameter binding, in-memory versions, and isolated Flask cold/hot state.
- review_browser_probes.cjs / review_browser_results.json: inert VM probes of the real execution functions, covering receipts, cross-batch dependencies, cancellation, and opacity fallback.
- verification.md: test commands, scope, and workspace protection notes.

Python is run from the project root with PYTHONPATH=. and the project environment; Node scripts locate the repository automatically. The JSON is the observation baseline for this pass; do not merely edit the JSON to fake a fix, but add correct-behavior assertions to the normal tests.

## 0B. Independent Review and Remediation of R01–R07 (Third Round)

Date: 2026-09-28. This section was written by the implementer after independent review and **is not a paraphrase of §0A**: each entry gives the review method, root-cause determination, change locations, and reproducibly rerunnable evidence. **All seven R01–R07 items in §0A are true**, and this round implemented fixes along their fix directions; the text also records two boundary judgments in §0A that could not be accepted wholesale.

### 0B.1 Review Conclusions (Item by Item)

Review method: directly run the two probe scripts from §0A.5, then locate root causes against the source. The probes' JSON output is **verbatim identical** to `review_results.json` / `review_browser_results.json` — the observations are reproducible, not transcription errors.

| ID | Review judgment | Independent review method |
|---|---|---|
| R01 | **True** | All three `mutating_execution_authorized(..., 'ctv_segmentation')` cases actually return `True`. The root cause is two filter sets: the ordinary authorization loop skips ambiguous/negated/interrogative/conditional/quoted/attributed, while `aggregate_scope_targets` skips only excluded/negated, then authorizes a second time with the weakly filtered set. |
| R02 | **True** | `handlerCompleted = success===true \|\| completed===true \|\| receipt!=null \|\| job_id!=null` actually upgrades `{success:true,completed:false,status:'running',job_id}` to complete; `_executeUIActionsWithProgress` emits `pending→done` for `{success:true,completed:false,dispatched:true}`. |
| R03 | **True** | In the single-pass `merge`, `dependencies = tuple(key_map.get(d, d) ...)` runs in the same pass as building `key_map`: when C enters the graph first, new A has not yet been renamed, so `key_map.get('A','A')` resolves to old A. The measured order is `A→C→dose_recompute#2`. It is true that `_order_tool_calls_by_action_plan` does not call `validate()`. |
| R04 | **True** | `OPACITY_WORD_PATTERNS` does one `re.search` per pattern, emitting values by pattern declaration order rather than original position: 「不透明和半透明」 yields `[50,100]` (should be `[100,50]`); 「半透明和半透明」 yields `[50]` (should be `[50,50]`). |
| R05 | **True** | Isolated Flask measurement: cold session seq9→seq4 both return 200 and the final value is the old one; after tombstone the memory has deleted it while the bucket still has `deleted:'old'` and `state_keys` still contains that key; (seq1,plan2)→(seq2,plan1) is accepted. The root cause is that the version fence exists only in `AgentMemory._ui_state_last_seq` (a cold session with no agent has no fence), bucket writes separately do `dict.update` without tombstones, and `plan_revision` is recorded but not compared. |
| R06 | **True** | `asFraction = raw => Number(raw)`: `Number(null)===0` and is finite, directly short-circuiting the `state.doseOpacity` fallback. Measured with `state={doseOpacity:0.6}` and no overlay, `increase 10` yields base 0 / percent 10. |
| R07 | **True** | `failedSteps` is a `Set` within a single call; `blockedBy` only checks `failedSteps.has(dep)`, so an unknown precondition is treated as satisfied; `signal.aborted` is never checked anywhere in the function. All three counterexamples are let through in the measurement. |

### 0B.2 Implemented Fixes (Root Cause → Change Locations)

No sentence allowlist, no opening up arbitrary DOM, no weakening of safety checks, and no passing off an enlarged cap as a fix; every criterion converges on a **single authoritative implementation**.

**R01｜Single authorization predicate + inspectable scope provenance**
- `agent_runtime/request_parse.py`: added `_subtask_can_authorize(task)`; the `named` collection in `aggregate_scope_targets` and the loop in `mutating_execution_authorized` **share the same predicate** (plus `excluded`). Conditions/quotations/reported speech/questions only "talk about" the object and no longer borrow the target.
- Aggregate scope resolution is factored into `_aggregate_scope_resolution`, exposing `aggregate_scope_provenance()` → `named` / `count_reference` / `elliptical` / `policy_default` / `contested_scope` / `unresolved_count_reference` / `none`. **Only the first three are authorizations given in the user's own words**; `policy_default` is truthfully labeled a "sourceless policy default" rather than a "sourced scope".
- Added `_AGGREGATE_GEOMETRY_TARGETS`: when the same sentence mentions a geometry target that is not an explicit exclusion ("全部更新，CTV分割了吗？" → contested), **even the default family is withheld**, forcing clarification. An explicit exclusion ("全部更新，CTV不用动。") is not contested and still goes through the default family with the excluded item deducted.

**R03｜Two-phase remapping + mandatory pre-execution validation**
- `agent_runtime/action_plan.py` `merge()`: **first assign final ids to the entire subgraph (phase 1), then uniformly rewrite all dependency edges (phase 2)**, so forward references bind to the producer that arrives with them. On duplicate/empty/self-dependent entry ids, **the entire graph is rejected** (returns `self`), without guessing.
- `agent_runtime/llm_runtime.py` `_order_tool_calls_by_action_plan()`: the execution path is separated from tolerance enumeration — if `validate()` is non-empty, **not a single tool is scheduled** (both call sites end the tool loop for the turn with an empty return). `ordered_steps()` still retains the exceptional graph for diagnostics but does not constitute permission to execute.
- `agent_runtime/execution_authorization.py` `set_action_plan()`: the event trace records `merge_refused` and `plan_problems`, so rejection is no longer silent.

**R02｜Terminal-state classifier, JobRef only proves acceptance**
- `web/app/static/js/brachybot-ui-api.js` adds `_uiActionResultState(result)`: a unified vocabulary of `completed / failed / cancelled / stale / accepted / dispatched / running / waiting_user / …`. `completed===false`, `job_id`, `dispatched`, and non-empty `receipt` **no longer equal completion**; nested receipts are determined recursively.
- `handlerCompleted` in `invokeMountedHandler` is changed to `state === 'completed'`; the response body gains a `status` field.
- `_executeUIActionsWithProgress` uses the same classifier to determine the progress terminal state: a non-terminal state emits `running` instead of `done`.
- `tool_factory/ui_controller/__init__.py`: `executed=len(validated)` is changed to `accepted=len(validated)` / `executed=0` / `execution_claim="accepted_pending_browser"` (this count describes the accepted amount; the browser has not yet executed).
- `tool_factory/viewer_command/viewer_command.py`: the same type of defect is fixed as well (its message claims "queued" yet reports `executed`).

**R05｜Control-plane atomic receiver + dual fences + tombstone single source**
- `agent_runtime/core.py` factors out `apply_ui_state_write()`: the merge logic for patch/replace/tombstone/delete-marker exists in **exactly one place**, shared by the bucket, AgentMemory, and checkpoint.
- `AgentMemory.set_ui_state()` adds a `plan_revision` fence (`_ui_state_last_plan`); an old planning snapshot is rejected even if its seq is newer (`stale_plan_revision`).
- `web/routes/planning_routes.py` `/api/ui/state` POST: **the fence moves to the control-plane bucket** (`bucket["version_fence"]`), effective even for a cold session with no agent; the bucket and memory write the same canonical state, so tombstones no longer diverge.
- `checkpoint_ui_bridge` persists `version_fence` / `state_seq` / `plan_revision`, and the recovery path `_bridge_view()` carries them back as-is — a restart does not reopen the fence window.
- Frontend `web/app/static/js/brachybot-ui-api.js` adds `_currentPlanRevision()`, whose authoritative source is `manualPlanningState.planningVersion` (previously it read the never-written `state.planningRevision`, so `plan_revision` was always null and the server had nothing to compare); the `manual` block of `_collectUIState()` gains `planning_version`, so the snapshot carries its own provenance.

**R04｜Take values by original position, retain duplicates**
- `agent_runtime/ui_operations.py`: `values_from_text` is changed to **unified collection with source spans** (number + text + color), sorted by `match.start()`, retaining repeated occurrences.
- Textual values are synthesized into a single `_OPACITY_WORD_RE` (named capture groups) with one `finditer`, no longer emitting values in per-pattern declaration order.
- `(?!度)` prevents the property name 「不透明度」 from being read as the number 100.

**R06｜missing is not 0, intra-group disagreement does not guess a baseline**
- `asFraction` in `_overlayOpacityFraction` first tests `null/undefined/blank` and then does `Number()`, so the missing fallback truly takes effect.
- The OAR group is evaluated per organ: when members disagree it returns `null` (rejecting a relative operation and requiring an absolute value), no longer silently taking the first item for the whole group.

**R07｜Cross-batch ledger + cancellation gate**
- Added `_uiActionStepLedger(ownerKey)` (owner+request dimension, retained across batches) and `_uiActionDependencySatisfied()`: **a precondition must be `completed`**; unknown/incomplete/failed/still-running is always blocked and never defaulted to success. The R02 classifier directly determines whether a dependency may be released.
- `_executeUIActionsWithProgress` checks `options.signal.aborted` both inside the loop and before business execution.

### 0B.3 Assertion Changes (2 places, both tightening)

Per the §0A closing condition "change R01–R07 to correct-behavior assertions", 46 new assertions were added (Python 31 + Node 15). At the same time, two **existing assertions themselves encoded the defect** and had to be changed:

1. `tests/ui-control-receipt.test.cjs`: `assert.equal(result.completed, true, 'a positive handler receipt proves completion')` — that handler returns `{success:true, job_id:'guide-1'}`, i.e. a JobRef. This line **is R02 itself**. Change to `completed === false` + `status === 'running'` + `dispatched === true`, and add a positive case with an explicit terminal state `{success:true, completed:true}` → `completed === true`.
2. `tests/test_screenshot_trace_integration.py:1493`: asserts the source string `"result.success === false || result.stale === true"`. That expression has been merged into `_uiActionResultState`, and the string no longer exists. Change to assert the new equivalent marker `state === 'failed' || state === 'stale'` + `function _uiActionResultState`, and add a **behavior-level** assertion in `tests/ui-action-terminal-state.test.cjs` (session switch → `stale` failure, and subsequent actions are not executed).

The remaining historical assertions were not changed.

### 0B.4 Verification Evidence

| Level | Result | Boundary |
|---|---|---|
| Whole-repository pytest `--ignore=tests/test_release_access.py` | **2029 passed, 2 skipped, 2 failed** | The 2 failures are the pre-existing `tests/test_brain_system.py` (`test_agent_chat_fallback` / `test_brain_agent_connection`); they fail on the baseline too and were not touched this round |
| Newly added `tests/test_nl_parity_review_regressions.py` | **31 passed** | Covers R01/R03/R04/R05, including isolated Flask cold/hot sessions |
| Newly added `tests/ui-action-terminal-state.test.cjs` | **15/15 passed** | Covers R02/R06/R07, loading the **production functions** rather than a replica |
| The 4 pre-existing Node contract suites | all pass | ui-control-receipt / ui-state-sync / ui-action-dependency / ui-action-owner (including 5 suites that need explicit argv) |
| The original §0A.5 probe `review_probes.py` | all seven counterexamples **converted to correct behavior** | see §0B.5 |

Measured comparison for the original probes (left = §0A observation, right = after this round):

| Counterexample | §0A | After this round |
|---|---|---|
| `全部更新；如果以后需要，重新分割CTV。` | `ctv_authorized=true` | **false**, scope `[]`, provenance `contested_scope` |
| `全部更新；他说"重新分割CTV"。` | `ctv_authorized=true` | **false**, scope `[]` |
| `全部更新，CTV分割了吗？` | `ctv_authorized=true` | **false**, scope `[]` |
| Forward-dependency merge | `order=[A, C, dose_recompute#2]`, C→old A | **`order=[A, dose_recompute#2, C]`**, C→`dose_recompute#2` |
| 「不透明和半透明」 | `[50, 100]` → ctv,50 / oar,100 | **`[100, 50]`** → ctv,100 / oar,50 |
| 「半透明和半透明」 | `[50]` → ambiguous | **`[50, 50]`** → ctv,50 / oar,50 |
| Cold session seq9→seq4 | both 200, final value `{"value":"old"}` | **409 `stale_state_seq`**, final value `{"value":"new"}` |
| (seq1,plan2)→(seq2,plan1) | accepted | **rejected with `stale_plan_revision`**, state remains new |
| tombstone | memory deletes / bucket keeps `deleted:'old'` | **both sides agree `{"keep":true}`**, `state_keys` does not contain `deleted` |
| incomplete receipt | `pending→done` | **`pending→running`** |
| Cross-batch failed dependency | `["producer","consumer"]` | **`["producer"]`** |
| Unknown precondition + aborted | `["consumer"]` | **`[]`** |
| Relative opacity with no overlay | base 0 / percent 10 | **base 60 / percent 70** |

### 0B.5 Two Boundary-Judgment Differences from §0A

1. **Handling of `policy_default`**: §0A's fix direction says "with no explicit source, first do read-only parsing/clarification". This round **did not categorically disable** bare 「全部更新」 — dose/report/guide are reproducible artifacts, rebuilding does not damage geometry, and there is an existing positive regression. The compromise is: (a) use `aggregate_scope_provenance()` to truthfully expose that `policy_default` is not an authorization source, so the upper layer can require clarification on that basis; (b) as soon as the same sentence contains a **non-excluded geometry target**, even the default family is withdrawn (`contested_scope`). This is exactly what the three §0A counterexamples demand (conditions/quotations/questions must not authorize), while not tearing down a usable path.
2. **Binding of count reference to structured offer**: §0A's S-level gap — `count_scope_targets` slices by the preceding enumeration, does not verify that "there really are that many real pending items", and does not bind the offer's case/plan revision. **Not fixed this round**: it requires authoritative storage of pending-item completion state/product freshness (the `currently explicitly stale product set`), the third source type in §0A's fix direction. Half-wiring a validation with no authoritative data source only manufactures false green. This item remains unclosed in §0B.6.

**Probe tool note**: `docs/audits/nl-ui-parity-review-20260928/review_browser_probes.cjs` loads `_executeUIActionsWithProgress` via a single-function slice. After this round factored the terminal-state classifier and ledger into shared helpers, that single slice is no longer self-sufficient (`_uiActionStepLedger is not defined`) — this is a limitation of the probe's loading method, not a product regression. The formal assertions now live in `tests/ui-action-terminal-state.test.cjs` (per the §0A closing condition's "counterexamples converted to correct-behavior assertions"). The Python-side `review_probes.py` needs no change and can still be rerun directly.

### 0B.6 Still Not Closed (Not Claimed Solved by This Round)

- The eight original defects F04 / F06 / F08 / F09 / F11 / F13 / F14 / F15 in §0A **are outside this round's scope** and their status is unchanged.
- The count-reference/offer-version binding of §0B.5-2.
- Real-case E2E (tool→browser→save→dependency→answer full chain) is still unverified; what was added this round are isolated contract assertions.
- The two pre-existing Node failures, `tests/chat_screenshot_delivery.cjs` (sandbox lacks `uiActionTasks`) and `tests/test-report-lifecycle.cjs` (`reportCaptureAllowed().allowed` is true), are retained as-is without changing assertions to mask them.
- This working tree also contains another parallel Monitor particle-spacing accuracy effort (`clearance_basis` / `finite_parallel_cylinders` endpoint false-positive criteria), already covered by the same full gate; its remediation record is in `docs/MONITOR_INTERACTION_AUDIT_REMEDIATION_2026-09-28.md`.

## 0. Initial-Review Conclusions for the Implementation Agent (Historical Baseline; See §0A for the Latest Status)

**It currently cannot be confirmed, let alone claimed, that every operation a user can perform in the frontend can be reliably completed through natural dialogue. The audit has confirmed general mechanical defects that prevent this goal from holding, not merely a few missed Chinese keywords.**

The project already has considerable infrastructure: a dynamic UI catalog, 111 registered UI targets, a structured ActionPlan, read-only metric contracts, active-planning context, screenshot transactions, Monitor version fences, and several browser completion receipts. Do not tear down and rewrite the clinical algorithms, and do not maintain yet another huge "sentence allowlist". The existing infrastructure should be unified into a capability system with types, permissions, versions, and execution receipts.

The six most important conclusions:

1. **The semantic model does not truly obtain a general execution channel.** UI actions must ultimately match item-for-item the action signature produced by the local lexical parser; even when the model understands a euphemistic request, it may still be discarded during normalization.
2. **Permissions are simultaneously too strict and too loose.** Polite questions are treated as non-executable; but a context-free “全部更新” lets through segmentation, full planning, and many other change types in the underlying authorization function. This cannot be fixed by simply "loosening keywords".
3. **Emitting an event is often treated as business success.** The generic control executor can return success when the handler returns failure, an asynchronous operation is not yet complete, or a value is wrongly converted. This is an important source of incorrect final replies.
4. **A structured plan is not a reliable task graph.** Step-key dependencies may be ignored; one failure in an action array stops all subsequent items; cross-batch UI operations may run concurrently. These rules do not express the real business dependencies.
5. **State visibility is not a complete, queryable, provably-fresh model.** The DOM, Data Tree, backend active planning, history summaries, and simplified tool results each hold part of the information; "a field has been collected" does not mean the model can discover and correctly use it.
6. **Answer-coverage verification is still a local keyword rule.** It can protect the already-enumerated OAR/seed-particle questions, but it cannot prove that arbitrarily complex requirements are covered, nor infer "already answered completely" from "no requirement was recognized".

Implementation order: first fix the underlying contracts such as authorization/execution receipts/task identity, then integrate module by module, and finally improve natural-language coverage. It is forbidden to use expanding DOM click permissions or removing clinical safety gates as a shortcut to "getting smarter".

## 1. The Precise Meaning and Boundaries of the User Requirement

### 1.1 Product Goal Adopted by This Audit

When a user says "knows all the information", this should be implemented as:

- Knowing which current cases, active plans, available data, running tasks, and display states the current account is authorized to access;
- For information not pre-loaded into context, knowing through which read-only resource query it can be obtained, rather than falsely claiming it is absent;
- Being able to recognize the objects, actions, parameters, constraints, temporal relations, negations, conditions, quotations, and references in a request;
- Manual buttons and natural language going through the same verified business executor, with identical validation, persistence, and undo semantics;
- Multiple requirements executing and reporting separately; independent task failures not swallowing each other, and dependent tasks not crossing a failed precondition;
- Completion meaning business completion with verified postconditions, not the model picking a tool, HTTP returning 200, or a DOM event having been dispatched;
- Replies being able to point to the evidence for this operation and this version, and accurately distinguishing not-executed, awaiting-confirmation, running, partially-succeeded, failed, and stale.

This is not about making the large model always carry all voxels, meshes, DVH sample points, and the complete event history, let alone giving it permissions beyond the current user.

### 1.2 Boundaries That Must Not Be Disguised as "Automatic Completion"

- Browser file selection, secure downloads, the clipboard, fullscreen, etc. may require real user activation. An explicit state such as "waiting for file selection" should be returned; opening the picker must not be treated as a successful upload.
- Clinical approval, manual signing, deletion with an unclear target, and overwriting a protected report must not bypass existing permissions/confirmations because of a natural-language entry point.
- An ambiguous tumor site, an object with the same name, or a reference from the previous case must be queried or clarified, not guessed.
- Noise levels, organ geometric proximity, dose thresholds, and clinical superiority that the model has not measured cannot be invented from textual common sense.
- "Doable via natural language" requires declaring the supported range: for example, precise patient-coordinate localization can be supported; when the user only says “往那边一点” with no view/target reference, coordinates must not be fabricated.

## 2. Audit Scope, Method, and Verification Strength

> This section records the initial-review baseline and the environment at that time, not the test list of this re-review. For the latest 209 regressions, 5 browser tests, and new counterexamples, see §0A.3.

### 2.1 Baseline and Inventory

The inventory was built from the remotely Git-tracked `.py/.js/.html/.css/.cjs` files; the local mirror and the current remote files were compared one by one by SHA-256, and **none of the 505 files were inconsistent**. During the work, an agent/user also modified `docs/MONITOR_INTERACTION_AUDIT_2026-09-26.md`; this document was not overwritten. At verification time the production source files were still consistent with this report's baseline.

| Inventory | Count | Limitation that must be understood |
|---|---:|---|
| Source files | 505 | Includes tests and third-party frontend libraries; excludes all non-code assets, external model weights, and runtime cases |
| Source-file lines | 270,436 | A static count; does not mean every line received a manual semantic proof |
| Flask route declarations under `web/` | 122 | AST-recognized route declarations; not guaranteed to cover all dynamic mounting mechanisms |
| `index.html` static control/event candidates | 264 | Overlaps/containers exist; not equal to 264 independent business capabilities |
| JS/HTML event registrations or inline event lines | 568 | Text scan; dynamically created and delegated events still need special inspection |
| `CONTROL_REGISTRY` targets | 111 | "Registered" does not mean "reachable via natural language and business-correct" |
| target-command pairs | 212 | Does not include all parameters, object instances, and combinations |
| Python `test_*` function declarations | 1,649 | Not equal to the number of tests executed this pass |

The corresponding complete inventory is in `docs/audits/nl-ui-parity-20260928/`, including all the above entries, source-file hashes, registration schemas, and probe results. Do not compute coverage with `111/264`; the two have different denominator meanings.

### 2.2 Evidence Levels

- **S: Static confirmation**: code behavior confirmed by reading the actual implementation, callers, and receivers.
- **P: Isolated reproduction**: calling actual pure functions, or extracting actual JS functions for execution in an inert DOM/VM; no case changes.
- **T: Existing tests pass**: only indicates that the scenarios these tests currently cover hold.
- **E: Real end-to-end not verified**: logged-in browser, real Viewer/GPU, refresh recovery, cross-process, etc. still require acceptance.
- **R: Risk/design gap**: has a code basis but was not reproduced on a real case, and is not stated as an incident that has occurred.

"Confirmed" in this report refers only to the explicitly described functions/paths and cannot be extrapolated to mean that all user requests necessarily fail.

### 2.3 Actual Execution Results

The remote side executed with `/home/lht/.conda/envs/brachytherapy/bin/python`:

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
  tests/test_ui_bridge_sidecar.py
```

Result: **139 passed, 3 SWIG deprecation warnings, 7.49 seconds**; the same set was run again before delivery and was still **139 passed, 3 warnings, 5.79 seconds**. This is not the full test suite.

Locally, `tests/guide-visibility-browser.test.cjs` and `tests/chat_turn_lifecycle.cjs` passed. These two are Node isolated tests, not real-browser clinical acceptance.

When attempting to run `manual-step-viewer-browser.test.cjs`, `monitor-dashboard-browser.test.cjs`, and `monitor-coaching-browser.test.cjs`, the environment lacked `playwright` and they failed at the dependency-loading stage; they were not recorded as product-logic regressions, nor were these browser tests claimed to pass. This pass did not install dependencies or start a clinical-service test instance.

The newly added audit probes reproduced the defects listed below. The probes are currently a **baseline observation script**, not an all-green fix-acceptance suite; during implementation their observed values should be changed into assertions of expected correct behavior and incorporated into the tests.

## 3. Current End-to-End Structure and Break Points

```text
User natural language + current case/session + history/pending items
    ↓
request_parse / turn_policy / shortcut_contract
    ↓ quick route or semantic model
ActionPlan + provider tool calls
    ↓ response_tools._normalize_tool_params / execution_authorization
Tool execution: backend business tool or ui_controller returning ui_actions
    ↓ stream event / chat task / browser receives
_executeUIActionsWithProgress → _executeUIActionRaw → business function or generic DOM control
    ↓
Backend data / browser local state / workspace save / Viewer render
    ↓
State sync, screenshots and evidence, progress, final reply
```

The current situation is not "there are no tools", but that each layer uses a different definition of success, object identity, permission basis, and state version:

- The request layer recognizes by lexicon, the tool layer matches by signature, and the UI layer looks up by DOM/ref; semantic decisions cannot directly resolve the inconsistency among the three.
- `ActionPlan` has `depends_on`, but ordering and execution do not always use the same step ID/dependency result as the basis.
- The tool returning "executed", the browser "event dispatched", the business actually completing, and persistence succeeding are not the same moment.
- The final text may come from the model's pre-answer, while screenshots come from subsequent browser results; without finalization on the same evidence version, they easily contradict each other.
- In a snapshot, an object not existing, not loaded, hidden, parent-group hidden, stale, query truncated, and query failed are different states and cannot all be called "absent".

## 4. Confirmed Problems and Root Causes (Ordered by Risk)

> The following F01–F16 retain the initial-review original evidence and design requirements. Whether they are currently fixed must be checked in §0A.1; the originally reproduced portions of F01/F02/F03/F05/F07/F10/F12 are partly fixed, and the residual boundaries are in R01–R07; do not copy old line numbers or claim the original samples still all fail.

### F01｜P0｜“全部更新” lacks scope binding in underlying change authorization (S/P)

Location: from `agent_runtime/request_parse.py:1255`, especially `parsed.aggregate_command and expected_target in _WRITABLE_TARGETS` at `:1307`.

Reproduction: with no history, active plan, or preceding list of items to update, calling `mutating_execution_authorized('全部更新', tool)` directly returns true for `ctv_segmentation`, `oar_segmentation`, `planning_pipeline`, `surgical_guide`, and `report_auto_fill`. "全部更新，不含导板" can exclude the guide but still lets through the other categories.

Root cause: treating the aggregate action word as authorization for all writable targets, rather than binding it to the set of objects the current user refers to. The upper layer already has limits such as `_downstream_update_calls`, so this audit **does not prove that a real request will necessarily mis-start segmentation**; what is confirmed is that the underlying defense itself cannot bear the authorization responsibility it claims.

Fix: parse "all" into a finite sourced set: the currently explicit products to update, the scope of the current pending items, and the object list the user is pointing at. Each effect is validated against the same subtask. When there is no dereferenceable set, clarify, and do not re-segment/re-plan. Read-only preconditions needed by the graph may run automatically; new clinical changes must not cross the boundary.

Acceptance: after an empty context/case switch, “全部更新” must not authorize re-segmentation; “把刚才三项全部更新” updates only those three; exclusions take effect for the entire execution plan; explicit commands for the full clinical workflow still work through the original confirmation flow.

### F02｜P0｜Generic UI control success is disconnected from real business results (S/P)

Location: `executeGenericUIControl` at `web/app/static/js/brachybot-ui-api.js:2659`; the simple async handler path is around `:2727`. Premature backend receipts are at `tool_factory/ui_controller/__init__.py:1192–1240`, `:1474`.

Reproduction: a mocked actual handler `failOperation()` returns `{success:false,error:'business_failure'}` and the executor still returns `success:true`; the parameterized `generateGuide('v1')` uses `el.click()` and returns success while the operation is still pending. The backend UIController's `executed` count occurs before the browser actually executes.

Impact: report/guide/segmentation failures may also be interpreted as success; natural-language next steps use an object that was not generated; the final reply conflicts with the frontend state.

Fix: controls with business side effects must bind to a business handler that can return `OperationReceipt/JobRef`, and must not treat the `click`-end state as proof of success. The generic DOM path may only prove `dispatched`; it must not self-upgrade to `completed`. Both synchronous and asynchronous failures propagate a structured reason. Operations that have returned a job track the job's terminal state and version postconditions.

Acceptance: synchronous failure, asynchronous failure, parameterized handler, save failure, network disconnect, user cancellation, and duplicate events must all not falsely succeed; a success reply has an actual receipt; retrying the same operation ID does not regenerate clinical products.

### F03｜P0｜Task dependency identity is wrong, consumption may precede production (S/P)

Location: `agent_runtime/action_plan.py:79`, `:127`, `:219–244`.

Reproduction: the step `consumer(report_generator)` depends on `dose_recompute#2`, which is actually in the plan; `ordered_steps()` still emits the consumer first, because the condition uses `dep not in self.tool_names`, mixing step keys with tool names. `from_tool_calls()` does not retain the passed-in `key/depends_on`; a cyclic dependency is output in the original order instead of blocking execution. `order_tool_calls()` sorts only by the first position of the tool name, so it cannot guarantee step order for duplicate tools.

Fix: all dependencies reference a unique step ID; missing dependencies, duplicate IDs, and cycles report a validation error before execution; schedule by step identity rather than tool name. Plan transforms/merges must preserve parameters and dependency mappings. Business-level preset ordering may still be added, but it cannot be dressed up as a "complete DAG" while continuing to sort by name.

Acceptance: A→B→A, two identical tools on different objects, cross-turn appends, restored tasks, unknown dependencies, cyclic dependencies, and a second dose recomputation all have tests; a dependency failure must block the corresponding downstream and cannot merely achieve correct ordering.

### F04｜P1｜Correct actions from the semantic model are still vetoed by the local parser (S/P)

Location: `agent_runtime/response_tools.py:3229–3330`; `_ui_action_signature` at `:48–69`; `resolve_ui_operation_request` in `agent_runtime/ui_operations.py`; the clause attributes in `request_parse.py`.

The isolated sample uses the same live catalog containing `guide_mesh_v1`:

| Request | Local result |
|---|---|
| 请显示导板 | correctly `tree.visibility set guide_mesh_v1,on` |
| 能帮我把导板显示出来吗？ | `rejected_unsafe_clause`, no action |
| Could you show the surgical guide? | likewise rejected because it is a question |
| 把刚才藏起来的导板恢复一下 | no parse result |
| 让导板重新出现在画面里 | no parse result |
| 请不要显示导板 | correctly refuses execution, must be retained |

The normalization layer only allows a `(target,command,value)` exactly identical to the local `expected_actions`. This means the local recognition misses above will continue to restrict provider actions rather than being remedied by later semantic understanding. The entire filter branch around `llm_runtime.py:2280` can set `tools_executed=True` and exit without returning a specific UI rejection reason to the model/user.

Fix: distinguish speech acts: polite request, asking about capability, hypothetical discussion, reported speech, explicit negation, and executable precondition. The model outputs a structured task; the authorization layer validates evidence spans, object scope, effect risk, preconditions, and required confirmations, and **must not require another keyword parser to produce the same action signature**. Model confidence itself is not an authorization credential either.

The local parser can be retained as a high-precision fast path; on a miss it returns `needs_semantic_resolution`, rather than treating non-recognition as prohibition/completion. An action that is genuinely refused must have a reason code and enter execution tracking and the final result.

### F05｜P1｜Multi-target parameter correspondences are lost (S/P)

Location: multi-target/numeric parsing in `agent_runtime/ui_operations.py` and the subsequent signature gate in `response_tools.py`.

Reproduction: “请把CTV和OAR分别设为30%和70%的透明度” generates `ctv,30` and `oar,30`, with confidence still 0.86.

Root cause: the sentence-level parameter is diffused to multiple targets, lacking per-subtask source-span/value binding. Furthermore, the business definitions of "transparency" and the opacity slider must be unified: the same interface must not use T in one place and alpha in another.

Fix: each assignment is `{objectRef, property, absoluteOrDelta, value, unit, sourceSpan}`; the “分别” (respectively) relation validates length by alignment; a shared parameter is broadcast only when it is genuinely shared semantically. Mixed actions must not take one whole-sentence value and apply it repeatedly. Ambiguity should prompt a question rather than high-confidence execution.

Acceptance: 2 targets/2 parameters, 3 targets/shared parameter, differing units, negating one of them, relative increase/decrease, same-named objects, target-count mismatch, and English respectively.

### F06｜P1｜The UI catalog may truncate even at a normal large-planning scale (S/P)

Location: virtual Data Tree actions at `brachybot-ui-api.js:947`, catalog at `:1238–1389`, 4096 cap at `:1389`; another cap after flattening at `agent_runtime/ui_operations.py:199`; the visual catalog has a separate 512 limit and legacy controls a 260 limit.

Reproduction: synthesizing 181 seeds, 24 needles, and 53 organs (258 nodes total), calling the actual `_uiOperationVirtualTreeActions()` generates **4464 entries**, before adding DOM, guides, dose, manual steps, and scene actions. The collector truncates to the first 4096; the Python flattening truncates again at 4096, potentially losing further actions at the tail.

This is a **synthetic-scale probe, not a read of a patient case**. But the scale is comparable to a user's actual use with nearly 200 particles, enough to refute the assumption that "this cap only affects discovery on abnormally huge pages".

Fix: separate the object index from the capability schema; each object stores only identity/type/state/applicable-capability references, without duplicating a dozen action copies. Query objects and properties by user task, paginate, and make `has_more/truncated` explicit. When the model cannot find the current page it knows to keep querying, rather than concluding "no objects". Do not merely change 4096 to a larger number.

Acceptance: 200/500/1000 particles, objects at the end of pagination, Chinese aliases, guide leaf, dynamically added nodes, catalog network and token budget; truncation must not be used as evidence of non-existence.

### F07｜P1｜Frontend/backend state merge, sync, and timing semantics are not unified (S/R)

Location: `set_ui_state` at `agent_runtime/core.py:559`; the UI state endpoint around `web/routes/planning_routes.py:5133`; `syncUIBridgeState` at `brachybot-ui-api.js:2137` and `ui.state` at `:8223`.

Confirmation: one server bucket path uses replace while the cached agent uses a shallow `.update()`, so missing fields may retain old values; the sync function does not validate `response.ok`, the catch swallows errors, and the caller can still report success. Collection/arrival times are not uniformly turned into client-side state-sequence validation.

Risk: deleted objects/old selections/old controls may remain in the merged state; a slower old snapshot overwrites a new one; the frontend believes the save succeeded while the server is still in the old state. This pass did not inject real-case network reordering and does not claim it happens every time.

Fix: clearly distinguish full snapshot, typed patch, and tombstone; validate with case/session/browser instance/state_seq/plan_revision. Sync returns an accepted revision; on failure it displays unsynced, and subsequent dependent operations must not assume persistence. Browser display state and backend clinical state each annotate their authoritative source and do not overwrite each other.

Acceptance: case switch, object deletion, out-of-order POST, network loss, two tabs, browser recovery, 401/409/500, and late old requests; a new state must not be rolled back, nor old fields left across cases.

### F08｜P1｜`ui_inspector component` queries source-code components, not active scene objects (S)

Location: `_search_component` at `tool_factory/ui_inspector/__init__.py:660–732`, dispatch from `:863`; the `:734` state branch can return the live catalog.

Confirmation: component/search queries static HTML and JS text; when `surgical_guide` is a business object type, "Found 0 matching items" does not mean the current guide does not exist. The state branch does have live content, and the single status string `Getting current UI state` shown by the tool must not be mistaken for the complete payload.

Fix: split `ui.components` (development diagnostics) from `resources.resolve` (current object query); make the tool description state its type; the guide→active guide artifact→Data Tree leaf→mesh/render state mapping is provided by the same resolver. Return `not_found/ambiguous/not_loaded/hidden/stale/query_failed` rather than mixing them into an empty list.

Acceptance: guide saved but not loaded, hidden, parent-group hidden, multiple versions, deleted, renamed, and same-named guides can all be explained without falsely triggering regeneration.

### F09｜P1｜Generic gestures are not equivalent to manual operations (S/P)

Location: wheel at `brachybot-ui-api.js:2979`, drag at `:3017`; real MPR interaction is at `brachybot-manual-annotation.js:3735–3830`.

Reproduction: a wheel with `ctrlKey:true` does not enter the generated event; drag dispatches only a PointerEvent, while the reviewed 2D pan listener uses mouse events. A real Ctrl+wheel is zoom and an ordinary wheel is slice change; losing the modifier key can execute a different action. A synthesized pointer does not automatically generate a complete, trustworthy mouse event sequence.

In addition, the `viewer.zoom` typed handler operates global zoom and `viewer.transform` lacks an explicit axis; a scenario where the user manually changes only one 2D Viewer cannot be proven covered by "there is a zoom tool".

Fix: make single-axis zoom/pan/slice, window width/window level, 3D camera, annotation geometry, and manual needle/seed editing into typed commands, and have manual gestures call the same command. Prefer patient/image coordinates over screen pixels. Generic gestures serve only as a restricted compatibility layer, with explicit modifiers, target viewport, units, and result verification.

Acceptance: three 2D windows do not falsely link; Ctrl/Shift/ordinary wheel, left/right buttons, touch/pen, resize, coordinate conversion after camera changes, undo/redo, and drag cancellation. Dispatching all mouse and pointer events at once in a way that causes double execution is forbidden.

### F10｜P1｜Control numeric/boolean/delta conversions are inconsistent (S/P)

Location: input assignment around `brachybot-ui-api.js:2740`; overlay opacity around `:7820`; registration schema at `tool_factory/ui_controller/__init__.py:176–192`.

Reproduction: a number input with no min/max set to 25 is clamped to 0 because `Number('')=0`; the checkbox string `'false'` becomes true via `!!value`; the `overlay.ctv.opacity/oar.opacity/dose.opacity` command with increase=10 actually performs an absolute set10.

Fix: the schema parses values strictly, and an empty boundary is not equal to 0; booleans accept only booleans or a clear normalization; a relative action reads a valid current value, computes, clamps, and returns the applied value. absolute/delta/unit are defined within the same schema, and the frontend and backend are forbidden from each guessing.

Acceptance: no range, one-sided range, step/float, percentage, 0/100, invalid NaN/Infinity, false/true string rejection or correct conversion, absolute/relative, and transparent/opaque definitions.

### F11｜P1｜Generic control discovery and execution have different safety boundaries (S/R)

Location: catalog collection from `brachybot-ui-api.js:1238`; `_resolveUIControlElement:2609–2657`; `applyParameterSet:156` onward.

Confirmation: filtering exists at collection time; at execution time it can additionally use `document.querySelector` as an ID/selector fallback, choosing the first match. The parameter setter can find a control directly by ID. Filtering read-only/sensitive items in the catalog cannot automatically protect the other execution entry point.

This pass did not attempt to bypass login or operate sensitive controls; this item is a boundary design risk, not a verified remote attack.

Fix: execution accepts only a capability instance ref issued by the current session and still valid; re-check permission/enabled/unique/revision; high-risk actions must not go through generic DOM, and a selector must not become a general model permission. The backend keeps the same authorization constraints; prompt injection cannot grant operation permission from documents, reports, or tool text.

Acceptance: password/hidden controls, duplicate selectors, stale refs, refs from other cases, resources of a non-current user, commands in report text, and forged actions in tool results are all rejected with an explanation.

### F12｜P1｜Independent task failures are dragged down together, while cross-batch tasks may conflict (S/P/R)

Location: `brachybot-ui-api.js:7101–7165`; `brachybot-chat-todo.js:4618–4651`, `:1292`.

Reproduction: when the first item of a UI actions array fails, the second item does not execute at all even if independent. Statically it is visible that each streaming UI batch can execute immediately and be added to a promise list, lacking a rule that coordinates by the full dependency/effect scope. The `_awaitChatUIActions` comment calls it a bounded window, but in reality the race between `Promise.allSettled` and abort does not provide its own timeout.

Fix: schedule by task graph and effect lock; clinical writes/screenshots of the same Viewer/saves to the same workspace are serial or conditionally serial; independent reads may be parallel. A task failure blocks only its dependents. An explicit confirmation/waiting-user must not be disguised as a timeout; a long job returns a job ref. Every wait has ownership, cancellation, offline recovery, and a terminal state.

Acceptance: A fails while B independently succeeds; A fails and C (depends A) is skipped with a reason; multiple ui_controller, screenshot, and report races; the user switches case/cancels; a modal is not clicked; the server task finishes but the browser has disconnected.

### F13｜P1｜Metric results do not carry full version/freshness, and coverage verification has blind spots (S/P)

Location: query_metrics injection around `AgenticSys.py:1514`; `web/planning_runs.py:1113–1267`; `tool_factory/viewer_command/query_metrics.py:54–85,226–312,459`; `agent_runtime/answer_coverage.py`.

Parts that already work: query_metrics is wired into current_planning_context; OAR dose actually exists in the implementation, so the historical log statement that "the system can only read organ volumes" should not continue to be repeated.

Still to fix:

- direct-read metadata does not fully carry case/plan/revision/stale; the active context has source information but it is not fully propagated into answer evidence.
- The `metric_type=plan_score` schema exists, but execute has no dedicated branch of the same name and falls through to all_metrics; the contract is not precise enough.
- In `_get_dose_metrics`, the D2 fallback to D2cc confuses a percentage-volume metric with an absolute-volume metric; different keys/units must be retained, and a missing one must not masquerade as a substitute.
- coverage models only a few aspects; “脊髓受到多少辐射” does not write “器官/OAR”, required is empty, and the target-only contract is judged covered; “每根针有多少粒子” does not recognize the single character “针” and only requires seed_total.
- A contract that does not declare `covers` is treated as covering the whole turn. A composite screenshot request with empty required also passes this metric helper; this is not evidence that the whole screenshot chain necessarily fails, but that the helper cannot serve as a general completeness proof.

Fix: a task's required outputs come from structured goals, not from re-running a vocabulary against the final question; tool results declare the specific resource/fields/covered objects/version/units. Unknown coverage is unknown, not covered. Small direct reads keep a fast path, while complex requirements align the result set with the task.

Acceptance: spinal cord/English aliases/left-right organs, per-needle detail, all OAR, missing/stale score, D2 and D2cc present together/only one, stale DVH after manual editing, switching to a different plan, and distinguishing true zero dose from not-computed.

### F14｜P1｜Completion states such as reports/parameters may still represent only that the DOM was set (S/R)

Location: parameters/hyperparameters at `brachybot-ui-api.js:8260`, report.field.set at `:8334`, report.template.set at `:8349`; report editing/export are in report-editor, report-shell, and report-export respectively.

Confirmation: some parameter applications do not wait for the asynchronous result, and applied=0 may still succeed; the report field path sets the DOM and schedules an autosave, without incorporating persistence confirmation into the current action's success; template set lacks a complete existence check. `input.*.browse` only opens the file picker.

Fix: distinguish displayed/applied/persisted; separate report dirty from the saved revision; a non-existent field/template fails explicitly. Download completion, export having been generated, and clicking download are not the same event. Retain auditing and versioning for clinical field edits, and do not treat directly editing DOM text as successfully modifying a report.

Acceptance: refresh/session switch after editing, save failure, read-only report, non-existent template, language switch including figure captions, export consistent with the current draft version; a parameter with no match reports details.

### F15｜P2｜Dynamic event scanning does not constitute a complete, stable business-capability catalog (S/R)

Location: the EventTarget ledger at `brachybot-ui-api.js:364–415`; `web/app/index.html:1599–1601` and script load order.

Confirmation: the ledger records only Elements and does not cover delegated interactions on document/window; previously registered events are also not traceable. The collection holds strong references to elements; disconnected filtering is not equivalent to explicit reclamation, nor is the lifecycle of one-shot/AbortSignal listeners.

Risk: canvas/hotkeys/delegated menus are not discoverable, old objects linger, and long-session catalogs and memory grow. This pass did not do a heap profile, so this is not called a measured memory leak.

Fix: explicit business capability registration is primary, and DOM scanning is only diagnostics/patching; components unregister on unmount, and dynamic object references resolve through the resource index. It is forbidden to rely solely on capturing all `addEventListener` calls to claim that arbitrary operations are covered.

### F16｜P2｜Existing correct improvements should be retained, but require cross-layer rather than single-point acceptance (S/T/E)

There are existing implementations and partial tests for guide leaf display, tree visibility result correction, screenshot ordering/recovery, Monitor fencing, manual-step results, and active-plan reading. This report does not list every issue in the historical screenshots again as a "currently confirmed bug".

What mainly needs to be added is integration acceptance: a target being within the camera projection range is not equal to being unoccluded; camera/visibility recovery should coordinate with concurrent user operations; the manual phase's init/refine/seed/dose results must be consistent in the real Viewer and after reload. Relevant source points include `brachybot-ui-api.js:11887`, `:12291`, `brachybot-manual-step-results.js`, `brachybot-monitor-interaction.js`, and `brachybot-monitor-dashboard.js`.

## 5. Parity Matrix Across All Frontend Domains

Legend: **Partial** means the corresponding capability or generic entry point has been found, but end-to-end completeness cannot be proven; **Gap** means a contract insufficiency confirmed this pass; **Awaiting E2E** means it must be verified by real operation. The complete item-by-item list of low-level controls/events/routes is in the attachments; below is the business-capability decomposition. The implementation agent must establish a capability ID for each item and cannot reconcile it by saying "there is already a one-line tool".

| Domain | Manual entry/action range | Existing code or channel | Audit conclusion and what must be completed |
|---|---|---|---|
| Login and permissions | Login, logout, roles and session ownership | auth JS, backend auth routes | Should recognize but not type/leak credentials; authenticate the same before and after execution; awaiting E2E |
| Case session | New, switch, rename, delete, clear, restore, cache recovery | session.*, workspace/session-cache | Partial; after switching, all object/task refs are invalid; deletion must not bypass confirmation via generic UI |
| File input | CT, mask, OAR, DICOM-RT, report/STL import | input.*.browse, import actions | Gap: opening the picker ≠ upload; must wait for file/progress/parse completion and a stable resource ID |
| Input mode | model, site, CT phase, multi-volume data, planning mode | planning.parameter, parameter catalog | Partial; the model site must match the current case, and dynamic options need versioning |
| Parameters | Thresholds, prescription, particles, needle tracks, planning hyperparameters, guide parameters | parameter.set, planning.hyperparams.set, etc. | Gap: numeric types, relative amounts, batch details, applied=0, asynchronous save |
| Auto-segmentation | CTV/OAR single, multiple, specified model, full workflow | dedicated clinical tools | Retain the dedicated executor; must not re-segment because of “全部更新”; a model alias does not replace site validation |
| Manual mask | New, brush, erase, threshold, rectangle, SAT3D, finish, rename, move, delete | mask.*, viewer.tool, manual-annotation | Partial; selecting a tool ≠ completing an annotation; patient/voxel coordinate input and commit/undo transactions are needed |
| Step-by-step | init/refine/seed/dose/evaluation, current-step product display and next-step hiding | plan.run_manual_step, manual-step-results | Partial; real result nodes/visibility/refresh recovery await E2E; a failed next step must not hide the only valid result |
| Whole-planning | Start, pause/cancel (where present), view progress, complete, reuse | plan.run, planning_pipeline, task routes | Partial; respect task ownership and resource leases, and forbid multiple starts on retry |
| Downstream update | Incremental update of dose, QA, score, guide, report, display | downstream_update, clinical tools, UI actions | Needs a dependency graph and a limited scope; if the report includes guide results, it must come after the relevant guide step |
| 2D browsing | Three-axis slice, single-axis zoom/pan, window width/level, flip/rotate/fit/reset | slice.*, viewer.*, manual-annotation | Gap: generic gestures and typed scope are not equivalent, see F09 |
| 2D measurement | Crosshair, distance, angle, marquee, history undo/redo | viewer.tool/transform, canvas listeners | Partial; tool activation does not mean the measurement is complete; units and the transform chain must be verified |
| 3D browsing | orbit/pan/zoom, fit, viewpoint, fullscreen, reconstruction, depth peeling | viewer actions, scene catalog, viewer-volume/layout | Partial; coordinates and camera capabilities need an explicit schema; must not rely only on dragging the canvas |
| Data Tree | Single/group display, parent-group state, 2D/3D separation, opacity/color, rename/classify/select | tree.*, context action, virtual catalog | Partial; large-scene truncation, stable object references, and consistency between color buttons and rendering must be closed |
| Data Tree resource ops | Export, delete, rebuild, mesh/mask grouping | data-export, context menus | Must not all be authorized as low-risk display; object permissions/dependency invalidation/recovery need dedicated receipts |
| Needle-track editing | Add/select/endpoint move/delete/direction, preview→commit, cancel | manual.needle.*, 3d-manual | Partial; clarify which endpoint, patient coordinates, geometry revision; automatic projection-associating particles do not count as multiple user edits |
| Particle editing | Add, move, delete, project along needle track, spacing validation | manual.seed.*, manual planning routes | Partial; real business result, safety constraints, retain-or-reset on conflict, and concurrent versions need unification |
| Manual recompute | Dose preview, recompute, re-plan, finish | manual.dose.recompute/plan.* | Must distinguish preview/committed/dose_revision; must not secretly run an expensive recompute just to answer |
| Analysis/DVH | Individual CTV/OAR, single organ, per-needle particles, score, hotspots, curve controls | query_metrics, dvh-planning | OAR queries already exist; the gaps are discovery/coverage/version/units, and a separate set of fake statistics must not be created |
| Guide | generate/analyze, parameters, version, geometry QA, display, export/import STL | surgical_guide, surgical-guide JS, tree.* | Retain the dedicated path; saved-exists ≠ display-exists; stale does not mean absent or un-screenshottable |
| Report body | Fields, templates, section toggles, citations, comments/review/verification, layout | report.*, report-editor/shell | Partial; persistence ack/permissions/input disambiguation/language switching must be covered |
| Report products | autofill, screenshot, snapshot, audit, export PDF/other formats | report.autofill/export/snapshot.* | Must not treat a screenshot plan/export start as completion; the report's dedicated camera strategy should not pollute the chat-localization strategy |
| Chat screenshots | Object localization, multiple targets, Data Tree/3D/2D/DVH, annotation | ui_screenshot, visual-annotation, ui-api | The foundation has improved; must be juxtaposed by object/step/view/evidence ID and not splice in unverified pre-answers |
| Monitor | start/stop/status, HUD, advice, focus, auto compare, undo/keep, summary | training.mode, monitor dashboard/interaction, training routes | Must not treat the light effect as the truth of the run; server lease/stop acknowledgement and versioned edit decisions must be connected |
| Chat tasks | Send, queue, cancel, retry, disconnect recovery, compaction, history, attachments | chat-core/todo, chat task/context code | Unify turn/step/job terminal state; cumulative invocation tokens ≠ context usage, and the display basis must be clear |
| Global UI | Chinese/English, theme, panels/sidebar, layout | chat.language/theme, panel/layout | Low-risk fast path; locale propagates to Monitor/figure captions/buttons and must not be changed by an English keep reply |

Special note: the four facts that a page has a button, the registry has a name, the interface can return 200, and an existing unit test passes cannot, individually, mark any row in the table as "fully at parity".

## 6. Recommended Underlying Design: Reuse Existing Modules and Establish One Business Contract

### 6.1 Unify the Capability Catalog, Not All Keywords

Define for each business capability:

```text
capability_id / schema_version
description / examples / supported_object_types
input_schema: ref, scope, axis, value, unit, absolute_or_delta, ...
read_selectors / preconditions / effects / postconditions
risk_class / permission / confirmation_policy
executor / async_job_kind / idempotency_scope
undo_policy / invalidates / locale_keys
evidence_schema / result_schema
```

The data catalog provides only object instances: `case_id, planning_id, object_id, kind, label, revision, parent, loaded, own_visible, effective_visible, stale, capabilities`. A displayable human-readable name must not be used as a unique ID.

`CONTROL_REGISTRY` and the frontend handlers retain compatibility entry points; gradually generate tool descriptions, the frontend catalog, validators, and parity tests from the same schema. It must not be the case that Python/JS/prompts each manually maintain three registries with different meanings.

### 6.2 Task-Understanding IR: Separate "What the User Wants" from "How to Execute It"

Suggested internal representation (not a requirement for a new external API):

```json
{
  "request_id": "...",
  "case_id": "...",
  "intent_source": {"turn_id": "...", "text_spans": []},
  "goals": [
    {
      "goal_id": "g1",
      "speech_act": "request",
      "object_query": {"kind": "surgical_guide", "scope": "active_plan"},
      "desired_effect": {"property": "effective_visible", "value": true},
      "constraints": {"preserve_other_objects": true},
      "polarity": "positive",
      "quoted": false,
      "precondition": null,
      "required_evidence": ["visibility_receipt"]
    }
  ]
}
```

The IR is not a new backdoor for "the model says it, so it executes". It must be validated with a bounded schema, source spans, current resources, permission rules, and required confirmations. High-risk ambiguous requests are clarified first; read-only state discovery may complete automatically.

Local explicit requests take the shortcut IR without adding an LLM; complex requests are understood once in a batch, not re-recognized subtask by subtask; when an object is missing, do targeted discovery first. A simple intent model must not authorize clinical changes on its own on the basis of confidence.

### 6.3 References and Follow-Up Instructions Are Persistent Task Context, Not Full-Text Keyword Inheritance

Store `pending_goal_set`, `offered_action_set`, `approved_scope`, `case/plan_revision`, and expiry time.

- “那就全更新” references the most recent relevant product set that is in the same case and still valid.
- “为什么不执行” is explanation/correction, and a single challenge does not infinitely expand clinical authorization; if an earlier authorization is still valid, check the original task's failure reason and retry safety.
- “保留/复位” binds to a specific edit decision and does not change the global locale based on the reply language.
- After switching case/plan, old approvals, old objects, and coordinates must be invalidated or require re-confirmation.
- History compaction retains structured pending items/authorizations/failure reasons, and must not keep only a generalized natural-language summary.

### 6.4 Authorization Policy by Effect and Risk, Not a Blanket Question-Mark/Tool-Name Rule

Suggested layers: read-only resource query; low-risk reversible display; persistent UI/report editing; clinical geometry/dose/segmentation changes; destructive operations/exporting sensitive data/permission operations.

“可以帮我显示导板吗” is a low-risk execution request; “你能生成导板吗” may be a capability question; “如果将来生成导板会怎样” is hypothetical discussion. Semantic discrimination and context are needed, not a uniform rejection of all interrogative sentences.

A read-only precondition query does not need to repeatedly ask “是否允许读取”; a lack of mutation permission must not block an independent read-only task that is already authorized. High-risk actions should have a limited-scope explicit authorization/confirmation handle. Tool payloads, web pages, reports, and the model's own suggestions cannot serve as a source of user authorization.

### 6.5 One Execution Ledger Unifying UI and Background Tasks

Unified identity: `request_id → goal_id → step_id → operation_id/job_id → evidence_id`, additionally carrying case, plan, and geometry/dose/report revision.

Recommended states: `planned / resolving / waiting_confirmation / queued / running / verifying / succeeded / failed / cancelled / blocked_by_dependency / expired`. Browser event dispatch is an intermediate event, not succeeded.

- The backend UI tool returns accepted/queued; the browser receipt flows back into the same task, rather than merely patching the page text.
- Step success requires validating the result schema, the business result, and the necessary persistence/display postconditions.
- A timeout is not automatically “not executed”; make the unknown outcome explicit, and query the operation ID before retrying.
- Writes to the same object/capture transactions of the same Viewer are serial; independent reads may be parallel.
- The dependency graph is built according to the actual version requirements. If a report includes a guide version/QA/screenshot, satisfy the guide result first and then generate the report; it must not be hard-coded as always "report before guide".
- Whether a background task continues after cancellation/disconnect must be explicit and recoverably tracked; turning off the light effect must not be taken to mean the backend stopped.

### 6.6 Unify State and Evidence, Without Stuffing All State into the Prompt

Example resource queries: `active_plan.summary`, `objects.resolve`, `oar.metrics`, `viewer.state(view_id)`, `report.fields`, `monitor.run`, `operation.status`.

Each result carries source, revision, generated_at, stale_reason, completeness/pagination, and units. Requests specify fields, and copying the entire scene/all voxels for one organ question is forbidden.

“Does not exist” requires a complete query with no result in an authoritative resource; “not loaded” is proven by the Viewer state; “hidden” also considers the parent group; “unknown” may be further read-only discovered rather than mechanically making the user ask again.

### 6.7 The Final Reply Must Be Generated from the Completion Ledger

Each goal records requested/attempted/result/evidence/remaining. The final answer uses only accepted evidence of the current version; the model's preliminary text is not used as a screenshot conclusion.

Simple display success: “已恢复显示导板 Puncture guide v1，其他对象未改变。” Say it only when verified.

Partial success: “导板已显示；肿瘤对象有两个同名节点，需要选择一个。没有调整它们。” Avoid a generic “没有可验证分析结果” that masks the real blocking reason.

Answer dose questions at the user's granularity; if OAR data already exists, read it, and do not ask again “是否允许读取”. An unknown clinical threshold may be stated as unknown, but that does not prevent reporting the actual measured values. Missing fields/zero values/stale results must be stated separately.

The UI's trace, progress, send button, and final-reply state take the same turn state. Generate only one final step; while a screenshot/report save is not finished, keep the corresponding pending state, but it must not pending indefinitely when there are no remaining jobs.

## 7. User Experience, Latency, and Cost Requirements

The following are suggested acceptance targets, not performance commitments measured this pass:

| Scenario | Decision strategy | Suggested limit |
|---|---|---|
| Clear low-risk single-item display/slice/theme | Local IR + resource reference + same executor | No additional LLM round trip; local decision overhead p95 target <200 ms, rendering measured separately |
| Complex multi-requirement | One batch semantic understanding, cached to the turn | Do not send an independent understanding request per subtask |
| Large Data Tree | Object index + type capabilities + query/pagination | 200–1000 particles must not copy thousands of complete action descriptions into every turn |
| Read-only dose/state questions | Targeted authoritative query + direct evidence synthesis | Do not secretly trigger planning/recompute/screenshot; at most targeted supplementary reads for missing required fields |
| Asynchronous long tasks | Return task accepted immediately + continuous real progress | Split time into decision/queue/compute/render/save, and do not falsely report completion |
| User choice needed | List the necessary options and object differences once | Do not repeatedly ask confirmations already answered; do not let the model loop guessing |
| Reversible display | Precisely modify the necessary objects | Do not recolor/clear the scene/change other windows without cause; user operations take priority |

Record in practice: local hit rate, semantic-parse time, model calls per turn, catalog bytes/tokens, query count, erroneous-rejection rate, unauthorized-execution rate, time to first feedback, time to business terminal state, state-sync latency, and duplicate-operation count.

It is not possible to solve every problem by "always thinking one more LLM round", nor to reduce latency by "taking a template whenever a keyword appears". The amount of computation should grow with request complexity, not with the size of the complete case data.

## 8. Implementation Work Packages (for the Follow-Up Agent)

> Current progress: WP0's test foundation is valid; WP1 is partially complete and not closed; WP2–WP5 are reconciled per §0A; WP6's five fixture browser tests have passed, and real-case E2E remains to be verified. The following is the complete work-package design and does not mean this work has not yet begun.

### WP0: Fix the Baseline and Establish Regression-Capable Acceptance (do first)

- Re-read the current remote HEAD/dirty diff and do not overwrite other agents' changes.
- Convert the attachment probes into correct-behavior assertions; record the existing 139-test baseline; add a real browser environment.
- Label every static control/dynamic event with `capability_id or UI-only/safety exception`, forbidding unexplained omissions.
- Form a formal parity matrix: supported/partial/to-be-implemented/exception/to-be-verified, with links to test IDs.

### WP1: Execution and Result Foundation Contract (P0, before language expansion)

Fix F02/F03/F07/F12: receipt, step identity, dependency results, idempotency, exception propagation, version sync; split UI action accepted from completed; unify the state machine. First retain old-interface adapters and migrate key capabilities such as report/guide/manual.

Acceptance postconditions: the same user task does not end in the UI while the backend still falsely hangs; independent subtasks are not interrupted; all false-success probes disappear; failures have a readable reason.

### WP2: Capability and Object Catalog (can run in parallel with WP1's schema)

Fix F06/F08/F11/F15: single-source registry, instance resource index, pagination, stable refs, scoping, selector boundaries. Retain DOM scanning to discover un-connected capabilities, without giving it business authority.

Acceptance: complete discovery for a normal large planning; querying a guide does not fall into source-code search; same-name/hidden/not-loaded/stale are distinguished; a stale ref does not operate on a new object.

### WP3: Semantic Tasks and Permissions (depends on the WP1/2 contracts)

Fix F01/F04/F05: shortcut IR, semantic fallback, source span, respectively parameters, limited aggregate scope, explicit rejection receipts. Keep zero extra model calls for common single intents; do not delete the old parser all at once.

Rollout suggestion: first shadow-compare new and old plans and execute only the old path; classify well-founded differences, then enable by capability. Anonymize shadow logs and do not store raw case imagery or sensitive credentials.

### WP4: Shared Business Executor for Manual/Dialogue

In risk batches: display/color/opacity → MPR axis control → parameters → report → manual editing → monitor → clinical generation/deletion. Fix F09/F10/F14. Each time a capability is migrated, connect the manual button to the same command as well, so the two logic sets do not continue to drift.

### WP5: State Query and Answer Coverage

Fix F13: typed resource query, real OAR/needle breakdown, revision/units, required_outputs, evidence ledger, partial reply. Incorporate into integration tests the contradiction between a final reply of "no evidence" and an image that has already been attached.

### WP6: Whole-Product E2E and Release

Complete Section 9; user acceptance on a real case with a completed plan. Release via the independent LAN service process, confirming listener/process/cwd/assets/health and task recovery. **This report itself does not authorize restarting services or changing the release deployment.**

## 9. Acceptance Matrix: Testing a Few Example Sentences Is Not Enough

### 9.1 Language and Authorization (Bilingual Chinese/English, Paraphrase Retention Set)

Include at least:

1. Command/polite request/capability question/why/hypothetical discussion/quotation/reported speech/negation/double negation/correction.
2. Chinese punctuation, no punctuation, English and/then/respectively, colloquial typos, object aliases.
3. “分别” multi-target parameter binding, shared action, shared modifier, mixed read/write, conditional precondition.
4. “它/刚才那个/这些/全部后续” same-case references, cross-case invalidation, and an existing pending confirmation.
5. An explicit positive subtask is executable; a negated/quoted adjacent clause must not authorize by splicing targets or actions.
6. Read questions automatically obtain the necessary read-only data; a read-only question must not trigger generation, deletion, or planning.
7. When any model provider outputs an unknown target, wrong type, forged ref, empty tool result, duplicate calls, or a missing step, there is a bounded response.

It is not acceptable to merely add the probe example sentences to training/rules and rerun the same sentences. Retain a set of user paraphrases and composite tasks that did not participate in implementation, and measure task-achievement rate/erroneous-execution rate.

### 9.2 Business Execution Equivalence

Each capability must have at minimum: manual entry → receipt; dialogue entry → the same business function → the same state change; same permissions; same failure semantics; same state after refresh. Test 0/1/multiple objects, loaded/unloaded, hidden/parent hidden, valid/stale, saved/preview.

Data Tree display/opacity/color should simultaneously verify the tree button, the 2D/3D actor, and save and restore; it is not enough to verify that the function was called. Patient-coordinate commands should verify the image orientation matrix/spacing/axis, not merely screen proximity.

### 9.3 Scheduling and Recovery

- Multiple same-named tools, different targets, different parameters; A→B→A; independent failure continues; dependency failure blocks.
- Screenshots of the same Viewer are serial; when the user changes viewpoint/visibility within a transaction, do not overwrite the user's new operation with an old snapshot.
- Recovery after network disconnect/refresh/case switch/duplicate messages/button double-click/cancel/timeout, with no duplicate clinical job.
- A closed/unconfirmed confirmation dialogue, a cancelled real file selection, and a browser-blocked export have the correct state.

### 9.4 Monitor Specific

Monitoring is not simple scheduled chat: each committed edit has before/after geometry, associated objects, conflict addition/resolution, a comparable dose version, and an explicit undo/keep token. Displaying a screenshot depends on the object existing and the Viewer being ready; when there is no image, state the specific failure, not merely “已经捕获”.

The authority for start/stop/lease is in the backend, and the UI light effect is not a state source; a pending stop is recoverable and idempotent. Suggested distinction among geometric facts, dose changes, and clinical interpretation; do not attribute without an identical baseline. Auto Compare stays opt-in and does not hide expensive recomputation.

Language uses the run/user-configured locale; a reply of `keep id` does not change subsequent Chinese feedback. Visual evidence, buttons, toasts, progress, and summaries are all included in locale tests.

### 9.5 Report/Screenshot Specific

- Chat localization prioritizes preserving the user's view; when a target is occluded/hidden, make the minimal temporary adjustment, explain it, and restore.
- Report images use their own stable camera/composition strategy; Fig1(a)/(b) target proportion, cropping, and reference direction are accepted using the actual image, not merely checking that the camera API was called.
- Two objects in the same turn each have their own attachment ID, and a later image must not overwrite an earlier one; the preliminary reply must not leak in the style of the final reply.
- Report body text, figure captions, titles, and export language are consistent; numeric decimals and Markdown tables must not be broken by “sentence cleanup”.
- The final reply/send button/progress are based on the same terminal state; a turn has only one final step.

### 9.6 Performance and Safety

200/500/1000-particle catalogs, low bandwidth, slow GPU, offline browser, two tabs. Record p50/p95 rather than reporting a single time. Truncation followed by falsely reporting non-existence must not be used to reduce tokens; the complete scene must not be put into every small interaction request.

## 10. Correct Implementations That Can Be Retained and Forbidden "Fix Shortcuts"

Retain: active-planning context and real backend array injection; the model must not be allowed to overwrite runtime arrays. Retain the existing Monitor run/plan/geometry fences, guide leaf parsing, screenshot recovery, dedicated clinical tools, and the physician-review boundary.

Forbidden:

- Adding another special if for every failing Chinese sentence;
- Treating all interrogative sentences as read-only, or all verbs as authorization;
- Expanding `aggregate_command` so that all mutating tools are let through;
- Believing that returning a longer tool list solves capability discovery;
- Letting the model execute arbitrary selector/JS/shell in place of business APIs;
- Reporting a clinical operation as complete when a click/dispatch succeeds;
- Treating source-text search results as the truth about case objects;
- Treating results that do not declare a coverage scope as "already fully answered";
- Using "all tests green" to mask that the browser was not run, the real GPU was not run, or historical assertions were weakened;
- Overwriting the independent public-release working tree, sharing a writable runtime, or restarting another service for this purpose.

## 11. Completion Criteria and Handoff Requirements

Implementation completion cannot be reported as merely "a smart route was added". The following must be delivered:

1. All UI candidate items are classified, with a supplementary list for dynamic menu/gesture/keyboard paths; each maps to a capability or a written exception.
2. Registration schema, executor, authorization/confirmation policy, state source, postconditions, receipt, and test ID are each traceable.
3. The defects corresponding to F01–F15 are fixed or have explicit incomplete items; failing probes must not be silently deleted.
4. Evidence that the frontend manual and dialogue paths share the executor, covering at least all clinical writes and key display/report/Monitor paths.
5. Real E2E evidence saved: completed planning → hide/restore guide → separately locate guide/tumor → read OAR dose → manual editing → Monitor reminder/screenshot → keep/undo → necessary recompute → limited-scope downstream update → report export → refresh recovery.
6. Partial success, clarification, cancellation, network anomalies, task recovery, and duplicate calls no longer mask the reason with a mechanical template.
7. Call counts and latency for short requests do not regress, and complex requests do not multiply understanding rounds per subtask; report the actual measurements and the test environment.

**Final judgment: this audit proved that the current state is "not fully at parity" and located the fixable root causes across semantics, authorization, state, execution, and evidence; it did not prove that arbitrary natural language has been fully understood, nor did it conduct complete real-case end-to-end certification. A sustainable capability-parity acceptance system should be established per this report, rather than claiming a one-time "knows everything".**

## Attachment Index

New re-review attachments: `docs/audits/nl-ui-parity-review-20260928/`, see §0A.5 for details. The original attachments below retain their initial-review baseline meaning.

- `audits/nl-ui-parity-20260928/README.md`: evidence levels, reproduction methods, and file descriptions.
- `source_manifest.csv`: 505 source files, line counts, SHA-256.
- `static_controls.csv`: 264 static control/event candidates and index.html line numbers.
- `control_handler_index.csv`: candidate locations of inline static-control calls and JS functions, not a complete call graph.
- `event_sites.csv`: 568 event-registration/inline-event lines and source paths.
- `production_routes.csv`: 122 production route declarations and methods.
- `capability_registry.csv/json`: the existing schema of all 111 UI targets.
- `capability_source_index.csv`: each target's registration location and frontend string references; the actual execution branches still need continued verification.
- `test_inventory.csv`: a list of 1,649 Python test function declarations.
- `audit_probes.py/json`: isolated probes for semantics/permissions/dependencies/answer coverage and their baseline results.
- `audit_browser_probes.cjs/json`: VM probes of the actual frontend functions and their baseline results.
- `inventory_summary.json`: inventory summary.

Source-code locations all refer to the baseline at the top of this document. After subsequent code changes, they must be re-located by function name, not modified by directly copying old line numbers.
