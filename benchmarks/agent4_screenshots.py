#!/usr/bin/env python3
"""
Take screenshots for all test cases in small batches to avoid OOM.
"""
import os, json, time, glob

SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
RESULTS_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent4_results_28_36.json"
BASE_URL = "http://localhost:8080"
BATCH_SIZE = 3  # Process N screenshots then exit browser

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

with open(RESULTS_FILE) as f:
    all_results = json.load(f)

# Find which screenshots are missing
missing = []
for r in all_results:
    cat_num = r['category_num']
    case_id = r['case_id']
    path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if not os.path.exists(path):
        missing.append((cat_num, case_id, path))

print(f"Total results: {len(all_results)}")
print(f"Missing screenshots: {len(missing)}")

if not missing:
    print("All screenshots exist!")
else:
    # Take screenshots in small batches
    taken = 0
    for cat_num, case_id, path in missing:
        if taken >= BATCH_SIZE:
            print(f"Batch complete ({taken} taken), re-run to continue")
            break
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})
                page.goto(BASE_URL, timeout=15000)
                page.wait_for_load_state('networkidle', timeout=15000)
                time.sleep(1)
                page.screenshot(path=path, full_page=True)
                browser.close()
            taken += 1
            print(f"  [{taken}] {case_id} -> {path}")
        except Exception as e:
            print(f"  FAILED {case_id}: {e}")
            taken += 1  # Count as done to avoid infinite retries

    print(f"\nTook {taken} screenshots. {len(missing) - taken} remaining.")
