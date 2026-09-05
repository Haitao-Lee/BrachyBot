"""Capability-driven natural-language UI operation resolution.

This module intentionally does not contain a sentence-to-action whitelist.
It separates the language problem into four general questions:

* is the turn asking to mutate the interface rather than asking for help;
* which property/value was requested (visibility, opacity, zoom, etc.);
* which *currently published* capability can satisfy it; and
* is the match strong enough to execute without asking the model to guess.

The browser publishes ``ui_operation_catalog`` from the actual mounted DOM
and Data Tree.  The small typed fallback below only covers the controller's
stable group contract, so a first turn is still routable before the browser
has completed its initial state synchronisation.  It is a capability
fallback, not a list of user phrases.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


_ACTION_RE = re.compile(
    r"(?:^|[\s,，。:：])(?:请|帮我|麻烦|请帮我|please|kindly|could you|would you|can you)\s*"
    r"|(?:设置|设为|设成|调成|调整|改变|修改|切换|打开|关闭|显示|隐藏|启用|禁用|展开|收起|"
    r"放大|缩小|适配|重置|点击|双击|右键|右击|悬停|聚焦|失焦|滚动|拖动|选择|移动|增加|减少|调高|调低|应用|运行|执行|提交|按键|指针|鼠标|触发输入|触发改变|生成|创建|新增|重算|重新计算|重新规划|重规划|开始|停止|确认|取消|保存|下载|最大化|最小化|全屏|撤销|重做|上一步|下一步|首项|末项|导出|导入|删除|重命名|"
    r"set|make|change|adjust|turn|switch|open|close|show|hide|enable|disable|expand|collapse|"
    r"zoom|fit|reset|click|right[-\s]?click|double[-\s]?click|dblclick|hover|focus|blur|scroll|wheel|drag|keypress|keydown|keyup|submit|select|move|increase|decrease|apply|run|generate|create|add|recompute|recalculate|replan|start|stop|confirm|cancel|save|download|maximize|minimize|fullscreen|undo|redo|previous|next|first|last|export|import|delete|rename|"
    r"pointer(?:down|move|up|over|out|cancel|enter|leave)|mouse(?:down|move|up|over|out|enter|leave)|input|change)"
    r"(?=\s|$|[，。！？!?：:])",
    re.IGNORECASE,
)

_IMPERATIVE_RE = re.compile(
    # Chinese imperative markers are not followed by ``\\b`` because two
    # adjacent CJK characters are both word characters in Python's regex
    # engine (for example ``请将3D viewer``).
    r"(?:请|帮我|麻烦|将|把|让|使|使得|需要|执行|点击|右键|右击|悬停|聚焦|失焦|指针|鼠标|选择|设置|设为|设成|调成|"
    r"调整为|改为|切换到|显示为|隐藏|展开|收起|打开|关闭|启用|禁用|放大|缩小|适配|重置|增加|减少|调高|调低|"
    r"应用|运行|提交|生成|创建|新增|重算|重新计算|重新规划|重规划|开始|停止|确认|取消|保存|下载|最大化|最小化|全屏|"
    r"撤销|重做|上一步|下一步|首项|末项|导出|导入|删除|重命名|清除|恢复|高亮)|"
    r"(?:^|\s)(?:please|kindly|set|make|change|adjust|turn|switch|show|hide|toggle|"
    r"open|close|enable|disable|click|right[-\s]?click|double[-\s]?click|dblclick|hover|focus|blur|scroll|wheel|drag|keypress|keydown|keyup|submit|select|move|run|generate|create|add|recompute|recalculate|replan|start|stop|confirm|cancel|save|download|apply|reset|fit|maximize|minimize|fullscreen|undo|redo|previous|next|first|last|"
    r"pointer(?:down|move|up|over|out|cancel|enter|leave)|mouse(?:down|move|up|over|out|enter|leave)|input|change)\b",
    re.IGNORECASE,
)

_QUESTION_RE = re.compile(
    # CJK question words are not separated by whitespace in normal user
    # input (``请问3D重建按钮在哪里`` is a common example).  The previous
    # expression required a trailing space/end anchor and consequently let
    # location questions enter the mutation path.  Keep English words
    # boundary-aware so ``is`` in ``isodose`` is not treated as a question.
    r"[?？]|(?:请问|告诉我|解释一下|吗|呢|么|是否|能否|可否|能不能|可以吗|为什么|如何|怎么|哪里|哪儿)|"
    r"(?<![a-z])(?:what\s+is|what|why|how\s+to|how|where\s+is|where|which|can|could|would|is|are|do|does)(?![a-z])",
    re.IGNORECASE,
)

_LOW_LEVEL_EVENT_RE = re.compile(
    # Event names may be glued directly to CJK text (``pointerdown坐标``),
    # so this intentionally has no ASCII word-boundary requirement.
    r"pointer(?:down|move|up|over|out|cancel|enter|leave)|"
    r"mouse(?:down|move|up|over|out|enter|leave)|"
    r"dblclick|double[-\s]?click|contextmenu|right[-\s]?click|"
    r"keypress|keydown|keyup|wheel|scroll|drag|hover|focus|blur|input\s*event|change\s*event|"
    r"指针|鼠标|右键|右击|双击|按键|滚动|滚轮|拖动|拖拽|悬停|聚焦|失焦|触发输入|触发改变",
    re.IGNORECASE,
)

_UI_CONTEXT_RE = re.compile(
    r"(?:ui|interface|control|button|viewer|panel|toolbar|data\s*tree|dom|界面|控件|按钮|"
    r"查看器|面板|工具栏|数据树|窗口|图标|菜单|切片|二维|三维|语言|主题|会话|报告|"
    r"输入|监测|2d|3d|language|theme|session|report|input|monitor)",
    re.IGNORECASE,
)

_ALL_RE = re.compile(
    r"(?:all|every|entire|全部|所有|全部的|每个|各个|整体|整组|整个)",
    re.IGNORECASE,
)

_PERCENT_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*%")

# These are semantic facets, not complete vocabulary lists.  They let the
# resolver classify a property while labels/aliases in the live catalog do the
# object matching.  Adding a new control therefore does not require adding a
# new sentence pattern here.
_PROPERTY_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("opacity", r"opacity|alpha|transparency|不透明度|透明度|透明|半透明|不透明"),
    ("visibility", r"visibility|visible|show|hide|display|显示|隐藏|可见|不可见"),
    ("zoom", r"zoom|magnification|缩放|放大|缩小"),
    ("slice", r"slice|切片|层面|层"),
    ("color", r"color|colour|颜色|色彩"),
    ("layout", r"layout|布局|排列|maximize|minimize|fullscreen|全屏|最大化|最小化"),
    ("panel", r"panel|tab|面板|标签页"),
    ("tool", r"tool|工具|工具栏"),
    ("reconstruct", r"reconstruct|reconstruction|重建"),
    ("file", r"file|browse|upload|文件|浏览|上传"),
    ("window", r"windows*(width)?|窗宽|窗位|windowing"),
    ("threshold", r"threshold|阈值"),
    ("expansion", r"expand|collapse|展开|收起|折叠"),
    ("language", r"language|lang|中文|英文|英语|汉语|语言|chinese|english"),
    ("theme", r"theme|dark|light|主题|深色|浅色|暗色|亮色"),
    ("session", r"session|case|会话|病例|案例"),
    ("report", r"report|报告"),
    ("action", r"set|make|change|adjust|turn|become|click|right[-\s]?click|double[-\s]?click|dblclick|keypress|keydown|keyup|submit|scroll|wheel|drag|hover|focus|blur|pointer(?:down|move|up|over|out|cancel|enter|leave)|mouse(?:down|move|up|over|out|enter|leave)|input|change|run|execute|apply|open|close|rename|move|delete|export|import|add|clear|solo|restore|highlight|reset|generate|create|recompute|recalculate|replan|start|stop|confirm|cancel|save|download|maximize|minimize|fullscreen|undo|redo|previous|next|first|last|设置|设为|设成|调成|调整|改变|修改|改为|变成|点击|右键|右击|双击|悬停|聚焦|失焦|按键|提交|滚动|滚轮|拖动|指针按下|指针移动|指针抬起|指针移入|指针移出|鼠标按下|鼠标移动|鼠标松开|鼠标移入|鼠标移出|触发输入|触发改变|运行|执行|应用|打开|关闭|重命名|移动|删除|导出|导入|添加|清除|仅显示|恢复|高亮|重置|生成|创建|重算|重新计算|重新规划|重规划|开始|停止|确认|取消|保存|下载|最大化|最小化|全屏|撤销|重做|上一步|下一步|首项|末项"),
)

# Stable groups are used only when the live catalog is not available yet.
# The values mirror the public UI-controller group contract and are deliberately
# independent from any particular natural-language sentence.
_GROUP_ALIASES: Tuple[Tuple[str, str], ...] = (
    # Python's Unicode ``\b`` treats adjacent CJK and Latin characters as
    # the same word. Use ASCII-token lookarounds so ``所有OAR`` and
    # ``CTV肿瘤`` remain addressable in natural Chinese input.
    ("oar", r"(?<![a-z0-9_])oar(?![a-z0-9_])|organ(?:s)?\s*at\s*risk|危及器官|器官"),
    ("ctv", r"(?<![a-z0-9_])ctv(?![a-z0-9_])|clinical\s*target|靶区|临床靶区|肿瘤|病灶|肿块"),
    ("non_traversable", r"non[_\s-]*traversable|不可穿刺|不可通过"),
    ("traversable", r"traversable|可穿刺|可通过"),
    ("masks", r"(?<![a-z0-9_])masks?(?![a-z0-9_])|掩膜|蒙版"),
    ("upload_masks", r"upload(?:ed)?\s*masks?|上传掩膜|上传的掩膜"),
    ("generic_masks", r"additional\s*masks?|其他分割掩膜"),
    ("planning", r"planning|计划|规划"),
    ("planning_trajectories", r"trajectory|trajectories|轨迹|针道路径"),
    ("planning_seeds", r"seed|seeds|粒子|种子"),
    ("planning_needles", r"needle|needles|穿刺针|针道"),
    ("dose_isosurfaces", r"isodose|iso[-\s]?surface|等剂量面|剂量面"),
    ("planning_meshes", r"mesh|guide|网格|导板|规划网格"),
    ("segmentation", r"segmentation|structures?|分割|结构"),
    ("image", r"(?<![a-z0-9_])images?(?![a-z0-9_])|影像|图像|(?<![a-z0-9_])ct(?![a-z0-9_])"),
    ("artifacts", r"artifact(?:s)?|annotation(?:s)?|工件|产物|标注|注释"),
)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", value or ""))


def _flatten_action_entries(ui_state: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten the browser catalog into capability entries.

    The collector has intentionally been tolerant across frontend versions:
    current entries use ``actions``/``native_action`` while older snapshots
    expose ``action``/``action_capabilities``.  All forms become the same
    internal record here.
    """
    state = ui_state if isinstance(ui_state, Mapping) else {}
    # ``ui_operation_catalog`` is the preferred live contract.  Older browser
    # snapshots and the static inspector may expose the same capabilities under
    # either of the legacy keys below.  Keep the fallback data-driven so a new
    # manually available control does not need a new natural-language branch.
    raw = (
        state.get("ui_operation_catalog")
        or state.get("ui_operations")
        or state.get("action_capabilities")
        or []
    )
    if not isinstance(raw, list):
        return []
    output: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        base = dict(item)
        actions: List[Mapping[str, Any]] = []
        for key in ("native_action", "action"):
            candidate = base.get(key)
            if isinstance(candidate, Mapping):
                actions.append(candidate)
        for key in ("actions", "action_capabilities", "capabilities"):
            candidate = base.get(key)
            if isinstance(candidate, list):
                actions.extend(value for value in candidate if isinstance(value, Mapping))
        # A catalog item can describe a control with no typed action.  Keep it
        # as a generic stable-ref capability so it is still discoverable.
        if not actions and (base.get("ref") or base.get("id") or base.get("selector")):
            actions.append({
                "target": "ui.control",
                "command": str(base.get("default_command") or "click"),
                "value_source": "control",
            })
        for action in actions:
            merged = dict(base)
            merged["action"] = dict(action)
            output.append(merged)
    # A large Data Tree plus viewer toolbar commonly exceeds a thousand
    # entries.  Truncating here silently removed late-mounted groups and
    # controls, making the resolver appear random after a refresh.  The state
    # transport already bounds the overall payload; use a generous resolver
    # limit while retaining a hard safety cap.
    return output[:4096]


