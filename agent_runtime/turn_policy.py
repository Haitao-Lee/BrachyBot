"""Low-cost turn classification and execution policy.

This module is deliberately conservative.  It may bypass an expensive router
only for deterministic, low-risk requests.  Clinical execution and evidence
based medical advice keep the normal routing and review gates.
"""

from dataclasses import dataclass, field
import re
from typing import FrozenSet, Iterable, Optional

from agent_runtime.action_plan import ActionPlan


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
    "dose_engine", "dose_recompute", "dose_evaluation", "planning_pipeline",
    "surgical_guide",
    "clinical_kb", "safety_validator", "plan_quality_scorer",
    "oar_constraint_checker", "plan_refinement", "report_auto_fill",
    "report_generator", "query_metrics", "ui_screenshot", "ui_content",
})

# Ambiguous, constrained, or mixed requests go through the configured LLM's
# existing function-calling turn rather than a second router call.  This union
# keeps all established BrachyBot capabilities available while the registry,
# tool schemas, Session state, and backend validators remain the hard safety
# boundary.
SEMANTIC_TOOLS: FrozenSet[str] = frozenset(
    set(KNOWLEDGE_TOOLS)
    | set(UI_TOOLS)
    | set(CLINICAL_TOOLS)
    | {"case_memory", "plan_comparator", "safety_validator"}
)


@dataclass(frozen=True)
class LocalTurnPolicy:
    """Low-cost routing hints and explicit fast-path grants.

    ``intent`` and ``allow_tools`` are advisory routing hints.  Mutating work
    is authorized only through ``execution_grants``/``workflow_grants`` or an
    explicit tool call selected by the LLM during this turn.
    """

    intent: str
    complexity: str
    requires_review: bool
    use_router: bool
    use_completeness: bool
    allow_tools: Optional[FrozenSet[str]] = None
    direct_execution: bool = False
    execution_grants: FrozenSet[str] = field(default_factory=frozenset)
    workflow_grants: FrozenSet[str] = field(default_factory=frozenset)
    action_plan: Optional[ActionPlan] = None


def visual_analysis_policy() -> LocalTurnPolicy:
    """Return the execution policy for a hidden screenshot-analysis child.

    A visual follow-up is not a second user turn. Its prompt contains the
    parent request plus uploaded image evidence, which can resemble an
    ordinary content-navigation request when classified as plain text. Give
    it a distinct role instead: the LLM remains responsible for interpreting
    the supplied evidence, while the runtime applies its separate read-only
    provider-tool boundary.
    """
    return LocalTurnPolicy(
        intent="visual_analysis",
        complexity="medium",
        requires_review=False,
        use_router=False,
        use_completeness=False,
        # Do not text-whitelist the model's reasoning tools here. The
        # runtime's typed visual-child boundary restricts provider schemas to
        # safe read-only case data after normal Session/CT safety filtering.
        allow_tools=None,
    )


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text or ""))


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    lowered = (text or "").lower()
    return any(phrase.lower() in lowered for phrase in phrases)


