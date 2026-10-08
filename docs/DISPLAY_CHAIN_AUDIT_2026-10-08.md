# Display-chain audit and MPR segmentation remediation

Date: 2026-10-08 (Asia/Shanghai)

Scope: `/home/lht/snap/brachyplan/BrachyBot`, LAN/debug checkout only.
Baseline: `b05602f1d52fb2a64701d19fd605452ffc210e8b`.

## 1. Outcome and validation boundary

The missing 2D CTV/OAR overlays were traced to contradictory presentation
controls, not to evidence that the patient's segmentation had been deleted.
The supplied screenshot showed CT Only and unchecked CTV/OAR overlay controls.
Data Tree Show in 2D changed only a node's `visible2D`, leaving both renderer
gates closed. This failure is reproduced by synthetic DOM/canvas tests.

The implementation now opens the relevant segmentation toolbar gate and
switches CT Only to CT+Label when explicitly showing a CTV/OAR node in 2D.
Both inline MPR and the PNG fallback share presentation and label semantics.
Additional reproducible adjacent display defects are repaired below.

This is not a claim that every possible rendering defect, GPU/driver issue,
or clinical image alignment issue has been excluded. Product source paths and
the complete product `tests/` suite were reviewed/verified; vendor renderer
internals, all possible historical snapshots, and a real patient/browser
acceptance session were not exhaustively verified. The benchmark project's
separate test corpus was not run because this change is a product display repair.

## 2. Presentation contract

The clinical segmentation arrays are not modified by display operations.

Effective CTV/OAR MPR visibility requires:

1. A CT+Label or Label Only presentation mode.
2. The relevant CTV/OAR slice-overlay toolbar setting.
3. The node and its ancestors' master and 2D visibility settings.
4. A corresponding non-background voxel on the current slice.

Show in 2D now fulfills steps 1 and 2 as well as setting the selected owner in
step 3. It does not change 3D visibility, master visibility, independent child
hide choices, color, opacity, camera, or clinical data. An intentionally hidden
all-view parent remains a hard constraint; showing an ancestor does not erase
child preferences. An organ may legitimately have no pixels on a particular
slice even when all display gates are open.

The CTV/OAR toolbar checkboxes are MPR overlay controls. They no longer rewrite
the all-view master eyes and thereby hide/reveal the same objects in 3D.
Display mode and checkbox changes are saved as workspace presentation state.

## 3. Confirmed defects and repairs

| Issue | Root cause | Repair / evidence |
|---|---|---|
| Data Tree Show in 2D did not show CTV/OAR | Per-node switch changed while mode/toolbar gates remained closed | Common `_enableSegmentation2DForNodes` used by node, group, batch, and existing UI-context executor |
| MPR checkbox affected 3D | `toggleOverlay` wrote `ctv.visible`/`oar.visible` | Keep 2D toolbar control independent of master/3D state |
| Batch/group actions lost child choices | Batch view toggle rewrote CTV/OAR and trajectory descendants | Mutate selected owners; descendants inherit without being flattened |
| Segmentation collection omitted hand-drawn masks | Scope helper included open generic masks only | Include standalone manual/threshold masks while excluding promoted duplicate mirrors |
| PNG fallback ignored view-specific label state and colors | It used master `visible`, common CTV opacity, and server palette | Shared per-frame label presentation; transmit label visibility, color and alpha for both families |
| PNG overlay could differ from loaded label volume | Separate raw-array selection omitted effective registry changes and legacy source-specific normalization | `_viewer_display_label_arrays` is shared by binary label export and PNG overlay; preserves legacy alignment, GTV union and pancreatic anatomy rules |
| CTV disappeared beneath an overlapping OAR in fallback | Fallback painted CTV before OAR; inline MPR painted OAR before CTV | Parallel fetch, deterministic atomic OAR-then-CTV composition |
| Late overlay response restored obsolete content | Guard covered case/slice only, not presentation or request ownership | Per-axis abort/job identity plus case/generation/slice/presentation checks before decode and publish |
| PNG-based CT path never requested labels reliably | CT decode reconciled layer geometry but did not load segmentation | Start label fallback after base CT decode; allow it when label data exists but CT volume rendering is not ready |
| Label Only leaked CT or remained invisible after hydration | No-overlay branch painted grayscale; fallback opacity zero survived inline hydration | Black base in Label Only; restore inline canvas opacity explicitly |
| Pure black/zero-channel mask colors were wrong | `parseInt(...) || fallback` treated zero as missing | Validated shared RGB helper; black and pure green pixel tests |
| Overlapping manual masks lost later masks | First hit replaced the previous layer and broke the loop | Stable source-over composition for all visible manual masks |
| PNG labels could drift after dose transform-host creation | Copying CT inline transform missed the wrapper's transform | Use shared layer geometry and viewer transform synchronization |
| Stale window/level frame could overwrite current settings | Server response/cache keyed by slice only | Keys include case/generation/CT/window/level/threshold; recheck asynchronous PNG decoder |
| Preload omitted final slice and retained unbounded frames | Slider maximum treated as count; eviction list unused | Include final index; bound fallback cache to 64 frames per axis |
| Invalid restored client slice showed empty/incorrect data | Only server and axial lookup clamped indices | Shared client normalization for all planes and slider state |

No model inference, prescription, dose calculation, needle geometry, seed
geometry, clinical masks, or planning authorization policy was changed.

## 4. Code-path review map

