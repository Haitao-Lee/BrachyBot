"""Monitor usage guide with real product DOM/measurement events, synthetic CT."""
import json
from pathlib import Path

import pytest

from test_viewers_toolbar_browser import page
from agent_runtime.ui_control_manual import catalog, VERSION

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def guided(page):
    page.route('**/api/ui/manual', lambda route:route.fulfill(status=200, content_type='application/json',
        headers={'Access-Control-Allow-Origin':'*'}, body=json.dumps({'success':True,'manual_version':VERSION,'cards':catalog()})))
    page.add_script_tag(content="window.API='http://control.test/api';window.trainingMonitorState={active:true,runId:'synthetic-run'};window._i18nLang='en';")
    page.add_style_tag(path=str(ROOT/'web/app/static/css/brachybot-control-guide.css'))
    page.add_style_tag(content='''
        :root {--bg-2:#141c30;--border-default:#28344d;--text:#dfe7f5;--text-secondary:#9daac0;--accent-ink:#638cff;}
        #panelViewers {position:fixed;inset:0;display:flex;flex-direction:column;background:#0d1424;color:#dfe7f5;overflow:auto;font-family:Arial;padding:12px;}
        #panelViewers .viewer-workspace {min-height:500px!important;}
        .control-usage-guide {flex-shrink:0;}
    ''')
    page.add_script_tag(path=str(ROOT/'web/app/static/js/brachybot-control-guide.js'))
    return page


def test_line_guide_matches_real_drag_and_does_not_create_annotations_on_explanation(guided, tmp_path):
    page = guided
    page.locator('#toolMeasure').click()
    guide = page.locator('#controlUsageGuide')
    guide.wait_for()
    assert 'hold the left mouse button' in guide.inner_text()
    assert page.evaluate('state.annotations.length') == 0
    assert page.evaluate('state.viewerSettings.activeTool') == 'measure'
    assert not page.evaluate('chats.length')
    assert page.evaluate("document.querySelector('#controlUsageGuide').nextElementSibling.classList.contains('viewer-workspace')")
    assert page.evaluate("document.querySelector('#controlUsageGuide').scrollHeight <= document.querySelector('#controlUsageGuide').clientHeight+1")
    page.screenshot(path=str(tmp_path/'line-guide.png'))
    page.locator('#toolMeasure').click()
    page.wait_for_timeout(400)
    assert guide.count() == 0


def test_angle_points_language_and_completion_use_actual_tool_state(guided):
    page = guided
    page.locator('#toolAngle').click()
    page.locator('#controlUsageGuide').wait_for()
    box = page.locator('#sliceCanvasAxial').bounding_box()
    for index, (x,y) in enumerate([(10,10),(30,30),(50,30)]):
        page.mouse.click(box['x']+x, box['y']+y)
        page.wait_for_timeout(400)
        if index < 2:
            assert f'{index+1}/3' in page.locator('[data-usage-part="progress"]').inner_text()
    assert page.evaluate('state.annotations[0].angleDeg') == pytest.approx(116.56505117707799)
    assert '116.6°' in page.locator('[data-usage-part="progress"]').inner_text()
    page.evaluate('viewerUndo()'); page.wait_for_timeout(400)
    assert '0/3' in page.locator('[data-usage-part="progress"]').inner_text()
    page.evaluate("window._i18nLang='zh';window.dispatchEvent(new Event('i18nchange'))")
    page.wait_for_timeout(100)
    assert '第二个点是角的顶点' in page.locator('#controlUsageGuide').inner_text()
    assert 'Select Angle' not in page.locator('#controlUsageGuide').inner_text()
    assert page.locator('.control-usage-dismiss').get_attribute('aria-label') == '关闭这条提示'


@pytest.mark.parametrize('change', ["activeSessionId='another'", "trainingMonitorState.runId='new'", "trainingMonitorState.active=false", "state.viewerSettings.activeTool=null"])
def test_guide_is_fenced_and_removed_without_mutating_a_case(guided, change):
    page = guided
    page.locator('#toolAngle').click(); page.locator('#controlUsageGuide').wait_for()
    page.evaluate(change); page.wait_for_timeout(450)
    assert page.locator('#controlUsageGuide').count() == 0
    assert page.evaluate('state.annotations.length') == 0


