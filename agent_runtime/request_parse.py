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
    "RequestSubtask",
    "parse_request",
    "normalize_text",
    "is_internal_tool_result_message",
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


def is_internal_tool_result_message(message: object) -> bool:
    """Identify synthetic user-role records used only for tool continuity."""
    return normalize_text(message).lstrip().casefold().startswith("[tool result:")


# ---------------------------------------------------------------------------
# Structural detectors
# ---------------------------------------------------------------------------

_INTERROGATIVE_END = re.compile(r"[?？吗呢]$")
_INTERROGATIVE_ZH = re.compile(
    r"(?:是不是|有没有|能不能|可不可以|是否|怎么样|如何|怎么|为什么|为何|什么|谁|"
    r"哪里|哪儿|在哪|哪次|哪个|哪一个|哪种|哪一种|"
    r"完成.*[了没]|做了[没吗]|好了[没吗]|生成.*[了没]|分割.*[了没]|规划.*[了没])"
)
_INTERROGATIVE_EN = re.compile(
    r"\b(?:what|which|where|when|why|who|whose|how|is it|are (?:you|there)|"
    r"can (?:you|i)|could|would|should|has (?:it|the)|have (?:you|they)|"
    r"did (?:you|it)|does (?:it|the))\b"
)
# ``是 A 还是 B`` choice questions often carry no question word or mark:
# "刚刚完成的这个规划任务是使用的算法是基于RL的还是规则-based的".  A
# ``无论/不管`` frame ("无论是规则还是RL都可以") is a statement and must
# not be treated as a question.
_INTERROGATIVE_CHOICE = re.compile(
    r"是[^，。？！?!,.]{0,28}还是|"
    r"\bwhether\b[^.?!]{0,48}\bor\b",
    re.IGNORECASE,
)
_CHOICE_STATEMENT = re.compile(r"^\s*(?:无论|不管|不论)")
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
    if _INTERROGATIVE_CHOICE.search(lower) and not _CHOICE_STATEMENT.match(lower):
        return True
    # Negation + passive inspection = "don't do anything, just check".
    if _NEGATED_INSPECTION.search(lower) and re.search(
        r"(?:查看|看看|检查|确认|告诉|check|look|inspect)", lower,
    ):
        return True
    return False


_NEGATION_MARKERS = (
    "不要", "不用", "不需要", "无需", "不必", "不能", "不可", "不可以",
    "没有", "取消", "切勿", "禁止", "不允许", "不执行", "不生成", "不重新",
    "别生成", "并非", "不是", "没生成", "未生成", "不需要",
    "do not", "don't", "dont", "never",
    "no need", "cancel", "not ",
)

# Scope exclusion: the named object is carved out of an otherwise positive
# command ("全部更新，不含导板" = update everything except the guide).  Unlike
# negation it does not veto the whole action, so it is tracked per target.
_EXCLUSION_MARKERS = (
    "不含", "不包括", "不包含", "除了", "除外", "除外", "之外",
    "except", "excluding", "with the exception", "without",
)


def is_negated(message: object) -> bool:
    """Return True when an explicit negation frame is present."""
    text = _clean(message)
    if not text:
        return False
    if any(marker in text for marker in _NEGATION_MARKERS):
        return True
    # ``别`` is a negation only in an imperative such as ``别生成``. A raw
    # substring check also matches ordinary words like ``分别``/``识别`` and
    # can incorrectly veto an otherwise valid read-only request. Ignore the
    # common lexical compounds on either side while preserving ``请别…`` and
    # ``别再…`` safety guards.
    lexical_prefixes = frozenset("分识类别特个告诀辞")
    lexical_suffixes = frozenset("名的处墅扭针称")
    for match in re.finditer("别", text):
        previous = text[match.start() - 1] if match.start() else ""
        following = text[match.end()] if match.end() < len(text) else ""
        if previous in lexical_prefixes or following in lexical_suffixes:
            continue
        return True
    return False


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
        "\u91cd\u7b97", "\u91cd\u65b0\u89c4\u5212",
        "\u91cd\u65b0\u8ba1\u7b97", "\u91cd\u65b0\u7b97", "\u518d\u8ba1\u7b97",
        "\u518d\u7b97", "\u91cd\u65b0\u8bc4\u4f30",
        "run", "execute", "start", "perform", "replan", "rerun",
        "recalculate", "recompute", "calculate", "compute",
    )),
    ("display", (
        "\u622a\u56fe", "\u622a\u5c4f", "\u62cd\u7167", "\u622a\u53d6", "screenshot", "capture",
        "\u67e5\u770b", "\u770b\u770b", "\u770b\u4e00\u4e0b", "\u663e\u793a",
        "\u5c55\u793a", "\u5448\u73b0", "\u6253\u5f00", "\u67e5\u9605", "show",
        "view", "display", "present", "load", "open", "see",
    )),
    # General UI interaction verbs are structurally distinct from clinical
    # writes. They let the shared clause parser bind separate UI actions
    # without granting a clinical tool capability.
    ("ui_change", (
        "hide", "hidden", "toggle", "set", "setting", "change", "adjust", "turn",
        "switch", "expand", "collapse", "increase", "decrease", "click",
        "right-click", "double-click", "select", "input", "scroll", "wheel", "drag",
        "隐藏", "关闭", "禁用", "切换", "设置", "设为", "设成", "调整", "改变", "修改",
        "展开", "收起", "增加", "减少", "调高", "调低", "点击", "右键", "双击",
        "选择", "输入", "滚动", "拖动",
    )),
    ("annotate", (
        "\u5708\u51fa", "\u6807\u51fa", "\u6807\u6ce8", "\u9ad8\u4eae", "circle",
        "annotate", "highlight", "mark",
    )),
)

