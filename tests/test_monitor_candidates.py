"""Counterexamples for bounded, non-mutating Monitor candidate generation."""
import copy
from types import SimpleNamespace

import pytest

from web.monitor_candidates import seed_spacing_candidates
from web import server_support as support
from web.routes.planning_routes import _normalize_manual_seed_records


def fixture():
    geometry = {'seeds': [dict(id='a',position=[0,0,5],direction=[0,0,1],trajectory_id='t'),
                          dict(id='b',position=[0,0,6],direction=[0,0,1],trajectory_id='t')],
                'needles': [dict(id='n',trajectory_id='t',points=[[0,0,0],[0,0,30]])]}
    memory = SimpleNamespace(retrieve=lambda key: {} if key == 'plan_config' else None)
    agent = SimpleNamespace(memory=memory)
    evidence = {'changed_objects':[dict(id='b',kind='seeds',operation='moved')],
                'conflicts':[dict(first_id='a',second_id='b',change='new')]}
    kwargs = dict(normalize=lambda seeds, needles: _normalize_manual_seed_records(memory,seeds,needles),
                  spacing=lambda seeds, needles, ref: support._seed_interference_report(agent,seeds,needles,focus_ids={ref},max_pairs=None),
                  contains=lambda seed: True)
    return geometry, evidence, kwargs


def test_actual_normalizer_and_finite_spacing_find_verified_axial_candidate_without_mutation():
    geometry, evidence, kwargs = fixture()
    original = copy.deepcopy(geometry)
    result = seed_spacing_candidates(geometry,evidence,'b',**kwargs)
    assert result['candidates'], result
    assert geometry == original
    for candidate in result['candidates']:
        assert candidate['position'][:2] == [0,0]
        assert candidate['distance_mm'] <= 4
        assert candidate['dose_status'] == 'not_computed'
        assert candidate['clinical_status'] == 'not_assessed'
        seeds = copy.deepcopy(geometry['seeds']); seeds[1]['position'] = candidate['position']
        assert kwargs['spacing'](seeds,geometry['needles'],'b')['status'] == 'clear'


def test_unrelated_seed_normalization_change_cannot_be_smuggled_into_local_candidate():
    geometry, evidence, kwargs = fixture()
    normalize = kwargs['normalize']
    calls = [0]
    def bad(seeds, needles):
        result = normalize(seeds,needles); calls[0] += 1
        if calls[0] > 1: result[0]['position'][0] += 1
        return result
    kwargs['normalize'] = bad
    assert not seed_spacing_candidates(geometry,evidence,'b',**kwargs)['candidates']


@pytest.mark.parametrize('reason', ['missing_target', 'invalid_report', 'other_conflict', 'empty_entries'])
def test_no_positive_placeholder_for_missing_validation(reason):
    geometry, evidence, kwargs = fixture()
    if reason == 'missing_target': kwargs['contains'] = lambda seed: False
    elif reason == 'invalid_report': kwargs['spacing'] = lambda *args: None
    elif reason == 'other_conflict': kwargs['spacing'] = lambda *args: {'status':'attention','close_pairs':[{'first_id':'b','second_id':'c'}]}
    else: kwargs['spacing'] = lambda *args: {'status':'unavailable','close_pairs':[]}
    assert not seed_spacing_candidates(geometry,evidence,'b',**kwargs)['candidates']


@pytest.mark.parametrize('patch', ['duplicate','nan','needle_missing','dependent','unrelated','no_conflicts'])
def test_invalid_or_unrelated_geometry_fails_closed(patch):
    geometry,evidence,kwargs=fixture()
    if patch == 'duplicate': geometry['seeds'].append(copy.deepcopy(geometry['seeds'][0]))
    if patch == 'nan': geometry['seeds'][1]['position'][0]=float('nan')
    if patch == 'needle_missing': geometry['needles']=[]
    if patch == 'dependent': evidence['changed_objects'][0]['dependent_on_needle']=True
    if patch == 'unrelated': evidence['changed_objects'][0]['id']='another'
    if patch == 'no_conflicts': evidence['conflicts']=[]
    assert not seed_spacing_candidates(geometry,evidence,'b',**kwargs)['candidates']


def test_search_deadline_stops_without_inventing_an_answer():
    geometry,evidence,kwargs=fixture()
    result=seed_spacing_candidates(geometry,evidence,'b',budget_seconds=0,**kwargs)
    assert result['reason']=='search_budget_exhausted'
    assert result['candidates']==[] and result['evaluations']==0


def test_bad_normalization_baseline_cannot_move_the_original_plan():
    geometry,evidence,kwargs=fixture()
    geometry['seeds'][0]['position']=[2,0,5]
    result=seed_spacing_candidates(geometry,evidence,'b',**kwargs)
    assert result['reason']=='geometry_requires_normalization'


def test_summary_prioritizes_actual_oar_changes_and_discloses_multi_edit_scope():
    from web.monitor_changes import interaction
    dose={'comparable':True,'edit_count':3,'before':{'v100':90,'v200':20,'plan_score':80},
          'after':{'v100':91,'v200':22,'plan_score':82},'delta':{'v100':1,'v200':2,'plan_score':2},
          'oar_changes':[{'organ':'cord','metric':'dmax','before':1,'after':2,'delta':1}]}
    result=interaction({'dose':dose},'en')
    assert result['decision_required'] is False
    assert result['primary_action']=='details'
    assert result['assessment']['attribution']=='edit_sequence'
    assert 'cord dmax' in result['assessment']['title']
    assert 'plan_score' not in result['assessment']['title']
    assert result['assessment']['clinical_status']=='not_assessed'


def test_read_preview_does_not_schedule_heavy_workspace_checkpoint_but_apply_does():
    from web.server import WORKSPACE_READ_ONLY_POST_PATHS, WORKSPACE_PATCH_ONLY_PATHS
    assert '/api/training/edit_preview' in WORKSPACE_READ_ONLY_POST_PATHS
    assert '/api/training/apply_candidate' not in WORKSPACE_READ_ONLY_POST_PATHS
    assert '/api/training/apply_candidate' not in WORKSPACE_PATCH_ONLY_PATHS
