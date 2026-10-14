"""Real staged continuation prerequisites, never zero-based intraoperative fallback."""
from dataclasses import asdict
import uuid

from tool_factory import ToolResult
from web.implant_workspace import ImplantWorkspace
from web.implant_service import ImplantServiceError
from web.timepoint_messages import timepoint_message


def ensure_intraoperative_baseline(agent, *, planning_config=None):
    """Return an actionable pause or prepare the current reviewed CNN baseline.

    Called after the ordinary current-image CTV/OAR prerequisite loaders. The
    detector's immutable journal may commit before a pause; no planning result
    is claimed. Human source/coverage/pose review is never supplied by the LLM.
    """
    captured = getattr(agent, "_workspace_timepoint_context", None)
    if captured is None or captured.target.stage != "intraoperative":
        return None
    if not associated_preoperative_plan_exists(agent,captured):
        locale=(getattr(agent,'_active_turn_context',None) or {}).get('ui_language') or agent.memory.user_lang
        message=timepoint_message('continuation_preoperative_plan_required',locale)['message']
        return ToolResult(False,error=message,message=message,metadata={
            'code':'continuation_preoperative_plan_required','phase':'awaiting_preoperative_plan',
            'timepoint_id':captured.target.timepoint_id,'planning_completed':False,
            'downstream_actions_executed':[]})
    from tool_factory.seed_plan.continuation_support import resolve_baseline
    from web.guide_service import GuidePlacementService
    raw=getattr(agent._workspace_store,'raw',agent._workspace_store)
    source_snapshot=raw.load_timepoint_snapshot(captured.owner_id,captured.session_id,
        captured.target.preoperative_timepoint_id,decode_arrays=False)
    current_source_has_guide=bool(GuidePlacementService.guide_records(source_snapshot))
    try:
        baseline = resolve_baseline(agent, current_image=agent.memory.retrieve("ct_image"))
        requirement = agent.memory.retrieve("continuation_guide_requirement") or {}
        if baseline is not None:
            from tool_factory.seed_plan.continuation_support import baseline_reaches_target
            if baseline_reaches_target(baseline, planning_config or agent.config):
                return None
            if not current_source_has_guide and not requirement.get('manufactured_guide_present'):return None
            if current_source_has_guide and requirement.get('placement_prepared'):
                placement=agent.memory.retrieve('guide_placement') or {}
                version=(placement.get('qc') or {}).get('service_scope',{}).get('guide_version')
                from web.guide_placement import GuidePlacementError
                try:
                    GuidePlacementService(agent).validate(source_timepoint_id=captured.target.preoperative_timepoint_id,
                        target_timepoint_id=captured.target.timepoint_id,guide_version=version,
                        placement_id=placement.get('placement_id'))
                except GuidePlacementError:return guide_review_pause(agent,captured.target.timepoint_id)
                return None
    except ValueError:
        pass  # Rebuild only from current authoritative inputs below.
    config = agent.config
    raw = getattr(agent._workspace_store, "raw", agent._workspace_store)
    owner, sid, target = captured.owner_id, captured.session_id, captured.target.timepoint_id
    locale = (getattr(agent, "_active_turn_context", None) or {}).get("ui_language") or agent.memory.user_lang
    workspace = ImplantWorkspace(raw, owner, sid, target)
    try:
        receipt = workspace.service.get()
    except ImplantServiceError as exc:
        if exc.code != "implant_reconstruction_not_found":
            raise
        # A stable operation/source-derived key makes retries idempotent but
        # never identifies two different CT acquisitions as the same request.
        source = workspace.input()
        request_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
            f"brachybot:plan-detect:{sid}:{target}:{source.image_ref.image_sha256}"))
        workspace.detect(request_id)
        receipt = workspace.service.get()
        saved = raw.load_timepoint_snapshot(owner, sid, target, decode_arrays=True)
        runtime = getattr(agent, "_workspace_scoped_chat_runtime", None)
        if runtime is not None:
            runtime.accept_external_patch(saved, saved["agent"]["planning_results"], ())
        else:
            for key, value in saved["agent"]["planning_results"].items():
                agent.memory.store(key, value)
    view = workspace.view()
    if not view["dose_input_ready"]:
        message = timepoint_message("implant_review_required", locale)["message"]
        return ToolResult(False, error=message, message=message,
            metadata={"code": "implant_review_required", "phase": "awaiting_observation_review",
                "requires_human_review": True, "planning_completed": False, "implant_view": view,
                "implant_command": {"action": "display", "session_id": sid, "timepoint_id": target},
                "timepoint_id": target, "downstream_actions_executed": []})
    profile = agent.memory.retrieve("implant_dose_profile") or {}
    if not profile.get("confirmation_id"):
        message = timepoint_message("implant_source_parameters_required", locale)["message"]
        return ToolResult(False, error=message, metadata={"code": "implant_source_parameters_required",
            "phase": "awaiting_source_settings", "timepoint_id": target, "planning_completed": False})
    needle_values = agent.memory.retrieve("continuation_review_profile")
    if not needle_values:
        message = timepoint_message("continuation_profile_required", locale)["message"]
        return ToolResult(False, error=message, message=message, metadata={"code": "continuation_profile_required",
            "phase": "awaiting_continuation_settings", "timepoint_id": target, "planning_completed": False})
    from web.continuation_service import ContinuationPreparationService, ContinuationSourceContract
    from web.guide_placement import BoreValidationProfile
    from web.guide_service import GuidePlacementService
    from plans.dose_pre.model_loader import resolve_dose_model_path
    source = ContinuationSourceContract(contract_id=profile["confirmation_id"], source_model_id=profile["source_model_id"],
        source_strength_u=None, source_strength_basis="model_nominal_relative", dose_scale_gy=profile["dose_scale_gy"],
        dose_model_sha256=profile["dose_model_sha256"], reviewer_id=profile["confirmed_by"],
        review_evidence=profile["confirmation_scope"], capsule_length_mm=profile["seed_info"]["length"],
        capsule_diameter_mm=2 * profile["seed_info"]["radius"])
    needle = BoreValidationProfile(**{key: needle_values[key] for key in (
        "profile_id", "needle_radius_mm", "minimum_guiding_length_mm", "obstacle_clearance_mm", "maximum_depth_mm")})
    placement = agent.memory.retrieve("guide_placement")
    guide = None
    helper = GuidePlacementService(agent)
    if placement and placement.get("review_state") == "accepted":
        version = (placement.get("qc") or {}).get("service_scope", {}).get("guide_version") or placement.get("guide_version")
        from web.guide_placement import GuidePlacementError
        try:
            helper.validate(source_timepoint_id=captured.target.preoperative_timepoint_id,target_timepoint_id=target,
                guide_version=version,placement_id=placement.get('placement_id'))
        except GuidePlacementError:return guide_review_pause(agent,target)
        _, _, guide = helper._source_target(captured.target.preoperative_timepoint_id, target, version)
    from plans.continuation import FixedNeedle
    in_situ=[]
    for row in agent.memory.retrieve('in_situ_needles') or ():
        if isinstance(row,FixedNeedle):in_situ.append(row)
        elif isinstance(row,dict):in_situ.append(FixedNeedle(**row))
        else:raise ValueError('Saved in-situ needle geometry is invalid; no obstacles were omitted')
    channel_states=agent.memory.retrieve('guide_channel_states')
    prepared = ContinuationPreparationService(agent).prepare(target_timepoint_id=target,
        observation_revision_id=receipt["record"]["reconstruction"]["revision_id"], source_contract=source,
        needle_profile=needle, dose_model_path=str(resolve_dose_model_path()), guide=guide,
        accepted_placement=placement if guide is not None else None,
        in_situ_needles=tuple(in_situ),channel_states=channel_states,
        target_image=helper._target_image(raw.load_timepoint_snapshot(owner, sid, target)) if guide is not None else None,
        dl_params=config.get("dl_params") or {})
    requirement = agent.memory.retrieve("continuation_guide_requirement") or {}
    if requirement.get("manufactured_guide_present") and not requirement.get("placement_prepared"):
        from tool_factory.seed_plan.continuation_support import baseline_reaches_target
        if not baseline_reaches_target(prepared["baseline"], planning_config or config):
            message = timepoint_message("continuation_guide_review_required", locale)["message"]
            return ToolResult(False, error=message, message=message, metadata={"code": "continuation_guide_review_required",
                "phase": "awaiting_guide_pose_review", "requires_human_review": True,
                "planning_completed": False, "timepoint_id": target, "existing_dose_computed": True})
    return None


