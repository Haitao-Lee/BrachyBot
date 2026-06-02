#!/usr/bin/env python3
"""
Agent 3 Single Category Runner - runs one category at a time with resume.
"""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
RESULTS_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def send_message(text, session_id, timeout=180, retries=3):
    for attempt in range(retries):
        try:
            payload = {"message": text, "clear_context": True, "session_id": session_id, "stream": False}
            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            return response.json().get('response', '')
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                return f"Error: {str(e)[:100]}"

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

def run_category(cat_num, agent_id):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        print(f"No benchmark file found for category {cat_num}")
        return []

    cat_file = files[0]
    cat_name = os.path.basename(cat_file).replace('.json', '')
    with open(cat_file, 'r') as f:
        data = json.load(f)
    test_cases = data.get('cases', data) if isinstance(data, dict) else data

    # Load existing results
    results_file = f"{RESULTS_DIR}/agent3_cat{cat_num:02d}.json"
    existing = []
    if os.path.exists(results_file):
        with open(results_file, 'r') as f:
            existing = json.load(f)
    existing_ids = {r['case_id'] for r in existing}

    results = list(existing)
    remaining = [(i, tc) for i, tc in enumerate(test_cases) if tc.get('id', '') not in existing_ids]

    print(f"Category {cat_num}: {cat_name}")
    print(f"Total: {len(test_cases)} | Completed: {len(existing)} | Remaining: {len(remaining)}")

    for idx, (i, test_case) in enumerate(remaining):
        case_id = test_case.get('id', f'Q{i+1:04d}')
        input_text = test_case.get('input', '')
        print(f"  [{idx+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

        session_id = f"agent{agent_id}_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
        t0 = time.time()
        response = send_message(input_text, session_id, timeout=180)
        rt = time.time() - t0

        total_score, dim = score_response(response, test_case)
        passed = total_score >= test_case.get('pass_threshold', 0.6) and dim['safety'] > 0
        rc = rcd = None
        if not passed:
            rc, rcd = analyze_failure(response, test_case)

        result = {
            'case_id': case_id, 'category': cat_name, 'category_num': cat_num,
            'input': input_text, 'response': response[:2000], 'response_length': len(response),
            'total_score': total_score, 'dimension_scores': dim, 'passed': passed,
            'root_cause': rc, 'root_cause_detail': rcd, 'response_time': rt,
            'difficulty': test_case.get('difficulty', 'unknown'), 'screenshot': None,
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{rt:.1f}s]")
        if rc:
            print(f"    -> {rc}: {rcd}")

        # Save after EVERY case
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        sys.stdout.flush()

    passed_count = sum(1 for r in results if r['passed'])
    print(f"Category {cat_num}: {passed_count}/{len(results)} passed ({passed_count/len(results)*100:.1f}%)")
    return results

if __name__ == "__main__":
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    cat_num = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    run_category(cat_num, agent_id)
