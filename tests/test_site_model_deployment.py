"""Application contracts for the supplied CT models; model inference is tested separately."""
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
import SimpleITK as sitk

from tool_factory.CTV_seg import CTVSegmentationTool, get_tool, normalize_tumor_type, resolve_ctv_tumor_type
from tool_factory.CTV_seg.site_models import SITE_MODELS, inference_command
from tool_factory.CTV_seg.site_model_tumor import SiteModelTumorTool, HeadNeckGTVTool

@pytest.mark.parametrize('alias,canonical', [
    ('lung', 'vista3d_lung_tumor'), ('biomedparse_lung_lesion', 'vista3d_lung_tumor'),
    ('voco_lung', 'vista3d_lung_tumor'), ('head_neck', 'nnunet_head_neck_gtv'),
    ('biomedparse_head_neck_cancer', 'nnunet_head_neck_gtv'),
    ('鼻咽癌平扫', 'nnunet_nasopharynx_ncct'), ('鼻咽癌增强', 'nnunet_nasopharynx_cect')])
def test_aliases_share_canonical_tools(alias, canonical):
    assert normalize_tumor_type(alias) == canonical
    assert isinstance(get_tool(alias), SiteModelTumorTool)

def test_nasopharynx_requires_explicit_phase():
    result = CTVSegmentationTool()._execute(tumor_type='鼻咽癌')
    assert not result.success and result.metadata['code'] == 'ct_phase_required'
    assert resolve_ctv_tumor_type({'tumor_type': 'nasopharynx', 'ct_phase': 'cect'}).endswith('_cect')
    assert resolve_ctv_tumor_type({'tumor_type': 'nasopharynx', 'ct_phase': 'ncct'}).endswith('_ncct')

@pytest.mark.parametrize('key', list(SITE_MODELS))
def test_command_keeps_validated_defaults(key):
    command = inference_command(key, '/in', '/out', '1')
    assert command[:2] == ['/opt/miniconda3/bin/python', str(SITE_MODELS[key]['script'])]
    assert command[command.index('--gpu')+1] == '1'
    assert '--fp16' not in command and '--fp32' not in command and '--no_tta' not in command
    if 'head_neck' in key:
        assert command[command.index('--checkpoint')+1] == 'final'
    if 'lung' in key:
        assert command[command.index('--label_prompt')+1] == '23'

def sample():
    raw = np.zeros((4, 5, 6), np.uint8)
    raw[1, 2, 3] = 1
    raw[2, 3, 4] = 2
    image = sitk.GetImageFromArray(np.zeros_like(raw, np.int16))
    image.SetSpacing((0.7, 1.2, 2.4))
    image.SetOrigin((14., -9., 30.))
    image.SetDirection((0., 1., 0., -1., 0., 0., 0., 0., 1.))
    label = sitk.GetImageFromArray(raw)
    label.CopyInformation(image)
    return image, label

@pytest.mark.parametrize('key', ['nnunet_head_neck_gtv', 'nnunet_nasopharynx_ncct', 'nnunet_nasopharynx_cect'])
def test_wrapper_preserves_geometry_both_targets_and_structure_classification(monkeypatch, key):
    image, label = sample()
    def fake_execute(self, **kwargs):
        return self._result(kwargs['image'], label, '1')
    monkeypatch.setattr(SiteModelTumorTool, '_execute', fake_execute)
    result = CTVSegmentationTool()._execute(image=image, tumor_type=key)
    assert result.success, result.error
    expected = sitk.GetArrayFromImage(sitk.DICOMOrient(label, 'LPI'))
    np.testing.assert_array_equal(result.metadata['full_label_array'], expected)
    np.testing.assert_array_equal(result.data, expected > 0)
    assert result.metadata['label_counts'] == {1: 1, 2: 1}
    assert result.metadata['inference_precision'] == SITE_MODELS[key]['precision']
    from web.structure_service import _source_structures
    class Memory:
        def retrieve(self, key, default=None):
            return {'ctv_array': result.data, 'ctv_full_labels': result.metadata['full_label_array'],
                    'ctv_label_map': result.metadata['label_map'], 'ctv_source': result.metadata['ctv_source']}.get(key, default)
    structures = _source_structures(Memory())
    assert len(structures) == 2
    assert all(s['source_classification'] == 'ctv' for s in structures)
    assert [s['source_label'] for s in structures] == [1, 2]
    from types import SimpleNamespace
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool, _merge_embedded_hard_obstacles
    memory = Memory()
    agent = SimpleNamespace(memory=memory, _get_label_array=lambda k: memory.retrieve(k))
    planned_target = PlanningPipelineTool()._load_ctv({}, agent, sitk.DICOMOrient(image, 'LPI'))
    np.testing.assert_array_equal(planned_target, expected > 0)
    oar = np.zeros_like(expected, np.uint16)
    merged, hard_ids = _merge_embedded_hard_obstacles(oar, agent)
    assert not hard_ids
    np.testing.assert_array_equal(merged, oar)