def test_dismiss_does_not_cancel_the_tool_and_inactive_monitor_has_no_hint(guided):
    page = guided
    page.locator('#toolAngle').click(); page.locator('#controlUsageGuide').wait_for()
    page.locator('.control-usage-dismiss').click()
    assert page.evaluate('state.viewerSettings.activeTool') == 'angle'
    assert page.locator('#controlUsageGuide').count() == 0
    page.evaluate("trainingMonitorState.active=false")
    page.locator('#toolMeasure').click(); page.wait_for_timeout(100)
    assert page.locator('#controlUsageGuide').count() == 0


def test_delayed_manual_fetch_cannot_attach_a_guide_to_a_new_case(guided):
    page = guided
    page.unroute('**/api/ui/manual')
    page.evaluate("() => { window.fetch=()=>new Promise(resolve=>window.resolveManual=resolve); }")
    page.locator('#toolAngle').click()
    page.evaluate("activeSessionId='another'")
    page.evaluate("cards=>window.resolveManual({ok:true,json:async()=>({success:true,cards})})", catalog())
    page.wait_for_timeout(100)
    assert page.locator('#controlUsageGuide').count() == 0


def test_unavailable_manual_does_not_block_normal_measurement(guided):
    page = guided
    page.unroute('**/api/ui/manual')
    page.route('**/api/ui/manual', lambda route:route.fulfill(status=503))
    page.locator('#toolMeasure').click(); page.wait_for_timeout(100)
    assert page.evaluate('state.viewerSettings.activeTool') == 'measure'
    assert page.locator('#controlUsageGuide').count() == 0


def test_programmatic_tool_selection_uses_the_same_guide(guided):
    guided.evaluate("setViewerTool('angle')")
    guided.locator('#controlUsageGuide').wait_for()
    assert 'SECOND point' in guided.locator('#controlUsageGuide').inner_text()
    assert guided.evaluate('state.annotations.length') == 0


def test_idle_hint_does_not_repeat_live_region_announcements(guided):
    guided.evaluate("setViewerTool('angle')")
    guided.locator('#controlUsageGuide').wait_for()
    guided.evaluate('''() => {
        window.hintMutations=0;
        new MutationObserver(rows => window.hintMutations+=rows.length).observe(
            document.querySelector('.control-usage-body'), {childList:true,subtree:true,characterData:true});
    }''')
    guided.wait_for_timeout(850)
    assert guided.evaluate('window.hintMutations') == 0


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_hint_uses_real_global_theme_and_does_not_cover_the_viewport(guided, theme, tmp_path):
    page = guided
    page.add_style_tag(path=str(ROOT/'web/app/static/css/brachybot-theme-layout.css'))
    page.add_style_tag(path=str(ROOT/'web/app/static/css/brachybot-panels-viewers.css'))
    page.add_style_tag(path=str(ROOT/'web/app/static/css/brachybot-control-guide.css'))
    page.evaluate('''theme=>{
        document.documentElement.dataset.theme=theme;
        document.querySelector('#panelViewers').classList.add('active');
    }''', theme)
    page.locator('#toolAngle').click()
    page.locator('#controlUsageGuide').wait_for()
    page.wait_for_timeout(100)
    assert page.evaluate('''() => {
        const guide=document.querySelector('#controlUsageGuide');
        const actual=getComputedStyle(guide);
        const probe=document.createElement('div');probe.style.cssText='color:var(--text);background:var(--bg-2)';
        document.body.append(probe);const expected=getComputedStyle(probe);
        const matches=actual.color===expected.color && actual.backgroundColor===expected.backgroundColor;
        probe.remove();return matches;
    }''')
    guide = page.locator('#controlUsageGuide').bounding_box()
    viewport = page.locator('#panelViewers .viewer-workspace').bounding_box()
    assert guide['y']+guide['height'] <= viewport['y']+1
    page.screenshot(path=str(tmp_path/f'control-guide-{theme}.png'))
