"""Bounded, server-owned edit evidence. No model inference or dose prediction."""
import copy
import hashlib
import json
import math
from types import SimpleNamespace


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
            and not any(stale.get(k) in ('stale', 'outdated') for k in ('dose', 'dvh')),
        'config': copy.deepcopy(memory.retrieve('plan_config') or {}),
        'anatomy_key': [(versions.get(k), id(memory.retrieve(k))) for k in anatomy_keys],
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
        snapshot['seed_pairs'] = support._seed_interference_report(agent,
            snapshot['geometry']['seeds'], snapshot['geometry']['needles'],
            focus_ids=ids, max_pairs=None)['close_pairs']
        snapshot['needle_pairs'] = []
        needles = snapshot['geometry']['needles']
        minimum = float(config.get('needle_diameter_mm') or 1.2) + float(config.get('needle_clearance_mm') or 1.0)
        for i, left in enumerate(needles):
            for right in needles[i+1:]:
                if not ids.intersection((str(left['id']), str(right['id']))):
                    continue
                distance = support._segment_segment_distance(left['points'][0], left['points'][-1], right['points'][0], right['points'][-1])
                if distance < minimum:
                    snapshot['needle_pairs'].append({'first_id': left['id'], 'second_id': right['id'],
                        'distance_mm': distance, 'minimum_distance_mm': minimum})
        if side == 0:
            before = snapshot
        else:
            after = snapshot
    conflicts = []
    resolved = 0
    for key, distance_key in (('seed_pairs', 'surface_clearance_mm'), ('needle_pairs', 'distance_mm')):
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
    conflicts.sort(key=lambda p: (p['change'] == 'existing', p.get('surface_clearance_mm', p.get('distance_mm', 0))))
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
    comparable = bool(before['metrics_current'] and after['metrics_current']
                      and before.get('anatomy_key') == after.get('anatomy_key')
                      and before.get('config') == after.get('config'))
    organ_changes = []
    if comparable:
        for organ, row in before.get('oar_metrics', {}).items():
            for key, value in row.items():
                current = after.get('oar_metrics', {}).get(organ, {}).get(key)
                if current is not None:
                    organ_changes.append({'organ': organ, 'metric': key, 'before': value,
                                          'after': current, 'delta': current - value})
        organ_changes.sort(key=lambda row: abs(row['delta']), reverse=True)
    return {'comparable': comparable, 'before': before['metrics'] if before['metrics_current'] else {},
            'after': after['metrics'] if after['metrics_current'] else {},
            'score_status': after.get('score_status'),
            'oar_changes': organ_changes[:4], 'oar_metric_comparison_count': len(organ_changes),
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
        label = '表面间隙' if pair['kind'] == 'seed_pairs' else '针道距离'
        lines.append(f"{status}：{pair['first_id']} ↔ {pair['second_id']}，{label} {value:.2f} mm。" if zh
                     else f"{pair['change']}: {pair['first_id']} ↔ {pair['second_id']}, {'surface clearance' if pair['kind'] == 'seed_pairs' else 'needle distance'} {value:.2f} mm.")
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
        code = evidence['restore_token']
        lines.append(f"是否撤销这次编辑？回复“复位 {code}”恢复本次编辑前的几何，或回复“保留 {code}”。复位后剂量仍需重算；原位置不等于已验证的安全位置。" if zh
                     else f"Undo this edit? Reply 'undo {code}' to restore its prior geometry, or 'keep {code}'. Dose must be recomputed afterward; the prior position is not a verified safe position.")
        for obj in display_objects[:2]:
            if obj.get('return_vector_mm'):
                vector = ', '.join(f'{v:+.2f}' for v in obj['return_vector_mm'])
                lines.append(f"{obj['id']} 返回原位的患者坐标位移为 [{vector}] mm（非屏幕左右方向，也不是剂量最优方向）。" if zh
                             else f"{obj['id']} return displacement in patient coordinates: [{vector}] mm; not screen directions or a dose-optimal direction.")
    return '\n\n'.join(lines)


def screenshot(evidence, event_id):
    ids = []
    for p in (p for p in evidence.get('conflicts', [])
              if p['change'] in ('new', 'worsened')):
        ids.extend((p['first_id'], p['second_id']))
        if len(ids) >= 4:
            break
    ids.extend(x['id'] for x in evidence.get('changed_objects', [])
               if x['operation'] not in ('deleted', 'reoriented')
               and not x.get('dependent_on_needle'))
    ids = list(dict.fromkeys(ids))[:8]
    if not ids:
        return None
    return {'target': 'viewer-3d', 'views': ['viewer-3d'], 'object_ids': ids,
            'checkpoint_id': event_id, 'planning_id': evidence['planning_id'],
            'planning_version': evidence['after_version'], 'geometry_key': evidence['geometry_key'],
            'visual_purpose': 'locate', 'annotation_policy': 'required',
            'edit_evidence': {'changed_objects': evidence.get('changed_objects', [])[:8]},
            'question': ' / '.join(ids), 'hide_unrelated': False,
            'focus': {'kind': 'auto', 'padding': 0.5}}
