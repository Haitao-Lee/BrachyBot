#!/usr/bin/env python3
"""
Sequential runner for remaining benchmark cases.
Runs one case at a time with very long timeout and detailed logging.
"""
import json, os, sys, time, glob, requests, traceback
from datetime import datetime

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
LOG_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent1_seq.log"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=10)
        return r.status_code == 200
    except:
        return False

def wait_server(timeout=600):
    start = time.time()
    while time.time() - start < timeout:
        if check_server():
            return True
        log("  Server offline, waiting 10s...")
        time.sleep(10)
    return False

def load_benchmark(cat_num):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return []
    with open(files[0], 'r') as f:
        data = json.load(f)
    return data.get('cases', data) if isinstance(data, dict) else data

def get_completed(cat_num):
    completed = set()
    for fp in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        bn = os.path.basename(fp)
        cid = bn.replace(f"{cat_num:02d}_", "").replace(".png", "")
        completed.add(cid)
    return completed

def send_message(text, session_id, timeout=300):
    """Send with very long timeout and up to 5 retries."""
    for attempt in range(5):
        try:
            if not check_server():
                log("  Server offline, waiting...")
                if not wait_server(120):
                    return "Error: Server unavailable"
            payload = {
                "message": text,
                "clear_context": True,
                "session_id": session_id,
                "stream": False
            }
            r = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            data = r.json()
            return data.get('response', '')
        except requests.exceptions.Timeout:
            log(f"    Timeout attempt {attempt+1}/5 (timeout={timeout}s)")
            time.sleep(10)
        except Exception as e:
            log(f"    Error attempt {attempt+1}/5: {e}")
            time.sleep(10)
    return "Error: All 5 retries failed"

def take_screenshot(case_id, cat_num):
    path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=60000, wait_until='domcontentloaded')
            time.sleep(5)
            page.screenshot(path=path, full_page=True)
            browser.close()
        return path
    except Exception as e:
        log(f"    Screenshot error: {e}")
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
    return 'wrong_answer', 'Response does not meet expectations'

def run_cat(cat_num, agent_id):
    cases = load_benchmark(cat_num)
    completed = get_completed(cat_num)
    missing = [c for c in cases if c.get('id', '') not in completed]

    if not missing:
        log(f"Category {cat_num}: All {len(cases)} complete!")
        return []

    log(f"Category {cat_num}: {len(cases)} total, {len(completed)} done, {len(missing)} remaining")
    results = []
    for i, tc in enumerate(missing):
        case_id = tc.get('id', f'Q{i+1:04d}')
        input_text = tc.get('input', '')

        log(f"  [{i+1}/{len(missing)}] {case_id}...")
        session_id = f"agent{agent_id}_cat{cat_num:02d}_{case_id}_{int(time.time()*1000)}"

        start = time.time()
        response = send_message(input_text, session_id, timeout=300)
        elapsed = time.time() - start

        screenshot = take_screenshot(case_id, cat_num)
        total_score, dim_scores = score_response(response, tc)
        threshold = tc.get('pass_threshold', 0.6)
        passed = total_score >= threshold and dim_scores['safety'] > 0

        root_cause = None
        root_detail = None
        if not passed:
            root_cause, root_detail = analyze_failure(response, tc)

        result = {
            'case_id': case_id, 'category_num': cat_num,
            'input': input_text, 'response': response[:1500],
            'response_length': len(response), 'total_score': total_score,
            'dimension_scores': dim_scores, 'passed': passed,
            'root_cause': root_cause, 'root_cause_detail': root_detail,
            'response_time': elapsed, 'screenshot': screenshot,
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)

        status = "PASS" if passed else "FAIL"
        log(f"    {status} ({total_score:.2f}) [{elapsed:.1f}s] resp_len={len(response)}")
        if root_cause:
            log(f"    -> {root_cause}: {root_detail}")

    cat_passed = sum(1 for r in results if r['passed'])
    log(f"Category {cat_num} complete: {cat_passed}/{len(results)} passed")
    return results

def generate_report(all_results, agent_id):
    report_file = f"{REPORT_DIR}/agent{agent_id}_remaining_report.md"
    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])

    cats = {}
    for r in all_results:
        cn = r['category_num']
        if cn not in cats:
            cats[cn] = []
        cats[cn].append(r)

    with open(report_file, 'w') as f:
        f.write(f"# Agent {agent_id} Remaining Cases Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"## Summary\n\n")
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Total | {total} |\n| Passed | {passed} |\n| Failed | {total-passed} |\n")
        f.write(f"| Rate | {passed/total*100:.1f}% |\n\n" if total else "")

        f.write("## Category Breakdown\n\n")
        f.write("| Cat | Cases | Passed | Failed | Rate |\n|-----|-------|--------|--------|------|\n")
        for cn in sorted(cats.keys()):
            cr = cats[cn]
            cp = sum(1 for r in cr if r['passed'])
            f.write(f"| {cn:02d} | {len(cr)} | {cp} | {len(cr)-cp} | {cp/len(cr)*100:.0f}% |\n")

        f.write("\n## Results\n\n")
        for r in all_results:
            s = "PASS" if r['passed'] else "FAIL"
            f.write(f"### [{s}] Cat {r['category_num']:02d} {r['case_id']}\n")
            f.write(f"- **Input:** {r['input'][:200]}\n")
            f.write(f"- **Score:** {r['total_score']:.2f} | Time: {r['response_time']:.1f}s\n")
            if r['root_cause']:
                f.write(f"- **Failure:** {r['root_cause']}\n")
            f.write("\n")

    log(f"Report: {report_file}")
    return report_file

if __name__ == "__main__":
    agent_id = 1
    cat_nums = [2, 7, 9]

    # Clear log
    with open(LOG_FILE, 'w') as f:
        f.write("")

    log("=" * 60)
    log(f"AGENT {agent_id} - SEQUENTIAL REMAINING RUNNER")
    log("=" * 60)

    if not check_server():
        log("Server offline, waiting...")
        if not wait_server(300):
            log("Cannot continue without server")
            sys.exit(1)

    all_results = []
    for cat_num in cat_nums:
        try:
            results = run_cat(cat_num, agent_id)
            all_results.extend(results)
        except Exception as e:
            log(f"ERROR in category {cat_num}: {e}")
            traceback.print_exc()

    if all_results:
        generate_report(all_results, agent_id)

    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    log(f"\n{'='*60}")
    log(f"COMPLETE: {passed}/{total} passed")
    log(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
