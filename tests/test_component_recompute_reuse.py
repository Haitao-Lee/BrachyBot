"""Dose-only reuse, source correction and unavailable-anatomy negative controls."""
from contextlib import nullcontext
from types import SimpleNamespace
import copy
import hashlib
import numpy as np
import pytest
import SimpleITK as sitk

from agent_runtime.core import AgentMemory
from web.dose_components import (dose_component, component_bundle, recompute_timepoint_dose,
                                 evaluate_total, total_evaluation_updates)
from web.timepoint_resources import capture_resources, component_current, resource_state


@pytest.fixture
def case(tmp_path, monkeypatch):
    from plans.dose_pre import model_loader
    import web.implant_workspace as workspace
    from web.routes import planning_routes
    image = sitk.GetImageFromArray(np.zeros((4, 5, 6), np.int16))
    image.SetSpacing((.8, 1.2, 2.1))
    checkpoint = tmp_path / 'inert-checkpoint.pth'
    checkpoint.write_bytes(b'not a model; injected inference only')
    sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    memory = AgentMemory('a' * 32)
    source = {'id': 'future-1', 'position': [1.6, 2.4, 4.2], 'direction': [0, 0, 1]}
    for key, value in dict(ct_image=image, ct_data=sitk.GetArrayFromImage(image),
        ctv_binary_array=np.ones((4, 5, 6), np.uint8), oar_array=np.ones((4, 5, 6), np.uint8),
        organ_names={1: 'bladder'}, plan_config={'seed_info': {'length': 1., 'radius': .2},
            'dose_scale_gy': 120., 'prescription_gy': 90., 'oar_constraints': {'bladder': {'max_dose': 80.}}},
        manual_seeds=[source], manual_plan_active=True, dose_scale_gy=120.).items():
        memory.store(key, value)
    context = SimpleNamespace(target=SimpleNamespace(stage='preoperative', legacy_default=False, clinical_revision=1))
    writes = []
    store = SimpleNamespace(capture_timepoint_context=lambda *a: context,
        save_timepoint_results=lambda *a, **k: writes.append((a, k)))
    agent = SimpleNamespace(memory=memory, _workspace_store=store,
        config={'_workspace_owner_id': 'owner', '_workspace_session_id': 'a' * 32, '_workspace_timepoint_id': 'b' * 32})
    monkeypatch.setattr(model_loader, 'resolve_dose_model_path', lambda *a: checkpoint)
    monkeypatch.setattr(workspace, 'implant_publication_guard', lambda *a: nullcontext())
    monkeypatch.setattr(planning_routes, '_current_planning_snapshot', lambda a: {'seeds': a.memory.retrieve('manual_seeds'), 'needles': []})
    calls = []
    from tool_factory.seed_plan import model_support
    def compute(sources, ct, model, dl, info, strict):
        assert strict and ct.GetSpacing() == image.GetSpacing()
        calls.append(copy.deepcopy(sources))
        return np.full(ct.GetSize()[::-1], .75, np.float32), sources
    monkeypatch.setattr(model_support, 'compute_world_seed_dose_grid', compute)
    return agent, calls, writes, image, sha


def test_recompute_total_then_reuse_both_numeric_and_metrics_without_inference(case):
    agent, calls, writes, _, _ = case
    first = recompute_timepoint_dose(agent, model=object())
    assert first.success, first.error
    assert len(calls) == 1 and len(writes) == 1
    assert agent.memory.retrieve('dose_metrics')['v100'] == 1
    assert np.all(agent.memory.retrieve('dose_distribution_gy') == 90.)
    assert np.all(agent.memory.retrieve('dose_distribution_current_normalized') == .75)
    assert agent.memory.retrieve('total_dose_evaluation')['oar_violations'][0]['actual'] == 90.
    second = recompute_timepoint_dose(agent, model=object())
    assert second.success, second.error
    assert len(calls) == 1
    assert 'planned' in second.metadata['reused_components']
    assert 'metrics' in second.metadata['reused_components']


