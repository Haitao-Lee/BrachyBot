#!/usr/bin/env python3
"""
Run a single benchmark test case.
Usage: python3 agent4_single_test.py <cat_num> <case_id>
"""
import json, os, sys, time, glob, requests

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
AGENT_ID = 4
API_TIMEOUT = 300

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code == 200
    except:
        return False

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 agent4_single_test.py <cat_num> <case_id>")
        sys.exit(1)

    cat_num = int(sys.argv[1])
    target_id = sys.argv[2]

    # Load benchmark
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        print(f"ERROR: No benchmark file for category {cat_num}")
        sys.exit(1)

    with open(files[0]) as f:
        data = json.load(f)
    cases = data.get('cases', data) if isinstance(data, dict) else data

    # Find the target case
    tc = None
    for c in cases:
        if c.get('id') == target_id:
            tc = c
            break

    if tc is None:
        print(f"ERROR: Case {target_id} not found in category {cat_num}")
        sys.exit(1)

    input_text = tc.get('input', '')

    # Check if already done
    screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{target_id}.png"
    if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
        print(f"DONE: {target_id} already has screenshot")
        sys.exit(0)

    # Check server
    if not check_server():
        print(f"OFFLINE: Server not responding")
        sys.exit(2)

    # Send message
    session_id = f"agent{AGENT_ID}_{cat_num:02d}_{target_id}_{int(time.time()*1000)}"
    t0 = time.time()
    response = ""
    try:
        r = requests.post(f"{BASE_URL}/api/chat", json={
            "message": input_text,
            "clear_context": True,
            "session_id": session_id,
            "stream": False
        }, timeout=API_TIMEOUT)
        data = r.json()
        response = data.get("response", "")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {str(e)[:200]}")
        sys.exit(3)

    response_time = time.time() - t0

    # Take screenshot (with retry)
    for ss_attempt in range(2):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})
                page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
                time.sleep(2)
                page.screenshot(path=screenshot_path, full_page=True)
                browser.close()
            break
        except Exception as e:
            print(f"WARNING: Screenshot attempt {ss_attempt+1} failed: {type(e).__name__}", file=sys.stderr)
            time.sleep(3)

    # Score
    expected = tc.get('expected_keywords', [])
    if expected and isinstance(expected, list):
        matched = sum(1 for kw in expected if kw.lower() in response.lower())
        keyword_score = matched / len(expected)
    elif expected and isinstance(expected, dict):
        total_w = sum(v.get('weight', 0.1) for v in expected.values())
        matched_w = sum(v.get('weight', 0.1) for kw, v in expected.items() if kw.lower() in response.lower())
        keyword_score = matched_w / total_w if total_w > 0 else 0
    else:
        keyword_score = 0

    passed = keyword_score >= 0.3 and len(response) > 100
    status = "PASS" if passed else "FAIL"
    print(f"{status}: {target_id} score={keyword_score:.2f} time={response_time:.1f}s len={len(response)}")

if __name__ == "__main__":
    main()
