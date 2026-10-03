# BrachyBot Planning Performance Review, Equivalent Acceleration, and Verification Report

Date: 2026-09-15

Original analysis report and code baseline: `a7fbbba23` (the earlier version cited in the original text is `8444676b8`)

Scope: the five-step planning chain and its needle-path safety checks, geometric search, and DoseUNet input construction; planning parameters, physical safety constraints, and the dose model are unchanged.

## 1. Conclusions and Measurement Basis

The original report captured two key bottlenecks: **repeatedly reading the entire CT per needle to determine truncated faces**, and **DoseUNet's per-particle line-map preprocessing**. The approach is broadly feasible, but the original report added together timings of different granularities, double-counted optimization gains, and presented unverified predictions too definitively. Here we first measure the actual chain, then implement equivalent optimizations.

First independent replay of the same case, run sequentially:

| Stage | Before | After |
|---|---:|---:|
| trajectory_init | 104.377 s | 10.929 s |
| trajectory_refine | 82.636 s | 0.671 s |
| seed_planning | 175.513 s | 65.544 s |
| dose_calc | 0.144 s | 0.145 s |
| dose_eval | 0.163 s | 0.163 s |
| **Five-step total** | **362.834 s** | **77.451 s** |

The five-step total is **4.68x** faster, with a **78.7%** reduction in time. These are a single paired measurement, not an SLA for all cases.

Second independent paired re-test:

| Stage | Before | After |
|---|---:|---:|
| trajectory_init | 71.135 s | 11.124 s |
| trajectory_refine | 49.133 s | 0.466 s |
| seed_planning | 199.444 s | 68.385 s |
| dose_calc | 0.097 s | 0.100 s |
| dose_eval | 0.175 s | 0.177 s |
| **Five-step total** | **319.984 s** | **80.251 s** |

The second group is **3.99x** faster, with a **74.9%** reduction in time. The two groups are 4.68x and 3.99x respectively; the fastest run is not treated as a stable upper bound.

### Full-entry verification after synchronization (2026-09-16)

Directly importing the remote synchronized source files and calling `_run_full_pipeline` with the normal GPU strategy:

- Data decoding, loading, and orientation preparation in a separate process: **47.994 s**;
- Full pipeline wrapper (including the shared body mask and the five steps): **79.532 s**;
- Five steps: 10.51 / 0.59 / 64.32 / 0.09 / 0.16 s;
- The two parts total roughly **127.53 s**, still excluding first-time module import, segmentation, LLM, guides, screenshots, and browser recovery;
- Returned successfully, five-step pending/done events were normal, and `latency_profile` and the original `substep_timings` both existed;
- 106 particles, 18 needles; V100=90.18965113556544%, D90=120.63172149658203 Gy;
- **All eight output fingerprints matched the second group's old-version baseline**, including the independent particle position/direction/attribution fields;
- Under-coverage repair exited normally due to `target_reached`, trials=0, and planning did not end by timeout.

This check verifies real code import and the full tool entry point; it is not a browser end-to-end test. The 48 s of data reading is the recovery cost of this separate replay and must not be treated as a fixed additional cost for every request on a loaded Session.

- The user's historical log shows a five-step total of 551.89 s, while planning_pipeline is about 607 s and a full conversation round is 921.9 s. **The current 77.45 s cannot be directly divided into the historical full-round time to derive a code speedup ratio.**
- The table above does not count reading snapshots, loading CT/masks, building the shared body mask, or outer request handling; it excludes segmentation, LLM, guide generation, report screenshots, and Session checkpointing.
- GPU training was still running during the re-test; no training task was paused, migrated, or modified. Load, cache, and file IO cause wall-clock fluctuation.
- This is an independent in-memory replay after reading the original Session input; it does not write back to the case or trigger the browser or checkpointing. A subsequent real UI full-chain run should still be timed separately.
- Single-case consistency is clear evidence, but not a mathematical proof for all inputs, hardware, or concurrency states.

## 2. Result Consistency

The following items in the first comparison group have identical SHA-256:

