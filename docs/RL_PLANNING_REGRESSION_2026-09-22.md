# Reinforcement Learning Planning Regression Root-Cause Report

- Date: 2026-09-22
- Case: `CTzhouqun_20260912_130651.nii` (session `69cfb439e0f643ca890f9df74a86a505`, CTV volume 238.17 cm³ / 142,533 voxels)
- Triggering commit: `7df40b5a7 fix(plans): align the RL search with a real objective; batched dose cache; reproducible greedy incumbent` (2026-09-22 18:52, RL rewrite, 1334 lines changed in `plans/reinforcement.py`)
- One-sentence conclusion: **This run used `mode=rl`, whereas the historically successful approach for this case was `mode=rule_based`; at the same time, the "greedy warm start" newly added in this RL rewrite exhausted the wall-clock budget before any real learning took place, and also performed dose inference a second time, resulting in 0 RL episodes and a large regression versus rule-based optimization.**

---

## 1. Symptoms

User feedback: "This case used to plan successfully; now planning hasn't succeeded after ten minutes, and it's much weaker."

| Item | Previous successful approach | This run (2026-09-22 22:13) |
|---|---|---|
| Planning mode | `rule_based` | **`rl`** |
| Needles / seeds | 24 needles / **181 seeds** | 24 needles / **57 seeds** |
| V100 | **≈90.3%** (meets target) | 11.3% |
| D90 | — | 27.20 Gy |
| Plan score | — | 35/100 |
| RL execution | N/A | Interrupted (`wall_clock_budget`), **episodes 0/0/0, actions 0** |
| Duration | Planning phase approx. 16 min | `seed_planning` 614 s, whole run 988 s |

This run's RL diagnostic (returned by the tool):

```
Execution status: interrupted
Stop reason: reached wall-clock budget (wall_clock_budget)
Target coverage / best coverage: 90.0% / 7.2%
Best reward: 0.0711
Episodes (total / high-level / low-level): 0 / 0 / 0
Actions / dense needle tracks / dense seed candidates: 0 / 20 / 70
Elapsed / dose cache hits / misses: 614.145 s / 80 / 70
```

---

## 2. Key Evidence (Logs)

Log locations: internal test `BrachyBot/.runtime/logs/server.log` (about 28k lines, covering from 2026-09-16 onward), real-time log `/tmp/brachybot_server.log`.

### 2.1 All successful 181-seed plans came from `rule_based`

```
server.log:14273  2026-09-18 19:25:05  Running seed planning (mode=rule_based)...
server.log:14445  2026-09-18 19:40:58  [optimal_plan] Final seed distribution: needles=24 ... max_seeds_per_needle=13
server.log:14451  2026-09-18 19:41:01  [seed_planning] Stored ... seed_plan=24 entries, total_seeds=181
server.log:15507  2026-09-18 21:57:58  (same as above, 181)
server.log:16257  2026-09-19 16:02:16  (same as above, 181)
```

### 2.2 In the full logs, `mode=rl` was run only twice, and neither succeeded

```
server.log:12366  2026-09-18 17:27:35  Running seed planning (mode=rl)...
server.log:27995  2026-09-22 22:13:55  Running seed planning (mode=rl)...   ← this run
```

- The 09-18 run (old RL code): dense evaluation hit the wall clock and retained only 14/20 trajectories and 56 seeds; hierarchical expansion at depth 2 hit the wall clock; baseline scoring hit the wall clock → RL coverage **0.0000**, rule-based fallback 0.0302.
- On 2026-09-21 ("yesterday") there were **no RL run records at all**.

### 2.3 Timeline and budget consumption of this run

| Time | Event | Notes |
|---|---|---|
| 22:13:55.8 | Load model, `Running seed planning (mode=rl)` | `max_wall_seconds=300` start |
| 22:14:39.9 | Dense evaluation complete: 20 trajectories / 70 seeds | `:28029`, took about 44 s |
| 22:18:56.3 | **High-level episode loop hit the wall clock** | `:28095`, indicating the 300 s was already exhausted before entering the loop |
| 22:19:00.9 | Low-level episode loop hit the wall clock | `:28096` |
| 22:19:01.6 | Rule-based fallback triggered (RL coverage 0.0716 < 0.9) | `:28098` |
| 22:21:03.9 | Fallback complete, coverage 0.0571, **did not exceed RL, RL result retained** | `:28137` (fallback ran the full 120 s) |
| 22:24:10.2 | Coverage repair complete, 0.0716 → 0.1132 | `:28166` (repair 186 s, adaptively extended to 180 s) |

