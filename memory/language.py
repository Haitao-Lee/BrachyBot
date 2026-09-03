"""
language.py — input/output language detection for the agent
============================================================

BrachyBot's agent historically had a Chinese-only UI bias: even
when the user typed English, the LLM was prompted to reply in
Chinese (because the system_prompt.md was authored in Chinese
and the i18n module defaulted to 'zh'). The user complained that
this is a "top-level issue" — they want the WHOLE
pipeline to follow their input language, not just patches here
and there.

This module is the single source of truth for "what language is
the conversation in?". The detection heuristic is intentionally
simple and deterministic — no model call, no API roundtrip —
because it runs on every chat turn and has to be fast.

Detection rules (in priority order):
1. If the caller passes an explicit conversation language, honor it.
   The web layer deliberately does not use the global UI toggle as this
   argument for an ordinary user turn; the toggle is only a fallback when
   there is no language-bearing user input yet.
2. Otherwise, count characters in the message:
     - CJK Unified Ideographs (U+4E00..U+9FFF)        → Chinese
     - CJK Unified Ideographs Extension A (U+3400..U+4DBF) → Chinese
     - Hiragana / Katakana (U+3040..U+30FF)          → Japanese
     - Hangul Syllables (U+AC00..U+D7AF)              → Korean
     - Cyrillic (U+0400..U+04FF)                       → Russian
     - Arabic (U+0600..U+06FF)                          → Arabic
   The dominant script wins (the one with the most characters
   in the message). Ties default to English.
3. If the message contains no recognized language script (for example, a
   number-only confirmation), use the caller-provided fallback. In the web
   application that fallback is the latest persisted conversation language,
   then the global UI locale.
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
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


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


def normalize_language(value: Optional[str], default: str = "en") -> str:
    """Return a supported language code from a locale-like value.

    Browser payloads and persisted snapshots may contain values such as
    ``zh-CN`` or ``en_US``.  Keeping normalization here gives every backend
    entry point the same contract and, importantly, lets callers distinguish
    an invalid/absent value by passing ``default=""``.
    """
    raw = str(value or "").strip().lower().replace("_", "-")
    if raw:
        if raw in _LANG_DISPLAY:
            return raw
        for code in _LANG_DISPLAY:
            if raw.startswith(f"{code}-"):
                return code

    fallback = str(default or "").strip().lower().replace("_", "-")
    if fallback in _LANG_DISPLAY:
        return fallback
    for code in _LANG_DISPLAY:
        if fallback.startswith(f"{code}-"):
            return code
    return ""


def _language_info(code: str, source: str) -> Dict[str, str]:
    return {
        "code": code,
        "name": _LANG_DISPLAY[code],
        "source": source,
    }


def detect(
    text: str,
    explicit: Optional[str] = None,
    fallback: Optional[str] = None,
) -> Dict[str, str]:
    """Detect the language of `text`.

    Returns a dict:
        {"code": "en"|"zh"|"ja"|"ko"|"ru"|"ar",
         "name": "English"|"中文 (Chinese)"|...,
         "source": "explicit"|"detected"|"memory"|"default"}

    The `explicit` arg wins over detection. ``fallback`` is consulted only
    when the input has no recognizable script, so a new Chinese or English
    turn always wins over a stale session/UI locale.
    """
    explicit_code = normalize_language(explicit, default="")
    if explicit_code:
        return _language_info(explicit_code, "explicit")

    fallback_code = normalize_language(fallback, default="")

    if not text or not text.strip():
        return (
            _language_info(fallback_code, "fallback")
            if fallback_code
            else _language_info("en", "default")
        )

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
        return (
            _language_info(fallback_code, "fallback")
            if fallback_code
            else _language_info("en", "default")
        )

    # Pick the dominant script.  A tie is intentionally language-neutral:
    # English is the documented fallback and avoids dictionary insertion
    # order making a mixed Chinese/Latin (or other mixed-script) message
    # appear to change language nondeterministically across entry points.
    best_count = max(counts.values())
    winners = [code for code, count in counts.items() if count == best_count]
    best_code = "en" if len(winners) > 1 and "en" in winners else winners[0]
    return _language_info(best_code, "detected")


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
        f"every clinical explanation, every markdown heading, every "
        f"table cell, and EVERY tool result you present to the user. "
        f"If the user typed in {name}, you reply in {name} — "
        f"no translation, no code-switching to another language, no "
        f"bilingual summaries. The user's language choice is the single "
        f"source of truth for output language. If the user's input is "
        f"ambiguous (e.g. mostly numbers, code, or proper nouns), "
        f"default to {name}. "
        f"CRITICAL: Even when reporting tool errors or technical output, "
        f"you MUST wrap them in {name} text. Never output raw English "
        f"error messages to a {name}-speaking user.\n"
    )


def session_language_store(
    agent_memory,
    lang_info: Optional[Dict[str, str]] = None,
) -> None:
    """Helper to keep `session_language` updated in agent memory.
    Called by the chat entry points after detection, so subsequent
    short messages (like a "yes" or "do it") don't get
    re-classified as English."""
    if agent_memory is None or not hasattr(agent_memory, "store"):
        return
    info = lang_info
    if not isinstance(info, dict):
        info = getattr(agent_memory, "_active_turn_language_info", None)
    if not isinstance(info, dict):
        try:
            info = agent_memory.retrieve("session_language") or {}
        except Exception:
            info = {}
    code = normalize_language(info.get("code"), default="")
    if not code:
        return
    payload = _language_info(code, str(info.get("source") or "memory"))
    try:
        previous = agent_memory.retrieve("session_language") or {}
        if (
            isinstance(previous, dict)
            and previous.get("code") == payload["code"]
            and previous.get("name") == payload["name"]
        ):
            return
        agent_memory.store("session_language", payload)
    except Exception as exc:
        logger.debug("Could not persist session language: %s", exc)


def get_session_language(agent_memory) -> Dict[str, str]:
    """Read the most recent non-ambiguous language from memory.
    Used as the fallback for very short messages."""
    try:
        prev = agent_memory.retrieve("session_language") or {}
        code = normalize_language(prev.get("code"), default="") if isinstance(prev, dict) else ""
        if code:
            return _language_info(code, str(prev.get("source") or "memory"))
    except Exception as exc:
        logger.debug("Could not read session language from agent memory: %s", exc)
    return {"code": "en", "name": _LANG_DISPLAY["en"], "source": "default"}
