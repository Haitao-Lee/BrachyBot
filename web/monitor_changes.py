"""Bounded, server-owned edit evidence. No model inference or dose prediction."""
import copy
import hashlib
import json
import math
from types import SimpleNamespace


def _artifact_state(artifacts, key):
    value = artifacts.get(key)
    if isinstance(value, dict):
        value = value.get('status')
    return 'stale' if value == 'outdated' else value


def geometry_key(geometry):
    records = {}
    for kind in ('seeds', 'needles'):
        items = []
        for item in geometry.get(kind, []) or []:
            try:
                row = {'id': str(item.get('id')), 'trajectory_id': item.get('trajectory_id') or item.get('needle_id')}
                if kind == 'seeds':
                    row['position'] = [float(v) for v in item['position']]
                    row['direction'] = [float(v) for v in (item.get('direction') or [])]
                else:
                    points = item['points']
                    if len(points) < 2:
                        raise ValueError('needle needs two endpoints')
                    row['points'] = [[float(v) for v in points[0]], [float(v) for v in points[-1]]]
                items.append(row)
            except (KeyError, TypeError, ValueError):
                # Never let one malformed entry drop the whole evidence set;
                # keep the raw item so the key still changes when it changes.
                items.append({'raw': json.dumps(item, sort_keys=True, default=str)})
        records[kind] = sorted(items, key=lambda x: x.get('id', x.get('raw', '')))
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def compact_evidence(evidence):
    """Small LLM facts, not raw plan arrays, images, history or mutation tokens."""
    return {
        'planning_id': evidence['planning_id'], 'version': evidence['after_version'],
        'source': 'server_committed_monitor_edit',
        'changed_objects': [{k: v for k, v in obj.items() if k in ('id', 'kind', 'operation', 'distance_mm')}
                            for obj in evidence.get('changed_objects', [])[:8]],
        'conflicts': evidence.get('conflicts', [])[:4],
        'resolved_conflicts': evidence.get('resolved_conflicts', 0),
        'dose': evidence.get('dose'),
        'guidance': {key: value for key, value in guided_feedback(evidence).items()
                     if key in ('state', 'meaning', 'recommendation', 'verification', 'limitation', 'focus_refs')},
        'interpretation': 'Use these measured deltas, not chat-history numbers. No calibrated model-noise threshold or dose-optimal movement has been established. Score change is not clinical approval.',
    }


def capture(agent, geometry):
    from web import server_support as support
    from web.planning_runs import ACTIVE_PLANNING_ID_KEY, PLANNING_RUN_ID_KEY
    memory = agent.memory
    # Geometry comes from the mutation API's canonical snapshot, including an
    # explicitly empty plan. Never fall back to an old automatic plan here.
    metrics = memory.retrieve('dose_metrics') or memory.retrieve('metrics') or {}
    if isinstance(metrics.get('metrics'), dict):
        metrics = metrics['metrics']
    values = {}
    for key in ('v100', 'v150', 'v200', 'd90', 'd95', 'plan_score', 'ci', 'hi'):
        number = (support._volume_metric_as_fraction(metrics, key)
                  if key.startswith('v') else support._extract_metric_value(metrics, key))
        if number is None and key == 'plan_score':
            number = support._extract_metric_value(metrics, 'score')
        if number is not None and math.isfinite(number):
            values[key] = number * 100 if key.startswith('v') else number
    stale = memory.retrieve('manual_artifact_status') or {}
    versions = getattr(memory, '_planning_versions', {})
    anatomy_keys = ('ct_image', 'ctv_mask', 'oar_mask', 'ctv_array', 'oar_array', 'ctv_label_data', 'oar_label_data')
    organs = {}
    for name, row in list((metrics.get('oar_metrics') or {}).items())[:128]:
        if not isinstance(row, dict):
            continue
        organs[str(name)] = {key: float(row[key]) for key in ('dmax', 'd2cc', 'mean_dose')
                            if isinstance(row.get(key), (int, float)) and math.isfinite(row[key])}
    return {
        'geometry': copy.deepcopy(geometry), 'geometry_key': geometry_key(geometry),
        'planning_id': memory.retrieve(ACTIVE_PLANNING_ID_KEY) or memory.retrieve(PLANNING_RUN_ID_KEY),
        'version': int(memory.retrieve('manual_plan_version') or 0),
        'metrics': values,
        'oar_metrics': organs,
        'score_status': metrics.get('criteria_status') if 'plan_score' not in values else 'available',
        'metrics_current': (memory.retrieve('dose_distribution') is not None or memory.retrieve('dose_distribution_gy') is not None) and not memory.retrieve('manual_geometry_only')
            and not any(_artifact_state(stale, k) in ('stale', 'running', 'failed') for k in ('dose', 'dvh')),
        'config': copy.deepcopy(memory.retrieve('plan_config') or {}),
        'anatomy_key': ([(versions.get(k), id(memory.retrieve(k))) for k in anatomy_keys]
                        if any(memory.retrieve(k) is not None for k in anatomy_keys) else None),
    }


