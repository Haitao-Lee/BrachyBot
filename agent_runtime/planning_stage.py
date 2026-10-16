"""Planning-stage gates shared by routing and workflow recovery.

The clinical planning pipeline is shared by the legacy single-workspace path
and the timepoint-scoped path.  This module keeps the one policy that must be
identical in both places: a preoperative plan may materialize its guide as a
downstream artifact, while an intraoperative re-plan must not silently replace
an existing guide unless the user explicitly asks for guide generation.

No natural-language routing is performed here.  The stage comes from the
captured execution context; the small explicit-guide check is only a safety
exception for an already-authorized user request.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_INTRAOPERATIVE_STAGES = frozenset({
    "intraoperative", "intra-operative", "intraop", "intra-op",
})


def active_planning_stage(owner: Any) -> str:
    """Return the captured planning stage, or ``''`` for legacy workspaces."""

    context = getattr(owner, "_workspace_timepoint_context", None)
    target = getattr(context, "target", None)
    stage = getattr(target, "stage", None)
    if stage is None and isinstance(target, Mapping):
        stage = target.get("stage")

    # Detached timepoint execution also stores a small, immutable copy in
    # memory.  It is useful when a view wrapper has not yet copied the full
    # context onto the temporary agent object.
    if stage is None:
        memory = getattr(owner, "memory", None)
        retrieve = getattr(memory, "retrieve", None)
        if callable(retrieve):
            try:
                stored = retrieve("timepoint_context")
            except Exception:
                stored = None
            if isinstance(stored, Mapping):
                stage = stored.get("stage")

    return str(stage or "").strip().lower()


def is_intraoperative(owner: Any) -> bool:
    return active_planning_stage(owner) in _INTRAOPERATIVE_STAGES


def _explicit_guide_request(message: str) -> bool:
    """Use the canonical guide classifier only as an explicit exception."""

    try:
        from agent_runtime.turn_policy import is_surgical_guide_generation_request
        return bool(is_surgical_guide_generation_request(message))
    except Exception:
        # A routing import must never make a clinical request fail.  This
        # conservative fallback recognizes only clear generation verbs.
        text = re.sub(r"\s+", " ", str(message or "").strip().lower())
        if not any(term in text for term in ("导板", "surgical guide", "puncture guide")):
            return False
        return bool(re.search(
            r"(?:生成|重建|重做|重新|create|generate|regenerate|rebuild)",
            text,
            re.IGNORECASE,
        )) and not bool(re.search(
            r"(?:不需要|不要|无需|不用|不生成|不重建|without|no guide|do not.*guide|don't.*guide)",
            text,
            re.IGNORECASE,
        ))


def _guide_suppressed(message: str) -> bool:
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    return bool(re.search(
        r"(?:不需要|不要|无需|不用|不生成|不重建|不重新设计|跳过).{0,16}"
        r"(?:导板|surgical\s+guide|puncture\s+guide)"
        r"|(?:without|no|do not|don't|dont|skip).{0,16}"
        r"(?:guide|surgical\s+guide|puncture\s+guide)",
        text,
        re.IGNORECASE,
    ))


def should_auto_generate_guide(owner: Any, message: str = "") -> bool:
    """Whether planning may derive a guide-generation call this turn.

    No captured stage means the legacy single-workspace path.  That path is
    treated as preoperative for backward compatibility.  A scoped
    intraoperative context is the only default exclusion; a clear explicit
    guide command remains allowed.
    """

    if _guide_suppressed(message):
        return False
    if is_intraoperative(owner):
        return _explicit_guide_request(message)
    return True

