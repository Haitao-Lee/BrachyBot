"""Versioned component repairs must not become fabricated formal evidence."""
import copy
import json
from pathlib import Path
import struct
import sys

import numpy as np
import pytest

BB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BB))
from tools import component_replay as cr
from tools import run_task as rt
from tools.gen_physics_fixtures import complete_quantisation_reference, GENERATORS


def _task(tid):
    return json.loads(next((BB/'tasks').rglob(f'{tid}.json')).read_text())


def test_profile_is_component_only_and_all_content_hashes_match():
    profile = cr.load_profile()
    assert profile['comparable_sut_result'] is False
    negatives = BB/'tests/replay/_negatives.json'
    assert cr.sha(negatives) == profile['negative_file_sha256']
    assert sum(e['status'] == 'BLOCKED-evidence' for e in profile['entries'].values()) == 73
    for tid, entry in profile['entries'].items():
        assert cr.sha(BB/entry['task_path']) == entry['task_sha256']
        assert cr.sha(BB/'tests/replay'/f'{tid}.json') == entry['positive_sha256']
        assert entry['reason']


def test_content_hash_cache_revalidates_changed_bytes(tmp_path):
    target = tmp_path / 'corpus.json'
    target.write_text('original')
    first = cr.sha(target)
    assert cr.sha(target) == first
    target.write_text('different bytes')
    assert cr.sha(target) != first


def test_profile_rejects_modified_candidate_and_task():
    tid = 'A6-INTERF-001'
    task = _task(tid)
    raw = json.loads((BB/'tests/replay'/f'{tid}.json').read_text())
    altered = copy.deepcopy(raw)
    altered['response'] = 'a live candidate must never receive replay repair'
    with pytest.raises(ValueError, match='live/candidate'):
        cr.prepare(task, altered, 'positive', BB/'tests/replay')
    task['protocol']['turns'][0]['text'] += ' modified'
    with pytest.raises(ValueError, match='passed task differs'):
        cr.prepare(task, raw, 'positive', BB/'tests/replay')


def test_missing_oar_is_not_filled_or_counted_as_safe():
    tid = 'PLAN-GEO-020'
    task = _task(tid)
    raw = json.loads((BB/'tests/replay'/f'{tid}.json').read_text())
    observation, entry = cr.prepare(task, raw, 'positive', BB/'tests/replay')
    assert observation == raw
    assert entry['status'] == 'BLOCKED-evidence'
    result = rt.evaluate(task, observation, rt.load_initial_state(task))
    cr.assert_component_outcome(result, entry, 'positive')
    assert result['verdict'].startswith('Insufficient')


def test_empty_or_incomplete_reference_is_not_completed_from_candidate():
    tid = 'DOSEPRE-EVAL-211'
    task = _task(tid)
    raw = json.loads((BB/'tests/replay'/f'{tid}.json').read_text())
    observation, entry = cr.prepare(task, raw, 'positive', BB/'tests/replay')
    assert observation == raw
    assert 'dose' not in observation['oracle_inputs']['roundtrip_fidelity']['independent']
    cr.assert_component_outcome(rt.evaluate(task, observation, {}), entry, 'positive')


def test_endpoint_controls_remain_discriminating_without_ignoring_contact():
    tid = 'PLAN2-GEO-006'
    task = _task(tid)
    pos = json.loads((BB/'tests/replay'/f'{tid}.json').read_text())
    neg = json.loads((BB/'tests/replay/_negatives.json').read_text())[tid]
    for role, raw in [('positive', pos), ('negative', neg)]:
        revised, entry = cr.prepare(task, raw, role, BB/'tests/replay')
        cr.assert_component_outcome(rt.evaluate(task, revised, {}), entry, role)
        assert revised['oracle_inputs']['interference_fp']['predictions'][0] == raw['oracle_inputs']['interference_fp']['predictions'][0]
    # The historical zero-distance endpoint contact is still rejected.
    assert rt.evaluate(task, pos, {})['verdict'] == 'Does not meet'


def test_receipt_permission_does_not_authorise_geometry_or_revision():
    tid = 'H-RECEIPT-008'
    task = _task(tid)
    raw = json.loads((BB/'tests/replay'/f'{tid}.json').read_text())
    observation, entry = cr.prepare(task, raw, 'positive', BB/'tests/replay')
    cr.assert_component_outcome(rt.evaluate(task, observation, {}), entry, 'positive')
    observation['oracle_inputs']['state_invariant']['after']['ui']['version_fence']['plan_revision'] += 1
    result = rt.evaluate(task, observation, {})
    assert result['verdict'] == 'Does not meet'


def test_quantisation_migration_preserves_grids_and_labels():
    manifest = json.loads((BB/'fixtures/physics_contract_v2/manifest.json').read_text())
    assert manifest['labels_regenerated_from_checker'] is False
    assert len(manifest['files']) == 25
    for record in manifest['files']:
        old = json.loads((BB/record['source']).read_text())
        new = json.loads((BB/record['migrated']).read_text())
        assert cr.sha(BB/record['source']) == record['source_sha256']
        assert cr.sha(BB/record['migrated']) == record['migrated_sha256']
        assert new['expected'] == old['expected']
        for key in ('first', 'second', 'scaling'):
            assert new['config'][key] == old['config'][key]
        reference = new['config']['component_reference']
        wire = bytes.fromhex(reference['payload_hex'])
        decoded = struct.unpack('<' + 'd' * (len(wire)//8), wire)
        assert np.array_equal(np.asarray(decoded).reshape(4,4,4), new['config']['independent']['dose'])
        result = GENERATORS['dose_quantisation'][1](new['config'])
        assert ('pass' if result.passed else 'fail') == old['expected']['verdict']
        assert not result.evidence_gaps


def test_quantisation_reference_rejects_bad_grids_and_detects_corruption():
    config = json.loads((BB/'fixtures/physics/dose_quantisation-000.json').read_text())['config']
    bad = copy.deepcopy(config)
    bad['first']['dose'][0][0][0] = float('nan')
    with pytest.raises(ValueError):
        complete_quantisation_reference(bad)
    fixed = complete_quantisation_reference(config)
    fixed['independent']['dose'][0][0][0] += 10
    result = GENERATORS['dose_quantisation'][1](fixed)
    assert any(v.code == 'independent_parser_disagrees' for v in result.violations)
