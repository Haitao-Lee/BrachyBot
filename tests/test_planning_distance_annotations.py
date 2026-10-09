"""Source/units/ownership contracts for automatic distance annotations."""
from types import SimpleNamespace
import inspect

import numpy as np
import pytest

from web.planning_distance_annotations import build_distance_annotations, distance_annotation_packet
from test_report_plan_tables import Memory


def snapshot():
    return {'needles': [{'id': 'needle_1', 'trajectory_id': 'traj_1', 'points': [[0,0,40],[0,0,-30]]}],
            'seeds': [{'id': 'seed_1_1','trajectory_id':'traj_1','position':[0,0,25]},
                      {'id': 'seed_1_2','trajectory_id':'traj_1','position':[0,0,20]}]}


def guide():
    return {'version': 2, 'planning_id': 'plan', 'planning_version': 3,
            'parameters': {'skin_clearance_mm':1, 'plate_thickness_mm':4, 'sleeve_outward_mm':5},
            'needle_paths': [{'needle_id':'needle_0','trajectory_id':'traj_1','entry_world_mm':[0,0,0], 'direction_world':[0,0,1]}]}


def packet(data=None, **kwargs):
    return build_distance_annotations(data or snapshot(), planning_id='plan', planning_version=3, **kwargs)


def test_seed_depths_are_signed_axial_millimetres_and_not_skin_based():
    result=packet()
    assert [r['tip_distance_mm'] for r in result['records']] == [15,20]
    assert all(r['units']=='mm' and r['visible'] and r['reference']=='needle_tip' for r in result['records'])
    assert result['records'][0]['anchor_world_mm']==[0,0,25]


def test_guide_mouth_is_outer_sleeve_not_skin_or_external_handle():
    row=packet(guide=guide(),guide_current=True)['records'][-1]
    assert row['anchor_world_mm']==[0,0,-10]
    assert row['skin_entry_world_mm']==[0,0,0]
    assert row['tip_distance_mm']==50
    assert row['needle_id']=='needle_1' and row['guide_version']==2
    assert row['anchor_definition']=='generated_primary_sleeve_outer_mouth_axis_center'


def test_rotation_anisotropic_world_coordinates_do_not_use_voxel_spacing():
    data=snapshot(); data['needles'][0]['points']=[[30,20,10],[-30,-40,-50]]
    data['seeds'][0]['position']=[20,10,0]
    row=packet(data)['records'][0]
    assert row['tip_distance_mm']==pytest.approx(10*np.sqrt(3))
    assert row['axis_offset_mm']==pytest.approx(0,abs=1e-10)


@pytest.mark.parametrize('mutate', [
    lambda g:g.update(planning_id='other'), lambda g:g.update(planning_version=2),
    lambda g:g['parameters'].update(plate_thickness_mm=np.nan),
    lambda g:g['parameters'].update(skin_clearance_mm=True),
    lambda g:g['needle_paths'][0].update(entry_world_mm=[1,0,0]),
    lambda g:g['needle_paths'][0].update(direction_world=[0,0,-1]),
    lambda g:g['needle_paths'].append(dict(g['needle_paths'][0])),
    lambda g:g.update(version=0), lambda g:g.update(version=True), lambda g:g.update(version=1.5),
    lambda g:g['parameters'].update(plate_thickness_mm=1e308,sleeve_outward_mm=1e308),
])
def test_invalid_or_wrong_revision_guide_never_invents_an_entry(mutate):
    g=guide();mutate(g); result=packet(guide=g,guide_current=True)
    assert len(result['records'])==2 and result['unavailable']


def test_stale_guide_does_not_hide_current_seed_annotations():
    result=packet(guide=guide(),guide_current=False)
    assert len(result['records'])==2 and all(r['kind']=='seed_tip_distance' for r in result['records'])


def test_stable_ids_preserve_preferences_but_guide_versions_get_new_ids():
    first=packet(guide=guide(),guide_current=True)
    changed=snapshot();changed['seeds'][0]['position']=[0,0,26]
    second=packet(changed,guide=guide(),guide_current=True)
    assert [r['id'] for r in first['records']]==[r['id'] for r in second['records']]
    assert first['geometry_signature']!=second['geometry_signature']
    g=guide();g['version']=3
    assert packet(guide=g,guide_current=True)['records'][-1]['id']!=first['records'][-1]['id']


