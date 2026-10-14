"""Owned source-separated physical dose, evaluated after addition exactly once."""
from collections.abc import Mapping
import copy
import numpy as np

from plans.continuation import grid_signature
from utils.dose_units import physical_volume
from web.timepoint_resources import clinical_sources, fingerprint


DOSE_UNIT_METADATA = {
    "dose_distribution": "normalized_model",
    "dose_distribution_gy": "physical_gy",
    "dose_distribution_physical_gy": "physical_gy",
    "dose_distribution_current_normalized": "normalized_model",
    "algorithm_plan_dose_distribution_gy": "physical_gy",
    "algorithm_plan_dose_distribution_current_normalized": "normalized_model",
    "dose_components.*.dose_distribution_physical_gy": "physical_gy",
}


def resample_dose(dose, source_image, target_image):
    """Interpolate a single component on physical grids without changing units."""
    import SimpleITK as sitk
    array = np.asarray(dose, dtype=np.float32)
    if array.shape != tuple(source_image.GetSize()[::-1]) or not np.isfinite(array).all() or np.any(array < 0):
        raise ValueError("Dose interpolation requires a valid explicit source grid")
    if grid_signature(source_image) == grid_signature(target_image):
        return np.array(array, copy=True)
    volume = sitk.GetImageFromArray(array)
    volume.CopyInformation(source_image)
    return sitk.GetArrayFromImage(sitk.Resample(volume, target_image, sitk.Transform(), sitk.sitkLinear, 0.0, sitk.sitkFloat32))


def dose_component(source_set, dose, image, *, units, scale, resources, sources=(), **metadata):
    if source_set not in {"implanted", "planned"}:
        raise ValueError("An individual dose component must name its source set")
    physical = physical_volume(dose, units=units, scale=scale)
    if physical.shape != tuple(image.GetSize()[::-1]):
        raise ValueError("Dose component does not match the current physical CT grid")
    geometry = clinical_sources(sources)
    return {**metadata, "schema_version": 1, "source_set": source_set,
            "dose_units": "physical_gy", "dose_scale_gy": float(scale),
            "grid_signature": grid_signature(image),
            "ct_spacing": list(image.GetSpacing()), "ct_origin": list(image.GetOrigin()),
            "ct_direction": list(image.GetDirection()), "dose_shape": list(physical.shape),
            "source_geometry": geometry, "source_count": len(geometry),
            "source_geometry_sha256": fingerprint(geometry),
            "dependency_fingerprint": resources[source_set + "_dose"],
            "dose_distribution_physical_gy": np.array(physical, copy=True),
            "dose_sha256": fingerprint(physical), "dose_min_gy": float(physical.min()),
            "dose_max_gy": float(physical.max()),
            "dose_basis": "projected_total_source_dose_not_elapsed_delivered_dose"}


def total_component(implanted, planned, resources):
    """Reject cross-grid or repeated physical sources instead of adding scans."""
    for record in (implanted, planned):
        if not isinstance(record, Mapping) or record.get("dose_units") != "physical_gy":
            raise ValueError("Total dose requires two explicitly physical-Gy components")
        if record.get("status") == "stale" or record.get("dose_status") == "stale":
            raise ValueError("A dose component is stale for the current clinical inputs")
        if (record.get("source_geometry_sha256") != fingerprint(clinical_sources(record.get('source_geometry') or ()))
                or record.get('source_count') != len(record.get('source_geometry') or ())):
            raise ValueError("Dose component source geometry changed after computation")
        if record.get("dose_sha256") != fingerprint(record["dose_distribution_physical_gy"]):
            raise ValueError("Dose component content changed after computation")
        if record.get("dependency_fingerprint") != resources[record["source_set"] + "_dose"]:
            raise ValueError("A dose component is stale for the current clinical inputs")
    if implanted["source_set"] != "implanted" or planned["source_set"] != "planned":
        raise ValueError("Total must contain the implanted and supplemental components once")
    if implanted["grid_signature"] != planned["grid_signature"]:
        raise ValueError("Cannot sum dose from different physical image grids")
    old_ids = {s["id"] for s in implanted["source_geometry"]}
    if old_ids.intersection(s["id"] for s in planned["source_geometry"]):
        raise ValueError("A physical source appears in both implanted and planned dose")
    old = physical_volume(implanted["dose_distribution_physical_gy"], units="physical_gy")
    new = physical_volume(planned["dose_distribution_physical_gy"], units="physical_gy")
    if old.shape != new.shape:
        raise ValueError("Dose components have different array grids")
    total = physical_volume(old.astype(np.float64) + new.astype(np.float64), units="physical_gy")
    return {"schema_version": 1, "source_set": "total", "dose_units": "physical_gy",
            "grid_signature": implanted["grid_signature"], "dose_shape": list(total.shape),
            "dose_distribution_physical_gy": total, "dose_sha256": fingerprint(total),
            "component_sha256": {"implanted": implanted["dose_sha256"], "planned": planned["dose_sha256"]},
            "dependency_fingerprint": resources["total_dose"],
            "source_count": implanted["source_count"] + planned["source_count"],
            "dose_basis": implanted["dose_basis"]}


