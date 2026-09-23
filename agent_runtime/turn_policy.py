"""Low-cost turn classification and execution policy.

This module is deliberately conservative.  It may bypass an expensive router
only for deterministic, low-risk requests.  Clinical execution and evidence
based medical advice keep the normal routing and review gates.
"""

from dataclasses import dataclass, field, replace
import re
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from agent_runtime.action_plan import ActionPlan
from agent_runtime.artifact_analysis import (
    ANALYSIS_READ_TOOLS,
    is_artifact_analysis_request,
    resolve_artifact_analysis_target,
)
from agent_runtime.ui_operations import resolve_ui_operation_request
from agent_runtime.shortcut_contract import shortcut_supported
from agent_runtime.intent_boundary import (
    canonical_resource_read, canonical_report_generation, has_explicit_read_request,
)
from agent_runtime import request_parse as _request_parse


KNOWLEDGE_TOOLS: FrozenSet[str] = frozenset({
    "clinical_kb", "web_search", "web_fetch", "web_access",
    "ctv_model_catalog", "doc_reader",
})

UI_TOOLS: FrozenSet[str] = frozenset({
    "ui_controller", "ui_inspector", "ui_screenshot", "ui_content", "ui_annotate",
    "viewer_command", "auto_navigate", "query_metrics", "dvh_curve",
})

