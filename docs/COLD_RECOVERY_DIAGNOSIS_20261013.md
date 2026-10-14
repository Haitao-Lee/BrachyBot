# Cold recovery diagnosis and minimal repair audit — 2026-10-13

Historical audit of SHA256 `0876376f4b9e3ad9866329ca9723211ba46d75eada8cc40994b13b0372d962da`.
Subsequent guarded fixes and exact reruns are recorded separately in
`COLD_RECOVERY_FINAL_REPAIR_20261013.md`; the original counterexamples below
remain the findings for this saved source, not claims about all later versions.

## Verdict and scope

The current repair removes the known `hydrate(item) -> restoreActive() -> hydrate(item)` self-promise path and serializes generic restoration for callers that begin on the same mounted generation. The completed focused run confirms 11 frontend contracts plus the actual two-timepoint upload/switch/cold/native-import flow: **12 passed in 188.55 seconds**. This is specific integration evidence, not a full-suite or supplied-model cold-restore pass.

There are remaining scheduling/ownership gaps. The most consequential is that a concurrent metadata observer can replace the revision against which an already-running resource hydration checks drift. Controlled execution of the exact current source reproduces readiness becoming true after a revision-1 resource producer starts and a revision-2 receipt is accepted, without a remount. Two other generation cases permit old callers to affect a newer mount. These are source-level counterexamples with synthetic deferred receipts; they are not claims of another observed real-browser failure.

This sidecar made no changes to product source, frontend source, existing tests, production, frozen checkouts, or the mutable remote checkout. It launched no server, model/provider request, browser product test, or full suite. New files are confined to this report and `work/cold-recovery-diagnostic-20261013-minimal-audit/`. Per the follow-up instruction, it did not replay the old immutable browser failure or inspect patient/runtime data. Main's running tests were only observed through completed logs and process metadata.

## Audited source identity

Local candidate: `C:/Users/hunte/OneDrive/Dokumen/ssh/timepoints-implementation-20261010`.

Remote stage: `/tmp/brachybot-timepoints-stage-20261010-E1Rvjz` on `rtx3090_external`.

The local candidate and remote `product-browser-checkout/web/app/static/js/brachybot-timepoint-workspace.js` matched SHA-256:

`0876376f4b9e3ad9866329ca9723211ba46d75eada8cc40994b13b0372d962da`.

The remote current-vs-`lan-deployment-frozen-20261013-checkout` diff has only three functional repair areas in this file:

1. Clinical drift in `hydrateResources` now calls `controller().reload()` and hydrates a distinct successor item; it no longer calls generic `restoreActive()`.
2. `restoreActive` stores one task under `[sessionId, timepointId, generation]`, returns the existing task to same-key callers, and deletes only its own task on settlement.
3. `restoreActiveResources` waits for the initially mounted item's hydration before starting its metadata read/readiness reset.

The exact four source-function sections used in this audit are preserved as `audited-source-extract.js`, independent of future candidate changes. No formal product test was edited or added.

## Completed log/XML evidence

All six listed logs were read in full for parsing and hashing. Every corresponding XML that exists was parsed in full. SHA-256, file sizes, suite attributes, failure identities, and the 12 focused testcase names are in `completed-log-audit.json`.

| Stage-relative artifact stem | Result | Actual failure boundary |
| --- | --- | --- |
| `lan-deployment-frozen-full-20261013` | 4524 passed, 2 failed, 2 skipped; 4 subtests passed; 1569.75 s | Native import: timepoint browser line 159. Implant cold reload: implant browser line 86. |
| `lan-cold-product-repeat-20261013` | 1 failed; 57.77 s | Add TP wait at timepoint browser line 55; final diagnostic was `{}`. |
| `lan-cold-after-reentry-20261013` | 1 failed; 197.26 s | Native import line 159, after the earlier direct-only repair. No matching XML present at the parsed path. |
| `lan-hydration-product-repair-20261013` | 13 passed, 3 failed; 426.04 s | Initial navigation: timepoint line 26, implant line 16, native intraoperative line 15. These did not reach cold restoration. |
| `lan-hydration-serialized-current-20261013` | **12 passed**; 188.55 s | 11 frontend contracts and the actual two-timepoint product test, no failure. Product testcase time: 179.199 s. |
| `lan-implant-cold-serialized-current-20261013` | **1 failed**; 66.29 s | `page.goto` timeout at implant line 16, waiting for `domcontentloaded`; `SCENE {}`. Did not reach implant cold reload at line 86. |

The last row is the completed PID 1968158 run. This audit establishes its failure location, not the cause of the initial page-load timeout. It cannot be used to claim success or regression of implant cold restoration.

The old native-import trace shows loaded CT, the intended session/timepoint mounted, visual readiness reporting `visual_restore_complete`, but bridge `ready:false` and `status:'dose_stale'`. That is not a missing-CT or empty-backend diagnostic. In current `selectDose`, stale/unavailable dose returns false and leaves the corresponding status, while `hydrateResources` intentionally proceeds to final workspace validation and may set bridge readiness true. Therefore `dose_stale` alone cannot explain the old permanent readiness failure.