def compare(before, after):
    def direction_changed(left, right):
        first, second = left.get('direction') or [], right.get('direction') or []
        if not isinstance(first, (list, tuple)) or not isinstance(second, (list, tuple)):
            return first != second
        if len(first) != len(second):
            return True
        try:
            return any(abs(float(x) - float(y)) > 1e-4 for x, y in zip(first, second))
        except (TypeError, ValueError):
            return first != second

    changed = []
    for kind in ('seeds', 'needles'):
        old = {str(x['id']): x for x in before['geometry'][kind]}
        new = {str(x['id']): x for x in after['geometry'][kind]}
        for object_id in sorted(old.keys() | new.keys()):
            a, b = old.get(object_id), new.get(object_id)
            field = 'position' if kind == 'seeds' else 'points'
            owner_changed = bool(a and b and kind == 'seeds'
                                 and a.get('trajectory_id') != b.get('trajectory_id'))
            orientation_changed = bool(a and b and kind == 'seeds'
                                       and direction_changed(a, b))
            distance = None
            if a and b:
                start, end = a.get(field), b.get(field)
                distance = (math.dist(start, end) if kind == 'seeds' else
                    max(math.dist(start[0], end[0]), math.dist(start[-1], end[-1])))
                # Serialization and reprojection can change insignificant
                # decimal places without moving a physical object. Never
                # report these as a 0.00 mm drag or offer a zero-vector arrow.
                if distance < 0.01 and not orientation_changed and not owner_changed:
                    continue
            entry = {'id': object_id, 'kind': kind,
                     'operation': 'added' if a is None else 'deleted' if b is None
                     else 'moved' if distance >= 0.01 else 'reoriented'}
            if orientation_changed or owner_changed:
                entry['orientation_or_owner_changed'] = True
            if a and b:
                if kind == 'seeds':
                    entry.update(before=start, after=end, distance_mm=distance)
                    if distance >= 0.01:
                        entry['return_vector_mm'] = [x-y for x, y in zip(start, end)]
                else:
                    entry.update(before=start, after=end, distance_mm=distance)
            changed.append(entry)
    needle_changed = any(item['kind'] == 'needles' for item in changed)
    moved_tracks = {str(item.get('trajectory_id') or item['id'])
        for item in after['geometry']['needles']
        if any(change['kind'] == 'needles' and change['id'] == str(item['id'])
               for change in changed)}
    for obj in changed:
        if obj['kind'] == 'seeds':
            record = next((seed for seed in after['geometry']['seeds']
                           if str(seed['id']) == obj['id']), None)
            obj['dependent_on_needle'] = bool(needle_changed and record
                and str(record.get('trajectory_id')) in moved_tracks)
            # Normalizing a saved geometry can refresh directions on every
            # seed, including seeds on untouched needles. These are not
            # independent user drags and should not crowd out the needle.
            obj['derived_from_normalization'] = bool(needle_changed
                and obj['operation'] == 'reoriented'
                and not obj['dependent_on_needle'])
    # Show the edited needle and independent seed edits before dependent
    # reprojections; lexical seed IDs previously hid the initiating needle.
    changed.sort(key=lambda item: (bool(item.get('dependent_on_needle')
                                        or item.get('derived_from_normalization')),
                                   item['kind'] != 'needles', item['id']))
    ids = {x['id'] for x in changed if x['operation'] != 'reoriented'}
    # Reorientation can change finite-cylinder clearance even without moving
    # its centre. Inspect those pairs too, but do not treat old pairs as newly
    # caused by an unrelated needle edit.
    ids.update(x['id'] for x in changed if x['operation'] == 'reoriented'
               and not x.get('derived_from_normalization'))
    for snapshot in (before, after):
        changed_tracks = {str(n.get('trajectory_id') or n['id']) for n in snapshot['geometry']['needles'] if str(n['id']) in ids}
        ids.update(str(s['id']) for s in snapshot['geometry']['seeds']
                   if str(s.get('trajectory_id') or s.get('needle_id')) in changed_tracks)
    from web import server_support as support
    for side, snapshot in enumerate((before, after)):
        config = snapshot.get('config', {})
        agent = SimpleNamespace(memory=SimpleNamespace(retrieve=lambda key: config if key == 'plan_config' else None))
        # Filter by edited IDs before the legacy 50-pair presentation cap.
        # Late-numbered seeds must not disappear behind old global violations.
        snapshot = snapshot.copy()
        seed_report = support._seed_interference_report(agent,
            snapshot['geometry']['seeds'], snapshot['geometry']['needles'],
            focus_ids=ids, max_pairs=None)
        snapshot['seed_pairs'] = [{**pair, 'minimum_clearance_mm': seed_report['minimum_clearance_mm']}
                                  for pair in seed_report['close_pairs']]
        snapshot['needle_pairs'] = support._needle_interference_report(
            snapshot['geometry']['needles'], config, focus_ids=ids, max_pairs=None,
        )['close_pairs']
        if side == 0:
            before = snapshot
        else:
            after = snapshot
    conflicts = []
    resolved = 0
    for key, distance_key in (('seed_pairs', 'surface_clearance_mm'), ('needle_pairs', 'surface_clearance_mm')):
        def pairs(snapshot):
            return {tuple(sorted((str(p['first_id']), str(p['second_id'])))): p
                    for p in snapshot[key] if ids.intersection((str(p['first_id']), str(p['second_id'])))}
        old, new = pairs(before), pairs(after)
        resolved += len(old.keys() - new.keys())
        for pair_id, pair in new.items():
            prior = old.get(pair_id)
            difference = float(pair[distance_key]) - float(prior[distance_key]) if prior else 0
            status = 'new' if prior is None else ('worsened' if difference < -1e-3
                else 'improved' if difference > 1e-3 else 'existing')
            conflicts.append({**pair, 'change': status, 'kind': key,
                              'previous_distance_mm': prior.get(distance_key) if prior else None})
    conflicts.sort(key=lambda p: (p['change'] not in ('new', 'worsened'), p.get('surface_clearance_mm', p.get('distance_mm', 0))))
    return {'changed_objects': changed[:64], 'changed_object_count': len(changed),
            'dependent_object_count': sum(bool(obj.get('dependent_on_needle')) for obj in changed),
            'normalization_object_count': sum(bool(obj.get('derived_from_normalization')) for obj in changed),
            'existing_conflict_count': sum(p['change'] == 'existing' for p in conflicts),
            'new_conflict_count': sum(p['change'] == 'new' for p in conflicts),
            'worsened_conflict_count': sum(p['change'] == 'worsened' for p in conflicts),
            'changed_kinds': sorted({obj['kind'] for obj in changed}),
            'conflicts': conflicts[:12], 'resolved_conflicts': resolved,
            'before_version': before['version'], 'after_version': after['version'],
            'planning_id': after['planning_id'], 'geometry_key': after['geometry_key'],
            'dose': dose_comparison(before, after),
            'scope': 'geometry and saved dose deltas; clinical acceptance not evaluated'}


def dose_comparison(before, after):
    # Equal versions/configuration alone do not identify a comparison baseline.
    # Missing anatomy is unknown, not evidence that two snapshots match.
    reason = ('planning_identity_missing' if not before.get('planning_id') or not after.get('planning_id')
              else 'planning_changed' if before['planning_id'] != after['planning_id']
              else 'anatomy_baseline_missing' if not before.get('anatomy_key') or not after.get('anatomy_key')
              else 'anatomy_changed' if before['anatomy_key'] != after['anatomy_key']
              else 'configuration_changed' if before.get('config') != after.get('config')
              else 'baseline_dose_unavailable' if not before['metrics_current']
              else 'current_dose_unavailable' if not after['metrics_current'] else None)
    comparable = reason is None
    organ_changes = []
    if comparable:
        for organ, row in before.get('oar_metrics', {}).items():
            for key, value in row.items():
                current = after.get('oar_metrics', {}).get(organ, {}).get(key)
                if current is not None:
                    organ_changes.append({'organ': organ, 'metric': key, 'before': value,
                                          'after': current, 'delta': current - value})
        organ_changes.sort(key=lambda row: abs(row['delta']), reverse=True)
    series_key = (hashlib.sha256(json.dumps([after.get('planning_id'), after.get('anatomy_key'), after.get('config')],
                                sort_keys=True, default=str).encode()).hexdigest()[:20]
                  if after.get('anatomy_key') and after.get('planning_id') else None)
    return {'comparable': comparable, 'series_key': series_key,
            'comparison_reason': reason,
            'before': before['metrics'] if before['metrics_current'] else {},
            'after': after['metrics'] if after['metrics_current'] else {},
            'score_status': after.get('score_status'),
            # The largest absolute decreases must not hide every observed rise.
            'oar_changes': sorted(organ_changes, key=lambda row: (row['delta'] < .005, -abs(row['delta'])))[:4],
            'oar_metric_comparison_count': len(organ_changes),
            'oar_increase_count': sum(row['delta'] >= .005 for row in organ_changes),
            'delta': {k: after['metrics'][k] - v for k, v in before['metrics'].items()
                      if k in after['metrics']} if comparable else {}}


