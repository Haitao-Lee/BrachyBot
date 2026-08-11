"""Shared physical geometry rules for planning and surgical-guide generation.

The planner and the printable guide must agree on the size of a needle
channel.  Keeping the constants here prevents a candidate path from being
accepted with a spacing that the generated STL cannot physically preserve.
"""

from __future__ import annotations

import math
from typing import Optional


# These values mirror the guide's manufacturing defaults.  The bore margin is
# part of the physical opening written to the STL, so its diameter is the
# useful default clearance for parallel planned needles.
DEFAULT_GUIDE_CHANNEL_RADIUS_MM = 0.9
GUIDE_BORE_MARGIN_MM = 0.4
DEFAULT_GUIDE_CHANNEL_DIAMETER_MM = 2.0 * (
    DEFAULT_GUIDE_CHANNEL_RADIUS_MM + GUIDE_BORE_MARGIN_MM
)
DEFAULT_PARALLEL_ANGLE_TOLERANCE_DEG = 10.0


def guide_primary_bore_diameter_mm(
    channel_radius_mm: Optional[float] = None,
    bore_margin_mm: float = GUIDE_BORE_MARGIN_MM,
) -> float:
    """Return the physical diameter of the guide's primary needle bore."""

    radius = (
        DEFAULT_GUIDE_CHANNEL_RADIUS_MM
        if channel_radius_mm is None
        else float(channel_radius_mm)
    )
    margin = float(bore_margin_mm)
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError("channel_radius_mm must be a positive finite number")
    if not math.isfinite(margin) or margin < 0.0:
        raise ValueError("bore_margin_mm must be a finite non-negative number")
    return 2.0 * (radius + margin)


def resolve_parallel_needle_min_distance_mm(value: Optional[float] = None) -> float:
    """Resolve the minimum center distance for near-parallel needle paths.

    ``None`` means use the physical default guide-bore diameter.  An explicit
    value is retained for research/configuration overrides and is validated so
    invalid input cannot silently disable the safety rule.
    """

    if value is None:
        return DEFAULT_GUIDE_CHANNEL_DIAMETER_MM
    resolved = float(value)
    if not math.isfinite(resolved) or resolved <= 0.0:
        raise ValueError(
            "parallel_min_distance_mm must be a positive finite number"
        )
    return resolved


def resolve_parallel_angle_tolerance_deg(value: Optional[float] = None) -> float:
    """Resolve the angular tolerance used to classify two paths as parallel."""

    resolved = (
        DEFAULT_PARALLEL_ANGLE_TOLERANCE_DEG
        if value is None
        else float(value)
    )
    if not math.isfinite(resolved) or not 0.0 <= resolved < 90.0:
        raise ValueError(
            "parallel_angle_tolerance_deg must be in the range [0, 90)"
        )
    return resolved
