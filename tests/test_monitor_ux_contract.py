"""Monitor UX is a projection of valid facts, not success-shaped placeholders."""
from types import SimpleNamespace

import pytest

from web.monitor_changes import capture, compare, dose_comparison, interaction, screenshot


def snapshot(**patch):
    return dict(planning_id='p', anatomy_key=[('ctv', 1)], config={'rx': 120},
                metrics_current=True, metrics={'v100': 90, 'd90': 120}, **patch)


@pytest.mark.parametrize('key,value,reason', [
    ('planning_id', 'different', 'planning_changed'),
    ('planning_id', None, 'planning_identity_missing'),
    ('anatomy_key', None, 'anatomy_baseline_missing'),
    ('anatomy_key', [], 'anatomy_baseline_missing'),
    ('config', {'rx': 130}, 'configuration_changed'),
    ('metrics_current', False, 'current_dose_unavailable'),
])
def test_nonmatching_baseline_explains_why_and_never_attributes_deltas(key, value, reason):
    before = snapshot()
    result = dose_comparison(before, {**before, key: value, 'metrics': {'v100': 91}})
    assert result['comparable'] is False and result['delta'] == {}
    assert result['comparison_reason'] == reason
    for lang in ('zh', 'en'):
        card = interaction({'dose': result}, lang)
        assert card['comparison_reason'] == reason
        assert card['metric_rows'] == []


def test_missing_plan_or_anatomy_cannot_be_equal_by_being_missing_twice():
    for field, value in (('planning_id', None), ('anatomy_key', None), ('anatomy_key', [])):
        both = {**snapshot(), field: value}
        result = dose_comparison(both, both)
        assert not result['comparable']
        assert result['series_key'] is None


@pytest.mark.parametrize('status', ['stale', 'outdated', 'running', 'failed'])
@pytest.mark.parametrize('nested', [False, True])
def test_capture_handles_scalar_and_structured_artifact_status(status, nested):
    values = {'dose_distribution': object(), 'dose_metrics': {'d90': 120},
              'manual_artifact_status': {'dose': {'status': status} if nested else status}}
    agent = SimpleNamespace(memory=SimpleNamespace(retrieve=lambda key: values.get(key)))
    result = capture(agent, {'seeds': [], 'needles': []})
    assert result['metrics_current'] is False
    assert result['anatomy_key'] is None


def test_computed_current_dose_without_baseline_does_not_recommend_pointless_recompute():
    before = {**snapshot(), 'metrics_current': False}
    dose = dose_comparison(before, snapshot())
    card = interaction({'dose': dose}, 'zh')
    assert card['dose_current'] and not card['dose_comparable']
    assert '编辑前剂量' in card['dose_note']
    assert '不能通过再次重算补造前值' in card['next_step']


def test_return_vectors_bind_the_moved_endpoint_not_all_associated_seeds():
    evidence = {'dependent_object_count': 3, 'normalization_object_count': 2,
                'changed_objects': [
                    {'id': 'needle23', 'kind': 'needles', 'operation': 'moved',
                     'before': [[0, 0, 0], [0, 0, 10]], 'after': [[3, -4, 0], [0, 0, 10]]},
                    {'id': 'seed', 'kind': 'seeds', 'operation': 'moved', 'dependent_on_needle': True,
                     'before': [0, 0, 5], 'after': [1, 0, 5]},
                ]}
    result = interaction(evidence, 'zh')
    assert result['related_object_counts'] == {'dependent': 3, 'normalized': 2}
    assert result['return_movements'] == [dict(object_id='needle23', endpoint=1,
        vector_mm=[-3, 4, 0], coordinate_system='patient_world_mm', purpose='return_to_pre_edit_not_optimized')]


def test_reorientation_is_real_geometry_and_should_offer_location_evidence():
    evidence = {'planning_id': 'p', 'after_version': 2, 'geometry_key': 'g', 'changed_objects': [
        {'id': 'rotated', 'operation': 'reoriented'},
        {'id': 'derived', 'operation': 'reoriented', 'derived_from_normalization': True},
        {'id': 'deleted', 'operation': 'deleted'},
    ]}
    assert screenshot(evidence, 'e')['object_ids'] == ['rotated']


def test_seed_gap_requirement_is_preserved_in_edit_evidence():
    def geometry(z):
        return {'seeds': [{'id': 'a', 'position': [0, 0, 0], 'direction': [0, 0, 1]},
                          {'id': 'b', 'position': [0, 0, z], 'direction': [0, 0, 1]}], 'needles': []}
    before = {**snapshot(), 'geometry': geometry(6), 'geometry_key': 'old', 'version': 1}
    after = {**snapshot(), 'geometry': geometry(4.7), 'geometry_key': 'new', 'version': 2}
    result = compare(before, after)
    pair = result['conflicts'][0]
    assert pair['surface_clearance_mm'] == pytest.approx(.2)
    assert pair['minimum_clearance_mm'] == .5
    assert pair['physical_overlap'] is False
