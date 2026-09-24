import copy
from types import SimpleNamespace

from web.monitor_changes import capture, compare, describe, screenshot
from web.monitor_changes import compact_evidence, geometry_key
from web.monitor_engine import _training_feedback_for_event, _training_screenshot_for_event
from web.monitor_engine import _format_training_summary
from web import server_support as support
import pytest
from flask import Flask
from uuid import uuid4
from web.routes import planning_routes as routes


class Memory:
    def __init__(self, **values):
        self.values = values
    def retrieve(self, key, default=None):
        return self.values.get(key, default)
    def store(self, key, value):
        self.values[key] = value


def setup():
    geometry = {'seeds': [
        {'id': 'a', 'position': [0, 0, 5], 'direction': [0, 0, 1], 'trajectory_id': 't'},
        {'id': 'b', 'position': [0, 0, 15], 'direction': [0, 0, 1], 'trajectory_id': 't'},
    ], 'needles': [{'id': 'n', 'trajectory_id': 't', 'points': [[0, 0, 0], [0, 0, 30]]}]}
    agent = SimpleNamespace(memory=Memory(
        dose_metrics={'v100': 0.903, 'd90': 120.63, 'plan_score': 80, 'volume_metric_units': 'fraction'},
        dose_distribution=object(), manual_plan_version=1))
    return agent, geometry


def test_specific_changed_pair_and_stale_dose_never_claims_improvement():
    agent, geometry = setup()
    before = capture(agent, geometry)
    geometry['seeds'][1]['position'] = [0, 0, 6]
    agent.memory.store('manual_geometry_only', True)
    agent.memory.store('manual_plan_version', 2)
    after = capture(agent, geometry)
    evidence = compare(before, after)
    assert evidence['changed_objects'][0]['id'] == 'b'
    assert evidence['changed_objects'][0]['distance_mm'] == 9
    assert evidence['conflicts'][0]['change'] == 'new'
    assert evidence['conflicts'][0]['first_id'] == 'a'
    assert not evidence['dose']['comparable']
    assert not evidence['dose']['after']
    assert '模型噪声' not in describe(evidence, 'zh')
    assert '新增违规' in describe(evidence, 'zh')
    assert before['geometry']['seeds'][1]['position'] == [0, 0, 15]


def test_recompute_compares_saved_baseline_score_and_volume_units():
    agent, geometry = setup()
    before = capture(agent, geometry)
    agent.memory.store('dose_metrics', {'v100': 90.54, 'd90': 121.45,
                                       'plan_score': 81.2, 'volume_metric_units': 'percent'})
    evidence = compare(before, capture(agent, geometry))
    assert evidence['dose']['comparable']
    assert abs(evidence['dose']['delta']['v100'] - .24) < 1e-9
    assert abs(evidence['dose']['delta']['plan_score'] - 1.2) < 1e-9
    assert 'OAR' in describe(evidence, 'zh')
    assert 'plan_score: 80.00 → 81.20' in describe(evidence, 'en')


def test_anatomy_or_config_change_invalidates_dose_comparison():
    agent, geometry = setup()
    before = capture(agent, geometry)
    agent.memory.store('ctv_mask', object())
    assert not compare(before, capture(agent, geometry))['dose']['comparable']
    agent.memory.store('ctv_mask', None)
    agent.memory.store('plan_config', {'prescription_gy': 130})
    assert not compare(before, capture(agent, geometry))['dose']['comparable']


def test_edit_after_fifty_old_pairs_is_not_lost():
    agent, geometry = setup()
    # 66 preexisting conflicts must not hide the edited b/a pair.
    geometry['seeds'] = [{'id': f'old{i}', 'position': [100, 100, 100], 'direction': [0, 0, 1]}
                         for i in range(12)] + geometry['seeds']
    before = capture(agent, geometry)
    geometry['seeds'][-1]['position'] = [0, 0, 6]
    evidence = compare(before, capture(agent, geometry))
    assert len(evidence['conflicts']) == 1
    assert {evidence['conflicts'][0]['first_id'], evidence['conflicts'][0]['second_id']} == {'a', 'b'}
    assert set(screenshot(evidence, 'event')['object_ids']) == {'a', 'b'}


