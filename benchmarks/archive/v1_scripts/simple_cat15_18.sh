#!/bin/bash
# Ultra-simple benchmark for remaining cat 15 & 18 cases
# Uses only curl + lightweight python for screenshots
set -euo pipefail

BASE="http://localhost:8080"
SSDIR="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHDIR="/home/lht/snap/brachyplan/BrachyBot/benchmarks"
LOG="/home/lht/snap/brachyplan/BrachyBot/benchmarks/simple_bench.log"
AGENT=2

exec > "$LOG" 2>&1
echo "Simple bench started $(date)"

while true; do
    # Get next missing case
    NEXT=$(python3 -c "
import json, glob, os, sys
for i in [15, 18]:
    files = glob.glob(f'$BENCHDIR/{i:02d}_*.json')
    if not files: continue
    with open(files[0]) as f:
        data = json.load(f)
    cases = data.get('cases', data) if isinstance(data, dict) else data
    completed = set(os.path.basename(f).replace(f'{i:02d}_','').replace('.png','') for f in glob.glob(f'{SSDIR}/{i:02d}_*.png'))
    for c in cases:
        cid = c.get('id','')
        if cid not in completed:
            inp = c.get('input','').replace('\"', '\\\\\"')[:2000]
            print(f'{i:02d}|{cid}|{inp}')
            sys.exit(0)
print('DONE')
" 2>/dev/null)

    if [ "$NEXT" = "DONE" ]; then
        echo "ALL DONE at $(date)"
        break
    fi

    CAT=$(echo "$NEXT" | cut -d'|' -f1)
    CID=$(echo "$NEXT" | cut -d'|' -f2)
    INPUT=$(echo "$NEXT" | cut -d'|' -f3-)

    echo "[$CAT] $CID ... $(date +%H:%M:%S)" | head -c 200

    # Wait for server
    for w in $(seq 1 30); do
        CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$BASE/" 2>/dev/null)
        [ "$CODE" = "200" ] && break
        echo -n "."; sleep 5
    done

    # Send message
    SID="a${AGENT}_${CAT}_${CID}_$(date +%s%3N)"
    RESP=$(curl -s -X POST "$BASE/api/chat" \
        -H "Content-Type: application/json" \
        -d "{\"message\":\"$(python3 -c "import sys; print(sys.stdin.read().strip())" <<< "$INPUT")\",\"clear_context\":true,\"session_id\":\"$SID\",\"stream\":false}" \
        --max-time 180 2>/dev/null || echo '{"response":"ERROR"}')

    LEN=$(echo "$RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('response','')))" 2>/dev/null || echo "0")
    echo " -> ${LEN} chars" | head -c 100

    # Screenshot
    SS="$SSDIR/${CAT}_${CID}.png"
    if [ ! -f "$SS" ] || [ $(stat -c%s "$SS" 2>/dev/null || echo 0) -lt 1000 ]; then
        python3 -c "
from playwright.sync_api import sync_playwright; import time
with sync_playwright() as p:
    b=p.chromium.launch(headless=True); pg=b.new_page(viewport={'width':1920,'height':1080})
    pg.goto('$BASE',timeout=30000,wait_until='domcontentloaded'); time.sleep(2)
    pg.screenshot(path='$SS',full_page=True); b.close()
" 2>/dev/null && echo " [SS OK]"
    else
        echo " [SS exists]"
    fi
done

echo "Summary:"
for i in 15 18; do
    T=$(python3 -c "
import json,glob
with open([f for f in glob.glob('$BENCHDIR/${i}_*.json')][0]) as f:
    d=json.load(f)
c=d.get('cases',d) if isinstance(d,dict) else d
print(len(c))
" 2>/dev/null)
    D=$(ls "$SSDIR/${i}_"*.png 2>/dev/null | wc -l)
    echo "Cat $i: $D/$T"
done
