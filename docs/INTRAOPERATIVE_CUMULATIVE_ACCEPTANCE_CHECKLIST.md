# Cumulative multi-timepoint and intraoperative acceptance ledger

Status: cumulative implementation merged into the LAN checkout on 2026-10-13;
whole-workflow acceptance still has pending gates; the public release is unchanged. This file covers prompts
**a–i together** and the subsequent 32 checks. It is not a completion certificate,
clinical validation or a claim that every a–i composition has passed.
Earlier "not deployed" statements below describe historical isolated checkpoints.

### Latest LAN merge and archived-Session repair

The user explicitly requested integration into the formal LAN directory.
The verified merge installed 257 cumulative source/document/test paths plus the
LAN launcher and private runtime configuration. Generated live skill-registry
state was deliberately preserved. Source/config and consistent SQLite backups
are under `/home/lht/snap/brachyplan/backups/brachybot-timepoints-archive-20261013`.
LAN PID 1853900 serves `192.168.1.113:8080` from the requested checkout;
health/index and five owned new/updated JS assets returned 200 with exact disk
hash matches. The private supplied SeedFinder bundle/interpreter/device is
configured and its availability validator passed. The independent public
listener remained PID 1836580 on loopback 18082 during this cutover.

Old-case activation failure was caused by lost archive-root configuration:
38 archived Session snapshots were absent from the default repository archive
but all 38 were present on the mounted original NAS. The correct root is now
persisted per LAN runtime, with required mountpoint checks and safe localized
unavailable-storage errors. Archive/config/store/authentication/route/bundle/
frontend checks passed **465 tests**, **21.52 s**. A real old archive was restored
on an isolated private clone: **30 files, 133587846 bytes, 5 array files**,
identical restored byte hashes and Session identity, compatible legacy-default
timepoint loading. Original NAS files and the production DB were not changed
by that verification.

The previously failing native guide browser fixture was incomplete; after
capturing its actual uploaded parent image fingerprint, the exact CPU/browser/
source/workflow batch passed **38 tests**. No original-source guard was relaxed.
The current code freeze `0e6cf7b03cb24cf221b4b517cef65d681eee891d3f1d14ad0412363c79471d35`
completed complete regression, separate from production writable data:
**4524 passed, 2 failed, 2 skipped and 4 passing subtests**, **1569.75 s**.
Both failures involved actual page recovery (two-timepoint cold/import recovery
and supplied-model page cold recovery). This full run is not green. The first
hydration-reentry repair subsequently passed the frontend/two-timepoint batch
(**12 tests**, **188.55 s**) and supplied-model full-page replay (**1 test**,
**214.74 s**), then was installed without another service restart. Additional
owned-receipt/generation/failure guards and their final bounded verification are
recorded in `COLD_RECOVERY_FINAL_REPAIR_20261013.md`; these do not retroactively
turn the earlier full freeze green.
The final owned-revision/generation/failure guard freeze passed **28 tests**,
**361.62 s**, including both actual browser workflows, frontend and archive
configuration cases; the compatible observation browser/asset batch passed
**2 tests**, **6.50 s**. This closes the demonstrated cold-recovery failures for
the bounded exact follow-up, not the remaining whole guided-continuation or
clinical commissioning gates. Installation and live-source evidence are in
`lan-recovery-followup-installed-20261013.json` and
`lan-final-live-verification-20261013.json`.
See `LAN_DEPLOYMENT_ARCHIVE_REPAIR_20261013.md` for the deployment details.

## Evidence categories

- **Implemented candidate:** actual product code exists, not a placeholder.
- **Contract evidence:** numerical/owned-storage/authentication tests with synthetic
  inputs; model mocks in narrowly labelled unit tests are not product substitutes.
- **Product evidence:** actual Flask routes / actual product scripts, not mock APIs.
- **Model execution:** supplied detector and existing DoseUNet run on the provided
  acquisition. This is not reference accuracy, independent dosimetry or clinical
  commissioning. Assumed source dimensions are explicitly limited to the smoke.
- **Pending:** at least one required composition or acceptance path is unfinished.

## Current directly executed evidence

1. Default migration and request-owned runtime: seven initial store/runtime tests
   passed before subsequent extensions. Clinical and presentation revisions are
   separate; old Viewer close cannot replace newer chat accounting/confirmation.
2. A focused integration batch passed **76 tests** covering migration, real image
   decoding, front-end contracts, immutable correction and implanted dose.
3. The later dose/bundle/product batch passed **18 tests**, including actual Flask
   upload/load/volume, two-image display/reference separation, complete store graph
   export/import, component addition and the physical-Gy Viewer boundary.
4. Real supplied SeedFinder + DoseUNet smoke: **12 detected sources**, **12 estimated
   axes**, original-current grid **9 × 324 × 324**, calibration **190.8 Gy/model unit**.
   Detection **10.102 s**, first dose **7.617 s**, unchanged-dose reuse **0.343 s**.
   No production patient was modified. This does not establish dose accuracy or
   clinical use. Software-smoke dimensions were explicitly assumed (4.5 mm length,
   0.4 mm radius), not presented as confirmed patient source parameters.
5. The real smoke discovered a pinned native export convention: fractional CSV
   voxel centroids, but rounded-index physical centers in some supplied branches.
   The adapter now verifies that exact convention without enlarging tolerance or
   replacing the reported physical center. CSV/Markups/original-grid checks remain.

These results are historical snapshots, not additive counts or final regression
results. A final frozen full-suite result and complete product workflow acceptance
are still required.

### Integration updates executed on 2026-10-12

- The first frozen cumulative full run reported **3812 passed, 32 failed, 2 skipped**.
  Following source-contract repair and genuine restoration fixes, the next frozen
  full run reported **3850 passed, 2 failed, 2 skipped**, 4 passing subtests.
  Neither run is the final current-candidate result. The remaining failures were
  a legacy radio-button test against the new image button, and an intermittent
  startup restoration race. Subsequent targeted product tests exercised those
  paths after correction; another complete frozen regression remains required.
- Actual product browser acceptance now executes owned NIfTI uploads, default
  migration, linked preop/intraop creation, four-panel switching, cold restore,
  image-name/UUID Data Tree hierarchy, right-click move out of role groups,
  mutually exclusive image display, hide-all background, original-reference
  retention, per-image opacity, and two-image cold recovery. No API route or
  product global is replaced in `timepoint-product-browser.test.cjs`.
- The same actual browser exports the complete graph, selects it through the
  native file chooser, confirms import, and restores a new independent Session
  with two linked timepoints. The original Session's image appearance remains
  unchanged. The executed bundle + actual product import batch reported **5 passed**
  (`cumulative-import-real-ui-fixed-20261012.xml`). The import test discovered a
  real dictionary-versus-job-enum error in the recursive graph rebinder; its
  regression retains nested UI dictionaries and checks cold journal restoration.
