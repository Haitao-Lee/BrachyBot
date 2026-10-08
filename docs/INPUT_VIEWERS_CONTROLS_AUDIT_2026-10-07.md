# Input and Viewers control audit

## 1. Scope and evidence boundary

The request covers every visible control in the supplied Input and Viewers
screenshots, including the expanded guide parameters and hyperparameters.
The authoritative checkout is `/home/lht/snap/brachyplan/BrachyBot`.
The independently operated `BrachyBot-release` checkout is out of scope.

Baseline: `43e030171a2d6bfd16dca4ed964ef47122c8327e`, with a clean worktree.
This baseline already includes the source-aware CTV and Viewers/SAT3D repairs
documented in `VIEWERS_CONTROLS_AUDIT_2026-10-07.md`. This audit verifies that
baseline and adds Input workflow repairs; it does not claim to have performed
the earlier real-checkpoint smoke again.

An implemented entry point, a passing synthetic browser contract, real GPU
execution and clinically accurate output are four different evidence levels.
This audit establishes the first two and preserves existing model/geometry
contracts. It does not certify every tumor model on every patient, arbitrary
CT-to-intraoperative registration, clinical planning safety or deployment
security. No production patient case, plan or runtime account is edited.

## 2. Confirmed findings and root-cause repairs

### 2.1 Completion flags did not represent completed products

The full-pipeline handler previously set all manual stage flags to completed
after a generic success. A partial workflow could therefore render successful
checkboxes for stages that had no saved result. `web/input_workflow.py` now
derives workflow flags from saved CT, segmentation, trajectories, seeds, dose
and evaluation products. Full planning requires saved seeds, dose and metrics,
then checks core result delivery. A saved computation whose display failed is
reported as a delivery problem, not an instruction to repeat expensive work.
Observed zero metrics and a finite all-zero dose array remain valid observed
data; they are not replaced by a missing-value placeholder.
Conversely, a retained reference array after a manual geometry edit is not a
current completed dose: the established manual geometry-only and dose/DVH
artifact lifecycle flags suppress its completion checkmarks without deleting
the reference data.

### 2.2 Reset and source replacement could resurrect a removed plan

Reset removed some active aliases but retained the active immutable planning
snapshot. Hydration could restore those aliases later. It also confused
segmentation readiness and planning reset. Reset now explicitly confirms its
scope, creates an empty draft identity through the existing planning history,
clears downstream products and manual aliases, and preserves CT, CTV/OAR,
conversation and previous planning versions.

Replacing a segmentation source also retires the outgoing planning identity
before publishing the new effective structures. Otherwise an old namespace
could restore old manual seeds, needles or dose during resource reload.
Structure replacement retains the historical snapshot, publishes a fresh
draft and invalidates the dependent stage presentation/dose/guide/report.
This uses the canonical Structure Set transaction, not another label parser.

### 2.3 Async Input actions lacked a common owner and mutation contract

`brachybot-input-actions.js` owns each action's case, decoded image and render
generation. Requests carry the captured case header. A late result, including
an A-to-B-to-A session transition, cannot repaint another presentation lifetime.
Duplicate Input mutations are blocked locally and release their tokens in
`finally`. Read-only result/export actions have independent action keys.

The API decorators for segmentation, configuration, planning stages, reset
and intraoperative work share the existing manual-dose case transaction lock.
A competing tab receives retryable HTTP 409 rather than queueing a stale reset
behind a long edit. This is a per-request lock in the existing process, not a
claim of distributed transactions or a lock spanning the entire multi-request
full-pipeline workflow. Existing source/version fences remain necessary.

### 2.4 Intraop was missing its indispensable inputs

The old button reused the main CT and omitted the required original seed plan.
It could only fail the backend's input contract. The repaired button requires
an existing preoperative seed plan, opens a chooser for a separate scan,
uploads it into the initiating case without replacing the preoperative CT,
and explicitly asks the server to use its authoritative current seed plan.
The backend still rejects incompatible physical frames/counts and requires
human review where registration/correspondence is not established. An upload
alone does not prove successful seed correspondence or authorize an unsafe
automatic replan. Cancellation does not mutate the plan.

