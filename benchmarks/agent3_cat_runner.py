#!/usr/bin/env python3
"""
Agent 3 Category Runner - Resilient batch runner for categories 19-27
"""
import json, os, sys, time, glob, requests
from datetime import datetime

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code == 200
    except:
        return False

def wait_for_server(timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        if check_server():
            return True
        time.sleep(3)
    return False

def load_cases(cat_num):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return []
    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
        if isinstance(data, dict) and 'cases' in data:
            return data['cases']
        elif isinstance(data, list):
            return data
    return []

def get_done(cat_num):
    done = []
    for f in glob.glob(f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"):
        bn = os.path.basename(f)
        cid = bn.replace(f"{cat_num:02d}_", "").replace(".png", "")
        done.append(cid)
    return done

def send_msg(text, session_id, timeout=180):
    for attempt in range(3):
        try:
            if not check_server():
                if not wait_for_server(timeout=60):
                    continue
            payload = {"message": text, "clear_context": True, "session_id": session_id, "stream": False}
            r = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
            return r.json().get('response', '')
        except requests.exceptions.Timeout:
            print(f"      Timeout attempt {attempt+1}/3", flush=True)
            if attempt < 2:
                time.sleep(3)
        except Exception as e:
            print(f"      Error attempt {attempt+1}/3: {type(e).__name__}", flush=True)
            if attempt < 2:
                time.sleep(3)
    return "Error: All attempts failed"

def take_ss(case_id, cat_num):
    path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
            time.sleep(3)
            page.screenshot(path=path, full_page=True)
            browser.close()
        return path
    except Exception as e:
        print(f"      Screenshot failed: {e}", flush=True)
    return None

def score(resp, tc):
    s = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
    ek = tc.get('expected_keywords', [])
    if ek:
        if isinstance(ek, dict):
            tw = sum(v.get('weight', 0.1) for v in ek.values())
            mw = sum(v.get('weight', 0.1) for kw, v in ek.items() if kw.lower() in resp.lower())
            s['keyword'] = mw / tw if tw > 0 else 0
        else:
            matched = sum(1 for kw in ek if kw.lower() in resp.lower())
            s['keyword'] = matched / len(ek) if ek else 0
    for kw in tc.get('forbidden_keywords', []):
        if kw.lower() in resp.lower():
            s['safety'] = 0.0
            break
    for kw in tc.get('hallucination_keywords', []):
        if kw.lower() in resp.lower():
            s['accuracy'] -= 0.5
    if len(resp) < 100:
        s['completeness'] = 0.5
    elif len(resp) > 5000:
        s['ux'] -= 0.3
    else:
        s['completeness'] = 1.0
    total = s['keyword']*0.4 + s['completeness']*0.2 + s['safety']*0.2 + s['accuracy']*0.1 + s['ux']*0.1
    return total, s

def main():
    categories = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [19,20,21,22,23]
    agent_id = 3

    if not check_server():
        print("Server offline, waiting...", flush=True)
        if not wait_for_server(timeout=300):
            print("Cannot reach server. Exiting.", flush=True)
            sys.exit(1)
    print("Server is online.", flush=True)

    all_results = []

    for cat_num in categories:
        cases = load_cases(cat_num)
        if not cases:
            print(f"\nCat {cat_num}: No cases found", flush=True)
            continue
        done = get_done(cat_num)
        remaining = [tc for tc in cases if tc.get('id','') not in done]
        print(f"\n{'='*60}", flush=True)
        print(f"Cat {cat_num}: {len(cases)} total | {len(done)} done | {len(remaining)} remaining", flush=True)
        print(f"{'='*60}", flush=True)

        if not remaining:
            print("  All done!", flush=True)
            continue

        cat_results = []
        for i, tc in enumerate(remaining):
            cid = tc.get('id', f'Q{i+1:04d}')
            inp = tc.get('input', '')
            print(f"  [{i+1}/{len(remaining)}] {cid}...", end=" ", flush=True)

            if not check_server():
                print("Server down, waiting...", end=" ", flush=True)
                if not wait_for_server(timeout=120):
                    print("SKIP (server down)", flush=True)
                    continue

            sid = f"agent{agent_id}_{cat_num:02d}_{cid}_{int(time.time()*1000)}"
            t0 = time.time()
            resp = send_msg(inp, sid, timeout=180)
            elapsed = time.time() - t0

            take_ss(cid, cat_num)
            total_s, dim_s = score(resp, tc)
            threshold = tc.get('pass_threshold', 0.6)
            passed = total_s >= threshold and dim_s['safety'] > 0

            status = "PASS" if passed else "FAIL"
            print(f"{status} ({total_s:.2f}) [{elapsed:.1f}s]", flush=True)

            cat_results.append({
                'case_id': cid, 'category_num': cat_num,
                'input': inp, 'response': resp[:1500], 'response_length': len(resp),
                'total_score': total_s, 'dimension_scores': dim_s, 'passed': passed,
                'response_time': elapsed, 'timestamp': datetime.now().isoformat()
            })
            time.sleep(1)

        all_results.extend(cat_results)
        cat_pass = sum(1 for r in cat_results if r['passed'])
        print(f"  Cat {cat_num} complete: {cat_pass}/{len(cat_results)} passed", flush=True)

    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    print(f"\n{'='*60}", flush=True)
    print(f"COMPLETE: {passed}/{total} passed ({passed/total*100:.1f}%)" if total else "No tests run", flush=True)
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)

if __name__ == "__main__":
    main()
