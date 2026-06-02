#!/usr/bin/env python3
"""
Agent 2 Benchmark Runner - Lightweight version (no screenshots during test runs)
Screenshots will be taken separately after all tests complete.
"""
import json, os, sys, time, glob, requests
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
RESULTS_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

def load_benchmark(category_file):
    with open(category_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if isinstance(data, dict) and 'cases' in data:
            return data['cases']
        elif isinstance(data, list):
            return data
        return []

def send_message(text, session_id, timeout=120):
    payload = {
        "message": text,
        "clear_context": True,
        "session_id": session_id,
        "stream": False
    }
    try:
        response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
        data = response.json()
        return data.get('response', '')
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

def run_category(cat_num, agent_id):
    """Run ALL test cases for a category - no screenshots.
    Uses a SINGLE session_id per category to avoid OOM from repeated agent initialization."""
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        print(f"No benchmark file found for category {cat_num}")
        return []
    cat_file = files[0]
    cat_name = os.path.basename(cat_file).replace('.json', '')
    test_cases = load_benchmark(cat_file)
    print(f"\n{'='*60}")
    print(f"Category {cat_num}: {cat_name} ({len(test_cases)} cases)")
    print(f"{'='*60}")
    # Use ONE session_id per category to avoid re-initializing BrachyAgent each time
    session_id = f"agent{agent_id}_cat{cat_num:02d}_{int(time.time() * 1000)}"
    results = []
    for i, test_case in enumerate(test_cases):
        case_id = test_case.get('id', f'Q{i+1:04d}')
        input_text = test_case.get('input', '')
        print(f"  [{i+1}/{len(test_cases)}] {case_id}...", end=" ", flush=True)
        start_time = time.time()
        response = send_message(input_text, session_id, timeout=90)
        response_time = time.time() - start_time
        total_score, dimension_scores = score_response(response, test_case)
        pass_threshold = test_case.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dimension_scores['safety'] > 0
        root_cause = None
        root_cause_detail = None
        if not passed:
            root_cause, root_cause_detail = analyze_failure(response, test_case)
        result = {
            'case_id': case_id, 'category': cat_name, 'category_num': cat_num,
            'input': input_text, 'response': response[:1500], 'response_length': len(response),
            'total_score': total_score, 'dimension_scores': dimension_scores, 'passed': passed,
            'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
            'response_time': response_time, 'screenshot': None,
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)
        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{response_time:.1f}s]")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")
    return results