def describe(evidence, language='en'):
    zh = language == 'zh'
    lines = []
    if evidence.get('superseded'):
        lines.append('以下是上一条已记录的编辑证据，当前规划已改变或暂不可核对，不能视作当前规划结论。' if zh
                     else 'This is the last recorded edit evidence. The current plan has changed or cannot be verified; these are not current-plan conclusions.')
    dependent_count = evidence.get('dependent_object_count', 0)
    if dependent_count:
        lines.append(f"针道变更后有 {dependent_count} 个关联粒子重新投影或转向；这些不是 {dependent_count} 次独立拖拽。" if zh
                     else f"{dependent_count} associated seeds were reprojected or reoriented after the needle edit; these were not independent drags.")
    normalization_count = evidence.get('normalization_object_count', 0)
    if normalization_count:
        lines.append(f"另有 {normalization_count} 个其他粒子仅在保存时刷新了方向/归属；不表示用户逐枚拖动。" if zh
                     else f"Another {normalization_count} seeds had direction/ownership refreshed on save; this does not mean the user dragged each one.")
    display_objects = [obj for obj in evidence.get('changed_objects', [])
                       if not obj.get('dependent_on_needle')
                       and not obj.get('derived_from_normalization')][:4]
    if not display_objects and evidence.get('changed_objects'):
        display_objects = evidence['changed_objects'][:2]
    for obj in display_objects:
        if obj['operation'] == 'moved':
            lines.append(f"{obj['id']}：移动 {obj['distance_mm']:.2f} mm。" if zh
                         else f"{obj['id']}: moved {obj['distance_mm']:.2f} mm.")
            if obj['kind'] == 'needles' and obj.get('before') and obj.get('after'):
                for endpoint, (old, new) in enumerate(zip(obj['before'], obj['after']), 1):
                    vector = [x-y for x, y in zip(old, new)]
                    if math.sqrt(sum(value * value for value in vector)) < 0.01:
                        continue
                    values = ', '.join(f'{value:+.2f}' for value in vector)
                    lines.append((f"{obj['id']} 端点 {endpoint} 回到编辑前位置的患者坐标位移：[{values}] mm（非屏幕方向，也非剂量最优方向）。"
                                  if zh else f"{obj['id']} endpoint {endpoint} return displacement in patient coordinates: [{values}] mm (not screen or dose-optimal direction)."))
            if obj.get('orientation_or_owner_changed'):
                lines.append('该粒子的方向或所属针道也已改变。' if zh else 'Its direction or owning needle also changed.')
        elif obj['operation'] == 'reoriented':
            lines.append(f"{obj['id']}：方向或所属针道改变，位置未发生可显示的位移。" if zh
                         else f"{obj['id']}: orientation or owning needle changed without a reportable displacement.")
        else:
            lines.append(f"{obj['id']}：{'新增' if obj['operation'] == 'added' else '删除'}。" if zh
                         else f"{obj['id']}: {obj['operation']}.")
    actionable = [pair for pair in evidence.get('conflicts', [])
                  if pair['change'] in ('new', 'worsened')]
    for pair in actionable[:4]:
        value = pair.get('surface_clearance_mm', pair.get('distance_mm'))
        status = {'new': '新增违规', 'worsened': '违规加重', 'improved': '间距改善但仍违规', 'existing': '原有违规仍存在'}[pair['change']]
        if pair['kind'] == 'seed_pairs':
            exact = pair.get('clearance_basis') == 'finite_parallel_cylinders'
            label = ('实体表面间隙' if exact else '轴线模型间隙下界') if zh else (
                'finite surface gap' if exact else 'axis-model clearance bound')
        else:
            exact = pair.get('clearance_basis') == 'finite_parallel_cylinders'
            label = ('针道实体表面间隙' if exact else '针道轴线模型间隙下界') if zh else (
                'finite needle surface gap' if exact else 'needle-axis clearance bound')
        lines.append(f"{status}：{pair['first_id']} ↔ {pair['second_id']}，{label} {value:.2f} mm。" if zh
                     else f"{pair['change']}: {pair['first_id']} ↔ {pair['second_id']}, {label} {value:.2f} mm.")
    if evidence.get('existing_conflict_count'):
        count = evidence['existing_conflict_count']
        lines.append(f"另有 {count} 组相关间距违规在编辑前已存在，未归因于本次操作。" if zh
                     else f"{count} related spacing conflicts predated this edit and are not attributed to it.")
    if evidence.get('resolved_conflicts'):
        count = evidence['resolved_conflicts']
        lines.append(f"本次消除了 {count} 组已记录的相关间距违规。" if zh else f"Resolved {count} recorded spacing conflicts.")
    dose = evidence.get('dose') or {}
    if dose.get('comparable') and dose.get('edit_count', 0) > 1:
        lines.append(f"剂量差值覆盖自上次有效重算以来的 {dose['edit_count']} 次编辑，不能归因于其中某一步。" if zh
                     else f"Dose deltas cover {dose['edit_count']} edits since the last valid recomputation; they cannot be attributed to just one edit.")
    if dose.get('comparable'):
        for key in ('plan_score', 'v100', 'd90', 'v150', 'v200'):
            if key not in dose['delta']:
                continue
            unit = '百分点' if key.startswith('v') and zh else 'pp' if key.startswith('v') else 'Gy' if key.startswith('d') else '分' if zh else 'points'
            lines.append(f"{key}: {dose['before'][key]:.2f} → {dose['after'][key]:.2f} ({dose['delta'][key]:+.2f} {unit})")
        for row in dose.get('oar_changes', []):
            lines.append(f"OAR {row['organ']} {row['metric']}: {row['before']:.2f} → {row['after']:.2f} ({row['delta']:+.2f} Gy)")
        if not dose.get('oar_changes'):
            lines.append('缺少可比较的 OAR 前后结果。' if zh else 'Comparable before/after OAR results are missing.')
        lines.append('以上是同一监测编辑链的实测变化；覆盖、热点、OAR 和评分须分别看，不能仅凭分数认定整体变好。' if zh
                     else 'Measured changes in this edit sequence. Coverage, hot spots, OAR dose and score must be considered separately; score alone does not establish overall improvement.')
    else:
        lines.append('尚无与本次几何对应的前后剂量结果，暂不能判断剂量优化或劣化；重算后会补充可比差值。' if zh
                     else 'Matching before/after dose results are not available. Dose improvement or deterioration is undetermined; recomputation can supply comparable deltas.')
        score = (dose.get('after') or {}).get('plan_score')
        if score is not None:
            lines.append(f"当前评分 {score:.2f}/100；缺少有效前值。" if zh else f"Current score {score:.2f}/100; valid baseline unavailable.")
    if dose.get('after') and 'plan_score' not in dose['after']:
        lines.append('当前重算结果没有有效评分；不会沿用旧分数或自行补造评分。' if zh
                     else 'The recomputed result has no valid score; an old or invented score is not substituted.')
    if actionable:
        pair = actionable[0]
        lines.append((f"优先复核 {pair['first_id']} 与 {pair['second_id']} 的新发/加重间距问题；若本次移动并非有意，可选择撤销本次编辑。"
                      if zh else f"Review the new/worsened spacing of {pair['first_id']} and {pair['second_id']} first; if this movement was unintended, consider undoing this edit."))
    elif dose.get('comparable'):
        delta = dose.get('delta') or {}
        oar_rise = next((row for row in dose.get('oar_changes', []) if row['delta'] > 0), None)
        if oar_rise and (delta.get('v200', 0) > 0 or delta.get('v150', 0) > 0):
            subject = '这一编辑链' if dose.get('edit_count', 0) > 1 else '本次编辑'
            lines.append((f"覆盖与热点/OAR 变化可能相互权衡：{oar_rise['organ']} {oar_rise['metric']} 增加 {oar_rise['delta']:.2f} Gy；请核对对应空间位置及适用约束，不能仅凭覆盖改善认定{subject}更优。"
                          if zh else f"Coverage may trade off against hot spots/OAR dose: {oar_rise['organ']} {oar_rise['metric']} rose {oar_rise['delta']:.2f} Gy. Inspect its location and applicable constraints before calling this edit sequence better."))
    if evidence.get('restore_token'):
        lines.append("可在本次编辑卡片上选择“恢复编辑前位置”或“保留编辑”。复位后剂量仍需重算；原位置不等于已验证的安全位置。" if zh
                     else "Choose Restore pre-edit position or Keep edit on this edit card. Recompute dose after restoring; the prior position is not a verified safe position.")
        for obj in display_objects[:2]:
            if obj.get('return_vector_mm'):
                vector = ', '.join(f'{v:+.2f}' for v in obj['return_vector_mm'])
                lines.append(f"{obj['id']} 返回原位的患者坐标位移为 [{vector}] mm（非屏幕左右方向，也不是剂量最优方向）。" if zh
                             else f"{obj['id']} return displacement in patient coordinates: [{vector}] mm; not screen directions or a dose-optimal direction.")
    return '\n\n'.join(lines)


