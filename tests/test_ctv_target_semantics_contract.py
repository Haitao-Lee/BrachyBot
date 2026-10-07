"""Cross-entry target/obstacle regressions; no model inference or patient data."""
from types import SimpleNamespace

import numpy as np
import pytest
import SimpleITK as sitk

from utils.ctv_targets import canonical_semantics, project_target, resolve_ctv_target
from tool_factory.CTV_seg.model_registry import CTV_ROUTES, validate_route_input


class Memory:
    def __init__(self, values):
        self.values = values

    def retrieve(self, key, default=None):
        return self.values.get(key, default)

    def get_ui_state(self):
        return {}


def case(source):
    raw = np.zeros((8, 8, 8), np.uint8)
    raw[4, 4, 3:5] = [1, 2]
    image = sitk.GetImageFromArray(np.zeros_like(raw, np.int16))
    return Memory({'ctv_source': source, 'ctv_full_labels': raw, 'ctv_array': raw,
                   'ctv_mask': raw, 'ct_image': image, 'ct_spacing': [1., 1., 1.],
                   'ctv_label_map': dict(CTV_ROUTES[source].labels),
                   'oar_array': np.zeros_like(raw, np.uint16)})


MULTI = ['nnunet_head_neck_gtv', 'nnunet_nasopharynx_ncct', 'nnunet_nasopharynx_cect']


@pytest.mark.parametrize('source', MULTI)
@pytest.mark.parametrize('restored', [False, True])
def test_direct_planning_and_dose_share_both_targets(source, restored):
    from AgenticSys import BrachyAgent
    from plans.dose_pre.evaluation_inputs import resolve_dose_evaluation_inputs
    from tool_factory.dose_eval import DoseEvaluationTool
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
    memory = case(source)
    raw = memory.values['ctv_full_labels']
    if restored:
        memory.values.update(ctv_source='classified', ctv_binary_array=(raw > 0).astype(np.uint8))
    agent = BrachyAgent.__new__(BrachyAgent)
    agent.memory = memory
    target = resolve_ctv_target(memory.retrieve)
    context = agent._current_planning_obstacle_context()
    np.testing.assert_array_equal(context['ctv_mask'], target)
    assert context['radiation_volume'][4, 4, 4] == context['radiation_volume'][4, 4, 3] == 1
    pipeline_agent = SimpleNamespace(memory=memory, _get_label_array=lambda key: memory.retrieve(key))
    planned = PlanningPipelineTool()._load_ctv({}, pipeline_agent, memory.values['ct_image'])
    np.testing.assert_array_equal(planned, target)
    dose = np.zeros(raw.shape, np.float32)
    dose[raw == 1] = 130.
    dose[raw == 2] = 60.
    memory.values.update(dose_distribution_physical_gy=dose, metrics={'prescription_gy': 120.})
    resolved = resolve_dose_evaluation_inputs(memory.retrieve)
    assert resolved['resolution_error'] is None
    np.testing.assert_array_equal(resolved['params']['ctv_mask'], target)
    result = DoseEvaluationTool().execute(**resolved['params'])
    assert result.success, result.error
    assert result.metadata['v100'] == pytest.approx(.5)  # Old label-1-only path reported 1.0.


@pytest.mark.parametrize('source', MULTI)
def test_manual_needle_crossing_nodal_target_is_not_a_vessel(source):
    from web.server_support import _validate_manual_needle_safety
    memory = case(source)
    _validate_manual_needle_safety(SimpleNamespace(memory=memory),
        [{'id': 'needle', 'points': [[1., 4., 4.], [6., 4., 4.]]}],
        memory.values['ct_image'], memory.values['ctv_array'], memory.values['oar_array'])


