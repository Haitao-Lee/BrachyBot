from types import SimpleNamespace

import pytest

from web.monitor_changes import overview, interaction, compare
from web.monitor_changes import timeline_projection, dose_comparison


def agent(**values):
    return SimpleNamespace(memory=SimpleNamespace(retrieve=lambda key: values.get(key)))


def test_cold_overview_does_not_create_or_hydrate_an_agent():
    assert overview(None) == {'available': False, 'stages': [], 'metrics': {}}


@pytest.mark.parametrize('state', ['stale', 'running', 'failed'])
def test_old_dose_is_not_advertised_as_current(state):
    result = overview(agent(dose_distribution=object(), dose_metrics={'v100': .92},
                            manual_artifact_status={'dose': state}))
    assert result['metrics'] == {}
    assert not result['dose_current']


@pytest.mark.parametrize('value,units,expected', [(.92, 'fraction', 92), (.5, 'percent', .5), (92, 'percent', 92)])
def test_overview_respects_units_and_does_not_treat_metrics_as_a_report(value, units, expected):
    result = overview(agent(dose_distribution=object(), dose_metrics={
        'v100': value, 'volume_metric_units': units, 'd90': 120, 'v200': float('nan')},
        manual_artifact_status={'quality_check': {'status': 'ready'}}))
    assert result['metrics']['v100'] == expected
    assert 'v200' not in result['metrics']
    states = {row['key']: row['state'] for row in result['stages']}
    assert states['report'] == 'unknown'
    assert states['quality_check'] == 'available'


def test_geometry_only_overview_does_not_reuse_old_values():
    assert overview(agent(dose_distribution=object(), manual_geometry_only=True,
                          dose_metrics={'d90':120}))['metrics'] == {}


def test_interaction_has_grounded_spatial_references_and_warning_not_clinical_failure():
    evidence = {'after_version':4, 'new_conflict_count':1, 'changed_objects':[
        {'id':'removed', 'operation':'deleted'}, {'id':'seed2', 'operation':'moved'}],
        'conflicts':[{'first_id':'seed1', 'second_id':'seed2', 'change':'new'}]}
    result = interaction(evidence, 'zh')
    assert result['severity'] == 'warning'
    assert result['spatial_refs'] == ['seed1', 'seed2']
    assert result['conflict_counts']['new'] == 1
    assert result['dose_comparable'] is False


def test_highest_recorded_organ_is_observed_not_clinical_classification():
    result = overview(agent(dose_distribution=object(), dose_metrics={'oar_metrics':{
        'a': {'dmax':4}, 'b': {'dmax':9}, 'broken': {'dmax':float('inf')}}}))
    assert result['highest_recorded_oar'] == {'organ':'b', 'dmax':9.0}
    assert 'passed' not in result


def test_blocking_is_measured_geometry_not_unsupported_clinical_threshold():
    evidence = {'new_conflict_count': 1, 'conflicts': [{'first_id':'a', 'second_id':'b',
                'change':'new', 'risk':'overlap', 'physical_overlap':True,
                'surface_clearance_mm':-.1}]}
    value = interaction(evidence)
    assert value['severity'] == 'blocking'
    assert value['blocking_scope'] == 'physical_geometry'
    evidence['conflicts'][0]['change'] = 'existing'
    assert interaction(evidence)['severity'] == 'warning'


@pytest.mark.parametrize('center_step, expected_risk, expected_gap', [
    (5.0, None, None),       # 0.5 mm end-face gap meets the safety minimum
    (4.7, 'too_close', .2),
    (4.55, 'too_close', .05),
    (4.5, 'too_close', 0.0),
    (4.4, 'overlap', -.1),
])
def test_finite_seed_end_faces_do_not_become_sidewall_collisions(
    center_step, expected_risk, expected_gap,
):
    from web.server_support import _seed_interference_report
    seeds = [{'id': 'a', 'position': [0, 0, 0], 'direction': [0, 0, 1]},
             {'id': 'b', 'position': [0, 0, center_step], 'direction': [0, 0, 1]}]
    report = _seed_interference_report(agent(), seeds, [])
    if expected_risk is None:
        assert report['close_pairs'] == []
        assert report['overlap_count'] == 0
        return
    pair = report['close_pairs'][0]
    assert pair['risk'] == expected_risk
    assert pair['physical_overlap'] is (expected_risk == 'overlap')
    assert pair['clearance_basis'] == 'finite_parallel_cylinders'
    assert pair['surface_clearance_mm'] == pytest.approx(expected_gap, abs=.001)
    evidence = {'new_conflict_count': 1, 'conflicts': [{**pair, 'change': 'new', 'kind': 'seed_pairs'}]}
    feedback = interaction(evidence, 'zh')
    assert feedback['severity'] == ('blocking' if expected_risk == 'overlap' else 'warning')
    assert feedback['blocking_scope'] == ('physical_geometry' if expected_risk == 'overlap' else None)


