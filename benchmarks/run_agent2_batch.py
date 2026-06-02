#!/usr/bin/env python3
"""Run a specific batch of test cases. Usage: python3 run_agent2_batch.py <start> <count>"""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = 'http://localhost:8080'
RESULTS_FILE = '/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent2_final_results.json'

START = int(sys.argv[1]) if len(sys.argv) > 1 else 0
COUNT = int(sys.argv[2]) if len(sys.argv) > 2 else 5

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

# Build flat list of all test cases
ALL_CASES = []
for cat_num in [10, 11, 12, 13, 14, 15, 16, 17, 18]:
    files = glob.glob('/home/lht/snap/brachyplan/BrachyBot/benchmarks/%02d_*.json' % cat_num)
    if not files: continue
    with open(files[0]) as f: d = json.load(f)
    cases = d.get('cases', d) if isinstance(d, dict) else d
    cat_name = os.path.basename(files[0]).replace('.json', '')
    for tc in cases:
        ALL_CASES.append({'cat_num': cat_num, 'cat_name': cat_name, 'tc': tc})

# Load existing
existing = []
completed = set()
if os.path.exists(RESULTS_FILE):
    try:
        with open(RESULTS_FILE) as f: existing = json.load(f)
        existing = [r for r in existing if not r.get('response', '').startswith('Error:')]
        completed = set('%d_%s' % (r['category_num'], r['case_id']) for r in existing)
    except: pass

# Filter to this batch
batch = []
for idx, item in enumerate(ALL_CASES):
    tc = item['tc']
    cid = tc.get('id', 'Q%04d' % (idx+1))
    key = '%d_%s' % (item['cat_num'], cid)
    if key in completed: continue
    batch.append((idx, item))

batch = batch[START:START+COUNT]

print('Batch %d-%d: %d cases to run (%d already done)' % (START, START+COUNT, len(batch), len(completed)))
sys.stdout.flush()

results = list(existing)
for idx, (orig_idx, item) in enumerate(batch):
    cat_num = item['cat_num']
    cat_name = item['cat_name']
    tc = item['tc']
    cid = tc.get('id', 'Q%04d' % (orig_idx+1))
    inp = tc.get('input', '')

    print('[%d/%d] %s/%s...' % (idx+1, len(batch), cat_name, cid), end=' ', flush=True)

    sid = 'a2_%d_%s_%d' % (cat_num, cid, int(time.time()*1000))
    t0 = time.time()
    resp = send_message(inp, sid, timeout=120)
    rt = time.time() - t0

    ts, dim = score_response(resp, tc)
    th = tc.get('pass_threshold', 0.6)
    passed = ts >= th and dim['safety'] > 0
    rc = rcd = None
    if not passed: rc, rcd = analyze_failure(resp, tc)

    results.append({
        'case_id': cid, 'category': cat_name, 'category_num': cat_num,
        'input': inp, 'response': resp[:2000], 'response_length': len(resp),
        'total_score': ts, 'dimension_scores': dim, 'passed': passed,
        'root_cause': rc, 'root_cause_detail': rcd, 'response_time': rt,
        'difficulty': tc.get('difficulty','unknown'), 'screenshot': None,
        'timestamp': datetime.now().isoformat()
    })

    st = 'PASS' if passed else 'FAIL'
    print('%s (%.2f) [%.1fs]' % (st, ts, rt))
    if rc: print('  -> %s: %s' % (rc, rcd))
    sys.stdout.flush()
    time.sleep(2)

# Save
os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
with open(RESULTS_FILE, 'w') as f: json.dump(results, f, indent=2, default=str)
print('Saved %d total results' % len(results))
