#!/usr/bin/env python3
"""Run benchmark in controlled batches with health checks."""
import json, os, sys, time, glob
from datetime import datetime
import requests

BASE_URL = "http://localhost:8080"
RESULTS_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_all_results.json"
BATCH_SIZE = 8  # cases per batch
BATCH_DELAY = 3  # seconds between batches

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

def health_check():
    try:
        payload = {"message": "hi", "clear_context": True, "session_id": "health"}
        resp = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=30, stream=True)
        for line in resp.iter_lines():
            if line:
                d = line.decode("utf-8")
                if d.startswith("data:"):
                    return True
        return False
    except:
        return False

def load_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return []

def save_results(results):
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

def get_all_cases():
    """Load all test cases across categories 1-9."""
    all_cases = []
    for cat_num in range(1, 10):
        files = glob.glob(f"/home/lht/snap/brachyplan/BrachyBot/benchmarks/{cat_num:02d}_*.json")
        if not files:
            continue
        with open(files[0]) as f:
            data = json.load(f)
        cases = data.get("cases", data) if isinstance(data, dict) else data
        cat_name = os.path.basename(files[0]).replace(".json", "")
        for i, tc in enumerate(cases):
            case_id = tc.get("id", f"Q{i+1:04d}")
            all_cases.append({
                "cat_num": cat_num,
                "cat_name": cat_name,
                "case_idx": i,
                "case_id": case_id,
                "test_case": tc
            })
    return all_cases

if __name__ == "__main__":
    all_cases = get_all_cases()
    existing = load_results()
    done_ids = {r["case_id"] for r in existing}

    remaining = [c for c in all_cases if c["case_id"] not in done_ids]
    print(f"Total cases: {len(all_cases)}, Already done: {len(done_ids)}, Remaining: {len(remaining)}")

    batch_num = 0
    i = 0
    while i < len(remaining):
        batch = remaining[i:i+BATCH_SIZE]
        batch_num += 1

        # Health check before batch
        if not health_check():
            print(f"\n--- Server down, waiting 30s (batch {batch_num}) ---")
            time.sleep(30)
            if not health_check():
                print("Server still down, waiting 60s...")
                time.sleep(60)
                if not health_check():
                    print("Server unreachable, aborting.")
                    break

        print(f"\n--- Batch {batch_num}: {len(batch)} cases ---")
        for c in batch:
            cat_num = c["cat_num"]
            case_id = c["case_id"]
            tc = c["test_case"]
            input_text = tc.get("input", "")
            session_id = f"a1_{cat_num:02d}_{case_id}_{int(time.time()*1000)}"

            t0 = time.time()
            try:
                response = send_message(input_text, session_id, timeout=60)
            except Exception as e:
                response = f"Error: {e}"
            rt = time.time() - t0

            total, scores, passed, rc, rcd = score_and_analyze(response, tc)

            screenshot_path = f"/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots/{cat_num:02d}_{case_id}.png"
            if not os.path.exists(screenshot_path):
                screenshot_path = None

            result = {
                "case_id": case_id, "category": c["cat_name"], "category_num": cat_num,
                "input": input_text, "response": response[:1500], "response_length": len(response),
                "total_score": total, "dimension_scores": scores, "passed": passed,
                "root_cause": rc, "root_cause_detail": rcd, "response_time": rt,
                "screenshot": screenshot_path, "timestamp": datetime.now().isoformat()
            }
            existing.append(result)
            save_results(existing)

            status = "PASS" if passed else "FAIL"
            is_error = response.startswith("Error:")
            marker = " [CONN ERROR]" if is_error else ""
            print(f"  {case_id} {status} ({total:.2f}) [{rt:.1f}s]{marker}")
            if rc:
                print(f"    -> {rc}: {rcd}")

            # If connection error, stop batch
            if is_error:
                print("  Connection error detected, stopping batch.")
                break

        i += len(batch)
        time.sleep(BATCH_DELAY)

        # Progress summary
        valid = [r for r in existing if not r["response"].startswith("Error:")]
        print(f"  Progress: {len(valid)} valid / {len(existing)} total")

    # Final summary
    existing = load_results()
    valid = [r for r in existing if not r["response"].startswith("Error:")]
    cats = {}
    for r in valid:
        cn = r["category_num"]
        cats[cn] = cats.get(cn, 0) + 1
    print(f"\n=== FINAL: {len(valid)} valid results ===")
    for k in sorted(cats):
        print(f"  Cat {k}: {cats[k]}")
