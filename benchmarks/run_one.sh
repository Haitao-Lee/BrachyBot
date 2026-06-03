#!/bin/bash
# Run a single benchmark test case via curl
# Usage: bash run_one.sh <cat_num> <case_id> <input_text>

CAT_NUM=$1
CASE_ID=$2
INPUT_TEXT=$3
BASE_URL="http://localhost:8080"
SCREENSHOT_DIR="docs/benchmark_result/screenshots"
SESSION_ID="agent1_${CAT_NUM}_${CASE_ID}_$(date +%s%3N)"

# Check if already done
SCREENSHOT_PATH="${SCREENSHOT_DIR}/${CAT_NUM}_${CASE_ID}.png"
if [ -f "$SCREENSHOT_PATH" ] && [ $(stat -c%s "$SCREENSHOT_PATH") -gt 1000 ]; then
    echo "SKIP: Already done"
    exit 0
fi

# Send API request
echo "Sending API request for ${CASE_ID}..."
RESPONSE=$(curl -s --max-time 180 \
    -H "Content-Type: application/json" \
    -d "{\"message\": $(python3 -c "import json; print(json.dumps('$INPUT_TEXT'))"), \"clear_context\": true, \"session_id\": \"${SESSION_ID}\", \"stream\": false}" \
    "${BASE_URL}/api/chat" 2>&1)

echo "Response received (length: ${#RESPONSE})"

# Take screenshot with playwright
echo "Taking screenshot..."
python3 -c "
from playwright.sync_api import sync_playwright
import time
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})
    page.goto('http://localhost:8080', timeout=30000, wait_until='domcontentloaded')
    time.sleep(3)
    page.screenshot(path='${SCREENSHOT_PATH}', full_page=True)
    browser.close()
print('Screenshot saved')
" 2>&1

echo "Done: ${CASE_ID}"
