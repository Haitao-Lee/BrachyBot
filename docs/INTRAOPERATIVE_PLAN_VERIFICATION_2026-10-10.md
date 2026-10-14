# Multi-timepoint implementation: plan verification and continuation branches

Date: 2026-10-10. Status: **in progress; not deployed and not clinically commissioned**.

2026-10-11 implanted-observation follow-up: detect/reconstruct display, individual appearance/exclusion/restoration, missed-seed 2D placement and 3D refinement, current source confirmation and separate CNN implanted-dose recomputation now have candidate integration. See `INTRAOPERATIVE_IMPLANT_INTERACTION_VERIFICATION_2026-10-11.md`. This supplements, rather than substitutes for, the unfinished complete multi-timepoint production bridge and operational validation.

The final 101-file combined candidate passed the unfiltered root suite: **3,765 passed / 2 skipped / 0 failures / 0 collection errors**, four passing subtests and 31 existing deprecation warnings, in **407.47 seconds**. Final new focused suite: **73 passed** in 13.93 seconds. Candidate hashes, live-before hashes, Python/JavaScript checks and the paired guide dependency guard passed. This is synthetic software evidence, not a deployed real-model or clinical acceptance result.

2026-10-11 follow-up: submission-owned ordinary chat targets, queued/retried/parent-linked requests, detached clinical tool views, dependency-based lazy hydration and global-language forms/messages now have candidate integration. The frozen combined candidate passed **3,726 tests / 2 skips**, four subtests, in 392.98 seconds. See `INTRAOPERATIVE_TARGET_LANGUAGE_VERIFICATION_2026-10-11.md` for root causes, exact evidence and the narrower scope of this result. Noncurrent mutation confirmation and the production four-panel/HTTP/resource/Monitor bridges remain unfinished; do not enable the UI gate from this test result.

This audit distinguishes an implemented candidate, synthetic validation, actual product integration and operational evidence. It must not be read as a statement that the current web page already supports the complete new workflow.

## 1. Scope and locations

- Authoritative LAN checkout: `/home/lht/snap/brachyplan/BrachyBot`.
- Separate public checkout: `/home/lht/snap/brachyplan/BrachyBot-release`; untouched by this work.
- Candidate source: `C:/Users/hunte/OneDrive/Dokumen/ssh/timepoints-implementation-20261010`.
- Remote test checkout: `/tmp/brachybot-timepoints-stage-20261010-E1Rvjz/checkout`.
- Private checkpoint: `/home/lht/.local/share/brachybot-intraoperative-development/20261010-E1Rvjz`.
- Pinned supplied model bundle: `/home/lht/.local/share/brachybot-intraoperative-development/seedfinder-bdb0db1202f3`.

No commit, push, patient migration, live product deployment or server restart is part of this verification. The existing dirty working tree is the delivery baseline, not a clean Git HEAD that may discard earlier work.

## 2. Defects found by checking composition rather than isolated helpers

1. The earlier continuation engine had not been threaded into the main pipeline. Rule/RL fallback, coverage reconstruction, coverage repair and late safety pruning could still lose the fixed baseline. These candidate paths now use the typed baseline; total dose is rebuilt once from fixed plus supplemental contributions.
2. The legacy intraoperative orchestrator required equal counts, borrowed preoperative axes/anatomy and removed covered CTV before zero-based optimization. It has been replaced by a current-image, reviewed-baseline main-pipeline call. Compatibility arguments are not acceptance evidence.
3. A prior candidate changed the historical normalized `dose_distribution_gy` alias to true Gy, although readers still scaled that alias. The alias now remains normalized; true Gy is published as `dose_distribution_physical_gy`. The exporter/evaluator conversion boundary is not inferred from value magnitude.
4. Continuous/serialized candidate depths can be floats. The old `range()` path crashed during refinement. Bounded sampling now accepts them while preserving integer behavior and not extending beyond the distal target interval.
5. Several coverage calculations used strict `>` while reported V100 used `>=`. Active continuation/rule/RL/repair comparisons now include equality; exact-threshold tests protect the convention.
6. Byte-identical physical CT under equivalent axis reordering could appear changed. Captured image content signatures now canonicalize to the product's LPI axis layout, while still rejecting different CT voxel content on the same frame/grid.
7. A captured target revision alone did not fence a source guide/preoperative change. A typed execution read-set is checked again within the SQLite publication transaction. Rename/display-only changes do not invalidate a nonlegacy clinical job; source clinical edits and delete/restore lifecycle changes do.
8. Partial nested appearance patches could erase siblings. Timepoint presentation patches now recursively retain unrelated color/opacity/camera fields; explicitly supplied arrays, including empty annotation arrays, replace their own field.
9. New guide read actions were not admitted consistently by authorization, hydration and analysis coercion. Manifest/validation are read-only; placement estimation requires a scoped operation grant. An analysis call cannot become generation.
10. Numerical success previously implied visible 3D output in the formatter. It now reports saved computation separately from Viewer loading and does not fabricate a score when absent.
11. A scoped tool result could be copied into default workspace aliases by post-processing. The named-timepoint dispatch and store/validation guards now keep its clinical publication separate from the shared conversation.
12. A newly bound reconstruction action was still subject to the old automatic mounted-image injector. Reconstruct/get/review now retain their captured input contract; only legacy threshold detection receives the mounted CT. Tests exercise the actual agent injection method.
13. Zero-addition paths could skip source/checkpoint drift validation because they did not need new inference. The saved source-strength/calibration/time contract has an immutable binding signature, and drift now invalidates a baseline before either zero- or nonzero-addition use.
14. Simply adding `timepoint_id` to an event does not make an old Session-only Viewer callback safe. Cross-timepoint previews now require an explicitly scope-aware consumer; shared trace callbacks retain their existing signature, but an unmounted/default scene cannot receive another timepoint's geometry by accident.