### Directly inspected and changed

- `web/app/static/js/brachybot-viewer-volume.js`: Data Tree owners and
  hierarchy, context/batch visibility, segmentation load/presentation,
  window/level slices, inline composition, PNG fallback, color/opacity and
  fallback caching.
- `web/app/static/js/brachybot-viewer-layout.js`: server PNG decoding,
  asynchronous frame checks and label-layer handoff.
- `web/routes/viewer_routes.py`: physical-grid label loading, binary label
  export, PNG overlay, source-specific/effective segmentation resolution.
- `web/app/index.html`: script cache revisions; unchanged Viewer layout.

### Adjacent contracts inspected and protected by existing regression tests

- `web/structure_service.py`: effective CTV/OAR registry, source labels,
  classification, deleted and promoted structures. It is reused, not replaced.
- `brachybot-ui-api.js`: UI-context and natural-language display executors
  already call the same node/group entry points; no duplicate implementation.
- `brachybot-workspace.js`: persisted mode, checkbox and node appearance
  restoration remains authoritative; no forced default reset added.
- `brachybot-manual-annotation.js`: shared geometry/transform host and
  annotation/layer reconciliation.
- `brachybot-3d-manual.js`, `brachybot-depth-peeling.js`: mesh visibility,
  independent label presentation and transparent material controls remain
  unchanged; targeted 3D/toolbar and full-suite tests protect these contracts.
- Planning dose, seeds/needles, guide projections and report figures retain
  their existing loaders and evidence fencing. Existing planning visual,
  guide, report, coordinate, cache, appearance-restore and workspace tests
  were included in the full product suite. This is contract coverage, not a
  statement that every line of those modules was manually audited.

## 5. Verification

All tests used an isolated source snapshot:
`/tmp/brachybot-display-audit-20261008-9n5HOO`.

New tests:

- `tests/test_slice_segmentation_display.py`: 22 endpoint/pixel checks on
  synthetic volumes, including all planes, uploaded labels, head-neck GTV,
  pancreatic anatomy and registry-deleted targets; finite alpha and empty
  visibility selection semantics.
- `tests/test_slice_segmentation_display_browser.py`: 24 real Chromium
  DOM/canvas checks using product render/control functions on synthetic data.
  Covers global/per-node gates, colors, overlap, hidden children, Label Only,
  six out-of-range plane/index combinations, asynchronous case/color/hide/
  volume changes, window caches, PNG decode and transform-host handoff.

Full product suite on final logical code:

```text
2872 passed, 2 skipped, 31 warnings, 4 subtests passed in 134.67s
```

Log: `/tmp/display-final-full-tests-20261008.log`.
Skipped tests are not counted as successful validation. The warnings are
existing SWIG/deprecated datetime usage, not rendering failures.

The first full iteration had three static-contract failures: two tests froze
the previous layout asset revision and one referred to the old guard name.
The asset assertions were advanced from 47 to 48 alongside the real asset
bump; the stronger guard retained the `sliceIsCurrent` entry name. No ownership
guard, performance reference, expected clinical result or safety assertion was
weakened to obtain the final result.

Python compilation and Node syntax checks are part of selected-file delivery.
Selected files are protected by pre/post SHA-256 verification. Git HEAD is not
changed and no commit or push is part of this request.

## 6. Rendering performance

The hot raster loop now resolves label color/opacity/visibility once per frame
instead of scanning the full organ list and reading CTV workspace presentation
for every voxel. Manual-mask presentation is also resolved once per frame.

A paired synthetic headless Chromium probe rendered 512 x 512 axial frames
with 53 OAR labels and CTV (2 warm-up + 12 measured frames):

| Version | Median | Min | Max |
|---|---:|---:|---:|
| Baseline | 130.0 ms | 128.8 ms | 131.0 ms |
| Repaired | 18.0 ms | 17.5 ms | 18.7 ms |

This measures synchronous synthetic raster work only, not production response
latency, case restore time, network transfer, 3D rendering or GPU computation.
No dose/model/provider work was introduced by display controls.

## 7. Deployment and acceptance

Only the LAN checkout is modified. `BrachyBot-release`, its runtime and
`127.0.0.1:18082` are not modified or restarted. The LAN server is not restarted
automatically, avoiding interruption of an active case.

Frontend assets are cache-busted (volume 89 -> 90, layout 47 -> 48). Reload the
browser to use them. Restart LAN 8080 at a safe time to load the Python
shared-label resolver and enhanced PNG endpoint; an already-running Python
process does not import these source changes automatically.

Operator acceptance steps after reload/restart:

1. Select the original case and let its CT/labels finish loading.
2. With CT Only and OAR unchecked, choose OAR -> Show in 2D. Expect CT+Label,
   OAR checked, and color overlay on slices that intersect selected organs.
3. Hide one organ in 2D; hide/show its OAR parent. That organ must remain
   independently hidden. Its 3D appearance must not be reset.
4. Change a CTV/OAR color and opacity; compare the intersecting MPR slice with
   the Data Tree and 3D object. Remember 2D and 3D remain independent views.
5. Scroll/zoom/rotate or change window/level rapidly. Old same-slice responses
   must not restore obsolete masks or grayscale settings.
6. Switch cases and restore the original. Its saved presentation must persist;
   this repair does not force segmentation defaults at every restore.

No real patient case was opened or changed for implementation/testing, and no
paid model call, inference job or clinical approval was performed.
