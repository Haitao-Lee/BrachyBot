"""Fail-closed admission policy for same-result planning speed claims."""
OUTPUTS = {
    'trajectories', 'refined_trajectories', 'seed_plan_serialized',
    'verified_needle_geometry', 'dose_distribution', 'dose_distribution_gy',
    'dose_metrics', 'algorithm_plan_dvh_data',
}


def equivalence_eligibility(run):
    reasons = []
    if run.get('success') is not True:
        reasons.append('run_not_successful')
    budget = run.get('planning_latency_budget_status') or {}
    # RL plus fallback needs its own complete termination accounting before
    # admission. Shared-function unit equivalence is not an RL E2E claim.
    if budget.get('mode') != 'rule_based':
        reasons.append('mode_budget_accounting_not_verified')
    if budget.get('rule_based_deadline_reached') is not False:
        reasons.append('deadline_reached_or_unverified')
    repair = run.get('coverage_repair_status') or {}
    if repair.get('stop_reason') != 'target_reached':
        reasons.append('target_not_reached')
    for status in (repair, repair.get('base_status'), repair.get('extension_status')):
        if status and ('budget' in str(status.get('stop_reason', '')) or status.get('extension_error')):
            reasons.append('repair_budget_or_error')
    if not OUTPUTS.issubset(run.get('hashes', {})):
        reasons.append('incomplete_output_fingerprints')
    return {'eligible': not reasons, 'reasons': sorted(set(reasons))}


def compare_runs(before, after):
    checks = [equivalence_eligibility(run) for run in (before, after)]
    reasons = [reason for check in checks for reason in check['reasons']]
    for key in ('inputs_sha256', 'deterministic_validation'):
        if key not in before or key not in after or before[key] != after[key]:
            reasons.append('input_or_environment_mismatch:' + key)
    for key in OUTPUTS:
        if before.get('hashes', {}).get(key) != after.get('hashes', {}).get(key):
            reasons.append('output_mismatch:' + key)
    return {'eligible': not reasons, 'reasons': sorted(set(reasons))}


if __name__ == '__main__':
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    args = parser.parse_args()
    before = json.loads(args.before.read_text())
    after = json.loads(args.after.read_text())
    result = compare_runs(before, after)
    if result['eligible'] and float(after.get('pipeline_seconds', 0)) > 0:
        result['paired_speedup'] = float(before['pipeline_seconds']) / float(after['pipeline_seconds'])
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['eligible'] else 2)
