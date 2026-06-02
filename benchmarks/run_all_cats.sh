#!/bin/bash
# Run all categories for Agent 3 benchmark
# Each category runs as a separate process to avoid long-running kill

PYTHON=/usr/bin/python3
SCRIPT="/home/lht/snap/brachyplan/BrachyBot/benchmarks/agent3_single_cat.py"
LOGDIR="/tmp/agent3_cat_logs"
mkdir -p $LOGDIR

for CAT in 19 20 21 22 23 24 25 26 27; do
    LOG="$LOGDIR/cat_${CAT}.log"
    echo "=== Starting category $CAT ===" >> $LOG
    echo "=== Starting category $CAT ==="

    $PYTHON -u "$SCRIPT" "$CAT" >> "$LOG" 2>&1
    EXIT=$?
    echo "=== Category $CAT finished with exit code $EXIT ===" >> $LOG
    echo "=== Category $CAT done (exit=$EXIT) ==="

    # Brief pause between categories
    sleep 2
done

echo "=== ALL CATEGORIES DONE ==="