def test_skew_endpoint_axis_bound_is_not_claimed_as_verified_overlap():
    from web.server_support import _finite_cylinder_spacing, _seed_interference_report
    spacing = _finite_cylinder_spacing([0, 0, 0], [4.5, 0, 0],
                                        [5, 0, 0], [5, 4.5, 0], .8)
    assert spacing['axis_distance_mm'] == pytest.approx(.5)
    assert spacing['physical_overlap'] is None
    assert spacing['clearance_basis'] == 'axis_lower_bound'
    seeds = [{'id': 'a', 'position': [2.25, 0, 0], 'direction': [1, 0, 0]},
             {'id': 'b', 'position': [5, 2.25, 0], 'direction': [0, 1, 0]}]
    pair = _seed_interference_report(agent(), seeds, [])['close_pairs'][0]
    assert pair['risk'] == 'possible_overlap'
    assert pair['physical_overlap'] is None
    evidence = {'new_conflict_count': 1, 'conflicts': [{**pair, 'change': 'new', 'kind': 'seed_pairs'}]}
    feedback = interaction(evidence, 'zh')
    assert feedback['severity'] == 'warning'
    assert feedback['blocking_scope'] is None


def test_finite_cylinder_witness_keeps_verified_sidewall_overlap():
    from web.server_support import _finite_cylinder_spacing
    spacing = _finite_cylinder_spacing([0, 0, 0], [4.5, 0, 0],
                                        [2, -2, .2], [2, 2.5, .2], .8)
    assert spacing['axis_distance_mm'] == pytest.approx(.2)
    assert spacing['physical_overlap'] is True
    assert spacing['clearance_basis'] == 'interior_axis_witness'
    separated_needles = _finite_cylinder_spacing([0, 0, 0], [10, 0, 0],
                                                  [10.5, 0, 0], [20.5, 0, 0], 1.2)
    assert separated_needles['axis_distance_mm'] == pytest.approx(.5)
    assert separated_needles['clearance_mm'] == pytest.approx(.5)
    assert separated_needles['physical_overlap'] is False


def test_touching_end_faces_worsened_to_overlap_still_block_the_edit():
    from web.server_support import _manual_seed_interference_delta
    first = {'id': 'a', 'position': [0, 0, 0], 'direction': [0, 0, 1]}
    def second(step):
        return {'id': 'b', 'position': [0, 0, step], 'direction': [0, 0, 1]}
    report, blocked = _manual_seed_interference_delta(
        agent(), [first, second(4.4)], [],
        baseline_seeds=[first, second(4.5)], baseline_needles=[],
    )
    assert report['overlap_count'] == 1
    assert len(blocked) == 1
    assert blocked[0]['risk'] == 'overlap'
    assert blocked[0]['physical_overlap'] is True


def test_finite_needle_end_gap_does_not_create_an_axis_only_conflict():
    from web.server_support import _needle_interference_report
    fixed = {'id': 'n1', 'points': [[0, 0, 0], [10, 0, 0]]}
    config = {'needle_diameter_mm': 1.2, 'needle_clearance_mm': 1.0}

    def reported(start):
        return _needle_interference_report([fixed,
            {'id': 'n2', 'points': [[start, 0, 0], [start + 10, 0, 0]]}], config)

    assert reported(11.5)['close_pairs'] == []
    near = reported(10.5)['close_pairs'][0]
    assert near['surface_clearance_mm'] == pytest.approx(.5)
    assert near['risk'] == 'too_close'
    assert near['physical_overlap'] is False
    assert reported(9.8)['close_pairs'][0]['risk'] == 'intersecting'

    def snapshot(start, version):
        return {'geometry': {'seeds': [], 'needles': [fixed,
                {'id': 'n2', 'points': [[start, 0, 0], [start + 10, 0, 0]]}]},
                'geometry_key': str(version), 'planning_id': 'p', 'version': version,
                'config': config,
                'metrics_current': False, 'metrics': {}, 'anatomy_key': None}

    # The 1.5 mm finite end gap satisfies the required 1.0 mm clearance,
    # although the axes are closer than the old 2.2 mm centreline threshold.
    safe = compare(snapshot(12.5, 1), snapshot(11.5, 2))
    assert safe['conflicts'] == []
    close = compare(snapshot(11.5, 2), snapshot(10.5, 3))
    assert close['new_conflict_count'] == 1
    assert close['conflicts'][0]['surface_clearance_mm'] == pytest.approx(.5)
    assert close['conflicts'][0]['physical_overlap'] is False
    assert interaction(close)['severity'] == 'warning'

    # Once end faces touch, the axis distance is zero on both sides of the
    # edit. The finite surface gap must still detect the new penetration.
    overlap = compare(snapshot(10.0, 3), snapshot(9.8, 4))
    assert overlap['worsened_conflict_count'] == 1
    assert overlap['conflicts'][0]['surface_clearance_mm'] == pytest.approx(-.2)
    assert overlap['conflicts'][0]['physical_overlap'] is True
    assert interaction(overlap)['severity'] == 'blocking'


