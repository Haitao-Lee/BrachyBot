"""
Core planning algorithm v2 from Zhiyuan repo.
Adapted for BrachyBot headless mode.
"""
from . import utilizations
import numpy as np
import torch
import torch.nn as nn
from scipy.ndimage import distance_transform_edt
from . import visualizer
import copy
import traceback as _tb
import time

from .planning_preview import safe_preview

try:
    import slicer
except ImportError:
    from . import slicer_mock as slicer


class _MockProgressDialog:
    """No-op progress dialog for headless mode."""
    def setValue(self, v): pass
    def setLabelText(self, t): pass

_mock_progress = _MockProgressDialog()


def seed_plan_to_world_coordinates(plan_res, dose_image):
    """Convert a voxel-space seed plan to the public patient-world contract.

    The optimizer works in array-order planning-grid coordinates ``[z, y, x]``
    while the Viewer, manual-edit APIs, guide generation, and reports consume
    physical patient coordinates.  ``optimal_plan`` historically converted
    only its normal completion path, so an early return (for example when no
    further trajectory could improve coverage) leaked voxel coordinates.  That
    leak is especially dangerous because the values are finite and look like
    plausible 3-D points, but they are not in the same frame as the CT meshes.

    Keep this conversion at the algorithm boundary and apply it to every
    return path.  Dose arrays and trajectory metadata are intentionally kept
    unchanged; only each seed's position and direction are transformed.
    """
    if plan_res is None:
        return plan_res
    if dose_image is None:
        raise ValueError("dose_image is required to transform seed coordinates")

    def _convert_seed(seed):
        if isinstance(seed, dict):
            position = seed.get("position", seed.get("pos"))
            direction = seed.get("direction", seed.get("dir"))
            if position is None or direction is None:
                raise ValueError("seed record is missing position or direction")
            position = np.asarray(position, dtype=np.float64).reshape(-1)
            direction = np.asarray(direction, dtype=np.float64).reshape(-1)
            if position.size < 3 or direction.size < 3:
                raise ValueError("seed position/direction must contain 3 values")
            world_position = np.asarray(
                utilizations.position_transform(dose_image, position[:3])[0],
                dtype=np.float64,
            )
            world_direction = np.asarray(
                utilizations.direction_transform(dose_image, direction[:3]),
                dtype=np.float64,
            ).reshape(-1)[:3]
            converted = dict(seed)
            if "position" in converted or "pos" not in converted:
                converted["position"] = world_position
            if "pos" in converted:
                converted["pos"] = world_position
            if "direction" in converted or "dir" not in converted:
                converted["direction"] = world_direction
            if "dir" in converted:
                converted["dir"] = world_direction
            return converted

        if not isinstance(seed, (list, tuple)) or len(seed) < 2:
            raise ValueError("seed record must contain position and direction")
        position = np.asarray(seed[0], dtype=np.float64).reshape(-1)
        direction = np.asarray(seed[1], dtype=np.float64).reshape(-1)
        if position.size < 3 or direction.size < 3:
            raise ValueError("seed position/direction must contain 3 values")
        world_position = np.asarray(
            utilizations.position_transform(dose_image, position[:3])[0],
            dtype=np.float64,
        )
        world_direction = np.asarray(
            utilizations.direction_transform(dose_image, direction[:3]),
            dtype=np.float64,
        ).reshape(-1)[:3]
        return (world_position, world_direction)

    converted_plan = []
    for entry in plan_res:
        if isinstance(entry, dict):
            converted_entry = dict(entry)
            converted_entry["seeds"] = [
                _convert_seed(seed) for seed in (entry.get("seeds") or [])
            ]
            converted_plan.append(converted_entry)
            continue
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            converted_plan.append(entry)
            continue
        converted_entry = list(entry)
        converted_entry[1] = [
            _convert_seed(seed) for seed in (entry[1] or [])
        ]
        converted_plan.append(
            tuple(converted_entry) if isinstance(entry, tuple) else converted_entry
        )
    return converted_plan