Key lines:

```
server.log:28095  WARNING plans.reinforcement  [rl] Hierarchical RL episode loop reached its wall-clock budget
server.log:28096  WARNING plans.reinforcement  [rl] Low-level RL episode loop reached its wall-clock budget
           :28097  INFO  plans.reinforcement  [rl] seed-dose cache: 80 hits, 70 model evaluations, 182.13s uncached inference
```

From the end of dense evaluation (22:14:39) until RL hit the wall clock (22:18:56), a total of about **257 s**; of which `model_inference_seconds = 182.13 s`, corresponding to **70 DoseUNet inferences**. This RL run had **0 episodes, 0 actions**, so these 70 inferences can only come from the **whole-group prefetch of the greedy warm start**.

---

## 3. Root-Cause Analysis

### 3.1 Direct cause: the newly added "greedy warm start" exhausted the RL budget; RL never completed a single episode

`plans/reinforcement.py` (newly added in `7df40b5a7`; did not exist in the old code):

- `reinforcement.py:1390-1394`: `greedy_enabled = rf_params.get("greedy_warm_start", True)`, enabled by default; calls `_greedy_incumbent(best_group_idx, ...)` **before** entering the REINFORCE episode loop.
- `reinforcement.py:1348-1388`: `_greedy_incumbent` → `env.run_greedy(group_idx, device)`.
- `reinforcement.py:915-932`: `run_greedy` defaults to `restarts=3`, i.e. performs 3 greedy passes.
- `reinforcement.py:730-751`: `activate_group` calls `prefetch_positions` on **all candidate positions** of the selected group.
- `reinforcement.py:269-302`: `prefetch_positions` runs DoseUNet in a single batch, filling `seed_cache`.
- `reinforcement.py:934-986`: before placing each seed, `_greedy_pass` calls `evaluate_action_marginal` for **every candidate** in the mask (`reinforcement.py:896-913` / `390-419`), and each call performs a `float32→float64` conversion and DVH computation over the full voxel set.

This entire set (whole-group prefetch + 3 greedy passes × iterating over all candidates at each step) happens entirely before the episode loop and is not subject to any budget constraint. Once `max_wall_seconds=300` is exhausted, the wall-clock check in the high-level loop at `reinforcement.py:1421-1428` fires immediately, `actions_taken` is still 0 → **0 episodes**, and a weak baseline is returned directly.

By contrast, `plans/utilizations.py`: `max_wall_seconds` defaults to 300 (`utilizations.py:4448-4456`), `candidate_limit=20`, `dense_seed_limit=40`, `max_hierarchy_depth=8`, `max_actions_per_episode=40` (`config/default_params.json`).

### 3.2 Time inflation: the greedy prefetch **recomputed** dose maps already produced by dense evaluation

- Dense evaluation phase: `utilizations.py:4565` calls `batch_seed_dose_calculation_dl` on each trajectory's dense seeds, storing each seed's dose map in that trajectory's `traj[2]/traj[3]` (structure see `utilizations.py:4586`). 70 maps in total this run.
- Greedy prefetch phase: `prefetch_positions` **only checks the flat `self.seed_cache`** (`reinforcement.py:277-282`) and does not reuse the dense dose maps already computed in `traj[2]/traj[3]` — that path is only taken by `_lookup_seed_dose` (`reinforcement.py:242-267`).
- Result: the 70 maps computed during this run's dense evaluation were computed again during prefetch — **the miss count is exactly 70, matching the total number of dense seeds**, `model_inference_seconds=182.13s`. The dense phase's 70 maps took about 45 s, while the prefetch phase's 70 maps took about 182 s (the latter also overlapped with GPU contention from concurrent workspace checkpoint / `/api/workspace/state`).

That is: the direct source of the longer runtime is **+182 s of duplicated DoseUNet inference**, plus the 3 greedy passes of marginal scoring.

### 3.3 Structural cause: this case needs ~24 needles, and RL's candidate-level upper bound is far below that