- Owned registry/image actions and read-set tests reported **20 passed**. An
  actual installed Agent compiled **40 registered capabilities, zero missing
  scope adapters**. This inventory is not proof of every possible natural-language
  utterance or external model availability. Developer execution stays disabled in
  patient workspaces. `timepoint_images` invokes the actual collection service,
  with required action authorization and canonical reference-grid replacement.
- Current total-quality invalidation, individual source exports, graph bundles,
  manual continuation dose, report capture, and frontend contracts reported
  **59 passed** in `cumulative-source-quality-report-20261012.xml`. Invalidated
  current metrics cannot fall back to historical algorithm comparison metrics.
- Real detector + actual DoseUNet component smoke reported **12 implanted sources,
  1 explicitly synthetic supplemental test source**, a physical total equal to
  the two components within float32 rounding (maximum absolute difference
  **0.0004482269287109375 Gy**), and reuse of both unchanged CNN components.
  Input SHA256 `e78a86bc291e7e17acbabc16c76647eddd71b583a4ef281defa0861b2c32aedb`;
  checkpoint `d73d19f22c846ee989786eabd9336fba80b8c9658881a6e878aca846861b5681`;
  evidence `real-model-evidence-bb3a86b2063e4b4692c7d87f28a053d6.json` in the isolated
  stage. The source dimensions are assumed software-test inputs, not a clinical
  prescription or reference dosimetry validation.
- Full-page supplied-model/THREE/manual-pointer acceptance passed independently
  in `cumulative-real-model-accepted-20261012.xml` (1 actual product scenario).
  It runs the supplied model and actual CNN, per-source 2D/3D/Tree visibility,
  color and opacity, source settings, implanted-dose recomputation, a real 2D
  pointer addition and 3D drag, save/invalidation, context-menu exclusion, another
  CNN recomputation, human review and cold restoration. It is software acceptance
  on the supplied demo, not clinical accuracy or approval. Root causes included
  premature shell readiness and a focus-induced delayed Tree scroll dismissing
  a newly opened context menu. Stable toolbar nodes alone were not the root fix.
- `cumulative-all-product-20261012.xml` passed **2 actual product scenarios**
  (the optional supplied detector was skipped in that batch, independently passed
  above): complete multi-timepoint native-chooser import and actual CPU guide
  registration/CT overlay/human review/cold recovery/rejection on a declared
  synthetic phantom. It does not establish real-patient guide fit. A browser
  file chooser fake-path persisted as an ordinary form value was the actual
  import-mount error; both capture and legacy restoration now exclude file and
  credential controls. The strengthened legacy fake-path replay also passed.
- Full regression of the preceding frozen candidate reported **3870 JUnit
  testcase records, 9 failures, 3 skips** (`cumulative-final-revalidation-20261012.xml`,
  559 s; testcase records include 4 subtests). Failures exposed missing Import help cards,
  invalid old metric fixtures expecting stale dose to remain current, and the
  actual import file-control defect. Targeted corrections passed 121 tests;
  another frozen full regression is running. Do not call those older totals a
  current final full-suite pass.
- Guide jobs now capture clinical version and immutable image/guide readsets,
  allowing presentation-only updates without accepting changed clinical inputs.
  Both UI and signed server overlay receipts include clinical revision. Actual
  guide workflow/CPU tests passed 14 tests before further signed-language checks.
- Current guide/needle settings, in-situ geometry and channel-state signatures
  invalidate prepared candidate paths. Current geometry preparation, pipeline
  and guide-first/exterior tests passed 58 tests. No software test proves the
  patient-specific feasibility of every external path.
- Source-separated aggregate inspection reads canonical component metadata,
  explicit Gy/fraction declarations and stale state, without decoding dose
  arrays or summing repeated implant observations. Its Agent boundary batch
  passed 15 tests. Dynamic observation controls have passive source-bound help
  even though they are not present in initial HTML; runtime availability and
  execution authorization remain separate (52 help tests passed).
- Actual detector/CNN dose was supplied to unpatched zero-addition planning and
  dose stages: 12 sources, 1213 explicitly dose-derived software-fixture target
  voxels, coverage 1.0, zero supplemental sources/needles, zero additional dose,
  and preserved physical baseline. Evidence `real-model-evidence-6bd330bc0dca4f75a7392c6a143d5260.json`.
  This is not a segmentation, clinical coverage or independent dosimetry test.
- Explicit zero source/needle counts survive report extraction and current plan
  queries; structured legacy stale flags suppress current metrics. A manual
  supplemental edit invalidates planned/total Viewer and export components but
  not an independent unchanged implanted component (87 current-quality/read
  tests and 16 export/recompute tests passed in overlapping targeted batches).
- A complete frozen candidate with actual supplied-model opt-in passed
  **3873 tests, 2 skips and 4 subtests** in **798.98 s**
  (`cumulative-owned-workflow-full-20261012.xml`, archive SHA256
  `c064eed7e0b08060365f8ce5f06a0e6249a0bc9ecb84f2494ea0502033febc65`).
  Later audit additions are not retroactively covered by that result. A newer
  frozen candidate is under regression; the subsequent obstacle-policy and
  total-QA restoration corrections have targeted and actual CNN evidence.
- Persisted traversability/embedded-hard-label changes invalidate prepared
  candidate paths, while color does not. Completed current total evaluation
  now clears the old quality-check stale flag while keeping the Report stale
  until explicitly regenerated. Those additions passed targeted graph tests;
  actual CNN component recomputation restored current total V100/D90 and
  report-readable total metadata on a declared synthetic target. Evidence
  `real-model-evidence-add1708effd84b538b1bf84a20ffb677.json` retains the actual
  source/checkpoint hashes and software-only target assumptions.
- Numerical read-set and presentation ordering were repaired without weakening
  patient/timepoint ownership, lifecycle, immutable observation head, source image
  or printed-guide candidate checks. Identical encoded clinical checkpoints no
  longer increment clinical revision. Repeated display of the selected image no
  longer increments collection revision. Source and geometry confirmations use
  clinical CAS; legacy state-CAS callers remain strict.
- Source-separated dose exports and individual acquisition/original exports now
  exist in the real export catalog. Unknown source axes/dimensions are exported
  as records only, never invented STL geometry. Current screenshot catalogs do
  not enumerate sibling timepoints' captures. Export catalog discovery does not
  execute component DVH evaluation as a hidden side effect.

### Final audit boundary and latest follow-up

