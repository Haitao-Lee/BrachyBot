#!/usr/bin/env python3
"""Minimal single-case runner using only stdlib + requests."""
import json, os, sys, time, glob
from datetime import datetime
import requests

def main():
    cat_num = int(sys.argv[1])
    case_idx = int(sys.argv[2])
    rf = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_all_results.json"

    # Load test case
    files = glob.glob(f"/home/lht/snap/brachyplan/BrachyBot/benchmarks/{cat_num:02d}_*.json")
    with open(files[0]) as f:
        data = json.load(f)
    cases = data.get("cases", data) if isinstance(data, dict) else data
    tc = cases[case_idx]
    case_id = tc.get("id", f"Q{case_idx+1:04d}")
    cat_name = os.path.basename(files[0]).replace(".json", "")

    # Check if done
    try:
        with open(rf) as f:
            existing = json.load(f)
    except:
        existing = []

    if any(r["case_id"] == case_id for r in existing):
        return  # Skip

    # Call API
    input_text = tc.get("input", "")
    sid = f"a1_{cat_num:02d}_{case_id}_{int(time.time()*1000)}"
    payload = {"message": input_text, "clear_context": True, "session_id": sid}

    t0 = time.time()
    try:
        resp = requests.post("http://localhost:8080/api/chat", json=payload, timeout=60, stream=True)
        chunks = []
        for line in resp.iter_lines():
            if line:
                d = line.decode("utf-8")
                if d.startswith("data:"):
                    o = json.loads(d[5:])
                    if "content" in o: chunks.append(o["content"])
                    if o.get("done"): break
        response = "".join(chunks)
    except Exception as e:
        response = f"Error: {e}"
    rt = time.time() - t0

    if response.startswith("Error:"):
        return  # Don't save errors

    # Score
    s = {"keyword": 0.0, "completeness": 0.0, "safety": 1.0, "accuracy": 1.0, "ux": 1.0}
    ek = tc.get("expected_keywords", [])
    if ek:
        if isinstance(ek, dict):
            tw = sum(v.get("weight", 0.1) for v in ek.values())
            mw = sum(v.get("weight", 0.1) for k, v in ek.items() if k.lower() in response.lower())
            s["keyword"] = mw / tw if tw > 0 else 0
        else:
            s["keyword"] = sum(1 for k in ek if k.lower() in response.lower()) / len(ek)
    for k in tc.get("forbidden_keywords", []):
        if k.lower() in response.lower(): s["safety"] = 0.0; break
    for k in tc.get("hallucination_keywords", []):
        if k.lower() in response.lower(): s["accuracy"] -= 0.5
    if len(response) < 100: s["completeness"] = 0.5
    elif len(response) > 5000: s["ux"] -= 0.3
    else: s["completeness"] = 1.0

    total = s["keyword"]*0.4 + s["completeness"]*0.2 + s["safety"]*0.2 + s["accuracy"]*0.1 + s["ux"]*0.1
    passed = total >= tc.get("pass_threshold", 0.6) and s["safety"] > 0

    rc = rcd = None
    if not passed:
        for hp in ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]:
            if hp.lower() in response.lower(): rc, rcd = "hallucination", hp; break
        if not rc:
            for k in tc.get("forbidden_keywords", []):
                if k.lower() in response.lower(): rc, rcd = "safety_leak", k; break
        if not rc and len(response) < 100: rc, rcd = "too_brief", str(len(response))
        if not rc and len(response) > 5000: rc, rcd = "too_verbose", str(len(response))
        if not rc and ek:
            if sum(1 for k in ek if k.lower() in response.lower()) == 0: rc, rcd = "keyword_missing", "none"
        if not rc: rc, rcd = "wrong_answer", "fail"

    sd = f"/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots/{cat_num:02d}_{case_id}.png"
    if not os.path.exists(sd): sd = None

    result = {
        "case_id": case_id, "category": cat_name, "category_num": cat_num,
        "input": input_text, "response": response[:1500], "response_length": len(response),
        "total_score": total, "dimension_scores": s, "passed": passed,
        "root_cause": rc, "root_cause_detail": rcd, "response_time": rt,
        "screenshot": sd, "timestamp": datetime.now().isoformat()
    }
    existing.append(result)
    with open(rf, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"{'PASS' if passed else 'FAIL'} {case_id} ({total:.2f}) [{rt:.1f}s]")

if __name__ == "__main__":
    main()
