#!/usr/bin/env python3
"""Run missing benchmark cases for specific categories."""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code == 200
    except:
        return False

def wait_server(timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        if check_server():
            return True
        print(".", end="", flush=True)
        time.sleep(5)
    return False

def send_message(text, session_id, timeout=240):
    for attempt in range(3):
        try:
            if not check_server():
                print("[server down, waiting...]", end=" ", flush=True)
                if not wait_server(60):
                    return "Error: server offline"
            r = requests.post(f"{BASE_URL}/api/chat", json={
                "message": text, "clear_context": True,
                "session_id": session_id, "stream": False
            }, timeout=timeout)
            return r.json().get('response', '')
        except requests.exceptions.Timeout:
            print(f"[timeout {attempt+1}]", end=" ", flush=True)
            time.sleep(5)
        except Exception as e:
            print(f"[err {attempt+1}: {e}]", end=" ", flush=True)
            time.sleep(5)
    return "Error: all retries failed"

def take_screenshot(case_id, cat_num):
    path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
            time.sleep(3)
            page.screenshot(path=path, full_page=True)
            page.close()
            browser.close()
        return path
    except Exception as e:
        print(f"[screenshot error: {e}]", end=" ", flush=True)
        return None

def get_done_ids(cat_num):
    done = set()
    for f in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        if os.path.getsize(f) > 1000:
            bn = os.path.basename(f).replace(f"{cat_num:02d}_", "").replace(".png", "")
            done.add(bn)
    return done

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

def run_category(cat_num):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        print(f"No benchmark file for category {cat_num}")
        return []

    with open(files[0]) as f:
        data = json.load(f)
    cases = data.get('cases', data) if isinstance(data, dict) else data
    done_ids = get_done_ids(cat_num)
    remaining = [tc for tc in cases if tc.get('id', '') not in done_ids]

    print(f"\nCategory {cat_num}: {len(cases)} total, {len(done_ids)} done, {len(remaining)} remaining")
    if not remaining:
        print("  All complete!")
        return []

    results = []
    for i, tc in enumerate(remaining):
        cid = tc.get('id', f'Q{i+1:04d}')
        inp = tc.get('input', '')
        print(f"  [{i+1}/{len(remaining)}] {cid}...", end=" ", flush=True)

        if not check_server():
            print("[waiting for server]", end=" ", flush=True)
            if not wait_server(120):
                print("SKIP (server offline)")
                continue

        sid = f"run2_{cat_num:02d}_{cid}_{int(time.time()*1000)}"
        t0 = time.time()
        resp = send_message(inp, sid, timeout=240)
        dt = time.time() - t0

        # Take screenshot
        screenshot = take_screenshot(cid, cat_num)
        print(f"[shot]", end=" ", flush=True) if screenshot else print(f"[no shot]", end=" ", flush=True)

        # Score
        total_score, dim_scores = score_response(resp, tc)
        pass_threshold = tc.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dim_scores['safety'] > 0

        root_cause = root_cause_detail = None
        if not passed:
            root_cause, root_cause_detail = analyze_failure(resp, tc)

        result = {
            'case_id': cid, 'category_num': cat_num,
            'input': inp, 'response': resp[:1500], 'response_length': len(resp),
            'total_score': total_score, 'dimension_scores': dim_scores, 'passed': passed,
            'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
            'response_time': dt, 'screenshot': screenshot,
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)
        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{dt:.1f}s] len={len(resp)}")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")
        time.sleep(2)  # Pause between requests

    return results

def main():
    categories = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [12, 15, 18]
    agent_id = 2

    print("=" * 60)
    print(f"MISSING CASES RUNNER - Categories: {categories}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if not check_server():
        print("Server offline, waiting...")
        if not wait_server(120):
            print("Cannot continue without server")
            sys.exit(1)

    all_results = []
    for cat in categories:
        results = run_category(cat)
        all_results.extend(results)
        passed = sum(1 for r in results if r['passed'])
        print(f"  -> Category {cat}: {passed}/{len(results)} passed")

    # Save results
    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\n{'='*60}")
    print(f"COMPLETE: {passed}/{total} passed ({passed/total*100:.1f}%)" if total else "No tests run")

    # Save results JSON
    out_file = f"/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/run2_missing_results.json"
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"Results saved: {out_file}")

if __name__ == "__main__":
    main()