def test_frozen_commit_evidence_wins_over_unrelated_live_snapshot():
    agent, geometry = setup()
    before = capture(agent, geometry)
    geometry['seeds'][1]['position'] = [0, 0, 6]
    evidence = compare(before, capture(agent, geometry))
    event = {'event_id': 'e1', 'type': 'manual.seed.drag', 'language': 'zh',
             'detail': {'commit_status': 'committed', 'edit_evidence': evidence}}
    text = _training_feedback_for_event(None, 'case', event, snapshot={})
    assert '新增违规' in text
    plan = _training_screenshot_for_event(None, 'case', event, text, snapshot={})
    assert plan['checkpoint_id'] == 'e1'
    assert not plan['hide_unrelated']
    assert plan['annotation_policy'] == 'required'


def test_resolving_existing_conflict_and_deletion_are_distinct():
    agent, geometry = setup()
    geometry['seeds'][1]['position'] = [0, 0, 6]
    before = capture(agent, geometry)
    geometry['seeds'].pop()
    evidence = compare(before, capture(agent, geometry))
    assert evidence['changed_objects'][0]['operation'] == 'deleted'
    assert evidence['resolved_conflicts'] == 1
    assert screenshot(evidence, 'deleted') is None


def test_stopping_monitor_discards_live_inverse_and_dose_baseline():
    stopped = support._close_stale_training_snapshot({'active': True, 'run_id': 'a',
        'pending_restore': {'secret': 'old'}, 'dose_baseline': {'geometry': []}})
    assert 'pending_restore' not in stopped
    assert 'dose_baseline' not in stopped


@pytest.fixture
def live_monitor(monkeypatch):
    agent, geometry = setup()
    agent.memory.values.update(manual_seeds=geometry['seeds'], manual_needles=geometry['needles'],
                               manual_plan_active=True, active_planning_id='p1')
    sid = 'edit-' + uuid4().hex
    store = SimpleNamespace(get_session=lambda user, case: SimpleNamespace(id=case),
        save_ui_bridge=lambda *a, **k: None, schedule_agent_checkpoint=lambda *a, **k: None)
    monkeypatch.setattr(routes, 'require_api_key', lambda f: f)
    monkeypatch.setattr(routes, 'rate_limit', lambda f: f)
    monkeypatch.setattr(routes, 'current_user', lambda store: {'id': 'test'})
    monkeypatch.setattr(routes, 'fork_planning_run', lambda *a, **kw: 'p1')
    monkeypatch.setattr(routes, 'publish_planning_run', lambda *a, **kw: None)
    monkeypatch.setattr(routes, 'invalidate_planning_dependents', lambda *a, **kw: None)
    monkeypatch.setattr('web.surgical_guide.invalidate_surgical_guides', lambda *a, **kw: None)
    app = Flask(__name__)
    app.secret_key = 'test'
    app.extensions['brachybot_workspace_store'] = store
    routes.register_planning_routes(app, lambda *a, **kw: agent, get_cached_agent=lambda *a: agent)
    client = app.test_client()
    def post(path, payload):
        return client.post('/api/' + path, json=payload, headers={'X-BrachyBot-Session': sid})
    post('training/start', {'monitor_run_id': 'run', 'language': 'zh'})
    yield agent, geometry, post, sid
    routes._flush_ui_bridge_checkpoint(('test', sid))
    support._drop_ui_bucket(sid)


def commit_move(agent, geometry, post):
    moved = copy.deepcopy(geometry['seeds'])
    moved[1]['position'] = [0, 0, 6]
    result = post('manual_planning/update_seeds', {'expected_version': 1, 'seeds': moved,
        'needles': geometry['needles'], 'reason': 'move', 'allow_unsafe': True, 'safety_override': 'user_confirmed'})
    assert result.status_code == 200, result.get_json()
    return result.get_json()


