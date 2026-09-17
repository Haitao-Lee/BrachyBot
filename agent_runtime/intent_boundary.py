"""Conservative syntax boundary for zero-model resource shortcuts.

These predicates grant a shortcut, not an intent. Unknown wording is handled
by the primary function-calling model with the original message and context.
Never infer a requested action solely from a resource noun.
"""
import re


_PREFIX = r"(?:(?:请问|请|麻烦|帮我|给我|我想|我要|你可以|可以|能否|能不能)\s*)*"
_READ = r"(?:查看|看看|看一下|看|显示|打开|展示|呈现)"
_EN_READ = r"(?:(?:please|can you|could you|would you|i want to)\s+)*(?:show|view|open|display|see|look at)(?:\s+me)?\s+"
_RESOURCE = (
    r"(?:当前|这个|本|全部|所有|已保存|保存的|历史|最新|最后|第一|第\d+|一张|张|中的|里的|的|和|与|结果|内容|选中|节点|"
    r"报告|截图|图片|图像|图件|正文|规划|剂量|指标|手术导板|穿刺导板|导板|结构|分割|影像|数据树|对话历史|执行追踪|会话|病例|附件|回复|上一次|上一条|刚才|"
    r"ct|ctv|oar|dvh|data tree|session|workspace|current|the|all|saved|previous|last|latest|first|selected|"
    r"report|figures?|screenshots?|images?|pictures?|results?|structures?|segmentations?|masks?|planning|dose|metrics?|"
    r"surgical guide|puncture guide|chat history|execution trace|attachments?|reply|response|item|object|node|in|from|of|and|\s)+"
)


def _text(message):
    return re.sub(r"\s+", " ", str(message or "").strip().lower()).strip(" .!?。！？")


def has_explicit_read_request(message):
    """Resource discovery may recognize a positive read clause, not a noun."""
    text = _text(message)
    return bool(re.match(_PREFIX + _READ, text) or re.match(_EN_READ, text))


def canonical_resource_read(message):
    """Every token must belong to one positive read command and its object."""
    text = _text(message)
    if len(text) > 240:
        return False
    return bool(re.fullmatch(
        r"(?:" + _PREFIX + _READ + r"\s*|" + _EN_READ + r")"
        + _RESOURCE + r"(?:吗|么|吧)?", text
    ))


# The object of a report-generation command is the report noun, optionally
# qualified by one or more report-domain words.  "报告" is the protected
# object here: a qualifier such as "手术" (surgical) modifies the report and
# must not let a guide rule claim the turn.  Only qualifiers that keep the
# phrase a positive command are accepted, so status/location wordings such
# as "报告已生成" or "生成的报告在哪里" still fail the whole-utterance match.
_REPORT_OBJECT_QUALIFIER = (
    r"(?:当前|完整|整个|本次|这个|一份|新的|最新|最终|详细|简要|标准|正式|"
    r"手术|穿刺|治疗|剂量|计划|规划|临床|术后|术中|病例|患者|"
    r"的|\s)*"
)
_EN_REPORT_OBJECT_QUALIFIER = (
    r"(?:(?:the|current|full|complete|final|surgical|treatment|dose|plan|"
    r"planning|clinical|patient)\s+)*"
)


def canonical_report_generation(message):
    """Thin adapter over the shared structural parser.

    The report must be the object of a command-position generation verb.
    Qualifier content (``手术``/``剂量``/``分析``/``验证`` ...) does not change
    the requested action; negation, conditions, questions and quoted text do.
    """
    from agent_runtime import request_parse

    return request_parse.canonical_report_mutation(message)
