"""Versioned synthetic checker contracts, never formal SUT evidence.

Historical replay bytes remain intact. Each reviewed repair is bound to the
task and both replay hashes. Missing real observations stay BLOCKED, not
manufactured as safe values or silently converted to a passing verdict.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import numpy as np

BB = Path(__file__).resolve().parents[1]
PROFILE = BB / 'tests/replay_contracts/v2.json'
_NEGATIVE_CACHE = {}
_HASH_CACHE = {}


def sha(path):
    path = Path(path)
    info = path.stat()
    stamp = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    key = str(path.resolve())
    previous = _HASH_CACHE.get(key)
    if previous is None or previous[0] != stamp:
        # Stream large replay bundles; validate changed bytes, but do not
        # reread the same 277 MB frozen negative corpus for every item.
        with path.open('rb') as stream:
            checksum = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                checksum.update(block)
            value = checksum.hexdigest()
        _HASH_CACHE[key] = (stamp, value)
    return _HASH_CACHE[key][1]


def load_profile(path=PROFILE):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data['evaluation_mode'] != 'component_self_test' or data['schema_version'] != 2:
        raise ValueError('unsupported component contract profile')
    return data


def prepare(task, observation, role, replay_dir, *, profile=None):
    """Apply only a documented, content-bound synthetic fixture repair."""
    profile = load_profile() if profile is None else profile
    entry = profile['entries'].get(task['id'])
    if entry is None:
        return copy.deepcopy(observation), None
    task_path = BB / entry['task_path']
    if sha(task_path) != entry['task_sha256']:
        raise ValueError(f"component task contract changed: {task['id']}")
    # Check actual passed task too, not only an unrelated file on disk.
    if json.loads(task_path.read_text(encoding='utf-8')) != task:
        raise ValueError(f"passed task differs from reviewed contract: {task['id']}")
    positive = Path(replay_dir) / f"{task['id']}.json"
    negative_file = Path(replay_dir) / '_negatives.json'
    if sha(positive) != entry['positive_sha256'] or sha(negative_file) != profile['negative_file_sha256']:
        raise ValueError(f"legacy replay changed without contract review: {task['id']}")
    negative_sha = profile['negative_file_sha256']
    if role == 'negative' and negative_sha not in _NEGATIVE_CACHE:
        _NEGATIVE_CACHE[negative_sha] = json.loads(negative_file.read_text(encoding='utf-8'))
    expected_raw = json.loads(positive.read_text(encoding='utf-8')) if role == 'positive' else (
        _NEGATIVE_CACHE[negative_sha][task['id']])
    if observation != expected_raw:
        raise ValueError('profile repairs must not apply to live/candidate observations')
    result = copy.deepcopy(observation)
    inputs = result['oracle_inputs'][entry['checker']]
    repair = entry['repair']
    if repair == 'synthetic_planar_mask_contract':
        # Historical 1D toy vectors become explicitly synthetic planar strips.
        # This does not make them valid patient segmentation observations.
        if np.asarray(inputs['pred']).ndim == 1:
            inputs['pred'] = [inputs['pred']]
            inputs['gold'] = [inputs['gold']]
        if np.asarray(inputs['pred']).ndim == 2:
            inputs['spacing_mm'] = inputs.get('spacing_mm', [1.0, 1.0])[:2]
    elif repair == 'separated_endpoint_control':
        # Original touching endpoints are a genuine zero-distance contact.
        # New component controls use a real 5 mm separation, not an old
        # interior-only overlap definition or a changed expected label.
        source = expected_raw if role == 'positive' else json.loads(positive.read_text(encoding='utf-8'))
        controls = {p['id']: p for p in source['oracle_inputs'][entry['checker']]['predictions']}
        for prediction in inputs['predictions']:
            if prediction['id'] not in entry['separated_ids']:
                continue
            original = controls[prediction['id']]
            axis = np.asarray(original['s'][1], dtype=float) - original['s'][0]
            offset = 5.0 * axis / np.linalg.norm(axis)
            prediction['t'] = (np.asarray(original['t']) + offset).tolist()
    elif repair == 'posix_traversal_control':
        if role == 'negative':
            inputs['file_ops'][0]['target'] = inputs['allowed_roots'][0] + '/../../evil'
    elif repair == 'explicit_receipt_permission':
        inputs['allowed_mutations'] = inputs.get('allowed_mutations', []) + entry['allowed_paths']
    elif repair == 'roi_names_component_scope':
        # This fixture tests semantic name preservation, not DICOM geometry.
        inputs['fmt'] = 'generic'
    elif repair not in ('missing_independent_reference', 'missing_oar_observation'):
        raise ValueError(f'unknown reviewed repair {repair}')
    return result, entry


def assert_component_outcome(evaluation, entry, role):
    expected = entry[f'expected_{role}'] if entry else (
        'Meets' if role == 'positive' else 'Does not meet')
    assert evaluation['evaluation_mode'] == 'component_self_test'
    assert evaluation['comparable_sut_result'] is False
    assert evaluation['verdict'] == expected, evaluation
    if entry and role == 'positive' and entry.get('expected_positive_gap_codes'):
        actual = sorted(v['code'] for v in evaluation['merged']['evidence_gaps'])
        assert actual == entry['expected_positive_gap_codes'], evaluation
        assert not evaluation['merged']['violations'], evaluation