- Frozen archive `f6ba2fb1b77f01013e8950eada53a56caae5c71099b5c07f786b8317cc08fb1e`
  passed **3879 tests, 2 skips and 4 subtests** in **887.05 s**. Evidence:
  `cumulative-cold-ready-final-full-20261012.xml` (SHA256
  `f5c856d94e98f7346d0a68204bf9f6348047f98a3ac7a23b846203e52e4619e7`).
  Two skips are public-origin dependencies and the unavailable real Nginx
  proxy binary; neither is a passing deployment check.
- The preceding full freeze caught an intermittent real cold-restore failure.
  New scoped lightweight views inherited another view's CT-ready/error flags.
  Both scoped constructors now reset them until owned decode completes.
  A real-decoder barrier test passed and three independent full-product
  upload/switch/cold-restore/import replays passed (114.05, 115.60, 114.45 s).
- Observed-source dose no longer invents a completed future Planning run.
  Generic Agent/Tree visibility, color, opacity and view toggles delegate to
  the same observation presentation journal. Planning parent visibility and
  opacity constrain rendered sources without flattening each child's setting.
  Actual shared controls/save/cold restore/parent-toggle acceptance passed
  in `cumulative-real-model-parent-controls-20261012.xml` (3 tests, including
  the actual supplied detector/CNN product scenario). The 3D empty-scene
  placeholder is absent when observed meshes exist; screenshots were inspected.
- The last prompt replay found two further admission/identity details.
  Intraoperative planning requires an owned nonempty associated preoperative
  plan, not just an empty linked tab. Detection and dose-only actions are
  independent. Uploaded-image display names use original selected filenames
  rather than server collision-avoidance timestamps. Actual product + source
  prerequisite checks passed in `cumulative-source-plan-and-original-name-20261012.xml`.
- Historical printed guides are discoverable across immutable Planning
  snapshots after a planning-only replan. They cannot be treated as "no guide"
  and bypass guide-first constraints. An invalid cached accepted placement
  pauses for new fit review, rather than being silently rebuilt as approved.
  Associated guide/preparation contracts passed 46 tests and follow-up guard
  tests passed 12 tests. These latest additions still require their final freeze
  regression; earlier green full-suite totals do not retroactively cover them.
- Empty-workspace stage/reference edits use clinical revision, not display
  state revision. Presentation-only saves preserve phase editing; actual
  populated clinical reclassification still requires explicit migration.
  Lifecycle counters fence older callbacks after valid metadata changes.
  Real store/runtime integration passed 48 tests after this final boundary
  correction; inputs/clinical states are not rewritten by ordinary display saves.

### Continued legacy-entry audit and intermittent restoration evidence

- The later archive `f6655e7966bdc19ef0c98881e407e653cb9dad52db926daf51779fac5fa849a2`
  reported **3879 passed, 2 failed, 2 skipped, 4 passing subtests** in 951.71 s.
  Both failures were actual cold-restoration readiness failures, one after
  shared observed-source presentation edits and one after guide acceptance.
  Earlier green totals do not invalidate this evidence. A separately replayed
  actual-product batch passed all three scenarios in 339.67 s, but did not
  reproduce the intermittent failures; this alone is not a root-cause fix.
- Actual visual barriers now retain bounded failing-producer details, and
  the supplied-model browser scenario repeats three further cold reloads
  after shared leaf controls. A new immutable archive with these diagnostics
  is under full regression; it is not retroactively applied to older freezes.
- Further source review found Session-only ownership in legacy Data Tree
  confirmations, delayed mutation repaint, generic-mask refresh coalescing,
  completed-segmentation coalescing and Input action locks/headers. These now
  capture the initiating timepoint and loading generation. A confirmation
  interrupted by navigation sends no destructive request; a committed old
  request does not clear the new target's selection or refresh its geometry.
  New-target Input work is not unlocked by old-target completion. Unit
  interleavings execute the real product handlers with explicit controlled
  transport fixtures, not substituted clinical detector or dose algorithms.
- The same audit found that structure-policy "Replan" previously only
  refreshed `/planning/results`. The confirmed action now calls the actual
  scoped `/planning/run_step` executor before display delivery. It does not
  authorize guide/report generation. Batch reconstruction also had unrelated
  undefined mask-mutation variables; it now reconstructs the captured batch
  and stops before processing another timepoint.
- Structure appearance and generic-mask volume caches include the timepoint
  and generation, not only Session/name. An owned legacy-entry regression
  passed **218 tests**; a subsequent cache/mutation/Input/Mask regression
  passed **46 tests**. The strengthened interleaving test additionally checks
  actual replan dispatch and independent A/B label hydration. Current changes
  still require a newly frozen full regression and actual product replay.

- The diagnostic frozen archive `63177d5ac9f9aa36553d23bb299164711e3c9018fd79e3da12f050aea3f71e09`
  passed **3882 tests, 2 skips and 4 subtests** in 985.69 s. The subsequent
  owned-legacy-entry archive `376db0405d368715c6d6a48502054d91a9ed77743f5193e8940cbafc774d2dfb`
  reported **3878 passed, 5 failed, 2 skips, 4 passing subtests** in 983.45 s.
  Those five failures were extracted-function measurement fixtures missing
  the actual newly required scope helpers; the fixtures now load those real
  helpers, rather than replacing them with unconditional success stubs.
  All 21 measurement browser scenarios then passed. Neither old full result
  covers later guide/SSE changes.
- The native guide UI now captures scan ownership in generation, validation,
  loading, automatic-generation checks and deferred transient retries. The
  initial UI and JavaScript defaults request four auxiliary rings consistently
  with the backend dense policy; restored explicit user settings are retained.
  Geometry still rejects unsafe bores. Executed guide/UI contracts passed
  **231 tests**, not a material-strength or clinical-fit certification.
- A later actual three-scenario product replay reported **1 failure, 2 passes**:
  two-image cold restore remained intermittently partial. A direct replay and
  a replay with three added cold reloads each passed (145.38 s and 147.56 s).
  This failure remains under investigation; no readiness check was weakened.
  Bounded producer diagnostics are retained as structured JSON, and boolean
  `false` producers are no longer silently counted as successful restoration.
- The terminal chat planning timer was a second, browser-side source of
  unrequested guide generation and report capture. It now restores saved
  outputs only, with explicit captured scan/timepoint timer keys and preserved
  Report state. Report *readiness* is separate from capture execution; the
  explicit guide/report executors remain available. Timer interleavings and
  legacy Input/report/measurement contracts passed **225 tests** after this
  change. A current-code full freeze is still required.

- Frozen archive `1bb1e386ad1a0c0e25c317d0b4676d85a0c2539cd5944d8eee1735888cfa3647`
  passed **3886 tests, 2 skips and 4 subtests** in 959.89 s. It includes the
  owned legacy mutations, guide timers/dense UI default, pure terminal chat
  refresh and strict boolean visual-producer failures. It precedes the native
  intraoperative admission/path/review-pause corrections below.