_WRITE_ACTIONS = frozenset({"generate", "clear", "export", "segment", "plan", "annotate"})

# A write whose scope is "all of them" may legitimately omit the target noun
# because the objects were just enumerated in the preceding reply (an
# elliptical follow-up such as "那请你全部更新" / "then update everything").
# Aggregate widening is limited to (re)producing actions: an explicit
# collection word can never authorize a destructive ``clear``.
_AGGREGATE_WRITE_ACTIONS = frozenset({"generate", "plan", "segment"})

_AGGREGATE_SCOPE = re.compile(
    r"(?:全部|全都|全数|全盘|所有|一切|每个|各个|逐一|逐个|统统|通通|一律|"
    r"整体|整组|整个|过期|过时|"
    r"\ball\b|\beverything\b|\bboth\b|\bevery\b|\beach\b|\bstale\b|\boutdated\b|"
    # Bare "都" is an aggregate only when it is followed by an action verb
    # (都更新 / 都要重算); unrelated compounds such as 都市 or predications
    # like 每次重建都失败 stay non-aggregate.
    r"都(?=(?:要|需|得|应|会|能|去|更|重|改|生|刷|做|算|建|修|换|补|填)))",
    re.IGNORECASE,
)


def _has_aggregate_scope(text: str) -> bool:
    return bool(_AGGREGATE_SCOPE.search(str(text or "")))


# A bare yes/confirm/go-ahead.  Evaluated with ``fullmatch`` against cleaned
# text, and additionally rejected when the turn carries its own target/action,
# so "可以生成报告吗" is a question and never a confirmation.
_ACK_ONLY = re.compile(
    r"(?:好(?:的|吧|啊|呀)?|行(?:吧|啊)?|可以|同意|确认(?:执行|一下)?|没问题|"
    r"开始(?:吧|啊|执行)?|执行(?:吧|一下)?|继续(?:吧|执行)?|来吧|搞吧|走起|"
    r"就(?:按|照)(?:这个|你说的|你说的做|上面|上述|这样)(?:做|执行|来|办)?|"
    r"按(?:这个|你说的|上述|上面)(?:做|执行|来|办)?|"
    r"做吧|上吧|都行|随便|yes|yep|yeah|sure|ok(?:ay)?|"
    r"go\s+ahead|do\s+it|proceed|continue|start|run\s+it|please\s+do)"
)


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

def _alias_matches(text: str, alias: str) -> bool:
    """Match CJK phrases by substring and ASCII aliases by token boundary."""
    if not text or not alias:
        return False
    if re.search(r"[a-z0-9]", alias, re.IGNORECASE):
        pattern = rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])"
        return bool(re.search(pattern, text, re.IGNORECASE))
    return alias in text


