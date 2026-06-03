#!/usr/bin/env python3
"""
Agent 2: API-only runner for remaining cases.
NO screenshots during API calls - screenshots taken separately afterward.
This prevents OOM from combining Playwright + requests.
"""
import json, os, sys, time, glob, subprocess, requests
from datetime import datetime

SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
BASE_URL = "http://localhost:8080"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

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
        print(".", end="", flush=True)
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
    return data if isinstance(data, list) else []

def send_message(text, session_id, timeout=180):
    """Send via subprocess curl for reliability."""
    payload = json.dumps({
        "message": text,
        "clear_context": True,
        "session_id": session_id,
        "stream": False
    })
    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', str(timeout), '-X', 'POST',
             f'{BASE_URL}/api/chat',
             '-H', 'Content-Type: application/json',
             '-d', payload],
            capture_output=True, text=True, timeout=timeout + 30
        )
        if result.returncode != 0:
            # Fallback to requests
            r = requests.post(f"{BASE_URL}/api/chat", json={
                "message": text, "clear_context": True,
                "session_id": session_id, "stream": False
            }, timeout=timeout)
            data = r.json()
            return data.get('response', '')
        data = json.loads(result.stdout)
        return data.get('response', '')
    except Exception as e:
        return f"Error: {e}"

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
    for kw in ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]:
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
        matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
        if matched == 0:
            return 'keyword_missing', 'No expected keywords found'
    return 'wrong_answer', 'Response does not meet expectations'

def take_screenshots_separately(missing_ids, cat_num):
    """Take screenshots for all missing cases at once, separately from API calls."""
    print(f"\n  Taking screenshots for {len(missing_ids)} cases in category {cat_num}...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for case_id in missing_ids:
                screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
                if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                    continue
                try:
                    page = browser.new_page(viewport={'width': 1920, 'height': 1080})
                    page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
                    time.sleep(2)
                    page.screenshot(path=screenshot_path, full_page=True)
                    page.close()
                    print(f"    Screenshot: {case_id} OK")
                except Exception as e:
                    print(f"    Screenshot: {case_id} FAILED: {e}")
                time.sleep(1)
            browser.close()
    except Exception as e:
        print(f"  Screenshot batch failed: {e}")

if __name__ == "__main__":
    categories = [15, 18]
    agent_id = 2
    all_results = []
    total_start = time.time()

    for cat_num in categories:
        cases = load_benchmark(cat_num)
        completed = get_completed_ids(cat_num)
        missing = [tc for tc in cases if tc.get('id', '') not in completed]
        missing_ids = [tc.get('id', '') for tc in missing]

        print(f"\n{'='*60}")
        print(f"Category {cat_num}: {len(cases)} total, {len(completed)} done, {len(missing)} remaining")
        print(f"{'='*60}")

        if not missing:
            print("  All done!")
            continue

        for i, tc in enumerate(missing):
            case_id = tc.get('id', f'Q{i+1:04d}')
            input_text = tc.get('input', '')
            print(f"  [{i+1}/{len(missing)}] {case_id}...", end=" ", flush=True)

            if not check_server():
                print("Server offline, waiting...", flush=True)
                if not wait_for_server(timeout=120):
                    print("SKIPPED")
                    continue

            session_id = f"agent{agent_id}_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
            start = time.time()
            response = send_message(input_text, session_id)
            elapsed = time.time() - start

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
                'response_time': elapsed, 'screenshot': None,
                'timestamp': datetime.now().isoformat()
            }
            all_results.append(result)

            status = "PASS" if passed else "FAIL"
            print(f"{status} ({total_score:.2f}) [{elapsed:.1f}s]")
            if root_cause:
                print(f"    -> {root_cause}: {root_cause_detail}")

            time.sleep(2)

        cat_results = [r for r in all_results if r['category_num'] == cat_num]
        cat_passed = sum(1 for r in cat_results if r['passed'])
        print(f"\nCategory {cat_num} API tests complete: {cat_passed}/{len(cat_results)} passed")

        # Take screenshots separately after all API calls for this category
        new_case_ids = [r['case_id'] for r in cat_results]
        take_screenshots_separately(new_case_ids, cat_num)

    # Final summary
    total_elapsed = time.time() - total_start
    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\n{'='*60}")
    print(f"AGENT 2 BENCHMARK RUN COMPLETE")
    print(f"New tests run: {total} | Passed: {passed} | Failed: {total - passed}")
    if total > 0:
        print(f"Pass Rate: {passed/total*100:.1f}%")
    print(f"Total time: {total_elapsed:.0f}s ({total_elapsed/60:.1f}min)")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results_file = f"/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent2_cat15_18_results.json"
    with open(results_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"Results saved: {results_file}")
