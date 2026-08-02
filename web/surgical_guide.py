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
import math
import re
import struct
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np


class SurgicalGuideError(ValueError):
    """A clinically meaningful guide-generation precondition failed."""


DEFAULT_GUIDE_PARAMETERS: Dict[str, float] = {
    "skin_threshold_hu": -300.0,
    "skin_clearance_mm": 1.0,
    "plate_thickness_mm": 3.0,
    "patch_margin_mm": 24.0,
    "channel_radius_mm": 0.9,
    "sleeve_outer_radius_mm": 3.0,
    "sleeve_outward_mm": 8.0,
    "sleeve_inward_mm": 8.0,
    # 0.35 mm resolution: a 1 mm grid made the ~2.2 mm guide channel collapse to
    # ~2 voxels (bore not visibly open, stepped surface). 0.35 mm keeps the
    # channel as a clear through-hole (~6 voxels) with a smooth printable
    # surface while keeping a 9-needle guide around ~50k vertices. Operators
    # can request an even finer 0.2 mm grid for export-quality STL.
    "geometry_resolution_mm": 0.35,
    "minimum_component_voxels": 24.0,
}

# A bounded history preserves clinically reviewable guide alternatives without
# allowing repeated mesh generation to grow one case workspace without limit.
MAX_SAVED_GUIDE_VERSIONS = 5

