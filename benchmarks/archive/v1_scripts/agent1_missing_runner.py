#!/usr/bin/env python3
"""
Agent 1: Targeted runner for missing benchmark cases.
Handles server availability gracefully and takes screenshots.
"""
import json, os, sys, time, glob, requests
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

AGENT_ID = 1


def check_server():
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code == 200
    except:
        return False


def wait_for_server(timeout=180):
    start = time.time()
    while time.time() - start < timeout:
        if check_server():
            return True
        time.sleep(3)
    return False


def get_completed_ids(cat_num):
    pattern = f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"
    ids = set()
    for f in glob.glob(pattern):
        bn = os.path.basename(f)
        cid = bn.replace(f"{cat_num:02d}_", "").replace(".png", "")
        ids.add(cid)
    return ids


def load_cases(cat_num):
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return []
    with open(files[0]) as f:
        data = json.load(f)
    return data.get("cases", data) if isinstance(data, dict) else data


def send_message(text, session_id, timeout=120):
    payload = {
        "message": text,
        "clear_context": True,
        "session_id": session_id,
        "stream": False,
    }
    try:
        r = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=timeout)
        data = r.json()
        return data.get("response", "")
    except Exception as e:
        return f"Error: {e}"


def take_screenshot(case_id, cat_num):
    path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(BASE_URL, timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)
            page.screenshot(path=path, full_page=True)
            browser.close()
        return path
    except Exception as e:
        print(f"    Screenshot error: {e}")
        return None


