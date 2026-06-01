#!/usr/bin/env python3
"""UI Detailed Screenshot Capture - Chat responses, viewer layouts, etc."""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BASE_URL = "http://localhost:8080"
SCREENSHOTS_DIR = Path("/home/lht/snap/brachyplan/BrachyBot/docs/screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

async def capture_detailed():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu"]
        )
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})

        await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # === 1. Chat Response Text Layout ===
        print("Capturing chat response layouts...")

        # Send a simple message
        chat_input = page.locator("#chatInput")
        await chat_input.fill("Hello, what can you do?")
        await page.click(".chat-send")
        await asyncio.sleep(5)

        await page.screenshot(path=str(SCREENSHOTS_DIR / "detail_01_chat_response.png"), full_page=False)
        print("✓ detail_01_chat_response.png")

        # Send another message with longer response
        await chat_input.fill("Explain what brachytherapy is")
        await page.click(".chat-send")
        await asyncio.sleep(8)

        await page.screenshot(path=str(SCREENSHOTS_DIR / "detail_02_long_response.png"), full_page=False)
        print("✓ detail_02_long_response.png")

        # Capture thinking indicator if visible
        thinking = page.locator(".thinking-indicator")
        if await thinking.count() > 0:
            await thinking.screenshot(path=str(SCREENSHOTS_DIR / "detail_03_thinking_indicator.png"))
            print("✓ detail_03_thinking_indicator.png")

        # Capture message with code block
        await chat_input.fill("Show me example code for DVH calculation")
        await page.click(".chat-send")
        await asyncio.sleep(8)

        await page.screenshot(path=str(SCREENSHOTS_DIR / "detail_04_code_block.png"), full_page=False)
        print("✓ detail_04_code_block.png")

        # === 2. Viewer Layout Modes ===
        print("\nCapturing viewer layouts...")

        # Switch to Viewers tab
        await page.click(".panel-tab >> text=Viewers")
        await asyncio.sleep(1)

        # Default layout (vertical stack)
        await page.screenshot(path=str(SCREENSHOTS_DIR / "detail_05_viewer_vertical.png"), full_page=False)
        print("✓ detail_05_viewer_vertical.png")

        # Try grid layout
        layout_btns = page.locator(".layout-btn")
        for i in range(await layout_btns.count()):
            btn = layout_btns.nth(i)
            btn_text = await btn.inner_text()
            if "grid" in btn_text.lower() or "2x2" in btn_text.lower():
                await btn.click()
                await asyncio.sleep(0.5)
                break

        await page.screenshot(path=str(SCREENSHOTS_DIR / "detail_06_viewer_grid.png"), full_page=False)
        print("✓ detail_06_viewer_grid.png")

        # Try horizontal layout
        for i in range(await layout_btns.count()):
            btn = layout_btns.nth(i)
            btn_text = await btn.inner_text()
            if "horizontal" in btn_text.lower() or "row" in btn_text.lower():
                await btn.click()
                await asyncio.sleep(0.5)
                break

        await page.screenshot(path=str(SCREENSHOTS_DIR / "detail_07_viewer_horizontal.png"), full_page=False)
        print("✓ detail_07_viewer_horizontal.png")

        # Try 3D top layout
        for i in range(await layout_btns.count()):
            btn = layout_btns.nth(i)
            btn_text = await btn.inner_text()
            if "3d" in btn_text.lower() and "top" in btn_text.lower():
                await btn.click()
                await asyncio.sleep(0.5)
                break

        await page.screenshot(path=str(SCREENSHOTS_DIR / "detail_08_viewer_3d_top.png"), full_page=False)
        print("✓ detail_08_viewer_3d_top.png")

        # Try 3D bottom layout
        for i in range(await layout_btns.count()):
            btn = layout_btns.nth(i)
            btn_text = await btn.inner_text()
            if "3d" in btn_text.lower() and "bottom" in btn_text.lower():
                await btn.click()
                await asyncio.sleep(0.5)
                break

        await page.screenshot(path=str(SCREENSHOTS_DIR / "detail_09_viewer_3d_bottom.png"), full_page=False)
        print("✓ detail_09_viewer_3d_bottom.png")

        # === 3. Input Form Data Upload Simulation ===
        print("\nCapturing input form...")

        await page.click(".panel-tab >> text=Input")
        await asyncio.sleep(0.5)

        await page.screenshot(path=str(SCREENSHOTS_DIR / "detail_10_input_form_full.png"), full_page=False)
        print("✓ detail_10_input_form_full.png")

        # === 4. Message Actions (copy, regenerate etc) ===
        print("\nCapturing message interactions...")

        # Hover over a bot message
        msg_wrapper = page.locator(".chat-msg-wrapper.bot").first
        if await msg_wrapper.count() > 0:
            await msg_wrapper.hover()
            await asyncio.sleep(0.5)
            await msg_wrapper.screenshot(path=str(SCREENSHOTS_DIR / "detail_11_msg_hover.png"))
            print("✓ detail_11_msg_hover.png")

        # === 5. Context Panel Expanded ===
        print("\nCapturing context panel...")

        context_btn = page.locator(".context-toggle-btn")
        if await context_btn.count() > 0:
            await context_btn.click()
            await asyncio.sleep(0.5)
            await page.screenshot(path=str(SCREENSHOTS_DIR / "detail_12_context_expanded.png"), full_page=False)
            print("✓ detail_12_context_expanded.png")

        # === 6. Sidebar New Chat Button ===
        sidebar = page.locator(".session-sidebar")
        if await sidebar.count() > 0:
            await sidebar.hover()
            await asyncio.sleep(0.3)
            await sidebar.screenshot(path=str(SCREENSHOTS_DIR / "detail_13_sidebar_hover.png"))
            print("✓ detail_13_sidebar_hover.png")

        # === 7. Full Page After Interaction ===
        await page.screenshot(path=str(SCREENSHOTS_DIR / "detail_14_full_page_final.png"), full_page=False)
        print("✓ detail_14_full_page_final.png")

        await browser.close()
        print(f"\n✅ Detailed screenshots saved to {SCREENSHOTS_DIR}/")

asyncio.run(capture_detailed())
