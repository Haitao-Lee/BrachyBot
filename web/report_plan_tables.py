"""Identity-owned OAR and implant tables for every report generation path.

These are read-only derivatives of saved structures, dose and world geometry.
No planning, segmentation, skin thresholding or coordinate reconstruction runs.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
import hashlib
import json
import math
import re

import numpy as np


def _number(value):
    if value is None or value == '' or isinstance(value, (bool, np.bool_)):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def _point(value):
    try:
        raw = np.asarray(value, dtype=object)
        if raw.shape != (3,) or any(isinstance(v, (bool, np.bool_)) for v in raw):
            return None
        array = np.asarray(value, dtype=float)
        return array if array.shape == (3,) and np.isfinite(array).all() else None
    except (ValueError, TypeError):
        return None


def _get(memory, key, default=None):
    value = memory.retrieve(key)
    return default if value is None else value


def _natural(value):
    return tuple((1, int(part)) if part.isdigit() else (0, part.lower())
                 for part in re.split(r'(\d+)', str(value)))


def _normalized(value):
    return re.sub(r'[^a-z0-9]+', '_', str(value).lower()).strip('_')


def _percent(value, units):
    value = _number(value)
    if value is None:
        return None
    kind = str(units or '').lower()
    if kind in {'fraction', 'ratio', '0-1'}:
        return value * 100 if 0 <= value <= 1 else None
    if kind in {'percent', 'percentage', '0-100'}:
        return value if 0 <= value <= 100 else None
    return value * 100 if 0 <= value <= 1 else value if 0 <= value <= 100 else None


def build_oar_rows(metrics, *, units=None, rationale=None, priorities=None, stale=False):
    """Include all rows, including measured zero and unavailable results.

    Review ordering is NOT a universal clinical importance ranking. Only exact
    criteria with their own sources (or the report's sources) and comparable
    physical-Gy upper bounds contribute a utilization ratio. EQD2 and defaults
    must not be compared with unconverted physical dose.
    """
    rationale = rationale if isinstance(rationale, Mapping) else {}
    criteria = rationale.get('oar_criteria') or {}
    criteria = criteria if isinstance(criteria, Mapping) else {}
    source_urls = [s if isinstance(s, str) else s.get('url') for s in rationale.get('sources', []) if isinstance(s, (str, Mapping))]
    priority_ids = list(priorities) if isinstance(priorities, (list, tuple)) else []
    rows = []
    for key, values in (metrics or {}).items():
        if not isinstance(values, Mapping):
            continue
        name = str(values.get('display_name') or values.get('organ') or key)
        row = {'organ': name, 'object_id': values.get('object_id'), 'label_id': values.get('label_id'),
               'computed_fields': list(values.get('computed_fields') or [])}
        aliases = {'dmax': ('dmax', 'max_dose'), 'dmean': ('dmean', 'mean_dose', 'dmean_gy'),
                   'volume_cm3': ('volume_cm3', 'volume_cc')}
        for field in ('dmax', 'dmean', 'd0_1cc', 'd1cc', 'd2cc', 'd90', 'd95', 'volume_cm3'):
            row[field] = next((n for alias in aliases.get(field, (field,))
                               if (n := _number(values.get(alias))) is not None and n >= 0), None)
        row['v100'] = _percent(values.get('v100'), values.get('volume_metric_units', units))
        row['review_status'] = 'stale' if stale else 'observed'
        row['reference_metric'] = None
        row['reference_limit_gy'] = None
        row['reference_sources'] = []
        row['constraint_utilization'] = None
        row['priority_index'] = next((i for i, p in enumerate(priority_ids)
                                     if str(p) in {str(row['object_id']), name}), None)
        candidates = [v for n, v in criteria.items() if _normalized(n) == _normalized(name) or str(n) == str(row['object_id'])]
        criterion = candidates[0] if len(candidates) == 1 and isinstance(candidates[0], Mapping) else {}
        own_sources = criterion.get('sources') or source_urls
        if isinstance(own_sources, str):
            own_sources = [own_sources]
        own_sources = [s if isinstance(s, str) else s.get('url') for s in own_sources if isinstance(s, (str, Mapping))]
        own_sources = [s for s in own_sources if isinstance(s, str) and s.startswith(('https://', 'http://'))]
        row['has_site_criterion'] = bool(criterion and own_sources)
        dose_basis = str(criterion.get('dose_basis') or criterion.get('dose_unit') or '').lower()
        ratios = []
        if own_sources and not stale and not any(unit in dose_basis for unit in ('eqd2', 'bed', 'cgy')):
            for metric in ('d2cc', 'd1cc', 'd0_1cc', 'dmax', 'dmean'):
                limit = _number(criterion.get(metric + '_gy'))
                if limit is not None and limit > 0 and row[metric] is not None:
                    ratios.append((row[metric] / limit, metric, limit))
        if ratios:
            ratio, metric, limit = max(ratios)
            row.update(constraint_utilization=ratio, reference_metric=metric,
                       reference_limit_gy=limit, reference_sources=own_sources,
                       review_status='criterion_review' if ratio > 1 else 'compared')
        if not any(row[f] is not None for f in ('dmax', 'dmean', 'd0_1cc', 'd1cc', 'd2cc')):
            row['review_status'] = 'unassessed'
        row['importance_basis'] = ('criterion_review' if row['review_status'] == 'criterion_review'
                                   else 'case_priority' if row['priority_index'] is not None
                                   else 'constraint_utilization' if ratios
                                   else 'site_criterion' if row['has_site_criterion']
                                   else 'unassessed' if row['review_status'] == 'unassessed'
                                   else 'observed_dose')
        rows.append(row)
    rows.sort(key=lambda r: (0 if r['review_status'] == 'criterion_review' else 1,
                            r['priority_index'] if r['priority_index'] is not None else math.inf,
                            0 if r['has_site_criterion'] else 1,
                            -(r['constraint_utilization'] if r['constraint_utilization'] is not None else -1),
                            -(r['d2cc'] if r['d2cc'] is not None else -1),
                            -(r['dmax'] if r['dmax'] is not None else -1),
                            _natural(r['organ']), str(r['object_id'] or '')))
    for index, row in enumerate(rows):
        row['review_order'] = index + 1
    return rows


def report_snapshot(memory):
    """Match current Viewer authority, including an explicitly empty manual plan."""
    seeds, needles = _get(memory, 'manual_seeds'), _get(memory, 'manual_needles')
    if _get(memory, 'manual_plan_active') or seeds or needles:
        return {'seeds': list(seeds or []), 'needles': list(needles or [])}
    serialized = _get(memory, 'seed_plan_serialized')
    if isinstance(serialized, list) and serialized:
        # Match public one-based IDs, but never silently omit a seed just
        # because its direction/position is malformed. The report must account
        # for every saved record and expose unassessed geometry.
        geometry = _get(memory, 'verified_needle_geometry', {})
        geometry = geometry if isinstance(geometry, Mapping) else {}
        snapshot = {'seeds': [], 'needles': []}
        for i, entry in enumerate(serialized):
            entry = entry if isinstance(entry, Mapping) else {}
            tid = f'traj_{i + 1}'
            # JSON checkpoint decoding restores numeric keys to integers.
            # Match the Viewer: a newer string-keyed repair takes precedence,
            # then read the restored integer key. Never infer endpoints from
            # seed centers or substitute another planning revision.
            points = geometry.get(str(i))
            if points is None:
                points = geometry.get(i)
            snapshot['needles'].append({'id': f'needle_{i + 1}', 'trajectory_id': tid, 'points': points})
            for j, seed in enumerate(entry.get('seeds') or []):
                if isinstance(seed, Mapping):
                    position = seed.get('position') if seed.get('position') is not None else seed.get('pos')
                elif isinstance(seed, (list, tuple)) and len(seed) >= 1:
                    position = seed[0]
                else:
                    position = None
                snapshot['seeds'].append({'id': f'seed_{i + 1}_{j + 1}', 'trajectory_id': tid, 'position': position})
        return snapshot
    baseline = _get(memory, 'algorithm_plan_snapshot', {})
    return {'seeds': list(baseline.get('seeds') or []), 'needles': list(baseline.get('needles') or [])}


def _signature(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=lambda v: v.tolist() if isinstance(v, np.ndarray) else str(v)).encode()).hexdigest()


def build_implant_table(snapshot, *, entry_resolver=None, coordinate_system='patient_world_mm'):
    """Distance is signed projection from needle tip back toward skin.

    Keep every seed, including invalid/unassigned/duplicate records. Do not snap
    sources to the axis, assign nearest needles, reverse axes using seeds, or
    substitute an external handle for the skin entry.
    """
    needles, seeds = snapshot.get('needles') or [], snapshot.get('seeds') or []
    owners = defaultdict(list)
    needle_counts = Counter(str(n.get('id') or '') for n in needles if isinstance(n, Mapping))
    seed_counts = Counter(str(s.get('id') or '') for s in seeds if isinstance(s, Mapping))
    channels = []
    for index, needle in enumerate(needles):
        needle = needle if isinstance(needle, Mapping) else {}
        nid = str(needle.get('id') or f'unnamed_needle_{index + 1}')
        tid = str(needle.get('trajectory_id') or nid)
        points = needle.get('points')
        # Restored small coordinate artifacts legitimately remain ndarrays.
        # Check their shape rather than their truth value; invalid/scalar
        # arrays still produce an explicitly unavailable axis.
        has_endpoints = (isinstance(points, (list, tuple, np.ndarray))
                         and (not isinstance(points, np.ndarray) or points.ndim == 2)
                         and len(points) >= 2)
        tip = _point(points[0]) if has_endpoints else None
        external = _point(points[-1]) if has_endpoints else None
        channel = {'needle_id': nid, 'trajectory_id': tid, 'tip_world_mm': tip.tolist() if tip is not None else None,
                   'external_world_mm': external.tolist() if external is not None else None,
                   'entry_world_mm': None, 'insertion_length_mm': None, 'entry_status': 'unavailable',
                   'entry_reason': 'saved_skin_unavailable', 'seeds': [], '_index': index}
        axis = tip - external if tip is not None and external is not None else None
        if axis is None or np.linalg.norm(axis) < 1e-6:
            channel['entry_reason'] = 'invalid_needle_geometry'
        elif needle_counts[nid] > 1:
            channel['entry_reason'] = 'duplicate_needle_identity'
        else:
            channel['_axis'] = axis / np.linalg.norm(axis)
            if entry_resolver is not None:
                try:
                    entry, method = entry_resolver(needle, tip, external)
                    entry = _point(entry)
                    if entry is None:
                        raise ValueError('invalid_skin_entry')
                    offset = entry - external
                    if np.linalg.norm(offset - np.dot(offset, channel['_axis']) * channel['_axis']) > .01:
                        raise ValueError('skin_entry_off_axis')
                    length = float(np.dot(tip - entry, channel['_axis']))
                    if length < 0 or np.dot(offset, channel['_axis']) < 0:
                        raise ValueError('skin_entry_outside_segment')
                    channel.update(entry_world_mm=entry.tolist(), insertion_length_mm=length,
                                   entry_status='sampled', entry_reason=None, entry_method=method)
                except (ValueError, RuntimeError) as exc:
                    channel['entry_reason'] = str(exc)
        channels.append(channel)
        for key in {nid, tid}:
            owners[key].append(channel)
    unassigned = []
    for index, seed in enumerate(seeds):
        seed = seed if isinstance(seed, Mapping) else {}
        sid = str(seed.get('id') or f'unnamed_seed_{index + 1}')
        value = seed.get('position') if seed.get('position') is not None else seed.get('pos')
        pos = _point(value)
        row = {'seed_id': sid, 'position_world_mm': pos.tolist() if pos is not None else None,
               'tip_distance_mm': None, 'axis_offset_mm': None, 'distance_from_previous_mm': None,
               'spacing_status': 'unavailable',
               'flags': [], '_index': index}
        if pos is None:
            row['flags'].append('invalid_position')
        if seed_counts[sid] > 1:
            row['flags'].append('duplicate_seed_identity')
        keys = [str(seed.get(k) or '') for k in ('needle_id', 'trajectory_id') if seed.get(k)]
        matches = [owners.get(k, []) for k in keys]
        candidates = [c for c in channels if matches and all(any(c is owner for owner in group) for group in matches)]
        if len(candidates) != 1:
            row['flags'].append('ambiguous_or_missing_owner')
            unassigned.append(row)
            continue
        channel = candidates[0]
        if pos is not None and channel.get('_axis') is not None:
            displacement = np.asarray(channel['tip_world_mm']) - pos
            distance = float(np.dot(displacement, channel['_axis']))
            offset = float(np.linalg.norm(displacement - distance * channel['_axis']))
            row.update(tip_distance_mm=distance, axis_offset_mm=offset)
            if offset > .1:
                row['flags'].append('off_axis')
            if distance < 0 or (channel['insertion_length_mm'] is not None and distance > channel['insertion_length_mm']):
                row['flags'].append('outside_insertion_span')
        elif pos is not None:
            row['flags'].append('needle_axis_unavailable')
        channel['seeds'].append(row)
    channels.sort(key=lambda c: _natural(c['needle_id']))
    for channel in channels:
        channel['seeds'].sort(key=lambda r: (r['tip_distance_mm'] is None, r['tip_distance_mm'] or 0, _natural(r['seed_id']), r['_index']))
        previous = None
        for row in channel['seeds']:
            if row['tip_distance_mm'] is not None:
                if previous is not None:
                    row['distance_from_previous_mm'] = row['tip_distance_mm'] - previous
                    row['spacing_status'] = 'measured'
                else:
                    row['spacing_status'] = 'not_applicable_first'
                previous = row['tip_distance_mm']
    for row in [*channels, *unassigned, *(s for c in channels for s in c['seeds'])]:
        row.pop('_index', None)
        row.pop('_axis', None)
    return {'version': 1, 'coordinate_system': coordinate_system, 'units': 'mm',
            'distance_reference': 'needle_tip',
            'distance_definition': 'signed_axis_projection_from_needle_tip_toward_skin_to_seed_center',
            'axis_offset_review_mm': .1, 'channels': channels, 'unassigned_seeds': unassigned,
            'needle_count': len(channels), 'seed_count': len(seeds),
            'assigned_seed_count': sum(len(c['seeds']) for c in channels),
            'skin_entry_available_count': sum(c['entry_world_mm'] is not None for c in channels),
            'geometry_signature': _signature(snapshot)}


def _entry_resolver(agent):
    memory = agent.memory
    image, mask = _get(memory, 'ct_image'), _get(memory, 'skin_surface_mask')
    metadata = _get(memory, 'skin_surface', {})
    if image is None or mask is None or not isinstance(metadata, Mapping):
        return None
    mask = np.asarray(mask)
    if mask.shape != tuple(reversed(image.GetSize())) or not np.isfinite(mask).all() or not np.any(mask):
        return None
    for key, actual in (('spacing', image.GetSpacing()), ('origin', image.GetOrigin()), ('direction', image.GetDirection())):
        recorded = metadata.get(key)
        if recorded is None or len(recorded) != len(actual) or not np.allclose(recorded, actual, atol=1e-4, rtol=0):
            return None
    from web.surgical_guide import _sample_skin_entry, _truncated_boundary_faces, _segment_crosses_truncated_boundary
    faces = _truncated_boundary_faces(mask)
    def resolve(needle, tip, external):
        if _segment_crosses_truncated_boundary(image, tip, external, faces, body_mask=mask):
            raise ValueError('truncated_ct_entry')
        entry, _ = _sample_skin_entry(image, mask, tip, external,
                                     truncated_boundary_faces=faces,
                                     truncated_z_min=faces['z_min'], truncated_z_max=faces['z_max'])
        return entry, {'source': 'saved_guide_skin_envelope', 'skin_data_version': metadata.get('data_version'),
                       'sampling_step_mm': max(.25, min(.75, min(image.GetSpacing()) * .5))}
    return resolve


def report_table_patch(agent, scope='all', rationale=None):
    """Shared by the authenticated API and direct agent tool; no HTTP loopback."""
    from web.planning_runs import active_planning_id
    memory = agent.memory
    planning_id = active_planning_id(memory)
    version = _get(memory, 'manual_plan_version', 0)
    snapshot = report_snapshot(memory)
    before = _signature(snapshot)
    config = _get(memory, 'plan_config', {})
    config = config if isinstance(config, Mapping) else {}
    if rationale is None:
        from tool_factory.report_context import build_prescription_rationale
        rationale = build_prescription_rationale(memory)
    patch = {}
    if scope in {'all', 'oar'}:
        from web.routes.planning_routes import _dose_display_context, _saved_dose_scale_gy, _dose_overlay_volume_array
        from web.routes.viewer_routes import _viewer_display_label_arrays
        from web.structure_dvh import complete_structure_analysis
        context = _dose_display_context(agent)
        result = complete_structure_analysis(agent, context, _saved_dose_scale_gy(agent, context.get('metrics')),
                                             label_resolver=_viewer_display_label_arrays, dose_resolver=_dose_overlay_volume_array)
        metrics = result['oar_metrics'] or _get(memory, 'oar_metrics', {}) or (context.get('metrics') or {}).get('oar_metrics', {})
        patch['oarDose'] = build_oar_rows(metrics, units=(context.get('metrics') or {}).get('volume_metric_units'),
                                          rationale=rationale, priorities=config.get('oar_review_priorities'), stale=bool(context.get('stale')))
        patch['oarDoseOrdering'] = {'version': 1, 'policy': 'case_review_priority_then_comparable_limit_then_observed_dose',
                                    'planning_id': planning_id, 'coverage': result['coverage'], 'stale': bool(context.get('stale'))}
    if scope == 'all':
        patch['planning.prescriptionRationale'] = rationale
        patch['implantPlan'] = build_implant_table(snapshot, entry_resolver=_entry_resolver(agent),
                                                  coordinate_system=config.get('seed_coordinate_space') or 'patient_world_mm')
        patch['implantPlan'].update(planning_id=planning_id, planning_version=version)
    if planning_id != active_planning_id(memory) or version != _get(memory, 'manual_plan_version', 0) or before != _signature(report_snapshot(memory)):
        raise ValueError('Report geometry changed during generation; retry current plan')
    return patch
