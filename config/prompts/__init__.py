"""
Prompts module for BrachyBot.
Loads system prompts from markdown files.
"""

import os
from pathlib import Path

# Get the directory of this file
_PROMPTS_DIR = Path(__file__).parent

def _load_prompt(filename: str) -> str:
    """Load a prompt from a markdown file."""
    filepath = _PROMPTS_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Prompt file not found: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract the string value from the Python assignment
    # Look for SYSTEM_PROMPT = """..."""
    if 'SYSTEM_PROMPT = """' in content:
        start = content.find('SYSTEM_PROMPT = """') + len('SYSTEM_PROMPT = """')
        end = content.find('"""', start)
        if end != -1:
            return content[start:end].strip()

    # Fallback: return the entire content
    return content

# Load the system prompt
SYSTEM_PROMPT = _load_prompt("system_prompt.md")

__all__ = ['SYSTEM_PROMPT']