def test_monitor_snapshot_uses_the_same_finite_needle_spacing_contract():
    from web.server_support import _latest_plan_snapshot

    def snapshot(start):
        values = {
            'plan_config': {'needle_diameter_mm': 1.2, 'needle_clearance_mm': 1.0},
            'manual_needles': [
                {'id': 'n1', 'points': [[0, 0, 0], [10, 0, 0]]},
                {'id': 'n2', 'points': [[start, 0, 0], [start + 10, 0, 0]]},
            ],
            'manual_seeds': [],
        }
        return _latest_plan_snapshot(agent(**values), validate_obstacles=False)['needle_geometry']

    assert snapshot(11.5)['close_pairs'] == []
    close = snapshot(10.5)['close_pairs'][0]
    assert close['risk'] == 'too_close'
    assert close['surface_clearance_mm'] == pytest.approx(.5)
    assert close['physical_overlap'] is False


def test_overview_oar_cards_and_configured_target_are_current_only():
    kwargs = dict(dose_distribution=object(),plan_config={'DVH_rate':.92},dose_metrics={
        'plan_score':83.2, 'oar_metrics': {f'o{i}':{'dmax':i} for i in range(9)}})
    result = overview(agent(**kwargs))
    assert result['metrics']['plan_score'] == 83.2
    assert [r['organ'] for r in result['recorded_oars']] == ['o8','o7','o6','o5','o4']
    assert result['recorded_oar_count'] == 9
    assert result['coverage_target_percent'] == 92
    stale = overview(agent(**kwargs,manual_geometry_only=True))
    assert stale['recorded_oars'] == [] and stale['metrics'] == {}
    assert overview(agent(plan_config={}))['coverage_target_percent'] is None


def test_timeline_projection_is_bounded_token_free_and_cannot_attest_a_preview():
    evidence = {'restore_token':'private-token', 'before_geometry':list(range(10000)),
                'after_version':3, 'planning_id':'p', 'dose':{'after':{'v100':91},'series_key':'base'}}
    events = [{'event_id':str(i), 'type':'manual.seed.drag','detail':{
        'commit_status':'committed' if i % 2 else 'unverified','edit_evidence':evidence}} for i in range(50)]
    result = timeline_projection({'events':events,'event_counts':{'manual.seed.drag':75},'dropped_event_count':25},4)
    assert result['event_count'] == 75 and result['retained_event_count'] == 50
    assert result['returned_event_count'] == 4 and result['dropped_event_count'] == 25
    assert 'dose_sample' not in result['events'][0]
    assert result['events'][1]['dose_sample']['series_key'] == 'base'
    assert 'private-token' not in str(result) and 'before_geometry' not in str(result)


def test_dose_trends_change_series_when_anatomy_or_prescription_changes():
    before = {'metrics_current':True,'metrics':{'v100':90},'anatomy_key':[1],'config':{'rx':120}}
    after = {**before,'metrics':{'v100':91}}
    current = dose_comparison(before,after)
    assert current['comparable']
    changed = dose_comparison(after,{**after,'config':{'rx':130}})
    assert not changed['comparable'] and current['series_key'] != changed['series_key']
    other_plan = dose_comparison(after,{**after,'planning_id':'another-plan'})
    assert current['series_key'] != other_plan['series_key']
    assert dose_comparison(after,{**after,'anatomy_key':None})['series_key'] is None


@pytest.mark.parametrize('segments, expected', [
    (([0,0,0],[10,0,0],[5,-2,0],[5,2,0]), 0),
    (([0,0,0],[10,0,0],[0,3,0],[10,3,0]), 3),
    (([0,0,0],[0,0,0],[2,0,0],[2,0,0]), 2),
    (([3,2,0],[3,2,0],[0,0,0],[10,0,0]), 2),
    (([0,0,0],[1,0,0],[3,2,0],[5,2,0]), 8 ** .5),
])
def test_spacing_witness_matches_finite_segment_check(segments,expected):
    import math
    from web.server_support import _segment_segment_closest_points, _segment_segment_distance
    a,b = _segment_segment_closest_points(*segments)
    assert math.dist(a,b) == pytest.approx(expected)
    assert _segment_segment_distance(*segments) == pytest.approx(expected)


