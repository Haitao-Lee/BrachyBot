"""Regression contracts for the publication-style Fig 2(e) DVH capture."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_report_dvh_capture_is_independent_from_the_dark_live_chart():
    source = _read("web/app/static/js/brachybot-report-editor.js")

    assert "const REPORT_DVH_CAPTURE_CONTRACT = 'dvh-readable-report-v3';" in source
    assert "async function captureReportDvhFigure" in source
    assert "const REPORT_DVH_CAPTURE_WIDTH = 2400;" in source
    assert "const REPORT_DVH_CAPTURE_HEIGHT = 1500;" in source
    assert "Plotly.newPlot(host, traces, reportLayout" in source
    assert "paper_bgcolor: '#ffffff'" in source
    assert "plot_bgcolor: '#ffffff'" in source
    assert "margin: { l: 150, r: 65, t: 70, b: 360 }" in source
    assert "text: 'Dose (Gy)'" in source
    assert "text: 'Volume (%)'" in source
    assert "range: [0, 400]" in source
    assert "range: [0, 100]" in source
    assert "orientation: 'h'" in source
    assert "xanchor: 'center'" in source
    assert "yanchor: 'top'" in source
    assert "entrywidthmode: 'pixels'" in source
    assert "entrywidth: 260" in source
    assert "captureContract: REPORT_DVH_CAPTURE_CONTRACT" in source


def test_all_report_dvh_paths_use_the_readable_exporter():
    editor = _read("web/app/static/js/brachybot-report-editor.js")
    planning = _read("web/app/static/js/brachybot-dvh-planning.js")

    assert "dvhDataUrl = await window.captureReportDvhFigure(dvhEl);" in editor
    assert "width: 2400, height: 800" not in editor
    assert "width: 900, height: 450" not in planning
    assert "await window.captureReportDvhFigure(dvhEl)" in planning
    assert "captureContract: window.REPORT_DVH_CAPTURE_CONTRACT || 'dvh-readable-report-v3'" in planning
