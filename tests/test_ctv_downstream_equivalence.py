import numpy as np

from web.structure_service import (
    _base_ctv_volume,
    _is_model_ctv_source,
    is_multitarget_gtv_source,
)


def test_lung_vista_is_a_registered_model_source():
    # Previously the name-prefix heuristic in the viewer missed vista3d_* and
    # treated a model output as an uploaded mask.
    from tool_factory.CTV_seg.model_registry import is_registered_model_source
    assert is_registered_model_source('vista3d_lung_tumor') is True


def test_embedded_anatomy_predicate_is_target_plus_anatomy_only():
    assert _is_model_ctv_source('nnunet_pancreatic')
    assert not _is_model_ctv_source('vista3d_lung_tumor')
    assert not _is_model_ctv_source('nnunet_head_neck_gtv')
    assert not _is_model_ctv_source('nnunet_nasopharynx_cect')


def test_multitarget_gate_uses_registry_not_name_prefix():
    assert is_multitarget_gtv_source('nnunet_head_neck_gtv')
    assert is_multitarget_gtv_source('nnunet_nasopharynx_ncct')
    assert is_multitarget_gtv_source('nnunet_nasopharynx_cect')
    assert not is_multitarget_gtv_source('vista3d_lung_tumor')
    assert not is_multitarget_gtv_source('nnunet_liver_tumor')
    assert not is_multitarget_gtv_source('manual_label')


class _Memory:
    def __init__(self, values):
        self._values = values

    def retrieve(self, key, default=None):
        return self._values.get(key, default)


def _nine_voxel_case(source, label_map, one=8, two=1):
    full = np.zeros((4, 4, 4), dtype=np.uint8)
    full[1:3, 1:3, 1:3] = 1
    full[0, 0, 0] = 2
    return _Memory({
        'ctv_source': source,
        'ctv_label_map': label_map,
        'ctv_full_labels': full,
        'ctv_array': (full == 1).astype(np.uint8),
    })


def test_multitarget_gtv_keeps_both_labels_as_target():
    array, labels, source = _base_ctv_volume(_nine_voxel_case(
        'nnunet_head_neck_gtv', {1: 'GTVp (primary)', 2: 'GTVn (nodal)'}))
    assert set(labels) == {1, 2}
    assert set(np.unique(array)) == {0, 1, 2}


def test_target_plus_anatomy_keeps_only_label_one_as_target():
    array, labels, source = _base_ctv_volume(_nine_voxel_case(
        'nnunet_pancreatic', {1: 'pancreatic tumor', 2: 'artery'}))
    assert set(labels) == {1}
    assert set(np.unique(array)) <= {0, 1}


def test_single_target_registered_model_projects_binary():
    array, labels, source = _base_ctv_volume(_nine_voxel_case(
        'vista3d_lung_tumor', {1: 'lung tumor'}))
    assert set(np.unique(array)) == {0, 1}
    assert labels == {1: 'lung tumor'}