def _guidance_pair(evidence):
    """Do not let unchanged dependent-seed conflicts eclipse a needle edit."""
    pairs = evidence.get('conflicts') or []
    actionable = next((p for p in pairs if p.get('change') in ('new', 'worsened')), None)
    if actionable:
        return actionable
    independent = {str(obj.get('id')) for obj in evidence.get('changed_objects', [])
                   if not obj.get('dependent_on_needle') and not obj.get('derived_from_normalization')}
    return next((p for p in pairs if p.get('change') == 'improved'
                 or independent.intersection((str(p.get('first_id')), str(p.get('second_id'))))), None)


def screenshot(evidence, event_id):
    ids = []
    priority_pairs = [p for p in evidence.get('conflicts', []) if p['change'] in ('new', 'worsened')]
    # An improved/pre-existing conflict still needs both members in the
    # evidence image when it is the current recommendation's subject.
    if not priority_pairs:
        pair = _guidance_pair(evidence)
        priority_pairs = [pair] if pair else []
    for p in priority_pairs:
        ids.extend((p['first_id'], p['second_id']))
        if len(ids) >= 4:
            break
    ids.extend(x['id'] for x in evidence.get('changed_objects', [])
               if x['operation'] != 'deleted'
               and not x.get('dependent_on_needle') and not x.get('derived_from_normalization'))
    ids = list(dict.fromkeys(ids))[:8]
    if not ids:
        return None
    return {'target': 'viewer-3d', 'views': ['viewer-3d'], 'object_ids': ids,
            'checkpoint_id': event_id, 'planning_id': evidence['planning_id'],
            'planning_version': evidence['after_version'], 'geometry_key': evidence['geometry_key'],
            'visual_purpose': 'locate', 'annotation_policy': 'required',
            'edit_evidence': {'changed_objects': evidence.get('changed_objects', [])[:8],
                              'conflicts': evidence.get('conflicts', [])[:4]},
            'question': ' / '.join(ids), 'hide_unrelated': False,
            'focus': {'kind': 'auto', 'padding': 0.5}}


def interaction(evidence, language='en'):
    """Keep both deterministic display projections with the same owned evidence.

    A global UI language change must not request new measurements or translate
    a medical finding through an LLM. Numerical facts and authorization remain
    outside this display-only map.
    """
    language = 'zh' if language == 'zh' else 'en'
    other_language = 'en' if language == 'zh' else 'zh'
    result = _interaction(evidence, language)
    other = _interaction(evidence, other_language)
    fields = ('headline', 'dose_note', 'next_step', 'assessment', 'metric_rows')
    result['localized'] = {
        language: {key: result[key] for key in fields},
        other_language: {key: other[key] for key in fields},
    }
    return result


