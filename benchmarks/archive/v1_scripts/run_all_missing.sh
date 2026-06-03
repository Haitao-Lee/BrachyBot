#!/bin/bash
# Run all missing benchmark cases one at a time
# Usage: bash run_all_missing.sh <cat1> <cat2> ...
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

for CAT in "$@"; do
    CAT=$(printf "%02d" $CAT)
    echo "=== Processing Category $CAT ==="

    # Get missing case count
    MISSING=$(python3 -c "
import json, glob, os
files = glob.glob('benchmarks/${CAT}_*.json')
if not files: print(0); exit()
with open(files[0]) as f:
    data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data
screenshots = glob.glob('docs/benchmark_result/screenshots/${CAT}_*.png')
completed = set()
for s in screenshots:
    bn = os.path.basename(s)
    cid = bn.replace('${CAT}_', '').replace('.png', '')
    completed.add(cid)
missing = [c for c in cases if c.get('id') not in completed]
print(len(missing))
")
    echo "  Missing: $MISSING cases"

    if [ "$MISSING" = "0" ]; then
        echo "  All complete!"
        continue
    fi

    # Run each missing case
    for ((i=0; i<MISSING; i++)); do
        echo -n "  [$((i+1))/$MISSING] "
        timeout 300 python3 "$SCRIPT_DIR/run_single_missing.py" $CAT $i 2>&1
        RESULT=$?
        if [ $RESULT -eq 124 ]; then
            echo "TIMEOUT"
        fi
        # Brief pause between requests
        sleep 2
    done

    # Count final state
    DONE=$(ls docs/benchmark_result/screenshots/${CAT}_*.png 2>/dev/null | wc -l)
    TOTAL=$(python3 -c "
import json, glob
files = glob.glob('benchmarks/${CAT}_*.json')
with open(files[0]) as f:
    data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data
print(len(cases))
")
    echo "  Category $CAT: $DONE/$TOTAL completed"
done

echo "=== All categories processed ==="
