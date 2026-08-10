"""Session-scoped content presentation tool.

This is deliberately separate from ``ui_screenshot``.  A screenshot command
asks the browser to capture a live viewer state; this tool asks it to read and
present data that already belongs to the active Session.  Keeping those paths
separate prevents a request such as "show the report figures" from failing
because a report panel is not currently mounted in the DOM.
"""

from __future__ import annotations

from typing import Any, Dict

from tool_factory import BaseTool, ToolResult


# The registry is intentionally capability-oriented rather than UI-page
# oriented.  New persistent Session artifacts can be added here without
# teaching the language model a new one-off screenshot target.
SESSION_CONTENT_TARGETS: Dict[str, str] = {
    "report_figures": "Saved figures generated for the current report",
    "report": "Current report and its saved figures",
    "session_screenshots": "Saved chat, Monitor, and report screenshots",
    "planning": "Current planning result and planning artifacts",
    "dose": "Current dose volume, overlays, and dose metrics",
    "dvh": "Current dose-volume histogram data and chart",
    "metrics": "Current planning and evaluation metrics",
    "ct": "Loaded CT image and its persisted metadata",
    "structures": "Persisted CTV, OAR, skin, and other structures",
    "surgical_guide": "Current Surgical Guide artifact",
    "data_tree": "Current Session Data Tree objects",
    "chat_history": "Current Session conversation and execution history",
    "artifact": "A persistent Session resource selected by stable object ID",
    "session_summary": "Available content in the current Session",
}

SESSION_CONTENT_PRESENTATIONS = ("auto", "attachments", "summary", "open")
SESSION_CONTENT_MODES = ("chat", "monitor")


def _trace_summary(target: str) -> Dict[str, str]:
    """Return short, localized trace text without exposing internal paths."""
    summaries = {
        "report_figures": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d\u62a5\u544a\u4e2d\u5df2\u4fdd\u5b58\u7684\u622a\u56fe\u3002",
            "Reading the saved figures from the current report.",
        ),
        "session_screenshots": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d Session \u4e2d\u5df2\u4fdd\u5b58\u7684\u622a\u56fe\u3002",
            "Reading saved screenshots from the current Session.",
        ),
        "report": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d\u62a5\u544a\u548c\u5176\u4fdd\u5b58\u9644\u4ef6\u3002",
            "Reading the current report and its saved attachments.",
        ),
        "planning": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d\u89c4\u5212\u7ed3\u679c\u3002",
            "Reading the current planning result.",
        ),
        "dose": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d\u5242\u91cf\u7ed3\u679c\u3002",
            "Reading the current dose result.",
        ),
        "dvh": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d DVH \u6570\u636e\u3002",
            "Reading the current DVH data.",
        ),
        "metrics": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d\u89c4\u5212\u6307\u6807\u3002",
            "Reading the current planning metrics.",
        ),
        "ct": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d CT \u56fe\u50cf\u548c\u5143\u6570\u636e\u3002",
            "Reading the loaded CT image and metadata.",
        ),
        "structures": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d\u7ed3\u6784\u548c\u5206\u5272\u7ed3\u679c\u3002",
            "Reading the current structures and segmentation results.",
        ),
        "surgical_guide": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d\u624b\u672f\u5bfc\u677f\u3002",
            "Reading the current Surgical Guide.",
        ),
        "data_tree": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d Session \u7684 Data Tree\u3002",
            "Reading the current Session Data Tree.",
        ),
        "chat_history": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d Session \u7684\u5bf9\u8bdd\u5386\u53f2\u3002",
            "Reading the current Session conversation history.",
        ),
        "artifact": (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d Session \u4e2d\u6307\u5b9a\u7684\u6570\u636e\u5bf9\u8c61\u3002",
            "Reading the selected data object from the current Session.",
        ),
        "session_summary": (
            "\u6b63\u5728\u68c0\u67e5\u5f53\u524d Session \u4e2d\u53ef\u5448\u73b0\u7684\u5185\u5bb9\u3002",
            "Checking the content available in the current Session.",
        ),
    }
    zh, en = summaries.get(
        target,
        (
            "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d Session \u4e2d\u5df2\u4fdd\u5b58\u7684\u5185\u5bb9\u3002",
            "Reading saved content from the current Session.",
        ),
    )
    return {"zh": zh, "en": en}


class UISessionContentTool(BaseTool):
    """Create a Session-bound browser command for persisted content."""

    @property
    def name(self) -> str:
        return "ui_content"

    @property
    def description(self) -> str:
        return (
            "Present real data already stored in the active Session. Use this "
            "for requests to show saved report figures, report content, prior "
            "screenshots, planning results, dose/DVH, CT, structures, Surgical "
            "Guide, Data Tree, chat history, or a persistent Data Tree object "
            "identified by object_ids. This does not create a new "
            "screenshot. Use ui_screenshot only when the user needs a newly "
            "captured live Viewer/UI image."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": list(SESSION_CONTENT_TARGETS.keys()),
                    "description": "Persisted Session content to present.",
                },
                "presentation": {
                    "type": "string",
                    "enum": list(SESSION_CONTENT_PRESENTATIONS),
                    "default": "auto",
                    "description": "Prefer attachments, a structured summary, or opening the matching panel.",
                },
                "mode": {
                    "type": "string",
                    "enum": list(SESSION_CONTENT_MODES),
                    "default": "chat",
                    "description": "Use monitor only when a Monitor reply presents Session content.",
                },
                "question": {
                    "type": "string",
                    "description": "The user's content request in their language.",
                },
                "planning_id": {
                    "type": "string",
                    "description": "Optional stable planning ID for historical planning content.",
                },
                "object_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 64,
                    "description": "Optional stable object IDs to focus the presentation on.",
                },
            },
            "required": ["target", "question"],
        }

    def _execute(self, **kwargs: Any) -> ToolResult:
        target = str(kwargs.get("target") or "").strip().lower()
        if target not in SESSION_CONTENT_TARGETS:
            return ToolResult(
                success=False,
                error="Unsupported Session content target.",
                metadata={
                    "user_error_i18n": {
                        "zh": "\u8bf7\u6c42\u7684 Session \u5185\u5bb9\u7c7b\u578b\u6682\u4e0d\u652f\u6301\u3002",
                        "en": "The requested Session content type is not supported yet.",
                    },
                    "internal_only": True,
                    "user_visible": False,
                },
            )
        presentation = str(kwargs.get("presentation") or "auto").strip().lower()
        if presentation not in SESSION_CONTENT_PRESENTATIONS:
            presentation = "auto"
        mode = str(kwargs.get("mode") or "chat").strip().lower()
        if mode not in SESSION_CONTENT_MODES:
            mode = "chat"
        question = str(kwargs.get("question") or "").strip()
        command = {
            "command": "present_session_content",
            "target": target,
            "presentation": presentation,
            "mode": mode,
            "question": question,
            "planning_id": str(kwargs.get("planning_id") or "").strip(),
            "object_ids": [str(value) for value in (kwargs.get("object_ids") or []) if str(value)],
        }
        model_instruction = (
            "The browser will present the requested persisted Session content in "
            "the same assistant reply. Do not expose this command, file paths, "
            "or internal parameters to the user. Do not call ui_screenshot unless "
            "the user explicitly needs a new live Viewer capture."
        )
        return ToolResult(
            success=True,
            message=model_instruction,
            metadata={
                "frontend_action": "session_content",
                "content_command": command,
                "content_target": target,
                "internal_only": True,
                "user_visible": False,
                "trace_summary_i18n": _trace_summary(target),
                "model_instruction": model_instruction,
            },
        )
