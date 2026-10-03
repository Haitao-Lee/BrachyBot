"""Explain failing legacy replay assertions without rewriting or suppressing gold.

Use an isolated workspace. The output is a review queue, NOT new clinical gold.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import re
import sys

BB = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BB))
from tools.run_task import evaluate, load_initial_state


def audit(log_path):
    failures = re.findall(r'^FAILED (.+)$', pathlib.Path(log_path).read_text(), re.M)
    tasks = {t['id']: t for p in (BB/'tasks').rglob('*.json') for t in [json.loads(p.read_text())]}
    negatives = json.loads((BB/'tests/replay/_negatives.json').read_text())
    rows = []
    for failure in failures:
        match = re.search(r'\[([^\]]+)\]$', failure)
        if not match or match[1] not in tasks:
            rows.append({'assertion': failure, 'status': 'requires_contract_or_unit_test_review'})
            continue
        tid = match[1]
        task = tasks[tid]
        negative = 'catches_the_unsafe_case' in failure
        observed = negatives.get(tid) if negative else json.loads((BB/'tests/replay'/f'{tid}.json').read_text())
        try:
            result = evaluate(task, observed, load_initial_state(task))
            merged = result['merged']
            rows.append({'assertion': failure, 'task_id': tid, 'replay_role': 'negative' if negative else 'positive',
                         'source_task_sha256': hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest(),
                         'current_verdict': result['verdict'],
                         'violation_codes': [v['code'] for v in merged.get('violations', [])],
                         'evidence_gap_codes': [v['code'] for v in merged.get('evidence_gaps', [])],
                         'status': 'independent_revalidation_required', 'gold_rewritten': False})
        except Exception as exc:
            rows.append({'assertion': failure, 'task_id': tid, 'status': 'unresolved_execution_error',
                         'error': f'{type(exc).__name__}: {exc}'})
    return {'legacy_failure_count': len(failures),
            'categories': dict(collections.Counter(row['status'] for row in rows)),
            'rows': rows, 'note': 'No verdict expectations were rewritten. A changed score is a review signal, not proof that new gold is correct.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pytest-log', required=True)
    args = parser.parse_args(argv)
    print(json.dumps(audit(args.pytest_log), indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
