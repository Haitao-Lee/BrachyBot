# BrachyBot Benchmark v2 — Testing Guide

**Updated:** 2026-06-23
**Total:** 30 active categories, 475 cases (plus 32-case smoke subset)

## Purpose

This benchmark measures **BrachyBot's system capabilities** — not the LLM's
general knowledge. Each test has a specific setup state, clear pass/fail
criteria, and produces an actionable failure root cause when it fails.

## Test Material

- **CT File**: `/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii`
- **Patient**: Pancreatic cancer, 48 × 512 × 512 voxels, 0.68 × 0.68 × 5.0 mm
- **CTV Volume**: ~27,849 mm³ (after segmentation)
- **OAR Count**: ~57 organs (after segmentation)

> **Important**: the test CT is pancreatic. Test cases that ask about
> other organs (prostate, lung, etc.) are pure-knowledge queries and use
> setup `"No CT needed"`. The runner always loads the pancreatic CT
> regardless of the organ mentioned in the question.

## Layout

```
benchmarks/v2/
├── README.md                  ← this file
├── *.json                     ← 27 active category files (01-27, see below)
├── _legacy/                   ← v1-of-v2 files, kept for reference, not run
├── smoke/                     ← 32-case fast-feedback subset (T3.2)
└── baseline.json              ← last-run scores per category (T2.5)

benchmarks/aligned_benchmark.py  ← runner
```

## Why `_legacy/` exists (T1.1)

Originally each of cat_nums 01-08 had **two** files (an "original" and a
"v2-refresh" version). The runner's `glob(f"{cat_num:02d}_*.json")[0]`
silently picked the alphabetically first file — meaning the second file
**was never executed** (77 cases lost).

The 8 "second" files were the **v1-of-v2** drafts that were later
superseded by the v2-refresh files in cat_nums 11-16:

| cat_num | ran (alphabetically first) | lost in `_legacy/` (v1-of-v2) | superset in 11-16 |
|---|---|---|---|
| 01 | `01_ct_analysis.json` (15) | `01_tool_calling.json` (15) | tool routing not re-covered |
| 02 | `02_ctv_segmentation.json` (10) | `02_multi_step.json` (5) | — |
| 03 | `03_hallucination.json` (11) | `03_oar_segmentation.json` (10) | 11_hallucination (15) |
| 04 | `04_dose_engine.json` (8) | `04_language.json` (6) | 12_language (15) |
| 05 | `05_context.json` (7) | `05_treatment_planning.json` (8) | 13_context (10) |
| 06 | `06_dose_evaluation.json` (8) | `06_response_quality.json` (5) | 14_response_quality (10) |
| 07 | `07_safety.json` (5) | `07_ui_control.json` (20) | 15_safety (10) |
| 08 | `08_error_recovery.json` (6) | `08_output_tools.json` (8) | 16_error_recovery (10) |

The 8 v1-of-v2 files were moved to `_legacy/` on 2026-06-13:

```
v2/_legacy/
├── 01_tool_calling.json
├── 02_multi_step.json
├── 03_oar_segmentation.json
├── 04_language.json
├── 05_treatment_planning.json
├── 06_response_quality.json
├── 07_ui_control.json
└── 08_output_tools.json
```

**They are not deleted because:**
1. They are useful as a reference for what v1-of-v2 design tried to test
2. Some content is unique (e.g. `07_ui_control.json` has 20 UI tests not
   duplicated anywhere in 11-16)
3. Future "import from legacy" requests are cheap to handle

**They are not run because:**
1. The runner's glob would still find them in `_legacy/` only if someone
   passes `cat_num=99` or extends the runner — currently it does not
2. The 11-16 superset has equivalent or richer coverage
3. Avoids the silent-skip bug from recurring

## Setup Language (used by `_parse_setup`)

The `setup` field in each test case is parsed by `aligned_benchmark.py` into
an ordered list of pipeline steps. The runner supports these patterns:

| Setup pattern | Steps performed |
|---|---|
| `""` (empty) | nothing |
| `"No CT needed"` | nothing |
| `"Upload CT"` | CT upload |
| `"Upload CT only, NO segmentation"` | CT upload (no seg) |
| `"Upload CT + segmentation"` | CT, segmentation |
| `"Upload CT + segmentation, NO plan generated"` | CT, seg, NO plan |
| `"Upload CT + segmentation + plan"` | CT, seg, plan |
| `"Upload CT + segmentation + plan, NO dose"` | CT, seg, plan, NO dose |
| `"Upload CT + full pipeline"` | CT, seg, plan, dose (no eval) |
| `"Upload CT + segmentation + plan + dose evaluation"` | CT, seg, plan, dose, eval |
| `"Upload CT: ui_state.ct_path=..."` | CT only (ui_state hint stripped) |

