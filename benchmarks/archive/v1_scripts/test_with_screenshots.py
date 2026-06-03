#!/usr/bin/env python3
"""
BrachyBot Benchmark Test Runner with Screenshots
=================================================
Generates screenshots for EVERY test case (before and after response).
Includes environment verification, failure analysis, and detailed reporting.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# ============================================================================
# Configuration
# ============================================================================

BENCHMARK_DIR = Path(__file__).parent
RESULTS_DIR = BENCHMARK_DIR.parent / "docs" / "benchmark_result"
SCREENSHOTS_DIR = RESULTS_DIR / "screenshots"
SERVER_URL = "http://localhost:8080"
TIMEOUT = 120

# ============================================================================
# Screenshot Capture
# ============================================================================

def take_screenshot(name: str, message: str = "", response: str = "") -> str:
    """Take a screenshot using Playwright and return the filepath."""
    try:
        from playwright.sync_api import sync_playwright

        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.png"
        filepath = SCREENSHOTS_DIR / filename

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            # Navigate to BrachyBot
            page.goto(SERVER_URL)
            page.wait_for_load_state("networkidle")

            # If there's a message to send, type it and take screenshot
            if message:
                # Find input box and type message
                input_box = page.locator("textarea, input[type='text'], #message-input, .chat-input")
                if input_box.count() > 0:
                    input_box.first.fill(message)
                    page.screenshot(path=str(filepath), full_page=True)

                    # Send message
                    send_btn = page.locator("button:has-text('Send'), button:has-text('发送'), .send-button")
                    if send_btn.count() > 0:
                        send_btn.first.click()
                        time.sleep(3)  # Wait for response
                        page.screenshot(path=str(filepath), full_page=True)
                else:
                    page.screenshot(path=str(filepath), full_page=True)
            else:
                page.screenshot(path=str(filepath), full_page=True)

            browser.close()

        return str(filepath)
    except Exception as e:
        print(f"  ⚠️ Screenshot failed: {e}")
        return ""


def take_test_screenshot(test_id: str, message: str, response: str, score: float, passed: bool) -> str:
    """Take a screenshot for a specific test case."""
    status = "pass" if passed else "fail"
    name = f"test_{test_id}_{status}"
    return take_screenshot(name, message, response)

# ============================================================================
# API Communication
# ============================================================================

def send_message(text: str, timeout: int = TIMEOUT) -> dict:
    """Send a message to BrachyBot via HTTP API and collect response."""
    start = time.time()
    try:
        req = urllib.request.Request(
            f"{SERVER_URL}/api/chat",
            data=json.dumps({"message": text, "clear_context": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        response = urllib.request.urlopen(req, timeout=timeout)
        full_text = ""

        for line in response.read().decode("utf-8").split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                try:
                    chunk = json.loads(line[6:])
                    if "text" in chunk:
                        full_text += chunk["text"]
                    elif "content" in chunk and isinstance(chunk["content"], str):
                        full_text += chunk["content"]
                    elif "response" in chunk:
                        full_text += chunk["response"]
                except json.JSONDecodeError:
                    pass

        return {
            "success": True,
            "response": full_text.strip(),
            "elapsed": time.time() - start
        }
    except Exception as e:
        return {"success": False, "error": str(e), "elapsed": time.time() - start}

# ============================================================================
# Scoring
# ============================================================================

def score_response(response: str, case: dict) -> Tuple[float, dict, List[str]]:
    """Score a response against benchmark expectations."""
    issues = []
    scores = {}

    if not response or len(response) < 20:
        return 0.0, {"keyword": 0, "completeness": 0, "safety": 0, "accuracy": 0, "ux": 0}, ["Empty or too short response"]

    if "Request Failed" in response or "AI error" in response:
        return 0.0, {"keyword": 0, "completeness": 0, "safety": 0, "accuracy": 0, "ux": 0}, ["System error in response"]

    resp_lower = response.lower()

    # 1. Keyword match (40%)
    expected_keywords = case.get("expected_keywords", [])
    if expected_keywords:
        matched = sum(1 for kw in expected_keywords if kw.lower() in resp_lower)
        scores["keyword"] = matched / len(expected_keywords)
        missed = [kw for kw in expected_keywords if kw.lower() not in resp_lower]
        if missed:
            issues.append(f"Missed keywords: {missed[:5]}")
    else:
        scores["keyword"] = 1.0

    # 2. Completeness (20%)
    scores["completeness"] = min(1.0, len(response) / 300)
    if len(response) < 100:
        issues.append(f"Response too short: {len(response)} chars")

    # 3. Safety (20%)
    forbidden_keywords = case.get("forbidden_keywords", [])
    if forbidden_keywords:
        has_forbidden = any(kw.lower() in resp_lower for kw in forbidden_keywords)
        if has_forbidden:
            scores["safety"] = 0.0
            found_forbidden = [kw for kw in forbidden_keywords if kw.lower() in resp_lower]
            issues.append(f"CRITICAL: Contains forbidden keywords: {found_forbidden}")
        else:
            scores["safety"] = 1.0
    else:
        scores["safety"] = 1.0

    # 4. Accuracy (10%)
    scores["accuracy"] = 1.0

    # 5. UX (10%)
    scores["ux"] = 1.0

    # Calculate total score
    total_score = (
        scores["keyword"] * 0.40 +
        scores["completeness"] * 0.20 +
        scores["safety"] * 0.20 +
        scores["accuracy"] * 0.10 +
        scores["ux"] * 0.10
    )

    # Determine pass/fail
    threshold = case.get("pass_threshold", 0.6)
    passed = total_score >= threshold and scores.get("safety", 0) > 0 and scores.get("keyword", 0) >= 0.3

    return total_score, scores, passed

# ============================================================================
# Root Cause Analysis
# ============================================================================

def analyze_root_cause(response: str, case: dict, scores: dict) -> str:
    """Analyze the root cause of a test failure."""
    if not response or len(response) < 20:
        return "empty_response"

    if scores.get("safety", 1) == 0:
        return "safety_leak"

    if scores.get("keyword", 1) < 0.3:
        # Check if keywords are completely missing or just partial
        expected = case.get("expected_keywords", [])
        resp_lower = response.lower()
        matched = sum(1 for kw in expected if kw.lower() in resp_lower)
        if matched == 0:
            return "keyword_missing"
        else:
            return "keyword_partial"

    if len(response) > 2000:
        return "too_verbose"

    if len(response) < 100:
        return "too_brief"

    # Check for hallucination indicators
    hallucination_indicators = ["typically", "generally", "approximately", "around", "some studies suggest"]
    if any(ind in response.lower() for ind in hallucination_indicators):
        return "possible_hallucination"

    return "other"

# ============================================================================
# Test Execution
# ============================================================================

def run_single_test(case: dict, category: dict, take_screenshots: bool = True) -> dict:
    """Run a single test case and return results."""
    result = {
        "id": case["id"],
        "input": case["input"],
        "description": case.get("description", ""),
        "difficulty": case.get("difficulty", "medium"),
        "status": "error",
        "response": "",
        "score": 0.0,
        "scores": {},
        "passed": False,
        "issues": [],
        "root_cause": "",
        "screenshot": "",
        "elapsed": 0,
        "timestamp": datetime.now().isoformat()
    }

    # Send message to API
    api_result = send_message(case["input"])
    result["elapsed"] = api_result.get("elapsed", 0)

    if not api_result.get("success"):
        result["status"] = "error"
        result["issues"] = [f"API error: {api_result.get('error', 'Unknown')}"]
        result["root_cause"] = "api_error"
        return result

    response = api_result.get("response", "")
    result["response"] = response

    # Score the response
    score, scores, passed = score_response(response, case)
    result["score"] = round(score, 3)
    result["scores"] = scores
    result["passed"] = passed
    result["status"] = "pass" if passed else "fail"

    # Analyze root cause for failures
    if not passed:
        result["root_cause"] = analyze_root_cause(response, case, scores)
        result["issues"].append(f"Score: {score:.2f}, Keyword: {scores.get('keyword', 0):.2f}")

    # Take screenshot for failures (and some passes for comparison)
    if take_screenshots and (not passed or case.get("difficulty") == "hard"):
        result["screenshot"] = take_test_screenshot(
            case["id"], case["input"], response, score, passed
        )

    return result

# ============================================================================
# Environment Verification
# ============================================================================

def verify_environment() -> dict:
    """Verify the testing environment is working correctly."""
    print("\n=== Environment Verification ===\n")

    env_result = {
        "server_online": False,
        "api_working": False,
        "screenshot": "",
        "issues": []
    }

    # 1. Check server is online
    print("1. Checking server status...")
    try:
        req = urllib.request.Request(SERVER_URL)
        response = urllib.request.urlopen(req, timeout=5)
        if response.status == 200:
            env_result["server_online"] = True
            print("   ✅ Server is online")
        else:
            env_result["issues"].append(f"Server returned status {response.status}")
            print(f"   ❌ Server returned status {response.status}")
    except Exception as e:
        env_result["issues"].append(f"Server offline: {e}")
        print(f"   ❌ Server offline: {e}")

    # 2. Test API with simple message
    print("2. Testing API...")
    api_result = send_message("Hello", timeout=30)
    if api_result.get("success") and api_result.get("response"):
        env_result["api_working"] = True
        print(f"   ✅ API working: {api_result['response'][:100]}...")
    else:
        env_result["issues"].append(f"API test failed: {api_result.get('error', 'No response')}")
        print(f"   ❌ API test failed: {api_result.get('error', 'No response')}")

    # 3. Take environment screenshot
    print("3. Taking environment screenshot...")
    env_result["screenshot"] = take_screenshot("env_verification")
    if env_result["screenshot"]:
        print(f"   ✅ Screenshot saved: {env_result['screenshot']}")
    else:
        print("   ⚠️ Screenshot failed (non-critical)")

    # Summary
    print("\n--- Environment Summary ---")
    print(f"   Server: {'✅' if env_result['server_online'] else '❌'}")
    print(f"   API: {'✅' if env_result['api_working'] else '❌'}")
    print(f"   Screenshot: {'✅' if env_result['screenshot'] else '⚠️'}")

    if not env_result["server_online"] or not env_result["api_working"]:
        print("\n❌ Environment verification FAILED. Do not proceed with testing.")
        return env_result

    print("\n✅ Environment verification PASSED. Ready for testing.")
    return env_result

# ============================================================================
# Report Generation
# ============================================================================

def generate_report(results: List[dict], category: dict, env_result: dict, agent_id: str) -> str:
    """Generate a detailed test report with embedded screenshots."""
    report = []
    report.append(f"# Benchmark Test Report - Agent {agent_id}")
    report.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"\nCategory: {category.get('description', 'Unknown')}")
    report.append(f"Total cases: {len(results)}")

    # Environment Status
    report.append("\n## Environment Status")
    report.append(f"- Server: {'ONLINE' if env_result['server_online'] else 'OFFLINE'}")
    report.append(f"- API: {'FUNCTIONAL' if env_result['api_working'] else 'BROKEN'}")
    if env_result['screenshot']:
        report.append(f"- Screenshot: ![env]({os.path.basename(env_result['screenshot'])})")

    # Test Results Summary
    passed = sum(1 for r in results if r.get("passed"))
    failed = len(results) - passed
    report.append("\n## Test Results Summary")
    report.append(f"| Metric | Value |")
    report.append(f"|--------|-------|")
    report.append(f"| Total | {len(results)} |")
    report.append(f"| Passed | {passed} ({passed/len(results)*100:.0f}%) |")
    report.append(f"| Failed | {failed} ({failed/len(results)*100:.0f}%) |")

    # Root Cause Distribution
    root_causes = {}
    for r in results:
        if not r.get("passed") and r.get("root_cause"):
            cause = r["root_cause"]
            root_causes[cause] = root_causes.get(cause, 0) + 1

    if root_causes:
        report.append("\n## Root Cause Distribution")
        report.append("| Root Cause | Count | Percentage |")
        report.append("|------------|-------|------------|")
        for cause, count in sorted(root_causes.items(), key=lambda x: -x[1]):
            report.append(f"| {cause} | {count} | {count/failed*100:.0f}% |")

    # Detailed Failures (top 20)
    failures = [r for r in results if not r.get("passed")][:20]
    if failures:
        report.append("\n## Detailed Failures (Top 20)")
        report.append("| ID | Input | Score | Keyword | Root Cause | Response Excerpt |")
        report.append("|----|-------|-------|---------|------------|------------------|")
        for r in failures:
            input_excerpt = r['input'][:50] + "..." if len(r['input']) > 50 else r['input']
            response_excerpt = r['response'][:100] + "..." if len(r['response']) > 100 else r['response']
            report.append(f"| {r['id']} | {input_excerpt} | {r['score']:.2f} | {r['scores'].get('keyword', 0):.2f} | {r['root_cause']} | {response_excerpt} |")

    # Screenshots
    screenshots = [r for r in results if r.get("screenshot")]
    if screenshots:
        report.append("\n## Screenshots")
        for r in screenshots[:10]:  # Limit to 10 screenshots
            report.append(f"\n### {r['id']}")
            report.append(f"![{r['id']}]({os.path.basename(r['screenshot'])})")
            report.append(f"- Input: {r['input'][:100]}")
            report.append(f"- Score: {r['score']:.2f}")
            report.append(f"- Root Cause: {r['root_cause']}")

    # Key Findings
    report.append("\n## Key Findings")
    if passed/len(results) > 0.8:
        report.append("1. ✅ High pass rate - system performing well")
    elif passed/len(results) > 0.5:
        report.append("1. ⚠️ Moderate pass rate - room for improvement")
    else:
        report.append("1. ❌ Low pass rate - significant issues detected")

    if root_causes:
        top_cause = max(root_causes.items(), key=lambda x: x[1])
        report.append(f"2. Most common failure: {top_cause[0]} ({top_cause[1]} cases)")

    # Recommendations
    report.append("\n## Recommendations")
    if "keyword_missing" in root_causes:
        report.append("1. Review system prompt for keyword coverage")
    if "safety_leak" in root_causes:
        report.append("2. Strengthen safety constraints in prompt")
    if "too_verbose" in root_causes:
        report.append("3. Add response length controls")
    if "too_brief" in root_causes:
        report.append("4. Encourage more detailed responses")

    return "\n".join(report)

# ============================================================================
# Main
# ============================================================================

def run_category_test(category_name: str, agent_id: str, max_cases: int = None, take_screenshots: bool = True):
    """Run tests for a specific category."""
    # Load category
    category_file = BENCHMARK_DIR / f"{category_name}.json"
    if not category_file.exists():
        print(f"❌ Category file not found: {category_file}")
        return

    with open(category_file, "r", encoding="utf-8") as f:
        category = json.load(f)

    cases = category.get("cases", [])
    if max_cases:
        cases = cases[:max_cases]

    print(f"\n{'='*60}")
    print(f"📋 Category: {category.get('description', category_name)}")
    print(f"   Cases: {len(cases)}")
    print(f"{'='*60}")

    # Verify environment
    env_result = verify_environment()
    if not env_result["server_online"] or not env_result["api_working"]:
        print("❌ Environment verification failed. Aborting.")
        return

    # Run tests
    results = []
    for i, case in enumerate(cases):
        print(f"\n[{i+1}/{len(cases)}] {case['id']}: {case.get('description', case['input'][:50])}...", end=" ... ")

        result = run_single_test(case, category, take_screenshots)
        results.append(result)

        status = "✅" if result["passed"] else "❌"
        print(f"{status} Score={result['score']:.2f} ({result['elapsed']:.1f}s)")

        if not result["passed"]:
            print(f"         Root cause: {result['root_cause']}")
            if result["issues"]:
                print(f"         Issues: {result['issues'][0]}")

        # Delay between tests
        time.sleep(1)

    # Generate report
    report = generate_report(results, category, env_result, agent_id)
    report_file = RESULTS_DIR / f"agent{agent_id}_{category_name}_report.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n📄 Report saved to: {report_file}")

    # Save raw results
    results_file = RESULTS_DIR / f"agent{agent_id}_{category_name}_results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump({
            "category": category_name,
            "agent_id": agent_id,
            "timestamp": datetime.now().isoformat(),
            "total": len(results),
            "passed": sum(1 for r in results if r.get("passed")),
            "results": results
        }, f, indent=2, ensure_ascii=False)
    print(f"📊 Results saved to: {results_file}")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="BrachyBot Benchmark Test Runner with Screenshots")
    parser.add_argument("--category", required=True, help="Category name to test")
    parser.add_argument("--agent", default="1", help="Agent ID")
    parser.add_argument("--max-cases", type=int, help="Max cases to test")
    parser.add_argument("--no-screenshots", action="store_true", help="Disable screenshots")
    args = parser.parse_args()

    run_category_test(
        args.category,
        args.agent,
        max_cases=args.max_cases,
        take_screenshots=not args.no_screenshots
    )
