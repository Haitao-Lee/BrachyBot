"""Turn-level response presentation policy.

The model remains responsible for understanding the user's request and for
writing the actual answer.  This module only describes the presentation
contract that the runtime and browser must preserve at the response boundary:
an information-seeking or mixed request needs an explanation, while a pure
action request needs a concise factual status.  It deliberately contains no
exact-question-to-answer map.
"""

from dataclasses import asdict, dataclass
import re
from typing import Any, Dict, Iterable


_QUESTION_RE = re.compile(
    r"(?:[?？]\s*$|(?:吗|呢|么)\s*$|"
    r"(?:是不是|是否|有没有|能不能|可不可以|为什么|为何|哪里|哪儿|"
    r"怎么|如何|什么|哪个|哪些|谁|多少|多久|是否可以)|"
    r"\b(?:what|which|where|when|why|who|how|whether|can|could|is|are|"
    r"did|does|do)\b)",
    re.IGNORECASE,
)
_ACTION_RE = re.compile(
    r"(?:^\s*(?:请|帮我|麻烦|执行|进行|生成|显示|加载|刷新|删除|添加|"
    r"修改|编辑|重算|重新|导出|打开|截图|分割|规划|启动|停止|查看)|"
    r"^\s*\b(?:please|run|execute|generate|show|display|load|refresh|delete|"
    r"add|edit|move|recompute|replan|export|open|capture|segment|plan|"
    r"start|stop|create|update)\b)",
    re.IGNORECASE,
)
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


@dataclass(frozen=True)
class ResponseContract:
    """Small, serializable contract shared by server and browser.

    ``text_required`` is intentionally true for every visible turn.  The
    distinction is in ``act`` and ``presentation_mode``: questions and mixed
    requests must retain explanatory prose alongside evidence, whereas a
    command may use a short execution/status sentence.  A hidden visual child
    also needs text internally so its interpretation can be merged into the
    owning visible reply.
    """

    version: int = 1
    act: str = "statement"
    language: str = "en"
    text_required: bool = True
    evidence_supplemental: bool = False
    presentation_mode: str = "status"
    source: str = "runtime_request_contract"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _has_question_signal(message: str) -> bool:
    value = re.sub(r"\s+", " ", str(message or "").strip())
    return bool(value and _QUESTION_RE.search(value))


def _has_action_signal(message: str) -> bool:
    value = re.sub(r"\s+", " ", str(message or "").strip())
    return bool(value and _ACTION_RE.search(value))


def build_response_contract(
    message: str,
    *,
    internal_followup: bool = False,
) -> ResponseContract:
    """Build presentation metadata from the current request only.

    This is not an answer whitelist and does not select a tool.  It gives the
    LLM and the frontend a shared invariant so a screenshot transport event
    cannot erase a needed textual answer.
    """
    question = _has_question_signal(message)
    action = _has_action_signal(message)
    value = re.sub(r"\s+", " ", str(message or "").strip())
    # A noun phrase such as "生成结果在哪里" contains an action-looking
    # word, but is still one information-seeking question. Treat a turn as
    # mixed only when a command clause is explicitly separated from the
    # question clause (or uses a clear polite imperative prefix).
    explicit_command_clause = bool(
        re.match(r"^\s*(?:请|帮我|麻烦|please)(?:\s|$)", value, re.IGNORECASE)
        or re.search(r"[,，;；]\s*(?:请|帮我|麻烦|please|run|show|display|load|refresh|generate|执行|显示|加载|刷新|生成)", value, re.IGNORECASE)
        or re.search(r"^\s*\S+[,，;；].*(?:[?？]|吗|呢|为什么|为何|哪里|怎么|如何)\s*$", value, re.IGNORECASE)
    )
    if question and action and explicit_command_clause:
        act = "mixed"
    elif question:
        act = "question"
    elif action:
        act = "command"
    else:
        act = "statement"

    language = "zh" if _CJK_RE.search(str(message or "")) else "en"
    if act in {"question", "mixed"}:
        mode = "explain_with_evidence"
    elif act == "command":
        mode = "status_with_evidence"
    else:
        mode = "answer_with_evidence"

    # ``internal_followup`` is retained as an argument for callers that need
    # to make the visibility distinction explicit.  The child still requires
    # a substantive answer for the parent reply, so the contract stays true.
    _ = internal_followup
    return ResponseContract(
        act=act,
        language=language,
        text_required=True,
        evidence_supplemental=act in {"question", "mixed"},
        presentation_mode=mode,
    )


def response_presentation_instruction(contract: ResponseContract) -> str:
    """Return a model instruction without prescribing wording or tool calls."""
    act = contract.act
    if act == "question":
        lead = (
            "The current user turn is information-seeking. Answer the question "
            "directly with a concise explanation grounded in this turn's evidence."
        )
    elif act == "mixed":
        lead = (
            "The current user turn combines an action and a question. State what "
            "was done or found, then answer the question directly."
        )
    elif act == "command":
        lead = (
            "The current user turn is primarily an action request. Give a concise, "
            "factual completion or failure status and the key result."
        )
    else:
        lead = "Answer the current user turn directly and keep the response focused."
    return (
        "\n### Response presentation contract\n"
        f"{lead}\n"
        "Screenshots or other UI evidence are supplemental to the text; never use "
        "an attachment-only response when a textual explanation or status is "
        "appropriate. Never emit an empty assistant answer. Use the same language "
        "as the user's current request. Do not copy a canned response or answer a "
        "previous turn. Report only facts supported by the current tool results.\n"
    )


def presentation_fallback_message(
    lang: str,
    message: str = "",
    tool_names: Iterable[str] = (),
) -> str:
    """Provide a non-empty, honest fallback for a presentation-only turn.

    This is selected by typed tool metadata, not by matching a particular user
    sentence.  It does not claim that a screenshot was uploaded until the
    browser has returned the attachment result.
    """
    is_zh = str(lang or "").lower().startswith("zh")
    contract = build_response_contract(message)
    names = {str(name or "").strip().lower() for name in tool_names}
    has_visual = bool(names & {"ui_screenshot", "ui_content"})
    if is_zh:
        if has_visual and contract.act in {"question", "mixed"}:
            return (
                "对应的 Viewer/Data Tree 截图已保留在本条回复中，但当前没有得到可验证的图像解读，"
                "因此没有盲目标注。若需要定位具体对象，请直接告诉我对象名称，我会基于当前可见状态重新核对。"
            )
        if has_visual:
            return "截图已保留在本条回复中；当前没有生成额外的文字解读。"
        return "本轮没有生成可展示的文字回复；当前病例和规划未因此被修改，请重试。"
    if has_visual and contract.act in {"question", "mixed"}:
        return (
            "The relevant Viewer/Data Tree screenshot is preserved in this reply, but no "
            "verified visual interpretation was returned, so I did not annotate it blindly. "
            "Name the object you want located and I will re-check the currently visible state."
        )
    if has_visual:
        return "The screenshot is preserved in this reply; no additional textual interpretation was generated."
    return "No user-facing text was generated in this turn; the case and Planning were not changed. Please retry."
