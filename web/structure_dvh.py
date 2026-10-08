"""Read-only, identity-owned completion of the Analysis Structure Set.

Reuse valid persisted curves/metrics. Missing curves are sampled from the
saved dose on the CT grid, never from a new inference or a fabricated zero.
The active plan's union CTV/scalar clinical metrics remain unchanged.
"""
from __future__ import annotations

from collections import Counter
import json
import threading
from typing import Mapping

import numpy as np

from utils.dose_metrics import hottest_volume_count
from utils.ctv_targets import project_target


_INPUT_KEYS = (
    'ct_image', 'ct_data', 'ct_spacing', 'ct_origin', 'ct_direction',
    'ctv_array', 'ctv_full_labels', 'ctv_source', 'ctv_label_map', 'target_semantics',
    'oar_array', 'oar_source', 'organ_names', 'structure_registry_initialized',
    'structure_base_ctv_array', 'structure_base_ctv_full_labels',
    'structure_base_ctv_label_map', 'structure_base_ctv_source',
    'structure_base_oar_array', 'structure_base_organ_names', 'structure_base_oar_source',
    'structure_overrides', 'structure_deleted_ids', 'generic_segmentation_masks',
    'dose_distribution', 'dose_distribution_gy', 'dose_distribution_physical_gy',
    'dose_metrics', 'dvh_data', 'manual_plan_version', 'active_planning_id',
    'algorithm_plan_dose_distribution', 'algorithm_plan_dose_distribution_gy',
    'algorithm_plan_dose_metrics', 'algorithm_plan_dvh_data',
)
_CACHE_CREATION_LOCK = threading.Lock()


def _token(memory, context, scale):
    versions = getattr(memory, '_planning_versions', {})
    image = memory.retrieve('ct_image')
    geometry = tuple(tuple(getattr(image, name)()) for name in ('GetSize', 'GetSpacing', 'GetOrigin', 'GetDirection')) if image is not None else ()
    return (str(context.get('source_planning_id')), str(context.get('source')), geometry,
            bool(context.get('stale')), float(scale),
            tuple((key, versions.get(key, 0), id(memory.retrieve(key))) for key in _INPUT_KEYS),
            json.dumps(memory.retrieve('structure_overrides') or {}, sort_keys=True, default=str),
            json.dumps(memory.retrieve('structure_deleted_ids') or [], sort_keys=True, default=str))


def _valid_curve(curve):
    if not isinstance(curve, Mapping):
        return False
    value = curve.get('cumulative', curve)
    try:
        x = np.asarray(value['dose_bins'], dtype=float)
        y = np.asarray(value['volume_pcts'], dtype=float)
        return bool(x.ndim == y.ndim == 1 and len(x) == len(y) >= 2
                    and np.isfinite(x).all() and np.isfinite(y).all()
                    and np.all(np.diff(x) >= 0) and np.all(np.diff(y) <= 1e-6)
                    and np.all((y >= 0) & (y <= 100)))
    except (KeyError, TypeError, ValueError):
        return False


def _sample(doses, spacing, rx):
    values = np.sort(np.asarray(doses, dtype=float).reshape(-1))
    if not values.size or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError('Structure has no finite non-negative dose samples')
    voxel_cm3 = float(np.prod(spacing) / 1000)
    desc = values[::-1]
    pct = lambda p: float(desc[max(0, int(np.ceil(p * len(desc) / 100)) - 1)])
    cc = lambda v: float(desc[hottest_volume_count(v, voxel_cm3, len(desc)) - 1])
    metrics = {'d0_1cc': cc(.1), 'd1cc': cc(1), 'd2cc': cc(2),
               'd90': pct(90), 'd95': pct(95), 'dmax': float(values[-1]),
               'mean_dose': float(values.mean()), 'volume_cm3': len(values) * voxel_cm3,
               'volume_voxels': len(values), 'volume_metric_units': 'fraction'}
    if rx is not None:
        metrics['v100'] = float(np.count_nonzero(values >= rx) / len(values))
    # Same cumulative >= convention as build_cumulative_dvh, using one sort
    # and searchsorted rather than scanning the entire mask for every bin.
    upper = max(600., float(values[-1]) * 1.1, (rx or 0) * 3)
    edges = np.linspace(0, upper, 601)
    anchors = [0., float(values[-1]), upper]
    if rx is not None:
        anchors += [rx, rx * 1.5, rx * 2, rx * .5]
    x = np.unique(np.concatenate(((edges[:-1] + edges[1:]) / 2, anchors)))
    y = (len(values) - np.searchsorted(values, x, side='left')) / len(values) * 100
    return {'dose_bins': x.tolist(), 'volume_pcts': y.tolist(), 'dose_unit': 'Gy'}, metrics