def _entry_blob(entry: Mapping[str, Any]) -> str:
    action = entry.get("action") if isinstance(entry.get("action"), Mapping) else {}
    pieces: List[str] = []
    for key in (
        "ref", "id", "label", "label_zh", "label_en", "title", "text", "aria_label", "aria-label",
        "aliases", "semantic_tokens", "data_ui_intents", "data-ui-intents",
        "panel", "surface", "group", "parent_ref", "node_id", "object_id",
        "object_ids", "nodeId", "objectId", "kind", "handler", "registered_events", "onclick",
        "oninput", "onchange", "oncontextmenu", "ondblclick", "onkeydown",
        "onkeyup", "onkeypress", "onwheel", "onscroll", "onsubmit", "onpointerdown", "onpointermove",
        "onpointerup", "onpointerover", "onpointerout", "onpointercancel", "onpointerenter", "onpointerleave",
        "onmousedown", "onmousemove", "onmouseup", "onmouseover", "onmouseout", "onmouseenter", "onmouseleave",
        "ondrag", "ondragstart", "ondragend", "onfocus", "onblur", "data_ui_command", "data_ui_target", "data_ui_value",
        "data_i18n_zh", "data_i18n_en", "placeholder", "action_id", "operation",
        "category", "view", "scope", "role", "tag", "type", "name", "value",
        "data_action", "data-action", "data_ui_action", "data-ui-action", "tabindex", "options", "option_values",
    ):
        value = entry.get(key)
        if isinstance(value, (list, tuple)):
            pieces.extend(_text(part) for part in value)
        elif value not in (None, ""):
            pieces.append(_text(value))
    pieces.extend(_text(action.get(key)) for key in (
        "target", "command", "value", "value_template", "semantic_property", "group",
        "action_id", "operation", "category", "view", "scope", "source",
    ) if action.get(key) not in (None, ""))
    return " ".join(pieces)


def _property_from_text(text: str) -> Optional[str]:
    for name, pattern in _PROPERTY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return None