def _find_targets(text: str) -> List[str]:
    matched: Dict[str, List[str]] = {}
    for target, aliases in TARGET_ALIASES:
        hits = [alias for alias in aliases if _alias_matches(text, alias)]
        if hits:
            matched[target] = hits
    # In a verb phrase such as “CTV 分割”, 分割 is the action, not a second
    # target family called structure. Keep structure when its noun aliases are
    # explicitly present (e.g. “segment the structure”).
    if "structure" in matched and not any(
        alias not in {"分割", "segmentation"}
        for alias in matched["structure"]
    ) and len(matched) > 1:
        matched.pop("structure", None)
    # “dose report” and “planning report” are report qualifiers, not two
    # independently requested objects. Explicit conjunctions remain compound.
    if "report" in matched:
        compact = re.sub(r"\s+", " ", text.casefold())
        coordinated = re.search(r"(?:和|与|及|以及|并且|(?<![a-z0-9_])and(?![a-z0-9_])|&)", compact)
        if "dose" in matched and re.search(r"剂量\s*报告|(?<![a-z0-9_])dose\s+report(?![a-z0-9_])", compact) and not coordinated:
            matched.pop("dose", None)
        if "planning" in matched and re.search(r"(?:计划|规划)\s*报告|(?<![a-z0-9_])(?:(?:treatment )?plan|planning)\s+report(?![a-z0-9_])", compact) and not coordinated:
            matched.pop("planning", None)
    # “截图/ screenshot” names an action, not an additional business object
    # when a concrete target such as a guide or CTV is also present.
    if "screenshot" in matched and len(matched) > 1:
        matched.pop("screenshot", None)
    return [target for target, _aliases in TARGET_ALIASES if target in matched]


def _find_actions(text: str) -> List[str]:
    found: List[str] = []
    for action, aliases in _ACTION_ALIASES:
        if any(_alias_matches(text, alias) for alias in aliases):
            found.append(action)
    return found


def _first_object_by_position(text: str) -> str:
    """Return the earliest, most specific target noun in the utterance."""
    matches = []
    allowed_targets = set(_find_targets(text))
    for target, aliases in TARGET_ALIASES:
        if target not in allowed_targets:
            continue
        for alias in aliases:
            if re.search(r"[a-z0-9]", alias, re.IGNORECASE):
                pattern = rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])"
                found = re.search(pattern, text, re.IGNORECASE)
            else:
                found = re.search(re.escape(alias), text)
            if found:
                matches.append((found.start(), -len(alias), target))
    return min(matches)[2] if matches else ""


def _primary_action(text: str, actions: List[str]) -> str:
    """Pick the highest-priority explicit action using token-safe aliases."""
    if not actions:
        return ""
    command_verbs = (
        "生成", "重新生成", "再生成", "重建", "重做", "制作", "创建", "更新", "刷新",
        "填充", "补全", "完善", "清空", "清除", "删除", "删掉", "导出", "分割",
        "勾画", "执行", "开始", "进行", "重置", "写", "撰写", "generate",
        "regenerate", "re-generate", "rebuild", "create", "update", "refresh",
        "clear", "delete", "remove", "export", "segment", "plan", "run", "execute",
        "start", "reset", "重新计算", "重算",
    )
    for action, aliases in _ACTION_ALIASES:
        if action not in actions:
            continue
        for alias in aliases:
            if alias in command_verbs and _alias_matches(text, alias):
                return action
    return actions[0]


def _target_mentions(text: str) -> List[Tuple[int, int, str]]:
    mentions = []
    allowed = set(_find_targets(text))
    for target, aliases in TARGET_ALIASES:
        if target not in allowed:
            continue
        for alias in aliases:
            if re.search(r"[a-z0-9]", alias, re.IGNORECASE):
                pattern = rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])"
                matches = re.finditer(pattern, text, re.IGNORECASE)
            else:
                matches = re.finditer(re.escape(alias), text)
            for match in matches:
                mentions.append((match.start(), match.end(), target))
    mentions.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    # Prefer the longest alias at a shared start offset, then one mention per
    # semantic target; duplicated synonyms must not look like two objects.
    selected = []
    seen_targets = set()
    last_start = None
    for mention in mentions:
        start, end, target = mention
        if target in seen_targets:
            continue
        if last_start == start and selected and (end - start) < (selected[-1][1] - selected[-1][0]):
            continue
        selected.append(mention)
        seen_targets.add(target)
        last_start = start
    return sorted(selected, key=lambda item: item[0])


def _action_position(text: str, action: str) -> Optional[int]:
    aliases = dict(_ACTION_ALIASES).get(action, ())
    positions = []
    for alias in aliases:
        if re.search(r"[a-z0-9]", alias, re.IGNORECASE):
            pattern = rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])"
            match = re.search(pattern, text, re.IGNORECASE)
        else:
            match = re.search(re.escape(alias), text)
        if match:
            positions.append(match.start())
    return min(positions) if positions else None