The old generic path could return the same pending hydration promise when recovery observed an already-rebased cached receipt. The direct-remount repair removes that dependency edge. The direct-only native-import failure and the later serialized native-import pass additionally support concurrent generic restoration/readiness reset as part of the integration failure. The historical logs do not identify the exact competing caller or prove every interleaving; no stronger caller-level historical trace is claimed here. None of these findings establishes a broken NAS, and no storage policy change follows from them.

## Remaining correctness findings

### 1. Resource drift is compared with a mutable cached receipt — high priority

Relevant current lines in `brachybot-timepoint-workspace.js`: 182, 199, 210–213, 350–356; producer paths at 278–285, 364–369, 402, and 405–416.

`hydrateResources` starts `hydrateTimepointWorkspace(item.workspace, ...)`, but later compares the final server clinical revision against **the then-current `item.workspace`**, rather than the receipt supplied to that resource producer. `observeCommittedState` replaces `entry(scope).workspace` in the meantime. That observer is used after accepted planning-config and image operations, and is guarded by mount identity, not by the ongoing hydration's resource revision.

Repeatable diagnostic schedule, using both actual `hydrateResources` and actual `observeCommittedState`:

1. Hydration starts with resource input clinical revision 1 and is held at its producer barrier.
2. The observer accepts a revision-2 response and replaces the same item's cached workspace.
3. The revision-1 producer completes; the final response also has revision 2.
4. The comparison reads `2 === 2`, performs zero remounts, and sets `item.ready = true`.

Recorded result: `resourceInputRevision:1`, `cachedReceiptRevision:2`, `reloads:0`, `bridgeReady:true`.

Required invariant: final readiness must validate the clinical/lifecycle/resource receipt actually consumed by this hydration, held immutable across awaits. Updating the metadata cache must not certify an older resource load. Preserve CAS on mutations; this is an additional resource-readiness fence, not permission to rebase clinical writes. The diagnostic proves the control-flow gap, not stale clinical geometry in a real case.

### 2. Waiting recovery may adopt an unrelated generation, bypassing coalescing — medium priority

Relevant lines: task key at 261–263; pending wait and successor check at 316–325.

After `await pending`, the check only compares session/timepoint IDs. This permits a recovery begun on A generation 1 to continue after navigation A1 → B2 → A3. It then resets A3 readiness and starts a generic metadata read even while A3's own hydration is pending, because it only awaited the earlier A1 promise.

Recorded schedule: A1 pending restore; mount B2, then A3; start and hold A3 hydration; release A1 with false. The old restore issues a generation-3 workspace read before A3 hydration settles and ultimately returns true. A1's cancellation did not cancel its generic restore.

There is a related intentional-remount case: a task entered under generation 1 can later operate on generation 2, while a second caller entered under generation 2 has a different `restoreTasks` key. Releasing both pending receipts produces two concurrent generic workspace reads against generation 2. Current coalescing is correct for the entry generation, but is not shared across the successor mount adopted by the old task. The bounded schedule settles successfully; it does not prove a deadlock or permanent readiness failure.

Required invariant: an old restore may follow only a successor explicitly created by its own recovery lineage, and must join that successor's in-flight work. An unrelated A→B→A mount cancels it. Avoid simply replacing every successor check with a generation equality check: clinical-drift recovery intentionally increments the generation and must remain functional.

### 3. A rejected old task can paint failure on a healthy newer mount — medium priority

Relevant lines: 267–268.

The outer `restoreActive` catch checks only matching session/timepoint IDs before calling `status('failed')`. A generation-1 metadata request can fail after a healthy generation-2 mount of the same timepoint has become ready. The catch then changes generation 2's status to failed.

Recorded result: generation 2 remains `ready:true`, but its status becomes `failed` after the old request rejects. This is incorrect failure attribution and can expose a spurious retry UI; it is not a cross-timepoint data write.

Required invariant: rejection/final status must belong to the exact active owner or an explicitly tracked successor of that task. An unrelated older generation cannot change current status. Preserve identity-checked task cleanup, which is already correct.

### 4. Observation-loader false does not affect bridge readiness — existing contract gap

Relevant lines: workspace bridge 188 and 213; `brachybot-implant-observations.js` 137–141.

The real observation reload catches transport/acceptance failures and returns false. The bridge awaits the operation but ignores its result, so successful geometry/final metadata can produce `ready:true` after observation loading fails. The source-level diagnostic returns false from the observation producer and reproduces this result.

This predates the current minimal repair. A false observation result can also indicate supersession by another observation request, so indiscriminately treating every false as fatal would be incorrect. Required invariant: distinguish an owned resource failure from successful supersession/empty observations; genuine failures must remain explicitly partial/retryable under whatever readiness contract consumers rely on. Stale or absent optional planned dose must continue to be represented separately from geometry restoration failure.