def test_real_commit_replay_feedback_and_exact_undo(live_monitor):
    agent, geometry, post, sid = live_monitor
    result = commit_move(agent, geometry, post)
    assert result['monitor_edit']['conflicts'][0]['change'] == 'new'
    feedback = post('ui/event', {'monitor_run_id': 'run', 'already_recorded': True,
        'committed_event': result['event'], 'language': 'zh'}).get_json()
    assert '新增违规' in feedback['feedback']
    assert feedback['suggested_screenshot']['checkpoint_id'] == result['event']['event_id']
    token = result['monitor_edit']['restore_token']
    response = post('training/restore_edit', {'token': token, 'decision': 'restore'})
    assert response.status_code == 200, response.get_json()
    assert agent.memory.retrieve('manual_seeds')[1]['position'] == [0, 0, 15]
    assert agent.memory.retrieve('manual_artifact_status')['dose'] == 'stale'
    assert post('training/restore_edit', {'token': token, 'decision': 'restore'}).status_code == 409


def test_later_edit_fences_undo_and_forged_token_is_rejected(live_monitor):
    agent, geometry, post, sid = live_monitor
    result = commit_move(agent, geometry, post)
    token = result['monitor_edit']['restore_token']
    assert post('training/restore_edit', {'token': 'f'*12, 'decision': 'restore'}).status_code == 409
    agent.memory.store('manual_plan_version', 3)
    response = post('training/restore_edit', {'token': token, 'decision': 'restore'})
    assert response.status_code == 409
    assert agent.memory.retrieve('manual_seeds')[1]['position'] == [0, 0, 6]


def test_keep_preserves_geometry_and_consumes_only_its_decision(live_monitor):
    agent, geometry, post, sid = live_monitor
    result = commit_move(agent, geometry, post)
    token = result['monitor_edit']['restore_token']
    assert post('training/restore_edit', {'token': token, 'decision': 'keep'}).status_code == 200
    assert agent.memory.retrieve('manual_seeds')[1]['position'] == [0, 0, 6]
    assert post('training/restore_edit', {'token': token, 'decision': 'restore'}).status_code == 409


def test_geometry_signature_ignores_json_numeric_spelling():
    agent, geometry = setup()
    normalized = copy.deepcopy(geometry)
    for seed in normalized['seeds']:
        seed['position'] = [float(v) for v in seed['position']]
        seed['direction'] = [float(v) for v in seed['direction']]
    assert geometry_key(normalized) == geometry_key(geometry)


def test_committed_evidence_reaches_general_chat_without_geometry_or_token():
    from agent_runtime.context_window import build_case_facts
    agent, geometry = setup()
    agent.memory.store('active_planning_id', 'p1')
    before = capture(agent, geometry)
    geometry['seeds'][1]['position'] = [0, 0, 6]
    evidence = compare(before, capture(agent, geometry))
    evidence['restore_token'] = 'abc123abc123'
    agent.memory.store('monitor_last_edit', compact_evidence(evidence))
    text = build_case_facts(agent.memory)
    assert 'server_committed_monitor_edit' in text
    assert 'abc123abc123' not in text
    assert 'return_vector_mm' not in text
    agent.memory.store('active_planning_id', 'p2')
    assert 'server_committed_monitor_edit' not in build_case_facts(agent.memory)


def test_case_facts_expose_saved_restore_candidate_without_claiming_it_is_validated():
    from agent_runtime.context_window import build_case_facts
    agent, _ = setup()
    agent.memory.store('planning_runs', [
        {'planning_id': 'original', 'source': 'algorithm', 'status': 'completed'},
        {'planning_id': 'draft', 'source': 'manual_edit', 'status': 'draft'},
    ])
    facts = build_case_facts(agent.memory)
    assert 'completed non-manual candidates: original' in facts
    assert 'activate a verified completed algorithm baseline' in facts
    assert 'draft' not in facts.split('completed non-manual candidates:')[1].split('\n')[0]


