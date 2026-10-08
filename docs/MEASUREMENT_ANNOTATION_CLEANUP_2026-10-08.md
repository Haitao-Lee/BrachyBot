# Measurement Annotation Deletion and Clear-All Repair

## Follow-up: save-queue and feedback repair

The original implementation was functionally validated, but a later user log
revealed that duplicate Tree clicks during annotation persistence produced red
errors and that full-workspace saves could delay a small clear operation. The
subsequent repair is documented in
[Annotation Save Queue and Data Tree Feedback Audit](ANNOTATION_SAVE_UX_AUDIT_2026-10-08.md).
It adds scoped persistence, queue-content ownership, bounded response consumption,
neutral ticking pending feedback, and explicit case-owned missing-object handling.
The validation counts and source versions below describe the original delivery,
not a claim that its full user experience was already complete.

## Scope and baseline

Repair Data Tree deletion of Line/Angle annotations and add **Clear
measurements**. Rectangle overlays are measurements too, not CTV masks. Preserve
manual masks, SAT3D prompts, seeds, needles, CT, dose and DVH. Saved screenshots
are independent images: clearing annotations does not modify their pixels.

LAN baseline: `/home/lht/snap/brachyplan/BrachyBot`, commit
`e77dab7b4a9518f054d6d7c0f3be8b015fd0989c`. The public-release checkout is out
of scope. No patient mutation, inference, restart, commit or push is validation.

## Verified failure mechanisms

1. New annotations lacked durable IDs. Tree projection used array-position
   IDs such as `annotation_1`; removing an earlier row changed later identities.
2. Projection retained raw geometry types (`line`/`angle`) instead of setting
   `manual_annotation`. A saved ID without the `annotation_` prefix could be
   transported as a bare ID, not `annotation:<id>`. Annotation nodes also
   inherited a clinical planning ID.
3. The file-object deletion API checked the persisted snapshot, but drawing
   saved through a 700 ms debounce. A new browser annotation could be absent
   there. Missing-object reconciliation did not itself remove the still-live
   browser annotation. A menu entry did not prove working deletion.
4. Creation/history did not consistently refresh Tree rows. There was no
   explicit removal transaction, scoped clear control or meaningful labels.
5. Mounted Undo/Redo discovery used `viewer.annotations` without a complete
   registered executor contract. A legacy route could report a false Undo as
   success.

These are verified source defects, not a live-browser trace proving which one
caused this user's exact click.

## Design

### Stable identity and canonical projection

`ensureViewerAnnotationIdentities()` assigns IDs once, preserves existing IDs
and repairs missing/duplicate IDs. Drawing history, Tree rows and persistence
use the same identity. Projection keeps geometry as `annotationType`, sets
`type=manual_annotation`, publishes `annotation:<id>` and excludes clinical
planning ownership. Labels expose actual type, axis and recorded value, e.g.
`Angle · Axial · 54.9°`. Custom labels remain; missing physical information is
not replaced by an invented distance.

### Delete the working state through its own writer

Annotation-only Tree deletion calls `deleteViewerAnnotations()`, using the
same case-owned workspace writer as drawing and Undo, not the file-object API
that knows only a prior debounced snapshot. View and Tree update before save
payload capture. Existing authentication, editing leases, revisions and per-case
save serialization remain intact; no new endpoint or file deletion is added.

Non-annotation and mixed file-object deletion keep the existing backend path.
This repair does not claim to redesign mixed clinical/artifact transactions.
Direct server annotation deletion still acts on saved objects, not unsaved
browser rows.

### Precisely scoped, reversible clear

The toolbar control sits beside Undo/Redo, uses existing button styling and the
global confirmation dialog, and selects only `line`, `angle` and `rect`. The
dialog states count, case scope and retained masks/prompts/planning data. Pending
measurement points can be cancelled; no manual-mask transaction is cleared.

Removal is one `annotation_remove` history transaction: Undo restores the batch
with its IDs/order, and Redo removes it again. This works for saved annotations
after reload even without their original creation history. SAT3D prompt clear
is separate.

Local view feedback is immediate; **Saving…** remains until save acknowledgement.
Duplicate/history edits are blocked while saving. Failure restores local rows
and history without claiming success. Late responses are fenced by case/CT
ownership and the annotation-array instance: they cannot restore rows or post
failure feedback into a different case. A late success is marked stale.
Read-only/incomplete-hydration states are rejected. Ambiguous transport failure
is not proof the server never committed; recovery is scheduled through the same
writer.

### Conversation parity

Controller registry, source/live discovery and browser dispatch agree on
`viewer.annotations` commands `undo`, `redo`, `clear_measurements`. Clear calls
the exact toolbar executor and exposes its persisted/cancelled/stale result.
Empty/busy history is not reported as successful Undo.

Shared manual version `2026-10-08.2` adds `viewer.measurements.clear`. Current
static coverage is **220 bound controls, 67 cards** (60 usage contracts and 7
basic-input families), with no unknown static controls. The generated catalogue
is refreshed. Knowledge coverage is not arbitrary-model or clinical validation.

## Validation

Synthetic Chromium tests use real toolbar, measurement, context-menu, Tree-ID,
controller and confirmation functions. They cover unsaved/legacy rows,
sequential deletion, precise scope, preserved masks/prompts/plan, cancellation,
batch Undo/Redo, failed-save recovery, case transitions, read-only/hydration,
save status, duplicate requests, Chinese dialog/labels and empty-history
negative receipts. A real WorkspaceStore test verifies that an empty annotation
array persists rather than merging old records back. Existing regression suites
also run. Final counts/evidence are recorded after the full suite completes.

Final isolated regression: **3,028 passed, 2 skipped, 31 warnings and 4 passing
subtests in 193.02 seconds**, with zero failures or collection errors. The new
cleanup suites contribute **19 passing tests**. Python compilation and syntax
checks for all three changed JavaScript files pass. Both skips belong to public
HTTP/Nginx integration prerequisites, not cleanup tests; existing warnings
concern SimpleITK bindings and UTC datetime deprecation.

Reproduction:

```bash
cd /tmp/brachybot-measurement-cleanup-20261008-9j7AwX
export PYTHONPATH=.
export BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan
export PATH=/home/lht/.vscode-server/cli/servers/Stable-04c0d99f4fb0d8afe6ce4f0c58e31e183ac3e4b1/server:$PATH
/home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q tests/ \
  --junitxml=/tmp/brachybot-measurement-full-20261008.xml
```

The full XML and selected-file SHA manifest are retained at
`/home/lht/.local/share/brachybot-measurement-cleanup/validation-20261008`.
Delivery selects 12 files, validates original and delivered hashes, backs up
originals before writing and replaces the HTML entry last. Prior edits are
preserved; concurrent changes abort delivery instead of being overwritten.

These tests are not a paid model, live patient, GPU or power-loss validation.

## User workflow and activation

1. Reload the webpage to obtain the versioned frontend bundles.
2. Delete one measurement by right-clicking its row under **Artifacts &
   Annotations**, selecting Delete and confirming.
3. Clear all measurements with **Clear measurements** beside Undo/Redo and
   confirm the stated scope. Other data remain.
4. Undo restores the batch; Redo clears it again. Re-capture saved screenshots
   that should no longer contain the overlays.

GUI cleanup uses the existing workspace-save endpoint, not a new backend route.
New controller schemas/manual source need a controlled restart if a running
agent has already imported old modules. Source delivery does not mean the live
agent has reloaded. Do not restart an active case as a side effect.
