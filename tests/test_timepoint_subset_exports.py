"""Actual owned NIfTI/source/observation serializers, not export placeholders."""
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
import numpy as np
import SimpleITK as sitk
from test_timepoint_images_integration import collection, image_file, upload
from agent_runtime.core import AgentMemory
from web.export_service import ExportError, ExportService, validate_export_selections


def agent_for(collection):
    store,owner,sid,tid,service = collection
    memory = AgentMemory(sid)
    memory.planning_results.update(service.planning_reference_bridge(owner,sid,tid))
    return SimpleNamespace(memory=memory,config={'_workspace_timepoint_id':tid})


def test_each_uploaded_acquisition_exports_its_own_grid_and_original_bytes(collection,tmp_path):
    store,owner,sid,tid,service = collection
    original = image_file(tmp_path)[0]
    first = upload(collection,original)['created_image_id']
    later = image_file(tmp_path,'later.nii.gz',1000)[0]
    second = upload(collection,later)['created_image_id']
    agent = agent_for(collection)
    exports = ExportService(store)
    rows = [row for row in exports.catalog(owner,sid,agent) if row.data_type == 'image']
    assert {row.metadata['image_id'] for row in rows} == {first,second}
    selections = validate_export_selections(rows,[{'object_id':'image:ct','format':'nifti'}])
    assert selections[0]['object_id'] == 'image:'+first
    row = next(row for row in rows if row.metadata['image_id'] == second)
    nifti = exports.export_object(owner,sid,agent,row,'nifti',tmp_path/'export')
    actual = sitk.ReadImage(str(nifti))
    expected = sitk.ReadImage(str(later))
    # The stored planning/display frame is canonically oriented to LPI. Its
    # array axes may differ from the acquisition while physical points agree.
    expected = sitk.DICOMOrient(expected,'LPI')
    np.testing.assert_array_equal(sitk.GetArrayFromImage(actual),sitk.GetArrayFromImage(expected))
    np.testing.assert_allclose(actual.GetDirection(),expected.GetDirection())
    np.testing.assert_allclose(actual.GetOrigin(),expected.GetOrigin())
    original_copy = exports.export_object(owner,sid,agent,row,'original',tmp_path/'export-original')
    assert original_copy.read_bytes() == later.read_bytes()


def test_observation_export_does_not_invent_missing_axes_and_capsule_dimensions(collection,tmp_path):
    store,owner,sid,tid,service = collection
    upload(collection,image_file(tmp_path)[0])
    agent = agent_for(collection)
    observations = [{'observation_id':'obs-a','physical_seed_id':'physical-a','center_lps_mm':[4.,5.,6.],
        'axis_lps':[0.,0.,1.],'axis_source':'reviewed_axis','review_status':'accepted',
        'dimensions':{'source_model_id':'explicit-test-source','capsule_length_mm':4.5,'capsule_diameter_mm':.8}},
        {'observation_id':'obs-b','center_lps_mm':[7.,8.,9.],'axis_lps':None,'dimensions':None,'review_status':'review_needed'},
        {'observation_id':'obs-c','center_lps_mm':[10.,11.,12.],'review_status':'rejected'}]
    agent.memory.store('implanted_seed_reconstruction',{'by_timepoint':{tid:{'current':{
        'reconstruction':{'image_ref':{'session_id':sid,'timepoint_id':tid},'observations':observations}}}}})
    exports=ExportService(store)
    rows = [row for row in exports.catalog(owner,sid,agent) if row.data_type == 'implanted_observation']
    assert len(rows) == 2
    uncertain = next(row for row in rows if row.metadata['observation_id'] == 'obs-b')
    assert [fmt.key for fmt in uncertain.formats] == ['json']
    saved = exports.export_object(owner,sid,agent,uncertain,'json',tmp_path/'observations')
    assert json.loads(saved.read_text())['observation']['axis_lps'] is None
    known = next(row for row in rows if row.metadata['observation_id'] == 'obs-a')
    mesh = exports.export_object(owner,sid,agent,known,'stl',tmp_path/'meshes')
    assert mesh.read_bytes().startswith(b'solid') and b'facet normal' in mesh.read_bytes()


def test_current_timepoint_screenshot_catalog_does_not_collect_a_siblings_files(collection,tmp_path):
    store,owner,sid,tid,service = collection
    upload(collection,image_file(tmp_path)[0])
    catalog = store.list_timepoints(owner,sid)
    sibling = store.create_timepoint(owner,sid,'Sibling',expected_revision=catalog['catalog_revision'])['created_timepoint_id']
    images = store.workspace_root(owner,sid)/'screenshots'
    images.mkdir(exist_ok=True)
    (images/(tid+'_current.png')).write_bytes(b'\x89PNG\r\n\x1a\n')
    (images/(sibling+'_different.png')).write_bytes(b'\x89PNG\r\n\x1a\n')
    rows = ExportService(store).catalog(owner,sid,agent_for(collection))
    screenshots = [row for row in rows if row.data_type == 'screenshot']
    assert [Path(row.metadata['source_path']).name for row in screenshots] == [tid+'_current.png']


