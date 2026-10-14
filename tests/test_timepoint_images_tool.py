"""Actual Agent gate + image service; no inference/route replacement."""
from io import BytesIO
import numpy as np
import SimpleITK as sitk
from test_agent_timepoint_boundary import owned, activate, grant
from tool_factory.timepoint_images import TimepointImagesTool
from web.timepoint_images import TimepointImageService


def prepare(owned):
    store,owner,sid,tid,_,root = owned
    service = TimepointImageService(store)
    service.adopt_saved_reference(owner,sid,tid)
    root.registry.register(TimepointImagesTool(root))
    return service, service.list_images(owner,sid,tid)['images'][0]['id']


def execute(runtime,action,**kwargs):
    params = dict(action=action,**kwargs)
    grant(runtime,'timepoint_images',params)
    return runtime.view._execute_tool_with_memory('timepoint_images',params)


def test_image_list_and_display_grouping_are_owned_metadata_actions(owned):
    service,image = prepare(owned)
    store,owner,sid,tid,_,root = owned
    runtime = activate(owned,message='Move this image to the intraoperative group, but do not replan')
    read = runtime.view._execute_tool_with_memory('timepoint_images',{'action':'list'})
    assert read.success and read.metadata['read_only'] and read.data['images'][0]['id'] == image
    assert runtime.view._workspace_data_ready is False
    version = store.load_timepoint_snapshot(owner,sid,tid)['timepoint_clinical_revision']
    result = execute(runtime,'move',image_id=image,role='intraop')
    assert result.success,result.error
    assert service.list_images(owner,sid,tid)['images'][0]['role'] == 'intraop'
    result = execute(runtime,'appearance',image_id=image,opacity=.29,color='#22D3EE',window_width=570.,window_level=51.)
    assert result.success,result.error
    assert result.metadata['ui_action']['scope']['timepoint_id'] == tid
    assert store.load_timepoint_snapshot(owner,sid,tid)['timepoint_clinical_revision'] == version
    assert root.memory.retrieve('dose_metrics') == {'v100':.1}


def test_explicit_reference_change_replaces_runtime_not_only_saved_path(owned,tmp_path):
    service,first = prepare(owned)
    store,owner,sid,tid,_,root = owned
    path = tmp_path / 'new_source.nii.gz'
    sitk.WriteImage(sitk.GetImageFromArray(np.full((4,5,6),99,np.int16)),str(path))
    packet = service.register_upload(owner,sid,tid,BytesIO(path.read_bytes()),path.name,modality='CT',
        expected_collection_revision=service.list_images(owner,sid,tid)['collection_revision'],editor_token='synthetic-editor')
    second = packet['created_image_id']
    runtime = activate(owned,message='Use this uploaded image as the planning reference')
    runtime._waiter(True)
    assert runtime.view.memory.retrieve('ctv_array') is not None
    result = execute(runtime,'set_reference',image_id=second)
    assert result.success,result.error
    assert runtime.view._workspace_data_ready is False
    assert runtime.view.memory.retrieve('ctv_array') is None
    runtime._waiter(True)
    assert runtime.view.memory.retrieve('ct_data').shape == (4,5,6)
    assert np.all(runtime.view.memory.retrieve('ct_data') == 99)
    assert runtime.view.memory.retrieve('planning_reference_image_id') == second
    assert service.list_images(owner,sid,tid)['images'][0]['id'] == first
    assert root.memory.retrieve('dose_metrics') == {'v100':.1}


def test_image_mutations_cannot_bypass_execution_grant_or_owned_ids(owned):
    service,image = prepare(owned)
    store,owner,sid,tid,_,_ = owned
    runtime = activate(owned)
    version = service.list_images(owner,sid,tid)['collection_revision']
    denied = runtime.view._execute_tool_with_memory('timepoint_images',{'action':'hide','image_id':image})
    assert not denied.success
    wrong = execute(runtime,'show',image_id='f'*32)
    assert not wrong.success
    assert service.list_images(owner,sid,tid)['collection_revision'] == version
    hidden = execute(runtime,'hide',image_id=image)
    assert hidden.success,hidden.error
    state = store.load_timepoint_snapshot(owner,sid,tid)
    assert state['image_collection']['display_image_id'] is None
    assert state['agent']['planning_results']['dose_metrics']['v100'] == .8