def test_pancreatic_targets_and_vascular_safety_are_preserved():
    from web.server_support import _validate_manual_needle_safety, ManualNeedleSafetyError
    memory = case('nnunet_pancreatic')
    assert resolve_ctv_target(memory.retrieve).sum() == 1
    with pytest.raises(ManualNeedleSafetyError):
        _validate_manual_needle_safety(SimpleNamespace(memory=memory),
            [{'id': 'needle', 'points': [[1., 4., 4.], [6., 4., 4.]]}],
            memory.values['ct_image'], memory.values['ctv_array'], memory.values['oar_array'])


@pytest.mark.parametrize('semantics,expected', [('multi_target_gtv', 2), ('target_plus_anatomy', 1), ('classified_union', 2)])
def test_low_level_radiation_volume_has_explicit_semantics(semantics, expected):
    from tool_factory.seed_plan.planning_pipeline import _build_radiation_volume, build_source_aware_needle_safety_context
    memory = case('nnunet_head_neck_gtv')
    raw = memory.values['ctv_array']
    volume = _build_radiation_volume(raw, None, target_semantics=semantics)
    assert np.count_nonzero(volume == 1) == expected
    context = build_source_aware_needle_safety_context(memory.values['ct_image'], raw, None, set(), target_semantics=semantics)
    assert context is not None
    assert context.segment_hits_obstacle([[1., 4., 4.], [6., 4., 4.]]) == (semantics == 'target_plus_anatomy')


def test_classified_union_can_contain_arbitrary_target_ids():
    raw = np.array([[[0, 2, 17, 255]]], np.uint8)
    memory = Memory({'ctv_source': 'classified', 'ctv_array': raw, 'target_semantics': 'target_plus_anatomy'})
    np.testing.assert_array_equal(resolve_ctv_target(memory.retrieve), raw > 0)


def test_binary_companion_wins_and_malformed_companion_fails_closed():
    memory = case('nnunet_head_neck_gtv')
    binary = (memory.values['ctv_array'] == 2).astype(np.uint8)
    memory.values['ctv_binary_array'] = binary
    assert resolve_ctv_target(memory.retrieve) is binary
    memory.values['ctv_binary_array'] = memory.values['ctv_array']
    with pytest.raises(ValueError, match='only background'):
        resolve_ctv_target(memory.retrieve)


def test_flat_hydrated_binary_uses_authoritative_grid():
    memory = case('nnunet_head_neck_gtv')
    memory.values['ctv_binary_array'] = (memory.values['ctv_array'] > 0).astype(np.uint8).ravel()
    assert resolve_ctv_target(memory.retrieve).shape == (8, 8, 8)


@pytest.mark.parametrize('bad', [np.nan, np.inf, -1, .5])
def test_invalid_labels_are_not_targets(bad):
    with pytest.raises(ValueError, match='finite non-negative integers'):
        project_target(np.full((2, 2, 2), bad))


def test_sitk_source_labels_and_legacy_semantics_are_supported():
    memory = case('nnunet_head_neck_gtv')
    memory.values['ctv_full_labels'] = sitk.GetImageFromArray(memory.values['ctv_full_labels'])
    assert resolve_ctv_target(memory.retrieve).sum() == 2
    assert canonical_semantics('nnunet_head_neck_gtv', 'target_plus_anatomy') == 'multi_target_gtv'
    assert canonical_semantics(semantics='primary_and_nodal_gtv_union') == 'multi_target_gtv'


@pytest.mark.parametrize('route_id', [key for key, route in CTV_ROUTES.items() if route.ui_visible and route.modality == 'CT'])
def test_every_ct_route_rejects_mri_before_inference(route_id):
    from tool_factory.CTV_seg import CTVSegmentationTool
    result = CTVSegmentationTool()._execute(image=sitk.GetImageFromArray(np.zeros((3, 3, 3))),
        tumor_type=route_id, image_modality='MRI')
    assert not result.success
    assert result.metadata['code'] == 'unsupported_modality'


def test_phase_conflict_and_prostate_modality_are_explicit():
    with pytest.raises(ValueError, match='supplied phase'):
        validate_route_input('nnunet_nasopharynx_ncct', image_modality='CECT')
    validate_route_input('nnunet_nasopharynx_ncct', image_modality='CT')
    with pytest.raises(ValueError, match='T2-weighted'):
        validate_route_input('biomedparse_prostate_lesion', image_modality='CT')
    validate_route_input('biomedparse_prostate_lesion', image_modality='T2w')