def _targets_explicitly_coordinated(text: str, targets: List[str]) -> bool:
    if len(targets) < 2:
        return False
    mentions = _target_mentions(text)
    by_target = {}
    for start, end, target in mentions:
        by_target.setdefault(target, (start, end))
    ordered = sorted((by_target[target] for target in targets if target in by_target))
    if len(ordered) != len(targets):
        return False
    return all(
        re.search(r"(?:和|与|及|以及|(?<![a-z0-9_])and(?![a-z0-9_])|&)", text[left[1]:right[0]], re.IGNORECASE)
        for left, right in zip(ordered, ordered[1:])
    )


def _mask_quoted_content(text: str) -> str:
    """Mask quote contents while preserving offsets for lexical authorization."""
    chars = list(text)
    for start, end in _quoted_spans(text):
        for index in range(max(0, start), min(len(chars), end)):
            chars[index] = " "
    return "".join(chars)


def _attribution_frame(text: str) -> bool:
    return bool(re.search(
        r"(?:日志|记录|原文|对话|邮件|消息|引用|转述|他说|她说|用户说|用户要求|医生说|"
        r"上面写着|文中写着|内容提到|提到有人说|"
        r"\b(?:the log|the record|the quote|quoted text|according to|"
        r"(?:he|she|they|the user|the doctor) said|the message says)\b)",
        text,
        re.IGNORECASE,
    ))


def _is_conditional_prefix(text: str) -> bool:
    return bool(re.match(
        r"\s*(?:如果|假如|假设|若是?|要是|除非|万一|一旦|"
        r"if\b|unless\b|suppose\b|assuming\b|in case\b)",
        text,
        re.IGNORECASE,
    ))


def _subtask_clause_spans(text: str) -> List[Tuple[int, int, bool]]:
    """Split independent clauses, but keep noun coordination intact.

    A conjunction is a boundary only when both sides independently contain an
    object and an action. Thus “generate guide and report” remains one shared
    command, while “view the guide and generate the report” splits safely.
    The boolean marks a consequent inherited from a preceding condition.
    """
    if not text:
        return []
    hard = re.compile(r"[,，;；。.!！?？\n]+")
    soft = re.compile(
        r"\s+(?:and then|then|however|but|also|additionally|besides|in addition|and)\s+|"
        r"(?:此外还|另外还|此外|另外|同时|顺便|而且|并且|但是|不过|然而|然后|接着|"
        r"以及|和|与|及|并(?=[\u4e00-\u9fff]))",
        re.IGNORECASE,
    )

    def trim_span(start: int, end: int) -> Optional[Tuple[int, int]]:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        return (start, end) if start < end else None

    def complete(start: int, end: int) -> bool:
        fragment = text[start:end]
        return bool(_find_targets(fragment) and _find_actions(_mask_quoted_content(fragment)))

    def split_soft(start: int, end: int, inherited: bool) -> List[Tuple[int, int, bool]]:
        for match in soft.finditer(text, start, end):
            left = trim_span(start, match.start())
            right = trim_span(match.end(), end)
            if not left or not right or not complete(*left) or not complete(*right):
                continue
            connector = match.group(0).strip().lower()
            left_text = text[left[0]:left[1]]
            conditional_right = inherited or (
                connector in {"then", "and then", "然后", "那么", "则"}
                and is_conditional(_mask_quoted_content(left_text))
            )
            return split_soft(*left, inherited) + split_soft(*right, conditional_right)
        return [(start, end, inherited)]

    spans: List[Tuple[int, int, bool]] = []
    pending_condition = False
    cursor = 0
    for boundary in hard.finditer(text):
        trimmed = trim_span(cursor, boundary.start())
        if trimmed:
            segment = text[trimmed[0]:trimmed[1]]
            spans.extend(split_soft(*trimmed, pending_condition))
            # A condition can contain action-looking words in a factual
            # predicate ("if the report has not been generated"). Its
            # consequence remains conditional even though the lexicon sees
            # that verb. Carry the condition only across clause separators,
            # never across a sentence-ending boundary.
            continues_sentence = not re.search(r"[.!！?？\n]", boundary.group(0))
            pending_condition = _is_conditional_prefix(segment) and continues_sentence
        cursor = boundary.end()
    trimmed = trim_span(cursor, len(text))
    if trimmed:
        spans.extend(split_soft(*trimmed, pending_condition))
    return spans


