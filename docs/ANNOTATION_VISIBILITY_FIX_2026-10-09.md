# Planning Annotation Visibility: Root Cause and Repair

Date: 2026-10-09  
Checkout: `/home/lht/snap/brachyplan/BrachyBot`  
Base commit: `0d840e38bea3fb36b8e9b3cf3acb33220062f3bc`

## Reproduction and root cause

Planning distance annotations are 3D-only records, separate from their physical needle, seed, and guide sources. They nevertheless inherited two independently writable visibility fields: the master `visible` field and the per-view `visible3D` field.

The single Data Tree eye toggled only `visible`. The 3D context action wrote only `visible3D`. The renderer required both fields to be enabled. A record hidden in 3D could therefore remain invisible after a master show operation. The eye also ignored the per-view field when representing the record's state. A restored legacy record could contain the same disagreement.

This was reproduced using actual Chromium mouse clicks on product-generated Data Tree rows: ordinary single toggles passed, but both seed and guide labels failed to reappear after the 3D hide path. The initial five-test reproduction produced three passes and two failures. This establishes a real state-contract defect without assuming that every possible cause of an invisible label is the same defect. No live patient case was read or modified to reproduce it.

A separate presentation problem occurs with dense labels: an enabled individual label may remain in the overlap cluster, making a successful show command appear ineffective.

## Implemented contract

For the `planning_distance` family only:

- An explicit master or 3D visibility operation updates both `visible` and `visible3D`; `visible2D` remains false.
- If one explicit patch contains conflicting boolean visibility values, hiding takes precedence.
- Legacy saved records are normalized conservatively: either saved false flag keeps the annotation hidden. Loading does not silently reveal a previously hidden annotation.
- The single eye resolves both existing flags, and its appearance and accessible pressed state reflect the same 3D-only visibility contract.
- Single eye actions, programmatic `setDataItemVisibility`, 3D context actions, overflow-list checkboxes, and batch actions write the canonical annotation record.
- Live preferences continue to update the existing case-owned workspace presentation index. A late authoritative packet or cold restore does not overwrite the user's choice.
- Showing one annotation gives it rendering priority and highlights its actual needle axis. Hiding it removes that focus. Bulk show does not choose an arbitrary individual label for focus.

This normalization is not applied to CT, masks, OARs, physical needles/seeds, or manual measurements. Those objects retain their existing independent 2D/3D presentation contracts.

## Preserved behavior and limits

The repair does not recalculate dose, regenerate a guide, modify geometry, move the camera, alter distance values, or reveal a hidden source mesh. Source-object visibility, plan/session/version ownership, geometry consistency, and annotation opacity remain rendering prerequisites.

An annotation with zero opacity, a hidden source, or an anchor outside the current viewport is not forcibly displayed. Data Tree tooltips distinguish annotation visibility from the prerequisite that its source object must be visible.

Guide-entry and seed labels retain the corrected English terminology from the preceding localization change. Tooltip strings use the global language manager. Both changed script URLs receive new asset version numbers so a normal reload can load the repaired frontend.

## Regression coverage

The new browser regression file exercises:

1. Actual eye clicks for every record in a synthetic two-seed/one-guide plan.
2. Hiding through the real `_setNodeViewVisibility` executor and showing through the eye.
3. Legacy split flags, eye appearance, and retained color/opacity.
4. Actual Show all / Hide all buttons, with guide and manual-measurement isolation.
5. Programmatic single visibility and cold workspace restore through the real presentation registry.
6. Dense 180-seed rendering, ensuring the individually requested label is drawn.
7. Hidden-source and zero-opacity preservation.
8. English/Chinese tooltips and accessible visibility state.

Existing annotation, artifact-tree, and workspace tests remain unchanged. The new file contains 12 browser regression cases. The initial focused run passed 202 tests. The final full product suite passed **3,332 tests**, with **2 skipped**, **4 passing subtests**, and no failures or collection errors. Deployed verification and the existing deprecation warnings are recorded in the evidence directory below. This is not a full benchmark evaluation or clinical physics validation.

## Delivery and evidence

Only five selected files are delivered: two product JavaScript modules, the HTML script-version references, the new browser tests, and this document. Before/after SHA-256 checks preserve the preceding localization changes and reject concurrent edits. Existing unrelated working-tree changes are retained.

Private evidence:

`/home/lht/.local/share/brachybot-annotation-visibility/validation-20261009-58Dhh0`

The delivery includes a private backup, manifest, test results, and served-asset checks. The independent public-release checkout is not modified. No server restart, commit, push, patient operation, or GPU planning run is required by this frontend repair.

After saving any current edit, reload the page to replace its already loaded JavaScript. Existing annotations and their stored appearance are reused; no new planning or guide generation is needed.
