"""
Centralized prompt management for BrachyBot.

Architecture:
    - SYSTEM_PROMPT_TEMPLATE: Core prompt (always loaded, ~80 lines)
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
}

# Keywords that trigger each module — keep specific to avoid over-triggering
_MODULE_TRIGGERS = {
    "medical_safety": [
        r"(?:dose constraint|剂量限制|OAR limit|危及器官|organ tolerance|耐受量|DVH|safety check|安全检查|剂量验证)",
    ],
    "search_guide": [
        r"(?:web_search|web_fetch|搜索结果|search result|cite|引用|source|来源|参考文献)",
    ],
    "memory_recall": [
        r"(?:recall|remember|回忆|记得|提醒我|之前.*讨论|上次.*说|prior conversation|previous session)",
    ],
    "security": [
        r"(?:ignore.*prompt|forget.*instruction|忽略.*规则|system prompt|jailbreak|越狱|injection|注入|DAN|roleplay.*as|假装.*是)",
    ],
}

def get_prompt_modules(message: str) -> str:
    """
    Return relevant prompt modules based on message content.
    Only loads modules whose trigger keywords appear in the message.
    """
    msg_lower = message.lower()
    parts = []

    for module_name, patterns in _MODULE_TRIGGERS.items():
        for pattern in patterns:
            if re.search(pattern, msg_lower, re.IGNORECASE):
                content = MODULES.get(module_name, "")
                if content:
                    parts.append(content)
                break  # One match is enough per module

    return "\n\n".join(parts)


__all__ = ["SYSTEM_PROMPT_TEMPLATE", "get_prompt_modules"]