def _looks_like_compound_action(message: str) -> bool:
    """Detect sentence structure that may contain more than one operation.

    This is only a fast-path boundary. It does not choose a tool or a
    workflow; compound requests are sent to the LLM so it can build the plan.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if re.search(
        r"(?:\u7136\u540e|\u4e4b\u540e|\u4e4b\u524d|\u5148|\u518d|\u540c\u65f6|\u4ee5\u53ca|\u5e76(?:\u4e14)?|\u5b8c\u6210\u540e|"
        r"\b(?:then|after|before|and then|followed by|as well as|also|next)\b)",
        text,
        flags=re.IGNORECASE,
    ):
        return True

    # Users often separate imperative clauses with punctuation and omit a
    # connective: "rerun planning, generate a new guide". Detect that
    # sentence structure only when both sides contain an action head; this is
    # deliberately a routing boundary, not a tool or intent classifier.
    action_head = (
        r"(?:\u6267\u884c|\u8fdb\u884c|\u5f00\u59cb|\u89c4\u5212|\u8ba1\u5212|\u751f\u6210|\u5206\u5272|\u663e\u793a|\u67e5\u770b|\u5bfc\u51fa|"
        r"\u66f4\u65b0|\u91cd\u5efa|\u8ba1\u7b97|\u8c03\u7528|\u505c\u6b62|\u6253\u5f00|\u5207\u6362|\u5220\u9664|\u79fb\u52a8|\u6dfb\u52a0|"
        r"run|rerun|replan|plan(?:ning)?|execute|perform|generate|segment|show|view|export|update|rebuild|calculate|call|stop|open|switch|delete|move|add)"
    )
    clauses = re.split(r"[,;\uFF0C\uFF1B]", text)
    if len(clauses) > 1:
        return any(
            re.search(action_head, clause, flags=re.IGNORECASE)
            for clause in clauses[:-1]
        ) and any(
            re.search(action_head, clause, flags=re.IGNORECASE)
            for clause in clauses[1:]
        )
    return False


def _has_explicit_planning_action(message: str) -> bool:
    """Recognize an explicit planning operation for dependency enforcement."""
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    planning = r"(?:\u89c4\u5212|\u8ba1\u5212|planning(?:\s+pipeline)?|treatment\s+plan|brachytherapy\s+plan)"
    action = r"(?:\u6267\u884c|\u8fdb\u884c|\u5f00\u59cb|\u91cd\u65b0|\u91cd\u505a|\u91cd\u8dd1|\u8c03\u6574|\u66f4\u65b0|execute|run|start|rerun|replan|perform|update)"
    return bool(re.search(
        rf"(?:{action}).{{0,18}}(?:{planning})|(?:{planning}).{{0,12}}(?:{action})",
        text,
        flags=re.IGNORECASE,
    ))


def is_planning_reexecution_request(message: str) -> bool:
    """Return true only for an explicit request to replace an existing plan."""
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    explicit = bool(re.search(
        r"(?:\u91cd\u65b0|\u518d\u6b21|\u518d|\u91cd\u505a|\u91cd\u8dd1|\u91cd\u65b0\u6267\u884c).{0,12}(?:\u89c4\u5212|\u8ba1\u5212)|"
        r"\b(?:replan|re-plan|rerun(?: the)? plan|rerun planning)\b",
        text,
        flags=re.IGNORECASE,
    ))
    changed_then_plan = bool(re.search(
        r"(?:\u6539|\u4fee\u6539|\u8c03\u6574|\u53d8\u66f4|\u66f4\u65b0|changed?|modified?|adjusted?).{0,28}"
        r"(?:\u53c2\u6570|\u8bbe\u7f6e|\u7c92\u5b50|\u9488\u9053|parameters?|settings?).{0,24}"
        r"(?:\u91cd\u65b0|\u518d\u6b21|\u518d|\u6267\u884c|\u8fd0\u884c|rerun|replan|run).{0,12}"
        r"(?:\u89c4\u5212|\u8ba1\u5212|plan(?:ning)?)",
        text,
        flags=re.IGNORECASE,
    ))
    return explicit or changed_then_plan


def requires_planning_before_guide(message: str) -> bool:
    """Return true when a guide request explicitly includes a planning step."""
    return bool(
        is_surgical_guide_generation_request(message)
        and (
            is_planning_reexecution_request(message)
            or (_looks_like_compound_action(message) and _has_explicit_planning_action(message))
        )
    )


def _planning_and_guide_plan() -> ActionPlan:
    """Build the only routing-level plan that is a hard business dependency."""
    return ActionPlan.from_tools(
        ("ctv_segmentation", "oar_segmentation", "planning_pipeline", "surgical_guide"),
        source="semantic_dependency_guard",
        dependencies={
            "planning_pipeline": ("ctv_segmentation", "oar_segmentation"),
            "surgical_guide": ("planning_pipeline",),
        },
    )


def _planning_only_plan() -> ActionPlan:
    """Build the ordered plan for an explicit re-planning request.

    Existing masks are reusable prerequisites.  The planning pipeline is not:
    a re-plan must create a new planning revision even when CTV/OAR are already
    present in memory.  Keeping this dependency in the turn plan prevents a
    later guide-only shortcut from silently consuming the request.
    """
    return ActionPlan.from_tools(
        ("ctv_segmentation", "oar_segmentation", "planning_pipeline"),
        source="semantic_replan_dependency_guard",
        dependencies={
            "planning_pipeline": ("ctv_segmentation", "oar_segmentation"),
        },
    )


def _requires_semantic_resolution(message: str) -> bool:
    """Return whether an action request needs real language understanding.

    This is a conservative fast-path boundary, not another intent classifier.
    Simple positive imperatives retain the existing low-latency route.  Any
    negation, exclusion, condition, correction, sequencing constraint, or
    diagnostic framing is delegated to the configured LLM with the full
    relevant capability set.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    semantic_markers = (
        # Negation and exclusion.
        "\u4e0d\u8981", "\u522b", "\u4e0d\u9700\u8981", "\u65e0\u9700", "\u4e0d\u7528",
        "\u4e0d\u662f", "\u5e76\u975e", "\u4e0d\u5fc5", "\u4e0d\u53ef\u4ee5", "\u4e0d\u80fd",
        "\u6ca1\u6709", "\u53d6\u6d88", "\u5207\u52ff", "\u7981\u6b62", "\u4e0d\u5141\u8bb8",
        "\u4e0d\u6267\u884c", "\u9664\u4e86", "\u9664\u5916",
        "do not", "don't", "dont", "not ", "without", "except", "exclude",
        # Mixed goals, sequencing, and conditions.
        "\u53ea", "\u4ec5", "\u4f46", "\u4f46\u662f", "\u7136\u540e", "\u4e4b\u540e", "\u4e4b\u524d",
        "\u5148", "\u518d", "\u7b49\u6211", "\u6682\u65f6", "\u9664\u975e", "\u5982\u679c",
        "only", "but", "instead", "rather than", "after", "before", "unless", "if ",
        # Corrections and diagnostics should never be mistaken for permission
        # to repeat the operation being discussed.
        "\u6211\u662f\u8bf4", "\u6211\u7684\u610f\u601d", "\u8bf4\u9519", "\u6539\u4e3a", "\u539f\u56e0",
        "\u4e3a\u4ec0\u4e48", "\u62a5\u9519", "\u5931\u8d25", "i mean", "correction", "why", "failed", "error",
        # Interpretation and synthesis need the primary LLM to decide how
        # evidence should be selected and explained. These are discourse
        # markers, not a map from phrase to a particular clinical tool.
        "\u5206\u6790", "\u89e3\u8bfb", "\u89e3\u91ca", "\u8bf4\u660e", "\u63cf\u8ff0", "\u4ecb\u7ecd",
        "\u8bc4\u4f30", "\u8bc4\u4ef7", "\u5224\u65ad", "\u6bd4\u8f83", "\u5bf9\u6bd4", "\u6709\u4ec0\u4e48\u95ee\u9898",
        "analyze", "analyse", "interpret", "explain", "describe", "assess", "evaluate", "compare", "findings",
    )
    return any(marker in text for marker in semantic_markers)


