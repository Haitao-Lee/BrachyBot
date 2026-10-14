"""Authenticated asynchronous detection, observation edits and presentation."""
import copy
from functools import wraps
import threading
import time
from uuid import UUID

from flask import jsonify, request
from web.auth import current_user
from web.request_identity import explicit_case_id, explicit_timepoint_id
from web.server_support import require_api_key
from web.implant_workspace import ImplantWorkspace
from web.implant_service import ImplantServiceError
from web.timepoint_messages import request_timepoint_language, timepoint_message
from web.workspace_store import WorkspaceError,WorkspaceLeaseConflict
from web.timepoints import TimepointError,TimepointConflict

SCOPED_IMPLANT_ENDPOINTS = frozenset({"implant_view", "implant_detect", "implant_job", "implant_correct", "implant_presentation", "implant_source_profile", "implant_review"})


def register_implant_routes(app, store):
    jobs, lock = {}, threading.RLock()
    workspace_factory = app.config.get("IMPLANT_WORKSPACE_FACTORY") or ImplantWorkspace
    def error(exc, language):
        code = getattr(exc, "code", "implant_operation_failed")
        packet = timepoint_message(code, language)
        status = 409 if isinstance(exc,(WorkspaceLeaseConflict,TimepointConflict)) or code in {"implant_revision_conflict", "implant_presentation_conflict", "implant_input_changed", "implant_request_conflict", "implant_job_in_progress"} else 400
        return jsonify(success=False, error=packet["message"], **packet), status
    def scoped(*, mutate=False):
        def decorate(fn):
            @wraps(fn)
            def run(session_id, identifier, **kwargs):
                user = current_user(store)
                language = request_timepoint_language(user=user, session_id=session_id)
                if not user:
                    return jsonify(error=timepoint_message("authentication_required", language)["message"]), 401
                try:
                    explicit_case_id(session_id); explicit_timepoint_id(identifier)
                    store.require_local_session(user["id"], session_id)
                    store._timepoint_record(store.list_timepoints(user["id"], session_id), identifier)
                    if mutate:
                        store.assert_editable(user["id"], session_id, request.headers.get("X-BrachyBot-Editor", ""))
                    return fn(user["id"], session_id, identifier, language, **kwargs)
                except (ImplantServiceError, WorkspaceError, TimepointError, ValueError, TypeError) as exc:
                    return error(exc, language)
            return require_api_key(run)
        return decorate
    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value
    base = "/api/sessions/<session_id>/timepoints/<identifier>/implants"
    @app.get(base)
    @scoped()
    def implant_view(owner, session_id, identifier, language):
        return jsonify(success=True, view=workspace_factory(store, owner, session_id, identifier).view())

    @app.post(base + "/detect")
    @scoped(mutate=True)
    def implant_detect(owner, session_id, identifier, language):
        data = body()
        if 'request_id' not in data or set(data) - {"request_id", "expected_revision_id"} or not isinstance(data.get('request_id'),str):
            raise ValueError("Unknown detection fields")
        if data.get('expected_revision_id') is not None:
            if not isinstance(data['expected_revision_id'],str):raise ValueError('Invalid observation revision')
            UUID(data['expected_revision_id'])
        rid = str(UUID(data["request_id"]))
        key = (owner, session_id, identifier, rid)
        with lock:
            for old in list(jobs):
                if jobs[old]["status"] != "running" and time.monotonic() - jobs[old]["finished"] > 3600:
                    jobs.pop(old)
            if key in jobs:
                if jobs[key]["expected"] != data.get("expected_revision_id"):
                    raise ImplantServiceError("implant_request_conflict", "Retry target revision changed")
                return jsonify(success=True, job={k:v for k,v in jobs[key].items() if k not in {"expected", "finished"}}), 202
            if len(jobs) >= 64 or any(old[:3] == key[:3] and job["status"] == "running" for old,job in jobs.items()):
                raise ImplantServiceError("implant_job_in_progress", "The target already has a detection job")
            workspace = workspace_factory(store, owner, session_id, identifier)
            workspace.service._config().validate_available()
            jobs[key] = {"request_id": rid, "session_id": session_id, "timepoint_id": identifier,
                "status": "running", "expected": data.get("expected_revision_id"), "finished": 0.}
        def run():
            try:
                with app.app_context():
                    view = workspace.detect(rid, data.get("expected_revision_id"))
                updates = {"status": "completed", "view": view}
            except Exception as exc:
                updates = {"status": "failed", "code": getattr(exc, "code", "implant_operation_failed")}
            with lock:
                jobs[key].update(**updates, finished=time.monotonic())
        threading.Thread(target=run, name="implant-detect-" + rid[:8], daemon=True).start()
        return jsonify(success=True, job={k:v for k,v in jobs[key].items() if k not in {"expected", "finished"}}), 202

    @app.get(base + "/jobs/<job_id>")
    @scoped()
    def implant_job(owner, session_id, identifier, language, job_id):
        key = (owner, session_id, identifier, str(UUID(job_id)))
        with lock:
            job = copy.deepcopy(jobs.get(key))
        if job is None:
            return jsonify(success=False, code="implant_job_not_found", error=timepoint_message("implant_job_not_found", language)["message"]), 404
        job.pop("expected", None); job.pop("finished", None)
        if job.get("code"):
            job["message"] = timepoint_message(job["code"], language)["message"]
        return jsonify(success=True, job=job)

    @app.post(base + "/corrections")
    @scoped(mutate=True)
    def implant_correct(owner, session_id, identifier, language):
        with lock:
            if any(key[:3] == (owner, session_id, identifier) and item["status"] == "running" for key,item in jobs.items()):
                raise ImplantServiceError("implant_job_in_progress", "Wait for detection before correction")
        view = workspace_factory(store, owner, session_id, identifier).correct(body(), actor=owner)
        return jsonify(success=True, view=view)

    @app.patch(base + "/presentation")
    @scoped(mutate=True)
    def implant_presentation(owner, session_id, identifier, language):
        return jsonify(success=True, view=workspace_factory(store, owner, session_id, identifier).set_presentation(body()))

    @app.post(base + "/review")
    @scoped(mutate=True)
    def implant_review(owner, session_id, identifier, language):
        with lock:
            if any(key[:3] == (owner, session_id, identifier) and job["status"] == "running" for key, job in jobs.items()):
                raise ImplantServiceError("implant_job_in_progress", "Review cannot race an active detection")
        return jsonify(success=True, view=workspace_factory(store, owner, session_id, identifier).review(body(), actor=owner))

    @app.route(base+'/dose-source',methods=['GET','POST'])
    @scoped(mutate=True)
    def implant_source_profile(owner,session_id,identifier,language):
        from plans.dose_pre.model_loader import DOSE_MODEL_SCALE_GY,resolve_dose_model_path
        from tool_factory.seed_seg.seedfinder_adapter import sha256_file
        import math
        checkpoint=resolve_dose_model_path()
        if checkpoint is None:raise ImplantServiceError('implant_dose_model_unavailable','Configure the installed dose CNN')
        state=store.load_timepoint_snapshot(owner,session_id,identifier)
        values=state.get('agent',{}).get('planning_results') or {}
        if request.method=='GET':
            return jsonify(success=True,profile=values.get('implant_dose_profile'),dose_scale_gy=DOSE_MODEL_SCALE_GY,
                dose_model_sha256=sha256_file(checkpoint),state_revision=state['timepoint_state_revision'],
                clinical_revision=state['timepoint_clinical_revision'],clinical_use_ready=False)
        data=body()
        revision_key = 'expected_clinical_revision' if 'expected_clinical_revision' in data else 'expected_state_revision'
        if set(data)!={'length_mm','radius_mm',revision_key} or any(type(data[key]) not in {int,float} or not math.isfinite(data[key]) or data[key]<=0 or data[key]>100 for key in ('length_mm','radius_mm')):
            raise ImplantServiceError('implant_source_parameters_required','Explicit finite source dimensions are required')
        if data['length_mm']<=2*data['radius_mm']:
            raise ImplantServiceError('implant_source_parameters_required','Source length must exceed diameter')
        from uuid import uuid4
        profile={'confirmation_id':uuid4().hex,'seed_info':{'length':data['length_mm'],'radius':data['radius_mm'],'margin_rate':1.5},
            'dose_scale_gy':DOSE_MODEL_SCALE_GY,'dose_model_sha256':sha256_file(checkpoint),
            'confirmed_by':owner,'confirmation_scope':'software_estimated_dose_settings_not_clinical_approval',
            'source_model_id':'dose_unet_spacing1mm','clinical_use_ready':False}
        actual_revision = state['timepoint_clinical_revision'] if revision_key == 'expected_clinical_revision' else state['timepoint_state_revision']
        if type(data[revision_key]) is not int or data[revision_key]!=actual_revision:
            raise TimepointConflict('Workspace source settings changed')
        prior = values.get('implant_dose_profile') or {}
        same_profile = bool(prior.get('confirmation_id')) and all(prior.get(key) == profile.get(key) for key in (
                'seed_info', 'dose_scale_gy', 'dose_model_sha256', 'source_model_id'))
        # Explicitly confirming the physical source also sets the matching
        # supplemental source dimensions in this acquisition's Input config.
        # Do not carry a Session default capsule size into reviewed continuation.
        # Preserve placement policy and every other owned planning parameter.
        from web.input_workflow import restore_owned_planning_config, planning_config_values
        owned_config = planning_config_values(restore_owned_planning_config({}, state.get('agent')))
        seed_settings = dict(owned_config.get('seed_info') or {})
        seed_settings.update(length=data['length_mm'], radius=data['radius_mm'])
        owned_config['seed_info'] = seed_settings
        same_config = values.get('timepoint_planning_config') == owned_config
        if same_profile and same_config:
            # Confirming identical numerical inputs is not a new physical
            # source or a reason to discard a current dose/review receipt.
            return jsonify(success=True, profile=prior, reused=True, clinical_use_ready=False)
        from web.source_profile_invalidation import source_profile_invalidation
        updates = {'implant_dose_profile': prior if same_profile else profile,
            'timepoint_planning_config': owned_config,
            **({} if same_profile else source_profile_invalidation(values))}
        if state['timepoint']['legacy_default']:
            store.save_agent_results_patch(owner,session_id,updates,
                expected_revision=data[revision_key])
        else:
            store.save_timepoint_results(owner,session_id,identifier,updates,**{revision_key:data[revision_key]})
        return jsonify(success=True,profile=updates['implant_dose_profile'],
            reused=same_profile, clinical_use_ready=False)
