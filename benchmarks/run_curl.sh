#!/bin/bash
# Pure curl-based benchmark runner - minimal memory footprint
# Each case is a completely independent curl call

BASE_URL="http://localhost:8080"
RESULTS_DIR="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
RESULTS_FILE="${RESULTS_DIR}/agent1_all_results.json"
SCREENSHOT_DIR="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"

mkdir -p "$RESULTS_DIR" "$SCREENSHOT_DIR"

# Initialize results file if empty or missing
if [ ! -s "$RESULTS_FILE" ] || ! python3 -c "import json; json.load(open('$RESULTS_FILE'))" 2>/dev/null; then
    echo "[]" > "$RESULTS_FILE"
fi

send_and_score() {
    local cat_num=$1
    local case_idx=$2
    local cat_name=$3
    local case_id=$4
    local input_text=$5
    local expected_kw=$6
    local forbidden_kw=$7
    local hallucination_kw=$8
    local pass_threshold=$9

    # Skip if already done
    local already_done=$(python3 -c "
import json
d=json.load(open('$RESULTS_FILE'))
ids={r['case_id'] for r in d}
print('yes' if '$case_id' in ids else 'no')
" 2>/dev/null)
    if [ "$already_done" = "yes" ]; then
        return 0
    fi

    local session_id="a1_${cat_num}_${case_id}_$(date +%s%N | cut -c1-13)"
    local start_time=$(date +%s%N)

    # Send the request
    local response=$(curl -s -X POST "${BASE_URL}/api/chat" \
        -H "Content-Type: application/json" \
        -d "{\"message\": $(python3 -c "import json; print(json.dumps('$input_text'))"), \"clear_context\": true, \"session_id\": \"$session_id\"}" \
        --max-time 90 2>/dev/null)

    local end_time=$(date +%s%N)
    local response_time=$(python3 -c "print(f'{($end_time - $start_time) / 1000000000:.1f}')" 2>/dev/null)

    # Extract text content from SSE
    local text_content=$(echo "$response" | grep "^data:" | python3 -c "
import sys, json
chunks = []
for line in sys.stdin:
    line = line.strip()
    if line.startswith('data:'):
        try:
            obj = json.loads(line[5:])
            if 'content' in obj:
                chunks.append(obj['content'])
        except:
            pass
print(''.join(chunks))
" 2>/dev/null)

    # Score and save
    python3 -c "
import json, os
from datetime import datetime

response = '''$( echo "$text_content" | sed "s/'/\\\\'/g" )'''
# Better: read from a temp file approach
" 2>/dev/null

    # Actually, let's use a temp file approach
    local tmpfile=$(mktemp)
    echo "$text_content" > "$tmpfile"

    python3 - "$cat_num" "$cat_name" "$case_id" "$input_text" "$tmpfile" "$response_time" "$expected_kw" "$forbidden_kw" "$hallucination_kw" "$pass_threshold" "$RESULTS_FILE" "$SCREENSHOT_DIR" << 'PYTHON_SCRIPT'
import json, sys, os
from datetime import datetime

cat_num = int(sys.argv[1])
cat_name = sys.argv[2]
case_id = sys.argv[3]
input_text = sys.argv[4]
tmpfile = sys.argv[5]
response_time = float(sys.argv[6])
expected_kw_str = sys.argv[7]
forbidden_kw_str = sys.argv[8]
hallucination_kw_str = sys.argv[9]
pass_threshold = float(sys.argv[10])
results_file = sys.argv[11]
screenshot_dir = sys.argv[12]

with open(tmpfile) as f:
    response = f.read().strip()
os.unlink(tmpfile)

if not response:
    response = "Error: Empty response"

# Score
scores = {"keyword": 0.0, "completeness": 0.0, "safety": 1.0, "accuracy": 1.0, "ux": 1.0}

expected = [kw.strip() for kw in expected_kw_str.split(',') if kw.strip()]
if expected:
    matched = sum(1 for kw in expected if kw.lower() in response.lower())
    scores["keyword"] = matched / len(expected) if expected else 0

forbidden = [kw.strip() for kw in forbidden_kw_str.split(',') if kw.strip()]
for kw in forbidden:
    if kw.lower() in response.lower():
        scores["safety"] = 0.0
        break

hallucination = [kw.strip() for kw in hallucination_kw_str.split(',') if kw.strip()]
for kw in hallucination:
    if kw.lower() in response.lower():
        scores["accuracy"] -= 0.5

if len(response) < 100:
    scores["completeness"] = 0.5
elif len(response) > 5000:
    scores["ux"] -= 0.3
    scores["completeness"] = 1.0
else:
    scores["completeness"] = 1.0

total = scores["keyword"]*0.4 + scores["completeness"]*0.2 + scores["safety"]*0.2 + scores["accuracy"]*0.1 + scores["ux"]*0.1
passed = total >= pass_threshold and scores["safety"] > 0

rc = rcd = None
if not passed:
    for hp in ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]:
        if hp.lower() in response.lower():
            rc, rcd = "hallucination", f'Contains: "{hp}"'
            break
    if not rc:
        for kw in forbidden:
            if kw.lower() in response.lower():
                rc, rcd = "safety_leak", f'Forbidden: "{kw}"'
                break
    if not rc and len(response) < 100:
        rc, rcd = "too_brief", f"{len(response)} chars"
    if not rc and len(response) > 5000:
        rc, rcd = "too_verbose", f"{len(response)} chars"
    if not rc and expected:
        m = sum(1 for kw in expected if kw.lower() in response.lower())
        if m == 0:
            rc, rcd = "keyword_missing", "No keywords found"
    if not rc:
        rc, rcd = "wrong_answer", "Does not meet expectations"

screenshot_path = f"{screenshot_dir}/{cat_num:02d}_{case_id}.png"
if not os.path.exists(screenshot_path):
    screenshot_path = None

result = {
    "case_id": case_id, "category": cat_name, "category_num": cat_num,
    "input": input_text, "response": response[:1500], "response_length": len(response),
    "total_score": total, "dimension_scores": scores, "passed": passed,
    "root_cause": rc, "root_cause_detail": rcd, "response_time": response_time,
    "screenshot": screenshot_path, "timestamp": datetime.now().isoformat()
}

# Load and append
if os.path.exists(results_file):
    with open(results_file) as f:
        all_results = json.load(f)
else:
    all_results = []

all_results.append(result)
with open(results_file, 'w') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)

status = "PASS" if passed else "FAIL"
print(f"{case_id} {status} ({total:.2f}) [{response_time}s]")
PYTHON_SCRIPT
}

