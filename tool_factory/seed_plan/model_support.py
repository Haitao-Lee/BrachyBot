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
    *, strict: bool = False,
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
    if strict:
        identities = []
        for seed in seeds or []:
            if not isinstance(seed, dict) or "direction" not in seed or not seed.get("id"):
                raise ValueError("Fixed dose requires every seed's accepted identity, center and axis")
            identities.append(seed["id"])
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate fixed physical seed identity")
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
        weight = float(seed.get("weight", 1.0)) if isinstance(seed, dict) else 1.0
        if not np.isfinite(weight) or weight <= 0:
            raise ValueError("Relative source strength must be finite and positive")
        model_seeds.append((position_zyx, voxel_direction))
        accepted.append({
            "id": seed_id,
            "position": position_xyz.tolist(),
            "direction": direction_lps.tolist(),
            "weight": weight,
        })

    if strict and len(accepted) != len(seeds or []):
        raise ValueError("Incomplete baseline: a fixed seed has invalid or out-of-grid geometry")
    if not model_seeds:
        if strict and not seeds:
            return np.zeros(tuple(int(v) for v in size_xyz[::-1]), dtype=np.float32), []
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
    if strict and len(per_seed_doses) != len(model_seeds):
        raise ValueError("Incomplete baseline: missing per-seed CNN dose contributions")
    for seed_dose, source in zip(per_seed_doses, accepted):
        seed_array = np.asarray(seed_dose, dtype=np.float32)
        if seed_array.shape != dose.shape:
            raise ValueError(
                f"dose_unet_spacing1mm returned shape {seed_array.shape}, expected {dose.shape}"
            )
        if strict and (not np.isfinite(seed_array).all() or np.any(seed_array < 0)):
            raise ValueError("Invalid fixed-seed CNN dose; baseline cannot be sanitized into validity")
        dose += seed_array * source["weight"]
    if strict and not np.isfinite(dose).all():
        raise ValueError("Fixed dose accumulation overflowed")
    dose = np.nan_to_num(dose, nan=0.0, posinf=0.0, neginf=0.0)
    dose[dose < 0.0] = 0.0
    return dose, accepted


def compute_continuation_baseline(fixed_seeds, dose_image, dose_model, dl_params,
                                seed_info, **baseline_kwargs):
    """Strict CNN aggregation; no guessed axes, skipped implants or double count.

    ``baseline_kwargs`` supplies complete_target_mask, OAR masks, explicit
    dose_scale_gy/dose_contract_id, collision dimensions, and optional immutable
    candidate paths/observed needles. The caller certifies observation coverage
    and source/model assumptions before invoking this computational boundary.
    """
    from plans.continuation import ContinuationBaseline, FixedSeed, array_sha256, grid_signature
    fixed_seeds = tuple(fixed_seeds)
    if any(not isinstance(s, FixedSeed) for s in fixed_seeds):
        raise ValueError("Accepted fixed seeds must be immutable FixedSeed records")
    for seed in fixed_seeds:
        if (abs(seed.length_mm - float(seed_info['length'])) > 1e-6
                or abs(seed.radius_mm - float(seed_info['radius'])) > 1e-6):
            raise ValueError("Heterogeneous source geometry is unsupported by this CNN batch")
    seeds = [{"id": s.physical_seed_id, "position": s.center_lps_mm, "direction": s.axis_lps}
             for s in fixed_seeds]
    dose, _ = compute_world_seed_dose_grid(seeds, dose_image, dose_model, dl_params, seed_info, strict=True)
    return ContinuationBaseline.create(
        dose, dose_image, baseline_unit="normalized_model",
        baseline_grid_signature=grid_signature(dose_image),
        baseline_dose_sha256=array_sha256(dose), fixed_seeds=fixed_seeds, **baseline_kwargs)


def continuation_dose_threshold(value, value_unit, continuation):
    """Keep legacy thresholds; continuation uses its own explicit calibration."""
    from plans.dose_pre.model_loader import planning_dose_value_to_model
    import numpy as np
    if continuation is None:
        return planning_dose_value_to_model(value, value_unit=value_unit)
    unit = str(value_unit).strip().lower()
    threshold = float(value)
    if not np.isfinite(threshold) or threshold <= 0:
        raise ValueError("Dose thresholds must be finite and positive")
    if unit in {"gy", "physical_gy", "dose_gy"}:
        return threshold / continuation.dose_scale_gy
    if unit == "normalized_model":
        return threshold
    raise ValueError("Continuation dose threshold units must be explicit")


def continuation_result_metadata(plan, continuation, volume, image, target_value,
                                 seed_info, prescription_model, outside_limit_model, target_coverage):
    if continuation is None:
        return {}
    from plans.continuation import finalize_continuation
    evaluation = finalize_continuation(plan, continuation, volume, image, target_value,
                                      seed_info, prescription_model, outside_limit_model, target_coverage)
    return {"continuation_evaluation": evaluation,
            "dose_distribution": evaluation["total_dose"],
            "dose_units": "normalized_model",
            "dose_distribution_gy": evaluation["total_dose_gy"],
            "dose_distribution_current_normalized": evaluation["total_dose"],
            "dose_distribution_physical_gy": evaluation["total_dose_gy"],
            "dose_unit_metadata": {"dose_distribution_gy": "physical_gy",
                                   "dose_distribution_current_normalized": "normalized_model",
                                   "dose_distribution_physical_gy": "physical_gy"},
            "additional_dose_distribution": evaluation["additional_dose"],
            "supplemental_only": True}
