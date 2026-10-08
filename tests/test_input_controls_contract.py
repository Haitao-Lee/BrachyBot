"""Actual Input contracts on synthetic cases; no production mutation/GPU."""
from types import SimpleNamespace
import numpy as np
import pytest
import SimpleITK as sitk


@pytest.fixture
def agent():
    from agent_runtime.core import AgentMemory
    memory = AgentMemory('synthetic-input-controls')
    image = sitk.GetImageFromArray(np.zeros((8, 8, 8), np.int16))
    mask = np.zeros((8, 8, 8), np.uint8)
    mask[3, 3, 3] = 1
    for key, value in {'ct_image': image, 'ct_data': np.zeros((8, 8, 8)), 'ctv_array': mask,
        'ctv_binary_array': mask, 'oar_array': mask.copy(), 'dose_distribution_gy': np.ones(mask.shape),
        'dose_metrics': {'v100': 0.0}, 'seed_plan_serialized': [{'seeds': [{'position': [3, 3, 3]}]}],
        'manual_needles': [{'id': 'old'}], 'manual_seeds': [{'id': 'old'}],
        'manual_step_outputs': {'stages': [{'step': 'dose_calc'}]}, 'surgical_guide': {'status': 'completed'}}.items():
        memory.store(key, value)
    memory.add_message('user', 'Synthetic conversation must be retained')
    return SimpleNamespace(memory=memory, config={'mode': 'rule_based'})


def test_reset_preserves_inputs_chat_history_and_stays_empty_after_restore(agent):
    from web.input_workflow import reset_current_plan
    from web.planning_runs import active_planning_id, list_planning_runs, reconcile_planning_history
    memory = agent.memory
    old_mask = memory.retrieve('ctv_array')
    old_chat = list(memory.conversation)
    result = reset_current_plan(agent)
    assert result['ctv_segmentation'] and result['oar_segmentation']
    assert not result['seed_planning'] and not result['dose_calc'] and not result['dose_eval']
    assert memory.retrieve('ctv_array') is old_mask
    assert memory.conversation == old_chat
    assert len(list_planning_runs(memory)) == 2
    active = active_planning_id(memory)
    assert memory.retrieve('manual_step_outputs') is None
    assert memory.retrieve('manual_needles') is None
    assert memory.retrieve('surgical_guide') is None
    reconcile_planning_history(memory, recover_running=True)
    assert active_planning_id(memory) == active
    assert memory.retrieve('seed_plan_serialized') is None
    assert memory.retrieve('dose_distribution_gy') is None


@pytest.mark.parametrize('patch', [
    {'seed_info': {'radius': float('nan')}}, {'DVH_rate': 1.2}, {'max_iter': -1},
    {'radiation_array_params': {'maximum_candidate_trajectories': 0}},
    {'reference_direc': [0, 0, 0]}, {'reference_direc': [1, float('inf'), 0]},
    {'distance_filter': {'lower_bound': 10, 'upper_bound': 1}},
    {'in_lowest_dose_gy': float('nan')}, {'mode': 'unknown'},
])
def test_config_rejects_invalid_candidate_without_partial_write(patch):
    from web.input_workflow import validated_config
    current = {'mode': 'rule_based', 'seed_info': {'radius': 0.4}}
    with pytest.raises((ValueError, TypeError)):
        validated_config(current, patch)
    assert current == {'mode': 'rule_based', 'seed_info': {'radius': 0.4}}


def test_zero_observed_metrics_and_zero_dose_are_not_treated_as_missing(agent):
    from web.input_workflow import workflow_state
    agent.memory.store('dose_distribution_gy', np.zeros((8, 8, 8)))
    flags = workflow_state(agent.memory)
    assert flags['dose_calc'] and flags['dose_eval']


@pytest.mark.parametrize('key, value, dose_ready', [
    ('manual_artifact_status', {'dose': 'stale', 'dvh': 'stale'}, False),
    ('manual_artifact_status', {'dose': 'ready', 'dvh': 'expired'}, True),
    ('manual_geometry_only', True, False),
])
def test_retained_reference_dose_never_marks_current_evaluation_complete(agent, key, value, dose_ready):
    from web.input_workflow import workflow_state
    agent.memory.store(key, value)
    flags = workflow_state(agent.memory)
    assert flags['dose_calc'] is dose_ready
    assert flags['dose_eval'] is False
    assert agent.memory.retrieve('dose_distribution_gy') is not None


