#!/usr/bin/env python3
"""UI Screenshot Audit - Capture BrachyBot UI for design review"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BASE_URL = "http://localhost:8080"
SCREENSHOTS_DIR = Path("/home/lht/snap/brachyplan/BrachyBot/docs/screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

async def capture_ui():
    """Capture UI screenshots for audit"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu"]
        )
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})

        # 1. Full page screenshot
        await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)
        await page.screenshot(path=str(SCREENSHOTS_DIR / "01_full_page.png"), full_page=False)
        print("✓ Captured 01_full_page.png")

        # 2. Chat area - close up
        chat_area = page.locator("#chatContainer")
        if await chat_area.count() > 0:
            await chat_area.screenshot(path=str(SCREENSHOTS_DIR / "02_chat_area.png"))
            print("✓ Captured 02_chat_area.png")

        # 3. Input area
        input_area = page.locator("#chatInput")
        if await input_area.count() > 0:
            await input_area.screenshot(path=str(SCREENSHOTS_DIR / "03_input_area.png"))
            print("✓ Captured 03_input_area.png")

        # 4. Tabs area
        tabs = page.locator(".tab-button")
        if await tabs.count() > 0:
            await tabs.screenshot(path=str(SCREENSHOTS_DIR / "04_tabs.png"))
            print("✓ Captured 04_tabs.png")

        # 5. Right panel (Viewers)
        right_panel = page.locator("#rightPanel")
        if await right_panel.count() > 0:
            await right_panel.screenshot(path=str(SCREENSHOTS_DIR / "05_right_panel.png"))
            print("✓ Captured 05_right_panel.png")

        # 6. Input tab content
        await page.click("text=Input")
        await asyncio.sleep(1)
        await page.screenshot(path=str(SCREENSHOTS_DIR / "06_input_tab.png"))
        print("✓ Captured 06_input_tab.png")

        # 7. Analysis tab content
        await page.click("text=Analysis")
        await asyncio.sleep(1)
        await page.screenshot(path=str(SCREENSHOTS_DIR / "07_analysis_tab.png"))
        print("✓ Captured 07_analysis_tab.png")

        # 8. Seeds tab content
        await page.click("text=Seeds")
        await asyncio.sleep(1)
        await page.screenshot(path=str(SCREENSHOTS_DIR / "08_seeds_tab.png"))
        print("✓ Captured 08_seeds_tab.png")

        # 9. Viewers tab content
        await page.click("text=Viewers")
        await asyncio.sleep(1)
        await page.screenshot(path=str(SCREENSHOTS_DIR / "09_viewers_tab.png"))
        print("✓ Captured 09_viewers_tab.png")

        # 10. Data tree
        data_tree = page.locator("#dataTree")
        if await data_tree.count() > 0:
            await data_tree.screenshot(path=str(SCREENSHOTS_DIR / "10_data_tree.png"))
            print("✓ Captured 10_data_tree.png")

        # 11. Full page after tab switch
        await page.screenshot(path=str(SCREENSHOTS_DIR / "11_full_viewers.png"), full_page=False)
        print("✓ Captured 11_full_viewers.png")

        # 12. Header/Menu area
        header = page.locator(".header, #header, header")
        if await header.count() > 0:
            await header.screenshot(path=str(SCREENSHOTS_DIR / "12_header.png"))
            print("✓ Captured 12_header.png")

        # 13. Send button area
        send_btn = page.locator(".chat-send, #sendButton, button:has-text('Send')")
        if await send_btn.count() > 0:
            await send_btn.screenshot(path=str(SCREENSHOTS_DIR / "13_send_button.png"))
            print("✓ Captured 13_send_button.png")

        await browser.close()
        print(f"\n✅ All screenshots saved to {SCREENSHOTS_DIR}/")

asyncio.run(capture_ui())
