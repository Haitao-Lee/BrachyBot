# Report completion and capture repair — 2026-09-17

Base: remote BrachyBot HEAD `91006161e467e9f8c9dabc0b09bb5ca31cf345dd`, including its existing uncommitted changes. Deployment checked SHA-256 preimages before replacing each reviewed file. Preimages retained in `/tmp/brachybot-report-workflow-9wagW7/preimage` (temporary, not permanent archival storage).

## Findings and changes

- The chat capped waiting for browser UI actions at 30 seconds, then allowed the server's premature success reply to appear. It now waits for action settlement; cancellation remains interruptible. A server `done` event no longer marks a case complete while local UI actions remain.
- UI progress appended pending and completed events as separate rows. It now updates the existing action ID, avoiding residual pending rows.
- Backend report dispatch claimed screenshots and persistence were complete without a browser acknowledgment. Backend wording now acknowledges dispatch only; browser success wording is emitted only after report generation succeeds. The final trace row remains pending until that result.
- The report watchdog previously reset presentation/progress but did not settle a stuck capture promise. It now rejects the capture, invalidates late results and restores presentation.
- Figure 1 overview previously enabled arbitrary meshes. It now allow-lists treatment/anatomy objects, excludes dose isosurfaces, guide/skin and unrelated upload masks, and temporarily disables vertex-color dose presentation. Close-up retains its target/seed/needle profile. Immediately before capture, an unexpected dose presentation fails closed.
- Figure 2 axial/sagittal/coronal panels use CT plus dose at 0.75 offscreen opacity and contours/planning projections, without opaque label fills, crosshairs or interactive annotations. Hidden live dose canvases can be included after requested-slice readiness is verified. Live CSS opacity and layer settings are not overwritten.
- Presentation restoration includes material vertex-color flags and dose-mode intent. Workspace presentation writes are locked during temporary capture. Restoration errors cannot silently become success.
- Figure contracts were bumped for Figure 1 and 2(a–c). Export validates canonical group/subfigure and normal-surface mode; workspace restoration rejects obsolete Figure 1 captures. Old images are not relabeled as new valid evidence.

## Verification

- Python: 171 passed across report capture/progress/DVH/pagination/layout, screenshot trace and whole-request routing.
- Python runtime contracts: 38 passed, 1 deselected. The excluded existing test expects UI API cache version 90 while the pre-existing remote index already uses a later version. Three SWIG deprecation warnings remain.
- Node: `report-workflow-completion.test.cjs`, `report-readonly-capture.test.cjs`, `report-planning-state.test.cjs`, `test-report-lifecycle.cjs` passed. New behavioral tests exercise action completion, abort, rejection, progress upsert, hidden-dose composition, canonical slot rejection, watchdog settlement and restoration.
- Modified JavaScript passed `node --check`; backend Python passed compilation.
- Internal service restarted after no active workspaces were detected: PID 1123148, port 8080, HTTP 200. Public release not changed.

## Remaining acceptance boundary

No authenticated patient browser was available to this agent. The supplied case has not yet been regenerated and visually compared page by page. Browser refresh is necessary for updated script URLs; old PDF files do not change retroactively. Regenerate the report to obtain the new figure contract. This change does not alter clinical planning, dose calculation, or segmentation outputs.
