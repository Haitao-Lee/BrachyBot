"""Synthetic identity, completeness and no-write dosimetry contracts."""
from types import SimpleNamespace

import numpy as np
import pytest
import SimpleITK as sitk

from web.structure_dvh import complete_structure_analysis, _sample
from tool_factory.dose_eval.dvh_utils import build_cumulative_dvh


class Memory:
    def __init__(self):
        image = sitk.Image([4, 3, 2], sitk.sitkInt16)
        image.SetSpacing([1, 2, 3])
        self.values = {'ct_image': image, 'ctv_source': 'manual_label',
                       'organ_names': {7: 'left', 8: 'right'}, 'ctv_label_map': {1: 'primary', 2: 'node'}}
        self._planning_versions = {}

    def retrieve(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture
def fixture():
    agent = SimpleNamespace(memory=Memory())
    ctv = np.ones((2, 3, 4), np.uint8)
    ctv[1] = 2
    oar = np.full_like(ctv, 7, dtype=np.uint16)
    oar[1] = 8
    dose = np.arange(24, dtype=float).reshape(ctv.shape)
    context = {'source_planning_id': 'plan', 'source': 'current', 'stale': False,
               'dvh': {'CTV': build_cumulative_dvh(dose, anchor_doses=[12])},
               'metrics': {'prescription_gy': 12}}
    calls = []

    def labels(*_):
        calls.append('labels')
        return ctv, oar, None, {}, {}, {}

    def doses(*_):
        calls.append('dose')
        return dose

    def run():
        return complete_structure_analysis(agent, context, 1, label_resolver=labels, dose_resolver=doses)

    return agent, context, ctv, oar, dose, calls, run


def test_all_children_plus_union_and_all_oars_with_stable_ids(fixture):
    agent, context, _, _, _, _, run = fixture
    before = dict(agent.memory.values)
    result = run()
    assert result['coverage']['status'] == 'complete'
    assert result['coverage']['expected'] == result['coverage']['available'] == 4
    assert len(result['dvh']) == 5  # Four objects plus the distinct union.
    assert set(result['oar_metrics']) == {'structure:oar:7', 'structure:oar:8'}
    assert result['dvh']['CTV']['is_union'] is True
    assert result['dvh']['CTV']['dose_bins'] == context['dvh']['CTV']['dose_bins']
    assert agent.memory.values == before


def test_saved_curves_and_metrics_reused_without_new_inference(fixture):
    _, context, _, _, dose, calls, run = fixture
    curve = build_cumulative_dvh(dose[0])
    context['dvh']['left'] = curve
    context['metrics']['oar_metrics'] = {'left': {'label_id': 7, 'd2cc': 123}}
    result = run()
    assert result['dvh']['structure:oar:7']['dose_bins'] == curve['dose_bins']
    assert result['oar_metrics']['structure:oar:7']['d2cc'] == 123
    assert calls.count('dose') == 1  # Missing structures share one saved field.


def test_duplicate_names_and_cross_family_numeric_labels_do_not_collapse(fixture):
    agent, _, _, oar, _, _, run = fixture
    agent.memory.values['organ_names'] = {7: 'same', 8: 'same'}
    oar[0] = 1
    result = run()
    assert len(result['dvh']) == 5
    assert 'structure:ctv:1' in result['dvh']
    assert 'structure:oar:1' in result['dvh']


def test_stale_dose_does_not_generate_current_missing_curves(fixture):
    _, context, _, _, _, calls, run = fixture
    context['stale'] = True
    result = run()
    assert result['coverage']['status'] == 'stale'
    assert result['coverage']['available'] == 0
    assert 'dose' not in calls
    assert all('d90' not in row for row in result['oar_metrics'].values())


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -1])
def test_invalid_dose_is_unassessed_not_zero(fixture, bad):
    _, _, _, _, dose, _, run = fixture
    dose[:] = bad
    result = run()
    assert result['coverage']['available'] == 0
    assert all(row['reason'] == 'dose_grid_unavailable' for row in result['coverage']['structures'])


def test_cache_is_case_owned_and_invalidated_by_revision(fixture):
    agent, _, _, _, _, calls, run = fixture
    first = run()
    assert run() is first
    assert calls.count('labels') == 1
    agent.memory._planning_versions['ctv_array'] = 2
    assert run() is not first
    assert calls.count('labels') == 2


