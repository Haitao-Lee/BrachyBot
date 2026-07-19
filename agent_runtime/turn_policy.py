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
    "ui_controller", "ui_inspector", "ui_screenshot", "ui_annotate",
    "viewer_command", "auto_navigate", "query_metrics", "dvh_curve",
})

CLINICAL_TOOLS: FrozenSet[str] = frozenset({
    "ctv_model_catalog", "ctv_segmentation", "oar_segmentation",
    "trajectory_init", "trajectory_refine", "trajectory_planning",
    "seed_planning", "seed_planning_rule_based", "seed_planning_rl",
    "dose_engine", "dose_evaluation", "planning_pipeline",
    "clinical_kb", "safety_validator", "plan_quality_scorer",
    "oar_constraint_checker", "plan_refinement", "report_auto_fill",
    "report_generator", "query_metrics", "ui_screenshot",
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
    fast_response: Optional[str] = None


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text or ""))


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    lowered = (text or "").lower()
    return any(phrase.lower() in lowered for phrase in phrases)


def _fast_response(message: str) -> Optional[str]:
    """Return a deterministic answer only for harmless, bounded requests."""
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if len(text) > 48:
        return None
    lower = text.lower().strip("!?.,，。！？ ")
    greetings = {
        "你好", "您好", "嗨", "哈喽", "早上好", "下午好", "晚上好",
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    }
    thanks = {"谢谢", "感谢", "thanks", "thank you"}
    if lower in greetings:
        return "你好！我是 BrachyBot，可以协助 CT 分割、近距离放疗计划分析、剂量评估和临床知识检索。涉及患者治疗的结果都需要专业医生和物理师审核。" if _has_cjk(text) else (
            "Hello! I am BrachyBot. I can assist with CT segmentation, brachytherapy planning, dose evaluation, and evidence-based clinical lookup. Patient-specific results still require review by qualified clinicians and physicists."
        )
    if lower in thanks:
        return "不客气！" if _has_cjk(text) else "You are welcome!"
    if re.search(r"(?:介绍自己|你是谁|你能做什么|你可以做什么|使用说明)", text) or re.search(
        r"\b(?:introduce yourself|who are you|what can you do|how do i use)\b", lower
    ):
        return (
            "我是 BrachyBot，面向近距离放疗工作流的 AI 助手。"
            "我可以协助 CT/CTV/OAR 分割、针道与粒子计划、剂量/DVH 分析、可视化操作和循证知识检索。"
            "临床计划仅供辅助，必须由合格的放疗医生和医学物理师审核。"
            if _has_cjk(text) else
            "I am BrachyBot, an AI assistant for brachytherapy workflows. "
            "I can assist with CT/CTV/OAR segmentation, needle and seed planning, dose/DVH analysis, UI visualization, and evidence lookup. "
            "Every clinical plan is advisory and must be reviewed by qualified clinicians and medical physicists."
        )
    return None


def classify_local_turn(message: str) -> LocalTurnPolicy:
    """Classify a turn without an LLM, using conservative intent boundaries."""
    text = str(message or "").strip()
    lower = text.lower()
    fast = _fast_response(text)
    if fast is not None:
        return LocalTurnPolicy("local_fast_path", "low", False, False, False, fast_response=fast)

    external = _contains_any(lower, (
        "deeprare", "github", "gitlab", "repository", "repo", "source code",
        "外部项目", "项目代码", "开源代码",
    ))
    planning = _contains_any(lower, (
        "执行规划", "开始规划", "重新规划", "粒子植入规划", "治疗计划",
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
    ))
    if planning:
        return LocalTurnPolicy("clinical_planning", "high", True, True, True, CLINICAL_TOOLS)
    if external:
        return LocalTurnPolicy("external_project_query", "low", True, True, True, frozenset({"web_search", "web_fetch", "web_access"}))
    if clinical_advice:
        return LocalTurnPolicy("clinical_knowledge", "medium", True, True, True, KNOWLEDGE_TOOLS)
    if ui:
        return LocalTurnPolicy("ui_control", "low", False, False, False, UI_TOOLS)
    return LocalTurnPolicy("knowledge_query", "low", False, False, False, KNOWLEDGE_TOOLS)


def filter_tool_schemas(tools, policy: Optional[LocalTurnPolicy]):
    """Keep only tools permitted by the local policy and current registry."""
    if not policy or not policy.allow_tools:
        return tools
    allowed = policy.allow_tools
    return [
        item for item in (tools or [])
        if item.get("function", {}).get("name") in allowed
    ]