def _property_from_entry(entry: Mapping[str, Any]) -> Optional[str]:
    action = entry.get("action") if isinstance(entry.get("action"), Mapping) else {}
    explicit = _text(action.get("semantic_property") or entry.get("semantic_property"))
    # ``action`` is the generic fallback marker, not a competing semantic
    # property. Inspect the typed target first so a declarative
    # ``data-ui-action={target: ..., command: ...}`` can still be recognized as
    # reconstruct/zoom/report/etc. when it omitted semantic_property.
    if explicit and explicit not in {"action", "control"}:
        for name, _ in _PROPERTY_PATTERNS:
            if name in explicit:
                return name
    target = _text(action.get("target"))
    if "opacity" in target or "alpha" in target:
        return "opacity"
    if "visibility" in target or "visible" in target:
        return "visibility"
    if "zoom" in target:
        return "zoom"
    if "slice" in target:
        return "slice"
    if "color" in target:
        return "color"
    if "layout" in target or target == "panel":
        return "layout" if target == "layout" else "panel"
    if "reconstruct" in target:
        return "reconstruct"
    if target == "data_tree" or "expand" in target or "collapse" in target:
        return "expansion"
    if "language" in target or "lang" in target:
        return "language"
    if "theme" in target:
        return "theme"
    if "session" in target or target == "case":
        return "session"
    if "report" in target:
        return "report"
    if target in {"chat.language", "chat.lang"}:
        return "language"
    if target in {"chat.theme", "theme"}:
        return "theme"
    # Generic controls may deliberately use target=ui.control.  Their
    # semantic property is still discoverable from the live label, aliases,
    # and data-ui-intents.  This keeps arbitrary future controls routable
    # without adding a sentence-specific branch to the resolver.
    blob = _entry_blob(entry)
    for name, pattern in _PROPERTY_PATTERNS:
        if re.search(pattern, blob, re.IGNORECASE):
            return name
    return None


def _group_from_text(text: str) -> Optional[str]:
    matches: List[Tuple[int, str]] = []
    for group, pattern in _GROUP_ALIASES:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            matches.append((match.start(), group))
    if not matches:
        return None
    # Prefer the most specific/longest match when a phrase contains both a
    # broad family and a subgroup; position breaks ties deterministically.
    return sorted(matches, key=lambda item: (item[0], -len(item[1])))[0][1]


def _group_from_entry(entry: Mapping[str, Any]) -> Optional[str]:
    action = entry.get("action") if isinstance(entry.get("action"), Mapping) else {}
    explicit = _text(action.get("group") or entry.get("group"))
    if explicit:
        for group, _ in _GROUP_ALIASES:
            if explicit == group or group in explicit:
                return group
    return _group_from_text(_entry_blob(entry))


def _command_from_text(text: str, property_name: Optional[str]) -> Optional[str]:
    # Resolve destination selectors before the generic ``切换``/``switch``
    # toggle branch.  A panel or layout control is a value-selection action;
    # treating the navigation verb as a boolean toggle can select the wrong
    # command even when the live capability is unambiguous.
    if property_name == "panel" and re.search(
        r"switch|select|choose|open|进入|切换|选择|打开", text, re.IGNORECASE
    ):
        return "switch"
    if property_name in {"layout", "tool"} and re.search(
        r"switch|select|choose|切换|选择", text, re.IGNORECASE
    ):
        return "set"
    if property_name == "expansion":
        if re.search(r"collapse|收起|折叠", text, re.IGNORECASE):
            return "collapse"
        if re.search(r"expand|展开", text, re.IGNORECASE):
            return "expand"
        if re.search(r"toggle|切换|开关", text, re.IGNORECASE):
            return "toggle"
    if property_name == "visibility":
        if re.search(r"hide|hidden|关闭|隐藏|不可见", text, re.IGNORECASE):
            return "hide"
        if re.search(r"show|visible|display|打开|显示|可见", text, re.IGNORECASE):
            return "show"
        if re.search(r"toggle|切换|开关", text, re.IGNORECASE):
            return "toggle"
    if property_name == "action" and re.search(
        r"set|make|change|adjust|turn|become|设置|设为|设成|调成|调整|改变|修改|改为|变成",
        text,
        re.IGNORECASE,
    ):
        return "set"
    # Preserve an explicitly named low-level gesture.  This is capability
    # vocabulary, not a sentence whitelist: the live catalogue still decides
    # whether the addressed element actually publishes that event.
    event_commands = (
        ("pointercancel", r"pointer[-_\s]?cancel|指针取消"),
        ("pointerdown", r"pointer[-_\s]?down|指针按下"),
        ("pointermove", r"pointer[-_\s]?move|指针移动"),
        ("pointerup", r"pointer[-_\s]?up|指针(?:抬起|松开)"),
        ("pointerover", r"pointer[-_\s]?over|指针移入"),
        ("pointerout", r"pointer[-_\s]?out|指针移出"),
        ("pointerenter", r"pointer[-_\s]?enter|指针进入"),
        ("pointerleave", r"pointer[-_\s]?leave|指针离开"),
        ("mousedown", r"mouse[-_\s]?down|鼠标按下"),
        ("mousemove", r"mouse[-_\s]?move|鼠标移动"),
        ("mouseup", r"mouse[-_\s]?up|鼠标(?:松开|抬起)"),
        ("mouseover", r"mouse[-_\s]?over|鼠标移入"),
        ("mouseout", r"mouse[-_\s]?out|鼠标移出"),
        ("mouseenter", r"mouse[-_\s]?enter|鼠标进入"),
        ("mouseleave", r"mouse[-_\s]?leave|鼠标离开"),
    )
    for event_name, pattern in event_commands:
        if re.search(pattern, text, re.IGNORECASE):
            return event_name
    if re.search(r"right[-\s]?click|contextmenu|右键|右击", text, re.IGNORECASE):
        return "contextmenu"
    if re.search(r"double[-\s]?click|dblclick|双击", text, re.IGNORECASE):
        return "doubleclick"
    if re.search(r"hover|mouses*over|悬停|鼠标移入", text, re.IGNORECASE):
        return "hover"
    if re.search(r"focus|聚焦|获得焦点", text, re.IGNORECASE):
        return "focus"
    if re.search(r"blur|失焦|取消聚焦", text, re.IGNORECASE):
        return "blur"
    if re.search(r"keydown|按下按键|按下键", text, re.IGNORECASE):
        return "keydown"
    if re.search(r"keyup|松开按键|松开键", text, re.IGNORECASE):
        return "keyup"
    if re.search(r"keypress|key\s*press|按键|按下|回车|enter|escape|esc|space|空格|tab", text, re.IGNORECASE):
        return "keypress"
    if re.search(r"scroll|wheel|滚动|滚轮", text, re.IGNORECASE):
        return "scroll"
    if re.search(r"drag|拖动|拖拽", text, re.IGNORECASE):
        return "drag"
    if re.search(r"submit|提交表单|提交", text, re.IGNORECASE):
        return "submit"
    if re.search(r"(?:input\s*event|触发输入|输入事件)", text, re.IGNORECASE):
        return "input"
    if re.search(r"(?:change\s*event|触发改变|触发变更|改变事件)", text, re.IGNORECASE):
        return "change"
    if re.search(r"increase|decrease|raise|lower|调高|调低|增加|减少", text, re.IGNORECASE):
        return "increase" if re.search(r"increase|raise|调高|增加", text, re.IGNORECASE) else "decrease"
    if re.search(r"toggle|切换|开关", text, re.IGNORECASE):
        return "toggle"
    # Navigation and lifecycle verbs are interpreted only after the live
    # capability has been selected below.  They are deliberately generic
    # operation vocabulary rather than a list of button sentences.
    if re.search(r"(?:previous|prev|back|上一步|上一项|上一层)", text, re.IGNORECASE):
        return "prev"
    if re.search(r"(?:next|forward|下一步|下一项|下一层)", text, re.IGNORECASE):
        return "next"
    if re.search(r"(?:first|beginning|首项|第一项|首层|最前)", text, re.IGNORECASE):
        return "first"
    if re.search(r"(?:last|end|末项|最后一项|末层|最后)", text, re.IGNORECASE):
        return "last"
    if re.search(r"(?:maximize|fullscreen|全屏|最大化)", text, re.IGNORECASE):
        return "toggle"
    if re.search(r"(?:minimize|restores+size|最小化|恢复大小)", text, re.IGNORECASE):
        return "toggle"
    if re.search(r"(?:undo|撤销)", text, re.IGNORECASE):
        return "undo"
    if re.search(r"(?:redo|重做)", text, re.IGNORECASE):
        return "redo"
    if property_name in {"opacity", "zoom", "color", "layout", "panel", "slice", "window", "threshold", "language", "theme", "session", "file", "report"}:
        if property_name in {"language", "theme"} and re.search(r"switch|切换|改用", text, re.IGNORECASE):
            if property_name == "theme" and not re.search(r"dark|light|深色|浅色|暗色|亮色", text, re.IGNORECASE):
                return "toggle"
            return "set"
        if re.search(r"set|make|change|adjust|turn|become|设置|设为|设成|调成|调整|改变|修改|改为|变成|让|使", text, re.IGNORECASE):
            return "set"
    if property_name == "session" and re.search(r"switch|切换|打开|进入", text, re.IGNORECASE):
        return "run"
    if property_name == "file" and re.search(r"browse|upload|选择文件|浏览|上传", text, re.IGNORECASE):
        return "run"
    if re.search(r"select|choose|选择|选中", text, re.IGNORECASE):
        return "select"
    if re.search(r"increment|decrement|increase|decrease|raise|lower|调高|调低|增加|减少", text, re.IGNORECASE):
        return "increment" if re.search(r"increment|increase|raise|调高|增加", text, re.IGNORECASE) else "decrement"
    if re.search(r"click|点击", text, re.IGNORECASE):
        return "click"
    if re.search(r"run|execute|apply|open|close|expand|collapse|reset|fit|generate|create|add|recompute|recalculate|replan|reconstruct|rebuild|start|stop|confirm|cancel|save|download|rename|move|delete|export|import|clear|solo|restore|highlight|运行|执行|应用|打开|关闭|展开|收起|重置|适配|生成|创建|新增|重算|重新计算|重新规划|重规划|重建|开始|停止|确认|取消|保存|下载|重命名|移动|删除|导出|导入|添加|清除|仅显示|恢复|高亮", text, re.IGNORECASE):
        return "run"
    return None


