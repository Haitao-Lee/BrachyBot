#!/bin/bash
# Agent 4 test runner - runs tests one at a time via Python
# Usage: bash run_tests.sh <category_num> [start_index]
# Each test is run as a separate Python invocation for stability

SCREENSHOT_DIR="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR="/home/lht/snap/brachyplan/BrachyBot/benchmarks"
LOG_DIR="/home/lht/snap/brachyplan/BrachyBot/benchmarks"

CAT_NUM=${1:-23}
START_INDEX=${2:-0}
LOG_FILE="$LOG_DIR/agent4_cat${CAT_NUM}_run.log"

mkdir -p "$SCREENSHOT_DIR"

# Get total cases and IDs
TOTAL=$(python3 -c "
import json, glob
files = glob.glob('$BENCHMARK_DIR/${CAT_NUM}_*.json')
if files:
    with open(files[0]) as f:
        data = json.load(f)
    cases = data.get('cases', data) if isinstance(data, dict) else data
    print(len(cases))
else:
    print(0)
")

echo "$(date) Starting category $CAT_NUM (total: $TOTAL)" >> "$LOG_FILE"

# Get list of remaining case IDs
python3 -c "
import json, glob, os
files = glob.glob('$BENCHMARK_DIR/${CAT_NUM}_*.json')
if not files:
    exit()
with open(files[0]) as f:
    data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data

done = set()
for f in glob.glob('$SCREENSHOT_DIR/${CAT_NUM}_*.png'):
    if os.path.getsize(f) > 1000:
        cid = os.path.basename(f).replace('${CAT_NUM}_', '').replace('.png', '')
        done.add(cid)

remaining = [tc for tc in cases if tc.get('id', '') not in done]
print(len(remaining))
" > /tmp/agent4_remaining_${CAT_NUM}.txt

REMAINING=$(cat /tmp/agent4_remaining_${CAT_NUM}.txt)
echo "$(date) Remaining: $REMAINING cases" >> "$LOG_FILE"

# Run each test case individually
python3 << 'PYEOF'
import json, os, sys, time, glob, requests

CAT_NUM = int(sys.argv[1]) if len(sys.argv) > 1 else 23
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
BASE_URL = "http://localhost:8080"
AGENT_ID = 4
API_TIMEOUT = 300

files = glob.glob(f"{BENCHMARK_DIR}/{CAT_NUM:02d}_*.json")
with open(files[0]) as f:
    data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data

done = set()
for f in glob.glob(f"{SCREENSHOT_DIR}/{CAT_NUM:02d}_*.png"):
    if os.path.getsize(f) > 1000:
        cid = os.path.basename(f).replace(f"{CAT_NUM:02d}_", "").replace(".png", "")
        done.add(cid)

remaining = [tc for tc in cases if tc.get('id', '') not in done]

print(f"Running {len(remaining)} tests for category {CAT_NUM}")

for i, tc in enumerate(remaining):
    case_id = tc.get('id', f'Q{i+1:04d}')
    input_text = tc.get('input', '')

    # Check server first
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        if r.status_code != 200:
            print(f"  Server offline, waiting 30s...")
            time.sleep(30)
    except:
        print(f"  Server offline, waiting 30s...")
        time.sleep(30)

    print(f"  [{i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

    session_id = f"agent{AGENT_ID}_{CAT_NUM:02d}_{case_id}_{int(time.time()*1000)}"
    t0 = time.time()

    response = ""
    for attempt in range(3):
        try:
            r = requests.post(f"{BASE_URL}/api/chat", json={
                "message": input_text,
                "clear_context": True,
                "session_id": session_id,
                "stream": False
            }, timeout=API_TIMEOUT)
            data = r.json()
            response = data.get("response", "")
            break
        except Exception as e:
            print(f"(err:{type(e).__name__})", end=" ", flush=True)
            time.sleep(10)

    response_time = time.time() - t0

    # Take screenshot
    screenshot_path = f"{SCREENSHOT_DIR}/{CAT_NUM:02d}_{case_id}.png"
    if not (os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})
                page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
                time.sleep(3)
                page.screenshot(path=screenshot_path, full_page=True)
                browser.close()
        except Exception as e:
            print(f"(ss_fail)", end=" ", flush=True)

    # Score
    expected = tc.get('expected_keywords', [])
    if expected and isinstance(expected, list):
        matched = sum(1 for kw in expected if kw.lower() in response.lower())
        keyword_score = matched / len(expected)
    else:
        keyword_score = 0

    passed = keyword_score >= 0.3 and len(response) > 100
    status = "PASS" if passed else "FAIL"
    print(f"{status} ({keyword_score:.2f}) [{response_time:.1f}s] [{len(response)}chars]")
PYEOF
"$CAT_NUM"
