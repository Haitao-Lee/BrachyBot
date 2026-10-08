"""Real Plotly/DOM checks with synthetic identities, no patient/provider."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'web/app/static/js'


def function(source, name):
    start = re.search(r'(?:async )?function ' + re.escape(name) + r'\(', source).start()
    return source[start:source.index('\n}', start) + 2]


@pytest.fixture(scope='module')
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        b = runtime.chromium.launch(headless=True, args=['--no-sandbox'],
            executable_path='/home/lht/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome')
        yield b
        b.close()


@pytest.fixture
def page(browser):
    p = browser.new_page(viewport={'width': 1100, 'height': 800})
    p.set_content('''<div id="dvhCoverageStatus"></div><div id="dvhPlaceholder"></div>
        <div id="dvhChart" style="width:900px;height:450px"></div>
        <table><tbody id="oarTableBody"></tbody></table>''')
    p.add_script_tag(path=str(JS / 'plotly.min.js'))
    p.add_script_tag(content='''
        var activeSessionId='case',viewerDataLoadGeneration=1,API='/api';
        var state={ctLoaded:true,dvhPlanningId:'plan',metrics:{prescription_gy:120,volume_metric_units:'fraction'},maskLabels:{}};
        var dataTreeState={ctv:{label:'CTV Mask',color:'#ff0000'},ctvLabels:{ctv_2:{id:'ctv_2',labelId:2,objectId:'structure:ctv:2',label:'Label 2',color:'#ff0000'}},
            oar:{},skin:{},planning:{id:'plan',activePlanningId:'plan',seeds:[],needles:[],doseLevels:[]},
            organs:[{id:'organ_52',labelId:52,objectId:'structure:oar:52',label:'aorta',color:'#00ff00'},
                    {id:'organ_58',labelId:58,objectId:'structure:oar:58',label:'artery_left',color:'#0000ff'},
                    {id:'organ_57',labelId:57,objectId:'structure:oar:57',label:'artery_right',color:'#ffff00'}]};
        var organMetaFromServer={},ctvLabelColorLUT={},oarLabelColorLUT={},labelColorLUT={},scene3D={meshes:{}};
        window._i18nLang='en';window._t=(zh,en)=>window._i18nLang==='zh'?zh:en;
        window.uiDebugLog=()=>{};window.escHtml=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        window.reloadOverlays=()=>{};window.redrawSeedNeedleOverlays=()=>{};
        window.renderDataTreeDebounced=()=>window.refreshAnalysisStructurePresentation?.();
        window.renderDataTree=window.renderDataTreeDebounced;window._scheduleDataTreeSave=()=>{};
        window.requestViewerVisualRefresh=()=>{};window.syncCtvWorkspaceColor=()=>{};
        window._isDataTreeMaskId=()=>false;window._planningItems=()=>[];window.applyDataTreeViewVisibility=()=>{};
        window._viewerDataHeaders=()=>({'X-Session-ID':activeSessionId});
        window.effectiveUiLanguage=()=>window._i18nLang;
        window.curve=(extra={})=>({dose_bins:[0,120,200,400],volume_pcts:[100,75,20,0],...extra});
    ''')
    p.add_script_tag(path=str(JS / 'brachybot-dvh-planning.js'))
    source = (JS / 'brachybot-viewer-volume.js').read_text()
    p.add_script_tag(content='\n'.join(function(source, name) for name in ('setDataTreeItemColor', 'setGroupColor')))
    yield p
    p.close()


def test_meaningful_names_survive_missing_metadata_and_label_id(page):
    page.evaluate("updateOARTable({aorta:{label_id:52,d2cc:1},brain:{label_id:90,d2cc:2}})")
    assert page.locator('td').all_text_contents()[0] == 'aorta'
    assert page.locator('tr').nth(1).locator('td').first.text_content() == 'brain'
    assert page.locator('tr').first.locator('td').first.evaluate('e=>getComputedStyle(e).color') == 'rgb(0, 255, 0)'


def test_unknown_anatomy_is_not_guessed_and_fuzzy_laterality_is_not_matched(page):
    assert page.evaluate("_getOrganColor('artery')") is None
    assert page.evaluate("_resolveOARDisplayName('Unmapped structure (label 900)',{label_id:900})") == 'Unmapped structure (label 900)'


def test_ctv_and_oar_same_numeric_label_have_independent_names_and_colors(page):
    page.evaluate("dataTreeState.organs.push({labelId:2,label:'organ two',color:'#00ffff'})")
    assert page.evaluate("_analysisStructurePresentation('CTV', {classification:'ctv',label_id:2}).color") == '#ff0000'
    assert page.evaluate("_analysisStructurePresentation('organ', {classification:'oar',label_id:2}).color") == '#00ffff'


def test_recycled_label_does_not_override_explicit_object_identity(page):
    assert page.evaluate("_analysisStructurePresentation('old organ',{object_id:'deleted-object',label_id:52}).name") == 'old organ'


@pytest.mark.parametrize('node,field', [('organ_52','aorta'),('ctv_2','CTV')])
def test_actual_node_color_executor_updates_plotly_and_table(page, node, field):
    page.evaluate("state.dvhData={CTV:curve(),aorta:curve({label_id:52})};state.metrics.oar_metrics={aorta:{label_id:52,d2cc:1}}")
    page.evaluate('drawDVH()')
    page.evaluate("([id])=>setDataTreeItemColor(id,'#123456')", [node])
    page.wait_for_function("([name])=>document.getElementById('dvhChart').data.find(t=>t.meta.structureKey===name)?.line.color==='#123456'", arg=[field])
    if field == 'aorta':
        assert page.locator('td').first.evaluate('e=>getComputedStyle(e).color') == 'rgb(18, 52, 86)'


def test_group_color_updates_all_curves_and_preserves_zoom(page):
    page.evaluate("state.dvhData={CTV:curve(),aorta:curve({label_id:52}),artery_left:curve({label_id:58}),artery_right:curve({label_id:57})}")
    page.evaluate('drawDVH()')
    page.evaluate("Plotly.relayout(document.getElementById('dvhChart'),{'xaxis.range':[0,180]})")
    page.evaluate("setGroupColor('oar','#abcdef')")
    page.wait_for_function("document.getElementById('dvhChart').data.filter(t=>t.meta.structureKey!=='CTV').every(t=>t.line.color==='#abcdef')")
    assert page.evaluate("document.getElementById('dvhChart')._fullLayout.xaxis.range") == [0,180]


def test_metadata_late_hydration_updates_name_and_color_without_dose_change(page):
    page.evaluate("state.dvhData={'old name':curve({label_id:52})}")
    page.evaluate('drawDVH()')
    page.evaluate("dataTreeState.organs[0].label='Aorta renamed';dataTreeState.organs[0].color='#000000';refreshAnalysisStructurePresentation()")
    page.wait_for_function("document.getElementById('dvhChart').data[0].name==='Aorta renamed'")
    assert page.evaluate("document.getElementById('dvhChart').data[0].line.color") == '#000000'


def test_missing_metrics_are_dashes_but_real_zero_is_zero(page):
    page.evaluate("updateOARTable({aorta:{label_id:52,d2cc:0,v100:0}})")
    cells = page.locator('td').all_text_contents()
    assert cells[1:7] == ['--','--','0.0','--','--','0.0']


def test_explicit_percent_units_not_multiplied_and_strings_safe(page):
    page.evaluate("updateOARTable({'<img src=x onerror=alert(1)>':{d2cc:'1',v100:.5,volume_metric_units:'percent'}})")
    assert page.locator('img').count() == 0
    assert page.locator('td').nth(6).text_content() == '0.5'


def test_nested_curve_identity_survives_normalization(page):
    assert page.evaluate("_normalizeRenderableDvhPayload({x:{object_id:'stable',classification:'ctv',label_id:2,cumulative:curve()}}).x.object_id") == 'stable'


def test_all_curves_including_zero_dose_and_more_than_53_are_rendered(page):
    page.evaluate("state.dvhData={};for(let i=1;i<=70;i++)state.dvhData['roi'+i]=curve({object_id:'roi'+i,classification:i<4?'ctv':'oar'});state.dvhData.zero={dose_bins:[0,1],volume_pcts:[100,0]}")
    page.evaluate('drawDVH()')
    assert page.evaluate("document.getElementById('dvhChart').data.length") == 71


@pytest.mark.parametrize('change', ["activeSessionId='other'", "viewerDataLoadGeneration++", "state.dvhPlanningId='other'", "state.metrics={prescription_gy:120}"])
def test_late_analysis_response_cannot_repaint_another_owner(page, change):
    page.evaluate("window.fetch=()=>new Promise(resolve=>window.release=resolve);window.pending=refreshStructureDvhAnalysis();void 0")
    page.evaluate(change)
    page.evaluate("release({ok:true,json:async()=>({success:true,planning_id:'plan',dvh:{aorta:curve()},oar_metrics:{},coverage:{expected:1,available:1,status:'complete',structures:[]}})})")
    page.evaluate('pending')
    assert page.evaluate('state.structureAnalysis===undefined') is True


def test_completeness_status_is_localized_by_global_event(page):
    page.evaluate("window.fetch=async()=>({ok:true,json:async()=>({success:true,planning_id:'plan',dvh:{aorta:curve()},oar_metrics:{},coverage:{expected:1,available:1,status:'complete',structures:[]}})})")
    page.evaluate('refreshStructureDvhAnalysis()')
    assert '1/1' in page.locator('#dvhCoverageStatus').text_content()
    page.evaluate("window._i18nLang='zh';window.dispatchEvent(new Event('i18nchange'))")
    page.wait_for_function("document.getElementById('dvhCoverageStatus').textContent.includes('全部已分类')")


def test_report_offscreen_fallback_uses_same_identity_name_and_color(page):
    source = (JS / 'brachybot-report-editor.js').read_text()
    page.add_script_tag(content='\n'.join(function(source, name) for name in ('_reportDvhCurvePairs','_reportDvhFallbackSource')))
    result = page.evaluate("_reportDvhFallbackSource({'structure:oar:52':curve({object_id:'structure:oar:52',classification:'oar',label_id:52,display_name:'aorta'})}).data[0]")
    assert result['name'] == 'aorta'
    assert result['line']['color'] == '#00ff00'