def _value_from_text(text: str, property_name: Optional[str]) -> Any:
    match = _PERCENT_RE.search(text)
    numeric = float(match.group(1)) if match else None
    if property_name == "opacity":
        if numeric is not None:
            return int(max(0, min(100, round(numeric))))
        if re.search(r"完全透明|透明至?底|fully\s*transparent|completely\s*transparent", text, re.IGNORECASE):
            return 0
        if re.search(r"半透明|semi[-\s]*transparent|translucent", text, re.IGNORECASE):
            return 50
        if re.search(r"不透明|opaque", text, re.IGNORECASE):
            return 100
    if property_name == "visibility":
        if re.search(r"hide|hidden|关闭|隐藏|不可见", text, re.IGNORECASE):
            return "hide"
        if re.search(r"show|visible|display|打开|显示|可见", text, re.IGNORECASE):
            return "show"
    if property_name == "color":
        color = re.search(r"#[0-9a-f]{3,8}\b", text, re.IGNORECASE)
        if color:
            return color.group(0)
        named = re.search(r"\b(red|green|blue|yellow|orange|purple|cyan|white|black)\b|红色?|绿色?|蓝色?|黄色?|橙色?|紫色?|青色?|白色?|黑色?", text, re.IGNORECASE)
        if named:
            return named.group(0)
    if property_name == "language":
        if re.search(r"中文|汉语|chinese|\bzh(?:-cn)?\b", text, re.IGNORECASE):
            return "zh"
        if re.search(r"英文|英语|english|\ben(?:-us)?\b", text, re.IGNORECASE):
            return "en"
    if property_name == "theme":
        if re.search(r"dark|深色|暗色", text, re.IGNORECASE):
            return "dark"
        if re.search(r"light|浅色|亮色", text, re.IGNORECASE):
            return "light"
    if property_name == "action":
        coordinates = re.search(
            r"(?:at|坐标|位置)\s*[:：]?\s*\(?\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*\)?",
            text,
            re.IGNORECASE,
        )
        if coordinates:
            return {
                "x": float(coordinates.group(1)),
                "y": float(coordinates.group(2)),
            }
        rename = re.search(r"(?:rename|重命名)\s*(?:to|为|成)?\s*[\"“']?([^\"”'，。,。！？!?]+)", text, re.IGNORECASE)
        if rename:
            return rename.group(1).strip()
        key = re.search(
            r"\b(enter|return|escape|esc|space|tab|backspace|delete|home|end|arrowup|arrowdown|arrowleft|arrowright)\b"
            r"|回车|返回|退出|空格|制表|退格|删除|主页|末尾|上|下|左|右",
            text,
            re.IGNORECASE,
        )
        if key:
            return key.group(0)
        if re.search(r"scroll|wheel|滚动|滚轮", text, re.IGNORECASE):
            direction = (
                "up" if re.search(r"up|向上|上滚", text, re.IGNORECASE)
                else "down" if re.search(r"down|向下|下滚", text, re.IGNORECASE)
                else "down"
            )
            return direction
        if re.search(r"drag|拖动|拖拽", text, re.IGNORECASE):
            direction = (
                "left" if re.search(r"left|向左|左移", text, re.IGNORECASE)
                else "right" if re.search(r"right|向右|右移", text, re.IGNORECASE)
                else "up" if re.search(r"up|向上|上移", text, re.IGNORECASE)
                else "down" if re.search(r"down|向下|下移", text, re.IGNORECASE)
                else ""
            )
            return direction or None
        explicit = re.search(
            r"(?:\bto\b|\bas\b|为|成|改为|设为|设成|设置为|变成)\s*[\"“']?([^\"”'，。,。！？!?]+)",
            text,
            re.IGNORECASE,
        )
        if explicit:
            candidate = explicit.group(1).strip()
            if candidate:
                return candidate
    # Operation words such as ``switch``/``select`` are not values.  For
    # panel/layout/tool/report controls the mounted capability owns the fixed
    # destination value; for a real <select>, the resolver fills it from the
    # element's live option list below.  Returning ``set`` or ``switch`` here
    # used to overwrite that value and made every selection look identical.
    if numeric is not None:
        return int(numeric) if numeric.is_integer() else numeric
    return None


