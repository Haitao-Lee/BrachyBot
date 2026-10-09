"""Numerical and authority contracts for complete surgical-report tables."""
from types import SimpleNamespace
import inspect

import numpy as np
import pytest
import SimpleITK as sitk

from web.report_plan_tables import build_oar_rows, build_implant_table, report_snapshot, _entry_resolver, report_table_patch


class Memory:
    def __init__(self, **data):
        self.data = data
    def retrieve(self, key, default=None):
        return self.data.get(key, default)
    def store(self, *args):
        raise AssertionError('Report tables must not mutate planning memory')


@pytest.mark.parametrize('nested', [False, True])
def test_report_detail_fields_survive_legacy_and_nested_snapshot_merge(nested):
    from web.workspace_store import _report_form_from_section, _merge_report_patch
    form = {'planningId': 'plan', 'updatedAt': '2026-10-08T10:00:00Z',
            'oarDoseOrdering': {'method': 'recorded_case_review_priority'},
            'implantPlan': {'reference': 'needle_tip', 'channels': [
                {'id': 'needle_1', 'seeds': [{'id': 'seed_1', 'tip_distance_mm': 15}]}]}}
    section = {'form': form} if nested else dict(form)
    restored, present = _report_form_from_section(section)
    assert present and restored == form
    metadata_only = _merge_report_patch(section, {'audit': {'source': 'synthetic'}})
    assert _report_form_from_section(metadata_only)[0] == form
    merged = _merge_report_patch(metadata_only, {'form': dict(form)})
    assert merged['form'] == form
    assert 'implantPlan' not in merged and 'oarDoseOrdering' not in merged
    assert _report_form_from_section(merged)[0] == form


def test_oar_includes_all_zero_and_missing_without_top_n():
    metrics = {f'organ_{i}': {'object_id': f'oar:{i}', 'd2cc': 0, 'dmax': 0, 'v100': 0} for i in range(53)}
    metrics['missing'] = {'d2cc': None, 'dmax': float('nan')}
    rows = build_oar_rows(metrics)
    assert len(rows) == 54
    assert all(r['d2cc'] == 0 and r['v100'] == 0 for r in rows if r['organ'] != 'missing')
    assert rows[-1]['dmax'] is None
    assert rows[-1]['review_status'] == 'unassessed'


def test_boolean_measurements_are_missing_not_fabricated_one_or_zero():
    rows = build_oar_rows({'invalid': {'dmax': np.bool_(True), 'd2cc': False}})
    assert rows[0]['dmax'] is None and rows[0]['d2cc'] is None
    table = build_implant_table({'needles': [{'id': 'n', 'points': [[0, 0, 10], [0, 0, -10]]}],
                                'seeds': [{'id': 's', 'needle_id': 'n', 'position': [True, 0, 5]}]})
    seed = table['channels'][0]['seeds'][0]
    assert seed['position_world_mm'] is None and seed['tip_distance_mm'] is None
    assert 'invalid_position' in seed['flags'] and table['seed_count'] == 1


def test_priorities_compare_only_source_backed_physical_gy_not_eqd2_or_fuzzy_names():
    metrics = {'spinal_cord': {'d2cc': 11}, 'skull': {'d2cc': 100}, 'artery_left': {'d2cc': 2}, 'artery_right': {'d2cc': 30}}
    rationale = {'sources': ['https://example.test/recorded-protocol'], 'oar_criteria': {
        'spinal_cord': {'d2cc_gy': 10}, 'skull': {'d2cc_gy_eqd2': 90}, 'artery': {'d2cc_gy': 1}}}
    rows = build_oar_rows(metrics, rationale=rationale, priorities=['artery_left'])
    assert [r['organ'] for r in rows] == ['spinal_cord', 'artery_left', 'skull', 'artery_right']
    assert rows[0]['review_status'] == 'criterion_review'
    assert rows[2]['constraint_utilization'] is None
    assert rows[3]['reference_metric'] is None
    assert build_oar_rows(metrics, rationale={'oar_criteria': rationale['oar_criteria']})[0]['organ'] == 'skull'
    assert all(r['constraint_utilization'] is None for r in build_oar_rows(metrics, rationale=rationale, stale=True))


