"""Patient-specific puncture-guide geometry in BrachyBot world coordinates.

The implementation intentionally mirrors the useful geometry stages from the
reference ``surgical_guide`` application without shelling out to its C++ GUI:

* derive a local skin-fitting plate from the CT body surface;
* intersect each planned needle with that skin surface;
* union printed guidance sleeves and subtract their inner bores; and
* serialise a watertight STL together with coordinate and QA provenance.

All public points are SimpleITK physical points.  That is the same patient
world-coordinate contract used by the planner, manual needle editor, viewer,
and DICOM import paths.  Do not add ad-hoc RAS/LPS flips in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import logging
import math
import re
import struct
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from plans.guide_geometry import (
    DEFAULT_GUIDE_CHANNEL_RADIUS_MM,
    GUIDE_BORE_MARGIN_MM,
)


logger = logging.getLogger(__name__)


class SurgicalGuideError(ValueError):
    """A clinically meaningful guide-generation precondition failed."""


DEFAULT_GUIDE_PARAMETERS: Dict[str, Any] = {
    "skin_threshold_hu": -300.0,
    "skin_clearance_mm": 1.0,
    "plate_thickness_mm": 3.0,
    "patch_margin_mm": 24.0,
    "channel_radius_mm": DEFAULT_GUIDE_CHANNEL_RADIUS_MM,
    "sleeve_outer_radius_mm": 3.0,
    "sleeve_outward_mm": 8.0,
    "sleeve_inward_mm": 8.0,
    # The reference guide's auxiliary-plan stage subtracts small catheter
    # bores from the already-built implant.  These bores are parallel to the
    # planned channel, flush with the plate, and never add an external sleeve.
    # Two 12-hole rings provide a dense, printable set of alternate entry
    # paths while leaving a clear wall around the primary channel.
    "auxiliary_holes_enabled": True,
    "auxiliary_hole_radius_mm": 1.3,
    "auxiliary_hole_ring_count": 2.0,
    "auxiliary_holes_per_ring": 12.0,
    "auxiliary_hole_first_offset_mm": 6.0,
    "auxiliary_hole_ring_spacing_mm": 3.0,
    # 0.2 mm is the default manufacturing grid.  It gives the primary bore
    # enough radial samples for a smooth STL even before the analytic wall
    # projection pass, while remaining bounded to the local guide patch.  A
    # coarser value remains available for preview/low-memory environments.
    "geometry_resolution_mm": 0.2,
    "minimum_component_voxels": 24.0,
    # Minimum distance the guide plate must keep from a truncated (finite-FOV)
    # CT superior/inferior boundary. The scan-boundary plane is a flat cut, not
    # anatomical skin, so the plate is shaved back by this margin AND every
    # plate voxel whose nearest body voxel sits on the boundary slice is
    # removed. If the remaining valid skin cannot support a needle's sleeve the
    # guide is rejected with a clear message instead of building on the cut.
    "truncation_margin_mm": 5.0,
}

# A bounded history preserves clinically reviewable guide alternatives without
# allowing repeated mesh generation to grow one case workspace without limit.
MAX_SAVED_GUIDE_VERSIONS = 5

# Stable identity for the exact CT-derived envelope used by guide generation.
# The mask is persisted separately from the printable guide mesh because it is
# also a first-class segmentation shown in the Data Tree and MPR viewers.
GUIDE_SKIN_OBJECT_ID = "skin_surface:guide"
GUIDE_SKIN_NODE_ID = "skin_surface"
GUIDE_SKIN_DEFAULT_COLOR = "#f2a088"
GUIDE_SKIN_DEFAULT_OPACITY = 0.10

# Extra radial clearance subtracted around every channel bore, beyond the
# nominal channel_radius. Without this, two nearby needle sleeves can merge and
# the wall of one sleeve intrudes into the neighbouring channel, partially
# plugging its opening. The margin keeps every channel a clean through-hole
# even for closely spaced needles (>= a printable wall thickness). The value
# is shared with the planner through ``plans.guide_geometry``.

# Minimum printable material left between independent bores or between an
# auxiliary bore and a primary sleeve.  Keep this manufacturing constraint in
# one place: parameter validation and cross-needle layout deconfliction must
# enforce the same physical wall thickness.
GUIDE_MINIMUM_WALL_MM = 0.35

# Auxiliary cylinders are construction tools, not printed geometry.  They
# must extend well beyond both sides of the guide shell so a curved skin
# surface cannot truncate a bore into a shallow half-hole.  The resulting STL
# still contains only the portion removed from the guide material.
AUXILIARY_HOLE_OVERRUN_MM = 8.0

# A main guidance channel must remain an open cylinder even where another
# sleeve crosses it outside the first sleeve's nominal length.  The CSG cutter
# therefore extends past its own plate/sleeve span and, when needed, across a
# neighbouring sleeve that can enter the channel.  These are construction
# margins only; they do not change the requested channel radius.
PRIMARY_BORE_CUTTER_END_OVERRUN_MM = 2.0
PRIMARY_BORE_CROSS_SLEEVE_GUARD_MM = 0.5

# A Planning run must export as one printable guide, even when distant needle
# groups produce non-overlapping local patches.  The bridge is routed on the
# CT-derived plate shell (never through the patient) and remains flush with the
# plate, so it preserves both the skin-facing surface and the configured plate
# thickness.  Eight millimetres leaves a practical load-bearing strip without
# materially enlarging the local guide footprint.
GUIDE_COMPONENT_BRIDGE_WIDTH_MM = 8.0
GUIDE_COMPONENT_BRIDGE_ROUTE_RESOLUTION_MM = 1.0
GUIDE_COMPONENT_BRIDGE_QUERY_CHUNK = 250_000


def _effective_primary_bore_radius_mm(params: Mapping[str, Any]) -> float:
    """Return the physical primary-hole radius written to the STL.

    The boolean CSG opens the nominal channel by GUIDE_BORE_MARGIN_MM.
    Auxiliary holes must use this same final radius, rather than the smaller
    legacy parameter, so every printed alternate path fits the same needle.
    """
    return float(params["channel_radius_mm"]) + GUIDE_BORE_MARGIN_MM

# Marching Cubes produces a deliberately watertight mesh, but its vertices at
# a cylindrical wall are still displaced slightly by voxelisation and by the
# shrink-free surface smoothing pass.  The final wall projection below uses a
# bounded tolerance, so only vertices belonging to a bore wall are corrected;
# sleeve edges, plate edges, and the skin-facing surface remain untouched.
BORE_WALL_PROJECTION_TOLERANCE_FACTOR = 1.25
BORE_WALL_PROJECTION_MIN_TOLERANCE_MM = 0.2
BORE_WALL_POLICY = "global_primary_csg_drilling_and_analytic_cylindrical_projection_v2"

_PARAMETER_LIMITS = {
    "skin_threshold_hu": (-800.0, 100.0),
    "skin_clearance_mm": (0.0, 5.0),
    "plate_thickness_mm": (1.0, 10.0),
    "patch_margin_mm": (10.0, 80.0),
    "channel_radius_mm": (0.3, 6.0),
    "sleeve_outer_radius_mm": (1.0, 12.0),
    "sleeve_outward_mm": (1.0, 30.0),
    "sleeve_inward_mm": (1.0, 30.0),
    # Compatibility input only. The normalized value is derived from the
    # final primary bore radius and may exceed the historical 1.5 mm limit.
    "auxiliary_hole_radius_mm": (0.3, 6.4),
    "auxiliary_hole_ring_count": (1.0, 4.0),
    "auxiliary_holes_per_ring": (4.0, 24.0),
    "auxiliary_hole_first_offset_mm": (2.0, 15.0),
    "auxiliary_hole_ring_spacing_mm": (1.5, 10.0),
    "geometry_resolution_mm": (0.2, 2.0),
    "minimum_component_voxels": (1.0, 10000.0),
    "truncation_margin_mm": (0.0, 40.0),
}


@dataclass(frozen=True)
class NeedleGuidePath:
    """One needle path and its CT-derived skin entry in world coordinates."""

    needle_id: str
    trajectory_id: str
    target: np.ndarray
    external: np.ndarray
    entry: np.ndarray
    inward_direction: np.ndarray
    seed_count: int


def _orthogonal_basis(direction: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return a stable right-handed basis perpendicular to a needle axis."""
    axis = np.asarray(direction, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(axis))
    if norm <= 1e-10:
        raise SurgicalGuideError("Needle direction is zero")
    axis = axis / norm
    # Pick the cardinal vector least aligned with the needle so the projection
    # remains well-conditioned for axial, sagittal, and coronal trajectories.
    reference = min(
        (np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])),
        key=lambda value: abs(float(np.dot(value, axis))),
    )
    first = reference - axis * float(np.dot(reference, axis))
    first /= max(float(np.linalg.norm(first)), 1e-12)
    second = np.cross(first, axis)
    second /= max(float(np.linalg.norm(second)), 1e-12)
    return first, second


def _segment_distance_mm(
    start_a: np.ndarray,
    end_a: np.ndarray,
    start_b: np.ndarray,
    end_b: np.ndarray,
) -> float:
    """Return the shortest distance between two finite 3D line segments."""
    p1 = np.asarray(start_a, dtype=np.float64).reshape(3)
    q1 = np.asarray(end_a, dtype=np.float64).reshape(3)
    p2 = np.asarray(start_b, dtype=np.float64).reshape(3)
    q2 = np.asarray(end_b, dtype=np.float64).reshape(3)
    direction_a = q1 - p1
    direction_b = q2 - p2
    offset = p1 - p2
    length_a_sq = float(np.dot(direction_a, direction_a))
    length_b_sq = float(np.dot(direction_b, direction_b))
    epsilon = 1e-12

    if length_a_sq <= epsilon and length_b_sq <= epsilon:
        return float(np.linalg.norm(p1 - p2))
    if length_a_sq <= epsilon:
        factor_b = float(np.clip(
            np.dot(direction_b, offset) / length_b_sq,
            0.0,
            1.0,
        ))
        return float(np.linalg.norm(p1 - (p2 + factor_b * direction_b)))
    if length_b_sq <= epsilon:
        factor_a = float(np.clip(
            -np.dot(direction_a, offset) / length_a_sq,
            0.0,
            1.0,
        ))
        return float(np.linalg.norm((p1 + factor_a * direction_a) - p2))

    direction_dot = float(np.dot(direction_a, direction_b))
    offset_a = float(np.dot(direction_a, offset))
    offset_b = float(np.dot(direction_b, offset))
    denominator = length_a_sq * length_b_sq - direction_dot * direction_dot
    factor_a = (
        float(np.clip(
            (direction_dot * offset_b - offset_a * length_b_sq) / denominator,
            0.0,
            1.0,
        ))
        if denominator > epsilon
        else 0.0
    )
    factor_b = (direction_dot * factor_a + offset_b) / length_b_sq
    if factor_b < 0.0:
        factor_b = 0.0
        factor_a = float(np.clip(-offset_a / length_a_sq, 0.0, 1.0))
    elif factor_b > 1.0:
        factor_b = 1.0
        factor_a = float(np.clip((direction_dot - offset_a) / length_a_sq, 0.0, 1.0))

    closest_a = p1 + factor_a * direction_a
    closest_b = p2 + factor_b * direction_b
    return float(np.linalg.norm(closest_a - closest_b))


def _primary_sleeve_segment(
    path: NeedleGuidePath,
    params: Mapping[str, Any],
) -> Tuple[np.ndarray, np.ndarray]:
    """Return the finite printed sleeve span for one planned needle.

    The start sits flush with the configured skin-clearance surface and the
    end points outward beyond the plate.  This remains the physical sleeve
    definition; the longer *cutter* used below only guarantees that no other
    sleeve wall can close this channel after unioning the guide solid.
    """
    inward = np.asarray(path.inward_direction, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(inward))
    if norm <= 1e-10:
        raise SurgicalGuideError(f"Needle {path.needle_id} has a zero direction")
    inward /= norm
    sleeve_inner = np.asarray(path.entry, dtype=np.float64).reshape(3) - inward * float(
        params["skin_clearance_mm"]
    )
    sleeve_outer = sleeve_inner - inward * (
        float(params["plate_thickness_mm"])
        + float(params["sleeve_outward_mm"])
    )
    return sleeve_inner, sleeve_outer


def _line_to_segment_distance_mm(
    line_origin: np.ndarray,
    line_direction: np.ndarray,
    segment_start: np.ndarray,
    segment_end: np.ndarray,
) -> float:
    """Return the shortest distance from an infinite line to a finite segment.

    Main-bore cutters are extended only across sleeves that can physically
    enter their cylindrical void.  Comparing a finite primary sleeve against
    another finite sleeve is insufficient when the crossing occurs just beyond
    the first sleeve tip, so this helper intentionally uses the complete
    primary channel line.
    """
    origin = np.asarray(line_origin, dtype=np.float64).reshape(3)
    direction = np.asarray(line_direction, dtype=np.float64).reshape(3)
    direction_norm = float(np.linalg.norm(direction))
    if direction_norm <= 1e-10:
        raise SurgicalGuideError("Primary bore direction is zero")
    direction /= direction_norm
    start = np.asarray(segment_start, dtype=np.float64).reshape(3)
    end = np.asarray(segment_end, dtype=np.float64).reshape(3)
    segment = end - start
    relative = start - origin
    relative_perpendicular = relative - direction * float(np.dot(relative, direction))
    segment_perpendicular = segment - direction * float(np.dot(segment, direction))
    denominator = float(np.dot(segment_perpendicular, segment_perpendicular))
    if denominator <= 1e-12:
        closest_factor = 0.0
    else:
        closest_factor = float(np.clip(
            -float(np.dot(relative_perpendicular, segment_perpendicular)) / denominator,
            0.0,
            1.0,
        ))
    closest_perpendicular = (
        relative_perpendicular + closest_factor * segment_perpendicular
    )
    return float(np.linalg.norm(closest_perpendicular))