| Object | Result |
|---|---|
| Initial safe candidate set and order | Identical |
| Refined candidate set and order | Identical |
| Final validated needle-path geometry | Identical |
| Full dose array over the planning space | Identical |
| Gy dose array | Identical |
| Full dose metrics | Identical |
| algorithm_plan_dvh_data | Identical |

The numerical results are all:

- Final safe candidates: 349;
- Final needle paths: 18; particles: 106;
- V100: 0.9018965113556544, i.e. 90.18965113556544%;
- V150: 0.6094591430578319;
- V200: 0.33809412315616943;
- D90: 120.63167572021484 Gy.

The first group's script did not record a valid independent particle-position field (the old script used a non-existent `seed_positions` alias). The second group and the formal replay scripts instead use the actually stored `seed_plan_serialized`, which contains per-needle attribution, particle centers, and directions. **In the second group, this field and all fields in the table above have exactly identical SHA-256.** Identical dose arrays do not replace independent verification of the particle fields.

Each of the two groups is exactly consistent in its own pairing, but the D90 of the first and second groups is 120.63167572021484 / 120.63172149658203 Gy respectively, a difference of about 0.000046 Gy; the old version itself showed this difference as well. The existing CUDA configuration for normal inference has cuDNN autotuning enabled, so normal repeated runs across processes cannot be generalized into a bit-exact guarantee. This GPU strategy was not changed this time; in addition, a `--deterministic` option effective only in the replay process is provided to fix algorithm selection and check the strict equivalence of the CPU changes.

### Budget boundary of the fixed-algorithm replay (added 2026-09-16)

An additional run of the full entry point's old hotspot baseline with `--deterministic` enabled: load 31.68 s, pipeline 841.12 s; the five steps were 128.17 / 96.29 / 613.00 / 0.13 / 0.19 s respectively. Rule Stage 1 took 301.885 s, triggering the original 300 s wall-clock budget; the subsequent base repair budget of 60 s and the 120 s extension were also exhausted, ending with 105 particles, 18 needles, V100=89.9087%, D90=119.7102 Gy.

**This is not a valid acceptance baseline for "same results after full execution," and it is not included in the speedup ratio.** The fixed algorithm configuration and the load at the time differ from the normal two groups, and the budget already changed the actual number of actions completed. No budget was extended this time to make the test pass, and failing to reach the coverage target was not treated as success. `--deterministic` only rules out some GPU algorithm-selection nondeterminism; it cannot eliminate wall-clock cutoff conditions. The two paired groups under the normal GPU strategy and the CPU differential test are the consistency evidence passed this time.

## 3. Actual Root Causes and Changes Needed to the Original Report

### 3.1 CT truncated-face information was repeatedly computed for every needle

Call chain:

`_filter_world_safe_trajectories` → `_needle_enters_through_truncated_boundary` → `infer_truncated_boundary_faces_from_image`

The old code passed `truncated_boundary_faces=None` to the per-needle check, causing every needle in a batch to re-copy and re-analyze the boundary information of the original CT. The init, refine, and seed stages all pass through this filter.

The measured three batch-filter runs total **205.758 s → 1.153 s**. This does not remove needle-path validation; rather, the six-face CT flags that are constant within a batch are computed once and passed to each needle.

Still performed per needle:

- Full 150 mm physical needle-path validation;
- Truncated scan-face entry rejection;
- non-traversable obstacle detection;
- Rejection when the safety context is missing;
- Final re-validation of particle/needle-path geometry.

On failure, the original per-needle check fallback is retained; a needle path is not judged safe because of a metadata computation anomaly.

**Skipping all safety filtering in refine was not implemented.** The input mask, structure classification, puncturability, or manual state may change, and cross-step caching must cover the full-version identity. Eliminating this round of repeated CT analysis already yields most of the benefit without risking reuse of an old "already safe" conclusion.

### 3.2 line-map large temporary arrays causing memory bandwidth overhead

