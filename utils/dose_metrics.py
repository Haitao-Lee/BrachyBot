"""Discrete hottest-volume sampling convention shared by dose paths."""
import math


def validated_spacing(spacing):
    """Require explicit physical voxel dimensions, including for direct tools."""
    if not isinstance(spacing, (list, tuple)) or len(spacing) != 3:
        raise ValueError("Explicit dose-grid spacing [x, y, z] in mm is required")
    values = tuple(float(value) for value in spacing)
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("Dose-grid spacing must contain three finite positive values")
    return values


def hottest_volume_count(volume_cc, voxel_volume_cc, count):
    """Cover at least requested volume; clamp to the whole available organ.

    If the requested volume exceeds the organ, this convention reports the
    organ minimum, not a claim that the organ contains the requested volume.
    """
    volume, voxel = float(volume_cc), float(voxel_volume_cc)
    if not math.isfinite(volume) or not math.isfinite(voxel) or volume <= 0 or voxel <= 0 or count < 1:
        raise ValueError("Hottest-volume metrics require positive volumes and a nonempty organ")
    ratio = volume / voxel
    nearest = round(ratio)
    if math.isclose(ratio, nearest, rel_tol=1e-12, abs_tol=1e-12):
        ratio = float(nearest)
    return min(int(count), max(1, math.ceil(ratio)))
