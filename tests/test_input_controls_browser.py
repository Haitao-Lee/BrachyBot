"""Real Input DOM and product handlers; synthetic endpoint boundaries only."""
from pathlib import Path
import pytest
from test_viewers_toolbar_browser import page, function

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'web/app/static/js'


@pytest.fixture
def input_page(page):
    page.add_script_tag(content=(JS / 'brachybot-input-actions.js').read_text())
    page.add_script_tag(content=function((JS / 'brachybot-ui-api.js').read_text(), '_confirmAction'))
    page.evaluate('''() => {
        window.escHtml=x=>String(x).replaceAll('<','&lt;');
        window.calls=[];window.events=[];window.panels=[];window.dataTreeState={planning:{}};
        window.reportUIEvent=(...a)=>events.push(a);
        window.clearManualStepPresentation=()=>{};window._invalidateDoseForPlanningRun=()=>{};
        window._refreshManualStepUI=()=>{};
        window.refreshPlanningUI=async()=>({success:true});
        window.switchPanel=x=>panels.push(x);
        window.fetch=async(url,opts)=>{
            const body=opts.body ? JSON.parse(opts.body):{};
            calls.push({url,body,headers:opts.headers});
            return {ok:true,status:200,json:async()=>({success:true,
                workflow_state:{ctv_segmentation:true,oar_segmentation:true,seed_planning:true,dose_calc:true,dose_eval:true},
                has_dose:true,dose_units:'gy',dose_range:[1,2],dose_scale_gy:190.8,metrics:{v100:0,d90:0},
                download_urls:[`/api/sessions/${activeSessionId}/artifacts/stl/seed.stl`],
                download_url:`/api/sessions/${activeSessionId}/artifacts/reports/report.html`})};
        };
    }''')
    return page


def test_reset_requires_confirmation_and_cancel_never_writes(input_page):
    p = input_page
    p.evaluate('() => { window.resetPromise=resetSession(); }')
    assert p.locator('#_confirmYes').is_visible()
    assert p.evaluate('calls.length') == 0
    p.locator('#_confirmNo').click()
    assert p.evaluate('resetPromise') == {'cancelled': True}
    assert p.evaluate('calls.length') == 0
    p.evaluate('() => { window.resetPromise=resetSession(); }')
    p.locator('#_confirmYes').click()
    assert p.evaluate('resetPromise')['success']
    assert p.evaluate('calls[0].url') == '/api/planning/clear'
    assert p.evaluate('calls[0].headers["X-BrachyBot-Session"]') == 'synthetic'


@pytest.mark.parametrize('key, expected', [('trajectories','viewers'),('seeds','viewers'),('dose','viewers'),
    ('all','viewers'),('dvh','metrics'),('metrics','metrics')])
def test_result_buttons_open_the_corresponding_panel(input_page, key, expected):
    p = input_page
    p.evaluate('(key)=>showStepResults(key)', key)
    assert p.evaluate('panels.at(-1)') == expected
    if key in ('dose', 'all'):
        text = p.evaluate('chats.map(x=>x[1]).join("\\n")')
        assert '1.0–2.0 Gy' in text
        assert '190.8–381.6' not in text
    if key in ('metrics', 'all'):
        assert 'V100=0%' in p.evaluate('chats.map(x=>x[1]).join("\\n")')


@pytest.mark.parametrize('action', ['exportDicomRT', 'exportSTL', 'exportReport'])
def test_exports_provide_case_owned_downloads(input_page, action):
    p = input_page
    p.evaluate('(action)=>window[action]()', action)
    assert any('/api/sessions/synthetic/artifacts/' in x[1] for x in p.evaluate('chats'))


def test_full_pipeline_no_duplicate_and_no_success_from_incomplete_products(input_page):
    p = input_page
    p.evaluate('''() => { window.fetch=async(url,opts)=>{
        calls.push({url,body:JSON.parse(opts.body)});
        if(url==='/api/config') await new Promise(r=>window.resume=r);
        return {ok:true,status:200,json:async()=>({success:true,workflow_state:{ctv_segmentation:true,oar_segmentation:true}})};
    }; window.first=runPlanning(); }''')
    p.evaluate('runPlanning()')
    assert p.evaluate('calls.filter(x=>x.url==="/api/config").length') == 1
    p.evaluate('resume()')
    assert p.evaluate('first')['success'] is False
    assert not any(x[1] == 'Full planning pipeline completed.' for x in p.evaluate('chats'))