- Actual native intraoperative acceptance discovered that the old button
  demanded a plan in the *target* timepoint, prompted for an extra image, and
  the old route discarded review-pause metadata. The button now dispatches
  the current owned stage-aware pipeline, enables before target seed planning,
  and returns a structured `pending_review` packet without claiming completion.
  Saved observations and fit/source controls are restored without repeating
  inference to paint the scene. Legacy non-timepoint behavior is retained.
- The actual native scenario then exposed public workspace-relative image
  paths being interpreted relative to the server checkout, and completed
  zero-label OAR masks being treated as missing segmentation. Numerical
  requests resolve aliases of the selected owned reference, not another
  displayed image or another timepoint. Empty OAR with explicit provenance is
  retained; an absent/unknown OAR is not invented. Custom-runtime reads are
  authorized only inside the authenticated patient directory, never all /tmp.
- Reference mismatch now returns a localized 400 packet. Its actual HTTP
  negative case also found and repaired a duplicate `success` keyword in the
  global Timepoint error handler (previously turning rejection into HTTP 500).
- `cumulative-real-native-pause-complete-20261012.xml` passed **2 tests**,
  including actual full-page native entry, supplied detector, reconstruction,
  current owned image, and explicit review pause with **12 real detections**.
  Its nonempty one-source preoperative input and current CTV/OAR masks are
  explicitly synthetic test *inputs*, not claimed optimized clinical planning
  or reference segmentation. No detector, route or clinical algorithm was
  replaced in that product scenario. Counts are not forced to match the
  synthetic preoperative input. Additional transport-only fixtures are
  separately labelled; a current frozen full regression is still required.

### Integration continuation on 2026-10-13

- Frozen archive `a497b6cc7daa51f9c647454e8921ee8c3a56f31aeb1fc72af7721b54d2e72606`
  did **not** finish its full regression. The preserved JUnit file contains
  3163 records and an internal `BrokenPipeError` while flushing the terminal
  output after the client turn ended. It has zero assertion failures but is
  **not** a passing full-suite result. Subsequent runs redirect output to a
  stage-owned log independently of the interactive output pipe.
- Stage-aware legacy `/api/plan/intraoperative` reuses the common current-image
  pipeline, including observation review pauses; it does not require an old
  plan inside the target workspace or force detection count matching. The
  actual supplied-model/full-page scenario exercises both native and alias
  entries and rejects `/api/plan/preoperative` in an intraoperative target.
  The latter now holds the same scoped mutation lock as manual Input work,
  and unsuccessful producers no longer publish a completed checkpoint.
  `cumulative-preop-stage-guard-20261013.xml`: **42 passed** in 52.44 s.
- The legacy preoperative writer still stored normalized values in `_gy`.
  It now writes schema-2 physical-Gy aliases and explicit normalized fields,
  using the common validated conversion and declaring every field's units.
  A nonzero software input tests both the physical/normalized readers and
  evaluation scaling; no zero array masks a calibration defect.
  `cumulative-legacy-dose-units-20261013.xml`: **103 passed** in 5.61 s.
  This is software-contract evidence, not independent source dosimetry.

- Archive `f61d397b1edd115d595c028ac70c1e7607f0c06ae3ce19ca4ecb78fa748aefb4`
  completed its regression: **3888 passed, 2 failed, 2 skipped, 4 passing
  subtests**, 918.37 s. Both failures were actual cold-page restoration, with
  bounded receipts `hydration_run_id=2`, `ready=false`, `cancelled=true`,
  `reason=restore_cancelled`. This failed freeze is retained, not called green.
- A reachable legacy scheduling cancellation was identified: declining a
  Session-wide startup restore cancelled **all** barriers, including the
  mounted timepoint's transaction. Legacy-only cancellation now clears its
  scheduler/legacy barriers without altering the owned hydration generation,
  notice or barrier. Real Session transitions still cancel their old restores.
  Stale CT-ready continuations/loaders are rejected before synchronous global
  metadata or debounce changes; cancelled debounce promises settle explicitly.
  Structural and generic-mask failures now survive producer promise delivery.
  Partial timepoint readiness is never converted into successful report or
  screenshot capture simply because another live object exists.
- Captured viewer-fit and delayed layout-settle callbacks check the same
  timepoint/render owner, not just Session. The executed real-function tests
  include **19 producer/barrier cases**, fit/paint interleavings and the legacy
  scheduler ordering negative. Narrow controlled transports are labelled as
  contracts, not clinical inference.
- `cumulative-owned-cold-restoration-products-20261013.xml`: **63 passed** in
  417.02 s. This includes actual uploads, two-timepoint switching and repeated
  cold reloads, native complete bundle export/chooser import, supplied model
  reconstruction/source corrections/current dose, native+legacy continuation
  review pauses, and the synthetic CPU guide/review four-canvas scenario.
  It does not establish real patient registration or arbitrary live-provider NL.
- Generic total dose/isodose/DICOM-RT selection and execution now reject stale
  arrays after real future-source deletion; independent valid implanted dose
  stays exportable. Report source tables respect both artifact status aliases.
  Evaluation fingerprints include the actually resolved prescription and unit
  declarations; changing prescription reuses numerical source dose, not old QA.
  `cumulative-dose-export-quality-fingerprints-verified-20261013.xml`:
  **145 passed** in 14.78 s. Subsequent localized-export/worker ownership batch:
  **92 passed** in 11.45 s. Counts are separate snapshots, not additive coverage.
- Planning snapshots now include source-separated components, evaluation/cache
  receipts and explicit unit/current-grid aliases. A→B→A restores A's full
  package, while old snapshots clear absent fields instead of leaving B's.
  History already invalidated by upstream edits cannot revive current QA on
  activation or missing-alias hydration. Acquisition observation facts and
  standalone implanted dose are not moved into mutable Planning ownership.
- Changed confirmed source settings invalidate numerical dose, continuation,
  current QA/report and current-use history flags atomically. Identical numerical
  settings retain their confirmation identity and do not advance clinical state.
  This operation neither recomputes nor deletes actual observations or printed
  guide geometry. Actual factory/HTTP and invalidation contracts:
  **15 passed** in 8.60 s.
- The current Planning module has fresh four-pair manufacturing dependency
  evidence in `surgical_guide_dependency_renewal_2026-10-13-component-history.json`.
  Each before/after subprocess explicitly loads its exact module, and final
  triangles, bore manifests and non-timing QA match. Guard renewal is tied to
  that artifact; no material-strength claim or guard bypass is made.
  A new complete frozen regression covering **all** these subsequent changes
  remains required; earlier full totals do not cover them.

### Owned Input / native continuation follow-up on 2026-10-13

