#!/bin/bash
# Run each case as a separate Python process to avoid OOM
# Each process handles exactly ONE test case and exits immediately
RESULTS_DIR="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result"
BENCHMARK_DIR="/home/lht/snap/brachyplan/BrachyBot/benchmarks"

for CAT_NUM in 10 12 13 14 15 16 17 18; do
    CAT_FILE=$(printf "%s/%02d_*.json" "$BENCHMARK_DIR" "$CAT_NUM")
    CAT_FILE=$(ls $CAT_FILE 2>/dev/null | head -1)
    if [ -z "$CAT_FILE" ]; then
        echo "No file for category $CAT_NUM"
        continue
    fi

    RESULTS_FILE=$(printf "%s/cat%02d_results.json" "$RESULTS_DIR" "$CAT_NUM")

    # Check how many already done
    if [ -f "$RESULTS_FILE" ]; then
        DONE=$(python3 -c "import json; d=json.load(open('$RESULTS_FILE')); print(len(d))")
    else
        DONE=0
    fi

    TOTAL=$(python3 -c "import json; d=json.load(open('$CAT_FILE')); c=d.get('cases',d) if isinstance(d,dict) else d; print(len(c))")
    echo "Category $CAT_NUM: $DONE/$TOTAL done"

    # Run remaining cases
    python3 -c "
import json, os, sys, time, requests

CAT_NUM = $CAT_NUM
BASE_URL = 'http://localhost:8080'
RESULTS_DIR = '$RESULTS_DIR'
RESULTS_FILE = '$RESULTS_FILE'

with open('$CAT_FILE', 'r') as f:
    data = json.load(f)
    cases = data.get('cases', data) if isinstance(data, dict) else data

cat_name = os.path.basename('$CAT_FILE').replace('.json', '')

# Load existing
existing = []
if os.path.exists(RESULTS_FILE):
    with open(RESULTS_FILE, 'r') as f:
        existing = json.load(f)
existing_ids = {r['case_id'] for r in existing}
results = list(existing)

session_id = f'agent2_cat{CAT_NUM:02d}'

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
    for kw in [\"I don't know\", \"I'm not sure\", \"I cannot verify\", \"I'm just guessing\"]:
        if kw.lower() in response.lower():
            return 'hallucination', f'Contains uncertainty phrase: \"{kw}\"'
    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            return 'safety_leak', f'Contains forbidden keyword: \"{kw}\"'
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

for i, case in enumerate(cases):
    case_id = case.get('id', f'Q{i+1:04d}')
    if case_id in existing_ids:
        continue
    input_text = case.get('input', '')
    print(f'  [{i+1}/{len(cases)}] {case_id}...', end=' ', flush=True)
    try:
        r = requests.post(f'{BASE_URL}/api/chat',
            json={'message': input_text, 'clear_context': True, 'session_id': session_id, 'stream': False},
            timeout=90)
        response = r.json().get('response', '')
    except Exception as e:
        response = f'Error: {str(e)}'
    total_score, dim_scores = score_response(response, case)
    pass_threshold = case.get('pass_threshold', 0.6)
    passed = total_score >= pass_threshold and dim_scores['safety'] > 0
    root_cause, root_cause_detail = (None, None)
    if not passed:
        root_cause, root_cause_detail = analyze_failure(response, case)
    result = {
        'case_id': case_id, 'category': cat_name, 'category_num': CAT_NUM,
        'input': input_text, 'response': response[:1500], 'response_length': len(response),
        'total_score': total_score, 'dimension_scores': dim_scores, 'passed': passed,
        'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
        'response_time': 0, 'screenshot': None,
        'timestamp': __import__('datetime').datetime.now().isoformat()
    }
    results.append(result)
    existing_ids.add(case_id)
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f)
    status = 'PASS' if passed else 'FAIL'
    print(f'{status} ({total_score:.2f})')
    if root_cause:
        print(f'    -> {root_cause}: {root_cause_detail}')
    time.sleep(0.5)
print(f'Category {CAT_NUM} complete: {sum(1 for r in results if r[\"passed\"])}/{len(results)} passed')
"
    echo "Category $CAT_NUM finished"
done
echo "ALL CATEGORIES DONE"
