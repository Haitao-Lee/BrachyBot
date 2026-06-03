#!/usr/bin/env python3
"""
BrachyBot Benchmark Runner v2
Enhanced with: weighted keywords, equivalent terms, regression tests,
response time tracking, and multi-turn conversations.

IMPORTANT: Agents must read all guidelines before running tests!
"""

import json
import os
import sys
import time
import argparse
import re
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any

BENCHMARK_DIR = Path(__file__).parent
RESULTS_DIR = BENCHMARK_DIR / "results"
SERVER_URL = "http://localhost:8080"
TIMEOUT = 120  # seconds per request
CT_FILE = "/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii"


# ============================================================================
# Project Understanding Verification
# ============================================================================

def verify_project_understanding():
    """
    Verify that the Agent understands project rules.
    Agent must read all guideline files and confirm understanding before starting tests.
    """
    print("\n=== Project Understanding Verification ===\n")

    # Required files to read
    required_files = [
        "README.md",
        "GUIDELINES.md",
        "RESPONSE_VALIDATION_RULES.md",
        "STRICT_TEST_RULES.md",
        "AGENT_INSTRUCTIONS.md"
    ]

    missing_files = []
    for f in required_files:
        if not (BENCHMARK_DIR / f).exists():
            missing_files.append(f)

    if missing_files:
        print("❌ Missing required files:")
        for f in missing_files:
            print(f"  - {f}")
        print("\nPlease create these files first to ensure Agent understands project rules.")
        return False

    print("✅ All required files exist")
    print("\nPlease ensure Agent has read the following files:")
    for f in required_files:
        print(f"  - {f}")

    print("\nKey Rules Summary:")
    print("  1. DO NOT modify .json files (benchmark files)")
    print("  2. ONLY modify Python code files")
    print("  3. MUST run verify_fix.py after each fix")
    print("  4. Goal is to improve BrachyBot, not just pass tests")

    return True


def verify_fix_integrity():
    """Verify fix integrity: ensure no benchmark files were modified"""
    print("\n=== Fix Integrity Verification ===\n")

    result = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        cwd="/home/lht/snap/brachyplan/BrachyBot"
    )

    modified_files = result.stdout.strip().split("\n") if result.stdout.strip() else []

    # Check if any benchmark files were modified
    benchmark_modified = [f for f in modified_files if "benchmarks/" in f and f.endswith(".json")]

    if benchmark_modified:
        print("❌ VIOLATION: The following benchmark files were modified:")
        for f in benchmark_modified:
            print(f"  - {f}")
        print("\nCorrect approach: Fix code, not tests!")
        return False

    # Check if any code files were modified
    code_modified = [f for f in modified_files if f.endswith(".py")]

    if code_modified:
        print("✅ CORRECT: The following Python files were modified:")
        for f in code_modified:
            print(f"  - {f}")
        return True

    print("⚠️  No file modifications detected")
    return True


# ============================================================================
# Data Loading
# ============================================================================

