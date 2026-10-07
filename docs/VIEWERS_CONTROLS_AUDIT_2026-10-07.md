# Viewers controls and interactive segmentation audit

## Scope and deployment

This audit covers the Viewers toolbar, its slice tools, layout/fullscreen
controls, and the 3D presentation controls in the LAN BrachyBot checkout.
Baseline HEAD: `45bdd13f108824311b6a0d8fb267b797299adc55`. The already-delivered
CTV target-semantics changes are part of the baseline and are preserved.
The independent public-release checkout is not modified or restarted.

Code delivery is not service activation. The backend additions require a
controlled LAN restart and the new asset versions require a browser refresh.
No patient case or saved plan is modified as part of validation.

## Findings and repairs

1. SAT3D positive/negative tools were present but marked hidden. Styling could
   still expose them; operationally they depended on selecting an interactive
   model absent from the automatic tumor selector. There was no self-contained
   Viewers workflow to run the points through the model.
2. The genuine published SAT3D checkpoints failed the previous
   `weights_only=True` loading path because they include `argparse.Namespace`.
   The worker now permits only that specific data-container class in a bounded
   `safe_globals` context. It retains checksum validation, strict topology
   checks and `weights_only=True`; it never falls back to arbitrary unpickling.
3. SAT3D now shares the CTV device lease and cross-process GPU lock rather than
   relying only on a process-local threading lock.
4. A generic, explicitly research-only point-guided route supplements the six
   site evidence profiles. Head/neck CT, prostate MRI and the generic route
   require an actual boolean out-of-distribution consent. The UI confirmation
   also explains replacement of an existing CTV and the need to review results.
5. SAT3D requests bypass any stale uploaded CTV path, use their own explicit
   model override, and carry the points and consent into `/api/segmentation`.
   The automatic nine-choice tumor selector is unchanged. A separate point
   interaction catalog is available through `/api/ctv/models?interaction=point`.
6. Prompt records bind to the loaded image path and shape, not merely the case.
   Unbound legacy prompts must be placed again. Switching cases while the
   confirmation is open cannot run against the newly selected case. The
   server checks the captured CT/CTV source objects and publishes under the
   case-memory lock; a changed source returns 409 without replacing the CTV.
7. Rect referenced an undefined `spacing` variable. Line/rectangle measurement
   also confused CSS display pixels with image pixels and sagittal/coronal
   resampling with original Z spacing. Final physical measurements now account
   for both. Angle values use physical spacing rather than anisotropic pixel
   angles. An angle sequence cannot silently combine different planes/slices.
8. Mouse inversion previously handled zoom only. It now inverts rotation,
   flips and zoom around the rendered canvas center, including transformed
   dose-layer hosts. Linked navigation/HU reads use the same inverse.
9. Draw enabled pointer interception on its overlay after mousedown, losing the
   slice's move/up events. The slice now owns the entire stroke event sequence.
   Rasterization uses the actual MPR grid, not a high-DPI rendering buffer.
10. Draw/Erase did not have real voxel Undo/Redo; only the decorative annotation
    was removed. Both now create reversible voxel-delta transactions. Erase
    edits only the active manual mask and never all other visible masks.
11. New annotations are slice-owned and scale with the current display size.
    SAT point clearing is undoable. Edits, undo/redo, flips and rotation schedule
    durable workspace saves. Undo history itself is session-local, not a
    crash-recovery log.
12. Wire forced hidden meshes visible and reset opacity. It now changes only
    material wireframe mode, including grouped/multi-material meshes.
13. 3D Label/Op targeted a nonexistent HTML overlay and did not affect meshes.
    They now affect CTV/OAR/manual-mask meshes, preserve per-node hiding and
    leave the guide/needles untouched. Label opacity is a multiplier of the
    relevant node's opacity, not an overwrite of its Data Tree record. The
    shared material executor also enforces this constraint on subsequent
    tree edits and late-created meshes; it is not just a one-time redraw.
14. Reset now resets presentation/control affordances without discarding manual
    contours, measurement annotations, prompt evidence or their undo history.
15. Manual model segmentation stored raw arrays without replacing an already
    initialized Structure Set source. This could leave the Data Tree and
    downstream planning reading an old CTV/OAR. The API now uses the canonical
    source-replacement transaction, preserves the other segmentation source,
    rebuilds the binary target/catalog, and invalidates dose, guide and report.
    A tool success without a mask is not reported as a completed segmentation.
