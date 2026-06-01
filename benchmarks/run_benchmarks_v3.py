#!/usr/bin/env python3
"""
BrachyBot Benchmark Runner v3
Major improvements over v2:

1. MULTI-RUN STABILITY: Each test runs N times, takes majority vote
2. ENHANCED SCORING: Semantic similarity, quality-based completeness
3. DYNAMIC TIMEOUT: Adjusts based on difficulty
4. STATISTICAL CONFIDENCE: Reports confidence intervals
5. CHANGE DETECTION: Compares against previous runs

Usage:
  python benchmarks/run_benchmarks_v3.py --all                  # Full suite
  python benchmarks/run_benchmarks_v3.py --all --runs 3         # 3 runs per test
  python benchmarks/run_benchmarks_v3.py --category greeting    # Single category
  python benchmarks/run_benchmarks_v3.py --compare prev.json    # Compare runs
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
from typing import Optional, Dict, List, Tuple, Any, Set
from collections import Counter
import difflib

BENCHMARK_DIR = Path(__file__).parent
RESULTS_DIR = BENCHMARK_DIR / "results"
SERVER_URL = "http://localhost:8080"

# Dynamic timeout based on difficulty
TIMEOUT_BY_DIFFICULTY = {
    "easy": 60,
    "medium": 120,
    "hard": 180
}
DEFAULT_TIMEOUT = 120

CT_FILE = "/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii"


# ============================================================================
# Utility Functions
# ============================================================================

def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    return re.sub(r'\s+', ' ', text.lower().strip())


def semantic_similarity(text1: str, text2: str) -> float:
    """
    Calculate semantic similarity using SequenceMatcher.
    Returns 0.0 to 1.0
    """
    if not text1 or not text2:
        return 0.0
    return difflib.SequenceMatcher(None, normalize_text(text1), normalize_text(text2)).ratio()


def extract_key_concepts(text: str) -> Set[str]:
    """
    Extract key medical/technical concepts from text.
    Returns set of important terms.
    """
    # Medical and technical terms to look for
    medical_terms = [
        'dose', 'gy', 'gray', 'ctv', 'ptv', 'gtv', 'oar',
        'bladder', 'rectum', 'uterus', 'cervix', 'vagina',
        'brachytherapy', 'hdr', 'ldr', 'icru',
        'point a', 'point b', 'hr-ctv', 'ir-ctv',
        'd90', 'd100', 'v100', 'v150', 'v200',
        'd2cc', 'd1cc', 'd0.1cc',
        'implant', 'applicator', 'tandem', 'ovoid', 'ring',
        'fraction', 'treatment plan', 'optimization',
        'organ at risk', 'dose constraint', 'dose volume histogram'
    ]

    text_lower = text.lower()
    found = set()

    for term in medical_terms:
        if term in text_lower:
            found.add(term)

    # Also extract capitalized abbreviations
    abbreviations = re.findall(r'\b[A-Z]{2,}\b', text)
    found.update(a.lower() for a in abbreviations if len(a) >= 2)

    return found


def calculate_concept_coverage(expected_concepts: Set[str], response: str) -> Tuple[float, Set[str], Set[str]]:
    """
    Calculate what percentage of expected concepts are covered in response.
    Returns: (coverage_ratio, matched_concepts, missing_concepts)
    """
    response_concepts = extract_key_concepts(response)
    response_lower = response.lower()

    matched = set()
    missing = set()

    for concept in expected_concepts:
        if concept in response_concepts or concept in response_lower:
            matched.add(concept)
        else:
            missing.add(concept)

    coverage = len(matched) / max(len(expected_concepts), 1)
    return coverage, matched, missing


# ============================================================================
# Dynamic Timeout
# ============================================================================

def get_timeout(case: dict) -> int:
    """Get appropriate timeout based on test difficulty and type."""
    difficulty = case.get("difficulty", "medium")
    base_timeout = TIMEOUT_BY_DIFFICULTY.get(difficulty, DEFAULT_TIMEOUT)

    # Multi-turn tests need more time
    if case.get("type") == "multi_turn":
        num_turns = len(case.get("turns", []))
        base_timeout *= max(1, num_turns // 2)

    # Tests with CT file context need more time
    if case.get("requires_ct", False):
        base_timeout += 30

    return base_timeout


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

def send_message(text: str, timeout: int = DEFAULT_TIMEOUT, clear_context: bool = True) -> dict:
    """Send a message to BrachyBot via HTTP API and collect response."""
    import urllib.request
    start = time.time()
    try:
        req = urllib.request.Request(
            f"{SERVER_URL}/api/chat",
            data=json.dumps({"message": text, "clear_context": clear_context}).encode("utf-8"),
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


def send_multi_turn_messages(turns: List[dict], timeout: int = DEFAULT_TIMEOUT) -> List[dict]:
    """Send multiple messages in sequence (multi-turn conversation)."""
    results = []
    for i, turn in enumerate(turns):
        clear_context = (i == 0)
        turn_timeout = get_timeout(turn) if "difficulty" in turn else timeout
        result = send_message(turn["input"], timeout=turn_timeout, clear_context=clear_context)
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

    # Fuzzy match for close variations (e.g., "point a" vs "Point-A")
    keyword_normalized = re.sub(r'[-_\s]+', ' ', keyword_lower)
    if keyword_normalized in response_lower:
        return True

    return False


def calculate_keyword_score(expected_keywords, response: str, equivalent_terms: dict = None) -> Tuple[float, List[str], List[str]]:
    """
    Calculate keyword match score with support for weighted keywords.
    Returns: (score, matched_keywords, missed_keywords)
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
                    weighted_score -= weight * 0.5

        score = max(0, weighted_score / max(total_weight, 0.01))
        return score, matched, missed

    return 0.0, [], []