@pytest.mark.parametrize('basis', ['eqd2', 'EQD2_Gy', 'bed', 'cgy'])
def test_nonphysical_criteria_never_compared(basis):
    rows = build_oar_rows({'organ': {'dmax': 100}}, rationale={'sources': ['https://example.test'], 'oar_criteria': {'organ': {'dmax_gy': 10, 'dose_basis': basis}}})
    assert rows[0]['constraint_utilization'] is None


def test_row_units_names_ids_and_fields_preserved():
    rows = build_oar_rows({'internal:key': {'object_id': 'roi:1', 'label_id': 2, 'display_name': 'brain', 'v100': .5, 'volume_metric_units': 'percent', 'dmax': 0, 'mean_dose': 2, 'd90': 1, 'volume_cm3': 8}})
    assert rows[0]['organ'] == 'brain'
    assert rows[0]['object_id'] == 'roi:1'
    assert rows[0]['v100'] == .5
    assert rows[0]['dmean'] == 2
    assert build_oar_rows({'other': {'v100': None}})[0]['v100'] is None


def test_tip_reference_actual_xyz_sorting_and_off_axis_are_not_snapped():
    snapshot = {'needles': [{'id': 'needle_2', 'trajectory_id': 'traj_2', 'points': [[20, 30, 40], [-20, -10, 0]]}],
                'seeds': [{'id': 'seed_b', 'trajectory_id': 'traj_2', 'position': [8, 18, 28]}, {'id': 'seed_a', 'needle_id': 'needle_2', 'position': [0, 10, 20]}, {'id': 'seed_off', 'trajectory_id': 'traj_2', 'position': [5, 10, 20]}]}
    resolve = lambda *_: ([-10, 0, 10], {'source': 'synthetic'})
    table = build_implant_table(snapshot, entry_resolver=resolve)
    channel = table['channels'][0]
    assert channel['entry_world_mm'] == [-10, 0, 10]
    assert channel['tip_world_mm'] == [20, 30, 40]
    assert channel['insertion_length_mm'] == pytest.approx(30 * np.sqrt(3))
    assert channel['seeds'][0]['seed_id'] == 'seed_b'
    assert channel['seeds'][0]['tip_distance_mm'] == pytest.approx(12 * np.sqrt(3))
    assert channel['seeds'][1]['position_world_mm'] == [5, 10, 20]
    assert 'off_axis' in channel['seeds'][1]['flags']
    assert channel['seeds'][2]['distance_from_previous_mm'] == pytest.approx(5 / np.sqrt(3))


def test_external_endpoint_never_substitutes_for_missing_skin_entry():
    data = {'needles': [{'id': 'n', 'points': [[0,0,40], [0,0,-150]]}], 'seeds': [{'id': 's', 'needle_id': 'n', 'position': [0,0,20]}]}
    channel = build_implant_table(data)['channels'][0]
    assert channel['entry_world_mm'] is None
    assert channel['seeds'][0]['tip_distance_mm'] == 20
    assert channel['seeds'][0]['position_world_mm'] == [0,0,20]


def test_duplicate_ambiguous_unowned_and_invalid_records_account_for_every_seed():
    data = {'needles': [{'id': 'n', 'trajectory_id': 't', 'points': [[0,0,20],[0,0,-20]]}] * 2,
            'seeds': [{'id': 's', 'trajectory_id': 't', 'position': [0,0,5]}, {'id': 's', 'trajectory_id': 't', 'position': [0,0,6]}, {'id': 'bad', 'position': [np.nan,0,0]}]}
    table = build_implant_table(data)
    assert table['seed_count'] == 3
    assert len(table['unassigned_seeds']) == 3
    assert table['assigned_seed_count'] == 0
    assert 'duplicate_seed_identity' in table['unassigned_seeds'][0]['flags']
    assert table['unassigned_seeds'][-1]['position_world_mm'] is None