def sample_spatial_trajectories(trajectories, limit, spacing=(1, 1, 1)):
    """Deterministic farthest-point sampling across physical positions AND directions.

    Planner coordinates are z,y,x. Normalize position by the overall diameter
    (not independently per axis) so anisotropic anatomy retains its geometry.
    Direction contributes on the same scale, preventing direction-major input
    ordering from concentrating all retained candidates in one cone sector.
    """
    limit = max(1, int(limit))
    if len(trajectories) <= limit:
        return list(trajectories)
    positions = np.asarray([t[0] for t in trajectories], dtype=float) * np.asarray(spacing)
    directions = np.asarray([t[1] for t in trajectories], dtype=float) * np.asarray(spacing)
    directions /= np.maximum(np.linalg.norm(directions, axis=1, keepdims=True), 1e-12)
    scale = max(float(np.linalg.norm(np.ptp(positions, axis=0))), 1e-12)
    features = np.column_stack(((positions - positions.mean(axis=0)) / scale, directions * 0.5))
    nearest = np.full(len(features), np.inf)
    index = int(np.argmax(np.sum((features - features.mean(axis=0)) ** 2, axis=1)))
    selected = []
    for _ in range(limit):
        selected.append(index)
        delta = features - features[index]
        nearest = np.minimum(nearest, np.einsum('ij,ij->i', delta, delta))
        nearest[selected] = -1
        index = int(np.argmax(nearest))
    return [trajectories[i] for i in selected]


def sample_anchor_covering_trajectories(trajectories, limit, spacing=(1, 1, 1)):
    """Keep at least one path for every sampled target-surface anchor.

    The candidate budget is a path budget, but spatial close-point coverage is
    the first requirement. A plain global farthest-point sampler can retain
    many directions at the same anchor and discard an entire target surface
    patch. This sampler first chooses one valid trajectory per anchor, then
    spends the remaining budget on spatial and directional diversity.
    """
    limit = max(1, int(limit))
    if len(trajectories) <= limit:
        return list(trajectories)

    groups = {}
    for index, trajectory in enumerate(trajectories):
        try:
            point = np.asarray(trajectory[0], dtype=np.float64).reshape(-1)
            if point.size < 3 or not np.all(np.isfinite(point[:3])):
                key = ("invalid", index)
            else:
                # Initializer points are on the planning voxel grid. Rounding
                # avoids splitting the same anchor because of float wrappers.
                key = tuple(np.rint(point[:3]).astype(np.int64).tolist())
        except Exception:
            key = ("invalid", index)
        groups.setdefault(key, []).append((index, trajectory))

    representatives = [members[0] for members in groups.values()]
    if len(representatives) > limit:
        # The budget is smaller than the number of anchors. At that point the
        # best possible contract is spatially uniform anchor selection while
        # retaining the direction feature in the sampler. Using only the first
        # path per anchor would make input order decide the direction and could
        # collapse the result to the first cone sector.
        return sample_spatial_trajectories(
            trajectories,
            limit,
            spacing,
        )

    representative_indices = {index for index, _trajectory in representatives}
    selected = [trajectory for _index, trajectory in representatives]
    remaining = [
        trajectory
        for index, trajectory in enumerate(trajectories)
        if index not in representative_indices
    ]
    if len(selected) < limit and remaining:
        selected.extend(
            sample_spatial_trajectories(
                remaining,
                limit - len(selected),
                spacing,
            )
        )
    return selected[:limit]


