#!/usr/bin/env python3
"""Lightweight agent runner - runs tests one category at a time with memory management."""
import json, glob, os, sys, time, gc
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from robust_scheduler import (
    load_state, save_state, get_completed_cases, load_benchmark,
    send_message, score_response, analyze_failure
)

SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"

def take_screenshot_lightweight(case_id, cat_num):
    """Take screenshot with strict memory management."""
    screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
        return screenshot_path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto("http://localhost:8080", timeout=30000)
            page.wait_for_load_state('networkidle', timeout=15000)
            time.sleep(2)
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
        del browser
        gc.collect()
        return screenshot_path
    except Exception as e:
        print(f"    Screenshot error: {e}")
        try:
            browser.close()
        except:
            pass
        gc.collect()
        return None

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

        session_id = f"agent{agent_id}_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
        start_time = time.time()
        response = send_message(input_text, session_id, timeout=90)
        response_time = time.time() - start_time

        # Take screenshot
        screenshot_path = take_screenshot_lightweight(case_id, cat_num)

        total_score, dimension_scores = score_response(response, test_case)
        pass_threshold = test_case.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dimension_scores['safety'] > 0
        root_cause = root_cause_detail = None
        if not passed:
            root_cause, root_cause_detail = analyze_failure(response, test_case)

        result = {
            'case_id': case_id, 'category': cat_name, 'category_num': cat_num,
            'input': input_text, 'response': response[:1500], 'response_length': len(response),
            'total_score': total_score, 'dimension_scores': dimension_scores, 'passed': passed,
            'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
            'response_time': response_time, 'screenshot': screenshot_path,
        }
        results.append(result)
        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{response_time:.1f}s]")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")

        state["completed"][f"{cat_num}_{case_id}"] = True
        save_state(state)

    return results

if __name__ == "__main__":
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    categories = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else [30, 32, 33, 34, 35, 36]

    state = load_state()
    print(f"Agent {agent_id} - Running categories: {categories}")

    all_results = []
    for cat_num in categories:
        results = run_category(cat_num, agent_id, state)
        all_results.extend(results)
        gc.collect()
        print(f"  Category {cat_num} done: {sum(1 for r in results if r['passed'])}/{len(results)} passed")

    # Summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\nAgent {agent_id} COMPLETE: {passed}/{total} passed ({passed/total*100:.1f}%)" if total > 0 else "\nNo tests run")
