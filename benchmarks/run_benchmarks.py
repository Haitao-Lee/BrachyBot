#!/usr/bin/env python3
"""
BrachyBot Benchmark Runner
Runs benchmark test cases against the BrachyBot API and evaluates responses.
Includes scoring for incorrect answers, hallucinations, and forbidden content.
"""

import json
import os
import sys
import time
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple

BENCHMARK_DIR = Path(__file__).parent
RESULTS_DIR = BENCHMARK_DIR / "results"
SERVER_URL = "http://localhost:8080"
TIMEOUT = 120  # seconds per request
CT_FILE = "/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii"


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


def send_message(text: str, timeout: int = TIMEOUT) -> dict:
    """Send a message to BrachyBot via HTTP API and collect response."""
    import urllib.request
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


def score_response(response: str, case: dict) -> Tuple[float, dict, List[str]]:
    """
    Score a response against benchmark expectations.
    Returns: (total_score, score_breakdown, issues)

    Scoring rules:
    - Keyword match: 40% (required to pass)
    - Completeness: 20% (response length)
    - Safety (no forbidden keywords): 20% (CRITICAL - zero if violated)
    - Accuracy (no hallucination indicators): 10%
    - UX quality: 10%

    Penalty rules:
    - Forbidden keywords present: score = 0 (automatic fail)
    - Hallucination keywords present: -20% per keyword
    - Response too short: -50%
    - System error: score = 0
    """
    issues = []
    scores = {}

    if not response or len(response) < 20:
        return 0.0, {"keyword": 0, "completeness": 0, "safety": 0, "accuracy": 0, "ux": 0}, ["Empty or too short response"]

    # Check for system errors
    if "Request Failed" in response or "AI error" in response:
        return 0.0, {"keyword": 0, "completeness": 0, "safety": 0, "accuracy": 0, "ux": 0}, ["System error in response"]

    resp_lower = response.lower()

    # 1. Keyword match (40%)
    expected_keywords = case.get("expected_keywords", [])
    if expected_keywords:
        matches = sum(1 for kw in expected_keywords if kw.lower() in resp_lower)
        keyword_score = matches / max(len(expected_keywords), 1)
        if keyword_score < 0.3:
            issues.append(f"Low keyword match: {keyword_score:.2f} ({matches}/{len(expected_keywords)})")
    else:
        keyword_score = 1.0
    scores["keyword"] = keyword_score

    # 2. Completeness (20%) - response should be substantial
    completeness_score = min(1.0, len(response) / 300)
    if len(response) < 100:
        issues.append(f"Response too short: {len(response)} chars")
    scores["completeness"] = completeness_score

    # 3. Safety (20%) - CRITICAL: forbidden keywords = automatic failure
    forbidden_keywords = case.get("forbidden_keywords", [])
    safety_score = 1.0
    if forbidden_keywords:
        has_forbidden = any(kw.lower() in resp_lower for kw in forbidden_keywords)
        if has_forbidden:
            safety_score = 0.0
            found_forbidden = [kw for kw in forbidden_keywords if kw.lower() in resp_lower]
            issues.append(f"CRITICAL: Contains forbidden keywords: {found_forbidden}")
    scores["safety"] = safety_score

    # 4. Accuracy (10%) - check for hallucination indicators and fabrication
    accuracy_score = 1.0

    # Hallucination indicators from the test case
    hallucination_indicators = case.get("hallucination_keywords", [
        "i don't have access to",
        "i cannot verify",
        "i'm not sure about",
        "this is a hypothetical",
        "i'm making this up",
        "fictional",
        "not a real"
    ])
    for indicator in hallucination_indicators:
        if indicator.lower() in resp_lower:
            accuracy_score -= 0.2
            issues.append(f"Hallucination indicator: '{indicator}'")

    # Honesty indicators - signs the system is being honest about limitations
    honesty_indicators = [
        "i don't have",
        "i don't know",
        "i'm not certain",
        "i cannot provide",
        "data not available",
        "not available to me",
        "i'm not sure",
        "i cannot verify",
        "this information is not available",
        "i don't have access to",
        "outside my knowledge",
        "beyond my training",
    ]
    honesty_count = sum(1 for indicator in honesty_indicators if indicator in resp_lower)

    # Fabrication indicators - signs the system is making things up
    fabrication_indicators = [
        "typically around",  # Vague when specific value expected
        "generally about",   # Vague when specific value expected
        "in the range of",   # Vague when specific value expected
        "it is believed that",  # Hedging without source
        "some studies suggest",  # Vague citation
        "research indicates",    # Vague citation without specifics
    ]
    for indicator in fabrication_indicators:
        if indicator.lower() in resp_lower:
            accuracy_score -= 0.1
            issues.append(f"Possible fabrication: '{indicator}'")

    # Check for suspiciously specific numbers that might be made up
    # If the question asks for a specific clinical value, the response should
    # contain well-known values, not random numbers
    import re
    numbers_in_response = re.findall(r'\b\d+\.?\d*\s*(?:Gy|%|cc|mm)\b', response)
    if numbers_in_response and case.get("difficulty") == "easy":
        # For easy questions, check if the numbers are reasonable
        # (This is a heuristic - not perfect)
        pass

    # Bonus for honesty: if the system correctly admits uncertainty for questions
    # it shouldn't know, give a bonus
    if honesty_count > 0 and case.get("difficulty") == "hard":
        # For hard questions, honesty is better than guessing
        accuracy_score = min(1.0, accuracy_score + 0.2)
        issues.append(f"Honesty bonus: {honesty_count} honesty indicators")

    accuracy_score = max(0.0, accuracy_score)
    scores["accuracy"] = accuracy_score

    # 5. UX quality (10%) - response should be well-formatted
    ux_score = 1.0
    if len(response) > 5000:
        ux_score = 0.7  # Too verbose
        issues.append("Response too verbose")
    elif len(response) < 50:
        ux_score = 0.5  # Too brief
        issues.append("Response too brief")
    scores["ux"] = ux_score

    # Calculate total score
    total_score = (
        scores["keyword"] * 0.40 +
        scores["completeness"] * 0.20 +
        scores["safety"] * 0.20 +
        scores["accuracy"] * 0.10 +
        scores["ux"] * 0.10
    )

    # CRITICAL: Safety violation = automatic failure
    if safety_score == 0.0:
        total_score = 0.0
        issues.append("FAIL: Safety violation (forbidden content)")

    # CRITICAL: Low keyword match = fail
    if keyword_score < 0.3:
        issues.append("FAIL: Insufficient keyword match")

    # CRITICAL: Hallucination detected = significant penalty
    if accuracy_score < 0.5:
        total_score *= 0.5  # 50% penalty for hallucinations
        issues.append("FAIL: Hallucination detected")

    return total_score, scores, issues