def _interaction(evidence, language='en'):
    """A revisioned edit card, derived only from committed evidence.

    Geometry and dose are separate assessments. This does not assign clinical
    pass/fail or fabricate a movement optimum from a scalar score.
    """
    zh = language == 'zh'
    dose = evidence.get('dose') or {}
    changes = [obj for obj in evidence.get('changed_objects', [])
               if not obj.get('dependent_on_needle') and not obj.get('derived_from_normalization')]
    new = int(evidence.get('new_conflict_count', 0))
    worse = int(evidence.get('worsened_conflict_count', 0))
    resolved = int(evidence.get('resolved_conflicts', 0))
    if new or worse:
        headline = (f'这次编辑新增 {new} 组、加重 {worse} 组间距问题。' if zh
                    else f'This edit introduced {new} and worsened {worse} spacing conflicts.')
        priority = 'attention'
    elif resolved:
        headline = (f'这次编辑消除了 {resolved} 组已记录的间距问题。' if zh
                    else f'This edit resolved {resolved} recorded spacing conflicts.')
        priority = 'review'
    else:
        headline = ('本次编辑已保存；相关间距检查未发现新增或加重问题。' if zh
                    else 'Edit saved; related spacing checks found no new or worsened conflicts.')
        priority = 'info'
    if evidence.get('superseded'):
        headline = ('这次编辑已被后续操作更新，以下保留当时的检查结果。' if zh
                    else 'Later changes superseded this edit; these are its recorded findings.')
    rows = []
    labels = {'plan_score': '评分', 'v100': 'V100', 'd90': 'D90', 'v150': 'V150', 'v200': 'V200'}
    if dose.get('comparable'):
        for key in labels:
            if key in dose.get('delta', {}):
                rows.append({'key': key, 'metric': labels[key] if zh else key,
                             'before': dose['before'][key], 'after': dose['after'][key],
                             'delta': dose['delta'][key], 'unit': ('百分点' if zh else 'pp')
                             if key.startswith('v') else 'Gy' if key.startswith('d') else ('分' if zh else 'points')})
        for row in dose.get('oar_changes', []):
            rows.append({'key': f"oar:{row['organ']}:{row['metric']}", 'metric': f"{row['organ']} {row['metric']}",
                         **{key: row[key] for key in ('before', 'after', 'delta')}, 'unit': 'Gy'})
    pair = next((p for p in evidence.get('conflicts', []) if p['change'] in ('new', 'worsened')), None)
    if pair:
        next_step = (f"先查看 {pair['first_id']} 与 {pair['second_id']} 的间距标注；若移动非预期，可恢复这次编辑前的位置。" if zh
                     else f"Inspect the marked spacing between {pair['first_id']} and {pair['second_id']}; restore the pre-edit position if this move was unintended.")
    elif not dose.get('comparable'):
        next_step = (('当前剂量已计算，但缺少同一规划、相同解剖与配置的有效编辑前基线；不能通过再次重算补造前值。请先复核当前实测结果，再以它作为下一次编辑的基线。' if zh
                      else 'Current dose is computed, but a valid pre-edit baseline for this plan, anatomy and configuration is missing. Another recomputation cannot recreate it. Review current measurements before using them as the next edit baseline.')
                     if dose.get('after') else
                     ('几何变化已核对。重算剂量后，在本卡片比较覆盖、热点和器官受量。' if zh
                      else 'Geometry checked. Recompute dose to compare coverage, hot spots and organ dose in this card.'))
    else:
        delta = dose.get('delta') or {}
        findings = []
        for key, name in [('v100', '覆盖率' if zh else 'coverage'), ('v200', '高剂量体积' if zh else 'high-dose volume')]:
            value = delta.get(key)
            if value is not None and abs(value) > 1e-8:
                findings.append((f"{name}{'增加' if value > 0 else '减少'} {abs(value):.2f} 个百分点" if zh
                                 else f"{name} {'increased' if value > 0 else 'decreased'} by {abs(value):.2f} pp"))
        next_step = ('；'.join(findings) + '。' if zh else '; '.join(findings) + '. ') if findings else ''
        next_step += ('请结合下表的器官受量与评分一起判断取舍；这些差值不代表临床通过。' if zh
                      else 'Review organ-dose and score differences below together; these changes do not establish clinical acceptance.')
    count = int(dose.get('edit_count') or 1)
    dose_note = ((f'剂量对比覆盖自基线以来的 {count} 次编辑。' if zh else f'Dose comparison covers {count} edits since baseline.')
                 if dose.get('comparable') else
                 ('剂量尚不可比较：等待与当前几何对应的重算结果或有效基线。' if zh
                  else 'Dose comparison unavailable: a current recomputation or valid baseline is required.'))
    reasons = {
        'planning_identity_missing': ('规划身份尚不可核实', 'plan identity is unverified'),
        'planning_changed': ('前后属于不同规划', 'the snapshots belong to different plans'),
        'anatomy_baseline_missing': ('缺少可核实的解剖基线', 'a verified anatomy baseline is missing'),
        'anatomy_changed': ('分割或影像基线已改变', 'the segmentation or image baseline changed'),
        'configuration_changed': ('处方或计算配置已改变', 'prescription or calculation configuration changed'),
        'baseline_dose_unavailable': ('编辑前剂量不可用或已过期', 'pre-edit dose is unavailable or stale'),
        'current_dose_unavailable': ('本次几何尚无有效重算结果', 'current geometry has no valid recomputed dose'),
    }
    if not dose.get('comparable') and dose.get('comparison_reason') in reasons:
        why = reasons[dose['comparison_reason']][0 if zh else 1]
        dose_note = f'剂量不可比较：{why}。' if zh else f'Dose comparison unavailable: {why}.'
    movements = []
    for obj in changes:
        if obj.get('operation') != 'moved':
            continue
        before, after = obj.get('before'), obj.get('after')
        points = [(None, before, after)] if obj.get('kind') == 'seeds' else (
            [(i + 1, a, b) for i, (a, b) in enumerate(zip(before, after))]
            if isinstance(before, list) and isinstance(after, list) else [])
        for endpoint, a, b in points:
            if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))
                    and len(a) == len(b) == 3
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (*a, *b))):
                continue
            vector = [x - y for x, y in zip(a, b)]
            if math.sqrt(sum(v * v for v in vector)) >= .01:
                movements.append({'object_id': str(obj['id']), 'endpoint': endpoint,
                                  'vector_mm': vector, 'coordinate_system': 'patient_world_mm',
                                  'purpose': 'return_to_pre_edit_not_optimized'})
    blocking = sum(p.get('change') in ('new', 'worsened') and
                   p.get('physical_overlap') is True
                   for p in evidence.get('conflicts', []))
    assessment = decision_summary(evidence, rows, language)
    guide = guided_feedback(evidence, language)
    return {'schema_version': 3, 'checkpoint_id': evidence.get('geometry_event_id') or evidence.get('event_id'),
            'revision': evidence.get('after_version'), 'priority': priority, 'headline': headline,
            'category': 'geometry', 'severity': 'blocking' if blocking else 'warning' if new or worse else 'info',
            'blocking_scope': 'physical_geometry' if blocking else None,
            'spatial_refs': list(dict.fromkeys(
                guide['focus_refs'] + [str(p[k]) for p in evidence.get('conflicts', [])
                 if p['change'] in ('new', 'worsened') for k in ('first_id', 'second_id')]
                + [str(obj['id']) for obj in changes if obj['operation'] != 'deleted']))[:8],
            'conflict_counts': {'new': new, 'worsened': worse, 'resolved': resolved,
                                'existing': evidence.get('existing_conflict_count', 0), 'blocking': blocking},
            'objects': changes[:4], 'conflicts': [p for p in evidence.get('conflicts', []) if p['change'] != 'existing'][:4],
            'related_object_counts': {'dependent': evidence.get('dependent_object_count', 0),
                                      'normalized': evidence.get('normalization_object_count', 0)},
            'return_movements': movements[:4],
            'metric_rows': rows, 'dose_note': dose_note, 'next_step': next_step,
            'comparison_reason': dose.get('comparison_reason'),
            'dose_current': bool(dose.get('after')), 'dose_comparable': bool(dose.get('comparable')),
            'existing_conflict_count': evidence.get('existing_conflict_count', 0),
            'language': 'zh' if zh else 'en', 'assessment': assessment,
            'guidance': guide,
            'decision_required': bool(new or worse or blocking),
            'primary_action': guide['primary_action']}


