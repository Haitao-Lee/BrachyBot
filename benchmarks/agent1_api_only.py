#!/usr/bin/env python3
"""
Agent 1 - API-only runner (no screenshots to avoid OOM)
Runs categories 1-9, all cases, saves results for screenshot pass later.
"""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
RESULTS_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result"

os.makedirs(RESULTS_DIR, exist_ok=True)
AGENT_ID = 1

def load_benchmark(category_file):
    with open(category_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if isinstance(data, dict) and 'cases' in data:
            return data['cases']
        elif isinstance(data, list):
            return data
        return []

def send_message(text, session_id, timeout=120):
    payload = {"message": text, "clear_context": True, "session_id": session_id, "stream": False}
    for attempt in range(3):
        try:
            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            if response.status_code == 429:
                print(f" [rate-limited, wait 15s]", end="", flush=True)
                time.sleep(15)
                continue
            data = response.json()
            return data.get('response', '')
        except requests.exceptions.ConnectionError:
            print(f" [conn-err]", end="", flush=True)
            time.sleep(5)
        except Exception as e:
            print(f" [err]", end="", flush=True)
            time.sleep(3)
    return ""

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
    results = []
    for i, test_case in enumerate(test_cases):
        case_id = test_case.get('id', f'Q{i+1:04d}')
        input_text = test_case.get('input', '')
        print(f"  [{i+1}/{len(test_cases)}] {case_id}...", end=" ", flush=True)
        session_id = f"agent{AGENT_ID}_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
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
            'total_score': round(total_score, 3), 'dimension_scores': {k: round(v, 3) for k, v in dimension_scores.items()},
            'passed': passed, 'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
            'response_time': round(response_time, 1), 'screenshot': None,
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)
        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{response_time:.1f}s] {len(response)}ch")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")
        time.sleep(0.5)
    return results

def take_screenshots_for_results(all_results):
    """Take screenshots for all results in batch using a single browser."""
    print(f"\n{'='*60}")
    print(f"SCREENSHOT PASS: {len(all_results)} cases")
    print(f"{'='*60}")
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        SCREENSHOT_DIR = f"{RESULTS_DIR}/screenshots"
        count = 0
        for i, r in enumerate(all_results):
            case_id = r['case_id']
            cat_num = r['category_num']
            screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
            if os.path.exists(screenshot_path):
                r['screenshot'] = screenshot_path
                continue
            print(f"  [{i+1}/{len(all_results)}] {case_id}...", end=" ", flush=True)
            try:
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})
                page.goto(BASE_URL, timeout=15000)
                page.wait_for_load_state('networkidle', timeout=10000)
                time.sleep(1)
                page.screenshot(path=screenshot_path, full_page=True)
                page.close()
                r['screenshot'] = screenshot_path
                count += 1
                print("OK")
            except Exception as e:
                try:
                    page.close()
                except:
                    pass
                print(f"FAIL: {str(e)[:60]}")
        browser.close()
        pw.stop()
        print(f"  Screenshots taken: {count}")
    except Exception as e:
        print(f"  Screenshot batch failed: {e}")
    return all_results

