"""Executed production scheduler contract, isolated from clinical runtime."""
import os
from pathlib import Path
import shutil
import subprocess
import pytest


def test_hidden_viewer_scheduler_is_event_driven_and_capture_is_preserved():
    node = os.environ.get('BRACHYBOT_NODE') or shutil.which('node')
    if not node:
        pytest.skip('Node.js is unavailable')
    script = Path(__file__).with_name('viewer-scheduler-idle.test.cjs')
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'capture stays full quality' in result.stdout
