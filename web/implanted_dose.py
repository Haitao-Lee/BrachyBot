"""CNN dose for the edited observed source set only; never supplemental planning."""
from dataclasses import asdict
from contextlib import nullcontext
import copy
import math

import numpy as np
import SimpleITK as sitk
from tool_factory import ToolResult
from utils.implant_reconstruction import SeedAxisReconstruction, SeedDetection
from web.implant_workspace import ImplantWorkspace
from web.implant_service import ImplantServiceError
from web.workspace_store import WorkspaceError
from web.timepoints import TimepointError


def _dose_settings(values):
    """Small source contract, excluding unrelated metrics and volume arrays."""
    result={key:copy.deepcopy(values.get(key)) for key in ('implant_dose_profile',
        'continuation_input_seed_info','continuation_source_contract','continuation_dl_params',
        'continuation_dose_model_path','dose_scale_gy')}
    calibration_keys=('dose_scale_gy','dose_model_scale_gy','dose_calibration')
    for key,fields in (('dose_metrics',calibration_keys),
                       ('plan_config',calibration_keys+('seed_info','dl_params'))):
        record=values.get(key) or {}
        result[key]={field:copy.deepcopy(record[field]) for field in fields if field in record}
    return result


def recompute_implanted_dose(agent, *, expected_revision_id=None, model=None, orientation_provider=None):
    from plans.dose_pre.model_loader import resolve_dose_model_path
    from tool_factory.seed_plan import model_support
    from tool_factory.seed_seg.seedfinder_adapter import SeedFinderModelContract, sha256_file
    from tool_factory.seed_seg.supplied_orientation import SuppliedXYOrientationProvider
    from utils.ct_volume import normalize_ct_image
    from utils.dose_units import calibrated_scale, physical_volume
    from utils.cancellation import raise_if_cancelled
    from web.timepoint_messages import timepoint_message
    from web.timepoints import default_timepoint_id
    language=(getattr(agent,"_active_turn_context",None) or {}).get("ui_language") or agent.memory.user_lang
    try:
        config=agent.config
        store=agent._workspace_store
        target=config.get("_workspace_timepoint_id") or default_timepoint_id(config["_workspace_session_id"])
        workspace=ImplantWorkspace(store,config["_workspace_owner_id"],config["_workspace_session_id"],target,agent=agent)
        receipt=workspace.service.get()
        reconstruction=SeedAxisReconstruction.from_dict(receipt["record"]["reconstruction"])
        if expected_revision_id is not None and expected_revision_id.replace('-','')!=reconstruction.revision_id.replace('-',''):
            raise ImplantServiceError("implant_revision_conflict","The requested observations are no longer current")
        source=workspace.input()
        if source.image_ref!=reconstruction.image_ref:
            raise ImplantServiceError("implant_input_changed","The current image differs from observation input")
        values=agent.memory.planning_results
        saved=store.load_timepoint_snapshot(config['_workspace_owner_id'],config['_workspace_session_id'],target) if hasattr(store,'load_timepoint_snapshot') else {}
        saved_values=saved.get('agent',{}).get('planning_results') or {}
        saved_fence=_dose_settings(saved_values)
        memory_fence=_dose_settings(values)
        inputs={key:copy.deepcopy(saved_fence[key] if key in saved_values else memory_fence[key]) for key in memory_fence}
        current_plan=inputs.get("plan_config") or {}
        profile=inputs.get('implant_dose_profile') or {}
        seed_info=profile.get('seed_info') or inputs.get("continuation_input_seed_info") or current_plan.get("seed_info")
        if not isinstance(seed_info,dict) or any(not isinstance(seed_info.get(key),(int,float)) or isinstance(seed_info[key],bool)
                or not math.isfinite(seed_info[key]) or seed_info[key]<=0 for key in ("length","radius")):
            raise ImplantServiceError("implant_source_parameters_required","Confirm current source dimensions before CNN dose")
        scale=calibrated_scale(profile,inputs.get("continuation_source_contract"), current_plan,inputs.get("dose_metrics"),explicit=inputs.get("dose_scale_gy"))
        dl=copy.deepcopy(inputs.get("continuation_dl_params") or current_plan.get("dl_params") or config.get("dl_params") or {})
        checkpoint=resolve_dose_model_path(inputs.get("continuation_dose_model_path") or dl.get("dose_model_path"))
        if checkpoint is None:
            raise ImplantServiceError("implant_dose_model_unavailable","The CNN checkpoint is unavailable")
        checkpoint_sha=sha256_file(checkpoint)
        if profile.get('dose_model_sha256') and profile['dose_model_sha256']!=checkpoint_sha:
            raise ImplantServiceError('implant_source_parameters_required','The confirmed dose model changed')
        dl["dose_model_path"]=str(checkpoint)
        observations=[item for item in reconstruction.observations if item.review_status!='rejected']
        original=sitk.ReadImage(source.ct_path)
        ct,_=normalize_ct_image(original);ct=sitk.DICOMOrient(ct,"LPI")
        from web.timepoint_resources import capture_resources, component_current, resource_state
        from web.dose_components import dose_component
        from web.timepoint_resources import clinical_sources
        planned_sources = values.get('manual_seeds') if values.get('manual_plan_active') else (values.get('algorithm_plan_snapshot') or {}).get('seeds')
        planned_sources = planned_sources or []
        valid_planned_sources = True
        try:
            planned_sources = clinical_sources(planned_sources)
        except ValueError:
            # An implanted-only request does not require a usable future plan.
            # It must still leave the malformed planned/total resource unavailable.
            planned_sources = []
            valid_planned_sources = False
        resources=capture_resources(values.get,ct,reconstruction=reconstruction,planned_sources=planned_sources,
            source={'profile':profile,'contract':inputs.get('continuation_source_contract'),'dose_scale_gy':scale},
            model_sha256=checkpoint_sha,dl_params=dl,seed_info=seed_info)
        cached=values.get('implanted_dose_record') or saved_values.get('implanted_dose_record')
        reused=component_current(cached,'implanted',resources,ct)
        estimates={}
        if not reused and any(item.axis_lps is None for item in observations):
            if orientation_provider is None:
                runtime=workspace.service._config();runtime.validate_available()
                orientation_provider=SuppliedXYOrientationProvider(SeedFinderModelContract.for_supplied_bundle(runtime.bundle_dir))
            estimated=orientation_provider.estimate_seed_axes(source.image_ref,original,
                tuple(SeedDetection(item.detection_id,item.center_lps_mm) for item in observations))
            estimates={item.detection_id:item for item in estimated.observations}
        seeds=copy.deepcopy(cached['source_geometry']) if reused else []
        estimated_count=cached.get('estimated_axis_count',0) if reused else 0
        for item in (() if reused else observations):
            axis=item.axis_lps
            if axis is not None and item.axis_source not in {'local_pca','reviewed_axis'}:estimated_count+=1
            if axis is None:
                axis=estimates.get(item.detection_id).axis_lps if estimates.get(item.detection_id) is not None else None
                estimated_count+=1
            if axis is None:
                raise ImplantServiceError("implant_axis_unavailable","A current source axis cannot be estimated")
            seeds.append({"id":item.physical_seed_id or 'observed:'+item.observation_id,
                "position":list(item.center_lps_mm),"direction":list(axis)})
        # Same authoritative DoseUNet world-space aggregation; no radiating
        # volume modification, needle optimizer, guide or report is invoked.
        raise_if_cancelled()
        if reused:
            physical=np.array(cached['dose_distribution_physical_gy'],copy=True)
        elif seeds:
            from plans.device_manager import device_session
            from web.implant_service import _default_device_lock
            from utils.cancellation import is_cancelled
            configured=str(dl.get('device') or 'auto')
            preferred=configured if configured in {'auto','cpu'} else configured.split(':')[-1]
            with (device_session(caller='implanted-dose:'+target,prefer=preferred) if model is None else nullcontext(None)) as lease:
                device=lease.device_str if lease is not None else configured
                dl['device']=device
                with (_default_device_lock(device,cancelled=is_cancelled,deadline=None) if lease is not None else nullcontext()):
                    if model is None:
                        model,error=model_support.resolve_dose_model({},dl)
                        if model is None:raise ImplantServiceError("implant_dose_model_unavailable",error or 'No CNN model')
                    dose,accepted=model_support.compute_world_seed_dose_grid(seeds,ct,model,dl,seed_info,strict=True)
        else:
            dose=np.zeros(ct.GetSize()[::-1],np.float32);accepted=[]
        if not reused:physical=physical_volume(dose,units='normalized_model',scale=scale)
        raise_if_cancelled()
        if sha256_file(checkpoint)!=checkpoint_sha or not workspace.image_current(source.image_ref):
            raise ImplantServiceError("implant_input_changed","Dose source/checkpoint changed during computation")
        if hasattr(store,'load_timepoint_snapshot'):
            latest=store.load_timepoint_snapshot(config['_workspace_owner_id'],config['_workspace_session_id'],target)
            latest_profile=(latest.get('agent',{}).get('planning_results') or {}).get('implant_dose_profile') or {}
            if latest_profile!=profile:
                raise ImplantServiceError('implant_source_parameters_required','Source settings changed during dose computation')
        # Exact observation-head check protects correction during a long CNN call.
        with workspace.service._journal() as index, store._case_guard(workspace.owner,workspace.session):
            head=workspace.service._load_record(index['current'])['reconstruction']['revision_id']
            if head.replace('-','')!=reconstruction.revision_id.replace('-',''):
                raise ImplantServiceError("implant_revision_conflict","Observations changed during dose computation")
            # Recheck the source settings inside the publication transaction.
            # A successful CNN call is not authority to restore older settings.
            current_state=store.load_timepoint_snapshot(workspace.owner,workspace.session,target)
            current_values=current_state.get('agent',{}).get('planning_results') or {}
            current_profile=current_values.get('implant_dose_profile') or {}
            if (current_profile!=profile or _dose_settings(current_values)!=saved_fence
                    or _dose_settings(values)!=memory_fence or not workspace.image_current(source.image_ref)):
                raise ImplantServiceError('implant_input_changed','Dose inputs changed before publication')
            record=dose_component('implanted',physical,ct,units='physical_gy',scale=scale,
                resources=resources,sources=seeds,**{"observation_revision_id":reconstruction.revision_id,"timepoint_id":target,
                "image_sha256":source.image_ref.image_sha256,
                "dose_model_sha256":checkpoint_sha,
                "source_count":len(seeds),"estimated_axis_count":estimated_count,
                "dose_basis":"projected_total_source_dose_not_elapsed_delivered_dose",
                "geometry":asdict(source.image_ref.geometry),"ct_spacing":list(ct.GetSpacing()),
                "ct_origin":list(ct.GetOrigin()),"ct_direction":list(ct.GetDirection()),
                "dose_shape":list(physical.shape),"dose_distribution_physical_gy":physical,
                "execution_device":dl.get('device','not_used_zero_sources'),
                "dose_min_gy":float(physical.min()),"dose_max_gy":float(physical.max()),
                "dose_status":"provisional_observation_dose","clinical_use_ready":False,
                "seed_info":copy.deepcopy(seed_info),"source_parameter_origin":"current_timepoint_saved_source_settings",
                "reused":reused})
            record['dose_profile']=copy.deepcopy(profile)
            components=copy.copy(values.get('dose_components') or {})
            components.update(schema_version=1,implanted=record,evaluation_source_set='total')
            if not reused:components['total']=None
            updates={"implanted_dose_record":record,"dose_components":components,
                "timepoint_resource_state":resource_state(values.get('timepoint_resource_state'),resources,ready=('implanted_dose',))}
            planned = components.get('planned')
            if valid_planned_sources and component_current(planned, 'planned', resources, ct):
                from web.dose_components import component_bundle, total_evaluation_updates, DOSE_UNIT_METADATA
                bundle = component_bundle(record, planned, resources)
                updates['dose_components'] = bundle
                total = bundle['total']['dose_distribution_physical_gy']
                updates.update(dose_distribution_physical_gy=total, dose_distribution_gy=total,
                    dose_distribution_current_normalized=total / scale,
                    dose_unit_schema_version=2, dose_unit_metadata=dict(DOSE_UNIT_METADATA))
                updates['timepoint_resource_state']['ready'].extend(['planned_dose', 'total_dose'])
                from web.planning_config import current_evaluation_config
                quality_updates,_=total_evaluation_updates(bundle,values.get,ct,
                    current_evaluation_config(values.get),resources,scale)
                updates.update(quality_updates)
                from web.dose_components import resample_dose
                planning_image=values.get('resampled_ct')
                if planning_image is None or not hasattr(planning_image,'GetSize'):planning_image=ct
                updates['dose_distribution']=resample_dose(total / scale,ct,planning_image)
                updates['additional_dose_distribution']=resample_dose(planned['dose_distribution_physical_gy'] / scale,ct,planning_image)
            else:
                # Do not retain an old summed field after this component changed.
                for key in ('dose_distribution', 'dose_distribution_gy', 'dose_distribution_physical_gy',
                            'dose_distribution_current_normalized', 'dose_metrics', 'metrics', 'dvh_data', 'total_dose_evaluation'):
                    if key in values:
                        updates[key] = None
                components['total']=None
            status=copy.deepcopy(values.get('artifact_status') or values.get('manual_artifact_status') or {})
            total_ready=updates['dose_components'].get('total') is not None
            status.update(dose='ready' if total_ready else 'stale',
                dvh='ready' if updates.get('total_dose_evaluation') is not None else 'stale',
                quality_check='ready' if updates.get('total_dose_evaluation') is not None else 'stale')
            if 'report' in updates['timepoint_resource_state']['invalidated'] or not total_ready:
                status['report']='stale';updates['report_status']='stale'
            updates.update(artifact_status=status,manual_artifact_status=status)
            if getattr(agent,"_workspace_scoped_chat_runtime",None) is None:
                if workspace.context.target.legacy_default:
                    # Encode only this numerical result; a full Agent snapshot
                    # could copy stale future-plan aliases over newer state.
                    store.save_agent_results_delta(workspace.owner,workspace.session,updates,
                        expected_revision=current_state['timepoint_state_revision'],reason='implant.dose.recompute')
                else:
                    store.save_timepoint_results(workspace.owner,workspace.session,target,updates,
                        expected_clinical_revision=workspace.context.target.clinical_revision,execution_context=workspace.context)
            for key,value in updates.items():agent.memory.store(key,value)
        message=timepoint_message("implant_dose_recomputed",language)["message"]
        return ToolResult(True,message=message,metadata={"source_set":"implanted","timepoint_id":target,
            "observation_revision_id":reconstruction.revision_id,"total_seeds":len(seeds),
            "estimated_axis_count":estimated_count,"dose_min_gy":record['dose_min_gy'],"dose_max_gy":record['dose_max_gy'],
            "dose_basis":record['dose_basis'],"clinical_use_ready":False,
            "reused":reused,"invalidated_resources":updates['timepoint_resource_state']['invalidated'],
            "downstream_actions_executed":[],"implant_command":{"action":"dose_ready","session_id":workspace.session,
                "timepoint_id":target,"observation_revision_id":reconstruction.revision_id}})
    except (ImplantServiceError,WorkspaceError,TimepointError,ValueError,OSError) as exc:
        packet=timepoint_message(getattr(exc,'code','implant_dose_inputs_invalid'),language)
        return ToolResult(False,error=packet['message'],metadata={**packet,"source_set":"implanted","downstream_actions_executed":[]})
