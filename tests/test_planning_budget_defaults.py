import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _rf_defaults(relative_path):
    with (ROOT / relative_path).open(encoding="utf-8") as stream:
        return json.load(stream)["rf_params"]


def test_planning_budget_defaults_are_consistent_across_config_entries():
    expected = {
        "max_episodes": 200,
        "dense_seed_limit": 40,
        "max_hierarchy_depth": 8,
        "max_actions_per_episode": 40,
        "max_wall_seconds": 300,
        "coverage_repair_seconds": 60,
    }
    for relative_path in ("plans/config.json", "config/default_params.json"):
        defaults = _rf_defaults(relative_path)
        assert {key: defaults.get(key) for key in expected} == expected