def test_empty_completed_site_inference_has_honest_diagnostic(monkeypatch):
    from tool_factory.CTV_seg import CTVSegmentationTool
    from tool_factory.CTV_seg.site_model_tumor import SiteModelTumorTool
    image = sitk.GetImageFromArray(np.zeros((3, 3, 3), np.int16))
    predicted = sitk.GetImageFromArray(np.zeros((3, 3, 3), np.uint8))
    monkeypatch.setattr(SiteModelTumorTool, '_execute', lambda self, **kw: self._result(image, predicted, '0'))
    result = CTVSegmentationTool()._execute(image=image, tumor_type='head_neck')
    assert not result.success
    assert result.metadata['code'] == 'no_tumor_detected'
    assert result.metadata['inference_completed'] is True
    assert 'not installed' not in result.error


def test_exact_embedded_vessel_duplicates_collapse_but_distinct_masks_do_not():
    from web.structure_service import _source_structures
    memory = case('nnunet_pancreatic')
    oar = np.where(memory.values['ctv_full_labels'] == 2, 1, 0).astype(np.uint16)
    memory.values.update(oar_array=oar, organ_names={1: 'artery'}, oar_source='ctv_embedded')
    structures = _source_structures(memory)
    assert sum(s['name'] == 'artery' for s in structures) == 1
    oar = oar.copy()
    oar[0, 0, 0] = 1
    memory.values['oar_array'] = oar
    assert sum(s['name'] == 'artery' for s in _source_structures(memory)) == 2


def test_node_only_site_result_exposes_canonical_ndarray_contract():
    from tool_factory.CTV_seg.site_model_tumor import HeadNeckGTVTool
    memory = case('nnunet_head_neck_gtv')
    raw = np.where(memory.values['ctv_array'] == 2, 2, 0).astype(np.uint8)
    predicted = sitk.GetImageFromArray(raw)
    result = HeadNeckGTVTool()._result(memory.values['ct_image'], predicted, '0')
    assert result.success and result.data.sum() == 1
    assert isinstance(result.metadata['full_label_array'], np.ndarray)
    assert result.metadata['target_semantics'] == 'multi_target_gtv'


def test_nodal_target_does_not_disable_real_oar_obstacles():
    from tool_factory.seed_plan.planning_pipeline import build_source_aware_needle_safety_context
    memory = case('nnunet_head_neck_gtv')
    oar = memory.values['oar_array'].copy()
    oar[4, 4, 4] = 77
    context = build_source_aware_needle_safety_context(memory.values['ct_image'],
        memory.values['ctv_array'], oar, {77}, target_semantics='multi_target_gtv')
    assert context.segment_hits_obstacle([[1., 4., 4.], [6., 4., 4.]])


def test_manual_restore_updates_binary_companion_with_selected_label():
    from web.workspace_store import _repair_restored_manual_ctv
    raw = np.array([[[0, 1, 255]]], np.uint16)
    state = {'ctv_source': 'manual_label', 'ctv_array': raw, 'ctv_target_value': 255,
             'ctv_binary_array': np.ones_like(raw)}
    assert _repair_restored_manual_ctv(state, {})
    np.testing.assert_array_equal(state['ctv_binary_array'], raw == 255)


def test_pipeline_can_consume_only_a_hydrated_binary_companion():
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
    memory = case('nnunet_head_neck_gtv')
    memory.values['ctv_binary_array'] = (memory.values['ctv_array'] > 0).astype(np.uint8)
    memory.values.pop('ctv_array')
    memory.values.pop('ctv_mask')
    memory.values.pop('ctv_full_labels')
    result = PlanningPipelineTool()._load_ctv({}, SimpleNamespace(memory=memory), memory.values['ct_image'])
    assert result.sum() == 2