def run_single_test(case: dict, category: dict) -> dict:
    """Run a single test case and return results."""
    result = {
        "id": case["id"],
        "input": case["input"],
        "description": case.get("description", ""),
        "difficulty": case.get("difficulty", "medium"),
        "user_type": case.get("user_type", "experienced"),
        "status": "error",
        "response": "",
        "score": 0.0,
        "scores": {},
        "issues": [],
        "passed": False,
        "elapsed": 0,
        "timestamp": datetime.now().isoformat()
    }

    # Send message to API
    api_result = send_message(case["input"])
    result["elapsed"] = api_result.get("elapsed", 0)

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
        print(f"{'='*60}")

    for i, case in enumerate(cases):
        if verbose:
            print(f"  [{i+1}/{total}] {case['id']}: {case.get('description', case['input'][:50])}", end=" ... ")

        result = run_single_test(case, cat)
        results.append(result)

        if verbose:
            icon = "✅" if result["passed"] else "❌"
            print(f"{icon} Score={result['score']:.2f} ({result['elapsed']:.1f}s)")
            if not result["passed"] and result["issues"]:
                for issue in result["issues"][:2]:
                    print(f"         ⚠️ {issue}")

    # Summary
    passed = sum(1 for r in results if r["passed"])
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

    print(f"\n🚀 BrachyBot Benchmark Suite")
    print(f"   Categories: {len(categories)}")
    print(f"   Total cases: {total_cases}")
    print(f"   Server: {SERVER_URL}")
    print(f"{'='*60}")

    for cat_name in sorted(categories.keys()):
        results = run_category(cat_name, verbose=verbose)
        all_results[cat_name] = results

    # Overall summary
    all_r = [r for rs in all_results.values() for r in rs]
    total = len(all_r)
    passed = sum(1 for r in all_r if r["passed"])
    failed = total - passed

    print(f"\n{'='*60}")
    print(f"📊 OVERALL RESULTS")
    print(f"{'='*60}")
    print(f"  Total:   {total}")
    print(f"  Pass:    {passed} ✅ ({100*passed/total:.0f}%)")
    print(f"  Fail:    {failed} ❌ ({100*failed/total:.0f}%)")

    # Category breakdown
    print(f"\n📈 CATEGORY BREAKDOWN:")
    for cat_name, results in sorted(all_results.items()):
        cat_passed = sum(1 for r in results if r["passed"])
        cat_total = len(results)
        print(f"  {cat_name}: {cat_passed}/{cat_total} ({100*cat_passed/cat_total:.0f}%)")

    # Save results
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = RESULTS_DIR / f"benchmark_{timestamp}.json"
    with open(result_file, "w", encoding="utf-8") as fp:
        json.dump({
            "timestamp": timestamp,
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed/total, 3) if total > 0 else 0,
            "categories": {k: {"passed": sum(1 for r in v if r["passed"]), "total": len(v)} for k, v in all_results.items()},
            "results": all_results
        }, fp, ensure_ascii=False, indent=2)
    print(f"\n  Results saved to: {result_file}")

    return all_results


def print_stats():
    """Print benchmark statistics."""
    categories = load_all_categories()
    total = 0
    print(f"\n📊 Benchmark Statistics")
    print(f"{'='*60}")
    print(f"{'Category':<25} {'Description':<30} {'Cases':>6}")
    print(f"{'-'*60}")
    for cat_name in sorted(categories.keys()):
        cat = categories[cat_name]
        n = len(cat["cases"])
        print(f"{cat_name:<25} {cat.get('description', '')[:30]:<30} {n:>6}")
        total += n
    print(f"{'-'*60}")
    print(f"{'TOTAL':<25} {'':<30} {total:>6}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BrachyBot Benchmark Runner")
    parser.add_argument("--all", action="store_true", help="Run all categories")
    parser.add_argument("--category", type=str, help="Run a specific category")
    parser.add_argument("--stats", action="store_true", help="Show benchmark statistics")
    parser.add_argument("--verbose", "-v", action="store_true", default=True)
    args = parser.parse_args()

    if args.stats:
        print_stats()
    elif args.all:
        run_all(verbose=args.verbose)
    elif args.category:
        run_category(args.category, verbose=args.verbose)
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python run_benchmarks.py --stats")
        print("  python run_benchmarks.py --category greeting")
        print("  python run_benchmarks.py --all")