def complete_structure_analysis(agent, context, scale, *, label_resolver, dose_resolver):
    """Return all classified CTV/OAR identities, including explicit omissions.

    Single-entry cache is owned by the case agent, fenced by input generations
    and plan identity. Cache publication never writes clinical memory. Inputs
    changing during sampling are rejected instead of mixing plan revisions.
    """
    memory = agent.memory
    lock = getattr(agent, '_structure_analysis_lock', None)
    if lock is None:
        with _CACHE_CREATION_LOCK:
            lock = getattr(agent, '_structure_analysis_lock', None)
            if lock is None:
                lock = agent._structure_analysis_lock = threading.RLock()
    with lock:
        token = _token(memory, context, scale)
        cached = getattr(agent, '_structure_analysis_cache', None)
        if cached and cached[0] == token:
            return cached[1]
        image = memory.retrieve('ct_image')
        if image is None:
            return {'dvh': dict(context.get('dvh') or {}), 'oar_metrics': dict((context.get('metrics') or {}).get('oar_metrics') or {}),
                    'coverage': {'status': 'unavailable', 'reason': 'ct_grid_unavailable',
                                 'structures': [], 'expected': 0, 'available': 0}}
        shape = tuple(reversed(image.GetSize()))
        spacing = np.asarray(image.GetSpacing(), dtype=float)
        if len(spacing) != 3 or not np.isfinite(spacing).all() or np.any(spacing <= 0):
            raise ValueError('Analysis requires finite positive CT spacing')
        ctv, oar, effective, ctv_ids, oar_ids, _ = label_resolver(agent, shape)
        for array in (ctv, oar):
            if array is not None and np.asarray(array).shape != shape:
                raise ValueError('Structure and CT geometry differ')
        catalog = {(item['classification'], int(item['target_label'])): item
                   for item in effective.structures} if effective is not None else {}
        names = effective.organ_names if effective is not None else memory.retrieve('organ_names') or {}
        ctv_names = effective.ctv_label_map if effective is not None else memory.retrieve('ctv_label_map') or {}
        structures = []
        for family, array, ids, mapping in (('ctv', ctv, ctv_ids, ctv_names), ('oar', oar, oar_ids, names)):
            if array is None:
                continue
            target = project_target(ctv, source=memory.retrieve('ctv_source'),
                                    semantics=memory.retrieve('target_semantics')) if family == 'ctv' and effective is None else None
            labels = {int(v) for v in np.unique(array) if v > 0}
            labels.update(label for cls, label in catalog if cls == family)
            for label in sorted(labels):
                item = catalog.get((family, label), {})
                # An overlap in the transport label map must not truncate the
                # individual ROI used for dosimetry. The registry owns masks.
                mask = np.asarray(item['mask'], dtype=bool) if 'mask' in item else array == label
                if mask.shape != shape:
                    raise ValueError('Structure object and CT geometry differ')
                if not np.any(mask):
                    continue
                if target is not None and not np.any(mask & target.astype(bool)):
                    continue
                object_id = str(ids.get(label) or item.get('object_id') or f'structure:{family}:{label}')
                name = str(item.get('name') or mapping.get(label) or mapping.get(str(label)) or f'{family.upper()} {label}')
                structures.append({'object_id': object_id, 'classification': family, 'label_id': label,
                                   'display_name': name, 'voxel_count': int(np.count_nonzero(mask)),
                                   '_mask': mask})
        legacy_dvh = dict(context.get('dvh') or {})
        old_metrics = context.get('metrics') or {}
        legacy_oar = old_metrics.get('oar_metrics') or {}
        rx_value = old_metrics.get('prescription_gy')
        if rx_value is None and str(old_metrics.get('dose_value_unit', '')).lower() == 'gy':
            rx_value = old_metrics.get('prescribed_dose')
        try:
            rx = float(rx_value) if rx_value is not None else None
            if rx is not None and (not np.isfinite(rx) or rx <= 0):
                rx = None
        except (TypeError, ValueError):
            rx = None
        counts = Counter(row['display_name'] for row in structures)
        curves, metrics, coverage = {}, {}, []
        used = set()
        union = next((key for key in legacy_dvh if key.upper() in {'CTV', 'GTV', 'PTV'}
                      and key not in legacy_oar
                      and (legacy_dvh[key] or {}).get('classification') != 'oar'), None)
        ctv_count = sum(row['classification'] == 'ctv' for row in structures)
        if ctv_count > 1 and union and _valid_curve(legacy_dvh[union]):
            curves['CTV'] = {**legacy_dvh[union], 'classification': 'ctv', 'display_name': 'CTV (union)',
                             'object_id': 'analysis:ctv_union', 'is_union': True}
            used.add(union)
        dose = None
        dose_error = None
        for row in structures:
            family, label, name = row['classification'], row['label_id'], row['display_name']
            identity = {key: value for key, value in row.items() if not key.startswith('_')}
            candidates = []
            if family == 'ctv' and ctv_count == 1 and union:
                candidates.append(union)
            for key, curve in legacy_dvh.items():
                if key in used or not isinstance(curve, Mapping):
                    continue
                if curve.get('object_id') and curve['object_id'] != row['object_id']:
                    continue
                old_identity = legacy_oar.get(key) or {}
                if old_identity.get('object_id') and old_identity['object_id'] != row['object_id']:
                    continue
                if curve.get('object_id') == row['object_id']:
                    candidates.insert(0, key)
                elif (curve.get('classification') == family and curve.get('label_id') == label):
                    candidates.append(key)
                elif family == 'oar':
                    old = legacy_oar.get(key) or {}
                    if old.get('label_id') == label or (key == name and counts[name] == 1):
                        candidates.append(key)
            key = next((key for key in candidates if key not in used and _valid_curve(legacy_dvh.get(key))), None)
            curve = dict(legacy_dvh[key]) if key is not None else None
            metric = dict(legacy_oar.get(key) or {}) if family == 'oar' and key is not None else {}
            required = ('d0_1cc', 'd1cc', 'd2cc', 'd90', 'd95', 'volume_cm3')
            def missing(field):
                try:
                    return metric.get(field) is None or not np.isfinite(float(metric[field]))
                except (KeyError, TypeError, ValueError):
                    return True
            missing_fields = [field for field in required if missing(field)] if family == 'oar' else []
            if family == 'oar' and rx is not None and missing('v100'):
                missing_fields.append('v100')
            reason = None
            if context.get('stale'):
                reason = 'dose_stale'
            elif curve is None or missing_fields:
                if dose is None and dose_error is None:
                    try:
                        dose = np.asarray(dose_resolver(agent, context), dtype=float) * float(scale)
                        if dose.shape != shape or not np.isfinite(dose).all() or np.any(dose < 0):
                            raise ValueError('Dose and structure grids differ or dose is invalid')
                    except (ValueError, TypeError) as exc:
                        dose_error = str(exc)
                if dose_error is not None:
                    reason = 'dose_grid_unavailable'
                else:
                    sampled, sampled_metrics = _sample(dose[row['_mask']], spacing, rx)
                    if curve is None:
                        curve = sampled
                    if not metric:
                        metric = sampled_metrics
                    else:
                        for field in missing_fields:
                            if field in sampled_metrics:
                                metric[field] = sampled_metrics[field]
                        metric['computed_fields'] = missing_fields
            curve_key = 'CTV' if family == 'ctv' and ctv_count == 1 else row['object_id']
            if curve is not None:
                curves[curve_key] = {**curve, **identity}
                if key is not None:
                    used.add(key)
            if family == 'oar':
                metrics[row['object_id']] = {**metric, **identity}
            coverage.append({**identity, 'available': curve is not None, 'reason': reason,
                             'basis': 'saved_curve' if key is not None else 'saved_dose_ct_grid'})
        if ctv_count > 1 and 'CTV' not in curves and dose is not None and not context.get('stale'):
            union_mask = np.zeros(shape, dtype=bool)
            for row in structures:
                if row['classification'] == 'ctv':
                    union_mask |= row['_mask']
            curve, _ = _sample(dose[union_mask], spacing, rx)
            curves['CTV'] = {**curve, 'classification': 'ctv', 'object_id': 'analysis:ctv_union',
                             'display_name': 'CTV (union)', 'is_union': True}
        available = sum(row['available'] for row in coverage)
        result = {'dvh': curves, 'oar_metrics': metrics,
                  'coverage': {'expected': len(coverage), 'available': available, 'structures': coverage,
                               'status': 'stale' if context.get('stale') else 'complete' if available == len(coverage) and coverage else 'incomplete',
                               'scope': 'classified_ctv_oar', 'union_extra': ctv_count > 1 and 'CTV' in curves}}
        # Dose sidecars can hydrate before masks. A partial registry must not
        # turn a 53-organ saved plan into a falsely "complete 1/1" display.
        incomplete_inputs = (ctv is None and any(key.upper() in {'CTV','PTV','GTV'} for key in legacy_dvh)) or (oar is None and bool(legacy_oar))
        if incomplete_inputs or not structures:
            result['dvh'] = {**{key:value for key,value in legacy_dvh.items() if key not in used}, **curves}
            present_labels = {row['label_id'] for row in coverage if row['classification'] == 'oar'}
            result['oar_metrics'] = {**{key:value for key,value in legacy_oar.items()
                                       if value.get('label_id') not in present_labels and key not in used}, **metrics}
            result['coverage']['status'] = 'unavailable'
            result['coverage']['reason'] = 'structure_grid_unavailable'
        if _token(memory, context, scale) != token:
            raise ValueError('Analysis inputs changed during sampling; retry current plan')
        agent._structure_analysis_cache = (token, result)
        return result