## 3. User-added branches implemented in candidate code

### 3.1 Existing dose is sufficient

The branch evaluates the **complete** target against the configured physical prescription after exactly one model-unit conversion. If the configured coverage goal is reached, it returns zero supplemental sources without loading the trained model for unnecessary additional inference. Dose interpolation/evaluation and a valid scoped Planning publication still run.

Existing OAR dose and hotspots remain separate. A coverage-sufficient baseline with an exceeded optimization objective is returned as such; the program neither removes implanted seeds nor declares all objectives satisfied. Generic optimization objectives are not source-backed clinical tolerance limits.

### 3.2 Guide channels are insufficient

Ordering is explicit:

1. Initialize only the reviewed, realized and currently feasible guide-channel inventory.
2. Optimize/repair within those channels, retaining the fixed implanted baseline.
3. If coverage remains below the goal, preserve the first-phase choices and search outside the positioned guide.
4. Project guide material conservatively as a hard planning obstacle, then independently test the full physical external-to-tip segment against the actual mesh and needle-radius clearance.
5. Check current CT skin-entry/FOV, non-traversable OAR, fixed seeds/in-situ needles and selected-needle spacing. Append only accepted additional contributions.
6. Recheck final geometry after canonical needle reconstruction. A changed final segment cannot bypass the guide obstacle merely because its initial proxy was safe.

The second phase uses bounded existing coverage-repair machinery and explicit candidate records. It does not reprint a guide, deform a guide, move a fixed implant, erase already covered CTV or silently extend a path beyond a manufactured channel.

No safe exterior path means an explicit undercoverage result with the accepted first-phase plan retained. No accepted supplemental seed at all means failure, not an empty completed plan. Timeout retains the previous accepted partial solution.

The default `GuideFirstPolicy` reflects the user's new explicit authorization. Older records without a reviewed guide obstacle remain guide-only until prepared. If a source guide exists but its pose is not reviewed, additional planning is blocked; evaluating existing dose is separate. A missing obstacle cannot authorize freehand search.

### 3.3 Source/time basis

The CNN is still the dose engine. `ContinuationPreparationService` composes reviewed detections, original-image identity, source dimensions, a pinned CNN checkpoint/calibration and realized bore trajectories into durable baseline state. It does not replace the CNN with TG-43 or Monte Carlo.

Its current supported basis is **projected total source dose**, not elapsed dose already physically delivered by the scan time. Source model/strength/calibration/time provenance must be supplied and reviewed. A profile is not invented from a tumor label or a default dose threshold. Model/source changes and observation corrections invalidate old baseline authority.

## 4. Acceptance matrix against the approved plan

Legend: **synthetic** means executed synthetic contract tests, not independent clinical or real-browser commissioning. **partial** means some code/tests exist but the complete requested path is not proven. **pending** means the required product behavior is not yet implemented/verified.

