"""Exercise the initializer budget without loading the GPU dose model."""
import ast
from pathlib import Path
from types import SimpleNamespace
import time
import numpy as np


def namespace():
    source = Path(__file__).resolve().parents[1] / 'plans/core.py'
    tree = ast.parse(source.read_text())
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in ('sample_spatial_trajectories', 'init_plan')]
    env = {'np': np, 'time': time}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), env)
    return env


def test_budget_preserves_positions_and_directions():
    sample = namespace()['sample_spatial_trajectories']
    paths = [(np.array([x, y, 0]), np.array(d), [], [], 1)
             for d in ((1, 0, 1), (-1, 0, 1), (0, 1, 1), (0, -1, 1))
             for x in range(-20, 21) for y in range(-20, 21)]
    result = sample(paths, 500, (5, 0.7, 0.7))
    assert len(result) == 500
    assert len({id(t) for t in result}) == 500
    assert {tuple(t[1]) for t in result} == {tuple(t[1]) for t in paths}
    assert all(any(t[0][0] * sx > 10 and t[0][1] * sy > 10 for t in result)
               for sx in (-1, 1) for sy in (-1, 1))
    assert [id(t) for t in result] == [id(t) for t in sample(paths, 500, (5, 0.7, 0.7))]
    assert len(sample(paths, 1)) == 1
    assert sample([], 500) == []


def test_initializer_and_every_preview_respect_budget_after_filtering():
    env = namespace()
    previews = []
    points = np.array([[x, y, 0] for x in range(-15, 16) for y in range(-15, 16)])
    dirs = [np.array([1., 0, 1]), np.array([-1., 0, 1])]
    calls = []
    def close(*args):
        calls.append(args[-1])
        return points, 100
    env['utilizations'] = SimpleNamespace(
        get_cone=lambda *args: dirs,
        get_close_points=close,
        infer_body_mask_from_image=lambda image: None,
        infer_truncated_boundary_faces_from_image=lambda image: None,
        init_trajectories_with_depth=lambda pts, vol, d, *args: [
            (p, d, [], [], 10) for p in pts if p[0] != 0],
    )
    env['safe_preview'] = lambda callback, payload: callback(payload)
    env['_mock_progress'] = SimpleNamespace(setValue=lambda *a: None, setLabelText=lambda *a: None)
    result = env['init_plan'](SimpleNamespace(GetSpacing=lambda: (1, 1, 1)),
        np.zeros((1, 1, 1)), dirs[0], [1, 1, 2], 0.5, 2, 0, 3, 37,
        preview_callback=previews.append)
    assert len(result) == 37
    assert calls == [0.5]  # no cone shrinking
    assert all(len(p['trajectories']) <= 37 for p in previews)
    assert all(t[0][0] != 0 for t in result)
    assert len({tuple(t[1]) for t in result}) == 2
