#!/usr/bin/env python3
"""
Efficient benchmark runner - reuses playwright browser, processes missing cases.
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

def get_completed_ids(cat_num):
    completed = set()
    for f in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        basename = os.path.basename(f).replace('.png', '')
        case_id = basename.replace(f"{cat_num:02d}_", '')
        completed.add(case_id)
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

def send_message(text, session_id, timeout=180, retries=3):
    for attempt in range(retries):
        try:
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
            print(f"    Timeout on attempt {attempt + 1}/{retries}")
            if attempt < retries - 1:
                time.sleep(3)
        except Exception as e:
            print(f"    Error on attempt {attempt + 1}/{retries}: {type(e).__name__}: {e}")
            if attempt < retries - 1:
                time.sleep(3)
    return ""

def take_screenshot_browser(browser, case_id, cat_num):
    screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
        return screenshot_path
    try:
        page = browser.new_page(viewport={'width': 1920, 'height': 1080})
        page.goto(BASE_URL, timeout=30000)
        page.wait_for_load_state('networkidle', timeout=15000)
        time.sleep(1)
        page.screenshot(path=screenshot_path, full_page=True)
        page.close()
        return screenshot_path
    except Exception as e:
        print(f"    Screenshot failed: {e}")
        try:
            page.close()
        except:
            pass
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

def run_categories(categories, agent_id=1):
    from playwright.sync_api import sync_playwright

    all_results = []
    print(f"="*60)
    print(f"EFFICIENT BENCHMARK RUNNER - Agent {agent_id}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Categories: {categories}")
    print(f"="*60)

    # Check server
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        if r.status_code != 200:
            print("Server not responding properly!")
            return
    except:
        print("Server offline!")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for cat_num in categories:
            cases = load_benchmark(cat_num)
            if not cases:
                print(f"\nCat {cat_num:02d}: No benchmark file found, skipping")
                continue

            completed = get_completed_ids(cat_num)
            remaining = [tc for tc in cases if tc.get('id', '') not in completed]
            print(f"\n{'='*60}")
            print(f"Category {cat_num:02d}: {len(cases)} total | {len(completed)} done | {len(remaining)} remaining")
            print(f"{'='*60}")

            if not remaining:
                print("  All cases already completed!")
                continue

            for i, test_case in enumerate(remaining):
                case_id = test_case.get('id', f'Q{i+1:04d}')
                input_text = test_case.get('input', '')
                print(f"  [{i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

                session_id = f"bench_{agent_id}_{cat_num:02d}_{case_id}_{int(time.time()*1000)}"
                start = time.time()
                response = send_message(input_text, session_id, timeout=180)
                elapsed = time.time() - start

                screenshot = take_screenshot_browser(browser, case_id, cat_num)
                total_score, dim_scores = score_response(response, test_case)
                pass_threshold = test_case.get('pass_threshold', 0.6)
                passed = total_score >= pass_threshold and dim_scores['safety'] > 0

                root_cause = None
                root_cause_detail = None
                if not passed:
                    root_cause, root_cause_detail = analyze_failure(response, test_case)

                result = {
                    'case_id': case_id, 'category_num': cat_num,
                    'input': input_text[:300], 'response': response[:1500],
                    'response_length': len(response),
                    'total_score': total_score, 'dimension_scores': dim_scores,
                    'passed': passed, 'root_cause': root_cause,
                    'root_cause_detail': root_cause_detail,
                    'response_time': elapsed, 'screenshot': screenshot,
                    'timestamp': datetime.now().isoformat()
                }
                all_results.append(result)

                status = "PASS" if passed else "FAIL"
                print(f"{status} ({total_score:.2f}) [{elapsed:.1f}s] len={len(response)}")
                if root_cause:
                    print(f"    -> {root_cause}: {root_cause_detail}")

        browser.close()

    # Summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\n{'='*60}")
    print(f"COMPLETE: {passed}/{total} passed ({passed/total*100:.1f}%)" if total > 0 else "No tests run")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Save results
    results_file = f"{REPORT_DIR}/efficient_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"Results saved: {results_file}")

    # Root cause breakdown
    root_causes = {}
    for r in all_results:
        if r.get('root_cause'):
            rc = r['root_cause']
            root_causes[rc] = root_causes.get(rc, 0) + 1
    if root_causes:
        print("\nFailure Root Causes:")
        for rc, count in sorted(root_causes.items(), key=lambda x: -x[1]):
            print(f"  {rc}: {count}")

    return all_results

if __name__ == "__main__":
    categories = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [2, 3, 5, 6, 7, 8, 9]
    run_categories(categories)
