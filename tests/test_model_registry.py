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
