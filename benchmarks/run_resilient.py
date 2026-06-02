#!/usr/bin/env python3
"""
Resilient runner for large categories.
Handles server crashes by checking server health between requests.
Restarts server when it becomes unresponsive.
"""
import json, sys, os, time, glob, subprocess

CAT_NUM = int(sys.argv[1])
BASE_URL = "http://localhost:8080"
RESULTS_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent3_results.json"
AGENT_ID = 3
TIMEOUT = 45  # 45s timeout - complex queries take 30-50s
MAX_RETRIES = 2

def check_server():
    try:
        r = subprocess.run(
            ['curl', '-s', '-m', '10', '-X', 'POST', '-H', 'Content-Type: application/json',
             '-d', '{"message":"ping","session_id":"healthcheck","clear_context":true,"stream":false}',
             f'{BASE_URL}/api/chat'],
            capture_output=True, text=True, timeout=15
        )
        return r.returncode == 0 and len(r.stdout) > 10
    except:
        return False

def restart_server():
    try:
        subprocess.run(['pkill', '-f', 'web/server.py'], timeout=5)
    except:
        pass
    time.sleep(3)
    subprocess.Popen(
        ['python3', '/home/lht/snap/brachyplan/BrachyBot/web/server.py'],
        stdout=open('/tmp/server_restart.log', 'w'),
        stderr=subprocess.STDOUT,
        cwd='/home/lht/snap/brachyplan/BrachyBot'
    )
    time.sleep(8)
    return check_server()

def send_request(input_text, session_id):
    payload = json.dumps({"message": input_text, "clear_context": True, "session_id": session_id, "stream": False})
    try:
        r = subprocess.run(
            ['curl', '-s', '-m', str(TIMEOUT), '-X', 'POST',
             '-H', 'Content-Type: application/json', '-d', payload,
             f'{BASE_URL}/api/chat'],
            capture_output=True, text=True, timeout=TIMEOUT + 5
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout).get('response', '')
        return f'Error: curl failed (rc={r.returncode})'
    except:
        return 'Error: request failed'

def score_response(response, test_case):
    scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
    ek = test_case.get('expected_keywords', [])
    if ek:
        if isinstance(ek, dict):
            tw = sum(v.get('weight', 0.1) for v in ek.values())
            mw = sum(v.get('weight', 0.1) for k, v in ek.items() if k.lower() in response.lower())
            scores['keyword'] = mw / tw if tw > 0 else 0
        else:
            scores['keyword'] = sum(1 for k in ek if k.lower() in response.lower()) / len(ek) if ek else 0

    for k in test_case.get('forbidden_keywords', []):
        if k.lower() in response.lower():
            scores['safety'] = 0.0
            break

    for k in test_case.get('hallucination_keywords', []):
        if k.lower() in response.lower():
            scores['accuracy'] -= 0.5

    if len(response) < 100: scores['completeness'] = 0.5
    elif len(response) > 5000: scores['ux'] -= 0.3
    else: scores['completeness'] = 1.0

    total = scores['keyword']*0.4 + scores['completeness']*0.2 + scores['safety']*0.2 + scores['accuracy']*0.1 + scores['ux']*0.1
    return total, scores

def analyze_failure(response, test_case):
    if response.startswith('Error:'):
        return 'env_error', response
    for hp in ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]:
        if hp.lower() in response.lower():
            return 'hallucination', f'Contains: {hp}'
    for k in test_case.get('forbidden_keywords', []):
        if k.lower() in response.lower():
            return 'safety_leak', f'Forbidden: {k}'
    if len(response) < 100: return 'too_brief', f'Only {len(response)} chars'
    if len(response) > 5000: return 'too_verbose', f'{len(response)} chars'
    ek = test_case.get('expected_keywords', [])
    if ek and isinstance(ek, list):
        if sum(1 for k in ek if k.lower() in response.lower()) == 0:
            return 'keyword_missing', 'No keywords found'
    return 'wrong_answer', 'Does not meet expectations'

# Load benchmark
files = glob.glob(f"/home/lht/snap/brachyplan/BrachyBot/benchmarks/{CAT_NUM:02d}_*.json")
with open(files[0]) as f:
    data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data
cat_name = os.path.basename(files[0]).replace('.json', '')

# Load existing results
try:
    with open(RESULTS_FILE) as f:
        results = json.load(f)
except:
    results = []

done_ids = {r['case_id'] for r in results if r.get('category_num') == CAT_NUM}
remaining = [(i, c) for i, c in enumerate(cases) if c.get('id', f'Q{i+1:04d}') not in done_ids]

print(f"\nCategory {CAT_NUM}: {cat_name} ({len(cases)} total, {len(remaining)} remaining)", flush=True)

# Check server
if not check_server():
    print("  Server not responding, restarting...", flush=True)
    if not restart_server():
        print("  ERROR: Could not restart server", flush=True)
        sys.exit(1)
    print("  Server restarted OK", flush=True)

consecutive_failures = 0
for idx, (i, tc) in enumerate(remaining):
    case_id = tc.get('id', f'Q{i+1:04d}')
    input_text = tc.get('input', '')

    # Check server health every 10 cases
    if idx > 0 and idx % 10 == 0:
        if not check_server():
            print(f"  [Server down at case {idx}, restarting...]", flush=True)
            if restart_server():
                print(f"  [Server restarted OK]", flush=True)
            else:
                print(f"  [ERROR: Server restart failed]", flush=True)
                consecutive_failures += 20

    # If too many consecutive failures, try restarting server
    if consecutive_failures >= 5:
        print(f"  [Too many failures, restarting server...]", flush=True)
        if restart_server():
            print(f"  [Server restarted]", flush=True)
            consecutive_failures = 0
        else:
            print(f"  [Server restart failed, continuing...]", flush=True)

    sys.stdout.write(f"  [{idx+1}/{len(remaining)}] {case_id}...")
    sys.stdout.flush()

    session_id = f"agent{AGENT_ID}_{CAT_NUM:02d}_{case_id}_{int(time.time()*1000)}"
    start = time.time()
    response = send_request(input_text, session_id)
    elapsed = time.time() - start

    total, scores = score_response(response, tc)
    threshold = tc.get('pass_threshold', 0.6)
    passed = total >= threshold and scores['safety'] > 0

    rc = rcd = None
    if not passed:
        rc, rcd = analyze_failure(response, tc)

    result = {
        'case_id': case_id, 'category': cat_name, 'category_num': CAT_NUM,
        'input': input_text, 'response': response[:1500], 'response_length': len(response),
        'total_score': total, 'dimension_scores': scores, 'passed': passed,
        'root_cause': rc, 'root_cause_detail': rcd, 'response_time': elapsed,
        'screenshot': None, 'timestamp': __import__('datetime').datetime.now().isoformat()
    }
    results.append(result)

    status = 'PASS' if passed else 'FAIL'
    print(f" {status} ({total:.2f}) [{elapsed:.1f}s]", flush=True)
    if rc:
        print(f"    -> {rc}: {rcd}", flush=True)
        if rc == 'env_error':
            consecutive_failures += 1
        else:
            consecutive_failures = 0
    else:
        consecutive_failures = 0

    # Save after every case
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nCategory {CAT_NUM} complete.", flush=True)
