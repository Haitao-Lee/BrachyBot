"""Low-cost turn classification and execution policy.

This module is deliberately conservative.  It may bypass an expensive router
only for deterministic, low-risk requests.  Clinical execution and evidence
based medical advice keep the normal routing and review gates.
"""

from dataclasses import dataclass
import re
from typing import FrozenSet, Iterable, Optional


KNOWLEDGE_TOOLS: FrozenSet[str] = frozenset({
    "clinical_kb", "web_search", "web_fetch", "web_access",
    "ctv_model_catalog", "doc_reader",
})

UI_TOOLS: FrozenSet[str] = frozenset({
    "ui_controller", "ui_inspector", "ui_screenshot", "ui_content", "ui_annotate",
    "viewer_command", "auto_navigate", "query_metrics", "dvh_curve",
})

CLINICAL_TOOLS: FrozenSet[str] = frozenset({
    "ctv_model_catalog", "ctv_segmentation", "oar_segmentation",
    "biomedparse_segmentation",
    "trajectory_init", "trajectory_refine", "trajectory_planning",
    "seed_planning", "seed_planning_rule_based", "seed_planning_rl",
    "dose_engine", "dose_evaluation", "planning_pipeline",
    "surgical_guide",
    "clinical_kb", "safety_validator", "plan_quality_scorer",
    "oar_constraint_checker", "plan_refinement", "report_auto_fill",
    "report_generator", "query_metrics", "ui_screenshot", "ui_content",
})


@dataclass(frozen=True)
class LocalTurnPolicy:
    """Execution choices made before any remote model call."""

    intent: str
    complexity: str
    requires_review: bool
    use_router: bool
    use_completeness: bool
    allow_tools: Optional[FrozenSet[str]] = None


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text or ""))


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    lowered = (text or "").lower()
    return any(phrase.lower() in lowered for phrase in phrases)


def _is_interrogative(message: str) -> bool:
    """Return True when the message reads like a question, not a command.

    A question asks for information; a command asks for action.  The
    distinction drives whether to auto-execute tools (command) or route
    through the LLM for a plain-text answer (question).
    """
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    if re.search(r"[?？吗呢]$", text.rstrip('!！')):
        return True
    if re.search(
        r'(?:是不是|有没有|能不能|可不可以|是否|怎么样|如何|怎么|'
        r'完成.*[了没]|做了[没吗]|好了[没吗]|分割.*[了没]|规划.*[了没])',
        lower,
    ):
        return True
    if re.search(
        r'\b(?:what|how|is it|are (?:you|there)|can (?:you|i)|'
        r'could|would|should|has (?:it|the)|have (?:you|they)|'
        r'did (?:you|it)|does (?:it|the))\b',
        lower,
    ):
        return True
    # Negation + passive inspection = "don't do anything, just check"
    if re.search(r'(?:不要|别|不准|不许)', lower) and re.search(
        r'(?:查看|看看|检查|确认|告诉)', lower,
    ):
        return True
    return False


def _is_current_case_dose_query(message: str) -> bool:
    """Identify a request for already-computed dose results in this case.

    A question such as ``current case dose distribution`` asks us to read the
    active workspace. It is not a dose recalculation command and it is not a
    request for external clinical standards.
    """
    text = str(message or "").strip().lower()
    if not text:
        return False
    dose_terms = (
        "dose", "dvh", "d90", "d95", "d2", "v100", "v150", "v200",
        "\u5242\u91cf", "\u5242\u91cf\u5206\u5e03", "\u5242\u91cf\u7ed3\u679c",
    )
    standards_terms = (
        "guideline", "standard", "constraint", "limit", "tolerance",
        "recommendation", "prescription", "\u6307\u5357", "\u6807\u51c6",
        "\u9650\u503c", "\u8010\u53d7", "\u53c2\u8003", "\u5904\u65b9",
    )
    action_terms = (
        "calculate", "recalculate", "recompute", "evaluate dose",
        "dose evaluation", "\u8ba1\u7b97", "\u91cd\u65b0\u8ba1\u7b97",
        "\u91cd\u65b0\u8bc4\u4f30", "\u91cd\u65b0\u89c4\u5212",
    )
    current_terms = (
        "current", "currently", "this case", "active case", "now",
        "\u5f53\u524d", "\u73b0\u5728", "\u672c\u4f8b", "\u672c\u75c5\u4f8b",
        "\u5f53\u524d\u6848\u4f8b", "\u5f53\u524d\u75c5\u4f8b",
    )
    question_terms = (
        "how", "what", "\u600e\u4e48\u6837", "\u5982\u4f55", "\u600e\u4e48",
        "\u60c5\u51b5", "\u7ed3\u679c", "\u770b\u770b", "\u600e\u4e48\u4e86",
    )
    has_dose = any(term in text for term in dose_terms)
    asks_for_current_state = any(term in text for term in current_terms) or any(
        term in text for term in question_terms
    ) or "?" in text or "\uff1f" in text
    return (
        has_dose
        and asks_for_current_state
        and not any(term in text for term in standards_terms)
        and not any(term in text for term in action_terms)
    )