The 109 `generate_line_map` calls total **83.660 s → 19.270 s**. Full preprocessing totals **98.199 s → 26.925 s**; the two are nested timings and cannot be added.

Voxel chunking along the X axis in slabs of 8 layers each is used:

- Original floating-point types, trigonometric functions, vector normalization, and the per-voxel expression are preserved;
- `np.stack` and the original vector norm reduction method are preserved;
- NaN/Inf and axial special-case handling are preserved;
- **Global** maximum normalization is performed only after all chunk computations complete;
- Output still uses the original SimpleITK metadata and conversion path.

The original report suggested algebraic rearrangements such as replacing norm with the sqrt of the squared distance, which could change the last-place rounding; these were not adopted. Of the two norm calls per invocation in the old code, one is only over a 3-element direction vector, not two full-volume norms.

The model checkpoint, patch, overlap, input channels, spacing, dose scale, inference batch size, and precision were all unchanged.

### 3.3 Per-sample Python loops in ray tracing

Per-ray batch evaluation is implemented, preserving the original sample order and stopping rules:

- `_trace_target_exit`: uses `np.add.accumulate` to preserve the rounding semantics of the original repeated addition; it cannot simply be changed to start+n*step.
- `trajectory_entry_is_valid`: computes the same positions in batch, still deciding at the first exit from the image or first entry into air; all boundary-face rules are unchanged.
- `get_trajectory_info`: batch sampling, preserving the original target/background segment statistics state machine and not adding terminal-segment recording; float32 input keeps the type semantics of the original scalar multiplication.

In the first replay, trace-exit was 38,912 calls: 11.413 s → 6.884 s; entry-check was 9,572 calls: 6.041 s → 0.801 s. The number of calls did not decrease.

The original report estimated that the ray loop accounted for 80–120 s of init, which lacks real full-chain support. The current measurement shows the largest item is repeated CT analysis; close points or directional coverage should not be reduced on that basis.

### 3.4 Deduplication of available particle position coordinate transforms

Within `get_available_position`, the physical transform/distance for identical candidate coordinates is computed only once; the needle-path end distance is computed once on demand and then reused in the existing particle-spacing exclusion.

- Candidate order, boundary strict greater-than/less-than, coordinate transforms, and the existing seed distance expression are preserved;
- Placeable positions, particle spacing, and the depth strategy are unchanged;
- Full flow 14,044 calls: 6.447 s → 3.318 s;
- The refine stage takes only about 0.11 s, so the original report's estimate that "refine position filtering accounts for a large proportion" does not hold.

### 3.5 Existing reuse and low-priority items

- `_run_full_pipeline` already shares the CT body mask; the expected savings from "rebuilding the body mask at each step" cannot be counted again.
- Voxel filtering totals only about 0.075 s across three runs, so cross-trajectory parallelism is not worth doing first.
- The currently measured number of dose line-map calls is 109; the original text's "270 cold candidates × 1 s" is not an observed fact.
- The first group's old/new-version GPU sliding-window totals are 21.707/26.461 s; the new version's GPU time is actually slightly longer, yet the overall time is still significantly faster, supporting the judgment that the main gain comes from repeated CPU work.
- "607 seconds have almost no algorithmically necessary overhead" is inaccurate: geometry generation, safety determination, and dose inference and evaluation all contain indispensable work.

## 4. Implemented Code Scope

| File | Change |
|---|---|
| `tool_factory/seed_plan/planning_pipeline.py` | Infer CT truncated faces once per batch; timing for the full flow/key functions |
| `plans/utilizations.py` | Equivalent batch determination of ray boundaries and entry; deduplication of placeable-position transforms |
| `plans/geometry.py` | Batch trajectory voxel sampling, with unchanged segment statistics semantics |
| `plans/dose_pre/inference.py` | line-map chunked computation; dose preprocessing/sliding-window timing |
| `plans/core.py` | Segmented timing for candidate generation and rule optimization Stage 1/2/3 |
| `plans/performance.py` | ContextVar per-request timing, restoring context on exception |
| `tests/test_planning_latency_equivalence.py` | Differential regression freezing the old implementation |
| `tests/latency_reference.json` | Original functions extracted from a7fbbba23, without patient data |
| `tests/test_planning_latency_profile.py` | Timing does not change return/exceptions, concurrency isolation, nested restoration |
| `scripts/benchmark_planning_latency.py` | Repeatable read-only case replay, outputting timings and result fingerprints |

