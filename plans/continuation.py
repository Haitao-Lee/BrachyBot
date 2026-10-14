"""Immutable initial conditions for supplemental planning on the complete grid.

The CNN and optimizer use normalized model dose. Gy input is converted exactly
once with an explicit calibration, independent of the prescription. Physical
collision checks use LPS millimeters and conservative capsule geometry. This
module does not certify guide placement, source calibration, or anatomy safety;
the caller must supply those accepted inputs and its normal safety validator.
"""
from dataclasses import dataclass
import hashlib
import json
import numpy as np


def array_sha256(array):
    """Hash shape and canonical float64 values, independent of array layout."""
    a = np.ascontiguousarray(array, dtype="<f8")
    return hashlib.sha256(str(a.shape).encode() + a.tobytes()).hexdigest()


def grid_signature(image):
    """Include size, spacing, origin, direction, axis order, and physical frame."""
    size = tuple(int(v) for v in image.GetSize())
    spacing = np.asarray(image.GetSpacing(), dtype=float)
    origin = np.asarray(image.GetOrigin(), dtype=float)
    direction = np.asarray(image.GetDirection(), dtype=float).reshape(3, 3)
    if (len(size) != 3 or min(size) <= 0 or spacing.shape != (3,)
            or origin.shape != (3,) or not np.isfinite(spacing).all()
            or not np.isfinite(origin).all() or not np.isfinite(direction).all()
            or np.any(spacing <= 0)
            or not np.allclose(direction.T @ direction, np.eye(3), atol=1e-6)):
        raise ValueError("Invalid physical planning grid")
    data = [size, spacing.tolist(), origin.tolist(), direction.ravel().tolist(), "zyx", "LPS_mm"]
    return hashlib.sha256(json.dumps(data, separators=(",", ":")).encode()).hexdigest()


def _immutable(array, dtype=float):
    a = np.ascontiguousarray(array, dtype=dtype)
    # Immutable bytes backing prevents setflags(write=True), including views.
    return np.frombuffer(a.tobytes(), dtype=a.dtype).reshape(a.shape)


def _point(value):
    a = np.asarray(value, dtype=float).reshape(-1)
    if a.shape != (3,) or not np.isfinite(a).all():
        raise ValueError("A finite LPS-mm three-vector is required")
    return tuple(float(v) for v in a)


def _axis(value):
    a = np.asarray(_point(value))
    norm = np.linalg.norm(a)
    if norm <= 1e-12:
        raise ValueError("An observed or explicitly accepted seed axis is required")
    return tuple(a / norm)


