"""Typed transport for hidden screenshot-analysis child tasks.

The visible browser reply owns attachments.  A follow-up that interprets those
attachments is a short-lived execution child, not another conversation turn.
This module keeps its evidence and parent request structured until the server
has already verified the active Session, so the generated multimodal prompt
cannot be compacted or replayed as a later user's instruction.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


VISUAL_EVIDENCE_PROTOCOL_VERSION = 1
VISUAL_EVIDENCE_PROTOCOL_MARKER = "[BRACHYBOT_VISUAL_EVIDENCE_V1]"
_SESSION_SCREENSHOT_URL = re.compile(
    r"^/api/sessions/([a-f0-9]{32})/screenshots/([^/?#]+)$",
    re.IGNORECASE,
)


def normalize_visual_evidence_context(
    raw_context: Any,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    """Validate a browser visual-child envelope against its owning Session.

    The only evidence accepted here is a bounded list of screenshots produced
    by the currently selected workspace.  The parent request remains normal
    user text, but it is never written into AgentMemory as another user row.
    Returning ``None`` means the caller should reject an explicitly supplied
    malformed envelope; legacy clients can continue using their older text
    transport only when they omit the envelope entirely.
    """
    if not isinstance(raw_context, dict):
        return None
    try:
        version = int(raw_context.get("version"))
    except (TypeError, ValueError):
        return None
    if version != VISUAL_EVIDENCE_PROTOCOL_VERSION:
        return None

    raw_urls = raw_context.get("evidence_urls", raw_context.get("evidenceUrls"))
    if not isinstance(raw_urls, (list, tuple)):
        return None
    expected_session = str(session_id or "").strip().lower()
    if not expected_session:
        return None

    evidence_urls: List[str] = []
    seen_urls = set()
    for raw_url in raw_urls:
        url = str(raw_url or "").strip()
        match = _SESSION_SCREENSHOT_URL.fullmatch(url)
        if match is None or match.group(1).lower() != expected_session:
            return None
        if url in seen_urls:
            continue
        seen_urls.add(url)
        evidence_urls.append(url)
        if len(evidence_urls) >= 4:
            break
    if not evidence_urls:
        return None

    parent_request = str(
        raw_context.get("parent_request", raw_context.get("parentRequest", ""))
        or ""
    ).strip()
    if not parent_request:
        return None
    # A visual analysis child does not need an unbounded copy of a parent
    # message. Keep enough context for a detailed question while bounding the
    # transient multimodal prompt and its provider payload.
    parent_request = parent_request[:8000]

    raw_labels = raw_context.get("attachment_labels", raw_context.get("attachmentLabels", []))
    labels: List[str] = []
    if isinstance(raw_labels, (list, tuple)):
        for raw_label in raw_labels:
            label = str(raw_label or "").strip()
            if not label or label in labels:
                continue
            labels.append(label[:160])
            if len(labels) >= 16:
                break

    return {
        "version": VISUAL_EVIDENCE_PROTOCOL_VERSION,
        "evidence_urls": evidence_urls,
        "parent_request": parent_request,
        "attachment_labels": labels,
    }


def build_visual_evidence_prompt(context: Dict[str, Any], response_language: str = "") -> str:
    """Build the ephemeral multimodal prompt after envelope validation.

    The marker is intentionally explicit so a legacy corrupted summary can be
    removed as one protocol block.  The normal execution path never persists
    this prompt; it exists only long enough for the visual child to call the
    multimodal provider.
    """
    urls = [str(url) for url in (context.get("evidence_urls") or []) if str(url)]
    request_text = str(context.get("parent_request") or "").strip()
    language = "Chinese" if str(response_language or "").lower().startswith("zh") else "English"
    captures = "\n".join(f"[Screenshot captured: {url}]" for url in urls)
    return (
        f"{VISUAL_EVIDENCE_PROTOCOL_MARKER}\n"
        f"{captures}\n\n"
        f"User request: {request_text}\n"
        "Analyze the supplied screenshot(s) and answer the user's request directly. "
        f"Use {language} for every user-visible sentence. "
        "Do not request another screenshot. Do not present attachments again or repeat attachment titles "
        "or standalone viewer labels; the browser already renders them below each image. "
        "Use the current case only as read-only corroboration and mention uncertainty instead of inventing details."
    )
