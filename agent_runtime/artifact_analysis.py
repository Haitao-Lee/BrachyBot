"""Artifact-analysis request resolution and read-only fact packets.

An analysis request ("分析导板特点", "analyze the guide characteristics") is a
discourse act over an already-produced artifact.  It is read-only: it must
never restart a workflow, never ask the user to confirm a regeneration, and
never degrade into a presentation-only reply.  This module resolves which
artifact is being analyzed (including short follow-ups such as "分析啊" that
inherit the target from conversation), classifies whether the request is a
simple single-artifact analysis (fast grounded answer) or a complex one
(cross-artifact comparison, standards question -> primary LLM with read-only
tools), and packages the artifact's characteristics as bounded facts.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Mapping, Optional

# Analysis verbs request interpretation of existing data, not new work.
_ANALYSIS_VERBS_RE = re.compile(
    r"(?:\u5206\u6790|\u8bc4\u4f30|\u8bc4\u4ef7|\u89e3\u8bfb|\u89c4\u7eb3|\u603b\u7ed3|\u68b3\u7406|"
    r"\u5bf9\u6bd4|\u6bd4\u8f83|\u5ba1\u89c6|\u68c0\u67e5|\u70b9\u8bc4|\u590d\u6838|"
    r"\u8bb2\u89e3|\u4ecb\u7ecd|\u63cf\u8ff0|\u8bf4\u660e|\u89e3\u91ca|"
    r"\b(?:analy[sz]|assess|evaluat|interpret|summariz|compar|review|characteri[sz]|"
    r"explain|describ|discuss)\w*)",
    re.IGNORECASE,
)

# "特点/特征/情况/质量" style aspect nouns strengthen the analysis reading.
_ASPECT_NOUNS_RE = re.compile(
    r"(?:\u7279\u70b9|\u7279\u5f81|\u60c5\u51b5|\u8d28\u91cf|\u8868\u73b0|\u6982\u51b5|\u7ed3\u679c|"
    r"\u4f18\u7f3a\u70b9|\u95ee\u9898|\u98ce\u9669|\u5339\u914d|"
    r"\b(?:characteristic|feature|quality|performance|overview|finding|risk|match\w*)\b)",
    re.IGNORECASE,
)

# Object families the analysis can target.  Ordered most-specific first.
_ARTIFACT_FAMILIES = (
    ("surgical_guide", re.compile(
        r"(?:\u624b\u672f\u5bfc\u677f|\u7a7f\u523a\u5bfc\u677f|\u5bfc\u677f|"
        r"surgical\s+guide|puncture\s+guide|guide\s+mesh|guide\s+stl|\bguides?\b)",
        re.IGNORECASE,
    )),
    ("seeds_needles", re.compile(
        r"(?:\u7c92\u5b50|\u79cd\u5b50|\u9488\u9053|\u5bfc\u9488|seed|needle)",
        re.IGNORECASE,
    )),
    ("tumor", re.compile(
        r"(?:\u80bf\u7624|\u75c5\u7076|\u80bf\u5757|\u9776\u533a|tumou?r|lesion|ctv)",
        re.IGNORECASE,
    )),
    ("dose", re.compile(
        r"(?:\u5242\u91cf|dvh|dose)",
        re.IGNORECASE,
    )),
    ("planning", re.compile(
        r"(?:\u89c4\u5212|\u8ba1\u5212|\u65b9\u6848|planning|treatment\s+plan|\bplans?\b)",
        re.IGNORECASE,
    )),
    ("segmentation", re.compile(
        r"(?:\u5206\u5272|\u52fe\u753b|\u63a9\u819c|\u8f6e\u5ed3|segmentation|segment|mask|oar|"
        r"\u5371\u53ca\u5668\u5b98|\u5668\u5b98)",
        re.IGNORECASE,
    )),
    ("report", re.compile(
        r"(?:\u62a5\u544a|report)",
        re.IGNORECASE,
    )),
)

# Feature/how-to questions ("explain how to generate the guide", "解释这个功能
# 怎么用") are procedural knowledge questions, not artifact analysis.
_PROCEDURAL_RE = re.compile(
    r"(?:\u5982\u4f55|\u600e\u4e48|\u600e\u6837|\u4e3a\u4f55|\u4e3a\u4ec0\u4e48|\u610f\u601d|"
    r"\u529f\u80fd|\u6309\u94ae|\u7528\u6cd5|\u64cd\u4f5c|\u754c\u9762|\u83dc\u5355|\u6b65\u9aa4|\u6d41\u7a0b|"
    r"how\s+to|how\s+do|how\s+can|why|what\s+does|what\s+is\s+the\s+(?:use|purpose)|"
    r"feature|button|menu|usage|workflow|procedure)",
    re.IGNORECASE,
)

# A generation verb inside an infinitive/procedure frame is not a mutation
# command, but it also means the user is asking about the procedure rather
# than asking us to analyze current data.
_PROCEDURAL_GENERATION_RE = re.compile(
    r"(?:\u5982\u4f55|\u600e\u4e48|\u600e\u6837|how\s+to|how\s+(?:do|can)\s+you)"
    r".{0,20}(?:\u751f\u6210|\u5236\u4f5c|\u521b\u5efa|\u66f4\u65b0|\u91cd\u5efa|generate|create|build|rebuild|update)",
    re.IGNORECASE,
)

# Positive mutation verbs: their presence (un-negated, in command position)
# turns the request into a compound action, not a pure analysis.
_MUTATION_VERBS_RE = re.compile(
    r"(?:\u751f\u6210|\u91cd\u65b0\u751f\u6210|\u518d\u751f\u6210|\u5236\u4f5c|\u521b\u5efa|\u5efa\u7acb|"
    r"\u66f4\u65b0|\u91cd\u5efa|\u91cd\u505a|\u8986\u76d6|\u5bfc\u51fa|\u6267\u884c|\u8fd0\u884c|\u5f00\u59cb|"
    r"\u89c4\u5212|\u5206\u5272|\u5212\u5206|"
    r"regenerate|re-?generate|generate|create|build|rebuild|update|refresh|overwrite|export|"
    r"run|execute|perform|start|replan|segment|delineate)",
    re.IGNORECASE,
)

# Inherited follow-ups: a bare analysis imperative with no object.
_FOLLOWUP_ONLY_RE = re.compile(
    r"^(?:\u8bf7)?(?:\u5e2e\u6211|\u8bf7|\u9ebb\u70e6)?\s*"
    r"(?:\u518d)?(?:\u597d\u597d)?"
    r"(?:\u5206\u6790|\u8bc4\u4f30|\u8bc4\u4ef7|\u89e3\u8bfb|\u603b\u7ed3|\u5bf9\u6bd4|\u6bd4\u8f83|"
    r"\u8bb2\u89e3|\u4ecb\u7ecd|\u63cf\u8ff0|\u8bf4\u660e|\u89e3\u91ca)"
    r"(?:\u4e00\u4e0b|\u4e00\u904d|\u4e00\u756a|\u4e0b|\u5427|\u554a|\u5462|\u4e00\u4e0b\u5427)?\s*[\uFF01\uFF1F!?\s]*$",
    re.IGNORECASE,
)

# Cross-artifact or standards questions need the primary LLM and evidence
# retrieval rather than a single-artifact fact packet.
_COMPLEX_MARKERS_RE = re.compile(
    r"(?:\u5339\u914d|\u7b26\u5408|\u6807\u51c6|\u6307\u5357|\u9650\u503c|\u89c4\u8303|\u8010\u53d7|"
    r"\u6587\u732e|\u8bc1\u636e|\u53c2\u8003|"
    r"match\w*|complian\w*|standard|guideline|constraint|tolerance|limit|reference|evidence|literature)",
    re.IGNORECASE,
)

# Requests that explicitly ask to open, show, or capture visual evidence need
# the presentation/visual route (hidden multimodal child), not a fact packet.
_VISUAL_EVIDENCE_RE = re.compile(
    r"(?:\u6253\u5f00|\u663e\u793a|\u5c55\u793a|\u5448\u73b0|\u67e5\u770b|\u770b\u770b|\u770b\u4e00\u770b|"
    r"\u622a\u5c4f|\u622a\u56fe|\u5708\u51fa|\u6807\u6ce8|\u6307\u51fa|"
    r"\bopen\b|\bshow\b|\bview\b|\bdisplay\b|\bcapture\b|\bscreenshots?\b|\blook\s+at\b|\bmark\b)",
    re.IGNORECASE,
)

# Location/size interrogatives want a find-or-measure answer from the image or
# segmentation pipeline ("肿瘤在哪，有多大"), not a characteristics discussion.
_LOCATION_SIZE_RE = re.compile(
    r"(?:\u5728\u54ea|\u5728\u54ea\u91cc|\u4f4d\u4e8e\u54ea|\u4f55\u5904|\u54ea\u4e2a\u4f4d\u7f6e|"
    r"\u591a\u5927|\u591a\u5c0f|\u5c3a\u5bf8|\u591a\u5c11\u6beb\u7c73|"
    r"\bwhere(?:\s+is|\s+are)?\b|\bhow\s+big\b|\bsize\s+of\b|\bdimension)",
    re.IGNORECASE,
)

# Read-only tool surface for complex analysis turns.  Mutating clinical tools
# are deliberately absent so an analysis can never restart a workflow.
ANALYSIS_READ_TOOLS = frozenset({
    "query_metrics",
    "dvh_curve",
    "plan_quality_scorer",
    "oar_constraint_checker",
    "safety_validator",
    "plan_comparator",
    "case_memory",
    "clinical_kb",
    "surgical_guide",
    "ui_content",
    "ui_screenshot",
    "ui_inspector",
    "ui_annotate",
    "doc_reader",
    "web_search",
    "web_fetch",
    "web_access",
    "ctv_model_catalog",
})


def _normalized(message: Any) -> str:
    return re.sub(r"\s+", " ", str(message or "").strip().lower())


def _iter_user_texts(conversation: Optional[Iterable[object]]) -> Iterable[str]:
    if not conversation:
        return
    try:
        items = list(conversation)
    except TypeError:
        return
    for item in reversed(items[-12:]):
        if not isinstance(item, Mapping):
            continue
        if str(item.get("role") or "").lower() != "user":
            continue
        content = item.get("content", item.get("message", ""))
        if isinstance(content, (list, tuple)):
            content = " ".join(
                str(part.get("text") or part.get("content") or "")
                if isinstance(part, Mapping) else str(part or "")
                for part in content
            )
        text = str(content or "").strip()
        if text and not text.startswith("[internal:"):
            yield text


def _has_positive_mutation(text: str) -> bool:
    """Return whether the utterance commands a write in its own clause.

    The frame requires an imperative-position mutation verb (sentence start or
    after a sequencing connector).  Bare noun phrases such as ``当前规划`` or
    ``分割结果`` reuse those words and must stay analysis targets, while
    ``分析一下导板然后重新生成`` carries a real second clause and becomes a
    compound action request instead.
    """
    if re.search(
        r"(?:\u4e0d\u8981|\u522b|\u65e0\u9700|\u4e0d\u7528|\u4e0d\u9700\u8981|"
        r"do\s+not|don'?t|no\s+need|without)\s*"
        r"(?:\u751f\u6210|\u91cd\u65b0|\u518d\u751f\u6210|\u6267\u884c|\u8fd0\u884c|generate|run|execute|rebuild)",
        text,
        re.IGNORECASE,
    ):
        return False
    return bool(re.search(
        r"(?:^|[\s,;\uFF0C\uFF1B]|"
        r"\u7136\u540e|\u4e4b\u540e|\u5b8c\u6210\u540e|\u63a5\u7740|\u5e76\u4e14|\u5e76|"
        r"\bthen\b|\band\s+then\b|\bafter\b|\balso\b|\bas\s+well\s+as\b|\band\b)"
        r"\s*(?:\u8bf7|\u5e2e\u6211|\u9ebb\u70e6|please|\bneed\s+to\b)?\s*"
        r"(?:\u91cd\u65b0|\u518d\u6b21|\u518d|\u8986\u76d6|\u5f3a\u884c|\u5ffd\u7565\u73b0\u6709)?\s*"
        r"(?:\u751f\u6210|\u5236\u4f5c|\u521b\u5efa|\u5efa\u7acb|\u66f4\u65b0|\u91cd\u5efa|\u91cd\u505a|"
        r"\u5bfc\u51fa|\u6267\u884c|\u8fd0\u884c|\u5f00\u59cb|\u89c4\u5212|\u5206\u5272|"
        r"generate|create|build|rebuild|update|refresh|overwrite|export|"
        r"run|execute|perform|start|replan|segment|delineate)",
        text,
        re.IGNORECASE,
    ))


def _match_artifact(text: str) -> Optional[str]:
    for family, pattern in _ARTIFACT_FAMILIES:
        if pattern.search(text):
            return family
    return None


def _resolve_inherited_target(
    conversation: Optional[Iterable[object]],
) -> Optional[str]:
    """Resolve the artifact of a bare follow-up from recent user turns."""
    for text in _iter_user_texts(conversation):
        resolved = is_artifact_analysis_request(text, conversation=None)
        if resolved is not None:
            return resolved["artifact"]
        family = _match_artifact(_normalized(text))
        if family:
            return family
    return None


def is_artifact_analysis_request(
    message: Any,
    conversation: Optional[Iterable[object]] = None,
) -> Optional[Dict[str, Any]]:
    """Return the analysis resolution dict for ``message``, or None.

    The dict carries ``artifact`` (family key), ``aspects`` (bool: explicit
    aspect nouns present), ``complex`` (bool: needs the primary LLM), and
    ``source`` (``"explicit"`` or ``"followup"``).
    """
    text = _normalized(message)
    if not text or len(text) > 400:
        return None
    if not _ANALYSIS_VERBS_RE.search(text):
        return None
    if _PROCEDURAL_GENERATION_RE.search(text):
        return None
    if _PROCEDURAL_RE.search(text) and _ASPECT_NOUNS_RE.search(text) is None:
        # "解释这个功能/怎么用" is procedural knowledge, not artifact analysis.
        return None
    if _VISUAL_EVIDENCE_RE.search(text):
        # "打开报告截图并详细解读" needs real visual evidence through the
        # presentation route, not a characteristics fact packet.
        return None
    if _LOCATION_SIZE_RE.search(text):
        # "肿瘤在哪，有多大" is a find/measure question for the image and
        # segmentation pipeline; the semantic path with its completeness
        # review owns it.
        return None

    followup_only = bool(_FOLLOWUP_ONLY_RE.match(text))
    family = _match_artifact(text)
    source = "explicit"
    if family is None:
        if not followup_only:
            return None
        family = _resolve_inherited_target(conversation)
        if family is None:
            return None
        source = "followup"

    if _has_positive_mutation(text):
        # "分析一下导板然后重新生成" is a compound action request; the
        # semantic action-plan path owns it (and its mutation gate).
        return None

    aspects = bool(_ASPECT_NOUNS_RE.search(text))
    families = {
        matched
        for matched, pattern in _ARTIFACT_FAMILIES
        if pattern.search(text)
    }
    complex_request = bool(_COMPLEX_MARKERS_RE.search(text)) or len(families) > 1
    return {
        "artifact": family,
        "aspects": aspects,
        "complex": complex_request,
        "source": source,
    }


def resolve_artifact_analysis_target(
    message: Any,
    conversation: Optional[Iterable[object]] = None,
) -> Optional[str]:
    """Convenience wrapper returning only the artifact family."""
    resolved = is_artifact_analysis_request(message, conversation=conversation)
    return resolved["artifact"] if resolved else None


def is_analysis_shaped(message: Any) -> bool:
    """Return whether the utterance asks for interpretation, not new work.

    Weaker than :func:`is_artifact_analysis_request`: the artifact may be
    absent (a short follow-up such as ``分析啊``) or the request may be a
    general knowledge question.  What matters at the tool-call boundary is
    that no write is commanded, so provider-selected mutations can be
    coerced to their read-only forms.
    """
    text = _normalized(message)
    if not text or len(text) > 400:
        return False
    if not _ANALYSIS_VERBS_RE.search(text):
        return False
    if _PROCEDURAL_GENERATION_RE.search(text):
        return False
    return not _has_positive_mutation(text)


def _bounded(value: Any, limit: int = 64) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, Mapping):
        return {str(k)[:100]: _bounded(v) for k, v in list(value.items())[:limit]}
    if isinstance(value, (list, tuple)):
        return [_bounded(v) for v in value[:32]]
    return str(value)[:500]


def build_guide_characteristics_facts(guide_state: Any) -> Dict[str, Any]:
    """Bounded design/validation characteristics of the puncture guide.

    This is the fact packet behind "分析导板特点".  It exposes the manufacturing
    parameters and mesh-validation record without vertices/faces or other
    unbounded arrays.
    """
    if not isinstance(guide_state, Mapping):
        return {"available": False}
    facts: Dict[str, Any] = {"available": True}
    for key in ("version", "status", "planning_id", "planning_version",
                "source_plan_signature"):
        if guide_state.get(key) is not None:
            facts[key] = _bounded(guide_state.get(key))

    parameters = guide_state.get("parameters")
    facts["parameters"] = _bounded(parameters) if isinstance(parameters, Mapping) else {}

    needle_ids = guide_state.get("selected_needle_ids") or []
    facts["needle_count"] = len(needle_ids) if isinstance(needle_ids, (list, tuple)) else 0

    paths = guide_state.get("needle_paths")
    facts["needle_path_count"] = len(paths) if isinstance(paths, (list, tuple)) else 0

    holes = guide_state.get("auxiliary_holes")
    if isinstance(holes, Mapping):
        facts["auxiliary_holes"] = {
            key: _bounded(value)
            for key, value in holes.items()
            if key not in {"holes", "skipped"}
        }
    else:
        facts["auxiliary_holes"] = {}

    validation = guide_state.get("validation")
    if isinstance(validation, Mapping):
        summary: Dict[str, Any] = {}
        for key in (
            "source_needle_count", "excluded_needle_paths",
            "max_centerline_deviation_mm", "skin_fit",
            "skin_surface_interpolation", "geometry_resolution_mm",
            "requested_geometry_resolution_mm", "bore_quality",
            "needle_spacing", "stage_timings_seconds", "grid_budget",
        ):
            if validation.get(key) is not None:
                summary[key] = _bounded(validation.get(key))
        connectivity = validation.get("plate_connectivity")
        if isinstance(connectivity, Mapping):
            summary["plate_connectivity_single_piece"] = connectivity.get("single_piece")
            summary["plate_connectivity_initial_components"] = connectivity.get(
                "initial_component_count")
            summary["plate_connectivity_bridges"] = connectivity.get("bridge_count")
        sleeve = validation.get("primary_sleeve_support")
        if isinstance(sleeve, Mapping):
            summary["primary_sleeve_support_valid"] = sleeve.get("valid")
        fov = validation.get("finite_fov")
        if isinstance(fov, Mapping):
            summary["finite_fov_truncated_superior"] = fov.get("truncated_superior")
            summary["finite_fov_truncated_inferior"] = fov.get("truncated_inferior")
            summary["all_entries_on_real_skin"] = fov.get("all_entries_on_real_skin")
        facts["validation"] = summary
    else:
        facts["validation"] = {}
    return facts


def coerce_analysis_tool_call(
    tool_name: str,
    params: Mapping[str, Any],
    question: str,
) -> Dict[str, Any]:
    """Rewrite one provider tool call so an analysis turn can never mutate.

    ``surgical_guide`` is forced to its read-only ``analyze`` action (the
    schema default is ``generate``, which is a mutation landmine), and
    ``ui_content`` receives the user's question so its analysis upgrade can
    request real evidence instead of a bare presentation.
    """
    name = str(tool_name or "")
    merged = dict(params or {})
    if name == "surgical_guide":
        merged["action"] = "analyze"
        return merged
    if name == "ui_content":
        if not str(merged.get("question") or "").strip():
            merged["question"] = str(question or "").strip()
        return merged
    return merged