def test_invalid_geometry_and_labels_are_rejected():
    image, label = sample()
    label.SetOrigin((0., 0., 0.))
    with pytest.raises(ValueError, match='physical grid'):
        HeadNeckGTVTool()._result(image, label, '0')
    label.CopyInformation(image)
    label[0, 0, 0] = 3
    with pytest.raises(ValueError, match='unexpected labels'):
        HeadNeckGTVTool()._result(image, label, '0')

def test_empty_prediction_is_not_published(monkeypatch):
    image, label = sample()
    label *= 0
    monkeypatch.setattr(SiteModelTumorTool, '_execute', lambda self, **kw: self._result(kw['image'], label, '0'))
    assert not CTVSegmentationTool()._execute(image=image, tumor_type='head_neck').success

def test_pancreatic_anatomy_contract_is_preserved():
    from web.structure_service import _source_structures
    class Memory:
        def retrieve(self, key, default=None):
            full = np.array([[[1, 2, 3, 4]]], np.uint8)
            return {'ctv_source': 'model', 'ctv_full_labels': full, 'ctv_array': (full == 1).astype(np.uint8)}.get(key, default)
    structures = _source_structures(Memory())
    assert [s['name'] for s in structures[1:]] == ['artery', 'vein', 'pancreas']

@pytest.mark.parametrize('key', ['nnunet_head_neck_gtv', 'nnunet_nasopharynx_ncct', 'nnunet_nasopharynx_cect'])
@pytest.mark.parametrize('restored', [False, True])
def test_viewer_transports_both_gtv_labels_without_creating_artery(monkeypatch, key, restored):
    from flask import Flask
    from web.routes import viewer_routes
    from types import SimpleNamespace
    image, label = sample()
    labels = sitk.GetArrayFromImage(sitk.DICOMOrient(label, 'LPI'))
    values = {'ct_data': np.zeros_like(labels), 'ctv_full_labels': labels,
              'ctv_array': (labels > 0).astype(np.uint8),
              'ctv_source': 'classified' if restored else key,
              'structure_base_ctv_source': key if restored else None,
              'ctv_label_map': SITE_MODELS[key]['labels']}
    memory = SimpleNamespace(retrieve=lambda k, default=None: values.get(k, default))
    agent = SimpleNamespace(memory=memory, _workspace_data_ready=True,
                            _get_label_array=lambda k: memory.retrieve(k))
    monkeypatch.setattr(viewer_routes, 'require_api_key', lambda f: f)
    monkeypatch.setattr(viewer_routes, 'rate_limit', lambda f: f)
    app = Flask(__name__)
    viewer_routes.register_viewer_routes(app, lambda **kw: agent, lambda *a, **kw: None, lambda *a, **kw: {})
    response = app.test_client().get('/api/viewer/label_volume')
    assert response.status_code == 200
    assert response.headers['X-Has-OAR'] == 'false'
    length = int(response.headers['X-CTV-Size'])
    np.testing.assert_array_equal(np.frombuffer(response.data[:length], np.uint8).reshape(labels.shape), labels)

def test_cancellation_is_observed_and_gpu_lock_is_exclusive():
    from tool_factory.CTV_seg.site_model_runtime import gpu_lock, communicate_cancellable
    from utils.cancellation import cancellation_scope, OperationCancelled
    with gpu_lock(99):
        with pytest.raises(TimeoutError):
            with gpu_lock(99, timeout=0):
                pass
    with cancellation_scope(lambda: True):
        with pytest.raises(OperationCancelled):
            communicate_cancellable(None, 5)

def test_runtime_keeps_user_site_and_does_not_inherit_cuda_remapping(monkeypatch):
    from tool_factory.CTV_seg.site_model_runtime import inference_env
    monkeypatch.setenv('PYTHONNOUSERSITE', '1')
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES', '1')
    env = inference_env()
    assert 'PYTHONNOUSERSITE' not in env and 'CUDA_VISIBLE_DEVICES' not in env

def test_oom_retries_other_gpu_without_altering_model(monkeypatch):
    import plans.device_manager as dm
    from contextlib import contextmanager
    from types import SimpleNamespace
    from tool_factory.CTV_seg.site_model_runtime import on_gpu
    import tool_factory.CTV_seg.site_model_runtime as runtime
    @contextmanager
    def session(caller, prefer=None):
        yield SimpleNamespace(device_str=f'cuda:{prefer or 0}')
    monkeypatch.delenv('BRACHYBOT_CTV_GPU', raising=False)
    monkeypatch.setattr(dm, 'device_session', session)
    from contextlib import nullcontext
    monkeypatch.setattr(runtime, 'gpu_lock', lambda gpu: nullcontext())
    monkeypatch.setattr(dm.DeviceManager, 'instance', lambda: SimpleNamespace(device_count=lambda: 2))
    seen = []
    def inference(gpu):
        seen.append(gpu)
        if len(seen) == 1:
            raise RuntimeError('CUDA out of memory')
        return 'same model result'
    assert on_gpu('test', inference) == 'same model result'
    assert seen == ['0', '1']
