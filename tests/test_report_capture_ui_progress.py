"""Regression contracts for the report-capture progress surface."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_report_capture_has_a_non_blocking_lifecycle_status():
    editor = _read("web/app/static/js/brachybot-report-editor.js")
    index = _read("web/app/index.html")
    css = _read("web/app/static/css/brachybot-report-controls.css")

    assert "REPORT_CAPTURE_STEP_TOTAL = 7" in editor
    assert "_reportCaptureUiStart(REPORT_CAPTURE_STEP_TOTAL, lang)" in editor
    assert "await _reportCaptureUiNextPaint();" in editor
    assert "_reportCaptureUiFinish(context.reportCaptureUiRunId" in editor
    assert "reportCaptureStep(1, '规划全景图（Fig 1a）'" in editor
    assert "reportCaptureStep(2, '靶区粒子特写（Fig 1b）'" in editor
    assert "reportCaptureStep(6, '三维剂量面（Fig 2d）'" in editor
    assert "reportCaptureStep(7, 'DVH 曲线（Fig 2e）'" in editor
    assert 'id="reportCaptureStatus"' in index
    assert "pointer-events: none" in css
    assert ".report-capture-status:not([hidden])" in css
    assert "@keyframes reportCaptureSpin" in css


def test_report_capture_status_is_scoped_to_the_canonical_capture_promise():
    source = _read("web/app/static/js/brachybot-report-editor.js")

    assert "captureContext.reportCaptureUiRunId = reportCaptureUiRunId" in source
    assert "captureContext.reportCaptureUiCaptured = Number(captureContext.reportCaptureUiCaptured || 0) + 1" in source
    assert "captured: context.reportCaptureUiCaptured" in source
    assert "stale: captureResult?.stale === true" in source
