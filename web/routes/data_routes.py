"""Data Tree mutation and unified export APIs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from flask import jsonify, request, send_file, session as flask_session

from web.auth import current_user
from web.export_service import ExportError, ExportJobManager, ExportService, _planning_snapshot
from web.planning_runs import publish_active_planning_state
from web.server_support import rate_limit, require_api_key
from web.structure_service import (
    StructureError,
    _batch_memory_update,
    delete_structure,
    delete_structures,
    reclassify_generic_segmentation_masks,
    reclassify_structure,
    reclassify_structures,
    resolve_structure_object_id,
    structure_catalog,
)
from web.workspace_store import WorkspaceError, WorkspaceStore


logger = logging.getLogger(__name__)


def _generic_mask_object_id(value: Any) -> str:
    """Normalize a generic segmentation mask to its stable Data Tree ID."""
    raw = str(value or "").strip()
    if raw.startswith("mask:"):
        return raw
    if raw.startswith("mask_"):
        # The legacy DOM id is ``mask_<id>`` while the persisted object id is
        # ``mask:<id>``. Keep both spellings interchangeable at the API
        # boundary so a context-menu action cannot address a phantom object.
        return f"mask:{raw[5:]}"
    return raw


def _public_generic_mask(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Return mask metadata without copying the potentially large voxel array."""
    return {
        key: value
        for key, value in dict(entry).items()
        if key not in {"mask_array", "voxels", "data"}
    }


def _reclassify_generic_masks(
    memory: Any,
    object_ids: list[str],
    classification: str,
) -> list[Dict[str, Any]]:
    """Return the public metadata for generic masks after a real move."""
    destination = str(classification or "").strip().lower()
    if destination not in {"ctv", "oar"}:
        raise StructureError("Generic masks can only move to CTV or OAR")
    requested = {_generic_mask_object_id(value) for value in object_ids}
    if not requested:
        raise StructureError("object_ids must contain at least one mask")
    existing = memory.retrieve("generic_segmentation_masks") or []
    if not isinstance(existing, list):
        existing = []
    matched: list[Dict[str, Any]] = []
    for raw_entry in existing:
        if not isinstance(raw_entry, Mapping):
            continue
        entry = dict(raw_entry)
        mask_id = str(entry.get("mask_id") or "").strip()
        stable_id = _generic_mask_object_id(entry.get("object_id") or mask_id)
        if stable_id in requested or _generic_mask_object_id(mask_id) in requested:
            matched.append(_public_generic_mask(entry))
    if len(matched) != len(requested):
        missing = sorted(requested - {
            _generic_mask_object_id(item.get("object_id") or item.get("mask_id"))
            for item in matched
        })
        raise StructureError(f"Generic mask was not found: {missing[0] if missing else 'unknown'}")
    return matched