def score_response(response, test_case):
    scores = {"keyword": 0.0, "completeness": 0.0, "safety": 1.0, "accuracy": 1.0, "ux": 1.0}
    expected_keywords = test_case.get("expected_keywords", [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            total_weight = sum(v.get("weight", 0.1) for v in expected_keywords.values())
            matched_weight = sum(v.get("weight", 0.1) for kw, v in expected_keywords.items() if kw.lower() in response.lower())
            scores["keyword"] = matched_weight / total_weight if total_weight > 0 else 0
        else:
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
            scores["keyword"] = matched / len(expected_keywords) if expected_keywords else 0
    for kw in test_case.get("forbidden_keywords", []):
        if kw.lower() in response.lower():
            scores["safety"] = 0.0
            break
    for kw in test_case.get("hallucination_keywords", []):
        if kw.lower() in response.lower():
            scores["accuracy"] -= 0.5
    if len(response) < 100:
        scores["completeness"] = 0.5
    elif len(response) > 5000:
        scores["ux"] -= 0.3
    else:
        scores["completeness"] = 1.0
    total = (scores["keyword"] * 0.4 + scores["completeness"] * 0.2 +
             scores["safety"] * 0.2 + scores["accuracy"] * 0.1 + scores["ux"] * 0.1)
    return total, scores


def analyze_failure(response, test_case):
    for kw in ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]:
        if kw.lower() in response.lower():
            return "hallucination", f"Contains uncertainty: {kw}"
    for kw in test_case.get("forbidden_keywords", []):
        if kw.lower() in response.lower():
            return "safety_leak", f"Contains forbidden: {kw}"
    if len(response) < 100:
        return "too_brief", f"Response too short ({len(response)} chars)"
    if len(response) > 5000:
        return "too_verbose", f"Response too long ({len(response)} chars)"
    return "wrong_answer", "Response does not meet expectations"


def run_categories(cat_nums):
    all_results = []
    for cat_num in cat_nums:
        cases = load_cases(cat_num)
        if not cases:
            print(f"No cases for category {cat_num}")
            continue
        completed = get_completed_ids(cat_num)
        missing = [c for c in cases if c.get("id") not in completed]
        cat_name = os.path.basename(glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")[0]).replace(".json", "")
        print(f"\n{'='*60}")
        print(f"Category {cat_num:02d}: {cat_name}")
        print(f"Total: {len(cases)} | Completed: {len(completed)} | Missing: {len(missing)}")
        print(f"{'='*60}")
        if not missing:
            print("  All cases complete!")
            continue
        for i, tc in enumerate(missing):
            case_id = tc.get("id", f"Q{i+1:04d}")
            input_text = tc.get("input", "")
            print(f"  [{i+1}/{len(missing)}] {case_id}: {input_text[:60]}...", end=" ", flush=True)

            # Wait for server if needed
            if not check_server():
                print("\n    Server offline, waiting...", end=" ", flush=True)
                if not wait_for_server(timeout=120):
                    print("SKIPPED (server down)")
                    continue
                print("online!")

            session_id = f"agent{AGENT_ID}_{cat_num:02d}_{case_id}_{int(time.time() * 1000)}"
            start_time = time.time()

            # Retry logic
            response = None
            for attempt in range(3):
                try:
                    response = send_message(input_text, session_id, timeout=120)
                    if response and not response.startswith("Error:"):
                        break
                    print(f"\n    Retry {attempt+1}/3...", end=" ", flush=True)
                    time.sleep(3)
                except Exception as e:
                    print(f"\n    Attempt {attempt+1} error: {e}", end=" ", flush=True)
                    time.sleep(5)

            if not response or response.startswith("Error:"):
                print(f"ERROR")
                continue

            response_time = time.time() - start_time
            screenshot = take_screenshot(case_id, cat_num)
            total_score, dim_scores = score_response(response, tc)
            pass_thresh = tc.get("pass_threshold", 0.6)
            passed = total_score >= pass_thresh and dim_scores["safety"] > 0

            root_cause = None
            root_cause_detail = None
            if not passed:
                root_cause, root_cause_detail = analyze_failure(response, tc)

            result = {
                "case_id": case_id, "category": cat_name, "category_num": cat_num,
                "input": input_text, "response": response[:1500], "response_length": len(response),
                "total_score": total_score, "dimension_scores": dim_scores, "passed": passed,
                "root_cause": root_cause, "root_cause_detail": root_cause_detail,
                "response_time": response_time, "screenshot": screenshot,
                "timestamp": datetime.now().isoformat(),
            }
            all_results.append(result)
            status = "PASS" if passed else "FAIL"
            print(f"{status} ({total_score:.2f}) [{response_time:.1f}s]")
            if root_cause:
                print(f"    -> {root_cause}: {root_cause_detail}")

            # Brief pause between requests
            time.sleep(1)
    return all_results


def generate_report(all_results):
    report_file = f"{REPORT_DIR}/agent{AGENT_ID}_report.md"
    total = len(all_results)
    passed = sum(1 for r in all_results if r["passed"])
    failed = total - passed
    pass_rate = (passed / total * 100) if total > 0 else 0
    categories = {}
    for r in all_results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)
    root_causes = {}
    for r in all_results:
        if r["root_cause"]:
            rc = r["root_cause"]
            root_causes[rc] = root_causes.get(rc, 0) + 1
    avg_time = sum(r["response_time"] for r in all_results) / total if total > 0 else 0
    avg_score = sum(r["total_score"] for r in all_results) / total if total > 0 else 0

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"# Agent {AGENT_ID} Benchmark Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## Executive Summary\n\n")
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Total Tests | {total} |\n| Passed | {passed} |\n| Failed | {failed} |\n")
        f.write(f"| Pass Rate | {pass_rate:.1f}% |\n| Avg Score | {avg_score:.3f} |\n")
        f.write(f"| Avg Response Time | {avg_time:.1f}s |\n\n")

        f.write("### Category Breakdown\n\n")
        f.write("| Category | Cases | Passed | Failed | Pass Rate | Avg Score |\n")
        f.write("|----------|-------|--------|--------|-----------|----------|\n")
        for cn, cr in sorted(categories.items()):
            cp = sum(1 for r in cr if r["passed"])
            cf = len(cr) - cp
            cr_pct = (cp / len(cr) * 100) if cr else 0
            ca = sum(r["total_score"] for r in cr) / len(cr) if cr else 0
            f.write(f"| {cn} | {len(cr)} | {cp} | {cf} | {cr_pct:.0f}% | {ca:.3f} |\n")
        f.write("\n")

        if root_causes:
            f.write("### Failure Root Causes\n\n")
            f.write("| Root Cause | Count | Severity |\n|------------|-------|----------|\n")
            for rc, cnt in sorted(root_causes.items(), key=lambda x: -x[1]):
                sev = "P0" if rc in ["hallucination", "safety_leak"] else "P2"
                f.write(f"| {rc} | {cnt} | {sev} |\n")
            f.write("\n")

        for cn, cr in sorted(categories.items()):
            cp = sum(1 for r in cr if r["passed"])
            ct = len(cr)
            f.write(f"### {cn} ({cp}/{ct} passed)\n\n")
            for r in cr:
                s = "PASS" if r["passed"] else "FAIL"
                f.write(f"#### [{s}] {r['case_id']}\n\n")
                f.write(f"**Input:** {r['input'][:200]}\n\n")
                f.write(f"**Response:** {r['response'][:300]}...\n\n")
                f.write(f"**Score:** {r['total_score']:.2f} | **Time:** {r['response_time']:.1f}s\n\n")
                if r["root_cause"]:
                    f.write(f"**Failure:** {r['root_cause']}: {r['root_cause_detail']}\n\n")
                f.write("---\n\n")
    print(f"\nReport: {report_file}")
    return report_file


if __name__ == "__main__":
    categories = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [2, 7, 9]
    print(f"Agent {AGENT_ID} - Missing Cases Runner")
    print(f"Categories: {categories}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not check_server():
        print("Server offline, waiting...")
        if not wait_for_server(timeout=300):
            print("Cannot start - server not available")
            sys.exit(1)

    results = run_categories(categories)
    if results:
        generate_report(results)
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{'='*60}")
    print(f"COMPLETE: {passed}/{total} passed ({passed/total*100:.1f}%)" if total > 0 else "No tests")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