def _parse_subtasks(text: str) -> Tuple["RequestSubtask", ...]:
    tasks = []
    source = normalize_text(text)
    for start, end, inherited_condition in _subtask_clause_spans(source):
        clause = source[start:end].strip()
        if not clause:
            continue
        leading = len(source[start:end]) - len(source[start:end].lstrip())
        task_start = start + leading
        task_end = task_start + len(clause)
        unquoted = _mask_quoted_content(clause)
        targets = _find_targets(clause)
        actions = _find_actions(unquoted)
        if "generate" in actions and (
            _ATTRIBUTIVE_REPORT.search(clause) or _ATTRIBUTIVE_GUIDE.search(clause)
        ) and not (canonical_report_mutation(clause) or canonical_guide_generation(clause)):
            actions = [action for action in actions if action != "generate"]
        mentions = _target_mentions(clause)
        ordered_targets = []
        for _start, _end, target in mentions:
            if target not in ordered_targets:
                ordered_targets.append(target)
        action = _primary_action(unquoted, actions)
        # One verb can govern a coordinated noun phrase (“generate guide and
        # report”), but must not leak onto an unrelated object later in the
        # clause (“generate report and screenshot the guide”).
        matched_targets = list(ordered_targets)
        ambiguous_pairing = False
        if action and len(matched_targets) > 1:
            if len(actions) > 1:
                ambiguous_pairing = True
            elif not _targets_explicitly_coordinated(clause, matched_targets):
                action_pos = _action_position(unquoted, action)
                if action_pos is None:
                    ambiguous_pairing = True
                else:
                    distances = []
                    for start_pos, end_pos, target in mentions:
                        distance = min(abs(action_pos - start_pos), abs(action_pos - end_pos))
                        distances.append((distance, target))
                    distances.sort()
                    if len(distances) > 1 and distances[0][0] == distances[1][0]:
                        ambiguous_pairing = True
                    else:
                        matched_targets = [distances[0][1]]
        quote_spans = _quoted_spans(clause)
        # Quoting only an object label (e.g. clear the "Report" section) does
        # not quote the command. Treat a clause as quoted when the whole clause
        # is quoted or the quoted span itself contains a target/action command.
        quoted = is_quoted(clause) or any(
            bool(_find_actions(clause[quote_start:quote_end]))
            and bool(_find_targets(clause[quote_start:quote_end]))
            for quote_start, quote_end in quote_spans
        )
        common = {
            "raw": clause,
            "start": task_start,
            "end": task_end,
            "actions": tuple(actions),
            "negated": is_negated(unquoted),
            "conditional": inherited_condition or is_conditional(unquoted),
            "interrogative": is_interrogative(clause) or bool(
                re.match(r"\s*[?？]", source[task_end:])
            ),
            "quoted": quoted,
            "attributed": _attribution_frame(clause),
            "ambiguous": ambiguous_pairing or (len(actions) > 1 and len(ordered_targets) > 1),
            "aggregate": _has_aggregate_scope(unquoted),
            "excluded": bool(ordered_targets) and (
                any(marker in unquoted for marker in _EXCLUSION_MARKERS)
                or is_negated(unquoted)
            ),
            "source": "deterministic_lexicon",
        }
        if action and matched_targets:
            for target in matched_targets:
                tasks.append(RequestSubtask(
                    **common, target=target, action=action, targets=(target,),
                ))
        else:
            tasks.append(RequestSubtask(
                **common,
                target=ordered_targets[0] if ordered_targets else "",
                action=action,
                targets=tuple(ordered_targets),
            ))
    return tuple(tasks)


def _ordered_goals(text: str, objects: List[str], actions: List[str]) -> List[Tuple[str, str]]:
    """Compatibility projection of locally parsed target/action goals."""
    goals = []
    for task in _parse_subtasks(text):
        if task.target and task.action and not task.ambiguous:
            pair = (task.target, task.action)
            if pair not in goals:
                goals.append(pair)
    return goals


def _clauses(text: str) -> List[str]:
    return [text[start:end] for start, end, _ in _subtask_clause_spans(text)]


