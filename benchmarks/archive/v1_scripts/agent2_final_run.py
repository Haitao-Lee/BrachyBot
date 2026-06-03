#!/usr/bin/env python3
"""
Benchmark Agent 2 Final Runner - Categories 10-18
Resumable: skips already-completed cases from previous results.
Takes screenshots via Playwright subprocess isolation.
"""
import json, os, sys, time, glob, requests, subprocess
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
AGENT_ID = 2
RESULTS_FILE = f"{REPORT_DIR}/agent{AGENT_ID}_final_results.json"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def load_benchmark(category_file):
    with open(category_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if isinstance(data, dict) and 'cases' in data:
            return data['cases']
        elif isinstance(data, list):
            return data
        return []

def load_existing_results():
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE) as f:
                return json.load(f)
        except:
            pass
    return []

def save_results(results):
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2, default=str)

def check_server():
    try:
        resp = requests.post(f"{BASE_URL}/api/chat",
            json={"message":"ping","session_id":"health","stream":False},
            timeout=30)
        return resp.status_code == 200
    except:
        return False

def send_message(text, session_id, timeout=120):
    payload = {
        "message": text,
        "clear_context": True,
        "session_id": session_id,
        "stream": False
    }
    for attempt in range(3):
        try:
            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            data = response.json()
            return data.get('response', '')
        except requests.Timeout:
            if attempt < 2:
                time.sleep(3)
            else:
                return "Error: Request timed out"
        except requests.ConnectionError:
            if attempt < 2:
                time.sleep(5)
            else:
                return "Error: Connection refused"
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                return f"Error: {str(e)}"

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