- The CTV is 238 cm³, and the successful plan was 24 needles / 181 seeds (about 7.5 seeds/needle).
- RL can only place seeds within the case's hierarchical candidate pool. Of the final 24 needles, coverage repair added 19 needles and 21 seeds (`:640`: `added_needles=19, added_seeds=21`), from which we can infer that **the plan returned by RL had only about 5 needles** — RL simply cannot place enough needles/seeds, and its coverage ceiling is inherently far below 90%.
- The `select_hierarchy_level` newly added in `7df40b5a7` (`utilizations.py:4299-4329`) scores and selects levels using `coverage - 0.01 × needle count`, which **biases toward shallower combinations with fewer needles before coverage has even reached target**. The old code directly took the deepest level (`hierarchical[-1]`). This further lowers the needle count/coverage ceiling available to RL (when coverage is already near target, using a needle penalty for trade-offs is reasonable; but before reaching target, coverage should take priority).

### 3.4 Trigger: this run was routed to `mode=rl`

- The tool defaults to `rule_based` (`tool_factory/seed_plan/seed_planning.py:65`), and at runtime it also prompts `Use mode='rule_based' (NOT 'rl')` (`agent_runtime/llm_runtime.py:1595-1597`).
- But this run's `planning_pipeline` input was `mode:"rl"`. We need to investigate separately whether the user explicitly requested it, or whether "re-execute" reused the `plan_config.mode=rl` left over from the failed 09-18 RL run.
- Conclusion: **This case cannot reach the target with RL, but can with rule_based.** The number-one reason for "planning so badly this time" is that RL was chosen.

### 3.5 Downstream fallback/repair were insufficient to compensate

