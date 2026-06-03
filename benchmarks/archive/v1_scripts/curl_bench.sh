#!/bin/bash
# Simple curl-based benchmark runner for remaining cases
# No heavy Python - just curl + playwright screenshots

BASE_URL="http://localhost:8080"
SCREENSHOT_DIR="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR="/home/lht/snap/brachyplan/BrachyBot/benchmarks"
LOG_FILE="/home/lht/snap/brachyplan/BrachyBot/benchmarks/curl_bench.log"
AGENT_ID=2

echo "=== Curl Benchmark Runner - Agent $AGENT_ID ===" | tee "$LOG_FILE"
echo "Started: $(date)" | tee -a "$LOG_FILE"

# Get remaining cases as JSON array
REMAINING=$(python3 -c "
import json, glob, os
SCREENSHOT_DIR = '$SCREENSHOT_DIR'
BENCHMARK_DIR = '$BENCHMARK_DIR'
results = []
for i in [15, 18]:
    files = glob.glob(f'{BENCHMARK_DIR}/{i:02d}_*.json')
    if not files: continue
    with open(files[0]) as f:
        data = json.load(f)
    cases = data.get('cases', data) if isinstance(data, dict) else data
    completed = set(os.path.basename(f).replace(f'{i:02d}_','').replace('.png','') for f in glob.glob(f'{SCREENSHOT_DIR}/{i:02d}_*.png'))
    for c in cases:
        cid = c.get('id','')
        if cid not in completed:
            results.append({'cat': i, 'id': cid, 'input': c.get('input','')[:2000], 'threshold': c.get('pass_threshold', 0.6), 'keywords': c.get('expected_keywords', [])})
print(json.dumps(results))
")

TOTAL=$(echo "$REMAINING" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
echo "Remaining cases: $TOTAL" | tee -a "$LOG_FILE"

INDEX=0
echo "$REMAINING" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for item in data:
    print(json.dumps(item))
" | while IFS= read -r LINE; do
    INDEX=$((INDEX + 1))
    CAT=$(echo "$LINE" | python3 -c "import sys,json; print(json.load(sys.stdin)['cat'])")
    CID=$(echo "$LINE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
    INPUT=$(echo "$LINE" | python3 -c "import sys,json; print(json.load(sys.stdin)['input'])")

    echo "[$INDEX/$TOTAL] Cat $CAT: $CID..." | tee -a "$LOG_FILE"

    # Wait for server
    for i in 1 2 3 4 5 6 7 8 9 10; do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE_URL/" 2>/dev/null)
        if [ "$HTTP_CODE" = "200" ]; then break; fi
        echo "  Server offline, waiting 10s..." | tee -a "$LOG_FILE"
        sleep 10
    done

    # Send request
    SESSION_ID="agent${AGENT_ID}_${CAT}_${CID}_$(date +%s%3N)"
    START=$(date +%s%N)
    RESPONSE=$(curl -s -X POST "$BASE_URL/api/chat" \
        -H "Content-Type: application/json" \
        -d "{\"message\": $(echo "$INPUT" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))'), \"clear_context\": true, \"session_id\": \"$SESSION_ID\", \"stream\": false}" \
        --max-time 120 2>/dev/null)
    END=$(date +%s%N)
    ELAPSED=$(( (END - START) / 1000000 ))

    if [ -z "$RESPONSE" ]; then
        echo "  TIMEOUT/Error (${ELAPSED}ms)" | tee -a "$LOG_FILE"
        continue
    fi

    # Extract response text
    RESP_TEXT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('response',''))" 2>/dev/null)
    RESP_LEN=${#RESP_TEXT}

    # Take screenshot
    SCREENSHOT="$SCREENSHOT_DIR/${CAT}_${CID}.png"
    if [ ! -f "$SCREENSHOT" ] || [ $(stat -c%s "$SCREENSHOT" 2>/dev/null || echo 0) -lt 1000 ]; then
        python3 -c "
from playwright.sync_api import sync_playwright
import time
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})
    page.goto('$BASE_URL', timeout=30000, wait_until='domcontentloaded')
    time.sleep(2)
    page.screenshot(path='$SCREENSHOT', full_page=True)
    browser.close()
" 2>/dev/null
    fi

    echo "  OK (${RESP_LEN} chars, ${ELAPSED}ms)" | tee -a "$LOG_FILE"
done

echo "" | tee -a "$LOG_FILE"
echo "Finished: $(date)" | tee -a "$LOG_FILE"

# Final count
python3 -c "
import json, glob, os
for i in [15, 18]:
    files = glob.glob(f'$BENCHMARK_DIR/{i:02d}_*.json')
    if not files: continue
    with open(files[0]) as f:
        data = json.load(f)
    cases = data.get('cases', data) if isinstance(data, dict) else data
    total = len(cases)
    done = len(glob.glob(f'$SCREENSHOT_DIR/{i:02d}_*.png'))
    print(f'Cat {i:02d}: {done}/{total}')
" | tee -a "$LOG_FILE"