def component_bundle(implanted, planned, resources):
    return {"schema_version": 1, "implanted": implanted, "planned": planned,
            "total": total_component(implanted, planned, resources), "evaluation_source_set": "total"}


def pipeline_components(agent, current_image, planning_image, implanted_model, planned_model, scale, baseline=None,
                        *, planned_sources=None, dl_params=None, seed_info=None, model_sha256=None):
    """Publish independent components from the actual accepted optimizer maps."""
    from dataclasses import asdict
    from web.timepoint_resources import capture_resources, dependency_fingerprints, resource_state
    retrieve = agent.memory.retrieve
    config = retrieve("plan_config") or {}
    saved = retrieve("continuation_baseline_record") or {}
    target = saved.get("timepoint_id")
    catalog = retrieve("implanted_seed_reconstruction") or {}
    reconstruction = ((catalog.get("by_timepoint", {}).get(target) or {}).get("current") or {}).get("reconstruction")
    sources = planned_sources if planned_sources is not None else (retrieve("algorithm_plan_snapshot") or {}).get("seeds") or []
    fixed = [{"id": seed.physical_seed_id, "position": seed.center_lps_mm, "direction": seed.axis_lps}
             for seed in (baseline.fixed_seeds if baseline is not None else ())]
    contract = retrieve("continuation_source_contract") or {}
    resources = capture_resources(retrieve, current_image, reconstruction=reconstruction, planned_sources=sources,
        source={"profile": retrieve("implant_dose_profile") or {}, "contract": contract or None, "dose_scale_gy": scale},
        model_sha256=model_sha256 or contract.get("dose_model_sha256") or config.get("dose_model_sha256"),
        dl_params=dl_params or retrieve("continuation_dl_params") or config.get("dl_params"),
        seed_info=seed_info or config.get("seed_info"))
    if baseline is not None and reconstruction is None:
        # Explicit typed numerical baselines still depend on their fixed geometry.
        resources["observation"] = fingerprint([asdict(seed) for seed in baseline.fixed_seeds])
        resources = dependency_fingerprints(resources)
    implanted = dose_component("implanted", resample_dose(implanted_model, planning_image, current_image), current_image,
        units="normalized_model", scale=scale, resources=resources, sources=fixed,
        observation_revision_id=saved.get("observation_revision_id"), timepoint_id=target,
        dose_profile=retrieve("implant_dose_profile") or {}, dose_model_sha256=model_sha256 or contract.get("dose_model_sha256"),
        seed_info=seed_info or config.get("seed_info"),
        clinical_use_ready=False, dose_status="reviewed_baseline_dose" if baseline is not None else "zero_no_implant")
    planned = dose_component("planned", resample_dose(planned_model, planning_image, current_image), current_image,
        units="normalized_model", scale=scale, resources=resources, sources=sources, supplemental_only=baseline is not None)
    bundle = component_bundle(implanted, planned, resources)
    return {"dose_components": bundle, "implanted_dose_record": implanted,
            "dose_distribution_physical_gy": bundle["total"]["dose_distribution_physical_gy"],
            "dose_distribution_gy": bundle["total"]["dose_distribution_physical_gy"],
            "dose_distribution_current_normalized": bundle["total"]["dose_distribution_physical_gy"] / scale,
            "dose_unit_schema_version": 2,
            "dose_unit_metadata": dict(DOSE_UNIT_METADATA),
            "timepoint_resource_state": resource_state(retrieve("timepoint_resource_state"), resources,
                ready=("implanted_dose", "planned_dose", "total_dose"))}


