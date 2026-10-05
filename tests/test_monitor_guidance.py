"""Evidence-to-action coaching counterexamples, independent of LLM wording."""
import copy

import pytest

from web.monitor_changes import compact_evidence, dose_comparison, guided_feedback, interaction, screenshot


def seed_edit(change='new'):
    return {'planning_id': 'plan', 'after_version': 2, 'geometry_key': 'geometry',
            'restore_token': 'private-token', 'geometry_event_id': 'edit',
            'changed_objects': [{'id': 'seed_b', 'kind': 'seeds', 'operation': 'moved',
                                 'before': [0, 0, 8], 'after': [0, 0, 5], 'distance_mm': 3}],
            'new_conflict_count': int(change == 'new'), 'worsened_conflict_count': int(change == 'worsened'),
            'conflicts': [{'first_id': 'seed_a', 'second_id': 'seed_b', 'kind': 'seed_pairs',
                           'change': change, 'surface_clearance_mm': -.4, 'previous_distance_mm': 1.,
                           'minimum_clearance_mm': .5, 'clearance_basis': 'finite_parallel_cylinders'}],
            'dose': {'comparable': False, 'after': {}, 'comparison_reason': 'current_dose_unavailable'}}


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_global_locale_projection_reuses_identical_committed_facts(language):
    evidence = seed_edit()
    original = copy.deepcopy(evidence)
    card = interaction(evidence, language)
    assert set(card['localized']) == {'zh', 'en'}
    for field in ('headline', 'dose_note', 'next_step', 'assessment', 'metric_rows'):
        assert card[field] == card['localized'][language][field]
    assert card['localized']['zh']['dose_note'] != card['localized']['en']['dose_note']
    assert card['localized']['zh']['assessment']['primary_pair'] == card['localized']['en']['assessment']['primary_pair']
    assert card['objects'] == original['changed_objects']
    assert evidence == original, 'UI projections do not mutate geometry, dose, identity or authorization'


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('change', ['new', 'worsened'])
def test_new_conflict_has_specific_measurement_first_action_choice_and_verification(language, change):
    evidence = seed_edit(change)
    original = copy.deepcopy(evidence)
    guide = guided_feedback(evidence, language)
    assert 'seed_a' in guide['title'] and 'seed_b' in guide['title']
    assert '-0.40 mm' in guide['meaning'] and '0.50 mm' in guide['meaning']
    assert [step['action'] for step in guide['steps']] == ['focus', 'spacing', 'preview']
    assert guide['steps'][1]['object_id'] == 'seed_b'
    assert guide['verification'] and guide['limitation']
    assert guide['localized']['zh']['title'] != guide['localized']['en']['title']
    assert evidence == original


@pytest.mark.parametrize('change', ['improved', 'existing'])
def test_remaining_conflict_is_not_presented_as_clear_or_as_new_damage(change):
    card = interaction(seed_edit(change), 'en')
    guide = card['guidance']
    assert card['primary_action'] == 'focus'
    assert set(guide['focus_refs']).issubset(card['spatial_refs'])
    assert set(guide['focus_refs']) == {'seed_a', 'seed_b'}
    assert 'still' in guide['title']
    assert not any(step['action'] == 'spacing' for step in guide['steps'])
    assert card['decision_required'] is False, 'review is not a routine keep confirmation'
    assert {'seed_a', 'seed_b'}.issubset(screenshot(seed_edit(change), 'image')['object_ids'])


def test_conservative_needle_bound_does_not_claim_exact_overlap_or_offer_seed_search():
    evidence = seed_edit()
    evidence['conflicts'][0].update(kind='needle_pairs', clearance_basis='axis_distance_bound')
    evidence['changed_objects'][0].update(kind='needles')
    guide = guided_feedback(evidence, 'en')
    assert 'axis-model clearance bound' in guide['meaning']
    assert 'physical overlap' not in guide['meaning']
    assert 'spacing' not in [step['action'] for step in guide['steps']]


def test_unchanged_dependent_seed_conflicts_do_not_steal_the_needle_edit_recommendation():
    evidence = seed_edit('existing')
    evidence['existing_conflict_count'] = 1
    evidence['changed_objects'] = [{'id': 'needle_n', 'kind': 'needles', 'operation': 'moved'},
                                   {'id': 'seed_b', 'kind': 'seeds', 'operation': 'moved', 'dependent_on_needle': True}]
    guide = guided_feedback(evidence, 'en')
    assert not guide['focus_refs'] and guide['primary_action'] == 'dose'
    assert 'not attributed to this edit' in guide['observation']
    assert screenshot(evidence, 'image')['object_ids'] == ['needle_n']


