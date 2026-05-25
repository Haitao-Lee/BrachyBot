# BrachyPlan - OpenCode Agent Instructions

## Project Overview
Medical brachytherapy (radiation seed) planning system using AI/ML for optimized seed placement. Located at Ruijin Hospital for clinical validation.

## Key Entry Points
- `python brachy_plan_seedpromax.py` - Main advanced planning pipeline
- `python core.py` - Basic seed placement algorithm
- `python test_promax.py` - Run test suite

## Critical: Use Optimized (_promax) Modules
Original modules exist alongside optimized versions. Always prefer:
- `utilizations_promax.py` over `utilizations.py`
- `reinforcement_promax.py` over `reinforcement.py`
- `core_promax.py` over `core.py`

The promax versions include dose caching, vectorization, and float32 optimizations documented in `OPTIMIZATION_REPORT.md`.

## Configuration
`config.py` provides CLI arguments via `config.setting()`. Run with `--case_name`, `--dose_image_path`, `--target_image_path`, etc.

## Dependencies
Uses conda environment (see `.vscode/settings.json`). Key packages: SimpleITK, PyTorch, numpy.

## Tool Factory
`tool_factory/` contains modular tools (`seed_seg`, `traj_plan`, `dose_eval`, `OAR_seg`, `CTV_seg`) with standardized `BaseTool` interface.

## Data Paths
- `data/kits21/` - Kidney tumor segmentation (KiTS21 challenge)
- `data/AbdomenAtlas3/` - Abdomen atlas
- `data/PanTS/` - Pancreas tumor dataset

## Testing
Run tests via: `python test_promax.py`

## TOPAS Integration
Optional Monte Carlo validation via `TOPAS/topas/` (requires separate installation).

## Code Quality
No lint/typecheck tooling configured. Run tests to verify changes: `python test_promax.py`