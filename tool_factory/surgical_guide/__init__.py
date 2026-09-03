"""Agent tool for the case-scoped patient-specific puncture-guide workflow."""

from __future__ import annotations

from typing import Any, Dict, List

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
            "and can be exported as STL. It includes optional non-protruding "
            "auxiliary puncture holes around each primary channel for patient-motion "
            "robustness. Use only after a CT and needle plan exist."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["generate", "status"],
                    "default": "generate",
                    "description": "Generate a new guide or inspect the current guide.",
                },
                "needle_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset of current plan needle IDs.",
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "Optional puncture-guide manufacturing parameters in mm or HU. "
                        "All keys are optional; omitted keys keep the case's current "
                        "panel values (or defaults)."
                    ),
                    "properties": {
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
                    f"Verified: puncture guide {version_text or 'current version'} is persisted, but {restoring_text_en}; it has not been treated as missing."
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