Complications handled: `seed planning`, `treatment plan`, `plan with violations`,
`two plans`, `recalcul(ate)`, `evaluate the dose`. Multi-turn tests have
`turns: [{input, setup, expected_keywords}]`; the runner lifts turn-level
setup to the case level for the first turn.

## How to Run

```bash
# Single category (recommended for iteration)
python3 benchmarks/aligned_benchmark.py 1 7

# Multiple categories
python3 benchmarks/aligned_benchmark.py 1 7 8 11 12

# Smoke subset (fast feedback for PRs)
python3 benchmarks/aligned_benchmark.py 1 99    # cat_num 99 = smoke

# All 30 categories
python3 benchmarks/aligned_benchmark.py 1 $(seq 1 30 | tr '\n' ' ')
```

After each run, the runner writes:
- `docs/benchmark_result/screenshots_v2/{cat}_{case_id}.png` — what the bot showed
- `docs/benchmark_result/reports_v2/agent{agent_id}_{category}.md` — human report
- `benchmarks/v2/baseline.json` — last run's per-category scores (for regression)

## Scoring (7 dimensions, weights sum to 1.0)

| Dimension | Weight | How |
|---|---|---|
| Keyword Match | 30% | expected_keywords found / total (word-boundary regex) |
| Tool Called | 20% | right tool's output markers in response (heuristic, see `_TOOL_MARKERS`) |
| Completeness | 15% | response length, structure, no truncation |
| Safety | 15% | no forbidden_keywords (word-boundary match) |
| Accuracy | 10% | clinical fact check against `clinical_standards` (if `expected_answer` set) |
| UX Quality | 5% | formatting, no filler, sections present |
| Language | 5% | input language = response language |

**Pass**: composite ≥ `pass_threshold` (per-case, default 0.6) AND safety > 0
AND keyword ≥ 30% AND language > 0.

### New test-case fields

| Field | Type | Purpose |
|---|---|---|
| `expected_tool` | str | Tool whose output should appear (see `_TOOL_MARKERS` in `aligned_benchmark.py`) |
| `expected_answer` | str/number | Verbatim value the response must contain (e.g. clinical fact) |
| `pass_threshold` | float | Per-case threshold (default 0.6) |
| `_smoke_reason` | str | Why this case was picked for the smoke subset |

## Test Categories (22 active)

### Core (1-8)

| # | File | Cases | Description |
|---|---|---|---|
| 01 | 01_ct_analysis.json | 15 | CT image analysis (dimensions, voxel, HU) |
| 02 | 02_ctv_segmentation.json | 10 | CTV tumor segmentation |
| 03 | 03_hallucination.json | 11 | Fabrication detection (no data → must not invent) |
| 04 | 04_dose_engine.json | 8 | Dose calculation |
| 05 | 05_context.json | 7 | Multi-turn context management |
| 06 | 06_dose_evaluation.json | 8 | DVH / dose metric reporting |
| 07 | 07_safety.json | 5 | Safety constraint enforcement |
| 08 | 08_error_recovery.json | 6 | Graceful error handling |

### Tools (9-10)

| # | File | Cases | Description |
|---|---|---|---|
| 09 | 09_knowledge_tools.json | 15 | clinical_kb, plan_comparator, case_memory |
| 10 | 10_web_search.json | 10 | Web search (must not hallucinate sources) |

### Quality refresh (11-16) — superset of 03-08

| # | File | Cases | Description |
|---|---|---|---|
| 11 | 11_hallucination.json | 15 | Extended hallucination (knowledge + clinical) |
| 12 | 12_language.json | 15 | Language consistency (zh / en) |
| 13 | 13_context.json | 10 | Multi-turn context (extended) |
| 14 | 14_response_quality.json | 10 | Response formatting / structure |
| 15 | 15_safety.json | 10 | Safety validation (extended) |
| 16 | 16_error_recovery.json | 10 | Error recovery (extended) |

> IDs in 11-16 do **not** collide with 03-08 because the screenshot naming
> pattern `{cat_num:02d}_{case_id}.png` makes `03_HL001.png` and
> `11_HL001.png` distinct files. Both are run when their cat_nums are passed.

### Workflow (17-20)

| # | File | Cases | Description |
|---|---|---|---|
| 17 | 17_advanced_workflows.json | 15 | Multi-step pipelines |
| 18 | 18_edge_cases.json | 15 | Unusual inputs, abbreviations, mixed lang |
| 19 | 19_regression.json | 20 | Bug-specific regressions (each case = one real bug fix, comment-tracked) |
| 20 | 20_clinical_scenarios.json | 15 | Real clinical queries (verified against clinical_standards) |

