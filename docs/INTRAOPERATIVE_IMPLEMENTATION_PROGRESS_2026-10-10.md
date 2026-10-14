# Intraoperative refactor implementation checkpoint

Date: 2026-10-10 (Asia/Shanghai).

2026-10-11 implanted-observation follow-up: continuous detect/reconstruct consumption, per-source Data Tree/2D/3D appearance, exclusion/restoration, 2D placement plus 3D draft refinement, source confirmation and natural-language source-only CNN recomputation are now implemented in the **isolated candidate**. The default saved-state path publishes an encoded numerical delta, not a full stale Agent. See `INTRAOPERATIVE_IMPLANT_INTERACTION_VERIFICATION_2026-10-11.md` for current evidence and exact boundaries. This supersedes the older claim that no implanted renderer exists, but does not enable the production four-panel restoration bridge or complete the entire refactor. Product code remains undeployed.

Latest implanted-observation checkpoint: **101 candidate files; 3,765 passed / 2 skipped / 0 failures / 0 collection errors**, four passing subtests, 31 deprecation warnings, **407.47 seconds**. The new focused suite passed **73 tests** in 13.93 seconds. All 80 changed/new Python files compiled; all 10 changed JavaScript files passed syntax checks. Stage hashes match; the live baseline's 45 before hashes have no drift and none of the 56 new candidate paths is already deployed. Exact evidence and remaining gates are in `INTRAOPERATIVE_IMPLANT_INTERACTION_VERIFICATION_2026-10-11.md`.

Earlier scope/language checkpoint (historical): 2026-10-11, 85 changed/new files; unfiltered `tests/` **3,726 passed / 2 skipped**, four passing subtests, 31 warnings, 392.98 seconds. See `INTRAOPERATIVE_TARGET_LANGUAGE_VERIFICATION_2026-10-11.md`. These historical counts are not the current candidate total, and overlapping runs must not be added.

Status: implementation in progress in an isolated development checkout. Main-pipeline continuation and the user's guide-first/outside-guide branches now have numerical and scoped-service integration. This is not a completed product release, a live migration, or a clinical/manufacturing validation. See `work/PLAN_VERIFICATION_2026-10-10.md` for the updated 42-scenario evidence matrix and remaining product gaps.

## Locations

- Authoritative unchanged product checkout: `/home/lht/snap/brachyplan/BrachyBot`.
- Local candidate source: `C:/Users/hunte/OneDrive/Dokumen/ssh/timepoints-implementation-20261010`.
- Isolated test source: `/tmp/brachybot-timepoints-stage-20261010-E1Rvjz/checkout`.
- Private persistent checkpoint: `/home/lht/.local/share/brachybot-intraoperative-development/20261010-E1Rvjz`.
- Design: `docs/INTRAOPERATIVE_MULTI_TIMEPOINT_EXECUTION_PLAN_2026-10-10.md` in the authoritative checkout.

## Implemented candidate code

