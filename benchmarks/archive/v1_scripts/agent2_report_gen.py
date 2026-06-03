#!/usr/bin/env python3
"""Generate the Agent 2 report from per-category result files."""
import json, os, glob
from datetime import datetime

RESULTS_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result"
REPORT_DIR = f"{RESULTS_DIR}/reports"
SCREENSHOT_DIR = f"{RESULTS_DIR}/screenshots"

os.makedirs(REPORT_DIR, exist_ok=True)

def generate_report(agent_id=2):
    """Collect all category results and generate a unified report."""
    all_results = []
    for f in sorted(glob.glob(f"{RESULTS_DIR}/cat*_results.json")):
        with open(f, 'r') as fh:
            cat_results = json.load(fh)
            all_results.extend(cat_results)

    if not all_results:
        print("No results found!")
        return

    total_tests = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    failed = total_tests - passed
    pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0

    categories = {}
    for r in all_results:
        cat = r.get('category', 'unknown')
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    root_causes = {}
    for r in all_results:
        if r.get('root_cause'):
            rc = r['root_cause']
            root_causes[rc] = root_causes.get(rc, 0) + 1

    avg_score = sum(r['total_score'] for r in all_results) / total_tests if total_tests > 0 else 0

    report_file = f"{REPORT_DIR}/agent{agent_id}_report.md"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"# Agent {agent_id} Benchmark Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Agent:** {agent_id}\n\n")
        f.write("## Executive Summary\n\n")
        f.write("| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Total Tests | {total_tests} |\n")
        f.write(f"| Passed | {passed} |\n")
        f.write(f"| Failed | {failed} |\n")
        f.write(f"| Pass Rate | {pass_rate:.1f}% |\n")
        f.write(f"| Avg Score | {avg_score:.3f} |\n\n")

        f.write("### Category Breakdown\n\n")
        f.write("| Category | Cases | Passed | Failed | Pass Rate | Avg Score |\n")
        f.write("|----------|-------|--------|--------|-----------|----------|\n")
        for cat_name, cat_results in sorted(categories.items()):
            cat_passed = sum(1 for r in cat_results if r['passed'])
            cat_failed = len(cat_results) - cat_passed
            cat_rate = (cat_passed / len(cat_results) * 100) if cat_results else 0
            cat_avg = sum(r['total_score'] for r in cat_results) / len(cat_results) if cat_results else 0
            f.write(f"| {cat_name} | {len(cat_results)} | {cat_passed} | {cat_failed} | {cat_rate:.0f}% | {cat_avg:.3f} |\n")
        f.write("\n")

        if root_causes:
            f.write("### Failure Root Causes\n\n")
            f.write("| Root Cause | Count | % of Failures | Severity | Description |\n")
            f.write("|------------|-------|---------------|----------|-------------|\n")
            for rc, count in sorted(root_causes.items(), key=lambda x: -x[1]):
                pct = (count / failed * 100) if failed > 0 else 0
                severity = "P0" if rc in ['hallucination', 'safety_leak'] else "P2"
                f.write(f"| {rc} | {count} | {pct:.1f}% | {severity} | {rc} |\n")
            f.write("\n")

        f.write("## Detailed Results\n\n")
        for cat_name, cat_results in sorted(categories.items()):
            cat_passed = sum(1 for r in cat_results if r['passed'])
            cat_total = len(cat_results)
            cat_rate = (cat_passed / cat_total * 100) if cat_total > 0 else 0
            f.write(f"### {cat_name} ({cat_passed}/{cat_total} passed, {cat_rate:.0f}%)\n\n")
            for r in cat_results:
                status = "PASS" if r['passed'] else "FAIL"
                f.write(f"#### {status} {r['case_id']}\n\n")
                f.write(f"**Input:** {r['input']}\n\n")
                resp_text = r['response'][:500]
                if len(r['response']) > 500:
                    resp_text += '...'
                f.write(f"**Response:**\n> {resp_text}\n\n")
                f.write(f"**Scores:**\n")
                f.write(f"- Total: {r['total_score']:.2f}\n")
                ds = r['dimension_scores']
                f.write(f"- Keyword: {ds['keyword']:.2f}\n")
                f.write(f"- Completeness: {ds['completeness']:.2f}\n")
                f.write(f"- Safety: {ds['safety']:.2f}\n")
                f.write(f"- Accuracy: {ds['accuracy']:.2f}\n")
                f.write(f"- UX: {ds['ux']:.2f}\n\n")
                if r.get('root_cause'):
                    f.write(f"**Root Cause:** {r['root_cause']}\n\n")
                    f.write(f"**Detail:** {r['root_cause_detail']}\n\n")
                # Check for screenshot
                screenshot = f"{SCREENSHOT_DIR}/{r['category_num']:02d}_{r['case_id']}.png"
                if os.path.exists(screenshot):
                    rel_path = os.path.relpath(screenshot, REPORT_DIR)
                    f.write(f"**Screenshot:**\n![{r['case_id']}]({rel_path})\n\n")
                f.write("---\n\n")

    print(f"Report generated: {report_file}")
    print(f"Total: {total_tests} | Passed: {passed} | Failed: {failed} | Rate: {pass_rate:.1f}%")
    return report_file

if __name__ == "__main__":
    agent_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    generate_report(agent_id)
