"""Execute isolated production budget/diagnostic paths without GPU imports."""
import ast
from pathlib import Path
from types import SimpleNamespace
import math
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_budget():
    path = ROOT / 'tool_factory/seed_plan/planning_pipeline.py'
    tree = ast.parse(path.read_text())
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name in {'_finite_number', '_rule_based_deadline'}]
    scope = {'np': SimpleNamespace(isfinite=math.isfinite),
             'time': SimpleNamespace(monotonic=lambda: 1000)}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), scope)
    return scope['_rule_based_deadline']


@pytest.mark.parametrize('params', [{}, {'max_wall_seconds': 300},
    {'max_wall_seconds': 1, 'rule_based_max_wall_seconds': 0}])
def test_rl_budget_never_truncates_normal_rule_search(params):
    assert load_budget()(params) is None


def test_explicit_rule_budget_is_independent():
    assert load_budget()({'max_wall_seconds': 1, 'rule_based_max_wall_seconds': 1200}) == 2200


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), 'bad', 86401])
def test_invalid_explicit_budget_fails_closed(value):
    with pytest.raises(ValueError):
        load_budget()({'rule_based_max_wall_seconds': value})


@pytest.mark.parametrize('prior,deadline,expected', [
    ('wall_clock_budget', 900, 'wall_clock_budget'),
    ('dose_inference_deadline', None, 'dose_inference_deadline'),
    (None, 900, 'wall_clock_budget'),
    (None, 1100, 'no_available_action'),
])
def test_empty_rl_hierarchy_preserves_timeout_cause(prior, deadline, expected):
    path = ROOT / 'plans/utilizations.py'
    tree = ast.parse(path.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'hierarchical_planning_rf')
    block = next(n for n in fn.body if isinstance(n, ast.If)
                 and 'not hierarchical_available_traj_with_seeds' in ast.unparse(n.test))
    wrapper = ast.parse('def run():\n    pass').body[0]
    wrapper.body = [block]
    status = {'_stop_reason': prior}
    def outcome(s, **kw):
        s['_stop_reason'] = kw['stop_reason']
    def finish(*args, **kw):
        return kw.get('stop_reason') or status['_stop_reason']
    scope = dict(hierarchical_available_traj_with_seeds=[], rl_status=status,
                 deadline=deadline, time=SimpleNamespace(monotonic=lambda: 1000),
                 np=SimpleNamespace(inf=float('inf')), _finish=finish, set_outcome=outcome)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])), str(path), 'exec'), scope)
    assert scope['run']() == expected
