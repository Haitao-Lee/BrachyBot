#!/usr/bin/env python3
"""
Agent 3 Benchmark Runner - Categories 19-27
- Runs ALL test cases (NO sampling, NO skipping)
- Takes screenshots efficiently (browser reuse)
- Saves intermediate results per category
- Resilient to server restarts
"""
import json, os, sys, time, glob, requests
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
RESULTS_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent3_all_results.json"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

CATEGORIES = [19, 20, 21, 22, 23, 24, 25, 26, 27]

def send_message(text, session_id, timeout=300, retries=3):
    payload = {
        "message": text,
        "clear_context": True,
        "session_id": session_id,
        "stream": False
    }
    for attempt in range(retries):
        try:
            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            data = response.json()
            return data.get('response', '')
        except Exception as e:
            if attempt < retries - 1:
                print(f"\n    Retry {attempt+1}/{retries}: {str(e)[:80]}", end="", flush=True)
                time.sleep(5)
            else:
                return f"Error: {str(e)}"

def take_screenshot_batch(results, cat_num):
    """Take screenshots using a single browser instance for all results."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            for r in results:
                case_id = r['case_id']
                screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
                if r.get('screenshot'):
                    continue  # Already has screenshot
                try:
                    page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
                    time.sleep(3)
                    page.screenshot(path=screenshot_path, full_page=True)
                    r['screenshot'] = screenshot_path
                except Exception as e:
                    print(f"    Screenshot failed for {case_id}: {e}")
                    r['screenshot'] = None
            browser.close()
    except ImportError:
        print("    Playwright not available, skipping screenshots")
    except Exception as e:
        print(f"    Screenshot batch failed: {e}")

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
    """Run ALL test cases for a category with batch screenshots."""
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        print(f"No benchmark file found for category {cat_num}")
        return []

    cat_file = files[0]
    cat_name = os.path.basename(cat_file).replace('.json', '')
    with open(cat_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    test_cases = data.get('cases', data) if isinstance(data, dict) else data

    print(f"\n{'='*60}")
    print(f"Category {cat_num}: {cat_name} ({len(test_cases)} cases)")
    print(f"{'='*60}")

    results = []

    # Load existing results for this category to skip completed cases
    existing_results = []
    existing_file = f"/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent3_cat{cat_num:02d}.json"
    if os.path.exists(existing_file):
        try:
            with open(existing_file, 'r') as ef:
                existing_results = json.load(ef)
            existing_ids = set(r['case_id'] for r in existing_results)
            print(f"  Resuming: {len(existing_results)} existing results loaded")
        except:
            existing_ids = set()
    else:
        existing_ids = set()

    for i, test_case in enumerate(test_cases):
        case_id = test_case.get('id', f'Q{i+1:04d}')

        # Skip already completed cases
        if case_id in existing_ids:
            existing_r = [r for r in existing_results if r['case_id'] == case_id]
            if existing_r:
                results.append(existing_r[0])
                print(f"  [{i+1}/{len(test_cases)}] {case_id}... CACHED ({existing_r[0]['total_score']:.2f})")
                continue

        input_text = test_case.get('input', '')
        print(f"  [{i+1}/{len(test_cases)}] {case_id}...", end=" ", flush=True)

        session_id = f"agent{agent_id}_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
        start_time = time.time()
        response = send_message(input_text, session_id, timeout=300)
        response_time = time.time() - start_time

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
            'response': response[:2000],
            'response_length': len(response),
            'total_score': total_score,
            'dimension_scores': dimension_scores,
            'passed': passed,
            'root_cause': root_cause,
            'root_cause_detail': root_cause_detail,
            'response_time': response_time,
            'screenshot': None,
            'difficulty': test_case.get('difficulty', 'unknown'),
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{response_time:.1f}s]")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")
        sys.stdout.flush()

        # Save intermediate results after every case
        save_intermediate(results, cat_num)

    # Try batch screenshots for this category
    print(f"  Taking screenshots for {len(results)} cases...")
    take_screenshot_batch(results, cat_num)

    # Final save for this category
    save_intermediate(results, cat_num)

    passed_count = sum(1 for r in results if r['passed'])
    print(f"\n  Category {cat_num} complete: {passed_count}/{len(results)} passed ({passed_count/len(results)*100:.1f}%)")
    return results

def save_intermediate(results, cat_num=None):
    """Save results to file."""
    try:
        # Save per-category file
        if cat_num is not None:
            cat_file = f"/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent3_cat{cat_num:02d}.json"
            cat_results = [r for r in results if r.get('category_num') == cat_num]
            with open(cat_file, 'w') as f:
                json.dump(cat_results, f, indent=2, default=str)

        # Load existing and merge for main file
        existing = []
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, 'r') as f:
                existing = json.load(f)

        # Remove results from same categories that we're updating
        cat_nums = set(r['category_num'] for r in results)
        existing = [r for r in existing if r.get('category_num') not in cat_nums]

        # Merge
        all_results = existing + results
        with open(RESULTS_FILE, 'w') as f:
            json.dump(all_results, f, indent=2, default=str)
    except Exception as e:
        print(f"  Warning: Could not save intermediate results: {e}")

def generate_report(all_results, agent_id):
    """Generate comprehensive report."""
    report_file = f"{REPORT_DIR}/agent{agent_id}_report.md"
    total_tests = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    failed = total_tests - passed
    pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0

    categories = {}
    for r in all_results:
        cat = r.get('category', 'unknown')
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    root_causes = {}
    for r in all_results:
        if r.get('root_cause'):
            rc = r['root_cause']
            root_causes[rc] = root_causes.get(rc, 0) + 1

    avg_response_time = sum(r.get('response_time', 0) for r in all_results) / total_tests if total_tests > 0 else 0
    avg_score = sum(r.get('total_score', 0) for r in all_results) / total_tests if total_tests > 0 else 0

    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"# Agent {agent_id} Benchmark Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Agent:** {agent_id}\n")
        f.write(f"**Categories:** 19-27\n\n")
        f.write(f"## Overall Summary\n\n")
        f.write(f"| Metric | Value |\n")
        f.write(f"|--------|-------|\n")
        f.write(f"| Total Tests | {total_tests} |\n")
        f.write(f"| Passed | {passed} |\n")
        f.write(f"| Failed | {failed} |\n")
        f.write(f"| Pass Rate | {pass_rate:.1f}% |\n")
        f.write(f"| Average Score | {avg_score:.2f} |\n")
        f.write(f"| Avg Response Time | {avg_response_time:.1f}s |\n\n")

        f.write(f"## Category Breakdown\n\n")
        f.write(f"| Category | Cases | Passed | Failed | Pass Rate |\n")
        f.write(f"|----------|-------|--------|--------|----------|\n")
        for cat_name in sorted(categories.keys(), key=lambda x: categories[x][0].get('category_num', 0)):
            cat_results = categories[cat_name]
            cat_passed = sum(1 for r in cat_results if r['passed'])
            cat_total = len(cat_results)
            cat_rate = (cat_passed / cat_total * 100) if cat_total > 0 else 0
            f.write(f"| {cat_name} | {cat_total} | {cat_passed} | {cat_total - cat_passed} | {cat_rate:.1f}% |\n")

        f.write(f"\n## Root Cause Analysis\n\n")
        if root_causes:
            for rc, count in sorted(root_causes.items(), key=lambda x: -x[1]):
                pct = count / failed * 100 if failed > 0 else 0
                f.write(f"- **{rc}**: {count} cases ({pct:.1f}% of failures)\n")
        else:
            f.write(f"No root causes identified.\n")

        f.write(f"\n## Detailed Results by Category\n\n")
        for cat_name in sorted(categories.keys(), key=lambda x: categories[x][0].get('category_num', 0)):
            cat_results = categories[cat_name]
            cat_num = cat_results[0].get('category_num', 0)
            f.write(f"\n### Category {cat_num}: {cat_name}\n\n")

            failed_cases = [r for r in cat_results if not r['passed']]
            if failed_cases:
                f.write(f"**Failed Cases ({len(failed_cases)}):**\n\n")
                for r in failed_cases:
                    f.write(f"- **{r['case_id']}** (score: {r['total_score']:.2f})\n")
                    f.write(f"  - Root Cause: {r.get('root_cause', 'N/A')} - {r.get('root_cause_detail', 'N/A')}\n")
                    f.write(f"  - Response Length: {r.get('response_length', 0)} chars\n")
                    if r.get('screenshot'):
                        f.write(f"  - Screenshot: `{r['screenshot']}`\n")
                    f.write(f"\n")
            else:
                f.write(f"All {len(cat_results)} cases passed!\n\n")

    print(f"\nReport saved to: {report_file}")
    return report_file

def main():
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    cats_to_run = [int(c) for c in sys.argv[2:]] if len(sys.argv) > 2 else CATEGORIES

    print(f"Agent {agent_id} Benchmark Runner")
    print(f"Categories: {cats_to_run}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Check server
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        print(f"Server: ONLINE (status {r.status_code})")
    except:
        print(f"Server: OFFLINE - attempting to continue anyway")

    all_results = []

    for cat_num in cats_to_run:
        results = run_category(cat_num, agent_id)
        all_results.extend(results)

        # Save after each category
        save_intermediate(all_results, cat_num)

    # Generate final report
    print(f"\n{'='*60}")
    print(f"GENERATING REPORT")
    print(f"{'='*60}")
    report_file = generate_report(all_results, agent_id)

    total_tests = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\n{'='*60}")
    print(f"FINAL RESULTS")
    print(f"{'='*60}")
    print(f"Total: {total_tests} tests")
    print(f"Passed: {passed} ({passed/total_tests*100:.1f}%)" if total_tests > 0 else "No tests")
    print(f"Failed: {total_tests - passed}")
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
