import os
import sys
import time
import logging
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from . import config
from . import core
from . import utilizations
import numpy as np
from . import visualizer
import SimpleITK as sitk
try:
    import slicer
except ImportError:
    from . import slicer_mock as slicer


def brachy_plan(ctimage, ctvimage, oarimage, dose_model, args, progressDialog):
    """Perform brachytherapy treatment planning with optimized pipeline.

    Generates and optimizes seed trajectories, then accumulates dose
    distribution. Uses cached normalization and throttled UI updates
    for improved performance compared to the original brachy_plan.

    Args:
        ctimage: CT image (normalized) as dose background.
        ctvimage: Binary tumor mask (CTV).
        oarimage: OAR mask (optional, can be None).
        dose_model: Deep learning-based dose prediction model.
        args: Configuration parameters including dose constraints,
            geometry settings, seed specs, and planning hyperparameters.
        progressDialog: The progress dialog for UI updates.

    Returns:
        A tuple of (plan_res, sum_image, dose_image) where:
            plan_res: Optimized seed placement plan.
            sum_image: Accumulated dose distribution array.
            dose_image: Normalized CT image for dose background.
    """
    try:
        
        
        dose_image = utilizations.normalize_dose_image(ctimage, args.image_normalize[0], args.image_normalize[1], args.image_normalize[0], args.image_normalize[1])
        
    except Exception as e:
        pass
        
        raise

    progressDialog.setValue(15)
    progressDialog.setLabelText("Getting Radiation Volume...")
    utilizations.throttled_process_events()

    try:
        radiation_volume = utilizations.get_planning_volume_array(
            ctvimage,
            oarimage,
            args.radiation_array_params['target_value'],
            args.radiation_array_params['obstacle_value'],
            args.radiation_array_params['background_value'],
        )
        import logging as _log
        _logger = _log.getLogger(__name__)
        _target_count = int(np.sum(radiation_volume == args.radiation_array_params['target_value']))
        _obstacle_count = int(np.sum(radiation_volume == args.radiation_array_params['obstacle_value']))
        _bg_count = int(np.sum(radiation_volume == args.radiation_array_params['background_value']))
        # Check if radiation_volume has any non-zero target voxels in the resampled grid
        _nz_z, _nz_y, _nz_x = np.where(radiation_volume == args.radiation_array_params['target_value'])
        if len(_nz_z) > 0:
            pass
    except Exception as e:
        raise

    progressDialog.setValue(25)
    progressDialog.setLabelText("Computing Reference Direction...")
    utilizations.throttled_process_events()

    try:
        if args.reference_direc is not None:
            ref_direc = np.array(args.reference_direc).reshape(-1)
        else:
            ref_direc = np.array(utilizations.get_reference_direction(radiation_volume, args.radiation_array_params['target_value'])).reshape(-1)
    except Exception as e:
        raise

    progressDialog.setValue(30)
    progressDialog.setLabelText("Initial Planning...")
    utilizations.throttled_process_events()

    try:
        
        init_tracjectories = core.init_plan(
            ctvimage,
            radiation_volume,
            ref_direc,
            args.direc_resolution,
            args.radiation_array_params['backlit_angle'],
            args.radiation_array_params['target_value'],
            args.radiation_array_params['background_value'],
            args.radiation_array_params['obstacle_value'],
            args.radiation_array_params['maximum_candidate_trajectories'],
            progressDialog,
            min_depth=args.radiation_array_params.get('min_depth', 1),
        )
        
    except Exception as e:
        pass
        
        raise

    progressDialog.setValue(50)
    progressDialog.setLabelText("Optimal Planning...")
    utilizations.throttled_process_events()

    try:
        
        plan_res = core.optimal_plan(
            init_tracjectories,
            radiation_volume,
            dose_image,
            dose_model,
            args.dl_params,
            args.distance_filtter['lower_bound'],
            args.distance_filtter['upper_bound'],
            args.distance_filtter['distance_rate'],
            args.radiation_array_params['target_value'],
            args.radiation_array_params['background_value'],
            args.radiation_array_params['obstacle_value'],
            args.radiation_array_params['infer_img_size'],
            args.in_lowest_energy,
            args.out_highest_energy,
            args.DVH_rate,
            args.seed_info,
            args.iter_rate,
            args.image_normalize[0],
            args.image_normalize[1],
            args.image_normalize[2],
            progressDialog
        )
        
    except Exception as e:
        raise
    
    planned_seeds = []
    planned_seed_doses = []
    for res in plan_res:
        planned_seeds.append(res[1])
        planned_seed_doses.append(res[2])
    
    sum_array = np.zeros_like(radiation_volume).astype(np.float32)

    for i, seeds in enumerate(planned_seeds):
        for j, _ in enumerate(seeds):
            sum_array += planned_seed_doses[i][j]
    
    return plan_res, sum_array, dose_image


