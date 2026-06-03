#!/usr/bin/env python3
"""
Agent 4 help runner - runs specific categories to help with incomplete ones.
No screenshots to avoid OOM.
"""
import sys, os, json, time, glob
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unified_agent import load_benchmark, send_message, score_response, analyze_failure, BENCHMARK_DIR, REPORT_DIR

AGENT_ID = 4
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"

def run_help_category(cat_num):
    """Run all missing cases for a category."""
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        print(f"No benchmark file found for category {cat_num}")
        return []

    cat_file = files[0]
    cat_name = os.path.basename(cat_file).replace('.json', '')
    test_cases = load_benchmark(cat_file)

    # Find which cases already have screenshots (done)
    done_ids = set()
    for tc in test_cases:
        cid = tc.get('id', 'unknown')
        if os.path.exists(f"{SCREENSHOT_DIR}/{cat_num:02d}_{cid}.png"):
            done_ids.add(cid)

    remaining = [tc for tc in test_cases if tc.get('id') not in done_ids]
    print(f"\nCategory {cat_num}: {cat_name} ({len(test_cases)} total, {len(done_ids)} done, {len(remaining)} remaining)")

    if not remaining:
        print(f"  All cases already have screenshots!")
        return []

    results = []
    for i, test_case in enumerate(remaining):
        case_id = test_case.get('id', f'Q{i+1:04d}')
        input_text = test_case.get('input', '')
        print(f"  [{i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)
        session_id = f"agent{AGENT_ID}_help_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
        start_time = time.time()
        response = send_message(input_text, session_id, timeout=90)
        response_time = time.time() - start_time

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
        results.append(result)
        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{response_time:.1f}s]")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")
    return results

if __name__ == "__main__":
    cats = [int(x) for x in sys.argv[1:]]
    if not cats:
        print("Usage: python agent4_help_runner.py <cat1> <cat2> ...")
        sys.exit(1)

    all_results = []
    for cat_num in cats:
        results = run_help_category(cat_num)
        all_results.extend(results)

    # Save to help results file
    help_file = f"{REPORT_DIR}/agent4_help_results.json"
    with open(help_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\nHelp complete: {total} cases, {passed} passed ({passed/total*100:.1f}%)" if total > 0 else "\nNo cases run")
    print(f"Results: {help_file}")