def test_outside_span_is_signed_not_clamped():
    data = {'needles': [{'id': 'n', 'points': [[0,0,40],[0,0,-20]]}], 'seeds': [{'id': 's', 'needle_id': 'n', 'position': [0,0,45]}]}
    row = build_implant_table(data, entry_resolver=lambda *_: ([0,0,0], {}))['channels'][0]['seeds'][0]
    assert row['tip_distance_mm'] == -5
    assert 'outside_insertion_span' in row['flags']


def test_explicitly_empty_manual_plan_never_resurrects_automatic_geometry():
    memory = Memory(manual_plan_active=True, manual_seeds=[], manual_needles=[], algorithm_plan_snapshot={'seeds': [{'id':'old'}]})
    assert report_snapshot(memory) == {'seeds': [], 'needles': []}


def test_automatic_snapshot_retains_seed_without_direction_and_malformed_position():
    memory = Memory(seed_plan_serialized=[{'seeds': [{'position':[1,2,3]}, {'position':[np.nan,2,3]}]}], verified_needle_geometry={'0': [[1,2,20],[1,2,-20]]})
    table = build_implant_table(report_snapshot(memory))
    assert table['seed_count'] == table['assigned_seed_count'] == 2
    assert table['channels'][0]['seeds'][1]['position_world_mm'] is None


@pytest.mark.parametrize('array_points', [False, True])
def test_checkpoint_roundtrip_keeps_automatic_needle_axis_and_tip_distances(tmp_path, array_points):
    from web.workspace_store import _ArtifactEncoder, _decode_artifacts
    points = [[0., 0., 40.], [0., 0., -20.]]
    payload = {
        'seed_plan_serialized': [{'seeds': [
            {'position': np.array([0., 0., 25.])},
            {'position': [0., 0., 20.]},
        ]}],
        'verified_needle_geometry': {'0': np.asarray(points) if array_points else points},
    }
    restored = _decode_artifacts(_ArtifactEncoder(tmp_path).encode(payload, 'memory'), tmp_path)
    assert 0 in restored['verified_needle_geometry']
    table = build_implant_table(report_snapshot(Memory(**restored)))
    channel = table['channels'][0]
    assert channel['tip_world_mm'] == [0., 0., 40.]
    assert [s['tip_distance_mm'] for s in channel['seeds']] == [15., 20.]
    assert [s['axis_offset_mm'] for s in channel['seeds']] == [0., 0.]
    assert channel['seeds'][1]['distance_from_previous_mm'] == 5.
    assert channel['seeds'][0]['spacing_status'] == 'not_applicable_first'
    assert channel['seeds'][1]['spacing_status'] == 'measured'
    assert all('needle_axis_unavailable' not in s['flags'] for s in channel['seeds'])


@pytest.mark.parametrize('container', [list, tuple, np.asarray])
def test_manual_axis_accepts_saved_numeric_endpoint_containers(container):
    memory = Memory(manual_plan_active=True,
                    manual_needles=[{'id': 'n', 'points': container([[0, 0, 40], [0, 0, -20]])}],
                    manual_seeds=[{'id': 's', 'needle_id': 'n', 'position': [0, 0, 25]}])
    table = build_implant_table(report_snapshot(memory))
    assert table['channels'][0]['tip_world_mm'] == [0., 0., 40.]
    assert table['channels'][0]['seeds'][0]['tip_distance_mm'] == 15.


def test_current_string_key_geometry_repair_wins_over_old_integer_key():
    memory = Memory(seed_plan_serialized=[{'seeds': [{'position': [0, 0, 25]}]}],
                    verified_needle_geometry={0: [[0, 0, 50], [0, 0, -20]],
                                              '0': [[0, 0, 40], [0, 0, -20]]})
    channel = build_implant_table(report_snapshot(memory))['channels'][0]
    assert channel['tip_world_mm'] == [0., 0., 40.]
    assert channel['seeds'][0]['tip_distance_mm'] == 15.


