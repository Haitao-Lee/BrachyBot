"""A/B compare the RL planner against the previous implementation.

Runs the synthetic planning case and reports neutral quality metrics
(coverage, OAR damage, seed/needle count, both objectives) plus wall time, so
"at least not worse" is measured rather than asserted.
"""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import torch
import SimpleITK as sitk
from plans import core
from plans.reward_metrics import normalized_oar_damage

GRID = (20, 20, 28)
BLOB_PEAK = 20.0
BLOB_SIGMA2 = 12.0
IN_LOWEST = 5.0
OUT_HIGHEST = 8.0

DVH_TARGET = float(sys.argv[1]) if len(sys.argv) > 1 else 0.95
SEEDS = [0, 1, 2]


def _blob(seed_point):
    seed_point = np.asarray(seed_point, dtype=np.float32).reshape(-1)
    zz, yy, xx = np.meshgrid(
        np.arange(GRID[0], dtype=np.float32),
        np.arange(GRID[1], dtype=np.float32),
        np.arange(GRID[2], dtype=np.float32),
        indexing="ij",
    )
    d2 = (zz - seed_point[0]) ** 2 + (yy - seed_point[1]) ** 2 + (xx - seed_point[2]) ** 2
    return (BLOB_PEAK * np.exp(-d2 / BLOB_SIGMA2)).astype(np.float32)


def _fake_single(pos, *args, **kwargs):
    return _blob(pos)


def _fake_batch(seeds, *args, **kwargs):
    return [_blob(seed[0]) for seed in seeds]


def _synthetic_case():
    zz, yy, xx = np.meshgrid(
        np.arange(GRID[0], dtype=np.float32),
        np.arange(GRID[1], dtype=np.float32),
        np.arange(GRID[2], dtype=np.float32),
        indexing="ij",
    )
    # Two separate lobes 6 mm apart: one needle can never cover both, so the
    # multi-needle hierarchy path is structurally mandatory and comparable.
    lobe_a = (((zz - 10.0) / 5.0) ** 2 + ((yy - 7.0) / 2.5) ** 2 + ((xx - 14.0) / 2.5) ** 2) <= 1.0
    lobe_b = (((zz - 10.0) / 5.0) ** 2 + ((yy - 13.0) / 2.5) ** 2 + ((xx - 14.0) / 2.5) ** 2) <= 1.0
    radiation_volume = np.zeros(GRID, dtype=np.int16)
    radiation_volume[lobe_a | lobe_b] = 1
    image = sitk.GetImageFromArray(np.zeros(GRID, dtype=np.float32))
    image.SetSpacing((1.0, 1.0, 1.0))
    image.SetOrigin((0.0, 0.0, 0.0))
    trajectories = []
    for y in (7.0, 13.0):
        point = np.array([3.0, y, 14.0])
        direction = np.array([1.0, 0.0, 0.0])
        trajectories.append((point, direction, [14], [0]))
    return image, radiation_volume, trajectories


def plan_objective(coverage, oar_damage, seed_count, needle_count, target_coverage):
    """Neutral objective, inlined so both revisions can be scored identically."""
    met = coverage >= target_coverage
    value = min(coverage, target_coverage)
    value += (1.0 - oar_damage + 2.0) * (1.0 if met else 0.0)
    value -= 2e-3 * oar_damage * (0.0 if met else 1.0)
    costs = 3e-4 * seed_count + 2e-3 * needle_count
    value -= costs * (1.0 if met else 0.02)
    return value


def metrics(plan):
    image, radiation_volume, _ = _synthetic_case()
    total = np.zeros(GRID, dtype=np.float32)
    seeds = 0
    needles = 0
    for entry in plan:
        maps = entry[2] or []
        entry_seeds = entry[1] or []
        n = len(entry_seeds) if entry_seeds else len(maps)
        seeds += n
        if n:
            needles += 1
        for dose in maps:
            total += np.asarray(dose, dtype=np.float32)
    target_mask = radiation_volume == 1
    target_count = int(np.count_nonzero(target_mask))
    coverage = float(np.count_nonzero(total[target_mask] > IN_LOWEST)) / max(1, target_count)
    damage = normalized_oar_damage(
        int(np.count_nonzero(total[~target_mask] > OUT_HIGHEST)), target_count)
    return {
        "coverage": round(coverage, 4),
        "oar_damage": round(damage, 4),
        "seeds": seeds,
        "needles": needles,
        "objective_new": round(plan_objective(coverage, damage, seeds, needles, DVH_TARGET), 4),
        "objective_old": round(
            min(coverage, DVH_TARGET) + (coverage >= DVH_TARGET) * (1.0 - damage), 4),
    }


def run_once(seed):
    image, radiation_volume, trajectories = _synthetic_case()
    params = {
        "lr": 0.01,
        "gamma": 0.9,
        "max_episodes": 24,
        "bandwidth": 8,
        "hierarchical_optimization": True,
        "segmented_rewards": True,
        "candidate_limit": 10,
        "dense_seed_limit": 10,
        "max_hierarchy_depth": 3,
        "max_actions_per_episode": 12,
        "max_wall_seconds": 60,
        "random_seed": seed,
    }
    started = time.perf_counter()
    with patch("plans.utilizations.single_seed_dose_calculation_dl", side_effect=_fake_single), \
         patch("plans.utilizations.batch_seed_dose_calculation_dl", side_effect=_fake_batch):
        try:
            plan = core.optimal_plan_rf(
                init_trajectories=trajectories,
                radiation_volume=radiation_volume,
                dose_image=image,
                dose_cal_model=torch.nn.Linear(1, 1),
                dl_params={},
                rf_params=params,
                interval_rate=2,
                target_value=1,
                infer_img_size=(8, 8, 8),
                in_lowest_dose=IN_LOWEST,
                out_highest_dose=OUT_HIGHEST,
                DVH_rate=DVH_TARGET,
                seed_info={"radius": 0.4, "length": 3.0, "margin_rate": 1.0},
                image_normalize_min=-1000.0,
                image_normalize_max=3000.0,
                image_normalize_scale=255.0,
                parallel_min_distance_mm=0.5,
                parallel_angle_tolerance_deg=5.0,
            )
        except Exception as exc:
            return {"success": False, "error": f"{type(exc).__name__}: {exc}",
                    "seconds": round(time.perf_counter() - started, 2)}
    elapsed = round(time.perf_counter() - started, 2)
    if not plan:
        return {"success": False, "error": "empty plan", "seconds": elapsed}
    result = metrics(plan)
    result.update(success=True, seconds=elapsed)
    return result


if __name__ == "__main__":
    label = sys.argv[2] if len(sys.argv) > 2 else "run"
    out = {"label": label, "dvh_target": DVH_TARGET, "runs": []}
    for seed in SEEDS:
        out["runs"].append(run_once(seed))
    successes = [r for r in out["runs"] if r.get("success")]
    if successes:
        out["mean"] = {
            key: round(float(np.mean([r[key] for r in successes])), 4)
            for key in ("coverage", "oar_damage", "seeds", "needles",
                        "objective_new", "objective_old", "seconds")
        }
        out["success_rate"] = f"{len(successes)}/{len(SEEDS)}"
    print(json.dumps(out, indent=1))