The original planning parameters, budgets, candidate counts, directions, close point strategy, refine order, RL/rule fallback, repair conditions, dose model, and guide strategy were all unchanged.

The paired raw timings, result fingerprints, and comparison results are stored separately in `docs/PLANNING_LATENCY_BENCHMARK_2026-09-15.json`, without imaging/mask/particle-coordinate plaintext. The original case snapshot was not written back.

## 5. Timing and Regression Verification

### Automated regression

The new geometry differential covers random points, voxel boundaries, internal cavities, non-convex masks, truncated-face combinations, different step sizes, rotated/anisotropic grids, float32/float64 rays, and existing particle exclusion.

The line-map differential covers 120³ and cropped volumes, axial/oblique particles, non-zero origin, rotated direction, and anisotropic spacing, requiring arrays to be exactly equal and image metadata to be preserved.

The safety test verifies that "one CT analysis" still performs truncation and obstacle checks per needle; missing obstacle context is still rejected. Existing close point, dose contract, and physical needle-path tests are run separately.

Actual results: 71 items passed under the temporary differential installation; after synchronizing the source files, the extended test set run directly gave **83 passed, 3 warnings**. The latter includes the new differential/timing tests, close point, performance contract, physical needle-path safety, parallel needle-path spacing, dose units, planning budget/loop termination, RL batch contract, candidate capacity preference, and planning preview/run records. The warnings do not affect passing, but no claim of completed browser full-flow verification is made on that basis.

After adding the frozen-baseline manifest completeness test, the two new test files re-run separately gave **8 passed, 3 warnings** (overlapping with the extended set above and not additive to a total).

### Runtime timing

New tool metadata returned by full pipeline:

```text
latency_profile.total_seconds
latency_profile.nested_timings.<name>.calls
latency_profile.nested_timings.<name>.seconds
```

The `[planning_latency]` log is also recorded. **nested_timings has parent-child overlap and cannot be summed item by item.** The timing context does not hold patient arrays/model instances and is not shared across requests via a dictionary. The existing substep_timings and UI events are unchanged.

### Reproducible replay

Execute sequentially in the repository root in the brachytherapy environment; do not let two planning runs compete for the GPU:

```bash
python scripts/benchmark_planning_latency.py \
  --workspace /absolute/path/to/session \
  --variant baseline --output /tmp/planning-baseline.json

python scripts/benchmark_planning_latency.py \
  --workspace /absolute/path/to/session \
  --variant current --output /tmp/planning-current.json
```

The source snapshot is required to be unchanged between the two replays; compare the snapshot/inputs hashes, all result hashes, and metrics. The output must be outside the source Session, and existing output files will not be overwritten. baseline only restores the old hotspot functions involved in this optimization; it does not switch the entire application to a historical version.

For strict numerical verification, add `--deterministic` to both commands. This option only sets cuDNN deterministic / disables benchmark in the separate replay process and retains the original TF32 strategy; it is not written to the production configuration. Its duration cannot be mixed with the paired timings of the normal GPU strategy.

`load_seconds` is data decoding/loading/orientation preparation; `pipeline_seconds` is the full five-step wrapper (including the shared body mask); `substep_timings` is the five steps; these three bases should be distinguished.

## 6. Options Not Yet Implemented and Reasons