def test_oar_changes_are_compared_only_for_matching_metrics():
    agent, geometry = setup()
    agent.memory.values['dose_metrics']['oar_metrics'] = {'spinal_cord': {'dmax': 10, 'd2cc': 4}}
    before = capture(agent, geometry)
    agent.memory.values['dose_metrics']['oar_metrics'] = {'spinal_cord': {'dmax': 12, 'd2cc': 3}, 'new_organ': {'dmax': 99}}
    evidence = compare(before, capture(agent, geometry))
    assert evidence['dose']['oar_metric_comparison_count'] == 2
    assert evidence['dose']['oar_changes'][0]['delta'] == 2
    assert 'spinal_cord' in describe(evidence, 'zh')
    assert 'new_organ' not in describe(evidence, 'zh')


def test_in_place_anatomy_store_generation_invalidates_comparison():
    agent, geometry = setup()
    agent.memory._planning_versions = {'ctv_array': 1}
    before = capture(agent, geometry)
    agent.memory._planning_versions['ctv_array'] = 2
    assert not compare(before, capture(agent, geometry))['dose']['comparable']


def test_joint_seed_and_needle_edit_offers_one_atomic_restore(live_monitor, monkeypatch):
    import numpy as np
    import SimpleITK as sitk
    agent, geometry, post, sid = live_monitor
    agent.memory.store('ct_image', sitk.GetImageFromArray(np.zeros((32, 4, 4), dtype=np.float32)))
    agent.memory.store('ctv_array', np.ones((32, 4, 4), dtype=np.uint8))
    monkeypatch.setattr(support, '_validate_manual_needle_safety', lambda *a, **kw: None)
    moved = copy.deepcopy(geometry)
    moved['needles'][0]['points'] = [[1, 0, 0], [1, 0, 30]]
    for seed in moved['seeds']:
        seed['position'][0] = 1
    response = post('manual_planning/update_geometry', {'expected_version': 1, 'reason': 'needle_drag', **moved})
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    token = data['monitor_edit']['restore_token']
    restored = post('training/restore_edit', {'token': token, 'decision': 'restore'})
    assert restored.status_code == 200, restored.get_json()
    assert agent.memory.retrieve('manual_needles')[0]['points'] == [[0, 0, 0], [0, 0, 30]]
    assert agent.memory.retrieve('manual_seeds')[0]['position'] == [0, 0, 5]


def test_two_edits_one_recompute_keeps_local_geometry_and_cumulative_dose(live_monitor, monkeypatch):
    agent, geometry, post, sid = live_monitor
    for version, z in ((1, 14), (2, 13)):
        seeds = copy.deepcopy(geometry['seeds'])
        seeds[1]['position'][2] = z
        response = post('manual_planning/update_seeds', {'expected_version': version,
            'seeds': seeds, 'needles': geometry['needles'], 'reason': 'move'})
        assert response.status_code == 200, response.get_json()
    def compute(agent, seeds, needles, **kwargs):
        metrics = {'v100': .91, 'd90': 122, 'plan_score': 82, 'volume_metric_units': 'fraction'}
        agent.memory.store('dose_metrics', metrics)
        agent.memory.store('manual_geometry_only', False)
        agent.memory.store('manual_artifact_status', {'dose': 'ready', 'dvh': 'ready'})
        return {'success': True, 'seeds': seeds, 'needles': needles, 'metrics': metrics,
                'planning_version': 3, 'total_seeds': 2, 'num_trajectories': 1}
    monkeypatch.setattr(routes, '_compute_manual_ai_dose', compute)
    monkeypatch.setattr(routes, '_build_plan_advice', lambda *a, **kw: {})
    response = post('manual_planning/update', {'planning_version': 3,
        'seeds': agent.memory.retrieve('manual_seeds'), 'needles': geometry['needles'], 'reason': 'manual_update'})
    assert response.status_code == 200, response.get_json()
    evidence = response.get_json()['monitor_edit']
    assert evidence['changed_objects'][0]['distance_mm'] == 1
    assert evidence['dose']['edit_count'] == 2
    assert evidence['dose']['delta']['plan_score'] == 2
    assert '2 次编辑' in describe(evidence, 'zh')