def generate_report(all_results, agent_id):
    REPORT_DIR = f"{RESULTS_DIR}/reports"
    os.makedirs(REPORT_DIR, exist_ok=True)
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
        f.write(f"# Agent {agent_id} Benchmark Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Agent:** {agent_id}\n\n")
        f.write("## Executive Summary\n\n")
        f.write("| Metric | Value |\n|--------|-------|\n")
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
            f.write("| Root Cause | Count | % of Failures | Severity |\n")
            f.write("|------------|-------|---------------|----------|\n")
            for rc, count in sorted(root_causes.items(), key=lambda x: -x[1]):
                pct = (count / failed * 100) if failed > 0 else 0
                severity = "P0" if rc in ['hallucination', 'safety_leak'] else "P2"
                f.write(f"| {rc} | {count} | {pct:.1f}% | {severity} |\n")
            f.write("\n")
        f.write("## Detailed Results\n\n")
        for cat_name, cat_results in sorted(categories.items()):
            cat_passed = sum(1 for r in cat_results if r['passed'])
            cat_total = len(cat_results)
            cat_rate = (cat_passed / cat_total * 100) if cat_total > 0 else 0
            f.write(f"### {cat_name} ({cat_passed}/{cat_total} passed, {cat_rate:.0f}%)\n\n")
            for r in cat_results:
                status = "PASS" if r['passed'] else "FAIL"
                f.write(f"#### [{status}] {r['case_id']}\n\n")
                f.write(f"**Input:** {r['input']}\n\n")
                resp_preview = r['response'][:500]
                if len(r['response']) > 500:
                    resp_preview += '...'
                f.write(f"**Response:**\n> {resp_preview}\n\n")
                f.write(f"**Scores:**\n- Total: {r['total_score']:.2f}\n")
                for dim, val in r['dimension_scores'].items():
                    f.write(f"- {dim.capitalize()}: {val:.2f}\n")
                f.write("\n")
                if r['root_cause']:
                    f.write(f"**Root Cause:** {r['root_cause']}\n\n")
                    f.write(f"**Detail:** {r['root_cause_detail']}\n\n")
                if r.get('screenshot') and os.path.exists(r['screenshot']):
                    rel_path = os.path.relpath(r['screenshot'], REPORT_DIR)
                    f.write(f"**Screenshot:** ![{r['case_id']}]({rel_path})\n\n")
                f.write("---\n\n")
    print(f"Report generated: {report_file}")
    return report_file

if __name__ == "__main__":
    categories = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else list(range(1, 10))
    print(f"Agent {AGENT_ID} API-Only Runner (with screenshot pass)")
    print(f"Categories: {categories}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Load existing results to avoid re-running
    existing_file = f"{RESULTS_DIR}/agent{AGENT_ID}_all_results.json"
    existing_results = []
    if os.path.exists(existing_file):
        try:
            with open(existing_file) as f:
                existing_results = json.load(f)
            print(f"Loaded {len(existing_results)} existing results")
        except:
            pass

    # Determine which categories/cases are already done
    done_cases = set()
    for r in existing_results:
        done_cases.add((r['category'], r['case_id']))

    all_results = list(existing_results)
    for cat_num in categories:
        files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
        if not files:
            print(f"No benchmark file for category {cat_num}")
            continue
        with open(files[0]) as f:
            data = json.load(f)
        cat_name = os.path.basename(files[0]).replace('.json', '')
        cases = data['cases'] if isinstance(data, dict) and 'cases' in data else data
        remaining = [tc for tc in cases if (cat_name, tc.get('id', '')) not in done_cases]
        if not remaining:
            print(f"\nCategory {cat_num}: {cat_name} - ALL DONE ({len(cases)} cases)")
            continue
        print(f"\nCategory {cat_num}: {cat_name} - {len(remaining)}/{len(cases)} remaining")
        
        cat_results = run_category(cat_num)
        all_results.extend(cat_results)
        
        # Save after each category
        with open(existing_file, 'w') as f:
            json.dump(all_results, f, indent=2)
        cat_passed = sum(1 for r in cat_results if r['passed'])
        print(f"  => Category {cat_num} saved: {cat_passed}/{len(cat_results)} passed")

    # Take screenshots
    all_results = take_screenshots_for_results(all_results)
    
    # Final save
    with open(existing_file, 'w') as f:
        json.dump(all_results, f, indent=2)

    # Generate report
    report_file = generate_report(all_results, AGENT_ID)
    
    total = len(all_results)
    passed_count = sum(1 for r in all_results if r['passed'])
    print(f"\n{'='*60}")
    print(f"AGENT {AGENT_ID} COMPLETE")
    print(f"Total: {total} | Passed: {passed_count} | Failed: {total - passed_count}")
    print(f"Pass Rate: {passed_count/total*100:.1f}%" if total > 0 else "No tests")
    print(f"Report: {report_file}")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
