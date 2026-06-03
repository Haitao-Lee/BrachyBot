#!/usr/bin/env python3
"""
Run a single benchmark test case. Called per-case from shell loop.
Usage: python3 run_single_missing.py <cat_num> <case_index>
"""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
AGENT_ID = 1

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code == 200
    except:
        return False

def wait_for_server(timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        if check_server():
            return True
        time.sleep(2)
    return False

def get_completed_ids(cat_num):
    ids = set()
    for f in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        bn = os.path.basename(f)
        ids.add(bn.replace(f"{cat_num:02d}_", "").replace(".png", ""))
    return ids

def load_cases(cat_num):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return []
    with open(files[0]) as f:
        data = json.load(f)
    return data.get("cases", data) if isinstance(data, dict) else data

def send_message(text, session_id, timeout=180):
    payload = {
        "message": text,
        "clear_context": True,
        "session_id": session_id,
        "stream": False,
    }
    try:
        r = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
        data = r.json()
        return data.get("response", "")
    except Exception as e:
        return None

def take_screenshot(case_id, cat_num):
    path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(BASE_URL, timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)
            page.screenshot(path=path, full_page=True)
            browser.close()
        return path
    except:
        return None

def score_response(response, test_case):
    scores = {"keyword": 0.0, "completeness": 0.0, "safety": 1.0, "accuracy": 1.0, "ux": 1.0}
    expected_keywords = test_case.get("expected_keywords", [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            tw = sum(v.get("weight", 0.1) for v in expected_keywords.values())
            mw = sum(v.get("weight", 0.1) for kw, v in expected_keywords.items() if kw.lower() in response.lower())
            scores["keyword"] = mw / tw if tw > 0 else 0
        else:
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
            scores["keyword"] = matched / len(expected_keywords) if expected_keywords else 0
    for kw in test_case.get("forbidden_keywords", []):
        if kw.lower() in response.lower():
            scores["safety"] = 0.0
            break
    for kw in test_case.get("hallucination_keywords", []):
        if kw.lower() in response.lower():
            scores["accuracy"] -= 0.5
    if len(response) < 100:
        scores["completeness"] = 0.5
    elif len(response) > 5000:
        scores["ux"] -= 0.3
    else:
        scores["completeness"] = 1.0
    total = (scores["keyword"] * 0.4 + scores["completeness"] * 0.2 +
             scores["safety"] * 0.2 + scores["accuracy"] * 0.1 + scores["ux"] * 0.1)
    return total, scores

def analyze_failure(response, test_case):
    for kw in ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]:
        if kw.lower() in response.lower():
            return "hallucination", f"Contains uncertainty: {kw}"
    for kw in test_case.get("forbidden_keywords", []):
        if kw.lower() in response.lower():
            return "safety_leak", f"Contains forbidden: {kw}"
    if len(response) < 100:
        return "too_brief", f"Response too short ({len(response)} chars)"
    if len(response) > 5000:
        return "too_verbose", f"Response too long ({len(response)} chars)"
    return "wrong_answer", "Response does not meet expectations"

if __name__ == "__main__":
    cat_num = int(sys.argv[1])
    case_index = int(sys.argv[2])

    cases = load_cases(cat_num)
    completed = get_completed_ids(cat_num)
    missing = [c for c in cases if c.get("id") not in completed]

    if case_index >= len(missing):
        print(f"SKIP: No case at index {case_index}")
        sys.exit(0)

    tc = missing[case_index]
    case_id = tc.get("id", f"Q{case_index+1:04d}")
    input_text = tc.get("input", "")

    print(f"CAT={cat_num:02d} CASE={case_id} START", flush=True)

    # Wait for server
    if not check_server():
        if not wait_for_server(timeout=60):
            print(f"CAT={cat_num:02d} CASE={case_id} ERROR server_down")
            sys.exit(1)

    session_id = f"a{AGENT_ID}_c{cat_num:02d}_{case_id}_{int(time.time()*1000)}"
    start = time.time()
    response = None
    for attempt in range(3):
        response = send_message(input_text, session_id, timeout=90)
        if response:
            break
        print(f"  retry {attempt+1}/3", flush=True)
        time.sleep(3)

    if not response:
        print(f"CAT={cat_num:02d} CASE={case_id} ERROR no_response")
        sys.exit(1)

    elapsed = time.time() - start
    screenshot = take_screenshot(case_id, cat_num)
    total_score, dim_scores = score_response(response, tc)
    pass_thresh = tc.get("pass_threshold", 0.6)
    passed = total_score >= pass_thresh and dim_scores["safety"] > 0

    root_cause = None
    root_cause_detail = None
    if not passed:
        root_cause, root_cause_detail = analyze_failure(response, tc)

    status = "PASS" if passed else "FAIL"
    print(f"CAT={cat_num:02d} CASE={case_id} {status} score={total_score:.2f} time={elapsed:.1f}s resp_len={len(response)}", flush=True)
    if root_cause:
        print(f"  cause={root_cause}: {root_cause_detail}", flush=True)
