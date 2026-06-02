#!/usr/bin/env python3
"""
Category 23 batch runner - processes a range of tests.
Usage: python cat23_batch.py START END
"""
import json, os, sys, time, requests, glob
from datetime import datetime

BASE_URL = "http://localhost:8080"
RESULTS_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent4_cat23_results.json"
AGENT_ID = 4
CAT_NUM = 23
API_TIMEOUT = 120

os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)

def load_benchmark():
    files = glob.glob(f"/home/lht/snap/brachyplan/BrachyBot/benchmarks/{CAT_NUM:02d}_*.json")
    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get('cases', data) if isinstance(data, dict) else data

def load_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_results(results):
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

def send_message(text, session_id, timeout=API_TIMEOUT):
    try:
        r = requests.post(f"{BASE_URL}/api/chat", json={
            "message": text, "clear_context": True,
            "session_id": session_id, "stream": False
        }, timeout=timeout)
        return r.json().get('response', '')
    except Exception as e:
        return f"Error: {str(e)[:200]}"

def score_response(response, test_case):
    scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
    expected = test_case.get('expected_keywords', [])
    if expected:
        if isinstance(expected, dict):
            tw = sum(v.get('weight', 0.1) for v in expected.values())
            mw = sum(v.get('weight', 0.1) for kw, v in expected.items() if kw.lower() in response.lower())
            scores['keyword'] = mw / tw if tw > 0 else 0
        else:
            scores['keyword'] = sum(1 for kw in expected if kw.lower() in response.lower()) / len(expected)
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

def run_batch(start, end):
    test_cases = load_benchmark()
    existing = load_results()
    existing_ids = {r['case_id'] for r in existing}

    end = min(end, len(test_cases))
    batch = test_cases[start:end]

    print(f"Batch: tests {start+1}-{end} of {len(test_cases)}")
    print(f"Already completed: {len(existing)} tests")

    new_results = []
    for i, tc in enumerate(batch):
        idx = start + i
        case_id = tc.get('id', f'Q{idx+1:04d}')
        if case_id in existing_ids:
            print(f"  [{idx+1}] {case_id} [CACHED]")
            continue

        print(f"  [{idx+1}] {case_id}...", end=" ", flush=True)
        sid = f"a4_cat23_{case_id}_{int(time.time()*1000)}"
        t0 = time.time()
        response = send_message(tc.get('input', ''), sid)
        rt = time.time() - t0

        total, dim = score_response(response, tc)
        passed = total >= tc.get('pass_threshold', 0.6) and dim['safety'] > 0
        rc = rcd = None
        if not passed:
            rc, rcd = analyze_failure(response, tc)

        result = {
            'case_id': case_id, 'input': tc.get('input', ''),
            'response': response[:2000], 'response_length': len(response),
            'total_score': total, 'dimension_scores': dim,
            'passed': passed, 'root_cause': rc, 'root_cause_detail': rcd,
            'response_time': rt, 'timestamp': datetime.now().isoformat()
        }
        new_results.append(result)
        existing.append(result)
        existing_ids.add(case_id)

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total:.2f}) [{rt:.1f}s] [{len(response)} chars]")
        if rc:
            print(f"    -> {rc}: {rcd}")

    save_results(existing)
    passed = sum(1 for r in existing if r['passed'])
    print(f"\nSaved {len(existing)} total results ({passed} passed)")

if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 999
    run_batch(start, end)
