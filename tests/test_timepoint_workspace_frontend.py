"""Executed frontend contracts; no claim of real image/model commissioning."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("script", ["timepoint-hydration-reentry.test.cjs", "timepoint-workspace-runtime.test.cjs", "timepoint-workspace-browser.test.cjs", "timepoint-data-tree-mutations.test.cjs", "timepoint-guide-ownership.test.cjs", "timepoint-chat-refresh.test.cjs", "timepoint-visual-barrier.test.cjs", "timepoint-viewer-fit.test.cjs", "timepoint-restore-producers.test.cjs", "timepoint-legacy-restore-cancel.test.cjs", "timepoint-input-config.test.cjs"])
def test_production_timepoint_workspace_contracts(script):
    node = os.environ.get("BRACHYBOT_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    if "browser" in script:
        dependency = subprocess.run([node, "-e", "require(process.argv[1])", os.environ.get("PLAYWRIGHT_MODULE", "playwright")], capture_output=True, text=True)
        if dependency.returncode:
            pytest.skip("Playwright is unavailable")
    result = subprocess.run([node, str(ROOT / "tests" / script)], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    if script == 'timepoint-input-config.test.cjs':
        assert 'fail 0' in result.stdout
    else:
        assert "contracts passed" in result.stdout