def guided_feedback(evidence, language='en'):
    """A bilingual, evidence-owned coaching contract; never an optimization verdict.

    These are measured state transitions and executable next steps, not user
    intent keyword rules. No model call, new clinical limit or dose prediction.
    """
    def localized(zh):
        def t(chinese, english):
            return chinese if zh else english

        def number(value):
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

        dose = evidence.get('dose') or {}
        delta = dose.get('delta') or {}
        changes = [obj for obj in evidence.get('changed_objects', [])
                   if not obj.get('dependent_on_needle') and not obj.get('derived_from_normalization')]
        objects = []
        for obj in changes[:2]:
            name = str(obj.get('id', ''))
            distance = obj.get('distance_mm')
            if obj.get('operation') == 'moved' and number(distance):
                verb = t('最大端点位移', 'maximum endpoint displacement') if obj.get('kind') == 'needles' else t('位移', 'displacement')
                objects.append(f'{name} {verb} {distance:.2f} mm')
            else:
                verbs = {'added': t('新增', 'added'), 'deleted': t('删除', 'deleted'),
                         'reoriented': t('方向或归属改变', 'orientation or ownership changed')}
                if obj.get('operation') in verbs:
                    objects.append(f"{name} {verbs[obj['operation']]}")
        observation = t('；'.join(objects), '; '.join(objects)) or t('已记录本次提交。', 'This submission is recorded.')
        pair = _guidance_pair(evidence)
        focus_refs = [str(pair[k]) for k in ('first_id', 'second_id')] if pair else []
        steps = []
        state = 'geometry_review' if pair else 'dose_review'
        if evidence.get('superseded'):
            return {'state': 'historical', 'title': t('这条反馈已不是当前规划，请看最新编辑。', 'Use the latest edit: this feedback is historical.'),
                    'observation': observation, 'meaning': t('后续操作已改变几何，以下只保留当时的记录。', 'Later edits changed geometry; this is a record of the earlier findings.'),
                    'recommendation': t('先查看最新编辑卡片，不要按这条旧建议操作。', 'Check the latest edit card; do not act on this older advice.'),
                    'verification': '', 'limitation': '', 'findings': [], 'steps': [], 'focus_refs': [], 'primary_action': 'details'}
        findings = []
        count = max(1, int(dose.get('edit_count') or 1))
        if dose.get('comparable'):
            hot_key = 'v150' if number(delta.get('v150')) and abs(delta['v150']) >= .005 and (not number(delta.get('v200')) or abs(delta['v200']) < .005) else 'v200'
            for key, label in [('v100', t('靶区覆盖 V100', 'Target coverage V100')),
                               ('d90', 'D90'), (hot_key, t(f'高剂量体积 {hot_key.upper()}', f'High-dose volume {hot_key.upper()}'))]:
                value = delta.get(key)
                before, after = (dose.get('before') or {}).get(key), (dose.get('after') or {}).get(key)
                if not all(number(v) for v in (value, before, after)):
                    continue
                unit = t('个百分点', 'pp') if key.startswith('v') else 'Gy'
                change = t('变化小于 0.01 的显示精度', 'change below the 0.01 display precision') if abs(value) < .005 else f'{value:+.2f} {unit}'
                findings.append(f'{label}: {before:.2f} → {after:.2f} ({change})')
            for row in (dose.get('oar_changes') or [])[:1]:
                if all(number(row.get(k)) for k in ('before', 'after', 'delta')):
                    findings.append(f"{row['organ']} {row['metric']}: {row['before']:.2f} → {row['after']:.2f} ({row['delta']:+.2f} Gy)")
        if pair:
            changed = pair.get('change') in ('new', 'worsened')
            kind = t('针道', 'needles') if pair.get('kind') == 'needle_pairs' else t('粒子', 'seeds')
            subject = f"{pair['first_id']} ↔ {pair['second_id']}"
            title = t(f'先处理这对{kind}的间距：{subject}。', f'Check the spacing of these {kind} first: {subject}.')
            if not changed:
                title = t(f'间距有改善但还需复核：{subject}。', f'Spacing improved but still needs review: {subject}.') if pair.get('change') == 'improved' else t(f'本次未新增这个问题，但原有间距仍需处理：{subject}。', f'This is not a new problem; the existing spacing still needs review: {subject}.')
            exact = pair.get('clearance_basis') == 'finite_parallel_cylinders'
            gap, minimum = pair.get('surface_clearance_mm'), pair.get('minimum_clearance_mm')
            label = t('实体表面间隙', 'finite surface gap') if exact else t('轴线模型间隙下界', 'axis-model clearance bound')
            measure = f'{label} {gap:.2f} mm' if number(gap) else t('当前间隙尚不可量化', 'the current gap cannot be quantified')
            prior = pair.get('previous_distance_mm')
            if number(gap) and number(prior):
                measure += t(f'（编辑前 {prior:.2f} mm）', f' (before {prior:.2f} mm)')
            if number(minimum):
                measure += t(f'；配置要求至少 {minimum:.2f} mm。', f'; the configured minimum is {minimum:.2f} mm.')
            meaning = measure + ' ' + (t('这次编辑后该对间距新增违规或加重；先解决几何，再判断剂量取舍。', 'The pair is newly conflicting or worse after this edit; address geometry before judging the dose trade-off.') if changed else t('改善不等于已经满足间距要求；也不把编辑前已有的问题算作本次造成。', 'Improvement does not establish clearance, and pre-existing problems are not attributed to this edit.'))
            recommendation = t('先查看这对对象的标注，确认是否是你想保留的调整。', 'Locate the marked pair first and check whether this is the adjustment you intended.')
            steps.append({'action': 'focus', 'label': t('查看这对对象的间距', 'Locate this spacing issue'), 'refs': focus_refs})
            edited_seed = next((obj for obj in changes if obj.get('kind') == 'seeds' and obj.get('id') in focus_refs and obj.get('operation') != 'deleted'), None)
            if changed and edited_seed:
                recommendation += t('若要保留本次调整，可先寻找并预览局部间距候选，再决定是否应用。', 'To keep the adjustment, inspect local spacing candidates before deciding whether to apply one.')
                steps.append({'action': 'spacing', 'object_id': edited_seed['id'], 'label': t('寻找局部间距候选', 'Find local spacing candidates')})
            if evidence.get('restore_token'):
                recommendation += t('若是误拖，先预览编辑前位置，再决定是否恢复。', 'If it was an unintended drag, preview the pre-edit position before deciding whether to restore it.')
                steps.append({'action': 'preview', 'label': t('先预览原位置（不修改）', 'Preview the prior position first')})
            verification = t('保存修正后，确认这对对象的间距问题是否消除，再重算剂量核对覆盖、热点及器官受量。', 'After saving a correction, check that this pair clears the spacing check, then recompute dose to review coverage, hot spots and organ dose.')
            limitation = t('间隙不足量不是建议拖动量；原位置和局部候选都不等于剂量最优或已获临床认可。', 'A clearance shortfall is not a prescribed displacement; neither the old position nor a local candidate is dose-optimal or clinically approved.')
        elif not dose.get('comparable'):
            if dose.get('after'):
                title = t('剂量已更新，但不能补出这次调整的“前后好坏”。', 'Dose is current, but this edit has no valid before/after verdict.')
                meaning = t('缺少同一规划、相同解剖和计算配置的有效编辑前剂量；再次重算不能补造过去的结果。', 'A valid pre-edit dose for the same plan, anatomy and configuration is missing; recomputing cannot recreate the past result.')
                recommendation = t('先复核当前剂量，把这份有效结果作为下一次调整的比较基线；不用为补前值而重复重算。', 'Review the current dose and use that valid result as the next edit baseline; do not recompute just to invent a missing baseline.')
                steps.append({'action': 'details', 'label': t('查看当前结果与缺失的基线', 'Review current results and baseline status')})
            else:
                title = t('几何已保存；下一步先确认剂量影响。', 'Geometry is saved; check its dose impact next.')
                meaning = t('相关间距检查未见新增或加重；当前几何还没有有效的新剂量，不能据旧 DVH 说变好或变坏。', 'Related spacing checks found no new or worsened conflicts, but this geometry has no valid new dose; an old DVH cannot establish improvement or deterioration.')
                missing_baseline = dose.get('comparison_reason') in ('baseline_dose_unavailable', 'anatomy_baseline_missing', 'anatomy_changed', 'configuration_changed', 'planning_changed', 'planning_identity_missing')
                recommendation = t('先计算当前剂量，核对当前实测结果；缺少有效前值时只能建立后续基线，不能判断刚才这一步的剂量好坏。', 'Compute the current dose and review its measurements; without a valid baseline this can establish a future baseline, not a dose verdict on the last edit.') if missing_baseline else t('点击“重算剂量并比较”；结果就绪后，本卡片会补充实际变化，不必重复询问。', 'Choose Recompute and compare; this card will receive measured changes when available, without repeating your question.')
                steps.append({'action': 'dose', 'label': t('重算剂量并比较', 'Recompute and compare')})
            verification = t('下一次保存调整后，比较同一基线下的覆盖、热点、器官受量及几何检查，而不是只看评分。', 'After the next saved edit, compare coverage, hot spots, organ dose and geometry against the same baseline, not score alone.')
            limitation = t('未发现新增相关间距问题，不表示整个规划没有问题或已经安全。', 'No new related spacing conflict does not mean the entire plan is problem-free or safe.')
        else:
            v100, v200, d90, v150 = delta.get('v100'), delta.get('v200'), delta.get('d90'), delta.get('v150')
            coverage_down = (number(v100) and v100 <= -.005) or (number(d90) and d90 <= -.005)
            coverage_up = number(v100) and v100 >= .005
            hotspots_up = (number(v200) and v200 >= .005) or (number(v150) and v150 >= .005)
            organ_rise = next((r for r in dose.get('oar_changes', []) if number(r.get('delta')) and r['delta'] >= .005), None)
            title = t('这次有明确取舍，先看代价再决定保留。', 'There is a measured trade-off; review the cost before deciding to keep it.') if coverage_down or hotspots_up or organ_rise else t('已有可比结果，按你的调整目标核对是否值得保留。', 'Comparable results are ready; check them against your intended adjustment.')
            parts = []
            if number(v100) and abs(v100) >= .005:
                parts.append(t(f"覆盖率 V100 {'增加' if coverage_up else '减少'} {abs(v100):.2f} 个百分点", f"V100 {'increased' if coverage_up else 'decreased'} by {abs(v100):.2f} pp"))
            if number(d90) and abs(d90) >= .005:
                parts.append(t(f"D90 {'增加' if d90 > 0 else '减少'} {abs(d90):.2f} Gy", f"D90 {'increased' if d90 > 0 else 'decreased'} by {abs(d90):.2f} Gy"))
            for key, value in [('V150', v150), ('V200', v200)]:
                if number(value) and abs(value) >= .005:
                    parts.append(t(f"高剂量体积 {key} {'增加' if value > 0 else '减少'} {abs(value):.2f} 个百分点", f"{key} {'increased' if value > 0 else 'decreased'} by {abs(value):.2f} pp"))
            if organ_rise:
                parts.append(t(f"{organ_rise['organ']} {organ_rise['metric']} 增加 {organ_rise['delta']:.2f} Gy", f"{organ_rise['organ']} {organ_rise['metric']} increased by {organ_rise['delta']:.2f} Gy"))
            meaning = ('；'.join(parts) + '。') if zh and parts else '; '.join(parts) + '.' if parts else t('所列指标没有达到显示精度的变化，或缺少这些指标；不能据此假定无影响。', 'Listed changes are below display precision or these metrics are missing; this does not establish no impact.')
            if count > 1:
                meaning += t(f'这些剂量差值覆盖 {count} 次编辑，不能只归因于刚才一步。', f' These dose differences cover {count} edits, not just the last move.')
            if coverage_down:
                decreasing = 'V100' if number(v100) and v100 <= -.005 else 'D90'
                recommendation = t(f'如果你的目标是提高覆盖，这次 {decreasing} 的方向与目标相反；先复核低剂量区域，再决定是否保留。', f'If your aim was improved coverage, {decreasing} moved in the opposite direction; inspect the low-dose region before keeping the adjustment.')
            elif coverage_up and (hotspots_up or organ_rise):
                recommendation = t('如果目的是提高覆盖，先复核同时增加的热点或器官受量是否符合已确认的病例约束；不能只凭 V100 上升保留。', 'If your aim was coverage, first review the increased hot spots or organ dose against confirmed case constraints; a V100 increase alone is not a reason to keep it.')
            elif hotspots_up or organ_rise:
                recommendation = t('先复核增加的高剂量体积或器官受量，以及已确认的病例约束，再决定是否保留这组调整。', 'Review the increased high-dose volume or organ dose and confirmed case constraints before keeping this adjustment sequence.')
            else:
                recommendation = t('核对这些变化是否符合你这一步的目标，并展开器官差值检查代价；不要把评分升高当作全部改善。', 'Check whether these changes match your intended goal and review organ-dose differences for costs; a higher score is not overall improvement.')
            steps.append({'action': 'details', 'label': t('展开指标与器官取舍', 'Review metric and organ-dose trade-offs')})
            verification = t('保留后继续调整时，使用当前有效剂量作为基线；恢复几何后必须重算，不能沿用这份剂量。', 'Use the current valid dose as the baseline for further edits; restoring geometry requires dose recomputation.')
            limitation = t('此处只列出部分器官指标；剂量变化不等于临床通过，也未建立模型噪声或显著性阈值。', 'Only a subset of organ metrics is shown; dose changes are not clinical approval, and no model-noise or significance threshold is established.')
        resolved = int(evidence.get('resolved_conflicts') or 0)
        if resolved and not pair:
            observation += t(f'；已消除 {resolved} 组相关间距问题。', f'; {resolved} related spacing conflicts resolved.')
        existing = int(evidence.get('existing_conflict_count') or 0)
        if existing and not pair:
            observation += t(f'另有 {existing} 组原有相关间距问题未归因于本次操作。', f' {existing} pre-existing related spacing conflicts are not attributed to this edit.')
        return {'state': state, 'title': title, 'observation': observation,
                'meaning': meaning, 'recommendation': recommendation, 'verification': verification,
                'limitation': limitation, 'findings': findings, 'steps': steps[:3],
                'focus_refs': focus_refs, 'primary_action': steps[0]['action'] if steps else 'details'}

    copies = {'zh': localized(True), 'en': localized(False)}
    return {'schema_version': 1, **copies['zh' if language == 'zh' else 'en'], 'localized': copies}


