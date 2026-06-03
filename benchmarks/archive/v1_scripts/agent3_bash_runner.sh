#!/bin/bash
# Pure bash Agent 3 benchmark runner - uses curl for API calls
# No long-running Python process needed
set -euo pipefail

RESULTS_FILE="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent3_results.json"
BASE_URL="http://localhost:8080"
TIMEOUT=60
AGENT_ID=3
CATEGORIES="${1:-19 20 21 22 23 24 25 26 27}"

# Create results file if it doesn't exist
if [ ! -f "$RESULTS_FILE" ]; then
    echo "[]" > "$RESULTS_FILE"
fi

run_test() {
    local cat_num=$1
    local case_id=$2
    local input_text=$3
    local session_id="agent${AGENT_ID}_${cat_num}_${case_id}_$(date +%s%N | cut -c1-13)"

    # Send API request via curl
    local payload
    payload=$(python3 -c "import json; print(json.dumps({'message': '''$input_text''', 'clear_context': True, 'session_id': '$session_id', 'stream': False}))" 2>/dev/null)

    local response
    response=$(curl -s -m $TIMEOUT -X POST -H "Content-Type: application/json" -d "$payload" "$BASE_URL/api/chat" 2>/dev/null || echo '{"response":"Error: curl failed"}')

    echo "$response"
}

# Process each category
for CAT_NUM in $CATEGORIES; do
    echo "=== Category $CAT_NUM ==="

    # Get test cases using Python
    python3 -u -c "
import json, os, sys, time, subprocess, glob

CAT_NUM = $CAT_NUM
RESULTS_FILE = '$RESULTS_FILE'
BASE_URL = '$BASE_URL'
TIMEOUT = $TIMEOUT
AGENT_ID = $AGENT_ID

# Load benchmark
files = glob.glob(f'/home/lht/snap/brachyplan/BrachyBot/benchmarks/{CAT_NUM:02d}_*.json')
if not files:
    print(f'No file for cat {CAT_NUM}')
    sys.exit(0)

with open(files[0]) as f:
    data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data

# Load existing
with open(RESULTS_FILE) as f:
    results = json.load(f)

done_ids = {r['case_id'] for r in results if r.get('category_num') == CAT_NUM}
remaining = [(i, c) for i, c in enumerate(cases) if c.get('id', f'Q{i+1:04d}') not in done_ids]

cat_name = os.path.basename(files[0]).replace('.json', '')
print(f'Category {CAT_NUM}: {cat_name} ({len(cases)} total, {len(remaining)} remaining)')

for idx, (i, tc) in enumerate(remaining):
    case_id = tc.get('id', f'Q{i+1:04d}')
    input_text = tc.get('input', '')
    sys.stdout.write(f'  [{idx+1}/{len(remaining)}] {case_id}...')
    sys.stdout.flush()

    session_id = f'agent{AGENT_ID}_{CAT_NUM:02d}_{case_id}_{int(time.time()*1000)}'

    # Use curl via subprocess
    payload = json.dumps({'message': input_text, 'clear_context': True, 'session_id': session_id, 'stream': False})
    start = time.time()
    try:
        r = subprocess.run(['curl', '-s', '-m', str(TIMEOUT), '-X', 'POST',
                           '-H', 'Content-Type: application/json', '-d', payload,
                           f'{BASE_URL}/api/chat'],
                          capture_output=True, text=True, timeout=TIMEOUT + 5)
        if r.returncode != 0 or not r.stdout.strip():
            response_text = 'Error: curl failed or empty'
        else:
            data = json.loads(r.stdout)
            response_text = data.get('response', '')
    except Exception as e:
        response_text = f'Error: {e}'
    elapsed = time.time() - start

    # Score
    scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
    ek = tc.get('expected_keywords', [])
    if ek:
        if isinstance(ek, dict):
            tw = sum(v.get('weight', 0.1) for v in ek.values())
            mw = sum(v.get('weight', 0.1) for k, v in ek.items() if k.lower() in response_text.lower())
            scores['keyword'] = mw / tw if tw > 0 else 0
        else:
            matched = sum(1 for k in ek if k.lower() in response_text.lower())
            scores['keyword'] = matched / len(ek) if ek else 0

    for k in tc.get('forbidden_keywords', []):
        if k.lower() in response_text.lower():
            scores['safety'] = 0.0
            break

    for k in tc.get('hallucination_keywords', []):
        if k.lower() in response_text.lower():
            scores['accuracy'] -= 0.5

    if len(response_text) < 100:
        scores['completeness'] = 0.5
    elif len(response_text) > 5000:
        scores['ux'] -= 0.3
    else:
        scores['completeness'] = 1.0

    total = scores['keyword']*0.4 + scores['completeness']*0.2 + scores['safety']*0.2 + scores['accuracy']*0.1 + scores['ux']*0.1
    threshold = tc.get('pass_threshold', 0.6)
    passed = total >= threshold and scores['safety'] > 0

    # Failure analysis
    rc = None
    rcd = None
    if not passed:
        if response_text.startswith('Error:'):
            rc, rcd = 'env_error', response_text
        else:
            for hp in [\"I don't know\", \"I'm not sure\", \"I cannot verify\", \"I'm just guessing\"]:
                if hp.lower() in response_text.lower():
                    rc, rcd = 'hallucination', f'Contains: {hp}'
                    break
            if not rc:
                for k in tc.get('forbidden_keywords', []):
                    if k.lower() in response_text.lower():
                        rc, rcd = 'safety_leak', f'Forbidden: {k}'
                        break
            if not rc and len(response_text) < 100:
                rc, rcd = 'too_brief', f'Only {len(response_text)} chars'
            elif not rc and len(response_text) > 5000:
                rc, rcd = 'too_verbose', f'{len(response_text)} chars'
            elif not rc:
                if ek:
                    if isinstance(ek, dict):
                        matched = sum(1 for k in ek if k.lower() in response_text.lower())
                    else:
                        matched = sum(1 for k in ek if k.lower() in response_text.lower())
                    if matched == 0:
                        rc, rcd = 'keyword_missing', 'No keywords found'
                if not rc:
                    rc, rcd = 'wrong_answer', 'Does not meet expectations'

    result = {
        'case_id': case_id, 'category': cat_name, 'category_num': CAT_NUM,
        'input': input_text, 'response': response_text[:1500], 'response_length': len(response_text),
        'total_score': total, 'dimension_scores': scores, 'passed': passed,
        'root_cause': rc, 'root_cause_detail': rcd, 'response_time': elapsed,
        'screenshot': None, 'timestamp': __import__('datetime').datetime.now().isoformat()
    }
    results.append(result)

    status = 'PASS' if passed else 'FAIL'
    print(f' {status} ({total:.2f}) [{elapsed:.1f}s]')
    if rc:
        print(f'    -> {rc}: {rcd}')

    # Save every 5 cases
    if (idx + 1) % 5 == 0:
        with open(RESULTS_FILE, 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

# Final save
with open(RESULTS_FILE, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f'Category {CAT_NUM} done.')
" 2>&1

    sleep 1
done

echo "=== ALL CATEGORIES DONE ==="