- Actual reviewed native continuation exposed an Input persistence defect:
  `/api/config` modified only a detached request Agent. Current Input settings
  now live in acquisition-owned `timepoint_planning_config`, are restored into
  HTTP/chat/named-pipeline views, and are not copied into historical plan state.
  Allowlisted schema-1 Agent config remains the migration fallback. Current
  settings GET/POST are metadata-only; provider/workspace control keys are not
  published as Input configuration. **8 real authenticated HTTP/store tests**
  cover new-request reads, independent A/B settings/revisions, cache eviction,
  a new application, actual ZIP export/import, invalid/identical updates and
  reset/named-execution ownership. These are not model accuracy tests.
- The Input controls project the captured owned configuration, not just file
  defaults or old UI drafts. Actual Apply uses the accepted normalized response.
  **18 executed production-function contracts** include late GET/mount/Apply,
  exact editable-field round trips, and clinical-write/presentation barriers.
  A real page found queued old presentation saves could reject navigation after
  configuration advanced clinical revision. Old writes now finish before the
  config mutation, later writes wait for its exact-owner acknowledgement, and
  the normal CAS guard is retained. The actual product batch
  `cumulative-owned-input-import-mount-current-20261013.xml` passed **35 tests**
  in 194.71 s, including separate A/B accepted parameters, immediate switching,
  repeated cold reloads, actual export/native chooser/import and both restored
  configs. Import creates an independent Session; its initially selected row
  is checked against its actual owner rather than assuming the old browser
  preference. Controlled DOM/transport contracts remain separately labelled.
- The actual native supplied detector/CNN/review/continue composition now
  returns a successful zero-supplemental-source plan when the declared low
  software-test Rx is already covered. The test retains 12 physical observed
  sources and reads the total dose and total-basis metrics after completion.
  Upstream one-voxel target/zero-OAR/source-plan inputs and source dimensions
  are explicit test fixtures, not clinical adequacy or optimized preop evidence.
  The first composed failure was lost config, followed by nested array JSON
  failure and stale quality status. Nested dose arrays now remain behind the
  owned dose endpoints; successful current evaluation replaces stale quality
  flags, keeps reports stale until regenerated, and records `source_set=total`.
  Full orchestration no longer claims success after failed dose calculation or
  evaluation. Current composed rerun
  `cumulative-native-owned-input-final-composition-20261013.xml`:
  **61 passed**, 160.26 s, including actual model/page/source confirmation,
  human observation review, zero-new-source completion and total quality read.
- Current evaluation config is separate from immutable `plan_config`: changing
  applied Rx invalidates current DVH/quality/report, not unchanged physical
  dose. Optimizer-policy changes have a separate supplemental-plan dependency.
  Current recompute, component DVH, manual evaluation, reports/rationale and
  Agent inspection share that basis; explicit historical report evaluation is
  retained. Source geometry/model/calibration are not replaced by Input QA
  fields. `current_dose_evaluation_config` travels with each plan's QA, and
  history activation/alias repair cannot revive old-Rx quality. Actual numerical,
  report, ownership and history integration batch
  `cumulative-current-input-total-evaluation-20261013.xml`: **122 passed**,
  13.48 s. No dose model is substituted as product evidence in that batch.
- Current config changes and these consumers are subsequent to the previous
  frozen full run. Another exact-hash guide dependency replay and complete
  frozen regression are required. The earlier local broad run containing
  `test_review_round6_regressions.py` had 3 failures (two setup and one absent
  benchmark CLI); it is not called green or used as final remote evidence.

### Current route, Agent quality and provider audit (2026-10-13)

The following batches are separate, overlapping results, not additive counts.

- The preceding owned-input/quality freeze reported **3968 passed, 2 skipped,
  4 passing subtests** in 1333.36 s. Archive SHA256
  `77e5a9f0dc2a9b4ce177c1be95728edf01e2096df4e53ae5653c731fdc48b3d1`.
  It does not cover subsequent route/provider/standalone-Agent corrections.
- Actual registered Flask inventory: **157 rules, 156 endpoints, 167 explicit
  method/rule pairs**. Thirteen pre-fix negatives exposed file membership,
  export-consumer and URL-Session mismatch bugs. All are now mandatory passing
  assertions, with positive nondefault artifact and signed-screenshot controls.
  `ScopedWorkspaceStore.session_artifact_path`, `ExportJobManager.get`, the
  central hook and immutable browser export scope enforce the original target.
  Combined targeted regression: **443 passed**, 23.75 s,
  `cumulative-route-file-export-provider-current-20261013.xml`. See
  `HTTP_TIMEPOINT_ROUTE_INVENTORY.md`; an inventory is not numerical acceptance.
- Standalone registered `dose_evaluation` now reads current owned canonical
  components, validates image/component fingerprints and uses current applied
  QA prescription rather than historical plan Rx. Agent publication retains
  all CTV/OAR DVHs, total-dose basis and dependencies; what-if evaluations do
  not overwrite current QA. Current quality scorer/OAR/report consumers reject
  unavailable measurements rather than assigning zero or falling back to stale
  raw aliases. Physical Gy prescriptions are never multiplied by an inferred
  scale. Batches: **134 passed**, 15.365 s,
  `cumulative-owned-tool-quality-report-current-20261013.xml`; **106 passed**,
  11.67 s, `cumulative-agent-evaluation-recovery-current-20261013.xml`.
  The latter includes nondefault scoped Agent publication and a fresh-store
  cold restore, plus a real CPU registration-child interruption and explicit
  retry. No product dose model was replaced by a mock for these claims.
- Nondefault native guide generation and owned cold recovery passed with actual
  geometry: **89 passed**, 308.35 s,
  `cumulative-nondefault-native-guide-current-20261013.xml`. Four real paired
  guide geometry/manifest/non-timing-QA replays support dependency renewal in
  `benchmarks/surgical_guide_dependency_renewal_2026-10-13-owned-input-quality.json`
  (SHA256 `470bd3467cd5806c426b7ca23557a49888803661b4b9240f2268a3c17e48a152`).
  Pipeline and planning-runs dependency files were not changed by later
  route/provider repairs. This is not printed material strength validation.
- Actual external-provider three-turn acceptance used only fictional saved
  metadata in a new isolated Session. It read mounted B's **145 Gy / 222 Gy D90**,
  actually renamed B to `Natural Language Review` without changing A, then
  compared A's **130 Gy / 111 Gy D90** with B. Real `/api/chat`, provider, scoped
  worker and store were used. Evidence:
  `benchmarks/live_timepoint_natural_language_acceptance_2026-10-13.json`, SHA256
  `2c44d67af93cb6c46bf7d51865207bc5a8724356e16a516d4f5a96cfc521638b`.
  Earlier attempts failed because streaming schemas hid catalog tools, title
  text containing “Review” was misrouted as analysis, provider tool output lacked
  resolvable IDs, and exact title-only human evidence was not recognized. Those
  actual failures motivated the fixes; the passing result is not evidence for
  arbitrary utterances, clinical acceptance or all catalog operations.
