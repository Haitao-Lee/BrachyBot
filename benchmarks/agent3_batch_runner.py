#!/usr/bin/env python3
"""
Agent 3 Batch Runner - Simple, robust runner for categories 19-27
Focuses on completing all remaining cases one at a time
"""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code == 200
    except:
        return False

def wait_for_server(timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        if check_server():
            return True
        time.sleep(3)
    return False

def load_cases(cat_num):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return []
    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
        if isinstance(data, dict) and 'cases' in data:
            return data['cases']
        elif isinstance(data, list):
            return data
        return []

def get_done(cat_num):
    done = set()
    for f in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        bn = os.path.basename(f)
        cid = bn.replace(f"{cat_num:02d}_", "").replace(".png", "")
        done.add(cid)
    return done

def send_msg(text, session_id, timeout=180):
    for attempt in range(3):
        try:
            if not check_server():
                if not wait_for_server(timeout=60):
                    continue
            payload = {"message": text, "clear_context": True, "session_id": session_id, "stream": False}
            r = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            data = r.json()
            return data.get('response', '')
        except requests.exceptions.Timeout:
            print(f"    Timeout attempt {attempt+1}/3", flush=True)
            time.sleep(3)
        except Exception as e:
            print(f"    Error attempt {attempt+1}/3: {e}", flush=True)
            time.sleep(3)
    return ""

def take_screenshot(case_id, cat_num):
    screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
        return screenshot_path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
            time.sleep(2)
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
        return screenshot_path
    except Exception as e:
        print(f"    Screenshot error: {e}", flush=True)
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
    for kw in test_case.get('hallucination_keywords', []):
        if kw.lower() in response.lower():
            scores['accuracy'] -= 0.5
    if len(response) < 100:
        scores['completeness'] = 0.5
    elif len(response) > 5000:
        scores['ux'] -= 0.3
    else:
        scores['completeness'] = 1.0
    total = (scores['keyword'] * 0.4 + scores['completeness'] * 0.2 +
             scores['safety'] * 0.2 + scores['accuracy'] * 0.1 + scores['ux'] * 0.1)
    return total, scores

def run_category(cat_num, agent_id=3):
    cases = load_cases(cat_num)
    if not cases:
        print(f"No cases for cat {cat_num}")
        return

    done = get_done(cat_num)
    remaining = [c for c in cases if c.get('id', '') not in done]

    print(f"\nCat {cat_num}: {len(cases)} total, {len(done)} done, {len(remaining)} remaining")

    if not remaining:
        print(f"  Cat {cat_num} COMPLETE!")
        return

    for i, tc in enumerate(remaining):
        case_id = tc.get('id', f'Q{i+1:04d}')
        input_text = tc.get('input', '')

        print(f"  [{i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

        session_id = f"a3_c{cat_num:02d}_{case_id}_{int(time.time()*1000)}"

        start = time.time()
        response = send_msg(input_text, session_id)
        elapsed = time.time() - start

        if not response:
            print(f"NO RESPONSE [{elapsed:.1f}s]")
            continue

        take_screenshot(case_id, cat_num)

        total_score, dim_scores = score_response(response, tc)
        pass_threshold = tc.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dim_scores['safety'] > 0

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{elapsed:.1f}s] {len(response)} chars")

    print(f"\nCat {cat_num} done!")

if __name__ == "__main__":
    categories = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [19, 20, 21, 22, 23, 24, 25, 26, 27]

    print(f"Agent 3 Batch Runner - Categories: {categories}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    for cat in categories:
        run_category(cat)

    print(f"\nAll done: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
