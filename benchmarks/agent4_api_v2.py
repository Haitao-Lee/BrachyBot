#!/usr/bin/env python3
"""API runner v2 - handles multi-turn, single-turn, and all test formats."""
import json, glob, os, sys, time, gc
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from robust_scheduler import (
    load_state, save_state, get_completed_cases, load_benchmark,
    score_response, analyze_failure
)

BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
BASE_URL = "http://localhost:8080"

def send_message(text, session_id, timeout=120):
    import requests
    for attempt in range(3):
        try:
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
            if attempt < 2:
                time.sleep(3)
        except Exception as e:
            print(f"    Error attempt {attempt+1}/3: {e}")
            if attempt < 2:
                time.sleep(3)
    return ""

def handle_multiturn(test_case, session_id):
    """Handle multi-turn test by sending all turns sequentially."""
    turns = test_case.get('turns', [])
    combined_response = ""
    all_expected = []
    all_forbidden = []

    for turn in turns:
        turn_input = turn.get('input', '')
        if not turn_input:
            continue
        # Send without clearing context for multi-turn continuity
        import requests
        try:
            payload = {
                "message": turn_input,
                "clear_context": False,
                "session_id": session_id,
                "stream": False
            }
            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=120)
            data = response.json()
            turn_response = data.get('response', '')
            combined_response += "\n" + turn_response
        except Exception as e:
            print(f"    Turn error: {e}")
            turn_response = ""
            combined_response += "\n"

        # Collect expected keywords from each turn
        ek = turn.get('expected_keywords', [])
        if ek:
            all_expected.extend(ek)
        fk = turn.get('forbidden_keywords', [])
        if fk:
            all_forbidden.extend(fk)

    # Build a composite test case for scoring
    composite = {
        'expected_keywords': list(set(all_expected)),
        'forbidden_keywords': list(set(all_forbidden)),
        'pass_threshold': test_case.get('pass_threshold', 0.6),
    }
    return combined_response.strip(), composite

def take_screenshot_lightweight(case_id, cat_num):
    screenshot_path = f"/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots/{cat_num:02d}_{case_id}.png"
    if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
        return screenshot_path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=30000)
            page.wait_for_load_state('networkidle', timeout=15000)
            time.sleep(2)
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
        gc.collect()
        return screenshot_path
    except Exception as e:
        print(f"    Screenshot error: {e}")
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
        is_multiturn = 'turns' in test_case and 'input' not in test_case
        print(f"  [{i+1}/{len(remaining)}] {case_id} ({'multi-turn' if is_multiturn else 'single'})...", end=" ", flush=True)

        session_id = f"agent{agent_id}_{cat_num:02d}_{case_id}_{int(time.time())}"
        start_time = time.time()

        if is_multiturn:
            # Multi-turn: send each turn, combine responses
            combined_response, scoring_case = handle_multiturn(test_case, session_id)
            input_text = " | ".join([t.get('input', '') for t in test_case.get('turns', [])])
            response = combined_response
        else:
            input_text = test_case.get('input', '')
            response = send_message(input_text, session_id, timeout=120)
            scoring_case = test_case

        response_time = time.time() - start_time

        # Screenshot (lightweight)
        screenshot_path = take_screenshot_lightweight(case_id, cat_num)

        # Score
        total_score, dimension_scores = score_response(response, scoring_case)
        pass_threshold = test_case.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dimension_scores['safety'] > 0
        root_cause = root_cause_detail = None
        if not passed:
            root_cause, root_cause_detail = analyze_failure(response, scoring_case)

        result = {
            'case_id': case_id, 'category': cat_name, 'category_num': cat_num,
            'input': input_text, 'response': response[:2000], 'response_length': len(response),
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
        gc.collect()

    return results

if __name__ == "__main__":
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    categories = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else []

    state = load_state()
    print(f"Agent {agent_id} API Runner v2 - Categories: {categories}")

    all_results = []
    for cat_num in categories:
        results = run_category(cat_num, agent_id, state)
        all_results.extend(results)
        print(f"  Category {cat_num} done: {sum(1 for r in results if r['passed'])}/{len(results)} passed")

    # Save results
    results_file = f"/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent{agent_id}_results.json"
    with open(results_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\nAgent {agent_id} COMPLETE: {passed}/{total} passed ({passed/total*100:.1f}%)" if total > 0 else "\nNo tests run")
    print(f"Results saved to: {results_file}")