def load_all_categories() -> dict:
    """Load all benchmark JSON files."""
    categories = {}
    for f in sorted(BENCHMARK_DIR.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                if "category" in data and "cases" in data:
                    categories[data["category"]] = data
        except (json.JSONDecodeError, KeyError):
            continue
    return categories


def load_category(name: str) -> Optional[dict]:
    """Load a specific benchmark category by name or filename."""
    path = BENCHMARK_DIR / f"{name}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    for f in BENCHMARK_DIR.glob("*.json"):
        with open(f, "r", encoding="utf-8") as fp:
            data = json.load(fp)
            if data.get("category") == name:
                return data
    return None


# ============================================================================
# API Communication
# ============================================================================

def send_message(text: str, timeout: int = TIMEOUT, session_id: str = None, clear_context: bool = True) -> dict:
    """
    Send a message to BrachyBot via HTTP API and collect response.

    Args:
        text: Message to send
        timeout: Request timeout in seconds
        session_id: Unique session ID for isolation (recommended for benchmarks)
        clear_context: Whether to clear conversation context (used for multi-turn within same session)
    """
    import urllib.request
    start = time.time()

    # Use unique session ID if not provided
    if session_id is None:
        session_id = f"benchmark_{int(time.time() * 1000)}"

    try:
        payload = {
            "message": text,
            "clear_context": clear_context,
            "session_id": session_id
        }
        req = urllib.request.Request(
            f"{SERVER_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
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
            "elapsed": time.time() - start,
            "session_id": session_id
        }
    except Exception as e:
        return {"success": False, "error": str(e), "elapsed": time.time() - start, "session_id": session_id}


def send_multi_turn_messages(turns: List[dict], timeout: int = TIMEOUT, session_id: str = None) -> List[dict]:
    """
    Send multiple messages in sequence (multi-turn conversation).

    All turns share the same session_id to maintain context.
    Only the first turn clears context.
    """
    # Use same session ID for all turns in a multi-turn test
    if session_id is None:
        session_id = f"benchmark_multiturn_{int(time.time() * 1000)}"

    results = []
    for i, turn in enumerate(turns):
        # Only clear context on first turn
        clear_context = (i == 0)
        result = send_message(turn["input"], timeout=timeout, session_id=session_id, clear_context=clear_context)
        results.append({
            "turn": i + 1,
            "input": turn["input"],
            "response": result.get("response", ""),
            "success": result.get("success", False),
            "elapsed": result.get("elapsed", 0),
            "error": result.get("error")
        })
    return results


# ============================================================================
# Keyword Matching (Enhanced)
# ============================================================================

def normalize_keyword(keyword: str) -> str:
    """Normalize keyword for matching."""
    return keyword.lower().strip()


def check_keyword_match(keyword: str, response: str, equivalent_terms: dict = None) -> bool:
    """Check if keyword matches in response, including equivalent terms."""
    keyword_lower = normalize_keyword(keyword)
    response_lower = response.lower()

    # Direct match
    if keyword_lower in response_lower:
        return True

    # Check equivalent terms
    if equivalent_terms and keyword in equivalent_terms:
        for equiv in equivalent_terms[keyword]:
            if normalize_keyword(equiv) in response_lower:
                return True

    return False


def calculate_keyword_score(expected_keywords, response: str, equivalent_terms: dict = None) -> Tuple[float, List[str], List[str]]:
    """
    Calculate keyword match score with support for weighted keywords.
    Returns: (score, matched_keywords, missed_keywords)

    Supports two formats:
    1. Simple list: ["keyword1", "keyword2"]
    2. Weighted dict: {"keyword1": {"weight": 0.5, "required": true}, ...}
    """
    if not expected_keywords:
        return 1.0, [], []

    matched = []
    missed = []

    # Handle simple list format
    if isinstance(expected_keywords, list):
        for kw in expected_keywords:
            if check_keyword_match(kw, response, equivalent_terms):
                matched.append(kw)
            else:
                missed.append(kw)
        score = len(matched) / max(len(expected_keywords), 1)
        return score, matched, missed

    # Handle weighted dict format
    if isinstance(expected_keywords, dict):
        total_weight = 0
        weighted_score = 0

        for kw, config in expected_keywords.items():
            weight = config.get("weight", 1.0 / len(expected_keywords))
            required = config.get("required", False)

            total_weight += weight

            if check_keyword_match(kw, response, equivalent_terms):
                weighted_score += weight
                matched.append(kw)
            else:
                missed.append(kw)
                if required:
                    # Required keyword missed - significant penalty
                    weighted_score -= weight * 0.5

        # Normalize score
        score = max(0, weighted_score / max(total_weight, 0.01))
        return score, matched, missed

    return 0.0, [], []


# ============================================================================
# Response Scoring (Enhanced)
# ============================================================================

def score_response(response: str, case: dict) -> Tuple[float, dict, List[str]]:
    """
    Score a response against benchmark expectations.
    Returns: (total_score, score_breakdown, issues)

    Scoring dimensions:
    - Keyword match: 40% (supports weighted keywords)
    - Completeness: 20% (response length)
    - Safety: 20% (no forbidden keywords)
    - Accuracy: 10% (no hallucination, honesty)
    - UX Quality: 10% (appropriate length, no filler)
    """
    issues = []
    scores = {}

    if not response or len(response) < 20:
        return 0.0, {"keyword": 0, "completeness": 0, "safety": 0, "accuracy": 0, "ux": 0}, ["Empty or too short response"]

    if "Request Failed" in response or "AI error" in response:
        return 0.0, {"keyword": 0, "completeness": 0, "safety": 0, "accuracy": 0, "ux": 0}, ["System error in response"]

    resp_lower = response.lower()

    # Get equivalent terms from case or category
    equivalent_terms = case.get("equivalent_terms", {})

    # 1. Keyword match (40%) - supports weighted keywords
    expected_keywords = case.get("expected_keywords", [])
    keyword_score, matched, missed = calculate_keyword_score(expected_keywords, response, equivalent_terms)

    if keyword_score < 0.3:
        issues.append(f"Low keyword match: {keyword_score:.2f} (matched: {matched}, missed: {missed})")
    scores["keyword"] = keyword_score

    # 2. Completeness (20%)
    completeness_score = min(1.0, len(response) / 300)
    if len(response) < 100:
        issues.append(f"Response too short: {len(response)} chars")
    scores["completeness"] = completeness_score

    # 3. Safety (20%) - forbidden keywords = automatic failure
    forbidden_keywords = case.get("forbidden_keywords", [])
    safety_score = 1.0
    if forbidden_keywords:
        has_forbidden = any(kw.lower() in resp_lower for kw in forbidden_keywords)
        if has_forbidden:
            safety_score = 0.0
            found_forbidden = [kw for kw in forbidden_keywords if kw.lower() in resp_lower]
            issues.append(f"CRITICAL: Contains forbidden keywords: {found_forbidden}")
    scores["safety"] = safety_score

    # 4. Accuracy (10%) - hallucination and honesty detection
    accuracy_score = 1.0

    # Hallucination indicators
    hallucination_indicators = case.get("hallucination_keywords", [
        "i don't have access to", "i cannot verify", "i'm not sure about",
        "this is a hypothetical", "i'm making this up", "fictional", "not a real"
    ])
    for indicator in hallucination_indicators:
        if indicator.lower() in resp_lower:
            accuracy_score -= 0.2
            issues.append(f"Hallucination indicator: '{indicator}'")

    # Honesty indicators (bonus for hard questions)
    honesty_indicators = [
        "i don't have", "i don't know", "i'm not certain", "i cannot provide",
        "data not available", "not available to me", "i'm not sure",
        "this information is not available", "outside my knowledge", "beyond my training"
    ]
    honesty_count = sum(1 for ind in honesty_indicators if ind in resp_lower)

    # Fabrication indicators
    fabrication_indicators = [
        "typically around", "generally about", "in the range of",
        "it is believed that", "some studies suggest", "research indicates"
    ]
    for indicator in fabrication_indicators:
        if indicator.lower() in resp_lower:
            accuracy_score -= 0.1
            issues.append(f"Possible fabrication: '{indicator}'")

    # Bonus for honesty on hard questions
    if honesty_count > 0 and case.get("difficulty") == "hard":
        accuracy_score = min(1.0, accuracy_score + 0.2)
        issues.append(f"Honesty bonus: {honesty_count} indicators")

    accuracy_score = max(0.0, accuracy_score)
    scores["accuracy"] = accuracy_score

    # 5. UX Quality (10%) - appropriate length, no filler
    ux_score = 1.0
    difficulty = case.get("difficulty", "medium")

    if difficulty == "easy":
        if len(response) > 1000:
            ux_score -= 0.5
            issues.append(f"Too verbose for easy question: {len(response)} chars")
        elif len(response) < 30:
            ux_score -= 0.5
            issues.append(f"Too brief: {len(response)} chars")
    elif difficulty == "medium":
        if len(response) > 2000:
            ux_score -= 0.4
            issues.append(f"Too verbose for medium question: {len(response)} chars")
        elif len(response) < 50:
            ux_score -= 0.5
            issues.append(f"Too brief: {len(response)} chars")
    else:  # hard
        if len(response) > 5000:
            ux_score -= 0.3
            issues.append(f"Too verbose: {len(response)} chars")
        elif len(response) < 100:
            ux_score -= 0.5
            issues.append(f"Too brief for hard question: {len(response)} chars")

    # Filler content penalty
    filler_phrases = [
        "great question", "that's an important", "let me know if you have",
        "i hope this helps", "is there anything else", "do you have any other",
        "feel free to ask", "i'd be happy to help"
    ]
    for filler in filler_phrases:
        if filler in resp_lower:
            ux_score -= 0.1
            issues.append(f"Filler content: '{filler}'")

    ux_score = max(0.0, ux_score)
    scores["ux"] = ux_score

    # Calculate total score
    total_score = (
        scores["keyword"] * 0.40 +
        scores["completeness"] * 0.20 +
        scores["safety"] * 0.20 +
        scores["accuracy"] * 0.10 +
        scores["ux"] * 0.10
    )

    # Critical failures
    if safety_score == 0.0:
        total_score = 0.0
        issues.append("FAIL: Safety violation")

    if keyword_score < 0.3:
        issues.append("FAIL: Insufficient keyword match")

    if accuracy_score < 0.5:
        total_score *= 0.5
        issues.append("FAIL: Hallucination detected")

    return total_score, scores, issues


# ============================================================================
# Test Execution
# ============================================================================

def run_single_test(case: dict, category: dict) -> dict:
    """Run a single test case with session isolation."""
    # Generate unique session ID for this test to ensure complete isolation
    test_session_id = f"test_{case['id']}_{int(time.time() * 1000)}"

    result = {
        "id": case["id"],
        "input": case["input"],
        "description": case.get("description", ""),
        "difficulty": case.get("difficulty", "medium"),
        "user_type": case.get("user_type", "experienced"),
        "type": case.get("type", "standard"),
        "status": "error",
        "response": "",
        "score": 0.0,
        "scores": {},
        "issues": [],
        "passed": False,
        "elapsed": 0,
        "session_id": test_session_id,
        "timestamp": datetime.now().isoformat()
    }

    # Send message with unique session ID for complete isolation
    api_result = send_message(case["input"], session_id=test_session_id)
    result["elapsed"] = api_result.get("elapsed", 0)

    # Check response time threshold
    max_time = case.get("max_response_time_ms")
    if max_time and result["elapsed"] * 1000 > max_time:
        result["issues"].append(f"Response time exceeded: {result['elapsed']*1000:.0f}ms > {max_time}ms")

    if not api_result.get("success"):
        result["status"] = "error"
        result["issues"] = [f"API error: {api_result.get('error', 'Unknown')}"]
        return result

    response = api_result.get("response", "")
    result["response"] = response

    # Score the response
    score, scores, issues = score_response(response, case)
    result["score"] = round(score, 3)
    result["scores"] = scores
    result["issues"] = issues

    # Determine pass/fail
    threshold = case.get("pass_threshold", 0.6)
    passed = score >= threshold and scores.get("safety", 0) > 0 and scores.get("keyword", 0) >= 0.3
    result["passed"] = passed
    result["status"] = "pass" if passed else "fail"

    return result


def run_multi_turn_test(case: dict, category: dict) -> dict:
    """Run a multi-turn conversation test with shared session."""
    turns = case.get("turns", [])
    if not turns:
        return run_single_test(case, category)

    # All turns in this test share the same session ID
    multi_turn_session_id = f"multiturn_{case['id']}_{int(time.time() * 1000)}"

    result = {
        "id": case["id"],
        "type": "multi_turn",
        "description": case.get("description", ""),
        "difficulty": case.get("difficulty", "medium"),
        "num_turns": len(turns),
        "turns": [],
        "overall_score": 0.0,
        "overall_passed": False,
        "issues": [],
        "session_id": multi_turn_session_id,
        "timestamp": datetime.now().isoformat()
    }

    # Send multi-turn messages with shared session ID
    turn_results = send_multi_turn_messages(turns, session_id=multi_turn_session_id)
    result["turns"] = turn_results

    # Score each turn
    turn_scores = []
    for i, (turn, turn_result) in enumerate(zip(turns, turn_results)):
        if not turn_result["success"]:
            turn_scores.append(0.0)
            result["issues"].append(f"Turn {i+1}: API error")
            continue

        score, scores, issues = score_response(turn_result["response"], turn)
        turn_scores.append(score)
        result["issues"].extend([f"Turn {i+1}: {issue}" for issue in issues])

    # Calculate overall score (average of turn scores)
    if turn_scores:
        result["overall_score"] = round(sum(turn_scores) / len(turn_scores), 3)
        result["overall_passed"] = result["overall_score"] >= case.get("pass_threshold", 0.6)

    return result


def run_regression_test(case: dict, category: dict) -> dict:
    """Run a regression test case."""
    result = run_single_test(case, category)
    result["type"] = "regression"
    result["related_fix"] = case.get("related_fix", "unknown")

    # Regression tests have stricter thresholds
    if not result["passed"]:
        result["issues"].insert(0, f"REGRESSION: Previously fixed issue may have returned (fix: {result['related_fix']})")

    return result


# ============================================================================
# Category and Suite Execution
# ============================================================================

def run_category(category_name: str, verbose: bool = True) -> list:
    """Run all tests in a category."""
    cat = load_category(category_name)
    if not cat:
        print(f"❌ Category '{category_name}' not found")
        return []

    cases = cat["cases"]
    results = []
    total = len(cases)

    if verbose:
        print(f"\n{'='*60}")
        print(f"📋 Category: {cat.get('description', category_name)} ({total} cases)")
        if cat.get("equivalent_terms"):
            print(f"   Equivalent terms: {len(cat['equivalent_terms'])} entries")
        print(f"{'='*60}")

    for i, case in enumerate(cases):
        if verbose:
            desc = case.get('description', case['input'][:50])
            test_type = case.get('type', 'standard')
            type_label = f" [{test_type}]" if test_type != 'standard' else ""
            print(f"  [{i+1}/{total}] {case['id']}{type_label}: {desc}", end=" ... ")

        # Run appropriate test type
        test_type = case.get("type", "standard")
        if test_type == "multi_turn":
            result = run_multi_turn_test(case, cat)
        elif test_type == "regression":
            result = run_regression_test(case, cat)
        else:
            result = run_single_test(case, cat)

        results.append(result)

        if verbose:
            if test_type == "multi_turn":
                icon = "✅" if result.get("overall_passed") else "❌"
                score = result.get("overall_score", 0)
                print(f"{icon} Score={score:.2f} ({result['num_turns']} turns)")
            else:
                icon = "✅" if result["passed"] else "❌"
                print(f"{icon} Score={result['score']:.2f} ({result['elapsed']:.1f}s)")

            if not result.get("passed", True) and result.get("issues"):
                for issue in result["issues"][:2]:
                    print(f"         ⚠️ {issue}")

    # Summary
    passed = sum(1 for r in results if r.get("passed", r.get("overall_passed", False)))
    failed = total - passed

    if verbose:
        print(f"\n  Results: {passed}✅ {failed}❌")
        print(f"  Pass rate: {passed}/{total} ({100*passed/total:.0f}%)")

    return results


def run_all(verbose: bool = True) -> dict:
    """Run all benchmark categories."""
    all_results = {}
    categories = load_all_categories()
    total_cases = sum(len(c["cases"]) for c in categories.values())

    print(f"\n🚀 BrachyBot Benchmark Suite v2")
    print(f"   Categories: {len(categories)}")
    print(f"   Total cases: {total_cases}")
    print(f"   Server: {SERVER_URL}")
    print(f"{'='*60}")

    start_time = time.time()

    for cat_name in sorted(categories.keys()):
        results = run_category(cat_name, verbose=verbose)
        all_results[cat_name] = results

    elapsed = time.time() - start_time

    # Overall summary
    all_r = [r for rs in all_results.values() for r in rs]
    total = len(all_r)
    passed = sum(1 for r in all_r if r.get("passed", r.get("overall_passed", False)))
    failed = total - passed

    print(f"\n{'='*60}")
    print(f"📊 OVERALL RESULTS")
    print(f"{'='*60}")
    print(f"  Total:    {total}")
    print(f"  Pass:     {passed} ✅ ({100*passed/total:.0f}%)")
    print(f"  Fail:     {failed} ❌ ({100*failed/total:.0f}%)")
    print(f"  Time:     {elapsed:.1f}s")
    print(f"  Avg/Case: {elapsed/total:.1f}s")

    # Category breakdown
    print(f"\n📈 CATEGORY BREAKDOWN:")
    for cat_name, results in sorted(all_results.items()):
        cat_passed = sum(1 for r in results if r.get("passed", r.get("overall_passed", False)))
        cat_total = len(results)
        print(f"  {cat_name}: {cat_passed}/{cat_total} ({100*cat_passed/cat_total:.0f}%)")

    # Regression test summary
    regression_results = [r for r in all_r if r.get("type") == "regression"]
    if regression_results:
        reg_passed = sum(1 for r in regression_results if r.get("passed"))
        reg_total = len(regression_results)
        print(f"\n🔄 REGRESSION TESTS: {reg_passed}/{reg_total} passed")

    # Save results
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = RESULTS_DIR / f"benchmark_{timestamp}.json"
    with open(result_file, "w", encoding="utf-8") as fp:
        json.dump({
            "version": "2.0",
            "timestamp": timestamp,
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed/total, 3) if total > 0 else 0,
            "elapsed_seconds": round(elapsed, 1),
            "categories": {k: {"passed": sum(1 for r in v if r.get("passed", r.get("overall_passed", False))), "total": len(v)} for k, v in all_results.items()},
            "results": all_results
        }, fp, ensure_ascii=False, indent=2)
    print(f"\n  Results saved to: {result_file}")

    return all_results


