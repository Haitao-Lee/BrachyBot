#!/usr/bin/env python3
"""
Agent 4 runner - NO screenshots (to avoid OOM from repeated Chromium launches).
Runs categories 32-36, scores and saves results.
"""
import sys, os, json, time, glob, requests
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unified_agent import load_benchmark, send_message, score_response, analyze_failure, BENCHMARK_DIR, REPORT_DIR

AGENT_ID = 4
CATEGORIES = [32, 33, 34, 35, 36]
RESULTS_FILE = f"{REPORT_DIR}/agent4_results_28_36.json"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"

# Load existing
existing_results = []
completed_case_ids = set()
if os.path.exists(RESULTS_FILE):
    with open(RESULTS_FILE) as f:
        existing_results = json.load(f)
    completed_case_ids = {(r['category_num'], r['case_id']) for r in existing_results}
    print(f"Loaded {len(existing_results)} existing results")

all_results = list(existing_results)

for cat_num in CATEGORIES:
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        print(f"No benchmark file found for category {cat_num}")
        continue
    cat_file = files[0]
    cat_name = os.path.basename(cat_file).replace('.json', '')
    test_cases = load_benchmark(cat_file)
    print(f"\n{'='*60}")
    print(f"Category {cat_num}: {cat_name} ({len(test_cases)} cases)")
    print(f"{'='*60}")

    for i, test_case in enumerate(test_cases):
        case_id = test_case.get('id', f'Q{i+1:04d}')

        # Skip if already done
        if (cat_num, case_id) in completed_case_ids:
            print(f"  [{i+1}/{len(test_cases)}] {case_id}... SKIP (already done)")
            continue

        input_text = test_case.get('input', '')
        print(f"  [{i+1}/{len(test_cases)}] {case_id}...", end=" ", flush=True)
        session_id = f"agent{AGENT_ID}_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
        start_time = time.time()
        response = send_message(input_text, session_id, timeout=90)
        response_time = time.time() - start_time

        # Check if screenshot already exists
        screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
        if not os.path.exists(screenshot_path):
            screenshot_path = None

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
            'response_time': response_time, 'screenshot': screenshot_path,
            'timestamp': datetime.now().isoformat()
        }
        all_results.append(result)
        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{response_time:.1f}s]")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")

    # Save after each category
    with open(RESULTS_FILE, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"  Category {cat_num} saved ({len(all_results)} total results)")

total = len(all_results)
passed = sum(1 for r in all_results if r['passed'])
print(f"\n{'='*60}")
print(f"AGENT {AGENT_ID} API Results Complete")
print(f"Total: {total} | Passed: {passed} | Failed: {total - passed}")
print(f"Pass Rate: {passed/total*100:.1f}%" if total > 0 else "No tests")
