#!/bin/bash
# Re-run only missing cases
SCRIPT="/home/lht/snap/brachyplan/BrachyBot/benchmarks/agent1_single.py"
BASE="/home/lht/snap/brachyplan/BrachyBot/benchmarks"

# Category 6: missing indices 67-157 (0-based)
echo "=== Re-running Category 6 (indices 67-157) ==="
for ((i=67; i<=157; i++)); do
    python3 "$SCRIPT" 6 "$i" 2>&1
    RET=$?
    if [ $RET -ne 0 ]; then
        echo "  RETRY case 6/$i..."
        sleep 3
        python3 "$SCRIPT" 6 "$i" 2>&1
    fi
done
echo "Cat 6 done"

# Category 7: all 30 cases
echo "=== Re-running Category 7 (0-29) ==="
FILE=$(ls ${BASE}/07_*.json | head -1)
COUNT=$(python3 -c "import json; d=json.load(open('$FILE')); c=d.get('cases',d) if isinstance(d,dict) else d; print(len(c))")
for ((i=0; i<COUNT; i++)); do
    python3 "$SCRIPT" 7 "$i" 2>&1
    RET=$?
    if [ $RET -ne 0 ]; then
        echo "  RETRY case 7/$i..."
        sleep 3
        python3 "$SCRIPT" 7 "$i" 2>&1
    fi
done
echo "Cat 7 done"

# Category 8: all 30 cases
echo "=== Re-running Category 8 (0-29) ==="
FILE=$(ls ${BASE}/08_*.json | head -1)
COUNT=$(python3 -c "import json; d=json.load(open('$FILE')); c=d.get('cases',d) if isinstance(d,dict) else d; print(len(c))")
for ((i=0; i<COUNT; i++)); do
    python3 "$SCRIPT" 8 "$i" 2>&1
    RET=$?
    if [ $RET -ne 0 ]; then
        echo "  RETRY case 8/$i..."
        sleep 3
        python3 "$SCRIPT" 8 "$i" 2>&1
    fi
done
echo "Cat 8 done"

# Category 9: all 60 cases
echo "=== Re-running Category 9 (0-59) ==="
FILE=$(ls ${BASE}/09_*.json | head -1)
COUNT=$(python3 -c "import json; d=json.load(open('$FILE')); c=d.get('cases',d) if isinstance(d,dict) else d; print(len(c))")
for ((i=0; i<COUNT; i++)); do
    python3 "$SCRIPT" 9 "$i" 2>&1
    RET=$?
    if [ $RET -ne 0 ]; then
        echo "  RETRY case 9/$i..."
        sleep 3
        python3 "$SCRIPT" 9 "$i" 2>&1
    fi
done
echo "Cat 9 done"

echo "=== ALL REMAINING CASES DONE ==="
