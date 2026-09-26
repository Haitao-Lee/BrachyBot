from types import SimpleNamespace

import pytest

from web.monitor_changes import overview, interaction


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
