#!/usr/bin/env python3 -u
"""Smart batch runner with unbuffered output."""
import json, os, sys, time, glob
from datetime import datetime
import requests

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)  # line-buffered

BASE_URL = "http://localhost:8080"
RESULTS_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_all_results.json"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"

def send_message(text, session_id, timeout=60):
    payload = {"message": text, "clear_context": True, "session_id": session_id}
    resp = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout, stream=True)
    chunks = []
    for line in resp.iter_lines():
        if line:
            d = line.decode("utf-8")
            if d.startswith("data:"):
                obj = json.loads(d[5:])
                if "content" in obj:
                    chunks.append(obj["content"])
                if obj.get("done"):
                    break
    return "".join(chunks)

def score_and_analyze(response, tc):
    scores = {"keyword": 0.0, "completeness": 0.0, "safety": 1.0, "accuracy": 1.0, "ux": 1.0}
    ek = tc.get("expected_keywords", [])
    if ek:
        if isinstance(ek, dict):
            tw = sum(v.get("weight", 0.1) for v in ek.values())
            mw = sum(v.get("weight", 0.1) for kw, v in ek.items() if kw.lower() in response.lower())
            scores["keyword"] = mw / tw if tw > 0 else 0
        else:
            matched = sum(1 for kw in ek if kw.lower() in response.lower())
            scores["keyword"] = matched / len(ek) if ek else 0
    for kw in tc.get("forbidden_keywords", []):
        if kw.lower() in response.lower():
            scores["safety"] = 0.0
            break
    for kw in tc.get("hallucination_keywords", []):
        if kw.lower() in response.lower():
            scores["accuracy"] -= 0.5
    if len(response) < 100:
        scores["completeness"] = 0.5
    elif len(response) > 5000:
        scores["ux"] -= 0.3
    else:
        scores["completeness"] = 1.0
    total = scores["keyword"]*0.4 + scores["completeness"]*0.2 + scores["safety"]*0.2 + scores["accuracy"]*0.1 + scores["ux"]*0.1
    threshold = tc.get("pass_threshold", 0.6)
    passed = total >= threshold and scores["safety"] > 0

    rc = rcd = None
    if not passed:
        for hp in ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]:
            if hp.lower() in response.lower():
                rc, rcd = "hallucination", f'Contains: "{hp}"'
                break
        if not rc:
            for kw in tc.get("forbidden_keywords", []):
                if kw.lower() in response.lower():
                    rc, rcd = "safety_leak", f'Forbidden: "{kw}"'
                    break
        if not rc and len(response) < 100:
            rc, rcd = "too_brief", f"{len(response)} chars"
        if not rc and len(response) > 5000:
            rc, rcd = "too_verbose", f"{len(response)} chars"
        if not rc and ek:
            if isinstance(ek, dict):
                m = sum(1 for kw in ek if kw.lower() in response.lower())
            else:
                m = sum(1 for kw in ek if kw.lower() in response.lower())
            if m == 0:
                rc, rcd = "keyword_missing", "No keywords found"
        if not rc:
            rc, rcd = "wrong_answer", "Does not meet expectations"
    return total, scores, passed, rc, rcd

def load_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return []

def save_results(results):
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    start_cat = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    end_cat = int(sys.argv[2]) if len(sys.argv) > 2 else 9

    all_results = load_results()
    done_ids = {r["case_id"] for r in all_results}

    total_run = 0
    total_errors = 0

    for cat_num in range(start_cat, end_cat + 1):
        files = glob.glob(f"/home/lht/snap/brachyplan/BrachyBot/benchmarks/{cat_num:02d}_*.json")
        if not files:
            continue
        with open(files[0]) as f:
            data = json.load(f)
        cases = data.get("cases", data) if isinstance(data, dict) else data
        cat_name = os.path.basename(files[0]).replace(".json", "")

        remaining = []
        for i, tc in enumerate(cases):
            case_id = tc.get("id", f"Q{i+1:04d}")
            if case_id not in done_ids:
                remaining.append((i, tc, case_id))

        print(f"CAT {cat_num} {cat_name}: {len(remaining)} remaining of {len(cases)}")

        for i, (idx, tc, case_id) in enumerate(remaining):
            input_text = tc.get("input", "")
            session_id = f"a1_{cat_num:02d}_{case_id}_{int(time.time()*1000)}"

            try:
                t0 = time.time()
                response = send_message(input_text, session_id, timeout=60)
                rt = time.time() - t0
            except Exception as e:
                response = f"Error: {e}"
                rt = 0

            if response.startswith("Error:"):
                total_errors += 1
                print(f"  {case_id} ERROR [{rt:.1f}s] {response[:80]}")
                # Don't save errors - will retry later
                if total_errors >= 3:
                    print(f"  3 consecutive errors, stopping category {cat_num}")
                    break
                continue

            total_errors = 0  # Reset error counter on success
            total, scores, passed, rc, rcd = score_and_analyze(response, tc)

            screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
            if not os.path.exists(screenshot_path):
                screenshot_path = None

            result = {
                "case_id": case_id, "category": cat_name, "category_num": cat_num,
                "input": input_text, "response": response[:1500], "response_length": len(response),
                "total_score": total, "dimension_scores": scores, "passed": passed,
                "root_cause": rc, "root_cause_detail": rcd, "response_time": rt,
                "screenshot": screenshot_path, "timestamp": datetime.now().isoformat()
            }
            all_results.append(result)
            save_results(all_results)
            total_run += 1

            status = "PASS" if passed else "FAIL"
            print(f"  {case_id} {status} ({total:.2f}) [{rt:.1f}s]")
            if rc:
                print(f"    -> {rc}: {rcd}")

        print(f"  CAT {cat_num} done: {len([r for r in all_results if r['category_num'] == cat_num])} results")

    valid = [r for r in all_results if not r["response"].startswith("Error:")]
    print(f"\nTOTAL: {len(valid)} valid results across {end_cat - start_cat + 1} categories")
