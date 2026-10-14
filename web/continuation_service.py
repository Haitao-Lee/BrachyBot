"""Compose reviewed observations/guide geometry into a durable CNN baseline.

The caller binds a server-issued scope and reviewed source contract. This does
not accept an LLM's claim of approval, infer source strength or freeze clinical
thresholds. Dose basis is projected total source dose, not already delivered Gy.
"""
from dataclasses import dataclass, asdict
from collections.abc import Mapping
from pathlib import Path
from contextlib import nullcontext
import hashlib
import numpy as np
import SimpleITK as sitk

from plans.continuation import FixedSeed, FixedNeedle, CandidatePath
from utils.implant_reconstruction import SeedAxisReconstruction
from web.timepoints import TimepointConflict, timepoint_id


@dataclass(frozen=True)
class ContinuationSourceContract:
    contract_id: str
    source_model_id: str
    source_strength_u: float
    dose_scale_gy: float
    dose_model_sha256: str
    reviewer_id: str
    review_evidence: str
    capsule_length_mm: float
    capsule_diameter_mm: float
    temporal_basis: str = "projected_total_source_dose"
    source_strength_basis: str = "absolute_u"

    def __post_init__(self):
        import re
        for field in ("contract_id", "source_model_id", "reviewer_id", "review_evidence"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip() or len(value) > 4000:
                raise ValueError("Explicit reviewed source/model provenance is required")
        if self.source_strength_basis not in {"absolute_u", "model_nominal_relative"}:
            raise ValueError("An explicit source strength convention is required")
        if self.source_strength_basis == "absolute_u" and (self.source_strength_u is None
                or not np.isfinite(self.source_strength_u) or self.source_strength_u <= 0):
            raise ValueError("Absolute air-kerma strength must be finite and positive")
        if self.source_strength_basis == "model_nominal_relative" and self.source_strength_u is not None:
            raise ValueError("Nominal CNN calibration must not invent an absolute air-kerma strength")
        for field in ("dose_scale_gy", "capsule_length_mm", "capsule_diameter_mm"):
            if not np.isfinite(getattr(self, field)) or getattr(self, field) <= 0:
                raise ValueError("Source/calibration/dimension values must be finite and positive")
        if not re.fullmatch(r"[0-9a-f]{64}", self.dose_model_sha256):
            raise ValueError("The calibrated CNN checkpoint hash is required")
        if self.temporal_basis != "projected_total_source_dose":
            raise ValueError("This CNN continuation cannot reinterpret projected total dose as elapsed delivered dose")


def candidate_on_planning_grid(candidate, bore, image):
    """Preserve a real straight bore and its physical target intervals exactly."""
    axis = np.asarray(candidate["axis_lps"], dtype=float)
    inner = np.asarray(bore["inner_lps_mm"], dtype=float)
    tip = np.asarray(candidate["tip_lps_mm"], dtype=float)
    extent = float(np.dot(tip - inner, axis))
    intervals = [(float(a), min(float(b), extent)) for a,b in candidate["target_intervals_from_inner_mm"] if a < extent]
    if not intervals:
        raise ValueError("Bore path has no reachable current-image target interval")
    first = intervals[0][0]
    world = inner + first * axis
    point = np.asarray(image.TransformPhysicalPointToContinuousIndex(tuple(world)))[::-1]
    next_point = np.asarray(image.TransformPhysicalPointToContinuousIndex(tuple(world + axis)))[::-1]
    voxel_axis = next_point - point
    step_per_mm = float(np.max(np.abs(voxel_axis)))
    if not np.isfinite(step_per_mm) or step_per_mm <= 0:
        raise ValueError("Invalid physical-to-planning bore transform")
    voxel_axis /= np.linalg.norm(voxel_axis)
    target, background, previous = [], [], first
    for start, end in intervals:
        if end <= start or start < previous - 1e-8:
            raise ValueError("Bore target intervals are not ordered physical intervals")
        background.append((start - previous) * step_per_mm)
        target.append((end - start) * step_per_mm)
        previous = end
    trajectory = [point, voxel_axis, target, background, sum(target)]
    return CandidatePath.from_trajectory(candidate["candidate_id"], trajectory, candidate["bore_id"])


class ContinuationPreparationService:
    def __init__(self, agent):
        self.agent = agent
        self.store = getattr(agent, "_workspace_store", None)
        config = getattr(agent, "config", {}) or {}
        self.owner, self.session = config.get("_workspace_owner_id"), config.get("_workspace_session_id")
        if self.store is None or not self.owner or not self.session:
            raise ValueError("An authenticated owned Session is required")

    def prepare(self, *, target_timepoint_id, observation_revision_id,
                source_contract, needle_profile, dose_model_path,
                guide=None, accepted_placement=None, target_image=None,
                channel_states=None, in_situ_needles=(), search_policy=None,
                dose_model=None, dl_params=None):
        """No provider JSON route: trusted review boundary supplies typed contracts."""
        from web.guide_placement import (BoreValidationProfile, CurrentCTGeometry,
            initialize_bore_trajectories, placed_guide_geometry)
        from web.guide_service import GuidePlacementService
        from tool_factory.seed_plan import model_support, planning_pipeline as pipeline
        from tool_factory.seed_plan.continuation_support import baseline_record, source_contract_signature
        from tool_factory.seed_plan.continuation_search import guide_search_record, GuideFirstPolicy
        if not isinstance(source_contract, ContinuationSourceContract) or not isinstance(needle_profile, BoreValidationProfile):
            raise ValueError("Reviewed typed source and needle-geometry profiles are required")
        timepoint_id(target_timepoint_id)
        context = self.store.capture_timepoint_context(self.owner, self.session, target_timepoint_id)
        if context.target.stage != "intraoperative" or context.target.legacy_default:
            raise ValueError("Prepare on an explicitly linked nonlegacy intraoperative timepoint")
        snapshot = self.store.load_timepoint_snapshot(self.owner, self.session, target_timepoint_id, decode_arrays=True)
        results = snapshot["agent"]["planning_results"]
        from types import SimpleNamespace
        target_agent = SimpleNamespace(memory=SimpleNamespace(retrieve=results.get))
        # Selected current-image CT only. The source/preoperative CT is never
        # read as this plan's clinical image.
        helper = GuidePlacementService(self.agent)
        source_snapshot = self.store.load_timepoint_snapshot(self.owner, self.session,
            context.target.preoperative_timepoint_id, decode_arrays=False)
        source_results = source_snapshot["agent"]["planning_results"]
        source_has_guide = bool(helper.guide_records(source_snapshot))
        guide_requirement = {"source_timepoint_id": context.target.preoperative_timepoint_id,
            "manufactured_guide_present": source_has_guide, "placement_prepared": guide is not None}
        ct = helper._target_ct_image(snapshot)
        from utils.ctv_targets import resolve_ctv_target
        ctv = resolve_ctv_target(results.get)
        if ctv is None or np.asarray(ctv).shape != ct.GetSize()[::-1]:
            raise ValueError("Current-image CTV must be selected before baseline preparation")
        oar = results.get("oar_array")
        if oar is None or np.asarray(oar).shape != np.asarray(ctv).shape:
            raise ValueError("Current-image OAR must be provided before baseline preparation")
        catalog = results.get("implanted_seed_reconstruction") or self.agent.memory.retrieve("implanted_seed_reconstruction")
        from web.implant_service import ImplantScope, ImplantService
        journal = ImplantService(ImplantScope(self.owner, self.session, target_timepoint_id,
            str(self.store.workspace_root(self.owner, self.session)),
            (snapshot.get("image_collection") or {}).get("planning_reference_image_id")), self.agent.memory)
        journal_exists = (journal.root / "index.json").is_file()
        if journal_exists:
            journal.get()  # Restore the durable current head, not an old saved metadata alias.
            catalog = self.agent.memory.retrieve("implanted_seed_reconstruction")
        entry = (catalog or {}).get("by_timepoint", {}).get(target_timepoint_id)
        current = entry.get("current") if isinstance(entry, Mapping) else None
        if not isinstance(current, Mapping) or current.get("preoperative_timepoint_id") != context.target.preoperative_timepoint_id:
            raise ValueError("Current owned implant reconstruction is missing or linked to another source")
        reconstruction = SeedAxisReconstruction.from_dict(current["reconstruction"])
        if reconstruction.revision_id != observation_revision_id or not reconstruction.dose_input_ready:
            raise ValueError("Review the exact current implant observation revision before dose construction")
        if reconstruction.image_ref.timepoint_id != target_timepoint_id or reconstruction.image_ref.session_id != self.session:
            raise ValueError("Implant observations belong to another clinical image workspace")
        # Byte hash plus physical image equality prevents reuse against a CT
        # with identical geometry but different voxel data.
        from utils.tool_security import checked_path
        from utils.image_limits import read_image
        image_path = checked_path(results.get("ct_path"), root=self.store.workspace_root(self.owner, self.session))
        from tool_factory.seed_seg.seedfinder_adapter import sha256_file
        if sha256_file(image_path) != reconstruction.image_ref.image_sha256:
            raise ValueError("The original intraoperative CT content changed after reconstruction")
        from tool_factory.seed_plan.continuation_support import image_signature
        if image_signature(read_image(image_path)) != image_signature(ct):
            raise ValueError("Saved clinical CT differs from the reconstructed intraoperative input")
        checkpoint = Path(dose_model_path).resolve(strict=True)
        if sha256_file(checkpoint) != source_contract.dose_model_sha256:
            raise ValueError("CNN checkpoint differs from the reviewed source-calibration contract")
        fixed = []
        for observation in reconstruction.observations:
            if observation.review_status != "accepted":
                continue
            dimensions = observation.dimensions
            if (dimensions.source_model_id != source_contract.source_model_id
                    or abs(dimensions.capsule_length_mm - source_contract.capsule_length_mm) > 1e-6
                    or abs(dimensions.capsule_diameter_mm - source_contract.capsule_diameter_mm) > 1e-6):
                raise ValueError("Observed source dimensions differ from the reviewed CNN source contract")
            fixed.append(FixedSeed(observation.physical_seed_id or "observed:" + observation.observation_id,
                observation.center_lps_mm, observation.axis_lps, dimensions.capsule_length_mm, dimensions.capsule_diameter_mm / 2))
        resampled, target, organs = pipeline._resample_for_planning(ct, np.asarray(ctv), np.asarray(oar))
        paths, guide_record, rejected = None, None, []
        fixed_needles = tuple(in_situ_needles)
        if any(not isinstance(n, FixedNeedle) for n in fixed_needles):
            raise ValueError("In-situ needles must be captured typed physical geometry")
        if guide is not None:
            if target_image != helper._target_image(snapshot):
                raise ValueError("Accepted guide placement refers to another current CT content revision")
            if not source_has_guide:
                raise ValueError("The associated preoperative timepoint has no saved source guide")
            _, _, saved_guide = helper._source_target(context.target.preoperative_timepoint_id,
                target_timepoint_id, guide.get("version"))
            from web.guide_placement import verify_manufactured_geometry
            if verify_manufactured_geometry(saved_guide)["manifest_sha256"] != verify_manufactured_geometry(guide)["manifest_sha256"]:
                raise ValueError("Supplied guide differs from the associated preoperative manufactured guide")
            geometry = placed_guide_geometry(guide, accepted_placement, target_image=target_image)
            labels, _ = pipeline._resolve_data_tree_obstacle_labels(target_agent)
            hard = np.isin(oar, list(labels))
            current_context = CurrentCTGeometry(ct, ctv_mask=np.asarray(ctv) > 0, oar_mask=hard,
                body_mask=pipeline._body_mask_from_ct(ct), identity=target_image)
            seeds_for_validation = [dict(id=s.physical_seed_id, center_lps_mm=s.center_lps_mm, axis_lps=s.axis_lps,
                length_mm=s.length_mm, radius_mm=s.radius_mm) for s in fixed]
            needles_for_validation = [dict(id=n.needle_id, points_lps_mm=[n.entry_lps_mm,n.tip_lps_mm], radius_mm=n.radius_mm) for n in fixed_needles]
            initialized = initialize_bore_trajectories(guide, accepted_placement, current_context,
                profile=needle_profile, fixed_seeds=seeds_for_validation, in_situ_needles=needles_for_validation,
                channel_states=channel_states)
            bores = {b["bore_id"]: b for b in geometry["bores"]}
            paths = tuple(candidate_on_planning_grid(c, bores[c["bore_id"]], resampled) for c in initialized["candidates"])
            rejected = initialized["rejected"]
            guide_record = guide_search_record(guide, accepted_placement, ct, target_image,
                                               policy=search_policy or GuideFirstPolicy())
        elif accepted_placement is not None or search_policy is not None:
            raise ValueError("Guide-first continuation requires the actual immutable source guide")
        seed_info = {"length": source_contract.capsule_length_mm,
                     "radius": source_contract.capsule_diameter_mm / 2, "margin_rate": 1.5}
        effective_dl = dict(dl_params or {})
        # Explicit path binds inference to the same checkpoint that was hashed.
        effective_dl["dose_model_path"] = str(checkpoint)
        oar_masks = tuple((str(label), organs == label) for label in np.unique(organs) if label > 0)
        baseline_options = dict(
            complete_target_mask=target > 0, dose_scale_gy=source_contract.dose_scale_gy,
            dose_contract_id=source_contract.contract_id, needle_radius_mm=needle_profile.needle_radius_mm,
            clearance_mm=needle_profile.obstacle_clearance_mm, candidate_paths=paths,
            fixed_needles=fixed_needles, oar_masks=oar_masks)
        from plans.continuation import ContinuationBaseline, array_sha256, grid_signature
        from web.timepoint_resources import capture_resources, component_current, resource_state
        from web.dose_components import dose_component, resample_dose
        resources = capture_resources(results.get, ct, reconstruction=reconstruction,
            source={"profile": results.get("implant_dose_profile") or {},
                    "contract": asdict(source_contract), "dose_scale_gy": source_contract.dose_scale_gy},
            model_sha256=source_contract.dose_model_sha256, dl_params=effective_dl, seed_info=seed_info)
        reused = False
        cached = results.get("continuation_baseline_record")
        dose = None
        if (cached is not None and results.get("continuation_baseline_dependency_fingerprint") == resources["implanted_dose"]):
            restored = ContinuationBaseline.from_record(cached["baseline"])
            if (restored.baseline_grid_signature == grid_signature(resampled)
                    and restored.fixed_seeds == tuple(fixed)):
                dose = restored.dose_model
                reused = True
        implanted = results.get("implanted_dose_record")
        if dose is None and component_current(implanted, "implanted", resources, ct):
            dose = resample_dose(implanted["dose_distribution_physical_gy"], ct, resampled) / source_contract.dose_scale_gy
            reused = True
        if dose is None and fixed:
            from plans.device_manager import device_session
            from web.implant_service import _default_device_lock
            from utils.cancellation import is_cancelled, raise_if_cancelled
            configured = str(effective_dl.get("device") or "auto")
            preferred = configured if configured in {"auto", "cpu"} else configured.split(":")[-1]
            with (device_session(caller="continuation-baseline:" + target_timepoint_id, prefer=preferred)
                    if dose_model is None else nullcontext(None)) as lease:
                device = lease.device_str if lease is not None else configured
                effective_dl["device"] = device
                with (_default_device_lock(device, cancelled=is_cancelled, deadline=None)
                        if lease is not None else nullcontext()):
                    raise_if_cancelled()
                    model, error = model_support.resolve_dose_model(
                        {"dose_cal_model": dose_model} if dose_model is not None else {}, effective_dl)
                    if model is None:
                        raise RuntimeError(error or "The reviewed CNN model is unavailable")
                    computed = model_support.compute_continuation_baseline(fixed, resampled, model,
                        effective_dl, seed_info, **baseline_options)
                    dose = computed.dose_model
        if dose is None:
            dose = np.zeros_like(target, dtype=float)
        # Anatomy and feasible channels are refreshed independently of the
        # unchanged CNN source dose. A reused baseline never retains old masks.
        baseline = ContinuationBaseline.create(dose, resampled, baseline_unit="normalized_model",
            baseline_grid_signature=grid_signature(resampled), baseline_dose_sha256=array_sha256(dose),
            fixed_seeds=fixed, **baseline_options)
        sources = [{"id": s.physical_seed_id, "position": s.center_lps_mm, "direction": s.axis_lps} for s in fixed]
        implant_record = dose_component("implanted", resample_dose(dose, resampled, ct), ct,
            units="normalized_model", scale=source_contract.dose_scale_gy, resources=resources, sources=sources,
            observation_revision_id=observation_revision_id, timepoint_id=target_timepoint_id,
            dose_model_sha256=source_contract.dose_model_sha256, dose_profile=results.get("implant_dose_profile") or {},
            seed_info=seed_info, clinical_use_ready=False, dose_status="reviewed_baseline_dose", reused=reused)
        components = dict(results.get("dose_components") or {})
        components.update(schema_version=1, implanted=implant_record, evaluation_source_set="total")
        if not reused:
            components["total"] = None
        updates = {"continuation_baseline_record": baseline_record(baseline, ct,
                       observation_revision_id=observation_revision_id, timepoint_id=target_timepoint_id),
                   "continuation_source_contract": asdict(source_contract),
                   "continuation_source_binding_sha256": source_contract_signature(asdict(source_contract)),
                   "continuation_dose_model_path": str(checkpoint),
                   "continuation_dl_params": effective_dl,
                   "continuation_search_record": guide_record,
                   "continuation_bore_rejections": rejected,
                   "continuation_guide_requirement": guide_requirement,
                   "implanted_seed_reconstruction": catalog,
                   "continuation_input_seed_info": seed_info,
                   "continuation_baseline_dependency_fingerprint": resources["implanted_dose"],
                   "continuation_anatomy_binding_sha256": anatomy_binding_signature(results.get, ct),
                   "implanted_dose_record": implant_record, "dose_components": components,
                   "timepoint_resource_state": resource_state(results.get("timepoint_resource_state"), resources,
                                                               ready=("implanted_dose",))}
        from tool_factory.seed_plan.continuation_support import inference_settings_signature,continuation_geometry_signature
        updates["continuation_inference_binding_sha256"] = inference_settings_signature({**results, **updates}.get)
        updates['continuation_geometry_binding_sha256']=continuation_geometry_signature({**results,**updates}.get)
        if "metrics" in updates["timepoint_resource_state"]["invalidated"]:
            updates.update(dose_metrics=None, metrics=None, dvh_data=None, total_dose_evaluation=None,
                           report_status="stale", quality_check_status="stale")
            status = dict(results.get("artifact_status") or results.get("manual_artifact_status") or {})
            status.update(dvh="stale", quality_check="stale", report="stale")
            updates.update(artifact_status=status, manual_artifact_status=status)
        if sha256_file(checkpoint) != source_contract.dose_model_sha256 or sha256_file(image_path) != reconstruction.image_ref.image_sha256:
            raise TimepointConflict("Current CT/checkpoint changed while baseline dose was computed")
        with journal._journal() if journal_exists else nullcontext(None) as index:
            if journal_exists:
                if index.get("current", {}).get("revision_id") != observation_revision_id.replace("-", ""):
                    # The service journal canonicalizes revision UUID strings.
                    from uuid import UUID
                    if not index.get("current") or UUID(index["current"]["revision_id"]) != UUID(observation_revision_id):
                        raise TimepointConflict("Implant observations changed while baseline dose was computed")
            latest_catalog = self.agent.memory.retrieve("implanted_seed_reconstruction")
            if latest_catalog is not None and latest_catalog != catalog:
                raise TimepointConflict("Implant observation memory changed while baseline dose was computed")
            saved = self.store.save_timepoint_results(self.owner, self.session, target_timepoint_id, updates,
                expected_clinical_revision=context.target.clinical_revision, execution_context=context)
        runtime = getattr(self.agent, "_workspace_scoped_chat_runtime", None)
        if runtime is not None:
            runtime.accept_external_patch(saved, updates, ())
        else:
            for key, value in updates.items():
                self.agent.memory.store(key, value)
        return {"baseline": baseline, "timepoint_id": target_timepoint_id,
                "saved_clinical_revision": saved["timepoint_clinical_revision"], "fixed_seed_count": len(fixed),
                "guide_channel_count": len(paths) if paths is not None else None, "rejected_channels": rejected,
                "dose_basis": source_contract.temporal_basis, "clinical_use_approved": False,
                "reused_implanted_dose": reused,
                "invalidated_resources": updates["timepoint_resource_state"]["invalidated"]}


def anatomy_binding_signature(retrieve, image):
    from web.timepoint_resources import fingerprint, capture_resources
    resources = capture_resources(retrieve, image)
    return fingerprint({key: resources[key] for key in ("image", "ctv", "oar",'obstacle_policy')})
