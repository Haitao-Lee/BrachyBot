#!/usr/bin/env python3
"""Lightweight runner for remaining category 2, 7, 9 cases one at a time."""
import json, os, sys, time, glob, requests
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "docs/benchmark_result/screenshots"
BENCHMARK_DIR = "benchmarks"

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code == 200
    except:
        return False

def send_message(text, session_id, timeout=180):
    for attempt in range(3):
        try:
            if not check_server():
                print("    Server offline, waiting 60s...")
                time.sleep(60)
                if not check_server():
                    continue
            payload = {"message": text, "clear_context": True, "session_id": session_id, "stream": False}
            r = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            return r.json().get('response', '')
        except Exception as e:
            print(f"    Attempt {attempt+1}/3 failed: {e}")
            time.sleep(5)
    return "Error: All attempts failed"

def take_screenshot(case_id, cat_num):
    path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
            time.sleep(3)
            page.screenshot(path=path, full_page=True)
            browser.close()
        return path
    except Exception as e:
        print(f"    Screenshot failed: {e}")
        return None

def score_response(response, test_case):
    scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
    expected_keywords = test_case.get('expected_keywords', [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            total_weight = sum(v.get('weight', 0.1) for v in expected_keywords.values())
            matched_weight = sum(v.get('weight', 0.1) for kw, v in expected_keywords.items() if kw.lower() in response.lower())
            scores['keyword'] = matched_weight / total_weight if total_weight > 0 else 0
        else:
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
            scores['keyword'] = matched / len(expected_keywords) if expected_keywords else 0
    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            scores['safety'] = 0.0
            break
    if len(response) < 100:
        scores['completeness'] = 0.5
    elif len(response) > 5000:
        scores['ux'] -= 0.3
    else:
        scores['completeness'] = 1.0
    total = (scores['keyword'] * 0.4 + scores['completeness'] * 0.2 +
             scores['safety'] * 0.2 + scores['accuracy'] * 0.1 + scores['ux'] * 0.1)
    return total, scores

def analyze_failure(response, test_case):
    for kw in ["I don't know", "I'm not sure", "I cannot verify"]:
        if kw.lower() in response.lower():
            return 'hallucination', f'Contains: "{kw}"'
    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            return 'safety_leak', f'Forbidden keyword: "{kw}"'
    if len(response) < 100:
        return 'too_brief', f'{len(response)} chars'
    if len(response) > 5000:
        return 'too_verbose', f'{len(response)} chars'
    return 'wrong_answer', 'Does not meet expectations'

if __name__ == "__main__":
    cats = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [2, 7, 9]

    for cat_num in cats:
        files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
        if not files:
            continue
        with open(files[0]) as f:
            data = json.load(f)
        cases = data.get('cases', data) if isinstance(data, dict) else data

        done_files = glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png")
        done_ids = {os.path.basename(f).replace(f"{cat_num:02d}_", "").replace(".png", "") for f in done_files}
        remaining = [c for c in cases if c.get('id', '') not in done_ids]

        print(f"\nCategory {cat_num}: {len(cases)} total, {len(done_ids)} done, {len(remaining)} remaining")

        for i, tc in enumerate(remaining):
            case_id = tc.get('id', f'Q{i+1:04d}')
            print(f"  [{i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

            session_id = f"agent1_{cat_num:02d}_{case_id}_{int(time.time()*1000)}"
            start = time.time()
            resp = send_message(tc.get('input', ''), session_id, timeout=180)
            elapsed = time.time() - start

            take_screenshot(case_id, cat_num)
            total_score, dim_scores = score_response(resp, tc)
            pass_th = tc.get('pass_threshold', 0.6)
            passed = total_score >= pass_th and dim_scores['safety'] > 0

            rc = None
            rcd = None
            if not passed:
                rc, rcd = analyze_failure(resp, tc)

            status = "PASS" if passed else "FAIL"
            print(f"{status} ({total_score:.2f}) [{elapsed:.1f}s]")
            if rc:
                print(f"    -> {rc}: {rcd}")

            # Flush after each case to free memory
            sys.stdout.flush()