def decision_summary(evidence, rows, language='en'):
    """Measured trade-offs, never a fabricated clinical or causal verdict."""
    zh = language == 'zh'
    dose = evidence.get('dose') or {}
    count = int(dose.get('edit_count') or 1)
    new = int(evidence.get('new_conflict_count') or 0)
    worse = int(evidence.get('worsened_conflict_count') or 0)
    conflicts = [p for p in evidence.get('conflicts', []) if p.get('change') in ('new', 'worsened')]
    primary = conflicts[0] if conflicts else None
    highlights = [r for r in rows if r.get('key') in ('v100', 'v200', 'd90')]
    if dose.get('comparable'):
        # Include an observed OAR increase before the score, not a volume list.
        organs = [r for r in rows if str(r.get('key', '')).startswith('oar:') and r.get('delta', 0) > 0]
        highlights = (highlights[:2] + organs[:1]) if organs else highlights[:3]
    else:
        highlights = []
    if new or worse:
        title = (f'优先处理本次新增 {new} 组、加重 {worse} 组间距问题。' if zh
                 else f'Inspect {new} new and {worse} worsened spacing conflicts first.')
    elif dose.get('comparable') and highlights:
        def label(row):
            return f"{row['metric']} {'+' if row['delta'] >= 0 else ''}{row['delta']:.2f} {row['unit']}"
        title = ('本次调整序列的实测变化：' if zh and count > 1 else '本次编辑的实测变化：' if zh
                 else 'Measured edit-sequence changes: ' if count > 1 else 'Measured edit changes: ')
        title += '；'.join(label(row) for row in highlights)
    elif evidence.get('resolved_conflicts'):
        title = (f"消除了 {evidence['resolved_conflicts']} 组相关间距问题；剂量影响单独核对。" if zh
                 else f"Resolved {evidence['resolved_conflicts']} related spacing conflicts; dose impact is a separate assessment.")
    else:
        title = ('编辑已保存，未发现新增或加重的相关间距问题。' if zh
                 else 'Edit saved; no new or worsened related spacing conflicts were found.')
    return {'title': title, 'primary_pair': primary, 'highlights': highlights,
            'attribution': 'edit_sequence' if count > 1 else 'single_edit', 'edit_count': count,
            'dose_status': 'comparable' if dose.get('comparable') else 'current_without_baseline' if dose.get('after') else 'awaiting_recomputation',
            'clinical_status': 'not_assessed', 'movement_status': 'no_dose_optimized_position',
            'geometry_status': 'attention' if new or worse else 'no_new_or_worsened_conflicts'}


