#!/usr/bin/env python3
"""
Standalone Agent 4 Runner - handles slow LLM responses with generous timeouts.
"""
import json, os, sys, time, glob, requests
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
STATE_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/scheduler_state.json"
API_TIMEOUT = 600  # 10 minutes per request
AGENT_ID = 4

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code == 200
    except:
        return False

def wait_for_server(timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        if check_server():
            return True
        time.sleep(5)
    return False

def load_benchmark(cat_num):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return None, []
    with open(files[0], 'r') as f:
        data = json.load(f)
    name = os.path.basename(files[0]).replace('.json', '')
    cases = data.get('cases', data) if isinstance(data, dict) else data
    return name, cases

def get_completed(cat_num):
    done = set()
    for f in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        if os.path.getsize(f) > 1000:
            cid = os.path.basename(f).replace(f"{cat_num:02d}_", "").replace(".png", "")
            done.add(cid)
    return done

def send_message(text, session_id):
    for attempt in range(3):
        try:
            if not check_server():
                print("    Server offline, waiting...", flush=True)
                wait_for_server(60)
            r = requests.post(f"{BASE_URL}/api/chat", json={
                "message": text,
                "clear_context": True,
                "session_id": session_id,
                "stream": False
            }, timeout=API_TIMEOUT)
            data = r.json()
            if "error" in data:
                return f"Error: {data['error']}"
            return data.get("response", "")
        except requests.exceptions.Timeout:
            print(f"    Timeout attempt {attempt+1}/3", flush=True)
            if attempt < 2:
                time.sleep(5)
        except Exception as e:
            print(f"    Error attempt {attempt+1}/3: {e}", flush=True)
            if attempt < 2:
                time.sleep(5)
    return "Error: All attempts failed"

def take_screenshot(case_id, cat_num):
    screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
        return screenshot_path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
            time.sleep(3)
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
        return screenshot_path
    except Exception as e:
        print(f"    Screenshot failed: {e}", flush=True)
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

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {"completed": {}, "failed": {}, "in_progress": {}}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def run_category(cat_num, state):
    cat_name, cases = load_benchmark(cat_num)
    if cat_name is None:
        print(f"No benchmark file for category {cat_num}")
        return []

    completed = get_completed(cat_num)
    remaining = [tc for tc in cases if tc.get('id', '') not in completed]

    print(f"\n{'='*60}")
    print(f"Category {cat_num}: {cat_name}")
    print(f"Total: {len(cases)} | Completed: {len(completed)} | Remaining: {len(remaining)}")
    print(f"{'='*60}", flush=True)

    if not remaining:
        print("  All cases already completed!")
        return []

    results = []
    for i, tc in enumerate(remaining):
        case_id = tc.get('id', f'Q{i+1:04d}')
        input_text = tc.get('input', '')
        print(f"  [{i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

        session_id = f"agent{AGENT_ID}_{cat_num:02d}_{case_id}_{int(time.time()*1000)}"
        t0 = time.time()
        response = send_message(input_text, session_id)
        response_time = time.time() - t0

        screenshot_path = take_screenshot(case_id, cat_num)
        total_score, dim_scores = score_response(response, tc)
        pass_threshold = tc.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dim_scores['safety'] > 0

        root_cause = root_cause_detail = None
        if not passed:
            root_cause, root_cause_detail = analyze_failure(response, tc)

        result = {
            'case_id': case_id, 'category': cat_name, 'category_num': cat_num,
            'input': input_text, 'response': response[:1500], 'response_length': len(response),
            'total_score': total_score, 'dimension_scores': dim_scores, 'passed': passed,
            'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
            'response_time': response_time, 'screenshot': screenshot_path,
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{response_time:.1f}s]", flush=True)
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}", flush=True)

        state["completed"][f"{cat_num}_{case_id}"] = True
        save_state(state)

    return results

if __name__ == "__main__":
    categories = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [23, 22, 19, 7]

    print("=" * 60)
    print(f"AGENT {AGENT_ID} STANDALONE RUNNER")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Categories: {categories}")
    print(f"API Timeout: {API_TIMEOUT}s per request")
    print(flush=True)

    if not check_server():
        print("Server offline, waiting...")
        if not wait_for_server():
            print("Cannot continue without server")
            sys.exit(1)

    state = load_state()
    all_results = []

    for cat_num in categories:
        results = run_category(cat_num, state)
        all_results.extend(results)
        passed = sum(1 for r in results if r['passed'])
        total = len(results)
        print(f"\n  Category {cat_num} done: {passed}/{total} passed", flush=True)

    # Summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\n{'='*60}")
    print(f"AGENT {AGENT_ID} COMPLETE")
    print(f"Total: {total} | Passed: {passed} | Failed: {total - passed}")
    print(f"Pass Rate: {passed/total*100:.1f}%" if total > 0 else "No tests")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
