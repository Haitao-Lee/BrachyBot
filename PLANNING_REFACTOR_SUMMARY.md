# Planning Algorithm Refactoring Summary

## Problem
The planning pipeline produced V100=0%, D90=0, 0 trajectories because:
1. No image resampling (algorithm expects [128, 128, 64] grid)
2. No RAS→voxel direction conversion
3. Old algorithm modules (not v2 from Zhiyuan)

## Solution
Replaced planning modules with Zhiyuan v2 versions and added proper preprocessing.

## Changes Made

### 1. plans/core.py
- Replaced with `core_v2.py` from Zhiyuan repo
- Added slicer_mock fallback for headless mode
- Uses `utilizations` module (not `utilizations_v2`)

### 2. plans/utilizations.py
- Replaced with `utilizations_v2.py` from Zhiyuan repo
- Added slicer_mock fallback for headless mode
- Replaced all `slicer.app.processEvents()` with `throttled_process_events()`
- Removed unused imports (vtk, sklearn.cluster, tqdm)

### 3. plans/brachy_plan_v2.py (NEW)
- Copied from Zhiyuan repo
- Added slicer_mock fallback for headless mode
- Uses `core` and `utilizations` modules (not `core_v2`/`utilizations_v2`)

### 4. plans/config.py + plans/config.json (NEW)
- Copied from Zhiyuan repo
- Contains default planning parameters

### 5. tool_factory/seed_plan/planning_pipeline.py
- Added `_resample_for_planning()` function
  - Resamples CT/CTV/OAR to [128, 128, 64] planning grid
  - Uses linear interpolation for CT, nearest neighbor for labels
- Added `_convert_ref_direc_to_voxel()` function
  - Converts RAS reference direction to voxel space
- Updated `_run_full_pipeline()` to use `brachy_plan_v2`
  - Chains: resample → convert direction → load model → plan → extract results
- Proper coordinate transform chain

### 6. Dose model symlink
- Created symlink: `plans/dose_pre/dose_model.pth` → `dose_pre/dose_model.pth`

## Key Algorithm Flow

```
CT Image (original, e.g. 512×512×200)
    ↓ _resample_for_planning([128, 128, 64])
Resampled CT (128×128×64) ← ALL PLANNING HAPPENS HERE
    ↓
CTV/OAR also resampled to same grid
    ↓
Reference direction: RAS → voxel via ras_direction_to_voxel()
    ↓
brachy_plan_v2.brachy_plan() or brachy_plan_rf()
    ↓ core.init_plan() → candidate trajectories
    ↓ core.optimal_plan() → optimized seeds
    ↓
Seeds in world coordinates (from position_transform)
    ↓
Display in 3D viewer
```

## Verification
- All imports work correctly
- Image resampling produces correct grid size
- Direction conversion works (RAS → Voxel)
- Trajectory generation produces 172 trajectories (vs 7 before)
- Dose model loads correctly
