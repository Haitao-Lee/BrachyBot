"""
Viewer Command Tool
==================
Enables LLM to directly control the CT viewer through natural language commands.
Supports navigation, segmentation overlay, window/level, and more.
"""

import os
import sys
import json
import logging
import requests
from typing import Dict, Any, Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8080/api"


class ViewerCommandTool(BaseTool):
    """Control the CT viewer through API commands."""

    @property
    def name(self) -> str:
        return "viewer_command"

    @property
    def description(self) -> str:
        return (
            "Control the CT viewer with natural language commands. "
            "Actions: navigate, set_window, set_preset, toggle_overlay, set_threshold, "
            "get_state, zoom_in, zoom_out, reset_view, screenshot. "
            "Use this to help the user view specific anatomy, adjust visualization, etc."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform: navigate, set_window, set_preset, toggle_overlay, set_threshold, get_state, zoom_in, zoom_out, reset_view",
                    "enum": ["navigate", "set_window", "set_preset", "toggle_overlay", "set_threshold", "get_state", "zoom_in", "zoom_out", "reset_view"]
                },
                "axis": {
                    "type": "string",
                    "description": "For navigate: which axis (axial, sagittal, coronal)",
                    "enum": ["axial", "sagittal", "coronal"]
                },
                "slice_index": {
                    "type": "integer",
                    "description": "For navigate: slice index to go to"
                },
                "window": {
                    "type": "integer",
                    "description": "For set_window: window width"
                },
                "level": {
                    "type": "integer",
                    "description": "For set_window: window level (center)"
                },
                "preset": {
                    "type": "string",
                    "description": "For set_preset: soft, bone, lung, brain",
                    "enum": ["soft", "bone", "lung", "brain"]
                },
                "overlay": {
                    "type": "string",
                    "description": "For toggle_overlay: ctv, oar",
                    "enum": ["ctv", "oar"]
                },
                "threshold": {
                    "type": "integer",
                    "description": "For set_threshold: HU threshold value"
                }
            },
            "required": ["action"]
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": "string"},
                "state": {"type": "object"}
            }
        }

    def _execute(self, **kwargs) -> ToolResult:
        """Execute viewer command."""
        action = kwargs.get("action")

        try:
            if action == "navigate":
                return self._navigate(kwargs.get("axis", "axial"), kwargs.get("slice_index", 0))
            elif action == "set_window":
                return self._set_window(kwargs.get("window", 400), kwargs.get("level", 40))
            elif action == "set_preset":
                return self._set_preset(kwargs.get("preset", "soft"))
            elif action == "toggle_overlay":
                return self._toggle_overlay(kwargs.get("overlay", "ctv"))
            elif action == "set_threshold":
                return self._set_threshold(kwargs.get("threshold", -1000))
            elif action == "get_state":
                return self._get_state()
            elif action == "zoom_in":
                return self._zoom(1.2)
            elif action == "zoom_out":
                return self._zoom(0.8)
            elif action == "reset_view":
                return self._reset_view()
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown action: {action}",
                    message=f"Unknown action: {action}"
                )
        except Exception as e:
            logger.error(f"Viewer command failed: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Viewer command failed: {e}"
            )

    def _navigate(self, axis: str, slice_index: int) -> ToolResult:
        """Navigate to a specific slice."""
        # First switch to the viewers panel
        self._switch_panel("viewers")

        # Then navigate to the slice
        res = requests.post(f"{API_BASE}/viewer/control", json={
            "action": "navigate_slice",
            "axis": axis,
            "slice_index": slice_index
        })

        if res.ok:
            data = res.json()
            return ToolResult(
                success=True,
                message=f"Navigated to {axis} slice {slice_index}",
                metadata={"axis": axis, "slice_index": slice_index}
            )
        else:
            return ToolResult(success=False, error="Navigation failed", message="Navigation failed")

    def _set_window(self, window: int, level: int) -> ToolResult:
        """Set window/level."""
        res = requests.post(f"{API_BASE}/viewer/control", json={
            "action": "set_window",
            "window": window,
            "level": level
        })

        if res.ok:
            return ToolResult(
                success=True,
                message=f"Window set to W:{window} L:{level}",
                metadata={"window": window, "level": level}
            )
        else:
            return ToolResult(success=False, error="Set window failed", message="Set window failed")

    def _set_preset(self, preset: str) -> ToolResult:
        """Set window preset."""
        res = requests.post(f"{API_BASE}/viewer/control", json={
            "action": "set_preset",
            "preset": preset
        })

        if res.ok:
            return ToolResult(
                success=True,
                message=f"Preset set to {preset}",
                metadata={"preset": preset}
            )
        else:
            return ToolResult(success=False, error="Set preset failed", message="Set preset failed")

    def _toggle_overlay(self, overlay: str) -> ToolResult:
        """Toggle CTV/OAR overlay."""
        res = requests.post(f"{API_BASE}/viewer/control", json={
            "action": "toggle_overlay",
            "overlay": overlay
        })

        if res.ok:
            return ToolResult(
                success=True,
                message=f"Toggled {overlay} overlay",
                metadata={"overlay": overlay}
            )
        else:
            return ToolResult(success=False, error="Toggle overlay failed", message="Toggle overlay failed")

    def _set_threshold(self, threshold: int) -> ToolResult:
        """Set HU threshold."""
        res = requests.post(f"{API_BASE}/viewer/control", json={
            "action": "set_threshold",
            "threshold": threshold
        })

        if res.ok:
            return ToolResult(
                success=True,
                message=f"Threshold set to {threshold} HU",
                metadata={"threshold": threshold}
            )
        else:
            return ToolResult(success=False, error="Set threshold failed", message="Set threshold failed")

    def _get_state(self) -> ToolResult:
        """Get current viewer state."""
        res = requests.post(f"{API_BASE}/viewer/control", json={
            "action": "get_state"
        })

        if res.ok:
            data = res.json()
            return ToolResult(
                success=True,
                message=json.dumps(data, indent=2),
                metadata=data
            )
        else:
            return ToolResult(success=False, error="Get state failed", message="Get state failed")

    def _zoom(self, factor: float) -> ToolResult:
        """Zoom in/out."""
        res = requests.post(f"{API_BASE}/viewer/control", json={
            "action": "zoom",
            "factor": factor
        })

        if res.ok:
            direction = "in" if factor > 1 else "out"
            return ToolResult(
                success=True,
                message=f"Zoomed {direction}",
                metadata={"factor": factor}
            )
        else:
            return ToolResult(success=False, error="Zoom failed", message="Zoom failed")

    def _reset_view(self) -> ToolResult:
        """Reset view to default."""
        res = requests.post(f"{API_BASE}/viewer/control", json={
            "action": "reset"
        })

        if res.ok:
            return ToolResult(
                success=True,
                message="View reset to default"
            )
        else:
            return ToolResult(success=False, error="Reset failed", message="Reset failed")

    def _switch_panel(self, panel: str) -> None:
        """Switch to a specific panel (via frontend JS - not directly callable from backend)."""
        # This is handled by the frontend when it receives the navigate command
        pass


if __name__ == "__main__":
    tool = ViewerCommandTool()
    print(f"Tool: {tool.name}")
    print(f"Description: {tool.description}")
    print(f"Input Schema: {json.dumps(tool.input_schema, indent=2)}")
