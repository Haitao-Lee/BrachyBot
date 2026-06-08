"""
Viewer Command Tool
==================
Control CT viewer via frontend actions (not HTTP API).
Returns action commands for the frontend to execute.
"""

import os
import sys
import json
import logging
from typing import Dict, Any, Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ViewerCommandTool(BaseTool):
    """Control the CT viewer via structured frontend actions."""

    def __init__(self, agent=None):
        self._agent = agent

    @property
    def name(self) -> str:
        return "viewer_command"

    @property
    def description(self) -> str:
        return (
            "Control CT viewer: navigate slices, adjust window/level, toggle overlays, "
            "set presets, zoom. Returns actions for frontend to execute. "
            "Use when user says 'adjust contrast', 'show bone window', 'zoom in', etc."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "description": "List of viewer actions",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string"},
                            "command": {"type": "string"},
                            "value": {}
                        },
                        "required": ["target", "command"]
                    }
                },
                "preset": {
                    "type": "string",
                    "description": "Window preset: 'lung', 'bone', 'soft_tissue', 'brain', 'default'",
                    "enum": ["lung", "bone", "soft_tissue", "brain", "default"]
                }
            }
        }

    def _execute(self, **kwargs) -> ToolResult:
        actions = kwargs.get("actions", [])
        preset = kwargs.get("preset")

        if preset:
            actions.extend(self._get_preset_actions(preset))

        if not actions:
            return ToolResult(success=False, error="No actions", message="No viewer actions specified.")

        return ToolResult(
            success=True,
            message=f"Viewer: {len(actions)} action(s) queued",
            metadata={"actions": actions, "executed": len(actions)}
        )

    def _get_preset_actions(self, preset: str) -> List[Dict]:
        presets = {
            "lung": [
                {"target": "viewer.window", "command": "set", "value": 1500},
                {"target": "viewer.level", "command": "set", "value": -600},
            ],
            "bone": [
                {"target": "viewer.window", "command": "set", "value": 2000},
                {"target": "viewer.level", "command": "set", "value": 300},
            ],
            "soft_tissue": [
                {"target": "viewer.window", "command": "set", "value": 400},
                {"target": "viewer.level", "command": "set", "value": 40},
            ],
            "brain": [
                {"target": "viewer.window", "command": "set", "value": 80},
                {"target": "viewer.level", "command": "set", "value": 40},
            ],
            "default": [
                {"target": "viewer.window", "command": "set", "value": 400},
                {"target": "viewer.level", "command": "set", "value": 40},
            ],
        }
        return presets.get(preset, presets["default"])