# ---------------------------------------------------------------------------
# Parsed record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RequestSubtask:
    """One locally scoped task extracted from a normalized user turn."""

    raw: str
    start: int
    end: int
    target: str = ""
    action: str = ""
    targets: Tuple[str, ...] = ()
    actions: Tuple[str, ...] = ()
    negated: bool = False
    conditional: bool = False
    interrogative: bool = False
    quoted: bool = False
    attributed: bool = False
    ambiguous: bool = False
    aggregate: bool = False
    excluded: bool = False
    source: str = "deterministic_lexicon"

    @property
    def affirmative_command(self) -> bool:
        return (
            bool(self.target)
            and self.action in _WRITE_ACTIONS
            and not (self.negated or self.interrogative or self.conditional
                     or self.quoted or self.attributed or self.ambiguous)
        )

    @property
    def aggregate_command(self) -> bool:
        """True for an explicit "update/regenerate everything" command.

        The target noun is intentionally optional: the aggregate scope word
        itself widens the write to every non-destructive clinical artifact,
        so requiring an explicit target here is what previously blocked a
        valid elliptical follow-up.  Destructive actions are excluded.
        """
        return (
            self.aggregate
            and self.action in _AGGREGATE_WRITE_ACTIONS
            and not (self.negated or self.interrogative or self.conditional
                     or self.quoted or self.attributed or self.ambiguous)
        )

    @property
    def unconditional_command(self) -> bool:
        return self.affirmative_command and not self.conditional


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
    excluded_targets: Tuple[str, ...] = ()
    subtasks: Tuple[RequestSubtask, ...] = ()
    reason: str = ""

    @property
    def has_write_intent(self) -> bool:
        return any(task.target and task.action in _WRITE_ACTIONS for task in self.subtasks)

    @property
    def affirmative_command(self) -> bool:
        """True when at least one locally scoped positive write was requested."""
        return any(task.affirmative_command for task in self.subtasks)

    @property
    def aggregate_command(self) -> bool:
        """True when a positive write is explicitly scoped to "everything"."""
        return any(task.aggregate_command for task in self.subtasks)

    @property
    def unconditional_command(self) -> bool:
        return any(task.unconditional_command for task in self.subtasks)

    @property
    def compound_write(self) -> bool:
        """True when the utterance contains multiple distinct write goals."""
        write_goals = {
            (task.target, task.action)
            for task in self.subtasks
            if task.target in _WRITABLE_TARGETS
            and task.action in _WRITE_ACTIONS
            and not task.negated
            and not task.interrogative
            and not task.attributed
            and not task.quoted
        }
        return len(write_goals) >= 2

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
            "excluded_targets": list(self.excluded_targets),
            "subtasks": [
                {
                    "raw": task.raw,
                    "start": task.start,
                    "end": task.end,
                    "target": task.target,
                    "action": task.action,
                    "targets": list(task.targets),
                    "actions": list(task.actions),
                    "negated": task.negated,
                    "conditional": task.conditional,
                    "interrogative": task.interrogative,
                    "quoted": task.quoted,
                    "attributed": task.attributed,
                    "ambiguous": task.ambiguous,
                    "aggregate": task.aggregate,
                    "excluded": task.excluded,
                    "source": task.source,
                    "affirmative": task.affirmative_command,
                    "aggregate_command": task.aggregate_command,
                }
                for task in self.subtasks
            ],
            "affirmative": self.affirmative_command,
            "unconditional": self.unconditional_command,
            "aggregate_command": self.aggregate_command,
        }


