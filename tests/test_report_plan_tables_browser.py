"""Real report preview/print pagination using synthetic data, no patient case."""
from pathlib import Path
import os
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'web/app/static/js'


@pytest.fixture(scope='module')
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        installed = sorted((Path.home() / '.cache/ms-playwright').glob('chromium-*/chrome-linux*/chrome'))
        executable = os.environ.get('BRACHYBOT_TEST_CHROMIUM') or (str(installed[-1]) if installed else runtime.chromium.executable_path)
        browser = runtime.chromium.launch(headless=True, args=['--no-sandbox'], executable_path=executable)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={'width': 1100, 'height': 1000})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    # index.html and the print window both use standards mode. Quirks mode
    # changes table line-height inheritance and invalidates print measurements.
    page.set_content('<!doctype html><html><body><div id="reportPages"></div><div id="reportFormHost"></div></body></html>')
    assert page.evaluate('document.compatMode') == 'CSS1Compat'
    page.add_script_tag(content="""
        var state={metrics:{}, sessionId:'case', dvhPlanningId:'plan'};
        var activeSessionId='case'; var dataTreeState={organs:[],ctvLabels:{},planning:{}};
        window._i18nLang='en'; window._t=(zh,en)=>window._i18nLang==='zh'?zh:en;
        window._setReportStatus=()=>{};window._scheduleReportAutoSave=()=>{};window.uiDebugLog=()=>{};
    """)
    page.add_script_tag(path=str(JS / 'brachybot-dvh-planning.js'))
    page.add_script_tag(path=str(JS / 'brachybot-report-plan-tables.js'))
    page.add_script_tag(path=str(JS / 'brachybot-report-editor.js'))
    page.add_script_tag(path=str(JS / 'brachybot-report-export.js'))
    page.add_style_tag(path=str(ROOT / 'web/app/static/css/brachybot-panels-viewers.css'))
    page.evaluate("""() => {
        window.reportForm=_localizedEmptyReportForm('en');
        window.reportForm.planningId='plan';
        window._reportPaginationToken=0;
    }""")
    yield page
    context.close()
    assert not errors, errors


def synthetic_form(page, language='en'):
    page.evaluate("""language => {
        const f=window.reportForm; f.language=language; window._i18nLang=language;
        f.oarDose=Array.from({length:54},(_,i)=>({organ:'organ_'+(i+1), object_id:'roi:'+i,
            review_order:i+1, importance_basis:'observed_dose', dmax:i, dmean:0, d2cc:0,
            d1cc:0,d0_1cc:0,d90:0,d95:0,v100:0,volume_cm3:1}));
        f.oarDose.push({organ:'missing_structure', dmax:null,d2cc:null,v100:null,importance_basis:'unassessed'});
        const seeds=n=>Array.from({length:n},(_,i)=>({seed_id:'S'+String(i+1).padStart(3,'0'),tip_distance_mm:i*5,
            axis_offset_mm:0,distance_from_previous_mm:i?5:null,position_world_mm:[1,2,350-i*5],flags:[]}));
        f.implantPlan={version:1,planning_id:'plan',coordinate_system:'patient_world_lps',distance_reference:'needle_tip',
            channels:[{needle_id:'needle_1',trajectory_id:'traj_1',entry_world_mm:[1,2,0],tip_world_mm:[1,2,350],insertion_length_mm:350,seeds:seeds(60)},
                {needle_id:'needle_2',trajectory_id:'traj_2',entry_world_mm:[3,4,0],tip_world_mm:[3,4,20],insertion_length_mm:20,
                    seeds:[{seed_id:'OTHER001',tip_distance_mm:5,axis_offset_mm:0,position_world_mm:[3,4,15],flags:[]}]},
                {needle_id:'needle_3',trajectory_id:'traj_3',entry_world_mm:null,tip_world_mm:[5,6,20],insertion_length_mm:null,
                    seeds:[{seed_id:'NO_SKIN',tip_distance_mm:7,axis_offset_mm:0,position_world_mm:[5,6,13],flags:[]}]}],
            unassigned_seeds:[{seed_id:'UNASSIGNED',position_world_mm:[9,8,7],flags:['ambiguous_or_missing_owner']}]
        };
        _updateReportPreview();
    }""", language)
    page.wait_for_timeout(100)
    page.evaluate('window._reflowReportPages()')


def test_fallback_retains_zero_missing_and_explicit_units(page):
    rows = page.evaluate("_reportOarRowsFromMetrics({zero:{d2cc:0,dmax:0,v100:0},missing:{v100:null},pct:{v100:.5,volume_metric_units:'percent'}},'fraction')")
    assert len(rows) == 3
    assert next(r for r in rows if r['organ'] == 'zero')['d2cc'] == 0
    assert next(r for r in rows if r['organ'] == 'missing')['v100'] is None
    assert next(r for r in rows if r['organ'] == 'pct')['v100'] == .5
    assert page.evaluate('_reportTableNumber(false)') == '—'
    assert page.evaluate('_reportTablePoint([false,1,2])') == '—'


def test_report_table_strings_escape_html_and_use_global_language(page):
    synthetic_form(page)
    page.evaluate("reportForm.implantPlan.channels[0].seeds[0].seed_id='<img src=x onerror=alert(1)>';reportForm.oarDose[0].organ='<script>alert(1)</script>';_updateReportPreview()")
    assert page.locator('#reportPages script').count() == 0
    assert page.locator('#reportPages img[src="x"]').count() == 0
    page.evaluate("window._i18nLang='zh';reportForm.language='zh';_updateReportPreview();renderReportEditor()")
    assert '距针尖末端' in page.locator('#reportPages').inner_text()
    assert '针道与粒子位置明细' in page.locator('#reportFormHost').inner_text()
    assert 'From needle tip' not in page.locator('#reportPages').inner_text()


