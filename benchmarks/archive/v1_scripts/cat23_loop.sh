#!/bin/bash
# Run category 23 tests one at a time in a loop
# Each test runs as a separate process to avoid timeout kills

RESULTS_FILE="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/agent4_cat23_results.json"
MAX_TESTS=199
TOTAL_DONE=0

echo "Category 23 Loop Runner - Starting at $(date)"

while true; do
    # Check how many done
    if [ -f "$RESULTS_FILE" ]; then
        TOTAL_DONE=$(python3 -c "import json; print(len(json.load(open('$RESULTS_FILE'))))" 2>/dev/null || echo "0")
    else
        TOTAL_DONE=0
    fi

    if [ "$TOTAL_DONE" -ge "$MAX_TESTS" ]; then
        echo "ALL DONE: $TOTAL_DONE/$MAX_TESTS tests completed"
        break
    fi

    # Run single test
    timeout 360 python3 /home/lht/snap/brachyplan/BrachyBot/benchmarks/cat23_one.py 2>&1
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 124 ]; then
        echo "  [TIMEOUT] Test timed out after 360s, retrying..."
        sleep 5
    elif [ $EXIT_CODE -eq 137 ]; then
        echo "  [KILLED] Process killed, waiting 10s..."
        sleep 10
    elif [ $EXIT_CODE -ne 0 ]; then
        echo "  [ERROR] Exit code $EXIT_CODE, waiting 5s..."
        sleep 5
    fi

    sleep 2
done

echo "Category 23 Loop Runner - Finished at $(date)"
echo "Total completed: $TOTAL_DONE/$MAX_TESTS"
