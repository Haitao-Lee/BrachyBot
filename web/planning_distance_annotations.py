"""Read-only, version-owned companion annotations in patient-world millimetres.

Guide anchors are the generated primary sleeve's nominal outer mouth centre,
not the skin entry or an invented mesh intersection. No inference or generation
is performed here. Presentation is stored by the existing annotation workspace.
"""
from collections import Counter
from collections.abc import Mapping
import hashlib
import math

import numpy as np

from web.report_plan_tables import build_implant_table, report_snapshot, _point, _signature


def build_distance_annotations(snapshot, *, planning_id, planning_version=0, guide=None, guide_current=False):
    table = build_implant_table(snapshot)
    records, unavailable = [], []
    planning_id = str(planning_id or '')
    if not planning_id:
        return {'schema_version': 1, 'planning_id': '', 'planning_version': planning_version,
                'records': [], 'unavailable': [], 'geometry_signature': table['geometry_signature']}
    channels = {c['trajectory_id']: c for c in table['channels']}
    trajectory_counts = Counter(c['trajectory_id'] for c in table['channels'])

    def row(kind, source_id, channel, anchor, distance, **extra):
        identity = f'{planning_id}|{kind}|{channel["trajectory_id"]}|{source_id}|{extra.get("guide_version", "")}'
        return {'id': 'annotation_distance_' + hashlib.sha256(identity.encode()).hexdigest()[:24],
                'type': 'planning_distance', 'generated': True, 'kind': kind,
                'planning_id': planning_id, 'planning_version': int(planning_version),
                'source_object_id': source_id, 'needle_id': channel['needle_id'],
                'trajectory_id': channel['trajectory_id'],
                'anchor_world_mm': list(map(float, anchor)), 'tip_distance_mm': float(distance),
                'tip_world_mm': channel['tip_world_mm'], 'external_world_mm': channel['external_world_mm'],
                'reference': 'needle_tip', 'units': 'mm', 'coordinate_system': 'patient_world_mm',
                'visible': True, 'visible3D': True, 'visible2D': False, 'opacity': 1.,
                'color': '#fde68a' if kind == 'seed_tip_distance' else '#67e8f9', **extra}

    for channel in table['channels']:
        for seed in channel['seeds']:
            if seed['tip_distance_mm'] is None or 'duplicate_seed_identity' in seed['flags']:
                unavailable.append({'source_object_id': seed['seed_id'], 'reason': 'invalid_or_ambiguous_geometry'})
                continue
            records.append(row('seed_tip_distance', seed['seed_id'], channel,
                               seed['position_world_mm'], seed['tip_distance_mm'],
                               axis_offset_mm=seed['axis_offset_mm'], geometry_flags=seed['flags']))
    unavailable.extend({'source_object_id': s['seed_id'], 'reason': 'ambiguous_needle_ownership'}
                       for s in table['unassigned_seeds'])

    if isinstance(guide, Mapping) and guide_current:
        parameters = guide.get('parameters') or {}
        offsets = [parameters.get(k) for k in ('skin_clearance_mm', 'plate_thickness_mm', 'sleeve_outward_mm')]
        try:
            if any(isinstance(v, (bool, np.bool_)) for v in offsets):
                raise ValueError('boolean offset')
            offsets = [float(v) for v in offsets]
            if not all(math.isfinite(v) and v >= 0 for v in offsets):
                raise ValueError('invalid offset')
            outer_offset = sum(offsets)
            if not math.isfinite(outer_offset) or offsets[1] <= 0:
                raise ValueError('invalid sleeve extent')
        except (TypeError, ValueError):
            outer_offset = None
        paths = guide.get('needle_paths') or []
        try:
            version_number=float(guide.get('version'))
            version_valid=(not isinstance(guide.get('version'),(bool,np.bool_)) and math.isfinite(version_number)
                           and version_number>0 and version_number.is_integer())
        except (ValueError,TypeError):
            version_valid=False
        path_counts = Counter(str(p.get('trajectory_id') or '') for p in paths if isinstance(p, Mapping))
        for path in paths:
            if not isinstance(path, Mapping):
                continue
            tid = str(path.get('trajectory_id') or '')
            channel = channels.get(tid)
            entry, inward = _point(path.get('entry_world_mm')), _point(path.get('direction_world'))
            reason = None
            if (not version_valid or outer_offset is None or channel is None or entry is None or inward is None
                    or np.linalg.norm(inward) < 1e-8 or path_counts[tid] != 1 or trajectory_counts[tid] != 1):
                reason = 'guide_mouth_geometry_unavailable'
            elif str(guide.get('planning_id') or '') != planning_id or guide.get('planning_version') != planning_version:
                reason = 'guide_revision_mismatch'
            else:
                tip, external = _point(channel['tip_world_mm']), _point(channel['external_world_mm'])
                if tip is None or external is None or np.linalg.norm(tip - external) < 1e-8:
                    reason = 'needle_axis_unavailable'
                else:
                    axis = (tip - external) / np.linalg.norm(tip - external)
                    inward = inward / np.linalg.norm(inward)
                    delta = tip - entry
                    if np.dot(axis, inward) < 1 - 1e-6 or np.linalg.norm(delta - np.dot(delta, axis) * axis) > .01:
                        reason = 'guide_axis_mismatch'
                    else:
                        mouth = entry - inward * outer_offset
                        distance = float(np.dot(tip - mouth, axis))
                        records.append(row('guide_entry_tip_distance', 'surgical_guide:active', channel,
                                           mouth, distance, guide_version=int(guide.get('version') or 0),
                                           skin_entry_world_mm=entry.tolist(),
                                           anchor_definition='generated_primary_sleeve_outer_mouth_axis_center',
                                           geometry_flags=['beyond_needle_tip'] if distance < 0 else []))
            if reason:
                unavailable.append({'source_object_id': str(path.get('needle_id') or tid), 'reason': reason})
    return {'schema_version': 1, 'planning_id': planning_id, 'planning_version': int(planning_version),
            'records': records, 'unavailable': unavailable, 'units': 'mm',
            'geometry_signature': table['geometry_signature'], 'guide_version': guide.get('version') if isinstance(guide, Mapping) else None}


