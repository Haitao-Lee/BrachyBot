#!/bin/bash
# Minimal benchmark runner - uses curl for API, quick Python for screenshots
set -e

SCREENSHOT_DIR="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BASE_URL="http://localhost:8080"
CAT=$1

echo "=== Category $CAT ==="

# Get remaining case IDs (quick python)
REMAINING=$(python3 -c "
import json, os, glob
cat_num = $CAT
files = glob.glob(f'benchmarks/{cat_num:02d}_*.json')
if not files: exit()
with open(files[0]) as f: data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data
done = {os.path.basename(f).replace(f'{cat_num:02d}_','').replace('.png','') for f in glob.glob('docs/benchmark_result/screenshots/{:02d}_*.png'.format(cat_num))}
remaining = [c for c in cases if c.get('id','') not in done]
for tc in remaining:
    print(tc.get('id','') + '|||' + tc.get('input',''))
" 2>/dev/null)

COUNT=$(echo "$REMAINING" | grep -c '|||' || true)
echo "Remaining: $COUNT"

if [ "$COUNT" -eq 0 ]; then
    echo "All done!"
    exit 0
fi

echo "$REMAINING" | while IFS='|||' read -r CASE_ID INPUT_TEXT; do
    [ -z "$CASE_ID" ] && continue

    SCREENSHOT="${SCREENSHOT_DIR}/${CAT}_${CASE_ID}.png"
    if [ -f "$SCREENSHOT" ] && [ $(stat -c%s "$SCREENSHOT" 2>/dev/null || echo 0) -gt 1000 ]; then
        echo "  SKIP: $CASE_ID"
        continue
    fi

    SESSION="agent1_${CAT}_${CASE_ID}_$(date +%s%3N)"
    echo -n "  $CASE_ID: "

    # Save input to temp file for curl
    python3 -c "
import json,sys
inp = sys.stdin.read().strip()
payload = json.dumps({'message': inp, 'clear_context': True, 'session_id': '$SESSION', 'stream': False})
with open('/tmp/payload.json','w') as f: f.write(payload)
" <<< "$INPUT_TEXT"

    START=$(date +%s)
    RESP=$(curl -s --max-time 180 -X POST "${BASE_URL}/api/chat" \
        -H "Content-Type: application/json" \
        -d @/tmp/payload.json 2>&1 || echo '{"response":"Error: curl failed"}')
    END=$(date +%s)
    ELAPSED=$((END - START))

    RLEN=$(echo "$RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('response','')))" 2>/dev/null || echo 0)
    echo "OK (${RLEN}c, ${ELAPSED}s)"

    # Screenshot (quick)
    python3 -c "
from playwright.sync_api import sync_playwright
import time
try:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={'width':1920,'height':1080})
        pg.goto('$BASE_URL',timeout=30000,wait_until='domcontentloaded')
        time.sleep(3)
        pg.screenshot(path='$SCREENSHOT',full_page=True)
        b.close()
except: pass
" 2>/dev/null || true

done

echo "=== Category $CAT complete ==="