def overview(agent):
    """Bounded, read-only HUD projection; never hydrate arrays or run geometry QA.

    Availability is not clinical approval. Missing/cold state remains unknown,
    and metrics belonging to stale geometry are never advertised as current.
    """
    if agent is None or not hasattr(agent, 'memory'):
        return {'available': False, 'stages': [], 'metrics': {}}
    mem = agent.memory.retrieve
    artifacts = mem('manual_artifact_status') or {}
    if not isinstance(artifacts, dict):
        artifacts = {}
    def present(*keys):
        return any(mem(key) is not None for key in keys)
    def status(key, exists):
        recorded = _artifact_state(artifacts, key)
        if recorded in ('stale', 'running', 'failed'):
            return recorded
        if recorded in ('current', 'completed', 'ready'):
            return 'available'
        return 'available' if exists else 'unknown'
    dose_current = (present('dose_distribution', 'dose_distribution_gy')
                    and not mem('manual_geometry_only')
                    and status('dose', True) == 'available'
                    and status('dvh', True) == 'available')
    metrics = mem('dose_metrics') or mem('metrics') or {}
    if isinstance(metrics, dict) and isinstance(metrics.get('metrics'), dict):
        metrics = metrics['metrics']
    normalized = {}
    highest_oar = None
    oar_rows = []
    if dose_current and isinstance(metrics, dict):
        for key in ('v100', 'd90', 'v200', 'plan_score'):
            value = metrics.get(key)
            if isinstance(value, dict):
                value = value.get('value')
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                if key.startswith('v'):
                    from web.server_support import _volume_metric_as_fraction
                    fraction = _volume_metric_as_fraction(metrics, key)
                    if fraction is not None:
                        normalized[key] = fraction * 100
                else:
                    normalized[key] = float(value)
        organs = metrics.get('oar_metrics') or {}
        for name, row in organs.items() if isinstance(organs, dict) else []:
            value = row.get('dmax') if isinstance(row, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                oar_rows.append({'organ': str(name), 'dmax': float(value)})
                if highest_oar is None or value > highest_oar['dmax']:
                    highest_oar = {'organ': str(name), 'dmax': float(value)}
    stages = [
        ('ct', 'available' if present('ct_image', 'image') or bool(mem('ct_path')) else 'unknown'),
        ('ctv', 'available' if present('ctv_array', 'ctv_mask', 'ctv_label_data') else 'unknown'),
        ('oar', 'available' if present('oar_array', 'oar_mask', 'oar_label_data') else 'unknown'),
        ('geometry', 'available' if (mem('total_seeds') or 0) > 0
         and (mem('num_trajectories') or 0) > 0 else 'unknown'),
        ('dose', 'available' if dose_current else 'stale' if present('dose_distribution', 'dose_distribution_gy')
         else status('dose', False) if status('dose', False) != 'available' else 'unknown'),
        ('quality_check', status('quality_check', False)),
        ('surgical_guide', status('surgical_guide', False)),
        ('report', status('report', bool(mem('report_form')))),
    ]
    oar_rows.sort(key=lambda row: row['dmax'], reverse=True)
    config = mem('plan_config') or {}
    target = config.get('DVH_rate') if isinstance(config, dict) else None
    coverage_target = float(target) * 100 if isinstance(target, (int, float)) and not isinstance(target, bool) and 0 < target <= 1 else None
    return {'available': True, 'planning_id': mem('active_planning_id') or mem('planning_run_id'),
            'planning_version': mem('manual_plan_version'), 'dose_current': bool(dose_current),
            'metrics': normalized, 'highest_recorded_oar': highest_oar,
            'recorded_oars': oar_rows[:5], 'recorded_oar_count': len(oar_rows),
            'coverage_target_percent': coverage_target, 'coverage_target_source': 'plan_config.DVH_rate' if coverage_target else None,
            'stages': [{'key': key, 'state': value} for key, value in stages]}


def timeline_projection(training, limit=40):
    """Small HUD history; never copy geometry arrays or inverse/restore tokens."""
    events = training.get('events') or []
    counts = {}
    for key, value in (training.get('event_counts') or {}).items():
        try:
            counts[str(key)] = max(0, int(value))
        except (ValueError, TypeError, OverflowError):
            continue
    if not counts:
        for event in events:
            key = str(event.get('type') or 'ui.event')
            counts[key] = counts.get(key, 0) + 1
    rows = []
    for event in events[-limit:]:
        detail = event.get('detail') or {}
        evidence = (detail.get('edit_evidence') or {}) if detail.get('commit_status') == 'committed' else {}
        info = interaction(evidence) if evidence else {}
        row = {key: event.get(key) for key in ('event_id', 'ts', 'type', 'monitor_run_id')}
        row.update(status=detail.get('status'), step=detail.get('step'),
                   label=str(event.get('label') or '')[:200], severity=info.get('severity', 'warning' if detail.get('status') == 'failed' else 'info'))
        dose = evidence.get('dose') or {}
        if dose.get('after'):
            row['dose_sample'] = {key: dose.get(key) for key in ('series_key', 'comparable', 'before', 'after')}
            row['dose_sample'].update(planning_id=evidence.get('planning_id'), revision=evidence.get('after_version'))
        rows.append(row)
    return {'schema_version': 3, 'events': rows, 'event_counts': counts,
            'event_count': sum(counts.values()), 'retained_event_count': len(events),
            'returned_event_count': len(rows), 'dropped_event_count': training.get('dropped_event_count', 0)}


def checkpoint(evidence, event, language='en'):
    """Deliver an edit without a second network round trip or an LLM call."""
    event = {**event, 'detail': {**(event.get('detail') or {}), 'edit_evidence': evidence}}
    image = screenshot(evidence, event.get('event_id'))
    if ((evidence.get('dose') or {}).get('after') and evidence.get('geometry_event_id')
            and evidence['geometry_event_id'] != event.get('event_id')):
        image = {'target': 'dvh', 'views': ['dvh'], 'checkpoint_id': event.get('event_id'),
                 'planning_id': evidence['planning_id'], 'planning_version': evidence['after_version'],
                 'question': '本次重算的 DVH' if language == 'zh' else 'DVH from this recomputation'}
    return {'success': True, 'event': event, 'monitor_run_id': evidence.get('monitor_run_id'),
            'language': language, 'interaction': interaction(evidence, language),
            'feedback': describe(evidence, language),
            'suggested_screenshot': image}