1. A SQLite-published timepoint catalog with stable identities, stage/source association, typed compare-and-swap revisions, sequence-cycle checks, owned queries, dependency-aware recoverable deletion and restoration. The legacy default is a live schema-1 projection rather than a destructive migration.
2. Immutable per-timepoint workspace states and numerical sidecars; shared conversation preservation; hash-verified state loading; retained array references across inactive, historical and recoverably deleted timepoints. Separate clinical and presentation revisions prevent a display-only edit from invalidating an otherwise current clinical result.
3. Explicit metadata/state routes with authentication, CSRF, lease and request-identity checks. Runtime routing is fail-closed for new timepoints until all execution entrypoints have been scoped.
4. A bound read-only `timepoint_inspector` tool for Session-wide catalog and saved-state discovery. It does not claim to recompute or independently verify dose freshness.
5. Three-dimensional local PCA and robust deposition-prior reconstruction, typed immutable observations and review revisions, vivid role-color metadata, original-grid reconstruction, and a thin hash-pinned SeedFinder adapter.
6. Updated SeedFinder format support after the user's direction-code update: native mask/CSV/Markups/STL replace the former source-CT/mask/CSV/Markups output. Original CT is read from the captured owned input and its hash is rechecked. The adapter defaults to the supplied direction routine for the updated contract and records its XY-plane restriction and singleton/global fallback as estimated evidence. It does not silently substitute the independent 3D estimator.
7. Actual rule, RL, candidate-construction, consolidation and coverage-repair code accepts a protected nonzero continuation baseline, fixed implant geometry and bounded candidate paths. Standalone seed-planning tools can forward the baseline and return total-dose metadata.
8. The legacy intraoperative Gy alias assignment is corrected in candidate code and covered by an extended producer regression.
9. Proper rigid guide placement, final STL bore auditing, realized versus skipped/unverified bore manifests, constrained current-CT trajectory initialization, and an explicit denser preoperative layout. Existing 5 mm truncation and wall constraints remain unchanged. A printed guide is never redesigned by its placement operation.
10. A timepoint-strip frontend controller, scoped request/presentation hooks, localized dialogs/styles and synthetic browser contracts. A production recovery bridge is not registered, and runtime capabilities remain gated.
11. Main `planning_pipeline.py` rule/RL/fallback/repair/safety-pruning paths now preserve the nonzero fixed dose, complete target, fixed-implant collision locks and explicit source/checkpoint binding. Typed numerical baseline records survive sidecar encoding and revalidation.
12. Zero-addition coverage-sufficient handling, and bounded guide-first/outside-guide continuation with a closed rigid guide-material obstacle, conservative planning projection, physical-radius full-segment validation, first-phase retention and final-geometry rechecking. No-safe-path and timeout outcomes remain explicit.
13. Actual supplied-detector service and surgical-guide wrapper actions for durable reconstruction/review, realized-hole metadata and scoped placement candidates. Human review and clinical/source approval are not inferred from tool JSON.
14. Detached, named-timepoint pipeline execution through the registered planning tool. Target/source read-sets are rechecked within SQLite publication. Shared chat is preserved and default-memory post-processing cannot overwrite it with another timepoint's clinical aliases.

## Validation evidence so far

All data in these tests is synthetic. No patient/GPU/model-inference experiment was run.

| Evidence file under the isolated stage root | Result | Scope and limitation |
|---|---|---|
| `storage-tests.xml` | 100 passed | New storage/routes plus existing store/auth tests, before the later clinical/presentation revision refinement. |
| `combined-core-tests.xml` | 319 passed | Storage, inspector, round-6 regressions, reconstruction/adapter and continuation tests; not production runtime integration. |
| `new-feature-contracts.xml` | 204 passed | Refined storage and new reconstruction, continuation and guide contracts. |
| `updated-seedfinder-tests.xml` | 85 passed | Updated output format, native direction reuse, unchanged-center and negative controls plus reconstruction. |
| `integration-regressions.xml` | 256 passed | Synthetic real-browser timepoint controller, refined storage/auth/inspector, round-6 and existing guide regressions. |

These are overlapping suites; their counts must not be added to claim a larger unique test total. Existing SimpleITK/SWIG deprecation warnings were observed.

Updated final evidence: the complete unfiltered product `tests/` suite on the frozen current candidate passed **3,671 tests**, with **2 skips**, **4 passing subtests**, **31 deprecation warnings**, **0 failures** and **0 collection errors**, in **388.57 seconds**. The initial full run had six failures; missing control documentation, an AST fixture, synthetic browser-layout assumptions and a Node PATH issue were repaired and rechecked. Subsequent source/calibration drift, captured detector input and unscoped preview boundaries are covered in the final run. Evidence: `full-root-current-final-tests.xml`. This is software contract evidence, not real-model/patient/browser workflow or clinical approval.

An initial round-6 run had one infrastructure failure because the isolated checkout lacked the benchmark report-generator support path. Read-only tracked support code was copied into the isolated checkout; the later combined/integration suites passed. No benchmark evaluation was run.

Two parallel workers terminated because of account usage limits. Their written changes remain in the candidate checkpoint and were subsequently included in main-agent synthetic tests. Completed reconstruction and guide work was reviewed at its interface level. No failed worker status is treated as proof that a feature is complete.

## Updated supplied-code contract

