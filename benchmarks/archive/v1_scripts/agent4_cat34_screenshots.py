#!/usr/bin/env python3
"""
Take screenshots for Category 34 using the correct CSS selector.
"""
import json, os, time

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def take_screenshot(case_id, cat_num, input_text, retries=2):
    screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
        print(f"    Already exists: {screenshot_path}")
        return screenshot_path

    for attempt in range(retries):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})

                # Navigate to BrachyBot
                page.goto(BASE_URL, timeout=30000, wait_until='networkidle')
                time.sleep(2)

                # Fill input and send
                page.wait_for_selector('#chatInput', timeout=10000)
                page.fill('#chatInput', input_text)
                time.sleep(0.5)
                page.locator('.chat-send').click()

                # Wait for bot response using CORRECT selector
                page.wait_for_selector('.chat-msg.bot-response', timeout=60000)

                # Wait for response to populate
                time.sleep(3)

                page.wait_for_function(
                    """() => {
                        const msgs = document.querySelectorAll('.chat-msg.bot-response');
                        const lastMsg = msgs[msgs.length - 1];
                        return lastMsg && lastMsg.textContent.length > 50;
                    }""",
                    timeout=60000
                )

                time.sleep(2)
                page.screenshot(path=screenshot_path, full_page=True)
                browser.close()

            return screenshot_path
        except Exception as e:
            print(f"    Screenshot failed on attempt {attempt + 1}: {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return None

if __name__ == "__main__":
    with open(f"{BENCHMARK_DIR}/34_multi_turn.json", 'r') as f:
        data = json.load(f)
    cases = data.get('cases', data)

    print(f"Taking screenshots for {len(cases)} cat 34 cases...")

    for tc in cases:
        case_id = tc.get('id')
        turns = tc.get('turns', [])
        if turns:
            input_text = turns[0].get('input', '')
        else:
            input_text = tc.get('input', '')

        if not input_text:
            print(f"  {case_id}: SKIP (no input)")
            continue

        print(f"  {case_id}...", end=" ", flush=True)
        result = take_screenshot(case_id, 34, input_text)
        if result:
            size = os.path.getsize(result)
            print(f"OK ({size} bytes)")
        else:
            print("FAILED")

    print("Done!")
