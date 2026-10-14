"""Immutable guide geometry, rigid pose candidates, and CT continuation corridors.

All points use physical LPS millimetres. Geometry checks are research software
checks, not manufacturing confirmation or clinical commissioning. Review and
mechanical thresholds must be supplied by the caller; no clinical tolerance is
inferred from a shared image frame, a source plan, or a watertight mesh.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Mapping, Sequence
import uuid

import numpy as np


class GuidePlacementError(ValueError):
    """A pose, manufactured artifact, or continuation prerequisite is invalid."""


def _array(value, shape=None, name="geometry"):
    try:
        result = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise GuidePlacementError(f"Invalid {name}") from exc
    if (shape is not None and result.shape != shape) or not np.all(np.isfinite(result)):
        raise GuidePlacementError(f"Invalid {name}")
    return result


def _unit(value):
    vector = _array(value, (3,), "direction")
    norm = float(np.linalg.norm(vector))
    if norm < 1e-10:
        raise GuidePlacementError("Direction is zero")
    return vector / norm


def _positive(value, name, allow_zero=False):
    number = float(value)
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise GuidePlacementError(f"Invalid {name}")
    return number


def _digest(value):
    def encode_array(item):
        if isinstance(item, np.ndarray):
            return item.tolist()
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(f"Unsupported provenance value: {type(item).__name__}")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False, default=encode_array).encode()).hexdigest()


def mesh_geometry_sha256(vertices, faces):
    """Hash original indexed mesh values, independently of display pose."""
    vertices = _array(vertices, name="vertices")
    faces_raw = np.asarray(faces)
    if (vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices)
            or faces_raw.ndim != 2 or faces_raw.shape[1] != 3 or not len(faces_raw)
            or not np.issubdtype(faces_raw.dtype, np.integer)):
        raise GuidePlacementError("Invalid indexed mesh")
    faces = faces_raw.astype("<i8")
    if np.any(faces < 0) or np.any(faces >= len(vertices)):
        raise GuidePlacementError("Mesh face index is out of range")
    digest = hashlib.sha256()
    for array in (vertices.astype("<f8"), faces):
        digest.update(np.asarray(array.shape, dtype="<i8").tobytes())
        digest.update(array.tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class RigidTransform:
    """A proper SE(3) point push from guide local coordinates to target LPS."""

    rotation: np.ndarray
    translation: np.ndarray

    def __post_init__(self):
        rotation = _array(self.rotation, (3, 3), "rigid rotation")
        translation = _array(self.translation, (3,), "rigid translation")
        if (not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8, rtol=0)
                or not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-8, rtol=0)):
            raise GuidePlacementError("Guide placement rejects scale, shear, and reflection")
        rotation, translation = rotation.copy(), translation.copy()
        rotation.flags.writeable = translation.flags.writeable = False
        object.__setattr__(self, "rotation", rotation)
        object.__setattr__(self, "translation", translation)

    @classmethod
    def from_matrix(cls, value):
        matrix = _array(value, (4, 4), "rigid transform")
        rotation = matrix[:3, :3]
        if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-8, rtol=0):
            raise GuidePlacementError("Transform has an invalid homogeneous row")
        if (not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8, rtol=0)
                or not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-8, rtol=0)):
            raise GuidePlacementError("Guide placement rejects scale, shear, and reflection")
        rotation = rotation.copy()
        translation = matrix[:3, 3].copy()
        rotation.flags.writeable = translation.flags.writeable = False
        return cls(rotation, translation)

    def matrix(self):
        matrix = np.eye(4)
        matrix[:3, :3] = self.rotation
        matrix[:3, 3] = self.translation
        return matrix

    def points(self, values):
        points = _array(values, name="points")
        if points.shape[-1:] != (3,):
            raise GuidePlacementError("Points must end in three coordinates")
        return points @ self.rotation.T + self.translation

    def directions(self, values):
        vectors = _array(values, name="directions")
        if vectors.shape[-1:] != (3,):
            raise GuidePlacementError("Directions must end in three coordinates")
        return vectors @ self.rotation.T


def fit_rigid_landmarks(source, target, *, max_residual_mm):
    """Fit explicitly corresponding landmarks; reject unidentifiable fits.

    Three non-collinear correspondences identify a rigid pose. A coplanar set
    cannot distinguish a reflection in its own plane; its QC records this
    limitation. Full-rank correspondences permit explicit reflection rejection.
    """
    source = _array(source, name="source landmarks")
    target = _array(target, name="target landmarks")
    limit = _positive(max_residual_mm, "landmark residual limit")
    if source.ndim != 2 or source.shape[1:] != (3,) or source.shape != target.shape or len(source) < 3:
        raise GuidePlacementError("At least three corresponding landmarks are required")
    source_center, target_center = source.mean(axis=0), target.mean(axis=0)
    a, b = source - source_center, target - target_center
    singular_a, singular_b = np.linalg.svd(a, compute_uv=False), np.linalg.svd(b, compute_uv=False)
    if min(singular_a[1], singular_b[1]) <= 1e-6 * max(singular_a[0], singular_b[0], 1.0):
        raise GuidePlacementError("Landmarks are coincident, collinear, or nearly degenerate")
    source_dist = np.linalg.norm(source[:, None] - source[None, :], axis=2)
    target_dist = np.linalg.norm(target[:, None] - target[None, :], axis=2)
    nonzero = source_dist > 1e-8
    # Explicitly exact scaled configurations are invalid even under a loose
    # residual threshold. No similarity transform is fitted or returned.
    ratios = target_dist[nonzero] / source_dist[nonzero]
    if np.ptp(ratios) < 1e-7 and abs(float(np.mean(ratios)) - 1.0) > 1e-7:
        raise GuidePlacementError("Landmark correspondences require scale")
    left, _, right = np.linalg.svd(a.T @ b)
    rotation = right.T @ left.T
    rank = int(np.linalg.matrix_rank(a, tol=singular_a[0] * 1e-6))
    if np.linalg.det(rotation) < 0:
        if rank == 3 and np.linalg.matrix_rank(b, tol=singular_b[0] * 1e-6) == 3:
            raise GuidePlacementError("Landmark correspondences require reflection")
        right[-1] *= -1
        rotation = right.T @ left.T
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = target_center - rotation @ source_center
    transform = RigidTransform.from_matrix(matrix)
    residuals = np.linalg.norm(transform.points(source) - target, axis=1)
    if float(residuals.max()) > limit:
        raise GuidePlacementError("Rigid landmark residual exceeds the explicit profile")
    return {"matrix": matrix.tolist(), "qc": {
        "landmark_count": len(source), "landmark_rank": rank,
        "reflection_observability": "full_rank" if rank == 3 else "coplanar_limited",
        "residuals_mm": residuals.tolist(), "rms_mm": float(np.sqrt(np.mean(residuals ** 2))),
        "max_residual_mm": float(residuals.max()), "residual_limit_mm": limit,
        "singular_values": singular_a.tolist(), "proper_rigid": True,
    }}


def _basis(axis):
    helper = np.eye(3)[int(np.argmin(np.abs(axis)))]
    first = _unit(np.cross(axis, helper))
    return first, np.cross(axis, first)


def _projected_clear_radius(xy):
    """Exact distance from an infinite axis to every triangle, not vertices.

    The distance is zero when a projected triangle covers the axis, including
    a tiny membrane missed by finite ray or voxel sampling.
    """
    minimum = np.full(len(xy), np.inf)
    signs = []
    for index in range(3):
        start, end = xy[:, index], xy[:, (index + 1) % 3]
        edge = end - start
        squared = np.sum(edge * edge, axis=1)
        factor = np.clip(-np.sum(start * edge, axis=1) / np.maximum(squared, 1e-30), 0, 1)
        closest = start + factor[:, None] * edge
        minimum = np.minimum(minimum, np.sum(closest * closest, axis=1))
        signs.append(start[:, 0] * end[:, 1] - start[:, 1] * end[:, 0])
    signs = np.stack(signs, axis=1)
    area = signs.sum(axis=1)
    inside = ((np.all(signs >= -1e-12, axis=1) | np.all(signs <= 1e-12, axis=1))
              & (np.abs(area) > 1e-14))
    minimum[inside] = 0
    return float(np.sqrt(minimum.min()))


def _axial_material_intervals(projected, point):
    """Intersect an axial ray with exact triangles and return material spans."""
    a = projected[:, 0, :2]
    e1 = projected[:, 1, :2] - a
    e2 = projected[:, 2, :2] - a
    determinant = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    usable = np.abs(determinant) > 1e-12
    relative = point - a
    safe = np.where(usable, determinant, 1)
    u = (relative[:, 0] * e2[:, 1] - relative[:, 1] * e2[:, 0]) / safe
    v = (e1[:, 0] * relative[:, 1] - e1[:, 1] * relative[:, 0]) / safe
    hit = usable & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
    z = projected[:, 0, 2] + u * (projected[:, 1, 2] - projected[:, 0, 2]) + v * (
        projected[:, 2, 2] - projected[:, 0, 2])
    values = np.sort(z[hit])
    if not len(values):
        return []
    values = values[np.r_[True, np.diff(values) > 1e-6]]
    if len(values) % 2:
        return None
    return [(float(values[i]), float(values[i + 1])) for i in range(0, len(values), 2)]


def _support_cylinder_crossings(projected, radius):
    """Conservative exact axial envelopes of triangle/cylinder intersections.

    Edge/circle roots and the extrema of each triangle plane on the circle
    bound every surface crossing. This catches a narrow missing-wall slit
    between circumferential support rays, without declaring sampled rays a
    complete cylindrical guidance certificate.
    """
    lower = np.full(len(projected), np.inf)
    upper = np.full(len(projected), -np.inf)
    for index in range(3):
        start, end = projected[:, index], projected[:, (index + 1) % 3]
        edge = end - start
        a = np.sum(edge[:, :2] ** 2, axis=1)
        b = 2 * np.sum(start[:, :2] * edge[:, :2], axis=1)
        c = np.sum(start[:, :2] ** 2, axis=1) - radius ** 2
        discriminant = b * b - 4 * a * c
        for sign in (-1, 1):
            factor = (-b + sign * np.sqrt(np.maximum(discriminant, 0))) / np.maximum(2 * a, 1e-30)
            hit = (a > 1e-20) & (discriminant >= -1e-12) & (factor >= 0) & (factor <= 1)
            z = start[:, 2] + factor * edge[:, 2]
            lower[hit], upper[hit] = np.minimum(lower[hit], z[hit]), np.maximum(upper[hit], z[hit])
        coincident = (a <= 1e-20) & (np.abs(c) <= 1e-10)
        lower[coincident] = np.minimum(lower[coincident], np.minimum(start[coincident, 2], end[coincident, 2]))
        upper[coincident] = np.maximum(upper[coincident], np.maximum(start[coincident, 2], end[coincident, 2]))
    start = projected[:, 0]
    e1, e2 = projected[:, 1] - start, projected[:, 2] - start
    determinant = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    usable = np.abs(determinant) > 1e-12
    safe = np.where(usable, determinant, 1)
    gradient = np.column_stack(((e1[:, 2] * e2[:, 1] - e1[:, 1] * e2[:, 2]) / safe,
                                (e1[:, 0] * e2[:, 2] - e1[:, 2] * e2[:, 0]) / safe))
    gradient_norm = np.linalg.norm(gradient, axis=1)
    for sign in (-1, 1):
        point = sign * radius * gradient / np.maximum(gradient_norm[:, None], 1e-30)
        # A horizontal triangle covering the entire circle has no edge root;
        # any circle point then supplies its constant axial value.
        point[gradient_norm <= 1e-12] = [radius, 0]
        relative = point - start[:, :2]
        u = (relative[:, 0] * e2[:, 1] - relative[:, 1] * e2[:, 0]) / safe
        v = (e1[:, 0] * relative[:, 1] - e1[:, 1] * relative[:, 0]) / safe
        hit = usable & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
        z = start[:, 2] + u * e1[:, 2] + v * e2[:, 2]
        lower[hit], upper[hit] = np.minimum(lower[hit], z[hit]), np.maximum(upper[hit], z[hit])
    return [(float(a), float(b)) for a, b in zip(lower, upper) if np.isfinite(a) and np.isfinite(b)]


def _continuous_support_span(projected, radius, outer, inner):
    """A connected support-cylinder interval with no final mesh crossing."""
    blocked = sorted((max(outer, a), min(inner, b)) for a, b in _support_cylinder_crossings(projected, radius)
                     if b > outer + 1e-8 and a < inner - 1e-8)
    gaps = []
    cursor = outer
    for a, b in blocked:
        if a > cursor + 1e-6:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < inner - 1e-6:
        gaps.append((cursor, inner))
    return gaps


def audit_bore_mesh(vertices, faces, candidate, *, minimum_wall_mm, support_samples=16):
    """Conservatively audit a full void and connected guidance on the final STL.

    Continuous triangle distance bounds the clear cylinder through the whole
    guide. Axial material rays establish material membership, and analytic
    triangle/cylinder intersections exclude unsampled wall gaps throughout the
    common guiding span. No load strength, full material-thickness certificate,
    or needle fit is inferred.
    """
    center = _array(candidate["center_local_mm"], (3,), "bore center")
    axis = _unit(candidate["axis_local"])
    radius = _positive(candidate["requested_radius_mm"], "bore radius")
    wall = _positive(minimum_wall_mm, "minimum wall")
    if support_samples < 8:
        raise GuidePlacementError("At least eight wall support rays are required")
    first, second = _basis(axis)
    triangles = np.asarray(vertices, dtype=float)[np.asarray(faces, dtype=int)] - center
    projected = np.stack((triangles @ first, triangles @ second, triangles @ axis), axis=2)
    probe_radius = radius + wall * 0.5
    # Every triangle outside this square is farther than probe_radius from
    # the axis. Discarding it preserves a conservative continuous void bound
    # and avoids repeating full-guide ray intersection arithmetic per bore.
    nearby = np.all((projected[:, :, :2].max(axis=1) >= -probe_radius)
                    & (projected[:, :, :2].min(axis=1) <= probe_radius), axis=1)
    projected = projected[nearby]
    clear = min(probe_radius, _projected_clear_radius(projected[:, :, :2])) if len(projected) else probe_radius
    # A numerical guard accounts for STL decimal quantization, not process
    # tolerance. The caller's needle profile must still fit the measured void.
    clear = max(0.0, clear - 1e-5)
    result = {"method": "final_stl_continuous_triangle_void_and_cylinder_support_v1",
              "clear_radius_mm": clear, "wall_support_samples": int(support_samples),
              "minimum_wall_policy_mm": wall, "mechanical_validation": "not_established"}
    if clear <= 0:
        return {**result, "passed": False, "reason": "blocked_axis_in_final_mesh"}
    common_outer, common_inner = -np.inf, np.inf
    for index in range(support_samples):
        angle = 2 * math.pi * (index + 0.173) / support_samples
        spans = _axial_material_intervals(projected, probe_radius * np.array([math.cos(angle), math.sin(angle)]))
        if spans is None or len(spans) != 1:
            reason = "disconnected_guidance" if spans and len(spans) > 1 else "missing_or_ambiguous_wall_support"
            return {**result, "passed": False, "reason": reason}
        common_outer = max(common_outer, spans[0][0])
        common_inner = min(common_inner, spans[0][1])
    length = common_inner - common_outer
    if length <= 1e-6:
        return {**result, "passed": False, "reason": "no_connected_guiding_span"}
    spans = _continuous_support_span(projected, probe_radius, common_outer, common_inner)
    if len(spans) != 1:
        return {**result, "passed": False,
                "reason": "disconnected_guidance" if spans else "missing_continuous_cylindrical_support"}
    common_outer, common_inner = spans[0]
    length = common_inner - common_outer
    return {**result, "passed": True, "reason": None,
            "effective_radius_mm": min(radius, clear),
            "outer_intersection_local_mm": (center + common_outer * axis).tolist(),
            "inner_intersection_local_mm": (center + common_inner * axis).tolist(),
            "guiding_length_mm": float(length),
            "connected_extent_axis_mm": [common_outer, common_inner],
            "wall_support": "continuous_boundary_free_support_cylinder_with_sampled_material_membership"}


def build_bore_manifest(vertices, faces, candidates, *, minimum_wall_mm, parameters=None, source_provenance=None):
    """Audit the deterministic exported bytes; never change their mesh."""
    from web.surgical_guide import mesh_to_ascii_stl, parse_stl

    mesh_hash = mesh_geometry_sha256(vertices, faces)
    payload = mesh_to_ascii_stl(vertices, faces)
    stl_hash = hashlib.sha256(payload).hexdigest()
    exported_vertices, exported_faces = parse_stl(payload, vertex_dtype=np.float64)
    geometry_id = _digest({"mesh_sha256": mesh_hash, "stl_sha256": stl_hash,
                           "parameters": parameters or {}})
    records = []
    ids = set()
    for candidate in candidates:
        record = deepcopy(dict(candidate))
        if not record.get("candidate_id") or record["candidate_id"] in ids:
            raise GuidePlacementError("Bore candidate IDs must be present and unique")
        ids.add(record["candidate_id"])
        bore_id = str(uuid.uuid5(uuid.NAMESPACE_URL, geometry_id + "/" + record["candidate_id"]))
        record.update({"bore_id": bore_id, "geometry_id": geometry_id,
                       "mesh_sha256": mesh_hash, "stl_sha256": stl_hash,
                       "coordinate_frame": "guide_local_lps_mm", "eligible": False})
        if record.get("skip_reason"):
            record.update({"manufacturing_outcome": "skipped", "reason": record["skip_reason"]})
        else:
            audit = audit_bore_mesh(exported_vertices, exported_faces, record, minimum_wall_mm=minimum_wall_mm)
            record["geometry_audit"] = audit
            record.update({"manufacturing_outcome": "realized" if audit["passed"] else "unverified",
                           "eligible": bool(audit["passed"]), "reason": audit["reason"]})
            if audit["passed"]:
                for field in ("effective_radius_mm", "outer_intersection_local_mm", "inner_intersection_local_mm",
                              "guiding_length_mm", "connected_extent_axis_mm"):
                    record[field] = audit[field]
                record["centerline_local_mm"] = [record["outer_intersection_local_mm"], record["inner_intersection_local_mm"]]
                record["needle_clearance_mm"] = None
                record["needle_clearance_status"] = "requires_explicit_needle_profile"
        records.append(record)
    manifest = {"schema_version": 1, "geometry_id": geometry_id, "mesh_sha256": mesh_hash,
                "stl_sha256": stl_hash, "stl_serialization": "mesh_to_ascii_stl_default_name_v1",
                "coordinate_frame": "guide_local_lps_mm",
                "guide_local_to_source_lps": np.eye(4).tolist(),
                "design_parameters": deepcopy(dict(parameters or {})),
                "design_parameters_sha256": _digest(parameters or {}),
                "source_provenance": deepcopy(dict(source_provenance or {})),
                "manufacturing_confirmation": "not_recorded", "bores": records,
                "realized_count": sum(record["eligible"] for record in records),
                "candidate_count": len(records), "minimum_wall_policy_mm": float(minimum_wall_mm)}
    manifest["manifest_sha256"] = _digest(manifest)
    return manifest


def verify_manufactured_geometry(guide, *, stl_payload=None):
    """Bind reuse to unchanged original mesh, exported STL, and audited record."""
    from web.surgical_guide import mesh_to_ascii_stl

    manifest = guide.get("bore_manifest")
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != 1:
        raise GuidePlacementError("A center-only or unaudited legacy guide is ineligible")
    if manifest.get("manifest_sha256") != _digest({key: value for key, value in manifest.items() if key != "manifest_sha256"}):
        raise GuidePlacementError("Bore manifest changed after geometry audit")
    if mesh_geometry_sha256(guide["vertices"], guide["faces"]) != manifest["mesh_sha256"]:
        raise GuidePlacementError("Original manufactured mesh changed")
    if guide.get("parameters") is not None and _digest(guide["parameters"]) != manifest["design_parameters_sha256"]:
        raise GuidePlacementError("Manufactured design parameters changed after export")
    canonical = mesh_to_ascii_stl(guide["vertices"], guide["faces"])
    if hashlib.sha256(canonical).hexdigest() != manifest["stl_sha256"]:
        raise GuidePlacementError("Manufactured STL does not match the geometry manifest")
    if stl_payload is not None and hashlib.sha256(stl_payload).hexdigest() != manifest["stl_sha256"]:
        raise GuidePlacementError("Selected manufactured STL bytes differ")
    return manifest


def create_guide_placement(guide, matrix, *, manufactured_guide_id, target_image,
                           evidence, qc=None, method="manual_rigid"):
    """Create a review-pending candidate without mutating a manufactured guide."""
    manifest = verify_manufactured_geometry(guide)
    transform = RigidTransform.from_matrix(matrix)
    if not manufactured_guide_id or not isinstance(target_image, Mapping) or not all(
            target_image.get(key) for key in ("image_id", "image_revision", "geometry_id")):
        raise GuidePlacementError("Manufactured guide and exact target image identities are required")
    if not isinstance(evidence, Mapping) or not evidence.get("source"):
        raise GuidePlacementError("Guide pose evidence provenance is required")
    placement = {"placement_id": str(uuid.uuid4()), "revision": 1,
                 "manufactured_guide_id": str(manufactured_guide_id),
                 "geometry_id": manifest["geometry_id"], "mesh_sha256": manifest["mesh_sha256"],
                 "stl_sha256": manifest["stl_sha256"], "manifest_sha256": manifest["manifest_sha256"],
                 "target_image": deepcopy(dict(target_image)), "matrix": transform.matrix().tolist(),
                 "transform_direction": "guide_local_to_target_lps_mm", "method": str(method),
                 "created_at_utc": datetime.now(timezone.utc).isoformat(),
                 "evidence": deepcopy(dict(evidence)), "qc": deepcopy(dict(qc or {})),
                 "review_state": "pending", "review": None}
    placement["candidate_sha256"] = _placement_signature(placement)
    return placement


def _placement_signature(placement):
    return _digest({key: value for key, value in placement.items()
                    if key not in {"candidate_sha256", "review_state", "review"}})


def review_guide_placement(placement, *, reviewer, decision, profile_id, evidence_reviewed,
                          manufacturing_confirmed):
    """Record consequential review; surface-fit ambiguity cannot auto-accept."""
    if placement.get("candidate_sha256") != _placement_signature(placement):
        raise GuidePlacementError("Pose candidate changed after estimation")
    RigidTransform.from_matrix(placement["matrix"])
    if not reviewer or not profile_id or decision not in {"accepted", "rejected"}:
        raise GuidePlacementError("Explicit reviewer, decision, and review profile are required")
    if decision == "accepted" and (not evidence_reviewed or not manufacturing_confirmed):
        raise GuidePlacementError("Pose evidence and manufacturing confirmation must be reviewed")
    if decision == "accepted" and placement.get("qc", {}).get("ambiguous"):
        raise GuidePlacementError("Ambiguous surface candidates require new disambiguating evidence")
    result = deepcopy(placement)
    result["review_state"] = decision
    result["review"] = {"reviewer": str(reviewer), "profile_id": str(profile_id),
                        "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
                        "evidence_reviewed": bool(evidence_reviewed),
                        "manufacturing_confirmed": bool(manufacturing_confirmed),
                        "candidate_sha256": placement["candidate_sha256"]}
    return result


def estimate_landmark_placement(guide, source, target, *, max_residual_mm, **identity):
    fit = fit_rigid_landmarks(source, target, max_residual_mm=max_residual_mm)
    return create_guide_placement(guide, fit["matrix"], qc=fit["qc"], method="corresponding_landmarks_se3_v1",
                                  evidence={"source": "corresponding_guide_landmarks",
                                            "source_landmarks_local_mm": np.asarray(source).tolist(),
                                            "target_landmarks_lps_mm": np.asarray(target).tolist()}, **identity)


def estimate_surface_placement(guide, source_surface, target_surface, *, initial_matrices,
                               max_residual_mm, ambiguity_margin_mm, iterations=20, **identity):
    """Bounded multi-start rigid ICP candidate; require direct pose review.

    Symmetric, poorly observed, or one-way subset fits remain ambiguous. This
    API takes guide-visible surfaces, not a deformable anatomy registration.
    """
    from scipy.spatial import cKDTree

    source = _array(source_surface, name="guide surface")
    target = _array(target_surface, name="observed guide surface")
    if (source.ndim != 2 or source.shape[1:] != (3,) or target.ndim != 2
            or target.shape[1:] != (3,) or min(len(source), len(target)) < 4
            or max(len(source), len(target)) > 10000 or not 1 <= iterations <= 100):
        raise GuidePlacementError("Surface fit requires bounded 3D point sets and iterations")
    limit = _positive(max_residual_mm, "surface residual limit")
    margin = _positive(ambiguity_margin_mm, "ambiguity margin", allow_zero=True)
    if not 2 <= len(initial_matrices) <= 32:
        raise GuidePlacementError("Surface ambiguity assessment requires 2 to 32 initial poses")
    tree = cKDTree(target)
    solutions = []
    for matrix in initial_matrices:
        transform = RigidTransform.from_matrix(matrix)
        for _ in range(iterations):
            moved = transform.points(source)
            _, nearest = tree.query(moved)
            try:
                fit = fit_rigid_landmarks(source, target[nearest], max_residual_mm=max(limit * 10, 1e-6))
            except GuidePlacementError:
                break
            updated = RigidTransform.from_matrix(fit["matrix"])
            delta = np.max(np.abs(updated.matrix() - transform.matrix()))
            transform = updated
            if delta < 1e-8:
                break
        moved = transform.points(source)
        distances = tree.query(moved)[0]
        reverse = cKDTree(moved).query(target)[0]
        score = float(max(np.sqrt(np.mean(distances ** 2)), np.sqrt(np.mean(reverse ** 2))))
        if not any(np.allclose(transform.matrix(), item[1], atol=1e-6, rtol=0) for item in solutions):
            solutions.append((score, transform.matrix(), float(max(distances.max(), reverse.max()))))
    solutions.sort(key=lambda item: item[0])
    best = solutions[0]
    rank = np.linalg.matrix_rank(source - source.mean(axis=0))
    ambiguous = (rank < 3 or len(solutions) < 2 or best[2] > limit
                 or solutions[1][0] - best[0] <= margin)
    qc = {"ambiguous": bool(ambiguous), "bidirectional_rms_mm": best[0],
          "max_residual_mm": best[2], "residual_limit_mm": limit,
          "distinct_pose_count": len(solutions), "ambiguity_margin_mm": margin,
          "candidates": [{"rms_mm": score, "matrix": matrix.tolist()} for score, matrix, _ in solutions],
          "direct_guide_observation_required": True}
    return create_guide_placement(guide, best[1], method="bounded_rigid_surface_icp_v1", qc=qc,
                                  evidence={"source": "guide_surface_candidate",
                                            "source_surface_sha256": _digest(source.tolist()),
                                            "target_surface_sha256": _digest(target.tolist())}, **identity)


def placed_guide_geometry(guide, placement, *, target_image):
    """Transform original vertices and eligible bores once; preserve all hashes."""
    manifest = verify_manufactured_geometry(guide)
    if (placement.get("candidate_sha256") != _placement_signature(placement)
            or placement.get("review_state") != "accepted"
            or not placement.get("review", {}).get("manufacturing_confirmed")
            or not placement.get("review", {}).get("evidence_reviewed")
            or not placement.get("review", {}).get("profile_id")
            or placement.get("review", {}).get("candidate_sha256") != placement.get("candidate_sha256")):
        raise GuidePlacementError("An unchanged accepted guide placement is required")
    for key in ("geometry_id", "mesh_sha256", "stl_sha256", "manifest_sha256"):
        if placement.get(key) != manifest[key]:
            raise GuidePlacementError("Guide pose references a different geometry revision")
    if dict(target_image) != placement["target_image"]:
        raise GuidePlacementError("Guide pose targets a different image revision or geometry")
    transform = RigidTransform.from_matrix(placement["matrix"])
    bores = []
    for original in manifest["bores"]:
        if not original.get("eligible") or original.get("manufacturing_outcome") != "realized":
            continue
        record = deepcopy(original)
        for local, world in (("center_local_mm", "center_lps_mm"),
                             ("outer_intersection_local_mm", "outer_lps_mm"),
                             ("inner_intersection_local_mm", "inner_lps_mm")):
            record[world] = transform.points(record[local]).tolist()
        record["axis_lps"] = _unit(transform.directions(record["axis_local"])).tolist()
        record["placement_id"] = placement["placement_id"]
        record["placement_revision"] = placement["revision"]
        bores.append(record)
    return {"vertices_lps_mm": transform.points(guide["vertices"]), "faces": np.asarray(guide["faces"]).copy(),
            "original_mesh_sha256": manifest["mesh_sha256"], "stl_sha256": manifest["stl_sha256"],
            "target_image": deepcopy(dict(target_image)), "bores": bores}


@dataclass(frozen=True)
class BoreValidationProfile:
    """Caller-supplied mechanical/path thresholds, with explicit provenance."""

    profile_id: str
    needle_radius_mm: float
    minimum_guiding_length_mm: float
    obstacle_clearance_mm: float
    maximum_depth_mm: float

    def __post_init__(self):
        if not self.profile_id:
            raise GuidePlacementError("A reviewed validation profile identity is required")
        for field in ("needle_radius_mm", "minimum_guiding_length_mm", "maximum_depth_mm"):
            object.__setattr__(self, field, _positive(getattr(self, field), field))
        object.__setattr__(self, "obstacle_clearance_mm", _positive(self.obstacle_clearance_mm, "obstacle clearance", allow_zero=True))

    def signature(self):
        return _digest(self.__dict__)


def validate_bore_corridor(bore, outer, tip, profile):
    """Enforce the finite realized span on both ends of any edited needle.

    The initial implementation permits the measured axis only. Bounded
    angulation needs a separate validated mechanical profile; it is not
    inferred from a short plate bore's radial clearance.
    """
    reasons = []
    if not bore.get("eligible") or bore.get("manufacturing_outcome") != "realized":
        reasons.append("bore_not_realized")
    if bore.get("guiding_length_mm", 0) < profile.minimum_guiding_length_mm:
        reasons.append("insufficient_guiding_length")
    clearance = float(bore.get("effective_radius_mm", 0)) - profile.needle_radius_mm
    if clearance <= 0:
        reasons.append("needle_does_not_fit_measured_bore")
    outer, tip = _array(outer, (3,)), _array(tip, (3,))
    inner_bore, outer_bore = _array(bore["inner_lps_mm"], (3,)), _array(bore["outer_lps_mm"], (3,))
    axis = _unit(bore["axis_lps"])
    line = tip - outer
    if np.linalg.norm(line) < 1e-8 or np.dot(line, axis) <= 0:
        reasons.append("invalid_forward_needle")
    elif not np.allclose(_unit(line), axis, atol=1e-7, rtol=0):
        reasons.append("angulation_not_validated")
    for point in (outer, tip):
        offset = point - outer_bore
        if np.linalg.norm(offset - np.dot(offset, axis) * axis) > 1e-6:
            reasons.append("lateral_translation_not_validated")
            break
    if np.dot(outer - outer_bore, axis) > 1e-6 or np.dot(tip - inner_bore, axis) <= 0:
        reasons.append("needle_does_not_traverse_finite_bore")
    return {"valid": not reasons, "reasons": reasons, "needle_clearance_mm": clearance,
            "bore_id": bore["bore_id"], "profile_id": profile.profile_id}


def _obstacle_segments(record):
    if not isinstance(record, Mapping) or "radius_mm" not in record:
        raise GuidePlacementError("Observed obstacle shape and radius must be explicit")
    radius = _positive(record["radius_mm"], "obstacle radius")
    if record.get("points_lps_mm") is not None:
        points = _array(record["points_lps_mm"], name="observed obstacle polyline")
        if points.ndim != 2 or points.shape[1:] != (3,) or len(points) < 2:
            raise GuidePlacementError("Observed needle polyline needs at least two points")
        return [(points[i], points[i + 1], radius) for i in range(len(points) - 1)]
    if "start_lps_mm" in record and "end_lps_mm" in record:
        return [(_array(record["start_lps_mm"], (3,)), _array(record["end_lps_mm"], (3,)), radius)]
    if "center_lps_mm" not in record or "length_mm" not in record:
        raise GuidePlacementError("Fixed seed center and physical dimensions must be explicit")
    center = _array(record["center_lps_mm"], (3,), "fixed seed center")
    length = _positive(record["length_mm"], "fixed seed length", allow_zero=True)
    if record.get("axis_lps") is None:
        # An axis-unknown source is enclosed by a sphere, never assumed to
        # have its source-plan direction or cloned deposition-line direction.
        return [(center, center, radius + length / 2)]
    axis = _unit(record["axis_lps"])
    return [(center - axis * length / 2, center + axis * length / 2, radius)]


def validate_fixed_obstacles(start, end, *, profile, fixed_seeds, in_situ_needles):
    """Capsule/polyline interference; explicit empty observations are allowed."""
    from web.surgical_guide import _segment_distance_mm

    if fixed_seeds is None or in_situ_needles is None:
        raise GuidePlacementError("Fixed-seed and in-situ observations must be explicitly supplied")
    start, end = _array(start, (3,)), _array(end, (3,))
    conflicts = []
    for kind, records in (("fixed_seed", fixed_seeds), ("in_situ_needle", in_situ_needles)):
        for record in records:
            if not isinstance(record, Mapping) or not record.get("id"):
                raise GuidePlacementError("Obstacle identity is required")
            for a, b, radius in _obstacle_segments(record):
                distance = _segment_distance_mm(start, end, a, b)
                surface = distance - radius - profile.needle_radius_mm
                if surface <= profile.obstacle_clearance_mm:
                    conflicts.append({"kind": kind, "id": record["id"], "surface_clearance_mm": surface})
                    break
    return {"valid": not conflicts, "conflicts": conflicts, "profile_id": profile.profile_id}


class CurrentCTGeometry:
    """Exact voxel-cell ray intervals on current CT; no source-image fallback."""

    def __init__(self, image, *, identity, body_mask, ctv_mask, oar_mask):
        from scipy import ndimage

        self.image, self.identity = image, deepcopy(dict(identity))
        if not all(self.identity.get(key) for key in ("image_id", "image_revision", "geometry_id")):
            raise GuidePlacementError("Current image identity and geometry revision are required")
        if image.GetDimension() != 3:
            raise GuidePlacementError("Current reference must be a three-dimensional CT grid")
        self.shape = tuple(reversed(image.GetSize()))
        masks = []
        for name, mask in (("body", body_mask), ("CTV", ctv_mask), ("OAR", oar_mask)):
            if mask is None or np.asarray(mask).shape != self.shape or not np.all(np.isfinite(mask)):
                raise GuidePlacementError(f"Current {name} mask must match the target CT grid")
            snapshot = np.array(mask, dtype=bool, order="C", copy=True)
            snapshot.flags.writeable = False
            masks.append(snapshot)
        self.body, self.ctv, self.oar = masks
        anatomy_digest = hashlib.sha256()
        for mask in masks:
            anatomy_digest.update(mask)
        self.anatomy_sha256 = anatomy_digest.hexdigest()
        if not np.any(self.body) or not np.any(self.ctv) or np.any(self.ctv & ~self.body):
            raise GuidePlacementError("Current body and contained CTV must be explicit and nonempty")
        self.spacing = _array(image.GetSpacing(), (3,), "CT spacing")
        self.size_xyz = np.asarray(image.GetSize(), dtype=int)
        self.origin = _array(image.GetOrigin(), (3,), "CT origin")
        self.direction = _array(image.GetDirection()).reshape(3, 3)
        if np.any(self.spacing <= 0) or not np.allclose(self.direction.T @ self.direction, np.eye(3), atol=1e-6):
            raise GuidePlacementError("Invalid current CT physical geometry")
        if self.identity["geometry_id"] != image_geometry_identity(
                image, image_id=self.identity["image_id"], image_revision=self.identity["image_revision"])["geometry_id"]:
            raise GuidePlacementError("Current CT grid differs from its declared geometry identity")
        self.oar_distance = (ndimage.distance_transform_edt(~self.oar, sampling=self.spacing[::-1])
                             if np.any(self.oar) else None)

    def ray_cells(self, start, axis):
        """Return exact forward voxel intersections, including rotated grids."""
        point = (self.direction.T @ (_array(start, (3,)) - self.origin)) / self.spacing
        delta = (self.direction.T @ _unit(axis)) / self.spacing
        size = self.size_xyz
        lower, upper = 0.0, np.inf
        for i in range(3):
            if abs(delta[i]) < 1e-12:
                if point[i] < -0.5 or point[i] > size[i] - 0.5:
                    return []
            else:
                limits = sorted(((-0.5 - point[i]) / delta[i], (size[i] - 0.5 - point[i]) / delta[i]))
                lower, upper = max(lower, limits[0]), min(upper, limits[1])
        if upper <= lower or not np.isfinite(upper):
            return []
        events = [lower, upper]
        for i in range(3):
            if abs(delta[i]) > 1e-12:
                crossings = (np.arange(size[i] + 1) - 0.5 - point[i]) / delta[i]
                events.extend(crossings[(crossings > lower) & (crossings < upper)].tolist())
        events = np.unique(np.asarray(events))
        result = []
        for a, b in zip(events[:-1], events[1:]):
            if b - a < 1e-9:
                continue
            index = np.floor(point + ((a + b) / 2) * delta + 0.5).astype(int)
            index = np.clip(index, 0, size - 1)
            result.append((float(a), float(b), tuple(index[::-1])))
        return result


def image_geometry_identity(image, *, image_id, image_revision):
    """Bind a target identity to the exact physical grid used by this API."""
    return {"image_id": str(image_id), "image_revision": str(image_revision),
            "geometry_id": _digest({"size_xyz": list(image.GetSize()),
                                     "spacing_xyz_mm": list(image.GetSpacing()),
                                     "origin_lps_mm": list(image.GetOrigin()),
                                     "direction": list(image.GetDirection())})}


def initialize_bore_trajectories(guide, placement, context, *, profile, fixed_seeds,
                                in_situ_needles, channel_states=None):
    """Construct only finite current-CTV paths from accepted realized bores.

    OAR cell inflation is conservative at voxel resolution. No clinical
    traversability, reused-channel policy, or missing observation is guessed.
    Final/refined paths must also pass ``validate_continuation_trajectory``.
    """
    geometry = placed_guide_geometry(guide, placement, target_image=context.identity)
    if fixed_seeds is None or in_situ_needles is None:
        raise GuidePlacementError("Explicit fixed seeds and observed in-situ needles are required")
    candidates, rejected = [], []
    for bore in geometry["bores"]:
        state = (channel_states or {}).get(bore["bore_id"], "available")
        if state != "available":
            rejected.append({"bore_id": bore["bore_id"], "reasons": ["channel_" + str(state)]})
            continue
        start, axis = np.asarray(bore["inner_lps_mm"]), np.asarray(bore["axis_lps"])
        cells = context.ray_cells(start, axis)
        body_indices = [i for i, (_, _, index) in enumerate(cells) if context.body[index]]
        if not body_indices:
            rejected.append({"bore_id": bore["bore_id"], "reasons": ["no_current_skin_intersection"]})
            continue
        first_body = body_indices[0]
        skin_depth, _, skin_index = cells[first_body]
        # Entering directly into a boundary body cell is missing skin/FOV
        # evidence. Traversing a real outside-body cell must precede entry.
        if first_body == 0:
            rejected.append({"bore_id": bore["bore_id"], "reasons": ["skin_entry_unobserved_or_truncated"]})
            continue
        target_intervals = []
        for a, b, index in cells[first_body:]:
            if not context.body[index] or a - skin_depth >= profile.maximum_depth_mm:
                break
            b = min(b, skin_depth + profile.maximum_depth_mm)
            if context.ctv[index] and b > a:
                if target_intervals and abs(a - target_intervals[-1][1]) < 1e-7:
                    target_intervals[-1][1] = b
                else:
                    target_intervals.append([a, b])
        if not target_intervals:
            rejected.append({"bore_id": bore["bore_id"], "reasons": ["no_reachable_current_ctv"]})
            continue
        # Try the deepest target first, then shallower intervals if an
        # immutable obstacle blocks deeper access. Every accepted tip is
        # strictly inside a current target voxel, not on its boundary.
        failures = []
        for a, b in reversed(target_intervals):
            tip_depth = b - min(1e-4, (b - a) / 4)
            candidate = {"candidate_id": str(uuid.uuid5(uuid.NAMESPACE_URL, bore["bore_id"] + "/" + placement["candidate_sha256"] + "/" + str(tip_depth))),
                         "bore_id": bore["bore_id"], "placement_id": placement["placement_id"],
                         "placement_revision": placement["revision"], "geometry_id": bore["geometry_id"],
                         "target_image": deepcopy(context.identity), "profile_id": profile.profile_id,
                         "profile_sha256": profile.signature(),
                         "anatomy_sha256": context.anatomy_sha256,
                         "obstacle_sha256": _digest({"fixed_seeds": list(fixed_seeds), "in_situ_needles": list(in_situ_needles)}),
                         "outer_lps_mm": bore["outer_lps_mm"], "tip_lps_mm": (start + tip_depth * axis).tolist(),
                         "axis_lps": axis.tolist(), "skin_entry_lps_mm": (start + skin_depth * axis).tolist(),
                         "target_intervals_from_inner_mm": deepcopy(target_intervals),
                         "depth_from_skin_mm": tip_depth - skin_depth, "mode": "manufactured_bore_axis_only"}
            check = validate_continuation_trajectory(candidate, bore, context, profile=profile,
                                                     fixed_seeds=fixed_seeds, in_situ_needles=in_situ_needles)
            if check["valid"]:
                candidate["validation"] = check
                candidates.append(candidate)
                break
            failures.extend(check["reasons"])
        else:
            rejected.append({"bore_id": bore["bore_id"], "reasons": sorted(set(failures))})
    return {"candidates": candidates, "rejected": rejected, "realized_bore_count": len(geometry["bores"]),
            "target_image": deepcopy(context.identity), "placement_id": placement["placement_id"],
            "profile_id": profile.profile_id, "freehand_fallback": False}


def validate_continuation_trajectory(candidate, bore, context, *, profile, fixed_seeds, in_situ_needles):
    """Shared initializer/refinement/repair validation against current inputs."""
    reasons = []
    for key in ("bore_id", "placement_id", "placement_revision", "geometry_id"):
        if candidate.get(key) != bore.get(key):
            reasons.append("stale_or_different_" + key)
    if candidate.get("target_image") != context.identity or candidate.get("profile_id") != profile.profile_id:
        reasons.append("stale_target_or_validation_profile")
    if candidate.get("profile_sha256") != profile.signature():
        reasons.append("stale_validation_profile_parameters")
    if candidate.get("anatomy_sha256") != context.anatomy_sha256:
        reasons.append("stale_current_anatomy")
    obstacle_signature = _digest({"fixed_seeds": list(fixed_seeds), "in_situ_needles": list(in_situ_needles)}) if fixed_seeds is not None and in_situ_needles is not None else None
    if candidate.get("obstacle_sha256") != obstacle_signature:
        reasons.append("stale_fixed_observations")
    outer, tip = candidate["outer_lps_mm"], candidate["tip_lps_mm"]
    corridor = validate_bore_corridor(bore, outer, tip, profile)
    reasons.extend(corridor["reasons"])
    obstacles = validate_fixed_obstacles(outer, tip, profile=profile, fixed_seeds=fixed_seeds,
                                         in_situ_needles=in_situ_needles)
    reasons.extend("intersects_" + conflict["kind"] for conflict in obstacles["conflicts"])
    start, axis = np.asarray(bore["inner_lps_mm"]), _unit(bore["axis_lps"])
    if not np.allclose(_unit(candidate.get("axis_lps")), axis, atol=1e-7, rtol=0):
        reasons.append("candidate_axis_differs_from_manufactured_bore")
    end_depth = float(np.dot(np.asarray(tip) - start, axis))
    cells = [(a, min(b, end_depth), index) for a, b, index in context.ray_cells(start, axis) if a < end_depth]
    body = [(a, b, index) for a, b, index in cells if context.body[index]]
    if not body or not cells or cells[-1][1] < end_depth - 1e-6:
        reasons.append("needle_outside_current_image_coverage")
    else:
        skin_depth = body[0][0]
        expected_skin = start + skin_depth * axis
        if not np.allclose(_array(candidate.get("skin_entry_lps_mm"), (3,), "skin entry"),
                           expected_skin, atol=1e-6, rtol=0):
            reasons.append("candidate_skin_entry_differs_from_current_ct")
        if not np.isclose(float(candidate.get("depth_from_skin_mm", np.nan)),
                          end_depth - skin_depth, atol=1e-6, rtol=0):
            reasons.append("candidate_insertion_depth_differs_from_geometry")
        first = next(i for i, (_, _, index) in enumerate(cells) if context.body[index])
        if first == 0:
            reasons.append("skin_entry_unobserved_or_truncated")
        if any(not context.body[index] for _, _, index in cells[first:]):
            reasons.append("needle_leaves_current_body")
        if not context.ctv[cells[-1][2]]:
            reasons.append("tip_not_in_current_ctv")
        if end_depth - skin_depth > profile.maximum_depth_mm:
            reasons.append("maximum_insertion_depth_exceeded")
        if context.oar_distance is not None:
            inflation = profile.needle_radius_mm + profile.obstacle_clearance_mm + float(np.linalg.norm(context.spacing))
            if any(context.oar_distance[index] <= inflation for _, _, index in cells):
                reasons.append("current_oar_corridor_blocked")
    return {"valid": not reasons, "reasons": sorted(set(reasons)), "bore_corridor": corridor,
            "fixed_obstacles": obstacles, "oar_method": "conservative_voxel_cell_capsule_inflation",
            "target_image": deepcopy(context.identity), "profile_id": profile.profile_id,
            "anatomy_sha256": context.anatomy_sha256, "obstacle_sha256": obstacle_signature}
