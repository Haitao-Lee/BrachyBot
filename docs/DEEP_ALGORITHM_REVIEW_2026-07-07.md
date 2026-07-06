# Deep Algorithm Code Review — 2026-07-07

**Review scope:** Algorithm core files outside the modularized web/agent pipeline
**Files reviewed:** `core.py`, `reinforcement.py`, `utilizations.py`, `fitting_model.py`, `data_preprocess.py`, `geometry.py`, `brachy_plan.py`, `exp.py`, `external_exp.py`, `config.py`
**Method:** Independent review agent + line-by-line verification of every finding
**Status:** **9 confirmed issues** — 3 CRITICAL, 2 HIGH, 4 MEDIUM, 4 LOW

---

## CRITICAL BUGS

### C1. `reinforcement.py:40,285-286,741` — Inverted OAR damage formula

The OAR ("organ at risk") damage penalty is computed using a ratio that
**decreases as OAR damage increases** — the exact opposite of the intended
behavior.

**`_dvh_oar_jit_fallback` at line 40:**
```python
out_damage = float(n_target) * dvh_rate / float(exceed_count)
```
where `n_target` = target (CTV) voxel count, `exceed_count` = OAR voxels
exceeding the dose threshold.

**`SeedPlacementReward` at line 285-286:**
```python
reward = min(cur_DVH_rate, self.DVH_rate) + \
         ((cur_DVH_rate - self.DVH_rate) >= 0) * (out_damage)
```

**`DVH2Rewards` at line 741:**
```python
out_damage = len(target_idx[0]) * cur_DVH_rate / exceed_count
```

**Impact:** As `exceed_count` grows (more OAR voxels overdosed), `out_damage`
shrinks, and the reward increases. The agent is **rewarded for overdosing OARs**
instead of being penalized. The correct formula should have `exceed_count` in
the numerator:
```python
out_damage = exceed_count * dvh_rate / float(n_target)   # fraction of OAR overdosed
```

**Severity: CRITICAL** — Systematically undermines the clinical objective of
sparing organs at risk.

### C2. `reinforcement.py:67,79,122,191,205,255` — Typo `target_valueimage_normalize_max`

Parameter name `target_valueimage_normalize_max` is missing an underscore
between `value` and `image`. Correct name: `target_value_image_normalize_max`.

The code explicitly acknowledges the typo with inline comments
(`# typo kept` / `# REVIEW: typo left for compatibility`), but it is frozen
because callers pass it by keyword and fixing the parameter name would break
existing call sites.

**Occurrences:**
| Line | Context |
|------|---------|
| 67 | Commented-out `__init__` (legacy) |
| 79 | Commented-out assignment (legacy) |
| 122 | Commented-out call (legacy) |
| 191 | **Active `__init__` parameter** |
| 205 | **Active instance assignment** |
| 255 | **Active call to `single_seed_dose_calculation_dl`** |
| 842 | `out_damage` formula (not the typo, but same method) |

**Impact:** Any external caller trying to pass `target_value_image_normalize_max`
(with correct underscore) gets `TypeError: unexpected keyword argument`.
Internal consistency masks the problem, but it propagates to the DL dose model
API.

**Severity: CRITICAL** — API-level defect that blocks proper integration for
external callers.

### C3. `reinforcement.py:842` — Wrong denominator in OAR damage penalty

```python
cur_out_damage = reward_calculator.target_v / max(0.1, non_target_sum)
```

Here `target_v` = CTV voxel count, `non_target_sum` = OAR voxels exceeding
threshold. The target count appears in the numerator when computing an **OAR
damage** metric. As with C1, this inverts the penalty — a large target volume
amplifies the OAR damage score for the same absolute OAR injury.

**Severity: CRITICAL** — Another instance of the inverted OAR formula in a
different code path.

---

## HIGH-SEVERITY ISSUES

### H1. `core.py:386-389` — Dead code in `trajectory_plan`