- Frozen archive SHA256
  `d47fa4406bcbfb22967020900671e1d271b29b2f5c06da0faa41e0e24a346d2f`
  includes 239 changed files and 180 compiled Python files. Its full run
  `cumulative-provider-route-dose-final-frozen-full-20261013` finished with
  **4238 passed, 2 failed, 2 skipped, 4 passing subtests** in 1305.15 s. Do not
  describe this freeze as green. Failures were the actual product browser's
  bundle-file download and cross-account signed-screenshot response status.
  The former made an unscoped `page.request` file request for a nondefault job;
  the new ownership guard correctly rejected it, but only the ZIP link had an
  explicit target URL. Status responses now decorate every file with its owned
  URL (without mutating the durable job), the browser uses that real link, and
  export UI retains the captured header scope as well. The latter is now a
  localized 403 file-access denial before disclosure, not an unlocalized 400.
  New scoped-file-link and localization negatives/positives passed **219 tests**
  remotely (`cumulative-export-scope-language-current-20261013.xml`, 7.80 s);
  an overlapping local route/message batch passed 237 tests. The separate full
  browser export/native-chooser import and route/auth batch passed **243 tests**
  in 183.42 s (`cumulative-export-file-link-auth-product-current-20261013.xml`),
  including the previously failing real two-timepoint product scenario. New
  frozen full regression is required; targeted passes do not erase the old
  two failures. Skips remain missing public-origin dependencies and unavailable
  `NGINX_TEST_BINARY`, not passing deployment evidence.
- Independent registered `plan_refinement` has been audited as a proposal
  boundary, not a hidden second optimizer. Owned calls now retain the original
  plan, read current total Gy, reject prescription overrides and return only
  explicitly unvalidated dose-array ZYX advisory locations. They never invent
  physical axes, append observed implants or claim feasible guide/outside paths.
  Canonical planning remains the separately authorized path for actual fixed
  capsule/needle/guide admission and subsequent dose inference. The legacy
  preoperative candidate API retains existing valid axes, excludes OAR voxels
  and no longer falls back to an unsafe mean centroid or hardcoded direction.
  Actual owned adapter/registered executor/numerical positive and negative
  tests passed **37 tests**, 22.90 s; two existing refinement regressions also
  passed (80 unrelated tests deselected). This is advisory isolation evidence,
  not a successful whole guided incremental plan or clinical validation.
- The next frozen archive
  `47ce3f0604a9f25be5cdb4110f5b75c7d813d20c3376e272f0635b69933465fc`
  (242 changed files, 183 compiled Python files) passed **4278 tests, 2 skips
  and 4 subtests**, 1351.16 s, in
  `cumulative-export-refinement-final-frozen-full-20261013.xml`. It covers the
  export-link/auth repairs and bounded refinement changes above. It does not
  retroactively cover the following newly found natural-language defects.
- Real post-edit natural-language/CNN acceptance found two further issues:
  nearest-noun action pairing confused a locative “current Table Viewer” with
  the dose object; a provider then recalled a stale observation revision from
  the previous turn. The initial attempt did not compute dose, and the next
  attempt computed the first dose but correctly rejected the stale second
  call. Those failures are retained in isolated logs. Locative Viewer mentions
  are now separated from action objects without granting negated, quoted,
  conditional or past commands. The request-owned observation head is now an
  injected dependency, hidden from scoped provider schemas; explicit human
  preconditions remain strict, and producer pre/post-inference and publication
  CAS checks remain. The targeted local parser/authorization batch passed
  **176 tests**, 11.84 s; Linux source/head/dose contracts passed **51 tests**,
  15.45 s (`cumulative-current-head-dose-contract-linux-20261013.xml`). A local
  overlapping 51-test batch had 9 Linux-only supplied-runtime setup failures
  and 42 passes; it is not called green or used as inference evidence.
- The repaired actual `/api/chat` + external provider + existing CNN sequence
  passed on a wholly generated 20-cubed CT and two explicitly supplied manual
  known-axis observations: **2 sources**, then a real journal exclusion and
  stale-dose invalidation, then **1 source** on a second natural-language
  request. Both dose hashes and observation heads changed; sibling state did
  not change, and no Planning, future source, needle, guide or report was
  created. Evidence:
  `benchmarks/live_fictional_implanted_dose_acceptance_2026-10-13.json`, SHA256
  `a972c68201cbffd51dbf33547f632137196c62024d41c581fbe903fd8e6203c7`;
  actual parser SHA256 `f95aff4a2c7c37e3825848b16ab6b8c6cfa5aa7144a2db130759f66bd25d9ccc`,
  adapter SHA256 `9f3e1cfdc77a11173ef8709cb9210f41882a0a2c0f30a4eedefd0f441e94560d`.
  CNN checkpoint SHA256 `d73d19f22c846ee989786eabd9336fba80b8c9658881a6e878aca846861b5681`;
  calibration 190.8 Gy/model unit. Source dimensions, CT and observed centers
  are declared test inputs, not detector accuracy, clinical review or dosimetry.
  No patient image or production case was sent to the provider.
- The live response misinterpreted a zero *axis-completion* count as proof that
  the directions were inferred. The formatter now distinguishes current axis
  inputs from axes completed during that dose record; zero does not establish
  original axis provenance or clinical review. This presentation correction
  has contract coverage and is subsequent to the live two-turn artifact, not
  a retroactively changed provider response. A final new freeze/full run must
  include these latest parser, dependency and presentation changes.

### Safety, original-guide acquisition and synchronization checkpoint — 2026-10-13

- The previous complete frozen regression, archive
  `12b91b43c31600e0273ed83287678c25e7f36f8939d1887a5d09f069bbc49700`,
  passed **4295 tests, 2 skips and 4 subtests** in **1289.60 s**.
  Its XML is `cumulative-natural-language-dose-final-frozen-full-20261013.xml`,
  SHA256 `e65f98e02895403b3754cd7c5e32f92b40c9af87b3ae9454157172042ad989b5`.
  The two skips are public-origin deployment requirements and an unavailable
  Nginx test binary, not successful deployment tests. This full run predates
  the safety/OAR and original-source changes below.
- Current safety and OAR checks now distinguish unavailable/invalid measurements
  from genuine zero, require authoritative current total-dose evaluation,
  use current prescription/constraints rather than historical plan settings,
  and check relative prescription limits with explicit units. Empty or incomplete
  checks cannot become a PASS or export approval. The existing clinical knowledge
  base limits were not changed. The source-backed merged safety/OAR batch passed
  **243 tests** in **15.35 s**:
  `cumulative-owned-safety-oar-current-20261013.xml`.
