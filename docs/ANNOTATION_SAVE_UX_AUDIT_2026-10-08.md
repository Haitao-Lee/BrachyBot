# Annotation Save Queue and Data Tree Feedback Audit

## Scope and evidence boundary

LAN checkout: `/home/lht/snap/brachyplan/BrachyBot`.
Baseline: `ef08fbc653d5862adde8eaef83341c4333085f71`.
The independent public-release deployment is not changed.

The reported log shows three repeated "Annotations are being saved" errors
followed by a successful annotation-clear message. This is consistent with a
pending save receiving duplicate clicks, not proof of a permanent deadlock or
lost clinical data. The screenshot does not identify the original operation's
start time, HTTP timings, target ID, or snapshot revision. Exact production
latency and the identity of the earlier missing item cannot be reconstructed
from it alone. The mechanisms below are verified in source and controlled tests.

## Verified mechanisms

1. `deleteViewerAnnotations()` optimistically removes annotations, then awaits
   `persistWorkspace()` before returning a durable-success receipt. The browser
   remains annotation-busy throughout that wait.
2. A duplicate annotation-delete request threw an ordinary Error. The common
   Tree wrapper displayed it as a red "Data operation failed" chat row, although
   the original save could still succeed. The Clear button was disabled, but
   Tree actions and Undo/Redo did not consistently express the same pending state.
3. Annotation deletion used the full workspace writer with only `skipChat`.
   It still serialized report state, masks (including voxel Sets), controls,
   scene state, and the full Tree. It could also queue behind earlier saves.
4. A queued save built its payload only after the previous Promise resolved.
   Changing cases during that wait could serialize the new viewer under the old
   owner's ID. Merely binding request headers did not bind the captured content.
5. The workspace HTTP timeout ended when response headers arrived. A stalled
   JSON body could leave the caller and its annotation-busy state unresolved.
6. The missing-object handler used English substrings such as `missing` and
   `not found` to decide that data no longer existed. It then claimed the latest
   state was restored even though loader results were gathered with
   `Promise.allSettled()` without checking failures.

## Implemented contracts

### A. Pending is not failure

- A duplicate annotation mutation returns `{success:false, pending:true}`.
  It does not remove more rows, open another confirmation, or append a red error.
- Tree deletion is gated when its selection includes annotations being saved.
  Its context menu displays a disabled, neutral "Saving annotations…" item.
- Clear, Undo, Redo, and Clear SAT3D prompts are temporarily disabled during the
  annotation-save transaction; their prior disabled state is restored afterward.
  Camera navigation and unrelated viewer controls remain available.
- The existing Clear button shows elapsed saving time after two seconds and
  explains that the view is updated but server confirmation is pending. The
  status uses the global language selector. Timers are cleaned up in `finally`.
- The original success receipt remains contingent on persistence. Failures
  restore local geometry/history only while the same case and annotation-array
  owner remain current. Cancellation and stale results are not success.

### B. Scoped annotation persistence

The existing authenticated `/api/workspace/state` route accepts:

```json
{
  "session_id": "owned-case-id",
  "response_mode": "ack",
  "viewer_annotations": {
    "annotations": [],
    "data_tree_annotations": []
  }
}
```

This is a dedicated save scope, not a miniature `ui_state` replacement. Existing
`ui.state` merges are shallow; sending only a `viewer` fragment through that
legacy path would erase other presentation fields. `save_viewer_annotations()`
merges just the two array leaves under the authoritative case guard instead.

- Empty arrays mean clear; they are not omitted or merged with old rows.
- The two lists require object records, unique stable IDs, and matching identity
  sets. Lists are limited to 10,000 records each.
- The scoped route rejects mixed UI/report/chat/operation writes.
- Masks, settings, controls, OAR rows, report, chat, and clinical planning results
  are preserved. Cached-agent UI memory gets the same leaf changes in the same
  ordered case transaction. A cold GPU agent is never hydrated for this save.
- The response must explicitly identify `saved_scope: "viewer_annotations"`.
  A generic ACK from an old running server is not proof it understood the scope.

### C. Compatibility and queue ownership

- Modern saves submit only annotation geometry and its Tree projection, without
  invoking report, chat, or mask serialization.
- Recording the removal's Undo transaction no longer schedules a redundant full
  workspace save; the scoped transaction owns its own acknowledgement.
- Saves remain ordered per case. They do not bypass an earlier full snapshot,
  which could otherwise resurrect a deleted annotation by arriving afterward.
- Every queued payload is captured synchronously at submission, before waiting.
  A detached full save omits the active viewer rather than serializing another
  case's UI under a previous owner.
- An old process without scoped-save support uses the existing full-UI save as a
  compatibility fallback, omitting report and chat. That fallback is allowed only
  while the same case remains active, and its own ACK is required. It remains
  heavier than the modern path; a normal controlled backend restart activates
  the compact route. This is not silent success after an unsupported request.
- The HTTP deadline covers response-body consumption too. A timed-out response
  releases the Promise queue; it does not certify that the server did not commit.

### D. Honest missing-object feedback

- Tree delete/classification errors carry the actual HTTP status and originating
  case ID. English error-message substrings are not an absence oracle.
- Only an explicit, case-owned 404 triggers missing-object reconciliation.
- All requested loaders must settle successfully before claiming data was
  reloaded. Exceptions, false results, and case switches do not produce that claim.
- The message says the server could not find the selection and current case data
  was reloaded. It does not assert that a deleted item is known to be permanently
  gone or that all clinical state is proven current.

## Validation and activation

Validation uses synthetic CT/annotations, local temporary WorkspaceStores, mocked
network delays/failures, the real browser handlers, and the real workspace bridge.
It does not clear annotations or modify any real patient case.

Focused tests cover compact payload isolation, queued case changes, legacy ACKs,
JSON-body timeout, duplicate clicks, ticking/global-language status, context-menu
gating, undo/redo, failed-save restoration, cached-memory preservation, and missing
object reconciliation. Final test totals and delivery hashes are recorded in the
private validation evidence directory and the delivery manifest.

Final unfiltered product regression: **3,044 passed, 2 skipped, 4 subtests passed**
in 219.09 seconds, with 31 existing dependency/UTC deprecation warnings and no
test failures or collection errors. The two skips require public deployment
extras and an explicitly configured real Nginx binary; they are not annotation
test skips. This is the product `tests/` suite, not a claim to have executed
the independent benchmark corpus or a live clinical pilot.

Evidence: `/home/lht/.local/share/brachybot-annotation-save/validation-20261008/`
contains `full-suite.xml` and `manifest-final.json`. The final manifest covers
13 selected files. Product source is hash-checked against the tested isolated
stage before and after delivery; original files are recoverably backed up.

Frontend assets are versioned: annotation JS `v34`, viewer-volume JS `v93`, and
workspace JS `v74`. Refresh the browser to load them. Python route/store changes
need the normal controlled LAN server restart; an old process remains safe through
the fallback. Do not restart the independent public-release service.

## Limits and follow-up

This repair reduces serialization/network work but does not promise instant
storage acknowledgements. Earlier queued writes, the case lock, snapshot I/O,
quota checks, and a busy server can still delay completion. Keep the elapsed
status honest rather than declaring success early or bypassing write ordering.

Undo history remains browser-session state; saved annotation geometry survives
reload, but an earlier Undo transaction is not restored across reload. Saved
screenshots are immutable pixels and require recapture after annotation changes.
Mixed clinical-object deletion is not redefined as measurement clearing.
Timeouts after a possible server commit retain the existing guarded recovery-save
behavior; this is not a claim of distributed exactly-once mutation semantics.