## Bounded validation and useful invariants

`source-invariants.cjs` executes only extracted candidate functions in a VM with deterministic synthetic promise receipts. It does not mock a live product API or compute a synthetic scene. Its exit code 0 means every asserted expected behavior/counterexample reproduced; it does **not** mean all eight scenarios are product contracts that passed.

Three verified positive invariants:

- Same-generation restore callers share one generic recovery, wait for current mount hydration, then clear their task; stale dose remains representable with successful geometry readiness.
- Clinical drift creates a distinct fresh mount, completes its hydration, and cannot set the superseded item's ready bit.
- A pending A restore cannot follow a mount of B; it returns false without a generic workspace read.

Five reproduced counterexamples are in `source-invariants-results.json`: mutable receipt hides resource drift; old rejection paints newer status; A→B→A waiter retargets; old/new-generation task keys allow duplicate recovery; observation false is ignored.

Run from the candidate root:

```powershell
node .\work\cold-recovery-diagnostic-20261013-minimal-audit\source-invariants.cjs
node .\work\cold-recovery-diagnostic-20261013-minimal-audit\source-invariants.cjs --snapshot
```

Both modes completed with exit code 0 and eight asserted scenarios. Snapshot mode replays the saved exact source extract; current mode audits the live candidate and reports its SHA-256.

Useful formal additions, still bounded and without changing real-browser timeout values:

1. Final resource receipt must equal the immutable input receipt even after `observeCommittedState` accepts a newer clinical revision.
2. Rejection from old A1 must leave healthy A2's ready/status untouched; task cleanup must not remove another owner's pending task.
3. Cancelled A1 waiter followed by B2→A3 must return false and cause no A3 readiness reset, metadata read, or presentation save.
4. Self-created A1→A2 drift successor plus a fresh A2 caller must share one recovery and one final readiness transition.
5. Partial geometry must never become ready or authorize presentation overwrite; a genuine observation error must remain distinguishable from intentional empty/stale optional-dose state.

The existing `timepoint-hydration-reentry.test.cjs` covers a drift remount and a changed-timepoint successor, but its generic `restoreActive` is a fixture function; it does not execute the new coalescing/wait logic or the same-ID generation cases above. Existing browser adapter contracts exercise one pending observation load, one network interruption/retry, and a changed-timepoint late loader; they do not close these additional schedules.

## Exact files read or searched

Paths below are relative to the local candidate unless stated otherwise. Sections were read for large frontend modules; whole-file/log parsing is explicitly identified where applicable.

Product source read:

- `web/app/static/js/brachybot-timepoint-workspace.js` — full source read for extraction/hash; restoration, image-observer, dose and ready paths inspected with line numbers.
- `web/app/static/js/brachybot-timepoints.js` — scope/request methods, save/CAS, select/reload, observeWorkspace, exposed controller methods.
- `web/app/static/js/brachybot-ui-api.js` — restore routing/coalescing, presentation-lock finalization, readiness replacement, hydration bridge.
- `web/app/static/js/brachybot-workspace.js` — legacy background scheduler ownership and suppression section; restore-call search results.
- `web/app/static/js/brachybot-implant-observations.js` — capture/mount guards, accept/reload, detection and correction restoration paths.
- `web/app/static/js/brachybot-chat-core.js` — restore-call search matches only, no full module audit.

Existing tests read:

- `tests/timepoint-product-browser.test.cjs`.
- `tests/implanted-product-browser.test.cjs`.
- `tests/test_timepoint_product_browser.py`.
- `tests/test_timepoint_workspace_frontend.py`.
- `tests/timepoint-hydration-reentry.test.cjs`.
- `tests/timepoint-workspace-runtime.test.cjs`.
- `tests/timepoint-restore-producers.test.cjs`.
- `tests/timepoint-workspace-browser.test.cjs` — targeted pending/retry/navigation sections.
- `tests/timepoint-chat-refresh.test.cjs` — search matches only.

Remote source read for diff/hash:

- `product-browser-checkout/web/app/static/js/brachybot-timepoint-workspace.js`.
- `lan-deployment-frozen-20261013-checkout/web/app/static/js/brachybot-timepoint-workspace.js`.

Remote logs/XML read in full: the six artifact stems in the evidence table, `.log` for each and `.xml` for all except the absent direct-only XML. Directory/process inventories were read; no SQLite contents, accounts, case artifacts, or production APIs were inspected.

## Handoff

Keep the current minimal repair's direct drift remount, same-generation coalescing, awaited hydration, ownership checks and server CAS guards. The passing actual two-timepoint flow is useful evidence to retain. Close the immutable resource-receipt gap first, then make successor/error attribution generation-aware with explicit recovery lineage. Implant cold restoration remains unverified by the latest run because its navigation failed before restoration; diagnose that page-load boundary independently if Main continues it. No increased timeout is proposed as a restoration repair.
