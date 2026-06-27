"""
Centralized prompt management for BrachyBot.

Architecture:
    - SYSTEM_PROMPT_TEMPLATE: Core prompt (always loaded, ~100 lines)
    - Optional modules loaded on demand via get_prompt_modules()

Usage:
    from config.prompts import SYSTEM_PROMPT_TEMPLATE, get_prompt_modules

    # Core prompt (always loaded)
    prompt = SYSTEM_PROMPT_TEMPLATE.format(...)

    # Add modules based on message context
    modules = get_prompt_modules(message)
    full_prompt = prompt + "\\n\\n" + modules
"""

import os
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

# Core prompt (always loaded)
SYSTEM_PROMPT_TEMPLATE = _load_prompt("system_prompt.md")

# Optional modules (loaded on demand)
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

# Keywords that trigger each module.
# Order matters: more specific modules should be checked first.
# Each module is triggered if ANY of its patterns match.
_MODULE_TRIGGERS = {
    # Security — highest priority, check first
    "security": [
        r"(?:ignore.*prompt|forget.*instruction|system prompt|jailbreak|injection|DAN|roleplay.*as)",
    ],
    # Memory recall
    "memory_recall": [
        r"(?:recall|remember|what did.*discuss|prior conversation|previous session|earlier.*talk)",
    ],
    # Clinical knowledge — dose constraints, guidelines, tolerances
    "clinical_kb": [
        r"(?:dose constraint|organ tolerance|clinical guideline|treatment protocol|prescription dose|dose limit)",
        r"(?:V100|D90|V200|D2cc|D0\.1cc|DVH.*constraint|dose.*standard)",
        r"(?:what.*dose|how much.*dose|recommended.*dose|standard.*dose|dose.*require)",
        r"(?:ABS|GEC.?ESTRO|AAPM|ICRU|NCCN|TG.?(?:43|229|137))",
        r"(?:clinical_kb|knowledge base|clinical knowledge|knowledge.*query)",
        r"(?:detailed.*introduction.*particle|particle.*implant.*introduction|brachytherapy.*overview|seed.*implant.*overview)",
        r"(?:spinal cord.*dose|cord.*tolerance)",
    ],
    # Planning agent — brachytherapy planning workflow
    "planning_agent": [
        r"(?:execute.*plan|run.*plan|start.*plan|perform.*plan)",
        r"(?:brachytherapy|particle.*implant|seed.*implant|implant.*plan|treatment.*plan)",
        r"(?:segment.*(?:ctv|tumor|tumour|lesion))",
        r"(?:segment.*(?:oar|organ))",
        r"(?:full.*plan|plan.*full|complete.*plan)",
        r"(?:planning_pipeline|ctv_segmentation|oar_segmentation|trajectory|seed.*plann)",
    ],
    # Tool routing — when user asks about tools or invokes planning/segmentation
    "tool_routing": [
        r"(?:which tool|what tool|tool.*(?:use|call|need)|use.*tool|call.*tool)",
        r"(?:dose_engine|dose_evaluation|planning_pipeline|ctv_segmentation|oar_segmentation)",
        r"(?:trajectory_planning|seed_planning|clinical_kb|web_search|ui_controller|ui_screenshot)",
        r"(?:report_generator|safety_validator|plan_comparator|code_executor)",
        r"(?:execute.*plan|run.*plan|start.*plan|segment.*(?:ctv|oar|tumor))",
        r"(?:full.*plan|plan.*full|complete.*plan)",
    ],
    # Medical safety — OAR limits, QUANTEC
    "medical_safety": [
        r"(?:dose constraint|OAR limit|organ tolerance|DVH|safety check|dose verification)",
        r"(?:QUANTEC|tolerance|OAR.*dose|organ.*dose|normal tissue)",
    ],
    # Search guide — web search rules
    "search_guide": [
        r"(?:web_search|web_fetch|search.*result|search.*(?:for|find|query))",
        r"(?:cite|source|reference|full.?text|pubmed|search)",
    ],
    # Formatting — report generation, visual formatting
    "formatting": [
        r"(?:generate.*report|create.*report|export.*report|PDF.*report|clinical.*report)",
    ],
    # Visual proactive — screenshots, viewers
    "visual_proactive": [
        r"(?:screenshot|capture|annotate|show.*(?:UI|viewer|image|3D|slice))",
        r"(?:axial|sagittal|coronal|data.tree|overlay|what does.*look)",
    ],
}

def get_prompt_modules(message: str) -> str:
    """
    Return relevant prompt modules based on message content.
    Only loads modules whose trigger keywords appear in the message.
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
                break  # One match is enough per module

    return "\n\n".join(parts)


__all__ = ["SYSTEM_PROMPT_TEMPLATE", "get_prompt_modules"]
