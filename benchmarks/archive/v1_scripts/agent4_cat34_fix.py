#!/usr/bin/env python3
"""
Agent 4 - Category 34 Multi-Turn fix
Handles the multi-turn test case structure where input is in turns[0].input
"""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def check_server_status():
    try:
        response = requests.get(f"{BASE_URL}/", timeout=5)
        return response.status_code == 200
    except:
        return False

def send_message(text, session_id, timeout=120, retries=3):
    for attempt in range(retries):
        try:
            if not check_server_status():
                print(f"    Server offline, waiting...")
                time.sleep(30)
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
            print(f"    Timeout on attempt {attempt + 1}/{retries}")
            if attempt < retries - 1:
                time.sleep(5)
        except Exception as e:
            print(f"    Error on attempt {attempt + 1}/{retries}: {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return f"Error: All {retries} attempts failed"

def take_screenshot_with_input(case_id, cat_num, input_text, retries=2):
    screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
        return screenshot_path
    for attempt in range(retries):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})
                page.goto(BASE_URL, timeout=30000, wait_until='networkidle')
                time.sleep(2)
                input_selector = '#chatInput'
                page.wait_for_selector(input_selector, timeout=10000)
                page.fill(input_selector, input_text)
                time.sleep(0.5)
                send_button = page.locator('.chat-send')
                send_button.click()
                page.wait_for_selector('.chat-msg.bot', timeout=60000)
                time.sleep(3)
                page.wait_for_function(
                    """() => {
                        const msgs = document.querySelectorAll('.chat-msg.bot');
                        const lastMsg = msgs[msgs.length - 1];
                        return lastMsg && lastMsg.textContent.length > 50;
                    }""",
                    timeout=60000
                )
                time.sleep(2)
                page.screenshot(path=screenshot_path, full_page=True)
                browser.close()
            return screenshot_path
        except Exception as e:
            print(f"    Screenshot failed on attempt {attempt + 1}: {e}")
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

def run_cat34():
    cat_num = 34
    agent_id = 4

    with open(f"{BENCHMARK_DIR}/34_multi_turn.json", 'r') as f:
        data = json.load(f)
    cases = data.get('cases', data)

    # Check existing screenshots
    completed = []
    for f_path in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        basename = os.path.basename(f_path)
        case_id = basename.replace(f"{cat_num:02d}_", "").replace(".png", "")
        completed.append(case_id)
    remaining = [tc for tc in cases if tc.get('id', '') not in completed]

    print(f"\nCategory 34: {len(cases)} total | {len(completed)} completed | {len(remaining)} remaining")

    results = []
    for i, test_case in enumerate(remaining):
        case_id = test_case.get('id', f'MT{i+1:03d}')

        # Extract input from turns array - first turn's input
        turns = test_case.get('turns', [])
        if turns:
            input_text = turns[0].get('input', '')
        else:
            input_text = test_case.get('input', '')

        if not input_text:
            print(f"  [{i+1}/{len(remaining)}] {case_id}: SKIP (no input)")
            continue

        print(f"  [{i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

        session_id = f"agent{agent_id}_cat34_{case_id}_{int(time.time() * 1000)}"
        start_time = time.time()
        response = send_message(input_text, session_id, timeout=180)
        response_time = time.time() - start_time

        screenshot_path = take_screenshot_with_input(case_id, cat_num, input_text)

        total_score, dimension_scores = score_response(response, test_case)
        pass_threshold = test_case.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dimension_scores['safety'] > 0

        root_cause = None
        root_cause_detail = None
        if not passed:
            root_cause, root_cause_detail = analyze_failure(response, test_case)

        result = {
            'case_id': case_id, 'category': '34_multi_turn', 'category_num': cat_num,
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
    if not check_server_status():
        print("Server is offline!")
        sys.exit(1)

    print("=" * 60)
    print("AGENT 4 - Category 34 Multi-Turn Fix")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = run_cat34()

    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    print(f"\nCategory 34 Complete: {passed}/{total} passed")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Save results to JSON
    output_file = f"{REPORT_DIR}/agent4_cat34_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Results saved: {output_file}")
