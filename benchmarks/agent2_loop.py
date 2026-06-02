#!/usr/bin/env python3
"""
Loop runner: keeps resuming categories until all are done.
Handles server crashes and OOM kills gracefully.
"""
import json, os, sys, time, glob, subprocess, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
RESULTS_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result"

def ensure_server():
    try:
        r = requests.post(f"{BASE_URL}/api/chat",
            json={"message":"ping","clear_context":True,"session_id":"health_check","stream":False},
            timeout=30)
        if r.json().get('response'):
            return True
    except:
        pass
    print("  [SERVER DOWN] Restarting...")
    subprocess.run(["pkill", "-f", "python3 web/server"], capture_output=True, timeout=5)
    time.sleep(3)
    subprocess.Popen(
        ["python3", "web/server.py"],
        stdout=open("/tmp/brachybot_server.log", "w"),
        stderr=subprocess.STDOUT,
        cwd="/home/lht/snap/brachyplan/BrachyBot",
        start_new_session=True
    )
    time.sleep(12)
    try:
        r = requests.post(f"{BASE_URL}/api/chat",
            json={"message":"ping","clear_context":True,"session_id":"health_check2","stream":False},
            timeout=60)
        if r.json().get('response'):
            print("  [SERVER RESTARTED]")
            return True
    except:
        pass
    return False

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
    expected_keywords = test_case.get('expected_keywords', [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
        else:
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
        if matched == 0:
            return 'keyword_missing', 'No expected keywords found'
    return 'wrong_answer', 'Response does not meet expectations'

def run_category(cat_num, agent_id):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return
    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
        cases = data.get('cases', data) if isinstance(data, dict) else data
    cat_name = os.path.basename(files[0]).replace('.json', '')
    results_file = f"{RESULTS_DIR}/cat{cat_num:02d}_results.json"
    existing = []
    if os.path.exists(results_file):
        with open(results_file, 'r') as f:
            existing = json.load(f)
    existing_ids = {r['case_id'] for r in existing}
    results = list(existing)
    session_id = f"agent{agent_id}_cat{cat_num:02d}"

    remaining = sum(1 for c in cases if c.get('id', '') not in existing_ids)
    if remaining == 0:
        print(f"  Category {cat_num}: ALREADY COMPLETE ({len(results)} cases)")
        return results

    print(f"  Category {cat_num}: {cat_name} ({len(cases)} total, {len(existing)} done, {remaining} remaining)")

    for i, case in enumerate(cases):
        case_id = case.get('id', f'Q{i+1:04d}')
        if case_id in existing_ids:
            continue

        if not ensure_server():
            print(f"  Cannot recover server for cat {cat_num}")
            break

        input_text = case.get('input', '')
        print(f"  [{i+1}/{len(cases)}] {case_id}...", end=" ", flush=True)

        try:
            r = requests.post(f"{BASE_URL}/api/chat",
                json={"message": input_text, "clear_context": True, "session_id": session_id, "stream": False},
                timeout=90)
            response = r.json().get('response', '')
        except Exception as e:
            print(f"ERR: {str(e)[:40]}")
            time.sleep(3)
            continue

        total_score, dim_scores = score_response(response, case)
        pass_threshold = case.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dim_scores['safety'] > 0
        root_cause, root_cause_detail = (None, None)
        if not passed:
            root_cause, root_cause_detail = analyze_failure(response, case)

        result = {
            'case_id': case_id, 'category': cat_name, 'category_num': cat_num,
            'input': input_text, 'response': response[:1500], 'response_length': len(response),
            'total_score': total_score, 'dimension_scores': dim_scores, 'passed': passed,
            'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
            'response_time': 0, 'screenshot': None,
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)
        existing_ids.add(case_id)
        with open(results_file, 'w') as f:
            json.dump(results, f)

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f})")
        time.sleep(0.5)

    cat_passed = sum(1 for r in results if r['passed'])
    print(f"  Category {cat_num} done: {cat_passed}/{len(results)} passed")
    return results

if __name__ == "__main__":
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    categories = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else [10, 12, 13, 14, 15, 16, 17, 18]

    print(f"Agent {agent_id} Loop Runner")
    print(f"Categories: {categories}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    for cat_num in categories:
        try:
            run_category(cat_num, agent_id)
        except Exception as e:
            print(f"  Category {cat_num} EXCEPTION: {e}")
            import traceback
            traceback.print_exc()

    print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