| ID | Plan requirement | Current evidence and remaining gap |
|---|---|---|
| T01 | Restore legacy chat/report/appearance/geometry without replan | Partial: live schema-1 projection and old-store tests; no real multi-panel migration/browser acceptance. |
| T02 | Interrupted migration remains idempotent | Partial: catalog publication fault injection; real migration/default detachment is pending. |
| T03 | Same names/IDs in A and B stay scoped | Synthetic storage/execution tests; actual multi-image scene focus and exports pending. |
| T04 | A completes while B is selected | Synthetic detached target commits and controller fences; production late-loader/scene test pending. |
| T05 | Concurrent timepoint checkpoints both survive | Synthetic multi-store CAS and source-read-set tests pass. |
| T06 | Two browser tabs with different timepoints | Partial: ownership/CAS/controller tests; real leases/browser concurrency integration pending. |
| T07 | Bright appearance restores before/after meshes | Candidate: cyan observed/gold planned roles, persistent item/group appearance and actual headless THREE interaction; deployed resource/mesh recovery remains pending. |
| T08 | Hiding an implant does not remove dose | Candidate: independent per-source 2D/3D controls; dose source set excludes rejected observations, not hidden objects. Real product acceptance remains pending. |
| T09 | Intraoperative stage requires a source | Synthetic backend/catalog/controller negative controls. |
| T10 | Rename retains source identity | Synthetic catalog/read-set tests. |
| T11 | Actual count may differ from preop | Synthetic reconstruction service ignores preop count and old equal-count orchestration is removed. Real inference pending. |
| T12 | Sparse axes are not fabricated | Synthetic provider/review gates. Supplied singleton fallback remains explicitly estimated evidence. |
| T13 | Oblique/anisotropic physical axes | Partial: independent physical 3D provider tests; supplied default direction routine forces Z=0. That limitation is preserved and review-gated, not called validated 3D accuracy. |
| T14 | Close/crossing/migrated groups | Synthetic independent estimator tests; real supplied-model error analysis pending. |
| T15 | Touching components and centers | Synthetic adapter associations; real native detector validation pending. |
| T16 | Zero vs failed/partial scans | Partial: synthetic DTO/review gates. Supplied zero-detection missing-STL edge case still needs a real inference-path resolution. |
| T17 | Reobserved seeds across scans counted once | Pending: physical cross-scan association and ambiguity ledger. Per-observation IDs are not proof of physical identity. |
| T18 | Frame metadata is not registration evidence | Synthetic pose/current-image validation; real registration workflow pending. |
| T19 | Proper rigid guide placement only | Synthetic SE(3), mesh/manifest and scoped candidate tests. Human-review UI pending. |
| T20 | Ambiguous/symmetric pose not auto-accepted | Synthetic surface-fit/review gates; real guide-visible evidence pending. |
| T21 | Absent final STL holes never become candidates | Synthetic final-bore auditing and manifest wrapper tests. Printed-guide tests pending. |
| T22 | Changed anatomy rejects unsafe old bores | Synthetic current-anatomy/path checks; production candidate visualization pending. |
| T23 | Refine/repair cannot leave bore unnoticed | Synthetic exact candidate guards and guide-first phase restriction; exterior paths are allowed only by the new second-phase policy and hard obstacle. |
| T24 | Baseline retained once, zero/known additions | Synthetic actual main-pipeline, real repair, dose and publication tests. |
| T25 | RL/reset/fallback/repair all retain baseline | Synthetic engine plus main-rule/RL/fallback and repair tests. No real trained-model optimization validation. |
| T26 | Interference with fixed implants/needles | Synthetic physical capsules and final-segment guards. Actual in-situ acquisition/review pending. |
| T27 | Existing violations are not falsely repaired | Synthetic baseline-sufficient/OAR-excess test; source-backed clinical limits remain unapproved. |
| T28 | Legacy dose alias cannot cause double scaling | Synthetic producer/reader/export convention tests; ambiguous historical clinical records still require provenance review. |
| T29 | Non-default calibration/Rx preserved | Synthetic 37-Gy/model-unit examples and checkpoint binding; real source commissioning pending. |
| T30 | Observation correction invalidates dependencies | Candidate: immutable center/exclusion/addition revisions, cleared estimated axes, stale dose/profile markers and publication fences; complete Monitor/report/artifact invalidation graph remains pending. |
| T31 | Crash between artifact and metadata commit | Synthetic fault injection for store and implant journal. No power-cut/filesystem qualification. |
| T32 | Restart/resume twice does not duplicate publication | Partial: implant request/revision idempotency. Durable whole-workflow job ledger and interrupted GPU/RL resume pending. |
| T33 | Delete/restore dependency policy | Synthetic nonlegacy lifecycle/CAS; default deletion remains gated pending safe detachment. |
| T34 | Session archive/export/import whole graph | Pending graph remap and explicit export/retention registration. A directory copy alone is not sufficient. |
| T35 | Late empty saves do not erase appearance | Synthetic recursive merge and previous restore regressions; production mounted-panel restore bridge pending. |
| T36 | Only recompute intraoperative dose | Candidate: `dose_recompute(source_set='implanted')` uses only included current observations, saves separate physical Gy, preserves future plan aliases and performs no guide/report/planning action. Dedicated production heatmap/DVH selector and remaining API adapters are unfinished. |
| T37 | Reuse named printed guide while another tab active | Partial: source/target/version service and read-set; operational accepted-guide execution/browser flow pending. |
| T38 | Compare scans without adding their doses | Pending comparability/registration service and user-facing report. |
| T39 | Undo surgery vs undo software plan | Pending new multi-timepoint conversational/Monitor scenarios. |
| T40 | Changed provider/profile invalidates cache | Partial: detector pins, observation/source/checkpoint binding; whole-stage recovery graph pending. |
| T41 | Existing dose reaches coverage goal | Synthetic full pipeline with zero additions, OAR evaluation and current-run publication. |
| T42 | Guide-first then safe external alternatives | Synthetic hard mesh, thin-wall/radius, real repair, empty inventory, timeout and final-reconstruction controls. |

