#!/usr/bin/env python3
"""
Agent 3 - Remaining categories 19-27 runner
Handles server contention and runs missing cases with unique session IDs.
Takes screenshots for every test case.
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
    print(f"  Waiting for server (timeout: {timeout}s)...", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        if check_server():
            print("  Server is online!", flush=True)
            return True
        time.sleep(5)
    return False

def send_message(text, session_id, timeout=120):
    """Send message with adaptive timeout."""
    for attempt in range(3):
        try:
            if not check_server():
                wait_for_server(timeout=60)
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
            print(f"    Timeout on attempt {attempt + 1}/3, retrying...", flush=True)
            time.sleep(10)
        except Exception as e:
            print(f"    Error on attempt {attempt + 1}/3: {e}", flush=True)
            time.sleep(10)
    return f"Error: All attempts failed"

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

def get_completed(cat_num):
    pattern = f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"
    completed = []
    for f in glob.glob(pattern):
        basename = os.path.basename(f)
        case_id = basename.replace(f"{cat_num:02d}_", "").replace(".png", "")
        completed.append(case_id)
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

def run_category(cat_num, agent_id):
    test_cases = load_benchmark(cat_num)
    if not test_cases:
        print(f"  No benchmark file for category {cat_num}")
        return []

    completed = get_completed(cat_num)
    remaining = [tc for tc in test_cases if tc.get('id', '') not in completed]

    print(f"\n{'='*60}")
    print(f"Category {cat_num}: {len(test_cases)} total, {len(completed)} done, {len(remaining)} remaining")
    print(f"{'='*60}")

    if not remaining:
        print("  All cases already completed!")
        return []

    results = []
    for i, test_case in enumerate(remaining):
        case_id = test_case.get('id', f'Q{i+1:04d}')
        input_text = test_case.get('input', '')

        print(f"  [{i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

        # Adaptive timeout: give more time for harder questions
        timeout = 180 if test_case.get('difficulty') == 'hard' else 120

        session_id = f"agent{agent_id}_cat{cat_num:02d}_{case_id}_{int(time.time()*1000)}"

        start_time = time.time()
        response = send_message(input_text, session_id, timeout=timeout)
        response_time = time.time() - start_time

        # Check for server contention (very long response time)
        if response_time > 150:
            print(f"\n    [Slow response: {response_time:.0f}s - possible contention]", end=" ", flush=True)

        screenshot_path = take_screenshot(case_id, cat_num)
        total_score, dimension_scores = score_response(response, test_case)
        pass_threshold = test_case.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dimension_scores['safety'] > 0

        root_cause = None
        root_cause_detail = None
        if not passed:
            root_cause, root_cause_detail = analyze_failure(response, test_case)

        result = {
            'case_id': case_id, 'category_num': cat_num,
            'input': input_text, 'response': response[:1500], 'response_length': len(response),
            'total_score': total_score, 'dimension_scores': dimension_scores, 'passed': passed,
            'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
            'response_time': response_time, 'screenshot': screenshot_path,
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{response_time:.1f}s]")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")

    return results

def generate_report(all_results, agent_id):
    report_file = f"{REPORT_DIR}/agent{agent_id}_report.md"
    total_tests = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    failed = total_tests - passed
    pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0

    categories = {}
    for r in all_results:
        cat = r['category_num']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    avg_response_time = sum(r['response_time'] for r in all_results) / total_tests if total_tests > 0 else 0
    avg_score = sum(r['total_score'] for r in all_results) / total_tests if total_tests > 0 else 0

    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"# Agent {agent_id} Benchmark Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Categories:** 19-27\n\n")
        f.write("## Executive Summary\n\n")
        f.write(f"| Metric | Value |\n")
        f.write(f"|--------|-------|\n")
        f.write(f"| Total Tests | {total_tests} |\n")
        f.write(f"| Passed | {passed} |\n")
        f.write(f"| Failed | {failed} |\n")
        f.write(f"| Pass Rate | {pass_rate:.1f}% |\n")
        f.write(f"| Avg Score | {avg_score:.3f} |\n")
        f.write(f"| Avg Response Time | {avg_response_time:.1f}s |\n\n")

        f.write("### Category Breakdown\n\n")
        f.write("| Category | Cases | Passed | Failed | Pass Rate | Avg Score |\n")
        f.write("|----------|-------|--------|--------|-----------|----------|\n")
        for cat_num in sorted(categories.keys()):
            cat_results = categories[cat_num]
            cat_passed = sum(1 for r in cat_results if r['passed'])
            cat_failed = len(cat_results) - cat_passed
            cat_rate = (cat_passed / len(cat_results) * 100) if cat_results else 0
            cat_avg = sum(r['total_score'] for r in cat_results) / len(cat_results) if cat_results else 0
            f.write(f"| {cat_num:02d} | {len(cat_results)} | {cat_passed} | {cat_failed} | {cat_rate:.0f}% | {cat_avg:.3f} |\n")
        f.write("\n")

        f.write("## Detailed Results\n\n")
        for cat_num in sorted(categories.keys()):
            cat_results = categories[cat_num]
            cat_passed = sum(1 for r in cat_results if r['passed'])
            cat_total = len(cat_results)
            cat_rate = (cat_passed / cat_total * 100) if cat_total > 0 else 0
            f.write(f"### Category {cat_num:02d} ({cat_passed}/{cat_total} passed, {cat_rate:.0f}%)\n\n")
            for r in cat_results:
                status = "PASS" if r['passed'] else "FAIL"
                f.write(f"#### [{status}] {r['case_id']}\n\n")
                f.write(f"**Input:** {r['input'][:200]}...\n\n")
                f.write(f"**Response Length:** {r['response_length']} chars | **Score:** {r['total_score']:.2f} | **Time:** {r['response_time']:.1f}s\n\n")
                if r['root_cause']:
                    f.write(f"**Root Cause:** {r['root_cause']} - {r['root_cause_detail']}\n\n")
                if r['screenshot'] and os.path.exists(r['screenshot']):
                    rel_path = os.path.relpath(r['screenshot'], REPORT_DIR)
                    f.write(f"![{r['case_id']}]({rel_path})\n\n")
                f.write("---\n\n")

    print(f"\nReport: {report_file}")
    return report_file

if __name__ == "__main__":
    agent_id = 3
    categories = [19, 20, 21, 22, 23, 24, 25, 26, 27]

    print("=" * 60)
    print(f"Agent {agent_id} - Categories 19-27 Runner")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if not check_server():
        print("Server is offline!")
        if not wait_for_server():
            sys.exit(1)

    all_results = []
    for cat_num in categories:
        results = run_category(cat_num, agent_id)
        all_results.extend(results)
        cat_passed = sum(1 for r in results if r['passed'])
        print(f"  Category {cat_num}: {cat_passed}/{len(results)} passed")

    if all_results:
        report_file = generate_report(all_results, agent_id)
        total = len(all_results)
        passed = sum(1 for r in all_results if r['passed'])
        print(f"\n{'='*60}")
        print(f"COMPLETE: {passed}/{total} passed ({passed/total*100:.1f}%)")
        print(f"Report: {report_file}")
        print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("\nNo new tests needed - all cases already completed!")
