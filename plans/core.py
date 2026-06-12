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

try:
    import slicer
except ImportError:
    from . import slicer_mock as slicer


class _MockProgressDialog:
    """No-op progress dialog for headless mode."""
    def setValue(self, v): pass
    def setLabelText(self, t): pass

_mock_progress = _MockProgressDialog()


def init_plan(dose_image, radiation_volume, ref_direc, direc_resolution, extract_angle,
              target_value, background_value, obstacle_value, maximum_candidate_trajectories, progressDialog=None,
              min_depth=2):
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

    Returns
    -------
    list[tuple]
        List of valid trajectories. Each tuple contains:
        (origin_voxel, direction_vector, depth, ...metadata...)
        Ready for downstream optimisation or refinement.
    """
    if progressDialog is None:
        progressDialog = _mock_progress

    # ---- 1.  Build conical direction grid ----
    candidate_dirs = utilizations.get_cone(
        ref_direc, direc_resolution[0], direc_resolution[1], direc_resolution[2]
    )

    progressDialog.setValue(35)
    progressDialog.setLabelText("Initial Planning...")

    # ---- 2.  Extract candidate voxels inside cone ----
    max_points_num = maximum_candidate_trajectories // len(candidate_dirs)

    close_points, max_length = utilizations.get_close_points(
        dose_image, radiation_volume, ref_direc, target_value, extract_angle
    )

    progressDialog.setValue(40)
    progressDialog.setLabelText("Initial Planning...")

    # Relax cone angle if too few points
    while close_points.shape[0] > max_points_num:
        extract_angle *= 1.1
        close_points, max_length = utilizations.get_close_points(
            dose_image, radiation_volume, ref_direc, target_value, extract_angle
        )
        progressDialog.setValue(40)
        progressDialog.setLabelText("Initial Planning...")

    # ---- 3.  Initialise trajectories with depth filter ----
    init_trajectories = []
    for i, direc in enumerate(candidate_dirs):
        progressDialog.setValue(45)
        progressDialog.setLabelText("Initial Planning...")
        traj_list = utilizations.init_trajectories_with_depth(
            close_points, radiation_volume, direc, target_value,
            background_value, obstacle_value, min_depth, max_length
        )
        init_trajectories += traj_list

    return init_trajectories


def optimal_plan(init_trajectories, radiation_volume, dose_image, dose_cal_model, dl_params, lower_bound, upper_bound, distance_rate,
                 target_value, background_value, obstacle_value, infer_img_size, in_lowest_dose, out_highest_dose,
                 DVH_rate, seed_info, iter_rate, image_normalize_min, image_normalize_max, image_normalize_scale, progressDialog=None):
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

    # --- Stage 1: Trajectory Selection and Initial Planning ---
    selected_indices = []
    stage1_count = 0
    while cur_DVH_rate < DVH_rate:
        stage1_count += 1
        if stage1_count > 100:
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
            selected_indices
        )
        if optimal_trajectory is None:
            return init_planned_res
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
            dose_context=dose_context
        )

        if len(optimal_seeds) == 0:
            return init_planned_res

        init_planned_res.append([optimal_trajectory, optimal_seeds, cur_single_seed_radiations])
        cur_radiation += np.sum(cur_single_seed_radiations, axis=0)

    # --- Stage 2: Plan Refinement ---
    minus_res = copy.copy(init_planned_res)
    for i in range(len(minus_res)):
        minus_res[i] = [minus_res[i][0], [], []]

    cur_DVH_rate = 0
    minus_radiation = np.zeros_like(radiation_volume)

    progressDialog.setValue(55)
    progressDialog.setLabelText("Optimal Planning...")

    while cur_DVH_rate < DVH_rate:
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
                dose_context=dose_context
            )
        except Exception as e:
            minus_res = copy.deepcopy(init_planned_res)
            minus_radiation = cur_radiation
            break
        if sign:
            cur_DVH_rate = updated_DVH_rate
        else:
            minus_res = copy.deepcopy(init_planned_res)
            minus_radiation = cur_radiation
            break

        progressDialog.setValue(55)
        progressDialog.setLabelText("Optimal Planning...")

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
                dose_context=dose_context
            )
        except Exception as e:
            sign = False
            add_res = opti_res
            add_radiation = opti_radiation

        if sign:
            opti_res = add_res
            opti_radiation = add_radiation
            consecutive_no_improvement = 0
        else:
            consecutive_no_improvement += 1

        iter_count += 1
        if iter_count % seed_num == 0:
            all_seeds = []
            for _, (_, seeds, _) in enumerate(opti_res):
                all_seeds.extend(seeds)

        if consecutive_no_improvement >= max_no_improvement:
            break

    # Transform seeds from voxel to world coordinates
    final_res = []
    for res in opti_res:
        final_seeds = []
        for seed in res[1]:
            pos = seed[0].reshape(-1)
            world_pos = utilizations.position_transform(dose_image, pos)[0]
            direction = seed[1].reshape(-1)
            world_dir = utilizations.direction_transform(dose_image, direction)
            final_seeds.append((world_pos, world_dir))
        final_res.append([res[0], final_seeds, res[2]])
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
    progressDialog=None
):
    """
    Hierarchical reinforcement-learning pipeline for prostate/LDR brachytherapy.
    """
    if progressDialog is None:
        progressDialog = _mock_progress

    distance_map = distance_transform_edt(radiation_volume == target_value)

    progressDialog.setValue(50)
    progressDialog.setLabelText("Initial Planning...")

    optimal_res, _ = utilizations.hierarchical_planning_rf(
        candidate_trajectories=copy.deepcopy(init_trajectories),
        seed_info=seed_info,
        interval_rate=interval_rate,
        rf_params=rf_params,
        radiation_volume=radiation_volume,
        dose_image=dose_image,
        dose_cal_model=dose_cal_model,
        infer_img_size=infer_img_size,
        target_value=target_value,
        in_lowest_dose=in_lowest_dose,
        out_highest_dose=out_highest_dose,
        DVH_rate=DVH_rate,
        distance_map=distance_map,
        image_normalize_min=image_normalize_min,
        image_normalize_max=image_normalize_max,
        image_normalize_scale=image_normalize_scale,
        progressDialog=progressDialog
    )

    return optimal_res
