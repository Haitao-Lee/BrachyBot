#!/usr/bin/env python3 -u
"""Lightweight benchmark runner using curl subprocess for API calls."""
import json, os, sys, subprocess, time, glob
from datetime import datetime

RESULTS_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_all_results.json"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"

def call_api(message, session_id, timeout=90):
    """Use curl to call the API - lower memory than requests."""
    payload = json.dumps({"message": message, "clear_context": True, "session_id": session_id})
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", "http://localhost:8080/api/chat",
             "-H", "Content-Type: application/json",
             "-d", payload, "--max-time", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 10
        )
        text = result.stdout
        chunks = []
        for line in text.split("\n"):
            if line.startswith("data:"):
                try:
                    obj = json.loads(line[5:].strip())
                    # SSE format uses "text" for streaming chunks
                    if "text" in obj:
                        chunks.append(obj["text"])
                    elif "content" in obj and obj.get("type") == "assistant":
                        chunks.append(obj["content"])
                except:
                    pass
        return "".join(chunks)
    except Exception as e:
        return f"Error: {e}"

def score_and_analyze(response, tc):
    scores = {"keyword": 0.0, "completeness": 0.0, "safety": 1.0, "accuracy": 1.0, "ux": 1.0}
    ek = tc.get("expected_keywords", [])
    if ek:
        if isinstance(ek, dict):
            tw = sum(v.get("weight", 0.1) for v in ek.values())
            mw = sum(v.get("weight", 0.1) for kw, v in ek.items() if kw.lower() in response.lower())
            scores["keyword"] = mw / tw if tw > 0 else 0
        else:
            scores["keyword"] = sum(1 for k in ek if k.lower() in response.lower()) / len(ek)
    for k in tc.get("forbidden_keywords", []):
        if k.lower() in response.lower(): scores["safety"] = 0.0; break
    for k in tc.get("hallucination_keywords", []):
        if k.lower() in response.lower(): scores["accuracy"] -= 0.5
    if len(response) < 100: scores["completeness"] = 0.5
    elif len(response) > 5000: scores["ux"] -= 0.3
    else: scores["completeness"] = 1.0

    total = scores["keyword"]*0.4 + scores["completeness"]*0.2 + scores["safety"]*0.2 + scores["accuracy"]*0.1 + scores["ux"]*0.1
    passed = total >= tc.get("pass_threshold", 0.6) and scores["safety"] > 0

    rc = rcd = None
    if not passed:
        for hp in ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]:
            if hp.lower() in response.lower(): rc, rcd = "hallucination", hp; break
        if not rc:
            for k in tc.get("forbidden_keywords", []):
                if k.lower() in response.lower(): rc, rcd = "safety_leak", k; break
        if not rc and len(response) < 100: rc, rcd = "too_brief", str(len(response))
        if not rc and len(response) > 5000: rc, rcd = "too_verbose", str(len(response))
        if not rc and ek and sum(1 for k in ek if k.lower() in response.lower()) == 0: rc, rcd = "keyword_missing", "none"
        if not rc: rc, rcd = "wrong_answer", "fail"
    return total, scores, passed, rc, rcd

if __name__ == "__main__":
    start_cat = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    end_cat = int(sys.argv[2]) if len(sys.argv) > 2 else 9

    # Load existing
    try:
        with open(RESULTS_FILE) as f: all_results = json.load(f)
    except: all_results = []
    done_ids = {r["case_id"] for r in all_results}

    error_streak = 0
    total_run = 0

    for cat_num in range(start_cat, end_cat + 1):
        files = glob.glob(f"/home/lht/snap/brachyplan/BrachyBot/benchmarks/{cat_num:02d}_*.json")
        if not files: continue
        with open(files[0]) as f: data = json.load(f)
        cases = data.get("cases", data) if isinstance(data, dict) else data
        cat_name = os.path.basename(files[0]).replace(".json", "")

        remaining = [(i, tc) for i, tc in enumerate(cases)
                     if tc.get("id", f"Q{i+1:04d}") not in done_ids]
        print(f"CAT {cat_num} {cat_name}: {len(remaining)} remaining", flush=True)

        for idx, (i, tc) in enumerate(remaining):
            case_id = tc.get("id", f"Q{i+1:04d}")
            input_text = tc.get("input", "")
            sid = f"a1_{cat_num:02d}_{case_id}_{int(time.time()*1000)}"

            t0 = time.time()
            response = call_api(input_text, sid, timeout=90)
            rt = time.time() - t0

            if response.startswith("Error:"):
                error_streak += 1
                print(f"  {case_id} ERR [{rt:.0f}s] {response[:60]}", flush=True)
                if error_streak >= 5:
                    print(f"  5 errors in a row, stopping.", flush=True)
                    break
                continue

            error_streak = 0
            total, scores, passed, rc, rcd = score_and_analyze(response, tc)

            sd = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
            if not os.path.exists(sd): sd = None

            result = {
                "case_id": case_id, "category": cat_name, "category_num": cat_num,
                "input": input_text, "response": response[:1500], "response_length": len(response),
                "total_score": total, "dimension_scores": scores, "passed": passed,
                "root_cause": rc, "root_cause_detail": rcd, "response_time": rt,
                "screenshot": sd, "timestamp": datetime.now().isoformat()
            }
            all_results.append(result)
            with open(RESULTS_FILE, "w") as f:
                json.dump(all_results, f, indent=2, ensure_ascii=False)
            total_run += 1

            status = "PASS" if passed else "FAIL"
            print(f"  {case_id} {status} ({total:.2f}) [{rt:.0f}s]", flush=True)
            if rc: print(f"    -> {rc}: {rcd}", flush=True)

        if error_streak >= 5:
            break

    valid = [r for r in all_results if not r["response"].startswith("Error:")]
    print(f"\nTOTAL: {len(valid)} valid results, {total_run} run this session", flush=True)
