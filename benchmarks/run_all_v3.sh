#!/bin/bash
# Ultra-minimal runner: one case per Python invocation
# Each invocation uses <10MB and exits cleanly

SCRIPT="/home/lht/snap/brachyplan/BrachyBot/benchmarks/agent1_mini.py"
RESULTS="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_all_results.json"

# Initialize if needed
if [ ! -s "$RESULTS" ]; then echo "[]" > "$RESULTS"; fi

for cat in 1 2 3 4 5 6 7 8 9; do
    FILE=$(ls /home/lht/snap/brachyplan/BrachyBot/benchmarks/$(printf '%02d' $cat)_*.json 2>/dev/null | head -1)
    if [ -z "$FILE" ]; then continue; fi
    COUNT=$(python3 -c "import json; d=json.load(open('$FILE')); c=d.get('cases',d) if isinstance(d,dict) else d; print(len(c))")
    echo "CAT $cat: $COUNT cases"

    DONE=0
    ERR_COUNT=0
    for ((i=0; i<COUNT; i++)); do
        # Check if already done
        ALREADY=$(python3 -c "
import json
d=json.load(open('$RESULTS'))
ids={r['case_id'] for r in d}
import glob, os
files=glob.glob('/home/lht/snap/brachyplan/BrachyBot/benchmarks/$(printf '%02d' $cat)_*.json')
with open(files[0]) as f: data=json.load(f)
cases=data.get('cases',data) if isinstance(data,dict) else data
cid=cases[$i].get('id', f'Q$(printf '%04d' $((i+1)))')
print('yes' if cid in ids else 'no')
" 2>/dev/null)
        if [ "$ALREADY" = "yes" ]; then
            DONE=$((DONE + 1))
            continue
        fi

        timeout 90 python3 -u "$SCRIPT" "$cat" "$i" 2>&1
        RET=$?

        if [ $RET -eq 0 ]; then
            DONE=$((DONE + 1))
            ERR_COUNT=0
        elif [ $RET -eq 124 ]; then
            echo "  TIMEOUT at index $i"
            ERR_COUNT=$((ERR_COUNT + 1))
        else
            ERR_COUNT=$((ERR_COUNT + 1))
        fi

        # If too many consecutive errors, check server
        if [ $ERR_COUNT -ge 3 ]; then
            HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ 2>/dev/null)
            if [ "$HTTP" != "200" ]; then
                echo "  Server down! Waiting 30s..."
                sleep 30
                ERR_COUNT=0
            else
                ERR_COUNT=0
            fi
        fi

        # Tiny delay between calls
        sleep 1
    done
    echo "  CAT $cat: $DONE cached + new results"
done

# Final count
python3 -c "
import json
d=json.load(open('$RESULTS'))
valid=[r for r in d if not r['response'].startswith('Error:')]
print(f'FINAL: {len(valid)} valid results')
"