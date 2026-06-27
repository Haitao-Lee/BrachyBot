#!/usr/bin/env python3
"""
Generate final benchmark report from all agent reports.
"""
import os, glob, re
from datetime import datetime

_ROOT = str(Path(__file__).resolve().parent.parent)
REPORT_DIR = os.path.join(_ROOT, "docs", "benchmark_result", "reports_v2")
FINAL_REPORT = os.path.join(REPORT_DIR, "final_report.md")

def parse_agent_report(report_path):
    """Parse an agent report and extract key metrics."""
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()

    metrics = {
        'agent_id': None,
        'total_tests': 0,
        'passed': 0,
        'failed': 0,
        'pass_rate': 0.0,
        'avg_score': 0.0,
        'categories': [],
        'root_causes': {}
    }

    # Extract agent ID from filename or content
    filename = os.path.basename(report_path)
    match = re.search(r'agent(\d+)_', filename)
    if match:
        metrics['agent_id'] = int(match.group(1))

    # Extract total tests
    match = re.search(r'\|\s*Total Tests\s*\|\s*(\d+)\s*\|', content)
    if match:
        metrics['total_tests'] = int(match.group(1))

    # Extract passed
    match = re.search(r'\|\s*Passed\s*\|\s*(\d+)\s*\|', content)
    if match:
        metrics['passed'] = int(match.group(1))

    # Extract failed
    match = re.search(r'\|\s*Failed\s*\|\s*(\d+)\s*\|', content)
    if match:
        metrics['failed'] = int(match.group(1))

    # Extract pass rate
    match = re.search(r'\|\s*Pass Rate\s*\|\s*([\d.]+)%\s*\|', content)
    if match:
        metrics['pass_rate'] = float(match.group(1))

    # Extract avg score
    match = re.search(r'\|\s*Avg Score\s*\|\s*([\d.]+)\s*\|', content)
    if match:
        metrics['avg_score'] = float(match.group(1))

    # Extract root causes
    root_cause_section = re.search(r'### Failure Root Causes\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if root_cause_section:
        for line in root_cause_section.group(1).split('\n'):
            if '|' in line and 'Root Cause' not in line and '---' not in line:
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) >= 2:
                    cause = parts[0]
                    count = int(parts[1])
                    metrics['root_causes'][cause] = count

    return metrics

def generate_final_report():
    """Generate final report from all agent reports."""
    report_files = glob.glob(f"{REPORT_DIR}/agent*_*.md")

    if not report_files:
        print("No agent reports found!")
        return

    all_metrics = []
    for report_file in sorted(report_files):
        metrics = parse_agent_report(report_file)
        if metrics['agent_id']:
            all_metrics.append(metrics)

    # Calculate totals
    total_tests = sum(m['total_tests'] for m in all_metrics)
    total_passed = sum(m['passed'] for m in all_metrics)
    total_failed = sum(m['failed'] for m in all_metrics)
    overall_pass_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
    overall_avg_score = sum(m['avg_score'] * m['total_tests'] for m in all_metrics) / total_tests if total_tests > 0 else 0

    # Merge root causes
    all_root_causes = {}
    for m in all_metrics:
        for cause, count in m['root_causes'].items():
            all_root_causes[cause] = all_root_causes.get(cause, 0) + count

    # Generate final report
    with open(FINAL_REPORT, 'w', encoding='utf-8') as f:
        f.write("# BrachyBot Benchmark Final Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Total Test Cases:** {total_tests}\n")
        f.write(f"**Agents Used:** {len(all_metrics)}\n\n")

        f.write("---\n\n")
        f.write("## Executive Summary\n\n")
        f.write("| Metric | Value |\n")
        f.write("|--------|-------|\n")
        f.write(f"| Total Tests | {total_tests} |\n")
        f.write(f"| Passed | {total_passed} |\n")
        f.write(f"| Failed | {total_failed} |\n")
        f.write(f"| Overall Pass Rate | {overall_pass_rate:.1f}% |\n")
        f.write(f"| Overall Avg Score | {overall_avg_score:.3f} |\n\n")

        f.write("### Agent Performance Summary\n\n")
        f.write("| Agent | Tests | Passed | Failed | Pass Rate | Avg Score |\n")
        f.write("|-------|-------|--------|--------|-----------|----------|\n")
        for m in sorted(all_metrics, key=lambda x: x['agent_id']):
            f.write(f"| Agent {m['agent_id']} | {m['total_tests']} | {m['passed']} | {m['failed']} | {m['pass_rate']:.1f}% | {m['avg_score']:.3f} |\n")
        f.write("\n")

        if all_root_causes:
            f.write("### Failure Root Causes (All Agents)\n\n")
            f.write("| Root Cause | Count | % of Failures | Severity |\n")
            f.write("|------------|-------|---------------|----------|\n")
            total_failures = sum(all_root_causes.values())
            for cause, count in sorted(all_root_causes.items(), key=lambda x: -x[1]):
                pct = count / total_failures * 100 if total_failures > 0 else 0
                severity = "P0" if cause == "safety_leak" else "P1" if cause == "hallucination" else "P2"
                f.write(f"| {cause} | {count} | {pct:.1f}% | {severity} |\n")
            f.write("\n")

        f.write("---\n\n")
        f.write("## Key Findings\n\n")
        f.write("### v2 Benchmark Categories (8 categories, 60 cases)\n\n")
        f.write("1. **tool_calling** (15 cases) — correct tool selection\n")
        f.write("2. **multi_step** (5 cases) — all steps in order\n")
        f.write("3. **hallucination** (11 cases) — no fabrication\n")
        f.write("4. **language** (6 cases) — language consistency\n")
        f.write("5. **context** (7 cases) — multi-turn context\n")
        f.write("6. **response_quality** (5 cases) — structured output\n")
        f.write("7. **safety** (5 cases) — refuse unsafe requests\n")
        f.write("8. **error_recovery** (10 cases) — graceful error handling\n\n")

        f.write("### Key Test Material\n\n")
        f.write("- **CT File:** `/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii`\n")
        f.write("- **Patient:** Pancreatic cancer\n")
        f.write("- **Specs:** 48 × 512 × 512 voxels, 0.68 × 0.68 × 5.0 mm spacing\n\n")

        f.write("---\n\n")
        f.write("## Data Sources\n\n")
        for m in sorted(all_metrics, key=lambda x: x['agent_id']):
            f.write(f"- **Agent {m['agent_id']} Report:** `{REPORT_DIR}/agent{m['agent_id']}_*.md`\n")
        f.write("\n")

    print(f"✅ Final report generated: {FINAL_REPORT}")

if __name__ == '__main__':
    generate_final_report()
