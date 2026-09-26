# Monitor interaction refactor — 2026-09-26

Baseline: remote LAN checkout `/home/lht/snap/brachyplan/BrachyBot`, HEAD `eae7edb50`, initially clean. The public-release checkout is outside this change.

## Findings and resulting behavior

- Geometry commits already computed authoritative edit evidence, but the browser waited for an additional `/api/ui/event` request before showing it. Successful commit responses now carry a bounded `monitor_checkpoint` derived from that same transaction. The existing event endpoint remains supported. No model call was added.
- Feedback, screenshot messages and dose results had separate identities. A new monitor interaction module owns cards by session, run and geometry-event identity. Dose publications enrich the original card; independent edits retain their own cards. Duplicate and older responses cannot repaint a newer checkpoint. Cards retain images through normal chat attachment persistence.
- Monitoring used the ordinary per-drag replan prompts. In active monitoring, a successful geometry edit now leads directly to a coaching card with an explicit dose-comparison button. Existing geometry safety validation and rejection/rollback still apply. An already explicit seed-recompute decision is honored. Outside monitoring the existing prompts remain unchanged.
- The card identifies moved objects, new/worsened/resolved spacing findings, separately labeled dose deltas and a concrete next step. Cumulative dose comparisons explicitly describe the edit sequence. Buttons use the existing authorized restore/keep endpoint. Failed screenshots have a retry action; stopping monitoring disables live card actions and settles pending image status.
- Automatic captures are case/run/version fenced and also reject an in-progress or changed live drag preview. One capture transaction at a time can change shared Viewer presentation. For a single monitor frame, display/camera state is restored immediately after pixels and grounding are frozen, before upload and annotation. Capture-time reveal/occluder metadata is retained after that restoration.
- Movement screenshots include the pre-edit endpoint in the framing bounds. When movement is approximately aligned with the camera, the camera uses a side direction to make displacement visible. Color/opacity/scale are not rewritten by framing. Return arrows describe only the recorded pre-edit position.
- Dose-only version changes keep a restore inverse usable only if the exact geometry and planning identity are unchanged. Consumed decisions no longer return an unusable restore token. Decisions made during an expensive transaction return a retryable busy response without waiting for a browser timeout or consuming the inverse.
- Screenshot failure results now consistently contain a boolean success value. The visual regression harness was updated to load the actual target-verification helper.

## Verification

- Full Python suite during implementation: 1882 passed, 8 skipped, 4 subtests passed.
- Final affected Python suite after the remaining changes and busy-decision regression: 306 passed.
- JavaScript integration checks cover checkpoint identity, duplicate delivery, dose enrichment, late responses, case/run switching, capture retry, stop recovery, visibility/restore, ordinary guide commands, and report framing/read-only capture.
- Headless Chrome with synthetic objects verifies real card buttons, retry and stop behavior, Three.js side-view framing, inclusion of the old endpoint, and exact camera/color restoration. This never opens or edits a patient session.
- Capture orchestration test holds the upload pending and confirms that temporary node/parent visibility and the Viewer transaction are already restored/released; annotation cannot hold those temporary settings.
- A broad initial JS harness run also exposed pre-existing fixture failures in `chat_screenshot_delivery.cjs` (missing `uiActionTasks` in its isolated VM) and `test-report-lifecycle.cjs` (old lifecycle expectation in an unchanged report source). These unrelated harnesses are not claimed to pass.

## Limits

This is feedback on committed edits, not a prediction while a mouse button remains held. Geometry feedback does not wait for dose computation. Dose comparisons still require a valid baseline and successful calculation using the same anatomy/configuration. No calibrated noise threshold or dose-optimal destination is inferred from a score.

The change does not add a candidate-search/physics-validation optimizer. The previous position is an available undo reference, not a certified safe or clinically optimal recommendation. Existing inverse validation may reject restoration if it worsens spacing.

Actual GPU inference and visual acceptance in a real patient case have not been exercised by this change. Automated tests use synthetic geometry and controlled dose results; startup/HTTP checks verify deployment only.
