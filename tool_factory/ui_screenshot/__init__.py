"""
UI Screenshot Tool
==================
Enables BrachyBot's LLM to capture screenshots of any UI component.
The LLM calls this tool → frontend captures the target → uploads to server → returns URL.

Flow:
    1. LLM calls ui_screenshot(target="viewer-axial", question="分析分割效果")
    2. Tool returns {command: "screenshot", target: "...", question: "..."}
    3. Frontend intercepts this result in the SSE step handler
    4. Frontend captures the target element using html2canvas
    5. Frontend uploads to /api/screenshot
    6. Frontend displays image in chat
    7. Frontend sends follow-up message with image URL to LLM
    8. LLM receives multimodal content and responds with analysis
"""

import json
import logging
from typing import Dict, Any
from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Valid screenshot targets
SCREENSHOT_TARGETS = {
    "viewer-axial": "Axial viewer panel (2D slice view)",
    "viewer-sagittal": "Sagittal viewer panel",
    "viewer-coronal": "Coronal viewer panel",
    "viewer-3d": "3D reconstruction view",
    "data-tree": "Data tree panel (organ list, visibility controls)",
    "chat": "Chat panel (conversation history)",
    "metrics": "Metrics panel (dose evaluation, DVH)",
    "input": "Input panel (file loading, configuration)",
    "seeds": "Seeds panel (seed planning results)",
    "planning": "Planning panel (step-by-step planning tools)",
    "full": "Full page screenshot",
    "overlay-controls": "Overlay control area (opacity sliders, toggles)",
}


class UIScreenshotTool(BaseTool):
    """Capture screenshots of any BrachyBot UI component for visual analysis."""

    @property
    def name(self) -> str:
        return "ui_screenshot"

    @property
    def description(self) -> str:
        targets = ", ".join(SCREENSHOT_TARGETS.keys())
        return (
            "Capture a screenshot of any BrachyBot UI component. "
            "Use this when you need to SEE the current state of the UI — viewer slices, "
            "3D reconstructions, data tree, overlays, segmentation results, etc. "
            "The screenshot will be displayed in chat and sent to you for visual analysis. "
            f"Available targets: {targets}. "
            "You can also specify a slice index to navigate to before capturing."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": f"UI component to capture. Options: {', '.join(SCREENSHOT_TARGETS.keys())}",
                    "enum": list(SCREENSHOT_TARGETS.keys()),
                },
                "question": {
                    "type": "string",
                    "description": "What you want to analyze in the screenshot. This will be sent along with the image for multimodal analysis.",
                },
                "slice_index": {
                    "type": "integer",
                    "description": "Optional: navigate to this slice index before capturing (for viewer targets).",
                },
                "axis": {
                    "type": "string",
                    "description": "Optional: which axis to navigate (axial, sagittal, coronal).",
                    "enum": ["axial", "sagittal", "coronal"],
                },
                "description": {
                    "type": "string",
                    "description": "Optional: brief description of what the screenshot shows (for display in chat).",
                },
            },
            "required": ["target", "question"],
        }

    def _execute(self, **kwargs) -> ToolResult:
        target = kwargs.get("target", "full")
        question = kwargs.get("question", "Analyze this screenshot")
        slice_index = kwargs.get("slice_index")
        axis = kwargs.get("axis")
        description = kwargs.get("description", "")

        if target not in SCREENSHOT_TARGETS:
            return ToolResult(
                success=False,
                error=f"Unknown target '{target}'. Valid: {', '.join(SCREENSHOT_TARGETS.keys())}"
            )

        # Build the command for the frontend to execute
        command = {
            "command": "screenshot",
            "target": target,
            "question": question,
            "description": description or SCREENSHOT_TARGETS[target],
        }

        if slice_index is not None:
            command["slice_index"] = int(slice_index)
        if axis:
            command["axis"] = axis

        return ToolResult(
            success=True,
            message=(
                f"Screenshot of '{target}' has been requested and is being captured. "
                f"The image will appear in the chat shortly. "
                f"DO NOT call ui_screenshot again. "
                f"Wait for the image to arrive, then analyze it and respond to the user."
            ),
            metadata={
                "screenshot_command": command,
                "target": target,
                "question": question,
                "description": description or SCREENSHOT_TARGETS[target],
                # This flag tells the frontend to intercept and execute
                "frontend_action": "screenshot",
            },
        )