### 2.5 View Results and dose units were misleading

Every result button previously went to Analysis regardless of its name.
Trajectories, Seeds, Dose and Show All now open Viewers; DVH/Metrics open
Analysis. Existing manual stage nodes are made visible through the shared
presentation executor rather than recreating conflicting nodes. Physical Gy
is preferred and explicitly tagged by `/planning/show_step`; the browser does
not multiply an already-physical dose by 190.8 again. Zero-valued V100/D90
are displayed as zero, not a dash. Normalized fallback data still uses the
canonical model calibration.

### 2.6 Export success did not produce a usable download

The Input export handlers previously reported server paths. DICOM-RT now
returns authenticated URLs for its DICOM artifact list. Seed STL export
returns download links, rejects non-finite geometry and refuses an empty
zero-file success while retaining quota transactions. Report exports the
supported planning-data HTML in the selected UI language. Download links are
case-owned, deduplicated and remain in the chat rather than automatically
opening dozens of downloads. Cross-case/external URLs are rejected.

The Input STL button exports seed cylinders; **Export Guide STL** is the
distinct guide action. Input Report exports a data report, not an illustrated
PDF. The established Report panel provides the illustrated browser PDF export;
the server PDF branch still intentionally returns 501. No fake PDF endpoint
or clinically approved export is introduced.

### 2.7 Editable fields were silently ignored

The planner ignored several legacy training/inference/label fields. The
candidate cone angle and maximum candidate count now travel through the
supported configuration path. Supported geometry, dose and optimizer fields
remain editable. Unsupported seed-count/average-dose, numeric label codes,
direction-grid and model-training/inference-size fields are explicitly
read-only with bilingual explanations. A fixed trained model is not retrained
by changing a GUI number; Structure Set target semantics cannot be replaced
by a generic pancreatic label convention.

Configuration validation reuses the planner's actual supported-parameter
validator and validates a copied candidate before replacing the live config.
Invalid/NaN/zero-direction/inverted-bound input cannot partially overwrite
valid settings. Physical Gy conversion is normalized once. Valid updates
schedule persistence. These are software validation ranges, not newly
invented clinical prescription limits.

### 2.8 Replan Geometry was only dose reprojection

The old alias called `recomputeManualDose('manual_replan')`, which could
reproject associated seeds but did not optimize needle/seed geometry.
Replan Geometry now confirms replacement of deliberate manual edits and calls
the genuine full planner, preserving the outgoing planning version. Recompute
AI Dose retains its existing geometry-preserving dose-update purpose. A
confirmation cancelled or detached by a case switch cannot launch the planner.

### 2.9 Restore Default Parameters erased the guide catalog

The guide default action previously cleared saved versions and planned needle
choices. Restoring parameter defaults now leaves those catalogs available and
resets the chosen subset to all current needles. Explicit case cleanup passes
`clearCatalog: true`, also clearing cached catalog metadata so a later language
change cannot resurrect the old case's options. Imported-STL validation also
fences success and error UI by case and render generation. The existing 5 mm
truncation policy, bore geometry and guide acceptance gates are unchanged.

## 3. Input control inventory