def init_plan(dose_image, radiation_volume, ref_direc, direc_resolution, extract_angle,
              target_value, background_value, obstacle_value, maximum_candidate_trajectories, progressDialog=None,
              min_depth=2, preview_callback=None, entry_body_mask=None,
              entry_boundary_faces=None):
    """
    Generate an initial set of candidate needle/catheter trajectories within a 3-D radiation volume.

    Workflow:
        1. Build a conical sampling grid around the reference direction.
        2. Extract candidate voxels that lie inside the cone and satisfy the target label.
        3. Initialise straight trajectories through those voxels and prune by minimum depth.
        4. (Optional) Sort or visualise results before returning.

    Parameters
    ----------
    dose_image : SimpleITK.Image
        Reference image providing voxel spacing and spatial metadata.
    radiation_volume : np.ndarray
        3-D label array (target, background, obstacle) used for geometric queries.
    ref_direc : np.ndarray, shape (3,)
        Unit vector that defines the central axis of the sampling cone.
    direc_resolution : list[float, float, int]
        [cone_half_angle, angular_step, n_rings] for direction sampling.
    extract_angle : float (radians)
        Half-angle of the cone inside which candidate voxels are collected.
    target_value : float
        Label value that identifies the target region.
    background_value : float
        Label value that identifies non-target soft tissue.
    obstacle_value : float
        Label value that identifies organs-at-risk or hard obstacles.
    maximum_candidate_trajectories : int
        Upper bound on the total number of trajectories to be generated.
    min_depth : float, optional
        Minimum path length (mm) required for a trajectory to be considered valid.
    entry_body_mask : np.ndarray, optional
        Boolean body envelope on the same ``[z, y, x]`` grid as
        ``radiation_volume``.  When supplied (or inferred from ``dose_image``),
        candidates whose reverse ray reaches an image boundary before leaving
        the body are rejected during initialization.  This prevents CT
        truncation faces from becoming needle entry points.
    entry_boundary_faces : sequence[bool], optional
        CT face flags in planner array order ``(z_min, z_max, y_min, y_max,
        x_min, x_max)``.  A body-to-air transition on a flagged face is not a
        real skin entry.  When omitted, the flags are inferred from
        ``dose_image``.

    Returns
    -------
    list[tuple]
        List of valid trajectories. Each tuple contains:
        (origin_voxel, direction_vector, depth, ...metadata...)
        Ready for downstream optimisation or refinement.
    """
    if progressDialog is None:
        progressDialog = _mock_progress

    # ``dose_image`` is the resampled CT in the production pipeline.  Infer a
    # body envelope when callers do not provide one so the standalone
    # trajectory tool follows the same entry-point contract as full planning.
    if entry_body_mask is None:
        entry_body_mask = utilizations.infer_body_mask_from_image(dose_image)
    if entry_boundary_faces is None:
        entry_boundary_faces = utilizations.infer_truncated_boundary_faces_from_image(
            dose_image
        )
    if entry_body_mask is not None:
        entry_body_mask = np.asarray(entry_body_mask, dtype=bool)
        if entry_body_mask.shape != np.asarray(radiation_volume).shape:
            raise ValueError(
                "entry_body_mask must have the same shape as radiation_volume"
            )

    # ---- 1.  Build conical direction grid ----
    candidate_dirs = utilizations.get_cone(
        ref_direc, direc_resolution[0], direc_resolution[1], direc_resolution[2]
    )

    progressDialog.setValue(35)
    progressDialog.setLabelText("Initial Planning...")

    # ---- 2.  Build a shared, surface-covering close-point set ----
    candidate_limit = max(1, int(maximum_candidate_trajectories))
    sampling_spacing = tuple(reversed(dose_image.GetSpacing())) if hasattr(dose_image, 'GetSpacing') else (1, 1, 1)
    shared_sampler = getattr(
        utilizations,
        "get_shared_close_points_for_directions",
        None,
    )
    has_physical_image_geometry = all(
        hasattr(dose_image, name)
        for name in ("GetSize", "GetDirection", "GetOrigin", "GetSpacing")
    )
    close_point_stats = {}
    if callable(shared_sampler) and has_physical_image_geometry:
        close_points, direction_lengths, close_point_stats = shared_sampler(
            dose_image,
            radiation_volume,
            candidate_dirs,
            target_value,
            extract_angle,
            max_surface_points=min(256, candidate_limit),
            surface_spacing_mm=2.5,
        )
    else:
        # Preserve the lightweight/legacy integration contract used by tools
        # that provide only a minimal image stub. Production SimpleITK images
        # always take the shared direction-conditioned path above.
        close_points, max_length = utilizations.get_close_points(
            dose_image, radiation_volume, ref_direc, target_value, extract_angle
        )
        direction_lengths = [max_length] * len(candidate_dirs)

    progressDialog.setValue(40)
    progressDialog.setLabelText("Initial Planning...")

    # Keep the full spatial cone. Apply the budget after entry/depth/obstacle
    # validation, so invalid paths cannot consume slots or bias the sampling.

    # ---- 3.  Initialise trajectories with depth filter ----
    init_trajectories = []
    entry_rejected = 0
    last_preview_at = 0.0
    for i, direc in enumerate(candidate_dirs):
        progressDialog.setValue(45)
        progressDialog.setLabelText("Initial Planning...")
        direction_points = close_points
        max_length = (
            direction_lengths[i]
            if i < len(direction_lengths)
            else (direction_lengths[0] if direction_lengths else 0.0)
        )
        if entry_body_mask is not None:
            direction_points, rejected = utilizations.filter_trajectory_entry_points(
                close_points,
                direc,
                entry_body_mask,
                truncated_boundary_faces=entry_boundary_faces,
            )
            entry_rejected += int(rejected)
        if entry_body_mask is None:
            # Preserve the historical positional call contract for light-
            # weight integrations that monkeypatch this utility.
            traj_list = utilizations.init_trajectories_with_depth(
                direction_points,
                radiation_volume,
                direc,
                target_value,
                background_value,
                obstacle_value,
                min_depth,
                max_length,
            )
        else:
            # Keep the guard inside the utility as well: other callers can
            # invoke ``init_trajectories_with_depth`` directly, while this
            # pre-filter ensures invalid paths never enter the initializer's
            # candidate list or live preview.
            traj_list = utilizations.init_trajectories_with_depth(
                direction_points,
                radiation_volume,
                direc,
                target_value,
                background_value,
                obstacle_value,
                min_depth,
                max_length,
                entry_body_mask=entry_body_mask,
                truncated_boundary_faces=entry_boundary_faces,
            )
        # Keep all valid anchors for each direction until the final
        # surface-covering sampler. Applying the global path budget here would
        # let several directions select the same anchors and could remove an
        # entire surface patch before the anchor coverage pass sees it.
        init_trajectories += sample_spatial_trajectories(
            traj_list,
            max(1, len(close_points)),
            sampling_spacing,
        )

        now = time.monotonic()
        if preview_callback is not None and now - last_preview_at >= 0.20:
            last_preview_at = now
            preview_sampler = globals().get(
                "sample_anchor_covering_trajectories",
                sample_spatial_trajectories,
            )
            preview = preview_sampler(
                init_trajectories,
                candidate_limit,
                sampling_spacing,
            )
            safe_preview(preview_callback, {
                "phase": "candidate_generation",
                "current": i + 1,
                "total": len(candidate_dirs),
                "trajectories": preview,
                "close_points": close_points,
                "detail": (
                    f"{len(preview)} surface-covering candidate paths "
                    f"(limit {candidate_limit}; directions {len(candidate_dirs)}; "
                    f"close points {close_point_stats.get('selected_points', len(close_points))})"
                ),
            })

    final_sampler = globals().get(
        "sample_anchor_covering_trajectories",
        sample_spatial_trajectories,
    )
    init_trajectories = final_sampler(
        init_trajectories,
        candidate_limit,
        sampling_spacing,
    )
    safe_preview(preview_callback, {
        "phase": "candidate_generation",
        "current": len(candidate_dirs),
        "total": len(candidate_dirs),
        "trajectories": init_trajectories,
        "close_points": close_points,
        "detail": (
            f"{len(init_trajectories)} surface-covering candidate paths"
            f"; directions={len(candidate_dirs)}"
            f"; close_points={close_point_stats.get('selected_points', len(close_points))}"
            + (f"; {entry_rejected} invalid CT-entry paths rejected" if entry_rejected else "")
        ),
        "force": True,
    })

    return init_trajectories


