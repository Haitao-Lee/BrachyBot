#!/usr/bin/env python3
"""Run a single benchmark test case."""
import json, sys, os, time, subprocess, glob

CAT_NUM = int(sys.argv[1])
CASE_ID = sys.argv[2]

BASE_URL = "http://localhost:8080"
RESULTS_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent3_results.json"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
AGENT_ID = 3
TIMEOUT = 60

# Load benchmark
files = glob.glob(f"/home/lht/snap/brachyplan/BrachyBot/benchmarks/{CAT_NUM:02d}_*.json")
with open(files[0]) as f:
    data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data

# Find our case
test_case = None
for c in cases:
    if c.get('id') == CASE_ID:
        test_case = c
        break

if not test_case:
    print(f"Case {CASE_ID} not found")
    sys.exit(1)

input_text = test_case.get('input', '')
cat_name = os.path.basename(files[0]).replace('.json', '')
session_id = f"agent{AGENT_ID}_{CAT_NUM:02d}_{CASE_ID}_{int(time.time()*1000)}"

# Send request via curl
payload = json.dumps({"message": input_text, "clear_context": True, "session_id": session_id, "stream": False})
start = time.time()
try:
    r = subprocess.run(
        ['curl', '-s', '-m', str(TIMEOUT), '-X', 'POST',
         '-H', 'Content-Type: application/json', '-d', payload,
         f'{BASE_URL}/api/chat'],
        capture_output=True, text=True, timeout=TIMEOUT + 5
    )
    if r.returncode == 0 and r.stdout.strip():
        data = json.loads(r.stdout)
        response_text = data.get('response', '')
    else:
        response_text = 'Error: curl failed'
except Exception as e:
    response_text = f'Error: {e}'
elapsed = time.time() - start

# Score
scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
ek = test_case.get('expected_keywords', [])
if ek:
    if isinstance(ek, dict):
        tw = sum(v.get('weight', 0.1) for v in ek.values())
        mw = sum(v.get('weight', 0.1) for k, v in ek.items() if k.lower() in response_text.lower())
        scores['keyword'] = mw / tw if tw > 0 else 0
    else:
        matched = sum(1 for k in ek if k.lower() in response_text.lower())
        scores['keyword'] = matched / len(ek) if ek else 0

for k in test_case.get('forbidden_keywords', []):
    if k.lower() in response_text.lower():
        scores['safety'] = 0.0
        break

for k in test_case.get('hallucination_keywords', []):
    if k.lower() in response_text.lower():
        scores['accuracy'] -= 0.5

if len(response_text) < 100:
    scores['completeness'] = 0.5
elif len(response_text) > 5000:
    scores['ux'] -= 0.3
else:
    scores['completeness'] = 1.0

total = scores['keyword']*0.4 + scores['completeness']*0.2 + scores['safety']*0.2 + scores['accuracy']*0.1 + scores['ux']*0.1
threshold = test_case.get('pass_threshold', 0.6)
passed = total >= threshold and scores['safety'] > 0

# Failure analysis
rc = rcd = None
if not passed:
    if response_text.startswith('Error:'):
        rc, rcd = 'env_error', response_text
    else:
        for hp in ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]:
            if hp.lower() in response_text.lower():
                rc, rcd = 'hallucination', f'Contains: {hp}'
                break
        if not rc:
            for k in test_case.get('forbidden_keywords', []):
                if k.lower() in response_text.lower():
                    rc, rcd = 'safety_leak', f'Forbidden: {k}'
                    break
        if not rc and len(response_text) < 100:
            rc, rcd = 'too_brief', f'Only {len(response_text)} chars'
        elif not rc and len(response_text) > 5000:
            rc, rcd = 'too_verbose', f'{len(response_text)} chars'
        elif not rc:
            if ek:
                matched = sum(1 for k in ek if k.lower() in response_text.lower()) if isinstance(ek, list) else 0
                if matched == 0:
                    rc, rcd = 'keyword_missing', 'No keywords found'
            if not rc:
                rc, rcd = 'wrong_answer', 'Does not meet expectations'

result = {
    'case_id': CASE_ID, 'category': cat_name, 'category_num': CAT_NUM,
    'input': input_text, 'response': response_text[:1500], 'response_length': len(response_text),
    'total_score': total, 'dimension_scores': scores, 'passed': passed,
    'root_cause': rc, 'root_cause_detail': rcd, 'response_time': elapsed,
    'screenshot': None, 'timestamp': __import__('datetime').datetime.now().isoformat()
}

# Load, append, save
try:
    with open(RESULTS_FILE) as f:
        results = json.load(f)
except:
    results = []

results.append(result)
with open(RESULTS_FILE, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

status = "PASS" if passed else "FAIL"
print(f"{status} ({total:.2f}) [{elapsed:.1f}s]")
if rc:
    print(f"  -> {rc}: {rcd}")