# Location discovery is deliberately read-only.  Unknown or newly added
# objects may be inspected and captured, but a "where is X" turn can never
# click a control or start a clinical operation while trying to discover X.
VISUAL_DISCOVERY_TOOLS: FrozenSet[str] = frozenset({
    "ui_inspector", "ui_screenshot",
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
    # Structured capability resolution for an imperative UI turn.  Keeping
    # this on the policy makes the same decision available to the direct
    # executor, provider-tool filter, trace, and response formatter without
    # reparsing the user's sentence in several layers.
    ui_operation: Optional[Dict[str, Any]] = None
    # Auditable distinction between a lexical candidate and an accepted
    # whole-request execution contract. These never grant execution themselves.
    routing_source: str = "legacy_candidate"
    routing_reason: str = ""
    candidate_intent: str = ""
    # Structured view of the current request.  Purely informational: it is
    # written into the execution trace and the provider context, and it never
    # grants execution by itself.
    parsed_goals: Tuple[Tuple[str, str], ...] = ()
    parsed_reference: str = ""
    parsed_subtasks: Tuple[Tuple[str, str], ...] = ()
    # Artifact family behind an analysis request ("surgical_guide", "tumor",
    # "planning", ...).  Read-only routing metadata used to select the
    # characteristics fact packet and the analysis answer contract.
    analysis_target: str = ""


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


def is_viewer_result_display_request(message: str) -> bool:
    """Recognize an unambiguous request to display saved results in Viewer.

    This is deliberately narrower than the general ``ui_control`` classifier.
    A request that names a Viewer, a display/load verb, and an existing result
    family has a deterministic meaning: refresh the active Session's planning
    presentation.  It must not require the language model to choose a tool,
    because that turns a read-only browser refresh into an avoidable provider
    dependency.  Compound requests are filtered by ``classify_local_turn``
    before this helper is used as a direct fast path.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    has_viewer = _contains_any(text, (
        "viewer", "查看器", "2d viewer", "3d viewer", "2d查看器", "3d查看器",
    ))
    has_display_verb = _contains_any(text, (
        "显示", "展示", "呈现", "加载", "恢复", "刷新", "挂载", "打开",
        "show", "display", "present", "load", "restore", "refresh", "render",
        "open", "visualize",
    ))
    has_result_family = _contains_any(text, (
        "结果", "规划", "计划", "剂量", "数据", "结构", "掩膜", "面具", "粒子",
        "针道", "导板", "result", "plan", "planning", "dose", "dvh", "seed",
        "needle", "surgical guide", "guide", "mask", "data", "structure",
        "mesh", "isosurface",
    ))
    return has_viewer and has_display_verb and has_result_family


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
        # Keep the planning verb adjacent to the re-execution verb. A loose
        # gap here misclassified "重新计算当前规划方案的 DVH" as re-planning
        # simply because the noun "规划方案" appeared later in the sentence.
        # A single qualifier may sit before the plan noun ("重新执行手术规划",
        # "重做治疗计划"); without it the phrase fell through to the open
        # semantic router, where the word "手术" steered the model into
        # surgical_guide instead of the planning pipeline.
        r"(?:\u91cd\u65b0|\u518d\u6b21|\u518d|\u91cd\u505a|\u91cd\u8dd1)"
        r"(?:\u6267\u884c|\u8fdb\u884c|\u5f00\u59cb|\u505a)?\s*"
        r"(?:\u624b\u672f|\u6cbb\u7597)?\s*(?:\u89c4\u5212|\u8ba1\u5212)|"
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


def _planning_and_guide_replan_plan() -> ActionPlan:
    """Build the complete plan for an explicit re-planning request.

    Existing masks are reusable prerequisites.  The planning pipeline is not:
    a re-plan must create a new planning revision even when CTV/OAR are already
    present in memory.  A successful re-plan also invalidates the previous
    guide, so guide generation is an explicit dependent step in the same
    action plan rather than an optional provider-side follow-up.
    """
    return ActionPlan.from_tools(
        ("ctv_segmentation", "oar_segmentation", "planning_pipeline", "surgical_guide"),
        source="semantic_replan_dependency_guard",
        dependencies={
            "planning_pipeline": ("ctv_segmentation", "oar_segmentation"),
            "surgical_guide": ("planning_pipeline",),
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

    Thin adapter over :mod:`agent_runtime.request_parse` so every layer uses
    one interrogative definition.
    """
    return _request_parse.is_interrogative(message)


def _is_location_question(message: str) -> bool:
    """Return whether a message asks where an existing UI/case object is.

    Location questions are a read-only presentation intent.  They must be
    distinguished from generation/help questions such as ``where can I
    generate a guide`` and from geometry-edit commands.  This helper only
    identifies the linguistic shape; the resource resolver below still has
    to map the message to a known Session-owned resource family.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    chinese_location = bool(re.search(
        r"(?:哪里|哪儿|在哪(?:里)?|哪个(?:面板|窗口|视图|地方|位置)|"
        r"什么位置|所在位置|怎么找|如何找|找到|找得到)",
        text,
    ))
    english_location = bool(re.search(
        r"\b(?:where|located|location|locate|find|position)\b",
        text,
        flags=re.IGNORECASE,
    ))
    # ``位置``/``定位`` alone can describe an edit (for example, "调整针道
    # 位置"). Treat them as a question only when the sentence is explicitly
    # interrogative; direct where/find forms above are already unambiguous.
    positional_question = bool(re.search(
        r"(?:位置|定位)", text,
    )) and bool(re.search(
        r"[?？]|请问|是否|怎么样|如何|怎么|为什么|\b(?:what|which|where|how)\b",
        text,
        flags=re.IGNORECASE,
    ))
    return chinese_location or english_location or positional_question


def _has_visual_annotation_request(message: str) -> bool:
    """Return whether the user explicitly asks for a visual locating mark.

    This is a capability/routing signal, not a response whitelist.  The
    actual target, coordinates, visibility, and final wording still come from
    the structured screenshot plan, the browser grounding manifest, and the
    linked multimodal answer editor.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    return bool(re.search(
        r"(?:圈出来|圈出|框出来|框出|标出来|标出|标注|高亮|指出|指给我看|用箭头|用方框|画箭头|画框|"
        r"\b(?:circle|box|outline|mark|annotate|highlight|point out|show me|draw an arrow|arrow to)\b)",
        text,
        flags=re.IGNORECASE,
    ))


def is_ui_control_location_question(message: str) -> bool:
    """Recognize a request to locate an interface control, not a case object.

    This is a semantic boundary for the UI evidence workflow, not a response
    whitelist.  The actual control identity must still come from the live DOM
    capability metadata (or from ``ui_inspector`` for an unknown control), and
    the browser must produce the coordinates and visibility evidence.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text or not (_is_location_question(text) or _has_visual_annotation_request(text)):
        return False
    has_control_word = _contains_any(text, (
        "按钮", "控件", "图标", "菜单", "工具栏", "操作键", "按键",
        "button", "control", "icon", "menu", "toolbar", "action", "command",
    ))
    has_ui_context = _contains_any(text, (
        "viewer", "查看器", "面板", "窗口", "界面", "工具栏", "顶部",
        "data tree", "数据树", "3d", "3-d", "三维", "2d", "2-d", "二维",
        "reconstruct", "reconstruction", "重建", "放大", "缩放", "全屏",
    ))
    # ``哪个按钮/which button`` is already an interface-location request
    # even when the user has not named a panel or viewer yet.  Let the real
    # inspector discover the control instead of guessing one from prose.
    generic_button_question = _contains_any(text, (
        "哪个按钮", "什么按钮", "which button", "what button",
    ))
    return has_control_word and (has_ui_context or generic_button_question)


def resolve_ui_control_location_target(message: str) -> Optional[str]:
    """Resolve a known UI-control location to a stable semantic target.

    Only the full Viewer toolbar's 3D reconstruction action is resolved here
    because it has an explicit stable DOM capability.  Other controls stay on
    the inspector-driven path; hard-coding a pixel target for them would be
    less reliable than asking the current UI capability catalog.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not is_ui_control_location_question(text):
        return None
    has_3d = _contains_any(text, ("3d", "3-d", "三维"))
    has_reconstruction = _contains_any(text, (
        "reconstruct", "reconstruction", "reconstruct 3d", "3d reconstruct",
        "重建", "三维重建",
    ))
    if not (has_3d and has_reconstruction):
        return None
    # A Data Tree organ-row action is a different capability from the global
    # Viewer toolbar action.  Keep that wording on the inspector path so the
    # model can inspect the selected node and its actual row menu.
    if _contains_any(text, (
        "data tree", "数据树", "organ", "器官", "right click", "右键",
        "context menu", "右键菜单", "节点",
    )):
        return None
    return "ui_control:viewer.reconstruct3d"


def _visual_targets_from_text(message: str) -> Tuple[str, ...]:
    """Return every canonical visual capability named in the current turn.

    These aliases are a fast path for common clinical object families.  They
    are not the complete object vocabulary: exact Data Tree rows, scene
    objects, controls, newly added plug-in objects, and object parts are
    resolved from the browser's live ``visual_target_catalog`` below.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return ()

    visual_objects = (
        (
            "surgical_guide",
            ("surgical guide", "puncture guide", "guide mesh", "手术导板", "穿刺导板", "导板"),
        ),
        (
            "ctv",
            ("clinical target volume", "target volume", "tumor", "tumour", "lesion", "ctv", "肿瘤", "肿块", "病灶", "靶区"),
        ),
        (
            "oar",
            ("organ at risk", "organs at risk", "oar", "危及器官"),
        ),
        (
            "trajectories",
            ("trajectory", "trajectories", "needle path", "needle paths", "轨迹", "针道路径"),
        ),
        (
            "needles",
            ("needle", "needles", "puncture needle", "puncture needles", "穿刺针", "针道"),
        ),
        (
            "seeds",
            ("seed", "seeds", "radioactive seed", "radioactive seeds", "粒子", "种子"),
        ),
    )
    found: List[str] = []
    for capability, aliases in visual_objects:
        def alias_matches(alias: str) -> bool:
            if re.search(r"[a-z0-9_]", alias):
                return bool(re.search(
                    rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])",
                    text,
                    re.IGNORECASE,
                ))
            return alias in text

        if any(alias_matches(alias) for alias in aliases) and capability not in found:
            found.append(capability)

    if found:
        return tuple(found)

    target = resolve_session_content_target(text)
    if target in {
        "surgical_guide", "ctv", "oar", "seeds", "needles", "trajectories",
        "planning", "structures", "data_tree", "artifact",
        "dose", "dvh", "ct", "metrics",
    }:
        return (target,)
    if any(term in text for term in ("data tree", "数据树")):
        return ("data_tree",)
    if any(term in text for term in ("dvh", "dose-volume histogram", "剂量体积直方图")):
        return ("dvh",)
    if any(term in text for term in ("metric", "metrics", "指标")):
        return ("metrics",)
    if any(term in text for term in ("dose", "剂量")):
        return ("dose",)
    if any(term in text for term in ("planning", "规划")):
        return ("planning",)
    if any(term in text for term in ("ct", "image", "scan", "影像", "图像")):
        return ("ct",)
    if any(term in text for term in ("structure", "structures", "segmentation", "mask", "结构", "分割", "掩膜", "面具")):
        return ("structures",)
    return ()


def _visual_target_from_text(message: str) -> Optional[str]:
    """Find a live visual resource family from target words alone.

    ``resolve_session_content_target`` intentionally requires presentation
    wording and therefore returns ``None`` for a phrase such as ``圈出哪个是
    导板``.  Annotation requests need the same stable target resolution while
    retaining the content resolver's conservative behaviour for ordinary
    conversation.
    """
    targets = _visual_targets_from_text(message)
    return targets[0] if targets else None


def _recent_user_visual_target(conversation: Optional[Iterable[object]], *, skip_surface: bool = False) -> Optional[str]:
    """Resolve the nearest explicit visual target from recent user turns.

    A short, user-only context window lets ``截图给我在哪里`` follow a
    previous ``导板`` question without allowing an assistant fallback, tool
    output, or an old unrelated case to steer the new request.  This is
    context resolution, not a canned answer.
    """
    if not conversation:
        return None
    try:
        items = list(conversation)
    except TypeError:
        return None
    for item in reversed(items[-12:]):
        if not isinstance(item, dict) or str(item.get("role") or "").lower() != "user":
            continue
        content = item.get("content", item.get("message", ""))
        if isinstance(content, (list, tuple)):
            content = " ".join(
                str(part.get("text") or part.get("content") or "")
                if isinstance(part, dict) else str(part or "")
                for part in content
            )
        if _request_parse.is_internal_tool_result_message(content):
            continue
        candidate = _visual_target_from_text(str(content or ""))
        if candidate and not (skip_surface and candidate == "data_tree"):
            return candidate
    return None


def _has_explicit_guide_generation_command(message: str) -> bool:
    """Return whether guide generation is explicitly requested as an action.

    The negative lookahead after the Chinese verb is important: ``生成的手术
    导板在哪里`` describes an already generated object and must not be
    rewritten as a generation command merely because it contains ``生成``.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    if re.search(
        r"\b(?:please\s+)?(?:re-?generate|rebuild|create|generate|make|update|refresh)"
        r"\s+(?:the\s+)?(?:surgical|puncture|guide)\s+guide\b",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    return bool(re.search(
        r"(?:^|[\s,;:：，；。])"
        r"(?:请|帮我|需要|想|我想|现在|立即|马上|重新|再次|再|重做|重建)?\s*"
        r"(?:重新生成|再生成|生成|重建|重做|制作|创建|更新|刷新)\s*"
        r"(?:一个|一份|新的|当前)?\s*(?:手术|穿刺)?导板(?!的)",
        text,
        flags=re.IGNORECASE,
    ))


def _is_guide_generation_help_query(message: str) -> bool:
    """Return whether a guide location phrase asks where to create one.

    This prevents ``手术导板在哪里生成`` from becoming either a screenshot
    of a nonexistent object or an unintended clinical mutation.  A phrase
    that explicitly refers to a completed result (``已生成的手术导板在哪里``)
    remains a location query and is handled by the visual evidence route.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text or not _is_location_question(text):
        return False
    if not _contains_any(text, (
        "surgical guide", "puncture guide", "guide mesh", "guide stl",
        "手术导板", "穿刺导板", "手术刀板", "导板",
    )):
        return False
    if not _contains_any(text, (
        "generate", "regenerate", "re-generate", "rebuild", "create", "make",
        "生成", "重新生成", "再生成", "重建", "重做", "制作", "创建", "更新", "刷新",
    )):
        return False
    # Past/result modifiers bind the noun to an existing artifact rather than
    # to a generation workflow.
    if _contains_any(text, (
        "generated", "already generated", "existing", "saved", "completed",
        "生成的", "已生成", "已经生成", "已有", "现有", "完成的",
    )):
        return False
    # The location-to-generation ordering is the decisive signal for a help
    # question ("where can I generate..." / "在哪里生成..."). Check it
    # before the generic imperative matcher below, because the same sentence
    # necessarily contains the words "generate ... guide".
    if re.search(
        r"(?:哪里|哪儿|在哪|位置|定位|where|located|location|locate|find).{0,40}"
        r"(?:生成|重建|制作|创建|更新|刷新|generate|re-?generate|rebuild|create|make)",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    # A real imperative compound ("generate it and tell me where") belongs to
    # semantic action planning, not to this read-only help boundary.
    if _has_explicit_guide_generation_command(text):
        return False
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


def is_current_case_dose_recompute_request(message: str) -> bool:
    """Identify an explicit request to refresh the active plan's Dose/DVH.

    This is intentionally separate from ``_is_current_case_dose_query``. The
    latter is a read-only Session query, while this predicate authorizes one
    focused stateful operation: recomputing Dose/DVH from the already
    persisted Needle/Seed geometry. It must not classify a request to
    re-plan, segment, or generate a guide as a dose refresh.

    The predicate is used before provider routing and again at the clinical
    tool-normalization boundary. The second use prevents a provider from
    turning an unambiguous current-dose request into a full
    ``planning_pipeline`` call when an earlier wording variant was missed.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False

    # An explicit geometry/planning replacement remains a full planning
    # workflow, even when Dose/DVH is mentioned as the expected output.
    if is_planning_reexecution_request(text):
        return False
    if _contains_any(text, (
        "segment", "segmentation", "ctv", "oar", "needle", "seed", "guide",
        "分割", "靶区", "危及器官", "针道", "粒子", "导板",
    )) and _contains_any(text, (
        "规划", "计划", "replan", "plan", "planning",
    )):
        return False

    # A second mutating operation belongs to semantic planning. Verification
    # wording in the same clause ("重算并核对") is allowed because the dose
    # tool reports a before/after consistency result itself.
    if _looks_like_compound_action(text) and not _contains_any(text, (
        "验证", "校验", "核对", "核验", "一致", "compare", "verify", "consistent",
    )):
        return False

    has_dose_object = bool(re.search(
        r"(?:dvh|dose(?:[-\s]volume)?(?:\s+metrics?)?|dose\s+metrics?|"
        r"剂量|剂量分布|剂量结果|剂量指标|剂量相关指标)",
        text,
        flags=re.IGNORECASE,
    ))
    if not has_dose_object or _contains_any(text, (
        "guideline", "standard", "constraint", "limit", "tolerance",
        "recommendation", "prescription", "指南", "标准", "限值", "耐受",
        "参考", "处方",
    )):
        return False

    # A computed-result noun is a read, not a recalculation. This protects
    # "现在计算的剂量结果是多少" from becoming a mutation merely because
    # it contains the verb "计算".
    if _is_current_case_dose_query(text):
        return False

    return bool(re.search(
        r"(?:重新|再次|再|重算|更新|刷新|复核|核验|校验|验证|计算|评估)"
        r".{0,32}(?:dvh|dose|剂量|剂量指标|剂量结果|剂量分布|剂量相关指标)"
        r"|\b(?:please\s+)?(?:recalculate|recompute|calculate|compute|update|"
        r"refresh|evaluate|verify|check|run)\b.{0,40}\b(?:dvh|dose|"
        r"dose[-\s]volume|dose\s+metrics?|metrics?)\b",
        text,
        flags=re.IGNORECASE,
    ))


def is_current_planning_provenance_query(message: str) -> bool:
    """Identify a read-only question about which Planning produced a result.

    A follow-up such as ``\u672c\u6b21\u8ba1\u7b97\u662f\u4ee5\u54ea\u6b21\u89c4\u5212\u7ed3\u679c\u4e3a\u4f9d\u636e\u7684\u5462`` is neither a
    new planning command nor a generic clinical-knowledge question. It asks
    for provenance of an already completed operation and must be answered from
    the active Session's persisted Planning metadata. Keeping this predicate
    separate from the dose read/recompute predicates prevents the word
    ``\u89c4\u5212`` or ``\u8ba1\u7b97`` from accidentally starting an expensive workflow.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text or not _is_interrogative(text):
        return False

    has_planning_object = _contains_any(text, (
        "planning", "plan", "treatment plan", "dose plan", "planning result",
        "\u89c4\u5212", "\u8ba1\u5212", "\u65b9\u6848",
        # Method/algorithm wording is a planning object too: "刚刚用的是
        # RL还是规则法" names no plan noun but is still a provenance question.
        "algorithm", "method", "mode", "approach", "optimizer",
        "\u7b97\u6cd5", "\u6a21\u5f0f", "\u65b9\u5f0f", "\u65b9\u6cd5",
        "\u6280\u672f\u8def\u7ebf",
        "reinforcement", "rule-based", "rule based",
        "\u5f3a\u5316\u5b66\u4e60", "\u89c4\u5219\u6cd5", "\u89c4\u5219\u4f18\u5316",
    ))
    # ``current``/``active`` alone are not provenance questions. They are
    # common in ordinary requests such as "what is wrong with the current
    # plan?". The old broad marker list treated those words as proof of
    # provenance and routed unrelated questions to the fixed
    # ``Planning used for this Dose/DVH calculation`` paragraph. Require an
    # explicit source/basis relation (or a which-plan form) instead.
    has_provenance_relation = bool(re.search(
        r"(?:based\s+on|derived\s+from|according\s+to|source|origin|"
        r"which\s+(?:plan|planning|planning\s+result)|what\s+(?:plan|planning)|"
        r"(?:plan|planning|result).{0,24}\bused\b|\bused\s+(?:for|to)\b)|"
        r"(?:\u4f9d\u636e|\u57fa\u4e8e|\u6839\u636e|\u6765\u6e90|\u6765\u81ea|\u54ea\u6b21|\u54ea\u4e2a|\u54ea\u4e00\u4e2a).{0,24}"
        r"(?:\u89c4\u5212|\u8ba1\u5212|\u65b9\u6848|\u8ba1\u7b97|\u5242\u91cf|\u7ed3\u679c)|"
        r"(?:\u89c4\u5212|\u8ba1\u5212|\u65b9\u6848|\u8ba1\u7b97|\u5242\u91cf|\u7ed3\u679c).{0,24}"
        r"(?:\u4f9d\u636e|\u57fa\u4e8e|\u6839\u636e|\u6765\u6e90|\u6765\u81ea|\u54ea\u6b21|\u54ea\u4e2a|\u54ea\u4e00\u4e2a)",
        text,
        flags=re.IGNORECASE,
    ))
    # Method/algorithm provenance: "是使用的算法是基于RL的还是规则-based的",
    # "用的什么算法", "which method produced this plan".  The ``是…还是…``
    # choice frame itself is the relation: the user is asking which of two
    # execution methods produced the result.
    method_relation = bool(re.search(
        r"(?:what|which|how)\s+(?:\w+\s+){0,3}"
        r"(?:method|algorithm|mode|approach|optimizer)|"
        r"(?:method|algorithm|mode|approach|optimizer).{0,28}"
        r"\b(?:used|produced|generated|selected|chosen)\b|"
        r"\b(?:used|produced|generated|selected|chosen)\b.{0,28}"
        r"(?:method|algorithm|mode|approach|optimizer)|"
        r"\u7528\u7684|\u4f7f\u7528\u7684|\u91c7\u7528|\u9009\u7528|\u7528\u4e86|"
        r"\u4ec0\u4e48(?:\u7b97\u6cd5|\u65b9\u6cd5|\u6a21\u5f0f|\u65b9\u5f0f)|"
        r"\u54ea\u79cd(?:\u7b97\u6cd5|\u65b9\u6cd5|\u6a21\u5f0f|\u65b9\u5f0f|\u4f18\u5316)|"
        r"\u662f[^,.!?\uff0c\u3002\uff01\uff1f]{0,28}\u8fd8\u662e",
        text,
        flags=re.IGNORECASE,
    ))
    if not (has_planning_object and (has_provenance_relation or method_relation)):
        return False

    # A sentence that explicitly asks the system to execute a new operation
    # must remain an action request even if it ends with a question mark. A
    # provenance question may mention a past "recalculation", but it does not
    # begin with an imperative mutation frame.
    if re.search(
        r"(?:^|[,;\uff0c\uff1b])\s*(?:please\s+|\u8bf7|\u5e2e\u6211|\u9700\u8981|\u5f00\u59cb|\u6267\u884c|\u8fdb\u884c|\u9a6c\u4e0a|\u73b0\u5728)"
        r"(?:\u91cd\u65b0\u89c4\u5212|\u91cd\u65b0\u8ba1\u5212|\u91cd\u7b97|\u91cd\u65b0\u8ba1\u7b97|\u91cd\u65b0\u8bc4\u4f30|"
        r"(?:replan|recalculate|recompute|rerun)\b)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    return True


def is_current_planning_assessment_query(message: str) -> bool:
    """Identify a read-only question asking for problems with this plan.

    This is intentionally separate from provenance. A question about the
    current plan's quality, risks, anomalies, or items needing review should
    read the active Session facts and let the LLM explain them; it must not be
    answered with the unrelated "which Planning was used" template.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    # Polite requests such as "评价一下当前规划结果" are read-only
    # assessment turns even without a question mark. Keep them on the same
    # grounded local-read path as explicit questions instead of treating them
    # as a planning command.
    non_interrogative_assessment = bool(re.search(
        r"(?:\u8bc4\u4ef7|\u8bc4\u4f30|\u5206\u6790|\u5ba1\u67e5|\u590d\u6838|\u70b9\u8bc4|\u5efa\u8bae).{0,24}"
        r"(?:\u89c4\u5212|\u8ba1\u5212|\u65b9\u6848|\u7ed3\u679c|\u5242\u91cf|\u9776\u533a|\u7c92\u5b50|\u9488\u9053)|"
        r"(?:\u89c4\u5212|\u8ba1\u5212|\u65b9\u6848|\u7ed3\u679c|\u5242\u91cf|\u9776\u533a|\u7c92\u5b50|\u9488\u9053).{0,24}"
        r"(?:\u8bc4\u4ef7|\u8bc4\u4f30|\u5206\u6790|\u5ba1\u67e5|\u590d\u6838|\u70b9\u8bc4|\u5efa\u8bae)|"
        r"(?:evaluate|assess|review|analy[sz]e).{0,24}(?:plan|planning|dose|result)|"
        r"(?:advice|recommendations?).{0,24}(?:plan|planning|dose|result)",
        text,
        flags=re.IGNORECASE,
    ))
    if not _is_interrogative(text) and not non_interrogative_assessment:
        return False
    if is_planning_reexecution_request(text) or _has_explicit_planning_action(text):
        return False

    has_planning_object = _contains_any(text, (
        "planning", "plan", "treatment plan", "dose plan", "planning result",
        "\u89c4\u5212", "\u8ba1\u5212", "\u65b9\u6848",
    ))
    has_assessment_marker = bool(re.search(
        r"(?:problem|problems|issue|issues|concern|concerns|wrong|abnormal|"
        r"risk|quality|status|assessment|assess|evaluate|review|analy[sz]e|advice|recommendation|check|acceptable|"
        r"any\s+(?:issue|problem)|what.{0,12}(?:wrong|problem)|"
        r"\u95ee\u9898|\u6bdb\u75c5|\u5f02\u5e38|\u98ce\u9669|\u9690\u60a3|\u7f3a\u9679|\u4e0d\u8db3|\u8d28\u91cf|\u72b6\u6001|\u8bc4\u4f30|\u8bc4\u4ef7|\u68c0\u67e5|"
        r"\u590d\u6838|\u5173\u6ce8|\u9700\u8981\u6ce8\u610f|\u662f\u5426\u5408\u7406|\u662f\u5426\u6b63\u5e38|\u600e\u4e48\u6837)",
        text,
        flags=re.IGNORECASE,
    ))
    if not (has_planning_object and has_assessment_marker):
        return False

    # Standards questions need evidence retrieval. The local assessment route
    # can report observed facts, but must not imply a site-specific guideline
    # pass/fail decision without a sourced constraint.
    if _contains_any(text, (
        "guideline", "standard", "constraint", "limit", "tolerance",
        "recommendation", "\u6307\u5357", "\u6807\u51c6", "\u9650\u503c", "\u8010\u53d7", "\u89c4\u8303",
    )):
        return False
    return True


def is_case_state_question(message: str) -> bool:
    """Identify a read-only question about persisted case state.

    This is a semantic boundary, not a phrase-to-answer map.  Questions such
    as ``why are the two plans identical after I changed parameters?`` need a
    compact snapshot of the active run *and* its planning history so the main
    LLM can select and explain the relevant evidence.  They must not enter the
    broad function-calling loop, where a model can choose unrelated tools such
    as ``query_metrics`` or ``case_memory`` and then lose the actual question.

    Explicit mutations, standards questions, external-project questions, and
    the narrower provenance/assessment/dose predicates are resolved elsewhere
    in :func:`classify_local_turn` before this boundary is evaluated.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text or not _is_interrogative(text):
        return False

    # A question may mention an operation while asking for an explanation of
    # its result.  An imperative/re-execution frame is still a mutation and
    # must remain on the clinical action path.
    if is_planning_reexecution_request(text) or is_current_case_dose_recompute_request(text):
        return False
    # The generic planning-action detector intentionally accepts noun phrases
    # (for dependency enforcement), so it is too broad for this read boundary:
    # ``为什么规划结果...`` contains two planning terms but is not a command.
    # Only an unambiguous command-position form is excluded here; less clear
    # cases remain semantic questions and are answered from persisted facts.
    if _is_canonical_execution_command(text, operation="planning"):
        return False

    if _contains_any(text, (
        "guideline", "guidelines", "standard", "standards", "constraint", "limit",
        "tolerance", "recommendation", "clinical evidence", "指南", "标准",
        "限值", "耐受", "推荐", "临床依据", "文献",
    )):
        return False
    if _contains_any(text, (
        "github", "gitlab", "repository", "repo", "external project", "source code",
        "github", "开源项目", "外部项目", "项目源码",
    )):
        return False

    state_objects = (
        "planning", "plan", "treatment plan", "planning result", "parameters",
        "parameter", "setting", "settings", "result", "dose", "dvh", "v100",
        "d90", "seed", "needle", "ctv", "oar", "viewer", "data tree", "session",
        "rl", "reinforcement learning", "reinforcement", "episode", "stop reason",
        "规划", "计划", "方案", "规划结果", "参数", "设置", "结果", "剂量",
        "粒子", "针道", "靶区", "危及器官", "查看器", "数据树", "会话",
        "强化学习", "回合", "停止原因",
    )
    relation_markers = (
        "why", "how come", "because", "cause", "reason", "same", "identical",
        "different", "change", "changed", "unchanged", "compare", "comparison",
        "difference", "missing", "disappear", "disappeared", "show", "visible",
        "failed", "failure", "fail", "interrupted", "stopped", "stop", "budget",
        "target", "not reached", "without target", "episode", "reason",
        "一样", "相同", "不一样", "不同", "改了", "修改", "变化", "变了", "比较",
        "对比", "差异", "原因", "为什么", "为何", "怎么", "消失", "不见", "显示",
        "可见", "丢失", "恢复", "还在", "是否", "失败", "未达", "未达到", "中断",
        "停止", "预算", "目标", "回合",
    )
    return _contains_any(text, state_objects) and _contains_any(text, relation_markers)


def is_current_oar_count_query(message: str) -> bool:
    """Identify a question about the OAR structures loaded in this case."""
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text or not _is_interrogative(text):
        return False
    if _contains_any(text, (
        "guideline", "standard", "constraint", "limit", "recommended",
        "clinical", "指南", "标准", "限值", "推荐", "临床",
    )):
        return False
    return bool(
        re.search(r"(?:how many|number of|count of)\s+(?:the\s+)?(?:oars?|organs?)", text)
        or re.search(r"(?:oars?|organs?).*(?:how many|how much|number|count)", text)
        or re.search(r"(?:多少|几种|数量|数一下).*(?:oar|危及器官|器官)", text)
        or re.search(r"(?:oar|危及器官|器官).*(?:多少|几种|数量)", text)
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

    parsed = _request_parse.parse_request(message)
    explicit_report_write = any(
        task.target == "report"
        and task.action == "generate"
        and task.unconditional_command
        and not task.attributed
        for task in parsed.subtasks
    )
    if explicit_report_write:
        return "regenerate"

    figure_terms = (
        "figure", "fig", "screenshot", "image", "images", "picture", "figures",
        "\u622a\u56fe", "\u622a\u5c4f", "\u56fe\u7247", "\u56fe\u50cf", "\u56fe\u4ef6",
    )
    if not has_explicit_read_request(positive_text):
        return None
    return "view_figures" if _contains_any(positive_text, figure_terms) else "view"


def is_report_generation_request(message: str) -> bool:
    """Return whether a turn mutates the editable report."""
    return resolve_report_request_action(message) == "regenerate"


def unambiguous_report_generation_request(message: str) -> bool:
    """Return whether the whole turn is a clear report mutation.

    A report noun with a generation/update verb names the report as the
    protected object, even when that noun carries a domain qualifier such as
    ``手术报告``, ``剂量报告`` or ``分析报告``.  The structural protection is
    "the report is the object of the command verb": qualifier content does not
    change the requested action.  Negation, correction, conditions, questions,
    quoted text and compound goals are not unambiguous and must stay on the
    semantic route.

    This is the object-level contract shared by the routing layer and the
    provider tool-selection boundary: a report request may never be executed
    by the guide capability.
    """
    text = str(message or "")
    if not is_report_generation_request(text):
        return False
    return _request_parse.unambiguous_report_generation(text)


def unambiguous_guide_generation_request(message: str) -> bool:
    """Return whether the whole turn is a clear guide mutation (not compound).

    Shared by the provider boundary so a report/screenshot call selected for an
    explicit guide command is corrected, while a compound "guide and report"
    turn is left to the semantic plan.
    """
    text = str(message or "")
    if not is_surgical_guide_generation_request(text):
        return False
    return _request_parse.unambiguous_guide_generation(text)


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

    # A location question is a read-only request.  In particular, the noun
    # phrase ``生成的手术导板在哪里`` contains the character ``生成`` but asks
    # for the already persisted artifact, so it must never authorize a new
    # guide operation.  Generation-help questions are also non-mutating; the
    # primary LLM can explain the UI/workflow without starting a run.
    if _is_guide_generation_help_query(text):
        return False
    if _is_location_question(text) and not _has_explicit_guide_generation_command(text):
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
        "where", "located", "location", "locate", "find", "position",
        "\u67e5\u770b", "\u770b\u770b", "\u663e\u793a", "\u6253\u5f00", "\u5c55\u793a", "\u5448\u73b0",
        "\u54ea\u91cc", "\u54ea\u513f", "\u5728\u54ea", "\u4f4d\u7f6e", "\u5b9a\u4f4d", "\u627e\u5230", "\u627e\u5f97\u5230",
        "\u600e\u4e48\u627e", "\u5982\u4f55\u627e", "\u54ea\u4e2a\u9762\u677f", "\u54ea\u4e2a\u7a97\u53e3", "\u54ea\u4e2a\u89c6\u56fe",
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
    if (
        re.search(r"(?<![a-z0-9_])ct(?![a-z0-9_])", text)
        or any(term in text for term in ("image", "scan", "\u5f71\u50cf", "\u56fe\u50cf"))
    ):
        return "ct"
    if any(term in text for term in ("session", "case", "workspace", "\u672c\u75c5\u4f8b", "\u5f53\u524d\u4f1a\u8bdd", "\u5f53\u524d\u6848\u4f8b", "\u5168\u90e8\u5185\u5bb9")):
        return "session_summary"
    return None


_CANONICAL_VISUAL_TARGET_REFS: Dict[str, Tuple[str, ...]] = {
    "surgical_guide": ("surgical_guide:active",),
    "ctv": ("structure:ctv:active",),
    "oar": ("structure:oar:active",),
    "seeds": ("group:planning:seeds",),
    "needles": ("group:planning:needles",),
    "trajectories": ("group:planning:trajectories",),
    "ui_control:viewer.reconstruct3d": ("reconstruct3DButton",),
}


def _target_agnostic_visual_followup(message: str) -> bool:
    """Return whether the turn refers only to a previously named target.

    Previous-target inheritance is intentionally narrow.  An explicit but
    unknown noun (including a nonexistent object) must go through live
    discovery and may not silently inherit the previous guide, CTV, or row.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    reduced = text
    removable = (
        "screenshot", "screen shot", "capture", "image", "picture",
        "where", "located", "location", "locate", "find", "show", "mark",
        "annotate", "box", "circle", "arrow", "point out", "which one",
        "截图", "截屏", "图片", "图像", "在哪里", "哪里", "哪儿", "在哪", "位置",
        "定位", "找到", "找出", "显示", "展示", "圈出", "圈起来", "框出",
        "标注", "箭头", "指出", "哪个", "哪一个", "告诉", "请问", "请",
        "给我", "一下", "出来", "看看", "看一下", "呢", "吗", "吧",
        "it", "this", "that", "them", "those", "these", "the object",
        "它", "这个", "那个", "该对象", "目标", "对象",
    )
    for phrase in sorted(removable, key=len, reverse=True):
        reduced = reduced.replace(phrase, " ")
    reduced = re.sub(r"[^a-z0-9\u3400-\u4dbf\u4e00-\u9fff]+", "", reduced)
    return not reduced


def _live_visual_catalog(ui_state: Optional[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    if not isinstance(ui_state, Mapping):
        return []
    raw = ui_state.get("visual_target_catalog", ui_state.get("visualTargets"))
    if not isinstance(raw, (list, tuple)):
        return []
    return [item for item in raw[:512] if isinstance(item, Mapping)]


def _catalog_target_matches(
    message: str,
    ui_state: Optional[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Resolve exact live labels/aliases to stable IDs without coordinates."""
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    matches: List[Dict[str, Any]] = []
    seen = set()
    for item in _live_visual_catalog(ui_state):
        refs = item.get("target_refs", item.get("targetRefs", item.get("identities", [])))
        if isinstance(refs, str):
            refs = [refs]
        if not isinstance(refs, (list, tuple)):
            refs = []
        normalized_refs = list(dict.fromkeys(
            str(value or "").strip()
            for value in refs
            if str(value or "").strip()
        ))[:16]
        ref = normalized_refs[0] if normalized_refs else ""
        if not ref or ref in seen:
            continue
        labels = [
            item.get("label"), item.get("name"), item.get("text"),
            *(item.get("aliases") if isinstance(item.get("aliases"), (list, tuple)) else []),
        ]
        normalized_labels = [
            re.sub(r"\s+", " ", str(value or "").strip().lower())
            for value in labels
            if str(value or "").strip()
        ]
        # Exact live labels may be arbitrary plug-in names or user-created
        # object names.  Requiring at least two characters avoids matching a
        # one-letter control label everywhere in the sentence.
        def label_matches(label: str) -> bool:
            if len(label) < 2:
                return False
            # CJK and punctuation-bearing display labels are naturally
            # phrase-like. Pure ASCII words/IDs need token boundaries so a
            # short row such as ``CT`` cannot match ``current``.
            if re.search(r"[^a-z0-9_ -]", label):
                return label in text
            return bool(re.search(
                rf"(?<![a-z0-9_]){re.escape(label)}(?![a-z0-9_])",
                text,
                flags=re.IGNORECASE,
            ))

        matched_labels = [label for label in normalized_labels if label_matches(label)]
        if not matched_labels:
            continue
        seen.add(ref)
        matches.append({
            "target_ref": ref,
            "target_refs": normalized_refs,
            "family": str(item.get("family") or item.get("kind") or "dynamic").strip().lower(),
            "label": next((label for label in normalized_labels if label), ref),
            "matched_labels": matched_labels,
            "surfaces": [
                str(value or "").strip().lower()
                for value in (
                    item.get("surfaces")
                    if isinstance(item.get("surfaces"), (list, tuple)) else []
                )
                if str(value or "").strip()
            ],
        })
        if len(matches) >= 32:
            break

    # The same display label can occur on a segmentation row and a generated
    # scene object, or on two historical/current nodes. Never turn that into a
    # composite target by concatenating both identities: the user must choose
    # which live object they mean. Several refs published by one catalog item
    # remain one logical target and are not ambiguous.
    label_owners: Dict[str, set] = {}
    for item in matches:
        for label in item.get("matched_labels", []):
            label_owners.setdefault(label, set()).add(item["target_ref"])
    for item in matches:
        ambiguous_labels = [
            label for label in item.get("matched_labels", [])
            if len(label_owners.get(label, ())) > 1
        ]
        item["ambiguous_labels"] = ambiguous_labels
        item["ambiguous"] = bool(ambiguous_labels)
        item["candidate_target_refs"] = sorted({
            ref
            for label in ambiguous_labels
            for ref in label_owners.get(label, ())
        })
    return matches


def _is_session_visual_discovery_question(
    message: str,
    ui_state: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Recognize a location request that needs runtime object discovery.

    This predicate is capability-based: an explicit UI/viewer/current-case
    context, an active medical viewer, or a label in the live target catalog
    is enough.  It does not assume that the requested object exists.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text or not (_is_location_question(text) or _has_visual_annotation_request(text)):
        return False
    if _catalog_target_matches(text, ui_state):
        return True
    if _contains_any(text, (
        "screenshot", "viewer", "data tree", "ui", "button", "control", "panel",
        "截图", "视图", "查看器", "数据树", "界面", "按钮", "控件", "面板",
        "current case", "this case", "patient", "当前病例", "本病例", "患者",
        "图中", "画面中", "屏幕上", "圈出", "框出", "标注", "箭头",
    )):
        return True
    viewer = ui_state.get("viewer") if isinstance(ui_state, Mapping) else None
    return bool(isinstance(viewer, Mapping) and viewer.get("ct_loaded"))


def resolve_session_visual_location_request(
    message: str,
    conversation: Optional[Iterable[object]] = None,
    ui_state: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve a location turn into a current-target integrity contract."""
    raw_text = str(message or "").strip()
    if not raw_text:
        return None

    # Resolve only positive, unconditioned, non-attributed parts of the
    # current request. Quoted instructions and neighboring negated clauses
    # must not supply a screenshot target to a real request.
    parsed = _request_parse.parse_request(raw_text)
    active_fragments = []
    for task in parsed.subtasks:
        if task.negated or task.conditional or task.attributed:
            continue
        if _request_parse.is_quoted(task.raw):
            continue
        fragment = str(task.raw or "").strip()
        if fragment:
            active_fragments.append(fragment)
    if parsed.subtasks and not active_fragments:
        return None
    scoped_text = " ".join(active_fragments) if active_fragments else raw_text
    unquoted_scope = _request_parse._mask_quoted_content(scoped_text)
    text = re.sub(r"\s+", " ", scoped_text.strip().lower())
    intent_text = re.sub(r"\s+", " ", unquoted_scope.strip().lower())
    if not text or not (
        _is_location_question(intent_text)
        or _has_visual_annotation_request(intent_text)
    ):
        return None
    if _is_image_tumor_measurement_request(text):
        return None
    if _has_explicit_guide_generation_command(text) or _is_guide_generation_help_query(text):
        return None

    control_target = resolve_ui_control_location_target(text)
    current_targets = list(_visual_targets_from_text(text))
    # "Where in the Data Tree?" names the presentation surface, not a new
    # object. Unlike "Where is the Data Tree?", it inherits the user's last
    # explicit subject. Full-clause matching prevents unknown object names
    # from being silently replaced by a previous guide.
    surface_followup = bool(re.fullmatch(
        r"(?:在\s*(?:data\s*tree|数据树)(?:里|中)?(?:的)?\s*(?:哪里|哪儿|哪个位置)(?:呢|呀|啊|吗)?"
        r"|where\s+(?:is\s+it\s+)?in\s+(?:the\s+)?data\s*tree)[？?。.!！\s]*",
        text,
    ))
    if surface_followup:
        inherited = _recent_user_visual_target(conversation, skip_surface=True)
        if inherited:
            return {
                "semantic_targets": [inherited],
                "target_refs": list(_CANONICAL_VISUAL_TARGET_REFS.get(inherited, ())),
                "target_query": text,
                "target_source": "conversation_reference",
                "target_surfaces": ["data-tree"],
                "requires_discovery": False,
            }
    if control_target:
        current_targets = [control_target]

    catalog_matches = _catalog_target_matches(text, ui_state)
    ambiguous_matches = [item for item in catalog_matches if item.get("ambiguous")]
    if ambiguous_matches:
        labels = list(dict.fromkeys(
            label
            for item in ambiguous_matches
            for label in item.get("ambiguous_labels", [])
        ))
        candidate_refs = list(dict.fromkeys(
            ref
            for item in ambiguous_matches
            for ref in item.get("candidate_target_refs", [])
        ))
        return {
            "semantic_targets": [],
            "target_refs": [],
            "target_query": text,
            "target_source": "ambiguous_live_catalog",
            "target_surfaces": list(dict.fromkeys(
                surface
                for item in ambiguous_matches
                for surface in item.get("surfaces", [])
            )),
            "requires_discovery": True,
            "ambiguous": True,
            "ambiguous_labels": labels[:16],
            "candidate_target_refs": candidate_refs[:32],
        }
    target_refs: List[str] = []
    semantic_targets: List[str] = []
    source = "canonical"
    if current_targets:
        semantic_targets = current_targets
        for target in current_targets:
            target_refs.extend(_CANONICAL_VISUAL_TARGET_REFS.get(target, ()))
        # A request may combine a canonical family with an arbitrary live row
        # or object part (for example "CTV and custom bracket"). Preserve
        # both instead of letting the common-family fast path erase the
        # dynamic half of the request.
        if catalog_matches:
            source = "canonical+live_catalog"
            for item in catalog_matches:
                target_refs.extend(item.get("target_refs") or [item["target_ref"]])
                family = item.get("family") or "dynamic"
                if family not in semantic_targets:
                    semantic_targets.append(family)
    elif catalog_matches:
        source = "live_catalog"
        for item in catalog_matches:
            target_refs.extend(item.get("target_refs") or [item["target_ref"]])
            semantic_targets.append(item.get("family") or "dynamic")
    elif _target_agnostic_visual_followup(text):
        inherited = _recent_user_visual_target(conversation)
        if inherited:
            source = "conversation_reference"
            semantic_targets = [inherited]
            target_refs.extend(_CANONICAL_VISUAL_TARGET_REFS.get(inherited, ()))

    target_refs = list(dict.fromkeys(ref for ref in target_refs if ref))[:32]
    semantic_targets = list(dict.fromkeys(target for target in semantic_targets if target))[:32]
    if semantic_targets or target_refs:
        return {
            "semantic_targets": semantic_targets,
            "target_refs": target_refs,
            "target_query": text,
            "target_source": source,
            "target_surfaces": list(dict.fromkeys(
                surface
                for item in catalog_matches
                for surface in item.get("surfaces", [])
            )),
            "requires_discovery": False,
        }
    if _is_session_visual_discovery_question(text, ui_state):
        return {
            "semantic_targets": [],
            "target_refs": [],
            "target_query": text,
            "target_source": "live_discovery",
            "requires_discovery": True,
        }
    return None


def resolve_session_visual_location_target(
    message: str,
    conversation: Optional[Iterable[object]] = None,
    ui_state: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Resolve a request to locate a live Session object visually.

    This is deliberately separate from ``resolve_session_content_target``:
    persisted report figures/attachments are read directly, while a question
    such as ``请问手术导板在哪里`` requires fresh, grounded Viewer/Data Tree
    evidence.  The returned value is a resource capability, not a canned
    answer; the browser validates the stable identity, visibility, freshness,
    and current Session before capturing or annotating anything.
    """
    request = resolve_session_visual_location_request(
        message,
        conversation=conversation,
        ui_state=ui_state,
    )
    if not request or request.get("requires_discovery"):
        return None
    targets = request.get("semantic_targets") or []
    return str(targets[0]) if targets else None


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


def _is_code_capability_query(message: str) -> bool:
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text or not _is_interrogative(text):
        return False
    has_code_topic = _contains_any(text, (
        "代码", "编程", "程序", "脚本", "code", "coding", "programming", "script",
    ))
    asks_capability = _contains_any(text, (
        "可以", "能不能", "能否", "会不会", "能做", "写", "编写",
        "can you", "could you", "are you able", "do you",
    ))
    return has_code_topic and asks_capability


def is_surgical_guide_status_query(message: str) -> bool:
    """Recognize a read-only question about whether a guide exists or is ready."""
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text or not _is_interrogative(text) or _is_location_question(text):
        return False
    if not _contains_any(text, (
        "surgical guide", "puncture guide", "guide mesh", "guide stl",
        "手术导板", "穿刺导板", "手术刀板", "导板",
    )):
        return False
    if _has_explicit_guide_generation_command(text):
        return False
    return bool(
        re.search(
            r"(?:生成|创建|制作|完成|存在|加载|保存|generate|create|build|load|save)"
            r".{0,36}(?:了吗|了没|没有|有吗|是否|吗|\?|？|ready|available)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:是否|有没有|有无|已经|已|当前状态|状态是|status|whether|has|is)"
            r".{0,36}(?:生成|创建|制作|完成|存在|加载|保存|generated|created|ready|available)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _split_compound_query_clauses(message: str) -> List[str]:
    text = re.sub(r"\s+", " ", str(message or "").strip())
    if not text or len(text) > 8000:
        return []
    parts = re.split(
        r"[?？!！;；\n]+|[,，]+|(?:此外|另外|同时|顺便|而且|并且|另外还|此外还|还有)|"
        r"\b(?:additionally|besides|in addition|also)\b",
        text,
        flags=re.IGNORECASE,
    )
    clauses = []
    for part in parts:
        clause = re.sub(
            r"^(?:此外|另外|同时|顺便|而且|并且|另外还|此外还|还有|然后)\s*",
            "",
            str(part or "").strip(),
            flags=re.IGNORECASE,
        )
        if clause:
            clauses.append(clause)
    # Coordinated complete read-questions are independent subtasks, while
    # ordinary noun coordination (“dose and report”) stays intact. A connector
    # splits only if both sides resolve to known read intents.
    expanded = []
    connector = re.compile(
        r"\s+(?:and then|and|then)\s+|(?:以及|和|与|及|并(?=[\u4e00-\u9fff]))",
        re.IGNORECASE,
    )
    for clause in clauses:
        split_at = None
        for match in connector.finditer(clause):
            left = clause[:match.start()].strip()
            right = clause[match.end():].strip()
            if not left or not right:
                continue
            if (
                _read_query_subtask_intent(left, None, None)
                and _read_query_subtask_intent(right, None, None)
            ):
                split_at = match
                break
        if split_at is None:
            expanded.append(clause)
        else:
            expanded.extend((clause[:split_at.start()].strip(), clause[split_at.end():].strip()))
    clauses = [clause for clause in expanded if clause]

    # A trailing presentation instruction is a modifier of the preceding
    # question, not an independent subtask. Without this fold, a request such
    # as "guide where? tumor where, screenshot separately" ends with a clause
    # that has no object and the conservative compound resolver rejects the
    # whole request. Keep this narrow: only capture/show/mark tails are folded.
    presentation_tail = re.compile(
        r"^(?:(?:请|麻烦)\s*)?(?:(?:分别|各自|逐一|依次)\s*)?"
        r"(?:截图|截屏|拍照|截取图像)"
        r"(?:(?:并|然后)?(?:告知|说明|告诉我|给我看(?:看)?|展示|标注|指出))?"
        r"(?:一下|即可|就行)?$|"
        r"^(?:(?:please\s*)?(?:(?:separately|individually|one by one)\s*)?)?"
        r"(?:take\s+)?(?:screenshots?|captures?)(?:\s+(?:and\s+)?(?:show|tell me|explain|mark|annotate))?$",
        flags=re.IGNORECASE,
    )
    if len(clauses) >= 2 and presentation_tail.fullmatch(clauses[-1]):
        clauses[-2] = f"{clauses[-2]}，{clauses[-1]}"
        clauses.pop()
    return clauses if 2 <= len(clauses) <= 6 else []


def _read_query_subtask_intent(
    clause: str,
    conversation: Optional[Iterable[object]],
    ui_state: Optional[Mapping[str, Any]],
) -> Optional[str]:
    if _is_code_capability_query(clause):
        return "code_capability_query"
    if is_surgical_guide_status_query(clause):
        return "surgical_guide_status_query"
    if is_current_planning_assessment_query(clause):
        return "planning_assessment_query"
    if is_current_planning_provenance_query(clause):
        return "planning_provenance_query"
    if is_case_state_question(clause):
        return "case_state_question"
    if _is_current_case_dose_query(clause):
        return "case_dose_query"
    if _is_current_image_metadata_query(clause):
        return "image_metadata_query"
    if is_current_oar_count_query(clause):
        return "current_oar_query"
    visual = resolve_session_visual_location_request(
        clause, conversation=conversation, ui_state=ui_state,
    )
    if visual and visual.get("ambiguous"):
        return "ambiguous_visual_target_query"
    if visual and visual.get("requires_discovery"):
        return "unresolved_visual_target_query"
    if visual:
        return "session_visual_location_query"
    return None


def resolve_compound_query_intents(
    message: str,
    conversation: Optional[Iterable[object]] = None,
    ui_state: Optional[Mapping[str, Any]] = None,
) -> Tuple[Tuple[str, str], ...]:
    """Resolve a small compound turn only when every clause is a known read.

    Any unknown clause, write goal, negation, condition, or quotation makes
    this resolver abstain and leaves the established semantic workflow in
    charge. Returned pairs are the read intent and original clause.
    """
    text = str(message or "").strip()
    if not text:
        return ()
    parsed = _request_parse.parse_request(text)
    if parsed.compound_write:
        return ()
    clauses = _split_compound_query_clauses(text)
    if not clauses:
        return ()
    resolved = []
    for clause in clauses:
        local = _request_parse.parse_request(clause)
        # A prohibited, quoted, attributed, or conditional clause contributes
        # no executable/read task, but does not cancel a separate positive
        # read request in the same turn.
        if any(
            task.negated or task.conditional or task.attributed
            or (task.quoted and task.action)
            for task in local.subtasks
        ):
            continue
        intent = _read_query_subtask_intent(clause, conversation, ui_state)
        if not intent:
            return ()
        resolved.append((intent, clause))
    return tuple(resolved) if resolved else ()


def _classify_local_candidate(
    message: str,
    pending_tumor_site: bool = False,
    conversation: Optional[Iterable[object]] = None,
    ui_state: Optional[Mapping[str, Any]] = None,
) -> LocalTurnPolicy:
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

    # An explicit "update everything" command is a deterministic downstream
    # repair: the Session already records which artifacts are stale, so the
    # plan is built from artifact_status instead of asking the model to
    # re-derive it.  Only an affirmative, unconditional aggregate write
    # qualifies; questions/negations/conditions never reach this point.  It is
    # resolved before the object-specific fast paths so "全部更新，不含导板"
    # is a scoped aggregate, not a bare guide-generation command.
    if _request_parse.is_downstream_update_request(text):
        return LocalTurnPolicy(
            "downstream_update",
            "high",
            True,
            False,
            False,
            SEMANTIC_TOOLS,
            direct_execution=True,
        )

    parsed_subtasks = resolve_compound_query_intents(
        text, conversation=conversation, ui_state=ui_state,
    )
    if parsed_subtasks:
        tool_names = set()
        if any(intent == "session_visual_location_query" for intent, _ in parsed_subtasks):
            tool_names.add("ui_screenshot")
        if any(intent == "surgical_guide_status_query" for intent, _ in parsed_subtasks):
            tool_names.add("surgical_guide")
        return LocalTurnPolicy(
            "multi_intent_query",
            "medium",
            False,
            False,
            False,
            frozenset(tool_names),
            direct_execution=True,
            execution_grants=frozenset(
                {"surgical_guide"} if "surgical_guide" in tool_names else set()
            ),
            parsed_subtasks=parsed_subtasks,
        )

    # This is a read-only provenance lookup. Resolve it before re-plan and
    # compound-action detection so historical wording such as "这次重新计算
    # 是基于哪次规划" cannot be interpreted as permission to run planning.
    if is_current_planning_provenance_query(text):
        return LocalTurnPolicy(
            "planning_provenance_query",
            "low",
            False,
            False,
            False,
            frozenset(),
        )

    if is_surgical_guide_status_query(text):
        return LocalTurnPolicy(
            "surgical_guide_status_query",
            "low",
            False,
            False,
            False,
            frozenset({"surgical_guide"}),
            direct_execution=True,
            execution_grants=frozenset({"surgical_guide"}),
        )

    # A question about problems, risks, or review items in the active plan is
    # a different read boundary from provenance.  Keep it out of the fixed
    # "which Planning was used" response, while still avoiding a mutating
    # planning pipeline.
    if is_current_planning_assessment_query(text):
        return LocalTurnPolicy(
            "planning_assessment_query",
            "low",
            False,
            False,
            False,
            frozenset(),
        )

    # "分析/评估/解读 <artifact>" is a read-only discourse act over an
    # already-produced artifact (guide characteristics, tumor situation, dose
    # shape, ...).  It must never reach the open tool loop where a provider can
    # mistake it for a regeneration command: the grounded analysis path answers
    # from the artifact's characteristics facts instead.  Cross-artifact or
    # standards questions keep the primary LLM but with a read-only tool
    # surface, so analysis can never restart a workflow.
    analysis_request = is_artifact_analysis_request(text, conversation=conversation)
    if analysis_request is not None:
        if analysis_request["complex"]:
            return replace(
                _semantic_action_policy(complexity="high", review=True),
                allow_tools=ANALYSIS_READ_TOOLS,
                routing_source="analysis_llm",
                routing_reason="complex_artifact_analysis",
                analysis_target=analysis_request["artifact"],
            )
        return LocalTurnPolicy(
            "artifact_analysis_query",
            "low",
            False,
            False,
            False,
            frozenset(),
            analysis_target=analysis_request["artifact"],
        )

    # Other questions about persisted case state (for example, why two
    # Planning results look identical after a parameter change) need a
    # history-aware evidence packet.  Resolve them before UI/action and
    # generic interrogative branches so they never enter an open-ended tool
    # loop or get answered by the current-dose-only formatter.
    if is_case_state_question(text):
        return LocalTurnPolicy(
            "case_state_question",
            "low",
            False,
            False,
            False,
            frozenset(),
        )

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
            action_plan=_planning_and_guide_replan_plan(),
        )

    # Resolve compound requests before every read-only or operation-specific
    # shortcut. Otherwise a phrase such as "regenerate the report and show
    # its figures" could be consumed by the report branch before the model
    # sees the second action. The only routing-level dependency encoded here
    # is the safety-critical planning -> guide relationship; all other actions
    # are selected and ordered by the primary LLM.
    if _looks_like_compound_action(text) or _request_parse.parse_request(text).compound_write:
        parsed = _request_parse.parse_request(text)
        policy = _semantic_action_policy(
            complexity="high",
            review=True,
            action_plan=(
                _planning_and_guide_plan()
                if requires_planning_before_guide(text)
                else (
                    _planning_and_guide_replan_plan()
                    if is_planning_reexecution_request(text)
                    else None
                )
            ),
        )
        # An ordered goal list is attached for the provider/trace.  Only the
        # safety-critical planning -> guide dependency is executed
        # deterministically; every other compound turn is resolved as a whole
        # by the primary model instead of being split into guessed shortcuts.
        if parsed.goals:
            policy = replace(
                policy,
                parsed_goals=parsed.goals,
                routing_reason="compound_goals_parsed",
            )
        return policy

    # Object + action priority: a report noun is the protected object of a
    # generation/update command. Resolve it before the guide, Viewer, and
    # dose shortcuts so a domain qualifier such as "手术" cannot be read as
    # "手术导板" and so "剂量报告" is a report, not a dose recalculation.
    # Negation, correction and compound goals were already delegated above,
    # so reaching here means the whole turn is a positive report command.
    if is_report_generation_request(text):
        if not canonical_report_generation(text):
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

    # "Where can I generate a guide?" asks for workflow/UI guidance, not for
    # a new guide and not for the location of an existing artifact. Keep this
    # as a safe knowledge turn so the model can explain the current controls
    # without receiving a clinical mutation capability.
    if _is_guide_generation_help_query(text):
        return LocalTurnPolicy(
            "knowledge_query",
            "low",
            False,
            False,
            False,
            KNOWLEDGE_TOOLS,
        )

    # Displaying an already persisted planning result is a deterministic,
    # read-only browser operation. Resolve it before the generic Session
    # content branch so ``...planning result in Viewer`` does not become a
    # report/attachment query and before the generic UI branch so it cannot
    # fall through to an LLM provider call.
    if is_viewer_result_display_request(text):
        return LocalTurnPolicy(
            "viewer_display",
            "low",
            False,
            False,
            False,
            frozenset({"ui_controller"}),
            direct_execution=True,
            execution_grants=frozenset({"ui_controller"}),
        )

    # Recomputing current Dose/DVH is a focused stateful operation. Resolve
    # it before the interrogative branch because users often append a
    # consistency check ("...是否一致"), which otherwise looks like a
    # knowledge question. The grant is scoped to the high-level tool only.
    if is_current_case_dose_recompute_request(text):
        return LocalTurnPolicy(
            "dose_recompute",
            "medium",
            False,
            False,
            False,
            frozenset({"dose_recompute"}),
            direct_execution=True,
            execution_grants=frozenset({"dose_recompute"}),
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

    # A location question about an existing case object needs live, grounded
    # visual evidence. Keep it read-only and route directly to one structured
    # screenshot plan; the browser will resolve the current stable identity
    # and the hidden multimodal child will explain only what is actually
    # visible. This branch precedes guide generation and generic interrogative
    # handling so ``手术导板在哪里`` cannot become
    # ``surgical_guide(action=generate)`` while image-grounded tumor
    # measurement questions above retain their analytical route.
    visual_location_request = resolve_session_visual_location_request(
        text,
        conversation=conversation,
        ui_state=ui_state,
    )
    if visual_location_request and visual_location_request.get("ambiguous"):
        return LocalTurnPolicy(
            "ambiguous_visual_target_query",
            "low",
            False,
            False,
            False,
            frozenset(),
            direct_execution=True,
        )
    if visual_location_request and not visual_location_request.get("requires_discovery"):
        return LocalTurnPolicy(
            "session_visual_location_query",
            "low",
            False,
            False,
            False,
            frozenset({"ui_screenshot"}),
            direct_execution=True,
            execution_grants=frozenset({"ui_screenshot"}),
        )

    # Arbitrary current-case objects, user-created rows, plug-in controls,
    # object subparts, combinations, and nonexistent names all enter the same
    # open discovery path.  The model may inspect the browser-published live
    # catalog and capture exact returned IDs; it may not mutate the UI or
    # substitute a different object when discovery returns no match.
    if (
        visual_location_request
        and visual_location_request.get("requires_discovery")
        and not is_ui_control_location_question(text)
    ):
        return LocalTurnPolicy(
            "session_visual_discovery_query",
            "low",
            False,
            False,
            False,
            VISUAL_DISCOVERY_TOOLS,
        )

    # An unknown control still needs live UI capability discovery.  Keep the
    # request read-only and let the LLM use ui_inspector followed by a
    # structured ui_screenshot plan; the browser remains the only source of
    # coordinates and annotations.
    if is_ui_control_location_question(text):
        return LocalTurnPolicy(
            "ui_control_location_query",
            "low",
            False,
            False,
            False,
            UI_TOOLS,
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

    # A full clinical-planning request owns the turn before the generic UI
    # capability resolver. The live Data Tree catalogue deliberately exposes
    # context actions (including Rename) for many nodes; letting that
    # catalogue run first can mistake incidental words such as "CT" and
    # "execute" for a node action and prevent the planning workflow from ever
    # receiving its execution grants.
    planning = _contains_any(lower, (
        "\u6267\u884c\u89c4\u5212", "\u5f00\u59cb\u89c4\u5212", "\u91cd\u65b0\u89c4\u5212", "\u7c92\u5b50\u690d\u5165\u89c4\u5212", "\u6cbb\u7597\u8ba1\u5212",
        "\u6267\u884c\u653e\u5c04\u6027\u7c92\u5b50\u690d\u5165\u89c4\u5212",
        "\u653e\u5c04\u6027\u7c92\u5b50\u690d\u5165\u89c4\u5212",
        "planning_pipeline", "brachytherapy plan", "treatment plan", "replan",
    ))
    if planning:
        if not _is_canonical_execution_command(text, operation="planning"):
            return _semantic_action_policy(complexity="high", review=True)
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
    # Imperative UI mutations are resolved against the live capability
    # catalogue after domain-specific clinical/report actions have had the
    # first opportunity to claim their own workflow.  This ordering is
    # intentional: ``重新生成报告`` remains report generation, while
    # ``点击报告模板`` or ``将 OAR 设为半透明`` is handled by the generic
    # capability-driven UI route.  The resolver uses mounted control/action
    # metadata and semantic properties, not a sentence whitelist.
    ui_operation = resolve_ui_operation_request(text, ui_state=ui_state)
    if ui_operation:
        actions = ui_operation.get("actions") or []
        confidence = float(ui_operation.get("confidence") or 0.0)
        if actions and not ui_operation.get("ambiguous") and confidence >= 0.75:
            return LocalTurnPolicy(
                "ui_operation",
                "low",
                False,
                False,
                False,
                frozenset({"ui_controller"}),
                direct_execution=True,
                execution_grants=frozenset({"ui_controller"}),
                ui_operation=ui_operation,
            )
        # An unresolved capability must not pre-empt a known domain route or
        # be presented as a successful UI action.  The normal UI branch below
        # grants inspector/controller access when the text contains a real UI
        # surface; otherwise the ordinary semantic route remains available.

    # A request to view a persisted Session artifact is not a new screenshot,
    # a viewer mutation, or a knowledge lookup. Keep it out of the expensive
    # router and let the Session-content bridge resolve real stored data.
    if resolve_session_content_target(text):
        if _requires_semantic_resolution(text) or not canonical_resource_read(text):
            return _semantic_action_policy(complexity="medium", review=False)
        return LocalTurnPolicy(
            "session_content_query",
            "low",
            False,
            False,
            False,
            frozenset(),
        )

    # An explicit "update everything" command was already resolved above; the
    # remaining object-specific branches below must not re-capture it.

    # A report noun without a canonical operation is not permission to open
    # it. Keep clear/edit/export/help requests on the primary semantic route,
    # with the real controller/inspector capabilities and no execution grant.
    if re.search(r"\breports?\b|报告", lower):
        return _semantic_action_policy(complexity="medium", review=False)

    if is_current_oar_count_query(text):
        return LocalTurnPolicy(
            "current_oar_query",
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
    clinical_advice = _contains_any(lower, (
        "临床", "指南", "处方剂量", "oar", "d90", "v100", "v150", "v200",
        "剂量限值", "治疗适应证", "clinical", "guideline", "prescription dose",
    ))
    ui = _contains_any(lower, (
        "viewer", "切片", "窗口", "放大", "缩小", "显示", "隐藏", "透明度",
        "颜色", "截图", "调节", "设置", "切换", "拖拽", "3d", "2d",
        "viewer", "slice", "zoom", "show", "hide", "opacity", "screenshot",
        "set", "adjust", "toggle", "drag", "button", "control", "menu", "form", "input",
        "select", "slider", "tab", "按钮", "控件", "菜单", "表单", "输入框", "选择器", "滑块", "标签页",
        # Monitor/training-mode control is a UI command (start/stop live
        # planning monitoring), not a clinical execution or knowledge query.
        # Without these keywords a request like "请停止monitor" fell through
        # to the generic knowledge_query intent, whose tool set excludes
        # ui_controller, so the LLM answered "no monitor is running" instead
        # of actually stopping it.
        "monitor", "training mode", "start monitoring", "stop monitoring",
        "停止监测", "开始监测", "结束监测", "停止监控", "监测",
    ))
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


def classify_local_turn(
    message: str,
    pending_tumor_site: bool = False,
    conversation: Optional[Iterable[object]] = None,
    ui_state: Optional[Mapping[str, Any]] = None,
) -> LocalTurnPolicy:
    """One acceptance boundary shared by plain, trace and streaming chat.

    Lexical candidates are hints, not permission. In particular an action plan
    can trigger direct execution even if direct_execution=False, so grants and
    plans must be checked as well. Semantic fallback must drop *all* of them.
    """
    candidate = _classify_local_candidate(
        message, pending_tumor_site, conversation, ui_state,
    )
    if candidate.intent == "small_talk" and not re.fullmatch(
        r"(?:你好|您好|嗨|哈喽|早上好|下午好|晚上好|谢谢|感谢|"
        r"hi|hello|hey|good morning|good afternoon|good evening|thanks|thank you|"
        r"(?:请)?介绍自己|你是谁|你能做什么|你可以做什么|使用说明|"
        r"introduce yourself|who are you|what can you do|how do i use (?:this|brachybot))",
        str(message or "").strip().lower().strip("!?.,，。！？ "),
    ):
        return replace(_semantic_action_policy(review=False),
                       routing_source="primary_semantic", candidate_intent=candidate.intent,
                       routing_reason="greeting_is_only_part_of_request")
    bypasses_semantics = bool(
        candidate.direct_execution or candidate.execution_grants
        or candidate.workflow_grants or candidate.action_plan
    )
    if bypasses_semantics and not shortcut_supported(
        message, candidate, pending_tumor_site=pending_tumor_site, ui_state=ui_state,
    ):
        return replace(
            _semantic_action_policy(
                complexity=candidate.complexity, review=candidate.requires_review,
            ),
            routing_source="primary_semantic",
            routing_reason="whole_request_contract_not_satisfied",
            candidate_intent=candidate.intent,
        )
    # Topic words may guide the prompt but cannot hide unrelated capabilities
    # from the primary model. No pregrants are added by broadening schemas.
    if candidate.intent in {"knowledge_query", "clinical_knowledge", "external_project_query", "ui_control"}:
        return replace(candidate, allow_tools=frozenset(
                           set(candidate.allow_tools or ()) | set(UI_TOOLS)
                           | {"case_memory", "plan_comparator"}),
                       routing_source="primary_semantic", candidate_intent=candidate.intent,
                       routing_reason="topic_hint_does_not_restrict_capabilities")
    return replace(candidate, routing_source="whole_request_contract" if bypasses_semantics else "local_read_or_semantic",
                   candidate_intent=candidate.intent)


def filter_tool_schemas(tools, policy: Optional[LocalTurnPolicy]):
    """Keep only tools permitted by the local policy and current registry."""
    if not policy or policy.allow_tools is None:
        return tools
    allowed = policy.allow_tools
    return [
        item for item in (tools or [])
        if item.get("function", {}).get("name") in allowed
    ]
