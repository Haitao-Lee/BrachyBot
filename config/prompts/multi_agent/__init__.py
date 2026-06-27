"""
Multi-Agent Prompts
===================
Centralized prompt management for multi-agent system.

Usage:
    from config.prompts.multi_agent import get_prompt, AGENT_PROMPTS

    # Get specific agent prompt
    router_prompt = get_prompt("router")
    plan_reviewer_prompt = get_prompt("plan_reviewer")

    # Get all prompts
    all_prompts = AGENT_PROMPTS
"""

import os
from typing import Dict, Optional

# Directory containing prompt files
PROMPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Agent prompt file mapping
AGENT_PROMPT_FILES = {
    "router": "router.md",
    "plan_reviewer": "plan_reviewer.md",
    "fact_checker": "fact_checker.md",
    "safety_guardian": "safety_guardian.md",
    "completeness_checker": "completeness_checker.md",
    "orchestrator": "orchestrator.md",
}

# Cache loaded prompts
_prompt_cache: Dict[str, str] = {}


def _load_prompt(filename: str) -> str:
    """Load a prompt from a markdown file."""
    filepath = os.path.join(PROMPTS_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return ""


def get_prompt(agent_name: str) -> str:
    """
    Get the system prompt for a specific agent.

    Args:
        agent_name: Name of the agent (router, plan_reviewer, fact_checker, safety_guardian, orchestrator)

    Returns:
        System prompt string, or empty string if not found
    """
    if agent_name not in _prompt_cache:
        filename = AGENT_PROMPT_FILES.get(agent_name)
        if filename:
            _prompt_cache[agent_name] = _load_prompt(filename)
        else:
            _prompt_cache[agent_name] = ""

    return _prompt_cache[agent_name]


def get_all_prompts() -> Dict[str, str]:
    """
    Get all agent prompts.

    Returns:
        Dict mapping agent names to their prompts
    """
    for name in AGENT_PROMPT_FILES:
        if name not in _prompt_cache:
            get_prompt(name)
    return _prompt_cache.copy()


def reload_prompts():
    """Reload all prompts from disk (useful for development)."""
    _prompt_cache.clear()
    return get_all_prompts()


# Auto-load all prompts on import
AGENT_PROMPTS = get_all_prompts()

__all__ = [
    "get_prompt",
    "get_all_prompts",
    "reload_prompts",
    "AGENT_PROMPTS",
]
