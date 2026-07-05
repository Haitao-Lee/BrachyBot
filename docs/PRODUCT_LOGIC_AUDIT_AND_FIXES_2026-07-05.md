# Product Logic Audit and Fixes - 2026-07-05

## Scope

This pass re-audited the latest `main` implementation with emphasis on:

- agent routing and review behavior;
- execution graph dependency ordering;
- plan review, fact checking, and safety advisory logic;
- manual/automatic dose visualization consistency;
- clinical-threshold provenance;
- frontend dose display and 3D/2D dose metadata.

Coordinate transforms for CT, masks, seeds, needles, and dose overlays were intentionally left unchanged.

## Confirmed Issues and Fixes

### 1. Case executor dependency ordering

**Issue:** `CaseExecutor.resolve_execution_order()` only used MedAgent-Pro `input_type` references and could ignore generic `dependencies` declarations. This could silently mis-order custom graph steps.

**Fix:** Dependency resolution now reads both `input_type` and `dependencies`, including `dependencies: [0]` references. Execution input collection uses the same helper, so ordering and runtime inputs stay consistent.

### 2. Dose-evaluation routing

**Issue:** Some user requests about dose distribution, DVH, and isodose review could be routed as generic planning because the router matched planning keywords first.

**Fix:** Added explicit dose-evaluation markers and an early routing path for DVH/dose/isodose queries before broad planning matches.

### 3. Advisory plan review coverage

**Issue:** Plan review and safety review avoided hardcoded clinical pass/fail thresholds, which is correct, but they also under-reported obvious dose-distribution anomalies when no source-backed thresholds were available.

**Fix:** Added deterministic advisory checks for clearly poor V100/D90/V150/V200/max-dose patterns. These are labeled as advisory sanity concerns, not clinical guideline thresholds. Formal approval still requires `clinical_kb` or explicit `plan_config` limits.

### 4. Fact-check hallucination penalty

**Issue:** Outputs containing fabricated-study patterns could remain too close to a clean pass.

**Fix:** Deterministic hallucination flags now carry stronger penalties and force conditional/reject decisions depending on severity.

### 5. Web-search quality gate path

**Issue:** `SafetyGuardian` could run on medical web-search results and emit irrelevant missing-plan concerns.

**Fix:** Web search quality review now relies on the fact-checker path; plan safety review is reserved for plan-like outputs.

### 6. Comprehensive dose scoring provenance

**Issue:** `comprehensive_dose_evaluation` duplicated local target/OAR threshold tables and included generic OAR violation heuristics that were not explicitly source-backed.

**Fix:** Removed duplicate threshold tables and connected scoring to `tool_factory.plan_quality.clinical_standards`, the curated source-backed mirror of `clinical_kb`. OAR violations are now evaluated only when a matched clinical standard exists.

### 7. Dose unit ambiguity

**Issue:** Several endpoints exposed normalized myDoseNet outputs through the legacy key `dose_distribution_gy`, making downstream code and UI text easy to misread as physical Gy.

**Fix:** Kept legacy keys for compatibility, but added explicit metadata:

- `dose_units: "normalized_model_output"`
- `dose_scale_gy: 120.0`
- manual preview `dose_range_normalized`
- manual preview `dose_range_gy`

Automatic and manual dose paths now store the unit metadata in agent memory.

### 8. Frontend dose display consistency

**Issue:** The step-result UI displayed normalized dose ranges as `Gy`. 3D isosurface data-tree percentages compared a Gy threshold against a normalized max dose.

**Fix:** The frontend now converts normalized ranges to Gy for display and computes isosurface percentages using `dose_scale_gy`.

### 9. Slice index boundary handling

**Issue:** Dose overlay and contour endpoints accepted negative slice indices, allowing Python negative indexing to show an unintended end slice.

**Fix:** Dose overlay and contour slice indices are clamped to valid `[0, max]` bounds for axial/coronal/sagittal axes.

### 10. Quality Gate display polish

**Issue:** Quality Gate summaries could show duplicated semantically equivalent concerns and legacy mojibake status markers in logs/UI text.

**Fix:** The final-message formatter now uses ASCII status labels, stable ordered de-duplication, and ASCII bullets. This only changes display text; advisory review decisions and scores are unchanged.

## Validation

Passed:

- `python -m compileall -q .`
- `python tests/test_multi_agent_basic.py`
- `python tests/test_multi_agent_phase2.py`
- `python tests/test_multi_agent_phase3.py`
- `python -m unittest tests.test_brain_system.TestBrainSystem.test_case_executor_ordering -v`
- direct smoke test for `ComprehensiveDoseEvaluationTool`
- frontend inline JavaScript syntax parse via Node `vm.Script`
- `git diff --check`

Known local-environment limitation:

- `python -m unittest discover -s tests -v` ran 13 tests; 9 passed and 4 failed only because this local bundled Python does not include `SimpleITK`, which is required to import `AgenticSys.py`.

## Product Status After This Pass

The current implementation has the expected product-level paths in place:

- automatic planning with CTV/OAR segmentation, trajectory planning, seed planning, dose/DVH, screenshots, report generation, and quality review;
- manual planning controls with manual needles/seeds, AI-dose recomputation, DVH refresh, and report compatibility;
- UI-state bridge and UI controller tools for agent-side observation and manipulation of Web UI controls;
- training/monitor mode with event capture, deterministic feedback, screenshot suggestions, and final summary support;
- source-aware clinical knowledge usage through `clinical_kb` and `clinical_standards`;
- developer capabilities preserved behind explicit trusted-local environment toggles.

Remaining validation that should be done on the clinical workstation:

- run full integration tests in the `brachytherapy` environment with `SimpleITK`, `nnUNet`, model weights, and GPU dependencies available;
- perform one full pancreas CT planning run through Web UI and confirm CT/mask/dose/seed/needle alignment visually in all three 2D viewers plus 3D;
- export one final report and verify screenshots, legends, dose colorbar, and OAR naming on the generated artifact.
