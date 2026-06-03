#!/usr/bin/env python3
"""Take screenshots for all completed API test cases."""
import json, os, sys, time, glob

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"

def take_screenshots(cat_num):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return
    with open(files[0]) as f:
        data = json.load(f)
    cases = data.get('cases', data) if isinstance(data, dict) else data

    existing = set()
    for fn in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        case_id = os.path.basename(fn).replace(f"{cat_num:02d}_", "").replace(".png", "")
        if os.path.getsize(fn) > 1000:
            existing.add(case_id)

    needed = [c for c in cases if c.get('id', '') not in existing]
    if not needed:
        print(f"Category {cat_num}: all {len(existing)} screenshots done")
        return

    print(f"Category {cat_num}: {len(existing)} existing, {len(needed)} needed")

    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except Exception as e:
        print(f"  Cannot launch browser: {e}")
        return

    for i, case in enumerate(needed):
        case_id = case.get('id', f'Q{i+1:04d}')
        path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
        try:
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=30000)
            page.wait_for_load_state('networkidle', timeout=15000)
            time.sleep(1)
            page.screenshot(path=path, full_page=True)
            page.close()
            print(f"  [{i+1}/{len(needed)}] {case_id} OK")
        except Exception as e:
            print(f"  [{i+1}/{len(needed)}] {case_id} FAILED: {e}")
            try:
                page.close()
            except:
                pass

    browser.close()
    pw.stop()

if __name__ == "__main__":
    cats = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [10, 11, 12, 13, 14, 15, 16, 17, 18]
    for cat in cats:
        take_screenshots(cat)