def register_data_routes(
    app: Any,
    store: WorkspaceStore,
    get_agent_for_owner: Callable[..., Any],
) -> None:
    export_jobs = ExportJobManager(store, get_agent_for_owner)
    app.extensions["brachybot_export_jobs"] = export_jobs

    def context(
        explicit_session_id: Optional[str] = None,
        *,
        hydrate: bool = True,
    ) -> tuple[Dict[str, Any], str, Any]:
        user = current_user(store)
        if not user:
            raise WorkspaceError("Authentication required")
        data = request.get_json(silent=True) if request.is_json else {}
        session_id = str(
            explicit_session_id
            or request.headers.get("X-BrachyBot-Session")
            or (data or {}).get("session_id")
            or request.args.get("session_id")
            or flask_session.get("bb_session_id")
            or ""
        ).strip()
        if not session_id:
            raise WorkspaceError("No case session is selected")
        store.get_session(user["id"], session_id)
        agent = get_agent_for_owner(user, session_id) if hydrate else None
        if hydrate and agent is None:
            raise WorkspaceError("Case workspace is unavailable")
        return user, session_id, agent

    def request_user() -> Dict[str, Any]:
        user = current_user(store)
        if not user:
            raise WorkspaceError("Authentication required")
        return user

    def error_response(exc: Exception):
        message = str(exc).lower()
        status = 404 if (
            isinstance(exc, (StructureError, ExportError))
            and any(token in message for token in ("not found", "no longer exists", "missing"))
        ) else 400
        return jsonify({"success": False, "error": str(exc)}), status

    def mark_report_stale(user_id: str, session_id: str, reason: str) -> None:
        snapshot = store.load_snapshot(user_id, session_id)
        report = snapshot.get("report")
        if not isinstance(report, Mapping) or not report:
            return
        store.replace_snapshot_section(
            user_id,
            session_id,
            "report",
            {
                **dict(report),
                "status": "stale",
                "stale_reason": reason,
            },
            reason="report.marked_stale",
        )

    @app.route("/api/data/catalog", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_data_catalog():
        try:
            user, session_id, agent = context()
            service = ExportService(store)
            catalog = service.public_catalog(user["id"], session_id, agent)
            return jsonify({
                "success": True,
                **catalog,
                "structures": structure_catalog(agent.memory),
            })
        except Exception as exc:
            return error_response(exc)

    @app.route("/api/data/structures/<path:object_id>/classification", methods=["PATCH"])
    @require_api_key
    @rate_limit
    def api_structure_classification(object_id: str):
        try:
            user, session_id, agent = context()
            payload = request.get_json(silent=True) or {}
            stable_id = resolve_structure_object_id(agent.memory, object_id)
            effective = reclassify_structure(
                agent.memory, stable_id, str(payload.get("classification") or ""),
            )
            mark_report_stale(
                str(user["id"]), session_id, "Structure classification changed",
            )
            store._audit(user["id"], session_id, "structure.reclassified", {
                "object_id": stable_id,
                "classification": payload.get("classification"),
            })
            return jsonify({
                "success": True,
                "session_id": session_id,
                "object_id": stable_id,
                "structures": effective.public_catalog(),
                "invalidated": [
                    "dose", "dvh", "evaluation", "report", "surgical_guide",
                ],
                "artifact_status": agent.memory.retrieve("structure_artifact_status") or {},
            })
        except Exception as exc:
            logger.warning("Structure classification failed: %s", exc)
            return error_response(exc)

    @app.route("/api/data/structures/classification", methods=["PATCH"])
    @require_api_key
    @rate_limit
    def api_structures_classification():
        try:
            user, session_id, agent = context()
            payload = request.get_json(silent=True) or {}
            raw_ids = payload.get("object_ids")
            if not isinstance(raw_ids, list):
                raise StructureError("object_ids must be a list")
            stable_ids = [
                resolve_structure_object_id(agent.memory, str(object_id))
                for object_id in raw_ids
            ]
            classification = str(payload.get("classification") or "")
            effective = reclassify_structures(
                agent.memory, stable_ids, classification,
            )
            mark_report_stale(
                str(user["id"]), session_id, "Structure classification changed",
            )
            store._audit(user["id"], session_id, "structures.reclassified", {
                "object_ids": stable_ids,
                "classification": classification,
            })
            return jsonify({
                "success": True,
                "session_id": session_id,
                "object_ids": stable_ids,
                "structures": effective.public_catalog(),
                "invalidated": [
                    "dose", "dvh", "evaluation", "report", "surgical_guide",
                ],
                "artifact_status": agent.memory.retrieve("structure_artifact_status") or {},
            })
        except Exception as exc:
            logger.warning("Structure classification failed: %s", exc)
            return error_response(exc)

    @app.route("/api/data/generic-masks/classification", methods=["PATCH"])
    @require_api_key
    @rate_limit
    def api_generic_masks_classification():
        try:
            user, session_id, agent = context()
            payload = request.get_json(silent=True) or {}
            raw_ids = payload.get("object_ids")
            if not isinstance(raw_ids, list):
                raise StructureError("object_ids must be a list")
            classification = str(payload.get("classification") or "")
            stable_ids = [_generic_mask_object_id(value) for value in raw_ids]
            effective = reclassify_generic_segmentation_masks(
                agent.memory, stable_ids, classification,
            )
            updated = _reclassify_generic_masks(
                agent.memory, stable_ids, classification,
            )
            mark_report_stale(
                str(user["id"]), session_id, "Generic segmentation mask classification changed",
            )
            store._audit(user["id"], session_id, "generic_masks.reclassified", {
                "object_ids": [_generic_mask_object_id(value) for value in raw_ids],
                "classification": classification,
            })
            return jsonify({
                "success": True,
                "session_id": session_id,
                "object_ids": [str(item["object_id"]) for item in updated],
                "generic_masks": updated,
                "structures": effective.public_catalog(),
                "invalidated": [
                    "dose", "dvh", "evaluation", "report", "surgical_guide",
                ],
                "artifact_status": agent.memory.retrieve("structure_artifact_status") or {},
            })
        except Exception as exc:
            logger.warning("Generic mask classification failed: %s", exc)
            return error_response(exc)

    @app.route("/api/data/objects/batch-delete", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_batch_delete_data_objects():
        try:
            user, session_id, agent = context()
            payload = request.get_json(silent=True) or {}
            raw_ids = payload.get("object_ids")
            if not isinstance(raw_ids, list) or not raw_ids:
                raise ExportError("object_ids must contain at least one object")
            ids = [str(value) for value in raw_ids]
            # Parent deletion is intentionally destructive.  A leaf structure
            # must never be interpreted as a request to delete its OAR/CTV
            # collection because of a stale browser selection or legacy group
            # alias.  Callers must explicitly opt in to recursive group
            # deletion; the Data Tree group menu sends concrete child IDs.
            recursive_groups = bool(payload.get("recursive_groups"))
            group_aliases = {
                "ctv", "oar", "group:structures:ctv", "group:structures:oar",
                "planning", "group:planning", "group:planning:needles",
                "group:planning:seeds", "group:dose", "group:dose:isosurfaces",
                "group:structures:masks",
            }
            requested_groups = sorted(set(ids) & group_aliases)
            if requested_groups and not recursive_groups:
                raise ExportError(
                    "Recursive group deletion requires explicit confirmation"
                )
            available = {
                item.object_id
                for item in ExportService(store).catalog(
                    str(user["id"]), session_id, agent,
                )
            }
            available.update({
                "ct", "ctv", "oar", "planning", "dose", "dose_overlay",
                "dvh", "report", "group:planning",
                "skin_surface", "skin_surface:guide",
                "group:planning:trajectories", "group:planning:needles",
                "group:planning:seeds", "group:dose",
                "group:dose:isosurfaces", "group:report",
                "group:structures:masks",
            })
            nonstructure_missing = [
                value for value in ids
                if not value.startswith(("structure:", "organ_", "ctv_", "mask:", "mask_"))
                and value not in available
            ]
            if nonstructure_missing:
                raise ExportError(
                    f"Data object was not found: {nonstructure_missing[0]}"
                )
            structure_ids = [
                resolve_structure_object_id(agent.memory, value)
                for value in ids
                if value.startswith(("structure:", "organ_", "ctv_"))
            ]
            generic_mask_ids = [
                value for value in ids
                if value.startswith(("mask:", "mask_"))
            ]
            results = []
            if structure_ids:
                effective = delete_structures(agent.memory, structure_ids)
                results.extend({
                    "object_id": value,
                    "invalidated": [
                        "dose", "dvh", "evaluation", "report", "surgical_guide",
                    ],
                } for value in structure_ids)
            else:
                effective = None
            for object_id in ids:
                if object_id.startswith(("structure:", "organ_", "ctv_", "mask:", "mask_")):
                    continue
                results.append(_delete_object(
                    store, user, session_id, agent, object_id,
                ))
            for object_id in generic_mask_ids:
                results.append(_delete_object(
                    store, user, session_id, agent, object_id,
                ))
            if any(
                "report" in (result.get("invalidated") or [])
                for result in results
                if isinstance(result, Mapping)
            ):
                mark_report_stale(
                    str(user["id"]), session_id, "A related data object was deleted",
                )
            store._audit(user["id"], session_id, "data.batch_deleted", {
                "object_ids": ids,
            })
            return jsonify({
                "success": True,
                "session_id": session_id,
                "results": results,
                "structures": effective.public_catalog() if effective else structure_catalog(agent.memory),
                "artifact_status": agent.memory.retrieve("structure_artifact_status") or {},
            })
        except Exception as exc:
            logger.warning("Batch data deletion failed: %s", exc)
            return error_response(exc)

    @app.route("/api/data/objects/<path:object_id>", methods=["DELETE"])
    @require_api_key
    @rate_limit
    def api_delete_data_object(object_id: str):
        try:
            user, session_id, agent = context()
            result = _delete_object(store, user, session_id, agent, object_id)
            if "report" in (result.get("invalidated") or []):
                mark_report_stale(
                    str(user["id"]), session_id, "A related data object was deleted",
                )
            store._audit(user["id"], session_id, "data.deleted", {
                "object_id": object_id,
                "result": result,
            })
            return jsonify({"success": True, "session_id": session_id, **result})
        except Exception as exc:
            logger.warning("Data deletion failed: %s", exc)
            return error_response(exc)

    @app.route("/api/data/exports", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_create_export():
        try:
            user, session_id, agent = context()
            payload = request.get_json(silent=True) or {}
            service = ExportService(store)
            catalog = service.catalog(user["id"], session_id, agent)
            available = {item.object_id: item for item in catalog}
            raw_selections = payload.get("selections")
            if not isinstance(raw_selections, list):
                raw_selections = [
                    {"object_id": item.object_id, "format": item.default_format}
                    for item in catalog
                ]
            selections = []
            for row in raw_selections:
                if not isinstance(row, Mapping):
                    continue
                object_key = str(row.get("object_id") or "")
                item = available.get(object_key)
                if item is None:
                    continue
                selections.append({
                    "object_id": object_key,
                    "format": str(row.get("format") or item.default_format),
                })
            if not selections:
                raise ExportError("Select at least one available data object")
            session_record = store.get_session(user["id"], session_id)
            job = export_jobs.create(user, session_id, selections, session_record.title)
            store._audit(user["id"], session_id, "export.started", {
                "job_id": job.job_id,
                "objects": [row["object_id"] for row in selections],
            })
            return jsonify({"success": True, "job": job.public_dict()}), 202
        except Exception as exc:
            return error_response(exc)

    @app.route("/api/data/exports/<job_id>", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_export_status(job_id: str):
        try:
            user = request_user()
            job = export_jobs.get(user["id"], job_id)
            payload = job.public_dict()
            if job.zip_path:
                payload["download_url"] = f"/api/data/exports/{job_id}/download"
                payload["file_base_url"] = f"/api/data/exports/{job_id}/files/"
            return jsonify({"success": True, "job": payload})
        except Exception as exc:
            return error_response(exc)

    @app.route("/api/data/exports/<job_id>/cancel", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_cancel_export(job_id: str):
        try:
            user = request_user()
            return jsonify({"success": True, "job": export_jobs.cancel(user["id"], job_id).public_dict()})
        except Exception as exc:
            return error_response(exc)

    @app.route("/api/data/exports/<job_id>/download", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_download_export(job_id: str):
        try:
            user = request_user()
            job = export_jobs.get(user["id"], job_id)
            path = Path(job.zip_path)
            if job.status not in {"completed", "completed_with_errors", "cancelled"} or not path.is_file():
                raise ExportError("Export archive is not ready")
            return send_file(path, as_attachment=True, download_name=path.name, mimetype="application/zip")
        except Exception as exc:
            return error_response(exc)

    @app.route("/api/data/exports/<job_id>/files/<path:relative_path>", methods=["GET"])
    @require_api_key
    @rate_limit
    def api_download_export_file(job_id: str, relative_path: str):
        try:
            user = request_user()
            job = export_jobs.get(user["id"], job_id)
            root = Path(job.export_root).resolve()
            candidate = (root / relative_path).resolve()
            candidate.relative_to(root)
            if not candidate.is_file():
                raise ExportError("Exported file was not found")
            return send_file(candidate, as_attachment=True, download_name=candidate.name)
        except Exception as exc:
            return error_response(exc)


def _delete_object(
    store: WorkspaceStore,
    user: Mapping[str, Any],
    session_id: str,
    agent: Any,
    object_id: str,
) -> Dict[str, Any]:
    memory = agent.memory
    candidate = str(object_id or "").strip()

    if candidate.startswith("annotation:"):
        annotation_id = candidate.split(":", 1)[1]
        snapshot = store.load_snapshot(str(user["id"]), session_id)
        ui = dict(snapshot.get("ui") or {})
        has_state_wrapper = isinstance(ui.get("state"), Mapping)
        ui_state = dict(ui.get("state") or {}) if has_state_wrapper else dict(ui)
        viewer = dict(ui_state.get("viewer") or {})
        rows = list(viewer.get("annotations") or [])
        remaining = [
            row for index, row in enumerate(rows)
            if not (
                isinstance(row, Mapping)
                and str(row.get("id") or f"annotation_{index + 1}") == annotation_id
            )
        ]
        if len(remaining) == len(rows):
            raise ExportError("Annotation was not found")
        viewer["annotations"] = remaining
        ui_state["viewer"] = viewer
        updated_ui = {**ui, "state": ui_state} if has_state_wrapper else ui_state
        store.replace_snapshot_section(
            str(user["id"]), session_id, "ui", updated_ui,
            reason="annotation.deleted",
        )
        return {"object_id": candidate, "invalidated": ["annotation", "report"]}

    if candidate.startswith(("screenshot:", "figure:")):
        filename = Path(candidate.split(":", 1)[1]).name
        root = store.workspace_root(str(user["id"]), session_id)
        path = (root / "screenshots" / filename).resolve()
        path.relative_to((root / "screenshots").resolve())
        if not path.is_file():
            raise ExportError("Screenshot was not found")
        path.unlink()
        # The bytes are gone even when no chat attachment referenced the
        # file (in which case no snapshot write below invalidates the
        # quota cache), so drop the cached storage total here.
        store.invalidate_storage_usage(str(user["id"]))
        snapshot = store.load_snapshot(str(user["id"]), session_id)
        chat = dict(snapshot.get("chat") or {})
        changed = False
        for message in chat.get("messages") or []:
            if not isinstance(message, dict):
                continue
            attachments = message.get("attachments")
            if not isinstance(attachments, list):
                continue
            filtered = [
                item for item in attachments
                if filename not in str(
                    item.get("url") if isinstance(item, Mapping) else item
                )
            ]
            if len(filtered) != len(attachments):
                message["attachments"] = filtered
                changed = True
        if changed:
            store.replace_snapshot_section(
                str(user["id"]), session_id, "chat", chat,
                reason="screenshot.deleted",
            )
        report = dict(snapshot.get("report") or {})
        form_wrapper = isinstance(report.get("form"), Mapping)
        report_form = dict(report.get("form") or {}) if form_wrapper else dict(report)
        figures = list(report_form.get("figures") or [])
        remaining_figures = [
            figure for figure in figures
            if not (
                isinstance(figure, Mapping)
                and filename in str(
                    figure.get("_serverUrl") or figure.get("dataUrl") or ""
                )
            )
        ]
        if len(remaining_figures) != len(figures):
            report_form["figures"] = remaining_figures
            updated_report = (
                {**report, "form": report_form}
                if form_wrapper else report_form
            )
            store.replace_snapshot_section(
                str(user["id"]), session_id, "report", updated_report,
                reason="report.figure.deleted",
            )
        return {"object_id": candidate, "invalidated": ["screenshot", "report"]}

    if candidate in {"group:structures:ctv", "ctv"}:
        selected = [
            item["object_id"]
            for item in structure_catalog(memory)
            if item["classification"] == "ctv"
        ]
        effective = delete_structures(memory, selected)
        return {
            "object_id": candidate,
            "structures": effective.public_catalog(),
            "invalidated": ["dose", "dvh", "evaluation", "report", "surgical_guide"],
        }

    if candidate in {"group:structures:oar", "oar"}:
        selected = [
            item["object_id"]
            for item in structure_catalog(memory)
            if item["classification"] == "oar"
        ]
        effective = delete_structures(memory, selected)
        return {
            "object_id": candidate,
            "structures": effective.public_catalog(),
            "invalidated": ["dose", "dvh", "evaluation", "report", "surgical_guide"],
        }

    if candidate.startswith(("structure:", "organ_", "ctv_")):
        stable_id = resolve_structure_object_id(memory, candidate)
        effective = delete_structure(memory, stable_id)
        return {
            "object_id": stable_id,
            "structures": effective.public_catalog(),
            "invalidated": ["dose", "dvh", "evaluation", "report", "surgical_guide"],
        }

    if candidate.startswith(("mask:", "mask_")):
        stable_id = _generic_mask_object_id(candidate)
        mask_id = stable_id.split(":", 1)[1]
        existing = memory.retrieve("generic_segmentation_masks") or []
        if not isinstance(existing, list):
            existing = []
        remaining = [
            item for item in existing
            if not isinstance(item, Mapping)
            or _generic_mask_object_id(item.get("object_id") or item.get("mask_id")) != stable_id
        ]
        if len(remaining) == len(existing):
            raise ExportError("Generic segmentation mask was not found")
        promoted = any(
            isinstance(item, Mapping)
            and _generic_mask_object_id(item.get("object_id") or item.get("mask_id")) == stable_id
            and str(item.get("classification") or item.get("moved_to") or "").lower() in {"ctv", "oar"}
            for item in existing
        )
        effective = delete_structure(memory, stable_id) if promoted else None
        memory.store("generic_segmentation_masks", remaining)
        if str(memory.retrieve("generic_segmentation_latest") or "") == mask_id:
            memory.store(
                "generic_segmentation_latest",
                str(remaining[-1].get("mask_id") or "") if remaining else None,
            )
        invalidated = ["generic_mask"]
        if promoted:
            invalidated.extend(["dose", "dvh", "evaluation", "report", "surgical_guide"])
        return {
            "object_id": stable_id,
            "structures": effective.public_catalog() if effective else None,
            "invalidated": invalidated,
        }

    if candidate in {"skin_surface", "skin_surface:guide"}:
        if (
            memory.retrieve("skin_surface") is None
            and memory.retrieve("skin_surface_mask") is None
        ):
            raise ExportError("Guide skin surface was not found")
        _batch_memory_update(
            memory,
            {},
            removals=("skin_surface", "skin_surface_mask"),
        )
        # The skin surface is planning-owned. Refreshing the active namespaced
        # snapshot prevents it from reappearing after a Planning switch.
        publish_active_planning_state(agent)
        return {
            "object_id": "skin_surface:guide",
            "invalidated": ["skin_surface", "report"],
        }

    if candidate in {"image:ct", "ct"}:
        root = store.workspace_root(str(user["id"]), session_id)
        for path_key in ("ct_path", "ct_image_path"):
            raw_path = memory.retrieve(path_key)
            if not raw_path:
                continue
            try:
                path = Path(str(raw_path)).resolve()
                path.relative_to(root.resolve())
                path.unlink(missing_ok=True)
            except (OSError, ValueError):
                continue
        with memory._lock:
            memory.planning_results.clear()
            memory._planning_versions.clear()
            memory.conversation_state["data_available"] = []
            memory.conversation_state["ctv_segmented"] = False
            memory.conversation_state["oar_segmented"] = False
            memory.conversation_state["planning_completed"] = False
        memory._notify_persistence("data.delete:ct")
        store.replace_snapshot_section(
            str(user["id"]), session_id, "report", {}, reason="report.cleared_with_ct",
        )
        report_root = root / "artifacts" / "reports"
        if report_root.is_dir():
            for report_path in report_root.iterdir():
                if report_path.is_file():
                    report_path.unlink()
        # The report PDFs are removed after replace_snapshot_section() has
        # completed its own quota bookkeeping.  A concurrent usage read can
        # therefore repopulate the cache before these final unlinks; always
        # invalidate after the last direct filesystem mutation.
        store.invalidate_storage_usage(str(user["id"]))
        return {"object_id": "image:ct", "invalidated": ["all_case_data"]}

    if candidate.startswith("needle:") or candidate.startswith("needle_"):
        needle_id = candidate.split(":", 1)[-1]
        snapshot = _planning_snapshot(memory)
        before = list(snapshot["needles"])
        removed = next((row for row in before if str(row.get("id")) == needle_id), None)
        if removed is None:
            raise ExportError("Needle was not found")
        trajectory_id = str(removed.get("trajectory_id") or removed.get("id") or "")
        needles = [row for row in before if str(row.get("id")) != needle_id]
        seeds = [
            row for row in snapshot["seeds"]
            if str(row.get("trajectory_id") or row.get("needle_id") or "") != trajectory_id
        ]
        version = int(memory.retrieve("manual_plan_version") or 0) + 1
        _batch_memory_update(memory, {
            "manual_needles": needles,
            "manual_seeds": seeds,
            "manual_plan_active": True,
            "manual_plan_version": version,
            "manual_artifact_status": _stale_status("needle deleted", version),
        })
        return {
            "object_id": needle_id,
            "removed_seeds": len(snapshot["seeds"]) - len(seeds),
            "invalidated": ["dose", "dvh", "report", "surgical_guide"],
        }

    if candidate == "group:planning:needles":
        snapshot = _planning_snapshot(memory)
        version = int(memory.retrieve("manual_plan_version") or 0) + 1
        _batch_memory_update(memory, {
            "manual_needles": [],
            "manual_seeds": [],
            "manual_plan_active": True,
            "manual_plan_version": version,
            "manual_artifact_status": _stale_status("all needles deleted", version),
        })
        return {
            "object_id": candidate,
            "removed_needles": len(snapshot["needles"]),
            "removed_seeds": len(snapshot["seeds"]),
            "invalidated": ["dose", "dvh", "report", "surgical_guide"],
        }

    if candidate.startswith("seed:") or candidate.startswith("seed_"):
        seed_id = candidate.split(":", 1)[-1]
        snapshot = _planning_snapshot(memory)
        seeds = [row for row in snapshot["seeds"] if str(row.get("id")) != seed_id]
        if len(seeds) == len(snapshot["seeds"]):
            raise ExportError("Seed was not found")
        version = int(memory.retrieve("manual_plan_version") or 0) + 1
        _batch_memory_update(memory, {
            "manual_needles": snapshot["needles"],
            "manual_seeds": seeds,
            "manual_plan_active": True,
            "manual_plan_version": version,
            "manual_artifact_status": _stale_status("seed deleted", version),
        })
        return {"object_id": seed_id, "invalidated": ["dose", "dvh", "report"]}

    if candidate == "group:planning:seeds":
        snapshot = _planning_snapshot(memory)
        version = int(memory.retrieve("manual_plan_version") or 0) + 1
        _batch_memory_update(memory, {
            "manual_needles": snapshot["needles"],
            "manual_seeds": [],
            "manual_plan_active": True,
            "manual_plan_version": version,
            "manual_artifact_status": _stale_status("all seeds deleted", version),
        })
        return {
            "object_id": candidate,
            "removed_seeds": len(snapshot["seeds"]),
            "invalidated": ["dose", "dvh", "report"],
        }

    if candidate.startswith("trajectory:") or candidate.startswith("trajectory_"):
        trajectory_id = candidate.split(":", 1)[-1]
        trajectories = [
            row for row in (memory.retrieve("trajectories") or [])
            if isinstance(row, Mapping)
        ]
        remaining = [
            row for index, row in enumerate(trajectories)
            if str(row.get("id") or f"trajectory_{index + 1}") != trajectory_id
        ]
        if len(remaining) == len(trajectories):
            raise ExportError("Trajectory was not found")
        snapshot = _planning_snapshot(memory)
        needles = [
            row for row in snapshot["needles"]
            if str(row.get("trajectory_id") or "") != trajectory_id
        ]
        seeds = [
            row for row in snapshot["seeds"]
            if str(row.get("trajectory_id") or row.get("needle_id") or "") != trajectory_id
        ]
        version = int(memory.retrieve("manual_plan_version") or 0) + 1
        _batch_memory_update(memory, {
            "trajectories": remaining,
            "manual_needles": needles,
            "manual_seeds": seeds,
            "manual_plan_active": True,
            "manual_plan_version": version,
            "manual_artifact_status": _stale_status("trajectory deleted", version),
        })
        return {
            "object_id": trajectory_id,
            "invalidated": ["planning", "dose", "dvh", "report", "surgical_guide"],
        }

    if candidate == "group:planning:trajectories":
        snapshot = _planning_snapshot(memory)
        version = int(memory.retrieve("manual_plan_version") or 0) + 1
        _batch_memory_update(memory, {
            "trajectories": [],
            "refined_trajectories": [],
            "manual_needles": [],
            "manual_seeds": [],
            "manual_plan_active": True,
            "manual_plan_version": version,
            "manual_artifact_status": _stale_status("all trajectories deleted", version),
        })
        return {
            "object_id": candidate,
            "removed_needles": len(snapshot["needles"]),
            "removed_seeds": len(snapshot["seeds"]),
            "invalidated": ["planning", "dose", "dvh", "report", "surgical_guide"],
        }

    if candidate.startswith(("dose_iso_", "dose_iso:")):
        threshold = candidate.split(":", 1)[-1].removeprefix("dose_iso_")
        deleted = {
            str(value)
            for value in (memory.retrieve("deleted_dose_iso_levels") or [])
        }
        deleted.add(str(threshold))
        _batch_memory_update(memory, {"deleted_dose_iso_levels": sorted(deleted)})
        return {"object_id": candidate, "invalidated": ["dose_iso_surface"]}

    if candidate in {"group:dose:isosurfaces", "dose_isosurfaces"}:
        _batch_memory_update(memory, {"deleted_dose_iso_levels": ["all"]})
        return {"object_id": candidate, "invalidated": ["dose_iso_surface"]}

    if candidate in {"dose:volume", "dose", "dose_overlay", "group:dose"}:
        keys = (
            "dose_distribution", "dose_distribution_gy", "dose_metrics",
            "dvh_data", "metrics", "plan_score", "radiation_volume",
        )
        _batch_memory_update(memory, {}, removals=keys)
        return {"object_id": candidate, "invalidated": ["dose", "dvh", "report"]}

    if candidate in {"dvh:data", "dvh:curve", "dvh"}:
        _batch_memory_update(memory, {}, removals=("dvh_data",))
        metrics = dict(memory.retrieve("dose_metrics") or {})
        metrics.pop("dvh_data", None)
        _batch_memory_update(memory, {"dose_metrics": metrics})
        return {"object_id": candidate, "invalidated": ["dvh", "report"]}

    if candidate.startswith("surgical_guide"):
        _batch_memory_update(
            memory, {}, removals=("surgical_guide", "surgical_guide_versions"),
        )
        return {"object_id": candidate, "invalidated": ["surgical_guide", "report"]}

    if candidate == "report:pdf":
        report_root = (
            store.workspace_root(str(user["id"]), session_id)
            / "artifacts" / "reports"
        )
        pdfs = sorted(
            (path for path in report_root.glob("*.pdf") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        ) if report_root.is_dir() else []
        if not pdfs:
            raise ExportError("Report PDF was not found")
        pdfs[0].unlink()
        store.invalidate_storage_usage(str(user["id"]))
        return {"object_id": candidate, "invalidated": ["report_pdf"]}

    if candidate in {"report:data", "report", "group:report"}:
        store.replace_snapshot_section(
            str(user["id"]), session_id, "report", {}, reason="report.deleted",
        )
        if candidate == "group:report":
            report_root = (
                store.workspace_root(str(user["id"]), session_id)
                / "artifacts" / "reports"
            )
            if report_root.is_dir():
                for path in report_root.glob("*.pdf"):
                    if path.is_file():
                        path.unlink()
            # See the CT deletion path above: snapshot replacement and PDF
            # removal are separate filesystem mutations, so the final unlink
            # needs its own invalidation boundary.
            store.invalidate_storage_usage(str(user["id"]))
        return {"object_id": candidate, "invalidated": ["report"]}

    if candidate in {"planning", "group:planning"}:
        _batch_memory_update(memory, {}, removals=(
            "manual_needles", "manual_seeds", "algorithm_plan_snapshot",
            "seed_plan", "seed_plan_serialized", "verified_needle_geometry",
            "trajectories", "refined_trajectories", "dose_distribution",
            "dose_distribution_gy", "dose_metrics", "dvh_data", "metrics",
            "surgical_guide", "surgical_guide_versions",
        ))
        return {"object_id": candidate, "invalidated": ["planning", "dose", "dvh", "guide", "report"]}

    raise ExportError("This data type does not currently support deletion")


def _stale_status(reason: str, planning_version: int) -> Dict[str, Any]:
    return {
        "dose": "stale",
        "dvh": "stale",
        "report": "stale",
        "quality_check": "stale",
        "surgical_guide": "stale",
        "reason": reason,
        "planning_version": planning_version,
    }
