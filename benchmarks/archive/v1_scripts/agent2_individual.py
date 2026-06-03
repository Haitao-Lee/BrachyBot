#!/usr/bin/env python3
"""
Run individual test cases via subprocess calls.
Each case is a separate process - immune to OOM kills.
Results are appended to disk after each case.
"""
import json, os, sys, time, glob
from datetime import datetime

BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
RESULTS_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result"

CASE_RUNNER = '''
import json, os, sys, time, requests
from datetime import datetime as _dt

CAT_NUM = {cat_num}
CASE_INDEX = {case_index}
BASE_URL = "http://localhost:8080"
RESULTS_DIR = "{results_dir}"
RESULTS_FILE = "{results_file}"

with open("{cat_file}", 'r', encoding='utf-8') as f:
    data = json.load(f)
    cases = data.get('cases', data) if isinstance(data, dict) else data

case = cases[CASE_INDEX]
case_id = case.get('id', f'Q{{CASE_INDEX+1:04d}}')
cat_name = os.path.basename("{cat_file}").replace('.json', '')
session_id = f"agent2_cat{{CAT_NUM:02d}}"

# Load existing
existing_ids = set()
results = []
if os.path.exists(RESULTS_FILE):
    with open(RESULTS_FILE, 'r') as f:
        results = json.load(f)
    existing_ids = {{r['case_id'] for r in results}}

if case_id in existing_ids:
    sys.exit(0)

input_text = case.get('input', '')

try:
    r = requests.post(f"{{BASE_URL}}/api/chat",
        json={{"message": input_text, "clear_context": True, "session_id": session_id, "stream": False}},
        timeout=90)
    response = r.json().get('response', '')
except Exception as e:
    response = f"Error: {{str(e)}}"

scores = {{'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}}
expected_keywords = case.get('expected_keywords', [])
if expected_keywords:
    if isinstance(expected_keywords, dict):
        total_weight = sum(v.get('weight', 0.1) for v in expected_keywords.values())
        matched_weight = sum(v.get('weight', 0.1) for kw, v in expected_keywords.items() if kw.lower() in response.lower())
        scores['keyword'] = matched_weight / total_weight if total_weight > 0 else 0
    else:
        matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
        scores['keyword'] = matched / len(expected_keywords) if expected_keywords else 0
for kw in case.get('forbidden_keywords', []):
    if kw.lower() in response.lower():
        scores['safety'] = 0.0
        break
for kw in case.get('hallucination_keywords', []):
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

passed = total >= case.get('pass_threshold', 0.6) and scores['safety'] > 0

root_cause, root_cause_detail = None, None
if not passed:
    for kw in ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]:
        if kw.lower() in response.lower():
            root_cause, root_cause_detail = 'hallucination', f'Contains uncertainty: "{{kw}}"'
            break
    if not root_cause:
        for kw in case.get('forbidden_keywords', []):
            if kw.lower() in response.lower():
                root_cause, root_cause_detail = 'safety_leak', f'Forbidden keyword: "{{kw}}"'
                break
    if not root_cause and len(response) < 100:
        root_cause, root_cause_detail = 'too_brief', f'Response too short ({{len(response)}} chars)'
    elif not root_cause and len(response) > 5000:
        root_cause, root_cause_detail = 'too_verbose', f'Response too long ({{len(response)}} chars)'
    elif not root_cause:
        expected_keywords = case.get('expected_keywords', [])
        if expected_keywords:
            if isinstance(expected_keywords, dict):
                matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
            else:
                matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
            if matched == 0:
                root_cause, root_cause_detail = 'keyword_missing', 'No expected keywords found'
        if not root_cause:
            root_cause, root_cause_detail = 'wrong_answer', 'Response does not meet expectations'

result = {{
    'case_id': case_id, 'category': cat_name, 'category_num': CAT_NUM,
    'input': input_text, 'response': response[:1500], 'response_length': len(response),
    'total_score': total, 'dimension_scores': scores, 'passed': passed,
    'root_cause': root_cause, 'root_cause_detail': root_cause_detail,
    'response_time': 0, 'screenshot': None,
    'timestamp': _dt.now().isoformat()
}}

results.append(result)
with open(RESULTS_FILE, 'w') as f:
    json.dump(results, f)

status = "PASS" if passed else "FAIL"
print(f"{{status}} ({{total:.2f}}) {{case_id}}")
if root_cause:
    print(f"  -> {{root_cause}}: {{root_cause_detail}}")
'''

def run_individual_case(cat_num, case_index, cat_file, results_file):
    """Run a single test case as a subprocess."""
    import subprocess
    script = CASE_RUNNER.format(
        cat_num=cat_num,
        case_index=case_index,
        results_dir=RESULTS_DIR,
        results_file=results_file,
        cat_file=cat_file
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "PYTHONUNBUFFERED": "1"}
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            return False, f"exit={result.returncode}: {result.stderr[:100]}"
        return True, output
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)[:100]

if __name__ == "__main__":
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    categories = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else [10, 12, 13, 14, 15, 16, 17, 18]

    print(f"Agent {agent_id} Individual Case Runner")
    print(f"Categories: {categories}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    for cat_num in categories:
        files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
        if not files:
            print(f"  No file for category {cat_num}")
            continue

        cat_file = os.path.abspath(files[0])
        results_file = f"{RESULTS_DIR}/cat{cat_num:02d}_results.json"

        with open(cat_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            cases = data.get('cases', data) if isinstance(data, dict) else data

        # Check existing
        existing_count = 0
        if os.path.exists(results_file):
            with open(results_file, 'r') as f:
                existing_count = len(json.load(f))

        remaining = len(cases) - existing_count
        cat_name = os.path.basename(cat_file).replace('.json', '')
        print(f"\nCategory {cat_num}: {cat_name} ({len(cases)} total, {existing_count} done, {remaining} remaining)")

        for i in range(len(cases)):
            # Reload to check if already done
            if os.path.exists(results_file):
                with open(results_file, 'r') as f:
                    existing = json.load(f)
                existing_ids = {r['case_id'] for r in existing}
                case_id = cases[i].get('id', f'Q{i+1:04d}')
                if case_id in existing_ids:
                    continue

            success, output = run_individual_case(cat_num, i, cat_file, results_file)

            case_id = cases[i].get('id', f'Q{i+1:04d}')
            if success:
                status_line = output.split('\n')[0] if output else "OK"
                print(f"  [{i+1}/{len(cases)}] {status_line}")
            else:
                print(f"  [{i+1}/{len(cases)}] {case_id}: ERR - {output}")

            time.sleep(0.5)  # Rate limit

        # Final count
        if os.path.exists(results_file):
            with open(results_file, 'r') as f:
                final = json.load(f)
            passed = sum(1 for r in final if r['passed'])
            print(f"  Category {cat_num} complete: {passed}/{len(final)} passed")
        else:
            print(f"  Category {cat_num}: no results")

    print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
