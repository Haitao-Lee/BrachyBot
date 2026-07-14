"""Inference preprocessing for the spacing-normalized DoseUNet checkpoint.

The training contract is:

* physical crop centered on each particle (12 cm by default);
* resample the crop to the checkpoint target spacing (1 mm in the deployed
  checkpoint);
* input channels ordered as line map, normalized CT, soft particle position;
* DoseUNet output divided by the checkpoint ``dose_multiplier``;
* the prediction resampled back into the original CT grid.

All public callers still pass the existing BrachyBot ``(z, y, x)`` voxel
position and voxel direction. Conversion to physical coordinates is kept here
so the established LPS/voxel coordinate chain is not changed at its callers.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np
import SimpleITK as sitk
import torch


def normalize_ct(ct: np.ndarray) -> np.ndarray:
    ct = np.clip(np.asarray(ct, dtype=np.float32), -1000.0, 3000.0)
    return (ct + 1000.0) / 4000.0


def normalize_unit(array: np.ndarray) -> np.ndarray:
    array = np.nan_to_num(np.asarray(array, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    max_value = float(np.max(array))
    return array / max_value if max_value > 0.0 else array


def crop_ct_center_on_seed(image: sitk.Image, seed_physical_point: Sequence[float], output_size_cm: float = 12.0) -> sitk.Image:
    spacing = np.asarray(image.GetSpacing(), dtype=np.float64)
    size = np.asarray(image.GetSize(), dtype=np.int64)
    output_size_mm = float(output_size_cm) * 10.0
    desired_voxels = np.maximum(np.ceil(output_size_mm / spacing).astype(np.int64), 1)

    seed_idx = np.asarray(
        image.TransformPhysicalPointToContinuousIndex(tuple(float(v) for v in seed_physical_point)),
        dtype=np.float64,
    )
    # Keep the fractional physical crop origin used during training while
    # extracting from integer voxel bounds. This preserves sub-voxel seed
    # alignment after resampling to the 1 mm network grid.
    start_float = seed_idx - desired_voxels.astype(np.float64) / 2.0
    start_int = np.floor(start_float).astype(np.int64)
    end_int = start_int + desired_voxels

    pad_before = np.maximum(0, -start_int)
    pad_after = np.maximum(0, end_int - size)
    extract_start = np.maximum(0, start_int)
    extract_end = np.minimum(size, end_int)

    array = sitk.GetArrayFromImage(image)
    x0, y0, z0 = extract_start
    x1, y1, z1 = extract_end
    sub = array[z0:z1, y0:y1, x0:x1]
    pad_width = (
        (int(pad_before[2]), int(pad_after[2])),
        (int(pad_before[1]), int(pad_after[1])),
        (int(pad_before[0]), int(pad_after[0])),
    )
    if any(width != (0, 0) for width in pad_width):
        sub = np.pad(sub, pad_width, mode="edge")

    desired_shape = (int(desired_voxels[2]), int(desired_voxels[1]), int(desired_voxels[0]))
    if sub.shape != desired_shape:
        pad_needed = [max(0, desired_shape[i] - sub.shape[i]) for i in range(3)]
        if any(pad_needed):
            sub = np.pad(sub, tuple((0, p) for p in pad_needed), mode="edge")
        sub = sub[:desired_shape[0], :desired_shape[1], :desired_shape[2]]

    cropped = sitk.GetImageFromArray(sub.astype(np.float32, copy=False))
    cropped.SetOrigin(image.TransformContinuousIndexToPhysicalPoint(tuple(start_float)))
    cropped.SetSpacing(tuple(float(v) for v in spacing))
    cropped.SetDirection(image.GetDirection())
    return cropped


def reference_at_spacing(image: sitk.Image, target_spacing: Sequence[float]) -> sitk.Image:
    target_spacing = np.asarray(target_spacing, dtype=np.float64)
    spacing = np.asarray(image.GetSpacing(), dtype=np.float64)
    size = np.asarray(image.GetSize(), dtype=np.int64)
    physical_size = size * spacing
    target_size = np.maximum(np.round(physical_size / target_spacing).astype(np.int64), 1)
    reference = sitk.Image([int(v) for v in target_size], sitk.sitkFloat32)
    reference.SetOrigin(image.GetOrigin())
    reference.SetSpacing(tuple(float(v) for v in target_spacing))
    reference.SetDirection(image.GetDirection())
    return reference


def resample_to_reference(image: sitk.Image, reference: sitk.Image, interpolator=sitk.sitkLinear, default_value: float = 0.0) -> sitk.Image:
    if (
        image.GetSize() == reference.GetSize()
        and np.allclose(image.GetSpacing(), reference.GetSpacing())
        and np.allclose(image.GetOrigin(), reference.GetOrigin())
        and np.allclose(image.GetDirection(), reference.GetDirection())
    ):
        return sitk.Cast(image, sitk.sitkFloat32)
    return sitk.Resample(image, reference, sitk.Transform(), interpolator, float(default_value), sitk.sitkFloat32)


def resample_image_to_spacing(image: sitk.Image, target_spacing: Sequence[float], interpolator=sitk.sitkLinear, default_value: float = 0.0) -> sitk.Image:
    return resample_to_reference(image, reference_at_spacing(image, target_spacing), interpolator, default_value)


def physical_coordinate_arrays(image: sitk.Image) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    size = np.asarray(image.GetSize(), dtype=np.int64)
    spacing = np.asarray(image.GetSpacing(), dtype=np.float64)
    origin = np.asarray(image.GetOrigin(), dtype=np.float64)
    direction = np.asarray(image.GetDirection(), dtype=np.float64).reshape(3, 3)
    x_idx, y_idx, z_idx = np.meshgrid(
        np.arange(size[0], dtype=np.float64),
        np.arange(size[1], dtype=np.float64),
        np.arange(size[2], dtype=np.float64),
        indexing="ij",
    )
    scaled = np.stack((x_idx * spacing[0], y_idx * spacing[1], z_idx * spacing[2]), axis=0)
    coords = origin.reshape(3, 1, 1, 1) + np.einsum("ij,jxyz->ixyz", direction, scaled)
    return coords[0], coords[1], coords[2]


def image_from_xyz_array(array_xyz: np.ndarray, reference_image: sitk.Image) -> sitk.Image:
    image = sitk.GetImageFromArray(np.transpose(array_xyz, (2, 1, 0)).astype(np.float32))
    image.CopyInformation(reference_image)
    return image


def generate_soft_pos(image: sitk.Image, position: Sequence[float], sphere_radius: float = 4.0) -> sitk.Image:
    x_phys, y_phys, z_phys = physical_coordinate_arrays(image)
    distance = np.sqrt(
        (x_phys - float(position[0])) ** 2
        + (y_phys - float(position[1])) ** 2
        + (z_phys - float(position[2])) ** 2
    )
    soft = np.zeros(image.GetSize(), dtype=np.float32)
    inside = distance <= float(sphere_radius)
    soft[inside] = ((float(sphere_radius) - distance[inside]) / float(sphere_radius)) ** 3
    total = float(np.sum(soft))
    if total > 0.0:
        soft /= total
    return image_from_xyz_array(soft, image)


def generate_line_map(image: sitk.Image, position: Sequence[float], direction: Sequence[float], line_length: float = 4.5) -> sitk.Image:
    x_phys, y_phys, z_phys = physical_coordinate_arrays(image)
    direction = np.asarray(direction, dtype=np.float64)
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-8:
        raise ValueError("Particle direction vector is zero")
    direction /= norm
    position = np.asarray(position, dtype=np.float64)
    vx, vy, vz = x_phys - position[0], y_phys - position[1], z_phys - position[2]
    distance_squared = np.maximum(vx * vx + vy * vy + vz * vz, 1e-8)
    half = float(line_length) / 2.0
    point_a = position + direction * half
    point_b = position - direction * half
    pa = np.sqrt((x_phys - point_a[0]) ** 2 + (y_phys - point_a[1]) ** 2 + (z_phys - point_a[2]) ** 2)
    pb = np.sqrt((x_phys - point_b[0]) ** 2 + (y_phys - point_b[1]) ** 2 + (z_phys - point_b[2]) ** 2)
    dot = (x_phys - point_a[0]) * (x_phys - point_b[0]) + (y_phys - point_a[1]) * (y_phys - point_b[1]) + (z_phys - point_a[2]) * (z_phys - point_b[2])
    with np.errstate(invalid="ignore", divide="ignore"):
        beta = np.arccos(np.clip(np.nan_to_num(np.abs(dot / (pa * pb)), nan=1.0), -1.0, 1.0))
    vectors = np.stack((vx, vy, vz), axis=-1)
    vec_norm = np.linalg.norm(vectors, axis=-1, keepdims=True)
    vec_norm = np.maximum(vec_norm, 1e-12)
    theta = np.arccos(np.clip(np.sum(vectors / vec_norm * direction.reshape((1, 1, 1, 3)), axis=-1), -1.0, 1.0))
    line_map = beta / (np.sin(theta) * distance_squared + 1e-5)
    axial = theta == 0
    axial_values = (distance_squared - float(line_length) ** 2 / 4.0) ** -1
    line_map[axial] = np.nan_to_num(axial_values[axial], nan=0.0, posinf=0.0, neginf=0.0)
    line_map = np.nan_to_num(line_map, nan=0.0, posinf=0.0, neginf=0.0)
    maximum = float(np.max(line_map))
    if maximum > 0.0:
        line_map /= maximum
    return image_from_xyz_array(line_map, image)


def starts_for_dim(size: int, patch: int, stride: int) -> List[int]:
    if size <= patch:
        return [0]
    starts = list(range(0, size - patch + 1, stride))
    if starts[-1] != size - patch:
        starts.append(size - patch)
    return starts


def crop_or_pad(array: np.ndarray, start: Sequence[int], patch_size: Sequence[int]) -> np.ndarray:
    patch_size = np.asarray(patch_size, dtype=np.int64)
    start = np.asarray(start, dtype=np.int64)
    end = start + patch_size
    shape = np.asarray(array.shape, dtype=np.int64)
    src_start = np.maximum(start, 0)
    src_end = np.minimum(end, shape)
    dst_start = src_start - start
    dst_end = dst_start + (src_end - src_start)
    result = np.zeros(tuple(int(v) for v in patch_size), dtype=array.dtype)
    result[dst_start[0]:dst_end[0], dst_start[1]:dst_end[1], dst_start[2]:dst_end[2]] = array[
        src_start[0]:src_end[0], src_start[1]:src_end[1], src_start[2]:src_end[2]
    ]
    return result


@torch.no_grad()
def sliding_window_predict(model: torch.nn.Module, inputs: np.ndarray, patch_size: Sequence[int], overlap: float, device: torch.device) -> np.ndarray:
    shape = tuple(int(v) for v in inputs.shape[1:])
    patch_size = tuple(int(v) for v in patch_size)
    if len(patch_size) != 3 or any(v <= 0 for v in patch_size):
        raise ValueError(f"Invalid DoseUNet patch size: {patch_size}")
    overlap = min(max(float(overlap), 0.0), 0.95)
    stride = tuple(max(1, int(round(p * (1.0 - overlap)))) for p in patch_size)
    starts = [starts_for_dim(shape[i], patch_size[i], stride[i]) for i in range(3)]
    pred_sum = np.zeros(shape, dtype=np.float32)
    pred_count = np.zeros(shape, dtype=np.float32)
    model.eval()
    for z in starts[0]:
        for y in starts[1]:
            for x in starts[2]:
                start = (z, y, x)
                patch = np.stack([crop_or_pad(channel, start, patch_size) for channel in inputs], axis=0)
                tensor = torch.from_numpy(patch[None].astype(np.float32, copy=False)).to(device)
                prediction = model(tensor).detach().cpu().numpy()[0, 0]
                z1, y1, x1 = min(z + patch_size[0], shape[0]), min(y + patch_size[1], shape[1]), min(x + patch_size[2], shape[2])
                pred_sum[z:z1, y:y1, x:x1] += prediction[:z1-z, :y1-y, :x1-x]
                pred_count[z:z1, y:y1, x:x1] += 1.0
    return pred_sum / np.maximum(pred_count, 1.0)


def resample_crop_to_full(crop_image: sitk.Image, crop_array: np.ndarray, full_image: sitk.Image) -> np.ndarray:
    prediction = sitk.GetImageFromArray(np.asarray(crop_array, dtype=np.float32))
    prediction.CopyInformation(crop_image)
    resampled = sitk.Resample(prediction, full_image, sitk.Transform(), sitk.sitkLinear, 0.0, sitk.sitkFloat32)
    return sitk.GetArrayFromImage(resampled).astype(np.float32)


def particle_inside_image(image: sitk.Image, position: Sequence[float]) -> bool:
    try:
        index = np.asarray(image.TransformPhysicalPointToContinuousIndex(tuple(float(v) for v in position)), dtype=np.float64)
    except RuntimeError:
        return False
    size = np.asarray(image.GetSize(), dtype=np.float64)
    return bool(np.all(index >= -0.5) and np.all(index <= size - 0.5))


def _model_contract(model: torch.nn.Module) -> Dict[str, Any]:
    contract = getattr(model, "_brachybot_dose_contract", None)
    if contract is None:
        # torch.nn.DataParallel stores the real model under ``module``. The
        # wrapper must not hide the preprocessing contract from the adapter.
        contract = getattr(getattr(model, "module", None), "_brachybot_dose_contract", None)
    if not isinstance(contract, dict):
        raise RuntimeError(
            "The loaded dose model has no DoseUNet spacing-normalized contract. "
            "Refusing to run the removed legacy dose preprocessing."
        )
    return contract


def predict_seed_dose(position_xyz: Sequence[float], direction_lps: Sequence[float], dose_image: sitk.Image, model: torch.nn.Module, seed_weight: float = 1.0) -> np.ndarray:
    contract = _model_contract(model)
    target_spacing = contract["target_spacing"]
    patch_size = contract["patch_size"]
    output_size_cm = float(contract.get("output_size_cm", 12.0))
    line_length = float(contract.get("line_length", 4.5))
    overlap = float(contract.get("overlap", 0.5))
    dose_multiplier = float(contract["dose_multiplier"])
    planning_output_scale = float(contract.get("planning_output_scale", 1.0))
    device = next(model.parameters()).device

    crop_image = crop_ct_center_on_seed(dose_image, position_xyz, output_size_cm)
    network_image = resample_image_to_spacing(crop_image, target_spacing, sitk.sitkLinear, -1000.0)
    ct_crop = sitk.GetArrayFromImage(network_image).astype(np.float32)
    soft = sitk.GetArrayFromImage(generate_soft_pos(
        network_image,
        position_xyz,
        float(contract.get("seed_soft_radius", 4.0)),
    )).astype(np.float32)
    line = sitk.GetArrayFromImage(generate_line_map(network_image, position_xyz, direction_lps, line_length)).astype(np.float32)
    inputs = np.stack([normalize_unit(line), normalize_ct(ct_crop), normalize_unit(soft)], axis=0)
    prediction_scaled = sliding_window_predict(model, inputs, patch_size, overlap, device)
    # ``prediction_scaled / dose_multiplier`` is the raw upstream predictor
    # output. The planner explicitly consumes training-scaled model units, so
    # apply the contract's reversible planning scale at this boundary.
    prediction = (
        prediction_scaled / dose_multiplier * planning_output_scale * float(seed_weight)
    )
    prediction = np.nan_to_num(prediction, nan=0.0, posinf=0.0, neginf=0.0)
    prediction[prediction < 0.0] = 0.0
    return resample_crop_to_full(network_image, prediction, dose_image)


def predict_seed_doses(particles: Iterable[Tuple[Sequence[float], Sequence[float], float]], dose_image: sitk.Image, model: torch.nn.Module) -> List[np.ndarray]:
    outputs = []
    for position, direction, weight in particles:
        if not particle_inside_image(dose_image, position):
            continue
        outputs.append(predict_seed_dose(position, direction, dose_image, model, weight))
    return outputs


__all__ = ["predict_seed_dose", "predict_seed_doses"]