def test_dose_exports_preserve_separate_physical_components_and_refuse_stale_total(collection,tmp_path):
    from web.dose_components import dose_component,component_bundle
    from web.timepoint_resources import dependency_fingerprints,fingerprint
    store,owner,sid,tid,service = collection
    upload(collection,image_file(tmp_path)[0])
    agent = agent_for(collection)
    agent._workspace_timepoint_context = store.capture_timepoint_context(owner,sid,tid)
    image=agent.memory.retrieve('ct_image')
    leaves={name:fingerprint(name) for name in ('image','observation','source','model','planned_sources','ctv','oar','constraints','guide','needles','guide_profile')}
    resources=dependency_fingerprints(leaves)
    shape=image.GetSize()[::-1]
    old=dose_component('implanted',np.full(shape,60.,np.float32),image,units='physical_gy',scale=190.8,resources=resources)
    new=dose_component('planned',np.full(shape,30.,np.float32),image,units='physical_gy',scale=190.8,resources=resources)
    bundle=component_bundle(old,new,resources)
    agent.memory.store('dose_components',bundle)
    agent.memory.store('timepoint_resource_state',{'fingerprints':resources})
    agent.memory.store('ctv_binary_array',np.ones(shape,np.uint8))
    agent.memory.store('oar_array',np.zeros(shape,np.uint8))
    from web.routes.dose_component_routes import dose_view_packet
    packet,volume=dose_view_packet(agent,'implanted')
    assert packet['metrics']['component_only'] is True
    assert packet['metrics']['d90'] == 60.
    assert np.all(volume == 60.)
    exports=ExportService(store)
    rows=[row for row in exports.catalog(owner,sid,agent) if row.data_type == 'dose_component']
    assert {row.metadata['source_set'] for row in rows} == {'implanted','planned','total'}
    for row in rows:
        path=exports.export_object(owner,sid,agent,row,'nifti',tmp_path/'dose-export')
        volume=sitk.ReadImage(str(path))
        expected={'implanted':60.,'planned':30.,'total':90.}[row.metadata['source_set']]
        assert np.all(sitk.GetArrayFromImage(volume) == expected)
        np.testing.assert_allclose(volume.GetSpacing(),image.GetSpacing())
    bundle['total']['dose_status']='stale'
    current=[row.metadata['source_set'] for row in exports.catalog(owner,sid,agent) if row.data_type == 'dose_component']
    assert 'total' not in current
    bundle['total']['dose_status']='ready'
    agent.memory.store('manual_artifact_status',{'dose':{'status':'stale','stale':True}})
    assert dose_view_packet(agent,'implanted',evaluate_component=False)[0]['stale'] is False
    assert dose_view_packet(agent,'planned',evaluate_component=False)[0]['stale'] is True
    assert dose_view_packet(agent,'total',evaluate_component=False)[0]['metrics']=={}
    current=[row.metadata['source_set'] for row in exports.catalog(owner,sid,agent) if row.data_type=='dose_component']
    assert current==['implanted']


@pytest.fixture
def component_exports(collection, tmp_path):
    from web.dose_components import dose_component, component_bundle
    from web.timepoint_resources import dependency_fingerprints, fingerprint
    store, owner, sid, tid, _ = collection
    upload(collection, image_file(tmp_path)[0])
    agent = agent_for(collection)
    agent._workspace_timepoint_context = store.capture_timepoint_context(owner, sid, tid)
    image = agent.memory.retrieve('ct_image')
    resources = dependency_fingerprints({name: fingerprint(name) for name in (
        'image', 'observation', 'source', 'model', 'planned_sources', 'ctv', 'oar',
        'constraints', 'guide', 'needles', 'guide_profile')})
    sources = [{'id': 'future-1', 'position': [5., 8., 12.], 'direction': [0., 0., 1.],
                'needle_id': 'needle-1', 'trajectory_id': 'trajectory-1'},
               {'id': 'future-2', 'position': [5., 8., 16.], 'direction': [0., 0., 1.],
                'needle_id': 'needle-1', 'trajectory_id': 'trajectory-1'}]
    old = dose_component('implanted', np.full(image.GetSize()[::-1], 60., np.float32), image,
        units='physical_gy', scale=190.8, resources=resources,
        sources=[{'id': 'observed-1', 'position': [6., 8., 12.], 'direction': [0., 0., 1.]}])
    new = dose_component('planned', np.full(image.GetSize()[::-1], 30., np.float32), image,
        units='physical_gy', scale=190.8, resources=resources, sources=sources)
    for key, value in dict(dose_components=component_bundle(old, new, resources),
        timepoint_resource_state={'fingerprints': resources}, manual_plan_active=True,
        manual_seeds=sources, manual_needles=[{'id': 'needle-1', 'trajectory_id': 'trajectory-1',
            'points': [[5., 8., 10.], [5., 8., 20.]]}],
        dose_distribution_gy=np.full(image.GetSize()[::-1], 90., np.float32),
        dose_distribution_physical_gy=np.full(image.GetSize()[::-1], 90., np.float32),
        dose_unit_schema_version=2, dose_unit_metadata={'dose_distribution_gy': 'physical_gy'},
        dose_scale_gy=190.8, plan_config={'prescription_gy': 60., 'dose_scale_gy': 190.8,
            'seed_info': {'length': 3.7, 'radius': .4}}).items():
        agent.memory.store(key, value)
    exports = ExportService(store)
    rows = exports.catalog(owner, sid, agent)
    assert {'dose', 'dose_isosurface', 'dicom_rt'} <= {row.data_type for row in rows}
    return store, owner, sid, agent, exports, rows


