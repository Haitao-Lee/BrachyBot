#!/usr/bin/env python3
"""Ultra-small batch runner - processes N cases at a time, then exits."""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
STATE_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/scheduler_state.json"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {"completed": {}, "failed": {}, "in_progress": {}}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def send_message(text, session_id, timeout=180):
    for attempt in range(2):
        try:
            payload = {"message": text, "clear_context": True, "session_id": session_id, "stream": False}
            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            return response.json().get('response', '')
        except Exception as e:
            if attempt == 0:
                time.sleep(3)
    return "Error: All attempts failed"

def take_screenshot(case_id, cat_num):
    path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
            time.sleep(2)
            page.screenshot(path=path, full_page=True)
            browser.close()
        return path
    except Exception as e:
        print(f"    Screenshot error: {e}")
        return None

def score_response(response, test_case):
    scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
    expected_keywords = test_case.get('expected_keywords', [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            tw = sum(v.get('weight', 0.1) for v in expected_keywords.values())
            mw = sum(v.get('weight', 0.1) for kw, v in expected_keywords.items() if kw.lower() in response.lower())
            scores['keyword'] = mw / tw if tw > 0 else 0
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
            return 'hallucination', f'Uncertainty: "{kw}"'
    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            return 'safety_leak', f'Forbidden: "{kw}"'
    if len(response) < 100:
        return 'too_brief', f'{len(response)} chars'
    if len(response) > 5000:
        return 'too_verbose', f'{len(response)} chars'
    ek = test_case.get('expected_keywords', [])
    if ek:
        matched = sum(1 for kw in ek if kw.lower() in response.lower())
        if matched == 0:
            return 'keyword_missing', 'No keywords found'
    return 'wrong_answer', 'Does not meet expectations'

def get_remaining(cat_num):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
        cases = data.get('cases', data) if isinstance(data, dict) else data
    completed = set()
    for f in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        bn = os.path.basename(f).replace(f"{cat_num:02d}_", "").replace(".png", "")
        completed.add(bn)
    return [tc for tc in cases if tc.get('id', '') not in completed], cases

if __name__ == "__main__":
    # Usage: python batch_runner.py <agent_id> <batch_size> <cat1> <cat2> ...
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    batch_size = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    categories = [int(x) for x in sys.argv[3:]] if len(sys.argv) > 3 else []

    state = load_state()
    total_run = 0

    for cat_num in categories:
        remaining, all_cases = get_remaining(cat_num)
        if not remaining:
            print(f"Cat {cat_num}: All done!")
            continue

        cat_name = os.path.basename(glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")[0]).replace('.json', '')
        to_process = remaining[:batch_size]
        print(f"\nCat {cat_num} ({cat_name}): {len(remaining)} remaining, processing {len(to_process)}")

        for i, tc in enumerate(to_process):
            case_id = tc.get('id', f'Q{i+1:04d}')
            input_text = tc.get('input', '')
            print(f"  [{i+1}/{len(to_process)}] {case_id}...", end=" ", flush=True)

            session_id = f"batch_agent{agent_id}_{cat_num:02d}_{case_id}_{int(time.time()*1000)}"
            start = time.time()
            response = send_message(input_text, session_id)
            rt = time.time() - start

            total_score, dim_scores = score_response(response, tc)
            passed = total_score >= tc.get('pass_threshold', 0.6) and dim_scores['safety'] > 0

            root_cause = root_cause_detail = None
            if not passed:
                root_cause, root_cause_detail = analyze_failure(response, tc)

            # Take screenshot
            screenshot_path = take_screenshot(case_id, cat_num)

            result = {
                'case_id': case_id, 'category': cat_name, 'category_num': cat_num,
                'input': input_text, 'response': response[:1500], 'response_length': len(response),
                'total_score': total_score, 'dimension_scores': dim_scores, 'passed': passed,
                'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
                'response_time': rt, 'screenshot': screenshot_path,
                'timestamp': datetime.now().isoformat()
            }

            status = "PASS" if passed else "FAIL"
            print(f"{status} ({total_score:.2f}) [{rt:.1f}s]")
            if root_cause:
                print(f"    -> {root_cause}: {root_cause_detail}")

            state["completed"][f"{cat_num}_{case_id}"] = True
            save_state(state)
            total_run += 1

        print(f"  Cat {cat_num} batch done.")

    print(f"\nTotal processed this run: {total_run}")
