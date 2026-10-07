"""Interactive SAT3D route and consent contracts; no GPU execution."""
import numpy as np
import pytest
import SimpleITK as sitk


def test_generic_route_is_explicit_not_an_automatic_alias():
    from tool_factory.CTV_seg import normalize_tumor_type, get_tool
    from tool_factory.CTV_seg.sat3d import SAT3DCTVTool
    route='sat3d_interactive_generic_tumor'
    assert normalize_tumor_type(route)==route
    assert isinstance(get_tool(route),SAT3DCTVTool)


@pytest.mark.parametrize('site,modality', [('sat3d_generic_tumor','CT'),('sat3d_head_neck_tumor','CT'),('sat3d_prostate_tumor','T2w')])
@pytest.mark.parametrize('consent',[False,'true',1,None])
def test_ood_cannot_run_without_explicit_boolean_consent(monkeypatch,site,modality,consent):
    import tool_factory.CTV_seg.sat3d as sat
    monkeypatch.setattr(sat,'_availability',lambda **kw:pytest.fail('must reject before probing/loading weights'))
    image=sitk.GetImageFromArray(np.ones((8,8,8),np.float32))
    result=sat.SAT3DCTVTool()._execute(image=image,tumor_type=site,image_modality=modality,
        positive_points=[[4,4,4]],allow_out_of_distribution=consent)
    assert not result.success
    assert result.metadata['code']=='sat3d_ood_confirmation_required'


def test_interactive_catalog_remains_separate_from_automatic_selector():
    from tool_factory.CTV_seg.model_catalog import CTV_MODEL_CATALOG
    interactive=[x for x in CTV_MODEL_CATALOG if str(x.get('tumor_type','')).startswith('sat3d_interactive_')]
    assert len(interactive)==7
    assert all(x['ui_visible'] is False for x in interactive)
    assert all(x['prompt_support']['positive_points'] and not x['prompt_support']['zero_prompt'] for x in interactive)


@pytest.fixture
def manual_segmentation_route(monkeypatch, tmp_path):
    """Mount the actual API and Structure Set; only model execution is mocked."""
    from types import SimpleNamespace
    from flask import Flask
    from agent_runtime.core import AgentMemory
    from web.routes import planning_routes as routes
    from web.structure_service import initialize_structure_registry
    from tool_factory.CTV_seg import CTVSegmentationTool
    from tool_factory.OAR_seg import OARSegmentationTool

    memory = AgentMemory('synthetic-viewers-segmentation')
    shape = (8, 8, 8)
    image = sitk.GetImageFromArray(np.zeros(shape, np.int16))
    image_path = str(tmp_path / 'synthetic.nii.gz')
    sitk.WriteImage(image, image_path)
    old = np.zeros(shape, np.uint8)
    old[1, 1, 1] = 1
    oar = np.zeros(shape, np.uint16)
    oar[6, 6, 6] = 1
    for key, value in {'ct_image': image, 'ct_data': sitk.GetArrayFromImage(image),
        'ctv_array': old, 'ctv_source': 'sat3d_generic_tumor', 'ctv_label_map': {1: 'Old tumor'},
        'oar_array': oar, 'organ_names': {1: 'Synthetic organ'}, 'oar_source': 'test_model'}.items():
        memory.store(key, value)
    initialize_structure_registry(memory)
    memory.store('dose_metrics', {'v100': 99})
    memory.store('dose_distribution_gy', np.ones(shape, np.float32))
    memory.store('surgical_guide', {'status': 'completed', 'mesh': 'synthetic-existing-guide'})
    agent = SimpleNamespace(memory=memory)
    store = SimpleNamespace(get_session=lambda *a: SimpleNamespace(id=memory.session_id),
        owns_path=lambda *a: a[-1] == image_path, schedule_agent_checkpoint=lambda *a, **kw: None)
    monkeypatch.setattr(routes, 'require_api_key', lambda f: f)
    monkeypatch.setattr(routes, 'rate_limit', lambda f: f)
    monkeypatch.setattr(routes, 'current_user', lambda *a: {'id': 'synthetic-owner'})
    app = Flask(__name__)
    app.secret_key = 'synthetic-only'
    app.extensions['brachybot_workspace_store'] = store
    routes.register_planning_routes(app, lambda *a, **kw: agent)

    def post(kind, metadata, *, change_source=False):
        def execute(_tool, **kwargs):
            if change_source:
                memory.store('ctv_array', old.copy())
            return SimpleNamespace(success=True, metadata=metadata)
        cls = CTVSegmentationTool if kind == 'ctv' else OARSegmentationTool
        monkeypatch.setattr(cls, 'execute', execute)
        return app.test_client().post('/api/segmentation', headers={'X-BrachyBot-Session': memory.session_id},
            json={'kind': kind, 'image_path': image_path, 'tumor_type': 'sat3d_interactive_generic_tumor',
                'positive_points': [[3, 3, 3]], 'allow_out_of_distribution': True})
    return memory, old, oar, post


@pytest.mark.parametrize('kind', ['ctv', 'oar'])
def test_manual_rerun_replaces_registered_source_and_invalidates_dependents(manual_segmentation_route, kind):
    memory, old, oar, post = manual_segmentation_route
    candidate = np.zeros(old.shape, np.uint16)
    candidate[3, 3, 3] = 1
    metadata = ({'ctv_array': candidate, 'ctv_source': 'sat3d_generic_tumor',
        'label_map': {1: 'Candidate tumor'}} if kind == 'ctv' else
        {'oar_array': candidate, 'organ_names': {1: 'Candidate organ'}, 'oar_source': 'test_model'})
    response = post(kind, metadata)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['success'] is True
    assert np.array_equal(memory.retrieve('ctv_binary_array'), candidate > 0 if kind == 'ctv' else old > 0)
    assert np.array_equal(memory.retrieve('oar_array'), oar if kind == 'ctv' else candidate)
    assert np.array_equal(memory.retrieve('structure_base_' + kind + '_array'), candidate)
    assert memory.retrieve('dose_metrics') is None
    assert memory.retrieve('dose_distribution_gy') is None
    assert memory.retrieve('manual_artifact_status')['report'] == 'stale'
    assert memory.retrieve('surgical_guide')['status'] == 'stale'
    assert memory.retrieve('surgical_guide')['mesh'] == 'synthetic-existing-guide'


def test_sat_candidate_cannot_overwrite_a_ctv_changed_during_inference(manual_segmentation_route):
    memory, old, oar, post = manual_segmentation_route
    response = post('ctv', {'ctv_array': np.ones_like(old)}, change_source=True)
    assert response.status_code == 409
    assert response.get_json()['code'] == 'segmentation_source_changed'
    assert np.array_equal(memory.retrieve('ctv_array'), old)
    assert memory.retrieve('dose_metrics') == {'v100': 99}


@pytest.mark.parametrize('kind', ['ctv', 'oar'])
def test_maskless_tool_success_is_not_published_as_a_finished_segmentation(manual_segmentation_route, kind):
    memory, old, oar, post = manual_segmentation_route
    response = post(kind, {})
    assert response.status_code == 500
    assert np.array_equal(memory.retrieve('ctv_array'), old)
    assert np.array_equal(memory.retrieve('oar_array'), oar)
    assert memory.retrieve('dose_metrics') == {'v100': 99}