@pytest.mark.parametrize('reason', ['baseline_dose_unavailable', 'anatomy_changed', 'configuration_changed'])
def test_current_dose_without_baseline_does_not_recommend_useless_recomputation(reason):
    evidence = {'dose': {'comparable': False, 'after': {'v100': 90}, 'comparison_reason': reason}}
    guide = guided_feedback(evidence, 'en')
    assert guide['primary_action'] == 'details'
    assert 'cannot recreate' in guide['meaning']
    assert 'do not recompute' in guide['recommendation']
    assert not any(step['action'] == 'dose' for step in guide['steps'])


def test_pending_dose_names_the_actual_next_action_without_automatic_work():
    guide = guided_feedback({'dose': {'comparable': False, 'after': {}}}, 'en')
    assert guide['primary_action'] == 'dose'
    assert guide['steps'][0]['label'] == 'Recompute and compare'
    assert 'old DVH' in guide['meaning']


def test_pending_dose_with_missing_baseline_does_not_promise_a_recoverable_comparison():
    guide = guided_feedback({'dose': {'comparable': False, 'after': {},
                            'comparison_reason': 'baseline_dose_unavailable'}}, 'en')
    assert 'without a valid baseline' in guide['recommendation']
    assert 'not a dose verdict' in guide['recommendation']
    assert guide['primary_action'] == 'dose'


def test_inconsistent_coverage_metrics_and_v150_only_cost_are_not_hidden():
    dose = {'comparable': True, 'delta': {'v100': 1, 'd90': -2, 'v150': 4, 'v200': 0},
            'before': {'v100': 90, 'd90': 120, 'v150': 30}, 'after': {'v100': 91, 'd90': 118, 'v150': 34}}
    guide = guided_feedback({'dose': dose}, 'en')
    assert 'D90 moved in the opposite direction' in guide['recommendation']
    assert 'V150 increased' in guide['meaning']
    assert any('V150' in finding for finding in guide['findings'])


def test_multi_edit_coverage_gain_with_hotspot_cost_is_conditional_not_a_verdict():
    evidence = {'dose': {'comparable': True, 'edit_count': 3,
                        'before': {'v100': 90, 'v200': 20, 'd90': 120},
                        'after': {'v100': 91, 'v200': 24, 'd90': 121},
                        'delta': {'v100': 1, 'v200': 4, 'd90': 1},
                        'oar_changes': [{'organ': 'cord', 'metric': 'd2cc', 'before': 2, 'after': 3, 'delta': 1}]}}
    guide = guided_feedback(evidence, 'en')
    assert 'trade-off' in guide['title']
    assert '3 edits' in guide['meaning'] and 'cord d2cc' in guide['meaning']
    assert 'If your aim' in guide['recommendation']
    assert 'clinical approval' in guide['limitation']
    assert guide['primary_action'] == 'details'


def test_coverage_loss_gives_a_goal_specific_warning_not_a_generic_checklist():
    evidence = {'dose': {'comparable': True, 'delta': {'v100': -1, 'v200': -2}}}
    guide = guided_feedback(evidence, 'en')
    assert 'opposite direction' in guide['recommendation']
    assert 'low-dose region' in guide['recommendation']


def test_sub_display_precision_is_not_called_model_noise_or_significant_improvement():
    dose = {'comparable': True, 'before': {'v100': 90}, 'after': {'v100': 90.001}, 'delta': {'v100': .001}}
    guide = guided_feedback({'dose': dose}, 'en')
    assert 'display precision' in guide['findings'][0]
    assert 'within model noise' not in str(guide)
    assert 'not overall improvement' in guide['recommendation']


def test_oar_rise_is_not_hidden_by_larger_decreases_in_other_organs():
    before = {'planning_id': 'p', 'anatomy_key': ['same'], 'config': {}, 'metrics_current': True,
              'metrics': {}, 'oar_metrics': {f'fall_{n}': {'dmax': 100 + n} for n in range(6)}}
    before['oar_metrics']['rising'] = {'dmax': 1}
    after = copy.deepcopy(before)
    after['oar_metrics'] = {key: {'dmax': 0} for key in before['oar_metrics']}
    after['oar_metrics']['rising'] = {'dmax': 2}
    dose = dose_comparison(before, after)
    assert dose['oar_changes'][0]['organ'] == 'rising'
    assert dose['oar_increase_count'] == 1
    assert dose['oar_metric_comparison_count'] == 7
    assert 'rising dmax' in guided_feedback({'dose': dose}, 'en')['meaning']


def test_superseded_evidence_preserves_observation_but_offers_no_old_actions():
    evidence = seed_edit()
    evidence['superseded'] = True
    guide = guided_feedback(evidence, 'en')
    assert guide['state'] == 'historical' and not guide['steps'] and not guide['focus_refs']
    assert 'do not act' in guide['recommendation']


def test_compact_agent_facts_include_guidance_without_tokens_coordinates_or_bilingual_bulk():
    facts = compact_evidence(seed_edit())
    assert facts['guidance']['recommendation']
    assert 'private-token' not in str(facts)
    assert 'localized' not in facts['guidance']
    assert 'before' not in facts['changed_objects'][0]
