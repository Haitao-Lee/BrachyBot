"""Create versioned component fixture contracts without checker-driven labels.

Never calls an oracle to decide expectations. No historical task, replay,
physics gold or result is overwritten. Use --output-root for a new version.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from tools.component_replay import BB, sha
from tools.gen_physics_fixtures import complete_quantisation_reference

GAP = 'Insufficient evidence for the benchmark criterion'


def migrate(output_root):
    output_root = Path(output_root)
    if (output_root/'tests/replay_contracts/v2.json').exists():
        raise FileExistsError('contract version already exists; do not silently regenerate it')
    replay = BB/'tests/replay'
    negatives = json.loads((replay/'_negatives.json').read_text())
    entries = {}
    for path in sorted((BB/'tasks').rglob('*.json')):
        task = json.loads(path.read_text())
        tid = task['id']
        positive_path = replay/f'{tid}.json'
        if tid not in negatives or not positive_path.exists():
            continue
        pos = json.loads(positive_path.read_text())
        check = task['oracle']['check']
        p = pos.get('oracle_inputs', {}).get(check, {})
        n = negatives[tid].get('oracle_inputs', {}).get(check, {})
        repair, gaps, reason, details = None, [], '', {}
        if check == 'dice_and_hd95' and any(
                np.asarray(side.get('pred')).ndim == 1 or
                (np.asarray(side.get('pred')).ndim == 2 and len(side.get('spacing_mm', [1,1,1])) == 3)
                for side in (p, n)):
            repair, reason = 'synthetic_planar_mask_contract', '1D toy vectors embedded as synthetic 2D strips; 2D masks have two explicit in-plane spacings. Not clinical segmentation evidence.'
        elif check == 'interference_fp':
            separated = [v['id'] for v in p.get('predictions', []) if v.get('predicted_risk') == 'none'
                         and v.get('s', [None,None])[1] == v.get('t', [None])[0]]
            if separated:
                repair, reason = 'separated_endpoint_control', 'Historical positive/negative invert physical contact truth. Replace touching synthetic controls with 5 mm separation; retain interior controls and historical bytes.'
                details['separated_ids'] = separated
        elif check == 'path_traversal_blocked' and any('..\\' in op.get('target', '') for op in n.get('file_ops', [])):
            repair, reason = 'posix_traversal_control', 'Backslash is a literal filename character on POSIX. New POSIX control really escapes the declared root.'
        elif check == 'state_invariant':
            allowed = []
            for prefix, key in [('plan', 'receipts'), ('ui', 'version_fence')]:
                a = p.get('before', {}).get(prefix, {}).get(key)
                b = p.get('after', {}).get(prefix, {}).get(key)
                if prefix == 'ui':
                    a, b = (a or {}).get('state_seq'), (b or {}).get('state_seq')
                if a != b:
                    allowed.append(f'{prefix}.{key}' + ('.state_seq' if prefix == 'ui' else ''))
            if allowed:
                repair, reason = 'explicit_receipt_permission', 'Explicit component policy allows receipt journal and UI sequence bookkeeping only. Plan revision, geometry, dose and terminal status remain protected.'
                details['allowed_paths'] = allowed
        elif check == 'roundtrip_fidelity' and p.get('fmt') == 'dicom' and set(p.get('first', {})) == {'roi_names'}:
            repair, reason = 'roi_names_component_scope', 'ROI-only fixture cannot certify DICOM geometry; test only generic name preservation.'
        elif check == 'roundtrip_fidelity':
            keys = ('roi_names', 'dose_scaling', 'grid', 'geometry', 'labels', 'numbers',
                    'dims', 'origin', 'spacing', 'direction', 'dose', 'volume_mm3', 'watertight')
            independent = p.get('independent')
            absent = [k for k in keys if k in p.get('first', {}) or k in p.get('second', {}) if k not in (independent or {})]
            if not independent or absent:
                repair = 'missing_independent_reference'
                if not independent:
                    gaps.append('roundtrip_self_only')
                if independent is not None:
                    gaps += ['independent_field_missing'] * len(absent)
                reason = 'Historical independent parser output is absent/incomplete. Preserve evidence gap; do not copy candidate values as real observation.'
        elif check == 'hard_constraint':
            for organ, spec in p.get('limits', {}).get('oar_limits', {}).items():
                if p.get('plan', {}).get('oar_metrics', {}).get(organ, {}).get(spec['metric']) is None:
                    gaps.append('oar_metric_missing')
            if gaps:
                repair, reason = 'missing_oar_observation', 'No measured OAR values in this replay. Do not invent below-limit values to make a positive case.'
        if repair:
            entries[tid] = {
                'checker': check, 'task_path': str(path.relative_to(BB)), 'task_sha256': sha(path),
                'positive_sha256': sha(positive_path), 'repair': repair, 'reason': reason,
                'expected_positive': GAP if gaps else 'Meets',
                'expected_positive_gap_codes': sorted(gaps), 'expected_negative': 'Does not meet',
                'status': 'BLOCKED-evidence' if gaps else 'reviewed_synthetic_component', **details,
            }
    profile = {'schema_version': 2, 'evaluation_mode': 'component_self_test',
        'comparable_sut_result': False, 'negative_file_sha256': sha(replay/'_negatives.json'),
        'expectations_source': 'Explicit contract reasoning; no oracle-derived label regeneration', 'entries': entries}
    target = output_root/'tests/replay_contracts/v2.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile, indent=2, sort_keys=True) + '\n')
    physics = output_root/'fixtures/physics_contract_v2'
    physics.mkdir(parents=True, exist_ok=False)
    records = []
    for path in sorted((BB/'fixtures/physics').glob('dose_quantisation-*.json')):
        fixture = json.loads(path.read_text())
        expected = fixture['expected']
        fixture['config'] = complete_quantisation_reference(fixture['config'])
        assert fixture['expected'] == expected
        fixture['contract_migration'] = {'version': 2, 'source_sha256': sha(path),
                                        'expected_verdict_and_codes_changed': False}
        dest = physics/path.name
        dest.write_text(json.dumps(fixture, indent=2, sort_keys=True) + '\n')
        records.append({'source': str(path.relative_to(BB)), 'source_sha256': sha(path),
                        'migrated': str(dest.relative_to(output_root)), 'migrated_sha256': sha(dest)})
    (physics/'manifest.json').write_text(json.dumps({'schema_version': 2,
        'scope': 'synthetic_component_only', 'labels_regenerated_from_checker': False,
        'files': records}, indent=2, sort_keys=True) + '\n')
    return {'reviewed_contracts': len(entries), 'blocked': sum(bool(e['expected_positive_gap_codes']) for e in entries.values()),
            'physics_contracts': len(records)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', required=True)
    print(json.dumps(migrate(parser.parse_args().output_root)))