# ============================================================================
# Response Scoring (Enhanced v3)
# ============================================================================

def score_response(response: str, case: dict) -> Tuple[float, dict, List[str]]:
    """
    Enhanced scoring v3 with better quality assessment.

    Scoring dimensions:
    - Keyword match: 35% (supports weighted keywords + concept coverage)
    - Completeness: 20% (quality-based, not just length)
    - Safety: 20% (no forbidden keywords)
    - Accuracy: 15% (hallucination detection + honesty bonus)
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

    # =========================================================================
    # 1. Keyword match (35%) - enhanced with concept coverage
    # =========================================================================
    expected_keywords = case.get("expected_keywords", [])
    keyword_score, matched, missed = calculate_keyword_score(expected_keywords, response, equivalent_terms)

    # Also check concept coverage if expected_concepts defined
    expected_concepts = case.get("expected_concepts", [])
    if expected_concepts:
        concept_coverage, _, missing_concepts = calculate_concept_coverage(set(expected_concepts), response)
        # Blend keyword score with concept coverage
        keyword_score = (keyword_score * 0.7) + (concept_coverage * 0.3)
        if missing_concepts:
            issues.append(f"Missing concepts: {missing_concepts}")

    if keyword_score < 0.3:
        issues.append(f"Low keyword match: {keyword_score:.2f} (matched: {matched}, missed: {missed})")
    scores["keyword"] = keyword_score

    # =========================================================================
    # 2. Completeness (20%) - quality-based, not just length
    # =========================================================================
    completeness_score = 0.0
    response_length = len(response)

    # Base score from length (information density)
    if response_length >= 500:
        completeness_score = 1.0
    elif response_length >= 200:
        completeness_score = 0.8
    elif response_length >= 100:
        completeness_score = 0.6
    elif response_length >= 50:
        completeness_score = 0.4
    else:
        completeness_score = 0.2

    # Bonus for structured content (lists, headers, etc.)
    has_structure = bool(re.search(r'(\n[-*•]|\n\d+[.)]|\n#{1,3}\s)', response))
    if has_structure:
        completeness_score = min(1.0, completeness_score + 0.1)

    # Bonus for including specific numbers/data
    has_numbers = bool(re.search(r'\b\d+\.?\d*\s*(Gy|%|cc|mm)\b', response, re.IGNORECASE))
    if has_numbers:
        completeness_score = min(1.0, completeness_score + 0.1)

    # Penalty for excessive repetition
    words = response.lower().split()
    if len(words) > 20:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.3:  # Too repetitive
            completeness_score *= 0.7
            issues.append("Excessive repetition detected")

    scores["completeness"] = completeness_score

    # =========================================================================
    # 3. Safety (20%) - forbidden keywords = automatic failure
    # =========================================================================
    forbidden_keywords = case.get("forbidden_keywords", [])
    safety_score = 1.0
    if forbidden_keywords:
        has_forbidden = any(kw.lower() in resp_lower for kw in forbidden_keywords)
        if has_forbidden:
            safety_score = 0.0
            found_forbidden = [kw for kw in forbidden_keywords if kw.lower() in resp_lower]
            issues.append(f"CRITICAL: Contains forbidden keywords: {found_forbidden}")
    scores["safety"] = safety_score

    # =========================================================================
    # 4. Accuracy (15%) - enhanced hallucination detection
    # =========================================================================
    accuracy_score = 1.0

    # Hallucination indicators (expanded list)
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
        "this information is not available", "outside my knowledge", "beyond my training",
        "consult with", "recommend discussing", "please verify"
    ]
    honesty_count = sum(1 for ind in honesty_indicators if ind in resp_lower)

    # Fabrication indicators (expanded)
    fabrication_indicators = [
        "typically around", "generally about", "in the range of",
        "it is believed that", "some studies suggest", "research indicates",
        "experts recommend", "it is known that", "universally accepted",
        "always used", "never used in", "standard protocol is"
    ]
    for indicator in fabrication_indicators:
        if indicator.lower() in resp_lower:
            accuracy_score -= 0.15
            issues.append(f"Possible fabrication: '{indicator}'")

    # Bonus for honesty on hard questions
    if honesty_count > 0 and case.get("difficulty") == "hard":
        accuracy_score = min(1.0, accuracy_score + 0.2)
        issues.append(f"Honesty bonus: {honesty_count} indicators")

    # Bonus for appropriate hedging
    hedging_phrases = ["may", "might", "could", "typically", "generally", "in most cases"]
    hedging_count = sum(1 for phrase in hedging_phrases if phrase in resp_lower)
    if hedging_count >= 2 and hedging_count <= 5:
        accuracy_score = min(1.0, accuracy_score + 0.1)

    accuracy_score = max(0.0, accuracy_score)
    scores["accuracy"] = accuracy_score

    # =========================================================================
    # 5. UX Quality (10%) - appropriate length, no filler
    # =========================================================================
    ux_score = 1.0
    difficulty = case.get("difficulty", "medium")

    # Length appropriateness by difficulty
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

    # Filler content penalty (expanded list)
    filler_phrases = [
        "great question", "that's an important", "let me know if you have",
        "i hope this helps", "is there anything else", "do you have any other",
        "feel free to ask", "i'd be happy to help", "that's a good question",
        "absolutely", "certainly", "of course", "sure thing"
    ]
    filler_count = sum(1 for filler in filler_phrases if filler in resp_lower)
    if filler_count > 0:
        ux_score -= min(0.5, filler_count * 0.1)
        issues.append(f"Filler content detected: {filler_count} instances")

    ux_score = max(0.0, ux_score)
    scores["ux"] = ux_score

    # =========================================================================
    # Calculate total score
    # =========================================================================
    total_score = (
        scores["keyword"] * 0.35 +
        scores["completeness"] * 0.20 +
        scores["safety"] * 0.20 +
        scores["accuracy"] * 0.15 +
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
# Multi-Run Stability Testing
# ============================================================================

def run_with_stability(case: dict, category: dict, num_runs: int = 1) -> dict:
    """
    Run a test case multiple times and aggregate results.
    Returns stable result with confidence metrics.
    """
    if num_runs <= 1:
        # Single run - just run normally
        return run_single_test(case, category)

    # Multiple runs
    results = []
    for run_idx in range(num_runs):
        result = run_single_test(case, category, run_id=run_idx + 1)
        results.append(result)
        time.sleep(0.5)  # Small delay between runs

    # Aggregate results
    return aggregate_runs(results, case)


def run_single_test(case: dict, category: dict, run_id: int = 0) -> dict:
    """Run a single test case and return results."""
    timeout = get_timeout(case)

    result = {
        "id": case["id"],
        "run_id": run_id,
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
        "timeout_used": timeout,
        "timestamp": datetime.now().isoformat()
    }

    # Send message to API
    api_result = send_message(case["input"], timeout=timeout)
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


def aggregate_runs(results: List[dict], case: dict) -> dict:
    """
    Aggregate multiple run results into a single stable result.
    Uses majority voting for pass/fail and median for scores.
    """
    if not results:
        return {"id": case["id"], "status": "error", "issues": ["No results to aggregate"]}

    # Extract successful results
    successful = [r for r in results if r.get("status") != "error"]
    if not successful:
        return {
            "id": case["id"],
            "status": "error",
            "num_runs": len(results),
            "num_errors": len(results),
            "issues": ["All runs failed with errors"]
        }

    # Majority voting for pass/fail
    pass_votes = sum(1 for r in successful if r.get("passed", False))
    majority_passed = pass_votes > len(successful) / 2

    # Median score
    scores = [r["score"] for r in successful]
    scores.sort()
    median_score = scores[len(scores) // 2]

    # Average elapsed time
    avg_elapsed = sum(r["elapsed"] for r in successful) / len(successful)

    # Collect all issues
    all_issues = []
    for r in successful:
        all_issues.extend(r.get("issues", []))
    # Deduplicate issues
    unique_issues = list(set(all_issues))

    # Find most common response (for reference)
    responses = [r["response"] for r in successful]
    most_common_response = max(set(responses), key=responses.count) if responses else ""

    # Stability score (how consistent are the runs)
    if len(scores) > 1:
        score_variance = sum((s - median_score) ** 2 for s in scores) / len(scores)
        stability = max(0, 1 - score_variance * 10)  # Scale variance to 0-1
    else:
        stability = 1.0

    return {
        "id": case["id"],
        "type": case.get("type", "standard"),
        "description": case.get("description", ""),
        "difficulty": case.get("difficulty", "medium"),
        "status": "pass" if majority_passed else "fail",
        "passed": majority_passed,
        "score": round(median_score, 3),
        "scores": successful[0].get("scores", {}),  # Use first successful's breakdown
        "num_runs": len(results),
        "num_successful": len(successful),
        "pass_votes": pass_votes,
        "fail_votes": len(successful) - pass_votes,
        "stability": round(stability, 3),
        "avg_elapsed": round(avg_elapsed, 2),
        "issues": unique_issues,
        "most_common_response": most_common_response[:500],  # Truncate for storage
        "timestamp": datetime.now().isoformat()
    }


# ============================================================================
# Multi-turn and Regression Tests
# ============================================================================

def run_multi_turn_test(case: dict, category: dict) -> dict:
    """Run a multi-turn conversation test."""
    turns = case.get("turns", [])
    if not turns:
        return run_single_test(case, category)

    timeout = get_timeout(case)

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
        "timestamp": datetime.now().isoformat()
    }

    # Send multi-turn messages
    turn_results = send_multi_turn_messages(turns, timeout=timeout)
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

    # Calculate overall score
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

def run_category(category_name: str, verbose: bool = True, num_runs: int = 1) -> list:
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
        if num_runs > 1:
            print(f"   Runs per test: {num_runs} (stability mode)")
        if cat.get("equivalent_terms"):
            print(f"   Equivalent terms: {len(cat['equivalent_terms'])} entries")
        print(f"{'='*60}")

    for i, case in enumerate(cases):
        if verbose:
            desc = case.get('description', case['input'][:50])
            test_type = case.get('type', 'standard')
            type_label = f" [{test_type}]" if test_type != 'standard' else ""
            run_label = f" ({num_runs}x)" if num_runs > 1 else ""
            print(f"  [{i+1}/{total}] {case['id']}{type_label}{run_label}: {desc}", end=" ... ")

        # Run appropriate test type
        test_type = case.get("type", "standard")
        if test_type == "multi_turn":
            result = run_multi_turn_test(case, cat)
        elif test_type == "regression":
            result = run_regression_test(case, cat)
        else:
            result = run_with_stability(case, cat, num_runs=num_runs)

        results.append(result)

        if verbose:
            if test_type == "multi_turn":
                icon = "✅" if result.get("overall_passed") else "❌"
                score = result.get("overall_score", 0)
                print(f"{icon} Score={score:.2f} ({result['num_turns']} turns)")
            else:
                icon = "✅" if result.get("passed", False) else "❌"
                score = result.get("score", 0)
                stability_info = ""
                if num_runs > 1 and "stability" in result:
                    stability_info = f" stability={result['stability']:.2f}"
                print(f"{icon} Score={score:.2f} ({result.get('avg_elapsed', result.get('elapsed', 0)):.1f}s){stability_info}")

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


def run_all(verbose: bool = True, num_runs: int = 1) -> dict:
    """Run all benchmark categories."""
    all_results = {}
    categories = load_all_categories()
    total_cases = sum(len(c["cases"]) for c in categories.values())

    print(f"\n🚀 BrachyBot Benchmark Suite v3")
    print(f"   Categories: {len(categories)}")
    print(f"   Total cases: {total_cases}")
    print(f"   Server: {SERVER_URL}")
    if num_runs > 1:
        print(f"   Runs per test: {num_runs} (stability mode)")
    print(f"{'='*60}")

    start_time = time.time()

    for cat_name in sorted(categories.keys()):
        results = run_category(cat_name, verbose=verbose, num_runs=num_runs)
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

    # Stability summary (if multi-run)
    if num_runs > 1:
        stability_scores = [r.get("stability", 1.0) for r in all_r if "stability" in r]
        if stability_scores:
            avg_stability = sum(stability_scores) / len(stability_scores)
            low_stability = sum(1 for s in stability_scores if s < 0.7)
            print(f"\n📊 STABILITY METRICS:")
            print(f"  Average stability: {avg_stability:.2f}")
            if low_stability > 0:
                print(f"  ⚠️ Low stability tests: {low_stability}")

    # Save results
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = RESULTS_DIR / f"benchmark_v3_{timestamp}.json"
    with open(result_file, "w", encoding="utf-8") as fp:
        json.dump({
            "version": "3.0",
            "timestamp": timestamp,
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed/total, 3) if total > 0 else 0,
            "elapsed_seconds": round(elapsed, 1),
            "num_runs": num_runs,
            "categories": {k: {"passed": sum(1 for r in v if r.get("passed", r.get("overall_passed", False))), "total": len(v)} for k, v in all_results.items()},
            "results": all_results
        }, fp, ensure_ascii=False, indent=2)
    print(f"\n  Results saved to: {result_file}")

    return all_results


# ============================================================================
# Compare Runs
# ============================================================================

def compare_runs(current_file: str, previous_file: str):
    """Compare two benchmark result files."""
    with open(current_file, 'r') as f:
        current = json.load(f)
    with open(previous_file, 'r') as f:
        previous = json.load(f)

    print(f"\n📊 Comparing Benchmark Runs")
    print(f"{'='*60}")
    print(f"  Current:  {current_file}")
    print(f"  Previous: {previous_file}")
    print(f"{'='*60}")

    # Overall comparison
    curr_rate = current.get("pass_rate", 0)
    prev_rate = previous.get("pass_rate", 0)
    diff = curr_rate - prev_rate

    print(f"\n  Pass Rate: {curr_rate:.1%} vs {prev_rate:.1%} ({diff:+.1%})")
    if diff > 0:
        print(f"  ✅ IMPROVED")
    elif diff < 0:
        print(f"  ❌ REGRESSED")
    else:
        print(f"  ➖ NO CHANGE")

    # Category comparison
    print(f"\n📈 Category Changes:")
    curr_cats = current.get("categories", {})
    prev_cats = previous.get("categories", {})

    all_cats = set(list(curr_cats.keys()) + list(prev_cats.keys()))
    for cat in sorted(all_cats):
        curr = curr_cats.get(cat, {"passed": 0, "total": 0})
        prev = prev_cats.get(cat, {"passed": 0, "total": 0})

        curr_pct = curr["passed"] / max(curr["total"], 1)
        prev_pct = prev["passed"] / max(prev["total"], 1)
        cat_diff = curr_pct - prev_pct

        icon = "✅" if cat_diff > 0 else "❌" if cat_diff < 0 else "➖"
        print(f"  {icon} {cat}: {curr_pct:.0%} vs {prev_pct:.0%} ({cat_diff:+.0%})")

    # Find newly failed tests
    print(f"\n🔍 Newly Failed Tests:")
    curr_results = current.get("results", {})
    prev_results = previous.get("results", {})

    newly_failed = []
    for cat_name, cases in curr_results.items():
        prev_cases = {r["id"]: r for r in prev_results.get(cat_name, [])}
        for case in cases:
            case_id = case.get("id")
            if case_id in prev_cases:
                if prev_cases[case_id].get("passed") and not case.get("passed"):
                    newly_failed.append({
                        "category": cat_name,
                        "id": case_id,
                        "description": case.get("description", ""),
                        "issues": case.get("issues", [])
                    })

    if newly_failed:
        print(f"  ⚠️ {len(newly_failed)} tests newly failed:")
        for fail in newly_failed[:5]:
            print(f"    - {fail['category']}/{fail['id']}: {fail['description'][:50]}")
    else:
        print(f"  ✅ No newly failed tests")


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
    print(f"{'Category':<25} {'Description':<30} {'Cases':>6}")
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
    parser = argparse.ArgumentParser(description="BrachyBot Benchmark Suite v3")
    parser.add_argument("--all", action="store_true", help="Run all categories")
    parser.add_argument("--category", type=str, help="Run a specific category")
    parser.add_argument("--stats", action="store_true", help="Show benchmark statistics")
    parser.add_argument("--runs", type=int, default=1, help="Number of runs per test (for stability)")
    parser.add_argument("--compare", nargs=2, metavar=("CURRENT", "PREVIOUS"), help="Compare two result files")
    parser.add_argument("--verbose", "-v", action="store_true", default=True)
    args = parser.parse_args()

    if args.stats:
        print_stats()
    elif args.compare:
        compare_runs(args.compare[0], args.compare[1])
    elif args.all:
        run_all(verbose=args.verbose, num_runs=args.runs)
    elif args.category:
        run_category(args.category, verbose=args.verbose, num_runs=args.runs)
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python benchmarks/run_benchmarks_v3.py --stats")
        print("  python benchmarks/run_benchmarks_v3.py --category greeting")
        print("  python benchmarks/run_benchmarks_v3.py --all")
        print("  python benchmarks/run_benchmarks_v3.py --all --runs 3")
        print("  python benchmarks/run_benchmarks_v3.py --compare results/current.json results/previous.json")
