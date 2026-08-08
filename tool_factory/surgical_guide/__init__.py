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
                            "type": "number", "minimum": 0.2, "maximum": 1.5,
                            "description": "Radius of each auxiliary alternate puncture hole.",
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
            normalize_guide_parameters,
            save_guide_version,
        )

        agent = kwargs.get("_agent") or self._agent
        if agent is None:
            return ToolResult(success=False, error="Case agent is unavailable")
        action = str(kwargs.get("action") or "generate").strip().lower()
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
                metadata=guide_public_payload(state),
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
