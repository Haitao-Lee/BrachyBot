#!/bin/bash
# Resilient runner: restart on OOM kills, skip done cases
SCRIPT="/home/lht/snap/brachyplan/BrachyBot/benchmarks/agent1_mini.py"
RESULTS="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_all_results.json"
TOTAL_CASES=564

for attempt in $(seq 1 200); do
    # Count valid results
    VALID=$(python3 -c "
import json
d=json.load(open('$RESULTS'))
valid=[r for r in d if not r['response'].startswith('Error:')]
print(len(valid))
" 2>/dev/null)
    echo "[Attempt $attempt] Valid: $VALID / $TOTAL_CASES"

    if [ "$VALID" -ge "$TOTAL_CASES" ]; then
        echo "ALL DONE!"
        break
    fi

    # Find the next category that needs work
    for cat in 1 2 3 4 5 6 7 8 9; do
        FILE=$(ls /home/lht/snap/brachyplan/BrachyBot/benchmarks/$(printf '%02d' $cat)_*.json 2>/dev/null | head -1)
        if [ -z "$FILE" ]; then continue; fi
        COUNT=$(python3 -c "import json; d=json.load(open('$FILE')); c=d.get('cases',d) if isinstance(d,dict) else d; print(len(c))" 2>/dev/null)

        for ((i=0; i<COUNT; i++)); do
            timeout 120 python3 -u "$SCRIPT" "$cat" "$i" 2>&1
            RET=$?
            if [ $RET -eq 137 ] || [ $RET -eq 124 ]; then
                # OOM killed or timeout - break inner loop, check server
                HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ 2>/dev/null)
                if [ "$HTTP" != "200" ]; then
                    echo "Server down, waiting 30s..."
                    sleep 30
                fi
                break  # Go to next attempt
            fi
        done
    done
done

# Final report
python3 -c "
import json
d=json.load(open('$RESULTS'))
valid=[r for r in d if not r['response'].startswith('Error:')]
cats={}
for r in valid:
    cn=r['category_num']
    cats[cn]=cats.get(cn,0)+1
print(f'FINAL: {len(valid)} valid results')
for k in sorted(cats):
    print(f'  Cat {k}: {cats[k]}')
"