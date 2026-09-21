"""Contract for the 3D Viewer seed/needle inspection chat card.

Right-clicking a seed or needle in the 3D Viewer used to dump a raw text line
into the chat (``💊 **Seed seed_21_1**\\n- Position: ...``). System events render
as plain escaped text, so the user saw literal asterisks and a ragged layout.
The inspection is now a system message with ``messageKind: 'inspection_card'``
that renders markdown (heading + table) in a left-aligned card.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_viewer_seed_inspection_renders_a_markdown_card():
    core = _read("web/app/static/js/brachybot-chat-core.js")
    manual = _read("web/app/static/js/brachybot-3d-manual.js")
    css = _read("web/app/static/css/brachybot-chat-status.css")

    # addChat treats the declared inspection kind as a markdown card even
    # though it is persisted as a system event.
    assert "isInspectionCard" in core
    assert "'inspection_card', 'seed_info', 'needle_info'" in core
    assert "isInspectionCard ? ' inspection-card'" in core
    assert "(safeType === 'bot' || isInspectionCard) && typeof renderMarkdown" in core

    # The viewer prints a structured table rather than a raw text blob.
    assert "messageKind: 'inspection_card'" in manual
    assert "| 属性 | 值 |" in manual
    assert "| Field | Value |" in manual
    assert "💊 **Seed" not in manual
    assert "📍 **Needle" not in manual

    # The card is left-aligned and full-width, overriding the centered pill.
    assert ".chat-msg.system.inspection-card" in css
    assert ".chat-row.inspection" in css
