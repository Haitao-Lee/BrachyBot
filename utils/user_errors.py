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

from utils.display_paths import relativize_text

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


_PROVIDER_ERROR_MARKERS = (
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

# A provider/transport diagnostic is a short, error-led machine string.  Model
# authored prose can legitimately mention one of the markers above (for
# example when explaining a past outage), so a plain substring scan must never
# classify a normal answer as a failure.  Require both a recognized lead at the
# very start of the text (after only punctuation/emoji/whitespace) and a
# bounded length.
_PROVIDER_ERROR_LEADS = (
    "error",
    "llm error",
    "exception",
    "traceback",
    "failed",
    "unable",
    "all providers failed",
    "no llm provider available",
    "provider unavailable",
    "error from provider",
    "failed to route",
)
_PROVIDER_ERROR_MAX_CHARS = 500
_LEADING_NON_WORD_RE = re.compile(r"^[\s\W_]+", re.UNICODE)


def is_provider_error(value: Any) -> bool:
    """Detect provider/transport diagnostics that must never reach chat.

    Diagnostics are short, error-led machine strings; ordinary model prose that
    merely quotes one of the markers is not a failure.  Both a recognized error
    lead and a bounded length are required, so an answer such as "this session
    once reported ``Error: No LLM provider available``" is preserved.
    """
    text = str(value or "").strip()
    if not text or len(text) > _PROVIDER_ERROR_MAX_CHARS:
        return False
    low = text.lower()
    structured = bool(re.search(r"error\s*code\s*:\s*4\d\d", low)) and (
        "provider" in low or "session" in low or "request" in low
    )
    if not any(marker in low for marker in _PROVIDER_ERROR_MARKERS) and not structured:
        return False
    head = _LEADING_NON_WORD_RE.sub("", low)
    return head.startswith(_PROVIDER_ERROR_LEADS)


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


_INTERNAL_PATH_RE = re.compile(
    r"(?:/home/|/workspace/|[A-Za-z]:\\)[^\s`'\"()\[\]{}<>,;，。；、）】]*"
)


def redact_internal_paths(value: Any, *, lang: str = "en") -> str:
    """Hide server-side absolute paths without discarding a useful answer.

    A completed action may legitimately name its output ("saved to
    plan_x.md").  Replacing that whole reply with a failure notice because the
    model quoted the server directory is both wrong and alarming, so absolute
    runtime paths are rewritten to their file name (or a placeholder) instead.
    """
    text = str(value or "")
    if not text:
        return text
    placeholder = (
        "（服务器本地路径已隐藏）" if _language(lang) == "zh" else "(server path hidden)"
    )

    def _replacement(match: "re.Match[str]") -> str:
        matched = match.group(0)
        candidate = matched.rstrip(".,;:!?")
        tail = matched[len(candidate):]
        name = re.split(r"[\\/]+", candidate)[-1]
        if name and "." in name:
            return name + tail
        return placeholder + tail

    return _INTERNAL_PATH_RE.sub(_replacement, text)


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

    invalid_metadata = (
        bool(meta.get("_metadata_contract_error"))
        or bool(meta.get("ctv_contract_error"))
        or ("list" in lower and "attribute" in lower and "get" in lower)
        or ("list" in lower and "attribute" in lower and "items" in lower)
    )
    if tool in {"ctv_segmentation", "biomedparse_segmentation"}:
        if invalid_metadata:
            return (
                "CTV 分割没有完成：CT 影像已进入分割流程，但模型结果在服务器内部校验/整理时发现了格式不一致，"
                "因此系统安全停止了后续规划。本次提示不表示 CT 被误传到 CTV mask 入口；请直接重新执行 CTV 分割。"
                "如果仍然失败，请保留执行追踪并联系管理员；只有在使用手工 CTV mask 时，才需要另外确认 mask 与 CT 同空间对齐。"
                if language == "zh" else
                "CTV segmentation did not complete because the CT reached the segmentation stage but the model "
                "result failed an internal format/normalization check, so downstream planning was stopped safely. "
                "This message does not mean that the CT was uploaded through the CTV-mask input; rerun CTV segmentation. "
                "If it happens again, keep the Execution Trace and contact the administrator. Only manual CTV-mask "
                "uploads additionally need to be checked for alignment with the CT."
            )
        if bool(meta.get("ctv_inference_error")) or any(
            marker in lower
            for marker in (
                "nnunet inference failed",
                "inference failed",
                "cuda out of memory",
                "out of memory",
                "memoryerror",
            )
        ):
            return (
                "CTV 分割没有完成：胰腺肿瘤模型在推理阶段没有成功输出结果，后续规划已安全暂停。"
                "这不是 CT 被误传到 CTV mask 入口。请确认服务端 GPU/模型运行状态后重新执行 CTV 分割；"
                "若再次失败，请保留执行追踪中的失败原因交给管理员。"
                if language == "zh" else
                "CTV segmentation did not complete because the pancreatic-tumor model failed during inference, so downstream planning was stopped safely. "
                "This does not mean the CT was uploaded through the CTV-mask input. Check the server GPU/model runtime and retry CTV segmentation; "
                "if it fails again, keep the failure details from the Execution Trace for the administrator."
            )
        if any(
            marker in lower
            for marker in (
                "model directory not found",
                "checkpoint",
                "model is not installed",
                "nnunet_results",
            )
        ):
            return (
                "CTV 分割没有完成：服务器当前没有找到可用的肿瘤分割模型或模型权重。"
                "请检查模型安装/权重配置后再重试；本次没有继续执行规划。"
                if language == "zh" else
                "CTV segmentation did not complete because the server could not find a usable tumor model or checkpoint. "
                "Check the model installation/configuration and retry; planning was not continued."
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
        # A planning/dose tool can fail because its inputs are not loaded yet —
        # which is a resource/loading condition, not evidence that the plan is
        # incomplete.  Claiming "规划没有完成" for a missing array is the exact
        # hallucination users reported on an already-planned case, so the
        # missing-input case gets its own honest, retryable message.
        missing_input = any(
            marker in lower
            for marker in (
                "is required", "required", "must be provided", "no ctv", "no ct",
                "not available", "not loaded", "has not been loaded", "not hydrated",
                "missing", "unavailable", "not found", "为空", "尚未加载",
                "未加载", "不存在", "缺少",
                # Server-injected array/object fields are not JSON values; a
                # type rejection here is an input-plumbing condition, not a
                # planning computation failure.
                "invalid parameter type", "not json serializable",
                "is not json serializable", "serializable",
            )
        ) and not any(
            marker in lower
            for marker in (
                "not completed", "did not complete", "incomplete",
                "规划没有完成", "未完成", "失败",
            )
        )
        if missing_input:
            return (
                "规划所需的 CT/靶区/剂量数据尚未加载完成，系统没有改动当前规划。"
                "这通常是病例资源仍在加载；请等待加载完成后重试。"
                if language == "zh" else
                "The CT/target/dose data required for this operation is not loaded yet, "
                "so the current plan was not modified. This is usually case resource loading; "
                "wait for it to finish and retry."
            )
        # A dose/mask grid mismatch is a data-consistency condition.  It says
        # nothing about whether planning completed: the case may be fully
        # planned while two workspace arrays simply live on different grids.
        grid_mismatch = any(
            marker in lower
            for marker in (
                "grids do not match", "grid mismatch", "shape must match",
                "shape mismatch", "must be a 3d", "broadcast", "dimension",
            )
        )
        if grid_mismatch:
            return (
                "剂量与靶区/危及器官数据不在同一体格网格上，本次评估无法进行；"
                "系统没有改动当前规划。请先在当前网格上重算剂量后再试。"
                if language == "zh" else
                "The dose and target/OAR data are not on the same spatial grid, so this "
                "assessment could not run; the current plan was not modified. Recompute "
                "the dose on the current grid and retry."
            )
        if tool == "dose_evaluation":
            # dose_evaluation is a post-planning quality assessment.  Its
            # failure is never evidence that planning did not complete.
            return (
                "剂量评估未能完成。这是对现有规划的质量评估，与规划是否完成无关；"
                "系统没有改动当前规划。请查看执行追踪中的失败原因后重试。"
                if language == "zh" else
                "Dose evaluation did not complete. This is a quality assessment of the "
                "existing plan and says nothing about planning completion; the current "
                "plan was not modified. Check the failure reason in the Execution Trace "
                "and retry."
            )
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


def sanitize_user_response(
    response: Any,
    *,
    lang: str = "en",
    tool_name: str = "",
    roots: Any = None,
) -> str:
    """Last response-boundary guard against raw exceptions/provider payloads.

    ``roots`` optionally carries the path tokens for the active case, so a
    quoted server path is presented as ``<workspace>/…`` instead of the
    basename-only fallback.
    """
    text = str(response or "").strip()
    if not text:
        return text
    if is_provider_error(text):
        return format_tool_error(tool_name or "request", text, {}, lang)
    if roots is not None:
        text = relativize_text(text, roots)
    redacted = redact_internal_paths(text, lang=lang)
    if is_internal_error(redacted):
        return format_tool_error(tool_name or "request", text, {}, lang)
    return redacted
