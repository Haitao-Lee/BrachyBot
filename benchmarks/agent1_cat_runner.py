#!/usr/bin/env python3
"""Agent 1 - Per-category runner. Saves to per-category files. Resumeable."""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
RESULTS_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result"
AGENT_ID = 1

def load_results(cat_num):
    f = f"{RESULTS_DIR}/agent1_results_cat{cat_num:02d}.json"
    try:
        with open(f) as fp:
            return json.load(fp)
    except:
        return []

def save_results(cat_num, results):
    f = f"{RESULTS_DIR}/agent1_results_cat{cat_num:02d}.json"
    tmp = f + ".tmp"
    with open(tmp, 'w') as fp:
        json.dump(results, fp, indent=2)
    os.replace(tmp, f)

def send_message(text, session_id, timeout=120):
    payload = {"message": text, "clear_context": True, "session_id": session_id, "stream": False}
    for attempt in range(3):
        try:
            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            if response.status_code == 429:
                print(f"[rate-limit, wait {15*(attempt+1)}s]", end=" ", flush=True)
                time.sleep(15 * (attempt + 1))
                continue
            data = response.json()
            return data.get('response', '')
        except requests.exceptions.ReadTimeout:
            print(f"[read-timeout]", end=" ", flush=True)
            time.sleep(5)
        except requests.exceptions.ConnectionError:
            print(f"[conn-err]", end=" ", flush=True)
            time.sleep(5)
        except Exception as e:
            print(f"[err:{type(e).__name__}]", end=" ", flush=True)
            time.sleep(3)
    return ""

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

if __name__ == "__main__":
    categories = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else list(range(1, 10))
    print(f"Agent {AGENT_ID} Per-Category Runner")
    print(f"Categories: {categories}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    sys.stdout.flush()
    
    for cat_num in categories:
        files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
        if not files:
            continue
        with open(files[0]) as f:
            data = json.load(f)
        cat_name = os.path.basename(files[0]).replace('.json', '')
        cases = data['cases'] if isinstance(data, dict) and 'cases' in data else data
        
        # Load existing results (filter empty responses)
        existing = [r for r in load_results(cat_num) if r.get('response_length', 0) > 0]
        done_ids = set(r['case_id'] for r in existing)
        remaining = [(i, tc) for i, tc in enumerate(cases) 
                     if tc.get('id', f'Q{i+1:04d}') not in done_ids]
        
        if not remaining:
            print(f"\nCat {cat_num}: {cat_name} - ALL DONE ({len(cases)} cases, {len(existing)} valid)")
            sys.stdout.flush()
            continue
        
        print(f"\nCat {cat_num}: {cat_name} - {len(existing)}/{len(cases)} done, {len(remaining)} remaining")
        sys.stdout.flush()
        
        for idx, (i, tc) in enumerate(remaining):
            case_id = tc.get('id', f'Q{i+1:04d}')
            input_text = tc.get('input', '')
            print(f"  [{len(existing)+idx+1}/{len(cases)}] {case_id}...", end=" ", flush=True)
            
            session_id = f"agent1_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
            t0 = time.time()
            response = send_message(input_text, session_id, timeout=90)
            rt = time.time() - t0
            total_score, dim = score_response(response, tc)
            threshold = tc.get('pass_threshold', 0.6)
            passed = total_score >= threshold and dim['safety'] > 0
            rc = rcd = None
            if not passed:
                rc, rcd = analyze_failure(response, tc)
            
            result = {
                'case_id': case_id, 'category': cat_name, 'category_num': cat_num,
                'input': input_text, 'response': response[:1500], 'response_length': len(response),
                'total_score': round(total_score, 3),
                'dimension_scores': {k: round(v, 3) for k, v in dim.items()},
                'passed': passed, 'root_cause': rc, 'root_cause_detail': rcd,
                'response_time': round(rt, 1), 'screenshot': None,
                'timestamp': datetime.now().isoformat()
            }
            
            existing.append(result)
            status = "PASS" if passed else "FAIL"
            print(f"{status} ({total_score:.2f}) [{rt:.1f}s] {len(response)}ch")
            if rc:
                print(f"    -> {rc}: {rcd}")
            
            save_results(cat_num, existing)
            sys.stdout.flush()
            time.sleep(0.5)
        
        cat_passed = sum(1 for r in existing if r['passed'])
        print(f"  => Cat {cat_num} complete: {cat_passed}/{len(existing)} passed")
    
    # Summary
    print(f"\n{'='*60}")
    total_all = 0
    passed_all = 0
    for cat_num in categories:
        results = [r for r in load_results(cat_num) if r.get('response_length', 0) > 0]
        passed = sum(1 for r in results if r['passed'])
        total_all += len(results)
        passed_all += passed
        print(f"  Cat {cat_num:02d}: {passed}/{len(results)} passed")
    print(f"Total: {passed_all}/{total_all} passed")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