def evaluate_total(bundle, ctv, oar, image, plan_config, *, organ_names=None):
    """Evaluate total physical Gy against the caller's explicit QA basis.

    Current consumers resolve owned Input settings; historical consumers can
    supply the saved evaluation config without rewriting immutable plan inputs.
    """
    from tool_factory.dose_eval.comprehensive_dose_evaluation import ComprehensiveDoseEvaluationTool
    from plans.dose_pre.model_loader import resolve_prescription_gy
    from utils.ctv_targets import label_array
    total_record = bundle["total"]
    dose = physical_volume(total_record["dose_distribution_physical_gy"], units=total_record["dose_units"])
    if total_record.get("grid_signature") != grid_signature(image) or dose.shape != tuple(image.GetSize()[::-1]):
        raise ValueError("Total dose does not belong to the current physical CT grid")
    if total_record.get("dose_sha256") != fingerprint(dose):
        raise ValueError("Total dose content changed before evaluation")
    if ctv is None or oar is None:
        raise ValueError("Current-image CTV and OAR are required for total-dose quality evaluation")
    ctv = label_array(ctv, shape=dose.shape)
    if not np.isin(ctv, (0, 1)).all():
        raise ValueError("Total-dose evaluation requires the complete binary CTV union")
    target = np.asarray(ctv) == 1
    if target.shape != dose.shape or not target.any():
        raise ValueError("Current-image complete CTV is required for total-dose evaluation")
    masks, types = {"CTV": target}, {"CTV": "target"}
    if oar is not None:
        organs = label_array(oar, shape=dose.shape)
        if organs.shape != dose.shape:
            raise ValueError("Current-image OAR differs from the dose grid")
        for label in np.unique(organs):
            if label <= 0:
                continue
            name = str((organ_names or {}).get(int(label), (organ_names or {}).get(str(int(label)), "OAR_" + str(int(label)))))
            if name in masks:
                name = name + ":" + str(int(label))
            masks[name], types[name] = organs == label, "oar"
    config = copy.deepcopy(plan_config or {})
    result = ComprehensiveDoseEvaluationTool()._execute(dose_array=dose, masks=masks,
        spacing=image.GetSpacing(), prescribed_dose=resolve_prescription_gy(config),
        vx_values=[100, 150, 200, 90, 50], dx_values=[98, 95, 90, 50, 2], cc_values=[2, 1, 0.1],
        structure_type=types, tumor_type=config.get("tumor_type", ""),
        oar_constraints=config.get("oar_constraints") or {})
    if not result.success:
        raise ValueError(result.error)
    return {**result.metadata, "source_set": "total", "dose_units": "physical_gy",
            "total_dose_sha256": bundle["total"]["dose_sha256"]}


def total_evaluation_updates(bundle, retrieve, image, plan, resources, scale):
    """Dose remains usable without anatomy; unavailable quality is never current."""
    from utils.ctv_targets import resolve_ctv_target
    empty = {"total_dose_evaluation": None, "dose_metrics": None, "metrics": None, "dvh_data": None,
             "current_dose_evaluation_config": None}
    try:
        ctv = resolve_ctv_target(retrieve)
        oar = retrieve("oar_array")
        if ctv is None or oar is None:
            return empty, False
        old = retrieve("total_dose_evaluation")
        reused = (isinstance(old, Mapping) and old.get("dependency_fingerprint") == resources["metrics"]
                  and old.get("total_dose_sha256") == bundle["total"]["dose_sha256"])
        evaluation = old if reused else evaluate_total(bundle, ctv, oar, image, plan,
            organ_names=retrieve("organ_names"))
    except (ValueError, TypeError):
        return empty, False
    evaluation = {**evaluation, "dependency_fingerprint": resources["metrics"]}
    target = evaluation["metrics"]["CTV"]
    metrics = {k.lower(): v for k, v in target.items() if k != "dvh"}
    dvh = {name: row["dvh"] for name, row in evaluation["metrics"].items() if "dvh" in row}
    metrics.update(source_set="total", dose_value_unit="gy", dose_scale_gy=scale,
        prescription_gy=evaluation["prescribed_dose"], prescribed_dose=evaluation["prescribed_dose"],
        volume_metric_units="fraction", plan_score=evaluation["plan_score"], dvh_data=dvh,
        oar_metrics={name: {k.lower(): v for k, v in row.items() if k != "dvh"}
                     for name, row in evaluation["metrics"].items() if name != "CTV"})
    return {"total_dose_evaluation": evaluation, "dose_metrics": metrics, "metrics": metrics, "dvh_data": dvh,
            "current_dose_evaluation_config": copy.deepcopy(plan or {})}, reused