def _primary_bore_cutter_specs(
    paths: Sequence[NeedleGuidePath],
    params: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Build final through-cutters that keep every main channel open.

    The printable sleeves are finite cylinders, but the primary CSG cutters
    must also cover any foreign sleeve that intersects a channel beyond its
    own nominal sleeve tip.  Without that extension, a later/nearby sleeve can
    leave a crescent or wall across an otherwise drilled primary opening.

    Each returned cutter keeps the same physical bore radius.  Only its axial
    span is enlarged, conservatively and only near a sleeve that can overlap
    the channel void, so guide generation remains local and performant.
    """
    bore_radius = _effective_primary_bore_radius_mm(params)
    sleeve_outer_radius = float(params["sleeve_outer_radius_mm"])
    resolution = float(params["geometry_resolution_mm"])
    end_overrun = max(PRIMARY_BORE_CUTTER_END_OVERRUN_MM, 2.0 * resolution)
    cross_sleeve_guard = max(PRIMARY_BORE_CROSS_SLEEVE_GUARD_MM, 2.0 * resolution)
    sleeves = [
        (path, *_primary_sleeve_segment(path, params))
        for path in paths
    ]
    cutters: List[Dict[str, Any]] = []
    for path, sleeve_inner, sleeve_outer in sleeves:
        axis_vector = sleeve_outer - sleeve_inner
        sleeve_length = float(np.linalg.norm(axis_vector))
        if sleeve_length <= 1e-10:
            raise SurgicalGuideError(f"Needle {path.needle_id} has a zero sleeve length")
        outward_axis = axis_vector / sleeve_length
        lower = -end_overrun
        upper = sleeve_length + end_overrun
        crossings: List[Dict[str, Any]] = []
        trigger_distance = bore_radius + sleeve_outer_radius + cross_sleeve_guard
        for other_path, other_inner, other_outer in sleeves:
            if other_path.needle_id == path.needle_id:
                continue
            centerline_distance = _line_to_segment_distance_mm(
                sleeve_inner,
                outward_axis,
                other_inner,
                other_outer,
            )
            if centerline_distance > trigger_distance:
                continue
            other_start_projection = float(
                np.dot(other_inner - sleeve_inner, outward_axis)
            )
            other_end_projection = float(
                np.dot(other_outer - sleeve_inner, outward_axis)
            )
            # A finite foreign sleeve can extend one outer radius beyond each
            # endpoint along this cutter axis. Include that cap extent plus a
            # sub-voxel manufacturing guard before drilling the final union.
            extension = sleeve_outer_radius + end_overrun
            lower = min(lower, min(other_start_projection, other_end_projection) - extension)
            upper = max(upper, max(other_start_projection, other_end_projection) + extension)
            crossings.append({
                "needle_id": str(other_path.needle_id),
                "centerline_distance_mm": float(centerline_distance),
            })
        cutters.append({
            "needle_id": str(path.needle_id),
            "start": sleeve_inner + outward_axis * lower,
            "end": sleeve_inner + outward_axis * upper,
            "radius_mm": float(bore_radius),
            "nominal_start": sleeve_inner,
            "nominal_end": sleeve_outer,
            "nominal_length_mm": float(sleeve_length),
            "cutter_length_mm": float(upper - lower),
            "crossing_sleeves": crossings,
        })
    return cutters


def _auxiliary_hole_specs(
    paths: Sequence[NeedleGuidePath],
    params: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Build the non-protruding alternate puncture cylinders.

    This is the native equivalent of the reference application's auxiliary
    planning stage: each small cylinder is parallel to its main needle, is
    centred at a radial offset around the entry axis, and is subtracted only
    from the plate shell.  It never creates an outer sleeve and therefore
    cannot replace, extend, or obstruct a primary guidance channel.
    """
    if not bool(params.get("auxiliary_holes_enabled", False)):
        return []
    ring_count = int(params["auxiliary_hole_ring_count"])
    holes_per_ring = int(params["auxiliary_holes_per_ring"])
    first_offset = float(params["auxiliary_hole_first_offset_mm"])
    ring_spacing = float(params["auxiliary_hole_ring_spacing_mm"])
    # Derive this again at the geometry boundary so direct callers and old
    # saved parameter payloads cannot create a smaller auxiliary hole.
    radius = _effective_primary_bore_radius_mm(params)
    clearance = float(params["skin_clearance_mm"])
    plate_thickness = float(params["plate_thickness_mm"])
    primary_outer_radius = float(params["sleeve_outer_radius_mm"])
    minimum_primary_centerline_distance = (
        primary_outer_radius + radius + GUIDE_MINIMUM_WALL_MM
    )
    specs: List[Dict[str, Any]] = []
    path_order = {path.needle_id: index for index, path in enumerate(paths)}
    primary_segments: List[Dict[str, Any]] = []
    for path in paths:
        inward = np.asarray(path.inward_direction, dtype=np.float64).reshape(3)
        inward /= max(float(np.linalg.norm(inward)), 1e-12)
        sleeve_inner = np.asarray(path.entry, dtype=np.float64) - inward * clearance
        sleeve_outer = sleeve_inner - inward * (
            plate_thickness + float(params["sleeve_outward_mm"])
        )
        primary_segments.append({
            "needle_id": path.needle_id,
            "start": sleeve_inner,
            "end": sleeve_outer,
        })

    for path in paths:
        inward = np.asarray(path.inward_direction, dtype=np.float64).reshape(3)
        inward /= max(float(np.linalg.norm(inward)), 1e-12)
        axis_a, axis_b = _orthogonal_basis(inward)
        for ring_index in range(ring_count):
            radial_offset = first_offset + ring_index * ring_spacing
            # Stagger successive rings so the pattern remains dense without
            # putting every hole on one radial spoke.
            phase = (ring_index % 2) * (math.pi / holes_per_ring)
            for hole_index in range(holes_per_ring):
                angle = phase + 2.0 * math.pi * hole_index / holes_per_ring
                offset_direction = math.cos(angle) * axis_a + math.sin(angle) * axis_b
                center = np.asarray(path.entry, dtype=np.float64) + radial_offset * offset_direction
                start = center - inward * (
                    clearance + plate_thickness + AUXILIARY_HOLE_OVERRUN_MM
                )
                end = center + inward * (clearance + AUXILIARY_HOLE_OVERRUN_MM)
                item: Dict[str, Any] = {
                    "id": f"aux_{path.needle_id}_{ring_index + 1}_{hole_index + 1}",
                    "needle_id": path.needle_id,
                    "trajectory_id": path.trajectory_id,
                    "ring_index": ring_index + 1,
                    "hole_index": hole_index + 1,
                    "angle_degrees": math.degrees(angle) % 360.0,
                    "radial_offset_mm": radial_offset,
                    "radius_mm": radius,
                    "center": center,
                    "start": start,
                    "end": end,
                    "skipped": False,
                    "skip_reason": None,
                }
                # Check the entire finite cylinder against every primary
                # sleeve, not only its entry point. Oblique channels can be
                # clear at the skin while intersecting deeper in the plate.
                primary_conflicts = []
                for primary in primary_segments:
                    centerline_distance = _segment_distance_mm(
                        start,
                        end,
                        np.asarray(primary["start"], dtype=np.float64),
                        np.asarray(primary["end"], dtype=np.float64),
                    )
                    if centerline_distance + 1e-6 < minimum_primary_centerline_distance:
                        primary_conflicts.append((centerline_distance, primary))
                if primary_conflicts:
                    centerline_distance, conflict = min(
                        primary_conflicts,
                        key=lambda value: value[0],
                    )
                    item.update({
                        "skipped": True,
                        "skip_reason": "nearby_primary_channel",
                        "conflicts_with": str(conflict["needle_id"]),
                        "centerline_distance_mm": float(centerline_distance),
                        "surface_clearance_mm": float(
                            centerline_distance - radius - primary_outer_radius
                        ),
                    })
                specs.append(item)

    # Interleave paths while accepting candidates so a dense cluster does not
    # let the first needle consume every printable alternate location.  A
    # candidate is retained only if its complete finite cylinder leaves the
    # required wall around all previously accepted auxiliary bores.
    accepted: List[Dict[str, Any]] = []
    candidates = sorted(
        (item for item in specs if not bool(item.get("skipped"))),
        key=lambda item: (
            int(item["ring_index"]),
            int(item["hole_index"]),
            path_order.get(str(item["needle_id"]), len(path_order)),
        ),
    )
    minimum_auxiliary_centerline_distance = 2.0 * radius + GUIDE_MINIMUM_WALL_MM
    for item in candidates:
        conflicts = []
        for prior in accepted:
            centerline_distance = _segment_distance_mm(
                np.asarray(item["start"], dtype=np.float64),
                np.asarray(item["end"], dtype=np.float64),
                np.asarray(prior["start"], dtype=np.float64),
                np.asarray(prior["end"], dtype=np.float64),
            )
            if centerline_distance + 1e-6 < minimum_auxiliary_centerline_distance:
                conflicts.append((centerline_distance, prior))
        if conflicts:
            centerline_distance, conflict = min(conflicts, key=lambda value: value[0])
            item.update({
                "skipped": True,
                "skip_reason": "nearby_auxiliary_hole",
                "conflicts_with": str(conflict["id"]),
                "centerline_distance_mm": float(centerline_distance),
                "surface_clearance_mm": float(centerline_distance - 2.0 * radius),
            })
            continue
        accepted.append(item)
    return specs


def _finite_float(value: Any, name: str, lower: float, upper: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SurgicalGuideError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed) or parsed < lower or parsed > upper:
        raise SurgicalGuideError(f"{name} must be between {lower:g} and {upper:g}")
    return parsed


def _finite_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        if float(value) in (0.0, 1.0):
            return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise SurgicalGuideError(f"{name} must be boolean")


def _finite_integer(value: Any, name: str, lower: float, upper: float) -> float:
    parsed = _finite_float(value, name, lower, upper)
    rounded = round(parsed)
    if abs(parsed - rounded) > 1e-6:
        raise SurgicalGuideError(f"{name} must be an integer between {lower:g} and {upper:g}")
    return float(rounded)


def normalize_guide_parameters(raw: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Validate guide parameters and enforce one physical bore diameter."""
    raw = raw if isinstance(raw, Mapping) else {}
    auxiliary_parameter_names = {
        "auxiliary_holes_enabled",
        "auxiliary_hole_radius_mm",
        "auxiliary_hole_ring_count",
        "auxiliary_holes_per_ring",
        "auxiliary_hole_first_offset_mm",
        "auxiliary_hole_ring_spacing_mm",
    }
    legacy_parameter_names = {
        "skin_threshold_hu",
        "skin_clearance_mm",
        "plate_thickness_mm",
        "patch_margin_mm",
        "channel_radius_mm",
        "sleeve_outer_radius_mm",
        "sleeve_outward_mm",
        "sleeve_inward_mm",
    }
    # Parameter snapshots created before auxiliary holes existed must continue
    # to reproduce their original guide. New UI/tool requests include at least
    # the enable flag, while a new partial request such as only changing the
    # grid resolution should still use the new default. The compatibility rule
    # therefore requires an old manufacturing parameter, not merely any raw
    # parameter. The auxiliary radius is a derived manufacturing value, so an
    # explicit legacy auxiliary-hole field cannot create a second diameter.
    legacy_without_auxiliary_parameters = bool(
        legacy_parameter_names.intersection(raw.keys())
        and not auxiliary_parameter_names.intersection(raw.keys())
    )
    params = dict(DEFAULT_GUIDE_PARAMETERS)
    for name, default in DEFAULT_GUIDE_PARAMETERS.items():
        if isinstance(default, bool):
            params[name] = _finite_bool(raw.get(name, default), name)
            continue
        lower, upper = _PARAMETER_LIMITS[name]
        if name in {"auxiliary_hole_ring_count", "auxiliary_holes_per_ring"}:
            params[name] = _finite_integer(raw.get(name, default), name, lower, upper)
        else:
            params[name] = _finite_float(raw.get(name, default), name, lower, upper)
    if legacy_without_auxiliary_parameters:
        params["auxiliary_holes_enabled"] = False
    # The primary boolean bore is opened by GUIDE_BORE_MARGIN_MM. Persist that
    # final radius as the canonical auxiliary radius so metadata, QA, and the
    # exported STL all describe the same physical hole.
    params["auxiliary_hole_radius_mm"] = _effective_primary_bore_radius_mm(params)
    if (
        params["sleeve_outer_radius_mm"]
        <= params["channel_radius_mm"] + GUIDE_MINIMUM_WALL_MM
    ):
        raise SurgicalGuideError(
            "sleeve_outer_radius_mm must exceed channel_radius_mm by at least 0.35 mm"
        )
    if params["auxiliary_holes_enabled"]:
        auxiliary_radius = _effective_primary_bore_radius_mm(params)
        primary_outer_radius = float(params["sleeve_outer_radius_mm"])
        minimum_primary_clearance = (
            primary_outer_radius + auxiliary_radius + GUIDE_MINIMUM_WALL_MM
        )
        if float(params["auxiliary_hole_first_offset_mm"]) < minimum_primary_clearance:
            raise SurgicalGuideError(
                "auxiliary_hole_first_offset_mm must leave at least 0.35 mm of wall "
                "outside the primary sleeve"
            )
        if float(params["auxiliary_hole_ring_count"]) > 1:
            if float(params["auxiliary_hole_ring_spacing_mm"]) < (
                2.0 * auxiliary_radius + GUIDE_MINIMUM_WALL_MM
            ):
                raise SurgicalGuideError(
                    "auxiliary_hole_ring_spacing_mm is too small for a printable wall"
                )
        ring_count = int(params["auxiliary_hole_ring_count"])
        holes_per_ring = int(params["auxiliary_holes_per_ring"])
        for ring in range(ring_count):
            radius = float(params["auxiliary_hole_first_offset_mm"]) + ring * float(
                params["auxiliary_hole_ring_spacing_mm"]
            )
            chord = 2.0 * radius * math.sin(math.pi / holes_per_ring)
            if chord < (2.0 * auxiliary_radius + GUIDE_MINIMUM_WALL_MM):
                raise SurgicalGuideError(
                    "auxiliary holes on a ring are too dense for a printable wall"
                )
            if radius + auxiliary_radius > float(params["patch_margin_mm"]):
                raise SurgicalGuideError(
                    "auxiliary hole rings must fit inside patch_margin_mm"
                )
    return params


def _as_point(value: Any, field: str) -> np.ndarray:
    try:
        point = np.asarray(value, dtype=np.float64).reshape(-1)[:3]
    except Exception as exc:  # pragma: no cover - defensive parsing path.
        raise SurgicalGuideError(f"Invalid {field}") from exc
    if point.size != 3 or not np.all(np.isfinite(point)):
        raise SurgicalGuideError(f"Invalid {field}")
    return point


def _algorithm_planning_snapshot(agent: Any) -> Dict[str, List[Dict[str, Any]]]:
    """Read the immutable automatic planning baseline geometry.

    The puncture guide is generated from the approved planned needle paths.  A
    manual needle/seed addition extends that geometry but does not invalidate
    the algorithm-derived guide; using the manual-superseding snapshot for
    guide *matching* made a single added manual needle change the plan
    signature, hide an otherwise valid guide, and disable its regenerate path.
    Signature checks that decide whether an existing guide is still valid must
    therefore compare against this baseline, not the display snapshot.
    """
    memory = agent.memory
    baseline = memory.retrieve("algorithm_plan_snapshot")
    if isinstance(baseline, Mapping):
        return {
            "seeds": list(baseline.get("seeds") or []),
            "needles": list(baseline.get("needles") or []),
        }
    serialized = memory.retrieve("seed_plan_serialized") or []
    geometry = memory.retrieve("verified_needle_geometry") or {}
    seeds: List[Dict[str, Any]] = []
    needles: List[Dict[str, Any]] = []
    for trajectory_index, entry in enumerate(serialized):
        if not isinstance(entry, Mapping):
            continue
        trajectory_id = f"traj_{trajectory_index + 1}"
        for seed_index, seed in enumerate(entry.get("seeds") or []):
            if isinstance(seed, Mapping):
                position = seed.get("position") or seed.get("pos")
                direction = seed.get("direction") or seed.get("dir")
            elif isinstance(seed, (list, tuple)) and len(seed) >= 2:
                position, direction = seed[0], seed[1]
            else:
                continue
            try:
                seeds.append({
                    "id": f"seed_{trajectory_index}_{seed_index}",
                    "position": _as_point(position, "seed position").tolist(),
                    "direction": _as_point(direction, "seed direction").tolist(),
                    "trajectory_id": trajectory_id,
                })
            except SurgicalGuideError:
                continue
        points = geometry.get(str(trajectory_index)) if isinstance(geometry, Mapping) else None
        if isinstance(points, list) and len(points) >= 2:
            try:
                needles.append({
                    "id": f"needle_{trajectory_index}",
                    "trajectory_id": trajectory_id,
                    "points": [_as_point(points[0], "needle point").tolist(),
                               _as_point(points[-1], "needle point").tolist()],
                })
            except SurgicalGuideError:
                continue
    return {"seeds": seeds, "needles": needles}


def _current_planning_snapshot(agent: Any) -> Dict[str, List[Dict[str, Any]]]:
    """Read the displayed planning geometry without reconstructing coordinates.

    ``algorithm_plan_snapshot`` is the immutable automatic baseline.  Manual
    arrays supersede it only after an explicit edit, matching the viewer and
    manual-dose routes.  This keeps guide generation stable across restores.
    """
    memory = agent.memory
    manual_seeds = memory.retrieve("manual_seeds") or []
    manual_needles = memory.retrieve("manual_needles") or []
    if manual_seeds or manual_needles:
        return {"seeds": list(manual_seeds), "needles": list(manual_needles)}
    return _algorithm_planning_snapshot(agent)


def available_guide_needles(agent: Any) -> List[Dict[str, Any]]:
    """Expose selectable guide channels from the current plan, not UI guesses."""
    if agent is None or not hasattr(agent, "memory"):
        return []
    snapshot = _current_planning_snapshot(agent)
    seed_counts: Dict[str, int] = {}
    for seed in snapshot["seeds"]:
        if isinstance(seed, Mapping):
            trajectory_id = str(seed.get("trajectory_id") or "")
            seed_counts[trajectory_id] = seed_counts.get(trajectory_id, 0) + 1
    needles: List[Dict[str, Any]] = []
    for index, needle in enumerate(snapshot["needles"]):
        if not isinstance(needle, Mapping):
            continue
        needle_id = str(needle.get("id") or f"needle_{index}")
        trajectory_id = str(needle.get("trajectory_id") or needle_id)
        points = needle.get("points")
        if not isinstance(points, list) or len(points) < 2:
            continue
        needles.append({
            "id": needle_id,
            "trajectory_id": trajectory_id,
            "seed_count": int(seed_counts.get(trajectory_id, 0)),
        })
    return needles


def planning_signature(snapshot: Mapping[str, Any]) -> str:
    """Return a stable provenance hash for guide invalidation decisions."""
    compact = {
        "seeds": snapshot.get("seeds") or [],
        "needles": snapshot.get("needles") or [],
    }
    encoded = json.dumps(compact, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def guide_bore_quality_ready(state: Any) -> bool:
    """Return whether a persisted guide has the printable circular-wall QA."""
    if not isinstance(state, Mapping):
        return False
    validation = state.get("validation")
    quality = validation.get("bore_quality") if isinstance(validation, Mapping) else None
    return isinstance(quality, Mapping) and quality.get("wall_policy") == BORE_WALL_POLICY


def _guide_payload_present(value: Any) -> bool:
    """Return whether a guide field contains usable persisted data.

    Workspace hydration deliberately restores JSON metadata before decoding
    large mesh sidecars.  A truthiness check is unsafe here: NumPy arrays have
    no scalar truth value, while a metadata shell may contain an empty list or
    ``None`` for ``vertices``/``faces``.  Keep this predicate local to the
    guide read boundary so every caller agrees about what "loaded" means.
    """
    if value is None:
        return False
    if isinstance(value, np.ndarray):
        return value.size > 0
    if isinstance(value, (str, bytes, bytearray)):
        return bool(value)
    if isinstance(value, (Mapping, list, tuple, set)):
        return bool(value)
    return True


def guide_mesh_loaded(state: Any) -> bool:
    """Return whether both persisted mesh arrays are available for display."""
    return isinstance(state, Mapping) and _guide_payload_present(state.get("vertices")) and _guide_payload_present(state.get("faces"))


def _read_active_planning_id(agent: Any) -> str:
    """Read the active Planning identity without mutating session state.

    Status queries run while a workspace is being restored.  Calling the
    legacy ``active_planning_id`` migration helper from this read path can
    create or rewrite registry entries while the authoritative snapshot is
    still arriving.  Prefer the persisted identity, then infer it only from
    the already-restored compact registry.
    """
    memory = getattr(agent, "memory", None)
    if memory is None:
        return ""
    for key in ("active_planning_id", "planning_run_id"):
        try:
            value = memory.retrieve(key)
        except Exception:
            value = None
        if value:
            return str(value)
    try:
        runs = memory.retrieve("planning_runs") or []
    except Exception:
        runs = []
    if not isinstance(runs, list):
        return ""
    visible = [item for item in runs if isinstance(item, Mapping) and item.get("visible")]
    candidates = visible or [item for item in runs if isinstance(item, Mapping)]
    if not candidates:
        return ""
    selected = max(
        candidates,
        key=lambda item: (
            int(item.get("sequence") or 0),
            float(item.get("updated_at") or item.get("created_at") or 0.0),
        ),
    )
    return str(selected.get("planning_id") or "")


def _guide_matches_active_planning(state: Mapping[str, Any], active_planning_id: str) -> bool:
    """Reject a guide from a different active Planning run.

    Older single-guide checkpoints did not record ``planning_id``.  They are
    still valid when exposed through the active alias; only an explicit,
    conflicting identity is disqualifying.
    """
    if not active_planning_id:
        return True
    stored = str(state.get("planning_id") or "").strip()
    return not stored or stored == active_planning_id


def _guide_records(agent: Any) -> List[Dict[str, Any]]:
    """Collect guide records from live aliases and the active run snapshot.

    The legacy top-level aliases are convenient for the current Viewer, but
    the immutable ``planning_run:<id>`` snapshot is the durable source of
    truth after a restart.  Returning source-labelled candidates lets callers
    prefer a decoded active alias while still recovering a guide whose alias
    was omitted by an older or partial checkpoint.
    """
    if agent is None or not hasattr(agent, "memory"):
        return []
    memory = agent.memory
    active_id = _read_active_planning_id(agent)
    records: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(value: Any, source: str, *, current: bool = False) -> None:
        if not isinstance(value, Mapping):
            return
        item = dict(value)
        planning_id = str(item.get("planning_id") or "")
        version = str(item.get("version") or "")
        signature = str(item.get("source_plan_signature") or "")
        key = (planning_id, version, signature)
        # Keep duplicate records when one has a decoded mesh and the other is
        # only metadata; the resolver below can then choose the usable one.
        if key in seen and not guide_mesh_loaded(item):
            return
        if guide_mesh_loaded(item):
            seen.add(key)
        records.append({
            "state": item,
            "source": source,
            "current": bool(current),
            "planning_id": planning_id,
            "mesh_loaded": guide_mesh_loaded(item),
        })

    try:
        add(memory.retrieve("surgical_guide"), "active_alias", current=True)
        top_history = memory.retrieve("surgical_guide_versions") or []
    except Exception:
        top_history = []
    if isinstance(top_history, list):
        for item in top_history:
            add(item, "guide_history")

    if active_id:
        try:
            snapshot = memory.retrieve("planning_run:" + active_id)
        except Exception:
            snapshot = None
        if isinstance(snapshot, Mapping):
            add(snapshot.get("surgical_guide"), "active_planning_snapshot", current=True)
            snapshot_history = snapshot.get("surgical_guide_versions") or []
            if isinstance(snapshot_history, list):
                for item in snapshot_history:
                    add(item, "active_planning_snapshot_history")
    return records


def _current_guide_record(agent: Any) -> Optional[Dict[str, Any]]:
    """Resolve the guide belonging to the active Planning, if any."""
    active_id = _read_active_planning_id(agent)
    candidates = [
        record for record in _guide_records(agent)
        if _guide_matches_active_planning(record["state"], active_id)
    ]
    if not candidates:
        return None

    # A decoded mesh is strictly more useful than a metadata shell.  Among
    # equally usable records, prefer the live alias over immutable history so
    # a just-completed generation is visible before the next checkpoint.
    source_rank = {
        "active_alias": 4,
        "active_planning_snapshot": 3,
        "guide_history": 2,
        "active_planning_snapshot_history": 1,
    }
    return max(
        candidates,
        key=lambda record: (
            1 if record.get("mesh_loaded") else 0,
            1 if str(record["state"].get("status") or "").lower() in {"ready", "stale", "expired", "outdated"} else 0,
            source_rank.get(record.get("source"), 0),
            int(record["state"].get("version") or 0),
        ),
    )


def _compact_guide_state(state: Any) -> Dict[str, Any]:
    """Copy guide metadata without exposing large mesh arrays."""
    if not isinstance(state, Mapping):
        return {}
    compact = dict(state)
    compact.pop("vertices", None)
    compact.pop("faces", None)
    return compact


def guide_status_payload(agent: Any, version: Optional[Any] = None) -> Dict[str, Any]:
    """Return a hydration-aware, source-backed guide status contract.

    ``not_generated`` is emitted only after the workspace is fully hydrated
    and no current or persisted guide exists.  During a cold restore the
    contract intentionally reports ``restoring`` or
    ``persisted_not_loaded``—never absence—so the chat, API and Viewer cannot
    turn a temporary alias/mesh gap into a false clinical conclusion.
    """
    if agent is None or not hasattr(agent, "memory"):
        return {
            "state": "unavailable",
            "available": False,
            "generated": False,
            "persisted": False,
            "persistence_known": False,
            "mesh_loaded": False,
            "presentation": "unavailable",
            "source": "none",
            "active_planning_id": None,
            "planning_id": None,
            "version": None,
            "status": None,
            "reason": "case_agent_unavailable",
        }

    requested_record: Optional[Dict[str, Any]] = None
    if version not in (None, ""):
        try:
            requested = int(version)
        except (TypeError, ValueError) as exc:
            raise SurgicalGuideError("Guide version must be an integer") from exc
        requested_record = next(
            (
                record for record in _guide_records(agent)
                if int(record["state"].get("version") or 0) == requested
            ),
            None,
        )
        if requested_record is None:
            raise SurgicalGuideError(f"Puncture guide version {requested} does not exist")

    record = requested_record or _current_guide_record(agent)
    state = record.get("state") if record else {}
    state = dict(state) if isinstance(state, Mapping) else {}
    raw_status = str(state.get("status") or "").strip().lower()
    hydration_error = str(getattr(agent, "_workspace_hydration_error", "") or "").strip()
    hydration_in_progress = bool(
        getattr(agent, "_workspace_hydration_in_progress", False)
        or not getattr(agent, "_workspace_data_ready", True)
    )
    active_id = _read_active_planning_id(agent)
    mesh_loaded = guide_mesh_loaded(state)
    persisted = bool(record)

    # A workspace-level hydration error does not erase a guide record that is
    # already present.  Keep reporting that guide (as ready or
    # persisted-not-loaded according to its own payload) and expose the
    # hydration error as an auxiliary diagnostic.  Only an error with no guide
    # record can make the guide status unavailable.
    if hydration_error and not persisted:
        lifecycle = "unavailable"
        reason = "workspace_hydration_failed"
    elif raw_status in {"running", "generating", "pending", "loading"}:
        lifecycle = "generating"
        reason = "guide_generation_in_progress"
    elif raw_status in {"failed", "error", "rejected"}:
        lifecycle = "failed"
        reason = str(state.get("error") or state.get("message") or "guide_generation_failed")
    elif raw_status in {"stale", "expired", "outdated"}:
        lifecycle = "stale"
        reason = str(state.get("stale_reason") or "guide_does_not_match_current_planning")
    elif persisted:
        lifecycle = "ready" if mesh_loaded and not hydration_in_progress else "persisted_not_loaded"
        reason = (
            "guide_mesh_loaded"
            if lifecycle == "ready"
            else "guide_persisted_but_mesh_not_decoded"
        )
    elif hydration_in_progress:
        lifecycle = "restoring"
        reason = "workspace_hydration_in_progress"
    else:
        lifecycle = "not_generated"
        reason = "no_persisted_guide_for_active_planning"

    # A version explicitly requested from history may belong to an older
    # Planning.  It remains inspectable, but the current-plan match must be
    # explicit so the Viewer never promotes it as the active guide.
    plan_matches: Optional[bool] = None
    if state and active_id:
        stored_id = str(state.get("planning_id") or "")
        plan_matches = not stored_id or stored_id == active_id
    # Planning identity alone is not enough: a guide may have been persisted
    # under the same run and then become stale after a needle edit.  Compare
    # signatures only when the current geometry has actually been restored;
    # an empty metadata shell must remain ``unknown`` rather than becoming a
    # false mismatch during the restore window.
    stored_signature = str(state.get("source_plan_signature") or "") if state else ""
    current_signature = ""
    if state and not hydration_in_progress:
        try:
            current_geometry = _algorithm_planning_snapshot(agent)
            if current_geometry.get("seeds") or current_geometry.get("needles"):
                current_signature = planning_signature(current_geometry)
        except Exception:
            current_signature = ""
    if stored_signature and current_signature:
        plan_matches = stored_signature == current_signature
    if plan_matches is False and lifecycle in {"ready", "persisted_not_loaded"}:
        lifecycle = "stale"
        reason = (
            "guide_belongs_to_another_planning_run"
            if requested_record
            else "guide_does_not_match_current_planning_geometry"
        )

    if lifecycle == "ready":
        presentation = "loaded"
    elif lifecycle in {"restoring", "persisted_not_loaded", "generating"}:
        presentation = "restoring"
    elif persisted and mesh_loaded:
        presentation = "loaded"
    elif lifecycle == "not_generated":
        presentation = "unavailable"
    else:
        presentation = "not_presented"

    persistence_known = bool(record) or (
        not hydration_in_progress and not hydration_error
    )
    return {
        "state": lifecycle,
        "available": persisted,
        "generated": bool(persisted and lifecycle not in {"failed", "unavailable", "generating"}),
        "persisted": persisted,
        # An empty store during hydration is not evidence that no guide was
        # persisted.  Keep this explicitly unknown until the restore barrier
        # has passed; callers may then safely distinguish absence from a
        # temporary read gap.
        "persistence_known": persistence_known,
        "mesh_loaded": mesh_loaded,
        "presentation": presentation,
        "source": record.get("source") if record else "none",
        "active_planning_id": active_id or None,
        "planning_id": state.get("planning_id") if state else None,
        "version": state.get("version") if state else None,
        "status": state.get("status") if state else None,
        "selected_needle_ids": list(state.get("selected_needle_ids") or []) if state else [],
        "stale_reason": state.get("stale_reason") if state else None,
        "plan_matches_current": plan_matches,
        "source_plan_signature": stored_signature or None,
        "current_plan_signature": current_signature or None,
        "hydration_pending": hydration_in_progress,
        "hydration_phase": getattr(agent, "_workspace_hydration_phase", "ready"),
        "hydration_error": hydration_error or None,
        "reason": reason,
        "guide": _compact_guide_state(state) if state else None,
    }


def invalidate_surgical_guides(agent: Any, reason: str) -> bool:
    """Mark an existing guide stale after a geometry-changing plan mutation."""
    if agent is None or not hasattr(agent, "memory"):
        return False
    timestamp = float(__import__("time").time())

    def stale(state: Mapping[str, Any]) -> Dict[str, Any]:
        updated = dict(state)
        updated["status"] = "stale"
        updated["stale_reason"] = str(reason or "planning geometry changed")
        updated["stale_at"] = timestamp
        return updated

    current = agent.memory.retrieve("surgical_guide")
    versions = agent.memory.retrieve("surgical_guide_versions") or []
    changed = False
    if isinstance(current, Mapping):
        agent.memory.store("surgical_guide", stale(current))
        changed = True
    if isinstance(versions, list):
        updated_versions = [stale(item) if isinstance(item, Mapping) else item for item in versions]
        if updated_versions:
            agent.memory.store("surgical_guide_versions", updated_versions)
            changed = True
    return changed


def guide_version_summaries(agent: Any) -> List[Dict[str, Any]]:
    """Return compact, session-owned guide history without mesh arrays."""
    if agent is None or not hasattr(agent, "memory"):
        return []
    # History was originally stored only in the mutable top-level alias.  A
    # cold restore can expose the immutable active-run snapshot first, so
    # merge both locations and de-duplicate by version/planning identity.
    records = _guide_records(agent)
    versions: List[Mapping[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for record in records:
        item = record.get("state")
        if not isinstance(item, Mapping):
            continue
        key = (
            int(item.get("version") or 0),
            str(item.get("planning_id") or ""),
        )
        if key in seen:
            # Prefer the record with a decoded mesh, which is useful to a
            # caller selecting a version immediately after hydration.
            existing_index = next(
                (
                    index for index, candidate in enumerate(versions)
                    if (
                        int(candidate.get("version") or 0),
                        str(candidate.get("planning_id") or ""),
                    ) == key
                ),
                None,
            )
            if (
                existing_index is not None
                and guide_mesh_loaded(item)
                and not guide_mesh_loaded(versions[existing_index])
            ):
                versions[existing_index] = item
            continue
        seen.add(key)
        versions.append(item)
    summaries: List[Dict[str, Any]] = []
    for item in versions:
        if not isinstance(item, Mapping):
            continue
        summaries.append({
            "version": int(item.get("version") or 0),
            "planning_id": item.get("planning_id"),
            "label": str(item.get("label") or "Puncture guide"),
            "status": str(item.get("status") or "unknown"),
            "selected_needle_ids": list(item.get("selected_needle_ids") or []),
            "parameters": dict(item.get("parameters") or {}),
            "created_at": item.get("created_at"),
            "stale_reason": item.get("stale_reason"),
            "stl_artifact": item.get("stl_artifact"),
            "mesh_loaded": guide_mesh_loaded(item),
        })
    return sorted(summaries, key=lambda item: item["version"], reverse=True)


def guide_state_for_version(agent: Any, version: Optional[Any] = None) -> Dict[str, Any]:
    """Resolve a saved version from the active alias or durable run snapshot."""
    if agent is None or not hasattr(agent, "memory"):
        return {}
    if version not in (None, ""):
        try:
            requested = int(version)
        except (TypeError, ValueError) as exc:
            raise SurgicalGuideError("Guide version must be an integer") from exc
        for record in _guide_records(agent):
            item = record.get("state")
            if isinstance(item, Mapping) and int(item.get("version") or 0) == requested:
                return dict(item)
        raise SurgicalGuideError(f"Puncture guide version {requested} does not exist")
    current = _current_guide_record(agent)
    if current and isinstance(current.get("state"), Mapping):
        return dict(current["state"])
    return {}


def _guide_history_for_version(agent: Any, previous: Any) -> list[Dict[str, Any]]:
    """Return the immutable guide history plus the legacy active guide alias."""
    history = [
        dict(item)
        for item in (agent.memory.retrieve("surgical_guide_versions") or [])
        if isinstance(item, Mapping) and int(item.get("version") or 0) > 0
    ]
    if isinstance(previous, Mapping):
        previous_version = int(previous.get("version") or 0)
        if previous_version > 0 and not any(
            int(item.get("version") or 0) == previous_version for item in history
        ):
            history.append(dict(previous))
    by_version = {int(item.get("version") or 0): item for item in history}
    return [by_version[version] for version in sorted(by_version)]


def _resolve_guide_version(
    agent: Any,
    previous: Any,
    signature: str,
    parameters: Mapping[str, Any],
    planning_id: Optional[str],
) -> int:
    """Choose a stable version without reusing a guide from another plan.

    The active ``surgical_guide`` key is intentionally replaced when a new
    Planning is created.  Version allocation therefore cannot rely on that
    alias alone; it must inspect ``surgical_guide_versions``.  A duplicate
    generation for the same Planning may reuse its version, while a new
    Planning always gets the next monotonically increasing version.
    """
    history = _guide_history_for_version(agent, previous)
    current_id = str(planning_id or "")
    for candidate in reversed(history):
        if (
            str(candidate.get("source_plan_signature") or "") == str(signature)
            and (candidate.get("parameters") or {}) == dict(parameters)
        ):
            candidate_id = str(candidate.get("planning_id") or "")
            if current_id and candidate_id and candidate_id != current_id:
                continue
            return int(candidate.get("version") or 0)
    return max((int(item.get("version") or 0) for item in history), default=0) + 1


def save_guide_version(agent: Any, state: Mapping[str, Any]) -> Dict[str, Any]:
    """Persist a new immutable mesh version and make it the active display."""
    if agent is None or not hasattr(agent, "memory"):
        raise SurgicalGuideError("Agent is unavailable")
    current = dict(state)
    current["created_at"] = float(__import__("time").time())
    try:
        from web.planning_runs import active_planning_id
        current["planning_id"] = active_planning_id(agent.memory)
    except Exception:
        # Guide persistence remains usable in the standalone tool runtime.
        current.setdefault("planning_id", None)
    history = [dict(item) for item in (agent.memory.retrieve("surgical_guide_versions") or []) if isinstance(item, Mapping)]
    previous = agent.memory.retrieve("surgical_guide")
    # Upgrade path for the original single-guide representation: preserve an
    # already generated guide the first time versioned storage is introduced.
    if not history and isinstance(previous, Mapping):
        history.append(dict(previous))
    history.append(current)
    by_version = {int(item.get("version") or 0): item for item in history}
    history = [item for version, item in by_version.items() if version > 0]
    history.sort(key=lambda item: int(item.get("version") or 0))
    history = history[-MAX_SAVED_GUIDE_VERSIONS:]
    agent.memory.store("surgical_guide_versions", history)
    agent.memory.store("surgical_guide", current)
    return current


def _largest_component(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage

    labels, count = ndimage.label(mask, structure=np.ones((3, 3, 3), dtype=np.uint8))
    if count <= 0:
        return np.zeros_like(mask, dtype=bool)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    return labels == int(np.argmax(sizes))


def _body_mask(ct_array: np.ndarray, threshold: float) -> np.ndarray:
    """Extract a conservative exterior body envelope from the current CT."""
    from scipy import ndimage

    if ct_array.ndim != 3:
        raise SurgicalGuideError("CT volume must be three-dimensional")
    candidate = np.asarray(ct_array, dtype=np.float32) > float(threshold)
    candidate = _largest_component(candidate)
    if int(candidate.sum()) < 64:
        raise SurgicalGuideError("Unable to derive a patient skin surface from the CT")
    # Close small skin discontinuities but preserve the outer patient contour.
    candidate = ndimage.binary_closing(candidate, structure=np.ones((3, 3, 3)), iterations=1)
    candidate = ndimage.binary_fill_holes(candidate)
    return _largest_component(candidate)


def store_guide_skin_surface(
    agent: Any,
    body: np.ndarray,
    *,
    ct_image: Any,
    threshold_hu: float,
) -> Dict[str, Any]:
    """Persist the exact smoothed skin envelope consumed by guide CSG.

    Keeping this result in session memory makes the Data Tree, 2D contour,
    3D surface, guide QA, and later session hydration refer to one immutable
    voxel result instead of independently thresholding CT in each viewer.
    """
    if agent is None or not hasattr(agent, "memory"):
        raise SurgicalGuideError("Agent is unavailable")
    mask = np.ascontiguousarray(np.asarray(body, dtype=np.uint8))
    if mask.ndim != 3 or not bool(np.any(mask)):
        raise SurgicalGuideError("The guide skin surface is empty")
    previous = agent.memory.retrieve("skin_surface") or {}
    try:
        data_version = int(previous.get("data_version") or 0) + 1
    except (AttributeError, TypeError, ValueError):
        data_version = 1
    try:
        from web.planning_runs import active_planning_id
        planning_id = active_planning_id(agent.memory)
    except Exception:
        planning_id = None
    spacing = tuple(float(value) for value in ct_image.GetSpacing())
    origin = tuple(float(value) for value in ct_image.GetOrigin())
    direction = tuple(float(value) for value in ct_image.GetDirection())
    metadata = {
        "id": GUIDE_SKIN_NODE_ID,
        "object_id": GUIDE_SKIN_OBJECT_ID,
        "data_tree_node_id": GUIDE_SKIN_NODE_ID,
        "label": "Guide skin surface",
        "type": "skin_surface",
        "data_type": "segmentation",
        "source": "surgical_guide",
        "status": "ready",
        "planning_id": planning_id or None,
        "data_version": data_version,
        "threshold_hu": float(threshold_hu),
        "voxel_count": int(np.count_nonzero(mask)),
        "shape": [int(value) for value in mask.shape],
        "spacing": list(spacing),
        "origin": list(origin),
        "direction": list(direction),
        "coordinate_system": "SimpleITK physical patient-world coordinates (mm)",
        "default_color": GUIDE_SKIN_DEFAULT_COLOR,
        "default_opacity": GUIDE_SKIN_DEFAULT_OPACITY,
        "visible_2d": True,
        "visible_3d": True,
    }
    agent.memory.store("skin_surface_mask", mask)
    agent.memory.store("skin_surface", metadata)
    return metadata


def skin_surface_public_payload(agent: Any) -> Dict[str, Any]:
    """Return browser-safe metadata for the persisted guide skin surface."""
    if agent is None or not hasattr(agent, "memory"):
        return {"available": False}
    metadata = agent.memory.retrieve("skin_surface")
    mask = agent.memory.retrieve("skin_surface_mask")
    if not isinstance(metadata, Mapping) or mask is None:
        return {"available": False}
    payload = dict(metadata)
    payload["available"] = True
    return payload


def _truncated_boundary_slices(body: np.ndarray) -> Tuple[bool, bool]:
    """Detect whether the body envelope is truncated by the CT scan boundaries.

    A finite-field-of-view CT stops at its first and last slices; the body
    mask therefore simply ends there instead of closing over a real skin
    surface. ``body[0]`` (z-min) and ``body[-1]`` (z-max) holding any body
    voxels means the patient's true skin continues beyond the scan and the
    boundary slice is a flat truncation plane, NOT anatomical skin.

    A real skin surface that legitimately reaches a scan edge (e.g. the top of
    the head) tapers to a small area over the last few slices, whereas a
    truncation plane keeps a large near-constant cross-section right up to the
    edge. We classify a boundary slice as truncated when it holds a substantial
    body area comparable to its neighbour (a flat cap), i.e. the contour was
    simply cut off rather than naturally closing.

    Returns ``(z_min_truncated, z_max_truncated)``.
    """
    faces = _truncated_boundary_faces(body)
    return bool(faces["z_min"]), bool(faces["z_max"])


def _truncated_boundary_faces(body: np.ndarray) -> Dict[str, bool]:
    """Detect flat body caps on every CT array face.

    The guide is constructed in ``[z, y, x]`` array order. Earlier versions
    only protected the first and last z slices, which left a crop touching a
    lateral CT edge free to treat that edge as a closed skin surface. The
    result could be a plate that wrapped around a scan boundary instead of
    following patient skin. This helper keeps the existing z-only API while
    extending the same conservative flat-cap test to all six faces.
    """
    mask = np.asarray(body, dtype=bool)
    names = ((0, "z_min", "z_max"), (1, "y_min", "y_max"), (2, "x_min", "x_max"))
    result = {name: False for _, low, high in names for name in (low, high)}
    if mask.ndim != 3 or min(mask.shape) < 3:
        return result

    def flat_cap(axis: int, side: int) -> bool:
        boundary_index = 0 if side == 0 else int(mask.shape[axis] - 1)
        neighbour_index = 1 if side == 0 else int(mask.shape[axis] - 2)
        boundary = np.take(mask, boundary_index, axis=axis)
        neighbour = np.take(mask, neighbour_index, axis=axis)
        area_boundary = int(np.count_nonzero(boundary))
        area_neighbour = int(np.count_nonzero(neighbour))
        if area_boundary < 32:
            return False
        # A flat acquisition cut keeps a substantial cross-section at the
        # boundary. A natural anatomical end tapers rapidly instead.
        return float(area_boundary) / max(1.0, float(area_neighbour)) >= 0.35

    for axis, low_name, high_name in names:
        if bool(np.any(np.take(mask, 0, axis=axis))):
            result[low_name] = flat_cap(axis, 0)
        if bool(np.any(np.take(mask, -1, axis=axis))):
            result[high_name] = flat_cap(axis, 1)
    return result


def _smooth_body_mask(
    body: np.ndarray,
    source_spacing_zyx: Sequence[float],
    sigma_mm: float = 2.0,
) -> np.ndarray:
    """Smooth the body envelope so the guide plate is not stair-stepped.

    Real CTs have thick slices (often 5 mm in z) far larger than the plate
    thickness, so the raw thresholded body surface is stepped. Smoothing the
    binary body with an anisotropic Gaussian (matched to the physical spacing)
    then re-thresholding produces a skin surface the guide plate can hug
    smoothly instead of following the CT slice steps. The smoothing is bounded
    to the plate region by the caller; sigma defaults to 2 mm.
    """
    from scipy import ndimage

    spacing = np.asarray(source_spacing_zyx, dtype=np.float64)
    sigma_vox = np.maximum(np.asarray([sigma_mm, sigma_mm, sigma_mm]) / np.maximum(spacing, 1e-6), 0.5)
    # Clamp so a 2 mm sigma never grows beyond a few voxels on coarse slices.
    sigma_vox = np.minimum(sigma_vox, 3.0)
    blurred = ndimage.gaussian_filter(body.astype(np.float32), sigma=tuple(float(s) for s in sigma_vox))
    return blurred > 0.5


def _sample_skin_entry(
    ct_image: Any,
    body: np.ndarray,
    target: np.ndarray,
    external: np.ndarray,
    *,
    truncated_z_min: bool = False,
    truncated_z_max: bool = False,
    truncated_boundary_faces: Optional[Mapping[str, bool]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Find the first body voxel entered by the physical needle segment.

    The planner stores ``[deep, external]`` endpoints.  The method still
    searches the complete physical segment rather than assuming an axis or
    image orientation, and returns a direction that points into the patient.

    When the body envelope is truncated by the CT scan boundaries (finite FOV),
    an entry landing on the first/last slice is a FLAT truncation plane, not a
    real skin surface. Such entries are skipped so the needle enters through
    genuine lateral skin; if the whole segment stays inside the truncated
    region an error is raised so the caller refuses an anatomically impossible
    guide.
    """
    line = target - external
    length = float(np.linalg.norm(line))
    if length <= 1e-6:
        raise SurgicalGuideError("Needle endpoints are coincident")
    inward = line / length
    spacing = np.asarray(ct_image.GetSpacing(), dtype=np.float64)
    step = max(0.25, min(0.75, float(np.min(np.abs(spacing))) * 0.5))
    samples = max(2, int(math.ceil(length / step)) + 1)
    size_xyz = np.asarray(ct_image.GetSize(), dtype=np.int64)
    z_count = int(size_xyz[2])
    boundary_faces = truncated_boundary_faces or {}
    boundary_tolerance_voxels = 1
    inside_before = False
    first_inside: Optional[np.ndarray] = None
    for fraction in np.linspace(0.0, 1.0, samples, dtype=np.float64):
        point = external + fraction * line
        try:
            index_xyz = np.asarray(
                ct_image.TransformPhysicalPointToContinuousIndex(tuple(float(value) for value in point)),
                dtype=np.float64,
            )
        except Exception:
            continue
        if np.any(index_xyz < 0.0) or np.any(index_xyz > (size_xyz - 1.0)):
            inside_before = False
            continue
        x, y, z = np.rint(index_xyz).astype(np.int64)
        in_body = bool(body[z, y, x])
        if in_body and not inside_before:
            # Reject an entry on a truncated (flat) scan-boundary slice. The CT
            # first/last slice is a flat scan-boundary plane, not real skin,
            # regardless of how the flat-cap heuristic classifies it: a genuine
            # anatomical entry can never sit exactly on the scan edge.
            on_truncated_boundary = (
                (z == 0 and truncated_z_min) or (z == z_count - 1 and truncated_z_max)
            ) or z == 0 or z == z_count - 1
            # Apply the same rule to lateral finite-FOV faces. A path that
            # enters through an x/y acquisition cap must not be accepted as
            # skin merely because it is not on the first or last CT slice.
            on_truncated_boundary = on_truncated_boundary or (
                (x <= boundary_tolerance_voxels and bool(boundary_faces.get("x_min")))
                or (
                    x >= int(size_xyz[0] - 1) - boundary_tolerance_voxels
                    and bool(boundary_faces.get("x_max"))
                )
                or (y <= boundary_tolerance_voxels and bool(boundary_faces.get("y_min")))
                or (
                    y >= int(size_xyz[1] - 1) - boundary_tolerance_voxels
                    and bool(boundary_faces.get("y_max"))
                )
            )
            if on_truncated_boundary:
                # The needle enters through the CT truncation plane, not real
                # skin. Keep searching: a real lateral skin entry may exist
                # further along the segment.
                inside_before = True
                continue
            first_inside = point
            break
        inside_before = in_body
    if first_inside is None:
        raise SurgicalGuideError(
            "The planned needle only intersects the CT scan-boundary truncation "
            "plane, not a real skin surface. The scan range is too short to "
            "generate a safe puncture guide; use a CT that covers the full body "
            "region or a lateral entry."
        )
    return first_inside, inward


def _path_records(
    agent: Any,
    body: np.ndarray,
    selected_needle_ids: Optional[Iterable[Any]] = None,
) -> List[NeedleGuidePath]:
    memory = agent.memory
    ct_image = memory.retrieve("ct_image")
    ct_array = memory.retrieve("ct_data")
    if ct_image is None or ct_array is None:
        raise SurgicalGuideError("Load a CT image before generating a puncture guide")
    snapshot = _current_planning_snapshot(agent)
    selected = {str(value) for value in selected_needle_ids or [] if str(value)}
    seed_by_trajectory: Dict[str, List[np.ndarray]] = {}
    for seed in snapshot["seeds"]:
        if not isinstance(seed, Mapping):
            continue
        try:
            seed_by_trajectory.setdefault(str(seed.get("trajectory_id") or ""), []).append(
                _as_point(seed.get("position") or seed.get("pos"), "seed position")
            )
        except SurgicalGuideError:
            continue
    paths: List[NeedleGuidePath] = []
    boundary_faces = _truncated_boundary_faces(body)
    trunc_z_min = bool(boundary_faces["z_min"])
    trunc_z_max = bool(boundary_faces["z_max"])
    for index, needle in enumerate(snapshot["needles"]):
        if not isinstance(needle, Mapping):
            continue
        needle_id = str(needle.get("id") or f"needle_{index}")
        if selected and needle_id not in selected:
            continue
        points = needle.get("points")
        if not isinstance(points, list) or len(points) < 2:
            continue
        target = _as_point(points[0], "needle target")
        external = _as_point(points[-1], "needle external endpoint")
        entry, inward = _sample_skin_entry(
            ct_image, body, target, external,
            truncated_z_min=trunc_z_min,
            truncated_z_max=trunc_z_max,
            truncated_boundary_faces=boundary_faces,
        )
        trajectory_id = str(needle.get("trajectory_id") or needle_id)
        linked_seeds = seed_by_trajectory.get(trajectory_id, [])
        if linked_seeds:
            center = np.mean(np.stack(linked_seeds, axis=0), axis=0)
            candidate = center - entry
            length = float(np.linalg.norm(candidate))
            # The needle endpoints define the insertion direction.  Seed
            # positions may refine that direction only when their centroid is
            # on the patient/inward side of the detected skin entry.  A stale
            # or manually placed seed behind the entry must never reverse the
            # sleeve into the body-exterior region: that creates an isolated
            # sleeve, which is then correctly removed by the post-CSG
            # component cleanup and looks like a missing guide channel.
            forward_distance = float(np.dot(candidate, inward))
            if length > 1e-5 and forward_distance > 1e-5:
                inward = candidate / length
        paths.append(NeedleGuidePath(
            needle_id=needle_id,
            trajectory_id=trajectory_id,
            target=target,
            external=external,
            entry=entry,
            inward_direction=inward,
            seed_count=len(linked_seeds),
        ))
    if not paths:
        raise SurgicalGuideError("No planned needle geometry is available for a puncture guide")
    return paths


def _crop_bounds(ct_image: Any, entries: Sequence[np.ndarray], margin_mm: float) -> Tuple[np.ndarray, np.ndarray]:
    size_xyz = np.asarray(ct_image.GetSize(), dtype=np.int64)
    spacing_xyz = np.maximum(np.asarray(ct_image.GetSpacing(), dtype=np.float64), 1e-6)
    index_points = []
    for entry in entries:
        idx = np.asarray(
            ct_image.TransformPhysicalPointToContinuousIndex(tuple(float(value) for value in entry)),
            dtype=np.float64,
        )
        index_points.append(idx)
    indices = np.vstack(index_points)
    pad = np.ceil(float(margin_mm) / spacing_xyz).astype(np.int64) + 3
    lower = np.maximum(0, np.floor(indices.min(axis=0)).astype(np.int64) - pad)
    upper = np.minimum(size_xyz - 1, np.ceil(indices.max(axis=0)).astype(np.int64) + pad)
    if np.any(upper <= lower):
        raise SurgicalGuideError("Guide region does not fit inside the CT field of view")
    return lower, upper


def _local_boundary_safety_mask(
    local_shape_zyx: Sequence[int],
    lower_zyx: Sequence[int],
    upper_zyx: Sequence[int],
    source_shape_zyx: Sequence[int],
    boundary_faces: Mapping[str, bool],
    target_spacing_zyx: Sequence[float],
    margin_mm: float,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Return the printable domain that excludes CT acquisition caps.

    A cropped signed-distance field has no way to distinguish an anatomical
    outside from a crop face. If the source body reaches a finite-FOV face and
    the guide crop also reaches that face, the face must be treated as invalid
    geometry. The mask is applied before patch connection and after every CSG
    union, so sleeves and bridge routing cannot reintroduce a cap-backed plate.
    """
    shape = tuple(int(value) for value in local_shape_zyx)
    lower = np.asarray(lower_zyx, dtype=np.int64).reshape(3)
    upper = np.asarray(upper_zyx, dtype=np.int64).reshape(3)
    source_shape = np.asarray(source_shape_zyx, dtype=np.int64).reshape(3)
    spacing = np.asarray(target_spacing_zyx, dtype=np.float64).reshape(3)
    if len(shape) != 3 or np.any(spacing <= 0.0):
        raise SurgicalGuideError("Invalid local guide boundary geometry")

    safe = np.ones(shape, dtype=bool)
    excluded: Dict[str, int] = {}
    # Keep at least one target voxel clear even when an operator explicitly
    # sets truncation_margin_mm to zero. A zero-width forbidden zone would
    # reintroduce the exact cap ambiguity this contract is meant to prevent.
    guard_mm = max(float(margin_mm), float(np.max(spacing)))
    face_names = (
        (0, "z_min", "z_max"),
        (1, "y_min", "y_max"),
        (2, "x_min", "x_max"),
    )
    for axis, low_name, high_name in face_names:
        low_touches = int(lower[axis]) <= 0 and bool(boundary_faces.get(low_name))
        high_touches = int(upper[axis]) >= int(source_shape[axis] - 1) and bool(
            boundary_faces.get(high_name)
        )
        guard_voxels = max(1, int(math.ceil(guard_mm / spacing[axis])))
        if low_touches:
            index = [slice(None)] * 3
            index[axis] = slice(0, min(shape[axis], guard_voxels))
            safe[tuple(index)] = False
            excluded[low_name] = min(shape[axis], guard_voxels)
        if high_touches:
            index = [slice(None)] * 3
            start = max(0, shape[axis] - guard_voxels)
            index[axis] = slice(start, shape[axis])
            safe[tuple(index)] = False
            excluded[high_name] = min(shape[axis], guard_voxels)

    return safe, {
        "guard_mm": float(guard_mm),
        "excluded_faces": excluded,
        "valid_voxel_count": int(np.count_nonzero(safe)),
        "local_voxel_count": int(safe.size),
    }


def _crop_origin_world(ct_image: Any, lower_xyz: np.ndarray) -> np.ndarray:
    """Return the world coordinate of the inclusive crop's first voxel."""
    return np.asarray(
        ct_image.TransformIndexToPhysicalPoint(tuple(int(value) for value in lower_xyz)),
        dtype=np.float64,
    )


def _world_to_local_index_zyx(
    ct_image: Any,
    lower_xyz: np.ndarray,
    world: np.ndarray,
    spacing_xyz: Sequence[float],
) -> np.ndarray:
    """Convert a physical point to a continuous index in the local grid.

    This is the inverse of ``_world_grid``'s forward transform, expressed as a
    single point so callers can compute patch distances entirely in the
    isotropic local index space.
    """
    spacing = np.asarray(spacing_xyz, dtype=np.float64)
    direction = np.asarray(ct_image.GetDirection(), dtype=np.float64).reshape(3, 3)
    crop_origin = _crop_origin_world(ct_image, lower_xyz)
    rel = np.asarray(world, dtype=np.float64) - crop_origin
    local_xyz = direction.T @ rel
    return (local_xyz / spacing)[::-1]


def _flat_cylinder_sdf(
    grid: Tuple[np.ndarray, np.ndarray, np.ndarray],
    start: np.ndarray,
    end: np.ndarray,
    radius: float,
) -> np.ndarray:
    """Signed distance field of a TRUE flat-ended cylinder (negative inside).

    A point is inside the solid cylinder iff its unclamped projection onto the
    axis lies in ``[0, length]`` and its perpendicular distance to the axis is
    ``<= radius``. The returned field is negative inside the cylinder, zero on
    its surface and positive outside, so it is an exact, resolution-independent
    form of the boolean-mask cylinder used for sleeve and bore volumes.
    """
    world_x, world_y, world_z = grid
    start = np.asarray(start, dtype=np.float64)
    end = np.asarray(end, dtype=np.float64)
    axis = end - start
    length = float(np.linalg.norm(axis))
    if length <= 1e-10:
        raise SurgicalGuideError("Guide sleeve has zero length")
    direction = axis / length
    dx = world_x - start[0]
    dy = world_y - start[1]
    dz = world_z - start[2]
    # Signed axial coordinate (mm) along the axis from ``start``.
    axial = dx * direction[0] + dy * direction[1] + dz * direction[2]
    # Perpendicular (radial) distance to the axis line.
    radial_sq = np.maximum((dx * dx + dy * dy + dz * dz) - axial * axial, 0.0)
    radial = np.sqrt(radial_sq)
    # Flat-ended cylinder: negative inside iff radial <= radius AND 0 <= axial
    # <= length. Using the max of the three unsigned distances is the exact
    # SDF of a flat-ended (not rounded) cylinder.
    return np.maximum(np.maximum(radial - float(radius), -axial), axial - length)


def _cylinder_sdf_in_region(
    ct_image: Any,
    lower_xyz: np.ndarray,
    shape_zyx: Sequence[int],
    spacing_xyz: Sequence[float],
    cylinder_start: np.ndarray,
    cylinder_end: np.ndarray,
    radius: float,
) -> Tuple[np.ndarray, Tuple[slice, slice, slice]]:
    """Evaluate an exact cylinder SDF on a tight local box, not the full grid.

    Returns the SDF values over a compact bounding box around the cylinder axis
    plus the box slices, so the caller can blend it into the global guide field
    with ``np.minimum`` (union) or ``np.maximum(-sdf)`` (subtract) without
    paying O(volume) per needle.
    """
    spacing = np.asarray(spacing_xyz, dtype=np.float64)
    direction = np.asarray(ct_image.GetDirection(), dtype=np.float64).reshape(3, 3)
    crop_origin = _crop_origin_world(ct_image, lower_xyz)
    shape = np.asarray(shape_zyx, dtype=np.int64)

    def _world_to_index_zyx(world: np.ndarray) -> np.ndarray:
        rel = np.asarray(world, dtype=np.float64) - crop_origin
        local_xyz = direction.T @ rel
        return (local_xyz / spacing)[::-1]

    i_start = _world_to_index_zyx(cylinder_start)
    i_end = _world_to_index_zyx(cylinder_end)
    radius_vox = radius / spacing[::-1]
    margin = np.maximum(np.ceil(np.max(radius_vox)), 2)
    lo = np.floor(np.minimum(i_start, i_end)).astype(np.int64) - int(margin)
    hi = np.ceil(np.maximum(i_start, i_end)).astype(np.int64) + int(margin) + 1
    lo = np.maximum(lo, 0)
    hi = np.minimum(hi, shape - 1)
    if np.any(hi <= lo):
        raise SurgicalGuideError("Guide cylinder falls outside the local plate grid")

    zs, ys, xs = lo.astype(int)
    ze, ye, xe = hi.astype(int)
    z = np.arange(zs, ze, dtype=np.float64)
    y = np.arange(ys, ye, dtype=np.float64)
    x = np.arange(xs, xe, dtype=np.float64)
    zz, yy, xx = np.meshgrid(z, y, x, indexing="ij")
    scaled_x = xx * spacing[0]
    scaled_y = yy * spacing[1]
    scaled_z = zz * spacing[2]
    world_x = crop_origin[0] + direction[0, 0] * scaled_x + direction[0, 1] * scaled_y + direction[0, 2] * scaled_z
    world_y = crop_origin[1] + direction[1, 0] * scaled_x + direction[1, 1] * scaled_y + direction[1, 2] * scaled_z
    world_z = crop_origin[2] + direction[2, 0] * scaled_x + direction[2, 1] * scaled_y + direction[2, 2] * scaled_z
    sdf = _flat_cylinder_sdf((world_x, world_y, world_z), cylinder_start, cylinder_end, radius)
    box = (slice(zs, ze), slice(ys, ye), slice(xs, xe))
    return sdf, box


def _subtract_cylinder_specs_from_mask(
    solid: np.ndarray,
    ct_image: Any,
    lower_xyz: np.ndarray,
    spacing_xyz: Sequence[float],
    cylinder_specs: Sequence[Mapping[str, Any]],
) -> np.ndarray:
    """Subtract exact finite cylinders from a guide construction mask in place.

    Both the initial CSG pass and the topology-repair pass call this same
    function.  Keeping the primary-cutter implementation in one place prevents
    a repair operation from accidentally reverting to the shorter historical
    sleeve-only bore and re-closing a channel at a sleeve intersection.
    """
    for spec in cylinder_specs:
        start = np.asarray(spec["start"], dtype=np.float64)
        end = np.asarray(spec["end"], dtype=np.float64)
        radius = float(spec["radius_mm"])
        cylinder_sdf, box = _cylinder_sdf_in_region(
            ct_image,
            lower_xyz,
            solid.shape,
            spacing_xyz,
            start,
            end,
            radius,
        )
        solid[box] &= ~(cylinder_sdf <= 0.0)
    return solid


def _sample_mask_at_world_points(
    mask: np.ndarray,
    ct_image: Any,
    lower_xyz: np.ndarray,
    spacing_xyz: Sequence[float],
    points_world: np.ndarray,
) -> np.ndarray:
    """Sample a local binary guide mask at physical world coordinates.

    The guide grid can contain hundreds of millions of voxels at the 0.2 mm
    manufacturing resolution. Never cast the complete mask for a sparse point
    query: doing so once for every candidate auxiliary bore turns a 200-hole
    guide into hundreds of gigabytes of transient memory traffic. Nearest-
    neighbour sampling is the correct contract because this is a binary CSG
    grid and the caller samples at no more than half a voxel along each axis.
    """
    from scipy import ndimage

    points = np.asarray(points_world, dtype=np.float64).reshape(-1, 3)
    spacing = np.asarray(spacing_xyz, dtype=np.float64)
    direction = np.asarray(ct_image.GetDirection(), dtype=np.float64).reshape(3, 3)
    crop_origin = _crop_origin_world(ct_image, lower_xyz)
    # Row-vector form of ``direction.T @ (point - origin)`` for every point.
    local_xyz = (points - crop_origin) @ direction
    indices_zyx = (local_xyz / spacing)[:, ::-1]
    return ndimage.map_coordinates(
        np.asarray(mask),
        indices_zyx.T,
        order=0,
        mode="constant",
        cval=False,
        prefilter=False,
    )


def _auxiliary_hole_support(
    solid: np.ndarray,
    ct_image: Any,
    lower_xyz: np.ndarray,
    spacing_xyz: Sequence[float],
    start: np.ndarray,
    end: np.ndarray,
    radius: float,
    plate_thickness_mm: float,
) -> Tuple[bool, str]:
    """Check that an auxiliary cylinder can produce a complete through-hole.

    A Boolean subtraction from a curved shell can otherwise leave a partial
    opening when the candidate line ends inside the plate or runs along its
    edge.  The check requires an interior material interval with air on both
    sides and a material ring around the bore centreline.  Invalid candidates
    are skipped and recorded instead of being exported as misleading half
    holes.
    """
    axis_vector = np.asarray(end, dtype=np.float64) - np.asarray(start, dtype=np.float64)
    length = float(np.linalg.norm(axis_vector))
    if length <= 1e-8:
        return False, "invalid_auxiliary_axis"
    axis = axis_vector / length
    spacing = np.asarray(spacing_xyz, dtype=np.float64)
    sample_step = max(0.1, min(0.5, float(np.min(spacing)) * 0.5))
    sample_count = max(3, int(math.ceil(length / sample_step)) + 1)
    fractions = np.linspace(0.0, 1.0, sample_count, dtype=np.float64)
    line_points = np.asarray(start, dtype=np.float64) + fractions[:, None] * axis_vector
    line_values = _sample_mask_at_world_points(
        solid, ct_image, lower_xyz, spacing_xyz, line_points
    )
    inside = line_values >= 0.5
    true_indices = np.flatnonzero(inside)
    if true_indices.size == 0:
        return False, "outside_plate_patch"

    # Find contiguous centreline intervals.  A complete hole must enter and
    # leave the guide material before the construction cylinder ends.
    breaks = np.flatnonzero(np.diff(true_indices) > 1)
    starts = np.r_[true_indices[0], true_indices[breaks + 1]]
    stops = np.r_[true_indices[breaks], true_indices[-1]]
    minimum_interval_mm = max(0.75, 0.35 * float(plate_thickness_mm))
    interval_candidates = []
    for interval_start, interval_stop in zip(starts, stops):
        if int(interval_start) <= 0 or int(interval_stop) >= sample_count - 1:
            continue
        interval_length = (
            float(fractions[int(interval_stop)] - fractions[int(interval_start)]) * length
        )
        if interval_length >= minimum_interval_mm:
            interval_candidates.append((int(interval_start), int(interval_stop), interval_length))
    if not interval_candidates:
        return False, "not_through_plate"

    # At the middle of the longest material interval, the guide must still
    # surround the bore by a printable wall.  This rejects holes clipped by a
    # patch boundary or by a curved guide edge, which otherwise look like half
    # circles after marching cubes and transparent Viewer rendering.
    interval_start, interval_stop, _ = max(interval_candidates, key=lambda item: item[2])
    midpoint = line_points[(interval_start + interval_stop) // 2]
    radial_a, radial_b = _orthogonal_basis(axis)
    probe_radius = float(radius) + GUIDE_MINIMUM_WALL_MM
    angles = np.linspace(0.0, 2.0 * math.pi, 24, endpoint=False)
    ring_points = np.asarray([
        midpoint + probe_radius * (
            math.cos(angle) * radial_a + math.sin(angle) * radial_b
        )
        for angle in angles
    ])
    ring_values = _sample_mask_at_world_points(
        solid, ct_image, lower_xyz, spacing_xyz, ring_points
    )
    if int(np.count_nonzero(ring_values >= 0.5)) < int(math.ceil(len(angles) * 0.9)):
        return False, "insufficient_auxiliary_wall"
    return True, "ready"


def _retain_largest_printable_component(
    mask: np.ndarray,
    minimum_voxels: int,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Retain the one plate component that can be exported as one guide.

    Boolean CSG around a dense cluster of needle bores can leave islands of
    material between neighbouring channels.  Those islands are not separate
    printable guide pieces and must not be passed to marching cubes as if they
    were part of the guide.  The old implementation filtered only by size,
    so a several-thousand-voxel island survived and the later single-piece
    check rejected an otherwise usable guide.

    This helper deliberately keeps the operation auditable.  It reports how
    many components and voxels were removed, and the caller separately checks
    that every primary channel still has material support after the cleanup.
    Thus a real detached needle sleeve cannot be silently lost: it causes a
    clear geometry error instead of being discarded as a generic small part.
    """
    from scipy import ndimage

    source = np.asarray(mask, dtype=bool)
    structure = ndimage.generate_binary_structure(3, 1)
    labels, count = ndimage.label(source, structure=structure)
    input_voxels = int(np.count_nonzero(source))
    metadata: Dict[str, Any] = {
        "policy": "largest_face_connected_component_after_csg",
        "minimum_component_voxels": int(minimum_voxels),
        "input_component_count": int(count),
        "input_voxel_count": input_voxels,
        "retained_component_count": 0,
        "retained_voxel_count": 0,
        "dropped_component_count": int(count),
        "dropped_voxel_count": input_voxels,
    }
    if count == 0:
        return np.zeros_like(source, dtype=bool), metadata

    sizes = np.bincount(labels.ravel())
    eligible = np.flatnonzero(sizes >= int(minimum_voxels))
    eligible = eligible[eligible != 0]
    if eligible.size == 0:
        return np.zeros_like(source, dtype=bool), metadata

    # ``eligible`` is label-order stable, so ties are deterministic and do not
    # make the exported guide change between otherwise identical generations.
    largest_label = int(eligible[int(np.argmax(sizes[eligible]))])
    retained = labels == largest_label
    retained_voxels = int(sizes[largest_label])
    metadata.update({
        "retained_component_count": 1,
        "retained_voxel_count": retained_voxels,
        "dropped_component_count": int(count - 1),
        "dropped_voxel_count": int(input_voxels - retained_voxels),
    })
    return retained, metadata


def _filter_components(mask: np.ndarray, minimum_voxels: int) -> np.ndarray:
    """Keep one largest face-connected printable component.

    Corner-connected specks can survive a 26-connected filter and create
    non-manifold edges when they touch the guide plate only diagonally.  More
    importantly, after bore CSG a dense needle cluster can produce sizeable
    material islands; a single printable guide must not include those islands
    as independent solids.  Use the same deterministic policy in the normal
    and mesh-topology-repair paths.
    """
    filtered, _metadata = _retain_largest_printable_component(mask, minimum_voxels)
    return filtered


def _primary_sleeve_support_quality(
    solid: np.ndarray,
    ct_image: Any,
    lower_xyz: np.ndarray,
    spacing_xyz: Sequence[float],
    paths: Sequence[NeedleGuidePath],
    params: Mapping[str, Any],
) -> Dict[str, Any]:
    """Verify that largest-component cleanup did not remove a needle sleeve.

    The post-CSG islands seen in dense plans are usually material trapped
    between overlapping bores, but a generic ``keep largest`` operation must
    not assume that.  Sample a sparse annulus inside each primary sleeve,
    between the bore radius and the sleeve outer radius.  The check is
    intentionally tolerant of shared/overlapping channels: it only requires
    a small amount of retained wall material along each sleeve, not a full
    independent ring that the plan geometry itself cannot provide.
    """
    if not paths:
        return {
            "valid": False,
            "probe_radius_mm": 0.0,
            "minimum_ring_samples": 0,
            "minimum_total_samples": 0,
            "tested_probe_radii_mm": [],
            "channels": [],
            "unsupported_needle_ids": [],
        }

    bore_radius = _effective_primary_bore_radius_mm(params)
    sleeve_outer_radius = float(params["sleeve_outer_radius_mm"])
    resolution = float(params["geometry_resolution_mm"])
    # Probe beyond the configured minimum printable wall.  A single sparse
    # ring is not reliable for dense/overlapping channels: a narrow shared
    # wall can fall between its angular samples and look absent even though it
    # is present in the CSG volume. Test several radii with enough angular
    # resolution to make that aliasing unlikely, while never treating material
    # inside the bore as support.
    minimum_probe_radius = bore_radius + float(GUIDE_MINIMUM_WALL_MM)
    maximum_probe_radius = sleeve_outer_radius - 0.25
    probe_radii = (
        np.linspace(
            minimum_probe_radius,
            maximum_probe_radius,
            num=5,
            dtype=np.float64,
        )
        if maximum_probe_radius >= minimum_probe_radius
        else np.array([], dtype=np.float64)
    )
    angle_count = 72
    minimum_ring_samples = 3
    minimum_total_samples = 12
    channels: List[Dict[str, Any]] = []

    for path in paths:
        sleeve_inner, sleeve_outer = _primary_sleeve_segment(path, params)
        axis_vector = sleeve_outer - sleeve_inner
        length = float(np.linalg.norm(axis_vector))
        if length <= 1e-8:
            channels.append({
                "needle_id": str(path.needle_id),
                "valid": False,
                "sampled_sections": 0,
                "max_ring_material_samples": 0,
                "total_ring_material_samples": 0,
            })
            continue
        axis = axis_vector / length
        radial_a, radial_b = _orthogonal_basis(path.inward_direction)
        axial_step = max(0.75, min(1.5, 4.0 * resolution))
        section_count = max(3, min(24, int(math.ceil(length / axial_step)) + 1))
        axial_positions = np.linspace(
            min(0.5, length * 0.25),
            max(length - 0.5, length * 0.75),
            section_count,
            dtype=np.float64,
        )
        angles = np.linspace(0.0, 2.0 * math.pi, angle_count, endpoint=False)
        ring_records: List[Dict[str, Any]] = []
        for probe_radius in probe_radii:
            points = np.asarray([
                sleeve_inner
                + axis * distance
                + float(probe_radius) * (
                    math.cos(angle) * radial_a + math.sin(angle) * radial_b
                )
                for distance in axial_positions
                for angle in angles
            ])
            values = _sample_mask_at_world_points(
                solid,
                ct_image,
                lower_xyz,
                spacing_xyz,
                points,
            ).reshape(section_count, angle_count)
            ring_counts = np.count_nonzero(values, axis=1)
            ring_records.append({
                "probe_radius_mm": float(probe_radius),
                "max_ring_material_samples": int(ring_counts.max()) if ring_counts.size else 0,
                "total_ring_material_samples": int(ring_counts.sum()),
            })
        best_ring = max(
            ring_records,
            key=lambda item: (
                int(item["total_ring_material_samples"]),
                int(item["max_ring_material_samples"]),
            ),
            default={
                "probe_radius_mm": 0.0,
                "max_ring_material_samples": 0,
                "total_ring_material_samples": 0,
            },
        )
        probe_radius = float(best_ring["probe_radius_mm"])
        max_ring = int(best_ring["max_ring_material_samples"])
        total_ring = int(best_ring["total_ring_material_samples"])
        channel_valid = bool(
            max_ring >= minimum_ring_samples
            and total_ring >= minimum_total_samples
        )
        channels.append({
            "needle_id": str(path.needle_id),
            "valid": channel_valid,
            "sampled_sections": int(section_count),
            "probe_radius_mm": probe_radius,
            "max_ring_material_samples": max_ring,
            "total_ring_material_samples": total_ring,
            "tested_probe_radii_mm": [
                float(item) for item in probe_radii.tolist()
            ],
            "probe_records": ring_records,
        })

    unsupported = [
        str(item["needle_id"])
        for item in channels
        if not bool(item.get("valid"))
    ]
    return {
        "valid": not unsupported,
        "probe_radius_mm": float(
            max(
                (
                    float(item.get("probe_radius_mm") or 0.0)
                    for item in channels
                    if bool(item.get("valid"))
                ),
                default=0.0,
            )
        ),
        "angle_samples_per_section": angle_count,
        "minimum_ring_samples": minimum_ring_samples,
        "minimum_total_samples": minimum_total_samples,
        "minimum_probe_radius_mm": float(minimum_probe_radius),
        "maximum_probe_radius_mm": float(maximum_probe_radius),
        "channels": channels,
        "unsupported_needle_ids": unsupported,
    }


def _needle_spacing_quality(
    paths: Sequence[NeedleGuidePath],
    params: Mapping[str, Any],
) -> Dict[str, Any]:
    """Audit dense primary channels without rejecting valid fused sleeves.

    Sleeve overlap is expected when several planned channels enter through a
    compact skin patch, so it is reported rather than treated as an automatic
    generation failure.  A second count identifies pairs whose final bore
    circles cannot retain the configured wall.  The actual export is guarded
    by ``_primary_sleeve_support_quality`` and mesh QA, so this audit informs
    review without dropping needles or inventing a new trajectory.
    """
    bore_radius = _effective_primary_bore_radius_mm(params)
    sleeve_radius = float(params["sleeve_outer_radius_mm"])
    minimum_wall = float(GUIDE_MINIMUM_WALL_MM)
    bore_wall_distance = 2.0 * bore_radius + minimum_wall
    sleeve_overlap_distance = 2.0 * sleeve_radius
    pair_records: List[Dict[str, Any]] = []
    for index, first in enumerate(paths):
        first_start, first_end = _primary_sleeve_segment(first, params)
        for second in paths[index + 1:]:
            second_start, second_end = _primary_sleeve_segment(second, params)
            distance = _segment_distance_mm(
                first_start,
                first_end,
                second_start,
                second_end,
            )
            pair_records.append({
                "needle_a": str(first.needle_id),
                "needle_b": str(second.needle_id),
                "centerline_distance_mm": float(distance),
                "bore_wall_conflict": bool(distance + 1e-6 < bore_wall_distance),
                "sleeve_overlap": bool(distance + 1e-6 < sleeve_overlap_distance),
            })

    ordered = sorted(
        pair_records,
        key=lambda item: (
            float(item["centerline_distance_mm"]),
            str(item["needle_a"]),
            str(item["needle_b"]),
        ),
    )
    bore_conflicts = [item for item in ordered if item["bore_wall_conflict"]]
    sleeve_overlaps = [item for item in ordered if item["sleeve_overlap"]]
    return {
        "status": "warning" if bore_conflicts else "clear",
        "path_count": int(len(paths)),
        "pair_count": int(len(pair_records)),
        "minimum_centerline_distance_mm": (
            float(ordered[0]["centerline_distance_mm"]) if ordered else None
        ),
        "minimum_bore_wall_distance_mm": float(bore_wall_distance),
        "sleeve_overlap_distance_mm": float(sleeve_overlap_distance),
        "bore_wall_conflict_pair_count": int(len(bore_conflicts)),
        "sleeve_overlap_pair_count": int(len(sleeve_overlaps)),
        "requires_operator_review": bool(bore_conflicts),
        "closest_pairs": [dict(item) for item in ordered[:12]],
    }


def _face_component_count(mask: np.ndarray) -> int:
    """Count printable solids using face connectivity, not corner contact."""
    from scipy import ndimage

    _labels, count = ndimage.label(
        np.asarray(mask, dtype=bool),
        structure=ndimage.generate_binary_structure(3, 1),
    )
    return int(count)


def _minimum_spanning_edges(points_mm: np.ndarray) -> List[Tuple[int, int]]:
    """Return deterministic Euclidean MST edges for a small anchor set."""
    points = np.asarray(points_mm, dtype=np.float64)
    if len(points) <= 1:
        return []
    connected = {0}
    remaining = set(range(1, len(points)))
    edges: List[Tuple[int, int]] = []
    while remaining:
        best: Optional[Tuple[float, int, int]] = None
        for source in sorted(connected):
            for target in sorted(remaining):
                distance = float(np.linalg.norm(points[source] - points[target]))
                candidate = (distance, source, target)
                if best is None or candidate < best:
                    best = candidate
        if best is None:  # pragma: no cover - guarded by the non-empty sets.
            break
        _distance, source, target = best
        edges.append((source, target))
        connected.add(target)
        remaining.remove(target)
    return edges


def _coarse_surface_route(
    plate_mask: np.ndarray,
    start_zyx: np.ndarray,
    end_zyx: np.ndarray,
    spacing_zyx: Sequence[float],
    route_resolution_mm: float,
) -> np.ndarray:
    """Route between two anchors while remaining on the skin-fitting shell.

    Running a shortest-path solver directly on the 0.2 mm manufacturing grid
    is needlessly expensive.  A max-pooled shell at approximately 1 mm keeps
    the skin topology, after which every route cell is mapped back to an actual
    fine-grid plate voxel.  The final bridge is still constructed on the full
    resolution shell; the coarse grid is used only for path planning.
    """
    from skimage.graph import route_through_array
    from skimage.measure import block_reduce

    plate = np.asarray(plate_mask, dtype=bool)
    spacing = np.asarray(spacing_zyx, dtype=np.float64)
    factor = max(1, int(round(float(route_resolution_mm) / float(np.min(spacing)))))
    coarse = block_reduce(
        plate,
        block_size=(factor, factor, factor),
        func=np.max,
        cval=False,
    ).astype(bool, copy=False)
    start_cell = np.minimum(
        np.asarray(start_zyx, dtype=np.int64) // factor,
        np.asarray(coarse.shape, dtype=np.int64) - 1,
    )
    end_cell = np.minimum(
        np.asarray(end_zyx, dtype=np.int64) // factor,
        np.asarray(coarse.shape, dtype=np.int64) - 1,
    )
    if not bool(coarse[tuple(start_cell)]) or not bool(coarse[tuple(end_cell)]):
        raise SurgicalGuideError("Guide bridge anchors do not lie on the printable plate shell")

    costs = np.where(coarse, np.float32(1.0), np.float32(1_000_000.0))
    route, _weight = route_through_array(
        costs,
        tuple(int(value) for value in start_cell),
        tuple(int(value) for value in end_cell),
        fully_connected=True,
        geometric=True,
    )
    route_array = np.asarray(route, dtype=np.int64)
    if route_array.size == 0 or not bool(np.all(coarse[tuple(route_array.T)])):
        raise SurgicalGuideError(
            "The planned needle groups cannot be connected along the available skin surface"
        )

    projected: List[np.ndarray] = []
    previous = np.asarray(start_zyx, dtype=np.int64)
    for cell in route_array:
        lower = cell * factor
        upper = np.minimum(lower + factor, np.asarray(plate.shape, dtype=np.int64))
        block = plate[
            lower[0]:upper[0],
            lower[1]:upper[1],
            lower[2]:upper[2],
        ]
        candidates = np.argwhere(block)
        if candidates.size == 0:  # pragma: no cover - coarse[cell] guarantees data.
            continue
        candidates = candidates + lower
        distances = np.linalg.norm((candidates - previous) * spacing, axis=1)
        chosen = candidates[int(np.argmin(distances))]
        if not projected or not np.array_equal(projected[-1], chosen):
            projected.append(chosen)
        previous = chosen
    if not projected:
        raise SurgicalGuideError("Unable to project the guide bridge onto the skin surface")
    return np.asarray(projected, dtype=np.int64)


def _connect_plate_patch_components(
    plate_mask: np.ndarray,
    plate_patch: np.ndarray,
    entry_indices_zyx: np.ndarray,
    spacing_zyx: Sequence[float],
    *,
    bridge_width_mm: float = GUIDE_COMPONENT_BRIDGE_WIDTH_MM,
    route_resolution_mm: float = GUIDE_COMPONENT_BRIDGE_ROUTE_RESOLUTION_MM,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Join distant needle patches with flush, skin-conforming plate bridges."""
    from scipy import ndimage
    from scipy.spatial import cKDTree

    plate = np.asarray(plate_mask, dtype=bool)
    solid = np.asarray(plate_patch, dtype=bool).copy()
    structure = ndimage.generate_binary_structure(3, 1)
    labels, initial_count = ndimage.label(solid, structure=structure)
    metadata: Dict[str, Any] = {
        "initial_component_count": int(initial_count),
        "final_component_count": int(initial_count),
        "bridge_count": 0,
        "bridge_width_mm": float(bridge_width_mm),
        "route_resolution_mm": float(route_resolution_mm),
        "single_piece": int(initial_count) == 1,
    }
    if initial_count <= 1:
        return solid, metadata

    solid_points = np.argwhere(solid)
    plate_points = np.argwhere(plate)
    entries = np.asarray(entry_indices_zyx, dtype=np.float64)
    spacing = np.asarray(spacing_zyx, dtype=np.float64)
    if solid_points.size == 0 or plate_points.size == 0 or entries.size == 0:
        raise SurgicalGuideError("Guide plate components have no valid skin anchors")

    solid_tree = cKDTree(solid_points.astype(np.float32) * spacing.astype(np.float32))
    _distance, nearest = solid_tree.query(entries * spacing)
    entry_anchors = solid_points[np.asarray(nearest, dtype=np.int64)]
    seeded_labels = labels[tuple(entry_anchors.T)]
    seeded_labels = np.unique(seeded_labels[seeded_labels > 0])
    # A sphere around an entry can touch a second folded or opposing body
    # surface.  Such a component has no needle anchor and must not become part
    # of the printed guide merely because it is larger than the speck filter.
    solid &= np.isin(labels, seeded_labels)
    labels, _seeded_count = ndimage.label(solid, structure=structure)

    anchor_by_label: Dict[int, np.ndarray] = {}
    for anchor in entry_anchors:
        label = int(labels[tuple(anchor)])
        if label > 0 and label not in anchor_by_label:
            anchor_by_label[label] = np.asarray(anchor, dtype=np.int64)
    anchors = np.asarray(list(anchor_by_label.values()), dtype=np.int64)
    if len(anchors) <= 1:
        metadata.update({"final_component_count": 1, "single_piece": True})
        return solid, metadata

    bridge_edges = _minimum_spanning_edges(anchors.astype(np.float64) * spacing)
    plate_points_float = plate_points.astype(np.float32)
    bridge_half_width = max(float(bridge_width_mm) / 2.0, float(np.max(spacing)))
    for source, target in bridge_edges:
        route = _coarse_surface_route(
            plate,
            anchors[source],
            anchors[target],
            spacing,
            route_resolution_mm,
        )
        route_tree = cKDTree(route.astype(np.float32) * spacing.astype(np.float32))
        for offset in range(0, len(plate_points), GUIDE_COMPONENT_BRIDGE_QUERY_CHUNK):
            points = plate_points_float[offset:offset + GUIDE_COMPONENT_BRIDGE_QUERY_CHUNK]
            distances, _indices = route_tree.query(points * spacing.astype(np.float32))
            selected = plate_points[offset:offset + len(points)][distances <= bridge_half_width]
            if selected.size:
                solid[tuple(selected.T)] = True

    _labels, final_count = ndimage.label(solid, structure=structure)
    metadata.update({
        "final_component_count": int(final_count),
        "bridge_count": len(bridge_edges),
        "single_piece": int(final_count) == 1,
    })
    if final_count != 1:
        raise SurgicalGuideError(
            "Unable to make one continuous guide along the available skin surface; "
            "increase CT skin coverage or revise the distant needle groups"
        )
    return solid, metadata


def _resample_mask_to_local_grid(
    mask: np.ndarray,
    source_spacing_zyx: Sequence[float],
    target_spacing_mm: float,
    *,
    return_signed_distance: bool = False,
) -> Any:
    """Resample a skin mask through a physical signed-distance field.

    Nearest-neighbour label interpolation preserves every thick-slice CT step
    and merely magnifies it on the fine guide grid. Interpolating a signed
    distance field instead reconstructs the zero-level skin surface between
    source slices while keeping the requested world-space lattice exact. The
    result remains boolean because later plate, sleeve and bore CSG is
    intentionally performed on a watertight binary solid.
    """
    from scipy import ndimage

    source = np.asarray(mask, dtype=bool)
    if source.ndim != 3 or min(source.shape) < 2:
        raise SurgicalGuideError("Guide crop is too small for physical resampling")
    source_spacing = np.asarray(source_spacing_zyx, dtype=np.float64)
    target_spacing = np.full(3, float(target_spacing_mm), dtype=np.float64)
    if np.any(source_spacing <= 0.0) or np.any(target_spacing <= 0.0):
        raise SurgicalGuideError("Guide spacing must be positive in every axis")

    # Positive values are outside the patient and negative values are inside.
    # Distances are measured in millimetres, so anisotropic CT slices contribute
    # their real physical thickness instead of being treated as unit voxels.
    outside_distance = ndimage.distance_transform_edt(
        ~source,
        sampling=tuple(float(value) for value in source_spacing),
    )
    inside_distance = ndimage.distance_transform_edt(
        source,
        sampling=tuple(float(value) for value in source_spacing),
    )
    signed_distance = (outside_distance - inside_distance).astype(np.float32, copy=False)

    extent = (np.asarray(source.shape, dtype=np.float64) - 1.0) * source_spacing
    target_shape = np.floor(extent / target_spacing + 1e-8).astype(np.int64) + 1
    target_shape = np.maximum(target_shape, 2)
    axes = [
        np.arange(int(target_shape[axis]), dtype=np.float32)
        * np.float32(target_spacing[axis] / source_spacing[axis])
        for axis in range(3)
    ]
    sampled_shape = tuple(int(value) for value in target_shape)
    sampled_mask = np.empty(sampled_shape, dtype=bool)
    sampled_signed_distance = (
        np.empty(sampled_shape, dtype=np.float32)
        if return_signed_distance
        else None
    )

    # Sampling the complete coordinate volume at 0.2 mm can temporarily use
    # several gigabytes. Process z slabs with a bounded point count so guide
    # detail does not trade away server responsiveness.
    plane_points = max(1, int(target_shape[1]) * int(target_shape[2]))
    slab_depth = max(1, min(int(target_shape[0]), 4_000_000 // plane_points))
    for z_start in range(0, int(target_shape[0]), slab_depth):
        z_stop = min(int(target_shape[0]), z_start + slab_depth)
        coordinates = np.meshgrid(axes[0][z_start:z_stop], axes[1], axes[2], indexing="ij")
        sampled_distance = ndimage.map_coordinates(
            signed_distance,
            coordinates,
            order=1,
            mode="nearest",
            prefilter=False,
        )
        sampled_mask[z_start:z_stop] = sampled_distance <= 0.0
        if sampled_signed_distance is not None:
            sampled_signed_distance[z_start:z_stop] = sampled_distance

    result_spacing = tuple(float(value) for value in target_spacing)
    if sampled_signed_distance is not None:
        return sampled_mask, result_spacing, sampled_signed_distance
    return sampled_mask, result_spacing


def _remove_truncated_cap_backed_voxels(
    solid: np.ndarray,
    body_mask: np.ndarray,
    signed_distance: np.ndarray,
    spacing_zyx: Sequence[float],
    *,
    remove_lower_cap: bool,
    remove_upper_cap: bool,
) -> int:
    """Remove guide voxels supported by a finite-CT boundary rather than skin.

    The nearest-point query separates exactly for a flat z cap: the distance
    to a cap voxel is the hypotenuse of its z offset and the 2D distance to the
    cap mask. Computing those two small 2D transforms and checking only active
    shell voxels replaces a full 3D EDT with three nearest-index volumes. The
    half-voxel tolerance is deliberately conservative at the cap/skin tie so
    acceleration cannot make the guide rely on a truncated scan boundary.
    """
    from scipy import ndimage

    if not (remove_lower_cap or remove_upper_cap):
        return 0
    solid = np.asarray(solid)
    body_mask = np.asarray(body_mask, dtype=bool)
    signed_distance = np.asarray(signed_distance)
    spacing = np.asarray(spacing_zyx, dtype=np.float64)
    tolerance_mm = 0.5 * float(np.linalg.norm(spacing))
    cap_distances: List[Tuple[int, np.ndarray]] = []
    if remove_lower_cap and bool(np.any(body_mask[0])):
        cap_distances.append((
            0,
            ndimage.distance_transform_edt(
                ~body_mask[0], sampling=tuple(float(value) for value in spacing[1:])
            ),
        ))
    if remove_upper_cap and bool(np.any(body_mask[-1])):
        cap_distances.append((
            int(body_mask.shape[0] - 1),
            ndimage.distance_transform_edt(
                ~body_mask[-1], sampling=tuple(float(value) for value in spacing[1:])
            ),
        ))

    removed = 0
    for z_index in range(int(solid.shape[0])):
        yy, xx = np.nonzero(solid[z_index])
        if yy.size == 0:
            continue
        supported_by_cap = np.zeros(yy.size, dtype=bool)
        surface_distance = np.maximum(
            signed_distance[z_index, yy, xx].astype(np.float64, copy=False),
            0.0,
        )
        for cap_z, lateral_distance in cap_distances:
            axial_distance = abs(z_index - cap_z) * float(spacing[0])
            distance_to_cap = np.hypot(axial_distance, lateral_distance[yy, xx])
            supported_by_cap |= distance_to_cap <= surface_distance + tolerance_mm
        if bool(np.any(supported_by_cap)):
            solid[z_index, yy[supported_by_cap], xx[supported_by_cap]] = False
            removed += int(np.count_nonzero(supported_by_cap))
    return removed


def _mesh_from_mask(
    mask: np.ndarray,
    ct_image: Any,
    lower_xyz: np.ndarray,
    spacing_xyz: Sequence[float],
) -> Tuple[np.ndarray, np.ndarray]:
    """Isosurface a boolean solid mask into a smooth, watertight mesh.

    The solid is built as a boolean volume (plate ∩ patch, union sleeves,
    subtract bores), so Marching Cubes on it is watertight by construction —
    this cannot produce the degenerate creases or open edges that direct
    SDF-CSG min/max isosurfacing can. Before extraction the mask is lightly
    blurred (anti-aliasing) so the isosurface rounds the CSG creases and voxel
    stair-steps into smooth fillets instead of hard edges. The blur sigma is a
    small fraction of the construction grid, well below the channel bore
    radius, so it never closes a through-hole. The extracted surface is then
    Taubin-smoothed (shrink-free) in local millimetre space before the world
    transform, producing a printable surface without pulling the plate off the
    skin.
    """
    from skimage import measure
    from scipy import ndimage as _ndi

    if not bool(np.any(mask)):
        raise SurgicalGuideError("Guide construction produced an empty plate")
    spacing_xyz = np.asarray(spacing_xyz, dtype=np.float64)
    spacing_zyx = tuple(float(value) for value in spacing_xyz[::-1])
    # Sub-voxel blur rounds the voxel steps and CSG creases. It is capped below
    # the smallest guide feature (the needle bore) so the through-holes stay
    # open, and it never exceeds a fraction of a voxel on coarse grids.
    blur_sigma = min(0.4, 0.35 * float(np.min(spacing_zyx)))
    field = _ndi.gaussian_filter(mask.astype(np.float64), sigma=blur_sigma)
    padded = np.pad(field, 1, mode="constant", constant_values=0.0)
    vertices_zyx, faces, _, _ = measure.marching_cubes(
        padded,
        level=0.5,
        spacing=spacing_zyx,
        allow_degenerate=False,
        method="lewiner",
    )
    # Remove the one-voxel padding and transform local physical coordinates
    # through the CT direction matrix.  The local origin crossed SimpleITK's
    # canonical transform above, so this is equivalent to index-to-world for
    # the resampled lattice and supports arbitrary orientation matrices.
    index_zyx = vertices_zyx / np.asarray(spacing_zyx, dtype=np.float64) - 1.0
    local_xyz_mm = index_zyx[:, ::-1] * spacing_xyz
    # Taubin-smooth the extracted surface in local millimetre space before the
    # world transform. Taubin is shrink-free: it removes the residual facet
    # steps while preserving the plate's skin fit, the channel geometry and the
    # sleeve axis alignment.
    local_xyz_mm = _smooth_mesh_vertices(local_xyz_mm, np.asarray(faces, dtype=np.int64))
    crop_origin = _crop_origin_world(ct_image, lower_xyz)
    direction = np.asarray(ct_image.GetDirection(), dtype=np.float64).reshape(3, 3)
    vertices_world = (direction @ local_xyz_mm.T).T + crop_origin
    return vertices_world.astype(np.float32), np.asarray(faces, dtype=np.int32)


def _smooth_mesh_vertices(
    vertices: np.ndarray,
    faces: np.ndarray,
    iterations: int = 20,
    lambda_factor: float = 0.5,
    mu_factor: Optional[float] = None,
) -> np.ndarray:
    """Apply Taubin smoothing to a triangle mesh without shrinking it.

    A plain uniform Laplacian (the previous implementation) both smooths and
    shrinks the surface, so raising the iteration count to remove the visible
    voxel stair-steps would also pull the guide's faces off the intended skin
    fit. Taubin's lambda/mu two-pole scheme (a positive ``lambda`` pass
    followed by a negative ``mu`` pass) removes the faceted high frequencies
    while preserving the low-frequency shape, so the guide gets visibly
    smoother and more refined without losing the plate's skin contact or the
    channel geometry. The default 20 lambda/mu cycles turn a Marching-Cubes
    surface on the smooth guide SDF into a printable surface (a pure Laplacian
    needs ~60 passes and would shrink the plate by ~0.5 mm).

    Only vertex positions change; the face connectivity is untouched so the
    mesh stays watertight and the needle bores stay open.
    """
    import numpy as np

    verts = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    if verts.ndim != 2 or verts.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        return np.asarray(vertices, dtype=np.float64)
    if len(verts) == 0 or len(faces) == 0:
        return np.asarray(vertices, dtype=np.float64)
    mu = float(mu_factor) if mu_factor is not None else -float(lambda_factor) - 0.1

    # Build one-ring adjacency (both edge directions) from faces.
    edge_forward = faces[:, [0, 1, 2]].reshape(-1)
    edge_back = faces[:, [1, 2, 0]].reshape(-1)
    import scipy.sparse as sparse

    data = np.ones(edge_forward.size, dtype=np.float64)
    adjacency = sparse.csr_matrix(
        (data, (edge_forward, edge_back)),
        shape=(len(verts), len(verts)),
    )
    adjacency = (adjacency + adjacency.T).tocsr()
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    degree = np.maximum(degree, 1.0)

    smoothed = verts.copy()
    for _ in range(int(iterations)):
        neighbour_sum = np.asarray(adjacency.dot(smoothed))
        average = neighbour_sum / degree[:, None]
        # Positive lambda pass.
        smoothed = smoothed + float(lambda_factor) * (average - smoothed)
        # Negative mu pass (Taubin's second pole) removes the shrinkage the
        # positive pass introduces, netting a shrink-free smoother.
        neighbour_sum = np.asarray(adjacency.dot(smoothed))
        average = neighbour_sum / degree[:, None]
        smoothed = smoothed + mu * (average - smoothed)
    return smoothed


def _project_bore_walls(
    vertices: np.ndarray,
    paths: Sequence[NeedleGuidePath],
    auxiliary_specs: Sequence[Mapping[str, Any]],
    params: Mapping[str, Any],
    *,
    primary_bore_specs: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Restore exact circular cross-sections on the exported bore walls.

    The guide is intentionally built as a boolean volume and extracted with
    Marching Cubes so that the complete STL remains watertight.  That process
    is robust for the union/subtraction topology, but it is not a suitable
    final definition for a manufactured needle bore: smoothing may move a
    wall vertex a fraction of a millimetre toward or away from the axis.  This
    pass projects only the narrow radial band around each final CSG cutter
    back to its analytic radius.  It does not add material or alter the
    auxiliary/main-hole ordering.

    ``bore_radius`` includes the manufacturing clearance used during the
    boolean subtraction.  Recording the before/after error gives the export
    route a concrete geometry QA result instead of relying on the Viewer.
    """
    result = np.asarray(vertices, dtype=np.float64).copy()
    resolution = float(params["geometry_resolution_mm"])
    tolerance = max(
        BORE_WALL_PROJECTION_MIN_TOLERANCE_MM,
        min(0.75, resolution * BORE_WALL_PROJECTION_TOLERANCE_FACTOR),
    )
    reports: List[Dict[str, Any]] = []
    projected_indices: set[int] = set()
    provided_primary_bores: Dict[str, Mapping[str, Any]] = {}
    for spec in primary_bore_specs or ():
        if not isinstance(spec, Mapping):
            continue
        needle_id = str(spec.get("needle_id") or "")
        if needle_id and spec.get("start") is not None and spec.get("end") is not None:
            provided_primary_bores[needle_id] = spec

    def primary_bore_for_path(path: NeedleGuidePath) -> Tuple[np.ndarray, np.ndarray, float]:
        """Return the final CSG cutter used for this channel, if available."""
        provided = provided_primary_bores.get(str(path.needle_id))
        if provided is not None:
            return (
                np.asarray(provided["start"], dtype=np.float64),
                np.asarray(provided["end"], dtype=np.float64),
                float(provided.get("radius_mm") or _effective_primary_bore_radius_mm(params)),
            )
        sleeve_inner, sleeve_outer = _primary_sleeve_segment(path, params)
        return sleeve_inner, sleeve_outer, _effective_primary_bore_radius_mm(params)

    # The Boolean CSG already drills every primary channel after all sleeves
    # have been unioned.  This later analytic wall pass must preserve those
    # cavities: a vertex snapped onto one sleeve wall must never be moved into
    # another channel's open volume at a close or crossing trajectory.
    #
    # The wall projection may move a vertex by up to ``tolerance``. Guard at
    # least that entire correction distance so a triangle adjacent to a
    # neighbouring bore cannot be pulled back across the final CSG void.
    cross_bore_guard_mm = max(tolerance, min(0.75, resolution * 0.75))
    protected_bores: List[Dict[str, Any]] = []
    for path in paths:
        sleeve_inner, sleeve_outer, bore_radius = primary_bore_for_path(path)
        protected_bores.append({
            "identity": ("primary", str(path.needle_id)),
            "start": sleeve_inner,
            "end": sleeve_outer,
            "radius_mm": bore_radius,
        })
    for spec in auxiliary_specs:
        if bool(spec.get("skipped")):
            continue
        protected_bores.append({
            "identity": ("auxiliary", str(spec.get("id") or "auxiliary_hole")),
            "start": np.asarray(spec.get("start"), dtype=np.float64),
            "end": np.asarray(spec.get("end"), dtype=np.float64),
            "radius_mm": float(spec["radius_mm"]),
        })

    def _inside_flat_cylinder(
        points: np.ndarray,
        start: np.ndarray,
        end: np.ndarray,
        radius: float,
    ) -> np.ndarray:
        """Return whether each sparse vertex lies inside a protected bore."""
        axis_vector = np.asarray(end, dtype=np.float64) - np.asarray(start, dtype=np.float64)
        length = float(np.linalg.norm(axis_vector))
        if length <= 1e-8:
            return np.zeros(len(points), dtype=bool)
        axis = axis_vector / length
        relative = np.asarray(points, dtype=np.float64) - np.asarray(start, dtype=np.float64)
        axial = relative @ axis
        radial_vector = relative - np.outer(axial, axis)
        radial = np.linalg.norm(radial_vector, axis=1)
        return (
            (axial >= -cross_bore_guard_mm)
            & (axial <= length + cross_bore_guard_mm)
            & (radial <= float(radius) + cross_bore_guard_mm)
        )

    def project_wall(
        *,
        hole_id: str,
        kind: str,
        start: np.ndarray,
        end: np.ndarray,
        radius: float,
        identity: Tuple[str, str],
    ) -> None:
        axis_vector = np.asarray(end, dtype=np.float64) - np.asarray(start, dtype=np.float64)
        length = float(np.linalg.norm(axis_vector))
        if length <= 1e-8:
            return
        axis = axis_vector / length
        relative = result - np.asarray(start, dtype=np.float64)
        axial = relative @ axis
        radial_vector = relative - np.outer(axial, axis)
        radial = np.linalg.norm(radial_vector, axis=1)
        radial_error_before = np.abs(radial - float(radius))
        selected = (
            (axial >= -tolerance)
            & (axial <= length + tolerance)
            & (radial > 1e-8)
            & (radial_error_before <= tolerance)
        )
        selected_indices = np.flatnonzero(selected)
        protected_count = 0
        if selected_indices.size:
            unit_radial = radial_vector[selected_indices] / radial[selected_indices, None]
            # Keep the original axial coordinate.  Only the cross-sectional
            # radius is corrected, preserving the flat end faces and the
            # sleeve/plate intersection generated by the boolean volume.
            candidate_points = (
                np.asarray(start, dtype=np.float64)
                + axial[selected_indices, None] * axis
                + float(radius) * unit_radial
            )
            keep = np.ones(selected_indices.size, dtype=bool)
            for protected in protected_bores:
                if protected["identity"] == identity:
                    continue
                keep &= ~_inside_flat_cylinder(
                    candidate_points,
                    protected["start"],
                    protected["end"],
                    float(protected["radius_mm"]),
                )
            protected_count = int(np.count_nonzero(~keep))
            selected_indices = selected_indices[keep]
            candidate_points = candidate_points[keep]
            if selected_indices.size:
                result[selected_indices] = candidate_points
            projected_indices.update(int(index) for index in selected_indices)
        radial_after = np.linalg.norm(
            result[selected_indices]
            - np.asarray(start, dtype=np.float64)
            - axial[selected_indices, None] * axis,
            axis=1,
        ) if selected_indices.size else np.empty(0, dtype=np.float64)
        reports.append({
            "id": str(hole_id),
            "kind": str(kind),
            "radius_mm": float(radius),
            "length_mm": length,
            "projected_vertex_count": int(selected_indices.size),
            "max_radius_error_before_mm": float(radial_error_before[selected_indices].max()) if selected_indices.size else 0.0,
            "max_radius_error_after_mm": float(np.abs(radial_after - float(radius)).max()) if selected_indices.size else 0.0,
            "tolerance_mm": tolerance,
            "cross_bore_protected_vertex_count": protected_count,
            "cross_bore_guard_mm": cross_bore_guard_mm,
        })

    for path in paths:
        sleeve_inner, sleeve_outer, bore_radius = primary_bore_for_path(path)
        project_wall(
            hole_id=path.needle_id,
            kind="primary",
            start=sleeve_inner,
            end=sleeve_outer,
            radius=bore_radius,
            identity=("primary", str(path.needle_id)),
        )

    for spec in auxiliary_specs:
        if bool(spec.get("skipped")):
            continue
        start = np.asarray(spec.get("start"), dtype=np.float64)
        end = np.asarray(spec.get("end"), dtype=np.float64)
        project_wall(
            hole_id=str(spec.get("id") or "auxiliary_hole"),
            kind="auxiliary",
            start=start,
            end=end,
            radius=float(spec["radius_mm"]),
            identity=("auxiliary", str(spec.get("id") or "auxiliary_hole")),
        )

    primary = [item for item in reports if item["kind"] == "primary"]
    auxiliary = [item for item in reports if item["kind"] == "auxiliary"]
    return result.astype(np.float32), {
        "wall_policy": BORE_WALL_POLICY,
        "tolerance_mm": tolerance,
        "projected_vertex_count": len(projected_indices),
        "primary": primary,
        "auxiliary": auxiliary,
        "max_radius_error_after_mm": max(
            (float(item["max_radius_error_after_mm"]) for item in reports),
            default=0.0,
        ),
    }


def mesh_validation(vertices: np.ndarray, faces: np.ndarray) -> Dict[str, Any]:
    """Return deterministic mesh QA including a strict watertightness check."""
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        return {"valid": False, "watertight": False, "reason": "invalid_mesh_shape"}
    if len(vertices) < 4 or len(faces) < 4 or not np.all(np.isfinite(vertices)):
        return {"valid": False, "watertight": False, "reason": "empty_or_nonfinite_mesh"}
    if np.any(faces < 0) or np.any(faces >= len(vertices)):
        return {"valid": False, "watertight": False, "reason": "face_index_out_of_range"}
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]), axis=0)
    edges.sort(axis=1)
    _, edge_counts = np.unique(edges, axis=0, return_counts=True)
    watertight = bool(np.all(edge_counts == 2))
    open_edges = int(np.count_nonzero(edge_counts == 1))
    nonmanifold_edges = int(np.count_nonzero(edge_counts > 2))
    bounds = [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()]
    return {
        "valid": watertight,
        "watertight": watertight,
        "vertex_count": int(len(vertices)),
        "face_count": int(len(faces)),
        "open_edges": open_edges,
        "nonmanifold_edges": nonmanifold_edges,
        "open_or_nonmanifold_edges": open_edges + nonmanifold_edges,
        "bounds_world_mm": bounds,
    }


def _planned_path_deviation(paths: Sequence[NeedleGuidePath]) -> List[Dict[str, Any]]:
    """QA the source geometry rather than inventing a second path convention."""
    checks = []
    for path in paths:
        line = path.target - path.external
        line_length = float(np.linalg.norm(line))
        if line_length <= 1e-8:
            raise SurgicalGuideError(f"Needle {path.needle_id} has zero length")
        # The sleeve centerline is built directly from this vector, therefore
        # its nominal geometric deviation is exactly zero.  Recording that
        # fact makes the exported guide's provenance auditable.
        checks.append({
            "needle_id": path.needle_id,
            "trajectory_id": path.trajectory_id,
            "entry_world_mm": path.entry.astype(float).tolist(),
            "direction_world": path.inward_direction.astype(float).tolist(),
            "line_length_mm": line_length,
            "seed_count": path.seed_count,
            "guide_centerline_deviation_mm": 0.0,
        })
    return checks


def generate_surgical_guide(
    agent: Any,
    raw_parameters: Optional[Mapping[str, Any]] = None,
    *,
    selected_needle_ids: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """Generate a CT skin-fitting puncture guide from current planned needles.

    The guide is an implicit solid: an external skin-offset shell intersected
    with a local patch and fused with sleeve cylinders, then bored by the
    corresponding planned needle axes.  Isosurfacing the final volume yields
    a closed mesh without depending on unavailable CGAL/VTK binaries.
    """
    from scipy import ndimage

    if agent is None or not hasattr(agent, "memory"):
        raise SurgicalGuideError("Agent is unavailable")
    generation_started = time.perf_counter()
    stage_started = generation_started
    stage_timings: Dict[str, float] = {}

    def finish_stage(name: str, **details: Any) -> None:
        """Record one stage without retaining any large intermediate arrays."""
        nonlocal stage_started
        now = time.perf_counter()
        duration = round(now - stage_started, 3)
        stage_timings[name] = duration
        stage_started = now
        suffix = " ".join(f"{key}={value}" for key, value in details.items())
        logger.info(
            "Surgical guide stage completed stage=%s duration_s=%.3f%s",
            name,
            duration,
            f" {suffix}" if suffix else "",
        )

    params = normalize_guide_parameters(raw_parameters)
    memory = agent.memory
    ct_image = memory.retrieve("ct_image")
    ct_data = memory.retrieve("ct_data")
    if ct_image is None or ct_data is None:
        raise SurgicalGuideError("Load a CT image before generating a puncture guide")
    raw_candidate = np.asarray(ct_data, dtype=np.float32) > float(
        params["skin_threshold_hu"]
    )
    # Detect finite-FOV caps from the original thresholded component before
    # binary closing or smoothing. Both operations can erode a one-voxel CT
    # face and erase the evidence that the acquisition was truncated.
    boundary_faces = _truncated_boundary_faces(_largest_component(raw_candidate))
    body = _body_mask(np.asarray(ct_data), params["skin_threshold_hu"])
    # Smooth the body envelope so the guide plate follows a smooth skin
    # surface instead of the CT's slice steps (real CTs often have 5 mm
    # slices — far coarser than the 3 mm plate). Entries and the printable
    # shell must use the exact same smoothed envelope so the sleeves always
    # meet the exported plate.
    body = _smooth_body_mask(body, source_spacing_zyx=tuple(
        float(value) for value in np.asarray(ct_image.GetSpacing(), dtype=np.float64)[::-1]
    ), sigma_mm=2.0)
    finish_stage("skin_envelope", source_shape=tuple(int(value) for value in body.shape))
    # Persist before the expensive guide CSG begins. Even when a downstream
    # manufacturability check rejects the guide mesh, the successfully derived
    # skin segmentation remains available for inspection and parameter repair.
    skin_surface = store_guide_skin_surface(
        agent,
        body,
        ct_image=ct_image,
        threshold_hu=params["skin_threshold_hu"],
    )
    finish_stage("skin_surface_persisted")
    # Finite-FOV detection: if the body envelope is truncated by the CT scan
    # boundaries, the guide must only be built from real lateral skin. Entries
    # falling on a truncated flat plane are rejected inside _path_records;
    # record the truncation state so the caller can warn the operator.
    trunc_z_min = bool(boundary_faces["z_min"])
    trunc_z_max = bool(boundary_faces["z_max"])
    paths = _path_records(agent, body, selected_needle_ids)
    auxiliary_specs = _auxiliary_hole_specs(paths, params)
    truncated_fov = bool(any(boundary_faces.values()))

    span_margin = (
        params["patch_margin_mm"]
        + params["skin_clearance_mm"]
        + params["plate_thickness_mm"]
        + params["sleeve_outward_mm"]
        + params["sleeve_outer_radius_mm"]
        # sleeve_inward_mm is accepted for compatibility but no longer moves
        # any geometry (the channel is clamped flush with the skin), so it must
        # not size the crop and change the guide's discretised mesh.
    )
    lower_xyz, upper_xyz = _crop_bounds(ct_image, [path.entry for path in paths], span_margin)
    lower_zyx = lower_xyz[::-1]
    upper_zyx = upper_xyz[::-1]
    body_crop = body[
        lower_zyx[0]:upper_zyx[0] + 1,
        lower_zyx[1]:upper_zyx[1] + 1,
        lower_zyx[2]:upper_zyx[2] + 1,
    ]
    if not bool(np.any(body_crop)):
        raise SurgicalGuideError("The planned skin entry lies outside the CT-derived body surface")
    source_spacing_zyx = tuple(
        float(value) for value in np.asarray(ct_image.GetSpacing(), dtype=np.float64)[::-1]
    )
    # Reconstruct the local skin zero-level surface on the requested isotropic
    # physical grid. The CT is never globally resampled or written back; only
    # the bounded guide patch is sampled for CSG and STL extraction.
    body_crop, spacing_zyx, skin_signed_distance = _resample_mask_to_local_grid(
        body_crop,
        source_spacing_zyx,
        params["geometry_resolution_mm"],
        return_signed_distance=True,
    )
    # The full skin mask is a first-class Data Tree segmentation, but it is
    # never allowed to define a printable cap at a finite CT boundary. Keep a
    # separate local safety domain for CSG instead of mutating the persisted
    # skin mask or relying on a post-mesh cleanup pass.
    boundary_safe_mask, boundary_safety = _local_boundary_safety_mask(
        body_crop.shape,
        lower_zyx,
        upper_zyx,
        body.shape,
        boundary_faces,
        spacing_zyx,
        params["truncation_margin_mm"],
    )
    finish_stage(
        "local_grid_resampled",
        grid_shape=tuple(int(value) for value in body_crop.shape),
        grid_voxels=int(body_crop.size),
        boundary_guard_voxels=boundary_safety["excluded_faces"],
    )
    spacing_xyz = tuple(reversed(spacing_zyx))
    # Reuse the physical signed-distance field that produced the smooth local
    # body mask. Recomputing an EDT after thresholding this 0.2 mm grid both
    # quantised the surface a second time and cost minutes for a 200M-voxel
    # guide crop. Positive values are true physical distance outside the skin;
    # negative values are inside and remain excluded by ``~body_crop`` below.
    outside_distance = skin_signed_distance
    finish_stage("skin_distance_field_reused", truncated_fov=truncated_fov)
    clearance = params["skin_clearance_mm"]
    plate_thickness = params["plate_thickness_mm"]
    # The zero level of a sampled label distance is uncertain within half a
    # construction-voxel diagonal. Keep that sub-voxel guard outside the skin
    # so later Taubin smoothing cannot pull an oblique sleeve wall back into
    # the patient. At the default 0.2 mm grid this is only 0.173 mm and does not
    # change the configured plate thickness or any bore diameter.
    surface_guard_mm = 0.5 * float(np.linalg.norm(np.asarray(spacing_zyx)))
    protected_clearance = clearance + surface_guard_mm
    # Plate mask: voxels inside the shell band [clearance, clearance+thickness]
    # offset OUTSIDE the skin (od > 0 means outside the body; od=0 is the body
    # interior and must be excluded), intersected with the patch sphere around
    # every entry. The boolean mask (not an SDF max) keeps the isosurface
    # watertight by construction: Marching-Cubes on a binary volume is always a
    # closed manifold, avoiding the degenerate creases that SDF-CSG min/max
    # produce.
    plate_mask = (
        (~body_crop)
        & (outside_distance >= protected_clearance)
        & (outside_distance <= protected_clearance + plate_thickness)
        & boundary_safe_mask
    )
    # Patch mask: spherical region of radius patch_margin_mm around every entry.
    # The local grid is isotropic, so a world distance equals an index distance
    # scaled by the uniform spacing. Convert each entry to a local continuous
    # index once and compute the patch distance ONLY on the plate-shell voxels
    # (a few percent of the crop), via a KD-tree of the entry indices. This is
    # exact (the same continuous-index transform as the world grid) and avoids
    # the full-size per-entry squared-distance array pass.
    patch_radius_index = params["patch_margin_mm"] / float(spacing_zyx[0])
    plate_voxel_indices = np.argwhere(plate_mask)
    entry_indices = np.array([
        _world_to_local_index_zyx(ct_image, lower_xyz, path.entry, spacing_xyz)
        for path in paths
    ], dtype=np.float32)
    patch_mask = np.zeros_like(plate_mask)
    if plate_voxel_indices.size:
        from scipy.spatial import cKDTree

        if len(entry_indices):
            entry_tree = cKDTree(entry_indices)
            distance, _ = entry_tree.query(plate_voxel_indices.astype(np.float32))
            plate_voxel_indices = plate_voxel_indices[distance <= patch_radius_index]
            patch_mask[tuple(plate_voxel_indices.T)] = True
    solid = plate_mask & patch_mask
    solid, plate_connectivity = _connect_plate_patch_components(
        plate_mask,
        solid,
        entry_indices,
        spacing_zyx,
    )
    finish_stage(
        "plate_patch",
        plate_voxels=int(np.count_nonzero(solid)),
        initial_components=plate_connectivity["initial_component_count"],
        bridges=plate_connectivity["bridge_count"],
    )
    # Pass 1: subtract every auxiliary hole from the bare plate first. This is
    # deliberately done before adding any primary sleeve: the auxiliary holes
    # are plate-only alternate paths, and their validated radial offset keeps
    # them outside the primary sleeve wall. They therefore cannot be filled by
    # or cut into the primary channel when the main geometry is fused below.
    realized_auxiliary_specs: List[Dict[str, Any]] = []
    for spec in auxiliary_specs:
        if bool(spec.get("skipped")):
            continue
        supported, support_reason = _auxiliary_hole_support(
            solid,
            ct_image,
            lower_xyz,
            spacing_xyz,
            np.asarray(spec["start"], dtype=np.float64),
            np.asarray(spec["end"], dtype=np.float64),
            float(spec["radius_mm"]),
            float(plate_thickness),
        )
        if not supported:
            # Never export a candidate that only removes a crescent or a
            # shallow dimple from the plate.  The skipped reason is persisted
            # in the guide QA payload so the operator can distinguish a
            # geometric boundary from a needle-spacing conflict.
            spec["skipped"] = True
            spec["skip_reason"] = support_reason
            continue
        hole_sdf, box = _cylinder_sdf_in_region(
            ct_image, lower_xyz, body_crop.shape, spacing_xyz,
            np.asarray(spec["start"], dtype=np.float64),
            np.asarray(spec["end"], dtype=np.float64),
            float(spec["radius_mm"]),
        )
        hole_mask = hole_sdf <= 0.0
        removable = solid[box] & plate_mask[box] & hole_mask
        if not bool(np.any(removable)):
            # The requested alternate line can fall outside a sharply curved
            # or truncated patch. Record it as skipped rather than silently
            # claiming that a physical hole was generated.
            spec["skipped"] = True
            spec["skip_reason"] = "outside_plate_patch"
            continue
        solid[box] &= ~(plate_mask[box] & hole_mask)
        realized_auxiliary_specs.append(spec)
    finish_stage(
        "auxiliary_holes",
        requested=len(auxiliary_specs),
        realized=len(realized_auxiliary_specs),
    )

    # Pass 2: union ALL sleeve cylinders, so the plate and every primary
    # sleeve form one merged solid before any primary bore is drilled. If the
    # bores were subtracted inside this loop, a later needle's sleeve wall
    # could re-enter an earlier needle's already-drilled channel and plug it.
    # Sleeve and bore volumes are exact flat-ended cylinder SDFs, not voxel
    # facets, so the merged solid has clean round walls.
    for path in paths:
        entry = path.entry
        sleeve_inner = entry - path.inward_direction * clearance
        sleeve_outer = sleeve_inner - path.inward_direction * (
            plate_thickness + params["sleeve_outward_mm"]
        )
        sleeve_sdf, box = _cylinder_sdf_in_region(
            ct_image, lower_xyz, body_crop.shape, spacing_xyz,
            sleeve_inner, sleeve_outer, params["sleeve_outer_radius_mm"],
        )
        # Trim the sleeve's skin-facing side flush with the plate: for oblique
        # needles the sleeve wall can cross the skin, so clip it at the
        # clearance offset before unioning.
        sleeve_mask = (
            (sleeve_sdf <= 0.0)
            & (outside_distance[box] >= protected_clearance)
            & boundary_safe_mask[box]
        )
        solid[box] |= sleeve_mask

    # Unioning sleeves after the first auxiliary subtraction can reintroduce
    # material at a nearby boundary. Re-cut the validated auxiliary bores after
    # the sleeve pass, while limiting the operation to plate voxels so no
    # primary sleeve wall can be damaged.
    for spec in realized_auxiliary_specs:
        hole_sdf, box = _cylinder_sdf_in_region(
            ct_image,
            lower_xyz,
            body_crop.shape,
            spacing_xyz,
            np.asarray(spec["start"], dtype=np.float64),
            np.asarray(spec["end"], dtype=np.float64),
            float(spec["radius_mm"]),
        )
        solid[box] &= ~(plate_mask[box] & (hole_sdf <= 0.0))

    # Pass 3: drill every main channel from the fully-unioned solid. The
    # cutter is deliberately longer than its own sleeve where another sleeve
    # can cross it: a wall belonging to a neighbouring needle must never remain
    # inside this channel just because the crossing falls beyond the first
    # sleeve's finite outer tip.
    primary_bore_specs = _primary_bore_cutter_specs(paths, params)
    needle_spacing = _needle_spacing_quality(paths, params)
    _subtract_cylinder_specs_from_mask(
        solid,
        ct_image,
        lower_xyz,
        spacing_xyz,
        primary_bore_specs,
    )
    # Re-apply the domain after all unions. This is intentionally redundant:
    # it protects the geometry if a future CSG stage adds a new volume without
    # remembering to intersect it with the acquisition-safe domain.
    solid &= boundary_safe_mask
    finish_stage("primary_sleeves_and_bores", needle_count=len(paths))
    # Reject plate voxels that are backed by a truncated flat cap. When the
    # body envelope is cut by the CT first/last slice, the cap plane is NOT
    # anatomical skin: any guide voxel whose nearest body voxel lies on the
    # truncated boundary slice would hug the cut, so it is removed. This
    # guarantees the plate only contacts real lateral skin.
    if truncated_fov:
        removed_cap_voxels = _remove_truncated_cap_backed_voxels(
            solid,
            body_crop,
            skin_signed_distance,
            spacing_zyx,
            remove_lower_cap=bool(trunc_z_min and int(lower_zyx[0]) == 0),
            remove_upper_cap=bool(
                trunc_z_max and int(upper_zyx[0]) == int(body.shape[0] - 1)
            ),
        )
        logger.info(
            "Surgical guide finite-FOV cap rejection removed_voxels=%d",
            removed_cap_voxels,
        )
    # Shave the guide off the CT scan boundaries (finite FOV): keep a clear
    # safety margin between the plate and the truncation plane so the guide
    # never contacts the flat scan-boundary cut.
    if truncated_fov:
        boundary_voxels = max(1, int(round(params["truncation_margin_mm"] / max(1e-6, spacing_zyx[0]))))
        ct_z_min = int(lower_zyx[0]) == 0
        ct_z_max = int(upper_zyx[0]) == int(body.shape[0] - 1)
        if trunc_z_min and ct_z_min:
            solid[:boundary_voxels] = False
        if trunc_z_max and ct_z_max:
            solid[-boundary_voxels:] = False
    solid &= boundary_safe_mask
    # Dense primary bores can cut out islands of material between neighbouring
    # channels. They are not separate printable guide parts. Retain one
    # deterministic main component, but verify that every primary sleeve still
    # has retained wall material before allowing the guide to continue.
    solid, component_cleanup = _retain_largest_printable_component(
        solid,
        int(params["minimum_component_voxels"]),
    )
    if not bool(np.any(solid)):
        raise SurgicalGuideError(
            "The CT does not cover enough real skin to support a puncture guide "
            "near the planned needles. Load a scan that includes the full body "
            "surface around the target, or move the needle entries away from the "
            "scan boundary."
        )
    primary_sleeve_support = _primary_sleeve_support_quality(
        solid,
        ct_image,
        lower_xyz,
        spacing_xyz,
        paths,
        params,
    )
    if not bool(primary_sleeve_support.get("valid")):
        unsupported = ", ".join(
            str(value)
            for value in primary_sleeve_support.get("unsupported_needle_ids") or []
        )
        raise SurgicalGuideError(
            "Dense primary needle bores removed the printable wall support for "
            f"{unsupported or 'one or more channels'}; reduce the local needle "
            "density or revise the affected needle geometry before generating "
            "a guide"
        )
    final_solid_component_count = _face_component_count(solid)
    if final_solid_component_count != 1:
        raise SurgicalGuideError(
            "The guide remains disconnected after removing CSG material islands; "
            "one printable guide cannot be produced safely from the current "
            "needle geometry"
        )
    plate_connectivity["final_component_count"] = final_solid_component_count
    plate_connectivity["single_piece"] = True
    plate_connectivity["post_csg_component_count"] = int(
        component_cleanup["input_component_count"]
    )
    plate_connectivity["component_cleanup"] = component_cleanup
    plate_connectivity["primary_sleeve_support"] = primary_sleeve_support
    finish_stage("solid_cleanup", solid_voxels=int(np.count_nonzero(solid)))
    # Marching Cubes is topologically correct for ordinary binary volumes,
    # but a thin plate intersected by several closely spaced bores can still
    # contain one-voxel diagonal cracks at ambiguous voxel configurations.
    # Keep the first pass unchanged for maximum geometric fidelity, and only
    # use the repair pass if the extracted mesh actually fails the strict
    # edge-closure check below.
    mesh_repair: Dict[str, Any] = {
        "attempted": False,
        "method": None,
        "initial_open_or_nonmanifold_edges": 0,
    }
    vertices, faces = _mesh_from_mask(solid, ct_image, lower_xyz, spacing_xyz)
    # Marching Cubes and the global Taubin pass are retained for the plate and
    # sleeve topology, but the clinically relevant needle interfaces must be
    # true cylindrical walls in the manufacturing mesh.  Restore those walls
    # after smoothing, before any STL is persisted or exported.
    vertices, bore_quality = _project_bore_walls(
        vertices,
        paths,
        realized_auxiliary_specs,
        params,
        primary_bore_specs=primary_bore_specs,
    )
    validation = mesh_validation(vertices, faces)
    finish_stage(
        "mesh_extraction_and_validation",
        vertices=len(vertices),
        faces=len(faces),
        watertight=bool(validation.get("watertight")),
    )
    if not validation.get("watertight"):
        mesh_repair["attempted"] = True
        mesh_repair["method"] = "restricted_voxel_closing_and_bore_recut"
        mesh_repair["initial_open_or_nonmanifold_edges"] = int(
            validation.get("open_or_nonmanifold_edges") or 0
        )

        # Close only one-voxel topology cracks. The result is constrained back
        # to the real lateral skin shell, then every known bore is cut again.
        # Re-cutting is essential: a closing operation must never fill a main
        # needle channel or an auxiliary alternate puncture hole.
        repaired_solid = ndimage.binary_closing(
            solid,
            structure=ndimage.generate_binary_structure(3, 1),
            iterations=1,
        )
        repaired_solid &= (~body_crop) & (outside_distance >= protected_clearance)
        repaired_solid &= boundary_safe_mask

        for spec in realized_auxiliary_specs:
            hole_sdf, box = _cylinder_sdf_in_region(
                ct_image,
                lower_xyz,
                body_crop.shape,
                spacing_xyz,
                np.asarray(spec["start"], dtype=np.float64),
                np.asarray(spec["end"], dtype=np.float64),
                float(spec["radius_mm"]),
            )
            repaired_solid[box] &= ~(hole_sdf <= 0.0)
        # A binary closing repair may restore material at channel/sleeve
        # intersections. Reuse the exact final cutters rather than a shorter
        # sleeve-only bore so repair cannot reintroduce the blocked-hole bug.
        _subtract_cylinder_specs_from_mask(
            repaired_solid,
            ct_image,
            lower_xyz,
            spacing_xyz,
            primary_bore_specs,
        )
        repaired_solid, repaired_component_cleanup = _retain_largest_printable_component(
            repaired_solid,
            int(params["minimum_component_voxels"]),
        )

        if bool(np.any(repaired_solid)):
            repaired_vertices, repaired_faces = _mesh_from_mask(
                repaired_solid,
                ct_image,
                lower_xyz,
                spacing_xyz,
            )
            repaired_vertices, repaired_bore_quality = _project_bore_walls(
                repaired_vertices,
                paths,
                realized_auxiliary_specs,
                params,
                primary_bore_specs=primary_bore_specs,
            )
            repaired_validation = mesh_validation(repaired_vertices, repaired_faces)
            repaired_support = _primary_sleeve_support_quality(
                repaired_solid,
                ct_image,
                lower_xyz,
                spacing_xyz,
                paths,
                params,
            )
            if repaired_validation.get("watertight") and repaired_support.get("valid"):
                vertices = repaired_vertices
                faces = repaired_faces
                bore_quality = repaired_bore_quality
                validation = repaired_validation
                primary_sleeve_support = repaired_support
                plate_connectivity["component_cleanup_after_mesh_repair"] = (
                    repaired_component_cleanup
                )
                mesh_repair["repaired_open_or_nonmanifold_edges"] = int(
                    validation.get("open_or_nonmanifold_edges") or 0
                )

        if not validation.get("watertight"):
            open_edges = int(validation.get("open_edges") or 0)
            nonmanifold_edges = int(validation.get("nonmanifold_edges") or 0)
            if nonmanifold_edges and not open_edges:
                guidance = (
                    "the generated channels contain an unresolved geometric intersection"
                )
            elif open_edges and not nonmanifold_edges:
                guidance = "the local skin or guide shell contains an unresolved opening"
            else:
                guidance = "the guide shell contains unresolved topology defects"
            raise SurgicalGuideError(
                "Generated guide mesh is not watertight after topology repair "
                f"(open edges: {open_edges}; non-manifold edges: {nonmanifold_edges}); "
                f"{guidance}"
            )
    if mesh_repair["attempted"]:
        finish_stage(
            "mesh_topology_repair",
            vertices=len(vertices),
            faces=len(faces),
            watertight=bool(validation.get("watertight")),
        )
    validation["mesh_repair"] = mesh_repair
    snapshot = _current_planning_snapshot(agent)
    prior = memory.retrieve("surgical_guide")
    signature = planning_signature(_algorithm_planning_snapshot(agent))
    # The guide belongs to the currently displayed Planning, including
    # algorithm-generated runs that do not have a manual planning id.  Keep
    # the legacy manual key only as a fallback for old sessions.
    try:
        from web.planning_runs import active_planning_id
        planning_id = str(active_planning_id(memory) or "")
    except Exception:
        planning_id = ""
    if not planning_id:
        planning_id = str(memory.retrieve("manual_planning_id") or "")
    # Deduplicate only duplicate generations for the same Planning.  A new
    # Planning must receive the next guide version even when its geometry and
    # manufacturing parameters happen to be identical to an older run.
    version = _resolve_guide_version(
        agent,
        prior,
        signature,
        params,
        planning_id or None,
    )
    planning_version = int(memory.retrieve("manual_plan_version") or 0)
    path_checks = _planned_path_deviation(paths)
    auxiliary_holes = {
        "enabled": bool(params.get("auxiliary_holes_enabled", False)),
        "requested_count": len(auxiliary_specs),
        "realized_count": len(realized_auxiliary_specs),
        "skipped_count": len(auxiliary_specs) - len(realized_auxiliary_specs),
        "ring_count": int(params["auxiliary_hole_ring_count"]),
        "holes_per_ring": int(params["auxiliary_holes_per_ring"]),
        "radius_mm": float(params["auxiliary_hole_radius_mm"]),
        "primary_bore_radius_mm": _effective_primary_bore_radius_mm(params),
        "diameter_match": abs(
            float(params["auxiliary_hole_radius_mm"])
            - _effective_primary_bore_radius_mm(params)
        ) <= 1e-6,
        "first_offset_mm": float(params["auxiliary_hole_first_offset_mm"]),
        "ring_spacing_mm": float(params["auxiliary_hole_ring_spacing_mm"]),
        "minimum_wall_mm": GUIDE_MINIMUM_WALL_MM,
        "through_plate_only": True,
        "non_protruding": True,
        "holes": [
            {
                "id": str(spec["id"]),
                "needle_id": str(spec["needle_id"]),
                "trajectory_id": str(spec["trajectory_id"]),
                "ring_index": int(spec["ring_index"]),
                "hole_index": int(spec["hole_index"]),
                "angle_degrees": float(spec["angle_degrees"]),
                "radial_offset_mm": float(spec["radial_offset_mm"]),
                "center_world_mm": np.asarray(spec["center"], dtype=float).tolist(),
            }
            for spec in realized_auxiliary_specs
        ],
        "skipped": [
            {
                "id": str(spec["id"]),
                "needle_id": str(spec["needle_id"]),
                "reason": str(spec.get("skip_reason") or "not_realized"),
                "conflicts_with": (
                    str(spec["conflicts_with"])
                    if spec.get("conflicts_with") is not None
                    else None
                ),
                "centerline_distance_mm": (
                    float(spec["centerline_distance_mm"])
                    if spec.get("centerline_distance_mm") is not None
                    else None
                ),
                "surface_clearance_mm": (
                    float(spec["surface_clearance_mm"])
                    if spec.get("surface_clearance_mm") is not None
                    else None
                ),
            }
            for spec in auxiliary_specs
            if bool(spec.get("skipped"))
        ],
    }
    stage_timings["total"] = round(time.perf_counter() - generation_started, 3)
    logger.info(
        "Surgical guide generation completed duration_s=%.3f needles=%d "
        "auxiliary_holes=%d vertices=%d faces=%d",
        stage_timings["total"],
        len(paths),
        len(realized_auxiliary_specs),
        len(vertices),
        len(faces),
    )
    # The guide covers the current displayed needle paths, but its validity
    # signature must be stable against the algorithm baseline: a manual needle
    # added after generation must not hide this guide or disable its update
    # path (guide_metadata compares against _algorithm_planning_snapshot).
    return {
        "id": "patient_specific_puncture_guide",
        "object_id": "patient_specific_puncture_guide",
        "data_tree_node_id": "patient_specific_puncture_guide",
        "label": f"Puncture guide v{version}",
        "version": version,
        "status": "ready",
        "planning_id": planning_id or None,
        "planning_version": planning_version,
        "data_version": version,
        "data_type": "surgical_guide",
        "coordinate_system": "SimpleITK physical patient-world coordinates (mm)",
        "parameters": params,
        "source_plan_signature": signature,
        "selected_needle_ids": [path.needle_id for path in paths],
        "skin_surface_object_id": skin_surface["object_id"],
        "skin_surface_data_version": skin_surface["data_version"],
        "needle_paths": path_checks,
        "auxiliary_holes": auxiliary_holes,
        "vertices": vertices,
        "faces": faces,
        "validation": {
            **validation,
            "source_needle_count": len(paths),
            "auxiliary_holes": {
                key: value
                for key, value in auxiliary_holes.items()
                if key not in {"holes", "skipped"}
            },
            "max_centerline_deviation_mm": 0.0,
            "skin_fit": "Physical signed-distance skin surface with explicit clearance",
            "skin_surface_interpolation": "physical_signed_distance_linear",
            "geometry_resolution_mm": params["geometry_resolution_mm"],
            "stage_timings_seconds": stage_timings,
            "bore_quality": bore_quality,
            "component_cleanup": component_cleanup,
            "primary_sleeve_support": primary_sleeve_support,
            "needle_spacing": needle_spacing,
            # Persist the final cutter spans so a saved guide can be audited:
            # a non-empty crossing list proves the affected primary channel
            # was re-drilled through the neighbouring sleeve wall.
            "primary_bore_cutters": [
                {
                    "needle_id": str(spec["needle_id"]),
                    "radius_mm": float(spec["radius_mm"]),
                    "nominal_length_mm": float(spec["nominal_length_mm"]),
                    "cutter_length_mm": float(spec["cutter_length_mm"]),
                    "crossing_sleeves": [dict(item) for item in spec["crossing_sleeves"]],
                }
                for spec in primary_bore_specs
            ],
            "plate_connectivity": plate_connectivity,
            "finite_fov": {
                "truncated_superior": bool(trunc_z_max),
                "truncated_inferior": bool(trunc_z_min),
                "boundary_faces": {
                    key: bool(value) for key, value in boundary_faces.items()
                },
                "boundary_safety": boundary_safety,
                # The complete skin segmentation is persisted for inspection,
                # while the mesh uses only this local, boundary-safe patch.
                "geometry_source": "local_skin_patch_only",
                "complete_skin_volume_used_for_display_only": True,
                "all_entries_on_real_skin": True,
            },
        },
    }


def guide_public_payload(state: Any, *, include_mesh: bool = False) -> Dict[str, Any]:
    """Convert persisted guide arrays into a browser-safe response."""
    if not isinstance(state, Mapping):
        return {"available": False, "mesh_loaded": False, "guide": None}
    guide = dict(state)
    vertices = guide.pop("vertices", None)
    faces = guide.pop("faces", None)
    mesh_loaded = _guide_payload_present(vertices) and _guide_payload_present(faces)
    guide["available"] = True
    if include_mesh:
        guide["vertices"] = np.asarray(vertices if vertices is not None else [], dtype=np.float32).tolist()
        guide["faces"] = np.asarray(faces if faces is not None else [], dtype=np.int32).tolist()
    return {"available": True, "mesh_loaded": mesh_loaded, "guide": guide}


def mesh_to_ascii_stl(vertices: Any, faces: Any, name: str = "brachybot_puncture_guide") -> bytes:
    """Create a deterministic ASCII STL from validated world-coordinate triangles."""
    vertices_np = np.asarray(vertices, dtype=np.float64)
    faces_np = np.asarray(faces, dtype=np.int64)
    validation = mesh_validation(vertices_np, faces_np)
    if not validation.get("watertight"):
        raise SurgicalGuideError("Only a validated watertight guide can be exported as STL")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name or "guide"))
    lines = [f"solid {safe_name}"]
    for face in faces_np:
        a, b, c = vertices_np[face]
        normal = np.cross(b - a, c - a)
        norm = float(np.linalg.norm(normal))
        if norm > 1e-12:
            normal /= norm
        else:  # Should be impossible after marching cubes, but keep STL valid.
            normal[:] = 0.0
        lines.append(f"  facet normal {normal[0]:.9g} {normal[1]:.9g} {normal[2]:.9g}")
        lines.append("    outer loop")
        for vertex in (a, b, c):
            lines.append(f"      vertex {vertex[0]:.9g} {vertex[1]:.9g} {vertex[2]:.9g}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {safe_name}")
    return ("\n".join(lines) + "\n").encode("ascii")


def parse_stl(payload: bytes) -> Tuple[np.ndarray, np.ndarray]:
    """Parse the project-owned ASCII or binary STL used for round-trip QA."""
    if not isinstance(payload, (bytes, bytearray)) or len(payload) < 6:
        raise SurgicalGuideError("STL payload is empty")
    raw = bytes(payload)
    # Binary STL has an 80-byte header followed by a uint32 triangle count.
    if len(raw) >= 84:
        count = struct.unpack("<I", raw[80:84])[0]
        expected = 84 + count * 50
        if expected == len(raw):
            vertices: List[Tuple[float, float, float]] = []
            faces: List[Tuple[int, int, int]] = []
            lookup: Dict[Tuple[float, float, float], int] = {}
            offset = 84
            for _ in range(count):
                values = struct.unpack("<12fH", raw[offset:offset + 50])
                offset += 50
                face = []
                for index in range(3):
                    vertex = tuple(float(value) for value in values[3 + index * 3:6 + index * 3])
                    if vertex not in lookup:
                        lookup[vertex] = len(vertices)
                        vertices.append(vertex)
                    face.append(lookup[vertex])
                faces.append(tuple(face))
            return np.asarray(vertices, dtype=np.float32), np.asarray(faces, dtype=np.int32)
    text = raw.decode("utf-8", errors="strict")
    values = re.findall(
        r"^\s*vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*$",
        text,
        flags=re.MULTILINE,
    )
    if not values or len(values) % 3:
        raise SurgicalGuideError("STL does not contain complete triangular facets")
    vertices = []
    faces = []
    lookup: Dict[Tuple[float, float, float], int] = {}
    for index in range(0, len(values), 3):
        face = []
        for raw_vertex in values[index:index + 3]:
            vertex = tuple(float(value) for value in raw_vertex)
            if not all(math.isfinite(value) for value in vertex):
                raise SurgicalGuideError("STL contains non-finite coordinates")
            if vertex not in lookup:
                lookup[vertex] = len(vertices)
                vertices.append(vertex)
            face.append(lookup[vertex])
        faces.append(tuple(face))
    return np.asarray(vertices, dtype=np.float32), np.asarray(faces, dtype=np.int32)


def validate_exported_stl(payload: bytes) -> Dict[str, Any]:
    """Validate the exact bytes exported or re-imported for manufacturing QA."""
    vertices, faces = parse_stl(payload)
    return mesh_validation(vertices, faces)


def stl_stream(state: Mapping[str, Any]) -> io.BytesIO:
    """Return a binary stream suitable for WorkspaceStore.write_artifact."""
    return io.BytesIO(mesh_to_ascii_stl(state.get("vertices"), state.get("faces")))
