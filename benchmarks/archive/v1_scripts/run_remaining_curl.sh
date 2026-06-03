#!/bin/bash
# Run remaining benchmark tests using curl (avoids OOM kills from long-running Python)
# Usage: bash run_remaining_curl.sh <cat_num> [cat_num2] ...

SCREENSHOT_DIR="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BASE_URL="http://localhost:8080"

for CAT_NUM in "$@"; do
    CAT_NUM_PADDED=$(printf "%02d" $CAT_NUM)
    echo ""
    echo "========================================="
    echo "Processing Category $CAT_NUM"
    echo "========================================="

    # Get remaining case IDs and inputs using Python (quick process)
    python3 -c "
import json, os, glob
BENCHMARK_DIR = '/home/lht/snap/brachyplan/BrachyBot/benchmarks'
SCREENSHOT_DIR = '$SCREENSHOT_DIR'
CAT_NUM = $CAT_NUM

files = glob.glob(f'{BENCHMARK_DIR}/{CAT_NUM:02d}_*.json')
if not files:
    exit()

with open(files[0]) as f:
    data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data

done_files = glob.glob(f'{SCREENSHOT_DIR}/{CAT_NUM:02d}_*.png')
done_ids = {os.path.basename(f).replace(f'{CAT_NUM:02d}_', '').replace('.png', '') for f in done_files}
remaining = [c for c in cases if c.get('id', '') not in done_ids]

print(f'Remaining: {len(remaining)}')
for tc in remaining:
    cid = tc.get('id', '')
    inp = tc.get('input', '')
    # Output as tab-separated: case_id<TAB>input
    print(f'{cid}\t{inp}')
" > /tmp/cat${CAT_NUM_PADDED}_remaining.txt

    REMAINING_COUNT=$(head -1 /tmp/cat${CAT_NUM_PADDED}_remaining.txt | cut -f2-)
    REMAINING_COUNT=$(head -1 /tmp/cat${CAT_NUM_PADDED}_remaining.txt)

    echo "Cases to process: $(wc -l < /tmp/cat${CAT_NUM_PADDED}_remaining.txt)"

    # Process each case (skip header line)
    tail -n +2 /tmp/cat${CAT_NUM_PADDED}_remaining.txt | while IFS=$'\t' read -r CASE_ID INPUT_TEXT; do
        if [ -z "$CASE_ID" ]; then
            continue
        fi

        SCREENSHOT_PATH="${SCREENSHOT_DIR}/${CAT_NUM_PADDED}_${CASE_ID}.png"
        if [ -f "$SCREENSHOT_PATH" ] && [ $(stat -c%s "$SCREENSHOT_PATH" 2>/dev/null || echo 0) -gt 1000 ]; then
            echo "  SKIP: $CASE_ID (already done)"
            continue
        fi

        SESSION_ID="agent1_${CAT_NUM_PADDED}_${CASE_ID}_$(date +%s%3N)"
        echo -n "  $CASE_ID: "

        # Create JSON payload
        PAYLOAD=$(python3 -c "import json; print(json.dumps({'message': '''$INPUT_TEXT''', 'clear_context': True, 'session_id': '$SESSION_ID', 'stream': False}))")

        START_TIME=$(date +%s)

        # Send API request with curl
        RESPONSE=$(curl -s --max-time 180 -X POST "${BASE_URL}/api/chat" \
            -H "Content-Type: application/json" \
            -d "$PAYLOAD" 2>&1)

        END_TIME=$(date +%s)
        ELAPSED=$((END_TIME - START_TIME))

        RESP_LEN=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('response','')))" 2>/dev/null || echo "0")

        echo "OK (${RESP_LEN} chars, ${ELAPSED}s)"

        # Take screenshot with playwright (quick process)
        python3 -c "
from playwright.sync_api import sync_playwright
import time
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1920, 'height': 1080})
        page.goto('${BASE_URL}', timeout=30000, wait_until='domcontentloaded')
        time.sleep(3)
        page.screenshot(path='${SCREENSHOT_PATH}', full_page=True)
        browser.close()
    print('    Screenshot saved')
except Exception as e:
    print(f'    Screenshot failed: {e}')
" 2>&1

    done
done
