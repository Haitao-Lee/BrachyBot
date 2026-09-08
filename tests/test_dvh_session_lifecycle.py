from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_completed_tool_events_execute_browser_content_actions():
    source = _read("web/app/static/js/brachybot-chat-todo.js")
    assert "function _isTerminalToolStatus" in source
    assert "'completed'" in source
    assert "toolCompleted && data.tool === 'ui_content'" in source
    assert "toolCompleted && data.tool === 'ui_screenshot'" in source
    assert "request: turnRequestId" in source


def test_planning_dvh_is_deferred_until_analysis_has_a_real_viewport():
    source = _read("web/app/static/js/brachybot-dvh-planning.js")
    viewer = _read("web/app/static/js/brachybot-viewer-volume.js")
    assert "dvhEl.offsetParent === null" in source
    assert "window.ensureDvhChartRendered = ensureDvhChartRendered" in source
    assert "data?.dvh_data" in source
    assert "window.ensureDvhChartRendered" in viewer


def test_dvh_visual_requests_never_fall_back_to_report_pages():
    source = _read("web/app/static/js/brachybot-ui-api.js")
    assert "visual_capture_failed:" in source
    assert "没有使用报告截图替代 DVH 图" in source
    assert "const chart = document.getElementById('dvhChart')" in source


def test_report_flow_reserves_footer_space_and_normalizes_preview_scale():
    source = _read("web/app/static/js/brachybot-report-export.js")
    css = _read("web/app/static/css/brachybot-panels-viewers.css")
    assert "function _reportFlowScaleY" in source
    assert "bodyRect.height / bodyCssHeight" in source
    assert "padding-bottom: 12mm" in source
    assert "function _reportFlowSplitTextNode" in source
    assert "const childCount = _reportFlowChildCount(oversized)" in source
    assert "padding-bottom: 12mm" in css