## 5. Evidence scope

The following results are historical checkpoints, not additive totals:

- Earlier combined plan review: 598 passed across 20 selected files, including the existing guide reference suite before the final scoped/search changes.
- Scoped tool policy/wrapper regressions: 212 passed.
- Implant service plus coordinate contract: 41 passed; worker reconstruction/adapter/coordinate joint suite: 127 passed.
- Scoped numerical integration before final guide-requirement change: 493 passed.
- Latest dedicated guide-first main-pipeline/preparation batch: 45 passed before the subsequent registered scoped-executor additions.
- Registered scoped-executor contracts: 6 passed.
- Real-repair guide-first file: 21 passed.
- Final dedicated new-branch/preparation/scoped-execution batch: 53 passed in 4.76 seconds.

The first unfiltered product run completed: **6 failed / 3,638 passed / 19 skipped**, with four passing subtests, in 442.18 seconds. Those failures were investigated rather than hidden by selection:

- Two failures were real omission of `timepointAdd/timepointManage` from source-bound UI help coverage. Added bilingual, source-anchored cards that preserve disabled/unobserved availability and migration limits.
- One AST-extracted latency-wrapper test lacked the new `continuation_kwargs` closure. Its fixture now tests both ordinary and continuation forwarding without relaxing elapsed-time assertions.
- Two browser theme tests placed the Viewer as a fixed window-filling overlay in their synthetic fixture, so the separate tab bar intercepted clicks after the new strip changed its height. The fixture now uses the actual product layout/timepoint styles and normal panel activation. No force-click, hidden tab bar or product pointer-event bypass was used.
- One Node-based Monitor test used `shutil.which('node')`; the test-process PATH did not include the bundled runtime. The rerun explicitly prepends the known Node directory. This was an environment issue, not a product-language failure.

The focused five-file follow-up passed 84 tests and exposed one incorrect new documentation function anchor (`createTimepoint`); the anchor was corrected to the actual `editTimepoint` handler. A new test protects both known controls and their non-authorization/unobserved-availability status. The next unfiltered run reached 3,662 passed, with one failure in that new test's field name: the established compact API uses `limits_and_exit`, not `caution`. Correcting the assertion did not change product behavior.

The following complete unfiltered run passed: **3,664 passed / 2 skipped**, four passing subtests, 31 deprecation warnings, in 382.71 seconds. Evidence: `full-root-regression-verified-tests.xml`. This is before the last incremental source-binding/agent-injection/preview guards. Their respective targeted batches passed 57, 121 and 28 tests (overlapping). A final unfiltered run against those frozen final guards is now in progress; its result is recorded below only when complete.

**Final frozen candidate result:** the complete unfiltered `tests/` run finished with **3,671 passed / 2 skipped / 0 failures / 0 collection errors**, plus four passing subtests and 31 existing deprecation warnings, in **388.57 seconds**. Evidence: `full-root-current-final-tests.xml`. The skip conditions remain explicit; this result must not be converted into a claim of patient/model/GPU/clinical/printing acceptance. No benchmark experiment was run. No product code was changed after this final run started.

