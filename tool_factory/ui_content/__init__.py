"""Session-scoped content presentation tool.

This is deliberately separate from ``ui_screenshot``.  A screenshot command
asks the browser to capture a live viewer state; this tool asks it to read and
present data that already belongs to the active Session.  Keeping those paths
separate prevents a request such as "show the report figures" from failing
because a report panel is not currently mounted in the DOM.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping

from tool_factory import BaseTool, ToolResult


# The registry is intentionally capability-oriented rather than UI-page
# oriented.  New persistent Session artifacts can be added here without
# teaching the language model a new one-off screenshot target.
SESSION_CONTENT_TARGETS: Dict[str, str] = {
    "report_figures": "Saved figures generated for the current report",
    "report": "Current report and its saved figures",
    "session_screenshots": "Saved chat, Monitor, and report screenshots",
    "reply_attachments": "Visual attachments owned by the referenced visible assistant reply",
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

# ``visual`` means that the browser materializes the native visual
# representation of persisted content (for example, the Plotly DVH chart)
# and includes it with the structured summary.  It is a presentation
# capability, not a user-phrase route or a report-template shortcut.
SESSION_CONTENT_PRESENTATIONS = ("auto", "attachments", "summary", "visual", "open")
SESSION_CONTENT_MODES = ("chat", "monitor")
# A selection describes position in an already ordered persisted collection.
# It deliberately says nothing about a particular report template or viewer:
# the same contract works for report figures, saved screenshots, and future
# Session-owned visual collections.
SESSION_CONTENT_SELECTION_KINDS = ("all", "first", "last", "index")


def _selection_from_question(question: Any) -> Dict[str, Any]:
    """Infer a universal ordinal selector from a content request.

    The language model remains responsible for deciding *which* Session
    resource to read.  This small protocol parser only preserves an explicit
    positional reference such as "the last one" or "第 3 张" if a provider
    omitted the structured ``selection`` argument.  It is intentionally
    resource-agnostic so it cannot turn into a report-figure keyword route.
    """
    text = str(question or "").strip().lower()
    if not text:
        return {"kind": "all"}

    ordinal = re.search(
        r"(?:\u7b2c\s*|\b(?:no\.?|number)\s*)(\d+)\s*(?:\u5f20|\u4e2a|\u5e45|\u9879|\u4efd|\u56fe|\b(?:image|figure|item)s?\b)?",
        text,
        flags=re.IGNORECASE,
    )
    if ordinal:
        return {"kind": "index", "index": max(1, int(ordinal.group(1)))}
    if re.search(r"\b\d+(?:st|nd|rd|th)\b", text, flags=re.IGNORECASE):
        value = re.search(r"\b(\d+)(?:st|nd|rd|th)\b", text, flags=re.IGNORECASE)
        if value:
            return {"kind": "index", "index": max(1, int(value.group(1)))}
    if re.search(
        r"(?:\u6700\u540e|\u6700\u65b0|\u6700\u672b|\u5c3e\u90e8|\b(?:last|latest|final)\b)",
        text,
        flags=re.IGNORECASE,
    ):
        return {"kind": "last"}
    if re.search(
        r"(?:\u7b2c\u4e00|\u9996\u4e2a|\u5f00\u5934|\b(?:first|initial)\b)",
        text,
        flags=re.IGNORECASE,
    ):
        return {"kind": "first"}
    return {"kind": "all"}


def _normalize_selection(selection: Any, question: Any) -> Dict[str, Any]:
    """Normalize the browser-safe selection contract with a language fallback."""
    source = dict(selection) if isinstance(selection, Mapping) else {}
    kind = str(source.get("kind") or "").strip().lower()
    if kind not in SESSION_CONTENT_SELECTION_KINDS:
        return _selection_from_question(question)
    if kind != "index":
        return {"kind": kind}
    try:
        index = int(source.get("index"))
    except (TypeError, ValueError):
        return _selection_from_question(question)
    if index < 1:
        return _selection_from_question(question)
    return {"kind": "index", "index": index}


def _question_requests_analysis(question: Any) -> bool:
    """Recognize a generic request to reason about presented content.

    This is not a command whitelist.  It distinguishes passive presentation
    from a discourse act that needs evidence-grounded interpretation, across
    every Session content target and in both supported user languages.
    """
    text = str(question or "").strip().lower()
    if not text:
        return False
    return bool(re.search(
        r"(?:\u5206\u6790|\u89e3\u8bfb|\u89e3\u91ca|\u8bf4\u660e|\u63cf\u8ff0|\u4ecb\u7ecd|"
        r"\u8bc4\u4f30|\u8bc4\u4ef7|\u5224\u65ad|\u6bd4\u8f83|\u5bf9\u6bd4|"
        r"\u6709\u4ec0\u4e48\u95ee\u9898|\u7ed3\u679c\u5982\u4f55|"
        r"\b(?:analy[sz]e|interpret|explain|describe|assess|evaluate|compare|findings?)\b)",
        text,
        flags=re.IGNORECASE,
    ))


def normalize_session_content_request(
    *,
    question: Any,
    presentation: Any = "auto",
    selection: Any = None,
    analysis: Any = None,
) -> Dict[str, Any]:
    """Return the portable rendering contract for one content request.

    ``analysis`` is an evidence requirement, not a model-output preference.
    When it is true the frontend must return the selected visual attachment(s)
    through the existing hidden multimodal child bound to this same reply.
    """
    normalized_presentation = str(presentation or "auto").strip().lower()
    if normalized_presentation not in SESSION_CONTENT_PRESENTATIONS:
        normalized_presentation = "auto"
    normalized_selection = _normalize_selection(selection, question)
    normalized_analysis = bool(analysis is True or _question_requests_analysis(question))
    # ``visual`` tells the browser that the response is incomplete until it
    # has supplied native/persisted visual evidence. It remains harmless for
    # targets whose visual is a saved attachment rather than a live chart.
    if normalized_analysis and normalized_presentation in {"auto", "attachments", "summary"}:
        normalized_presentation = "visual"
    return {
        "presentation": normalized_presentation,
        "selection": normalized_selection,
        "analysis": normalized_analysis,
    }


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
        "reply_attachments": (
            "\u6b63\u5728\u8bfb\u53d6\u6700\u8fd1\u4e00\u6761\u53ef\u89c1\u56de\u590d\u4e2d\u7684\u56fe\u50cf\u9644\u4ef6\u3002",
            "Reading image attachments from the most recent visible reply.",
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
            "\u6b63\u5728\u8bfb\u53d6 DVH \u6570\u636e\u5e76\u751f\u6210\u56fe\u8868\u622a\u56fe\u3002",
            "Reading the current DVH data and generating a chart capture.",
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
            "screenshots, attachments from a preceding assistant reply, planning "
            "results, dose/DVH, CT, structures, Surgical "
            "Guide, Data Tree, chat history, or a persistent Data Tree object "
            "identified by object_ids. For content with a native visual "
            "representation, such as DVH, presentation=auto can include the "
            "real chart capture together with a data-grounded summary. Use "
            "When the user refers to an image attached to a preceding assistant "
            "reply, use target=reply_attachments rather than a global report or "
            "screenshot collection. Use selection to preserve a user reference to the first, last, or an "
            "ordinal item in an ordered persisted collection. Set analysis=true "
            "when the user asks to interpret, describe, compare, assess, or "
            "explain the presented content; the selected visual evidence will "
            "then be analyzed in the same assistant reply. Use "
            "ui_screenshot only when the user needs a newly captured live "
            "Viewer/UI image or a custom multi-view composition."
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
                    "description": "Prefer saved attachments, a structured summary, a native chart/image plus summary, or opening the matching panel.",
                },
                "selection": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": list(SESSION_CONTENT_SELECTION_KINDS),
                            "default": "all",
                        },
                        "index": {
                            "type": "integer",
                            "minimum": 1,
                        },
                    },
                    "description": "Optional item selection in displayed order. Use last for the latest/last item, first for the first item, index for an ordinal item, or all when the request has no item reference.",
                },
                "analysis": {
                    "type": "boolean",
                    "default": False,
                    "description": "Set true when the user wants an interpretation, explanation, comparison, assessment, or detailed description of the selected content rather than passive presentation only.",
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
        mode = str(kwargs.get("mode") or "chat").strip().lower()
        if mode not in SESSION_CONTENT_MODES:
            mode = "chat"
        question = str(kwargs.get("question") or "").strip()
        request_contract = normalize_session_content_request(
            question=question,
            presentation=presentation,
            selection=kwargs.get("selection"),
            analysis=kwargs.get("analysis"),
        )
        command = {
            "command": "present_session_content",
            "target": target,
            "presentation": request_contract["presentation"],
            "selection": request_contract["selection"],
            "analysis": request_contract["analysis"],
            "mode": mode,
            "question": question,
            "planning_id": str(kwargs.get("planning_id") or "").strip(),
            "object_ids": [str(value) for value in (kwargs.get("object_ids") or []) if str(value)],
        }
        model_instruction = (
            "The browser will present the requested persisted Session content in "
            "the same assistant reply. When analysis is requested, it will return "
            "only the selected visual evidence through a hidden, parent-bound "
            "multimodal follow-up before producing the user-visible interpretation. "
            "Do not expose this command, file paths, or internal parameters to the "
            "user. Do not call ui_screenshot unless the user explicitly needs a new "
            "live Viewer capture."
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
