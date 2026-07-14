"""Shared dose-model helpers for standalone and intra-operative planning."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def resolve_dose_model(
    kwargs: Dict[str, Any], dl_params: Dict[str, Any]
) -> Tuple[Any, Optional[str]]:
    """Return an injected or configured spacing-normalized DoseUNet model."""
    injected_model = kwargs.get("dose_cal_model")
    if injected_model is not None:
        return injected_model, None

    from plans.dose_pre.model_loader import load_dose_model

    features = dl_params.get("dose_cal_features", (16, 32, 64, 128, 256))
    model, error, _ = load_dose_model(
        explicit_path=dl_params.get("dose_model_path"),
        device=dl_params.get("device", "cpu"),
        spatial_dims=dl_params.get("dose_spatial_dims", 3),
        in_channels=dl_params.get("dose_in_channel", 3),
        out_channels=dl_params.get("dose_out_channel", 1),
        features=tuple(features),
    )
    return model, error


def compute_world_seed_dose_grid(
    seeds: list,
    dose_image: Any,
    dose_model: Any,
    dl_params: Dict[str, Any],
    seed_info: Dict[str, Any],
) -> Tuple[Any, list]:
    """Run DoseUNet for physical LPS seed positions on ``dose_image``.

    Positions and directions stay in the deployed physical LPS convention at
    the API boundary. They are converted to NumPy ``(z, y, x)`` coordinates
    only for the existing model inference functions.
    """
    import numpy as np
    import SimpleITK as sitk

    from plans import utilizations

    if dose_model is None:
        raise ValueError("A trained dose_unet_spacing1mm model is required")
    if dose_image is None:
        raise ValueError("dose_image is required")

    size_xyz = np.asarray(dose_image.GetSize(), dtype=np.float64)
    model_seeds = []
    accepted = []
    for index, seed in enumerate(seeds or []):
        if isinstance(seed, dict):
            position = seed.get("physical_position", seed.get("position"))
            direction = seed.get("direction", [0.0, 0.0, 1.0])
            seed_id = seed.get("id", index + 1)
        elif isinstance(seed, (list, tuple)) and len(seed) >= 2:
            position, direction = seed[0], seed[1]
            seed_id = index + 1
        else:
            continue

        position_xyz = np.asarray(position, dtype=np.float64).reshape(-1)
        direction_lps = np.asarray(direction, dtype=np.float64).reshape(-1)
        if (
            position_xyz.size != 3
            or direction_lps.size != 3
            or not np.all(np.isfinite(position_xyz))
            or not np.all(np.isfinite(direction_lps))
        ):
            continue

        direction_norm = float(np.linalg.norm(direction_lps))
        if direction_norm <= 1e-8:
            continue
        direction_lps = direction_lps / direction_norm

        try:
            index_xyz = np.asarray(
                dose_image.TransformPhysicalPointToContinuousIndex(
                    tuple(float(value) for value in position_xyz)
                ),
                dtype=np.float64,
            )
        except Exception:
            continue
        if (
            not np.all(np.isfinite(index_xyz))
            or np.any(index_xyz < 0.0)
            or np.any(index_xyz >= size_xyz)
        ):
            continue

        voxel_direction = np.asarray(
            utilizations.ras_direction_to_voxel(direction_lps, dose_image),
            dtype=np.float32,
        ).reshape(-1)
        voxel_norm = float(np.linalg.norm(voxel_direction))
        if voxel_direction.size != 3 or not np.isfinite(voxel_norm) or voxel_norm <= 1e-8:
            continue
        voxel_direction = voxel_direction / voxel_norm
        position_zyx = np.asarray(index_xyz[::-1], dtype=np.float32)
        model_seeds.append((position_zyx, voxel_direction))
        accepted.append({
            "id": seed_id,
            "position": position_xyz.tolist(),
            "direction": direction_lps.tolist(),
        })

    if not model_seeds:
        raise ValueError("No seed positions fall inside the planning dose grid")

    image_normalize = dl_params.get("image_normalize", [-1000, 3000, 255])
    infer_size = dl_params.get("infer_img_size", [64, 64, 64])
    per_seed_doses = utilizations.batch_seed_dose_calculation_dl(
        model_seeds,
        dose_image,
        dose_model,
        infer_size,
        seed_info,
        image_normalize[0],
        image_normalize[1],
        image_normalize[2],
    )
    dose = np.zeros_like(sitk.GetArrayFromImage(dose_image), dtype=np.float32)
    for seed_dose in per_seed_doses:
        seed_array = np.asarray(seed_dose, dtype=np.float32)
        if seed_array.shape != dose.shape:
            raise ValueError(
                f"dose_unet_spacing1mm returned shape {seed_array.shape}, expected {dose.shape}"
            )
        dose += seed_array
    dose = np.nan_to_num(dose, nan=0.0, posinf=0.0, neginf=0.0)
    dose[dose < 0.0] = 0.0
    return dose, accepted
