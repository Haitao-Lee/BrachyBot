# coding = utf-8
import json
import os
import sys
import numpy as np

# Add parent directory to system path for module imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def setting():
    """Load configuration from config.json and return as argparse.Namespace.

    Returns:
        argparse.Namespace: A namespace containing all configuration parameters.
    """
    import argparse

    config_path = os.path.join(os.path.dirname(__file__), "config.json")

    with open(config_path, "r") as f:
        config = json.load(f)

    # Convert lists back to numpy arrays where needed
    config["reference_direc"] = np.array(config["reference_direc"])
    config["iso_dose_params"]["iso_dose_values"] = np.array(config["iso_dose_params"]["iso_dose_values"])
    config["iso_dose_params"]["iso_colors"] = [tuple(c) for c in config["iso_dose_params"]["iso_colors"]]

    # Convert dose_img_dimention and infer_img_size to tuples
    config["radiation_array_params"]["dose_img_dimention"] = tuple(
        config["radiation_array_params"]["dose_img_dimention"]
    )
    config["radiation_array_params"]["infer_img_size"] = tuple(config["radiation_array_params"]["infer_img_size"])

    # Convert iso_dose_params iso_opacities to list
    config["iso_dose_params"]["iso_opacities"] = list(config["iso_dose_params"]["iso_opacities"])

    # Convert color list
    config["color"] = list(config["color"])

    # Convert dl_params device string to torch.device
    import torch

    device_str = config["dl_params"]["device"]
    config["dl_params"]["device"] = torch.device(device_str)

    # Convert dose_cal_features to tuple
    config["dl_params"]["dose_cal_features"] = tuple(config["dl_params"]["dose_cal_features"])

    # Convert dl_params loss_weights to list
    config["dl_params"]["loss_weights"] = list(config["dl_params"]["loss_weights"])

    # Convert rays_res, obstacle_res, direc_resolution to lists
    config["rays_res"] = list(config["rays_res"])
    config["obstacle_res"] = list(config["obstacle_res"])
    config["direc_resolution"] = list(config["direc_resolution"])

    # Convert image_normalize to list
    config["image_normalize"] = list(config["image_normalize"])

    # Convert seed_info margin_rate to float
    config["seed_info"]["margin_rate"] = float(config["seed_info"]["margin_rate"])

    # Create namespace from config
    args = argparse.Namespace(**config)
    return args
