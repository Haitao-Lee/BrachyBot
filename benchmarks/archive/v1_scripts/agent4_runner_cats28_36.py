#!/usr/bin/env python3
"""
Focused runner for Agent 4, categories 28-36 ONLY.
No auto-help to avoid OOM from large incomplete categories.
Saves results incrementally.
"""
import sys, os, json, time, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unified_agent import run_category, generate_report, SCREENSHOT_DIR, REPORT_DIR

AGENT_ID = 4
CATEGORIES = [28, 29, 30, 31, 32, 33, 34, 35, 36]
RESULTS_FILE = f"{REPORT_DIR}/agent4_results_28_36.json"

all_results = []

for cat_num in CATEGORIES:
    print(f"\n>>> Running category {cat_num}...", flush=True)
    results = run_category(cat_num, AGENT_ID)
    all_results.extend(results)
    cat_passed = sum(1 for r in results if r['passed'])
    print(f"  Category {cat_num} done: {cat_passed}/{len(results)} passed", flush=True)
    # Save incrementally
    with open(RESULTS_FILE, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"  Results saved to {RESULTS_FILE}", flush=True)

# Generate report
report_file = generate_report(all_results, AGENT_ID)

total = len(all_results)
passed = sum(1 for r in all_results if r['passed'])
print(f"\n{'='*60}")
print(f"AGENT {AGENT_ID} COMPLETE")
print(f"Total: {total} | Passed: {passed} | Failed: {total - passed}")
print(f"Pass Rate: {passed/total*100:.1f}%" if total > 0 else "No tests")
print(f"Report: {report_file}")
print(f"Results: {RESULTS_FILE}")
