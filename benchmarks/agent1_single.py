#!/usr/bin/env python3
"""Run a single test case and save the result. Designed to be called per-case."""
import json, os, sys, time, gc
from datetime import datetime
import requests

BASE_URL = "http://localhost:8080"
RESULTS_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_all_results.json"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"

def send_message(text, session_id, timeout=60):
    payload = {"message": text, "clear_context": True, "session_id": session_id}
    response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout, stream=True)
    chunks = []
    for line in response.iter_lines():
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
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    cat_num = int(sys.argv[1])
    case_idx = int(sys.argv[2])

    import glob
    files = glob.glob(f"/home/lht/snap/brachyplan/BrachyBot/benchmarks/{cat_num:02d}_*.json")
    with open(files[0]) as f:
        data = json.load(f)
    cases = data.get("cases", data) if isinstance(data, dict) else data
    cat_name = os.path.basename(files[0]).replace(".json", "")

    tc = cases[case_idx]
    case_id = tc.get("id", f"Q{case_idx+1:04d}")
    input_text = tc.get("input", "")
    session_id = f"a1_{cat_num:02d}_{case_id}_{int(time.time()*1000)}"

    all_results = load_results()
    done_ids = {r["case_id"] for r in all_results}
    if case_id in done_ids:
        print(f"SKIP {case_id} (already done)")
        sys.exit(0)

    t0 = time.time()
    try:
        response = send_message(input_text, session_id, timeout=60)
    except Exception as e:
        response = f"Error: {e}"
    rt = time.time() - t0

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

    status = "PASS" if passed else "FAIL"
    print(f"{case_id} {status} ({total:.2f}) [{rt:.1f}s]")
    if rc:
        print(f"  -> {rc}: {rcd}")
