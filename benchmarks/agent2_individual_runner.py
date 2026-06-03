#!/usr/bin/env python3
"""
Agent 2 Individual Test Runner - handles server crashes gracefully
Runs remaining missing cases for categories 10-18, one at a time.
"""
import json, os, sys, time, glob, requests
from datetime import datetime
from pathlib import Path

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

def wait_for_server(timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        if check_server():
            return True
        time.sleep(5)
    return False

def get_completed_ids(cat_num):
    completed = set()
    for f in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        bn = os.path.basename(f).replace(f"{cat_num:02d}_", "").replace(".png", "")
        completed.add(bn)
    return completed

def load_benchmark(cat_num):
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

def send_message(text, session_id, timeout=180):
    """Send with aggressive retry and server-recovery logic."""
    for attempt in range(3):
        try:
            if not check_server():
                print("      Server offline, waiting...", flush=True)
                if not wait_for_server(timeout=120):
                    return "Error: Server did not come back online"
            payload = {
                "message": text,
                "clear_context": True,
                "session_id": session_id,
                "stream": False
            }
            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            data = response.json()
            return data.get('response', '')
        except requests.exceptions.Timeout:
            print(f"      Timeout attempt {attempt+1}/3", flush=True)
            time.sleep(10)
        except Exception as e:
            print(f"      Error attempt {attempt+1}/3: {type(e).__name__}", flush=True)
            # Wait longer for server recovery
            if not wait_for_server(timeout=120):
                return f"Error: Server did not recover"
    return "Error: All retries failed"

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
            time.sleep(3)
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
        return screenshot_path
    except Exception as e:
        print(f"      Screenshot failed: {e}")
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

def analyze_failure(response, test_case):
    hallucination_phrases = ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]
    for kw in hallucination_phrases:
        if kw.lower() in response.lower():
            return 'hallucination', f'Contains uncertainty phrase: "{kw}"'
    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            return 'safety_leak', f'Contains forbidden keyword: "{kw}"'
    if len(response) < 100:
        return 'too_brief', f'Response too short ({len(response)} chars)'
    if len(response) > 5000:
        return 'too_verbose', f'Response too long ({len(response)} chars)'
    expected_keywords = test_case.get('expected_keywords', [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
        else:
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
        if matched == 0:
            return 'keyword_missing', 'No expected keywords found'
    return 'wrong_answer', 'Response does not meet expectations'

if __name__ == "__main__":
    categories = [15, 18]
    agent_id = 2
    all_results = []

    for cat_num in categories:
        cases = load_benchmark(cat_num)
        completed = get_completed_ids(cat_num)
        missing = [tc for tc in cases if tc.get('id', '') not in completed]

        print(f"\nCategory {cat_num}: {len(cases)} total, {len(completed)} done, {len(missing)} missing")
        if not missing:
            continue

        for i, tc in enumerate(missing):
            case_id = tc.get('id', f'Q{i+1:04d}')
            input_text = tc.get('input', '')
            print(f"  [{i+1}/{len(missing)}] {case_id}...", end=" ", flush=True)

            # Check server before each test
            if not check_server():
                print("Server offline, waiting...", flush=True)
                if not wait_for_server(timeout=180):
                    print("SKIPPED (server unavailable)")
                    continue

            session_id = f"agent{agent_id}_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
            start = time.time()
            response = send_message(input_text, session_id)
            elapsed = time.time() - start

            screenshot_path = take_screenshot(case_id, cat_num)
            total_score, dim_scores = score_response(response, tc)
            pass_threshold = tc.get('pass_threshold', 0.6)
            passed = total_score >= pass_threshold and dim_scores['safety'] > 0

            root_cause = None
            root_cause_detail = None
            if not passed:
                root_cause, root_cause_detail = analyze_failure(response, tc)

            result = {
                'case_id': case_id, 'category_num': cat_num,
                'input': input_text, 'response': response[:1500],
                'response_length': len(response), 'total_score': total_score,
                'dimension_scores': dim_scores, 'passed': passed,
                'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
                'response_time': elapsed, 'screenshot': screenshot_path,
                'timestamp': datetime.now().isoformat()
            }
            all_results.append(result)
            status = "PASS" if passed else "FAIL"
            print(f"{status} ({total_score:.2f}) [{elapsed:.1f}s]")
            if root_cause:
                print(f"    -> {root_cause}: {root_cause_detail}")

            # Small delay between requests to avoid overwhelming the server
            time.sleep(2)

        print(f"\nCategory {cat_num} complete: {sum(1 for r in all_results if r['category_num']==cat_num and r['passed'])}/{len(missing)} passed")

    # Summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\n{'='*60}")
    print(f"AGENT 2 COMPLETE - Categories 10-18")
    print(f"New tests run: {total} | Passed: {passed} | Failed: {total - passed}")
    print(f"Pass Rate: {passed/total*100:.1f}%" if total > 0 else "No tests")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