def take_screenshot(case_id, cat_num):
    """Take screenshot via isolated subprocess."""
    screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(screenshot_path):
        return screenshot_path
    try:
        code = f'''
import sys
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={{'width': 1920, 'height': 1080}})
        page.goto("{BASE_URL}", wait_until="domcontentloaded", timeout=15000)
        import time; time.sleep(1)
        page.screenshot(path="{screenshot_path}", full_page=False)
        browser.close()
except Exception as e:
    print(f"SS_ERR: {{e}}", file=sys.stderr)
    sys.exit(1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True, text=True, timeout=25
        )
        if result.returncode == 0 and os.path.exists(screenshot_path):
            return screenshot_path
        return None
    except:
        return None

def run_all_categories():
    CATEGORIES = [10, 11, 12, 13, 14, 15, 16, 17, 18]

    # Load existing results for resumption
    existing = load_existing_results()
    completed_keys = set()
    for r in existing:
        completed_keys.add(f"{r['category_num']}_{r['case_id']}")

    print(f"Benchmark Agent {AGENT_ID} - Final Run (Resumable)")
    print(f"Categories: {CATEGORIES}")
    print(f"Previously completed: {len(completed_keys)} cases")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    sys.stdout.flush()

    # Check server
    if not check_server():
        print("ERROR: Server not responding at", BASE_URL)
        sys.exit(1)
    print("Server check: OK")
    sys.stdout.flush()

    all_results = list(existing)

    for cat_num in CATEGORIES:
        files = glob.glob(f"/home/lht/snap/brachyplan/BrachyBot/benchmarks/{cat_num:02d}_*.json")
        if not files:
            continue

        cat_file = files[0]
        cat_name = os.path.basename(cat_file).replace('.json', '')
        test_cases = load_benchmark(cat_file)

        if not test_cases:
            print(f"\nCategory {cat_num}: {cat_name} - 0 cases (skipping)")
            continue

        # Count how many we need to run
        remaining = []
        for i, tc in enumerate(test_cases):
            cid = tc.get('id', 'Q%04d' % (i+1))
            key = '%d_%s' % (cat_num, cid)
            if key not in completed_keys:
                remaining.append(tc)

        print(f"\n{'='*60}")
        print(f"Category {cat_num}: {cat_name} ({len(test_cases)} total, {len(remaining)} remaining)")
        print(f"{'='*60}")
        sys.stdout.flush()

        for i, test_case in enumerate(test_cases):
            case_id = test_case.get('id', f'Q{i+1:04d}')
            key = f"{cat_num}_{case_id}"

            if key in completed_keys:
                continue

            input_text = test_case.get('input', '')
            print(f"  [{i+1}/{len(test_cases)}] {case_id}...", end=" ", flush=True)

            session_id = f"agent{AGENT_ID}_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"

            start_time = time.time()
            response = send_message(input_text, session_id, timeout=120)
            response_time = time.time() - start_time

            total_score, dimension_scores = score_response(response, test_case)
            pass_threshold = test_case.get('pass_threshold', 0.6)
            passed = total_score >= pass_threshold and dimension_scores['safety'] > 0

            root_cause = root_cause_detail = None
            if not passed:
                root_cause, root_cause_detail = analyze_failure(response, test_case)

            difficulty = test_case.get('difficulty', 'unknown')

            # Take screenshot
            screenshot_path = take_screenshot(case_id, cat_num)

            result = {
                'case_id': case_id,
                'category': cat_name,
                'category_num': cat_num,
                'input': input_text,
                'response': response[:2000],
                'response_length': len(response),
                'total_score': total_score,
                'dimension_scores': dimension_scores,
                'passed': passed,
                'root_cause': root_cause,
                'root_cause_detail': root_cause_detail,
                'response_time': response_time,
                'difficulty': difficulty,
                'screenshot': screenshot_path,
                'timestamp': datetime.now().isoformat()
            }
            all_results.append(result)
            completed_keys.add(key)

            status = "PASS" if passed else "FAIL"
            print(f"{status} ({total_score:.2f}) [{response_time:.1f}s]")
            if root_cause:
                print(f"    -> {root_cause}: {root_cause_detail}")

            # Save every 5 cases
            if len(all_results) % 5 == 0:
                save_results(all_results)

        # Save after each category
        save_results(all_results)
        print(f"  [Category complete. Total: {len(all_results)} results saved]")
        sys.stdout.flush()

    return all_results

def generate_report(all_results):
    report_file = f"{REPORT_DIR}/agent{AGENT_ID}_report.md"
    total_tests = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    failed = total_tests - passed
    pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0

    categories = {}
    for r in all_results:
        cat = r['category']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    root_causes = {}
    for r in all_results:
        if r['root_cause']:
            root_causes[r['root_cause']] = root_causes.get(r['root_cause'], 0) + 1

    avg_response_time = sum(r['response_time'] for r in all_results) / total_tests if total_tests > 0 else 0
    avg_score = sum(r['total_score'] for r in all_results) / total_tests if total_tests > 0 else 0
    max_rt = max(r['response_time'] for r in all_results) if all_results else 0
    min_rt = min(r['response_time'] for r in all_results) if all_results else 0

    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"# Agent {AGENT_ID} Benchmark Report - Categories 10-18\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**Agent ID:** {AGENT_ID}\n\n")
        f.write(f"**Categories Tested:** {', '.join(sorted(categories.keys()))}\n\n")

        f.write("## Executive Summary\n\n")
        f.write("| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Total Tests | {total_tests} |\n")
        f.write(f"| Passed | {passed} |\n")
        f.write(f"| Failed | {failed} |\n")
        f.write(f"| Pass Rate | {pass_rate:.1f}% |\n")
        f.write(f"| Avg Score | {avg_score:.3f} |\n")
        f.write(f"| Avg Response Time | {avg_response_time:.1f}s |\n")
        f.write(f"| Max Response Time | {max_rt:.1f}s |\n")
        f.write(f"| Min Response Time | {min_rt:.1f}s |\n\n")

        f.write("### Category Breakdown\n\n")
        f.write("| Category | Cases | Passed | Failed | Pass Rate | Avg Score |\n")
        f.write("|----------|-------|--------|--------|-----------|----------|\n")
        for cat_name, cat_results in sorted(categories.items()):
            cp = sum(1 for r in cat_results if r['passed'])
            cf = len(cat_results) - cp
            cr = (cp / len(cat_results) * 100) if cat_results else 0
            ca = sum(r['total_score'] for r in cat_results) / len(cat_results) if cat_results else 0
            f.write(f"| {cat_name} | {len(cat_results)} | {cp} | {cf} | {cr:.0f}% | {ca:.3f} |\n")
        f.write("\n")

        if root_causes:
            f.write("### Failure Root Causes\n\n")
            f.write("| Root Cause | Count | % of Failures | Severity | Description |\n")
            f.write("|------------|-------|---------------|----------|-------------|\n")
            sev = {'hallucination':'P0','safety_leak':'P0','keyword_missing':'P2','wrong_answer':'P2',
                   'too_brief':'P2','too_verbose':'P2','context_lost':'P1','tool_misfire':'P1',
                   'env_error':'P1','scoring_bug':'P3'}
            desc = {'hallucination':'Contains uncertainty/fabrication phrases',
                    'safety_leak':'Contains forbidden keywords',
                    'keyword_missing':'Missing expected clinical keywords',
                    'wrong_answer':'Response does not meet expectations',
                    'too_brief':'Response too short (<100 chars)',
                    'too_verbose':'Response too long (>5000 chars)',
                    'context_lost':'Lost conversation context',
                    'tool_misfire':'Tool call failed',
                    'env_error':'Environment issue',
                    'scoring_bug':'Scoring error'}
            for rc, count in sorted(root_causes.items(), key=lambda x: -x[1]):
                pct = (count / failed * 100) if failed > 0 else 0
                f.write(f"| {rc} | {count} | {pct:.1f}% | {sev.get(rc,'P2')} | {desc.get(rc,'Unknown')} |\n")
            f.write("\n")

        difficulties = {}
        for r in all_results:
            d = r.get('difficulty', 'unknown')
            if d not in difficulties:
                difficulties[d] = []
            difficulties[d].append(r)

        if difficulties:
            f.write("### Score Distribution by Difficulty\n\n")
            f.write("| Difficulty | Count | Avg Score | Pass Rate |\n")
            f.write("|------------|-------|-----------|----------|\n")
            for dn, dr in sorted(difficulties.items()):
                da = sum(r['total_score'] for r in dr) / len(dr)
                dp = sum(1 for r in dr if r['passed'])
                dpr = (dp / len(dr) * 100) if dr else 0
                f.write(f"| {dn} | {len(dr)} | {da:.3f} | {dpr:.0f}% |\n")
            f.write("\n")

        env_screenshot = f"{SCREENSHOT_DIR}/agent2_env.png"
        if os.path.exists(env_screenshot):
            f.write("### System Screenshot\n\n")
            f.write("![BrachyBot UI](../screenshots/agent2_env.png)\n\n")

        f.write("## Detailed Results\n\n")
        for cat_name, cat_results in sorted(categories.items()):
            cp = sum(1 for r in cat_results if r['passed'])
            ct = len(cat_results)
            cr = (cp / ct * 100) if ct > 0 else 0
            fc = [r for r in cat_results if not r['passed']]
            pc = [r for r in cat_results if r['passed']]

            f.write(f"### {cat_name} ({cp}/{ct} passed, {cr:.0f}%)\n\n")

            crc = {}
            for r in fc:
                if r['root_cause']:
                    crc[r['root_cause']] = crc.get(r['root_cause'], 0) + 1
            if crc:
                f.write(f"**Root Causes:** {', '.join(f'{k}({v})' for k,v in crc.items())}\n\n")

            if fc:
                f.write(f"#### Failed Cases ({len(fc)})\n\n")
                for r in fc:
                    f.write(f"**{r['case_id']}** [{r['root_cause']}]\n\n")
                    f.write(f"- **Input:** {r['input'][:200]}{'...' if len(r['input'])>200 else ''}\n")
                    f.write(f"- **Response ({r['response_length']} chars, {r['response_time']:.1f}s):**\n")
                    f.write(f"  > {r['response'][:300]}{'...' if len(r['response'])>300 else ''}\n")
                    f.write(f"- **Scores:** keyword={r['dimension_scores']['keyword']:.2f}, completeness={r['dimension_scores']['completeness']:.2f}, safety={r['dimension_scores']['safety']:.2f}, accuracy={r['dimension_scores']['accuracy']:.2f}, ux={r['dimension_scores']['ux']:.2f}\n")
                    f.write(f"- **Total:** {r['total_score']:.3f} (threshold: 0.6)\n")
                    f.write(f"- **Detail:** {r['root_cause_detail']}\n")
                    if r.get('screenshot') and os.path.exists(r['screenshot']):
                        rel = os.path.relpath(r['screenshot'], REPORT_DIR)
                        f.write(f"- **Screenshot:** ![{r['case_id']}]({rel})\n")
                    f.write("\n")

            if pc:
                f.write(f"#### Passed Cases ({len(pc)})\n\n")
                f.write("| Case ID | Score | Response Time | Response Length | Difficulty |\n")
                f.write("|---------|-------|---------------|-----------------|------------|\n")
                for r in pc:
                    f.write(f"| {r['case_id']} | {r['total_score']:.3f} | {r['response_time']:.1f}s | {r['response_length']} | {r['difficulty']} |\n")
                f.write("\n")

            f.write("---\n\n")

    print(f"\nReport: {report_file}")
    return report_file


if __name__ == "__main__":
    all_results = run_all_categories()

    if all_results:
        report_file = generate_report(all_results)
        save_results(all_results)
        print(f"\n{'='*60}")
        print(f"Agent {AGENT_ID} Complete!")
        print(f"Total: {len(all_results)} tests, {sum(1 for r in all_results if r['passed'])} passed")
        print(f"Report: {report_file}")
        print(f"Results: {RESULTS_FILE}")
        print(f"{'='*60}")
    else:
        print("\nNo results collected!")
