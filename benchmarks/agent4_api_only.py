#!/usr/bin/env python3
"""API-only runner - no screenshots, minimal memory footprint."""
import json, glob, os, sys, time, gc, tracemalloc
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from robust_scheduler import (
    load_state, save_state, get_completed_cases, load_benchmark,
    send_message, score_response, analyze_failure
)

BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"

def run_category(cat_num, agent_id, state):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return []
    test_cases = load_benchmark(files[0])
    completed_cases = get_completed_cases(cat_num)
    remaining = [tc for tc in test_cases if tc.get('id', '') not in completed_cases]
    cat_name = os.path.basename(files[0]).replace('.json', '')

    print(f"\nCategory {cat_num} ({cat_name}): {len(remaining)} remaining of {len(test_cases)}")
    if not remaining:
        print("  All done!")
        return []

    results = []
    for i, test_case in enumerate(remaining):
        case_id = test_case.get('id', f'Q{i+1:04d}')
        input_text = test_case.get('input', '')
        print(f"  [{i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

        session_id = f"agent{agent_id}_{cat_num:02d}_{case_id}_{int(time.time())}"
        start_time = time.time()
        response = send_message(input_text, session_id, timeout=120)
        response_time = time.time() - start_time

        total_score, dimension_scores = score_response(response, test_case)
        pass_threshold = test_case.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dimension_scores['safety'] > 0
        root_cause = root_cause_detail = None
        if not passed:
            root_cause, root_cause_detail = analyze_failure(response, test_case)

        result = {
            'case_id': case_id, 'category': cat_name, 'category_num': cat_num,
            'input': input_text, 'response': response[:2000], 'response_length': len(response),
            'total_score': total_score, 'dimension_scores': dimension_scores, 'passed': passed,
            'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
            'response_time': response_time, 'screenshot': None,
        }
        results.append(result)
        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{response_time:.1f}s]")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")

        state["completed"][f"{cat_num}_{case_id}"] = True
        save_state(state)
        gc.collect()

    return results

if __name__ == "__main__":
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    categories = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else []

    state = load_state()
    print(f"Agent {agent_id} API-ONLY Runner - Categories: {categories}")

    all_results = []
    for cat_num in categories:
        results = run_category(cat_num, agent_id, state)
        all_results.extend(results)
        print(f"  Category {cat_num} done: {sum(1 for r in results if r['passed'])}/{len(results)} passed")

    # Save results as JSON for later report generation
    results_file = f"/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent{agent_id}_results.json"
    with open(results_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\nAgent {agent_id} COMPLETE: {passed}/{total} passed ({passed/total*100:.1f}%)" if total > 0 else "\nNo tests run")
    print(f"Results saved to: {results_file}")