@pytest.fixture
def client(agent, monkeypatch, tmp_path):
    from flask import Flask
    from web.routes import planning_routes as routes
    monkeypatch.setattr(routes, 'require_api_key', lambda f: f)
    monkeypatch.setattr(routes, 'rate_limit', lambda f: f)
    monkeypatch.setattr(routes, 'current_user', lambda *a: {'id': 'synthetic-owner'})
    store = SimpleNamespace(get_session=lambda *a: SimpleNamespace(id=agent.memory.session_id),
        owns_path=lambda *a: True, schedule_agent_checkpoint=lambda *a, **kw: None)
    app = Flask(__name__)
    app.secret_key = 'synthetic-only'
    app.extensions['brachybot_workspace_store'] = store
    routes.register_planning_routes(app, lambda *a, **kw: agent)
    client = app.test_client()
    client.environ_base['HTTP_X_BRACHYBOT_SESSION'] = agent.memory.session_id
    return client


def test_show_dose_reports_physical_units_without_double_scaling(client, agent):
    response = client.post('/api/planning/show_step', json={'step': 'dose'})
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert data['dose_range'] == [1.0, 1.0]
    assert data['dose_units'] == 'gy' and data['dose_scale_gy'] == 1.0
    assert data['workflow_state']['ctv_segmentation'] is True


def test_config_endpoint_is_atomic_and_persists_valid_update(client, agent):
    response = client.post('/api/config', json={'mode': 'rl', 'DVH_rate': -0.1})
    assert response.status_code == 400
    assert agent.config == {'mode': 'rule_based'}
    response = client.post('/api/config', json={'radiation_array_params': {'maximum_candidate_trajectories': 321, 'backlit_angle': 0.8}})
    assert response.status_code == 200, response.get_json()
    assert agent.config['radiation_array_params']['maximum_candidate_trajectories'] == 321


def test_reset_endpoint_does_not_delete_segmentation_or_chat(client, agent):
    response = client.post('/api/planning/clear', json={})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['workflow_state']['ctv_segmentation']
    assert agent.memory.retrieve('ctv_binary_array') is not None
    assert agent.memory.conversation


def test_structure_replacement_cannot_resurrect_old_plan_on_hydration(agent):
    from web.structure_service import initialize_structure_registry, replace_structure_source
    from web.planning_runs import ensure_planning_history, active_planning_id, reconcile_planning_history
    memory = agent.memory
    initialize_structure_registry(memory)
    ensure_planning_history(memory)
    old = active_planning_id(memory)
    memory.store('ctv_array', np.ones((8, 8, 8), np.uint8))
    replace_structure_source(memory, 'ctv')
    current = active_planning_id(memory)
    assert current != old
    assert memory.retrieve('planning_run:' + old)['seed_plan_serialized']
    reconcile_planning_history(memory, recover_running=True)
    assert active_planning_id(memory) == current
    for key in ('seed_plan_serialized', 'manual_step_outputs', 'manual_seeds', 'manual_needles', 'dose_distribution_gy'):
        assert memory.retrieve(key) is None


def test_input_reset_does_not_wait_and_apply_after_a_concurrent_case_edit(client, agent):
    import threading
    # Use the same identity resolved by the signed/header case path.
    from web.routes.planning_routes import _manual_dose_transaction_lock as route_lock
    # A header binds the selected case. The held edit is on another thread,
    # since a same-thread RLock must remain reentrant for nested model tools.
    held = threading.Event()
    release = threading.Event()
    def edit():
        with route_lock(agent.memory.session_id):
            held.set()
            release.wait(5)
    thread = threading.Thread(target=edit)
    thread.start()
    assert held.wait(2)
    try:
        response = client.post('/api/planning/clear', json={}, headers={'X-BrachyBot-Session': agent.memory.session_id})
        assert response.status_code == 409, response.get_json()
        assert response.get_json()['code'] == 'case_edit_in_progress'
        assert agent.memory.retrieve('dose_metrics') == {'v100': 0.0}
    finally:
        release.set()
        thread.join()


def test_every_input_inline_action_has_a_product_entry_point():
    from pathlib import Path
    import re
    root = Path(__file__).resolve().parents[1]
    html = (root / 'web/app/index.html').read_text()
    panel = html.split('id="panelInput"', 1)[1].split('id="panelMetrics"', 1)[0]
    source = '\n'.join(path.read_text() for path in (root / 'web/app/static/js').glob('brachybot-*.js'))
    api_source = (root / 'web/app/static/js/brachybot-ui-api.js').read_text()
    helpers = api_source.split('const _staticUiHelpers = {', 1)[1].split('\n};', 1)[0]
    assert 'Object.entries(_staticUiHelpers)' in api_source
    actions = set()
    for handler in re.findall(r'\bon(?:click|change|input)="([^"]+)"', panel):
        match = re.match(r'(\w+)\s*\(', handler)
        if match:
            actions.add(match[1])
    assert len(actions) >= 20
    for action in sorted(actions):
        assert re.search(r'\bfunction\s+' + re.escape(action) + r'\s*\(', source) or re.search(
            r'\bwindow\.' + re.escape(action) + r'\s*=', source) or re.search(
            r'^\s+' + re.escape(action) + r'\s*\(', helpers, re.M), action