def _semantic_action_policy(
    *,
    complexity: str = "medium",
    review: bool = True,
    action_plan: Optional[ActionPlan] = None,
) -> LocalTurnPolicy:
    """Use the main LLM once for semantic action selection, not a second router."""
    execution_grants = frozenset()
    workflow_grants = frozenset()
    if action_plan is not None:
        execution_grants = frozenset(action_plan.tool_names)
        if action_plan.requires_tool("planning_pipeline"):
            workflow_grants = frozenset({"clinical_planning"})
    return LocalTurnPolicy(
        "semantic_action",
        complexity,
        review,
        False,
        review,
        SEMANTIC_TOOLS,
        execution_grants=execution_grants,
        workflow_grants=workflow_grants,
        action_plan=action_plan,
    )


def _is_canonical_execution_command(message: str, *, operation: str) -> bool:
    """Return whether a low-latency action shortcut is unquestionably safe.

    This helper never selects a business workflow on its own. It only decides
    whether a phrase already classified as planning/segmentation is canonical
    enough to bypass the main LLM. Anything less explicit falls back to
    semantic function calling.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text or _requires_semantic_resolution(text):
        return False

    common_english = bool(re.search(
        r"\b(?:run|execute|start|perform|create|generate|do|rerun|replan)\b",
        text,
        flags=re.IGNORECASE,
    ))
    common_chinese = bool(re.search(
        r"(?:\u8bf7|\u5e2e\u6211|\u73b0\u5728|\u7acb\u5373|\u9700\u8981)?"
        r"(?:\u6267\u884c|\u5f00\u59cb|\u8fdb\u884c|\u751f\u6210|\u5236\u5b9a|\u91cd\u505a|\u91cd\u8dd1)",
        text,
    ))
    if common_english or common_chinese:
        return True

    if operation == "segmentation":
        # A bare imperative such as "segment the liver" or "分割肝脏" is
        # itself explicit. Noun phrases such as "CTV segmentation method"
        # do not match these command-position forms.
        return bool(
            re.match(r"^(?:please\s+)?(?:segment|delineate|outline|extract)\b", text)
            or re.match(r"^(?:\u8bf7|\u5e2e\u6211|\u73b0\u5728)?(?:\u5206\u5272|\u52fe\u753b|\u52fe\u52d2|\u63d0\u53d6)", text)
        )
    if operation == "planning":
        return bool(
            re.match(r"^(?:please\s+)?plan\b", text)
            or re.match(r"^(?:\u8bf7|\u5e2e\u6211|\u73b0\u5728)?(?:\u89c4\u5212|\u5236\u5b9a)", text)
        )
    return False


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
    current_terms = (
        "current", "currently", "this case", "active case", "now",
        "\u5f53\u524d", "\u73b0\u5728", "\u672c\u4f8b", "\u672c\u75c5\u4f8b",
        "\u5f53\u524d\u6848\u4f8b", "\u5f53\u524d\u75c5\u4f8b",
    )
    question_terms = (
        "how", "what", "\u600e\u4e48\u6837", "\u5982\u4f55", "\u600e\u4e48",
        "\u60c5\u51b5", "\u7ed3\u679c", "\u770b\u770b", "\u600e\u4e48\u4e86",
        "\u591a\u5c11", "\u6307\u6807", "metrics", "values", "key metrics",
    )

    # Distinguish a mutating imperative from an attributive description such
    # as "当前计算的剂量结果".  Substring matching on "计算" incorrectly
    # turned a read into a re-calculation and sent it through the expensive
    # tool/LLM/review chain.  The mutation grammar requires an action frame
    # (request/command verb + dose object); calculated/computed result nouns
    # remain read-only.
    calculated_result_noun = bool(re.search(
        r"(?:计算|评估|计算得到|评估得到)(?:的|出来的|得到的)"
        r"(?:剂量|剂量分布|剂量结果|剂量指标|dose|dvh)",
        text,
        re.IGNORECASE,
    ))
    mutation_request = bool(re.search(
        r"(?:请|帮我|需要|执行|开始|进行|马上|现在|重新|再次|再)"
        r".{0,16}(?:计算|重算|评估|更新).{0,10}"
        r"(?:剂量|剂量分布|剂量结果|dvh|dose)"
        r"|(?:重新|再次|再).{0,8}(?:规划|计划)"
        r"|\b(?:please\s+)?(?:recalculate|recompute|calculate|update|run|evaluate)"
        r"\b.{0,24}\b(?:dose|dvh|dose metrics?)\b",
        text,
        re.IGNORECASE,
    ))
    has_dose = any(term in text for term in dose_terms)
    asks_for_current_state = any(term in text for term in current_terms) or any(
        term in text for term in question_terms
    ) or "?" in text or "\uff1f" in text
    return (
        has_dose
        and asks_for_current_state
        and not any(term in text for term in standards_terms)
        and not (mutation_request and not calculated_result_noun)
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


def _is_image_tumor_measurement_request(message: str) -> bool:
    """Recognize image-grounded tumor location/size analysis requests.

    These requests need a real segmentation result. They are different from
    general tumor knowledge questions because the user identifies an uploaded
    scan and asks for patient-specific location or size.
    """
    text = str(message or "").strip().lower()
    if not text:
        return False
    image_terms = (
        "ct", "image", "scan", "nifti", "uploaded", "patient",
        "\u56fe\u50cf", "\u5f71\u50cf", "\u4e0a\u4f20", "\u60a3\u8005",
    )
    tumor_terms = (
        "tumor", "tumour", "lesion", "cancer",
        "\u80bf\u7624", "\u80bf\u5757", "\u75c5\u7076", "\u764c",
    )
    request_terms = (
        "analy", "where", "location", "size", "volume", "large",
        "\u5206\u6790", "\u5728\u54ea", "\u4f4d\u7f6e", "\u591a\u5927", "\u4f53\u79ef",
    )
    site_terms = (
        "pancreas", "pancreatic", "liver", "kidney", "lung", "colon", "prostate",
        "\u80f0\u817a", "\u809d", "\u80be", "\u80ba", "\u7ed3\u80a0", "\u524d\u5217\u817a",
    )
    return (
        any(term in text for term in image_terms)
        and any(term in text for term in tumor_terms)
        and any(term in text for term in request_terms)
        and any(term in text for term in site_terms)
    )


def resolve_report_request_action(message: str) -> Optional[str]:
    """Resolve a report turn to one semantic operation.

    The operation and the presentation target are intentionally parsed
    separately.  In particular, a corrective request such as "regenerate the
    report, not screenshots" must remain a mutating report operation even
    though the rejected presentation target appears in the same sentence.
    This resolver is also used at the tool-normalization boundary, so an LLM
    tool choice cannot silently downgrade report generation to figure reading.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text or not _contains_any(text, ("report", "\u62a5\u544a")):
        return None

    # Remove explicitly rejected figure clauses before deciding whether the
    # user positively requested saved report figures. Keep the rest of the
    # sentence intact so the requested report operation still wins.
    positive_text = re.sub(
        r"(?:\u4e0d\u662f|\u4e0d\u8981|\u5e76\u975e|\u522b|\u65e0\u9700|\u4e0d\u9700\u8981)"
        r"[^,\uff0c;\uff1b.!\u3002]{0,24}(?:\u622a\u56fe|\u622a\u5c4f|\u56fe\u7247|\u56fe\u4ef6|\u56fe\u50cf)",
        " ",
        text,
    )
    positive_text = re.sub(
        r"(?:not|do not|don't|instead of|rather than)\s+"
        r"[^,;.!]{0,40}\b(?:screenshots?|figures?|images?|pictures?)\b",
        " ",
        positive_text,
        flags=re.IGNORECASE,
    )

    english_mutation = bool(re.search(
        r"\b(?:generate|regenerate|re-generate|rebuild|create|update|refresh|"
        r"rewrite|refill|auto-fill|autofill|fill|complete)\b",
        text,
    ))
    chinese_mutation = _contains_any(text, (
        "\u751f\u6210", "\u66f4\u65b0", "\u5237\u65b0", "\u91cd\u505a", "\u91cd\u5efa",
        "\u5236\u4f5c", "\u521b\u5efa", "\u586b\u5145", "\u8865\u5168", "\u5b8c\u5584",
    ))
    incomplete_report = bool(re.search(
        r"(?:\u6b63\u6587|\u6587\u5b57|\u8868\u683c|reference|status|content|text|table)"
        r"[^,\uff0c;\uff1b.!\u3002]{0,20}(?:\u7a7a|\u6ca1\u6709|\u6ca1\u586b|\u672a\u586b|\u7f3a\u5931|"
        r"empty|missing|not filled|unfilled|incomplete)",
        text,
        flags=re.IGNORECASE,
    ))
    if english_mutation or chinese_mutation or incomplete_report:
        return "regenerate"

    figure_terms = (
        "figure", "fig", "screenshot", "image", "images", "picture", "figures",
        "\u622a\u56fe", "\u622a\u5c4f", "\u56fe\u7247", "\u56fe\u50cf", "\u56fe\u4ef6",
    )
    return "view_figures" if _contains_any(positive_text, figure_terms) else "view"


