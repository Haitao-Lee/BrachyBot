#!/usr/bin/env python3
"""
Continue Agent 4 benchmark from saved results.
Loads existing results, runs remaining categories.
"""
import sys, os, json, time, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unified_agent import run_category, generate_report, SCREENSHOT_DIR, REPORT_DIR

AGENT_ID = 4
ALL_CATEGORIES = [28, 29, 30, 31, 32, 33, 34, 35, 36]
RESULTS_FILE = f"{REPORT_DIR}/agent4_results_28_36.json"

# Load existing results
existing_results = []
completed_cats = set()
if os.path.exists(RESULTS_FILE):
    with open(RESULTS_FILE) as f:
        existing_results = json.load(f)
    completed_cats = {r['category_num'] for r in existing_results}
    print(f"Loaded {len(existing_results)} existing results, completed categories: {sorted(completed_cats)}")
else:
    print("No existing results found, starting fresh")

# Determine remaining categories
remaining = [c for c in ALL_CATEGORIES if c not in completed_cats]
print(f"Remaining categories: {remaining}")

all_results = list(existing_results)

for cat_num in remaining:
    print(f"\n>>> Running category {cat_num}...", flush=True)
    results = run_category(cat_num, AGENT_ID)
    all_results.extend(results)
    cat_passed = sum(1 for r in results if r['passed'])
    print(f"  Category {cat_num} done: {cat_passed}/{len(results)} passed", flush=True)
    # Save incrementally
    with open(RESULTS_FILE, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"  Results saved ({len(all_results)} total)", flush=True)

# Generate report
report_file = generate_report(all_results, AGENT_ID)

total = len(all_results)
passed = sum(1 for r in all_results if r['passed'])
print(f"\n{'='*60}")
print(f"AGENT {AGENT_ID} COMPLETE")
print(f"Total: {total} | Passed: {passed} | Failed: {total - passed}")
print(f"Pass Rate: {passed/total*100:.1f}%" if total > 0 else "No tests")
print(f"Report: {report_file}")