| Control | Product entry point and expected behavior | Disposition/evidence |
|---|---|---|
| CT Browse | `handleFileSelect`, owned upload and image loading | Existing file/DICOM/ownership tests retained; planning now checks decoded CT path, not only a nonempty field |
| CT Folder | Same handler with directory DICOM collection | Existing extensionless/series validation retained; no new folder bypass |
| CTV Browse | Upload-mask staging, then explicit CTV classification | Preserved: upload is not implicit tumor selection or planning approval |
| Tumor type | Registered model catalog and source-specific target semantics | Nine automatic profiles retained; full flow honors selected model via segmentation API |
| Image modality | Segmentation request modality | Preserved; Intraop does not reinterpret the pre-op image as a new scan |
| 4D volume index | Explicit selected volume for segmentation | Existing validation retained; no claim that every 4D volume has been GPU-tested |
| OAR Browse | Case-owned upload and OAR source replacement | Existing staging/classification contract retained; replacement retires dependent planning state |
| DICOM-RT Import | `handleDicomRTImport`, read-only case import | Existing frame/reference checks retained; no automatic overwrite of effective CTV/OAR/dose |
| Hyperparameters expansion | `toggleHyperparams` | Existing show/hide handler retained |
| Apply hyperparameters | `applyHyperparams` -> `/api/config` | Supported values only; atomic validation, owner fence and persistence |
| Start Plan | `runPlanning` -> segmentation as needed -> full planner | Requires decoded selected image; uploaded CTV must be explicitly classified; products determine completion |
| Intraop | `runIntra` -> separate upload -> intraoperative API | Fixed missing original plan and wrong scan; preserves review-required boundary |
| Reset | `resetSession` -> `/planning/clear` | Confirm/cancel; inputs/chat/history preserved; no hydration resurrection |
| Step-by-step expansion | `toggleStepButtons` | Existing expansion retained |
| CTV Seg | `runSegmentationStep('ctv_segmentation')` | Selected model/modality/volume; source replacement, downstream invalidation and owning-case completion |
| OAR Seg | `runSegmentationStep('oar_segmentation')` | Independent of CTV as designed; shared source transaction and downstream invalidation |
| Trajectories | `runPlanningStep('trajectory_init')` | Existing common stage node (trajectories + close points), display completion and next-stage visibility contracts retained |
| Refine | `runPlanningStep('trajectory_refine')` | Requires initial trajectories; existing intermediate geometry executor retained |
| Seeds | `runPlanningStep('seed_planning')` | Requires refined trajectories; actual persisted output/presentation, not a clicked flag |
| Dose | `runPlanningStep('dose_calc')` | Requires seeds; existing CNN dose calculation and physical units retained |
| Evaluate | `runPlanningStep('dose_eval')` | Requires dose; existing canonical target/OAR metrics contract retained |
| Show All | `showStepResults('all')` | Correct Viewers panel, common stage visibility and current-case refresh |
| View Trajectories | `showStepResults('trajectories')` | Correct Viewers panel and trajectory presentation |
| View Seeds | `showStepResults('seeds')` | Correct Viewers panel and seed presentation |
| View Dose | `showStepResults('dose')` | Correct Viewers panel; no double physical-unit scaling |
| View DVH | `showStepResults('dvh')` | Correct Analysis panel; existing DVH renderer retained |
| View Metrics | `showStepResults('metrics')` | Correct Analysis panel; zero metrics remain zero |
| Export DICOM-RT | `exportDicomRT` | Authenticated case-owned artifact links; existing geometry/provenance/quota validation retained |
| Export STL | `exportSTL` | Seed cylinders, finite geometry, nonempty files and download links |
| Export Report | `exportReport` | Supported planning-data HTML; PDF remains in Report panel |
| Monitor | `startTrainingMode` | Existing common monitor-run lifecycle, run/version fences and localized controls retained |
| Finish Monitor | `stopTrainingMode` | Existing retryable stop/reconciliation path retained |
| Add Needle | `addManualNeedle` | Existing server suggestion, validation, commit/rollback and optimistic version contracts retained |
| Add Seed | `addManualSeed` | Existing normalized candidate/commit/spacing safety contracts retained |
| Recompute AI Dose | `recomputeManualDose` | Existing authoritative CNN recomputation; not presented as geometry optimization |
| Replan Geometry | `replanManualPlan` -> `runPlanning` | Real optimizer after explicit replacement confirmation; history retained |
| Generate Guide | `generateSurgicalGuide` | Existing chosen planning/needle subset, version and source-geometry fences retained |
| Export Guide STL | `exportSurgicalGuideSTL` | Existing versioned guide export; distinct from seed STL |
| Detailed Advice | `requestPlanningAdvice` | Existing server-owned compact facts/evidence and owner-scoped read retained; no whole-scene request |
| Readiness | `checkSystemReadiness` | Existing readiness endpoint and owner-scoped response retained |
| Guide parameters expansion | Guide panel controls | Existing expansion retained |
| Guide numeric/auxiliary-hole fields | `guideParametersFromControls` | Existing validated generation payload and geometry QA retained; original truncation policy unchanged |
| Guide needle subset | `selectedNeedleIds` | Existing chosen-subset generation; defaults restore no longer destroys options |
| Source planning selector | Guide planning selection helpers | Existing explicit planning/version association retained |
| Saved guide version selector | `selectedGuideVersion` | Existing version catalog retained |
| Show Selected Version | `loadSelectedSurgicalGuideVersion` | Existing case/version-aware mesh load retained |
| Validate Imported STL | `validateImportedSurgicalGuideSTL` | Existing mesh validation; stale success/error responses suppressed |
| Restore Default Parameters | `resetSurgicalGuideControls` | Parameter-only reset; catalog clearing reserved for actual case cleanup |