def recompute_timepoint_dose(agent, *, source_set="total", planning_id=None,
                            expected_revision_id=None, model=None):
    """Dose-only executor for current CT sources with dependency-based reuse.

    The temporary memory holds both computations until successful publication.
    A stale unselected component cannot become current total-dose authority.
    HTTP and chat callers must bind the Agent to their captured timepoint first.
    """
    from contextlib import nullcontext
    from pathlib import Path
    from types import SimpleNamespace
    from tool_factory import ToolResult
    from tool_factory.dose_recompute import _ensure_ct_runtime
    from tool_factory.seed_plan import model_support
    from tool_factory.seed_seg.seedfinder_adapter import sha256_file
    from plans.dose_pre.model_loader import resolve_dose_model_path
    from utils.cancellation import raise_if_cancelled, is_cancelled
    from utils.dose_units import calibrated_scale
    from utils.ctv_targets import resolve_ctv_target
    from web.timepoint_resources import capture_resources, component_current, resource_state
    from web.implant_workspace import implant_publication_guard
    from web.planning_runs import active_planning_id
    from web.routes.planning_routes import _current_planning_snapshot
    from web.implanted_dose import recompute_implanted_dose
    from web.timepoints import default_timepoint_id
    from web.timepoint_messages import resolve_timepoint_language, timepoint_message
    language = resolve_timepoint_language(agent=agent)

    if source_set not in {"planned", "both", "total"}:
        packet = timepoint_message('dose_source_set_invalid',language)
        return ToolResult(False,error=packet['message'],metadata=packet)
    try:
        _ensure_ct_runtime(agent)
        memory = agent.memory
        current_id = active_planning_id(memory)
        if planning_id and str(planning_id) != str(current_id or ""):
            raise ValueError("The requested Planning is not active in this captured timepoint")
        config = agent.config
        store = agent._workspace_store
        owner, session = config["_workspace_owner_id"], config["_workspace_session_id"]
        target_id = config.get("_workspace_timepoint_id") or default_timepoint_id(session)
        context = store.capture_timepoint_context(owner, session, target_id)
        previous_state = memory.retrieve("timepoint_resource_state")
        # Shallow arrays are immutable inputs here; writes use a private mapping.
        view = copy.copy(agent)
        from agent_runtime.core import AgentMemory
        view.memory = AgentMemory(session)
        view.memory.planning_results = dict(memory.planning_results)
        view.memory._planning_versions = dict(getattr(memory, "_planning_versions", {}))
        view.memory.user_lang = memory.user_lang
        view.memory.set_ui_state(memory.get_ui_state())
        view._workspace_scoped_chat_runtime = SimpleNamespace(dose_only=True)
        retrieve = view.memory.retrieve
        image = retrieve("ct_image")
        catalog = retrieve("implanted_seed_reconstruction") or {}
        reconstruction = ((catalog.get("by_timepoint", {}).get(target_id) or {}).get("current") or {}).get("reconstruction")
        if reconstruction is None and context.target.stage == "intraoperative":
            raise ValueError("Current intraoperative observations, including an explicitly empty scan, are required")
        if source_set in {"both", "total"} and reconstruction is not None:
            result = recompute_implanted_dose(view, expected_revision_id=expected_revision_id, model=model)
            if not result.success:
                return result
            catalog = retrieve("implanted_seed_reconstruction") or {}
            reconstruction = ((catalog.get("by_timepoint", {}).get(target_id) or {}).get("current") or {}).get("reconstruction")
        plan = retrieve("plan_config") or {}
        profile = retrieve("implant_dose_profile") or {}
        seed_info = profile.get("seed_info") or retrieve("continuation_input_seed_info") or plan.get("seed_info")
        if not isinstance(seed_info, Mapping) or any(not np.isfinite(float(seed_info.get(k, 0)))
                or float(seed_info.get(k, 0)) <= 0 for k in ("length", "radius")):
            raise ValueError("Current source dimensions must be confirmed before dose recomputation")
        scale = calibrated_scale(profile, retrieve("continuation_source_contract"), plan,
            retrieve("dose_metrics"), explicit=retrieve("dose_scale_gy"))
        dl = dict(retrieve("continuation_dl_params") or plan.get("dl_params") or config.get("dl_params") or {})
        path = resolve_dose_model_path(retrieve("continuation_dose_model_path") or dl.get("dose_model_path"))
        if path is None:
            raise ValueError("The current calibrated CNN checkpoint is unavailable")
        checkpoint_sha = sha256_file(path)
        contract = retrieve("continuation_source_contract") or {}
        confirmed_sha = profile.get("dose_model_sha256") or contract.get("dose_model_sha256")
        if confirmed_sha and confirmed_sha != checkpoint_sha:
            raise ValueError("The CNN checkpoint differs from the confirmed source profile")
        dl["dose_model_path"] = str(path)
        snapshot = _current_planning_snapshot(view)
        sources = clinical_sources(snapshot.get("seeds") or ())
        resources = capture_resources(retrieve, image, reconstruction=reconstruction, planned_sources=sources,
            source={"profile": profile, "contract": contract or None, "dose_scale_gy": scale},
            model_sha256=checkpoint_sha, dl_params=dl, seed_info=seed_info)
        cached = retrieve("dose_components") or {}
        implanted = retrieve("implanted_dose_record") or cached.get("implanted")
        if reconstruction is None:
            implanted = dose_component("implanted", np.zeros(image.GetSize()[::-1], np.float32), image,
                units="physical_gy", scale=scale, resources=resources, dose_status="zero_no_implant", clinical_use_ready=False)
        implanted_ready = component_current(implanted, "implanted", resources, image)
        planned = cached.get("planned")
        planned_reused = component_current(planned, "planned", resources, image)
        if not planned_reused:
            if sources:
                from plans.device_manager import device_session
                from web.implant_service import _default_device_lock
                configured = str(dl.get("device") or "auto")
                preferred = configured if configured in {"cpu", "auto"} else configured.split(":")[-1]
                with (device_session(caller="component-dose:" + target_id, prefer=preferred)
                        if model is None else nullcontext(None)) as lease:
                    device = lease.device_str if lease is not None else configured
                    dl["device"] = device
                    with (_default_device_lock(device, cancelled=is_cancelled, deadline=None)
                            if lease is not None else nullcontext()):
                        if model is None:
                            model, error = model_support.resolve_dose_model({}, dl)
                            if model is None:
                                raise ValueError(error or "The CNN is unavailable")
                        normalized, _ = model_support.compute_world_seed_dose_grid(sources, image, model, dl, seed_info, strict=True)
            else:
                normalized = np.zeros(image.GetSize()[::-1], np.float32)
            planned = dose_component("planned", normalized, image, units="normalized_model", scale=scale,
                resources=resources, sources=sources, planning_id=current_id,
                supplemental_only=context.target.stage == "intraoperative", clinical_use_ready=False)
        updates = {"dose_components": {"schema_version": 1, "implanted": implanted, "planned": planned,
                                      "total": None, "evaluation_source_set": "total"},
                   "dose_unit_metadata": dict(DOSE_UNIT_METADATA)}
        ready = ["planned_dose"]
        evaluation = None
        evaluation_reused = False
        if implanted_ready:
            bundle = component_bundle(implanted, planned, resources)
            updates["dose_components"] = bundle
            ready.extend(["implanted_dose", "total_dose"])
            from web.planning_config import current_evaluation_config
            evaluation_updates, evaluation_reused = total_evaluation_updates(
                bundle, retrieve, image, current_evaluation_config(retrieve), resources, scale)
            evaluation = evaluation_updates['total_dose_evaluation']
            total_physical = bundle["total"]["dose_distribution_physical_gy"]
            normalized = total_physical / scale
            planning_image = retrieve("resampled_ct")
            if planning_image is None or not hasattr(planning_image, "GetSize"):
                planning_image = image
            updates.update(implanted_dose_record=implanted,
                dose_distribution_physical_gy=total_physical, dose_distribution_gy=total_physical,
                dose_distribution_current_normalized=normalized, dose_unit_schema_version=2,
                dose_distribution=resample_dose(normalized, image, planning_image),
                additional_dose_distribution=resample_dose(planned["dose_distribution_physical_gy"] / scale, image, planning_image),
                dose_units="normalized_model_output", dose_scale_gy=scale)
            updates.update(evaluation_updates)
            if evaluation is not None:ready.append("metrics")
        elif source_set in {"both", "total"}:
            raise ValueError("Implanted dose is stale; total dose and quality were not published")
        else:
            # Planned-only refresh is useful, but cannot leave stale total quality
            # in the current aliases while the other component needs correction.
            updates.update(dose_distribution=None, dose_distribution_gy=None, dose_distribution_physical_gy=None,
                           dose_distribution_current_normalized=None,
                           dose_metrics=None, metrics=None, dvh_data=None, total_dose_evaluation=None)
        state = resource_state(previous_state, resources, ready=ready)
        artifact_status = dict(retrieve("manual_artifact_status") or {})
        artifact_status.update(dose="ready" if implanted_ready else "stale", dvh="ready" if evaluation else "stale",
                               quality_check='ready' if evaluation else 'stale')
        if "report" in state["invalidated"]:
            artifact_status["report"] = "stale"
        if "manufactured_guide" in state["invalidated"]:
            artifact_status["surgical_guide"] = "stale"
        updates.update(timepoint_resource_state=state, manual_artifact_status=artifact_status,
            artifact_status=artifact_status, report_status="stale" if artifact_status.get('report') == 'stale' else retrieve('report_status'))
        raise_if_cancelled()
        if sha256_file(path) != checkpoint_sha:
            raise ValueError("CNN checkpoint changed during dose computation")
        latest = capture_resources(memory.retrieve, memory.retrieve("ct_image"), reconstruction=reconstruction,
            planned_sources=clinical_sources(_current_planning_snapshot(agent).get("seeds") or ()),
            source={"profile": memory.retrieve("implant_dose_profile") or {},
                    "contract": memory.retrieve("continuation_source_contract"), "dose_scale_gy": scale},
            model_sha256=checkpoint_sha, dl_params=dl, seed_info=seed_info)
        if resources != latest:
            raise ValueError("Clinical inputs changed during dose recomputation")
        with implant_publication_guard(agent, updates):
            if getattr(agent, "_workspace_scoped_chat_runtime", None) is None:
                if context.target.legacy_default:
                    saved = store.load_timepoint_snapshot(owner, session, target_id)
                    store.save_agent_results_delta(owner, session, updates,
                        expected_revision=saved["timepoint_state_revision"], reason="dose.components.recompute")
                else:
                    store.save_timepoint_results(owner, session, target_id, updates,
                        expected_clinical_revision=context.target.clinical_revision, execution_context=context)
            for key, value in updates.items():
                memory.store(key, value)
        return ToolResult(True, data={"source_set": source_set, "planning_id": current_id,
            "metrics": updates.get("dose_metrics") or {}, "dvh_data": updates.get("dvh_data") or {}},
            message=timepoint_message('component_dose_recomputed',language)['message'],
            metadata={"source_set": source_set, "timepoint_id": target_id, "planning_id": current_id,
                "total_seeds": len(sources), "implanted_seed_count": implanted.get("source_count", 0) if implanted else 0,
                "dose_units": "physical_gy", "dose_scale_gy": scale,
                "reused_components": [name for name, reused in (("implanted", implanted_ready and implanted.get("reused", False)),
                    ("planned", planned_reused), ("metrics", evaluation_reused)) if reused],
                "total_available": implanted_ready, "metrics": updates.get("dose_metrics") or {},
                "artifact_status": artifact_status, "invalidated_resources": state["invalidated"],
                "clinical_use_ready": False, "downstream_actions_executed": []})
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning('Component-dose recomputation failed: %s',type(exc).__name__,exc_info=True)
        packet = timepoint_message('component_dose_recompute_failed',language)
        return ToolResult(False,error=packet['message'],metadata={**packet,'source_set':source_set,'downstream_actions_executed':[]})
