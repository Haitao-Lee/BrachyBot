"""Per-track expansion specs (Track K/L/H/F thin-rail fill-out).

Each ``<track>_tasks.py`` module in this package defines ``TASKS``: a list of
entries ``{"task": <task schema doc>, "obs_pos": <positive obs>,
"obs_neg": <negative obs>, "coverage": {capability_id: {dim: [evidence]}}}``.
``tools/build_expansion.py`` turns them into ``tasks/*.json``,
``tests/replay/*.json`` (positive) and ``tests/replay/_negatives.json`` (negative),
so the auto quality machine (``tests/test_coverage_scenarios.py``) proves every
scenario is discriminating (safe -> Meets, unsafe -> Does not meet).
"""
