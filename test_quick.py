#!/usr/bin/env python3
"""Quick test: upload CT, send planning request, check logs."""
import time, json
from playwright.sync_api import sync_playwright

CT_PATH = "/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii"
BASE = "http://127.0.0.1:5000"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    logs = []
    page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

    page.goto(BASE, wait_until="load", timeout=30000)
    time.sleep(2)

    # Upload CT
    file_input = page.query_selector('input[type="file"]')
    file_input.set_input_files(CT_PATH)
    time.sleep(8)
    print(f"CT loaded: {page.evaluate('state?.ctLoaded')}")

    # Send planning request
    chat_input = page.query_selector('#chatInput')
    chat_input.fill("Perform brachytherapy planning for a pancreatic tumor patient")
    chat_input.press("Enter")
    print("Planning request sent, waiting 120s...")

    # Wait and periodically check state
    for i in range(24):
        time.sleep(5)
        state = page.evaluate("""() => {
            const r = {};
            try {
                const xhr = new XMLHttpRequest();
                xhr.open('GET', '/api/planning/results', false);
                xhr.send();
                const data = JSON.parse(xhr.responseText);
                r.has_dose = data.has_dose;
                r.total_seeds = data.total_seeds;
                r.dvh_keys = data.dvh ? Object.keys(data.dvh).length : 0;
            } catch(e) { r.error = e.message; }
            return r;
        }""")
        print(f"  {(i+1)*5}s: {json.dumps(state)}")
        if state.get('has_dose') or state.get('total_seeds', 0) > 0:
            print("Planning data available!")
            break

    # Check logs
    print("\nRelevant logs:")
    for log in logs:
        if any(k in log.lower() for k in ['store-check', 'exec', 'verify', 'tool-loop', 'error', 'fail', 'dedup', 'hard-block']):
            print(f"  {log}")

    browser.close()