- `test_single_ct.py`: `bdb0db1202f3cbca8e20c254f74aa8abb989adf687c78796fb59e16db173bfd0`.
- `seed_pipeline_deepdec_roi.py`: `1e04cd50170e000a2240011d5679097c624ce5af58ecb2019ff801716eb91dbf`.
- `autoencoder_inference.py`: `7a0d2a21391a14ff9115a10dd23d49d2068f3271b49da646da5f8f5cb07a287e`.
- Model: `561e905d06b5423273554a539ebc65e2fabaf484f1761d6311e17f38e7b6707b`.

The supplied package has not been edited. Its three scripts and model have also been copied, hash-verified and import-checked at `/home/lht/.local/share/brachybot-intraoperative-development/seedfinder-bdb0db1202f3`. No model was deserialized or inference executed, and live server environment was not changed. Its README still describes the older artifact roles. Its actual direction routine forces zero Z direction and supplies fallback axes for singletons. Directions are used for the STL but are not exported as direction columns in CSV or true seed orientation in Markups; the adapter records them explicitly by reusing the same pinned routine.

Additional upstream edge cases to resolve or document before a real inference smoke test: zero detections do not produce an STL in `generate_capsules_stl`, while the top-level script unconditionally renames that file; the generated visual geometry's cylinder and end spheres must not be assumed to certify source dimensions. No zero-detection output or STL dimensions are used to invent an accepted dose baseline.

## Mandatory next implementation steps

1. Extend the implemented captured `TimepointContext` and detached numerical executor to all runtime entrypoints, shared dialogue/control plane, agent caching, production hydration/callbacks and checkpoint dispatch. Separate legacy default clinical generations from chat/UI saves before enabling the general workflow.
2. Bind every existing API/UI executor, worker, Monitor operation, screenshot, report and artifact URL to its initiating target. Never enable the new frontend simply by changing `execution_scope` to true.
3. Build and test the complete production frontend recovery bridge: all four panels, image/background exclusivity, camera/appearance restore and late-loader fencing. The new implanted observation renderer/2D overlays and per-source controls now have candidate browser tests, but need integration with this bridge and real current-CT/browser acceptance. Synthetic tests do not establish deployed behavior.
4. Finish production binding/review UI and the durable stage state machine around the now-composed numerical services. The main pipeline has been updated; complete API/UI entrypoint scoping remains pending. Its guide dependency hash was renewed only with final paired evidence.
5. Validate the replacement of the old equal-count/preoperative-image/covered-target-removal orchestration in a bounded real-model/browser workflow. Synthetic current-image/main-pipeline tests are not operational acceptance.
6. Integrate Session archive/export/import and graph-ID remapping, crash/restart job recovery, interrupted-stage continuation and default-timepoint deletion/reclassification. The current default-protection gate is deliberate, not the requested final UX.
7. Complete performance review of final-bore QA. Default synthetic meshes were unchanged in the guide worker's paired observations, but the new audit added cost; old guide latency evidence does not cover it. Do not renew frozen hashes without paired review.
8. Run focused old/new integration suites, then bounded end-to-end browser/phantom/model smoke validation under reviewed parameters. Keep the live LAN/public deployments separate and do not interrupt active work.

## What remains deliberately disabled or unclaimed

- New-timepoint clinical execution and the production timepoint UI bridge.
- A claim that the current webpage can complete intraoperative planning end to end.
- Automatic acceptance of reconstructed seed axes, guide placement, source/time calibration or printing strength.
- Instruction-level interrupted GPU/RL resumption.
- Live product changes, server restart, migration of real Sessions, commit or push.
- Completion of the production panel bridge, actual implanted renderer, graph export/import and physical cross-scan seed association.

Use `work/checkpoint/manifest.json` and `candidate-changes.tar.gz` to verify/recover the candidate write set against the original source snapshot. Check the live hashes before any future integration; preserve pre-existing working-tree changes and perform a deliberate bounded delivery.

Current checkpoint has **70 candidate files** (31 pre-existing changed paths and 39 new paths). Local/remote candidate hashes, Python compilation, JavaScript syntax and the final paired guide reference guard were verified. The original extra-source archive is retained; `extra-source-before-v2.tar` adds the pre-change regression fixture needed for the updated test. No candidate product file has been deployed to the authoritative checkout.