def test_changed_input_during_sampling_is_rejected(fixture):
    agent, context, ctv, oar, dose, _, _ = fixture
    def doses(*_):
        agent.memory._planning_versions['oar_array'] = 1
        return dose
    with pytest.raises(ValueError, match='changed during sampling'):
        complete_structure_analysis(agent, context, 1,
            label_resolver=lambda *_: (ctv, oar, None, {}, {}, {}), dose_resolver=doses)


def test_single_ctv_reuses_union_without_duplicate(fixture):
    _, _, ctv, _, _, _, run = fixture
    ctv[:] = 1
    result = run()
    assert len(result['dvh']) == 3
    assert result['dvh']['CTV']['object_id'] == 'structure:ctv:1'


def test_same_named_overwritten_legacy_curve_is_not_used_twice(fixture):
    agent, context, _, _, dose, _, run = fixture
    agent.memory.values['organ_names'] = {7: 'same', 8: 'same'}
    context['dvh']['same'] = build_cumulative_dvh(dose[1])
    context['metrics']['oar_metrics'] = {'same': {'label_id': 8, 'd2cc': 99}}
    result = run()
    assert result['oar_metrics']['structure:oar:7']['d2cc'] != 99
    assert result['oar_metrics']['structure:oar:8']['d2cc'] == 99


def test_pancreatic_anatomy_is_not_a_ctv_child(fixture):
    agent, _, _, _, _, _, run = fixture
    agent.memory.values['ctv_source'] = 'nnunet_pancreatic'
    result = run()
    assert not any(row['classification'] == 'ctv' and row['label_id'] == 2 for row in result['coverage']['structures'])


@pytest.mark.parametrize('rx', [12, 0.5, 120])
def test_sampled_curve_uses_exact_ge_threshold_and_physical_voxel_volume(rx):
    values = np.array([0, rx, rx, 2 * rx])
    curve, metrics = _sample(values, [1, 2, 3], rx)
    assert curve['volume_pcts'][curve['dose_bins'].index(rx)] == 75
    assert metrics['v100'] == .75
    assert metrics['volume_cm3'] == .024
    assert metrics['d90'] == 0


def test_route_rejects_other_plan_before_sampling(fixture, monkeypatch):
    from flask import Flask
    from web.routes import planning_routes as routes
    agent = fixture[0]
    monkeypatch.setattr(routes, 'require_api_key', lambda f: f)
    monkeypatch.setattr(routes, 'rate_limit', lambda f: f)
    agent._workspace_data_ready = True
    monkeypatch.setattr(routes, 'active_planning_id', lambda _: 'plan')
    app = Flask(__name__)
    app.secret_key = 'synthetic'
    routes.register_planning_routes(app, lambda **_: agent)
    result = app.test_client().get('/api/planning/structure-analysis?planning_id=old')
    assert result.status_code == 409


@pytest.mark.parametrize('key', ['dose_distribution_gy', 'dose_distribution_physical_gy', 'dose_distribution'])
def test_actual_route_and_label_resolver_complete_physical_dose_on_all_supported_grids(fixture, monkeypatch, key):
    from flask import Flask
    from web.routes import planning_routes as routes
    agent, _, ctv, oar, dose, _, _ = fixture
    agent._workspace_data_ready = True
    agent._get_label_array = lambda key: agent.memory.retrieve(key)
    agent.memory.values.update(ctv_array=ctv, ctv_full_labels=ctv,
        ctv_source='nnunet_head_neck_gtv', oar_array=oar, oar_source='uploaded_unknown',
        resampled_ct=agent.memory.retrieve('ct_image'),
        dose_metrics={'prescription_gy': 12, 'dose_scale_gy': 2, 'dose_value_unit': 'gy'})
    agent.memory.values[key] = dose * 2 if key == 'dose_distribution_physical_gy' else dose
    monkeypatch.setattr(routes, 'require_api_key', lambda f: f)
    monkeypatch.setattr(routes, 'rate_limit', lambda f: f)
    monkeypatch.setattr(routes, 'active_planning_id', lambda _: 'plan')
    monkeypatch.setattr(routes, '_active_planning_run_metadata', lambda _: {})
    app = Flask(__name__)
    app.secret_key = 'synthetic'
    routes.register_planning_routes(app, lambda **_: agent)
    response = app.test_client().get('/api/planning/structure-analysis?planning_id=plan')
    assert response.status_code == 200, response.json
    assert response.json['coverage']['expected'] == response.json['coverage']['available'] == 4
    assert response.json['oar_metrics']['structure:oar:7']['dmax'] == 22
    assert 'structure:ctv:2' in response.json['dvh']
    assert not response.json['dose_stale']