```python
sorted_trajectories = utilizations.sort_candidate_tracjectories(
    radiation_volume, candidate_trajectories)
# Further processing of candidate_trajectories is needed
pass
```

The sorted trajectories are computed but never used. The function ends with
`pass` and returns `None`. This appears to be an incomplete implementation of
trajectory optimization — the most promising trajectories are identified but
never selected or applied.

**Severity: HIGH** — The function is dead code, but it signals that trajectory
optimization was planned but never delivered. If this code path is ever
activated, it silently does nothing.

### H2. `exp.py` vs `external_exp.py` — ~99% identical, ~1300 lines each

These two files are near-identical duplicates. The only meaningful difference:
- `exp.py` calls `core.optimal_plan(...)` (rule-based) and saves to `./exp/comparison/`
- `external_exp.py` calls `core.optimal_plan_rf(...)` (RL-based) and saves to `./output_rf_msd/`

Every other function (`sensitivity_k`, `sensitivity_e`, `ablation_study`,
`robustness_study1`, `robustness_study2`, `calculate_metric`,
`find_latest_dose_file`, `NumpyEncoder`, `comparison`) is copied verbatim.

**Impact:** Any bug fix or enhancement must be applied to both files
independently. They will diverge over time. ~50% of the codebase's top-level
scripts is duplicated.

**Recommendation:** Extract common functions into a shared module (e.g.,
`exp_utils.py`) and have both files import from it. Keep only the
optimization-strategy-specific call in each file.

**Severity: HIGH** — Maintenance liability.

---

## MEDIUM-SEVERITY ISSUES

### M1. `utilizations.py:558` — Hardcoded resampling to [128,128,128]

```python
def ImageResample_size(sitk_image, new_size=[128, 128, 128], is_label=False):
```

`read_nii_image` (line 224) calls `ImageResample_size(sitk.ReadImage(path))`
with no `new_size` argument, so every loaded image is unconditionally resampled
to 128³ voxels. This discards spatial detail in high-resolution volumes and
unnecessarily upsamples low-resolution volumes.

**Impact:** Downstream dose calculations operate on a fixed grid regardless of
the original imaging protocol. Needle placement optimization loses accuracy for
high-resolution inputs.

**Severity: MEDIUM** — Functional limitation.

### M2. `fitting_model.py:30,61` — Parameter named `search_region` used as scaling weight

```python
self.weight = search_region   # line 30
...
sigmoid_normalized = torch.clamp(
    self.weight * (2 * torch.sigmoid(out[even_mask]) - 1) + x[even_mask], 0, 1)   # line 61
```

The constructor parameter `search_region` suggests a spatial extent or range,
but it is used as a linear gain on a sigmoid-transformed activation. This makes
the code misleading to readers.

**Severity: MEDIUM** — Poor naming obscures intent.

### M3. `data_preprocess.py:312-313` — Gaussian smoothing after morphological operations

```python
if self.gaussian_sigma > 0:
    binary = (gaussian_filter(binary.astype(np.float64), sigma=self.gaussian_sigma) > 0.5).astype(np.uint8)
```

Gaussian smoothing is applied after erosion and dilation. Since morphological
operations produce crisp binary boundaries, the subsequent blur (even with
`> 0.5` re-thresholding) can shift edges and re-introduce artifacts depending
on sigma.

**Severity: MEDIUM** — Mask quality may degrade; the order should be
reconsidered or documented.

### M4. `fitting_model.py:302-304` — Verbose matrix construction

```python
K = torch.stack([
    torch.stack([torch.tensor(0, device=self.device), -axis[2], axis[1]]),
    torch.stack([axis[2], torch.tensor(0, device=self.device), -axis[0]]),
    torch.stack([-axis[1], axis[0], torch.tensor(0, device=self.device)])
])
```

9 separate `torch.tensor`/`torch.stack` calls for a 3×3 skew-symmetric matrix.
The same file has a cleaner pattern at lines 168-172 using literal syntax.
This function is called once per seed in a loop (line 282).