def _is_current_image_metadata_query(message: str) -> bool:
    """Identify a request for technical metadata of the loaded image.

    This is intentionally narrower than a generic image-analysis request. It
    only handles requests that ask about the uploaded/current image itself,
    such as dimensions, spacing, origin, direction, or voxel values. Clinical
    interpretation and segmentation continue through the normal guarded path.
    """
    text = str(message or "").strip().lower()
    if not text:
        return False
    image_terms = (
        "ct", "image", "uploaded image", "scan", "nifti", "nii",
        "\u56fe\u50cf", "\u5f71\u50cf", "\u4e0a\u4f20", "\u533b\u5b66\u5f71\u50cf",
    )
    detail_terms = (
        "metadata", "details", "information", "technical", "dimensions",
        "spacing", "voxel", "origin", "direction", "pixel", "header",
        "\u8be6\u7ec6\u4fe1\u606f", "\u5143\u6570\u636e", "\u6280\u672f\u4fe1\u606f",
        "\u5c3a\u5bf8", "\u4f53\u7d20", "\u4f53\u7d20\u95f4\u8ddd", "\u539f\u70b9", "\u65b9\u5411",
        "\u67e5\u770b\u56fe\u50cf", "\u67e5\u770b\u5f71\u50cf",
    )
    analysis_terms = (
        "analyze the uploaded image", "analyze this image",
        "\u5206\u6790\u4e00\u4e0b\u6211\u4e0a\u4f20\u7684\u56fe\u50cf",
        "\u5206\u6790\u4e0a\u4f20\u7684\u56fe\u50cf",
    )
    return (
        (any(term in text for term in image_terms) and any(term in text for term in detail_terms))
        or any(term in text for term in analysis_terms)
    )


