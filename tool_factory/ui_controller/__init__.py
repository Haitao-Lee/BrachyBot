"""
UI Controller Tool
==================
Enables BrachyBot to control every UI element precisely.
Uses a structured control registry so the LLM never hallucinates controls.

Architecture:
    LLM → ui_controller(action={target, command, value})
        → Server validates against registry
        → Frontend executes the exact UI function
"""

import json
import logging
from typing import Dict, Any, Optional, List
from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# ============================================================
# CONTROL REGISTRY — Single source of truth for all UI controls
# ============================================================
# Each entry defines: target name, what commands it accepts,
# value type, and a human-readable description.
# The LLM sees this registry and picks from it — no guessing.

CONTROL_REGISTRY = {
    "panel": {
        "commands": ["switch"],
        "values": ["input", "metrics", "seeds", "viewers"],
        "description": "Switch between UI panels/tabs"
    },
    "viewer.window": {
        "commands": ["set", "increase", "decrease"],
        "value_type": "int",
        "range": [1, 2000],
        "description": "CT window width (contrast range). Higher = more contrast."
    },
    "viewer.level": {
        "commands": ["set", "increase", "decrease"],
        "value_type": "int",
        "range": [-1000, 1000],
        "description": "CT window level (center HU). Lower = darker, higher = brighter."
    },
    "viewer.zoom": {
        "commands": ["set", "increase", "decrease", "fit"],
        "value_type": "int",
        "range": [50, 300],
        "description": "Zoom level in percent. 'fit' resets to 100% and centers."
    },
    "viewer.threshold": {
        "commands": ["set"],
        "value_type": "int",
        "range": [-1000, 1000],
        "description": "HU threshold for segmentation overlay"
    },
    "overlay.ctv": {
        "commands": ["show", "hide", "toggle"],
        "description": "CTV segmentation overlay visibility"
    },
    "overlay.oar": {
        "commands": ["show", "hide", "toggle"],
        "description": "OAR segmentation overlay visibility"
    },
    "overlay.ctv.opacity": {
        "commands": ["set", "increase", "decrease"],
        "value_type": "int",
        "range": [0, 100],
        "description": "CTV overlay opacity (0=transparent, 100=opaque)"
    },
    "overlay.oar.opacity": {
        "commands": ["set", "increase", "decrease"],
        "value_type": "int",
        "range": [0, 100],
        "description": "OAR overlay opacity (0=transparent, 100=opaque)"
    },
    "overlay.display_mode": {
        "commands": ["set"],
        "values": ["ct", "overlay", "label"],
        "description": "Display mode: ct=CT only, overlay=CT+label, label=label only"
    },
    "slice.axial": {
        "commands": ["set", "next", "prev", "first", "last"],
        "value_type": "int",
        "description": "Navigate axial slice. Value is slice index."
    },
    "slice.sagittal": {
        "commands": ["set", "next", "prev", "first", "last"],
        "value_type": "int",
        "description": "Navigate sagittal slice"
    },
    "slice.coronal": {
        "commands": ["set", "next", "prev", "first", "last"],
        "value_type": "int",
        "description": "Navigate coronal slice"
    },
    "layout": {
        "commands": ["set"],
        "values": ["vertical", "horizontal", "grid", "3d-top", "3d-bottom"],
        "description": "Viewer layout arrangement"
    },
    "preset": {
        "commands": ["set"],
        "values": ["default", "lung", "bone", "soft_tissue", "brain"],
        "description": "Window/level presets for common views"
    },
    "data_tree": {
        "commands": ["expand", "collapse"],
        "values": ["segmentation", "oar", "non_traversable", "traversable", "dose"],
        "description": "Expand or collapse data tree groups"
    },
    "tool": {
        "commands": ["set"],
        "values": ["crosshair", "measure", "angle", "rect", "zoombox", "annotate", "eraser"],
        "description": "Active annotation/measurement tool"
    },
    "3d.reconstruct": {
        "commands": ["run"],
        "value_type": "string",
        "description": "3D reconstruct an organ by ID (e.g., 'ctv', 'organ_5')"
    },
}


def get_control_registry_summary() -> str:
    """Generate a compact summary of all controls for the system prompt."""
    lines = []
    for target, info in CONTROL_REGISTRY.items():
        cmds = "|".join(info["commands"])
        vals = info.get("values", info.get("value_type", ""))
        if isinstance(vals, list):
            vals = ",".join(str(v) for v in vals[:6])
            if len(info.get("values", [])) > 6:
                vals += ",..."
        desc = info.get("description", "")
        lines.append(f"  {target} [{cmds}] {vals} — {desc}")
    return "\n".join(lines)


class UIControllerTool(BaseTool):
    """Execute precise UI actions on the BrachyBot interface."""

    @property
    def name(self) -> str:
        return "ui_controller"

    @property
    def description(self) -> str:
        return (
            "Control the BrachyBot UI precisely. Use structured actions to switch panels, "
            "adjust viewer settings, toggle overlays, navigate slices, and more. "
            "Available controls:\n" + get_control_registry_summary()
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "description": "List of UI actions to execute in order",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {
                                "type": "string",
                                "description": "Control target (e.g., 'panel', 'viewer.window', 'overlay.ctv')",
                            },
                            "command": {
                                "type": "string",
                                "description": "Action command (e.g., 'switch', 'set', 'show', 'toggle')",
                            },
                            "value": {
                                "description": "Value for the command (number, string, or null)",
                            },
                        },
                        "required": ["target", "command"],
                    },
                },
            },
            "required": ["actions"],
        }

    def _execute(self, **kwargs) -> ToolResult:
        actions = kwargs.get("actions", [])
        if not actions:
            return ToolResult(success=False, error="No actions provided")

        # Validate all actions against registry
        validated = []
        errors = []
        for i, action in enumerate(actions):
            target = action.get("target", "")
            command = action.get("command", "")
            value = action.get("value")

            if target not in CONTROL_REGISTRY:
                valid_targets = ", ".join(CONTROL_REGISTRY.keys())
                errors.append(f"Action {i}: unknown target '{target}'. Valid: {valid_targets}")
                continue

            reg = CONTROL_REGISTRY[target]
            if command not in reg["commands"]:
                errors.append(f"Action {i}: unknown command '{command}' for '{target}'. Valid: {reg['commands']}")
                continue

            # Validate value
            if "values" in reg and value is not None:
                if value not in reg["values"]:
                    errors.append(f"Action {i}: invalid value '{value}' for '{target}'. Valid: {reg['values']}")
                    continue

            if "range" in reg and value is not None:
                lo, hi = reg["range"]
                try:
                    v = float(value)
                    if v < lo or v > hi:
                        errors.append(f"Action {i}: value {value} out of range [{lo}, {hi}] for '{target}'")
                        continue
                except (ValueError, TypeError):
                    errors.append(f"Action {i}: value '{value}' must be a number for '{target}'")
                    continue

            validated.append(action)

        if errors and not validated:
            return ToolResult(success=False, error="; ".join(errors))

        # Return validated actions — frontend will execute them
        result_data = {
            "actions": validated,
            "errors": errors,
            "executed": len(validated),
        }

        summary_parts = []
        for a in validated:
            t, c, v = a["target"], a["command"], a.get("value", "")
            if v:
                summary_parts.append(f"{t}: {c} → {v}")
            else:
                summary_parts.append(f"{t}: {c}")

        summary = ", ".join(summary_parts) if summary_parts else "No valid actions"
        if errors:
            summary += f" ({len(errors)} errors skipped)"

        return ToolResult(
            success=True,
            message=summary,
            data=result_data,
        )
