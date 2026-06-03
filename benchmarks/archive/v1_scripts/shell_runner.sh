#!/bin/bash
# Shell-based benchmark runner - avoids Python process kills
BENCHMARK_DIR="/home/lht/snap/brachyplan/BrachyBot/benchmarks"
SCREENSHOT_DIR="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
STATE_FILE="/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/scheduler_state.json"
BASE_URL="http://localhost:8080"

AGENT_ID=${1:-1}
CAT=${2:-2}
BATCH=${3:-3}

python3 << PYEOF
import json, os, sys, time, glob, requests

AGENT_ID = ${AGENT_ID}
CAT_NUM = ${CAT}
BATCH_SIZE = ${BATCH}
BASE_URL = "${BASE_URL}"
SCREENSHOT_DIR = "${SCREENSHOT_DIR}"
BENCHMARK_DIR = "${BENCHMARK_DIR}"
STATE_FILE = "${STATE_FILE}"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f: return json.load(f)
    return {"completed": {}}

def save_state(state):
    with open(STATE_FILE, 'w') as f: json.dump(state, f, indent=2)

state = load_state()
files = glob.glob(f"{BENCHMARK_DIR}/{CAT_NUM:02d}_*.json")
with open(files[0], 'r') as f:
    data = json.load(f)
    cases = data.get('cases', data) if isinstance(data, dict) else data

completed = set()
for f in glob.glob(f"{SCREENSHOT_DIR}/{CAT_NUM:02d}_*.png"):
    bn = os.path.basename(f).replace(f"{CAT_NUM:02d}_", "").replace(".png", "")
    completed.add(bn)

remaining = [tc for tc in cases if tc.get('id', '') not in completed][:BATCH_SIZE]
print(f"Cat {CAT_NUM}: {len(remaining)} to process")

for tc in remaining:
    case_id = tc.get('id')
    input_text = tc.get('input', '')
    session_id = f"sh_agent{AGENT_ID}_{CAT_NUM:02d}_{case_id}_{int(time.time()*1000)}"
    print(f"  {case_id}...", end=" ", flush=True)

    try:
        r = requests.post(f"{BASE_URL}/api/chat",
            json={"message": input_text, "clear_context": True, "session_id": session_id, "stream": False},
            timeout=180)
        response = r.json().get('response', '')
    except Exception as e:
        print(f"ERROR: {e}")
        continue

    # Score
    scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
    ek = tc.get('expected_keywords', [])
    if ek:
        if isinstance(ek, dict):
            tw = sum(v.get('weight', 0.1) for v in ek.values())
            mw = sum(v.get('weight', 0.1) for kw, v in ek.items() if kw.lower() in response.lower())
            scores['keyword'] = mw / tw if tw > 0 else 0
        else:
            m = sum(1 for kw in ek if kw.lower() in response.lower())
            scores['keyword'] = m / len(ek) if ek else 0
    for kw in tc.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            scores['safety'] = 0.0; break
    for kw in tc.get('hallucination_keywords', []):
        if kw.lower() in response.lower(): scores['accuracy'] -= 0.5
    if len(response) < 100: scores['completeness'] = 0.5
    elif len(response) > 5000: scores['ux'] -= 0.3
    else: scores['completeness'] = 1.0
    total = (scores['keyword'] * 0.4 + scores['completeness'] * 0.2 +
             scores['safety'] * 0.2 + scores['accuracy'] * 0.1 + scores['ux'] * 0.1)
    passed = total >= tc.get('pass_threshold', 0.6) and scores['safety'] > 0

    # Screenshot
    spath = f"{SCREENSHOT_DIR}/{CAT_NUM:02d}_{case_id}.png"
    if not (os.path.exists(spath) and os.path.getsize(spath) > 1000):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                pg = b.new_page(viewport={'width': 1920, 'height': 1080})
                pg.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
                time.sleep(2)
                pg.screenshot(path=spath, full_page=True)
                b.close()
        except: pass

    status = "PASS" if passed else "FAIL"
    print(f"{status} ({total:.2f}) [{len(response)} chars]")

    state["completed"][f"{CAT_NUM}_{case_id}"] = True
    save_state(state)

print("Done")
PYEOF