def resolve_session_content_target(message: str) -> Optional[str]:
    """Resolve a read-only request for persisted current-Session content.

    This is a capability resolver, not a list of chatbot replies. It maps a
    request to a stable data family that the browser can read from the active
    Session without assuming the relevant panel is currently mounted. A fresh
    Viewer capture remains a ui_screenshot request.
    """
    text = str(message or "").strip().lower()
    if not text:
        return None

    report_terms = ("report", "\u62a5\u544a")
    figure_terms = (
        "figure", "fig", "screenshot", "image", "images", "picture", "figures",
        "\u622a\u56fe", "\u622a\u5c4f", "\u56fe\u7247", "\u56fe\u50cf", "\u56fe\u4ef6",
    )
    if any(term in text for term in report_terms):
        return "report_figures" if any(term in text for term in figure_terms) else "report"
    # A fresh capture is a different capability from reading Session-owned
    # content. Keep it on the live ui_screenshot path unless the user
    # explicitly asks for a previously saved image collection.
    live_capture_terms = ("screenshot", "capture", "\u622a\u56fe", "\u622a\u5c4f")
    saved_terms = ("saved", "previous", "history", "\u5df2\u4fdd\u5b58", "\u5386\u53f2")
    if any(term in text for term in live_capture_terms) and not any(term in text for term in saved_terms):
        return None
    presentation_terms = (
        "show", "view", "open", "display", "look", "see", "check",
        "\u67e5\u770b", "\u770b\u770b", "\u663e\u793a", "\u6253\u5f00", "\u5c55\u793a", "\u5448\u73b0",
    )
    if not any(term in text for term in presentation_terms):
        return None
    if any(term in text for term in ("data tree", "\u6570\u636e\u6811")):
        return "data_tree"
    if any(term in text for term in ("surgical guide", "puncture guide", "guide mesh", "\u624b\u672f\u5bfc\u677f", "\u7a7f\u523a\u5bfc\u677f")):
        return "surgical_guide"
    if any(term in text for term in ("chat history", "conversation history", "execution trace", "\u5bf9\u8bdd\u5386\u53f2", "\u6267\u884c\u8ffd\u8e2a")):
        return "chat_history"
    if any(term in text for term in ("all screenshots", "saved screenshots", "session screenshots", "\u6240\u6709\u622a\u56fe", "\u5df2\u4fdd\u5b58\u7684\u622a\u56fe")):
        return "session_screenshots"
    if any(term in text for term in ("structure", "structures", "segmentation", "mask", "ctv", "oar", "\u7ed3\u6784", "\u5206\u5272", "\u63a9\u819c", "\u9762\u5177")):
        return "structures"
    # Preserve the requested resource family.  The browser uses this stable
    # target to read the corresponding persisted result rather than treating
    # DVH or metrics as a generic screenshot request.
    if any(term in text for term in ("dvh", "dose-volume histogram", "\u5242\u91cf\u4f53\u79ef\u76f4\u65b9\u56fe")):
        return "dvh"
    if any(term in text for term in ("metric", "metrics", "\u6307\u6807")):
        return "metrics"
    if any(term in text for term in ("dose", "\u5242\u91cf")):
        return "dose"
    if any(term in text for term in ("planning", "needles", "seeds", "\u89c4\u5212", "\u7a7f\u523a\u9488", "\u7c92\u5b50")):
        return "planning"
    if any(term in text for term in ("ct", "image", "scan", "\u5f71\u50cf", "\u56fe\u50cf")):
        return "ct"
    if any(term in text for term in ("session", "case", "workspace", "\u672c\u75c5\u4f8b", "\u5f53\u524d\u4f1a\u8bdd", "\u5f53\u524d\u6848\u4f8b", "\u5168\u90e8\u5185\u5bb9")):
        return "session_summary"
    return None


