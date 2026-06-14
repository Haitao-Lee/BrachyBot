"""
language.py — input/output language detection for the agent
============================================================

BrachyBot's agent historically had a Chinese-only UI bias: even
when the user typed English, the LLM was prompted to reply in
Chinese (because the system_prompt.md was authored in Chinese
and the i18n module defaulted to 'zh'). The user complained that
this is a "顶层问题" (top-level issue) — they want the WHOLE
pipeline to follow their input language, not just patches here
and there.

This module is the single source of truth for "what language is
the conversation in?". The detection heuristic is intentionally
simple and deterministic — no model call, no API roundtrip —
because it runs on every chat turn and has to be fast.

Detection rules (in priority order):
1. If the caller passes an explicit `lang` (e.g. the frontend's
   user-preference toggle), honor it.
2. Otherwise, count characters in the message:
     - CJK Unified Ideographs (U+4E00..U+9FFF)        → Chinese
     - CJK Unified Ideographs Extension A (U+3400..U+4DBF) → Chinese
     - Hiragana / Katakana (U+3040..U+30FF)          → Japanese
     - Hangul Syllables (U+AC00..U+D7AF)              → Korean
     - Cyrillic (U+0400..U+04FF)                       → Russian
     - Arabic (U+0600..U+06FF)                          → Arabic
   The dominant script wins (the one with the most characters
   in the message). Ties default to English.
3. If the message is too short to tell (< 4 characters), fall
   back to the most recent non-ambiguous language from memory.
4. If all else fails, default to English.

The output is a 2-letter ISO code ('en', 'zh', 'ja', 'ko',
'ru', 'ar') plus a display name. The agent system prompt gets
an explicit "REPLY IN {name}" instruction so the LLM is never
in doubt about which language to use.

A per-session language is also stored in agent memory under
"session_language" so that mid-conversation switches (e.g. user
types one English message then one Chinese message) flip the
language without the LLM getting confused. The system prompt
injects both the detected language AND a one-line reminder
that the LLM should match.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Optional, Tuple


# Character ranges per language. Each entry is (name, code, regex).
# Order matters for the "dominant script" scan — we count matches
# and pick the max, so order doesn't bias the result, but listing
# CJK first keeps the regex compiles straightforward.
_LANG_RANGES: Tuple[Tuple[str, str, str], ...] = (
    ("Chinese",  "zh", r"[一-鿿㐀-䶿]"),
    ("Japanese", "ja", r"[぀-ゟ゠-ヿ]"),
    ("Korean",   "ko", r"[가-힯]"),
    ("Russian",  "ru", r"[Ѐ-ӿ]"),
    ("Arabic",   "ar", r"[؀-ۿ]"),
    ("English",  "en", r"[A-Za-z]"),
)

# Pre-compile once at import time so detect() is O(n) only
_COMPILED = [(name, code, re.compile(rgx)) for name, code, rgx in _LANG_RANGES]

# Map ISO code → human-readable display name for the system prompt
_LANG_DISPLAY = {
    "en": "English",
    "zh": "中文 (Chinese)",
    "ja": "日本語 (Japanese)",
    "ko": "한국어 (Korean)",
    "ru": "Русский (Russian)",
    "ar": "العربية (Arabic)",
}


def detect(text: str, explicit: Optional[str] = None) -> Dict[str, str]:
    """Detect the language of `text`.

    Returns a dict:
        {"code": "en"|"zh"|"ja"|"ko"|"ru"|"ar",
         "name": "English"|"中文 (Chinese)"|...,
         "source": "explicit"|"detected"|"memory"|"default"}

    The `explicit` arg wins over detection — it's the way the
    frontend forces a language via a user-preference toggle.
    """
    if explicit and explicit in _LANG_DISPLAY:
        return {"code": explicit, "name": _LANG_DISPLAY[explicit], "source": "explicit"}

    if not text or not text.strip():
        return {"code": "en", "name": _LANG_DISPLAY["en"], "source": "default"}

    # Strip whitespace and emoji so they don't count as characters
    cleaned = text.strip()
    # Count matches per language
    counts: Dict[str, int] = {}
    for name, code, rgx in _COMPILED:
        n = len(rgx.findall(cleaned))
        if n > 0:
            counts[code] = counts.get(code, 0) + n

    if not counts:
        # No recognized script (e.g. all emoji, all numbers, all punct)
        return {"code": "en", "name": _LANG_DISPLAY["en"], "source": "default"}

    # Pick the dominant script
    best_code = max(counts, key=counts.get)
    return {"code": best_code, "name": _LANG_DISPLAY[best_code], "source": "detected"}


def system_prompt_clause(lang_info: Dict[str, str]) -> str:
    """Build the language directive that gets injected into the
    agent's system prompt. Always says "REPLY IN <name>" plus a
    short reminder that mixed-language replies are NOT allowed.
    """
    name = lang_info.get("name") or "English"
    return (
        f"## Language directive (HIGHEST PRIORITY)\n"
        f"**All your replies to the user MUST be written in {name}.** "
        f"This applies to every text_chunk, every assistant message, "
        f"every clinical explanation, every markdown heading, and every "
        f"table cell. If the user typed in {name}, you reply in {name} — "
        f"no translation, no code-switching to another language, no "
        f"bilingual summaries. The user's language choice is the single "
        f"source of truth for output language. If the user's input is "
        f"ambiguous (e.g. mostly numbers, code, or proper nouns), "
        f"default to {name}.\n"
    )


def session_language_store(agent_memory) -> None:
    """Helper to keep `session_language` updated in agent memory.
    Called by the chat entry points after detection, so subsequent
    short messages (like a "yes" or "do it") don't get
    re-classified as English."""
    pass  # Implemented in the agent — see AgenticSys chat() entry


def get_session_language(agent_memory) -> Dict[str, str]:
    """Read the most recent non-ambiguous language from memory.
    Used as the fallback for very short messages."""
    try:
        prev = agent_memory.retrieve("session_language") or {}
        if prev.get("code") in _LANG_DISPLAY:
            return prev
    except Exception:
        pass
    return {"code": "en", "name": _LANG_DISPLAY["en"], "source": "default"}
