"""Real Chromium DOM tests of the product controls, with synthetic HTTP only."""
from pathlib import Path
import os

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def page():
    playwright = pytest.importorskip('playwright.sync_api')
    binary = os.environ.get('BRACHYBOT_TEST_CHROMIUM')
    if not binary:
        candidate = Path.home() / '.cache/ms-playwright/chromium-1223/chrome-linux64/chrome'
        binary = str(candidate) if candidate.exists() else None
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True, executable_path=binary,
                                          args=['--no-sandbox'])
        instance = browser.new_page(viewport={'width': 900, 'height': 700})
        instance.set_content('''<style>:root {
            --bg-2:#10182b; --bg-3:#172238; --text:#e2e8f0; --text-dim:#94a3b8;
            --card-border:#263149; --radius-sm:12px; --control-r:6px; --primary:#487aff;
        } body {background:#080e1c; font-family:Arial;} .btn {color:var(--text);background:var(--bg-3);border:1px solid var(--card-border);border-radius:6px;cursor:pointer;} .btn-primary{background:var(--primary);}</style>
        <button id="previous">Previous focus</button><div class="chat-input-row"></div>''')
        instance.add_style_tag(content=(ROOT / 'web/app/static/css/brachybot-report-controls.css').read_text())
        instance.evaluate('''() => {
            window.API='/api'; window.activeSessionId='case-a'; window._i18nLang='zh';
            window.effectiveUiLanguage=()=>window._i18nLang;
            window.escHtml=String; window.addChat=(...args)=>window.notices.push(args);
            window.notices=[]; window.requests=[]; window.statusResolvers=[];
            window.fetch=(url, options={})=>{
                window.requests.push({url, options});
                if (options.method==='POST') return Promise.resolve({ok:true,json:async()=>({success:true,persisted:true,session_id:options.headers['X-BrachyBot-Session'],context:{window:1048576,used_tokens:1200,estimated:true}})});
                return new Promise(resolve=>window.statusResolvers.push(resolve));
            };
        }''')
        source = (ROOT / 'web/app/static/js/brachybot-ui-api.js').read_text()
        source = source[source.index('// ── Context-window indicator + manual compression'):]
        instance.add_script_tag(content=source)
        instance.evaluate("window.updateContextIndicator({window:1048576,used_tokens:31139,measured:true,observed_at_ms:2})")
        yield instance
        browser.close()


def post_count(page):
    return page.evaluate("requests.filter(r=>r.options.method==='POST').length")


def test_cancel_opens_immediately_without_waiting_for_status_or_mutating(page):
    page.locator('#previous').focus()
    page.evaluate('void window.compressContextNow(); void window.compressContextNow();')
    assert page.locator('[role=dialog]').count() == 1
    assert page.locator('[role=dialog]').inner_text().startswith('是否压缩上下文？')
    assert post_count(page) == 0
    page.get_by_role('button', name='取消', exact=True).click()
    assert page.locator('[role=dialog]').count() == 0
    assert post_count(page) == 0
    assert page.locator('#previous').evaluate('(el)=>el===document.activeElement')


def test_yes_posts_once_to_the_confirmed_case(page):
    page.evaluate('void window.compressContextNow()')
    page.get_by_role('button', name='是，确认压缩').click()
    page.wait_for_function("requests.some(r=>r.options.method==='POST')")
    row = page.evaluate("requests.find(r=>r.options.method==='POST')")
    assert row['options']['headers']['X-BrachyBot-Session'] == 'case-a'
    assert '"confirmed":true' in row['options']['body']
    assert post_count(page) == 1


def test_case_switch_while_modal_open_never_compacts_another_case(page):
    page.evaluate('void window.compressContextNow()')
    page.evaluate("window.activeSessionId='case-b'")
    page.get_by_role('button', name='是，确认压缩').click()
    page.wait_for_function("document.querySelector('[role=dialog]')===null")
    assert post_count(page) == 0


def test_global_language_changes_existing_modal_and_ring(page):
    page.evaluate('void window.compressContextNow()')
    page.evaluate("window._i18nLang='en'; window.dispatchEvent(new Event('i18nchange'))")
    assert page.get_by_role('button', name='Yes, compress context').count() == 1
    assert 'Current context' in page.locator('#contextRing').get_attribute('title')
    page.keyboard.press('Escape')
    assert page.locator('[role=dialog]').count() == 0
    assert post_count(page) == 0


