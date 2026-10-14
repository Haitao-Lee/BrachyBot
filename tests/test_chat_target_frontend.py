"""The actual chat entrypoint carries captured targets across async boundaries."""
import os
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_request_capture_protocol_in_javascript():
    node = os.environ.get("BRACHYBOT_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for request-capture protocol validation")
    result = subprocess.run([node, str(ROOT / 'tests/chat-targets.test.cjs')], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'late-paint fences passed' in result.stdout


def test_real_send_queue_and_followup_use_same_capture_contract():
    source = (ROOT / 'web/app/static/js/brachybot-chat-todo.js').read_text(encoding='utf-8')
    html = (ROOT / 'web/app/index.html').read_text(encoding='utf-8')
    assert html.index('src="static/js/brachybot-chat-target.js') < html.index('src="static/js/brachybot-chat-todo.js')
    assert source.index('let submittedTarget') < source.index('await pendingStop;', source.index('async function sendChat'))
    assert '_queueChatTurn(activeSessionId, queuedText, submittedTarget, opts)' in source
    assert 'targetConfirmationReceiptId: next.targetConfirmationReceiptId' in source
    assert 'timepointScope: next.timepointScope' in source
    assert 'BrachyBotChatTargets?.parent(ownerSessionId, parentRequestId)' in source
    assert 'BrachyBotChatTargets.headers(submittedTarget' in source
    assert 'timepoint_id: submittedTarget?.timepointId' in source
    assert 'visualTargetIsMounted() && typeof collectUIState' in source
