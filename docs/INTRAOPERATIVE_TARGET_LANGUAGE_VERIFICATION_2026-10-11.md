# Submission-owned timepoint targets and global language: implementation verification

Date: 2026-10-11 (Asia/Shanghai).

Status: **candidate implementation; not deployed; complete multi-timepoint product remains unfinished**.

This record supplements `INTRAOPERATIVE_PLAN_VERIFICATION_2026-10-10.md`, including its 42-scenario matrix and remaining engineering list. It does not replace clinical, model, registration, printing, deployment or real-operator validation with code tests.

## 1. Requirements checked

The user's unqualified commands, including planning, segmentation, guides, reports and analogous tasks, must refer to the currently mounted Table Viewer. The correct invariant is **submission ownership**, not "whatever tab is active when a callback finally runs".

All added presentation must respect the top-level language manager. User-defined names, file basenames, technical IDs, units and clinical values are not translation templates. Changing interface language must not change the target, data, prescription or evidence.

There is a third necessary boundary: a provider inserting `timepoint_id` is not proof that the human authorized a clinical mutation on another workspace. Cross-timepoint read comparison is permitted within the owned Session; noncurrent writes require explicit human target confirmation. The authenticated confirmation-receipt UI is not yet implemented. The candidate therefore asks for target selection/resubmission instead of silently executing there.

## 2. Root causes found

1. The previous candidate exposed explicit named numerical planning, but ordinary chat still resolved a Session-only cached Agent. Merely injecting a header would leave normalization, state evidence, prerequisites, results and post-processing bound to the default clinical state.
2. The busy-turn queue stored only prompt text. A queued prompt could inherit a different tab at dispatch. Waiting for Stop acknowledgement and case creation had the same late-default risk.
3. Network retry and hidden screenshot analysis could independently re-resolve the navigation default. A child belongs to its parent request, not to the newly mounted scene.
4. A Session-only completion refresh could clear dose or reload a different Viewer after an off-screen task finished. Case identity alone is no longer sufficient.
5. Open timepoint forms and confirmations stored translated strings. Switching language could leave old headings/actions, and raw server exceptions could leak English into Chinese presentation.
6. Full array hydration at every named chat turn would create an unnecessary CT/OAR/dose decode barrier for saved-metric questions.
7. A metadata-only save could destroy undecoded array references if the execution view wrote `None` placeholders as a complete clinical state.
8. Shared conversation language could become a timepoint clinical mutation, unnecessarily incrementing clinical revisions and retained history.
9. An added field for target ownership could accidentally stop the legacy default Viewer from refreshing after reconnection. The authoritative default marker must travel in task recovery metadata.
10. A delete confirmation did not identify its target by name. The browser test exposed this UX defect; the product confirmation now names the captured target and uses explicit Delete/Restore buttons.

## 3. Implemented candidate path

### 3.1 Browser submission

`brachybot-chat-target.js` and the actual `sendChat` entrypoint capture an immutable envelope before asynchronous waits. The envelope carries Session ID, timepoint ID, mounted generation, default-workspace marker and UI locale.

The same envelope is retained by the FIFO queue and its dispatch, retrying HTTP handshake, case-readiness continuation and hidden child analysis. A deliberately empty timepoint header on older default-only captures prevents the generic fetch wrapper from injecting a later tab ID. The server still validates identity; browser envelopes are not authorization.

When the origin is no longer mounted, `collectUIState()` does not serialize the other tab into that request. Clinical completion signals and fallback refreshes are fenced by the captured target and current generation. Shared conversation display remains Session-wide.

### 3.2 Authenticated task binding

`capture_chat_scope` resolves the owned stable target before the worker, hydration or task-start persistence. Header/body/query disagreements are typed identity errors. Older default-only clients retain the original default behavior.

`ChatTask` carries the typed target. A repeated request ID reuses the original task only when both target and original message match; it cannot become a new-target execution. Retained parent scope and persisted transcript timepoint IDs support child linkage. Recovery metadata distinguishes the default workspace from named workspaces.

Archived default-only requests retain the established quick-failure SSE contract. Named/non-streaming execution through the older Session-only checkpoint path remains blocked rather than save another scan's arrays into the default workspace.

### 3.3 Clinical execution view

`ScopedChatRuntime` creates a detached clinical view of a named target without replacing the cached shared Session Agent. Shared conversational fields are copied back at task finalization; image, patient/clinical state, plan, dose, UI and report aliases are not copied to the default.

The actual common `BrachyAgent._execute_tool_with_memory` boundary routes omitted targets through that view. Tested factory capabilities have scoped admission; Session-only browser/manual/service capabilities remain unavailable until their adapters are complete. This capability inventory is not an intent keyword list.

Numerical and structured result changes are committed through `save_timepoint_results`, clinical CAS and the captured source read-set. Failed or stale computation cannot be published as current. The task's own successful target revision advances while original source dependencies stay frozen. Failed work is rolled back in the detached view before another tool.