16. Zoom-box centering multiplied the translation by zoom before the CSS
    transform scaled it again. Box-fit now centers correctly and persists its
    presentation. Angle previews use the same physical-space convention as
    the final result; preview redraws respect the current slice and scale.
17. Prompt deduplication now includes image identity: a point on an old image
    cannot prevent placing the same voxel coordinate on a different image.

## Control-by-control inventory

“Regression” means code contracts and existing automated fixtures, not an
operator acceptance test on every real modality and patient geometry.

| Control | Implementation / effect | Validation and disposition |
|---|---|---|
| Preset | `applyWindowPreset` / `setViewerWindowLevel` | Existing window-level tests retained; no missing handler |
| W / L | `applyViewerSettings` | Shared normalization, render and persistence path retained |
| Zoom slider/steppers | `applyZoom` plus shared range-stepper | Existing viewport/slider tests retained; inverse pointer repair applies |
| Threshold / Apply | `applyThreshold` | Existing chunked count, mask node, cancel-generation and persistence contracts retained |
| Display mode | `setDisplayMode` | Existing CT/label display path retained; Reset now updates its control too |
| CTV / OAR overlay | `toggleOverlay` | Existing layer-refresh/state contracts retained |
| Dose opacity (top) | `setDoseOverlayOpacity` | Existing dose-generation/frame-opacity tests retained |
| Normal/Dose Surface | `toggleDoseTextureMode` | Existing 3D texture/restoration contracts retained |
| Dose Scale | Colorbar open/apply/reset helpers | Existing independent 2D/3D scale/palette and persistence tests retained |
| Crosshair | `setViewerTool('crosshair')`, linked MPR handler | Uses repaired inverse; existing linked-navigation tests retained |
| Line | Annotation tool | Actual Chromium mouse events verify mm measurement |
| Angle | Annotation tool | Physical spacing and same-plane/slice sequence repaired |
| Rect | Annotation tool | Actual Chromium events verify successful creation and mm dimensions |
| Zoom box | Annotation tool / MPR transforms | Chromium regression verifies centered pan, fit zoom and save; repaired double scaling |
| Draw | `createMaskFromFreehand` | Actual Chromium strokes verify nonempty voxels and true Undo/Redo |
| Erase | `eraseMaskArea` | Actual Chromium strokes verify active target only, reversibility and other-mask preservation |
| SAT3D + / − | Explicit point tools | Voxel/image/slice identity, duplicates, point payload and inverse transform tests |
| Clear pts | `clearSat3dPromptPoints` | Actual clear, Undo and Redo verified |
| Segment… | `prepareSat3dInteraction` | Independent model catalog, point count, availability and modality reminder |
| Run segmentation | `runSat3dInteractive` → manual segmentation API → CTV wrapper → SAT3D worker | Explicit confirmation, source/case fencing, uploaded-path bypass and real checkpoint smoke |
| FlipH / FlipV | Shared transform | All four flip combinations × four rotations tested with zoom |
| Rotate | Shared transform | 0/90/180/270-degree inverse-coordinate tests |
| Undo / Redo | Annotation and mask-delta history | Real voxel and point operations tested; not just stack length |
| Fit | `fitView` | Existing MPR geometry/viewport tests retained |
| Reset (2D) | `resetViewer` | Control reset repaired; clinical/manual data preserved |
| 3D reconstruction | `reconstruct3D` | Existing scene loading, reconstruction, request scope and mask registry tests retained |
| Five Layout buttons | `setViewerLayout` | Existing responsive geometry/resize/restoration tests retained |
| Slice sliders / wheel | `updateSlice` / basic interactions | Existing slice frame, geometry and overlay contracts retained |
| Fullscreen (four panes) | `toggleViewerFullscreen` | Existing layout/resize contracts retained |
| HU display | Linked MPR / `fetchHUValue` | Receives the same repaired pointer inverse as navigation |
| 3D Reset | `reset3DView` → `fitCameraToScene` | Existing camera framing tests retained |
| Mesh Op | `update3DMeshOpacity` | Existing hidden-mesh and workspace presentation tests retained |
| Wire | `toggle3DWireframe` | Actual Chromium material test verifies hidden state/opacity preservation |
| Skin | `toggle3DSkin` | Existing canonical skin-node/threshold-node path retained |
| Dose Op (3D) | `updateDoseOpacity` | Existing dose-overlay state/render path retained |
| Label / Op (3D) | `updateLabelImage('3d')` | Actual Chromium test verifies mesh change, tree hiding and guide preservation |
| Data Tree visibility/color/opacity | Shared Data Tree registry/executors | Existing tests retained; the prior CTV label identity repairs are preserved |

