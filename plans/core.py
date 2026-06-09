from . import utilizations
import numpy as np
import torch
import torch.nn as nn
from scipy.ndimage import distance_transform_edt
from . import visualizer
import copy
try:
    import slicer
except ImportError:
    from . import slicer_mock as slicer



def init_plan(dose_image, radiation_volume, ref_direc, direc_resolution, extract_angle,
              target_value, background_value, obstacle_value, maximum_candidate_trajectories, progressDialog,
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
    # ---- 1.  Build conical direction grid ----
    candidate_dirs = utilizations.get_cone(
        ref_direc, direc_resolution[0], direc_resolution[1], direc_resolution[2]
    )
    
    progressDialog.setValue(35)
    progressDialog.setLabelText("Initial Planning...")
    slicer.app.processEvents()

    # ---- 2.  Extract candidate voxels inside cone ----
    max_points_num = maximum_candidate_trajectories // len(candidate_dirs)
    close_points, max_length = utilizations.get_close_points(
        dose_image, radiation_volume, ref_direc, target_value, extract_angle
    )
    
    progressDialog.setValue(40)
    progressDialog.setLabelText("Initial Planning...")
    slicer.app.processEvents()

    # Relax cone angle if too few points
    while close_points.shape[0] > max_points_num:
        extract_angle *= 1.1
        close_points, max_length = utilizations.get_close_points(
            dose_image, radiation_volume, ref_direc, target_value, extract_angle
        )
        progressDialog.setValue(40)
        progressDialog.setLabelText("Initial Planning...")
        slicer.app.processEvents()

    # ---- 3.  Initialise trajectories with depth filter ----
    init_trajectories = []
    for direc in candidate_dirs:
        progressDialog.setValue(45)
        progressDialog.setLabelText("Initial Planning...")
        slicer.app.processEvents()
        traj_list = utilizations.init_trajectories_with_depth(
            close_points, radiation_volume, direc, target_value,
            background_value, obstacle_value, min_depth, max_length
        )
        init_trajectories += traj_list
        
    # ---- 4.  Optional post-processing (commented) ----
    # sorted_trajectories = utilizations.sort_candidate_trajectories_by_depth(init_trajectories)
    # visual_list = [t[:2] for t in init_trajectories]
    # visualizer.visualize_rays_3d_with_obstacles_and_save(
    #     radiation_volume, visual_list, target_value, obstacle_value,
    #     filename='./fig/rays.png'
    # )

    return init_trajectories



def optimal_plan(init_trajectories, radiation_volume, dose_image, dose_cal_model, dl_params, lower_bound, upper_bound, distance_rate, 
                 target_value, background_value, obstacle_value, infer_img_size, in_lowest_dose, out_highest_dose, 
                 DVH_rate, seed_info, iter_rate, image_normalize_min, image_normalize_max, image_normalize_scale, progressDialog):
    """
    Generate an optimized radiation treatment plan by selecting seed trajectories, placing seeds, and refining the plan 
    to ensure effective tumor coverage while minimizing radiation exposure to healthy tissues.

    Parameters:
        init_trajectories (list): A list of initial candidate trajectories for seed placement.
        radiation_volume (ndarray): A 3D array representing the radiation distribution within the treatment area.
        dose_image (SimpleITK.Image): A dose image used to extract voxel spacing for precise seed placement.
        lower_bound (float): Minimum allowable distance between seeds for placement validation.
        upper_bound (float): Maximum allowable distance between seeds for placement validation.
        distance_rate (float): A threshold ratio to filter and optimize trajectory selection.
        target_value (float): The value representing the tumor region in the radiation volume.
        background_value (float): The value representing non-tumor regions in the radiation volume.
        obstacle_value (float): The value representing obstacles (e.g., critical organs) in the radiation volume.
        in_lowest_dose (float): Minimum radiation dose required for tumor treatment (in Gray).
        out_highest_dose (float): Maximum allowable radiation dose for surrounding healthy tissues (in Gray).
        DVH_rate (float): Target Dose Volume Histogram (DVH) coverage rate for tumor regions.
        seed_info (tuple): A tuple containing properties of the seeds (e.g., size, length, radiation intensity).
        iter_rate (int): The iteration multiplier for refining seed placement and minimizing dangerous radiation exposure.
        image_normalize_min (float): Minimum value for normalizing image intensity.
        image_normalize_max (float): Maximum value for normalizing image intensity.
        image_normalize_scale (float): Scaling factor for image intensity normalization.

    Returns:
        tuple:
            - opti_res (list): The final optimized plan containing refined trajectories, seed placements, and radiation distributions.
            - init_planned_res (list): The initial plan before refinement, including trajectories, seeds, and radiation data.

    Stages:
        1. **Trajectory Selection and Initial Planning**: Iteratively select optimal trajectories and place seeds to achieve the target DVH rate.
        2. **Plan Refinement**: Remove ineffective seeds, refine trajectory placements, and ensure adequate radiation coverage.
        3. **Fine-tuning for Safety**: Adjust seed placements iteratively to minimize excessive radiation exposure to healthy tissue regions.
    """

    # --- Initialize Variables ---
    candidate_trajectories = copy.deepcopy(init_trajectories)
    init_planned_res = []  # Stores the initial planned trajectories, seeds, and radiation values
    cur_DVH_rate = 0  # Current DVH coverage rate
    cur_radiation = np.zeros_like(radiation_volume).astype(float)  # Initialize the radiation distribution field
    distance_map = distance_transform_edt((radiation_volume == target_value))  # Compute the distance map for the tumor region
    
    
    # --- Stage 1: Trajectory Selection and Initial Planning ---
    selected_indices = []  # Store the indices of selected trajectories
    while cur_DVH_rate < DVH_rate:
        progressDialog.setValue(50)
        progressDialog.setLabelText("Optimal Planning...")
        slicer.app.processEvents()
        
        # Select the optimal trajectory based on current radiation distribution
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
            print("No seeds can be placed along the selected trajectory, The dose requirement is too high.")
            return init_planned_res, init_planned_res
        selected_indices.append(selected_idx)
        # Place seeds along the selected trajectory and calculate the radiation distribution
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
            image_normalize_scale
        )
        
        if len(optimal_seeds) == 0:
            print("No seeds can be placed along the selected trajectory, The dose requirement is too high.")
            return init_planned_res, init_planned_res
        
        # Append the selected trajectory and seed placements to the initial plan
        init_planned_res.append([optimal_trajectory, optimal_seeds, cur_single_seed_radiations])
        cur_radiation += np.sum(cur_single_seed_radiations, axis=0)  # Update the radiation distribution

    # --- Stage 2: Plan Refinement ---
    minus_res = copy.deepcopy(init_planned_res)
    # Remove seeds and radiation from the refined plan to prepare for re-planning
    for i in range(len(minus_res)):
        minus_res[i][1] = []
        minus_res[i][2] = []
    
    cur_DVH_rate = 0
    minus_radiation = np.zeros_like(radiation_volume)
    
    progressDialog.setValue(55)
    progressDialog.setLabelText("Optimal Planning...")
    slicer.app.processEvents()
    
    while cur_DVH_rate < DVH_rate:
        # Refine the plan by removing ineffective seeds and adjusting placements
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
            image_normalize_scale
        )
        if sign:
            cur_DVH_rate = updated_DVH_rate  # Update DVH rate if re-planning is successful
        else:
            minus_res = copy.deepcopy(init_planned_res)  # Reset if re-planning failed
            minus_radiation = cur_radiation
            break
        
        progressDialog.setValue(55)
        progressDialog.setLabelText("Optimal Planning...")
        slicer.app.processEvents()
        
    # --- Stage 3: Fine-tuning for Safety ---
    opti_res = copy.deepcopy(minus_res)
    all_seeds = []
    for _, (_, seeds, _) in enumerate(opti_res):
        all_seeds.extend(seeds)
    opti_radiation = copy.deepcopy(minus_radiation)
    iter_count = 0
    seed_num = sum(len(seeds) for _, seeds, _ in minus_res)
    
    while iter_count < iter_rate * seed_num:
        # Remove improper seeds that could cause excessive radiation exposure
        # rest_res, rest_radiation = utilizations.remove_unproper_seed(
        #     opti_res,
        #     radiation_volume,
        #     minus_radiation,
        #     out_highest_dose,
        #     target_value,
        #     background_value,
        #     obstacle_value
        # )
    
        # Remove seeds sequentially to minimize radiation exposure
        progressDialog.setValue(60)
        progressDialog.setLabelText("Optimal Planning...")
        slicer.app.processEvents()
        rest_res, rest_radiation = utilizations.remove_seed_sequentially(
            opti_res,
            all_seeds,
            iter_count % seed_num,
            opti_radiation,
        )
        
        # Add proper seeds to ensure sufficient tumor coverage and minimize radiation to healthy tissues
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
            image_normalize_scale
        )
        
        if sign:
            opti_res = copy.deepcopy(add_res)
            opti_radiation = copy.deepcopy(add_radiation)
        
        iter_count += 1 
        if iter_count % seed_num == 0:
            all_seeds = []
            for _, (_, seeds, _) in enumerate(opti_res):
                all_seeds.extend(seeds)

    
    final_res = []
    for res in opti_res:
        for seeds in res[1]:
            final_seeds = []
            for seed in seeds:
                pos = utilizations.position_transform(dose_image, seed[0]).reshape(-1) 
                direction = utilizations.direction_transform(dose_image, seed[1]).reshape(-1)
                final_seeds.append((pos, direction))
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
    progressDialog
):
    """
    Hierarchical reinforcement-learning pipeline for prostate/LDR brachytherapy.
    
    Steps:
        1. Build distance map for fast collision query.
        2. Load & wrap CNN-based single-seed dose engine.
        3. Call hierarchical REINFORCE to return the optimal needle trajectory
           and seed positions that maximise target coverage while respecting
           healthy-tissue constraints.
    
    Parameters
    ----------
    init_trajectories : list[Trajectory]
        Initial candidate needle paths (start-voxel, direction, meta).
    radiation_volume : np.ndarray
        3-D segmentation mask (target_value labels tumour).
    dose_image : SimpleITK.Image
        Reference image yielding voxel spacing and world mapping.
    dl_params : dict
        {'dose_spatial_dims': int,
         'dose_in_channel': int,
         'dose_out_channel': int,
         'dose_cal_features': list[int],
         'multi_GPU': bool,
         'dose_model_path': str,
         'device': torch.device}
    rf_params : dict
        {'lr': float, 'gamma': float, 'episodes': int} for REINFORCE.
    interval_rate : float
        Step-density factor when generating sub-positions.
    target_value : float
        Voxel intensity that identifies tumour.
    infer_img_size : tuple[int, int, int]
        CNN input patch size (H, W, D).
    in_lowest_dose : float
        DVH coverage threshold [Gy].
    out_highest_dose : float
        OAR penalty threshold [Gy].
    DVH_rate : float
        Required target-cover fraction.
    seed_info : dict
        {'length': float, 'radius': float, ...} seed geometry & activity.
    image_normalize_{min,max,scale} : float
        Intensity pre-processing constants for CNN.

    Returns
    -------
    optimal_res : tuple
        (high_action, planned_positions, dose, DVH_rate) produced by
        hierarchical REINFORCE.
    """
    distance_map = distance_transform_edt(radiation_volume == target_value)
    
    progressDialog.setValue(50)
    progressDialog.setLabelText("Initial Planning...")
    slicer.app.processEvents()

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
        progressDialog = progressDialog
    )

    return optimal_res

        
        




        
    




    
    
    
    
    

    
    


    

    
    



