"""Authenticated, case-scoped routes for patient-specific puncture guides."""

from __future__ import annotations

import io
import logging
import time
from typing import Any, Dict

from flask import current_app, jsonify, request, send_file, session as flask_session

from web.auth import current_user
from web.surgical_guide import (
    SurgicalGuideError,
    available_guide_needles,
    generate_surgical_guide,
    guide_public_payload,
    guide_state_for_version,
    guide_version_summaries,
    mesh_to_ascii_stl,
    normalize_guide_parameters,
    parse_stl,
    save_guide_version,
    stl_stream,
    validate_exported_stl,
)

try:
    from web.server_support import rate_limit, require_api_key
except ImportError:  # pragma: no cover - supports `python web/server.py`.
    from server_support import rate_limit, require_api_key  # type: ignore


logger = logging.getLogger(__name__)


def register_surgical_guide_routes(app, get_agent):
    """Register routes whose case is resolved from authenticated request state."""

    def request_case_context():
        store = current_app.extensions.get("brachybot_workspace_store")
        user = current_user(store) if store is not None else None
        session_id = str(
            request.headers.get("X-BrachyBot-Session")
            or flask_session.get("bb_session_id")
            or ""
        ).strip()
        if not store or not user or not session_id:
            raise SurgicalGuideError("Authenticated case session is required")
        entry = store.get_session(user["id"], session_id)
        return store, user, entry.id

    def current_guide(agent: Any, version: Any = None) -> Dict[str, Any]:
        return guide_state_for_version(agent, version)

    def guide_metadata(agent: Any) -> Dict[str, Any]:
        return {
            "versions": guide_version_summaries(agent),
            "needle_options": available_guide_needles(agent),
        }

    def snapshot(agent: Any, reason: str, operation: Dict[str, Any] | None = None) -> None:
        store, user, session_id = request_case_context()
        if operation is not None:
            store.mark_operation(user["id"], session_id, agent, operation)
        else:
            store.flush_agent_checkpoint(user["id"], session_id, agent, reason)

    @app.route("/api/surgical-guides", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_surgical_guide_status():
        try:
            _store, _user, _session_id = request_case_context()
            agent = get_agent()
            return jsonify({"success": True, **guide_public_payload(current_guide(agent)), **guide_metadata(agent)})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 400

    @app.route("/api/surgical-guides/mesh", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_surgical_guide_mesh():
        try:
            _store, _user, _session_id = request_case_context()
            agent = get_agent()
            state = current_guide(agent, request.args.get("version"))
            return jsonify({"success": True, **guide_public_payload(state, include_mesh=True), **guide_metadata(agent)})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 400

    @app.route("/api/surgical-guides/generate", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_surgical_guide_generate():
        agent = get_agent()
        if agent is None:
            return jsonify({"success": False, "error": "Case agent is unavailable"}), 503
        try:
            data = request.get_json(silent=True) or {}
            parameters = normalize_guide_parameters(data.get("parameters") or {})
            selected = data.get("needle_ids") or None
            if selected is not None and not isinstance(selected, list):
                raise SurgicalGuideError("needle_ids must be a list when supplied")
            _store, _user, session_id = request_case_context()
            snapshot(agent, "surgical_guide.running", {
                "state": "running",
                "message": "Generating patient-specific puncture guide",
                "started_at": time.time(),
                "checkpoint": {"kind": "surgical_guide"},
            })
            state = save_guide_version(
                agent,
                generate_surgical_guide(agent, parameters, selected_needle_ids=selected),
            )
            snapshot(agent, "surgical_guide.ready", {
                "state": "ready",
                "message": "Patient-specific puncture guide generated",
                "updated_at": time.time(),
                "checkpoint": {"kind": "surgical_guide", "version": state["version"]},
            })
            logger.info("Generated surgical guide v%s for session %s", state["version"], session_id)
            return jsonify({"success": True, **guide_public_payload(state, include_mesh=True), **guide_metadata(agent)})
        except Exception as exc:
            logger.exception("Surgical guide generation failed")
            try:
                snapshot(agent, "surgical_guide.failed", {
                    "state": "ready",
                    "message": f"Puncture guide generation failed: {exc}",
                    "updated_at": time.time(),
                })
            except Exception:
                pass
            return jsonify({"success": False, "error": str(exc)}), 400

    @app.route("/api/surgical-guides/export", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_surgical_guide_export():
        try:
            store, user, session_id = request_case_context()
            agent = get_agent()
            state = current_guide(agent, (request.get_json(silent=True) or {}).get("version"))
            if not state or state.get("status") != "ready":
                raise SurgicalGuideError("Generate a current puncture guide before export")
            payload = mesh_to_ascii_stl(state.get("vertices"), state.get("faces"))
            validation = validate_exported_stl(payload)
            if not validation.get("watertight"):
                raise SurgicalGuideError("Exported STL failed watertightness validation")
            filename = f"puncture_guide_v{int(state.get('version') or 1)}.stl"
            path = store.write_artifact(
                user["id"], session_id, "surgical_guides", filename,
                io.BytesIO(payload), expected_bytes=len(payload),
            )
            updated = dict(state)
            updated["stl_artifact"] = path.relative_to(store.workspace_root(user["id"], session_id)).as_posix()
            updated["stl_validation"] = validation
            history = list(agent.memory.retrieve("surgical_guide_versions") or [])
            for index, item in enumerate(history):
                if isinstance(item, dict) and int(item.get("version") or 0) == int(updated.get("version") or 0):
                    history[index] = updated
            agent.memory.store("surgical_guide_versions", history)
            # Only overwrite the active pointer when exporting the active
            # version; historical exports must not silently change the guide
            # currently rendered in the viewer.
            active = current_guide(agent)
            if int(active.get("version") or 0) == int(updated.get("version") or 0):
                agent.memory.store("surgical_guide", updated)
            snapshot(agent, "surgical_guide.export")
            return send_file(
                io.BytesIO(payload), mimetype="model/stl", as_attachment=True,
                download_name=filename,
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 400

    @app.route("/api/surgical-guides/validate", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_surgical_guide_validate():
        """Validate a re-imported STL without treating it as patient geometry."""
        try:
            _store, _user, _session_id = request_case_context()
            upload = request.files.get("file")
            if upload is None or not upload.filename:
                raise SurgicalGuideError("Choose an STL file to validate")
            payload = upload.read()
            # Validation is intentionally read-only, but it still accepts an
            # untrusted client upload. Keep its resource use bounded so a
            # manufacturing QA check cannot exhaust the planning process.
            if not payload or len(payload) > 64 * 1024 * 1024:
                raise SurgicalGuideError("STL validation accepts files up to 64 MiB")
            vertices, faces = parse_stl(payload)
            validation = validate_exported_stl(payload)
            return jsonify({
                "success": True,
                "validation": validation,
                "mesh": {"vertices": vertices.tolist(), "faces": faces.tolist()},
            })
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