def distance_annotation_packet(agent, snapshot=None, guide_version=None):
    from web.surgical_guide import _current_guide_record, guide_state_for_version, guide_status_payload, guide_bore_quality_ready
    memory = agent.memory
    def active_id():
        # Do not call the legacy history migration while projecting labels.
        # This companion read must not create or activate a Planning run.
        return str(memory.retrieve('active_planning_id') or memory.retrieve('planning_run_id')
                   or memory.retrieve('manual_planning_id') or '')
    planning_id = active_id()
    version = int(memory.retrieve('manual_plan_version') or 0)
    saved_snapshot = report_snapshot(memory)
    signature = _signature(saved_snapshot)
    def read_guide():
        if guide_version is not None:
            return guide_state_for_version(agent, guide_version)
        record = _current_guide_record(agent)
        return record.get('state') if record else None
    def guide_key(g):
        return tuple(g.get(k) for k in ('planning_id','planning_version','version','source_plan_signature')) if isinstance(g,Mapping) else None
    guide = read_guide()
    before_guide = guide_key(guide)
    status = guide_status_payload(agent,guide_version) if guide_version is not None else guide_status_payload(agent)
    current = (status.get('state') == 'ready' and status.get('plan_matches_current') is True
               and guide_bore_quality_ready(guide))
    packet = build_distance_annotations(snapshot if snapshot is not None else saved_snapshot,
                                       planning_id=planning_id, planning_version=version,
                                       guide=guide, guide_current=current)
    if (planning_id != active_id() or version != int(memory.retrieve('manual_plan_version') or 0)
            or signature != _signature(report_snapshot(memory)) or before_guide != guide_key(read_guide())):
        raise ValueError('Planning geometry changed while reading annotations')
    packet['guide_status'] = status.get('state')
    return packet