def test_ring_uses_counts_not_a_conflicting_ratio_and_rejects_late_snapshots(page):
    page.evaluate("window.updateContextIndicator({window:100000,used_tokens:5000,ratio:0.9,measured:true,observed_at_ms:3})")
    assert page.locator('#contextRingLabel').inner_text() == '5%'
    page.evaluate("window.updateContextIndicator({window:100000,used_tokens:90000,observed_at_ms:1})")
    assert page.locator('#contextRingLabel').inner_text() == '5%'
    page.evaluate("window.updateContextIndicator({window:100000,used_tokens:300,estimated:true,observed_at_ms:4})")
    assert page.locator('#contextRingLabel').inner_text() == '~<1%'


def test_keyboard_focus_is_trapped_and_overlay_click_cancels(page):
    page.evaluate('void window.compressContextNow()')
    page.get_by_role('button', name='是，确认压缩').focus()
    page.keyboard.press('Tab')
    assert page.get_by_role('button', name='关闭', exact=True).evaluate('(el)=>el===document.activeElement')
    page.locator('.context-compress-overlay').click(position={'x': 5, 'y': 5})
    assert post_count(page) == 0


def test_partial_provider_usage_is_not_presented_as_a_complete_measurement(page):
    page.evaluate("window.updateContextIndicator({window:100000,used_tokens:5000,measured:true,context_complete:false,missing_usage_calls:1,turn_total_tokens:12000,observed_at_ms:3})")
    assert page.locator('#contextRingLabel').inner_text() == '≥5%'
    assert '下界' in page.locator('#contextRing').get_attribute('title')
    assert '≥12,000' in page.locator('#contextRing').get_attribute('title')
    page.evaluate('void window.compressContextNow()')
    assert '下界' in page.locator('.context-compress-stats').inner_text()
    page.keyboard.press('Escape')
    assert post_count(page) == 0


def test_status_update_preserves_the_confirmation_button_and_focus(page):
    page.evaluate('void window.compressContextNow()')
    page.get_by_role('button', name='是，确认压缩').focus()
    page.evaluate("window.savedButton=document.querySelector('[data-act=confirm]'); window.statusResolvers[0]({ok:true,json:async()=>({session_id:'case-a',context:{window:100000,used_tokens:40000,measured:true}})})")
    page.wait_for_function("document.querySelector('.context-compress-stats').textContent.includes('40,000')")
    assert page.evaluate('savedButton===document.activeElement && savedButton===document.querySelector("[data-act=confirm]")')
    artifact_dir = os.environ.get('BRACHYBOT_TEST_ARTIFACT_DIR')
    if artifact_dir:
        target = Path(artifact_dir)
        target.mkdir(parents=True, exist_ok=True)
        page.wait_for_function("Number(getComputedStyle(document.querySelector('.context-compress-overlay')).opacity)>0.99")
        page.screenshot(path=str(target / 'context-compress-zh.png'))
        page.evaluate("window._i18nLang='en'; window.dispatchEvent(new Event('i18nchange'))")
        page.screenshot(path=str(target / 'context-compress-en.png'))
    page.keyboard.press('Escape')
    assert post_count(page) == 0


def test_cold_zero_date_estimate_cannot_overwrite_measured_context(page):
    page.evaluate("window.updateContextIndicator({window:100000,used_tokens:1000,estimated:true,observed_at_ms:0})")
    assert page.locator('#contextRingLabel').inner_text() == '3%'


def test_durable_revision_rejects_late_sse_and_accepts_real_new_smaller_call(page):
    page.evaluate("window.updateContextIndicator({session_id:'case-a',epoch:'a'.repeat(32),revision:8,window:100000,used_tokens:4200,measured:true,observed_at_ms:10,updated_at_ms:10,session_total_tokens:4200,session_calls:1,retained_history_tokens:1000,retained_messages:12})")
    assert page.locator('#contextRingLabel').inner_text() == '4.2%'
    title = page.locator('#contextRing').get_attribute('title')
    assert '最近请求上下文' in title and '本会话累计消耗：4,200' in title
    page.evaluate("window.updateContextIndicator({session_id:'case-a',epoch:'a'.repeat(32),revision:7,window:100000,used_tokens:1000,estimated:true,observed_at_ms:1000})")
    assert page.locator('#contextRingLabel').inner_text() == '4.2%'
    page.evaluate("window.updateContextIndicator({session_id:'case-a',epoch:'a'.repeat(32),revision:9,window:100000,used_tokens:3100,measured:true,observed_at_ms:11,updated_at_ms:11,change_reason:'request_selection',session_total_tokens:7300,session_calls:2})")
    assert page.locator('#contextRingLabel').inner_text() == '3.1%'
    assert '不代表删除聊天' in page.locator('#contextRing').get_attribute('title')