def optimal_plan(init_trajectories, radiation_volume, dose_image, dose_cal_model, dl_params, lower_bound, upper_bound, distance_rate,
                 target_value, background_value, obstacle_value, infer_img_size, in_lowest_dose, out_highest_dose,
                 DVH_rate, seed_info, iter_rate, image_normalize_min, image_normalize_max, image_normalize_scale,
                 progressDialog=None, parallel_min_distance_mm=None,
                 parallel_angle_tolerance_deg=None, preview_callback=None, deadline=None):
    """
    Generate an optimized radiation treatment plan by selecting seed trajectories, placing seeds, and refining the plan
    to ensure effective tumor coverage while minimizing radiation exposure to healthy tissues.

    Stages:
        1. **Trajectory Selection and Initial Planning**: Iteratively select optimal trajectories and place seeds to achieve the target DVH rate.
        2. **Plan Refinement**: Remove ineffective seeds, refine trajectory placements, and ensure adequate radiation coverage.
        3. **Fine-tuning for Safety**: Adjust seed placements iteratively to minimize excessive radiation exposure to healthy tissue regions.
    """
    if progressDialog is None:
        progressDialog = _mock_progress

    # --- Initialize Variables ---
    candidate_trajectories = copy.deepcopy(init_trajectories)
    init_planned_res = []
    cur_DVH_rate = 0
    cur_radiation = np.zeros_like(radiation_volume).astype(float)
    distance_map = distance_transform_edt((radiation_volume == target_value))

    dose_context = utilizations.DoseImageContext(
        dose_image, image_normalize_min, image_normalize_max, dose_cal_model
    )
    last_preview_at = 0.0

    def _deadline_expired():
        return deadline is not None and time.monotonic() >= float(deadline)

    def _emit_plan_preview(plan, phase, iteration, coverage=None, force=False):
        nonlocal last_preview_at
        now = time.monotonic()
        if not force and now - last_preview_at < 0.20:
            return
        last_preview_at = now
        safe_preview(preview_callback, {
            "phase": phase,
            "iteration": iteration,
            "coverage": coverage,
            "coordinate_space": "voxel",
            "plan": plan,
            "force": bool(force),
        })

    # --- Stage 1: Trajectory Selection and Initial Planning ---
    selected_indices = []
    stage1_count = 0
    import logging as _log
    _logger = _log.getLogger(__name__)
    _logger.info(f"[optimal_plan] Start: {len(candidate_trajectories)} candidates, DVH_rate={DVH_rate}, cur_DVH={cur_DVH_rate}")
    if len(candidate_trajectories) == 0:
        _logger.warning(f"[optimal_plan] 0 candidates! radiation_volume target_voxels={int(np.sum(radiation_volume == target_value))}, dose_image type={type(dose_image).__name__}")
    while cur_DVH_rate < DVH_rate:
        if _deadline_expired():
            _logger.info("[optimal_plan] deadline reached during Stage 1")
            break
        stage1_count += 1
        if stage1_count > min(100, len(candidate_trajectories)):
            break
        progressDialog.setValue(50)
        progressDialog.setLabelText("Optimal Planning...")

        optimal_trajectory, selected_idx = utilizations.select_optimal_trajectory(
            candidate_trajectories,
            [traj for traj, _, _ in init_planned_res],
            cur_radiation,
            dose_image,
            lower_bound,
            upper_bound,
            distance_rate,
            in_lowest_dose,
            distance_map,
            seed_info,
            selected_indices,
            parallel_min_distance_mm=parallel_min_distance_mm,
            parallel_angle_tolerance_deg=parallel_angle_tolerance_deg,
        )
        if optimal_trajectory is None:
            _logger.info(f"[optimal_plan] select_optimal_trajectory returned None at iteration {stage1_count}, {len(init_planned_res)} trajectories planned")
            break
        selected_indices.append(selected_idx)
        optimal_seeds, cur_DVH_rate, cur_single_seed_radiations = utilizations.put_seeds(
            radiation_volume,
            dose_image,
            dose_cal_model,
            infer_img_size,
            cur_radiation,
            target_value,
            in_lowest_dose,
            optimal_trajectory,
            seed_info,
            DVH_rate,
            distance_map,
            image_normalize_min,
            image_normalize_max,
            image_normalize_scale,
            dose_context=dose_context, deadline=deadline
        )

        if len(optimal_seeds) == 0:
            _logger.info(f"[optimal_plan] put_seeds returned 0 seeds at iteration {stage1_count}, trajectory={optimal_trajectory[0][:3] if optimal_trajectory else 'None'}")
            continue

        init_planned_res.append([optimal_trajectory, optimal_seeds, cur_single_seed_radiations])
        cur_radiation += np.sum(cur_single_seed_radiations, axis=0)
        _emit_plan_preview(
            init_planned_res,
            "trajectory_and_seed_addition",
            stage1_count,
            cur_DVH_rate,
        )

    if not init_planned_res:
        return []

    # --- Stage 2: Plan Refinement ---
    minus_res = copy.copy(init_planned_res)
    for i in range(len(minus_res)):
        minus_res[i] = [minus_res[i][0], [], []]

    cur_DVH_rate = 0
    minus_radiation = np.zeros_like(radiation_volume)
    # Stage 2 evaluates a full dose-model sweep for every replan attempt.
    # Keep the loop finite even when the target is unreachable or a candidate
    # is reported as successful without improving the coverage metric.
    max_stage2_iterations = 100
    stage2_iterations = 0

    progressDialog.setValue(55)
    progressDialog.setLabelText("Optimal Planning...")

    while cur_DVH_rate < DVH_rate:
        if _deadline_expired():
            _logger.info("[optimal_plan] deadline reached during Stage 2")
            break
        stage2_iterations += 1
        if stage2_iterations > max_stage2_iterations:
            _logger.warning(
                "[optimal_plan] Stage 2 reached the iteration cap (%d) "
                "with DVH=%.4f/%.4f; returning the best plan found",
                max_stage2_iterations,
                cur_DVH_rate,
                DVH_rate,
            )
            break
        previous_DVH_rate = cur_DVH_rate
        try:
            minus_res, updated_DVH_rate, minus_radiation, sign = utilizations.replan(
                minus_res,
                radiation_volume,
                minus_radiation,
                dose_image,
                dose_cal_model,
                infer_img_size,
                in_lowest_dose,
                target_value,
                background_value,
                obstacle_value,
                seed_info,
                distance_map,
                image_normalize_min,
                image_normalize_max,
                image_normalize_scale,
                dose_context=dose_context, deadline=deadline
            )
        except Exception as e:
            minus_res = copy.deepcopy(init_planned_res)
            minus_radiation = cur_radiation
            break
        if sign:
            cur_DVH_rate = updated_DVH_rate
            _emit_plan_preview(
                minus_res,
                "coverage_refinement",
                stage2_iterations,
                cur_DVH_rate,
            )
            if cur_DVH_rate <= previous_DVH_rate + 1e-6:
                _logger.warning(
                    "[optimal_plan] Stage 2 stopped after no measurable DVH "
                    "improvement (%.4f -> %.4f)",
                    previous_DVH_rate,
                    cur_DVH_rate,
                )
                break
        else:
            minus_res = copy.deepcopy(init_planned_res)
            minus_radiation = cur_radiation
            break

        progressDialog.setValue(55)
        progressDialog.setLabelText("Optimal Planning...")

    # A stalled rebuilding sweep must not replace a better complete seed set.
    target_mask = radiation_volume == target_value
    if np.count_nonzero(minus_radiation[target_mask] > in_lowest_dose) < np.count_nonzero(cur_radiation[target_mask] > in_lowest_dose):
        minus_res = copy.deepcopy(init_planned_res)
        minus_radiation = cur_radiation.copy()

    # --- Stage 3: Fine-tuning for Safety ---
    opti_res = copy.deepcopy(minus_res)
    all_seeds = []
    for _, (_, seeds, _) in enumerate(opti_res):
        all_seeds.extend(seeds)
    opti_radiation = copy.deepcopy(minus_radiation)
    iter_count = 0
    seed_num = sum(len(seeds) for _, seeds, _ in minus_res)

    consecutive_no_improvement = 0
    max_no_improvement = seed_num

    while iter_count < iter_rate * seed_num:
        if _deadline_expired():
            _logger.info("[optimal_plan] deadline reached during Stage 3")
            break
        progressDialog.setValue(60)
        progressDialog.setLabelText("Optimal Planning...")
        rest_res, rest_radiation = utilizations.remove_seed_sequentially(
            opti_res,
            all_seeds,
            iter_count % seed_num,
            opti_radiation,
        )

        try:
            add_res, add_radiation, sign = utilizations.add_proper_seed(
                rest_res,
                radiation_volume,
                rest_radiation,
                dose_image,
                dose_cal_model,
                infer_img_size,
                in_lowest_dose,
                out_highest_dose,
                target_value,
                background_value,
                obstacle_value,
                DVH_rate,
                seed_info,
                distance_map,
                image_normalize_min,
                image_normalize_max,
                image_normalize_scale,
                dose_context=dose_context, deadline=deadline
            )
        except Exception as e:
            sign = False
            add_res = opti_res
            add_radiation = opti_radiation

        if sign:
            opti_res = add_res
            opti_radiation = add_radiation
            consecutive_no_improvement = 0
            _emit_plan_preview(
                opti_res,
                "seed_position_refinement",
                iter_count + 1,
                force=False,
            )
        else:
            consecutive_no_improvement += 1

        iter_count += 1
        if iter_count % seed_num == 0:
            all_seeds = []
            for _, (_, seeds, _) in enumerate(opti_res):
                all_seeds.extend(seeds)

        if consecutive_no_improvement >= max_no_improvement:
            break

    # Retain the better coverage/deficit result if seed removal degraded it.
    initial_values = minus_radiation[target_mask]
    final_values = opti_radiation[target_mask]
    if (np.count_nonzero(final_values > in_lowest_dose) < np.count_nonzero(initial_values > in_lowest_dose)
            or np.maximum(in_lowest_dose-final_values, 0).sum() > np.maximum(in_lowest_dose-initial_values, 0).sum() + 1e-6):
        opti_res = minus_res
        opti_radiation = minus_radiation
    # Transform seeds from voxel to world coordinates
    _emit_plan_preview(
        opti_res,
        "seed_position_refinement",
        iter_count,
        force=True,
    )
    final_res = seed_plan_to_world_coordinates(opti_res, dose_image)
    _logger.info(
        "[optimal_plan] Exact seed-dose cache: hits=%d misses=%d entries=%d bytes=%d",
        dose_context.seed_dose_cache_hits,
        dose_context.seed_dose_cache_misses,
        len(dose_context._seed_dose_cache),
        dose_context._seed_dose_cache_bytes,
    )
    return final_res


