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
    guide_bore_quality_ready,
    guide_state_for_version,
    guide_status_payload,
    guide_version_summaries,
    mesh_to_ascii_stl,
    normalize_guide_parameters,
    parse_stl,
    planning_signature,
    save_guide_version,
    skin_surface_public_payload,
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

    def workspace_data_pending(agent):
        """Keep a cold-session restore from being mistaken for no guide."""
        guide_status = None
        if agent is not None:
            try:
                guide_status = guide_status_payload(agent)
            except Exception:
                logger.debug("Guide status unavailable while workspace is pending", exc_info=True)

        def response_payload(payload):
            if guide_status is not None:
                payload["guide_status"] = guide_status
            return jsonify(payload)

        if agent is None:
            return response_payload({
                "success": False,
                "pending": True,
                "code": "workspace_agent_initializing",
                "message": "Case resources are being initialized.",
                "retry_after_ms": 250,
            }), 202
        hydration_error = str(getattr(agent, "_workspace_hydration_error", "") or "")
        guide_can_be_read = bool(
            guide_status
            and guide_status.get("available")
            and guide_status.get("mesh_loaded")
            and guide_status.get("state") in {"ready", "stale"}
        )
        if hydration_error:
            # A guide mesh can be independently decoded before another case
            # artifact fails. Do not block a truthful guide read in that case;
            # only reject it when the guide itself is not readable.
            if guide_can_be_read:
                return None
            return response_payload({
                "success": False,
                "pending": False,
                "code": "workspace_hydration_failed",
                "phase": getattr(agent, "_workspace_hydration_phase", "failed"),
                "error": hydration_error,
            }), 409
        if not getattr(agent, "_workspace_data_ready", True):
            # Metadata/CT hydration is allowed to continue in the background
            # while an already decoded guide is served to the Viewer.
            if guide_can_be_read:
                return None
            return response_payload({
                "success": False,
                "pending": True,
                "code": "workspace_hydration_pending",
                "message": "Case resources are still loading.",
                "phase": getattr(agent, "_workspace_hydration_phase", "artifacts"),
                "retry_after_ms": 250,
            }), 202
        return None

    def guide_metadata(agent: Any) -> Dict[str, Any]:
        from web.surgical_guide import _algorithm_planning_snapshot
        from web.planning_runs import active_planning_id, list_planning_runs

        needles = available_guide_needles(agent)
        current = current_guide(agent)
        current_status = guide_status_payload(agent)
        # Guide validity is judged against the immutable automatic planning
        # baseline, not the display snapshot. Adding or editing a manual
        # needle/seed changes the display snapshot's signature and would make
        # an otherwise-valid guide (which covers the algorithm needle paths)
        # silently disappear and its regenerate button lose its enabled state.
        algorithm_snapshot = _algorithm_planning_snapshot(agent)
        # The empty planning shape has a perfectly valid hash, but it is not
        # evidence that the current run has been restored.  Keep the
        # signature unknown during the metadata-only restore window so the
        # Viewer can use the explicit planning identity without mistaking an
        # empty snapshot for a geometry mismatch.
        signature = (
            planning_signature(algorithm_snapshot)
            if algorithm_snapshot.get("seeds") or algorithm_snapshot.get("needles")
            else ""
        )
        current_signature = (
            str(current.get("source_plan_signature") or "")
            if isinstance(current, dict) else ""
        )
        quality_ready = guide_bore_quality_ready(current)
        guide_matches_current_plan = None
        if current:
            if current_signature and signature:
                guide_matches_current_plan = current_signature == signature and quality_ready
            elif current_status.get("plan_matches_current") is not False:
                # The active Planning ID is already source-backed even when
                # its large geometry arrays are still being decoded.
                guide_matches_current_plan = True
        return {
            "versions": guide_version_summaries(agent),
            "active_planning_id": active_planning_id(agent.memory),
            "planning_options": list_planning_runs(agent.memory),
            "needle_options": needles,
            "can_generate": bool(needles),
            "current_plan_signature": signature,
            "guide_requires_regeneration": bool(current and not quality_ready),
            # A guide whose plan signature matches the current needle geometry
            # is authoritative regardless of its stored status. The status is
            # flipped to "stale" by operations unrelated to guide geometry
            # (e.g. reclassifying an OAR in the Data Tree) which must not hide
            # an otherwise valid guide. Signature equality is the real validity
            # signal; `status == "ready"` was dropped from this check because
            # stale guides with matching geometry must still be displayed.
            "guide_matches_current_plan": guide_matches_current_plan,
            "guide_status": current_status,
            "skin_surface": skin_surface_public_payload(agent),
        }

    def snapshot(agent: Any, reason: str, operation: Dict[str, Any] | None = None) -> None:
        store, user, session_id = request_case_context()
        if operation is not None:
            # Guide generation can encode a large mesh and STL sidecar. Keep
            # operation metadata durable, but let the workspace store debounce
            # and persist the heavy Agent checkpoint in its background timer.
            store.schedule_agent_checkpoint(
                user["id"], session_id, agent, "surgical_guide.operation", operation=operation,
            )
        else:
            store.schedule_agent_checkpoint(
                user["id"], session_id, agent, reason,
            )

    def publish_active_planning_guide(agent: Any) -> None:
        """Persist guide changes inside the currently selected Planning run.

        ``surgical_guide`` is still kept as the legacy active alias for the
        existing viewer endpoints, but the immutable Planning snapshot must be
        refreshed after generation/export or a restart would restore the old
        guide state for that run.
        """
        try:
            from web.planning_runs import publish_active_planning_state

            publish_active_planning_state(agent)
        except Exception:
            # Guide generation itself succeeded; a checkpoint retry can repair
            # the optional run snapshot without turning a valid mesh into a 500.
            logger.warning("Unable to publish guide into Planning snapshot", exc_info=True)

    @app.route("/api/surgical-guides", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_surgical_guide_status():
        try:
            _store, _user, _session_id = request_case_context()
            agent = get_agent()
            pending = workspace_data_pending(agent)
            if pending is not None:
                return pending
            metadata = guide_metadata(agent)
            return jsonify({"success": True, **guide_public_payload(current_guide(agent)), **metadata})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 400

    @app.route("/api/surgical-guides/mesh", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_surgical_guide_mesh():
        try:
            _store, _user, _session_id = request_case_context()
            agent = get_agent()
            pending = workspace_data_pending(agent)
            if pending is not None:
                return pending
            requested_version = request.args.get("version")
            state = current_guide(agent, requested_version)
            metadata = guide_metadata(agent)
            # The version selector may intentionally request an older guide;
            # expose its status alongside the selected mesh rather than
            # silently describing the active version as if it were selected.
            metadata["guide_status"] = guide_status_payload(agent, requested_version)
            return jsonify({"success": True, **guide_public_payload(state, include_mesh=True), **metadata})
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
            requested_planning_id = str(data.get("planning_id") or "").strip()
            if requested_planning_id:
                from web.planning_runs import activate_planning_run, active_planning_id
                if requested_planning_id != str(active_planning_id(agent.memory) or ""):
                    activate_planning_run(agent, requested_planning_id)
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
            publish_active_planning_guide(agent)
            snapshot(agent, "surgical_guide.ready", {
                "state": "ready",
                "message": "Patient-specific puncture guide generated",
                "updated_at": time.time(),
                "checkpoint": {"kind": "surgical_guide", "version": state["version"]},
            })
            logger.info("Generated surgical guide v%s for session %s", state["version"], session_id)
            return jsonify({
                "success": True,
                **guide_public_payload(state, include_mesh=True),
                **guide_metadata(agent),
                "guide_status": guide_status_payload(agent),
            })
        except Exception as exc:
            logger.exception("Surgical guide generation failed")
            try:
                # Skin extraction precedes guide CSG. Preserve a valid skin
                # segmentation in the current Planning even when the printable
                # mesh fails its manufacturability checks.
                publish_active_planning_guide(agent)
                snapshot(agent, "surgical_guide.failed", {
                    "state": "failed",
                    "message": f"Puncture guide generation failed: {exc}",
                    "error": str(exc),
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
            requested_version = (request.get_json(silent=True) or {}).get("version")
            pending = workspace_data_pending(agent)
            if pending is not None:
                return pending
            state = current_guide(agent, requested_version)
            status = guide_status_payload(agent, requested_version)
            if not state or status.get("state") != "ready" or not status.get("mesh_loaded"):
                if status.get("state") in {"restoring", "persisted_not_loaded", "generating"}:
                    raise SurgicalGuideError(
                        "The Surgical Guide is still being restored; retry after its mesh is loaded"
                    )
                raise SurgicalGuideError("Generate a current puncture guide before export")
            if not guide_bore_quality_ready(state):
                raise SurgicalGuideError(
                    "This guide was generated by an older geometry pipeline; regenerate it before STL export"
                )
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
                publish_active_planning_guide(agent)
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
