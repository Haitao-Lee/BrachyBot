#!/usr/bin/env python3
"""
Batch runner that handles server crashes and retries.
Runs categories with automatic resume and server health checks.
"""
import json, os, sys, time, glob, subprocess, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
RESULTS_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result"

def ensure_server():
    """Check if server is running, restart if needed."""
    try:
        r = requests.post(f"{BASE_URL}/api/chat",
            json={"message":"ping","clear_context":True,"session_id":"health","stream":False},
            timeout=30)
        d = r.json()
        if d.get('response'):
            return True
    except:
        pass

    print("  Server is down, restarting...")
    # Kill any existing
    subprocess.run(["pkill", "-f", "python.*web/server.py"], capture_output=True)
    time.sleep(2)
    # Start new
    subprocess.Popen(
        ["python3", "web/server.py"],
        stdout=open("/tmp/brachybot_server.log", "w"),
        stderr=subprocess.STDOUT,
        cwd="/home/lht/snap/brachyplan/BrachyBot"
    )
    time.sleep(10)

    try:
        r = requests.post(f"{BASE_URL}/api/chat",
            json={"message":"ping","clear_context":True,"session_id":"health2","stream":False},
            timeout=60)
        d = r.json()
        if d.get('response'):
            print("  Server restarted successfully")
            return True
    except:
        pass

    print("  Failed to restart server!")
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

def run_category_with_resume(cat_num, agent_id):
    """Run a category with automatic resume after crashes."""
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        print(f"  No benchmark file for category {cat_num}")
        return []

    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
        cases = data.get('cases', data) if isinstance(data, dict) else data

    cat_name = os.path.basename(files[0]).replace('.json', '')
    results_file = f"{RESULTS_DIR}/cat{cat_num:02d}_results.json"

    # Load existing results
    existing = []
    if os.path.exists(results_file):
        with open(results_file, 'r') as f:
            existing = json.load(f)
    existing_ids = {r['case_id'] for r in existing}
    results = list(existing)

    print(f"\nCategory {cat_num}: {cat_name} ({len(cases)} cases, {len(existing)} already done)")

    max_retries = 10
    retry = 0

    i = 0
    while i < len(cases) and retry < max_retries:
        case = cases[i]
        case_id = case.get('id', f'Q{i+1:04d}')

        if case_id in existing_ids:
            i += 1
            continue

        # Ensure server is alive
        if not ensure_server():
            print("  Cannot recover server, aborting")
            break

        input_text = case.get('input', '')
        print(f"  [{i+1}/{len(cases)}] {case_id}...", end=" ", flush=True)

        session_id = f"agent{agent_id}_cat{cat_num:02d}_resume"

        try:
            r = requests.post(f"{BASE_URL}/api/chat",
                json={"message": input_text, "clear_context": True, "session_id": session_id, "stream": False},
                timeout=90)
            response = r.json().get('response', '')
        except Exception as e:
            response = f"Error: {str(e)}"
            retry += 1
            print(f"ERR ({retry}/{max_retries}): {str(e)[:50]}")
            # Wait and try to recover
            time.sleep(5)
            if "Connection refused" in str(e) or "timed out" in str(e):
                ensure_server()
            continue

        retry = 0  # Reset on success
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

        # Write after EVERY case
        with open(results_file, 'w') as f:
            json.dump(results, f)

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f})")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")

        i += 1
        time.sleep(0.5)

    cat_passed = sum(1 for r in results if r['passed'])
    print(f"  Category {cat_num} complete: {cat_passed}/{len(results)} passed")
    return results

if __name__ == "__main__":
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    categories = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else []

    if not categories:
        print("Usage: python agent2_batch.py <agent_id> <cat1> <cat2> ...")
        sys.exit(1)

    print(f"Agent {agent_id} Batch Runner (with auto-retry)")
    print(f"Categories: {categories}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    for cat_num in categories:
        run_category_with_resume(cat_num, agent_id)

    print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
