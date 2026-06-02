#!/usr/bin/env python3
"""
Agent 1 - Per-test saver. Saves after every test case.
Resumeable: skips already-completed cases.
No screenshots in this pass - screenshots done separately.
"""
import json, os, sys, time, glob, requests, fcntl
from datetime import datetime

BASE_URL = "http://localhost:8080"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
RESULTS_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent1_all_results.json"

def load_results():
    try:
        with open(RESULTS_FILE) as f:
            return json.load(f)
    except:
        return []

def save_results(results):
    tmp = RESULTS_FILE + ".tmp"
    with open(tmp, 'w') as f:
        json.dump(results, f, indent=2)
    os.replace(tmp, RESULTS_FILE)

def send_message(text, session_id, timeout=120):
    payload = {"message": text, "clear_context": True, "session_id": session_id, "stream": False}
    for attempt in range(3):
        try:
            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            if response.status_code == 429:
                wait = 15 * (attempt + 1)
                print(f"[rate-limit, wait {wait}s]", end=" ", flush=True)
                time.sleep(wait)
                continue
            data = response.json()
            return data.get('response', '')
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

if __name__ == "__main__":
    categories = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else list(range(1, 10))
    
    existing = load_results()
    done = set((r['category'], r['case_id']) for r in existing)
    print(f"Loaded {len(existing)} existing results, {len(done)} unique cases done")
    print(f"Categories: {categories}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    sys.stdout.flush()
    
    new_count = 0
    for cat_num in categories:
        files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
        if not files:
            continue
        with open(files[0]) as f:
            data = json.load(f)
        cat_name = os.path.basename(files[0]).replace('.json', '')
        cases = data['cases'] if isinstance(data, dict) and 'cases' in data else data
        remaining = [(i, tc) for i, tc in enumerate(cases) 
                     if (cat_name, tc.get('id', f'Q{i+1:04d}')) not in done]
        
        if not remaining:
            print(f"\nCat {cat_num}: {cat_name} - ALL DONE ({len(cases)} cases)")
            sys.stdout.flush()
            continue
        
        cat_done = len(cases) - len(remaining)
        print(f"\nCat {cat_num}: {cat_name} - {cat_done}/{len(cases)} done, {len(remaining)} remaining")
        sys.stdout.flush()
        
        for idx, (i, tc) in enumerate(remaining):
            case_id = tc.get('id', f'Q{i+1:04d}')
            input_text = tc.get('input', '')
            print(f"  [{cat_done+idx+1}/{len(cases)}] {case_id}...", end=" ", flush=True)
            
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
            done.add((cat_name, case_id))
            new_count += 1
            
            status = "PASS" if passed else "FAIL"
            print(f"{status} ({total_score:.2f}) [{rt:.1f}s] {len(response)}ch")
            if rc:
                print(f"    -> {rc}: {rcd}")
            
            # Save after EVERY test
            save_results(existing)
            sys.stdout.flush()
            time.sleep(0.5)
    
    print(f"\n{'='*60}")
    print(f"DONE: {new_count} new tests, {len(existing)} total")
    sys.stdout.flush()