@pytest.mark.parametrize('action', ['runPlanning()', 'applyHyperparams()', 'showStepResults("all")', 'exportReport()'])
def test_late_response_never_repaints_a_new_case_or_a_returned_old_case(input_page, action):
    p = input_page
    p.evaluate('''() => { window.fetch=async()=>{await new Promise(r=>window.resume=r);
        return {ok:true,status:200,json:async()=>({success:true})};}; }''')
    p.evaluate('() => { window.work=' + action + '; }')
    count = p.evaluate('chats.length')
    p.evaluate('''() => { activeSessionId='other'; window.__viewerRenderGeneration=1;
        activeSessionId='synthetic'; resume(); }''')
    p.evaluate('work')
    assert p.evaluate('chats.length') == count
    assert p.evaluate('panels.length') == 0


def test_download_rejects_cross_case_and_external_urls(input_page):
    p = input_page
    p.evaluate('window.owner=beginInputAction("test")')
    with pytest.raises(Exception):
        p.evaluate('presentInputDownloads(owner,["https://invalid.example/file","/api/sessions/other/artifacts/file"],"test")')
    assert not p.evaluate('chats.some(x=>x[1].includes("https://invalid"))')
    p.evaluate('owner.finish()')


def test_intraop_uses_separate_scan_and_explicit_current_plan(input_page):
    p = input_page
    p.evaluate('_saveManualState({seed_planning:true})')
    p.evaluate('''() => { window.fetch=async(url,opts)=>{
        const body=opts.body instanceof FormData ? {file:opts.body.get('file').name}:JSON.parse(opts.body);
        calls.push({url,body});
        return {ok:true,status:200,json:async()=>url==='/api/upload'
            ? {path:'/owned/intraoperative.nii.gz'}
            : {success:true,requires_human_review:true,automatic_replanning_blocked:true}};
    }; }''')
    with p.expect_file_chooser() as chooser:
        p.locator('button[onclick="runIntra()"]').click()
    chooser.value.set_files({'name':'synthetic.nii.gz','mimeType':'application/octet-stream','buffer':b'synthetic-boundary-only'})
    p.wait_for_function('calls.length===2')
    assert p.evaluate('calls[1].body') == {'ct_path':'/owned/intraoperative.nii.gz', 'use_current_plan':True, 'deviation_threshold_mm':2}
    assert p.evaluate('state.ctPath') == '/synthetic.nii.gz'
    assert p.locator('#ctPath').input_value() == '/synthetic.nii.gz'
    assert any('automatic replanning was not performed' in x[1] for x in p.evaluate('chats'))


@pytest.mark.parametrize('choice, expected', [('No', 0), ('Yes', 1)])
def test_replan_geometry_requires_confirmation_and_invokes_real_planner(input_page, choice, expected):
    p = input_page
    p.add_script_tag(content=function((JS / 'brachybot-3d-manual.js').read_text(), 'replanManualPlan'))
    p.evaluate('() => { window.plannerCalls=0; window.runPlanning=async()=>{plannerCalls++;return {success:true};};window.work=replanManualPlan(); }')
    assert p.evaluate('plannerCalls') == 0
    p.locator('#_confirm' + choice).click()
    p.evaluate('work')
    assert p.evaluate('plannerCalls') == expected
    assert p.evaluate('inputMutationPending()') is False


def test_guide_parameter_defaults_preserve_catalog_but_case_cleanup_does_not(input_page):
    p = input_page
    p.add_script_tag(content=(JS / 'brachybot-surgical-guide.js').read_text())
    p.evaluate('''() => {
        document.getElementById('guideNeedleSelection').innerHTML='<option value="n1" selected>Needle 1</option>';
        document.getElementById('guideVersionSelect').innerHTML='<option value="1">Guide 1</option>';
        document.getElementById('guidePlateThickness').value='9';
        resetSurgicalGuideControls();
    }''')
    assert p.locator('#guidePlateThickness').input_value() == '3'
    assert p.locator('#guideNeedleSelection option').count() == 1
    assert p.locator('#guideVersionSelect option[value="1"]').count() == 1
    p.evaluate('resetSurgicalGuideControls({clearCatalog:true})')
    assert p.locator('#guideNeedleSelection option').count() == 0
    assert p.locator('#guideVersionSelect option[value="1"]').count() == 0


def test_fixed_model_fields_are_read_only_and_supported_fields_remain_editable(input_page):
    p = input_page
    p.evaluate('document.dispatchEvent(new Event("DOMContentLoaded"))')
    for field in ('seedCountMin', 'dlLR', 'inferSizeX', 'targetValue'):
        assert p.locator('#' + field).is_disabled()
        assert p.locator('#' + field).get_attribute('data-i18n-title-zh')
        assert p.locator('#' + field).get_attribute('data-i18n-title-en')
    for field in ('backlitAngle', 'maxCandiTraj', 'seedRadius', 'inLowestEnergy'):
        assert p.locator('#' + field).is_enabled()
