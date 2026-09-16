"""Contracts around telemetry and immutable baseline dependencies."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.latency_dependency_guard import MODULE_PATHS, verify_dependencies

ROOT = Path(__file__).resolve().parents[1]


def test_performance_delivery_contains_baseline_runner_and_tests():
    required = (
        'plans/performance.py', 'tests/latency_reference.json',
        'tests/test_planning_latency_equivalence.py', 'tests/test_planning_latency_profile.py',
        'scripts/benchmark_planning_latency.py', 'scripts/latency_dependency_guard.py',
        'scripts/latency_comparison.py', 'docs/PLANNING_LATENCY_ANALYSIS_2026-09-15.md',
    )
    assert all((ROOT / name).is_file() for name in required)


def test_shared_helper_drift_fails_even_when_both_replay_sides_use_it(tmp_path):
    frozen = json.loads((ROOT / 'tests/latency_reference.json').read_text())
    for relative in MODULE_PATHS.values():
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text((ROOT / relative).read_text())
    path = tmp_path / MODULE_PATHS['utilizations']
    source = path.read_text()
    source = source.replace('def _refine_target_boundary(', 'def _refine_target_boundary_changed(', 1)
    path.write_text(source)
    with pytest.raises(AssertionError, match='Missing baseline dependency'):
        verify_dependencies(tmp_path, frozen)


def test_zero_trial_repair_reports_real_elapsed_not_allocated_quota():
    source = (ROOT / MODULE_PATHS['planning_pipeline']).read_text()
    node = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.FunctionDef) and n.name == '_run_repair_pass')
    args = SimpleNamespace(radiation_array_params={'target_value': 2, 'maximum_candidate_trajectories': 500},
                           DVH_rate=0.9, seed_info={})
    namespace = {name: None for name in ('trajectories', 'radiation_volume', 'dose_image', 'repair_organs',
                                       'in_lowest_model', 'out_highest_model', '_repair_infer',
                                       '_repair_validate', '_repair_generate')}
    ticks = iter((100.0, 100.002))
    namespace.update(args=args, time=SimpleNamespace(perf_counter=lambda: next(ticks)),
                     repair_coverage=lambda *a, **kw: ('unchanged', {'stop_reason': 'target_reached', 'trials': 0}))
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<repair-wrapper>', 'exec'), namespace)
    plan, status = namespace['_run_repair_pass']([], 60.0, 24)
    assert plan == 'unchanged'
    assert status['budget_allocated_seconds'] == 60.0
    assert status['elapsed_seconds'] == pytest.approx(0.002)


def test_both_final_geometry_checks_receive_same_local_faces():
    tree = ast.parse((ROOT / MODULE_PATHS['planning_pipeline']).read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == '_validated_needle_geometry']
    assert len(calls) == 2
    for call in calls:
        keyword = next(k for k in call.keywords if k.arg == 'truncated_boundary_faces')
        assert isinstance(keyword.value, ast.Name) and keyword.value.id == 'final_boundary_faces'