@pytest.mark.parametrize('points', [None, np.array(1), np.array([0, 0, 40]),
                                  [[0, 0, 40], [0, 0]],
                                  [[0, 0, 40], [0, 0, np.nan]],
                                  [[0, 0, True], [0, 0, -20]],
                                  [[0, 0, 40], [0, 0, 40]]])
def test_invalid_endpoint_payloads_stay_unavailable_not_invented(points):
    data = {'needles': [{'id': 'n', 'points': points}],
            'seeds': [{'id': 's', 'needle_id': 'n', 'position': [0, 0, 25]}]}
    channel = build_implant_table(data)['channels'][0]
    assert channel['entry_reason'] == 'invalid_needle_geometry'
    assert channel['seeds'][0]['tip_distance_mm'] is None
    assert channel['seeds'][0]['spacing_status'] == 'unavailable'
    assert channel['seeds'][0]['position_world_mm'] == [0., 0., 25.]


def test_missing_geometry_does_not_use_stale_automatic_baseline():
    memory = Memory(seed_plan_serialized=[{'seeds': [{'position': [0, 0, 25]}]}],
                    algorithm_plan_snapshot={'needles': [{'id': 'old', 'trajectory_id': 'traj_1',
                                                       'points': [[0, 0, 50], [0, 0, -20]]}]})
    channel = build_implant_table(report_snapshot(memory))['channels'][0]
    assert channel['tip_world_mm'] is None
    assert channel['seeds'][0]['position_world_mm'] == [0., 0., 25.]


def test_saved_skin_entry_uses_physical_direction_spacing_and_origin():
    body = np.zeros((50,50,50), np.uint8)
    body[10:40,10:40,10:40] = 1
    image = sitk.GetImageFromArray(body)
    image.SetSpacing((1,2,3))
    image.SetOrigin((100,-80,40))
    image.SetDirection((0,-1,0,1,0,0,0,0,1))
    metadata = {'spacing': list(image.GetSpacing()), 'origin': list(image.GetOrigin()), 'direction': list(image.GetDirection()), 'data_version': 4}
    memory = Memory(ct_image=image, skin_surface_mask=body, skin_surface=metadata)
    resolver = _entry_resolver(SimpleNamespace(memory=memory))
    tip = np.asarray(image.TransformIndexToPhysicalPoint((35,25,25)))
    external = np.asarray(image.TransformIndexToPhysicalPoint((0,25,25)))
    entry, method = resolver({}, tip, external)
    assert image.TransformPhysicalPointToContinuousIndex(tuple(entry))[0] == pytest.approx(9.5, abs=.6)
    assert method['skin_data_version'] == 4
    metadata['origin'][0] += 10
    assert _entry_resolver(SimpleNamespace(memory=memory)) is None


def test_generation_rejects_geometry_revision_changed_mid_report(monkeypatch):
    memory = Memory(manual_plan_active=True, manual_plan_version=1, manual_seeds=[], manual_needles=[])
    monkeypatch.setattr('web.planning_runs.active_planning_id', lambda _: 'plan')
    monkeypatch.setattr('web.report_plan_tables._entry_resolver', lambda _: memory.data.update(manual_plan_version=2))
    monkeypatch.setattr('web.structure_dvh.complete_structure_analysis', lambda *a, **k: {'oar_metrics':{}, 'coverage':{}})
    with pytest.raises(ValueError, match='changed'):
        report_table_patch(SimpleNamespace(memory=memory), rationale={})


def test_owned_direct_tool_failure_never_falls_back_to_another_agent(monkeypatch):
    from tool_factory.output.report_auto_fill import ReportAutoFillTool
    tool = ReportAutoFillTool()
    def changed(*args):
        raise ValueError('Report geometry changed during generation')
    def forbidden(*args):
        raise AssertionError('Must not query a different, unscoped agent')
    monkeypatch.setattr(tool, '_build_patch_from_agent', changed)
    monkeypatch.setattr(tool, '_in_process_call', forbidden)
    monkeypatch.setattr('requests.post', forbidden)
    result = tool._execute(_agent=SimpleNamespace(memory=Memory()), language='en')
    assert result.success is False
    assert 'geometry changed' in result.error


