# Monitor edit evidence and interaction

Implemented against remote working tree at a50fef033; unrelated in-progress LLM/context changes were preserved.

## Behavior

- Successful manual geometry commits capture server-owned before/after geometry, stable object IDs and saved dose metrics under the existing per-case transaction lock.
- Feedback identifies edited objects and displacement, new/worsened/resolved spacing conflicts, and comparable saved score/coverage/OAR deltas. It does not infer a model-noise threshold from a small difference.
- If several edits precede recomputation, dose differences are explicitly attributed to the whole sequence. Geometry evidence still describes the latest individual edit. Changes to anatomy/configuration invalidate dose comparability.
- Committed edits bypass the generic screenshot throttle. Captures are serialized, tied to case/run/planning version, and have independent attachment identities. A superseded checkpoint is not illustrated with a later plan.
- Screenshots use existing visibility verification and reversible camera/display handling. Purple arrows indicate the previous position of the edited object. They are not predicted dose-optimal destinations. Screenshots occur after commit, not continuously during pointer movement.
- A feedback message offers restore/keep buttons and explicit numbered chat commands. The server stores one inverse for the latest edit, expiring after 15 minutes. Restoration requires the same case/run/version/geometry and uses normal edit validation; it does not bypass safety checks. Restored geometry requires dose recomputation.
- Compact edit facts are available to ordinary chat. Simple edit-comparison queries use the bounded evidence endpoint without additional model calls.
- Successful dose publication clears the geometry-only marker. Global seed-conflict totals are counted before truncating displayed details.

## Verification

435 related Python tests passed, including 16 new edit-evidence/transaction tests. Frontend simulation suites passed for monitor capture, serialized edit checkpoints, attachment identity, chat lifecycle, and visual reveal/restore. Git diff whitespace checks passed.

Covered: late-numbered edited seeds beyond the global 50-detail cap, stale/forged decisions, exact seed undo, combined needle/seed undo, cumulative dose attribution, anatomy changes, OAR deltas and case switching.

These are automated source/transaction/simulated-browser checks. Actual GPU recomputation and visual inspection of the new overlays in a live patient Viewer remain unverified. No candidate-position dose optimization or clinical acceptance model was added.
