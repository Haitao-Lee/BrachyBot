"""Owned, editor/CSRF-protected guide registration and explicit fit review."""
from functools import wraps
import hashlib
import hmac
import json

from flask import jsonify, request

from web.auth import current_user, csrf_valid
from web.request_identity import explicit_case_id, explicit_timepoint_id
from web.server_support import require_api_key, rate_limit
from web.workspace_store import WorkspaceError, WorkspaceLeaseConflict, WorkspaceNotFound
from web.timepoints import TimepointError, TimepointConflict, TimepointNotFound
from web.guide_placement import GuidePlacementError
from web.guide_service import guide_manifest_summary, GuideSourceImageError
from web.guide_registration import GuideRegistrationJobs, owned_service, guide_overlay
from web.timepoint_messages import request_timepoint_language,timepoint_message


SCOPED_GUIDE_REGISTRATION_ENDPOINTS = frozenset({'guide_registration_inventory', 'guide_registration_start',
    'guide_registration_job', 'guide_registration_cancel', 'guide_registration_overlay', 'guide_registration_review'})


def register_guide_registration_routes(app, store):
    jobs = GuideRegistrationJobs(store, limits=app.config.get('GUIDE_REGISTRATION_LIMITS'))
    app.extensions['guide_registration_jobs'] = jobs

    def signed_receipt(receipt):
        fields = {key: receipt.get(key) for key in ('session_id', 'timepoint_id', 'placement_id',
                      'candidate_sha256', 'target_image', 'state_revision','clinical_revision')}
        key = str(app.secret_key).encode()
        return hmac.new(key, json.dumps(fields, sort_keys=True, allow_nan=False).encode(), hashlib.sha256).hexdigest()

    def scoped(*, mutate=False):
        def decorate(fn):
            @wraps(fn)
            def run(session_id, identifier, **kwargs):
                user = current_user(store)
                language=request_timepoint_language()
                if not user:
                    packet=timepoint_message('authentication_required',language)
                    return jsonify(success=False,error=packet['message'],**packet),401
                try:
                    explicit_case_id(session_id); explicit_timepoint_id(identifier)
                    store.require_local_session(user['id'], session_id)
                    store._timepoint_record(store.list_timepoints(user['id'], session_id), identifier)
                    if mutate:
                        if not csrf_valid():
                            packet=timepoint_message('access_denied',language)
                            return jsonify(success=False,error=packet['message'],**packet),403
                        store.assert_editable(user['id'], session_id, request.headers.get('X-BrachyBot-Editor', ''))
                    return fn(user['id'], session_id, identifier, **kwargs)
                except (WorkspaceError, TimepointError, GuidePlacementError, ValueError, TypeError) as exc:
                    status = (404 if isinstance(exc, (WorkspaceNotFound, TimepointNotFound)) else
                              409 if isinstance(exc, (WorkspaceLeaseConflict, TimepointConflict)) else 400)
                    code='guide_registration_conflict' if status==409 else 'guide_registration_invalid'
                    if isinstance(exc, GuideSourceImageError):
                        code = exc.error_code
                    packet=timepoint_message(code,language)
                    app.logger.info('Owned guide registration rejected: %s',exc)
                    return jsonify(success=False,error=packet['message'],**packet),status
            return require_api_key(rate_limit(run))
        return decorate

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise GuidePlacementError('A JSON request object is required')
        return data

    def public_job(record):
        # Keep technical worker diagnostics in the owned journal, not the UI.
        result = dict(record)
        if result.get('error'):
            code = ('guide_source_image_unverified' if result.get('error_code') == 'guide_source_image_unverified'
                    else 'guide_registration_conflict' if result.get('status') == 'stale'
                    else 'guide_registration_invalid')
            packet = timepoint_message(code, request_timepoint_language())
            result.update(error=packet['message'], error_code=code)
        return result

    base = '/api/sessions/<session_id>/timepoints/<identifier>/guide-registration'

    @app.get(base)
    @scoped()
    def guide_registration_inventory(owner, session_id, identifier):
        service = owned_service(store, owner, session_id)
        target = service._snapshot(identifier)
        source_id = target['timepoint'].get('preoperative_timepoint_id')
        candidates = service._results(target).get('guide_placement_candidates') or {}
        versions = []
        if source_id:
            source = service._snapshot(source_id)
            values = service._results(source)
            records = service.guide_records(source)
            seen = set()
            for record in records:
                if isinstance(record, dict) and record.get('version') not in seen:
                    versions.append(guide_manifest_summary(record)); seen.add(record.get('version'))
        return jsonify(success=True, session_id=session_id, timepoint_id=identifier,
            source_timepoint_id=source_id, state_revision=target['timepoint_state_revision'], guide_versions=versions,
            clinical_revision=target['timepoint_clinical_revision'],
            review_profile=service._results(target).get('continuation_review_profile'),
            current_anatomy_feasibility=service._results(target).get('guide_current_feasibility'),
            candidates=[{key: row.get(key) for key in ('placement_id', 'candidate_sha256', 'method', 'review_state', 'qc', 'target_image')}
                        for row in candidates.values()], active_placement_id=(service._results(target).get('guide_placement') or {}).get('placement_id'),
            clinical_use_approved=False)

    @app.post(base + '/jobs')
    @scoped(mutate=True)
    def guide_registration_start(owner, session_id, identifier):
        return jsonify(success=True, job=public_job(jobs.start(owner, session_id, identifier, body()))), 202

    @app.get(base + '/jobs/<job_id>')
    @scoped()
    def guide_registration_job(owner, session_id, identifier, job_id):
        return jsonify(success=True, job=public_job(jobs.get(owner, session_id, identifier, job_id)))

    @app.post(base + '/jobs/<job_id>/cancel')
    @scoped(mutate=True)
    def guide_registration_cancel(owner, session_id, identifier, job_id):
        return jsonify(success=True, job=public_job(jobs.cancel(owner, session_id, identifier, job_id)))

    @app.get(base + '/placements/<placement_id>/overlay')
    @scoped()
    def guide_registration_overlay(owner, session_id, identifier, placement_id):
        service = owned_service(store, owner, session_id)
        source_id = service._snapshot(identifier)['timepoint'].get('preoperative_timepoint_id')
        version = int(request.args.get('guide_version', '0'))
        packet = guide_overlay(service, source_timepoint_id=source_id, target_timepoint_id=identifier,
                               guide_version=version, placement_id=placement_id)
        packet['receipt_token'] = signed_receipt(packet)
        return jsonify(success=True, overlay=packet)

    @app.post(base + '/placements/<placement_id>/review')
    @scoped(mutate=True)
    def guide_registration_review(owner, session_id, identifier, placement_id):
        data = body()
        allowed = {'guide_version', 'expected_state_revision', 'candidate_sha256', 'decision', 'profile_id',
                   'note', 'overlay_receipt', 'manufacturing_confirmed','expected_clinical_revision'}
        if set(data) - allowed:
            raise GuidePlacementError('Unknown placement review fields')
        receipt = data.get('overlay_receipt')
        if data.get('decision') == 'accepted':
            if (not isinstance(receipt, dict) or receipt.get('session_id') != session_id
                    or receipt.get('timepoint_id') != identifier or receipt.get('placement_id') != placement_id
                    or not hmac.compare_digest(str(receipt.get('receipt_token', '')), signed_receipt(receipt))):
                raise GuidePlacementError('Fetch and display the owned current overlay before accepting a placement')
        service = owned_service(store, owner, session_id)
        source_id = service._snapshot(identifier)['timepoint'].get('preoperative_timepoint_id')
        result = service.review(source_timepoint_id=source_id, target_timepoint_id=identifier,
            guide_version=data.get('guide_version'), placement_id=placement_id,
            expected_state_revision=data.get('expected_state_revision'), candidate_sha256=data.get('candidate_sha256'),
            decision=data.get('decision'), profile_id=data.get('profile_id'), note=data.get('note'),
            overlay_receipt=receipt, manufacturing_confirmed=data.get('manufacturing_confirmed') is True,
            expected_clinical_revision=data.get('expected_clinical_revision'))
        return jsonify(success=True, **result)
