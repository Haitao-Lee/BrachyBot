from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_report_text_pages_use_measured_flow_pagination():
    source = (ROOT / "web/app/static/js/brachybot-report-export.js").read_text(
        encoding="utf-8"
    )
    screen_css = (ROOT / "web/app/static/css/brachybot-panels-viewers.css").read_text(
        encoding="utf-8"
    )

    assert "function _paginateReportFlow" in source
    assert "function _reportFlowAvailableHeight" in source
    assert 'data-report-flow-page="true"' in source
    assert 'class="report-flow-page-body"' in source
    assert 'class="report-flow-section"' in source
    assert "function _renderReportInterpretation" in source
    assert "_renderReportInterpretation(f.interpretation, interpretationSection)" in source
    assert "const withoutHeading = rendered.replace(" in source
    assert "(strong|b)" in source
    assert "const includeHeading = firstFragment;" in source
    assert "_paginateReportFlow(pagesEl, { page: s.page, pageOf: s.pageOf });" in source
    assert "document.fonts.ready.then(repaginate)" in source
    assert ".report-flow-page-body" in screen_css
    assert ".report-flow-section" in screen_css


def test_report_pagination_preserves_a4_clipping_boundary_and_renumbers_pages():
    source = (ROOT / "web/app/static/js/brachybot-report-export.js").read_text(
        encoding="utf-8"
    )

    # A page remains a physical sheet; only flowable blocks are moved between
    # sheets.  The paginator must repair page totals after it merges/splits
    # the OAR, interpretation, and safety sections.
    assert "height: 297mm; min-height: 297mm; max-height: 297mm" in source
    assert "position: relative; overflow: hidden; contain: layout paint;" in source
    assert "sourcePages.forEach(page => page.remove());" in source
    assert "allPages.length" in source
    assert "report-flow-section" in source