def test_plan_mismatch_never_labels_old_seed_positions_current(page):
    synthetic_form(page)
    page.evaluate("reportForm.implantPlan.planning_id='old';_updateReportPreview()")
    assert page.locator('#reportPages [data-seed-id]').count() == 0
    assert 'another planning revision' in page.locator('#reportPages').inner_text()


@pytest.mark.parametrize('language', ['en', 'zh'])
def test_real_pdf_all_organs_seeds_headings_and_pages_are_readable(page, language):
    synthetic_form(page, language)
    # The two OAR metric tables retain every structure on paper.
    assert page.locator('#reportPages .hp-oar-detail-table tbody tr').count() == 110
    assert page.locator('#reportPages [data-seed-id]').count() == 63
    headings = page.locator('#reportPages .hp-section-title').all_text_contents()
    assert any('needle_1' in h for h in headings)
    assert any('needle_2' in h for h in headings)
    assert any('needle_3' in h for h in headings)
    assert page.locator('#reportPages .hp-implant-table thead').count() > 3
    assert page.locator('#reportPages .hp-implant-table').count() == page.locator('#reportPages .hp-implant-table caption').count()
    assert page.evaluate("""() => Array.from(document.querySelectorAll('#reportPages [data-report-flow-key^="implant-channel-"]')).every(section=>!section.querySelector('.hp-needle-endpoints') || section.querySelector('[data-seed-id]'))""")
    overflow = page.evaluate("""() => Array.from(document.querySelectorAll('#reportPages .report-flow-page')).filter(p=>{
        const b=p.querySelector('.report-flow-page-body');
        return b && b.scrollHeight > _reportFlowAvailableHeight(p,b)+1;
    }).length""")
    assert overflow == 0
    assert page.evaluate("""() => Array.from(document.querySelectorAll('.hp-grid-table')).every(t=>t.scrollWidth<=t.clientWidth+1)""")
    markdown = page.evaluate('_reportDetailedTablesMarkdown(reportForm).join("\\n")')
    assert 'S060' in markdown and 'UNASSIGNED' in markdown
    assert 'From needle tip' in markdown if language == 'en' else '距针尖末端' in markdown
    output = ROOT / 'tmp/pdfs'
    output.mkdir(parents=True, exist_ok=True)
    pdf = output / f'report-plan-tables-{language}.pdf'
    # Match exportReportPDF: print only approved report pages, never the editor.
    sheets = page.locator('#reportPages .report-page').count()
    print_html = page.evaluate("'<!doctype html><html><head><meta charset=\"utf-8\"><style>'+_printableCss()+'</style></head><body class=\"report-print\">'+Array.from(document.querySelectorAll('#reportPages .report-page')).map(p=>p.outerHTML).join('')+'</body></html>'")
    print_page = page.context.new_page()
    print_page.set_content(print_html)
    print_page.evaluate('document.fonts.ready')
    assert print_page.evaluate("""() => Array.from(document.querySelectorAll('[data-seed-id], .hp-oar-detail-table tbody tr')).every(row=>{
        const page=row.closest('.report-page'), bottom=page.querySelector('.hp-page-footer').getBoundingClientRect().top;
        return row.getBoundingClientRect().bottom < bottom;
    })""")
    print_page.pdf(path=str(pdf), format='A4', prefer_css_page_size=True, print_background=True)
    print_page.close()
    result = subprocess.run(['pdftotext', '-layout', str(pdf), '-'], capture_output=True, text=True, check=True)
    assert 'S060' in result.stdout
    assert 'UNASSIGNED' in result.stdout
    assert 'needle_2' in result.stdout and 'needle_3' in result.stdout
    assert len([s for s in result.stdout.split('\f') if s.strip()]) == sheets


def test_legacy_autofill_reply_cannot_cross_case_or_report_form(page):
    page.evaluate("""() => { window.fetch=()=>new Promise(resolve=>window.releaseTables=resolve); window._pendingFill=reportAutoFill().catch(e=>({error:String(e)})); void 0; }""")
    page.wait_for_function('typeof window.releaseTables === "function"', timeout=5000)
    page.evaluate("activeSessionId='other';reportForm=_localizedEmptyReportForm('en');window.releaseTables({ok:true,json:async()=>({success:true,patch:{implantPlan:{planning_id:'plan'}}})})")
    result = page.evaluate('window._pendingFill')
    assert result['stale'] is True
    assert page.evaluate('reportForm.implantPlan') is None


def test_legacy_autofill_reply_cannot_cross_geometry_revision(page):
    page.evaluate("""() => { dataTreeState.planning.version=1; window.fetch=()=>new Promise(resolve=>window.releaseTables=resolve); window._pendingFill=reportAutoFill(); }""")
    page.wait_for_function('typeof window.releaseTables === "function"', timeout=5000)
    page.evaluate("dataTreeState.planning.version=2;window.releaseTables({ok:true,json:async()=>({success:true,patch:{implantPlan:{planning_id:'plan'}}})})")
    assert page.evaluate('window._pendingFill')['stale'] is True
    assert page.evaluate('reportForm.implantPlan') is None


def test_manual_oar_edits_are_not_overwritten_by_autofill(page):
    synthetic_form(page)
    page.evaluate("updateOARDoseRow(0,'d2cc','12.5');window.fetch=async()=>({ok:true,json:async()=>({success:true,patch:{oarDose:[]}})})")
    page.evaluate('reportAutoFill()')
    assert page.evaluate('reportForm.oarDose[0].d2cc') == 12.5
    assert page.evaluate('reportForm.oarDose[0].importance_basis') == 'manual_edit'
