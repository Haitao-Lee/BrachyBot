"""Bounded, replaceable reconstruction of observed implants in physical LPS mm.

This module neither matches a preoperative plan nor snaps detected centers. All
algorithm output starts in review state. The research profile below is an
engineering default, not a commissioned clinical tolerance or a probability.
Axes are unoriented capsule lines; their serialization sign is not insertion
direction. A deposition line is an estimate, never an observed physical needle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import time
from typing import Callable, Optional, Protocol, Sequence
from uuid import UUID, uuid4, uuid5

import numpy as np
import SimpleITK as sitk
from scipy import ndimage
from scipy.spatial import cKDTree

Vector3 = tuple[float, float, float]
CancelCheck = Optional[Callable[[], bool]]
REVIEW_STATES = frozenset(("review_needed", "accepted", "rejected"))
COVERAGE_STATES = frozenset(("unknown", "partial", "complete"))


class ReconstructionCancelled(RuntimeError):
    pass


class ReconstructionDeadlineExceeded(TimeoutError):
    pass


def check_execution(cancelled: CancelCheck = None, deadline: Optional[float] = None) -> None:
    """Use a monotonic deadline; callbacks report cancellation without mutation."""
    if cancelled is not None and cancelled():
        raise ReconstructionCancelled("Implant reconstruction cancelled")
    if deadline is not None:
        if not math.isfinite(deadline):
            raise ValueError("deadline must be a finite monotonic timestamp")
        if time.monotonic() >= deadline:
            raise ReconstructionDeadlineExceeded("Implant reconstruction deadline exceeded")


def _vector(value: Sequence[float]) -> Vector3:
    array = np.asarray(value, dtype=float)
    if array.shape != (3,) or not np.isfinite(array).all():
        raise ValueError("Expected three finite physical coordinates")
    return tuple(float(x) for x in array)


def canonical_axis(value: Sequence[float]) -> Vector3:
    axis = np.asarray(_vector(value))
    length = float(np.linalg.norm(axis))
    if length < 1e-12:
        raise ValueError("An axis cannot be zero")
    axis /= length
    if axis[int(np.argmax(np.abs(axis)))] < 0:
        axis = -axis
    return _vector(axis)


def axis_angle_deg(first: Sequence[float], second: Sequence[float]) -> float:
    return math.degrees(math.acos(float(np.clip(
        abs(np.dot(canonical_axis(first), canonical_axis(second))), 0, 1))))


def fuse_unoriented_axes(axes: Sequence[Sequence[float]], weights: Sequence[float]) -> Vector3:
    """Fuse projectors, avoiding cancellation when equivalent axes have opposite signs.

    A degenerate top eigenspace is unresolved and raises rather than inventing an
    axis. Callers must first check whether the evidence supports fusion.
    """
    if len(axes) != len(weights) or not axes:
        raise ValueError("Provide matching nonempty axes and weights")
    projector = np.zeros((3, 3))
    for axis, weight in zip(axes, weights):
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError("Axis weights must be positive and finite")
        unit = np.asarray(canonical_axis(axis))
        projector += weight * np.outer(unit, unit)
    values, vectors = np.linalg.eigh(projector)
    if values[-1] - values[-2] <= max(values[-1], 1.0) * 1e-10:
        raise ValueError("Unoriented axis fusion is ambiguous")
    return canonical_axis(vectors[:, -1])


@dataclass(frozen=True)
class ImageGeometry:
    size_xyz: tuple[int, int, int]
    spacing_xyz: Vector3
    origin_lps_mm: Vector3
    direction: tuple[float, ...]

    def __post_init__(self):
        size = tuple(self.size_xyz)
        if len(size) != 3 or any(int(x) != x or x < 1 for x in size):
            raise ValueError("Only nonempty three-dimensional image grids are supported")
        object.__setattr__(self, "size_xyz", tuple(int(x) for x in size))
        object.__setattr__(self, "spacing_xyz", _vector(self.spacing_xyz))
        object.__setattr__(self, "origin_lps_mm", _vector(self.origin_lps_mm))
        direction = tuple(float(x) for x in self.direction)
        if len(direction) != 9 or not np.isfinite(direction).all():
            raise ValueError("Image direction must contain nine finite values")
        matrix = np.asarray(direction).reshape(3, 3)
        if not np.allclose(matrix.T @ matrix, np.eye(3), atol=1e-5, rtol=0):
            raise ValueError("Image direction must be orthonormal")
        if min(self.spacing_xyz) <= 0:
            raise ValueError("Image spacing must be positive")
        object.__setattr__(self, "direction", direction)

    @classmethod
    def from_image(cls, image: sitk.Image) -> "ImageGeometry":
        if image.GetDimension() != 3 or image.GetNumberOfComponentsPerPixel() != 1:
            raise ValueError("Expected a scalar 3D image")
        return cls(image.GetSize(), image.GetSpacing(), image.GetOrigin(), image.GetDirection())

    @property
    def signature(self) -> str:
        return _signature(asdict(self))

    def points_from_xyz(self, indices: np.ndarray) -> np.ndarray:
        return np.asarray(self.origin_lps_mm) + (
            indices * np.asarray(self.spacing_xyz)) @ np.asarray(self.direction).reshape(3, 3).T

    def xyz_from_points(self, points: np.ndarray) -> np.ndarray:
        return ((points - np.asarray(self.origin_lps_mm)) @
                np.asarray(self.direction).reshape(3, 3)) / np.asarray(self.spacing_xyz)

    def agrees_with(self, image: sitk.Image) -> bool:
        other = ImageGeometry.from_image(image)
        return self.size_xyz == other.size_xyz and all(
            np.allclose(a, b, rtol=0, atol=1e-5) for a, b in (
                (self.spacing_xyz, other.spacing_xyz),
                (self.origin_lps_mm, other.origin_lps_mm), (self.direction, other.direction)))


def _signature(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class ImageReference:
    session_id: str
    timepoint_id: str
    image_id: str
    image_revision: int
    image_sha256: str
    geometry: ImageGeometry

    def __post_init__(self):
        if not all(isinstance(x, str) and x for x in (
                self.session_id, self.timepoint_id, self.image_id)):
            raise ValueError("Image ownership identities are required")
        if self.image_revision < 1 or int(self.image_revision) != self.image_revision:
            raise ValueError("Image revision must be a positive integer")
        if len(self.image_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.image_sha256):
            raise ValueError("Image SHA256 must be lowercase hexadecimal")
        if not isinstance(self.geometry, ImageGeometry):
            raise ValueError("ImageReference requires typed geometry")


@dataclass(frozen=True)
class SeedDetection:
    """Detector-local measurement; uncertainty is an uncalibrated spatial scale."""
    detection_id: str
    center_lps_mm: Vector3
    component_ids: tuple[int, ...] = ()
    center_uncertainty_mm: float = 0.25
    association_status: str = "unassociated"

    def __post_init__(self):
        if not isinstance(self.detection_id, str) or not self.detection_id:
            raise ValueError("Detector-local identity is required")
        object.__setattr__(self, "center_lps_mm", _vector(self.center_lps_mm))
        ids = tuple(self.component_ids)
        if any(int(i) != i or i <= 0 for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("Component identities must be unique positive integers")
        object.__setattr__(self, "component_ids", tuple(int(i) for i in ids))
        if not math.isfinite(self.center_uncertainty_mm) or self.center_uncertainty_mm < 0:
            raise ValueError("Center uncertainty must be finite and nonnegative")
        if self.association_status not in ("associated", "ambiguous", "unassociated"):
            raise ValueError("Invalid component association status")
        if self.association_status == "associated" and not ids:
            raise ValueError("Associated detections require component identities")


@dataclass(frozen=True)
class OrientationProfile:
    """Recorded research thresholds and strict resource limits, not clinical claims."""
    profile_id: str = "physical-pca-multiline-research-v1"
    roi_radius_mm: float = 4.0
    min_core_hu: float = 800.0
    min_contrast_hu: float = 300.0
    background_quantile: float = 0.5
    weight_clip_hu: float = 3000.0
    min_support_voxels: int = 4
    min_local_extent_mm: float = 1.5
    max_local_extent_mm: float = 8.0
    min_eigenvalue_ratio: float = 4.0
    max_resolution_angle_deg: float = 25.0
    support_center_limit_mm: float = 2.0
    partition_margin_mm: float = 0.2
    line_inlier_mm: float = 0.65
    line_max_rms_mm: float = 0.2
    center_uncertainty_scale: float = 1.0
    max_center_uncertainty_mm: float = 1.0
    min_line_extent_mm: float = 4.0
    min_pair_distance_mm: float = 2.0
    max_neighbor_distance_mm: float = 35.0
    merge_line_distance_mm: float = 0.25
    merge_line_angle_deg: float = 7.0
    local_line_angle_deg: float = 25.0
    competing_support_fraction: float = 0.8
    line_prior_weight: float = 0.25
    max_detections: int = 1024
    max_roi_voxels: int = 200_000
    max_support_voxels: int = 4096
    max_local_competitors: int = 32
    neighbor_count: int = 12
    max_hypotheses: int = 1024
    max_lines: int = 32
    max_image_voxels: int = 256_000_000

    def __post_init__(self):
        if not self.profile_id:
            raise ValueError("Profile identity is required")
        for name, value in asdict(self).items():
            if name == "profile_id":
                continue
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Profile parameter {name} must be positive and finite")
            if name.startswith("max_") and ("voxels" in name or name in (
                    "max_detections", "max_hypotheses", "max_lines", "max_local_competitors")) and int(value) != value:
                raise ValueError(f"Resource bound {name} must be integral")
        if not 0 < self.background_quantile < 1 or not 0 < self.competing_support_fraction <= 1:
            raise ValueError("Profile fractions must lie in their supported ranges")
        if self.max_support_voxels < self.min_support_voxels or self.min_support_voxels < 3:
            raise ValueError("Invalid local support bounds")
        if int(self.neighbor_count) != self.neighbor_count or self.neighbor_count < 2:
            raise ValueError("neighbor_count must be an integer >= 2")
        if int(self.min_support_voxels) != self.min_support_voxels:
            raise ValueError("min_support_voxels must be integral")
        if self.min_local_extent_mm > self.max_local_extent_mm:
            raise ValueError("Invalid local extent range")

    @property
    def signature(self) -> str:
        return _signature(asdict(self))


@dataclass(frozen=True)
class AxisDiagnostics:
    support_voxels: int = 0
    eigenvalues_mm2: Vector3 = (0.0, 0.0, 0.0)
    eigenvalue_ratio: float = 0.0
    extent_mm: float = 0.0
    rms_perpendicular_mm: float = 0.0
    resolution_angle_deg: Optional[float] = None
    threshold_hu: Optional[float] = None
    identifiable: bool = False
    flags: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "eigenvalues_mm2", _vector(self.eigenvalues_mm2))
        object.__setattr__(self, "flags", tuple(self.flags))
        if self.support_voxels < 0 or int(self.support_voxels) != self.support_voxels:
            raise ValueError("Invalid support count")
        for value in (self.eigenvalue_ratio, self.extent_mm, self.rms_perpendicular_mm,
                      self.resolution_angle_deg, self.threshold_hu):
            if value is not None and not math.isfinite(value):
                raise ValueError("Nonfinite axis diagnostics")


@dataclass(frozen=True)
class DepositionLine:
    line_id: str
    anchor_lps_mm: Vector3
    axis_lps: Vector3
    detection_ids: tuple[str, ...]
    extent_mm: float
    rms_perpendicular_mm: float
    independently_supported_axes: int
    flags: tuple[str, ...] = ()
    role: str = "estimated_deposition_line"
    actual_needle: bool = False
    line_style: str = "dashed"

    def __post_init__(self):
        object.__setattr__(self, "anchor_lps_mm", _vector(self.anchor_lps_mm))
        object.__setattr__(self, "axis_lps", canonical_axis(self.axis_lps))
        object.__setattr__(self, "detection_ids", tuple(self.detection_ids))
        object.__setattr__(self, "flags", tuple(self.flags))
        if self.actual_needle or self.role != "estimated_deposition_line":
            raise ValueError("A deposition prior cannot represent an observed needle")
        if (len(set(self.detection_ids)) != len(self.detection_ids) or len(self.detection_ids) < 2 or
                not math.isfinite(self.extent_mm) or self.extent_mm <= 0 or
                not math.isfinite(self.rms_perpendicular_mm) or self.rms_perpendicular_mm < 0):
            raise ValueError("Invalid deposition line diagnostics")


@dataclass(frozen=True)
class SeedDimensions:
    source_model_id: str
    capsule_length_mm: float
    capsule_diameter_mm: float

    def __post_init__(self):
        if not self.source_model_id or not all(math.isfinite(x) and x > 0 for x in (
                self.capsule_length_mm, self.capsule_diameter_mm)):
            raise ValueError("Seed dimensions require an explicit source model and positive measurements")


@dataclass(frozen=True)
class RolePresentation:
    role: str
    color: str
    label: str
    glyph: str
    halo_style: str
    geometry_locked: bool = True
    visible: bool = True
    opacity: float = 1.0


def seed_presentation(status: str, axis_known: bool, dimensions_known: bool = False) -> RolePresentation:
    if status not in REVIEW_STATES:
        raise ValueError("Invalid observation review state")
    return RolePresentation(
        role="implanted", color={"accepted": "#22D3EE", "review_needed": "#C084FC",
                                  "rejected": "#64748B"}[status],
        label={"accepted": "Implanted", "review_needed": "Review needed",
               "rejected": "Rejected detection"}[status],
        glyph="capsule" if axis_known and dimensions_known else "point_halo",
        halo_style="dashed" if status == "review_needed" else "solid",
        visible=status != "rejected")


ADDITIONAL_SEED_PRESENTATION = RolePresentation(
    "planned", "#FBBF24", "Planned", "capsule", "solid", geometry_locked=False)


@dataclass(frozen=True)
class SeedObservation:
    observation_id: str
    detection_id: str
    center_lps_mm: Vector3
    axis_lps: Optional[Vector3]
    axis_source: str
    local_diagnostics: AxisDiagnostics
    component_ids: tuple[int, ...]
    candidate_line_ids: tuple[str, ...]
    diagnostics: tuple[str, ...]
    presentation: RolePresentation
    dimensions: Optional[SeedDimensions] = None
    physical_seed_id: Optional[str] = None
    review_status: str = "review_needed"
    reviewer_id: Optional[str] = None
    review_evidence: Optional[str] = None
    local_line_disagreement_deg: Optional[float] = None
    axis_semantics: str = "unoriented"
    center_uncertainty_mm: Optional[float] = None
    component_association_status: str = "unassociated"

    def __post_init__(self):
        UUID(self.observation_id)
        object.__setattr__(self, "center_lps_mm", _vector(self.center_lps_mm))
        if self.axis_lps is not None:
            object.__setattr__(self, "axis_lps", canonical_axis(self.axis_lps))
        for key in ("component_ids", "candidate_line_ids", "diagnostics"):
            object.__setattr__(self, key, tuple(getattr(self, key)))
        if self.review_status not in REVIEW_STATES or self.axis_semantics != "unoriented":
            raise ValueError("Invalid observation semantics")
        if self.axis_source not in ("unknown", "local_pca", "local_pca_with_line_prior",
                                    "estimated_from_deposition_line", "provider_estimate", "reviewed_axis"):
            raise ValueError("Unknown axis evidence source")
        if not isinstance(self.local_diagnostics, AxisDiagnostics) or not isinstance(self.presentation, RolePresentation):
            raise ValueError("Observation diagnostics and presentation must be typed")
        if self.dimensions is not None and not isinstance(self.dimensions, SeedDimensions):
            raise ValueError("Seed dimensions must be typed")
        if (self.axis_lps is None) != (self.axis_source == "unknown"):
            raise ValueError("Unknown axes require an explicit unknown source")
        if self.review_status != "review_needed" and not (self.reviewer_id and self.review_evidence):
            raise ValueError("Review decisions require reviewer identity and evidence")
        if self.center_uncertainty_mm is not None and (
                not math.isfinite(self.center_uncertainty_mm) or self.center_uncertainty_mm < 0):
            raise ValueError("Center uncertainty must be nonnegative, finite or explicitly unknown")
        if self.component_association_status not in ("associated", "ambiguous", "unassociated"):
            raise ValueError("Invalid component association state")
        if self.component_association_status == "associated" and not self.component_ids:
            raise ValueError("Associated observations require component identities")


@dataclass(frozen=True)
class SeedAxisReconstruction:
    observation_set_id: str
    revision_id: str
    revision: int
    image_ref: ImageReference
    observations: tuple[SeedObservation, ...]
    deposition_lines: tuple[DepositionLine, ...]
    profile: OrientationProfile
    provider_id: str
    provider_version: str
    coverage_status: str = "unknown"
    diagnostics: tuple[str, ...] = ()
    parent_revision_id: Optional[str] = None
    set_reviewer_id: Optional[str] = None
    set_review_evidence: Optional[str] = None
    coordinate_system: str = "LPS"
    coordinate_unit: str = "mm"
    detector_provenance: tuple[tuple[str, str], ...] = ()
    schema_version: int = 1

    def __post_init__(self):
        UUID(self.observation_set_id)
        UUID(self.revision_id)
        if self.parent_revision_id is not None:
            UUID(self.parent_revision_id)
        for key in ("observations", "deposition_lines", "diagnostics"):
            object.__setattr__(self, key, tuple(getattr(self, key)))
        object.__setattr__(self, "detector_provenance", tuple(tuple(x) for x in self.detector_provenance))
        if self.revision < 1 or int(self.revision) != self.revision:
            raise ValueError("Observation revision must be positive")
        if self.schema_version != 1 or (self.revision == 1) != (self.parent_revision_id is None):
            raise ValueError("Unsupported observation schema or invalid revision lineage")
        if self.coverage_status not in COVERAGE_STATES:
            raise ValueError("Unknown coverage status")
        if self.coordinate_system != "LPS" or self.coordinate_unit != "mm":
            raise ValueError("Reconstruction records use physical LPS mm")
        if len({s.detection_id for s in self.observations}) != len(self.observations):
            raise ValueError("Detector-local identities must be unique within this revision")
        if not self.provider_id or not self.provider_version:
            raise ValueError("Provider provenance is required")
        if not isinstance(self.image_ref, ImageReference) or not isinstance(self.profile, OrientationProfile):
            raise ValueError("Revision image and profile must be typed")
        if any(not isinstance(s, SeedObservation) for s in self.observations) or any(
                not isinstance(line, DepositionLine) for line in self.deposition_lines):
            raise ValueError("Revision observations and lines must be typed")
        known = {s.detection_id for s in self.observations}
        line_ids = {line.line_id for line in self.deposition_lines}
        if len(line_ids) != len(self.deposition_lines) or any(
                not set(line.detection_ids) <= known for line in self.deposition_lines) or any(
                not set(s.candidate_line_ids) <= line_ids for s in self.observations):
            raise ValueError("Deposition line references must resolve within the immutable revision")

    @property
    def review_status(self) -> str:
        if (self.coverage_status != "complete" or not self.set_reviewer_id or
                not self.set_review_evidence or any(
                    s.review_status == "review_needed" for s in self.observations)):
            return "review_needed"
        return "accepted"

    @property
    def dose_input_ready(self) -> bool:
        """Geometry gate only; dose source, temporal basis and commissioning are separate."""
        return self.review_status == "accepted" and all(
            s.axis_lps is not None and s.dimensions is not None and
            np.all(self.image_ref.geometry.xyz_from_points(np.asarray(s.center_lps_mm)) >= -0.5) and
            np.all(self.image_ref.geometry.xyz_from_points(np.asarray(s.center_lps_mm)) <=
                   np.asarray(self.image_ref.geometry.size_xyz) - 0.5)
            for s in self.observations if s.review_status == "accepted")

    def to_dict(self) -> dict:
        data = asdict(self)
        data.update(review_status=self.review_status, dose_input_ready=bool(self.dose_input_ready),
                    profile_sha256=self.profile.signature)
        return data

    @classmethod
    def from_dict(cls, value: dict) -> "SeedAxisReconstruction":
        data = dict(value)
        recorded_status = data.pop("review_status", None)
        recorded_ready = data.pop("dose_input_ready", None)
        recorded_profile = data.pop("profile_sha256", None)
        image = dict(data["image_ref"])
        image["geometry"] = ImageGeometry(**image["geometry"])
        data["image_ref"] = ImageReference(**image)
        data["profile"] = OrientationProfile(**data["profile"])
        observations = []
        for item in data["observations"]:
            item = dict(item)
            item["local_diagnostics"] = AxisDiagnostics(**item["local_diagnostics"])
            item["presentation"] = RolePresentation(**item["presentation"])
            if item.get("dimensions") is not None:
                item["dimensions"] = SeedDimensions(**item["dimensions"])
            observations.append(SeedObservation(**item))
        data["observations"] = tuple(observations)
        data["deposition_lines"] = tuple(DepositionLine(**x) for x in data["deposition_lines"])
        result = cls(**data)
        if ((recorded_status is not None and recorded_status != result.review_status) or
                (recorded_ready is not None and recorded_ready != result.dose_input_ready) or
                (recorded_profile is not None and recorded_profile != result.profile.signature)):
            raise ValueError("Serialized revision status/profile disagrees with its immutable evidence")
        return result


@dataclass(frozen=True)
class ObservationReview:
    detection_id: str
    status: str
    evidence: str
    corrected_center_lps_mm: Optional[Vector3] = None
    corrected_axis_lps: Optional[Vector3] = None
    clear_axis: bool = False
    corrected_center_uncertainty_mm: Optional[float] = None
    corrected_dimensions: Optional[SeedDimensions] = None

    def __post_init__(self):
        if self.status not in REVIEW_STATES or not self.evidence:
            raise ValueError("A review decision requires explicit status and evidence")
        if self.corrected_center_lps_mm is not None:
            object.__setattr__(self, "corrected_center_lps_mm", _vector(self.corrected_center_lps_mm))
        if self.corrected_axis_lps is not None:
            object.__setattr__(self, "corrected_axis_lps", canonical_axis(self.corrected_axis_lps))
        if self.corrected_dimensions is not None and not isinstance(self.corrected_dimensions, SeedDimensions):
            raise ValueError("Corrected source dimensions require the typed confirmed source model")
        if self.clear_axis and self.corrected_axis_lps is not None:
            raise ValueError("Cannot both clear and replace an axis")
        if self.corrected_center_uncertainty_mm is not None and (
                self.corrected_center_lps_mm is None or not math.isfinite(self.corrected_center_uncertainty_mm)
                or self.corrected_center_uncertainty_mm < 0):
            raise ValueError("Corrected center uncertainty requires an explicit center correction and finite scale")


def review_observations(previous: SeedAxisReconstruction, decisions: Sequence[ObservationReview], *,
                        reviewer_id: str, coverage_status: Optional[str] = None,
                        set_review_evidence: Optional[str] = None) -> SeedAxisReconstruction:
    """Create a new immutable revision. The owner must publish it with a revision CAS.

    Center/axis corrections invalidate deposition priors; unreviewed axes using those
    priors are cleared rather than carried forward as current measurements.
    """
    if not reviewer_id:
        raise ValueError("Reviewer identity is required")
    decision_map = {x.detection_id: x for x in decisions}
    known = {x.detection_id for x in previous.observations}
    if len(decision_map) != len(decisions) or not decision_map.keys() <= known:
        raise ValueError("Review decisions must name unique existing detections")
    centers_changed = any(x.corrected_center_lps_mm is not None for x in decisions)
    exclusion_changed = any(observation.detection_id in decision_map and
                            (observation.review_status == "rejected") !=
                            (decision_map[observation.detection_id].status == "rejected")
                            for observation in previous.observations)
    priors_changed = (centers_changed or exclusion_changed or
                      any(x.corrected_axis_lps is not None or x.clear_axis for x in decisions))
    observations = []
    for observation in previous.observations:
        decision = decision_map.get(observation.detection_id)
        updated = observation
        if priors_changed:
            changes = dict(candidate_line_ids=(), local_line_disagreement_deg=None,
                           diagnostics=observation.diagnostics + ("deposition_priors_invalidated",))
            if observation.axis_source in ("estimated_from_deposition_line", "local_pca_with_line_prior"):
                changes.update(axis_lps=None, axis_source="unknown", review_status="review_needed",
                               reviewer_id=None, review_evidence=None)
            updated = replace(updated, **changes)
        if decision is not None:
            if decision.corrected_dimensions is not None:
                updated = replace(updated, dimensions=decision.corrected_dimensions)
            if decision.corrected_center_lps_mm is not None:
                updated = replace(updated, center_lps_mm=decision.corrected_center_lps_mm,
                                  local_diagnostics=AxisDiagnostics(flags=("center_corrected_reestimate_required",)),
                                  axis_lps=None, axis_source="unknown", component_ids=(),
                                  component_association_status="unassociated",
                                  center_uncertainty_mm=decision.corrected_center_uncertainty_mm)
            if decision.corrected_axis_lps is not None or decision.clear_axis:
                updated = replace(updated, axis_lps=decision.corrected_axis_lps,
                                  axis_source="reviewed_axis" if decision.corrected_axis_lps else "unknown")
            updated = replace(updated, review_status=decision.status, reviewer_id=reviewer_id,
                              review_evidence=decision.evidence)
        updated = replace(updated, presentation=seed_presentation(
            updated.review_status, updated.axis_lps is not None, updated.dimensions is not None))
        observations.append(updated)
    return replace(previous, revision_id=str(uuid4()), revision=previous.revision + 1,
                   parent_revision_id=previous.revision_id, observations=tuple(observations),
                   deposition_lines=() if priors_changed else previous.deposition_lines,
                   coverage_status=coverage_status or previous.coverage_status,
                   set_reviewer_id=reviewer_id if set_review_evidence else None,
                   set_review_evidence=set_review_evidence)


def reconstruct_original_grid_mask(native_mask: sitk.Image, original_ct: sitk.Image, *,
                                   max_voxels: int = 256_000_000) -> sitk.Image:
    """Nearest-neighbor physical-space pull onto the exact original image grid.

    Binary values and component IDs are preserved. No center-generated spheres,
    label extrapolation or RAS/LPS conversion are added.
    """
    native = ImageGeometry.from_image(native_mask)
    original = ImageGeometry.from_image(original_ct)
    if math.prod(original.size_xyz) > max_voxels or math.prod(native.size_xyz) > max_voxels:
        raise ValueError("Mask reconstruction exceeds the image voxel limit")
    array = sitk.GetArrayViewFromImage(native_mask)
    if not np.isfinite(array).all() or np.any(array < 0) or np.any(array != np.floor(array)):
        raise ValueError("Masks must contain finite nonnegative integer labels")
    if native.agrees_with(original_ct):
        result = sitk.Image(native_mask)
        result.CopyInformation(original_ct)
        return result
    return sitk.Resample(native_mask, original_ct, sitk.Transform(3, sitk.sitkIdentity),
                         sitk.sitkNearestNeighbor, 0, native_mask.GetPixelID())


class SeedOrientationProvider(Protocol):
    """Replacement boundary; providers must preserve centers, frame and review state."""
    provider_id: str
    provider_version: str

    def estimate_seed_axes(self, image_ref: ImageReference, original_ct: sitk.Image,
                           detections: Sequence[SeedDetection], native_labels: Optional[sitk.Image] = None,
                           *, profile: OrientationProfile = OrientationProfile(),
                           dimensions: Optional[SeedDimensions] = None,
                           coverage_status: str = "unknown", cancelled: CancelCheck = None,
                           deadline: Optional[float] = None) -> SeedAxisReconstruction: ...


def _weighted_pca(points: np.ndarray, weights: np.ndarray):
    weights = weights / weights.sum()
    anchor = weights @ points
    centered = points - anchor
    covariance = (centered * weights[:, None]).T @ centered
    values, vectors = np.linalg.eigh(covariance)
    values = np.maximum(values[::-1], 0)
    axis = np.asarray(canonical_axis(vectors[:, -1]))
    projection = centered @ axis
    perpendicular = centered - projection[:, None] * axis
    rms = float(np.sqrt(weights @ np.sum(perpendicular ** 2, axis=1)))
    return anchor, axis, values, float(np.ptp(projection)), rms


def _sample_labels(points: np.ndarray, image: sitk.Image, geometry: ImageGeometry) -> np.ndarray:
    xyz = np.floor(geometry.xyz_from_points(points) + 0.5).astype(np.int64)
    valid = np.all((xyz >= 0) & (xyz < np.asarray(geometry.size_xyz)), axis=1)
    result = np.zeros(len(points), dtype=np.int64)
    array = sitk.GetArrayViewFromImage(image)
    result[valid] = array[tuple(xyz[valid, ::-1].T)]
    return result


def _local_axis(image: sitk.Image, geometry: ImageGeometry, detection: SeedDetection,
                all_detections: Sequence[SeedDetection], labels: Optional[sitk.Image],
                label_geometry: Optional[ImageGeometry], profile: OrientationProfile):
    center = np.asarray(detection.center_lps_mm)
    xyz = geometry.xyz_from_points(center)
    size = np.asarray(geometry.size_xyz)
    if np.any(xyz < -0.5) or np.any(xyz > size - 0.5):
        return None, AxisDiagnostics(flags=("center_outside_original_grid",))
    radius = profile.roi_radius_mm / np.asarray(geometry.spacing_xyz)
    low = np.maximum(np.floor(xyz - radius).astype(int), 0)
    high = np.minimum(np.ceil(xyz + radius).astype(int) + 1, size)
    shape = high - low
    if math.prod(int(x) for x in shape) > profile.max_roi_voxels:
        return None, AxisDiagnostics(flags=("local_roi_resource_limit",))
    flags = []
    if np.any(xyz - radius < 0) or np.any(xyz + radius > size - 1):
        flags.append("local_roi_clipped_by_fov")
    slices = tuple(slice(int(a), int(b)) for a, b in zip(low[::-1], high[::-1]))
    values = sitk.GetArrayViewFromImage(image)[slices].astype(float)
    finite = np.isfinite(values)
    if not finite.all():
        return None, AxisDiagnostics(flags=tuple(flags + ["nonfinite_local_ct"]))
    background = float(np.quantile(values, profile.background_quantile))
    threshold = max(profile.min_core_hu, background + profile.min_contrast_hu)
    support = values >= threshold
    indices_zyx = np.argwhere(support)
    points = geometry.points_from_xyz(indices_zyx[:, ::-1] + low)
    selected = np.linalg.norm(points - center, axis=1) <= profile.roi_radius_mm
    if labels is not None:
        label_values = _sample_labels(points, labels, label_geometry)
        selected &= np.isin(label_values, detection.component_ids) if detection.component_ids else label_values > 0
        if detection.association_status != "associated":
            flags.append("component_association_" + detection.association_status)
    competitors = [d for d in all_detections if d.detection_id != detection.detection_id and
                   (not detection.component_ids or set(d.component_ids) & set(detection.component_ids)) and
                   np.linalg.norm(np.asarray(d.center_lps_mm) - center) <= 2 * profile.roi_radius_mm]
    if len(competitors) > profile.max_local_competitors:
        return None, AxisDiagnostics(threshold_hu=threshold,
                                     flags=tuple(flags + ["local_competitor_resource_limit"]))
    if competitors:
        # Physical Voronoi ownership partitions shared components, including split centers.
        own_distance = np.linalg.norm(points - center, axis=1)
        for other in competitors:
            selected &= own_distance + profile.partition_margin_mm < np.linalg.norm(
                points - np.asarray(other.center_lps_mm), axis=1)
        flags.append("shared_component_partitioned")
    support[:] = False
    if len(indices_zyx):
        support[tuple(indices_zyx[selected].T)] = True
    components, count = ndimage.label(support, structure=np.ones((3, 3, 3)))
    if count:
        indices_zyx = np.argwhere(components > 0)
        points = geometry.points_from_xyz(indices_zyx[:, ::-1] + low)
        ids = components[tuple(indices_zyx.T)]
        distances = np.linalg.norm(points - center, axis=1)
        nearest = np.full(count + 1, np.inf)
        np.minimum.at(nearest, ids, distances)
        ordered = np.argsort(nearest[1:]) + 1
        if nearest[ordered[0]] > profile.support_center_limit_mm:
            flags.append("core_support_far_from_center")
            indices_zyx = indices_zyx[:0]
        elif len(ordered) > 1 and nearest[ordered[1]] - nearest[ordered[0]] < profile.partition_margin_mm:
            flags.append("competing_local_core_components")
            indices_zyx = indices_zyx[:0]
        else:
            indices_zyx = indices_zyx[ids == ordered[0]]
    else:
        indices_zyx = np.empty((0, 3), dtype=int)
    support_count = len(indices_zyx)
    if support_count < profile.min_support_voxels:
        return None, AxisDiagnostics(support_voxels=support_count, threshold_hu=threshold,
                                     flags=tuple(flags + ["insufficient_local_support"]))
    if support_count > profile.max_support_voxels:
        # Deterministic bounded sampling; retain original support count in diagnostics.
        indices_zyx = indices_zyx[np.linspace(0, support_count - 1, profile.max_support_voxels, dtype=int)]
        flags.append("local_support_subsampled")
    points = geometry.points_from_xyz(indices_zyx[:, ::-1] + low)
    weights = np.clip(values[tuple(indices_zyx.T)] - background, 1.0, profile.weight_clip_hu)
    _, axis, eigenvalues, extent, rms = _weighted_pca(points, weights)
    ratio = float(eigenvalues[0] / max(eigenvalues[1], 1e-12))
    rotation = np.asarray(geometry.direction).reshape(3, 3)
    voxel_covariance = rotation @ np.diag(np.asarray(geometry.spacing_xyz) ** 2 / 12) @ rotation.T
    transverse_resolution = math.sqrt(max(0, float(np.trace(voxel_covariance) - axis @ voxel_covariance @ axis)))
    resolution_angle = math.degrees(math.atan2(transverse_resolution, max(extent / 2, 1e-12)))
    if ratio < profile.min_eigenvalue_ratio:
        flags.append("local_axis_not_identifiable")
    if not profile.min_local_extent_mm <= extent <= profile.max_local_extent_mm:
        flags.append("local_extent_outside_profile")
    if resolution_angle > profile.max_resolution_angle_deg:
        flags.append("undersampled_original_grid")
    blocking = {"local_axis_not_identifiable", "local_extent_outside_profile", "undersampled_original_grid",
                "local_roi_clipped_by_fov", "component_association_ambiguous", "component_association_unassociated"}
    identifiable = not (set(flags) & blocking)
    diagnostics = AxisDiagnostics(support_count, _vector(eigenvalues), ratio, extent, rms,
                                  resolution_angle, threshold, identifiable, tuple(flags))
    return canonical_axis(axis) if identifiable else None, diagnostics


def _multiline(detections: Sequence[SeedDetection], local_axes: Sequence[Optional[Vector3]],
               profile: OrientationProfile, cancelled: CancelCheck, deadline: Optional[float],
               usable_centers: Sequence[bool]):
    count = len(detections)
    if count < 2:
        return (), ()
    points = np.asarray([d.center_lps_mm for d in detections])
    uncertainty = np.asarray([d.center_uncertainty_mm for d in detections])
    eligible = (uncertainty <= profile.max_center_uncertainty_mm) & np.asarray(usable_centers, dtype=bool)
    tolerance = profile.line_inlier_mm + uncertainty * profile.center_uncertainty_scale
    tree = cKDTree(points)
    distances, neighbors = tree.query(points, k=min(count, profile.neighbor_count + 1))
    pairs = set()
    for i in range(count):
        for distance, j in zip(np.atleast_1d(distances[i]), np.atleast_1d(neighbors[i])):
            if (i != j and eligible[i] and eligible[j] and
                    profile.min_pair_distance_mm <= distance <= profile.max_neighbor_distance_mm):
                pairs.add(tuple(sorted((i, int(j)))))
    pairs = sorted(pairs)
    global_flags = []
    if len(pairs) > profile.max_hypotheses:
        pairs = [pairs[x] for x in np.linspace(0, len(pairs) - 1, profile.max_hypotheses, dtype=int)]
        global_flags.append("line_hypothesis_budget_reached")
    fits = []
    mixed_support = False
    for i, j in pairs:
        check_execution(cancelled, deadline)
        axis = np.asarray(canonical_axis(points[j] - points[i]))
        anchor = points[i]
        ids = np.array([], dtype=int)
        for _ in range(3):
            displacement = points - anchor
            residuals = np.linalg.norm(displacement - (displacement @ axis)[:, None] * axis, axis=1)
            selected = np.flatnonzero((residuals <= tolerance) & eligible)
            if len(selected) < 2:
                break
            anchor, axis, _, extent, rms = _weighted_pca(
                points[selected], 1 / np.maximum(uncertainty[selected], 0.1) ** 2)
            if np.array_equal(ids, selected):
                ids = selected
                break
            ids = selected
        if len(ids) < 2:
            continue
        displacement = points[ids] - anchor
        residuals = np.linalg.norm(displacement - (displacement @ axis)[:, None] * axis, axis=1)
        if np.any(residuals > tolerance[ids]):
            continue
        local_support = sum(local_axes[k] is not None and axis_angle_deg(local_axes[k], axis) <=
                            profile.local_line_angle_deg for k in ids)
        if len(ids) < 3 and local_support < 2:
            continue
        if extent < profile.min_line_extent_mm:
            continue
        if rms > profile.line_max_rms_mm:
            mixed_support = True
            continue
        fits.append((ids, anchor, axis, extent, rms, local_support))
    fits.sort(key=lambda f: (-len(f[0]), f[4], -f[3], tuple(f[0])))
    retained = []
    for fit in fits:
        ids, anchor, axis, extent, rms, local_support = fit
        equivalent = False
        for old in retained:
            offset = anchor - old[1]
            perpendicular = np.linalg.norm(offset - np.dot(offset, old[2]) * old[2])
            overlap = len(set(ids) & set(old[0])) / min(len(ids), len(old[0]))
            if (axis_angle_deg(axis, old[2]) <= profile.merge_line_angle_deg and
                    perpendicular <= profile.merge_line_distance_mm and overlap >= 0.75):
                equivalent = True
                break
        if not equivalent:
            retained.append(fit)
        if len(retained) == profile.max_lines:
            global_flags.append("deposition_line_budget_reached")
            break
    if mixed_support:
        global_flags.append("mixed_or_parallel_support_rejected")
    lines = tuple(DepositionLine(
        "line-" + _signature([detections[k].detection_id for k in ids])[:16],
        _vector(anchor), canonical_axis(axis), tuple(detections[k].detection_id for k in ids),
        extent, rms, local_support,
        ("two_point_line_with_independent_local_support",) if len(ids) == 2 else ())
        for ids, anchor, axis, extent, rms, local_support in retained)
    return lines, tuple(global_flags)


class PhysicalPCAOrientationProvider:
    """Original-image local PCA plus bounded robust 3D multiline hypotheses.

    Complexity is O(N^2 + N * K * ROI + H * N + H * max_lines), with explicit
    caps on N, local competitors K, ROI, H and output lines. No all-pairs voxel
    cloud or unbounded RANSAC loop.
    A budget limit is visible in diagnostics and cannot imply complete grouping.
    """
    provider_id = "physical-local-pca-robust-multiline"
    provider_version = "1.0.0"

    def estimate_seed_axes(self, image_ref: ImageReference, original_ct: sitk.Image,
                           detections: Sequence[SeedDetection], native_labels: Optional[sitk.Image] = None,
                           *, profile: OrientationProfile = OrientationProfile(),
                           dimensions: Optional[SeedDimensions] = None, coverage_status: str = "unknown",
                           cancelled: CancelCheck = None, deadline: Optional[float] = None) -> SeedAxisReconstruction:
        check_execution(cancelled, deadline)
        detections = tuple(detections)
        if len(detections) > profile.max_detections:
            raise ValueError("Detection count exceeds the orientation profile limit")
        if not image_ref.geometry.agrees_with(original_ct):
            raise ValueError("Original CT does not match its captured image reference")
        if math.prod(image_ref.geometry.size_xyz) > profile.max_image_voxels:
            raise ValueError("Original CT exceeds the orientation image limit")
        if len({d.detection_id for d in detections}) != len(detections):
            raise ValueError("Detection IDs must be unique")
        if coverage_status not in COVERAGE_STATES:
            raise ValueError("Invalid coverage status")
        label_geometry = ImageGeometry.from_image(native_labels) if native_labels is not None else None
        if native_labels is not None:
            if math.prod(label_geometry.size_xyz) > profile.max_image_voxels:
                raise ValueError("Label image exceeds the orientation image limit")
            label_array = sitk.GetArrayViewFromImage(native_labels)
            if not np.isfinite(label_array).all() or np.any(label_array < 0) or np.any(label_array != np.floor(label_array)):
                raise ValueError("Native labels must be nonnegative integers")
        local = []
        for detection in detections:
            check_execution(cancelled, deadline)
            local.append(_local_axis(original_ct, image_ref.geometry, detection, detections,
                                     native_labels, label_geometry, profile))
        usable_centers = ["center_outside_original_grid" not in diag.flags and
                          detection.association_status != "ambiguous"
                          for detection, (_, diag) in zip(detections, local)]
        lines, flags = _multiline(detections, [x[0] for x in local], profile, cancelled, deadline, usable_centers)
        set_id = uuid4()
        observations = []
        budget_limited = any("budget_reached" in f for f in flags)
        for detection, (local_axis, diagnostics) in zip(detections, local):
            check_execution(cancelled, deadline)
            candidates = [line for line in lines if detection.detection_id in line.detection_ids]
            candidates.sort(key=lambda line: (-len(line.detection_ids), line.rms_perpendicular_mm,
                                              line.line_id))
            axis, source = local_axis, "local_pca" if local_axis is not None else "unknown"
            issues = list(diagnostics.flags)
            angle = None
            ambiguous = False
            if candidates:
                best = candidates[0]
                contenders = [line for line in candidates[1:] if len(line.detection_ids) >=
                              len(best.detection_ids) * profile.competing_support_fraction]
                if local_axis is not None and contenders:
                    aligned = [line for line in [best] + contenders if
                               axis_angle_deg(local_axis, line.axis_lps) <= profile.local_line_angle_deg]
                    if len(aligned) == 1:
                        best = aligned[0]
                        contenders = []
                ambiguous = bool(contenders)
                if ambiguous:
                    issues.append("competing_deposition_lines")
                elif budget_limited:
                    issues.append("deposition_prior_budget_limited")
                elif local_axis is None:
                    if not any(f in issues for f in ("center_outside_original_grid",
                                                    "component_association_ambiguous")):
                        axis, source = best.axis_lps, "estimated_from_deposition_line"
                        issues.append("axis_estimated_not_directly_observed")
                else:
                    angle = axis_angle_deg(local_axis, best.axis_lps)
                    if angle > profile.local_line_angle_deg:
                        issues.append("rotated_seed_or_association_disagreement")
                    else:
                        axis = fuse_unoriented_axes((local_axis, best.axis_lps), (1, profile.line_prior_weight))
                        source = "local_pca_with_line_prior"
            if axis is None:
                issues.append("axis_unknown")
            observations.append(SeedObservation(
                observation_id=str(uuid5(set_id, detection.detection_id)), detection_id=detection.detection_id,
                center_lps_mm=detection.center_lps_mm, axis_lps=axis, axis_source=source,
                local_diagnostics=diagnostics, component_ids=detection.component_ids,
                candidate_line_ids=tuple(x.line_id for x in candidates), diagnostics=tuple(issues),
                dimensions=dimensions, local_line_disagreement_deg=angle,
                center_uncertainty_mm=detection.center_uncertainty_mm,
                component_association_status=detection.association_status,
                presentation=seed_presentation("review_needed", axis is not None, dimensions is not None)))
        result_flags = list(flags)
        if not detections:
            result_flags.append("zero_detections_requires_coverage_review")
        if dimensions is None:
            result_flags.append("source_capsule_dimensions_unknown")
        return SeedAxisReconstruction(str(set_id), str(uuid4()), 1, image_ref, tuple(observations),
                                      lines, profile, self.provider_id, self.provider_version,
                                      coverage_status, tuple(result_flags))
