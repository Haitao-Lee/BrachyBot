"""User-facing error contracts for the BrachyBot application.

The clinical/runtime layers may need the complete exception text for logs and
debugging, but that text is not a safe or useful chat response.  This module
keeps the boundary explicit: normalize malformed tool metadata, classify
transport/internal failures, and return a short localized explanation with a
corrective action.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any, Dict


logger = logging.getLogger(__name__)


def normalize_metadata(metadata: Any, *, source: str = "tool") -> Dict[str, Any]:
    """Return mapping-shaped metadata without allowing malformed adapters to crash.

    A few optional segmentation adapters are external/research code and have
    historically returned a list in the metadata slot.  Every caller assumes a
    mapping and calls ``.get``; normalizing at the ToolResult boundary turns
    that contract violation into a controlled failure/diagnostic instead of a
    second exception.  The payload itself is deliberately not retained: model
    outputs can contain arrays or images and are not safe to serialize into a
    Session snapshot.
    """
    if metadata is None:
        return {}
    if isinstance(metadata, Mapping):
        return dict(metadata)
    logger.error(
        "Tool returned non-mapping metadata; normalized to an empty mapping "
        "source=%s type=%s",
        source,
        type(metadata).__name__,
    )
    return {
        "_metadata_contract_error": True,
        "_metadata_type": type(metadata).__name__,
    }


def _language(lang: Any) -> str:
    return "zh" if str(lang or "").lower().startswith("zh") else "en"


def _localized(metadata: Any, lang: str) -> str:
    meta = normalize_metadata(metadata, source="user_error")
    for key in ("user_error_i18n", "display_message_i18n"):
        value = meta.get(key)
        if not isinstance(value, Mapping):
            continue
        text = str(value.get(lang) or value.get("en") or value.get("zh") or "").strip()
        if text:
            return text
    return ""


def is_provider_error(value: Any) -> bool:
    """Detect provider/transport diagnostics that must never reach chat."""
    text = str(value or "").strip().lower()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            "all providers failed",
            "no llm provider available",
            "invalid api key",
            "authentication failed",
            "unauthorized",
            "forbidden",
            "rate limit",
            "connection refused",
            "timed out",
            "missing sessionid",
            "x-opencode-session",
            "request is missing",
            "error from provider",
            "console go",
            "failed to route",
            "provider unavailable",
        )
    ) or bool(re.search(r"error\s*code\s*:\s*4\d\d", text)) and (
        "provider" in text or "session" in text or "request" in text
    )


def is_internal_error(value: Any) -> bool:
    """Detect exception/log-shaped text rather than ordinary explanations."""
    text = str(value or "").strip().lower()
    if not text:
        return False
    if is_provider_error(text):
        return True
    markers = (
        "traceback (most recent call last)",
        "object has no attribute",
        "list' object has no attribute",
        'list" object has no attribute',
        "tool execution failed:",
        "exception:",
        "jsondecodeerror",
        "unicodeencodeerror",
        "filenotfounderror",
        "connectionerror",
        "timeout error",
        "typeerror",
        "attributeerror",
        "valueerror",
        "keyerror",
        "runtimeerror",
        "modulenotfounderror",
        "importerror",
        "permissionerror",
        "surgicalguideerror",
        "cannot read",
        "is not a function",
        "networkerror",
        "status code",
        "no such file",
        "stack trace",
        "\n  file \"",
    )
    if any(marker in text for marker in markers):
        return True
    if re.match(r"^(?:⚠️\s*)?(?:error|exception|failed|failure|错误|异常)\s*:", text):
        return True
    # Absolute runtime paths and raw provider JSON are implementation details.
    return bool(re.search(r"(?:/home/|/workspace/|[a-z]:\\|error\s*code\s*:)", text))


def _generic_message(lang: str) -> str:
    if lang == "zh":
        return (
            "系统未能完成本次请求，病例数据没有因此被删除。请重试；如果问题重复出现，"
            "请保留执行追踪并联系管理员。"
        )
    return (
        "The system could not complete this request; the case data was not deleted. "
        "Please retry. If it happens again, keep the Execution Trace and contact the administrator."
    )


def _provider_message(lang: str) -> str:
    if lang == "zh":
        return (
            "AI 语言服务当前不可用，本次请求没有可靠完成，也没有继续启动临床规划。"
            "请先刷新页面或重新进入当前病例后重试；如果仍失败，请检查服务端的模型/会话配置。"
        )
    return (
        "The AI language service is currently unavailable, so this request was not completed reliably "
        "and no clinical planning was continued. Refresh the page or reopen the case and retry; "
        "if it persists, check the server model/session configuration."
    )


def format_tool_error(
    tool_name: str,
    error: Any = None,
    metadata: Any = None,
    lang: str = "en",
) -> str:
    """Convert a failed tool result into an actionable localized message.

    The original ``error`` remains available to the logger and diagnostics;
    this return value is the only form intended for the chat/trace surface.
    """
    language = _language(lang)
    meta = normalize_metadata(metadata, source=str(tool_name or "tool"))
    localized = _localized(meta, language)
    if localized:
        return localized

    raw = str(error or "").strip()
    lower = raw.lower()
    tool = str(tool_name or "").lower()
    if is_provider_error(raw):
        return _provider_message(language)

    invalid_metadata = bool(meta.get("_metadata_contract_error")) or (
        "list" in lower and "attribute" in lower and "get" in lower
    )
    if tool in {"ctv_segmentation", "biomedparse_segmentation"}:
        if invalid_metadata or "metadata" in lower or "ctv" in lower:
            return (
                "CTV 分割没有完成：分割模块返回了无法识别的数据格式，因此后续规划已停止。"
                "请确认上传的是 CT（不要把 CT 放到 CTV mask 入口），然后重新执行 CTV 分割；"
                "也可以上传与 CT 同一空间且包含目标的 CTV mask。"
                if language == "zh" else
                "CTV segmentation was not completed because the segmentation module returned an "
                "invalid data format, so downstream planning was stopped. Confirm that the CT was "
                "uploaded as CT rather than through the CTV-mask input, then rerun CTV segmentation; "
                "alternatively upload a CTV mask aligned to the CT."
            )
        return (
            "CTV 分割未完成，因此后续规划没有启动。请确认 CT 已完整加载并明确肿瘤部位/模型，"
            "然后重试；也可以上传已与 CT 对齐的 CTV mask。"
            if language == "zh" else
            "CTV segmentation did not complete, so downstream planning was not started. Confirm that "
            "the CT is fully loaded and the tumor site/model is specified, then retry; you can also "
            "upload a CTV mask aligned to the CT."
        )
    if tool == "oar_segmentation":
        return (
            "OAR 分割没有完成，后续规划已暂停。请确认 CT 已加载且影像方向/空间有效，然后重新执行 OAR 分割。"
            if language == "zh" else
            "OAR segmentation did not complete, so planning was paused. Confirm that the CT is loaded "
            "with a valid image geometry, then rerun OAR segmentation."
        )
    if tool in {"planning_pipeline", "trajectory_planning", "trajectory_init", "trajectory_refine", "seed_planning", "dose_engine", "dose_calc", "dose_recompute", "dose_evaluation"}:
        return (
            "放射性粒子规划没有完成。请先确认 CTV/OAR 已成功加载、靶区不是空白，并重新执行规划；"
            "如果仍失败，请保留执行追踪以便检查针道和剂量计算。"
            if language == "zh" else
            "The brachytherapy plan was not completed. Confirm that CTV/OAR data loaded successfully "
            "and that the target is not empty, then rerun planning. If it persists, keep the Execution "
            "Trace so the needle and dose calculation can be checked."
        )
    if tool in {"surgical_guide", "surgical_guide_generation"}:
        return (
            "手术导板没有生成。规划结果可能仍可查看，但导板文件不可用；请先确认针道有效且皮肤入口可连接，"
            "再重新生成导板。"
            if language == "zh" else
            "The surgical guide was not generated. The planning result may still be available, but the "
            "guide file is not usable. Confirm that the needle paths are valid and their skin entry points "
            "can be connected, then generate the guide again."
        )
    if tool in {"ui_controller", "ui_content", "ui_screenshot", "ui_annotate"}:
        return (
            "界面操作没有完成：当前数据或控件状态不满足该操作。请确认目标已加载/可见后重试；"
            "如果是查看器操作，请先打开对应查看器。"
            if language == "zh" else
            "The interface operation was not completed because the target or control state was not ready. "
            "Confirm that the target is loaded and visible, then retry; for viewer actions, open the relevant viewer first."
        )
    if not is_internal_error(raw) and raw:
        # Controlled, already-human-readable tool errors may be returned as-is.
        return raw
    return _generic_message(language)


def sanitize_user_response(response: Any, *, lang: str = "en", tool_name: str = "") -> str:
    """Last response-boundary guard against raw exceptions/provider payloads."""
    text = str(response or "").strip()
    if not text:
        return text
    if is_provider_error(text) or is_internal_error(text):
        return format_tool_error(tool_name or "request", text, {}, lang)
    return text
