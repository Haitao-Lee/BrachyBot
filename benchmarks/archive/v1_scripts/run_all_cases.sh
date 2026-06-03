#!/bin/bash
# Run all benchmark cases one at a time, saving results incrementally

SCRIPT="/home/lht/snap/brachyplan/BrachyBot/benchmarks/agent1_single.py"
BASE="/home/lht/snap/brachyplan/BrachyBot/benchmarks"

for cat in 01 02 03 04 05 06 07 08 09; do
    # Find the file
    FILE=$(ls ${BASE}/${cat}_*.json 2>/dev/null | head -1)
    if [ -z "$FILE" ]; then
        echo "No file for category $cat, skipping"
        continue
    fi
    COUNT=$(python3 -c "import json; d=json.load(open('$FILE')); c=d.get('cases',d) if isinstance(d,dict) else d; print(len(c))")
    echo "Category $cat: $COUNT cases (file: $(basename $FILE))"

    for ((i=0; i<COUNT; i++)); do
        python3 "$SCRIPT" "$((10#$cat))" "$i" 2>&1
        RET=$?
        if [ $RET -ne 0 ]; then
            echo "  WARNING: case $i exited with code $RET, retrying in 3s..."
            sleep 3
            python3 "$SCRIPT" "$((10#$cat))" "$i" 2>&1
        fi
    done
    echo "Category $cat complete"
done

echo "ALL DONE"
