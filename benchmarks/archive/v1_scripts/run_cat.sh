#!/bin/bash
# Run a single category, one test case at a time (each as separate Python process)
# Usage: bash run_cat.sh <category_num>

CAT_NUM=$1
RESULTS_FILE="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent3_results.json"
SCRIPT="/home/lht/snap/brachyplan/BrachyBot/benchmarks/run_single_test.py"

echo "=== Running category $CAT_NUM ==="

python3 -u -c "
import json, glob

CAT_NUM = $CAT_NUM
files = glob.glob(f'/home/lht/snap/brachyplan/BrachyBot/benchmarks/{CAT_NUM:02d}_*.json')
with open(files[0]) as f:
    data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data

# Load existing
with open('$RESULTS_FILE') as f:
    existing = json.load(f)
done = {r['case_id'] for r in existing if r.get('category_num') == CAT_NUM}

for i, c in enumerate(cases):
    cid = c.get('id', f'Q{i+1:04d}')
    if cid in done:
        continue
    print(cid)
" | while read CASE_ID; do
    echo -n "  $CASE_ID ... "
    python3 -u "$SCRIPT" "$CAT_NUM" "$CASE_ID" 2>&1
done

echo "=== Category $CAT_NUM done ==="
