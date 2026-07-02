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
    # ── Panel switching ──
    "panel": {
        "commands": ["switch"],
        "values": ["input", "metrics", "viewers", "report"],
        "description": "Switch between UI panels/tabs (input, metrics, viewers, report)"
    },
    # ── Viewer settings ──
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
    "viewer.fullscreen": {
        "commands": ["toggle"],
        "values": ["axial", "sagittal", "coronal", "3d"],
        "description": "Toggle fullscreen for a specific viewer"
    },
    "viewer.reset": {
        "commands": ["run"],
        "description": "Reset all viewer settings (window/level/zoom/pan) to defaults"
    },
    "viewer.fit_all": {
        "commands": ["run"],
        "description": "Fit all 2D viewers to show the full image"
    },
    "viewer.preset": {
        "commands": ["set"],
        "values": ["soft", "bone", "lung", "brain", "custom"],
        "description": "Apply window/level preset"
    },
    # ── Overlay controls ──
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
    "overlay.dose.opacity": {
        "commands": ["set", "increase", "decrease"],
        "value_type": "int",
        "range": [0, 100],
        "description": "Dose overlay opacity (0=transparent, 100=opaque)"
    },
    "overlay.display_mode": {
        "commands": ["set"],
        "values": ["ct", "overlay", "label"],
        "description": "Display mode: ct=CT only, overlay=CT+label, label=label only"
    },
    # ── Slice navigation ──
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
    # ── Layout ──
    "layout": {
        "commands": ["set"],
        "values": ["vertical", "horizontal", "grid", "3d-top", "3d-bottom"],
        "description": "Viewer layout arrangement"
    },
    # ── Data tree ──
    "data_tree": {
        "commands": ["expand", "collapse", "expand_all", "collapse_all"],
        "values": ["segmentation", "oar", "non_traversable", "traversable", "dose"],
        "description": "Expand or collapse data tree groups. expand_all/collapse_all affects all groups."
    },
    "tree.visibility": {
        "commands": ["set"],
        "value_type": "string",
        "description": "Toggle organ visibility. Value: 'organ_id,on' or 'organ_id,off' (e.g. 'ctv_1,on', 'organ_52,off')"
    },
    "tree.opacity": {
        "commands": ["set"],
        "value_type": "string",
        "description": "Set organ opacity. Value: 'organ_id,0-100' (e.g. 'ctv_1,80')"
    },
    "tree.reconstruct3d": {
        "commands": ["run"],
        "value_type": "string",
        "description": "3D reconstruct an organ node. Value: organ_id (e.g. 'ctv_1', 'organ_52')"
    },
    "tree.group.visibility": {
        "commands": ["set"],
        "values": ["ctv,show", "ctv,hide", "oar,show", "oar,hide",
                   "non_traversable,show", "non_traversable,hide",
                   "traversable,show", "traversable,hide"],
        "description": "Toggle visibility for an entire organ group"
    },
    "tree.group.opacity": {
        "commands": ["set"],
        "value_type": "string",
        "description": "Set opacity for an entire group. Value: 'group_name,0-100'"
    },
    "tree.group.reconstruct3d": {
        "commands": ["run"],
        "value_type": "string",
        "description": "3D reconstruct all organs in a group. Value: group name (e.g. 'oar', 'non_traversable')"
    },
    "tree.dose.visibility": {
        "commands": ["toggle"],
        "values": ["on", "off"],
        "description": "Toggle dose overlay visibility in data tree"
    },
    "tree.trajectories.visibility": {
        "commands": ["toggle"],
        "values": ["on", "off"],
        "description": "Toggle trajectory lines visibility"
    },
    "tree.seeds.visibility": {
        "commands": ["toggle"],
        "values": ["on", "off"],
        "description": "Toggle seed points visibility"
    },
    "tree.needles.visibility": {
        "commands": ["toggle"],
        "values": ["on", "off"],
        "description": "Toggle needle lines visibility"
    },
    "tree.isosurfaces.visibility": {
        "commands": ["toggle"],
        "values": ["on", "off"],
        "description": "Toggle dose isosurface visibility"
    },
    # ── Session management ──
    "session.new": {
        "commands": ["run"],
        "description": "Create a new chat session"
    },
    "session.switch": {
        "commands": ["run"],
        "value_type": "string",
        "description": "Switch to an existing session by ID"
    },
    "session.rename": {
        "commands": ["set"],
        "value_type": "string",
        "description": "Rename the current session. Value: new title"
    },
    "session.delete": {
        "commands": ["run"],
        "value_type": "string",
        "destructive": True,
        "description": "Delete a session by ID. REQUIRES user confirmation."
    },
    "session.clear_all": {
        "commands": ["run"],
        "destructive": True,
        "description": "Delete ALL local sessions and data. REQUIRES user confirmation."
    },
    # ── Planning actions ──
    "plan.run": {
        "commands": ["run"],
        "description": "Run the full planning pipeline"
    },
    "plan.run_manual_step": {
        "commands": ["run"],
        "values": [
            "ctv_segmentation", "oar_segmentation", "trajectory_init",
            "trajectory_refine", "seed_planning", "dose_calc", "dose_eval"
        ],
        "description": "Run one manual workflow step without relying on the LLM planner"
    },
    "plan.reset": {
        "commands": ["run"],
        "destructive": True,
        "description": "Reset the current planning session. REQUIRES user confirmation."
    },
    "ui.state": {
        "commands": ["sync", "inspect"],
        "description": "Synchronize or inspect the current frontend UI state snapshot"
    },
    "ui.control": {
        "commands": ["click", "set", "toggle", "focus", "blur"],
        "value_type": "string",
        "description": "Generic safe DOM control by id or CSS selector. Value may be an id, selector, or JSON like {\"id\":\"viewerWindow\",\"value\":450}."
    },
    "training.mode": {
        "commands": ["start", "stop", "status", "advice"],
        "value_type": "string",
        "description": "Start/stop live planning monitor, check status, or request detailed planning advice"
    },
    "manual.needle.create": {
        "commands": ["run"],
        "description": "Create an editable manual needle in the 3D viewer near the current planning target"
    },
    "manual.seed.add": {
        "commands": ["run"],
        "description": "Add a manual seed on the selected/current manual needle and refresh dose preview"
    },
    "manual.dose.recompute": {
        "commands": ["run"],
        "value_type": "string",
        "description": "Recompute manual dose/DVH with the trained myDoseNet AI dose model"
    },
    "manual.plan.finish": {
        "commands": ["run"],
        "description": "Finish/review a manual plan and provide current planning advice"
    },
    "system.readiness": {
        "commands": ["check"],
        "description": "Run a deterministic readiness checklist for the current case and surface missing workflow items"
    },
    # ── Report actions ──
    "report.autofill": {
        "commands": ["run"],
        "description": "Auto-fill the report form from planning data"
    },
    "report.export": {
        "commands": ["run"],
        "values": ["pdf", "html", "markdown", "json"],
        "description": "Export the report in the specified format"
    },
    "report.import": {
        "commands": ["run"],
        "value_type": "string",
        "description": "Import report from JSON file path"
    },
    "report.snapshot.save": {
        "commands": ["run"],
        "description": "Save a snapshot of the current report"
    },
    "report.snapshot.open": {
        "commands": ["run"],
        "description": "Open the snapshots manager"
    },
    "report.audit.open": {
        "commands": ["run"],
        "description": "Open the audit trail"
    },
    "report.validation.open": {
        "commands": ["run"],
        "description": "Open the validation checklist"
    },
    "report.preview.zoom": {
        "commands": ["set", "increase", "decrease", "reset"],
        "value_type": "int",
        "range": [50, 200],
        "description": "Report preview zoom level"
    },
    "report.layout": {
        "commands": ["set"],
        "values": ["2col", "1col"],
        "description": "Report editor layout: 2col=side-by-side, 1col=stacked"
    },
    "report.section.toggle": {
        "commands": ["run"],
        "value_type": "string",
        "description": "Toggle a report section open/closed. Value: section key"
    },
    "report.reference.add": {
        "commands": ["set"],
        "value_type": "string",
        "description": "Add a reference citation. Value: catalog key"
    },
    "report.reference.remove": {
        "commands": ["set"],
        "value_type": "int",
        "description": "Remove a reference by index (0-based)"
    },
    "report.clear": {
        "commands": ["run"],
        "destructive": True,
        "description": "Clear all report data. REQUIRES user confirmation."
    },
    # ── 3D controls ──
    "3d.reconstruct": {
        "commands": ["run"],
        "value_type": "string",
        "description": "3D reconstruct an organ by ID (e.g., 'ctv_1', 'organ_52')"
    },
    "3d.wireframe": {
        "commands": ["toggle"],
        "values": ["on", "off"],
        "description": "Toggle wireframe mode on 3D meshes"
    },
    "3d.skin": {
        "commands": ["toggle"],
        "values": ["on", "off"],
        "description": "Toggle CT skin surface visibility"
    },
    "3d.dose_opacity": {
        "commands": ["set"],
        "value_type": "int",
        "range": [0, 100],
        "description": "3D dose mesh opacity"
    },
    "3d.dose_surface": {
        "commands": ["toggle"],
        "values": ["on", "off"],
        "description": "Toggle dose-textured CTV/OAR surface mode in the 3D viewer"
    },
    "3d.fit": {
        "commands": ["run"],
        "description": "Fit camera to show all 3D meshes"
    },
    "3d.reset": {
        "commands": ["run"],
        "description": "Reset 3D camera to default position and zoom"
    },
    "3d.show_all": {
        "commands": ["run"],
        "description": "Show all 3D meshes"
    },
    "3d.hide_all": {
        "commands": ["run"],
        "description": "Hide all 3D meshes"
    },
    # ── Chat controls ──
    "chat.language": {
        "commands": ["set"],
        "values": ["zh", "en"],
        "description": "Set the UI and LLM response language"
    },
    "chat.clear_history": {
        "commands": ["run"],
        "destructive": True,
        "description": "Clear the current chat history. REQUIRES user confirmation."
    },
    "chat.sidebar.toggle": {
        "commands": ["run"],
        "description": "Toggle the session sidebar visibility"
    },
    # ── Screenshot ──
    "screenshot": {
        "commands": ["run"],
        "values": ["axial", "sagittal", "coronal", "3d", "dvh", "full"],
        "description": "Capture a screenshot of the specified view"
    },
    # ── Tools ──
    "tool": {
        "commands": ["set"],
        "values": ["crosshair", "measure", "angle", "rect", "zoombox", "annotate", "eraser"],
        "description": "Active annotation/measurement tool"
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

            # Mark destructive actions
            if reg.get("destructive"):
                action["requires_confirm"] = True

            validated.append(action)

        if errors and not validated:
            return ToolResult(success=False, error="; ".join(errors))

        # Return validated actions — frontend will execute them
        result_data = {
            "actions": validated,
            "errors": errors,
            "executed": len(validated),
            "has_destructive": any(a.get("requires_confirm") for a in validated),
        }

        # Build human-readable descriptions for each action
        display_parts = []
        summary_parts = []
        for a in validated:
            t, c, v = a["target"], a["command"], a.get("value", "")
            desc = self._describe_action(t, c, v)
            display_parts.append(desc)
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
            metadata={
                **result_data,
                "display_message": " | ".join(display_parts),
            },
        )

    @staticmethod
    def _describe_action(target: str, command: str, value: Any = None) -> str:
        """Generate a human-readable description for a single UI action."""
        # Panel switching
        if target == "panel":
            names = {"input": "Input", "metrics": "Metrics", "seeds": "Seeds",
                     "viewers": "Viewers", "report": "Report"}
            return f"Switched to {names.get(value, value)} panel"

        # Viewer settings
        if target == "viewer.window":
            if command == "set": return f"Window width set to {value}"
            return f"Window width {command}d by {value or 50}"
        if target == "viewer.level":
            if command == "set": return f"Window level set to {value}"
            return f"Window level {command}d by {value or 20}"
        if target == "viewer.zoom":
            if command == "fit": return "Zoom reset to fit view"
            if command == "set": return f"Zoom set to {value}%"
            return f"Zoom {command}d by {value or 20}%"
        if target == "viewer.threshold": return f"HU threshold set to {value}"
        if target == "viewer.fullscreen": return f"{value} viewer fullscreen toggled"
        if target == "viewer.reset": return "Viewer settings reset to defaults"
        if target == "viewer.fit_all": return "All viewers fitted to image"
        if target == "viewer.preset": return f"Applied {value} window preset"

        # Overlay controls
        if target == "overlay.ctv":
            return f"CTV overlay {'shown' if command == 'show' else 'hidden' if command == 'hide' else 'toggled'}"
        if target == "overlay.oar":
            return f"OAR overlay {'shown' if command == 'show' else 'hidden' if command == 'hide' else 'toggled'}"
        if target in ("overlay.ctv.opacity", "overlay.oar.opacity", "overlay.dose.opacity"):
            name = target.split(".")[1].upper()
            return f"{name} overlay opacity set to {value}%"
        if target == "overlay.display_mode":
            mode_names = {"ct": "CT only", "overlay": "CT + overlay", "label": "Label only"}
            return f"Display mode changed to {mode_names.get(value, value)}"

        # Slice navigation
        if target.startswith("slice."):
            axis = target.split(".")[1]
            if command == "set": return f"Navigated to {axis} slice {value}"
            if command in ("next", "prev"): return f"Moved to {command} {axis} slice"
            if command in ("first", "last"): return f"Navigated to {command} {axis} slice"
            return f"{axis} slice: {command}"

        # Layout
        if target == "layout": return f"Viewer layout changed to {value}"

        # Data tree
        if target == "data_tree":
            if command in ("expand_all", "collapse_all"):
                return f"All data tree groups {command.replace('_', ' ')}"
            return f"Data tree '{value}' group {command}ed"
        if target == "tree.visibility":
            parts = value.split(",") if value else []
            return f"Organ {parts[0]} {'shown' if len(parts) > 1 and parts[1] == 'on' else 'hidden'}"
        if target == "tree.opacity":
            parts = value.split(",") if value else []
            return f"Organ {parts[0]} opacity set to {parts[1] if len(parts) > 1 else '?'}%"
        if target == "tree.reconstruct3d":
            return f"3D reconstruction started for '{value}'"
        if target in ("tree.group.visibility", "tree.group.opacity"):
            return f"Group {value} updated"
        if target == "tree.group.reconstruct3d":
            return f"3D reconstruction started for group '{value}'"
        if target == "tree.dose.visibility":
            return f"Dose overlay {'shown' if value == 'on' else 'hidden'}"
        if target in ("tree.trajectories.visibility", "tree.seeds.visibility",
                       "tree.needles.visibility", "tree.isosurfaces.visibility"):
            name = target.split(".")[1]
            return f"{name.capitalize()} {'shown' if value == 'on' else 'hidden'}"

        # Session management
        if target == "session.new": return "New chat session created"
        if target == "session.switch": return f"Switched to session {value}"
        if target == "session.rename": return f"Session renamed to '{value}'"
        if target == "session.delete": return f"⚠️ Deleted session {value}"
        if target == "session.clear_all": return "⚠️ All sessions cleared"

        # Planning
        if target == "plan.run": return "Planning pipeline started"
        if target == "plan.run_manual_step": return f"Manual workflow step started: {value}"
        if target == "ui.state": return "UI state snapshot synchronized"
        if target == "ui.control": return f"UI control {command}: {value}"
        if target == "training.mode":
            if command == "start": return f"Planning monitor started: {value or 'default goal'}"
            if command == "stop": return "Planning monitor stopped"
            if command == "advice": return "Detailed planning advice requested"
            return "Planning monitor status requested"
        if target == "manual.needle.create": return "Manual editable needle created"
        if target == "manual.seed.add": return "Manual seed added and dose preview requested"
        if target == "manual.dose.recompute": return "Manual dose and DVH preview recomputed"
        if target == "manual.plan.finish": return "Manual plan review requested"
        if target == "system.readiness": return "System readiness checklist requested"
        if target == "plan.reset": return "⚠️ Planning session reset"

        # Report
        if target == "report.autofill": return "Report auto-filled from planning data"
        if target == "report.export": return f"Report exported as {value}"
        if target == "report.import": return f"Report imported from {value}"
        if target == "report.snapshot.save": return "Report snapshot saved"
        if target == "report.snapshot.open": return "Snapshot manager opened"
        if target == "report.audit.open": return "Audit trail opened"
        if target == "report.validation.open": return "Validation checklist opened"
        if target == "report.preview.zoom":
            if command == "reset": return "Report preview zoom reset"
            return f"Report preview zoom {command}ed to {value}%"
        if target == "report.layout": return f"Report layout changed to {value}"
        if target == "report.section.toggle": return f"Report section '{value}' toggled"
        if target == "report.reference.add": return f"Reference '{value}' added"
        if target == "report.reference.remove": return f"Reference at index {value} removed"
        if target == "report.clear": return "⚠️ Report data cleared"

        # Tools
        if target == "tool":
            tool_names = {
                "crosshair": "crosshair", "measure": "measurement",
                "angle": "angle measurement", "rect": "rectangle ROI",
                "zoombox": "zoom box", "annotate": "annotation", "eraser": "eraser",
            }
            return f"Activated {tool_names.get(value, value)} tool"

        # 3D
        if target == "3d.reconstruct": return f"3D reconstruction started for '{value}'"
        if target == "3d.wireframe": return f"3D wireframe {value}"
        if target == "3d.skin": return f"3D skin surface {value}"
        if target == "3d.dose_opacity": return f"3D dose opacity set to {value}%"
        if target == "3d.dose_surface": return f"3D dose surface mode {value}"
        if target == "3d.fit": return "Camera fitted to all 3D meshes"
        if target == "3d.reset": return "3D camera reset to default"
        if target == "3d.show_all": return "All 3D meshes shown"
        if target == "3d.hide_all": return "All 3D meshes hidden"

        # Chat
        if target == "chat.language": return f"Language set to {value}"
        if target == "chat.clear_history": return "⚠️ Chat history cleared"
        if target == "chat.sidebar.toggle": return "Session sidebar toggled"

        # Screenshot
        if target == "screenshot": return f"Screenshot captured: {value}"

        # Fallback
        return f"{target}: {command}" + (f" → {value}" if value else "")