Provider schemas expose an optional stable `timepoint_id` argument on clinical capabilities without adding a classifier or provider round. The system contract describes the submission default, ambiguous reference handling, passive historical evidence and noncurrent mutation confirmation. Explicit same-Session read targets affect only their call; sibling unqualified calls retain the submission default.

### 3.4 Latency and persistence

Named chat starts with saved JSON metadata. CT/OAR/dose sidecars are decoded only when the chosen operation requires arrays, and once per task. This is a dependency decision, not a guess from words such as "dose" or "tumor".

Clinical publication uses changed keys and explicit removals. It preserves unchanged encoded array references and does not persist hydration placeholders. Committed numerical inputs become read-only views before another tool. Source/target currency is checked before and after hydration and at publication.

`session_language` stays shared conversational state. It is excluded from named clinical revision updates and survives delayed required-array hydration. Case containment remains the read boundary; scoped output directories separate identical filenames across timepoints. Explicit output paths must also remain in that target's output subtree.

No extra LLM classification, CNN inference or automatic dose comparison was added for target binding. Code tests do not establish real deployed p50/p95 latency; large metadata manifests, source-default coupling and production resource restoration remain relevant performance work.

### 3.5 Language and interaction

`timepoint_messages.py` centralizes supported zh/en message codes, safe public errors, typed counts and saved-operation presentation. It does not detect language from titles, exceptions or requests and does not hydrate an Agent.

Timepoint routes, middleware error responses and the inspector use structured safe public messages. UI locale headers are sent by the timepoint controller. Stable technical codes remain intact; custom clinical names and values are not translated or rewritten.

Open forms/confirmations relabel on the existing global `i18nchange` event. Values, references and target identity survive. Inline validation has localized text and focus handling. Keyboard Escape/focus behavior and the established application confirmation style are retained. Delete confirmation names the target and uses Delete/Cancel; Restore uses Restore/Cancel. Automatic default titles have an explicit localizable marker; a human rename clears that marker.

## 4. Requirement-to-evidence matrix

| Scenario | Candidate evidence | Remaining boundary |
|---|---|---|
| Unqualified saved-dose query | Actual registered metrics injector reads the named scan, not root aliases | Real product tab/resource bridge |
| Unqualified segmentation/planning/guide/report tool | Shared execution-boundary tests publish only the captured workspace | Capability-specific trained model, artifact and real browser acceptance |
| Queue on A, dispatch after B is selected | Queue preserves original immutable envelope | Full deployed panel-switch workflow |
| Retry after navigation | Same payload/headers; request ID cannot change target/message | Restart-durable task/receipt ledger |
| Screenshot analysis after tab change | Parent target lookup and child mismatch rejection | Scoped screenshot/upload/annotation browser adapters |
| Explicit comparison of another scan | Actual metrics injector reads the explicit same-Session target, then reverts to the sibling default | Comparability, registration and cumulative-dose interpretation |
| Provider invents a noncurrent write target | Negative control: no mutation, confirmation-required result | Authenticated natural-language target confirmation UI/receipt |
| Foreign/malformed target | Owned catalog/type checks; no default fallback | Whole resource graph/default migration |
| Input changes during computation | Cross-store CAS rejects stale publication; default aliases retained | Crash/power-cut/real-GPU cancellation testing |
| Unsupported Session-only tool | Explicit not-ready result; no execution elsewhere | Manual/Monitor/UI/export adapters |
| Read-only question about saved dose | Test fails if any array decode occurs | Real metadata-size and end-to-end latency profiling |
| Metadata update while arrays are cold | Exact old array references retained | All future metadata writers must use same contract |
| Language changes during required hydration | Shared language retained, no clinical revision created solely for language | Remaining native tool/report operational strings |
| Global language switch with open form | Real headless browser preserves custom values and relabels controls | Real operator review |
| Global language switch with delete confirmation | Real headless browser keeps exact target, localized actions and naming | Complete default detachment/delete workflow |
| Identical artifact filenames | Distinct scoped output paths; target-root output containment | Quota-transaction integration for every exporter |
| Finalization or cancellation | Shared Agent restored; no clinical view goes to root checkpoint | Durable whole-workflow recovery and task garbage collection |
| Legacy default reconnect | Default marker carried through task recovery | Real current-case browser regression after integration |

## 5. Validation and regression treatment

All commands ran in `/tmp/brachybot-timepoints-stage-20261010-E1Rvjz/checkout`, not the live LAN or public checkout. No patient/model inference, full cohort experiment, service restart, commit or push was performed.

The first focused run passed 152 tests and found one identity-error presentation contract. It was corrected by a typed `RequestIdentityError` and code-based localization, not by returning raw exception text.

An intermediate unfiltered run stopped at 10 failures: six old route test doubles lacked authenticated Agent bindings; an archived-request SSE regression was real and repaired; one FIFO source assertion had the old two-argument queue signature; two screenshot route test doubles had the same missing binding. Test doubles were updated with real store/owner/Session bindings; target checks were not weakened.

