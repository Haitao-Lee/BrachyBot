#!/bin/bash
# Pure bash benchmark runner - one API call at a time
RESULTS_FILE="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent2_final_results.json"
LOG_FILE="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent2_bash.log"

echo "Bash benchmark runner started at $(date)" > "$LOG_FILE"

# Start fresh
rm -f "$RESULTS_FILE"
echo "[]" > "$RESULTS_FILE"

# Run each category
for CAT in 10 11 12 13 14 15 16 17 18; do
  FNAME=$(printf "/home/lht/snap/brachyplan/BrachyBot/benchmarks/%02d_*.json" $CAT)
  FNAME=$(ls $FNAME 2>/dev/null | head -1)
  if [ -z "$FNAME" ]; then continue; fi

  CAT_NAME=$(basename "$FNAME" .json)
  echo "Category $CAT: $CAT_NAME" >> "$LOG_FILE"
  echo "Category $CAT: $CAT_NAME"

  # Extract case count
  TOTAL=$(python3 -c "import json; d=json.load(open('$FNAME')); cases=d.get('cases',d) if isinstance(d,dict) else d; print(len(cases))")

  for ((i=0; i<TOTAL; i++)); do
    # Extract case data
    CASE_DATA=$(python3 -c "
import json, sys
with open('$FNAME') as f: d = json.load(f)
cases = d.get('cases', d) if isinstance(d, dict) else d
tc = cases[$i]
cid = tc.get('id', 'Q%04d' % ($i+1))
inp = tc.get('input', '')
ek = tc.get('expected_keywords', [])
fk = tc.get('forbidden_keywords', [])
hk = tc.get('hallucination_keywords', [])
th = tc.get('pass_threshold', 0.6)
diff = tc.get('difficulty', 'unknown')
print(json.dumps({'id': cid, 'input': inp, 'ek': ek, 'fk': fk, 'hk': hk, 'th': th, 'diff': diff}))
")

    CID=$(echo "$CASE_DATA" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['id'])")
    INPUT=$(echo "$CASE_DATA" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['input'])")

    printf "  [%d/%d] %s... " "$((i+1))" "$TOTAL" "$CID"

    # Send API request
    RESP=$(curl -s -X POST http://localhost:8080/api/chat \
      -H "Content-Type: application/json" \
      -d "{\"message\": $(echo "$INPUT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'), \"clear_context\": true, \"session_id\": \"a2_${CAT}_${CID}_$(date +%s%N)\", \"stream\": false}" \
      --max-time 120 2>/dev/null)

    # Extract response and score
    RESULT=$(python3 -c "
import json, sys, time

case_data = json.loads('''$CASE_DATA''')
resp_raw = '''$RESP'''

try:
    resp_json = json.loads(resp_raw)
    response = resp_json.get('response', '')
except:
    response = ''

# Score
scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
ek = case_data.get('ek', [])
if ek:
    if isinstance(ek, dict):
        tw = sum(v.get('weight', 0.1) for v in ek.values())
        mw = sum(v.get('weight', 0.1) for kw, v in ek.items() if kw.lower() in response.lower())
        scores['keyword'] = mw/tw if tw > 0 else 0
    else:
        m = sum(1 for kw in ek if kw.lower() in response.lower())
        scores['keyword'] = m/len(ek) if ek else 0
for kw in case_data.get('fk', []):
    if kw.lower() in response.lower():
        scores['safety'] = 0.0; break
for kw in case_data.get('hk', []):
    if kw.lower() in response.lower():
        scores['accuracy'] -= 0.5
if len(response) < 100: scores['completeness'] = 0.5
elif len(response) > 5000: scores['ux'] -= 0.3
else: scores['completeness'] = 1.0
total = scores['keyword']*0.4 + scores['completeness']*0.2 + scores['safety']*0.2 + scores['accuracy']*0.1 + scores['ux']*0.1
passed = total >= case_data.get('th', 0.6) and scores['safety'] > 0

# Root cause
rc = rcd = None
if not passed:
    for kw in [\"I don't know\", \"I'm not sure\", 'I cannot verify']:
        if kw.lower() in response.lower():
            rc, rcd = 'hallucination', 'Contains: ' + kw; break
    if not rc:
        for kw in case_data.get('fk', []):
            if kw.lower() in response.lower():
                rc, rcd = 'safety_leak', 'Forbidden: ' + kw; break
    if not rc and len(response) < 100:
        rc, rcd = 'too_brief', 'Short: %d chars' % len(response)
    if not rc and len(response) > 5000:
        rc, rcd = 'too_verbose', 'Long: %d chars' % len(response)
    if not rc:
        m = sum(1 for kw in ek if kw.lower() in response.lower())
        if m == 0 and ek:
            rc, rcd = 'keyword_missing', 'No keywords found'
    if not rc:
        rc, rcd = 'wrong_answer', 'Does not meet expectations'

print(json.dumps({
    'case_id': case_data['id'],
    'category_num': $CAT,
    'category': '$CAT_NAME',
    'input': case_data['input'][:500],
    'response': response[:2000],
    'response_length': len(response),
    'total_score': round(total, 3),
    'dimension_scores': scores,
    'passed': passed,
    'root_cause': rc,
    'root_cause_detail': rcd,
    'response_time': 0,
    'difficulty': case_data.get('diff', 'unknown'),
    'screenshot': None,
    'timestamp': '$(date -Iseconds)'
}))
")

    # Append to results file
    python3 -c "
import json
with open('$RESULTS_FILE') as f: results = json.load(f)
results.append(json.loads('''$RESULT'''))
with open('$RESULTS_FILE', 'w') as f: json.dump(results, f, indent=2, default=str)
"

    # Print result
    python3 -c "
import json, sys
r = json.loads('''$RESULT''')
status = 'PASS' if r['passed'] else 'FAIL'
print('%s (%.2f)' % (status, r['total_score']))
if r['root_cause']:
    print('    -> %s: %s' % (r['root_cause'], r['root_cause_detail']))
"

    # Rate limit
    sleep 2
  done

  echo "  Category $CAT complete" >> "$LOG_FILE"
done

echo "Done at $(date)" >> "$LOG_FILE"
echo "DONE"