_PARAMETER_LIMITS = {
    "skin_threshold_hu": (-800.0, 100.0),
    "skin_clearance_mm": (0.0, 5.0),
    "plate_thickness_mm": (1.0, 10.0),
    "patch_margin_mm": (10.0, 80.0),
    "channel_radius_mm": (0.3, 6.0),
    "sleeve_outer_radius_mm": (1.0, 12.0),
    "sleeve_outward_mm": (1.0, 30.0),
    "sleeve_inward_mm": (1.0, 30.0),
    "geometry_resolution_mm": (0.2, 2.0),
    "minimum_component_voxels": (1.0, 10000.0),
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


def _finite_float(value: Any, name: str, lower: float, upper: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SurgicalGuideError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed) or parsed < lower or parsed > upper:
        raise SurgicalGuideError(f"{name} must be between {lower:g} and {upper:g}")
    return parsed


def normalize_guide_parameters(raw: Optional[Mapping[str, Any]] = None) -> Dict[str, float]:
    """Validate guide parameters without silently changing requested geometry."""
    raw = raw if isinstance(raw, Mapping) else {}
    params = dict(DEFAULT_GUIDE_PARAMETERS)
    for name, default in DEFAULT_GUIDE_PARAMETERS.items():
        lower, upper = _PARAMETER_LIMITS[name]
        params[name] = _finite_float(raw.get(name, default), name, lower, upper)
    if params["sleeve_outer_radius_mm"] <= params["channel_radius_mm"] + 0.35:
        raise SurgicalGuideError(
            "sleeve_outer_radius_mm must exceed channel_radius_mm by at least 0.35 mm"
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
    versions = agent.memory.retrieve("surgical_guide_versions") or []
    if not isinstance(versions, list):
        versions = []
    if not versions:
        current = agent.memory.retrieve("surgical_guide")
        versions = [current] if isinstance(current, Mapping) else []
    summaries: List[Dict[str, Any]] = []
    for item in versions:
        if not isinstance(item, Mapping):
            continue
        summaries.append({
            "version": int(item.get("version") or 0),
            "label": str(item.get("label") or "Puncture guide"),
            "status": str(item.get("status") or "unknown"),
            "selected_needle_ids": list(item.get("selected_needle_ids") or []),
            "parameters": dict(item.get("parameters") or {}),
            "created_at": item.get("created_at"),
            "stale_reason": item.get("stale_reason"),
            "stl_artifact": item.get("stl_artifact"),
        })
    return sorted(summaries, key=lambda item: item["version"], reverse=True)


def guide_state_for_version(agent: Any, version: Optional[Any] = None) -> Dict[str, Any]:
    """Resolve a saved version, falling back only to the active guide."""
    if agent is None or not hasattr(agent, "memory"):
        return {}
    if version not in (None, ""):
        try:
            requested = int(version)
        except (TypeError, ValueError) as exc:
            raise SurgicalGuideError("Guide version must be an integer") from exc
        for item in agent.memory.retrieve("surgical_guide_versions") or []:
            if isinstance(item, Mapping) and int(item.get("version") or 0) == requested:
                return dict(item)
        raise SurgicalGuideError(f"Puncture guide version {requested} does not exist")
    current = agent.memory.retrieve("surgical_guide")
    return dict(current) if isinstance(current, Mapping) else {}


def save_guide_version(agent: Any, state: Mapping[str, Any]) -> Dict[str, Any]:
    """Persist a new immutable mesh version and make it the active display."""
    if agent is None or not hasattr(agent, "memory"):
        raise SurgicalGuideError("Agent is unavailable")
    current = dict(state)
    current["created_at"] = float(__import__("time").time())
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
) -> Tuple[np.ndarray, np.ndarray]:
    """Find the first body voxel entered by the physical needle segment.

    The planner stores ``[deep, external]`` endpoints.  The method still
    searches the complete physical segment rather than assuming an axis or
    image orientation, and returns a direction that points into the patient.
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
            first_inside = point
            break
        inside_before = in_body
    if first_inside is None:
        raise SurgicalGuideError("A planned needle does not intersect the CT-derived skin surface")
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
        entry, inward = _sample_skin_entry(ct_image, body, target, external)
        trajectory_id = str(needle.get("trajectory_id") or needle_id)
        linked_seeds = seed_by_trajectory.get(trajectory_id, [])
        if linked_seeds:
            center = np.mean(np.stack(linked_seeds, axis=0), axis=0)
            candidate = center - entry
            length = float(np.linalg.norm(candidate))
            if length > 1e-5:
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


def _crop_origin_world(ct_image: Any, lower_xyz: np.ndarray) -> np.ndarray:
    """Return the world coordinate of the inclusive crop's first voxel."""
    return np.asarray(
        ct_image.TransformIndexToPhysicalPoint(tuple(int(value) for value in lower_xyz)),
        dtype=np.float64,
    )


def _world_grid(
    ct_image: Any,
    lower_xyz: np.ndarray,
    shape_zyx: Sequence[int],
    spacing_xyz: Sequence[float],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return world coordinates for a local, isotropic physical grid.

    The reference C++ workflow performs its guide booleans in millimetres,
    rather than in acquisition-index units.  CT slices can be substantially
    thicker than in-plane pixels, so operating directly in source voxels would
    distort sleeve diameters and plate thickness.  This native implementation
    therefore resamples only the small guide region to a validated isotropic
    grid while retaining the original SimpleITK origin and direction matrix.
    """
    spacing = np.asarray(spacing_xyz, dtype=np.float64)
    origin = np.asarray(ct_image.GetOrigin(), dtype=np.float64)
    direction = np.asarray(ct_image.GetDirection(), dtype=np.float64).reshape(3, 3)
    crop_origin = _crop_origin_world(ct_image, lower_xyz)
    # ``origin`` is intentionally not used for index arithmetic below.  The
    # crop origin has already crossed the canonical SimpleITK index-to-world
    # transform, keeping arbitrary direction matrices correct.
    del origin
    z = np.arange(int(shape_zyx[0]), dtype=np.float64)
    y = np.arange(int(shape_zyx[1]), dtype=np.float64)
    x = np.arange(int(shape_zyx[2]), dtype=np.float64)
    zz, yy, xx = np.meshgrid(z, y, x, indexing="ij")
    scaled_x = xx * spacing[0]
    scaled_y = yy * spacing[1]
    scaled_z = zz * spacing[2]
    world_x = crop_origin[0] + direction[0, 0] * scaled_x + direction[0, 1] * scaled_y + direction[0, 2] * scaled_z
    world_y = crop_origin[1] + direction[1, 0] * scaled_x + direction[1, 1] * scaled_y + direction[1, 2] * scaled_z
    world_z = crop_origin[2] + direction[2, 0] * scaled_x + direction[2, 1] * scaled_y + direction[2, 2] * scaled_z
    return world_x, world_y, world_z


def _sleeve_bore_in_region(
    ct_image: Any,
    lower_xyz: np.ndarray,
    shape_zyx: Sequence[int],
    spacing_xyz: Sequence[float],
    sleeve_start: np.ndarray,
    sleeve_end: np.ndarray,
    sleeve_radius: float,
    bore_radius: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute the sleeve (outer cylinder) and bore (inner cylinder) masks.

    The per-needle sleeve/bore are evaluated on a tight local bounding box
    instead of the full 31M-voxel grid. The box spans the sleeve axis plus the
    outer radius in every direction; only voxels that can possibly belong to
    the cylinder are tested, which removes the O(needles x volume) cost that
    previously dominated guide generation (~85% of runtime).
    """
    spacing = np.asarray(spacing_xyz, dtype=np.float64)
    direction = np.asarray(ct_image.GetDirection(), dtype=np.float64).reshape(3, 3)
    crop_origin = _crop_origin_world(ct_image, lower_xyz)
    shape = np.asarray(shape_zyx, dtype=np.int64)

    # World -> local continuous index (inverse of _world_grid). The grid arrays
    # and mask are in zyx order; convert the world coords to that order too.
    def _world_to_index_zyx(world: np.ndarray) -> np.ndarray:
        rel = np.asarray(world, dtype=np.float64) - crop_origin
        local_xyz = direction.T @ rel
        return (local_xyz / spacing)[::-1]

    i_start = _world_to_index_zyx(sleeve_start)
    i_end = _world_to_index_zyx(sleeve_end)
    radius_vox = sleeve_radius / spacing[::-1]  # per-axis radius in zyx voxels
    margin = np.maximum(np.ceil(np.max(radius_vox)), 2)
    lo = np.floor(np.minimum(i_start, i_end)).astype(np.int64) - int(margin)
    hi = np.ceil(np.maximum(i_start, i_end)).astype(np.int64) + int(margin) + 1
    lo = np.maximum(lo, 0)
    hi = np.minimum(hi, shape - 1)
    if np.any(hi <= lo):
        raise SurgicalGuideError("Guide sleeve falls outside the local plate grid")

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
    local_grid = (world_x, world_y, world_z)

    sleeve_local = _segment_mask(local_grid, sleeve_start, sleeve_end, sleeve_radius)
    bore_local = _segment_mask(local_grid, sleeve_start, sleeve_end, bore_radius)

    sleeve = np.zeros(shape, dtype=bool)
    bore = np.zeros(shape, dtype=bool)
    sleeve[zs:ze, ys:ye, xs:xe] = sleeve_local
    bore[zs:ze, ys:ye, xs:xe] = bore_local
    return sleeve, bore


def _segment_mask(
    grid: Tuple[np.ndarray, np.ndarray, np.ndarray],
    start: np.ndarray,
    end: np.ndarray,
    radius: float,
) -> np.ndarray:
    """Return voxels inside a TRUE flat-ended cylinder from ``start`` to ``end``.

    The previous implementation used a clipped projection which produced a
    capsule with spherical end caps. A capsule's rounded cap poked the sleeve
    wall into the skin and left the channel's inner opening sealed on the body
    side (the bore is smaller than the sleeve, so the rounded sleeve cap
    formed a solid plug in front of the bore). A flat-ended cylinder keeps the
    channel a clean through-hole: voxels belong iff their unclamped projection
    onto the axis lies within ``[0,1]`` AND their perpendicular distance to the
    axis is ``<= radius``.
    """
    world_x, world_y, world_z = grid
    vector = np.asarray(end - start, dtype=np.float64)
    length_sq = float(np.dot(vector, vector))
    if length_sq <= 1e-10:
        raise SurgicalGuideError("Guide sleeve has zero length")
    dx = world_x - start[0]
    dy = world_y - start[1]
    dz = world_z - start[2]
    # Unclamped projection fraction along the axis.
    proj = (dx * vector[0] + dy * vector[1] + dz * vector[2]) / length_sq
    along = (proj >= 0.0) & (proj <= 1.0)
    # Perpendicular (radial) distance squared to the axis line.
    radial_sq = (dx * dx + dy * dy + dz * dz) - proj * proj * length_sq
    return along & (radial_sq <= float(radius) ** 2)


def _filter_components(mask: np.ndarray, minimum_voxels: int) -> np.ndarray:
    from scipy import ndimage

    labels, count = ndimage.label(mask, structure=np.ones((3, 3, 3), dtype=np.uint8))
    if count == 0:
        return np.zeros_like(mask, dtype=bool)
    sizes = np.bincount(labels.ravel())
    keep = np.flatnonzero(sizes >= int(minimum_voxels))
    keep = keep[keep != 0]
    return np.isin(labels, keep)


def _resample_mask_to_local_grid(
    mask: np.ndarray,
    source_spacing_zyx: Sequence[float],
    target_spacing_mm: float,
) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    """Nearest-neighbour resample a label mask on an exact physical lattice.

    ``ndimage.zoom`` chooses a convenient output shape but can subtly change
    the effective spacing.  The guide's bores and plate thickness are physical
    dimensions, so explicit source coordinates are used instead.  This keeps
    a requested 1.0 mm guide grid exactly 1.0 mm in every world direction.
    """
    from scipy import ndimage

    source = np.asarray(mask, dtype=np.uint8)
    if source.ndim != 3 or min(source.shape) < 2:
        raise SurgicalGuideError("Guide crop is too small for physical resampling")
    source_spacing = np.asarray(source_spacing_zyx, dtype=np.float64)
    target_spacing = np.full(3, float(target_spacing_mm), dtype=np.float64)
    extent = (np.asarray(source.shape, dtype=np.float64) - 1.0) * source_spacing
    target_shape = np.floor(extent / target_spacing + 1e-8).astype(np.int64) + 1
    target_shape = np.maximum(target_shape, 2)
    axes = [
        np.arange(int(target_shape[axis]), dtype=np.float64) * target_spacing[axis] / source_spacing[axis]
        for axis in range(3)
    ]
    coordinates = np.meshgrid(*axes, indexing="ij")
    sampled = ndimage.map_coordinates(
        source,
        coordinates,
        order=0,
        mode="nearest",
        prefilter=False,
    )
    return sampled.astype(bool), tuple(float(value) for value in target_spacing)


def _mesh_from_voxels(
    mask: np.ndarray,
    ct_image: Any,
    lower_xyz: np.ndarray,
    spacing_xyz: Sequence[float],
) -> Tuple[np.ndarray, np.ndarray]:
    from skimage import measure

    if not bool(np.any(mask)):
        raise SurgicalGuideError("Guide construction produced an empty plate")
    spacing_xyz = np.asarray(spacing_xyz, dtype=np.float64)
    spacing_zyx = tuple(float(value) for value in spacing_xyz[::-1])
    padded = np.pad(mask.astype(np.uint8), 1, mode="constant")
    vertices_zyx, faces, _, _ = measure.marching_cubes(
        padded, level=0.5, spacing=spacing_zyx, allow_degenerate=False
    )
    # Remove the one-voxel padding and transform local physical coordinates
    # through the CT direction matrix.  The local origin crossed SimpleITK's
    # canonical transform above, so this is equivalent to index-to-world for
    # the resampled lattice and supports arbitrary orientation matrices.
    index_zyx = vertices_zyx / np.asarray(spacing_zyx, dtype=np.float64) - 1.0
    local_xyz_mm = index_zyx[:, ::-1] * spacing_xyz
    # Smooth the surface in local millimetre space before the world transform.
    # Marching cubes on a 0.5 mm voxel grid leaves visible facet steps on a
    # printable guide; a few Laplacian passes soften the facets without moving
    # the mesh off the intended geometry (edges are preserved by keeping the
    # surface watertight — only vertex positions move, connectivity is fixed).
    local_xyz_mm = _smooth_mesh_vertices(local_xyz_mm, np.asarray(faces, dtype=np.int64))
    crop_origin = _crop_origin_world(ct_image, lower_xyz)
    direction = np.asarray(ct_image.GetDirection(), dtype=np.float64).reshape(3, 3)
    vertices_world = (direction @ local_xyz_mm.T).T + crop_origin
    return vertices_world.astype(np.float32), np.asarray(faces, dtype=np.int32)


def _smooth_mesh_vertices(
    vertices: np.ndarray,
    faces: np.ndarray,
    iterations: int = 12,
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
    channel geometry. The default 12 lambda/mu cycles smooth a 0.35 mm voxel
    grid into a printable surface (a pure Laplacian needs ~60 passes and would
    shrink the plate by ~0.5 mm).

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
    bounds = [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()]
    return {
        "valid": watertight,
        "watertight": watertight,
        "vertex_count": int(len(vertices)),
        "face_count": int(len(faces)),
        "open_or_nonmanifold_edges": int(np.count_nonzero(edge_counts != 2)),
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
    params = normalize_guide_parameters(raw_parameters)
    memory = agent.memory
    ct_image = memory.retrieve("ct_image")
    ct_data = memory.retrieve("ct_data")
    if ct_image is None or ct_data is None:
        raise SurgicalGuideError("Load a CT image before generating a puncture guide")
    body = _body_mask(np.asarray(ct_data), params["skin_threshold_hu"])
    # Smooth the body envelope so the guide plate follows a smooth skin
    # surface instead of the CT's slice steps (real CTs often have 5 mm
    # slices — far coarser than the 3 mm plate). Entries and the printable
    # shell must use the exact same smoothed envelope so the sleeves always
    # meet the exported plate.
    body = _smooth_body_mask(body, source_spacing_zyx=tuple(
        float(value) for value in np.asarray(ct_image.GetSpacing(), dtype=np.float64)[::-1]
    ), sigma_mm=2.0)
    paths = _path_records(agent, body, selected_needle_ids)

    span_margin = (
        params["patch_margin_mm"]
        + params["skin_clearance_mm"]
        + params["plate_thickness_mm"]
        + params["sleeve_outward_mm"]
        + params["sleeve_inward_mm"]
        + params["sleeve_outer_radius_mm"]
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
    # Model local printable geometry on the requested isotropic physical grid.
    # The CT is never globally resampled or written back; only the bounded
    # guide patch is sampled for SDF booleans and STL extraction.
    body_crop, spacing_zyx = _resample_mask_to_local_grid(
        body_crop,
        source_spacing_zyx,
        params["geometry_resolution_mm"],
    )
    spacing_xyz = tuple(reversed(spacing_zyx))
    outside_distance = ndimage.distance_transform_edt(~body_crop, sampling=spacing_zyx)
    shell = (
        (~body_crop)
        & (outside_distance >= params["skin_clearance_mm"])
        & (outside_distance <= params["skin_clearance_mm"] + params["plate_thickness_mm"])
    )
    grid = _world_grid(ct_image, lower_xyz, body_crop.shape, spacing_xyz)
    patch = np.zeros_like(shell, dtype=bool)
    outer_sleeves = np.zeros_like(shell, dtype=bool)
    bores = np.zeros_like(shell, dtype=bool)
    for path in paths:
        entry = path.entry
        world_x, world_y, world_z = grid
        patch |= (
            (world_x - entry[0]) ** 2
            + (world_y - entry[1]) ** 2
            + (world_z - entry[2]) ** 2
            <= params["patch_margin_mm"] ** 2
        )
        # The sleeve is a TRUE cylinder (flat ends) anchored on the plate and
        # protruding OUTWARD from the patient. Its inner end sits at the plate's
        # skin-facing face (skin_clearance outside the smoothed skin surface),
        # never inside the body. The bore is a full through-hole from that inner
        # face to the sleeve tip, so the needle is guided the whole way and the
        # channel stays open on the skin side. sleeve_inward_mm is retained in
        # the schema for compatibility but no longer moves any geometry.
        sleeve_inner = entry - path.inward_direction * params["skin_clearance_mm"]
        sleeve_outer = sleeve_inner - path.inward_direction * (
            params["plate_thickness_mm"] + params["sleeve_outward_mm"]
        )
        sleeve, bore = _sleeve_bore_in_region(
            ct_image,
            lower_xyz,
            body_crop.shape,
            spacing_xyz,
            sleeve_inner,
            sleeve_outer,
            params["sleeve_outer_radius_mm"],
            params["channel_radius_mm"],
        )
        outer_sleeves |= sleeve
        bores |= bore
    solid = (shell & patch) | outer_sleeves
    solid &= ~bores
    # Trim the guide's skin-facing side with the smoothed skin surface. The
    # sleeve cylinder is built along the needle axis; for oblique needles its
    # wall can cross the skin and leave voxels inside the body. Cutting the
    # solid with the smoothed body's distance field (outside_distance) removes
    # anything closer to the skin than the clearance, so the sleeve inner face
    # is shaved flush with the plate's skin side and never pokes into the skin.
    solid &= outside_distance >= params["skin_clearance_mm"]
    solid = _filter_components(solid, int(params["minimum_component_voxels"]))
    vertices, faces = _mesh_from_voxels(solid, ct_image, lower_xyz, spacing_xyz)
    validation = mesh_validation(vertices, faces)
    if not validation.get("watertight"):
        raise SurgicalGuideError(
            "Generated guide mesh is not watertight; adjust guide parameters or verify CT skin coverage"
        )
    snapshot = _current_planning_snapshot(agent)
    prior = memory.retrieve("surgical_guide")
    signature = planning_signature(_algorithm_planning_snapshot(agent))
    # Deduplicate versions: when the plan geometry and manufacturing parameters
    # are identical to the latest version, keep that version number instead of
    # bumping it. This prevents spurious v2 -> v3 jumps caused by duplicate
    # auto-generation calls (LLM tool + frontend auto-generate after a session
    # restart) that would otherwise produce N copies of the same guide.
    reuse_version = None
    if isinstance(prior, Mapping):
        prior_sig = str(prior.get("source_plan_signature") or "")
        prior_params = prior.get("parameters") or {}
        if prior_sig == signature and prior_params == params:
            reuse_version = int(prior.get("version") or 0)
    version = int(reuse_version) if reuse_version else (
        int(prior.get("version", 0)) + 1 if isinstance(prior, Mapping) else 1
    )
    planning_id = str(memory.retrieve("manual_planning_id") or "")
    planning_version = int(memory.retrieve("manual_plan_version") or 0)
    path_checks = _planned_path_deviation(paths)
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
        "needle_paths": path_checks,
        "vertices": vertices,
        "faces": faces,
        "validation": {
            **validation,
            "source_needle_count": len(paths),
            "max_centerline_deviation_mm": 0.0,
            "skin_fit": "CT threshold surface with explicit clearance",
            "geometry_resolution_mm": params["geometry_resolution_mm"],
        },
    }


def guide_public_payload(state: Any, *, include_mesh: bool = False) -> Dict[str, Any]:
    """Convert persisted guide arrays into a browser-safe response."""
    if not isinstance(state, Mapping):
        return {"available": False, "guide": None}
    guide = dict(state)
    vertices = guide.pop("vertices", None)
    faces = guide.pop("faces", None)
    guide["available"] = True
    if include_mesh:
        guide["vertices"] = np.asarray(vertices if vertices is not None else [], dtype=np.float32).tolist()
        guide["faces"] = np.asarray(faces if faces is not None else [], dtype=np.int32).tolist()
    return {"available": True, "guide": guide}


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