def parse_request(message: object) -> ParsedRequest:
    """Parse one utterance into its structural record."""
    raw = str(message or "")
    text = _clean(raw)
    if not text:
        return ParsedRequest(raw=raw, text="", reason="empty")

    source = normalize_text(raw)
    subtasks = _parse_subtasks(source)
    objects = _find_targets(text)
    actions = _find_actions(_mask_quoted_content(text))
    target = _first_object_by_position(text) or (objects[0] if objects else "")
    action = _primary_action(_mask_quoted_content(text), actions)
    goals = []
    for task in subtasks:
        if task.target and task.action and not task.ambiguous:
            pair = (task.target, task.action)
            if pair not in goals:
                goals.append(pair)
    references = tuple(
        marker for marker in _REFERENCE_MARKERS if marker in text
    )
    excluded_targets: List[str] = []
    for task in subtasks:
        if not task.excluded:
            continue
        candidates = task.targets or ((task.target,) if task.target else ())
        for name in candidates:
            if name and name not in excluded_targets:
                excluded_targets.append(name)
    return ParsedRequest(
        raw=raw,
        text=text,
        target=target,
        action=action,
        scope="compound" if len(goals) > 1 else "single",
        negated=any(task.negated for task in subtasks),
        conditional=any(task.conditional for task in subtasks),
        interrogative=any(task.interrogative for task in subtasks),
        quoted=any(task.quoted for task in subtasks) or is_quoted(raw),
        references=references,
        objects=tuple(objects),
        actions=tuple(actions),
        goals=tuple(goals),
        excluded_targets=tuple(excluded_targets),
        subtasks=subtasks,
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


def is_downstream_update_request(message: object) -> bool:
    """True for a target-less "update everything" (downstream repair) command.

    ``全部更新`` / ``所有后续都更新`` name no object of their own: the objects
    are the Session's stale artifacts.  A target-specific aggregate such as
    ``全部重新分割`` or ``全部重新规划`` is a different command and must keep its
    own handler, so it is deliberately excluded here.
    """
    parsed = message if isinstance(message, ParsedRequest) else parse_request(message)
    if not parsed.aggregate_command:
        return False
    excluded = set(parsed.excluded_targets)
    return any(
        task.aggregate_command and (not task.target or task.target in excluded)
        for task in parsed.subtasks
    )


def is_unconditional_command(message: object) -> bool:
    return parse_request(message).unconditional_command


def tool_authorization_target(tool_name: str) -> Optional[Tuple[str, str]]:
    return _TOOL_MUTATION_GOAL.get(str(tool_name or ""))


def _conversation_text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(
            str(part.get("text") or part.get("content") or "")
            if isinstance(part, Mapping) else str(part or "")
            for part in value
        )
    return str(value or "")


def is_affirmative_acknowledgement(message: object) -> bool:
    """True when the turn is only a yes/confirm/go-ahead, with no new request.

    After the assistant proposes an ordered operation and asks the user to
    confirm, the natural reply is a bare acknowledgement ("开始吧", "执行",
    "就按你说的做", "go ahead").  Such a turn carries no target or action of its
    own; it inherits the plan from the preceding assistant message, which is
    resolved separately in ``mutating_execution_authorized``.
    """
    text = _clean(message)
    if not text or len(text) > 24:
        return False
    if not _ACK_ONLY.fullmatch(text):
        return False
    parsed = parse_request(message)
    # A named object makes it a new request ("继续规划"), not a confirmation.
    # Bare start/execute verbs are allowed because they carry no object.
    for task in parsed.subtasks:
        if task.target:
            return False
    return True


def _previous_assistant_text(conversation: object) -> str:
    """Return the assistant message that immediately precedes the current turn."""
    try:
        items = list(conversation or [])
    except TypeError:
        return ""
    seen_current_user = False
    for item in reversed(items):
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").lower()
        if role == "user":
            # The current utterance is the newest user entry; skip it and stop
            # at the assistant reply before it.
            if not seen_current_user:
                seen_current_user = True
                continue
            break
        if role == "assistant" and seen_current_user:
            return _conversation_text(item.get("content", item.get("message", "")))
    return ""


def _previous_assistant_names_tool(conversation: object, tool_name: str) -> bool:
    if not tool_name:
        return False
    text = _previous_assistant_text(conversation)
    if not text:
        return False
    return bool(re.search(
        rf"(?<![a-z0-9_]){re.escape(str(tool_name))}(?![a-z0-9_])",
        text,
        re.IGNORECASE,
    ))



# Tools that form the deterministic planning dependency chain.  When the user
# confirms a blocked-mutation prompt, the whole chain is authorized even if the
# LLM re-emits only the first steps.
_PLANNING_CHAIN_TOOLS = frozenset({
    "ctv_segmentation",
    "oar_segmentation",
    "planning_pipeline",
})

# Markers that identify the blocked-mutation confirmation prompt generated by
# ``_blocked_mutation_message`` in llm_runtime.py.
_CONFIRMATION_PROMPT_MARKERS = (
    "\u4e3a\u907f\u514d\u8bef\u6539\u5f53\u524d\u75c5\u4f8b",
    "To avoid changing the current case without consent",
)


def _previous_assistant_is_confirmation_prompt(conversation: object) -> bool:
    """True when the immediately preceding assistant reply is a confirmation prompt."""
    text = _previous_assistant_text(conversation)
    if not text:
        return False
    return any(marker in text for marker in _CONFIRMATION_PROMPT_MARKERS)


def mutating_execution_authorized(
    message: object,
    tool_name: str,
    conversation: object = None,
) -> bool:
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
    expected_target, expected_action = goal
    # A target explicitly carved out of the request ("不含导板") is never
    # authorized, even when the surrounding write is a positive aggregate.
    if expected_target in parsed.excluded_targets:
        return False
    allowed_actions = {
        "generate": {"generate"},
        "plan": {"plan"},
        "segment": {"segment", "plan", "generate"},
    }.get(expected_action, {expected_action})
    for task in parsed.subtasks:
        if (
            task.ambiguous or task.negated or task.interrogative
            or task.conditional or task.quoted or task.attributed
        ):
            continue
        if task.target == expected_target and task.action in allowed_actions:
            return True
        # A positive planning pipeline may implicitly load its segmentation
        # inputs, but only when planning itself is the same local task.
        if (
            expected_target in {"ctv", "oar", "structure"}
            and task.target == "planning"
            and task.action == "plan"
            and not task.negated
            and not task.conditional
            and not task.attributed
        ):
            return True
    # An aggregate command ("全部更新" / "update everything") widens a write from
    # one named object to every non-destructive clinical artifact named in the
    # preceding reply.  The clause carries an action and a scope word but no
    # target noun, so the per-target loop above cannot match it; treat it as
    # authorization for any writable target.  Destructive targets are not in
    # ``_TOOL_MUTATION_GOAL`` and ``clear`` is excluded from the aggregate
    # action set, so this path can never authorize a destructive operation.
    if parsed.aggregate_command and expected_target in _WRITABLE_TARGETS:
        return True
    # A bare confirmation inherits the plan the assistant proposed in the
    # immediately preceding reply.  This closes the loop after the agent asked
    # "shall I run these?", so an acknowledgement is not silently ignored.
    if (
        conversation
        and is_affirmative_acknowledgement(message)
        and _previous_assistant_names_tool(conversation, tool_name)
    ):
        return True
    # When the previous reply is the blocked-mutation confirmation prompt and
    # the user confirms, the whole planning dependency chain is authorized.
    # The LLM may re-emit only the first steps (ctv_segmentation,
    # oar_segmentation) instead of the anchor tool named in the prompt; those
    # are prerequisites of the confirmed plan and must not trigger a second
    # confirmation loop.
    if (
        conversation
        and is_affirmative_acknowledgement(message)
        and _previous_assistant_is_confirmation_prompt(conversation)
        and tool_name in _PLANNING_CHAIN_TOOLS
    ):
        return True
    return False


def ui_action_is_destructive(target: object) -> bool:
    return str(target or "") in DESTRUCTIVE_UI_TARGETS


def ui_action_explicitly_authorized(message: object, target: object) -> bool:
    """Authorize a destructive UI action only from its own positive clause."""
    target = str(target or "")
    if not ui_action_is_destructive(target):
        return True

    clear_verb = re.compile(r"(?:清空|清除|\bclear\b|\bwipe\b)", re.IGNORECASE)
    delete_verb = re.compile(r"(?:删除|删掉|移除|\bdelete\b|\bremove\b)", re.IGNORECASE)
    reset_verb = re.compile(r"(?:重置|\breset\b)", re.IGNORECASE)
    session_scope = re.compile(
        r"(?:\b(?:session|case)\b|当前\s*(?:病例|session)|"
        r"本(?:次)?(?:病例|session)|会话)",
        re.IGNORECASE,
    )
    browser_cache_scope = re.compile(
        r"(?:\bbrowser\s+cache\b|\bcache\b|浏览器\s*缓存|浏览器缓存)",
        re.IGNORECASE,
    )
    manual_scope = re.compile(
        r"(?:\bmanual\b|\bmanual\s+planning\b|手动)",
        re.IGNORECASE,
    )

    for task in parse_request(message).subtasks:
        # Keep negation, quotation, condition, question, and attribution local:
        # a bad sibling clause cannot authorize or cancel this action.
        if (
            task.negated or task.interrogative or task.conditional
            or task.quoted or task.attributed or task.ambiguous
        ):
            continue
        clause = _mask_quoted_content(task.raw).casefold()
        if task.action != "clear":
            continue

        if target == "report.clear":
            if task.target == "report" and (clear_verb.search(clause) or delete_verb.search(clause)):
                return True
        elif target == "plan.reset":
            if (
                task.target == "planning" and reset_verb.search(clause)
                and not manual_scope.search(clause)
            ):
                return True
        elif target == "manual.plan.reset":
            if (
                task.target == "planning" and reset_verb.search(clause)
                and manual_scope.search(clause)
            ):
                return True
        elif target == "session.delete":
            if session_scope.search(clause) and delete_verb.search(clause):
                return True
        elif target == "session.clear_all":
            if session_scope.search(clause) and clear_verb.search(clause):
                return True
        elif target == "browser_cache.clear":
            if browser_cache_scope.search(clause) and clear_verb.search(clause):
                return True
    return False


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
        cleaned = _clean(content)
        if is_internal_tool_result_message(cleaned):
            continue
        return cleaned
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