- Original printed-guide acquisition repair is documented in
  `GUIDE_SOURCE_IMAGE_AUDIT.md`. Normal reference changes now retain archived
  guide discovery; an old parent fingerprint binds registration and overlay
  to original A rather than newly selected C. File, pixel, geometry and parent
  evidence are checked at capture/publication/access/review. Unverifiable sources
  fail closed; direct visible-guide fitting does not require original CT pixels.
  Legacy single-image compatibility explicitly does not prove historical identity.
- Source recovery now has a fixed bilingual HTTP message. The actual guide-review
  controller displays verified original-image identity, unverified legacy evidence,
  or direct-guide evidence, without treating those categories as clinical approval.
  Worker diagnostics stay in the owned journal; public job failures are localized.
  Browser contract tests verify these labels, live language changes and removal of
  target-A provenance on target-B. Their transport is synthetic and is not claimed
  as a new real-patient end-to-end registration acceptance.
- On Linux, the merged original-source, localized recovery, registration child/
  CPU/workflow, guide manifest, image-service and safety/OAR batch passed
  **298 tests**, **38.73 s**, 3 SimpleITK warnings:
  `cumulative-safety-guide-source-targeted-20261013.xml`. This includes the
  actual child-crash/retry check that had a Windows pipe-message mismatch.
  Counts above are separate executions, not additive acceptance totals.
- The code freeze
  `f7b6868b5605234079827f8c54f7139eb1b745813459b0152c96dbd9fd862829`
  contains **253 changed files / 192 compiled Python files**. Its new complete
  regression is running in the isolated
  `cumulative-safety-guide-source-frozen-20261013-checkout`, with PID **1733881**
  as observed at **2026-10-13 09:25:44 UTC**. A running process is not a passing
  result. Read `cumulative-safety-guide-source-frozen-full-20261013.log` and its
  final XML before claiming current full-suite acceptance.
- At the user's request to synchronize and wrap up this round, the candidate,
  manifest and evidence are transferred to the previously approved isolated
  remote stage. The running freeze is not edited. LAN/public code, runtime and
  processes are not overwritten or restarted. See
  `SYNCHRONIZATION_HANDOFF_20261013.md` for exact targets and remaining gates.

### External evidence still unavailable / bounded acceptance

Synchronization follow-up: the frozen run completed with **4506 passed,
1 failed, 2 skipped and 4 passing subtests**, **1333.75 s**. The sole failure is
`test_actual_product_guide_registration_and_review_on_synthetic_phantom`:
the native browser's image-registration job returned HTTP 400,
`guide_source_image_unverified`, instead of expected 202. The synthetic setup
upload/load/history interaction needs further diagnosis; no provenance guard
was weakened and no mock fit supplied to turn it green. Current full-suite
acceptance is **not passed**. This overrides the earlier running-PID observation.
Full source synchronization is audited separately in
`CUMULATIVE_REMOTE_SYNC_AUDIT_20261013.md`.

- Live-provider current-read/title-rename/two-timepoint comparison was executed
  as described above. Other catalog/image/clinical commands and all paraphrases
  are not thereby live-provider accepted; schema/target-grant tests alone do
  not establish that broader claim.
- Actual paired patient preoperative/intraoperative images, current CTV/OAR,
  the physically printed guide and reference placement/dose measurements
  were not available as an end-to-end clinical reference case. Supplied-model
  demo, synthetic geometry and phantom review tests are explicitly distinct.
- Printed material strength, sterilization/manufacturing tolerance, source
  commissioning and independent dosimetry remain external validations, not
  facts that unit tests can invent.
- LAN/public production sources, runtime databases, ports and services were
  not replaced/restarted. The read-only listener check found public loopback
  18082 present and no LAN 8080 listener. Do not assert that the user's current
  website now runs this candidate.

All updates remain in the isolated candidate; this is not an assertion that the
LAN or public service has been deployed or commissioned with this code.

## Requirement-by-requirement ledger

