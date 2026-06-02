#!/usr/bin/env python3
"""
Focused runner for categories 19-27 with:
- domcontentloaded for screenshots (fixes hang)
- Skips already-completed cases (by screenshot existence)
- 120s timeout per request
- Progress output
"""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
RESULT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def get_completed_ids(cat_num):
    """Get IDs of cases with existing screenshots."""
    completed = set()
    for f in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        basename = os.path.basename(f)
        case_id = basename.replace(f"{cat_num:02d}_", "").replace(".png", "")
        if os.path.getsize(f) > 1000:
            completed.add(case_id)
    return completed

def load_cases(cat_num):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return []
    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('cases', data) if isinstance(data, dict) else data

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code == 200
    except:
        return False

def restart_server():
    """Kill and restart the web server."""
    import subprocess
    os.system("pkill -f 'web/server.py' 2>/dev/null")
    time.sleep(2)
    subprocess.Popen(
        ["python3", "web/server.py"],
        cwd="/home/lht/snap/brachyplan/BrachyBot",
        stdout=open("/tmp/server_run.log", "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True
    )
    # Wait for server to come up
    for _ in range(30):
        time.sleep(2)
        if check_server():
            print("      [server restarted]", flush=True)
            return True
    print("      [server restart failed]", flush=True)
    return False

def send_message(text, session_id, timeout=120, retries=2):
    for attempt in range(retries):
        try:
            r = requests.post(f"{BASE_URL}/api/chat", json={
                "message": text, "clear_context": True,
                "session_id": session_id, "stream": False
            }, timeout=timeout)
            return r.json().get('response', '')
        except Exception as e:
            if attempt < retries - 1:
                # Check if server died
                if not check_server():
                    print("      [server down, restarting...]", flush=True)
                    restart_server()
                else:
                    time.sleep(3)
            else:
                return f"Error: {e}"

def take_screenshot(case_id, cat_num):
    screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
        return screenshot_path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
            time.sleep(3)
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
        return screenshot_path
    except Exception as e:
        print(f"      [screenshot failed: {e}]", flush=True)
        return None

def score_response(response, test_case):
    scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
    expected = test_case.get('expected_keywords', [])
    if expected:
        if isinstance(expected, dict):
            tw = sum(v.get('weight', 0.1) for v in expected.values())
            mw = sum(v.get('weight', 0.1) for kw, v in expected.items() if kw.lower() in response.lower())
            scores['keyword'] = mw / tw if tw > 0 else 0
        else:
            m = sum(1 for kw in expected if kw.lower() in response.lower())
            scores['keyword'] = m / len(expected) if expected else 0
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
            return 'hallucination', f'Contains uncertainty phrase: "{kw}"'
    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            return 'safety_leak', f'Contains forbidden keyword: "{kw}"'
    if len(response) < 100:
        return 'too_brief', f'Response too short ({len(response)} chars)'
    if len(response) > 5000:
        return 'too_verbose', f'Response too long ({len(response)} chars)'
    expected = test_case.get('expected_keywords', [])
    if expected:
        matched = sum(1 for kw in expected if kw.lower() in response.lower())
        if matched == 0:
            return 'keyword_missing', 'No expected keywords found'
    return 'wrong_answer', 'Response does not meet expectations'

def run_category(cat_num, agent_id=3):
    cases = load_cases(cat_num)
    if not cases:
        print(f"  No benchmark file for category {cat_num}", flush=True)
        return []

    completed = get_completed_ids(cat_num)
    remaining = [tc for tc in cases if tc.get('id', '') not in completed]

    cat_name = os.path.basename(glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")[0]).replace('.json', '')
    print(f"\n{'='*60}", flush=True)
    print(f"Category {cat_num}: {cat_name}", flush=True)
    print(f"Total: {len(cases)} | Completed: {len(completed)} | Remaining: {len(remaining)}", flush=True)
    print(f"{'='*60}", flush=True)

    if not remaining:
        print("  All cases already completed!", flush=True)
        return []

    results = []
    for i, tc in enumerate(remaining):
        case_id = tc.get('id', f'Q{i+1:04d}')
        inp = tc.get('input', '')

        print(f"  [{i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

        # Health check before each request
        if not check_server():
            print("[server down, restarting...]", end=" ", flush=True)
            if not restart_server():
                print("SKIPPED (server down)", flush=True)
                continue

        sid = f"agent{agent_id}_{cat_num:02d}_{case_id}_{int(time.time()*1000)}"
        t0 = time.time()
        response = send_message(inp, sid, timeout=120)
        rt = time.time() - t0

        # Score
        total, dims = score_response(response, tc)
        passed = total >= tc.get('pass_threshold', 0.6) and dims['safety'] > 0
        rc, rcd = (None, None)
        if not passed:
            rc, rcd = analyze_failure(response, tc)

        result = {
            'case_id': case_id, 'category': cat_name, 'category_num': cat_num,
            'input': inp, 'response': response[:2000], 'response_length': len(response),
            'total_score': total, 'dimension_scores': dims, 'passed': passed,
            'root_cause': rc, 'root_cause_detail': rcd,
            'response_time': rt, 'screenshot': f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png",
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total:.2f}) [{rt:.1f}s]", flush=True)
        if rc:
            print(f"    -> {rc}: {rcd}", flush=True)

        # Save per-case result
        with open(f"{RESULT_DIR}/{cat_num:02d}_{case_id}.json", 'w') as f:
            json.dump(result, f, indent=2)

    # Save category results
    cat_file = f"{RESULT_DIR}/agent3_cat{cat_num:02d}.json"
    with open(cat_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    # Take screenshots in batch for new results
    print(f"  Taking screenshots for {len(results)} new cases...", flush=True)
    for r in results:
        if r.get('screenshot') and not os.path.exists(r['screenshot']):
            take_screenshot(r['case_id'], cat_num)

    passed_n = sum(1 for r in results if r['passed'])
    print(f"\n  Category {cat_num} complete: {passed_n}/{len(results)} passed", flush=True)
    return results

if __name__ == "__main__":
    cats = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [19, 20, 21, 22, 23, 24, 25, 26, 27]

    print("=" * 60, flush=True)
    print(f"RUNNER - Categories {cats}", flush=True)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("=" * 60, flush=True)

    # Server check
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        print(f"Server: ONLINE ({r.status_code})", flush=True)
    except:
        print("Server: OFFLINE", flush=True)
        sys.exit(1)

    all_results = []
    for cat_num in cats:
        results = run_category(cat_num)
        all_results.extend(results)

    # Summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\n{'='*60}", flush=True)
    print(f"COMPLETE: {passed}/{total} passed ({passed/total*100:.1f}%)" if total else "No tests", flush=True)
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