def take_screenshots_for_category(cat_num, test_cases):
    """Take screenshots for all cases in a category using a single browser."""
    from playwright.sync_api import sync_playwright
    print(f"\n  Taking screenshots for category {cat_num}...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            count = 0
            for test_case in test_cases:
                case_id = test_case.get('id', '')
                screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
                if os.path.exists(screenshot_path):
                    count += 1
                    continue
                try:
                    page.goto(BASE_URL, timeout=15000)
                    page.wait_for_load_state('networkidle', timeout=15000)
                    time.sleep(1)
                    page.screenshot(path=screenshot_path, full_page=True)
                    count += 1
                except Exception as e:
                    print(f"    Screenshot failed for {case_id}: {e}")
            browser.close()
            print(f"  Screenshots taken: {count}/{len(test_cases)}")
    except Exception as e:
        print(f"  Screenshot batch failed: {e}")

def generate_report(all_results, agent_id):
    """Generate comprehensive report."""
    report_file = f"{REPORT_DIR}/agent{agent_id}_report.md"
    total_tests = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    failed = total_tests - passed
    pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0
    categories = {}
    for r in all_results:
        cat = r['category']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)
    root_causes = {}
    for r in all_results:
        if r['root_cause']:
            rc = r['root_cause']
            root_causes[rc] = root_causes.get(rc, 0) + 1
    avg_response_time = sum(r['response_time'] for r in all_results) / total_tests if total_tests > 0 else 0
    avg_score = sum(r['total_score'] for r in all_results) / total_tests if total_tests > 0 else 0
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"# Agent 2 Benchmark Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Agent:** {agent_id}\n\n")
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
        for cat_name, cat_results in sorted(categories.items()):
            cat_passed = sum(1 for r in cat_results if r['passed'])
            cat_failed = len(cat_results) - cat_passed
            cat_rate = (cat_passed / len(cat_results) * 100) if cat_results else 0
            cat_avg = sum(r['total_score'] for r in cat_results) / len(cat_results) if cat_results else 0
            f.write(f"| {cat_name} | {len(cat_results)} | {cat_passed} | {cat_failed} | {cat_rate:.0f}% | {cat_avg:.3f} |\n")
        f.write("\n")
        if root_causes:
            f.write("### Failure Root Causes\n\n")
            f.write("| Root Cause | Count | % of Failures | Severity | Description |\n")
            f.write("|------------|-------|---------------|----------|-------------|\n")
            for rc, count in sorted(root_causes.items(), key=lambda x: -x[1]):
                pct = (count / failed * 100) if failed > 0 else 0
                severity = "P0" if rc in ['hallucination', 'safety_leak'] else "P2"
                f.write(f"| {rc} | {count} | {pct:.1f}% | {severity} | {rc} |\n")
            f.write("\n")
        f.write("## Detailed Results\n\n")
        for cat_name, cat_results in sorted(categories.items()):
            cat_passed = sum(1 for r in cat_results if r['passed'])
            cat_total = len(cat_results)
            cat_rate = (cat_passed / cat_total * 100) if cat_total > 0 else 0
            f.write(f"### {cat_name} ({cat_passed}/{cat_total} passed, {cat_rate:.0f}%)\n\n")
            for r in cat_results:
                status = "PASS" if r['passed'] else "FAIL"
                f.write(f"#### {status} {r['case_id']}\n\n")
                f.write(f"**Input:** {r['input']}\n\n")
                f.write(f"**Response:**\n> {r['response'][:500]}{'...' if len(r['response']) > 500 else ''}\n\n")
                f.write(f"**Scores:**\n")
                f.write(f"- Total: {r['total_score']:.2f}\n")
                f.write(f"- Keyword: {r['dimension_scores']['keyword']:.2f}\n")
                f.write(f"- Completeness: {r['dimension_scores']['completeness']:.2f}\n")
                f.write(f"- Safety: {r['dimension_scores']['safety']:.2f}\n")
                f.write(f"- Accuracy: {r['dimension_scores']['accuracy']:.2f}\n")
                f.write(f"- UX: {r['dimension_scores']['ux']:.2f}\n\n")
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
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    categories = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else []

    if not categories:
        print(f"Usage: python agent2_noscreenshot.py <agent_id> <category1> ...")
        sys.exit(1)

    print(f"Agent {agent_id} Benchmark Runner (Lightweight - No Inline Screenshots)")
    print(f"Categories: {categories}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_results = []
    cat_test_cases = {}
    for cat_num in categories:
        try:
            # Load test cases for later screenshot use
            files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
            if files:
                with open(files[0], 'r') as f:
                    data = json.load(f)
                    cat_test_cases[cat_num] = data.get('cases', data) if isinstance(data, dict) else data

            results = run_category(cat_num, agent_id)
            all_results.extend(results)
            print(f"  Category {cat_num} complete: {sum(1 for r in results if r['passed'])}/{len(results)} passed")

            # Take screenshots for this category immediately after
            if cat_num in cat_test_cases:
                take_screenshots_for_category(cat_num, cat_test_cases[cat_num])

        except Exception as e:
            print(f"  Category {cat_num} ERROR: {e}")
            import traceback
            traceback.print_exc()

    # Check for incomplete categories and help
    incomplete = []
    for cat_num in range(1, 37):
        files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
        if not files:
            continue
        with open(files[0], 'r') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'cases' in data:
                expected = len(data['cases'])
            elif isinstance(data, list):
                expected = len(data)
            else:
                continue
        actual = len(glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"))
        if actual < expected:
            incomplete.append({'category': cat_num, 'expected': expected, 'actual': actual, 'missing': expected - actual})

    if incomplete:
        print(f"\nFound {len(incomplete)} incomplete categories after finishing assigned categories")
        for cat in incomplete[:5]:
            print(f"  Category {cat['category']:02d}: {cat['actual']}/{cat['expected']} ({cat['missing']} missing)")

    report_file = generate_report(all_results, agent_id)

    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\n{'='*60}")
    print(f"AGENT {agent_id} COMPLETE")
    print(f"Total: {total} | Passed: {passed} | Failed: {total - passed}")
    print(f"Pass Rate: {passed/total*100:.1f}%" if total > 0 else "No tests")
    print(f"Report: {report_file}")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