- Rule-based fallback coverage 0.0571 < RL 0.0716, discarded (`planning_pipeline.py`'s `rule_based_fallback_is_strictly_better`).
- Coverage repair only raised coverage from 0.0716 to 0.1132, and because the starting point was so bad it triggered adaptive extension (60 s → 180 s), `added_needles=19/added_seeds=21` (about 1 seed/needle on average, extremely inefficient), and added about 120 s of extra runtime.

---

## 4. Old vs. New Version Comparison

| Dimension | Old code `ccddd71c2` (09-21 and earlier) | New code `7df40b5a7` (09-22 18:52) |
|---|---|---|
| Greedy warm start `greedy_warm_start` | **None** | Present, **enabled by default** |
| Whole-group dose prefetch `prefetch_positions` | **None** | Present (all candidates of the selected group) |
| `evaluate_action_marginal` full-voxel scoring | **None** | Present (3 restarts × all candidates per step) |
| Level selection | `hierarchical[-1]` (deepest level, coverage-first) | `select_hierarchy_level` (`coverage - 0.01×needle count`, biased toward fewer needles) |
| How the RL budget was used | **Directly enter episodes** after dense evaluation, remaining budget used for placing seeds | Budget consumed first by greedy prefetch/scoring → **0 episodes** |
| This run's corresponding time structure | RL 300 s + fallback 120 s + repair 62 s (extension not triggered) | RL 257 s burned idle + fallback 122 s + repair 186 s |

Worth noting: comparing "RL vs RL" alone, the new code (coverage 0.0716 / final 0.1132) is even slightly better than the old RL from 09-18 (0.0000 / 0.0343) — but both fall far short of rule_based's 0.903. Therefore the **"weakening" is mainly caused by the algorithm/mode change, not by the same RL being made worse**; the new RL's problem is that it is "expensive and ineffective", and it exposes the failure more prominently.

---

## 5. Fix Recommendations

In priority order:

1. **Restore the correct path for this case (immediately usable)**: switch planning to `mode:"rule_based"`, which can reproduce 24 needles / 181 seeds / V100≈90%. At the same time, investigate why this run was routed to `rl` (whether "re-execute" reused the old rl parameters), and if necessary force/prompt the use of rule_based on the rerun path.

2. **Make dose prefetch reuse dense evaluation results (saves ~182 s)**: before `SeedPlacementReward.prefetch_positions` consults the cache, first call `_lookup_seed_dose(traj, ...)` for each candidate to hit the dense dose maps already stored in each trajectory's `traj[2]/traj[3]`; or, before entering `reinforcement_planning`, preload the dense dose maps into `seed_cache`.

3. **Make the greedy warm start budget-aware (restore effective RL learning)**:
   - Before entering `run_greedy`, check the remaining budget and skip directly if below the threshold;
   - Have `_greedy_pass` check `deadline` before scoring each candidate and before each restart (currently it only checks after placing each seed, `reinforcement.py:960`);
   - Converge `restarts` from 3 to 1 (or adapt it to the remaining budget);
   - A more robust approach: default `greedy_warm_start=False` (interactive path), and enable it explicitly only for research use.

4. **Fix the level selection strategy**: the needle-count penalty in `select_hierarchy_level` should take effect **only after coverage reaches target**; before reaching target, coverage should be maximized (equivalent to the old deepest-level-first), to avoid RL limiting its own needle count before reaching target.

5. **Fallback/repair efficiency**: coverage repair currently averages ~1 seed/needle (`added_seeds=21 / added_needles=19`); we need to check why needles were added but almost no seeds were placed (suspected needle-track candidates/geometric constraints allow only 1 seed per needle), otherwise even extending the budget will struggle to recover coverage.

---

## Appendix A: Key Code Locations

| File | Location | Notes |
|---|---|---|
| `plans/reinforcement.py` | `1390-1394` | `greedy_warm_start` enabled by default, called before the episode loop |
| `plans/reinforcement.py` | `1348-1388` | `_greedy_incumbent` |
| `plans/reinforcement.py` | `915-986` | `run_greedy` (restarts=3) / `_greedy_pass` |
| `plans/reinforcement.py` | `730-751` | `activate_group` whole-group prefetch |
| `plans/reinforcement.py` | `269-302` | `prefetch_positions` (only checks `seed_cache`, does not reuse dense maps) |
| `plans/reinforcement.py` | `242-267` | `_lookup_seed_dose` (can reuse `traj[2]/traj[3]`) |
| `plans/reinforcement.py` | `896-913` / `390-419` | `evaluate_action_marginal` / `evaluate_marginal` full-voxel scoring |
| `plans/reinforcement.py` | `1421-1428` | High-level loop wall-clock check → `wall_clock_budget` |
| `plans/utilizations.py` | `4299-4329` | newly added `select_hierarchy_level` (level selection with needle penalty) |
| `plans/utilizations.py` | `4448-4456` | `max_wall_seconds` deadline |
| `plans/utilizations.py` | `4563-4602` | dense evaluation + dose maps into `traj` |
| `tool_factory/seed_plan/planning_pipeline.py` | `4305-4440` | rl branch, rule fallback, coverage repair |
| `config/default_params.json` | `rf_params` | `max_wall_seconds=300`, `fallback_max_wall_seconds=120`, `coverage_repair_seconds=60/extended 120/cap 180` |

## Appendix B: Raw Log Excerpts

```
# Dense evaluation
:502  [rl] interactive budget: wall=300.0s, candidates=20, dense-seeds-per-trajectory=40, actions-per-episode=40
:533  Dense evaluation retained 20 trajectories and 70 seed candidates
# RL 0 episodes
:570  WARNING [rl] Hierarchical RL episode loop reached its wall-clock budget
:571  WARNING [rl] Low-level RL episode loop reached its wall-clock budget
:572  INFO  [rl] seed-dose cache: 80 hits, 70 model evaluations, 182.13s uncached inference
# Downstream
:612  [rl] Rule-based fallback coverage 0.0571 did not strictly improve RL coverage 0.0716; retaining the RL result
:640  [coverage_repair] initial_coverage=0.0716 final_coverage=0.1132 added_needles=19 added_seeds=21 elapsed=186.13s
# Historical success (rule_based)
:14445 [optimal_plan] Final seed distribution: needles=24 ... max_seeds_per_needle=13
:14451 [seed_planning] Stored ... seed_plan=24 entries, total_seeds=181
```

---

## Notes

- The code references in this report are based on the internal test repository `7df40b5a7` and its current working tree; that commit was synchronized to this public test repository in round 20, so the same regression exists in the public test as well.
- This report is only an analysis document and does not modify any production code. Before fixing, we recommend first running a controlled experiment of "disabling `greedy_warm_start` + reusing dense dose maps", and then deciding whether to adjust `select_hierarchy_level`.
