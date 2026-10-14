"""Agent tool for the case-scoped patient-specific puncture-guide workflow."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Dict, Mapping

from tool_factory import BaseTool, ToolResult


class SurgicalGuideTool(BaseTool):
    """Generate or inspect a printable guide without bypassing the case state."""

    def __init__(self, agent: Any = None):
        self._agent = agent

    @property
    def name(self) -> str:
        return "surgical_guide"

    @property
    def description(self) -> str:
        return (
            "Generate or inspect a patient-specific skin-fitting puncture guide "
            "from the current CT and approved planned needle paths. The guide "
            "uses the same physical patient coordinates as planning, records QA, "
            "and can be exported as STL via ui_controller data.export (data_types=['surgical_guide'], format='stl'). "
            "For export/save of an existing guide, open that save dialog; do NOT generate a guide. It includes optional non-protruding "
            "auxiliary puncture holes around each primary channel for "
            "alternate-path coverage, without a clinical robustness claim. "
            "New guide designs default to continuation_dense_v1; standard_v1 retains "
            "the older two-ring layout. Reuse never redesigns a printed guide. The manifest action reads "
            "the final-STL bore inventory, including skipped/unverified candidates. "
            "estimate_placement stores a review-pending rigid candidate in an explicitly "
            "named intraoperative timepoint; validate_placement checks that saved "
            "candidate without approving physical placement or clinical use. "
            "Neither placement action regenerates the printed guide. "
            "Use only after a CT and needle plan exist. This tool is "
            "for a printable GUIDE (导板/guide) only. A request to generate a "
            "report (报告/report, including 手术报告 or surgical report) is not a "
            "guide request; use the report capability (ui_controller with "
            "report.autofill) instead. Never call this tool when no guide noun "
            "(导板, guide, 插植导板, 穿刺导板, 3D 打印导板) is present."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["generate", "status", "analyze", "manifest", "estimate_placement", "validate_placement"],
                    "default": "generate",
                    "description": (
                        "Generate a new guide, inspect its lifecycle state ('status'), "
                        "or analyze its design/validation characteristics ('analyze'). "
                        "'status' and 'analyze' are read-only: never use 'generate' "
                        "unless the user explicitly asks to create or regenerate the guide."
                    ),
                },
                "needle_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset of current plan needle IDs.",
                },
                "timepoint_id": {
                    "type": "string", "pattern": "^[0-9a-f]{32}$",
                    "description": "Optional generation/status target within the bound Session. Omit to use the captured Table Viewer. Placement actions require an explicit target and source.",
                },
                "source_timepoint_id": {
                    "type": "string", "pattern": "^[0-9a-f]{32}$",
                    "description": "Owned preoperative source for placement, or owned guide workspace for manifest lookup.",
                },
                "guide_version": {"type": "integer", "minimum": 1,
                                  "description": "Exact frozen source guide version; required for cross-timepoint manifest and placement calls."},
                "bore_offset": {"type": "integer", "minimum": 0, "default": 0},
                "bore_limit": {"type": "integer", "minimum": 1, "maximum": 32, "default": 20},
                "placement_id": {"type": "string", "description": "Saved candidate identity returned by estimate_placement."},
                "placement": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "method": {"type": "string", "enum": ["manual_rigid", "landmarks"]},
                        "manufactured_guide_id": {"type": "string", "minLength": 1, "maxLength": 160,
                                                  "description": "Declared physical guide identifier. Candidate creation does not confirm manufacture."},
                        "expected_state_revision": {"type": "integer", "minimum": 0},
                        "matrix": {"type": "array", "minItems": 4, "maxItems": 4,
                                   "items": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number"}}},
                        "source_landmarks": {"type": "array", "minItems": 3, "maxItems": 64,
                                             "items": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}}},
                        "target_landmarks": {"type": "array", "minItems": 3, "maxItems": 64,
                                             "items": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}}},
                        "max_residual_mm": {"type": "number", "exclusiveMinimum": 0,
                                            "description": "Explicit landmark-fit tolerance; no clinical default is supplied."},
                        "evidence_source": {"type": "string", "minLength": 1, "maxLength": 500},
                    },
                    "required": ["method", "manufactured_guide_id", "expected_state_revision"],
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "Optional puncture-guide manufacturing parameters in mm or HU. "
                        "All keys are optional; omitted keys keep the case's current "
                        "panel values (or defaults)."
                    ),
                    "properties": {
                        "auxiliary_density_profile": {
                            "type": "string", "enum": ["standard_v1", "continuation_dense_v1"],
                            "default": "continuation_dense_v1",
                            "description": "New designs default to four staggered candidate rings. Explicit standard_v1 preserves the two-ring layout. Final STL wall/spacing/guidance gates and 5 mm truncation apply. No mechanical commissioning is implied.",
                        },
                        "skin_threshold_hu": {
                            "type": "number", "minimum": -800, "maximum": 100,
                            "description": "CT HU threshold defining the skin surface.",
                        },
                        "skin_clearance_mm": {
                            "type": "number", "minimum": 0, "maximum": 5,
                            "description": "Offset from the skin surface to the guide plate.",
                        },
                        "plate_thickness_mm": {
                            "type": "number", "minimum": 1, "maximum": 10,
                            "description": "Printable shell thickness.",
                        },
                        "patch_margin_mm": {
                            "type": "number", "minimum": 10, "maximum": 80,
                            "description": "Surface patch radius around each entry.",
                        },
                        "channel_radius_mm": {
                            "type": "number", "minimum": 0.3, "maximum": 6,
                            "description": "Inner guide-hole RADIUS (the UI shows diameter = 2x radius).",
                        },
                        "sleeve_outer_radius_mm": {
                            "type": "number", "minimum": 1, "maximum": 12,
                            "description": "Outer support sleeve RADIUS (UI diameter = 2x radius).",
                        },
                        "sleeve_outward_mm": {
                            "type": "number", "minimum": 1, "maximum": 30,
                            "description": "Sleeve length protruding OUTWARD from the skin entry.",
                        },
                        "sleeve_inward_mm": {
                            "type": "number", "minimum": 1, "maximum": 30,
                            "description": "Accepted for compatibility; the channel is clamped flush with the skin and never penetrates the body.",
                        },
                        "auxiliary_holes_enabled": {
                            "type": "boolean",
                            "description": "Subtract dense, non-protruding alternate puncture holes around each primary channel.",
                        },
                        "auxiliary_hole_radius_mm": {
                            "type": "number", "minimum": 0.3, "maximum": 6.4,
                            "description": "Compatibility field; the physical auxiliary-hole radius is derived to equal the final primary bore radius.",
                        },
                        "auxiliary_hole_ring_count": {
                            "type": "integer", "minimum": 1, "maximum": 4,
                            "description": "Number of concentric auxiliary-hole rings around each primary channel.",
                        },
                        "auxiliary_holes_per_ring": {
                            "type": "integer", "minimum": 4, "maximum": 24,
                            "description": "Number of equally spaced auxiliary holes on each ring.",
                        },
                        "auxiliary_hole_first_offset_mm": {
                            "type": "number", "minimum": 2, "maximum": 15,
                            "description": "Radial distance from the primary channel to the first auxiliary ring.",
                        },
                        "auxiliary_hole_ring_spacing_mm": {
                            "type": "number", "minimum": 1.5, "maximum": 10,
                            "description": "Radial spacing between auxiliary-hole rings.",
                        },
                        "geometry_resolution_mm": {
                            "type": "number", "minimum": 0.2, "maximum": 2,
                            "description": "Isotropic local construction lattice.",
                        },
                    },
                },
            },
            # The planner commonly requests the default operation with an
            # empty tool-call object.  Keep generation as the safe default;
            # an explicit status action remains available for inspection.
            "required": [],
        }

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {
            "manufactured_guide_metadata": {"type": "object",
                "description": "Recorded final-STL identity, eligible/skipped/unverified bore counts, density profile, and explicit manufacture/placement evidence limits."},
            "guide_manifest": {"type": "object", "description": "Bounded recorded bore page with next_offset; excludes large mesh arrays."},
            "guide_placement_candidate": {"type": "object", "description": "Durably saved, review-pending candidate; no clinical approval."},
            "guide_placement_validation": {"type": "object", "description": "Read-only rigid/geometry/current-image verification of a saved candidate."},
        }}

    @staticmethod
    def _execution_scope(agent, kwargs, *, mutating=False):
        """Use a typed detached owner; retain strict fencing for legacy callers."""
        from web.guide_placement import GuidePlacementError

        if kwargs.get("source_timepoint_id") is not None:
            raise GuidePlacementError("Use manifest or a placement action for source-timepoint lookup")
        config = getattr(agent, "config", {}) or {}
        store = getattr(agent, "_workspace_store", None)
        requested = kwargs.get("timepoint_id")
        if store is None:
            if requested is not None:
                raise GuidePlacementError("A scoped timepoint requires an authenticated workspace")
            return {"execution_scope": "legacy_single_workspace"}
        owner, sid = config.get("_workspace_owner_id"), config.get("_workspace_session_id")
        if not owner or not sid:
            raise GuidePlacementError("Authenticated workspace owner and Session are required")
        catalog = store.list_timepoints(owner, sid)
        from web.timepoint_context import TimepointContext
        context = getattr(agent, '_workspace_timepoint_context', None)
        if isinstance(context, TimepointContext):
            identifier = context.target.timepoint_id
            if (context.owner_id, context.session_id, identifier) != (
                    owner, sid, config.get('_workspace_timepoint_id')):
                raise GuidePlacementError('Guide context differs from the authenticated captured workspace')
            if requested is not None and requested != identifier:
                raise GuidePlacementError('Guide target differs from the captured Table Viewer')
            raw = getattr(store, 'raw', store)
            context.assert_current(owner, sid, raw._timepoint_catalog(owner, sid),
                legacy_revision=raw.get_session(owner, sid).revision)
            return {'session_id':sid,'timepoint_id':identifier,'execution_scope':'captured_timepoint'}
        identifier = catalog["default_timepoint_id"]
        if mutating and requested is None and len(catalog["timepoints"]) > 1:
            raise GuidePlacementError("Generation in a multi-timepoint Session requires an explicit target")
        if requested is not None and requested != identifier:
            raise GuidePlacementError("Guide generation/status runtime is bound to the legacy default timepoint; use manifest for other saved guides")
        return {"session_id": sid, "timepoint_id": identifier, "execution_scope": "legacy_default_timepoint"}

    @staticmethod
    def _manifest_result(page):
        summary = page["summary"]
        return ToolResult(success=True, data=page,
                          message="Read the recorded final-STL bore inventory without generation or clinical approval.",
                          display=json.dumps(page, ensure_ascii=False, sort_keys=True),
                          metadata={"manufactured_guide_metadata": summary, "guide_manifest": page, "read_only": True})

    def _execute_guide_service(self, agent, action, kwargs):
        from web.guide_placement import GuidePlacementError
        from web.guide_service import GuidePlacementService, guide_manifest_page

        if action == "manifest" and kwargs.get("source_timepoint_id") is None:
            from web.surgical_guide import guide_state_for_version
            scope = self._execution_scope(agent, kwargs)
            page = guide_manifest_page(guide_state_for_version(agent, kwargs.get("guide_version")),
                                       offset=kwargs.get("bore_offset", 0), limit=kwargs.get("bore_limit", 20))
            page["scope"] = scope
            return self._manifest_result(page)
        service = GuidePlacementService(agent)
        source_id, target_id = kwargs.get("source_timepoint_id"), kwargs.get("timepoint_id")
        version = kwargs.get("guide_version")
        if not source_id:
            raise GuidePlacementError("An explicit source_timepoint_id is required")
        if action == "manifest":
            if target_id is not None:
                raise GuidePlacementError("Manifest lookup selects its source_timepoint_id only")
            return self._manifest_result(service.manifest(source_timepoint_id=source_id, guide_version=version,
                                                         offset=kwargs.get("bore_offset", 0), limit=kwargs.get("bore_limit", 20)))
        if not target_id:
            raise GuidePlacementError("An explicit target timepoint_id is required")
        if action == "estimate_placement":
            request = kwargs.get("placement")
            if not isinstance(request, Mapping):
                raise GuidePlacementError("A placement request is required")
            result = service.estimate(source_timepoint_id=source_id, target_timepoint_id=target_id,
                                       guide_version=version, **dict(request))
            return ToolResult(success=True, data=result, metadata={"guide_placement_candidate": result},
                              message="Stored a rigid placement candidate; physical placement and clinical use remain unapproved.",
                              display=json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not kwargs.get("placement_id"):
            raise GuidePlacementError("A saved placement_id is required")
        result = service.validate(source_timepoint_id=source_id, target_timepoint_id=target_id,
                                  guide_version=version, placement_id=kwargs["placement_id"])
        return ToolResult(success=True, data=result, metadata={"guide_placement_validation": result, "read_only": True},
                          message="Validated the saved candidate's rigid transform and exact guide/current-image identities; review is pending.",
                          display=json.dumps(result, ensure_ascii=False, sort_keys=True))

    def _execute(self, **kwargs: Any) -> ToolResult:
        from web.surgical_guide import (
            SurgicalGuideError,
            generate_surgical_guide,
            guide_public_payload,
            guide_status_payload,
            normalize_guide_parameters,
            save_guide_version,
        )

        agent = kwargs.get("_agent") or self._agent
        if agent is None:
            return ToolResult(success=False, error="Case agent is unavailable")
        action = str(kwargs.get("action") or "generate").strip().lower()
        from web.guide_service import guide_manifest_summary
        try:
            allowed = set(self.input_schema["properties"]) | {"_agent"}
            if set(kwargs) - allowed:
                raise ValueError("Unsupported surgical_guide fields")
            if action in {"manifest", "estimate_placement", "validate_placement"}:
                if kwargs.get("parameters") is not None or kwargs.get("needle_ids") is not None:
                    raise ValueError("Manifest and placement actions cannot change guide design parameters or needles")
                return self._execute_guide_service(agent, action, kwargs)
            if any(kwargs.get(key) is not None for key in ("placement", "placement_id", "bore_offset", "bore_limit", "guide_version")):
                raise ValueError("Placement/manifest inputs require their explicit action")
            scope = self._execution_scope(agent, kwargs, mutating=action == "generate")
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            return ToolResult(success=False, error=str(exc), metadata={"guide_action": action})
        if action == "analyze":
            from agent_runtime.artifact_analysis import build_guide_characteristics_facts

            status = guide_status_payload(agent)
            facts = build_guide_characteristics_facts(
                status.get("guide") if isinstance(status, dict) else {}
            )
            manufactured = guide_manifest_summary(status.get("guide"))
            facts["manufactured_guide_metadata"] = deepcopy(manufactured)
            turn_context = getattr(agent, "_active_turn_context", {}) or {}
            lang = str(
                getattr(agent.memory, "user_lang", "")
                or (turn_context.get("response_language", "") if isinstance(turn_context, dict) else "")
                or "en"
            ).lower()
            lang = "zh" if lang.startswith(("zh", "cn")) else "en"
            if not facts.get("available"):
                message = (
                    "当前没有可核验的手术导板特征记录。"
                    if lang == "zh" else
                    "No verifiable puncture-guide characteristics record is present."
                )
            else:
                version_text = f"v{facts.get('version')}" if facts.get("version") is not None else ""
                message = (
                    f"已读取手术导板 {version_text} 的设计与校验特征，可供分析。"
                    if lang == "zh" else
                    f"Read the design and validation characteristics of the "
                    f"{version_text or 'current'} puncture guide for analysis."
                )
            return ToolResult(
                success=True,
                message=message,
                metadata={
                    "guide_characteristics": facts,
                    "guide_status": status,
                    "analysis_action": "analyze",
                    "manufactured_guide_metadata": manufactured,
                    "execution_scope": scope,
                },
            )
        if action == "status":
            status = guide_status_payload(agent)
            guide = status.get("guide")
            turn_context = getattr(agent, "_active_turn_context", {}) or {}
            lang = str(
                getattr(agent.memory, "user_lang", "")
                or (turn_context.get("response_language", "") if isinstance(turn_context, dict) else "")
                or "en"
            ).lower()
            lang = "zh" if lang.startswith(("zh", "cn")) else "en"
            state = str(status.get("state") or "unavailable")
            version = status.get("version")
            version_text = f"v{version}" if version not in (None, "") else ""
            needle_count = len(status.get("selected_needle_ids") or [])
            if state == "ready":
                message = (
                    f"已核验：手术导板 {version_text or '当前版本'} 已生成并已加载，包含 {needle_count} 条计划针道。"
                    if lang == "zh" else
                    f"Verified: puncture guide {version_text or 'current version'} is generated and loaded for {needle_count} planned needle paths."
                )
            elif state in {"restoring", "persisted_not_loaded"}:
                restoring_text = (
                    "当前 Session 仍在恢复导板资源，尚未完成呈现"
                    if status.get("hydration_pending")
                    else "导板资源尚未完成加载或呈现"
                )
                restoring_text_en = (
                    "this Session is still restoring its resources and presentation is not complete"
                    if status.get("hydration_pending")
                    else "its resources or presentation are not complete yet"
                )
                message = (
                    f"已核验：手术导板 {version_text or '当前版本'} 已持久化，但{restoring_text}；这不表示导板未生成。"
                    if lang == "zh" else
                    f"Verified: puncture guide {version_text or 'current version'} is persisted, but {restoring_text_en}; this does not mean the guide was not generated."
                )
            elif state == "generating":
                message = (
                    "手术导板正在生成，请等待当前操作完成。"
                    if lang == "zh" else
                    "Puncture-guide generation is in progress; wait for the current operation to finish."
                )
            elif state == "stale":
                message = (
                    f"已核验：手术导板 {version_text or '当前版本'} 已存在，但与当前规划不一致或已过期，需要重新生成。"
                    if lang == "zh" else
                    f"Verified: puncture guide {version_text or 'current version'} exists, but it is stale or does not match the current Planning and should be regenerated."
                )
            elif state == "failed":
                message = (
                    f"手术导板生成曾经失败：{status.get('reason') or '未知错误'}。"
                    if lang == "zh" else
                    f"Puncture-guide generation failed: {status.get('reason') or 'unknown error'}."
                )
            elif state == "not_generated":
                message = (
                    "已核验：当前规划没有可核验的已保存手术导板。"
                    if lang == "zh" else
                    "Verified: no persisted puncture guide can be confirmed for the current Planning."
                )
            else:
                message = (
                    "当前病例的手术导板状态暂不可用，正在等待病例资源恢复。"
                    if lang == "zh" else
                    "The current puncture-guide status is temporarily unavailable while case resources are being restored."
                )
            return ToolResult(
                success=True,
                message=message,
                metadata={
                    **guide_public_payload(guide),
                    "guide_status": status,
                    "manufactured_guide_metadata": guide_manifest_summary(guide),
                    "execution_scope": scope,
                },
            )
        if action != "generate":
            return ToolResult(success=False, error="Unsupported surgical_guide action")
        try:
            state = save_guide_version(
                agent,
                generate_surgical_guide(
                    agent,
                    normalize_guide_parameters(kwargs.get("parameters") or {}),
                    selected_needle_ids=kwargs.get("needle_ids"),
                ),
            )
            # Chat/tool-driven generation bypasses the HTTP route. Publish the
            # immutable guide into the active Planning snapshot as well as the
            # legacy active alias, otherwise a restart restores needles/seeds
            # but silently loses the guide mesh.
            try:
                from web.planning_runs import publish_active_planning_state
                publish_active_planning_state(agent)
            except Exception:
                # Guide generation already succeeded; the workspace checkpoint
                # can retry this optional snapshot publication.
                pass
            return ToolResult(
                success=True,
                message=(
                    f"Generated puncture guide v{state['version']} for "
                    f"{len(state['selected_needle_ids'])} planned needle paths."
                ),
                metadata={
                    **guide_public_payload(state),
                    "guide_status": guide_status_payload(agent),
                    "manufactured_guide_metadata": guide_manifest_summary(state),
                    "execution_scope": scope,
                },
            )
        except SurgicalGuideError as exc:
            try:
                # The CT-derived skin envelope is stored before guide CSG. It
                # remains a valid inspection result when the printable mesh is
                # rejected, so bind it to the current Planning snapshot too.
                from web.planning_runs import publish_active_planning_state
                publish_active_planning_state(agent)
            except Exception:
                pass
            return ToolResult(success=False, error=str(exc), message=str(exc))
