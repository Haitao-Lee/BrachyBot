"""
Centralized prompt management for BrachyBot.

Usage:
    from config.prompts import SYSTEM_PROMPT_TEMPLATE, SELF_EVOLUTION_DOC

    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        ui_state_summary="...",
        enhanced_context="...",
        clean_context="..."
    )
"""

import os
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent

def _load_prompt(filename: str) -> str:
    """Load a prompt file with error handling."""
    filepath = _PROMPT_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Prompt file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()

# Load prompts
SYSTEM_PROMPT_TEMPLATE = _load_prompt("system_prompt.md")
SELF_EVOLUTION_DOC = _load_prompt("SELF_EVOLUTION.md")

__all__ = ["SYSTEM_PROMPT_TEMPLATE", "SELF_EVOLUTION_DOC"]
