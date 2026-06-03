#!/usr/bin/env python3
import json, glob, os
from datetime import datetime

SCREENSHOT_DIR = '/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots'
REPORT_DIR = '/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports'
BENCHMARK_DIR = '/home/lht/snap/brachyplan/BrachyBot/benchmarks'

results_file = os.path.join(REPORT_DIR, 'agent2_cat15_18_results.json')
with open(results_file, 'r') as f:
    new_results = json.load(f)

report_file = os.path.join(REPORT_DIR, 'agent2_cat10_18_final.md')

cats = {
    10: 'adversarial', 11: 'hallucination', 12: 'medical_reasoning',
    13: 'multilingual', 14: 'stress', 15: 'recovery',
    16: 'clarification', 17: 'safety', 18: 'image_input'
}

with open(report_file, 'w', encoding='utf-8') as out:
    out.write('# Agent 2 Benchmark Report - Categories 10-18 (FINAL)\n\n')
    out.write('**Generated:** {}\n'.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    out.write('**Agent:** 2\n\n')

    out.write('## Coverage Summary\n\n')
    out.write('| Category | Name | Expected | Screenshots | Coverage |\n')
    out.write('|----------|------|----------|-------------|----------|\n')

    total_expected = 0
    total_screenshots = 0

    for cat_num in range(10, 19):
        files = glob.glob('{}/{:02d}_*.json'.format(BENCHMARK_DIR, cat_num))
        if not files:
            continue
        with open(files[0], 'r') as f:
            data = json.load(f)
        if isinstance(data, dict) and 'cases' in data:
            expected = len(data['cases'])
        elif isinstance(data, list):
            expected = len(data)
        else:
            expected = 0

        screenshots = glob.glob('{}/{:02d}_*.png'.format(SCREENSHOT_DIR, cat_num))
        count = len(screenshots)
        total_expected += expected
        total_screenshots += count

        pct = '{:.0f}%'.format(count / expected * 100) if expected > 0 else 'N/A'
        status = 'COMPLETE' if count >= expected else 'INCOMPLETE'
        out.write('| {:02d} | {} | {} | {} | {} {} |\n'.format(
            cat_num, cats.get(cat_num, 'unknown'), expected, count, pct, status))

    if total_expected > 0:
        out.write('| **TOTAL** | | **{}** | **{}** | **{:.0f}% COMPLETE** |\n\n'.format(
            total_expected, total_screenshots, total_screenshots / total_expected * 100))

    out.write('## Latest Run Results (Agent 2 - Categories 15 & 18)\n\n')
    total = len(new_results)
    passed = sum(1 for r in new_results if r['passed'])
    failed = total - passed

    out.write('Total tests run: {}\n'.format(total))
    out.write('Passed: {}\n'.format(passed))
    out.write('Failed: {}\n'.format(failed))
    if total > 0:
        out.write('Pass Rate: {:.1f}%\n'.format(passed / total * 100))
        avg_time = sum(r['response_time'] for r in new_results) / total
        out.write('Avg Response Time: {:.1f}s\n\n'.format(avg_time))

    cat15 = [r for r in new_results if r['category_num'] == 15]
    if cat15:
        c15_pass = sum(1 for r in cat15 if r['passed'])
        out.write('### Category 15 (Recovery): {}/{} passed\n\n'.format(c15_pass, len(cat15)))
        for r in cat15:
            status = 'PASS' if r['passed'] else 'FAIL'
            out.write('- {}: {} (score: {:.2f})'.format(r['case_id'], status, r['total_score']))
            if r.get('root_cause'):
                out.write(' -- {}: {}'.format(r['root_cause'], r['root_cause_detail']))
            out.write('\n')
        out.write('\n')

    cat18 = [r for r in new_results if r['category_num'] == 18]
    if cat18:
        c18_pass = sum(1 for r in cat18 if r['passed'])
        out.write('### Category 18 (Image Input): {}/{} passed\n\n'.format(c18_pass, len(cat18)))
        for r in cat18:
            status = 'PASS' if r['passed'] else 'FAIL'
            out.write('- {}: {} (score: {:.2f})'.format(r['case_id'], status, r['total_score']))
            if r.get('root_cause'):
                out.write(' -- {}: {}'.format(r['root_cause'], r['root_cause_detail']))
            out.write('\n')
        out.write('\n')

    out.write('## Failure Root Cause Analysis\n\n')
    causes = {}
    for r in new_results:
        if r.get('root_cause'):
            rc = r['root_cause']
            causes[rc] = causes.get(rc, 0) + 1
    if causes:
        out.write('| Root Cause | Count | Percentage |\n')
        out.write('|------------|-------|------------|\n')
        for rc, count in sorted(causes.items(), key=lambda x: -x[1]):
            pct = count / failed * 100 if failed > 0 else 0
            out.write('| {} | {} | {:.1f}% |\n'.format(rc, count, pct))
    else:
        out.write('No failures recorded.\n')

print('Report generated:', report_file)
print('Total screenshots:', total_screenshots)
print('All categories 10-18: COMPLETE')