@pytest.mark.parametrize('rx_key', [
    'prescription_gy', 'prescription_dose_gy', 'prescribed_dose_gy', 'rx_gy'])
def test_prescription_change_reuses_dose_but_recomputes_total_quality(case, rx_key):
    agent, calls, _, _, _ = case
    plan = agent.memory.retrieve('plan_config')
    plan.pop('prescription_gy')
    plan[rx_key] = 90.
    plan['tumor_type'] = 'prostate'
    assert recompute_timepoint_dose(agent, model=object()).success
    before = agent.memory.retrieve('timepoint_resource_state')['fingerprints'].copy()
    old_score = agent.memory.retrieve('dose_metrics')['plan_score']
    assert old_score is not None
    assert agent.memory.retrieve('dose_metrics')['v100'] == 1.
    plan[rx_key] = 120.
    result = recompute_timepoint_dose(agent, model=object())
    assert result.success, result.error
    after = agent.memory.retrieve('timepoint_resource_state')['fingerprints']
    assert len(calls) == 1 and 'planned' in result.metadata['reused_components']
    assert 'metrics' not in result.metadata['reused_components']
    for key in ('implanted_dose', 'planned_dose', 'total_dose'):
        assert before[key] == after[key]
    assert before['metrics'] != after['metrics'] and before['report'] != after['report']
    metrics = agent.memory.retrieve('dose_metrics')
    assert metrics['prescription_gy'] == 120. and metrics['v100'] == 0.
    assert metrics['plan_score'] != old_score
    assert np.all(agent.memory.retrieve('dose_distribution_physical_gy') == 90.)


@pytest.mark.parametrize('unit_key', ['dose_value_unit', 'planning_dose_unit'])
@pytest.mark.parametrize('new_unit', ['rx', 'physical_gy'])
def test_prescription_unit_change_reuses_dose_but_recomputes_total_quality(case, unit_key, new_unit):
    agent, calls, _, _, _ = case
    plan = agent.memory.retrieve('plan_config')
    plan.pop('prescription_gy')
    plan.update(in_lowest_energy=.75)
    plan[unit_key] = 'gy'
    assert recompute_timepoint_dose(agent, model=object()).success
    before = agent.memory.retrieve('timepoint_resource_state')['fingerprints'].copy()
    assert agent.memory.retrieve('dose_metrics')['prescription_gy'] == .75
    plan[unit_key] = new_unit
    result = recompute_timepoint_dose(agent, model=object())
    assert result.success, result.error
    after = agent.memory.retrieve('timepoint_resource_state')['fingerprints']
    from plans.dose_pre.model_loader import DEFAULT_PRESCRIPTION_GY
    expected_rx = .75 * DEFAULT_PRESCRIPTION_GY if new_unit == 'rx' else .75
    assert agent.memory.retrieve('dose_metrics')['prescription_gy'] == expected_rx
    assert len(calls) == 1 and 'metrics' not in result.metadata['reused_components']
    assert before['total_dose'] == after['total_dose'] and before['metrics'] != after['metrics']


def test_recomputed_total_restores_current_quality_after_manual_invalidation(case):
    from web.planning_runs import current_planning_context
    from tool_factory.report_facts import resolve_report_facts
    agent,*_=case
    agent.memory.store('manual_artifact_status',{'dose':'stale','dvh':'stale','quality_check':'stale','report':'stale'})
    assert recompute_timepoint_dose(agent,source_set='total',model=object()).success
    assert agent.memory.retrieve('manual_artifact_status')['quality_check']=='ready'
    assert current_planning_context(agent.memory)['metrics']['v100']==1.
    assert resolve_report_facts(agent.memory)['dose']['source_set']=='total'
    assert agent.memory.retrieve('manual_artifact_status')['report']=='stale'


@pytest.mark.parametrize('key', ['ctv_binary_array', 'oar_array'])
def test_removed_anatomy_retains_dose_but_clears_all_quality(case, key):
    agent, calls, _, _, _ = case
    assert recompute_timepoint_dose(agent, model=object()).success
    agent.memory.store(key, None)
    result = recompute_timepoint_dose(agent, model=object())
    assert result.success, result.error
    assert len(calls) == 1 and result.metadata['total_available']
    assert agent.memory.retrieve('dose_metrics') is None
    assert agent.memory.retrieve('dvh_data') is None
    assert agent.memory.retrieve('artifact_status')['dvh'] == 'stale'
    assert agent.memory.retrieve('report_status') == 'stale'


