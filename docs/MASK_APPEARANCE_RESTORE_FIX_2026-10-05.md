# Mask Appearance Restoration Repair

Date: 2026-10-05. Scope: the LAN/debug checkout at
`/home/lht/snap/brachyplan/BrachyBot`, not `BrachyBot-release`.

## Symptom and root causes

Previously saved upload-mask colours, opacity and visibility could revert to
defaults when resources were reloaded after a session switch or server restart.
These failures are in frontend identity and reconciliation, not proof that the
server's durable snapshot store loses the data on every restart.

1. The staged presentation index did not retain all equivalent durable identities
   (snapshot map key, `mask:<id>`, snake-case UI-bridge object/node identifiers,
   and legacy DOM IDs). Live edits could therefore fail to update the record
   subsequently read by resource/mesh loaders.
2. Mask appearance lives under `viewer.masks.labels`. The existing browser/Agent
   merge handled `data_tree` but omitted Agent-only mask styles. A partial browser
   projection could hide valid saved fields. Legacy bridge checkpoints also use
   `data_tree.nodes` for mask presentation.
3. Catalogue hydration used hard-coded colour, opacity and visibility defaults
   when there was no existing local record, even when server metadata supplied
   an appearance fallback.
4. A newly uploaded mask could have no presentation record in the staged snapshot.
   Its subsequent live edit was not registered for late loaders.
5. A later snapshot reconciliation copied the original snapshot's appearance
   over an edit made during resource loading.

Different uploads can legitimately have the same display name, such as `Label 2`.
Names and segmentation label values are not globally unique object identities;
this repair does not collapse separate uploads or change their label meaning.

## Repair contract

- Mask records are indexed by family-scoped durable identities and explicit
  aliases. Every alias for the same object shares one mutable presentation record.
  An unknown mask with a supplied durable ID does not borrow another upload's
  style based on its label/name or a CTV/OAR alias.
- Agent mask styles and legacy bridge presentation are staged first; a browser
  mask projection overrides only fields it actually contains. Neither voxel
  data nor classification is recovered from this presentation-only registry.
- A live mask edit can create its own presentation record. Catalogue loading,
  mesh appearance and late snapshot reconciliation use that same registry.
- Defaults are used only when saved/live/server presentation is absent. Opacity
  `0` and explicit hidden flags remain valid, not missing values.
- Server classification remains authoritative. CTV/OAR-promoted masks are not
  recreated as standalone unclassified-mask volumes. Manual/threshold masks keep
  their existing restore and voxel-Set semantics.
- Existing session/generation fencing is retained; an old-case response cannot
  write into a newly selected case.

## Files

| File | Purpose |
| --- | --- |
| `web/app/static/js/brachybot-workspace.js` | Identity-aware staging, field-level merge, live-record updates and late snapshot reconciliation |
| `web/app/static/js/brachybot-viewer-volume.js` | Server appearance fallback without replacing saved/live style |
| `web/app/index.html` | Cache versions: viewer-volume 85, workspace 71 |
| `tests/mask-appearance-restore.test.cjs` | Actual cross-module function regressions using synthetic resource responses |
| `tests/test_mask_appearance_restore.py` | Node harness integration and durable WorkspaceStore cold-reload/case-switch test |
| `tests/test_workspace_frontend.py` | Preserve the sibling-retention contract while asserting registry-aware snapshot reconciliation |

No backend product source, model, clinical geometry, patient case, database,
upload classification rule or public-release checkout is changed.

## Validation status

The 14-scenario JavaScript harness uses the actual presentation registry,
catalogue loader, colour/opacity setters, workspace serializer, and mask snapshot
reconciliation branch. It does not substitute an always-successful presentation
writer. The final harness fails 10 scenarios and passes 4 on the unchanged source;
the repaired source passes all 14. Tests explicitly include same-name uploads, zero opacity,
hidden flags, partial browser snapshots, Agent-only styles, repeat hydration,
fresh frontend runtimes, editing during hydration, classification, manual masks,
and late old-case responses. The added sibling scenario verifies that one uploaded
label promoted to CTV does not erase an unclassified sibling absent from the
browser snapshot. Mesh appearance is checked after a live edit and a fresh runtime.