def brachy_plan_rf(ctimage, ctvimage, oarimage, dose_model, args, progressDialog):
    """Perform brachytherapy planning with reinforcement learning optimization.

    Uses hierarchical REINFORCE for trajectory and seed position
    optimization. Employs cached normalization and throttled UI
    updates for improved performance.

    Args:
        ctimage: CT image (normalized) as dose background.
        ctvimage: Binary tumor mask (CTV).
        oarimage: OAR mask (optional, can be None).
        dose_model: Deep learning-based dose prediction model.
        args: Configuration parameters including RF hyperparameters,
            dose constraints, seed specs, and planning settings.
        progressDialog: The progress dialog for UI updates.

    Returns:
        A tuple of (plan_res, sum_image, dose_image) where:
            plan_res: Optimized seed placement plan from RL.
            sum_image: Accumulated dose distribution array.
            dose_image: Normalized CT image for dose background.
    """
    
    
    try:

        dose_image = utilizations.normalize_dose_image(ctimage, args.image_normalize[0], args.image_normalize[1], args.image_normalize[0], args.image_normalize[1])

    except Exception as e:
        pass

        # REVIEW: previously fell back to `sitk.GetArrayFromImage(ctimage)
        # .astype(np.float32)` which assigned a NumPy array to `dose_image`.
        # Downstream calls (`core.optimal_plan_rf` ->
        # `batch_seed_dose_calculation_dl`) expect a SimpleITK image and call
        # `.GetDirection() / .GetSpacing() / .GetOrigin()` on it, plus
        # `sitk.GetArrayFromImage(dose_image)` further downstream; all of
        # those `AttributeError` on a NumPy array, leaving the plan empty
        # and silent. Like the non-rf `brachy_plan` path (line 48: `raise`),
        # surface the underlying failure instead of substituting a wrong
        # type that corrupts the rest of the pipeline.
        raise

    progressDialog.setValue(25)
    progressDialog.setLabelText("Getting Radiation Volume...")
    utilizations.throttled_process_events()

    try:
        
        radiation_volume = utilizations.get_planning_volume_array(
            ctvimage,
            oarimage,
            args.radiation_array_params['target_value'],
            args.radiation_array_params['obstacle_value'],
            args.radiation_array_params['background_value'],
        )
        
    except Exception as e:
        pass
        
        return [], np.array([]), dose_image

    progressDialog.setValue(30)
    progressDialog.setLabelText("Computing Reference Direction...")
    utilizations.throttled_process_events()

    try:
        
        if args.reference_direc is not None:
            ref_direc = np.array(args.reference_direc).reshape(-1)
        else:
            ref_direc = np.array(utilizations.direction_transform(ctvimage, utilizations.get_reference_direction(radiation_volume, args.radiation_array_params['target_value']))).reshape(-1)
        
    except Exception as e:
        pass
        
        ref_direc = np.array([0, 0, 1])

    progressDialog.setValue(30)
    progressDialog.setLabelText("Initial Planning...")
    utilizations.throttled_process_events()

    try:
        
        init_tracjectories = core.init_plan(
            ctvimage,
            radiation_volume,
            ref_direc,
            args.direc_resolution,
            args.radiation_array_params['backlit_angle'],
            args.radiation_array_params['target_value'],
            args.radiation_array_params['background_value'],
            args.radiation_array_params['obstacle_value'],
            args.radiation_array_params['maximum_candidate_trajectories'],
            progressDialog,
            min_depth=args.radiation_array_params.get('min_depth', 1),
        )
        
    except Exception as e:
        return [], np.array([]), dose_image
    
    progressDialog.setValue(50)
    progressDialog.setLabelText("Initial Planning...")
    utilizations.throttled_process_events()

    try:
        
        plan_res = core.optimal_plan_rf(
            init_tracjectories,
            radiation_volume,
            dose_image,
            dose_model,
            args.dl_params,
            args.rf_params,
            args.distance_filtter['interval_rate'],
            args.radiation_array_params['target_value'],
            args.radiation_array_params['infer_img_size'],
            args.in_lowest_energy,
            args.out_highest_energy,
            args.DVH_rate,
            args.seed_info,
            args.image_normalize[0],
            args.image_normalize[1],
            args.image_normalize[2],
            progressDialog
        )
        
    except Exception as e:
        pass
        
        plan_res = []
    
    planned_seeds = []
    planned_seed_doses = []
    try:
        for res in plan_res:
            planned_seeds.append(res[1])
            planned_seed_doses.append(res[2])
    except Exception as e:
        pass

    sum_array = np.zeros_like(radiation_volume).astype(np.float32)

    try:
        for i, seeds in enumerate(planned_seeds):
            for j, _ in enumerate(seeds):
                sum_array += planned_seed_doses[i][j]
    except Exception as e:
        pass

    return plan_res, sum_array, dose_image