| Check | Cumulative requirement | Actual implementation paths | Evidence / remaining acceptance |
|---|---|---|---|
| 1 | Owned Session → timepoint → resources | `web/timepoints.py`, `timepoint_context.py`, `timepoint_images.py`, scoped file/job consumers | Real store/image tests; registered 157-rule HTTP and 40-capability Agent inventories executed. This is bounded scope evidence, not every workflow accepted. |
| 2 | Independent four panels and all scene state | `brachybot-timepoints.js`, `brachybot-timepoint-workspace.js`, legacy restore hooks | Actual two-timepoint upload/switch/cold recovery and import passed; late-loader contract negatives passed. Final full regression pending. |
| 3 | Late jobs publish to original scan | `timepoint_http.py`, `timepoint_chat.py`, `chat_tasks.py`, `timepoint_context.py` | Captured request/read-set tests and registered route inventory passed; actual browser late-overlay negative passed. Whole nonzero guided sequence remains a separate gate. |
| 4 | Save/load/restart/legacy migration | `migrate_default_timepoint`, immutable version ledger, `timepoint_bundle.py` | Actual complete native-chooser import plus graph/journal roundtrips passed; legacy fake-path mount regression passed. Whole clinical composition audit remains. |
| 5 | Shared dialogue/read-all, isolated mutation | detached `ScopedChatRuntime`, `timepoint_inspector`, registry rebinding | Registered capability inventory and owned contracts; real provider compared two saved timepoints without shared mutation. |
| 6 | Omitted target uses submitted mounted pane | `captureSubmission`, `capture_chat_scope`, trusted turn scope, locative request pairing | Real provider reads/renames submitted nondefault target and performs post-edit implanted-only CNN dose there. No claim of every possible utterance. |
| 7 | All old Agent tools respect scope | `owned_tool_arguments`, registry workspace binding, common tool boundary | Actual Agent inventory: 40 registered capabilities, no missing scope adapter; target-grant/readset tests passed. Arbitrary external-provider NL is not thereby proven. |
| 8 | Current intraoperative anatomy only | image planning-reference bridge, `ContinuationPreparationService` | Physical/owned-reference tests; actual complete planning sequence pending. |
| 9 | Baseline participates from iteration zero | `plans/continuation.py`, main pipeline/rule/RL/refinement/repair | Numerical baseline/optimizer tests, actual CNN component recompute/sum and zero-addition composition passed. Full guide-to-exterior nonzero-addition product composition remains pending. |
| 10 | Fixed implants and interference | `FixedSeed`, `FixedNeedle`, canonical direct planning delegation and advisory-only refinement | Positive/negative physical capsule/path tests; direct planning delegates owned canonical steps and refinement cannot admit physical seeds/channels. Whole reviewed-guide nonzero-addition product composition remains pending. |
| 11 | Edits invalidate dependent resources | immutable observation journal, `timepoint_resources.py`, `ImplantWorkspace.publish` | Correction tests and stale aliases; whole Monitor/report/export graph pending review. |
| 12 | Sufficient dose adds zero sources | `baseline_reaches_target`, zero-addition pipeline branch, report/current-plan count extraction | Unpatched actual CNN baseline and planning/dose stages add zero sources; explicit zero-count report/query tests passed. Synthetic target is clearly labelled, not claimed clinical coverage. |
| 13 | Guide-first then safe exterior paths | `continuation_search.py`, hard guide mesh/clearance, repair guards | Existing numerical tests; complete reviewed-guide execution acceptance pending. |
| 14 | Dense realized bores + manufacturing checks | `surgical_guide.py`, `guide_manufacturing.py`, final STL bore manifest | Four paired current/earlier geometry and non-timing QA runs passed, measured wall/guidance/interbore constraints tested. Printed material strength remains externally unestablished. |
| 15 | Printed guide remains rigid SE(3) | `guide_placement.py`, `guide_registration_cpu.py`, `guide_service.py` | CPU geometry tests; no deformation applied to printed triangles. |
| 16 | Visible-guide fit first, image-derived estimate otherwise | guide registration method/ROI/surface fitting, original-parent image resolver | Actual CPU image and visible-guide child jobs passed on synthetic geometry, including deleted original CT and original-A overlay after reference-C selection. Actual paired patient guide fit is not established. |
| 17 | Display + human confirm/reject | signed clinical-version overlay receipt, guide review API/actual CT+mesh canvases | Actual full-product CPU registration, four canvases, human accept, cold restore and reject passed on synthetic phantom; localized failures and forged receipts tested. Real-patient fit not established. |
| 18 | Real observations in 2D/3D/tree | `brachybot-implant-observations.js`, native physical centers/axes | Actual supplied detector/full-page 2D/3D/Tree and cold restore passed. |
| 19 | Per-source controls | persistent presentation journal, tree stable IDs | Actual eye toggles/color/opacity/correction/exclusion/cold restoration passed, not just script fixtures. |
| 20 | Distinct observed/planned encoding | cyan observed / gold planned roles | Actual supplied-detector full-page observed controls and role contracts passed. Co-rendering a genuinely optimized nonzero supplemental guided plan remains a composition gate. |
| 21 | False-positive exclusion, 2D add + 3D refine | common correction executor, explicit drafts/Save/Cancel | Actual pointer placement/3D drag/save/context exclusion on supplied acquisition passed; removal is an observation exclusion, never a physical surgical action. |
| 22 | Correction synchronizes all consumers | observation revision + transitive fingerprints/stale flags | Dose tests; all report/export/Monitor consumers pending final regression. |
| 23 | Detect → reconstruct → display continuously | detector service, async job, `implant_command`, viewer bridge | Actual supplied detector/reconstruction/full-page delivery passed; actual post-edit chat/CNN dose passed separately. Live NL detector-to-full-page composition is not implied by those separate tests. |
| 24 | Supplied directions used in rendering/dose | pinned `SuppliedXYOrientationProvider`, source geometry | Real model/CNN execution; XY assumption remains visibly estimated, not clinical proof. |
| 25 | Honest units and exactly-once calibration | `dose_units.py`, canonical physical fields, evaluation inputs, report generator | Actual CNN sum/Viewer and current-QA consumers tested; low physical-Gy prescriptions remain physical Gy. Independent dosimetry is external. |
| 26 | Multiple images and explicit planning reference | actual image upload/collection APIs, display projection | Actual HTTP and full-product tree hierarchy/reference retention/mutual display/per-image opacity/cold recovery passed. Exact image-ID Agent mutations tested. |
| 27 | Old Monitor/manual/screenshot/report/export scope | central HTTP facade, scoped Monitor buckets, export worker/read-set, file guards | Full registered route inventory executed; old file/export leaks repaired and actual nondefault export/import passed. Deployment freeze: 4524 passed, two actual page-recovery failures; guide provenance fixture corrected. Both recovery workflows subsequently passed targeted repair reruns. Full-suite acceptance on the final frontend follow-up remains unclaimed. |
| 28 | Global language consistency | code-based messages, localized forms/controls | Registration/recovery and file/export errors have executed zh/en contracts; guide-source labels update with language and clear on navigation. Current merged full regression remains pending. |
| 29 | Failure/restart/retry recovery | durable operation metadata, immutable stage journals, explicit retry | Real CPU child interruption, persisted failure and explicit new-request retry passed; existing detect/dose failure contracts and cold recovery passed. Whole clinical sequence restart remains pending. |
| 30 | No cross-scan/session data or progress pollution | owner/session/timepoint/lifecycle/generation/read-set fences | Negative controls; complete production async/browser evidence pending. |
| 31 | Separate implanted/planned/total dose, score on total | `dose_components.py`, `/api/dose/view`, source selectors, component exports and report source table | Actual CNN sum/reuse and native button recompute passed. Supplemental manual edits block old planned/total views and exports; stale total cannot restore historical QA. Final all-consumer regression pending. |
| 32 | Reuse unchanged upstream inputs; invalidate changed dependencies | content fingerprints, observation/image journals, reference cache, continuation geometry signatures | Real source-dose reuse measured; changed current anatomy/guide/needles/channel constraints invalidate candidate reuse. Inference source and presentation are separate. Whole graph final audit pending. |

## Prompt coverage

- **a:** rows 1–10, 13–17, 26–30; independent patient/timepoint model, guide
  inventory, current anatomy/baseline and shared Agent coordination.
- **b:** rows 4, 8–17, 24–26, 31–32; cumulative physical/source/calibration
  corrections, not a zero-based residual-target workaround.
- **c:** rows 18–20.
- **d:** rows 12–14.
- **e:** rows 3, 6–7, 28, 30.
- **f:** rows 18–24, 27–30.
- **g:** rows 11, 25, 31–32.
- **h:** rows 1–7, 15–19, 26–30; actual isolated native restoration/migration
  acceptance is recorded above. A deployment or complete guided continuation
  is not implied by those bounded browser scenarios.
- **i:** every row, with particular attention to effect authorization, target
  defaults, accessible controls, errors, cancellation and natural-language parity.

## Final gate

Do not mark this ledger complete until every pending item has an implementation
path and appropriate executed evidence, the final candidate is frozen, the full
regression including guide paired evidence passes, and deployment/runtime state
is explicitly distinguished from isolated candidate state. Clinical source
commissioning, independent dosimetry, printed strength and real surgical fit are
separate external validation tasks and must never be invented by tests or prose.