def test_context_snapshot_is_fenced_by_owning_case(page):
    page.evaluate("window.updateContextIndicator({session_id:'case-b',window:100000,used_tokens:90000,measured:true,observed_at_ms:200})")
    assert page.locator('#contextRingLabel').inner_text() == '3%'


def test_case_shell_hides_other_case_ring_until_own_status_is_available(page):
    page.evaluate("window.activeSessionId='case-b'; window.resetContextIndicatorForCase()")
    assert page.locator('#contextRingLabel').inner_text() == '–'
    assert '正在读取当前会话' in page.locator('#contextRing').get_attribute('title')
    page.evaluate("window.activeSessionId='case-a'; window.resetContextIndicatorForCase()")
    assert page.locator('#contextRingLabel').inner_text() == '3%'


def test_equal_revision_older_measurement_is_rejected(page):
    page.evaluate("window.updateContextIndicator({epoch:'a'.repeat(32),revision:10,updated_at_ms:10,observed_at_ms:12,window:100000,used_tokens:4200,measured:true})")
    page.evaluate("window.updateContextIndicator({epoch:'a'.repeat(32),revision:10,updated_at_ms:10,observed_at_ms:11,window:100000,used_tokens:3000,estimated:true})")
    assert page.locator('#contextRingLabel').inner_text() == '4.2%'


def test_new_ledger_can_reset_context_without_resurrecting_old_epoch(page):
    page.evaluate("window.updateContextIndicator({epoch:'a'.repeat(32),revision:50,updated_at_ms:10,window:100000,used_tokens:5000,measured:true})")
    page.evaluate("window.updateContextIndicator({epoch:'b'.repeat(32),revision:1,updated_at_ms:11,window:100000,used_tokens:0,estimated:true})")
    assert page.locator('#contextRingLabel').inner_text() == '–'
    page.evaluate("window.updateContextIndicator({epoch:'a'.repeat(32),revision:50,updated_at_ms:10,window:100000,used_tokens:5000,measured:true})")
    assert page.locator('#contextRingLabel').inner_text() == '–'


def test_session_usage_lower_bound_and_restart_provenance_follow_global_language(page):
    page.evaluate("window.updateContextIndicator({epoch:'a'.repeat(32),revision:1,updated_at_ms:10,window:100000,used_tokens:5000,measured:true,session_total_tokens:40000,session_calls:3,session_missing_usage_calls:1,preexisting_history:true,restored_snapshot:true})")
    assert '≥40,000' in page.locator('#contextRing').get_attribute('title')
    assert '不是重新估算' in page.locator('#contextRing').get_attribute('title')
    page.evaluate("window._i18nLang='en'; window.dispatchEvent(new Event('i18nchange'))")
    title = page.locator('#contextRing').get_attribute('title')
    assert 'Session consumption: ≥40,000' in title
    assert 'not re-estimated' in title
    assert '本会话' not in title


def test_wrong_case_status_response_cannot_change_ring(page):
    page.evaluate('void window.refreshContextStatus()')
    page.evaluate("window.statusResolvers[0]({ok:true,json:async()=>({session_id:'case-b',context:{window:100000,used_tokens:90000,observed_at_ms:200}})})")
    page.wait_for_function("!document.querySelector('#contextRing').classList.contains('is-busy')")
    assert page.locator('#contextRingLabel').inner_text() == '3%'


def test_version_three_footer_uses_current_contract_not_legacy_warning(page):
    source = (ROOT / 'web/app/static/js/brachybot-chat-core.js').read_text()
    source = source[source.index('function _buildResponseFooter('):source.index('function _appendRestoredFooter(')]
    page.evaluate("window._footerI18n=()=>({time:'Time',context:'Context',tokens:'Turn total',input:'Input',output:'Output',tools:'Tools',unit_s:'s',unit_times:'x',hint_context:'Latest request contract',hint_total:'Sum of calls'}); window._todoTurnToolCount=1")
    page.add_script_tag(content=source)
    page.evaluate("document.body.appendChild(_buildResponseFooter({latency_ms:500,context_status:{accounting_version:3,used_tokens:3100,measured:true,context_complete:false},usage:{prompt_tokens:7000,completion_tokens:200,usage_complete:true}}))")
    context = page.locator('.usage-item').filter(has_text='Context')
    assert context.get_attribute('title') == 'Latest request contract'
    assert context.inner_text() == 'Context≥3,100'
    assert '7,200' in page.locator('.usage-bar').inner_text()