The two skips are existing real public-origin/proxy checks: `tests.test_public_http.test_real_public_origin` requires `deploy/public/requirements.txt`, and `tests.test_public_proxy.test_nginx_template_tls_headers_and_unbuffered_sse` requires `NGINX_TEST_BINARY`. They are not waived release validations.

These overlap. The final combined run and its exact evidence path must be recorded below after completion. No claim of a full unfiltered suite is made from these selected batches.

The raw pytest summary is the pass-count authority. JUnit includes the four subtests in its test-case accounting, so subtracting XML failures/skips without accounting for subtests would produce a different apparent pass total.

Final paired guide evidence: `docs/benchmarks/surgical_guide_dependency_renewal_2026-10-10-verified-final.json`; SHA-256 `00dd9bd8e3a10af97c306fce9083af889db0f2a19e22ee5f931fc72dfff5d336`. It binds pipeline SHA-256 `97d56ecd1815bd37f8a0d4f408e22e08187d7f19ba110a9322cf125b8e8cf117`. Four geometry/QA-matching pairs measured pre/post seconds of 22.386/22.999, 21.680/22.888, 8.074/8.157 and 7.913/7.919. They are descriptive synthetic observations, not p50/p95 or clinical performance evidence.

Packaging verification: 70 candidate files, comprising 31 changed pre-existing files and 39 new files. Local/isolated hashes match, all candidate Python files compile, the three modified frontend JavaScript files pass syntax checks, and the final paired guide dependency guard passes. Product files are not deployed. Existing source-before archives remain retained, with the extra pre-change regression fixture preserved in `extra-source-before-v2.tar`.

SeedFinder runtime: all three source hashes and the 108,243,082-byte checkpoint matched. Actual required modules and the supplied entry module imported in the existing remote environment: Torch 2.6.0+cu124, MONAI 1.5.0, VTK 9.4.2, scikit-learn 1.6.1, SimpleITK 2.5.0, NumPy 2.4.6, SciPy 1.15.3. No model was deserialized and no inference was run. This is not a dependency-upgrade/security-release clearance.

Paired guide dependency replays use fresh subprocesses with alternating order. The canonical guide helper remains unchanged; geometry/QA hashes match in four pairs. That renews dependency equivalence only, not a guide-generation speedup or mechanical validation. Earlier intermediate evidence that no longer binds the final pipeline hash is retained as historical evidence, never used as the final guard.

## 6. Mandatory remaining engineering

1. Register a **production** frontend restoration bridge for all four panels, resource URLs and generation fences. Current `execution_scope=False` remains deliberate; `explicit_pipeline_tool=True` is a narrower backend capability, not permission to flip the UI gate.
   The legacy default source still uses its Session-level revision for fencing. A shared chat/UI save can conservatively invalidate a job that reads that default source. Default detachment and a true clinical-generation boundary must remove that coupling before enabling the general workflow; tests of nonlegacy clinical/presentation separation do not resolve it.
2. Scope uploads, uploaded-mask promotion, CTV/OAR models, manual edits, dose/report/export endpoints, Monitor, screenshots, resource caches and task cleanup. Explicit numerical pipeline scope does not cover those APIs.
3. Implement image collections/planning-reference selection and corresponding Data Tree parentage/exclusive MPR backgrounds without hiding unrelated clinical overlays.
4. Integrate the now-implemented implanted mesh/MPR presentation and per-object/group controls with the production recovery bridge, including dedicated implanted-dose source selection. Candidate tests cover vivid colors, language, unknown-axis glyphs, correction drafts and late-target fences; real resource/browser acceptance is still required.
5. Add authenticated human-review UI/routes for observations, source contract and guide placement; compose their artifact/invalidation receipts into the authoritative timepoint graph.
6. Complete anatomy registration and guide-visible/direct-placement workflow; never derive printed-guide rigid authority from a deformation field alone.
7. Complete durable workflow job recovery, restart reconciliation, source changes, physical seed association across scans and idempotent stage re-entry.
8. Complete default-timepoint detachment/deletion, complete archive/export/import ID graph remap, retention and per-account quota transactions for new journals/artifacts.
9. Run bounded real supplied-model/phantom/browser acceptance after the contracts above are integrated. Independent direction, print/strength and dosimetry evidence remain operational gates, not claims that passing code tests can establish.

The complete feature is **not finished**. Candidate foundations and numerical composition have advanced; live product enablement must wait for the missing runtime/UI/persistence paths rather than exposing a partly isolated clinical workflow.