def test_direct_tool_uses_shared_complete_tables(monkeypatch):
    from tool_factory.output.report_auto_fill import ReportAutoFillTool
    tool = ReportAutoFillTool()
    patch = {'oarDose': build_oar_rows({f'oar_{i}': {'d2cc': 0} for i in range(53)}),
             'implantPlan': build_implant_table({'needles': [], 'seeds': []})}
    monkeypatch.setattr('tool_factory.output.report_auto_fill.resolve_report_facts', lambda *a: {})
    monkeypatch.setattr('web.report_plan_tables.report_table_patch', lambda *a: patch)
    generated, provenance = tool._build_patch_from_agent(SimpleNamespace(memory=Memory(), config={}), 'all', 'en')
    assert generated['oarDose'] == patch['oarDose']
    assert generated['implantPlan'] == patch['implantPlan']
    assert set(patch).issubset(provenance['derived'])


@pytest.mark.parametrize('restored_automatic', [False, True])
def test_authenticated_report_api_uses_complete_tables_and_rejects_old_revision(tmp_path, monkeypatch, restored_automatic):
    from web.server import create_app
    app = create_app({'runtime_dir': str(tmp_path / 'runtime'), 'secret_key': 'synthetic-test-key',
                      'workspace_maintenance': False})
    memory = Memory(manual_plan_active=True, manual_plan_version=3,
                    manual_needles=[{'id': 'n', 'points': [[0,0,40],[0,0,-20]]}],
                    manual_seeds=[{'id': 's', 'needle_id': 'n', 'position': [0,0,25]}])
    if restored_automatic:
        from web.workspace_store import _ArtifactEncoder, _decode_artifacts
        payload = {'manual_plan_version': 3, 'seed_plan_serialized': [{'seeds': [{'position': [0,0,25]}]}],
                   'verified_needle_geometry': {'0': np.array([[0,0,40],[0,0,-20]])}}
        root = tmp_path / 'checkpoint'
        memory = Memory(**_decode_artifacts(_ArtifactEncoder(root).encode(payload, 'memory'), root))
    agent = SimpleNamespace(memory=memory, config={})
    # Substitute only this isolated app's agent provider; retain real routing,
    # authentication/CSRF, report handler, and shared numerical table builder.
    handler = inspect.unwrap(app.view_functions['api_report_auto_fill'])
    provider = dict(zip(handler.__code__.co_freevars, handler.__closure__))['get_agent']
    provider.cell_contents = lambda *a, **k: agent
    monkeypatch.setattr('web.planning_runs.active_planning_id', lambda _: 'plan')
    monkeypatch.setattr('web.report_plan_tables._entry_resolver', lambda _: None)
    monkeypatch.setattr('web.structure_dvh.complete_structure_analysis', lambda *a, **k: {
        'oar_metrics': {f'organ_{i}': {'dmax': 0, 'd2cc': 0} for i in range(53)},
        'coverage': {'status': 'complete'}})
    client = app.test_client()
    registered = client.post('/api/auth/register', json={'username': 'report_tables_test',
                                'password': 'synthetic-report-password-123'})
    assert registered.status_code == 201
    headers = {'X-CSRF-Token': registered.get_json()['csrf_token']}
    response = client.post('/api/report/auto-fill', json={'scope': 'all', 'sources': ['planning'],
                            'planning_id': 'plan', 'planning_version': 3, 'language': 'en'}, headers=headers)
    assert response.status_code == 200, response.get_json()
    patch = response.get_json()['patch']
    assert len(patch['oarDose']) == 53
    assert patch['implantPlan']['channels'][0]['seeds'][0]['tip_distance_mm'] == 15
    assert patch['implantPlan']['channels'][0]['seeds'][0]['axis_offset_mm'] == 0
    assert patch['implantPlan']['channels'][0]['seeds'][0]['spacing_status'] == 'not_applicable_first'
    conflict = client.post('/api/report/auto-fill', json={'planning_id': 'plan',
                            'planning_version': 2}, headers=headers)
    assert conflict.status_code == 409
    assert 'patch' not in conflict.get_json()
