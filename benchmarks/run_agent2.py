#!/usr/bin/env python3
"""Minimal benchmark runner - API only, no screenshots."""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = 'http://localhost:8080'
RESULTS_FILE = '/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent2_final_results.json'
LOG_FILE = '/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent2_api.log'

os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)

def log(msg):
    line = '%s %s' % (datetime.now().strftime('%H:%M:%S'), msg)
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f: f.write(line + '\n')

def send_message(text, session_id, timeout=120):
    for attempt in range(3):
        try:
            r = requests.post(BASE_URL + '/api/chat',
                json={'message': text, 'clear_context': True, 'session_id': session_id, 'stream': False},
                timeout=timeout)
            return r.json().get('response', '')
        except:
            if attempt < 2: time.sleep(3)
            else: return 'Error: timeout'

def score_response(response, test_case):
    scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
    ek = test_case.get('expected_keywords', [])
    if ek:
        if isinstance(ek, dict):
            tw = sum(v.get('weight', 0.1) for v in ek.values())
            mw = sum(v.get('weight', 0.1) for kw, v in ek.items() if kw.lower() in response.lower())
            scores['keyword'] = mw/tw if tw > 0 else 0
        else:
            m = sum(1 for kw in ek if kw.lower() in response.lower())
            scores['keyword'] = m/len(ek) if ek else 0
    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            scores['safety'] = 0.0; break
    for kw in test_case.get('hallucination_keywords', []):
        if kw.lower() in response.lower():
            scores['accuracy'] -= 0.5
    if len(response) < 100: scores['completeness'] = 0.5
    elif len(response) > 5000: scores['ux'] -= 0.3
    else: scores['completeness'] = 1.0
    total = (scores['keyword']*0.4 + scores['completeness']*0.2 + scores['safety']*0.2 + scores['accuracy']*0.1 + scores['ux']*0.1)
    return total, scores

def analyze_failure(response, test_case):
    for kw in ["I don't know", "I'm not sure", 'I cannot verify', "I'm just guessing"]:
        if kw.lower() in response.lower(): return 'hallucination', 'Contains: ' + kw
    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower(): return 'safety_leak', 'Forbidden: ' + kw
    if len(response) < 100: return 'too_brief', 'Short: %d chars' % len(response)
    if len(response) > 5000: return 'too_verbose', 'Long: %d chars' % len(response)
    ek = test_case.get('expected_keywords', [])
    if ek:
        m = sum(1 for kw in ek if kw.lower() in response.lower())
        if m == 0: return 'keyword_missing', 'No keywords found'
    return 'wrong_answer', 'Does not meet expectations'

def load_existing():
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE) as f: data = json.load(f)
            valid = [r for r in data if not r.get('response', '').startswith('Error:')]
            keys = set('%d_%s' % (r['category_num'], r['case_id']) for r in valid)
            return valid, keys
        except: pass
    return [], set()

def save(all_results):
    with open(RESULTS_FILE, 'w') as f: json.dump(all_results, f, indent=2, default=str)

def main():
    CATEGORIES = [10, 11, 12, 13, 14, 15, 16, 17, 18]
    all_results, completed = load_existing()
    log('Agent2 API Phase - %d existing results, %d completed keys' % (len(all_results), len(completed)))

    for cat_num in CATEGORIES:
        files = glob.glob('/home/lht/snap/brachyplan/BrachyBot/benchmarks/%02d_*.json' % cat_num)
        if not files: continue
        with open(files[0]) as f: d = json.load(f)
        cases = d.get('cases', d) if isinstance(d, dict) else d
        cat_name = os.path.basename(files[0]).replace('.json', '')
        remaining = sum(1 for i,tc in enumerate(cases) if '%d_%s' % (cat_num, tc.get('id','Q%04d'%(i+1))) not in completed)
        log('Cat %d: %s (%d total, %d remaining)' % (cat_num, cat_name, len(cases), remaining))

        for i, tc in enumerate(cases):
            cid = tc.get('id', 'Q%04d' % (i+1))
            key = '%d_%s' % (cat_num, cid)
            if key in completed: continue

            inp = tc.get('input', '')
            sys.stdout.write('  [%d/%d] %s... ' % (i+1, len(cases), cid))
            sys.stdout.flush()

            sid = 'a2_%d_%s_%d' % (cat_num, cid, int(time.time()*1000))
            t0 = time.time()
            resp = send_message(inp, sid, timeout=120)
            rt = time.time() - t0

            ts, dim = score_response(resp, tc)
            th = tc.get('pass_threshold', 0.6)
            passed = ts >= th and dim['safety'] > 0
            rc = rcd = None
            if not passed: rc, rcd = analyze_failure(resp, tc)

            all_results.append({
                'case_id': cid, 'category': cat_name, 'category_num': cat_num,
                'input': inp, 'response': resp[:2000], 'response_length': len(resp),
                'total_score': ts, 'dimension_scores': dim, 'passed': passed,
                'root_cause': rc, 'root_cause_detail': rcd, 'response_time': rt,
                'difficulty': tc.get('difficulty','unknown'), 'screenshot': None,
                'timestamp': datetime.now().isoformat()
            })
            completed.add(key)

            st = 'PASS' if passed else 'FAIL'
            line = '%s (%.2f) [%.1fs]' % (st, ts, rt)
            print(line, flush=True)
            with open(LOG_FILE, 'a') as f: f.write('  %s %s\n' % (cid, line))
            if rc:
                detail = '    -> %s: %s' % (rc, rcd)
                print(detail, flush=True)
                with open(LOG_FILE, 'a') as f: f.write('    %s\n' % detail)

            save(all_results)
            time.sleep(2)  # Rate limit: avoid 429

        save(all_results)
        log('  [Saved %d total]' % len(all_results))

    total = len(all_results)
    passed_n = sum(1 for r in all_results if r['passed'])
    log('DONE: %d tests, %d passed (%.1f%%)' % (total, passed_n, passed_n/total*100 if total else 0))

if __name__ == '__main__':
    # Clear log
    with open(LOG_FILE, 'w') as f: f.write('Agent2 API Phase\n')
    main()
