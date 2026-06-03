#!/usr/bin/env python3
"""
Category 23 runner v2 - handles concurrent server usage, retries, longer timeouts.
"""
import json, os, sys, time, requests, glob
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
AGENT_ID = 4
CAT_NUM = 23
MAX_RETRIES = 3
API_TIMEOUT = 180  # 3 minutes per request

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

def send_message(text, session_id, timeout=API_TIMEOUT):
    payload = {
        "message": text,
        "clear_context": True,
        "session_id": session_id,
        "stream": False
    }
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            data = response.json()
            return data.get('response', '')
        except requests.exceptions.ReadTimeout:
            if attempt < MAX_RETRIES - 1:
                print(f"    [Retry {attempt+2}/{MAX_RETRIES}] timeout, waiting 5s...", end=" ", flush=True)
                time.sleep(5)
            else:
                return f"Error: Read timed out after {timeout}s"
        except requests.exceptions.ConnectionError:
            if attempt < MAX_RETRIES - 1:
                print(f"    [Retry {attempt+2}/{MAX_RETRIES}] connection error, waiting 10s...", end=" ", flush=True)
                time.sleep(10)
            else:
                return f"Error: Connection refused"
        except Exception as e:
            return f"Error: {str(e)}"

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

def run_category(cat_num):
    files = glob.glob(f"/home/lht/snap/brachyplan/BrachyBot/benchmarks/{cat_num:02d}_*.json")
    if not files:
        print(f"No benchmark file found for category {cat_num}")
        return []

    cat_file = files[0]
    cat_name = os.path.basename(cat_file).replace('.json', '')
    test_cases = load_benchmark(cat_file)

    print(f"\n{'='*60}")
    print(f"Category {cat_num}: {cat_name} ({len(test_cases)} cases)")
    print(f"{'='*60}")

    results = []

    # Launch browser ONCE for all screenshots
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})

    for i, test_case in enumerate(test_cases):
        case_id = test_case.get('id', f'Q{i+1:04d}')
        input_text = test_case.get('input', '')

        print(f"  [{i+1}/{len(test_cases)}] {case_id}...", end=" ", flush=True)

        session_id = f"agent{AGENT_ID}_{CAT_NUM:02d}_{case_id}_{int(time.time() * 1000)}"

        # Send message with retries
        start_time = time.time()
        response = send_message(input_text, session_id)
        response_time = time.time() - start_time

        # Take screenshot (reuse browser - much faster)
        screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
        try:
            page.goto(BASE_URL, timeout=15000)
            page.wait_for_load_state('networkidle', timeout=10000)
            time.sleep(0.5)
            page.screenshot(path=screenshot_path, full_page=True)
        except Exception as e:
            screenshot_path = None

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
            'category_num': CAT_NUM,
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

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{response_time:.1f}s] [{len(response)} chars]")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")

        # Save intermediate results every 10 cases
        if (i + 1) % 10 == 0:
            save_intermediate(results, cat_name)

    browser.close()
    pw.stop()
    return results

