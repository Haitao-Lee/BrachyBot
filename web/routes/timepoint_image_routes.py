"""Owned multi-image inventory, distinct display and planning-reference actions."""
from functools import wraps
from pathlib import Path

from flask import jsonify, request, send_file

from web.auth import current_user
from web.request_identity import explicit_case_id, explicit_timepoint_id
from web.server_support import require_api_key
from web.timepoint_images import TimepointImageService
from web.timepoint_messages import request_timepoint_language, timepoint_error
from web.timepoints import TimepointError
from web.workspace_store import WorkspaceError

SCOPED_IMAGE_ENDPOINTS = frozenset({"timepoint_images", "timepoint_image_update", "timepoint_image_source"})


def register_timepoint_image_routes(app, store):
    store = getattr(store, "raw", store)
    service = TimepointImageService(store)
    app.extensions["timepoint_images"] = service

    def owned(fn):
        @wraps(fn)
        def run(session_id, identifier, **kwargs):
            user = current_user(store)
            if not user:
                return jsonify(success=False, code="authentication_required"), 401
            try:
                explicit_case_id(session_id)
                explicit_timepoint_id(identifier)
                store.require_local_session(user["id"], session_id)
                store._timepoint_record(store.list_timepoints(user["id"], session_id), identifier)
                return fn(user["id"], session_id, identifier, **kwargs)
            except (WorkspaceError, TimepointError, ValueError, TypeError, OSError) as exc:
                packet, status = timepoint_error(exc, request_timepoint_language())
                return jsonify(packet), status
        return require_api_key(run)

    base = "/api/sessions/<session_id>/timepoints/<identifier>/images"

    @app.route(base, methods=["GET", "POST"])
    @owned
    def timepoint_images(owner, session_id, identifier):
        if request.method == "GET":
            service.adopt_saved_reference(owner, session_id, identifier)
            return jsonify(success=True, **service.list_images(owner, session_id, identifier))
        editor = request.headers.get("X-BrachyBot-Editor", "")
        if request.is_json:
            data = request.get_json(silent=True)
            allowed = {"path", "name", "modality", "role", "frame_index", "series_id", "expected_collection_revision"}
            if not isinstance(data, dict) or set(data) - allowed:
                raise TimepointError("Unexpected image registration fields")
            # This adapter accepts only a path produced by this target's
            # authenticated upload. The service resolves links and ownership;
            # it never treats a browser path as arbitrary filesystem authority.
            result = service.register_owned_source(owner, session_id, identifier, data.get("path", ""),
                modality=data.get("modality", "CT"), role=data.get("role", "unclassified"),
                frame_index=data.get("frame_index"), series_id=data.get("series_id"), name=data.get("name"),
                expected_collection_revision=data.get("expected_collection_revision"), editor_token=editor,
                select_first_reference=True)
        else:
            file = request.files.get("file")
            if file is None or not file.filename:
                raise TimepointError("Upload one image acquisition")
            def integer(name, optional=False):
                value = request.form.get(name)
                if optional and value in (None, ""):
                    return None
                if value is None or not str(value).isdigit():
                    raise TimepointError("Image revisions and frame indices must be nonnegative integers")
                return int(value)
            result = service.register_upload(owner, session_id, identifier, file.stream, file.filename,
                modality=request.form.get("modality", "CT"), role=request.form.get("role", "unclassified"),
                frame_index=integer("frame_index", optional=True), name=request.form.get("name"),
                expected_collection_revision=integer("expected_collection_revision"), editor_token=editor,
                expected_bytes=file.content_length or 0, select_first_reference=True)
        return jsonify(success=True, **result), 201

    @app.route(base + "/<image_id>", methods=["PATCH", "DELETE"])
    @owned
    def timepoint_image_update(owner, session_id, identifier, image_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise TimepointError("An image update must be a JSON object")
        expected = data.pop("expected_collection_revision", None)
        editor = request.headers.get("X-BrachyBot-Editor", "")
        if request.method == "DELETE":
            if data:
                raise TimepointError("Deletion accepts only its collection revision")
            result = service.delete_image(owner, session_id, identifier, image_id,
                expected_collection_revision=expected, editor_token=editor)
        else:
            result = service.update_image(owner, session_id, identifier, image_id, data,
                expected_collection_revision=expected, editor_token=editor)
        return jsonify(success=True, **result)

    @app.get(base + "/<image_id>/<kind>")
    @owned
    def timepoint_image_source(owner, session_id, identifier, image_id, kind):
        if kind not in {"source", "original"}:
            raise TimepointError("Unknown image resource")
        path, image = service.source_file(owner, session_id, identifier, image_id, original=kind == "original")
        response = send_file(path, as_attachment=False, conditional=True)
        response.headers["X-BrachyBot-Session"] = session_id
        response.headers["X-BrachyBot-Timepoint"] = identifier
        response.headers["X-BrachyBot-Image"] = image_id
        response.headers["Cache-Control"] = "private, no-store"
        return response
