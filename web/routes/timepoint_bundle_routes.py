"""Owned graph imports create a new patient; never overwrite the mounted case."""
from flask import jsonify, request
from web.auth import current_user
from web.server_support import require_api_key
from web.timepoint_bundle import import_bundle
from web.timepoint_messages import request_timepoint_language, timepoint_error
from web.timepoints import TimepointError
from web.workspace_store import WorkspaceError
import tempfile
from pathlib import Path


def register_timepoint_bundle_routes(app, store):
    raw = getattr(store, "raw", store)
    @app.post("/api/workspace/import-bundle")
    @require_api_key
    def import_timepoint_bundle():
        user = current_user(raw)
        if not user:
            return jsonify(success=False, code="authentication_required"), 401
        try:
            uploaded = request.files.get("file")
            if uploaded is None:
                raise TimepointError("Upload a complete workspace ZIP")
            with tempfile.TemporaryDirectory(prefix="workspace-import-upload-", dir=raw.staging_dir) as directory:
                path = Path(directory) / "bundle.zip"
                count = 0
                with path.open("xb") as output:
                    for chunk in iter(lambda: uploaded.stream.read(1024 * 1024), b""):
                        count += len(chunk)
                        if count > 500 * 1024**2:
                            raise TimepointError("Workspace upload exceeds the configured request limit")
                        raw.ensure_capacity(user["id"], count)
                        output.write(chunk)
                entry = import_bundle(raw, user["id"], path, title=request.form.get("title") or None)
            return jsonify(success=True, session=entry.public_dict(), reviews_require_revalidation=True,
                active_session_changed=False), 201
        except (WorkspaceError, TimepointError, ValueError, KeyError, OSError) as exc:
            packet, status = timepoint_error(exc, request_timepoint_language())
            return jsonify(packet), status