def is_report_generation_request(message: str) -> bool:
    """Return whether a turn mutates the editable report."""
    return resolve_report_request_action(message) == "regenerate"


def is_surgical_guide_generation_request(message: str) -> bool:
    """Return whether the user explicitly asks to create or rebuild a guide.

    This is intentionally separate from the read-only Session-content resolver.
    A guide can be viewed, inspected, exported, or generated; only the last
    group is allowed to mutate the case and call the clinical guide tool.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    guide_terms = (
        "surgical guide", "puncture guide", "guide mesh", "guide stl",
        "\u624b\u672f\u5bfc\u677f", "\u7a7f\u523a\u5bfc\u677f", "\u624b\u672f\u5200\u677f", "\u5bfc\u677f",
    )
    if not any(term in text for term in guide_terms):
        return False

    # Match an explicit generation verb, not a passive status/error report.
    english_action = bool(re.search(
        r"\b(?:generate|regenerate|re-generate|rebuild|create|make|update|refresh)\b",
        text,
        flags=re.IGNORECASE,
    ))
    chinese_action = any(term in text for term in (
        "\u751f\u6210", "\u91cd\u65b0\u751f\u6210", "\u518d\u751f\u6210", "\u91cd\u5efa", "\u91cd\u505a",
        "\u66f4\u65b0", "\u5237\u65b0", "\u5236\u4f5c", "\u521b\u5efa",
    ))
    if not (english_action or chinese_action):
        return False

    # "guide generation failed" is a diagnostic question, not permission to
    # start another long-running operation. An imperative regeneration phrase
    # still wins when both appear in the same message.
    passive_failure = any(term in text for term in (
        "failed", "failure", "error", "\u5931\u8d25", "\u62a5\u9519", "\u539f\u56e0",
    ))
    imperative = bool(re.search(
        r"\b(?:please\s+)?(?:regenerate|re-generate|rebuild|create|generate|update|refresh)\b|"
        r"(?:^|[\s,;:])(?:\u8bf7|\u5e2e\u6211|\u9700\u8981|\u91cd\u65b0|\u518d\u6b21|\u518d|\u91cd\u505a|\u91cd\u5efa|\u751f\u6210|\u5236\u4f5c|\u521b\u5efa|\u66f4\u65b0|\u5237\u65b0)[^。.!?\uff01\uff1f]{0,24}(?:\u624b\u672f|\u7a7f\u523a)?\u5bfc\u677f",
        text,
        flags=re.IGNORECASE,
    ))
    return not passive_failure or imperative


def _references_prior_reply_attachments(message: str) -> bool:
    """Return whether a visual noun resolves to the conversational antecedent.

    This recognizes a discourse reference, not a report-specific command.  A
    phrase such as ``open the last screenshot`` has no stable report, Viewer,
    or Data Tree owner; when it carries a positional/deictic reference, its
    only unambiguous owner is the preceding visible assistant reply.  Explicit
    collection owners (for example, "last report figure") retain their own
    Session resource family.
    """
    text = str(message or "").strip().lower()
    if not text:
        return False
    attachment_terms = (
        "screenshot", "image", "picture", "figure", "attachment", "photo",
        "\u622a\u56fe", "\u56fe\u50cf", "\u56fe\u7247", "\u56fe", "\u9644\u4ef6", "\u9644\u56fe",
    )
    if not any(term in text for term in attachment_terms):
        return False

    explicit_reply_terms = (
        "previous reply", "previous response", "prior reply", "prior response",
        "above reply", "above response", "last reply", "last response",
        "earlier reply", "earlier response",
        "\u4e0a\u4e00\u6761\u56de\u590d", "\u4e0a\u6761\u56de\u590d", "\u524d\u4e00\u6761\u56de\u590d", "\u4e0a\u4e00\u8f6e\u56de\u590d",
        "\u4e0a\u4e00\u6761\u6d88\u606f", "\u524d\u9762\u7684\u56de\u590d", "\u4e0a\u9762\u7684\u56de\u590d", "\u521a\u624d\u7684\u56de\u590d",
    )
    if any(term in text for term in explicit_reply_terms):
        return True

    # An ordinal image reference without an explicit durable collection is a
    # deictic reference to the images just shown in the conversation.  Keep
    # report/session/history ownership explicit so "last report figure" and
    # "last saved Session screenshot" stay attached to their real collections.
    explicit_collection_terms = (
        "report", "session", "workspace", "saved", "history", "all screenshots",
        "\u62a5\u544a", "\u5f53\u524d\u4f1a\u8bdd", "\u5f53\u524d\u6848\u4f8b", "\u5de5\u4f5c\u533a", "\u5df2\u4fdd\u5b58", "\u5386\u53f2", "\u6240\u6709\u622a\u56fe",
    )
    if any(term in text for term in explicit_collection_terms):
        return False
    return bool(re.search(
        r"(?:\u6700\u540e|\u6700\u672b|\u7b2c\s*\d+|\u9996\u4e2a|\u7b2c\u4e00|\u8fd9\u5f20|\u90a3\u5f20|\u4e0a\u9762\u7684|\u524d\u9762\u7684|\u521a\u624d\u7684|"
        r"\b(?:last|latest|final|first|this|that|above|previous|prior|\d+(?:st|nd|rd|th))\b)",
        text,
        flags=re.IGNORECASE,
    ))


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

    # A report action must reach the report-generation workflow.  It is not a
    # read-only request for the previously persisted report or its figures.
    report_action = resolve_report_request_action(text)
    if report_action == "regenerate":
        return None

    # Resolve conversational attachment references before global report
    # families.  The browser owns the actual message/attachment association,
    # so this target preserves the source relationship instead of guessing from
    # a report filename or a currently mounted panel.
    if _references_prior_reply_attachments(text):
        return "reply_attachments"

    if report_action:
        return "report_figures" if report_action == "view_figures" else "report"
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
    # A Data Tree selection already carries a stable node/object identity in
    # the browser. Treat an explicit selected-node request as an artifact
    # presentation rather than asking the model to infer a display name.
    # This works for every real Data Tree leaf, including newly added types.
    selected_object_terms = (
        "selected item", "selected object", "selected node", "current selection",
        "this selected", "\u5f53\u524d\u9009\u4e2d", "\u9009\u4e2d\u7684", "\u8fd9\u4e2a\u8282\u70b9", "\u8be5\u8282\u70b9",
    )
    if any(term in text for term in selected_object_terms):
        return "artifact"
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


def resolve_session_content_presentation(message: str, target: Optional[str] = None) -> str:
    """Choose the least disruptive browser presentation for a content query.

    Reading saved figures belongs in the reply as attachments. A request that
    explicitly refers to the selected Data Tree item should additionally open
    the Viewer panel and focus that existing node; this is still read-only and
    never changes the object's visibility or planning data.
    """
    resolved_target = str(target or resolve_session_content_target(message) or "").lower()
    if resolved_target in {"report_figures", "session_screenshots", "reply_attachments"}:
        return "attachments"
    text = str(message or "").strip().lower()
    explicit_selected = any(term in text for term in (
        "selected item", "selected object", "selected node", "current selection",
        "this selected", "\u5f53\u524d\u9009\u4e2d", "\u9009\u4e2d\u7684", "\u8fd9\u4e2a\u8282\u70b9", "\u8be5\u8282\u70b9",
    ))
    return "open" if resolved_target == "artifact" and explicit_selected else "auto"


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

    # A re-plan is a mutating operation even when it is expressed as a short
    # correction or follow-up. Resolve it before the guide fast path so the
    # existing masks can be reused but the planning pipeline is mandatory.
    if requires_planning_before_guide(text):
        return _semantic_action_policy(
            complexity="high",
            review=True,
            action_plan=_planning_and_guide_plan(),
        )
    if is_planning_reexecution_request(text):
        return _semantic_action_policy(
            complexity="high",
            review=True,
            action_plan=_planning_only_plan(),
        )

    # Resolve compound requests before every read-only or operation-specific
    # shortcut. Otherwise a phrase such as "regenerate the report and show
    # its figures" could be consumed by the report branch before the model
    # sees the second action. The only routing-level dependency encoded here
    # is the safety-critical planning -> guide relationship; all other actions
    # are selected and ordered by the primary LLM.
    if _looks_like_compound_action(text):
        return _semantic_action_policy(
            complexity="high",
            review=True,
            action_plan=(
                _planning_and_guide_plan()
                if requires_planning_before_guide(text)
                else (_planning_only_plan() if is_planning_reexecution_request(text) else None)
            ),
        )

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

    # Patient-specific tumor location/size questions require a real CTV mask,
    # even though they are phrased as questions rather than commands.
    if _is_image_tumor_measurement_request(text):
        return _semantic_action_policy(complexity="medium", review=True)

    if is_report_generation_request(text):
        if _requires_semantic_resolution(text):
            return _semantic_action_policy(complexity="medium", review=False)
        return LocalTurnPolicy(
            "report_generation",
            "low",
            False,
            False,
            False,
            UI_TOOLS,
            direct_execution=True,
            execution_grants=frozenset({"ui_controller"}),
        )

    # Guide generation is a real case mutation and must never fall through to
    # knowledge_query, where the model may invent a code_executor workaround.
    if is_surgical_guide_generation_request(text):
        if requires_planning_before_guide(text):
            return _semantic_action_policy(
                complexity="high",
                review=True,
                action_plan=_planning_and_guide_plan(),
            )
        if _requires_semantic_resolution(text):
            return _semantic_action_policy(
                complexity="medium",
                review=True,
            )
        return LocalTurnPolicy(
            "surgical_guide_generation",
            "medium",
            True,
            False,
            True,
            CLINICAL_TOOLS,
            direct_execution=True,
            execution_grants=frozenset({"surgical_guide"}),
        )

    # A request to view a persisted Session artifact is not a new screenshot,
    # a viewer mutation, or a knowledge lookup. Keep it out of the expensive
    # router and let the Session-content bridge resolve real stored data.
    if resolve_session_content_target(text):
        if _requires_semantic_resolution(text):
            return _semantic_action_policy(complexity="medium", review=False)
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
    if _is_interrogative(text) and _contains_any(lower, (
        "segment", "segmentation", "planning", "treatment plan", "generate", "regenerate",
        "\u5206\u5272", "\u89c4\u5212", "\u8ba1\u5212", "\u751f\u6210", "\u91cd\u65b0\u751f\u6210",
        "\u5bfc\u677f", "\u62a5\u544a", "\u622a\u56fe",
    )):
        return _semantic_action_policy(complexity="medium", review=False)
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
        if not _is_canonical_execution_command(text, operation="planning"):
            return _semantic_action_policy(complexity="high", review=True)
        # A full planning request has an unambiguous local execution path
        # (CTV/OAR -> planning pipeline).  Sending it through the remote
        # multi-agent router first adds a second LLM round-trip of tens of
        # seconds without improving the safety gates: review and completeness
        # checks still run after the actual plan is produced.
        return LocalTurnPolicy(
            "clinical_planning",
            "high",
            True,
            False,
            True,
            CLINICAL_TOOLS,
            direct_execution=True,
            execution_grants=frozenset({
                "ctv_segmentation", "oar_segmentation", "planning_pipeline", "surgical_guide",
            }),
            workflow_grants=frozenset({"clinical_planning"}),
            action_plan=ActionPlan.from_tools(
                ("ctv_segmentation", "oar_segmentation", "planning_pipeline", "surgical_guide"),
                source="clinical_workflow_fast_path",
                dependencies={
                    "planning_pipeline": ("ctv_segmentation", "oar_segmentation"),
                    "surgical_guide": ("planning_pipeline",),
                },
            ),
        )
    if segmentation:
        resumes_clarified_action = bool(
            pending_tumor_site and not _requires_semantic_resolution(text)
        )
        if not resumes_clarified_action and not _is_canonical_execution_command(
            text,
            operation="segmentation",
        ):
            return _semantic_action_policy(complexity="medium", review=True)
        return LocalTurnPolicy(
            "segmentation",
            "medium",
            True,
            False,
            True,
            CLINICAL_TOOLS,
            direct_execution=True,
            execution_grants=frozenset({
                "ctv_segmentation", "oar_segmentation", "biomedparse_segmentation",
            }),
        )
    if external:
        return LocalTurnPolicy("external_project_query", "low", True, True, True, frozenset({"web_search", "web_fetch", "web_access"}))
    if clinical_advice:
        return LocalTurnPolicy("clinical_knowledge", "medium", True, True, True, KNOWLEDGE_TOOLS)
    if ui:
        return LocalTurnPolicy("ui_control", "low", False, False, False, UI_TOOLS)
    # An unmatched declarative/imperative turn may refer to a newly added
    # capability, a mixed request, or domain wording that no local shortcut
    # knows yet. Let the main LLM see the real registered capability set once
    # instead of silently reducing the turn to a knowledge-only whitelist.
    # Explicit questions above remain on the smaller low-latency read path.
    return _semantic_action_policy(complexity="medium", review=False)


def filter_tool_schemas(tools, policy: Optional[LocalTurnPolicy]):
    """Keep only tools permitted by the local policy and current registry."""
    if not policy or policy.allow_tools is None:
        return tools
    allowed = policy.allow_tools
    return [
        item for item in (tools or [])
        if item.get("function", {}).get("name") in allowed
    ]
