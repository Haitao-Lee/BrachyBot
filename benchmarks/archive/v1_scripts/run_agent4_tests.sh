#!/bin/bash
# Agent 4 batch runner - runs remaining tests one at a time
# Each test is a separate Python process for stability

BENCHMARK_DIR="/home/lht/snap/brachyplan/BrachyBot/benchmarks"
SCREENSHOT_DIR="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
RUNNER="/home/lht/snap/brachyplan/BrachyBot/benchmarks/agent4_single_test.py"
LOG="/home/lht/snap/brachyplan/BrachyBot/benchmarks/agent4_batch_run.log"

# Categories to run, in order of priority (most incomplete first)
CATEGORIES=(23 19 15)

echo "$(date '+%Y-%m-%d %H:%M:%S') Agent 4 batch runner started" >> "$LOG"
echo "Categories: ${CATEGORIES[*]}" >> "$LOG"

for CAT_NUM in "${CATEGORIES[@]}"; do
    echo "" >> "$LOG"
    echo "$(date '+%H:%M:%S') === Category $CAT_NUM ===" >> "$LOG"

    # Get remaining case IDs
    REMAINING=$(python3 -c "
import json, glob, os
files = glob.glob('$BENCHMARK_DIR/${CAT_NUM}_*.json')
if not files: exit()
with open(files[0]) as f: data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data
done = set()
for f in glob.glob('$SCREENSHOT_DIR/${CAT_NUM}_*.png'):
    if os.path.getsize(f) > 1000:
        cid = os.path.basename(f).replace('${CAT_NUM}_', '').replace('.png', '')
        done.add(cid)
for tc in cases:
    cid = tc.get('id', '')
    if cid and cid not in done:
        print(cid)
" 2>/dev/null)

    COUNT=0
    TOTAL=$(echo "$REMAINING" | wc -l)
    PASSED=0
    FAILED=0

    for CASE_ID in $REMAINING; do
        COUNT=$((COUNT + 1))
        echo -n "$(date '+%H:%M:%S') [Cat $CAT_NUM $COUNT/$TOTAL] $CASE_ID ... " >> "$LOG"

        # Run the single test
        RESULT=$(python3 "$RUNNER" "$CAT_NUM" "$CASE_ID" 2>&1)
        EXIT_CODE=$?

        echo "$RESULT" >> "$LOG"

        if [ $EXIT_CODE -eq 2 ]; then
            echo "$(date '+%H:%M:%S') Server offline, waiting 60s" >> "$LOG"
            sleep 60
        elif [ $EXIT_CODE -eq 3 ]; then
            FAILED=$((FAILED + 1))
            sleep 5
        elif echo "$RESULT" | grep -q "^PASS"; then
            PASSED=$((PASSED + 1))
        else
            FAILED=$((FAILED + 1))
        fi

        # Small delay between tests
        sleep 2
    done

    echo "$(date '+%H:%M:%S') Category $CAT_NUM done: $PASSED passed, $FAILED failed out of $TOTAL" >> "$LOG"
done

echo "" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') Agent 4 batch runner completed" >> "$LOG"
