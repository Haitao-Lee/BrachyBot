"""Real DOM visual-component acceptance; synthetic images, no product network."""
import os
from pathlib import Path

import pytest


def between(source, start, end):
    a = source.index(start)
    return source[a:source.index(end, a + len(start))]


def test_visual_delivery_continuous_clock_and_responsive_status(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    root = Path(__file__).resolve().parents[1]
    core = (root / "web/app/static/js/brachybot-chat-core.js").read_text()
    todo = (root / "web/app/static/js/brachybot-chat-todo.js").read_text()
    scripts = "\n".join([
        between(core, "function ensureAssistantReplyContainer(", "\nfunction _chatAttachmentLanguage("),
        between(core, "function createLiveThinkingChain(", "\nconst _mountedAssistantFinalRequestIds"),
        between(core, "const _mountedAssistantFinalRequestIds", "\nfunction createStreamingResponse("),
        between(todo, "function _updateVisualDeliveryStatus(", "\nfunction _finishFinalResponseTraceSteps("),
    ])
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True, executable_path=os.getenv("SCREENSHOT_UX_CHROME"))
        try:
            page = browser.new_page(viewport={"width": 1050, "height": 880}, reduced_motion="reduce")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.set_content('''<style>:root{--bg-sunken:#090e19;--bg-1:#111b2b;--text:#e2e8f2;
                --text-secondary:#c3d0e5;--text-dim:#98a9c4;--border-soft:#2c3a51;--border-hairline:#202d41;
                --radius-sm:12px;--accent:#829cff}body{margin:0;background:#0a1120;color:var(--text);font:14px/1.5 Arial}
                main{max-width:850px;padding:28px;margin:auto}.chat-row{display:flex;gap:10px}
                .chat-msg-wrapper{min-width:0;flex:1}.chat-avatar{flex:0 0 30px}
                .chat-row.bot{margin-bottom:14px}.thinking-chain{min-width:280px;max-width:460px}
                .chat-image-gallery{display:flex;gap:12px}.chat-gallery-item{width:160px}
                .synthetic-preview{display:grid;place-items:center;height:110px;background:#071018;color:#97d77b;border:1px solid #334864;border-radius:9px}
                @media(max-width:450px){main{padding:12px}.chat-gallery-item{width:120px}.thinking-chain{min-width:0;width:100%}}</style>
                <main><div id="chatMessages"></div></main>''')
            page.add_style_tag(path=str(root / "web/app/static/css/brachybot-chat-status.css"))
            page.add_script_tag(content='''window.activeSessionId='synthetic';window.CHAT_AVATAR_SVGS={bot:'B'};
                window.escHtml=value=>String(value);window._chatDomKey=value=>value;
                window.createChatIdentity=value=>value;window._normalizeTraceLanguage=value=>value;
                window.effectiveUiLanguage=()=> 'zh';window.requestChatScrollToBottom=()=>{};
                window.toggleThinkingChain=()=>{};window.updateChainHeader=()=>{};
                window.STEP_ICONS={user:'●',routing:'●',tool:'●',assistant:'●'};
                window._localizeStepTitle=value=>value;window._localizeStepStatus=value=>({done:'完成',pending:'等待中'}[value]||value);
                window.sanitizeChatErrorContent=value=>value;
                window._chainI18n=key=>({thinking:'执行追踪',header:'执行追踪',steps_suffix:' 步',stopped:'已取消'}[key]||key);''')
            page.add_script_tag(content=scripts)
            page.evaluate('''() => {
                window.live=createLiveThinkingChain(Date.now()-43500,'parent','zh');
                window.steps=[
                    {id:1,type:'user',title:'用户输入',status:'done',content:'肿瘤在哪里啊'},
                    {id:2,type:'routing',title:'连接与准备',status:'done',content:'对象定位'},
                    {id:3,type:'tool',tool:'ui_screenshot',title:'生成截图',status:'done',content:'截图已保存并标注'},
                    {id:4,type:'assistant',title:'生成回复',status:'done',content:'图片证据已就绪'},
                    {id:5,type:'assistant',title:'最终回复',phase:'final_response',status:'pending',content:'正在核对截图证据'}];
                steps.forEach((step,index)=>appendStepToChain(live.stepsDiv,step,index));
                window.record={sessionId:'synthetic',requestId:'parent',assistantMessageId:'assistant-parent',responseLanguage:'zh'};
                _updateVisualDeliveryStatus(record,'checking');
                const shell=ensureAssistantReplyContainer('parent','assistant-parent');
                shell.attachments.hidden=false;
                shell.attachments.innerHTML='<div class="chat-gallery-item"><div class="synthetic-preview">[ 已标注的节点 ]</div><div class="chat-image-caption">数据树 · 合成示例</div></div><div class="chat-gallery-item"><div class="synthetic-preview">↘ 合成靶区</div><div class="chat-image-caption">三维查看器 · 合成示例</div></div>';
                finalizeThinkingChain(live.chainEl,live.headerEl,steps);
            }''')
            before = float(page.locator(".thinking-time").inner_text()[:-1])
            page.wait_for_timeout(1150)
            after = float(page.locator(".thinking-time").inner_text()[:-1])
            assert after > before + 0.7
            assert page.locator(".visual-delivery-title").inner_text() == "截图已就绪 · 正在核对证据"
            assert page.locator(".visual-delivery-status").get_attribute("role") == "status"
            assert page.locator(".visual-delivery-dot").evaluate("el=>getComputedStyle(el).animationName") == "none"
            screenshot = root / "screenshot-ux-component.png"
            page.screenshot(path=str(screenshot))
            page.set_viewport_size({"width": 360, "height": 700})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.evaluate("_updateVisualDeliveryStatus(record,'done'); steps[4].status='done'; finalizeThinkingChain(live.chainEl,live.headerEl,steps)")
            assert page.locator(".visual-delivery-status").count() == 0
            assert page.evaluate("live.headerEl._timer === null && live.chainEl.dataset.deliveryPending === undefined")
            # Locale follows the owning turn, not a late global toggle; old
            # case status cannot paint onto the new selected Session.
            page.evaluate("record.responseLanguage='en'; _updateVisualDeliveryStatus(record,'checking')")
            assert "Images ready" in page.locator(".visual-delivery-title").inner_text()
            page.evaluate("_updateVisualDeliveryStatus(record,'cancelled'); activeSessionId='other'; _updateVisualDeliveryStatus(record,'checking')")
            assert page.locator(".visual-delivery-status").count() == 0
            assert not errors
        finally:
            browser.close()