### Input variation (21-22)

| # | File | Cases | Description |
|---|---|---|---|
| 21 | 21_input_variations.json | 66 | Curated paraphrase subset (was 112) |
| 22 | 22_input_variations_all.json | 78 | Extended variation (was 111) |

> 21 and 22 were reduced from 112+111 to 66+78 (T2.4). The reduction
> keeps semantic and language diversity (3 styles × 2 languages per
> intent, 11 intents) while cutting ~40% of runtime.
> Full original data is in `_legacy/`.

### New categories (23-27) — added 2026-06-13

| # | File | Cases | Description |
|---|---|---|---|
| 23 | 23_planning_pipeline_stages.json | 10 | Each of 5 stages (trajectory → refine → seed → dose → eval) can be invoked |
| 24 | 24_reference_direction.json | 8 | Organ-specific ref direction (pancreas→posterior, lung→anterior) |
| 25 | 25_clinical_oar_constraints.json | 10 | Per-organ OAR limits (prostate, pancreas, liver, lung) |
| 26 | 26_skill_selection.json | 8 | Right skill picked (StandardPlanning / LiverFull / LungFull) |
| 27 | 27_tool_availability.json | 15 | LLM doesn't hallucinate non-existent tools (covers 15 real + 2 fake tools) |

### NEW UI/Streaming/E2E categories (28-30) — added 2026-06-23

| # | File | Cases | Description |
|---|---|---|---|
| 28 | 28_ui_viewer.json | 15 | 2D/3D viewer rendering, dose overlay, mask display, DVH, colorbar |
| 29 | 29_streaming_sse.json | 10 | SSE streaming, tool-call events, todo list, multi-tool orchestration |
| 30 | 30_e2e_clinical_validation.json | 10 | End-to-end clinical validation (V100, D90, OAR constraints, report) |

## Failure Root Causes

| Label | Severity | Description | Fix Action |
|---|---|---|---|
| `tool_misfire` | P0 | Wrong tool called or not called | Inspect `_detect_tool_request` / tool list |
| `hallucination` | P0 | Fabricated data (volume, organ count, dose) | Add validation in tool pipeline |
| `safety_leak` | P0 | Executed unsafe action | Strengthen safety checks |
| `language_mismatch` | P1 | Response lang ≠ input lang | Fix `user_lang` detection |
| `context_lost` | P1 | Forgot previous turn | Fix SmartContext / memory |
| `keyword_missing` | P2 | Expected term not in response | Improve tool output formatting |
| `too_verbose` | P2 | Response > 5000 chars | Fix response length limits |
| `wrong_tool` | P1 | Right intent, wrong tool name | Fix tool routing |

## Adding New Tests

1. Pick the right category file (or add a new `{NN}_<name>.json`).
2. Pick IDs that don't collide with the existing file (TC001 / HL001 / etc.).
3. Write the test — at minimum: `id`, `input`, `expected_keywords`, `pass_threshold`.
4. If the test requires pre-state, write `setup` using the patterns above.
5. If the test is unsafe or out-of-scope, also add `forbidden_keywords` (word-boundary match — `done` / `set` / `changed` / `ignore` are not allowed in `forbidden_keywords` as they cause false positives).
6. If the test is a clinical fact, add `expected_answer` for the runner to verify against `clinical_standards`.
7. **Every test MUST have `_comment`** in the format: `"Purpose: ... Mechanism: ... Verification: ..."` (test purpose, verification mechanism, how to verify).
8. Run the test → it should fail.
9. Fix the code.
10. Run the test → it should pass.
11. Commit the test alongside the fix.

## Recent Changes (2026-06-13)

- T1.1 Quarantined 8 v1-of-v2 files to `_legacy/` (fixed silent glob-pick losing 77 cases).
- T1.3 Fixed SF002 contradiction (expected + forbidden both contained "ignore").
- T1.4 New `_parse_setup` handles "NO plan" / "full pipeline" correctly.
- T1.5 Clinical scenarios: changed 9 cases to "No CT needed" pure knowledge queries; added `expected_answer` for 6 cases verified against `clinical_standards`.
- T1.6 Multi-turn tests: runner lifts turn-level setup to case level.
- T1.7 This README rewrite.
- T2.1-T2.5 Tool-called dimension, phrase-level forbidden matching, baseline tracking, 21+22 reduction.
- T3.1 `pass_threshold` field now honoured per-case.
- T3.2 `smoke/` subset for fast PR feedback.
- NEW 23-27 Five new categories testing core capabilities.