# ============================================================================
# Statistics
# ============================================================================

def print_stats():
    """Print benchmark statistics."""
    categories = load_all_categories()
    total = 0
    multi_turn = 0
    regression = 0
    weighted = 0

    print(f"\n📊 Benchmark Statistics")
    print(f"{'='*70}")
    print(f"{'Category':<25} {'Description':<30} {'Cases':>6} {'Type':<10}")
    print(f"{'-'*70}")

    for cat_name in sorted(categories.keys()):
        cat = categories[cat_name]
        n = len(cat["cases"])
        print(f"{cat_name:<25} {cat.get('description', '')[:30]:<30} {n:>6}")
        total += n

        for case in cat["cases"]:
            if case.get("type") == "multi_turn":
                multi_turn += 1
            if case.get("type") == "regression":
                regression += 1
            if isinstance(case.get("expected_keywords"), dict):
                weighted += 1

    print(f"{'-'*70}")
    print(f"{'TOTAL':<25} {'':<30} {total:>6}")
    print(f"\n  Multi-turn tests: {multi_turn}")
    print(f"  Regression tests: {regression}")
    print(f"  Weighted keyword tests: {weighted}")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BrachyBot Benchmark Runner v2")
    parser.add_argument("--all", action="store_true", help="Run all categories")
    parser.add_argument("--category", type=str, help="Run a specific category")
    parser.add_argument("--stats", action="store_true", help="Show benchmark statistics")
    parser.add_argument("--verify", action="store_true", help="Verify project understanding")
    parser.add_argument("--check-fix", action="store_true", help="Verify no benchmark files were modified")
    parser.add_argument("--verbose", "-v", action="store_true", default=True)
    args = parser.parse_args()

    if args.stats:
        print_stats()
    elif args.verify:
        # Verify project understanding
        if verify_project_understanding():
            print("\n✅ Project understanding verified, ready to test")
        else:
            print("\n❌ Project understanding verification failed, please read all guidelines first")
            sys.exit(1)
    elif args.check_fix:
        # Verify fix integrity
        if verify_fix_integrity():
            print("\n✅ Fix integrity verified")
        else:
            print("\n❌ Fix integrity verification failed")
            sys.exit(1)
    elif args.all:
        # Verify project understanding first
        if not verify_project_understanding():
            print("\n❌ Please read all guideline files first")
            sys.exit(1)
        run_all(verbose=args.verbose)
    elif args.category:
        # Verify project understanding first
        if not verify_project_understanding():
            print("\n❌ Please read all guideline files first")
            sys.exit(1)
        run_category(args.category, verbose=args.verbose)
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python benchmarks/run_benchmarks.py --stats")
        print("  python benchmarks/run_benchmarks.py --verify")
        print("  python benchmarks/run_benchmarks.py --check-fix")
        print("  python benchmarks/run_benchmarks.py --category greeting")
        print("  python benchmarks/run_benchmarks.py --all")