@pytest.mark.parametrize('change', ['position', 'scale', 'image', 'preprocessing'])
def test_semantic_source_inputs_invalidate_inference(case, change):
    agent, calls, _, image, _ = case
    assert recompute_timepoint_dose(agent, model=object()).success
    if change == 'position':
        agent.memory.retrieve('manual_seeds')[0]['position'][0] += .1
    elif change == 'scale':
        agent.memory.retrieve('plan_config')['dose_scale_gy'] = 100.
    elif change == 'image':
        changed = sitk.Image(image); changed[1, 1, 1] = 500
        agent.memory.store('ct_image', changed)
    else:
        agent.memory.retrieve('plan_config')['dl_params'] = {'image_normalize': [-800, 2500, 255]}
    result = recompute_timepoint_dose(agent, model=object())
    assert result.success, result.error
    assert len(calls) == 2


def test_hidden_sources_and_display_color_do_not_invalidate_dose(case):
    agent, calls, _, _, _ = case
    assert recompute_timepoint_dose(agent, model=object()).success
    agent.memory.retrieve('manual_seeds')[0].update(visible=False, color='#112233', opacity=.1)
    agent.memory.store('ui_state', {'background': 'another displayed image'})
    result = recompute_timepoint_dose(agent, model=object())
    assert result.success, result.error
    assert len(calls) == 1 and agent.memory.retrieve('dose_components')['planned']['source_count'] == 1


def test_missing_intraop_observations_cannot_be_assumed_zero(case):
    agent, calls, writes, _, _ = case
    agent._workspace_store.capture_timepoint_context = lambda *a: SimpleNamespace(
        target=SimpleNamespace(stage='intraoperative', legacy_default=False, clinical_revision=1))
    result = recompute_timepoint_dose(agent, model=object())
    assert not result.success and result.metadata['code']=='component_dose_recompute_failed'
    assert 'implanted-source review' in result.error
    assert not calls and not writes


def test_total_requires_explicit_current_oar_even_when_ctv_exists(case):
    agent, _, _, image, sha = case
    resources = capture_resources(agent.memory.retrieve, image, model_sha256=sha)
    old = dose_component('implanted', np.full((4, 5, 6), 60.), image, units='physical_gy', scale=120., resources=resources)
    new = dose_component('planned', np.full((4, 5, 6), 30.), image, units='physical_gy', scale=120., resources=resources)
    bundle = component_bundle(old, new, resources)
    with pytest.raises(ValueError, match='CTV and OAR'):
        evaluate_total(bundle, np.ones((4, 5, 6)), None, image, {})
    old['status'] = 'stale'
    with pytest.raises(ValueError, match='stale'):
        component_bundle(old, new, resources)


def test_reference_identity_change_invalidates_dose_but_display_identity_does_not(case):
    agent, calls, _, _, _ = case
    agent.memory.store('planning_reference_image_id', 'c' * 32)
    assert recompute_timepoint_dose(agent, model=object()).success
    agent.memory.store('display_image_id', 'd' * 32)
    assert recompute_timepoint_dose(agent, model=object()).success and len(calls) == 1
    agent.memory.store('planning_reference_image_id', 'e' * 32)
    assert recompute_timepoint_dose(agent, model=object()).success and len(calls) == 2


def test_malformed_target_does_not_make_cached_source_dose_or_quality_current(case):
    agent, calls, _, _, _ = case
    assert recompute_timepoint_dose(agent, model=object()).success
    agent.memory.store('ctv_binary_array', np.full((4, 5, 6), 2, np.uint8))
    result = recompute_timepoint_dose(agent, model=object())
    assert result.success, result.error
    assert len(calls) == 1
    assert agent.memory.retrieve('dose_metrics') is None