def test_generic_dose_exports_are_hidden_after_seed_deletion(component_exports, tmp_path):
    from web.routes.data_routes import _delete_object
    store, owner, sid, agent, exports, rows = component_exports
    _delete_object(store, {'id': owner}, sid, agent, 'seed:future-2')
    assert len(agent.memory.retrieve('manual_seeds')) == 1
    # The old arrays remain present: rejection must use freshness, not absence.
    assert np.all(agent.memory.retrieve('dose_distribution_physical_gy') == 90.)
    current = exports.catalog(owner, sid, agent)
    assert not {'dose', 'dose_isosurface', 'dicom_rt'} & {row.data_type for row in current}
    components = [row for row in current if row.data_type == 'dose_component']
    assert [row.metadata['source_set'] for row in components] == ['implanted']
    saved = exports.export_object(owner, sid, agent, components[0], 'nifti', tmp_path / 'implanted')
    assert np.all(sitk.GetArrayFromImage(sitk.ReadImage(str(saved))) == 60.)
    for row in rows:
        if row.data_type in {'dose', 'dose_isosurface', 'dicom_rt'}:
            with pytest.raises(ExportError, match='stale'):
                exports.export_object(owner, sid, agent, row, row.default_format, tmp_path / 'stale')
    assert not (tmp_path / 'stale').exists()


@pytest.mark.parametrize('data_type', ['dose', 'dose_isosurface', 'dicom_rt'])
@pytest.mark.parametrize('status_key', ['manual_artifact_status', 'artifact_status'])
@pytest.mark.parametrize('stale', ['stale', {'status': 'stale', 'stale': True}])
def test_cached_generic_dose_selection_rechecks_stale_at_execution(
        component_exports, tmp_path, data_type, status_key, stale):
    _, owner, sid, agent, exports, rows = component_exports
    row = next(row for row in rows if row.data_type == data_type)
    # A ready value in the other alias must not hide this invalidation.
    other = 'artifact_status' if status_key == 'manual_artifact_status' else 'manual_artifact_status'
    agent.memory.store(other, {'dose': 'ready'})
    agent.memory.store(status_key, {'dose': stale})
    assert not {'dose', 'dose_isosurface', 'dicom_rt'} & {
        item.data_type for item in exports.catalog(owner, sid, agent)}
    with pytest.raises(ExportError, match='stale'):
        exports.export_object(owner, sid, agent, row, row.default_format, tmp_path / 'cached')
    assert not (tmp_path / 'cached').exists()


@pytest.mark.parametrize('change', ['missing_total', 'stale_total', 'changed_fingerprint'])
def test_generic_dose_exports_reject_invalidated_total_receipt(component_exports, tmp_path, change):
    _, owner, sid, agent, exports, rows = component_exports
    bundle = agent.memory.retrieve('dose_components')
    if change == 'missing_total':
        bundle['total'] = None
    elif change == 'stale_total':
        bundle['total']['dose_status'] = 'stale'
    else:
        agent.memory.retrieve('timepoint_resource_state')['fingerprints']['total_dose'] = 'changed'
    assert not {'dose', 'dose_isosurface', 'dicom_rt'} & {
        row.data_type for row in exports.catalog(owner, sid, agent)}
    for row in rows:
        if row.data_type in {'dose', 'dose_isosurface', 'dicom_rt'}:
            with pytest.raises(ExportError, match='stale'):
                exports.export_object(owner, sid, agent, row, row.default_format, tmp_path / 'invalid')


def test_stale_total_export_error_follows_existing_language_management(component_exports, tmp_path):
    _, owner, sid, agent, exports, rows = component_exports
    agent.memory.user_lang = 'zh'
    agent.memory.store('manual_artifact_status', {'dose': 'stale'})
    row = next(row for row in rows if row.data_type == 'dose')
    with pytest.raises(ExportError, match='总剂量已失效') as captured:
        exports.export_object(owner, sid, agent, row, row.default_format, tmp_path / 'stale-zh')
    assert captured.value.code == 'total_dose_export_stale'
    assert not (tmp_path / 'stale-zh').exists()