def save_intermediate(results, cat_name):
    """Save intermediate results in case of crash."""
    intermediate_file = f"{REPORT_DIR}/agent{AGENT_ID}_category23_intermediate.json"
    with open(intermediate_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    passed = sum(1 for r in results if r['passed'])
    print(f"    [Checkpoint saved: {len(results)} cases, {passed} passed]")

def generate_report(results):
    report_file = f"{REPORT_DIR}/agent{AGENT_ID}_category23_report.md"

    total_tests = len(results)
    passed = sum(1 for r in results if r['passed'])
    failed = total_tests - passed
    pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0

    # Count error responses (server failures)
    error_responses = sum(1 for r in results if r['response'].startswith('Error:'))

    root_causes = {}
    for r in results:
        if r['root_cause']:
            rc = r['root_cause']
            root_causes[rc] = root_causes.get(rc, 0) + 1

    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"# Agent {AGENT_ID} - Category 23 (medium_complexity) Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Agent:** {AGENT_ID} (Helping Agent 3)\n")
        f.write(f"**Category:** 23_medium_complexity\n\n")

        f.write("## Executive Summary\n\n")
        f.write(f"| Metric | Value |\n")
        f.write(f"|--------|-------|\n")
        f.write(f"| Total Tests | {total_tests} |\n")
        f.write(f"| Passed | {passed} |\n")
        f.write(f"| Failed | {failed} |\n")
        f.write(f"| Pass Rate | {pass_rate:.1f}% |\n")
        if error_responses > 0:
            f.write(f"| Server Errors | {error_responses} |\n")
        f.write("\n")

        if error_responses > 0:
            f.write(f"**WARNING:** {error_responses} responses were server errors (timeouts/connection refused). ")
            f.write(f"These indicate the server was overloaded, not actual AI response quality issues.\n\n")

        if root_causes:
            f.write("### Root Cause Breakdown\n\n")
            f.write("| Root Cause | Count | Severity | Description |\n")
            f.write("|------------|-------|----------|-------------|\n")
            severity_map = {
                'hallucination': ('P0', 'Contains uncertainty/fabrication'),
                'safety_leak': ('P0', 'Forbidden keywords in response'),
                'keyword_missing': ('P2', 'Missing expected keywords'),
                'wrong_answer': ('P2', 'Does not meet expectations'),
                'too_brief': ('P2', 'Response too short (<100 chars)'),
                'too_verbose': ('P2', 'Response too long (>5000 chars)')
            }
            for rc, count in sorted(root_causes.items(), key=lambda x: -x[1]):
                sev, desc = severity_map.get(rc, ('P2', rc))
                f.write(f"| {rc} | {count} | {sev} | {desc} |\n")
            f.write("\n")

        f.write("## Detailed Results\n\n")
        for r in results:
            is_error = r['response'].startswith('Error:')
            status = "PASS" if r['passed'] else "FAIL"
            f.write(f"#### [{status}] {r['case_id']}\n\n")
            f.write(f"**Input:** {r['input']}\n\n")
            if is_error:
                f.write(f"**Response (SERVER ERROR):**\n> {r['response'][:500]}\n\n")
                f.write(f"**Note:** Server was unable to process this request.\n\n")
            else:
                f.write(f"**Response:**\n> {r['response'][:500]}{'...' if len(r['response']) > 500 else ''}\n\n")
            f.write(f"**Scores:**\n")
            f.write(f"- Total: {r['total_score']:.2f}\n")
            f.write(f"- Keyword: {r['dimension_scores']['keyword']:.2f}\n")
            f.write(f"- Completeness: {r['dimension_scores']['completeness']:.2f}\n")
            f.write(f"- Safety: {r['dimension_scores']['safety']:.2f}\n")
            f.write(f"- Accuracy: {r['dimension_scores']['accuracy']:.2f}\n")
            f.write(f"- UX: {r['dimension_scores']['ux']:.2f}\n")
            f.write(f"- Response Time: {r['response_time']:.1f}s\n\n")

            if r['root_cause']:
                f.write(f"**Root Cause:** {r['root_cause']}\n\n")
                f.write(f"**Detail:** {r['root_cause_detail']}\n\n")

            if r['screenshot'] and os.path.exists(r['screenshot']):
                rel_path = os.path.relpath(r['screenshot'], REPORT_DIR)
                f.write(f"**Screenshot:**\n![{r['case_id']}]({rel_path})\n\n")

            f.write("---\n\n")

    print(f"\nReport generated: {report_file}")
    return report_file

if __name__ == "__main__":
    print(f"Agent {AGENT_ID} - Category 23 Runner v2")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"API Timeout: {API_TIMEOUT}s, Max Retries: {MAX_RETRIES}")

    results = run_category(CAT_NUM)
    report_file = generate_report(results)

    # Save final results as JSON
    results_file = f"{REPORT_DIR}/agent{AGENT_ID}_category23_results.json"
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"Category 23 Complete!")
    print(f"Total: {len(results)} tests, {sum(1 for r in results if r['passed'])} passed")
    errors = sum(1 for r in results if r['response'].startswith('Error:'))
    if errors:
        print(f"Server Errors: {errors}")
    print(f"Report: {report_file}")
    print(f"Results: {results_file}")
    print(f"{'='*60}")
