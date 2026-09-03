"""Regression contracts for the Report 2-column interaction model."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_report_two_column_layout_has_two_panes_and_a_real_splitter():
    index = _read("web/app/index.html")
    shell = _read("web/app/static/js/brachybot-report-shell.js")
    css = _read("web/app/static/css/brachybot-report-controls.css")

    assert 'data-report-layout-pane="editor"' in index
    assert 'data-report-layout-pane="preview"' in index
    assert 'id="reportLayoutSplitter"' in index
    assert 'role="separator"' in index
    assert "Body: one continuous scrollable container" not in index

    # The body becomes a non-scrolling grid in desktop 2-col mode; each pane
    # owns its own vertical scroll context and contains scroll chaining.
    assert "grid-template-columns: minmax(260px, min(var(--rp-editor-width, 50%), calc(100% - 312px)))" in shell
    assert "overflow-y: auto" in shell
    assert "overscroll-behavior: contain" in shell
    assert "overflow: hidden" in shell

    # The divider is visible, touch-safe, keyboard-accessible and styled as a
    # genuine resize affordance rather than a decorative border.
    assert "pointerdown" in shell
    assert "setPointerCapture" in shell
    assert "event.key === 'ArrowLeft'" in shell
    assert "event.key === 'ArrowRight'" in shell
    assert "--rp-editor-width" in shell
    assert "brachyplan_report_2col_split_v1" in shell
    assert ".rp-layout-splitter" in css
    assert "cursor: col-resize" in css
    assert "touch-action: none" in css


def test_report_two_column_split_is_constrained_and_persisted():
    shell = _read("web/app/static/js/brachybot-report-shell.js")
    index = _read("web/app/index.html")

    assert "const _REPORT_SPLIT_MIN = 0.30" in shell
    assert "const _REPORT_SPLIT_MAX = 0.70" in shell
    assert "_clampReportSplitRatio" in shell
    assert "aria-valuenow" in shell
    assert "_persistReportSplitRatio" in shell
    assert "_scheduleReport2colLayout" in shell

    # New users start in the useful side-by-side layout, while an explicit
    # local opt-out remains authoritative on later reloads.
    assert 'type="checkbox" checked onchange="Report.panels.layout2col(this.checked)"' in index
    assert "const enabled = stored === null || stored === '1';" in shell
