#!/usr/bin/env python3
"""Benchmark runner using urllib instead of requests to avoid memory issues."""
import json, os, sys, time, glob, urllib.request, urllib.error
from datetime import datetime

BASE_URL = 'http://localhost:8080'
RESULTS_FILE = '/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent2_final_results.json'
LOG_FILE = '/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent2_urllib.log'

os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)

def log(msg):
    line = '%s %s' % (datetime.now().strftime('%H:%M:%S'), msg)
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f: f.write(line + '\n')

def send_message(text, session_id, timeout=120):
    payload = json.dumps({
        'message': text,
        'clear_context': True,
        'session_id': session_id,
        'stream': False
    }).encode('utf-8')
    for attempt in range(3):
        try:
            req = urllib.request.Request(BASE_URL + '/api/chat',
                data=payload,
                headers={'Content-Type': 'application/json'})
            resp = urllib.request.urlopen(req, timeout=timeout)
            data = json.loads(resp.read())
            resp.close()
            return data.get('response', '')
        except Exception as e:
            if attempt < 2: time.sleep(3)
            else: return 'Error: %s' % str(e)

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

# Load existing
all_results = []
completed = set()
if os.path.exists(RESULTS_FILE):
    try:
        with open(RESULTS_FILE) as f: all_results = json.load(f)
        all_results = [r for r in all_results if not r.get('response', '').startswith('Error:')]
        completed = set('%d_%s' % (r['category_num'], r['case_id']) for r in all_results)
        log('Loaded %d existing, %d completed keys' % (len(all_results), len(completed)))
    except: pass

def save(results):
    with open(RESULTS_FILE, 'w') as f: json.dump(results, f, indent=2, default=str)

CATEGORIES = [10, 11, 12, 13, 14, 15, 16, 17, 18]
log('Agent2 urllib runner - Starting')

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
        print('  [%d/%d] %s...' % (i+1, len(cases), cid), end=' ', flush=True)

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
            detail = '  -> %s: %s' % (rc, rcd)
            print(detail, flush=True)

        save(all_results)
        time.sleep(2)

    save(all_results)
    log('  [Saved %d total]' % len(all_results))

total = len(all_results)
passed_n = sum(1 for r in all_results if r['passed'])
log('DONE: %d tests, %d passed (%.1f%%)' % (total, passed_n, passed_n/total*100 if total else 0))