@dataclass(frozen=True)
class FixedSeed:
    physical_seed_id: str
    center_lps_mm: tuple
    axis_lps: tuple
    length_mm: float
    radius_mm: float

    def __post_init__(self):
        if not isinstance(self.physical_seed_id, str) or not self.physical_seed_id.strip():
            raise ValueError("Fixed seeds require a physical identity")
        object.__setattr__(self, "center_lps_mm", _point(self.center_lps_mm))
        object.__setattr__(self, "axis_lps", _axis(self.axis_lps))
        for name in ("length_mm", "radius_mm"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value <= 0:
                raise ValueError("Fixed seed dimensions must be finite and positive")
            object.__setattr__(self, name, value)

    @property
    def segment(self):
        c, half = np.asarray(self.center_lps_mm), np.asarray(self.axis_lps) * self.length_mm / 2
        return c - half, c + half


@dataclass(frozen=True)
class FixedNeedle:
    needle_id: str
    entry_lps_mm: tuple
    tip_lps_mm: tuple
    radius_mm: float

    def __post_init__(self):
        if not isinstance(self.needle_id, str) or not self.needle_id.strip():
            raise ValueError("Observed needles require an identity")
        object.__setattr__(self, "entry_lps_mm", _point(self.entry_lps_mm))
        object.__setattr__(self, "tip_lps_mm", _point(self.tip_lps_mm))
        r = float(self.radius_mm)
        if not np.isfinite(r) or r <= 0 or self.entry_lps_mm == self.tip_lps_mm:
            raise ValueError("Observed needle geometry is incomplete")
        object.__setattr__(self, "radius_mm", r)

    @property
    def segment(self):
        return np.asarray(self.entry_lps_mm), np.asarray(self.tip_lps_mm)


def trajectory_key(trajectory):
    """Freeze anchor, axis and all reachable intervals; ignore mutable caches."""
    p = _point(trajectory[0])
    d = _axis(trajectory[1])
    if len(trajectory) < 4:
        raise ValueError("Continuation candidates require target/background depth intervals")
    depths = tuple(tuple(float(v) for v in trajectory[i]) for i in (2, 3))
    if any(not np.isfinite(v) or v < 0 for ds in depths for v in ds):
        raise ValueError("Invalid candidate depth intervals")
    if sum(map(sum, depths)) <= 0:
        raise ValueError("Continuation candidate has no physical extent")
    return p, d, *depths


@dataclass(frozen=True)
class CandidatePath:
    """A frozen, caller-validated path, optionally associated with a real bore.

    Exact geometry is deliberately required: unsupported corridor angulation
    fails closed. A caller can provide several independently validated paths
    for a bore whose accepted mechanical profile permits angulation.
    """
    candidate_id: str
    geometry: tuple
    bore_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("Candidate paths require a stable identity")
        object.__setattr__(self, "geometry", trajectory_key(self.geometry))
        if self.bore_id is not None and (not isinstance(self.bore_id, str) or not self.bore_id.strip()):
            raise ValueError("A bore identity cannot be empty")

    @classmethod
    def from_trajectory(cls, candidate_id, trajectory, bore_id=None):
        return cls(candidate_id, trajectory_key(trajectory), bore_id)


def _segment_distance(a, b, c, d):
    """Minimum Euclidean distance between finite segments, including crossings."""
    u, v, w = b - a, d - c, a - c
    uu, vv = float(u @ u), float(v @ v)
    if not np.isfinite([uu, vv, float(w @ w)]).all():
        raise ValueError("Collision geometry exceeds supported numerical range")
    candidates = []
    for s in (0., 1.):
        t = np.clip(float(v @ (w + s * u)) / max(vv, 1e-30), 0., 1.)
        candidates.append(np.linalg.norm(w + s * u - t * v))
    for t in (0., 1.):
        s = np.clip(float(u @ (t * v - w)) / max(uu, 1e-30), 0., 1.)
        candidates.append(np.linalg.norm(w + s * u - t * v))
    uv = float(u @ v)
    determinant = uu * vv - uv * uv
    if determinant > 1e-12 * max(uu * vv, 1e-30):
        s, t = np.linalg.solve([[uu, -uv], [-uv, vv]], [-float(u @ w), float(v @ w)])
        if 0 <= s <= 1 and 0 <= t <= 1:
            candidates.append(np.linalg.norm(w + s * u - t * v))
    return float(min(candidates))


def voxel_world(image, point):
    return np.asarray(image.TransformContinuousIndexToPhysicalPoint(tuple(np.asarray(point, dtype=float)[::-1])))


def voxel_axis_world(image, point, axis):
    d = voxel_world(image, np.asarray(point) + np.asarray(axis)) - voxel_world(image, point)
    return np.asarray(_axis(d))


@dataclass(frozen=True, eq=False)
class ContinuationBaseline:
    dose_model: np.ndarray
    complete_target_mask: np.ndarray
    oar_masks: tuple
    fixed_seeds: tuple
    fixed_needles: tuple
    candidate_paths: tuple | None
    baseline_grid_signature: str
    baseline_dose_sha256: str
    dose_scale_gy: float
    dose_contract_id: str
    needle_radius_mm: float
    clearance_mm: float

    def __post_init__(self):
        dose = np.asarray(self.dose_model, dtype=float)
        target = np.asarray(self.complete_target_mask)
        if (dose.ndim != 3 or not dose.size or not np.isfinite(dose).all()
                or np.any(dose < 0) or target.shape != dose.shape
                or target.dtype != np.bool_ or not target.any()):
            raise ValueError("Baseline requires finite nonnegative dose and the complete boolean target")
        if array_sha256(dose) != self.baseline_dose_sha256:
            raise ValueError("Baseline dose hash mismatch")
        for name in ("baseline_grid_signature", "dose_contract_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError("Baseline requires grid and dose/source contract identities")
        for name in ("dose_scale_gy", "needle_radius_mm", "clearance_mm"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value < 0 or (name != "clearance_mm" and value == 0):
                raise ValueError("Calibration and collision dimensions must be explicit and valid")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "dose_model", _immutable(dose))
        object.__setattr__(self, "complete_target_mask", _immutable(target, bool))
        organs = []
        for name, mask in self.oar_masks:
            mask = np.asarray(mask)
            if not isinstance(name, str) or not name or mask.dtype != np.bool_ or mask.shape != dose.shape:
                raise ValueError("OAR masks require names and matching boolean grids")
            organs.append((name, _immutable(mask, bool)))
        if len({name for name, _ in organs}) != len(organs):
            raise ValueError("Duplicate OAR identities")
        object.__setattr__(self, "oar_masks", tuple(organs))
        for field, kind, identity in (("fixed_seeds", FixedSeed, "physical_seed_id"),
                                      ("fixed_needles", FixedNeedle, "needle_id")):
            items = tuple(getattr(self, field))
            if any(not isinstance(item, kind) for item in items):
                raise ValueError("Fixed geometry must use validated immutable records")
            if len({getattr(item, identity) for item in items}) != len(items):
                raise ValueError("Duplicate fixed physical identity would double count the baseline")
            object.__setattr__(self, field, items)
        if self.candidate_paths is not None:
            paths = tuple(self.candidate_paths)
            if (any(not isinstance(p, CandidatePath) for p in paths)
                    or len({p.candidate_id for p in paths}) != len(paths)
                    or len({p.geometry for p in paths}) != len(paths)):
                raise ValueError("Candidate paths require unique immutable identities and geometry")
            object.__setattr__(self, "candidate_paths", paths)

    @classmethod
    def create(cls, baseline_dose, dose_image, *, baseline_unit,
               baseline_grid_signature, baseline_dose_sha256,
               complete_target_mask, dose_scale_gy, dose_contract_id,
               needle_radius_mm, clearance_mm, fixed_seeds=(), fixed_needles=(),
               candidate_paths=None, oar_masks=()):
        if grid_signature(dose_image) != baseline_grid_signature:
            raise ValueError("Baseline grid signature mismatch")
        if array_sha256(baseline_dose) != baseline_dose_sha256:
            raise ValueError("Input baseline dose hash mismatch")
        unit = str(baseline_unit).lower()
        scale = float(dose_scale_gy)
        if not np.isfinite(scale) or scale <= 0:
            raise ValueError("Explicit positive model-to-Gy calibration is required")
        dose = np.asarray(baseline_dose, dtype=float)
        if unit == "gy":
            dose = dose / scale
        elif unit != "normalized_model":
            raise ValueError("baseline_unit must be 'Gy' or 'normalized_model'")
        obj = cls(dose, complete_target_mask, tuple(oar_masks), tuple(fixed_seeds),
                  tuple(fixed_needles), candidate_paths, baseline_grid_signature,
                  array_sha256(dose), scale, dose_contract_id, needle_radius_mm, clearance_mm)
        obj.validate_grid(dose_image)
        return obj

    def validate_grid(self, image):
        if (grid_signature(image) != self.baseline_grid_signature
                or tuple(image.GetSize()[::-1]) != self.dose_model.shape):
            raise ValueError("Continuation grid differs from its frozen baseline")
        for seed in self.fixed_seeds:
            index = np.asarray(image.TransformPhysicalPointToContinuousIndex(seed.center_lps_mm))
            if not np.isfinite(index).all() or np.any(index < 0) or np.any(index > np.asarray(image.GetSize()) - 1):
                raise ValueError("Incomplete baseline: fixed seed center is outside the current image grid")

    def validate_context(self, volume, image, target_value):
        self.validate_grid(image)
        if not np.array_equal(np.asarray(volume) == target_value, self.complete_target_mask):
            raise ValueError("Continuation requires the complete target; covered CTV cannot be dropped")
        self.assert_unchanged()

    def assert_unchanged(self):
        if array_sha256(self.dose_model) != self.baseline_dose_sha256:
            raise ValueError("Fixed baseline dose changed during planning")

    def to_record(self):
        """Sidecar-safe state; never pickle a live optimizer or a model object."""
        from dataclasses import asdict
        return {
            "schema_version": 1, "dose_model": self.dose_model,
            "complete_target_mask": self.complete_target_mask,
            "oar_masks": list(self.oar_masks),
            "fixed_seeds": [asdict(seed) for seed in self.fixed_seeds],
            "fixed_needles": [asdict(needle) for needle in self.fixed_needles],
            "candidate_paths": None if self.candidate_paths is None else [
                {"candidate_id": p.candidate_id, "geometry": p.geometry, "bore_id": p.bore_id}
                for p in self.candidate_paths],
            "baseline_grid_signature": self.baseline_grid_signature,
            "baseline_dose_sha256": self.baseline_dose_sha256,
            "dose_scale_gy": self.dose_scale_gy, "dose_contract_id": self.dose_contract_id,
            "needle_radius_mm": self.needle_radius_mm, "clearance_mm": self.clearance_mm,
        }

    @classmethod
    def from_record(cls, record):
        """Revalidate after hydration instead of trusting a serialized success flag."""
        from collections.abc import Mapping
        if not isinstance(record, Mapping) or type(record.get("schema_version")) is not int or record["schema_version"] != 1:
            raise ValueError("Unsupported continuation baseline state")
        allowed = {"schema_version", "dose_model", "complete_target_mask", "oar_masks",
                   "fixed_seeds", "fixed_needles", "candidate_paths", "baseline_grid_signature",
                   "baseline_dose_sha256", "dose_scale_gy", "dose_contract_id", "needle_radius_mm", "clearance_mm"}
        if set(record) != allowed:
            raise ValueError("Incomplete or unknown continuation state fields")
        paths = record["candidate_paths"]
        return cls(
            record["dose_model"], record["complete_target_mask"], tuple(record["oar_masks"]),
            tuple(FixedSeed(**s) for s in record["fixed_seeds"]),
            tuple(FixedNeedle(**n) for n in record["fixed_needles"]),
            None if paths is None else tuple(CandidatePath(**p) for p in paths),
            record["baseline_grid_signature"], record["baseline_dose_sha256"],
            record["dose_scale_gy"], record["dose_contract_id"], record["needle_radius_mm"], record["clearance_mm"],
        )

    def _clear(self, start, end, radius):
        for item in (*self.fixed_seeds, *self.fixed_needles):
            a, b = item.segment
            if _segment_distance(start, end, a, b) <= radius + item.radius_mm + self.clearance_mm:
                return False
        return True

    def path_allowed(self, trajectory, image):
        key = trajectory_key(trajectory)
        if self.candidate_paths is not None and key not in {p.geometry for p in self.candidate_paths}:
            return False
        point, direction, target, background = key
        direction = np.asarray(direction)
        advance = direction / np.max(np.abs(direction))
        end = np.asarray(point) + sum(target + background) * advance
        return self._clear(voxel_world(image, point), voxel_world(image, end), self.needle_radius_mm)

    def seed_allowed(self, trajectory, point, direction, image, seed_info):
        if not self.path_allowed(trajectory, image):
            return False
        p = np.asarray(_point(point))
        if np.any(p < 0) or np.any(p > np.asarray(self.dose_model.shape) - 1):
            return False
        if not self.complete_target_mask[tuple(np.rint(p).astype(int))]:
            return False
        key = trajectory_key(trajectory)
        axis = np.asarray(key[1])
        advance = axis / np.max(np.abs(axis))
        step = float((p - key[0]) @ advance / (advance @ advance))
        if (step < 0 or step > sum(key[2] + key[3])
                or np.linalg.norm(p - np.asarray(key[0]) - step * advance) > 1e-6
                or abs(float(np.asarray(_axis(direction)) @ axis)) < 1 - 1e-8):
            return False
        length, radius = float(seed_info["length"]), float(seed_info["radius"])
        if not np.isfinite(length + radius) or length <= 0 or radius <= 0:
            raise ValueError("Supplemental seed dimensions are invalid")
        c = voxel_world(image, p)
        half = voxel_axis_world(image, p, direction) * length / 2
        return self._clear(c - half, c + half, radius)


def validate_continuation(continuation, volume, image, target_value):
    if continuation is not None:
        if not isinstance(continuation, ContinuationBaseline):
            raise TypeError("continuation must be a validated ContinuationBaseline")
        continuation.validate_context(volume, image, target_value)


def initial_radiation(volume, continuation=None, dtype=np.float32):
    if continuation is None:
        return np.zeros_like(volume, dtype=dtype)
    if np.asarray(volume).shape != continuation.dose_model.shape:
        raise ValueError("Baseline dose shape mismatch")
    return continuation.dose_model.astype(dtype, copy=True)


def continuation_candidates(continuation, trajectories, image):
    if continuation is None:
        return list(trajectories)
    return [t for t in trajectories if continuation.path_allowed(t, image)]


def continuation_preview_context(continuation):
    """Identify supplemental geometry and total-dose coverage on preview events."""
    if continuation is None:
        return {}
    return {"supplemental_only": True, "coverage_component": "total",
            "dose_unit": "normalized_model",
            "baseline_dose_sha256": continuation.baseline_dose_sha256,
            "baseline_grid_signature": continuation.baseline_grid_signature,
            "dose_contract_id": continuation.dose_contract_id}


def continuation_slots(continuation, trajectory, steps, image, seed_info):
    if continuation is None:
        return steps
    point, direction = np.asarray(trajectory[0]), np.asarray(trajectory[1])
    advance = direction / np.max(np.abs(direction))
    return [s for s in steps if continuation.seed_allowed(
        trajectory, point + float(s) * advance, direction, image, seed_info)]


def sum_plan_dose(plan, volume, continuation=None, dtype=np.float32):
    """Rebuild baseline ONCE plus supplemental maps; fixed seeds are never entries."""
    total = initial_radiation(volume, continuation, dtype)
    for entry in plan or []:
        if continuation is not None and (len(entry) != 3 or len(entry[1]) != len(entry[2])):
            raise ValueError("Supplemental seeds and dose maps must correspond one to one")
        for contribution in entry[2]:
            dose = np.asarray(contribution, dtype=dtype)
            if dose.shape != total.shape or not np.isfinite(dose).all() or np.any(dose < 0):
                raise ValueError("Invalid supplemental dose map")
            total += dose
    if not np.isfinite(total).all():
        raise ValueError("Total dose overflowed")
    return total


def _cumulative_dvh(values, scale, thresholds):
    """Evaluate whole-structure V(dose >= threshold), including requested limits."""
    if not values.size:
        return {"dose_gy": np.array([]), "volume_fraction": np.array([])}
    physical = np.sort(values * scale)
    knots = np.unique(np.r_[np.linspace(0., physical[-1], 201), np.asarray(thresholds) * scale])
    fraction = (values.size - np.searchsorted(physical, knots, side='left')) / values.size
    return {"dose_gy": knots, "volume_fraction": fraction}


def finalize_continuation(plan, continuation, volume, image, target_value, seed_info,
                          prescription_model, outside_limit_model, target_coverage):
    """Supplemental decisions and typed complete-target/OAR total evaluation."""
    continuation.validate_context(volume, image, target_value)
    for name, value in (("prescription", prescription_model), ("outside_limit", outside_limit_model)):
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"Continuation {name} must be finite and positive")
    if not np.isfinite(target_coverage) or not 0 <= target_coverage <= 1:
        raise ValueError("Target coverage must be a finite fraction")
    supplemental = [entry for entry in plan or [] if entry[1]]
    associations = []
    for trajectory, seeds, _ in supplemental:
        if not continuation.path_allowed(trajectory, image):
            raise ValueError("Supplemental plan left its candidate/bore or collided with fixed material")
        for position, axis in seeds:
            index = np.asarray(image.TransformPhysicalPointToContinuousIndex(tuple(np.asarray(position).reshape(3))))[::-1]
            origin = index[::-1]
            tip = np.asarray(image.TransformPhysicalPointToContinuousIndex(tuple(np.asarray(position).reshape(3) + np.asarray(axis).reshape(3))))
            if not continuation.seed_allowed(trajectory, index, (tip - origin)[::-1], image, seed_info):
                raise ValueError("Supplemental seed violated fixed geometry or its candidate path")
        key = trajectory_key(trajectory)
        match = next((p for p in continuation.candidate_paths or () if p.geometry == key), None)
        associations.append({"candidate_id": match.candidate_id if match else None,
                             "bore_id": match.bore_id if match else None})
    additional = sum_plan_dose(plan, volume, None, dtype=np.float64)
    total = continuation.dose_model + additional
    scale = continuation.dose_scale_gy
    with np.errstate(over='ignore', invalid='ignore'):
        physical_total = total * scale
    if not np.isfinite(physical_total).all():
        raise ValueError("Calibrated physical total dose overflowed")
    target_values = total[continuation.complete_target_mask]
    coverage = float(np.mean(target_values >= prescription_model))
    organs = {}
    unmet = [] if coverage >= target_coverage else ["target_coverage"]
    curves = {"target": _cumulative_dvh(target_values, scale, [prescription_model, 1.5 * prescription_model, 2 * prescription_model])}
    for name, mask in continuation.oar_masks:
        values = total[mask]
        old = continuation.dose_model[mask]
        above = int(np.count_nonzero(values > outside_limit_model))
        if above:
            unmet.append(f"oar_limit:{name}")
        curves[f"oar:{name}"] = _cumulative_dvh(values, scale, [outside_limit_model])
        organs[name] = {"voxel_count": int(mask.sum()),
                        "Dmax_gy": float(values.max() * scale) if values.size else None,
                        "Dmean_gy": float(values.mean() * scale) if values.size else None,
                        "above_limit_fraction": float(np.mean(values > outside_limit_model)) if values.size else None,
                        "baseline_above_limit_voxels": int(np.count_nonzero(old > outside_limit_model))}
    return {"supplemental_plan": supplemental, "path_associations": associations,
            "dose_unit": "normalized_model", "physical_dose_unit": "Gy",
            "baseline_dose": continuation.dose_model, "additional_dose": additional,
            "implanted_dose_physical_gy": continuation.dose_model * scale,
            "planned_dose_physical_gy": additional * scale,
            "total_dose": total, "total_dose_gy": physical_total,
            "baseline_dose_sha256": continuation.baseline_dose_sha256,
            "grid_signature": continuation.baseline_grid_signature,
            "dose_contract_id": continuation.dose_contract_id,
            "fixed_seed_ids": tuple(s.physical_seed_id for s in continuation.fixed_seeds),
            "target_metrics": {"voxel_count": int(target_values.size), "V100": coverage,
                               "V150": float(np.mean(target_values >= 1.5 * prescription_model)),
                               "V200": float(np.mean(target_values >= 2 * prescription_model)),
                               "D90_gy": float(np.percentile(target_values, 10) * scale),
                               "Dmean_gy": float(target_values.mean() * scale)},
            "oar_metrics": organs, "total_dvh_gy": curves,
            "target_reached": coverage >= target_coverage,
            "objectives_met": not unmet, "unmet_objectives": unmet}
