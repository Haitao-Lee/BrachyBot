"""Authenticated case-session and workspace persistence routes."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from flask import jsonify, request, send_file, session

from web.auth import current_user
from web.workspace_store import (
    WorkspaceError,
    WorkspaceLeaseConflict,
    WorkspaceNotFound,
    WorkspaceStore,
)


def register_session_routes(
    app: Any,
    store: WorkspaceStore,
    get_agent: Callable[[Optional[str]], Any],
    drop_agent: Callable[[str], None],
) -> None:
    """Register account-owned session APIs.

    Authentication and CSRF validation are installed centrally in
    ``web.auth.configure_auth``.  Every route below still resolves the user
    from the signed cookie and verifies ownership before touching workspace
    metadata or files.
    """

    def user_or_error():
        user = current_user(store)
        if not user:
            return None, (jsonify({"error": "Authentication required"}), 401)
        return user, None

    def session_payload(entry):
        return entry.public_dict()

    def assert_target_editable(user: Dict[str, Any], session_id: str) -> None:
        """Apply the edit lease to an explicitly addressed case session.

        The global request hook protects the selected case. Rename and delete
        endpoints also accept another owned case id, so they need this
        target-specific check to avoid bypassing an active editor in a
        different browser window.
        """
        store.assert_editable(
            user["id"],
            session_id,
            str(request.headers.get("X-BrachyBot-Editor") or ""),
        )

    @app.route("/api/sessions", methods=["GET"])
    def list_case_sessions():
        user, error = user_or_error()
        if error:
            return error
        active = str(session.get("bb_session_id") or "")
        return jsonify({
            "success": True,
            "active_session_id": active,
            "sessions": [session_payload(item) for item in store.list_sessions(user["id"])],
        })

    @app.route("/api/sessions", methods=["POST"])
    def create_case_session():
        user, error = user_or_error()
        if error:
            return error
        data = request.get_json(silent=True) or {}
        try:
            entry = store.create_session(user["id"], str(data.get("title") or "New case"))
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 400
        session["bb_session_id"] = entry.id
        # A new case has an empty, cheap snapshot. Return it directly so the
        # browser can paint the new workspace without constructing a GPU agent.
        snapshot = store.load_snapshot(user["id"], entry.id)
        return jsonify({
            "success": True,
            "session": session_payload(entry),
            "active_session_id": entry.id,
            "workspace": snapshot,
        }), 201

    @app.route("/api/sessions/<session_id>", methods=["PATCH"])
    def rename_case_session(session_id: str):
        user, error = user_or_error()
        if error:
            return error
        data = request.get_json(silent=True) or {}
        try:
            assert_target_editable(user, session_id)
            entry = store.rename_session(user["id"], session_id, str(data.get("title") or ""))
        except WorkspaceLeaseConflict as exc:
            return jsonify({"error": str(exc), "code": "workspace_locked"}), 409
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"success": True, "session": session_payload(entry)})

    @app.route("/api/sessions/<session_id>/select", methods=["POST"])
    def select_case_session(session_id: str):
        user, error = user_or_error()
        if error:
            return error
        try:
            entry = store.get_session(user["id"], session_id)
            session["bb_session_id"] = entry.id
            # Do not hydrate the Python/GPU agent in the selection request.
            # Selecting a case is a control-plane operation and must remain
            # responsive; the data-plane agent is hydrated lazily by the first
            # status/planning request after the lightweight snapshot is shown.
            snapshot = store.load_snapshot(user["id"], entry.id)
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify({"success": True, "active_session_id": entry.id, "workspace": snapshot})

    @app.route("/api/sessions/<session_id>", methods=["DELETE"])
    def trash_case_session(session_id: str):
        user, error = user_or_error()
        if error:
            return error
        try:
            assert_target_editable(user, session_id)
            drop_agent(session_id)
            store.move_to_trash(user["id"], session_id)
        except WorkspaceLeaseConflict as exc:
            return jsonify({"error": str(exc), "code": "workspace_locked"}), 409
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 404
        if session.get("bb_session_id") == session_id:
            remaining = store.list_sessions(user["id"])
            replacement = remaining[0] if remaining else store.create_session(user["id"], "New case")
            session["bb_session_id"] = replacement.id
        active_session_id = session.get("bb_session_id")
        snapshot = store.load_snapshot(user["id"], str(active_session_id))
        return jsonify({
            "success": True,
            "active_session_id": active_session_id,
            "workspace": snapshot,
        })

    @app.route("/api/sessions/trash", methods=["GET"])
    def list_trashed_sessions():
        user, error = user_or_error()
        if error:
            return error
        entries = [item for item in store.list_sessions(user["id"], include_trashed=True) if item.status == "trashed"]
        return jsonify({"success": True, "sessions": [session_payload(item) for item in entries]})

    @app.route("/api/sessions/<session_id>/restore", methods=["POST"])
    def restore_case_session(session_id: str):
        user, error = user_or_error()
        if error:
            return error
        try:
            entry = store.restore_from_trash(user["id"], session_id)
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"success": True, "session": session_payload(entry)})

    @app.route("/api/sessions/<session_id>/purge", methods=["DELETE"])
    def purge_case_session(session_id: str):
        user, error = user_or_error()
        if error:
            return error
        try:
            assert_target_editable(user, session_id)
            drop_agent(session_id)
            store.permanently_delete(user["id"], session_id)
        except WorkspaceLeaseConflict as exc:
            return jsonify({"error": str(exc), "code": "workspace_locked"}), 409
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify({"success": True})

    @app.route("/api/sessions/<session_id>/artifacts/<path:artifact_path>", methods=["GET"])
    def download_case_artifact(session_id: str, artifact_path: str):
        """Download an exported artifact after an ownership and path check."""
        user, error = user_or_error()
        if error:
            return error
        try:
            # ``session_artifact_path`` rejects traversal and verifies that the
            # requested session belongs to the signed-in account before file IO.
            path = store.session_artifact_path(user["id"], session_id, "artifacts", artifact_path)
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 404
        if not path.is_file():
            return jsonify({"error": "Artifact not found"}), 404
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.route("/api/workspace/artifacts", methods=["POST"])
    def upload_generated_case_artifact():
        """Persist a browser-generated report/export file in the active case."""
        user, error = user_or_error()
        if error:
            return error
        file = request.files.get("file")
        if file is None or not file.filename:
            return jsonify({"error": "A generated artifact file is required"}), 400
        category = str(request.form.get("category") or "reports")
        # Browser artifacts are intentionally narrow in scope; clinical source
        # imaging always uses the validated input-upload endpoint instead.
        if category not in {"reports", "exports"}:
            return jsonify({"error": "Unsupported artifact category"}), 400
        session_id = str(session.get("bb_session_id") or "")
        try:
            path = store.write_artifact(
                user["id"], session_id, category, file.filename, file.stream,
                expected_bytes=file.content_length or 0,
            )
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 413 if "quota" in str(exc).lower() else 400
        relative = path.relative_to(store.workspace_root(user["id"], session_id) / "artifacts").as_posix()
        return jsonify({
            "success": True,
            "path": str(path),
            "download_url": f"/api/sessions/{session_id}/artifacts/{relative}",
        }), 201

    @app.route("/api/workspace/snapshot", methods=["GET"])
    def workspace_snapshot():
        user, error = user_or_error()
        if error:
            return error
        session_id = str(session.get("bb_session_id") or "")
        try:
            store.get_session(user["id"], session_id)
            get_agent(session_id)
            snapshot = store.load_snapshot(user["id"], session_id)
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify({"success": True, "workspace": snapshot})

    @app.route("/api/workspace/state", methods=["POST"])
    def save_workspace_state():
        user, error = user_or_error()
        if error:
            return error
        data = request.get_json(silent=True) or {}
        session_id = str(session.get("bb_session_id") or "")
        patch: Dict[str, Any] = {}
        for key in ("ui", "report", "chat", "operation"):
            if isinstance(data.get(key), dict):
                patch[key] = data[key]
        if isinstance(data.get("ui_state"), dict):
            patch["ui"] = {**patch.get("ui", {}), "state": data["ui_state"]}
        try:
            snapshot = store.save_snapshot_patch(
                user["id"], session_id, patch,
                # Agent checkpoints and viewer events are intentionally
                # independent writers.  Merge this named UI patch instead of
                # rejecting a harmless stale browser revision.
                expected_revision=None, reason="workspace.ui_saved",
            )
            agent = get_agent(session_id)
            if agent is not None and isinstance(data.get("ui_state"), dict):
                agent.memory.set_ui_state(data["ui_state"])
        except WorkspaceLeaseConflict as exc:
            return jsonify({"error": str(exc), "code": "stale_workspace"}), 409
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"success": True, "revision": snapshot["session"]["revision"], "workspace": snapshot})

    @app.route("/api/workspace/checkpoint", methods=["POST"])
    def checkpoint_workspace():
        user, error = user_or_error()
        if error:
            return error
        session_id = str(session.get("bb_session_id") or "")
        try:
            agent = get_agent(session_id)
            snapshot = store.flush_agent_checkpoint(user["id"], session_id, agent, "workspace.explicit_checkpoint")
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"success": True, "revision": snapshot["session"]["revision"]})

    @app.route("/api/workspace/lease", methods=["POST", "DELETE"])
    def workspace_lease():
        user, error = user_or_error()
        if error:
            return error
        data = request.get_json(silent=True) or {}
        session_id = str(session.get("bb_session_id") or "")
        token = str(data.get("editor_token") or request.headers.get("X-BrachyBot-Editor") or "")
        try:
            if request.method == "DELETE":
                store.release_lease(user["id"], session_id, token)
                return jsonify({"success": True, "editable": False})
            lease = store.acquire_lease(user["id"], session_id, token, data.get("ttl_seconds", 75))
        except WorkspaceLeaseConflict as exc:
            return jsonify({"error": str(exc), "code": "workspace_locked", "editable": False}), 409
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"success": True, **lease})

    @app.route("/api/workspace/import-client", methods=["POST"])
    def import_legacy_client_workspace():
        """One-time migration for old localStorage chat/report data.

        The payload intentionally contains only browser-owned JSON.  Existing
        in-memory clinical arrays are captured separately by the normal agent
        checkpoint path when their old session is still alive.
        """
        user, error = user_or_error()
        if error:
            return error
        data = request.get_json(silent=True) or {}
        title = str(data.get("title") or "Imported case")
        try:
            entry = store.create_session(user["id"], title)
            snapshot = store.save_snapshot_patch(
                user["id"], entry.id,
                {
                    "ui": data.get("ui") if isinstance(data.get("ui"), dict) else {},
                    "report": data.get("report") if isinstance(data.get("report"), dict) else {},
                    "chat": data.get("chat") if isinstance(data.get("chat"), dict) else {},
                },
                reason="workspace.legacy_imported",
            )
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"success": True, "session": session_payload(entry), "workspace": snapshot}), 201