def associated_preoperative_plan_exists(agent,captured):
    """Association is not evidence that the linked preoperative plan exists.

    Read saved, owned geometry/count metadata only; never run or invent a
    preoperative plan, borrow its dose, or compare its count with observations.
    Detection and source-only dose entrypoints intentionally do not call this
    planning prerequisite.
    """
    store=getattr(agent._workspace_store,'raw',agent._workspace_store)
    source=captured.target.preoperative_timepoint_id
    if not source:return False
    snapshot=store.load_timepoint_snapshot(captured.owner_id,captured.session_id,source,decode_arrays=False)
    if snapshot['timepoint']['stage']!='preoperative':return False
    results=(snapshot.get('agent') or {}).get('planning_results') or {}
    for key in ('seed_plan','manual_seeds','seed_positions'):
        value=results.get(key)
        if isinstance(value,(list,tuple)) and value:return True
    for key in ('seed_plan_serialized','manual_plan_serialized','algorithm_plan_snapshot'):
        value=results.get(key)
        if isinstance(value,dict) and isinstance(value.get('seeds'),list) and value['seeds']:return True
    count=results.get('total_seeds')
    # Legacy numerical plans can keep their source geometry in array sidecars.
    # A positive saved count alone without any actual plan artifact is not a plan.
    return type(count) is int and count>0 and any(results.get(key) is not None
        for key in ('seed_plan','seed_plan_serialized','manual_plan_serialized','seed_positions','algorithm_plan_snapshot'))


def guide_review_pause(agent,target):
    locale=(getattr(agent,'_active_turn_context',None) or {}).get('ui_language') or agent.memory.user_lang
    message=timepoint_message('continuation_guide_review_required',locale)['message']
    return ToolResult(False,error=message,message=message,metadata={'code':'continuation_guide_review_required',
        'phase':'awaiting_guide_pose_review','requires_human_review':True,'planning_completed':False,
        'timepoint_id':target,'downstream_actions_executed':[]})