Each remaining interactive hyperparameter is consumed by the canonical
planner: seed radius/length/margin, cone angle/candidate limit, reference
direction/auto mode, physical dose/DVH target, iteration/replanning rates,
distance bounds/rates and RL episode/bandwidth values. Read-only legacy fields
are not represented as implemented adjustment capabilities.

## 4. Viewers control inventory

The complete earlier inventory is retained in
`VIEWERS_CONTROLS_AUDIT_2026-10-07.md`; this round reruns its browser/API and
the full product regression suite. The following lists all screenshot groups
and makes the evidence boundary explicit.

| Control(s) | Expected behavior and verified contract |
|---|---|
| Preset; W; L | Shared window/level normalization and redraw; existing regression retained |
| Zoom slider and left/right steppers | Common range handler/viewport transform; existing regression retained |
| HU threshold; Apply | Count/create threshold mask with generation cancellation and durable node state |
| Display CT/overlay/label selector | Existing label/CT layer selection and reset-control agreement |
| CTV; OAR checkboxes | Existing layer visibility and tree state contract |
| Top Dose opacity and steppers | Existing dose-overlay opacity/frame state |
| Normal/Dose Surface | Existing physical-dose surface textures and restoration |
| Dose Scale; close; scope; min/max/palette; Reset; Apply | Existing independently configured 2D/3D ranges and palettes |
| Crosshair | Linked MPR navigation using the corrected inverse transform |
| Line | Image-grid, anisotropic-spacing-aware millimeter measurement |
| Angle | Physical-space angle; one sequence cannot combine unrelated slices/planes |
| Rect | Real physical-size rectangle creation; repaired undefined spacing retained |
| Zoom box | Region fit and centered pan without double zoom scaling |
| Draw | Real active-mask voxels and durable source identity |
| Erase | Active-mask-only voxel edit; never erase unrelated visible masks |
| SAT3D +; SAT3D - | Positive/negative voxel points bound to actual image and slice |
| Clear pts | Real prompt removal with Undo/Redo |
| Segment…; profile; Run segmentation; close | Explicit independent SAT3D workflow with model/consent/source fences; no inference just from clicking a point tool |
| FlipH; FlipV; Rotate | Render and inverse-pointer agreement for all flip/rotation combinations |
| Undo; Redo | Real voxel/annotation/prompt reversibility, not just a visual stack |
| Fit; 2D Reset | Presentation reset without deleting contours or measurements |
| 3D reconstruction | Existing source-owned geometry reconstruction/loading |
| Five layout buttons and pane fullscreen buttons | Existing resize, canvas resolution and restoration contracts |
| HU readout and slice navigation | Consistent inverse pointer geometry and linked slice state |
| Data Tree expand/collapse; show/hide; color; opacity slider/steppers | Existing stable source IDs, mesh/material executors and saved presentation |
| 3D Reset | Existing camera fit/framing |
| Mesh Op slider/steppers | Existing global multiplier with hidden-node preservation |
| Wire | Material mode only; must not unhide meshes or overwrite opacity |
| Skin | Existing canonical skin/threshold node |
| 3D Dose Op slider/steppers | Existing dose material opacity contract |
| Label checkbox; Label Op slider/steppers | Actual label meshes, tree hiding respected; guide/needles not recolored |

