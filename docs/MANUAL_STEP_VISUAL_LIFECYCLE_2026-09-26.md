# Manual planning step result delivery — 2026-09-26

## Scope and baseline

LAN/debug checkout: `/home/lht/snap/brachyplan/BrachyBot`, HEAD `eae7edb50` with existing uncommitted Monitor work. Existing edits were preserved. No changes to the independent `BrachyBot-release` service, no commit created, and no patient planning/geometry mutation was run for verification.

## Confirmed causes

- The manual buttons use `/api/planning/run_step`, not the chat preview stream. The general results/seed projection did not provide a completed candidate-stage display before a seed plan existed.
- Trajectory initialization's close points were only ephemeral preview data. Clearing the preview removed them.
- The first partial fix reused the chat preview group for completed manual results, so ordinary stream cleanup could erase the result. Stages 3–5 only had informational rows, not a consistent visibility lifecycle.
- A hidden Viewer canvas could remain zero-sized, and the Input-panel completion did not reliably reveal the result panel.
- Candidate counts could trigger a nonexistent seed-geometry load. A prior seed-count projection counted plan entries instead of actual seeds.

## Result contract

`web/manual_step_outputs.py` records a plan-owned five-stage catalog immediately before the pipeline's existing planning snapshot publication. Candidate stages retain world-coordinate geometry; clinical seed, dose and DVH arrays are not duplicated. The initial paths and close points form one read-only output. Ordinary SSE previews retain their original sampling limits; completed manual geometry is not silently capped at 64/256/512 items.

`brachybot-manual-step-results.js` owns independent result layers and one visibility transaction per manual request. Completion and workspace restoration consume the same catalog. Earlier nodes stay available for review, but hide when the next step starts. Failed requests restore the previous visibility selection. Re-running an upstream stage retires its downstream result descriptors. New cases/plans do not inherit an unrelated catalog.

| Step | Visible output after successful completion |
| --- | --- |
| Trajectory init | One node controlling candidate paths and close points together in 3D |
| Trajectory refine | Refined trajectory layer |
| Seed planning | Existing canonical seed and needle objects, including their 2D projections |
| Dose calculation | Existing dose overlay/iso-surface products |
| Dose evaluation | DVH/metrics in Analysis; a stage node controls the DVH presentation |

Existing object colours, opacity and individual visibility preferences remain intact. Stage visibility is an additional display constraint, not a clinical mutation. Explicit child show actions and screenshot reveal/restore transactions account for the stage constraint. Report capture excludes candidate layers, uses its own display transaction, and restores manual presentation afterward.

## Delivery, failure and latency

- Concurrent clicks do not send duplicate step requests. A session transaction token prevents late completion from publishing into another case, including A → B → A.
- Computation success and incomplete visual delivery are reported separately; a loading failure does not instruct the user to recompute already-saved clinical results.
- The result panel opens automatically only if the operator stayed on Input. A panel deliberately selected during computation is preserved.
- Only the relevant seed/dose producers are awaited for visual completion; unrelated OAR reconstruction stays in the background and cannot reframe the newly focused manual output.
- Manual completion suppresses incidental report autofill/capture. No extra LLM call was introduced.
- Completed candidate lines are batched; close points use a single dynamically sized instanced draw call.

## Validation

- Related Python regression suite: **402 passed, 6 skipped**, 3 existing SimpleITK/SWIG deprecation warnings. The six workspace bridge tests skip because Node is unavailable on the remote host; they are not counted as passing.
- Nine local Node/browser scripts passed: manual-stage state, all five buttons, manual Viewer WebGL, visual-location reveal/restore, read-only report capture, report renderer restoration, hidden-report Viewer WebGL, workspace presentation merging, Data Tree target resolution.
- Manual Viewer test uses real Chromium/Three.js/WebGL pixel readback and the production stage-row renderer. It verifies one shared row, the DOM eye controlling both paths and points, chat cleanup isolation, next-stage hiding and failure rollback. Geometry tests include 1,000 paths and 300 close points.
- Backend tests verify all five step hooks run before snapshot publication, complete world-coordinate output, downstream retirement, and saved-plan activation/restoration.
- Python compilation, JavaScript syntax checks, and `git diff --check` passed.
- These are synthetic/runtime and regression checks, not a fresh five-step GPU run against the user's current clinical case.

## Runtime delivery

- Restarted only LAN/debug port 8080. Verified PID `2842360`, checkout working directory, `192.168.1.113:8080` listener, root HTTP 200, `/api/healthz` HTTP 200, and newly served manual-stage asset.
- Independent public-release PID `2746992` remained unchanged.
- Relevant assets: manual-step-results v2, manual-annotation v29, 3d-manual v113, viewer-volume v82, dvh-planning v42, ui-api v119, report-editor v54.
- Reload the page to load the new scripts. Historical outputs created before the durable catalog cannot recover unsaved close points retroactively; execute a new initialization if that old result needs the complete paths/close-points display. This repair does not silently rerun or replace the current patient plan.
