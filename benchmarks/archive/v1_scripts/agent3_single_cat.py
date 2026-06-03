#!/usr/bin/env python3
"""
Run a single category for Agent 3 benchmark.
Usage: python agent3_single_cat.py <category_num> [--resume]
"""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
RESULTS_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent3_results.json"
AGENT_ID = 3
API_TIMEOUT = 60  # Server responses can take up to 50s for clinical queries

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def load_benchmark(category_file):
    with open(category_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if isinstance(data, dict) and 'cases' in data:
            return data['cases']
        elif isinstance(data, list):
            return data
        return []

def load_existing_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_results(results):
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

def send_message(text, session_id):
    payload = {
        "message": text,
        "clear_context": True,
        "session_id": session_id,
        "stream": False
    }
    try:
        resp = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=API_TIMEOUT)
        data = resp.json()
        return data.get('response', ''), resp.status_code
    except requests.exceptions.Timeout:
        return "Error: Request timed out", 408
    except requests.exceptions.ConnectionError:
        return "Error: Connection refused", 503
    except Exception as e:
        return f"Error: {str(e)}", 500

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
    if response.startswith("Error:"):
        return 'env_error', response

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

def take_screenshot(case_id, cat_num):
    screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(screenshot_path):
        return screenshot_path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=10000)
            page.wait_for_load_state('load', timeout=10000)
            time.sleep(0.5)
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
        return screenshot_path
    except:
        return None

def run_category(cat_num, do_screenshots=False):
    files = glob.glob(f"/home/lht/snap/brachyplan/BrachyBot/benchmarks/{cat_num:02d}_*.json")
    if not files:
        print(f"No benchmark file found for category {cat_num}")
        return []

    cat_file = files[0]
    cat_name = os.path.basename(cat_file).replace('.json', '')
    test_cases = load_benchmark(cat_file)

    existing_results = load_existing_results()
    done_ids = set()
    for r in existing_results:
        if r.get('category_num') == cat_num:
            done_ids.add(r['case_id'])

    remaining = [(i, tc) for i, tc in enumerate(test_cases)
                 if tc.get('id', f'Q{i+1:04d}') not in done_ids]

    print(f"\nCategory {cat_num}: {cat_name} ({len(test_cases)} total, {len(remaining)} remaining)")

    if not remaining:
        print("  All cases already completed.")
        return []

    results = []
    for idx, (i, test_case) in enumerate(remaining):
        case_id = test_case.get('id', f'Q{i+1:04d}')
        input_text = test_case.get('input', '')

        sys.stdout.write(f"  [{idx+1}/{len(remaining)}] {case_id}...")
        sys.stdout.flush()

        session_id = f"agent{AGENT_ID}_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"

        start_time = time.time()
        response, status_code = send_message(input_text, session_id)
        response_time = time.time() - start_time

        # Take screenshot if requested
        screenshot_path = None
        if do_screenshots:
            screenshot_path = take_screenshot(case_id, cat_num)

        total_score, dimension_scores = score_response(response, test_case)
        pass_threshold = test_case.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dimension_scores['safety'] > 0

        root_cause = None
        root_cause_detail = None
        if not passed:
            root_cause, root_cause_detail = analyze_failure(response, test_case)

        result = {
            'case_id': case_id,
            'category': cat_name,
            'category_num': cat_num,
            'input': input_text,
            'response': response[:1500],
            'response_length': len(response),
            'total_score': total_score,
            'dimension_scores': dimension_scores,
            'passed': passed,
            'root_cause': root_cause,
            'root_cause_detail': root_cause_detail,
            'response_time': response_time,
            'screenshot': screenshot_path,
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)

        status_str = "PASS" if passed else "FAIL"
        print(f" {status_str} ({total_score:.2f}) [{response_time:.1f}s]")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")

        # Save after every case
        all_results = existing_results + results
        save_results(all_results)

    return results

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent3_single_cat.py <category_num> [--screenshots]")
        sys.exit(1)

    cat_num = int(sys.argv[1])
    do_screenshots = '--screenshots' in sys.argv
    results = run_category(cat_num, do_screenshots=do_screenshots)
    print(f"\nCompleted: {len(results)} new cases for category {cat_num}")
