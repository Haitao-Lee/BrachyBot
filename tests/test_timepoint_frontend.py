"""Frontend integration and a real-browser synthetic timepoint contract suite."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS_ROOT = ROOT / "web/app/static/js"


@pytest.fixture(autouse=True)
def isolated_auth_fixture():
    """The browser fixture never imports the server or uses an auth database."""
    yield


def test_one_timepoint_strip_mounts_above_existing_clinical_panels():
    html = (ROOT / "web/app/index.html").read_text(encoding="utf-8")
    assert html.count('id="timepointStrip"') == 1
    assert html.index('id="timepointStrip"') < html.index('id="panelInput"')
    for panel in ("panelInput", "panelMetrics", "panelViewers", "panelReport"):
        assert html.count(f'id="{panel}"') == 1
    assert html.count('src="static/js/brachybot-timepoints.js?v=') == 1
    assert html.count('href="static/css/brachybot-timepoints.css?v=1"') == 1
    assert html.index('src="static/js/brachybot-workspace.js') < html.index('src="static/js/brachybot-timepoints.js')


def test_header_and_presentation_hooks_use_the_existing_bridges():
    api = (JS_ROOT / "brachybot-ui-api.js").read_text(encoding="utf-8")
    workspace = (JS_ROOT / "brachybot-workspace.js").read_text(encoding="utf-8")
    assert "window.BrachyBotTimepoints?.addRequestHeaders(headers, pathname, requestSessionId);" in api
    assert "window.captureTimepointWorkspacePresentation = workspaceUiState;" in workspace
    assert "window.dispatchEvent(new CustomEvent('brachybot:session-readiness'" in workspace
    assert "window.dispatchEvent(new CustomEvent('brachybot:timepoint-session-ready'" in workspace


def test_synthetic_timepoint_browser_contracts():
    node = os.environ.get("BRACHYBOT_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the browser contract suite")
    # Missing browser dependencies are a reported skip, never a passing browser test.
    module = os.environ.get("PLAYWRIGHT_MODULE", "playwright")
    available = subprocess.run([node, "-e", "require(process.argv[1])", module], capture_output=True, text=True)
    if available.returncode:
        pytest.skip("Playwright is unavailable; set PLAYWRIGHT_MODULE to an installed runtime")
    result = subprocess.run([node, str(ROOT / "tests/timepoints-browser.test.cjs"), str(JS_ROOT)],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "synthetic timepoint browser scenarios passed." in result.stdout