def test_partial_saved_oar_metrics_are_completed_but_existing_values_preserved(fixture):
    _, context, _, _, dose, _, run = fixture
    context['dvh']['left'] = build_cumulative_dvh(dose[0])
    context['metrics']['oar_metrics'] = {'left': {'label_id': 7, 'd2cc': 123, 'd90': None}}
    metric = run()['oar_metrics']['structure:oar:7']
    assert metric['d2cc'] == 123
    assert metric['d90'] == 1
    assert 'd90' in metric['computed_fields']


def test_individual_registry_roi_not_truncated_by_overlapping_transport_labels(fixture):
    agent, context, ctv, oar, dose, _, _ = fixture
    from web.structure_service import EffectiveStructures
    own_mask = np.ones_like(oar, dtype=bool)
    effective = EffectiveStructures(ctv, oar, {1:'primary',2:'node'}, {7:'left',8:'right'}, {},
        [{'classification':'oar','target_label':7,'object_id':'own-roi','name':'left','mask':own_mask}])
    result = complete_structure_analysis(agent, context, 1,
        label_resolver=lambda *_:(ctv, oar, effective, {}, {7:'own-roi'}, {}), dose_resolver=lambda *_:dose)
    assert result['oar_metrics']['own-roi']['volume_voxels'] == 24


def test_spacing_change_invalidates_cached_physical_volume(fixture):
    agent, _, _, _, _, _, run = fixture
    first = run()['oar_metrics']['structure:oar:7']['volume_cm3']
    agent.memory.retrieve('ct_image').SetSpacing([2,2,3])
    assert run()['oar_metrics']['structure:oar:7']['volume_cm3'] == first * 2


def test_reserved_oar_name_does_not_masquerade_as_ctv_union(fixture):
    agent, context, _, _, dose, _, run = fixture
    agent.memory.values['organ_names'][7] = 'CTV'
    context['dvh']['CTV'] = build_cumulative_dvh(dose[0])
    context['metrics']['oar_metrics'] = {'CTV': {'label_id':7,'d2cc':123}}
    result = run()
    assert result['dvh']['CTV']['object_id'] == 'analysis:ctv_union'
    assert result['oar_metrics']['structure:oar:7']['d2cc'] == 123
    assert result['dvh']['structure:ctv:1']['object_id'] == 'structure:ctv:1'


def test_recycled_label_does_not_reuse_explicitly_different_object_curve(fixture):
    _, context, _, _, dose, _, run = fixture
    context['dvh']['left'] = {**build_cumulative_dvh(dose[1]), 'object_id':'deleted-roi'}
    context['metrics']['oar_metrics'] = {'left': {'label_id':7,'object_id':'deleted-roi','d2cc':123}}
    result = run()
    assert result['oar_metrics']['structure:oar:7']['d2cc'] != 123


@pytest.mark.parametrize('missing_family', ['oar','ctv','both'])
def test_mask_sidecar_hydration_cannot_claim_partial_registry_complete(fixture, missing_family):
    agent, context, ctv, oar, dose, _, _ = fixture
    context['dvh']['left'] = build_cumulative_dvh(dose[0])
    context['metrics']['oar_metrics'] = {'left': {'label_id':7,'d2cc':1}}
    result = complete_structure_analysis(agent, context, 1,
        label_resolver=lambda *_:(None if missing_family in {'ctv','both'} else ctv,
                                 None if missing_family in {'oar','both'} else oar, None, {}, {}, {}),
        dose_resolver=lambda *_:dose)
    assert result['coverage']['status'] == 'unavailable'
    assert any(curve.get('label_id') == 7 or key == 'left' for key,curve in result['dvh'].items())
    rows = [metric for metric in result['oar_metrics'].values() if metric.get('label_id') == 7]
    assert len(rows) == 1 and rows[0]['d2cc'] == 1