SAT3D is a research point-prompted model. Successfully binding its buttons
does not establish accurate segmentation of every cancer or modality. The
automatic site-model selector remains distinct from the interactive catalog.

## 5. Validation and delivery

Validation uses a fresh isolated HEAD archive at
`/tmp/brachybot-controls-stage-20261007-HRdOPm`, not the running patient server.
Synthetic tests use real AgentMemory, planning history, Structure Set and
Flask route code, with authentication/storage/model boundaries explicitly
stubbed where stated. Browser tests use actual Input HTML, product JavaScript,
Chromium click/file-chooser events and synthetic endpoint responses. This
does not constitute a live case/GPU or external security acceptance test.

- Clean baseline: 2,747 passed, two skipped, 31 warnings and four passing
  subtests; `/tmp/controls-baseline-tests-20261007.log`.
- Focused Input/Viewers browser/API run: 86 passed before the final readonly
  field and entry-point inventory additions;
  `/tmp/controls-focused-3-tests-20261007.log`.
- Pre-final complete suite: 2,783 passed, two skipped, 31 warnings and four
  passing subtests; `/tmp/controls-full-2-tests-20261007.log`.
- Final complete suite: **2,788 passed, two skipped, 31 warnings and four
  passing subtests**, in 100.05 seconds;
  `/tmp/controls-final-lifecycle-tests-20261007.log`. All final product edits are
  included. The skips are the same count as the clean baseline, not new
  missing control tests. The warnings are the existing SWIG/UTC deprecations.
- `verify_reference()` passes without editing the frozen guide dependencies,
  paired evidence or geometric/latency acceptance thresholds.
- Python compilation and syntax checks cover every modified/new Python/JS file.

No commit, push or public-release restart is performed. Python changes require
controlled LAN backend activation; cache-versioned frontend changes require a
browser refresh. A code-delivery manifest records current before/after SHA256
values, refuses concurrent edits and preserves a mode-0700 backup. Service
state observations are timestamped facts, not permanent deployment promises.

### Final evidence details

- 41 additional passing tests compared with the clean baseline. Tests include
  real confirmation/cancellation clicks, the native file chooser, six result
  destinations, three download handlers, incomplete full-plan products,
  duplicate actions, A-to-B-to-A late responses, fixed-model readonly fields,
  guide defaults/catalog preservation, actual planning-history reconciliation,
  atomic invalid configuration, physical units and competing-case edit locks.
  The final negative controls also retain old dose arrays while marking dose
  stale, DVH expired or geometry-only, and require the corresponding stage
  checkmarks to remain incomplete.
- The added entry-point inventory initially did not recognize methods of
  `_staticUiHelpers`, which are deliberately published in a loop. The inventory
  now checks that actual helper registration as well as declared/window
  functions. This was a test-discovery defect, not a missing expansion handler;
  no product function or guard was weakened to make it pass.
- Visual QA uses actual product HTML/CSS and generated data, not patient
  imagery: `/tmp/controls-input-visual-20261007.png`. Existing themed confirmation
  controls are reused rather than introducing a separate modal style.
- Delivery selects 12 files (seven existing, five new) and publishes HTML
  asset versions last. The backup and manifest are returned by the checked
  delivery helper; the manifest is the definitive per-file hash inventory.
- At `2026-10-07T21:23:43+08:00`, the LAN listener was PID 1888549 on
  `192.168.1.113:8080`; the independent release listener was PID 1888807 on
  `127.0.0.1:18082`. Both observations precede delivery. No restart is part of
  this delivery; backend activation is a separate operational step.