**Severity: MEDIUM** — Readability and minor performance overhead.

---

## LOW-SEVERITY ISSUES

### L1. `brachy_plan.py:3` — `sys.path.append` mutates module search path

```python
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
```

Common pattern for entry-point scripts, but breaks when the file is imported as
part of a larger application (e.g., from `plans/`). Should use relative imports
or a proper package structure.

### L2. `core.py:330` — Unused variable `opt_DVH_rate`

```python
opt_DVH_rate = np.sum(opti_radiation * mask_volume > in_lowest_dose) / volume
return opti_planned_seeds, opti_single_seed_radiations
```

Computed but never referenced. Possibly a debugging remnant or incomplete
return value.

### L3. `brachy_plan.py:63` — Hardcoded reference direction

```python
ref_direc = np.array([0, 1, 0])  # Manually set direction if needed
```

The PCA-based anatomical direction calculation (commented out at lines 59-61)
is ignored in favor of a hardcoded `[0, 1, 0]` (anterior). This is incorrect
for non-prostate sites or non-supine patient orientations.

### L4. `fitting_model.py:157,291` — Hardcoded 0.99 alignment threshold

```python
if torch.abs(torch.dot(x_axis, direction)) >= 0.99:
    rotation_matrix = torch.eye(3, device=self.device)
```

The threshold `0.99` (≈ cos(8°)) determines whether two vectors are aligned
enough to skip rotation. Directions near this boundary may produce
discontinuous behavior. Should be a named constant.

---

## Summary

| ID | File | Line(s) | Severity | Description |
|----|------|---------|----------|-------------|
| C1 | `reinforcement.py` | 40, 285-286, 741 | CRITICAL | Inverted OAR damage formula |
| C2 | `reinforcement.py` | 67,79,122,191,205,255 | CRITICAL | Typo `target_valueimage_normalize_max` |
| C3 | `reinforcement.py` | 842 | CRITICAL | Wrong denominator in OAR penalty |
| H1 | `core.py` | 386-389 | HIGH | Dead code in `trajectory_plan` |
| H2 | `exp.py` / `external_exp.py` | — | HIGH | ~1300-line duplicate (~99% identical) |
| M1 | `utilizations.py` | 558 | MEDIUM | Hardcoded resampling to 128³ |
| M2 | `fitting_model.py` | 30,61 | MEDIUM | `search_region` used as weight |
| M3 | `data_preprocess.py` | 312-313 | MEDIUM | Gaussian after morphological ops |
| M4 | `fitting_model.py` | 302-304 | MEDIUM | Verbose matrix construction |
| L1 | `brachy_plan.py` | 3 | LOW | `sys.path.append` |
| L2 | `core.py` | 330 | LOW | Unused `opt_DVH_rate` |
| L3 | `brachy_plan.py` | 63 | LOW | Hardcoded `ref_direc` |
| L4 | `fitting_model.py` | 157,291 | LOW | Hardcoded 0.99 threshold |

**Not confirmed after verification (from initial report):** 7 items were
either wrong file/line numbers, already fixed, or false positives:
- `core.py:294-296` wrong function call arguments — function is dead code, no callers
- `core.py:447` wrong inequality — line does not exist in any relevant function
- `reinforcement.py:680` UnboundLocalError — `cur_DVH_rate = 0.0` already initialized
- `reinforcement.py:738` division by zero — guarded by `if exceed_count == 0`
- `geometry.py:937` 0.99 threshold — is in `fitting_model.py`, not `geometry.py`
- `utilizations.py:1011-1017` insertion sort off-by-one — no insertion sort exists
- `config.py:49-51,76` misleading help / unrealistic defaults — wrong locations

**Relationship to prior reviews:** This review covers the **algorithm core**
(`plans/` and root-level scripts) that was not examined in the
2026-07-06 modularization-focused review. The 5 should-fix items fixed in
commit `7cfd1d0` were in the web/agent layers and are unrelated to the
findings here.
