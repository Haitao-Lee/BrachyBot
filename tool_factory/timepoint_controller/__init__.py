"""Owned timepoint catalog operations and fenced browser selection requests."""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping

from tool_factory import BaseTool, ToolResult
from web.timepoints import TimepointError, timepoint_id, title
from web.timepoint_messages import resolve_timepoint_language, timepoint_message, timepoint_error
from agent_runtime.execution_authorization import tool_call_is_mutating
from agent_runtime.timepoint_targets import capture_catalog_target, readset_dict, require_human_target
from web.workspace_store import WorkspaceError


class TimepointControllerTool(BaseTool):
    name = "timepoint_controller"
    description = (
        "Manage the bound Session's timepoints: metadata, create, rename, update stage/source "
        "metadata, delete_impact, recoverable delete, restore, select, or explain the workflow. "
        "Discover exact stable IDs with timepoint_inspector, including deleted entries for restore. "
        "Only exact owned catalog identities are accepted. A different mutation target needs the "
        "current human's exact unique title/ID or a server-confirmed exact-call receipt. A model ID "
        "alone does not confirm it. Create an intraoperative timepoint with its explicit preoperative "
        "source. Soft delete never undoes surgery or deletes a physical implant; dependencies and "
        "running tasks block deletion. Selection is accepted pending browser mount and affects "
        "future submissions, not sibling calls in the current turn. No clinical computation runs here."
    )
    input_schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["metadata", "create", "rename", "update", "delete_impact", "delete", "restore", "select", "explain"]},
            "timepoint_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
            "title": {"type": "string", "minLength": 1, "maxLength": 160},
            "stage": {"type": "string", "enum": ["preoperative", "intraoperative"]},
            "preoperative_timepoint_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
            "expected_revision": {"type": "integer", "minimum": 0,
                                  "description": "Optional observed catalog revision; stale revisions fail."},
            "patch": {"type": "object", "additionalProperties": False, "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 160},
                "stage": {"type": "string", "enum": ["preoperative", "intraoperative"]},
                "preoperative_timepoint_id": {"type": ["string", "null"]},
                "previous_intraoperative_timepoint_id": {"type": ["string", "null"]},
                "episode_id": {"type": ["string", "null"]},
            }},
        }, "required": ["action"],
    }

    def __init__(self, agent):
        self._agent = agent

    def is_available(self):
        config = getattr(self._agent, "config", {}) or {}
        return bool(getattr(self._agent, "_workspace_store", None) and
                    config.get("_workspace_owner_id") and config.get("_workspace_session_id"))

    def _execute(self, **kwargs):
        agent = self._agent
        config = getattr(agent, 'config', {}) or {}
        facade = getattr(agent, '_workspace_store', None)
        store = getattr(facade, 'raw', facade)
        owner, sid = config.get('_workspace_owner_id'), config.get('_workspace_session_id')
        if store is not None and owner and sid:
            with store._case_guard(owner, sid):
                return self._execute_catalog(**kwargs)
        return self._execute_catalog(**kwargs)

    def _execute_catalog(self, **kwargs):
        agent, language = self._agent, resolve_timepoint_language(agent=self._agent)
        config = getattr(agent, "config", {}) or {}
        owner, sid = config.get("_workspace_owner_id"), config.get("_workspace_session_id")
        facade = getattr(agent, "_workspace_store", None)
        store = getattr(facade, "raw", facade)
        if not owner or not sid or store is None:
            packet = timepoint_message("timepoint_workspace_unbound", language)
            return ToolResult(False, error=packet["message"], metadata=packet)
        try:
            unknown = set(kwargs) - set(self.input_schema["properties"])
            action = kwargs.get("action")
            if unknown or action not in self.input_schema["properties"]["action"]["enum"]:
                raise TimepointError("Unsupported catalog action or arguments")
            fields = {"metadata": {"action", "timepoint_id"}, "explain": {"action"},
                "create": {"action", "title", "stage", "preoperative_timepoint_id", "expected_revision"},
                "rename": {"action", "timepoint_id", "title", "expected_revision"},
                "update": {"action", "timepoint_id", "patch", "expected_revision"},
                "delete_impact": {"action", "timepoint_id"},
                "delete": {"action", "timepoint_id", "expected_revision"},
                "restore": {"action", "timepoint_id", "expected_revision"},
                "select": {"action", "timepoint_id"}}
            if set(kwargs) - fields[action]:
                raise TimepointError("Arguments do not belong to this catalog action")
            catalog = store.list_timepoints(owner, sid, include_trashed=True)
            runtime = getattr(agent, "_workspace_scoped_chat_runtime", None)
            scope = (getattr(agent, "_active_turn_context", {}) or {}).get("timepoint_scope")
            if scope is None and runtime is not None:
                scope = runtime.scope
            identifier = kwargs.get("timepoint_id") or getattr(scope, "timepoint_id", None)
            record, context = None, None
            if action not in {"create", "explain"}:
                if not identifier:
                    raise TimepointError("A captured or explicit catalog target is required")
                timepoint_id(identifier)
                record = store._timepoint_record(catalog, identifier, include_trashed=action in {"restore", "metadata"})
                context = capture_catalog_target(store, scope, record) if scope is not None else None
            mutating = tool_call_is_mutating(self.name, kwargs)
            if mutating:
                from web.timepoint_chat import ChatTimepointScope
                if not isinstance(scope, ChatTimepointScope):
                    raise TimepointError("Catalog mutation requires a captured authenticated human turn")
                authorization = agent._current_execution_authorization() if callable(getattr(agent, "_current_execution_authorization", None)) else None
                if authorization is None or not authorization.tool_allowed(self.name, kwargs):
                    raise TimepointError("The catalog action was not authorized by this human turn")
                turn = getattr(agent, "_active_turn_context", {}) or {}
                store.assert_editable(owner, sid, str(turn.get("editor_token") or config.get("_workspace_editor_token") or ""))
                if action != "create":
                    require_human_target(agent, scope, identifier, self.name, kwargs, context=context)
            expected = kwargs.get("expected_revision", catalog["catalog_revision"])
            metadata = {"session_id": sid, "timepoint_id": identifier,
                "timepoint_ids": [identifier] if identifier else [], "catalog_revision": catalog["catalog_revision"],
                "readset": readset_dict(context) if context is not None else [],
                "read_only": not mutating, "clinical_computation_performed": False}
            if action == "explain":
                data = {
                    "conversation": "One shared Session conversation; independent clinical/UI/report state per timepoint.",
                    "default_target": "The Table Viewer mounted when the human submits a turn.",
                    "intraoperative_source": "An explicit owned preoperative source; inference and dose use the current intraoperative CT.",
                    "comparison": "Read saved timepoint facts and compare compatible metrics; never add dose grids across scans.",
                    "delete_restore": "Recoverable software catalog state only. It never reverses physical implantation.",
                    "selection": "Browser mount affects later submissions; pending work retains its captured target.",
                    "review": "Seed axes, source settings and guide placement require their separate clinical review contracts."}
                message = "时间点工作流说明已读取。" if language == "zh" else "Read the timepoint workflow contract."
                return ToolResult(True, data=data, message=message, metadata={**metadata, "workflow": data},
                    display=message + "\n```json\n" + json.dumps(data, ensure_ascii=False) + "\n```")
            if action == "metadata":
                return ToolResult(True, data=copy.deepcopy(record), metadata={**metadata, "timepoint": copy.deepcopy(record)},
                    message=timepoint_message("timepoint_catalog_loaded", language)["message"])
            if action == "delete_impact":
                return ToolResult(True, data=store.timepoint_delete_impact(owner, sid, identifier), metadata=metadata,
                    message=timepoint_message("timepoint_delete_impact_loaded", language)["message"])
            if action == "select":
                if config.get("_workspace_scoped_browser_delivery") is not True:
                    from web.timepoint_chat import ScopedToolUnavailable
                    raise ScopedToolUnavailable("Timepoint selection requires the scoped browser mount bridge")
                command = {"target": "timepoint", "command": "select", "value": identifier}
                return ToolResult(True, data={"selected_timepoint_id": identifier, "mounted": False},
                    metadata={**metadata, "frontend_action": "timepoint", "ui_action": command,
                        "actions": [command], "completed": False, "accepted": 1, "executed": 0,
                        "execution_claim": "accepted_pending_browser"},
                    message="已请求切换时间点；等待浏览器挂载。" if language == "zh" else
                            "Requested timepoint selection; browser mount is pending.")
            if action == "create":
                stage = kwargs.get("stage", "preoperative")
                name = title(kwargs.get("title", "Intraoperative" if stage == "intraoperative" else "Preoperative"))
                result = store.create_timepoint(owner, sid, name, expected_revision=expected,
                    stage=stage, preoperative_timepoint_id=kwargs.get("preoperative_timepoint_id"))
                identifier, code = result["created_timepoint_id"], "timepoint_created"
            elif action in {"rename", "update"}:
                patch = {"title": title(kwargs.get("title"))} if action == "rename" else kwargs.get("patch")
                if not isinstance(patch, Mapping) or not patch:
                    raise TimepointError("A nonempty metadata patch is required")
                result = store.update_timepoint(owner, sid, identifier, patch, expected_revision=expected)
                code = "timepoint_updated"
            elif action == "delete":
                result = store.delete_timepoint(owner, sid, identifier, expected_revision=expected)
                code = "timepoint_deleted"
            else:
                result = store.restore_timepoint(owner, sid, identifier, expected_revision=expected)
                code = "timepoint_restored"
            packet = timepoint_message(code, language)
            return ToolResult(True, data=result, message=packet["message"], metadata={**metadata, **packet,
                "timepoint_id": identifier, "timepoint_ids": [identifier],
                "catalog_revision": result["catalog_revision"], "catalog_changed": True,
                "recoverable": action == "delete", "published_to_timepoint": False,
                "catalog": result, "created_timepoint_id": identifier if action == "create" else None})
        except (TimepointError, WorkspaceError, TypeError, ValueError) as exc:
            packet, _ = timepoint_error(exc, language)
            return ToolResult(False, error=packet["error"], message=packet["error"],
                metadata={**packet, "target_confirmation": getattr(exc, "confirmation", None),
                    "published_to_timepoint": False, "clinical_computation_performed": False})
