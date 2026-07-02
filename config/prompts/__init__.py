"""
Centralized prompt management for BrachyBot.

Architecture:
    - SYSTEM_PROMPT_TEMPLATE: core prompt, always loaded.
    - get_prompt_modules(message): optional modules loaded by intent triggers.
"""

import re
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent


def _load_prompt(filename: str) -> str:
    """Load a prompt file with error handling."""
    filepath = _PROMPT_DIR / filename
    if not filepath.exists():
        return ""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


SYSTEM_PROMPT_TEMPLATE = _load_prompt("system_prompt.md")

MODULES = {
    "medical_safety": _load_prompt("medical_safety.md"),
    "search_guide": _load_prompt("search_guide.md"),
    "memory_recall": _load_prompt("memory_recall.md"),
    "security": _load_prompt("security.md"),
    "tool_routing": _load_prompt("tool_routing.md"),
    "planning_agent": _load_prompt("planning_agent.md"),
    "clinical_kb": _load_prompt("clinical_kb.md"),
    "formatting": _load_prompt("formatting.md"),
    "visual_proactive": _load_prompt("visual_proactive.md"),
}


_MODULE_TRIGGERS = {
    "security": [
        r"(?:ignore.*prompt|forget.*instruction|system prompt|jailbreak|injection|DAN|roleplay.*as)",
    ],
    "memory_recall": [
        r"(?:recall|remember|what did.*discuss|prior conversation|previous session|earlier.*talk)",
    ],
    "clinical_kb": [
        r"(?:dose constraint|organ tolerance|clinical guideline|treatment protocol|prescription dose|dose limit)",
        r"(?:V100|D90|V200|D2cc|D0\.1cc|DVH.*constraint|dose.*standard)",
        r"(?:what.*dose|how much.*dose|recommended.*dose|standard.*dose|dose.*require)",
        r"(?:ABS|GEC.?ESTRO|AAPM|ICRU|NCCN|TG.?(?:43|186|229|137))",
        r"(?:clinical_kb|knowledge base|clinical knowledge|knowledge.*query|source_search)",
        r"(?:detailed.*introduction.*particle|particle.*implant.*introduction|brachytherapy.*overview|seed.*implant.*overview)",
        r"(?:spinal cord.*dose|cord.*tolerance)",
        r"(?:知识库|临床知识|指南|共识|文献|论文|证据|出处|引用|参考文献)",
        r"(?:剂量限制|剂量约束|剂量标准|处方剂量|器官耐受|危及器官|安全阈值)",
        r"(?:粒子植入.*(?:好处|优势|适应症|禁忌|为什么)|近距离治疗.*(?:好处|优势|适应症|禁忌|为什么))",
    ],
    # Execution-only planning triggers. Conceptual questions that mention
    # brachytherapy should load clinical_kb, not the planning workflow module.
    "planning_agent": [
        r"(?:execute|run|start|perform|generate|create|calculate|optimi[sz]e).*(?:plan|planning|seed|trajectory)",
        r"(?:执行|运行|开始|生成|创建|计算|优化|自动).*(?:规划|计划|路径|轨迹|布源|粒子)",
        r"(?:帮我|请).*(?:规划一下|做.*规划|生成.*计划|算.*剂量)",
        r"(?:^|\s)(?:segment.*(?:ctv|tumor|tumour|lesion)|segment.*(?:oar|organ))",
        r"(?:分割.*(?:ctv|靶区|肿瘤|病灶)|分割.*(?:oar|危及器官|器官))",
        r"(?:full.*plan|plan.*full|complete.*plan|完整.*规划|全流程.*规划)",
        r"(?:planning_pipeline|ctv_segmentation|oar_segmentation|trajectory|seed.*plann)",
    ],
    "tool_routing": [
        r"(?:which tool|what tool|tool.*(?:use|call|need)|use.*tool|call.*tool)",
        r"(?:dose_engine|dose_evaluation|planning_pipeline|ctv_segmentation|oar_segmentation)",
        r"(?:trajectory_planning|seed_planning|clinical_kb|web_search|ui_controller|ui_screenshot)",
        r"(?:report_generator|safety_validator|plan_comparator|code_executor)",
        r"(?:execute.*plan|run.*plan|start.*plan|segment.*(?:ctv|oar|tumor))",
        r"(?:执行.*规划|生成.*规划|分割.*(?:ctv|oar|靶区|器官))",
        r"(?:full.*plan|plan.*full|complete.*plan|完整.*规划|全流程.*规划)",
    ],
    "medical_safety": [
        r"(?:dose constraint|OAR limit|organ tolerance|DVH|safety check|dose verification)",
        r"(?:QUANTEC|tolerance|OAR.*dose|organ.*dose|normal tissue)",
        r"(?:安全|剂量限值|耐受剂量|危及器官.*剂量|正常组织)",
    ],
    "search_guide": [
        r"(?:web_search|web_fetch|search.*result|search.*(?:for|find|query))",
        r"(?:cite|source|reference|full.?text|pubmed|search)",
        r"(?:联网|搜索|检索|来源|引用|参考文献|pubmed|doi)",
    ],
    "formatting": [
        r"(?:generate.*report|create.*report|export.*report|PDF.*report|clinical.*report)",
        r"(?:生成.*报告|导出.*报告|临床报告|PDF.*报告)",
    ],
    "visual_proactive": [
        r"(?:screenshot|capture|annotate|show.*(?:UI|viewer|image|3D|slice))",
        r"(?:DVH|dose.?volume|histogram|剂量体积|直方图|剂量分布|截图)",
        r"(?:axial|sagittal|coronal|data.tree|overlay|what does.*look)",
        r"(?:轴向|矢状|冠状|数据树|叠加|显示|看看)",
    ],
}


def get_prompt_modules(message: str) -> str:
    """
    Return relevant prompt modules based on message content.
    Only modules whose trigger patterns match are included.
    """
    msg_lower = message.lower()
    parts = []
    seen = set()

    for module_name, patterns in _MODULE_TRIGGERS.items():
        if module_name in seen:
            continue
        for pattern in patterns:
            if re.search(pattern, msg_lower, re.IGNORECASE):
                content = MODULES.get(module_name, "")
                if content and module_name not in seen:
                    parts.append(content)
                    seen.add(module_name)
                break

    return "\n\n".join(parts)


__all__ = ["SYSTEM_PROMPT_TEMPLATE", "get_prompt_modules"]
