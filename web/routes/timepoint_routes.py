"""Authenticated timepoint metadata and explicitly addressed workspace APIs."""
from __future__ import annotations

from functools import wraps

from flask import jsonify, request

from web.auth import current_user
from web.request_identity import explicit_case_id, explicit_timepoint_id
from web.server_support import require_api_key
from web.timepoints import (
    TimepointConflict, TimepointDependencyConflict, TimepointError,
    TimepointIntegrityError, TimepointNotFound,
)
from web.workspace_store import WorkspaceArchived, WorkspaceError, WorkspaceLeaseConflict, WorkspaceNotFound
from web.timepoint_messages import (request_timepoint_language, timepoint_error, timepoint_http_error,
    TimepointMessageError)


TIMEPOINT_CONTROL_ENDPOINTS = frozenset({
    "list_timepoints", "create_timepoint", "update_timepoint", "timepoint_delete_impact",
    "delete_timepoint", "restore_timepoint", "load_timepoint_workspace", "save_timepoint_workspace",
})


def register_timepoint_routes(app, store):
    @app.after_request
    def localize_timepoint_error(response):
        if request.endpoint in TIMEPOINT_CONTROL_ENDPOINTS and response.status_code >= 400:
            data = response.get_json(silent=True) or {}
            packet = timepoint_http_error(response.status_code, request_timepoint_language(),
                code=data.get("code"), message_code=data.get("message_code"))
            if isinstance(data.get("dependents"), list):
                packet["dependents"] = [value for value in data["dependents"] if isinstance(value, str) and len(value) == 32]
            response.set_data(app.json.dumps(packet))
            response.content_type = "application/json"
        return response

    def endpoint(*, mutate=False):
        def decorate(fn):
            @wraps(fn)
            def run(session_id, *args, **kwargs):
                user = current_user(store)
                if not user:
                    return jsonify(timepoint_http_error(401, request_timepoint_language())), 401
                try:
                    explicit_case_id(session_id)
                    store.require_local_session(user["id"], session_id)
                    if "identifier" in kwargs:
                        explicit_timepoint_id(kwargs["identifier"])
                    if mutate:
                        store.assert_editable(user["id"], session_id, request.headers.get("X-BrachyBot-Editor", ""))
                        with store._case_guard(user['id'], session_id):
                            return fn(user, session_id, *args, **kwargs)
                    return fn(user, session_id, *args, **kwargs)
                except (WorkspaceError, TimepointError, TimepointMessageError, TypeError, ValueError) as exc:
                    packet, status = timepoint_error(exc, request_timepoint_language(user=user, session_id=session_id))
                    return jsonify(packet), status
            return require_api_key(run)
        return decorate

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise TimepointMessageError("timepoint_json_required")
        return value

    def mutation_revision(user, session_id, data):
        from web.timepoints import revision
        expected = revision(data.get('expected_revision'))
        signature = data.pop('expected_metadata_signature', None)
        if signature is None:
            return expected  # Strict legacy CAS remains available.
        catalog = store.list_timepoints(user['id'], session_id, include_trashed=True)
        if signature != catalog['metadata_signature']:
            raise TimepointConflict('The catalog metadata changed after the operation was prepared')
        return catalog['catalog_revision']

    @app.route("/api/sessions/<session_id>/timepoints", methods=["GET"])
    @endpoint()
    def list_timepoints(user, session_id):
        store.migrate_default_timepoint(user["id"], session_id)
        return jsonify(success=True, **store.list_timepoints(
            user["id"], session_id, include_trashed=request.args.get("include_trashed") == "1",
        ))

    @app.route("/api/sessions/<session_id>/timepoints", methods=["POST"])
    @endpoint(mutate=True)
    def create_timepoint(user, session_id):
        data = body()
        result = store.create_timepoint(
            user["id"], session_id, data.get("title", "Preoperative"),
            expected_revision=mutation_revision(user, session_id, data),
            stage=data.get("stage", "preoperative"),
            preoperative_timepoint_id=data.get("preoperative_timepoint_id"),
        )
        return jsonify(success=True, **result), 201

    @app.route("/api/sessions/<session_id>/timepoints/<identifier>", methods=["PATCH"])
    @endpoint(mutate=True)
    def update_timepoint(user, session_id, identifier):
        data = body()
        expected = mutation_revision(user, session_id, data)
        data.pop('expected_revision', None)
        data.pop("session_id", None)
        data.pop("timepoint_id", None)
        return jsonify(success=True, **store.update_timepoint(
            user["id"], session_id, identifier, data, expected_revision=expected,
        ))

    @app.route("/api/sessions/<session_id>/timepoints/<identifier>/delete-impact", methods=["GET"])
    @endpoint()
    def timepoint_delete_impact(user, session_id, identifier):
        return jsonify(success=True, **store.timepoint_delete_impact(user["id"], session_id, identifier))

    @app.route("/api/sessions/<session_id>/timepoints/<identifier>", methods=["DELETE"])
    @endpoint(mutate=True)
    def delete_timepoint(user, session_id, identifier):
        data = body()
        return jsonify(success=True, **store.delete_timepoint(
            user["id"], session_id, identifier, expected_revision=mutation_revision(user, session_id, data),
        ))

    @app.route("/api/sessions/<session_id>/timepoints/<identifier>/restore", methods=["POST"])
    @endpoint(mutate=True)
    def restore_timepoint(user, session_id, identifier):
        data = body()
        return jsonify(success=True, **store.restore_timepoint(
            user["id"], session_id, identifier, expected_revision=mutation_revision(user, session_id, data),
        ))

    @app.route("/api/sessions/<session_id>/timepoints/<identifier>/workspace", methods=["GET"])
    @endpoint()
    def load_timepoint_workspace(user, session_id, identifier):
        if request.args.get('response_mode') == 'resource_shell':
            snapshot = store.load_timepoint_snapshot(user['id'], session_id, identifier,
                include_shared=False, projection='resource_shell')
            return jsonify(success=True, workspace=snapshot)
        return jsonify(success=True, workspace=store.load_timepoint_snapshot(user["id"], session_id, identifier))

    @app.route("/api/sessions/<session_id>/timepoints/<identifier>/workspace", methods=["PATCH"])
    @endpoint(mutate=True)
    def save_timepoint_workspace(user, session_id, identifier):
        data = body()
        patch = data.get("patch")
        if not isinstance(patch, dict) or set(patch) - {"ui", "report"}:
            raise TimepointError("Browser patches can update only UI and report state")
        workspace = store.save_timepoint_patch(
            user["id"], session_id, identifier, patch,
            expected_state_revision=data.get("expected_state_revision"),
            expected_clinical_revision=data.get('expected_clinical_revision'),
            expected_lifecycle_revision=data.get('expected_lifecycle_revision'),
            presentation_source=data.get('presentation_source'), presentation_sequence=data.get('presentation_sequence'),
        )
        if data.get('response_mode') == 'presentation_receipt':
            # Saving presentation must not send all clinical results, masks and
            # chat back to the browser. The immutable owner/revision receipt is
            # sufficient; retain the full response for older clients.
            receipt = {key: workspace[key] for key in (
                'session_id', 'timepoint_id', 'timepoint_state_revision',
                'timepoint_clinical_revision', 'saved_at',
            ) if key in workspace}
            row = workspace.get('timepoint') or {}
            receipt['timepoint'] = {key: row[key] for key in (
                'id', 'revision', 'state_revision', 'clinical_revision', 'lifecycle_revision',
                'title', 'stage', 'status', 'preoperative_timepoint_id',
            ) if key in row}
            # Return only canonical presentation touched by this request. Report
            # merging/sanitization stays server-authoritative, even for stale
            # fields; unrelated legacy UI sections need not cross the network.
            presentation = {}
            if 'ui' in patch:
                ui = workspace.get('ui') or {}
                presentation['ui'] = {key: ui[key] for key in patch['ui'] if key in ui}
            if 'report' in patch:
                presentation['report'] = workspace.get('report') or {}
            return jsonify(success=True, presentation_receipt=receipt, presentation=presentation)
        return jsonify(success=True, workspace=workspace)
