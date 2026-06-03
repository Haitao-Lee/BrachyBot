#!/bin/bash
# Master runner for Agent 2 - runs all remaining categories
# Usage: bash agent2_master.sh
LOG="/tmp/agent2_master.log"
cd /home/lht/snap/brachyplan/BrachyBot

echo "======================================" >> $LOG
echo "Agent 2 Master Runner started at $(date)" >> $LOG

# Run categories that have remaining cases, one at a time
# Uses --no-screenshots to avoid OOM, screenshots taken separately
for cat in 10 11 12 14 15 17 18; do
    echo "" >> $LOG
    echo ">>> Starting category $cat at $(date)" >> $LOG
    python benchmarks/agent2_fast_runner.py 2 $cat --no-screenshots >> $LOG 2>&1
    EXIT_CODE=$?
    echo ">>> Category $cat finished with exit code $EXIT_CODE at $(date)" >> $LOG

    # Check screenshots for this category
    COUNT=$(ls docs/benchmark_result/screenshots/${cat}_*.png 2>/dev/null | wc -l)
    TOTAL=$(python3 -c "import json,glob; d=json.load(open(glob.glob('benchmarks/${cat}_*.json')[0])); print(len(d.get('cases',d)))" 2>/dev/null)
    echo ">>> Category $cat screenshots: $COUNT/$TOTAL" >> $LOG
done

echo "" >> $LOG
echo ">>> All categories complete at $(date)" >> $LOG

# Take screenshots for all completed cases
echo ">>> Taking screenshots..." >> $LOG
for cat in 10 11 12 14 15 17 18; do
    python benchmarks/agent2_screenshot_taker.py 2 $cat >> $LOG 2>&1
done

echo ">>> Master runner finished at $(date)" >> $LOG
