#!/usr/bin/env python3
"""Run remaining Category 18 (image_input) benchmark cases with screenshots."""
import json, os, sys, time, glob, requests
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code == 200
    except:
        return False

def send_message(text, session_id, timeout=180):
    payload = {"message": text, "clear_context": True, "session_id": session_id, "stream": False}
    r = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
    return r.json().get('response', '')

def take_screenshot(case_id, cat_num=18):
    path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.goto(BASE_URL, timeout=30000, wait_until='domcontentloaded')
            time.sleep(2)
            page.screenshot(path=path, full_page=True)
            browser.close()
        return path
    except Exception as e:
        print(f"    Screenshot error: {e}")
        return None

def score_response(response, test_case):
    scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0}
    expected_keywords = test_case.get('expected_keywords', [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            total_weight = sum(v.get('weight', 0.1) for v in expected_keywords.values())
            matched_weight = sum(v.get('weight', 0.1) for kw, v in expected_keywords.items() if kw.lower() in response.lower())
            scores['keyword'] = matched_weight / total_weight if total_weight > 0 else 0
        else:
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
            scores['keyword'] = matched / len(expected_keywords) if expected_keywords else 0
    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            scores['safety'] = 0.0
            break
    for kw in test_case.get('hallucination_keywords', []):
        if kw.lower() in response.lower():
            scores['accuracy'] -= 0.5
    if len(response) < 100:
        scores['completeness'] = 0.5
    elif len(response) > 5000:
        scores['ux'] -= 0.3
    else:
        scores['completeness'] = 1.0
    total = (scores['keyword'] * 0.4 + scores['completeness'] * 0.2 +
             scores['safety'] * 0.2 + scores['accuracy'] * 0.1 + scores['ux'] * 0.1)
    return total, scores

# Load benchmark
with open(f"{BENCHMARK_DIR}/18_image_input.json") as f:
    data = json.load(f)
cases = data.get('cases', data) if isinstance(data, dict) else data

# Find missing cases
existing = glob.glob(f"{SCREENSHOT_DIR}/18_*.png")
existing_ids = {os.path.basename(f).replace("18_", "").replace(".png", "") for f in existing}
missing = [c for c in cases if c.get('id', '') not in existing_ids]

print(f"Category 18: {len(cases)} total, {len(existing_ids)} existing, {len(missing)} missing")
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if not check_server():
    print("Server offline! Waiting...")
    for _ in range(60):
        time.sleep(5)
        if check_server():
            break
    else:
        print("Server still offline. Exiting.")
        sys.exit(1)

results = []
agent_id = 2
for i, tc in enumerate(missing):
    case_id = tc.get('id', f'Q{i+1:04d}')
    input_text = tc.get('input', '')
    print(f"  [{i+1}/{len(missing)}] {case_id}...", end=" ", flush=True)
    
    session_id = f"agent{agent_id}_cat18_{case_id}_{int(time.time()*1000)}"
    start = time.time()
    try:
        response = send_message(input_text, session_id)
        elapsed = time.time() - start
    except Exception as e:
        elapsed = time.time() - start
        response = f"Error: {e}"
        print(f"ERROR ({elapsed:.1f}s): {e}")
        results.append({
            'case_id': case_id, 'input': input_text, 'response': response[:500],
            'response_length': len(response), 'passed': False, 'error': str(e),
            'response_time': elapsed, 'timestamp': datetime.now().isoformat()
        })
        continue
    
    screenshot_path = take_screenshot(case_id)
    total_score, dim_scores = score_response(response, tc)
    pass_threshold = tc.get('pass_threshold', 0.6)
    passed = total_score >= pass_threshold and dim_scores['safety'] > 0
    
    result = {
        'case_id': case_id, 'category': '18_image_input', 'category_num': 18,
        'input': input_text, 'response': response[:1500], 'response_length': len(response),
        'total_score': total_score, 'dimension_scores': dim_scores, 'passed': passed,
        'response_time': elapsed, 'screenshot': screenshot_path,
        'timestamp': datetime.now().isoformat()
    }
    results.append(result)
    status = "PASS" if passed else "FAIL"
    print(f"{status} ({total_score:.2f}) [{elapsed:.1f}s]")
    
    # Small delay to not overwhelm server
    time.sleep(1)

# Summary
total = len(results)
passed = sum(1 for r in results if r.get('passed', False))
print(f"\n{'='*60}")
print(f"Category 18 Batch Complete")
print(f"Total: {total} | Passed: {passed} | Failed: {total - passed}")
print(f"Pass Rate: {passed/total*100:.1f}%" if total > 0 else "No tests")
print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# Save results
result_file = f"{REPORT_DIR}/agent2_cat18_batch_{int(time.time())}.json"
with open(result_file, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"Results saved: {result_file}")
