#!/usr/bin/env python3
"""
Agent 2 Category Runner
- Processes missing cases for specific categories
- Uses longer timeouts for complex medical queries
- Takes screenshots for every case
- Reports progress
"""
import json, os, sys, time, glob, requests
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def get_completed(cat):
    s = set()
    for f in glob.glob(f'{SCREENSHOT_DIR}/{cat:02d}_*.png'):
        b = os.path.basename(f).replace('.png','').replace(f'{cat:02d}_','')
        if os.path.getsize(f) > 1000:
            s.add(b)
    return s

def load_cases(cat):
    files = glob.glob(f'{BENCHMARK_DIR}/{cat:02d}_*.json')
    if not files: return []
    with open(files[0]) as f:
        d = json.load(f)
    return d.get('cases',d) if isinstance(d,dict) else d

def send_msg(text, sid, timeout=180):
    for attempt in range(4):
        try:
            r = requests.post(f'{BASE_URL}/api/chat',
                json={'message': text, 'clear_context': True, 'session_id': sid, 'stream': False},
                timeout=timeout)
            data = r.json()
            return data.get('response','')
        except requests.exceptions.Timeout:
            print(f'    Retry {attempt+1}: Timeout', flush=True)
            time.sleep(5)
        except Exception as e:
            print(f'    Retry {attempt+1}: {type(e).__name__}: {str(e)[:80]}', flush=True)
            time.sleep(10)
    return ''

def take_screenshot(cat, case_id, retries=2):
    screenshot_path = f"{SCREENSHOT_DIR}/{cat:02d}_{case_id}.png"
    if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
        return screenshot_path
    for attempt in range(retries):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})
                page.goto(BASE_URL, timeout=30000)
                page.wait_for_load_state('networkidle', timeout=15000)
                time.sleep(2)
                page.screenshot(path=screenshot_path, full_page=True)
                browser.close()
            return screenshot_path
        except Exception as e:
            print(f'    Screenshot attempt {attempt+1} failed: {str(e)[:80]}', flush=True)
            if attempt < retries - 1:
                time.sleep(5)
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