Remote current-source validation in a private detached directory completed:

- Node.js actual-function harness: **14 passed, 0 failed**.
- Existing live Data Tree presentation and browser/Agent tree-merge harnesses:
  **passed**.
- Full application `tests/`: **2,175 passed, 2 skipped, 17 warnings, 4 subtests
  passed**, in 51.15 seconds. This is the application suite, not the nested
  benchmark evaluation suite or a clinical planning experiment.
- JavaScript syntax checks passed for both changed scripts.
- The new Python tests exercise completed snapshot writes, a fresh WorkspaceStore
  instance, repeated A/B session selection with the same raw mask ID, and a
  chat-only patch that must not erase mask styles.

The first detached run was not green: **3 failed, 2,172 passed, 2 skipped**.
One old source-string assertion required directly copying the old mask snapshot;
it was updated to require live-registry reconciliation, with actual-function
regression coverage rather than relaxed sibling-retention semantics. The other
two failures were model-availability probes resolving deployment paths relative
to `/tmp`. The final run sets `BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan`
for read-only model lookup; model code, weights and default availability rules
were not altered to make those tests pass.

Node.js v24.20.0, already bundled with the remote VS Code server, was added only
to the test process's PATH. No Node installation or production environment change
was performed. Logs and the selected-file hash manifest are retained in the
private directory `/tmp/brachybot-mask-appearance-delivery-20261005`.

The delivery helper refuses a changed HEAD or changed selected-file hash, creates
a mode-0700 backup of the pre-edit files, replaces only this repair's seven files,
and publishes the HTML cache versions after both JavaScript files are present.
It does not reset or overwrite unrelated work, commit, push or restart a service.

## Delivered-worktree verification

The full application suite was repeated in the actual LAN checkout after
delivery, without a deployment-path override: **2,175 passed, 2 skipped,
17 warnings, 4 subtests passed**, in 51.22 seconds. The two skips are existing
public-deployment integration checks: missing `deploy/public/requirements.txt`
for `test_public_http.py`, and no `NGINX_TEST_BINARY` for `test_public_proxy.py`.
No mask-appearance test or Node-based browser-function harness was skipped.
Warnings are existing SWIG and naive-UTC deprecations, not test failures.

`git diff --check` and both JavaScript syntax checks passed on the delivered
files. HTTP responses from the running LAN server match the changed scripts'
SHA-256 hashes, and the served index references viewer-volume **85** and workspace
**71**. Both the LAN listener (PID 987025, port 8080) and the independent public
listener (PID 986735, port 18082) remained unchanged during this repair; these
PIDs are point-in-time evidence, not persistent configuration.

The original selected files are recoverable in the restricted backup
`/tmp/brachybot-mask-appearance-backup-20261005-ye8fkgkh`. The initial manifest
and final selected-file hash manifest are retained with the delivery evidence.
The checked HEAD is `a7609fa920681ee705444d379dd12c0950e7b09f`; its preceding
security-review commit was made by other work before this repair's delivery.
This repair itself made no Git commit or push.

## Acceptance and limits

Refresh the LAN page to load both new asset versions; a Python server restart is
not required for these JavaScript changes. Do not reload during an unsaved edit.
Set distinct colours and opacity on two uploaded masks, allow the workspace save
to complete, switch to another case, then return and reload resources. The Data
Tree swatches and 2D/3D mask styles should match the saved values. Repeat after the
next planned server restart, and confirm that CTV/OAR-promoted masks remain in
their correct classification rather than reappearing as duplicate open masks.

The automated tests use synthetic cases and resource responses; they do not
constitute a real browser interaction or a restart of the live clinical service.
Historical styles already overwritten in the durable snapshot cannot be inferred
or reconstructed by this fix. An edit interrupted before its save is acknowledged
is outside the completed-save durability guarantee.
