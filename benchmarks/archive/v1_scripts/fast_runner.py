#!/usr/bin/env python3
"""Fast benchmark runner - processes remaining cases efficiently with batched screenshots."""
import json, os, sys, time, glob, requests
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
STATE_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/scheduler_state.json"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code == 200
    except:
        return False

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {"completed": {}, "failed": {}, "in_progress": {}}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def send_message(text, session_id, timeout=180):
    for attempt in range(3):
        try:
            if not check_server():
                print("    Server offline, waiting...")
                for _ in range(60):
                    if check_server():
                        break
                    time.sleep(5)
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
            print(f"    Timeout attempt {attempt+1}/3")
            time.sleep(5)
        except Exception as e:
            print(f"    Error attempt {attempt+1}/3: {e}")
            time.sleep(5)
    return "Error: All attempts failed"

def take_screenshot_batch(case_ids, cat_num):
    """Take screenshots for a batch of case IDs using a single browser instance."""
    screenshots = {}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
            time.sleep(3)
            for case_id in case_ids:
                screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
                if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                    screenshots[case_id] = screenshot_path
                    continue
                try:
                    page.screenshot(path=screenshot_path, full_page=True)
                    screenshots[case_id] = screenshot_path
                except Exception as e:
                    print(f"    Screenshot failed for {case_id}: {e}")
                    screenshots[case_id] = None
            browser.close()
    except Exception as e:
        print(f"    Browser launch failed: {e}")
        for case_id in case_ids:
            screenshots[case_id] = None
    return screenshots

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
            return 'hallucination', f'Contains uncertainty: "{kw}"'
    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            return 'safety_leak', f'Forbidden keyword: "{kw}"'
    if len(response) < 100:
        return 'too_brief', f'Too short ({len(response)} chars)'
    if len(response) > 5000:
        return 'too_verbose', f'Too long ({len(response)} chars)'
    expected_keywords = test_case.get('expected_keywords', [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
        else:
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
        if matched == 0:
            return 'keyword_missing', 'No expected keywords found'
    return 'wrong_answer', 'Does not meet expectations'

def run_category(cat_num, agent_id, state):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return []
    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
        cases = data.get('cases', data) if isinstance(data, dict) else data

    completed = set()
    for f in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        bn = os.path.basename(f).replace(f"{cat_num:02d}_", "").replace(".png", "")
        completed.add(bn)

    remaining = [tc for tc in cases if tc.get('id', '') not in completed]
    cat_name = os.path.basename(files[0]).replace('.json', '')

    print(f"\n{'='*60}")
    print(f"Category {cat_num}: {cat_name}")
    print(f"Total: {len(cases)} | Completed: {len(completed)} | Remaining: {len(remaining)}")
    print(f"{'='*60}")

    if not remaining:
        print("  All cases already completed!")
        return []

    results = []
    BATCH_SIZE = 5

    for batch_start in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[batch_start:batch_start+BATCH_SIZE]
        batch_ids = [tc.get('id', f'Q{batch_start+i+1:04d}') for i, tc in enumerate(batch)]

        print(f"\n  Batch {batch_start//BATCH_SIZE + 1}: Processing {len(batch)} cases...")

        # Process each case in the batch
        for i, test_case in enumerate(batch):
            case_id = test_case.get('id', f'Q{batch_start+i+1:04d}')
            input_text = test_case.get('input', '')
            print(f"    [{batch_start+i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

            session_id = f"fast_agent{agent_id}_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
            start_time = time.time()
            response = send_message(input_text, session_id)
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
                print(f"        -> {root_cause}: {root_cause_detail}")

            state["completed"][f"{cat_num}_{case_id}"] = True

        # Take screenshots for the batch
        print(f"    Taking screenshots for batch...")
        screenshots = take_screenshot_batch(batch_ids, cat_num)
        for r in results[-len(batch):]:
            r['screenshot'] = screenshots.get(r['case_id'])

        save_state(state)
        print(f"    Batch complete. State saved.")

    return results

def generate_report(all_results, agent_id):
    report_file = f"{REPORT_DIR}/agent{agent_id}_report_cats1to9.md"
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
        f.write(f"# Agent {agent_id} Benchmark Report (Categories 1-9)\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Agent:** {agent_id}\n\n")
        f.write("## Executive Summary\n\n")
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Total Tests | {total_tests} |\n| Passed | {passed} |\n| Failed | {failed} |\n")
        f.write(f"| Pass Rate | {pass_rate:.1f}% |\n| Avg Score | {avg_score:.3f} |\n")
        f.write(f"| Avg Response Time | {avg_response_time:.1f}s |\n\n")

        f.write("### Category Breakdown\n\n")
        f.write("| Category | Cases | Passed | Failed | Pass Rate | Avg Score |\n")
        f.write("|----------|-------|--------|--------|-----------|----------|\n")
        for cat_name, cat_results in sorted(categories.items()):
            cp = sum(1 for r in cat_results if r['passed'])
            cf = len(cat_results) - cp
            cr = (cp / len(cat_results) * 100) if cat_results else 0
            ca = sum(r['total_score'] for r in cat_results) / len(cat_results) if cat_results else 0
            f.write(f"| {cat_name} | {len(cat_results)} | {cp} | {cf} | {cr:.0f}% | {ca:.3f} |\n")
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
            cp = sum(1 for r in cat_results if r['passed'])
            ct = len(cat_results)
            cr = (cp / ct * 100) if ct > 0 else 0
            f.write(f"### {cat_name} ({cp}/{ct} passed, {cr:.0f}%)\n\n")
            for r in cat_results:
                status = "PASS" if r['passed'] else "FAIL"
                f.write(f"#### [{status}] {r['case_id']}\n\n")
                f.write(f"**Input:** {r['input']}\n\n")
                f.write(f"**Response (first 500 chars):**\n> {r['response'][:500]}{'...' if len(r['response']) > 500 else ''}\n\n")
                f.write(f"**Scores:** total={r['total_score']:.2f} | keyword={r['dimension_scores']['keyword']:.2f} | completeness={r['dimension_scores']['completeness']:.2f} | safety={r['dimension_scores']['safety']:.2f} | accuracy={r['dimension_scores']['accuracy']:.2f} | ux={r['dimension_scores']['ux']:.2f}\n\n")
                f.write(f"**Response Time:** {r['response_time']:.1f}s | **Response Length:** {r['response_length']} chars\n\n")
                if r['root_cause']:
                    f.write(f"**Root Cause:** {r['root_cause']} - {r['root_cause_detail']}\n\n")
                if r['screenshot'] and os.path.exists(r['screenshot']):
                    rel_path = os.path.relpath(r['screenshot'], REPORT_DIR)
                    f.write(f"![{r['case_id']}]({rel_path})\n\n")
                f.write("---\n\n")

    print(f"\nReport generated: {report_file}")
    return report_file

if __name__ == "__main__":
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    categories = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else []

    if not categories:
        print("Usage: python fast_runner.py <agent_id> <cat1> <cat2> ...")
        sys.exit(1)

    state = load_state()

    print("=" * 60)
    print(f"FAST BENCHMARK RUNNER - Agent {agent_id}")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Categories: {categories}")

    if not check_server():
        print("Server offline, waiting...")
        for _ in range(60):
            if check_server():
                break
            time.sleep(5)
        if not check_server():
            print("Cannot continue without server")
            sys.exit(1)

    all_results = []
    for cat_num in categories:
        results = run_category(cat_num, agent_id, state)
        all_results.extend(results)
        cat_passed = sum(1 for r in results if r['passed'])
        print(f"  Category {cat_num} complete: {cat_passed}/{len(results)} passed")

    report_file = generate_report(all_results, agent_id)

    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\n{'='*60}")
    print(f"AGENT {agent_id} COMPLETE")
    print(f"Total: {total} | Passed: {passed} | Failed: {total - passed}")
    print(f"Pass Rate: {passed/total*100:.1f}%" if total > 0 else "No tests")
    print(f"Report: {report_file}")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
