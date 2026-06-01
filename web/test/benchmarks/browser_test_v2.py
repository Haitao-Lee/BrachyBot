#!/usr/bin/env python3
"""
BrachyBot Browser Test V2 - Test one, evaluate one, fix one.
Improved: health check, longer timeout, better response capture, AI evaluation.
"""

import json, os, sys, time, asyncio, re, subprocess
from pathlib import Path
from datetime import datetime

BASE_URL = "http://localhost:8080"
SCREENSHOTS_DIR = Path(__file__).parent / "screenshots_v2"
RESULTS_DIR = Path(__file__).parent / "results_v2"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

MAX_WAIT_SECONDS = 180  # 3 minutes per question
HEALTH_CHECK_INTERVAL = 10  # seconds between health checks


def check_server_health():
    """Check if BrachyBot server is online and responding."""
    import urllib.request
    try:
        req = urllib.request.urlopen(f"{BASE_URL}/api/status", timeout=10)
        data = json.loads(req.read())
        return data.get("brain_available", False)
    except Exception as e:
        return False


def ensure_server_running():
    """Ensure BrachyBot server is running, restart if needed."""
    if check_server_health():
        return True

    print("⚠️  Server offline, attempting restart...", flush=True)
    # Kill existing process
    subprocess.run(["pkill", "-f", "python web/server.py"], capture_output=True)
    time.sleep(2)

    # Start new process
    subprocess.Popen(
        ["python", "web/server.py"],
        cwd="/home/lht/snap/brachyplan/BrachyBot",
        stdout=open("/tmp/brachybot_server.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True
    )

    # Wait for startup
    for i in range(30):
        time.sleep(2)
        if check_server_health():
            print("✅ Server restarted successfully", flush=True)
            return True

    print("❌ Server failed to restart", flush=True)
    return False


def clean_response(text):
    """Remove streaming artifacts and UI noise from response."""
    text = re.sub(r'▶\s*\n?Thinking\s*\d+/\d+\s*steps\s*\n?[\d.]+s\s*\n?', '', text)
    text = re.sub(r'👤\s*\n?User Input\s*\n?done\s*\n?', '', text)
    text = re.sub(r'Execution Trace.*?(?=\n\n\n|\nHello|\nHi|\nGood|\nThank|\nI |The )', '', text, flags=re.DOTALL)
    text = re.sub(r'\d+\.\d+s\s*\n?tokens\s*~\d+\s*\n?out\s*~\d+\s*\n?calls\s*\d+', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def check_keywords(response, keywords, operator="AND"):
    """Lenient keyword validation."""
    if not keywords:
        return 1.0
    resp_lower = response.lower()
    matches = sum(1 for kw in keywords if kw.lower() in resp_lower)
    if operator == "OR":
        return 1.0 if matches > 0 else (0.5 if len(response) > 100 else 0.0)
    else:  # AND
        if len(response) < 50:
            return 0.0
        if matches == 0:
            return 0.5 if len(response) > 300 else 0.2
        return min(1.0, matches / max(len(keywords), 1) * 2.0)


def check_forbidden(response, forbidden):
    if not forbidden:
        return True
    resp_lower = response.lower()
    return not any(kw.lower() in resp_lower for kw in forbidden)


def score_response(response, benchmark):
    """Score response on multiple dimensions."""
    scores = {}
    cleaned = clean_response(response)
    kw_op = benchmark.get("expected_keywords_operator", "AND")
    kw_list = benchmark.get("expected_keywords", [])

    scores["correctness"] = check_keywords(cleaned, kw_list, kw_op)
    scores["completeness"] = min(1.0, len(cleaned) / 500)
    scores["safety"] = 1.0 if check_forbidden(cleaned, benchmark.get("forbidden_keywords", [])) else 0.0
    scores["ux"] = 1.0 if 100 < len(cleaned) < 10000 else 0.5
    scores["robustness"] = 1.0

    weights = {"correctness": 0.4, "completeness": 0.2, "safety": 0.2, "ux": 0.1, "robustness": 0.1}
    total = sum(scores[k] * weights[k] for k in weights)
    return total, scores, scores["safety"] < 1.0


def evaluate_response_brachybot(response, benchmark):
    """
    Evaluate if the response is acceptable based on BrachyBot's capabilities.
    Returns: (is_acceptable, issue_type, root_cause, fix_needed)
    """
    cleaned = clean_response(response)

    # Check for system errors - use word boundaries to avoid false positives
    # "AI error" should match "AI error" but not "AI errors in medicine" or "AI errors:"
    # "Request Failed" should match as a UI error message
    import re
    ai_error_pattern = re.search(r'\bAI error\b(?!\s*[s:])', response, re.IGNORECASE)
    request_failed_pattern = "Request Failed" in response
    if request_failed_pattern or ai_error_pattern:
        return False, "system_error", "Server/API timeout or failure", True

    if len(cleaned) < 20:
        return False, "empty_response", "Response too short, possibly timeout", True

    # Check for hallucination indicators
    forbidden = benchmark.get("forbidden_keywords", [])
    if forbidden and not check_forbidden(cleaned, forbidden):
        return False, "hallucination", "Contains forbidden/incorrect content", True

    # Check keyword match
    kw_op = benchmark.get("expected_keywords_operator", "AND")
    kw_list = benchmark.get("expected_keywords", [])
    if kw_list:
        kw_score = check_keywords(cleaned, kw_list, kw_op)
        if kw_score < 0.3:
            return False, "poor_quality", "Response doesn't address the question", True

    # Check if response is too short for the question complexity
    expected_min = benchmark.get("pass_threshold", 0.75) * 1000
    if len(cleaned) < expected_min * 0.3:
        return False, "insufficient", "Response too brief for the question", True

    return True, "pass", "Response acceptable", False


async def test_one_question(page, benchmark, idx, total):
    """Test one question with full evaluation."""
    bid = benchmark["id"]
    cat = benchmark["category"]
    inp = benchmark["input"]
    threshold = benchmark.get("pass_threshold", 0.75)

    print(f"\n{'='*60}", flush=True)
    print(f"[{idx+1}/{total}] Testing: {bid} ({cat})", flush=True)
    print(f"Input: {inp[:100]}...", flush=True)
    print(f"{'='*60}", flush=True)

    result = {
        "id": bid, "category": cat, "input": inp, "status": "error",
        "response": "", "screenshot": "", "pass": False, "score": 0,
        "scores": {}, "hallucination": False, "ux_score": 0,
        "error": None, "timestamp": datetime.now().isoformat(),
        "evaluation": {}
    }

    try:
        # Ensure server is running
        if not ensure_server_running():
            result["error"] = "Server offline"
            result["evaluation"] = {"is_acceptable": False, "issue_type": "server_offline"}
            return result

        # Clear input and type question
        chat_input = page.locator("#chatInput")
        await chat_input.clear()
        await page.wait_for_timeout(300)
        await chat_input.fill(inp)
        await page.wait_for_timeout(300)

        # Click send with clear_context flag to prevent context contamination
        # First, modify the sendChat function to include clear_context
        await page.evaluate("""
            window._clearContext = true;
        """)
        await page.locator(".chat-send").click()
        print("📤 Question sent (with context clear), waiting for response...", flush=True)

        # Wait for response with extended timeout
        response_text = ""
        start = time.time()
        last_len = 0
        stable_count = 0
        thinking_started = False

        while time.time() - start < MAX_WAIT_SECONDS:
            elapsed = time.time() - start

            try:
                # Check for error messages first
                error_msgs = await page.locator(".chat-msg.error").all()
                if error_msgs:
                    for em in error_msgs:
                        txt = await em.inner_text()
                        if "Request Failed" in txt or "AI error" in txt:
                            response_text = txt
                            print(f"  ❌ Error detected: {txt[:100]}", flush=True)
                            break

                # Check for bot responses - use bot-response class specifically
                if not response_text:
                    # First try to get the actual bot response (not thinking chain)
                    bot_msgs = await page.locator(".chat-msg.bot-response").all()
                    if bot_msgs:
                        # Get the LAST bot-response element (the most recent one)
                        for m in reversed(bot_msgs):
                            try:
                                txt = await m.inner_text()
                                # Skip trace/stats, get substantial content
                                if len(txt) > 50 and "Execution Trace" not in txt and "tokens" not in txt:
                                    response_text = txt
                                    if not thinking_started:
                                        thinking_started = True
                                        print(f"  💭 Response started ({len(txt)} chars)", flush=True)
                                    break
                            except:
                                pass

                    # Fallback: try chat-row.bot but filter out thinking chain
                    if not response_text:
                        msgs = await page.locator(".chat-row.bot").all()
                        if msgs:
                            for m in reversed(msgs):
                                try:
                                    txt = await m.inner_text()
                                    # Skip trace/stats, skip thinking chain content
                                    if (len(txt) > 50 and
                                        "Execution Trace" not in txt and
                                        "tokens" not in txt and
                                        "Thinking" not in txt[:20] and
                                        "User Input" not in txt and
                                        "Crystallized Skill" not in txt and
                                        "Experience Recall" not in txt and
                                        "LLM Call" not in txt):
                                        response_text = txt
                                        if not thinking_started:
                                            thinking_started = True
                                            print(f"  💭 Response started ({len(txt)} chars)", flush=True)
                                        break
                                except:
                                    pass

                # Update response if we find a longer one
                if response_text:
                    bot_msgs = await page.locator(".chat-msg.bot-response").all()
                    for m in reversed(bot_msgs):
                        try:
                            txt = await m.inner_text()
                            if len(txt) > len(response_text) and "Execution Trace" not in txt:
                                response_text = txt
                        except:
                            pass

                # Check stability - only consider complete if stable for 10 seconds AND no thinking indicator
                thinking_visible = await page.locator(".thinking-indicator").count()
                # Check for the thinking chain container (shows steps like "Thinking 3/4 steps")
                thinking_chain_visible = await page.locator("text=/Thinking \\d+/").count()

                if len(response_text) > 0:
                    if len(response_text) == last_len:
                        stable_count += 1
                        # Only consider complete if:
                        # 1. Stable for 10 seconds
                        # 2. No thinking indicator
                        # 3. No thinking chain text visible
                        # 4. Response is substantial (>200 chars)
                        if (stable_count >= 10 and
                            thinking_visible == 0 and
                            thinking_chain_visible == 0 and
                            len(response_text) > 200):
                            print(f"  ✅ Response complete ({len(response_text)} chars, {elapsed:.1f}s)", flush=True)
                            break
                    else:
                        stable_count = 0
                        last_len = len(response_text)
                        if len(response_text) % 500 < 10:  # Progress update
                            print(f"  📝 Progress: {len(response_text)} chars ({elapsed:.1f}s)", flush=True)

                # Progress update for long waits
                if elapsed > 30 and int(elapsed) % 30 == 0:
                    print(f"  ⏳ Waiting... ({elapsed:.1f}s, {len(response_text)} chars)", flush=True)

            except Exception as e:
                pass

            await page.wait_for_timeout(1000)

        # Final response
        result["response"] = response_text

        # Take screenshot
        ss_path = SCREENSHOTS_DIR / f"{bid}_{cat}.png"
        await page.screenshot(path=str(ss_path), full_page=True)
        result["screenshot"] = str(ss_path)
        print(f"📸 Screenshot saved: {ss_path.name}", flush=True)

        # Score response
        total_score, scores, hallucination = score_response(response_text, benchmark)
        result["score"] = round(total_score, 3)
        result["scores"] = scores
        result["hallucination"] = hallucination

        # AI Evaluation
        is_acceptable, issue_type, root_cause, fix_needed = evaluate_response_brachybot(response_text, benchmark)
        result["evaluation"] = {
            "is_acceptable": is_acceptable,
            "issue_type": issue_type,
            "root_cause": root_cause,
            "fix_needed": fix_needed
        }

        # Determine pass/fail
        passes = total_score >= threshold and not hallucination and is_acceptable
        result["pass"] = passes
        result["status"] = "pass" if passes else "fail"
        result["ux_score"] = 5 if total_score >= 0.8 else (4 if total_score >= 0.6 else (3 if total_score >= 0.4 else 2))

        mark = "✅" if passes else "❌"
        print(f"\n{mark} Result: Score={total_score:.2f}, KW={scores['correctness']:.2f}, Safety={scores['safety']:.2f}", flush=True)
        print(f"   Evaluation: {issue_type} - {root_cause}", flush=True)

        # Click +New for next question
        try:
            new_btn = page.locator("text=+ New").first
            if await new_btn.is_visible():
                await new_btn.click()
                await page.wait_for_timeout(500)
        except:
            pass

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        result["evaluation"] = {"is_acceptable": False, "issue_type": "exception", "root_cause": str(e)}
        print(f"  ❌ EXCEPTION: {e}", flush=True)

    return result


def analyze_and_fix(result, all_results):
    """
    Analyze the result and determine if BrachyBot needs fixing.
    Returns: (needs_fix, fix_description)
    """
    eval_data = result.get("evaluation", {})

    if eval_data.get("issue_type") == "system_error":
        return True, "Server/API timeout - need to increase timeout or optimize API calls"

    if eval_data.get("issue_type") == "empty_response":
        return True, "Empty response - need to debug response capture or server processing"

    if eval_data.get("issue_type") == "hallucination":
        return True, f"Hallucination detected - need to review system prompt for {result['category']}"

    if eval_data.get("issue_type") == "poor_quality":
        # Check if this is a pattern
        category = result["category"]
        category_fails = [r for r in all_results if r["category"] == category and not r["pass"]]
        if len(category_fails) > 5:
            return True, f"Pattern of poor responses in {category} - may need category-specific improvements"

    return False, "No fix needed"


async def run_single_test(benchmark_id=None, benchmark_index=0):
    """Run a single test for immediate feedback."""
    merged = Path(__file__).parent / "benchmark_2000.json"
    if not merged.exists():
        print("❌ No benchmark file found.")
        return

    with open(merged) as f:
        benchmarks = json.load(f)

    if benchmark_id:
        bench = next((b for b in benchmarks if b["id"] == benchmark_id), None)
        if not bench:
            print(f"❌ Benchmark {benchmark_id} not found.")
            return
        idx = benchmarks.index(bench)
    else:
        idx = benchmark_index
        bench = benchmarks[idx]

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await ctx.new_page()

        await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        result = await test_one_question(page, bench, idx, len(benchmarks))

        # Analyze
        needs_fix, fix_desc = analyze_and_fix(result, [result])
        if needs_fix:
            print(f"\n🔧 FIX NEEDED: {fix_desc}", flush=True)

        # Save result
        result_file = RESULTS_DIR / f"single_test_{bench['id']}.json"
        with open(result_file, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"\n📄 Result saved to {result_file}", flush=True)

        await browser.close()

    return result


async def run_batch_test(start_idx=0, count=10):
    """Run a batch of tests with monitoring."""
    merged = Path(__file__).parent / "benchmark_2000.json"
    if not merged.exists():
        print("❌ No benchmark file found.")
        return

    with open(merged) as f:
        benchmarks = json.load(f)

    end_idx = min(start_idx + count, len(benchmarks))
    batch = benchmarks[start_idx:end_idx]

    print(f"\n{'='*60}", flush=True)
    print(f"🚀 BrachyBot Browser Test V2 - Batch", flush=True)
    print(f"   Testing {len(batch)} questions ({start_idx+1} to {end_idx})", flush=True)
    print(f"{'='*60}\n", flush=True)

    all_results = []
    fixes_needed = []

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await ctx.new_page()

        await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        for idx, bench in enumerate(batch):
            result = await test_one_question(page, bench, start_idx + idx, len(benchmarks))
            all_results.append(result)

            # Analyze and fix
            needs_fix, fix_desc = analyze_and_fix(result, all_results)
            if needs_fix:
                fixes_needed.append({
                    "id": bench["id"],
                    "issue": result["evaluation"].get("issue_type"),
                    "description": fix_desc,
                    "response_preview": result["response"][:200]
                })
                print(f"🔧 Fix needed: {fix_desc}", flush=True)

            # Save progress
            if (idx + 1) % 5 == 0:
                save_progress(all_results, fixes_needed, start_idx, end_idx)

        await browser.close()

    # Final save
    save_progress(all_results, fixes_needed, start_idx, end_idx)

    # Print summary
    print_batch_summary(all_results, fixes_needed)

    return all_results, fixes_needed


def save_progress(results, fixes, start_idx, end_idx):
    """Save test progress."""
    summary = {
        "start_idx": start_idx,
        "end_idx": end_idx,
        "total": len(results),
        "pass": sum(1 for r in results if r["pass"]),
        "fail": sum(1 for r in results if not r["pass"]),
        "fixes_needed": len(fixes),
        "timestamp": datetime.now().isoformat()
    }

    with open(RESULTS_DIR / "batch_progress.json", "w") as f:
        json.dump(summary, f, indent=2)

    with open(RESULTS_DIR / "batch_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    with open(RESULTS_DIR / "fixes_needed.json", "w") as f:
        json.dump(fixes, f, indent=2, ensure_ascii=False)


def print_batch_summary(results, fixes):
    """Print batch test summary."""
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    failed = total - passed

    print(f"\n{'='*60}", flush=True)
    print(f"📊 BATCH SUMMARY", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"Total: {total} | Pass: {passed} ({passed/total*100:.1f}%) | Fail: {failed} ({failed/total*100:.1f}%)", flush=True)
    print(f"Fixes needed: {len(fixes)}", flush=True)

    if fixes:
        print(f"\n🔧 ISSUES REQUIRING FIXES:", flush=True)
        for fix in fixes:
            print(f"  - {fix['id']}: {fix['description']}", flush=True)

    # Category breakdown
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"pass": 0, "fail": 0}
        if r["pass"]:
            categories[cat]["pass"] += 1
        else:
            categories[cat]["fail"] += 1

    print(f"\n📈 CATEGORY BREAKDOWN:", flush=True)
    for cat, stats in sorted(categories.items()):
        t = stats["pass"] + stats["fail"]
        print(f"  {cat}: {stats['pass']}/{t} ({stats['pass']/t*100:.1f}%)", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="BrachyBot Browser Test V2")
    parser.add_argument("--mode", choices=["single", "batch"], default="single",
                       help="Test mode: single question or batch")
    parser.add_argument("--id", help="Question ID for single test (e.g., Q0001)")
    parser.add_argument("--index", type=int, default=0, help="Question index for single test")
    parser.add_argument("--start", type=int, default=0, help="Start index for batch test")
    parser.add_argument("--count", type=int, default=10, help="Number of questions for batch test")
    args = parser.parse_args()

    if args.mode == "single":
        asyncio.run(run_single_test(benchmark_id=args.id, benchmark_index=args.index))
    else:
        asyncio.run(run_batch_test(start_idx=args.start, count=args.count))