def run_category(cat_num, agent_id):
    cases = load_cases(cat_num)
    done = get_completed(cat_num)
    remaining = [c for c in cases if c.get('id','') not in done]
    print(f"\n{'='*60}")
    print(f"Category {cat_num}: {len(cases)} total, {len(done)} completed, {len(remaining)} remaining")
    print(f"{'='*60}", flush=True)

    if not remaining:
        print("  All cases completed!")
        return []

    results = []
    for i, tc in enumerate(remaining):
        cid = tc.get('id', f'Q{i+1:04d}')
        inp = tc.get('input', '')
        print(f"  [{i+1}/{len(remaining)}] {cid}...", end=" ", flush=True)

        # Check server
        try:
            hr = requests.get(f'{BASE_URL}/', timeout=5)
            if hr.status_code != 200:
                print('Server not ready, waiting...', flush=True)
                time.sleep(30)
                continue
        except:
            print('Server offline, waiting...', flush=True)
            time.sleep(30)
            continue

        sid = f"agent{agent_id}_{cat_num:02d}_{cid}_{int(time.time()*1000)}"
        t0 = time.time()
        resp = send_msg(inp, sid, timeout=180)
        dt = time.time() - t0

        # Take screenshot
        screenshot = take_screenshot(cat_num, cid)

        # Score
        total_score, dim_scores = score_response(resp, tc)
        passed = total_score >= tc.get('pass_threshold', 0.6) and dim_scores['safety'] > 0

        root_cause = None
        root_cause_detail = None
        if not passed:
            root_cause, root_cause_detail = analyze_failure(resp, tc)

        result = {
            'case_id': cid, 'category_num': cat_num,
            'input': inp[:200], 'response': resp[:1500], 'response_length': len(resp),
            'total_score': total_score, 'dimension_scores': dim_scores, 'passed': passed,
            'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
            'response_time': dt, 'screenshot': screenshot,
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{dt:.1f}s] len={len(resp)} shot={'Y' if screenshot else 'N'}", flush=True)
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}", flush=True)

        # Small delay between requests to avoid overwhelming server
        time.sleep(2)

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

    root_causes = {}
    for r in all_results:
        if r['root_cause']:
            rc = r['root_cause']
            root_causes[rc] = root_causes.get(rc, 0) + 1

    avg_response_time = sum(r['response_time'] for r in all_results) / total_tests if total_tests > 0 else 0
    avg_score = sum(r['total_score'] for r in all_results) / total_tests if total_tests > 0 else 0

    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"# Agent {agent_id} Benchmark Report\n\n")
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
        for cat_num, cat_results in sorted(categories.items()):
            cat_passed = sum(1 for r in cat_results if r['passed'])
            cat_failed = len(cat_results) - cat_passed
            cat_rate = (cat_passed / len(cat_results) * 100) if cat_results else 0
            cat_avg = sum(r['total_score'] for r in cat_results) / len(cat_results) if cat_results else 0
            f.write(f"| Cat {cat_num:02d} | {len(cat_results)} | {cat_passed} | {cat_failed} | {cat_rate:.0f}% | {cat_avg:.3f} |\n")

        if root_causes:
            f.write("\n### Failure Root Causes\n\n")
            f.write("| Root Cause | Count | % of Failures | Severity |\n")
            f.write("|------------|-------|---------------|----------|\n")
            for rc, count in sorted(root_causes.items(), key=lambda x: -x[1]):
                pct = (count / failed * 100) if failed > 0 else 0
                severity = "P0" if rc in ['hallucination', 'safety_leak'] else "P2"
                f.write(f"| {rc} | {count} | {pct:.1f}% | {severity} |\n")

        f.write("\n## Detailed Results\n\n")
        for cat_num, cat_results in sorted(categories.items()):
            cat_passed = sum(1 for r in cat_results if r['passed'])
            cat_total = len(cat_results)
            cat_rate = (cat_passed / cat_total * 100) if cat_total > 0 else 0
            f.write(f"\n### Category {cat_num:02d} ({cat_passed}/{cat_total} passed, {cat_rate:.0f}%)\n\n")
            for r in cat_results:
                status_icon = "PASS" if r['passed'] else "FAIL"
                f.write(f"#### [{status_icon}] {r['case_id']}\n\n")
                f.write(f"**Input:** {r['input']}\n\n")
                f.write(f"**Response Length:** {r['response_length']} chars\n\n")
                f.write(f"**Scores:** total={r['total_score']:.2f} | kw={r['dimension_scores']['keyword']:.2f} | compl={r['dimension_scores']['completeness']:.2f} | safe={r['dimension_scores']['safety']:.2f} | acc={r['dimension_scores']['accuracy']:.2f} | ux={r['dimension_scores']['ux']:.2f}\n\n")
                if r['root_cause']:
                    f.write(f"**Root Cause:** {r['root_cause']} - {r['root_cause_detail']}\n\n")
                if r['screenshot'] and os.path.exists(r['screenshot']):
                    rel_path = os.path.relpath(r['screenshot'], REPORT_DIR)
                    f.write(f"**Screenshot:** ![screenshot]({rel_path})\n\n")
                f.write("---\n\n")

    print(f"\nReport generated: {report_file}")
    return report_file

if __name__ == "__main__":
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    categories = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else []

    if not categories:
        print(f"Usage: python agent2_cat_runner.py <agent_id> <cat1> <cat2> ...")
        sys.exit(1)

    print("=" * 60)
    print(f"AGENT {agent_id} CATEGORY RUNNER")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Categories: {categories}", flush=True)

    # Check server
    try:
        r = requests.get(f'{BASE_URL}/', timeout=5)
        if r.status_code != 200:
            print("Server not ready!")
            sys.exit(1)
    except:
        print("Server offline!")
        sys.exit(1)

    all_results = []
    for cat_num in categories:
        results = run_category(cat_num, agent_id)
        all_results.extend(results)
        cat_passed = sum(1 for r in results if r['passed'])
        print(f"\n  Category {cat_num} complete: {cat_passed}/{len(results)} passed", flush=True)

    if all_results:
        report_file = generate_report(all_results, agent_id)

        total = len(all_results)
        passed = sum(1 for r in all_results if r['passed'])
        print(f"\n{'='*60}")
        print(f"AGENT {agent_id} COMPLETE")
        print(f"Total: {total} | Passed: {passed} | Failed: {total - passed}")
        print(f"Pass Rate: {passed/total*100:.1f}%" if total > 0 else "No tests")
        print(f"Report: {report_file}")
        print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