def optimal_plan_rf(
    init_trajectories,
    radiation_volume,
    dose_image,
    dose_cal_model,
    dl_params,
    rf_params,
    interval_rate,
    target_value,
    infer_img_size,
    in_lowest_dose,
    out_highest_dose,
    DVH_rate,
    seed_info,
    image_normalize_min,
    image_normalize_max,
    image_normalize_scale,
    progressDialog=None,
    parallel_min_distance_mm=None,
    parallel_angle_tolerance_deg=None,
    diagnostics=None,
    preview_callback=None,
):
    """
    Hierarchical reinforcement-learning pipeline for prostate/LDR brachytherapy.
    """
    if progressDialog is None:
        progressDialog = _mock_progress

    distance_map = distance_transform_edt(radiation_volume == target_value)

    progressDialog.setValue(50)
    progressDialog.setLabelText("Initial Planning...")

    planning_kwargs = {
        "candidate_trajectories": copy.deepcopy(init_trajectories),
        "seed_info": seed_info,
        "interval_rate": interval_rate,
        "rf_params": rf_params,
        "radiation_volume": radiation_volume,
        "dose_image": dose_image,
        "dose_cal_model": dose_cal_model,
        "infer_img_size": infer_img_size,
        "target_value": target_value,
        "in_lowest_dose": in_lowest_dose,
        "out_highest_dose": out_highest_dose,
        "DVH_rate": DVH_rate,
        "distance_map": distance_map,
        "image_normalize_min": image_normalize_min,
        "image_normalize_max": image_normalize_max,
        "image_normalize_scale": image_normalize_scale,
        "progressDialog": progressDialog,
        "parallel_min_distance_mm": parallel_min_distance_mm,
        "parallel_angle_tolerance_deg": parallel_angle_tolerance_deg,
    }
    # Keep the public return value backward compatible for legacy callers,
    # while allowing the planning pipeline to receive structured execution
    # telemetry from the same bounded RL invocation.
    if diagnostics is not None:
        planning_kwargs["diagnostics"] = diagnostics
    if preview_callback is not None:
        planning_kwargs["preview_callback"] = preview_callback
    optimal_res, _ = utilizations.hierarchical_planning_rf(**planning_kwargs)

    # The hierarchical RL utility already converts both seed positions and
    # directions to patient-world coordinates while it builds the plan:
    # planned_position2planned_res and the low-level refinement loop use
    # position_transform/direction_transform before returning. Do not apply
    # seed_plan_to_world_coordinates a second time here. The previous double
    # conversion treated world millimetres as [z, y, x] voxels, which made the
    # persisted seeds drift away from their owning trajectory and caused the
    # final physical needle validator to reject an otherwise valid RL plan.
    return optimal_res
