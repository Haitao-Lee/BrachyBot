"""Budgeted residual-dose repair; public seed coordinates remain patient-world.

Geometry is supplied by the caller's authoritative safety validator. Coarse
distance scores only order trials; acceptance always uses full dose arrays.
"""
import time
import numpy as np


def dose_gain(dose, addition, target, organs, prescription, outside_limit):
    """Continuous deficit improvement with hotspot/normal-tissue penalties.

    These are optimization weights, not clinical organ tolerance thresholds.
    Normalize every term by target volume, so a large OAR cannot dilute cost.
    """
    if addition.shape != dose.shape or not np.all(np.isfinite(addition)) or np.any(addition < 0):
        return -np.inf
    scale = max(float(prescription), 1e-12)
    before, after = dose[target] / scale, (dose[target] + addition[target]) / scale
    gain = np.maximum(1 - before, 0).sum() - np.maximum(1 - after, 0).sum()
    hot = (np.maximum(after - 2, 0) - np.maximum(before - 2, 0)).sum()
    old = dose[organs]
    new = old + addition[organs]
    excess = (np.maximum(new - outside_limit, 0) - np.maximum(old - outside_limit, 0)).sum() / scale
    return float((gain - 0.05 * hot - excess) / max(1, target.sum()))


def repair_coverage(plan, candidates, volume, image, target_value, organs,
                    prescription, outside_limit, target_coverage, seed_info,
                    infer_dose, validate, generate=None, *, seconds=60.0,
                    rounds=3, shortlist=5, candidate_limit=500, clock=time.monotonic):
    from . import utilizations as util
    from .core import seed_plan_to_world_coordinates, sample_spatial_trajectories
    from scipy.ndimage import distance_transform_edt

    started = clock()
    deadline = started + max(0.0, float(seconds))
    # Copy mutable containers: a rejected/failed repair must not mutate the
    # caller's accepted plan while appending seeds to an existing needle.
    result = [[e[0], list(e[1]), list(e[2])] for e in plan]
    target = volume == target_value
    dose = np.zeros(volume.shape, dtype=np.float32)
    for entry in result:
        for contribution in entry[2]:
            dose += contribution
    coverage = lambda: float(np.mean(dose[target] > prescription)) if target.any() else 0.0
    info = dict(initial_coverage=coverage(), final_coverage=coverage(),
                trials=0, added_needles=0, added_seeds=0, generated=0, stop_reason='no_improvement')
    if not target.any() or coverage() >= target_coverage or seconds <= 0:
        info['stop_reason'] = 'target_reached' if target.any() and coverage() >= target_coverage else 'disabled_or_empty'
        return result, info
    spacing = np.asarray(image.GetSpacing()[::-1], dtype=float)
    distance = distance_transform_edt(target)
    pool = sample_spatial_trajectories(candidates, candidate_limit, spacing)
    generated_once = False
    available_cache = {}
    for iteration in range(rounds):
        if clock() >= deadline:
            info['stop_reason'] = 'time_budget'
            break
        if coverage() >= target_coverage:
            info['stop_reason'] = 'target_reached'
            break
        cold = np.argwhere(target & (dose <= prescription))
        if not len(cold):
            info['stop_reason'] = 'no_residual'
            break
        # Deterministic distributed samples; the actual acceptance is full-grid.
        cold = cold[np.linspace(0, len(cold) - 1, min(256, len(cold)), dtype=int)]
        residual = np.maximum(0, 1 - dose[tuple(cold.T)] / prescription)
        # Targeted paths must compete before the budget is consumed by paths
        # which already cover the warm part of the target.
        if generate is not None and not generated_once and clock() < deadline:
            generated_once = True
            extra = list(generate(cold, min(deadline, clock() + max(0.1, seconds * 0.2))))
            info['generated'] += len(extra)
            extra = sample_spatial_trajectories(extra, min(48, candidate_limit), spacing)
            pool = (sample_spatial_trajectories(pool, candidate_limit-len(extra), spacing)
                    if len(extra) < candidate_limit else []) + extra
        ranked = []
        def key(t):
            return (tuple(np.asarray(t[0])), tuple(np.asarray(t[1])))
        selected_keys = {key(e[0]): i for i, e in enumerate(result)}
        # Revisit existing needles as well: a single repair seed cannot fill
        # a long cold region, and its new needle excludes parallel neighbours.
        search_pool = list(pool)
        known = {key(t) for t in search_pool}
        search_pool.extend(e[0] for e in result if key(e[0]) not in known)
        for trajectory in search_pool:
            if clock() >= deadline:
                break
            owner = selected_keys.get(key(trajectory))
            placed = []
            if owner is not None:
                for p, d in result[owner][1]:
                    index = image.TransformPhysicalPointToContinuousIndex(tuple(float(v) for v in p))
                    placed.append((np.asarray(index[::-1]), trajectory[1]))
            cache_key = (key(trajectory), len(placed))
            if cache_key not in available_cache:
                available_cache[cache_key] = util.get_available_position(
                    trajectory, placed, seed_info, image, distance)
            available = available_cache[cache_key]
            if not available:
                continue
            direction = np.asarray(trajectory[1], dtype=float)
            advance = direction / np.max(np.abs(direction))
            steps = np.asarray(available)[np.linspace(0, len(available)-1, min(16, len(available)), dtype=int)]
            points = np.asarray(trajectory[0]) + steps[:, None] * advance
            if placed:
                # Also guard against stale/rounded candidate ranges returning
                # an already occupied position.
                occupied = np.asarray([p for p, _ in placed])
                keep = np.min(np.linalg.norm((points[:, None]-occupied[None])*spacing, axis=2), axis=1) >= float(seed_info['length']) - 1e-6
                points = points[keep]
                if not len(points):
                    continue
            squared = np.sum(((points[:, None] - cold[None]) * spacing)**2, axis=2)
            scores = np.exp(-squared / (2 * 5.0**2)) @ residual
            # A distance proxy can rank a hotspot/OAR-adjacent position first.
            # Keep a bounded set of alternatives on the same safe trajectory.
            for best in np.argsort(-scores, kind='stable')[:3]:
                ranked.append((float(scores[best]), trajectory, points[best], direction, owner))
        ranked.sort(key=lambda item: item[0], reverse=True)
        best_trial = None
        best_gain = 1e-6
        evaluated = 0
        for _, trajectory, point, direction, owner in ranked:
            if clock() >= deadline:
                break
            if not validate(trajectory, [entry[0] for i, entry in enumerate(result) if i != owner]):
                continue
            # Use precisely the same voxel position for inference and output.
            point = np.asarray(point, dtype=np.float64)
            addition = np.asarray(infer_dose(point, direction))
            info['trials'] += 1
            evaluated += 1
            gain = dose_gain(dose, addition, target, organs, prescription, outside_limit)
            if gain > best_gain:
                best_gain = gain
                best_trial = (trajectory, point, direction, addition, owner)
            # Coarse ranking is not an acceptance test. If its first few
            # suggestions fail, continue searching within the same deadline.
            if evaluated >= shortlist and best_trial is not None:
                break
        if best_trial is None:
            info['stop_reason'] = 'time_budget' if clock() >= deadline else 'no_safe_positive_gain'
            break
        trajectory, point, direction, addition, owner = best_trial
        new_entry = [trajectory, [(point, direction)], [addition]]
        converted = seed_plan_to_world_coordinates([new_entry], image)[0]
        if owner is None:
            result.append(converted)
            info['added_needles'] += 1
        else:
            result[owner][1].extend(converted[1])
            result[owner][2].extend(converted[2])
        dose += addition
        info['added_seeds'] += 1
        info['stop_reason'] = 'round_budget'
    info['final_coverage'] = coverage()
    if coverage() >= target_coverage:
        info['stop_reason'] = 'target_reached'
    info['elapsed_seconds'] = clock() - started
    return result, info
