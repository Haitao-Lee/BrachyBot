"""Deterministic whole-request parsing shared by routing and authorization.

This module is the single place that turns one user utterance into a small
structural record::

    request{target, action, scope, negated, conditional, interrogative,
            quoted, references, objects, goals}

Everything here is pure text/in-memory work.  It never calls a model and it
never touches the network or disk, so it is safe to evaluate on every turn.
The router (``turn_policy``), the lexical boundary (``intent_boundary``) and
the provider boundary (``response_tools``) all consume the same record instead
of each maintaining a slightly different keyword list.

Design rules:

* A topic noun is never an action.  ``target``/``objects`` describe *what* is
  named; ``action``/``goals`` describe *what is asked*.
* Negation, conditions, questions and quoted/cited text do not authorize a
  mutating action.  ``affirmative_command`` and ``unconditional_command``
  express those guarantees explicitly.
* Unknown wording stays on the semantic route.  This module only answers
  structural questions; it does not invent an operation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional, Tuple

__all__ = [
    "ParsedRequest",
    "parse_request",
    "normalize_text",
    "is_interrogative",
    "is_negated",
    "is_conditional",
    "is_quoted",
    "has_reference",
    "is_affirmative_command",
    "is_unconditional_command",
    "canonical_report_mutation",
    "canonical_guide_generation",
    "mutating_execution_authorized",
    "tool_authorization_target",
    "ui_action_is_destructive",
    "ui_action_explicitly_authorized",
    "resolve_reference_target",
    "DESTRUCTIVE_UI_TARGETS",
]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_QUOTE_PAIRS = (
    ('"', '"'), ("'", "'"), ("\u201c", "\u201d"), ("\u2018", "\u2019"),
    ("\u300c", "\u300d"), ("\u300e", "\u300f"), ("`", "`"),
)


def normalize_text(message: object) -> str:
    """Lower-case and collapse whitespace without dropping semantics."""
    text = str(message or "").replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def _clean(text: str) -> str:
    """Normalized text with outer quotes and trailing punctuation removed."""
    text = normalize_text(text)
    text = text.strip(" \t")
    # Strip one layer of symmetric wrapping quotes.
    for left, right in _QUOTE_PAIRS:
        if left != right and text.startswith(left) and text.endswith(right):
            text = text[len(left):-len(right)].strip()
            break
    return text.strip(" \u3002.!！?？,，;；:：、" + "\"'")


# ---------------------------------------------------------------------------
# Structural detectors
# ---------------------------------------------------------------------------

_INTERROGATIVE_END = re.compile(r"[?？吗呢]$")
_INTERROGATIVE_ZH = re.compile(
    r"(?:是不是|有没有|能不能|可不可以|是否|怎么样|如何|怎么|为什么|为何|什么|谁|"
    r"哪里|哪儿|在哪|哪次|哪个|哪一个|"
    r"完成.*[了没]|做了[没吗]|好了[没吗]|生成.*[了没]|分割.*[了没]|规划.*[了没])"
)
_INTERROGATIVE_EN = re.compile(
    r"\b(?:what|which|where|when|why|who|whose|how|is it|are (?:you|there)|"
    r"can (?:you|i)|could|would|should|has (?:it|the)|have (?:you|they)|"
    r"did (?:you|it)|does (?:it|the))\b"
)
_NEGATED_INSPECTION = re.compile(r"(?:不要|别|不准|不许)")


def is_interrogative(message: object) -> bool:
    """Return True when the utterance reads as a question, not a command."""
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    if _INTERROGATIVE_END.search(text.rstrip("!！")):
        return True
    if _INTERROGATIVE_ZH.search(lower) or _INTERROGATIVE_EN.search(lower):
        return True
    # Negation + passive inspection = "don't do anything, just check".
    if _NEGATED_INSPECTION.search(lower) and re.search(
        r"(?:查看|看看|检查|确认|告诉|check|look|inspect)", lower,
    ):
        return True
    return False


_NEGATION_MARKERS = (
    "不要", "别", "不用", "不需要", "无需", "不必", "不能", "不可", "不可以",
    "没有", "取消", "切勿", "禁止", "不允许", "不执行", "不生成", "不重新",
    "别生成", "除了", "除外", "并非", "不是", "没生成", "未生成", "不需要",
    "do not", "don't", "dont", "without", "except", "exclude", "never",
    "no need", "cancel", "not ",
)


def is_negated(message: object) -> bool:
    """Return True when an explicit negation frame is present."""
    text = _clean(message)
    if not text:
        return False
    return any(marker in text for marker in _NEGATION_MARKERS)


_CONDITIONAL_MARKERS = (
    "如果", "假如", "假设", "若", "若是", "要是", "除非", "万一", "一旦",
    "条件", "前提", "在.*情况下",
    "if ", "unless", "suppose", "assuming", "in case",
)


def is_conditional(message: object) -> bool:
    """Return True when the action is guarded by a condition."""
    text = _clean(message)
    if not text:
        return False
    for marker in _CONDITIONAL_MARKERS:
        if marker.startswith("在") and marker.endswith("情况下"):
            if re.search(marker, text):
                return True
        elif marker in text:
            return True
    return False


def _quoted_spans(text: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    for left, right in _QUOTE_PAIRS:
        if left == right:
            parts = text.split(left)
            cursor = 0
            for index in range(1, len(parts) - 1, 2):
                start = cursor + len(parts[index - 1]) + 1
                end = start + len(parts[index])
                spans.append((start, end))
                cursor = end + 1
        else:
            cursor = 0
            while True:
                start = text.find(left, cursor)
                if start < 0:
                    break
                end = text.find(right, start + len(left))
                if end < 0:
                    break
                spans.append((start + len(left), end))
                cursor = end + len(right)
    return spans


def is_quoted(message: object) -> bool:
    """Return True when the whole utterance is wrapped in quote characters."""
    text = normalize_text(message)
    if len(text) < 2:
        return False
    for left, right in _QUOTE_PAIRS:
        if text.startswith(left) and text.endswith(right) and len(text) > len(left) + len(right):
            return True
    return False


_REFERENCE_MARKERS = (
    "它", "这个", "那个", "就它", "照这个", "按这个", "就按它", "同上",
    "上一个", "上一条", "刚才的", "刚才那个", "再来一次", "再来一遍",
    "重做一遍", "again", "same", "this one", "that one", "the last one",
)


def has_reference(message: object) -> bool:
    """Return True when the turn refers to a prior object/action."""
    text = _clean(message)
    if not text:
        return False
    return any(marker in text for marker in _REFERENCE_MARKERS)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

TARGET_ALIASES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("report", (
        "\u62a5\u544a", "report", "reports",
    )),
    ("surgical_guide", (
        "\u624b\u672f\u5bfc\u677f", "\u7a7f\u523a\u5bfc\u677f", "\u624b\u672f\u5200\u677f",
        "\u5bfc\u677f", "surgical guide", "puncture guide", "guide mesh",
        "guide stl", "guide",
    )),
    ("planning", (
        "\u89c4\u5212", "\u8ba1\u5212", "planning", "treatment plan",
        "brachytherapy plan", "replan", "re-plan", "plan",
    )),
    ("ctv", (
        "\u9776\u533a", "\u80bf\u7624", "\u80bf\u5757", "\u75c5\u7076", "ctv",
        "target volume", "tumor", "tumour", "lesion",
    )),
    ("oar", (
        "\u5371\u53ca\u5668\u5b98", "oar", "organs at risk", "organ at risk",
    )),
    ("screenshot", (
        "\u622a\u56fe", "\u622a\u5c4f", "\u56fe\u7247", "screenshot", "capture",
        "screenshot",
    )),
    ("dose", (
        "\u5242\u91cf", "dose", "dvh", "dose-volume histogram",
    )),
    ("structure", (
        "\u7ed3\u6784", "\u5206\u5272", "\u63a9\u819c", "\u5934\u9762", "structure",
        "structures", "segmentation", "mask", "segmentation",
    )),
    ("viewer", (
        "\u67e5\u770b\u5668", "viewer", "3d", "2d",
    )),
)

_ACTION_ALIASES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("clear", (
        "\u6e05\u7a7a", "\u6e05\u9664", "\u5220\u9664", "\u5220\u6389",
        "\u79fb\u9664", "\u91cd\u7f6e", "clear", "delete", "remove",
        "reset", "wipe", "erase",
    )),
    ("export", (
        "\u5bfc\u51fa", "export",
    )),
    ("generate", (
        "\u91cd\u65b0\u751f\u6210", "\u518d\u751f\u6210", "\u751f\u6210", "\u91cd\u5efa",
        "\u91cd\u505a", "\u5236\u4f5c", "\u521b\u5efa", "\u66f4\u65b0", "\u5237\u65b0",
        "\u586b\u5145", "\u8865\u5168", "\u5b8c\u5584", "\u5199", "\u64b0\u5199",
        "generate", "regenerate",
        "re-generate", "rebuild", "create", "update", "refresh", "auto-fill",
        "autofill", "fill", "complete", "make",
    )),
    ("segment", (
        "\u5206\u5272", "\u52fe\u753b", "\u52fe\u52d2", "\u63d0\u53d6", "segment",
        "delineate", "outline", "extract",
    )),
    ("plan", (
        "\u6267\u884c", "\u8fdb\u884c", "\u5f00\u59cb", "\u5236\u5b9a", "\u91cd\u8dd1",
        "\u91cd\u7b97", "\u91cd\u65b0\u89c4\u5212", "run", "execute", "start",
        "perform", "replan", "rerun",
    )),
    ("display", (
        "\u67e5\u770b", "\u770b\u770b", "\u770b\u4e00\u4e0b", "\u663e\u793a",
        "\u5c55\u793a", "\u5448\u73b0", "\u6253\u5f00", "\u67e5\u9605", "show",
        "view", "display", "present", "load", "open", "see",
    )),
    ("annotate", (
        "\u5708\u51fa", "\u6807\u51fa", "\u6807\u6ce8", "\u9ad8\u4eae", "circle",
        "annotate", "highlight", "mark",
    )),
)

_WRITE_ACTIONS = frozenset({"generate", "clear", "export", "segment", "plan", "annotate"})

# Targets that a command-position verb can address with a mutating effect.
_WRITABLE_TARGETS = frozenset({
    "report", "surgical_guide", "planning", "ctv", "oar", "dose", "structure",
})

# Tool name -> (target family, action family) for provider authorization.
_TOOL_MUTATION_GOAL = {
    "report_auto_fill": ("report", "generate"),
    "report_generator": ("report", "generate"),
    "surgical_guide": ("surgical_guide", "generate"),
    "planning_pipeline": ("planning", "plan"),
    "ctv_segmentation": ("ctv", "segment"),
    "oar_segmentation": ("oar", "segment"),
    "biomedparse_segmentation": ("structure", "segment"),
    "dose_recompute": ("dose", "plan"),
    "dose_engine": ("dose", "plan"),
    "dose_evaluation": ("dose", "plan"),
    "plan_refinement": ("planning", "plan"),
    "trajectory_init": ("planning", "plan"),
    "trajectory_refine": ("planning", "plan"),
    "trajectory_planning": ("planning", "plan"),
    "seed_planning": ("planning", "plan"),
    "seed_planning_rule_based": ("planning", "plan"),
    "seed_planning_rl": ("planning", "plan"),
}

DESTRUCTIVE_UI_TARGETS = frozenset({
    "report.clear",
    "session.delete",
    "session.clear_all",
    "browser_cache.clear",
    "plan.reset",
    "manual.plan.reset",
})

_DESTRUCTIVE_VERBS = (
    "\u6e05\u7a7a", "\u6e05\u9664", "\u5220\u9664", "\u5220\u6389",
    "\u91cd\u7f6e", "clear", "delete", "remove", "reset", "wipe",
)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _find_targets(text: str) -> List[str]:
    found: List[str] = []
    for target, aliases in TARGET_ALIASES:
        if any(alias in text for alias in aliases):
            if target not in found:
                found.append(target)
    return found


def _find_actions(text: str) -> List[str]:
    found: List[str] = []
    for action, aliases in _ACTION_ALIASES:
        if any(alias in text for alias in aliases):
            found.append(action)
    return found


def _first_object_by_position(text: str) -> str:
    """Return the target noun that appears earliest in the utterance."""
    best = ""
    best_index = len(text) + 1
    for target, aliases in TARGET_ALIASES:
        for alias in aliases:
            index = text.find(alias)
            if index >= 0 and index < best_index:
                best_index = index
                best = target
    return best


def _primary_action(text: str, actions: List[str]) -> str:
    """Pick the command-position action rather than any mentioned verb."""
    if not actions:
        return ""
    command_verbs = (
        "\u751f\u6210", "\u91cd\u65b0\u751f\u6210", "\u518d\u751f\u6210", "\u91cd\u5efa",
        "\u91cd\u505a", "\u5236\u4f5c", "\u521b\u5efa", "\u66f4\u65b0", "\u5237\u65b0",
        "\u586b\u5145", "\u8865\u5168", "\u5b8c\u5584", "\u6e05\u7a7a", "\u6e05\u9664",
        "\u5220\u9664", "\u5220\u6389", "\u5bfc\u51fa", "\u5206\u5272", "\u52fe\u753b",
        "\u6267\u884c", "\u5f00\u59cb", "\u8fdb\u884c", "\u91cd\u7f6e", "\u5199", "\u64b0\u5199",
        "generate", "regenerate", "rebuild", "create", "update", "refresh",
        "clear", "delete", "remove", "export", "segment", "plan", "run",
        "execute", "start", "reset",
    )
    for action, aliases in _ACTION_ALIASES:
        if action not in actions:
            continue
        for alias in aliases:
            if alias not in command_verbs:
                continue
            if alias in text:
                return action
    return actions[0]


def _clauses(text: str) -> List[str]:
    return [part for part in re.split(r"[,;\uff0c\uff1b\u3002]|(?:\s+(?:and then|then)\s+)", text) if part.strip()]


def _ordered_goals(text: str, objects: List[str], actions: List[str]) -> List[Tuple[str, str]]:
    """Return the ordered (target, action) goals named by the turn."""
    goals: List[Tuple[str, str]] = []
    for clause in _clauses(text):
        clause_targets = [t for t in _find_targets(clause) if t in objects] or _find_targets(clause)
        clause_targets = sorted(
            clause_targets,
            key=lambda target: min(
                (clause.find(alias) for alias in dict(TARGET_ALIASES).get(target, ()) if clause.find(alias) >= 0),
                default=len(clause),
            ),
        )
        clause_actions = _find_actions(clause)
        if not clause_targets or not clause_actions:
            continue
        action = _primary_action(clause, clause_actions)
        for target in clause_targets:
            pair = (target, action)
            if pair not in goals:
                goals.append(pair)
    if not goals and objects and actions:
        goals.append((_primary_object(text, objects), _primary_action(text, actions)))
    return goals


def _primary_object(text: str, objects: List[str]) -> str:
    positioned = _first_object_by_position(text)
    if positioned and positioned in objects:
        return positioned
    return objects[0] if objects else ""


# ---------------------------------------------------------------------------
# Parsed record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedRequest:
    """Structural view of one user utterance (no model, no I/O)."""

    raw: str
    text: str
    target: str = ""
    action: str = ""
    scope: str = "single"
    negated: bool = False
    conditional: bool = False
    interrogative: bool = False
    quoted: bool = False
    references: Tuple[str, ...] = ()
    objects: Tuple[str, ...] = ()
    actions: Tuple[str, ...] = ()
    goals: Tuple[Tuple[str, str], ...] = ()
    reason: str = ""

    @property
    def has_write_intent(self) -> bool:
        if self.action in _WRITE_ACTIONS and self.target:
            return True
        if self.action == "plan" and self.target in _WRITABLE_TARGETS:
            return True
        return any(action in _WRITE_ACTIONS and target for target, action in self.goals)

    @property
    def affirmative_command(self) -> bool:
        """A positive command; negation/questions/quotes never authorize."""
        return self.has_write_intent and not (
            self.negated or self.interrogative or self.quoted
        )

    @property
    def unconditional_command(self) -> bool:
        return self.affirmative_command and not self.conditional

    @property
    def compound_write(self) -> bool:
        """True when two or more distinct write goals are requested.

        Two object nouns inside one noun phrase (``剂量报告``) are one goal;
        two clauses, or a conjunction joining two writable objects
        (``导板和报告``), are a compound request.
        """
        write_clauses = 0
        for clause in _clauses(self.text):
            has_target = any(
                target in _WRITABLE_TARGETS for target in _find_targets(clause)
            )
            has_action = any(action in _WRITE_ACTIONS for action in _find_actions(clause))
            if has_target and has_action:
                write_clauses += 1
        if write_clauses >= 2:
            return True
        if re.search(r"[\u548c\u4e0e\u53ca]", self.text):
            targets = [
                target for target in self.objects if target in _WRITABLE_TARGETS
            ]
            if len(targets) >= 2:
                return True
        return False

    @property
    def primary_goal(self) -> Optional[Tuple[str, str]]:
        if self.goals:
            return self.goals[0]
        if self.target and self.action:
            return (self.target, self.action)
        return None

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "action": self.action,
            "scope": self.scope,
            "negated": self.negated,
            "conditional": self.conditional,
            "interrogative": self.interrogative,
            "quoted": self.quoted,
            "references": list(self.references),
            "objects": list(self.objects),
            "actions": list(self.actions),
            "goals": [list(goal) for goal in self.goals],
            "affirmative": self.affirmative_command,
            "unconditional": self.unconditional_command,
        }


def parse_request(message: object) -> ParsedRequest:
    """Parse one utterance into its structural record."""
    raw = str(message or "")
    text = _clean(raw)
    if not text:
        return ParsedRequest(raw=raw, text="", reason="empty")

    objects = _find_targets(text)
    actions = _find_actions(text)
    target = _first_object_by_position(text) or (objects[0] if objects else "")
    action = _primary_action(text, actions)
    goals = _ordered_goals(text, objects, actions)
    # A generation verb used attributively (``重新生成的报告``) describes an
    # existing artifact rather than commanding a new one.
    if action == "generate" and (
        _ATTRIBUTIVE_REPORT.search(text) or _ATTRIBUTIVE_GUIDE.search(text)
    ):
        if not (canonical_report_mutation(text) or canonical_guide_generation(text)):
            action = ""
            actions = [item for item in actions if item != "generate"]
            goals = [goal for goal in goals if goal[1] != "generate"]
    references = tuple(
        marker for marker in _REFERENCE_MARKERS if marker in text
    )
    return ParsedRequest(
        raw=raw,
        text=text,
        target=target,
        action=action,
        scope="compound" if len(goals) > 1 else "single",
        negated=is_negated(text),
        conditional=is_conditional(text),
        interrogative=is_interrogative(raw),
        quoted=is_quoted(raw),
        references=references,
        objects=tuple(objects),
        actions=tuple(actions),
        goals=tuple(goals),
    )


# ---------------------------------------------------------------------------
# Command contracts
# ---------------------------------------------------------------------------

_REPORT_QUALIFIER = (
    r"(?:当前|完整|整个|本次|这个|一份|新的|最新|最终|详细|简要|标准|正式|"
    r"手术|穿刺|治疗|剂量|计划|规划|临床|术后|术中|病例|患者|分析|解读|"
    r"评估|比较|复核|验证|校验|核对|术前的|术中|诊断|结构化|"
    r"的|\s)*"
)
_EN_REPORT_QUALIFIER = (
    r"(?:(?:the|current|full|complete|final|surgical|treatment|dose|plan|"
    r"planning|clinical|patient|analysis|diagnostic|structured|validated)\s+)*"
)
_REPORT_GEN_VERB = r"(?:重新|再次|再)?(?:生成|更新|刷新|重做|重建|制作|创建|填充|补全|完善|写|撰写)"
_PREFIX = r"(?:(?:请问|请|麻烦|帮我|给我|我想|我要|你可以|可以|能否|能不能)\s*)*"
_EN_PREFIX = r"(?:please\s+)?"
_EN_REPORT_GEN_VERB = (
    r"(?:generate|regenerate|re-generate|rebuild|create|update|refresh|"
    r"auto-fill|autofill|fill|complete)"
)

_ATTRIBUTIVE_REPORT = re.compile(
    r"(?:生成|更新|重做|重建|制作|创建|填充|补全|完善|generate|regenerate|"
    r"rebuild|create|update|refresh)\s*(?:的|出来的|得到的|好的|完的)\s*"
    r"(?:[^\s]{0,8})?(?:报告|report)",
    re.IGNORECASE,
)

_ATTRIBUTIVE_GUIDE = re.compile(
    r"(?:已生成|已经生成|生成|更新|重做|重建|制作|创建|刷新|generate|regenerate|"
    r"rebuild|create|update|refresh)\s*(?:的|出来的|得到的|好的|完的)\s*"
    r"(?:[^\s,，；;!?？。]{0,8})?(?:手术|穿刺)?导板",
    re.IGNORECASE,
)


def canonical_report_mutation(message: object) -> bool:
    """Whole-utterance report *command*: the report is the object of the verb.

    Qualifiers such as ``分析``/``评估`` are part of the object name, not a
    discourse marker that changes the requested action.  An attributive form
    such as ``重新生成的报告`` describes an existing artifact and is not a
    command.
    """
    text = _clean(message)
    if not text or len(text) > 240:
        return False
    if is_interrogative(message) or is_negated(text) or is_conditional(text) or is_quoted(message):
        return False
    if _ATTRIBUTIVE_REPORT.search(text):
        return False
    zh = bool(re.fullmatch(
        _PREFIX + _REPORT_GEN_VERB + _REPORT_QUALIFIER + r"报告(?:吗|吧)?",
        text,
    ))
    en = bool(re.fullmatch(
        _EN_PREFIX + _EN_REPORT_GEN_VERB + r"\s+" + _EN_REPORT_QUALIFIER + r"report",
        text,
    ))
    return zh or en


_REPORT_ATTRIBUTION_STOP = (
    "他让我", "她让我", "日志", "记录", "报告说", "上面写", "消息说",
    "instructions", "the log", "it says", "i mean", "correction",
)


def _has_citation_frame(text: str) -> bool:
    return any(marker in text for marker in _REPORT_ATTRIBUTION_STOP)


_GUIDE_GEN_VERB = r"(?:重新|再次|再)?(?:生成|重建|重做|制作|创建|更新|刷新)"
_GUIDE_OBJECT = r"(?:手术|穿刺)?导板"


def canonical_guide_generation(message: object) -> bool:
    """Whole-utterance guide *command* (generation, not a location question)."""
    text = _clean(message)
    if not text or len(text) > 240:
        return False
    if is_interrogative(message) or is_negated(text) or is_conditional(text) or is_quoted(message):
        return False
    zh = bool(re.fullmatch(
        _PREFIX + _GUIDE_GEN_VERB + r"(?:一个|一份|新的|当前)?\s*" + _GUIDE_OBJECT,
        text,
    ))
    en = bool(re.fullmatch(
        _EN_PREFIX + r"(?:generate|regenerate|re-generate|rebuild|create|update|refresh|make)"
        r"\s+(?:the\s+)?(?:surgical |puncture )?guide",
        text,
    ))
    return zh or en


_COMPOUND_CONNECTORS = re.compile(
    r"(?:然后|之后|之前|先|再(?!次)|同时|以及|并且|并(?=[\u4e00-\u9fff])|完成后|"
    r"\b(?:then|after|before|and then|followed by|as well as|also|next)\b)"
)
_GUIDE_NOUNS = ("\u5bfc\u677f", "surgical guide", "puncture guide", "guide mesh", "guide stl")
_PLANNING_NOUNS = ("\u89c4\u5212", "\u8ba1\u5212", "planning", "treatment plan", "replan")


def _is_compound(text: str) -> bool:
    if _COMPOUND_CONNECTORS.search(text):
        return True
    clauses = _clauses(text)
    with_goals = [c for c in clauses if _find_targets(c) and _find_actions(c)]
    return len(with_goals) > 1


def unambiguous_report_generation(message: object) -> bool:
    """Whole-turn report mutation with no second business object in play."""
    text = _clean(message)
    if not text or len(text) > 240:
        return False
    if not canonical_report_mutation(text):
        return False
    if any(noun in text for noun in _GUIDE_NOUNS):
        return False
    if _has_citation_frame(text):
        return False
    return True


def unambiguous_guide_generation(message: object) -> bool:
    """Whole-turn guide mutation with no report/planning object in play."""
    text = _clean(message)
    if not text or len(text) > 240:
        return False
    if not canonical_guide_generation(text):
        return False
    if "\u62a5\u544a" in text or "report" in text:
        return False
    if any(noun in text for noun in _PLANNING_NOUNS):
        return False
    return True


# ---------------------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------------------

def is_affirmative_command(message: object) -> bool:
    """True when the utterance positively commands a write action.

    Conditions are not rejected here (they are recorded separately) but a
    conditional turn is *not* treated as an unconditional authorization by
    :func:`mutating_execution_authorized`.
    """
    return parse_request(message).affirmative_command


def is_unconditional_command(message: object) -> bool:
    return parse_request(message).unconditional_command


def tool_authorization_target(tool_name: str) -> Optional[Tuple[str, str]]:
    return _TOOL_MUTATION_GOAL.get(str(tool_name or ""))


def mutating_execution_authorized(message: object, tool_name: str) -> bool:
    """Second-line check before a provider-selected mutation executes.

    The provider only gets a mutating call when the current user utterance is a
    positive command whose parsed goal matches the tool.  Questions, negations,
    quoted text and purely conditional turns are rejected here even if the
    routing layer already passed a grant.
    """
    goal = tool_authorization_target(tool_name)
    if goal is None:
        return True
    parsed = parse_request(message)
    if parsed.negated or parsed.interrogative or parsed.quoted:
        return False
    if parsed.conditional and not parsed.unconditional_command:
        return False
    expected_target, expected_action = goal
    if expected_target not in parsed.objects and parsed.target != expected_target:
        # A planning command may legitimately imply its segmentation inputs.
        if not (
            expected_target in {"ctv", "oar", "structure"}
            and parsed.target == "planning"
        ):
            return False
    if expected_action == "generate":
        return parsed.action in {"generate", "create", "update"} or "generate" in parsed.actions
    if expected_action == "plan":
        return parsed.action in {"plan", "generate"} or "plan" in parsed.actions
    if expected_action == "segment":
        return parsed.action in {"segment", "plan", "generate"} or "segment" in parsed.actions
    return True


def ui_action_is_destructive(target: object) -> bool:
    return str(target or "") in DESTRUCTIVE_UI_TARGETS


def ui_action_explicitly_authorized(message: object, target: object) -> bool:
    """Destructive UI targets require an explicit clear/delete command."""
    target = str(target or "")
    if not ui_action_is_destructive(target):
        return True
    parsed = parse_request(message)
    if parsed.negated or parsed.interrogative or parsed.quoted:
        return False
    if parsed.action == "clear":
        return True
    if "clear" in parsed.actions:
        return True
    return any(verb in parsed.text for verb in _DESTRUCTIVE_VERBS)


# ---------------------------------------------------------------------------
# Conversational reference resolution
# ---------------------------------------------------------------------------

def _last_user_text(conversation: Optional[Iterable[object]]) -> str:
    if not conversation:
        return ""
    try:
        items = list(conversation)
    except TypeError:
        return ""
    for item in reversed(items[-8:]):
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
        return _clean(content)
    return ""


def resolve_reference_target(
    message: object,
    conversation: Optional[Iterable[object]] = None,
) -> Optional[str]:
    """Resolve a deictic follow-up (``就它吧``) to the nearest prior target.

    Pure in-memory context lookup: the current turn's own explicit target
    always wins, and only an otherwise object-less reference consults the
    recent user turns.
    """
    parsed = parse_request(message)
    if parsed.target:
        return parsed.target
    if not parsed.references:
        return None
    prior = parse_request(_last_user_text(conversation))
    return prior.target or None