| Option | Assessment |
|---|---|
| Directly skip safety filtering across steps | Must have the full input/strategy version identity; not worth taking this risk now |
| Change batch, mixed precision, or parallel candidate evaluation | GPU floating-point reduction, candidate dependencies, and deadlines affect results; not an optimization proven equivalent |
| Process-level model singleton | Saves a small amount of load time, but requires device/checkpoint identity, concurrency locks, and lifecycle design |
| Enlarge dose cache / share across optimizers | Measure hits and evictions first; multi-user cases need a total memory budget and cannot be enlarged arbitrarily |
| Cache the entire plan or segmentation | Must include input/model/parameters/structure strategy and version; whether duplicate requests should be recomputed is also user semantics |
| Pause or migrate training | A resource-scheduling choice; not operated this time |
| Guide failure and screenshot time | Separate issue; this optimization does not mark failures as success or weaken manufacturing/needle-path safety limits |

## 7. Acceptance Boundary and Follow-up Order

1. This time, deliver first the CPU optimizations with observed large gains and consistent results, not aiming to implement all options simultaneously.
2. After completing the paired replay for the current case, coverage still needs to be extended to other cases of different sizes, shapes, and RL modes; the single-case 4.68x cannot be promised as the speed for all cases.
3. **Do not shorten the time budget.** If an old implementation stopped early due to a wall-clock cutoff while the new version completes more of the originally intended actions, the results may differ; in that case the reason for stopping must be recorded separately, and bit-for-bit equality cannot be claimed.
4. The next step is to add timing from real requests to identify remaining bottlenecks, then consider GPU scheduling, model caching, or a safe preprocessing pipeline.
5. Planning success is not guide success; guide failures in the user log should still be reported separately. This document only proves software result equivalence; it does not constitute a clinical dose/guide effectiveness validation.
6. This time there is no automatic commit/push, no service restart, and no replacement of the public release; whether the source synchronization, tests, and service actually loaded the new version should be stated separately.

The original report's 130–210 s / 100–150 s predictions, the directly additive savings per Tier, and the generalized "all results unchanged" conclusion have been withdrawn, replaced by the paired measurements above and explicit verification boundaries. The original draft can be retrieved from the Git baseline.

## 8. 2026-09-16 Independent Review Feedback and Strengthening

The main conclusions of the independent review hold. This round checked the six frozen functions again against the Git original text, all verbatim identical; the old baseline was not reconstructed from the current optimized functions.

Implemented:

- `latency_reference.json` adds 36 shared-symbol source fingerprints extracted from `a7fbbba23`, covering recursive local helpers, coordinate grid cache configuration, and related import declarations, and explicitly covering the cross-module `voxel_to_world` and the locally imported truncated-face inference. Source newlines are normalized to LF to avoid false drift from CRLF. `scripts/latency_dependency_guard.py` validates before equivalence tests and old-baseline replays; a dependency change aborts verification; a negative test with a deliberately deleted helper is included. This is not equivalent to freezing the entire Python/NumPy/Torch environment or all cross-module implementations; pairing still requires the same environment.
- A conservative result-equivalence declaration gate is added: rule optimization must have an explicit untouched-deadline record and a final `target_reached`, neither the base nor the extended repair may hit a budget cutoff, and all eight result fingerprints must be complete. The two runs must also have identical input fingerprints and inference strategies and all identical output fingerprints. A single `eligible` only means it may participate in comparison; it does not mean it is already identical to another run. When old evidence lacks the new budget fields, it is marked unverified rather than fabricating fields; RL still lacks complete budget attribution, so it is temporarily not admitted to end-to-end "same result" declarations.
- Each repair pass records the measured `elapsed_seconds`, and a new `budget_allocated_seconds` is added. The old `budget_used_seconds` is retained for the time being for consumer compatibility and is explicitly marked as a historical quota alias, no longer interpreted as actual runtime.
- Removed the duplicate condition in `trajectory_entry_is_valid` already guaranteed by `stops`, while retaining the truncated-face rejection logic.
- The final needle-path validation and the post-crop re-check share the current CT's boundary-face information; computation anomalies continue to use the original safety fallback. The second validation is only performed when cropping occurs and should not be described as saving two checks every time. Per-needle safety validation was not skipped, and no cross-patient cache was established.