def test_seed_annotation_measures_axes_not_centroid_distance():
    import math
    from web.server_support import _seed_interference_report
    seeds = [{'id':'a','position':[0,0,0],'direction':[0,0,1]},
             {'id':'b','position':[0,0,4.7],'direction':[0,0,1]}]
    pair = _seed_interference_report(agent(),seeds,[])['close_pairs'][0]
    measurement = pair['measurement']
    assert measurement['coordinate_system'] == 'patient_world_mm'
    assert math.dist(*measurement['points']) == pytest.approx(measurement['value_mm'])
    assert measurement['value_mm'] != pair['center_distance_mm']
    assert measurement['surface_clearance_mm'] == pytest.approx(pair['surface_clearance_mm'],abs=.001)


def test_compact_timeline_checks_run_and_never_copies_full_case_bridge(monkeypatch):
    from flask import Flask
    from web.routes import planning_routes as routes
    monkeypatch.setattr(routes,'require_api_key',lambda f:f)
    monkeypatch.setattr(routes,'rate_limit',lambda f:f)
    monkeypatch.setattr(routes,'current_user',lambda store:{'id':'test-user'})
    store = SimpleNamespace(get_session=lambda user,case:SimpleNamespace(id=case))
    bucket = {'training':{'active':True,'run_id':'run', 'events':[
        {'event_id':str(i),'type':'ui.slider','detail':{'large':list(range(1000))}} for i in range(90)]}}
    monkeypatch.setattr(routes,'_ui_bucket',lambda sid:bucket)
    def forbidden(*args,**kwargs):
        raise AssertionError('compact timeline must not hydrate/copy the whole bridge')
    monkeypatch.setattr(routes._server_support,'_ui_bridge_snapshot',forbidden)
    app = Flask(__name__); app.secret_key='test'; app.extensions['brachybot_workspace_store']=store
    routes.register_planning_routes(app,forbidden,get_cached_agent=forbidden)
    client = app.test_client(); headers={'X-BrachyBot-Session':'case'}
    response = client.get('/api/training/timeline?compact=1&limit=3&monitor_run_id=run',headers=headers)
    assert response.status_code == 200
    result = response.get_json()
    assert result['returned_event_count'] == 3 and result['event_count'] == 90
    assert 'large' not in str(result) and result['monitor_run_id'] == 'run'
    assert client.get('/api/training/timeline?compact=1&monitor_run_id=other',headers=headers).status_code == 409
    assert client.get('/api/training/timeline?compact=1&limit=bad',headers=headers).status_code == 400


@pytest.mark.parametrize('busy', [False, True])
def test_status_overview_is_opt_in_bounded_and_never_waits_for_dose_job(monkeypatch, busy):
    from flask import Flask
    from uuid import uuid4
    from web.routes import planning_routes as routes
    from web import server_support as support
    sid = 'monitor-dashboard-' + uuid4().hex
    store = SimpleNamespace(get_session=lambda user, case: SimpleNamespace(id=case), save_ui_bridge=lambda *a, **k: None)
    monkeypatch.setattr(routes, 'require_api_key', lambda f:f)
    monkeypatch.setattr(routes, 'rate_limit', lambda f:f)
    monkeypatch.setattr(routes, 'current_user', lambda store:{'id':'test-user'})
    attempts = []
    lock = SimpleNamespace(acquire=lambda **kw: attempts.append(kw) or not busy, release=lambda:None)
    monkeypatch.setattr(routes, '_manual_dose_transaction_lock', lambda sid:lock)
    app = Flask(__name__)
    app.secret_key = 'test'
    app.extensions['brachybot_workspace_store'] = store
    def forbidden(*args, **kwargs):
        raise AssertionError('status must not hydrate a case')
    routes.register_planning_routes(app, forbidden, get_cached_agent=lambda sid:None)
    try:
        client = app.test_client()
        headers = {'X-BrachyBot-Session':sid}
        assert 'overview' not in client.get('/api/training/status', headers=headers).get_json()
        response = client.get('/api/training/status?overview=1', headers=headers)
        assert response.status_code == 200
        value = response.get_json()
        assert value['overview']['available'] is False
        assert value['overview']['metrics'] == {}
        assert attempts == [{'blocking':False}]
        assert 'events' not in value
    finally:
        routes._flush_ui_bridge_checkpoint(('test-user',sid))
        support._drop_ui_bucket(sid)
