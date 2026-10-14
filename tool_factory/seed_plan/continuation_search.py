"""Guide-first continuation with a reviewed rigid guide as a hard obstacle.

Outside-guide search is a second bounded phase. It keeps the complete target,
fixed implanted dose and first-phase choices; it never creates a new guide or
changes the manufactured mesh. Neither phase certifies clinical readiness.
"""
from dataclasses import dataclass, replace
from collections.abc import Mapping
import hashlib
import json
import time
import numpy as np

from plans.continuation import CandidatePath, continuation_candidates, trajectory_key
from .continuation_support import image_signature


@dataclass(frozen=True)
class GuideFirstPolicy:
    outside_guide_enabled: bool = True
    search_seconds: float = 60.
    maximum_candidates: int = 200
    repair_rounds: int = 128
    policy_id: str = "guide-first-hard-obstacle-v1"

    def __post_init__(self):
        if type(self.outside_guide_enabled) is not bool or not self.policy_id:
            raise ValueError("Guide search requires an explicit policy")
        if not np.isfinite(self.search_seconds) or not 0 < self.search_seconds <= 600:
            raise ValueError("Outside-guide search budget must be within (0, 600] seconds")
        for name in ("maximum_candidates", "repair_rounds"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 2000:
                raise ValueError("Outside-guide resource limits must be bounded integers")


def _record_digest(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def guide_search_record(guide, accepted_placement, current_image, target_image, *, policy=GuideFirstPolicy()):
    """Called by the trusted reviewed-placement boundary, not provider JSON."""
    from dataclasses import asdict
    from web.guide_placement import placed_guide_geometry
    geometry = placed_guide_geometry(guide, accepted_placement, target_image=target_image)
    record = {"schema_version": 1, "current_image_signature": image_signature(current_image),
        "placement_id": accepted_placement["placement_id"], "placement_revision": accepted_placement["revision"],
        "candidate_sha256": accepted_placement["candidate_sha256"], "manufactured_geometry_id": accepted_placement["geometry_id"],
        "vertices_lps_mm": np.asarray(geometry["vertices_lps_mm"], dtype=float).tolist(),
        "faces": np.asarray(geometry["faces"], dtype=int).tolist(), "policy": asdict(policy),
        "source": "reviewed-manufactured-guide-placement", "clinical_use_approved": False}
    record["record_sha256"] = _record_digest(record)
    return record


class GuideMaterialObstacle:
    """Closed original guide material, with physical-radius collision tests.

    Distance-guided marching uses the 1-Lipschitz distance bound: a step never
    exceeds the known free distance. Thin walls between sampled points cannot
    be stepped over. Nonfinite geometry, open surfaces and budget exhaustion
    fail closed. A conservative voxel projection is used only for init ranking;
    the full external-to-tip segment is independently checked against the mesh.
    """
    def __init__(self, vertices, faces, *, needle_radius_mm, clearance_mm, signature):
        import vtk
        from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
        v, f = np.asarray(vertices, dtype=float), np.asarray(faces)
        if (v.ndim != 2 or v.shape[1:] != (3,) or f.ndim != 2 or f.shape[1:] != (3,)
                or not 4 <= len(v) <= 1_000_000 or not 4 <= len(f) <= 2_000_000
                or not np.isfinite(v).all() or not np.isfinite(f).all()
                or np.any(f != np.floor(f)) or f.min() < 0 or f.max() >= len(v)):
            raise ValueError("A bounded finite triangular guide mesh is required")
        f = f.astype(np.int64)
        edges = np.sort(np.concatenate((f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]])), axis=1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        if np.any(counts != 2) or np.any(np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1) <= 1e-10):
            raise ValueError("Guide obstacle must be closed, manifold and nondegenerate")
        self.radius = float(needle_radius_mm) + float(clearance_mm)
        if not np.isfinite(self.radius) or self.radius <= 0:
            raise ValueError("Guide collision radius/clearance is invalid")
        points = vtk.vtkPoints()
        points.SetData(numpy_to_vtk(v, deep=True))
        cells = vtk.vtkCellArray()
        cells.SetCells(len(f), numpy_to_vtkIdTypeArray(np.column_stack((np.full(len(f), 3), f)).ravel(), deep=True))
        poly = vtk.vtkPolyData()
        poly.SetPoints(points)
        poly.SetPolys(cells)
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(poly)
        normals.ConsistencyOn()
        normals.AutoOrientNormalsOn()
        normals.SplittingOff()
        normals.Update()
        self.distance = vtk.vtkImplicitPolyDataDistance()
        self.distance.SetInput(normals.GetOutput())
        self.bounds = (v.min(axis=0), v.max(axis=0))
        self.signature = signature

    def blocks_segment(self, points, *, deadline=None):
        p = np.asarray(points, dtype=float)
        if p.shape != (2, 3) or not np.isfinite(p).all():
            return True
        delta = p[1] - p[0]
        length = float(np.linalg.norm(delta))
        if not np.isfinite(length) or length <= 1e-9:
            return True
        unit, depth = delta / length, 0.
        for _ in range(20_000):
            if deadline is not None and time.monotonic() >= deadline:
                return True
            d = float(self.distance.EvaluateFunction((p[0] + depth * unit).tolist()))
            free = d - self.radius
            if not np.isfinite(free) or free <= 1e-6:
                return True
            if depth >= length:
                return False
            depth += min(length - depth, free * .8)
        return True

    def planning_mask(self, image, *, deadline=None, max_voxels=2_000_000):
        shape = tuple(image.GetSize()[::-1])
        if np.prod(shape) > max_voxels:
            raise ValueError("Guide obstacle projection exceeds the planning-grid resource limit")
        mask = np.zeros(shape, bool)
        origin = np.asarray(image.GetOrigin())
        linear = np.asarray(image.GetDirection()).reshape(3, 3) @ np.diag(image.GetSpacing())
        # Inflated distance covers the entire voxel and the needle radius.
        inflation = self.radius + float(np.linalg.norm(image.GetSpacing())) / 2
        low, high = self.bounds
        for z in range(shape[0]):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Outside-guide obstacle projection reached its time budget")
            yy, xx = np.indices(shape[1:])
            xyz = np.column_stack((xx.ravel(), yy.ravel(), np.full(xx.size, z)))
            world = origin + xyz @ linear.T
            near = np.flatnonzero(np.all(world >= low - inflation, axis=1) & np.all(world <= high + inflation, axis=1))
            for index in near:
                d = float(self.distance.EvaluateFunction(world[index].tolist()))
                if not np.isfinite(d):
                    raise ValueError("Guide obstacle distance is nonfinite")
                mask[z].ravel()[index] = d <= inflation
        return mask