A real pancreas case replay of this round's current implementation: input load 26.369 s, planning main chain 69.630 s, 106 particles, 18 needle paths, V100=90.189651%, D90=120.631676 Gy. The quota for zero repair trials is 60 s, with a measured duration of 0.022688 s; the rule stage did not touch the deadline. The needle-path/particle fingerprints of this round and the previous independent replay were consistent; the dose fields showed a tiny cross-run difference, so the move from 79.5 s to 69.6 s is not treated as a gain from this round's changes, nor is the cross-run dose called bit-for-bit identical. The original strict pairing evidence and this round's repeatability check are archived separately.

### Follow-up performance priorities (re-ranked by current measurement)

This round `rule_stage1=49.244 s`; 109 preprocessing runs total 25.695 s, of which line map is 18.254 s and GPU window inference is 17.785 s. The timings are nested and cannot be added to estimate total duration. Model loading is only 0.703 s, so a process-level singleton should not take priority over preprocessing, and it must resolve checkpoint/device identity, concurrency, and GPU memory lifecycle.

1. **Bounded CPU prefetch is worth experimenting with, but do not just default to four threads.** `put_seeds` recomputes available positions after each accepted particle, and the next action depends on the previous step's result and coverage. A correct implementation should only preprocess discardable candidate inputs, preserving the actual acceptance order, batch=1, GPU call order, and cache-write semantics; it must limit in-flight memory, handle cancellation/deadlines and thread-context timing, and avoid excessive contention between SimpleITK internal threads and external threads. First perform an isolated A/B, and enable it only after demonstrating effectiveness.
2. Batch GPU inference, mixed precision, and reordering candidates are not part of this round's bit-for-bit equivalent optimization and were not enabled.
3. Exact ray deduplication or line-map intermediate reuse should first sample the actual repetition rate of identical full keys; the cache key must include image geometry/mask identity, direction, start point, step size, and all other dependencies, and candidates cannot be merged with a tolerance.
4. In the long run, a dual budget of "algorithmic work upper limit + independent safety wall-clock upper limit" is more reasonable. Counting should at least distinguish candidate trials, actual dose inference, repair rounds, and RL actions, and clarify whether cache hits are counted. Simply replacing seconds with iteration counts would change the existing strategy, so the default budget is not changed this round.
5. Strict end-to-end pairing for different real cases and RL has not yet been completed; synthetic non-convex/cavity/anisotropic tests cannot replace them, nor can single-case speed be generalized.

This batch of performance code, frozen assets, tests, timing module, benchmark, and report must be delivered together; parallel changes such as the cancellation flow, workspace, guides, and front end are not included in the performance commit. The service was not restarted, the public release was not replaced, and the case Session was not written back.

### Additional strict pairing result of this round

`docs/PLANNING_LATENCY_REVIEW_2026-09-16.json` stores the two raw summaries and the gate determinations. The main-chain duration of the frozen old-hotspot implementation is 374.569 s, and the current implementation is 69.630 s, about 5.38x; input loading is 27.246 s and 26.369 s respectively, listed separately and not mixed into the main-chain speedup ratio. The two input fingerprints are identical, all eight output SHA-256 are identical, both are 106 particles and 18 needle paths, V100=90.189651%, D90=120.631676 Gy; the rule stage did not touch the deadline in either run, and both repairs were `target_reached`. The comparison gate passed.

This is a re-verification on this case of the whole batch of existing hotspot optimizations relative to the original baseline; it is not that this round's telemetry/anti-drift strengthening additionally brought a 5.38x improvement, nor is it a speed promise for other cases or RL. The earlier records of tiny cross-run dose differences are retained and not overwritten or erased by this round's successful pairing.

This round's related tests cover 39 independent test items (equivalence and timing, budget declaration gate, dependency drift and delivery contract, repair strategy, default budget, and planning preview); there are only the three pre-existing SWIG type deprecation warnings. The performance files are organized as separate commits, and the remaining work-in-progress stays in the workspace; this section is a follow-up update to the previous round's "not automatically committed" status and does not mean it has been pushed or that the online service has been restarted.