# Process all categories
for cat_num in $(seq 1 9); do
    # Get category info from JSON
    info=$(python3 -c "
import json, glob
files = glob.glob(f'/home/lht/snap/brachyplan/BrachyBot/benchmarks/{cat_num:02d}_*.json')
if not files: sys.exit(1)
with open(files[0]) as f: data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data
cat_name = os.path.basename(files[0]).replace('.json', '')
for i, tc in enumerate(cases):
    case_id = tc.get('id', f'Q{i+1:04d}')
    ek = ','.join(tc.get('expected_keywords', []))
    fk = ','.join(tc.get('forbidden_keywords', []))
    hk = ','.join(tc.get('hallucination_keywords', []))
    pt = tc.get('pass_threshold', 0.6)
    print(f'{cat_name}|{case_id}|{ek}|{fk}|{hk}|{pt}|{\"|\".join(tc.get(\"expected_keywords\", []))}')
" 2>/dev/null)

    while IFS='|' read -r cat_name case_id ek fk hk pt ek_raw; do
        if [ -z "$case_id" ]; then continue; fi

        echo "Processing: $cat_num - $case_id"

        # The input text needs to be extracted properly
        input_text=$(python3 -c "
import json, glob
files = glob.glob(f'/home/lht/snap/brag/{cat_num:02d}_*.json')
" 2>/dev/null)

        # Use curl to send and score
        send_and_score "$cat_num" "$case_id" "$cat_name" "$ek" "$fk" "$hk" "$pt"
    done <<< "$info"
done

echo "Done. Total files in results:"
python3 -c "
import json
with open('$RESULTS_FILE') as f:
    d = json.load(f)
print(f'{len(d)} entries')
" 2>/dev/null
SCRIPT
chmod +x /tmp/run_curl.sh
echo "Script generated. Due to complexity of input text extraction, using Python for the main loop."