def resolve_guide_search(agent, image, baseline):
    retrieve = getattr(getattr(agent, "memory", None), "retrieve", lambda *_: None)
    record = retrieve("continuation_search_record")
    if record is None:
        return None  # Legacy guide-only research records stay explicitly guide-only.
    if not isinstance(record, Mapping) or record.get("schema_version") != 1:
        raise ValueError("Invalid guide-first continuation search state")
    if record.get("record_sha256") != _record_digest({k: v for k, v in record.items() if k != "record_sha256"}):
        raise ValueError("Guide obstacle changed after reviewed placement")
    if record.get("current_image_signature") != image_signature(image):
        raise ValueError("The guide obstacle belongs to another current-image revision")
    if record.get("source") != "reviewed-manufactured-guide-placement":
        raise ValueError("Outside-guide search requires the positioned manufactured guide")
    poses = retrieve("guide_placement_candidates")
    if isinstance(poses, Mapping) and poses:
        pose = poses.get(record.get("placement_id"))
        if (not isinstance(pose, Mapping) or pose.get("candidate_sha256") != record.get("candidate_sha256")
                or pose.get("revision") != record.get("placement_revision") or pose.get("review_state") != "accepted"):
            raise ValueError("Guide placement review changed; refresh candidates and guide obstacle")
    if baseline is None or baseline.candidate_paths is None:
        raise ValueError("Guide-first search requires an explicit first-stage channel inventory")
    policy = GuideFirstPolicy(**record["policy"])
    obstacle = GuideMaterialObstacle(record["vertices_lps_mm"], record["faces"],
        needle_radius_mm=baseline.needle_radius_mm, clearance_mm=baseline.clearance_mm,
        signature=record["record_sha256"])
    return policy, obstacle


def extend_candidates(baseline, trajectories):
    paths = list(baseline.candidate_paths or ())
    known = {p.geometry for p in paths}
    for trajectory in trajectories:
        key = trajectory_key(trajectory)
        if key in known:
            continue
        identifier = hashlib.sha256(repr(key).encode()).hexdigest()[:24]
        paths.append(CandidatePath.from_trajectory("outside-guide-" + identifier, trajectory))
        known.add(key)
    return replace(baseline, candidate_paths=tuple(paths))


