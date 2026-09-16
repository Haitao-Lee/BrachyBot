import copy
from scripts.latency_comparison import OUTPUTS, compare_runs, equivalence_eligibility


def valid_run():
    return dict(success=True, inputs_sha256='same', deterministic_validation=False,
                hashes={key: key for key in OUTPUTS},
                planning_latency_budget_status=dict(mode='rule_based', rule_based_deadline_reached=False),
                coverage_repair_status=dict(stop_reason='target_reached', trials=0,
                                           budget_allocated_seconds=60, elapsed_seconds=0.001))


def test_zero_trials_allocated_budget_is_not_timeout():
    run = valid_run()
    assert compare_runs(run, copy.deepcopy(run))['eligible']


def test_extension_success_does_not_erase_base_timeout():
    run = valid_run()
    run['coverage_repair_status']['base_status'] = dict(stop_reason='time_budget')
    assert not equivalence_eligibility(run)['eligible']


def test_unknown_or_expired_budget_and_rl_are_not_admitted():
    for value in (None, True):
        run = valid_run()
        run['planning_latency_budget_status']['rule_based_deadline_reached'] = value
        assert not equivalence_eligibility(run)['eligible']
    run = valid_run()
    run['planning_latency_budget_status']['mode'] = 'rl'
    assert not equivalence_eligibility(run)['eligible']


def test_output_and_input_mismatch_and_missing_hash_are_rejected():
    before = valid_run()
    for key in ('inputs_sha256', 'deterministic_validation'):
        after = copy.deepcopy(before)
        after[key] = 'different'
        assert not compare_runs(before, after)['eligible']
    after = copy.deepcopy(before)
    after['hashes'].pop('dose_distribution')
    assert not compare_runs(before, after)['eligible']
