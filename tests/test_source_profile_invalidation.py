"""Numerical-source changes invalidate authority without modifying source facts."""
import numpy as np
from web.source_profile_invalidation import source_profile_invalidation


def test_source_profile_change_invalidates_all_components_but_preserves_history_and_geometry():
    results = {'dose_distribution_physical_gy': np.full((2,2,2),90.,np.float32),
        'dose_components': {name: {'status':'ready','source_count':1} for name in ('implanted','planned','total')},
        'implanted_dose_record': {'dose_status':'ready'}, 'total_dose_evaluation': {'metrics':{'v100':1.}},
        'manual_seeds': [{'id':'future'}], 'implanted_seed_reconstruction': {'revision_id':'observed'},
        'surgical_guide': {'geometry_id':'printed'}, 'planning_run:old': {'dose':90.},
        'planning_runs': [{'planning_id':'old','status':'completed'}], 'report_result':'historical report'}
    updates = source_profile_invalidation(results)
    assert updates['dose_distribution_physical_gy'] is None
    assert updates['total_dose_evaluation'] is None and updates['report_result'] is None
    assert all(row['status']=='stale' for row in updates['dose_components'].values())
    assert updates['implanted_dose_record']['dose_status']=='stale'
    assert updates['planning_runs'][0]['clinical_inputs_current'] is False
    assert updates['manual_artifact_status']['dose']=='stale'
    for key in ('manual_seeds','implanted_seed_reconstruction','surgical_guide','planning_run:old'):
        assert key not in updates
    assert results['dose_components']['total']['status']=='ready'
    assert np.all(results['dose_distribution_physical_gy']==90.)


def test_first_source_confirmation_without_downstream_data_does_not_invent_a_plan():
    assert source_profile_invalidation({'ctv_binary_array':np.ones((2,2,2),np.uint8)}) == {}