def test_geometry_key_tolerates_malformed_entries():
    """One bad entry must not drop the whole edit-evidence set.

    Previously a seed without ``position`` (or a needle without two points)
    raised inside ``geometry_key``; the decorator then skipped all evidence for
    a successful edit. The key must stay defined and still change when the bad
    entry changes.
    """
    malformed = {
        'seeds': [
            {'id': 'good', 'position': [1, 2, 3], 'direction': [0, 0, 1], 'trajectory_id': 't'},
            {'id': 'bad'},  # no position
        ],
        'needles': [
            {'id': 'n', 'points': [[0, 0, 0]]},  # one point only
        ],
    }
    key = geometry_key(malformed)
    assert isinstance(key, str) and len(key) == 64

    changed = copy.deepcopy(malformed)
    changed['seeds'][1]['position'] = [9, 9, 9]
    assert geometry_key(changed) != key

    empty = geometry_key({'seeds': [], 'needles': []})
    assert isinstance(empty, str) and empty != key


def test_rounding_noise_and_orientation_are_not_reported_as_zero_mm_drags():
    agent, geometry = setup()
    before = capture(agent, geometry)
    geometry['seeds'][1]['position'][2] += .004
    noise = compare(before, capture(agent, geometry))
    assert noise['changed_object_count'] == 0
    assert '0.00 mm' not in describe(noise, 'zh')
    geometry['seeds'][1]['direction'] = [.01, 0, .99995]
    oriented = compare(before, capture(agent, geometry))
    assert oriented['changed_objects'][0]['operation'] == 'reoriented'
    assert '移动 0.00 mm' not in describe(oriented, 'zh')


def test_needle_edit_groups_dependent_seeds_and_does_not_blame_old_conflicts():
    agent, geometry = setup()
    geometry['seeds'][1]['position'] = [0, 0, 6]
    before = capture(agent, geometry)
    geometry['needles'][0]['points'][0] = [1, 0, 0]
    geometry['needles'][0]['points'][1] = [1, 0, 30]
    geometry['seeds'][0]['position'][0] = 1
    geometry['seeds'][1]['position'][0] = 1
    evidence = compare(before, capture(agent, geometry))
    assert evidence['changed_objects'][0]['id'] == 'n'
    assert evidence['dependent_object_count'] == 2
    text = describe(evidence, 'zh')
    assert '不是 2 次独立拖拽' in text
    assert '原有违规仍存在' not in text
    assert '编辑前已存在' in text
    assert screenshot(evidence, 'edit')['object_ids'] == ['n']


def test_summary_collapses_dose_recompute_of_same_geometry_edit():
    evidence = {'event_id': 'edit', 'geometry_event_id': 'edit',
                'changed_objects': [{'id': 'needle_22', 'kind': 'needles',
                    'operation': 'moved', 'distance_mm': 2.0}],
                'changed_object_count': 1, 'conflicts': [], 'dose': {}}
    after_dose = {**evidence, 'event_id': 'dose', 'dose': {'comparable': False}}
    events = [{'type': 'manual.needle.drag', 'detail': {'edit_evidence': evidence}},
              {'type': 'manual.dose', 'detail': {'edit_evidence': after_dose}}]
    summary = _format_training_summary(events, {}, {}, 'zh')
    assert summary.count('needle_22：移动 2.00 mm') == 1


def test_needle_commit_direction_normalization_is_not_many_independent_drags():
    agent, geometry = setup()
    for index in range(10):
        geometry['seeds'].append({'id': f'other_{index}', 'trajectory_id': 'other',
            'position': [100 + 10 * index, 0, 0], 'direction': [0, 0, 1]})
    before = capture(agent, geometry)
    geometry['needles'][0]['points'][0] = [1, 0, 0]
    for seed in geometry['seeds'][2:]:
        seed['direction'] = [0, .01, .99995]
    evidence = compare(before, capture(agent, geometry))
    assert evidence['normalization_object_count'] == 10
    assert evidence['changed_objects'][0]['id'] == 'n'
    assert screenshot(evidence, 'edit')['object_ids'] == ['n']
    text = describe(evidence, 'zh')
    assert '不表示用户逐枚拖动' in text
    assert 'other_0：移动' not in text
