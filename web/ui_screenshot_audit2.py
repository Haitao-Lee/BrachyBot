#!/usr/bin/env python3
"""UI Screenshot Audit v2 - Comprehensive design review captures"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BASE_URL = "http://localhost:8080"
SCREENSHOTS_DIR = Path("/home/lht/snap/brachyplan/BrachyBot/docs/screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

async def capture_comprehensive():
    """Capture comprehensive UI screenshots for design review"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu"]
        )
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})

        # Full page load
        await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # 1. Complete full page with all panels visible
        await page.screenshot(path=str(SCREENSHOTS_DIR / "design_01_full_page.png"), full_page=False)
        print("✓ design_01_full_page.png")

        # 2. Session sidebar - chat list and new chat button
        sidebar = page.locator(".session-sidebar")
        if await sidebar.count() > 0:
            await sidebar.screenshot(path=str(SCREENSHOTS_DIR / "design_02_sidebar.png"))
            print("✓ design_02_sidebar.png")

        # 3. Chat header area
        chat_header = page.locator(".chat-header")
        if await chat_header.count() > 0:
            await chat_header.screenshot(path=str(SCREENSHOTS_DIR / "design_03_chat_header.png"))
            print("✓ design_03_chat_header.png")

        # 4. Chat messages area with scroll
        chat_messages = page.locator(".chat-messages")
        if await chat_messages.count() > 0:
            await chat_messages.screenshot(path=str(SCREENSHOTS_DIR / "design_04_chat_messages.png"))
            print("✓ design_04_chat_messages.png")

        # 5. Input area - send button and text input
        chat_input_area = page.locator(".chat-input-area")
        if await chat_input_area.count() > 0:
            await chat_input_area.screenshot(path=str(SCREENSHOTS_DIR / "design_05_input_area.png"))
            print("✓ design_05_input_area.png")

        # 6. Right panel tabs
        right_panel = page.locator(".right-panel")
        if await right_panel.count() > 0:
            await right_panel.screenshot(path=str(SCREENSHOTS_DIR / "design_06_right_panel.png"))
            print("✓ design_06_right_panel.png")

        # 7. Panel tabs close-up
        panel_tabs = page.locator(".panel-tabs")
        if await panel_tabs.count() > 0:
            await panel_tabs.screenshot(path=str(SCREENSHOTS_DIR / "design_07_panel_tabs.png"))
            print("✓ design_07_panel_tabs.png")

        # 8. Input form tab
        await page.click(".panel-tab >> text=Input")
        await asyncio.sleep(0.5)
        input_form = page.locator(".input-form")
        if await input_form.count() > 0:
            await input_form.screenshot(path=str(SCREENSHOTS_DIR / "design_08_input_form.png"))
            print("✓ design_08_input_form.png")

        # 9. Analysis tab
        await page.click(".panel-tab >> text=Analysis")
        await asyncio.sleep(0.5)
        metrics = page.locator(".metrics-panel")
        if await metrics.count() > 0:
            await metrics.screenshot(path=str(SCREENSHOTS_DIR / "design_09_analysis_tab.png"))
            print("✓ design_09_analysis_tab.png")

        # 10. Seeds tab
        await page.click(".panel-tab >> text=Seeds")
        await asyncio.sleep(0.5)
        seeds = page.locator(".seeds-panel")
        if await seeds.count() > 0:
            await seeds.screenshot(path=str(SCREENSHOTS_DIR / "design_10_seeds_tab.png"))
            print("✓ design_10_seeds_tab.png")

        # 11. Viewers tab with CT display
        await page.click(".panel-tab >> text=Viewers")
        await asyncio.sleep(0.5)
        viewers = page.locator(".viewers-panel, .viewer-container")
        if await viewers.count() > 0:
            await viewers.screenshot(path=str(SCREENSHOTS_DIR / "design_11_viewers_tab.png"))
            print("✓ design_11_viewers_tab.png")

        # 12. Data tree
        data_tree = page.locator(".data-tree-container")
        if await data_tree.count() > 0:
            await data_tree.screenshot(path=str(SCREENSHOTS_DIR / "design_12_data_tree.png"))
            print("✓ design_12_data_tree.png")

        # 13. Context panel (if visible)
        context_btn = page.locator(".context-toggle-btn")
        if await context_btn.count() > 0:
            await context_btn.click()
            await asyncio.sleep(0.5)
            context_panel = page.locator(".context-panel")
            if await context_panel.count() > 0:
                await context_panel.screenshot(path=str(SCREENSHOTS_DIR / "design_13_context_panel.png"))
                print("✓ design_13_context_panel.png")

        # 14. Tool call message style
        # Send a test message to see tool call UI
        chat_input = page.locator("#chatInput")
        if await chat_input.count() > 0:
            await chat_input.fill("Show me the help")
            await page.click(".chat-send")
            await asyncio.sleep(3)

            # Capture chat with response
            chat_area = page.locator(".chat-area")
            if await chat_area.count() > 0:
                await chat_area.screenshot(path=str(SCREENSHOTS_DIR / "design_14_chat_response.png"))
                print("✓ design_14_chat_response.png")

        # 15. Scrollable content areas
        await page.evaluate("document.querySelector('.chat-messages').scrollTop = 0")
        await asyncio.sleep(0.5)
        chat_messages2 = page.locator(".chat-messages")
        if await chat_messages2.count() > 0:
            await chat_messages2.screenshot(path=str(SCREENSHOTS_DIR / "design_15_scrolled_chat.png"))
            print("✓ design_15_scrolled_chat.png")

        await browser.close()
        print(f"\n✅ Design review screenshots saved to {SCREENSHOTS_DIR}/")

asyncio.run(capture_comprehensive())