def classify_local_turn(message: str, pending_tumor_site: bool = False) -> LocalTurnPolicy:
    """Classify a turn without an LLM, using conservative intent boundaries."""
    text = str(message or "").strip()
    lower = text.lower()
    small_talk = {
        "你好", "您好", "嗨", "哈喽", "早上好", "下午好", "晚上好",
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "谢谢", "感谢", "thanks", "thank you",
    }
    if re.sub(r"\s+", " ", lower).strip("!?.,，。！？ ") in small_talk or re.search(
        r"(?:介绍自己|你是谁|你能做什么|你可以做什么|使用说明)|"
        r"\b(?:introduce yourself|who are you|what can you do|how do i use)\b",
        lower,
    ):
        # The classifier only removes the remote router/tool overhead. The
        # answer itself is still generated by the configured LLM.
        return LocalTurnPolicy("small_talk", "low", False, False, False, frozenset())

    # Technical image metadata is a local read-only workspace query. Do this
    # before the interrogative branch so it cannot drift into doc_reader or a
    # knowledge search that returns only a generic completion message.
    if _is_current_image_metadata_query(text):
        return LocalTurnPolicy(
            "image_metadata_query",
            "low",
            False,
            False,
            False,
            frozenset(),
        )

    # A request to view a persisted Session artifact is not a new screenshot,
    # a viewer mutation, or a knowledge lookup. Keep it out of the expensive
    # router and let the Session-content bridge resolve real stored data.
    if resolve_session_content_target(text):
        return LocalTurnPolicy(
            "session_content_query",
            "low",
            False,
            False,
            False,
            frozenset(),
        )

    # Current dose questions are local workspace reads. They must be handled
    # before the generic interrogative/clinical-knowledge branches so a
    # completed plan is not sent to clinical_kb or web_fetch. Explicit
    # "show/view" requests above use ui_content; analytical questions such
    # as "how is the current dose" retain the richer existing dose response.
    if _is_current_case_dose_query(text):
        return LocalTurnPolicy(
            "case_dose_query",
            "low",
            False,
            False,
            False,
            frozenset(),
        )

    # A question about clinical data is not a clinical action command.
    # Route interrogative turns through the LLM so it can read the current
    # status from memory instead of auto-executing a segmentation tool.
    if _is_interrogative(text):
        return LocalTurnPolicy("knowledge_query", "low", False, False, False, KNOWLEDGE_TOOLS)

    external = _contains_any(lower, (
        "deeprare", "github", "gitlab", "repository", "repo", "source code",
        "外部项目", "项目代码", "开源代码",
    ))
    # Segmentation is an execution request, not a generic knowledge query.
    # Keep the Chinese aliases as Unicode escapes because this module must
    # remain ASCII-safe even when deployed with a non-UTF-8 locale.
    segmentation = _contains_any(lower, (
        "ctv", "oar segmentation", "segment ctv", "segment oar", "segmentation",
        "segment", "delineate", "outline", "extract", "\u52fe\u753b", "\u52fe\u52d2", "\u63d0\u53d6",
        "\u5206\u5272", "\u6267\u884cctv\u5206\u5272", "\u6267\u884coar\u5206\u5272",
        "\u9776\u533a", "\u5371\u53ca\u5668\u5b98", "\u80bf\u7624\u90e8\u4f4d",
    ))
    # A site-only follow-up is actionable only after the agent explicitly
    # asked for the tumor site. This prevents a bare site name in a new case
    # from silently starting a clinical workflow.
    if pending_tumor_site and _contains_any(lower, (
        "pancreas", "pancreatic", "liver", "kidney", "lung", "colon", "prostate",
        "\u80f0\u817a", "\u809d", "\u80be", "\u80ba", "\u7ed3\u80a0", "\u524d\u5217\u817a",
    )):
        segmentation = True
    planning = _contains_any(lower, (
        "执行规划", "开始规划", "重新规划", "粒子植入规划", "治疗计划",
        "\u6267\u884c\u653e\u5c04\u6027\u7c92\u5b50\u690d\u5165\u89c4\u5212",
        "\u653e\u5c04\u6027\u7c92\u5b50\u690d\u5165\u89c4\u5212",
        "planning_pipeline", "brachytherapy plan", "treatment plan", "replan",
    ))
    clinical_advice = _contains_any(lower, (
        "临床", "指南", "处方剂量", "oar", "d90", "v100", "v150", "v200",
        "剂量限值", "治疗适应证", "clinical", "guideline", "prescription dose",
    ))
    ui = _contains_any(lower, (
        "viewer", "切片", "窗口", "放大", "缩小", "显示", "隐藏", "透明度",
        "颜色", "截图", "调节", "设置", "切换", "拖拽", "3d", "2d",
        "viewer", "slice", "zoom", "show", "hide", "opacity", "screenshot",
        "set", "adjust", "toggle", "drag",
        # Monitor/training-mode control is a UI command (start/stop live
        # planning monitoring), not a clinical execution or knowledge query.
        # Without these keywords a request like "请停止monitor" fell through
        # to the generic knowledge_query intent, whose tool set excludes
        # ui_controller, so the LLM answered "no monitor is running" instead
        # of actually stopping it.
        "monitor", "training mode", "start monitoring", "stop monitoring",
        "停止监测", "开始监测", "结束监测", "停止监控", "监测",
    ))
    if planning:
        # A full planning request has an unambiguous local execution path
        # (CTV/OAR -> planning pipeline).  Sending it through the remote
        # multi-agent router first adds a second LLM round-trip of tens of
        # seconds without improving the safety gates: review and completeness
        # checks still run after the actual plan is produced.
        return LocalTurnPolicy("clinical_planning", "high", True, False, True, CLINICAL_TOOLS)
    if segmentation:
        return LocalTurnPolicy("segmentation", "medium", True, False, True, CLINICAL_TOOLS)
    if external:
        return LocalTurnPolicy("external_project_query", "low", True, True, True, frozenset({"web_search", "web_fetch", "web_access"}))
    if clinical_advice:
        return LocalTurnPolicy("clinical_knowledge", "medium", True, True, True, KNOWLEDGE_TOOLS)
    if ui:
        return LocalTurnPolicy("ui_control", "low", False, False, False, UI_TOOLS)
    return LocalTurnPolicy("knowledge_query", "low", False, False, False, KNOWLEDGE_TOOLS)


def filter_tool_schemas(tools, policy: Optional[LocalTurnPolicy]):
    """Keep only tools permitted by the local policy and current registry."""
    if not policy or policy.allow_tools is None:
        return tools
    allowed = policy.allow_tools
    return [
        item for item in (tools or [])
        if item.get("function", {}).get("name") in allowed
    ]