def search_outside_guide(plan, baseline, search, *, ct_image, planning_image, ctv_mask,
                        oar_mask, planning_oar, volume, obstacle_labels, body_mask, args, reference_direction,
                        prescription_model, outside_limit_model, dose_model,
                        infer_dose, parallel_min_distance_mm, parallel_angle_tolerance_deg,
                        preview_callback=None):
    """Retain first-stage choices and append only independently safe additions."""
    from plans import core, utilizations as util
    from plans.coverage_repair import repair_coverage
    from plans.continuation import sum_plan_dose
    from . import planning_pipeline as pipe
    started = time.monotonic()
    target = baseline.complete_target_mask
    dose = sum_plan_dose(plan, volume, baseline)
    coverage = float(np.mean(dose[target] >= prescription_model))
    policy, guide = search
    status = {"policy_id": policy.policy_id, "order": ["existing_guide_channels", "outside_guide"],
              "guide_phase_coverage": coverage, "outside_guide_attempted": False,
              "guide_material_obstacle": guide.signature, "clinical_use_approved": False,
              "kept_first_phase_seeds": sum(len(e[1]) for e in plan), "stop_reason": "target_already_reached"}
    if coverage >= float(args.DVH_rate):
        return plan, baseline, status
    if not policy.outside_guide_enabled:
        status["stop_reason"] = "outside_guide_disabled"
        return plan, baseline, status
    deadline = started + policy.search_seconds
    status["outside_guide_attempted"] = True
    try:
        hard_mask = guide.planning_mask(planning_image, deadline=deadline)
        if np.any(hard_mask & target):
            raise ValueError("Positioned guide overlaps the current target; review pose before outside-guide planning")
        search_volume = np.array(volume, copy=True)
        search_volume[hard_mask] = args.radiation_array_params['obstacle_value']
        direction = pipe._convert_ref_direc_to_voxel(reference_direction, planning_image)
        entry_body = pipe._body_mask_from_ct(planning_image)
        faces = util.infer_truncated_boundary_faces_from_image(planning_image)
        candidates = core.init_plan(planning_image, search_volume, direction, args.direc_resolution,
            args.radiation_array_params['backlit_angle'], args.radiation_array_params['target_value'],
            args.radiation_array_params['background_value'], args.radiation_array_params['obstacle_value'],
            min(policy.maximum_candidates, args.radiation_array_params['maximum_candidate_trajectories']),
            min_depth=args.radiation_array_params.get('min_depth', 1),
            entry_body_mask=entry_body, entry_boundary_faces=faces, deadline=deadline)
        candidates = pipe._filter_safe_trajectories(candidates, search_volume, args.radiation_array_params['obstacle_value'])
        candidates = pipe._filter_world_safe_trajectories(candidates, planning_image, ct_image,
            ctv_mask, oar_mask, obstacle_labels, body_mask=body_mask)
        unbound = replace(baseline, candidate_paths=None)
        previous = {p.geometry for p in baseline.candidate_paths or ()}
        candidates = [t for t in continuation_candidates(unbound, candidates, planning_image)
                      if trajectory_key(t) not in previous and not guide.blocks_segment(
                          pipe._candidate_world_needle_points(t, planning_image), deadline=deadline)]
        status["outside_candidate_count"] = len(candidates)
        if not candidates:
            status["stop_reason"] = "no_safe_outside_guide_path"
            return plan, baseline, status
        expanded = extend_candidates(baseline, candidates)
        outside_keys = {trajectory_key(t) for t in candidates}
        def validate(trajectory, selected):
            if not expanded.path_allowed(trajectory, planning_image):
                return False
            if trajectory_key(trajectory) in outside_keys and guide.blocks_segment(
                    pipe._candidate_world_needle_points(trajectory, planning_image), deadline=deadline):
                return False
            spacing = util.get_trajectory_spacing_safety_mask([trajectory], selected, planning_image,
                base_min_distance_mm=args.distance_filtter['lower_bound'],
                parallel_min_distance_mm=parallel_min_distance_mm,
                parallel_angle_tolerance_deg=parallel_angle_tolerance_deg)
            return bool(spacing[0])
        organs = np.zeros_like(target) if planning_oar is None else np.asarray(
            pipe._planning_grid_array(planning_oar, source="outside-guide OAR")) > 0
        if organs.shape != target.shape:
            # Caller supplies the planning-grid OAR volume, not acquisition labels.
            raise ValueError("Outside-guide OAR dose grid does not match the complete target")
        organs &= ~target
        remaining = max(0., deadline - time.monotonic())
        if preview_callback is not None:
            preview_callback({"phase": "outside_guide_search", "candidate_count": len(candidates),
                              "coverage": coverage, "guide_obstacle_checked": True})
        result, repair = repair_coverage(plan, candidates, volume, planning_image,
            args.radiation_array_params['target_value'], organs, prescription_model, outside_limit_model,
            args.DVH_rate, args.seed_info, infer_dose, validate, generate=None,
            seconds=remaining, rounds=policy.repair_rounds, shortlist=5,
            candidate_limit=policy.maximum_candidates, continuation=expanded)
        status.update(stop_reason=repair["stop_reason"], outside_phase_coverage=repair["final_coverage"],
                      additional_seeds=repair["added_seeds"], additional_needles=repair["added_needles"])
        return result, expanded, status
    except (ValueError, TimeoutError) as exc:
        status.update(stop_reason="outside_search_blocked", error=str(exc))
        return plan, baseline, status
    finally:
        status["elapsed_seconds"] = time.monotonic() - started