def test_multiple_guide_ports_are_independently_identified():
    data=snapshot();data['needles'].append({'id':'needle_2','trajectory_id':'traj_2','points':[[2,0,40],[2,0,-30]]})
    g=guide();g['needle_paths'].append({'needle_id':'needle_1','trajectory_id':'traj_2','entry_world_mm':[2,0,0],'direction_world':[0,0,1]})
    rows=packet(data,guide=g,guide_current=True)['records']
    assert len({r['id'] for r in rows})==len(rows)==4


@pytest.mark.parametrize('position', [[np.nan,0,20], [True,0,20]])
def test_invalid_seed_position_is_unavailable_not_zero(position):
    data=snapshot();data['seeds'][0]['position']=position
    result=packet(data)
    assert len(result['records'])==1 and result['unavailable']


def test_duplicate_and_unassigned_seeds_never_get_guessed_owners():
    data=snapshot();data['seeds'].append(dict(data['seeds'][0]))
    data['seeds'].append({'id':'orphan','position':[0,0,30]})
    result=packet(data)
    assert [r['source_object_id'] for r in result['records']]==['seed_1_2']
    assert len(result['unavailable'])==3


def test_beyond_tip_and_off_axis_are_not_clamped_or_snapped():
    data=snapshot();data['seeds'][0]['position']=[2,0,45]
    row=next(r for r in packet(data)['records'] if r['source_object_id']=='seed_1_1')
    assert row['tip_distance_mm']==-5 and row['axis_offset_mm']==2
    assert row['anchor_world_mm']==[2,0,45] and 'off_axis' in row['geometry_flags']


def test_packet_rejects_mid_read_planning_change(monkeypatch):
    memory=Memory(active_planning_id='plan',manual_plan_active=True,manual_seeds=snapshot()['seeds'],manual_needles=snapshot()['needles'],manual_plan_version=3)
    monkeypatch.setattr('web.planning_runs.active_planning_id',lambda m:'plan')
    monkeypatch.setattr('web.surgical_guide._current_guide_record',lambda a:None)
    monkeypatch.setattr('web.surgical_guide.guide_status_payload',lambda a:memory.data.update(manual_plan_version=4) or {})
    with pytest.raises(ValueError,match='changed'):
        distance_annotation_packet(SimpleNamespace(memory=memory))


def test_owned_api_has_no_clinical_or_workspace_write(tmp_path,monkeypatch):
    from web.server import create_app
    app=create_app({'runtime_dir':str(tmp_path/'runtime'),'secret_key':'synthetic-annotations','workspace_maintenance':False})
    handler=inspect.unwrap(app.view_functions['api_planning_distance_annotations'])
    provider=dict(zip(handler.__code__.co_freevars,handler.__closure__))['get_agent']
    memory=Memory(active_planning_id='plan',manual_plan_active=True,manual_seeds=snapshot()['seeds'],manual_needles=snapshot()['needles'],manual_plan_version=3)
    provider.cell_contents=lambda *a,**k:SimpleNamespace(memory=memory)
    monkeypatch.setattr('web.planning_runs.active_planning_id',lambda m:'plan')
    monkeypatch.setattr('web.surgical_guide._current_guide_record',lambda a:None)
    monkeypatch.setattr('web.surgical_guide.guide_status_payload',lambda a:{})
    client=app.test_client()
    assert client.get('/api/planning/distance-annotations').status_code==401
    assert client.post('/api/auth/register',json={'username':'distance_annotations','password':'synthetic-password-123'}).status_code==201
    response=client.get('/api/planning/distance-annotations')
    assert response.status_code==200
    assert len(response.get_json()['distance_annotations']['records'])==2


def test_annotation_workspace_checkpoint_preserves_metadata_and_preferences(tmp_path):
    from web.workspace_store import _ArtifactEncoder,_decode_artifacts
    rows=packet(guide=guide(),guide_current=True)['records'];rows[0].update(visible=False,color='#123456',opacity=.4)
    payload={'viewer':{'annotations':rows},'data_tree':{'annotations':rows}}
    restored=_decode_artifacts(_ArtifactEncoder(tmp_path).encode(payload,'ui'),tmp_path)
    assert restored==payload


def test_guide_revision_changed_mid_read_is_not_published(monkeypatch):
    memory=Memory(active_planning_id='plan',manual_plan_active=True,manual_seeds=snapshot()['seeds'],manual_needles=snapshot()['needles'],manual_plan_version=3)
    g=guide()
    monkeypatch.setattr('web.surgical_guide._current_guide_record',lambda a:{'state':g})
    monkeypatch.setattr('web.surgical_guide.guide_status_payload',lambda a:g.update(version=3) or {})
    with pytest.raises(ValueError,match='changed'):
        distance_annotation_packet(SimpleNamespace(memory=memory))