All inline click/input/change handlers in the Viewers section are checked
against implementations. This catches missing entry points but is not used as
the only proof of behavior.

## SAT3D use and capability boundary

1. Load the actual image and set its true modality in Input.
2. Click SAT3D + and place one or more positive points inside the intended
   lesion on the 2D MPR views. SAT3D − places exclusion points.
3. The compact assisted-segmentation strip opens in Viewers. Select the matching
   evidence profile; use Other site only as a research candidate.
4. Click Run segmentation and read the replacement/review confirmation.
   Selecting a point tool alone never launches expensive inference.
5. Inspect the resulting CTV on the relevant slices and in the Data Tree/3D
   view. It is a candidate contour, not a clinically approved segmentation.

The official model is a point-prompted, cross-site research model. Its title
“Segment Any Tumour” is not a guarantee of correctness for every tumor,
modality, acquisition or out-of-distribution anatomy. Published support and
local deployment are different from BrachyBot's own case-level validation.
Primary source: [official SAT3D repository](https://github.com/himashi92/SAT3D),
pinned local commit `e85cbf4b2e17c09b34b36369c4eca29e98321b4b`.

## Validation evidence and limitations

- Browser tests exercise actual product annotation code and real DOM mouse
  events on generated images. Network/model boundaries are explicitly mocked
  in browser contract tests, not presented as live patient inference.
- Real weights: the complete CTV wrapper/SAT3D worker succeeded on a generated
  64×64×64 volume with positive and negative points. It returned 728 candidate
  voxels in approximately 7.1 seconds and retained the review-required flag.
  This is technical execution evidence, not a Dice/clinical accuracy result.
- The initial isolated-stage resource-path mismatch was corrected by setting
  the actual deployment root. A subsequent genuine checkpoint-load failure
  was repaired as described above. Neither failure is hidden by a fake mask.
- Existing exact asset-version assertions are updated to the new layout
  revision; no physical/guide-latency guard or geometric threshold is weakened.
- The final isolated-stage full product suite passed 2,747 tests, with two
  skips, 31 deprecation warnings and four passing subtests, in 90.57 seconds.
  It includes the original guide reference-guard collection checks and the
  new browser/API regressions. This is not a live-user acceptance result.
- Real-patient segmentation precision, nonzero 4D-volume interactive viewing,
  every external GPU model's accuracy and production service activation are
  outside these synthetic/browser regression proofs. Do not claim universal
  tumor segmentation or comprehensive clinical readiness.

## Final engineering validation and delivery

- Stage: `/tmp/brachybot-viewers-stage-20261007-s1lXop`.
- Full suite: `/tmp/viewers-final-tests-20261007.log` (`pytest -q tests`).
- Focused browser/API/workspace run:
  `/tmp/viewers-focused-final-20261007.log` (205 passed before the final
  direct-visibility refinement; the full suite above includes that refinement).
- Real checkpoint result: `/tmp/viewers-sat3d-synthetic-20261007.json`.
- Actual HTML/CSS controls visual QA: `/tmp/viewers-controls-20261007.png`.
- Python compilation and all six modified/new JavaScript files' syntax checks
  pass. `verify_reference()` explicitly passes without changing guide reference
  dependencies, geometry thresholds or the previous paired evidence.
- The first full run without the deployed Node path had one Node-availability
  failure and additional skips. Correcting the test environment, not loosening
  the contract, produced the final full result above. A zoom test also exposed
  fractional CSS event rounding; its oracle now verifies the actual centered
  region invariant instead of assuming an integer canvas origin.
- Delivery comprises 16 selected files: 12 existing files and four new files.
  Before hashes refer to the current dirty checkout, not an older Git snapshot.
  Checked delivery aborts on a changed HEAD or concurrent selected-file edit,
  keeps a mode-0700 backup with the manifest, verifies every after hash, and
  publishes the index asset versions last.
- LAN/public listeners checked before delivery remained PID 1709933 on
  `192.168.1.113:8080` and PID 1703529 on `127.0.0.1:18082`. These are dated
  observations, not a permanent deployment claim. No restart is included.
- No patient inference, production case mutation, commit or push is included.
  Restart the LAN backend and refresh the browser to activate the new backend
  catalog and versioned assets. The public-release checkout remains independent.
- Existing dependency/security release gates, including the previously flagged
  Torch 2.6.0 runtime, are not certified or upgraded by this Viewers work.
