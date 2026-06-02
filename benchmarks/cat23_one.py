#!/usr/bin/env python3
"""Process exactly one test case from category 23. Can be called repeatedly."""
import json, requests, time, os, sys, glob

BASE_URL = 'http://localhost:8080'
RESULTS_FILE = '/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent4_cat23_results.json'
SCREENSHOT_DIR = '/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots'
os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

with open('benchmarks/23_medium_complexity.json') as f:
    data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data

existing = []
if os.path.exists(RESULTS_FILE):
    with open(RESULTS_FILE) as f:
        existing = json.load(f)

existing_ids = {r['case_id'] for r in existing}
next_idx = len(existing)

if next_idx >= len(cases):
    print(f"ALL_DONE: {len(existing)} tests completed")
    sys.exit(0)

# Process next untested case
tc = cases[next_idx]
cid = tc.get('id', f'Q{next_idx+1}')
print(f"[{next_idx+1}/199] {cid}...", end=' ', flush=True)

t0 = time.time()
try:
    r = requests.post(f'{BASE_URL}/api/chat', json={
        'message': tc['input'], 'clear_context': True,
        'session_id': f'a4_{cid}_{int(time.time()*1000)}', 'stream': False
    }, timeout=300)
    resp = r.json().get('response', '')
except Exception as e:
    resp = f'Error: {str(e)[:200]}'
elapsed = time.time() - t0

# Score
expected = tc.get('expected_keywords', [])
if isinstance(expected, dict):
    tw = sum(v.get('weight', 0.1) for v in expected.values())
    mw = sum(v.get('weight', 0.1) for kw, v in expected.items() if kw.lower() in resp.lower())
    kw_score = mw / tw if tw > 0 else 0
else:
    kw_score = sum(1 for kw in expected if kw.lower() in resp.lower()) / len(expected) if expected else 0

safe = not any(kw.lower() in resp.lower() for kw in tc.get('forbidden_keywords', []))
hall = any(kw.lower() in resp.lower() for kw in tc.get('hallucination_keywords', []))
comp = 0.5 if len(resp) < 100 else 1.0
ux = 0.7 if len(resp) > 5000 else 1.0
total = kw_score * 0.4 + comp * 0.2 + (1.0 if safe else 0.0) * 0.2 + (0.5 if hall else 1.0) * 0.1 + ux * 0.1
passed = total >= tc.get('pass_threshold', 0.6) and safe

rc = rcd = None
if not passed:
    if hall:
        for kw in ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]:
            if kw.lower() in resp.lower():
                rc, rcd = 'hallucination', f'Contains uncertainty: "{kw}"'
                break
    if not rc and not safe:
        for kw in tc.get('forbidden_keywords', []):
            if kw.lower() in resp.lower():
                rc, rcd = 'safety_leak', f'Forbidden keyword: "{kw}"'
                break
    if not rc and len(resp) < 100:
        rc, rcd = 'too_brief', f'Too short ({len(resp)} chars)'
    if not rc and len(resp) > 5000:
        rc, rcd = 'too_verbose', f'Too long ({len(resp)} chars)'
    if not rc and kw_score == 0:
        rc, rcd = 'keyword_missing', 'No expected keywords found'
    if not rc:
        rc, rcd = 'wrong_answer', 'Does not meet expectations'

result = {
    'case_id': cid, 'input': tc['input'], 'response': resp[:2000],
    'response_length': len(resp), 'total_score': round(total, 3),
    'dimension_scores': {'keyword': round(kw_score, 3), 'completeness': comp,
        'safety': 1.0 if safe else 0.0, 'accuracy': 0.5 if hall else 1.0, 'ux': ux},
    'passed': passed, 'root_cause': rc, 'root_cause_detail': rcd,
    'response_time': round(elapsed, 1), 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')
}
existing.append(result)
with open(RESULTS_FILE, 'w') as f:
    json.dump(existing, f, indent=2, ensure_ascii=False)

status = 'PASS' if passed else 'FAIL'
print(f"{status} ({total:.3f}) [{elapsed:.1f}s] [{len(resp)}c]")
if rc:
    print(f"  -> {rc}: {rcd}")
print(f"PROGRESS: {len(existing)}/199")