def _entry_option_pairs(entry: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """Return the live options of a select-like control.

    Options are published by the browser capability catalogue.  Keeping the
    value extraction data-driven means a newly added select, report template,
    or plug-in menu can be addressed without adding a phrase branch here.
    """
    raw = entry.get("options") or entry.get("option_values") or entry.get("values")
    if not isinstance(raw, (list, tuple)):
        return []
    pairs: List[Tuple[str, str]] = []
    for item in raw:
        if isinstance(item, Mapping):
            if item.get("disabled") is True:
                continue
            value = str(item.get("value", item.get("id", item.get("key", ""))) or "").strip()
            label = str(item.get("label", item.get("text", item.get("name", value))) or value).strip()
        else:
            value = str(item or "").strip()
            label = value
        if value or label:
            pairs.append((value or label, label or value))
    return pairs


def _infer_selection_value(text: str, entry: Mapping[str, Any]) -> Optional[str]:
    """Infer a select value only from options published by that control."""
    normalized = _text(text)
    options = _entry_option_pairs(entry)
    # Prefer the longest option so a menu containing both ``liver`` and
    # ``liver_with_margin`` cannot resolve to the shorter value first.
    for value, label in sorted(options, key=lambda pair: max(len(pair[0]), len(pair[1])), reverse=True):
        for candidate in (label, value):
            candidate_text = _text(candidate)
            if not candidate_text:
                continue
            if _has_cjk(candidate_text):
                if candidate_text in normalized:
                    return value
            elif re.search(rf"(?<![a-z0-9_]){re.escape(candidate_text)}(?![a-z0-9_])", normalized, re.IGNORECASE):
                return value

    # When a custom select does not expose options yet, accept an explicit
    # ``to/为/成/as`` value but never guess from an arbitrary trailing word.
    explicit = re.search(
        r"(?:\bto\b|\bas\b|为|成)\s*[\"“']?([^\"”'，。,。！？!?\s]+)",
        normalized,
        re.IGNORECASE,
    )
    return explicit.group(1).strip() if explicit else None


def _is_mutation_turn(text: str) -> bool:
    normalized = _text(text)
    if not normalized:
        return False
    # A question such as “can I set opacity?” asks for capability/help and
    # must not modify the interface. An explicit imperative wins only when it
    # contains an actual command form ("please set ...", "把 ... 设为 ...").
    if _QUESTION_RE.search(normalized):
        # A question that merely contains an imperative-looking courtesy word
        # (for example ``请问...在哪里``) is still a read/help request.  Do
        # not mutate the UI just because the question starts with ``请`` or
        # ``can you``.  An imperative followed by a real question suffix is
        # kept conservative as well; the user can issue the command directly.
        return bool(_IMPERATIVE_RE.search(normalized)) and not bool(
            re.search(
                r"(?:请问|能否|可否|能不能|可以吗|是否|吗|呢|么|can\s+(?:i|you)|could\s+(?:i|you)|"
                r"how\s+to|怎么|如何|为什么|where\s+is|where|哪里|哪儿)",
                normalized,
                re.IGNORECASE,
            )
        )
    return bool(_IMPERATIVE_RE.search(normalized) or _ACTION_RE.search(normalized) or _LOW_LEVEL_EVENT_RE.search(normalized))


def _supports(action: Mapping[str, Any], command: str) -> bool:
    commands = action.get("commands")
    if isinstance(commands, (list, tuple, set)) and commands:
        return command in {str(value) for value in commands}
    # Live catalog entries normally publish one concrete command and omit a
    # redundant ``commands`` list.  The old default (True) made every event
    # appear supported by every element: ``pointerdown`` could be selected for
    # a layout button and ``toggle`` could replace a panel switch.  Treat the
    # declared command as the capability contract; explicit aliases below can
    # still map human wording such as "click"/"run" to that command.
    declared = str(action.get("command") or "").strip()
    return not declared or command == declared


def _requested_command_supported(
    action: Mapping[str, Any],
    requested_command: Optional[str],
    text: str,
) -> Optional[str]:
    """Map a natural-language verb to a command exposed by the capability.

    The user says what a human would do (for example, "click the 3D
    reconstruct button"), while a typed capability may call the same handler
    ``run`` or ``switch``.  The capability remains authoritative; this helper
    only accepts lossless aliases and never invents a target or value.
    """
    if not requested_command:
        declared = str(action.get("command") or "click")
        return declared if _supports(action, declared) else None
    if _supports(action, requested_command):
        return requested_command
    target = str(action.get("target") or "")
    declared = str(action.get("command") or "")
    if declared and requested_command in {"click", "run", "execute", "apply", "open", "close"}:
        if target == "ui.control":
            # Generic DOM elements are only clickable when the live catalogue
            # actually published a click capability.  A slider's ``set``
            # capability must not be mistaken for a click, while a labelled
            # button may losslessly accept the user's run/open wording.
            if requested_command == "click" and declared == "click":
                return declared
            if requested_command in {"run", "execute", "apply", "open", "close"} and declared in {"click", "run", "toggle"}:
                return declared
        elif requested_command == "click" and declared in {"run", "switch", "toggle", "set", "reset", "fit"}:
            return declared
    if declared and requested_command in {
        "doubleclick", "dblclick", "keypress", "keydown", "keyup", "submit",
        "scroll", "wheel", "drag", "hover", "focus", "blur", "contextmenu",
        "pointerdown", "pointermove", "pointerup", "pointerover", "pointerout",
        "pointercancel", "pointerenter", "pointerleave", "mousedown", "mousemove",
        "mouseup", "mouseover", "mouseout", "mouseenter", "mouseleave", "input", "change",
    }:
        event_aliases = {
            "doubleclick": {"doubleclick", "dblclick"},
            "dblclick": {"doubleclick", "dblclick"},
            "keypress": {"keypress", "keydown", "keyup"},
            "keydown": {"keydown", "keypress"},
            "keyup": {"keyup", "keypress"},
            "scroll": {"scroll", "wheel"},
            "wheel": {"wheel", "scroll"},
            "contextmenu": {"contextmenu", "rightclick"},
            "pointerdown": {"pointerdown"},
            "pointermove": {"pointermove"},
            "pointerup": {"pointerup"},
            "pointerover": {"pointerover"},
            "pointerout": {"pointerout"},
            "pointercancel": {"pointercancel"},
            "pointerenter": {"pointerenter"},
            "pointerleave": {"pointerleave"},
            "mousedown": {"mousedown"},
            "mousemove": {"mousemove"},
            "mouseup": {"mouseup"},
            "mouseover": {"mouseover"},
            "mouseout": {"mouseout"},
            "mouseenter": {"mouseenter"},
            "mouseleave": {"mouseleave"},
        }
        if target == "ui.control" and declared in event_aliases.get(requested_command, {requested_command}):
            return declared
    if target == "ui.control" and requested_command == "select" and declared in {"set", "select"}:
        return declared
    if target == "ui.control" and requested_command in {
        "run", "execute", "apply", "open", "close", "switch", "generate", "create", "add",
        "recompute", "recalculate", "replan", "start", "stop", "confirm", "cancel", "save",
        "download", "export", "import", "delete", "rename", "move", "clear", "reset", "fit",
        "next", "prev", "first", "last",
    } and declared in {
        "click", "run", "toggle", "switch", "open", "close", "execute", "apply", "generate",
        "create", "add", "recompute", "recalculate", "replan", "start", "stop", "confirm",
        "cancel", "save", "download", "export", "import", "delete", "rename", "move", "clear",
        "reset", "fit",
    }:
        # A declarative plug-in may name its action after the business verb
        # (``switch``, ``export``, ``reset``), while the actual manual UI
        # operation is still clicking that mounted control. Normalize only
        # after the live catalog has selected this exact element; this keeps
        # arbitrary controls extensible without treating a sentence as a
        # target whitelist.
        return "click"
    if target == "panel" and declared == "switch" and requested_command in {
        "run", "execute", "apply", "open", "close", "switch", "select", "click", "set",
    }:
        return declared
    if target in {"layout", "viewer.tool", "viewer.preset", "overlay.display_mode"} \
            and declared == "set" and requested_command in {
                "run", "execute", "apply", "open", "switch", "select", "click",
            }:
        return declared
    if target == "ui.control" and requested_command in {"expand", "collapse", "toggle"}:
        # A disclosure control often exposes only a click handler in the live
        # DOM, while its aria-expanded/data-ui-semantic metadata describes the
        # actual operation.  Treat the user's expansion verb as a lossless
        # click alias only when that semantic is published by the control.
        semantic = _text(action.get("semantic_property"))
        if semantic == "expansion" and declared in {"click", "toggle", "expand", "collapse"}:
            return "click" if declared == "click" else declared
    if target == "data_tree" and requested_command in {"expand", "collapse", "toggle"} and _supports(action, requested_command):
        return requested_command
    # Visibility is a semantic command for the typed tree targets, whose
    # schema deliberately uses one ``set`` command with a show/hide value.
    if target in {"tree.visibility", "tree.group.visibility", "tree.group.view_visibility"} \
            and requested_command in {"show", "hide", "toggle"} \
            and _supports(action, "set"):
        return "set"
    return None


def _entry_scope(entry: Mapping[str, Any], action: Mapping[str, Any]) -> str:
    """Return the scope advertised by a capability.

    A group operation and a leaf operation may share the same words (for
    example ``OAR`` and ``opacity``).  Keeping scope explicit lets the
    resolver prefer the group operation for “all OAR” while still selecting a
    single liver/needle/seed row when the user names that leaf.
    """
    raw = action.get("scope") or entry.get("scope")
    if raw:
        return _text(raw)
    target = _text(action.get("target"))
    if "group" in target or entry.get("group_scope") is True:
        return "group"
    if entry.get("node_id") or entry.get("object_id") or entry.get("objectId"):
        return "leaf"
    return "control"


def _specific_subject_score(text: str, entry: Mapping[str, Any], group: Optional[str]) -> float:
    """Score a named object without turning the resolver into a phrase list."""
    if group:
        return 0.0
    candidates: List[str] = []
    for key in (
        "label", "label_zh", "label_en", "title", "text", "aria_label", "placeholder",
        "name", "id", "node_id", "object_id", "objectId",
        "handler", "data_action", "data_ui_action", "data_control_id",
        "data_i18n_zh", "data_i18n_en", "semantic_property",
    ):
        value = entry.get(key)
        if value not in (None, ""):
            candidates.append(str(value))
    for key in ("aliases", "semantic_tokens", "data_ui_intents", "data-ui-intents"):
        value = entry.get(key)
        if isinstance(value, (list, tuple, set)):
            candidates.extend(str(item) for item in value)
        elif value not in (None, ""):
            candidates.append(str(value))
    # Select-like controls publish their option labels/values as part of the
    # live capability.  Treat a value explicitly named by the user as the
    # control subject, so ``选择报告模板 liver`` resolves to that exact
    # mounted select even when the surrounding UI is currently in English.
    for option_value, option_label in _entry_option_pairs(entry):
        candidates.extend((option_value, option_label))

    # Generic UI vocabulary should not make every button look like the named
    # object.  The vocabulary itself comes from the catalogue; this set merely
    # excludes operation words from object scoring.
    ignored = {
        "set", "show", "hide", "toggle", "click", "run", "apply", "reset", "generate", "create", "add",
        "recompute", "recalculate", "replan", "start", "stop", "confirm", "cancel", "save", "download",
        "maximize", "minimize", "fullscreen", "undo", "redo", "previous", "prev", "next", "first", "last",
        "opacity", "visibility", "visible", "color", "colour", "zoom", "slice",
        "layout", "panel", "tool", "reconstruct", "action", "control",
        "all", "every", "group", "button", "viewer", "data tree", "数据树",
    }
    best = 0.0
    for candidate in candidates:
        normalized = _text(candidate)
        if not normalized or normalized in ignored:
            continue
        # Explicit aliases are intentionally treated as searchable data, not
        # as hard-coded natural-language commands.  Use token containment for
        # Latin labels and substring containment for CJK/user-created labels.
        parts = [part for part in re.split(r"[^a-z0-9_]+", normalized) if part and part not in ignored]
        if any(len(part) >= 2 and re.search(rf"(?<![a-z0-9_]){re.escape(part)}(?![a-z0-9_])", text, re.IGNORECASE) for part in parts):
            best = max(best, 0.38)
        elif len(normalized) >= 2 and normalized in text:
            best = max(best, 0.34)
    return best


def _specific_label_score(text: str, entry: Mapping[str, Any]) -> float:
    """Score a mounted control label, including operation-labelled buttons.

    Subject scoring intentionally ignores words such as ``save`` and
    ``reset`` because they are operations rather than object names.  That is
    correct for preventing a random click, but it also made a uniquely
    labelled control like "保存"/"Save" impossible to address when no typed
    target existed.  This second score is restricted to the control's own
    human-facing identity and ignores only generic UI nouns, so a live label
    can authorize the exact stable ref without introducing sentence branches.
    """
    generic = {
        "button", "control", "input", "select", "option", "viewer", "canvas", "panel",
        "tab", "menu", "menuitem", "link", "toolbar", "data", "tree", "数据树", "按钮",
        "控件", "输入框", "选择器", "查看器", "面板", "菜单", "图标",
    }
    labels: List[str] = []
    for key in (
        "label", "label_zh", "label_en", "title", "text", "aria_label", "aria-label",
        "placeholder", "name", "id", "data_i18n_zh", "data_i18n_en",
    ):
        value = entry.get(key)
        if value not in (None, ""):
            labels.append(str(value))
    best = 0.0
    for label in labels:
        normalized = _text(label)
        if not normalized or normalized in generic:
            continue
        if len(normalized) >= 2 and normalized in text:
            best = max(best, 0.38)
            continue
        parts = [part for part in re.split(r"[^a-z0-9_]+", normalized) if part and part not in generic]
        if any(len(part) >= 2 and re.search(rf"(?<![a-z0-9_]){re.escape(part)}(?![a-z0-9_])", text, re.IGNORECASE) for part in parts):
            best = max(best, 0.30)
    return best


def _materialize_action(action: Mapping[str, Any], entry: Mapping[str, Any], command: str, value: Any) -> Optional[Dict[str, Any]]:
    target = str(action.get("target") or "").strip()
    if not target:
        return None
    if command not in {
        "set", "increase", "decrease", "increment", "decrement", "show", "hide",
        "toggle", "click", "doubleclick", "dblclick", "run", "reset", "switch", "select", "contextmenu", "focus", "blur",
        "keypress", "keydown", "keyup", "submit", "scroll", "wheel", "drag",
        "hover", "focus", "blur", "contextmenu", "rightclick",
        "pointerdown", "pointermove", "pointerup", "pointerover", "pointerout",
        "pointercancel", "pointerenter", "pointerleave", "mousedown", "mousemove",
        "mouseup", "mouseover", "mouseout", "mouseenter", "mouseleave", "input", "change",
        "expand", "collapse", "expand_all", "collapse_all", "next", "prev", "first", "last", "undo", "redo",
    }:
        return None
    # Context-menu capabilities are exposed as one executable ``run`` action
    # even though the user's semantic command can be show/hide/rename/etc.
    # Preserve that distinction in the browser contract; the action_id is the
    # authoritative operation identity and the command remains schema-valid.
    target = str(action.get("target") or "").strip()
    effective_command = "run" if target == "ui.context_action" else command
    if not _supports(action, effective_command):
        # Visibility controls often expose only toggle in the registry. A
        # show/hide request can be represented as the typed toggle only when
        # the browser says it supports it; never silently swap semantics.
        return None
    result: Dict[str, Any] = {"target": target, "command": effective_command}
    template = action.get("value_template")
    if target == "ui.control":
        # Generic controls are identified by the live stable ref.  Keep the
        # requested value beside that ref so the browser can dispatch the
        # correct input/change event instead of relying on a selector guess.
        payload: Dict[str, Any] = {}
        ref = entry.get("ref") or entry.get("control_ref") or entry.get("id")
        if ref:
            payload["ref"] = ref
        for key in ("label", "panel", "tag", "type", "id"):
            candidate = entry.get(key)
            if candidate not in (None, ""):
                payload[key] = candidate
        if value is not None:
            payload["value"] = value
        elif action.get("value") not in (None, "") and action.get("value_source") not in {"control", "current"}:
            # Declarative controls may publish a fixed semantic value (for
            # example a panel/layout destination). Preserve it when the user
            # only supplied the operation verb; never use the control's
            # current value as a requested value.
            payload["value"] = action.get("value")
        if action.get("checked") is not None:
            payload["checked"] = action.get("checked")
        result["value"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    elif target == "ui.context_action":
        # Context actions are published by the live browser, not guessed from
        # a translated menu label.  Preserve the complete stable identity and
        # the action-specific arguments so the browser can dispatch the same
        # handler as a human right-click menu selection.
        payload: Dict[str, Any] = {}
        for key in (
            "ref", "action_id", "operation", "object_id", "object_ids", "node_id",
            "category", "view", "source", "scope",
        ):
            candidate = action.get(key, entry.get(key))
            if candidate not in (None, "", [], {}):
                payload[key] = candidate
        ref = entry.get("ref") or entry.get("control_ref")
        if ref and "ref" not in payload:
            payload["ref"] = ref
        if value is not None and action.get("value_source") not in {"none", "fixed"}:
            payload["value"] = value
        elif action.get("value") not in (None, ""):
            payload["value"] = action.get("value")
        if action.get("action_id") in {"node_rename", "group_rename"} and value not in (None, ""):
            payload["name"] = value
            payload["new_name"] = value
        result["value"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    elif template not in (None, ""):
        try:
            result["value"] = str(template).format(value=value, group=_group_from_entry(entry) or "")
        except (KeyError, IndexError, ValueError):
            return None
    elif target in {"tree.group.opacity", "tree.group.visibility"} and _group_from_entry(entry):
        group = _group_from_entry(entry)
        if target.endswith("opacity"):
            result["value"] = f"{group},{value}"
        else:
            result["value"] = f"{group},{value}"
    elif target == "tree.group.view_visibility" and _group_from_entry(entry):
        group = _group_from_entry(entry)
        view = str(action.get("view") or entry.get("view") or "").strip().lower()
        if not view:
            view = _requested_view(str(entry.get("label") or "")) or "3d"
        result["value"] = f"{group},{view},{value}"
    elif target == "data_tree":
        # Expansion is a UI state operation on a group header.  The group is
        # carried by the live entry; the user's verb chooses expand/collapse/
        # toggle and does not need a guessed DOM selector.
        group = _group_from_entry(entry) or str(action.get("group") or "").strip()
        if not group:
            return None
        result["value"] = group
    elif target in {"tree.opacity", "tree.visibility"} and (entry.get("node_id") or entry.get("id")):
        ident = entry.get("node_id") or entry.get("id")
        if target == "tree.visibility":
            normalized = "on" if str(value).lower() in {"show", "on", "visible", "true", "1"} else "off"
            result["value"] = f"{ident},{normalized}"
        else:
            result["value"] = f"{ident},{value}"
    elif target == "tree.color":
        # The live capability stores the stable object id in its fixed value;
        # the requested colour is the semantic value from the user's turn.
        fixed = action.get("value")
        try:
            payload = json.loads(str(fixed)) if fixed not in (None, "") else {}
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if value is not None:
            payload["color"] = value
        result["value"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    elif value is not None:
        result["value"] = value
    elif action.get("value") not in (None, ""):
        result["value"] = action.get("value")
    return result


def _requested_view(text: str) -> Optional[str]:
    """Return an explicitly requested presentation view, if any."""
    if re.search(r"3d|三维|3-d", text, re.IGNORECASE):
        return "3d"
    if re.search(r"2d|二维|2-d", text, re.IGNORECASE):
        return "2d"
    return None


def _action_operation_score(text: str, entry: Mapping[str, Any]) -> float:
    """Score a capability's published operation against the user's verb.

    This is deliberately metadata-driven.  The browser publishes ``action_id``
    and a human label; the resolver compares those to the request.  It does
    not maintain a list of complete natural-language sentences, so a newly
    mounted Data Tree action can participate without a backend code change.
    """
    action = entry.get("action") if isinstance(entry.get("action"), Mapping) else {}
    if str(action.get("target") or "") != "ui.context_action":
        return 0.0
    requested_terms = (
        ("rename", "重命名"),
        ("move", "移动"),
        ("delete", "删除"),
        ("export", "导出"),
        ("import", "导入"),
        ("add", "添加"),
        ("clear", "清除"),
        ("solo", "仅显示"),
        ("restore", "恢复"),
        ("highlight", "高亮"),
        ("reconstruct|rebuild", "重建"),
        ("show", "显示"),
        ("hide", "隐藏"),
    )
    blob = _entry_blob(entry)
    score = 0.0
    for english, chinese in requested_terms:
        if re.search(english, text, re.IGNORECASE) or chinese in text:
            if re.search(english, blob, re.IGNORECASE) or chinese in blob:
                score = max(score, 0.27)
    requested_view = _requested_view(text)
    # A plain show/hide request has a typed visibility capability.  The
    # context-menu variants only participate when the user explicitly names a
    # presentation plane; otherwise they create indistinguishable candidates.
    if not requested_view and re.search(r"show|hide|显示|隐藏", text, re.IGNORECASE):
        if re.search(r"show|hide|显示|隐藏", blob, re.IGNORECASE):
            score = 0.0
        return score
    if requested_view:
        if re.search(rf"(?:^|[^a-z0-9]){requested_view}(?:$|[^a-z0-9])", blob, re.IGNORECASE) or requested_view in blob:
            score += 0.22
        else:
            # A typed all-view visibility operation is valid for a generic
            # show/hide request but is not the requested plane-specific one.
            score -= 0.08
    return score


def _context_action_matches_command(
    action: Mapping[str, Any],
    requested_command: Optional[str],
    text: str,
) -> bool:
    """Check a live context action without hard-coding user sentences."""
    if str(action.get("target") or "") != "ui.context_action":
        return False
    declared = str(action.get("command") or "run")
    if requested_command in {None, "run"}:
        return _supports(action, declared)
    if requested_command == "click":
        return _supports(action, declared)
    action_id = _text(action.get("action_id") or action.get("operation") or "")
    label = _text(action.get("label") or "")
    blob = f"{action_id} {label}"
    aliases = {
        "show": ("show", "显示"),
        "hide": ("hide", "隐藏"),
        "rename": ("rename", "重命名"),
        "move": ("move", "移动"),
        "delete": ("delete", "删除"),
        "export": ("export", "导出"),
        "add": ("add", "添加"),
        "clear": ("clear", "清除"),
        "solo": ("solo", "仅显示"),
        "restore": ("restore", "恢复"),
        "highlight": ("highlight", "高亮"),
        "reconstruct": ("reconstruct|rebuild", "重建"),
    }
    if requested_command in aliases:
        english, chinese = aliases[requested_command]
        return bool(re.search(english, blob, re.IGNORECASE) or chinese in blob)
    return False


def _typed_fallback(text: str, property_name: Optional[str], command: Optional[str], value: Any, group: Optional[str]) -> Optional[Dict[str, Any]]:
    if not property_name or not command:
        return None
    if property_name == "language" and command == "set" and value in {"zh", "en"}:
        return {
            "actions": [{"target": "chat.language", "command": "set", "value": value}],
            "source": "typed_capability_fallback",
            "confidence": 0.9,
        }
    if property_name == "theme" and command in {"set", "toggle"}:
        if command == "set" and value not in {"dark", "light"}:
            return None
        action = {"target": "chat.theme", "command": command}
        if value is not None:
            action["value"] = value
        return {
            "actions": [action],
            "source": "typed_capability_fallback",
            "confidence": 0.9,
        }
    if not group:
        return None
    if property_name == "reconstruct" and command in {"run", "click"} and group in {
        "ctv", "oar", "non_traversable", "traversable",
    }:
        return {
            "actions": [{
                "target": "tree.group.reconstruct3d",
                "command": "run",
                "value": group,
            }],
            "source": "typed_capability_fallback",
            "confidence": 0.86,
        }
    if property_name == "opacity" and command == "set" and value is not None:
        return {
            "actions": [{"target": "tree.group.opacity", "command": "set", "value": f"{group},{value}"}],
            "source": "typed_capability_fallback",
            "confidence": 0.86,
        }
    if property_name == "visibility" and command in {"show", "hide", "toggle"}:
        # The typed registry accepts show/hide through tree.group.visibility;
        # the browser adapter owns the actual boolean conversion.
        visibility = "show" if command == "show" else "hide" if command == "hide" else "toggle"
        return {
            "actions": [{"target": "tree.group.visibility", "command": "set", "value": f"{group},{visibility}"}],
            "source": "typed_capability_fallback",
            "confidence": 0.82,
        }
    return None


def resolve_ui_operation_request(
    message: str,
    ui_state: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve an imperative UI mutation against live capabilities.

    ``None`` means the turn is a read/help request or cannot yet be mapped
    safely.  A returned contract is suitable for ``ui_controller`` and always
    carries confidence/source diagnostics for trace and tests.
    """
    text = _text(message)
    if not text or not _is_mutation_turn(text):
        return None

    property_name = _property_from_text(text)
    command = _command_from_text(text, property_name)
    value = _value_from_text(text, property_name)
    group = _group_from_text(text)
    catalog = _flatten_action_entries(ui_state)
    candidates: List[Tuple[float, Dict[str, Any], Dict[str, Any]]] = []

    # A mutation must contain a UI cue or resolve to a real catalog capability;
    # this prevents clinical commands such as "run planning" being treated as
    # DOM clicks merely because they contain a general action verb.
    has_explicit_event = bool(re.search(
        r"click|right[-\s]?click|double[-\s]?click|dblclick|keypress|keydown|keyup|"
        r"scroll|wheel|drag|hover|focus|blur|pointer|mouse|input\s*event|change\s*event|"
        r"点击|右键|右击|双击|滚动|拖动|悬停|聚焦|失焦|指针|鼠标|触发输入|触发改变",
        text,
        re.IGNORECASE,
    ))
    has_ui_context = bool(_UI_CONTEXT_RE.search(text)) or property_name in {
        "opacity", "visibility", "zoom", "slice", "color", "layout", "panel", "tool",
        "expansion", "language", "theme", "session", "file", "report",
    } or (property_name == "action" and has_explicit_event)

    for entry in catalog:
        action = entry.get("action") if isinstance(entry.get("action"), Mapping) else {}
        if not action:
            continue
        # Live entries keep the semantic facet beside the executable action so
        # a plain DOM click can still be resolved as expand/collapse, zoom,
        # visibility, or another declared property without trusting a label.
        if not action.get("semantic_property") and entry.get("semantic_property"):
            action = {**action, "semantic_property": entry.get("semantic_property")}
        entry_property = _property_from_entry(entry)
        entry_group = _group_from_entry(entry)
        scope = _entry_scope(entry, action)
        blob = _entry_blob(entry)
        score = 0.0
        if property_name and entry_property == property_name:
            score += 0.44
        elif property_name and entry_property:
            # A control has two independent semantics: the subject/context it
            # belongs to (report, panel, file, ...) and the operation it can
            # perform (click/select/set/...).  The old single-property test
            # treated ``选择报告模板`` as a report *read* query and rejected
            # the live select action because the entry was classified as
            # ``action``.  Preserve strictness for competing data properties,
            # but allow a context label to match a generic action control when
            # the user's verb explicitly requests an interaction.
            contextual = {"panel", "tool", "session", "file", "report", "language", "theme"}
            if not (
                property_name == "action"
                or
                (entry_property == "action" and property_name in contextual)
                or (property_name == "action" and entry_property in contextual)
            ):
                continue
            score += 0.08
        elif property_name and not entry_property:
            # A generic DOM control is still a valid candidate when its label
            # or explicit intent matches the user's object/action.  It gets a
            # lower score than a typed capability so a typed handler wins.
            score += 0.05
        if group:
            if entry_group == group:
                score += 0.39
            elif re.search(rf"(?:^|[_.:\s-]){re.escape(group)}(?:$|[_.:\s-])", blob):
                score += 0.24
            else:
                # An explicit object family must never fall through to a
                # neighbouring family merely because it has the same property.
                continue
        elif has_ui_context:
            score += 0.05
        subject_score = _specific_subject_score(text, entry, group)
        score += subject_score
        # A control's visible/i18n label is an executable identity too. This
        # covers operation-labelled controls such as Save/Reset/导出 when the
        # page has not assigned a typed target, while remaining tied to the
        # currently mounted element rather than a phrase whitelist.
        label_score = _specific_label_score(text, entry)
        score += label_score
        # A generic DOM capability without a named subject is not executable.
        # This is the important anti-random-click boundary: “click a button”
        # must ask for clarification, while “click Generate Guide” can use
        # the exact live ref published for that button.
        target = str(action.get("target") or "")
        if target == "ui.control" and property_name == "action" and not group \
                and subject_score < 0.2 and label_score < 0.2:
            continue
        if _ALL_RE.search(text):
            if scope == "group" or (entry_group and not entry.get("node_id")):
                score += 0.17
            elif scope == "leaf":
                # Do not execute one arbitrary child when the user asked for
                # an entire family.  A proper group capability (or the typed
                # fallback below) must represent the batch operation.
                score -= 0.24
        if target == "ui.context_action":
            candidate_command = "run" if _context_action_matches_command(action, command, text) else None
        else:
            candidate_command = _requested_command_supported(action, command, text)
        if command and candidate_command:
            score += 0.10
        elif command:
            continue
        if entry.get("visible") is False or entry.get("enabled") is False or entry.get("disabled") is True:
            score -= 0.25
        if entry.get("available") is False:
            score -= 0.35
        if score <= 0:
            continue
        materialized_value = value
        if candidate_command in {"select", "set"} \
                and (str(entry.get("tag") or "").lower() == "select" or _entry_option_pairs(entry)) \
                and materialized_value is None:
            materialized_value = _infer_selection_value(text, entry)
        materialized = _materialize_action(
            action,
            entry,
            candidate_command or str(action.get("command") or "click"),
            materialized_value,
        )
        if materialized is None:
            continue
        candidates.append((score, materialized, dict(entry)))

    # Prefer the typed capability returned by the live catalog. If multiple
    # different targets are tied, report ambiguity rather than guessing.
    candidates.sort(key=lambda item: item[0], reverse=True)
    if candidates:
        best_score = candidates[0][0]
        tied = [item for item in candidates if best_score - item[0] < 0.08]
        distinct = {json.dumps(item[1], sort_keys=True, ensure_ascii=False) for item in tied}
        if len(distinct) > 1 and best_score < 0.92:
            return {
                "actions": [],
                "confidence": round(best_score, 3),
                "source": "live_ui_catalog",
                "ambiguous": True,
                "candidates": [item[1] for item in tied[:8]],
                "property": property_name,
                "target_group": group,
                "language": "zh" if _has_cjk(text) else "en",
            }
        # A simple request represents one semantic operation.  Returning all
        # matching leaf controls used to make “all OAR” apply dozens of
        # unrelated actions and caused the browser to stop after the first
        # failure.  Batch capabilities are represented by one group/context
        # action; a genuinely compound request is resolved by the semantic
        # path, not by accidental candidate fan-out.
        return {
            "actions": [candidates[0][1]],
            "confidence": round(min(0.99, best_score), 3),
            "source": "live_ui_catalog",
            "ambiguous": False,
            "candidates": [item[1] for item in candidates[:8]],
            "property": property_name,
            "target_group": group,
            "language": "zh" if _has_cjk(text) else "en",
        }

    fallback = _typed_fallback(text, property_name, command, value, group)
    if fallback:
        return {
            **fallback,
            "ambiguous": False,
            "candidates": list(fallback["actions"]),
            "property": property_name,
            "target_group": group,
            "language": "zh" if _has_cjk(text) else "en",
        }

    # An imperative UI-shaped request with no unique capability is still
    # useful to the semantic route: the model can inspect the live catalog,
    # but this resolver deliberately grants no executable action.
    if has_ui_context:
        return {
            "actions": [],
            "confidence": 0.35,
            "source": "unresolved_ui_request",
            "ambiguous": True,
            "candidates": [],
            "property": property_name,
            "target_group": group,
            "language": "zh" if _has_cjk(text) else "en",
        }
    return None


__all__ = ["resolve_ui_operation_request"]