def replan_single_needle(new_trajectory, other_needles_data, radiation_volume,
                         dose_image, dose_cal_model, args, dose_context=None):
    """Replan a single dragged needle while preserving other needles.

    Places seeds on the new trajectory using the same algorithm as the
    original planning pipeline (put_seeds). Other needles' seeds and
    dose contributions are preserved unchanged.

    Args:
        new_trajectory: New trajectory [start_point, direction, target_depths,
            background_depths] in resampled IJK voxel coordinates.
        other_needles_data: List of (trajectory, seeds_voxel, seed_radiations)
            for unchanged needles. Seeds must be in resampled IJK coordinates.
            Pass None for seeds_voxel and seed_radiations if not available;
            in that case those needles' doses are skipped.
        radiation_volume: 3D label array (target/background/obstacle).
        dose_image: SimpleITK image (resampled CT used for dose calculation).
        dose_cal_model: Deep learning dose prediction model.
        args: Planning parameters namespace.
        dose_context: Optional DoseImageContext for cached preprocessing.

    Returns:
        Tuple of (plan_res, sum_array, success) where:
            plan_res: List of [trajectory, seeds_world, seed_radiations] for
                ALL needles (unchanged + replanned), in world coordinates.
            sum_array: Cumulative dose array from all needles (float32).
            success: True if replanning found seed positions.
    """
    sys.stderr.write(f"[REPLAN SINGLE NEEDLE] CALLED! start={new_trajectory[0]}, dir={new_trajectory[1]}\n")
    sys.stderr.flush()
    target_value = args.radiation_array_params['target_value']
    obstacle_value = args.radiation_array_params['obstacle_value']
    background_value = args.radiation_array_params['background_value']
    infer_img_size = args.radiation_array_params['infer_img_size']
    in_lowest_dose = args.in_lowest_energy
    DVH_rate = args.DVH_rate
    seed_info = args.seed_info
    image_normalize_min = args.image_normalize[0]
    image_normalize_max = args.image_normalize[1]
    image_normalize_scale = args.image_normalize[2]

    # ============================================================
    # Replan trajectory setup
    # Principle: NEVER change the trajectory direction. The direction
    # comes from the dragged needle and must stay aligned with it.
    # Find the best starting point along the trajectory to maximize
    # the CTV depth in the forward direction.
    # ============================================================
    new_point = np.array(new_trajectory[0]).reshape(-1)
    new_direction = np.array(new_trajectory[1]).reshape(-1)

    max_idx = np.argmax(np.abs(new_direction))
    step_dir = new_direction / np.abs(new_direction[max_idx])

    # Step 1: Check if start is inside CTV
    pt_int = np.round(new_point).astype(int)
    start_val = None
    if all(0 <= pt_int[d] < radiation_volume.shape[d] for d in range(3)):
        start_val = radiation_volume[pt_int[0], pt_int[1], pt_int[2]]

    # Step 2: Walk along the trajectory to find the CTV segment
    # and pick the deepest interior point (maximizes forward depth)
    # First, walk backward to find CTV entry
    entry_step = -1
    ctv_segment = []
    for s in range(1, 100):
        test = np.round(new_point - s * step_dir).astype(int)
        if not all(0 <= test[d] < radiation_volume.shape[d] for d in range(3)):
            break
        v = radiation_volume[test[0], test[1], test[2]]
        if v == target_value:
            entry_step = s
        elif entry_step >= 0:
            break

    if entry_step >= 0:
        # Found CTV entry. Now walk forward from entry to find the full CTV segment.
        entry_point = np.round(new_point - entry_step * step_dir).astype(np.float64)

        # Walk forward from entry to find the extent of CTV along trajectory
        ctv_segment = []
        for s in range(0, 200):
            test = np.round(entry_point + s * step_dir).astype(int)
            if not all(0 <= test[d] < radiation_volume.shape[d] for d in range(3)):
                break
            v = radiation_volume[test[0], test[1], test[2]]
            if v == target_value:
                ctv_segment.append(s)
            elif len(ctv_segment) > 0:
                break  # Exited CTV after being inside

        if len(ctv_segment) > 0:
            # Use the CTV surface entry point as starting point.
            # Seeds will be placed along the dragged direction from this
            # entry point inward, letting put_seeds fill the CTV until
            # the dosimetric goal is met or no valid positions remain.
            new_point = entry_point
            new_trajectory[0] = new_point.tolist()
        else:
            pass
    else:
        # No CTV found backward, check if start is inside
        if start_val == target_value:
            pass
        else:
            pass

    # Step 3: Compute depths along the ORIGINAL direction
    # get_depthInfo_from_point only walks FORWARD and records target/background depths.
    # The backward walk only checks for obstacles, not target depths.
    # So we use the CTV segment we already found to compute the full trajectory.
    has_obstacle, target_depths, background_depths = utilizations.get_depthInfo_from_point(
        new_point, radiation_volume, new_direction,
        target_value, background_value, obstacle_value
    )

    # If the CTV segment we found is longer than what get_depthInfo_from_point reports,
    # use the CTV segment length as the target depth.
    # This handles the case where get_depthInfo_from_point exits the CTV early
    # due to the trajectory direction not aligning with the CTV's longest extent.
    if len(ctv_segment) > sum(target_depths) and len(ctv_segment) >= 3:
        target_depths = [len(ctv_segment)]
        background_depths = []

    # Step 4: If depth is too small, leave empty (don't change direction)
    if sum(target_depths) < 3:
        pass

    # Update trajectory with recomputed depths
    new_trajectory[2] = target_depths
    new_trajectory[3] = background_depths

    total_depth = sum(target_depths) + sum(background_depths)

    # Compute distance map for seed placement constraints
    from scipy.ndimage import distance_transform_edt
    distance_map = distance_transform_edt((radiation_volume == target_value))

    # Compute baseline radiation from other (unchanged) needles
    baseline_radiation = np.zeros_like(radiation_volume).astype(np.float32)
    for traj, seeds_vox, seed_rads in other_needles_data:
        if seed_rads is not None:
            for sr in seed_rads:
                baseline_radiation += sr

    # DEBUG: Log trajectory and CTV info
    traj_start = np.array(new_trajectory[0]).reshape(-1)
    traj_dir = np.array(new_trajectory[1]).reshape(-1)
    ctv_mask = (radiation_volume == target_value)
    ctv_voxels = np.sum(ctv_mask)

    # Check if trajectory start is near CTV
    start_int = np.round(traj_start).astype(int)
    for d in range(3):
        if start_int[d] < 0 or start_int[d] >= radiation_volume.shape[d]:
            pass
    # Sample points along trajectory to find CTV overlap
    point = traj_start.copy()
    max_idx = np.argmax(np.abs(traj_dir))
    step = traj_dir / np.abs(traj_dir[max_idx])
    ctv_hits = 0
    for t in range(20):
        test_pt = (point + t * step).astype(int)
        if all(0 <= test_pt[d] < radiation_volume.shape[d] for d in range(3)):
            # Note: radiation_volume is [z,y,x], trajectory is [x,y,z]
            val = radiation_volume[test_pt[0], test_pt[1], test_pt[2]]
            if val == target_value:
                ctv_hits += 1

    # Replan the dragged needle using put_seeds
    new_seeds_voxel, dvvh_rate, new_seed_radiations = utilizations.put_seeds(
        radiation_volume, dose_image, dose_cal_model, infer_img_size,
        baseline_radiation, target_value, in_lowest_dose,
        new_trajectory, seed_info, DVH_rate, distance_map,
        image_normalize_min, image_normalize_max, image_normalize_scale,
        dose_context=dose_context
    )


    if not new_seeds_voxel:
        return None, None, False

    # Transform seeds from IJK to world/physical coords (same as core.optimal_plan does)
    # run_brachyPlan will apply fMat to these world coords for RAS display
    new_seeds_world = []
    for seed in new_seeds_voxel:
        pos = seed[0].reshape(-1)
        world_pos = utilizations.position_transform(dose_image, pos)[0]
        direction = seed[1].reshape(-1)
        world_dir = utilizations.direction_transform(dose_image, direction)
        new_seeds_world.append((world_pos, world_dir))

    # Build plan_res: combine unchanged needles + replanned needle
    # Other needles already have world-coord seeds from initial plan
    plan_res = []
    for traj, seeds_vox, seed_rads in other_needles_data:
        plan_res.append([traj, seeds_vox, seed_rads])

    # Add the replanned needle (seeds in world coords)
    plan_res.append([new_trajectory, new_seeds_world, new_seed_radiations])

    # Compute total dose array
    sum_array = np.zeros_like(radiation_volume).astype(np.float32)
    for res in plan_res:
        if res[2] is not None:
            for sr in res[2]:
                sum_array += sr

    return plan_res, sum_array, True
