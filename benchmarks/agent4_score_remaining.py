#!/usr/bin/env python3
"""Score remaining categories: 31, 32, 33, 35, 36"""
import json, os, sys, time, requests, glob
from datetime import datetime

BASE_URL = "http://localhost:8080"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"

def send_message(text, session_id, timeout=120, retries=3):
    for attempt in range(retries):
        try:
            payload = {"message": text, "clear_context": True, "session_id": session_id, "stream": False}
            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            return response.json().get('response', '')
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(5)
    return f"Error: All retries failed"

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
    files = [f for f in os.listdir(BENCHMARK_DIR) if f.startswith(f"{cat_num:02d}_") and f.endswith('.json')]
    if not files:
        return []
    with open(os.path.join(BENCHMARK_DIR, files[0]), 'r') as f:
        data = json.load(f)
    cases = data.get('cases', data)
    cat_name = files[0].replace('.json', '')

    results = []
    for i, tc in enumerate(cases):
        case_id = tc.get('id', f'Q{i+1:03d}')
        input_text = tc.get('input', '')
        if not input_text:
            turns = tc.get('turns', [])
            if turns:
                input_text = turns[0].get('input', '')
        if not input_text:
            print(f"  {case_id}: SKIP (no input)")
            continue

        print(f"  [{i+1}/{len(cases)}] {case_id}...", end=" ", flush=True)
        session_id = f"agent4_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
        start = time.time()
        response = send_message(input_text, session_id, timeout=180)
        resp_time = time.time() - start

        total_score, dim_scores = score_response(response, tc)
        pass_threshold = tc.get('pass_threshold', 0.6)
        passed = total_score >= pass_threshold and dim_scores['safety'] > 0

        root_cause = root_cause_detail = None
        if not passed:
            root_cause, root_cause_detail = analyze_failure(response, tc)

        screenshot_path = f"/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots/{cat_num:02d}_{case_id}.png"

        result = {
            'case_id': case_id, 'category': cat_name, 'category_num': cat_num,
            'input': input_text, 'response': response[:1500], 'response_length': len(response),
            'total_score': total_score, 'dimension_scores': dim_scores, 'passed': passed,
            'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
            'response_time': resp_time, 'screenshot': screenshot_path,
            'timestamp': datetime.now().isoformat()
        }
        results.append(result)

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({total_score:.2f}) [{resp_time:.1f}s]")
        if root_cause:
            print(f"    -> {root_cause}: {root_cause_detail}")

    return results

if __name__ == "__main__":
    all_results = []
    for cat in [31, 32, 33, 35, 36]:
        print(f"\nCategory {cat}:")
        results = run_category(cat)
        all_results.extend(results)
        passed = sum(1 for r in results if r['passed'])
        print(f"  Total: {passed}/{len(results)} passed")

    output_file = os.path.join(REPORT_DIR, "agent4_remaining_scores.json")
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved: {output_file}")
