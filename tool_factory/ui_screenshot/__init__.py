"""
UI Screenshot Tool
==================
Enables BrachyBot's LLM to capture screenshots of any UI component.
The LLM calls this tool → frontend captures the target → uploads to server → returns URL.

Flow:
    1. LLM calls ui_screenshot(target="viewer-axial", question="Analyze segmentation overlay")
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

# Valid screenshot targets — must match frontend _SCREENSHOT_TARGET_MAP
SCREENSHOT_TARGETS = {
    "viewer-axial": "Axial viewer panel (2D slice view)",
    "viewer-sagittal": "Sagittal viewer panel",
    "viewer-coronal": "Coronal viewer panel",
    "dose-overview": "Dose report overview (axial, sagittal, coronal CT with dose overlay, colorbar, and DVH chart)",
    "viewer-3d": "3D reconstruction view",
    "data-tree": "Data tree panel (organ list, visibility controls)",
    "chat": "Chat panel (conversation history)",
    "metrics": "Metrics panel (dose evaluation, DVH)",
    "dvh": "DVH chart only (dose-volume histogram)",
    "input": "Input panel (file loading, configuration)",
    "seeds": "Seeds panel (seed planning results)",
    "planning": "Planning panel (step-by-step planning tools)",
    "report": "Report panel (report editor and preview)",
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
            "Take a screenshot of the UI. ONLY use this when the user EXPLICITLY asks "
            "for a screenshot, image, or picture ('截图', '拍个照', 'show me the image'). "
            "Do NOT call this automatically after planning or other tasks. "
            "For a request to see the current dose distribution without a specified plane, "
            "use target `dose-overview`; it captures the three 2D planes and the DVH together, "
            "like the report figure. For a request to explain, analyze, or describe a chart, "
            "request the relevant screenshot once and then answer from the returned image; "
            "never issue a second screenshot call for the same request. "
            "Available targets: " + targets + ". "
            "The screenshot will be displayed in chat for the user to view."
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
        target = {
            "dose": "dose-overview",
            "dose_distribution": "dose-overview",
            "dose-distribution": "dose-overview",
            "dose_overview": "dose-overview",
            "dvh-chart": "dvh",
            "dose-volume-histogram": "dvh",
        }.get(target, target)
        question = kwargs.get("question", "Analyze this screenshot")
        slice_index = kwargs.get("slice_index")
        axis = kwargs.get("axis")
        description = kwargs.get("description", "")

        # A common model error is to collapse an unspecified dose overview
        # into the axial viewer. Preserve an explicit axial-only request,
        # but promote generic dose-distribution questions to the report-like
        # overview so the user receives all three planes and the DVH.
        question_text = str(question or "")
        generic_dose = (
            target == "viewer-axial"
            and any(token in question_text.lower() for token in (
                "dose distribution", "dose map", "dose cloud", "剂量分布", "剂量云图",
            ))
            and not any(token in question_text.lower() for token in (
                "axial only", "only axial", "仅轴向", "只看轴向", "轴向视图",
            ))
        )
        if generic_dose:
            target = "dose-overview"

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
