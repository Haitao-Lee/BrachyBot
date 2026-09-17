from tool_factory.CTV_seg.model_registry import (
    CTV_ROUTES, route, target_semantics, is_registered_model_source,
    canonical_ctv_source, ui_routes,
)

EXPECTED = {
    'nnunet_pancreatic': ('pancreas', 'target_plus_anatomy'),
    'nnunet_liver_tumor': ('liver', 'single_target'),
    'nnunet_kidney_tumor': ('kidney', 'single_target'),
    'nnunet_head_neck_gtv': ('head_neck', 'multi_target_gtv'),
    'nnunet_nasopharynx_ncct': ('nasopharynx', 'multi_target_gtv'),
    'nnunet_nasopharynx_cect': ('nasopharynx', 'multi_target_gtv'),
    'vista3d_lung_tumor': ('lung', 'single_target'),
}


def test_all_primary_routes_are_registered_as_peers():
    for rid, (site, semantics) in EXPECTED.items():
        r = route(rid)
        assert r is not None, rid
        assert r.site == site
        assert r.target_semantics == semantics


def test_target_semantics_handles_legacy_sources():
    assert target_semantics('model') == 'target_plus_anatomy'
    assert target_semantics('nnunet_cascade_liver') == 'single_target'
    assert target_semantics('manual_label') == 'single_target'
    assert target_semantics('') == 'single_target'


def test_registered_model_source_detection():
    assert is_registered_model_source('vista3d_lung_tumor')
    assert is_registered_model_source('model')
    assert is_registered_model_source('nnunet_cascade_kidney')
    assert not is_registered_model_source('manual_label')
    assert not is_registered_model_source('uploaded')


def test_canonical_ctv_source_maps_legacy_to_route_id():
    assert canonical_ctv_source('model') == 'nnunet_pancreatic'
    assert canonical_ctv_source('nnunet_cascade_liver') == 'nnunet_liver_tumor'
    assert canonical_ctv_source('nnunet_cascade_kidney') == 'nnunet_kidney_tumor'
    assert canonical_ctv_source('nnunet_nasopharynx_ncct') == 'nnunet_nasopharynx_ncct'
    assert canonical_ctv_source('manual_label') == 'manual_label'


def test_ui_routes_are_all_available_peers():
    ids = {r.id for r in ui_routes()}
    assert EXPECTED.keys() <= ids


def test_metadata_contract_is_identical_across_engines():
    import numpy as np, SimpleITK as sitk
    from tool_factory.CTV_seg import CTVSegmentationTool
    from tool_factory.CTV_seg.model_registry import canonical_ctv_source

    # Legacy adapter output shape used by pancreatic.  The wrapper must
    # normalize ctv_source and compute label_stats for every engine.
    image = sitk.GetImageFromArray(np.zeros((4, 4, 4), dtype=np.int16))
    label = np.zeros((4, 4, 4), dtype=np.uint8)
    label[1:3, 1:3, 1:3] = 1
    label[0, 0, 0] = 2
    mask = sitk.GetImageFromArray(label)
    mask.CopyInformation(image)

    class FakeTool:
        name = 'nnunet_pancreatic'
        def _execute(self, **kwargs):
            from tool_factory import ToolResult
            return ToolResult(success=True, data=label, metadata={
                'ctv_mask': mask, 'ctv_array': (label == 1).astype(np.uint8),
                'full_label_array': label, 'label_map': {1: 'pancreatic tumor', 2: 'artery'},
                'label_counts': {1: 8, 2: 1},
            })

    tool = CTVSegmentationTool()
    tool._resolve_tool = lambda tumor_type: FakeTool()
    result = tool._execute(image=image, tumor_type='nnunet_pancreatic')
    assert result.success
    meta = result.metadata
    assert canonical_ctv_source(meta['ctv_source']) == 'nnunet_pancreatic'
    assert meta['target_semantics'] == 'target_plus_anatomy'
    assert meta['label_stats']['artery']['voxel_count'] == 1


def test_pancreatic_inference_uses_shared_gpu_lock(monkeypatch):
    import contextlib
    import tool_factory.CTV_seg.pancreatic_tumor_nnunet as P
    from tool_factory.CTV_seg import site_model_runtime

    used = {}

    @contextlib.contextmanager
    def fake_lock(gpu, timeout=900):
        used['gpu'] = gpu
        yield

    monkeypatch.setattr(site_model_runtime, 'gpu_lock', fake_lock)
    with P.NNUNetPancreaticTumorTool()._gpu_guard('0'):
        pass
    assert used['gpu'] == '0'


def test_biomedparse_external_inference_is_pinned_and_locked(monkeypatch):
    import contextlib
    import numpy as np
    from tool_factory.CTV_seg import biomedparse_v2 as B

    seen = {}

    @contextlib.contextmanager
    def fake_guard():
        yield '3'

    monkeypatch.setattr(B, '_inference_gpu_guard', fake_guard)

    def fake_run(cmd, **kwargs):
        seen['env'] = kwargs.get('env') or {}
        return type('R', (), {'returncode': 1, 'stdout': '', 'stderr': 'stop'})()

    monkeypatch.setattr(B.subprocess, 'run', fake_run)
    try:
        B._run_external_inference(
            normalised=np.zeros((4, 4, 4), dtype=np.float32),
            root=B.Path('.'), checkpoint=B.Path('x'), text_assets=B.Path('y'),
            runtime_python=B.Path('/usr/bin/false'), prompt='lung', slice_batch_size=1,
        )
    except Exception:
        pass
    assert seen['env'].get('CUDA_VISIBLE_DEVICES') == '3'


def test_unsupported_tumor_points_at_open_vocabulary():
    import numpy as np, SimpleITK as sitk
    from tool_factory.CTV_seg import CTVSegmentationTool

    image = sitk.GetImageFromArray(np.zeros((4, 4, 4), dtype=np.int16))
    r = CTVSegmentationTool()._execute(image=image, tumor_type='食管癌')
    assert r.success is False
    assert (r.metadata or {}).get('open_vocabulary_available') is True
    assert (r.metadata or {}).get('suggested_tool') == 'biomedparse_segmentation'


def test_open_vocabulary_route_is_a_registered_peer():
    assert route('biomedparse_segmentation') is not None
    assert target_semantics('biomedparse_segmentation') == 'candidate_mask'
    assert is_registered_model_source('biomedparse_segmentation')
    assert 'biomedparse_segmentation' not in {r.id for r in ui_routes()}


def test_catalog_lists_registry_routes_as_peers():
    from tool_factory.CTV_seg import filter_catalog, normalize_tumor_type

    visible = [r for r in filter_catalog() if r.get('ui_visible')]
    resolved = {
        normalize_tumor_type(r.get('tumor_type') or r.get('id') or '')
        for r in visible
    }
    for rid in ('nnunet_pancreatic', 'nnunet_liver_tumor', 'nnunet_kidney_tumor',
                'nnunet_head_neck_gtv', 'nnunet_nasopharynx_ncct',
                'nnunet_nasopharynx_cect', 'vista3d_lung_tumor',
                'biomedparse_colon_primary', 'biomedparse_prostate_lesion'):
        assert rid in resolved, rid
    assert 'biomedparse_lung_lesion' not in resolved
    assert 'biomedparse_head_neck_cancer' not in resolved
