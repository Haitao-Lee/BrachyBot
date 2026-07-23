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
            "and can be exported as STL. Use only after a CT and needle plan exist."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["generate", "status"],
                    "description": "Generate a new guide or inspect the current guide.",
                },
                "needle_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset of current plan needle IDs.",
                },
                "parameters": {
                    "type": "object",
                    "description": "Optional skin offset, plate, sleeve, and bore parameters in mm.",
                },
            },
            "required": ["action"],
        }

    def _execute(self, **kwargs: Any) -> ToolResult:
        from web.surgical_guide import (
            SurgicalGuideError,
            generate_surgical_guide,
            guide_public_payload,
            normalize_guide_parameters,
            save_guide_version,
        )

        agent = kwargs.get("_agent") or self._agent
        if agent is None:
            return ToolResult(success=False, error="Case agent is unavailable")
        action = str(kwargs.get("action") or "").strip().lower()
        if action == "status":
            return ToolResult(
                success=True,
                message="Puncture-guide status retrieved",
                metadata=guide_public_payload(agent.memory.retrieve("surgical_guide")),
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
            return ToolResult(
                success=True,
                message=(
                    f"Generated puncture guide v{state['version']} for "
                    f"{len(state['selected_needle_ids'])} planned needle paths."
                ),
                metadata=guide_public_payload(state),
            )
        except SurgicalGuideError as exc:
            return ToolResult(success=False, error=str(exc), message=str(exc))