The next unfiltered run reported 3,720 passed / 2 failed / 2 skipped, four passing subtests, 31 warnings, in 386.83 seconds. Its failures exposed the unnamed delete confirmation and an old completion-refresh source-shape assertion. The confirmation product text was corrected; completion refresh now filters eligible target events before retaining the original completion condition and independently fences the actual UI refresh. No test was waived to hide a wrong-target refresh.

Latest focused preflight: **213 passed**, 3 deprecation warnings, in 10.55 seconds. Evidence: `scope-language-frozen-preflight-20261011.xml`. Further shared-language/input-immutability/noncurrent-write guards were added afterward. The final unfiltered frozen-candidate result is recorded below only after it finishes. Overlapping focused results must not be summed.

### 5.1 Final frozen-candidate result

The complete unfiltered `tests/` run finished with **3,726 passed / 2 skipped / 0 failures / 0 collection errors**, four passing subtests and 31 existing deprecation warnings, in **392.98 seconds**. Evidence: `/tmp/brachybot-timepoints-stage-20261010-E1Rvjz/full-target-language-frozen-20261011.xml`.

The two skips remain real public-origin/proxy checks requiring the public deployment dependencies and `NGINX_TEST_BINARY`; they are not waived release validations. Pytest's summary is the pass-count authority: XML includes the four subtests in its testcase accounting.

The candidate was frozen before this final run and no product code was changed during it. The staged 85-file manifest matched every local candidate hash: 39 pre-existing modified files and 46 new files. All 71 candidate Python files compiled; all five changed JavaScript files passed syntax checks. The paired guide dependency guard still passes with the previously audited pipeline hash; no hash-only renewal was performed.

Read-only delivery checks found no drift in the live baseline's 39 before hashes and none of the 46 new product/test paths already present there. The running LAN process remained PID 3386575, host `192.168.1.113`, port `8080`, at this inspection. That is a point-in-time observation, not a future runtime guarantee.

Manifest SHA-256: `74786e6b667336265c33f4fd93c0b3582f0326a14d263fbd96555ad57da66868`.
Candidate archive SHA-256: `6ba82c03d850e41d2c4fb1ebe413afcc5865b204a03e4817ad17107b0846023b`.

Test results are not model/clinical/printing validation. Product delivery remains gated; only documentation and the private resumable checkpoint are published by this turn.

## 6. Whole-plan reinspection: not finished

The previous 42-scenario matrix remains applicable. Its largest gaps are still genuine, not waived by the new chat binder:

1. A production four-panel bridge for input forms, Analysis/DVH, Data Tree/MPR/3D, Report, asynchronous resources and appearance restoration is absent. `execution_scope=False` remains correct. `chat_target_binding=True` is narrower backend progress, not permission to enable UI switching.
2. The legacy default's source fence still uses a Session revision. A shared chat/UI/language save can conservatively invalidate a job reading that source. Safe default migration and true clinical-generation fencing are required; ignoring the revision would hide real source changes.
3. Scoped uploaded images, upload-mask staging/promotion, model selection and manual edit APIs need complete production integration. The common conversational factory boundary does not complete all HTTP routes.
4. Actual image collections/planning-reference selection, per-image hierarchy and mutually exclusive MPR backgrounds remain unimplemented.
5. Actual vivid implanted-seed mesh/MPR rendering, individual controls, uncertainty glyphs and restore/load fencing remain pending. Stored role/color metadata is not a rendered implant.
6. Authenticated review interfaces and service bindings are needed for detected centers/axes, source parameters and rigid guide placement. Existing journals/services are not a completed operator workflow.
7. Anatomy registration, visible-guide reconstruction and accepted rigid reuse need end-to-end integration and operational validation. A metadata frame match or soft-tissue deformation is not printed-guide pose authority.
8. Natural-language mutation of a different timepoint needs authenticated target-confirmation receipts. The current conservative selection/resubmission boundary is not the final cross-workspace interaction design.
9. Manual dose/edit, Monitor, report/autofill/export, screenshots, caches, annotations and artifact download/UI actions still contain Session-only paths. They remain gated for named-workspace delivery.
10. Durable workflow restart/cancellation/recovery, manufactured-artifact lifecycle, default deletion, archive/export/import graph remapping, quota transactions and retention need further engineering.
11. Reports/native clinical tool operational strings still need a source-bound language audit alongside the future panel bridge. New message localization cannot certify every historical string.
12. Real supplied-model, phantom, GPU, registration, print/strength and operator-browser acceptance remain required before release. Existing real public-origin/proxy checks are not waived by synthetic tests.

The candidate is resumable, but the complete user-visible multi-timepoint intraoperative feature is **not complete** and is **not deployed**. The remaining steps should be implemented in the same scoped graph rather than by enabling a flag, cloning four DOM panels, or copying a mutable plan between scans.
